"""Read-only LP token classification used to keep price routing fail closed."""

import logging
from typing import Any, TypedDict

from aiocache import cached

from core.db.contracts import get_contracts_by_type
from flex import db

logger = logging.getLogger(__name__)


class LpTokenRegistryError(RuntimeError):
    """The LP registry cannot safely distinguish LP tokens from regular assets."""


class LpTokenDefinition(TypedDict):
    lp_token_id: int
    asset1_id: int
    asset2_id: int
    dex: str


def _extract_stake_token_id(contract: Any) -> int | None:
    """Extract a stake token ID from contract metadata or its cached state."""

    metadata = contract.metadata or {}
    stake_token_id = metadata.get("stake_token_id")
    if stake_token_id is not None:
        return int(stake_token_id)

    initial = metadata.get("cache", {}).get("initial", {})
    raw = initial.get("stakeToken") or initial.get("token")
    if raw is None:
        return None
    if isinstance(raw, dict) and raw.get("type") == "BigNumber" and "hex" in raw:
        return int(raw["hex"], 16)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@cached(ttl=300, namespace="lp_token_defs")
async def get_lp_token_definitions() -> list[LpTokenDefinition]:
    """Build a read-only LP registry without deriving prices from balances."""

    contracts = get_contracts_by_type("farm")
    stake_token_ids: set[int] = set()
    for contract in contracts:
        stake_token_id = _extract_stake_token_id(contract)
        if stake_token_id:
            stake_token_ids.add(stake_token_id)

    if not stake_token_ids:
        logger.warning("No stake tokens found in farm contracts")
        return []

    definitions: dict[int, LpTokenDefinition] = {}
    from_lp_tokens = 0
    from_farming_pools = 0
    from_metadata = 0

    try:
        for token in db.lp_tokens.get_many_by_query(
            {"id": {"$in": list(stake_token_ids)}},
        ):
            definitions[token.id] = LpTokenDefinition(
                lp_token_id=token.id,
                asset1_id=token.asset1_id,
                asset2_id=token.asset2_id,
                dex=token.dex_provider,
            )
            from_lp_tokens += 1
    except Exception as exc:
        raise LpTokenRegistryError("failed to query lp_tokens") from exc

    try:
        for pool in db.farming_pools.get_all():
            stake_token_id = pool.stake_token.id
            if stake_token_id not in stake_token_ids or stake_token_id in definitions:
                continue
            asset1_id = pool.first_token.id
            asset2_id = pool.second_token.id
            if asset1_id == 0:
                asset1_id, asset2_id = asset2_id, asset1_id
            definitions[stake_token_id] = LpTokenDefinition(
                lp_token_id=stake_token_id,
                asset1_id=asset1_id,
                asset2_id=asset2_id,
                dex=pool.dex_name,
            )
            from_farming_pools += 1
    except Exception as exc:
        raise LpTokenRegistryError("failed to query farming_pools") from exc

    for contract in contracts:
        metadata = contract.metadata or {}
        stake_token_id = _extract_stake_token_id(contract)
        if not stake_token_id or stake_token_id in definitions:
            continue
        asset1_id = metadata.get("asset1_id", metadata.get("asset_1_id"))
        asset2_id = metadata.get("asset2_id", metadata.get("asset_2_id", 0))
        dex = metadata.get("dex") or metadata.get("dex_provider")
        if asset1_id is not None and dex:
            definitions[stake_token_id] = LpTokenDefinition(
                lp_token_id=stake_token_id,
                asset1_id=int(asset1_id),
                asset2_id=int(asset2_id),
                dex=str(dex),
            )
            from_metadata += 1

    unresolved_stake_token_ids = stake_token_ids - definitions.keys()
    if unresolved_stake_token_ids:
        raise LpTokenRegistryError(
            f"LP classification is incomplete for farm stake token ids {sorted(unresolved_stake_token_ids)}",
        )

    result = list(definitions.values())
    logger.info(
        "LP token definitions: %s/%s (lp_tokens=%s, farming_pools=%s, metadata=%s, unresolved=%s)",
        len(result),
        len(stake_token_ids),
        from_lp_tokens,
        from_farming_pools,
        from_metadata,
        len(unresolved_stake_token_ids),
    )
    return result
