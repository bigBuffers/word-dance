# 词表来源与种子流水线 · 综合设计（SYNTHESIS）

日期 2026-11-06 · 基线 `main @ 75df534`（所有 `path:line` 按此提交重新打开核对）· 线上库只读副本 `scratchpad/live-copy.db`（9,162 词、2 用户、77 条 `user_words`、49 条内容、31 张图）· 词表文件 = `data/lists/` 已交付的 11 个文件（未跟踪，2026-11-06 00:21 状态）。

输入：`official-purist.md`、`continuity.md`、`data-engineering.md` 三份设计与 `judge-data-safety.md`、`judge-learner-product.md`、`judge-maintainer.md` 三份评审；`INDEX.md`、`facts/`、`verify/`、`data/lists/*.README.md`、`docs/WORD_LIBRARY_CURATION.md`。

**本文件的数字全部来自一次新的复算**：`scratchpad/word-lists-synthesis/recount.py`（`/opt/homebrew/bin/python3.12 -I`，只读打开 `live-copy.db`、`scratchpad/ecdict-dl/extract/stardict.db`（ECDICT 1.0.28，851,288,064 B）与 `data/lists/` 交付文件，按 §3.3 的文法逐行解析），输出 `recount.out.txt` / `recount.json`。三份设计的数字都来自 verify 阶段的中间解析件而不是交付文件（judge-maintainer §1.2、judge-data-safety §1.3-8），所以凡与它们不同处以本文为准，差异原因在 §3.6 注明。下文「[复算]」即指这次输出。

`scratchpad/` = `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/`。

---

## 1. 一页结论

**骨架与嫁接。** 三份评审的排名互不一致（data-safety：data-engineering > official-purist > continuity；learner-product、maintainer：official-purist > data-engineering > continuity），但对「最终方案该长什么样」的描述一致：**official-purist 的集合代数与不变量 + data-engineering 的工程骨架（retain、内容哈希、manifest 校验、dry-run、构建期 lemma 一致性）+ continuity 的运维安全阀（守卫只报告、`sources` 令牌不整体改名、多词词头禁止去空格匹配）**，再补上三份共同缺失的四件事：`main.seed_check` 对导入异常的防御、按**交付文件**重写的括注/并列文法、`is/are/am/does` 的阶段继承、`difficulty` 尺子与阶段编号在同一提交决定。本文就是这个合并体，并把三位评审没有做的事做了：用交付文件把全部数字重算了一遍。

**决定了什么（细节见 §2）**

1. 阶段成员只由官方词头决定：`xs = 国家 2022 二级 ∪ 附表数词/月份/星期`；`zk = 国家三级 ∪ 附表专名 ∪ 上海市教育考试院 2020 单词表 ∪ 上海附表 ∪ 上海词组（仅 ECDICT 有条目者）`；`gk = 高中课标 2025 修订 3100 ∪ 2020 版 3000`；`cet4/cet6` 不变。不做人为闭包（`zk ⊄ gk` 真实存在：212 个单词 + 333 个词组），`xs ⊆ zk` 由课标构造保证（[复算] 成立）。ECDICT 的 `zk/gk` 标签与 mahavivo 中考/Highschool 两张表退出成员判定。
2. 文法按交付文件写进构建器（§3.3）：`x/y`、`x=y` 拆分；`(=X)`、`(AmE X)`、`(X)` 变体成为**同阶段的独立行**；`(pl. …)`、`(am, is, are)`、`(has)` 不产生成员；`Mr→mr.`、`PE→p.e.`、`hot-dog→hot dog`、`humourous→humorous` 走 `aliases.tsv`；`be/have/do` 的人称形式若已是库内独立词条则**继承原形阶段**（只影响 `is/are/am/does` 4 行）。
3. 词的宇宙单调（retain）：上一版种子的每个 lemma 都留在新种子里，只重标不消失；掉出所有官方表的 238 个词成为无阶段词典词（`stage_min NULL`，0 个被用户持有、0 个有内容或配图 [复算]）。不删词、不加「拓展」阶段、不做「上海/全国」维度；信息用 `sources` 令牌保留（`legacy:zk/gk`、`moe22:l2/l3/app`、`shmeea20[:app|:phr]`、`hs20`、`hs25:0|1|2`、`inherit:be|do`）。
4. 构建器进包 `backend/wd/seedbuild/`（`normalise.py`、`build.py`、`diff.py` 三个模块），`scripts/build_seed.py` / `scripts/seed_diff.py` 作为入口；**词典字段从上一版种子逐字复制**，只有新词头（455 行）才查 ECDICT；mahavivo CET 四表变成可选输入。构建两次字节相同；`stats.json` 带 `content_sha256`；`data/seed/DIFF.md` 随种子提交。
5. 导入器：`kv.seed_version` 改为解压后内容的 sha256；`seed.py` 的 `STAGES` 删除、`SEED_COLUMNS` 由 `schemas.STAGE_ORDER` 生成、`stage_min = min(stage_to_index)`（与 Q1 编码解耦）；新增 `--dry-run [--report]`（插入/更新/孤儿/旗标增减/`stage_min` 升降矩阵，零写入）；未知阶段码计数告警而不是静默丢弃；别名写入 `word_forms(kind='alias')`（新迁移 `0012`）；`main.seed_check` 捕获导入异常并记 `system_events('seed_import_failed')` 后继续启动。
6. 运行时一致性：`services/ecdict.py` 对用户自添词只按 `cet4/cet6` 标签赋阶段，`has_stage_tag` 仍按四个标签判定（保住 `words.py:669,673` 的回指逻辑）。

**代价多少（[复算]，线上 9,162 → 9,617 行）**

| | 旧 | 新 | 说明 |
|---|---|---|---|
| `stage_xs` | — | 600 | 580 个现有行（旧 `stage_min` 1:571 / 2:6 / 3:2 / 4:1）+ 16 个新行（14 个序数词、`excited`、`physical education`）+ `is/are/am/does` 继承 |
| `stage_zk` | 2,099 | 2,548 | +858（418 现有行重标 + 440 新行，其中 332 个词组）；−409（188 → 仅高中、152 → 仅 CET、69 → 无阶段） |
| `stage_gk` | 3,829 | 3,260 | +479（450 + 29）；−1,048（78 仍在初中、760 → 仅 CET、210 → 无阶段）——正是旧「高考 3500」谱系词（INDEX A1/C2） |
| `stage_cet4 / cet6` | 4,722 / 7,671 | 不变 | 现有行的 CET 旗标逐字保留 |
| `stage_min`（新编号 1..5） | 2,099 / 1,792 / 1,577 / 3,694 | 600 / 1,948 / 1,255 / 1,726 / 3,850 / NULL 238 | 「仅本阶段新增」数字随之变化；`API.md:169` 的 3,694 → 3,850 |
| 导入写入 | — | 4,357 行 UPDATE + 455 行 INSERT；4,805 行不动 | 2,601 行旗标集合变化，1,756 行只有 `sources` 变化 |
| 两位用户 | — | 77 个生词中 65 个阶段集合变化，**0 个失去阶段**；49 个内容词 37 个变化，0 个失去阶段 | 用户 2 的 10 个生词全部多出「小学」 |

**工作量（本线）：≈ 12.5 人日（11–14）**，不含 0011 迁移、10 份阶段常量、前端页签（阶段模型线）与配图线；低于 10 的估算被三位评审质疑过，本文不重复那个错误（§7.3）。

---

## 2. 逐条决定

每条：决定 → 理由 → 依据 → 被否决的替代及原因。

**D-word-lists-1 成员定义 = 官方词头的集合代数，不闭包。**
决定：§3.1 的公式；`gk` 显式写成 `HS3100 ∪ HS3000`；不做 `gk := gk ∪ zk`。
理由：国家表自身累计（三级「含二级 505 个」、高中表「含义务教育阶段 1600 个」），实测 `xs ⊆ zk` 成立；2025 修订版把 94 个月份/数词/国籍词移出主表，显式并集才不丢它们；闭包会让「高中」页签 `total` 脱离官方 3100 并把 333 个上海初中词组塞进高中层（data-engineering 自己没提这一点，judge-data-safety §2.3 指出）。
依据：`data/lists/moe-senior.README.md §3`（说明第 1 条原文）、`moe-2022.README.md §4.3`（带 `*` 的 505 条与二级表逐字相同）、[复算] `XS ⊆ ZK: True`、`ZK − GK = 212`、`H20-only = 94`；official-purist §3.1.3；judge-maintainer §5.1。
否决：data-engineering D1 的 `gk ⊇ zk` 闭包（偏离 A2、页签数字失真）；continuity 的 `Z₀ ∪ …` 加法口径（judge-learner-product §2.4：在真实数据上没有受益人，却把 16–24% 旧考纲词留给 K-12，并把 `hot-dog=卖弄`、`mum=菊花` 交给学生）。

**D-word-lists-2 ECDICT 的 `zk/gk` 标签与 mahavivo 中考/Highschool 表退出成员判定；运行时 ECDICT 只按 `cet4/cet6` 赋阶段。**
决定：构建器只把 ECDICT 的 `cet4/cet6` 标签当成员依据；`services/ecdict.py` 新增 `MEMBER_TAGS = ("cet4", "cet6")` 给 `stages` 属性，`STAGE_TAGS` 四元组保留给 `has_stage_tag`。
理由：ECDICT 的 zk/gk 来自旧考纲（verify list-sources-2；release 库 tag 全集 = csv 8 值，data-engineering §3.7 实测），其 1,603 个 zk 词与现库 zk 100% 一致，不带来新信息；若运行时仍按旧标签赋 zk/gk，用户自添词会拿到种子里已废除的口径（official-purist §3.1.4 第 4 条）。但 `has_stage_tag` 决定屈折形是否回指原形（`words.py:669,673`），缩成两值会改变回指行为（judge-learner-product 对阶段模型线的抽查 #4）。
依据：`services/ecdict.py:28,117-123,173-177`、`services/words.py:663-677`。
否决：continuity 保留 ECDICT zk/gk 标签（两套口径永久混在一列）；三份设计里把 `STAGE_TAGS` 直接改成二元组的写法（破坏 `has_stage_tag`）。

**D-word-lists-3 上海 2020 单词表并入 `zk`，不做「上海/全国」维度；上海 342 个词组首版即入库，但只收 ECDICT 有条目且通过严格归一化的 303 条（展开为 333 行）。**
理由：上海表 24% 不在国家三级（INDEX B5），不并入就漏词；维度的全部受益场景都能用并集覆盖而成本是契约级的（learner-first §3.4，阶段模型线已决定不做）。词组是上海中考词汇表的正式组成（INDEX B4），推迟是功能缺口（judge-learner-product §2.2）；但空释义卡片不能进筛词池（judge-data-safety §2.3 致命 3），所以只收 ECDICT 有条目者；`sb./sth./one's/…` 模板 35 条与 `…` 句式 7 条、`arrive at/in a place` 等 4 条不入，留在 `stats.json.skipped` 供下一版 `overrides` 处理。
依据：[复算] `phrases: raw with ECDICT hit 303 → lemma rows 333`、`[网络]` 首行的 10 条词组；`shmeea-2020-junior.README.md §6`（342 为准）；`services/words.py:143-146`（含空格即 `phrase`）。
否决：official-purist 把词组推到第二版；data-engineering 对无 ECDICT 条目的词组生成最小记录；continuity 的 272 条口径（其 N5 把 `excited` 落回 `excite` 的同一套解析也用于词组，且未对 `/` 并列展开）。

**D-word-lists-4 `xs` 含课标附表的数词/月份/星期；不规则动词表不授予成员；`be/do` 人称形式按显式清单继承原形阶段。**
决定：`moe-2022-appendix.tsv` 的「数词-基数词/序数词」（只收单 token，含连字符）、「月份」「星期」→ `xs+zk`；「地理名称/派生/缩写/节日/地名景点/其他专有名词」→ `zk`；「不规则动词」106 行不产生成员。`manifest.inherit_stages = {"be": [am,is,are,was,were,been,being], "have": [has,had], "do": [does,did,done]}`：清单里的形式若**已是上一版种子的 lemma** 且不是任何官方表词头，则继承原形的阶段并记令牌 `inherit:<base>`；**从不新建行**。
理由：课标说明 5「单独列出」不等于不要求，`Monday`、`ten` 不在小学层说不过去（三份设计一致）。`is/are/does` 在两份纯净路线下变成无阶段词是三位评审都点名的「肉眼可见的回退」（judge-learner-product §2.1、judge-maintainer §1.2-5）；但把附表 106 个不规则动词全部拿来继承会把 `saw`（锯）、`bore`、`shot`、`fell` 等独立义项的词塞进小学/初中层——[复算] 第一轮用通用规则命中了 16 个这样的 lemma，其中 12 个是不该继承的，所以改为显式清单，实际只影响 `am, is, are, does` 4 行（`was/were/has/had/did/done/been` 不是独立 lemma，走 `word_forms`）。
依据：[复算] `inherit = {am, are, does, is}`、`irregular-verb forms that are seed lemmas but NOT inherited = [bore, broke, broken, drunk, fell, given, learned, mistaken, saw, shot, spoken, worn]`；`seed.py:239-241`（表头词守卫使 `is→be` 永远进不了 `word_forms`）。
否决：official-purist「不建议补救」；data-engineering 的 `exclude_groups: ["irregular_verb"]`（排除了却不处理后果）；judge-maintainer 建议的「附表不规则动词整组继承」（会带进 `saw` 一类）。

**D-word-lists-5 括注与并列的文法按交付文件定义，写成纯函数并用交付文件里的真实行做表驱动测试。**
决定：§3.3 的 12 条规则（R1–R12），其中 R2（括注分类）与 R3（并列）直接以 `moe-2022.README.md §4.2`、`shmeea-2020-junior.README.md §4.1`、`moe-senior.README.md §4` 列出的记法为输入。
理由：三份设计都假定产出流水线会预拆并列、把变体放进独立列，而交付文件明确「拆分、去括号、大小写归一都留给种子阶段」；official-purist 的「只改 manifest 不改代码」不成立（judge-data-safety §2.1 致命 1）；data-engineering 的 R2 文法对 `(AmE color)`、`(=mathematics, AmE math)`、`(mum AmE mom)` 不成立（judge-maintainer §3.3-4）。复算第一轮暴露了四处连评审也没发现的坑（§3.6.4）。
依据：`data/lists/moe-2022-level2.txt` 的 23 条括注行、`level3` 61 条、`shmeea-2020-junior.txt` 18 条、`moe-2020-senior.tsv` 61 条、`moe-2025rev-senior.tsv` 71 条（`grep -E '[(/=]'`）。
否决：要求词表任务回头预拆文件（文件忠于原件是正确的姿态，可逐行对照官方件核对）。

