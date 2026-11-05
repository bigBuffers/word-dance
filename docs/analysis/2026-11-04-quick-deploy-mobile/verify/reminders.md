# Verification — slice "reminders" (word-Dance quick-deploy + mobile research)

Repo /Users/sqin/word-dance @ 9ab13a5 · verified 2026-11-04 · digest: scratchpad/quick/facts/reminders.md

Method: adversarial, execution-first. Scratch only under `scratchpad/quick/verify-reminders/` (scripts `probe.py`, `measure.py`, `server-run.sh`, DB copy `live2.db`, throwaway data dir `data/`). Throwaway `wd serve` on 127.0.0.1:8027 (`WD_WORKER_ENABLED=0 WD_DEV=1 WD_CLAUDE_BIN=backend/tests/fake_claude.py`, mini seed), killed afterwards (`lsof -iTCP:8027 -sTCP:LISTEN` → none). The read-only live copy was queried through `file:…?mode=ro` and a private copy. Nothing was written to /Users/sqin/word-dance-data (two reads only: the launchd plist and `grep '^WD_PUBLIC_URL' .env`), port 8000 and the real `claude` were never used, no tracked file changed. Live probes sent only the constant test string with throw-away keys to a random ntfy topic — identical in kind to the research slice's probes. A second `wd serve` found on 127.0.0.1:8021 (PID 24108, `WD_DATA_DIR=…/verify-deploy/dataB`) belongs to the deploy verification slice and was left alone; PID 1204 on :8000 is the live service.

Test suites run (all green): `pytest -q backend/tests/integration/test_delivery.py backend/tests/unit/test_queue.py` → **71 passed**; `pytest -q backend/tests/unit/test_scheduler.py` → **27 passed**; `pytest -q backend/tests/integration/test_settings.py -k webhook` → **4 passed**; `pytest -q backend/tests/unit/test_registry_complete.py` → **4 passed**.

Verdict summary: F3 confirmed (and worse than stated: Server酱³ has the same bug) · F2 confirmed · F4 confirmed · F5 confirmed · F6 **corrected** · F9 confirmed · F11 confirmed · F13 **corrected** (minor) · F12 confirmed · F1 confirmed.

---

## F3 — `safe_post` 2xx = success, body never read; WeCom/Feishu answer HTTP 200 for bogus keys

