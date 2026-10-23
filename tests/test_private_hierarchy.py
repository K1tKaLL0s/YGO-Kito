"""Wire/learning contracts only; real script evidence is in integration_tests."""
from dataclasses import replace
import json,struct,unittest
import torch
from torch.distributions import Categorical
from ygo_kito.contracts import (RunContext,Versions,Observation,LegalAction,DecisionRequest,SelectionChoice,PromptInfo,CardView)
from ygo_kito.native_protocol import Reader,decode_prompt,NativeError
from ygo_kito.duel_model import DuelModelConfig,DuelActorCritic,PlayerEncoder
from ygo_kito.hierarchical_policy import score_requests,sample_index
from ygo_kito.validation import ContractError
from ygo_kito.effect_duel import choose_effect_duel_action

CTX=RunContext('unit',Versions(*(['unit-wire-fixture']*6)),None)
def observation(cards=()):return Observation(0,0,1,'main1',(8000,8000),(1,3),(35,35),cards)
def wire(candidates):return bytes((0,0,1,1,len(candidates)))+b''.join(struct.pack('<IBBBB',*c) for c in candidates)
def request(decoded,obs):
 return DecisionRequest(CTX,'unit-duel','unit-window',obs,tuple(LegalAction('a'+str(i),x.kind,x.refs,x.value,x.details) for i,x in enumerate(decoded.options)),prompt=decoded.info,selection_choices=decoded.selection_choices)

class PrivateSelectionContracts(unittest.TestCase):
 def test_opponent_identity_and_zone_sequence_never_change_player_features(self):
  for zone in (1,2,64,32):
   with self.subTest(zone=zone):
    views=[];tensors=[]
    for codes,positions in [([111111,222222,333333],[3,4,5]),([444444,555555,666666],[8,9,10])]:
     obs=observation();d=decode_prompt(15,Reader(wire([(c,1,zone,s,8) for c,s in zip(codes,positions)])),selection_observation=obs,selection_seed=(123,0,0))
     r=request(d,obs);views.append(r.to_dict());tensors.append(PlayerEncoder([1],DuelModelConfig()).encode(r))
     for c in r.selection_choices:
      self.assertIsNone(c.card_id);self.assertIsNone(c.owner)
      self.assertNotIn('sequence',c.__dataclass_fields__)
    self.assertEqual(views[0],views[1])
    for key in tensors[0]:self.assertTrue(torch.equal(tensors[0][key],tensors[1][key]),key)
 def test_mixed_offered_deck_and_legal_hand_have_distinct_scopes_without_deck_order(self):
  obs=observation((CardView('p0.hand.0',0,0,'hand','observer',101),))
  d=decode_prompt(15,Reader(wire([(101,0,2,0,0),(202,0,1,71,8)])),selection_observation=obs,selection_seed=(1,0,0))
  r=request(d,obs)
  self.assertEqual(len(r.selection_choices),1)
  self.assertEqual((r.selection_choices[0].zone,r.selection_choices[0].card_id),('deck',202))
  self.assertEqual(DecisionRequest.from_dict(json.loads(json.dumps(r.to_dict()))),r)
  self.assertNotEqual(PlayerEncoder([101,202],DuelModelConfig()).encode(r)['pointers'][0].tolist(),PlayerEncoder([101,202],DuelModelConfig()).encode(r)['pointers'][1].tolist())
 def test_forged_identity_ownership_or_extra_native_fields_are_rejected(self):
  for kwargs in ({'card_id':12},{'owner':1}):
   with self.assertRaises(ContractError):SelectionChoice('x',1,'hand','hidden',**kwargs)
  with self.assertRaises(ContractError):SelectionChoice.from_dict({'ref':'x','controller':1,'zone':'deck','visibility':'hidden','sequence':1})
  c=SelectionChoice('x',1,'hand','observer',123)
  with self.assertRaises(ContractError):DecisionRequest(CTX,'d','w',observation(),(LegalAction('a','select',('x',)),),prompt=PromptInfo(15,1,1),selection_choices=(c,))
 def test_private_response_permutation_replays_and_does_not_publish_native_rank(self):
  obs=observation();payload=wire([(111,1,2,0,0),(222,1,2,1,0),(333,1,2,2,0)])
  def decode(seed):return decode_prompt(15,Reader(payload),selection_observation=obs,selection_seed=seed)
  a,b=decode((1,0,0)),decode((1,0,0))
  self.assertEqual(a,b)
  alternative=next(decode((s,0,0)) for s in range(2,20) if decode((s,0,0)).options!=a.options)
  self.assertEqual(request(a,obs).to_dict(),request(alternative,obs).to_dict())
  self.assertNotEqual([x.response for x in a.options],[x.response for x in alternative.options])
 def test_oversized_combinations_duplicates_and_unsupported_field_fail_closed(self):
  obs=observation()
  for payload in [bytes((0,0,3,3,128))+b''.join(struct.pack('<IBBBB',i+1,0,1,i,8) for i in range(128)),wire([(1,1,2,0,0)]*2),wire([(1,1,0x84,2,0)])]:
   with self.assertRaises(NativeError):decode_prompt(15,Reader(payload),selection_observation=obs,selection_seed=(1,0,0))
 def test_private_unselect_groups_keep_add_remove_finish_responses_separate(self):
  obs=observation();payload=bytes((0,1,0,1,2,1))+struct.pack('<IBBBB',111,1,2,3,0)+bytes((1,))+struct.pack('<IBBBB',222,1,2,4,0)
  d=decode_prompt(26,Reader(payload),selection_observation=obs,selection_seed=(1,0,0))
  self.assertEqual({x.details.operation for x in d.options},{'add','remove','finish'})
  self.assertEqual({x.response for x in d.options},{b'\x01\0',b'\x01\x01',-1})
  self.assertTrue(all(c.card_id is None for c in request(d,obs).selection_choices))
  self.assertEqual(choose_effect_duel_action(request(d,obs),{}).details.operation,'finish')
 def test_nonzero_cancel_flag_and_more_than_2048_combinations_keep_all_actions(self):
  payload=bytes((0,2,2,2,70))+b''.join(struct.pack('<IBBBB',i+1,0,1,i,8) for i in range(70))
  d=decode_prompt(15,Reader(payload),selection_observation=observation(),selection_seed=(1,0,0))
  self.assertTrue(d.info.cancelable);self.assertEqual(len(d.options),2416)
  self.assertTrue(any(x.response==bytes((2,68,69)) for x in d.options))

