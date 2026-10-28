"""Concrete CB-envelope and real paged neural/LoRA contracts.

The sampler below uses an explicitly fake decision engine and a synthetic SQL
catalog. No scorer, encoder, planner, gradient or restore operation is mocked.
These are interface checks, not live-core/strength/formal-training evidence.
"""
from copy import deepcopy,copy
from dataclasses import asdict,replace
import gc
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import torch
from torch.distributions import Categorical

from tests.fixtures import request as payload
from ygo_kito.build_contracts import BuildTask,DeckParts,digest
from ygo_kito.build_semantics import route_task
from ygo_kito.contracts import DecisionRequest,validate_selection
from ygo_kito.cpu_training import CpuTrainer,CpuTrainingConfig
from ygo_kito.duel_model import DuelModelConfig,PlayerEncoder,FEATURE_VERSION,parameter_digest
from ygo_kito.duel_planning import plans_from_construction,DuelPlanner,PlanningBudget
from ygo_kito.effect_duel import public_card_facts
from ygo_kito.hierarchical_policy import score_requests,sample_index
from ygo_kito.lora import AdapterConfig,AdapterSession,tensor_digest
from ygo_kito.lora_group import ppo_inputs,ppo_loss,output
from ygo_kito.validation import ContractError

ROOT=Path(__file__).resolve().parents[1]


def construction_fixture():
    raw=json.loads((ROOT/'configs/build-semantic-engineering-v4.json').read_text(encoding='utf-8'))
    raw.update(task_id='original-constraint-goal',pool=list(range(1,44)),candidate_budget=2,
        sizes=dict(main=40,extra=2,side=0),requirements=[dict(zone=z,card_id=c,minimum=1,maximum=3)
            for z,c in (('main',1),('main',2),('extra',42),('extra',43))])
    raw['goal']=dict(kind='deck_constraints',constraints=[dict(id='monsters',zones=['main'],
        predicate=dict(field='type_all',value=1),minimum=40,maximum=40)],preferences=[])
    original=BuildTask.from_dict(raw);deck=DeckParts(tuple(range(1,41)),(42,43),())
    routes=[]
    for target in (42,43):
        child=deepcopy(raw);child['task_id']='derived-'+str(target)
        child['goal']['route_goal']=dict(kind='synchro_summon',card_id=target,
            starting_conditions=dict(player=0,turn=1,requires_opening_hand=[1,2]))
        derived=BuildTask.from_dict(child);native=route_task(derived)
        responses=[dict(player=0,request_sha256=digest(['fixture',target]),action_id='private-native-action')]
        proof=dict(status='verified_success',card_list_legal=True,task_sha256=native.sha256,
            deck_sha256=digest(deck.to_dict()),starting_condition=native.goal['starting_conditions'],
            responses=responses,trajectory_sha256=digest(responses),core_event_kinds=[62,63],
            route_evidence=dict(conditional_only=True,versions=native.environment['versions'],
                final_observation=dict(opponent_hand=[987654321]),private_selection_key_audit_only='private-seed-secret',
                exploration=dict(discovered_intents=[dict(operation='summon',card_ids=[1]),
                    dict(operation='special_summon',card_ids=[target])])),seed_audit_only=123456789)
        routes.append(dict(task=derived.to_dict(),proof=dict(status='constraints_and_route_verified',
            task_sha256=derived.sha256,deck_sha256=digest(deck.to_dict()),native_route=proof,effect_execution_verified=True)))
    result=dict(best=dict(deck=deck.to_dict()),goal_sha256=digest(original.goal),
        basic_cb=dict(kind='basic_cb_inference_after_construction',status='routes_inferred',task_sha256=original.sha256,
            subject_deck_sha256=digest(deck.to_dict()),routes=routes))
    return original,deck,result


