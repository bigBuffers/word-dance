# 评审 · 词表来源与种子流水线 —— 视角「迁移与数据安全怀疑者」

日期 2026-11-06 · 基线 `main @ 75df534` · 评审对象：`design/word-lists/{official-purist,continuity,data-engineering}.md` · 依据：INDEX.md 全文、facts/verify 相关条目、仓库代码（`path:line` 按 75df534）、线上库只读副本 `scratchpad/live-copy.db`（`?mode=ro`）、已交付的 `data/lists/`（2026-11-06 00:02 状态）。本文不改任何仓库文件；独立复算脚本在 `scratchpad/judge-data-safety/zero_impact.py`（`python3 -I`，只读）。

默认立场：每个未被证明的说法都当作错的，直到在代码、库或原始文件里看到。

---

## 0. 结论与排名

| 名次 | 设计 | overall | 一句话 |
|---|---|---|---|
| 1 | **data-engineering** | **7.3** | 数据安全机制最完整（上一版种子作 `retain`、内容哈希版本、构建期 lemma 与导入器一致性断言、manifest sha256/expect、`--dry-run` 孤儿报告、与 Q1 解耦），代价是工作量最大（14 人日）且解析器对已交付 TSV 的表头约定判断错误。 |
| 2 | **official-purist** | **7.0** | 集合代数最清晰、证据最扎实（`final.json` 可复核），上线/回滚步骤正确；但解析层规格与已交付文件不符（「只改 manifest 不改代码」不成立），隐含拍板 1..5 重编号却不提 `difficulty` 尺子错位，若干事实性口误。 |
| 3 | **continuity** | **5.3** | 唯一在上线路径上引入**新故障模式**的设计：默认开启的单调性守卫在 `import_seed` 内抛异常，而 `wd serve` 启动时的 `seed_check` 没有任何捕获——会把服务推进 launchd 重启循环；同时实质偏离 A3，把旧考纲口径永久留在 K-12 层。 |

三份设计共同的、必须在最终方案补上的洞：**`main.seed_check` 对导入失败零防御**（`main.py:307-319`、`:477-485`；`docs/WORD_LIBRARY_CURATION.md §1.2` 第 89 行已确认「启动失败并进入重启循环」）；**已交付 `data/lists/` 的格式**（内联括注、斜杠并列、中文类别、部分 TSV 表头被注释）与三份设计写作时的假设都不一致；**`difficulty` 1–5 尺子与 `stage_min` 的 `COALESCE` 混用**（`vocab.py:78`、INDEX A5）只有 continuity 正面处理（且依赖 xs=0）。

---

## 1. 核验方法与抽查结果

### 1.1 引用抽查（要求 ≥10 处；实际逐条核对 40 余处，下表列有代表性的）

