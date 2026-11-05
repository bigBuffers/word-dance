# Judge J1 — lens: owner effort and calendar realism

Date 2026-11-04 · repo `/Users/sqin/word-dance` @ main 9ab13a5 · plans judged: `design-D1-fast.md`, `design-D2-solid.md`, `design-D3-apps.md` (all read in full) · fact base: all ten `facts/*.md` and ten `verify/*.md` (verify files override digests).

Owner profile applied throughout: solo, part-time, mainland China, Mac with node 22.23.4 / python 3.12, **no Xcode, no JDK/Android SDK**, api.anthropic.com only through a hand-started SOCKS tunnel (privoxy front), evenings + weekends available. "Realistic" below means: the hours fit into weekday evenings (≤ 3 h) and weekend days (≤ 6–8 h) with a first-timer multiplier on every console/toolchain step (deploy slice: 2–3.5 h first time vs ~1 h repeated).

Method: every command the plans rely on that is not already in the fact base was checked read-only in the checkout (`backend/wd/security.py:734-766`, `backend/wd/diag.py`, `backend/wd/cli.py`, `docs/SCHEMA.sql`, `docs/ops.md`, `docs/API.md`, `deploy/install.sh:1-30`, `backend/wd/backup.py`, `grep` for emitted `system_events` kinds) and on the Mac (`ls ~/Library/LaunchAgents`). Nothing was written outside this file; no server, build or real `claude` was run.

---

## 1. Scores (0–10 per criterion, total /60)

| Criterion | D1-fast | D2-solid | D3-apps |
|---|---|---|---|
| speed_to_first_friend | **9** | 6 | 6 |
| factual_correctness | **9** | 8 | 7 |
| completeness_both_platforms | 7 | 7 | **9** |
| owner_effort_realism | **8** | 6 | 3 |
| friend_experience | 7 | **9** | 8 |
| risk_and_maintenance | 7 | **8** | 5 |
| **total** | **47** | **44** | **38** |

### D1-fast — 47
- **Speed 9.** Day 0 purchases (≈ 45 min), Day 1 build, friends technically able to log in Day 1 night, pilot friends Day 2. Nothing is gated on code. The only faster path (Mac + Cloudflare Tunnel) is correctly rejected (deploy:F9, hosting:F17).
- **Factual 9.** Every runbook claim I could check verified: `create-admin` without `--if-none` really creates a second admin (`security.py:738-764`, username rule `^[A-Za-z0-9_一-龥]{2,32}$` at `schemas.py:52`); `wd stats`, `wd check providers`, `wd check db --db` exist (`diag.py:28,255-257`); `sessions(user_id, ip, user_agent, created_at)` (`SCHEMA.sql:87-95`); `$DATA/tmp` exists (`config.py:189-190`; ops.md:64 is the exact drill line); both Mac agents `com.word-dance.server` and `com.word-dance.backup` exist, so stopping both is right. Errors found: the Ubuntu 22.04 fallback `PY=python3.12` cannot work (`install.sh:12` is the literal `PY=python3`), an over-broad CVE range, and an unverified "≈ 300 words/h" figure (see §2). None affects the primary path.
- **Completeness 7.** Per-device table covers iPhone/WeChat/GMS/GMS-less/HarmonyOS 4/NEXT; the app route (§5) is fully specified with tooling, CVE pin, USE_EXACT_ALARM/re-arm notes, TestFlight-internal and APK mechanics — but deliberately unscheduled ("decide at day 28"). The owner asked to *plan* an Android app; D1 plans it but will not start it without evidence. Acceptable, not complete.
- **Effort realism 8.** Mandatory ≈ 1.3 person-days to day 14 is the only budget that fits a part-time owner. Day 1 "3–4 h hands-on" is optimistic by ~1 h for a first timer (12 numbered steps incl. launchd plist, credential wiring, phone tests; deploy slice 2–3.5 h for its steps 1–7 alone, hosting slice 6–9 h total), but D1 explicitly lets 1.10 slip and keeps everything else as 10-min/day watch items plus *triggered* patches. The triggered model is the right one for scarce evenings.
- **Friend experience 7.** Week 1 ships no icon/manifest (unless the Day-1 test triggers W1) and no in-app WeChat handoff — the onboarding message carries that load (it is the most complete of the three: throttle warning, shared images, speech caveat, AI disclosure). 「明天补齐」 copy stays until "later". Bark/Server酱 from Day 2.
- **Risk 7.** Wrapper + pinned CLI + model pin, break-glass admin (unique to D1 and cheap insurance against the no-`unlock` lockout), off-box pull with `RunAtLoad`, restore drill Day 2, GFW re-IP runbook, 21:00 latency gate. Missing: any alerting (manual 概览 only), external uptime monitor, console snapshot.

