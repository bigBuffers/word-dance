# 词表来源与种子流水线 · 评审（角度：维护者怀疑者）

日期 2026-11-06 · 基线 `main @ 75df534` · 评审对象：`design/word-lists/{official-purist,continuity,data-engineering}.md` · 评审者只读仓库，未改任何代码。

评审口径：盯住契约镜像负担（`types.ts` / `API.md §9` / `FRONTEND.md §8` / `check_contract.py` / `CLAUDE_INTEGRATION §4.1` / `SCHEMA.sql` 字节一致）、硬编码是否真的减少、测试与文档改动量是否被低估、工作量是否诚实、实现时最容易出错的地方。**默认每个未被证明的说法都是错的**；下文每条结论标依据（`文件:行` 按 75df534；`[INDEX x]`、`[verify slug-N]` 指本目录调研文件；「实测」= 我在 `python3 -I` 下对 `data/lists/`、`scratchpad/live-copy.db`（只读）与三位设计者留下的脚本输出重新核对）。

---

## 0. 一页结论

| 排名 | 设计 | overall | 一句话 |
|---|---|---|---|
| 1 | official-purist | **7.0** | 阶段成员的集合代数最忠于 A1–A3、量化最完整（转移矩阵、用户影响逐词核过）；代价是把 9,162 行的 `sources` 词汇整体改名（每行都重写）、`is/are/does` 等 243 词变成无阶段词典词、manifest/解析层按「产出流水线已预拆并列」设计而交付文件并没有拆；8 人日偏乐观。 |
| 2 | data-engineering | **6.7** | 唯一把构建器做成可单元测试、字节可复现的包，`retain` 上一版种子 + 内容哈希 + `--dry-run` 是维护者真正想要的骨架；但 manifest 自相矛盾（词组 `expect: 331` vs 自己正文 342）、`gk ⊇ zk` 闭包偏离 A2、`is/are/does` 失去阶段**未披露**、括注文法与交付记法不匹配、manifest 里的 `stage_rank` 又多了一份阶段顺序副本；14 人日是三份里最诚实的估算。 |
| 3 | continuity | **5.9** | 上线/回滚故事最好（旧代码容忍新种子、`--allow-regress`）、`sources` 不改名；但产品契合最弱（初中 16.2% / 高中 24.2% 超纲词保留且第一期无任何 UI 标记）、单调性守卫默认开在 `import_seed` 里而 `main.startup → seed_check` 没有任何 try/except（`main.py:477-495`）——未来任何一次纠错种子都会让 `wd serve` 启动失败进重启循环；依赖「xs 秩 = 0」却把三处 `or DEFAULT_CURRENT_STAGE` 陷阱推给别的切片。 |

**三份设计共有、必须在实现前修掉的问题**（§1）：① 都按「产出流水线会预拆并列、把括注放进独立列」设计，而 2026-11-06 00:02 已落地的 `data/lists/` 明确「拆分、去括号、大小写归一都留给种子阶段」；② 都采用了 INDEX 的「331 个词组」，而交付文件与其 README 已裁决为 **342**（331 是换页符伪影）；③ 两份「官方纯净」路线都让 `is / are / does` 变成无阶段词；④ 两份在 manifest 里又写了一份阶段顺序（`stage_order` / `stage_rank`），`check_contract.py` 管不到它。

---

## 1. 引用抽查（每份 ≥ 10 处）与三份共有的事实问题

### 1.1 代码/文档引用抽查结果

