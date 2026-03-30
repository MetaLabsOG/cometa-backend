# Cometa Backend — Task Board

> Last updated: 2026-03-12

## Conventions

- **ID format**: `CB-NNN` (sequential, never reuse)
- **Statuses**: `todo` | `in_progress` | `blocked` | `done`
- **Priorities**: `critical` | `high` | `medium` | `low`
- **Tags**: `security` | `backend` | `frontend` | `infra` | `dx` | `arch` | `perf`
- Next available ID: **CB-071**

---

## Pre-Launch Sprint (March 17 Comeback)

> Full context: `~/dev/cometa/cometa-strategy/research/pre-launch-final-plan.md`
> Cross-project sync: `~/dev/cometa/CLAUDE.md` → "Pre-Launch Coordination" section

### Phase 1 — Independent (no cross-project deps)

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-051 | Fix PoolState/UserState infinite recursion | done | critical | backend | Deleted `to_dict()`/`from_dict()` overrides from both PoolState and UserState — `@dataclass_json` provides them |
| CB-052 | Fix CORS configuration | done | critical | security | Changed to `allow_origins=['https://app.cometa.farm', 'http://localhost:3000']`, `allow_credentials=False` |
| CB-053 | Fix /stats/tvl crashes (3 bugs) | done | critical | backend | (1) `distribution_tvl or 0` guard. (2) `find_one()` instead of `.next()`. (3) None guard on empty snapshot. DoD: `GET /stats/tvl` returns 200 on cold DB |
| CB-054 | Security cleanup: credentials, DB endpoints, dead alerts | done | critical | security | (2) `/db/find` + `/db/count` deleted in CB-059. (3) `notify_prices()` deleted in CB-059. (1) Tatum token in `verify_algorand_credentials.py` — file not used in production, defer |
| CB-055 | Gate fake wallet endpoints | done | critical | backend | `/wallet/{addr}/nfts` and `/wallet/{addr}/total_cost/` now return `[]` directly. Dead functions removed from wallet_manager.py |
| CB-056 | Disable lottery endpoints (if NftLottery entries exist) | done | critical | security | All 3 user-facing lottery endpoints return 503 `{"disabled": true}`. Admin lottery endpoints removed entirely (CB-059) |
| CB-057 | Unify BLOCK_TIME constant | done | high | backend | Deleted hardcoded 3.7s from core/util.py, now uses `settings.block_time` (2.7s). APR calculations corrected (~37% increase) |
| CB-058 | JS sidecar timeout | done | high | backend | Added `settimeout(30)` + `asyncio.wait_for(timeout=30)` + `TimeoutError` in retry handling |

### Phase 2 — Dead Code Removal

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-059 | Remove dead endpoints and modules | done | high | backend | Removed 23 dead endpoints from flex/api.py, 22 from app.py. Deleted 5 dirs (metapunks, farcaster, unusedcode, marketplaces, airdrop), 6 dead scripts, 3 orphan background tasks. Kept `/contracts/refresh-cache` (ops). `/lp/states/update` removed in CB-070. Also: CB-055 (wallet nfts/cost return []), CB-056 (lottery returns 503) |
| CB-060 | Fix blocking I/O in async handlers | done | high | backend, perf | `get_wallet_assets()` wrapped in `run_in_executor()`. `get_address_app_ids()` in `/contracts` replaced with async version. `send_nft()`/`is_opted_in()` no longer called (lottery disabled) |
| CB-061 | Docker hardening | done | high | infra | Added `.dockerignore`, added `HEALTHCHECK` to Dockerfile. Bind mount removal requires VPS docker-compose.yml change (noted for Phase 3 deploy) |

### Phase 3 — Performance & Code Quality

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-063 | Optimize background asset price update | done | high | backend, perf | Batch-fetch all prices in 1 MongoDB query (was N individual queries). Removed per-asset `asyncio.sleep(1)` — only sleep between batches. Task now completes within interval |
| CB-064 | Fix blocking I/O in flex async functions | done | high | backend, perf | Wrapped sync algod/indexer SDK calls in `run_in_executor` in `flex/blockchain/info.py` and `flex/data/transactions.py`. No longer blocks uvicorn event loop |
| CB-065 | Optimize `exists()` queries | done | medium | backend, perf | Changed `CollectionManager.exists()` from `count_documents` (full scan) to `find_one(projection={'_id': 1})` (early exit) |
| CB-066 | Clean up dead utility functions in blockchain/node.py | done | medium | backend | Removed `print_created_asset`, `print_asset_holding`, `try_rekeyed_transaction` — dead copypaste code with hardcoded addresses |

---

