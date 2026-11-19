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

- [ ] Every toast on /study (bare route, no tab bar) and /screen/run (tab bar on phones) sits ABOVE the grade / verdict bar — 不熟悉 / 认识 stay visible and tappable while the 5-s undo toast or 「10 分钟后再见」 is up, on phone and desktop (the bar publishes its height through `useBottomBarOffset`).

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
      attribution (photo), 「AI 生成示意图」 (claude_svg) or 「系统生成卡片」 (card). A 记忆图卡 shows 不合适 only, and a
      report on it is followed by the toast alone — no poll, the picture stays (§9).
- [ ] Content: examples highlighted + 🔊 + 译; `queued` → 「例句生成中…」 + skeleton + 5-s poll; deferred → the
      「明天补齐」 copy without polling; `none`/`failed` → 生成例句 (`word.generateExamples`) → toast
      `word.examplesQueued`; the button is hidden for a 待校验 word (`is_valid_english === null`).
- [ ] Actions: 不熟悉 (5-s 撤销 toast → restore), 已掌握 (confirm unless suggested; 8-s 撤销 → restore, toast
      「已恢复到生词库」), 移除 and 重置 (confirm dialogs); state badge and SRS panel update; 我的记录 lists the last 20
      actions with time and label.
- [ ] 反馈问题 sheet: reasons 释义有误 / 例句不地道 / 翻译有误 / 配图无关 / 配图不合适 / 其他 + note (≤ 300) →
      `POST …/report` with the right target (image reasons → image; 释义有误 without Claude content → dictionary).
- [ ] 易混 chips from `confusables` link to `/words/<lemma>`.
- [ ] TTS: 🔊 works in Chrome, Edge and Safari (first tap unlocks audio on iOS); where `speechSynthesis` is absent or lists no English
      voice, the server clip plays when `ServerFlags.audio` is true (an example sentence with quotes and dashes too; a double tap plays
      only the second); the button is disabled with the tooltip 「当前浏览器不支持语音」 only when the server has no provider either.

## 5. 记录 (`/history`, `/history/:batchId`)

- [ ] 学习日历: a calendar, weeks as rows (一 … 日), five weeks ending with this week; every day shows its date
      (「今」 today, M/D on the first cell and on a first of the month); a filled green day = 已完成 (the day's goal
      met), a tinted outlined day = 学了一部分, the legend under the grid names both; tapping a day that had words
      opens its batch; 「显示更早」 appears only when an earlier week was studied and opens the 12 weeks (收起 closes).
      「连续学习 N 天」 and 「最长连续 N 天」 above it.
- [ ] 每日记录: ONE row per day, newest first — 「11月18日 周三」 + a status pill 已完成 / 进行中 / 未开始 (today) /
      未完成 (an older day) and what the day held, 「复习 6 · 新词 10 · 推荐词 45」 once everything is done,
      「复习 5/14 · 新词 0/10 · 推荐词 0/15」 while something is left; the row links to the batch. A day whose batch
      had no words reads 「… · 当天没有要学的词」, a day studied without a batch 「… · 学习 N 个」, a day without a
      batch overlapping a recorded downtime 「… · 服务器离线」 (`DayStats.offline`) — one muted line each, no link.
      No day appears twice; 加载更多 brings older days.
- [ ] 反复遗忘 lists `Stats.stubborn` (`times_added ≥ 3`) linking to detail, under the days.
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

## 7. 单词之舞（P1，FRONTEND §6.5）

