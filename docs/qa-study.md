# WP8 manual QA — today, study, screening, word detail, history

Checklist for the WP8 pages (`/today`, `/study`, `/screen`, `/screen/:stage`, `/words/:idOrLemma`, `/history`,
`/history/:batchId`). Run against a real backend (`make dev`; the fake Claude via `WD_CLAUDE_BIN` is fine) with
a user who finished onboarding and has a few bank words. Tick every box on a **phone (360 px)** and on a
**desktop (1280 px)**; the keyboard column applies to the desktop run. Linked from `docs/qa.md` (WP9).
Vite binds `localhost` only (open `http://localhost:5173`, not `127.0.0.1`), so a real phone cannot reach `:5173`:
run `cd frontend && npm run dev -- --host` (then `http://<LAN-ip>:5173`), or use the built SPA of the installed
service on `http://<LAN-ip>:8000`, or the desktop browser's device emulation at 360 px.

Dev override for the 10-minute step: start Vite with `VITE_REQUEUE_SECONDS=30 npm run dev` — the client then
shows a requeued card 30 s after its intermediate grade instead of waiting for the server's `requeue_at`
(the server accepts the second grade at any time, API.md 45).

## 1. 今日 (`/today`)

- [ ] `status:'none'` before the push time: the card shows `today.notYet(push_time)` and 立即生成; 再来一组 is
      disabled; with an empty bank the `today.emptyBank` empty state appears with 去筛词 (and 去词库).
- [ ] 立即生成 → `POST /api/today/build` → the batch renders at once (ring `done/total`, chips 复习 · 新词 ·
      推荐词, 顺延 note when `deferred_reviews > 0`).
- [ ] While `building`: items are visible, 再来一组新词 / 再筛一组推荐词 work (`POST /api/today/more`); the
      「N 个词的例句生成中」 notice shows **only while** `counts.pending_content > 0` and disappears when every
      remaining item is budget-deferred or AI is paused; the page re-polls `/api/today` every 30 s only while
      that count is > 0 and the tab is visible.
- [ ] 整理建议 badge (`today.suggestions(n)`) appears when `suggestions_open > 0` and links to `/bank/suggestions`.
- [ ] After every card has a final result: 「今日完成 🎉」 + `today.seeYou(push_time)` + 再来一组 + 去筛词 + 去词库;
      a 4th 再来一组 round → 429 toast (`errors.rateLimited`); `added: 0` → `today.nothingMore`.
- [ ] After midnight with yesterday's batch unfinished: `previous_open_batch` renders the
      「继续昨天的学习（还剩 N 个）」 card above today's CTA (also in the `none` state); it opens
      `/study?batch=<id>` **with the grade bar** (`batch.gradable:true`) and grading its items returns 200.
- [ ] A two-day-old batch opened from 记录 is replay-only (no grade bar, outcome chips, ← / → navigation).

## 2. 学习 (`/study`)

Keyboard: Space = 显示释义 · 1 / 2 / 3 = 不熟悉 / 模糊 / 记住了 · 4 = 已掌握 · S = 跳过 · P = 发音 · Z = 译 · H = 提示 ·
U = 撤销 the last 推荐词 verdict (while its toast is visible).

- [ ] Full session on the phone by tapping and on the desktop **with the keyboard only**.
- [ ] Front: headword, phonetic, 🔊 (auto-pronounce when `settings.auto_pronounce`), stage chips, kind badge;
      提示 (H) shows the first example with the headword/forms replaced by `___`; tap / Space / 显示释义 reveals.
- [ ] Back: `meaning_zh` (ECDICT translation when content is missing), image (`settings.show_images`),
      examples with the headword and its forms in `<mark>` + 🔊 per sentence + 译 per sentence (always shown
      when `zh_examples='always'` or after Z), 搭配, 记忆, 易混 chips (from `confusables`, linking to detail),
      collapsible 词典释义, 「第 N 次复习 · 间隔 N 天」, 「下次：模糊 → … · 记住了 → …」.
- [ ] 「下次」 preview equals the server's `next_due_zh` after the grade for new / step / review cards
      (3 天后, 8 天后, …, 约 4 个月后).
- [ ] Intermediate grade (记住了 on a new card, 不熟悉 / 模糊 anywhere): toast 「10 分钟后再见」, `done/total` in the
      header does **not** rise, the card is gone from view and comes back ≥ 10 cards later or at the end.
