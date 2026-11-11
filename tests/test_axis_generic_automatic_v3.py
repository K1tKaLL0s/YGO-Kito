"""Selected, bounded artificial tests for the local automatic v3 entry."""
from copy import deepcopy
from dataclasses import replace
from itertools import combinations, permutations
import gzip
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from tests.multifactor_helpers import task_temporary_directory
from tests.test_multifactor_learning_v3 import record, PROTOCOL
from tests.test_multifactor_review_v3 import fixture_run
from training.axis_generic import automatic_v3 as auto
from ygo_kito.multifactor.contracts import AnalysisGraph, FactorContractError, Factors, GraphNode, GraphEdge, RoleInput, digest
from ygo_kito.multifactor.training import RoleTrainer


def fixture(root, *, post=True):
    training, manifest = fixture_run(root)
    training.update(epochs=1,patience=1,engineering_max_records=8,save_every_batches=1)
    data=Path(training['dataset_dir'])
    for fold,groups in (('validation',['dev-a','dev-b','dev-c']),('retrospective_test',['past'])):
        rows=[]
        for group in groups:
            for value in (0,1):
                row=record([('mechanism',('card:1',),'search',value)],name=group+str(value),kind='engineering_fixture')
                row['supervision'].update(partition=fold,trainable=False)
                row['provenance'].update(leakage_group=group,previously_consumed=True,final_eval_eligible=False)
                rows.append(row)
        path=data/(fold+'.gz')
        with gzip.open(path,'wt',encoding='utf-8') as stream:
            stream.write(''.join(json.dumps(r)+'\n' for r in rows))
        manifest['shards'][fold]=[dict(file=path.name,records=len(rows),semantic_records=digest(rows))]
    semantic=dict(feature_schema='axis-graph-v3',label_protocol=PROTOCOL,split={})
    manifest.update(version='axis-dataset-v3',split_counts={'train':2,'validation':6,'test':0,'retrospective_test':2},
                    source_counts={'train':1,'validation':3,'test':0,'retrospective_test':1},new_independent_final=False)
    manifest['preparation_identity'].update(implementation=auto.prepare_v3.preparation_implementation(),semantic_config=semantic)
    auto.write(data/'dataset.json',manifest)
    preparation=dict(run_dir=str(data),formal_training=False,automatic_lora=False,core_course_resumed=False)
    config=dict(version='axis-automatic-v3',prepare_config='prepare.json',train_config='train.json',state_dir=str(root/'automatic'),
        minimum_free_gib=.001,calibration_reservation=dict(fraction=.25,minimum_groups=2),
        postprocess=dict(calibrate=post,evaluate_folds=['test','retrospective_test'] if post else []))
    for name,value in (('prepare.json',preparation),('train.json',training),('automatic.json',config)):
        auto.write(root/name,value)
    return root/'automatic.json',training,manifest


