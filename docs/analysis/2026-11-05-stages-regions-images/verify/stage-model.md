# verify: stage-model — 对抗性核验

基线：仓库 `/Users/sqin/word-dance`，`main @ 75df534`（`git rev-parse --short HEAD` = `75df534`），核验日期 2026-11-05。被核验文件：`docs/analysis/2026-11-05-stages-regions-images/facts/stage-model.md`（22 条编号结论 + 第二节改动面表格）。所有 `path:line` 相对仓库根；置信度：高 = 直接读到代码/数据或实测，中 = 代码推断，低 = 猜测。

## 范围与方法

**读了哪些文件**（逐条重开作者引用的行号核对原文）：`backend/wd/schemas.py`（20-70、446-460、486-490、553-562、706-710、1333-1337）、`seed.py`（1-15、40-90、178-212、215-268）、`services/words.py`（35-42、224-232、272-295、565-600）、`services/ecdict.py`（24-32、168-182）、`services/screen.py:30-55`、`services/batches.py`（55-65、228-236、268-276、310-320、694-700）、`routers/vocab.py:45-100`、`services/stats.py:170-196`、`services/bank.py`（80-90、160-190）、`security.py`（585-616、655-668）、`routers/onboarding.py:30-40`、`routers/settings.py:85-120`、`routers/admin_ops.py:375-385`、`routers/screen.py:18-25`、`migrations/0001_init.sql`（26-37、139-161、166-210、570-584）、`0008_fk_child_indexes.sql`（头注释）、`0010_ai_provider.sql`（全文）、`db.py`（10-20、38-52、155-175、195-250）、`ai/prewarm.py:28-45`、`ai/content.py`（44-50、80-94、226-236）、`ai/lookup.py:350-357`、`ai/consolidate.py:278-312`、`ai/models.py`、`ai/prompts/*.txt`、`ai/schemas/*.json`、`main.py`（305-320、478-488）、`backup.py:280-296`、`deploy/install.sh:115-145`、`scripts/check_contract.py`（150-172、268-285）、`scripts/build_seed.py`（1-15、78-110、145-152、186-193）、`scripts/smoke.py:350-354, 612-616`、`scripts/eval_provider.py:338-346`、`data/seed/stats.json`、`data/seed/ATTRIBUTION.md`、`docs/SCHEMA.sql`（与 0001 `diff`）、`docs/API.md`、`docs/DESIGN.md`、`docs/DEPLOY.md`、`docs/FRONTEND.md`、`docs/TASKS.md`、`README.md` 的全部被引行、`backend/tests/unit/test_db.py`（10-62、76-106、125-235、236-260、282-320、360-368）与作者引用的其余测试行、`frontend/src/api/types.ts`、`api/endpoints.ts`、`components/word/StageChips.tsx`、`pages/{ScreenPage,VocabPage,WelcomePage,AdminPage}.tsx`、`i18n/zh.ts`，以及 `docs/analysis/2026-11-04-library-curation/facts/{schema-model,seed-pipeline}.txt` 的被引条目。

**全库 grep**（`backend/wd`、`scripts`、`frontend/src`）：`"zk", "gk", "cet4", "cet6"`、`current_stage`、`stage_min`、`\bsources\b`、`v_bank`、`settings_json`、`difficulty = ?`、`STAGE_ZH|STAGE_NAMES_ZH`、`\bDifficulty\b`、`INSERT INTO user_settings`、`VACUUM`、前端测试文件里的阶段字面量（严格词边界 `\b(zk|gk|cet4|cet6)\b` 与宽松子串两种口径）。

**只读查询线上库副本** `…/scratchpad/live-copy.db`（`sqlite3 -readonly`）：`schema_migrations`；`words` 的阶段计数、`stage_min` 分布、旗标组合、`source`、`difficulty`、`content_state`、可见性三元组；`users`、`user_settings`、`push_batches.settings_json`；`kv.seed_*`；`words`/`user_settings` DDL、视图与索引清单；对全部 25 张表跑 `pragma_foreign_key_list` 找引用 `words`/`user_settings` 的外键；三条选词 SQL 的 `EXPLAIN QUERY PLAN` 与 `time` 计时。

**自己重算**：`python3 -I …/verify-stage-model/seedstats.py data/seed/vocab.jsonl.gz backend/tests/fixtures/mini_seed.jsonl`（统计 `stages` 的 per_stage / first / 无阶段数）；`shasum -a 256 data/seed/vocab.jsonl.gz`。

