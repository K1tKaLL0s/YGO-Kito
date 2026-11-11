"""Explicit bounded environment training recipe; base model stays unchanged."""
from dataclasses import asdict
import json
from pathlib import Path

from ygo_kito.multifactor.contracts import FactorContractError


def comparison_recipes(base):
    from copy import deepcopy
    plans=[]
    for mode in ("head_only","lora_head","full_copy"):
        config=deepcopy(base)
        config["adapter"]=dict(config.get("adapter",{}),mode=mode,
            learning_rate=base.get("full_copy_learning_rate",.0001) if mode=="full_copy" else base.get("adapter_learning_rate",.001))
        config["run_dir"]=str(Path(base["run_dir"])/mode)
        plans.append(config)
    return plans


def fit(config):
    # Gate precedes data access, Torch import, directory creation or loading.
    engineering=config.get("execution_mode")=="engineering_fixture"
    if config.get("formal_training") is not (False if engineering else True):
        raise FactorContractError("environment training remains paused")
    if config.get("automatic_lora") is not False or config.get("core_course_resumed") is not False:
        raise FactorContractError("environment run cannot activate a course or model")
    if engineering and (config.get("base",{}).get("device")!="cpu" or not 1<=config.get("max_records",0)<=64 or not 1<=config.get("epochs",0)<=3):
        raise FactorContractError("engineering environment run requires bounded CPU fixtures")
    for name in ("epochs","batch_size"):
        if type(config.get(name)) is not int or not 1<=config[name]<=(64 if name=="batch_size" else 10000):
            raise FactorContractError("invalid environment "+name)
    mode=config.get("load_mode","fresh")
    if mode not in ("fresh","resume"):
        raise FactorContractError("explicit environment fresh/resume required")
    run=Path(config["run_dir"]).resolve(); data=Path(config["records_file"]).resolve()
    if data==run or run in data.parents or run.exists() and mode=="fresh" and any(run.iterdir()):
        raise FactorContractError("environment run needs a separate new output directory")
    from ygo_kito.multifactor.environment import EnvironmentAdapter,EnvironmentConfig
    from ygo_kito.multifactor.network import NetworkConfig
    from ygo_kito.multifactor.training import RoleTrainer
    from ygo_kito.multifactor.calibration import write_new,Calibration,host_capabilities
    from ygo_kito.multifactor.contracts import digest
    from training.axis_generic.runtime import training_lock
    payload=json.loads(data.read_text("utf-8-sig"))
    if payload.get("version")!="axis-environment-feedback-v3":
        raise FactorContractError("versioned environment feedback required")
    rows=payload["records"]
    if not rows or engineering and len(rows)>config["max_records"]:
        raise FactorContractError("environment record budget exceeded")
    ids=set()
    for row in rows:
        source=row["source"]
        if (not row.get("record_id") or row["record_id"] in ids or source.get("partition")!="train" or
                source.get("kind")!=("engineering_fixture" if engineering else "environment_feedback")):
            raise FactorContractError("environment runner only consumes distinct matching train records")
        EnvironmentAdapter.features(row["environment"])
        EnvironmentAdapter.validate_feedback([row["observations"]],[row["environment"]],[row["value"]],[source],engineering_mode=engineering)
        ids.add(row["record_id"])
    recipe={k:v for k,v in config.items() if k not in ("run_dir","load_mode","adapter_checkpoint")}
    identity=dict(recipe=digest(recipe),records=digest(payload))
    with training_lock(run):
        identity_path=run/"experiment.json"
        if mode=="resume" and (not identity_path.exists() or json.loads(identity_path.read_text("utf-8"))!=identity):
            raise FactorContractError("environment resume data/recipe differs")
        if mode=="fresh" and any(p.name!=".training.lock" for p in run.iterdir()):
            raise FactorContractError("new environment experiment directory is not empty")
        base_config=config["base"]
        trainer=RoleTrainer.load(base_config["checkpoint"],mode="inference",expected_config=NetworkConfig(**base_config["network"]),
            expected_binding=base_config["binding"],expected_label_protocol_sha256=base_config["label_protocol_sha256"],device=base_config["device"])
        capabilities={}
        if not engineering:
            def read(path):return json.loads(Path(path).read_text("utf-8-sig"))
            capabilities=host_capabilities(read(base_config["release"]),Calibration.load(base_config["calibration"]),trainer,
                evidence_ref=base_config["assessment_report"],assessment_report=read(base_config["assessment_report"]),
                baseline_report=read(base_config["baseline_report"]))
        adapter=(EnvironmentAdapter.load(trainer,config["adapter_checkpoint"]) if mode=="resume" else
                 EnvironmentAdapter(trainer,EnvironmentConfig(**config["adapter"]),engineering_mode=engineering,base_capabilities=capabilities))
        if asdict(adapter.config)!=asdict(EnvironmentConfig(**config["adapter"])) or adapter.engineering_mode!=engineering:
            raise FactorContractError("environment resume adapter configuration differs")
        if mode=="resume" and adapter.experiment_binding!=digest(identity):
            raise FactorContractError("environment checkpoint belongs to different records/recipe")
        if adapter.base_capabilities!={k:asdict(v) for k,v in capabilities.items()}:
            raise FactorContractError("environment resume base capability evidence differs")
        adapter.experiment_binding=digest(identity)
        cursor=json.loads(adapter.data_cursor) if adapter.data_cursor else dict(epoch=0,next_row=0)
        if set(cursor)!={"epoch","next_row"} or any(type(v) is not int or v<0 for v in cursor.values()) or cursor["epoch"]>config["epochs"] or cursor["next_row"]>=len(rows) or cursor["epoch"]==config["epochs"] and cursor["next_row"]!=0:
            raise FactorContractError("invalid environment resume cursor")
        if cursor["next_row"]%config["batch_size"]!=0:
            raise FactorContractError("environment resume cursor is not a batch boundary")
        if mode=="fresh":
            write_new(identity_path,identity)
            write_new(run/"recipe.json",config)
        latest=config.get("adapter_checkpoint")
        for epoch in range(cursor["epoch"],config["epochs"]):
            start=cursor["next_row"] if epoch==cursor["epoch"] else 0
            for index in range(start,len(rows),config["batch_size"]):
                part=rows[index:index+config["batch_size"]]
                next_row=index+len(part)
                next_cursor=dict(epoch=epoch+int(next_row==len(rows)),next_row=0 if next_row==len(rows) else next_row)
                adapter.train([r["observations"] for r in part],[r["environment"] for r in part],
                    [r["value"] for r in part],[r["source"] for r in part],data_cursor=json.dumps(next_cursor,sort_keys=True))
                latest=run/f"environment-e{next_cursor['epoch']:04d}-r{next_cursor['next_row']:07d}.pt"
                adapter.save(latest)
        return dict(adapter_checkpoint=str(latest),adapter_id=adapter.identity(),steps=adapter.steps,
                    base_changed=False,capability_accepted=False,formal_training=not engineering)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",required=True)
    args=parser.parse_args()
    result=fit(json.loads(Path(args.config).read_text("utf-8-sig")))
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
