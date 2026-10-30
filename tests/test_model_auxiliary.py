"""CPU contracts for actual auxiliary evidence; no engine or ability claims."""
from copy import deepcopy
import unittest

from ygo_kito.model_auxiliary import (
    METRICS,benefits,choose_auxiliary,pack_requests,unpack_requests,
)
from ygo_kito.validation import ContractError


def cases():
    return [{'candidate_index':i,'seed_audit_only':s,'actor_seat':p,'score':0.,
             'auxiliary':{'metrics':dict.fromkeys(METRICS,0)}}
            for s in (31,32) for p in (0,1) for i in (0,1)]


class AuxiliaryEvidenceTests(unittest.TestCase):
    def test_actual_goal_dominance_can_differ_while_all_games_are_losses(self):
        rows=cases()
        for r in rows:
            if r['candidate_index']==1:r['auxiliary']['metrics'][METRICS[0]]=1
        preferred,reason=choose_auxiliary(rows,{'paired_seeds_audit_only':[31,32]},METRICS)
        self.assertEqual(preferred,1);self.assertIn('goal_auxiliary',reason)
        self.assertTrue(all(r['score']==0. for r in rows))

    def test_single_seed_unknown_and_competing_goal_objectives_do_not_create_rank(self):
        plan={'paired_seeds_audit_only':[31,32]}
        rows=cases()
        for r in rows:
            if r['candidate_index']==1 and r['seed_audit_only']==31:r['auxiliary']['metrics'][METRICS[0]]=1
        self.assertIsNone(choose_auxiliary(rows,plan,METRICS)[0])
        for r in rows:
            if r['candidate_index']==1:r['auxiliary']['metrics'][METRICS[0]]=1
        rows[0]['auxiliary']['metrics'][METRICS[0]]=None
        self.assertIsNone(choose_auxiliary(rows,plan,METRICS)[0])
        rows=cases()
        for r in rows:r['auxiliary']['metrics'][METRICS[0 if r['candidate_index']==1 else 2]]=1
        self.assertIsNone(choose_auxiliary(rows,plan,METRICS)[0])

    def test_auxiliary_does_not_override_a_paired_primary_result(self):
        rows=cases()
        for r in rows:
            if r['candidate_index']==1:r['auxiliary']['metrics'][METRICS[0]]=1
        rows[0]['score']=1.
        self.assertIsNone(choose_auxiliary(rows,{'paired_seeds_audit_only':[31,32]},METRICS)[0])

    def test_goal_prerequisite_needs_an_actual_nonnegated_resolved_benefit(self):
        task={'goal':{'required_chain_resolutions':[101],'route_goal':{'fusion_witness':{
            'effect_assessments':[{'card_id':202}],'required_source_zones':[16]}}}}
        activation={'kind':70,'link':1,'player':0,'public_card':101}
        solving={'kind':72,'link':1};solved={'kind':73,'link':1}
        move={'kind':50,'player':0,'public_card':202,'from_zone':1,'to_zone':16,'reason':0x40}
        self.assertEqual(benefits(task,[activation,solving,solved],0)[0],[])
        self.assertEqual(len(benefits(task,[activation,solving,move,solved],0)[0]),1)
        self.assertEqual(benefits(task,[activation,solving,move,{'kind':75,'link':1},solved],0)[0],[])

    def test_observation_encoding_is_bounded_and_detects_corruption(self):
        episode={'steps':[{'request':{'schema_version':1,'fixture':'synthetic-contract-only'}}]}
        proof=pack_requests(episode);self.assertEqual(unpack_requests(proof),[episode['steps'][0]['request']])
        bad=deepcopy(proof);bad['raw_sha256']='0'*64
        with self.assertRaises(ContractError):unpack_requests(bad)
        bad=deepcopy(proof);bad['raw_bytes']=1
        with self.assertRaises(ContractError):unpack_requests(bad)

if __name__=='__main__':unittest.main()
