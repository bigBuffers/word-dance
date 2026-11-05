# 评审 S3a `seedbuild-normalise-metadata` — 归一化规则库 R1–R12、`data/lists` 元数据、构建夹具

评审日期 2026-11-06。基线 main @ 75df534（工作区 HEAD 0a62322 含已交付的 15 个 `data/lists` 文件）。规格：PLAN §1 R-3/R-4/R-7、§4.1–§4.4、§4.6、§6 S3；WL SYNTHESIS §3.2–§3.4。评审方式：逐文件读实现与测试；用真实 ECDICT 副本（`$SCRATCH/ecdict-dl/extract/stardict.db`，只读 `mode=ro`）与真实上一版种子（`data/seed/vocab.jsonl.gz`，9,162 lemma）把 **全部** 交付行喂给 `split_head` / `resolve_phrase` / `inherit_forms`；对夹具目录做了一次「模拟构建」并与夹具 README 的预期表逐 lemma 对照；对实现做了 6 处临时改坏再恢复的变异测试。评审结束时 `normalise.py` sha256 与开始时相同（`f273ca85…1ca4`），`git status` 与开始时相同，没有修改任何文件。

## 1 结论

**通过，无 blocker、无 major。** 8 条 minor（文档/契约措辞/夹具计数/命名），其中 2 条是需要 PLAN 负责人或 S3b 决定的规格空白而非实现缺陷。实现忠实于 PLAN §4.3 的 12 条规则；三处自报偏离都有据可查、影响范围与自报一致（见 §4）。