**独立重跑重建探针**（不复用作者脚本；自写 `…/scratchpad/verify-stage-model/probe/probe.py`，用 `.venv/bin/python` = Python 3.12.16 / SQLite 3.54.1，`sys.path` 指向 `backend` 调用真实的 `wd.db.run_migrations`，跑在 `live-copy.db` 的私有拷贝上）：变体 A（重建 `words`，不处理视图）、B（先 `DROP VIEW v_bank`、重建后 `CREATE VIEW`）、C（重建 `user_settings`）、E（只 `ALTER TABLE words ADD COLUMN stage_xs`，不放宽 CHECK）。另用 `/usr/bin/sqlite3` CLI 在另一份拷贝上执行同样的「不删视图」重建 SQL，分别在 CLI 默认与 `PRAGMA legacy_alter_table=OFF` 下运行；用 CLI 验证 `ALTER TABLE ADD COLUMN … GENERATED ALWAYS AS (…) VIRTUAL` 与 `STORED`。

**联网**：WebFetch `https://raw.githubusercontent.com/skywind3000/ECDICT/master/README.md`（核对 tag 行原文、搜「小学」；访问 2026-11-05）、`https://sqlite.org/lang_altertable.html`（支持的 ALTER 操作、12 步重建流程、ADD COLUMN 对生成列的限制；访问 2026-11-05）、`https://github.com/yinyanfr/ecdict/blob/HEAD/docs/README.en.md`（找 tag 全集的第二来源；访问 2026-11-05）；WebSearch「ECDICT stardict tag 字段 … 全部取值」「sqlite3 command-line shell legacy_alter_table enabled by default」。复用作者下载的 `…/scratchpad/stage-model/dl-ecdict-readme/README.md`（18,414 字节，只 `grep`）。本次没有新的落盘下载。

**没做的**：未重跑作者的变体 D（两表同一文件）；未触碰 `/Users/sqin/word-dance-data`、仓库与 `live-copy.db` 本身。

---

## 逐条核验

### [stage-model-1] 阶段清单的副本数 — **修正**（数字；其余事实确认）

- 核对无误：`schemas.py:25` `Stage = Literal["zk", "gk", "cet4", "cet6"]`、`:26` `StageIndex = Literal[1, 2, 3, 4]`、`:51` `STAGE_ORDER`、`:52` `STAGE_NAMES_ZH`；`seed.py:43`、`services/words.py:39`、`services/ecdict.py:28`、`ai/prewarm.py:32-33`、`ai/content.py:49`；请求 Literal `schemas.py:488`、`:708`、`:1335`（`grep -rn '"zk", "gk", "cet4", "cet6"' backend/wd scripts` 全部命中，无遗漏）。前端 `types.ts:5-6`、`StageChips.tsx:7-9`、`zh.ts:28`、`VocabPage.tsx:29`、`AdminPage.tsx:36`、`WelcomePage.tsx:33-38, 42`、`ScreenPage.tsx:20` 行号准确。`check_contract.py:274-281` 的比对确实覆盖整数联合 `StageIndex`：`parse_types_ts`（`:157-170`）对 `export type X = …` 的成员既收 `'…'` 字符串也收整数——`:164-165` `elif re.fullmatch(r"-?\d+", p): values.append(int(p))`。
- 修正：标题「6 个模块里各存一份（9 个常量）」——按作者自己列出的清单是 **10 个**：schemas 4（`Stage`/`StageIndex`/`STAGE_ORDER`/`STAGE_NAMES_ZH`）+ seed 1 + words 1 + ecdict 1 + prewarm 2（`STAGE_COLUMNS`/`STAGES`）+ content 1 = 10。另有两处同类字面量未计入：`services/bank.py:85` `DEFAULT_STAGES = ("cet4", "cet6")` 与 `scripts/eval_provider.py:107` `STAGES`。置信度高（事实）。

### [stage-model-2] 整数索引同时承担身份与顺序 — **确认**

`schemas.py:58` `return STAGE_ORDER.index(stage) + 1`；`:65-67` `if not 1 <= int(index) <= 4: raise ValueError(…) / return STAGE_ORDER[int(index) - 1]`；`seed.py:208` `(STAGES.index(stages[0]) + 1) if stages else None`；`ecdict.py:177` 同式；`0001_init.sql:147-148, 185` CHECK 原文一致；副本 `sqlite_master` 中 `words`/`user_settings` 的 DDL 含 `stage_min INTEGER CHECK (stage_min BETWEEN 1 AND 4)`、`current_stage INTEGER NOT NULL DEFAULT 3 CHECK (current_stage BETWEEN 1 AND 4)`，与 0001 逐字相同；`bank.py:85-86, 172-173`；`API.md:460`「the server maps `zk→1, gk→2, cet4→3, cet6→4` to `user_settings.current_stage` and back」；`DESIGN.md:72`「(stage index 1–4)」。置信度高。