| # | 设计 | 引用 | 核对结果 |
|---|---|---|---|
| 1 | 三者 | `seed.py:43 STAGES`、`:47-68 SEED_COLUMNS`、`:72-82 _UPSERT_SQL`、`:184-185` 未知码静默丢弃、`:208` `STAGES.index(stages[0]) + 1`、`:218-245 _rebuild_forms`、`:239-241` 表头词守卫、`:258/:287 kv.seed_version`、`:333-360 CLI` | **全部属实**（本文附 §1.3 的关键发现：`_UPSERT_SQL` 的 WHERE 用 `IS NOT`，NULL 安全） |
| 2 | 三者 | `schemas.py:25-26 Stage/StageIndex`、`:51-52 STAGE_ORDER/STAGE_NAMES_ZH`、`:56-67 stage_to_index/index_to_stage`（`:65` 越界抛 `ValueError`）、`:472 WordBrief.stage_min`、`:488/:708/:1335` 请求字面量 | 属实；`WordBrief.stage_min: StageIndex \| None`（`schemas.py:472`），`types.ts:52` 同为 `StageIndex \| null` → 无阶段词不会让 DTO 500 |
| 3 | 三者 | `0001_init.sql:148` `current_stage CHECK BETWEEN 1 AND 4`、`:185` `stage_min CHECK BETWEEN 1 AND 4`（可 NULL，注释「NULL = outside the 4 lists」）、`:205 ux_words_lemma`、`:219-225 word_forms`（`kind` CHECK 含 `'alt'`）、`:266 score`、`:572 v_bank`（含 `w.stage_min`） | 属实；`docs/SCHEMA.sql` 与 `0001_init.sql` 字节一致（`cmp` 通过），`test_db.py:362-366` 守住它；migrations 目录只有 0001/0008/0009/0010，下一个编号 0011 ✓；0010 用 `ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT … CHECK` 确有先例 |
| 4 | 三者 | `main.py:307-319 seed_check`、`:482-485` 启动顺序 `run_migrations → seed_check`；`install.sh:140-141` migrate → import-seed | 属实；**`seed_check` 调 `import_seed` 无 try/except**，`startup()` 也不捕获（见 §1.3） |
| 5 | 三者 | `services/ecdict.py:28 STAGE_TAGS`、`:118-119 stages`、`:173-177 word_columns`（`stage_min` 同式） | 属实 |
| 6 | 三者 | `services/words.py:39 STAGES`、`:143-151 derive_kind`、`:183-189 normalise_lemma`、`:576-580 _word_defaults`、`:589-597 _INSERT_WORD_SQL`；`routers/vocab.py:52-56` 阶段筛选、`:78 COALESCE(w.difficulty, w.stage_min, 5)`、`:86-98 /api/stages`、`:89 new_only_total` | 属实 |
| 7 | 三者 | `screen.py:34-36/:44/:51-55`、`batches.py:60-61/:232-234/:272/:698`、`prewarm.py:32-33/:37-38`、`content.py:48-49/:88/:90-91`、`bank.py:85-86/:181` | 属实；注意实际路径是 `backend/wd/services/screen.py`、`services/batches.py`（任务书写的 `ai/` 是笔误，设计文稿多数只写文件名，未受影响） |
| 8 | official-purist | `test_seed.py:93/94/96/97/98/197/204/291-298/339-353`、`test_api_schemas.py:33-39`、`test_vocab.py:69-70/75-76/93/99/111`、`test_screen.py:129-134`、`test_batches.py:127`、`test_content_apply.py:255`、`test_words_resolve.py:478`、`test_reports.py:86-87`、`smoke.py:352`、`check_contract.py:274-281` | 全部属实；**漏列** `smoke.py:614`（`len(stats["stages"]) == 4`，continuity 与 data-engineering 都列了） |
| 9 | continuity | `test_seed.py:113`（`a["sources"] == "cet4 ecdict zk"`）、`:229-238`（`:234`）、`test_vocab.py:232-234`（3694/7671）、`FRONTEND.md:292`、`zh.test.ts:19-30`、`WelcomePage.tsx:35`、`0010 先例` | 属实 |
| 10 | data-engineering | `requirements.txt:9` `jsonschema>=4.18,<5` 是运行依赖、`pyproject.toml:26-28` package-data、`cli.py:31-56 CLI_MODULES/COMMAND_OWNERS`、`test_cli.py:51-58`、`test_seed.py:86`（`I` 故意不在夹具）、`:348` forms 14000–14300、`:352` `kind` 不变量 | 属实（记忆文件里「jsonschema 只在 dev」已过时；fallback 提交后进了运行依赖）。但 `cli.build_parser()` 对 CLI_MODULES **逐个 `importlib.import_module`**（`cli.py:169-170`），「服务器运行时不导入 seedbuild」不准确 |
| 11 | 三者 | 线上基线：9,162 / zk 2,099 / gk 3,829 / cet4 4,722 / cet6 7,671；`stage_min` 2,099/1,792/1,577/3,694；kind 9,004/13/26/119；`difficulty` 49；`user_settings` `(1, 3, ["zk","gk","cet4","cet6"])`、`(2, 1, ["zk"])`；`user_words` 77；`word_contents` 49；`word_images` 31；`kv.seed_version a68127…`；`word_forms` 14,132；schema v10 | **全部与 live-copy 一致**（本文只读查询） |
| 12 | official-purist | `is/are/am/does`、`hotdog` 变无阶段 | **部分不实**：live `am` 旗标 `(1,1,0,1)`、`hotdog` `(1,1,0,1)`，都带 `stage_cet6=1`（`sources` 含 `cet46`），按其自身「CET 原样」代数仍留在 cet6 层 |
| 13 | continuity | 夹具 60 条 zk 35 / gk 52 / cet4 45 / cet6 24，首阶段 35/19/3/3 | 属实（本文重算） |
| 14 | 三者 | 评审证据目录 `scratchpad/word-lists-{official-purist,continuity,data-eng}/`、`ecdict-dl/extract/stardict.db` 851,288,064 B | 存在；`final.json`（XS 594 / ZK 2194 / GK 3253 / stageless 243 / newwords 112）、`quant_output2.txt`（2520/4297/1269/16.2%/24.2%、top-k 原始与扣除附表两组数）、`preview_out.json`（含 `metr`、`caf`、`kung`/`fu` 噪声，作者已声明） |

### 1.2 独立复算（`zero_impact.py`，宽松解析已交付 `data/lists/`，live-copy 只读）

- 已交付官方表的词头并集 ≈3,508（含解析噪声）；`L2 ⊆ L3` 成立；`L3 − HS25` 除 `pl.` 噪声外只剩 `yogurt`（与 official-purist §3.1.3 一致）。
- 线上只带 zk/gk 旗标的 305 个词中，**237 个不在任何官方表**（official-purist 算 243、data-engineering 算 249，差异在变体/屈折归一方式）；其中 **0 个被 `user_words` 持有、0 个有 AI 内容、0 个有图**——两份「零影响」声明成立。
- 77 个生词中 11 个在 L2（将获得 xs 标签）；49 个内容词中 1 个在 L2。

