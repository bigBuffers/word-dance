# 发布说明 · 2026-11 · 学习顺序（派生列 `words.learn_rank`，迁移 0014）

基线 `main @ cd3df8c`（K-12 发布：schema 13，交付种子 `stats.json.content_sha256` = `24f3b949…6692`，已部署在 Mac 上）；本次发布 = 四条实现车道
（A 策略 / B 持久化与运维 / C 五处排序 / D 文档与文案）合入、集成门禁（设计 §8）通过的那个提交——后端部分**只需重启**，前端部分只是一个标签。
设计契约是 `docs/analysis/2026-11-06-learn-order/DESIGN.md`（下文「设计」），本文章节与设计 §1 / §2 / §6 / §7 对应。
迁移文件：`0014_learn_rank.sql`（`words` 表一条 `ADD COLUMN learn_rank INTEGER`，纯附加：无默认值、无索引、不重建表、不动 `kv`）。
种子文件、`docs/SCHEMA.sql`、`VocabSort` 联合、`types.ts` 与 `scripts/check_contract.py` 都不变。

**数字的约定。** 本文的名次与计数（「`the` 在小学第 526 张」「前 30 张 0 个语法词」…）全部是**设计阶段的参考模拟**（`sim_final_policy.py`）在线上库
只读副本上的实测值（设计 §1.5 / §1.6），只用来说明形状与量级；发布后的权威值是随本次提交生成的 `data/seed/learn_order.json`（`stages.<阶段>.first`、
`acceptance`，由 `wd learn-order --report` 在排练库上写出）和 `pytest -m full_seed` 直接从库里算出的结果。测试与仓库文档从不把这些数字写成常量
（FACTS §3 约定）。§3.1 的词表是 2026-11-06 上线前排练（§6 第 0 步 c/d：`rehearse_migration.py` 与 `wd learn-order --show xs|zk --top 30` 在线上库 `VACUUM INTO` 副本上的输出），与参考模拟逐词一致。

---

## 1 变更概览

| 面向 | 变化 |
|---|---|
| 学习者 | 词库默认排序、引导期筛词（`GET /api/screen/next`）、每日推荐词（`batches.select_words` / `add_more`）与管理员预生成候选（`prewarm.candidates`）不再按成人 COCA 名次 `frq` 出词，改按派生的**学习顺序** `words.learn_rank`；词库排序芯片「词频」改名「学习顺序」（接口值仍是 `sort=freq`，`VocabSort` 不变）；词库「全部」页签从小学课程开始、课标外最后；各阶段页签先出本阶段新增词，再出更低阶段的词（与该主攻阶段的筛词流一致） |
| 数据 | `words` 表新增可空整数列 `learn_rank`（迁移 0014），由 `backend/wd/services/learn_order.py` 从库里已有的列（`lemma`、`pos` → 主词性、`frq`、`bnc`、`sources`、`stage_min`、`word_forms`）派生；导种子、服务启动、每夜 03:30 维护和 `wd learn-order` 时重算；为 NULL 时退回今天的 `frq` 顺序 |
| 运维 | 新命令 `wd learn-order [--dry-run] [--show STAGE [--top N] [--cur STAGE]] [--report PATH] [--db PATH]`；`wd check db` 从 schema 14 起多四条不变量（共八条）；`scripts/rehearse_migration.py` 新增 `check_0014`（在拷贝上重算并打印小学 / 初中新增前 15 个词）；`deploy/install.sh` 在 `import-seed` 之后多跑一步 `wd learn-order`；新增复核工件 `data/seed/learn_order.json` |
| 不变 | 查词自动补全（`GET /api/lookup` 的 `suggestions`）仍按原始词频（API.md 22，有意的例外）；`difficulty` 排序的第一键不变，只是尾部换成学习顺序；已生成的批次保留其 `push_items`；已评分的词不受影响；种子内容哈希不变，不导种子 |

**给产品负责人的两句话。** 卡片按英语里的常用程度排序（COCA 词频，缺的用 BNC 补），语法词——冠词、代词、介词、连词、助动词——排在本阶段所有实义词之后。
没有词频的词（上海词组、缩写）、副词和感叹词按均匀间隔插入，月份和星期各作为一组按日历顺序出现，am/is/are 紧跟 be。

---

## 2 策略（设计 §1）