## 2 验收命令复跑

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q backend/tests/unit/test_seedbuild_normalise.py` | **238 passed** in 0.21s |
| `cd data/lists && shasum -a 256 -c SHA256SUMS` | 11 个文件全部 `OK`，exit 0 |
| `python -I -c "… manifest.json …"` | `2 11` |
| `.venv/bin/python -I -c "import wd.seedbuild.normalise"` | ok（`-I` 下可导入，PLAN §4.5 前提成立；`pyproject` 用 `packages.find include=["wd*"]`，新子包随之打包） |
| `git diff --stat HEAD -- data/lists/` | 空——已交付 15 个文件一字未改；S3a 只新增 5 个文件 |

## 3 对规格的逐项核对（真实数据）

### 3.1 元数据文件（PLAN §4.1）

- `manifest.json`：与 WL SYNTHESIS §3.2.2 全文逐键比对，差异只有两处且都是 PLAN 要求/允许的：`hs20` 多了 `"level_token": "hs20:{level}"`（PLAN §4.1「两处调整」之一）、`title` 改为引用 PLAN 并声明阶段顺序真相在 `schemas.py`。`inherit_stages` 保留 be/have/do 三组；11 个 `lists` 条目、policy/format/stages/expect_rows/columns/groups 全部相同；不含阶段顺序与阶段中文名（测试 `test_manifest_lists_the_eleven_delivered_files…` 用 `schemas.STAGE_NAMES_ZH` 反向钉住）。
- `aliases.tsv`：6 行，与 SYNTHESIS §3.2.3 逐行相同；`load_aliases` 拒绝链式/自映射/重复。
- `overrides.tsv`：23 行（≤ 30），与 SYNTHESIS §3.2.4 逐行相同；`field` 全在 `translation|word|phonetic|definition|drop`；`the bund` 的 `drop` 行 value 为空、仍是 4 列。
- `SHA256SUMS`：恰好 11 个词表文件（不含三份 README、diff 与元数据自身），`shasum -a 256` 格式。
- `README.md`：索引、provenance 表（id/文件/原件/URL/校验值/日期/解析规则/expect_rows/对账）、许可段（未声明许可、《著作权法》第五条未核实、只收词头、ECDICT MIT、2025 修订 provisional、overrides 为本仓库 MIT 文本）、行格式；全部按 PLAN §4.1/§4.6 与 SYNTHESIS §3.2.5。
- 五个新文件：UTF-8 无 BOM、LF、末尾换行。

### 3.2 规则 R1–R12（PLAN §4.3）在真实 ECDICT 上的复算

全部 11 个列表的每一行（主表 505/1600/1724/3000/3099，附表 267/158，词组 342）：

| 集合 | 实现产出 | SYNTHESIS §3.1/§3.6 复算 | 备注 |
|---|---|---|---|
| L2 / L3 | 520 / 1,646 | ≈520 / ≈1,646 | L2 ⊆ L3 成立 |
| APPzk（moe22:app） | 168（161 行参与，106 行不规则动词 `member:false`） | ≈168 | 缺失 3 个附表词头 `PLA Day`、`Mount Huangshan`、`Mount Taishan`（警告跳过） |
| SH / SH:app | 1,737 / 142（158 行里 12 行非单 token 数词跳过） | 1,737 / 142 | |
| SHP | 334（skipped patterns 36 + other 4，R12 拒 7） | 333（35 + 4） | +4（`be familiar to/with`、`get familiar with`、`go to the movies`）−3（`a lot of`、`lots of`、`no longer`，见 F8） |
| HS = hs25 ∪ hs20 | 3,256 = 3,162 ∪ 3,046 | 3,256 = 3,162 ∪ 3,045 | hs20 多出的 1 个是 `an`（`a (an)`，见 §4） |
| 变体关系（去重对） | 77 对 | 170 条（按出现次数） | 全部在 ECDICT |
| 屈折丢弃 | 16（be ×3 ×4 表 + have ×4 表） | 17 | 少的 1 条是 `an`（见 §4） |
| 搭配 | 2（`according (to)` 三级与 2025 表），裸 `according` 不在上一版 → 丢弃 | 2 | |
| `unparsed_notes` | 1（`BCE (Before the Common Era)`） | 1 | |
| R12 拒（词头/变体） | `The United States of America`（5 token，附表词头）、UNESCO 全称（charset/66 字符，变体） | 同 | 主表词头 0 拒 |
| 新 lemma（∉ 上一版） | 456 | 455 | 差 1 = 词组 +4−3 |
| `inherit_forms` | `{am: be, is: be, are: be, does: do}` | 同 | |
| 函数词被当成变体 | 0 | — | `to/for/with…` 单项从未落到 variant 分支 |

重点核查项：R4 只对紧贴且内容为 `s/es` 的括号生效（`a (an)` → 变体 `an`，`a(an)` → 仍是括注）；R2 `be (am, is, are)` / `have (has)` 丢弃；`according (to)` → 成员 `according to`；UNESCO 全称整项、R12 拒；R10 `break down` 不匹配 `breakdown`，`ice-cream` 与 `ice cream` 并存；R6 `Miss/miss`、`China/china`、`A.M./a.m.`、`Mr/Mr.` 同 lemma；R1 `café`、`o’clock`、全角 `（）＝／，`、`…`、`ＡＢＣ` 折叠正确。真实行抽样 57 条词头 + 16 条词组的完整结果见 `$SCRATCH/review-s3a/sample40.out`。

### 3.3 夹具 `backend/tests/fixtures/lists/`

- 6 个迷你列表的每一行都是交付文件的逐字行（测试钉住）；`previous_seed.jsonl` 53 条与 `data/seed/vocab.jsonl.gz` 逐字相同（本评审逐条比对）；`mini_stardict.sql` 110 行中 **109 行**与真实 `stardict.db` 逐字段相同，1 行不同（见 F4）；DDL 与四个索引与真实库一致；`in hospital`、`save one's life` 带 `[网络] ` 译文（支撑 S3b (g)）；`breakdown` 有、`break down` 无（R10 反例）。
- 用 normalise 规则模拟构建（主表/附表 group 策略/词组/继承/drop）：**82 个成员、32 个新行、3 个保留无阶段（bookshelf, hotdog, humourous）**，与 README 预期表逐 lemma 对照：82 个 lemma 一一对应，阶段与令牌全部一致；唯一不符是 README 正文「30 of them new rows」与表内 32 个 `NEW` 标记（见 F3）。
- 足以支撑 PLAN §6 S3 (a)–(i)：(b) retain/xs⊆zk、(c) 附表缺失 `PLA Day`/`Mount Huangshan`（主表缺失需 S3b 临时改清单）、(e) `being/am/is/are/does` 在 previous 且 `was/were/has/had` 不在、(f) `translation/word/drop` 三类 override 都有样例、(g) 两条 `[网络] `、(h) `external` 文件缺席。