- [ ] Requeue: with `VITE_REQUEUE_SECONDS=30`, finish the other cards → 「还有 1 个词将在 N 分钟后复现」 +
      现在就复习; after 30 s (or 现在就复习) the card reappears; its second grade is accepted (200, a new
      `client_event_id`), the done count rises **only then** and the summary follows.
- [ ] Requeued card with the real 10-minute step: `GET /api/today` on reload still lists it as remaining with
      `requeue_at` set; the session keeps it in `requeue` (waiting panel) and never counts it as done.
- [ ] Content-pending card: dictionary data + skeleton + 「例句生成中…」, polls `GET /api/words/{id}/content`
      every 5 s (≤ 24) and switches to the examples when ready; the card is usable and gradable meanwhile.
- [ ] Failed card (`content_state:'failed'` / `none`): 「今天的例句暂时生成不了，先用词典释义学习」 + 生成例句 →
      `POST …/content/request` → toast `word.examplesQueued`, polling resumes.
- [ ] Budget-deferred card (`content_deferred_until` set): 「今日 AI 额度已用完，例句将在明天补齐」, **no**
      skeleton, **no** 生成例句, **no** polling (network tab quiet); a 409 `budget_exhausted` from 生成例句 flips a
      failed card to this state with the `errors.budgetExhausted` toast; 503 → `errors.aiDisabled`.
- [ ] 已掌握 with `mastery_suggested` (建议 badge, primary button): acts immediately, 8-s 撤销 toast; 撤销 calls
      `POST /api/words/{id}/mark {action:'restore', context:'today'}`, toast 「已恢复到生词库」 and the card is back
      at the front of the queue, gradable; after 15 min 撤销 → `errors.undoExpired`.
- [ ] 已掌握 without the suggestion: ConfirmDialog 「确定已掌握？…」 first; cancel keeps the card.
- [ ] 推荐词 inside the session: 认识 / 不熟悉 / 跳过 directly, 显示释义 peeks; 不熟悉 appends the new card to the end
      of the queue (toast 「已加入生词库，今天就学」) or shows 「已加入生词库，明天开始学」 when the quota is full;
      its 撤销 (toast or U) runs the server restore and removes the appended card again (and the 推荐词 returns).
- [ ] 跳过 moves the card to the end (header count unchanged); Z toggles every translation and persists
      (`localStorage['wd.zhToggle']`); P pronounces.
- [ ] Offline grading: switch the network off, grade two cards → the cards advance; after > 10 s the banner
      「有 N 个结果待同步」 appears; `localStorage['wd.pendingGrades']` holds the events; network back → they are
      delivered with backoff (1 s, 3 s, 10 s…); a reload flushes them **before** `/api/today` is fetched.
- [ ] A stale card (word mastered in 词库 before studying) is hidden by the server; grading a card that turned
      stale mid-session → 409 `invalid_transition` → the card is dropped silently.
- [ ] Summary: ring complete, counts (复习 N · 新词 N · 推荐词 N), grade breakdown, 不熟悉 words as chips → detail,
      「连续学习 N 天」, 再来一组新词 / 再筛一组推荐词 (while `can_request_more`, they continue the session) / 去筛词 /
      回到今日; `POST /api/today/complete` was called once.
- [ ] `/study?batch=<yesterday>` grades with the grade bar; its completion shows the summary without calling
      `/api/today/complete`; `/study?batch=<older>` is replay-only.
- [ ] 360 px: no horizontal scroll; the grade bar stays at the bottom above the safe area; buttons ≥ 44 px.

## 3. 筛词 (`/screen`, `/screen/:stage`)

- [ ] `/screen`: one card per stage with 「本阶段还剩 N 个未筛」, a progress bar and the last used stage highlighted
      (`localStorage['wd.screenStage']`).
- [ ] `/screen/cet4`: title 「筛词 · 四级」, headword + phonetic + 🔊 only; 认识 (1 / swipe right) · 不熟悉 (2 /
      swipe left) · 跳过 (S) · 显示释义 (Space) keeps the buttons.
- [ ] Each verdict posts `POST /api/screen/verdict` with a `client_event_id` and the deck advances at once;
      remaining count decrements for 认识 / 不熟悉 (not 跳过).
- [ ] 不熟悉 toast: 「已加入生词库」 (no batch today) / 「已加入生词库，今天就学」 (`added_to_today`) /
      「已加入生词库，明天开始学」 (quota full); 认识 toast with 撤销.
