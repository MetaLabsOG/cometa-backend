"""Validated pricing value objects and exact LP-token arithmetic."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from math import isfinite

type DecimalInput = Decimal | int | float | str

MAX_DECIMAL_EXPONENT = 300
MAX_SIGNIFICANT_DIGITS = 50
MAX_ASSET_DECIMALS = 19
CALCULATION_PRECISION = 80
PERSISTED_PRICE_PRECISION = 34
MAX_OBSERVATION_CLOCK_SKEW = timedelta(minutes=1)


class PricingError(ValueError):
    """Base class for invalid financial data."""


class InvalidPriceError(PricingError):
    """Raised when a provider returns an unsafe or unusable quote."""


class InvalidLiquidityPoolError(PricingError):
    """Raised when LP reserves or supply violate pricing invariants."""


class PriceUnavailableError(RuntimeError):
    """Raised when no provider or acceptably recent fallback can supply a price."""


class PriceSource(StrEnum):
    VESTIGE = "vestige"
    TINYMAN = "tinyman"
    COINGECKO = "coingecko"
    DATABASE = "database"
    DERIVED_LP = "derived_lp"


def _decimal(value: DecimalInput, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise InvalidPriceError(f"{field} must be numeric, not bool")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidPriceError(f"{field} is not a valid decimal") from exc

    if not parsed.is_finite():
        raise InvalidPriceError(f"{field} must be finite")
    if parsed < 0:
        raise InvalidPriceError(f"{field} must be non-negative")
    if parsed and abs(parsed.adjusted()) > MAX_DECIMAL_EXPONENT:
        raise InvalidPriceError(f"{field} exponent is outside the supported range")
    if len(parsed.as_tuple().digits) > MAX_SIGNIFICANT_DIGITS:
        raise InvalidPriceError(f"{field} has too many significant digits")
    return parsed


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise InvalidPriceError("observed_at must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def validate_observation_timestamp(
    observed_at: datetime,
    *,
    now: datetime | None = None,
) -> datetime:
    """Reject timestamps that could pin a quote ahead of wall-clock time."""

    observed = _utc(observed_at)
    current_time = _utc(now or datetime.now(UTC))
    if observed > current_time + MAX_OBSERVATION_CLOCK_SKEW:
        raise InvalidPriceError("observed_at is too far in the future")
    return observed


def _legacy_float(value: Decimal, *, field: str) -> float:
    converted = float(value)
    if not isfinite(converted) or (value != 0 and converted == 0):
        raise InvalidPriceError(f"{field} cannot be represented by the legacy API")
    return converted


def base_units_to_decimal(
    amount_micros: int,
    *,
    decimals: int,
    field: str = "amount_micros",
) -> Decimal:
    """Convert integer base units without crossing a float boundary."""

    amount = _non_negative_int(amount_micros, field=field)
    precision = _asset_decimals(decimals, field=f"{field}_decimals")
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        return Decimal(amount) / Decimal(10**precision)


def decimal_to_legacy_float(value: DecimalInput, *, field: str) -> float:
    """Convert an exact value only at a legacy float API/storage boundary."""

    return _legacy_float(_decimal(value, field=field), field=field)


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """A validated provider observation before legacy float persistence."""

    asset_id: int
    algo: Decimal
    usd: Decimal
    source: PriceSource
    observed_at: datetime
    stale_after: timedelta
    observed_round: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.asset_id, bool) or not isinstance(self.asset_id, int) or self.asset_id < 0:
            raise InvalidPriceError("asset_id must be a non-negative integer")

        algo = _decimal(self.algo, field="algo")
        usd = _decimal(self.usd, field="usd")
        if algo <= 0 or usd <= 0:
            raise InvalidPriceError("algo and usd quote values must be positive")
        if not isinstance(self.stale_after, timedelta):
            raise InvalidPriceError("stale_after must be a timedelta")
        if self.stale_after <= timedelta(0):
            raise InvalidPriceError("stale_after must be positive")
        if self.observed_round is not None and (
            isinstance(self.observed_round, bool) or not isinstance(self.observed_round, int) or self.observed_round < 0
        ):
            raise InvalidPriceError("observed_round must be a non-negative integer")
        try:
            source = PriceSource(self.source)
        except (TypeError, ValueError) as exc:
            raise InvalidPriceError("source is not a supported price provider") from exc

        object.__setattr__(self, "algo", algo)
        object.__setattr__(self, "usd", usd)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "observed_at", _utc(self.observed_at))

    @classmethod
    def from_raw(
        cls,
        *,
        asset_id: int,
        algo: DecimalInput,
        usd: DecimalInput,
        source: PriceSource,
        stale_after: timedelta,
        observed_round: int | None = None,
        observed_at: datetime | None = None,
    ) -> "PriceQuote":
        return cls(
            asset_id=asset_id,
            algo=_decimal(algo, field="algo"),
            usd=_decimal(usd, field="usd"),
            source=source,
            observed_at=observed_at or datetime.now(UTC),
            stale_after=stale_after,
            observed_round=observed_round,
        )

    def is_stale(self, *, now: datetime | None = None) -> bool:
        current_time = _utc(now or datetime.now(UTC))
        if self.observed_at > current_time + MAX_OBSERVATION_CLOCK_SKEW:
            return True
        return current_time - self.observed_at >= self.stale_after

    def to_legacy_floats(self) -> tuple[float, float]:
        return (
            _legacy_float(self.algo, field="algo"),
            _legacy_float(self.usd, field="usd"),
        )


def is_observation_stale(
    observed_at: datetime,
    *,
    fresh_for: timedelta,
    now: datetime | None = None,
) -> bool:
    if fresh_for <= timedelta(0):
        raise ValueError("fresh_for must be positive")
    current_time = _utc(now or datetime.now(UTC))
    observed = _utc(observed_at)
    if observed > current_time + MAX_OBSERVATION_CLOCK_SKEW:
        return True
    return current_time - observed >= fresh_for


def _non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidLiquidityPoolError(f"{field} must be a non-negative integer")
    return value


def _asset_decimals(value: int, *, field: str) -> int:
    decimals = _non_negative_int(value, field=field)
    if decimals > MAX_ASSET_DECIMALS:
        raise InvalidLiquidityPoolError(f"{field} exceeds Algorand asset precision")
    return decimals


def calculate_lp_token_price_algo(
    *,
    asset1_price_algo: DecimalInput,
    asset1_reserve_micros: int,
    asset1_decimals: int,
    total_lp_supply_micros: int,
    pool_lp_balance_micros: int,
    lp_token_decimals: int,
) -> Decimal:
    """Calculate one LP token's ALGO value without crossing a float boundary."""

    price = _decimal(asset1_price_algo, field="asset1_price_algo")
    if price <= 0:
        raise InvalidLiquidityPoolError("asset1_price_algo must be positive")

    reserve_micros = _non_negative_int(asset1_reserve_micros, field="asset1_reserve_micros")
    total_supply_micros = _non_negative_int(total_lp_supply_micros, field="total_lp_supply_micros")
    pool_balance_micros = _non_negative_int(pool_lp_balance_micros, field="pool_lp_balance_micros")
    asset_decimals = _asset_decimals(asset1_decimals, field="asset1_decimals")
    lp_decimals = _asset_decimals(lp_token_decimals, field="lp_token_decimals")

    if reserve_micros == 0:
        raise InvalidLiquidityPoolError("asset1 reserve must be positive")
    if pool_balance_micros >= total_supply_micros:
        raise InvalidLiquidityPoolError("circulating LP supply must be positive")

    return calculate_lp_token_price_from_issued_supply(
        asset1_price_algo=price,
        asset1_reserve_micros=reserve_micros,
        asset1_decimals=asset_decimals,
        issued_lp_supply_micros=total_supply_micros - pool_balance_micros,
        lp_token_decimals=lp_decimals,
    )