class AutomaticTests(unittest.TestCase):
    def test_null_legacy_unit_is_preserved_without_invented_function(self):
        with task_temporary_directory() as temp:
            root=Path(temp)
            auto.write(root/'cases.json',[dict(case_id='null',main=[[1,1]],extra=[],selected_main=[[1,1]],unit=None)])
            auto.write(root/'labels.json',[dict(case_id='null',roles=[1,0,None,None,1],confidence=[1]*5)])
            rows=auto.prepare_v3.load_legacy_sources({},dict(cases=str(root/'cases.json'),labels=str(root/'labels.json')))
            self.assertEqual(len(rows),1)
            self.assertTrue(rows[0]['provenance']['previously_consumed'])
            self.assertFalse(rows[0]['provenance']['final_eval_eligible'])
            self.assertEqual(RoleInput.from_dict(rows[0]['observations']['input']).unit_definition.function_id,'function:unresolved_legacy_request')

    def test_preflight_exposes_missing_tasks_classes_coordinates_and_zero_weight(self):
        with task_temporary_directory() as temp:
            recipe,manifest=fixture_run(Path(temp))
            recipe['task_weights']={'mechanism':0}
            report=auto.train_v3.inspect_data(recipe,manifest)
            self.assertFalse(report['ready'])
            self.assertIn('mechanism:no effective training labels',report['missing'])
            self.assertIn('copy_preference',report['tasks'])
            search=next(v for v in report['tasks']['mechanism']['partitions']['validation'] if v['coordinate']=='search')
            self.assertEqual(search['effective_classes'],[0,1])
            self.assertEqual(search['source_groups'],1)

    def test_default_prepares_only_and_start_missing_labels_never_constructs_model(self):
        with task_temporary_directory() as temp:
            root=Path(temp);path,recipe,manifest=fixture(root)
            recipe['selection_tasks'].append('copy_preference')
            auto.write(root/'train.json',recipe)
            with patch.object(auto,'prepare_data',return_value=manifest),patch.object(RoleTrainer,'__init__',side_effect=AssertionError('model must not be constructed')):
                result=auto.run(path,start=True)
            self.assertEqual(result['status'],'not_ready')
            self.assertFalse(Path(recipe['run_dir']).exists())
            self.assertEqual(len(result['partitions']['calibration_groups']),2)
            self.assertFalse(result['formal_training_started'])

    def test_cuda_unavailable_never_falls_back(self):
        with task_temporary_directory() as temp:
            path,recipe,_=fixture(Path(temp))
            settings,_,_=auto.load_config(path)
            recipe['device']='cuda:0'
            with patch.object(torch.cuda,'is_available',return_value=False):
                with self.assertRaisesRegex(FactorContractError,'no CPU fallback'):
                    auto.hardware(settings,recipe)

    def test_initial_snapshot_exists_before_first_update_and_resumes(self):
        with task_temporary_directory() as temp:
            root=Path(temp);recipe,manifest=fixture_run(root)
            def stop(event,**values):
                if event=='v3_checkpoint':raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt),patch.object(RoleTrainer,'train_supervised',side_effect=AssertionError('no update before snapshot')):
                auto.train_v3.fit(recipe,root/'run',manifest,stop)
            latest=auto.read(root/'run/latest.json')
            self.assertEqual(latest['sampler']['next_batch'],0)
            recipe['load_mode']='resume'
            result=auto.train_v3.fit(recipe,root/'run',manifest,lambda *a,**k:None)
            self.assertTrue(result['sampler']['finished'])

    def test_interrupted_unsaved_batch_recovery_matches_continuous(self):
        with task_temporary_directory() as temp:
            root=Path(temp);recipe,manifest=fixture_run(root)
            def stop(event,**values):
                if event=='v3_batch':raise RuntimeError('interrupt after unsaved batch')
            with self.assertRaisesRegex(RuntimeError,'unsaved'):
                auto.train_v3.fit(recipe,root/'run',manifest,stop)
            recipe['load_mode']='resume'
            auto.train_v3.fit(recipe,root/'run',manifest,lambda *a,**k:None)
            recipe.update(load_mode='fresh',run_dir=str(root/'continuous'))
            auto.train_v3.fit(recipe,root/'continuous',manifest,lambda *a,**k:None)
            a=torch.load(auto.train_v3.latest_checkpoint(root/'run'),weights_only=True)
            b=torch.load(auto.train_v3.latest_checkpoint(root/'continuous'),weights_only=True)
            self.assertEqual(a['sampler'],b['sampler'])
            self.assertEqual(a['steps'],b['steps'])
            for name in a['model']:torch.testing.assert_close(a['model'][name],b['model'][name],rtol=0,atol=0)

    def test_published_checkpoint_survives_missing_latest_and_partitions(self):
        with task_temporary_directory() as temp:
            root=Path(temp);recipe,manifest=fixture_run(root)
            original=auto.train_v3.write
            def stop(path,value):
                if Path(path).name=='latest.json':raise RuntimeError('metadata interruption')
                original(path,value)
            with patch.object(auto.train_v3,'write',side_effect=stop),self.assertRaisesRegex(RuntimeError,'metadata'):
                auto.train_v3.fit(recipe,root/'run',manifest,lambda *a,**k:None)
            (root/'run/partitions.json').unlink()
            recipe['load_mode']='resume'
            auto.train_v3.fit(recipe,root/'run',manifest,lambda *a,**k:None)
            self.assertTrue(auto.read(root/'run/latest.json')['sampler']['finished'])
            self.assertTrue((root/'run/partitions.json').exists())

    def test_matching_zero_step_metadata_without_checkpoint_resumes(self):
        with task_temporary_directory() as temp:
            root=Path(temp);recipe,manifest=fixture_run(root)
            with patch.object(RoleTrainer,'save',side_effect=RuntimeError('before snapshot')),self.assertRaisesRegex(RuntimeError,'snapshot'):
                auto.train_v3.fit(recipe,root/'run',manifest,lambda *a,**k:None)
            recipe['load_mode']='resume'
            result=auto.train_v3.fit(recipe,root/'run',manifest,lambda *a,**k:None)
            self.assertTrue(result['sampler']['finished'])

    def test_full_local_pipeline_and_completed_restart_reuses_postprocessing(self):
        with task_temporary_directory() as temp:
            root=Path(temp);path,recipe,manifest=fixture(root)
            with patch.object(auto,'prepare_data',return_value=manifest):
                prepared=auto.run(path)
                self.assertEqual(prepared['status'],'prepared')
                self.assertFalse(Path(recipe['run_dir']).exists())
                result=auto.run(path,start=True)
                self.assertEqual(result['status'],'complete')
                self.assertFalse(result['postprocess']['evaluations']['retrospective_test']['independent'])
                self.assertEqual(result['postprocess']['evaluations']['test']['status'],'unavailable')
                snapshots={p.name:p.stat().st_mtime_ns for p in Path(recipe['run_dir']).glob('*.pt')}
                import workflow_v3
                with (patch.object(RoleTrainer,'train_supervised',side_effect=AssertionError('completed training repeated')),
                      patch.object(workflow_v3,'predict_records',side_effect=AssertionError('predictions repeated'))):
                    resumed=auto.run(path,start=True)
                self.assertTrue(resumed['training']['resumed_completed'])
                self.assertEqual(snapshots,{p.name:p.stat().st_mtime_ns for p in Path(recipe['run_dir']).glob('*.pt')})
                self.assertEqual(auto.read(root/'automatic/state.json')['status'],'complete')

    def test_config_change_and_duplicate_process_are_rejected(self):
        with task_temporary_directory() as temp:
            root=Path(temp);path,recipe,manifest=fixture(root,post=False)
            with auto.runtime.training_lock(root/'automatic'),patch.object(auto,'hardware',side_effect=AssertionError('duplicate must stop before work')):
                with self.assertRaises(OSError):auto.run(path)
            with patch.object(auto,'prepare_data',return_value=manifest):auto.run(path)
            recipe['learning_rate']=.002
            auto.write(root/'train.json',recipe)
            with self.assertRaisesRegex(FactorContractError,'config/implementation differs'):auto.run(path,start=True)

    def test_failure_records_stage_and_error_and_does_not_continue(self):
        with task_temporary_directory() as temp:
            root=Path(temp);path,_,_=fixture(root)
            with patch.object(auto,'prepare_data',side_effect=RuntimeError('broken source')),patch.object(auto.train_v3,'fit',side_effect=AssertionError('must not train')):
                with self.assertRaisesRegex(RuntimeError,'broken source'):auto.run(path,start=True)
            state=auto.read(root/'automatic/state.json')
            self.assertEqual((state['status'],state['stage']),('failed','prepare'))
            self.assertEqual(state['error']['message'],'broken source')
            self.assertIn('broken source',Path(state['log']).read_text('utf-8'))

    def test_preparation_attempt_publishes_only_complete_data_and_reuses_cache(self):
        from tests.test_multifactor_data_v3 import record as source_record,config as prep_config
        with task_temporary_directory() as temp:
            root=Path(temp);state=root/'state';state.mkdir()
            sources=root/'sources.json';auto.write(sources,[source_record()])
            recipe=prep_config();recipe.update(records_file=str(sources),run_dir=str(root/'data'))
            report=auto.prepare_data(recipe,state,lambda *a,**k:None)
            reused=auto.prepare_data(recipe,state,lambda *a,**k:None)
            self.assertEqual(report['preparation_identity'],reused['preparation_identity'])
            self.assertEqual(list(state.glob('prepare-attempt-*')),[])
            sources.write_text('[]',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'no source records'):auto.prepare_data(recipe,state,lambda *a,**k:None)
            self.assertTrue((root/'data/dataset.json').exists())

    def test_cli_exit_codes_for_not_ready_and_interrupt(self):
        with patch.object(auto.sys,'argv',['automatic','--start']),patch.object(auto,'run',return_value={'status':'not_ready'}):
            self.assertEqual(auto.main(),2)
        with patch.object(auto.sys,'argv',['automatic','--start']),patch.object(auto,'run',side_effect=KeyboardInterrupt()):
            self.assertEqual(auto.main(),130)

    def test_atomic_state_write_transient_sharing_and_persistent_failure(self):
        with task_temporary_directory() as temp:
            path=Path(temp)/'state.json';auto.write(path,{'before':True})
            original=auto.train_v3.os.replace
            blocked=PermissionError('transient sharing');blocked.winerror=32
            calls=[]
            def replace(source,destination):
                calls.append(1)
                if len(calls)<3:raise blocked
                return original(source,destination)
            with patch.object(auto.train_v3.os,'name','nt'),patch.object(auto.train_v3.os,'replace',side_effect=replace):
                auto.write(path,{'after':True})
            self.assertEqual(len(calls),3)
            self.assertEqual(auto.read(path),{'after':True})
            with patch.object(auto.train_v3.os,'name','nt'),patch.object(auto.train_v3.os,'replace',side_effect=blocked) as denied:
                with self.assertRaises(PermissionError):auto.write(path,{'lost':True})
            self.assertEqual(denied.call_count,6)
            self.assertEqual(auto.read(path),{'after':True})

    def test_completed_run_rejects_corrupt_postprocess_binding(self):
        with task_temporary_directory() as temp:
            root=Path(temp);path,_,manifest=fixture(root)
            with patch.object(auto,'prepare_data',return_value=manifest):
                auto.run(path,start=True)
                prediction=root/'automatic/postprocess/validation-predictions.json'
                value=auto.read(prediction);value['model_id']='wrong-model';auto.write(prediction,value)
                with patch.object(RoleTrainer,'train_supervised',side_effect=AssertionError('must not update')):
                    with self.assertRaisesRegex(FactorContractError,'binding'):
                        auto.run(path,start=True)
            state=auto.read(root/'automatic/state.json')
            self.assertEqual((state['status'],state['stage']),('failed','postprocess'))

    def test_exact_canonicalization_matches_exhaustive_small_graph_isomorphism(self):
        nodes=tuple(GraphNode('anon:'+str(i),'card',Factors('group')) for i in range(4))
        pairs=list(combinations(range(4),2))
        by_exact,by_key={},{}
        for mask in range(1<<len(pairs)):
            selected=[p for i,p in enumerate(pairs) if mask&(1<<i)]
            exact=min(tuple(sorted(tuple(sorted((order[a],order[b]))) for a,b in selected)) for order in permutations(range(4)))
            edges=tuple(GraphEdge(nodes[a].ref,nodes[b].ref,'contains') for a,b in selected for a,b in ((a,b),(b,a)))
            graph=AnalysisGraph(nodes,edges)
            key=auto.prepare_v3._canonical_graph(graph)
            self.assertEqual(by_exact.setdefault(exact,key),key)
            self.assertEqual(by_key.setdefault(key,exact),exact)
            renamed={node.ref:'renamed:'+str(9-i) for i,node in enumerate(nodes)}
            other=AnalysisGraph(tuple(replace(node,ref=renamed[node.ref]) for node in reversed(nodes)),
                tuple(replace(edge,source=renamed[edge.source],target=renamed[edge.target]) for edge in reversed(edges)))
            self.assertEqual(key,auto.prepare_v3._canonical_graph(other))
        for node in nodes:self.assertEqual(auto.prepare_v3._node_values(node),node.numeric_values())
        with self.assertRaisesRegex(ValueError,'budget exhausted'):
            auto.prepare_v3._canonical_graph(AnalysisGraph(nodes,()),budget=1)

    def test_symmetric_whole_branches_are_pruned_only_by_exact_isomorphism(self):
        nodes=[GraphNode('card:1','card',Factors('group'))]
        edges=[]
        for branch in range(8):
            refs=[f'branch:{branch}:{i}' for i in range(3)]
            nodes.extend(GraphNode(ref,'card',Factors('group')) for ref in refs)
            edges.extend(GraphEdge(a,b,'contains') for a,b in zip(['card:1']+refs,refs))
        graph=AnalysisGraph(tuple(nodes),tuple(edges))
        key=auto.prepare_v3._canonical_graph(graph,budget=128)
        self.assertEqual(key,auto.prepare_v3._canonical_graph(AnalysisGraph(tuple(reversed(nodes)),tuple(reversed(edges))),budget=128))
        altered=AnalysisGraph(tuple(nodes),tuple([replace(edges[0],quantity=2)]+edges[1:]))
        self.assertNotEqual(key,auto.prepare_v3._canonical_graph(altered,budget=128))


if __name__=='__main__':
    unittest.main()
