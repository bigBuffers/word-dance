# 词表来源与种子流水线 · 评审（角度：产品与学习科学怀疑者）

日期 2026-11-06 · 基线 `main @ 75df534` · 评审对象：`official-purist.md`、`continuity.md`、`data-engineering.md`（同目录）。
我的视角：上海小学生（1–5）/ 初中生（6–9）/ 高中生与两位现有用户**实际会看到什么**——默认值、页签与 chips、排序与推荐、释义是否正确、是否过度/欠设计。配图线的 D1 证据对本线不直接适用（三份设计都不碰配图，A5），只在 §2.5 借它谈「小学词的排序」。

所有复算脚本只读：`scratchpad/judge-learner-product/check.py`（`python3.12 -I`，`live-copy.db` 以 `?mode=ro` 打开，词表取 `data/lists/` 实际文件，括注/并列按三份设计共同的规则拆分，解析噪声 ±1–2%）。

---

## 0. 结论先行

| | official-purist | data-engineering | continuity |
|---|---|---|---|
| fit（上海 K-12 + 老用户） | **8** | 7 | 5 |
| correctness（迁移/数据/契约） | 7 | 7 | 5 |
| effort_risk（高 = 工作量小、风险低） | 6 | 4 | 7 |
| maintainability | 7 | **8** | 5 |
| evidence | **9** | 7 | 7 |
| rollout | 6 | 7 | 7 |
| **overall** | **7.3** | **6.7** | **5.9** |

**排名：official-purist > data-engineering > continuity。**

一句话：三份设计的「对现有数据零影响」都成立——我独立复算，无论哪种重标，77 条 `user_words` 与 49 条 AI 内容**无一**被降级或失去阶段（§4.1）；因此 continuity 用来换取 16–24% 旧考纲词的「不丢阶段」承诺，在真实数据上保护的是一个空集，而它的两条规范化规则会给上海中考词 `hot-dog` 和小学词 `mum` 挂上错释义（「v. 卖弄」「n. 菊花」，§3.3）。official-purist 的数字最经得起复算（我得到 412/189/153/70 对它的 415/188/155/72；578 = 569/6/2/1 完全一致），阶段口径与现行课标一致，并把 `abortion/bungalow` 一类旧「高考 3500」词移出 K-12 池；短板是依赖重编号却不谈 `difficulty` 尺子（Q5）、让 `is/are/does` 变成无阶段词、把上海 331 个词组推到第二版。data-engineering 的机制（与 Q1 解耦的 `stage_min`、manifest 的 `expect±tolerance`+sha256、内容哈希版本、dry-run 孤儿行）是最值得嫁接的，但 14 人日对一个一年改两次的 9k 词种子偏重，预览数字没有包含它自己决定加进去的附表与词组。

---

## 1. 抽查记录（引用是否属实）

共抽查 30 余处，列出主要的；✓ = 与 75df534 / 文件 / 线上副本一致。

