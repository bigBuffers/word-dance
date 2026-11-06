# word-Dance — manual QA checklist: shell, auth, onboarding, 词库, 生词库, 设置, 管理 (WP7)

Scope: the WP7 pages and components (`frontend/src/components/{layout,list,bank}`, `pages/{Login,Register,Welcome,Vocab,Bank,AddWords,Suggestions,Settings,Admin,NotFound}Page.tsx`). The study / today / screening / detail / history pages are checked in `docs/qa-study.md` (WP8); `docs/qa.md` (WP9) links both.

How to run: `make dev` (backend on :8000 with `WD_CLAUDE_BIN` = the fake claude, Vite on `http://localhost:5173`), or the installed service on `http://<LAN-ip>:8000`. Take every screenshot at **360 px** (phone, bottom TabBar) and **1280 px** (desktop, TopNav) and store them under `docs/screenshots/wp7/` as `<item>-360.png` / `<item>-1280.png`.

Status legend: **AUTO** = covered by `npm test` in this package (vitest, jsdom); **PENDING-MANUAL** = needs the running backend (WP1–WP6 routers) and a browser — to be ticked by the integrator; a ticked box `[x]` means verified on a real backend.

## 0. Automated gates (run first)

| Check | Command | Status |
|---|---|---|
| Types | `cd frontend && npm run typecheck` | AUTO — green |
| Unit / render tests | `npm test` | AUTO — green (utils `normalizeInput` ≥ 60 table rows, `format`, `date`; `usePolling`; `AttentionBadge` state machine + polling; `SuggestionRow` copy; `AddWordPreviewRow`; `WordRow` (incl. `onlyStages` chip narrowing and the 课标外 chip); `StageChips`; `Pager` + `usePagedList`; `LetterIndex`; `AppLayout` badges; `LoginPage` / `RegisterPage` health-flag branches; settings import reduction; vocab/bank helpers) |
| Build | `npm run build` | AUTO — `dist/index.html` + lazy page chunks |
| Copy rules | `npm run lint` (= `scripts/check-copy.mjs`), also `grep -rn '[一-龥]' frontend/src --include=*.tsx \| grep -v i18n` → empty; forbidden glossary term absent | AUTO — green |

## 1. Shell (`components/layout`)

- [ ] PENDING-MANUAL — 360 px: bottom TabBar 今日 · 词库 · 生词库 · 记录 · 我的, safe-area padding, active item tinted; page content never hides behind the bar (`--tabbar-h` is set on `<html>` while the bar is shown) and toasts float above it.
- [ ] PENDING-MANUAL — 1280 px: sticky TopNav with the same items, 管理 appears only for an admin, display name at the right links to 我的.
- [ ] PENDING-MANUAL — number badge on 生词库 = `counters.suggestions_open + counters.attention` from `GET /api/auth/me`; it updates after accept/reject/undo of a suggestion, after bank adds/import and after 保留/重试 (no polling — verify in the network tab that only `/api/auth/me` is re-fetched).
- [ ] PENDING-MANUAL — dot on 今日 while today's batch has ungraded items (shell checks `GET /api/today` once per route change / tab return, at most every 60 s; WP8 pages may call `setTodayUngraded()` directly); no dot once everything is graded; no `/api/today` request before onboarding.
- [ ] PENDING-MANUAL — `/study` renders without TopNav/TabBar (full-viewport study card).

## 2. Login / register (`/login`, `/register`)

- [ ] PENDING-MANUAL — fresh server (`needs_setup:true`): 登录 shows 「尚无账号，首个注册的账号将成为管理员」 + 去注册 instead of 还没有账号？; 注册 shows 「首个注册的账号将成为管理员」 and **no** 邀请码 field; the first registration succeeds without a code and lands on `/welcome`; afterwards `GET /api/health.needs_setup` is false.
- [ ] PENDING-MANUAL — `WD_REGISTRATION_MODE=invite` after setup: 邀请码 field shown and required; wrong code → 邀请码无效或已过期 inline; `closed` → 登录 hides the 注册 link and `/register` shows 当前不开放注册.
- [ ] PENDING-MANUAL — login errors: wrong password → 用户名或密码不正确; 11th failure → 423 shown as 「登录失败次数过多，请 N 分钟后再试」; `?next=/bank` is honoured after login.
- [ ] PENDING-MANUAL — register validation: username hint (2–32 chars), password strength bar (red < 8 chars or = username, amber, green), 两次输入的密码不一致, optional 昵称 / 邮箱; server 409 `username_taken` → 用户名已被使用.
- AUTO — needs_setup / closed / invite / open branches, `?next=` propagation, error display (`LoginPage.test.tsx`, `RegisterPage.test.tsx`).

## 3. Onboarding (`/welcome`)

