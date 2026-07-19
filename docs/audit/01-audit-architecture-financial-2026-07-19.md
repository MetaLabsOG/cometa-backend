# Мультиагентный аудит архитектуры и финансовой корректности

**Дата:** 2026-07-19
**База:** состояние `main` до ветки `audit/financial-correctness`; история
репозитория затем была очищена, поэтому старые SHA намеренно не используются.

## Резюме

Аудит проводился как review production fintech backend, а не косметическая
подготовка профиля. Независимые потоки проверяли выплаты, MongoDB concurrency,
LP accounting, price provenance, Algorand boundaries, supply chain, Git history,
CI и публичную документацию. Повторяющиеся находки перепроверялись тестами и
исправлялись только после воспроизведения.

Ключевой результат: денежные операции используют integer base units,
неизменяемые business IDs, persisted signed intents и одно-документные CAS.
Непроверенные источники цены и staking projection остаются fail-closed.

| Граница | Контроль |
| --- | --- |
| Выплата | exact allocation, durable intent, bounded signer fee, on-chain reconciliation |
| Staking draw | CAS entitlement, одна generation, crash-repair того же draw ID |
| LP ledger | strict uint64 input, ordered cursor, marker repair, fenced round lease |
| Цена | provenance + freshness + clock-skew guard; raw pool balances запрещены |
| Проверка | Python 3.12/3.14, 372 fast tests, 26 real-Mongo tests, 83.19% focused coverage |