| # | 设计 | 引用 | 结果 |
|---|---|---|---|
| 1 | 三者 | `seed.py:43 STAGES`、`:47-68 SEED_COLUMNS`（旗标列 :60-64）、`:72-82 _UPSERT_SQL`、`:184-185` 未知阶段码过滤、`:208` `STAGES.index(stages[0]) + 1`、`:239-241` 表头词守卫、`:258/:287` 文件哈希、`:333-360` CLI | ✓ 全部属实 |
| 2 | 三者 | `schemas.py:25/26/51/52/56-67`（`:65` `1 <= index <= 4`）、`:47 Difficulty`、`:488 VocabQuery.stage` | ✓ |
| 3 | 三者 | `vocab.py:55` 旗标筛选、`:78 COALESCE(difficulty, stage_min, 5)`、`:86-98 /api/stages`、`:89 new_only_total` | ✓ |
| 4 | 三者 | `bank.py:85-86 DEFAULT_STAGES/DEFAULT_CURRENT_STAGE`、`:181` 未知阶段静默过滤并回落 cet4/cet6；`screen.py:44`、`batches.py:272,698` 的 `int(x or DEFAULT_CURRENT_STAGE)` | ✓（文件在 `services/`，不是 `routers/`/`ai/`；行号准确） |
| 5 | 三者 | `services/ecdict.py:28 STAGE_TAGS`、`:118-119 stages`、`:177 stage_min` 公式；`services/words.py:39/69-91/143-151/183-189/576-597`、`:228 stages_of` | ✓ |
| 6 | 三者 | `main.py:307-319 seed_check`、`:482-485` 先迁移后 `seed_check`；`install.sh:140-141`；`backup.py:283-292` | ✓ |
| 7 | 三者 | `0001_init.sql:148/185/205/219-225`、`:186` 的「3,694」注释、`:215` 的「388」注释 | ✓ |
| 8 | 三者 | `test_seed.py:61,86,93-98,113,197/204,229-238,291-298,338-353`；`test_screen.py:129-134`；`test_vocab.py:69-70,75-76,111,232-234`；`test_content_apply.py:255`；`test_api_schemas.py:33-39`；`test_cli.py:51-58`；`conftest.py:203-209`；`test_words_resolve.py:478`；`test_reports.py:86-87`；`smoke.py:352,614` | ✓ |
| 9 | purist | `WelcomePage.tsx:35` 高中生预设 `['zk','gk']` | 偏差一行：预设在 `:36`（`ROLE_PRESETS` :34-39）。无碍 |
| 10 | 三者 | `VocabPage.tsx:29,202`、`ScreenPage.tsx:31`、`zh.ts:86`、`FRONTEND.md:292`（continuity）、`types.ts:5,73`、`StageChips.tsx` | ✓ |
| 11 | data-eng | 「`jsonschema` 已是运行依赖：`backend/requirements.txt:9`」 | ✓ `jsonschema>=4.18,<5` 在第 9 行（我的记忆里「仅 dev 依赖」已过时） |
| 12 | data-eng | `cli.py:31-42 CLI_MODULES`、`:45-56 COMMAND_OWNERS`、`pyproject.toml:26-28` package-data、`test_seed.py:86`「`I` 故意不在夹具」、`:348` `14000 ≤ forms ≤ 14300`、`words.py:174-175` 点号 token ≤ 6 | ✓ |
| 13 | 三者 | `API.md:167`「4 rows」/`:169` 3,694；`DESIGN.md:186`「cumulative as in the sources」/`:209` 验收数；`TASKS.md:162`「keep verbatim」/`:172-175`；`check_contract.py:274-281` 顺序敏感比对；`Makefile:93-98`；`pack_seed.sh:44-47,62,68,79,90`（`zcat`）、`:63,84,90`（`sha256sum`）、`:90`（`stat -c`） | ✓ |
| 14 | 三者 | INDEX/facts：`verify list-sources-7` 与「遗漏 3」（7 行被 `RICH_RE` 丢）、`verify shanghai-secondary O5/O6/O8`、`stage-model-15/19/20`、`frontend-stages-12/15/16/22/23`、`verify provinces-24` | ✓ 内容与引用一致 |
| 15 | 三者 | 线上副本：`user_settings` = `(1, ["zk","gk","cet4","cet6"], 3)`、`(2, ["zk"], 1)`；`user_words` 67 + 10 = 77；内容/`difficulty`/`content_state=ready` 各 49；`an` `0|1|0|1|2`、`best` 3、`less` 2、`cafe` 3 | ✓ |
| 16 | purist | 「`is/are/am/does` 变成无阶段」 | **部分错**：`am` 带 `stage_cet6=1`（`1|1|0|1|1`），只会降到 cet6 层；`is`（`gk zk`）、`are`（gk）、`does`（gk）确实变无阶段 |
| 17 | continuity | `hot-dog → hotdog`（N10、§3.3 表 variants） | **属实但有害**：`hotdog` 的 ECDICT 释义是「v. 卖弄」（线上实查），见 §3.3 |
| 18 | continuity | 夹具计数 zk 35 / gk 52 / cet4 45 / cet6 24；first 35/19/3/3 | ✓ 精确 |
| 19 | purist | 夹具里 24 个 L2 词（故意不加 `an`）、`is` 在夹具、`color` 不在夹具 | ✓（夹具实际含 25 个 L2 词，`an` 即被排除的那个） |
| 20 | 三者 | `data/lists/` 实际文件：L2 505 ✓、L3 1600 ✓、`shmeea-2020-junior.txt` 1,724 行（拆并列后 ≈1,731）、`shmeea-2020-junior-phrases.txt` **342** 行（三份设计写 331——INDEX 矛盾 1 给的是 331–342 区间，data-eng 的 342 与文件一致）、HS2020 3,000 ✓、HS2025 3,099 ✓、附表 267 行（含 106 个不规则动词，`be (am, is, are)` 在其中） | 词组计数需在最终 manifest 用 `expect` 锁定 |
| 21 | continuity | 「前 50/100/300/600/1000 个候选里拓展词 0/0/0/5/30」 | ✓ 我复算 0/0/0/6/31（把附表词当官方词），第一个拓展词 `policy` 排第 350 |
| 22 | purist | zk −415（188 → 高中 / 155 → CET / 72 → 无）；gk −1,055；xs 578 现有行 = 旧 `stage_min` 569/6/2/1；无阶段 243（word 204 / phrase 6 / abbr 8 / proper 25） | ✓ 我得 412（189/153/70）、1,054、578（569/6/2/1 完全一致）、241（202/6/8/25） |
| 23 | data-eng | 无阶段 249、`xs` 504 在库 + `excited`、`missGK` 含未拆并列 `a/an`、`actor/actress` | ✓ 与其 `preview_out.json` 一致；249 与我 241 的差是附表/变体口径 |

