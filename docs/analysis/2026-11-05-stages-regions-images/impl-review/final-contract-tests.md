# 最终评审 · 契约 / 镜像 / 测试纪律（对抗式）

评审对象：工作区全部改动（`git diff 75df534` + `git status` 新文件，139 条；HEAD `0a62322` 的 `docs/analysis/`、`data/lists/` 11 个官方词表文件随基线计入）。规格：PLAN §0、§1（R-1/R-2/R-12/R-13/R-14/R-17）、§2.2–2.5、§3 全部、§4.7、§6（S1–S7 的契约条款）、§7.1–7.2。本评审只报告跑过命令或读过代码并能引用位置的问题；评审过程中的临时突变全部已恢复（`cmp` 逐文件核对，`git status --short | wc -l` 前后均为 139，无新增杂散文件）。

## 0 结论

**通过。无 blocker、无 major；5 条 minor（全是陈旧文案/数字，另有 1 条出 PLAN 范围但已文档化且有测试的行为改动需在门禁记录里补一笔）。** 所有契约与镜像验收命令复跑全绿；`docs/API.md §9` 代码块与 `frontend/src/api/types.ts` 正文 216 行逐字相同；三份迁移文件与 PLAN §2.2–2.4 的 SQL 块逐字相同（0011 只有 PLAN 明示允许的注释令牌示例一处不同）；全仓库四阶段字面量检索后逐处判断，剩余命中均为「按设计保留」（`ecdict.STAGE_TAGS`、`seedbuild/diff.V1_ORDER`、旧索引迁移测试夹具、`docs/SCHEMA.sql` 基线）或与阶段无关；8 处人工突变全部被新增/改写的测试捕获（任务要求 ≥ 5）。

## 1 验收命令复跑（全部在本工作区、本次评审中执行）

| 命令 | 结果 |
|---|---|
| `.venv/bin/python scripts/check_contract.py` | `compared 44 interfaces and 15 literal unions … contract OK: no property-name or literal-union mismatch`，exit 0 |
| `.venv/bin/python -m pytest -q backend/tests/unit/test_schemas.py backend/tests/unit/test_docs_contract.py` | `30 passed in 1.74s` |
| `.venv/bin/python -m pytest -q backend/tests/unit/test_db.py -k schema` + `cmp docs/SCHEMA.sql backend/wd/migrations/0001_init.sql` | `3 passed`；`cmp` 无输出（字节一致）；两文件对 75df534 的 `git diff --stat` 为空 |
| `cd frontend && npx vitest run src/i18n` | `Test Files 2 passed · Tests 9 passed`（`zh.test.ts` 逐行比对 `FRONTEND.md §8`，`zh.contract.test.ts`） |
| `.venv/bin/python -m pytest -q backend/tests -k "not test_deploy_files and not test_defaults_without_environment"` | `1946 passed, 3 skipped, 34 deselected in 215.98s`，exit 0（与门禁自报一致） |
| `.venv/bin/python -m pytest -q backend/tests/unit/test_deploy_files.py -k env_example` | `4 passed, 29 deselected` —— 该文件在 Mac 上整体被排除，但其中 `deploy/env.example ↔ Settings` 的双向绑定测试（`test_env_example_covers_every_setting_exactly_once` 等）与平台无关，单独跑是绿的；`WD_IMAGE_KID_STAGES=""` 在 `env.example:154`、`DEPLOY.md §4:340`、`config.py:372-385` 三处对齐 |
| `cd frontend && npm run typecheck && npm test && npm run lint && npm run build` | tsc exit 0 · `41 files / 321 tests passed` · `copy check OK` · `✓ built in 333ms` |
| `env -u HTTP_PROXY -u HTTPS_PROXY make smoke` | `SMOKE PASSED — 28 steps in 38s`（`smoke.py:352` 断言五阶段 `["xs","zk","gk","cet4","cet6"]`，`:616` `len(stats["stages"]) == 5`） |
| `scripts/pack_seed.sh --check` | `9618 records, content sha256 ee985d90…c55c … seed archive OK`，exit 0；`data/seed/stats.json` `total_words 9618 / per_stage xs 600 · zk 2549 · gk 3260 · cet4 4722 · cet6 7671 / first_stage 600 · 1949 · 1255 · 1726 · 3850 · none 238`（与 PLAN §4.8 复算差 ≤ 1 行） |
| `cd data/lists && shasum -a 256 -c SHA256SUMS` | 11 个官方词表文件全部 `OK`；`git status --short data/lists/` 只有 5 个新增文件（README / manifest / aliases / overrides / SHA256SUMS），已交付文件一字未改 |