| 引用 | 出现在 | 核验 |
|---|---|---|
| `seed.py:43 STAGES`、`:47-68 SEED_COLUMNS`（20 列）、`:72-82 _UPSERT_SQL`、`:184-185` 未知阶段码静默丢弃、`:208 stage_min = STAGES.index(stages[0]) + 1`、`:218-245 _rebuild_forms`、`:239-241` 表头词守卫、`:258/:287 sha256_file → kv.seed_version`、`:333-360` CLI | 三份 | **全部属实** |
| `schemas.py:25-26 Stage/StageIndex`、`:47 Difficulty`、`:51-52`、`:56-67`（`:65` 越界抛 `ValueError`）、`:472 stage_min: StageIndex | None`、`:488/:708/:1335` 请求字面量 | 三份 | 属实 |
| `build_seed.py:16 RICH_RE`、`:25 len(line)==1`、`:96-100 lookup`、`:102-109` 收全部 zk/gk/cet 标签行、`:112-127`、`:128-142 cet46`、`:144-147`、`:150-151 order`、`:157-171 stats`、`:176-177/:201-219 ATTRIBUTION`、`:180-198 make_record`；文件共 222 行 | 三份 | 属实 |
| `services/ecdict.py:28 STAGE_TAGS`、`:118-119 stages`、`:173-177 word_columns`（`:177` 同一公式） | 三份 | 属实 |
| `services/words.py:39 STAGES`、`:69-87 _CHAR_MAP`、`:88 _STRIP_PUNCT`、`:91 _ACRONYM_RE`、`:143-151 derive_kind`、`:174-175` 点号 token ≤ 6、`:183-189 normalise_lemma`、`:576-580 _word_defaults`、`:589-597 _INSERT_WORD_SQL` | 三份 | 属实 |
| `routers/vocab.py:40-43` 词形前缀搜索、`:52-56` 阶段筛选、`:78 COALESCE(difficulty, stage_min, 5)`、`:86-98 /api/stages` 按 `STAGE_ORDER` 迭代 | 三份 | 属实 |
| `screen.py:44`、`batches.py:272,698` 的 `int(x or bank.DEFAULT_CURRENT_STAGE)`；`screen.py:51-55`、`batches.py:232-234` 旗标 OR（按 `words.STAGES` 过滤）；`bank.py:85-86 DEFAULT_STAGES/DEFAULT_CURRENT_STAGE`、`:181` | continuity、official-purist | 属实（真实路径是 `backend/wd/services/{screen,batches,bank}.py`，任务书里的 `ai/` 前缀不对，设计文稿只写文件名，无误） |
| `ai/prewarm.py:32-33,37-38`；`ai/content.py:48 AUDIENCE`、`:49 STAGE_ZH`、`:88 STAGE_ZH[s]`（`KeyError` 风险）、`:90-91 kind`、`:183-184` lemma 回退 | 三份 | 属实 |
| `main.py:307-319 seed_check`（文件 sha256）；`:482-485` 先 `run_migrations` 再 `seed_check` | 三份 | 属实；**补充**：`startup()`（`:477-495`）对 `seed_check` 无任何异常处理，见 §3 continuity 致命缺陷 1 |
| `0001_init.sql:147-148`（默认 `["cet4","cet6"]` / `current_stage 3 CHECK 1..4`）、`:181-186`（旗标注释「cumulative」、`stage_min CHECK 1..4`、「cet6: 3,694 words」）、`:188 sources` 示例、`:205 ux_words_lemma`、`:219-225 word_forms`（`:222 alt = Claude/suffix rule`）、`:266 score` | 三份 | 属实 |
| `scripts/check_contract.py:274-281` 字面量联合顺序敏感比对 | 三份 | 属实（`py_values != values` 列表比较） |
| `scripts/pack_seed.sh:12`「kept verbatim」、`:44-47 total_words`、`:62/68/79/90 zcat`、`:63/84/90 sha256sum`、`:78 gzip -9 -n`、`:90 stat -c %s`；`Makefile:37-40, 93-98`（`:95` 提示文字、`:96` 调用、`:97-98 gzip/zcat`） | 三份 | 属实 |
| 测试：`test_seed.py:61,63,64,73`（60 条）、`:86`（`I` 故意不在夹具）、`:93-98`、`:113`（`"cet4 ecdict zk"`）、`:171-187`、`:197/:204`、`:229-238`（`:234/:237` gz≠plain 语义）、`:291-298`、`:339-353`（`:343-346` 验收数、`:346 phrase == 13`、`:348`、`:352`）；`test_api_schemas.py:32-39`；`test_vocab.py:69-70,75-76,93,99,111,232-234`；`test_screen.py:129-134`；`test_batches.py:127`；`test_content_apply.py:255`；`test_words_resolve.py:478`；`test_reports.py:86-87`；`test_db.py:13-17,51,362-366`；`test_cli.py:50-58`；`conftest.py:203-209` | 三份 | 属实 |
| `cli.py:31-42 CLI_MODULES`、`:45-56 COMMAND_OWNERS`；`pyproject.toml:26-28` package-data；`backend/requirements.txt:9 jsonschema>=4.18,<5` | data-engineering | 属实（`jsonschema` 确是运行依赖，不只在 dev 文件里） |
| `zh.ts:86 sources.lists`；`FRONTEND.md:209`（§8）与 `:292` 镜像行；`zh.test.ts:19-30` 读 `docs/FRONTEND.md`；`check-copy.mjs` | 三份 | 属实 |
| `API.md:167`「4 rows」、`:169` 3,694、`:239-240`、`:459-460`；`DESIGN.md:186, 193-209（:202 stage_min 定义、:206 kind derived、:209 验收数）, 321-322`；`TASKS.md:160-180`（`:162`「keep verbatim unless a bug is proven」、`:172-175`）；`DEPLOY.md:304, 407, 413, 417`；根 `ATTRIBUTION.md:14, 19-32`；`data/seed/ATTRIBUTION.md:12-13`；`README.md:5, 9, 78, 103` | 三份 | 属实 |
| `backup.py:283-296 snapshot_before_migrate`；`WelcomePage.tsx:35`（gk 预设 `['zk','gk']`）；`ScreenPage.tsx:31` 丢未知阶段；`VocabPage.tsx:29, 202`；`types.ts:5-6, 45, 73`；`security.py:613`；`smoke.py:352, 614`；`deploy/fetch_ecdict.sh:23 df --output` | 三份 | 属实 |
| `install.sh:140-141`（migrate → import-seed） | official-purist | 属实 |
| `install.sh:168-169`（同一顺序） | data-engineering | **错误**：`:168-169` 是 Caddy 反向代理段；正确行号是 `:140-141` |
| 「只有 `test_seed.py:93-97` 与 `:338-353` 依赖 Q1」 | data-engineering §7.1 | **不完整**：若 Q1 选重编号，`test_words_resolve.py:478`、`test_reports.py:86-87`（`stage_min == 2`）、`test_vocab.py:111`（`== 4`）同样变红（official-purist §5.1 列全了） |
| 调研条目 [verify list-sources-7]（RICH_RE 丢 7 行、`best`/`less`/`cafe`）、[verify shanghai-secondary O5/O6/O8、-19（真缺 14）、-7、-9]、[verify provinces-3/4/12/13/24/25]、[verify shanghai-primary-21]、[seed-pipeline-2/7/8/9/10/12/13/14/15/20/21/22/27/31]、[stage-model-4/12/13/15/17/19/20]、[verify stage-model-1/-13/遗漏]、[verify seed-pipeline-4/O2/O3/O5]、[frontend-stages-22/23] | 三份 | 条目存在且首句与引用含义一致 |
| 三位设计者的复算脚本与输出：`scratchpad/word-lists-official-purist/{final.py,final.json}`、`word-lists-continuity/{quant.py,extra.py,quant_output2.txt,extra_output.txt}`、`word-lists-data-eng/{preview.py,closure.py,richre.py,preview_out.json}` | 三份 | 存在；关键数字与正文一致（official-purist：XS 594 / ZK 2,194 / GK 3,253 / 无阶段 243 / 新词 112；continuity：505 / 2,520 / 4,297 / 下移 1,269 / 超纲 20.1% 25.4% / `zk−gk` 94；data-engineering：无阶段 249、缺词清单）。一处表述问题见 §3 continuity 缺陷 3 |