**没有一条引用被推翻**；两处实质性数字问题是 purist 的 `am`（#16）与 continuity 的 `hotdog`（#17），以及三者沿用 INDEX 的「331 词组」与交付文件 342 的差（#20）。

---

## 2. 学习者与产品视角的共同判断（三份设计都要面对）

### 2.1 上海小学生（1–5 年级）会看到什么

- 三份设计的 `xs` 都以国家二级 505 为骨架，并都把数词/月份/星期并入（purist 594、continuity ≈570、data-eng 505+附表）。这是对的：`Monday`、`ten` 不进小学层说不过去（INDEX B2 体例说明）。
- **但三份设计都没有回答「小学页签按什么顺序给孩子看」。** 词库页默认 `sort=freq`，筛词/推荐按阶段距离 → `frq`（`screen.py:34-36`、`batches.py:60-61`）。我按 `frq` 排 xs 在库词，前 30 个是 `the, be, and, of, a, in, to, have, it, I, that, for, you, he, with, on, do, say, this, they, at, but, we, his, from, not, by, she, or, what`——**全是功能词**。一个主攻小学的用户，引导页「花两分钟筛一筛」的 30 个词会是「the / be / and / of…」，推荐词也从这里开始。D1 的核心证据（具体性是最强预测量、儿童从图学词优于从词学词）恰恰说明小学层应先给具体名词。这是三份设计共同的欠设计（见 §5 嫁接 4b）。
- `is / are`：官方表只列 `be (am, is, are)`，purist 与 data-eng 都不让括注产生成员 → `is`（今天 zk+gk）、`are`、`does` 变无阶段词典词（我复算确认，`am` 因有 cet6 标签留在 cet6 层）。小学/初中页签里没有 `is`、`are`，搜索能命中但 `COALESCE(difficulty, stage_min, 5)` 把它们排成「最难」。purist 把它列为风险并「不建议」补救；从学习者角度我不同意——这几个词是一年级教材前十课的词。continuity 保留旧 zk（`is` 仍在初中层但不在小学层，也别扭）。嫁接 4a 给出零成本修法。
- 五四学制：上海一年级开英语，牛津上海版 1A–5B 约 772–825 词（INDEX B3），所以 505 对上海五年级偏小、1,600–2,500 的初中层对预备班（六年级）偏大；三份设计都按 A1 把教材拓展推后，只有 purist 显式预留了 `member: false` 的词表位。不算缺陷，但拍板时要知道「小学」页签对上海孩子是下限而不是全集。

### 2.2 上海初中生（6–9 年级）

- 三份都把考试院 2020 表并入 zk，覆盖问题解决（INDEX B4/B5）。差别在「还带什么」：
  - purist zk 2,194 = L3 ∪ SH ∪ 附表 ∪ 变体，**无词组**；其中 ≈277 个只在国家表不在上海表（我复算；按 `frq` 前 300 里 12 个）。
  - data-eng zk ≈ 2,000 + 附表 + **331 词组**（含 32 个 `translation NULL` 的空卡）+ 闭包不影响 zk。
  - continuity zk 2,520 + **272 词组**（只收有 ECDICT 释义的），412 个旧表词留在层内（16.2% 扣除体例差异后），但它们都在 `frq` 尾部：前 300 个推荐词里 0 个，第一个（`policy`）排第 350，按每天 15 个推荐词约第 24 天才会碰到——这个「代价很小」的论证我复算成立。