无任何数值可调参数；唯一的人工数据是 16 个语法词 lemma 与 19 个月份 / 星期 lemma。策略有版本号 `LEARN_ORDER_VERSION`（`services/learn_order.py`，本次 `lo-1`）：
改任何规则都必须升版本，否则 `test_learn_order.py::test_golden_table_lo_1`（迷你种子 62 词的黄金表与 sha256 摘要）会失败。

1. **词频顺序。** 一个词的名次 = `frq`（COCA）；`frq` 为空或 0 时用 `bnc`（BNC，量纲相同）；两者都没有 → 无名次。参考模拟里 BNC 救回 225 个种子词
   （小学的 12 个月份、7 个星期、`colour`、`an` 都在其中）。
2. **语法词排在本阶段实义词之后。** 语法词 = 主词性（`wd.images.style.dominant_pos`，与配图功能词门同一个读法）∈ {介词 `i`、连词 `c`、限定词 `d`、
   代词 `p`、冠词 `a`、不定式标记 `t`}（即 `FUNCTION_POS` 去掉感叹词 `u`），或 lemma ∈ {a an the be do have can could will would shall should may might
   must ought}，或 `sources` 带 `inherit:` 令牌（am is are does）。语法词在同一「阶段距离组」内排在全部实义词之后，彼此仍按词频。副词与感叹词**不是**语法词。
3. **没有词频的词均匀撒入。** 上海词组（`kind='phrase'`，参考模拟 381 个，全部无 `frq`）、缩写（`mr.` `mrs.` `ms.` `p.e.`）等先按「最难的成分词」排序
   （成分词经 `word_forms` 解析，`have to` 早于 `the pacific ocean`），再按等间隔撒进本阶段的词频序列（第 k 个落在第 `ceil((k − ½)·n_有名次 / n_无名次)` 个有名次的词之后）。
4. **副词与感叹词也均匀撒入**，彼此保持词频序（`not` 仍然很早，`very` 中段）；感叹词同样（`yes` 早、`goodbye` 晚），四级的 `oh` 不再是第 1 张。
5. **月份、星期各作为一组。** 12 个月份锚在成员名次的中位数上，按 1 月 → 12 月的日历顺序连续出现；7 个星期同理。`may` 在这里是月份，不是情态动词；
   `march`（动词义）、`august`（形容词义）也按月份处理。
6. **粘连形式。** `am / are / is` 紧跟 `be`（be + 1 / 2 / 3），`does` 紧跟 `do`；它们自己的 `frq` / `bnc` / `pos` 忽略（`is` 的 `bnc` 24648 是垃圾值）。
7. **阶段距离不变、只补一条。** 筛词 / 推荐词 / 词库页签 / 预生成仍先按阶段距离（0 = 主攻阶段，更高阶段 `2(s − cur) − 1`，更低阶段 `2(cur − s)`），
   新增：`stage_min` 为空 → 距离 11（`2 × 阶段数 + 1`，由枚举推出），**排最后**。以前这样的行排在每个用户筛词的第一位（WLC 核验 C10 的手工插入行陷阱），
   现在排在 601 / 601。词库「全部」页签取 `cur = 1`，等价于 `COALESCE(stage_min, 6)` 升序：小学课程在前，课标外最后。
8. **键的编码。** `learn_rank = (语法词 ? 10 000 000 : 0) + 名次 × 100 + 子序号`（0 本词 · 1–19 粘连形式 · 20 撒入的无词频词 · 21–32 月份 · 33–39 星期 ·
   40 副词 · 50 感叹词）；同键时按 `(frq IS NULL OR frq = 0), frq, lemma` 决胜（COCA 名次先于 BNC 救回的，再字母序；`lemma` 唯一，所以全序）。完整 ORDER BY
   是 `learn_order.ORDER_SQL`：`w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma`，前面按场合加阶段距离或 `COALESCE(difficulty + 1, …)`。
9. **不读的东西。** `kind`、`collins`、`oxford`、`difficulty`、`exchange_json`、用户数据、时钟。`pos` 只经 `dominant_pos` 读：Claude 写的标签形 `pos`
   （`v./n.`）读作「无词性」= 实义词，所以查词填 `pos` 不会改变任何词的类别。

---

## 3 预演结果（§3.1 为排练输出；§3.2 / §3.3 为参考模拟，以 `learn_order.json` 为准）

### 3.1 各阶段本阶段新增词（`stage_min = 该阶段`）的前 30 张

