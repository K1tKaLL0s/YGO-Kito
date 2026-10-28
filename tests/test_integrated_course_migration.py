"""Pinned legacy implementations -> strict composed restore, synthetic assets.

No original course, native engine, formal game, or authorization hold is used.
The legacy modules are repository-authored bytes from the PR8 baseline.
"""
from contextlib import contextmanager,ExitStack
from copy import deepcopy
import hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import torch

import tests.test_coordinator_control
from ygo_kito.course_models import CourseModels
from ygo_kito.build_contracts import BuildTask
from ygo_kito.data_isolation import DataIndex
from ygo_kito.scenario_course import ScenarioCourse
from ygo_kito.group_runner import tree_digest
from migrate_coordinator_course import export_closed_course,migrate_closed_course,sha


@contextmanager
def legacy_runtime():
    import ygo_kito.course_models as models
    import ygo_kito.course_feedback as feedback
    folder=Path(__file__).parent/'legacy_course_5cf3dc1'
    provenance=json.loads((folder/'provenance.json').read_text(encoding='utf-8'))
    modules={}
    with ExitStack() as stack:
        for name in ('build_model','build_training','coordinator_model','autonomous_construction'):
            path=folder/(name+'.py')
            if sha(path)!=provenance['sha256'][path.name]:raise AssertionError('legacy fixture bytes changed')
            spec=importlib.util.spec_from_file_location('ygo_kito.'+name,path)
            module=importlib.util.module_from_spec(spec)
            stack.enter_context(patch.dict(sys.modules,{spec.name:module}));spec.loader.exec_module(module)
            modules[name]=module
        for target in (models,feedback):
            stack.enter_context(patch.object(target,'BuildTrainer',modules['build_training'].BuildTrainer))
            stack.enter_context(patch.object(target,'CoordinatorTrainer',modules['coordinator_model'].CoordinatorTrainer))
        stack.enter_context(patch.object(models,'AutonomousConstructionKernel',modules['autonomous_construction'].AutonomousConstructionKernel))
        stack.enter_context(patch.object(models,'initialize_course_vocabulary',modules['autonomous_construction'].initialize_course_vocabulary))
        yield modules,provenance


class IntegratedMigrationTests(unittest.TestCase):
    def test_v5_nonempty_adam_and_aggregate_coordinator_compose_without_changing_old_course(self):
        from tests.test_scenario_course import ScenarioCourseTests
        import ygo_kito.course_models as current
        helper=ScenarioCourseTests('test_real_adapter_updates_same_lora_and_pause_restore_resumes_next_bo1')
        helper.setUp();self.addCleanup(helper.doCleanups)
        package=Path(current.__file__).parent
        target={'src/ygo_kito/'+p.name:sha(p) for p in package.glob('*.py')}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=root/'parent';parent.mkdir()
            with legacy_runtime() as (_,provenance):
                old_source=dict(target)
                old_source.update({'src/ygo_kito/'+name:value for name,value in provenance['sha256'].items()})
                binding=deepcopy(helper.models.binding);binding.update(learning_stage='base',source_files=old_source)
                # Old source policy adds a fixed route over a general base task,
                # matching the actual checkpoint16/base-task boundary.
                binding['construction_goal']=deepcopy(helper.models.builder.task.goal)
                raw=helper.models.builder.task.to_dict();raw['requirements']=[]
                for key in ('route_goal','required_activations','required_chain_resolutions'):raw['goal'].pop(key,None)
                general=BuildTask.from_dict(raw)
                old_models=CourseModels.initialize(general,helper.host.assets,helper.models.duel.config,
                    helper.models.adapter_configs,root,None,helper.host.assets.rows,binding)
                selection=old_models.kernel.select_task();old_models.kernel._session(selection)
                # Real Adam states for every old construction parameter. This
                # isolated algebraic fixture gives no game or quality credit.
                for role,model in old_models.builder.models.items():
                    optimizer=old_models.builder.optimizers[role]
                    sum(p.square().sum() for p in model.parameters()).backward();optimizer.step();optimizer.zero_grad()
                    old_models.builder.schedulers[role].step();old_models.builder.updates[role]=1
                old_models.builder.batch_cursor=1
                old=ScenarioCourse(old_models,assets=helper.host.assets,data_index=DataIndex(parent/'index'),
                    config=helper.config,state_root=parent/'course',bots=helper.bots)
                old.selection=selection;old.active_seconds=17.;old.desired='paused'
                with patch('os.statvfs',return_value=SimpleNamespace(f_frsize=4096),create=True):
                    old.save();receipt=export_closed_course(old,root/'export.weights')
                before_models=old.models.save_state()
            before={str(p.relative_to(parent)):sha(p) for p in parent.rglob('*') if p.is_file()}
            changed={p for p in target if old_source.get(p)!=target[p]}
            with patch('os.statvfs',return_value=SimpleNamespace(f_frsize=4096),create=True):
                migrated,report=migrate_closed_course(receipt,root/'next',assets=helper.host.assets,bots=helper.bots,
                    source_files=target,allowed_changed_files=changed,transition_to_postconstruction_cb=True)
                migrated.restore_latest()
            after=migrated.models.save_state()
            self.assertEqual(before,{str(p.relative_to(parent)):sha(p) for p in parent.rglob('*') if p.is_file()})
            self.assertEqual(migrated.desired,'paused');self.assertFalse(report['resume_authorized'])
            self.assertEqual(migrated.active_seconds,17.);self.assertEqual(migrated.records,old.records)
            self.assertEqual(after['cursors'],before_models['cursors'])
            self.assertEqual(report['construction_upgrade']['archived_sessions'],1)
            archive=torch.load(root/'next/pre-mechanism-kernel.weights',weights_only=True)
            self.assertEqual(tree_digest(archive),tree_digest(before_models['kernel']))
            self.assertEqual(after['kernel']['sessions'],{})
            self.assertEqual(after['kernel']['selections'],{});self.assertIsNone(migrated.selection)
            self.assertEqual(migrated.models.binding['basic_cb_stage'],'after_construction')
            self.assertNotIn('route_goal',migrated.models.binding['construction_goal'])
            self.assertTrue(report['source_objective_transition_performed'])
            self.assertTrue((root/'next/pre-policy-construction.weights').is_file())
            for role in ('build_goal','build_optimizer'):
                old_component=before_models['components'];new_component=after['components']
                for name,value in old_component['models'][role].items():
                    self.assertTrue(torch.equal(value,new_component['models'][role][name]),(role,name))
                self.assertEqual(new_component['models'][role]['mechanism.weight'].count_nonzero().item(),0)
                self.assertGreater(len(old_component['build_optimizers'][role]['state']),0)
                self.assertEqual(tree_digest(new_component['build_optimizers'][role]['state']),
                                 tree_digest(old_component['build_optimizers'][role]['state']))
                old_modes=before_models['rng']['modes'][role]
                self.assertEqual({k:v for k,v in after['rng']['modes'][role].items() if k!='mechanism'},old_modes)
            for name,value in before_models['rng'].items():
                if name!='modes':self.assertEqual(tree_digest(value),tree_digest(after['rng'][name]),name)
            with self.assertRaisesRegex(Exception,'explicitly reviewed'):
                migrate_closed_course(receipt,root/'wrong',assets=helper.host.assets,bots=helper.bots,
                    source_files=target,allowed_changed_files=set())
            self.assertFalse((root/'wrong').exists())