- [ ] 撤销 (toast or U) within 5 s for **both** 认识 and 不熟悉 → `mark {action:'restore', context:'screen_page'}` →
      the card is re-inserted at the front, remaining +1, toast 「已撤销」; after 15 min → `errors.undoExpired`.
- [ ] End of a 30-card deck: 再筛 30 个 fetches the next batch; a stage with nothing left shows 「这个阶段的词都筛完了 🎉」.
- [ ] Swipe on a phone: dragging shows the 认识 / 不熟悉 overlay, releasing past 80 px posts the verdict,
      releasing earlier springs back; vertical scrolling still works (`touch-action: pan-y`).

## 4. 单词详情 (`/words/:idOrLemma`)

- [ ] `/words/abandon` and `/words/123` render the full ECDICT entry (pos, translation lines, definition), 词形
      chips with kind labels, 考试标签, stage chips, state badge, `times_added` chip.
- [ ] `/words/went` → the headword `go` with 「已从“went”跳转」; `/words/bases` → 「多个可能的原形，请选择」 with the
      candidate chips `base` / `basis` linking to their detail pages; an unknown word → 「没有找到…」 + 添加生词
      (prefilled).
- [ ] Image: 换一张 → `POST …/image/refresh` → toast 「正在换图…」 → `GET …/image` polled every 3 s until the URL
      changes; 不合适 → `report {target:'image'}` → toast 「已收到反馈，谢谢」 and the same poll. Caption shows the
      attribution (photo), 「AI 生成示意图」 (claude_svg) or 「系统生成卡片」 (card).
- [ ] Content: examples highlighted + 🔊 + 译; `queued` → 「例句生成中…」 + skeleton + 5-s poll; deferred → the
      「明天补齐」 copy without polling; `none`/`failed` → 生成例句 (`word.generateExamples`) → toast
      `word.examplesQueued`; the button is hidden for a 待校验 word (`is_valid_english === null`).
- [ ] Actions: 不熟悉 (5-s 撤销 toast → restore), 已掌握 (confirm unless suggested; 8-s 撤销 → restore, toast
      「已恢复到生词库」), 移除 and 重置 (confirm dialogs); state badge and SRS panel update; 我的记录 lists the last 20
      actions with time and label.
- [ ] 反馈问题 sheet: reasons 释义有误 / 例句不地道 / 翻译有误 / 配图无关 / 配图不合适 / 其他 + note (≤ 300) →
      `POST …/report` with the right target (image reasons → image; 释义有误 without Claude content → dictionary).
- [ ] 易混 chips from `confusables` link to `/words/<lemma>`.
- [ ] TTS: 🔊 works in Chrome, Edge and Safari (first tap unlocks audio on iOS); the button is disabled with the
      tooltip 「当前浏览器不支持语音」 where `speechSynthesis` is absent.

## 5. 记录 (`/history`, `/history/:batchId`)

- [ ] 12-week heat strip (12 × 7, Monday first, 5 levels, ring on goal-met days, tooltip 「10月12日 · 学习 N 个」),
      「连续学习 N 天」 and 「最长连续 N 天」.
- [ ] Day rows 「10月13日 · 完成 41/41 🔥」 link to the batch; a day without a batch overlapping a recorded
      downtime shows 「10月11日 · 服务器离线」 (`DayStats.offline`).
- [ ] 反复遗忘 lists `Stats.stubborn` (`times_added ≥ 3`) linking to detail; past batches list with 加载更多.
- [ ] Fresh account: 「学习记录会在第一次学习后出现。」 + 开始学习.
- [ ] `/history/:batchId`: title is the batch date, ring + kind counts, every item with its kind badge and
      outcome chip; 「重新浏览」 opens the replay; for today's / yesterday's open batch the button is 继续学习 and
      opens the grade bar; an unknown id → 「找不到这个页面」 + 记录.

## 6. Cross-cutting

- [ ] `npm run typecheck && npm test && npm run build` green; `npm run lint` (copy rules) green.
- [ ] `grep -rn '[一-龥]' frontend/src --include=*.tsx | grep -v i18n` → empty; the forbidden glossary term is absent.
- [ ] Dark mode (`prefers-color-scheme: dark`) keeps every text ≥ 4.5:1; focus rings visible on every control;
      every icon button has an `aria-label`; the study card is `role="group"`.
- [ ] `prefers-reduced-motion`: no ring animation, no toast / sheet motion.
