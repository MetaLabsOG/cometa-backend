"""Pure Algorand transaction flattening with deterministic event identifiers."""

from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
from typing import Any

ASSET_TRANSFER_TX = "asset-transfer-transaction"
APPLICATION_CALL_TX = "application-transaction"
PAYMENT_TX = "payment-transaction"
INNER_TRANSACTIONS = "inner-txns"
PROJECTION_SEPARATOR = "@"

type Transaction = dict[str, Any]
type TransactionView = Mapping[str, Any]


class TransactionShapeError(ValueError):
    """Raised when an indexer payload cannot produce stable event IDs."""


def _root_id(transaction: TransactionView) -> str:
    transaction_id = transaction.get("id")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise TransactionShapeError("top-level transaction must have a non-empty id")
    return transaction_id


def _inner_transactions(transaction: TransactionView) -> Sequence[TransactionView]:
    inner = transaction.get(INNER_TRANSACTIONS)
    if inner is None:
        return ()
    if not isinstance(inner, list):
        raise TransactionShapeError("inner-txns must be a list")
    if not all(isinstance(item, Mapping) for item in inner):
        raise TransactionShapeError("every inner transaction must be an object")
    return inner


def _walk_inner(
    transaction: TransactionView,
    *,
    root_id: str,
    path: tuple[int, ...] = (),
) -> Iterator[tuple[TransactionView, str]]:
    for index, inner in enumerate(_inner_transactions(transaction)):
        inner_path = (*path, index)
        event_id = "#".join((root_id, *(str(part) for part in inner_path)))
        yield inner, event_id
        yield from _walk_inner(inner, root_id=root_id, path=inner_path)


def _copy_with_id(transaction: TransactionView, event_id: str) -> Transaction:
    copied = deepcopy(dict(transaction))
    copied["id"] = event_id
    return copied


def event_id_aliases(event_id: str) -> tuple[str, ...]:
    """Return the canonical ID and any legacy parent-ID alias.

    Older ingestion code stored every inner event under its root transaction ID.
    Treating that root as an alias prevents a post-migration replay from applying
    the same financial event again.
    """

    if not isinstance(event_id, str) or not event_id:
        raise TransactionShapeError("event id must be a non-empty string")
    chain_event_id, projection_separator, _ = event_id.partition(
        PROJECTION_SEPARATOR,
    )
    root_id, path_separator, _ = chain_event_id.partition("#")
    aliases = [event_id]
    if projection_separator:
        aliases.append(chain_event_id)
    if path_separator and root_id not in aliases:
        aliases.append(root_id)
    return tuple(aliases)


def projection_event_id(event_id: str, scope: str) -> str:
    """Create a stable ID for one event projected into a scoped aggregate."""

    event_id_aliases(event_id)
    if not isinstance(scope, str) or not scope:
        raise TransactionShapeError("projection scope must be a non-empty string")
    if PROJECTION_SEPARATOR in event_id or PROJECTION_SEPARATOR in scope:
        raise TransactionShapeError("projection id contains a reserved separator")
    return f"{event_id}{PROJECTION_SEPARATOR}{scope}"


def _inherit_root_metadata(
    event: Transaction,
    root: TransactionView,
) -> Transaction:
    if "confirmed-round" not in event and "confirmed-round" in root:
        event["confirmed-round"] = deepcopy(root["confirmed-round"])
    return event


def flatten_transfer_payments(transactions: Sequence[TransactionView]) -> list[Transaction]:
    """Return top-level and nested transfers/payments without mutating input."""

    flattened: list[Transaction] = []
    for transaction in transactions:
        root_id = _root_id(transaction)
        if ASSET_TRANSFER_TX in transaction or PAYMENT_TX in transaction:
            flattened.append(_copy_with_id(transaction, root_id))
            continue
        if APPLICATION_CALL_TX not in transaction:
            continue

        for inner, event_id in _walk_inner(transaction, root_id=root_id):
            if ASSET_TRANSFER_TX in inner or PAYMENT_TX in inner:
                flattened.append(
                    _inherit_root_metadata(
                        _copy_with_id(inner, event_id),
                        transaction,
                    ),
                )
    return flattened


def flatten_asset_transfers(
    transactions: Sequence[TransactionView],
    *,
    skip_groups_with_payments: bool = True,
) -> list[Transaction]:
    """Return asset transfers, optionally excluding claim-like payment groups."""

    flattened: list[Transaction] = []
    for transaction in transactions:
        root_id = _root_id(transaction)
        if ASSET_TRANSFER_TX in transaction:
            flattened.append(_copy_with_id(transaction, root_id))
            continue
        if APPLICATION_CALL_TX not in transaction:
            continue

        nested = list(_walk_inner(transaction, root_id=root_id))
        if skip_groups_with_payments and any(PAYMENT_TX in inner for inner, _ in nested):
            continue
        flattened.extend(
            _inherit_root_metadata(
                _copy_with_id(inner, event_id),
                transaction,
            )
            for inner, event_id in nested
            if ASSET_TRANSFER_TX in inner
        )
    return flattened
