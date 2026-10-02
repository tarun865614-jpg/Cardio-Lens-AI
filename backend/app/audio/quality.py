"""Recording-quality assessment (pipeline `sqa-1.0`).

Every check returns a status (pass / warn / fail), the measured value, the
threshold used, and a plain-language explanation. Thresholds are engineering
heuristics chosen to catch technically unusable audio; they have NOT been
clinically validated and are versioned so they can be tuned against labelled
quality data (see docs/VALIDATION_PLAN.md).

Design rule: a recording is rejected only for *technical* reasons. Rhythm
irregularity is never a rejection reason, because an irregular rhythm is a
potential clinical finding, not a recording fault.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import signal

from .decode import DecodedAudio
from .preprocess import (
    ANALYSIS_SR,
    bandpass,
    coarse_spectrogram,
    db,
    envelope_periodicity,
    frame_rms,
    minmax_waveform,
    remove_dc,
    resample,
    shannon_envelope,
)

PIPELINE_VERSION = "sqa-1.0"

T = dict(
    min_sample_rate=2000,
    min_duration_fail=5.0,
    min_duration_warn=10.0,
    max_duration=300.0,
    clip_warn=0.0005,
    clip_fail=0.01,
    silence_dbfs=-70.0,
    dropout_dbfs=-90.0,
    low_peak_dbfs=-40.0,
    dropout_warn=0.10,
    dropout_fail=0.50,
    snr_warn_db=10.0,
    snr_fail_db=6.0,
    inband_warn=0.50,
    inband_fail=0.25,
    periodicity_warn=0.30,
    lowfreq_warn=0.85,
)


@dataclass
class Check:
    id: str
    label: str
    status: str  # pass | warn | fail
    value: float | str | None
    threshold: str
    explanation: str


def _status(value: float, warn: float, fail: float, higher_is_worse: bool) -> str:
    if higher_is_worse:
        return "fail" if value >= fail else "warn" if value >= warn else "pass"
    return "fail" if value <= fail else "warn" if value <= warn else "pass"


def _band_power(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    f, p = signal.welch(x, fs=sr, nperseg=min(len(x), 1024))
    return f, p


def _band_fraction(f: np.ndarray, p: np.ndarray, lo: float, hi: float, tot_lo: float, tot_hi: float) -> float:
    tot = p[(f >= tot_lo) & (f <= tot_hi)].sum()
    if tot <= 0:
        return 0.0
    return float(p[(f >= lo) & (f < hi)].sum() / tot)


def window_quality(x: np.ndarray, sr: int, win_s: float = 5.0, hop_s: float = 2.5) -> list[dict]:
    """Per-window quality, so reviewers and models can focus on the cleanest segments."""
    out = []
    n, h = int(win_s * sr), int(hop_s * sr)
    if len(x) < n:
        return out
    for start in range(0, len(x) - n + 1, h):
        seg = x[start : start + n]
        fr = frame_rms(seg, sr, 0.02)
        snr = float(db(np.percentile(fr, 95)) - db(np.percentile(fr, 10) + 1e-12))
        env = shannon_envelope(seg, sr)
        per, _ = envelope_periodicity(env, 50)
        out.append({"start_s": round(start / sr, 2), "end_s": round((start + n) / sr, 2), "snr_db": round(snr, 1), "periodicity": round(per, 2)})
    return out


def assess(audio: DecodedAudio, *, include_visuals: bool = True) -> tuple[dict, dict | None]:
    """Return (quality_report, signal_summary). signal_summary is None if the audio can't be measured."""
    checks: list[Check] = []
    x0 = audio.samples
    sr0 = audio.sample_rate

    # --- container / format --------------------------------------------------
    checks.append(
        Check(
            "sample_rate", "Sample rate",
            "fail" if sr0 < T["min_sample_rate"] else "pass",
            sr0, f">= {T['min_sample_rate']} Hz",
            "Sample rate is sufficient to capture heart-sound frequencies."
            if sr0 >= T["min_sample_rate"]
            else f"{sr0} Hz cannot represent heart-sound content up to ~1 kHz. Record at 4 kHz or higher (44.1/48 kHz is typical).",
        )
    )
    checks.append(
        Check(
            "encoding", "Encoding",
            "warn" if audio.lossy else "pass",
            audio.source_format, "lossless preferred",
            f"Lossy '{audio.source_format}' compression can discard low-level sounds; use WAV where possible."
            if audio.lossy else "Lossless encoding.",
        )
    )

    finite = np.isfinite(x0)
    if not finite.all():
        checks.append(Check("integrity", "Data integrity", "fail", float(1 - finite.mean()), "no NaN/Inf samples",
                            "The file contains invalid sample values and appears corrupted. Please re-export or re-record."))
        return _report(checks, audio), None
    checks.append(Check("integrity", "Data integrity", "pass", 0.0, "no NaN/Inf samples", "Sample data is valid."))

    dur = audio.duration_s
    if dur < T["min_duration_fail"] or dur > T["max_duration"]:
        st = "fail"
    elif dur < T["min_duration_warn"]:
        st = "warn"
    else:
        st = "pass"
    checks.append(Check(
        "duration", "Duration", st, round(dur, 2),
        f"{T['min_duration_fail']:.0f}–{T['max_duration']:.0f} s (>= {T['min_duration_warn']:.0f} s recommended)",
        {"pass": "Duration covers multiple cardiac cycles.",
         "warn": "Short recording: fewer cardiac cycles are available for analysis. 15–30 s per site is recommended.",
         "fail": "Recording is too short to analyse reliably (minimum 5 s)." if dur < T["min_duration_fail"]
         else "Recording is too long for a single auscultation site; trim to under 5 minutes."}[st],
    ))

    # --- clipping (on original samples) --------------------------------------
    clip = audio.rail_fraction
    st = _status(clip, T["clip_warn"], T["clip_fail"], True)
    checks.append(Check(
        "clipping", "Clipping / saturation", st, round(clip * 100, 3),
        f"< {T['clip_warn'] * 100:.2f}% of samples at full scale",
        {"pass": "No meaningful clipping detected.",
         "warn": "Some samples hit the maximum level. Reduce input gain or chest-piece pressure if possible.",
         "fail": "The signal is heavily saturated; clipped audio distorts heart sounds. Lower the gain and re-record."}[st],
    ))

    # --- level & silence ------------------------------------------------------
    x = remove_dc(x0)
    rms_dbfs = float(db(np.sqrt(np.mean(x**2))))
    peak_dbfs = float(db(np.max(np.abs(x))))
    if rms_dbfs <= T["silence_dbfs"]:
        checks.append(Check("level", "Signal level", "fail", round(rms_dbfs, 1), f"RMS > {T['silence_dbfs']:.0f} dBFS",
                            "The recording is silent or nearly silent. Check the microphone/stethoscope connection and placement."))
        return _report(checks, audio), _summary_minimal(audio, rms_dbfs, peak_dbfs)
    st = "warn" if peak_dbfs < T["low_peak_dbfs"] else "pass"
    checks.append(Check("level", "Signal level", st, round(peak_dbfs, 1), f"peak > {T['low_peak_dbfs']:.0f} dBFS",
                        "Signal level is adequate." if st == "pass"
                        else "Signal is very quiet; low-level sounds may be lost in device noise. Increase gain or improve contact."))

    frames = frame_rms(x, sr0, 0.05)
    dropout = float(np.mean(db(frames) < T["dropout_dbfs"]))
    st = _status(dropout, T["dropout_warn"], T["dropout_fail"], True)
    checks.append(Check("dropouts", "Silence / dropouts", st, round(dropout * 100, 1),
                        f"< {T['dropout_warn'] * 100:.0f}% silent frames",
                        {"pass": "No significant gaps in the signal.",
                         "warn": "Parts of the recording are silent (possible loss of contact or dropouts).",
                         "fail": "Most of the recording is silent; the sensor likely lost contact."}[st]))

    if sr0 < T["min_sample_rate"]:
        return _report(checks, audio), _summary_minimal(audio, rms_dbfs, peak_dbfs)

    # --- spectral / noise ------------------------------------------------------
    f0, p0 = _band_power(x, sr0)
    low_frac = _band_fraction(f0, p0, 0, 20, 0, min(1000, sr0 / 2))

    xa = resample(x, sr0, ANALYSIS_SR)
    xa_hp = bandpass(xa, ANALYSIS_SR, 20, 950)
    f, p = _band_power(xa_hp, ANALYSIS_SR)
    inband = _band_fraction(f, p, 25, 400, 25, 950)

    st = _status(inband, T["inband_warn"], T["inband_fail"], False)
    checks.append(Check("spectral_noise", "Background noise (spectral)", st, round(inband, 2),
                        f"> {T['inband_warn']:.2f} of 25–950 Hz energy within 25–400 Hz",
                        {"pass": "Energy is concentrated in the typical heart-sound band.",
                         "warn": "Substantial high-frequency energy (speech, ambient or friction noise). Results may be less reliable.",
                         "fail": "The recording is dominated by noise outside the heart-sound band. Record in a quieter setting."}[st]))

    band = bandpass(xa, ANALYSIS_SR, 25, 400)
    fr = frame_rms(band, ANALYSIS_SR, 0.02)
    snr = float(db(np.percentile(fr, 95)) - db(np.percentile(fr, 10) + 1e-12))
    st = _status(snr, T["snr_warn_db"], T["snr_fail_db"], False)
    checks.append(Check("snr", "Signal-to-noise estimate", st, round(snr, 1),
                        f"> {T['snr_warn_db']:.0f} dB",
                        {"pass": "Distinct sound events stand out from the background.",
                         "warn": "Sound events are only moderately above the background noise floor.",
                         "fail": "No distinct sound events above the noise floor; the recording looks like continuous noise."}[st]))

    if low_frac >= T["lowfreq_warn"]:
        checks.append(Check("motion", "Low-frequency rumble", "warn", round(low_frac, 2), f"< {T['lowfreq_warn']:.2f} of energy below 20 Hz",
                            "Strong sub-audible energy suggests handling/motion artefact or breathing on the sensor."))
    else:
        checks.append(Check("motion", "Low-frequency rumble", "pass", round(low_frac, 2), f"< {T['lowfreq_warn']:.2f} of energy below 20 Hz",
                            "No dominant handling or motion artefact."))

    env = shannon_envelope(band, ANALYSIS_SR, 50)
    per, cpm = envelope_periodicity(env, 50)
    checks.append(Check("regularity", "Cycle regularity (informational)", "warn" if per < T["periodicity_warn"] else "pass",
                        round(per, 2), f"> {T['periodicity_warn']:.2f}",
                        "A repeating sound pattern was detected." if per >= T["periodicity_warn"]
                        else "No consistent repeating pattern was found. This can be caused by noise OR by an irregular rhythm — "
                             "listen to the recording. This check never rejects a recording on its own."))

    report = _report(checks, audio)
    summary = {
        "duration_s": round(dur, 2),
        "sample_rate_hz": sr0,
        "analysis_sample_rate_hz": ANALYSIS_SR,
        "channels": audio.channels,
        "source_format": audio.source_format,
        "bit_depth": audio.bit_depth,
        "rms_dbfs": round(rms_dbfs, 1),
        "peak_dbfs": round(peak_dbfs, 1),
        "band_energy_fraction": {
            "25-150Hz": round(_band_fraction(f, p, 25, 150, 25, 950), 3),
            "150-400Hz": round(_band_fraction(f, p, 150, 400, 25, 950), 3),
            "400-950Hz": round(_band_fraction(f, p, 400, 950, 25, 950), 3),
        },
        "envelope_periodicity": round(per, 3),
        "envelope_cycle_rate_per_min": round(cpm, 1) if cpm else None,
        "envelope_cycle_rate_note": "Dominant repetition rate of the sound envelope. A signal-processing estimate, "
                                    "not a validated heart-rate measurement; it can lock onto S1–S2 spacing or harmonics.",
        "windows": window_quality(band, ANALYSIS_SR),
    }
    if include_visuals:
        disp = xa_hp / (np.max(np.abs(xa_hp)) or 1.0)
        summary["waveform"] = minmax_waveform(disp, 800)
        summary["envelope"] = [round(float(v), 3) for v in env[:: max(1, len(env) // 1500)]]
        summary["spectrogram"] = coarse_spectrogram(xa, ANALYSIS_SR)
    return report, summary


def _summary_minimal(audio: DecodedAudio, rms_dbfs: float, peak_dbfs: float) -> dict:
    return {"duration_s": round(audio.duration_s, 2), "sample_rate_hz": audio.sample_rate, "channels": audio.channels,
            "source_format": audio.source_format, "rms_dbfs": round(rms_dbfs, 1), "peak_dbfs": round(peak_dbfs, 1)}


def _report(checks: list[Check], audio: DecodedAudio) -> dict:
    statuses = {c.status for c in checks}
    overall = "unusable" if "fail" in statuses else "usable_with_warnings" if "warn" in statuses else "usable"
    failing = [c.label for c in checks if c.status == "fail"]
    return {
        "pipeline_version": PIPELINE_VERSION,
        "overall": overall,
        "recommend_rerecord": overall == "unusable",
        "headline": (
            "Recording is not usable for analysis: " + ", ".join(failing).lower() + ". Please record again."
            if overall == "unusable"
            else "Recording passed quality checks with warnings — review before relying on any analysis."
            if overall == "usable_with_warnings"
            else "Recording passed all technical quality checks."
        ),
        "checks": [asdict(c) for c in checks],
        "notes": audio.notes,
        "disclaimer": "Quality checks are technical heuristics (not clinically validated). Passing them does not mean "
                      "the recording is diagnostic-grade, and smartphone microphones are not equivalent to an electronic stethoscope.",
    }