**D-word-lists-6 变体（美式拼写、全称、口语形）作为独立行，与词头同阶段、同令牌，不合并、不进 `word_forms`。**
理由：`color`/`colour`、`math`/`maths`、`television`/`TV` 今天都已是独立 lemma（表头词守卫会拒绝把它们写成词形，`seed.py:239-241`）；合并需要 `merged_into_word_id` 流程，不是种子的事（continuity §7.2-4）；美式拼写学习者不该在「仅本阶段新增」里漏掉它们（official-purist 规则 1、data-engineering R11）。全称只收 ≤ 4 个 token、≤ 48 字符者（`normalise_input` 的限制，`words.py:36-37`），所以 UNESCO 的 66 字符全称与 `The United States of America`（5 token）被严格门过滤。
依据：[复算] 变体关系 170 条（`variants per list`），全部在 ECDICT 中；`strict/drop rejected`。
否决：continuity N2「变体不在库则不新建」（`yogurt` 只给 `yoghurt` 打标，官方词头得不到行）；把变体写成 `word_forms(kind='alt')`。

**D-word-lists-7 官方书写的别名写进 `aliases.tsv`，导入时进入 `word_forms(kind='alias')`，不混用 `alt`；需要迁移 `0012_word_forms_alias.sql`。**
理由：`Mr/Mrs/Ms/PE` 是 2022 二级词，孩子会不带点输入；`words.resolve` 的顺序是精确 lemma → `word_forms` → ECDICT（`words.py:663-696`），没有别名行时装了 ECDICT 的部署会命中 `Mr`「存储器回收程序」、`hot-dog`「冲浪术语」（[复算] 译文核查）。`alt` 是 Claude/后缀规则写的记录（`0001_init.sql:222`、`words.py:618,694`），种子别名混进去会让 `test_seed.py:352` 的不变量与 `alt` 的可追溯性一起失效（judge-data-safety §5-7、judge-maintainer §3.3-6）。`word_forms.kind` 有 CHECK，只能重建表（14,132 行，`WITHOUT ROWID`，毫秒级）。
依据：`0001_init.sql:219-225`、`services/words.py:40-50 FORM_KINDS/FORM_KIND_ZH`、`routers/vocab.py:40-43`（搜索已含 `word_forms.form` 前缀）。
否决：data-engineering 的 `aliases → alt`；不做别名搜索（放弃 K-12 最常见的输入错误）。

**D-word-lists-8 retain：词只重标不消失；无阶段词保留为词典词；不删、不下架、不加「拓展」阶段。**
理由：导入器从不 DELETE（`seed.py:280-305`），文件里消失的词会带着旧旗标永久活下去（minimal-delta §3.8.1 与 data-engineering D5 都证明了这个洞）；构建期以上一版种子为输入把它封死。238 个无阶段词 0 个被持有、0 个有内容/图（[复算]），`COALESCE(difficulty, stage_min, 5)` 把它们排到最后，`screen.py:51-55`/`batches.py:232-234` 的旗标 OR 与 `prewarm.py:37-38` 的 `stage_min IS NOT NULL` 自然排除它们。「拓展」层需要阶段枚举再加一位、前端再加一个 tab，而候选集来自两张身份不明的旧表（INDEX A1）——信息用 `legacy:zk/gk` 令牌保留即可。下架属 `WORD_LIBRARY_CURATION.md §2.4 阶段 C` 的 `retired.jsonl`，不在本线。
依据：judge-data-safety §1.3-1（UPSERT 的 `IS NOT` 使 `stage_min 1 → NULL` 真正写入）；`schemas.py:472`/`types.ts:52`（`stage_min` 可空，DTO 不会 500）。
否决：continuity「拓展 = 统计口径」与第二期 `core_min` 列（又一次 `WordBrief` 契约变更）；official-purist 的 `retired-allowlist.txt`（本轮没有任何词需要退役）。

**D-word-lists-9 `sources` 令牌表：保留 `ecdict/cet4/cet6/cet46`，`zk/gk` 改名为 `legacy:zk/legacy:gk`（= 75df534 种子里曾带该旗标），新增官方令牌；manifest 不写阶段顺序。**
理由：`sources` 没有任何读取者（stage-model-15），改它零契约风险；但 official-purist 连 CET 令牌一起改名使 9,162 行全部重写（judge-maintainer §3.1-2），本文只改必须改的：`zk/gk` 作为令牌与阶段码同名会在新口径下造成歧义，而 `legacy:*` 恰好是将来「拓展」候选集的定义（learner-first §3.4）。阶段顺序只允许存在于 `schemas.STAGE_ORDER`（judge-maintainer §1.2-6：manifest 里的副本没有任何门禁）。
依据：[复算] 导入足迹 4,357 行更新（其中 1,756 行只有 `sources` 变化）、4,805 行不动；令牌频次见 §3.6.3。
否决：continuity「现有记号一个都不改名」（`zk` 令牌与 `stage_zk` 语义冲突）；data-engineering 的 `ecdict_zk/ecdict_gk` 两个额外记号（`legacy:*` 已覆盖其用途）。

**D-word-lists-10 构建器从上一版种子复制词典字段，只为新词头查 ECDICT；mahavivo CET 四表成为可选输入。**
理由：同一 ECDICT release 下 9,162 行的词典字段不会变（data-engineering §3.7 实测 `stardict.id` 与 `ecdict_id` 逐一相同），复制保证「导入只碰阶段列与 `sources`」；本机只有校验过的 `stardict.db`（`scratchpad/ecdict-dl/extract/`）而没有 mahavivo 文件，构建不应被一次 216 MB 的下载卡住（data-engineering §7.2「等输入」）。CET 表缺席时：现有行的 CET 旗标与 `cet6_star` 逐字保留，新行只从 ECDICT 标签取 CET 旗标，`stats.json.external_lists = "absent"`。
依据：`scripts/build_seed.py:96-147`（现流程）、`data/seed/stats.json`、learner-first §4 `relabel_seed.py` 思路、judge-data-safety（阶段模型线）§7-2。
否决：从 `stardict.db` 全量重建 9,162 行（每次构建都要验证字节级一致，收益为零）；要求 `WORDLISTS_DIR` 必填。

**D-word-lists-11 `kv.seed_version` 改为解压后内容的 sha256；`pack_seed.sh` 保留并修 BSD 可移植性。**
理由：Apple gzip 与 GNU gzip 字节不同（seed-pipeline-7），按 `.gz` 哈希做版本让 Mac 重打包触发伪重导；内容哈希才是「同一种子」的定义。Python 版打包器的「zlib 跨平台字节一致」说法过强（judge-maintainer §3.2-5），不值得新文件。
依据：`seed.py:107-112,258-263,287`、`main.py:307-319`、`scripts/pack_seed.sh:62-90`。
否决：continuity `pack_seed.py`；official-purist「可选项」（这不是可选的：版本语义必须在同一提交里定）。

**D-word-lists-12 导入器：`--dry-run [--report]` 产出计划；旗标回退只报告不拒绝；未知码计数告警；`seed_check` 捕获异常继续启动。**
理由：continuity 的默认开启守卫会在 `main.startup → seed_check → import_seed` 路径上抛异常，让 `wd serve` 进 launchd 重启循环（三位评审一致判为致命；`WORD_LIBRARY_CURATION.md §1.2` 第 89 行已复现同类循环）；守卫又使修正与回退不可区分。所以 `flag_removed/min_raised` 只是 `--dry-run` 报告的两行，`--allow-regress` 不需要存在。`seed.py:184-185` 的静默丢弃（如旧代码读到 `"xs"`）改为计数 + 一次 WARNING，保证旧代码/新种子、新代码/旧种子都能启动（可分步上线）。
依据：`main.py:307-319,477-495`（`startup()` 对 `seed_check` 无 try/except）；`seed.py:184-185`。
否决：continuity `SeedGuardError`/`--allow-regress`；stages-as-data（阶段模型线）的「未知码报错中止」。

**D-word-lists-13 官方主表词头在 ECDICT 与上一版种子里都查不到 → 构建失败；附表与词组查不到 → 警告并跳过；不生成空记录；ECDICT 义项错误的词用 `overrides.tsv` 自写释义。**
理由：今天 `missing_from_ecdict` 只统计不报错（`build_seed.py:119-121`）正是 `best/less/cafe` 丢了两年没人发现的原因；空释义卡片对学习者没有可学内容（continuity §3.4.4）；附表（说明「单独列出」）与词组本就是补充层，漏一个专名不该阻塞构建。[复算] 主表 0 个缺失；附表缺 `PLA Day`、`Mount Huangshan`、`Mount Taishan` 3 个与 12 个多词数词；需要自写释义的 22 条列在 §3.2.4。
依据：[复算] `main heads missing: {}`、`appendix skipped`、译文核查表。
否决：data-engineering 的 `max_missing 0.5%` 与最小记录；official-purist 对附表缺失也报错。

**D-word-lists-14 构建器进包 `backend/wd/seedbuild/`（3 个模块），脚本只做入口；不新增 `wd` 子命令。**
理由：`scripts/build_seed.py` 单文件不可单元测试（`main()` 一体，`TASKS.md:162`「keep verbatim」前提已失效）；但 7 模块 + 2 条 CLI + JSON schema 是三份里最大的改动面（judge-learner-product §3.3 致命 3），且注册 `wd` 子命令要同步 `cli.py:31-56`、`DEPLOY.md §9`、`test_cli.py:51-58`。服务器运行时不 import `wd.seedbuild`（它不在 `CLI_MODULES`）。
依据：`backend/wd/cli.py:31-56,169-170`、`backend/pyproject.toml:26-28`。
否决：data-engineering 的 7 模块包与 `wd seed-build/seed-diff`；official-purist/continuity 的单文件脚本 + `importlib` 载入测试。

**D-word-lists-15 `difficulty` 尺子：本线不改尺子，假设阶段模型线采用 `COALESCE(w.difficulty + 1, w.stage_min, 6)` 平移（Q5-a）。**
理由：这是 `vocab.py:78` 的一行，属阶段模型线；但 official-purist 对它一字未提是评审点名的缺陷，所以本文把假设写明（§9）。49 行 `difficulty` 不动（`seed.py:10-12` 承诺）。
依据：minimal-delta D5（排练库 `difficulty + 1 = stage_min` 44/49，与迁移前一致）；`0001_init.sql:190`。

**D-word-lists-16 验收常量不再写死：`test_full_seed_acceptance_numbers`、`TASKS.md`、`API.md:169`、`DESIGN.md:209`、`README.md` 全部引用 `data/seed/stats.json`；本文 §3.6 的数字是验收的预期值，最终以构建产物为准。**
理由：三份设计给出的数字三套互不相同，都不是交付文件的数字；验收应比对「构建器说了什么」与「库里有什么」。

---

## 3. 详细设计

### 3.1 阶段成员的集合代数与不变量

记号（`heads(L)` = 按 §3.3 文法拆分、折叠、别名改写后的词头 lemma 集合；`variants(L)` = 括注产生的变体 lemma；所有集合元素都是 `words.normalise_lemma` 口径的小写 lemma）：

```
L2    = heads(moe22:l2) ∪ variants(moe22:l2)                     # 505 行 → 520 个 lemma
L3    = heads(moe22:l3) ∪ variants(moe22:l3)                     # 1600 行 → 1,646
APPxs = moe22:app{数词-基数词, 数词-序数词}(单 token) ∪ {月份, 星期}  ∩ (ECDICT ∪ 上一版种子)   # 77
APPzk = APPxs ∪ moe22:app{地理名称, 地理名称-派生, 缩写, 节日, 地名景点, 其他专有名词} ∩ (ECDICT ∪ 上一版种子)   # 168
SH    = heads(shmeea20) ∪ variants(shmeea20) ∪ shmeea20:app(各节; 数词单 token) ∩ (ECDICT ∪ 上一版种子)        # 1,871
SHP   = phrases(shmeea20:phr) ∩ ECDICT ∩ strict                   # 303 条 → 333 个 lemma
HS    = heads∪variants(hs25) ∪ heads∪variants(hs20)               # 3,162 ∪ 3,045 = 3,256
INH   = { f ∈ inherit_stages[*] : f 是上一版种子的 lemma 且 f ∉ L2∪L3∪SH∪HS }   # {am, is, are, does}

xs    = L2 ∪ APPxs ∪ { f ∈ INH : base(f) ∈ xs }
zk    = L3 ∪ APPzk ∪ SH ∪ SHP ∪ { f ∈ INH : base(f) ∈ zk }
gk    = HS ∪ { f ∈ INH : base(f) ∈ gk }
cet4  = 上一版种子的 stage_cet4 ∪ ECDICT tag cet4(新行) ∪ 外部 CET4/CET46∩CET4 表（存在时）
cet6  = 上一版种子的 stage_cet6 ∪ ECDICT tag cet6(新行) ∪ 外部 CET6/CET46∖CET4 表（存在时）
宇宙  = 上一版种子全部 lemma ∪ xs ∪ zk ∪ gk
stage_min(w) = min{ stage_to_index(s) : s ∈ stages(w) }，stages 为空 → NULL
```

构建期断言（任一失败 → exit 2，不写输出）：
1. `xs ⊆ zk`（[复算] 成立；若将来某版附表只进 xs 不进 zk 会在这里被抓到）。
2. 每个阶段码 ∈ `schemas.STAGE_ORDER`（manifest 不写顺序，构建器 import `wd.schemas`）。
3. 宇宙 ⊇ 上一版种子的 lemma 集合（retain）。
4. 官方主表（`policy: main`）的每个词头都解析到 ECDICT 或上一版种子（否则列出缺失 → 失败）。
5. 同一 lemma 不产生两条记录（`Miss`/`miss`、`May`/`may`、`A.M.`/`a.m.` 在构建期合并：阶段并集、令牌并集、记录取上一版/ECDICT 的那一条）。

