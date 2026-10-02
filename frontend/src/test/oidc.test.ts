import { afterEach, describe, expect, it, vi } from "vitest";
import { buildAuthorizeUrl, completeLogin, pkceChallenge, type AuthConfig } from "../lib/oidc";

const cfg: AuthConfig = { mode: "oidc", issuer: "https://idp.example.org", client_id: "spa", audience: "api://cl", scopes: "openid email" };
const disco = {
  issuer: "https://idp.example.org",
  authorization_endpoint: "https://idp.example.org/authorize",
  token_endpoint: "https://idp.example.org/token",
};

function mockFetch(tokenResponse: unknown, ok = true) {
  const f = vi.fn(async (url: string) => {
    if (url.endsWith("/.well-known/openid-configuration")) return { ok: true, json: async () => disco };
    return { ok, json: async () => tokenResponse };
  });
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("PKCE", () => {
  it("is base64url(SHA-256(verifier)) without padding", async () => {
    // SHA-256("abc") = ba7816bf8f01cfea… (FIPS 180-2 test vector), base64url-encoded.
    expect(await pkceChallenge("abc")).toBe("ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0");
  });

  it("builds an authorize URL with S256 and no client secret", async () => {
    const url = new URL(await buildAuthorizeUrl(cfg, disco, "verifier-123", "st", "nn"));
    expect(url.origin + url.pathname).toBe("https://idp.example.org/authorize");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("state")).toBe("st");
    expect(url.searchParams.get("audience")).toBe("api://cl");
    expect(url.searchParams.get("redirect_uri")).toBe(window.location.origin + "/auth/callback");
    expect(url.searchParams.has("client_secret")).toBe(false);
  });
});

describe("callback", () => {
  const pending = (state = "s1") => sessionStorage.setItem("cl.oidc.pending", JSON.stringify({ verifier: "v", state, returnTo: "/patients" }));

  it("exchanges the code with the verifier and returns the access token", async () => {
    pending();
    const f = mockFetch({ access_token: "at-1" });
    const r = await completeLogin(cfg, "?code=c1&state=s1");
    expect(r).toEqual({ accessToken: "at-1", returnTo: "/patients" });
    const [, init] = f.mock.calls[1] as unknown as [string, { body: URLSearchParams }];
    expect(init.body.get("code_verifier")).toBe("v");
    expect(init.body.get("grant_type")).toBe("authorization_code");
    expect(sessionStorage.getItem("cl.oidc.pending")).toBeNull(); // single use
  });

  it("rejects a state mismatch (CSRF)", async () => {
    pending("expected");
    mockFetch({ access_token: "x" });
    await expect(completeLogin(cfg, "?code=c1&state=forged")).rejects.toThrow(/state mismatch/);
  });

  it("surfaces IdP errors and missing sessions", async () => {
    pending();
    await expect(completeLogin(cfg, "?error=access_denied&error_description=MFA+required")).rejects.toThrow("MFA required");
    await expect(completeLogin(cfg, "?code=c&state=s1")).rejects.toThrow(/expired/);
  });

  it("fails when the token exchange fails", async () => {
    pending();
    mockFetch({}, false);
    await expect(completeLogin(cfg, "?code=c1&state=s1")).rejects.toThrow(/Token exchange/);
  });

  it("never redirects off-site after login", async () => {
    sessionStorage.setItem("cl.oidc.pending", JSON.stringify({ verifier: "v", state: "s", returnTo: "https://evil.example" }));
    mockFetch({ access_token: "a" });
    expect((await completeLogin(cfg, "?code=c&state=s")).returnTo).toBe("/");
  });
});
