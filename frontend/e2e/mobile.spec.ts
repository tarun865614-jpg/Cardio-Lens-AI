import { expect, test } from "@playwright/test";
import { login } from "./helpers";

for (const path of ["/", "/patients", "/record", "/reports"]) {
  test(`mobile: ${path} has no horizontal overflow`, async ({ page }) => {
    await login(page, "clinician");
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("mobile: navigation drawer opens and routes", async ({ page }) => {
  await login(page, "clinician");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Patient Records" }).click();
  await expect(page.getByRole("heading", { name: "Patient records" })).toBeVisible();
});

test("mobile: recording analysis page renders", async ({ page }) => {
  await login(page, "clinician");
  await page.getByRole("link", { name: /CL-.*·/ }).first().click();
  await expect(page.getByRole("heading", { name: /Audio analysis/ })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