### [stage-model-3] `stage_min` 的 5 个消费点与索引使用 — **确认**（补两处读取者）

五处原文核对无误：`vocab.py:55` `where.append("w.stage_min = :stage_idx")`；`vocab.py:89` 与 `stats.py:180` 同一句 `COALESCE(SUM(w.stage_min = :idx), 0)`；`screen.py:35` 与 `batches.py:60` 的 `CASE WHEN w.stage_min = :cur THEN 0 WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END` 逐字相同；`vocab.py:78` `"COALESCE(w.difficulty, w.stage_min, 5), …"`；`prewarm.py:37-38`。`EXPLAIN QUERY PLAN` 复现：new_only 查询 `SEARCH w USING INDEX ix_words_stage_min (stage_min=?)` + `USE TEMP B-TREE FOR ORDER BY`；筛词查询 `SEARCH w USING INDEX ix_words_public (is_public=? AND is_valid_english=?)` + `USE TEMP B-TREE FOR ORDER BY`；`/api/stages` 计数 `SEARCH w USING INDEX ix_words_public (is_public=?)`。`time sqlite3 -readonly … LIMIT 15` = 0.014 s total，与作者一致。
补充（`grep -rn stage_min backend/wd` 的其余命中）：`services/words.py:277` `"stage_min": r.get("stage_min")` 把值送上线（`schemas.py:472` `WordBrief.stage_min: StageIndex | None`，前端 `StageChips.tsx:31` 据此高亮），以及视图 `v_bank`（`0001_init.sql:573` 选出 `w.stage_min`）。前者作者在 [8] 用到但未计入「消费点」；办法 3（字符串列）会同时改变二者的类型。

### [stage-model-4] 线上数据 — **确认**（全部数字复算一致）

`SELECT COUNT(*), SUM(stage_zk), SUM(stage_gk), SUM(stage_cet4), SUM(stage_cet6), SUM(stage_min IS NULL) FROM words` → `9162|2099|3829|4722|7671|0`；`GROUP BY stage_min` → 1:2099、2:1792、3:1577、4:3694；`GROUP BY source` → `seed|9162`；`SELECT COUNT(*) FROM words WHERE stage_min IS NOT (CASE WHEN stage_zk=1 THEN 1 WHEN stage_gk=1 THEN 2 WHEN stage_cet4=1 THEN 3 WHEN stage_cet6=1 THEN 4 END)` = 0；旗标组合 `SELECT COUNT(*) FROM (SELECT DISTINCT stage_zk||stage_gk||stage_cet4||stage_cet6 FROM words)` = 15，各组计数 0001 3694 / 0011 1512 / 0111 1156 / 1110 1019 / 1111 854 / 0101 349 / 0100 193 / 0110 94 / 1101 85 / 1100 79 / 0010 65 / 1000 33 / 1011 14 / 1010 8 / 1001 7，与原文逐一相同；`users` 2 行；`user_settings` = `(1, 3, ["zk","gk","cet4","cet6"])`、`(2, 1, ["zk"])`；`push_batches` 4 行、4 行含 `"current_stage": 3`；`grep -rn settings_json backend/wd`（非测试）只命中 `batches.py:316` 的 INSERT（只写不读成立）。种子文件 `python3 -I` 复算：per_stage zk 2099 / gk 3829 / cet4 4722 / cet6 7671，first zk 2099 / gk 1792 / cet4 1577 / cet6 3694，no_stage 0，与 `data/seed/stats.json` 一致。置信度高。

### [stage-model-5] 选词 SQL 按列名拼模板 — **确认**

`vocab.py:53` `f"w.stage_{q.stage} = 1"`、`:91` `f"{_FROM} WHERE w.stage_{stage} = 1 AND …"`、`stats.py:183`、`screen.py:52` `" OR ".join(f"w.stage_{s} = 1" for s in stages)`、`batches.py:233`（多一个 `if s in words.STAGES` 过滤）、`prewarm.py:39` `f"w.{STAGE_COLUMNS[stage]} = 1"`、`words.py:229` `row.get(f"stage_{s}")`、`eval_provider.py:342` `… AND stage_{stage} = 1 …`。全部命中。

### [stage-model-6] AI 侧的阶段中文名与难度尺子 — **确认**

