"""Exercise only launch wiring and recorded-audit restoration with local fixtures."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class CpuCourseLaunchTests(unittest.TestCase):
    def test_default_and_explicit_roots_keep_resources_readonly(self):
        repository=Path(__file__).resolve().parents[1]
        def load(name,filename):
            module=types.ModuleType(name);module.__file__=str(repository/'scripts'/filename)
            exec(compile(Path(module.__file__).read_text(encoding='utf-8'),module.__file__,'exec'),module.__dict__)
            return module
        fake_fcntl=types.SimpleNamespace(LOCK_EX=1,LOCK_NB=2,LOCK_UN=4,flock=lambda *_:None)
        with patch.dict(sys.modules,{'fcntl':fake_fcntl}):worker=load('launch_worker','local_training_worker.py')
        course=load('launch_course','local_foundation_course.py')
        goal={'kind':'deck_constraints','constraints':[{'id':'requested-theme','minimum':12}],'preferences':[]}
        policy={'construction_flow':'four_concrete_handoffs_then_basic_cb_inference_v3','basic_cb_stage':'after_construction',
                'construction_theme_ids':['setcode-181'],'construction_card_requirements':[],'construction_goal':goal}
        def candidate(ident,theme='setcode-181',route=False):
            task_goal=json.loads(json.dumps(goal));task_goal['constraints'].append({'id':'autonomous-axis','minimum':1})
            if route:task_goal['route_goal']={'kind':'old-fixed-route'}
            return {'candidate_id':ident,'theme':{'theme_id':theme},'task':{'requirements':[],'goal':task_goal}}
        old=candidate('old-task',route=True);outside=candidate('outside-theme',theme='different-theme')
        undeclared=candidate('undeclared-card');undeclared['task']['requirements']=[{'card_id':123}]
        first=candidate('first-legal');later=candidate('later-legal')
        proposals={'candidates':[old,outside,undeclared,first,later]}
        original_proposals=json.dumps(proposals,sort_keys=True)
        rank,event=course.initial_task_rank(proposals,policy,'old-task',explicit_roots=True)
        self.assertEqual(rank,3)
        self.assertEqual(event['old_selected_task_sha256'],'old-task')
        self.assertEqual(event['new_selected_task_sha256'],'first-legal')
        self.assertIs(event['old_matches_relabelled'],False)
        self.assertEqual(json.dumps(proposals,sort_keys=True),original_proposals)
        self.assertEqual(course.initial_task_rank(proposals,policy,'old-task'),(0,None))
        with self.assertRaisesRegex(RuntimeError,'No ranked candidate matches'):
            course.initial_task_rank({'candidates':[old,outside,undeclared]},policy,'old-task',explicit_roots=True)
        with self.assertRaisesRegex(RuntimeError,'original selected goal'):
            course.initial_task_rank({'candidates':[first,later]},policy,'old-task')
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)/'owner';source=base/'repository';resources=Path(temporary)/'old-resources'
            reports=base/'reports';reports.mkdir(parents=True)
            state=base/'migrated-course';state.mkdir()
            for root in (base/'source',source):
                (root/'scripts').mkdir(parents=True)
                for name in ('local_training_worker.py','local_foundation_course.py'):
                    (root/'scripts'/name).write_text('# fixture\n',encoding='utf-8')
            worker.__file__=str(source/'scripts/local_training_worker.py')
            course.__file__=str(source/'scripts/local_foundation_course.py')
            continuation={'state_root':str(state),'source_manifest':str(reports/'source.json'),
                          'source_archive':str(reports/'source.tar')}
            loaded=[];calls=[]
            def invoke(*args,**kwargs):calls.append((args,kwargs));return {'fixture':True}
            def specification(name,path):
                loaded.append(Path(path))
                return types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda module:setattr(module,'run',invoke)))
            class Thread:
                def __init__(self,*args,**kwargs):pass
                def start(self):pass
                def join(self,**kwargs):pass
            original_read=Path.read_text
            def read_text(path,*args,**kwargs):
                if str(path)=='/proc/sys/kernel/random/boot_id':return 'fixture-boot'
                if str(path)=='/proc/self/stat':return ' '.join(['0']*21+['fixture-ticks'])
                return original_read(path,*args,**kwargs)
            fake_hash=lambda _:types.SimpleNamespace(hexdigest=lambda:'fixture-script')
            boundary=lambda *_:True
            supervision=types.SimpleNamespace(make_unit_boundary=lambda *args:boundary)
            def launch(run_id,extra):
                argv=['worker','--base',str(base),'--run-id',run_id,'--job','course','--resume',*extra]
                with patch.object(sys,'argv',argv),patch.object(Path,'read_text',read_text),\
                     patch.object(worker.threading,'Thread',Thread),patch.object(worker.signal,'signal'),\
                     patch.object(worker.hashlib,'sha256',fake_hash),\
                     patch.object(worker.importlib.util,'spec_from_file_location',specification),\
                     patch.object(worker.importlib.util,'module_from_spec',lambda _:types.SimpleNamespace()),\
                     patch.dict(sys.modules,{'local_design_supervision':supervision}):
                    worker.main()
            launch('default',[])
            self.assertEqual(loaded[-1],base/'source/scripts/local_foundation_course.py')
            self.assertIsNone(calls[-1][1]['continuation'])
            self.assertNotIn('execution_source_root',calls[-1][1])
            self.assertNotIn('resource_base',calls[-1][1])
            (reports/'course-continuation.json').write_text(json.dumps(continuation),encoding='utf-8')
            explicit=['--source-root',str(source),'--resource-base',str(resources)]
            launch('explicit',explicit)
            self.assertEqual(loaded[-1],source/'scripts/local_foundation_course.py')
            self.assertEqual(calls[-1][0][0],base)
            self.assertEqual(calls[-1][1]['execution_source_root'],source)
            self.assertEqual(calls[-1][1]['resource_base'],resources)
            self.assertEqual(calls[-1][1]['continuation'],continuation)
            self.assertIs(calls[-1][1]['unit_boundary'],boundary)
            continuation['state_root']=str(base/'missing-course')
            (reports/'course-continuation.json').write_text(json.dumps(continuation),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'existing migrated course'):launch('fresh-forbidden',explicit)
            self.assertFalse((reports/'local-training/fresh-forbidden').exists())
            continuation['state_root']=str(state)
            class StopBeforeRuntime(Exception):pass
            archives=[]
            def unpack(archive,*_):archives.append(archive);raise StopBeforeRuntime
            comparison=types.SimpleNamespace(unpack_exact=unpack,restore_cached_bot_audit=lambda *_:self.fail('runtime was reached'))
            for root in (base,resources):
                (root/'reports').mkdir(parents=True,exist_ok=True)
                (root/'reports/model-pair-runtime-pack.json').write_text(json.dumps({'archive_sha256':'fixture'}),encoding='utf-8')
            with patch.dict(sys.modules,{'local_foundation_comparison':comparison}):
                with self.assertRaises(StopBeforeRuntime):course.run(base,None,None,lambda *args,**kwargs:None,execution_source_root=None,resource_base=None)
                self.assertEqual(archives[-1],base/'cache/model-pair-runtime-001.tar')
                with self.assertRaises(StopBeforeRuntime):
                    course.run(base,None,None,lambda *args,**kwargs:None,resume=True,continuation=continuation,
                               execution_source_root=source,resource_base=resources)
                self.assertEqual(archives[-1],resources/'cache/model-pair-runtime-001.tar')
            # Reach the explicit saved-bot branch without loading any model,
            # unpacking any archive, or entering the old observed-report writer.
            project=Path(temporary)/'tmp/ygo-kito-formal-source-fixture'
            for root in (source,project):
                (root/'src/ygo_kito').mkdir(parents=True)
                (root/'src/ygo_kito/probe.py').write_text('# fixture\n',encoding='utf-8')
            (reports/'source.json').write_text(json.dumps({'archive_sha256':'fixture'}),encoding='utf-8')
            (resources/'reports/native-runtime-cache-source-manifest.json').write_text(json.dumps({'cache_root':str(Path(temporary)/'native')}),encoding='utf-8')
            environment=resources/'source/.cache/local-base-training-20261027/2207-base-005/active-environment.local.json'
            environment.parent.mkdir(parents=True);environment.write_text('{}',encoding='utf-8')
            (state/'model-binding.json').write_text(json.dumps({'source_files':{'src/ygo_kito/probe.py':'fixture-script'}}),encoding='utf-8')
            initial=state/'initial.state';initial.write_bytes(b'fixture-state')
            (state/'initial-pointer.json').write_text(json.dumps({'path':str(initial),'sha256':'fixture-script'}),encoding='utf-8')
            package=types.ModuleType('ygo_kito');package.__path__=[]
            components={
                'build_contracts':dict(BuildTask=object,DeckParts=object,digest=lambda _:None),
                'build_pipeline':dict(verify_goal=None),'bot_deployment':dict(BotSourceRegistry=object),
                'course_models':dict(CourseModels=types.SimpleNamespace(from_state=lambda *a,**k:object())),
                'course_game_adapter':dict(CourseBotRuntime=object,course_config_from_dict=None),
                'data_isolation':dict(DataIndex=object),'group_runner':dict(tree_digest=None),
                'implementation_identity':dict(source_tree_snapshot=lambda _:self.fail('old observed report writer was entered')),
                'observed_bot_evidence':dict(KIND='fixture'),'period_runtime':dict(PeriodBuildAssets=lambda *a,**k:object()),
                'scenario_course':dict(ScenarioCourse=object)}
            modules={'ygo_kito':package,'torch':types.SimpleNamespace(set_num_threads=lambda _:None,load=lambda *a,**k:{})}
            for name,attributes in components.items():
                module=types.ModuleType('ygo_kito.'+name);module.__dict__.update(attributes);modules[module.__name__]=module
            comparison.unpack_exact=lambda *_:None;modules['local_foundation_comparison']=comparison
            class StopAfterSavedBots(Exception):pass
            selected=[]
            def saved_bots(target,actual_runtime):selected.append((target,actual_runtime));raise StopAfterSavedBots
            path_factory=lambda value:(Path(temporary)/'tmp' if str(value)=='/tmp' else Path(value))
            with patch.dict(sys.modules,modules),patch.object(sys,'path',list(sys.path)),\
                 patch.object(course,'Path',path_factory),patch.object(course.hashlib,'sha256',fake_hash),\
                 patch.object(course,'restore_readonly_cached_bot_audit',lambda *_:None),\
                 patch.object(course,'restore_saved_course_bots',saved_bots):
                with self.assertRaises(StopAfterSavedBots):
                    course.run(base,None,None,lambda *a,**k:None,resume=True,continuation=continuation,
                               execution_source_root=source,resource_base=resources)
            self.assertEqual(selected,[(state,Path(temporary)/'tmp/ygo-kito-model-pair-fixture')])
            runtime=Path(temporary)/'runtime';(runtime/'build').mkdir(parents=True)
            saved=resources/'reports/cached-bot-runtime-audit-001';saved.mkdir()
            names=('cached-build-audit.json','cache-audit-output.json','cache-audit-input.json')
            payloads={name:('recorded-'+name).encode() for name in names}
            identities={name:'saved-'+name for name in names}
            for name,data in payloads.items():
                (saved/name).write_bytes(data)
                if name!=names[-1]:(runtime/'build'/name).write_bytes(data)
            meta={'runtime_root':str(runtime),'files':identities,'completed_game_audit_sha256':identities[names[0]]}
            (saved/'manifest.json').write_text(json.dumps(meta),encoding='utf-8')
            plan=resources/'source/.cache/local-base-training-20261027/2207-base-006/paired-comparison-001/plan.json'
            plan.parent.mkdir(parents=True);plan.write_text(json.dumps({'driver':{'audit_sha256':identities[names[0]]}}),encoding='utf-8')
            originals={path:path.read_bytes() for path in (*saved.iterdir(),plan)}
            original_open=Path.open;original_mkdir=Path.mkdir
            def guarded_open(path,mode='r',*args,**kwargs):
                if path.resolve().is_relative_to(resources) and any(flag in mode for flag in 'wax+'):
                    self.fail('write attempted in original resource base: '+str(path))
                return original_open(path,mode,*args,**kwargs)
            def guarded_mkdir(path,*args,**kwargs):
                if path.resolve().is_relative_to(resources):self.fail('mkdir attempted in original resource base')
                return original_mkdir(path,*args,**kwargs)
            by_payload={data:identities[name] for name,data in payloads.items()}
            proof_relative='observed-course-evidence-006/profile.json'
            proof_data=b'{"original":"profile"}';by_payload[proof_data]='saved-profile'
            persisted=state/'runtime-evidence'/proof_relative;persisted.parent.mkdir(parents=True)
            persisted.write_bytes(proof_data)
            proof=runtime/proof_relative;proof.parent.mkdir(parents=True);proof.write_bytes(proof_data);proof.unlink()
            proof_manifest={'kind':'saved-runtime-proof-copies-v1','runtime_root':str(runtime),
                            'files':{'build/'+names[0]:identities[names[0]],proof_relative:'saved-profile'}}
            (state/'runtime-evidence-manifest.json').write_text(json.dumps(proof_manifest),encoding='utf-8')
            with patch.object(Path,'open',guarded_open),patch.object(Path,'mkdir',guarded_mkdir),\
                 patch.object(course.hashlib,'sha256',lambda data:types.SimpleNamespace(hexdigest=lambda:by_payload[data])):
                self.assertEqual(course.restore_readonly_cached_bot_audit(resources,runtime),runtime/'build'/names[0])
                course.restore_saved_runtime_proofs(state,runtime)
                self.assertEqual(proof.read_bytes(),proof_data)
                (runtime/'project/configs').mkdir(parents=True)
                (runtime/'project/configs/bot-sources-v1.json').write_text('{}',encoding='utf-8')
                bot={'deck':{'main':[1],'extra':[],'side':[]},'stage':'bots-bo1','purpose':'train',
                     'first_order':'always_first','coverage_label':'saved baseline','source':'user_provided',
                     'runtime':{'source_id':'ice','executor_id':'SavedExecutor','source_lock_sha256':'registry-lock',
                                'inventory_sha256':'saved-inventory','mono':'/saved/tools/mono','session_seconds':300}}
                for field,name in zip(('audit','qualification','qualification_profile'),names):
                    bot['runtime'][field]={'path':'build/'+name,'sha256':identities[name]}
                (state/'course-bots.json').write_text(json.dumps({'saved-bot':bot}),encoding='utf-8')
                registry=types.SimpleNamespace(lock={},inventory={'inventory_sha256':'saved-inventory'})
                constructors=[]
                def construct(*args,**kwargs):constructors.append((args,kwargs));return object()
                modules['ygo_kito.bot_deployment'].BotSourceRegistry=lambda *_:registry
                modules['ygo_kito.build_contracts'].DeckParts=types.SimpleNamespace(from_dict=lambda deck:dict(deck))
                modules['ygo_kito.build_contracts'].digest=lambda _:'registry-lock'
                modules['ygo_kito.course_game_adapter'].CourseBotRuntime=construct
                with patch.dict(sys.modules,modules):bots=course.restore_saved_course_bots(state,runtime)
                self.assertEqual(bots['saved-bot']['deck'],bot['deck'])
                self.assertEqual(constructors[0][0][7:9],('/saved/tools/mono','saved-bot'))
                self.assertEqual(constructors[0][1],{'source':'user_provided','session_seconds':300})
            self.assertEqual((runtime/'build'/names[-1]).read_bytes(),payloads[names[-1]])
            self.assertEqual({path:path.read_bytes() for path in originals},originals)


if __name__=='__main__':unittest.main()
