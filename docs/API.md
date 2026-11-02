# word-Dance — REST API contract

Base path `/api` (media at `/media`, SPA at `/`). JSON in/out, `Content-Type: application/json; charset=utf-8`. This file is the frozen contract between the backend routers (`backend/wd/routers/*`, Pydantic models in `backend/wd/schemas.py`) and the frontend (`frontend/src/api/types.ts` — Section 9 is copied there verbatim). Any change requires updating `schemas.py`, `types.ts` and this file in one commit.

## 1. Conventions

* **Auth column**: `–` public · `U` logged-in user (401 otherwise) · `O` logged-in user with `onboarding_state='done'` (409 `onboarding_required` otherwise; `/api/onboarding/*`, `/api/auth/*`, `/api/account/*`, `/api/settings*`, `/api/screen/*`, `/api/stages`, `/api/vocab*`, `/api/lookup`, `/api/words/*`, `/api/bank*`, `/api/suggestions*` are `U` — browsing, screening and the bank work before onboarding; only 今日/学习/记录 require it, matching FRONTEND §2 and DESIGN §6.2) · `A` admin (403 otherwise).
* **Word visibility** (the single rule, applied by every route that reads `words`: 20, 21, 22, 23, 24, 25, 31, 33, 52, 53 and the screen/today joins): a word is visible to user `:me` iff `is_public = 1 OR created_by_user_id = :me OR EXISTS (SELECT 1 FROM user_words uw WHERE uw.user_id = :me AND uw.word_id = words.id)`; admins see every word. A word that is invisible yields 404 `word_not_found` (never 403) and is absent from lists. Two users who added the same unvalidated string share one `words` row and both see it; a third user does not (DESIGN §5.2).
* **Route order**: FastAPI matches routes in registration order. The lookup preview lives at `GET /api/lookup` (not under `/api/words/`) so it can never collide with `GET /api/words/{id_or_lemma}`; every static sibling path under a dynamic segment (e.g. `POST /api/words/batch-mark`) is registered before the dynamic route, and `{id_or_lemma}` never matches a path containing `/`.
* **Session**: cookie `wd_session` (`HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000` + `Secure` on https). Sliding expiry once per day.
* **CSRF**: every non-GET `/api/*` request must carry `X-WD-Request: 1`; if an `Origin` header is present it must equal **either** the request's own `Host`-derived origin (scheme from `X-Forwarded-Proto` when `WD_TRUST_PROXY=1`, else the connection) **or** the origin of `WD_PUBLIC_URL` when set (`http://localhost:5173` is also accepted when `WD_DEV=1`). Otherwise 403 `csrf_rejected`. No CORS. (Accepting the Host-derived origin keeps a LAN install reachable by IP *and* by hostname even though install.sh writes the LAN URL into `WD_PUBLIC_URL` for delivery links — DEPLOY §4.)
* **Pagination**: `page` (1-based, default 1), `page_size` (default 50, max 100). Response `{"items":[…],"page":1,"page_size":50,"total":4722}`.
* **Idempotency**: all `GET`s are side-effect free (`GET /api/today` never builds). Grades and screening verdicts carry `client_event_id` (UUID v4); a duplicate returns the original outcome with `duplicate:true`.
* **Timestamps** UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ`; local dates `YYYY-MM-DD`.
* **Headers on every response**: `X-Request-Id` (uuid4, also in logs); `Cache-Control: no-store` on all `/api` JSON.
* **Error envelope** (all errors incl. Pydantic validation, which is converted from FastAPI's 422):

```json
{"error":{"code":"invalid_word","message":"只能包含英文字母、空格、连字符、撇号和缩写点","details":{"input":"abc123"}}}
```

### 1.1 Error codes

| code | status | when |
|---|---|---|
| `validation_error` | 400 | body/query fails validation (`details.fields = {field: message}`) |
| `invalid_word` / `too_many_words` | 400 | custom-add validation (§5.1 DESIGN) / > 50 tokens |
| `invalid_grade` | 400 | grade not allowed for the item kind |
| `weak_password` | 400 | < 8 chars, = username, or in the common-password list |
| `invalid_code` | 400 | e-mail code wrong/expired (`details.attempts_left`) |
| `unauthorized` | 401 | no/expired session |
| `invalid_credentials` | 401 | login failed (same message for unknown user) |
| `forbidden` | 403 | not admin / not owner |
| `account_disabled` | 403 | `users.is_active=0` |
| `registration_closed` / `invalid_invite` | 403 | registration policy |
| `csrf_rejected` | 403 | missing `X-WD-Request` or Origin mismatch |
| `not_found` / `word_not_found` / `batch_not_found` | 404 | — (foreign ids also yield 404, never 403) |
| `method_not_allowed` | 405 | wrong HTTP method on an existing route (transport-level: Starlette's `HTTPException` is mapped through `errors._STATUS_TO_CODE`; a mutation still passes the CSRF check first, so without `X-WD-Request` it is 403 `csrf_rejected`) |
| `username_taken` / `email_taken` | 409 | uniqueness |
| `onboarding_required` | 409 | `O` endpoint before onboarding is done |
| `invalid_transition` | 409 | state machine refuses the action (`details.from`, `details.action`); also returned when grading a stale push item (its `user_words` row left `new`/`learning`, its word was merged, or a screen word already has a `user_words` row — DESIGN §6.3); by `PATCH /api/bank/{id} {attention:'retry'}` when the word is already validated (`is_valid_english IS NOT NULL`); and by `POST /api/onboarding/complete` while `onboarding_state='pending'` (step 1 not done) |
| `item_already_graded` | 409 | a *different* event grades an item whose `result IS NOT NULL` (a **final** grade was stored — DESIGN §7; an item in the 10-minute step has `result NULL` and is gradable again) |
| `batch_not_ready` | 409 | `/today/more` when no batch exists yet for the user's current local date (「请先生成今日词汇」); a `building` batch accepts `/more` |
| `ambiguous_form` | 409 | `GET /api/words/{lemma}` where the path is an inflected form mapping to several headwords (`details.candidates: WordBrief[]`); bulk add reports this per item as `status:"ambiguous"` instead |
| `budget_exhausted` | 409 | explicit content request while the daily AI cap is hit (`details.resumes_at`) |
| `email_not_verified` / `smtp_unconfigured` / `webhook_unconfigured` | 409 | channel prerequisites |
| `already_resolved` / `undo_expired` | 409 | suggestions; `undo_expired` is also returned by `mark {action:"restore"}` when the word has no eligible `master`/`known`/∅→`unfamiliar` log row by this user within the last 15 minutes (endpoint 26) |
| `import_too_large` | 400 | `POST /api/bank/import` with more than 2,000 rows or an unparsable file (`details.rows`) |
| `last_admin` | 409 | disabling/demoting/deleting the last active admin |
| `payload_too_large` | 413 | request body larger than `WD_MAX_BODY_BYTES` (rejected from `Content-Length` before the body is read, or while streaming it; `details.max_bytes`) |
| `account_locked` | 423 | login lockout (`details.retry_after_s`) |
| `rate_limited` | 429 | throttle (`Retry-After` header, `details.retry_after_s`) |
| `ai_disabled` | 503 | admin AI action while `WD_AI_ENABLED=0` / paused |
| `email_send_failed` | 503 | `POST /api/account/email/request-code` when the SMTP server refused or could not be reached (the code is not issued; retry later) |
| `internal_error` | 500 | unexpected; logged with request id |

## 2. Endpoint catalogue

| # | Method | Path | Auth | Purpose |
|---|---|---|---|---|
| 1 | GET | `/api/health` | – | liveness + public flags |
| 2 | POST | `/api/auth/register` | – | create account (+settings), auto-login |
| 3 | POST | `/api/auth/login` | – | set session cookie |
| 4 | POST | `/api/auth/logout` | U | delete session |
| 5 | GET | `/api/auth/me` | U | current user, settings, server flags |
| 6 | PUT | `/api/account` | U | display name / e-mail |
| 7 | POST | `/api/account/password` | U | change password (revokes other sessions) |
| 8 | DELETE | `/api/account` | U | delete account (cascade) |
| 9 | POST | `/api/account/email/request-code` | U | send 6-digit verification code |
| 10 | POST | `/api/account/email/verify` | U | verify e-mail |
| 11 | GET | `/api/account/export` | U | export bank + history (csv/json) |
| 12 | POST | `/api/onboarding` | U | save stage choice, push time, timezone |
| 13 | POST | `/api/onboarding/complete` | U | finish onboarding |
| 14 | GET | `/api/settings` | U | settings |
| 15 | PUT | `/api/settings` | U | partial update |
| 16 | GET | `/api/settings/timezones` | U | timezone list |
| 17 | POST | `/api/settings/webhook/test` | U | send a test webhook now |
| 18 | POST | `/api/settings/email/test` | U | queue a test e-mail |
| 19 | GET | `/api/stages` | U | stage totals + my progress |
| 20 | GET | `/api/vocab` | U | browse 全部/stage vocabulary |
| 21 | GET | `/api/vocab/letters` | U | A–Z counts for the current filter |
| 22 | GET | `/api/lookup` | U | live preview for 添加生词 (deliberately outside `/api/words/` — see Route order) |
| 23 | GET | `/api/words/{id_or_lemma}` | U | word detail |
| 24 | GET | `/api/words/{id}/content` | U | content + state (polled) |
| 25 | GET | `/api/words/{id}/image` | U | image metadata |
| 26 | POST | `/api/words/{id}/mark` | U | state transition |
| 27 | POST | `/api/words/batch-mark` | U | bulk 不熟悉/认识 (≤ 100) |
| 28 | POST | `/api/words/{id}/report` | U | report content/image/dictionary |
| 29 | POST | `/api/words/{id}/image/refresh` | U | 换一张 |
| 30 | POST | `/api/words/{id}/content/request` | U | ask for examples now |
| 31 | GET | `/api/screen/next` | U | screening candidates |
| 32 | POST | `/api/screen/verdict` | U | 认识 / 不熟悉 / 跳过 (筛词 page) |
| 33 | GET | `/api/bank` | U | my bank |
| 34 | POST | `/api/bank/add` | U | bulk add custom words (text) |
| 35 | POST | `/api/bank/add-word` | U | add one resolved word by id |
| 36 | PATCH | `/api/bank/{word_id}` | U | update note / resolve a 待处理 flag (保留 · 重试) |
| 37 | POST | `/api/bank/{word_id}/accept-suggestion` | U | replace a flagged word with the suggested correction |
| 38 | POST | `/api/bank/consolidate` | U | run 整理 now |
| 39 | GET | `/api/suggestions` | U | 整理建议 inbox |
| 40 | POST | `/api/suggestions/{id}/accept` | U | apply |
| 41 | POST | `/api/suggestions/{id}/reject` | U | dismiss |
| 42 | POST | `/api/suggestions/{id}/undo` | U | undo an auto-applied change (7 days) |
| 43 | GET | `/api/today` | O | today's batch (no side effects) |
| 44 | POST | `/api/today/build` | O | build today's batch now (idempotent) |
| 45 | POST | `/api/today/items/{item_id}/grade` | O | grade a card / screen verdict inside the batch |
| 46 | POST | `/api/today/more` | O | 再来一组 |
| 47 | POST | `/api/today/complete` | O | session summary, marks completion |
| 48 | GET | `/api/history` | O | per-day aggregates |
| 49 | GET | `/api/history/batches` | O | past batches |
| 50 | GET | `/api/batches/{id}` | O | one past batch (read-only) |
| 51 | GET | `/api/stats` | O | bank counts, stage progress, streak |
| 52 | GET | `/media/images/{path}` | U | cached photo / sanitised SVG |
| 53 | GET | `/media/card/{word_id}.svg` | U | template card (always available) |
| 54 | GET | `/api/admin/overview` | A | counts, spend, queue, quotas |
| 55 | GET | `/api/admin/health` | A | detailed health |
| 56 | GET | `/api/admin/users` | A | users |
| 57 | POST | `/api/admin/users/{id}` | A | activate/role/reset password |
| 58 | GET | `/api/admin/invites` | A | invite codes (hashed; metadata only) |
| 59 | POST | `/api/admin/invites` | A | create invite (code shown once) |
| 60 | GET | `/api/admin/jobs` | A | jobs |
| 61 | POST | `/api/admin/jobs/{id}/retry` | A | requeue one |
| 62 | POST | `/api/admin/jobs/requeue-dead` | A | requeue all dead |
| 63 | POST | `/api/admin/jobs/run-once` | A (dev only) | drain the queue synchronously |
| 64 | GET | `/api/admin/ai/calls` | A | ledger |
| 65 | POST | `/api/admin/ai/pause` | A | pause/resume AI |
| 66 | POST | `/api/admin/ai/probe` | A | `claude` probe (≤ $0.05) |
| 67 | POST | `/api/admin/content/prewarm` | A | budgeted pre-generation |
| 68 | POST | `/api/admin/words/{id}/regenerate` | A | new content version |
| 69 | POST | `/api/admin/words/{id}/refetch-image` | A | new image |
| 70 | GET | `/api/admin/reports` | A | content reports |
| 71 | POST | `/api/admin/reports/{id}` | A | resolve/dismiss |
| 72 | GET | `/api/admin/events` | A | system events |
| 73 | GET | `/api/admin/config` | A | effective config (secrets masked) |
| 74 | POST | `/api/admin/push/run` | A | build + publish a user's batch now |
| 75 | POST | `/api/bank/import` | U | import a previous `GET /api/account/export` file (csv/json) into my bank |

## 3. Health, auth, account, onboarding

**1 `GET /api/health`** → `200 {status:"ok", version:"0.1.0", registration_mode:"invite"|"open"|"closed", needs_setup: boolean, time:"…Z"}`; `503 {status:"degraded"}` if the DB is unreachable. `needs_setup` is `true` while the `users` table is empty (no admin exists yet); the login/register pages use it (FRONTEND §2). Implemented in Phase 0 (`routers/health.py` needs only `db` + `config`; TASKS P0), so P0's own `curl /api/health` acceptance is satisfiable.

**2 `POST /api/auth/register`** — body `{username: string, password: string, display_name?: string, email?: string, invite_code?: string}`. `username` 2–32 chars `^[A-Za-z0-9_一-龥]+$`; `password` 8–64 chars; `display_name` ≤ 32. → `201 {user: User, settings: Settings}` + cookie. The `user_settings` row is inserted in the same transaction as the user **with `next_push_at = clock.compute_next_push(now, 'Asia/Shanghai', '08:00')`** computed from the default settings — a freshly registered user is never left with `next_push_at NULL` (the scheduler selects users by `next_push_at <= …`, DESIGN §6.4); onboarding and `PUT /api/settings` recompute it. **Bootstrap rule**: inside one `BEGIN IMMEDIATE` the server checks `SELECT COUNT(*) FROM users`; when it is 0 the registration is accepted **regardless of `WD_REGISTRATION_MODE` and without an invite code**, and that user becomes `admin` (the first user ever is always admin). Every later registration follows the mode: `open` → no code; `invite` → a valid code is consumed atomically; `closed` → 403 `registration_closed`. Errors: 400 `validation_error`/`weak_password`, 403 `registration_closed`/`invalid_invite`, 409 `username_taken`/`email_taken`, 429 (5/h per IP).

**3 `POST /api/auth/login`** — `{username: string, password: string}` → `200 {user, settings}` + `Set-Cookie`. 401 `invalid_credentials`, 403 `account_disabled`, 423 `account_locked`, 429. A new session is created (no fixation).

**4 `POST /api/auth/logout`** → 204, cookie cleared. **5 `GET /api/auth/me`** → `200 {user: User, settings: Settings, server: ServerFlags, counters: Counters}` — `counters.suggestions_open` = my `bank_suggestions` with `status='open'`, `counters.attention` = my bank rows with `needs_attention=1`; these feed the tab-bar badges (FRONTEND §2) so no page needs an extra poll. The client refreshes `counters` after accept/reject/undo of a suggestion and after bank adds.

**6 `PUT /api/account`** — `{display_name?: string|null, email?: string|null}` → `{user}`; changing `email` clears `email_verified_at` and disables `email_enabled`. 409 `email_taken`.
**7 `POST /api/account/password`** — `{current_password, new_password}` → 204; all other sessions deleted. 401 `invalid_credentials`, 400 `weak_password`.
**8 `DELETE /api/account`** — `{password}` → 204 (cascade deletes every row of the user). A private word (`is_public=0`) created by this user is deleted only when **no other user's `user_words` row references it** (checked after the cascade, inside the same transaction); otherwise it is kept with `created_by_user_id=NULL` (the remaining holders still see it through the visibility rule). 401, 409 `last_admin`.
**9 `POST /api/account/email/request-code`** → `202 {sent: true, expires_in_s: 900}` (3/h per user; 409 `smtp_unconfigured` if no SMTP; 400 if no e-mail on the account; 503 `email_send_failed` when the SMTP server refused or could not be reached — no code is issued).
**10 `POST /api/account/email/verify`** — `{code: "123456"}` → `{user}` (`email_verified` true). 400 `invalid_code` (5 attempts per code).
**11 `GET /api/account/export?format=csv|json`** → file `word-dance-export-YYYYMMDD.csv|json`. CSV: one row per `user_words` row with columns `word, phonetic, translation, state, origin, note, times_added, added_at, mastered_at, ease, interval_days, repetitions, lapses, due_at`. JSON: `{"version": 1, "exported_at": "…Z", "username": "…", "words": [ {the same 14 fields} ], "review_logs": [ {created_at, word, action, context, prev_state, new_state, prev_interval, new_interval} ] }` — `review_logs` holds the last 365 days (tens of thousands of rows for an active user, several MB). **Only `words` is re-importable**: the client sends `JSON.stringify({version, words})` to endpoint 75 and the server ignores a `review_logs` key if present, so a faithful round trip of a real export never hits the 1 MB body cap (≤ 2,000 bank rows ≈ 500 KB). The CSV export has no history and round-trips as is.

**12 `POST /api/onboarding`** — `{stages: Stage[] (non-empty), current_stage: Stage, timezone: string, push_time: "HH:MM"}` → `{settings: Settings, onboarding_state: "screen"}`. Allowed while `onboarding_state != 'done'` (re-posting overwrites). The server validates `current_stage ∈ stages`. `current_stage` is the `Stage` **string** on the wire everywhere (here, endpoint 15 and `Settings`); the server maps it to the 1–4 column index (§9.1).
**13 `POST /api/onboarding/complete`** → `{onboarding_state: "done"}`. Precondition: `onboarding_state = 'screen'` (step 1 saved — so `next_push_at`, stages and timezone are the user's own); `'done'` → 200 unchanged (idempotent); `'pending'` → 409 `invalid_transition` (`details.from:'pending'`). There is no path to `done` that skips step 1.

## 4. Settings

**14 `GET /api/settings`** → `Settings`. **15 `PUT /api/settings`** — any subset of the writable fields of `Settings` → full `Settings`. Validation: `timezone ∈ zoneinfo.available_timezones()`; `push_time` `^([01]\d|2[0-3]):[0-5]\d$`; counts within the CHECK ranges; `stages` non-empty ⊆ {zk,gk,cet4,cet6} and `current_stage ∈ stages`; `webhook_url` https + public host (SSRF host check) required when `webhook_enabled`; `email_enabled=true` requires `email_verified` (409 `email_not_verified`) and server SMTP (409 `smtp_unconfigured`). Saving recomputes `next_push_at`.
**16 `GET /api/settings/timezones?all=0|1`** → `{items: string[]}` — curated 30 (Asia/Shanghai first) or all zones.
**17 `POST /api/settings/webhook/test`** → `200 {ok: boolean, http_status: number|null, error: string|null}` — sends the configured format with a test text synchronously (10 s timeout). 409 `webhook_unconfigured`, 429 (1 per 10 min).
**18 `POST /api/settings/email/test`** → `202 {queued: true}`. Enqueues `send_email {"user_id": <me>, "test": true}` (no `batch_id`; dedupe key `email:test:<user_id>`, priority 10). The rendered test mail: subject `【word-Dance】测试邮件`, body 「这是一封测试邮件。你的下次推送时间：10月15日 08:00（Asia/Shanghai）」 + the public URL link (DESIGN §6.5; omitted when none is known); `push_batches.email_status` is untouched. 409 `email_not_verified`/`smtp_unconfigured`, 429 (1 per 10 min).

## 5. Vocabulary, words, screening

**19 `GET /api/stages`** → `{items: StageInfo[]}` (4 rows, totals from `words` where `is_public=1 AND merged_into_word_id IS NULL`; progress joins `user_words`).

**20 `GET /api/vocab`** — query: `stage=all|zk|gk|cet4|cet6` (default `all`), `new_only=0|1` (only with a specific stage: words whose lowest stage is that stage, i.e. `stage_min = idx`; for cet6 this is the 3,694-word CET-6 increment), `q` (≤ 64; ASCII → prefix match on `lemma` via `lemma >= :q AND lemma < :q||'~'` **plus** `word_forms.form` prefix so `abandoned` finds `abandon`; CJK → `translation LIKE '%q%' ESCAPE '\'`), `status=all|unmarked|unfamiliar|known|mastered` (`unfamiliar` = new+learning), `sort=freq|alpha|difficulty` (default `freq`: `ORDER BY (frq IS NULL OR frq=0), frq, lemma`; `alpha`: `ORDER BY lemma`; `difficulty`: `ORDER BY COALESCE(difficulty, stage_min, 5), (frq IS NULL OR frq=0), frq, lemma` — `words.difficulty` is NULL for seed words until Claude content/consolidation fills it, so the stage index stands in and the order is always deterministic), `letter=a..z`, `page`, `page_size` → `Page<WordBrief>`. Visibility: the §1 rule `AND merged_into_word_id IS NULL`. **Browsing never enqueues jobs.**
**21 `GET /api/vocab/letters`** — same filters minus `letter`/`q` → `{items: [{letter: "a", count: 412}, …]}`.

