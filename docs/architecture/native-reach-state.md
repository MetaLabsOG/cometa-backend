# Native Reach State Decoding

## Context

Cometa farm and distribution contracts were compiled with Reach 0.1.11. The
backend previously launched a Node.js sidecar and loaded the generated Reach
backend solely to read public views. That duplicated the runtime, required a
private npm dependency, and made request handling depend on a local socket.

## Decision

`flex/blockchain/contract_state.py` decodes the supported layouts directly from
Algorand application and account state. Each `(contract type, version)` entry
defines its packed-state size, field offsets, expected schema, program pages,
and approval-program digest.

The adapter fails closed before exposing decoded data:

1. fetch application data outside the event loop;
2. verify the returned application ID, approval and clear-program digests,
   schemas, and extra program pages;
3. reconstruct Reach byte-slice chunks and require the expected consensus step
   and exact length;
4. decode fixed-width unsigned integers and validate every local `Maybe` tag;
5. isolate malformed contracts while bounding batch concurrency.

The resulting dictionaries preserve the historical `BigNumber` JSON shape, so
the API and frontend contract remain unchanged.

## Consequences

- Production needs only Python 3.12; Node.js and the socket bridge are gone.
- Contract identity is explicit and testable instead of implied by byte shape.
- New compiler outputs are unsupported by default.
- Layout changes require evidence from the canonical compiled artifact and
  on-chain parity checks.

## Adding a Contract Version

Add a layout only after recording the canonical program digest, schema, page
count, state size, and offsets. Cover global and local decoding, identity
rejection, malformed payloads, failure isolation, and concurrency bounds. Run
`make quality`, then compare at least one mainnet application with the previous
decoder before enabling the version.
