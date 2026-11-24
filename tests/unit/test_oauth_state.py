import pytest

from modules.identity.oauth import OAuthError, sign_state, verify_state

SECRET = "test-secret-value"


def test_state_round_trip_for_the_expected_provider() -> None:
    state = sign_state("google", SECRET, now=1000)

    verify_state(state, "google", SECRET, now=1001)


def test_state_for_another_provider_is_rejected() -> None:
    state = sign_state("google", SECRET, now=1000)

    with pytest.raises(OAuthError, match="another provider"):
        verify_state(state, "github", SECRET, now=1001)


def test_tampered_state_is_rejected() -> None:
    state = sign_state("github", SECRET, now=1000)
    tampered = state[:-1] + ("0" if state[-1] != "0" else "1")

    with pytest.raises(OAuthError, match="signature"):
        verify_state(tampered, "github", SECRET, now=1001)


def test_expired_state_is_rejected() -> None:
    state = sign_state("github", SECRET, now=1000)

    with pytest.raises(OAuthError, match="expired"):
        verify_state(state, "github", SECRET, now=1000 + 601)


def test_state_signed_with_a_different_secret_is_rejected() -> None:
    state = sign_state("google", "other-secret", now=1000)

    with pytest.raises(OAuthError):
        verify_state(state, "google", SECRET, now=1001)


def test_state_carries_the_return_origin() -> None:
    """The callback must know which frontend origin started the flow."""
    state = sign_state("google", SECRET, origin="http://localhost:3000", now=1000)

    payload = verify_state(state, "google", SECRET, now=1001)

    assert payload["o"] == "http://localhost:3000"
