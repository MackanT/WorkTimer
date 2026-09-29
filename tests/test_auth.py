"""Sign-in (v6 Phase 6): the Cloudflare Access token checks in src/auth.py
(tokens from tests/_access.py)."""

import time

import pytest

from _access import ADA, AUD, CONFIG, OTHER_KEY, verifier as _verifier
from _access import token as _token
from src.auth import AuthConfig, AuthError, Identity


@pytest.fixture
def verifier():
    return _verifier()


def test_a_valid_token_names_the_user(verifier):
    assert verifier.verify(_token()) == Identity(ADA, "ada@example.com")


def test_the_token_comes_from_the_header_or_the_cookie(verifier):
    token = _token()
    assert verifier.identity({"Cf-Access-Jwt-Assertion": token}, {}).email == "ada@example.com"
    assert verifier.identity({}, {"CF_Authorization": token}).email == "ada@example.com"
    with pytest.raises(AuthError, match="no Access token"):
        verifier.identity({}, {})


@pytest.mark.parametrize("claims, error", [
    ({"aud": ["another-app"]}, "audience"),
    ({"iss": "https://evil.cloudflareaccess.com"}, "issuer"),
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"sub": ""}, "names no user"),  # a service token
    ({"sub": None}, "sub"),
])
def test_a_token_for_something_else_is_refused(verifier, claims, error):
    with pytest.raises(AuthError, match=f"(?i){error}"):
        verifier.verify(_token(**claims))


def test_a_token_signed_with_another_key_is_refused(verifier):
    with pytest.raises(AuthError, match="Signature"):
        verifier.verify(_token(key=OTHER_KEY))


def test_an_unknown_key_id_is_refused(verifier):
    with pytest.raises(AuthError):
        verifier.verify(_token(kid="not-ours"))


def test_unsigned_and_symmetric_tokens_are_refused(verifier):
    """No 'alg: none', and no HS256 signed with the public key as a secret."""
    with pytest.raises(AuthError):
        verifier.verify(_token(key=None, algorithm="none"))
    with pytest.raises(AuthError):
        verifier.verify(_token(key="a-shared-secret-of-at-least-32-bytes!", algorithm="HS256"))


def test_config_defaults_to_single_user(monkeypatch):
    monkeypatch.delenv("WORKTIMER_AUTH", raising=False)
    assert AuthConfig.from_env() == AuthConfig()
    assert not AuthConfig.from_env().multi_user


def test_cloudflare_access_needs_its_team_and_audience(monkeypatch):
    monkeypatch.delenv("WORKTIMER_OWNER_EMAIL", raising=False)
    monkeypatch.setenv("WORKTIMER_AUTH", "cloudflare-access")
    monkeypatch.delenv("CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.setenv("CF_ACCESS_AUD", AUD)
    with pytest.raises(AuthError, match="CF_ACCESS_TEAM_DOMAIN"):
        AuthConfig.from_env()
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "acme.cloudflareaccess.com/")
    assert AuthConfig.from_env() == CONFIG
    monkeypatch.setenv("WORKTIMER_AUTH", "none")
    with pytest.raises(AuthError, match="must be one of"):
        AuthConfig.from_env()


def test_the_owner_is_matched_by_email_whatever_its_case(monkeypatch):
    monkeypatch.setenv("WORKTIMER_AUTH", "cloudflare-access")
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "acme.cloudflareaccess.com")
    monkeypatch.setenv("CF_ACCESS_AUD", AUD)
    monkeypatch.setenv("WORKTIMER_OWNER_EMAIL", " Ada@Example.com ")

    config = AuthConfig.from_env()
    assert config.owner_email == "ada@example.com"
    assert config.is_owner(Identity(ADA, "ADA@example.COM"))
    assert not config.is_owner(Identity(ADA, "bob@example.com"))
    assert not config.is_owner(Identity(ADA, None))
    monkeypatch.delenv("WORKTIMER_OWNER_EMAIL")
    assert not AuthConfig.from_env().is_owner(Identity(ADA, "ada@example.com"))


def test_the_header_and_the_cookie_must_name_the_same_user(verifier):
    ada, bob = _token(), _token(sub="0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")

    assert verifier.identity({"Cf-Access-Jwt-Assertion": ada}, {"CF_Authorization": ada}).sub == ADA
    with pytest.raises(AuthError, match="different users"):
        verifier.identity({"Cf-Access-Jwt-Assertion": bob}, {"CF_Authorization": ada})


def test_the_owner_email_is_never_matched_through_unicode_folding():
    config = AuthConfig("cloudflare-access", "https://t.cloudflareaccess.com", AUD, "mackan@example.com")

    assert config.is_owner(Identity(ADA, "Mackan@Example.com"))
    assert not config.is_owner(Identity(ADA, "macKan@example.com"))  # a Kelvin sign
