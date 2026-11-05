# stage-model — 后端「阶段」数据模型：新增「小学」与区分「上海 / 全国」时的改动面

基线：仓库 `/Users/sqin/word-dance`，分支 `main @ 75df534`，核对日期 2026-11-05。所有 `path:line` 相对仓库根。

## 范围与方法

**读了哪些文件（全部按 75df534 重新核对行号）**
- 迁移与 schema：`backend/wd/migrations/0001_init.sql`（§1 运行规则 26-37 行、`user_settings` 139-161、`words` 166-210、`v_bank` 572-576、§10 578-584）、`0008_fk_child_indexes.sql`、`0009_strip_phonetic_delimiters.sql`、`0010_ai_provider.sql`、`docs/SCHEMA.sql`（`diff` 与 0001 完全一致）、`backend/wd/db.py`（PRAGMAS 44-51、`begin` 109-122、`run_migrations` 195-249）、`backend/wd/backup.py:283-295`。
- 阶段常量与 DTO：`backend/wd/schemas.py`（25-26、51-67、77-84、155-175、325-435、440-510、700-720、1070-1085、1325-1345、1415-1430）。
- 种子与词条写入：`backend/wd/seed.py`（全文）、`backend/wd/services/words.py`（35-42、225-282、565-600）、`backend/wd/services/ecdict.py`（24-32、110-182）、`backend/wd/main.py:307-319, 482-485`、`deploy/install.sh:117-141`、`scripts/build_seed.py`（阶段相关行）、`data/seed/stats.json`、`data/seed/ATTRIBUTION.md`。
- 选词 / 计数：`backend/wd/routers/vocab.py`（全文）、`backend/wd/services/stats.py:170-196`、`backend/wd/services/screen.py:1-75`、`backend/wd/services/batches.py`（55-65、228-275、308-318、680-705）、`backend/wd/services/bank.py`（80-90、160-190）、`backend/wd/ai/prewarm.py:28-64, 84-135`、`backend/wd/ai/content.py:44-96, 186-236`、`backend/wd/ai/consolidate.py:280-286`、`backend/wd/ai/models.py:38-100`、`backend/wd/ai/prompts/*.txt`、`backend/wd/ai/schemas/*.json`。
- 设置 / 引导：`backend/wd/security.py:555-615`、`backend/wd/routers/onboarding.py`（全文）、`backend/wd/routers/settings.py:80-122`、`backend/wd/routers/admin_ops.py:370-386`、`backend/wd/routers/screen.py:22`。
- 测试：`backend/tests/unit/test_db.py`（10-62、128-262、282-310、362-366）、`tests/fixtures/mini_seed.jsonl`、`tests/conftest.py:28-30, 203-210`，以及 `integration/test_vocab.py`、`test_onboarding.py`、`test_settings.py`、`test_screen.py`、`test_history.py`、`test_reports.py`、`test_admin_ops.py`、`test_auth.py`、`unit/test_api_schemas.py`、`test_seed.py`、`test_security.py`、`test_batches.py`、`test_content_apply.py`、`test_words_resolve.py` 中所有含 zk/gk/cet4/cet6/stage_min/current_stage 字面量的行。
- 文档契约：`docs/API.md`（155、160、167、169、187、230、236-292、456-462）、`docs/DESIGN.md`（32、40、72、186、193-209、316-330、338-352）、`docs/FRONTEND.md`（50-56、85-89、232-235）、`docs/DEPLOY.md:357-360, 421`、`docs/TASKS.md:174`、`README.md:9,103`、`scripts/check_contract.py:255-300`、`scripts/smoke.py`、`scripts/eval_provider.py:107, 326-344`。
- 前端（只列改动面，不做前端分析）：`frontend/src/api/types.ts`、`api/endpoints.ts`、`components/word/StageChips.tsx`、`pages/WelcomePage.tsx`、`SettingsPage.tsx`、`VocabPage.tsx`、`ScreenPage.tsx`、`ScreenRunPage.tsx`、`AdminPage.tsx`、`i18n/zh.ts`。
- 既有分析：`docs/analysis/2026-11-04-library-curation/facts/schema-model.txt`（第 8、180-183 条）、`seed-pipeline.txt`（第 2、3、4、19 条）。

**跑了哪些命令**
- 只读查询线上库副本 `…/scratchpad/live-copy.db`（`sqlite3 -readonly`）：`schema_migrations`、`sqlite_master` 中 `words`/`user_settings`/索引/视图 DDL、`stage_*`/`stage_min`/`difficulty`/`source` 分布、`user_settings` 的 `current_stage`/`stages_json`、`push_batches.settings_json`、`words` 的外键子表（`pragma_foreign_key_list`）、三条选词 SQL 的 `EXPLAIN QUERY PLAN` 与计时。
- 用 `python3 -I` 统计 `data/seed/vocab.jsonl.gz` 与 `tests/fixtures/mini_seed.jsonl` 的 `stages` 分布。
- 重建探针：`…/scratchpad/stage-model/rebuild_probe.py`（我自己写的脚本，用 `.venv/bin/python`＝应用运行时 Python 3.12.16 / SQLite 3.54.1，`PYTHONPATH=backend` 调用真实的 `wd.db.run_migrations`），在**线上库副本的私有拷贝**（`…/scratchpad/stage-model/rebuild/*.db`）上试跑 4 种 0011 式表重建。未触碰仓库、`live-copy.db` 本身与 `/Users/sqin/word-dance-data`。

**下载**
- `https://raw.githubusercontent.com/skywind3000/ECDICT/master/README.md` → `…/scratchpad/stage-model/dl-ecdict-readme/README.md`（18,414 字节，只用 `grep`/`sed` 读取；访问 2026-11-05）。

**置信度标注**：高 = 直接读到代码/数据或实测；中 = 代码推断、未实测；低 = 猜测。每条区分「事实」与「推断」。

---

## 一、现状：阶段模型是怎么编码的

### [stage-model-1] 阶段清单在后端 6 个模块里各存一份（9 个常量）＋ 3 个带字面量的请求模型，前端再存 5 份（事实，置信度高）