- **词组是上海中考的正式考点**（词汇表第二部分），purist 推迟到第二版，对上海初中生是真实缺口；data-eng/continuity 收录但 `frq` 为空 → 排在全部单词之后、在「仅本阶段新增」里却计数。学习卡/配图流程对词组只在 13 个 phrase 上验证过（INDEX D2/D6）。折中见嫁接 4c。
- 屈折形容词 `excited / lost / frozen / united…`：上海表把它们列为词头（考的就是形容词义）。purist/data-eng 建独立行（ECDICT 有独立条目），continuity N5 把它们落回原形（`lost → lose`），学习者查 `lost` 得到「失去」的动词卡——continuity 自己也承认是损失。学习者角度 purist/data-eng 正确。
- 派生副词 `angrily / carefully / quietly…`（上海独有，国家表按说明 10 不列）：三份都建行，一致。

### 2.3 上海高中生

- 现行依据是国家 3000/3100 + 考试院 200 词（无机读，INDEX B7），三份都只能做前者，一致。
- purist gk 3,253（HS3100 ∪ HS3000，不闭包）：`abolish / abortion / absurd…` 764 个旧「高考 3500」词降到 CET 层，`abortion` 这类词不再出现在 K-12 用户的筛词与推荐里——对未成年人内容安全（INDEX D6 指出控制很薄）是一个顺带的正收益。198–222 个「上海初中有、高中表无」的词保留 `zk=1, gk=0`，高中生预设 `['zk','gk']` 仍能看到；只选 `['gk']` 的用户会漏掉（罕见）。
- data-eng 闭包 `gk ⊇ zk`：只选 gk 的用户池完整，但「高中」页签 total 与官方 3100 脱钩（≈3,360+）。对学习者中性，对「页签数字 = 官方词量」的直觉有损。
- continuity gk 4,297，24.2% 为旧表词。其 `frq` 前列的「超纲」gk 词（`federal, simply, organization, media, growth, physical, analysis…`）其实是高频四级词，高中生背了不亏；真正无家可归的是 227 个既无官方也无 CET 归属的词（`abortion, bungalow, yummy`），它们会一直留在高中池里。

### 2.4 两位现有用户

- 用户 1（四阶段、主攻 cet4）：三种方案下候选池都不变（四阶段并集）；≈300–370 个词的 `stage_min` 从 cet4 下移，推荐顺序变化方向合理（`issue, guy, economic…` 本就是高中词）。
- 用户 2（只选 zk、主攻 zk）：10 个生词 `a, and, be, have, I, in, it, of, the, to` 全部变成小学词；按重编号或 xs=0 都是「距离 2」，推荐词会先给纯初中词——对初中生是正确方向，发布说明写一句即可。**他们持有的词没有一个离开 zk**（我复算 `leave_zk ∩ user_words = ∅`，内容词同样为空）。
- 因此 continuity 的核心价值主张「线上任何一个词都不失去它今天拥有的阶段」在真实数据上没有受益人；它保护的是 2,099 个 zk 词里 412 个没人学过的旧表词。

### 2.5 D1 与本线的关系

D1（图优效应在儿童更弱更晚、具体性最强、无关细节伤害儿童）不直接评判词表设计，但它推出一个本线能做的事：**小学层的「首批词」应优先具体名词**（apple / cat / book）而不是 `frq` 前列的功能词。三份设计都没有在种子里留一个可用于此的键（purist 的 `hs_level` 只服务高中星级；data-eng 的 `list_levels` 同）。Lancaster 常模（CC BY 4.0，INDEX D5）或 ECDICT `pos` 都能零成本给出这个键。

### 2.6 页签与 chips（前端线的事，但词表决定它的难度）

- 6 个 tab 在 375px 溢出 ≈13px（frontend-stages-16）；小学词因国家表累计（L2 ⊂ L3 ⊂ HS3100）天然带 ≥3 个 chip，加上 cet 常满 5 个（frontend-stages-15 核验：换行风险真实但非常态）。三份设计对此都正确地不发表意见；但 data-eng 的闭包会让 ≈150 个上海初中词也多一个「高中」chip——影响很小。
- `WelcomePage` 角色只有 zk/gk/uni/pro（`:33-39`），没有「小学生」；三份都归到前端/阶段模型线。

---

## 3. 逐份评审

### 3.1 official-purist（fit 8 · correctness 7 · effort_risk 6 · maintainability 7 · evidence 9 · rollout 6 → 7.3）

**好在哪里**