### 1.3 跨方案的数据安全事实（本文自己查到、三份设计都需要知道的）

1. **UPSERT 对 NULL 安全**：`_UPSERT_SQL` 的 DO UPDATE 条件是 `words.{c} IS NOT excluded.{c}`（`seed.py:79`），所以 `stage_min 1 → NULL` 的降级会真正写入，不会出现「比较结果为 NULL、行不更新」的残留。两份「无阶段词」设计都没点明这一点，但它们的方案因此成立。
2. **`seed_check` 零防御**：`main.startup()` → `db.run_migrations` → `seed_check(conn, cfg)` → `import_seed(conn, str(path))`，任何异常直接冒泡到 `lifespan`，服务起不来；launchd 会反复拉起。`WORD_LIBRARY_CURATION.md §1.2`（第 89 行）用截断 gzip 复现过这个重启循环。任何在导入器里「拒绝导入」的设计（continuity 的守卫）都必须同时改 `seed_check`。
3. **`stage_min` 的消费者**（`grep -rn stage_min backend/wd`）：`vocab.py:55/78/89`、`services/stats.py:180`（`/api/stats` 的 StageInfo，同一口径）、`prewarm.py:38`、`screen.py:35`、`batches.py:60`、`ecdict.py:177`、`words.py:277/580/591-594`。无阶段词（NULL）在旗标 OR 筛选下不进入筛词/推荐池，在 `COALESCE(difficulty, stage_min, 5)` 下排最后——三份设计对这一点的描述一致且正确。
4. **`v_bank` 含 `w.stage_min`**（`0001_init.sql:572-576`）：重建 `words` 前必须 `DROP VIEW v_bank`，INDEX A4 已证；三份都提到。
5. **`difficulty` 尺子**：`difficulty CHECK BETWEEN 1 AND 5`（1 初中 … 4 六级，5 beyond，`0001_init.sql:190`）与 `stage_min` 被 `COALESCE` 当一把尺子（`vocab.py:78`）。重编号 1..5 后 `stage_min=5` 是六级、`difficulty=5` 是「超六级」，排序把两者并列；`stage_min=1` 是小学、`difficulty=1` 是初中。这是 INDEX A5/Q5 明示的问题，official-purist 一字未提（全文 `difficulty` 只出现在 `hs_level` 预留与 COALESCE 描述），data-engineering 显式推给 Q1，continuity 用 xs=0 规避。
6. **全库 `updated_at` 刷新**：三份设计都会改写 ≈6,000–9,162 行的 `sources`，`updated_at` 随之更新；唯一消费者是 `/media/card/{id}.svg` 的 LRU 键 `(word_id, active_content_id, updated_at)`（`images/card_svg.py:6,158`），无客户端增量同步逻辑——「无害」结论成立。
7. **`StageIndex = Literal[1,2,3,4]`**（`schemas.py:26`）：五阶段下任何 `stage_min=5`（或 0）的行在 `StageIndex` 扩展前都会让 `WordBrief` 校验失败 → 500；这是阶段模型线的工作，但三份设计的「部署顺序」都默认它与种子同一提交，正确。
8. **已交付 `data/lists/` 的真实格式**（三份设计写作时都未读到或只读了文件名）：
   - `moe-2022-level2.txt`/`level3.txt`：一行一词头，**内联括注与斜杠并列未拆**：`a/an`、`be (am, is, are)`、`colour (AmE color)`、`mother (mum AmE mom)`、`Mr (AmE Mr.)`、`PE (=physical education)`；`I`、`excited` 在表内；level3 同时有 `miss` 与 `Miss`（同 lemma）。头部是中文自由文本注释（`# 计数：505 行 = …`），**没有** `# count: 505` 这类机器可读键。
   - `moe-2022-appendix.tsv`：4 列 `类别<TAB>词<TAB>附加1<TAB>附加2`，**表头行被 `#` 注释掉**，类别是中文（数词-基数词/数词-序数词/月份/星期/地理名称/地理名称-派生/缩写/节日/地名景点/其他专有名词/不规则动词），267 行含 106 个不规则动词。
   - `moe-2020-senior.tsv`/`moe-2025rev-senior.tsv`：**有未注释表头** `word<TAB>level`；2020 版写 `a (an)`，2025 版写 `a/an`；级别分布 1500/499/1001 与 1600/502/997（与 verify 解析件的 1,525/487/985、1,605/501/1,000 不同）。
   - `shmeea-2020-junior.txt`：1,724 行词头，不拆 `/`、`=`（`although/though`、`exam=examination`），保留 `manner(s)`、`toward(s)`、`phone (=telephone)`、`bund (the Bund)`；`shmeea-2020-junior-phrases.txt` 342 行；`shmeea-2020-junior-appendix.tsv`/`-forms.tsv` 表头被注释。