后端：
- `backend/wd/schemas.py:25` `Stage = Literal["zk", "gk", "cet4", "cet6"]`；`:26` `StageIndex = Literal[1, 2, 3, 4]`；`:51` `STAGE_ORDER: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")`；`:52` `STAGE_NAMES_ZH = {"zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}`。
- `backend/wd/seed.py:43` `STAGES: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")`。
- `backend/wd/services/words.py:39` `STAGES: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")`（被 `services/screen.py:46`、`services/bank.py:181`、`services/batches.py:233`、`services/words.py:229 stages_of` 使用）。
- `backend/wd/services/ecdict.py:28` `STAGE_TAGS: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")`。
- `backend/wd/ai/prewarm.py:32-33` `STAGE_COLUMNS = {"zk": "stage_zk", …}`，`STAGES = ("zk", "gk", "cet4", "cet6", "all")`。
- `backend/wd/ai/content.py:49` `STAGE_ZH = {"zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}`（与 `schemas.STAGE_NAMES_ZH` 内容相同但独立定义）。
- 请求模型里的字面量：`schemas.py:488` `VocabQuery.stage: Literal["all", "zk", "gk", "cet4", "cet6"]`，`:708` `ScreenNextQuery.stage: Literal["zk", "gk", "cet4", "cet6", "auto"]`，`:1335` `PrewarmRequest.stage: Literal["zk", "gk", "cet4", "cet6", "all"]`。

前端：`frontend/src/api/types.ts:5-6`（`Stage`/`StageIndex`）、`components/word/StageChips.tsx:7-9`（`STAGE_ORDER`/`STAGE_INDEX`/`STAGE_BY_INDEX`）、`i18n/zh.ts:28-29`（`stages: { zk: '初中', … }`）、`pages/VocabPage.tsx:29`（`TABS = ['all','zk','gk','cet4','cet6']`）、`pages/AdminPage.tsx:36`（`PREWARM_STAGES`）；另有派生映射 `WelcomePage.tsx:33-37` `ROLE_PRESETS`、`:42` `STAGE_FULL`、`ScreenPage.tsx:20` `FULL_NAME`。

`scripts/check_contract.py:274-281` 会把 `types.ts` 的字面量联合与 `schemas.py` 的 `Literal` 别名逐值比对（`if py_values != values: out.hard.append(...)`），所以 `Stage`/`StageIndex` 两边必须同一提交改。

> **核验修正（INDEX §3 #15，2026-11-05）**：按本条自己列出的清单，后端常量是 10 个而非 9 个（schemas 4：`Stage`/`StageIndex`/`STAGE_ORDER`/`STAGE_NAMES_ZH` + seed 1 + words 1 + ecdict 1 + prewarm 2：`STAGE_COLUMNS`/`STAGES` + content 1）；另有两处同类字面量未计入：`services/bank.py:85` `DEFAULT_STAGES = ("cet4", "cet6")` 与 `scripts/eval_provider.py:107` `STAGES`；其余行号与「`check_contract.py:274-281` 覆盖整数联合」的说法确认，依据 verify/stage-model.md [stage-model-1]。

### [stage-model-2] 整数索引同时承担「身份」和「顺序」，并且由元组位置推导（事实，高）

- 映射函数：`schemas.py:56-61` `stage_to_index` = `STAGE_ORDER.index(stage) + 1`；`:64-67` `index_to_stage` 先 `if not 1 <= int(index) <= 4: raise`，再 `STAGE_ORDER[int(index) - 1]`。
- 种子导入同样按位置算：`seed.py:208` `"stage_min": (STAGES.index(stages[0]) + 1) if stages else None`；ECDICT 直查亦然：`services/ecdict.py:177` `(STAGE_TAGS.index(stages[0]) + 1)`。
- 数据库把范围写死：`0001_init.sql:148` `current_stage INTEGER NOT NULL DEFAULT 3 CHECK (current_stage BETWEEN 1 AND 4)`；`:185` `stage_min INTEGER CHECK (stage_min BETWEEN 1 AND 4)`；`:147` `stages_json TEXT NOT NULL DEFAULT '["cet4","cet6"]'`。线上副本 `sqlite_master` 的 DDL 与 0001 逐字一致（查询 `SELECT sql FROM sqlite_master WHERE name IN ('words','user_settings')`）。
- 线上默认值在代码里又复制了一份：`services/bank.py:85-86` `DEFAULT_STAGES = ("cet4", "cet6")`，`DEFAULT_CURRENT_STAGE = 3`（`:172-173` 用于无设置行时的兜底）。
- 契约：`docs/API.md:459-460`「`Settings.current_stage` … is the `Stage` string; the server maps `zk→1, gk→2, cet4→3, cet6→4` … `StageIndex` is used only where an index is the natural value (`StageInfo.index`, `WordBrief.stage_min`)」；`docs/DESIGN.md:72`「`zk` / `gk` / `cet4` / `cet6` (stage index 1–4)」。

### [stage-model-3] `stage_min` 的 5 个消费点（事实，高）

1. 仅本阶段新增过滤：`routers/vocab.py:54-56` `where.append("w.stage_min = :stage_idx")`。
2. `/api/stages` 与 `/api/stats` 的 `new_only_total`：`routers/vocab.py:89` 与 `services/stats.py:180` 同一条 SQL `COALESCE(SUM(w.stage_min = :idx), 0)`。
3. 阶段距离排序（筛词与每日推荐词）：`services/screen.py:34-36` 与 `services/batches.py:60` 完全相同的 `CASE WHEN w.stage_min = :cur THEN 0 WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END`（DESIGN.md:347-350 的 `stage_distance`）。
4. 难度排序兜底：`routers/vocab.py:78` `"difficulty": "COALESCE(w.difficulty, w.stage_min, 5), …"`——把 Claude 给的 `difficulty`（1 初中 … 4 六级 … 5 beyond，`ai/prompts/content_system.txt:11`）与 `stage_min` 当作**同一把尺子**。
5. 预生成 `all` 的范围：`ai/prewarm.py:37-38` `if stage == "all": return "w.stage_min IS NOT NULL"`。

索引 `ix_words_stage_min(stage_min, frq)`（`0001_init.sql:207`）只被第 1 点命中：对副本执行 `EXPLAIN QUERY PLAN` 的 new_only 查询给出 `SEARCH w USING INDEX ix_words_stage_min (stage_min=?)`；筛词选词与 `/api/stages` 计数走的是 `ix_words_public`，排序用 `USE TEMP B-TREE FOR ORDER BY`。15 词的筛词查询在副本上含进程启动共 0.014 s（`time sqlite3 …`）。

### [stage-model-4] 线上数据：9,162 词全部来自种子，索引与旗标一致，但旗标集合并非「区间」（事实，高）

查询副本：`SELECT COUNT(*), SUM(stage_zk), SUM(stage_gk), SUM(stage_cet4), SUM(stage_cet6), SUM(stage_min IS NULL) FROM words` → `9162|2099|3829|4722|7671|0`；`GROUP BY stage_min` → 1:2099、2:1792、3:1577、4:3694；`SELECT source, COUNT(*) … GROUP BY source` → 只有 `seed|9162`；`stage_min` 与「第一个为 1 的旗标」不一致的行数 = 0。种子文件自己的统计一致（`python3 -I` 解包 `vocab.jsonl.gz`：per_stage zk 2099 / gk 3829 / cet4 4722 / cet6 7671，first_stage 2099/1792/1577/3694；`data/seed/stats.json` 同）。