**不断言** `zk ⊆ gk`：[复算] 212 个单词（136 个上海独有：`angrily, beautifully, dancer, seafood, bund, hot dog, cafe …`；76 个国家侧附表/变体：序数词、`The Great Wall`、`CPC` …）与 333 个词组只在 zk。用户体验由预设解决：高中生预设保持 `['zk','gk']`（`WelcomePage.tsx:36`，阶段模型线）。

**同一词在多张官方表里**：`stages` 取并集（按 `STAGE_ORDER` 排序），`sources` 记每一张命中表的令牌。例 `colour`：`stages ["xs","zk","gk","cet6"]`，`sources "cet46 ecdict hs20 hs25:0 legacy:gk legacy:zk moe22:l2 moe22:l3"`；变体 `color` 同阶段、同令牌，记录另带 `variant_of: "colour"`。

### 3.2 官方词表文件如何进仓库

#### 3.2.1 目录与文件（以交付命名为准，一个都不改名）

```
data/lists/
  README.md                         # 新建：索引 + provenance 表 + 许可段 + 文件格式（§3.2.5）
  manifest.json                     # 新建：§3.2.2
  aliases.tsv                       # 新建：§3.2.3
  overrides.tsv                     # 新建：§3.2.4
  SHA256SUMS                        # 新建：11 个词表文件的 sha256（shasum -a 256 格式），构建器校验
  moe-2022-level2.txt               # 已交付 505 行（二级）
  moe-2022-level3.txt               # 已交付 1600 行（三级，含二级，星号已去）
  moe-2022-appendix.tsv             # 已交付 267 行；4 列 类别/词/附加1/附加2，表头是 # 注释，类别为中文
  moe-2020-senior.tsv               # 已交付 3000 行；word<TAB>level（0/1/2）
  moe-2025rev-senior.tsv            # 已交付 3099 行；同上
  moe-2020-senior-appendix.tsv      # 已交付 55 行；国家表，只存档（policy: reference）
  moe-2025rev-senior-appendix.tsv   # 已交付 56 行；同上
  shmeea-2020-junior.txt            # 已交付 1724 行（单词正文；a/an/the 不在正文）
  shmeea-2020-junior-phrases.txt    # 已交付 342 行
  shmeea-2020-junior-appendix.tsv   # 已交付 158 行；word/section/note，表头是 # 注释
  shmeea-2020-junior-forms.tsv      # 已交付 146 行；只存档（policy: reference，§3.3 R2 的测试用例来源）
  moe-2022.README.md / moe-senior.README.md / shmeea-2020-junior.README.md / moe-senior-2020-vs-2025.diff.txt   # 已交付
```

行格式（已由交付文件满足，写进 README 并由 `lists.py` 测试钉死）：UTF-8 无 BOM、LF；`#` 开头整行是注释（文件头的来源注释与 TSV 的 `# 列名` 表头都靠这一条共存）；`.txt` 一行一个词头，原件记法；`.tsv` 列由 manifest 的 `columns` 声明，**没有非注释表头行**（`moe-senior.README.md §10` 第 9 条已把两张高中表的表头改成注释）。词头列不得含中文释义/音标/词性——A3 的机械保证；唯一例外是附表的消歧注 `hang (悬挂)`、`lie (躺)`（`不规则动词` 组，`member: false`，在成员判定之前就被丢弃，所以 CJK 检查放在组过滤之后）。

#### 3.2.2 `manifest.json`（全文；`format: 2`）

```json
{
  "format": 2,
  "title": "word-Dance 阶段词表清单：官方词头文件 → 阶段成员（docs/analysis/2026-11-05-stages-regions-images/design/word-lists/SYNTHESIS.md §3）",
  "checksums": "SHA256SUMS",
  "aliases": "aliases.tsv",
  "overrides": "overrides.tsv",
  "ecdict_member_tags": ["cet4", "cet6"],
  "inherit_stages": {
    "be": ["am", "is", "are", "was", "were", "been", "being"],
    "have": ["has", "had"],
    "do": ["does", "did", "done"]
  },
  "lists": [
    {"id": "moe22:l2", "file": "moe-2022-level2.txt", "format": "heads", "policy": "main", "stages": ["xs"], "expect_rows": 505,
     "title": "义务教育英语课程标准（2022 年版）附录 3 二级词汇表"},
    {"id": "moe22:l3", "file": "moe-2022-level3.txt", "format": "heads", "policy": "main", "stages": ["zk"], "expect_rows": 1600,
     "title": "义务教育英语课程标准（2022 年版）附录 3 三级词汇表（含二级）"},
    {"id": "moe22:app", "file": "moe-2022-appendix.tsv", "format": "tsv", "policy": "appendix", "expect_rows": 267,
     "columns": ["group", "word", "extra1", "extra2"], "title": "同上 附表（数词、月份星期、地理名称、缩写、节日与中国文化专有名词、不规则动词）",
     "groups": {
       "数词-基数词": {"stages": ["xs", "zk"], "single_token": true},
       "数词-序数词": {"stages": ["xs", "zk"], "single_token": true},
       "月份": {"stages": ["xs", "zk"]},
       "星期": {"stages": ["xs", "zk"]},
       "地理名称": {"stages": ["zk"]},
       "地理名称-派生": {"stages": ["zk"]},
       "缩写": {"stages": ["zk"]},
       "节日": {"stages": ["zk"]},
       "地名景点": {"stages": ["zk"]},
       "其他专有名词": {"stages": ["zk"]},
       "不规则动词": {"member": false}
     }},
    {"id": "shmeea20", "file": "shmeea-2020-junior.txt", "format": "heads", "policy": "main", "stages": ["zk"], "expect_rows": 1724,
     "title": "上海市教育考试院《2020 年上海市初中英语课程终结性评价指南》词汇表 · 单词"},
    {"id": "shmeea20:app", "file": "shmeea-2020-junior-appendix.tsv", "format": "tsv", "policy": "appendix", "expect_rows": 158,
     "columns": ["word", "group", "note"], "title": "同上 附表（代词、数词、月份星期、国家与国籍、学科）",
     "groups": {
       "基数词": {"stages": ["zk"], "single_token": true},
       "序数词": {"stages": ["zk"], "single_token": true},
       "*": {"stages": ["zk"]}
     }},
    {"id": "shmeea20:phr", "file": "shmeea-2020-junior-phrases.txt", "format": "phrases", "policy": "phrases", "stages": ["zk"], "expect_rows": 342,
     "title": "同上 词组（Phrases and Expressions）；只收 ECDICT 有条目且通过 normalise_input 的展开形"},
    {"id": "shmeea20:forms", "file": "shmeea-2020-junior-forms.tsv", "format": "tsv", "policy": "reference", "expect_rows": 146,
     "columns": ["headword", "kind", "printed", "where"], "title": "同上 词条括号内词形信息（只存档；R2 文法测试样例来源）"},
    {"id": "hs25", "file": "moe-2025rev-senior.tsv", "format": "tsv", "policy": "main", "stages": ["gk"], "expect_rows": 3099,
     "columns": ["word", "level"], "level_token": "hs25:{level}", "provisional": true,
     "title": "普通高中英语课程标准 日常修订版（2017 年版 2025 年修订）附录 2 词汇表（非官方镜像，印发文号待确认）"},
    {"id": "hs20", "file": "moe-2020-senior.tsv", "format": "tsv", "policy": "main", "stages": ["gk"], "expect_rows": 3000,
     "columns": ["word", "level"], "title": "普通高中英语课程标准（2017 年版 2020 年修订）附录 2 词汇表"},
    {"id": "hs25:app", "file": "moe-2025rev-senior-appendix.tsv", "format": "tsv", "policy": "reference", "expect_rows": 56,
     "columns": ["country_zh", "country", "person", "adjective"], "title": "2025 修订版 部分国家名称及相关信息（供教学参考；不入成员）"},
    {"id": "hs20:app", "file": "moe-2020-senior-appendix.tsv", "format": "tsv", "policy": "reference", "expect_rows": 55,
     "columns": ["country_zh", "country", "person", "adjective"], "title": "2020 版 主要国家名称及相关信息（供教学参考；不入成员）"}
  ],
  "external": {
    "note": "mahavivo/english-wordlists 的 CET 文件；通过 --wordlists DIR 提供，缺席时现有行保留上一版旗标、新行只取 ECDICT 标签（stats.external_lists = absent）",
    "lists": [
      {"id": "cet4", "file": "CET4_edited.txt", "mode": "rich", "stages": ["cet4"]},
      {"id": "cet6", "file": "CET6_edited.txt", "mode": "rich", "stages": ["cet6"]},
      {"id": "cet46", "file": "CET_4+6_edited.txt", "mode": "plain", "stages_rule": "cet4 if in cet4 else cet6"},
      {"id": "cet6star", "file": "英语六级词汇（星标，1726）.txt", "mode": "plain", "flag": "cet6_star"}
    ]
  }
}
```

语义：`policy: main` = 词头缺失即失败；`appendix` = 缺失警告并跳过，`single_token: true` 的组只收不含空格的词（连字符允许；`one hundred (and) one` 一类组合数词跳过）；`phrases` = §3.3 R9；`reference` = 只校验 `expect_rows` 与 sha256，不产生成员。`expect_rows` = 非注释行数（与每个文件头部的 `# 计数` 相同；[复算] 505/1600/267/3000/3099/55/56/1724/342/158/146），不是拆分后的词头数——拆分后的数字由 `stats.json.lists[].members` 给出。`level_token: "hs25:{level}"` 把星级写进 `sources`。`provisional: true` 只影响 README/ATTRIBUTION 措辞。阶段顺序、阶段名都不在这个文件里。

#### 3.2.3 `aliases.tsv`（全文；只作用于官方词头与变体，**从不**作用于上一版种子里已有的 lemma）

```
# spelling<TAB>canonical<TAB>note   — 官方书写 → 库内 lemma；小写、NFKC、去重音后比较；导入时写 word_forms(kind='alias')
Mr	mr.	2022 二级/三级与上海表写 Mr；ECDICT 无点条目 Mr 是「存储器回收程序」，带点 Mr. 才是「先生」
Mrs	mrs.	同上
Ms	ms.	同上；无点 MS 是「美国微软公司」
PE	p.e.	官方 PE (=physical education)；ECDICT 无点 PE 是「相位编码」
hot-dog	hot dog	上海表写 hot-dog；ECDICT hot-dog 是冲浪术语、hotdog 是「v. 卖弄」（现库 hotdog 行保留，只剩 cet6）
humourous	humorous	2025 修订高中表第 1401 行的镜像原文拼写（moe-senior.README.md §9.4）；ECDICT 有该拼写条目（frq 0），现库也有此 lemma（旧 Highschool 表），该行保留但不授予阶段
```

不需要别名的情形（折叠即可）：`A.M. (a.m.)`、`P.E.`、`P.M.`（小写）；`café→cafe`、`o’clock→o'clock`（R1）；`Miss/miss`、`May/may`、`China/china`（小写合并）。

#### 3.2.4 `overrides.tsv`（初版 23 行；列 `lemma<TAB>field<TAB>value<TAB>note`，`field ∈ translation | word | phonetic | definition | drop`）

`translation` 用给定的一行**替换**整个 `translation[]`（`definition[]`、音标、词频照旧来自 ECDICT）；`word` 改 display（从而改 `derive_kind`）；`drop` 让该 lemma 不成为成员也不建行。这些是本仓库自己写的 MIT 文本，`ATTRIBUTION.md` 注明「≤ 30 条人工释义」。

```
bund	translation	n. 外滩（the Bund，上海黄浦江西岸）	ECDICT「(政治上的)同盟, 联盟」
the bund	drop		bund 已是词头；避免两行
mum	translation	n. 妈妈（英式口语，= mom）	ECDICT「n. 菊花, 沉默」；现库该行今天就是这个错义项
p.e.	translation	n. 体育（课）（= physical education）	ECDICT 首行「排字错误」
physical education	translation	n. 体育（课）	ECDICT「[医] 体育」
ai	translation	abbr. 人工智能（artificial intelligence）	ECDICT「[计] 附加信息, 人工智能」
bce	translation	abbr. 公元前（Before the Common Era）	ECDICT「化学工程学士」
ce	translation	abbr. 公元（Common Era）	ECDICT「[计] 组件选通」
cpc	translation	abbr. 中国共产党（Communist Party of China）	ECDICT 首行「卡片编程计算器」
un	translation	abbr. 联合国（United Nations）	ECDICT「pron. 家伙, 东西」
wto	translation	abbr. 世界贸易组织（World Trade Organization）	ECDICT「[计] 给操作员送信息」
tcm	translation	abbr. 中医（Traditional Chinese Medicine）	ECDICT「[计] 网络编码调制」
qipao	translation	n. 旗袍	ECDICT「[网络] 女士旗袍；娆洪獥；旗袍裤」
beijing opera	translation	n. 京剧（= Peking opera）	ECDICT「[网络] 京剧；国戏；京戏」
tian'anmen square	translation	天安门广场	ECDICT「[网络] 天安门广场；周年联欢晚会；…」
communist party of china	translation	中国共产党	ECDICT「[网络] …」
world trade organization	translation	世界贸易组织	ECDICT「[网络] …」
children's day	translation	n. 儿童节（6 月 1 日）	ECDICT 释义为基督教节日
women's day	translation	n. 妇女节（3 月 8 日）	ECDICT「女人节」
the changjiang river	translation	长江	ECDICT「江」
stuck	translation	a. 被卡住的，动不了的（stick 的过去式和过去分词）	上海表以形容词义列为词头；ECDICT 只有「stick 的过去式」
wi-fi	translation	n. 无线网络（Wi-Fi）	ECDICT 为技术说明
e-mail	word	e-mail	ECDICT display「E-MAIL」使 derive_kind 判为 proper_noun（现库如此）
```

