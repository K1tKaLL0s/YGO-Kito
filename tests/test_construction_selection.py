"""Static selection/supervision contracts; the real-model entry is separate."""
from types import SimpleNamespace
import unittest

from ygo_kito.construction_learning import candidate_pairs
from ygo_kito.construction_fill import construct_task
from tests.test_construction_functional_flow import functional_fill


class ConstructionSelectionTests(unittest.TestCase):
    def test_fixed_task_entry_uses_goal_skeleton_and_optimizer_with_resume(self):
        import json
        from unittest.mock import patch

        import torch

        from tests.test_autonomous_construction import fixture as model_fixture, deck_for
        from ygo_kito.build_contracts import DeckParts, digest
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.duel_model import parameter_digest

        task, assets, builder, _ = model_fixture()
        before = {role: parameter_digest(model) for role, model in builder.models.items()}
        paused = False
        evaluate_inventory = ConstructionLayerAdapter.evaluate_inventory

        def pause_after_evaluation(adapter, *args, **kwargs):
            nonlocal paused
            result = evaluate_inventory(adapter, *args, **kwargs)
            if result[0] is not None:
                paused = True
            return result

        with patch.object(torch.optim.AdamW, 'step', side_effect=AssertionError('updates forbidden')):
            with patch.object(ConstructionLayerAdapter, 'evaluate_inventory', pause_after_evaluation):
                result = construct_task(task, assets, builder.models, builder.encoder,
                    base=deck_for(task, assets), max_iterations=1, pause_requested=lambda: paused)
            saved = json.loads(json.dumps(result['session']))
            pending = saved['construction_progress']['pending_quality']
            completed, = pending['evaluations'].values()
            completed_id = completed['quality_evaluation']['evaluation_id']
            with patch('ygo_kito.build_pipeline.goal_candidates', side_effect=AssertionError('saved candidates required')):
                resumed = construct_task(task, assets, builder.models, builder.encoder,
                    continuation=saved, max_iterations=1)

        self.assertEqual(result['stop_reason'], 'user_pause')
        self.assertEqual([p['role'] for p in result['phases']], ['build_goal', 'build_optimizer'])
        self.assertTrue(result['phases'][0]['graph_model_selection'])
        self.assertEqual(result['phases'][0]['unfilled'], task.sizes)
        self.assertEqual(result['phases'][1]['stage_1']['status'], 'effect_draft_received')
        self.assertEqual([p['role'] for p in resumed['phases']], ['build_optimizer'])
        self.assertEqual(resumed['latest_logic_sha256'], result['latest_logic_sha256'])
        self.assertEqual(resumed['continuation']['candidate_cursor'], saved['construction_progress']['candidate_cursor'])
        self.assertEqual(resumed['continuation']['iteration'], 1)
        phase = resumed['phases'][0]['stage_3']
        self.assertIn(completed_id, {row['quality_evaluation_id'] for row in phase['candidate_trace']['candidates']})
        self.assertEqual(resumed['best_criterion'], 'versioned_pre_cb_construction_gate')
        candidate = resumed['construction_candidate']
        assets.validate(task, DeckParts.from_dict(candidate['deck']))
        self.assertTrue(candidate['graph_binding_unresolved'])
        self.assertIsNone(candidate['concrete_proposal'])
        layer = candidate['layer_evaluation']
        self.assertEqual(layer['validation'], 'list_constraints_verified')
        self.assertTrue(layer['axis']['logic_gaps'])
        self.assertEqual(layer['axis']['inventory'], candidate['deck'])
        quality = candidate['quality_evaluation']
        self.assertEqual(quality['deck_sha256'], digest(candidate['deck']))
        self.assertEqual(quality['task_sha256'], task.sha256)
        self.assertEqual(quality['logic_sha256'], resumed['latest_logic_sha256'])
        self.assertEqual(before, {role: parameter_digest(model) for role, model in builder.models.items()})
        self.assertFalse(resumed['graph_execution_verified'])
        self.assertEqual(resumed['basic_cb']['status'], 'not_run')

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