- [ ] 设置 → 学习设置 有「单词之舞」三档（全部 / 只拼读 / 关，默认全部）和一行说明文字，360px 下不换行错位；选「关」发 `PUT /api/settings {dance_mode:'off'}`，学习卡与详情页的词头是普通文字、没有音节芯片；选「只拼读」发 `{dance_mode:'form_only'}`。
- [ ] 开着时，新词卡出现：字母按音节依次入场，重读音节跳得最高并变色；词下方音节芯片（如 `rab · bit`）标出重读音节；单音节词没有芯片、只有一拍；不发音字母（night 的 gh、knife 的 k、magic e）颜色变浅、不跳。
- [ ] 点 🔊 或按 `P`：再跳一次并朗读；翻面不重跳；复习卡不论复习过多少次，出现时都自动跳（2026-11-16 起取消「前三次」的限制）；推荐词卡出现时也自动跳拼读和重音——没有意思动作、舞台物件和颜色姿态，点「显示释义」后不重跳，🔊 / `P` 重放的也只是拼读。
- [ ] 系统「减弱动态效果」打开：不动，重读音节静态着色，信息不丢。
- [ ] 手机 360px：长词（supermarket、grandmother）不换行、不溢出；整段动画不超过 2.5 s；低端 Android 上不卡顿。
- [ ] 详情页：打开一个词时自动跳一次（「全部」档先拼读、再做意思动作；「只拼读」档只跳拼读；「关」档不跳），弹出确认框这类操作不会让它重跳；词头下有音节芯片，🔊 重放；词组（ice cream）、缩写（TV、Mr.）没有芯片，词头照旧。
- [ ] 语义舞（P2，设置为默认的 full 时）：有语义舞步的词（up、in、small、cold、red、three…）在**翻面**那一刻做一次意思动作，正面不做；🔊 / `P` 在背面重放时先拼读后动作；设置成「只拼读」（`form_only`）后背面不再做动作、词头没有颜色姿态、没有舞台物件。
- [ ] 有舞台物件的词（in / out 的盒子、over 的屋顶、on 的台子、under 的桌子、behind 的树、between 的两道杠）在 360px 下不溢出卡片；two / three 的分身复制在动画后消失。
- [ ] P3：jump 翻面时整词蹲下、跳起、落地压扁、再小跳一次后回到原样（字形不变）；on 从左上方落到台子上停住，台子微微一沉；字母的下伸部画在台子前面。
- [ ] 名词（rabbit、apple）和虚词（the、of）没有语义舞，只有拼读两舞；`wd dance-annotate --word <w>` 后详情页接口 `word.dance.source` 变为 `claude`。

## 8. 磨耳朵（`/listen`，FRONTEND §5.9；设计稿 docs/LISTEN_MODE_DESIGN.md）

三台设备各走一遍：**电脑浏览器**（Chrome 或 Safari）、**手机浏览器**（iPhone Safari 或安卓 Chrome）、**鸿蒙平板 APK**。前提：今天有批次，里面有复习 / 新词 / 加练；服务器 `WD_AUDIO_PROVIDER=say` 且 `wd audio-voices` 列出了中文语音（`/api/auth/me` 的 `server.audio_zh` 为 `true`）。

入口与页面

- [ ] 今日页：「开始学习 / 继续学习」正下方有次级按钮「磨耳朵」，点开是 `/listen`；学完后的「今日完成」卡片里也有；只有推荐词的批次、还没有批次时都没有这个按钮；今天的词全都标了「掌握」（或都已移出生词库）时也没有——播放列表是空的，不给一个点进去什么都没有的入口。
- [ ] `/listen` 是整屏页面：没有底部导航、没有顶栏；左上「回到今日」能回去；360px 下没有横向滚动，控制条贴在底部、不被安全区遮挡；深色模式下高亮和文字都看得清。
- [ ] 加载失败（先停掉服务再点「磨耳朵」）：除了「重试」，左上角仍有「回到今日」，不会困在这一页。
- [ ] 进入后不用点任何东西就开始播放（电脑浏览器、平板 APK）；iPhone Safari 第一次会停住并显示「点一下开始播放」，点一下之后整条播放链不再需要点。

跟着听