---

## 2. 逐份评审

### 2.1 official-purist

**契合（7）**。严格按 A1–A4：阶段成员只由官方词头决定，上海表并入 zk，附录数词/月份星期进 xs（有课标说明 5 的依据）。对线上两位用户：77 个生词 64 个「多一个 chip」，无数据损失；243 个无阶段词 0 被持有（本文复算 237 / 0，§1.2）。扣分点：`is`（live `stage_min=1`，`sources 'gk zk'`）、`are`、`does` 变无阶段词典词，小学生按阶段浏览看不到 `is`——作者自己列为风险并「不建议」补救，但对 K-12 产品这是可感知的缺口。

**正确性（6）**。
- 成立的：UPSERT NULL 安全（§1.3-1）；`stages: []` 的记录被 `seed_row` 正确映射为四（五）个 0 与 `stage_min NULL`；`--previous` 回填保证旧 lemma 不消失；`seed_diff.py` 的不变量（新 lemma 集 ⊇ 旧、xs ⊆ zk、per_stage 与 stats 一致，失败 exit 1）是好的构建期闸门；`missing_policy.official: error` 终结了今天的静默 `missing_from_ecdict`。
- **致命 1：解析层规格与已交付文件不符。** §3.2.1 假定 `variants` 在第 2 列、`a/ an 拆两行`、头注释为 `# key: value` 且 `parse_official` 校验 `# count` 与行数一致（不一致 exit 2）。实际文件（§1.3-8）是内联括注与斜杠并列、中文自由文本头注释、附录 TSV 表头被注释且类别为中文。文中「若实际文件的列与本文不同，改 manifest 的 `columns`，不改构建代码」**不成立**：`a/an`、`colour (AmE color)`、`PE (=physical education)`、`be (am, is, are)` 的拆分/分类逻辑必须进代码（正是 data-engineering 的 R2/R3），`# count` 校验会直接失败或需要删掉，`stages_by_group` 的英文组名需要一张中文映射表。按文稿实现会在第一次 `make seed` 失败，或（若放宽校验）静默把 `a/an` 当一个词头丢掉——后者正是今天 `RICH_RE` 丢词那一类缺陷的翻版。
- **致命 2：隐含拍板 Q1-a 却不负责其后果。** 全文数字（`stage_min` xs=1…cet6=5）、夹具与测试改动、`API.md`/`TASKS.md` 数字替换都按重编号 1..5 写；§3.1.4 第 2 条还要求 0011 在 `INSERT … SELECT` 里做 `stage_min + 1`/`current_stage + 1`。但对 INDEX A5 明示的 `difficulty` 尺子错位（§1.3-5）**一字未提**；对「若阶段模型线选 xs=0 或字符串码」只说「构建端只需改这一行」，而 §5.1 列出的十余处测试常量、§3.6.3 的转移矩阵、§6.7 的验收口径全都要重写。设计把最关键的耦合点当成别人的事。
- 事实性口误：`am`、`hotdog` 并不会变无阶段（§1.1 #12）；`is/are/am/does` 四个里至少 `am` 留在 cet6。漏列 `smoke.py:614`。这些不影响主结论，但说明 §3.6.5 的分类清单没有逐词对过 CET 旗标。
- 运行时一致性：§3.1.4 第 4 条把 `ecdict.py:28 STAGE_TAGS` 改为只认 cet4/cet6 是**必要**的（否则用户自添词会拿到已废除的 zk/gk 口径）——三份里 official-purist 与 data-engineering 都写了，continuity 只改了 `stage_min` 公式。

**工作量与风险（6）**。8 人日的估计建立在「解析层只是读列」上；按真实文件至少要补括注分类、并列拆分、中文组名映射、表头开关，接近 data-engineering 的 `normalise.py` 规模。数据面风险可控：全部变化可在 `--dry-run` 与 `DIFF.md` 里预览；但 `--dry-run` 是建议而非闸门，`wd serve` 的 `seed_check` 仍会在无人值守下自动导入（§1.3-2）。

**可维护性（7）**。manifest 驱动、`aliases.tsv`/`overrides.jsonl`、`legacy-*` 来源记号、ATTRIBUTION 从 manifest 渲染、`stats.json` v2 带 `vs_previous`——都减少硬编码。但仍保留 `seed.py:43 STAGES` 元组与 `STAGES.index(stages[0]) + 1` 公式（「不改公式只改元组」），与 Q1-b/c 不兼容；`build_seed.py` 仍是单文件脚本，测试要 `import scripts/build_seed.py`。

**证据（8）**。数字全部可在 `final.json` 复核；对 INDEX 的引用准确（B2/B4/B5/C1/C2/A6、矛盾 1/9）；新核实 release 库 tag 全集（关闭 INDEX 未解决 6 的一半）。扣分：§3.6.5 的个例分类错误；对已交付文件「只看了文件名、未读内容」却给出「只改 manifest」的结论。

