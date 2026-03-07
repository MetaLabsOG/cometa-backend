# Cometa Backend — Task Board

> Last updated: 2026-03-08

## Conventions

- **ID format**: `CB-NNN` (sequential, never reuse)
- **Statuses**: `todo` | `in_progress` | `blocked` | `done`
- **Priorities**: `critical` | `high` | `medium` | `low`
- **Tags**: `security` | `backend` | `frontend` | `infra` | `dx` | `arch` | `perf`
- Next available ID: **CB-050**

---

## Active

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-001 | Rotate compromised keys from `test_refund.py` | in_progress | critical | security, backend | File gitignored. **Keys must be rotated manually** — mnemonic + Nodely token in git history |
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
| CB-007 | Fix blocking I/O in async endpoints — `send_nft()`, `is_opted_in()`, `get_account_assets()` | todo | critical | backend, perf | `api/wallet.py`, `blockchain/indexer.py:46`, `app.py:739` — sync calls block uvicorn event loop |
| CB-008 | Configure aiocache to use Redis backend instead of in-memory | todo | high | backend, perf | `flex/providers/vestige.py`, `flex/data/` — SimpleMemoryCache means N workers = N caches = N API calls |
| CB-009 | Unify `get_current_round()` — two implementations with different TTL and clients | todo | high | backend, arch | `blockchain/node.py:26` (sync, cachetools) vs `flex/blockchain/info.py:55` (async, aiocache) |
| CB-010 | Fix CircuitBreaker — `asyncio.Lock` doesn't work across `spawn.Process` | todo | high | backend | `core/circuit_breaker.py:21` — each process has own CB instance, protection ineffective |
| CB-011 | Fix N+1 queries in `/pools/state/` and `/pools/cost` endpoints | todo | high | backend, perf | `flex/api.py:83-88, 95-97` — sequential awaits per pool. Use `asyncio.gather()` |
| CB-012 | Add MongoDB indexes for hot queries | todo | high | backend, perf | `contract` (type), `lottery_draws` (wallet+claimed), `pool_states` (pool_id) — full collection scans |
| CB-013 | Fix `delete /pool/` endpoint — only reads, doesn't delete | todo | high | backend | `flex/api.py:51-52` — DELETE handler returns data without removing |

### Backend — Medium

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
| CB-014 | Replace all `print()` with `logger` calls | todo | medium | backend | `env.py:102-105`, `api/background.py:320`, `blockchain/node.py:44-102` — print in production |
| CB-015 | Standardize datetime usage — all `datetime.now(timezone.utc)` | todo | medium | backend | `app.py:205,260`, `flex/api.py:87,212` — mix of naive and aware datetimes |
| CB-016 | Pin dependency versions in Pipfile | todo | medium | backend, infra | All packages `"*"` — non-reproducible builds. Pin to current working versions |
| CB-017 | Fix Dockerfile — layer caching, non-root user, .dockerignore | todo | medium | infra | COPY before pip install, no USER directive, apt cache not cleaned |
| CB-018 | Fix JS interop zombie processes — `start_js_interop_server()` leaks Node.js processes | todo | medium | backend | `core/js_interop.py:18` — no cleanup on retry, zombies accumulate |
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
| CB-033 | Add MCP servers: Algorand, Vestige, MongoDB | todo | high | dx | `@goplausible/algorand-mcp` (61 tools), `@goplausible/vestige-mcp`, `mongodb-mcp-server` — direct DeFi dev value |
| CB-034 | Add pytest infrastructure + basic test coverage for critical paths | todo | high | backend | No tests at all. Start with: lottery claim, contract CRUD, price fetching |

## Done

| ID | Task | Status | Priority | Tags | Notes |
|----|------|--------|----------|------|-------|
