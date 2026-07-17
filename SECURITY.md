# Security Policy

## Supported Versions

Security fixes target the current `main` branch and the version deployed at
[`api.cometa.farm`](https://api.cometa.farm/status). Older commits and local
development snapshots are not maintained as separate release lines.

## Report a Vulnerability

Do not open a public issue or pull request for a suspected vulnerability. Use
GitHub's
[private vulnerability reporting](https://github.com/MetaLabsOG/cometa-backend/security/advisories/new)
to share the report securely with the maintainers.

Include:

- the affected endpoint, component, or commit;
- reproducible steps and the expected impact;
- whether funds, signing operations, credentials, or data integrity are at risk;
- a minimal proof of concept with secrets and personal data removed.

We aim to acknowledge reports within three business days. Please allow time for
validation, remediation, credential rotation, and coordinated disclosure before
publishing details.

## Sensitive Areas

The highest-risk boundaries are API authentication, Algorand transaction
signing, the Python/Node.js sidecar, price-provider fallbacks, and event replay.
Tests must use generated accounts and non-production credentials.

Never commit mnemonics, API keys, `.env` files, database exports, recovery
artifacts, or unredacted logs. If a secret reaches Git history, revoke or rotate
it immediately; deleting the current file is not sufficient.