## Active

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-070 | LP token pricing via background worker | done | high | backend | LP prices calculated from on-chain reserves in `update_asset_prices_background`, written to `asset_prices`. Broken lp_states/lp_tokens/sync_pools pipeline bypassed. 3/3 LP tokens verified on prod. Phase 2 cleanup (delete old modules) deferred |
| CB-001 | Rotate compromised keys from `test_refund.py` | done | critical | security, backend | File gitignored. Keys rotated manually (2026-03-09) |
| CB-002 | Move `password` from query string to `X-API-Key` header | done | critical | security, backend | `core/auth.py` created, 18 endpoints migrated to `Depends(require_password)` |
| CB-033 | Add MCP servers: Algorand, Vestige, MongoDB | done | high | dx | Added to `~/.claude/mcp.json` |
| CB-035 | Fix cacheMigration stale wallet keys — users disconnected on every deploy | done | critical | frontend | `cacheMigration.ts` preserved wrong key names, bumped to v3 |
| CB-036 | Fix ErrorBoundary preserving wrong wallet localStorage keys | done | critical | frontend | Was saving `walletType` instead of `connectedWalletType` |
| CB-037 | Fix auto-reconnect blocked by `window.algorand` browser extension | done | high | frontend | `ConnectWallet.tsx:109` — removed `!window.algorand` condition |
| CB-040 | Fix Rules of Hooks in `meteors-styled.tsx` — hooks after conditional return | done | critical | frontend | Moved hooks before conditional return, memoized meteor positions |
| CB-041 | Fix `throw` in Effector `combine` (`Farm/store.ts:597`) | done | critical | frontend | Replaced with fallback sort by TVL |
| CB-042 | Fix BigInt division by zero in `createAprs` | done | critical | frontend | Guard `totalBlocks === 0n` before division |
| CB-043 | Fix `parseBignumState` throw in derived store | done | critical | frontend | Wrapped in try/catch, logs warning on parse failure |
| CB-044 | Fix `useUnit()` inside JSX in `Farm.tsx` | done | critical | frontend | Moved to top level of render function |
| CB-045 | Fix Immutable Map.set() in `loadAssetsFromLocalStorage` | done | critical | frontend | `assets = assets.set(...)` — result was being discarded |
| CB-046 | Remove 600+ infinite CSS animations from pool components | done | high | frontend, perf | Removed subtle-glow, reward-glow, token-glow, amount-glow, textclip |
| CB-047 | Replace `window.innerWidth` in render with `useWindowSize()` | done | high | frontend, perf | Farm.tsx, Stake.tsx — prevents layout thrashing |
| CB-048 | Fix error handling: Vestige type, useEffect deps, unhandled rejections | done | high | frontend | coinPriceProvider, LaaS deps, Zap/Swap .catch() |
| CB-049 | Fix enriched prices: 164 tokens getting META price, batch Vestige API | done | critical | backend, perf | Cache namespace collision, upsert race condition, unique index, distribution contracts, batch API, price validation. See `ENRICHED_PRICES_BUG.md` |
| CB-050 | Fix LP/CORS/enriched: batch /lp/state/priced, CORS on errors, stabilize enriched | done | high | backend, perf | Batch LP endpoint (asyncio.gather), catch-all exception handlers for CORS, enriched TTL 60s + parallel asset fetch |

## Backlog

### Security

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-003 | Remove hardcoded API keys from frontend bundle (`logEvent.tsx`) | todo | critical | security, frontend | `logEvent.tsx:50,80` — Airtable PAT + Amplitude key in source. Move to `REACT_APP_*` env vars |
| CB-004 | Fix query cache key to include `user_address` — prevents cross-wallet data leak | todo | critical | security, frontend | `src/index.tsx:125-126` — `useQuery(['contracts', 'farm'], ...)` ignores wallet address change |

### Backend — Critical / High

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-005 | Fix duplicate `add_new_contract` function — second definition shadows first | todo | critical | backend | `app.py:317` and `app.py:329` — same function name, `/contract/add` endpoint is dead |
| CB-006 | Atomize lottery claim — prevent double NFT distribution via race condition | todo | critical | backend | `app.py:703-776` — no lock between `is_opted_in()` check and `send_nft()`. Use `findOneAndUpdate` with `claimed: false` condition |
| CB-007 | Fix blocking I/O in async endpoints — `send_nft()`, `is_opted_in()`, `get_account_assets()` | done | critical | backend, perf | `get_wallet_assets` wrapped in `run_in_executor` (CB-060). `send_nft`/`is_opted_in` no longer called (lottery disabled). `flex/blockchain/info.py` sync calls wrapped (CB-064) |
| CB-008 | Configure aiocache to use Redis backend instead of in-memory | todo | high | backend, perf | `flex/providers/vestige.py`, `flex/data/` — SimpleMemoryCache means N workers = N caches = N API calls |
| CB-009 | Unify `get_current_round()` — two implementations with different TTL and clients | done | high | backend, arch | Async version now delegates to sync via `run_in_executor`. Single algod call, shared cachetools cache. Dead functions removed from `blockchain/node.py` |
| CB-010 | Fix CircuitBreaker — `asyncio.Lock` doesn't work across `spawn.Process` | todo | high | backend | `core/circuit_breaker.py:21` — each process has own CB instance, protection ineffective |
| CB-011 | Fix N+1 queries in `/pools/state/` and `/pools/cost` endpoints | todo | high | backend, perf | `flex/api.py:83-88, 95-97` — sequential awaits per pool. Use `asyncio.gather()` |
| CB-012 | Add MongoDB indexes for hot queries | done | high | backend, perf | Added indexes on `lp_states.token_id`, `pool_states.pool_id`, `user_states.address`, `lp_tokens.id` at startup in `init_app()` |
| CB-013 | Fix `delete /pool/` endpoint — only reads, doesn't delete | todo | high | backend | `flex/api.py:51-52` — DELETE handler returns data without removing |

