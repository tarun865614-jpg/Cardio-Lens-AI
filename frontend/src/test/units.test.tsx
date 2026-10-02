import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelPanel, QualityPanel } from "../components/AnalysisPanels";
import { ModeBanner } from "../components/Layout";
import { QualityBadge, ReviewBadge, TierBadge } from "../components/ui";
import { fmtProportion } from "../lib/format";
import type { Analysis } from "../lib/types";
import { clipFraction, encodeWav, levelDbfs } from "../lib/wav";

async function bytes(b: Blob): Promise<Uint8Array> {
  const buf = await new Promise<ArrayBuffer>((resolve) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as ArrayBuffer);
    r.readAsArrayBuffer(b);
  });
  return new Uint8Array(buf);
}

describe("wav encoder", () => {
  it("writes a valid 16-bit mono PCM header and clamps samples", async () => {
    const blob = encodeWav([new Float32Array([0, 1, -1, 2])], 48000);
    const b = await bytes(blob);
    const v = new DataView(b.buffer);
    expect(String.fromCharCode(...b.slice(0, 4))).toBe("RIFF");
    expect(String.fromCharCode(...b.slice(8, 12))).toBe("WAVE");
    expect(v.getUint16(22, true)).toBe(1);
    expect(v.getUint32(24, true)).toBe(48000);
    expect(v.getUint32(40, true)).toBe(8);
    expect(v.getInt16(46, true)).toBe(32767);
    expect(v.getInt16(48, true)).toBe(-32768);
    expect(v.getInt16(50, true)).toBe(32767); // clamped
  });
  it("meters level and clipping", () => {
    expect(levelDbfs(new Float32Array(100))).toBe(-120);
    expect(levelDbfs(new Float32Array(100).fill(1))).toBeCloseTo(0);
    expect(clipFraction(new Float32Array([1, 0, 0, -1]))).toBe(0.5);
  });
});

describe("metric formatting", () => {
  it("never invents a value", () => {
    expect(fmtProportion({ value: null, ci_low: null, ci_high: null, reason: "no cases in denominator" })).toBe(
      "Not evaluated (no cases in denominator)",
    );
    expect(fmtProportion(undefined)).toBe("Not evaluated");
    expect(fmtProportion({ value: 0.75, ci_low: 0.6, ci_high: 0.86, k: 30, n: 40 })).toBe("75.0% (95% CI 60.0%–86.0%) · 30/40");
  });
});

const quality = {
  pipeline_version: "sqa-1.0",
  overall: "usable" as const,
  recommend_rerecord: false,
  headline: "Recording passed all technical quality checks.",
  checks: [{ id: "snr", label: "Signal-to-noise estimate", status: "pass" as const, value: 30, threshold: "> 10 dB", explanation: "ok" }],
  notes: [],
  disclaimer: "heuristics",
};

function analysis(over: Partial<Analysis>): Analysis {
  return {
    id: 1,
    created_at: "2026-01-01T00:00:00Z",
    pipeline_version: "sqa-1.0",
    quality,
    signal_summary: {},
    model_status: "no_model",
    model_status_text: "Research-demo mode: no validated model is configured, so no screening result is produced.",
    result_tier: "signal_only",
    result_tier_text: "",
    model_name: null,
    model_version: null,
    model_output: null,
    error: null,
    boundaries: ["A negative or low score does not mean the heart is healthy."],
    ...over,
  };
}

describe("result labelling", () => {
  it("research-demo mode shows no scores", () => {
    render(<ModelPanel a={analysis({})} />);
    expect(screen.getAllByText(/Research-demo mode/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/score/i, { selector: "p.label" })).toBeNull();
    expect(screen.getByText(/does not mean the heart is healthy/)).toBeInTheDocument();
  });

  it("service errors show no result", () => {
    render(<ModelPanel a={analysis({ model_status: "service_error", error: "Model inference timed out. No model result is available." })} />);
    expect(screen.getByText("Model unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Nothing has been inferred/)).toBeInTheDocument();
  });

  it("experimental output is labelled and uncalibrated scores are not probabilities", () => {
    render(
      <ModelPanel
        a={analysis({
          model_status: "completed",
          result_tier: "experimental",
          model_output: {
            abstained: false,
            abstain_reason: null,
            scores: [{ category: "abnormal", label: "Abnormal", score: 0.71, score_type: "uncalibrated_score" }],
            segments: [],
            tier_reason: "Model validation status is 'research_only'.",
            limitations: ["Model scores are not calibrated probabilities"],
          },
        })}
      />,
    );
    expect(screen.getByText("Experimental AI")).toBeInTheDocument();
    expect(screen.getByText(/research use only/)).toBeInTheDocument();
    expect(screen.getByText(/Uncalibrated model score — not a probability of disease/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("unusable quality is a technical issue and asks to re-record", () => {
    render(<QualityPanel q={{ ...quality, overall: "unusable", recommend_rerecord: true, headline: "Recording is not usable" }} />);
    expect(screen.getByText(/please record again/i)).toBeInTheDocument();
    expect(screen.getByText(/not a clinical finding/)).toBeInTheDocument();
  });

  it("badges distinguish technical issues from clinical flags", () => {
    render(
      <>
        <QualityBadge status="unusable" />
        <ReviewBadge status="flagged" />
        <TierBadge tier="validated" status="completed" />
      </>,
    );
    expect(screen.getByText("Recording issue")).toHaveAttribute("title", expect.stringMatching(/not a clinical finding/));
    expect(screen.getByText("Flagged for follow-up")).toBeInTheDocument();
    expect(screen.getByText("Validated model")).toBeInTheDocument();
  });

  it("mode banner always states it is not a diagnostic device", () => {
    render(<ModeBanner mode={{ mode: "research_demo", label: "Research-demo mode", detail: "No validated model.", model: null }} />);
    expect(screen.getByTestId("mode-banner")).toHaveTextContent(/Not a diagnostic device/);
  });
});
