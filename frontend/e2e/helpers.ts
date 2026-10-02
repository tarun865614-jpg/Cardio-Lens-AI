import { expect, type Page } from "@playwright/test";

export async function login(page: Page, role: "clinician" | "researcher" | "admin") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(`${role}@demo.cardiolens.local`);
  await page.getByLabel("Password").fill("demo-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("mode-banner")).toBeVisible();
}

/** Synthetic S1/S2-like tone bursts as a 16-bit WAV (test fixture only — not physiological). */
export function syntheticWav({ seconds = 15, sr = 4000, silent = false } = {}): Buffer {
  const n = seconds * sr;
  const pcm = new Int16Array(n);
  if (!silent) {
    const rr = 60 / 72;
    for (let beat = 0.2; beat < seconds - 1; beat += rr) {
      for (const [offset, dur, f, amp] of [[0, 0.1, 55, 0.5], [0.3, 0.08, 80, 0.35]]) {
        const start = Math.floor((beat + offset) * sr);
        const len = Math.floor(dur * sr);
        for (let i = 0; i < len && start + i < n; i++) {
          const env = Math.sin((Math.PI * i) / len) ** 2;
          pcm[start + i] += Math.round(32767 * amp * env * Math.sin((2 * Math.PI * f * i) / sr));
        }
      }
    }
    for (let i = 0; i < n; i++) pcm[i] += Math.round((Math.random() - 0.5) * 300);
  }
  const buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + n * 2, 4);
  buf.write("WAVE", 8);
  buf.write("fmt ", 12);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(sr, 24);
  buf.writeUInt32LE(sr * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(n * 2, 40);
  Buffer.from(pcm.buffer).copy(buf, 44);
  return buf;
}