构建器另对**新行**的译文做两件事：首行以 `[网络] ` 开头的去掉该前缀并计入 `stats.network_translations`（[复算] 词组 10 条：`save one's life, in hospital, go to the movie, be poor at, be located at, go for a swim, make a film, have a class, on weekends, what's more`）；首行为空的新行列入 `stats.empty_translation`，非零则构建失败（[复算] 0）。

#### 3.2.5 `README.md`、`ATTRIBUTION.md`、许可、Makefile

- `data/lists/README.md`：索引三份已交付 README；provenance 表（id · 文件 · 原件 · URL · md5/sha256 · 获取日期 · 解析规则 · `expect_rows` · 对账结论）直接汇总三份 README 的 §1/§2；许可段统一写：课标与考试院词汇表是政府/事业单位发布的考试文件，未声明许可，《著作权法》第五条是否适用未核实（INDEX C4）；本仓库只收录**词头清单**（接近事实数据），不收录释义、词性、例句、版式与说明文字；释义/音标/词频/词形全部来自 ECDICT（MIT）；2025 修订版标「学界已采用、印发文号未见」；`overrides.tsv` 的释义是本仓库 MIT 文本。
- `data/seed/ATTRIBUTION.md` 改为由 `build.py` 从 manifest 渲染（删除 `scripts/build_seed.py:201-219` 常量）：§1 ECDICT 不变；§2 官方词表（manifest `main/appendix/phrases` 条目各一行，含 `provisional`）；§3 mahavivo CET 四表（`external`，不分发；本次构建是否使用）；§4 `overrides.tsv` 人工释义条数；§5 令牌表（§3.6.3）。
- 根 `ATTRIBUTION.md:14` 的「9,162 records」改为引用 `stats.json`；`:19-32` §2 改写为「2a 官方词表（只用词头）」+「2b mahavivo CET 四表」，并注明 `中考英语词汇表.txt`、`Highschool_edited.txt` 已停用（成员资格以 `legacy:*` 令牌保留出处）。
- `data/licenses/` 不新增文件（没有可引用的许可证文本）。
- `Makefile:93-98`：

```make
seed: ## Rebuild data/seed from data/lists + the previous seed: make seed [ECDICT_DB=<stardict.db>] [WORDLISTS_DIR=<mahavivo dir>]
	$(call need,$(PY),run 'make setup' first)
	$(PY) -I scripts/build_seed.py --manifest data/lists/manifest.json --previous data/seed/vocab.jsonl.gz \
	    $(if $(ECDICT_DB),--ecdict "$(ECDICT_DB)") $(if $(WORDLISTS_DIR),--wordlists "$(WORDLISTS_DIR)") --out data/seed
	git show HEAD:data/seed/vocab.jsonl.gz > data/seed/.prev.jsonl.gz && \
	    $(PY) -I scripts/seed_diff.py data/seed/.prev.jsonl.gz data/seed/vocab.jsonl --md data/seed/DIFF.md; rm -f data/seed/.prev.jsonl.gz
	scripts/pack_seed.sh
```

`$(PY)` 是 `.venv/bin/python`（`Makefile:18`），`wd` 在 venv 里是可编辑安装，所以 `-I` 下 `import wd.seedbuild` 成立；`Makefile:37-40` 的注释改为「ECDICT_DB 只在有新词头时需要；WORDLISTS_DIR 可选」。

### 3.3 规范化规则（逐条；文法以交付文件为输入）

全部实现于 `backend/wd/seedbuild/normalise.py`，纯函数、表驱动测试。最终 lemma 一律 `wd.services.words.normalise_lemma(fold(text))`（`words.py:183-189`），并在测试里断言「构建器写进记录的 `lemma` == 导入器 `seed_row` 算出的 lemma」。

| # | 规则 | 函数 | 交付文件里的样例 → 产出 | 对现库的影响 [复算] |
|---|---|---|---|---|
| R1 | **折叠**：NFKC → 弯引号/破折号/全角括号等号斜杠逗号 → ASCII（复用 `words._CHAR_MAP` 并补 `（）＝／，`）→ NFD 去组合变音符 → 空白压缩 | `fold(text) -> str` | `café`→`cafe`；`o’clock`→`o'clock`；`A.M.`→`A.M.`（大小写在 `canon` 处理） | `cafe` 现 `stage_min 3`（`cet4 cet46 ecdict`）→ 进 zk；`o'clock` 已在库 |
| R2 | **括注分类**（仅最后一个括号）：① `pl. …`/`复 …` 或含 CJK → 丢弃；② 项目列表（按 `,`、` AmE `、`美 `、`或` 切分，去掉前导 `=`/`AmE`/`美`；**若任一项 > 2 个 token，则整个括注作为一项**）；③ 每项依次判定：与词头同 lemma → 别名（不产生成员）；是词头在 ECDICT `exchange` 中的屈折形、或该项 ECDICT 条目的 `0:` 指针指向词头、或词头 ∈ {be, have, do} → 屈折，丢弃；单项且 ∈ FUNCTION_NOTES={to,for,with,on,at,in,of,up,out} 且 `词头 项` ∈ ECDICT → **搭配**：短语成为成员，裸词头只在它已是上一版种子 lemma 时才是成员；否则该项 ∈ ECDICT → **变体**成员；否则记入 `unparsed_notes`（警告） | `classify_note(head, note) -> list[NoteItem]`；`split_head(raw) -> ParsedHead(heads, variants, aliases, dropped)` | `colour (AmE color)`→变体 `color`；`maths (=mathematics, AmE math)`→`mathematics`,`math`；`mother (mum AmE mom)`→`mum`,`mom`；`PE (=physical education)`→词头别名 `p.e.` + 变体 `physical education`；`Mr (AmE Mr.)`→同 lemma（别名）；`be (am, is, are)`、`have (has)`、`child (pl. children)`→丢弃；`according (to)`→成员 `according to`，裸 `according` 不入（不在库）；`until (till)`→`till`；`kilo (kilogramme, kilogram)`→两个变体；`UNESCO (United Nations Educational, Scientific and Cultural Organization)`→整项，ECDICT 有但 66 字符 → R12 严格门拒；`BCE (Before the Common Era)`→无 ECDICT 条目，`unparsed_notes`；`bund (the Bund)`→ECDICT 有 `the Bund` → 被 `overrides` drop；`hang (悬挂)`→丢弃 | 变体关系 170 条，全部在 ECDICT；屈折丢弃 17 条；搭配 2 条（`according (to)` 两表）；`unparsed_notes` 1 条 |
| R3 | **并列**：词头部分按 `/` 与 `=` 拆成多个词头，各自成员 | `split_head` | `a/an`（二级、三级、2025）与 `a (an)`（2020，按 R2 变体）→ `a`,`an`；`although/though`、`exam=examination`、`policeman/policewoman (pl. …)`、`actor/actress` | `an` 现 `stage_zk=0, stage_min 2` → xs；`though`,`examination`,`actress` 等进 zk/gk |
| R4 | **可选后缀**：词头紧贴 `(s)`/`(es)`（无空格）→ 两个词头 | `split_head` | `manner(s)`→`manner`,`manners`；`toward(s)`→`toward`,`towards`；`Math(s)`→`math`,`maths` | `manners` 新行（zk） |
| R5 | **别名**：`aliases.tsv` 在 `canon` 中对词头与变体改写；上一版种子 lemma 不改写 | `canon(text, aliases) -> str` | §3.2.3 | `mr./mrs./ms./p.e.` 四行获得 xs；`hot dog` 新行（zk），`hotdog` 行只剩 cet6；`humourous` 行不授予阶段 |
| R6 | **大小写与同 lemma 合并**：lemma 全小写；display 取上一版种子/ECDICT 原形；同 lemma 的多个词头在构建期合并 | `merge_heads` | `miss`/`Miss`、`May`/`may`、`China`/`china`、`A.M.`/`a.m.` | 无新行；`I` 的 display `I`、kind `proper_noun` 不改（既有副作用 seed-pipeline-31，不在本线改 `derive_kind`） |
| R7 | **屈折形式作词头**：官方表列为词头的分词形容词建独立行（ECDICT 有独立条目）；`seed.py:239-241` 的表头词守卫让 `excited→excite(p)` 一类词形行自然消失 | 无特殊代码 | `excited, embarrassed, frightened, frightening, frozen, lost, satisfied, satisfying, stuck, surprised, underlined, united, confused, endangered, dining` | 15 个新行；`word_forms` 减少约 15 行 |
| R8 | **继承**：`manifest.inherit_stages` 的形式若已是上一版 lemma 且非官方词头 → 继承原形阶段，令牌 `inherit:<base>`；从不建行 | `apply_inheritance(members, previous)` | `am, is, are`←`be`；`does`←`do` | 4 行获得 xs+zk+gk（`am` 另有 cet6） |
| R9 | **词组**：`…`/`...` 归一为 ` ... `；可选括号 `(of)`、`(a)`、`(in/on/at)` 展开为含/不含两种；`/` 并列按 **token 级**展开（`at first/last`→`at first`,`at last`；跨 token 的并列只能靠 `overrides.tsv` 的 `phrase` 字段：`a lot of/lots of`、`no longer/not...any longer`）；候选必须**含空格**、在 ECDICT 中有条目、通过 R12 严格门；全部候选落空 → 跳过并按是否含 `sb./sth./one's/oneself/...` 归入 `skipped.patterns` 或 `skipped.other` | `phrase_candidates(raw) -> set[str]` | `a bit (of)`→`a bit`,`a bit of`；`catch (a) cold`→两条；`by bus/train/plane`→三条；`agree with sb.`→跳过（模板）；`add...to`→ECDICT 有但 `...` 是纯标点 token，严格门拒 | 303 条原文 → 333 个 lemma；跳过 39 条（模板 35 + 其他 4） |
| R10 | **连字符/空格**：查 ECDICT 时依次试原形 → 空格↔连字符；**多词词头禁止去空格匹配**（`break down ≠ breakdown`） | `ecdict_candidates(head)` | `e-mail (email)`、`ice-cream` 与 `ice cream` 并存不合并 | 无新行 |
| R11 | **英式/美式**：R2 的变体规则覆盖；两边都是成员 | — | `programme/program`、`realise/realize`、`theatre/theater` | 美式行从 `stage_min 2` 升到对应阶段 |
| R12 | **严格门**：每个候选 lemma 必须通过 `words.normalise_input` 的全部检查（charset `^[A-Za-z' .\-]+$`、≤ 48 字符、≤ 4 个 token、无纯标点 token、带点 token ≤ 6、不以 `-`/`'` 开头）；主表词头不通过 → 失败，附表/变体/词组不通过 → 警告跳过 | `strict_ok(lemma) -> bool`（直接调用 `words.normalise_input`） | 被拒：`The United States of America`（5 token，附表）、UNESCO 全称（66 字符）、7 条 `...` 词组 | 见 [复算] `strict/drop rejected` |

**对 `scripts/build_seed.py:16 RICH_RE` 缺陷的处理**：中考表退出后 `rich` 模式只服务外部 CET 表；`parse_mahavivo(path, mode)` 先做 R1 折叠（全角括号→半角）再用放宽的正则，`a (an)` 产出两个词头，`len(line) == 1` 的跳过改为「单个大写字母」（`a`/`I` 保留）。修复的 7 行（`best`、`less`、`cafe`、`wolf`、`more`、`practice`、`silent`）在新口径下都已由官方表覆盖，所以这个修复只影响 CET 表中同类行（无实测样例），纯防御。

### 3.4 构建器：`backend/wd/seedbuild/`

```
backend/wd/seedbuild/__init__.py     # 空
backend/wd/seedbuild/normalise.py    # R1–R12：fold, canon, classify_note, split_head, phrase_candidates, strict_ok, merge_heads, ecdict_candidates
backend/wd/seedbuild/build.py        # Manifest 读取/校验、来源加载、集合代数、记录生成、stats、ATTRIBUTION、确定性输出
backend/wd/seedbuild/diff.py         # 两版种子的差异报告与不变量
scripts/build_seed.py                # 入口：from wd.seedbuild.build import main; raise SystemExit(main())
scripts/seed_diff.py                 # 入口：from wd.seedbuild.diff import main; raise SystemExit(main())
```

CLI：

```
.venv/bin/python -I scripts/build_seed.py --manifest data/lists/manifest.json --previous data/seed/vocab.jsonl.gz \
    [--ecdict PATH] [--wordlists DIR] --out data/seed [--no-strict] [--built-at ISO]
.venv/bin/python -I scripts/seed_diff.py OLD.jsonl[.gz] NEW.jsonl[.gz] [--md PATH] [--json PATH] [--no-invariants]
```

`build.py` 的签名与步骤：

```python
@dataclass(frozen=True)
class ListSpec: id: str; file: Path; format: str; policy: str; stages: tuple[str, ...]; expect_rows: int; columns: tuple[str, ...]; groups: dict[str, GroupSpec]; level_token: str | None; provisional: bool
@dataclass(frozen=True)
class Manifest: lists: tuple[ListSpec, ...]; external: tuple[ExternalSpec, ...]; aliases: dict[str, str]; overrides: dict[str, dict[str, str]]; inherit: dict[str, tuple[str, ...]]; member_tags: tuple[str, ...]; checksums: dict[str, str]
def load_manifest(path: Path) -> Manifest            # 校验 format==2、已知 policy/format、stages ⊆ schemas.STAGE_ORDER、文件存在、SHA256SUMS 匹配、expect_rows == 非注释行数（不符 → ManifestError）
def load_previous(path: Path) -> dict[str, dict]     # lemma(fold+lower，不走 aliases) → 记录；断言无重复 lemma
class Ecdict: def __init__(self, path: Path | None); def get(self, head: str) -> EcdictRow | None   # word = ? COLLATE NOCASE；path 为 None 时 get 永远返回 None
def collect_members(m: Manifest, prev, ec) -> Membership   # 按 §3.1；返回 lemma → {stages, tokens, variant_of, aliases, origin}
def make_records(membership, prev, ec, m, wordlists) -> list[dict]   # 旧 lemma 复制上一版记录（只改 stages/sources/aliases），新 lemma 从 ECDICT 生成（make_record 字段同 build_seed.py:180-198），再套 overrides
def build(m: Manifest, previous: Path, ecdict: Path | None, wordlists: Path | None, out: Path, strict: bool = True) -> BuildStats
def render_attribution(m: Manifest, stats: BuildStats) -> str
def main(argv: list[str] | None = None) -> int
```