### 3.4 测试质量

- 变异测试 6/6 被捕获：R4 允许空格后括号 → `colour (AmE color)` 红；`_points_to` 去掉 `1:` 要求 → `a (an)` 红；R10 加去空格候选 → `break down` 红；R2 去掉「>2 token 整项」 → UNESCO 红；搭配裸词头保留 → `according (to)` 红；`split_head` 关闭 R12 → USA/UNESCO 红。
- 没有削弱既有断言（全是新文件）。`test_lemma_of_is_the_importer_lemma…` 按定义恒真，但它正是 PLAN §6 S3 点名的契约钉子，保留合理。
- 整表 smoke（5 个主表 7,928 行无 lexicon 下 `heads` 非空、无 R12 拒、无 CJK）与 342 条词组全展开是对交付文件文法的有效回归。

## 4 自报偏离的评估

| 偏离 | 评估 |
|---|---|
| R2 `_points_to` 要求 `0:<head>` **且** `1:` 形码 | **接受。** PLAN §4.3 R2（`0:` 指针→丢弃）与 PLAN §6 S3 的硬性测试（`a (an)` → 变体 `an`）自相矛盾，实现取后者。用真实 ECDICT 枚举「`0:` 指向词头但无 `1:` 码」的括注项，**只有** `an`（`0:a/s:some`）一例，影响如自报：`an` 多得 `hs20:0`。 |
| `known` = ECDICT ∪ 上一版 | 接受；有 ECDICT 时结果不变，且让无 `--ecdict` 的构建不丢已入库变体。 |
| R9 全 slash token 笛卡尔展开 + 紧贴 `(s)` 粘合 | 接受；PLAN R9 本就写「按 token 级展开」。净效果 +4 −3（见 F8）。 |
| 搭配短语放 `heads`（并记 `collocations`） | 接受；PLAN 只要求「成员」。 |
| 额外导出的 helper；`__init__.py` 一行 docstring | 接受（F6 建议回到 PLAN 的「空」）。 |
| 元数据/夹具校验测试放在本切片唯一的测试文件里 | 接受。 |
| `mini_stardict.sql` 110 行而非 ≈60 | 接受；但「逐字」有 1 行例外（F4）。 |

## 5 Findings（按严重度）

无 blocker，无 major。

