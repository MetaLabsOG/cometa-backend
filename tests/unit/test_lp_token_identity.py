from types import SimpleNamespace

import pytest

from flex.data import lp_tokens
from flex.db.model.blockchain import LpToken


def _token(*, address: str = "POOL") -> LpToken:
    return LpToken(
        id=99,
        pool_id=123,
        asset1_id=7,
        asset2_id=0,
        address=address,
        dex_provider="tinyman",
    )


def test_lp_token_registration_returns_matching_atomic_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _token()
    manager = SimpleNamespace(get_or_create=lambda item: item)
    monkeypatch.setattr(
        lp_tokens,
        "db",
        SimpleNamespace(lp_tokens=manager),
    )

    assert lp_tokens.persist_lp_token(candidate) is candidate


def test_lp_token_registration_fails_closed_on_identity_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _token()
    manager = SimpleNamespace(
        get_or_create=lambda item: _token(address="OTHER_POOL"),
    )
    monkeypatch.setattr(
        lp_tokens,
        "db",
        SimpleNamespace(lp_tokens=manager),
    )

    with pytest.raises(
        lp_tokens.LpTokenIdentityConflictError,
        match="different pool metadata",
    ):
        lp_tokens.persist_lp_token(candidate)