步骤：(1) 读 manifest，校验 sha256 与行数；(2) 读上一版种子；(3) 逐表解析 → `RawEntry(list_id, raw, group, level)` → `split_head`/`phrase_candidates`；(4) 别名、overrides(drop)、严格门、ECDICT/上一版存在性检查（按 policy 决定失败或跳过）；(5) 聚合成员、继承、断言 §3.1 的 1–5；(6) 生成记录（词典字段：旧 lemma 复制，新 lemma 查 ECDICT；CET 旗标：旧 lemma 保留，新 lemma 看 ECDICT 标签，外部表存在时并入；`cet6_star` 同理）；(7) 套 `overrides`（`translation`/`word`/…）；去 `[网络] ` 前缀；(8) 排序 `(stage_to_index(stage_min) if stage_min else 99, lemma)`，写 `vocab.jsonl`（固定键序，`ensure_ascii=False`，LF）；(9) `stats.json`（含 `content_sha256` = `vocab.jsonl` 字节的 sha256）、`ATTRIBUTION.md`；(10) 打印每表 `members/variants/skipped/missing`。两次构建字节相同（无时间戳进 `vocab.jsonl`；`stats.built_at` 由 `--built-at` 给定时才写）。

**种子记录 v2**（键序固定；`✓` = 导入器读取）：

| 键 | 含义 | 导入器 |
|---|---|---|
| `word` | display（上一版/ECDICT 原形；`overrides.word` 可改） | ✓ |
| `lemma` | 构建器算出的 lemma（`words.normalise_lemma(fold(word))`） | 读并核对：不等 → `SeedStats.lemma_mismatch += 1` + WARNING，行为不变 |
| `phonetic, translation[], definition[], pos, collins, oxford, exam_tags[], bnc, frq, exchange{}, ecdict_id, cet6_star` | 同 v1 | ✓ 不变 |
| `stages[]` | 阶段码，按 `STAGE_ORDER` 排序 | ✓ `stage_*` 旗标 + `stage_min = min(stage_to_index)` |
| `sources[]` | 令牌（§3.6.3），排序 | ✓ 空格连接（`seed.py:210` 不变） |
| `aliases[]` | 只在有别名的记录出现（`["mr"]`） | ✓ `word_forms(kind='alias')` |
| `variant_of` | 只在变体记录出现（`"colour"`） | 忽略 |
| `seed_v` | `2` | 忽略 |

**`stats.json` v2**：

```json
{"seed_v": 2, "content_sha256": "…", "total_words": 9617, "previous_sha256": "…", "ecdict_release": "1.0.28", "external_lists": "absent|present",
 "per_stage": {"xs": 600, "zk": 2548, "gk": 3260, "cet4": 4722, "cet6": 7671},
 "first_stage": {"xs": 600, "zk": 1948, "gk": 1255, "cet4": 1726, "cet6": 3850, "none": 238},
 "only_stage": {}, "per_kind": {"word": 0, "phrase": 0, "abbreviation": 0, "proper_noun": 0},
 "lists": {"moe22:l2": {"rows": 505, "heads": 506, "variants": 14, "members": 520, "missing": [], "skipped": []}, "…": {}},
 "tokens": {"ecdict": 8285, "legacy:zk": 2099, "…": 0},
 "variants": 170, "aliases": 6, "inherited": ["am", "are", "does", "is"], "overrides_applied": 23, "network_translations": 10,
 "new_words": 455, "stageless": 238, "rows_changed_vs_previous": {"stage_set": 2601, "sources_only": 1756},
 "with_phonetic": 0, "with_translation": 0, "with_definition": 0, "with_exchange": 0, "multiword": 0, "uppercase": 0, "file_bytes": 0}
```

`pack_seed.sh:44-47` 只读 `total_words`，兼容；`per_stage/first_stage` 的键顺序 = `STAGE_ORDER`。

**`diff.py`**：按 lemma 对齐（v1 记录无 `lemma` 键时用 `words.normalise_lemma(word)` 现算）；输出 (a) 记录数、新增、消失、阶段变化数、字段变化数；(b) `stage_min` 迁移矩阵（旧 1..4/∅ × 新 1..5/∅）与每阶段 `+/−`；(c) 逐词清单（`--only stages|fields|added|removed`）；(d) 「值得人工看」：失去全部阶段的词、新增且译文含 `[网络]` 的词、`merged_heads`、`aliases`、display 变化；(e) 不变量：**新 lemma 集 ⊇ 旧 lemma 集**、`xs ⊆ zk`、`per_stage` 与 `stats.json` 一致——任一失败 exit 1（`--no-invariants` 关闭，只用于比较两个历史版本）。Markdown 写到 `data/seed/DIFF.md`（随种子提交，覆盖式；历史在 git）。

### 3.5 导入器：`backend/wd/seed.py` 与相关运行时

**语义不变的部分**：按 lemma 的 UPSERT、覆盖全部种子列、从不删行、不碰内容/配图/用户表（`seed.py:1-20` docstring 的承诺、`seed.py:72-82`、`:280-305`）。[复算] 对线上 9,162 行的实际写入：4,357 行 UPDATE（2,601 行旗标变化 + 1,756 行只有 `sources`）、455 行 INSERT、4,805 行不动；`updated_at` 只在变化行移动，`/media/card/{id}.svg` 的 LRU 键随之失效一次（`images/card_svg.py:6,158`，无害）。

**改动**（按 75df534 行号）：

1. `:43 STAGES` 删除；新增 `from .schemas import STAGE_ORDER, stage_to_index`；`STAGE_COLUMNS = tuple(f"stage_{s}" for s in STAGE_ORDER)`；`:47-68 SEED_COLUMNS` 的四个旗标列替换为 `*STAGE_COLUMNS`（DDL 顺序 `stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6` 与 0011 一致；`_UPSERT_SQL` 由列表生成，无需手改）。`schemas.py` 只 import `.clock`，无循环依赖。
2. `:184-185`：
   ```python
   raw_stages = rec.get("stages") or []
   known = [s for s in STAGE_ORDER if isinstance(raw_stages, (list, tuple)) and s in raw_stages]
   unknown = [s for s in raw_stages if s not in STAGE_ORDER] if isinstance(raw_stages, (list, tuple)) else []
   ```
   未知码计入 `SeedStats.unknown_stage_codes`，`import_seed` 结束时对非零值打一条 WARNING（列出前 5 个码）。
3. `:204-208`：`**{f"stage_{s}": int(s in stages) for s in STAGE_ORDER}`，`"stage_min": min(stage_to_index(s) for s in stages) if stages else None`。
4. `seed_row` 新增 `"_aliases": [normalise_lemma(a) for a in rec.get("aliases") or [] if isinstance(a, str)]` 与 `"_lemma_declared": rec.get("lemma")`（两者都是下划线键，被命名参数 UPSERT 忽略，与 `_exchange` 同理）；导入时 `_lemma_declared` 非空且 ≠ 计算值 → `lemma_mismatch += 1`。
5. `_rebuild_forms`（`:218-245`）：`DELETE … kind != 'alt'` 不变（`alias` 也被删重建）；在 exchange 词形之后加别名：
   ```python
   for lemma, row in rows.items():
       wid = ids.get(lemma)
       for form in row["_aliases"]:
           if form and form != lemma and form not in lemmas:
               pairs.setdefault((form, wid), "alias")
   ```
   表头词守卫同样适用（`humourous` 既是 lemma 就不会成为别名行）。`stats.aliases` 计数。
6. 版本 = 内容哈希：新增 `seed_digest(path) -> str`（`gzip.open`/`io.open` 流式读、sha256）；`:258` 用 `seed_digest`，`SeedStats` 保留 `sha256`（文件）并新增 `content_sha256`；`kv.seed_version` 写 `content_sha256`；`system_events.detail_json` 加 `content_sha256`。
7. `--dry-run`：
   ```python
   @dataclass
   class SeedPlan:
       inserted: int; updated: int; unchanged: int; orphans: list[str]            # orphans: source='seed' 且不在文件的 lemma
       flag_added: dict[str, int]; flag_removed: dict[str, int]; min_lowered: int; min_raised: int; stageless: int
       matrix: dict[str, int]                                                     # "old→new" 计数，例如 "2→3": 681
       samples: list[tuple[str, list[str], list[str]]]                            # 前 30 条 (lemma, old_stages, new_stages)
   def plan_import(conn, rows: Mapping[str, dict]) -> SeedPlan   # SELECT lemma, <SEED_COLUMNS>, source FROM words；按列逐一比较（None/'' 归一与 _text/_lines/_int 一致）
   def import_seed(conn, path: str, *, force: bool = False, dry_run: bool = False) -> SeedStats   # dry_run: 只算 plan，不开事务、不写 kv/system_events；stats.plan 非空、stats.dry_run=True
   ```
   `cmd_import_seed` 加 `--dry-run` 与 `--report PATH`（JSON：`SeedStats.as_dict()` 含 plan；真实导入时也可写）。`format_stats` 对 dry-run 打印 `would insert N / update M / unchanged U; orphans K; flags +{…} −{…}; stage_min lowered a / raised b; stageless c` 与矩阵。守卫**不**拒绝任何情形。
8. `SeedStats` 新字段：`content_sha256: str = ""`, `unknown_stage_codes: int = 0`, `lemma_mismatch: int = 0`, `aliases: int = 0`, `stageless_records: int = 0`, `dry_run: bool = False`, `plan: SeedPlan | None = None`。
9. docstring `:1-20`：五个阶段旗标、`lemma` 核对、`aliases → word_forms('alias')`、内容哈希、dry-run。

**`backend/wd/main.py:307-319 seed_check`**（全文替换）：

```python
def seed_check(conn, cfg: Settings) -> None:
    """Import the seed when ``kv.seed_version`` differs from the content sha256 of ``WD_SEED_PATH``; never fails startup."""
    path = cfg.seed_path
    if not path.is_file():
        log.warning("seed file %s does not exist; skipping the seed check (set WD_SEED_PATH or run `wd import-seed --file`)", path)
        return
    try:
        digest = seed_digest(path)
        if db.kv_get(conn, "seed_version") == digest:
            return
        log.info("seed version changed; importing %s", path, extra={"event": "seed_import"})
        import_seed(conn, str(path))
    except Exception as e:  # a bad seed must not take the service down (WORD_LIBRARY_CURATION §1.2)
        log.exception("seed import failed; continuing with the current vocabulary", extra={"event": "seed_import_failed"})
        with db.maybe_tx(conn):
            conn.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES ('seed_import_failed', ?, ?)",
                         (json.dumps({"file": path.name, "error": f"{type(e).__name__}: {e}"[:500]}), now_iso()))
```

`import_seed` 内部的事务在异常时已回滚（`test_seed.py:267-277`），连接可继续使用；`kv.seed_version` 未更新，下次启动会重试。`system_events.kind` 无 CHECK（`0001_init.sql:59-64`）。

**`backend/wd/services/ecdict.py`**：`:28` 下加 `MEMBER_TAGS: tuple[str, ...] = ("cet4", "cet6")`；`:117-119 stages` 改为 `[t for t in MEMBER_TAGS if t in self.tags]`；`:121-123 has_stage_tag` 改为 `any(t in self.tags for t in STAGE_TAGS)`（语义不变：四个标签任一）；`:173-177 word_columns` 输出 `**{f"stage_{s}": int(s in stages) for s in STAGE_ORDER}` 与 `"stage_min": min(stage_to_index(s) for s in stages) if stages else None`（import `from ..schemas import STAGE_ORDER, stage_to_index`）。效果：装了 ECDICT 的部署里用户自添词只会得到 cet4/cet6 旗标，不再得到已废除的 zk/gk；屈折形回指行为不变。

**`backend/wd/services/words.py`**：`:40 FORM_KINDS` 加 `"alias"`；`:41-50 FORM_KIND_ZH` 加 `"alias": "另一种写法"`（`lemma_note_zh("Mr.", "alias")` → 「已归为原形 Mr.（另一种写法）」）；`:95-99 _form_kind_order` 的 `ELSE 7` 已覆盖新 kind，不改。

**`backend/wd/migrations/0012_word_forms_alias.sql`**（全文；编号在阶段模型线的 `0011` 之后，若 0012 被占用则顺延并改名，内容不变）：

```sql
-- 0012_word_forms_alias.sql — allow seed-provided spelling aliases in word_forms (kind 'alias').
--
-- The official word lists spell some headwords differently from the dictionary lemma (Mr → mr., PE → p.e.,
-- hot-dog → hot dog; data/lists/aliases.tsv). The seed import writes those spellings as word_forms rows with
-- kind 'alias' so that lookup/search resolve them to the headword before falling back to ECDICT, whose
-- undotted entries mean something else (Mr = a memory-reclaim program). 'alt' keeps its meaning (rows written
-- by lookup_word merges / the suffix rule, never touched by the import; DESIGN §3.1). SQLite cannot ALTER a
-- CHECK list, so the table is rebuilt (14k rows, WITHOUT ROWID, milliseconds). No view references word_forms;
-- the only index is re-created below. The runner wraps this file in BEGIN IMMEDIATE with foreign_keys=OFF and
-- records schema_migrations(12, 'word_forms_alias') itself (SCHEMA.sql §1) — nothing else belongs here.
-- docs/SCHEMA.sql stays the 0001 baseline byte-for-byte (test_db.py).
CREATE TABLE word_forms_new (
  form     TEXT NOT NULL,                               -- normalised like words.lemma
  word_id  INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  kind     TEXT NOT NULL CHECK (kind IN ('p','d','i','3','s','r','t','alt','alias')),  -- ECDICT codes; 'alt' = Claude/suffix rule; 'alias' = seed spelling alias (data/lists/aliases.tsv)
  PRIMARY KEY (form, word_id)
) WITHOUT ROWID;
INSERT INTO word_forms_new(form, word_id, kind) SELECT form, word_id, kind FROM word_forms;
DROP TABLE word_forms;
ALTER TABLE word_forms_new RENAME TO word_forms;
CREATE INDEX ix_word_forms_word ON word_forms(word_id);
```