def calculate_lp_token_price_from_issued_supply(
    *,
    asset1_price_algo: DecimalInput,
    asset1_reserve_micros: int,
    asset1_decimals: int,
    issued_lp_supply_micros: int,
    lp_token_decimals: int,
) -> Decimal:
    """Calculate LP price from an already-derived issued token supply."""

    price = _decimal(asset1_price_algo, field="asset1_price_algo")
    if price <= 0:
        raise InvalidLiquidityPoolError("asset1_price_algo must be positive")
    reserve_micros = _non_negative_int(
        asset1_reserve_micros,
        field="asset1_reserve_micros",
    )
    issued_micros = _non_negative_int(
        issued_lp_supply_micros,
        field="issued_lp_supply_micros",
    )
    asset_decimals = _asset_decimals(
        asset1_decimals,
        field="asset1_decimals",
    )
    lp_decimals = _asset_decimals(
        lp_token_decimals,
        field="lp_token_decimals",
    )
    if reserve_micros == 0:
        raise InvalidLiquidityPoolError("asset1 reserve must be positive")
    if issued_micros == 0:
        raise InvalidLiquidityPoolError("issued LP supply must be positive")

    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        reserve = base_units_to_decimal(
            reserve_micros,
            decimals=asset_decimals,
            field="asset1_reserve_micros",
        )
        issued_supply = base_units_to_decimal(
            issued_micros,
            decimals=lp_decimals,
            field="issued_lp_supply_micros",
        )
        calculated = price * reserve * Decimal(2) / issued_supply
    if not calculated.is_finite() or calculated <= 0:
        raise InvalidLiquidityPoolError("calculated LP price is invalid")
    with localcontext() as context:
        context.prec = PERSISTED_PRICE_PRECISION
        return +calculated