**上线与回滚（7）**。停服务 → 手工备份 → `wd migrate --dry-run`/`migrate`（pre-migrate 快照，`backup.py:283-296`）→ `import-seed --dry-run`（期望 ≈112 inserted / ≈9,162 updated）→ 导入 → 起服务 → 验证；回滚明确「库与代码必须一起回」（`schemas.py:65` 对 5 抛 `ValueError`）、VACUUM 手动。缺：`seed_check` 自动导入路径无闸门；0011 的 `+1` 与随后 `import-seed` 的绝对值覆盖之间若导入失败，库虽自洽但 `stage_xs` 全 0——文中有提（§3.1.4-2），处置是「库仍自洽」，可接受。

**可嫁接**：§3.1.2 的显式集合代数（含 `HS3100 ∪ HS3000` 显式并集，避免 94 个月份/数词/国籍词掉出高中层；V(·) 变体作独立行继承阶段，不建 `word_forms`）；`seed_diff.py` 不变量 exit 1；`missing_policy.official: error`；`legacy-zk/legacy-gk` 记号；§3.6.6 对两位用户 77 个生词的逐词影响表；`ecdict.py STAGE_TAGS` 只认 cet；§5.2 夹具「最小改动」原则（不按新种子重标 gk 以免连锁打破排序断言）。

### 2.2 continuity

**契合（5）**。保留旧表成员是对 A3「mahavivo 中考/高中表不再作为阶段依据」的**实质偏离**（已声明，理由是「不丢阶段」）。代价作者量化了：zk 16.2%、gk 24.2% 超纲（扣除附表与变体后），999 个纯旧表词，其中 227 个无任何官方或 CET 归属（`abortion/bungalow/yummy` 谱系，INDEX A1）。「拓展」第一期只是 `sources` 里的记号，**没有任何读取者**，用户在阶段页签与「仅本阶段新增」里看到的就是 2,520/4,297 的混合口径。对上海初中生按词频前 300 推荐词拓展为 0 的论证成立（`quant_output2.txt` 第 124-128 行，扣除附表口径；原始口径第 55-59 行是 0/1/6/16/47，文稿正文有说明但摘要没有标「扣除后」）。对两位现有用户：设置行不动、池只增不减，推荐顺序变化（用户 2 的 499 个基础词沉到距离 2）——方向正确、已写进发布说明。

**正确性（5）**。
- 成立的：`xs ⊆ zk` 由 `L2 ⊆ L3` 保证（本文复算 ✓）；不做闭包；`stage_xs` 作 additive 列（0010 先例 ✓）；`PRAGMA table_info(words)` 前置检查避免 `no such column`；旧代码读新种子静默忽略 `xs`（`seed.py:184-185` ✓）；多词词头禁止去空格匹配（`break down ≠ breakdown`，实证 5 个假阳性）——这是三份里唯一指出的真实陷阱。
- **致命 1：默认开启的单调性守卫 + 启动自动导入 = 重启循环。** §3.5.3 让 `import_seed(..., guard="monotonic")` 默认在 `flag_removed > 0 or min_raised > 0` 时抛 `SeedGuardError`。`main.seed_check` 对 `import_seed` 没有任何捕获（§1.3-2），任何一次让守卫触发的种子都会让 `wd serve` 起不来并被 launchd 反复拉起。触发并不罕见：§6 的回滚路径「`wd import-seed --file <旧 vocab.jsonl.gz> --allow-regress`」只在 CLI 上存在，操作者若先 `git checkout` 回旧 `data/seed` 再重启服务，`seed_check` 看到哈希不同就自动导入旧种子 → 守卫抛错 → 循环；以后任何一次「去掉一个错标」的正常维护也一样。设计通篇没有提到 `seed_check`。
- **致命 2：守卫的语义自相矛盾。** 「修正错标」与「回退」在守卫眼里是同一件事，都要 `--allow-regress`。于是守卫要么被常态化绕过（失去意义），要么阻止正常维护。把它做成 `--dry-run` 报告里的计数（flag_removed/min_raised）而不是拒绝条件，才是它正确的形态。
- **致命 3：以 xs 秩 = 0 为前提。** I2 明写「假定 xs 的秩 = 0」，§3.6.3 的「`difficulty` 零代码」、`API.md:460` 不变、`push_batches.settings_json` 快照不变都建立在此之上。INDEX 矛盾 14 / A3 的结论是「= 0 并不比重编号便宜」：`screen.py:44`、`batches.py:272/698` 的 `int(x or DEFAULT_CURRENT_STAGE)` 把 0 当缺失（作者承认）、`schemas.py:65` 范围检查、`CHECK (current_stage BETWEEN 1 AND 4)`/`stage_min` 仍要整表重建。若阶段模型线选 1..5，本设计关于 difficulty 与排序的结论全部失效，且文中没有给出该情形下的替代论证。
- **致命 4（成员资格错位）：N5 把官方词头解析到原形。** L2 明列 `excited`，N5 规则把它落到 `excite(p)`，于是 `excite` 得到 xs/l2 记号而官方词头 `excited` 不成为词条；上海 12 个屈折形容词同理。另一边 N2「变体若不在库不新建」让 `yogurt`（L3、SH 都列）只给 `yoghurt` 打标。这不是「加法」，是把官方表改写成库内已有词的子集，与 A3「只用官方词头」的精神相反。作者把它列入风险（§7.1），但未量化对 `new_only`/`/api/stages` 的影响。
- 其他：272 个 `frq` 为空的词组进入 zk 使 `/api/vocab?stage=zk&new_only=1` 多 272 条排在末尾的条目（已说明）；`ecdict.py:28 STAGE_TAGS` 继续给自添词打 zk/gk 旧标签（与「legacy 不再作官方依据」不一致，设计只改了 `stage_min` 公式）。