- 阶段口径与现行课标/考试院文件一字一句对得上（INDEX C1/C2/B4/C4、Q8-a），不做人为闭包的理由站得住（国家表自身累计，实测 XS ⊆ ZK；`zk \ gk` 只剩上海独有词与附录项）。
- 数字最可复现：§3.6 的每一张表我都能用独立脚本逼近（§1 #22）。`stage_min` 转移矩阵、`sources` 全量改写（9,162 行都会 UPDATE）、卡片 LRU 失效一次等副作用都写明了。
- 对现库缺陷的修复完整（`RICH_RE` 全角括号、`a (an)`、单字母白名单），并把「官方词缺失即构建失败」「`DIFF.md` 不变量检查 exit 1」做成门禁。
- 变体继承（`colour→color`、`maths→math`）让 57 个美式拼写行拿到与英式相同的阶段——美式拼写学习者不会在「仅本阶段新增」里漏掉它们。
- `overrides.jsonl` 把 `bund / mum / PE / bce / ce` 的 ECDICT 错义项全部点名；`Mr→Mr.` 方向正确（无点 `Mr` 是「存储器回收程序」）。
- 对阶段模型线的 4 条接口要求（含 `ecdict.py:28 STAGE_TAGS` 必须改成只认 cet，否则自添词会拿到废除的初中/高中标记）是三份里最清楚的。

**致命/必须修的缺陷**

1. **依赖重编号 1..5 却只字不提 `difficulty` 尺子（Q5/INDEX A5）。** `vocab.py:78 COALESCE(difficulty, stage_min, 5)` 把两把尺子当一把：重编号后 49 行 `difficulty=1`（提示词里的「初中」）与 `stage_min=1`（小学）并列，`content_system.txt:11` 的「1 = 初中」与 DB 的「1 = 小学」错位。不会报错，但是悄悄的语义漂移，而且会随每一次新内容生成扩大（`content.py:230-234` 只在 `difficulty IS NULL` 时写）。0011 必须同时决定：49 行 +1 并扩到 6 级，或清空让夜间整理重算，或共用 1（Q5-a）并在提示词里改尺子说明。
2. **`is / are / does` 变成无阶段词**（§2.1）。设计承认并拒绝补救。对以小学为目标的产品这是可见退步；修法零成本（嫁接 4a）。
3. 词组整体推迟（§2.2）——对上海初中生是功能缺口，且设计里没有给「第二版」任何时间点。

**非致命问题**

- `am` 不会变无阶段（有 cet6 标签），§3.3 规则 2 与 §3.6.5 的表述需改。
- `manifest.stage_order` 是第 11 份阶段常量；`seed.py:208` 仍用元组位置。应直接采用 data-eng 的 `min(stage_to_index)`。
- 附表计数与文件不一致（A_geo 46 vs 文件 27+18=45，A_cult 35 vs 13+8+11=32）；不影响方向。
- 序数词 `thirteenth…ninetieth, hundredth` 作为小学新词（14 个，`frq` 为空）价值很低，且会进入「仅本阶段新增」计数；建议 `member: true` 但进 `frq` 尾部即可，或留给附表 `group` 开关。
- 8 人日估计里没有排练发现 OCR 错词后的二次迭代；`parse_official` 只校验行数，不校验词。
- 重编号会让 `push_batches.settings_json` 里的历史快照 `"current_stage": 3` 变成陈旧值（线上 4 行）；`batches.py:680` 用的是实时 `user_settings_row`，所以只是历史记录失真，发布说明写一句。

### 3.2 continuity（fit 5 · correctness 5 · effort_risk 7 · maintainability 5 · evidence 7 · rollout 7 → 5.9）

**好在哪里**

- 把「超纲比例」量化并扣除体例差异（16.2%/24.2%），且证明旧表词集中在 `frq` 尾部（我复算成立）——这是三份里唯一从「学生按什么顺序遇到词」出发的论证。
- `seed_diff --db` 列出「会被覆盖的非阶段列」与「违反单调的词」，`plan()` 把导入变成可预演的计划；`--allow-regress` 给了回退种子的显式路径。
- 变体「两者都在库则同标」（N2）、多词词头禁止去空格匹配（N8 发现 `break down → breakdown` 5 个假阳性）、`pack_seed.py` 用 Python gzip `mtime=0` 解决 Mac/GNU 字节差（seed-pipeline-7/8）、夹具最小改动原则、provenance 表的列定义——都值得搬走。
- 对两位用户的设置行「无操作」是正确判断（`xs ⊆ zk`）。

**致命缺陷**

