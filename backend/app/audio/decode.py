"""Audio decoding and container validation.

WAV (PCM 8/16/24/32-bit, IEEE float) is decoded natively. Other formats
(FLAC, OGG/Opus, WebM, MP3, M4A) are transcoded through ffmpeg if it is
installed; otherwise they are rejected with a clear message rather than guessed.
Note that lossy codecs (MP3/AAC/Opus) can remove or smear low-level acoustic
content; that fact is surfaced as a quality warning.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

MAX_CHANNELS = 8
LOSSY_FORMATS = {"mp3", "m4a", "aac", "ogg", "opus", "webm"}
SUPPORTED_EXTENSIONS = {"wav", "flac", *LOSSY_FORMATS}


class AudioDecodeError(ValueError):
    """Raised when bytes cannot be decoded into a usable PCM signal."""


@dataclass
class DecodedAudio:
    samples: np.ndarray  # mono float64 in [-1, 1]
    sample_rate: int
    channels: int
    source_format: str
    bit_depth: int | None
    lossy: bool
    # Fraction of samples at the integer full-scale rails, computed before float conversion.
    rail_fraction: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return len(self.samples) / float(self.sample_rate) if self.sample_rate else 0.0


def sniff_format(data: bytes, filename: str | None) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "mp3"
    if data[4:8] == b"ftyp":
        return "m4a"
    ext = (Path(filename).suffix.lower().lstrip(".") if filename else "")
    return ext or "unknown"


def _decode_wav(data: bytes) -> DecodedAudio:
    # Try scipy first: handles float WAV and WAVE_FORMAT_EXTENSIBLE.
    from scipy.io import wavfile

    try:
        sr, raw = wavfile.read(io.BytesIO(data))
    except Exception:
        try:
            with wave.open(io.BytesIO(data)) as w:
                sr = w.getframerate()
                ch = w.getnchannels()
                width = w.getsampwidth()
                frames = w.readframes(w.getnframes())
            if width not in (1, 2, 4):
                raise AudioDecodeError(f"Unsupported WAV sample width: {width * 8}-bit")
            dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
            raw = np.frombuffer(frames, dtype=dtype)
            if ch > 1:
                raw = raw.reshape(-1, ch)
        except AudioDecodeError:
            raise
        except Exception as e:
            raise AudioDecodeError("File is not a readable WAV recording (header or data corrupted)") from e

    raw = np.asarray(raw)
    channels = 1 if raw.ndim == 1 else raw.shape[1]
    if channels > MAX_CHANNELS:
        raise AudioDecodeError(f"Too many channels ({channels})")

    bit_depth: int | None
    if raw.dtype == np.uint8:
        bit_depth = 8
        rails = np.mean((raw == 0) | (raw == 255)) if raw.size else 0.0
        x = (raw.astype(np.float64) - 128.0) / 128.0
    elif raw.dtype == np.int16:
        bit_depth = 16
        rails = np.mean((raw <= -32767) | (raw >= 32767)) if raw.size else 0.0
        x = raw.astype(np.float64) / 32768.0
    elif raw.dtype == np.int32:
        # scipy returns 24-bit data left-justified in int32.
        bit_depth = 32
        info = np.iinfo(np.int32)
        thr = info.max - (1 << 8)
        rails = np.mean((raw <= -thr) | (raw >= thr)) if raw.size else 0.0
        x = raw.astype(np.float64) / float(1 << 31)
    elif raw.dtype in (np.float32, np.float64):
        bit_depth = 32 if raw.dtype == np.float32 else 64
        x = raw.astype(np.float64)
        rails = np.mean(np.abs(x) >= 0.999) if x.size else 0.0
    else:
        raise AudioDecodeError(f"Unsupported WAV sample type: {raw.dtype}")

    if x.ndim == 2:
        x = x.mean(axis=1)
    return DecodedAudio(
        samples=x,
        sample_rate=int(sr),
        channels=channels,
        source_format="wav",
        bit_depth=bit_depth,
        lossy=False,
        rail_fraction=float(rails),
    )


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _transcode_with_ffmpeg(data: bytes, fmt: str, timeout_s: float = 30.0) -> bytes:
    if not ffmpeg_available():
        raise AudioDecodeError(
            f"'{fmt}' files require ffmpeg on the server, which is not installed. Upload a WAV file instead."
        )
    with tempfile.TemporaryDirectory(prefix="cl-") as td:
        src = Path(td) / f"in.{fmt}"
        dst = Path(td) / "out.wav"
        src.write_bytes(data)
        # Keep native sample rate; convert to 32-bit float to avoid extra quantisation.
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-c:a", "pcm_f32le", str(dst)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            raise AudioDecodeError("Audio conversion timed out") from e
        if proc.returncode != 0 or not dst.exists():
            raise AudioDecodeError("Audio file could not be decoded (corrupted or unsupported encoding)")
        return dst.read_bytes()
    # TemporaryDirectory is removed on exit — no plaintext audio is left on disk.


def decode_audio(data: bytes, filename: str | None = None) -> DecodedAudio:
    if not data:
        raise AudioDecodeError("File is empty")
    fmt = sniff_format(data, filename)
    if fmt == "wav":
        out = _decode_wav(data)
    elif fmt in SUPPORTED_EXTENSIONS:
        out = _decode_wav(_transcode_with_ffmpeg(data, fmt))
        out.source_format = fmt
        out.lossy = fmt in LOSSY_FORMATS
        out.bit_depth = None
        if out.lossy:
            out.notes.append(f"Lossy '{fmt}' encoding may remove low-level acoustic detail.")
    else:
        raise AudioDecodeError("Unsupported file type. Accepted: WAV (preferred), FLAC, OGG, WebM, MP3, M4A.")

    if out.samples.size == 0:
        raise AudioDecodeError("File contains no audio samples")
    return out
