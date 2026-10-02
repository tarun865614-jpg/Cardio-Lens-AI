import numpy as np
import pytest

from app.research.evaluation import EvaluationError, evaluate
from app.research.metrics import auc, binary_metrics, calibration, wilson


def test_wilson_reference_values():
    w = wilson(81, 263)  # reference: Wilson 95% CI ≈ (0.2553, 0.3662)
    assert w["value"] == pytest.approx(0.308, abs=1e-3)
    assert w["ci_low"] == pytest.approx(0.2553, abs=1e-3) and w["ci_high"] == pytest.approx(0.3662, abs=1e-3)


def test_zero_denominator_is_not_imputed():
    w = wilson(0, 0)
    assert w["value"] is None and "no cases" in w["reason"]


def test_auc_known_cases():
    y = np.array([0, 0, 1, 1])
    assert auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert auc(y, np.array([0.5, 0.5, 0.5, 0.5])) == 0.5
    assert auc(np.array([1, 1]), np.array([0.2, 0.3])) is None


def test_binary_metrics_confusion_and_ci():
    y = [1, 1, 1, 0, 0, 0, 0, 1]
    s = [0.9, 0.8, 0.3, 0.2, 0.1, 0.7, 0.4, 0.6]
    m = binary_metrics(y, s, [f"p{i}" for i in range(8)], 0.5, n_boot=200)
    assert m["confusion"] == {"tp": 3, "fp": 1, "tn": 3, "fn": 1}
    assert m["sensitivity"]["value"] == 0.75 and m["specificity"]["value"] == 0.75
    assert m["auc"]["ci_low"] <= m["auc"]["value"] <= m["auc"]["ci_high"]


def test_calibration_perfect_vs_overconfident():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 5000)
    y = (rng.uniform(0, 1, 5000) < p).astype(int)
    good = calibration(y, p)
    bad = calibration(y, np.where(p > 0.5, 0.99, 0.01))
    assert good["ece"] < 0.03 < bad["ece"]
    assert 0.8 < good["slope"] < 1.2


def csv_rows(rows, extra=""):
    head = "recording_id,patient_id,label,score,split,quality_pass" + ("," + extra if extra else "")
    return "\n".join([head] + rows)


def test_rejects_training_split_rows():
    with pytest.raises(EvaluationError, match="held-out"):
        evaluate(csv_rows(["r1,p1,1,0.9,train,1", "r2,p2,0,0.1,test,1"]))


def test_rejects_patient_leakage_against_training_manifest():
    with pytest.raises(EvaluationError, match="leakage"):
        evaluate(csv_rows(["r1,p1,1,0.9,test,1", "r2,p2,0,0.1,test,1"]), training_patients={"p2", "p9"})


def test_rejects_patient_in_two_splits():
    with pytest.raises(EvaluationError, match="more than one split"):
        evaluate(csv_rows(["r1,p1,1,0.9,test,1", "r2,p1,0,0.1,external,1"]))


@pytest.mark.parametrize("row,msg", [("r1,p1,2,0.9,test,1", "label"), ("r1,p1,1,1.9,test,1", "outside"), ("r1,p1,1,abc,test,1", "number")])
def test_rejects_invalid_values(row, msg):
    with pytest.raises(EvaluationError, match=msg):
        evaluate(csv_rows([row]))


def test_failed_recordings_and_subgroups():
    rows = [f"r{i},p{i},{i % 2},{0.8 if i % 2 else 0.2},test,{0 if i < 4 else 1},{'phone' if i % 3 else 'steth'}" for i in range(40)]
    res = evaluate(csv_rows(rows, "device"), training_patients=set(), n_boot=100)
    o = res["overall"]
    assert o["failed_recording_rate"]["k"] == 4 and o["n"] == 36
    assert set(res["subgroups"]["device"]) == {"phone", "steth"}
    assert "warning" in res["subgroups"]["device"]["steth"]  # n < 30
    assert any("External validation" in w for w in res["warnings"])
