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
self-transfers are discarded as net zero. Clawback and close semantics fail
closed only when they affect an LP account.

The repository fails closed when:

- an event ID exists with different immutable data;
- an event marker exists while its state cursor is still behind;
- a later cursor has passed an unrecorded event;
- a balance would leave the Algorand uint64 range;
- legacy root aliases make an inner event ambiguous;
- duplicate LP token IDs or addresses exist.

Reserves, issued LP supply, IDs, rounds, positions, and deltas are Python
integers encoded as BSON Decimal128 where MongoDB int64 is insufficient.
Pricing stays in `Decimal`; floats exist only in legacy API fields. ASA total
supply is read directly from Indexer base units and persisted as a decimal
string.

## Snapshots and derived prices

Account balances and `current-round` come from the same Indexer response. An
authoritative snapshot advances the cursor to that round’s end sentinel. A
stale snapshot cannot overwrite a newer event, and conflicting balances for the
same snapshot round require reconciliation. Price writers update only derived
fields when the state cursor still matches; a monotonic observation timestamp
prevents an older calculation from overwriting a newer quote. Tinyman reserve
projection writes only the underlying asset quote; the LP token price has one
canonical writer.

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

Indexer account balances are authoritative for reconciliation, but not
necessarily for a DEX’s economic reserve accounting: donations and protocol
excess balances may be included. Production pricing therefore remains disabled
until each DEX has a verified app-state adapter.