但旗标组合有 15 种，不是单调区间：`SELECT stage_zk||stage_gk||stage_cet4||stage_cet6, COUNT(*) …` → `0001` 3694、`0011` 1512、`0111` 1156、`1110` 1019、`1111` 854、`0101` 349（高中+六级但不在四级）、`0100` 193、`0110` 94、`1101` 85、`1100` 79、`0010` 65、`1000` 33（仅初中）、`1011` 14、`1010` 8、`1001` 7。推断：任何新模型都必须保留「每词一个阶段集合」，不能退化成「一个最低阶段 + 向上累积」。

用户侧：`SELECT COUNT(*) FROM users` = 2；`user_settings` 为 `current_stage=1, stages_json='["zk"]'` 与 `current_stage=3, stages_json='["zk","gk","cet4","cet6"]'` 各 1 行。`push_batches.settings_json` 4 行都含 `"current_stage": 3`（整数索引快照，`services/batches.py:314-318` 只写不读——`grep settings_json backend/wd` 仅命中那条 INSERT）。

### [stage-model-5] 选词 SQL 按列名拼模板，没有「阶段维度」参数（事实，高）

`f"w.stage_{q.stage} = 1"`（`routers/vocab.py:53`）、`f"… WHERE w.stage_{stage} = 1 …"`（`vocab.py:91`、`services/stats.py:183`）、`" OR ".join(f"w.stage_{s} = 1" for s in stages)`（`services/screen.py:52`、`services/batches.py:233`）、`f"w.{STAGE_COLUMNS[stage]} = 1"`（`ai/prewarm.py:39`）、`stages_of` 读 `row.get(f"stage_{s}")`（`services/words.py:228-229`）、`scripts/eval_provider.py:342` 同款。新增阶段只要列名符合 `stage_<code>` 并加入各常量，这些模板自动覆盖；但要区分「方案」（上海 / 全国）时，每一处都要多一个维度（见第五节）。

### [stage-model-6] AI 侧把阶段中文名与难度尺子写进提示词（事实，高；影响为推断）

- `ai/content.py:82-92` `prompt_entry` 生成 `"stages": [STAGE_ZH[s] for s in words.stages_of(word)]`——`stages_of` 按 `services/words.STAGES` 迭代，若 `words.STAGES` 先加了 `xs` 而 `STAGE_ZH` 没加，会 `KeyError`，两处必须同改。
- `ai/content.py:48` `AUDIENCE = "Chinese learners, junior high school to CET-6, plus working professionals"`；`ai/prompts/content_system.txt:1`「…for Chinese learners (初中, 高中, CET-4, CET-6 and working professionals)」，`:11`「difficulty: integer 1–5 (1 = 初中 basic, 2 = 高中, 3 = CET-4, 4 = CET-6, 5 = beyond CET-6)」；`consolidate_system.txt:11`「difficulty_tags … (1 初中 … 5 beyond CET-6)」；`ai/schemas/content_v1.json:11` `"difficulty":{"type":"integer","enum":[1,2,3,4,5],"description":"1 junior high, …"}`；`ai/models.py:44/61/76/90` `difficulty: Literal[1, 2, 3, 4, 5]`；`words.difficulty INTEGER CHECK (difficulty BETWEEN 1 AND 5)`（`0001_init.sql:195`）。写入点：`ai/content.py:230-234`（内容生成，`force or difficulty IS NULL` 时写）、`ai/lookup.py:353-355`、`ai/consolidate.py:282-285, 308-311`。线上有 49 行非空 difficulty（分布 1:2、2:1、3:43、4:3），全部是 `content_state='ready'` 的 49 词。
- 推断：加「小学」后要决定 difficulty 尺子是否把 1 让给小学。若不改尺子，`COALESCE(difficulty, stage_min, 5)`（vocab.py:78）里两把尺子就不再对齐（见 [stage-model-10]）。

### [stage-model-7] 种子构建器只认 4 个 ECDICT 标签；「小学」在数据源层没有现成输入（事实，高；最后一句为中）

`scripts/build_seed.py:105-106` 只查 `' '||tag||' ' like '% zk %' or … '% gk %' or … '% cet4 %' or … '% cet6 %'`；`:82-87` 词表文件为 中考英语词汇表 / Highschool_edited / CET4_edited / CET6_edited / CET_4+6_edited / 六级星标；`:150` `order = {"zk": 0, "gk": 1, "cet4": 2, "cet6": 3}`。ECDICT README（访问 2026-11-05）对 `tag` 列的说明是「字符串标签：zk/中考，gk/高考，cet4/四级 等等标签，空格分割」；项目把其余已知标签列为 `EXAM_TAGS = ("ky", "toefl", "ielts", "gre")`（`seed.py:44`、`services/ecdict.py:29`、`data/seed/ATTRIBUTION.md`）。推断（中）：ECDICT 没有「小学」标签，小学词表必须来自新的外部清单，由构建器写入 `stages` 数组——这是其他 slug 的范围，这里只指出接口：`seed.py:184-185` 读 `rec["stages"]` 并用 `s in STAGES` 过滤，当前代码会**静默丢弃** `"xs"`。

> **核验修正（INDEX §3 #31，2026-11-05）**：「ECDICT 没有小学标签」的置信度按数据范围区分——对仓库基础版 `ecdict.csv`（770,611 行）为高：`tag` 全集只有 zk/gk/cet4/cet6/ky/toefl/ielts/gre 8 个取值（已全量计数），且 csv 的 zk 1,603 词与线上 `stage_zk` 100% 一致；对 1.0.28 release 的 `stardict.db` 全集维持中（本机无该文件，csv 与 release 有 8 个种子词之差），依据 verify/stage-model.md [stage-model-7]、verify/list-sources.md [list-sources-2]、verify/seed-pipeline.md O5、facts/seed-pipeline.md [seed-pipeline-27]。

---

## 二、(a) 新增阶段 `xs`（小学）要改的每个文件:行（含测试与文档）

行数为估计（推断）；「自动」表示该处通过常量/模板自动覆盖，无需改动但要回归。