- **小学**（600 词；排练输出 2026-11-06，`wd learn-order --show xs --top 30`）：say · go · get · make · know · one · time · year · not · think · people · take · see · come · two · want · way · look · first · new · day · use · man · find · up · give · tell · good · physical education · woman
- **初中新增**（1,949 词；排练输出 2026-11-06，`wd learn-order --show zk --top 30`）：other · thing · have to · life · need · state · become · go in for · high · leave · just · mean · go on · group · seem · country · problem · get on · start · american · part · get on with · case · company · system · program · get to · government · number · point
- 作对照，今天（cd3df8c）小学的前 30 张：the be and of a in to have it i that for you he with on do say this they at but we his from not by she or what（FACTS §1：28 个语法词）。

四级新增与六级新增的头部基本是今天的头部去掉感叹词与语法词（四级前 100 与今天重合 90 个，参考模拟）；高中新增 `issue political guy policy economic …`。
排练脚本第 0c 步打印每个阶段的前 15 个，`wd learn-order --show xs --top 30` / `--show zk --top 30` 打印前 30 个并逐词注明原因（`how` 列：native / dealt / set / glued / adverb / interj）。

### 3.2 探针位置（参考模拟；小学，除非注明）

| 探针 | 位置 |
|---|---|
| 月份 / 星期 | 1 月 → 12 月在 243–254 连续、日历序；周一 → 周日在 343–349 |
| be 族 | be 527 · am 528 · are 529 · is 530 · do 545 · does 546 |
| 语法词块 | 526–600（75 词）：the 526 · a 533 · in 534 · have 536 · i 538 · you 541 · on 544 · an 555 · like 575（见 §5）· no 580；今天 the 在第 1 张 |
| 副词 | not 9 · up 25 · so 42 · out 58 · now 75 · how 91 · then 107 · also 123 · here 139 · well 156 · very 172 · too 222 |
| 感叹词与客套话 | yes 64 · thank 158 · hi 191 · sorry 278 · hello 329 · ok 436 · goodbye 463 · please 469 · bye 514 |
| 无词频的小学词 | physical education 29 · ice cream 85 · email 142 · colour 195 · mr. 198 · mrs. 265 · ms. 322 · p.e. 385 · ping-pong 441 · schoolbag 498（今天全在 571–600） |
| 数词 | one 6 · two 15 · first 19 · three 40 · four 88 · five 108 · second 137 · hundred 189 · ten 226 |
| 具体名词 / 颜色 | mother 76 · book 83 · father 97 · teacher 135 · red 181 · dog 216 · blue 227 · cat 357 · apple 399 · pen 431 |
| 初中新增 | have to 3 · go in for 8 · just 11 · be made of 41 · london 44 · get up 50 · only 52 · even 72 · centre 78 · programme 100 · would like 121 · because of 224 · look after 294 · such as 445 · according to 1734 · kung fu 1842 · favour 1855 · grey 1867 · as 1873 · if 1874 · would 1875 · could 1877 · although 1905 · unless 1932；前 200 张里 42 个词组，之后每 100 张约 21 个（今天前 200 张 0 个） |
| 高中新增 | 首个语法词在 1248 |
| 四级新增 | simply 10 · particularly 27 · oh 854（今天第 1）· due 1707 · via 1710 |
| 六级新增 | currently 16 · yeah 642 · alas 1922 |
| 词库「全部」 | the 526 · is 530 · hello 329 · monday 343 · other 601 · have to 603 · just 611 · 课标外从 9,381 起（`bookshelf` 9,489）；「初中」页签第一个小学词在 1,950 |

### 3.3 验收数字（`pytest -m full_seed` 从库里算，计数而不是词）

| 断言（每阶段本阶段新增词） | 参考模拟 | 门槛 |
|---|---|---|
| 前 30 张中的功能词（FACTS 口径：主词性 ∈ `FUNCTION_POS`、25 形助动词清单 `learn_order.ACCEPTANCE_AUX_LEMMAS` 或 `inherit:`） | xs 0 · zk 0 · gk 0 · cet4 0 · cet6 0 | 每阶段 `== 0` |
| 小学前 30 张中的副词 | 2 | `≤ 2` |
| 12 个月份连续且日历序 | 243…254 | 12 个连续位置，january 在前 |
| 初中新增前 200 张中的词组（`kind='phrase'`） | 42 | `≥ 40` |
| `frq` 为空的最长连续段 | xs 7（星期块）· zk 3 · gk 2 · cet4 1 · cet6 3 | 每阶段 `≤ 7` |
| `learn_rank` 为空的阶段词 | 0 | `== 0` |
| 四级前 100 与今天的重合 | 90 | 仅记录 |

