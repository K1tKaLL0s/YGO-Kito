"""Source-isolated calibration and explicit host capability artifacts.

No model, data file or device is opened on import. Fitting never publishes.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from .contracts import CapabilityStatus, FactorContractError, TASK_DOMAINS, digest, unit
from .task_queries import BINARY_COORDINATES, CATEGORY_COORDINATES, LEARNED_TASKS, query_key, record_sources

VERSION = "axis-calibration-v3-2"
REAL_SOURCES = {"human_feedback", "engine_probe", "self_generated_candidate", "weak_context_annotation"}
ENGINEERING_SOURCES = {"engineering_fixture", "definition_development"}


def prediction_bundle(predictions,records,*,model_id,dataset_id):
    if not isinstance(model_id,str) or not model_id or not isinstance(dataset_id,str) or not dataset_id:
        raise FactorContractError("prediction bundle needs explicit model and dataset identities")
    ids=[r["record_id"] for r in records]
    if len(ids)!=len(set(ids)) or set(predictions)-set(ids):
        raise FactorContractError("prediction bundle record identities differ")
    return dict(version="axis-predictions-v3",model_id=model_id,dataset_id=dataset_id,
        records_id=digest({r["record_id"]:r for r in records}),predictions=deepcopy(predictions))


def bound_predictions(predictions,records,*,model_id,dataset_id):
    if isinstance(predictions,dict) and predictions.get("version")=="axis-predictions-v3":
        if (predictions.get("model_id")!=model_id or predictions.get("dataset_id")!=dataset_id or
                predictions.get("records_id")!=digest({r["record_id"]:r for r in records})):
            raise FactorContractError("prediction model/dataset/records binding differs")
        return predictions["predictions"]
    # Small artificial saved maps remain useful for arithmetic tests.
    # Real evaluation must use the actual predictor's bound artifact.
    if any(record_sources(r)-ENGINEERING_SOURCES for r in records):
        raise FactorContractError("real predictions require a bound axis-predictions-v3 artifact")
    return predictions


def model_identity(trainer):
    """Bind to actual weights, not just an architecture or an update count."""
    state = hashlib.sha256()
    for name, tensor in sorted(trainer.model.state_dict().items()):
        state.update(name.encode())
        state.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest(dict(binding=trainer.binding,weights=state.hexdigest(),
                       protocol=trainer.label_protocol_sha256,config=trainer.model.config_dict()))


def write_new(path, value):
    text = json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    with Path(path).open("x",encoding="utf-8") as stream:
        stream.write(text)


def probabilities(task, value):
    if task in CATEGORY_COORDINATES:
        classes = TASK_DOMAINS[task]
        if not isinstance(value,dict) or set(value)!=set(classes):
            raise FactorContractError("complete categorical probabilities required")
        for v in value.values():
            unit(v,"probability")
        if abs(sum(value.values())-1)>1e-5:
            raise FactorContractError("probabilities must sum to one")
        return [float(value[c]) for c in classes]
    unit(value,"probability")
    return [1-float(value),float(value)]


def rescale(values, temperature):
    logits = [math.log(max(1e-12,p))/temperature for p in values]
    high = max(logits)
    exp = [math.exp(v-high) for v in logits]
    return [v/sum(exp) for v in exp]


def _weighted_f1(samples, temperature, threshold):
    matrix = [[0.,0.],[0.,0.]]
    for values,y,w in samples:
        p=rescale(values,temperature)[1]
        matrix[int(y>=.5)][int(p>=threshold)] += w
    scores=[]
    for c in (0,1):
        tp=matrix[c][c]; fp=matrix[1-c][c]; fn=matrix[c][1-c]
        scores.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.)
    return sum(scores)/2


def fit_calibration(records, predictions, *, model_id, dataset_id, selection_groups,
                    reserved_groups, training_groups, minimum_groups=2, minimum_confidence=0.0):
    from .training import Targets
    if type(minimum_groups) is not int or minimum_groups<1:
        raise FactorContractError("positive calibration group minimum required")
    unit(minimum_confidence,"minimum confidence")
    predictions=bound_predictions(predictions,records,model_id=model_id,dataset_id=dataset_id)
    protocols={r["supervision"].get("label_protocol_sha256") for r in records}
    if len(protocols)!=1:
        raise FactorContractError("calibration cannot mix label protocols")
    reserved,selected,trained = set(reserved_groups),set(selection_groups),set(training_groups)
    if not reserved or reserved&selected or (reserved|selected)&trained or not model_id or not dataset_id:
        raise FactorContractError("calibration needs disjoint explicit group and model bindings")
    ids=set(); actual=set(); kinds=set(); by_task=defaultdict(list)
    coordinate_classes=defaultdict(set); coordinate_groups=defaultdict(set)
    for row in records:
        rid=row["record_id"]; group=row["provenance"]["leakage_group"]
        if rid in ids or group not in reserved or row["supervision"]["partition"]!="validation":
            raise FactorContractError("calibration only consumes unique reserved validation records")
        ids.add(rid); actual.add(group)
        source_kinds=record_sources(row)
        if not source_kinds or source_kinds-(REAL_SOURCES|ENGINEERING_SOURCES):
            raise FactorContractError("calibration source kind is missing or unsupported")
        kinds.update(source_kinds)
        for task,subject,coordinate,cell in Targets.from_dict(row["targets"]).graph_cells():
            if task not in LEARNED_TASKS or not cell.known:
                continue
            value=predictions.get(rid,{}).get("probabilities",{}).get(query_key(task,subject,coordinate))
            if value is None:
                continue
            ps=probabilities(task,value)
            y=TASK_DOMAINS[task].index(cell.value) if task in CATEGORY_COORDINATES else float(cell.value)
            by_task[task].append((group,ps,y))
            if task in BINARY_COORDINATES:
                coordinate_classes[task,coordinate].add(int(y>=.5))
                coordinate_groups[task,coordinate].add(group)
    if set(predictions)-ids or actual!=reserved:
        raise FactorContractError("calibration reservation does not match supplied groups/predictions")
    tasks={}
    for task in LEARNED_TASKS:
        values=by_task[task]; counts=defaultdict(int)
        for g,_,_ in values:
            counts[g]+=1
        covered={int(y) if task in CATEGORY_COORDINATES else int(y>=.5) for _,_,y in values}
        expected=set(range(len(TASK_DOMAINS[task]))) if task in CATEGORY_COORDINATES else {0,1}
        if len(counts)<minimum_groups or covered!=expected:
            tasks[task]=dict(status="uncovered",groups=len(counts),classes=sorted(covered))
            continue
        samples=[(ps,y,1/counts[g]/len(counts)) for g,ps,y in values]
        def nll(temp):
            total=0.
            for ps,y,w in samples:
                calibrated=rescale(ps,temp)
                loss=(-math.log(max(1e-12,calibrated[int(y)])) if task in CATEGORY_COORDINATES else
                      -y*math.log(max(1e-12,calibrated[1]))-(1-y)*math.log(max(1e-12,calibrated[0])))
                total+=w*loss
            return total
        temp=min((.25,.5,.75,1.,1.5,2.,3.,4.),key=lambda t:(nll(t),abs(t-1)))
        threshold=(None if task in CATEGORY_COORDINATES else
                   max((.1,.2,.3,.4,.5,.6,.7,.8,.9),key=lambda t:(_weighted_f1(samples,temp,t),-abs(t-.5))))
        tasks[task]=dict(status="fitted",temperature=temp,threshold=threshold,
                         minimum_confidence=minimum_confidence,groups=len(counts),classes=sorted(covered),
                         covered_coordinates=[c for c in BINARY_COORDINATES.get(task,()) if coordinate_classes[task,c]=={0,1} and len(coordinate_groups[task,c])>=minimum_groups])
    return Calibration(dict(version=VERSION,model_id=model_id,dataset_id=dataset_id,
        selection_groups=sorted(selected),calibration_groups=sorted(actual),source_kinds=sorted(kinds),
        training_groups=sorted(trained),
        label_protocol_sha256=next(iter(protocols)),
        engineering_only=bool(kinds&ENGINEERING_SOURCES),tasks=tasks,capability_accepted=False))


class Calibration:
    def __init__(self, artifact):
        self.artifact=deepcopy(artifact)
        value=self.artifact
        if (value.get("version")!=VERSION or value.get("capability_accepted") is not False or
                not value.get("model_id") or not value.get("dataset_id") or
                set(value.get("tasks",{}))!=set(LEARNED_TASKS) or
                "training_groups" not in value or not value.get("calibration_groups") or
                set(value["calibration_groups"])&set(value.get("selection_groups",())) or
                (set(value["calibration_groups"])|set(value.get("selection_groups",())))&set(value["training_groups"])):
            raise FactorContractError("invalid calibration artifact")
        kinds=set(value.get("source_kinds",()))
        if not kinds or kinds-(REAL_SOURCES|ENGINEERING_SOURCES) or value.get("engineering_only")!=bool(kinds&ENGINEERING_SOURCES):
            raise FactorContractError("calibration source provenance differs")
        for task,entry in value["tasks"].items():
            if entry.get("status")=="uncovered":
                continue
            expected=list(range(len(TASK_DOMAINS[task]))) if task in CATEGORY_COORDINATES else [0,1]
            if (entry.get("status")!="fitted" or entry.get("classes")!=expected or
                    type(entry.get("groups")) is not int or entry["groups"]<1 or
                    type(entry.get("temperature")) not in (int,float) or not .01<=entry["temperature"]<=100):
                raise FactorContractError("invalid fitted calibration task")
            unit(entry["minimum_confidence"],"minimum confidence")
            if task not in CATEGORY_COORDINATES:
                unit(entry["threshold"],"binary threshold")

    def check_base(self, trainer):
        if model_identity(trainer)!=self.artifact["model_id"] or trainer.label_protocol_sha256!=self.artifact.get("label_protocol_sha256"):
            raise FactorContractError("calibration belongs to a different base model")

    def __call__(self, task, rows):
        entry=self.artifact["tasks"].get(task,{})
        calibrated,applied=[],[]
        if entry.get("status")!="fitted":
            return dict(calibrated_scores=(),applied_prediction=())
        for row in rows:
            if row["task"]!=task:
                raise FactorContractError("calibration task mismatch")
            ps=rescale(probabilities(task,row["value"]),entry["temperature"])
            categorical=task in CATEGORY_COORDINATES
            value=dict(zip(TASK_DOMAINS[task],ps)) if categorical else ps[1]
            calibrated.append(dict(row,value=value))
            if max(ps)>=entry["minimum_confidence"]:
                chosen=TASK_DOMAINS[task][max(range(len(ps)),key=ps.__getitem__)] if categorical else ps[1]>=entry["threshold"]
                applied.append(dict(row,value=chosen))
        return dict(calibrated_scores=tuple(calibrated),applied_prediction=tuple(applied))

    def save(self,path):
        write_new(path,self.artifact)

    @classmethod
    def load(cls,path):
        return cls(json.loads(Path(path).read_text("utf-8-sig")))


def host_capabilities(release, calibration, trainer, *, evidence_ref,assessment_report=None,baseline_report=None):
    """Called only by a host explicitly selecting this immutable release.

    Does not mutate a model, policy, file, active pointer or adapter.
    """
    calibration.check_base(trainer)
    value=calibration.artifact
    if (release.get("version")!="axis-release-candidate-v3" or release.get("model_id")!=value["model_id"] or
            release.get("calibration_id")!=digest(value) or release.get("dataset_id")!=value["dataset_id"] or
            release.get("independent_final") is not True or release.get("engineering_only") is not False or
            value["engineering_only"] or not evidence_ref):
        raise FactorContractError("release/model/calibration/provenance binding differs")
    if assessment_report is None or baseline_report is None:
        raise FactorContractError("host must bind the actual independent and baseline reports")
    expected=release_candidate(assessment_report,calibration,requested_tasks=list(release["capabilities"]),baseline=baseline_report,policy=release["policy"])
    if release!=expected:
        raise FactorContractError("release decision differs from its actual assessment/baseline reports")
    result={}
    for task,decision in release["capabilities"].items():
        if task not in LEARNED_TASKS:
            raise FactorContractError("unknown release capability")
        if decision.get("eligible") is True:
            if value["tasks"][task]["status"]!="fitted" or trainer.head_status(task)!="trained_uncalibrated":
                raise FactorContractError("released head has no real training or fitted calibration")
            result[task]=CapabilityStatus("available",producer="axis-release-v3",version=digest(release),
                evidence_refs=(evidence_ref,),validated=True,calibrated=True)
    return result


DEFAULT_POLICY=dict(f1=.80,coverage=.90,candidate_recall=.95,open_precision=.90,
                    closed_to_open=.05,unseen_receiver_f1=.70,maximum_regression=.03)

def _f1(metric):
    if not metric.get("complete_class_coverage"):
        return None
    # Binary tasks report both classes; do not treat positive-only F1 as macro.
    if "negative_f1" in metric:
        return (metric["f1"]+metric["negative_f1"])/2 if metric["f1"] is not None and metric["negative_f1"] is not None else None
    return metric.get("f1")

def release_candidate(report,calibration,*,requested_tasks,baseline,policy=None):
    """Produce a reviewable manifest. Host selection remains an explicit call."""
    thresholds=dict(DEFAULT_POLICY)
    if policy is not None:
        if set(policy)!=set(DEFAULT_POLICY):
            raise FactorContractError("release policy must declare all fixed gates")
        thresholds=dict(policy)
    if any(type(v) not in (int,float) or not 0<=v<=1 for v in thresholds.values()):
        raise FactorContractError("finite release gates in [0,1] required")
    tasks=list(requested_tasks)
    if not tasks or len(set(tasks))!=len(tasks) or set(tasks)-set(LEARNED_TASKS):
        raise FactorContractError("explicit distinct learned capabilities required")
    art=calibration.artifact
    if report.get("model_id")!=art["model_id"] or report.get("calibration_id")!=digest(art) or report.get("dataset_id")!=art["dataset_id"]:
        raise FactorContractError("evaluation belongs to a different calibration/model/dataset")
    final=report["partitions"]["test"]
    baseline_ok=(baseline is not None and baseline.get("model_id")!=report["model_id"] and
                 baseline.get("version")==report.get("version") and
                 baseline.get("metric_version")==report.get("metric_version")=="axis-source-coordinate-macro-v3-review1" and
                 baseline.get("prediction_records_id")==report.get("prediction_records_id") and
                 baseline.get("dataset_id")==report["dataset_id"] and
                 baseline.get("evaluation_groups")==report["evaluation_groups"] and
                 baseline.get("label_protocol")==report.get("label_protocol"))
    decisions={}
    for task in tasks:
        reasons=[]
        if final["independent_final"] is not True: reasons.append("INDEPENDENT_FINAL_REQUIRED")
        if report["engineering_only"] or art["engineering_only"]: reasons.append("ENGINEERING_EVIDENCE_ONLY")
        if art["tasks"][task]["status"]!="fitted": reasons.append("CALIBRATION_UNCOVERED")
        if set(art["tasks"][task].get("covered_coordinates",()))!=set(BINARY_COORDINATES.get(task,())):
            reasons.append("CALIBRATION_COORDINATES_UNCOVERED")
        for layer in ("raw","calibrated","applied"):
            metric=final["layers"][layer]["source_balanced_tasks"][task]
            if set(metric.get("covered_coordinates",()))!=set(BINARY_COORDINATES.get(task,())):
                reasons.append(layer.upper()+"_COORDINATES_UNCOVERED")
            score=_f1(metric)
            if score is None or score<thresholds["f1"]: reasons.append(layer.upper()+"_F1_OR_COVERAGE")
            if metric.get("coverage") is None or metric["coverage"]<thresholds["coverage"]: reasons.append(layer.upper()+"_LOW_COVERAGE")
            previous=baseline["partitions"]["test"]["layers"][layer].get("source_balanced_tasks",{}).get(task) if baseline_ok else None
            if previous is None or _f1(previous) is None or score is None or score<_f1(previous)-thresholds["maximum_regression"]:
                reasons.append(layer.upper()+"_BASELINE_MISSING_OR_REGRESSION")
        if task in ("axis_membership","axis_function","axis_position","axis_origin"):
            recall=final["layers"]["applied"]["axes"]["source_macro_candidate_recall"]
            if recall is None or recall<thresholds["candidate_recall"]: reasons.append("CANDIDATE_RECALL")
        if task in ("transferability","receiver_compatibility","function_role","contribution","copy_preference"):
            unseen=report.get("unseen_receiver")
            metric=None if unseen is None else unseen["partitions"]["test"]["layers"]["applied"]["source_balanced_tasks"][task]
            score=None if metric is None else _f1(metric)
            if score is None or score<thresholds["unseen_receiver_f1"]: reasons.append("UNSEEN_RECEIVER_UNCOVERED_OR_LOW")
        if task=="transferability":
            metric=final["layers"]["applied"]["source_balanced_tasks"][task]
            precision=metric["per_class"]["open"]["precision"]
            closed=metric["confusion"]["closed"]; count=sum(closed.values())
            if precision is None or precision<thresholds["open_precision"]: reasons.append("OPEN_PRECISION")
            if not count or closed["open"]/count>thresholds["closed_to_open"]: reasons.append("CLOSED_TO_OPEN")
        decisions[task]=dict(eligible=not reasons,reasons=reasons)
    return dict(version="axis-release-candidate-v3",model_id=art["model_id"],dataset_id=art["dataset_id"],
        calibration_id=digest(art),report_id=digest(report),baseline_id=None if baseline is None else digest(baseline),policy=thresholds,capabilities=decisions,
        independent_final=final["independent_final"],engineering_only=report["engineering_only"],
        active_pointer_changed=False,capability_accepted=False)
