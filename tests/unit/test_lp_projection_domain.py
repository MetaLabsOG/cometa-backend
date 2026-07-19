from flex.domain.lp_projection import lp_balance_delta


def test_algo_pool_fee_debits_the_economic_algo_reserve() -> None:
    delta = lp_balance_delta(
        token_id=99,
        asset1_id=7,
        asset2_id=0,
        event_asset_id=0,
        event_pool_delta_micros=-1_000,
    )

    assert delta.field == "asset2_reserve_micros"
    assert delta.amount == -1_000


def test_token_token_pool_fee_debits_the_operational_algo_balance() -> None:
    delta = lp_balance_delta(
        token_id=99,
        asset1_id=7,
        asset2_id=8,
        event_asset_id=0,
        event_pool_delta_micros=-1_000,
    )

    assert delta.field == "operational_algo_balance_micros"
    assert delta.amount == -1_000
