import { useEffect, useRef } from "react";
import type { Spectrogram } from "../lib/types";

function useCanvas(draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void, deps: unknown[]) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const render = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = c.clientWidth;
      const h = c.clientHeight;
      c.width = Math.max(1, Math.floor(w * dpr));
      c.height = Math.max(1, Math.floor(h * dpr));
      const ctx = c.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      draw(ctx, w, h);
    };
    render();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(render) : null;
    ro?.observe(c);
    return () => ro?.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

interface Region {
  start_s: number;
  end_s: number;
}

export function Waveform({
  data,
  duration,
  progress = 0,
  highlights = [],
  onSeek,
}: {
  data: [number, number][];
  duration: number;
  progress?: number;
  highlights?: Region[];
  onSeek?: (t: number) => void;
}) {
  const ref = useCanvas(
    (ctx, w, h) => {
      const mid = h / 2;
      ctx.fillStyle = "rgba(60,154,145,0.10)";
      for (const r of highlights) ctx.fillRect((r.start_s / duration) * w, 0, ((r.end_s - r.start_s) / duration) * w, h);
      ctx.strokeStyle = "#e2e8f0";
      ctx.beginPath();
      ctx.moveTo(0, mid);
      ctx.lineTo(w, mid);
      ctx.stroke();
      const n = data.length;
      const playedX = progress * w;
      for (let i = 0; i < n; i++) {
        const x = (i / n) * w;
        const [lo, hi] = data[i];
        ctx.fillStyle = x <= playedX ? "#2f7f78" : "#1d3a63";
        ctx.fillRect(x, mid - hi * mid * 0.95, Math.max(1, w / n), Math.max(1, (hi - lo) * mid * 0.95));
      }
      if (progress > 0) {
        ctx.fillStyle = "#0b1f3a";
        ctx.fillRect(playedX, 0, 1.5, h);
      }
    },
    [data, duration, progress, highlights],
  );
  return (
    <canvas
      ref={ref}
      className="h-32 w-full cursor-pointer rounded-md bg-slate-50 sm:h-40"
      role="img"
      aria-label={`Waveform, ${duration.toFixed(1)} seconds (band-limited 20–950 Hz display). Click to seek.`}
      onClick={(e) => {
        if (!onSeek) return;
        const rect = e.currentTarget.getBoundingClientRect();
        onSeek(((e.clientX - rect.left) / rect.width) * duration);
      }}
    />
  );
}

// Perceptually ordered navy → teal → pale ramp.
function ramp(v: number): string {
  const t = v / 255;
  const stops = [
    [11, 31, 58],
    [29, 58, 99],
    [47, 127, 120],
    [143, 208, 199],
    [240, 250, 248],
  ];
  const p = t * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(p));
  const f = p - i;
  const c = stops[i].map((a, k) => Math.round(a + (stops[i + 1][k] - a) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function SpectrogramView({ spec, progress = 0 }: { spec: Spectrogram; progress?: number }) {
  const ref = useCanvas(
    (ctx, w, h) => {
      const F = spec.db_u8.length;
      const T = spec.db_u8[0]?.length ?? 0;
      const cw = w / Math.max(1, T);
      const ch = h / Math.max(1, F);
      for (let f = 0; f < F; f++) {
        for (let t = 0; t < T; t++) {
          ctx.fillStyle = ramp(spec.db_u8[f][t]);
          ctx.fillRect(t * cw, h - (f + 1) * ch, cw + 0.5, ch + 0.5);
        }
      }
      if (progress > 0) {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(progress * w, 0, 1.5, h);
      }
    },
    [spec, progress],
  );
  const top = spec.freqs_hz[spec.freqs_hz.length - 1] ?? 1000;
  return (
    <div className="relative">
      <canvas ref={ref} className="h-28 w-full rounded-md sm:h-36" role="img" aria-label={`Spectrogram 0–${Math.round(top)} Hz, ${spec.range_db} dB range`} />
      <span className="absolute left-1 top-1 rounded bg-navy-950/60 px-1 text-[10px] text-white">{Math.round(top)} Hz</span>
      <span className="absolute bottom-1 left-1 rounded bg-navy-950/60 px-1 text-[10px] text-white">0 Hz</span>
    </div>
  );
}