### 1.2 三份设计共同踩到的事实坑（以交付的 `data/lists/` 为准，实测 2026-11-06）

1. **交付文件不拆并列、不剥括注，与三份设计的前提相反。** `moe-2022-level2.txt` 505 行里 24 行带括注/斜杠（`a/an`、`be (am, is, are)`、`colour (AmE color)`、`maths (=mathematics, AmE math)`、`mother (mum AmE mom)`、`child (pl. children)`、`Mr (AmE Mr.)`、`PE (=physical education)`）；`level3` 69 行；`shmeea-2020-junior.txt` 1,724 行，其中 `/` 5 行、`=` 3 行、括注 10 行（`A.M. (a.m.)`、`manner(s)`、`toward(s)`、`bund (the Bund)`、`phone (=telephone)`…）；`shmeea-2020-junior.README.md:55,128` 明写「并列不拆…由种子构建阶段决定拆分规则」「拆分、去括号、大小写归一都留给种子阶段」。official-purist 假设「`a/an` 一类并列拆成两行、括注进 `variants` 列」（§3.2.1），continuity 假设「由产出流水线预先拆成两行，`alt` 列互指」（§3.2，有防御性拆分兜底），data-engineering 设计了 `split_head/classify_note`（R2/R3）但其文法以 `colour (color)`、`exam (=examination)` 为样例——对交付记法 `(AmE color)`、`(=mathematics, AmE math)`（R2① 遇逗号整体丢弃→丢掉 `math`）、`(mum AmE mom)`、`(pl. children)` 都不成立。**这是三份设计实现时最容易出错的一点**：没有任何一份的解析层能直接吃交付文件。
2. **词组数 331 是错的，交付为 342。** 三份都采用 INDEX「1,731 + 331」（official-purist README 表与 manifest；continuity `declared_count: 331`；data-engineering manifest `expect: 331` 无 tolerance）。`shmeea-2020-junior-phrases.txt` 342 行，其 README §7.4 已裁决「331 = 顶格以字母开头的行，词组区后 11 页首行以 `\f` 开头被漏数，以 342 为准」，并明确建议把 INDEX §6.2 第 3 条改为「1,731（或 1,724 行）+ 342」。data-engineering 自己的 §1.2 还写着「342 个抽取词头中 310 在 ECDICT」——与其 manifest 自相矛盾。
3. **单词表行数 1,724 vs 1,731。** 1,731 只有在拆开 5 条 `/` 与 3 条 `=` 之后才成立（1,724 + 5 + 3 = 1,732，README §6）。data-engineering `expect 1731, tolerance 5` 没有说明是数原始行还是拆分后词头；official-purist 的 `parse_official` 用文件自带 `# count` 校验（自洽），但其 README/manifest 写死 1731；continuity 的 `declared_vs_parsed` 必须一致才允许提交，拆分后能对上。
4. **附表的真实形状与三份 manifest 都不同。** `moe-2022-appendix.tsv` 267 行、4 列 `类别/词/附加1/附加2`，类别是中文（数词-基数词 30、数词-序数词 28、月份 12、星期 7、地理名称 27、地理名称-派生 18、缩写 7、节日 13、地名景点 8、其他专有名词 11、**不规则动词 106**），词头列含两处消歧中文 `hang (悬挂)`、`lie (躺)`。official-purist 预期 165 行、5 个英文 group，无「不规则动词」排除规则（按其 `stages_by_group` 兜底逻辑，106 个屈折形式要么成为 zk 成员要么让构建失败）；continuity 的 `stage_by_group` 只有 numeral/month/weekday/country/holiday；data-engineering 有 `exclude_groups: ["irregular_verb"]` 和 `head_column`，最接近，但它「词头列遇到 CJK 直接报错」的规则会被 `hang (悬挂)` 触发，除非排除先于校验（文稿未定顺序）。
5. **`is / are / does` 在两份「官方纯净」路线里都失去全部阶段**（实测 `final.json.stageless` 与 `preview_out.json.nostage` 都含这三个词）。原因相同：官方表只列 `be (am, is, are)`、`do (did, done)` 的括注，三份都把括注里的屈折当「不建成员」，而 `is/are/does` 在库里是独立 lemma（表头词守卫 `seed.py:239-241` 使 `is→be` 不会进 `word_forms`）。对一个面向小学生的产品，「小学」页签里没有 `is` 是肉眼可见的回退。official-purist 在 §7.1 承认并「不建议」修；data-engineering **完全没有提到**；continuity 因为是加法不受影响。
6. **manifest 里又多了一份阶段顺序。** official-purist `"stage_order": ["xs","zk","gk","cet4","cet6"]`、data-engineering `"stage_rank": [...]`——这是 `schemas.STAGE_ORDER` 之外的第 11 份副本（[verify stage-model-1] 数的 10 份都在 Python/TS 里，`check_contract.py` 还能比对；JSON 文件里的这份谁来比对？两份都没有列出「manifest 顺序 == `schemas.STAGE_ORDER`」的测试）。continuity 反而写明「秩值不在此文件；种子只写 `stages[]` 码」。
7. **`seed.py` 改用 `schemas.STAGE_ORDER` 的前提**：`seed.py:36-39` 今天不 import `schemas`；加上没有循环依赖（`schemas.py` 只 import `.clock`），可行，三份都没有核过这一点但结论成立。
8. **`push_batches.settings_json`** 只在 `batches.py:316` 写入、无读取者，所以重编号不会破坏代码（continuity 把它当成「xs=0 更好」的论据之一，论据成立但分量很轻）。

