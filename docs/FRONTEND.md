# word-Dance — Frontend contract (React 19 + TypeScript 5.9 + Vite 8, Simplified-Chinese UI)

Package `frontend/`. Pins: `react@^19.3`, `react-dom@^19.3`, `react-router@^7.18` (**not 8**), `vite@^8.3`, `@vitejs/plugin-react@^6.1`, `typescript@~5.9`, `vitest@^5`, `jsdom@^30`; the shell's runtime packages exactly as pinned in mobile/package.json — `@capacitor/core@8.6.0`, `@capacitor/app@8.1.2`, `@capacitor/local-notifications@8.3.1`, `@capacitor-community/text-to-speech@8.0.2` (bump both together, §6.6). Plain CSS (custom properties), no UI kit, no CSS framework, no CDN assets, no web fonts. Data types come verbatim from `API.md` §9 (`src/api/types.ts`). UI copy comes from `src/i18n/zh.ts` (Section 8) and must follow the glossary in DESIGN §0.3.

## 1. Project layout

```
frontend/
├── index.html                      # <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">, theme-color, lang="zh-CN",
│                                   # the apple-mobile-web-app-* / mobile-web-app-capable metas, <link rel="manifest"> and <link rel="apple-touch-icon"> (home-screen install)
├── public/                         # copied verbatim to the dist root by Vite: favicon.svg · manifest.webmanifest (id "/", start_url "/today", scope "/", display standalone,
│                                   # colours = the light --bg, icons below, Android shortcuts 开始学习 → /study and 生词库 → /bank) · apple-touch-icon.png (180², opaque: iOS paints
│                                   # transparent pixels black) · icons/icon-{192,512}.png (purpose any, from favicon.svg) + icons/icon-maskable-{192,512}.png (from icon-maskable.svg:
│                                   # full-bleed brand square, glyph inside the 80 % safe zone). Regenerate on macOS with sips, no dependency: see "Icons" under Build below
├── vite.config.ts                  # base '/', build.outDir 'dist', server.proxy {'/api','/media'} → http://127.0.0.1:8000
├── tsconfig.json                   # strict, noUncheckedIndexedAccess
├── package.json                    # scripts: dev, build, typecheck (tsc --noEmit), test (vitest run), lint
└── src/
    ├── main.tsx  App.tsx  routes.tsx
    ├── api/client.ts               # request<T>(method, path, body?) — credentials same-origin, X-WD-Request: 1, JSON, error envelope → ApiError, 401 → auth:expired event
    ├── api/types.ts                # == API.md §9 (frozen)
    ├── api/endpoints.ts            # typed functions per endpoint (getToday(), gradeItem(id, body), …)
    ├── auth/AuthContext.tsx        # {user, settings, server, loading, login(), logout(), refresh(), updateSettings()} ; <RequireAuth/>, <RequireOnboarded/>, <RequireAdmin/>
    ├── i18n/zh.ts                  # all UI strings (Section 8) — the only place Chinese UI copy lives
    ├── hooks/                      # useApi, useToast, useLocalPref, useSpeech, useKeyboard, usePolling, useDebounce, useBottomBarOffset
    ├── native/capacitor.ts  NativeBridge.tsx   # the Capacitor shell integration (§6.6): no-ops in a browser; mobile/ holds the iOS / Android projects (docs/MOBILE_APP.md)
    ├── audio/serverAudio.ts        # server-side pronunciation clips (GET /media/audio, API.md 76): the fallback for a device without an English voice — the clip URL played in one <audio> element, a fetch only to diagnose a failure (§6.4); `clipUrl` carries `ServerFlags.audio_key` as `v`, so a switched voice is a new URL for the browser cache.
    ├── utils/                      # normalizeInput.ts (mirrors backend §5.1), srsPreview.ts (mirrors srs.py, consumes srs_trajectory.json in tests), highlight.ts, date.ts, format.ts
    ├── study/queue.ts              # pure reducer for the in-session queue (Section 5.2)
    ├── components/                 # Section 4 — FIXED sub-tree; every import path uses these directories (owners in brackets, TASKS)
    │   ├── ui/      Sheet ConfirmDialog Toast Tabs Segmented Switch Field EmptyState Skeleton Button        [P0]
    │   ├── word/    WordHeader SpeakButton StageChips StateBadge KindBadge                                  [P0]
    │   ├── layout/  AppLayout TopNav TabBar                                                                 [WP7]
    │   ├── list/    WordRow LetterIndex SearchBox Pager                                                     [WP7]
    │   ├── bank/    AttentionBadge AddWordPreviewRow SuggestionRow                                          [WP7]
    │   ├── study/   StudyCard ScreenCard ExampleList WordImage SessionSummary                               [WP8]
    │   └── stats/   HeatStrip ProgressRing                                                                  [WP8]
    ├── pages/                      # Section 2
    └── styles/global.css  tokens.css  (page CSS files next to their pages)
```

Import example: `import { StateBadge } from '@/components/word/StateBadge'` (alias `@` → `src`); no component lives directly under `components/`.

Build: `npm run build` → `frontend/dist`; FastAPI serves the files of `dist` itself — `/assets/*` `public, max-age=31536000, immutable`; `manifest.webmanifest` (and a future `sw.js` / `registerSW.js`) `no-cache`, so an install or update check always sees the current one; every other file of the snapshot (icons, `favicon.svg`) `public, max-age=3600` — and answers `index.html` (`no-cache`) for every other non-`/api`, non-`/media` path, **except** a path under `/assets/` that is not a file: that is a 404 `not_found` (a tab left open across a deploy asks for the old hashed chunk and must not receive `index.html` as a script). The installability surface is static (manifest, PNG icons, `apple-touch-icon`, the two `*-web-app-capable` metas): no service worker, no install prompt, no offline cache — on iOS 26 the home-screen bookmark opens standalone by itself, Android Chrome installs from the browser menu. Icons: `cd frontend && sips -s format png -z 192 192 public/favicon.svg --out public/icons/icon-192.png` and likewise 512 from `favicon.svg`, 192/512 `icon-maskable-*.png` and the 180² `apple-touch-icon.png` from `public/icon-maskable.svg` (macOS `sips` renders SVG; on Linux use `npx @vite-pwa/assets-generator` or `@resvg/resvg-js`). Dev: Vite on :5173 proxies `/api` and `/media` to :8000 (same-origin cookies).

## 2. Routes and pages

| Route | Page title (zh) | Component | Guard | Content |
|---|---|---|---|---|
| `/login` | 登录 | `LoginPage` | guest | 用户名 + 密码; link 注册 (hidden when `registration_mode='closed'` **unless** `needs_setup`); when `GET /api/health.needs_setup` is true a notice 「尚无账号，首个注册的账号将成为管理员」 with a 去注册 link replaces the normal hint |
| `/register` | 注册 | `RegisterPage` | guest | 用户名、密码（强度提示）、昵称（可选）、邮箱（可选）、邀请码 (shown when `registration_mode='invite'` and not `needs_setup`); with `needs_setup` the form shows 「首个注册的账号将成为管理员」 and no invite field (API.md endpoint 2 bootstrap rule) |
| `/welcome` | 欢迎使用 word-Dance | `WelcomePage` | user, `onboarding_state != 'done'` | step 1 我是… quick picks (小学生 → 小学 · 初中生 → 小学+初中 · 高中生 → 初中+高中 · 大学生 → 高中+四级+六级 · 职场人士 → 四级+六级; default before a pick 小学+初中 / 小学) pre-selecting 目标阶段 chips, 主攻阶段 segmented, 推送时间 time input, 时区 select (auto-detected) → `POST /api/onboarding`; step 2 筛词 (20–30 cards from `/api/screen/next?stage=auto&count=30`) with 跳过引导 → `POST /api/onboarding/complete` → `/today` |
| `/` | — | redirect | onboarded | → `/today` |
| `/today` | 今日词汇 | `TodayPage` | onboarded | header (date, 连续学习 N 天), progress ring `done/total`, chips 复习 · 新词 · 推荐词 · 再来一组, 顺延 N 个复习 note, 「例句生成中 N 个」 notice (from `counts.pending_content`), 整理建议 badge, 「继续昨天的学习（还剩 N 个）」 card when `previous_open_batch` is set, CTA 开始学习/继续学习, empty states (§6.1) |
| `/study` | 学习 | `StudyPage` | onboarded | the card session (Section 5); `?batch=<id>` loads `GET /api/batches/{id}`: with the grade bar when `batch.gradable` (today's, or yesterday's open batch), otherwise a read-only replay |
| `/screen` | 筛词 | `ScreenPage` | user | stage picker cards with unseen counts (`GET /api/stages`) |
| `/screen/:stage` | 筛词 · 四级 | `ScreenRunPage` | user | rapid 认识 / 不熟悉 triage (Section 5.4) |
| `/vocab` | 词库 | `VocabPage` | user | tabs 全部 / 小学 / 初中 / 高中 / 四级 / 六级 (six `fill` tabs; ≤ 479 px narrows the tab padding so they fit 375 px without scrolling), toggle 仅本阶段新增 (hidden on 全部 and on the lowest stage), search, status filter, sort, A–Z index, list with inline 不熟悉 / 认识, desktop bulk checkboxes |
| `/words/:idOrLemma` | 单词详情 | `WordDetailPage` | user | dictionary data, content, image (+ 换一张 / 不合适), SRS status, my history, actions 标为不熟悉 / 已掌握 / 移除 / 重置, 反馈问题 |
| `/bank` | 生词库 | `BankPage` | user | tabs 待学 / 学习中 / 已掌握 / 已认识 / 已移除 / 待处理 (attention), counts, search, sort, row actions, FAB 添加生词, 整理建议 entry with badge |
| `/bank/add` | 添加生词 | `AddWordsPage` | user | textarea (paste many), live preview per line, 备注, 今天就学 toggle, results list, ambiguous candidate chips; `?prefill=<text>` pre-fills the textarea (used by the 修改 button of a 待处理 row and by the 词库 「没有找到」 empty state) |
| `/bank/suggestions` | 整理建议 | `SuggestionsPage` | user | inbox: open suggestions with 合并/替换/删除 vs 保留; 「已自动整理」 section with 撤销 |
| `/history` | 记录 | `HistoryPage` | onboarded | 12-week heat strip, 连续学习, 反复遗忘 list, list of past batches |
| `/history/:batchId` | 10月12日 | `BatchPage` | onboarded | read-only batch with outcome chips; 「重新浏览」 → `/study?batch=` |
| `/settings` | 我的 | `SettingsPage` | user | sections 推送设置 / 学习设置 / 账号 / 关于与数据来源 |
| `/admin` | 管理 | `AdminPage` | admin | tabs 概览 / 用户与邀请 / 任务 / AI / 内容反馈 / 事件 / 配置 |
| `*` | 页面不存在 | `NotFoundPage` | — | 回到今日 |

