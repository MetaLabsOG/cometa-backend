# Crash-Safe LP Projection

The LP projector treats MongoDB’s LP-state document as the authoritative
idempotency boundary. This is required because the deployed standalone MongoDB
cannot atomically update both `lp_states` and `lp_transactions`.

## Invariants

Each scoped transfer has a fixed-width cursor:

```text
<confirmed-round>:<block-event-position>:<event-id>
```

Events are sorted by that cursor. One `find_one_and_update` atomically applies
the Decimal128 balance delta and advances `last_event_order`. The audit marker
is inserted afterward. If the process dies in that gap, replay sees the cursor,
repairs the missing marker, and does not apply the delta again.

Before the first write, the complete block batch is checked for its expected
round, deterministic order, duplicate IDs, and conflicting payloads. LP
self-transfer amount legs are discarded as net zero, but their network fee is
still projected. Every pool-paid fee is a separate, stable
`<event-id>#fee@<pool>` ALGO event, so retry cannot combine or repeat it.
Clawback and close semantics fail closed when they affect a tracked LP account.
Indexer rounds, asset IDs, amounts, balances, and fees reject booleans,
coercible strings, negatives, and overflow before any delta is negated or any
repository write begins.

The repository fails closed when:

- an event ID exists with different immutable data;
- an event marker exists while its state cursor is still behind;
- a later cursor has passed an unrecorded event;
- a balance would leave the Algorand uint64 range;
- legacy root aliases make an inner event ambiguous;
- duplicate LP token IDs or addresses exist;
- one LP-token ASA is discovered with conflicting immutable pool metadata.

Balances, issued LP supply, IDs, rounds, positions, fees, and deltas are Python
integers encoded as BSON Decimal128 where MongoDB int64 is insufficient.
Token-token pools keep fee-funding ALGO in
`operational_algo_balance_micros`, separate from the two economic asset
balances. ASA total supply is read directly from Indexer base units and
persisted as a decimal string with `total_supply_source=indexer`. A legacy or
generic rewrite without that provenance is refetched and migrated atomically
before a financial read may use it. A unique asset ID index makes concurrent
creation fail closed. LP-token registration likewise uses a unique Decimal128
ASA ID plus atomic `get-or-create`, then compares pool ID, assets, address, and
DEX provider against the persisted winner.

## Snapshots and pricing isolation

Account balances and `current-round` come from the same Indexer response. An
authoritative snapshot advances the cursor to that round’s end sentinel. A
stale snapshot cannot overwrite a newer event, and conflicting balances for the
same snapshot round require reconciliation. Snapshots update only integer ledger
fields and cursors: they never calculate or publish a price.
Duplicate holdings and out-of-range values are rejected at the Indexer adapter;
issued supply is range-checked before subtraction. Refresh builds an immutable
candidate state, and the repository repeats validation before issuing its
single-document CAS, so a failed snapshot cannot partially mutate in-memory or
persisted balances.

Indexer account balances are useful for reconciliation but are not proof of a
DEX’s economic reserves. Donations, minimum-balance funding, and protocol excess
can all be present. The ledger projector therefore has no price-publishing
dependency. Public LP prices come from the separately validated `asset_prices`
read model with source and freshness checks. The raw-balance publisher has been
removed; startup deletes its identifiable legacy rows and read paths
independently reject them. A future DEX adapter must derive economic reserves
from verified protocol state before it can become a price source.

## Worker ordering

The singleton `sync_states/main` document provides a Mongo lease and a fenced,
compare-and-set round checkpoint. An expired worker can duplicate work but
cannot regress the checkpoint; per-state cursors make that replay convergent.
Cutover advances only through the minimum round fully covered by every LP
cursor. A mid-round event cursor covers the preceding round, not the unfinished
one, so an Indexer lag cannot skip its remaining events.
Repeated deterministic failure uses bounded exponential backoff and terminates
the worker instead of hot-looping.

`SYNC_LIQUIDITY_POOLS` remains opt-in until an operational snapshot cutover is
performed. `SYNC_STAKING_POOLS` remains disabled because the legacy classifier
does not validate complete Algorand application groups. Enabling it is rejected
at runtime rather than risking financial corruption.

Standalone MongoDB still cannot make an LP-to-LP transfer visible in two pool
documents simultaneously. Replay guarantees convergence; strict cross-pool
visibility would require a replica-set transaction or a one-document ledger
aggregate.

`BACKGROUND_LP_PRICES_UPDATE` remains accepted only for deployment
compatibility and cannot restore the removed publisher. Enabling LP ledger sync
does not bypass this boundary.