**22 `GET /api/lookup?q=`** → `LookupPreview`: normalisation result, `via ∈ exact|form|ambiguous|ecdict|none|invalid`, the matched word, `candidates` for ambiguous forms, `suggestions` (≤ 5 prefix matches on `lemma`), `mine` (my bank row if any). Matches and suggestions obey the §1 visibility rule. No rows are created.

**23 `GET /api/words/{id_or_lemma}`** — numeric → by id; else `lemma = normalise(path)`: exact lemma match, otherwise a `word_forms` match (unique → the headword with `redirected_from` set; several → 409 `ambiguous_form` with `details.candidates: WordBrief[]`, rendered by FRONTEND §5.8 as candidate chips); follows `merged_into_word_id` (`redirected_from`). → `WordDetail`. 404 `word_not_found` for words outside the §1 visibility rule.
**24 `GET /api/words/{id}/content`** → `{state: ContentState, content: Content|null, eta_s: number|null, deferred_until: string|null}` — `eta_s` is a rough estimate from queue position × 30 s and is `null` whenever `deferred_until` is set. `deferred_until` = the live `generate_content` job's `run_after` when it lies more than 5 minutes in the future (budget/monthly deferral, CLAUDE_INTEGRATION §7) or when AI is disabled/paused (then = `kv.claude.paused_until`, or `null` state with `eta_s null` if the kill switch is off entirely — the client treats `state:'queued', eta_s:null, deferred_until:null` like a deferral too); otherwise `null`. Clients poll every 5 s while `queued` **and** `deferred_until` is null (max 24 polls); a non-null `deferred_until` stops polling and shows 「今日 AI 额度已用完，例句将在明天补齐」 (FRONTEND §5.1.5). The same value is carried as `content_deferred_until` on `StudyItem` and `WordDetail`. §1 visibility rule (404 otherwise).
**25 `GET /api/words/{id}/image`** → `ImageMeta` (always 200 for a visible word: falls back to the card). §1 visibility rule.