---

## 2. 维度评分

| 维度 | official-purist | continuity | data-engineering |
|---|---|---|---|
| fit（上海 K-12 + 现有用户） | **8** 阶段 = 官方词头；小学含数词/月份；上海表并入 zk；cet 原样。扣分：243 词无阶段（含 `is/are/does`） | **5** zk 16.2% / gk 24.2% 超纲词保留且第一期无 UI 标记；227 个既无官方也无 CET 归属的词（`abortion/bungalow/yummy` 一类）继续当「高中词」 | **7** 同 official-purist 的官方口径 + 词组入库；`gk ⊇ zk` 闭包对上海高中生合理但偏离 A2；`is/are/does` 失阶段未披露 |
| correctness（迁移/数据/契约） | **7** 量化最完整，接口要求（`_word_defaults`/`_INSERT_WORD_SQL`/`word_columns` 必须输出 `stage_xs`）写全；`sources` 改名使 9,162 行全部重写；manifest/解析层与交付文件不符（§1.2 1/2/4） | **6** 解析顺序与「多词禁止去空格」规则细致；但守卫默认开在 `import_seed` 内（§3）、xs=0 的三处陷阱外推、`pack_seed.py` 的 zlib 跨平台一致性说法不成立 | **7** 确定性与 lemma 预测/校验最严；但 manifest 自相矛盾、`max_missing 0.5%` 对词组（32/342 = 9.4%）必然失败、CJK 规则与交付附表冲突、一处错误行号 |
| effort_risk（高 = 工作量小风险低） | **5** 自报 8 人日，我估 10–12（并列/括注文法、`--previous` 回填、dry-run 20 列比对、`test_build_seed` 需 `sys.path`/importlib 载入 `scripts/`）；风险：全行重写、无阶段词 | **6** 自报 7（6–8），我估 ≈10（`plan()`、守卫、`seed_diff --db`、I1 集成测试、3 组新测试）；数据风险最低（加法），运维风险见守卫 | **4** 自报 14（12–16），可信；但 7 个新模块 + 2 条 CLI + schema + 5 个测试文件是三份里最大的改动面 |
| maintainability（硬编码/镜像是否减少） | **6** `build_seed` 常量→manifest（-1）；`seed.py STAGES` 元组仍是镜像；新增 `manifest.json/aliases.tsv/overrides.jsonl/retired-allowlist.txt` 4 个人工文件 + manifest `stage_order` 副本；`hs_level/variant_of` 暂无消费者 | **5** `seed.py:43` → 共享秩表（-1）；`sources` 不改名（最小扰动）；但永久保留 `$WORDLISTS_DIR` 的 6 个 mahavivo 文件（含 2 个「来源不明」表）作成员输入，构建永远不能离开它们；第二期 `core_min` 列 = 又一次 `WordBrief` 契约变更 | **7** `STAGES` 删除、`SEED_COLUMNS` 从 `STAGE_ORDER` 生成（-1）；纯函数 + 表驱动测试是真正的可维护性提升；但新增 `manifest.schema.json ↔ manifest.py`、manifest `stage_rank`、`kind`/`aliases` 导入语义（DESIGN §3.2 放宽）、`alt` 词形语义重载（`0001_init.sql:222` 注释改不了，SCHEMA.sql 要字节一致） |
| evidence（与调研一致） | **9** 引用 ≥ 25 处全部属实；`final.py` 可复跑；对 INDEX 未解决 6 给了实测（release tag 全集 = csv 8 值） | **8** 数字全部能在 `quant_output2.txt` 找到；一处把「扣除体例差异后」的 top-N 序列（`:124-128`：拓展 0/0/0/5/30）当作主结论而未标注，原始序列是 0/1/6/16/47（`:55-59`） | **8** 两项新核实（release tag 全集；`stardict.id` 与种子 `ecdict_id` 逐一相同 → 可复现基线）有价值；`install.sh:168-169` 引错；「只有两处测试依赖 Q1」不完整 |
| rollout（上线顺序与回滚） | **6** 8 步 Mac 运行手册完整，dry-run 作为检查点；回滚只有「快照 + 代码一起回」；首次导入 9,162 行全部 update（diff 噪声大、卡片缓存全失效） | **6** 旧代码容忍新种子、新代码容忍旧种子 → 可分步上线；`--allow-regress` 回退种子；但守卫在 `seed_check` 路径上是启动炸弹（§3） | **7** `retain` 保证新种子 ⊇ 旧种子 → 仅回退种子文件即可（`git checkout -- … && import-seed --force`）；内容哈希使 Mac 重打包不再伪重导；对 Q1 的顺序依赖写得明确 |
| **overall** | **7.0** | **5.9** | **6.7** |

---

## 3. 逐份评审

### 3.1 official-purist

**致命/重大缺陷**（会导致线上错误、契约/测试问题，或违反假设而未说明）

