# Аудит архитектуры и финансовой корректности

**Дата:** 2026-07-19

**База аудита:** `main@2c1cdad`

**Ветка исправлений:** `audit/financial-correctness`

## Резюме

Аудит проводился с позиции production fintech backend, а не косметической
подготовки GitHub-профиля. На исходной базе были риски повторной выплаты,
потери точности и некорректного replay при конкурирующих воркерах. На ветке
исправлений денежные операции переведены на integer base units, устойчивые
business keys, immutable intents и compare-and-set проекции.

Оценка критических границ до/после:

| Область | До | После | Комментарий |
| --- | ---: | ---: | --- |
| Финансовая корректность | 3/10 | 9/10 | replay-safe выплаты, точное распределение, fail-closed legacy |
| Конкурентность и recovery | 3/10 | 8/10 | CAS, marker repair, round leases, реальные Mongo-тесты |
| Security boundaries | 5/10 | 7/10 | секреты из кода вынесены; auth/signing требуют следующего milestone |
| Инженерная проверяемость | 6/10 | 9/10 | Python 3.12/3.14, strict typing, 262 теста, Mongo integration CI |

MongoDB гарантирует атомарность одной операции над одним документом, поэтому
проектор строится вокруг conditional update, а не blind read-modify-write.
Междокументная одновременная видимость остаётся отдельной задачей для
replica-set transactions. См. [MongoDB atomicity](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/)
и [transactions](https://www.mongodb.com/docs/manual/core/transactions/).

## Ранжированные находки

### 1. Critical — повторная выплата и неточное распределение airdrop — исправлено

**Почему:** сбой после broadcast, но до записи результата, позволял повторно
отправить актив; float-доли не гарантировали сохранение целого бюджета.

**Исправление:** immutable signed intent сохраняется до broadcast и сверяется
по `operation_id`; неопределённый результат reconciled по txid
(`flex/application/asset_transfers.py:179-298`). Airdrop резервирует неизменяемый
manifest до первой отправки (`flex/tools/airdrop.py:332-405`), а largest-remainder
allocation сохраняет бюджет до последней base unit
(`flex/domain/allocation.py:36-80`).

### 2. Critical — LP double-apply, stale-read race и истёкший lease — исправлено

**Почему:** blind read-modify-write терял обновления; конкурентный replay мог
принять свежий marker за corruption из-за старого snapshot; истёкший worker
мог завершить round.

**Исправление:** per-state CAS cursor, marker-last recovery и повторное чтение
при конкурентном marker (`flex/db/lp_projection.py:53-149`). Завершение round
требует неистёкший lease (`flex/db/sync_coordinator.py:63-100`). Управляемая
гонка на настоящем Mongo доказывает exactly-once delta
(`tests/integration/test_mongo_financial_projection.py:130-155`).

### 3. Critical — LP price manipulation через raw account balance — исправлено

**Почему:** donation или protocol excess на адресе пула мог попасть в
«экономический резерв» и исказить цену.

**Исправление:** legacy worker отделён от обычного price refresh и default-off
через `BACKGROUND_LP_PRICES_UPDATE=false` (`env.py:57-64`,
`api/background.py:243-251`). Включать только после DEX-specific проверки
app state и economic reserves.

### 4. High — staking classifier принимал непроверенные переводы — mitigated

**Почему:** перевод рядом с application call не доказывает stake; без проверки
полной transaction group можно создать ложное состояние.

**Исправление сейчас:** `SYNC_STAKING_POOLS=false`, а попытка включения
завершается fail-closed (`flex/sync_pools.py:351-367`). **Следующий фикс:**
типизированный parser полной Algorand group, проверка app ID, selector,
sender/receiver, asset и group order, затем adversarial fixtures.

### 5. High — browser-visible shared key не является авторизацией — открыто

**Почему:** `X-API-Key` сравнивается корректно, но один общий клиентский token
не подтверждает пользователя и не разделяет права
(`core/auth.py:8-13`, `app.py:323-369`).

**Конкретный фикс:** registration авторизовать wallet-signature challenge с
nonce, expiry и replay table; `/contracts/refresh-cache` оставить только
server-to-server роли с отдельным secret и audit log. До этого считать текущий
token compatibility/rate-control механизмом, не security boundary.

### 6. High — blocking persistence остаётся в async routes — открыто

**Почему:** sync PyMongo/provider вызовы в event loop увеличивают tail latency
всех запросов при деградации Mongo или DEX (`app.py:418-428`,
`app.py:529-535`, `app.py:559-561`).

**Конкретный фикс:** ввести async repository ports с timeout/cancellation;
переходно — `asyncio.to_thread` вокруг целого repository call и
thread-safe cache, плюс saturation/load test.

### 7. High — Mongo invariants раньше проверялись только fake-коллекциями — исправлено

**Почему:** mocks не проверяют BSON numeric comparison, unique-index races,
`$inc` promotion и реальные `find_one_and_update` semantics.

**Исправление:** отдельный digest-pinned MongoDB CI job
(`.github/workflows/ci.yml:84-109`) проверяет concurrent CAS, marker repair,
legacy int64→Decimal128, `uint64` max, fail-closed duplicates и fencing
(`tests/integration/test_mongo_financial_projection.py:130-336`). Стабильный
required context `python` агрегирует matrix и Mongo job
(`.github/workflows/ci.yml:111-126`).

### 8. Medium — mutable stateful Docker images — открыто

**Почему:** `mongo` и `algorand/algod:latest` могут поменять major/runtime при
обычном rebuild поверх persistent volumes (`docker-compose.yml:29-61`).

**Конкретный фикс:** после проверки реального VPS зафиксировать оба образа как
`tag@sha256`, описать backup/restore и downgrade, а CI должен отклонять bare
tags и `latest`. Не подменять production digest без data-format rehearsal.

### 9. Medium — container smoke не запускает production entrypoint — открыто

**Почему:** CI заменяет entrypoint на shell и импортирует `app`, поэтому не
доказывает запуск `scripts/run.sh`, Uvicorn, healthcheck и graceful shutdown
(`.github/workflows/ci.yml:55-70`).

**Конкретный фикс:** поднять disposable Mongo, запустить образ штатно с
безопасными feature flags, дождаться healthy, запросить `/status`, затем
проверить SIGTERM и вывести logs при сбое.

### 10. Medium — contract registration не атомарен по business key — открыто

**Почему:** check-then-insert допускает конкурентные дубликаты, а notification
после записи является незарегистрированным side effect
(`app.py:327-365`, `core/db/contracts.py:16-25`).

**Конкретный фикс:** unique index по contract `id`, atomic upsert с
immutable-field conflict check и transactional outbox для уведомления.

## Milestones

1. **M0 — money safety (готово):** findings 1–3 исправлены; finding 4
   переведён в fail-closed. Добавлены NFT idempotency
   (`api/wallet.py:14-37`), on-chain reconciliation и regressions.
2. **M1 — persistence proof (готово):** finding 7, Python matrix, BSON boundary,
   stable required check. Production остаётся на 3.12; 3.14 — compatibility
   gate. Python 3.14.6 является актуальным maintenance release
   ([Python.org](https://www.python.org/downloads/release/python-3146/)).
3. **M2 — authority and atomic workflows (следующий):** findings 5 и 10.
4. **M3 — runtime hardening:** findings 6, 8 и 9; затем SLO/metrics и controlled
   deploy rehearsal.

## Вклад независимых агентов

- три financial-review потока независимо подтвердили payout/LP классы ошибок;
- adversarial Mongo/BSON review воспроизвёл stale-read race, пропущенный
  первоначальным concurrency-тестом;
- CI/GitHub review обнаружил drift обязательного status context после matrix;
- dependency/container review проверил lock, image posture и runtime smoke;
- docs/API review сравнил публичные обещания с фактическими route shapes и
  cross-project consumer contract.

Форматирование и стиль намеренно не включались в findings: их обеспечивает
Ruff. Приоритет аудита — correctness, security, data integrity и доказуемое
recovery-поведение.
