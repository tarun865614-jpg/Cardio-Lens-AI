"""Minimal OIDC identity provider for end-to-end tests only. NEVER use outside tests.

Implements discovery, JWKS, an /authorize endpoint that immediately redirects
back with a code (simulating a user who signed in with MFA), and a /token
endpoint that verifies PKCE and issues an RS256 access token.

Query parameters on /authorize let a test pick the identity:
  login_hint=<email>, x_roles=<comma list>, x_amr=<comma list>
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8767
ISS = f"http://127.0.0.1:{PORT}"
AUD = "api://cardiolens-e2e"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
JWK.update(kid="e2e", use="sig", alg="RS256")
CODES: dict[str, dict] = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: dict | None = None, headers: dict | None = None):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body is not None:
            data = json.dumps(body).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.end_headers()

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/.well-known/openid-configuration":
            return self._send(200, {"issuer": ISS, "authorization_endpoint": f"{ISS}/authorize", "token_endpoint": f"{ISS}/token",
                                    "jwks_uri": f"{ISS}/jwks", "end_session_endpoint": f"{ISS}/logout"})
        if u.path == "/jwks":
            return self._send(200, {"keys": [JWK]})
        if u.path == "/authorize":
            if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
                return self._send(400, {"error": "pkce_required"})
            code = secrets.token_urlsafe(16)
            CODES[code] = {**q, "email": q.get("login_hint", "clinician@demo.cardiolens.local")}
            loc = q["redirect_uri"] + "?" + urlencode({"code": code, "state": q["state"]})
            return self._send(302, headers={"Location": loc})
        if u.path == "/logout":
            return self._send(302, headers={"Location": q.get("post_logout_redirect_uri", "/")})
        self._send(404, {"error": "not_found"})

    def do_POST(self):
        if urlparse(self.path).path != "/token":
            return self._send(404, {"error": "not_found"})
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
        req = CODES.pop(form.get("code", ""), None)
        if req is None:
            return self._send(400, {"error": "invalid_grant"})
        challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
        if challenge != req["code_challenge"] or form.get("redirect_uri") != req["redirect_uri"]:
            return self._send(400, {"error": "invalid_grant", "error_description": "PKCE verification failed"})
        now = int(time.time())
        email = req["email"]
        claims = {"iss": ISS, "aud": AUD, "sub": "sub-" + email, "iat": now, "exp": now + 600, "email": email,
                  "name": email.split("@")[0], "roles": req.get("x_roles", "clinician").split(","),
                  "amr": req.get("x_amr", "pwd,mfa").split(",")}
        token = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "e2e"})
        self._send(200, {"access_token": token, "token_type": "Bearer", "expires_in": 600})


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