1. **243 个词变成无阶段词典词，其中有 `is`、`are`、`does`**（实测 `final.json.stageless`）。小学生在「小学」页签看不到 `is`。设计在 §7.1 披露并给出「`aliases` 继承」的替代方案却标「不建议」。这不是「官方纯净」的必然结果——`moe-2022-appendix.tsv` 的「不规则动词」106 行就是官方给出的 `be/do/have` 屈折清单，可以作为 `member` 规则的输入。
2. **`sources` 词汇整体改名**（`zk`→`legacy-zk`、`cet4`→`ecdict-cet4`…）导致导入时 **9,162 行全部 UPDATE**（§3.5、§6 第 4 步自己也写了），`updated_at` 全库刷新、`/media/card` LRU 全失效、首次 `DIFF.md`/`system_events` 没有信噪比。`sources` 没有任何读取者（[stage-model-15]，实测 `schemas.py`/`API.md` 不含 `sources`），所以无契约风险，但这是纯粹的自找扰动；continuity 的「现有记号一个都不改名，只加新记号」显然更好。
3. **解析层按「产出流水线已预拆、变体在第 2 列」设计**（§3.2.1 行格式、§3.3 规则 1/2 的「产出流水线把 `/`、`=` 拆成两行」），交付文件没有做这件事（§1.2-1）。`parse_official` 文稿里只有「读头注释、按 `\t` 取列、`variants` 逗号拆分、校验 `# count`」，没有括注/斜杠/等号文法；配上 `missing_policy.official: error`，第一次构建会在 `although/though`、`be (am, is, are)`、`colour (AmE color)` 上直接失败——失败是响亮的（好），但文法与测试都没设计，工作量也没算。
4. **manifest 与交付文件的形状不符**：`moe-2022-appendix.tsv` 的 `columns: ["word","group"]` 与 5 个英文 group（§3.2.3）对不上中文类别列在前、词在后的 4 列 TSV，且没有「不规则动词」的排除规则；词组 331 vs 342（§1.2-2/4）。设计写了「若实际文件的列与本文不同，改 manifest 的 `columns`，不改构建代码」——对列顺序成立，对「中文 group 值」「要排除的 group」「词头列含 `(悬挂)`」不成立。
5. **manifest `stage_order` 是第 11 份阶段顺序副本**，而 `seed.py:43 STAGES` 元组依旧保留并扩展（§3.5「改 `STAGES` → 五元组」）——硬编码没有减少，只是从 10 份变成 10 份 + 1 份 JSON。
6. **工作量 8 人日偏乐观**（我估 10–12）：§7.3 把「`build_seed.py` 重构 + manifest/aliases/overrides + `seed_diff.py` + `pack_seed.sh` 可移植」算 3 天，没有包含 §1.2-1 的文法、`--previous` 用 ECDICT 当前条目「重建记录」的路径、`test_build_seed.py` 直接 import `scripts/build_seed.py` 需要的 `sys.path`/`importlib` 处理（continuity 注意到了）。

**次要问题**：§3.3 规则 8 让 `the great wall`、`spring festival` 走 `derive_kind` 成为 `kind='phrase'`（专名当词组）；新增 `variant_of`/`hs_level` 两个字段进种子却没有消费者（典型的「先埋字段」）；`kv.seed_format`/`kv.seed_stats` 新 kv 键未列入 DESIGN.md:184 的 kv 清单。

**值得嫁接**

- 阶段成员的显式集合代数与记号表（§3.1.1–3.1.2），特别是 `gk = HS3100 ∪ HS3000`（显式并集而非「含」），避免 2025 版挪进附录的 94 个月份/数词/国籍词掉出高中层（continuity 的 `extra_output.txt` 也独立复算出 H2020−H3100 = 100）。
- 不做人为闭包，保留 `zk=1, gk=0` 的 198 个上海独有词，用「阶段预设」而不是数据闭包解决用户体验（§3.1.3）。
- 变体（`colour/color`、`maths/math`）各自成行、同阶段、`variant_of` 互链；不合并、不进 `word_forms`（表头词守卫会拒绝）。
- 附表按 `group → stages` 分配（数词/月份星期 → xs+zk；地理/机构/文化 → zk）；2025 国家附表 `member: false`。
- `overrides.jsonl` 处理 ECDICT 错义项（`bund`「政治同盟」、`mum`「菊花」、`PE`「相位编码」、`bce/ce`），并且「官方词缺失即构建失败」而不是静默进 `missing_from_ecdict`。
- `seed_diff.py` 的不变量检查（`新 lemma 集 ⊇ 旧 lemma 集` 除非在 `retired-allowlist.txt`、`xs ⊆ zk`、`per_stage` 与 `stats.json` 一致）与 `stage_min` 转移矩阵作为标准评审产物；`retired-allowlist.txt` 与 `WORD_LIBRARY_CURATION.md §2.4 阶段 C` 的 `retired.jsonl`（下架随种子传播）方向一致。
- §3.1.4 对阶段模型线的接口清单（`services/words.py:576-580,589-597`、`services/ecdict.py:173-177` 必须输出 `stage_xs`；`ecdict.py:28 STAGE_TAGS` 改只认 cet）。
- §5.2 夹具「最小改动」原则：不按新种子重标 gk，避免 `test_screen.py:130`、`test_batches.py:127` 的排序断言连锁。
- §6 的 Mac/launchd 运行手册（手工 `wd backup` → `bootout` → `migrate --dry-run` → `migrate` → `import-seed --dry-run` → `import-seed` → `kickstart` → 7 项验证）。

### 3.2 continuity

**致命/重大缺陷**