**工作量与风险（6）**。7 人日可信（解析器改动最小，因为它把真实文件的括注当「防御性拆分」处理）。数据面是三份里最保守的（没有任何行失去旗标）；操作面因守卫引入新风险；phrase 路径虽存在（13 个）但从未在 272 条规模上验证。

**可维护性（5）**。旧记号 `zk/gk`（= mahavivo 表）与新记号 `l2 l3 sh2020 …` 并存，ECDICT zk/gk 标签继续定义成员（INDEX A1：旧考纲谱系）——两套口径永久混在同一列旗标里，将来任何「拓展层」都要从 `sources` 文本反推。`STAGE_RANK` 共享、manifest、`pack_seed.py`（Python gzip `mtime=0`，三份里最干净的可复现打包）是加分项。

**证据（8）**。`quant_output2.txt`/`extra_output.txt` 完整复现全部数字；引用 `FRONTEND.md:292`、`zh.test.ts:19-30`、`smoke.py:614`、`test_seed.py:113` 等都准确；`H2020 − H3100 = 100` 的词表与 official-purist 的 94 口径不同但各自有据。扣分：摘要的「前 300 个推荐词中拓展词为 0」是扣除附表后的口径，原始口径为 6，未在摘要标注。

**上线与回滚（5）**。步骤本身正确（停 → 备份 → 更新 → `migrate` → `--dry-run` → 导入 → 起 → 验证 → VACUUM），前端必须同次上线的提醒正确（`ScreenPage.tsx:31` 静默丢 xs 页签）。但守卫 × `seed_check` 的交互没有分析，回滚路径依赖操作者记得 `--allow-regress`。

**可嫁接**：`SeedPlan`（inserted/updated/flag_added/flag_removed/min_lowered/min_raised 计数与样例）作为 `--dry-run` **报告**；`--report` JSON；`stage_xs` 列前置检查；`scripts/pack_seed.py`；多词词头禁止去空格匹配；`sb./sth.` 句型模板标记跳过；「新种子对旧库的 I1 不变量」集成测试改写为「按预期变化」的回归测试；两位用户影响的量化方法（距离变化计数）。

### 2.3 data-engineering

**契合（7）**。A1–A3 采用；`gk := gk ∪ zk` 闭包（Q-a）是对 A2 的声明偏离，理由（国家表自身累计、上海高中生仍需这些词）成立，但使 `/api/stages` 的 gk `total` 与官方 3100 脱钩（official-purist 反对的正是这一点），且**331 个上海词组也随闭包进入 gk**——文稿未提。D9 词组入库与 INDEX B4 一致；D10 不做双方案/拓展与 A4 一致。

