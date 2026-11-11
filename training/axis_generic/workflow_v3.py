"""Explicit offline T3/T4 workflow. No stage runs on import."""
from copy import deepcopy
import json
import math
import gzip
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from ygo_kito.multifactor.calibration import (Calibration, ENGINEERING_SOURCES, REAL_SOURCES, fit_calibration, write_new,
    bound_predictions, prediction_bundle, DEFAULT_POLICY, release_candidate)
from ygo_kito.multifactor.contracts import FactorContractError, TASK_DOMAINS, digest
from ygo_kito.multifactor.task_queries import BINARY_COORDINATES, CATEGORY_COORDINATES, LEARNED_TASKS, record_sources, record_graph_size
from assessment import assess_records, prediction_key
from prepare_v3 import iter_target_cells,verify_preparation_implementation



def evaluation_records(dataset_dir,fold,*,groups=None):
    """Read only an explicitly requested evaluation fold with shard identity checks."""
    if fold not in ("validation","test","retrospective_test"):
        raise FactorContractError("offline evaluation cannot read training/quarantine shards")
    root=Path(dataset_dir).resolve()
    manifest=json.loads((root/"dataset.json").read_text("utf-8-sig"))
    if manifest.get("version")!="axis-dataset-v3":
        raise FactorContractError("versioned prepared evaluation dataset required")
    verify_preparation_implementation(manifest)
    selected=None if groups is None else set(groups)
    rows=[];ids=set();actual=set()
    for shard in sorted(manifest["shards"].get(fold,()),key=lambda s:s["file"]):
        path=(root/shard["file"]).resolve()
        if not path.is_relative_to(root):
            raise FactorContractError("evaluation shard escapes dataset directory")
        with gzip.open(path,"rt",encoding="utf-8") as stream:
            part=[json.loads(line) for line in stream]
        if len(part)!=shard["records"] or digest(part)!=shard["semantic_records"]:
            raise FactorContractError("evaluation shard content differs from manifest")
        for row in part:
            if row.get("schema_version")!="axis-training-record-v3" or row["supervision"]["partition"]!=fold or row["record_id"] in ids:
                raise FactorContractError("evaluation shard schema/partition/record identity differs")
            record_sources(row)
            ids.add(row["record_id"])
            group=row["provenance"]["leakage_group"]
            if selected is None or group in selected:
                rows.append(row);actual.add(group)
    if not rows or selected is not None and actual!=selected:
        raise FactorContractError("requested evaluation groups are absent")
    return rows,manifest["preparation_identity"]["semantic_id"]


def predict_records(trainer,records,*,batch_size=32):
    from train_v3 import predict_saved
    if type(batch_size) is not int or not 1<=batch_size<=64:
        raise FactorContractError("prediction batch size must be 1..64")
    if len({r["record_id"] for r in records})!=len(records):
        raise FactorContractError("duplicate prediction record identity")
    parts=[];part=[];nodes=edges=graphs=0
    for row in records:
        record_sources(row,label_protocol_sha256=trainer.label_protocol_sha256)
        n,e,count=record_graph_size(row)
        if n>trainer.model.config.graph_node_budget or e>trainer.model.config.graph_edge_budget:
            raise FactorContractError("single evaluation graph exceeds tensor budget")
        if part and (len(part)==batch_size or nodes+n>trainer.model.config.graph_node_budget or edges+e>trainer.model.config.graph_edge_budget or graphs+count>64):
            parts.append(part);part=[];nodes=edges=graphs=0
        part.append(row);nodes+=n;edges+=e;graphs+=count
    if part:parts.append(part)
    predictions={}
    for part in parts:
        predictions.update(predict_saved(trainer,part))
    return predictions

def ablation_recipes(base, *, selected=None, seeds=None):
    """Four one-seed cells; explicit chosen baseline/candidate get three seeds."""
    cells={f"{stream}-route{int(route)}":(stream,route) for stream in ("single","dual") for route in (False,True)}
    chosen=list(cells) if selected is None else list(selected)
    seed_list=[base["seed"]] if seeds is None else list(seeds)
    if (len(set(chosen))!=len(chosen) or set(chosen)-set(cells) or
            selected is None and len(seed_list)!=1 or selected is not None and (len(chosen)!=2 or len(seed_list)!=3) or
            len(set(seed_list))!=len(seed_list) or any(type(s) is not int or not 0<=s<2**31 for s in seed_list)):
        raise FactorContractError("four-cell first round or two explicitly chosen cells with three distinct seeds required")
    recipes=[]
    for name in chosen:
        for seed in seed_list:
            config=deepcopy(base)
            config["network"].update(stream_mode=cells[name][0],use_route_features=cells[name][1],seed=seed)
            config.update(seed=seed,load_mode="fresh",checkpoint=None,
                          run_dir=str(Path(base["run_dir"])/(name+f"-seed{seed}")))
            recipes.append(dict(cell=name,seed=seed,config=config))
    return recipes