- [ ] PENDING-MANUAL — step 1: quick picks 小学生 → 小学 · 初中生 → 小学+初中 · 高中生 → 初中+高中 · 大学生 → 高中+四级+六级 · 职场人士 → 四级+六级 pre-select the 目标阶段 chips and the 主攻阶段 (segmented shows only selected stages; before any pick 小学+初中 with 主攻 小学 — the server default); the five 目标阶段 chips read 小学（课标二级词汇） / 初中（中考） / 高中（高考） / 大学英语四级 / 大学英语六级; toggling the last stage off is refused; 时区 is auto-detected (`Intl`) with 自动检测 to re-apply; 推送时间 defaults to 08:00; 下一步 → `POST /api/onboarding` (body has `current_stage` as a Stage string) → step 2.
- [ ] PENDING-MANUAL — step 2: up to 30 cards from `GET /api/screen/next?stage=auto&count=30`; 认识 (key 1) / 不熟悉 (key 2) / 跳过 (S) / 显示释义 (Space); each verdict posts `POST /api/screen/verdict {client_event_id, context:'onboarding'}`; the 5-s 撤销 toast calls `mark {action:'restore', context:'screen_page'}` and the card returns to the front; 「本阶段还剩 N 个未筛」 decreases; 再筛 30 个 loads another batch; 跳过引导 / 开始使用 → `POST /api/onboarding/complete` → `/today`.
- [ ] PENDING-MANUAL — gate: before completing, 词库 / 生词库 / 设置 (and 筛词, 单词详情) are reachable while `/today`, `/history` redirect to `/welcome`; reloading `/welcome` with state `screen` starts at step 2.

## 4. 词库 (`/vocab`)