| 层 | 文件:行 | 要改什么 | 估计行数 |
|---|---|---|---|
| 迁移 | `backend/wd/migrations/0011_<name>.sql`（新建） | ① `words`：新增 `stage_xs INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs IN (0,1))`（可用 `ALTER TABLE ADD COLUMN`，0010 先例）；② 放宽 `stage_min` 的 `CHECK (BETWEEN 1 AND 4)` → 必须整表重建（复制 words DDL ≈ 50 行、`INSERT … SELECT`、`DROP`、`RENAME`、重建 6 个索引、**先 `DROP VIEW v_bank` 后重建**，见 [stage-model-13]）；③ `user_settings`：放宽 `current_stage` CHECK → 重建（DDL ≈ 25 行 + 重建 `ix_user_settings_next_push`）；④ 如选重编号方案，加 `UPDATE` 两条 | 90–120 |
| schema 文档 | `docs/SCHEMA.sql` | **不改**：`tests/unit/test_db.py:362-366` 断言它与 `0001_init.sql` 字节相同；0001 头部 `:37`「later files … are additive; this file stays the complete baseline schema」。代价是文档漂移（它已不含 0010 的 `ai_calls.provider`：`grep -c 'provider TEXT' docs/SCHEMA.sql` = 0） | 0 |
| 迁移测试 | `backend/tests/unit/test_db.py` | 仿 `:236-258`（从 0001 基线升级）与 `:282-310`（0009）为 0011 加「有数据的库升级后子表行数不变、新 CHECK 生效、`v_bank` 可查」的测试；若新增表还要改 `:13-17 EXPECTED_TABLES`、`:50` 的集合等式与 `:51 assert len(tables) == 25` | 30–40 |
| 常量/DTO | `backend/wd/schemas.py:25, 26, 51, 52, 56-67, 488, 708, 1335` | `Stage`/`StageIndex` 字面量、`STAGE_ORDER`、`STAGE_NAMES_ZH`（`"xs": "小学"`）、`index_to_stage` 的范围检查（按所选索引方案改为查表）、三处请求 Literal | 10–15 |
| 种子导入 | `backend/wd/seed.py:7, 43, 60-64, 204-208` | docstring、`STAGES`、`SEED_COLUMNS` 加 `stage_xs`（UPSERT 的列清单与 `WHERE … IS NOT excluded.…` 由 `:72-82` 自动生成）、`"stage_xs": int("xs" in stages)`、`stage_min` 改为查表而非 `index+1` | 6–8 |
| 词条写入 | `backend/wd/services/words.py:39, 576-580, 591-594` | `STAGES`、`_word_defaults` 加 `"stage_xs": 0`、`_INSERT_WORD_SQL` 列清单与占位符加 `stage_xs`；`:228-229 stages_of` 自动 | 4–5 |
| ECDICT 直查 | `backend/wd/services/ecdict.py:28, 173-177` | `word_columns` 必须输出 `stage_xs`（否则 `_INSERT_WORD_SQL` 缺参数报错）；`STAGE_TAGS` 只有在 ECDICT 真有对应标签时才加 | 2–3 |
| 选词 | `backend/wd/services/screen.py:35, 44, 46`；`services/batches.py:60, 233, 272, 698`；`routers/vocab.py:53-56, 78, 86-98`；`services/stats.py:177-190`；`services/bank.py:85-86, 181` | 模板自动覆盖。**例外**：选「`xs` = 索引 0」时 `screen.py:44`、`batches.py:272`、`:698` 的 `int(s["current_stage"] or bank.DEFAULT_CURRENT_STAGE)` 会把 0 当缺失→3（见 [stage-model-10]）；选「索引 5 但排序另算」时 `screen.py:35`、`batches.py:60`、`vocab.py:78` 的算式要改成查表 CASE | 0–8 |
| 预生成 | `backend/wd/ai/prewarm.py:32-33` | `STAGE_COLUMNS["xs"] = "stage_xs"`、`STAGES` 加 `xs` | 2 |
| AI 提示 | `backend/wd/ai/content.py:48-49`；`ai/prompts/content_system.txt:1, 11`；`consolidate_system.txt:11`；`ai/schemas/content_v1.json:11` | `STAGE_ZH["xs"] = "小学"`、受众文案；难度尺子是否纳入小学是产品决定（改了提示词应考虑 `content.py:46 PROMPT_VERSION`） | 2–6 |
| 设置/引导 | `backend/wd/security.py:588, 597, 612-614`；`routers/onboarding.py:36`；`routers/settings.py:89-91, 113-116`；`routers/admin_ops.py:380`；`routers/screen.py:22` | 全部经由 `stage_to_index`/`index_to_stage`/Pydantic Literal，自动 | 0 |
| 测试夹具 | `backend/tests/fixtures/mini_seed.jsonl` | 60 条记录（zk 35 / gk 52 / cet4 45 / cet6 24；first zk 35 / gk 19 / cet4 3 / cet6 3，`python3 -I` 统计）需给若干词加 `"xs"`。注意连锁：`a`/`be`/`go` 一旦成为小学词，`stage_min` 变化会打破 `test_seed.py:94-97`（`word(conn,"a")["stage_min"] == 1`）、`test_screen.py:129-134`（`stage=zk` 按频率返回 `["be","a","go"]`）、`test_batches.py:127`、`test_content_apply.py:255`（`"stages": ["初中","高中","四级"]`）、`test_words_resolve.py:478`、`test_reports.py:87` 这些按夹具钉死的断言 | 5–15 |
| 契约测试 | `backend/tests/integration/test_vocab.py:69-70, 111`；`unit/test_api_schemas.py:33-39`；`integration/test_history.py:112`；`test_onboarding.py:98, 120, 139`；`test_settings.py:57-58, 84-96, 108-112`；`test_security.py:315`；`test_auth.py:82`；`test_admin_ops.py:107, 257, 435-478` | `/api/stages` 由 4 行变 5 行、索引序列、`STAGE_NAMES_ZH` 等式、存库整数值（`'cet4' is stored as 3` 等视方案而定）、`"cet9"`/`"nope"` 仍非法 | 30–60 |
| 脚本 | `scripts/build_seed.py:10-11, 82-87, 102-151, 159-161, 191, 213-216`；`scripts/smoke.py:352, 614`；`scripts/eval_provider.py:107` | 新词表来源与 `order` 字典；smoke 钉死 `["zk","gk","cet4","cet6"]` 与 `len(stats["stages"]) == 4`；评测脚本的 `STAGES` | 20–40 |
| 文档 | `docs/API.md:155, 160, 167（"4 rows"）, 169, 187, 230, 239-240, 279, 459-460`；`docs/DESIGN.md:32, 40, 72, 186, 202, 209, 321-322, 330, 345-350`；`docs/FRONTEND.md:50, 54, 56, 89, 234-235`；`docs/TASKS.md:174`（验收数字 2099/1792/1577/3694）；`README.md:9, 103`；`data/seed/ATTRIBUTION.md` | 阶段枚举、索引范围、行数、验收数字、来源署名 | 40–60 |
| 前端 | `frontend/src/api/types.ts:5-6`；`components/word/StageChips.tsx:7-9`；`i18n/zh.ts:28-29`；`pages/VocabPage.tsx:29, 202`；`pages/WelcomePage.tsx:30-42`（加「小学生」预设）；`pages/ScreenPage.tsx:20`；`pages/AdminPage.tsx:36`；`SettingsPage.tsx`（经 `STAGE_ORDER`，自动）；`api/endpoints.ts:131, 196, 328`（派生类型，自动）；19 个 `*.test.ts(x)` 含阶段字面量（`SettingsPage.test` 6 处、`BankPage.test` 7 处、`WelcomePage.test` 4 处最集中） | 30–50 |

