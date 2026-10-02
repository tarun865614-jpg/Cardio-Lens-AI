import io
import shutil
import subprocess

import numpy as np
import pytest
from scipy.io import wavfile

from app.audio.decode import AudioDecodeError, decode_audio
from app.audio.quality import assess
from app.audio.synthetic import synth_pcg, to_wav_bytes

from .conftest import wav


def status_of(data: bytes) -> tuple[str, dict]:
    report, _ = assess(decode_audio(data, "x.wav"))
    return report["overall"], {c["id"]: c["status"] for c in report["checks"]}


def test_clean_recording_is_usable():
    overall, checks = status_of(wav("clean"))
    assert overall == "usable"
    assert all(s == "pass" for s in checks.values())


@pytest.mark.parametrize("kind,check", [("silence", "level"), ("clipped", "clipping"), ("noise", "snr"), ("short", "duration")])
def test_unusable_recordings_fail_specific_check(kind, check):
    overall, checks = status_of(wav(kind))
    assert overall == "unusable"
    assert checks[check] == "fail"


def test_unusable_report_recommends_rerecord():
    report, _ = assess(decode_audio(wav("silence")))
    assert report["recommend_rerecord"] is True
    assert "record again" in report["headline"].lower()


def test_irregular_rhythm_is_never_rejected():
    # An irregular rhythm is a potential clinical finding, not a recording fault.
    x = synth_pcg(irregular=0.4, seed=7, duration_s=20)
    overall, checks = status_of(to_wav_bytes(x, 4000))
    assert overall != "unusable"
    assert checks["regularity"] in ("warn", "pass")


def test_low_sample_rate_rejected():
    x = synth_pcg(sr=1000, duration_s=15)
    overall, checks = status_of(to_wav_bytes(x, 1000))
    assert overall == "unusable" and checks["sample_rate"] == "fail"


def test_dropouts_detected():
    x = synth_pcg(duration_s=20)
    x[8000:72000] = 0
    overall, checks = status_of(to_wav_bytes(x, 4000))
    assert checks["dropouts"] == "fail" and overall == "unusable"


def test_nan_float_wav_is_corrupted():
    x = synth_pcg(duration_s=10).astype(np.float32)
    x[100:200] = np.nan
    overall, checks = status_of(to_wav_bytes(x, 4000, dtype="float32"))
    assert overall == "unusable" and checks["integrity"] == "fail"


@pytest.mark.parametrize("payload", [b"", b"not audio at all", b"RIFF\x00\x00\x00\x00WAVEgarbage"])
def test_corrupted_or_unsupported_bytes_raise(payload):
    with pytest.raises(AudioDecodeError):
        decode_audio(payload, "file.wav" if payload.startswith(b"RIFF") else "file.xyz")


@pytest.mark.parametrize("dtype", [np.uint8, np.int16, np.int32, np.float32])
def test_decodes_common_wav_sample_formats(dtype):
    x = synth_pcg(duration_s=12, amplitude=0.4)
    if dtype == np.uint8:
        data = (x * 127 + 128).astype(np.uint8)
    elif dtype == np.float32:
        data = x.astype(np.float32)
    else:
        data = (x * np.iinfo(dtype).max).astype(dtype)
    buf = io.BytesIO()
    wavfile.write(buf, 4000, data)
    audio = decode_audio(buf.getvalue())
    assert audio.sample_rate == 4000 and abs(audio.duration_s - 12) < 0.01
    assert np.max(np.abs(audio.samples)) <= 1.0


def test_stereo_is_downmixed():
    x = synth_pcg(duration_s=10)
    buf = io.BytesIO()
    wavfile.write(buf, 8000, np.stack([(x * 20000).astype(np.int16)] * 2, axis=1).repeat(1, axis=0)[: len(x)])
    audio = decode_audio(buf.getvalue())
    assert audio.channels == 2 and audio.samples.ndim == 1


def test_high_sample_rate_is_resampled_for_analysis():
    x = synth_pcg(sr=48000, duration_s=12)
    report, summary = assess(decode_audio(to_wav_bytes(x, 48000)))
    assert report["overall"] == "usable"
    assert summary["sample_rate_hz"] == 48000 and summary["analysis_sample_rate_hz"] == 2000


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_lossy_format_transcoded_with_warning(tmp_path):
    src = tmp_path / "a.wav"
    src.write_bytes(to_wav_bytes(synth_pcg(sr=8000, duration_s=12), 8000))
    dst = tmp_path / "a.ogg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:a", "libopus", str(dst)], check=True)
    audio = decode_audio(dst.read_bytes(), "a.ogg")
    assert audio.lossy
    report, _ = assess(audio)
    assert {c["id"]: c["status"] for c in report["checks"]}["encoding"] == "warn"


def test_every_check_has_explanation_and_threshold():
    report, summary = assess(decode_audio(wav("clean")))
    for c in report["checks"]:
        assert c["explanation"] and c["threshold"]
    assert "not a validated heart-rate" in summary["envelope_cycle_rate_note"]
    assert report["pipeline_version"] == "sqa-1.0"
