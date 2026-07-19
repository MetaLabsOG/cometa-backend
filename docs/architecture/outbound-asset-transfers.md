# Replay-Safe Outbound Asset Transfers

Cometa treats every payout as a durable business operation, not as a retryable
SDK call. Callers provide a stable operation ID such as
`airdrop:<campaign>:<address>` or `nft:lottery:<draw>`.

Before the first broadcast, the service stores:

- immutable receiver, ASA, amount, and note;
- the signed Algorand transaction and its transaction ID;
- its first/last valid rounds and execution status.

A retry loads and rebroadcasts the same signed payload. Before network I/O, the
adapter verifies its signature, transaction ID, sender, receiver, ASA, amount,
note, lease, validity window, and absence of close, clawback, group, or rekey
fields. This closes the crash window where Algorand accepted a transaction but
MongoDB did not record the result and prevents a corrupted intent from sending
another valid treasury transaction.

Algorand uint64 values are stored as decimal strings because BSON integers are
signed int64. Conflicting immutable intent or manifest IDs abort index setup;
the application never deletes financial evidence automatically.

A deterministic Algorand lease adds defense in depth, but persistence of the
exact signed transaction is the primary idempotency mechanism. If the
transaction expires without confirmed status, the service stops and requires
on-chain reconciliation before any replacement can be authorized.

## Airdrop invariants

`send_airdrop` uses exact rational arithmetic and the largest-remainder method,
so recipient base units sum to the declared budget exactly. The first run also
reserves an immutable SHA-256 manifest covering the asset, total, complete
recipient set, allocations, and selected notes. Reusing an `airdrop_id` with a
different manifest fails before any broadcast.

Legacy campaigns have no trustworthy complete-recipient manifest. They
therefore fail closed until explicitly reviewed and migrated. Legacy reward
transactions must be confirmed on-chain and match the stored sender, receiver,
ASA, and amount before they can be marked complete.

Operational retries must always reuse the original operation or airdrop ID.
`AirdropIncompleteError` reports unresolved recipients and transaction IDs;
never invent a replacement ID to bypass reconciliation.

## Lottery payouts

Every lottery draw receives an immutable ID. Legacy draws are assigned a stable
ID derived from their MongoDB identity before payment. The payout intent is
stored against that ID, and the exact draw is marked claimed with a conditional
update only after confirmation. Multiple workers may race safely: they resolve
to the same persisted transaction and cannot update another draw.
