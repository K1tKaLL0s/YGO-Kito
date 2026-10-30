"""Independent subprocess checks using isolated synthetic records, never native games."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v),encoding='utf-8')

class IndependentDesignSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        self.script=ROOT/'scripts/design_supervisor.py';self.guard=ROOT/'scripts/local_design_supervision.py'
        self.course=self.base/'course';self.course.mkdir()
        ids=list(range(1,25))+list(range(1001,1016));db=self.base/'cards.cdb'
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE datas(id INTEGER PRIMARY KEY,alias INTEGER,ot INTEGER,type INTEGER,setcode INTEGER,race INTEGER,attribute INTEGER)')
            c.executemany('INSERT INTO datas VALUES(?,?,?,?,?,?,?)',[(n,0,1,0x41 if n>=1000 else 17,385 if n in (1,2,3,4,1001,1002,1003) else 0,1,32) for n in ids])
        ban=self.base/'banlist.conf';ban.write_text('!2022.7\n',encoding='utf-8')
        release=self.base/'releases.json';write(release,{'period_id':'2022-07','release_cutoff':'2022-09-30','cards':[{'card_id':n,'ocg_release_date':'2021-01-01'} for n in ids]})
        self.task={'pool':ids,'sizes':{'main':40,'extra':15,'side':15},'requirements':[],
            'environment':{'release_cutoff':'2022-09-30'},'goal':{'kind':'deck_constraints','constraints':[]}}
        deck={'main':[n for n in range(1,14) for _ in range(3)]+[14],'extra':list(range(1001,1016)),
              'side':[n for n in range(15,20) for _ in range(3)]}
        phases=[];previous=None
        for i,role in enumerate(('build_goal','build_optimizer','build_goal','build_optimizer')):
            output=deepcopy(deck);output['main'][-1]=20+i
            concrete={'deck':output,'task_sha256':digest(self.task),'logic_sha256':str(i)*64}
            phases.append({'phase_number':i+1,'role':role,'input_deck':previous,'proposal_deck':output,
                'stage_1':{'logic_sha256':str(i)*64},'stage_3':{'attempts':[{'concrete_proposal':concrete,'engine_validation':{'status':'not_run'}}]}})
            previous=deepcopy(output)
        cb={'task_sha256':digest(self.task),'subject_deck_sha256':digest(previous),
            'engine_validation':{'status':'synthetic_inference_not_engine_execution','deck_sha256':digest(previous)}}
        self.result={'phases':phases,'construction_candidate':{'deck':previous},'basic_cb':cb,
            'selected_task_sha256':digest(self.task),'cb_verified':False,'passed':False}
        self.path=self.course/'initial-four-stage-construction.json';write(self.path,self.result)
        write(self.course/'basic-cb-inference-001.json',{'task':self.task,'deck':previous,'inference':cb})
        self.policy={'main_run_id':'fixture-main','supervisor_run_id':'fixture-supervisor','course_root':str(self.course),
            'period_id':'2022-07','release_cutoff':'2022-09-30','banlist_section':'2022.7','basic_cb_after_construction':True,'construction_card_requirements':[],
            'supervisor_script_sha256':hashlib.sha256(self.script.read_bytes()).hexdigest()}
        for name,path in (('cards',db),('banlist',ban),('releases',release)):
            self.policy[name]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        self.policy_path=self.base/'reports/design-supervision-policy.json';write(self.policy_path,self.policy)
    def observe(self,expected):
        p=subprocess.run([sys.executable,str(self.script),'--base',str(self.base),'--run-id','fixture-supervisor','--policy',str(self.policy_path),'--once'],capture_output=True,text=True)
        self.assertEqual(p.returncode,expected,p.stdout+p.stderr)
        value=json.loads((self.base/'reports/local-training/fixture-supervisor/status.json').read_text())
        return value
    def stopped(self):return (self.base/'reports/local-training/fixture-main/stop.request').exists()
    def test_separate_process_accepts_correct_evidence_without_trusting_main_flags(self):
        value=self.observe(0);self.assertEqual(value['verdict'],'clear');self.assertNotEqual(value['pid'],__import__('os').getpid());self.assertFalse(self.stopped())
    def test_detects_wrong_real_deck_handoff_despite_passed_flag(self):
        self.result['passed']=True;self.result['cb_verified']=True;self.result['phases'][2]['input_deck']=deepcopy(self.result['phases'][0]['proposal_deck'])
        write(self.path,self.result);self.assertEqual(self.observe(2)['verdict'],'violation');self.assertTrue(self.stopped())
    def test_detects_cb_payload_for_old_deck_even_when_subject_is_claimed_correct(self):
        self.result['basic_cb']['engine_validation']['deck_sha256']='0'*64;self.result['cb_verified']=True
        write(self.path,self.result);self.assertEqual(self.observe(2)['verdict'],'violation');self.assertTrue(self.stopped())
    def test_detects_actual_card_type_section_mismatch(self):
        self.result['phases'][0]['input_deck']=deepcopy(self.result['phases'][0]['proposal_deck'])
        self.result['phases'][0]['input_deck']['extra'][0]=1;write(self.path,self.result)
        self.assertIn('type/section',self.observe(2)['reason'])
    def test_side_deck_may_legally_contain_extra_deck_monsters(self):
        self.result['phases'][0]['input_deck']=deepcopy(self.result['phases'][0]['proposal_deck'])
        self.result['phases'][0]['input_deck']['side'][0]=1001;write(self.path,self.result)
        self.assertEqual(self.observe(0)['verdict'],'clear')
    def test_rejects_same_deck_cb_payload_for_wrong_task(self):
        self.result['basic_cb']['engine_validation']['task_sha256']='0'*64;write(self.path,self.result)
        self.assertIn('different task',self.observe(2)['reason'])
    def test_rejects_raw_proof_for_wrong_task_even_when_deck_matches(self):
        path=self.course/'basic-cb-inference-001.json';raw=json.loads(path.read_text())
        raw['proof']={'deck_sha256':digest(raw['deck']),'task_sha256':'0'*64};write(path,raw)
        self.assertIn('raw CB proof',self.observe(2)['reason'])
    def test_detects_unknown_card_identity(self):
        self.result['phases'][0]['input_deck']=deepcopy(self.result['phases'][0]['proposal_deck'])
        self.result['phases'][0]['input_deck']['main'][0]=999999999;write(self.path,self.result)
        self.assertEqual(self.observe(2)['verdict'],'violation')
    def test_detects_wrong_declared_quantity(self):
        self.result['phases'][0]['input_deck']=deepcopy(self.result['phases'][0]['proposal_deck'])
        self.result['phases'][0]['input_deck']['main'].append(24);write(self.path,self.result)
        self.assertIn('size',self.observe(2)['reason'])
    def test_partial_write_is_unknown_and_safe_stops_instead_of_claiming_violation(self):
        self.path.write_text('{"phases":',encoding='utf-8');self.assertEqual(self.observe(3)['verdict'],'unknown');self.assertTrue(self.stopped())
    def test_observer_fault_is_not_silent_permission(self):
        self.policy['cards']['sha256']='0'*64;write(self.policy_path,self.policy)
        value=self.observe(1);self.assertEqual(value['verdict'],'unknown');self.assertEqual(value['desired'],'failed');self.assertTrue(self.stopped())
    def test_preassigned_cb_goal_is_not_allowed_to_constrain_construction(self):
        self.task['goal']['route_goal']={'kind':'synchro_summon','card_id':1001}
        self.result['selected_task_sha256']=digest(self.task);self.result['basic_cb']['task_sha256']=digest(self.task)
        write(self.path,self.result)
        write(self.course/'basic-cb-inference-001.json',{'task':self.task,'deck':self.result['construction_candidate']['deck'],'inference':self.result['basic_cb']})
        self.assertIn('preassigned',self.observe(2)['reason'])
    def test_dead_observer_receipt_cannot_open_formal_guard(self):
        self.observe(0)
        p=subprocess.run([sys.executable,str(self.guard),'--base',str(self.base)],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)

if __name__=='__main__':unittest.main()