另：`learn_order.json` 的 `policy` == 代码的 `LEARN_ORDER_VERSION` == `kv.learn_order.version`，`seed` == `stats.json.content_sha256` == `kv.seed_version`；
19 个月份 / 星期全部 `stage_xs = 1`；`am is are does` 带 `inherit:` 令牌；`GET /api/vocab?stage=xs` 第一页前 8 个 == `stages.xs.first[:8]` == 库里的 SQL 顺序。

---

## 4 机制（设计 §2）

### 4.1 列、重算与退化

- `words.learn_rank INTEGER`，可空，无索引（每条学习顺序 ORDER BY 前面都有 CASE / COALESCE 项，都在临时 B 树里排序，参考模拟：计划不变，600–9,618 行 1–5 ms）。
  线上种子的最大键 13,812,400（参考模拟），永远 < 2·10^7；`pack()` 的上界有单元测试钉住。
- **重算何时发生。** 服务启动（`main.startup` 在 `seed_check` 之后调 `learn_order.ensure_current`：存储值与计算值逐行比对，只 `UPDATE` 变化的行；
  无变化 ≈ 60 ms，首次填充 ≈ 80 ms——2026-11-06 排练在 9,618 词副本上的实测，设计估计是 20 / 40 ms）；导种子（`seed.import_seed` 同一事务内，名次与 `kv.seed_version` 一起落地；策略异常不回滚导入，
  只记 `system_events('learn_order_failed')`）；每夜 03:30 维护；`wd learn-order`；Lighthouse 的 `install.sh` 在 `import-seed` 之后。
  **不**触发：单独的 `wd migrate`（服务下次启动补）、`wd restore`（恢复的文件自带名次，旧文件在下次启动补齐）。
- `kv`：`learn_order.version`（写名次的代码的策略版本）、`learn_order.seed_version`（为哪个种子哈希算的——旧代码导了新种子会让它 ≠ `kv.seed_version`）、
  `learn_order.computed_at`、`learn_order.stats`（< 2 KB 的逐阶段统计：n / ranked / from_bnc / dealt / set / glued / adverb / interj / closed / p10 / p50 / p90 /
  first8，加标签形 `pos` 的阶段词数、撒入漂移数 `drift_dealt`（上次比对里被重新撒入的阶段词数，见下「运行时新词」）与课标外漂移数 `drift_none`——策略版本刚升级的那次比对两者都记 0，因为那时每个键都会动，不是漂移；`wd check db` 原样打印一行 `… · dealt drift N · 课标外 drift N · label-pos N`）。首次填充写一条 `system_events('learn_order_recomputed')`（导种子路径不写）。
- **退化。** NULL 的行排在同阶段距离组内所有有名次的行之后，按今天的 `frq` 顺序——参考模拟验证「全部为 NULL == 今天的顺序」；所以迁移已应用、名次未填的那一刻，
  列表就是今天的列表。
- `updated_at` 从不因重算移动（模板卡 `/media/card/{id}.svg` 的 LRU 键不失效）。
- **群体涟漪。** 撒入的无词频词、副词、感叹词的位置取决于同组其他词，所以一次种子变更可能让被触及阶段的这些词换位置（`test_seed.py` 的涟漪测试钉住：
  只有 `how != 'native'` 的行会动）；原生有名次的词的键只取决于自身。
- **运行时新词。** 用户添加的 ECDICT 词在 `_insert_word` 时用 `learn_order.best_effort_rank` 直接得到精确键（有原生名次）；临时词（待校验）为 NULL；
  无词频的新词到下次重算才拿到撒入位置。**运行时的词或词形也能动到阶段词**（评审 F-1，线上副本实测）：规则 3 的「最难成分词」要在**全部**词行与
  `word_forms` 里解析，所以用户查词新建的行（`sooner`、`york`、`kung`）或查词写入的词形（`sooner → soon`）会让某个无词频阶段词组的成分词变得可解析，
  从而重排该组撒入词的次序——一次 2–341 个初中键，每个只挪一个宿主位——直到下次重算（启动、03:30 维护、`wd learn-order`）。原生词、月份 / 星期、副词、感叹词、
  粘连形式只读种子管理的输入（运行时行没有阶段旗标，也没有 `inherit:` 令牌），键不会在运行时漂移。所以 `learn_rank_matches_policy` 只数这些「种子规则」安置的阶段词
  （`learn_order.drift(conn).policy`），被重新撒入的阶段词计入 stats 行的 `dealt drift`（只记录）。四个运行时 `pos` 写入点只填空 `pos`，不改类别，无挂点（设计 §7 A7）。