MongoDB гарантирует атомарность одной операции над одним документом; поэтому
денежные инварианты размещены внутри одного CAS aggregate, а не blind
read-modify-write. Междокументная одновременная видимость потребует replica-set
transactions. См. [atomicity](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/)
и [transactions](https://www.mongodb.com/docs/manual/core/transactions/).

## Ранжированные находки

### 1. Critical — секрет оставался в достижимой Git history — исправлено в репозитории

**Почему:** удаление файла из HEAD не отзывает значение и не удаляет старый
blob; его можно восстановить из любого достижимого commit.

**Исправление:** чувствительные исторические пути удалены из всех публикуемых
refs через `git-filter-repo`; old-object и fresh-clone проверки входят в
процедуру публикации. CI сканирует все публикуемые refs digest-pinned
TruffleHog (`.github/workflows/ci.yml:84`). Ротация ранее использованного
credential остаётся обязательным внешним действием владельца.

### 2. Critical — double-pay window, float allocation и signer fee — исправлено

**Почему:** crash после broadcast до Mongo update допускал повторную отправку;
float shares не сохраняли бюджет; доверенный Algod мог предложить чрезмерную
комиссию.

**Исправление:** immutable signed intent сохраняется до первого broadcast и
reconciled по txid (`flex/application/asset_transfers.py:227`). Airdrop заранее
фиксирует полный manifest, а largest-remainder allocation сохраняет каждую base
unit. Confirmed intent и complete manifest терминальны. Gateway до подписи и
повторно перед broadcast проверяет genesis, signature, lease и configured fee
floor/ceiling (`flex/blockchain/asset_transfers.py:50`). Algorand minimum fee описан в
[официальной документации](https://dev.algorand.co/concepts/transactions/fees/).

### 3. Critical — staking lottery создавала две независимые liabilities — исправлено

**Почему:** прежний `read recent draws → insert` позволял двум workers создать
разные draw IDs; idempotency выплаты не объединяет разные business operations.

**Исправление:** один entitlement на `(lottery_name, wallet)` атомарно меняет
`next_eligible_at`, `generation` и active draw. Crash recovery продолжает тот же
draw и replay prize selection (`api/nft_lottery.py:275`). Гонка 32 вызовов и crash
между entitlement/draw writes проверены на настоящем MongoDB. One-of-one NFT
inventory ещё требует отдельной атомарной reservation, поэтому публичные
lottery routes остаются disabled.

### 4. Critical — LP replay мог потерять или повторить баланс — исправлено

**Почему:** blind RMW, stale snapshots и истёкший worker нарушали exactly-once
projection.

**Исправление:** per-state cursor CAS, marker-last repair и re-read после
конкурентного marker (`flex/db/lp_projection.py:52`). Round commit fenced
неистёкшим lease. Fee pool-sender — отдельное replay-safe ALGO событие;
token-token operational ALGO не смешивается с economic reserves. Indexer
amounts, IDs, rounds, duplicates и snapshots проверяются до negation и Mongo
write (`flex/sync_pools.py:78`, `flex/data/lp_states.py:113`).

### 5. Critical — raw account balance мог манипулировать LP price — исправлено

**Почему:** donation, minimum-balance funding или protocol excess не являются
экономическими reserves DEX.

**Исправление:** LP projector стал ledger-only; raw-balance publisher удалён.
Startup очищает обе legacy provenance signatures, а readers независимо их
отклоняют. LP registry прекращает весь refresh, если не классифицирован хотя бы
один farm stake token. Provider observation за пределами clock-skew budget
отклоняется до записи; уже сохранённое далёкое future value считается invalid
и заменяется корректной котировкой. Новый источник допускается только после
DEX-specific app state verification. Canonical supply доверяется лишь с
`total_supply_source=indexer`.

### 6. High — shared browser key не является пользовательской авторизацией — открыто

**Почему:** один `X-API-Key` не доказывает wallet ownership и не разделяет роли
(`core/auth.py:8`, `app.py:323`).

**Конкретный фикс:** wallet-signature challenge с nonce, expiry и replay table;
server-to-server maintenance role с отдельным secret и audit log. До этого
shared key считается compatibility/rate-control механизмом.

### 7. High — blocking persistence остаётся в async routes — открыто

**Почему:** sync PyMongo/provider calls в event loop увеличивают tail latency
всех запросов при деградации Mongo или DEX (`app.py:418`, `app.py:529`).

**Конкретный фикс:** async repository ports с timeout/cancellation; переходно —
`asyncio.to_thread` вокруг целого repository call и saturation test.

### 8. High — legacy staking classifier не доказывает transaction group — mitigated

**Почему:** соседний transfer без проверки app ID, selector и group order не
доказывает stake.

**Текущий контроль:** `SYNC_STAKING_POOLS=false`, а включение отклоняется.
Следующий фикс — типизированный parser полной Algorand group и adversarial
fixtures. Это отдельно от исправленного lottery entitlement.

### 9. High — mocks не доказывали Mongo/BSON invariants — исправлено

**Почему:** fake collections не воспроизводят Decimal128 comparison, unique
index races, `$inc` promotion и `find_one_and_update`.

**Исправление:** digest-pinned MongoDB CI job проверяет 26 integration scenarios:
CAS replay, marker repair, uint64 max, legacy int64 promotion, terminal payout
races, uniqueness, staking entitlement и lease fencing
(`.github/workflows/ci.yml:106`). Stable `python` context агрегирует Python
matrix, container configuration/image scan, Mongo и all-ref secret scan
(`.github/workflows/ci.yml:133`).

### 10. Medium — runtime/container proof остаётся неполным — открыто

**Почему:** production smoke заменяет entrypoint shell-командой, а stateful
Mongo/Algod image rollout требует отдельной data-format rehearsal.

**Конкретный фикс:** disposable stack должен запустить штатный entrypoint,
дождаться health, проверить `/status`, SIGTERM и logs. Production digests
фиксировать только после backup/restore и downgrade rehearsal.

## Milestones

1. **M0 — money safety (готово):** findings 2–5; точные суммы, terminal states,
   fee/network policy, CAS entitlements, strict uint64 boundaries.
2. **M1 — proof and history (готово в коде):** findings 1 и 9; Python
   3.12/3.14, real Mongo, immutable scanner, clean-history procedure.
3. **M2 — authority (следующий):** finding 6, atomic contract registration,
   transactional outbox и one-of-one NFT inventory.
4. **M3 — runtime (следующий):** findings 7, 8 и 10; затем SLO, metrics и
   controlled deploy rehearsal.

Python 3.14.6 проверяется как forward-compatibility gate и является текущим
maintenance release ([Python.org](https://www.python.org/downloads/release/python-3146/));
production-equivalent environment остаётся на Python 3.12.

## Воспроизводимость

```bash
make sync
make quality

# Только disposable MongoDB, никогда production:
MONGODB_TEST_URI=mongodb://127.0.0.1:27017 \
  pipenv run pytest tests/integration -m integration -v
```

Отдельные чистые environments Python 3.12.8 и 3.14.6 дали одинаковый результат:
372 passed, 26 integration skipped. Все 26 integration tests прошли на
standalone MongoDB отдельно. Форматирование не включалось в findings: его
обеспечивает Ruff; review приоритизировал correctness, security, data integrity
и recovery semantics.
