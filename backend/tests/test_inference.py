import json
import time

import httpx
import pytest

from app.audio.decode import decode_audio
from app.inference.adapters import HttpModelAdapter, LocalBaselineAdapter
from app.inference.base import InferenceError, ModelCard, validate_output
from app.inference.service import analyze

from .conftest import wav

CATS = [{"id": "normal", "label": "Normal"}, {"id": "abnormal", "label": "Abnormal"}]


def card(**kw) -> ModelCard:
    base = dict(name="m", version="1.0", intended_use="test", categories=CATS)
    base.update(kw)
    return ModelCard(**base)


class FakeAdapter:
    def __init__(self, c: ModelCard, out=None, exc=None, delay=0.0):
        self.card, self.out, self.exc, self.delay, self.calls = c, out, exc, delay, 0

    def predict(self, inp):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.out


GOOD = {"scores": [{"category": "normal", "score": 0.3}, {"category": "abnormal", "score": 0.7}]}


def run(adapter, kind="clean", device="electronic_stethoscope", site="mitral"):
    return analyze(decode_audio(wav(kind)), device_type=device, auscultation_site=site, adapter=adapter, use_configured=False)


def test_no_model_gives_signal_only_without_any_prediction():
    o = analyze(decode_audio(wav()), device_type="unknown", auscultation_site="mitral", adapter=None, use_configured=False)
    assert o.model_status == "no_model" and o.result_tier == "signal_only" and o.model_output is None


def test_quality_failure_never_calls_model():
    a = FakeAdapter(card(), GOOD)
    o = run(a, kind="silence")
    assert a.calls == 0 and o.model_status == "not_run_quality" and o.model_output is None


@pytest.mark.parametrize("exc", [InferenceError("boom"), RuntimeError("segfault-ish"), ValueError("bad")])
def test_model_errors_never_produce_a_result(exc):
    o = run(FakeAdapter(card(), exc=exc))
    assert o.model_status == "service_error" and o.model_output is None and o.result_tier == "signal_only"
    assert "No model result" in o.error


def test_model_timeout_never_produces_a_result():
    o = run(FakeAdapter(card(), GOOD, delay=3.0))  # timeout configured to 0.5 s (+1 s grace) in conftest
    assert o.model_status == "service_error" and o.model_output is None and "timed out" in o.error


@pytest.mark.parametrize("bad", [
    None, [], {"scores": []},
    {"scores": [{"category": "normal", "score": 1.3}, {"category": "abnormal", "score": -0.3}]},
    {"scores": [{"category": "normal", "score": 0.5}, {"category": "cancer", "score": 0.5}]},
    {"scores": [{"category": "normal", "score": 0.9}]},
    {"scores": [{"category": "normal", "score": 0.9}, {"category": "abnormal", "score": 0.9}]},
    {"scores": [{"category": "normal", "score": float("nan")}, {"category": "abnormal", "score": 0.5}]},
    {"scores": [{"category": "normal", "score": "0.5"}, {"category": "abnormal", "score": 0.5}]},
    {"abstained": "yes"},
])
def test_contract_violations_rejected(bad):
    o = run(FakeAdapter(card(), bad))
    assert o.model_status == "service_error" and o.model_output is None


def test_research_model_output_is_experimental_and_uncalibrated_warning():
    o = run(FakeAdapter(card(), GOOD))
    assert o.model_status == "completed" and o.result_tier == "experimental"
    assert o.model_output["scores"][1]["score_type"] == "uncalibrated_score"
    assert any("not calibrated" in x for x in o.model_output["limitations"])


def test_validated_card_requires_evidence():
    with pytest.raises(ValueError):
        card(validation_status="externally_validated")
    with pytest.raises(ValueError):
        card(validation_status="clinically_proven")


def test_validated_model_in_scope_is_validated_tier():
    c = card(validation_status="externally_validated", validation_evidence="doi:10.0000/example", calibrated=True,
             supported_devices=["electronic_stethoscope"])
    o = run(FakeAdapter(c, GOOD))
    assert o.result_tier == "validated"
    assert o.model_output["scores"][0]["score_type"] == "calibrated_probability"


def test_validated_model_out_of_scope_device_downgraded():
    c = card(validation_status="externally_validated", validation_evidence="doi:x", supported_devices=["electronic_stethoscope"])
    o = run(FakeAdapter(c, GOOD), device="smartphone_mic")
    assert o.result_tier == "experimental"
    assert any("outside the model's validated devices" in x for x in o.model_output["limitations"])


def test_abstention_is_passed_through_without_scores():
    o = run(FakeAdapter(card(), {"abstained": True, "abstain_reason": "too noisy"}))
    assert o.model_output["abstained"] and o.model_output["scores"] == []


def test_validate_output_direct():
    out = validate_output(card(), GOOD)
    assert [s["category"] for s in out["scores"]] == ["normal", "abnormal"]


def _http(handler, version="1.0"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpModelAdapter("http://model.local", card(version=version), timeout_s=0.5, client=client)


def test_http_adapter_success():
    def h(req):
        body = json.loads(req.content)
        assert body["contract"] == "inference/v1" and body["sample_rate"] == 2000
        return httpx.Response(200, json={"model": {"name": "m", "version": "1.0"}, **GOOD})
    o = run(_http(h))
    assert o.model_status == "completed" and o.result_tier == "experimental"


@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(500, text="oops"),
    lambda req: httpx.Response(200, text="<html>"),
    lambda req: httpx.Response(200, json={"model": {"name": "m", "version": "2.0"}, **GOOD}),
])
def test_http_adapter_failures(handler):
    o = run(_http(handler))
    assert o.model_status == "service_error" and o.model_output is None


def test_http_adapter_timeout_and_unreachable():
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    def down(req):
        raise httpx.ConnectError("refused", request=req)

    for h, msg in ((slow, "timed out"), (down, "unreachable")):
        o = run(_http(h))
        assert o.model_status == "service_error" and msg in o.error


def test_local_baseline_cannot_self_certify(tmp_path):
    from app.research.baseline import run as train, synthetic_manifest

    rows = synthetic_manifest(tmp_path, n_patients=24)
    train(rows, tmp_path / "out", synthetic=True)
    w = json.loads((tmp_path / "out" / "weights.json").read_text())
    w["card"]["validation_status"] = "externally_validated"
    w["card"]["validation_evidence"] = "trust me"
    (tmp_path / "w.json").write_text(json.dumps(w))
    a = LocalBaselineAdapter(tmp_path / "w.json")
    assert a.card.validation_status == "research_only" and a.card.weights_sha256
    o = run(a)
    assert o.model_status == "completed" and o.result_tier == "experimental"
    assert abs(sum(s["score"] for s in o.model_output["scores"]) - 1) < 0.01
    # Test split predictions are written in the Research Lab upload format.
    header = (tmp_path / "out" / "test_predictions.csv").read_text().splitlines()[0]
    assert header.startswith("recording_id,patient_id,label,score,split,quality_pass")