### 3.6 新旧差异量化（[复算]，交付文件 × `live-copy.db`）

#### 3.6.1 各集合的构成

| 集合 | 大小 | 构成 |
|---|---|---|
| xs | 596（+4 继承 = `stage_xs` 600 行） | L2 主表∪变体 520 ∪ 附表数词/月份/星期 77 |
| zk 国家侧 | 1,809 | L3 主表∪变体 1,646 ∪ 附表 168 |
| zk 上海侧 | 1,871 | 单词正文∪变体 1,737 ∪ 附表 142 |
| zk 单词 | 2,212 | 两侧共有 1,468；仅国家侧 341；仅上海侧 403 |
| zk 词组 | 333 | 303 条原文展开 |
| `stage_zk` 行 | 2,548 | 单词 ∪ 词组 ∪ 继承 |
| gk | 3,256（+4 = 3,260） | 2025 版 3,162 ∪ 2020 版 3,045；共有 2,951；仅 2025 版 211；仅 2020 版 94（月份/数词/国籍词与 `cheek, crayon, foggy, pupil, ice-cream …`；`humorous` 经别名 `humourous→humorous` 两版都有） |
| `zk ∖ gk` | 212 单词 + 333 词组 | 上海独有 136 + 国家附表/变体 76 |
| 2025 版星级在 gk 上 | 0 级 1,646 / ★ 504 / ★★ 1,012 / 仅 2020 版 94 | 进入 `sources` 令牌 `hs25:0|1|2` |

#### 3.6.2 `stage_min` 转移矩阵（行 = 旧 1..4 与新行；列 = 新编号 1..5 / 无）

| 旧 \ 新 | 1 xs | 2 zk | 3 gk | 4 cet4 | 5 cet6 | 无 | 行计 |
|---|---|---|---|---|---|---|---|
| 1 (zk) | 573 | 1,117 | 188 | 122 | 30 | 69 | 2,099 |
| 2 (gk) | 8 | 315 | 681 | 399 | 220 | 169 | 1,792 |
| 3 (cet4) | 2 | 68 | 302 | 1,205 | — | — | 1,577 |
| 4 (cet6) | 1 | 24 | 69 | — | 3,600 | — | 3,694 |
| 新行 | 16 | 424 | 15 | — | — | — | 455 |
| **列计** | **600** | **1,948** | **1,255** | **1,726** | **3,850** | **238** | 9,617 |

「仅本阶段新增」（`vocab.py:54-56`、`/api/stages.new_only_total`）因此从 2,099 / 1,792 / 1,577 / 3,694 变为 600 / 1,948 / 1,255 / 1,726 / 3,850；初中页签的该筛选今天是空操作（INDEX A6），上线后有意义。

#### 3.6.3 令牌表（写进 `DESIGN.md §3.2` 与 `data/seed/ATTRIBUTION.md`）

| 令牌 | 含义 | [复算] 行数 |
|---|---|---|
| `ecdict` | ECDICT 带任一考试标签（不变） | 8,285 |
| `cet4` / `cet6` / `cet46` | mahavivo CET 表归属（不变） | 4,539 / 2,220 / 8,007 |
| `legacy:zk` / `legacy:gk` | 75df534 种子里带 `stage_zk` / `stage_gk`（旧中考表 ∪ ECDICT zk / 旧 Highschool ∪ ECDICT gk）；不授予阶段；将来「拓展」层的候选集 | 2,099 / 3,829 |
| `moe22:l2` / `moe22:l3` / `moe22:app` | 国家 2022 二级 / 三级 / 附表 | 520 / 1,646 / 168 |
| `shmeea20` / `shmeea20:app` / `shmeea20:phr` | 上海 2020 单词 / 附表 / 词组 | 1,737 / 142 / 333 |
| `hs20` | 高中课标 2020 版 3000 | 3,045 |
| `hs25:0` / `hs25:1` / `hs25:2` | 2025 修订版 无星（义务教育 1600）/ ★ 必修 / ★★ 选择性必修 | 1,646 / 504 / 1,012 |
| `inherit:be` / `inherit:do` | 按 `manifest.inherit_stages` 继承 | 3 / 1 |

删除的令牌：`zk`、`gk`（改名为 `legacy:*`）。变体与别名不另设令牌（`variant_of`/`aliases` 只在种子文件里）。

#### 3.6.4 复算揭示、三份设计与三位评审都没抓到的四个文法坑（已在 §3.3 修正）

1. `a (an)`、`advertisement (ad)`（2020 版）被「可选后缀」规则吃掉成 `a an`——后缀规则必须要求括号紧贴词头且内容是 `s/es`（R4）。
2. `UNESCO (United Nations Educational, Scientific and Cultural Organization)` 按逗号切分出 `United Nations Educational`（ECDICT 竟有此条目）——项目 > 2 个 token 时整个括注作一项（R2②）。
3. `according (to)` 让不在库的 `according` 成为初中词——搭配类括注以短语为成员（R2③）。
4. 用附表 106 个不规则动词做通用继承会给 `saw`（锯）、`bore`、`shot`、`fell`、`drunk`、`broken` 等 12 个独立义项的 lemma 打上小学/初中标签——继承改为显式清单（R8）。

另有两处交付文件特有的事实：`humourous`（2025 版第 1401 行的镜像拼写）在 ECDICT 与现库里都有条目，不加别名就会成为高中词；`the Bund` 在 ECDICT 里有条目，会与 `bund` 并存。

#### 3.6.5 对现有数据的影响

- `user_words` 77 个 lemma：65 个阶段集合变化（几乎全是多出 `xs`/`gk`），**0 个失去任何阶段**；用户 2（`stages_json ["zk"]`, 主攻 zk）的 10 个生词 `a, and, be, have, I, in, it, of, the, to` 全部多出「小学」，在主攻初中的推荐排序里从距离 0 变为距离 2（阶段模型线的 `_STAGE_DISTANCE`，`screen.py:35`、`batches.py:60`）——方向正确，发布说明写一句。
- 有 AI 内容的 49 个词：37 个阶段集合变化，0 个失去阶段；`difficulty` 不动（`seed.py:10-12`）；`PROMPT_VERSION` 不变，不触发重生成。
- 无阶段 238 词：旧旗标 `0100` 169、`1100` 41、`1000` 28；kind word 199 / proper_noun 25 / abbreviation 8 / phrase 6；**0 个被持有、0 个有内容、0 个有图**。样例：`airmail, armchair, bathtub, bookcase, bookshop, bungalow, cd-rom, dustbin, egypt, …, humourous`（全表 `recount.json.stageless`）。
- 新行 455：332 个词组 + 123 个单词/多词词头（`excited, angrily, bund, hot dog, kung fu, tofu, drone, lifestyle, ai, bce, ce, 14 个序数词, 15 个分词形容词, 节日/地名/机构 ≈ 45 …`），**全部在 ECDICT 中**；22 个需要 `overrides.tsv` 释义（§3.2.4）。
- 导入足迹：4,357 行 UPDATE、455 行 INSERT、4,805 行不动；`sources` 从 6 种令牌扩为 18 种。

#### 3.6.6 与三份设计数字的差异来源

official-purist XS 594 / ZK 2,194 / GK 3,253 / 无阶段 243 / 新词 112；data-engineering 无阶段 249 / zk 2,022 词头；continuity 505 / 2,520 / 4,297（加法）。本文 596 / 2,212(+333) / 3,256 / 238 / 455。差异全部来自：交付文件 vs 中间解析件（`metr`、`caf`、`kung`/`fu`、页首词、1,722 vs 1,724）、变体口径（R2 的 170 条 vs 其 57/39 条）、词组是否入库、继承 4 行。方向与量级一致，没有任何一处改变结论。

### 3.7 「消失 / 降级」的词的处置

| 情形 | 数量 | 处置 | 依据 |
|---|---|---|---|
| 不再属于任何阶段 | 238 | 留在种子里：`stages: []`、`stage_min NULL`、`sources` 保留 `ecdict/cet*` 并带 `legacy:zk/gk`；行不删、`is_public=1` 不变；只在「全部」页签与搜索可见；筛词/推荐/预生成自然排除 | `vocab.py:52-56`、`screen.py:51-55`、`batches.py:232-234`、`prewarm.py:37-38`；`WORD_LIBRARY_CURATION.md §1.2`「种子从不删词」 |
| 从初中降到高中 / CET | 188 / 152 | 自然降级（`stage_min` 上移）；不保留旧旗标 | 保留等于保留 mahavivo 口径；`legacy:zk` 记录出处 |
| 从高中降到 CET | 760 | 同上 | 旧「高考 3500」多出的词（INDEX C2） |
| 用户收藏的降级词 | 0 | — | [复算] |
| 旧种子有、新词集无、ECDICT 也查不到 | 0 | retain 复制旧记录，不依赖 ECDICT | 词典字段来自上一版 |
| 官方附表词在 ECDICT 中无条目 | 3（`PLA Day, Mount Huangshan, Mount Taishan`） | 跳过，列入 `stats.lists[].skipped`；下一版可加 `overrides`（需要同时给 `word/translation/phonetic`——本轮不做，无音标的专名卡价值低） | D-13 |
| 需要「拓展/超纲」层或「课标外」页签 | — | 本轮不做；候选集 = `legacy:*` 且 `stage_min IS NULL`，一条 SQL 可得 | D-8 |

---

## 4. 改动清单（文件 → 改什么）

**数据与脚本（本线）**

| 文件 | 改动 |
|---|---|
| `data/lists/manifest.json`、`aliases.tsv`、`overrides.tsv`、`SHA256SUMS`、`README.md` | 新建（§3.2；manifest 全文、别名 6 条、覆盖 23 条） |
| `backend/wd/seedbuild/{__init__,normalise,build,diff}.py` | 新建（§3.3–3.4） |
| `scripts/build_seed.py` | 全文替换为入口（`from wd.seedbuild.build import main`）；`TASKS.md:162`「keep verbatim」前提失效 |
| `scripts/seed_diff.py` | 新建入口 |
| `scripts/pack_seed.sh` | `:62,68,79,90` `zcat` → `gzip -dc`；`:63,84,90` `sha256sum` → `command -v sha256sum >/dev/null && sha256sum … \|\| shasum -a 256 …`；`:90` `stat -c %s` → `wc -c <`；`--check` 比对 `gzip -dc \| shasum -a 256` 与 `stats.json.content_sha256`；`:12-13` 注释 |
| `Makefile:37-40,93-98` | §3.2.5 |
| `data/seed/vocab.jsonl.gz`、`stats.json`、`ATTRIBUTION.md`、`DIFF.md`（新） | 重建产物 |
| `ATTRIBUTION.md`（根）`:14,19-32` | §3.2.5 |
| `README.md:5,9,78,103` | 词表范围与数字改为「小学/初中/高中依据国家课标与上海市初中英语词汇表、四六级依据 2016 大纲；记录数见 `data/seed/stats.json`」 |

**后端（本线）**

| 文件 | 改动 |
|---|---|
| `backend/wd/seed.py` | §3.5 第 1–9 条 |
| `backend/wd/main.py:307-319` | `seed_check` 全文（§3.5）；import `seed_digest`、`json`、`now_iso` |
| `backend/wd/services/ecdict.py:28,117-123,173-177` | `MEMBER_TAGS`、`stages`、`has_stage_tag`、`word_columns`（§3.5） |
| `backend/wd/services/words.py:40-50` | `FORM_KINDS` + `alias`；`FORM_KIND_ZH["alias"]` |
| `backend/wd/migrations/0012_word_forms_alias.sql` | 新建（全文见 §3.5） |

**阶段模型线拥有、必须与本线同一提交（列出以便排期，§9）**：`backend/wd/migrations/0011_*.sql`（`stage_xs` 列、CHECK 1..5、`+1`、DEFAULT、`DROP/CREATE VIEW v_bank`、清 `kv.seed_version`）；`schemas.py:25-26,51-52,56-67,488,708,1335`；`services/words.py:39,576-580,589-597`（`stage_xs`）；`ai/prewarm.py:32-33`；`ai/content.py:49`；`services/bank.py:85-86`；`routers/vocab.py:78`；前端 7 个源文件。

**测试（本线）**：`backend/tests/fixtures/mini_seed.jsonl`、`backend/tests/fixtures/lists/*`（新）、`backend/tests/unit/test_seed.py`、`test_seedbuild_normalise.py`（新）、`test_seedbuild_build.py`（新）、`test_seed_diff.py`（新）、`test_db.py`（0012 升级）、`test_words_resolve.py`（别名解析、ECDICT 运行时阶段）、`test_main_seed_check.py`（新，或并入现有 `test_main*.py`）——见 §5。

**文档（本线）**

| 文件 | 改动 |
|---|---|
| `docs/DESIGN.md §3.1 :186` | 旗标说明改为「cumulative on the national chain by construction (xs ⊆ zk), zk ⊄ gk by design; `stage_min` lowest; `NULL` = outside the official lists」；`word_forms` 段加 `'alias'` |
| `docs/DESIGN.md §3.2 :193-209` | 记录 v2 键（`lemma`、`aliases`、`variant_of`、`seed_v`）；`stage_min = min(stage_to_index)`；令牌表（§3.6.3）；`:209` 验收数字改为引用 `stats.json` |
| `docs/DESIGN.md :172,184` | 种子版本 = 内容 sha256；kv 清单文字 |
| `docs/API.md :167,169` | 「5 rows」；`new_only` 说明与 3,694 → `stats.json.first_stage.cet6`（本文预期 3,850）；`:239-240,459-460` 的字面量与映射属阶段模型线 |
| `docs/TASKS.md :160-180` | WP1 验收脚本改为读 `stats.json` 比对；`:162` 删「keep verbatim」；`:165`「sha256 of the file」→「content sha256」；加 `wd import-seed --dry-run` |
| `docs/DEPLOY.md :304,410,417` | `WD_SEED_PATH` 行加内容哈希；`make seed` 新参数；§9 `import-seed [--dry-run] [--report PATH]`；§10 加「停机迁移 0011/0012 + 导入」一段 |
| `docs/WORD_LIBRARY_CURATION.md §1.2` | 加「阶段来源 = `data/lists` 官方词头清单；`DIFF.md` 评审；`seed_check` 已对导入失败防御」 |
| `frontend/src/i18n/zh.ts:86` + `docs/FRONTEND.md:292` | `lists: '词表范围：小学（课标二级）、初中（课标三级与上海市初中英语词汇表）、高中（高中课标词表）、大学英语四级与六级大纲'`——两处逐字相同（`zh.test.ts:19-30` 读 FRONTEND.md 比对；`check-copy.mjs`）。文案由本线定稿，阶段模型线的前端提交直接采用这一行 |

