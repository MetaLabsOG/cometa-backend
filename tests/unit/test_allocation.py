from decimal import Decimal

import pytest

from flex.domain.allocation import AllocationError, allocate_proportionally


def test_allocation_never_exceeds_the_integer_budget() -> None:
    allocations = allocate_proportionally(
        2,
        {
            "ADDRESS-B": 1,
            "ADDRESS-A": 1,
        },
    )

    assert allocations == {"ADDRESS-A": 1, "ADDRESS-B": 1}
    assert sum(allocations.values()) == 2


def test_allocation_uses_deterministic_largest_remainders() -> None:
    allocations = allocate_proportionally(
        10,
        {
            "ADDRESS-C": Decimal("1"),
            "ADDRESS-B": Decimal("1"),
            "ADDRESS-A": Decimal("1"),
        },
    )

    assert allocations == {
        "ADDRESS-A": 4,
        "ADDRESS-B": 3,
        "ADDRESS-C": 3,
    }


def test_allocation_is_independent_of_input_order() -> None:
    forwards = allocate_proportionally(
        100,
        {"ADDRESS-A": 0.1, "ADDRESS-B": 0.2},
    )
    backwards = allocate_proportionally(
        100,
        {"ADDRESS-B": 0.2, "ADDRESS-A": 0.1},
    )

    assert forwards == backwards == {"ADDRESS-A": 33, "ADDRESS-B": 67}


@pytest.mark.parametrize("total_micros", [True, 0, -1, 1.5])
def test_allocation_rejects_invalid_budgets(total_micros: object) -> None:
    with pytest.raises(AllocationError):
        allocate_proportionally(total_micros, {"ADDRESS": 1})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "shares",
    [
        {},
        {"": 1},
        {"ADDRESS": True},
        {"ADDRESS": 0},
        {"ADDRESS": -1},
        {"ADDRESS": float("nan")},
        {"ADDRESS": float("inf")},
        {"ADDRESS": "not-a-number"},
        {"ADDRESS": Decimal("1e-301")},
    ],
)
def test_allocation_rejects_invalid_shares(shares: dict[str, object]) -> None:
    with pytest.raises(AllocationError):
        allocate_proportionally(100, shares)  # type: ignore[arg-type]