1. **单调性守卫默认开在 `import_seed` 内部，会炸在服务启动路径上。** §3.5.3：`import_seed(..., guard="monotonic")`（默认）在 `flag_removed > 0 or min_raised > 0` 时抛 `SeedGuardError`。`main.startup()`（`main.py:477-495`）直接调用 `seed_check(conn, cfg)`，没有 try/except；`seed_check` 只要 `kv.seed_version` 与文件 sha256 不同就调用 `import_seed`（`main.py:313-317`）。于是**未来任何一次纠错种子**（哪怕只是把一个错标的 `zk` 旗标去掉）通过 `git pull` + 重启上线，`wd serve` 会在每次启动时抛异常退出，launchd 进入重启循环，直到有人手工 `wd import-seed --allow-regress`（而 `kv.seed_version` 在抛出前不会更新，所以每次启动都重试）。`WORD_LIBRARY_CURATION.md §1.2` 已经记录了「`seed_check` 对损坏的种子文件不做防御，会让服务启动失败并进入重启循环」，这个设计把同类炸弹从「文件损坏」扩大到「任何回退旗标的合法修正」。守卫应当只是 `--dry-run` 报告里的一行警告，或仅在 CLI 显式 `--guard` 时抛出，绝不能进 `seed_check`。
2. **依赖「xs 秩 = 0」却把它的代价外推。** §3.1 I2 明说「本设计假定 `xs` 的秩 = 0」，并承认 `screen.py:44`、`batches.py:272,698` 的 `int(x or bank.DEFAULT_CURRENT_STAGE)` 会把 0 当缺失（实测三处都如此）→ 主攻小学的用户推荐词按 cet4 排；`schemas.py:65` 的 `1 <= index <= 4` 也要改。INDEX 矛盾 14 已裁定「两案都不便宜」。选择秩 0 是这份设计做的，代价不能只写「本切片不受影响」。
3. **产品契合与「超纲比例」论证的口径问题。** zk 2,520 中 409 个（16.2%）、gk 4,297 中 1,042 个（24.2%）不在任何官方表；227 个既无官方也无 CET 归属的旧「高考 3500」词留在 gk。第一期「拓展」只是统计口径（§1 结论 2），词库页、「仅本阶段新增」、推荐词都看不出区别。§3.6.3「前 50/100/300 个候选里拓展词 0/0/0」取自 `quant_output2.txt:124-128` 的「adj」（扣除附表与美式拼写）序列，正文没有标注；原始序列（`:55-59`）是 0/1/6/16/47，「不在上海表」是 14/23/34/61/130 而非 3/5/10/28/88。结论方向仍成立（拓展词集中在词频尾部），但数字呈现有选择性。
4. **`WORDLISTS_DIR` 的 6 个 mahavivo 文件（含两张「来源不明」表）成为永久成员输入。** A3 的偏离已声明（「部分偏离」），但维护后果没有写：构建永远不能脱离这两个无 LICENSE、README 一字未提的文件（[list-sources-4]），`ATTRIBUTION.md` 要永远解释「legacy 成员来源」，而官方件就在仓库里。
5. **`pack_seed.py` 的可复现性说法过强。** §3.4.7「Python `gzip.GzipFile(mtime=0, compresslevel=9)`（zlib，跨平台同版本字节一致）」——只在同一 zlib 构建下成立（Homebrew Python 与 Linux 发行版的 zlib/zlib-ng 可以不同），而 `kv.seed_version` 仍是 `.gz` 文件哈希（§3.5.4「语义不变」），`jsonl_sha256` 只写进 `stats.json`。[seed-pipeline-7] 的 Mac 伪重导问题实际上没有被解决，只是换了一个压缩实现。
6. **N5 把 `excited/lost/frozen/united` 落到原形**，L2 自己的词头 `excited` 得不到行（§3.3 N5、§7.1 已承认）；这与 A1「L2 = 505 个词头」的字面含义相悖——official-purist/data-engineering 都为这些分词形容词建行（ECDICT 有独立条目）。
7. **工作量 7 人日（6–8）偏乐观**（我估 ≈10）：`plan()` 对 20 列的比较、`SeedGuardError`/`--allow-regress`、`seed_diff --db` 模式、I1 集成测试、「旧代码读新种子」回归、3 组新测试、`pack_seed.py` 重写，1.5 + 1.0 天装不下。

**次要问题**：N4 要改 `mrs.`→`Mrs.` 的 display，而 DESIGN §3.2:197 写「keeps ECDICT casing」——需同步文档；`xs ⊆ zk` 由 `L2 ⊆ L3` 保证的论证不覆盖「附表入 xs」的 ≈65 个词（16 个序数词不在库、新建后若上海附表没有同名词就只在 xs），没有构建期断言；manifest 里 `"$WORDLISTS_DIR/..."` 这种 shell 变量写法要在构建器里自己展开。

**值得嫁接**

- **`sources` 现有记号一个都不改名，只追加新记号**（`l2 l3 sh2020 hs2020 hs2025 …`）——把导入扰动从 9,162 行降到真正变化的行。
- 共享秩表：`stage_min = min(stage_to_index(s) for s in stages)` 同时替换 `seed.py:208` 与 `ecdict.py:177`；种子只含 `stages[]` 码，与 Q1 解耦。
- 「旧代码遇到新种子静默忽略 `xs`（`seed.py:184-185`），新代码遇到旧种子正常」固定成回归测试 → 可分步上线。
- `wd import-seed --dry-run` 的 `plan()` 报告字段（`inserted/updated/flag_added/flag_removed/min_lowered/min_raised/display_changed/translation_changed` + 样例）；`--allow-regress` 这个命名；但守卫只作报告。
- 解析顺序「精确 → 拼写/书写变体 → 屈折（`word_forms`）→ 人工覆盖 → ECDICT 新记录 → 失败」与 `stats.json.resolution` 逐表记录命中方式。
- **多词词头禁止「去空格」匹配**（`break down ≠ breakdown`、`take off ≠ takeoff`，5 个假阳性实测），只允许空格↔连字符。
- `declared_vs_parsed` 必须一致才允许提交；`seed_diff` 输出追加到 `data/seed/CHANGES.md`。
- 对两位线上用户的影响量化到「推荐词距离」层面（§3.6.4），发布说明素材。

### 3.3 data-engineering

**致命/重大缺陷**

