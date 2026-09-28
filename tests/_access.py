"""Cloudflare Access tokens for tests: signed here with a throwaway RSA key,
verified against the matching key set the way the app gets it from the team's
certs URL (PyJWKClient, fed locally instead of over the network)."""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from src.auth import AccessVerifier, AuthConfig

TEAM = "https://acme.cloudflareaccess.com"
AUD = "a1b2c3-aud-tag"
CONFIG = AuthConfig("cloudflare-access", TEAM, AUD)
ADA = "7335d417-61da-459d-899c-0a01c76a2f94"
BOB = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNING_KEY = _key()
OTHER_KEY = _key()


class LocalKeys(jwt.PyJWKClient):
    """The team's key set, without the network."""

    def __init__(self, *public_keys):
        super().__init__(f"{TEAM}/cdn-cgi/access/certs")
        self._set = {"keys": [
            {**jwt.algorithms.RSAAlgorithm.to_jwk(k, as_dict=True), "kid": f"k{i}",
             "use": "sig", "alg": "RS256"}
            for i, k in enumerate(public_keys)]}

    def fetch_data(self):
        return self._set


def verifier() -> AccessVerifier:
    return AccessVerifier(CONFIG, LocalKeys(SIGNING_KEY.public_key()))


def token(key=SIGNING_KEY, kid="k0", algorithm="RS256", **overrides) -> str:
    now = int(time.time())
    claims = {"sub": ADA, "email": "ada@example.com",
              "aud": [AUD], "iss": TEAM, "iat": now, "exp": now + 3600, **overrides}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})
