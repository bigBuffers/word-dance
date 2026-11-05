# Judge J2 — lens: the friends' experience across device classes

Date 2026-11-04 · repo `/Users/sqin/word-dance` @ `9ab13a5` · plans judged: `design-D1-fast.md`, `design-D2-solid.md`, `design-D3-apps.md` (each read in full) · fact base: the ten `facts/*.md` digests and the ten `verify/*.md` reports (verify corrections override digests). Citations: `(slice:Fn)` = digest finding, `(v-slice:Fn/On)` = verifier verdict / omission, `file:line` = checkout.

Extra spot-checks run by this judge (read-only greps on the checkout and `ls ~/Library/LaunchAgents`): `com.word-dance.backup.plist` exists; `wd check providers` and `wd stats` exist (`backend/wd/diag.py:28,259`); `USERNAME_RE = ^[A-Za-z0-9_一-龥]{2,32}$` (`backend/wd/schemas.py:52`); `cmd_create_admin` skips the "users already exist" guard when `--if-none` is absent (`backend/wd/security.py:738-740`); `system_events(kind, detail_json, created_at)`, `push_batches.webhook_status/published_at` and `provider_state(provider, cooldown_until, last_ok_at, last_error, …)` per `docs/SCHEMA.sql:59-64, 390-393, 542-549`; the event kinds `claude_auth`, `budget_daily/monthly/svg`, `backup_failed`, `downtime`, `claude_unavailable` exist in `backend/wd`, `provider_blocked` does not.

---

## 1. What a friend actually gets, per device class and plan

"Day 3" = the day the first friends are invited in each plan; "Day 14" = end of the plan window. All three plans share the same verified substrate (Tokyo Lighthouse + Caddy TLS, Mac DB copied in, invite mode, 30-day sliding HttpOnly cookie, Bark/Server酱 Turbo as week-1 channels, `WD_AI_*` caps 6/100), so the differences below are what the friend notices.