---

## 5. 测试与验收

### 5.1 会变红的现有测试（按 75df534 行号）与处理

| 测试 | 为什么红 | 处理 |
|---|---|---|
| `test_seed.py:61,63,64,73`（60 条）、`test_vocab.py:93,99`（60 / 10） | 夹具加 2 条（§5.2） | 60 → 62、10 → 12 |
| `test_seed.py:93-97` | 重编号：abandon `(0,1,1,1,2)` → `(0,0,1,1,1,3)`；absolutely 3 → 4；ought to 4 → 5；`a` 仍 1 | 写成 `stage_to_index("gk")` 等，不写字面量 |
| `test_seed.py:98`（无 `stage_min NULL`） | 夹具含 1 条无阶段记录 | `== 1` |
| `test_seed.py:113` `a["sources"] == "cet4 ecdict zk"` | 令牌表 | `"cet4 ecdict hs20 hs25:0 legacy:gk legacy:zk moe22:l2 moe22:l3"` |
| `test_seed.py:117` ability `"cet4 cet46 ecdict gk zk"` | 同上 | `"cet4 cet46 ecdict hs20 hs25:0 legacy:gk legacy:zk moe22:l3 shmeea20"` |
| `test_seed.py:136` `kind NOT IN (p,d,i,3,s,r,t)` = 0 | 夹具含别名 | `NOT IN (…, 'alias')` = 0，另断言 `('mr', 'mr.', 'alias')` 存在 |
| `test_seed.py:197,204` | `stages` 四元组 → 五元组；`stage_min == 1` → `stage_to_index("zk")` | 改 |
| `test_seed.py:229-238` | 内容哈希：gz 与 plain 的 `content_sha256` 相同，第二次导入 `up_to_date` | 断言反转（`stats.sha256` 仍不同） |
| `test_seed.py:291-298` | `seed_row` 多 `stage_xs`；`stage_min` 用 `stage_to_index` | 改元组 |
| `test_seed.py:338-353`（`full_seed`） | 全部数字 | 改为读 `data/seed/stats.json` 的 `total_words/per_stage/first_stage/per_kind` 比对；`word_forms` 范围由排练库实测后以 ±1% 钉死；`:352` 加 `'alias'` |
| `test_api_schemas.py:33-39`、`test_vocab.py:69-70,75-76,111,216-234`、`test_screen.py:129-134`、`test_content_apply.py:255`、`test_words_resolve.py:478`、`test_reports.py:86-87`、`smoke.py:352,614`、`check_contract.py:274-281` | 五阶段 / 重编号 / 数字 | 阶段模型线；`test_screen.py:133` 的 `["be","a","go"]` 在夹具加 `xs` 后顺序改变（它们 `stage_min` 变 xs、距离 2），期望值按新夹具重算 |
| `test_db.py:362-366` | 不红（`SCHEMA.sql` 不动） | — |
| `test_deploy_files.py` 19 个 | Mac 上本就失败（GNU 工具） | 不变 |

### 5.2 夹具 `backend/tests/fixtures/mini_seed.jsonl`（60 → 62 条，v2 键）

最小改动原则（official-purist §5.2）：不按新种子重标 gk，避免 `test_screen.py:130`、`test_batches.py:127` 的排序断言连锁。改动：全部记录加 `"lemma"`、`"seed_v": 2`，`sources` 令牌按 §3.6.3 重写（`zk→legacy:zk`、`gk→legacy:gk`，官方令牌只给二级词）；二级词加 `"xs"`：`a, apple, be, book, cat, child, China, clothes, computer, dog, email, glass, go, good, happy, house, ice cream, run, some, study, take, teacher, TV, water`（`an` 故意不加，保持 `test_screen` 的 zk 池）；`is` 加 `"xs"` 与令牌 `inherit:be`；别名路径用 `TV` 记录的 `"aliases": ["t.v."]`（真实写法，`normalise_lemma` 后为 `t.v.`，不与任何夹具 lemma 冲突；`Mr.` 不在夹具里，不为它新增记录）；新增第 61 条 `color`（`stages ["xs","zk","gk","cet4"]`, `variant_of "colour"`，`exchange {"s": "colors"}`）与第 62 条 `bookshelf`（`stages []`，真实无阶段词）。

### 5.3 新增测试

- `test_seedbuild_normalise.py`：表驱动，每条 R1–R12 ≥ 3 例，样例直接取自交付文件（§3.3 表的每一行），含反例：`split_head("a (an)")` → heads `[a]`, variants `[(an, a)]`；`split_head("manner(s)")` → `[manner, manners]`；`split_head("be (am, is, are)")` → `[be]`, dropped 3；`split_head("according (to)")` → 成员 `according to`，裸词头只在 previous 含它时保留；`classify_note("UNESCO", "United Nations Educational, Scientific and Cultural Organization")` → 单项；`strict_ok("united nations educational, scientific and cultural organization") is False`；`phrase_candidates("a bit (of)") == {"a bit", "a bit of"}`；`phrase_candidates("at first/last") == {"at first", "at last"}`；`canon("Mr", aliases) == "mr."`；`fold("café") == "cafe"`；`lemma_of(h) == words.normalise_lemma(fold(h))` 对夹具全量成立；多词词头 `break down` 不匹配 `breakdown`。
- `test_seedbuild_build.py`：`tests/fixtures/lists/` 放迷你 manifest + 6 个小列表（每条规则一行）+ `mini_stardict.sql`（≈ 60 行 `stardict` 表，含 `Mr`/`Mr.`/`hot dog`/`hotdog`/`hot-dog`/`excited`/`the Bund`/`humourous`）+ `previous_seed.jsonl`：(a) 两次构建字节相同且 `content_sha256` 一致；(b) `xs ⊆ zk` 断言与 retain 断言（故意删一个旧 lemma 的清单 → exit 2）；(c) 主表词头缺失 → exit 2 并列出；附表缺失 → 警告 + `skipped`；(d) 旧 lemma 的词典字段逐字等于 previous；(e) `inherit_stages` 只影响 previous 里已有的 lemma；(f) `overrides` 的 `translation/word/drop` 生效；(g) `[网络] ` 前缀被去掉并计数；(h) 外部 CET 目录缺席 → `external_lists == "absent"`，现有行 CET 旗标不变；(i) 产物能被 `seed.import_seed` 导入且 `lemma_mismatch == 0`。
- `test_seed_diff.py`：v1 夹具 vs v2 夹具的矩阵、新增、消失（非空 → exit 1）、`xs ⊆ zk` 失败 → exit 1；md/json 渲染稳定。
- `test_seed.py` 新增：`test_dry_run_writes_nothing`（`dump()` 前后字节相同、`kv` 无 `seed_version`、`plan.inserted == 62`）；`test_dry_run_reports_orphans_flag_changes_and_matrix`（先导入夹具，再对改过阶段的文件 dry-run → `flag_removed`、`min_raised`、`matrix["2→3"]` 正确，且**不抛异常**）；`test_unknown_stage_code_is_counted_not_dropped_silently`（`stages ["xs","cet9"]` → `unknown_stage_codes == 1`，WARNING 一次，`stage_xs == 1`）；`test_alias_rows_written_with_headword_guard`；`test_content_digest_up_to_date_across_gz_and_plain`；`test_lemma_mismatch_counted`。
- `test_main_seed_check.py`（新或并入）：损坏的 gzip / 抛异常的 `import_seed`（monkeypatch）→ `seed_check` 返回、`system_events('seed_import_failed')` 一行、`kv.seed_version` 不变；正常路径不写事件。
- `test_db.py`：0012 升级测试（仿 `:236-257`）：带 `alt` 行的 v11 库升到 v12，`alt` 行保留、可插 `alias`、`bogus` 被 CHECK 拒；`EXPECTED_TABLES` 不变。
- `test_words_resolve.py`：`resolve("mr")` 在别名行存在时 `via == "form"` 且目标 `mr.`、`lemma_note` 含「另一种写法」；ECDICT 运行时新词只得 cet 旗标（`word_columns` 对 tag `zk gk` 的行 → 全 0、`stage_min None`；对 `cet4` 行 → `stage_min == stage_to_index("cet4")`）；`has_stage_tag` 对 `zk` 标签仍为 True。

### 5.4 在 `live-copy.db` 私有拷贝上的排练（不碰 `/Users/sqin/word-dance-data`；一律 `.venv/bin/python` 的 `run_migrations`，不用 `/usr/bin/sqlite3` 排练迁移——`legacy_alter_table=1` 会掩盖 `v_bank` 问题，verify stage-model-13）

```
S=/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad
D=$S/word-lists-synthesis/rehearsal; mkdir -p $D && cp $S/live-copy.db $D/word-dance.db
cd /Users/sqin/word-dance && export WD_DATA_DIR=$D WD_DB_PATH=$D/word-dance.db
make seed ECDICT_DB=$S/ecdict-dl/extract/stardict.db                      # WORDLISTS_DIR 可省（本机无 mahavivo 文件）
cat data/seed/DIFF.md | head -80                                           # 不变量全部通过；矩阵与 §3.6.2 一致（±1%）
.venv/bin/wd migrate --dry-run && .venv/bin/wd migrate                    # 0011 + 0012；pre-migrate 快照在 $D/backups
.venv/bin/wd import-seed --dry-run --report $D/dry.json                   # 期望：insert 455 / update ≈4,357 / orphans 0 / stageless 238 / flag_removed 非零（只报告）
.venv/bin/wd import-seed
sqlite3 -readonly "file:$D/word-dance.db?mode=ro" "select sum(stage_xs),sum(stage_zk),sum(stage_gk),sum(stage_cet4),sum(stage_cet6) from words; select stage_min,count(*) from words group by 1; select kind,count(*) from words group by 1; select kind,count(*) from word_forms group by 1; select count(*) from user_words; select count(*) from word_contents where status='active'; select count(*) from word_images where status='active'; pragma integrity_check; pragma foreign_key_check;"
WD_FULL_SEED_DB=$D/word-dance.db .venv/bin/pytest -q backend/tests -m full_seed   # 默认被 skip（conftest.py:38-46），必须显式设环境变量
.venv/bin/wd import-seed                                                   # 第二次：seed up to date
```

验收：`sum(stage_*)` = `stats.json.per_stage`；`stage_min` 分布 = `first_stage`；`user_words` 77、内容 49、图 31 不变（`dump` 前后对 `user_words/word_contents/word_images/review_logs` 做字节比对）；`word_forms` 含 `alias` 行且 `JOIN words ON lemma = form` 为 0；`integrity_check ok`、`foreign_key_check` 空；第二次导入 no-op；Mac 上用 `gzip -9 -n` 重打包后 `seed_check` 不再触发导入。

---

## 6. 上线与回滚（Mac，launchd）

前提：阶段模型线的 0011 + 五阶段常量 + 前端、本线的 0012 + 种子 + `data/lists` 在同一个（或连续的）提交里；`make test` 全绿且 §5.4 的 `full_seed` 已在排练库上跑过（没有 CI，这是硬门）；`export WD_DATA_DIR=/Users/sqin/word-dance-data`（CLI 默认是 Linux 路径）。

1. 手工备份：`.venv/bin/wd backup --keep-daily 14 --keep-weekly 8`。
2. 停服务：`launchctl bootout gui/$(id -u)/com.word-dance.server`；`curl --noproxy '*' http://127.0.0.1:8000/api/health` 应失败；确认 `kv.worker_lease` 过期。
3. 更新代码：`git pull`；`.venv/bin/pip install -e backend`（无新依赖）；前端按 `memory/macos-local-install.md` 的快照方式发布（阶段枚举变了，前端必须同次上线——旧 SPA 的 `ScreenPage.tsx:31` 会静默丢掉 xs 页签）。
4. 迁移：`.venv/bin/wd migrate --dry-run`（看到 0011、0012）→ `.venv/bin/wd migrate`（自动写 `backups/pre-migrate-10-to-12.db.gz`，`backup.py:283-296`）。
5. 预览：`.venv/bin/wd import-seed --dry-run --report /Users/sqin/word-dance-data/tmp/seed-dry.json`——与 §5.4 排练的报告逐项一致才继续（insert 455、orphans 0、stageless 238、矩阵同 §3.6.2）。
6. 导入：`.venv/bin/wd import-seed`（0.2–0.5 s）。
7. 整理：库文件 5.6 MB → ≈ 9.4 MB 且不自动收缩（verify stage-model 遗漏 4）；服务停着时 `sqlite3 /Users/sqin/word-dance-data/word-dance.db 'VACUUM; ANALYZE;'`。
8. 起服务：`launchctl kickstart -k gui/$(id -u)/com.word-dance.server`；`wd serve` 的 `run_migrations` 无事可做、`seed_check` 因内容哈希一致为 no-op。
9. 验证：`/api/health`；登录后 `GET /api/stages` 5 行、`total/new_only_total` = `stats.json`；`GET /api/vocab?stage=xs&new_only=1` total 600；`GET /api/lookup?q=mr` 解析到 `Mr.`；两位用户的 `current_stage` 字符串不变（`zk`、`cet4`）；`~/Library/Logs/word-dance/word-dance.log` 无 `seed_import_failed`/`MigrationError`。
10. 发布说明写明：初中/高中页签的词集与「仅本阶段新增」数字变化；用户 2 的推荐词顺序变化；`push_batches.settings_json` 历史快照里的整数是旧编号（`batches.py:316` 只写不读）；回滚方式。