`content.py:48-49`、`:88` `"stages": [STAGE_ZH[s] for s in words.stages_of(word)]`（`STAGE_ZH` 只有 4 键，`KeyError` 风险成立）；`content_system.txt:1`「(初中, 高中, CET-4, CET-6 and working professionals)」、`:11`「difficulty: integer 1–5 (1 = 初中 basic, 2 = 高中, 3 = CET-4, 4 = CET-6, 5 = beyond CET-6)」；`consolidate_system.txt:11`「(1 初中 … 5 beyond CET-6)」；`content_v1.json:11` `"enum":[1,2,3,4,5]`（`lookup_v1.json:11`、`consolidate_v1.json:8, 11` 同）；`ai/models.py:44/61/76/90` `difficulty: Literal[1, 2, 3, 4, 5]`；`0001_init.sql:195`；写入点 `content.py:230-234`（`if force or word.get("difficulty") is None`）、`lookup.py:353-355`、`consolidate.py:282-285, 308-311`。副本：`difficulty` 非空 49 行，分布 1:2 / 2:1 / 3:43 / 4:3；`content_state='ready'` 且非空 = 49；`content_state` 分布 none 9113 / ready 49。置信度高。关于尺子的硬编码位置清单不全，见遗漏 3。

### [stage-model-7] 构建器只认 4 个 ECDICT 标签；小学没有现成输入 — **确认**（推断部分维持「中」）

`build_seed.py:105-106` `' '||tag||' ' like '% zk %' or … '% cet6 %'`、`:82-87` 六个词表文件、`:150` `order = {"zk": 0, "gk": 1, "cet4": 2, "cet6": 3}` 行号准确；`:147` 与 `:191` 也把 `stages` 过滤到这 4 个码。ECDICT README：本地文件第 40 行与线上 `https://raw.githubusercontent.com/skywind3000/ECDICT/master/README.md`（访问 2026-11-05）原文均为「| tag | 字符串标签：zk/中考，gk/高考，cet4/四级 等等标签，空格分割 |」，全文无「小学」。`seed.py:44`/`ecdict.py:29` `EXAM_TAGS = ("ky", "toefl", "ielts", "gre")`；`seed.py:184-185` `stages = [s for s in STAGES if isinstance(raw_stages, (list, tuple)) and s in raw_stages]` 确会静默丢弃 `"xs"`。
「ECDICT 没有小学标签」：README 以「等等」收尾，第二来源 yinyanfr/ecdict `docs/README.en.md`（访问 2026-11-05）只写「Tags: zk: junior high school level; gk/ college entrance exam level; cet: cet4 level」，同样不枚举全集、也无小学标签。没有一手来源枚举 tag 全集，这一句维持作者标注的「推断（中）」。

### [stage-model-8] 只改常量不迁数据会整体错位 — **确认**

推导链每一环都在代码里：`schemas.py:58` 按位置算索引；`words.py:277` 原样回传 `stage_min`；`StageChips.tsx:31` `stageMin === STAGE_INDEX[stage] && 'chip--min'`；`security.py:597` `"current_stage": index_to_stage(int(row["current_stage"]))`；`vocab.py:87-89` 用 `stage_to_index(stage)` 作 `:idx` 去 `SUM(w.stage_min = :idx)`——`zk` 变 2 后会数到今天的 1,792。部署顺序：`install.sh:122` `run sudo -n systemctl stop word-dance.service` → `:140` `wd migrate` → `:141` `wd import-seed`；`main.py:482-485` `run_migrations` 后 `seed_check`。`DEPLOY.md:421` 原文：「With `--no-restart` the service keeps running during `wd migrate`, which is safe **only for purely additive migrations** (new tables/columns/indexes … never `DROP`/`RENAME`/type changes)」。置信度高。

### [stage-model-9] 三种办法与代价 — **修正**（办法 1' ② 的难度尺子清单不全；其余确认）

- 办法 1 的 0 值陷阱是事实：`screen.py:44` `cur = int(s["current_stage"] or bank.DEFAULT_CURRENT_STAGE)`、`batches.py:272` 与 `:698` `int(… .get("current_stage") or bank.DEFAULT_CURRENT_STAGE)`；`grep -rn current_stage backend/wd` 没有第四处同型写法。`COALESCE(difficulty, stage_min, 5)` 对 0 取 0、排最前——成立。
- 办法 2「`ALTER TABLE ADD COLUMN` 可加 VIRTUAL 生成列」：CLI 实测 `ALTER TABLE t ADD COLUMN stage_rank INTEGER GENERATED ALWAYS AS (CASE stage_min WHEN 5 THEN 0 ELSE stage_min END) VIRTUAL` 成功、能查出值，`… STORED` 报「cannot add a STORED column」；`https://sqlite.org/lang_altertable.html`（访问 2026-11-05）：「The column may not be GENERATED ALWAYS ... STORED, though VIRTUAL columns are allowed」。
- 办法 3 引用的 `API.md:239-240`（`Stage`/`StageIndex`）、`:286`（`stages: Stage[]; stage_min: StageIndex | null;`）与 `types.ts:5-6, 45, 52` 行号准确。
- 修正：办法 1' ② 写「`CHECK BETWEEN 1 AND 5` 与四处 `Literal[1..5]`、三个 JSON schema 的 `enum` 都要改」，漏了 API 契约层的两处同尺子：`schemas.py:47` `Difficulty = Literal[1, 2, 3, 4, 5]`（被 `:559` `class Content … difficulty: Difficulty` 使用）与 `frontend/src/api/types.ts:73` `difficulty: 1 | 2 | 3 | 4 | 5`（`types.ts:1-2`「FROZEN CONTRACT: this file is API.md §9 copied verbatim … Any change requires updating API.md, backend/wd/schemas.py and this file in one "contract change" commit」）。任何把尺子扩到 6 的方案都要同提交改这两处与 `API.md §9`。置信度高。