class BasicCbRuntimeShapeTests(unittest.TestCase):
    def test_original_constraint_goal_yields_its_own_derived_routes_and_strips_audit(self):
        task,deck,result=construction_fixture();before=task.to_dict()
        self.assertNotIn('card_id',task.goal);self.assertNotIn('route_goal',task.goal)
        plans=plans_from_construction(task,result,deck=deck)
        self.assertEqual({p.goal_card for p in plans},{42,43})
        self.assertTrue(all(p.opening==(1,2) for p in plans))
        self.assertEqual(task.to_dict(),before)
        for plan in plans:
            self.assertEqual(set(asdict(plan)),{'plan_id','goal_card','opening','steps','effect_descriptions'})
            self.assertNotIn('private-seed-secret',repr(plan));self.assertNotIn('987654321',repr(plan))
            self.assertNotIn('private-native-action',repr(plan));self.assertNotIn('123456789',repr(plan))

    def test_inferred_status_without_verified_recorded_route_stays_unknown(self):
        task,deck,result=construction_fixture()
        for row in result['basic_cb']['routes']:row['proof']['status']='bounded_inference_unknown'
        self.assertEqual(plans_from_construction(task,result,deck=deck),())
        for row in result['basic_cb']['routes']:
            row['proof']['status']='constraints_and_route_verified'
            row['proof']['native_route']['responses']=[]
        self.assertEqual(plans_from_construction(task,result,deck=deck),())

    def test_task_deck_and_original_goal_mismatches_cannot_borrow_another_cb(self):
        task,deck,result=construction_fixture()
        for mutate in (
            lambda r:r['basic_cb'].update(subject_deck_sha256='0'*64),
            lambda r:r['basic_cb'].update(task_sha256='0'*64),
            lambda r:r['basic_cb']['routes'][0]['proof'].update(task_sha256='0'*64),
            lambda r:r['basic_cb']['routes'][0]['proof']['native_route'].update(deck_sha256='0'*64),
            lambda r:r['basic_cb']['routes'][0]['task']['goal']['constraints'][0].update(minimum=39),
        ):
            bad=deepcopy(result);mutate(bad)
            with self.assertRaises(ContractError):plans_from_construction(task,bad,deck=deck)
        different=replace(deck,main=tuple(reversed(deck.main)))
        with self.assertRaises(ContractError):plans_from_construction(task,result,deck=different)


def decision(count,ident):
    raw=payload();raw['context']['seed']=None;raw['decision_id']=ident
    raw['observation']['cards']=[dict(ref='own-'+str(c),owner=0,controller=0,
        zone='hand' if c==1 else 'graveyard',visibility='observer',card_id=c) for c in range(1,12)]
    raw['prompt']=dict(message=15,minimum=1,maximum=1)
    raw['actions']=[dict(action_id='select-'+str(c),kind='select',card_refs=['own-'+str(c)]) for c in range(1,count+1)]
    return DecisionRequest.from_dict(raw)


class FakeDecisionEngine:
    def __init__(self,requests):self.requests=iter(requests);self.turn=1;self.events=[];self.outcome=None;self.pending=None
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def next_decision(self):
        self.pending=next(self.requests,None)
        if self.pending is None:self.events=[dict(kind=5)];self.outcome=dict(winner=0)
        return self.pending
    def submit(self,selection):validate_selection(self.pending,selection)