## 2 契约与镜像逐项核对

### 2.1 `docs/API.md §9` ↔ `frontend/src/api/types.ts`（逐字）

脚本提取 `## 9. Shared TypeScript DTOs` 下的 ```` ```ts ```` 块（216 行）与 `types.ts` 去掉开头 `//` 头注释后的正文（216 行）做 `difflib.unified_diff`：**IDENTICAL**。`Stage = 'xs' | 'zk' | 'gk' | 'cet4' | 'cet6';   // index 1..5 in that order`、`StageIndex = 1 | 2 | 3 | 4 | 5;`、`Settings` 注释「1–5 index」、`StageInfo.name_zh` 注释「小学 / 初中 / 高中 / 四级 / 六级」在两边一致（PLAN §3.2/§3.3）。`types.ts` 对基线还多了 `ScreenResponse.today` 与 `Stats.heatmap` 两条行内注释，均是向 API.md 既有文本看齐（API.md 侧无 diff），不是漂移。`check_contract.py` 对 75df534 无改动（`:151-171` 只收 `export type X = 'a' | 'b';`，`:274-281` 顺序敏感）。`endpoints.ts` 无改动，`VocabStageFilter/ScreenStage/PrewarmStage` 由 `Stage` 派生。

### 2.2 `schemas.py` ↔ PLAN §3.1

`Stage`/`StageIndex`/`STAGE_ORDER`/`STAGE_INDEX`/`STAGE_NAMES_ZH`/`stage_to_index`（查字典、`KeyError → ValueError`）/`index_to_stage`（上界 `len(STAGE_ORDER)`）/`VocabQuery`/`ScreenNextQuery`/`PrewarmRequest` 逐项与 §3.1 新值相同；`Difficulty`、`ImageProviderName`、`current_stage ∈ stages` 校验未动。`test_api_schemas.py::test_stage_index_is_position_plus_one` 钉住「索引 = 位置 + 1」且 `typing.get_args(Stage) == STAGE_ORDER`；`index_to_stage(0/6/-1)` 抛。后端常量副本只剩规格允许的派生/标签：`seed.STAGE_COLUMNS`、`prewarm.STAGE_COLUMNS/STAGES`、`words.STAGES = STAGE_ORDER`、`content.STAGE_ZH = schemas.STAGE_NAMES_ZH`、`ecdict.STAGE_TAGS`（ECDICT 标签名，R-10）+ `MEMBER_TAGS`、`bank.DEFAULT_STAGES/DEFAULT_CURRENT_STAGE`（`test_bank_defaults` 绑 DDL）、`scripts/eval_provider.py:107`（独立脚本的五元组镜像，§3.6 允许）。

### 2.3 迁移文件 ↔ PLAN §2.2–2.4

`diff <(PLAN §2.2 块) backend/wd/migrations/0011_primary_stage.sql` → 只有第 49 行注释（令牌示例 `cs2022:l2 … sh2020` → `cet4 cet46 ecdict moe22:l2 moe22:l3 shmeea20`，PLAN §2.2 开头明示允许）；0012、0013 与 PLAN 块**逐字相同**。`docs/SCHEMA.sql` 字节不变（§2.5）。

### 2.4 `zh.ts` ↔ `FRONTEND.md §8`、提示词 ↔ `CLAUDE_INTEGRATION.md`、`DEPLOY §4` ↔ `Settings`