| # | 严重度 | 文件 | 问题 | 证据 | 建议 |
|---|---|---|---|---|---|
| F1 | minor | `backend/wd/seedbuild/normalise.py` `resolve_phrase` | 含 `sb.`/`sth.` 的模板词组只要 ECDICT 有条目就成为成员，PLAN §4.3 R9 的字面是「模板（sb./sth./one's/…）跳过入 `skipped.patterns`」；实现按 SYNTHESIS「全部候选落空才跳过」。真实数据：`talk to/with sb.` → 成员 `talk to sb.`，`give sb. a hand` → 成员；另 12 条 `one's`/`oneself` 词组成为成员（`save one's life` 是 SYNTHESIS 明示的成员，所以 `one's` 类无疑义）。PLAN §0 的 333 复算已含这些，故非偏离，但 `sb.` 占位符作为学习者可见 lemma（`kind='phrase'`，display `talk to sb.`）值得产品确认 | `$SCRATCH/review-s3a/probe_real.out`「template-marked rows that still produced members」14 条 | PLAN 负责人确认；若不要 `sb./sth.` 行，`resolve_phrase` 对含 `\b(sb|sth)\.` 的候选直接归 `patterns`（`one's/oneself` 保留），并同步 SYNTHESIS R9 措辞。两行之差在 ±1% 容差内 |
| F2 | minor | `normalise.py` `split_head` 契约（模块 docstring） | 词头被 R12 拒或被 `drop` 时，变体仍带 `variant_of=<非成员>`：`The United States of America (USA)` → `heads=()`, `variants=(("usa","the united states of america"),)`；`sh("bund (the Bund)", drop={"bund"})` → 变体指向被丢弃的词头（测试 `test_r2_drop_set_removes_the_overridden_variant` 甚至把这当成预期）。种子记录 v2 的 `variant_of` 会悬空 | 本评审 sample 表、测试第 449–452 行 | 在 docstring 契约里写明 S3b 的处理（变体提升为词头 / 清空 `variant_of`），或在 `split_head` 内：词头部分没有产生任何成员时把变体放进 `heads`。夹具 README 已把 `usa` 描述为「variant of the rejected head」，S3b 要据此断言 |
| F3 | minor | `backend/tests/fixtures/lists/README.md` | 正文「82 members, **30** of them new rows」与表内 `NEW` 标记数（32）及模拟构建结果（32 个 ∉ previous）不符 | `$SCRATCH/review-s3a/probe_fixture.out`：`new (not previous) 32`；表内 NEW 枚举 32 个 | 改为 32；S3b 若用它做 `stats.new_words` 断言会直接踩到 |
| F4 | minor | `backend/tests/fixtures/lists/mini_stardict.sql` 与其 README | 自报「110 verbatim rows」，实际 id 7909 `a` 的 `translation` 把真实库的 `\r\n` 写成了 `\n`（其余 109 行逐字段相同）。无功能影响（`a` 是上一版 lemma，字段来自 previous） | 本评审逐 id 与 `stardict.db` 比对 | 重新导出该行，或把 README/文件头的「verbatim」改为「verbatim（CRLF 已归一）」 |
| F5 | minor | `backend/tests/unit/test_seedbuild_normalise.py:588` | 测试名 `…the_seven_dotted_ones_fail_strict` 但断言 `len(dotted) == 16`；PLAN 的「7」是进入 R12 的数量（6 条 `...` 有 ECDICT 条目 + `get into the habit of` 5 token） | 本评审复算：R12 拒 7 条，含 `...` 的词组 16 条 | 改名为 `…all_sixteen_dotted_lines_fail_strict` 并在 docstring 注明 7 条进入 R12 |
| F6 | minor | `backend/wd/seedbuild/__init__.py` | PLAN §4.5 写 `# 空`，文件含一行 docstring（已自报） | 文件内容 | 可保留；若要与 PLAN 字节一致则清空 |
| F7 | minor | `normalise.py` `inherit_forms` docstring | 「not official heads」；PLAN §4.2 的 INH 条件是 `f ∉ L2∪L3∪SH∪HS`（含变体）。真实数据无差别（没有继承形式是变体），但 S3b 读契约时应传成员全集 | PLAN §4.2 | docstring 写「`official` = 全部官方成员 lemma（词头 ∪ 变体）」 |
| F8 | minor（规格空白） | PLAN §4.3 R9 / §4.1 overrides 字段枚举 | 跨 token 并列 `a lot of/lots of`、`no longer/not...any longer` 展不出成员（`a lot lots of`/`a lot of of`），而 SYNTHESIS R9 指望的 `overrides.tsv` `phrase` 字段不在 PLAN 的 `field` 枚举里；三者都不是上一版 lemma，所以 `a lot of`、`lots of`、`no longer` 在新种子里**不存在**（复算 333 曾含它们）。实现符合 PLAN，但这是三条常用初中词组 | probe：`skipped other` 含 `a lot of/lots of`、`patterns` 含 `no longer/not...any longer`；`PREV` 不含三者 | 请求 PLAN 负责人：给 `overrides.tsv` 加 `phrase` 字段（`lemma<TAB>phrase<TAB><展开形>`）或在 S3b 的 manifest `phrases` 条目加 `expand` 清单；上限 30 条不受影响（+3） |

## 6 给其他切片的请求 / 备注

- → S3b：按 F2 处理悬空 `variant_of`；`inherit_forms(official=…)` 传词头 ∪ 变体；夹具预期是 82 成员 / **32** 新行 / 3 无阶段；附表缺失 `PLA Day`、`Mount Huangshan`、`Mount Taishan`（真实表）要进 `stats.lists[].skipped` 而非失败。
- → PLAN 负责人：F1（`sb.` 模板是否入库）、F8（跨 token 并列词组）。
- 备注：评审期间对 `normalise.py` 做过 6 次临时改坏，每次用 `cmp` 核对恢复；`backend/.pytest_cache` 为既有被忽略目录；没有触碰 `/Users/sqin/word-dance-data`，ECDICT 副本以 `mode=ro` 打开。