1. **`hot-dog → hotdog`（N10、§3.3 variants 表、`extra_output.txt`）给上海中考词挂错释义。** 线上 `hotdog` 的 ECDICT 释义是「v. 卖弄」，`hot dog`（「n. <口>热狗」）不在库。按此设计，上海初中生在初中页签看到的「hot-dog」是一张「卖弄」卡。purist（规则 9）与 data-eng（R10）都识别并别名到 `hot dog`。
2. **`mum` 未进 overrides。** N2 让 `mother (mum AmE mom)` 的 `mum/mom` 拿到 xs，而线上 `mum` 释义是「n. 菊花, 沉默 / a. 沉默的 / vi. 演哑剧」；N11 的覆盖清单只有 AI/bund/BCE/CE/UK。小学页签里会出现「mum = 菊花」。
3. **单调守卫与启动期自动导入冲突，未定义行为。** `main.seed_check`（`main.py:307-319`）在每次 `wd serve` 启动时无条件 `import_seed`；设计让 `import_seed` 默认 `guard="monotonic"` 并在违例时抛 `SeedGuardError`，却没有说 `seed_check` 怎么办。一旦某版种子合法地收回一个错标（例如 ECDICT 把 `hotdog` 标成 zk），服务启动失败 → launchd 重启循环（WORD_LIBRARY_CURATION §1.2 已指出 `seed_check` 对坏种子零防御）。
4. **「可以分步上线」（§1 第 5 点）与 `kv.seed_version` 机制矛盾。** 若新种子先于新代码部署，旧代码导入后 `kv.seed_version` 已是新文件哈希；升级并跑完 0011 后 `seed_check` 认为「up to date」，`stage_xs` 全库为 0，除非有人记得 `--force`。设计未提；§6 运行手册碰巧避开了。
5. **以 xs = 0 为默认秩**（I2），直接踩进 INDEX 矛盾 #14 核验过的结论：0 值在 `screen.py:44`、`batches.py:272,698` 被当作缺失 → 主攻小学的用户（新目标用户）推荐词按 cet4 排；设计把修复推给阶段模型线，但自己全部数字与不变量都建立在这个假设上，且没有量化若改重编号要改多少。
6. **核心前提在数据上为空**（§2.4）：没有任何现有用户或内容词会因重标受损，而代价是 K-12 用户永久背 412 + 1,042 个旧表词，并把 `abortion` 等词留在高中池。这不是 bug，但让「连续性」失去了存在理由。

**非致命问题**

- N5 把 `lost/frozen/united/according` 落回原形，丢掉上海表要考的形容词/介词义（已承认）。
- 永久依赖 mahavivo 两张来源不明的表作为成员来源（A3 说「不再作为阶段依据」，设计把它改读为「不作官方依据但保留成员」——偏离已声明，但也意味着 `WORDLISTS_DIR` 永远不能瘦身）。
- `sources` 保留 `zk/gk` 记号表示 mahavivo 表，同时新增 `l3/sh2020`——一个列里两套语义的记号，以后读它的人要查文档。
- 第二期 `core_min` 列 + 「拓展」chip 是又一次契约变更（`API.md §9`、`types.ts`、`schemas.py`）。

### 3.3 data-engineering（fit 7 · correctness 7 · effort_risk 4 · maintainability 8 · evidence 7 · rollout 7 → 6.7）

**好在哪里**

- **与 Q1 解耦**：种子只写阶段码，`stage_min = min(stage_to_index)`，删掉 `seed.py:43 STAGES`（10 份常量去 1），Q1 三个选项都只改 `schemas`。这是三份里唯一让种子线不被拍板阻塞的设计。
- manifest 带 `expect ± tolerance` 与 sha256：上游文件变了会显式失败而不是悄悄改种子；`lists.py` 对词头列出现 CJK 直接报错——「只取词头」的许可姿态有了机械保证。
- 内容哈希取代 `.gz` 哈希做 `kv.seed_version`，顺手解决 Mac 重打包伪重导（seed-pipeline-7）；升级后首启多一次导入已写明。
- `retain` 把「词从种子消失 → 旧旗标永久残留」这个真正的洞堵上；dry-run 报告含「孤儿行」。
- `kind` 覆盖修 `I`（proper_noun）与 `E-MAIL`（display），`aliases → word_forms(alt)` 让搜索 `mr`、`hot-dog` 命中规范词头——对学习者是实打实的体验改善。
- 独立核实了 ECDICT release 的 tag 全集与 `ecdict_id` 稳定（关掉 INDEX 未解决 6 的一半），并给出「用旧 manifest 重建出现种子 `content_sha256`」这个最好的回归验收。

**致命/必须修的缺陷**