### D2-solid — 44
- **Speed 6.** Site live Thursday, friends Saturday by design: invites are gated on B1–B3 (icons, cache headers, InstallHint 3–4 h) and dry runs. Two calendar days lost to polish that iOS 26 does not need (pwa:F7 "zero requirements") and a message could cover.
- **Factual 8.** Runbook consistent with the fact base; `POST /api/admin/push/run` (API.md endpoint 74) exists; cookie-`Secure` reasoning correct (WD_PUBLIC_URL https ⇒ Secure on all requests, security:F6). Nits: "claude.ai … answer 403" (v-clivps:O6 measured 302 for claude.ai, 403 for platform.claude.com); the watch cron lists `provider_blocked`, which no code emits (only the schema comment), and omits `claude_paused`/`claude_overloaded`, which are emitted (`admin_ops.py:328`, `ai/common.py`); webhook patch 4–5 h vs the reminders slice's ≈ 1 person-day; Lighthouse default firewall "22/80/443" unverified.
- **Completeness 7.** Same device table quality as D1; phase 2 app route detailed with the verifier corrections; trigger on Day 30. Equivalent to D1.
- **Effort realism 6.** 24 h in week 1 = 3 h every weekday evening + 6 h Saturday + 3 h Sunday, then ≈ 1 pd in week 2. Feasible for a motivated owner but rigid: any slip (copy-mirror test, InstallHint tests, DNS) pushes the Saturday invites. The custom watch cron is a new artefact the owner must debug (and it queries kinds that never fire).
- **Friend experience 9.** Best web-only experience: real icon/name on both platforms, in-app WeChat handoff, Bark/Server酱 dry-run before invites, webhook hardening Days 5–6 so 企业微信/飞书/Server酱³ can be offered truthfully, real deferral date Day 7, uptime monitor. Onboarding message good.
- **Risk 8.** Watch cron to the owner's own phone, external monitor, console snapshot, restore drill, ops notes, apt-stable CLI (no auto-update at all), conditional classifier patch. Missing: break-glass admin; cron kind list needs correction.