def compare_ablation(results):
    """Only development selection scores with identical data and budgets."""
    if not results:
        raise FactorContractError("ablation results required")
    identity=results[0]["comparison_binding"]
    budget_keys=("dataset","split","epochs","effective_batch_size","optimizer","selection_groups")
    if any(k not in identity for k in budget_keys):
        raise FactorContractError("ablation data/budget/source binding incomplete")
    seen=set(); grouped={}
    for row in results:
        key=(row["cell"],row["seed"])
        if key in seen or row["comparison_binding"]!=identity or row.get("scope")!="development":
            raise FactorContractError("ablation cells differ in data/budget or consume final results")
        seen.add(key)
        score=row.get("score")
        if type(score) not in (int,float) or not 0<=score<=1:
            raise FactorContractError("uncovered development tasks cannot select a winner")
        grouped.setdefault(row["cell"],[]).append((row["seed"],score))
    seed_sets={tuple(sorted(s for s,_ in values)) for values in grouped.values()}
    if len(seed_sets)!=1:
        raise FactorContractError("ablation cells need matched seeds")
    return dict(scope="development",comparison_binding=identity,
                cells={k:dict(seeds=sorted(s for s,_ in v),mean_score=sum(x for _,x in v)/len(v)) for k,v in grouped.items()},
                capability_accepted=False)


def apply_saved(records,predictions,calibration):
    result=deepcopy(predictions)
    for record in records:
        rid=record["record_id"]
        saved=result.setdefault(rid,{})
        saved.update(calibrated={},applied={},calibrated_probabilities={})
        for task,coordinate,cell in iter_target_cells(record["targets"]):
            key=prediction_key(task,coordinate)
            value=saved.get("probabilities",{}).get(key)
            if value is None or task not in LEARNED_TASKS:
                continue
            row=dict(task=task,subject=list(coordinate),coordinate="saved",value=value)
            layers=calibration(task,(row,))
            for public,internal in (("calibrated_scores","calibrated"),("applied_prediction","applied")):
                if layers[public]:
                    answer=layers[public][0]["value"]
                    saved[internal][key]=max(answer,key=answer.get) if isinstance(answer,dict) else answer
                    if internal=="calibrated":
                        saved["calibrated_probabilities"][key]=answer
        axes=saved.setdefault("axes",{})
        axes.update(calibrated=[],applied=[])
        for axis,members in saved.get("axis_probabilities",{}).items():
            selected={"calibrated":[],"applied":[]}
            for member,value in members.items():
                layers=calibration("axis_membership",(dict(task="axis_membership",subject=[axis,member],coordinate="member",value=value),))
                if layers["calibrated_scores"] and layers["calibrated_scores"][0]["value"]>=.5:
                    selected["calibrated"].append(member)
                if layers["applied_prediction"] and layers["applied_prediction"][0]["value"]:
                    selected["applied"].append(member)
            for layer,names in selected.items():
                if len(names)>1:
                    axes[layer].append(dict(candidate_ref=axis,members=sorted(names)))
    return result


def _source_metric(groups,classes,*,categorical):
    matrix={c:{p:0. for p in (*classes,"unknown")} for c in classes}
    for pairs in groups.values():
        for cell,p in pairs:
            truth=cell.value if categorical else str(int(cell.value>=.5))
            guess="unknown" if p is None else p if categorical else str(int(p>=.5))
            matrix[truth][guess]+=1/len(pairs)/len(groups)
    per={}
    for c in classes:
        tp=matrix[c][c];support=sum(matrix[c].values());fp=sum(matrix[k][c] for k in classes if k!=c);fn=support-tp
        per[c]=dict(precision=tp/(tp+fp) if tp+fp else None,f1=2*tp/(2*tp+fp+fn) if support and 2*tp+fp+fn else None,support=support)
    complete=all(v["support"]>0 for v in per.values())
    return dict(f1=sum(v["f1"] for v in per.values())/len(classes) if complete else None,
        complete_class_coverage=complete,coverage=sum(matrix[c][p] for c in classes for p in classes) if groups else None,
        source_groups=len(groups),per_class=per,confusion=matrix)