1. **D9 与 `--strict` 自相矛盾。** 步骤 6 规定每表缺失上限默认 0.5%，D9/R9 又说 342 个词组里 32 个（9.4%）无 ECDICT 释义并以 `translation = NULL` 入库 → 严格模式下词组表必然构建失败，除非 per-list 放宽；文中没写。而且 32 张 `translation NULL` 的词组卡对初中生就是空卡（「UI 显示空短译」），continuity 明确拒绝生成这类最小记录是对的。
2. **预览数字不含自己的决定。** §1.2 的「初中层 2,099 → ≈1,987」「`stage_min` NULL 249」是 S ∪ L3 的裸数字，不含 D1 的附表、R8 的专名、D9 的 331 词组、A2 偏离 1 的闭包；按其最终定义 zk ≈ 2,000 + 附表 ≈150 + 词组 331 ≈ 2,500。拍板者若按 §1.2 理解「初中变小了」会被误导。
3. **工作量 14 人日（12–16）用在一个一年改两次、线上 2 个用户的 9k 词种子上**，是三份里唯一让我担心「过度设计」的：7 个模块 + 5 个新测试文件 + v2 夹具 + `kind` 契约放宽 + CLI 注册 + 哈希语义切换。其中真正有杠杆的是 §3.6 的 4 处 `seed.py` 改动、manifest 校验与 diff；12 条规则写成单文件表驱动函数即可。

**非致命问题**

- 闭包 `gk ⊇ zk` 偏离 A2（已说明）；让「高中」total 与官方 3100 脱钩；对学习者中性。
- `is/are/does` 无阶段（`irregular_verb` 组被排除）——与 purist 同样的小学页签退步，且未列入风险。
- `aliases` 写入的 `alt` 行永不被重导清理（已承认）：别名改错只能手工删。
- `kind` 可由种子覆盖 → DESIGN §3.2「kind 派生」契约放宽（已承认，需同步 `DESIGN.md:206`）。
- `|zk − gk| = 152` 与 purist 198 的差来自附表口径，两者都对，但阅读者需要知道。

---

## 4. 我的复算（只读，`check.py`）

### 4.1 对现有数据的影响（三份设计的共同主张，全部成立）

| 项 | 结果 |
|---|---|
| 现 zk 词不在 L3 ∪ SH ∪ 附表 | 412（→ 仅高中 189 / 仅 CET 153 / 无阶段 70）；purist 415（188/155/72） |
| 现 gk 词不在 HS2025 ∪ HS2020 | 1,054（闭包后 962）；purist 1,055 |
| 失去全部阶段 | 241（word 202 / phrase 6 / abbr 8 / proper 25）；含 `is, are, does`；purist 243、data-eng 249 |
| 以上三组 ∩ `user_words`（两位用户） | **∅** |
| 以上三组 ∩ 有 AI 内容的 49 词 | **∅** |
| 用户 2 的 10 个生词 | `a, and, be, have, I, in, it, of, the, to`——全部进入 xs，全部仍在新 zk |
| xs 成员 | 596（含附表数词/月份/星期）；在库 578，旧 `stage_min` 569/6/2/1；缺 13 个序数词 + `excited` + `physical education`（+ `has` 为我的解析噪声） |
| 新 zk 在库但今天无 zk 旗标 | 415（旧 `stage_min` 2:321 / 3:70 / 4:24）；purist 416 |
| `zk_new − gk_new` | 222（purist 198；差为附表/数词口径） |

### 4.2 continuity 的「拓展词在尾部」

zk 层（旧 ∪ 新）2,514 词，拓展词 412；按 `frq` 排序，前 50/100/300/600/1000 里拓展词 0/0/0/6/31，首个 `policy` 排第 350；不在上海表的词 4/6/12/31/90。与设计所称 0/0/0/5/30 一致。

### 4.3 小学层的排序现实

xs 在库 578 词按 `frq`：前 30 个全是功能词（§2.1）；26 个无 `frq`（序数词、多词项）排尾。

### 4.4 释义核查（线上 ECDICT 字段）

`hotdog`「v. 卖弄」；`mum`「n. 菊花, 沉默」；`p.e.`「n. 排字错误；体育(课)」（首行即 `translation_short`，含「体育」尚可）；`mr.`「阁下, 先生」；`am` display `AM`、「be的单数第一人称」。

---

## 5. 嫁接到最终方案的建议