### 4.2 `wd learn-order`（`wd.services.learn_order` 拥有；DEPLOY §9）

| 用法 | 作用 |
|---|---|
| `wd learn-order` | schema < 14 时一行拒绝、退出 1（「run `wd migrate` first」，同 `import-seed`）；否则重算并打印 `learn order lo-1: <行数> rows, <N> updated in <秒> s; 0 stage words unranked`（阶段词仍有未排名的则退出 1） |
| `--dry-run` | 不写任何东西；打印**变动报告**：每阶段 记录数 · 名次变化数 · 移动 ≥ 50 位的数 · 最大位移 · 旧前 10 → 新前 10，再列 20 个最大上升与 20 个最大下降——每次调策略的复核工件 |
| `--show STAGE [--top N] [--cur STAGE]` | `位置 lemma learn_rank closed how frq bnc eff` 逐行：某阶段本阶段词的前 N 个（带 `--cur` 则是该主攻阶段的页签 / 筛词顺序）；`how` 说明这个词为什么在这个位置 |
| `--report PATH` | 紧接重算、从刚存下的名次写 §4.1 的 JSON 文档（发布提交里的 `data/seed/learn_order.json`）；与 `--dry-run` / `--show` 同用是用法错误（退出 2）——那时没有重算，文档会以本代码的策略戳描述未重算的存储键 |
| `--db PATH` | 像 `wd check --db`：排练拷贝、恢复演练 |

可以挨着运行中的服务跑：一个 ≤ 30 ms 的 `BEGIN IMMEDIATE`；读者看到旧名次或新名次（翻页边界可能移动一次，与导种子后一样）。

### 4.3 `wd check db` 八条不变量（`backend/wd/diag.py`，schema 14 起）

导入后一次干净的 `wd check db` 打印（`kv.learn_order.version: lo-1` 与 `kv.learn_order.stats: …` 两行在 `kv.backup.last` **之前**）：

```
invariant stage_min_consistent: ok
invariant xs_subset_zk: ok
invariant stages_json_known: ok
invariant seed_version_matches_file: ok
invariant learn_rank_present: ok
invariant learn_order_current: ok
invariant learn_rank_matches_policy: ok
invariant calendar_words_in_xs: ok
```

| 不变量 | 含义 | 违反时 |
|---|---|---|
| `learn_rank_present` | 阶段词（`stage_min IS NOT NULL`，未合并）都有 `learn_rank` | `N violation(s) (stage words without learn_rank — the next wd serve start or wd learn-order fills them)` |
| `learn_order_current` | `kv.learn_order.version` == 代码版本，`kv.learn_order.seed_version` == `kv.seed_version`，且已算过 | 三种原因各一行：版本不同 / 为别的种子算的 / 从未算过；修法都是 `wd learn-order` |
| `learn_rank_matches_policy` | 由种子规则安置的阶段词（原生 / 月份星期 / 粘连 / 副词 / 感叹词）存储的键 == `learn_order.rank_rows()` 现算的键（`drift(conn).policy`，设计 §7 A8）；被运行时词或词形重新撒入的阶段词（§4.1「运行时新词」）与课标外漂移只记在 stats 行的 `dealt drift` / `课标外 drift` 里 | `N violation(s) (stored learn_rank of stage words differs …; run wd learn-order)`——手改 `learn_rank` 会被它抓到（手改撒入词的键则由下次重算改回） |
| `calendar_words_in_xs` | 库里**存在**的月份 / 星期行都 `stage_xs = 1` 且 `stage_min = 1`（19 个是否齐全由 `full_seed` 断言；迷你种子没有它们） | `N violation(s) (month/weekday rows without stage_xs = 1 / stage_min = 1)` |

任一非零 → `[FAIL] db`、退出 1；查询出错或策略计算抛异常都报 `query failed (…)`，不计违反、不抛 traceback。旧的四条不变（`STAGE_INVARIANTS` 钉在 PLAN 字面）。M4 的「有阶段旗标 ⇒ `stage_min` 非空」已由
`stage_min_consistent` 覆盖，不另加。

### 4.4 排练脚本与安装脚本

