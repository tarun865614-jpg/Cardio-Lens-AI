// OpenID Connect sign-in for a public SPA: Authorization Code flow with PKCE (no client secret in the browser).
// The IdP-issued access token is sent to the API, which verifies it against the IdP's keys.

export interface AuthConfig {
  mode: "local" | "oidc";
  issuer?: string;
  client_id?: string;
  audience?: string;
  scopes?: string;
}

interface Discovery {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
}

const PENDING = "cl.oidc.pending";
export const CALLBACK_PATH = "/auth/callback";

function b64url(bytes: Uint8Array): string {
  let s = "";
  bytes.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomString(len = 32): string {
  const a = new Uint8Array(len);
  crypto.getRandomValues(a);
  return b64url(a);
}

export async function pkceChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return b64url(new Uint8Array(digest));
}

export async function discover(issuer: string): Promise<Discovery> {
  const r = await fetch(issuer.replace(/\/$/, "") + "/.well-known/openid-configuration");
  if (!r.ok) throw new Error("Could not reach the identity provider");
  return r.json();
}

export function redirectUri(): string {
  return window.location.origin + CALLBACK_PATH;
}

export async function buildAuthorizeUrl(cfg: AuthConfig, d: Discovery, verifier: string, state: string, nonce: string): Promise<string> {
  const p = new URLSearchParams({
    response_type: "code",
    client_id: cfg.client_id!,
    redirect_uri: redirectUri(),
    scope: cfg.scopes ?? "openid profile email",
    state,
    nonce,
    code_challenge: await pkceChallenge(verifier),
    code_challenge_method: "S256",
  });
  if (cfg.audience) p.set("audience", cfg.audience); // used by Auth0-style IdPs; ignored by others
  return `${d.authorization_endpoint}?${p}`;
}

export async function startLogin(cfg: AuthConfig, returnTo = "/"): Promise<void> {
  const d = await discover(cfg.issuer!);
  const verifier = randomString(48);
  const state = randomString(16);
  const nonce = randomString(16);
  sessionStorage.setItem(PENDING, JSON.stringify({ verifier, state, returnTo }));
  window.location.assign(await buildAuthorizeUrl(cfg, d, verifier, state, nonce));
}

/** Completes the redirect: validates state, exchanges the code, returns the access token and where to go next. */
export async function completeLogin(cfg: AuthConfig, search: string): Promise<{ accessToken: string; returnTo: string }> {
  const params = new URLSearchParams(search);
  const raw = sessionStorage.getItem(PENDING);
  sessionStorage.removeItem(PENDING);
  if (params.get("error")) throw new Error(params.get("error_description") ?? params.get("error")!);
  if (!raw) throw new Error("Sign-in session expired — please try again");
  const pending = JSON.parse(raw) as { verifier: string; state: string; returnTo: string };
  if (!params.get("state") || params.get("state") !== pending.state) throw new Error("Sign-in state mismatch — please try again");
  const code = params.get("code");
  if (!code) throw new Error("No authorization code returned");
  const d = await discover(cfg.issuer!);
  const r = await fetch(d.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(),
      client_id: cfg.client_id!,
      code_verifier: pending.verifier,
    }),
  });
  if (!r.ok) throw new Error("Token exchange with the identity provider failed");
  const body = (await r.json()) as { access_token?: string };
  if (!body.access_token) throw new Error("Identity provider returned no access token");
  return { accessToken: body.access_token, returnTo: pending.returnTo?.startsWith("/") ? pending.returnTo : "/" };
}

export async function logoutUrl(cfg: AuthConfig): Promise<string | null> {
  try {
    const d = await discover(cfg.issuer!);
    if (!d.end_session_endpoint) return null;
    return `${d.end_session_endpoint}?${new URLSearchParams({ client_id: cfg.client_id!, post_logout_redirect_uri: window.location.origin + "/login" })}`;
  } catch {
    return null;
  }
}