**26 `POST /api/words/{id}/mark`** — `{action: "unfamiliar"|"known"|"mastered"|"remove"|"reset"|"restore", note?: string, context?: "browse"|"detail"|"bank"|"today"|"screen_page"}` → `{word_id, state: UserState|null, mine: UserWord|null, status: "added"|"readded"|"exists"|"noop"|"restored"}` (`state`/`mine` are `null` only after a `restore` that deleted a ∅-origin row). `context` defaults to `'api'` when omitted and determines `user_words.origin` for a row created by this call through the DESIGN §4 mapping table (`browse`/`detail` → origin `browse`; `today` → `push`; `screen_page` → `screen`; `bank`/`api` → `browse`). 409 `invalid_transition`; 404 `word_not_found` (ids are explicit, so no ambiguity is possible here). `restore` is the **undo** of the user's most recent transition on the word when that transition is undoable and younger than **15 minutes** (the 8-second 撤销 toast on cards, the 5-second 撤销 toasts of 词库 rows and 筛词 verdicts); the eligible log rows and their effects, all of which also log `action='restore'` and expire nothing:
  * `master` / `known` (incl. a `known` that was the mastered-synonym, `new_state='mastered'`): writes the `prev_srs_json` snapshot back verbatim (state, ease, interval_days, step, repetitions, lapses, consecutive_good, due_at, last_graded_at, mastered_at — `times_added`, `priority` and `ease` are **not** changed); a ∅-origin `known` row is deleted; clears `result`/`graded_at` on the push item that produced the transition (the card or 推荐词 becomes gradable again); `daily_stats`: `mastered-1` when `new_state` was `mastered` (and `graded-1` when it was a study-card `master` grade), `known-1` when `new_state` was `known`, `screened-1` when the undone row was a screening verdict (context `screen_page`/`onboarding`, or a `kind='screen'` push item).
  * `unfamiliar` with `prev_state IS NULL` (a ∅ → `new` row that has not been graded since: `repetitions = 0`, state still `new`): deletes the row again (the word becomes a 推荐词 candidate once more), clears `result`/`graded_at` on the screen push item that produced it, deletes an ungraded `kind='new'` row appended for the word in an open batch (`append_to_today` second row), `daily_stats.added-1` (and `screened-1` for a screening verdict); the `generate_content` job, if any, is left alone (content is global). An idempotent `unfamiliar` (`status:"exists"`, `prev_state` not NULL) and a `readd` are **not** undoable this way.
  * anything else, or older than 15 minutes → 409 `undo_expired`. A deliberate re-add from the 已掌握 list is `unfamiliar` (re-add semantics, DESIGN §4), never `restore`.
