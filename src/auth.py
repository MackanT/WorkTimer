"""Who is signed in (v6 Phase 6, docs/v6_plan.md §2).

Single-user, the default: nobody signs in; everything runs as user 1,
'local'. Hosted (``WORKTIMER_AUTH=cloudflare-access``): the app sits behind a
Cloudflare Access application, which lets a request through only after its
login and signs it with a JWT (header ``Cf-Access-Jwt-Assertion``, cookie
``CF_Authorization``). The app verifies that token itself — signature against
the team's published keys, the application's audience tag, issuer, expiry —
and takes the user from its subject. No valid token, no user: nothing reached
through the compose network is trusted on its word.
"""

import os
from dataclasses import dataclass

import jwt

ACCESS_HEADER = "Cf-Access-Jwt-Assertion"
ACCESS_COOKIE = "CF_Authorization"
MODES = ("local", "cloudflare-access")


class AuthError(Exception):
    """No signed-in user: a missing, invalid or expired token, or bad config."""


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class AuthConfig:
    mode: str = "local"
    team_domain: str | None = None  # https://<team>.cloudflareaccess.com
    audience: str | None = None  # the Access application's AUD tag

    @property
    def multi_user(self) -> bool:
        return self.mode == "cloudflare-access"

    @classmethod
    def from_env(cls) -> "AuthConfig":
        mode = (os.getenv("WORKTIMER_AUTH") or "local").strip().lower()
        if mode not in MODES:
            raise AuthError(f"WORKTIMER_AUTH must be one of {', '.join(MODES)} — not {mode!r}")
        if mode == "local":
            return cls()
        team = (os.getenv("CF_ACCESS_TEAM_DOMAIN") or "").strip().rstrip("/")
        audience = (os.getenv("CF_ACCESS_AUD") or "").strip()
        if not team or not audience:
            raise AuthError("WORKTIMER_AUTH=cloudflare-access needs CF_ACCESS_TEAM_DOMAIN "
                            "(https://<team>.cloudflareaccess.com) and CF_ACCESS_AUD "
                            "(the Access application's audience tag)")
        if not team.startswith("https://"):
            team = "https://" + team.removeprefix("http://")
        return cls(mode, team, audience)


class AccessVerifier:
    """Verifies Cloudflare Access tokens. The team's signing keys are fetched
    once and cached (Access rotates them; an unknown key id refetches)."""

    LEEWAY_SECONDS = 60  # clock skew between Cloudflare and this server

    def __init__(self, config: AuthConfig, jwks_client: jwt.PyJWKClient | None = None):
        if not config.multi_user:
            raise AuthError("Access tokens are verified only in cloudflare-access mode")
        self.config = config
        self._keys = jwks_client or jwt.PyJWKClient(
            f"{config.team_domain}/cdn-cgi/access/certs", cache_keys=True, lifespan=3600)

    def verify(self, token: str) -> Identity:
        """The identity in a valid token; AuthError otherwise. Blocking (a
        key fetch may go over the network) — call it off the event loop."""
        try:
            key = self._keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"], audience=self.config.audience,
                issuer=self.config.team_domain, leeway=self.LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except jwt.PyJWTError as e:
            raise AuthError(f"invalid Access token: {e}") from e
        sub = str(claims.get("sub") or "").strip()
        if not sub:  # a service token: a machine, not a user
            raise AuthError("the Access token names no user")
        return Identity(sub, claims.get("email") or None, claims.get("name") or None)

    def identity(self, headers, cookies) -> Identity:
        """The identity of a request, from its header or cookie."""
        token = headers.get(ACCESS_HEADER) or cookies.get(ACCESS_COOKIE)
        if not token:
            raise AuthError("no Access token — is the app reached through Cloudflare Access?")
        return self.verify(token)


_config: AuthConfig | None = None
_verifier: AccessVerifier | None = None


def auth_config() -> AuthConfig:
    """This process's sign-in mode, read from the environment once."""
    global _config
    if _config is None:
        _config = AuthConfig.from_env()
    return _config


def request_identity(request) -> Identity | None:
    """Who a page request comes from: None in single-user mode (nobody signs
    in), else the verified Access identity — AuthError when there is none.
    Blocking; call it off the event loop."""
    global _verifier
    config = auth_config()
    if not config.multi_user:
        return None
    if request is None:
        raise AuthError("no request to take the sign-in from")
    if _verifier is None:
        _verifier = AccessVerifier(config)
    return _verifier.identity(request.headers, request.cookies)