1. **manifest 自相矛盾、首轮构建必失败。** `shmeea2020_phr` `expect: 331`（无 tolerance）vs 正文 §1.2「342 个抽取词头」与交付文件 342 行；`shmeea2020` `expect 1731, tolerance 5` 对交付的 1,724 原始行只有拆开并列后才成立，而「`expect` 数原始行还是数拆分后词头」没有定义。`--strict` 的 `max_missing` 默认 0.5% 对词组（32/342 = 9.4% 不在 ECDICT，自己的预览数字）必然失败，manifest 没有为该表放宽。
2. **`gk := gk ∪ zk` 闭包偏离 A2**（已作为 Q-a 声明）：高中层多出 ≈150 个上海初中独有词（派生副词、`bund`、`hot dog`…），`/api/stages` 的 gk `total` 不再对应官方 3100；对上海高中生「它仍是必备词」的论证成立，但对全国高中生它是把上海初中口语词塞进高中表。既然 `sources` 已逐词记录，这一步应该是展示层/预设的事（official-purist §3.1.3 的做法）。
3. **`is / are / does` 失去全部阶段且未披露**（实测 `preview_out.json.nostage` 含 `are`；正文只举 `airmail, armchair, bathtub, bookcase, bungalow, cd-rom …`）。A1 的附表里「不规则动词」被 `exclude_groups` 整组排除（§2「它们是屈折形式，走 `word_forms`」）——但 `is/are/does` 是独立 lemma，表头词守卫让它们永远进不了 `word_forms`，结果就是从所有阶段消失。
4. **R2 括注文法与交付记法不匹配**（§1.2-1）：`colour (AmE color)`、`maths (=mathematics, AmE math)`、`mother (mum AmE mom)`、`child (pl. children)`、`Mr (AmE Mr.)`。按 R2 的四类：① 「含逗号分隔多项→丢弃」会丢掉 `=mathematics, AmE math`；③ 「单个字母串」不匹配 `AmE color`；结果大部分变体落到 ④ `unparsed` → `--strict` 失败或 ≈60 条人工 overrides。另外「词头列遇到 CJK 直接报错」与交付附表词头列的 `hang (悬挂)`、`lie (躺)` 冲突，除非 `exclude_groups` 先于校验执行（文稿未定）。
5. **manifest `stage_rank` 是新的阶段顺序副本**：构建器用 `manifest.stage_rank`，导入器用 `schemas.STAGE_ORDER`（§2「对 Q1 的依赖」），两个事实来源、没有列出相等性测试；`check_contract.py` 不比对 JSON 文件。同时 `manifest.schema.json ↔ manifest.py` dataclass 是又一对需要同步的镜像。
6. **`aliases → word_forms(kind='alt')` 重载了 `alt` 的语义**：`0001_init.sql:222` 注释「'alt' = Claude/suffix rule」、`words.add_form(…,"alt")`（`words.py:618,694`）是 lookup 合并写的记录；种子别名混进同一 kind 后，`test_full_seed_acceptance_numbers:352`（`kind not in (p,d,i,3,s,r,t)` = 0）变红（文稿只说「全部数字重写」），`alt` 行再也分不清「种子别名」还是「Claude 合并记录」，且 §3.6 自己承认「移除别名需要手动清理」。`0001_init.sql` 改不了（`test_db.py:362-366` 要求与 `docs/SCHEMA.sql` 字节一致），注释将永久失真。
7. **`kind` 由种子覆盖**放宽了 DESIGN §3.2:206「kind derived」的契约（已声明要改文档）；`seed_row` 的 `kind` 来自记录意味着 `normalise_input` 的 `kind` 与 `words.kind` 可以不一致——`words.add_form`/`derive_kind` 的其他调用方（自添词）仍按派生规则，两套规则并存。
8. **引用/完整性**：`install.sh:168-169` 引错（应为 `:140-141`）；「只有 `test_seed.py:93-97` 与 `:338-353` 依赖 Q1」漏了 `test_words_resolve.py:478`、`test_reports.py:86-87`、`test_vocab.py:111`。
9. **改动面与镜像增加**（不是估算问题，14 人日可信）：7 个新模块 + `manifest.schema.json` + 2 条 CLI（`DEPLOY.md §9` 命令清单、`cli.py COMMAND_OWNERS`、`test_cli.py` 自动覆盖）+ 5 个新测试文件 + `tests/fixtures/lists/` + `mini_stardict.sql`；`kv.seed_version` 语义切换要同步 `DEPLOY.md:304`、`TASKS.md:165`「sets kv.seed_version = sha256 of the file」、`seed.py:1-20` docstring、`test_seed.py:229-238`。文稿列了大部分，但 `TASKS.md:165` 没列。

**值得嫁接**

- **构建器进包 `backend/wd/seedbuild/`**：纯函数 + 表驱动测试（R1–R12 每条 ≥ 3 例含反例）、`mini_stardict.sql` 夹具、「构建两次字节相同」测试——这是 `TASKS.md:162`「keep verbatim unless a bug is proven」前提失效后唯一负责任的做法。
- **`retain` 上一版种子**：词的宇宙单调，任何词只重标不消失（与导入器「从不删行」对齐，堵住「文件里删掉的词旧旗标永久残留」这个洞）。
- **`kv.seed_version` 改为解压后内容的 sha256**（`seed_digest`），同步 `main.seed_check`；`gzip -9 -n` 只是运输格式——真正解决 [seed-pipeline-7]。
- manifest 对每个列表文件记 `sha256` + `expect ± tolerance`（**定义为拆分后词头数**），上游变了就显式失败。
- `split_head / classify_note / phrase_variants / merge_heads / lemma_of` 的函数边界，补上交付记法的文法（`AmE x`、`=x[, AmE y]`、`pl. x`、`(dad)` 口语变体、`x/y`、`x=y`、`x(s)`）；`a bit (of)` → 两个词组互链；`…` 规范为 ` ... ` 保证 `derive_kind` 判 phrase。
- 词头列 CJK 即报错作为「只取词头」的机械保证（在 `exclude_groups` 之后执行）。
- 记录里带 `lemma`，导入器用 `words.normalise_lemma` 复算并计数 `lemma_mismatch`；`unknown_stage_codes` 计数 + 告警一次，不再静默丢弃。
- 可复现性基线：先用同一 `stardict.db` + 旧 manifest 重建出与现 `vocab.jsonl` 相同的 `content_sha256`（`stardict.id` 与 `ecdict_id` 逐一相同已实测），再换官方表。
- `wd seed-diff` 不依赖 `Settings`/`.env`；`make seed-diff` 默认对 `git show HEAD:data/seed/vocab.jsonl.gz`。
- 「回退种子不回退代码」路径：`git checkout <prev> -- data/seed/vocab.jsonl.gz && wd import-seed --force`。