- `scripts/rehearse_migration.py <拷贝>`：待办恰好 `(14, 'learn_rank')`；`check_0014` 核对列类型 / 可空 / 无默认 / 无索引、`words` 与 `v_bank` 行数不变、
  刚应用时全为 NULL，然后**在拷贝上重算**：0 个阶段词无名次、stale 0、第二次重算 0 行变化、`MAX(updated_at)` 不变、每阶段前 30 张 0 个功能词；
  `[info]` 打印小学 / 初中新增前 15 与逐阶段摘要（n · ranked · dealt · closed · 前 8）；探针：`UPDATE words SET learn_rank = NULL` 在 BEGIN…ROLLBACK 内被接受
  （NULL 是合法状态）；`check_invariants` 顺带打印四条学习顺序行，脚本与 `wd check db` 不会各说各话。空库 0001 → 0014 仍是 25 张表 + `v_bank`。
- `deploy/install.sh` 第 141 行后新增 `run "$REPO/.venv/bin/wd" learn-order || echo "WARN: …"`：单元启动前填好列，`--no-restart` 升级也能让 `wd check db` 一致；`|| echo WARN` 与 `claude-check` 一行同款——`wd learn-order` 在阶段词仍未排名时退出 1，脚本在 `set -e` 下不能因此在停服之后、systemd 步骤之前中止（服务启动对同一情形本就是软失败）。

---

## 5 接受的代价与替你做的决定（设计 §7 摘要）

1. **`like`（喜欢）在小学第 575 张。** ECDICT 给 `like` 的词性份额以介词为主，主词性 `i` → 语法词块。接受为数据问题（将来用 ECDICT 份额覆盖，一个常量 + 升版本）。
   同一原因在语法词块末尾的还有 `front` / `near` / `behind` / `half` / `much` / `where` 等。
2. **英式拼写在初中靠前。** `colour`（小学 195）、`centre` 78、`programme` 100、`london` 44 等由 BNC（英国语料）救回，名次偏靠前；美式孪生 `color` / `center` 按 COCA。
   G8「英式拼写继承美式孪生的 `frq`」是种子构建器的事（§9）。
3. **撒入位置是均匀间隔，不是词频证据。** `schoolbag` 498、`mr.` 198、`mrs.` 265、`p.e.` 385 只说明「均匀分布在本阶段里、按最难的成分词再字母序」，别拿它们判断难度。
4. **`the` 在小学第 526 张。** 语法词二元后置（G10 保留）：小学生在 525 个实义词之后才见冠词、代词、介词、be 动词。中考测试者若反馈语法词来得太晚，再做
   G10 的「初中及以上 50% 窗口」。
5. **感叹词撒入**（G5）：`yes` 64、`hi` 191、`hello` 329、`goodbye` 463；四级的 `oh` 从第 1 张到 854。排序闭类 `ORDER_CLOSED_POS` 因此比配图门 `FUNCTION_POS` 少一个 `u`
   ——由代码从后者推出，测试钉住。
6. **查词补全保持原始词频**（A4，API.md 22）：它是自动补全，不是学习顺序。
7. **各阶段页签读起来像该主攻阶段的筛词流**（A2）：初中页签先初中新增、第 1,950 个起是小学词；`kimi`（主攻初中）看到的推荐顺序与 K-12 说明 §3.4 末条一致。
8. **只改标签，不加第四种排序**（A3）：`sort=freq` 的接口值不变，避免 TS↔Pydantic、`check_contract`、API.md §9 的八处联动。
9. **同键时 COCA 先于 BNC**（A13）：与评审的元组键相差几位（`an` / `by` 554 / 555；月份 243–254 而不是 241–252，因为 G5 把 `yes`、`hi` 提前了）。
10. 无索引（A6，需要时 `0015 CREATE INDEX` 2 ms）；每夜自愈而不是逐点刷新（A7）；`learn_rank_matches_policy` 只看种子规则安置的阶段词（A8，§4.1「运行时新词」）；不做会 FAIL 的 `pos` 不变量
    （A9：662 个阶段词合法地没有 `pos`，查词合并可能填一个标签进去）；`learn_order.json` 入库（A11）；群体撒入而不是 crc32 散列（A12：保住「最容易的词组先出」）。

---

## 6 上线步骤（Mac launchd；只需重启）

