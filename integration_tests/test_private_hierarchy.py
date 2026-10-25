"""Pinned native core/scripts, normal deals, separate from unit wire fixtures."""
from dataclasses import replace
import copy,json,random,tempfile,unittest
from pathlib import Path
import torch
from ygo_kito.contracts import ActionSelection,DecisionRequest
from ygo_kito.native import NativeNormalEngine,NativeError
from ygo_kito.normal_duel import request_digest
from ygo_kito.private_cases import read_case,run_private_case,REQUIRED
from ygo_kito.protocol_cases import EngineeringDriver
from ygo_kito.duel_model import PlayerEncoder,DuelModelConfig,parameter_digest
from ygo_kito.cpu_training import CpuTrainer,CpuTrainingConfig,resource_binding,save_checkpoint,load_checkpoint
from ygo_kito.effect_duel import public_card_facts,run_effect_duel
from ygo_kito.validation import ContractError

CACHE=Path(__file__).resolve().parents[1]/'.cache'

class RealPrivateSelectionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  torch.set_num_threads(1)
  cls.cases={name:run_private_case(CACHE,name) for name in REQUIRED}
  cls.alternate={name:run_private_case(CACHE,name,preference='last') for name in ('chosen-blind','mixed-teleport')}
  cls.complete=run_private_case(CACHE,'chosen-blind',complete=True)
 def test_every_actual_route_and_complete_terminal_replay_exactly(self):
  for name,pair in self.cases.items():
   with self.subTest(name=name):
    summary,trace=pair
    checked,again=run_private_case(CACHE,name,replay=json.loads(json.dumps(trace)))
    self.assertEqual(trace,again);self.assertEqual(summary['trace_sha256'],checked['trace_sha256'])
    self.assertEqual(trace['result']['callback_errors'],0)
    for window in trace['windows']:
     if 'context' in window['request']:self.assertEqual(window['request']['context']['versions']['card_pool'],'native-private-selection-v4')
  s,t=self.complete;self.assertTrue(t['result']['natural_terminal']);self.assertEqual(t['events'][-1]['kind'],5)
  _,again=run_private_case(CACHE,'chosen-blind',complete=True,replay=json.loads(json.dumps(t)))
  self.assertEqual(t,again)
 def test_real_blind_hand_choices_are_opaque_after_actual_reveal_and_shuffle(self):
  for _,t in [self.cases['chosen-blind'],self.alternate['chosen-blind']]:
   window=next(w for w in t['windows'] if w['request'].get('selection_choices'))
   r=DecisionRequest.from_dict(window['request'])
   self.assertEqual(r.observation.observer,1);self.assertEqual(len(r.selection_choices),3)
   self.assertTrue(all(c.card_id is None and c.owner is None and c.zone=='hand' for c in r.selection_choices))
   self.assertIsNone(r.context.seed)
   self.assertNotIn(t['selection_key_audit_only'],json.dumps(r.to_dict()))
   self.assertTrue(any(e.details.message==31 for e in r.observation.public_history))
   self.assertTrue(any(e.details.message==33 for e in r.observation.public_history))
   self.assertTrue(all(c.controller!=0 or c.zone!='hand' for c in r.observation.cards))
 def test_real_mixed_selection_exposes_only_offered_deck_identities_and_distinct_source_moves(self):
  sources=[]
  for _,t in [self.cases['mixed-teleport'],self.alternate['mixed-teleport']]:
   req=DecisionRequest.from_dict(t['windows'][0]['request'])
   self.assertTrue(req.selection_choices);self.assertTrue(all(c.controller==0 and c.zone=='deck' and c.visibility=='observer' for c in req.selection_choices))
   self.assertTrue(any(r.startswith('p0.hand.') for a in req.actions for r in a.card_refs))
   sources.append(next(e['from_zone'] for e in t['events'] if e['kind']==50 and e.get('to_zone')==4))
  self.assertEqual(set(sources),{1,2})
 def test_real_hidden_hand_worlds_have_identical_opponent_windows_and_all_model_tensors(self):
  case=read_case('chosen-blind');changed=copy.deepcopy(case['profile'])
  # The real opening's unselected normal monster is deck slot16. It is never
  # confirmed by Chosen One; changing its identity must not affect the chooser.
  self.assertEqual(changed['decks'][0][16],732302)
  facts=public_card_facts(CACHE)
  replacement=next(code for code,x in sorted(facts.items()) if x['type']==17 and code not in changed['decks'][0] and code<100000000)
  changed['decks'][0][16]=replacement
  views=[]
  for profile in (case['profile'],changed):
   with NativeNormalEngine(CACHE,scenario='effect-duel',deck_profile=profile,seed=case['seed_audit_only'],selection_key='0123456789abcdef0123456789abcdef') as engine:
    driver=EngineeringDriver(case,engine._rows,'first');req=engine.next_decision()
    for _ in range(100):
     if req.selection_choices and req.observation.observer==1:
      views.append(req);break
     action=driver.choose(req);engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id));req=engine.next_decision()
    else:self.fail('real blind hand window not reached')
    with self.assertRaisesRegex(NativeError,'must not be queried'):engine._query(0,1,0,1)
  self.assertEqual(request_digest(views[0]),request_digest(views[1]))
  encoder=PlayerEncoder(sorted(facts),DuelModelConfig())
  a,b=map(encoder.encode,views)
  for key in a:self.assertTrue(torch.equal(a[key],b[key]),key)
 def test_control_swap_and_flip_summon_have_actual_public_events_and_correct_owners(self):
  _,t=self.cases['control-swap'];hist=t['final_observations'][0]['public_history']
  self.assertTrue(any(e['details']['message']==55 for e in hist))
  cards=t['final_observations'][0]['cards']
  self.assertTrue(any(c['card_id']==32864 and c['owner']==1 and c['controller']==0 for c in cards))
  self.assertTrue(any(c['card_id']==43096270 and c['owner']==0 and c['controller']==1 for c in cards))
  _,t=self.cases['flip-summon'];seen={e['details']['message'] for e in t['final_observations'][0]['public_history']}
  self.assertTrue({64,65}<=seen)
 def test_real_high_bit_packed_sum_and_public_coin_result_are_not_small_dual_values(self):
  _,t=self.cases['large-packed-sum'];r=DecisionRequest.from_dict(t['windows'][0]['request'])
  self.assertEqual(r.sum_selection.mode,'minimal_at_least')
  self.assertEqual(r.sum_selection.optional[0].values,(67200,))
  self.assertEqual(r.sum_selection.target,63200)
  self.assertTrue(any(e['details']['message']==130 for e in t['final_observations'][0]['public_history']))
  self.assertTrue(any(e['kind']==50 and e.get('from_zone')==4 and e.get('to_zone')==1 and e.get('public_card')==7930346 for e in t['events']))
 def test_blind_forgery_stale_action_and_bad_native_response_are_rejected(self):
  _,trace=self.cases['chosen-blind'];case=trace['case']
  with NativeNormalEngine(CACHE,scenario='effect-duel',deck_profile=case['profile'],seed=case['seed_audit_only'],selection_key=trace['selection_key_audit_only']) as engine:
   req=engine.next_decision();old=None
   for row in trace['responses']:
    if req.selection_choices:break
    old=ActionSelection(req.context.run_id,req.duel_id,req.decision_id,row['action_id']);engine.submit(old);req=engine.next_decision()
   before=request_digest(req)
   for bad in (ActionSelection(req.context.run_id,req.duel_id,req.decision_id,'forged'),old):
    with self.assertRaises(ContractError):engine.submit(bad)
    self.assertEqual(request_digest(engine.next_decision()),before)
   action=req.actions[0];engine._responses[action.action_id]=b'\0'*64
   engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id))
   with self.assertRaisesRegex(NativeError,'MSG_RETRY'):engine.next_decision()
 def test_missing_private_replay_material_and_incompatible_profile_fail_closed(self):
  _,t=self.cases['chosen-blind'];bad=copy.deepcopy(t);bad.pop('selection_key_audit_only')
  with self.assertRaises(ContractError):run_private_case(CACHE,'chosen-blind',replay=bad)
  with self.assertRaises(ContractError):NativeNormalEngine(CACHE,selection_key='0'*32)
 def test_generic_v4_effect_duel_reaches_natural_terminal_and_retains_private_replay_material(self):
  result,trace=run_effect_duel(CACHE,read_case('chosen-blind')['profile'],seed=90,budget_seconds=30)
  self.assertTrue(result['ok']);self.assertEqual(trace['versions']['adapter_schema'],'native-private-selection-v4')
  self.assertIn('selection_key_audit_only',trace)
  checked,again=run_effect_duel(CACHE,trace['profile'],replay=json.loads(json.dumps(trace)),budget_seconds=30)
  self.assertTrue(checked['replay_verified']);self.assertEqual(trace,again)