- `zh.ts:25/28-29/86` 与 `FRONTEND.md:231/234-235/292` 的 `welcome.roles`（加 `xs: '小学生'`）、`stages`（`xs`、`xsFull: '小学（课标二级词汇）'`、`newOnlyZk: '仅初中新增（不含小学）'`、`outside: '课标外'`）、`sources.lists`（R-14 的 WL 字符串）逐字相同；vitest + `check-copy.mjs` 绿。
- `CLAUDE_INTEGRATION.md §5.1/§5.5` 代码块 ↔ `content_system.txt`/`svg_system.txt`：脚本直接比对 `== True`，`svg_system.txt` 首字符为字母；`§5` 标题 `content-v2`、`§6.4` 10–240、`AI_FALLBACK_MODEL.md:29` 同步；`ai/schemas/*.json` 与 `fixtures/claude_schemas.json` 对基线无 diff（R-2）；`content.py` `PROMPT_VERSION="content-v2"`、`AUDIENCE` 含「(小学)」、`EXAMPLE_EN_MIN=10`、`_is_blocked(keyword, lemma)`，规则 8 `1 = 小学/初中 basic`。
- `test_docs_contract.py::test_deploy_config_table_names_every_setting` 双向绿；`DEPLOY.md:340` 有 `WD_IMAGE_KID_STAGES` 行，`:420` CLI 行含 `import-seed [--file PATH] [--force] [--dry-run] [--report PATH]` 与 `images-retry [--limit N] [--dry-run]`，`:304` 「content sha256 of the (gunzipped) file」，`:361` 0011/0013 stop-first（S2 → S5 的请求全部落地）。

## 3 全仓库四阶段残留检索（排除 `docs/analysis`、`data/seed`、`node_modules`、`.venv`、`dist`）

| 模式 | 命中 | 判断 |
|---|---|---|
| `("zk", "gk", "cet4", "cet6")` / `['zk','gk','cet4','cet6']` | `ecdict.py:34 STAGE_TAGS`；`seedbuild/diff.py:47 V1_ORDER`；`test_words_resolve.py:376`（钉 `STAGE_TAGS`）；`test_seedbuild_normalise.py:809`（v1 夹具码）；`test_db.py:328/347/400`（旧索引升级夹具）；`test_seed.py:289`、`test_scheduler.py:340`、`StudyPage.test.tsx:287`、`BankPage.test.tsx:94`（合法的四旗标词 / 用户 `stages_json` 取值）；`fixtures/lists/previous_seed.jsonl`（v1 输入） | 全部按设计保留，不改 |
| `zk" \| "gk` / `'zk' \| 'gk'` | 仅 `WelcomePage.tsx:30 Role = 'xs' \| 'zk' \| 'gk' \| 'uni' \| 'pro'` | 正确 |
| `1, 2, 3, 4]` | `test_db.py:378`（迁移前断言）；`normalizeInput.test.ts:169`、`HeatStrip.tsx:90`（与阶段无关） | 不改 |
| `1–4` | **`docs/TASKS.md:204`「mapped to the 1–4 column」**；`CLAUDE_INTEGRATION.md:360`（`image_keywords` 1–4 个，非阶段）；`StageChips.tsx:12`、`schemas.py:53`、`DESIGN.md:342`、`0011:3-4`（描述「旧 1..4 → 新 2..5」，正确） | TASKS.md:204 应改（minor，见 §5 F-2） |
| `BETWEEN 1 AND 4` | `docs/SCHEMA.sql:148,185`（0001 基线，必须字节不变）；`0011:3-4` 注释（描述旧约束） | 不改 |
| `cet6 → 4` / `4 rows` / `cet6→4` | 无 | — |
| `four stages` / `four-stage` | `test_db.py:321` docstring（描述旧索引夹具 sqin 四阶段） | 正确 |
| `初中 / 高中 / 四级 / 六级`（不带小学） | 无；全部命中均已是 `小学 / 初中 / 高中 / 四级 / 六级`（`types.ts:45`、`API.md:279`、`README.md:9`、`FRONTEND.md:56,89`、`DESIGN.md:72`、`qa-frontend.md:42`） | — |
| `4 lists` / `the 4 ` | **`docs/DESIGN.md:43`「also outside the 4 lists」** | 应改为五表/官方词表（minor，F-1） |
| `9,162` / `9162` | **`backend/tests/conftest.py:41`、`backend/pyproject.toml:38`**（`full_seed` 跳过理由「needs the full 9,162-word seed」）、**`backend/wd/seedbuild/build.py:9`**（「the 9,162 existing rows」）；`DESIGN.md:229,639`、`WORD_LIBRARY_CURATION.md`、`releases/2026-11-k12-stages.md`、`P0_STATUS.md`（明示为历史/基线数字） | 前三处为陈旧/易过期文案（minor，F-3/F-4）；其余不改 |
| `["cet4","cet6"]` 默认 | `docs/SCHEMA.sql:147`（基线）；`test_batches.py:74`、`test_screen.py:116`、`smoke.py:332`（测试用户的选择，合法） | 不改 |
| `Literal['zk','gk','cet4','cet6']` | `docs/P0_STATUS.md:36` | P0 阶段状态快照（历史文档），判断不改 |
| `content-v1` / `$0.028` / `18 cards` | `WORD_LIBRARY_CURATION.md:166`、`releases:20`、`DESIGN.md:541`（说明旧卡版本）；成本旧数字无残留 | 不改 |
| `stage_zk, stage_gk, stage_cet4, stage_cet6`（无 `stage_xs` 的列清单） | 仅 `0011:71`（`SELECT … 0, stage_zk, …` 读旧表）与 `test_db.py:331`（旧表 INSERT） | 正确 |