合计（推断）：迁移 ≈ 100 行；后端代码 ≈ 30–50 行（都是常量级改动）；测试 ≈ 70–120 行；脚本 ≈ 20–40 行；文档 ≈ 40–60 行；前端 ≈ 30–50 行。真正的工作量不在行数，而在 [stage-model-10] 的索引方案决定与夹具连锁。

---

## 三、(b) `stage_min` 既是顺序又是身份：在 zk 前插入小学会不会整体错位？

### [stage-model-8] 会——如果只改常量不迁数据（事实 + 推断，高）

因为索引由元组位置推出（[stage-model-2]），把 `"xs"` 插到 `STAGE_ORDER` 最前面后：`stage_to_index("zk")` 从 1 变 2；`index_to_stage(1)` 返回 `"xs"`；线上 `stage_min=1` 的 2,099 个初中词会被当作小学词展示（`services/words.py:277` 直接回传 `r.get("stage_min")`，`StageChips.tsx:31` 用 `stageMin === STAGE_INDEX[stage]` 高亮）；线上那位 `current_stage=1` 的用户会被读成主攻小学（`security.py:597 index_to_stage(int(row["current_stage"]))`）；`/api/stages` 的 `new_only_total` 对 zk 会去数 `stage_min = 2`（今天的 gk 增量 1,792）。所以**代码改动与数据重编号必须在同一次停机里落地**：`install.sh:117-141` 的顺序是停服务 → `wd migrate` → `wd import-seed` → 启动；`main.py:482-485` 启动时也是先 `run_migrations` 再 `seed_check`。`--no-restart` 路径（DEPLOY.md:421「safe only for purely additive migrations」）在这里不可用——而且重建表本身就不是 additive。

### [stage-model-9] 三种处理办法与代价（推断，中—高）

**办法 1：小学 = 索引 0，其余不动。**
- 改动最小：数据不重编号；`CHECK` 改为 `BETWEEN 0 AND 4`/`0 AND 5`（仍需重建，见第四节）；`stage_to_index`/`index_to_stage`/`seed.py:208`/`ecdict.py:177` 改成显式字典（`{"xs": 0, "zk": 1, …}`）而不是 `index+1`；`StageIndex` 加 0；前端 `STAGE_INDEX` 加 `xs: 0`。
- 排序天然正确：`CASE … w.stage_min - :cur` 与 `COALESCE(difficulty, stage_min, 5)` 对 0 都成立，小学词排最前。
- **陷阱（事实，高）**：`services/screen.py:44` `cur = int(s["current_stage"] or bank.DEFAULT_CURRENT_STAGE)`、`services/batches.py:272` 与 `:698` `int(settings_row.get("current_stage") or bank.DEFAULT_CURRENT_STAGE)`——Python 里 `0 or 3 == 3`，主攻小学的用户会被静默按主攻四级排推荐词。三处要改成 `is None` 判断。另外 `index_to_stage` 现在 `1 <= index <= 4` 的硬编码要同步。
- 难度尺子不对齐：Claude 的 `difficulty` 1 仍表示「初中 basic」，小学词没有对应难度值；`COALESCE` 排序里 `difficulty=1` 的词会和 `stage_min=1` 的初中词并列而排在小学词（0）之后——可接受但要写进文档。
- 历史快照 `push_batches.settings_json.current_stage` 含义不变。

**办法 2：小学 = 索引 5（追加在末尾），排序另算。**
- 数据不重编号，`StageIndex` 加 5，`CHECK` 放宽到 5（仍需重建）。
- 但「索引 = 顺序」的假设被打破：`seed.py:208`/`ecdict.py:177` 的 `stages[0]`（按 `STAGES` 顺序过滤后的第一个）会把「小学∩初中」的词算成 `stage_min = zk`，必须改成「取 rank 最小」；`screen.py:35`、`batches.py:60` 的距离算式与 `vocab.py:78` 的 `COALESCE` 要换成查表 `CASE w.stage_min WHEN 5 THEN 0 WHEN 1 THEN 1 … END`（或者加一个 `VIRTUAL` 生成列做 rank——SQLite 允许 `ALTER TABLE ADD COLUMN` 添加 VIRTUAL 生成列，但 CHECK 放宽仍要重建，所以省不下重建）。
- `ix_words_stage_min(stage_min, frq)` 对 new_only 仍有效；`stage_min IS NOT NULL`（prewarm all）仍有效。
- 代价是在 SQL 和 Python 两边各维护一份 rank 表，三处算式与 `index_to_stage` 都要改；可读性最差。

**办法 3：改成字符串列（`stage_min TEXT CHECK (IN ('xs','zk',…))`，`current_stage TEXT`）。**
- 去掉 `stage_to_index`/`index_to_stage` 这一层与 `StageIndex` 类型；但 API §9（`docs/API.md:239-240, 279, 286, 459-460` 的「frozen contract」）、`types.ts:5-6, 45, 52`、`scripts/check_contract.py` 的联合比对都要跟着改：`StageInfo.index` 与 `WordBrief.stage_min` 从 `StageIndex` 变成 `Stage | null`，前端 `StageChips.tsx:31` 的比较改为字符串。
- 排序仍需 rank：要么 SQL `CASE`，要么新建 `stage_defs(code PRIMARY KEY, rank, name_zh)` 表 JOIN（这张表顺带解决 [stage-model-1] 的 6 份常量，并给第五节的「方案」留位置）。
- 迁移要在重建表的 `INSERT … SELECT` 里做值转换（`CASE stage_min WHEN 1 THEN 'zk' …`），`user_settings` 同理；`push_batches.settings_json` 旧快照仍是整数（只读，不影响代码）。
- 工作量最大，但是唯一让「阶段」成为可扩展的数据而不是硬编码枚举的方案。