- [ ] 每个词依次读：单词（英文，口音跟「学习设置 → 口音」一致）→ 中文意思 → 例句 → 例句中文；屏幕上正在读的那一行高亮；词与词之间有不到 1 秒的停顿；右上角「i / n」和进度条跟着走。
- [ ] 读出来的中文意思是短释义（不读 `n.` `v.` 这类词性，不读括号里的内容），屏幕上显示的是带词性的完整释义。
- [ ] 关掉「例句」：只读单词和中文意思，屏幕上例句消失；关掉「中文」：不再读中文；两个都关：只连着读单词。每次切换都从当前这个词的开头重新读。
- [ ] 暂停后再播放，从当前词的第一段重新读；「上一个 / 下一个」立即跳并开读（暂停时只移动、不出声）；「重新开始」回到第一个词。
- [ ] 键盘（电脑）：空格 播放 / 暂停，← / → 上一个 / 下一个；焦点在某个按钮上时空格按的是那个按钮。
- [ ] 播完显示「听完了」，有「再听一遍」和「去学习」。键盘：播完时如果焦点原本在播放 / 暂停等按钮上，焦点落到「听完了」（听写是「对答案」）上，按 Tab 从它后面的内容开始；焦点在模式、遍数 / 间隔上时不被挪走。
- [ ] 没有例句的词（内容还没生成）只读单词和中文意思，不卡住。

听写

- [ ] 切到「听写」：屏幕上**看不到单词、音标、释义**，只有「第 i 个」、每遍一个小圆点和「听到单词后写下来」；暂停时也看不到。
- [ ] 默认每词读 2 遍、每遍后停 5 秒；改成 1 / 3 遍、3 / 8 / 12 秒后按新的节奏走（拿秒表量一次 12 秒）。
- [ ] 播完出现「对答案」：序号、单词、🔊、释义；点 🔊 能读这个词；「再听写一遍」从头开始并把答案收起；「回到今日」回今日页。
- [ ] 途中用「下一个」跳过一个词（没等它读完），播完后这个词在「对答案」里带灰色的「没读」标记，其余的词没有；读不出来的词同样带标记；「再听写一遍」后标记清空。
- [ ] 在「对答案」页按空格、←、→ 或耳机上的播放键，答案不会消失；改遍数 / 间隔也不会；切回「跟着听」会回到第一个词（不自动播放）。
- [ ] 耳机线控 / 锁屏控件（有的设备才有）：播放、暂停、上一个、下一个可用；听写时锁屏上的标题是「第 i 个」，不是单词。

设置记忆

- [ ] 模式、两个开关、遍数、间隔刷新后还在（`localStorage['wd.listen']`）；平板和手机各记各的，互不影响。

读不出来的时候

- [ ] 服务器没有中文语音（`server.audio_zh` 为 `false`）而设备自己有中文语音的浏览器：中文由设备读；设备也没有中文语音：页面提示「这台设备读不了中文，只播放英文」，只读英文，不卡住。
- [ ] 同样的服务器、在平板 APK 里打开（事先看不出平板读不了中文）：第一个词的中文意思试一次、没有声音，随即出现上面那条提示；**这个词不会从头再读一遍**，后面的词不再有中文；提示旁边不出现「有 N 段没能读出来」。
- [ ] 服务重启后两三秒内打开磨耳朵（重启后马上刷新今日页再点进去）：不用再刷新，中文照常由服务器读出——`server.audio_zh` 这时是乐观的 `true`，第一段中文多等一两秒（语音在这条请求里解析）。
- [ ] 把服务器的发音关掉（`WD_AUDIO_PROVIDER=off`）后在电脑浏览器里打开：用浏览器自己的语音照样连播；在平板 APK 里打开：显示「这台设备现在读不出声音」和「去学习」。
- [ ] 播放途中重启服务（2–3 秒）：不用点任何东西，停顿几秒后自己接着读（每 1.5 秒再问一次服务器，最多再问两次）；已经播过的词来自浏览器缓存，不受影响。
- [ ] 播放途中断网（或把服务停掉不再启动）：电脑 / 手机浏览器等约 3 秒后改用设备自己的语音接着读（只有第一段要等，之后每段只问服务器一次）；设备读不了的段（平板 APK 的全部、没有中文语音的浏览器的中文）**不跳过**：停在当前这个词，按钮变回「播放」，显示「连不上服务器，点播放再试一次」，「有 N 段没能读出来」不增加，听写不会提前跳到「对答案」；恢复后点播放，从这个词接着读。

鸿蒙平板 APK（本期最要紧的三项，结果写进上线记录）

