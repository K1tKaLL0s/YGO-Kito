"""Static selection/supervision contracts; the real-model entry is separate."""
from types import SimpleNamespace
import unittest

from ygo_kito.construction_learning import candidate_pairs
from ygo_kito.construction_fill import construct_task
from tests.test_construction_functional_flow import functional_fill


class ConstructionSelectionTests(unittest.TestCase):
    def test_fixed_task_entry_uses_goal_skeleton_and_optimizer_with_resume(self):
        import torch
        from ygo_kito.duel_model import parameter_digest
        from tests.test_autonomous_construction import fixture as model_fixture,deck_for
        task,assets,builder,_=model_fixture()
        before={r:parameter_digest(m) for r,m in builder.models.items()}
        from unittest.mock import patch
        with patch.object(torch.optim.AdamW,'step',side_effect=AssertionError('updates forbidden')):
            result=construct_task(task,assets,builder.models,builder.encoder,base=deck_for(task,assets),max_iterations=1)
            resumed=construct_task(task,assets,builder.models,builder.encoder,continuation=result['session'],max_iterations=1)
        self.assertFalse(result['construction_passed']);self.assertFalse(result['task_verified'])
        self.assertEqual([p['role'] for p in result['phases']],['build_goal','build_optimizer'])
        self.assertEqual([p['role'] for p in resumed['phases']],['build_optimizer'])
        self.assertGreater(result['phases'][0]['unfilled']['main'], 0)
        self.assertEqual(result['best_criterion'],'versioned_pre_cb_construction_gate')
        self.assertTrue(result['construction_candidate']['layer_evaluation'])
        self.assertTrue(all(p['graph_model_selection'] for p in result['phases']))
        self.assertEqual(before,{r:parameter_digest(m) for r,m in builder.models.items()})
        self.assertEqual(result['basic_cb']['status'],'not_run')

    def test_quality_preferences_enter_existing_semantic_learning_contract_without_updates(self):
        from ygo_kito.build_contracts import DeckParts,digest
        from ygo_kito.build_semantics import proof
        from ygo_kito.semantic_training import validate as validate_supervision,supervision_projection
        from ygo_kito.semantic_training import SOURCE
        task,assets,decks,result=functional_fill()
        pairs=candidate_pairs(task,result['learning_candidates'])
        data=dict(source=SOURCE,purpose='train',task_sha256=task.sha256,pairs=pairs,
            goals=[dict(deck=d.to_dict(),label=1.,source='pinned_catalog_constraint_check',
                        evidence=proof(task,d,assets)) for d in decks],
            unknown_routes_used_as_negative=False,competitive_quality_labels=False,
            public_effect_receipts=assets.effect_receipts(task))
        data['supervision_sha256']=digest(supervision_projection(data))
        validate_supervision(task,assets,data)
        self.assertTrue(pairs)

    def test_pre_cb_slice_ingests_strict_optimizer_samples_once_without_real_updates(self):
        from ygo_kito.construction_learning import consume_optimizer_slice
        from ygo_kito.semantic_training import validate as validate_supervision
        task,assets,_,fill=functional_fill()
        admitted=[];consumed=[]
        def ingest(dataset,artifact,t,a,data,**kwargs):
            validate_supervision(t,a,data);admitted.append(artifact)
        def consume(fid,aid,**kwargs):
            self.assertEqual(kwargs['roles'],('build_optimizer',))
            consumed.append(dict(feedback_id=fid,role='build_optimizer',fixture_only=True))
        course=SimpleNamespace(_task=lambda:task,assets=assets,config={'course_id':'synthetic-no-training'},
            models=SimpleNamespace(builder=SimpleNamespace(updates={'build_optimizer':0})),
            data_index=SimpleNamespace(freeze=lambda *a:None,ingest_construction=ingest),
            feedback=SimpleNamespace(consumed=consumed),apply_feedback=consume)
        result=dict(phases=[dict(role='build_optimizer',stage_3=fill)],continuation={'iteration':1})
        receipt=consume_optimizer_slice(course,result)
        self.assertGreater(receipt['eligible_pairs'],0)
        self.assertEqual(receipt['updates_after'],0)
        consume_optimizer_slice(course,result)
        self.assertEqual(len(consumed),1);self.assertEqual(admitted[0],admitted[1])


if __name__=='__main__':unittest.main()