**办法 1'（重编号）**：xs=1、zk=2…cet6=5，并在 0011 的 `INSERT … SELECT` 中 `stage_min + 1`、`current_stage + 1`。保持「索引 = 顺序」且无 0 值陷阱，但：① `docs/TASKS.md:174`、`API.md:460`、`DESIGN.md:72, 186, 202, 322` 等所有写死 `1=zk … 4=cet6` 的文字全部作废；② `difficulty` 1–5 尺子与新索引错位一格，要么同步 `difficulty + 1`（上限 6，`CHECK BETWEEN 1 AND 5` 与四处 `Literal[1..5]`、三个 JSON schema 的 `enum` 都要改）要么改提示词；③ 历史 `settings_json` 快照的整数含义改变。线上只有 2 个用户、49 行 difficulty，数据层面代价极小，但文档与契约代价最大。

> **核验修正（INDEX §3 #14，2026-11-05）**：三种办法与 0 值陷阱确认；裁定口径：办法 1（小学 = 0）与办法 1'（重编号 1..5）都要重建 `words`/`user_settings` 两张表，重编号是现有「位置推导」代码（`schemas.py:56-61` `stage_to_index`、`:64-67` `index_to_stage`）的自然结果，= 0 还需改写这两个函数并修 3 处 `or DEFAULT_CURRENT_STAGE` 陷阱——两案都不便宜（前端切片低估了方案 A）；办法 1' ② 的难度尺子清单漏了 API 契约层两处：`schemas.py:47` `Difficulty = Literal[1, 2, 3, 4, 5]` 与 `frontend/src/api/types.ts:73` `difficulty: 1 | 2 | 3 | 4 | 5`，扩到 6 级须与 `API.md §9` 同一提交改，依据 verify/stage-model.md [stage-model-9]、verify/frontend-stages.md [frontend-stages-12]。

### [stage-model-10] 另一个必然的语义变化：「仅初中新增」会缩水（事实 + 推断，高）

`stage_min` 定义为「最低阶段」（`0001_init.sql:185` 注释、`DESIGN.md:186`）。小学词表大概率与初中 2,099 词大量重叠；重叠的词 `stage_min` 变成小学，`/api/vocab?stage=zk&new_only=1`、`StageInfo.new_only_total`（zk）与 `docs/TASKS.md:174` 的验收数字 `(2099,1792,1577,3694)` 都会变化，幅度取决于词表（见未解决问题 1）。这不是 bug，而是产品要接受的定义变化；FRONTEND.md:235 的「仅六级新增（不含四级）」文案逻辑在 `VocabPage.tsx:202` 只对 cet6 特判，小学/初中的文案要补。

---

## 四、(c) SQLite 能否改 `CHECK (current_stage BETWEEN 1 AND 4)`？

### [stage-model-11] 不能原地改，必须重建表；运行器明确支持这种重建（事实，高）

- SQLite 没有 `ALTER TABLE … DROP/ALTER CONSTRAINT`；项目自己的结论写在 `backend/wd/db.py:222-226`「SQLite's table-rebuild recipe (CREATE new → INSERT … SELECT → DROP old → RENAME) is the only way to change a CHECK list」与 `0001_init.sql:31-36`。
- 运行器为此专门做了：`PRAGMA foreign_keys=OFF` 在 `BEGIN` 之前（`db.py:227`），`conn.executescript(sql)` 在运行器自己的 `BEGIN IMMEDIATE` 内（`:231`），`PRAGMA foreign_key_check` 不为空则整文件回滚（`:235-238`），运行器自己写 `schema_migrations` 行（`:239`），`finally: PRAGMA foreign_keys=ON`（`:246`）。`tests/unit/test_db.py:128-211` 用 `REBUILD_USERS_SQL` 证明重建父表 `users` 时 8 张子表行数不变、新 CHECK 生效。
- `docs/DEPLOY.md:421`：「A table rebuild (the only way to change a CHECK list in SQLite) is an ordinary stop-first migration」。迁移前自动快照：`backup.py:283-292 snapshot_before_migrate` 写 `backups/pre-migrate-<from>-to-<to>.db.gz`（`from_version == 0` 时跳过）。
- 加列本身不需要重建：0010 的 `ALTER TABLE ai_calls ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude' CHECK (provider IN ('claude','fallback'))` 是先例；`stage_xs` 可同样加。只有 `stage_min`/`current_stage` 的范围 CHECK 逼出重建。

### [stage-model-12] 实测：重建 `user_settings` 与 `words` 都能通过运行器，耗时毫秒级（事实，高）

探针（`…/scratchpad/stage-model/rebuild_probe.py`，应用运行时 Python 3.12.16 / SQLite 3.54.1，`PRAGMA legacy_alter_table` = 0）在线上副本的私有拷贝（版本 10，9,162 词）上运行真实的 `wd.db.run_migrations`：
- 变体 C（只重建 `user_settings`，CHECK 改 `BETWEEN 0 AND 5`）：`applied=[(11,'probe')]`，0.009 s；12 张表行数不变；`foreign_key_check` 空；`integrity_check ok`；随后 `UPDATE user_settings SET current_stage = 0` 被接受。`user_settings` 没有任何子表（`pragma_foreign_key_list` 中无表引用它），`users` 不受影响。
- 变体 B（重建 `words`，加 `stage_xs`，CHECK 改 `BETWEEN 0 AND 5`，重建 6 个索引，**前后 `DROP VIEW v_bank` / `CREATE VIEW v_bank`**）：0.041 s；`words` 的 9 条外键子关系（`words.merged_into_word_id SET NULL`、`word_forms/word_contents/word_images/user_words.word_id/push_items/content_reports CASCADE`、`user_words.suggested_word_id`、`bank_suggestions.target_word_id SET NULL`）全部保留行数；插入 `stage_min=0` 成功，`stage_min=6` 被 `CHECK constraint failed: stage_min BETWEEN 0 AND 5` 拒绝。
- 变体 D（两张表放在同一个 0011 文件）：0.042 s，同样通过。

### [stage-model-13] 重建 `words` 的隐蔽坑：视图 `v_bank` 会让 `RENAME` 失败，必须在迁移文件里先 DROP VIEW 再重建（事实，高）

变体 A（与 B 相同但不处理视图）：`MigrationError: migration 0011_probe.sql failed and was rolled back: error in view v_bank: no such table: main.words`，版本停在 10，`in_transaction=False`，`foreign_keys=1`——运行器的回滚与清理正确，但迁移不会成功。原因：`v_bank`（`0001_init.sql:572-576`）引用 `words`，`DROP TABLE words` 后执行 `ALTER TABLE words_new RENAME TO words` 时 SQLite（`legacy_alter_table=OFF`）重新解析全部视图而失败。`0001_init.sql:31-36` 与 `db.py:222-226` 的重建说明都没有提到视图；`test_db.py` 的 `REBUILD_USERS_SQL` 之所以通过，是因为没有视图引用 `users`。注意（推断，中）：本机 `/usr/bin/sqlite3` 3.51.0 报 `PRAGMA legacy_alter_table` = 1，用 CLI 排练可能通过而应用运行时失败——排练必须用 `.venv/bin/python` 走 `run_migrations`。`v_bank` 在后端代码中无读取者（`grep v_bank backend/wd` 空），重建它只是为了保持 schema 一致（`test_db.py:52 assert db.view_names(c) == ["v_bank"]`）。