- [ ] **中文出声**：中文意思和例句中文都能听到（平板没有本机语音，声音全部来自服务器）。
- [ ] **连播不需要再点**：从进入页面到「听完了」不碰屏幕，一个词接一个词读完；听写的 5 秒间隔之后能自己接着读。
- [ ] **熄屏后的表现**：让屏幕按系统设置自动熄灭（或按电源键），记录声音是否继续、停在了哪里、亮屏后是否接着播；如果熄屏就停，临时办法是把平板的「休眠」时间调长（局域网 `http://` 下网页不能保持常亮，设计稿 §7.1）。
- [ ] 切到别的 App 再回来、来一条通知、拔掉耳机：记录播放是否中断。如果系统自己把声音停了，页面应当变成「播放」按钮加「点一下开始播放」（而不是还显示「暂停」却没有声音），点一下从当前词接着读；系统随后自己恢复那一段声音的话，会多听到半句，属已知现象。

手机浏览器

- [ ] iPhone Safari：点过一次之后连播正常；锁屏后声音是否继续（服务器音频一般会继续，段间停顿可能变长），记录下来。
- [ ] 安卓 Chrome：同上；从今日页点「磨耳朵」进入时通常不需要再点一次。
- [ ] iPhone / iPad Safari，服务器不读中文（`server.audio_zh` 为 `false`，或本次打开后有一条中文音频失败过）而「中文」开着：中文段只能靠手机自己的语音，而 iOS 不让网页在点击之外开始朗读——**已知限制，没有真机验证过**（设计稿 §7「iOS 上点击之外的设备朗读」）：预计每个中文段静默 5–10 秒后被跳过并计入「有 N 段没能读出来」。记录实际表现；本次打开网页后在别处点过任何 🔊 的不受影响，关掉「中文」可以避开；因为一条中文音频失败才落到这种状态的，刷新页面后重新由服务器读。
- [ ] 离开页面（返回今日、系统返回键）后声音立刻停。

## 9. 记忆图卡（FRONTEND §4 `study/WordImage`、§5.1.2、§5.8；设计稿 docs/MEMORY_CARDS_DESIGN.md）

前提：已经用 `wd images-import` 导入了至少两三张记忆图卡（比如样例里的 happy、rain、moon），这些词在今天的批次里，或者能从词库点进详情页；另外准备一个还是旧图的词（照片或旧的 AI 示意图）作对照。三台设备各走一遍：**电脑浏览器**、**手机浏览器（360px）**、**鸿蒙平板 APK**。

开关

- [ ] 设置 → 学习设置，「显示配图」下面有「图片上显示单词」开关，默认开，标题下面第二行小字是「关掉后，带单词的配图只显示画面」（不加粗；360px 下是一行，320px 或系统字号调大后自动折成两行）。
- [ ] 设置页所有开关（每日推送、邮件推送、Webhook 推送、显示配图、图片上显示单词、自动发音）的滑块都在行的最右端，上下对齐，和「例句译文」「单词之舞」的分段按钮右边缘齐平；360px、320px 下开关不被挤出卡片，页面不能左右滑动。点一行里文字和滑块之间的空白处也能切换开关。
- [ ] 点一下开关：发 `PUT /api/settings {image_word:false}`（请求体里只有这一个字段），标题旁闪「已保存」；刷新页面后开关仍是关。再点一下发 `{image_word:true}`。
- [ ] 开着：学习卡翻面后的图、详情页的图，画面里都有单词（按拼读块分色的大字母）；图片地址不带参数。
- [ ] 关掉：同一个词在学习卡背面、详情页、历史批次回放（`/study?batch=<id>`）里都只剩画面、没有单词；图片地址以 `?plain=1` 结尾（开发者工具 Network 里看）；画面是完整的，没有残留的字母、投影或空白块。再打开开关，单词回来。
- [ ] 开关对照片、旧的 AI 示意图、系统生成卡片没有任何影响（地址不带 `?plain=1`，图不变）。
- [ ] 「显示配图」关掉：记忆图卡和其他图一样不显示，这时「图片上显示单词」开或关没有区别。
- [ ] 登录页的体验区（未登录）：示例词里有记忆图卡时，显示的是带单词的图；这张图的 `alt`（开发者工具 Elements 里看，或用读屏）是图卡自己的画面描述，不是内容里旧的配图描述。