### D3-apps — 38
- **Speed 6.** Same Saturday first-friend as D2 (site live D1 with icons, but invites wait for credential + InstallHint). Could invite D1 night; the plan does not.
- **Factual 7.** The web runbook mirrors D1/D2 and is sound; the app spec is the best-integrated with verifier findings. Errors: `exec $SHELL -l && claude --version` never runs the second command; Phase-2 header "≈ 3.5 h" vs tasks summing to ≈ 5.5–6.5 h; "Apple's store CDN … no proxy" asserted without fact-base support (captool table: multiply download times 2–4×; ios open q 8); "pinned to stable so the binary does not change silently" conflates channel pin with `DISABLE_AUTOUPDATER` (clivps:F2) and leaves the owner's interactive `claude` runs free to update the shared launcher target.
- **Completeness 9.** Only plan that schedules both apps with every known gotcha: 8.6.0 CVE pin, origin-exact Android bridge, `webDir/index.html` requirement, USE_EXACT_ALARM + re-arm on resume, TTS plugin mandatory on Android, `ITSAppUsesNonExemptEncryption`, Marketing-role ASC users, all-territory availability, Caddy `/dl`, keystore custody, 2027 limited-distribution, HarmonyOS NEXT honesty, 卓易通 as experiment.
- **Effort realism 3.** The plan's own totals — 3 pd web (D0–D7) + 2 pd hardening + 6 pd apps, releases D9–D14 — put ≈ 11 person-days inside 14 calendar days, ≈ 64 h between D3 and D14 (≈ 5.8 h/day including workdays) for a part-time owner who also has to install Xcode (3.1 GB), JDK + SDK via the proxy, enrol with Apple (1–3 days typical, weeks on mismatch, ios:F3) and borrow a domestic Android test phone. "The apps never delay the web launch" is true for the VPS and false for the owner's evenings, which are the bottleneck. The ¥688 is paid on D0 before any evidence, against the reminders slice's explicit "observe a month" (acknowledged deviation).
- **Friend experience 8.** Web track = D2 (icons D1, handoff D2/D3, dry runs, hardening week 2) plus, if delivered, on-device reminders and TTS for iPhone/Android friends. Debits: the onboarding message promises apps "两周后" (expectation risk), iPhone friends must become ASC users and reinstall every ≤ 90 days.
- **Risk 5.** Web-side risk table is good, but no alerting, no break-glass admin, no uptime monitor; the app track adds permanent chores (80-day re-uploads, keystore, Capacitor 9 migration, site↔shell plugin coupling, Apple subscription) and doubles the QA matrix.

---

## 2. Factual errors (quote → contradicting evidence)

