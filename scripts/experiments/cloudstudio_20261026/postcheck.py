import os
os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
import json,sys,time,hashlib,traceback
from pathlib import Path
import torch
from compare_actual import fresh,ROOT,OUT,STATE,SNAP,sync,distribution
from ygo_kito.cpu_training import save_checkpoint,load_checkpoint,resource_binding
from ygo_kito.duel_model import parameter_digest
from ygo_kito.hierarchical_policy import score_requests
from ygo_kito.normal_duel import request_digest
r={'kind':'actual-DTO-inference-and-CUDA-checkpoint-continuation','formal_games':0,'formal_updates':0,'status':'running','source_checkpoint_sha256':hashlib.sha256(SNAP.read_bytes()).hexdigest()}
try:
 profile=json.loads((ROOT/'.cache/codex-20261025/actor.json').read_text());tr=fresh('cuda:0',seeds=(530001,530002));binding=resource_binding(ROOT/'.cache',profile)
 first=tr.sample_episode(ROOT/'.cache',profile,purpose='train');first_update=tr.update(first);cp=save_checkpoint(tr,OUT/'cuda-recovery','after-1',binding);ep=tr.sample_episode(ROOT/'.cache',profile,purpose='train');continuous_update=tr.update(ep);expected=parameter_digest(tr.model);restored=load_checkpoint(cp,binding,device='cuda:0');replayed=restored.sample_episode(ROOT/'.cache',profile,purpose='train');restored_update=restored.update(replayed)
 r['recovery']={'checkpoint':str(cp),'checkpoint_sha256':hashlib.sha256(cp.read_bytes()).hexdigest(),'binding':binding,'first_update':first_update,'continuous_update':continuous_update,'restored_update':restored_update,'continuation_trajectory_equal':ep['summary']['trajectory_sha256']==replayed['summary']['trajectory_sha256'],'continuation_model_bit_equal':parameter_digest(restored.model)==expected,'complete_episode_boundaries':True,'physical_updates':3,'logical_updates':2}
 assert r['recovery']['continuation_trajectory_equal'] and r['recovery']['continuation_model_bit_equal']
 requests=[s['request'] for s in ep['steps'][:32]];assert len(requests)==32;r['input_request_sha256']=[request_digest(q) for q in requests];r['inference']={}
 ref=None
 for device in ('cpu','cuda:0'):
  t=fresh(device);t.model.eval();t.model.requires_grad_(False)
  with torch.no_grad():
   for _ in range(5):score_requests(t.model,t.encoder,requests)
   for q in requests[:10]:score_requests(t.model,t.encoder,[q])
   sync(device);logits,values=score_requests(t.model,t.encoder,requests);sync(device);current=(logits.cpu(),values.cpu())
   if ref is None:ref=current
   else:r['numeric']={'max_abs_logit_error':float((ref[0]-current[0]).abs().max()),'max_abs_value_error':float((ref[1]-current[1]).abs().max()),'all_greedy_actions_equal':bool(torch.equal(ref[0].argmax(1),current[0].argmax(1)))}
   rows={}
   for batch in (1,32):
    times=[]
    for k in range(96 if batch==1 else 20):
     chosen=[requests[k%32]] if batch==1 else requests;sync(device);start=time.perf_counter();score_requests(t.model,t.encoder,chosen);sync(device);times.append(time.perf_counter()-start)
    rows[str(batch)]={'wall_seconds':distribution(times),'samples_per_second':len(times)*batch/sum(times),'same_actual_inputs_across_devices':True}
   r['inference'][device]=rows
 r['status']='completed'
except Exception as e:r.update(status='failed_or_partial',error=str(e),traceback=traceback.format_exc());print(r['traceback'])
r['source_checkpoint_unchanged']=hashlib.sha256(SNAP.read_bytes()).hexdigest()==r['source_checkpoint_sha256'];(OUT/'exact-input-and-cuda-recovery.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