def source_balanced(records,saved,layer):
    """Equal source groups within each fixed output coordinate, then macro."""
    from collections import defaultdict
    values=defaultdict(lambda:defaultdict(list))
    coordinate_values=defaultdict(lambda:defaultdict(list))
    for row in records:
        for task,coordinate,cell in iter_target_cells(row["targets"]):
            if cell.known and task in LEARNED_TASKS:
                pair=(cell,saved.get(row["record_id"],{}).get(layer,{}).get(prediction_key(task,coordinate)))
                group=row["provenance"]["leakage_group"]
                values[task][group].append(pair)
                if task in BINARY_COORDINATES:coordinate_values[task,coordinate[-1]][group].append(pair)
    result={}
    for task in LEARNED_TASKS:
        categorical=task in CATEGORY_COORDINATES
        metric=_source_metric(values[task],tuple(TASK_DOMAINS[task]) if categorical else ("0","1"),categorical=categorical)
        metric["covered_coordinates"]=[]
        if task in BINARY_COORDINATES:
            by_coordinate={c:_source_metric(coordinate_values[task,c],("0","1"),categorical=False) for c in BINARY_COORDINATES[task]}
            covered=[c for c,v in by_coordinate.items() if v["complete_class_coverage"]]
            complete=len(covered)==len(by_coordinate)
            metric.update(per_coordinate=by_coordinate,covered_coordinates=covered,complete_class_coverage=complete,
                f1=sum(v["f1"] for v in by_coordinate.values())/len(by_coordinate) if complete else None,
                coverage=sum(v["coverage"] for v in by_coordinate.values())/len(by_coordinate) if all(v["coverage"] is not None for v in by_coordinate.values()) else None)
        result[task]=metric
    return result



def reliability(records,saved,layer):
    """Source-balanced binary/multiclass Brier and confidence ECE."""
    from collections import defaultdict
    from ygo_kito.multifactor.calibration import probabilities
    grouped=defaultdict(lambda:defaultdict(list))
    channel="probabilities" if layer=="raw" else "calibrated_probabilities"
    for row in records:
        for task,coordinate,cell in iter_target_cells(row["targets"]):
            if cell.known and task in LEARNED_TASKS:
                grouped[task][row["provenance"]["leakage_group"]].append((cell,saved.get(row["record_id"],{}).get(channel,{}).get(prediction_key(task,coordinate))))
    report={}
    for task,groups in grouped.items():
        brier=answered=0.; bins=[[] for _ in range(10)]
        for pairs in groups.values():
            for cell,value in pairs:
                if value is None: continue
                ps=probabilities(task,value);w=1/len(pairs)/len(groups)
                truth=TASK_DOMAINS[task].index(cell.value) if task in CATEGORY_COORDINATES else int(cell.value>=.5)
                target=[float(i==truth) for i in range(len(ps))] if task in CATEGORY_COORDINATES else [1-float(cell.value),float(cell.value)]
                brier+=w*sum((p-y)**2 for p,y in zip(ps,target))
                confidence=max(ps);correct=float(max(range(len(ps)),key=ps.__getitem__)==truth)
                bins[min(9,int(confidence*10))].append((w,confidence,correct));answered+=w
        ece=sum(abs(sum(w*(p-y) for w,p,y in bucket)) for bucket in bins)
        complete=math.isclose(answered,1.,abs_tol=1e-8)
        report[task]=dict(brier=brier if complete else None,ece=ece if complete else None,
                          coverage=answered,selective_brier=brier/answered if answered else None,
                          selective_ece=ece/answered if answered else None)
    return report


def evaluate(records,predictions,calibration,protocol,*,training_groups=()):
    """Final and retrospective reports; never refits or selects anything."""
    predictions=bound_predictions(predictions,records,model_id=calibration.artifact["model_id"],dataset_id=calibration.artifact["dataset_id"])
    if digest(protocol.get("label_protocol"))!=calibration.artifact.get("label_protocol_sha256"):
        raise FactorContractError("evaluation/calibration label protocol differs")
    groups=set(); ids=set(); group_fold={}; kinds=set()
    excluded=(set(training_groups)|set(calibration.artifact["training_groups"])|
              set(calibration.artifact["selection_groups"])|set(calibration.artifact["calibration_groups"]))
    for row in records:
        fold=row["supervision"]["partition"]; group=row["provenance"]["leakage_group"]; rid=row["record_id"]
        if fold not in ("test","retrospective_test") or group in excluded or rid in ids or group_fold.setdefault(group,fold)!=fold:
            raise FactorContractError("evaluation sources overlap training/selection/calibration or cross partitions")
        groups.add(group); ids.add(rid)
        source=record_sources(row,label_protocol_sha256=calibration.artifact["label_protocol_sha256"])
        if not source or source-(REAL_SOURCES|ENGINEERING_SOURCES):
            raise FactorContractError("evaluation source provenance missing")
        kinds.update(source)
    if not records or set(predictions)-ids:
        raise FactorContractError("explicit nonempty evaluation records required")
    scoped=deepcopy(protocol); scoped["partitions"]=["test","retrospective_test"]
    saved=apply_saved(records,predictions,calibration)
    report=assess_records(records,saved,scoped)
    # Receiver holdout is a declared split fact, never inferred from a card ID.
    unseen=[r for r in records if r["supervision"]["partition"]=="test" and r["provenance"].get("evaluation_slice")=="unseen_receiver"]
    report["unseen_receiver"]=assess_records(unseen,{r["record_id"]:saved[r["record_id"]] for r in unseen},dict(scoped,partitions=["test"])) if unseen else None
    for fold in scoped["partitions"]:
        rows=[r for r in records if r["supervision"]["partition"]==fold]
        for layer in ("raw","calibrated","applied"):
            report["partitions"][fold]["layers"][layer]["source_balanced_tasks"]=source_balanced(rows,saved,layer)
            if layer!="applied":
                report["partitions"][fold]["layers"][layer]["probability_reliability"]=reliability(rows,saved,layer)
    if unseen:
        for layer in ("raw","calibrated","applied"):
            report["unseen_receiver"]["partitions"]["test"]["layers"][layer]["source_balanced_tasks"]=source_balanced(unseen,saved,layer)
    report.update(model_id=calibration.artifact["model_id"],dataset_id=calibration.artifact["dataset_id"],
                  metric_version="axis-source-coordinate-macro-v3-review1",
                  calibration_id=digest(calibration.artifact),evaluation_groups=sorted(groups),
                  prediction_records_id=digest({r["record_id"]:r for r in records}),
                  training_groups=sorted(set(training_groups)|set(calibration.artifact["training_groups"])),source_kinds=sorted(kinds),
                  engineering_only=calibration.artifact["engineering_only"] or bool(kinds&ENGINEERING_SOURCES))
    return report,saved