**正确性（7）**。
- 成立且是三份里最强的：D5 `retain`（上一版种子作输入，词只重标不消失）直接堵住「文件里删掉的词旗标永久残留」这个最先要堵的洞（本文确认导入器无 DELETE 路径）；D6 内容哈希作 `kv.seed_version`（消除 Mac gzip 伪重导，`seed-pipeline-7`）；构建器预测 `lemma` 并在导入时核对（`lemma_mismatch`），同 lemma 词头（`May/may`、`miss/Miss`——后者在已交付 level3 里确实同时存在）在构建期合并而不靠导入器「先到先得」（`seed.py:274-277`）；`stage_min = min(stage_to_index)` 与 Q1 三个选项解耦；`unknown_stage_codes` 计数告警替代静默丢弃；manifest `sha256` + `expect ± tolerance` + `--strict`；`--dry-run` 报告孤儿行。
- **致命 1：TSV 表头规则对已交付文件不成立。** §3.2.1「TSV 第一个非注释行是表头」——`moe-2022-appendix.tsv`、`shmeea-2020-junior-appendix.tsv`、`shmeea-2020-junior-forms.tsv` 的表头都是 `#` 注释行，第一条数据（`数词-基数词<TAB>one`）会被当表头吞掉且列名无从得知；两张 senior 表则有未注释表头。作者对 senior/shmeea 文件做了对账（§3.2.1 末），却没有发现这一点。需要 manifest 逐文件 `header: true|false` + 显式列索引 + 中文类别→阶段映射。`expect` 计数会在构建期抓到这类错误，所以是构建期失败而非线上错误。
- **致命 2：`aliases → word_forms(kind='alt')` 由种子写入。** 打破 `test_seed.py:352`/`TASKS.md` 验收的「`word_forms.kind ∈ p d i 3 s r t`」不变量与 DESIGN §3.1 对 `alt` 的「Claude/后缀规则」语义；`_rebuild_forms` 只删非 `alt` 行（`seed.py:222`），种子写的别名永不清理（作者承认「需要手动清理」）。把种子别名混进 `alt` 让「哪些 alt 是 Claude 合并产生的」不可追溯。应单独用一个新 `kind='alias'`（需 CHECK 迁移）或放进 `words` 的新列。
- **致命 3：对不在 ECDICT 的官方词头生成「最小记录」。** 32 个词组将以空短译进入词库页与筛词池；continuity §3.4.4 正确指出这类卡片没有任何可学内容且 `frq` 空会排到最后却仍出现在 `new_only`。`max_missing 0.5%` 的上限不改变单条记录的用户体验。
- 其他：「服务器运行时不导入 seedbuild」不准确（`cli.py:169-170` 逐个 import），无害；`kind` 覆盖放宽 DESIGN §3.2（已同步文档）；旧代码 + v2 种子的「无害」判断成立（未知键被 `rec.get` 忽略，`xs` 被过滤）。

**工作量与风险（4）**。14 人日（12–16）是三份最大：新包 7 个模块 + schema + 5 个新测试文件 + 两个 CLI + fixture `mini_stardict.sql`。风险由确定性测试、`expect`、`--strict`、孤儿报告摊薄；但 `cli.py`/`COMMAND_OWNERS`/`pyproject` package-data 三处同步、`test_cli.py` 自动覆盖，都是新的红灯面。

**可维护性（9）**。删除 `seed.py:43 STAGES`、`SEED_COLUMNS` 由 `STAGE_ORDER` 生成（去掉 10 份常量中的 1 份）；manifest 有 JSON schema；12 条规则表驱动测试；`seed-diff` 不依赖库与 `.env`；`content_sha256`；ATTRIBUTION 渲染；`stage_sources`/`list_levels` 为未来「拓展」或 `difficulty` 预留结构化数据而不加列。

**证据（7）**。预览数字来自 verify 解析件，噪声（`metr`、`caf`、`kung`/`fu`、未拆并列）已声明；与 INDEX §4.1 一致；两处「新核实」（release 库 tag 全集；`stardict.id` 与现种子 `ecdict_id` 逐一相同 → 可做字节级重建验收）有价值。对 live-copy 的交叉核对比 official-purist 少（例如没有逐词列出 249 个无阶段词的旧旗标分布）。

**上线与回滚（7）**。停 → 快照 → `migrate` → `--dry-run --report` → 导入 → 起 → 验证；回滚「只回退种子 + `--force`」因 retain ⊇ 旧而成立；代码回退到文件哈希语义只触发一次无害重导。缺：与其他两份一样不处理 `seed_check` 的自动导入；`kv.seed_version` 语义切换后升级首启必然导入一次（已说明）。

**可嫁接**：D5 `retain` + 孤儿报告；D6 内容哈希；lemma 一致性断言与构建期合并；manifest sha256/expect/tolerance/`--strict`；`stage_min = min(stage_to_index)`；`unknown_stage_codes` 告警；`stats.json.merged_heads/closure_added/retained_without_stage`；`mini_stardict.sql` 测试夹具思路；R9 词组归一（`…` → ` ... `、`(of)` 可选成分展开、`sb./sth.` 保留）。

---

## 3. 会变红的测试与契约（三份都应覆盖的清单，按本文核对）

