# 发布说明 · 2026-11 · 单词之舞 P3 第一批（hop / onto 两个原语、设置页三档；无迁移）

基线 `main @ 50622b7`（P2 已上线，schema 16）；本次发布 = 「单词之舞」第三期的第一批：小学评审确认的两处舞步库空缺补上（jump → `hop`、on → `onto`），设置页把「单词之舞」从开关改成三档（全部 / 只拼读 / 关）。
契约：`docs/WORD_DANCE_DESIGN.md` §4.3 / §12，`docs/API.md` §9 `DancePrimitive`，`docs/CLAUDE_INTEGRATION.md` §4.5 / §5.6（`dance-v2`）/ §6.8，`docs/FRONTEND.md` §4 / §5.8 / §6.5 / §8。
**没有数据库迁移**：前端快照 + 重启即生效；已存的 `dance-v1` spec 全部有效（枚举只增不减）。

---

## 1 变更概览

| 面向 | 变化 |
|---|---|
| 学习者 | jump 翻面时整词蹲下、跳起、落地压扁再小跳一次；on 从左上方落到一个台子上停住，台子微微一沉。设置 → 学习设置 → 单词之舞 有三档：全部（拼读 + 意思动作）/ 只拼读（不做意思动作、没有姿态色和舞台物件）/ 关 |
| AI | 提示词 `dance-v2`：舞步库 28 → 30（`hop`、`onto`）；schema `dance_v1.json` 的枚举同步；已标注的词不重跑，只重标 jump、on |
| 接口 | `DancePrimitive` 多 `hop` / `onto`；`Settings.dance_mode` 不变（三个值 0015 起就合法） |
| 不变 | 数据库、入队与预算、P1 / P2 的播放时机、`docs/SCHEMA.sql`、`wd check db` |

## 2 机制要点

- 枚举顺序 = 提示词舞步库顺序；`test_schemas.test_dance_prompt_library_lists_every_primitive_of_the_schema_in_order` 把 `dance_v1.json`、`schemas.DancePrimitive`、`models.DanceItem` 与提示词锁成一份（types.ts 由 `scripts/check_contract.py` 对齐；API.md §9 的 ts 块由 `test_docs_contract` 锁定为与 types.ts 逐字相同）。
- `hop` 与 `onto` 两个落地动作以脚底为原点压扁（word.css 按 `data-primitive` 给这两个词设 `transform-origin: 50% 100%`，关键帧里仍只有 transform / opacity，走合成层），落地的压扁贴在基线 / 台面上；其余整词动作保持中心原点。
- `onto` 的台子 `.dword-stage--shelf`：台面在基线处；`isolation: isolate` + `z-index: -1` 让字母（含下伸部）画在台子前面而台子不会掉到卡片背景后面；台子的下沉步不带 options 级 easing（效果级 easing 会扭曲关键帧偏移），从词的落地偏移 `ONTO_TOUCHDOWN` = 0.78 起才下沉。
- 三档控件复用 `Segmented`（和例句译文、口音一致），说明文字作为行内第三个元素换行到下一行（`.settings__row--wrap` / `.settings__hint--row`）。

## 3 验收

- `make test`（新增用例见设计稿 §12）；`npm run lint`。
- 手测 `docs/qa-study.md` §7 的三档一条与 P3 一条。

## 4 上线步骤（Mac launchd；无迁移，约 3 秒）

1. 构建前端到 `$D/frontend-releases/<sha>`，切换 `frontend` 软链接（P1 发布说明 §4 第 1 步）。
2. `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`；`/api/health` 正常；`schema_migrations` 仍为 16。
3. `WD_DATA_DIR=… wd dance-annotate --word jump --word on --force`：两个任务在舞步子预算允许时执行（当日子预算用完则顺延到次日 00:05）；完成后 `GET /api/words/{id}` 的 `word.dance.semantic.primitive` 为 `hop` / `onto`，`word_dances.prompt_version = dance-v2`。

## 5 回滚

`git checkout 50622b7` 重建前端快照并重启。注意：旧后端的 `schemas.DancePrimitive` 不认识 `hop` / `onto`，带这两个原语的存储 spec 会让**所有嵌入该词的响应** 500（响应模型校验失败）：该词的 `GET /api/words/{id}`，以及批次里含 jump / on 的每个学员的整个 `TodayResponse`（`GET /api/today`、`POST /api/today/build`、`/more`、`GET /api/batches/{id}` —— 整批读不到、无法学习），还有把 jump / on 判「不熟悉」追加进今日批次时的 `ScreenResponse.study_item` / `GradeResponse.study_item` —— 所以回滚前必须先把它们作废：`UPDATE words SET active_dance_id = NULL, dance_state = 'none' WHERE active_dance_id IN (SELECT id FROM word_dances WHERE status = 'active' AND json_extract(spec_json, '$.semantic.primitive') IN ('hop', 'onto'))`（`word_dances` 行留着无害，规则 spec 接着服务）。旧前端对不认识的原语不播放、词头照常。

## 6 未决

- 线索复习（P3 其余部分）、手势（P4）、初高中词缀舞（P5）按设计稿分期。
- 规则层的 -er 后缀切分（work·er / farm·er）：11-09 00:05 的强制重标没有改掉它（§7）。提示词第 1 条要模型「除非明显错误，否则保留规则层建议」，而音节上的 VC·CV 切分 wor·ker 并不「明显错误」，所以这两个词要靠规则层做 -er 后缀切分（词干是已知词时保留词干：work·er、farm·er、teach·er），不是再喂一次模型。

## 7 上线记录

- 11-08 17:28 `bb2d1b5` 上线（`frontend-releases/bb2d1b5`，重启后 2 秒内健康，schema 16，`jobs` / `ai_calls` 行数不变）。
- 11-09 00:05 四个强制重标任务（2890 worker、2891 farmer、2892 jump、2893 on）由 worker 在一次合并调用里完成：`ai_calls` 1 条 success、4 词、$0.019（每词 $0.004739）；`word_dances` 596 行 = 592 活动 + 4 作废，活动 spec 588 个 `dance-v1` + 4 个 `dance-v2`。
- `jump` → `hop`（reason 跳跃的动作），`on` → `onto`（reason 在……上的位置），切块不变（jump / on 各一块）。`worker` / `farmer` 重标后与旧 spec 完全相同（wor·ker / far·mer，none，名词靠图），见 §6。
- 00:06 看护脚本把 `WD_AI_DAILY_BUDGET_USD` 从临时的 6.00 改回 3.00 并重启，`.env` 里 TEMPORARY 行为 0；00:12 健康检查正常。
- 审核页按重标结果重建并发布到原链接（hop / onto 各一组；脚注注明四个词于 11-09 00:05 用 dance-v2 重标）。