class PagedLoraRuntimeTests(unittest.TestCase):
    def test_sampler_full_distribution_gradient_and_restored_next_lora_update(self):
        cfg=CpuTrainingConfig(model=DuelModelConfig(width=8,card_width=4,heads=2,feedforward=16,
            max_actions=4,max_tokens=64),game_seeds=(100,101),batch_size=2)
        trainer=CpuTrainer(cfg,list(range(1,12)));base=deepcopy(trainer.model)
        session=AdapterSession(trainer.model,AdapterConfig('paged-duel','duel',('policy_head.0','value_head.2'),
            rank=1,max_updates=3),dict(base_version='fixture-base',feature_version=FEATURE_VERSION,context_sha256='a'*64))
        requests=(decision(11,'large'),decision(2,'small'))
        with self.assertRaises(ContractError):trainer.encoder.batch(requests)  # reproduces the old real boundary
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=root/'engine-src/database/locales/zh-CN/cards.cdb';db.parent.mkdir(parents=True)
            with sqlite3.connect(db) as connection:
                connection.execute('create table datas(id integer,type integer,level integer,atk integer,def integer)')
                connection.executemany('insert into datas values(?,?,?,?,?)',[(i,17,4,i*500,1000) for i in range(1,12)])
            connection.close()
            facts=public_card_facts(root);profile=dict(decks=[list(range(1,12)),[1]],extras=[[],[]])
            budget=PlanningBudget(nodes=128,roots=32,seconds=1)
            trainer.model.eval()
            with torch.no_grad():
                raw,_=score_requests(trainer.model,trainer.encoder,[requests[0]])
                oracle,_=DuelPlanner(own_deck=tuple(profile['decks'][0]),facts=facts,budget=budget).evaluate(requests[0],raw[0])
            # Use the real distribution/RNG to exercise a selected leaf in the
            # final page. No forced action, patched scorer or truncated prefix.
            for seed in range(128):
                generator=torch.Generator().manual_seed(seed);state=generator.get_state()
                index,_=sample_index(oracle,generator=generator,max_actions=4)
                if index>=8:trainer.policy_rng.set_state(state);break
            else:self.fail('fixture failed to select a final-page leaf')
            def sample():
                return trainer.sample_episode(root,profile,engine_factory=lambda *a,**kw:FakeDecisionEngine(requests),planning_budget=budget)
            episode=sample();self.assertGreaterEqual(episode['steps'][0]['action_index'],8)
            self.assertTrue(any(v!=0 for v in episode['steps'][0]['planning']['bias']))
            values=ppo_inputs(episode,trainer,session)
            self.assertEqual(sorted(len(r.actions) for r in values['requests']),[2,11])
            logits,predicted=score_requests(session.model,values['encoder'],values['requests'])
            probe=output(session.model,values)  # existing LoRA disable/restore probe uses the same paged inputs
            torch.testing.assert_close(probe['0'],logits.detach(),rtol=0,atol=0)
            torch.testing.assert_close(probe['1'],predicted.detach(),rtol=0,atol=0)
            wide=PlayerEncoder(list(range(1,12)),replace(cfg.model,max_actions=32))
            flat,flat_values=session.model(wide.batch(values['requests']))
            torch.testing.assert_close(logits,flat,rtol=1e-5,atol=1e-6)
            torch.testing.assert_close(predicted,flat_values,rtol=1e-5,atol=1e-6)
            planned=logits+values['planning_bias'];dist=Categorical(logits=planned)
            torch.testing.assert_close(dist.log_prob(values['actions']),values['old_log_probs'],rtol=1e-5,atol=1e-6)
            torch.testing.assert_close(dist.probs.sum(1),torch.ones(2))
            large=next(i for i,r in enumerate(values['requests']) if len(r.actions)==11)
            small=1-large;self.assertTrue((dist.probs[small,2:]==0).all())
            policy_loss=-dist.log_prob(values['actions'])[large]
            gradient=torch.autograd.grad(policy_loss,logits,retain_graph=True)[0]
            self.assertTrue((gradient[large,:11].abs()>0).all())  # includes every unselected page in normalization
            parameters=tuple(session.parameters())
            paged_grads=torch.autograd.grad(policy_loss,parameters,allow_unused=True)
            flat_loss=-Categorical(logits=flat+values['planning_bias']).log_prob(values['actions'])[large]
            flat_grads=torch.autograd.grad(flat_loss,parameters,allow_unused=True)
            for paged,reference in zip(paged_grads,flat_grads):
                if reference is None:self.assertIsNone(paged)
                else:torch.testing.assert_close(paged,reference,rtol=1e-4,atol=1e-6)
            policy_before=session.weights()['policy_head.0.b'].detach().clone()
            update=session.step(ppo_loss(session,values,cfg))
            self.assertGreater(update['changed_adapter_elements'],0);self.assertEqual(session.verify_base(),parameter_digest(base))
            self.assertFalse(torch.equal(policy_before,session.weights()['policy_head.0.b']))
            receipt=session.save(root/'adapter.weights')
            restored=AdapterSession.load(base,root/'adapter.weights',session.compatibility(),receipt)
            trainer.updates=trainer.episode_cursor=session.updates  # same boundary used by CourseGameAdapter
            next_episode=sample();other=copy(trainer);other.model=restored.model
            a=ppo_inputs(next_episode,trainer,session);b=ppo_inputs(next_episode,other,restored)
            self.assertEqual([r.decision_id for r in a['requests']],[r.decision_id for r in b['requests']])
            torch.testing.assert_close(a['planning_bias'],b['planning_bias'],rtol=0,atol=0)
            first=session.step(ppo_loss(session,a,cfg));second=restored.step(ppo_loss(restored,b,cfg))
            self.assertEqual(first,second)
            self.assertEqual(tensor_digest(session.weights()),tensor_digest(restored.weights()))
            self.assertEqual(parameter_digest(session.model),parameter_digest(restored.model))
            gc.collect()  # release read-only sqlite contexts before Windows temp cleanup


if __name__=='__main__':unittest.main()