| Device class | Install | Stay logged in | Pronunciation | Daily reminder | Lockout / bad code | AI budget exhausted |
|---|---|---|---|---|---|---|
| **iPhone, Safari** | All: 分享 → 添加到主屏幕; opens standalone on iOS 26/27 with "zero requirements" (ios:F14, v-ios:F14/O5). Icon: D1 ships no `apple-touch-icon` before invites → iOS ≤ 18 (≈ 16 % of CN iOS traffic, ios:F21) gets a page-screenshot icon and iOS 26 depends on the SVG favicon being picked up (hedged in D1 1.11); D2 (Day 2) and D3 (Day 1) ship the PNG set first (pwa:F2/F5). | All: one Safari login; home-screen app may need one more (ios:F17 says cookies are copied on ≥ 17.2; v-pwa:F8 says the WWDC statement is macOS-only) — every plan hedges correctly. | Web Speech, Samantha/Daniel; first card after cold launch may wait for a tap (pwa:F8). D3's app later speaks without a tap (inference, v-capacitor:F12). | Bark → APNs lock-screen push; tap opens the *default browser* at `/today` (v-reminders:F4). All three correct. | All: 10 wrong = 15 min username lock (security:F4); owner unlock SQL with `.timeout 5000` (v-security:F4). D1 adds a break-glass admin; D2 adds `wd unlock` in week 2. Mistyped invite codes count toward 5/h/IP (v-security:O1) — all three say "paste". | SPA shows 「今日 AI 额度已用完，例句将在明天补齐」 for hourly, daily *and* monthly deferrals (security:F17). D2 fixes the copy Day 7, D3 week 2, D1 "later". |
| **iPhone inside WeChat** | WeChat's WKWebView has no A2HS (ios:F16, pwa:F9 — unverifiable on a device per v-pwa:F9 but consistent). D2/D3 show a non-dismissible 「在Safari中打开」 card before the first friend; D1 relies on the onboarding message alone until a week-2 trigger. | Separate cookie jar → an extra login if used there (reminders:F5). | Unknown inside XWeb (android open q6). D1/D3 say so; **D2's friend message states the button is grey there as fact** (see §3). | Server酱 nudge lands here — see blind spot B2. | same | same |
| **GMS Android** (global ROM / Google services on) | Chrome ⋮ → install; a real WebAPK only once the manifest + 192/512 PNGs exist (android:F8–F9) — D2/D3 before invites, D1 week 1 if triggered. | WebAPK shares Chrome's profile → no extra login expected (pwa:F8, unverified). | Chrome bridges to the system engine (android:F13). | Server酱 Turbo (WeChat) or ntfy via the template URL (reminders:F9); Web Push correctly ruled out by all three (android:F11: Chrome throws "Google Play Services missing"). | same | same |
| **GMS-less domestic Android** (Xiaomi/OPPO/vivo/Honor default) | Vendor browser → 添加到桌面 = launcher shortcut; standalone undocumented for every vendor browser (android:F10). Icon/name come from the manifest/PNGs (D2/D3) or the SVG favicon (D1). | Shortcut opens the same browser profile → persists. | Vendor browsers "likely" bridge to the system TTS — untested; English voice may be absent (android:F13). D2's message tells friends to install an English voice pack (good); D3's app adds the TTS plugin + `openInstall()` hint. | Server酱 Turbo → WeChat 服务号 (title-only card, 5/day free, reminders:F5); Server酱³ (real system push) only after the HTTP-200-error patch (v-reminders:O1) — D2 holds it to Day 6, D1 "after physical receipt", **D3 offers it on D3**. | same | same |
| **HarmonyOS 4.x** | Huawei Browser ∷ → 添加至桌面 (android:F7). | persists | Huawei engine untested. | Server酱 → WeChat; Server酱³ lists Push Kit (v-reminders:F6). | same | same |
| **HarmonyOS NEXT** | Huawei Browser shortcut, max 10, no manifest/standalone documented (android:F7); no APK (android:F5); 卓易通 container is an experiment (v-android:O1) — D3 says so explicitly, D1/D2 mention it as untested. | persists | ArkWeb SpeechSynthesis inferred outside 坚盾守护 mode (v-android:F7) — all three hedge. | Server酱 → native WeChat; 企业微信/飞书 after the patch (reminders:F7–F8). | same | same |

Net per lens: by the day friends arrive, **D2 gives the most polished first contact** (icon, WeChat hand-off card, truthful channels only, owner alerted by cron when AI pauses or a webhook fails); **D1 is the fastest and simplest** but leaves the two mainland-critical surfaces (icon, WeChat hand-off) to the message text; **D3 matches D2 on the web** and is the only plan that eventually gives GMS-less Android friends a relay-free reminder and reliable pronunciation — at the price of promising it in the first message.