前端非测试代码中的阶段码字面量只剩 `WelcomePage.tsx:34-43`（预设，PLAN §6 S4 规定值）、`VocabPage.tsx:32 TABS`、`:208 newOnlyZk` 分支、`AdminPage.tsx:740 useState<PrewarmStage>('cet4')`（下拉初值，非阶段表副本）。

## 4 测试纪律

### 4.1 突变测试（改坏 → 跑对应测试 → `cp` 回原件 → `cmp` 核对；8/8 被捕获）

| # | 突变 | 捕获的测试 |
|---|---|---|
| M1 | `schemas.STAGE_INDEX` 交换 `xs`/`zk` 的值 | `test_api_schemas.py::test_stage_mapping_roundtrip`、`::test_stage_index_is_position_plus_one`（2 failed / 11 passed） |
| M2 | `bank.DEFAULT_STAGES = ("cet4","cet6")` | `test_bank_defaults.py::test_defaults_mirror_user_settings_ddl`、`::test_missing_row_gets_the_python_defaults` |
| M3 | `routers/vocab.py:81` 排序回退为 `COALESCE(w.difficulty, w.stage_min, 5)` | `test_vocab.py::test_vocab_sort_alpha_and_difficulty` |
| M4 | `diag.STAGE_INVARIANTS` 的 `xs_subset_zk` 改成永不触发的 `stage_zk = 2` | `test_diag.py::test_check_db_counts_a_primary_word_missing_from_the_junior_list`、`::test_stage_invariant_sql_is_the_plan_literal_rendered_from_the_enum` |
| M5 | `sanitize_svg._serialise` 忽略 `allow_text=False` | `test_sanitize_svg.py::test_allow_text_false_drops_text_and_tspan_but_keeps_title_desc`、`test_images.py::test_activate_svg_sanitises_and_serves_a_svg_image`、`::test_svg_activation_records_prompt_version_model_and_text_free` |
| M6 | `StageChips.tsx` `only` 过滤去掉「最低阶段永不隐藏」 | `StageChips.test.tsx` 两条 `only` 用例（2 failed / 15 passed） |
| M7 | `seed.py:443` 不再累计 `unknown_stage_codes` | `test_seed.py::test_unknown_stage_code_is_counted_not_dropped_silently` |
| M8 | `0011_primary_stage.sql:71` 去掉 `stage_min + 1` 的 `+1` | `test_db.py::test_upgrade_0011_renumbers_stages_and_rebuilds_two_tables` |

### 4.2 断言强弱与跳过