Navigation: phone (< 768 px) bottom tab bar 今日 · 词库 · 生词库 · 记录 · 我的 (badge dot on 今日 while ungraded items exist, number badge on 生词库 = `counters.suggestions_open + counters.attention` from `GET /api/auth/me` — no extra poll; the 今日 page's 整理建议 badge uses `TodayResponse.suggestions_open`); desktop (≥ 768 px) top nav with the same items + 管理 for admins. Guards: `RequireAuth` (→ `/login?next=`), `RequireOnboarded` (→ `/welcome`; applied **only** to `/`, `/today`, `/study`, `/history`, `/history/:batchId` — 词库 / 生词库 / 筛词 / 单词详情 / 我的 are browsable before onboarding, exactly as their API endpoints are `U`; DESIGN §6.2), `RequireAdmin` (→ `/today` with toast).

## 3. State management

* **Session**: `AuthContext` loads `GET /api/auth/me` once; exposes `user`, `settings`, `server`, `counters` and `refreshCounters()` (re-fetches `/api/auth/me` after suggestion accept/reject/undo, bank adds/import and attention resolution so the badges stay current); `updateSettings(partial)` calls `PUT /api/settings` and replaces the cached object. 401 anywhere → context cleared → `/login?next=`.
* **Page data**: `useApi(fetcher, deps)` → `{data, error, loading, reload, setData}`; optimistic updates patch `setData` and roll back on error with a toast.
* **Study session**: `study/queue.ts` pure reducer (Section 5.2) + `StudyPage` effect that flushes pending grades. Pending grade events (with their `client_event_id`) are mirrored to `localStorage['wd.pendingGrades']` and flushed on reload before refetching `/api/today`.
* **Per-viewer conveniences in `localStorage` (never authoritative, all access try/catch)**: last 词库 tab, 译 toggle state, last 筛词 stage, pending grades.
* **Polling**: `usePolling(fn, intervalMs, {enabled, max})` — `/api/today` every 30 s while `pending_content > 0` and the tab is visible; `GET /api/words/{id}/content` every 5 s (max 24) for the visible card **only while `content_deferred_until` is null** (a non-null value — budget deferral / AI paused — stops polling and switches the card to the 「明天补齐」 copy, §5.1.5); `GET /api/words/{id}` every 3 s (max 30) for 待校验 / 重新校验中 custom words.
* **Toasts**: `useToast()` global queue, bottom-centre, ≤ 3 visible; undo toasts carry an action and a countdown (8 s for 已掌握, 5 s for list toggles). On a page with a sticky grade / verdict bar (`StudyCard`, `ScreenCard`) the bar publishes its reach through `useBottomBarOffset` (`--bottom-bar-h` + `html.has-bottom-bar`) and the toasts stack above the buttons instead of covering 认识 / 不熟悉.

## 4. Components (`src/components/<dir>/`, directories fixed in §1)

| Component | Props (essential) | Behaviour |
|---|---|---|
| `layout/AppLayout` / `TopNav` / `TabBar` | — | responsive shell, safe-area padding, badges |
| `study/StudyCard` | `item: StudyItem, revealed, onReveal, onGrade(grade), onMaster, onSkip, zhMode, showImage, preview: Record<Grade,string>, onlyStages?, danceMode?, danceToken?, danceAutoplay?` | front/back faces (§5.1; the two face `div`s are keyed `front` / `back` so the back's `WordHeader` mounts fresh at the reveal and its semantic autoplay fires); the front `WordHeader` gets `autoplay='form'` and `semanticEnabled={false}` (no meaning leak: no stage object, pose colour or ghosts), the back `autoplay='semantic'` + `replay='full'` when `danceMode === 'full'` (§5.1.2, §6.5); disables buttons while a grade is in flight; shows the 建议 badge when `mastery_suggested`; renders the deferred-content copy when `item.content_deferred_until` is set (§5.1.5) |
| `study/ScreenCard` | `word: WordBrief, onVerdict(v), onPeek` | headword + phonetic + 🔊, buttons 认识 / 不熟悉 / 跳过, swipe left/right on touch, 显示释义 peek link |
| `word/WordHeader` | `word: WordBrief, size, onlyStages?, dance?: DanceSpec \| null, playToken?, autoplay?: 'form' \| 'semantic' \| 'full' \| false, replay?: 'form' \| 'semantic' \| 'full', semanticEnabled?` | display form (long words shrink with `clamp()`), phonetic, `SpeakButton`, `StageChips` (`only={onlyStages}`), `KindBadge`; with `dance` the display form is a `DancingWord` (the heading carries `aria-label={display}` because the letter spans would otherwise be read letter by letter), a named list of syllable chips (`word.syllables`, the stressed chunk filled) sits before the phonetic, and 🔊 replays the dance (`replay` kind: `'form'` on the card front, `'full'` on the back and the detail page) together with the sound (§6.5) |
| `word/DancingWord` | `text, spec: DanceSpec \| null, playToken?, autoplay?: 'form' \| 'semantic' \| 'full' \| false, replay?, semanticEnabled?` | 单词之舞 (§6.5): one span per letter (`data-syl`, `--stressed`, `--silent`) inside a `.dword-stage` that draws the semantic's stage object (`--box` / `--roof` / `--shelf` / `--table` / `--tree` / `--bars`), the ghost copies of `multiply` and the pose colour (cold / hot / sad / colour words, `--pose-*` tokens); with `autoplay` the given kind plays once in the mount's layout phase (before the first paint), and whenever `playToken` moves after mount the `replay` kind plays: `'form'` = the letters enter syllable by syllable (`dances.spellPlan`), the syllables beat with the stressed one highest (`beatPlan`) and doubled letters jump together (`twinPlan`); `'semantic'` = `semanticPlan` (the colour pour starts from the heading ink); `'full'` = the form dance now and the semantic dance as a second play after `danceDuration + SEMANTIC_GAP_MS` (a timer cleared on unmount / the next play — a delayed `fill: 'backwards'` entrance would hide the letters during the form dance), all through `element.animate()`; `semanticEnabled={false}` strips the semantic (no object, ghosts, pose or motion); plain letters without a spec, and static (stressed syllable coloured, pose colour kept) without the Web Animations API or under `prefers-reduced-motion` |
| `study/ExampleList` | `examples, lemma, forms, zhMode` | highlights the headword/forms with `<mark>` (`utils/highlight.ts`: `\b(form1|form2…)\b` case-insensitive, longest first); per-sentence 🔊; 译 toggle per sentence or always |
| `study/WordImage` | `image: ImageMeta, showImages, onRefresh?, onFlag?` | fixed 16:10 box, `<img loading="lazy">`, skeleton while loading, attribution caption `图片：{title} · {creator} · {license} ↗` (card: 「系统生成卡片」, claude_svg: 「AI 生成示意图」), overflow menu 换一张 / 不合适 |
| `word/SpeakButton` | `text, lang, onClick?` | `useSpeech()` wrapper; disabled with tooltip 当前浏览器不支持语音 when nothing can pronounce — no `speechSynthesis`, not the shell, and no server clips (`ServerFlags.audio` false, §6.4) — unless an `onClick` (the dance replay) is passed, then it stays usable with the label 再跳一次 and only skips the speech (§6.5) |
| `word/StageChips` | `stages: Stage[], stageMin, only?` | 小学 / 初中 / 高中 / 四级 / 六级 chips in canonical order (`STAGE_ORDER` / `STAGE_INDEX` mirror `schemas.py`, index 1–5); `only` (the learner's target stages) hides the other chips except the word's lowest stage — lists and study cards pass `settings.stages` as `onlyStages`, the detail page and onboarding show all; `stages = []` (outside every official list) renders one dashed 课标外 chip; `cet6_star` adds ★ |
| `word/StateBadge` | `state: UserState \| null, srs?` | 待学 / 学习中 · 3 天后 (· 今天 / · 已到期 when the review is due) / 已掌握 / 已认识 / 已移除 / 未标记 |
| `bank/AttentionBadge` | `mine: UserWord, word: WordBrief, onKeep(), onRetry(), onEdit(), onRemove(), onReplace()` | state machine (API.md §9.1 / SCHEMA `needs_attention`): `needs_attention && attention_msg` → ⚠ msg + buttons 修改 (`onEdit`: `mark remove` then `/bank/add?prefill=`) · 重试 (`onRetry`, only when `word.is_valid_english === null`; `PATCH {attention:'retry'}`) · 保留 (`onKeep`: `PATCH {attention:'keep'}`; label 仅收藏 when `is_valid_english === false`) · 删除 (`onRemove`) · 替换为 “X” (`onReplace`, when `suggested_word`); `needs_attention && !attention_msg` → 重新校验中 (spinner, polls `GET /api/words/{id}`); `!needs_attention && is_valid_english === null` → 待校验; `!needs_attention && is_valid_english === false` → 仅收藏 chip (muted, no buttons); after `onKeep`/`onRetry` the page calls `refreshCounters()` |
| `list/WordRow` | `word: WordBrief, mine?, onMark(action), selectable?, selected?, onlyStages?` | list row: display · phonetic · translation_short · chips · state badge · quick buttons 不熟悉 / 认识 (或 已在生词库 → sheet 已掌握 / 移除) · checkbox in bulk mode |
| `list/LetterIndex` | `letters: {letter,count}[], active, onPick` | desktop sticky right rail; phone horizontal chips |
| `list/SearchBox` | `value, onChange (debounced 250 ms), placeholder` | — |
| `list/Pager` | `page, pageSize, total, onChange` | numeric pager on desktop; 上一页 / 「第 p / t 页」 / 下一页 on phone — every control replaces the page and scrolls to the top (the former phone 加载更多 appended pages and made the 词库 list grow without bound) |
| `stats/ProgressRing` | `done, total` | SVG ring, animated once |
| `stats/HeatStrip` | `days: {date, graded, goal_met}[]` | 12 × 7 squares, 5 intensity levels, tooltip 「10月12日 · 学习 32 个」 |
| `ui/Sheet` / `ConfirmDialog` / `Toast` / `Tabs` / `Segmented` / `Switch` / `Field` / `EmptyState` / `Skeleton` / `Button` | — | primitives; `ConfirmDialog` uses `<dialog>`; `Sheet` slides from the bottom on phones, modal on desktop |
| `bank/AddWordPreviewRow` | `preview: LookupPreview` | ✅ exact · 「将归为原形 abandon（过去式）」 · candidates chips (ambiguous) · 「词典中未找到，将由 AI 校验补全」 · ⚠ reason_zh · 「已在你的生词库中」 |
| `bank/SuggestionRow` | `s: Suggestion, onAccept, onReject, onUndo` | copy per type (§6.5) |
| `study/SessionSummary` | `summary: SessionSummary, onMoreNew, onMoreScreen` | §5.1.7 |

## 5. Interactions

### 5.1 Study card (`/study`)

```
[front]                                             [back]
┌──────────────────────────────────────────┐        ┌──────────────────────────────────────────┐
│ 复习 · 第 12/41                      跳过 │        │ abandon  /əˈbændən/ 🔊      高中 · 四级 · 六级 │
│                                          │        │ v. 放弃；抛弃  n. 放纵                     │
│              abandon                     │  tap / │ [配图 16:10 + 图片来源 · 换一张 ▾]          │
│            /əˈbændən/   🔊               │  space │ 例句                                      │
│          高中 · 四级 · 六级               │  ───►  │ • They had to **abandon** the car …  🔊 译 ▸│
│                                          │        │ 搭配  abandon ship · abandon a plan        │
│   提示：They had to ___ the car in …     │        │ 记忆  a-(去)+bandon(控制) → 脱离控制        │
│                                          │        │ 易混  abundant        词典释义 ▸            │
│            [ 显示释义 ]                   │        │ 第 3 次复习 · 间隔 8 天                     │
└──────────────────────────────────────────┘        │ 下次：模糊 → 明天 · 记住了 → 3 天后          │
                                                    │ [不熟悉] [模糊] [记住了]    已掌握 ✓   跳过  │
                                                    └──────────────────────────────────────────┘
```

1. **Front**: headword, phonetic, 🔊 (auto-pronounce if `settings.auto_pronounce`), stage chips, kind badge (复习 / 新词 / 推荐词 / 加练). 提示 reveals a cloze of the first example (headword/forms → `___`). `screen` items show 推荐词 and the buttons 认识 / 不熟悉 / 跳过 directly (no reveal). **单词之舞** (`settings.dance_mode !== 'off'`, §6.5): the headword is a `DancingWord` with the word's `DanceSpec`; when the front face mounts for a 新词, or for a 复习 / 加练 card with `srs.repetitions < 3`, the letters enter syllable by syllable and the syllables beat (the stressed one highest), the syllable chips under the word mark the stressed one; 🔊 and `P` replay it at any time, the reveal does not; 推荐词 never dance (the spec is withheld, the headword is plain).
2. **Reveal** (tap, 显示释义, Space): with `dance_mode === 'full'` and a `dance.semantic`, the headword on the back performs its meaning once as the face mounts (语义舞, §6.5: up rises, in walks into a box) — never on the front, so the meaning is not leaked before the learner has tried to recall it; back shows `meaning_zh` (or ECDICT translation when content is missing), image (if `show_images`), examples (highlighted, Chinese behind 译 unless `zh_examples='always'`), collocations, mnemonic, 易混 chips (from accepted `confusable_group` suggestions), collapsible 词典释义 (ECDICT definition/translation), SRS line, and the preview 「下次：模糊 → 明天 · 记住了 → 3 天后」 computed by `utils/srsPreview.ts` (same formulas as `srs.py`; verified against `GradeResponse.next_due_zh` in tests).
3. **Grade bar**: 不熟悉 (red, key 1) · 模糊 (amber, key 2) · 记住了 (green, key 3); secondary 已掌握 (outline → primary with 建议 badge when `mastery_suggested`, key 4) · 跳过 (text, key S). 已掌握 when suggested acts immediately with an 8-s 撤销 toast; 撤销 calls `POST /api/words/{id}/mark {action:'restore', context:'today'}`, which puts the exact prior SRS state back and re-opens the card (the reducer's `restore(itemId)` returns it to the queue; toast `study.restored`); a 409 `undo_expired` shows `errors.undoExpired`. The deliberate re-add from the 已掌握 list later is `{action:'unfamiliar'}` (re-add semantics). When not suggested a `ConfirmDialog` appears first («确定已掌握？该词将移出生词库，随时可在「已掌握」中恢复。»). `P` pronounce, `Z` toggle 译, `H` hint.
4. **Requeue**: after 不熟悉 / 模糊 or 记住了 on a new card (an **intermediate** grade: `GradeResponse.item.result === null` and `requeue_at` set — API.md 45), toast 「10 分钟后再见」 and the item **stays ungraded**: it remains in the reducer's `order` (never enters `graded`), re-enters the visible queue ≥ 10 cards later or at the end, and is shown when `requeue_at ≤ now`, otherwise the session waits with 「还有 1 个词将在 N 分钟后复现」 and a 现在就复习 link; the second grade is a new event with a fresh `client_event_id` and the server answers 200 (the item is only *done* when a grade returns a non-null `result`; `done/total` counts those). A 推荐词 graded 不熟悉 whose `GradeResponse.study_item` is non-null is appended to the end of the local queue as a 新词 card (toast `screen.addedToday`); null → toast `screen.addedTomorrow`.
5. **Content pending**: if `content_state === 'queued'` and `content_deferred_until === null` the back shows dictionary data + skeleton lines + 「例句生成中…」 and polls; if `content_deferred_until` is set (today's AI budget is spent, or AI is paused — API.md 24) the back shows the dictionary data **without** a skeleton, the notice `study.contentDeferred` 「今日 AI 额度已用完，例句将在明天补齐」, no polling and **no** 「生成例句」 button; `none`/`failed` → 「今天的例句暂时生成不了，先用词典释义学习」 plus a 「生成例句」 button (`POST /api/words/{id}/content/request`, then polling resumes; 409 `budget_exhausted` → toast `errors.budgetExhausted` and the card switches to the deferred copy, 503 → `errors.aiDisabled`, 60/day). The card is always usable.
6. **Optimistic grading**: the card advances immediately **and the event `{client_event_id, grade}` is POSTed at once** — there is no client-side undo window for grades (a posted grade with a fixed `client_event_id` cannot be reversed by replay); the only undo is 已掌握's 8-second 撤销 toast, which is a *server* `restore` (point 3). On network failure the event stays in `pending` and retries with backoff (1 s, 3 s, 10 s…); banner 「有 N 个结果待同步」 when the backlog > 1 for > 10 s. 409 `item_already_graded` is treated as success (refetch).
7. **Session summary** (`SessionSummary`): ring completes, counts (复习 26 · 新词 10 · 推荐词 15), 不熟悉 words list (chips → detail), 「连续学习 13 天」, buttons 再来一组新词 / 再筛一组推荐词 (while `can_request_more`) / 去筛词 / 回到今日. Calls `POST /api/today/complete`.
8. `?batch=<id>`: `batch.gradable === true` (today's batch, or yesterday's while it has ungraded items — the 「继续昨天的学习」 entry) → the normal session on the ungraded items with the grade bar; `false` → read-only replay: no grade bar, outcome chips shown.

### 5.2 Queue reducer (`study/queue.ts`, pure, vitest-covered)

State `{batchId, order: itemId[], cursor, revealed, requeue: {itemId, at}[], pending: GradeEvent[], graded: Record<itemId, result>, startedAt}`. Actions: `load(items)` (ungraded first, skipped after unskipped; an item with `requeue_at` set goes to `requeue`, not `graded`), `reveal`, `grade(itemId, grade, response)` — **final** (`response.item.result !== null`): moves the item to `graded`; **intermediate** (`result === null`, `requeue_at` set): removes it from the visible position and inserts it into `requeue` (it stays in `order`, never in `graded`); either way appends `response.study_item` to `order` when present — `skip(itemId)` (moves to the end), `tick(now)` (pulls due requeues back into `order` at `cursor + 10` or the end), `flushPending`, `restore(itemId)` (after a successful server `restore`: removes the item from `graded`, re-inserts it at `cursor`). There is **no** `undo` action: grades are posted immediately (§5.1.6) and undo exists only as the server `restore`.

### 5.3 Today page (`/today`)

Before a batch exists: 「今日词汇将于 08:00 推送」 + 立即生成 (`POST /api/today/build`) — the only build path besides the scheduler (再来一组 is disabled in this state: API 46 answers 409 `batch_not_ready` → toast `today.buildFirst`). While `building`: items are shown immediately and 再来一组 works; the header shows `today.pending(n)` 「N 个词的例句生成中」 **only while `counts.pending_content > 0`** (budget-deferred and AI-paused items are not counted, so the notice disappears when nothing is generating). When `previous_open_batch` is non-null a card 「继续昨天的学习（还剩 N 个）」 (`today.continueYesterday`) links to `/study?batch=<id>` — this is how a late session is finished after midnight (API.md 43/45); it is shown above today's CTA and also in the `status:'none'` state. After completion: 「今日完成 🎉 明天 08:00 见」 (`today.seeYou` is time-neutral: push times run 00:00–23:59) + 再来一组 + 去筛词 + 去词库. 顺延 note when `deferred_reviews > 0`.

### 5.4 Screening (`/screen/:stage`, `/welcome` step 2, 推荐词 cards)

Headword + phonetic + 🔊 only. 认识 (key 1 / swipe right) · 不熟悉 (key 2 / swipe left) · 跳过 (S) · 显示释义 peek (reveals translation, keeps buttons). Verdicts are posted immediately; **撤销 (5-s toast, key U) is the server undo** `POST /api/words/{id}/mark {action:'restore', context:'screen_page'}` (API.md 26: undoes the 认识 — deletes the `known` row — or the 不熟悉 — deletes the never-graded `new` row and its appended study row), after which the card is re-inserted at the front; 409 `undo_expired` → `errors.undoExpired`. Inside a running study session the same applies to 推荐词 cards (`context:'today'`; the reducer's `restore(itemId)` brings the card back). Progress 「本阶段还剩 1 203 个未筛」 from `remaining`. Batches of 30 with 再筛 30 个. Each verdict posts `POST /api/screen/verdict` with a `client_event_id`; 不熟悉 toast 「已加入生词库」, or 「已加入生词库，今天就学」 when `added_to_today` (the returned `study_item` is a second `kind='new'` row for the same word — inside a running study session it is appended to the local queue), or 「已加入生词库，明天开始学」 when today's new-word quota is full.

### 5.5 Vocabulary browser (`/vocab`)

`GET /api/vocab?stage=&new_only=&q=&status=&sort=&letter=&page=&page_size=50` (default sort 学习顺序 = `sort=freq`, the learning order of API.md 20: the tab's own stage first, grammar words after the content words of a stage; 字母 = `alpha`; 难度 = `difficulty`). Tabs reset the page; `仅本阶段新增` toggle appears for a specific stage above the lowest one (on 小学 it would be an identity filter — `stage_min = 1` ⇔ the xs flag — so it is hidden and ignored; label for 初中: 仅初中新增（不含小学）, for 六级: 仅六级新增（不含四级）). A word outside every official list (`stages = []`) shows the dashed 课标外 chip and is listed only under 全部 or by search. Search: English prefix (also matches inflected forms) or Chinese substring, debounced 250 ms. Row buttons call `POST /api/words/{id}/mark {action, context:'browse'}` and patch `my_state` in place with a 5-s 撤销 toast whose action is the server undo `mark {action:'restore', context:'browse'}` (API.md 26 — valid for 15 minutes, so the toast never lies). Desktop bulk mode: checkboxes + 「标记所选为不熟悉 / 认识」 → `POST /api/words/batch-mark`. `aria-live` count 「共 4 722 个词」. Row tap → detail.

### 5.6 Add words (`/bank/add`)

Textarea; on change (debounced 300 ms) each line (≤ 50) gets `GET /api/lookup?q=` → `AddWordPreviewRow`. Ambiguous rows show candidate chips; picking one marks the line to be committed via `POST /api/bank/add-word {word_id}`. 备注 field (≤ 500), 今天就学 switch. Submit → `POST /api/bank/add` for plain lines + `add-word` for chosen candidates → results list with badges 已添加 / 重新加入 / 已在生词库 / 待 AI 校验 / 需选择原形 / 无效 and links; 待校验 rows poll until resolved and then show 已校验 or ⚠ 未识别 + 替换为 “X”. A row's study-today note: 「已加入生词库，今天就学」 (`screen.addedToday`) when the server appended a study row (`added_to_today:true`); with the 今天就学 switch on, 「已加入生词库，明天开始学」 (`screen.addedTomorrow`) for every row that reached the bank without one — `added` / `readded` / `exists` / `pending_ai` with `added_to_today:false` (the 20/day cap of API.md 34/35, a word already in today's batch, or a provisional word that joins the first batch after validation); `ambiguous` / `invalid` rows and adds with the switch off carry no note.

### 5.7 Bank (`/bank`), suggestions (`/bank/suggestions`)

Tabs map to `state=new|learning|mastered|known|removed|attention`; rows show `StateBadge`, 第 N 次加入 chip when `times_added > 1`, due 「3 天后」, and `AttentionBadge` (待校验 / 重新校验中 / ⚠ / 仅收藏); swipe/overflow actions 已掌握 / 移除 / 重置 / 备注 / 查看. The 待处理 tab lists `needs_attention=1` rows with the `AttentionBadge` buttons (§4): 修改 → `mark remove` + `/bank/add?prefill=`, 重试 → `PATCH {attention:'retry'}` (toast `bank.retrying`), 保留 → `PATCH {attention:'keep'}` (toast `bank.keptOnly` for an unrecognised word, `common.saved` otherwise), 删除 → `mark remove`, 替换为 “X” → `accept-suggestion`; each resolution removes the row from the tab and calls `refreshCounters()`. A kept unrecognised word stays visible in 待学 with the muted 仅收藏 chip and is never pushed. Suggestion copy: `fix_spelling` 「“abandonned” 看起来是 “abandon” 的拼写错误。替换？」 · `lemmatize` 「“analyses” 是 “analysis” 的复数，合并？」 · `merge_duplicate` 「“colour” 与 “color” 是同一个词的不同拼写，合并？」 · `invalid_word` 「“zzzq” 似乎不是英文单词，删除？」 · `split_phrase` 「建议改学核心词 “negotiate”」; buttons 接受 / 保留; auto rows 「已自动归为 “run”」 with 撤销.

### 5.8 Word detail, settings, history, admin

* **Detail**: full ECDICT entry, 词形 chips, content, image with 换一张 (`POST …/image/refresh`, toast 「正在换图…」 then poll `GET …/image`) and 不合适 (`report {target:'image'}`), SRS panel, my last 20 actions, actions bar, 反馈问题 sheet (例句有误 / 释义有误 / 配图不合适 + note). When `content_state ∈ {none, failed}` the examples section shows a 「生成例句」 button (`word.generateExamples`) calling `POST /api/words/{id}/content/request` → toast `word.examplesQueued` and the 5-s content poll starts; 409 `budget_exhausted` → `errors.budgetExhausted`, 503 → `errors.aiDisabled`; hidden for 待校验 words (409 `invalid_transition`). A typed/deep-linked lemma that returns 409 `ambiguous_form` renders 「多个可能的原形，请选择」 (`bank.preview.ambiguous`) with the `details.candidates` as chips linking to `/words/{id}` instead of the detail body; `redirected_from` shows `word.redirected`.
* **Settings**: per-section forms saved per field (`PUT /api/settings`, inline 已保存). 推送设置: 推送时间, 时区 (select + 自动检测), 每日新词 (0–50), 每日推荐词 (0–50), 每日最多复习 (0–300), 目标阶段 chips, 主攻阶段 (`Stage` string, API.md §9.1), 邮件推送 (requires verified e-mail: inline 验证邮箱 flow → request code → 6-digit input), Webhook (switch, URL, format select 通用 / 企业微信机器人 / 飞书机器人 / Server酱 / Bark, 发送测试 — enabled only with the switch on and a saved URL; success → `settings.webhookOk`; failure → `settings.webhookFail(cause)` where the cause is chosen from the response's closed-set `reason` (API.md 17): `dns_failed` → `webhookFailDns`, `host_not_public` → `webhookFailPrivate`, `connect_failed` → `webhookFailConnect`, `timeout` → `webhookFailTimeout`, `tls_failed` → `webhookFailTls`, `invalid_url` → `webhookFailInvalidUrl`, `http_error` → `webhookFailHttp(http_status)`; without a usable reason the HTTP status, else `webhookFailConnect`; the English `error` string is never rendered (DESIGN §0.3)). 学习设置: 显示配图, 例句译文 (点按显示 / 总是显示), 自动发音, 单词之舞 (segmented 全部 / 只拼读 / 关 → `dance_mode` `'full'` / `'form_only'` / `'off'`, the hint `settings.danceHint` wrapping under the row, §6.5), 口音 (美音 / 英音). 账号: 昵称, 邮箱, 修改密码, 导出数据 (CSV / JSON), 导入数据 (file picker for a previous export → for `.json` the client parses the file and posts **only** `JSON.stringify({version, words})` — the export's `review_logs` array (up to several MB) is dropped client-side, API.md 11/75; for `.csv` the text is posted as is → `POST /api/bank/import {format, data}` → result sheet with the `AddResult` badges and 「已导入 N 个，跳过 M 个」; 400 `import_too_large` → `errors.importTooLarge`; an unparsable JSON file → `errors.importTooLarge` without a request), 退出登录, 删除账号 (password re-entry). 关于与数据来源: version, ECDICT (MIT), 词表来源, 图片来源 (Wikimedia Commons / Openverse / AI 生成示意图 / 系统生成卡片), 例句由 AI 生成 notice.
* **History**: `GET /api/history?from=-84d`, `GET /api/history/batches`; day rows 「10月13日 · 完成 41/41 🔥」 / 「10月11日 · 服务器离线」 (offline flag); 反复遗忘 list from `Stats.stubborn`.
* **Admin**: 概览 tiles (users, spend today/month vs caps, `svg_today_usd` vs `svg_daily_budget_usd` (`admin.images.svgBudget`), word image mix 照片 / AI 示意图 / 仅文字卡片 from `words.with_photo/with_claude_svg/card_only`, queue, provider quotas, scheduler), 用户与邀请 (table, 禁用/启用, 设为管理员, 重置密码, 生成邀请码 shown once), 任务 (table, filters, 重试, 重排所有失败), AI (ledger with a 来源 column, 当前提供方 tile (Claude / 备用模型, the fallback's availability 未探测 / 可用 / 不可用 from `ai.fallback_available` and its calls today), 备用模型已暂停 note, 暂停/恢复 keyed to the admin's own pause `ai.manual_paused_until` — the CLI's automatic pause (`ai.paused_until` set, `manual_paused_until` null, the fallback may be serving) shows as a 「Claude 自动暂停至 <time>」 note instead of 已暂停, so the only button offered is still 暂停 AI —, 探测 claude, 探测备用 when `ai.fallback_configured`, flag tier, 预生成 form stage/limit/budget), 内容反馈 (reports → 重新生成 / 换图 / 忽略), 事件, 配置 (masked). Admin copy may show error codes.

## 6. Copy, empty states, responsiveness, accessibility

### 6.1 Empty states (each has one action)

* 今日 (no bank, no batch): 「生词库还是空的——去词库里挑几个不熟悉的词，或者直接筛词」 → 去筛词 / 去词库.
* 生词库: 「还没有生词。在词库里点「不熟悉」，或直接添加。」 → 添加生词.
* 整理建议: 「暂无整理建议。每晚会自动整理你的生词库。」
* 记录: 「学习记录会在第一次学习后出现。」 → 开始学习.
* 词库 search: 「没有找到“xxx”。想把它加入生词库？」 → 添加生词 (pre-filled).

### 6.2 Responsive rules

Mobile-first; breakpoints 480 / 768 / 1024 px; body side gutter 16 px at every width (`padding-inline`); card max-width 720 px centred; tap targets ≥ 44 px; `100dvh` study card with the grade bar fixed at the bottom (safe-area aware); no horizontal scroll at 360 px; tables only in admin inside `overflow-x:auto`; lists are stacked rows on phones; `prefers-reduced-motion` disables flip/ring animations and (checked in JS, `DancingWord.canDance()`) the word dance, which then shows its static stress mark.

### 6.3 Visual system (`styles/tokens.css`)

```css
:root { color-scheme: light;
  --font-ui: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif;
  --font-word: "Charter", Georgia, "Source Serif 4", "Noto Serif CJK SC", serif;   /* English headwords only */
  --bg: #ffffff; --bg-2: #f5f6f8; --ink: #1d2433; --muted: #667085; --line: #e4e7ec;
  --brand: #3b5bdb; --again: #d6453d; --hard: #d98d0b; --good: #2f9e63; --screen: #7048e8; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark; --bg: #121620; --bg-2: #1a2030; --ink: #e8ecf3; --muted: #98a2b3; --line: #2a3345; } }
:root[data-theme="dark"] { color-scheme: dark; /* same dark palette */ }
body { background: var(--bg); color: var(--ink); font-family: var(--font-ui); margin: 0; }
```

Contrast ≥ 4.5:1 for text; grade colours always paired with labels; focus rings visible; every icon button has `aria-label`; the study card is `role="group"` with `aria-live="polite"` announcements (「已显示释义」); A–Z rail keyboard-navigable.

### 6.4 Pronunciation (`hooks/useSpeech.ts`, `audio/serverAudio.ts`)

Three routes, chosen per call by `speechRoute(accent)`:

```ts
export function speechRoute(accent: Accent): SpeechRoute | null {
  if (isNative()) return 'native';                                        // the shell's TTS plugin (§6.6)
  const synth = speechSupported();                                        // speechSynthesis + SpeechSynthesisUtterance exist
  if (synth) {
    const voices = window.speechSynthesis.getVoices();
    if (voices.length === 0 || pickVoice(voices, accent)) return 'synth'; // an English voice is listed (exact lang first — a Premium / Enhanced voice, then Google/Microsoft/Samantha/Daniel —, else any 'en') — or no list yet: Chrome fills it asynchronously, the browser default speaks meanwhile
  }
  if (serverAudioEnabled()) return 'server';                              // the list has no English voice and ServerFlags.audio says GET /media/audio has a provider
  return synth ? 'synth' : null;                                          // the browser default; null = nothing can speak
}
```

One voice at a time: every call first silences the others (`stopServerAudio()`, `speechSynthesis.cancel()`; the plugin flushes itself). **synth**: `new SpeechSynthesisUtterance(text)` with `lang`, the picked voice and `rate` (0.92 by default), then `speak()`; voices load asynchronously (`voiceschanged`), and the first user gesture unlocks audio on iOS — naturally satisfied because `speak()` is always triggered from a click/key handler. **native**: `speakNative` (same `rate`); when the plugin rejects — no TTS engine the plugin can reach (the Android container of HarmonyOS NEXT answers code `UNAVAILABLE` for ever: the plugin initialises its engine once at launch and never retries), no English voice, an engine error — the server clip speaks instead if `ServerFlags.audio` is true. **server**: `playServerAudio(text, accent, rate)` sets the clip URL `GET /media/audio?text&accent[&v=<ServerFlags.audio_key>]` (`clipUrl`; the server ignores `v` — a switched provider or voice is a new URL for the week-long browser cache; `diagnose` fetches the same URL) as the `src` of one shared `<audio>` element and calls `play()` synchronously — still inside the tap, so autoplay policies are satisfied however long the server takes; same-origin, so the session cookie goes along, the browser's HTTP cache keeps a clip for a week and the site's CSP (`default-src 'self'`, no `blob:`) allows it — at `playbackRate = rate` (pitch preserved), and resolves when the clip ends or when a later play / stop cuts it short (resolved, not rejected, like `speakNative`). Only when the element fails is the URL fetched once more to learn why (`diagnose`: 503 `audio_unavailable` → `off` / `busy` / `failed`, 400 → `invalid`, 401 → `auth`, 429 → `busy`, a 200 → `decode` — the server serves it, the device cannot play it, no response → `network`). `off` switches the server route off for the session (`setServerAudio(false)`; `AuthContext` sets the flag and the key (`setServerAudio(audio, audio_key)`) from `/api/auth/me` on every load, so the module-level `speak()` of auto-pronounce / key `P` knows it without the context — and the next `/me` reflects whatever the restarted server says); a browser that still has `speechSynthesis` then falls back to its default voice, silently, as before clips existed.

**What the learner hears about it** (the hook only; the module-level `speak()` stays silent) — one copy per cause (`speechFailureCopy`): `zh.word.voiceFetchFailed` (`network`: check the connection), `voiceBusy` (`busy`: the two synthesis slots, the waiters' cap or the 60 misses / minute budget), `voiceServerFailed` (`failed`: the provider broke — the server log says why), `voiceTextUnsupported` (`invalid`: the server refused the text), `voicePlayFailed` (`decode`: the device cannot play the clip), `voiceMissing` (`off`, or the plugin rejected without a server to turn to: no English voice on the device and none on the server), nothing for an autoplay refusal (`blocked`), a lost session (`auth`, which `client.ts` announces itself) or a call a later tap superseded (the hook numbers its calls: only the latest owns `speaking` and the toast). `supported` (→ `SpeakButton` disabled state) = speechSynthesis, the shell, or the module flag `serverAudioEnabled()` — true once `/me` lands, false again after a 503 `off`. Tests: `hooks/useSpeech.test.ts` (routes incl. the empty voice list, the browser-default fallback, the hook without speechSynthesis, copy per reason, one voice at a time, the double tap), `hooks/useSpeech.native.test.ts` (the plugin → server fallback and its copy), `audio/serverAudio.test.ts` (the URL played synchronously, the `v` fingerprint on it, the diagnosis, interruption), `auth/AuthContext.test.tsx` (`/me` → `setServerAudio`), `components/word/SpeakButton.test.tsx` (enabled by the server flag alone).

### 6.5 单词之舞 (`components/word/DancingWord.tsx`, `dances.ts`; docs/WORD_DANCE_DESIGN.md §4.1–4.2)

The headword of the study card and the detail page is a `DancingWord` when `settings.dance_mode !== 'off'` and the word has a `DanceSpec` (API.md §9 / §9.1: derived server-side from display + phonetic, `null` for phrases and words without a transcription). Two dances, both pure keyframe plans (`dances.ts`) fed to `element.animate()` — only `transform` / `opacity` / `color`, so they composite: **拼写舞** — the letters enter in reading order (85 ms apart, 55 ms for words of 8 letters or more, +150 ms — 120 ms for those long words — at every syllable boundary, `fill: 'backwards'`); **重音舞** — the syllables then beat in turn (300 ms each, the stressed one 330 ms), the primary-stressed one jumps highest (−0.6em, ×1.18, `--dance-accent` = `--brand-ink`), silent letters stay still and muted (`.dword__l--silent`), doubled letters jump together once more (`twinPlan`). No 小学 word exceeds 2.5 s (`danceDuration`; `dances.test.ts` pins the worst shapes: January, February, tomorrow, umbrella). **When it plays**: when the card's front face mounts for `kind='new'` cards and for `review` / `extra` cards with `srs.repetitions < 3` (never 推荐词 — `StudyCard` withholds their spec), and on 🔊 / key `P` at any time — `StudyPage` passes `danceAutoplay` (`DancingWord` plays it in a mount-only layout effect, before the first paint, so the word never flashes whole) and owns `danceToken` for key `P`, `WordHeader` adds the 🔊 replays on top; a remount (the reveal) does not replay the spelling + stress dance — the back face's `autoplay` is `'semantic'` only, and `DancingWord` replays only on a token that moves after mount. 🔊 keeps working where nothing can pronounce (no `speechSynthesis`, no shell, no server clips): `SpeakButton` stays enabled for the replay with the label 再跳一次 and just skips the speech; with server clips (§6.4) it speaks as well. **Static fallback**: no `element.animate` (jsdom) or `prefers-reduced-motion` → `.dword--static`, plain letters with the stressed syllable in `--brand-ink`, so the information survives without motion. The syllable chips (`<ol class="syl" aria-label=音节>`, `rab · bit`, stressed chip filled) show whenever the spec has two or more chunks; a one-chunk spec shows none. Sound and motion run in parallel, not in sync (Web Speech has no timing events worth using); the dance works without speech (Android WebView). **语义舞** (P2): a spec with `semantic` (`source: 'claude'`, chosen by `generate_dance` from the 30-primitive library — 28 at P2, `hop` / `onto` added by P3 —, API.md §9 `DancePrimitive`) plays its one meaning motion when the BACK face mounts at the reveal (`StudyCard` passes `autoplay="semantic"` there when `danceAutoplay` holds and `dance_mode === 'full'`), never on the front; 🔊 / `P` on the back replay `'full'` = spelling + stress + meaning, on the front `'form'` only. `dances.semanticPlan` maps each primitive to one motion (word-level: grow / shrink / spin / thud / float / stretch / squash / hop / enter / exit / arc / onto / under / behind / between / repeat / dim / glow; letter-level: rise / fall / dash / creep / split / join / shiver / shimmer / wave / droop / color; `multiply` fans ghost copies out and back), ≤ 2.5 s, em-based so it fits the card at 360 px; seven primitives stand on a small stage object drawn by CSS (`.dword-stage--box|roof|shelf|table|tree|bars`; the `onto` shelf sits behind the in-flow letters through an isolated stacking context, so descenders paint over it); `poseColor` gives cold / hot / sad and the colour words a rest colour that also serves as the static fallback (no size or letterform change, design principle 5). `dance_mode === 'form_only'` (`semanticEnabled=false`) drops the object, the ghosts, the pose and the motion. The setting lives in 学习设置 as the three-way segmented 「单词之舞」 全部 / 只拼读 / 关 (`dance_mode: 'full' | 'form_only' | 'off'`, P3; `settings.danceModes`).

### 6.6 Native shell (`native/capacitor.ts`, `native/NativeBridge.tsx`; docs/MOBILE_APP.md)

The same build is loaded by the Capacitor remote shell in `mobile/` (iOS / Android). `isNative()` is `Capacitor.isNativePlatform()`; in a browser it is false and every function below is a no-op, so nothing changes for web users. In the shell: `NativeBridge` (mounted once in App.tsx under the router and AuthProvider) installs the listeners — Android back button (history back, else minimise), resume, notification tap → navigate to its path — tags `<html>` with `native` / `native-<platform>` (`global.css` gives `.auth` / `.welcome` the top inset), and keeps the device's daily reminder in step with the settings: `syncDailyReminder(settings)` cancels notification 1001 and, when `push_enabled` and notifications are granted, schedules it daily at `push_time` converted from `settings.timezone` to the device clock (`localReminderTime`), title / body from `zh.native`, `extra.path = '/today'`; the notification is scheduled inexact (`isExactNotification: false` — the plugin's exact default opens the system alarm-settings page from `schedule()` on Android 14+); it runs once the session is known (never while `/api/auth/me` is loading and never because it failed or the session expired), on resume of a known session and whenever `push_enabled` / `push_time` / `timezone` change; only an explicit sign-out cancels it (`AuthContext.logout()` dispatches `auth:signed-out`, `client.ts` `AUTH_SIGNED_OUT_EVENT`). Permission is requested only inside a gesture: the push toggle (`requestReminderPermission`, SettingsPage) or — for a learner whose push was already on before installing the app — the `zh.settings.allowNotifications` button the page shows next to `zh.settings.reminderDenied` while `reminderPermission()` is not `granted`; a refusal shows `zh.settings.reminderDenied` and the setting is saved anyway. The settings page shows `zh.settings.nativeReminderHint` and hides the export links in the shell (a WebView cannot download them). Pronunciation goes to the TTS plugin (§6.4); when it rejects — code `UNAVAILABLE` (no TTS engine: the plugin initialises once at launch and never retries, so the Android container of HarmonyOS NEXT fails for ever), no English voice, an engine error — the server clip of `GET /media/audio` speaks instead when `ServerFlags.audio` is true, and only a failure of that too reaches the toast (§6.4: one copy per cause); `speakNative` settles an utterance that a later speak / stop flushes (the Android plugin never does), so no button sticks in the speaking state. The listeners are installed once (`navigate` kept in a ref). Tests: `native/capacitor.test.ts` (zone arithmetic incl. DST days, round-trip of push_time, inexact scheduling, sync / permission / listener behaviour with the plugins mocked), `native/NativeBridge.test.tsx` (no sync while loading, no cancel on a failed `/me`, cancel on sign-out, resume), `hooks/useSpeech.native.test.ts`, `pages/SettingsPage.native.test.tsx`, and the browser-mode case in `pages/SettingsPage.test.tsx`.

## 7. Quality gates

`npm run typecheck` (strict), `npm run build` (initial JS ≤ 200 KB gzip, per-route code splitting via `React.lazy`), `npm test` (vitest, jsdom): `normalizeInput` (mirrors the backend table), `srsPreview` (pins `tests/fixtures/srs_trajectory.json`: 1 → 3 → 8 → 20 → 51 → 133 → 180 **and** the `next_due_zh` strings — `10 分钟后` / `明天` / `N 天后` for 2–59 / `约 M 个月后` for ≥ 60 with `M = round-half-up(N/30)` — exactly as DESIGN §7 `humanize`), `highlight` (forms, punctuation, case, no partial-word matches), `queue` reducer (requeue placement; **an intermediate grade (`result:null` + `requeue_at`) keeps the item in `order` and out of `graded`, a later final grade on it moves it to `graded`**; skip ordering; pending flush; `restore` re-insert; `study_item` append; `load` puts items with `requeue_at` into `requeue`), `api/client` (envelope → `ApiError`, 401 event, header injection), one render test for `StudyCard` (reveal → grade bar; screen kind → 认识/不熟悉; `content_state:'failed'` → 生成例句 button; `content_deferred_until` set → `study.contentDeferred` copy, no skeleton, no 生成例句 button), stage chips (`StageChips`: five-stage order, `only` keeps the learner's stages plus the word's lowest, `stages: []` → the dashed 课标外 chip; `WordHeader` keeps its meta row for such a word even without phonetic / kind; `WordRow`, `StudyCard` and the `/vocab`, `/bank`, `/study` pages pass `onlyStages={settings.stages}` through to it).

## 8. i18n strings (`src/i18n/zh.ts`) — binding

```ts
export const zh = {
  app: { name: 'word-Dance', tagline: '每天几个词，稳稳记住' },
  nav: { today: '今日', vocab: '词库', bank: '生词库', history: '记录', me: '我的', admin: '管理', about: '关于' },
  common: { save: '保存', saved: '已保存', cancel: '取消', confirm: '确定', back: '返回', retry: '重试', undo: '撤销', close: '关闭',
            loading: '加载中…', more: '更多', search: '搜索', all: '全部', none: '无', yes: '是', no: '否', delete: '删除', keep: '保留', undone: '已撤销',
            copy: '复制', copied: '已复制', loadMore: '加载更多', prevPage: '上一页', nextPage: '下一页', total: (n: number) => `共 ${n} 个词`, pageOf: (p: number, t: number) => `第 ${p} / ${t} 页`,
            backToToday: '回到今日', sort: '排序', status: '状态' },
  errors: { network: '网络开小差了，请稍后重试', unauthorized: '请先登录', forbidden: '没有权限', notFound: '找不到这个页面',
            rateLimited: '操作太频繁，请稍后再试', server: '服务器出了点问题，请稍后重试', csrf: '请求已过期，请刷新页面',
            invalidWord: '只能包含英文字母、空格、连字符、撇号和缩写点', tooManyWords: '一次最多添加 50 个词',
            weakPassword: '密码至少 8 位，且不能与用户名相同或过于常见', usernameTaken: '用户名已被使用', emailTaken: '邮箱已被使用', invalidEmail: '邮箱格式无效',
            invalidCredentials: '用户名或密码不正确', accountLocked: (s: number) => `登录失败次数过多，请 ${Math.ceil(s / 60)} 分钟后再试`,
            registrationClosed: '当前不开放注册', invalidInvite: '邀请码无效或已过期', budgetExhausted: '今日 AI 额度已用完，例句将在明天补齐',
            aiDisabled: 'AI 功能暂时关闭', emailNotVerified: '请先验证邮箱', smtpUnconfigured: '服务器未配置邮件发送', webhookUnconfigured: '请先填写 Webhook 地址',
            undoExpired: '撤销时间已过，可在「已掌握」中重新加入', importTooLarge: '导入文件过大或格式不正确（最多 2000 行）' },
  auth: { login: '登录', register: '注册', logout: '退出登录', username: '用户名', password: '密码', password2: '再次输入密码',
          displayName: '昵称（可选）', email: '邮箱（可选）', invite: '邀请码', noAccount: '还没有账号？', hasAccount: '已有账号？',
          usernameHint: '2–32 个字符，字母、数字、下划线或中文', passwordHint: '至少 8 个字符', mismatch: '两次输入的密码不一致',
          needsSetup: '尚无账号，首个注册的账号将成为管理员', firstUser: '首个注册的账号将成为管理员', goRegister: '去注册' },
  welcome: { title: '欢迎使用 word-Dance', step1: '先告诉我们你的目标', whoAreYou: '我是…', roles: { xs: '小学生', zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' },
             stages: '目标阶段', currentStage: '主攻阶段', pushTime: '每日推送时间', timezone: '时区', detectTz: '自动检测',
             step2: '花两分钟筛一筛', step2Hint: '认识的点「认识」，不熟悉的会进入生词库', skip: '跳过引导', finish: '开始使用', next: '下一步' },
  stages: { xs: '小学', zk: '初中', gk: '高中', cet4: '四级', cet6: '六级', xsFull: '小学（课标二级词汇）', zkFull: '初中（中考）', gkFull: '高中（高考）', cet4Full: '大学英语四级', cet6Full: '大学英语六级',
            newOnly: '仅本阶段新增', newOnlyZk: '仅初中新增（不含小学）', newOnlyCet6: '仅六级新增（不含四级）', outside: '课标外', star: '六级星标词' },
  today: { title: '今日词汇', streak: (n: number) => `连续学习 ${n} 天`, counts: { review: '复习', new: '新词', screen: '推荐词', extra: '加练' },
           deferred: (n: number) => `另有 ${n} 个复习顺延到明天`, pending: (n: number) => `${n} 个词的例句生成中`,
           start: '开始学习', resume: '继续学习', notYet: (t: string) => `今日词汇将于 ${t} 推送`, buildNow: '立即生成',
           done: '今日完成 🎉', seeYou: (t: string) => `明天 ${t} 见`, moreNew: '再来一组新词', moreScreen: '再筛一组推荐词', goScreen: '去筛词', goVocab: '去词库',
           emptyBank: '生词库还是空的——去词库里挑几个不熟悉的词，或者直接筛词', suggestions: (n: number) => `整理建议 (${n})`, nothingMore: '今天没有更多可加练的词了',
           continueYesterday: (n: number) => `继续昨天的学习（还剩 ${n} 个）`, yesterdayBatch: '昨天的词汇', buildFirst: '请先生成今日词汇' },
  study: { title: '学习', reveal: '显示释义', hint: '提示', again: '不熟悉', hard: '模糊', good: '记住了', master: '已掌握', skip: '跳过', known: '认识', unfamiliar: '不熟悉',
           suggested: '建议', nextLabel: '下次', requeue: '10 分钟后再见', waiting: (n: number, m: number) => `还有 ${n} 个词将在 ${m} 分钟后复现`, reviewNow: '现在就复习',
           masterConfirm: '确定已掌握？该词将移出生词库，随时可在「已掌握」中恢复。', mastered: '已从生词库移除', restored: '已恢复到生词库',
           contentPending: '例句生成中…', contentFailed: '今天的例句暂时生成不了，先用词典释义学习', contentDeferred: '今日 AI 额度已用完，例句将在明天补齐', examples: '例句', collocations: '搭配', mnemonic: '记忆', confusable: '易混',
           dictionary: '词典释义', srsLine: (n: number, d: number) => `第 ${n} 次复习 · 间隔 ${d} 天`, srsNew: '尚未复习', lastMastered: (d: string) => `上次掌握于 ${d}`, addedTimes: (n: number) => `第 ${n} 次加入`,
           position: (i: number, n: number) => `第 ${i}/${n}`,
           kind: { review: '复习', new: '新词', screen: '推荐词', extra: '加练' }, pendingSync: (n: number) => `有 ${n} 个结果待同步`, zh: '译',
           summary: { title: '本次学习', unfamiliarWords: '还不熟悉的词', minutes: (m: number) => `用时 ${m} 分钟` },
           nextDue: { tenMin: '10 分钟后', today: '今天', overdue: '已到期', tomorrow: '明天', days: (d: number) => `${d} 天后`, months: (m: number) => `约 ${m} 个月后`, mastered: '已掌握', skipped: '已跳过' } },
  screen: { title: '筛词', subtitle: '快速筛一筛，不熟悉的会进入生词库', remaining: (n: number) => `本阶段还剩 ${n} 个未筛`, screenedCount: (n: number) => `本次已筛 ${n} 个`, another: '再筛 30 个', peek: '显示释义',
            addedBank: '已加入生词库', addedToday: '已加入生词库，今天就学', addedTomorrow: '已加入生词库，明天开始学', markedKnown: (w: string) => `${w} · 已认识`, allDone: '这个阶段的词都筛完了 🎉' },
  vocab: { title: '词库', searchPlaceholder: '搜索英文或中文', status: { all: '全部', unmarked: '未标记', unfamiliar: '不熟悉', known: '已认识', mastered: '已掌握' },
           sort: { freq: '学习顺序', alpha: '字母', difficulty: '难度' }, markUnfamiliar: '不熟悉', markKnown: '认识', inBank: '已在生词库', addedToBank: '已加入生词库',
           bulk: '批量选择', bulkUnfamiliar: '标记所选为不熟悉', bulkKnown: '标记所选为认识', selected: (n: number) => `已选 ${n} 个`,
           notFound: (q: string) => `没有找到“${q}”。想把它加入生词库？`, letters: '字母索引' },
  word: { title: '单词详情', forms: '词形', examTags: '考试标签', actions: '操作', reset: '重置进度', remove: '移除', changeImage: '换一张', flagImage: '不合适',
          resetConfirm: '确定重置进度？该词的复习进度将归零并回到「待学」，学习记录保留。', removeConfirm: '确定移除？该词将从列表中移除，不计入已掌握，之后可在「已移除」中重新加入。',
          report: '反馈问题', reportReasons: { wrong_meaning: '释义有误', unnatural_example: '例句不地道', bad_translation: '翻译有误', irrelevant_image: '配图无关', inappropriate_image: '配图不合适', other: '其他' },
          reported: '已收到反馈，谢谢', changingImage: '正在换图…', imageSource: '图片', generatedCard: '系统生成卡片', aiImage: 'AI 生成示意图', history: '我的记录', redirected: (f: string) => `已从“${f}”跳转`,
          generateExamples: '生成例句', examplesQueued: '例句生成中，稍后自动显示', speak: '发音', speechUnsupported: '当前浏览器不支持语音', voiceMissing: '这台设备没有英文语音，服务器也没有配置发音；可到系统设置安装英文语音包（设置 → 语音 / 文字转语音输出）', voiceFetchFailed: '发音加载失败，请检查网络后再试', voiceBusy: '发音服务器正忙，请稍后再试', voiceServerFailed: '服务器暂时无法生成这条发音，请稍后再试', voiceTextUnsupported: '这段文字无法发音', voicePlayFailed: '发音音频无法播放，请稍后再试', syllables: '音节', replayDance: '再跳一次' },
  bank: { title: '生词库', tabs: { new: '待学', learning: '学习中', mastered: '已掌握', known: '已认识', removed: '已移除', attention: '待处理' },
          add: '添加生词', addMany: '粘贴多个词，用换行或逗号分隔', note: '备注（可选，比如在哪里遇到的）', studyToday: '今天就学', submit: '添加',
          status: { added: '已添加', readded: '重新加入', exists: '已在生词库', pending_ai: '待 AI 校验', ambiguous: '需选择原形', invalid: '无效', validated: '已校验' },
          preview: { exact: '已识别', form: (l: string, k: string) => `将归为原形 ${l}（${k}）`, ambiguous: '多个可能的原形，请选择', none: '词典中未找到，将由 AI 校验补全', inBank: '已在你的生词库中', invalid: '无效',
                     duplicate: '与上面的词重复，已忽略' },
          invalidReason: { empty: '请输入单词', not_english: '请输入英文单词', charset: '只能包含英文字母、空格、连字符、撇号和缩写点', too_long: '太长了（最多 48 个字符）',
                           too_many_tokens: '最多 4 个单词组成的短语', bad_token: '请输入有效的单词', dot_in_long_token: '缩写点只能用于缩写（如 a.m.、e.g.）', leading_punct: '不能以连字符或撇号开头' },
          formKinds: { p: '过去式', d: '过去分词', i: '现在分词', '3': '第三人称单数', s: '复数', r: '比较级', t: '最高级', alt: '变体' },
          pendingAi: '待校验', notRecognised: '未识别', replaceWith: (w: string) => `替换为“${w}”`, unresolved: '未能识别该词，请检查拼写', keep: '保留', edit: '修改',
          retry: '重试', retrying: '重新校验中', keepOnly: '仅收藏', keptOnly: '已保留，仅收藏不推送', unresolvedTemp: '暂时无法校验，请稍后重试或检查拼写',
          sort: { added: '加入时间', due: '到期', alpha: '字母', ease: '熟练度', times_added: '反复次数' }, counts: (n: number) => `共 ${n} 个`,
          empty: '还没有生词。在词库里点「不熟悉」，或直接添加。', dueIn: (s: string) => `${s}复习`, consolidateNow: '立即整理', consolidating: '正在整理…', consolidateQueued: '已安排整理，稍后查看整理建议' },
  suggestions: { title: '整理建议', badge: (n: number) => `整理建议 (${n})`, empty: '暂无整理建议。每晚会自动整理你的生词库。', accept: '接受', reject: '保留', undo: '撤销', autoSection: '已自动整理', expiresIn: (d: number) => `${d} 天后过期`, expiresToday: '今天过期',
                 fix_spelling: (a: string, b: string) => `“${a}” 看起来是 “${b}” 的拼写错误。替换？`, lemmatize: (a: string, b: string) => `“${a}” 是 “${b}” 的变化形式，合并？`,
                 merge_duplicate: (a: string, b: string) => `“${a}” 与 “${b}” 是同一个词的不同拼写，合并？`, invalid_word: (a: string) => `“${a}” 似乎不是英文单词，删除？`,
                 split_phrase: (b: string) => `建议改学核心词 “${b}”`, fill_data: (a: string) => `已为 “${a}” 补全词典信息`, auto_lemmatize: (a: string, b: string) => `已自动将 “${a}” 归为 “${b}”`, undone: '已撤销' },
  history: { title: '记录', heat: '最近 12 周', completed: (d: number, t: number) => `完成 ${d}/${t}`, gradedCount: (n: number) => `学习 ${n} 个`, offline: '服务器离线', stubborn: '反复遗忘', replay: '重新浏览', empty: '学习记录会在第一次学习后出现。',
             longest: (n: number) => `最长连续 ${n} 天` },
  settings: { title: '我的', push: '推送设置', learn: '学习设置', account: '账号', about: '关于与数据来源', pushTime: '推送时间', timezone: '时区', detect: '自动检测', pushEnabled: '每日推送',
              dailyNew: '每日新词', dailyScreen: '每日推荐词', maxReviews: '每日最多复习', stages: '目标阶段', currentStage: '主攻阶段', nextPush: (t: string) => `下次推送：${t}`,
              email: '邮件推送', emailVerify: '验证邮箱', emailCode: '请输入邮件中的 6 位验证码', emailSent: '验证码已发送', emailVerified: '邮箱已验证', emailTest: '发送测试邮件', emailTestQueued: '测试邮件已加入发送队列，请稍后查收',
              webhook: 'Webhook 推送', webhookUrl: 'Webhook 地址（https）', webhookFormat: '格式', formats: { generic: '通用 JSON', wecom: '企业微信机器人', feishu: '飞书机器人', serverchan: 'Server酱', bark: 'Bark' },
              webhookTest: '发送测试', webhookOk: '测试成功', webhookFail: (e: string) => `测试失败：${e}`, webhookEnableFirst: '请先开启 Webhook 推送',
              webhookFailHttp: (n: number) => `目标返回 HTTP ${n}，请检查地址或令牌`, webhookFailConnect: '无法连接到目标地址，请检查地址后重试',
              webhookFailDns: '域名无法解析，请检查地址拼写', webhookFailPrivate: '地址不是公网地址，已拒绝；请填写公网 https 地址', webhookFailTimeout: '连接超时，请稍后重试或检查目标服务',
              webhookFailTls: 'HTTPS 证书校验失败，请检查目标站点的证书', webhookFailInvalidUrl: '地址格式无效，请检查后重新填写',
              showImages: '显示配图', zhExamples: '例句译文', zhModes: { tap: '点按显示', always: '总是显示' }, autoPronounce: '自动发音', accent: '口音', accents: { 'en-US': '美音', 'en-GB': '英音' },
              dance: '单词之舞', danceModes: { full: '全部', form_only: '只拼读', off: '关' }, danceHint: '新词和还不熟的词出现时，字母按音节入场、重读的音节跳得最高；翻面时 up、in、cold 这类词再做一次它的意思。「只拼读」只跳字母、不做意思动作；点发音按钮随时可以再看一次',
              nativeReminderHint: '在 App 里，提醒由手机本机在设定时间发出，不需要 Bark 或微信推送', reminderDenied: '没有通知权限，请到系统设置里允许 word-Dance 发送通知', allowNotifications: '允许通知',
              displayName: '昵称', changePassword: '修改密码', currentPassword: '当前密码', newPassword: '新密码', export: '导出数据', exportCsv: 'CSV', exportJson: 'JSON',
              import: '导入数据', importHint: '选择之前导出的 CSV 或 JSON 文件', importDone: (n: number, m: number) => `已导入 ${n} 个，跳过 ${m} 个`,
              deleteAccount: '删除账号', deleteConfirm: '删除后所有学习记录将无法恢复。请输入密码确认。', version: (v: string) => `版本 ${v}`,
              sources: { dict: '词典数据：ECDICT（MIT 许可）', lists: '词表范围：小学（课标二级）、初中（课标三级与上海市初中英语词汇表）、高中（高中课标词表）、大学英语四级与六级大纲', images: '图片来源：Wikimedia Commons、Openverse（CC 许可）、AI 生成示意图或系统生成卡片', ai: '例句、搭配与记忆提示由 AI 生成，仅供学习参考' } },
  native: { reminderTitle: 'word-Dance', reminderBody: '今日词汇已准备好，点开复习' },
  admin: { title: '管理', tabs: { overview: '概览', users: '用户与邀请', jobs: '任务', ai: 'AI', reports: '内容反馈', events: '事件', config: '配置' },
           spendToday: '今日花费', spendMonth: '本月花费', cap: '上限', queue: '队列', paused: '已暂停', pause: '暂停 AI', resume: '恢复 AI', probe: '探测 claude', probeOk: (t: number) => `探测成功（flag tier ${t}）`,
           activeProvider: '当前提供方', providerClaude: 'Claude', providerFallback: '备用模型', probeFallback: '探测备用', fallbackPaused: '备用模型已暂停', probeFallbackOk: (m: string) => `备用模型探测成功（${m}）`,
           claudeAutoPaused: 'Claude 自动暂停至', fallbackAvailability: { unprobed: '未探测', available: '可用', unavailable: '不可用' },
           prewarm: '预生成', invite: '生成邀请码', inviteOnce: '邀请码只显示一次，请立即复制', disable: '禁用', enable: '启用', makeAdmin: '设为管理员', resetPassword: '重置密码',
           images: { photo: '照片', svg: 'AI 示意图', card: '仅文字卡片', svgBudget: 'AI 示意图额度' },
           retry: '重试', requeueDead: '重排所有失败任务', regenerate: '重新生成', refetchImage: '换图', dismiss: '忽略', lastTick: '上次调度', flagTier: 'CLI 加固级别',
           labels: { id: '编号', role: '角色', active: '状态', lastLogin: '最近登录', bankSize: '生词数', streak: '连续天数', maxUses: '次数上限', expiresInDays: '有效天数', note: '备注', uses: '已用',
                     expiresAt: '到期时间', createdAt: '创建时间', createdBy: '创建者', type: '类型', status: '状态', priority: '优先级', attempts: '尝试', runAfter: '执行时间', lockedBy: '执行者',
                     payload: '参数', lastError: '最近错误', kind: '种类', model: '模型', tier: '级别', words: '词数', cost: '费用', durationMs: '耗时(ms)', tokens: 'Token', startedAt: '开始时间',
                     error: '错误', avgCostPerWord7d: '近 7 天每词均价', calls: '调用次数', ledger: 'AI 调用记录', health: '健康状态', db: '数据库', diskFree: '剩余磁盘', dataDir: '数据目录',
                     threads: '线程', scheduler: '调度器', claudeWorker: 'Claude 线程', ioWorker: 'IO 线程', claudeBin: 'claude 可执行文件', seedVersion: '词库版本', migrations: '迁移版本',
                     workerLease: '工作租约', lastBackup: '上次备份', providers: '图片来源配额', provider: '来源', perMinute: '每分钟', perDay: '每日', cooldownUntil: '冷却至',
                     active7d: '7 日活跃', bankEntries: '生词条目', batchesToday: '今日批次', running: '运行中', dead: '失败', alive: '运行中', stopped: '已停止', enabled: '已启用', disabled: '已禁用',
                     withContent: '有内容', total: '总数', userAdded: '用户添加', pendingValidation: '待校验', limit: '数量上限', maxBudgetUsd: '预算上限 (USD)', detail: '详情',
                     word: '单词', user: '用户', target: '对象', key: '键', value: '值', source: '来源' } },
} as const;

export type Zh = typeof zh;
```

Rules: no other file may contain Chinese UI copy; `grep -rn '[一-龥]' src --include=*.tsx --exclude=i18n` must return nothing (CI check); the forbidden term 单词本 must not appear anywhere.
