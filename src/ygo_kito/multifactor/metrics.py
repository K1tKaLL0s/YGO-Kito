"""Fixed-denominator known-cell metrics; no inference or model dependency."""
import math
import random

from .contracts import FactorContractError, LabelCell, unit


def _probability(value):
    if type(value) is bool:
        return float(value)
    unit(value, "prediction probability")
    return float(value)


def binary_metrics(cells):
    known = answered = tp = fp = fn = tn = reject_positive = reject_negative = 0
    squared, logloss, positive_errors, negative_errors = [], [], [], []
    for cell, prediction in cells:
        if not isinstance(cell, LabelCell):
            raise FactorContractError("typed label cells required")
        cell.validate_domain()
        if not cell.known:
            continue
        known += 1
        truth = cell.value >= 0.5
        if prediction is None:
            if truth:
                fn += 1
                reject_positive += 1
            else:
                reject_negative += 1
            continue
        value = _probability(prediction)
        answered += 1
        guess = value >= 0.5
        tp += int(truth and guess)
        fp += int(not truth and guess)
        fn += int(truth and not guess)
        tn += int(not truth and not guess)
        error = (float(cell.value) - value) ** 2
        squared.append(error)
        (positive_errors if truth else negative_errors).append(error)
        logloss.append(-float(cell.value) * math.log(max(1e-7, value)) - (1-float(cell.value)) * math.log(max(1e-7, 1-value)))
    positive = tp + fn
    negative = tn + fp + reject_negative
    denominator = 2 * tp + fp + fn
    f1 = 2 * tp / denominator if denominator and positive else None
    negative_denominator = 2 * tn + fn - reject_positive + fp + reject_negative
    negative_f1 = 2 * tn / negative_denominator if negative_denominator and negative else None
    selective_brier = sum(squared) / answered if answered else None
    balanced = ((sum(positive_errors)/len(positive_errors) + sum(negative_errors)/len(negative_errors))/2
                if positive_errors and negative_errors else selective_brier)
    return dict(known=known, observed=known, answered=answered, positive=positive, negative=negative,
                tp=tp, fp=fp, fn=fn, tn=tn, rejected_positive=reject_positive, rejected_negative=reject_negative,
                precision=tp/(tp+fp) if tp+fp else None, recall=tp/positive if positive else None, f1=f1,
                negative_f1=negative_f1, class_coverage=dict(positive=positive > 0, negative=negative > 0),
                complete_class_coverage=positive > 0 and negative > 0,
                coverage=answered/known if known else None, selective_accuracy=(tp+tn)/answered if answered else None,
                overall_accuracy=(tp+tn)/known if known else None,
                brier=selective_brier if answered == known else None, selective_brier=selective_brier,
                balanced_brier=balanced if answered == known else None,
                soft_bce=sum(logloss)/answered if answered else None)


def categorical_metrics(cells, classes):
    classes = tuple(classes)
    if not classes or "unknown" in classes or len(set(classes)) != len(classes) or any(not isinstance(c, str) for c in classes):
        raise FactorContractError("distinct fixed categorical classes required")
    matrix = {c: {p: 0 for p in classes + ("unknown",)} for c in classes}
    known = answered = correct = 0
    for cell, prediction in cells:
        if not isinstance(cell, LabelCell):
            raise FactorContractError("typed label cells required")
        cell.validate_domain(classes)
        if not cell.known:
            continue
        known += 1
        if prediction not in classes and prediction is not None and prediction != "unknown":
            raise FactorContractError("prediction outside fixed categorical vocabulary")
        value = "unknown" if prediction is None else prediction
        matrix[cell.value][value] += 1
        answered += int(value != "unknown")
        correct += int(value == cell.value)
    per_class = {}
    for c in classes:
        tp = matrix[c][c]
        fp = sum(matrix[y][c] for y in classes if y != c)
        support = sum(matrix[c].values())
        fn = support - tp  # Includes unknown predictions for this true class.
        den = 2*tp + fp + fn
        per_class[c] = dict(tp=tp, fp=fp, fn=fn, support=support, covered=support > 0,
            precision=tp/(tp+fp) if tp+fp else None, recall=tp/support if support else None,
            f1=2*tp/den if den else None)
    covered = [v["f1"] for v in per_class.values() if v["covered"] and v["f1"] is not None]
    complete = all(v["covered"] and v["f1"] is not None for v in per_class.values())
    return dict(known=known, answered=answered, coverage=answered/known if known else None,
        overall_accuracy=correct/known if known else None, selective_accuracy=correct/answered if answered else None,
        confusion=matrix, per_class=per_class, f1=sum(covered)/len(covered) if complete else None,
        covered_macro_f1=sum(covered)/len(covered) if covered else None, complete_class_coverage=complete)


def macro_f1_report(per_task, *, tasks=None):
    tasks = tuple(per_task) if tasks is None else tuple(tasks)
    available, missing = [], []
    for task in tasks:
        value = per_task.get(task, {}).get("f1")
        if value is not None:
            available.append(value)
        if value is None or per_task.get(task, {}).get("complete_class_coverage") is False:
            missing.append(task)
    return dict(f1=sum(available)/len(tasks) if tasks and not missing else None,
                covered_macro_f1=sum(available)/len(available) if available else None,
                fixed_tasks=list(tasks), uncovered_tasks=missing, complete=bool(tasks) and not missing)