### [stage-model-14] `docs/SCHEMA.sql` 的规则：它是 0001 的字节拷贝，不是「当前 schema」（事实，高）

`tests/unit/test_db.py:362-366` `assert docs.read_bytes() == (db.MIGRATIONS_DIR / "0001_init.sql").read_bytes()`；`diff` 两文件今天完全一致；0008/0009/0010 都没有改它（SCHEMA.sql 中没有 `ai_calls.provider`）。所以 0011 之后 `SCHEMA.sql` 里 `words.stage_min`/`user_settings.current_stage` 的 CHECK 仍是 `BETWEEN 1 AND 4`，与线上不符。推断（中）：要么在 `DESIGN.md §3` 加一段「当前 schema = 0001 + 0008 + 0010 + 0011」的差异说明，要么增加一个由 `sqlite_master` 导出的当前 schema 文件并相应调整测试；二者都不在本次范围。

---

## 五、(d) 区分「上海词表 / 全国词表」：当前模型能表达吗？

### [stage-model-15] 不能：模型里只有「阶段」一维，没有「方案/地区」维（事实，高）

每词 4 个 0/1 旗标 + 1 个 `stage_min`（`0001_init.sql:181-185`），每用户 `stages_json` + `current_stage`（`:147-148`）；`words.sources`（`:188`，如 `'cet4 cet46 ecdict gk zk'`）记录来源但无索引、无任何路由读取（`grep -rn '\bsources\b' backend/wd` 仅命中 seed/ecdict/words 的写入）。要表达「同一个词在上海方案属小学、在全国方案属初中」，需要新的维度。

### [stage-model-16] 路线 A：多加列（`stage_sh_xs`、`stage_sh_zk`、`stage_sh_gk`…）（推断，中）

- 迁移：`ALTER TABLE words ADD COLUMN stage_sh_xs INTEGER NOT NULL DEFAULT 0 CHECK (… IN (0,1))` × N，可附加（additive），无需重建；但 `stage_min` 是方案相关的「最低阶段」，必须加 `stage_min_sh`（+ 索引 `(stage_min_sh, frq)`），否则上海方案的 new_only / 距离排序无处取值。`user_settings` 加 `scheme TEXT NOT NULL DEFAULT 'cn' CHECK (scheme IN ('cn','sh'))`（additive）。
- 代码：模板 `f"w.stage_{s} = 1"`（[stage-model-5] 的 6 处）要变成 `f"w.stage_{prefix}{s} = 1"`，`stage_min` 的 5 个消费点（[stage-model-3]）要按方案选列；`/api/stages` 的循环（`vocab.py:86`、`stats.py:177`）要按方案给出不同的阶段清单；`seed.py SEED_COLUMNS` 与 `services/words._INSERT_WORD_SQL`、`ecdict.word_columns` 都要补列。每加一个方案或一个阶段就再加一批列——列数 = 方案 × 阶段。
- 优点：查询仍是单表、无 JOIN；现有 EXPLAIN 计划不变。缺点：schema 随方案膨胀，常量再复制一轮。

### [stage-model-17] 路线 B：新表 `word_stage_tags(word_id, scheme, stage)`（推断，中）

- 迁移：`CREATE TABLE word_stage_tags (word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE, scheme TEXT NOT NULL, stage TEXT NOT NULL, PRIMARY KEY (word_id, scheme, stage)) WITHOUT ROWID` + `CREATE INDEX ix_word_stage_tags_lookup ON word_stage_tags(scheme, stage, word_id)`；回填 `INSERT … SELECT id,'cn','zk' FROM words WHERE stage_zk=1` × 4——全部 additive。`stage_min` 按方案要么再建 `word_stage_min(word_id, scheme, rank)`，要么在 SQL 里 `MIN(rank)` 子查询（需要 `stage_defs(code, scheme, rank, name_zh)` 字典表）。`tests/unit/test_db.py:13-17 EXPECTED_TABLES`/`:51 len == 25` 要加表。
- 代码：选词从 `w.stage_x = 1` 变成 `EXISTS (SELECT 1 FROM word_stage_tags t WHERE t.word_id = w.id AND t.scheme = :scheme AND t.stage IN (…))`；`/api/stages` 变成 `GROUP BY t.stage` 一条查询；`stages_of` 变成一次批量查询（`word_briefs` 已经是批量构造，`services/words.py:291`）；种子导入要像 `word_forms` 一样「删后重灌」（`seed.py:218-245 _rebuild_forms` 的模式）；`ecdict.word_columns` 要额外产出 tags。
- 性能：9,162 词 × 平均 2 个阶段 ≈ 2 万行 tag；现有筛词查询在副本上 0.014 s（含进程启动），EXPLAIN 为 `SEARCH w USING INDEX ix_words_public` + `TEMP B-TREE FOR ORDER BY`；加一个按 `(scheme, stage, word_id)` 索引的 EXISTS 在这个规模下不会改变数量级（推断，中；未实测）。
- 优点：加方案/加阶段只是加行，不动 schema；`stage_defs` 顺便消灭 6 份常量。缺点：改动面最大（所有 6 处模板 + 5 个 `stage_min` 消费点 + 导入两处 + 前端常量），而且过渡期要决定旧 4 列是删、留作缓存还是作为 `'cn'` 方案的物化副本。

### [stage-model-18] 两条路线共同的 API / 前端影响（事实 + 推断，高）

- `GET /api/stages` 现约定「4 rows」（`API.md:167`）且 `StageInfo.stage: Stage`、`index: StageIndex`（`API.md:278-282`，`schemas.py:448-458`）；区分方案后要么按用户 `scheme` 返回其阶段清单，要么增加 `?scheme=` 参数并在 `StageInfo` 里带 `scheme`。
- 前端把阶段清单当常量：`ScreenPage.tsx:31` `STAGE_ORDER.map((s) => data.items.find((i) => i.stage === s))` 会**静默丢掉**后端返回的未知阶段；`VocabPage.tsx:29` 的 `TABS` 是写死的；`StageChips.tsx:7-9` 的三张映射表也是。要让「上海用户看到小学/初中/高中、全国用户看到初中/高中/四级/六级」，前端必须改为以 `/api/stages` 的返回驱动页签与芯片——这是前端 slug 的范围，这里只指出耦合点。
- `user_settings.stages_json` 存的是阶段码字符串（`security.py:612-614`），`current_stage` 是整数；区分方案后两者都要带方案含义（要么码本身带前缀如 `sh_xs`，要么靠同行的 `scheme` 列解释）。如果阶段码带前缀，`Stage` Literal、`stage_to_index` 与所有 Literal 请求字段都要扩。