**27 `POST /api/words/batch-mark`** — `{items: [{word_id, action: "unfamiliar"|"known"}]}` (≤ 100) → `{updated: n, results: [{word_id, ok: boolean, state: UserState|null, error: string|null}]}`.
**28 `POST /api/words/{id}/report`** — `{target: "content"|"image"|"dictionary", reason: ReportReason, note?: string(≤300)}` → `201 {id}`. `target:"image"` marks the active image `rejected` and enqueues `fetch_image` (priority 10, excluding it). 20/day/user.
**29 `POST /api/words/{id}/image/refresh`** → `202 {job_id, image_state: "queued"}`; enqueues `fetch_image` with `exclude` = current active `provider_ref`/`sha256` list (priority 10). 20/day/user.
**30 `POST /api/words/{id}/content/request`** → `202 {job_id: number|null, state: ContentState}` (no-op 200 when already `ready`/`queued`); 409 `budget_exhausted {resumes_at}`; 503 `ai_disabled`; 409 `invalid_transition` for a provisional word (`is_valid_english IS NULL` — content is generated only after `lookup_word` validates it, DESIGN §4); 60/day/user. UI trigger: the 「生成例句」 button on the word detail page and on a study card whose `content_state ∈ {none, failed}` (FRONTEND §5.1, §5.8).

