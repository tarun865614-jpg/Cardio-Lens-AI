import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login, syntheticWav } from "./helpers";

test.describe.configure({ mode: "serial" });

async function newPatientAndImport(page: import("@playwright/test").Page, wav: Buffer) {
  await page.getByRole("link", { name: "New Recording", exact: true }).click();
  await page.getByRole("button", { name: "New patient" }).click();
  await expect(page.getByLabel("Patient", { exact: true })).not.toHaveValue("");
  await page.getByLabel("Recording device").selectOption("electronic_stethoscope");
  await page.getByLabel("Auscultation site").selectOption("aortic");
  await page.locator('input[type="file"]').setInputFiles({ name: "e2e.wav", mimeType: "audio/wav", buffer: wav });
  await expect(page.getByLabel("Preview recording")).toBeVisible();
  const submit = page.getByRole("button", { name: "Upload and analyse" });
  await expect(submit).toBeDisabled(); // consent not yet given
  await page.getByText(/has consented to this heart-sound recording/).click();
  await submit.click();
}

test("clinician: dashboard shows demo data and research-demo mode", async ({ page }) => {
  await login(page, "clinician");
  await expect(page.getByTestId("mode-banner")).toContainText("Research-demo mode");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("DEMO · synthetic").first()).toBeVisible();
  await expect(page.getByText("Recording issue").first()).toBeVisible();
  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
});

test("clinician: import → quality → playback → review → report", async ({ page }) => {
  await login(page, "clinician");
  await newPatientAndImport(page, syntheticWav());

  await expect(page).toHaveURL(/\/recordings\/\d+/);
  await expect(page.getByRole("heading", { name: /Audio analysis/ })).toBeVisible();
  await expect(page.getByText("Quality: usable").first()).toBeVisible();
  await expect(page.getByTestId("model-panel")).toContainText("No disease prediction has been simulated");
  await expect(page.getByTestId("model-panel")).not.toContainText("%");

  // Original audio is fetched with auth and is playable.
  const audio = page.getByLabel("Original recording playback");
  await expect(audio).toBeVisible();
  await expect.poll(async () => audio.evaluate((el: HTMLAudioElement) => el.duration)).toBeGreaterThan(14);
  await expect(page.getByRole("img", { name: /Waveform/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /Spectrogram/ })).toBeVisible();

  // Clinician review with a follow-up flag.
  await page.getByLabel("Notes").fill("E2E listening note");
  await page.getByLabel("Clinician conclusion / next steps").fill("E2E: refer for echocardiogram");
  await page.getByText("Flag this case for further clinical evaluation").click();
  await page.getByRole("button", { name: "Save review" }).click();
  await expect(page.getByText("Flagged for follow-up").first()).toBeVisible();
  await expect(page.getByText("E2E listening note")).toBeVisible();

  const axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? "")).map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export report" }).click()]);
  const path = await download.path();
  const html = readFileSync(path, "utf8");
  expect(html).toContain("Section A — Automated signal-quality analysis");
  expect(html).toContain("Section C — Clinician review");
  expect(html).toContain("E2E: refer for echocardiogram");
});

test("clinician: silent recording is rejected as a technical issue", async ({ page }) => {
  await login(page, "clinician");
  await newPatientAndImport(page, syntheticWav({ silent: true }));
  await expect(page).toHaveURL(/\/recordings\/\d+/);
  await expect(page.getByText(/Technical recording problem — please record again/)).toBeVisible();
  await expect(page.getByTestId("model-panel")).toContainText("Not analysed (quality)");
});

test("clinician: corrupted file shows re-record guidance", async ({ page }) => {
  await login(page, "clinician");
  await page.getByRole("link", { name: "New Recording", exact: true }).click();
  await page.getByRole("button", { name: "New patient" }).click();
  await page.locator('input[type="file"]').setInputFiles({ name: "broken.wav", mimeType: "audio/wav", buffer: Buffer.from("RIFF0000WAVEnope") });
  await page.getByText(/has consented to this heart-sound recording/).click();
  await page.getByRole("button", { name: "Upload and analyse" }).click();
  await expect(page.getByText("Recording could not be used — please record again")).toBeVisible();
});

test("clinician: microphone capture with fake device", async ({ page }) => {
  await login(page, "clinician");
  await page.getByRole("link", { name: "New Recording", exact: true }).click();
  await page.getByRole("button", { name: "New patient" }).click();
  await page.getByRole("button", { name: "Start recording" }).click();
  await expect(page.getByRole("meter", { name: "Input level" })).toBeVisible();
  await page.waitForTimeout(6500);
  await page.getByRole("button", { name: "Stop recording" }).click();
  await expect(page.getByText(/Microphone · \d+\.\d s · WAV/)).toBeVisible();
  await page.getByText(/has consented to this heart-sound recording/).click();
  await page.getByRole("button", { name: "Upload and analyse" }).click();
  await expect(page).toHaveURL(/\/recordings\/\d+/);
  await expect(page.getByRole("heading", { name: /Recording quality/ })).toBeVisible();
});

test("researcher: no patient access; lab shows not-evaluated state", async ({ page }) => {
  await login(page, "researcher");
  await expect(page).toHaveURL(/\/research$/);
  await expect(page.getByRole("link", { name: "Patient Records" })).toHaveCount(0);
  await expect(page.getByText("No model has been evaluated")).toBeVisible();
  await page.goto("/patients");
  await expect(page).toHaveURL(/\/research$/);
  await page.getByRole("tab", { name: "datasets" }).click();
  await expect(page.getByText(/CirCor DigiScope/)).toBeVisible();
});

test("admin: audit log integrity check", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("button", { name: "Verify integrity" }).click();
  await expect(page.getByText(/Hash chain intact/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "review.create" }).first()).toBeVisible();
});