| 门禁 | 位置 | 谁列了 |
|---|---|---|
| `test_seed.py` 阶段常量与无 NULL 断言 | `:93-98`、`:197/:204`、`:291-298`、`:338-353` | 三者 |
| `test_seed.py::test_dictionary_column_mapping` `sources` 字面量 | `:113` | continuity（official-purist 的 `sources` 词汇整体改写同样会红，未列） |
| `test_seed.py::test_gzip_and_plain_inputs_are_equivalent` | `:229-238` | data-engineering（内容哈希反转语义）、official-purist（作为可选项） |
| `test_api_schemas.py::test_stage_mapping_roundtrip` | `:33-39` | 三者 |
| `test_vocab.py` 4 行/`items[3]`/`stage_min == 4`/3694 | `:69-70, 75-76, 111, 232-234` | 三者 |
| `test_screen.py` `["be","a","go"]` 顺序 | `:133` | 三者（continuity 正确指出若 be/a 得 xs 则顺序变） |
| `test_content_apply.py` `go` 的中文阶段标签 | `:255` | 三者 |
| `test_words_resolve.py:478`、`test_reports.py:86-87` `stage_min == 2` | 重编号下红 | official-purist |
| `smoke.py` | `:352`、**`:614`** | continuity、data-engineering（official-purist 漏 `:614`） |
| `check_contract.py` 顺序敏感联合比对 | `:274-281` | 三者 |
| `zh.ts:86` ↔ `FRONTEND.md:292`（`check-copy.mjs`/`zh.test.ts`） | — | 三者 |
| `test_db.py::test_schema_file_is_byte_identical_to_docs_copy_when_present` | `:362-366` | 三者都正确地不动 `SCHEMA.sql`，新 DDL 进 0011 |
| `test_cli.py:51-58`（`COMMAND_OWNERS == CLI_MODULES`） | 新命令 | data-engineering |
| `test_seed.py:352` `word_forms.kind` 不变量 | 种子写 `alt` 会红 | data-engineering 只把它归入「验收数字待重写」，未点名 |

---

## 4. 评分表

| 维度 | official-purist | continuity | data-engineering |
|---|---|---|---|
| fit | 7 | 5 | 7 |
| correctness | 6 | 5 | 7 |
| effort_risk（高 = 工作量小风险低） | 6 | 6 | 4 |
| maintainability | 7 | 5 | 9 |
| evidence | 8 | 8 | 7 |
| rollout | 7 | 5 | 7 |
| **overall** | **7.0** | **5.3** | **7.3** |

排名：data-engineering > official-purist > continuity。前两名差距小：若产品方把「8 人日内上线」看得比「流水线可长期维护」重，official-purist 在补上解析层与 `difficulty` 决定后可以先行；但从迁移与数据安全角度，data-engineering 的 `retain`、内容哈希与 lemma 一致性断言是我不愿意放弃的三件事。

---

## 5. 给最终方案的建议（嫁接清单，按优先级）

1. **`seed_check` 防御（三者都缺）**：`main.seed_check` 捕获 `import_seed` 的异常 → 记 `system_events('seed_import_failed')` + 日志 → 继续启动；任何「拒绝导入」的逻辑只存在于 CLI 的显式调用，不在启动路径。
2. **data-engineering D5 + D6 + lemma 断言**：上一版种子作 `retain`；`kv.seed_version` 改内容哈希（同步 `main.seed_check`、`test_seed.py:234`）；构建器写 `lemma` 并由导入器核对。
3. **official-purist 的集合代数与不变量**：`xs = L2 ∪ A_num ∪ A_cal`、`zk = L3 ∪ A_* ∪ SH_w`、`gk = HS3100 ∪ HS3000`（闭包与否由 PO 在 Q-a 拍板；若闭包，词组是否随之进 gk 要显式决定）；`seed_diff.py` 的「新 lemma 集 ⊇ 旧、xs ⊆ zk、per_stage = stats」exit 1；`missing_policy.official: error`；`ecdict.py STAGE_TAGS` 只认 cet。
4. **解析层按已交付文件重写**（data-engineering R1–R3/R9 的函数 + 本文 §1.3-8 的事实）：manifest 逐文件 `header: true|false`、`head_column` 索引、中文类别 → 阶段映射、`a/an` 与 `a (an)` 两种写法都拆、`(AmE x)`/`(=x)`/`(x)` 三类括注分类、`pl.`/`am, is, are` 类不产生成员、`manner(s)`/`toward(s)` 展开。
5. **continuity 的 `SeedPlan` 作报告**：`--dry-run --report` 输出 flag_added/flag_removed/min_lowered/min_raised/orphans，**不**作拒绝条件；`PRAGMA table_info(words)` 含 `stage_xs` 的前置检查；`pack_seed.py`。
6. **`difficulty` 尺子在同一提交决定**（Q5）：若 Q1 选 1..5，至少把 `vocab.py:78` 改为 `COALESCE(w.difficulty, <stage_min 映射到 difficulty 尺>, 5)` 或明确接受错位并写进 `API.md §9.1`。
7. **别名不要混进 `word_forms.kind='alt'`**：用新 `kind='alias'`（0011 顺带改 CHECK）或单独列，保持 `alt` 的 Claude 合并语义与 `test_seed.py:352` 不变量可解释。
8. **无 ECDICT 条目的官方词头不生成空记录**：进 `overrides`（自写释义，≤10 个 + 词组 32 个）或 `member: false` 延后，不让空卡进入筛词池。
9. **排练一律走 `.venv/bin/python` 的 `run_migrations`**（`legacy_alter_table=1` 会掩盖 `v_bank` 问题，verify stage-model-13），排练后 `PRAGMA foreign_key_check`、`integrity_check`，并对 `user_words`/`word_contents`/`word_images`/`review_logs` 做 dump 前后字节对比（official-purist §5.4 的验收口径）。