def macro_f1(per_task):
    result = macro_f1_report(per_task)
    if result["covered_macro_f1"] is None:
        raise FactorContractError("macro F1 needs at least one known task")
    return result["f1"]


def probability_calibration(cells, bins=10):
    if type(bins) is not int or bins < 1:
        raise FactorContractError("positive reliability bin count required")
    rows = [[] for _ in range(bins)]
    known = 0
    for cell, prediction in cells:
        cell.validate_domain()
        if cell.known:
            known += 1
            if prediction is not None:
                value = _probability(prediction)
                rows[min(bins-1, int(value*bins))].append((float(cell.value), value))
    result = []
    for i, group in enumerate(rows):
        result.append(dict(lower=i/bins, upper=(i+1)/bins, count=len(group),
            mean_prediction=sum(p for _, p in group)/len(group) if group else None,
            observed_rate=sum(y for y, _ in group)/len(group) if group else None))
    answered = sum(len(g) for g in rows)
    selective = sum((y-p)**2 for g in rows for y,p in g)/answered if answered else None
    return dict(known=known, answered=answered, bins=result, selective_brier=selective,
                brier=selective if answered == known else None)


def group_bootstrap(groups, statistic, *, repetitions=1000, seed=17):
    """Resample source components, preserving all rows in each selected group."""
    if type(repetitions) is not int or repetitions < 0:
        raise FactorContractError("nonnegative bootstrap repetitions required")
    keys = sorted(groups)
    rng = random.Random(seed)
    values = []
    for _ in range(repetitions if keys else 0):
        sample = [row for _ in keys for row in groups[rng.choice(keys)]]
        score = statistic(sample)
        if score is not None:
            values.append(score)
    values.sort()
    def quantile(p):
        if not values:
            return None
        return values[min(len(values)-1, int(p*(len(values)-1)))]
    return dict(lower=quantile(.025), upper=quantile(.975), source_groups=len(keys),
                requested_repetitions=repetitions, defined_repetitions=len(values), unit="leakage_group")


def _maximum_assignment(weights):
    """Square maximum-weight assignment via bounded-size Hungarian matching."""
    n = len(weights)
    if n > 256 or any(len(row) != n for row in weights):
        raise FactorContractError("axis matching needs a square matrix of size <=256")
    u, v, p, way = [0.0]*(n+1), [0.0]*(n+1), [0]*(n+1), [0]*(n+1)
    for i in range(1, n+1):
        p[0], j0 = i, 0
        minimum, used = [float("inf")]*(n+1), [False]*(n+1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1, n+1):
                if not used[j]:
                    cur = -weights[i0-1][j-1] - u[i0] - v[j]
                    if cur < minimum[j]:
                        minimum[j], way[j] = cur, j0
                    if minimum[j] < delta:
                        delta, j1 = minimum[j], j
            for j in range(n+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            p[j0] = p[way[j0]]
            j0 = way[j0]
    return [(p[j]-1, j-1) for j in range(1, n+1)]


def axis_set_metrics(truth, predicted, *, natural_candidate_ids=()):
    """Final member sets use IoU matching; candidate recall uses gold mappings.

    Gold allowed_candidate_refs=[] is an explicit candidate miss. An omitted
    mapping is unannotated and cannot be called candidate success or failure.
    """
    actual = [set(v["members"]) for v in truth]
    proposed_records = [v for v in predicted if v.get("candidate_ref") in set(natural_candidate_ids)]
    proposed = [set(v["members"]) for v in proposed_records]
    size = max(len(actual), len(proposed))
    if size > 256:
        raise FactorContractError("axis matching budget exceeded; no partial matching score")
    def compatible(i,j):
        return "allowed_candidate_refs" not in truth[i] or proposed_records[j]["candidate_ref"] in truth[i]["allowed_candidate_refs"]
    matrix = [[len(a & b)/len(a | b) if a | b and compatible(i,j) else 0 for j,b in enumerate(proposed)] + [0.0]*(size-len(proposed)) for i,a in enumerate(actual)]
    matrix += [[0.0]*size for _ in range(size-len(actual))]
    matching = _maximum_assignment(matrix) if size else []
    tp = fp = fn = 0
    total_iou = 0.0
    for i, j in matching:
        a = actual[i] if i < len(actual) else set()
        b = proposed[j] if j < len(proposed) else set()
        allowed = i >= len(actual) or j >= len(proposed) or compatible(i,j)
        tp += len(a & b) if allowed else 0
        fp += len(b-a) if allowed else len(b)
        fn += len(a-b) if allowed else len(a)
        total_iou += matrix[i][j]
    mapped = [v for v in truth if "allowed_candidate_refs" in v]
    natural = set(natural_candidate_ids)
    recalled = sum(bool(natural & set(v["allowed_candidate_refs"])) for v in mapped)
    return dict(truth_axes=len(actual), predicted_axes=len(proposed),
        excluded_non_natural_predictions=len(predicted)-len(proposed),
        matched_mean_iou=total_iou/len(actual) if actual else None,
        precision=tp/(tp+fp) if tp+fp else None, recall=tp/(tp+fn) if tp+fn else None,
        f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
        candidate_recall=recalled/len(mapped) if mapped else None, candidate_mapped_truth=len(mapped),
        candidate_unmapped_truth=len(truth)-len(mapped), candidate_missed_truth=len(mapped)-recalled,
        matching=[list(v) for v in matching])