1. **D1 §2 Day 1 step 1.3** — "If the image was Ubuntu 22.04: … run install.sh with `PY=python3.12` (hosting:F7; install.sh uses `$PY`, deploy/install.sh:12)." → `deploy/install.sh:12` is the literal assignment `PY=python3`, not `${PY:-python3}`; an exported `PY=python3.12` is overwritten and the preflight (`install.sh:45`) tests the system `python3` (3.10 on 22.04) → exit 1. Fix: require the 24.04 image, or make `python3` resolve to 3.12 (`update-alternatives`/a PATH shim) before running the script. Low impact (24.04 is the default and the verifier's F7 says Tencent's own 2026 tutorials use it).
2. **D1 §5** — "Pin `@capacitor/*` ≥ 8.5.1 — 8.0–8.5.0 carry the critical proxy-path CVE-2026-103922" → v-captool:O1: affected 8.0.0–8.3.4, 8.3.5–8.4.2, 8.5.0; **8.4.3 is patched**. Recommendation unchanged; range over-broad.
3. **D1 §2 Day 2 step 2.2** — "Throughput: 300–600 words/h (… ≈ 300 effective because the fan-out is one 10-word group per 2 min; memory note 2026-11-04)" → v-security:F11 reads `PASS_MULTIPLIER 5`, `PASS_INTERVAL 2 min` and the 60-calls/h cap, i.e. the ceiling is 600 words/h and the "one group per 2 min" premise is not what the code does; the 300 figure is not in the fact base. Hedged as a range, so low impact on the plan's 3–7 h estimate.
4. **D2 §2 Day 2 step 2.1** — "(claude.ai/platform.claude.com answer 403 from your network without the tunnel — clivps-verify omission 6 …)" → v-clivps:O6 measured direct `https://claude.ai/` → **302**, `https://platform.claude.com/` → 403, `api.anthropic.com` → 403. Conclusion (browser side through the Mac proxy) still holds.
5. **D2 §2 Day 4 step 4.2 (watch cron)** — "kind in ('claude_auth','budget_daily','budget_monthly','budget_svg','backup_failed','downtime','provider_blocked')" → `provider_blocked` appears only in the schema comment (`docs/SCHEMA.sql:56`, `migrations/0001_init.sql:56`); no insert exists in `backend/wd` (grep), so that alert can never fire; the emitted kinds the cron does **not** watch are `claude_paused` (`routers/admin_ops.py:328`), `claude_overloaded` (`ai/common.py`) and `lease_lost`. `backup_failed` (`backup.py:183`) and `downtime` do exist.
6. **D3 §2 step 1.3** — "`exec $SHELL -l && claude --version` # re-login so ~/.local/bin is on PATH" → `exec` replaces the shell process; the `&&` branch never executes (only on exec failure). The owner lands in a new login shell and must type `claude --version` by hand. Compare D1's `. ~/.profile`.
7. **D3 §2 Phase 2 header** — "Phase 2 — D2 (≈ 3.5 h)" vs its own task 2.6 "4–5 h; may spill to D3 morning" plus 2.1–2.5 ≈ 1.3 h → ≈ 5.5–6.5 h on a Friday evening. Internal inconsistency that hides ~2–3 h of owner time.
8. **D3 §2 step 0.6 / §5.2** — "Apple's store CDN normally serves the mainland directly, so no proxy; let it run overnight." → no fact-base support; captool's requirements table says "Time (owner's proxy-dependent network: multiply by 2–4)" and ios open question 8 lists the realistic download time as unknown. Unverified assumption stated as fact.
9. **D3 §2 step 1.3** — "pinned to the stable channel so the binary under systemd does not change silently (clivps:F2)" → clivps:F2: native installs auto-update regardless of channel unless `DISABLE_AUTOUPDATER`/`DISABLE_UPDATES` is set; D3 sets it only in the wrapper (service spawns), so an interactive `claude auth login` as `sqin` can still update the shared `~/.local/share/claude/versions` target the wrapper execs. D1 also exports it in `~/.profile`; D2's apt route never auto-updates.
10. **D3 §0 pitch and §6 message** — "the Apple Developer enrolment (¥688, 1–3 days) … finishing in the background" / "两周后会有 iPhone（TestFlight 内测）和安卓（安装包）版本" → ios:F3 (medium): no SLA, 1–3 days typical, 2–4-week outliers on name/address mismatch; v-ios:F7/O2: TestFlight installability coupled to storefront state with a months-long Apple-side outage in 2025–26. A dated promise to friends is not supported.
11. **D3 §2 "Effort totals" + §5.7** — ≈ 3 + 2 + 6 = 11 person-days scheduled inside D0–D14 for a "solo, part-time" owner (the plan's own words). This is a sequencing/realism error rather than a mechanical fact error, but it is the plan's central claim.

Verified-correct claims worth recording (so the synthesis keeps them): D1's break-glass `create-admin` (no `--if-none`), `launchctl bootout … com.word-dance.backup`, `wd stats`/`wd check providers`/`wd check db --db`, the `sessions` SQL; D2's `POST /api/admin/push/run` (API.md:135,234) and `sqlite3 -readonly -cmd ".timeout 5000"` idiom; D3's `rsync` in the VPS apt list and `select username, role from users` done-check.

---

## 3. Grafts — concrete ideas from the non-winning plans the synthesis should adopt (base = D1)

- **G1 (D2)** Publish the A record on Day 0, right after the VPS exists (nothing listens; the copied DB closes the admin race anyway) so Day 1's TLS step never waits on propagation; keep ufw 22-only until the local health check.
- **G2 (D2, D3)** Make W1 — manifest + the five verified `sips` PNGs + three `index.html` lines (1 h, byte-identical in v-pwa:F5) — a fixed Day-2 Mac task, not a triggered one: it costs less than the test that would trigger it and gives every Android browser a real icon/name.
- **G3 (D2)** The 10-minute watch cron posting to the owner's own Bark/Server酱 URL (`sqlite3 -readonly -cmd ".timeout 5000"`, 6-h dedupe), with the kind list corrected to what the code emits: `claude_auth, claude_unavailable, claude_paused, claude_overloaded, budget_daily, budget_monthly, budget_svg, backup_failed, downtime, lease_lost`, plus health, `kv.claude.paused_until`, disk.
- **G4 (D2)** External uptime monitor on `/api/health` (15 min) and a Lighthouse console snapshot after Day 1: "monitor green + friend says 打不开 = mainland path problem" is the cheapest GFW diagnostic.
- **G5 (D2)** Install the CLI from the apt `stable` repo (`/usr/bin/claude`, no auto-update at all) — removes the interactive-run update hole without relying on remembered env vars; `install.sh` picks the path up automatically.
- **G6 (D2)** Day-7 real-date deferral copy (1.5 h) and the private ops-notes file (unlock SQL with `.timeout`, corrected cancel recipe, re-IP runbook, renewal dates).
- **G7 (D3)** Day-0 friend poll extended with iOS version and Apple-Account e-mail (keeps the app option open at zero cost); `apt-get install rsync` on the VPS; the longer reachability loop (Wikimedia, Openverse, sctapi, api.day.app, github); the post-copy done-check `select username, role from users`.
- **G8 (D3)** Origin pinning decided at domain time: one canonical host, no `www`, no apex→sub redirect, `WD_PUBLIC_URL` = that origin — so a later Capacitor shell (Android bridge is origin-exact, v-capacitor:O1) needs no domain change.
- **G9 (D3)** Keep D3 §5.3–5.6 as the app-track spec for whenever the trigger fires: exact `8.6.0` pin (CVE), `USE_EXACT_ALARM` + `syncDailyReminder` on `appStateChange`, `ITSAppUsesNonExemptEncryption=NO`, Marketing-role ASC users, availability left at all territories, Caddy `handle_path /dl/*`, keystore backup, 80-day calendar, per-brand sideload paths, EAS cloud build as the Xcode-download fallback.
- **G10 (D3)** The first-week watch table (check / how / act when) is the most usable daily checklist of the three.

---

## 4. Blind spots — covered by none of the three plans

1. **`rsync -a --delete` mirrors VPS-side deletions to the Mac.** A `rm -rf backups/` on the box (mistake, compromise) empties the only off-box copy at the next pull. Drop `--delete` or rotate the pull into dated folders; let Time Machine cover the pull directory.
2. **Unattended SSH from launchd.** The pull job needs a passphrase-less key or one loaded with `ssh-add --apple-use-keychain`; no plan names the key or tests the job once *from launchd* (D1's `ssh … true` runs in the interactive agent context).
3. **No safe pause points.** For a part-time owner the biggest calendar risk is a Day 1 that overruns. None of the plans marks where the evening can stop safely (after the local health check: service on 127.0.0.1, ufw 22-only, AI off, DNS not yet pointing) and resume next evening.
4. **SSH itself from the mainland to a Tokyo IP** can be slow or reset in the evening; none mentions Lighthouse's browser console (OrcaTerm) as the fallback for Day-1 work or the re-IP runbook.
5. **Stored-login expiry is discoverable in advance.** 2.1.318 exposes `loginExpiresAt` in `claude auth status` and `credential_expires_at` in `-p` JSON (v-clivps:O3); no plan adds it to the weekly routine, so expiry would still be discovered through a 30-min pause and a misleading banner.
6. **Renewal traps.** First-year Lighthouse promos renew at list (v-hosting:O6), `.xyz`-style domains renew at 7× (v-hosting:F14), Apple renews automatically via the Apple Account; no plan puts renewal dates into the ops notes.
7. **The friend's first evening.** The scheduler builds a batch from `max(next_push_at − 3 h, 00:00 local)` (reminders:F1), so a friend who registers at 21:00 gets the first 今日词汇 next morning; none of the onboarding messages says so, and prewarm covers only the polled stage's top words (others see 「例句生成中…」).
8. **D2/D3 leave the Mac `com.word-dance.backup` agent running** against a frozen database (harmless noise); only D1 stops it, and none says how to re-enable the Mac stack for `make dev` or the 14-day rollback.
9. **Event-kind drift.** `provider_blocked` is documented (schema comment) but never emitted; `claude_paused`/`claude_overloaded` are emitted but unwatched — anyone copying D2's cron or D3's watch list inherits the gap.
10. **Lighthouse traffic/overage alarm and auto-snapshot cost** (hosting rec 6) — tiny, owner-facing, missing everywhere.

---

## 5. Recommendation

**Base: D1-fast.** It is the only plan whose calendar fits a solo part-time owner (≈ 1.3 mandatory person-days to day 14, friends on day 2) and whose commands verified cleanly; D2 is the same architecture with more up-front code and a rigid 24-h week; D3 is the right app *spec* bolted to an impossible fortnight (≈ 11 person-days in 14 days with no Xcode/JDK installed).

**Synthesised shape**

- **Phase 0 — Buy & probe (Day 0, ≤ 1 h):** Porkbun + Alipay domain; DNS at DNSPod (TTL 600) or Cloudflare DNS-only (60 s); A record published at once (G1); one canonical host, no `www` (G8); Lighthouse Tokyo 2c4g, Ubuntu 24.04 only (no `PY` override exists); D3's reachability loop — 401 from `api.anthropic.com` and `platform.claude.com` or rebuild in Singapore; friend poll: phone/OS/stage/iOS version/Apple-ID e-mail (G7).
- **Phase 1 — Live (Day 1, budget 4–5 h, safe pause after the local health check):** D1 1.1–1.9 verbatim (user `sqin`, NodeSource, apt-stable `claude` (G5), Mac DB + images copied before `install.sh --with-caddy --with-ecdict`, caps 6/100, model pin, `WD_AI_ENABLED="0"`, break-glass admin, per-friend 14-day codes), DNS/TLS/HSTS check, backup pull **without `--delete`** and tested from launchd; W1 icons+manifest as a fixed 1-h Mac task (G2). Credential wiring (1.10) may slip to Day 2.
- **Phase 2 — AI on + pilot (Day 2–3, 2–3 h):** wrapper + owner-chosen credential → `wd claude-check` → AI on; Bark + Server酱 Turbo dry run on own devices; prewarm top 1,000–2,000 of the polled stage overnight; watch cron with real event kinds (G3) + uptime monitor + console snapshot (G4); pilot 2–3 friends on Day 2 evening (one iPhone, one domestic Android); restore drill; `sessions.ip` check.
- **Phase 3 — Circle (Day 3–7, ≤ 15 min/day):** staggered invites, 48-h SVG-cap decision, 21:00 latency check (> 5 % loss → Singapore), D3's watch table (G10), `claude auth status` expiry in the weekly routine.
- **Phase 4 — Evidence patches (Day 8–14, ≤ 1 pd):** InstallHint + WeChat handoff if friends stay in WeChat; webhook body check only if someone wants 企业微信/飞书/Server酱³; real deferral date (G6); registration `closed` on Day 14; ops notes with renewal dates.
- **Decision A (Day 14–28) — app go/no-go:** D1's triggers plus the owner's wish; prerequisites: ≥ 3 free weekend days inside a month, friends' iOS versions and Apple-ID e-mails, ≥ 2 domestic-Android users. If go: **Phase 5 — Apps over 3–4 weeks** using D3 §5 as the spec (G9): week A enrol (¥688) + Xcode/JDK/SDK downloads via proxy + skeleton; week B web adapter + TTS + safe-top CSS + QA on the owner's phones; week C TestFlight Internal Only (Marketing-role ASC users) + APK via Caddy `/dl` + install notes. Never promise friends a date.

**Mobile route per device class:** iPhone → Safari home-screen + Bark (app later, optional); iPhone-in-WeChat → 「在 Safari 中打开」 first; GMS Android → Chrome install + Server酱/ntfy; GMS-less domestic Android → vendor-browser shortcut + Server酱 Turbo (Server酱³ after the patch) — the class that justifies the APK; HarmonyOS 4.x → Huawei browser + Server酱 (APK possible); HarmonyOS NEXT → web + Server酱 only.

**Decision points:** Day 0 region (403 → Singapore) · Day 1 21:00 loss > 5 % → Singapore · Day 2 credential path (wrapper, credential-neutral) · 48 h SVG cap · Day 7 patch triggers · Day 14 `closed` · Day 14–28 app go/no-go.
