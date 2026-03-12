# Backend Agent Briefing — Pre-Launch Sprint

Read this at session start before touching any code.

## Context

Cometa is relaunching after 8 months of shutdown. Comeback tweet: March 17, 2026. Your task board: `BOARD.md` → "Pre-Launch Sprint" section (CB-051 to CB-061).

## Phase 0 (developer does manually on VPS)

You don't do these — the developer handles ops:
- SSL renewal, algod sync, MongoDB `sync_state.last_round` update, cache warmup
- Check if `db.nft_lotteries.find().count() > 0` → determines if CB-056 is needed

## Phase 1 (do first — data bugs, then security)

Order matters:
1. **CB-051** — PoolState recursion (crashes everything)
2. **CB-052** — CORS fix (unblocks frontend testing)
3. **CB-053** — TVL crash fixes (3 separate 1-line bugs)
4. **CB-054** — Security: credentials + dead DB endpoints + notify_prices
5. **CB-055** — Gate fake wallet endpoints (returns `[]`)
6. **CB-056** — Disable lottery (only if developer confirms NftLottery entries exist)
7. **CB-057** — BLOCK_TIME unification
8. **CB-058** — JS sidecar timeout

## Phase 2 (dead code removal + hardening)

- **CB-059** — Remove 39 dead endpoints + 7 dead directories. This is the biggest task. See the full dead endpoint list in `~/dev/cometa/cometa-strategy/research/pre-launch-final-plan.md`.
- **CB-060** — Blocking I/O → `run_in_executor`
- **CB-061** — Docker hardening

## Cross-project awareness

- Your CB-052 (CORS) unblocks the frontend agent. Prioritize it early.
- Your CB-055 + CB-056 have frontend counterparts (MF-046, MF-048). Update Cross-Project Task Sync in `~/dev/cometa/CLAUDE.md` when done.
- After removing endpoints in CB-059, update the API Contract table in `~/dev/cometa/CLAUDE.md`.

## Do NOT touch

- Reach JS sidecar contract logic in `js/contracts/`
- Algorand transaction signing paths
- Wallet mnemonic handling
- `telegram_bot.py` (separate process)
- Any dependency version upgrades (risky 4 days before launch)

## Important: 8-month gap

- algod may be syncing when you start. `get_current_round()` returns 0 or stale.
- All caches are empty. First requests will be slow.
- Don't panic about stale data — Phase 0 ops handles the warm-up.

## When done

Update task status in `BOARD.md`. For CB-055, CB-056: also update Cross-Project Task Sync in `~/dev/cometa/CLAUDE.md`.