- [ ] PENDING-MANUAL — tabs 全部 / 小学 / 初中 / 高中 / 四级 / 六级 (last tab remembered in `localStorage['wd.vocabTab']`; at 375 px and 360 px all six fit without horizontal scrolling); 「共 N 个词」 updates (`aria-live`); on the full seed 六级 + 仅六级新增（不含四级） shows `data/seed/stats.json` `first_stage.cet6`, 初中 shows the toggle as 仅初中新增（不含小学）; the toggle is hidden on 全部 and on 小学; a word outside every official list (search for one from `DIFF.md`) shows a dashed 课标外 chip and appears only under 全部; rows show only the stages in my 目标阶段 plus the word's lowest stage (the detail page shows all of them).
- [ ] PENDING-MANUAL — search (250 ms debounce): `aband` finds abandon, `abandoned` finds abandon through forms, `放弃` finds abandon; status filter 未标记 / 不熟悉 / 已认识 / 已掌握; sort 学习顺序 / 字母 / 难度 (学习顺序 is the default: 全部 opens with 小学 words and the 小学 tab's first screen shows no 冠词 / 代词 / 介词); A–Z rail (sticky on ≥ 1024 px, chips below) filters by letter, letters without words disabled, keyboard arrows move between letters.
- [ ] PENDING-MANUAL — inline 不熟悉 / 认识: the row's badge changes at once (未标记 → 待学 / 已认识), the 5-s 撤销 toast calls `POST /api/words/{id}/mark {action:'restore', context:'browse'}` and the row returns to 未标记; wait 16 minutes and press 撤销 → 「撤销时间已过，可在「已掌握」中重新加入」; a word already in the bank shows 已在生词库 → sheet 已掌握 / 移除; a mastered word offers 不熟悉 (re-add).
- [ ] PENDING-MANUAL — 1280 px bulk mode: 批量选择 → checkboxes, 「已选 N 个」, 标记所选为不熟悉 / 认识 → one `POST /api/words/batch-mark`; the bulk controls are hidden at 360 px.
- [ ] PENDING-MANUAL — empty search 「没有找到“xxx”。想把它加入生词库？」 → 添加生词 opens `/bank/add?prefill=xxx`; pager: numeric on desktop, 加载更多 (append) on phone.
- AUTO — `WordRow`, `LetterIndex`, `Pager`/`usePagedList`, `optimisticState` / `markToast` / `markUndoable`.

## 5. 添加生词 (`/bank/add`)

- [ ] PENDING-MANUAL — paste `abandoned, children\nubiquitous；bases\tabc123`: live preview after 300 ms — ✓ 将归为原形 abandon（过去式）, ✓ 将归为原形 child, 词典中未找到，将由 AI 校验补全, 多个可能的原形，请选择 with chips base / basis, ⚠ invalid (client-side, no request); lines that fail the client rules never hit `GET /api/lookup`; 51 valid lines → 一次最多添加 50 个词 and the button is disabled.
- [ ] PENDING-MANUAL — pick `basis`: submitting sends `POST /api/bank/add` for the plain lines and `POST /api/bank/add-word {word_id}` for the chosen candidate; results show 已添加 / 重新加入 / 已在生词库 / 待 AI 校验 / 需选择原形 / 无效 badges with links; `ubiquitous` (待 AI 校验) polls `GET /api/words/{id}` every 3 s (≤ 30) and switches to 已识别 after the fake-claude `lookup_word` job, or to ⚠ + 替换为 “…” for a typo; 今天就学 adds 已加入生词库，今天就学 / 明天开始学 notes.
- [ ] PENDING-MANUAL — `?prefill=zzqx` pre-fills the textarea (from the 修改 button and the 词库 empty state); the 生词库 badge refreshes after the add.
- AUTO — `normalizeInput` table, `analyseInput` duplicates, `AddWordPreviewRow` branches.

## 6. 生词库 (`/bank`) and 待处理

- [ ] PENDING-MANUAL — tabs 待学 / 学习中 / 已掌握 / 已认识 / 已移除 / 待处理 with counts from `BankResponse.counts`; search, sort (加入时间 / 到期 / 字母 / 熟练度 / 反复次数); rows show StateBadge (学习中 · 3 天后), 第 N 次加入 when `times_added > 1`; 更多 sheet: 单词详情 / 备注 / 已掌握 / 重置进度 / 移除 / 不熟悉 (re-add); 已掌握 confirms first unless `mastery_suggested`, then shows the 8-s 撤销 toast calling `mark restore`; empty bank → 「还没有生词。在词库里点「不熟悉」，或直接添加。」 → 添加生词; FAB 添加生词 above the TabBar at 360 px.
- [ ] PENDING-MANUAL — 待处理 (make `lookup_word` fail with `FAKE_CLAUDE_MODE=invalid_word` or let a job die): ⚠ message with **修改** (row removed via `mark remove`, lands on `/bank/add?prefill=<input_text>`), **重试** (only for 暂时无法校验-type flags where `is_valid_english` is null → `PATCH {attention:'retry'}` → badge 重新校验中 with spinner, polling until resolved), **保留** (flag gone; an unrecognised word shows the muted 仅收藏 chip in 待学 and is never pushed; toast 已保留，仅收藏不推送), **删除**, **替换为 “X”** (`POST /api/bank/{id}/accept-suggestion`); each resolution removes the row from the tab and the TabBar badge drops (`refreshCounters`).
- [ ] PENDING-MANUAL — 立即整理 → `POST /api/bank/consolidate` → 已安排整理，稍后查看整理建议 (429 within 60 min → 操作太频繁); 整理建议 entry carries the `suggestions_open` badge.
- AUTO — `AttentionBadge` state machine, button set per flag type, 3-s polling and stop-on-resolve; `rowBelongsToTab`.

## 7. 整理建议 (`/bank/suggestions`)

- [ ] PENDING-MANUAL — open rows with copy per type (fix_spelling 「“abandonned” 看起来是 “abandon” 的拼写错误。替换？」, lemmatize, merge_duplicate, invalid_word, split_phrase), 「N 天后过期」, 接受 (toast = `result.message_zh`) / 保留; 「已自动整理」 section with 撤销 inside 7 days → 已撤销; 409 `already_resolved` / `undo_expired` reloads the inbox; the badge refreshes after every decision; empty → 「暂无整理建议。每晚会自动整理你的生词库。」 + 立即整理.
- AUTO — `suggestionText`, `canUndo`, button sets (`SuggestionRow.test.tsx`).

## 8. 我的 (`/settings`)

- [ ] PENDING-MANUAL — 推送设置: every control saves on its own (`PUT /api/settings` with just that field, inline 已保存 for 2 s): 每日推送, 推送时间 (blur), 时区 select + 自动检测, 下次推送 shown in the user's timezone, 每日新词 0–50 / 每日推荐词 0–50 / 每日最多复习 0–300 (out-of-range values are clamped), 目标阶段 chips (never empty; 主攻阶段 follows), 主攻阶段 sent as a Stage string (`"current_stage":"cet4"` in the request body).
- [ ] PENDING-MANUAL — e-mail: without a verified address the 邮件推送 switch is disabled with 请先验证邮箱; 验证邮箱 → `POST /api/account/email/request-code` → 验证码已发送 → 6-digit input → `POST /api/account/email/verify` → 邮箱已验证 and the switch becomes enabled; 发送测试邮件 queues the test mail (`RecordingMailer` in dev shows subject 【word-Dance】测试邮件); with no SMTP the hint reads 服务器未配置邮件发送.
- [ ] PENDING-MANUAL — Webhook: enabling with an empty URL → 请先填写 Webhook 地址; `http://` or a private host (10.0.0.1) → the server validation error toast and the switch stays off; 格式 通用 JSON / 企业微信机器人 / 飞书机器人 / Server酱 / Bark; 发送测试 → 测试成功 or 「测试失败：…」.
- [ ] PENDING-MANUAL — 学习设置: 显示配图, 例句译文 点按显示 / 总是显示, 自动发音, 口音 美音 / 英音 each saved on change.
- [ ] PENDING-MANUAL — 账号: 昵称 / 邮箱 saved on blur (`PUT /api/account`; changing the e-mail clears verification), 修改密码 sheet (`POST /api/account/password`, other sessions revoked), 导出数据 CSV / JSON download the `word-dance-export-YYYYMMDD.*` files, **导入数据**: pick the JSON export **with its `review_logs` array** → the request body is only `{version, words}` (check the body size in the network tab) → result sheet 「已导入 N 个，跳过 M 个」 with per-row badges; pick the CSV export → round-trips verbatim; a corrupt file → 「导入文件过大或格式不正确（最多 2000 行）」 without a request; > 2,000 rows → the same message from the 400; 退出登录 → `/login`; 删除账号 asks for the password, then `/login`.
- [ ] PENDING-MANUAL — 关于与数据来源: version, ECDICT (MIT), 词表来源, 图片来源, AI notice.
- AUTO — `buildImportBody` (review_logs stripped, CSV verbatim, garbage → null), `toggleStageSetting`.

## 9. 管理 (`/admin`, admin only)

- [ ] PENDING-MANUAL — non-admin visiting `/admin` → `/today` with 没有权限 toast; admin sees the 管理 nav item.
- [ ] PENDING-MANUAL — 概览 renders the real `GET /api/admin/overview` + `/health`: tiles (users / 今日花费 vs 上限 with a meter / 本月花费 / AI 示意图额度 / 队列 / 上次调度), AI status (enabled, 已暂停 until, CLI 加固级别), the **照片 / AI 示意图 / 仅文字卡片** bar + legend summing to `with_content` (card-only segment is the textured neutral track), jobs by type, provider quotas table, health card, 24-h events.
- [ ] PENDING-MANUAL — 用户与邀请: table from `GET /api/admin/users`, 禁用 / 启用 (the current admin's own row is not disable-able from the UI), 设为管理员, 重置密码 sheet; 生成邀请码 → the code is shown once with 复制 and 「邀请码只显示一次，请立即复制」; the invites table lists uses / expiry.
- [ ] PENDING-MANUAL — 任务: status / type filters, 重试 per non-running job, 重排所有失败任务; run-once button only when `server.dev`.
- [ ] PENDING-MANUAL — AI: ledger table (`GET /api/admin/ai/calls`), 暂停 AI / 恢复 AI, 探测 claude → 「探测成功（flag tier N）」 (ONE real call ≤ $0.05 — integrator), 预生成 form (stage / limit / budget) → planned count toast.
- [ ] PENDING-MANUAL — 内容反馈: open reports with 重新生成 / 换图 / 忽略 (the resolved row leaves the open list); 事件 pager; 配置 shows masked secrets (`***`) with env/default source tags.
- [ ] PENDING-MANUAL — tables scroll horizontally inside their container at 360 px; no horizontal page scroll.

## 10. Cross-cutting

- [ ] PENDING-MANUAL — no horizontal scroll at 360 px on any WP7 page; tap targets ≥ 44 px; focus rings visible with keyboard navigation; dark mode (`prefers-color-scheme: dark`) keeps contrast on badges, meters and the image-mix bar.
- [ ] PENDING-MANUAL — `*` → 找不到这个页面 with 回到今日.
- AUTO — `grep -rn '[一-龥]' frontend/src --include=*.tsx | grep -v i18n` → empty; the forbidden term is absent (`npm run lint`, `zh.test.ts`).

## Screenshots

| Item | 360 px | 1280 px |
|---|---|---|
| login (needs_setup) | `login-setup-360.png` | `login-setup-1280.png` |
| register (invite) | `register-invite-360.png` | `register-invite-1280.png` |
| welcome step 1 / step 2 | `welcome-1-360.png`, `welcome-2-360.png` | `welcome-1-1280.png`, `welcome-2-1280.png` |
| vocab (cet6 new-only, bulk mode on desktop) | `vocab-360.png` | `vocab-bulk-1280.png` |
| add words preview + results | `add-360.png` | `add-1280.png` |
| bank + 待处理 | `bank-360.png`, `bank-attention-360.png` | `bank-1280.png`, `bank-attention-1280.png` |
| suggestions | `suggestions-360.png` | `suggestions-1280.png` |
| settings (import result sheet) | `settings-360.png`, `settings-import-360.png` | `settings-1280.png`, `settings-import-1280.png` |
| admin overview | `admin-360.png` | `admin-1280.png` |

All items above are PENDING-MANUAL in this work package: the backend routers of WP1–WP6 are not present in the WP7 worktree, so only the automated gates were run here.