数据目录 `D=/Users/sqin/word-dance-data`；服务 `com.word-dance.server`（备份代理 `com.word-dance.backup` 不用动）；所有 `wd` 命令需 `WD_DATA_DIR`。
与 K-12 发布不同，本次**不停服务、不手工迁移、不导种子**：`wd serve` 启动时自己应用 0014（应用前写 `$D/backups/pre-migrate-13-to-14.db.gz`），`seed_check`
因内容哈希未变而静默，`ensure_current` 在接受第一个请求前填好全部名次。停机时长 ≈ 一次进程重启。

0. **在私有拷贝上排练**（服务照常运行；编号是因为本文 §3.1 要带上它打印的词）：
   ```sh
   D=/Users/sqin/word-dance-data; M=$(mktemp -d /private/tmp/wd-learn-order-XXXX)
   a. .venv/bin/python -c "import sqlite3; sqlite3.connect('$D/word-dance.db').execute(\"VACUUM INTO '$M/word-dance.db'\")"   # 一致副本；排练永远不写 $D
   b. git checkout <发布提交>                                # 可编辑安装已指向 backend/；无新依赖
   c. .venv/bin/python -I scripts/rehearse_migration.py $M/word-dance.db
      # 期望：pending 恰好 [(14, 'learn_rank')]；check_0014 ok（列、无索引、拷贝上重算：0 个阶段词无名次、stale 0、幂等、updated_at 不变、
      # 每阶段前 30 张 0 个功能词）；[info] 小学 / 初中新增 前 15；退出 0
   d. WD_DATA_DIR=$M .venv/bin/wd learn-order --dry-run      # 变动报告：首次填充每行都「变化」——读每阶段的前 10
      WD_DATA_DIR=$M .venv/bin/wd learn-order                # 填充拷贝；然后 --show xs --top 30 / --show zk --top 30 目测顺序
   e. WD_DATA_DIR=$M .venv/bin/wd learn-order --report data/seed/learn_order.json   # 入库工件（§4.1）；git add
   f. WD_DATA_DIR=$M .venv/bin/wd check db                   # 八条 `invariant …: ok`，kv.learn_order.version lo-1
   g. WD_FULL_SEED_DB=$M/word-dance.db .venv/bin/python -m pytest backend/tests -m full_seed -q
   ```
   第 c / d 步打印的词表已抄进本文 §3.1（2026-11-06 的排练），`learn_order.json` 随发布一起提交；日后重跑排练若与 §3.1 不同，以排练输出为准并更新本文。
1. **前端快照**（只因「学习顺序」标签要上；SPA 与 API 兼容，可先于后端发布——K-12 说明 §6 第 1 / 5 步的配方）：
   ```sh
   SHA=$(git rev-parse --short HEAD); cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm ci && npm run build -- --outDir $D/frontend-releases/$SHA.new --emptyOutDir && cd ..
   mv $D/frontend-releases/$SHA.new $D/frontend-releases/$SHA && ln -sfn frontend-releases/$SHA $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"   # BSD mv 无 -T
   ```
   进程在启动时解析符号链接，所以第 2 步的重启同时让新快照生效。
2. **重启 = 迁移 + 填充**：`launchctl kickstart -k gui/$(id -u)/com.word-dance.server`。
3. **验证**：
   ```sh
   curl --noproxy '*' -fsS http://127.0.0.1:8000/api/health
   grep -E 'applied migration 0014_learn_rank|learn_order_recomputed|learn order|learn_order_failed|MigrationError' ~/Library/Logs/word-dance/word-dance.log | tail
   #   期望：一条 `applied migration 0014_learn_rank`、一条学习顺序重算的记录；没有 `learn_order_failed` / `MigrationError`，
   #   也没有 `seed version changed; importing`（内容哈希未变，seed_check 静默）
   ls -la $D/backups/pre-migrate-13-to-14.db.gz
   WD_DATA_DIR=$D .venv/bin/wd check db                   # 线上库八条 ok 行
   sqlite3 -cmd '.timeout 5000' $D/word-dance.db "SELECT lemma FROM words WHERE stage_min = 1 ORDER BY learn_rank IS NULL, learn_rank, (frq IS NULL OR frq = 0), frq, lemma LIMIT 8"
   #   → 等于 data/seed/learn_order.json 的 stages.xs.first 前 8（排练：say go get make know one time year）
   sqlite3 -cmd '.timeout 5000' $D/word-dance.db "SELECT COUNT(*) FROM words WHERE stage_min IS NOT NULL AND learn_rank IS NULL"      # 0
   ```
   登录后：`GET /api/vocab?stage=xs` 的 `items[0..7].lemma` 等于上面的 SQL；`GET /api/vocab`（全部）开头相同；`GET /api/screen/next?stage=xs&count=30` 没有冠词 /
   代词 / 介词；词库排序芯片显示「学习顺序」；管理页事件表有一条 `learn_order_recomputed`。
   对线上数据的影响：已建批次保留其 `push_items`；下一次夜间建批次与每一页筛词用新顺序；已评分的词不受影响（`NOT EXISTS user_words`）。