**Verdict: confirmed** (plus a new instance of the same defect, see Omissions #1).

Read: `backend/wd/delivery/webhook.py:252-254`
```
    if 200 <= response.status_code < 300:
        return PostResult(response.status_code, None, None)
    return PostResult(response.status_code, f"HTTP {response.status_code}", "http_error")
```
`response.text/json()` is never touched anywhere in the module; `:332-336` sets `sent` whenever `error is None`; `:353` returns `ok = result.error is None`.

Ran (direct network, proxies unset) `backend$ ../.venv/bin/python …/verify-reminders/probe.py` — calls the repo's own `send_test_webhook()` then repeats the raw POST to capture the body:
```
wecom@qyapi.weixin.qq.com   send_test_webhook={"ok": true, "http_status": 200}  0.28 s  raw 200 {"errcode":93000,"errmsg":"invalid webhook url, hint: […], from ip: 203.18.50.9, …"}
feishu@open.feishu.cn       send_test_webhook={"ok": true, "http_status": 200}  0.33 s  raw 200 {"code":19001,"data":{},"msg":"param invalid: incoming webhook access token invalid"}
bark@api.day.app            send_test_webhook={"ok": false,"http_status": 400,"error":"HTTP 400","reason":"http_error"} 0.32 s  raw 400 {"code":400,"message":"failed to get device token: …"}
serverchan@sctapi.ftqq.com  send_test_webhook={"ok": false,"http_status": 400,"error":"HTTP 400","reason":"http_error"} 0.74 s  raw 400 {"message":"[AUTH]错误的Key","code":40001,…,"scode":461}
```
End-to-end on the throwaway server (`server-run.sh`): `PUT /api/settings` with the bogus WeCom URL + `webhook_format: wecom` → `POST /api/settings/webhook/test` → `{"ok":true,"http_status":200,"error":null,"reason":null} [200]` (the UI maps this to 「测试成功」). Then, server stopped, `wd push-now verifyuser` → `batch 1 … webhook queued`; `wd worker-once` → `push_batches`: `webhook_status=sent, delivery_error NULL`; `jobs`: `send_webhook done attempts=1 result_json={"format":"wecom","http_status":200,"sent":true}` — while WeCom had answered errcode 93000. Docs re-read: developer.work.weixin.qq.com/document/path/90313 — `45002` "消息内容大小超过限制", `93000` "消息推送webhookurl不合法或者消息推送已经被移除出群"; open.feishu.cn/document/client-docs/bot-v3/add-custom-bot — success `{"code":0,"msg":"success","data":{}}`, errors `19021`/`19024`/`9499`/`11232`, "All error responses use HTTP 200 status".

## F2 — digest sizes from the live snapshot: body 1,911–1,989 B, WeCom/Feishu text 1,982–2,061 B, title 43–44 chars

**Verdict: confirmed** (the "Server酱's documented 32-char title" qualifier is unverifiable from public official pages — see note).

Ran `measure.py` against a private copy of live-copy.db (batches 2 and 3, `cfg.public_url="https://wd.example.com"`), independent re-implementation of the measurement:
```
batch=2 title_chars=44 words=10 body_chars=1307 body_bytes=1989 wecom_text_bytes=2061
batch=3 title_chars=43 words=10 body_chars=1294 body_bytes=1911 wecom_text_bytes=1982
```
Byte-identical to payload-sizes.json. With `public_url=""` (today's live state) the LAN link makes it 1,992/1,914 B body and 2,064/1,985 B WeCom text. WeCom doc (developer.work.weixin.qq.com/document/path/91770, accessed today): text "文本内容，最长不超过2048个字节"; markdown "最长不超过4096个字节"; "每个消息推送发送的消息不能超过20条/分钟" → batch 2 (2,061 B) overflows the cap, batch 3 sits 66 B under it. Actual httpx wire bodies (compact separators) are a little smaller than the digest's `json_bytes` (generic 3,145–3,355 B instead of 3,226–3,436) — irrelevant for WeCom, which counts the `content` field.

Note on the 32-char title: `WebFetch https://sct.ftqq.com/sendkey` shows only the page title (login-only), npm page returned 403, the FAQ/channels pages carry no title length, and the only public figure found is the legacy API's "text：消息标题，最长为 256" (developer.cloud.tencent.com/article/1620709). So "documented 32" rests on the npm README quoted by the digest; it should be checked with a real SendKey before shortening `Digest.title`.

## F4 — Bark: zero-code iPhone push; HTTP 400 for bad keys; iOS only; one device; plaintext key; tap opens /today

**Verdict: confirmed** (one wording nuance).

Read `webhook.py:288-291` (`{"title","body"}` + `"url"` when known) and `:351` (`url=None` for the test). Live: `api.day.app` → HTTP 400 `failed to get device token: failed to get [verifybogusdevicekey00000000] device token from database` in 0.32 s (whole `send_test_webhook`, DNS+TLS+POST), reported as `http_error` → correct. README (raw.githubusercontent.com/Finb/Bark/master/README.md): "Bark is a push notification tool app. It's free, simple, and secure, leveraging APNs…", App Store id1403753865, "Click on the push notification to jump to the specified URL"; no Android build is mentioned. bark-server docs/API_V2.md: `url` "Url that will jump when click notification", 400 for empty/invalid device key, 500 for push failure. Plaintext: `grep -rni "fernet|encrypt|aes" backend/wd` → nothing; `user_settings.webhook_url TEXT` (0001_init.sql:155) and `security.py:604` returns the row value verbatim in the settings DTO. One device per account follows from the single `webhook_url` column (no `device_keys` array is sent). Nuance: the tap opens the iOS *default browser* (Safari unless the friend changed it in iOS 14+), not Safari per se.

## F5 — Server酱 Turbo: every phone with WeChat; 5/day free after 7-day trial; ¥8/月 ¥39/年; title-only card; JSON title/desp; bad key → HTTP 400

**Verdict: confirmed** (detail-page behaviour not executable without a real SendKey).

sct.ftqq.com/docs/getting-started/faq/ (accessed today): "每天最多 5 条", "新用户自动获得 7 天全功能试用", "8 元/1 个月、39 元/12 个月、180 元/60 个月", members "每天最多可发 1000 条 … 每分钟不超过 50 条", 429 "你的 IP 在 24 小时内调用 API 次数超过限制", "`title` 中不能包含换行符". channels page: 免费用户仅显示标题，订阅会员可显示标题和内容 — "服务号通道除外，该通道展开内容易被举报" (so on the WeChat 服务号 channel even paying members get the title-only card). integrations/python: `Content-Type: application/json;charset=utf-8`, "Both variants send parameters as JSON", success = `"code": 0`. Live JSON POST (title/desp) to `sctapi.ftqq.com/<bogus>.send` → HTTP 400 `{"code":40001,"message":"[AUTH]错误的Key","scode":461}` in 0.74 s, i.e. the JSON body was parsed up to the key check and the failure is surfaced correctly by the backend. Code: `webhook.py:286-287`.

## F6 — Server酱³: same payload, `https://<uid>.push.ft07.com/send/<key>.send`, vendor channels; JSON acceptance/reachability unexercised

**Verdict: corrected.**

What holds: compare page lists "FCM（有 Google 服务的机型）、小米、华为、荣耀、vivo、OPPO、iQOO、Realme、OnePlus、魅族"; faq: "free during the testing period", "most parameters are compatible with ServerChanTurbo"; hostname passes the SSRF rules (the backend actually posted to it, see below).

Corrections, all from today:
1. The official API page exists and is readable: https://doc.ft07.com/en/serverchan3/server/api — "Both `POST` and `GET` are supported", POST bodies `application/json`, `application/x-www-form-urlencoded`, `multipart/form-data`; params `title`|`text` (required), `desp`, `tags`, `short`. JSON acceptance is therefore documented, not merely inferred from the integrations page.
2. The API path *is* reachable from this mainland network: `send_test_webhook` → `https://1.push.ft07.com/send/sctp1tbogus.send` answered in **0.54 s** (the digest's root-GET timeout was the origin ignoring `/`, not the API path).
3. **It answered HTTP 200 `{"error":"sendkey not found","code":10003}`** → `send_test_webhook` returned `{"ok": true, "http_status": 200}`. Server酱³ therefore shares the WeCom/Feishu false-success defect (F3); the digest's "Bark and Server酱 answer HTTP 400" is true only for Turbo's `sctapi.ftqq.com`.
4. Android distribution (doc.ft07.com/en/serverchan3/app/install): "download from the store or search for 'ServerChan'" or "download the APK directly" (sc3.ft07.com/client); channels MiPush, Push Kit (Huawei), OPPO Push, vivo Push, Flyme Push; no HarmonyOS/NEXT statement anywhere.

Still unverified (needs a real key): that a JSON `title`/`desp` body is rendered, and whether rejections of a *valid* key (quota etc.) also come back as HTTP 200.

## F9 — generic JSON + ntfy template URL works; 250 msgs/day per IP; F-Droid build without GMS; native `ntfy` format ≈ 1 day (CHECK rebuild)

**Verdict: confirmed** (the 1-day figure is an estimate; its premise is proven).

Live end-to-end through the unchanged `generic` format: `send_test_webhook` → `https://ntfy.sh/wd-verify-<random>?template=yes&title={{.title}}&message={{.body}}&click=https://example.com/today` → HTTP 200 in 0.87 s; poll-back `GET https://ntfy.sh/<topic>/json?poll=1`:
```
{"event":"message","topic":"wd-verify-581ab8fd9f5f3e47","title":"word-Dance 测试消息","message":"Webhook 配置成功，每日词汇将推送到这里。","click":"https://example.com/today"}
```
(the query string evidently survives `validate_url`/`pin`, otherwise the template could not have applied). Docs (raw.githubusercontent.com/binwiederhier/ntfy/main/docs/publish.md): "250 messages per day" on ntfy.sh, "All limits are per visitor/IP address, not per topic", "Templates are limited to 32 KB", templating applies to title, message and action parameters; docs.ntfy.sh/subscribe/phone/: F-Droid flavour has no Firebase, "all subscriptions use instant delivery by default, and there is no option to disable it"; docs.ntfy.sh/config/: `upstream-base-url` forwards only the message id and "the SHA256 checksum of the topic URL". CHECK rebuild premise executed on the scratch copy:
```
sqlite3 live2.db "BEGIN; UPDATE user_settings SET webhook_format='ntfy' WHERE user_id=1; ROLLBACK;"
→ Error: CHECK constraint failed: webhook_format IN ('generic','wecom','feishu','serverchan','bark')
```
Touch points exist as listed: schemas.py:37, frontend/src/api/types.ts:17, SettingsPage.tsx:27, i18n/zh.ts:77, 0001_init.sql:156; no migration so far rebuilds a table (0008, 0009 don't).

## F11 — every channel links `<base>/today`; live base is the LAN guess; opens a browser; app deep links need AASA/assetlinks + paid Apple account

**Verdict: confirmed.**

`email.py:60-70` (`WD_PUBLIC_URL → kv.public_url_guess → None`). Live copy: `kv.public_url_guess = http://10.23.147.103:8000`; rendering batches 2/3 with `public_url=""` gives `url = http://10.23.147.103:8000/today`. WD_PUBLIC_URL is really empty on the live service: `grep '^WD_PUBLIC_URL' /Users/sqin/word-dance-data/.env` → line 29 `WD_PUBLIC_URL=""`, and the launchd plist's EnvironmentVariables are only WD_DATA_DIR/HOME/PATH/LANG/PYTHONUNBUFFERED (note `main.py:482-484` records the guess at every start regardless of WD_PUBLIC_URL, so the kv row alone would not have proven it). Catch-all verified on the throwaway server: `GET /.well-known/apple-app-site-association` → `200`, `content-type: text/html`, `cache-control: no-cache`, body = index.html; same for `/.well-known/assetlinks.json`. Paid account for Associated Domains: Apple forums thread 656318 (via search) — a free "Personal Team" cannot add the Associated Domains capability. Browser hand-off details (Bark → default browser, Server酱 → WeChat WebView) are not executable here; consistent with the vendor docs.

## F13 — Web Push ≈ 6–10 person-days; reaches only Safari-installed Home-Screen iPhones and GMS Android

**Verdict: corrected** (code/dependency facts confirmed; two reach statements need adjusting).

Confirmed by execution: `ls frontend/public` → `favicon.svg` only; `index.html:11-13` carries only the `apple-mobile-web-app-*` metas; `grep -rn "serviceWorker|manifest|pushManager" frontend/src frontend/index.html` → no match; `sqlite3 live2.db "INSERT INTO jobs(type) VALUES('send_webpush')"` → `CHECK constraint failed: type IN (…)` (table rebuild needed); `registry.JOB_TYPES`/`HANDLER_MODULES` (registry.py:30-50), `queue.IO_TYPES` (queue.py:34), `schemas.AdminJobsQuery.type` Literal (schemas.py:1251), `test_registry_complete.OWNERS` (:17-27) all enumerate the job types; venv probe: `pywebpush`, `py_vapid`, `http_ece`, `requests`, `h2`, `cryptography`, `aiohttp` all `ModuleNotFoundError`, `httpx.Client(http2=True)` → `ImportError: … 'h2' package is not installed`; pypi JSON: pywebpush **2.5.0**, uploaded 2026-08-29/30, `requires_python >=3.10`, `requires_dist` = aiohttp, cryptography>=47.0.0, http-ece>=1.1.0, requests>=2.21.0, py-vapid>=1.7.0 (+dev extras).

Corrections: (1) WebKit blog 13878: Web Push comes "with iOS and iPadOS 16.4 … to Home Screen web apps", and "third-party browsers can now offer their users the ability to add websites and web apps to the Home Screen from the Share menu" — so "installed from Safari" is too narrow; the real exclusion is WeChat's in-app browser, which has no add-to-Home-Screen. (2) "Chrome on GMS-less mainland phones gets nothing" is consistent with Chrome's documented FCM dependency (developer.chrome.com/blog/push-notifications-on-the-open-web: "Chrome uses FCM to handle the sending and delivery of push messages") but no primary source states the failure mode on Play-less devices; treat as plausible, not verified. The 6–10 day figure is judgment.

## F12 — Capacitor local notifications: no backend change, but an app per phone; Android APK ≈ 2–3 days; iOS needs Xcode + $99; HarmonyOS NEXT no APK; exact-alarm permissions

**Verdict: confirmed** (effort figures and ROM force-stop behaviour are judgment, not re-verified).

capacitorjs.com/docs/apis/local-notifications (v8): `at`/`every: 'day'`/`on {hour, minute}`/`repeats`/`allowWhileIdle`; Android 13+ `POST_NOTIFICATIONS`, 12+ `SCHEDULE_EXACT_ALARM`, 14 `USE_EXACT_ALARM`, `checkExactNotificationSetting()`/`changeExactNotificationSetting()`. Apple (UILocalNotification reference JSON): "the system keeps the soonest-firing 64 notifications (with automatically rescheduled notifications counting as a single notification) and discards the rest". Wikipedia HarmonyOS NEXT: "cannot run Android apk apps natively". Toolchain: `xcode-select -p` → `/Library/Developer/CommandLineTools`, no `/Applications/Xcode*.app`, `xcodebuild` refuses; `adb` not found, no `~/Library/Android/sdk`, `java -version` → "Unable to locate a Java Runtime". `GET /api/settings` on the throwaway server returns `"timezone":"Asia/Shanghai","push_time":"08:00"` (the inputs a shell app would schedule from).

## F1 — pipeline facts (who/when, 6 h stale skip, 2/10-min retries, 300-char error, SSRF final, 1 test per 10 min without URL, no DTO exposure)

**Verdict: confirmed** (two visibility nuances).

`scheduler.py:106-107`: `u.is_active = 1 AND u.onboarding_state = 'done' AND s.push_enabled = 1 AND s.next_push_at IS NOT NULL`; `:49` `STALE_DELIVERY = 6 h`, `:149-156` conditional `publish_batch` → `enqueue_deliveries(stale=now - next_push > 6 h)` → `compute_next_push`; `batches.py:1000-1032` `skipped` when stale, dedupe `webhook:<id>`, priority 20, default `max_attempts=3`. `queue.py:31` `BACKOFF_MINUTES=(2,10,60)`, `:47-49` `backoff_minutes(attempts)`, attempts incremented at claim (`:149`), `:173-190` dead when `attempts >= max_attempts` → after failures 1 and 2 the job waits 2 then 10 min, the third failure is `dead`; `webhook.py:374-376` maps `dead` → `webhook_status='failed'`, `:311` truncates to 300 chars; `:369-373` SSRF → final. Tests: `test_send_test_webhook_ok_and_server_errors_retry` asserts exactly 3 requests → `dead`/`failed`; `test_webhook_ssrf_guard_rejects_private_targets` asserts `failed` + `final: true`; `test_catch_up_after_a_three_day_gap_…` asserts `("skipped","skipped")  # > 6 h late`. Throwaway server: second `POST /api/settings/webhook/test` within 10 min → `429 {"code":"rate_limited","details":{"retry_after_s":600}}`; test payload built with `url=None` (`:351`). DTOs: `GET /api/admin/users` items carry no delivery fields; `GET /api/admin/jobs?type=send_webhook` shows the job (`last_error` null); settings DTO has none. Nuances: `wd push-now` prints `email … webhook …` statuses (batches.py:1099) and the admin page renders the jobs ledger with `last_error` (frontend/src/pages/AdminPage.tsx:681), so genuine failures ("HTTP 400", "rejected: …") are visible on the admin page — only false successes (F3) are not.

---

## Omissions / new findings

1. **Server酱³ has the same HTTP-200-on-error behaviour as WeCom/Feishu.** Live: `https://1.push.ft07.com/send/<bogus>.send` → HTTP 200 `{"error":"sendkey not found","code":10003}` → `send_test_webhook` `ok=True`. The week-2 body check must parse `code != 0` for the `serverchan` format too (Turbo success is `{"code":0,…}`), otherwise the Android recommendation inherits the false-「测试成功」 problem. Also: the official sc3 API page is live (doc.ft07.com/en/serverchan3/server/api — JSON/form/multipart POST, params `title|text`, `desp`, `tags`, `short`) and the API path answers from this mainland network in 0.54 s, which removes two of F6's caveats.
2. **A false success leaves no trace anywhere an operator looks.** Verified end-to-end: `wd push-now` + `wd worker-once` against the bogus WeCom key → `push_batches.webhook_status='sent'`, `delivery_error NULL`, job `done` with `result_json {"sent": true, "http_status": 200}`, and `GET /api/admin/jobs` shows `last_error: null`. The DB, the admin job ledger and the admin page all read as a delivery; the only detector is the friend's phone. The fix should store the vendor `errcode`/`code` in `delivery_error` so the ledger becomes truthful.
3. **The live service environment is clean and the public URL really is unset.** Launchd plist `com.word-dance.server.plist` exports only WD_DATA_DIR/HOME/PATH/LANG/PYTHONUNBUFFERED (comment: proxy deliberately not set), and `.env` line 29 is `WD_PUBLIC_URL=""`. This closes F15's open question for the Mac (httpx `trust_env=True` is moot here; only a future VPS unit file needs the check) and confirms F11's premise independently of the kv guess, which `main.py:482-484` rewrites at every start regardless of WD_PUBLIC_URL. Incidentally WeCom reported the Mac's egress IP as `203.18.50.9` (relevant to a Feishu IP allowlist or ntfy's per-IP budget if the Mac stays the server).
4. **The Server酱 32-character title limit has no public official source.** The Turbo parameter table lives on the login-only SendKey page; public docs give no title length, and the legacy API documented 256. Recommendation 2(c) ("keep the title ≤ 32 chars") should be confirmed with one real SendKey before touching `Digest.title`.
5. **Two reach statements in the alternatives are slightly off.** iOS Home-Screen web apps (Web Push) can be added from third-party browsers since 16.4 (WebKit blog 13878), so Web Push is not "Safari-installed only" — the real blocker is WeChat's WebView; and ntfy's templating is documented for title, message *and* action/click parameters, so `click` could be templated from the generic payload's `url` field instead of being hard-coded in the webhook URL (cosmetic for F9).