- 改动的测试里删除 95 行 `assert/expect`、新增 642 行；逐条看删除行均为重算期望（60 → 62 条、索引 +1、新令牌串、`page_size "20" → "10"`、`"<text" in stored → not in`、`keyword_tokens` 返回 `frozenset`、`word_forms` 守卫加 `merged_into_word_id IS NULL`——与 PLAN §7.3 的 SQL 一致，`DESIGN.md:187` 解释了原因），没有「去断言换绿」。
- 新增/改动测试中没有新的 `skip`/`xfail`/`it.skip`/`.only`（唯一命中 `test_deploy_files.py:635 skipif(make 不存在)` 为既有）。`@full_seed` 读 `data/seed/stats.json`（R-17），`word_forms` 窗口 `14_054..14_338` = 实测 14,196 ± 1%。
- `test_style.py::test_function_pos_matches_the_frontend_code_table_without_adverbs` 只是硬编码 `{"i","c","d","p","a","u","t"}` 并在 docstring 里引用 `frontend/src/utils/pos.ts`，**没有读取** `pos.ts` 做跨语言比对（PLAN §5.1 只要求「与码表一致」，不要求文件绑定）——记为观察，不列问题。
- 新增代码无 `TODO/FIXME`；新增非注释代码里的中文只有 `AUDIENCE`（发给模型的受众句，`CLAUDE_INTEGRATION §5.2` 同步）、`STAGE_NAMES_ZH`（既有 API 字段 `name_zh` 的来源）、`FORM_KIND_ZH["alias"] = "另一种写法"`（PLAN §4.7 明文规定，`lemma_note` 既有机制）。

## 5 问题清单（只含验证过的）

| # | 严重度 | 位置 | 问题 | 证据 | 修法 |
|---|---|---|---|---|---|
| F-1 | minor | `docs/DESIGN.md:43` | 用户故事 5「User adds own words anytime (also outside the **4** lists)」仍写四表 | `grep -n "4 lists" docs/DESIGN.md` → 43；同文件 `:40`、`:72` 已写五阶段 | 改为 `(also outside the five official lists)` |
| F-2 | minor | `docs/TASKS.md:204` | WP2 交付物段「`current_stage` … (mapped to the **1–4** column)」 | `grep -n "1–4 column" docs/TASKS.md`；API.md:155/schemas.py:9 已改 1–5 | 改为「1–5 column」 |
| F-3 | minor | `backend/tests/conftest.py:41`、`backend/pyproject.toml:38` | `full_seed` 标记/跳过理由仍写「needs the full 9,162-word seed」；R-17 要求验收数字只引用 `stats.json`，当前种子是 9,618 条 | 两处 `grep -n "9,162"`；`stats.json.total_words = 9618` | 改为「needs the full seed (`data/seed/stats.json` total_words; set WD_FULL_SEED_DB=…)」 |
| F-4 | minor | `backend/wd/seedbuild/build.py:9` | 模块 docstring「the 9,162 existing rows come from the previous vocab.jsonl.gz」——下一次 `make seed` 的「上一版」就是 9,618 行，数字会立刻过期 | 文件第 9 行 | 改为「the existing rows (the previous seed, `stats.json.total_words`)」 |
| F-5 | minor | `backend/wd/config.py:389-398`（+ `docs/DEPLOY.md:317`、`backend/tests/unit/test_config.py:135-150`） | `WD_CLAUDE_BIN` 含 `/` 的相对路径改为按启动 cwd `abspath`，是 PLAN 之外的行为改动（S5 为排练命令所加），S7 门禁自报的「Fix-only changes」清单没有列它；语义变化：以前相对路径按子进程 `cwd=WD_CLAUDE_CWD` 解析。已有 DEPLOY §4 文案与 8 条断言；线上 Mac 用绝对路径的 shim、`install.sh` 写绝对路径，故无线上风险 | `git diff 75df534 -- backend/wd/config.py`；memory：Mac `WD_CLAUDE_BIN=/Users/sqin/word-dance-data/bin/claude-wrapper` | 在 S7 门禁记录 / `docs/releases/2026-11-k12-stages.md` 补一行说明该语义变化（或在 DEPLOY §4 行加「before this release a relative path was resolved in `WD_CLAUDE_CWD`」）；代码不必改 |

判断为**不改**的命中：`docs/P0_STATUS.md:36`（P0 验收快照）、`docs/SCHEMA.sql`（0001 基线，字节绑定）、`ecdict.STAGE_TAGS`、`seedbuild/diff.V1_ORDER`、所有旧索引迁移夹具、`DESIGN.md:229,639` 与发布说明中标明为历史的 9,162/2,099/3,829/3,694。

## 6 复跑是否通过

是：§1 的全部验收命令在本评审中重新执行并通过；突变全部恢复，`git status` 条目数与评审前相同（139），`data/lists/` 已交付文件 `shasum -c` 全 OK。