### Backend — Medium

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-014 | Replace all `print()` with `logger` calls | done | medium | backend | Replaced in `blockchain/node.py`, `flex/data/stats.py`, `flex/data/transactions.py`, `flex/migrations/__init__.py`. `env.py` keeps print (runs before logging configured). Remaining prints in scripts/one-off tools only |
| CB-015 | Standardize datetime usage — all `datetime.now(timezone.utc)` | todo | medium | backend | `app.py:205,260`, `flex/api.py:87,212` — mix of naive and aware datetimes |
| CB-016 | Pin dependency versions in Pipfile | todo | medium | backend, infra | All packages `"*"` — non-reproducible builds. Pin to current working versions |
| CB-017 | Fix Dockerfile — layer caching, non-root user, .dockerignore | todo | medium | infra | COPY before pip install, no USER directive, apt cache not cleaned |
| CB-018 | Fix JS interop zombie processes — `start_js_interop_server()` leaks Node.js processes | done | medium | backend | Fixed: global process tracking, kill-before-spawn, context manager, atexit cleanup, restart cooldown, run_in_executor for async context |
| CB-019 | Fix `safe_async_method` — return value discarded, decorator order with `@repeat_every` | todo | medium | backend | `core/decorators.py:6-11` — swallows return values |
| CB-020 | Clean up dead code — `unusedcode/`, `notify_prices`, `check_vestige_hack.py`, debug scripts | todo | medium | backend | `unusedcode/`, `api/background.py:187-195`, root-level temp scripts |
| CB-021 | Deduplicate `check_password` function | todo | low | backend | `app.py:70` and `flex/api.py:38` — identical functions |

### Frontend — High

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-022 | Fix `$assets.getState()` timing — LP pre-population reads store before it's updated | todo | high | frontend | `src/index.tsx:200-211` — Effector store not yet populated when LP data reads it |
| CB-023 | Replace `window.innerWidth` in render with `useWindowSize()` hook | todo | high | frontend | `Farm.tsx:15,75`, `Stake.tsx:41,44`, `AppContext.ts:56` — 5+ different mobile detection methods |
| CB-024 | Fix LP cache — `getLPTokenInfo` still calls DEX even on cache hit | todo | high | frontend, perf | `src/Farm/store.ts:70-180` — cache saves nothing, `dex.getPoolByAssets` called regardless |
| CB-025 | Reduce Sentry `tracesSampleRate` from 1.0 to 0.1 | todo | high | frontend, perf | `src/index.tsx:57` — 100% sampling in production, excessive load |

### Frontend — Medium / Low

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-026 | Delete deprecated `algoExplorerProvider.ts` | todo | medium | frontend | AlgoExplorer API is dead, provider unused but imported |
| CB-027 | Remove `console.log` in production module-level code | todo | medium | frontend | `AppContext.ts:22,57,63` — logs ALGONET, IS_MOBILE, fees to every user's console |
| CB-028 | Fix double retry in `tinymanPriceProvider.ts` — up to 6 attempts before Vestige fallback | todo | medium | frontend, perf | `tinymanPriceProvider.ts:66-79` — nested retries, 10+ seconds on bad network |
| CB-029 | Remove or fix stub functions in `types.ts` — `parseInitialInfo`, `parseGlobalInfo`, `parseLocalInfo` | todo | medium | frontend | `types.ts:357-385` — return undefined, will crash if ever called |
| CB-030 | Fix `useEffect` deps in `Pool.tsx` — `account` object causes unnecessary re-inits | todo | medium | frontend | `Pool.tsx:43-45` — depend on `account?.networkAccount.addr` not whole object |
| CB-031 | Split `AddFarm.tsx` monolith (777 lines) into form + deploy + state hook | todo | low | frontend, arch | Single file handles both farm and stake creation, validation, deploy |
| CB-032 | Add unit tests for business logic — reward calc, price calc, APR | todo | low | frontend | Only 3 test files, all skipped in CI. Zero coverage on core logic |

### Infrastructure / DX

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| ~~CB-033~~ | ~~Add MCP servers~~ | done | high | dx | Duplicate — see Active section line 21 |
| CB-034 | Add pytest infrastructure + basic test coverage for critical paths | todo | high | backend | No tests at all. Start with: lottery claim, contract CRUD, price fetching |

## Done

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