**31 `GET /api/screen/next?stage=zk|gk|cet4|cet6|auto&count=1..50`** → `{items: ScreenWord[], remaining: number}` — unseen stage words (`is_public=1 AND is_valid_english=1 AND merged_into_word_id IS NULL`, no `user_words` row for me), ordered as in DESIGN §6.3 step 4 (`auto` = the user's `stages` with `current_stage` first), by frequency; `remaining` = total unseen for the filter. No side effects.
**32 `POST /api/screen/verdict`** — `{client_event_id: uuid, word_id, verdict: "known"|"unfamiliar"|"skip", context?: "screen_page"|"onboarding"}` → `ScreenResponse`. `unfamiliar` → bank row `new` (origin `screen`); when today's batch exists, has new-quota room (`new_done + new_remaining < daily_new_count`) and the word has no `review`/`new`/`extra` row in it yet, `append_to_today(kind='new')` adds a study row (a `screen` row for the same word may coexist — `UNIQUE(batch_id, word_id, kind)`) → `added_to_today:true`, `study_item` = that new `StudyItem`; otherwise `added_to_today:false`, `study_item:null` (toast 「已加入生词库，明天开始学」). `known` → `known`; `skip` → nothing stored except the log. Duplicate `client_event_id` → stored response with `duplicate:true`.

## 6. Bank and suggestions

**33 `GET /api/bank`** — `state=active|new|learning|mastered|known|removed|attention` (default `active` = new+learning), `q` (prefix on lemma / LIKE on translation), `sort=added|due|alpha|ease|times_added` (default `added` desc), `origin?`, `page`, `page_size` → `BankResponse`. Every listed word is visible to me by construction (my own `user_words` row — §1 rule), so detail/content/card for a bank entry never 404.
**34 `POST /api/bank/add`** — `{text: string(≤ 4000), note?: string(≤ 500), study_today?: boolean}` → `200 AddResponse`. Splitting and statuses per DESIGN §5.3; `ambiguous` items carry `candidates`. 400 `too_many_words` (> 50 tokens); 429 (200/day).
**35 `POST /api/bank/add-word`** — `{word_id, note?, study_today?}` → `201 AddResult` (`added`/`readded`) or `200` (`exists`). Used after an ambiguous preview or a lookup preview. 404 `word_not_found`.
**36 `PATCH /api/bank/{word_id}`** — `{note?: string|null, attention?: "keep"|"retry"}` (at least one key) → `UserWord`. `note` updates the private 备注 (log `note`). `attention` resolves a 待处理 flag (DESIGN §5.4, CLAUDE_INTEGRATION §6.5; log `attention`, `result_json={"decision":…}`):
  * `retry` (保留并重试 for 「暂时无法校验」): allowed only while `words.is_valid_english IS NULL`, else 409 `invalid_transition`; re-enqueues `lookup_word {"word_id"}` (dedupe `lookup:<word_id>`, priority 10, `run_after = now` — the UPSERT means exactly one live job exists even if several holders retry), sets `attention_msg = NULL` and keeps `needs_attention = 1` until the job resolves (badge 重新校验中); the lookup handler clears the flag or re-flags as in §6.5.
  * `keep` (保留): sets `needs_attention = 0, attention_msg = NULL, suggested_word_id = NULL`; `counters.attention` drops. For a word with `is_valid_english = 0` this means **仅收藏，不推送**: the row stays in the bank list (badge 仅收藏, derived client-side from `word.is_valid_english === false`) but DESIGN §6.3 step 3 keeps it out of every batch and no content is ever generated for it. `keep` on a row with `needs_attention = 0` → 200 `noop`.
  * 修改 (the third button) is **client-side**: `mark {action:'remove'}` on the flagged word, then navigate to `/bank/add?prefill=<input_text>`; 删除 is `mark {action:'remove'}`; 替换 is endpoint 37.
**37 `POST /api/bank/{word_id}/accept-suggestion`** → `{removed_word_id, mine: UserWord}` — marks `suggested_word_id` unfamiliar (origin `custom`, note copied) and sets the flagged entry to `removed`. 409 `invalid_transition` if no suggestion.
**38 `POST /api/bank/consolidate`** → `202 {job_id}`; 429 if a run happened in the last 60 min; 503 `ai_disabled`.
**75 `POST /api/bank/import`** — `{format: "csv"|"json", data: string}` (`csv`: the CSV file of endpoint 11 verbatim; `json`: `JSON.stringify({version, words})` — the client drops the export's `review_logs` array before posting and the server ignores that key if it is present; ≤ 1 MB body (`WD_MAX_BODY_BYTES`), ≤ 2,000 rows, else 400 `import_too_large`) → `200 ImportResponse`. Each row is resolved like a custom add (`services.words.resolve` on the `word` column; `invalid`/`ambiguous`/`pending_ai` statuses as in `AddResult`; provisional words get `lookup_word` enqueued) with `origin='import'`, `note` and `times_added` copied, `input_text = word`; rows whose exported `state` is `new`/`learning` enter the bank (`learning` rows restore `ease, interval_days, repetitions, lapses, due_at` when present and valid, else start as `new`); `mastered`/`known`/`removed` rows are recorded in that state so re-add detection and history work; an existing `user_words` row for the word is never overwritten (`status:"exists"`). One `review_logs(action='import', context='api')` row per imported row; counts in `daily_stats.added`. 429 under the custom-add throttle (counts as 200 adds/day). UI: Settings → 账号 → 导入数据 (FRONTEND §5.8).

**39 `GET /api/suggestions?status=open|all`** → `{items: Suggestion[], open_count: number}` (`all` includes `auto` within the 7-day undo window, `accepted`, `rejected`, `expired`).
**40 `POST /api/suggestions/{id}/accept`** → `{result: SuggestionResult}` — applies per CLAUDE_INTEGRATION.md §6.4. 409 `already_resolved`.
**41 `POST /api/suggestions/{id}/reject`** → `200 {}`.
**42 `POST /api/suggestions/{id}/undo`** → `{result}` — only `status='auto'` within `expires_at`; 409 `undo_expired`/`already_resolved`.

## 7. Today, history, stats

**43 `GET /api/today`** → `TodayResponse`. When no batch exists for the user's current local date: `status:"none"`, `batch:null`, `can_build_now:true`. **No side effects.** **Stale items** (DESIGN §6.3; a batch may be built up to 3 h before study and state can change in between): an ungraded `review`/`new`/`extra` item whose `user_words.state` is no longer `new`/`learning`, an ungraded `screen` item whose word now has a `user_words` row, and any item whose word has `merged_into_word_id IS NOT NULL` are **omitted from `items` and from every `counts` field**; graded items always stay (they are history). "Graded" everywhere in `counts` means `push_items.result IS NOT NULL` — an item in the 10-minute learning step (intermediate grade, DESIGN §7) is **not** done. `counts.pending_content` counts non-stale items with `content_state='queued'` whose live content job is runnable today (`run_after ≤ day_start(local_date+1)` and AI not disabled/paused) — deferred items are excluded so the header never says 「例句生成中」 when nothing is generating. `previous_open_batch` = `{id, local_date, remaining}` for **yesterday's** batch (the user's previous local date) when it still has ungraded, non-stale `review`/`new`/`extra` items (`remaining` = their count), else `null`; the 今日 page renders 「继续昨天的学习（还剩 N 个）」 from it and `/study?batch=<id>` grades it through endpoint 45 (FRONTEND §5.3). `suggestions_open` carries the 整理建议 badge count.
**44 `POST /api/today/build`** → `200 TodayResponse` (`trigger:"manual"`); returns the existing batch unchanged if present (idempotent, `BEGIN IMMEDIATE`, `UNIQUE(user_id, local_date)`).
**45 `POST /api/today/items/{item_id}/grade`** — `{client_event_id: uuid, grade: Grade|ScreenVerdict, elapsed_ms?: number}`. Allowed: `review|new|extra` → `again|hard|good|master|skip`; `screen` → `known|unfamiliar|skip`. → `GradeResponse`. **Final vs intermediate grades (DESIGN §7)**: a grade is *final* iff it is `master`, a screen verdict `known`/`unfamiliar`, or an `again`/`hard`/`good` that leaves `user_words.step = 0` (graduation or review); only a final grade writes `push_items.result`/`graded_at` (`GradeResponse.item.result` non-null, `requeue_at` null). An *intermediate* grade — the card enters or repeats the 10-minute step (`again` always; `good` on a card's first exposure; `hard` on a `new`/step card) — applies the SRS, writes `review_logs` and `daily_stats`, returns `item.result:null` and `item.requeue_at`, and leaves the item ungraded, so the **same item is graded again later in the session with a new `client_event_id` and that call returns 200**, not 409. 400 `invalid_grade`; 409 `item_already_graded` only when a *different* event grades an item whose `result IS NOT NULL` (`skip` exempt); 409 `invalid_transition` for a stale item (see 43); duplicate event → stored response, `duplicate:true`. A `screen` item graded `unfamiliar` follows endpoint 32's rule: when quota allows, a `kind='new'` study row for the same word is appended and returned as `GradeResponse.study_item` (the client inserts it into the local queue), else `study_item:null` and `next_due_zh:'明天'`. Items belong to today's or yesterday's batch (finishing a late session — reached from 「继续昨天的学习」 on 今日, endpoint 43 `previous_open_batch`), else 404 (`batch_not_found`; a `Batch` with `gradable:false` is replay-only).
**46 `POST /api/today/more`** — `{source: "new"|"screen", count?: 1..20 (default 10)}` → `TodayResponse` with appended `extra` (source new: more bank `new` words — words that already have a `review`/`new`/`extra` row in the batch are skipped, a word present only as `screen` is eligible; source screen: more 推荐词 as `kind='screen'`). Works on **any** existing batch for today (`building`, `ready` or `published` — appending never waits for content, and with AI paused a batch may legitimately stay `building`); 409 `batch_not_ready` only when no batch exists yet for today (the client offers 立即生成); 429 after 3 rounds; `200` with no new items when nothing is available (`added:0`).
**47 `POST /api/today/complete`** → `{summary: SessionSummary}`; sets `completed_at` when every non-stale non-screen item has `result IS NOT NULL` (an item still in the 10-minute step keeps the batch open); idempotent.

**48 `GET /api/history?from=YYYY-MM-DD&to=YYYY-MM-DD`** (≤ 370 days) → `{days: DayStats[], streak_days: number, longest_streak: number}`.
**49 `GET /api/history/batches?page`** → `Page<BatchSummary>`. **50 `GET /api/batches/{id}`** → `TodayResponse` for that batch (404 if not mine). `batch.gradable` is `true` for today's batch and for yesterday's batch while it has ungraded items (endpoint 45 accepts their grades); `false` for every older batch (replay only — the client hides the grade bar).
**51 `GET /api/stats`** → `Stats`.

## 8. Media and admin

**52 `GET /media/images/{path}`** — `path` must match `^[0-9a-f]{2}/[0-9a-f]{64}\.(jpg|svg)$` else 404; `Cache-Control: private, max-age=31536000, immutable`, `X-Content-Type-Options: nosniff`, for SVG also `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'`. Session cookie required.
**53 `GET /media/card/{word_id}.svg`** — deterministic template card rendered from DB (LRU-cached by `(word_id, active_content_id)`); `Cache-Control: private, max-age=86400`; same SVG headers. 404 for words outside the §1 visibility rule (a word in my bank is always visible).

**54 `GET /api/admin/overview`** → `AdminOverview` (`words.with_photo` / `with_claude_svg` / `card_only` make the photo hit rate visible: `card_only` = words with content but no active image). **55 `GET /api/admin/health`** → `AdminHealth`.
**56 `GET /api/admin/users?q&page`** → `Page<AdminUser>`. **57 `POST /api/admin/users/{id}`** — `{is_active?: boolean, role?: "user"|"admin", new_password?: string}` → `AdminUser`; 409 `last_admin`.
**58 `GET /api/admin/invites`** → `{items: [{id, max_uses, uses, expires_at, note, created_at, created_by}]}`. **59 `POST /api/admin/invites`** — `{max_uses?: 1..100, expires_in_days?: 1..365, note?: string}` → `201 {id, code (shown once), expires_at}`.
**60 `GET /api/admin/jobs?status&type&page`** → `Page<Job>`. **61 `POST /api/admin/jobs/{id}/retry`** → `Job` (queued, attempts 0, run_after now). **62 `POST /api/admin/jobs/requeue-dead`** → `{requeued: n}`. **63 `POST /api/admin/jobs/run-once`** (only when `WD_DEV=1`; 403 `forbidden` otherwise — the admin page shows the button only while `ServerFlags.dev`) → `{processed: n}` — runs claude/io handlers synchronously until the queue is empty.
**64 `GET /api/admin/ai/calls?page`** → `Page<AiCall> & {today_usd, month_usd, avg_cost_per_word_7d}`. **65 `POST /api/admin/ai/pause`** — `{paused: boolean}` → `{paused, paused_until: string|null}`. **66 `POST /api/admin/ai/probe`** → `{ok: boolean, flag_tier: 0|1, cost_usd, duration_ms, model_used, error: string|null}` (1/min).
**67 `POST /api/admin/content/prewarm`** — `{stage: "zk"|"gk"|"cet4"|"cet6"|"all", limit: 1..2000, max_budget_usd: 0.1..50}` → `202 {job_id, planned: n}` (priority 90; Wikimedia-only images; stops when its own spend reaches the budget). 503 `ai_disabled`.
**68 `POST /api/admin/words/{id}/regenerate`** → `202 {job_id}` (new content version, priority 10). **69 `POST /api/admin/words/{id}/refetch-image`** — `{provider?: "wikimedia"|"openverse"|"pixabay"|"pexels"|"claude_svg", query?: string}` → `202 {job_id}`.
**70 `GET /api/admin/reports?status=open|resolved|dismissed`** → `Page<Report>`. **71 `POST /api/admin/reports/{id}`** — `{status: "resolved"|"dismissed", regenerate?: boolean, refetch_image?: boolean}` → `Report`.
**72 `GET /api/admin/events?page`** → `Page<SystemEvent>`. **73 `GET /api/admin/config`** → `{entries: [{key, value, source: "env"|"default"}]}` with secrets masked as `"***"`.
**74 `POST /api/admin/push/run`** — `{user_id}` → `{batch_id, status}` — builds (if missing) with `trigger:"admin"` and publishes immediately (deliveries enqueued).

## 9. Shared TypeScript DTOs (`frontend/src/api/types.ts`, frozen in Phase 0)

```ts
export type Stage = 'zk' | 'gk' | 'cet4' | 'cet6';           // index 1..4 in that order
export type StageIndex = 1 | 2 | 3 | 4;
export type UserState = 'new' | 'learning' | 'mastered' | 'known' | 'removed';
export type Origin = 'browse' | 'custom' | 'screen' | 'push' | 'import';   // 'import' = POST /api/bank/import
export type MarkAction = 'unfamiliar' | 'known' | 'mastered' | 'remove' | 'reset' | 'restore';
export type Grade = 'again' | 'hard' | 'good' | 'master' | 'skip';
export type ScreenVerdict = 'known' | 'unfamiliar' | 'skip';
export type ContentState = 'none' | 'queued' | 'ready' | 'failed';
export type ImageState = 'none' | 'queued' | 'ready' | 'failed';
export type ItemKind = 'review' | 'new' | 'screen' | 'extra';
export type WordKind = 'word' | 'phrase' | 'abbreviation' | 'proper_noun';
export type ReportReason = 'wrong_meaning' | 'unnatural_example' | 'bad_translation' | 'irrelevant_image' | 'inappropriate_image' | 'other';
export type WebhookFormat = 'generic' | 'wecom' | 'feishu' | 'serverchan' | 'bark';

export interface ApiError { error: { code: string; message: string; details?: Record<string, unknown> } }
export interface Page<T> { items: T[]; page: number; page_size: number; total: number }

export interface User {
  id: number; username: string; display_name: string; email: string | null; email_verified: boolean;
  role: 'user' | 'admin'; onboarding_state: 'pending' | 'screen' | 'done'; created_at: string;
}
export interface ServerFlags {
  version: string; registration_mode: 'open' | 'invite' | 'closed'; email_configured: boolean;
  ai_enabled: boolean; images_enabled: boolean; dev: boolean;
  needs_setup: boolean;                 // true while no user exists (also in GET /api/health)
}
export interface Counters { suggestions_open: number; attention: number }   // GET /api/auth/me → badges
export interface Settings {
  timezone: string; push_time: string; push_enabled: boolean;
  daily_new_count: number; daily_screen_count: number; max_reviews: number;
  stages: Stage[]; current_stage: Stage;   // Stage string on the wire; the server stores the 1–4 index (§9.1)
  show_images: boolean; zh_examples: 'tap' | 'always'; auto_pronounce: boolean; accent: 'en-US' | 'en-GB';
  email_enabled: boolean; webhook_enabled: boolean; webhook_url: string | null; webhook_format: WebhookFormat;
  next_push_at: string | null;          // read-only
  email_verified: boolean;              // read-only
  updated_at: string;
}
export interface StageInfo {
  stage: Stage; index: StageIndex; name_zh: string;           // 初中 / 高中 / 四级 / 六级
  total: number; new_only_total: number;                      // all words in the stage / words whose lowest stage is this one
  unfamiliar: number; known: number; mastered: number; unseen: number;
}
export interface WordBrief {
  id: number; lemma: string; display: string; kind: WordKind; phonetic: string | null;
  translation_short: string;            // first translation line, ≤ 60 chars
  stages: Stage[]; stage_min: StageIndex | null; cet6_star: boolean;
  frq: number | null; collins: number | null; oxford: boolean | null; difficulty: number | null;
  is_public: boolean; is_valid_english: boolean | null;
  my_state: UserState | null;
  content_state: ContentState; image_state: ImageState;
}
export interface Srs {
  ease: number; interval_days: number; step: 0 | 1; repetitions: number; lapses: number; consecutive_good: number;
  due_at: string | null; last_graded_at: string | null; mastery_suggested: boolean;
}
export interface UserWord {
  id: number; word_id: number; state: UserState; origin: Origin; priority: number;
  note: string | null; input_text: string | null;
  needs_attention: boolean; attention_msg: string | null; suggested_word: WordBrief | null;
  srs: Srs; times_pushed: number; times_added: number;
  added_at: string; first_added_at: string; mastered_at: string | null;
}
export interface Example { en: string; zh: string }
export interface Content {
  word: string; valid: boolean; meaning_zh: string; meaning_en: string;
  examples: Example[]; collocations: string[]; mnemonic_zh: string;
  image_keywords: string[]; image_alt_zh: string; difficulty: 1 | 2 | 3 | 4 | 5;
  version: number; prompt_version: string; model: string; created_at: string;
}
export interface Attribution {
  title: string | null; creator: string | null; creator_url: string | null;
  license: string; license_url: string | null; landing_url: string | null; text: string;   // text = ready-to-display line
}
export interface ImageMeta {
  id: number | null;                                          // null for the template card
  url: string;                                                // '/media/images/ab/ab12….jpg' | '/media/card/123.svg'
  kind: 'photo' | 'svg' | 'card';
  provider: 'wikimedia' | 'openverse' | 'pixabay' | 'pexels' | 'claude_svg' | 'card_svg';
  mime: 'image/jpeg' | 'image/svg+xml'; width: number | null; height: number | null;
  alt_zh: string | null; attribution: Attribution | null;      // null for the card
}
export interface WordDetail {
  word: WordBrief & {
    definition: string | null; translation: string | null; pos: string | null; exam_tags: string[];
    bnc: number | null; forms: { form: string; kind: string }[]; source: 'seed' | 'ecdict' | 'claude' | 'user';
    confusables: string[];                                    // 易混 chips: this user's accepted confusable_group rows containing the lemma, minus the lemma (§9.1)
  };
  content: Content | null; content_state: ContentState;
  content_deferred_until: string | null;                      // == GET /api/words/{id}/content.deferred_until (budget deferral / AI paused → no polling, 「明天补齐」 copy)
  image: ImageMeta; mine: UserWord | null; redirected_from: string | null;
  history: ReviewLogItem[];                                   // my last 20 actions on this word
}
export interface ReviewLogItem {
  id: number; created_at: string; action: string; context: string;
  prev_state: UserState | null; new_state: UserState | null; prev_interval: number | null; new_interval: number | null;
}
export interface LookupPreview {
  input: string; normalized: string | null; valid: boolean; reason_zh: string | null;
  via: 'exact' | 'form' | 'ambiguous' | 'ecdict' | 'none' | 'invalid';
  match: WordBrief | null; lemma_note_zh: string | null;      // e.g. 已归为原形 go（过去式）
  candidates: WordBrief[];                                    // ambiguous forms (bases → base / basis)
  suggestions: WordBrief[];                                   // ≤ 5 prefix matches
  mine: UserWord | null;
}
export interface ScreenWord { word: WordBrief; phonetic: string | null }
export interface ScreenResponse {
  word_id: number; verdict: ScreenVerdict; mine: UserWord | null; added_to_today: boolean;
  study_item: StudyItem | null; today: TodayCounts | null; duplicate: boolean;
}
export interface AddResult {
  input: string; status: 'added' | 'readded' | 'exists' | 'pending_ai' | 'ambiguous' | 'invalid';
  word: WordBrief | null; mine: UserWord | null;
  resolved_via: 'exact' | 'form' | 'ecdict' | 'provisional' | null; lemma_note_zh: string | null;
  candidates: WordBrief[]; error: string | null; message: string | null; added_to_today: boolean;
}
export interface AddResponse { results: AddResult[]; added: number; readded: number; exists: number; pending_ai: number; ambiguous: number; invalid: number }
export interface ImportResponse extends AddResponse { rows: number; skipped: number }   // POST /api/bank/import; results holds the first 200 rows
export interface BankItem extends WordBrief { mine: UserWord }
export interface BankCounts { new: number; learning: number; mastered: number; known: number; removed: number; attention: number; due_today: number }
export interface BankResponse extends Page<BankItem> { counts: BankCounts }
export interface Suggestion {
  id: number; type: 'fix_spelling' | 'lemmatize' | 'merge_duplicate' | 'invalid_word' | 'split_phrase' | 'confusable_group' | 'fill_data' | 'difficulty';
  status: 'open' | 'accepted' | 'rejected' | 'expired' | 'auto' | 'undone';
  user_word: BankItem | null; target: WordBrief | null;
  payload: { from?: string; to?: string; note_zh?: string; confidence?: number; group?: string[]; fields?: string[] };
  created_at: string; expires_at: string | null; resolved_at: string | null;
}
export interface SuggestionResult { applied: boolean; mine: UserWord | null; removed_word_id: number | null; message_zh: string }

export interface TodayCounts {
  total: number; done: number; review: number; review_done: number; new: number; new_done: number;   // *_done = items with result !== null (final grade); the 10-minute step is not done
  screen: number; screen_done: number; extra: number; extra_done: number; pending_content: number; deferred_reviews: number;   // pending_content excludes budget-deferred items (endpoint 43)
}
export interface StudyItem {
  item_id: number; kind: ItemKind; position: number; result: string | null; skip_count: number;   // result: FINAL grade only (null while the card sits in the 10-minute step)
  requeue_at: string | null;                                  // learning step due (UTC) → client re-inserts the card; always paired with result === null
  word: WordBrief & { definition: string | null; translation: string | null; pos: string | null; forms: string[]; confusables: string[] };
  mine: UserWord | null; content: Content | null; content_state: ContentState; content_deferred_until: string | null; image: ImageMeta;
}
export interface Batch {
  id: number; local_date: string; timezone: string; status: 'building' | 'ready' | 'published'; trigger: string;
  gradable: boolean;                                          // today's batch, or yesterday's while it has ungraded items (endpoint 50); false → replay only, no grade bar
  counts: TodayCounts; items: StudyItem[];                    // ungraded first (skipped after unskipped), then graded
  extra_rounds: number; can_request_more: boolean; built_at: string; published_at: string | null; completed_at: string | null;
}
export interface PreviousOpenBatch { id: number; local_date: string; remaining: number }   // yesterday's batch with ungraded review/new/extra items (endpoint 43)
export interface TodayResponse {
  status: 'none' | 'building' | 'ready' | 'published'; local_date: string; push_time: string; next_push_at: string | null;
  can_build_now: boolean; batch: Batch | null; streak_days: number; goal_met: boolean; added: number | null;   // added: items appended by /more
  previous_open_batch: PreviousOpenBatch | null;              // 「继续昨天的学习（还剩 N 个）」 on 今日
  suggestions_open: number;                                   // open 整理建议 (badge on 今日)
}
export interface GradeResponse {
  item: { item_id: number; result: string | null; skip_count: number; requeue_at: string | null };   // result null + requeue_at set = intermediate grade: the item stays ungraded and is graded again later (endpoint 45)
  mine: UserWord | null; next_due_zh: string;                 // '10 分钟后' | '明天' | '今天' | 'N 天后' | '约 N 个月后' | '已掌握' | '已跳过' | '已认识' (thresholds in §9.1)
  mastery_suggested: boolean; today: TodayCounts; duplicate: boolean;
  study_item: StudyItem | null;                               // the kind='new' card appended when a screen item was graded unfamiliar in-batch
}
export interface SessionSummary {
  local_date: string; review: number; new: number; extra: number; screen: number; again: number; hard: number; good: number;
  mastered: number; known: number; unfamiliar: number; study_minutes: number; streak_days: number; goal_met: boolean;
  next_push_at: string | null; can_request_more: boolean;
}
export interface DayStats {
  date: string; graded: number; again: number; hard: number; good: number; mastered: number; known: number; screened: number; added: number;
  study_minutes: number; batch_id: number | null; batch_total: number | null; batch_done: number | null; offline: boolean;
}
export interface BatchSummary { id: number; local_date: string; status: string; trigger: string; counts: TodayCounts; published_at: string | null; completed_at: string | null }
export interface Stats {
  bank: BankCounts; stages: StageInfo[]; custom_words: number; streak_days: number; longest_streak: number;
  today: { done: number; total: number } | null; total_graded: number; total_mastered: number;
  heatmap: { date: string; graded: number; goal_met: boolean }[];   // last 84 days
  stubborn: WordBrief[];                                             // times_added ≥ 3, max 20
}

// ---- admin ----
export interface AdminOverview {
  users: { total: number; active_7d: number };
  words: { total: number; with_content: number; with_photo: number; with_claude_svg: number; card_only: number; user_added: number; pending_validation: number };
  // with_photo = active word_images.provider ∈ wikimedia/openverse/pixabay/pexels · with_claude_svg = provider claude_svg · card_only = content ready but no active image
  bank_entries: number; batches_today: number;
  jobs: { queued: number; running: number; dead: number; by_type: Record<string, number> };
  ai: { enabled: boolean; paused_until: string | null; flag_tier: 0 | 1; today_usd: number; month_usd: number;
        daily_budget_usd: number; monthly_budget_usd: number; svg_today_usd: number; svg_daily_budget_usd: number;
        calls_today: number; avg_cost_per_word_7d: number | null; last_error: string | null };
  images: { providers: { provider: string; minute_count: number; day_count: number; minute_limit: number | null; day_limit: number | null; cooldown_until: string | null }[] };
  scheduler: { last_tick_at: string | null; alive: boolean };
  events_24h: SystemEvent[];
}
export interface AdminHealth {
  db_ok: boolean; db_size_bytes: number; disk_free_bytes: number; data_dir: string;
  scheduler_alive: boolean; scheduler_last_tick_at: string | null; claude_worker_alive: boolean; io_worker_alive: boolean;
  claude_bin: { path: string; version: string | null; ok: boolean; flag_tier: 0 | 1; last_probe_at: string | null };
  seed_version: string | null; migrations_version: number; worker_lease: { instance: string; expires_at: string } | null;
  last_backup: { file: string; at: string; bytes: number } | null;
}
export interface AdminUser extends User { is_active: boolean; last_login_at: string | null; bank_size: number; streak_days: number }
export interface Job {
  id: number; type: string; payload: Record<string, unknown>; dedupe_key: string | null; priority: number; status: string;
  attempts: number; max_attempts: number; run_after: string; locked_by: string | null; last_error: string | null; created_at: string; finished_at: string | null;
}
export interface AiCall {
  id: number; kind: string; status: string; model_requested: string; model_used: string | null; flag_tier: 0 | 1; word_count: number;
  cost_usd: number; duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; error: string | null; started_at: string;
}
export interface Report {
  id: number; user: { id: number; username: string }; word: WordBrief; target: 'content' | 'image' | 'dictionary'; reason: ReportReason;
  note: string | null; status: 'open' | 'resolved' | 'dismissed'; resolution: string | null; created_at: string; resolved_at: string | null;
}
export interface SystemEvent { id: number; kind: string; detail: Record<string, unknown>; created_at: string }
```

### 9.1 Field notes

* `WordBrief.translation_short` = first line of `translation`, truncated to 60 chars; `stages` lists every stage flag set (cumulative), `stage_min` the lowest.
* `Settings.current_stage` (and the request bodies of endpoints 12/15) is the `Stage` string; the server maps `zk→1, gk→2, cet4→3, cet6→4` to `user_settings.current_stage` and back. `StageIndex` is used only where an index is the natural value (`StageInfo.index`, `WordBrief.stage_min`).
* `UserWord.srs.mastery_suggested` = `step==0 && interval_days>=30 && consecutive_good>=3` (server computed; the client never derives it).
* `GradeResponse.next_due_zh` (= `srs.humanize`, mirrored byte-for-byte by `utils/srsPreview.ts` and pinned in `tests/fixtures/srs_trajectory.json`): `step==1 → '10 分钟后'`; `interval_days==1 → '明天'`; `2 ≤ interval_days ≤ 59 → 'N 天后'`; `interval_days ≥ 60 → '约 M 个月后'` with `M = rnd(interval_days / 30)` (half-up); `master → '已掌握'`; `skip → '已跳过'`; a screen verdict `unfamiliar` without a same-day study row → `'明天'`, with an appended `kind='new'` study row → `'今天'`; an in-batch screen verdict `known` → `'已认识'` (endpoint 45).
* `SessionSummary.mastered` / `known` / `unfamiliar` count final outcomes (`push_items.result`), so an undone 已掌握 (`mark restore`) is not counted; `again` / `hard` / `good` count `review_logs` rows of the session (intermediate grades included, like `daily_stats`).
* `ImageMeta` is **never null** in `WordDetail`/`StudyItem`: when no active photo/SVG exists it is `{id:null, url:'/media/card/<id>.svg', kind:'card', provider:'card_svg', mime:'image/svg+xml', width:800, height:500, alt_zh:null, attribution:null}`.
* `StudyItem.requeue_at` is set when the item's `user_words.step=1` and `due_at` is in the future (10-minute step); such an item always has `result:null` (only final grades are stored, endpoint 45) and is listed among the ungraded items; the client keeps it in `order` (not `graded`), re-inserts the card ≥ 10 positions later or at the end, and shows it when `requeue_at ≤ now`. On reload the server lists it as remaining with `requeue_at` still set (or null once due).
* `TodayResponse.goal_met` = every non-stale `review`/`new`/`extra` item of today's batch has `result IS NOT NULL` (final grade; stale items are excluded, endpoint 43). `TodayCounts.done`, `completed_at` and `item_already_graded` use the same predicate.
* `confusables` (`StudyItem.word`, `WordDetail.word`) = for this user, the union of `payload.group` over `bank_suggestions` rows with `type='confusable_group' AND status='accepted'` whose group contains the word's lemma, minus the lemma itself, de-duplicated, ≤ 6, in insertion order (CLAUDE_INTEGRATION §6.6); `[]` when none. Served directly on the item/detail so the client never has to fetch and index the suggestions list.
* `UserWord` has no extra field for 仅收藏: the bank row shows that chip when `word.is_valid_english === false && !mine.needs_attention` (API 36 `attention:'keep'`), 待校验 when `is_valid_english === null && !needs_attention`, 重新校验中 when `needs_attention && attention_msg === null`.
* `DayStats.offline` = the user has no batch that day **and** some `system_events(kind='downtime')` row with `detail_json = {"from", "to"}` (UTC, written by the scheduler on startup, DESIGN §6.4) satisfies `from ≤ day_start(date+1, tz) AND to ≥ day_start(date, tz)` — i.e. the recorded gap overlaps the user's local day.