class HierarchicalPolicyContracts(unittest.TestCase):
 @classmethod
 def setUpClass(cls):torch.set_num_threads(1)
 def test_tail_remains_reachable_and_path_log_probability_is_exact(self):
  logits=torch.zeros(5003);logits[-1]=100
  idx,receipt=sample_index(logits,generator=torch.Generator().manual_seed(1),max_actions=64)
  self.assertEqual(idx,5002);self.assertGreater(len(receipt['path']),1)
  self.assertAlmostEqual(receipt['path_log_prob'],float(Categorical(logits=logits).log_prob(torch.tensor(idx))),places=5)
  for seed in range(20):
   x,meta=sample_index(torch.linspace(-3,4,5003),generator=torch.Generator().manual_seed(seed),max_actions=64)
   self.assertAlmostEqual(meta['path_log_prob'],float(Categorical(logits=torch.linspace(-3,4,5003)).log_prob(torch.tensor(x))),places=5)
 def test_chunk_sizes_preserve_complete_learned_logits_and_backpropagation(self):
  cfg=DuelModelConfig(width=16,card_width=8,heads=2,feedforward=32,max_tokens=32,max_actions=64,history_events=1)
  cards=list(range(1,2051));model=DuelActorCritic(cfg,len(cards))
  req=DecisionRequest(CTX,'unit','unit',observation(),tuple(LegalAction('a'+str(i),'number',value=i) for i in cards),prompt=PromptInfo(142,1,1))
  enc=PlayerEncoder(cards,cfg);logits,value=score_requests(model,enc,[req])
  other,_=score_requests(model,PlayerEncoder(cards,replace(cfg,max_actions=512)),[req])
  self.assertEqual(logits.shape,(1,2050));self.assertTrue(torch.allclose(logits,other,atol=2e-6,rtol=1e-6))
  loss=-Categorical(logits=logits).log_prob(torch.tensor([2049])).mean()+value.square().mean()
  loss.backward();self.assertGreater(float(model.policy_head[-1].weight.grad.abs().sum()),0)
  page=replace(req,actions=req.actions[-2:]);encoded=enc.encode(page)
  self.assertEqual(encoded['actions'][:,1].tolist(),[2049,2050])
 def test_empty_or_unbounded_logits_and_insufficient_branch_budget_are_rejected(self):
  for logits,cap in [(torch.tensor([]),64),(torch.zeros(50001),64),(torch.tensor([float('nan')]),64),(torch.zeros(3),1)]:
   with self.assertRaises(ContractError):sample_index(logits,generator=torch.Generator(),max_actions=cap)

if __name__=='__main__':unittest.main()
