#!/usr/bin/env python3
"""Bounded same-host FP32 project-model / native-engine CPU-CUDA comparison."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import sys,json,time,hashlib,subprocess,threading,traceback,resource,copy,argparse
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace,asdict
from collections import Counter
import torch
from ygo_kito.cpu_training import CpuTrainer,config_from_dict
from ygo_kito.training_pilot import TrainingPilot,_ObservedEngine,distribution
from ygo_kito.duel_model import parameter_digest
from ygo_kito.normal_duel import request_digest
from ygo_kito.native import NativeNormalEngine
from ygo_kito.implementation_identity import source_tree_snapshot
from ygo_kito.build_contracts import digest
ROOT=Path('/workspace');OUT=ROOT/'.cache/gpu-compare-20261026'
SNAP=ROOT/'.cache/codex-20261025/agent/runs/smoke-normal123/checkpoints/step-2.weights'
STATE=torch.load(SNAP,map_location='cpu',weights_only=True)
BASE=config_from_dict(STATE['config'])
torch.set_num_threads(1);torch.set_num_interop_threads(1)
torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
torch.use_deterministic_algorithms(True)
def sync(d):
 if str(d).startswith('cuda'):torch.cuda.synchronize(d)
def save(report,name):
 p=OUT/name;tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str));tmp.replace(p)
class Monitor:
 def __init__(self):self.stop=threading.Event();self.rows=[]
 def run(self):
  while not self.stop.is_set():
   r={'wall':time.time()}
   try:r['nvidia']=subprocess.check_output(['nvidia-smi','--query-gpu=utilization.gpu,utilization.memory,memory.used,power.draw','--format=csv,noheader,nounits'],text=True,timeout=3).strip()
   except Exception as e:r['monitor_error']=str(e)
   try:
    stat=Path('/proc/self/stat').read_text().split();r['process_cpu_seconds']=(int(stat[13])+int(stat[14]))/os.sysconf('SC_CLK_TCK');r['rss_bytes']=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
   except Exception as e:r['proc_error']=str(e)
   self.rows.append(r);self.stop.wait(1)
 def __enter__(self):self.t=threading.Thread(target=self.run,daemon=True);self.t.start();return self
 def __exit__(self,*args):self.stop.set();self.t.join(4)
class Meter:
 def __init__(self,model,device):
  self.d=device;self.forward_ms=[];self.requests=[];self.a=model.register_forward_pre_hook(self.pre);self.b=model.register_forward_hook(self.post)
 def pre(self,m,args):sync(self.d);self.tick=time.perf_counter()
 def post(self,m,args,out):sync(self.d);self.forward_ms.append((time.perf_counter()-self.tick)*1000)
 def close(self):self.a.remove();self.b.remove()
def engine_factory(obs,times):
 class Timed(_ObservedEngine):
  def __init__(self,*a,**kw):
   t=time.perf_counter();super().__init__(*a,pilot_observations=obs,**kw);times['constructor']+=time.perf_counter()-t
  def next_decision(self):
   t=time.perf_counter()
   try:return super().next_decision()
   finally:times['next_decision']+=time.perf_counter()-t
  def submit(self,*a,**kw):
   t=time.perf_counter()
   try:return super().submit(*a,**kw)
   finally:times['submit']+=time.perf_counter()-t
  def __exit__(self,*a):
   t=time.perf_counter()
   try:return super().__exit__(*a)
   finally:times['exit']+=time.perf_counter()-t
 return Timed
def observation():return {'engine_constructor_started':False,'engine_constructor_completed':False,'actual_first_player':None,'decision_windows':0,'seat_prompt_counts':Counter()}
def fresh(device,seat=0,seeds=(510001,)):
 cfg=replace(BASE,actor_seat=seat,game_seeds=tuple(seeds),episode_seconds=60.,native_decision_limit=3000)
 tr=CpuTrainer(cfg,STATE['card_ids'],device=device);tr.model.load_state_dict(STATE['model'],strict=True)
 assert parameter_digest(tr.model)==STATE['model_sha256']
 return tr
def warm(device,report):
 tr=fresh(device);profile=json.loads((ROOT/'.cache/codex-20261025/actor.json').read_text());t=time.perf_counter();ep=tr.sample_episode(ROOT/'.cache',profile,purpose='train');sync(device);s=time.perf_counter();u=tr.update(ep);sync(device)
 report['warmups'].append({'device':device,'kind':'excluded-real-normal-engine-episode-and-PPO-update','sampling_wall_seconds':s-t,'update_wall_seconds':time.perf_counter()-s,'summary':ep['summary'],'update':u});del tr
def frozen(report,spec):
 p=TrainingPilot(ROOT,ROOT/'.cache',spec);pre=p.preflight();report['preflight']=pre
 if pre['status']!='ready':raise RuntimeError('qualification/model preflight blocked: '+str(pre['blockers']))
 policy,cfg,prov,cases,sources,receipt=p._prepared
 report['frozen_planned']=len(cases)*2*2;report['frozen_attempts']=[]
 for rep in range(2):
  for ci,(case,profile,adapter) in enumerate(cases):
   devices=['cpu','cuda:0'] if (rep+ci)%2==0 else ['cuda:0','cpu']
   for device in devices:
    row={'device':device,'case_id':case['case_id'],'repeat':rep,'status':'in_flight','actor_seat':case['actor_seat'],'seed_pair':case['seeds'][0]};report['in_flight']=row;save(report,'comparison.json')
    sync(device);policy.model.to(device);policy.model.eval();meter=Meter(policy.model,device);obs=observation();times=Counter();view=SimpleNamespace(model=cfg.model,actor_seat=case['actor_seat'],game_seeds=cfg.game_seeds,episode_seconds=180.,native_decision_limit=3000,curriculum=None)
    sampler=SimpleNamespace(model=policy.model,encoder=policy.encoder,config=view,updates=prov['completed_updates']);pair=case['seeds'][0];tick=time.perf_counter();cpu=time.process_time()
    try:
     with Monitor() as mon:
      ep=CpuTrainer.sample_episode(sampler,ROOT/'.cache',profile,purpose='validation',seed=pair['game_seed'],policy_seed=pair['policy_seed'],opponent_adapter=adapter,engine_factory=engine_factory(obs,times));sync(device)
     row.update(status='completed',wall_seconds=time.perf_counter()-tick,process_cpu_seconds=time.process_time()-cpu,summary=ep['summary'],native_api_seconds=dict(times),forward_ms=meter.forward_ms,utilization_samples=mon.rows,actual_start_order='first' if obs['actual_first_player']==case['actor_seat'] else 'second',model_unchanged=parameter_digest(policy.model)==STATE['model_sha256']);del ep
    except Exception as e:row.update(status='failed',wall_seconds=time.perf_counter()-tick,error=str(e),traceback=traceback.format_exc(),forward_ms=meter.forward_ms,observations=obs)
    finally:meter.close()
    report['frozen_attempts'].append(row);report.pop('in_flight',None);save(report,'comparison.json');print('FROZEN',device,case['case_id'],rep,row['status'],row.get('wall_seconds'),flush=True)
    if row['status']!='completed':raise RuntimeError('frozen real game failed; stop remaining declared window')
 report['frozen_stats']={d:{'completed':sum(r['device']==d for r in report['frozen_attempts']),'game_seconds':distribution([r['summary']['elapsed_seconds'] for r in report['frozen_attempts'] if r['device']==d]),'wall_seconds':distribution([r['wall_seconds'] for r in report['frozen_attempts'] if r['device']==d]),'model_forward_ms':distribution([v for r in report['frozen_attempts'] if r['device']==d for v in r['forward_ms']]),'actor_full_inference_ms':distribution([v for r in report['frozen_attempts'] if r['device']==d for v in r['summary']['actor_inference_ms']])} for d in ('cpu','cuda:0')}
def training(report):
 report['training_planned']=16;report['training_attempts']=[];profile=json.loads((ROOT/'.cache/codex-20261025/actor.json').read_text())
 # Independent fresh on-policy episodes; both devices start from identical saved
 # model, fresh AdamW/RNG, same eight training seeds, batch 32 and FP32.
 for device in ('cpu','cuda:0'):
  tr=fresh(device,seeds=range(520001,520009));meter=Meter(tr.model,device)
  try:
   for i in range(8):
    row={'device':device,'step':i,'seed':520001+i,'status':'in_flight'};report['in_flight']=row;save(report,'comparison.json');tick=time.perf_counter();cpu=time.process_time();obs=observation();times=Counter();fm=len(meter.forward_ms)
    try:
     with Monitor() as mon:
      ep=tr.sample_episode(ROOT/'.cache',profile,purpose='train',engine_factory=engine_factory(obs,times));sync(device);sample_end=time.perf_counter();train_start=sample_end;u=tr.update(ep);sync(device);end=time.perf_counter()
     row.update(status='completed',sampling_wall_seconds=sample_end-tick,update_wall_seconds=end-train_start,wall_seconds=end-tick,process_cpu_seconds=time.process_time()-cpu,summary=ep['summary'],update=u,forward_ms=meter.forward_ms[fm:],native_api_seconds=dict(times),utilization_samples=mon.rows,model_after_sha256=parameter_digest(tr.model));del ep
    except Exception as e:row.update(status='failed',wall_seconds=time.perf_counter()-tick,error=str(e),traceback=traceback.format_exc())
    report['training_attempts'].append(row);report.pop('in_flight',None);save(report,'comparison.json');print('TRAIN',device,i,row['status'],row.get('update_wall_seconds'),flush=True)
    if row['status']!='completed':raise RuntimeError('training failed; stop remaining declared window')
   torch.save({'kind':'isolated-benchmark-weights-not-formal-checkpoint','device':device,'model':{k:v.detach().cpu() for k,v in tr.model.state_dict().items()},'source_sha256':STATE['model_sha256'],'updates':tr.updates},OUT/('benchmark-final-'+device.replace(':','')+'.weights'))
  finally:meter.close()
 report['training_stats']={d:{'completed_updates':sum(r['device']==d for r in report['training_attempts']),'sampling_seconds':distribution([r['sampling_wall_seconds'] for r in report['training_attempts'] if r['device']==d]),'update_seconds':distribution([r['update_wall_seconds'] for r in report['training_attempts'] if r['device']==d]),'total_seconds':distribution([r['wall_seconds'] for r in report['training_attempts'] if r['device']==d]),'batch_samples':sum(r['update']['batch_samples'] for r in report['training_attempts'] if r['device']==d),'samples_per_update_second':sum(r['update']['batch_samples'] for r in report['training_attempts'] if r['device']==d)/sum(r['update_wall_seconds'] for r in report['training_attempts'] if r['device']==d)} for d in ('cpu','cuda:0')}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['all','training'],default='all');args=ap.parse_args()
 report={'kind':'same-host-actual-model-engine-training-cpu-cuda-comparison','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_identity':digest(source_tree_snapshot(Path(__file__).resolve().parents[1]/'codex-gpu-20261026/src/ygo_kito')),'source_checkpoint':str(SNAP),'source_file_sha256':hashlib.sha256(SNAP.read_bytes()).hexdigest(),'source_model_sha256':STATE['model_sha256'],'source_completed_updates':STATE['updates'],'torch':str(torch.__version__),'cuda_runtime':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),'dtype':'float32','tf32':False,'torch_threads':torch.get_num_threads(),'batch_size':32,'warmups':[],'formal_games':0,'formal_updates':0,'started_utc':time.time(),'status':'running'}
 try:
  if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
  for device in ('cpu','cuda:0'):warm(device,report);save(report,'comparison.json')
  training(report)
  if args.mode=='all':frozen(report,json.loads((OUT/'pilot-spec.json').read_text()))
  report['status']='completed'
 except Exception as e:report.update(status='failed_or_partial',error=str(e),traceback=traceback.format_exc());print(report['traceback'],flush=True)
 report.update(ended_utc=time.time(),original_checkpoint_unchanged=hashlib.sha256(SNAP.read_bytes()).hexdigest()==report['source_file_sha256'],peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved());save(report,'comparison.json');print('FINAL',report['status'],report.get('training_stats'),report.get('frozen_stats'),flush=True)
if __name__=='__main__':main()