回滚：
- 导入后只想退种子（代码与 0011/0012 保留）：`git checkout <上一提交> -- data/seed/vocab.jsonl.gz && .venv/bin/wd import-seed --force`——因为新种子 ⊇ 旧种子（retain），旧文件把 9,162 行的阶段列改回（`stage_xs` 全 0），新增 455 行留下但无阶段（无害）；`--dry-run` 会报告 `flag_removed`，这是预期，不会被拒绝。
- 退迁移：`launchctl bootout …` → `.venv/bin/wd restore /Users/sqin/word-dance-data/backups/pre-migrate-10-to-12.db.gz --yes` → `git checkout 75df534`（或前一标签）→ 重建前端快照指向旧 sha → `kickstart`。**库与代码必须一起回**：新库 + 旧代码对 `current_stage=5` 抛 `ValueError` → 500（`schemas.py:65`），且 `bank.py:181` 会把 `["xs"]` 用户静默回落到 cet4/cet6；回滚丢失快照之后的学习记录。
- `kv.seed_version` 语义切换：回到旧代码（文件哈希）会在下次启动触发一次重导（旧代码读 v2 种子：`xs` 被 `seed.py:185` 静默丢弃、未知键被忽略），无害。

---

## 7. 风险、未决问题、工作量

### 7.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 交付文件的 OCR/转录错词（二级/三级为纯扫描件目视转录） | 个别词进错层 | 三份 README 的逐页对账 + `expect_rows`/sha256 锁定；`DIFF.md` 评审；修正只改 `data/lists` 文件 + `SHA256SUMS` 再 `make seed` |
| 2025 修订版文号未找到 | 若正式版有增删，gk 多出 211 个词 | manifest `provisional: true`；退回 3000 只需删掉 `hs25` 条目重建（`legacy`/`hs20` 令牌不受影响） |
| 阶段编号假设（1..5）与阶段模型线最终方案不一致 | `seed.py`、`ecdict.py` 已改为查 `schemas.stage_to_index`，种子只含阶段码 | 只有 §5.1 的测试字面量与 §3.6.2 的列名依赖编号 |
| 别名的 `word_forms` 行与用户自添 lemma 冲突（有人把 `pe` 添成词） | 守卫跳过别名，搜索退回 ECDICT/临时词 | 既有守卫语义；`stats.aliases` 可见 |
| 333 个词组进入初中层，`frq` 全空、排在尾部，学习卡/配图路径只在 13 个 phrase 上验证过 | 卡片质量未知 | 配图线对 `kind='phrase'` 的处理（§9）；词组译文 10 条已去 `[网络]` 前缀；可用 manifest `policy: reference` 一键退出 |
| `overrides.tsv` 的人工释义 | 释义错误直接进卡 | 23 条，评审 `DIFF.md` 时逐条看；标注为本仓库文本 |
| `seed_check` 捕获异常后服务带着旧种子运行 | 不再是重启循环，但可能长期不一致 | `system_events('seed_import_failed')` 显示在管理页事件表；`wd check db`（阶段模型线）加「`kv.seed_version` ≠ 文件内容哈希」告警 |
| 夹具连锁 | 排序类测试被无意改动 | §5.2 最小改动原则 |
| Linux 生产机 SQLite 版本未知（INDEX 未解决 10） | 0011/0012 的 `RENAME` 新语义需 ≥ 3.26 | Lighthouse 部署前在目标机跑 §5.4 探针 |

### 7.2 未决问题（非拍板项，等输入）

1. 上海 2026 手册 1,785 + 347 词与考试院高考 200 补充词：无机读件（INDEX B6/B7）；manifest 预留 `id` 命名规则 `shmeea26`、`shmeea:gk200`。
2. `PLA Day`、`Mount Huangshan`、`Mount Taishan` 的 `overrides`（需同时自写音标）；39 条词组模板的归一规则（`agree with sb.` → `agree with`？）——下一版种子。
3. `a.m`/`a.m.`、`ice cream`/`ice-cream`、`e-mail`/`email`、`miss`/`miss.` 并存的合并：需要 `merged_into_word_id` 流程，属 `WORD_LIBRARY_CURATION.md §2.4 阶段 C`。
4. `I` 的 `kind='proper_noun'`（`derive_kind` 规则副作用）——本线不改 `derive_kind`，也不引入 `kind` 覆盖。

### 7.3 工作量（本线，人日）

| 项 | 人日 |
|---|---|
| `data/lists/manifest.json`、`aliases.tsv`、`overrides.tsv`、`SHA256SUMS`、`README.md` 索引与 provenance | 1.0 |
| `seedbuild/normalise.py`（R1–R12）+ 表驱动测试 | 2.5 |
| `seedbuild/build.py`（manifest 校验、retain、ECDICT、词组、继承、overrides、stats、ATTRIBUTION、确定性）+ `tests/fixtures/lists` + 测试 | 3.0 |
| `seedbuild/diff.py` + 两个脚本入口 + 测试 | 1.0 |
| `seed.py`（列生成、内容哈希、dry-run/plan、别名、统计）+ `main.seed_check` + `ecdict.py` + `words.py` + `0012` + 测试 + 夹具 | 2.5 |
| `pack_seed.sh`/`Makefile`、文档（DESIGN/API/TASKS/DEPLOY/CURATION/ATTRIBUTION×2/README/zh.ts+FRONTEND） | 1.5 |
| 排练（§5.4）、上线（§6）、发布说明 | 1.0 |
| **合计** | **≈ 12.5（11–14）** |

---

## 8. 仍需产品负责人拍板的问题（每个都给默认，实现先按默认进行）

| # | 问题 | 默认（本文按此实现） | 改变时的代价 |
|---|---|---|---|
| P1 | 课标附表的数词/月份/星期是否进「小学」（课标说明 5「单独列出」） | **进**（xs+zk；数词只收单 token，14 个序数词成为无 `frq` 的小学新词） | manifest 改 `groups` 的 `stages`，重建；xs 从 600 变 ≈ 523 |
| P2 | 上海 342 个词组是否首版入库 | **入** 303 条有 ECDICT 条目且通过严格门的（333 行，`kind='phrase'`，只在 zk，`frq` 空排尾） | manifest `policy: reference`，重建；zk 2,548 → 2,215 |
| P3 | 2025 修订版 3100（镜像、文号未见）是否作为高中依据 | **作为依据**，标 `provisional`；与 2020 版 3000 取并集 | 删 `hs25` 条目重建；gk 少 211 词 |
| P4 | 括注变体/全称是否成为同阶段独立成员（`color`、`television`、`physical education`…） | **是**（170 条关系，全部在 ECDICT；全称 ≤ 4 token） | `classify_note` 的变体分支改为只记录不授阶；美式拼写用户在「仅本阶段新增」漏词 |
| P5 | `is/are/am/does` 继承 `be/do` 的阶段 | **继承**（只这 4 行；`saw/bore/shot…` 不继承） | 删 `inherit_stages`；小学页签没有 `is` |
| P6 | 238 个旧考纲词失去全部阶段后的去向 | **保留为词典词**（`stage_min NULL`，只在「全部」与搜索可见；不删、不下架、不加「拓展」页签） | 「课标外」筛选属阶段模型/前端线；下架属 CURATION 阶段 C |
| P7 | 教材拓展层（牛津上海版/新五四制沪教版词表） | **不做**（许可与来源不明，INDEX B3/C4）；manifest 预留 `policy: reference` 词表位 | 等许可干净的教材词表出现 |
| P8 | 小学层的排序键（`frq` 前 30 个全是功能词，judge-learner-product §2.1） | **不加种子字段**；`words.pos` 已有（ECDICT 词性分布），筛词/推荐排序对 `current_stage = xs` 的处理由阶段模型线决定 | 若要具体性常模（Lancaster CC BY 4.0）需新下载与新列 |
| P9 | mahavivo CET 四表缺席时是否允许构建 | **允许**（现有行 CET 旗标与 `cet6_star` 逐字保留；新行只取 ECDICT 标签；`stats.external_lists = absent`） | 把 `--wordlists` 设为必填 |
| P10 | `overrides.tsv` 自写释义（23 条，本仓库 MIT 文本） | **允许**，上限 30 条，超过要先想别的办法 | 不允许则 `bund/mum/un/wto/tcm…` 带错义项上线 |

---

## 9. 对其他两条线的依赖与接口

### 9.1 阶段模型与地区维度线（`design/stage-model/`）

本线**假设**（三位阶段模型评审的共同建议：minimal-delta 骨架）：五阶段码 `xs, zk, gk, cet4, cet6`，整数索引重编号 1..5，`words.stage_xs` 布尔列，不做方案维度与拓展阶段，`difficulty` 尺子不动、`vocab.py:78` 改 `COALESCE(w.difficulty + 1, w.stage_min, 6)`。本线对编码方案的依赖只有 `schemas.stage_to_index`——若最终选 `xs = 0` 或字符串码，`seed.py`/`ecdict.py` 不改，§5.1 的测试字面量与 §3.6.2 的列名换算即可。

必须由阶段模型线提供、且与本线**同一提交**：

1. `0011_*.sql`：`words.stage_xs INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs IN (0,1))`（列序 `stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6`，与本线 `SEED_COLUMNS` 一致）、`stage_min`/`current_stage` CHECK 1..5、`+1`、`DROP VIEW v_bank` 先行、新用户 DEFAULT、`DELETE FROM kv WHERE key='seed_version'`（可选：本线的内容哈希使首次启动必然导入一次，清不清都行）。本线的 `0012` 排在其后。
2. `schemas.py`：`Stage`/`StageIndex` 字面量、`STAGE_ORDER = ("xs","zk","gk","cet4","cet6")`、`STAGE_NAMES_ZH["xs"] = "小学"`、`index_to_stage` 的上界改 `len(STAGE_ORDER)`、`:488/:708/:1335` 的请求字面量。本线 `seed.py`、`ecdict.py`、`seedbuild` 全部从这里读阶段顺序。
3. `services/words.py:39 STAGES` 引用 `schemas.STAGE_ORDER`；`:576-580 _word_defaults`、`:589-597 _INSERT_WORD_SQL` 输出 `stage_xs`（否则 `_insert_word` 缺参数）；`ai/prewarm.py:32-33`、`ai/content.py:49 STAGE_ZH["xs"]`（否则 `prompt_entry` 对小学词 `KeyError` 整组失败，INDEX D6）；`services/bank.py:85-86` 默认值。
4. 前端：`types.ts:5-6`、`StageChips.tsx:7-9`、`zh.ts:25,28-29`、`WelcomePage.tsx:33-38`（小学生角色；初中生预设 `['xs','zk']`；高中生预设保持 `['zk','gk']`——本线不闭包的前提）、`VocabPage.tsx:29`、`AdminPage.tsx:36`、`ScreenPage.tsx:31`；`zh.ts:86` 的 `sources.lists` 用本文 §4 的字符串。
5. `/api/stages`、`API.md:239-240,459-460` 的契约提交；`check_contract.py:274-281` 两边同序。

本线向阶段模型线提供：`stats.json` 的 `per_stage/first_stage`（页签数字与验收）；令牌表（§3.6.3；`DESIGN.md §3.2` 由本线改写）；「`zk ⊄ gk`」这一事实（他们的验收脚本不得断言 `stage_zk ⇒ stage_gk`——learner-first 曾写错）；`stage_min IS NULL` 的 238 行（若做「课标外」筛选，候选 = `legacy:*` 令牌）；`wd check db` 若加不变量，本线建议两条：`stage_min = min(index of set flags)` 与 `kv.seed_version == content sha256 of WD_SEED_PATH`。

### 9.2 配图更易记线（`design/images/`）

配图线只消费 `words.stage_min`（整数阈值 `WD_IMAGE_KID_STAGE_MAX`）、`words.kind`、`words.pos`（功能词门）与 `translation`（`dictionary_hint`）。本线的影响：

1. `stage_min` 重编号后小学词 = 1、初中词 = 2：他们的阈值在重编号方案下取 2 覆盖小学+初中（pipeline-engineer §2 已写明三种编码各取何值）。
2. 新增 333 个 `kind='phrase'` 的初中词组与 ≈ 45 个专名/节日多词词头：`derive_kind` 判 `phrase`，`pos` 为空（功能词门不触发）；它们没有内容、没有图，进入筛词池后会按正常路径排 `generate_content`/`fetch_image`；配图线若要对 `phrase` 特殊处理（例如跳过照片直接 SVG），以 `kind` 判断即可，本线不另加字段。
3. 238 个无阶段词被 `prewarm all` 排除（`stage_min IS NOT NULL`）；它们已有的 0 张图不受影响。
4. `overrides.tsv` 改了 23 个词的 `translation` 首行，`dictionary_hint` 与 `image_keywords` 的输入随之改善（`bund` 不再是「政治同盟」）。
5. 本线不提供具体性/图标性字段（P8）；若配图线第三期要按具体性跳过抽象词，`words.pos`（n/v/j 占比）是现成的近似，常模要另起任务。

### 9.3 AI 提示词（阶段标签与受众）

`content.STAGE_ZH` 与 `AUDIENCE` 属 AI/阶段模型线；本线只保证每个种子词的 `stages` 都是 `STAGE_ORDER` 内的码，且 `kind` 对词组为 `phrase`（`content.py:90-91` 已把非 `word` 的 kind 写进提示词条目）。

---

## 附：本综合的产物

- `scratchpad/word-lists-synthesis/recount.py`：按 §3.3 文法对 `data/lists/` 交付文件 × `live-copy.db` × `stardict.db` 的只读复算（`python3.12 -I`）。
- `scratchpad/word-lists-synthesis/recount.out.txt`：全部数字的来源（§1、§3.6 引用）。
- `scratchpad/word-lists-synthesis/recount.json`：`XS/ZK/GK/PHRS` 集合、每个 lemma 的新阶段、238 个无阶段词、455 个新行、170 条变体关系、括注分类日志——实现 `test_seedbuild_normalise.py` 的样例可直接从 `note_log` 取。