1. **主干取 official-purist**：集合代数（不闭包、附表按 `group` 分配、变体继承、`overrides.jsonl` + `aliases.tsv`、`hs_level`）、`DIFF.md` 不变量检查（exit 1）、`--dry-run`、对阶段模型线的 4 条接口要求（尤其 `ecdict.py:28 STAGE_TAGS → ("cet4","cet6")`）。
2. **从 data-engineering 搬机制**：`stage_min = min(stage_to_index)` 并删 `seed.py:43 STAGES`；manifest 的 `expect ± tolerance` + sha256 + `enabled`；`lists.py` 词头列 CJK 报错；`kv.seed_version` 改内容哈希（含 `test_seed.py:234` 语义反转与 `main.seed_check` 同步）；`--dry-run --report` 含孤儿行；`kind` 覆盖仅限 `I`/`E-MAIL`/词组；`aliases → word_forms(alt)`。把 12 条规则写成**一个**表驱动模块 + 一个测试文件，不建 7 文件包；工作量压回 9–10 人日。
3. **从 continuity 搬报告与防线**：`seed_diff --db` 的「违反单调的词」清单——作为**醒目告警**而非拒绝；`resolution` 统计；多词词头禁止去空格；`pack_seed.py`（Python gzip `mtime=0`）；夹具最小改动原则；provenance 表列定义。**不搬**加法口径、xs=0 假设、`hot-dog→hotdog`、N5 落回原形。
4. **三份都缺、必须补的四件事**
   - 4a. be/have/do 的屈折形 `is / are / am / was / were / has / does / did` 通过 `aliases.tsv` 新 `kind: inflect` 规则**继承原形的阶段**（它们已是独立行，不需要新建），让小学/初中页签有 `is`、`are`；附表 `不规则动词` 组可作为这条规则的输入源。
   - 4b. 小学层的首批词不能只按 `frq`：在种子 v2 加一个 xs 专用排序键（优先级：ECDICT `pos` 为 art/prep/pron/conj/aux/modal 的词后置；可选 Lancaster 具体性，CC BY 4.0），并让 `screen`/推荐对 `current_stage = xs` 的用户用它作次级键。这是 D1 证据在本线唯一可落地的地方。
   - 4c. 上海词组首版即入库，但只收有 ECDICT 释义者（≈272–310），`kind='phrase'`、`frq` 为空排尾、`sb./sth.` 模板跳过；`manifest.expect` 按交付文件锁 **342** 而不是 331。
   - 4d. `main.seed_check` 对导入异常改为 warn-and-continue（无论最终是否采用守卫），并在 0011 发布说明里写清：`difficulty` 49 行的处置（Q5）、`push_batches.settings_json` 历史快照为旧编号、`bank.py:181` 在回滚代码时会把 `["xs"]` 用户静默回落到 cet4/cet6（只能库与代码一起回）。
5. **口径提醒**：`xs = 505(+附表)` 对上海五年级是下限；保留 purist 的 `member: false` 教材词表位，并让前端「小学生」预设为 `['xs','zk']`、主攻 xs，使上海预备班（六年级）用户不至于在两个页签间无所适从。

---

## 6. 评分依据摘要

| 维度 | official-purist | continuity | data-engineering |
|---|---|---|---|
| fit | 口径 = 现行课标 + 考试院；移出旧 3500 词；缺词组、`is/are` 退步 → 8 | 前提无受益人；K-12 背 16–24% 旧词；`hot-dog`/`mum` 错卡；词组 272 是加分 → 5 | 口径同 purist；词组含 32 空卡；闭包中性；`mr`/`I`/`E-MAIL` 修复加分 → 7 |
| correctness | 数字可复现；`am` 小错；Q5 未处理 → 7 | 两处错释义、守卫撞启动、分步上线陷阱、xs=0 陷阱 → 5 | 内部矛盾（strict vs 32 缺失）、预览不含自身决定；其余严谨 → 7 |
| effort_risk | 8 人日，一次性重标 2,603 词，有 DIFF/dry-run 兜底 → 6 | 7 人日，加法，但守卫与双口径增加复杂度 → 7 | 14 人日，7 模块 + 契约放宽 → 4 |
| maintainability | manifest 驱动，但第 11 份常量、单文件脚本 → 7 | 两套口径永久混在一列，永久依赖 legacy 文件，`core_min` 二期 → 5 | 去 1 份常量、与 Q1 解耦、校验可测 → 8 |
| evidence | 引用准确、复算一致、小计数差 → 9 | 复算一致，但「可感知退步」无证据 → 7 | 引用准确、新核实两条，预览口径误导 → 7 |
| rollout | 停机一次、快照回滚、dry-run → 6 | 加法 + `--allow-regress`，xs=0 仍需重建表，守卫行为未定 → 7 | 种子级回滚、内容哈希首启重导已写明，依赖 Q1 → 7 |