### [stage-model-10] 「仅初中新增」会缩水 — **确认**

`0001_init.sql:185` 注释「lowest stage 1=zk 2=gk 3=cet4 4=cet6; NULL = outside the 4 lists」；`DESIGN.md:186`「`stage_min` (1–4, lowest stage; `NULL` = outside the four lists)」；`TASKS.md:174` 断言 `==(2099,1792,1577,3694)`；`FRONTEND.md:235` `newOnlyCet6: '仅六级新增（不含四级）'`；`VocabPage.tsx:202` `const newOnlyLabel = tab === 'cet6' ? zh.stages.newOnlyCet6 : zh.stages.newOnly;` 只对 cet6 特判。幅度未知，如作者所述。

### [stage-model-11] 不能原地改 CHECK；运行器支持重建 — **确认**

`db.py:222-226` 注释原文「SQLite's table-rebuild recipe (CREATE new → INSERT … SELECT → DROP old → RENAME) is the only way to change a CHECK list」；`:227` `conn.execute("PRAGMA foreign_keys=OFF")`、`:231` `conn.executescript(sql)`、`:235-238` `foreign_key_check`、`:239` 运行器 `INSERT INTO schema_migrations`、`:246` `finally: conn.execute("PRAGMA foreign_keys=ON")`；`0001_init.sql:31-36`。`test_db.py:132-211`：`REBUILD_USERS_SQL`（`:132`）+ `USER_CHILD_TABLES`（`:155`）恰为 8 张（user_settings, sessions, user_words, review_logs, daily_stats, push_batches, push_items, email_codes），`:199` `assert _counts(c) == before`。`DEPLOY.md:421`「A table rebuild (the only way to change a CHECK list in SQLite) is an ordinary stop-first migration: the runner turns foreign-key enforcement off around the file and runs `foreign_key_check` before committing」。`backup.py:290-292` `if from_version <= 0: … return`。`0010_ai_provider.sql` 是 `ALTER TABLE ai_calls ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude' CHECK (…)` 先例。我的变体 E 证实「加列 additive 但解决不了范围」：只 `ADD COLUMN stage_xs` 后 `UPDATE words SET stage_min = 0` 仍报 `CHECK constraint failed: stage_min BETWEEN 1 AND 4`。SQLite 官方文档（上述 URL，访问 2026-11-05）：ALTER TABLE 仅支持 rename table / rename column / add column / drop column。置信度高。

### [stage-model-12] 实测重建通过、毫秒级 — **确认**（独立复现 A/B/C；D 未重跑）

我的探针（SQLite 3.54.1，`PRAGMA legacy_alter_table` = 0，版本 10 → 11，拷贝 5,644,288 字节）：
- C（只重建 `user_settings`，CHECK → `BETWEEN 0 AND 5`）：`applied=[(11, 'probe')]`，0.007 s（作者 0.009 s）；12 张表行数不变；`foreign_key_check` 空；`integrity_check` = ok；`UPDATE user_settings SET current_stage = 0` 被接受。对副本 25 张表跑 `pragma_foreign_key_list`，没有任何表引用 `user_settings`——与作者一致。
- B（重建 `words` + `stage_xs` + CHECK `0..5`，前后 `DROP VIEW v_bank` / `CREATE VIEW v_bank`）：0.039 s（作者 0.041 s）；行数不变；`words` 上 6 个索引重建；`INSERT … stage_min=0` 成功，`stage_min=6` 报 `CHECK constraint failed: stage_min BETWEEN 0 AND 5`。引用 `words` 的外键恰 9 条：`words.merged_into_word_id SET NULL`、`word_forms.word_id`/`word_contents.word_id`/`word_images.word_id`/`user_words.word_id`/`push_items.word_id`/`content_reports.word_id` CASCADE、`user_words.suggested_word_id SET NULL`、`bank_suggestions.target_word_id SET NULL`——与作者列表完全一致。
- D 未独立重跑（B、C 分别通过；作者产物 `…/stage-model/rebuild/D-both.db` 存在）。置信度高。

### [stage-model-13] `v_bank` 让 RENAME 失败；CLI 的 `legacy_alter_table` 差异 — **确认**（CLI 部分由推断升级为实测）

变体 A 复现同一错误：`MigrationError: migration 0011_probe.sql failed and was rolled back: error in view v_bank: no such table: main.words`，之后 `current_version` = 10、`in_transaction=False`、`foreign_keys=1`。CLI：`/usr/bin/sqlite3` 3.51.0 对 `live-copy.db` 与 `:memory:` 均报 `PRAGMA legacy_alter_table` = **1**；同一份「不删视图」重建 SQL 经 CLI 执行**成功**（`CLI rename OK|9162`），前置 `PRAGMA legacy_alter_table=OFF;` 后**失败**（`Parse error near line 48: no such table: words`）。所以「用 CLI 排练可能通过而应用运行时失败」是实测事实，不只是推断。CLI 为何默认 1（Apple 构建还是上游 shell 行为）未查明，不影响结论。`grep -rn v_bank backend/wd scripts docs` 只命中 `docs/SCHEMA.sql:572`、0001 与本次分析文档；`test_db.py:52` `assert db.view_names(c) == ["v_bank"]`。SQLite 文档 12 步流程（访问 2026-11-05）第 8 步「Use CREATE INDEX, CREATE TRIGGER, and CREATE VIEW to reconstruct indexes, triggers, and views」、第 9 步「If any views refer to table X in a way affected by the schema change, drop those views and recreate them」——官方流程同样要求重建视图，与作者结论相符。置信度高。

### [stage-model-14] `docs/SCHEMA.sql` 是 0001 的字节拷贝 — **确认**

`diff docs/SCHEMA.sql backend/wd/migrations/0001_init.sql` 无输出；`grep -c 'provider TEXT' docs/SCHEMA.sql` = 0；`test_db.py:362-366` `assert docs.read_bytes() == (db.MIGRATIONS_DIR / "0001_init.sql").read_bytes()`。

### [stage-model-15] 模型只有「阶段」一维 — **确认**

`0001_init.sql:181-185`、`:147-148`、`:188` `sources TEXT, -- provenance, e.g. 'cet4 cet46 ecdict gk zk'`；`grep -rn '\bsources\b' backend/wd`（非测试）只命中 `seed.py:7, 66, 189, 210`、`ecdict.py:179`、`words.py:582, 591, 594` 与 0001——全是写入/列清单，没有读取者。

### [stage-model-16] 路线 A（多加列）— **确认**（推断，与代码一致）

涉及点都存在：`vocab.py:86` / `stats.py:177` 的 `for stage in STAGE_ORDER` 循环、`seed.py:47-68 SEED_COLUMNS`、`words.py:589-597 _INSERT_WORD_SQL`、`ecdict.py:173-180`（`word_columns` 字典的阶段列）。「加列 additive 无需重建」有 0010 先例与我的变体 E（0.018 s 通过，行数不变）佐证。

### [stage-model-17] 路线 B（tag 表）— **确认**（推断，未实测）

`test_db.py:13-17 EXPECTED_TABLES` 25 项、`:51 assert len(tables) == 25`；`seed.py:218-245 _rebuild_forms` 的「删后重灌」模式；`words.py:291 word_briefs` 批量构造。行数估算：旗标总和 2099+3829+4722+7671 = 18,321 行（作者「≈ 2 万」量级正确；平均 18321/9162 = 2.0 个阶段/词）。性能结论未实测，与作者标注一致。

### [stage-model-18] API / 前端耦合 — **确认**

`API.md:167`「**19 `GET /api/stages`** → `{items: StageInfo[]}` (4 rows, …)」；`API.md:278-282` `export interface StageInfo { stage: Stage; index: StageIndex; name_zh: string; …}`；`schemas.py:448-457`；`ScreenPage.tsx:31` `STAGE_ORDER.map((s) => data.items.find((i) => i.stage === s)).filter(…)`——只保留前端已知的阶段；`VocabPage.tsx:29 TABS`；`StageChips.tsx:7-9`；`security.py:612-614 stages_json`。

### [stage-model-19] UPSERT 覆盖阶段列且只在有差异时写 — **确认**

`seed.py:72-82` `_UPSERT_SQL` 原文与作者摘录一致（`ON CONFLICT(lemma) DO UPDATE SET <c = excluded.c …> … WHERE <words.c IS NOT excluded.c OR …> OR words.source IS NOT 'seed' …`）；`SEED_COLUMNS`（`:47-68`）含 `stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min, cet6_star, sources`；`:10-12` docstring 列出永不触碰的列；`test_seed.py:190-206` 断言 `(stats.inserted, stats.updated, stats.up_to_date) == (0, 1, False)` 与 `ab["stage_zk"] == 1 and ab["stage_min"] == 1`、`word(conn, "apple") == apple_before`；`import_seed` `:260-263`；`main.py:307-319 seed_check`；`install.sh:140-141`。副本 `kv.seed_version` = `a68127812a43c47ff011828b7894b789ba0fcf69cc8e76f1ec6c2356e81a3336` = `shasum -a 256 data/seed/vocab.jsonl.gz`；`seed_imported_at` = `2026-11-02T07:36:59Z`。

### [stage-model-20] 静默丢 `"xs"`；迁移先于导种子 — **确认**

`seed.py:184-185` 过滤成立；`_UPSERT_SQL` 由 `SEED_COLUMNS` 生成，列不存在时 SQLite 报 `no such column`——逻辑成立；`install.sh:140-141` 与 `main.py:482-485` 顺序已核。

### [stage-model-21] 迁移编号与文件规则 — **确认**

`db.py:41` `MIGRATION_FILE_RE = re.compile(r"^(\d{4})_([A-Za-z0-9][A-Za-z0-9_-]*)\.sql$")`；`:159-172 list_migration_files` 对重复版本 `raise MigrationError`；`test_db.py:313-317`；`db.py:232-234` 文件内 COMMIT 检测；`:15-16` 事务内 PRAGMA 为 no-op；`0001_init.sql:30`；`0008` 头注释「Numbers 0002–0007 were pre-allocated to the work packages and left unused」；`ls backend/wd/migrations` = 0001 / 0008 / 0009 / 0010，下一个 0011；`test_db.py:78-105` 坏文件整体回滚且 `versions == [1]`。

### [stage-model-22] 既有分析仍成立 — **确认**

`schema-model.txt` 第 8 条（旗标 0/1 累积、`stage_min` 1-4、`difficulty` 1-5、`ix_words_stage_min(stage_min, frq)`）、`seed-pipeline.txt` 第 3 条（四个阶段轴 = ECDICT tag ∪ 词表）与第 19 条（无 `stages` → `stage_min` NULL、只在 `stage=all` 下可见）均与 75df534 的 `0001_init.sql:181-185, 207`、`build_seed.py:1-15, 105-106`、`seed.py:184-185, 208` 相符。

### 第二节表格「前端」行：「19 个 `*.test.ts(x)` 含阶段字面量（SettingsPage.test 6 处、BankPage.test 7 处、WelcomePage.test 4 处）」— **修正**（口径）

数字只在宽松子串口径下成立：`grep -rl "zk\|gk\|cet4\|cet6" --include='*.test.ts' --include='*.test.tsx' frontend/src | wc -l` = 19，三文件行数 6 / 7 / 4——该口径把 `zkFull`、`gkFull` 等也算进去。按词边界 `\b(zk|gk|cet4|cet6)\b`：**16** 个文件，`SettingsPage.test.tsx` 6 行（28 次出现）、`BankPage.test.tsx` 4 行、`WelcomePage.test.tsx` 3 行。非测试源文件含引号阶段字面量的恰 5 个（`StageChips.tsx`、`types.ts`、`AdminPage.tsx`、`WelcomePage.tsx`、`VocabPage.tsx`），与「5 份」相符。

---

## 作者遗漏的重要事实

1. **新用户的默认受众写死在 DDL 默认值里，注册只依赖默认值**（事实，高）。`security.py:662-663` `INSERT INTO user_settings(user_id, next_push_at, updated_at) VALUES (?, ?, ?)` 不写 `stages_json`/`current_stage`，新用户因此拿到 `0001_init.sql:147-148` 的 `DEFAULT '["cet4","cet6"]'`、`DEFAULT 3`（四级/六级），`bank.py:85-86` 又复制了一份兜底。面向上海小学/初中/高中的产品若要让新用户默认落在 K-12 阶段，要么改这条 INSERT，要么改列 DEFAULT——SQLite 不支持 `ALTER COLUMN`，改 DEFAULT 同样只能靠整表重建，应与 0011 的 `user_settings` 重建合并在同一次停机。相关文案也写死：`FRONTEND.md:50`「初中生 / 高中生 / 大学生 / 职场人士」、`WelcomePage.tsx:30` `export type Role = 'zk' | 'gk' | 'uni' | 'pro'`、`content.py:48` `AUDIENCE = "… plus working professionals"`。

2. **0011 的回滚路径没有讨论**（事实，高）。`DEPLOY.md:421`：「Rollback: `git checkout <previous tag> && deploy/install.sh` (stops, migrates nothing new, restarts); if a migration must be undone, `sudo systemctl stop word-dance && wd restore backups/pre-migrate-*.db.gz && sudo systemctl start word-dance`」——撤销迁移 = 恢复迁移前快照，快照之后的学习记录全部丢失。只回退代码、保留新库则直接出错：旧代码 `schemas.py:65` `if not 1 <= int(index) <= 4: raise ValueError` 让 `security.py:597` 对任何已选小学的用户（`current_stage` 为 0 或 5）在 `GET /api/settings` 等返回 500；`bank.py:181` `[s for s in stages if s in words.STAGES] or list(DEFAULT_STAGES)` 会把 `["xs"]` 静默换成四六级。结论：阶段方案一旦上线且有用户选择小学，就不存在「只回代码」的回滚，只剩快照恢复——应写进 0011 的发布说明。

3. **难度尺子还有两处 API 契约层的硬编码**（事实，高）。`schemas.py:47` `Difficulty = Literal[1, 2, 3, 4, 5]` → `:559` `Content.difficulty: Difficulty`；`frontend/src/api/types.ts:73` `difficulty: 1 | 2 | 3 | 4 | 5`（`types.ts:1-2` 的「FROZEN CONTRACT」声明）。作者在 [6]/[9]/未解决问题 2 列的是 `ai/models.py` 四处、三个 JSON schema、DB CHECK 与提示词，漏了这两处；若把 1 让给小学或扩到 6，它们和 `API.md §9` 必须同提交改。

4. **重建 `words` 会让数据库文件膨胀，而项目里没有对线上库的 `VACUUM`**（事实，高；影响为推断，低）。探针变体 B 后文件从 5,644,288 字节涨到 9,449,472 字节（`PRAGMA wal_checkpoint(TRUNCATE)` 后 `PRAGMA freelist_count` = 938 页），作者自己的 `B-words-dropview.db` 同为 9,449,472 字节。`grep -rn VACUUM backend/wd deploy` 只有 `backup.py:158` `conn.execute("VACUUM INTO ?", …)`（备份用）。9 MB 规模无实际影响，但 0011 发布说明应注明文件不会自动收缩；迁移文件内也做不了（运行器把文件包在事务里，`VACUUM` 不能在事务内执行），只能迁移后手动 `VACUUM`。

5. **官方一手来源可直接佐证 [11]/[13]，作者只引了项目自己的注释**（事实，高）。`https://sqlite.org/lang_altertable.html`（访问 2026-11-05）：ALTER TABLE 只支持 rename table / rename column / add column / drop column；12 步流程第 8-9 步要求重建视图；ADD COLUMN「may not be GENERATED ALWAYS ... STORED, though VIRTUAL columns are allowed」。加上本机实测：`/usr/bin/sqlite3` 的 `legacy_alter_table` = 1 会掩盖视图问题（见 [13]）。