def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("ablation-plan","ablation-compare","calibrate","evaluate","release-candidate","predict",
                                         "environment-plan","environment-calibrate","environment-assess"))
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    if Path(args.output).exists():
        raise FactorContractError("output exists; preserve it and choose a new file")
    payload=json.loads(Path(args.input).read_text("utf-8-sig"))
    if args.action in ("predict","calibrate","evaluate") and "records" not in payload:
        # A predictor must be explicitly authorized before any dataset access.
        if args.action=="predict" and payload.get("evaluation_authorized") is not True:
            raise FactorContractError("prediction requires explicit evaluation authorization")
        rows,dataset_id=evaluation_records(payload.pop("dataset_dir"),payload.pop("fold"),groups=payload.pop("groups",None))
        payload["records"]=rows
        if args.action=="calibrate":
            if payload.get("dataset_id",dataset_id)!=dataset_id:raise FactorContractError("calibration dataset identity differs")
            payload["dataset_id"]=dataset_id
        elif args.action=="evaluate":
            if payload["calibration"]["dataset_id"]!=dataset_id:raise FactorContractError("final dataset identity differs")
        elif payload["binding"]["dataset"]!=dataset_id:
            raise FactorContractError("predictor dataset differs from model binding")
    if args.action=="ablation-plan":
        result=ablation_recipes(payload["base"],selected=payload.get("selected"),seeds=payload.get("seeds"))
    elif args.action=="ablation-compare":
        result=compare_ablation(payload["results"])
    elif args.action=="calibrate":
        result=fit_calibration(**payload).artifact
    elif args.action=="evaluate":
        payload["calibration"]=Calibration(payload["calibration"])
        report,saved=evaluate(**payload)
        result=dict(report=report,predictions=saved)
    elif args.action=="release-candidate":
        payload["calibration"]=Calibration(payload["calibration"])
        result=release_candidate(**payload)
    elif args.action=="environment-plan":
        from environment_v3 import comparison_recipes
        result=comparison_recipes(payload)
    elif args.action=="environment-calibrate":
        from ygo_kito.multifactor.environment import fit_environment_calibration
        result=fit_environment_calibration(**payload)
    elif args.action=="environment-assess":
        from ygo_kito.multifactor.environment import assess_environment
        result=assess_environment(**payload)
    else:
        if payload.get("evaluation_authorized") is not True:
            raise FactorContractError("prediction requires explicit evaluation authorization")
        from ygo_kito.multifactor.training import RoleTrainer
        from ygo_kito.multifactor.network import NetworkConfig
        from ygo_kito.multifactor.calibration import model_identity
        trainer=RoleTrainer.load(payload["checkpoint"],mode="inference",expected_config=NetworkConfig(**payload["network"]),
            expected_binding=payload["binding"],expected_label_protocol_sha256=payload["label_protocol_sha256"],device=payload["device"])
        result=prediction_bundle(predict_records(trainer,payload["records"],batch_size=payload.get("batch_size",32)),
            payload["records"],model_id=model_identity(trainer),dataset_id=trainer.binding["dataset"])
    write_new(args.output,result)


if __name__=="__main__":
    main()
