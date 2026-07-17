import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from flex.data import tinyman_lps
from flex.domain.pricing import (
    InvalidLiquidityPoolError,
    PriceQuote,
    PriceSource,
)


def _lp_state(
    *,
    asset_reserve: int = 4_000_000,
    observed_at: datetime | None = None,
):
    return SimpleNamespace(
        id=555,
        token_id=99,
        asset1_id=7,
        asset2_id=0,
        is_algo_pool=True,
        asset1_reserve_micros=asset_reserve,
        asset2_reserve_micros=2_000_000,
        total_tokens_micros=2_000_000,
        token_price_algo=0,
        last_updated_round=123,
        updated=observed_at or datetime(2026, 1, 1, tzinfo=UTC),
    )


def _algo_quote(*, observed_at: datetime | None = None) -> PriceQuote:
    return PriceQuote.from_raw(
        asset_id=0,
        algo=1,
        usd="0.5",
        source=PriceSource.VESTIGE,
        stale_after=timedelta(minutes=5),
        observed_at=observed_at,
    )


def test_tinyman_projection_persists_validated_provenance(monkeypatch) -> None:
    pool_observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    state = _lp_state(observed_at=pool_observed_at)
    lp_updates = []
    persisted = []

    async def asset_details(asset_id: int):
        if asset_id == 7:
            return SimpleNamespace(decimals=6, name="ASSET")
        assert asset_id == 99
        return SimpleNamespace(decimals=6, name="LP")

    monkeypatch.setattr(tinyman_lps, "get_asset_details", asset_details)
    monkeypatch.setattr(
        tinyman_lps,
        "db",
        SimpleNamespace(lp_states=SimpleNamespace(update=lp_updates.append)),
    )
    monkeypatch.setattr(
        tinyman_lps,
        "_upsert_asset_price",
        persisted.append,
    )

    result = asyncio.run(
        tinyman_lps.update_tinyman_algo_lp_state_and_prices(
            state,
            algo_quote=_algo_quote(
                observed_at=pool_observed_at + timedelta(minutes=1),
            ),
        ),
    )

    assert state.token_price_algo == 2.0
    assert lp_updates == [state]
    assert persisted == [result]
    assert result.price_algo == 0.5
    assert result.price_usd == 0.25
    assert result.source == PriceSource.TINYMAN.value
    assert result.observed_at == pool_observed_at


def test_tinyman_projection_rejects_empty_reserve_without_writing(
    monkeypatch,
) -> None:
    state = _lp_state(asset_reserve=0)
    persisted = []
    monkeypatch.setattr(
        tinyman_lps,
        "_upsert_asset_price",
        persisted.append,
    )

    with pytest.raises(InvalidLiquidityPoolError, match="must be positive"):
        asyncio.run(
            tinyman_lps.update_tinyman_algo_lp_state_and_prices(
                state,
                algo_quote=_algo_quote(),
            ),
        )

    assert persisted == []
