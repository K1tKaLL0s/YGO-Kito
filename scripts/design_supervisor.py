"""Independent design observer using current pure contracts, never the trainer."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,os,signal,sqlite3,sys,time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ygo_kito.build_contracts import DeckParts
from ygo_kito.build_semantics import matches as matches_task_predicate
from ygo_kito.construction_progress import FUNCTIONAL_GATE_VERSION, _quality_binding
from ygo_kito.construction_quality import FUNCTIONAL_QUALITY_VERSION, functional_delta
from ygo_kito.validation import ContractError

EXTRA=0x40|0x2000|0x800000|0x4000000
class Unknown(Exception):pass
class Violation(Exception):pass
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
def utc():return datetime.now(timezone.utc).isoformat()
def write(path,value):
    tmp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)
def stable(path):
    try:
        a=path.stat()
        if a.st_size>40000000:raise Unknown('bounded evidence size exceeded: '+path.name)
        raw=path.read_bytes();b=path.stat()
        if (a.st_size,a.st_mtime_ns,a.st_ino)!=(b.st_size,b.st_mtime_ns,b.st_ino):raise Unknown('evidence still changing: '+path.name)
        return json.loads(raw),hashlib.sha256(raw).hexdigest()
    except (OSError,ValueError) as e:raise Unknown('missing, unreadable or partial evidence: '+path.name) from e
def alive(state):
    try:return state['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip() and Path('/proc',str(state['pid']),'stat').read_text().split()[21]==state['process_start_ticks']
    except (KeyError,OSError,IndexError):return False
def stop_main(base,policy,reason):
    directory=base/'reports/local-training'/policy['main_run_id'];directory.mkdir(parents=True,exist_ok=True)
    (directory/'stop.request').write_text('Independent design supervision requests safe boundary: '+reason+'\n',encoding='utf-8')
def confined(base,value):
    p=Path(value).resolve()
    if not p.is_relative_to(base.resolve()):raise Violation('policy path leaves project')
    return p

class Catalog:
    def __init__(self,base,policy):
        self.policy=policy;self.paths=[]
        for name in ('cards','banlist','releases'):
            item=policy[name];path=confined(base,item['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise Violation('pinned '+name+' identity differs')
            self.paths.append((path,path.stat().st_mtime_ns,path.stat().st_size))
        self.db=sqlite3.connect('file:'+self.paths[0][0].as_posix()+'?mode=ro',uri=True);self.db.row_factory=sqlite3.Row
        data,_=stable(self.paths[2][0])
        if data['period_id']!=policy['period_id'] or data['release_cutoff']!=policy['release_cutoff']:raise Violation('period boundary differs')
        self.released={r['card_id'] for r in data['cards'] if r['ocg_release_date']<=policy['release_cutoff']}
        self.limits={};active=False;found=False
        for line in self.paths[1][0].read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if line.startswith('!'):
                active=line[1:].strip()==policy['banlist_section'];found|=active;continue
            if active and line and not line.startswith('#'):
                values=line.split()
                if len(values)>=2 and values[0].isdigit() and values[1].isdigit():self.limits[int(values[0])]=int(values[1])
        if not found:raise Violation('declared banlist section is missing')
    def unchanged(self):
        for p,mtime,size in self.paths:
            s=p.stat()
            if s.st_mtime_ns!=mtime or s.st_size!=size:raise Unknown('pinned catalog changed during observation')
    def deck(self,deck,task=None,*,partial=False):
        if not isinstance(deck,dict) or set(deck)!={'main','extra','side'}:raise Violation('invalid three-section deck')
        bounds={'main':(0 if partial else 40,60),'extra':(0,15),'side':(0,15)};all_cards=[];rows={}
        for zone,(low,high) in bounds.items():
            cards=deck[zone]
            if not isinstance(cards,list) or not low<=len(cards)<=high:raise Violation('illegal '+zone+' size')
            if task and (len(cards)>task['sizes'][zone] or not partial and len(cards)!=task['sizes'][zone]):raise Violation('concrete deck misses declared section size')
            for code in cards:
                if type(code) is not int or not 0<code<2**32:raise Violation('invalid card ID')
                if task and code not in task['pool']:raise Violation('card outside declared task pool')
                if code not in rows:
                    row=self.db.execute('SELECT id,alias,ot,type,setcode,race,attribute,level FROM datas WHERE id=?',(code,)).fetchone()
                    if row is None:raise Violation('unknown card ID '+str(code))
                    rows[code]=dict(row)
                row=rows[code]
                if code not in self.released or not row['ot']&1:raise Violation('card outside the OCG period '+str(code))
                if row['type']&0x4000:raise Violation('token is not a deck card')
                if zone in ('main','extra') and bool(row['type']&EXTRA)!=(zone=='extra'):raise Violation('card type/section mismatch '+str(code))
                all_cards.append(code)
        aliases=Counter(rows[c]['alias'] or c for c in all_cards)
        for identity,count in aliases.items():
            if count>self.limits.get(identity,3):raise Violation('copy/banlist limit exceeded '+str(identity))
        if task:
            for r in task['requirements']:
                n=deck[r['zone']].count(r['card_id'])
                if not r['minimum']<=n<=r['maximum']:raise Violation('declared mandatory quantity missed')
            for c in task['goal'].get('constraints',[]):
                n=sum(matches_task_predicate(rows[code],c['predicate']) for zone in c['zones'] for code in deck[zone])
                if n>c['maximum'] or not partial and n<c['minimum']:raise Violation('declared hard constraint missed '+c['id'])

def inspect_artifact(path,root,catalog):
    result,sha=stable(path);phases=result.get('phases')
    handoffs=result.get('handoffs',[])
    if not handoffs or handoffs[0].get('role') not in ('build_goal', 'build_optimizer'):
        raise Unknown('construction handoff missing')
    first = handoffs[0]
    draft = result.get('effect_draft') if first['role'] == 'build_optimizer' else None
    if first['role'] == 'build_optimizer':
        from ygo_kito.construction_logic import ConstructionLogic
        try:
            logic = ConstructionLogic.from_dict(draft['logic'])
        except (ContractError, KeyError, TypeError) as error:
            raise Violation('invalid goal effect draft') from error
        if (draft.get('logic_sha256') != logic.sha256 or first.get('input_draft_sha256') != logic.sha256
                or draft.get('goal_sha256') != result.get('goal_sha256') or first.get('input_deck_sha256') is not None):
            raise Violation('optimizer seed differs from the goal effect draft')
    if any(p.get('role')!='build_optimizer' for p in handoffs[1:]):raise Violation('optimizer continuation changed role')
    if any(b.get('input_deck_sha256')!=a.get('output_deck_sha256') for a,b in zip(handoffs,handoffs[1:])):raise Violation('saved handoff ancestry differs')
    gate=result.get('construction_gate') or {}
    if (result.get('construction_passed') is not True or gate.get('status')!='passed'
            or gate.get('version')!=FUNCTIONAL_GATE_VERSION or gate.get('cb_result_used') is not False):
        raise Unknown('construction has not passed its pre-CB gate')
    if not isinstance(phases,list):raise Unknown('construction slice trace missing')
    handoff_links = {(h.get('role'), h.get('input_deck_sha256'), h.get('output_deck_sha256'))
                     for h in handoffs}
    previous = first['output_deck_sha256'] if draft is not None else None
    compact_skeletons = [first.get('unfilled')] if draft is not None else []
    compact = False
    for i,p in enumerate(phases):
        if p.get('role') not in ('build_goal','build_optimizer'):raise Violation('unknown construction role')
        fill=p.get('stage_3',{})
        if draft is not None and p['role'] == 'build_goal':
            if (fill.get('status') != 'effect_draft_ready' or p.get('effect_draft') != draft
                    or any(p.get(k) is not None for k in ('input_deck', 'proposal_deck', 'proposal_deck_sha256'))):
                raise Violation('goal stage must hand off only its effect draft')
            continue
        if 'proposal_deck_sha256' in p and 'proposal_deck' not in p:
            compact = True
            before, after = p.get('input_deck_sha256'), p['proposal_deck_sha256']
            if (p['role'], before, after) not in handoff_links or i and before != previous:
                raise Violation('phase inventory identity differs from its saved handoff')
            if fill.get('engine_validation_performed') is True:
                raise Violation('CB was executed inside an unfinished construction iteration')
            if p['role'] == 'build_goal':
                if fill.get('status') != 'axis_skeleton_ready':raise Unknown('goal skeleton status missing')
                compact_skeletons.append(p.get('unfilled'))
            else:
                selected = [row for row in fill.get('candidate_trace', {}).get('candidates', ())
                            if row.get('selected') is True]
                if (fill.get('selection_complete') is not True or len(selected) != 1
                        or selected[0].get('deck_sha256') != after):
                    raise Violation('phase selection differs from its saved handoff')
            previous = after
            continue
        if not isinstance(p.get('proposal_deck'),dict):raise Unknown('concrete phase output is not available')
        if i and digest(p.get('input_deck'))!=previous:raise Violation('actual deck handoff mismatch '+str(i+1))
        previous = digest(p['proposal_deck'])
        attempts=fill.get('attempts',[])
        concrete=([fill['concrete_proposal']] if p['role']=='build_goal' and
            fill.get('status')=='axis_skeleton_ready' and isinstance(fill.get('concrete_proposal'),dict) else
            [a['concrete_proposal'] for a in attempts if isinstance(a,dict) and 'concrete_proposal' in a])
        if not any(q.get('deck')==p['proposal_deck'] for q in concrete):raise Violation('phase output lacks its concrete fill record')
        # Intermediate fills may contain text/constraint checks, never CB runs.
        for a in attempts:
            v=a.get('engine_validation',{})
            if v.get('status','not_run')!='not_run':raise Violation('CB was executed inside an unfinished construction iteration')
    candidate=result.get('construction_candidate') or result.get('final_candidate') or result.get('best')
    output=(candidate or {}).get('deck')
    if not isinstance(output,dict) or digest(output)!=handoffs[-1]['output_deck_sha256']:raise Violation('final inventory differs from saved handoff')
    if gate.get('deck_sha256')!=digest(output):raise Violation('construction gate belongs to another deck')
    if compact and (candidate.get('concrete_proposal') or {}).get('deck') != output:
        raise Violation('final inventory differs from its concrete fill record')
    quality=candidate.get('quality_evaluation')
    if not isinstance(quality,dict) or quality.get('version')!=FUNCTIONAL_QUALITY_VERSION:
        raise Unknown('current functional quality evaluation is required before clearance')
    try:
        binding=_quality_binding(gate.get('policy'),quality,DeckParts.from_dict(output))
        if binding!=gate.get('quality_binding') or quality.get('task_sha256')!=gate.get('task_sha256'):
            raise ContractError('gate differs from its current quality binding')
        if not all(binding.get(k) is True for k in ('required','present','complete','scope_complete')):
            raise Unknown('current functional quality is not complete')
        if any(r['status']!='satisfied' for r in quality.get('hard_requirements',())):
            raise ContractError('original required functions do not support the reported pass')
        if candidate.get('construction_gate')!=gate:
            raise ContractError('candidate gate differs from the reported pass')
        policy=gate['policy']
        if policy['pass']['mode']=='reference_ratio':
            reference=(result.get('continuation') or {}).get('reference_evaluation')
            if not isinstance(reference,dict):raise Unknown('specified reference evaluation is missing')
            reference_binding=_quality_binding(policy,reference,DeckParts.from_dict(reference['inventory']))
            if (reference.get('deck_sha256')!=policy['pass']['reference']['deck_sha256']
                    or reference.get('task_sha256')!=gate.get('task_sha256')
                    or not reference_binding['complete'] or reference['score']['value']<=0
                    or any(r['status']!='satisfied' for r in reference.get('hard_requirements',()))
                    or functional_delta(reference,quality,ratio=policy['pass']['minimum_reference_ratio'])['lower']<0):
                raise ContractError('specified reference does not support the reported pass')
    except (ContractError,KeyError,TypeError) as error:
        raise Violation('current quality binding invalid: '+str(error)) from error
    cb=result.get('basic_cb')
    if cb is None:cb=result.get('final_cb') # Read historical terminology; no extra capability gate.
    if not isinstance(cb,dict):raise Unknown('basic CB inference record is not available')
    inference=cb.get('engine_validation',{})
    subject=cb.get('subject_deck_sha256',inference.get('deck_sha256'))
    if subject is None:raise Unknown('basic CB input identity is missing')
    if subject!=digest(output):raise Violation('basic CB result belongs to a different construction')
    if inference.get('deck_sha256',subject)!=subject:raise Violation('basic CB payload belongs to a different construction')
    task_sha=cb.get('task_sha256');raw=None;raw_path=None
    if inference.get('task_sha256',task_sha)!=task_sha:raise Violation('basic CB payload belongs to a different task')
    # Preserve namespace precedence; choose the first matching receipt within
    # each namespace by relative pathname, independent of filesystem order.
    paths=[path for pattern in ('basic-cb-inference-*.json','collaboration-v2-*/basic-cb-inference-*.json',
                               'construction-route-*.json','collaboration-v2-*/route-*.json')
           for path in sorted(root.glob(pattern),key=lambda p:p.relative_to(root).as_posix())]
    for route_path in paths:
        value,_=stable(route_path)
        if value.get('deck')==output and digest(value.get('task'))==task_sha:
            raw=value;raw_path=route_path
            if value.get('inference',{}).get('subject_deck_sha256')==subject:break
            if value.get('proof',{}).get('deck_sha256')==subject:break
    if raw is None:raise Unknown('basic CB source input record is missing')
    task=raw['task']
    if 'proof' in raw:
        proof=raw['proof']
        if not isinstance(proof,dict) or 'task_sha256' not in proof or 'deck_sha256' not in proof:
            raise Unknown('raw CB proof ownership fields are missing')
        if proof['task_sha256']!=digest(task) or proof['deck_sha256']!=digest(raw['deck']):
            raise Violation('raw CB proof does not correspond to its actual task and deck')
    for route in cb.get('routes',[]):
        proof=route.get('proof',{});derived=route.get('task')
        if not derived or 'task_sha256' not in proof or 'deck_sha256' not in proof:raise Unknown('inferred route proof ownership is missing')
        if proof['task_sha256']!=digest(derived) or proof['deck_sha256']!=subject:raise Violation('inferred route proof belongs to another task or construction')
    if catalog.policy.get('basic_cb_after_construction'):
        if any(k in task['goal'] for k in ('route_goal','required_activations','required_chain_resolutions')):
            raise Violation('construction imposes a preassigned CB route')
        if task.get('requirements',[])!=catalog.policy.get('construction_card_requirements',[]):
            raise Violation('construction imposes undeclared fixed card components')
        if raw.get('inference',{}).get('subject_deck_sha256')!=subject:
            raise Unknown('separate post-construction CB input record is missing')
    if task.get('environment',{}).get('release_cutoff')!=catalog.policy['release_cutoff']:raise Violation('task period differs')
    if result.get('selected_task_sha256')!=digest(task):raise Violation('construction and CB task identity differ')
    if gate.get('task_sha256')!=digest(task):raise Violation('current construction gate belongs to another task')
    if draft is not None and draft.get('unfilled') != task['sizes']:
        raise Violation('goal effect draft differs from the original slot counts')
    for unfilled in compact_skeletons:
        if (not isinstance(unfilled, dict) or unfilled.keys() != task['sizes'].keys()
                or any(type(n) is not int or not 0 <= n <= task['sizes'][zone] for zone,n in unfilled.items())):
            raise Violation('goal skeleton slot counts differ from the original task')
    for p in phases:
        if p.get('input_deck') is not None:catalog.deck(p['input_deck'],task,partial=any(len(p['input_deck'][z])<task['sizes'][z] for z in task['sizes']))
        if 'proposal_deck' in p:catalog.deck(p['proposal_deck'],task,partial=p['role']=='build_goal')
    catalog.deck(output,task)
    # Independently check the raw input and output association. Do not treat
    # cb_verified/passed or a whole-graph execution flag as conformance proof.
    if digest(raw['deck'])!=subject:raise Violation('raw CB input differs from construction')
    return {'artifact':str(path.relative_to(root)),'artifact_sha256':sha,'deck_sha256':subject,
        'task_sha256':task_sha,'cb_source':str(raw_path.relative_to(root)),
        'checked':['role_handoffs_and_pre_cb_gate','basic_cb_subject','card_id_type_quantity_period'],
        'phase_inventory_check':'handoff_identity' if compact else 'full_lists',
        'whole_graph_execution_or_competitive_strength_certified':False}

def audit(base,policy,catalog):
    root=confined(base,policy['course_root']);catalog.unchanged()
    initial = root/'initial-formal-construction.json'
    paths = sorted(root.glob('collaboration-v2-*/construction-result.json'))
    if initial.exists():
        current, _ = stable(initial)
        task_sha = current.get('selected_task_sha256')
        paths = [path for path in paths if stable(path)[0].get('selected_task_sha256') == task_sha]
    else:
        initial = root/'initial-construction.json'
    if not initial.exists():raise Unknown('awaiting initial construction evidence; formal clearance withheld')
    paths.insert(0, initial)
    receipts=[]
    for path in paths:receipts.append(inspect_artifact(path,root,catalog))
    for value in policy.get('opponent_decks',[]):
        data,_=stable(confined(base,value));catalog.deck(data)
    return receipts

def main():
    import fcntl
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--policy',type=Path,required=True);p.add_argument('--once',action='store_true');p.add_argument('--status',action='store_true');p.add_argument('--resume',action='store_true')
    a=p.parse_args();base=a.base.resolve();directory=base/'reports/local-training'/a.run_id;directory.mkdir(parents=True,exist_ok=True)
    if a.status:
        value,_=stable(directory/'status.json');value['process_identity_verified']=alive(value);print(json.dumps(value));return
    policy,policy_sha=stable(a.policy);stop=directory/'stop.request'
    if stop.exists():
        if not a.resume:raise RuntimeError('Previous supervisor stop preserved; use Resume')
        stop.rename(stop.with_name('prior-stop-'+str(time.time_ns())+'.request'))
    mutex=(directory/'active.mutex').open('a+b');fcntl.flock(mutex.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    identity={'run_id':a.run_id,'job':'supervisor','pid':os.getpid(),'process_start_ticks':Path('/proc/self/stat').read_text().split()[21],
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'policy_sha256':policy_sha}
    state=dict(identity,started_utc=utc(),verdict='unknown',desired='running',receipts=[])
    def save():state['heartbeat_utc']=utc();write(directory/'status.json',state)
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    signal.signal(signal.SIGTERM,lambda *_:stop.write_text('stop supervisor at observation boundary\n'))
    unknowns=0
    try:
        catalog=Catalog(base,policy)
        while not stop.exists():
            try:
                if stable(a.policy)[1]!=policy_sha:raise Unknown('supervisor policy changed; explicit restart required')
                receipts=audit(base,policy,catalog)
                if not a.once:
                    current,_=stable(base/'reports/local-training'/policy['main_run_id']/'status.json')
                    if current.get('desired')=='running':
                        if not alive(current):raise Unknown('main process identity is unknown')
                        age=(datetime.now(timezone.utc)-datetime.fromisoformat(current['heartbeat_utc']).astimezone(timezone.utc)).total_seconds()
                        if age>45:raise Unknown('main heartbeat is stale')
                state.update(verdict='clear',reason=None,receipts=receipts);unknowns=0
            except Violation as error:
                state.update(verdict='violation',reason=str(error),receipts=[]);stop_main(base,policy,str(error))
            except Unknown as error:
                state.update(verdict='unknown',reason=str(error),receipts=[]);unknowns+=1
                bootstrap=str(error).startswith('awaiting initial construction evidence;')
                if (a.once or unknowns>=2) and not bootstrap:stop_main(base,policy,'unknown: '+str(error))
            save()
            if a.once:
                print(json.dumps(state));return 0 if state['verdict']=='clear' else 2 if state['verdict']=='violation' else 3
            time.sleep(2)
        stop_main(base,policy,'supervisor stopped');state.update(desired='stopped',verdict='unknown',reason='supervisor stopped');save()
    except Exception as error:
        state.update(desired='failed',verdict='unknown',reason='supervisor fault: '+repr(error));save();stop_main(base,policy,state['reason']);raise
    finally:
        fcntl.flock(mutex.fileno(),fcntl.LOCK_UN);mutex.close()
    return 0
if __name__=='__main__':raise SystemExit(main())