6. **`stage_min` 还有两个未计入的读取者**（事实，高）：`services/words.py:277` 经 `WordBrief.stage_min`（`schemas.py:472`、`API.md:286`）送到前端用于 `StageChips.tsx:31` 高亮；视图 `v_bank` 选出 `w.stage_min`（`0001_init.sql:573`）。办法 3（字符串列）会同时改变这两处的类型，办法 1 / 1' 会改变前者的取值含义。

---

## 未解决的问题

1. ECDICT `tag` 的完整取值集合仍无一手来源枚举（README 用「等等」，派生 README 也只列 zk / gk / cet），「没有小学标签」维持推断；`stardict.db` 在禁区 `/Users/sqin/word-dance-data` 内，无法本机核实。
2. `/usr/bin/sqlite3` 默认 `legacy_alter_table` = 1 是 Apple 构建特性还是上游 shell 行为未查明（WebSearch 只确认 shell 有 `.dbconfig legacy_alter_table` 开关）；对结论无影响——排练一律走 `run_migrations`。
3. 作者的变体 D（两表同一文件）未独立重跑。
4. 生产服务器（Linux）的 Python / SQLite 版本未知；本次与作者的重建耗时、`legacy_alter_table` 取值都只在 macOS / SQLite 3.54.1（`.venv`）上测得。

---

核验 23 条：确认 20、修正 3、推翻 0、无法核验 0。
