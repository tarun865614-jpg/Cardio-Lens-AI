import { expect, test } from "@playwright/test";

// Runs against a second API instance in OIDC mode, backed by e2e/mock_idp.py.

test("SSO: Authorization Code + PKCE sign-in links the clinician and opens the dashboard", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByLabel("Password")).toHaveCount(0); // password form disabled in SSO mode
  await page.getByRole("button", { name: /Sign in with your organisation/ }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Dr. Demo Clinician")).toBeVisible();
});

test("SSO: sign-in without MFA is refused by the API", async ({ page }) => {
  await page.goto("/login");
  // Ask the mock IdP for a password-only session.
  await page.route("**/authorize?*", async (route) => {
    const u = new URL(route.request().url());
    u.searchParams.set("x_amr", "pwd");
    const resp = await route.fetch({ url: u.toString(), maxRedirects: 0 });
    await route.fulfill({ response: resp });
  });
  await page.getByRole("button", { name: /Sign in with your organisation/ }).click();
  await expect(page.getByText("Sign-in failed")).toBeVisible();
  await expect(page.getByText(/Multi-factor authentication is required/)).toBeVisible();
});

test("SSO: a forged state parameter is rejected", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(() => sessionStorage.setItem("cl.oidc.pending", JSON.stringify({ verifier: "v", state: "real", returnTo: "/" })));
  await page.goto("/auth/callback?code=whatever&state=forged");
  await expect(page.getByText(/state mismatch/)).toBeVisible();
});
