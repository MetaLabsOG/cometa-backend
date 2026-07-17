# Codebase Audit — 2026-07-17

## Executive Summary

Three independent reviewers audited architecture/reliability, security/data integrity, and testing/DX across 143 tracked files and roughly 9.4k lines of Python, JavaScript, and Solidity. Cometa demonstrates credible production experience: multi-DEX integration, on-chain state processing, fallback providers, background workers, MongoDB, TTL caching, and Python/Node interoperability. The strongest gaps are fintech correctness boundaries rather than syntax: event replay is not exactly-once, stale prices can appear fresh, chain outages become valid data, and signing capability shares a trust boundary with the public service.

The first remediation milestone is complete in the working tree: current credential material was removed, Docker exclusions were hardened, Mongo `get_or_create` became a single-operation upsert, tests/CI were introduced, and the public README was rebuilt. Concurrent uniqueness still requires collection-level indexes. Historical credentials require rotation and history cleanup before the repository is made public.

## What the Vacancy and Market Reward

The vacancy asks for Python/FastAPI plus agents, RAG, model integration, experimentation, and MVP speed. Current production guidance adds a more important discriminator: reliable AI engineers establish eval baselines, build narrow composable tools, trace failures, constrain high-risk actions, and optimize only after measuring quality.

- [OpenAI's agent guide](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/) emphasizes eval baselines, reusable tools, layered guardrails, and human approval for financial actions.
- [Anthropic's agent guidance](https://www.anthropic.com/engineering/building-effective-agents) recommends simple composable patterns before framework complexity; its [agent eval guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) treats multi-turn trajectories and environment state as first-class.
- A current [LangChain production-agent role](https://jobs.ashbyhq.com/langchain/7ed7ca6f-2b4a-4dcd-8c14-c0f85fcf9ae2/) explicitly asks for failure handling, evaluation, observability, guardrails, and systems fundamentals—not API demos.
- [LangSmith evaluation](https://docs.langchain.com/langsmith/evaluation) separates offline regression datasets from online production evaluation.
- [Qdrant hybrid-search guidance](https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/) combines dense and sparse retrieval with reranking and continuous relevance testing.
- [OWASP Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) makes least-privilege tools and approval boundaries especially relevant to fintech agents.

## Findings

| # | Severity | Issue | Location | Why it matters | Concrete fix | Agent |
|---|---|---|---|---|---|---|
| 1 | Critical | Financial projections are not exactly-once | `flex/data/pool_state.py:116`, `flex/data/pool_state.py:143`, `flex/data/lp_states.py:149`, `flex/data/lp_states.py:176` | State is persisted before transaction markers; a crash can replay deltas. The full input batch is recorded even when events were skipped. | Add an immutable inbox keyed by `(network, txid, inner_index)`, `pending/applied` states, versioned CAS updates, and deterministic replay/invariant tests. Use Mongo transactions only after enabling a replica set. | architecture |
| 2 | High | Public API and signer share a trust boundary | `flex/blockchain/base.py:20`, `flex/blockchain/base.py:29`, `js/commands.mjs:119`, `js/commands.mjs:155`, `js/index.js:35` | A long-lived service loads a mnemonic and exposes deployment-capable commands through an unauthenticated Unix socket. API compromise can become fund compromise. | Make the API read-only. Move signing to an isolated service/KMS with an allowlisted transaction policy, authenticated IPC, `0600` socket permissions, audit logs, and human approval for high-risk actions. | security |
| 3 | High | Failed price refreshes are marked fresh | `flex/data/asset_prices.py:110`, `flex/data/asset_prices.py:115`, `flex/data/asset_prices.py:125`, `flex/providers/price_router.py:108` | Old values receive the current round after a provider failure; routing then treats them as authoritative. TVL and APR can silently use stale data. | Introduce `PriceQuote(value, source, observed_at, stale_after)`. Update freshness only on success, validate finite positive `Decimal` values, apply deviation limits, then return explicit stale data or `503`. | architecture + security |
| 4 | High | On-chain amounts cross `float` boundaries | `flex/db/model/blockchain.py:78`, `flex/db/model/blockchain.py:82`, `flex/db/model/blockchain.py:107`, `flex/db/model/blockchain.py:120`, `flex/tools/airdrop.py:40` | Valid uint64-scale values can lose micros; the airdrop formula also rounds every recipient upward and can exceed its budget. | Store micros as `int`, expose decimal strings at API boundaries, and allocate payouts with a largest-remainder algorithm plus `sum(outputs) == budget` tests. | architecture + security |
| 5 | High | Contract registration is race-prone and fail-open | `app.py:227`, `app.py:248`, `app.py:295`, `app.py:299`, `app.py:307` | Check-then-insert permits duplicates; provisioning failures are swallowed; beneficiary verification is skipped when configuration is absent; program identity is not allowlisted. | Add unique `(network,id)` storage, an idempotent `verifying → provisioning → active/failed` state machine, fail-closed config, and approval/clear program hash allowlists per version. | architecture + security |
| 6 | High | Algod outage becomes round zero | `blockchain/node.py:23`, `blockchain/node.py:30`, `blockchain/node.py:32`, `blockchain/node.py:37` | Cold-start failure produces a plausible integer used by date migrations, active-pool filters, and synchronization, potentially persisting corrupt state. | Return `RoundSnapshot(round, observed_at)` or raise `ChainUnavailable`; permit last-known data only inside a bounded stale window and block mutations/readiness outside it. | architecture + security |
| 7 | High | Async boundaries still execute blocking storage calls | `app.py:394`, `app.py:402`, `flex/api.py:132`, `flex/api.py:148`, `core/db/mongodb.py:5` | Synchronous PyMongo and some provider calls can block the event loop during pool exhaustion or outages, amplifying tail latency. | Introduce repository/provider ports and an app factory. Move to an async Mongo driver or a bounded executor with explicit connect/server/socket timeouts; expose `/livez` and `/readyz`. | architecture |
| 8 | High | Runtime and dependency graph are not reproducible | `Pipfile:7`, `Pipfile:22`, `Pipfile:37`, `Dockerfile:1`, `Dockerfile:9`, `Dockerfile:11`, `docker-compose.yml:27`, `docker-compose.yml:34` | Wildcards, prereleases, mutable images, an unpinned Pipenv install, and an out-of-band Telegram downgrade make local/CI/production behavior diverge. | Pin direct dependencies and image digests, use Node LTS, remove the second `pip install`, run `pipenv sync --system --deploy`, and separate development from production Compose files. | testing/DX + security |

## Completed in Milestone 1

- Replaced current-tree npm credentials with `${NODE_AUTH_TOKEN}` and removed obsolete signing/credential scripts.
- Excluded `.env*`, nested `.npmrc`, and legacy credential tools from Docker build context.
- Replaced the broken literal-key/check-then-insert path with one upsert operation, documented its unique-index requirement, and handled duplicate-key races.
- Preserved async decorator return values and metadata; removed sensitive argument logging.
- Deferred Flex database and signing-runtime initialization until first domain use; low-level imports are now side-effect free.
- Added focused Python/Node regression tests, Ruff configuration, locked dev tooling, and GitHub Actions.
- Fixed JS network-default handling and contract-type validation, including inherited-key rejection.
- Replaced the one-line README with architecture, quickstart, API, security, quality gates, and explicit trade-offs.

## Implementation Milestones

### Milestone 0 — Before Public Exposure

- Rotate/revoke every credential ever committed, inventory affected wallets, and delete published images that may contain secret layers.
- Rewrite Git history with `git filter-repo`, coordinate clones, force-push only after approval, then run a full-history secret scanner.
- Confirm repository visibility, add description/topics, and choose a license.

### Milestone 2 — Fintech Reliability

- Implement the event inbox/projector and crash/duplicate/reorder test matrix.
- Add deduplication migrations and unique primary-key indexes for every projected collection.
- Introduce typed price freshness with `Decimal`, source attribution, and provider quorum/deviation rules.
- Replace round-zero sentinels with typed availability and readiness semantics.
- Split `app.py` into routers, use cases, repository/provider ports, and lifespan-managed dependencies.

### Milestone 3 — AI Portfolio Differentiator

Build a read-only **DeFi Risk Copilot** instead of a decorative chat endpoint:

1. ingest versioned protocol docs and normalized pool events;
2. use Qdrant/pgvector hybrid retrieval with metadata filters and reranking;
3. expose provider-neutral LLM and embedding ports;
4. return Pydantic-validated risk factors, uncertainty, and source citations;
5. version prompts and maintain a golden dataset measuring Recall@k, groundedness, schema validity, cost, and p95 latency;
6. keep all transaction/signing tools outside the agent, or behind explicit human approval.

## Audit Metadata

- Date: 2026-07-17
- Scope: codebase + portfolio alignment
- Depth: standard, compressed to three non-overlapping reviewers
- Agents: architecture/reliability, security/data integrity, testing/DX/portfolio
- Files examined: 143 tracked files
- Findings retained: 8 (1 critical, 7 high)
- Status: Milestone 1 implemented; production-sensitive milestones pending