---

## 六、(e) 导入新种子时 `seed.py` 对已有行会不会更新 `stage_*` 与 `stage_min`？

### [stage-model-19] 会：UPSERT 的 `DO UPDATE` 覆盖全部种子列（含 4 个旗标与 `stage_min`），且只在有差异时写（事实，高）

`backend/wd/seed.py:72-82`：
```
INSERT INTO words(lemma, <SEED_COLUMNS>, source, is_public, is_valid_english, safe_for_sharing, created_at, updated_at) VALUES (…)
ON CONFLICT(lemma) DO UPDATE SET <c = excluded.c for c in SEED_COLUMNS>, source = 'seed', is_public = 1, is_valid_english = 1, safe_for_sharing = 1, merged_into_word_id = NULL, updated_at = excluded.updated_at
WHERE <words.c IS NOT excluded.c OR …> OR words.source IS NOT 'seed' OR words.is_public IS NOT 1 OR words.is_valid_english IS NOT 1 OR words.safe_for_sharing IS NOT 1 OR words.merged_into_word_id IS NOT NULL
```
`SEED_COLUMNS`（`:47-68`）包含 `stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min, cet6_star, sources`。被明确排除、永不触碰的列：`active_content_id, active_image_id, content_state, image_state, difficulty, created_by_user_id` 及所有每用户表（`:10-12` docstring）。`tests/unit/test_seed.py:190-206` 验证：改一条记录的 `stages` 后重导，`stats.updated == 1`，`stage_zk == 1 and stage_min == 1`，其他行原样。

触发时机：`import_seed`（`:260-263`）在 `kv.seed_version` 等于文件 sha256 时为 no-op，除非 `--force`；`main.py:307-319 seed_check` 在服务启动时发现 sha 不同就自动导入；`deploy/install.sh:140-141` 在 `wd migrate` 之后执行 `wd import-seed`。线上 `kv.seed_version = a68127812a43…`，`seed_imported_at = 2026-11-02T07:36:59Z`。

### [stage-model-20] 但当前代码会静默丢掉 `"xs"`，而且旧行的 `stage_xs` 只能靠新代码 + 新种子一起到位（事实 + 推断，高）

`seed.py:184-185` `stages = [s for s in STAGES if … s in raw_stages]`——`"xs"` 不在 `STAGES` 就被过滤；一条只有 `["xs"]` 的记录会以 `stage_min = NULL`（「outside the lists」）导入，只在「全部」页签可见（既有分析 seed-pipeline.txt 第 19 条同样结论）。因此：① 新种子可以先于代码发布而不出错，但无效果；② `stage_xs` 列不存在时，加了 `stage_xs` 的新 `SEED_COLUMNS` 会让 UPSERT 报「no such column」——所以 0011（加列）必须先于新代码的 `import-seed` 运行，`install.sh:140-141` 与 `main.py:482-485` 的「先迁移后导种子」顺序已经满足；③ `sources` 列是种子列，重导会把 `'sh_xs'` 之类的来源标记一并写入——如果走路线 B（[stage-model-17]），`sources` 可当作过渡期的人类可读来源，但不能替代索引化的 tag 表。

---

## 七、补充事实

### [stage-model-21] 迁移编号与文件规则（事实，高）

`db.py:41 MIGRATION_FILE_RE = r"^(\d{4})_([A-Za-z0-9][A-Za-z0-9_-]*)\.sql$"`；`list_migration_files` 对重复版本号抛 `MigrationError`（`:159-172`，`test_db.py:313-317`）；0002–0007 被预留后弃用（`0008_fk_child_indexes.sql` 头注释），下一个编号应为 0011。文件内不得 `COMMIT`/`ROLLBACK`（`db.py:232-234`），不得自写 `schema_migrations`（`0001_init.sql:30`），不得自己切换 `PRAGMA foreign_keys`（事务内是 no-op，`db.py:15-16`）。`test_db.py:78-105` 证明坏文件整体回滚、不留 bookkeeping 行。

### [stage-model-22] 既有分析的相关结论在 75df534 仍成立（事实，高）

`2026-11-04-library-curation/facts/schema-model.txt` 第 8 条（旗标 0/1 累积、`stage_min` 1-4、`difficulty` 1-5、索引 `ix_words_stage_min(stage_min, frq)`）与 `seed-pipeline.txt` 第 3 条（四个阶段轴、各阶段 = ECDICT 标签 ∪ 词表）、第 19 条（无 `stages` 的记录 `stage_min` 为 NULL）按当前代码逐行核对无误；本文件给出的行号均为 75df534 的。

---

## 未解决的问题

1. **小学词表与初中 2,099 词的重叠规模**——决定「仅初中新增」缩水幅度与 `docs/TASKS.md:174` 验收数字如何重写；没有小学清单无法计算（其他 slug 的产出）。
2. **难度尺子**：`difficulty` 1 是否改为「小学」；若改，`content_v1.json`/`lookup_v1.json`/`consolidate_v1.json` 的 `enum`、`ai/models.py` 四处 `Literal[1..5]`、`words.difficulty CHECK`、三份提示词与 `PROMPT_VERSION` 是否一起变。本文件只指出耦合（[stage-model-6]、[stage-model-9]），不做决定。
3. **「上海 / 全国」到底是成员差异还是只是年级边界差异**：若只是 5-4-3 与 6-3-3 的年级切分不同而词的阶段归属相同，一个 `scheme` 字段加前端文案就够，不需要 [stage-model-16]/[17] 的任一路线；需要产品/词表侧先回答。
4. **ECDICT 的完整 `tag` 取值集合**未在本机核实（`stardict.db` 位于禁止触碰的 `/Users/sqin/word-dance-data`），「ECDICT 没有小学标签」是基于 README 与项目 `EXAM_TAGS` 的中置信度推断。
5. **`docs/SCHEMA.sql` 的定位**（基线 vs 当前）需要项目决定；0011 之后它对 `stage_min`/`current_stage` 的 CHECK 描述将与线上不符。
6. **线上 2 个用户的迁移默认**：`current_stage=1/stages_json='["zk"]'` 的用户在引入小学后是否要自动加入小学阶段、`scheme` 默认取 `cn` 还是 `sh`——数据层面只有两行，但要在 0011 里写死规则。
7. 前端 `localStorage` 偏好（`ScreenPage.tsx:18 'wd.screenStage'`、词库页签）保存的是阶段码；新增 `xs` 无影响，若改码（如加 `sh_` 前缀）会让旧偏好失效——属前端 slug，未深究。
