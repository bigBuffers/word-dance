# 发布说明 · 2026-11 · 单词之舞 P2（语义舞，迁移 0016 · 停机迁移）

基线 `main @ 2a1359d`（P1 已上线，schema 15）；本次发布 = 「单词之舞」第二期：有「意思动作」的词在翻面时做一次它的意思，动作由 Claude 从固定的 28 个舞步里选。
设计契约 `docs/WORD_DANCE_DESIGN.md` §4.3 / §6 / §11，接口契约 `docs/API.md` §9 `DanceSpec.semantic` / `DancePrimitive`、§9.1，AI 契约 `docs/CLAUDE_INTEGRATION.md` §4.5 / §5.6 / §6.1 / §6.8 / §7，前端契约 `docs/FRONTEND.md` §5.1.2 / §6.5。
迁移文件：`0016_word_dances.sql` —— **重建** `jobs` 与 `ai_calls`（CHECK 列表加 `generate_dance` / `dance`）、新建 `word_dances`、`words` 加 `active_dance_id` / `dance_state`。**停机迁移**（和 0011 / 0013 一样）：Mac 上 `launchctl kickstart -k` 先停旧进程再启动，迁移在启动时套用，几千行表重建不到一秒；Lighthouse 上绝不能 `--no-restart`。

---

## 1 变更概览

| 面向 | 变化 |
|---|---|
| 学习者 | 翻面时，有语义舞步的词（up 升起、small 缩小、in 走进盒子、cold 发抖、red 变红、three 分身成三个…）做一次它的意思，正面不做；背面点 🔊 或按 `P` 先拼读再做动作。名词、虚词、抽象词没有语义舞，只有拼读两舞。「减弱动态效果」下只保留姿态颜色 |
| 数据 | 新表 `word_dances`（每词一行 active 的 Claude spec 和模型的 ≤12 字理由 `reason`，旧行 superseded）；`words.active_dance_id` / `dance_state`；`jobs` / `ai_calls` 重建以容纳新任务类型与调用种类 |
| AI | 新任务 `generate_dance`：20 词一次调用，提示词 `dance-v1`，输出按 `dance_v1.json` 校验；每词给模型词形、音标、第一义项和规则层切块，模型确认或改正切块、给出重读、选一个舞步或 none；后验证以规则层为底线。预算：日子上限 `WD_AI_DANCE_DAILY_BUDGET_USD`（默认 0.50，计入总日上限）、单次 `WD_AI_BUDGET_DANCE` 0.25、超时 `WD_AI_TIMEOUT_DANCE_SEC` 120 |
| 入队 | 学习者将要学的词（加入生词库、进批次、推荐词转新词）在排内容任务时顺带排舞步任务——排在内容任务之后、优先级低一档（11 / 21 / 31），等内容的学习者不会排在舞步调用后面；子预算为 0 时什么都不排；`wd dance-annotate --stage xs` 一次性跑完小学 600 词 |
| 接口 | `DanceSpec` 多 `semantic`（`{primitive, params} \| null`）、`source` 可为 `claude`；`Settings.dance_mode = form_only` 从此有实际含义（只拼读、不做意思动作）；管理页 `ai` 多 `dance_today_usd` / `dance_daily_budget_usd` |
| 不变 | 复习算法、批次、词库、配图；P1 的拼读两舞与开关；`docs/SCHEMA.sql`；`wd check db` 的八条不变量 |

## 2 机制要点

- **舞步库**（前端 `components/word/dances.ts`）：28 个原语各一种动作，全部用 em 单位、只动 transform / opacity / color、≤ 2.5 s；六个方位原语站在 CSS 小舞台上（盒子 / 屋顶 / 桌子 / 树 / 两道杠）；cold / hot / sad / 颜色词有静态姿态色（不改大小和字形）。
- **时机**：背面挂载时 `autoplay="semantic"`（仅新词与复习次数 < 3 的卡，`dance_mode = full`）；背面重放 `full`，正面永远 `form`。
- **标注**（`backend/wd/ai/dance.py`）：给模型的义项 = 卡片内容的第一义项，没有内容时取词典里主要词性那一行（内容任务还在路上则顺延 10 分钟再标，最多 6 次）；运行时再查词是否被合并 / 判无效（跳过，状态回 none）；切块拼不回词形 → 用规则切块；重读越界 → 切块和重读一起回退规则层；`color` 没给颜色 → 当作 none；`multiply` 的 n 不是 2/3 → 3；字母标记永远取规则层；最终 `schemas.DanceSpec` 校验通过才写库；一个词写库失败（调用期间被删）只影响它自己的任务。
- **附带修复**（评审发现）：服务启动时把上次进程留下的 `ai_calls` `running` 行关掉（`ledger.close_orphans`），否则它们的预留额会永远占着日上限和子预算；注销账户时一并取消孤儿词的舞步任务。
- **读取**（`wd.dance.spec_for_word`）：有存储的 Claude spec 就用它，否则规则现算；卡片从不等任务。

## 3 验收