---

## 7 Lighthouse（Linux / systemd，`deploy/install.sh`）

在目标机上同样先对拷贝排练（第 0 步 a–f；`rehearse_migration.py` 可移植，SQLite ≥ 3.26）。然后 `git pull && deploy/install.sh`：停 → 发布快照 → `wd migrate`（0014）→
`wd import-seed`（无事可做）→ **`wd learn-order`**（新增的一行，在单元启动前填好列）→ 起。本次**允许** `--no-restart`（纯附加），但旧进程在重启前仍按 `frq` 出词。
之后 `wd check db` 八条 ok 行。从 Mac 复制过去的库若已在 Mac 上完成本次升级，则自带名次与 `kv.learn_order.*` 戳，VPS 上启动只做一次比对。
`docs/QUICK_DEPLOY_AND_MOBILE.md` §1.3 末已补这一段。

---

## 8 回滚

- **只回代码（正常情况）**：`git checkout cd3df8c && launchctl kickstart -k gui/$(id -u)/com.word-dance.server`（标签已上则再把 `$D/frontend` 指回
  `frontend-releases/cd3df8c`：`ln -sfn frontend-releases/cd3df8c $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"`——BSD `mv` 无 `-T`，`mv -f` 会把链接挪进旧快照目录）。旧代码不读 `learn_rank`（每条 `INSERT INTO words` 都写明列名；读者按列名取 `sqlite3.Row`；`v_bank` 写明 `words` 的列），
  列表立刻回到 `frq` 顺序；列与 `kv.learn_order.*` 留着无害。
- **只回策略**：改 `rank_rows`，升 `LEARN_ORDER_VERSION`，更新黄金摘要与 `learn_order.json`，重启（重算 ≈ 80 ms，排练实测）。
- **整库快照**（只有文件本身必须退回时）：`launchctl bootout …; wd restore $D/backups/pre-migrate-13-to-14.db.gz --yes; git checkout cd3df8c; launchctl bootstrap …`
  ——会丢失快照之后的学习记录；对一条附加迁移不推荐。

---

## 9 未决（设计 §3 末；不阻塞本轮）

- **G8 英式拼写继承美式孪生的 `frq`**（`colour ← color`、`favourite ← favorite`、`grey ← gray`、`honour`、`centre`、`programme`、`realise`、`theatre`、`labour`、`defence`、
  `licence`、`cheque` …）：确定性、无常量，但改变种子内容哈希 → 单独的种子发布，构建器数据规则。
- **`mr.` / `mrs.` 的构建期 `frq` 补丁**（纯粹派 §6 #8）：同上，走种子。
- **第一课起始词表**（具体性）：等第一批三年级以上小学生的反馈之后再定，不预设。
- **G10 初中及以上语法词 50% 窗口**：只在中考测试者反馈语法词来得太晚时做（一个规则 + 升版本）。
- `like` / `front` / `near` / `behind` 的 ECDICT 词性份额覆盖（§5 第 1 条）：数据问题，先观察。
- **粘连链**（评审 N-5）：设计只定义了 `am is are → be`、`does → do` 一层粘连；若种子将来出现 `done → did → do` 这样的链，链上的形式按其**直接**宿主的形式编号，
  会与根的另一形式（`does`）同键、靠 `frq` 尾键决胜。线上种子没有链；改成按根编号会改变 `rank_rows` 的输出，须升 `LEARN_ORDER_VERSION`（lo-2）并重生成两份黄金摘要与 `learn_order.json`，留待下一次策略迭代。
- **运行时词触发的阶段词重撒**（评审 F-1，§4.1「运行时新词」）：本轮只收窄了门禁的范围并把它记成 `dealt drift`；若希望查词后立刻稳定，可在 `_insert_word` / `add_form` 后挂 `ensure_current`（≈ 70 ms，设计 §7 A7 的反向决定），或把规则 3 的成分词解析限制在种子行（策略变更，lo-2）。