Checks the task asked for:
- **TTS in WebViews**: Android System WebView has no `speechSynthesis` (`disable-speech-synthesis-api`, v-capacitor:F12; caniuse `android 156: n`, v-captool:F15) — all three know; D1 makes the TTS plugin mandatory for the Android app, D3 also routes iOS through it (silent-switch bypass, flagged as a decision), D2 includes it in phase 2. WeChat XWeb is unverified — only D2 overclaims.
- **Web Push and Google services**: all three skip Web Push with the right reason (android:F11, reminders:F13). None sells it as an Android reminder.
- **Server酱/Bark behaviour**: Bark HTTP 400 on bad keys, iOS-only, default browser on tap; Server酱 Turbo HTTP 400 on bad keys, 5/day free, title-only card, WeChat landing; WeCom/Feishu/Server酱³ HTTP 200 with error body → false 「测试成功」 and `sent` with no trace anywhere (v-reminders:O1–O2). All three plans state these correctly; they differ on when Server酱³ is offered (D2 strictest).
- **TestFlight internal testers and Apple Accounts**: D1/D2/D3 all state the e-mail-bound invitation, 3-day expiry, Marketing role, 50-user cap, all-territory availability, "Internal Only", 90-day expiry (ios:F4/F6, v-ios:F7/O2–O4). D3 goes furthest (polls the friends' Apple-Account e-mail on D0, names the redemption-code path). None mentions phone-number Apple IDs (blind spot B4).

---

## 2. Scores (0–10 each; total of 60)

| Criterion | D1-fast | D2-solid | D3-apps |
|---|---|---|---|
| speed_to_first_friend | **9** — pilot friends Day 2 evening, rest Day 3; zero code before invite | 8 — first friends Day 3 (Sat), rest Day 4 | 8 — first friends D3; web launch isolated from the app track |
| factual_correctness | **9** — every verify correction applied (`.timeout 5000`, two-statement cancel recipe, Server酱³ false success, ≥ 8.5.1 pin, origin-exact bridge, `USE_EXACT_ALARM`, re-arm, `ITSAppUsesNonExemptEncryption`); my spot-checks confirm its repo claims; only soft spots are an uncited "≈ 300 words/h" and "iOS 18.4+" | 8 — one overclaim in the friend message (WeChat TTS grey "as fact"), an arithmetic slip (6 vs 10 calls/10 min), a mischaracterised verifier verdict, a dead event kind in the cron | 7 — wrong `provider_state` column, internally inconsistent Phase-2 hours, `exec … && claude --version` never runs, friend text "第二天自动补上" wrong for monthly deferral, 20-login window misapplied, a two-week app promise its own table cannot keep |
| completeness_both_platforms | 7 — both app routes specified (§5) but trigger-gated; Android TTS/safe-area in "Later" | 8 — both routes specified as phase 2 with a Day-30 gate; adds export fallback, 返回 control | **10** — full iOS + Android spec, config, distribution, QA matrix, 2027 verification, NEXT handled |
| owner_effort_realism | **9** — ≈ 1.3 pd mandatory through day 14; Day 1 is tight but honest ("+ waits") | 7 — ≈ 3 pd in week 1 (6-h Saturday, 3-h evenings) + 1 pd week 2; honest budget, heavy for part-time | 4 — ≈ 11 pd in 14 calendar days for a solo part-time owner, plus proxy-bound Xcode/SDK downloads and a 1–3-day enrolment; Phase 2 evening overbooked |
| friend_experience | 7 — clearest onboarding message; break-glass admin protects support; but no icon/hand-off before invites, "明天" copy unfixed, no alerting so friend-visible failures surface slowly | **9** — icon + WeChat card before the first friend, only truthful channels in week 1, cron pings the owner on AI pause/webhook failure/health, copy fix Day 7, more channels Day 6, English-voice tip | 8 — same web polish as D2 and the only plan that upgrades GMS-less Android friends (relay-free reminder, TTS); minus: Server酱³ offered before truthfulness, apps promised in the first message, no alerting, iOS silent-switch bypass, ASC e-mail/legal-name exposure |
| risk_and_maintenance | 7 — backups off-box Day 1 (RunAtLoad), drill Day 2, Mac rollback 14 days, pinned CLI; no monitor/alerting | **9** — watch cron + external monitor + drill + console snapshot + restart hygiene; pre-invite patches are small and test-gated | 6 — adds 90-day TestFlight cadence, keystore custody, plugin/site version coupling, Capacitor 9 migration, Apple subscription; no automated alerting |
| **Total** | **48** | **49** | **43** |

---

## 3. Factual errors found (quoting the plan)

### D1-fast
1. §2 Day 2 2.2 — "Throughput: 300–600 words/h (security:F11 says 600 at 60 calls/h; the curation analysis measured ≈ 300 effective because the fan-out is one 10-word group per 2 min; memory note 2026-11-04)". The fan-out is **five** ten-word groups per 2-minute pass (`prewarm.py:29-33` `PASS_MULTIPLIER 5`, `PASS_INTERVAL 2 min`, v-security:F11), i.e. 1,500 words/h enqueued; the binding limit is the 60 calls/h cap = 600 words/h (security:F11). The "≈ 300" rests on an uncited memory note, not on the fact base. Low impact (prewarm takes longer or shorter; nothing a friend sees).
2. §3 iPhone row — "Data export (`<a download>`) can hang the standalone window on iOS 18.4+ (WebKit 290847)". The bug report names iOS 18 (18.4 in the title) **and** iOS 16.7.10 (v-pwa:F8), so it is not an "18.4+" regression; older home-screen apps are affected too. Low impact.

### D2-solid
1. §6 friend message — "在微信内置浏览器里喇叭是灰的，请用系统浏览器打开", and §3 notes "if the 发音 button is greyed … the friend is in a WebView (WeChat/QQ in-app)". The fact base has WeChat XWeb speechSynthesis as **unknown** (android:F10 and open question 6; pwa:F9), and caniuse lists QQ Browser (`and_qq 14.9`) as **supporting** synthesis (v-captool:F15). Stated as fact to friends; may be wrong in both directions.
2. §2 Day 3 3.5 — "概览 shows `jobs.queued` draining at ≈ 6 calls/10 min". With `WD_AI_HOURLY_CALL_CAP=60` the ceiling is 10 calls per 10 minutes (security:F11; `budget.py` hourly cap). Arithmetic slip; no friend impact.
3. §2 Day 3 3.3 — "the pwa verifier read the WWDC transcript as ambiguous, so expect at most one extra login". v-pwa:F8 says the WWDC23 cookie-copy sentence is **macOS-specific** ("Safari copies website cookies when it is added to the Dock"), not ambiguous; the Safari 17.2 blog (ios:F17) is the iOS source. Conclusion unchanged.
4. §5 — "pin `@capacitor/*` 8.6.x — never 8.4.x/8.5.0 (CVE-2026-103922 … fixed in 8.5.1". The advisory's patched versions are 6.2.2, 7.6.9, **8.4.3**, 8.5.1 (v-captool:O1); 8.4.3 is safe. Nuance only; the 8.6.0 advice is right.
5. §2 Day 4 4.2 watch cron — greps `system_events` for `provider_blocked`; no such kind exists in `backend/wd` (grep today; existing kinds: `claude_auth`, `budget_*`, `backup_failed`, `downtime`, `claude_unavailable`). Harmless no-op, but the cron will never report provider cooldowns as the comment implies.

### D3-apps
1. §2 Phase 2 2.4 — "`select name, cooldown_until, last_error from provider_state`". The table's key column is `provider`; there is no `name` column (`docs/SCHEMA.sql:542-549`). The query errors.
2. §2 Phase 2 header — "Phase 2 — D2 (≈ 3.5 h)" versus its own tasks 2.1 (20 min + login) … 2.6 ("4–5 h; may spill to D3 morning"): ≈ 6 h on a Friday evening. Internal inconsistency in the effort budget; and the pitch's "≈ 3 + 2 + 6 person-days" lands ≈ 11 pd inside 14 calendar days for a part-time owner.
3. §2 Phase 1 1.3 — "`exec $SHELL -l && claude --version`". `exec` replaces the shell; the `&& claude --version` is never executed. Harmless.
4. §2 Phase 3 3.2 — "on launch night 10 friends × 2 devices fit the 20-logins/10-min window exactly, so one device each". The window is per client IP (`security.py:72`, v-security:F5); it binds only on a shared NAT, not across the circle on mobile data.
5. §6 friend message — "每天的 AI 额度有限，偶尔会显示「例句将稍后补齐」，第二天自动补上". The SPA string is 「今日 AI 额度已用完，例句将在明天补齐」 and the deferral target can be the next hour or the **1st of next month** (security:F8/F17, `budget.py` `next_month_resume`); "第二天自动补上" is wrong in the monthly case until H3 ships.
6. §6 friend message — "两周后会有 iPhone（TestFlight 内测）和安卓（安装包）版本". Contradicted by D3's own §5.7 table (≈ 6 pd, first artefacts D10–D14 only if enrolment, downloads and all web work land on schedule) and ios:F3 (multi-week enrolment outliers). A commitment to friends the plan cannot guarantee.
7. §2 parameters / 1.4 — "`/home/sqin/word-dance` … fixed to the repo defaults". The repo's documented checkout is `/home/sqin/word-Dance` (docs/DEPLOY.md:3, clivps step 4, ops.md recipes). Harmless to the service, but every ops.md path differs. Low.

---

## 4. Grafts for the synthesis (best ideas from the non-base plans)

From **D1-fast** (base = D2):
1. **Break-glass second admin** on Day 1: `WD_ADMIN_USERNAME=<unguessable> WD_ADMIN_PASSWORD=… wd create-admin` (no `--if-none`; verified in `security.py:738-764`) so a friend's typos can never lock the only admin for up to 24 h (security:F4, no unlock command).
2. **14-day single-use codes** instead of 7: slack for slow friends, still one account per code.
3. **`WD_AI_ENABLED="0"` on Day 1 regardless** of credential readiness: no 30-minute pause churn or misleading banner while DNS/TLS settle.
4. **`RunAtLoad` on the Mac backup-pull LaunchAgent** (the Mac sleeps after 1 idle minute, v-deploy:O5; D2's plist lacks it).
5. **Day-1 smoke with `wd stats` and `wd check providers`** (both exist) — answers the photo-provider question before any friend studies a word.
6. **The symptom → fact → move table** (lockout SQL with `.timeout`, 429 households, forgotten password, 「未登录」 banner, 「明天补齐」, queue flood + corrected two-statement cancel, 503 after prune, GFW re-IP once per instance) as the owner's support card.
7. **"Do not test wrong passwords from your own IP"** and the 21:00 carrier latency check on Day 1 evening.
8. **Onboarding-message ordering**: step 1 is "不要在微信里直接打开 → 在 Safari/浏览器打开", then "复制粘贴邀请码（输错也算次数）", the shared-image warning, the AI/privacy line, and the parent line for minors.
9. **Day-2 pilot**: if `wd claude-check` passes on Day 2, invite one iPhone and one domestic-Android friend that evening (D2 waits for Saturday).

From **D3-apps**:
10. **Day-0 friend poll with four fields**: phone model/OS (HarmonyOS 4 vs NEXT), exam stage, willingness to accept an App Store Connect invitation, the e-mail of their Apple Account.
11. **The app spec as the Phase-6 blueprint, verbatim**: exact `@capacitor/*@8.6.0` pins (never < 8.5.1); canonical non-redirecting `server.url` + the QA assertion `window.Capacitor.isNativePlatform() === true` on Android; `USE_EXACT_ALARM` + `syncDailyReminder` on launch/resume (or `isExactNotification:false`); TTS plugin mandatory on Android with `getSupportedLanguages()`/`openInstall()`; `plugins.SystemBars {insetsHandling:'native', initialViewportFitValueHint:'cover'}`; `ITSAppUsesNonExemptEncryption=NO`; friends as Marketing-role ASC users limited to the app, accepted with the invited Apple Account or the redemption code; availability at all 175 territories, never "Removed from Sale", "TestFlight Internal Only", never an external group; `/dl/` Caddy `handle_path` with the APK content-type and never `--with-caddy` again; `versionCode` YYYYMMDDn; keystore backed up twice; limited-distribution account (≤ 50 devices) before 2027; iOS deployment target 17; 80-day re-upload calendar.
12. **卓易通 as an explicit "experiment, never promise" cell** for HarmonyOS NEXT, with notifications/alarms/TTS inside the container marked untested.
13. **Per-brand APK install note** (Xiaomi 纯净模式 授权单次安装, vivo 应用安装 toggle, OPPO 外部来源应用, Huawei/Honor 纯净模式 退出, MIUI 自启动 + 省电无限制).
14. **H4 classifier scope regardless of credential**: policy-fetch string, `403 Request not allowed`, `ECONNREFUSED|ENOTFOUND`, `hit your .* limit` → short-retry class, credential-neutral banner (D2 ties W4 to a claude.ai login only).
15. **First-week watch-list table with "act when" thresholds** (e.g. today > $4 before noon → look for a mass-mark flood).
16. **The honest per-class sentence** ("iPhone: a convenience; domestic Android: a real upgrade; NEXT: nothing") as the wording of the app gate.

---

## 5. Blind spots none of the three plans covers

- **B1 — Server酱 Turbo sign-up on a single phone.** All three messages say "浏览器打开 sct.ftqq.com → 微信扫码登录". The login is a WeChat QR shown on the page; a friend holding only one phone cannot scan it with the same phone's WeChat — it has to be opened inside WeChat and long-pressed ("识别图中二维码"), or done on a PC. The fact base never exercised the sign-up UX (reminders:F5 assumes a QR scan). Verify it in the owner's own dry run on a phone and write the exact steps into the message.
- **B2 — The Server酱 nudge drops friends into WeChat's WebView**, the one context every plan tells them to avoid (separate cookie jar, no A2HS, TTS unknown, title-only card, reminders:F5). Android/HarmonyOS friends will tap the WeChat message and log in again there. Add one sentence to the message (and later to the digest footer in `digest_body`): 「收到微信提醒后，请点桌面图标打开」. Also unverified: a Server酱³ system notification opens the sc3 app, not the site.
- **B3 — Bark device-key rotation and invisible delivery failures.** Reinstalling Bark or changing iPhones yields a new key; the old one answers HTTP 400 → job `failed` visible only in `GET /api/admin/jobs` (reminders:F1: no DTO shows `webhook_status`). Only D2's cron notices; no plan tells friends to re-paste after a reinstall, and no friend-visible "last reminder delivered" exists.
- **B4 — Mainland Apple IDs are often phone-number IDs.** ASC invitations are e-mail-bound (v-ios:O4, forum 853308 "signed-in Apple Account does not match"); the TestFlight redemption code is the fallback (ios:F4). No plan's friend message says which Apple Account to use or mentions the code path.
- **B5 — Browser-engine floor for domestic browsers.** The SPA relies on `dvh`, `color-mix()`, `<dialog>.showModal`, `crypto.randomUUID` (capacitor:F13 → WebView ≥ 108); UC (U4 lineage, android:F10), 夸克 and old X5 cores may render broken. No plan has a "请改用系统浏览器/Chrome" fallback or puts an engine check in the pilot matrix.
- **B6 — No friend-facing AI status.** When the credential dies for days (expiry, policy fetch, 403), friends get dictionary-only cards, 「例句生成中…」 indefinitely and custom words stuck at 暂时无法校验 (deploy:F2), with no explanation; only the admin banner exists. A one-line notice on /today (or a WeChat heads-up template) is missing from all three.
- **B7 — HarmonyOS NEXT is never a test gate.** D1/D2 test a NEXT phone "if available", D3 tests "one domestic Android"; with 1–2 NEXT friends expected (android:F6), shortcut-standalone, cookie persistence and SpeechSynthesis should be verified on a NEXT device before inviting those friends, or they should be told it is untested.
- **B8 — Hourly-cap deferrals read as "tomorrow".** 60 calls/h plus morning SVG bursts (security:F8) show 「明天补齐」 for a one-hour wait (security:F17); D2/D3 fix the copy later, nobody warns friends in week 1.
- **B9 — Server酱 Turbo quota is per SendKey** (5/day free, failures count; 7-day full trial first). A friend reusing an existing SendKey, or whose trial ends, hits the ceiling silently; whether quota rejections return HTTP 200 is unverified (v-reminders:F6).

---

## 6. Recommendation

**Base: D2-solid.** It is the only plan whose first friend meets an icon, a WeChat hand-off card, truthful reminder channels and an owner who is paged when AI pauses or a webhook fails — the things this lens cares about. Graft D1's speed/ordering and D3's app spec onto it.

**Synthesised shape**
- **Phase 0 "Buy & test" (Day 0, 1 h)** — D2 Day 0 (Porkbun + DNSPod or Cloudflare DNS-only, Lighthouse Tokyo, the 401-vs-403 curl gate) + D3's four-question poll (phone/OS incl. HarmonyOS 4 vs NEXT, stage, ASC willingness, Apple-Account e-mail).
- **Phase 1 "Live" (Day 1, 3 h)** — D2 Day 1 + D1 grafts: break-glass admin, `WD_AI_ENABLED="0"` regardless, backup-pull agent with `RunAtLoad`, `wd stats`/`wd check providers` smoke, 21:00 latency check.
- **Phase 2 "Credential + icons" (Day 2, 3 h)** — D2 Day 2 unchanged (wrapper, `claude-check`, AI on, provider check → SVG cap, manifest/PNGs/cache headers). If `claude-check` passes early, run D1's two-friend pilot that evening.
- **Phase 3 "Hint + pilot" (Day 3, ≈ 5 h)** — InstallHint/WeChat card deployed; own-device checks including the Server酱 sign-up done on a phone (B1) and the WeChat interstitial test; Bark/Server酱 dry run; prewarm top 1,000–2,000 of the polled stages; pilots; a NEXT-device test is a gate before inviting NEXT friends (B7).
- **Phase 4 "Circle + truth" (Days 4–7)** — D2 as written (watch cron Day 4, staggered invites with 14-day single-use codes, webhook body-check Days 5–6 then Server酱³/企业微信/飞书, deferral-copy fix + restore drill + external monitor Day 7) with D3's H4 classifier scope regardless of credential.
- **Phase 5 "Observe" (Days 8–14)** — closed registration, numbers per device class, reminder taps.
- **Phase 6 "Apps" (gate on Day 14, not Day 30)** — D3 §5 is the spec verbatim; enrol with Apple the day the gate passes (1–3 days), iOS-first TestFlight Internal, then the signed APK; never promise dates to friends.

**Earlier than the plans had it:** icons + WeChat hand-off before any friend (vs D1), the pilot (vs D2), the app gate (vs D2's Day 30). **Later:** Apple enrolment, Xcode and app code (vs D3's D0/D3), Server酱³/企业微信/飞书 until the body-check patch, code expiry 14 days (vs 7).

**Mobile route per class:** iPhone Safari → home-screen app + Bark; iPhone-in-WeChat → hand-off card → Safari; GMS Android → Chrome install (WebAPK) + Server酱 Turbo or ntfy; GMS-less Android → vendor-browser shortcut + Server酱 Turbo (Server酱³ after Day 6) → the APK is their Phase-6 upgrade; HarmonyOS 4.x → Huawei Browser shortcut + Server酱 (APK possible); HarmonyOS NEXT → web-only + Server酱/企业微信, 卓易通 as an experiment only.

**Decision points:** D0 region (401 vs 403); D2 providers → SVG cap 1.00/0/keys; D3 Server酱 title/QR result and WeChat interstitial → message wording; D4 vendor-browser TTS results → per-brand advice; D14 close registration + app gate (≥ 3 active iPhone friends asking for an app, or ≥ 2 Android friends without a usable reminder/TTS); D30 re-check with month-1 spend and reminder-tap counts.
