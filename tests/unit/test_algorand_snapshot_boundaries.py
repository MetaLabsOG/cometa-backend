import asyncio

import pytest

from flex.blockchain import info
from flex.domain.algorand import MAX_ALGORAND_UINT


def _response(*, assets: list[dict], amount: object = 10, round_number: object = 20) -> dict:
    return {
        "account": {
            "assets": assets,
            "amount": amount,
        },
        "current-round": round_number,
    }


def _install_response(monkeypatch, response: dict) -> None:
    async def run_sync(func, *args):
        del func, args
        return response

    monkeypatch.setattr(info, "_run_sync", run_sync)


def test_account_snapshot_preserves_full_uint64_domain(monkeypatch) -> None:
    _install_response(
        monkeypatch,
        _response(
            assets=[{"asset-id": MAX_ALGORAND_UINT, "amount": MAX_ALGORAND_UINT}],
            amount=MAX_ALGORAND_UINT,
            round_number=MAX_ALGORAND_UINT,
        ),
    )

    snapshot = asyncio.run(
        info.get_address_asset_snapshot("ACCOUNT", include_algo=True),
    )

    assert snapshot.balances == {
        0: MAX_ALGORAND_UINT,
        MAX_ALGORAND_UINT: MAX_ALGORAND_UINT,
    }
    assert snapshot.observed_round == MAX_ALGORAND_UINT


@pytest.mark.parametrize(
    "assets",
    [
        [{"asset-id": True, "amount": 1}],
        [{"asset-id": 0, "amount": 1}],
        [{"asset-id": 1, "amount": -1}],
        [{"asset-id": 1, "amount": MAX_ALGORAND_UINT + 1}],
        [
            {"asset-id": 1, "amount": 1},
            {"asset-id": 1, "amount": 2},
        ],
    ],
)
def test_account_snapshot_rejects_malformed_or_duplicate_holdings(
    monkeypatch,
    assets: list[dict],
) -> None:
    _install_response(monkeypatch, _response(assets=assets))

    with pytest.raises(RuntimeError):
        asyncio.run(
            info.get_address_asset_snapshot("ACCOUNT", include_algo=True),
        )


@pytest.mark.parametrize(
    ("amount", "round_number"),
    [
        (True, 1),
        (-1, 1),
        (MAX_ALGORAND_UINT + 1, 1),
        (1, True),
        (1, -1),
        (1, MAX_ALGORAND_UINT + 1),
    ],
)
def test_account_snapshot_rejects_invalid_algo_or_round(
    monkeypatch,
    amount: object,
    round_number: object,
) -> None:
    _install_response(
        monkeypatch,
        _response(
            assets=[],
            amount=amount,
            round_number=round_number,
        ),
    )

    with pytest.raises(RuntimeError):
        asyncio.run(
            info.get_address_asset_snapshot("ACCOUNT", include_algo=True),
        )
