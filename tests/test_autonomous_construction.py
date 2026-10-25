"""Synthetic CPU contracts only: no optimizer steps, engine or ability claims."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

import torch

from ygo_kito.autonomous_construction import (
    AutonomousConstructionKernel, CourseBuildEncoder, initialize_course_vocabulary,
)
from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_model import BuildModelConfig
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.build_training import BuildTrainer, BuildTrainingConfig
from ygo_kito.coordinator_model import CoordinatorTrainer, CoordinatorModelConfig
from ygo_kito.duel_model import parameter_digest
from ygo_kito.lora import AdapterConfig, AdapterSession
from ygo_kito.validation import ContractError

ROOT=Path(__file__).resolve().parents[1]


def fixture(count=36, *, initialize=True):
    raw=json.loads((ROOT/"configs/build-semantic-engineering-v4.json").read_text())
    raw.update(task_id="synthetic-course",pool=list(range(1,15)),requirements=[],
        sizes={"main":40,"extra":0,"side":0},candidate_budget=2)
    raw["goal"]={"kind":"deck_constraints","constraints":[{"id":"monsters","zones":["main"],
        "predicate":{"field":"type_all","value":1},"minimum":40,"maximum":40}],"preferences":[]}
    task=BuildTask.from_dict(raw)
    assets=BuildAssets.__new__(BuildAssets)
    assets.root=ROOT
    assets.environment=deepcopy(task.environment)
    assets.limits={}
    assets.receipt={"resources":{"cards":"a"*64,"scripts":"b"*64},"engineering_fixture":True}
    assets.rows={c:{"id":c,"alias":0,"ot":1,"type":17,"race":1<<(c%3),
        "setcode":0x2c3 if c%2 else 0x4d5,"level":4,"attribute":1,
        "atk":100*c,"def":50*c,"name":"synthetic-"+str(c),
        "desc":"Synthetic public text; no actual card effect."} for c in range(1,count+1)}
    builder=BuildTrainer(task,assets,BuildTrainingConfig(model=BuildModelConfig(
        width=8,card_width=4,heads=2,layers=1,feedforward=16,max_tokens=256),batches=1))
    if initialize:initialize_course_vocabulary(builder,assets.rows)
    coordinator=CoordinatorTrainer(CoordinatorModelConfig(hidden=4,steps=1))
    return task,assets,builder,coordinator


def kernel_fixture(count=36):
    task,assets,builder,coordinator=fixture(count)
    kernel=AutonomousConstructionKernel(builder,coordinator,assets=assets,
        host_available_ids=assets.rows,source_binding={"kind":"synthetic_host_availability_not_real_scripts",
            "catalog_sha256":"a"*64,"scripts_sha256":"b"*64},pool_limit=32,candidate_limit=8)
    return task,assets,builder,kernel


def deck_for(task,assets,variant=0):
    required={r["card_id"]:r["minimum"] for r in task.requirements if r["zone"]=="main"}
    cards=[c for c,n in required.items() for _ in range(n)]
    order=list(task.pool)
    order=order[variant:]+order[:variant]
    # Ensure the open-axis minimum, then use only independently legal copies.
    from ygo_kito.build_semantics import matches
    axis=task.goal["constraints"][-1]
    match=next(c for c in order if matches(assets.rows[c],axis["predicate"]))
    if match not in cards:cards.append(match)
    for c in order:
        while cards.count(c)<3 and len(cards)<40:cards.append(c)
    deck=DeckParts(tuple(sorted(cards)))
    assets.validate(task,deck)
    return deck


class CourseVocabularyTests(unittest.TestCase):
    def test_extension_preserves_rows_roles_optimizer_and_rng_without_updates(self):
        _,assets,builder,_=fixture(initialize=False)
        models=dict(builder.models);optimizers=dict(builder.optimizers);schedulers=dict(builder.schedulers)
        before={r:{n:v.detach().clone() for n,v in m.state_dict().items()} for r,m in models.items()}
        rng=torch.get_rng_state().clone()
        migration=initialize_course_vocabulary(builder,assets.rows,seed=812)
        self.assertTrue(torch.equal(rng,torch.get_rng_state()))
        self.assertIsInstance(builder.encoder,CourseBuildEncoder)
        self.assertEqual(builder.encoder.card_ids,tuple(range(1,37)))
        self.assertEqual(migration["initialization_seed"],812)
        self.assertFalse(migration["ability_verified"])
        for role in models:
            self.assertIs(builder.models[role],models[role]);self.assertIs(builder.optimizers[role],optimizers[role])
            self.assertIs(builder.schedulers[role],schedulers[role])
            self.assertTrue(torch.equal(builder.models[role].card.weight[:15],before[role]["card.weight"]))
            for name,value in before[role].items():
                if name!="card.weight":self.assertTrue(torch.equal(value,builder.models[role].state_dict()[name]))
            self.assertEqual(torch.count_nonzero(builder.models[role].card.weight[0]).item(),0)
            self.assertFalse(torch.equal(builder.models[role].card.weight[15],builder.models[role].card.weight[16]))
            self.assertTrue(any(p is builder.models[role].card.weight for g in optimizers[role].param_groups for p in g["params"]))
            self.assertFalse(optimizers[role].state)
        self.assertFalse(torch.equal(builder.models["build_goal"].card.weight[15:],builder.models["build_optimizer"].card.weight[15:]))
        self.assertEqual(initialize_course_vocabulary(builder,assets.rows,seed=812),migration)
        with self.assertRaises(ContractError):initialize_course_vocabulary(builder,assets.rows,seed=813)

    def test_global_vocabulary_can_exceed_local_bound_and_no_oov_padding(self):
        task,assets,builder,_=fixture(150)
        raw=task.to_dict();raw["pool"]=list(range(135,151));raw["task_id"]="unseen-local-pool"
        local=BuildTask.from_dict(raw)
        tokens,_,_=builder.encoder.encode(local,DeckParts((150,)))
        self.assertEqual(tokens[-1][0],builder.encoder.card_index[150])
        self.assertGreater(tokens[-1][0],128)
        self.assertEqual(builder.encoder.card_index[1],1)
        raw["pool"][-1]=999
        with self.assertRaises(ContractError):builder.encoder.encode(BuildTask.from_dict(raw),DeckParts(()))
        raw=local.to_dict();raw["annotations"][0]["condition"]="changed"
        with self.assertRaises(ContractError):builder.encoder.encode(BuildTask.from_dict(raw),DeckParts(()))

    def test_missing_and_forbidden_cards_filter_per_card_not_whole_catalog(self):
        _,assets,builder,_=fixture(initialize=False)
        assets.limits[36]=0
        metadata=initialize_course_vocabulary(builder,list(assets.rows)+[999])
        self.assertNotIn(36,builder.encoder.available_ids);self.assertNotIn(999,builder.encoder.available_ids)
        self.assertEqual({r["reason"] for r in metadata["excluded"]},{"forbidden","catalog_missing"})
        self.assertEqual(len(builder.encoder.available_ids),35)

    def test_vocabulary_expansion_rejects_active_lora_or_updated_optimizer(self):
        for mode in ("updated","optimizer","lora"):
            with self.subTest(mode=mode):
                _,assets,builder,_=fixture(initialize=False)
                if mode=="updated":builder.updates["build_goal"]=1
                elif mode=="optimizer":builder.optimizers["build_goal"].state[builder.models["build_goal"].card.weight]={"step":torch.tensor(1.)}
                else:AdapterSession(builder.models["build_goal"],AdapterConfig("fixture-goal","build_goal",rank=1,targets=("head.0",)),
                    {"base_version":"fixture-base","feature_version":"fixture","context_sha256":"c"*64})
                with self.assertRaises(ContractError):initialize_course_vocabulary(builder,assets.rows)


class AutonomousKernelTests(unittest.TestCase):
    def test_supported_extra_goals_are_proposals_not_engine_or_graph_proof(self):
        task,assets,builder,coordinator=fixture(initialize=False)
        assets.rows[37]=dict(assets.rows[1],id=37,type=0x800001,name="synthetic-xyz",setcode=0x6e7)
        raw=task.to_dict();raw["pool"].append(37);raw["sizes"]["extra"]=1
        task=BuildTask.from_dict(raw)
        builder=BuildTrainer(task,assets,builder.config)
        initialize_course_vocabulary(builder,assets.rows)
        kernel=AutonomousConstructionKernel(builder,coordinator,assets=assets,host_available_ids=assets.rows,
            source_binding={"kind":"synthetic-not-engine-availability"},pool_limit=32,candidate_limit=16)
        proposals=kernel.propose_tasks()
        self.assertEqual(proposals["status"],"model_ranked_tasks")
        for candidate in proposals["candidates"]:
            self.assertTrue(candidate["cb_goal_proposed"])
            self.assertEqual(candidate["task"]["goal"]["route_goal"]["kind"],"xyz_summon")
            self.assertNotIn("cb_verified",candidate)
            assets.check_task(BuildTask.from_dict(candidate["task"]))

    def test_fixed_user_goal_missing_card_is_not_silently_retargeted(self):
        task,assets,builder,coordinator=fixture(initialize=False)
        raw=task.to_dict();raw["requirements"]=[{"zone":"main","card_id":14,"minimum":1,"maximum":3}]
        builder=BuildTrainer(BuildTask.from_dict(raw),assets,builder.config)
        available=[c for c in assets.rows if c!=14]
        initialize_course_vocabulary(builder,available)
        kernel=AutonomousConstructionKernel(builder,coordinator,assets=assets,host_available_ids=available,
            source_binding={"kind":"synthetic-availability-missing-one-script"})
        self.assertEqual(kernel.select_task()["status"],"fixed_goal_card_unavailable")

    def test_open_catalog_facts_and_actual_goal_model_select_without_topic_list(self):
        _,assets,builder,kernel=kernel_fixture()
        themes=kernel.enumerate_themes()
        self.assertEqual({(t["field"],t["value"]) for t in themes},
            {("setcode",0x2c3),("setcode",0x4d5),("race_any",1),("race_any",2),("race_any",4)})
        proposals=kernel.propose_tasks()
        self.assertEqual(proposals["status"],"model_ranked_tasks")
        self.assertGreater(proposals["scored_candidate_count"],1)
        self.assertFalse(proposals["trained_ability_verified"])
        selected=kernel.select_task(proposals)
        self.assertEqual(selected["candidate_id"],max(proposals["all_scores"],key=lambda r:r["score"])["candidate_id"])
        self.assertEqual(selected["selected_model_sha256"],parameter_digest(builder.models["build_goal"]))
        self.assertTrue(set(selected["task"]["pool"])<=assets.rows.keys())
        self.assertLessEqual(len(selected["task"]["pool"]),128)
        self.assertEqual(selected["task"]["goal"]["constraints"][0],builder.task.goal["constraints"][0])

    def test_tied_missing_stale_or_modified_scores_never_choose_rule_fallback(self):
        _,_,builder,kernel=kernel_fixture()
        proposals=kernel.propose_tasks();changed=deepcopy(proposals)
        changed["candidates"][0]["model_score_uncalibrated"]+=1
        with self.assertRaises(ContractError):kernel.select_task(changed)
        with torch.no_grad():
            for p in builder.models["build_goal"].parameters():p.zero_()
        with self.assertRaises(ContractError):kernel.select_task(proposals)
        self.assertEqual(kernel.select_task()["status"],"model_selection_unresolved")
        del builder.models["build_goal"]
        with self.assertRaises((ContractError,KeyError)):kernel.propose_tasks()

    def test_explicit_rank_tries_actual_second_model_choice_and_rejects_invalid_rank(self):
        _,_,_,kernel=kernel_fixture()
        proposals=kernel.propose_tasks()
        selected=kernel.select_task(proposals,rank=1)
        self.assertEqual(selected["candidate_id"],proposals["candidates"][1]["candidate_id"])
        self.assertEqual(kernel._selection(selected).sha256,selected["candidate_id"])
        for rank in (-1,True,1.5,len(proposals["candidates"])):
            with self.subTest(rank=rank),self.assertRaises(ContractError):kernel.select_task(proposals,rank=rank)

    def test_real_graph_fill_cycle_rejects_unknown_verification_and_revises_feedback(self):
        _,assets,_,kernel=kernel_fixture()
        selection=kernel.select_task();task=BuildTask.from_dict(selection["task"])
        deck=deck_for(task,assets)
        first=kernel.run_selected(selection,base=deck,verifier=None)
        session=kernel.sessions[selection["candidate_id"]]
        old_graph=session.logic.sha256;old_goal=session.goal_sha256
        self.assertFalse(first["cb_verified"]);self.assertFalse(first["graph_execution_verified"])
        self.assertFalse(first["text_classifier_inference"])
        self.assertIn("build_goal",first["graph_model_selections"])
        self.assertEqual(first["status"],"construction_unresolved")
        second=kernel.run_selected(selection,base=deck,verifier=None,feedback=[{"source":"duel","message":"try another graph while retaining the selected objective"}])
        self.assertNotEqual(session.logic.sha256,old_graph)
        self.assertEqual(session.goal_sha256,old_goal)
        self.assertEqual(second["selected_task_sha256"],task.sha256)
        self.assertTrue(any(f["source"]=="duel" for f in session.feedback))
        self.assertFalse(second["cb_verified"])

    def test_losses_reuse_actual_models_have_gradients_and_do_not_step_or_admit_eval(self):
        _,assets,builder,kernel=kernel_fixture()
        proposals=kernel.propose_tasks();selected=kernel.select_task(proposals)
        task=BuildTask.from_dict(selected["task"])
        a,b=deck_for(task,assets),deck_for(task,assets,variant=3)
        before={r:parameter_digest(m) for r,m in builder.models.items()}
        losses=[kernel.preference_loss(proposals,selected["candidate_id"],source="synthetic_code_path_only"),
            kernel.fill_preference_loss(selected,a,b,source="synthetic_code_path_only"),
            kernel.graph_preference_loss(selected,0,role="build_goal",source="synthetic_code_path_only")]
        for result in losses:
            role=result["receipt"]["role"]
            gradients=torch.autograd.grad(result["loss"],tuple(builder.models[role].parameters()),allow_unused=True)
            self.assertTrue(any(g is not None and torch.count_nonzero(g) for g in gradients))
            self.assertFalse(result["receipt"]["optimizer_step_performed"])
            self.assertFalse(result["receipt"]["data_admission_checked"])
        self.assertEqual(before,{r:parameter_digest(m) for r,m in builder.models.items()})
        self.assertTrue(all(p.grad is None for m in builder.models.values() for p in m.parameters()))
        self.assertTrue(all(not o.state for o in builder.optimizers.values()))
        with self.assertRaises(ContractError):kernel.preference_loss(proposals,selected["candidate_id"],source="real_duel_feedback",purpose="evaluation")
        with self.assertRaises(ContractError):kernel.fill_preference_loss(selected,a,b,source="unknown")
        with self.assertRaises(ContractError):kernel.record_update("build_goal",before_sha256=before["build_goal"],after_sha256=before["build_goal"])

    def test_active_lora_uses_same_models_and_differentiable_host_owned_loss(self):
        _,_,builder,kernel=kernel_fixture()
        adapter=AdapterSession(builder.models["build_goal"],AdapterConfig("fixture-goal","build_goal",rank=1,targets=("head.0",)),
            {"base_version":"fixture-base","feature_version":"fixture","context_sha256":"c"*64})
        proposals=kernel.propose_tasks();selected=kernel.select_task(proposals)
        result=kernel.preference_loss(proposals,selected["candidate_id"],source="synthetic_code_path_only")
        grads=torch.autograd.grad(result["loss"],adapter.parameters(),allow_unused=True)
        self.assertTrue(any(g is not None and torch.count_nonzero(g) for g in grads))
        adapter.verify_base()
        self.assertEqual(adapter.updates,0)
        _,shared=kernel._session(selected)
        self.assertIs(shared.models["build_goal"],builder.models["build_goal"])
        with self.assertRaises(ContractError):shared.train_preference(None)

    def test_metadata_roundtrip_preserves_goal_graph_feedback_and_rejects_tamper(self):
        _,assets,builder,kernel=kernel_fixture()
        proposals=kernel.propose_tasks();selected=kernel.select_task(proposals);task=BuildTask.from_dict(selected["task"])
        kernel.run_selected(selected,base=deck_for(task,assets),verifier=None,
            feedback=[{"source":"duel","message":"preserve feedback on recovery"}])
        state=kernel.state_dict()
        kernel._proposal_seals.clear()
        kernel.load_state_dict(deepcopy(state))
        self.assertEqual(kernel.state_dict(),state)
        queued=kernel.preference_loss(proposals,selected["candidate_id"],source="synthetic_code_path_only")
        self.assertTrue(queued["loss"].requires_grad)
        before=kernel.state_dict();bad=deepcopy(state)
        bad["encoder_binding"]["cards"].reverse()
        with self.assertRaises(ContractError):kernel.load_state_dict(bad)
        self.assertEqual(kernel.state_dict(),before)
        bad=deepcopy(state);key=next(iter(bad["selections"]))
        bad["selections"][key]["task"]["goal"]["constraints"][0]["minimum"]=39
        with self.assertRaises(ContractError):kernel.load_state_dict(bad)
        self.assertEqual(kernel.state_dict(),before)
        bad=deepcopy(state);bad["selections"][key]["theme"]["source"]="made-up-source"
        with self.assertRaises(ContractError):kernel.load_state_dict(bad)
        self.assertEqual(kernel.state_dict(),before)
        with torch.no_grad():builder.models["build_goal"].head[-1].bias.add_(.1)
        with self.assertRaises(ContractError):kernel.load_state_dict(state)


if __name__=="__main__":unittest.main()