- `make test`（新增 `test_db_0016`、`test_dance_annotate`；契约 / fake claude / 预算 / 队列 / 注册表测试扩到 dance；前端 `dances` / `DancingWord` / `StudyCard` 的语义舞用例）；`npm run lint`。
- 手测 `docs/qa-study.md` §7 末尾三条（语义舞）。

## 4 上线步骤（Mac launchd；停机迁移，约 5 秒）

0. 本机测试全绿；用 `scripts/rehearse_migration.py` 在数据库副本上彩排 0016（`jobs` / `ai_calls` 列、行、索引全部保留，CHECK 接受新值，`word_dances` 出现）；提交。
1. 构建前端到 `$D/frontend-releases/<sha>`，切换 `frontend` 软链接（同 P1 发布说明 §4 第 1 步）。
2. `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`：旧进程停止，新进程启动时套用 0016（先写 `backups/pre-migrate-15-to-16.db.gz`），日志出现 `applied migration 0016_word_dances`。正在运行的任务被中断会在启动时被重新排队（stale sweep）。
3. 验证：`/api/health` 正常；`schema_migrations` 最高 16；`jobs` / `ai_calls` 行数与迁移前一致；`PRAGMA integrity_check` ok。
4. 小学词批量标注：先看管理页 `ai.today_usd`；临时把 `WD_AI_DANCE_DAILY_BUDGET_USD` 抬到 3.00、`WD_AI_DAILY_BUDGET_USD` 从 3.00 抬到 6.00 并重启（舞步花费计入总日上限，否则 ≈ $2 的回填会把当晚学习者的例句 / 配图调用挤到明天；脚本在回填结束后把子预算改回 0.50 并重启，总日上限在次日 00:06 改回 3.00），`wd dance-annotate --stage xs --priority 50`，30 次调用约 1 小时（每小时 60 次调用上限与其他任务共享），≈ $2；「结束」= `jobs WHERE type='generate_dance' AND status IN ('queued','running')` 为 0；然后生成按舞步分组的审核页（Artifact）给负责人扫一遍，错的用 `--word W --force` 重标或改提示词。

## 5 回滚

`git checkout 2a1359d` 重建前端快照并重启：旧代码不认识 `generate_dance` 任务和 `word_dances`，但只读不写、无害；需要连库回退时 `wd restore backups/pre-migrate-15-to-16.db.gz`（停服务 → restore → 启动）。

## 6 未决

- 设置页仍是开关（full / off）；`form_only` 需要三档控件 —— P3 第一批已做（`docs/releases/2026-11-word-dance-p3.md`）。
- 标注的人工审核页是一次性脚本生成的 Artifact，不在产品里。
- 线索复习（P3）、手势（P4）、初高中词缀舞（P5）按设计稿分期。

## 7 上线与回填结果（2026-11-08，Mac）

- 14:43 上线 `d143df0`：0016 在启动时套用（< 1 s，快照 `backups/pre-migrate-15-to-16.db.gz`），`jobs` 2297 / `ai_calls` 849 行不变，2 s 内健康。迁移前用 `scripts/rehearse_migration.py` 在副本上彩排通过（68 项）。
- 14:45–14:51 回填：`wd dance-annotate --stage xs --priority 50` 排 592 个任务（8 个词组 / 缩写没有规则 spec：physical education、ice cream、Mr.、Mrs.、Ms.、p.e.、ping-pong、o'clock），30 次调用全部成功，共 **$0.675**（每 20 词 ≈ $0.0225、9.4 s，比预估的 $2 便宜 2/3），无失败、无重试。
- 结果：592 词有 Claude spec，**67 个有动作**（color 8、repeat 5、multiply 4、glow 4、shimmer 4、droop 4、rise 3、dash 3，其余各 1–2），525 个无动作；模型改正规则层切块 12 处（sto·ry、teach·er、T·V、O·K、Jan·u·ar·y、Feb·ru·ar·y、health·y、fa·vor·ite、fa·vour·ite、grand·moth·er、cloud·y、ev·ery），评审认为 10 处更好、2 处等价。
- 评审（5 个评审 + 每条 2 个反驳者，47 个 agent）：67 个动作全部合库；525 个「无动作」没有漏判；确认 4 条——**舞步库空缺** `jump`（跳；库里没有「跳一下」的原语，最接近的 rise 意为向上 / 高处）和 `on`（在……上；库里有 enter=in、under，缺 on），模型判 none 是对的，是否扩库留给 P3（P3 第一批加了 `hop` / `onto`）；**切块** `worker` → work·er、`farmer` → farm·er（规则层的机械 VC·CV 切分，模型没改），已用 `--word worker --word farmer --force` 排了重标，因当日舞步子预算已花完（0.675 > 0.50）顺延到 11-09 00:05 执行。00:05 已执行（dance-v2，与 jump / on 同一次合并调用），但模型再次保留了规则层的 wor·ker / far·mer——提示词要它「除非明显错误，否则保留规则层建议」，所以这两个词的切块要靠规则层的 -er 后缀处理（P3 发布说明 §6 / §7）。
- 审核页（Artifact「小学语义舞分配」）：按舞步分组，点卡片预览动作。