「记忆」一栏

- [ ] 记忆图卡的词，学习卡背面和详情页的「记忆」显示的是图的钩子（说的就是画面里的事，如 happy 的「两个 p 像两只气球」）；下面一行字号小一号、颜色较淡的是读音 / 词义提醒；没有提醒的图只有一行。内容里旧的联想句（尤其是谐音的那种）不再出现。
- [ ] 「图片上显示单词」关着时，「记忆」仍然是图的钩子。
- [ ] 「显示配图」关掉后，「记忆」回到内容里原来的联想句（没有较淡的第二行）；不是记忆图卡的词始终显示原来的联想句。
- [ ] 例句还在生成（「例句生成中…」）、额度用完（「明天补齐」）或生成失败的记忆图卡词：图和「记忆」里的钩子照常显示。
- [ ] 图没加载出来时（开发者工具 Network 里把这张 `/media/images/….svg` 设为 Block request url，或断网后翻一张没看过的记忆图卡）：图框空着，「记忆」显示的是内容里原来的联想句，不是钩子，也没有较淡的第二行；例句还没生成的词这时没有「记忆」一栏。恢复网络后重新进这张卡 / 这个词，图出来了，钩子也回来。详情页里图加载失败后点「易混」跳到另一个记忆图卡词，那个词的钩子照常显示。
- [ ] 学习卡正面（翻面之前）看不到图，也看不到钩子；深色模式下较淡的第二行仍然看得清。

「换一张」与「不合适」

- [ ] 记忆图卡的详情页，图片下方只有「不合适」，没有「换一张」；图片说明是「AI 生成示意图」。其他图（照片、旧示意图、系统卡片）两个按钮都在，「换一张」照旧能换。
- [ ] 记忆图卡上点「不合适」：提示「已收到反馈，谢谢」，图原样留着（带不带单词与开关一致），「记忆」不变，「不合适」按钮不变灰；Network 里只有一条 `POST …/report`，没有随后每 3 秒一次的 `GET …/image`；刷新页面后图卡还在。从「反馈问题」里选「配图无关」或「配图不合适」提交，结果相同。管理员在后台的举报列表里能看到这条反馈。
- [ ] 管理员（管理 → 内容反馈）：上一条留下的反馈在列表里，状态是未处理。点「忽略」：图卡原样留着。另找一条点「换图」：这个词的记忆图卡下线，稍后换成图库的图或旧式示意图（都取不到就是系统卡片），详情页的「记忆」回到内容里的联想句，图下面「换一张」又出现了。之后运维整份重跑 `wd images-import studio/cards --manifest studio/manifest.json`：这个词列为 `retired`、图不变；加 `--only <词>` 再跑，图卡才回来。
- [ ] 照片或旧示意图上点「不合适」照旧：同样的提示，随后「换一张」转圈、「不合适」变灰，每 3 秒轮询 `GET …/image`，换上新图（或系统卡片）后两个按钮恢复。

平板和手机上的观感（上线前实际看一眼，结果写进上线记录）

- [ ] 鸿蒙平板 APK：连着学 10 张记忆图卡，翻面后图在 1 秒内出现（先是灰色骨架，再淡入），翻面和上下滚动卡片背面都不卡顿（每张图有约 10 个带模糊的图层，设计稿 §5 风险 3）。
- [ ] 平板和手机上图片清晰：字母边缘不发虚、没有锯齿，朵朵 / 乐乐 / 奶奶 / 团子的脸不糊；图是 16:10、完整显示，四边不被裁掉；横竖屏切换后仍然清晰。
- [ ] 同一张图第二次打开是即时的（不可变缓存）；切换开关后，另一种取法第一次要重新下载一次，之后同样即时。
- [ ] 手机 360px：图不溢出卡片，图里的单词在这个宽度下仍然读得清。