---

## 4. 对「维护者」四个追问的汇总回答

**契约镜像负担**：三份都把 `Stage/StageIndex` 的 `schemas.py ↔ types.ts ↔ API.md §9` 变更推给阶段模型线（正确），都没有碰 AI schema（`CLAUDE_INTEGRATION §4.1` 不受影响），都不改 `0001_init.sql`（`SCHEMA.sql` 字节一致测试安全），都要同一提交改 `zh.ts:86` 与 `FRONTEND.md:292`（三份都列了）。额外镜像：official-purist/data-engineering 的 manifest 阶段顺序（无门禁）；data-engineering 的 `manifest.schema.json`、DESIGN §3.2 `kind`、DEPLOY §9 命令、`kv.seed_version` 语义；continuity 第二期 `core_min` 将是一次 `WordBrief` 契约变更。

**硬编码是否真的减少**：净效果都只是 -1（`seed.py:43` 或 `build_seed` 常量）。data-engineering 的 `SEED_COLUMNS` 由 `STAGE_ORDER` 生成是唯一让「加阶段」少改一处的设计；official-purist 让 `seed.py STAGES` 继续以元组存在；continuity 保留 `ecdict_tags` 的 zk/gk 与 6 个外部文件。真正的「阶段成为数据」（INDEX Q1-c）不在任何一份的范围内，三份都如实声明。

**测试与文档改动量是否被低估**：清单上三份都列得相当全（official-purist §5.1 最全，含 `test_words_resolve.py:478`、`test_reports.py:86-87`）；被低估的是**天数**而不是条目——官方表的括注/并列文法（§1.2-1）在三份工作量表里都是 0。

**实现时最容易出错的地方**（按概率排序）：① 交付文件的括注/并列记法（§1.2-1）；② 词组 342 与 `expect` 口径（§1.2-2/3）；③ 附表中文类别与不规则动词（§1.2-4）；④ `is/are/does`（§1.2-5）；⑤ 任何在 `seed_check` 路径上会抛异常的新逻辑（continuity 守卫；official-purist/data-engineering 的「官方词缺失即失败」只在构建期，安全）；⑥ 重编号时 `seed.py`/`schemas.py`/0011 必须同一提交，否则 `stage_min=5` 撞 `CHECK (BETWEEN 1 AND 4)` 或 `StageIndex` 校验 → 导入事务失败 / `WordBrief` 500。

---

## 5. 给最终方案的建议（嫁接清单）

1. **成员定义**取 official-purist §3.1（`xs = L2 ∪ V ∪ 数词 ∪ 月份星期`；`zk = L3 ∪ V ∪ 附表 ∪ SH_w`；`gk = HS3100 ∪ V ∪ HS3000`；cet 原样；不闭包），并**加一条**：`moe-2022-appendix.tsv` 的「不规则动词」组中已是库内独立 lemma 的屈折形式（`is/are/am/was/were/does/did/has/had…`）继承其原形的阶段（或至少 `xs+zk`），让 §1.2-5 的回退不发生；`stages: []` 词典词只留给真正的旧考纲多余词。
2. **工程骨架**取 data-engineering §3.4（包、纯函数、表驱动测试、`retain`、`content_sha256`、`--dry-run --report`、manifest `sha256`/`expect ± tolerance`），但：manifest **不**写阶段顺序（构建器 import `schemas.STAGE_ORDER`）；`expect` 定义为拆分后词头数并把词组改 342；`max_missing` 按表配置；CJK 校验在 `exclude_groups` 之后；`aliases` 不写 `word_forms(kind='alt')`——放进 `aliases.tsv` 由 `canon()` 改写即可（official-purist 规则 3），搜索命中靠 `word_forms` 以外的方式再议。
3. **运维安全阀**取 continuity：`sources` 只追加记号不改名；`flag_removed/min_raised` 只进 dry-run 报告，不抛异常；`seed_row` 对未知码「计数 + 告警」而不是抛错，保证旧代码/新种子、新代码/旧种子都能启动；`--allow-regress` 作为显式 CLI 开关。
4. **先补文法再谈计数**：以交付文件为输入写 `split_head` 的样例表（`a/an`、`be (am, is, are)`、`colour (AmE color)`、`maths (=mathematics, AmE math)`、`mother (mum AmE mom)`、`child (pl. children)`、`Mr (AmE Mr.)`、`PE (=physical education)`、`A.M. (a.m.)`、`manner(s)`、`toward(s)`、`bund (the Bund)`、`phone (=telephone)`、`exam=examination`、`a bit (of)`、`add…to`、`hang (悬挂)`），每行写明产出的词头、变体与丢弃项，再让三份设计的数字（594/2,194/3,253 等）用真实文件重算一遍——现在所有「≈」数字都来自 verify 阶段的解析件，不是 `data/lists/`。
5. **工作量**按 official-purist 的集合代数 + data-engineering 的骨架合并估 **12–15 人日**（不含 0011/枚举/前端）；低于 10 的估算应当被质疑。