class RealLargeActionLearningTests(unittest.TestCase):
 def test_real_full_catalogue_hierarchy_updates_and_checkpoint_continuation_match(self):
  torch.set_num_threads(1);profile=read_case('large-declaration')['profile'];facts=public_card_facts(CACHE)
  config=CpuTrainingConfig(model=DuelModelConfig(width=16,card_width=8,heads=2,feedforward=32,history_events=2,max_tokens=128),game_seeds=(0,3),curriculum='large-declaration')
  trainer=CpuTrainer(config,sorted(facts));binding=resource_binding(CACHE,profile)
  first=trainer.sample_episode(CACHE,profile)
  self.assertEqual(first['summary']['callback_errors'],0)
  self.assertEqual(first['summary']['curriculum']['policy_messages'],[142])
  self.assertTrue(first['summary']['outcome']['winner'] in (0,1,2))
  for step in first['steps']:
   self.assertGreater(len(step['request'].actions),2048)
   self.assertEqual(step['hierarchy']['leaf_count'],len(step['request'].actions))
   self.assertGreater(len(step['hierarchy']['path']),1)
   self.assertAlmostEqual(step['old_log_prob'],step['hierarchy']['path_log_prob'],places=4)
  metrics=trainer.update(first)
  self.assertGreater(abs(metrics['policy_loss']),0, 'terminal reward must affect the actor, not only entropy/value updates')
  self.assertGreater(metrics['policy_head_delta_l2'],0)
  self.assertGreater(metrics['changed_parameter_elements'],0)
  with tempfile.TemporaryDirectory() as tmp:
   checkpoint=save_checkpoint(trainer,Path(tmp),'hierarchy-first',binding)
   restored=load_checkpoint(checkpoint,binding)
   self.assertEqual(restored.config.curriculum,'large-declaration')
   with self.assertRaises(ContractError):load_checkpoint(checkpoint,{**binding,'feature_version':'old-v3'})
   left=trainer.sample_episode(CACHE,profile);right=restored.sample_episode(CACHE,profile)
   for key in ('trajectory_sha256','real_core_events_sha256','outcome'):
    self.assertEqual(left['summary'][key],right['summary'][key])
   self.assertEqual([s['hierarchy'] for s in left['steps']],[s['hierarchy'] for s in right['steps']])
   a,b=trainer.update(left),restored.update(right)
   self.assertEqual(a,b);self.assertEqual(parameter_digest(trainer.model),parameter_digest(restored.model))
   self.assertTrue(torch.equal(trainer.policy_rng.get_state(),restored.policy_rng.get_state()))
   with self.assertRaises(ContractError):trainer.update(first)

if __name__=='__main__':unittest.main()
