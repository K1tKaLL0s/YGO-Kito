import os
os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
import json,time,traceback,hashlib,sys
from pathlib import Path
from dataclasses import replace
import torch
from compare_actual import sync,distribution,ROOT,OUT,Monitor
from ygo_kito.build_pipeline import BuildAssets,BuildTask
from ygo_kito.build_training import BuildTrainer,BuildTrainingConfig,engineering_dataset
from ygo_kito.cpu_training import CpuTrainer,config_from_dict
from ygo_kito.coordinator_model import CoordinatorTrainer,CoordinatorModelConfig
from ygo_kito.group_initialization import initialize_group_weights
from ygo_kito.duel_model import parameter_digest
from ygo_kito.build_contracts import digest
REPO=Path('/workspace/.cache/codex-gpu-20261026')
r={'kind':'same-source-four-model-representative-real-update-comparison','status':'running','formal_games':0,'formal_updates':0,'repeats_per_device':3,'warmup_cycles_per_device':1,'dtype':'float32','duel_batch_size':32,'rows':[]}
try:
 assets=BuildAssets(ROOT/'.cache');task=BuildTask.from_dict(json.loads((REPO/'configs/build-engineering-v1.json').read_text()));spec=json.loads((OUT/'source-group-reference.json').read_text());r['source_group']=spec
 tick=time.perf_counter();data=engineering_dataset(task,assets);r['shared_supervision']={'source':data['source'],'supervision_sha256':data['supervision_sha256'],'goal_records':len(data['goals']),'preference_pairs':len(data['pairs']),'preparation_seconds':time.perf_counter()-tick,'data_kind':'existing-engineering-conditional-native-goals-and-weak-preferences'}
 profile=json.loads((REPO/'configs/effect-duel-v1.json').read_text());r['profile_sha256']=digest(profile);r['coordinator_supervision']='existing-explicit-engineering-aggregate-supervision'
 for device in ('cpu','cuda:0'):
  cfg=replace(config_from_dict({}),game_seeds=(1724,1725,1726,1727),episode_seconds=60.,batch_size=32)
  builder=BuildTrainer(task,assets,BuildTrainingConfig(batches=4),device=device);duel=CpuTrainer(cfg,sorted(c for c in assets.rows if 0<c<2**32),device=device);coord=CoordinatorTrainer(CoordinatorModelConfig(steps=4),device=device)
  init=initialize_group_weights(builder,duel,coord,workspace=ROOT,spec=spec);models=dict(builder.models,duel=duel.model,coordinator=coord.model)
  r.setdefault('initialization',{})[device]={'provenance':init,'initial_model_sha256':{k:parameter_digest(m) for k,m in models.items()},'parameter_counts':{k:sum(p.numel() for p in m.parameters()) for k,m in models.items()},'actual_parameter_devices':{k:sorted({str(p.device) for p in m.parameters()}) for k,m in models.items()}}
  for i in range(4):
   row={'device':device,'cycle':i,'warmup':i==0,'status':'in_flight'};tick=time.perf_counter();cpu=time.process_time()
   with Monitor() as mon:
    sync(device);start=time.perf_counter();ep=duel.sample_episode(ROOT/'.cache',profile,purpose='train');sync(device);sample_end=time.perf_counter();u=duel.update(ep);sync(device);duel_end=time.perf_counter();b=builder.step(data);sync(device);build_end=time.perf_counter();c=coord.step();sync(device);end=time.perf_counter()
   row.update(status='completed',sample_seconds=sample_end-start,duel_update_seconds=duel_end-sample_end,paired_build_update_seconds=build_end-duel_end,coordinator_update_seconds=end-build_end,total_seconds=end-tick,process_cpu_seconds=time.process_time()-cpu,duel_summary=ep['summary'],duel_update=u,build_updates=b,coordinator_update=c,utilization_samples=mon.rows);r['rows'].append(row);(OUT/'group-update-comparison.json').write_text(json.dumps(r,indent=2));print('GROUP',device,i,row['total_seconds'],row['duel_update_seconds'],row['paired_build_update_seconds'],row['coordinator_update_seconds'],flush=True)
  dest=OUT/('group-benchmark-final-'+device.replace(':','')+'.weights');torch.save({'kind':'four-model-benchmark-weights','source_group':spec,'models':{role:{k:v.detach().cpu() for k,v in m.state_dict().items()} for role,m in models.items()},'updates':{'duel':duel.updates,'build':builder.updates,'coordinator':coord.updates}},dest)
 r['initial_model_weights_equal']=r['initialization']['cpu']['initial_model_sha256']==r['initialization']['cuda:0']['initial_model_sha256'];assert r['initial_model_weights_equal']
 r['paired_trajectory_equal']=[r['rows'][i]['duel_summary']['trajectory_sha256']==r['rows'][4+i]['duel_summary']['trajectory_sha256'] for i in range(4)]
 r['summary']={d:{key:distribution([a[key] for a in r['rows'] if a['device']==d and not a['warmup']]) for key in ('sample_seconds','duel_update_seconds','paired_build_update_seconds','coordinator_update_seconds','total_seconds')} for d in ('cpu','cuda:0')};r['status']='completed'
except Exception as e:r.update(status='failed_or_partial',error=str(e),traceback=traceback.format_exc());print(r['traceback'],flush=True)
r['source_group_unchanged']=hashlib.sha256((ROOT/spec['path']).read_bytes()).hexdigest()==spec['sha256'];(OUT/'group-update-comparison.json').write_text(json.dumps(r,indent=2));print('GROUP_FINAL',r['status'],json.dumps(r.get('summary')),flush=True)
