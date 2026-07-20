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
note, lease, validity window, fee ceiling, configured network genesis, and
absence of close, clawback, group, or rekey fields. Suggested parameters are
normalized to a flat protocol-minimum fee only after Algod's reported minimum
is at least the protocol floor and both fee ceiling and genesis match policy.
This closes the crash window where Algorand accepted a
transaction but MongoDB did not record the result, prevents node-provided fees
from draining the signer, and stops a corrupted intent from sending another
valid treasury transaction.

ASA IDs and amounts remain decimal strings for compatibility; validity and
confirmation rounds use BSON Decimal128 codecs. Both representations preserve
the full Algorand uint64 domain rather than relying on signed BSON int64.
Conflicting immutable intent or manifest IDs abort index setup; the application
never deletes financial evidence automatically.

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

`send_airdrop` is also safe when invoked directly by an operator script rather
than through FastAPI startup: before any reward read or signing, it fail-closes
on duplicate manifest IDs or reward operation IDs and installs their unique
indexes. Concurrent workers therefore converge on one reward record as well as
one transfer intent.

Legacy campaigns have no trustworthy complete-recipient manifest. They
therefore fail closed until explicitly reviewed and migrated. Legacy reward
transactions must be confirmed on-chain and match the stored sender, receiver,
ASA, and amount before they can be marked complete.

Operational retries must always reuse the original operation or airdrop ID.
`AirdropIncompleteError` reports unresolved recipients and transaction IDs;
never invent a replacement ID to bypass reconciliation.
`complete` is terminal: a slower worker cannot overwrite it with `partial`.
Likewise, attempt, submitted, and error updates cannot regress a confirmed
transfer intent.

## Lottery payouts

Every new lottery draw receives an immutable ID and starts in `pending`. The
payout moves through `prepared` to `confirmed`; uncertain attempts remain
`unresolved` and reuse the same operation.

Staking lotteries first claim a single entitlement document keyed by
`(lottery_name, wallet)`. A compare-and-set advances its rolling 24-hour window,
generation, and active draw ID atomically. Prize selection and draw insertion
are replay-repaired from that reservation, so crashes and competing workers
converge on one liability. An unresolved prize blocks the next generation until
reconciliation; no-prize and confirmed generations are terminal.

Pre-intent legacy draws are different: an old worker may have broadcast and
crashed before recording `claimed`. They receive a deterministic ID but move to
`reconciliation_required`, never directly to payment. Automatic resume is
allowed only when the draw already references the exact durable operation ID,
which proves that any broadcast used the persisted-intent path. Manual
reconciliation must otherwise attach verified on-chain evidence or explicitly
authorize an unpaid draw.

The exact draw is marked claimed with a conditional update only after
confirmation. Multiple workers may race safely: they resolve to the same
persisted transaction and cannot update another draw.

Lottery inventory is a separate authority boundary. Public lottery routes are
disabled because one-of-one NFT inventory is not yet reserved atomically.
