# PLAN — 小学阶段 · 官方词表 · 配图第一期：合并后的实现计划

基线 `main @ 75df534`（`git rev-parse --short HEAD` 实测 2026-11-06）。输入：`design/stage-model/SYNTHESIS.md`、`design/word-lists/SYNTHESIS.md`、`design/images/SYNTHESIS.md`、`INDEX.md`、`docs/WORD_LIBRARY_CURATION.md`。本文引用的每个 `path:line` 都按 75df534 重新打开核对过（§1 末尾列出与三份综合稿不一致的行号）。线上库只读副本 `scratchpad/live-copy.db`（`schema_migrations` 1/8/9/10；`user_settings` `1|["zk","gk","cet4","cet6"]|3`、`2|["zk"]|1`；13 个 `kind='phrase'`；49 行 `difficulty`；`sources` 令牌全集 `cet4 cet46 cet6 ecdict gk zk`）。`scratchpad/` = `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/`。

记号：`[SM D-n]` = stage-model 综合稿决定 n；`[WL D-n]` = word-lists 决定 n；`[IM D-n]` = images 决定 n；`[INDEX An]` = INDEX.md 第 2 节条目；`S1…S7` = §6 的切片。

---

## 0 一页结论

**数据模型与阶段编码**（S1）：沿用 `words.stage_*` 布尔列 + 整数 `stage_min`，新增一列 `stage_xs`（列序 `stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6`）；阶段枚举 `STAGE_ORDER = ("xs","zk","gk","cet4","cet6")`，整数索引**重编号 1..5**（xs=1 … cet6=5），显式字典 `STAGE_INDEX` + 测试钉住「索引 = 位置 + 1」；`index_to_stage` 上界 `len(STAGE_ORDER)`。一次停机迁移 `0011_primary_stage.sql`（§2.2，已用真实 `wd.db.run_migrations` 在线上副本上排练通过）。不建 `stage_defs`/`word_stage_tags`，不做「上海/全国」维度，不做「拓展/超纲」阶段；一切回填信息留在 `words.sources` 令牌里。`difficulty` 1–5 尺子不动，只把 `routers/vocab.py:78` 改成 `COALESCE(w.difficulty + 1, w.stage_min, 6)`。

**各阶段词集**（S3，全部只用官方文件的**词头**；集合代数与 12 条归一化规则见 §4）：
- `xs` = 国家 2022 课标二级 505（`moe-2022-level2.txt`，含括注变体）∪ 2022 附表{数词-基数词, 数词-序数词（单 token）, 月份, 星期} ∪ `be/do` 人称形式继承（实际 `am, is, are, does` 四行）。
- `zk` = `xs` ∪ 国家三级 1600（`moe-2022-level3.txt`）∪ 2022 附表{地理名称, 地理名称-派生, 缩写, 节日, 地名景点, 其他专有名词} ∪ 上海市教育考试院 2020 单词表（`shmeea-2020-junior.txt`）∪ 上海附表全部节 ∪ 上海词组（`shmeea-2020-junior-phrases.txt` 中 ECDICT 有条目且通过 `normalise_input` 严格门者，`kind='phrase'`）。
- `gk` = 高中课标 2025 修订 3100（`moe-2025rev-senior.tsv`）∪ 2020 修订 3000（`moe-2020-senior.tsv`），显式并集；两份国家名称附表只存档不授予成员。
- `cet4` / `cet6` 不变（现有行逐字保留；新行取 ECDICT 标签）。
- 不规则动词附表不授予成员；ECDICT 的 `zk/gk` 标签与 mahavivo 中考/Highschool 两表退出成员判定（运行时 ECDICT 只按 `cet4/cet6` 赋阶段）；`xs ⊆ zk` 构建期断言，`zk ⊄ gk` 是事实（不断言）。
- 老词只重标不删除：掉出所有官方表的词（复算 238 个）成为 `stage_min NULL` 的「课标外」词典词，只在「全部」页签与搜索可见；`legacy:zk/legacy:gk` 令牌保留旧出处。复算预期（最终以 `data/seed/stats.json` 为准）：`stage_xs` 600 · `stage_zk` 2,548 · `stage_gk` 3,260 · cet4 4,722 · cet6 7,671；`stage_min` 600 / 1,948 / 1,255 / 1,726 / 3,850 / NULL 238；9,162 → 9,617 行（+455，其中 333 个词组）。

**新用户与老用户**（S1/S2/S4）：DDL 默认 `stages_json '["xs","zk"]'` / `current_stage 1`（主攻小学）；`bank.DEFAULT_STAGES/DEFAULT_CURRENT_STAGE` 同值并用 `pragma_table_info` 绑定测试；欢迎页加「小学生」角色（`['xs']`/xs），「初中生」预设改 `['xs','zk']`/zk，其余不变。线上两行写死在 0011 里：只 `current_stage + 1`（sqin 3→4=cet4，kimi 1→2=zk），`stages_json` 原样，不自动加 `xs`。

**配图第一期**（S5，零 key、零 API 契约）：SVG 系统提示词 v2（图中无文字由 `sanitize_svg.clean(allow_text=False)` 代码保证、裸 `&` 修复、`<desc id="aigc-label">` 隐式标识、例句 + 挂钩 + Style 段，`SVG_PROMPT_VERSION='svg-v2'`）；content 提示词 v2（受众句加小学、规则 1/3/5 加小学/初中条款、规则 6/7 改为「例句 1 的同一场景」、`EXAMPLE_EN_MIN` 15→10、`PROMPT_VERSION='content-v2'`）；功能词门（主词性 ∈ {i,c,d,p,a,u,t} → 模板卡、不发请求）；黑名单三分 + 查询词豁免；provider 风格参数（默认链只多 `thumbmime`/`maxlag=5`/`page_size=10`）；打分新信号；失败词夜间重试（6 h / 30 天 ≤ 3 次 / 每晚 ≤ 50，`wd images-retry`）；插画优先轮代码就绪但 `WD_IMAGE_KID_STAGES` 默认空 = 关；附加迁移 `0012_word_images_meta.sql`（`prompt_version`/`model`/`text_free`/`eval_json` 四列）。第二期（智谱 key + 出口正常的机器）只做适配器 + 200 词四臂试点脚本，不进契约；第三期以预注册门槛为条件。

**迁移编号**：0011 阶段模型（S1）· 0012 `word_images_meta`（S5）· 0013 `word_forms_alias`（S2）；配图三期的重建迁移顺延为 0014。`docs/SCHEMA.sql` 字节不变。

**对产品负责人假设 A1–A6 的最终处理**

| 假设 | 处理 | 细化 / 偏离 |
|---|---|---|
| A1 小学 = 国家 2022 二级 505 骨架 | 采用 | 细化：加入 2022 附表的数词（单 token）/月份/星期（否则 `Monday/one/January` 只能经高中表进 gk）；括注变体（`color`、`math`、`mom`…）与词头同阶段；`am/is/are/does` 继承 `be/do`。教材词拓展层不做（§9） |
| A2 初中 = 上海 2020 ∪ 三级 1600；高中 = 2025 修订 3100（含 2020 版 3000）；200 词暂缺 | 采用 | 细化：① 上海表的单词、附表**与词组**都入 zk（词组只收 ECDICT 有条目者，默认入，见 §9 P2）；② 2022 国家附表的专名/缩写/节日归 zk；③ 高中 = 2025 ∪ 2020 显式并集（保住被 2025 版移出主表的 94 词），两份国家名称附表只存档；④ 考试院 200 词与上海 2026 手册无机读件，manifest 预留 id |
| A3 只用官方词头；mahavivo 中考/高中两表退出；有道系等只作核验 | 采用 | `build_seed.py` 删除两张表输入；ECDICT `zk/gk` 标签也退出；CET 四表变为**可选**输入（缺席时现有行 CET 旗标逐字保留）；旧成员关系只以 `legacy:*` 令牌保留；`overrides.tsv` 的 ≤ 30 条人工释义是本仓库 MIT 文本 |
| A4 不按省份分层；双方案/拓展层由设计决定 | **都不做** | 封死/变贵的路径与触发条件写进 `DESIGN.md §3.1`（§9） |
| A5 配图先改提示词与抓取链；位图生成可配置、默认关 | 采用并更保守 | 「无文字」由代码保证；插画优先链也默认关（`WD_IMAGE_KID_STAGES=""`）；生成器第二期只做脚本试点，第三期才进配置与契约 |
| A6 新用户默认 K-12；2 个用户迁移规则写死 | 采用 | DDL 默认 `["xs","zk"]`/xs；两行只 `+1`、不加 `xs`，写死在 0011 的 `INSERT … SELECT`（排练输出 `(1, 4)`、`(2, 2)`） |

工作量合计（人日，含测试与文档）：S1 0.5 · S2 4 · S3 8 · S4 1.5 · S5 7 · S6 1.5 · S7 1 ≈ **23.5**；配图二期 ≈ 5.5（另计，需拍板），三期 ≈ 9（条件合入）。

---

## 1 跨线冲突的裁决

每条：冲突 → 裁决 → 理由。括号内是三份综合稿各自的立场。

**R-1 阶段编码 vs 种子 `stage_min` 计算 vs 前端契约。** （SM：重编号 1..5、显式 `STAGE_INDEX`；WL：只依赖 `schemas.stage_to_index`，不关心编码；IM：`style.stage_code()` 兼容整数索引与字符串码。）→ **重编号 1..5，`schemas.py` 是唯一真相**：`seed.py`、`ecdict.py`、`seedbuild`、`prewarm.py`、`words.py` 全部从 `schemas.STAGE_ORDER` / `stage_to_index` 读，不再保留任何副本（`INDEX A3` 的 10 份常量 → 1 份 + 前端 `StageChips.STAGE_ORDER` 镜像，由 `check_contract.py:274-281` 的字面量联合比对钉住）；`types.ts:5-6` 与 `API.md:239-240` 同序 `xs, zk, gk, cet4, cet6` / `1..5`。理由：现有「位置推导」代码（`schemas.py:59`、`seed.py:208`、`ecdict.py:177`、`_STAGE_DISTANCE` `screen.py:34-35`/`batches.py:60`、`StageChips.tsx:31`）在重编号下零逻辑改动；「小学 = 0」要修 `screen.py:44`、`batches.py:272,698` 的 `int(x or DEFAULT)` 并永久背上 Python/JS 两侧「0 为假」风险；线上只有 2 个用户、49 行 `difficulty`，重编号代价是历史最低点（`[INDEX Q1]` 建议 a）。三处 `int(x or DEFAULT)` 仍改为 `is None` 判断（防御，`[SM D-16]`）。

**R-2 `difficulty` 尺子。** （SM/WL：不动尺子、`COALESCE(w.difficulty + 1, w.stage_min, 6)`；IM：content v2 不改 schema。）→ **不动**：`content_v1.json` 的 `difficulty` enum/description、`schemas.Difficulty`、`types.ts:73`、DB CHECK 全不改；`vocab.py:78` 一行平移；content 提示词规则 8 改为「1 = 小学/初中 basic」（S5，同一次 `content-v2` 版本提升，不另起版本）。理由：排练库上 `difficulty + 1 = stage_min` 44/49 与迁移前 `difficulty = stage_min` 44/49 逐项相同；扩 6 级要动 ≈ 12 个文件 + 三方字节绑定的 schema（`test_schemas.py:56`）。

**R-3 种子流水线的形态。** （SM：新脚本 `scripts/relabel_seed.py` 就地重标，两步管线，`python -I` 下不做兄弟模块导入；WL：包 `backend/wd/seedbuild/{normalise,build,diff}.py` + `manifest.json` + `aliases.tsv` + `overrides.tsv` + `SHA256SUMS`，`scripts/build_seed.py` 只是入口。）→ **采用 WL 的包方案**，`relabel_seed.py` 不建；SM 的「只增不减」断言、`--dry-run` 口径、`stats.json` 新键、`ATTRIBUTION` 由脚本生成全部嫁接进 `seedbuild/build.py` / `diff.py`。理由：① `.venv/bin/python -I -c "import wd"` 实测成功（`wd` 是 venv 内的可编辑安装，`-I` 只屏蔽脚本目录与用户 site），SM 担心的导入障碍不存在；② 包可单元测试，单文件 `main()` 不能（`TASKS.md:162`「keep verbatim」前提已失效）；③ WL 的数字是按**交付文件**复算的，SM 的是按中间件模拟的；④ 阶段逻辑仍只在一处（`seedbuild/build.collect_members`）。SM 的 `headword-overrides.jsonl`（4 条）并入 WL 的 `overrides.tsv`（23 条，含 `bund/ai/bce/ce`）。

**R-4 `sources` 令牌命名。** （SM：`cs2022:l2 / cs2022:l3 / cs2022:app / sh2020 / sh2020:app / cs2020:hs0|1|2 / cs2020:app / cs2025:hs0|1|2 / cs2025:app / legacy:*`；WL：`moe22:l2|l3|app / shmeea20[:app|:phr] / hs20 / hs25:0|1|2 / inherit:be|do / legacy:*`。）→ **采用 WL 的命名族**（与交付文件名、manifest `id` 一致），并做一处统一：`hs20` 也带星级（`hs20:0|1|2`，`moe-2020-senior.tsv` 的 `level` 列实测 1500/499/1001 行）。最终令牌表见 §4.4；`zk`、`gk` 两个旧令牌删除（改名 `legacy:zk`/`legacy:gk`），`ecdict cet4 cet6 cet46` 不变。

**R-5 国家高中附表（国家名称）是否授予 `gk`。** （SM：授予已在库词头；WL：`policy: reference`，只存档。）→ **只存档，不授予**。理由：两份附表在原件中标为「供教学参考」（`moe-senior.README.md`），词表线是列表语义的责任方；相关国名若已在 2022 附表则经 `moe22:app` 进 zk，若不在任何表则作为课标外词典词保留。反悔只改 manifest 一行（`policy: appendix`, `stages: ["gk"]`）。

**R-6 上海 342 个词组。** （SM：本轮不入库，留给词表线；WL：首版入库 303 条 → 333 行，`kind='phrase'`，只在 zk，模板型 39 条跳过。）→ **入库**（WL 是责任方且 SM 明示让渡）。接口与 SM 预留的一致：非空 `translation`（ECDICT）、`derive_kind` 得 `phrase`、阶段 zk、令牌 `shmeea20:phr`；配图线无需改动（`pos` 为空 → 不触发功能词门，允许裸 lemma 搜索）。一键退出 = manifest 该条 `policy: reference`。列为 §9 P2。

**R-7 括注变体与人称形式。** （SM：变体只在**已是** lemma 时同享旗标，绝不新建；`be (am, is, are)` 的 is/are/am 同享；WL：变体成为同阶段独立行（170 条关系全部在 ECDICT，缺行则新建），`(am, is, are)`/`(has)`/`(pl. …)` 不产生成员，`is/are/am/does` 经 manifest `inherit_stages` 显式清单继承。）→ **采用 WL**：变体建行、人称形式按显式清单继承、从不建行。理由：两方对「已在库的变体同享」一致；WL 的显式清单避免 SM 通用规则会带进 `saw/bore/shot` 一类独立义项词（复算 12 个）。实测 `has/had` 不是 lemma、`being` 是官方词头本身，所以继承只落在 `am, is, are, does` 四行；机制对任一情形都正确。

**R-8 导入器对未知阶段码的处理。** （SM：`SeedFormatError`，写入前失败、exit 1；WL：计数 + 一次 WARNING，从不拒绝。）→ **计数 + WARNING**（WL），硬门放在构建期：`seedbuild` 断言每个码 ∈ `schemas.STAGE_ORDER`（失败 exit 2，不写输出）。理由：运行时拒绝与「可分步上线 / 回滚旧代码读新种子」冲突；两线都已把 `main.seed_check` 改为捕获异常并写 `system_events('seed_import_failed')`，所以运行时的真正风险（重启循环）已消除；`SeedStats.unknown_stage_codes` 同时写进 `system_events('seed_imported').detail_json` 与 `--dry-run` 报告，不再是「静默」。

**R-9 `kv.seed_version` 语义。** （SM：0011 `DELETE FROM kv WHERE key='seed_version'` 强制重导；WL：改为解压后内容 sha256。）→ **两者都做**：0011 保留 DELETE（在旧代码下也保证重导），`seed.py` 改为 `content_sha256`（Mac `gzip -9 -n` 重打包不再触发伪重导）。`main.seed_check` 全文按 WL §3.5 替换（捕获 `Exception`，记 `seed_import_failed`，继续启动）。

**R-10 `ecdict.py` 的标签常量。** （SM：`GRANTED_TAGS`；WL：`MEMBER_TAGS`。语义相同。）→ 名字取 **`MEMBER_TAGS = ("cet4","cet6")`**；`STAGE_TAGS` 四元组保留给 `has_stage_tag`（`words.py:669,673` 的回指启发式不变）；`word_columns()` 由 `STAGE_ORDER` 生成五个旗标、`stage_min = min(stage_to_index)`。

**R-11 迁移编号撞车。** （WL：`0012_word_forms_alias.sql`；IM：`0012_word_images_meta.sql`，并明确「0011 留给阶段模型」。）→ **0011 阶段模型 · 0012 `word_images_meta` · 0013 `word_forms_alias`**（WL 自己写明「若 0012 被占用则顺延改名，内容不变」）；配图三期的 `word_images` 重建迁移改为 **0014**。`db.list_migration_files` 只要求编号唯一（`db.py:159-170`），`pending_migrations` 按未记录集合选文件（`:190`），所以三个文件可独立合入，同批上线时按编号顺序应用；快照名 `pre-migrate-10-to-13.db.gz`。

**R-12 `content.py` / `content_system.txt` / `CLAUDE_INTEGRATION.md §5.1` 的归属。** （SM：本线只改 `STAGE_ZH` 常量来源，受众句/规则 8/`AUDIENCE` 归「Q9 切片」；IM：改规则 1/3/5/6/7、`PROMPT_VERSION`、`EXAMPLE_EN_MIN`、`_is_blocked(keyword, lemma)`，第 1 行与规则 8 归阶段模型线。）→ **全部归配图/提示词切片 S5，一次 `content-v2` 版本提升**：`content.STAGE_ZH = schemas.STAGE_NAMES_ZH`、`AUDIENCE` 加小学、第 1 行受众句、规则 1/3/5/6/7/8、`EXAMPLE_EN_MIN`、`_is_blocked` 签名、`CLAUDE_INTEGRATION.md §5.1/§5.2/§6.4` 逐字节同步。理由：同一文件两线各改一次 = 必然的合并冲突 + 两次版本提升；`content_system.txt` 被 `test_schemas.py:123` 逐字节钉住，必须一人一次改完。后果：**S2 合入而 S5 未合入期间**，`prompt_entry`（`content.py:88`）对 `stage_xs=1` 的词 `KeyError` —— 所以 S2 的 `mini_seed.jsonl` 不给 `go` 加 `xs`（`test_content_apply.py:254-255` 用它），且上线前 S5 必须合入（§8 第 1 步预检）。

**R-13 `docs/DEPLOY.md` 与 `deploy/env.example` 的归属。** （三线都要改：SM 的 §9 CLI/§10 runbook、WL 的 `make seed`/`import-seed --dry-run`、IM 的 `WD_IMAGE_KID_STAGES` 行。）→ 归 **S5**（配图切片，拥有 `config.py`）：`test_docs_contract.py:114-133` 对 DEPLOY §4 表与 `Settings` 字段做**双向**比对，`env.example` 同理（`test_deploy_files.py:119`），所以新字段与其文档行必须同一切片。S2/S3/S6 对 DEPLOY.md 的改动以本文 §6 的「请求清单」交给 S5 执行。

**R-14 `zh.ts:86 sources.lists` 文案。** （SM：『词表范围：义务教育课标二级与三级词汇、上海市初中英语词汇表、高中课标词汇表、大学英语四级与六级大纲』；WL：『词表范围：小学（课标二级）、初中（课标三级与上海市初中英语词汇表）、高中（高中课标词表）、大学英语四级与六级大纲』，SM 明示采用 WL 定稿。）→ **WL 的字符串**，`zh.ts:86` 与 `docs/FRONTEND.md:292` 逐字相同（S4）。

**R-15 图风格按阶段驱动 vs 阶段码变化。** （IM：`WD_IMAGE_KID_STAGES` 阶段码集合、`style.stage_code()` 经 `schemas.index_to_stage`；SM：请用码集合而非 0 哨兵，`kid_max_index` 用 `stage_to_index`。）→ 一致，无冲突：`stage_code(1) == "xs"`（重编号后），越界返回 `None` 而不抛；`config.from_env` 对 `WD_IMAGE_KID_STAGES` 的校验用函数级 `from .schemas import STAGE_ORDER`。默认空；试点达标后才改 `("xs",)`。`zk` 永不在默认里。

**R-16 失败词即时重试的两处挂点。** （IM：`bank.py:636,659` 与 `batches.py:352-362,639` 调 `images.retry_if_failed`。）→ **一期只做夜间 `retry_failed_studied`（`scheduler.maintenance`）+ CLI `wd images-retry`**；两处即时挂点推迟到集成后的一次性小提交（§9 未决 7）。理由：`bank.py`/`batches.py` 属 S2（阶段默认与 `is None`），`images.retry_if_failed` 属 S5，两切片并行；夜间维护已覆盖「正在被学的失败词 24 h 内重抓」（线上 18 个 failed 词里 17 个在学）。

**R-17 验收数字。** （SM 模拟：xs 584 / 新词头 47 / 课标外 227；WL 复算：600 / 455 / 238。）→ 以 **S3 产出的 `data/seed/stats.json` 为唯一验收常量来源**（`test_full_seed_acceptance_numbers`、`TASKS.md`、`API.md:169`、`DESIGN.md:209`、`README.md:103` 全部引用它，不手填）；WL 的复算是预期区间（±1%），差异来自规则不同（变体建行、词组入库、继承、附表口径），方向一致。

**与三份综合稿不一致的行号（按 75df534 核对后以本文为准）**：`scripts/check_contract.py` 的联合比对在 `:274-281`（SM 写 `:301-308`）；`services/ecdict.py` 的 `word_columns` 位置推导在 `:177`（两线一致）；`content_system.txt` 的难度尺子是第 **11** 行（文件行号），`image_keywords`/`image_alt_zh` 是第 9/10 行；`docs/FRONTEND.md` 的 `stages` 镜像块在 `:234-235`；`WelcomePage.tsx` 的 `Role`/`ROLE_PRESETS`/`ROLES`/`STAGE_FULL` 在 `:30-42`，兜底在 `:72-73`；`frontend` 含 `stage_min: <数字>` 的测试夹具 12 处分布在 10 个文件（`grep -rn 'stage_min: [0-9]' frontend/src --include='*.test.*'`）。

---

## 2 统一的数据模型与迁移规格

### 2.1 模型（迁移后的现行 DDL = 0011 文件头 + 0012/0013 的增量；`docs/SCHEMA.sql` 仍是 0001 基线，字节不变）

| 表 / 列 | 迁移后 | 读者 / 写者 |
|---|---|---|
| `words.stage_xs … stage_cet6` | 五个 `INTEGER NOT NULL DEFAULT 0 CHECK (… IN (0,1))`，列序 `stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6`（与 `seed.SEED_COLUMNS` 由 `STAGE_ORDER` 生成的顺序一致） | 写：`seed.import_seed`（UPSERT 覆盖）、`services/words._insert_word`、`ecdict.word_columns`；读：`vocab.py:53-56`、`screen.py:51-56`、`batches.py:233`、`prewarm.py:36-39`、`words.stages_of:229` |
| `words.stage_min` | `INTEGER CHECK (stage_min BETWEEN 1 AND 5)`；= 最低旗标的索引（1 xs … 5 cet6）；`NULL` = 不在任何表（课标外）| 不变量 `stage_min IS (CASE WHEN stage_xs=1 THEN 1 … END)` 由 `wd check db` 与 `full_seed` 验收断言 |
| `words.sources` | 令牌集合（§4.4），空格连接、排序；仍无运行时读者 | `seed.py:210` |
| `words.difficulty` | 不变（1–5，Claude 尺子） | `vocab.py:78` 排序键 `difficulty + 1` |
| `user_settings.stages_json` | `DEFAULT '["xs","zk"]'`，非空子集 of 五码 | `bank.user_settings_row:181` 过滤未知码并在全部过滤掉时回落默认 + `stage_fallback` 日志 |
| `user_settings.current_stage` | `DEFAULT 1 CHECK (BETWEEN 1 AND 5)` | `security.py:597 index_to_stage` |
| `word_forms.kind` | CHECK 加 `'alias'`（0013）；别名行由种子导入写入（`data/lists/aliases.tsv` 经种子记录 `aliases[]`），`alt` 语义不变 | `words.resolve:663-696`（精确 → `word_forms` → ECDICT） |
| `word_images.prompt_version / model / text_free / eval_json`（0012） | `TEXT / TEXT / INTEGER NOT NULL DEFAULT 0 CHECK (text_free IN (0,1)) / TEXT` | 写：`store.activate(... prompt_version, model, text_free)`；30 张旧 SVG `text_free=0`、`prompt_version NULL` |
| `kv.seed_version` | 解压后内容的 sha256（原来是 `.gz` 文件的 sha256） | `seed.import_seed`、`main.seed_check` |
| `system_events.kind` | 新值 `'migration'`、`'seed_import_failed'`（列无 CHECK，`0001_init.sql:59-64`） | 管理页事件表 |
| `push_batches.settings_json` | 不改写：0011 之前的快照里 `current_stage` 是旧整数（只写不读，`batches.py:314-318`；旁边的 `stages` 码无歧义） | — |

不做：`stage_defs`/`word_stage_tags`/`stage_presets`、`user_settings.scheme`、第二个 `stage_min`、`user_settings.image_hint`、`word_images.audience/style`、`(word_id, style)` 唯一索引。目标模型（阶段即数据）与触发条件归档在 `DESIGN.md §3.1`：① 产品拍板做每用户「上海/全国」方案；② 出现许可干净的教材词表要做拓展层；③ 第三次要加阶段。届时用 `sources` 令牌一条 SQL 回填 tag 表。

### 2.2 `backend/wd/migrations/0011_primary_stage.sql`（S1；全文 = `scratchpad/synthesis-stage-model/0011_primary_stage.sql`，已排练；入库前只允许改注释里的令牌示例 `cs2022:l2 …` → `moe22:l2 …`）

运行器约束（`db.py:195-249`、`0001_init.sql:25-37`）：文件在 `BEGIN IMMEDIATE` 内执行，`foreign_keys=OFF` 包裹，运行器自己写 `schema_migrations(11,'primary_stage')` 并先跑 `foreign_key_check`；文件内不得 `COMMIT`/`ROLLBACK`/切 PRAGMA/`VACUUM`。`DROP VIEW v_bank` 必须先于 `DROP TABLE words`（`legacy_alter_table=OFF` 下 RENAME 否则失败；`/usr/bin/sqlite3` 的 `legacy_alter_table=1` 会掩盖这个错误，排练一律走 `wd.db.run_migrations`）。

```sql
-- 0011_primary_stage.sql — add the 小学 stage (code `xs`), renumber the stage index 1..5 and move the new-user default to K-12.
--
-- Why a rebuild: SQLite cannot ALTER a CHECK list or a column DEFAULT, so `words` (stage_min BETWEEN 1 AND 4) and
-- `user_settings` (current_stage BETWEEN 1 AND 4, DEFAULT 3, stages_json DEFAULT '["cet4","cet6"]') are re-created with
-- SQLite's 12-step recipe (CREATE new → INSERT … SELECT → DROP old → RENAME → indexes → views). The runner wraps this file
-- in BEGIN IMMEDIATE with foreign_keys=OFF and runs foreign_key_check before recording schema_migrations(11, 'primary_stage')
-- itself (SCHEMA.sql §1); nothing here toggles PRAGMAs or commits. Stop-first migration (DEPLOY §10: never under --no-restart).
--
-- Index renumbering (DESIGN §0.3 / API.md §9.1): old 1=zk 2=gk 3=cet4 4=cet6 → new 1=xs 2=zk 3=gk 4=cet4 5=cet6, so every stored
-- stage_min / current_stage moves +1 (NULL stays NULL). stages_json holds stage CODES and is copied as is; nobody is enrolled
-- in xs automatically (live rows: user 1 → current_stage 4 = cet4, user 2 → 2 = zk). The seed re-import that follows
-- (kv.seed_version is cleared below so the next `wd import-seed` / `wd serve` start imports unconditionally) recomputes
-- stage_xs/stage_zk/stage_gk/stage_min for every seed word from the official lists; the +1 here only keeps the database
-- self-consistent in between and for non-seed rows. push_batches.settings_json snapshots written before this migration keep
-- the OLD integer in "current_stage" (write-only column, batches.py; the "stages" codes next to it are unambiguous).
--
-- The view v_bank references words: it must be dropped before the DROP TABLE/RENAME and re-created afterwards (with
-- legacy_alter_table=OFF the RENAME otherwise fails with "error in view v_bank: no such table: main.words"). docs/SCHEMA.sql
-- stays the 0001 baseline byte for byte (test_db.py); the current DDL of words/user_settings is THIS file (DESIGN §3.1).

-- ---------------------------------------------------------------------------
-- 1. words: + stage_xs, stage_min 1..5 (renumbered)
-- ---------------------------------------------------------------------------
DROP VIEW v_bank;

CREATE TABLE words_new (
  id                  INTEGER PRIMARY KEY,
  lemma               TEXT NOT NULL,                    -- normalised key: NFKC, lower-case, single spaces, ASCII ' - .
  display             TEXT NOT NULL,                    -- display form, keeps casing ('China', 'NASA', 'a.m.', 'ice cream')
  kind                TEXT NOT NULL DEFAULT 'word' CHECK (kind IN ('word','phrase','abbreviation','proper_noun')),
  phonetic            TEXT,                             -- 'ə'bændən' (seed: ә→ə, :→ː normalised)
  translation         TEXT,                             -- zh lines joined by '\n' (seed translation[])
  definition          TEXT,                             -- en lines joined by '\n' (seed definition[])
  pos                 TEXT,                             -- ECDICT pos distribution 'n:4/v:96'
  collins             INTEGER,                          -- 0–5
  oxford              INTEGER,                          -- 0/1 (Oxford 3000)
  exam_tags           TEXT,                             -- 'ky toefl ielts gre' (space-joined seed exam_tags[])
  bnc                 INTEGER,                          -- BNC rank; 0/NULL = unknown
  frq                 INTEGER,                          -- COCA-ish rank; 0/NULL = unknown (sorted last)
  exchange_json       TEXT,                             -- seed exchange{} as JSON object ({"p":"went","d":"gone",…})
  stage_xs            INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs   IN (0,1)),  -- 小学 (义务教育课标 2022 二级词汇表 + 附表数词/月份/星期)
  stage_zk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_zk   IN (0,1)),  -- 初中 (课标 2022 三级 1600 ∪ 上海市教育考试院 2020 初中词汇表; ⊇ xs)
  stage_gk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_gk   IN (0,1)),  -- 高中 (普通高中课标 2017 年版 2025 年修订 3100 ∪ 2020 年修订 3000)
  stage_cet4          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet4 IN (0,1)),  -- 四级
  stage_cet6          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet6 IN (0,1)),  -- 六级 (cumulative: includes most CET-4)
  stage_min           INTEGER CHECK (stage_min BETWEEN 1 AND 5),  -- lowest stage 1=xs 2=zk 3=gk 4=cet4 5=cet6; NULL = outside the 5 lists.
                                                                  -- 仅本阶段新增 filter == stage_min = <stage index>
  cet6_star           INTEGER NOT NULL DEFAULT 0 CHECK (cet6_star IN (0,1)),   -- starred CET-6 word
  sources             TEXT,                             -- provenance tokens (data/seed/ATTRIBUTION.md), e.g. 'cet4 cet46 cs2022:l2 cs2022:l3 ecdict sh2020'
  ecdict_id           INTEGER,                          -- stardict.id
  source              TEXT NOT NULL CHECK (source IN ('seed','ecdict','claude','user')),  -- where dictionary fields came from
  is_public           INTEGER NOT NULL DEFAULT 1 CHECK (is_public IN (0,1)),   -- 0 = unvalidated/unsafe user word (visibility rule: API.md §1, DESIGN §5.2)
  is_valid_english    INTEGER CHECK (is_valid_english IN (0,1)),  -- NULL = not yet checked; set by lookup_word / seed import
  safe_for_sharing    INTEGER CHECK (safe_for_sharing IN (0,1)),  -- NULL = not yet checked; Claude verdict (no personal names etc.)
  difficulty          INTEGER CHECK (difficulty BETWEEN 1 AND 5), -- Claude scale, unchanged: 1 初中 … 4 六级, 5 beyond (= stage index − 1; vocab sort uses difficulty + 1)
  merged_into_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,  -- consolidation merged this row into another
  created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  active_content_id   INTEGER,                          -- logical FK → word_contents.id (no constraint: avoids a cycle)
  active_image_id     INTEGER,                          -- logical FK → word_images.id (NULL ⇒ template card is served)
  content_state       TEXT NOT NULL DEFAULT 'none' CHECK (content_state IN ('none','queued','ready','failed')),
  image_state         TEXT NOT NULL DEFAULT 'none' CHECK (image_state  IN ('none','queued','ready','failed')),
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT INTO words_new (id, lemma, display, kind, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq, exchange_json,
                       stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min, cet6_star, sources, ecdict_id, source,
                       is_public, is_valid_english, safe_for_sharing, difficulty, merged_into_word_id, created_by_user_id,
                       active_content_id, active_image_id, content_state, image_state, created_at, updated_at)
SELECT id, lemma, display, kind, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq, exchange_json,
       0, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min + 1, cet6_star, sources, ecdict_id, source,
       is_public, is_valid_english, safe_for_sharing, difficulty, merged_into_word_id, created_by_user_id,
       active_content_id, active_image_id, content_state, image_state, created_at, updated_at
FROM words;

DROP TABLE words;
ALTER TABLE words_new RENAME TO words;

CREATE UNIQUE INDEX ux_words_lemma      ON words(lemma);
CREATE INDEX        ix_words_frq        ON words(frq);
CREATE INDEX        ix_words_stage_min  ON words(stage_min, frq);
CREATE INDEX        ix_words_content    ON words(content_state);
CREATE INDEX        ix_words_created_by ON words(created_by_user_id) WHERE created_by_user_id IS NOT NULL;
CREATE INDEX        ix_words_public     ON words(is_public, is_valid_english);

CREATE VIEW v_bank AS
SELECT uw.*, w.lemma, w.display, w.kind, w.phonetic, w.translation, w.stage_min, w.content_state, w.image_state,
       w.is_public, w.is_valid_english
FROM user_words uw JOIN words w ON w.id = uw.word_id
WHERE uw.state IN ('new','learning');

-- ---------------------------------------------------------------------------
-- 2. user_settings: current_stage 1..5 (renumbered), K-12 defaults for new rows
-- ---------------------------------------------------------------------------
CREATE TABLE user_settings_new (
  user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  timezone           TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
  push_time          TEXT    NOT NULL DEFAULT '08:00' CHECK (push_time GLOB '[01][0-9]:[0-5][0-9]' OR push_time GLOB '2[0-3]:[0-5][0-9]'),
  push_enabled       INTEGER NOT NULL DEFAULT 1  CHECK (push_enabled IN (0,1)),
  daily_new_count    INTEGER NOT NULL DEFAULT 10 CHECK (daily_new_count BETWEEN 0 AND 50),
  daily_screen_count INTEGER NOT NULL DEFAULT 15 CHECK (daily_screen_count BETWEEN 0 AND 50),
  max_reviews        INTEGER NOT NULL DEFAULT 60 CHECK (max_reviews BETWEEN 0 AND 300),
  stages_json        TEXT    NOT NULL DEFAULT '["xs","zk"]',  -- 目标阶段: non-empty subset of xs/zk/gk/cet4/cet6 (set by onboarding); K-12 default, mirrored by services/bank.DEFAULT_STAGES (tested)
  current_stage      INTEGER NOT NULL DEFAULT 1  CHECK (current_stage BETWEEN 1 AND 5),  -- 主攻阶段 1=xs 2=zk 3=gk 4=cet4 5=cet6; Stage string on the wire (API.md §9.1); mirrored by bank.DEFAULT_CURRENT_STAGE
  show_images        INTEGER NOT NULL DEFAULT 1  CHECK (show_images IN (0,1)),
  zh_examples        TEXT    NOT NULL DEFAULT 'tap' CHECK (zh_examples IN ('tap','always')),
  auto_pronounce     INTEGER NOT NULL DEFAULT 1  CHECK (auto_pronounce IN (0,1)),
  accent             TEXT    NOT NULL DEFAULT 'en-US' CHECK (accent IN ('en-US','en-GB')),
  email_enabled      INTEGER NOT NULL DEFAULT 0  CHECK (email_enabled IN (0,1)),
  webhook_enabled    INTEGER NOT NULL DEFAULT 0  CHECK (webhook_enabled IN (0,1)),
  webhook_url        TEXT,
  webhook_format     TEXT    NOT NULL DEFAULT 'generic' CHECK (webhook_format IN ('generic','wecom','feishu','serverchan','bark')),
  next_push_at       TEXT,
  updated_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT INTO user_settings_new (user_id, timezone, push_time, push_enabled, daily_new_count, daily_screen_count, max_reviews, stages_json,
                               current_stage, show_images, zh_examples, auto_pronounce, accent, email_enabled, webhook_enabled,
                               webhook_url, webhook_format, next_push_at, updated_at)
SELECT user_id, timezone, push_time, push_enabled, daily_new_count, daily_screen_count, max_reviews, stages_json,
       current_stage + 1, show_images, zh_examples, auto_pronounce, accent, email_enabled, webhook_enabled,
       webhook_url, webhook_format, next_push_at, updated_at
FROM user_settings;

DROP TABLE user_settings;
ALTER TABLE user_settings_new RENAME TO user_settings;
CREATE INDEX ix_user_settings_next_push ON user_settings(next_push_at);

-- ---------------------------------------------------------------------------
-- 3. Force the seed re-import on the next start and leave an operator-visible trace
-- ---------------------------------------------------------------------------
DELETE FROM kv WHERE key = 'seed_version';
INSERT INTO system_events(kind, detail_json, created_at)
VALUES ('migration', '{"version": 11, "name": "primary_stage", "stages": "xs/zk/gk/cet4/cet6", "index": "1..5", "note": "stage_min and current_stage renumbered +1; stage flags re-derived from the seed at the next import"}',
        strftime('%Y-%m-%dT%H:%M:%SZ','now'));
```

数据迁移规则（写死在文件里）：`stage_min` 与 `current_stage` 逐行 `+1`（`NULL + 1 = NULL`）；`stage_xs` 全 0（旗标由随后的种子重导从官方表重算）；`stages_json` 原样复制（存的是码）；不给任何用户自动加 `xs`；`kv.seed_version` 删除；一行 `system_events('migration')`。排练结果（`scratchpad/synthesis-stage-model/rehearse.py`，`.venv/bin/python -I`，SQLite 3.54.1）：`applied [(11,'primary_stage')] 0.050 s`；只有 `schema_migrations 4→5`、`kv 15→14`、`system_events 17→18` 行数变化；`integrity_check ok`、`foreign_key_check []`；`stage_min` 1/2/3/4 → 2/3/4/5 逐行恰好 +1；旗标 `(0, 2099, 3829, 4722, 7671)`；`difficulty + 1 = stage_min` 44 / < 2 / > 3；用户 `(1,'["zk","gk","cet4","cet6"]',4)`、`(2,'["zk"]',2)`；`v_bank` 18 行；CHECK 拒绝 `stage_min 0/6`、`stage_xs 2`、`current_stage 0/6`；`user_words(word_id=999999)` 被外键拒绝；新插设置行默认 `('["xs","zk"]', 1)`；二次运行 `[]`；空库 0001→0011 应用 `[1, 8, 9, 10, 11]`，25 张表 + `v_bank`。

### 2.3 `backend/wd/migrations/0012_word_images_meta.sql`（S5；纯附加，`--no-restart` 安全）

```sql
-- 0012_word_images_meta.sql — word_images gains prompt_version / model / text_free / eval_json
-- (docs/analysis/2026-11-05-stages-regions-images/design/PLAN.md §2.3).
--
-- Additive only: four ADD COLUMN statements, the 0010_ai_provider.sql precedent (ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT …
-- CHECK). Existing rows keep their meaning: the 30 Claude SVGs drawn before this migration printed the headword (svg_system v1),
-- so text_free stays 0 for them; prompt_version / model stay NULL (photos never get a prompt_version). No view, trigger or real
-- foreign key references word_images (v_bank joins user_words/words only; words.active_image_id and content_reports.image_id are
-- logical), nothing is rebuilt, so the file is safe under `deploy/install.sh --no-restart` (DEPLOY §10). The runner wraps the
-- file in BEGIN IMMEDIATE and records schema_migrations(12, 'word_images_meta') itself (SCHEMA.sql §1) — nothing else belongs
-- here. Numbered 0012 because 0011 is the stage-model rebuild; db.list_migration_files does not require consecutive numbers and
-- pending_migrations applies every file not yet in schema_migrations, so the files may land in either order.
ALTER TABLE word_images ADD COLUMN prompt_version TEXT;                                             -- 'svg-v2' | 'ai-v1' | NULL (photos, pre-0012 SVGs)
ALTER TABLE word_images ADD COLUMN model TEXT;                                                      -- generator model id (ai_calls.model_used or the vendor model); NULL for photos
ALTER TABLE word_images ADD COLUMN text_free INTEGER NOT NULL DEFAULT 0 CHECK (text_free IN (0,1));  -- 1 = code-guaranteed text-free file (<text>/<tspan> stripped): the only gate for any picture-first mode
ALTER TABLE word_images ADD COLUMN eval_json TEXT;                                                  -- pilot / VLM rubric scores; never overwrites `score`
```

### 2.4 `backend/wd/migrations/0013_word_forms_alias.sql`（S2；重建 `word_forms`，14k 行 `WITHOUT ROWID`，毫秒级；stop-first）

```sql
-- 0013_word_forms_alias.sql — allow seed-provided spelling aliases in word_forms (kind 'alias').
--
-- The official word lists spell some headwords differently from the dictionary lemma (Mr → mr., PE → p.e.,
-- hot-dog → hot dog; data/lists/aliases.tsv). The seed import writes those spellings as word_forms rows with
-- kind 'alias' so that lookup/search resolve them to the headword before falling back to ECDICT, whose
-- undotted entries mean something else (Mr = a memory-reclaim program). 'alt' keeps its meaning (rows written
-- by lookup_word merges / the suffix rule, never touched by the import; DESIGN §3.1). SQLite cannot ALTER a
-- CHECK list, so the table is rebuilt (14k rows, WITHOUT ROWID, milliseconds). No view references word_forms;
-- the only index is re-created below. The runner wraps this file in BEGIN IMMEDIATE with foreign_keys=OFF and
-- records schema_migrations(13, 'word_forms_alias') itself (SCHEMA.sql §1) — nothing else belongs here.
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

### 2.5 运行、回滚、SCHEMA.sql 规则、排练方法

- **运行**：Mac 上 `wd serve` 启动即 `run_migrations`（`main.py:482`，先 `backup.snapshot_before_migrate` 写 `backups/pre-migrate-10-to-13.db.gz`），所以顺序必须是「备份 → 停 → 切代码 → 起」或在停服务状态下显式 `WD_DATA_DIR=… .venv/bin/wd migrate`（推荐，§8）。三个文件同一停机窗口按编号应用；0011 与 0013 都是重建，**不可**在服务运行时应用（`DEPLOY.md §10` 的 `--no-restart` 规则）。迁移后 `ANALYZE`（`ix_words_stage_min` 的计划不漂）+ `VACUUM`（重建使文件 5.6 MB → ≈ 9.4 MB，项目无自动 VACUUM）——两者在文件外、服务停着时用 `isolation_level=None` 的连接执行。
- **回滚**：只有快照。`wd restore backups/pre-migrate-10-to-13.db.gz --yes`（要求服务已停）+ `git checkout 75df534` + 前端符号链接指回旧快照，**库与代码一起回**。没有「只回代码」的回滚：旧代码对新库不是 500 而是**静默错位**——`index_to_stage(4)='cet6'` 让 sqin 的主攻阶段显示为「六级」、kimi 显示为「高中」，而词库/筛词列表因 `stage_min=5` 不满足旧 `StageIndex` 返回 500（`schemas.py:65`、`security.py:597`）。0012 单独回代码无害（显式列名 INSERT + `SELECT wi.*`）。回滚丢失快照之后的学习记录，所以 §8 第 4–11 步一气呵成、选无人学习的时段。
- **`docs/SCHEMA.sql`**：不改（`test_db.py:362-366` 字节一致）；新 DDL 只进新迁移文件；`DESIGN.md §3.1` 加一句「当前 schema = 0001 + 0008 + 0009 + 0010 + 0011 + 0012 + 0013；`words`/`user_settings` 的现行 DDL 见 0011 文件头，`word_forms` 见 0013，`word_images` 四列见 0012」。不新建 `SCHEMA_CURRENT.sql`。
- **排练方法**（上线前在本机、Lighthouse 部署前在目标机各跑一次；永远不碰 `/Users/sqin/word-dance-data`）：
  1. `cp scratchpad/live-copy.db <私有目录>/word-dance.db`（线上则 `cp` 停服务后的库）。
  2. `WD_DATA_DIR=<私有目录> .venv/bin/wd migrate --dry-run` → 应恰好列出 `(11,'primary_stage') (12,'word_images_meta') (13,'word_forms_alias')`；`.venv/bin/wd migrate`。
  3. `.venv/bin/python -I scripts/rehearse_migration.py <私有目录>/word-dance.db`（S6 把 `scratchpad/synthesis-stage-model/rehearse.py` 移植进仓库：对比迁移前后 `stage_min` 逐行 +1、`current_stage` +1、旗标和、`difficulty + 1 = stage_min` 计数、`v_bank` 行数、CHECK 拒绝探针、`PRAGMA table_info(word_images)` 含四列、`word_forms` CHECK 含 `'alias'`、`integrity_check`/`foreign_key_check`、二次运行为空）。
  4. `WD_DATA_DIR=<私有目录> .venv/bin/wd import-seed --dry-run --report <私有目录>/dry.json` → 与 §7.3 的预期一致后 `.venv/bin/wd import-seed`；再 `WD_FULL_SEED_DB=<私有目录>/word-dance.db .venv/bin/python -m pytest backend/tests -q -m full_seed`。
  5. 生产机 SQLite 版本未知：`RENAME` 新语义需 ≥ 3.26，`wd check db` 的 `json_each` 需 ≥ 3.38（只影响诊断）；本机 3.54.1。

---

## 3 统一的契约变更清单（逐项新旧值；同一「contract change」提交 = S1 + S4 合入后的集成点，`make check-contract` 在集成门禁执行）

### 3.1 `backend/wd/schemas.py`（S1）

| 位置 | 旧 | 新 |
|---|---|---|
| `:9-10` docstring | 「1–4 column」 | 「1–5 column」 |
| `:25` | `Stage = Literal["zk", "gk", "cet4", "cet6"]` | `Stage = Literal["xs", "zk", "gk", "cet4", "cet6"]` |
| `:26` | `StageIndex = Literal[1, 2, 3, 4]` | `StageIndex = Literal[1, 2, 3, 4, 5]` |
| `:46` `ImageProviderName` | 不变（配图三期才加 `ai_image`） | 不变 |
| `:47` `Difficulty` | `Literal[1, 2, 3, 4, 5]` | 不变 |
| `:51` | `STAGE_ORDER = ("zk", "gk", "cet4", "cet6")` | `("xs", "zk", "gk", "cet4", "cet6")` |
| 新增 `:52` | — | `STAGE_INDEX: dict[str, int] = {"xs": 1, "zk": 2, "gk": 3, "cet4": 4, "cet6": 5}`（测试断言 `== STAGE_ORDER.index(s) + 1`） |
| `:52` | `STAGE_NAMES_ZH = {"zk": "初中", …}` | `{"xs": "小学", "zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}` |
| `:56-61` `stage_to_index` | `STAGE_ORDER.index(stage) + 1` | 查 `STAGE_INDEX`，`KeyError` → `ValueError(f"unknown stage {stage!r}")` |
| `:64-67` `index_to_stage` | `1 <= index <= 4` | `1 <= index <= len(STAGE_ORDER)` |
| `:472` `WordBrief.stage_min: StageIndex \| None` | 自动随 `StageIndex` | 不变 |
| `:488` `VocabQuery.stage` | `Literal["all", "zk", "gk", "cet4", "cet6"]` | `Literal["all", "xs", "zk", "gk", "cet4", "cet6"]` |
| `:708` `ScreenNextQuery.stage` | `Literal["zk", "gk", "cet4", "cet6", "auto"]` | `Literal["xs", "zk", "gk", "cet4", "cet6", "auto"]` |
| `:1335` `PrewarmRequest.stage` | `Literal["zk", "gk", "cet4", "cet6", "all"]` | `Literal["xs", "zk", "gk", "cet4", "cet6", "all"]` |
| `:361-362` `current_stage ∈ stages` 校验 | 不变 | 不变 |

### 3.2 `frontend/src/api/types.ts`（S4；「API.md §9 copied verbatim」）

| 位置 | 旧 | 新 |
|---|---|---|
| `:5` | `export type Stage = 'zk' \| 'gk' \| 'cet4' \| 'cet6';           // index 1..4 in that order` | `export type Stage = 'xs' \| 'zk' \| 'gk' \| 'cet4' \| 'cet6';   // index 1..5 in that order` |
| `:6` | `export type StageIndex = 1 \| 2 \| 3 \| 4;` | `export type StageIndex = 1 \| 2 \| 3 \| 4 \| 5;` |
| `:37` `Settings` 注释 | 「the server stores the 1–4 index」 | 「1–5 index」 |
| `:45` `StageInfo.name_zh` 注释 | `// 初中 / 高中 / 四级 / 六级` | `// 小学 / 初中 / 高中 / 四级 / 六级` |
| `:52` `WordBrief.stage_min: StageIndex \| null` | 自动 | 不变 |
| `:73` `Content.difficulty: 1 \| 2 \| 3 \| 4 \| 5` | 不变 | 不变 |
| `:84` `ImageMeta.provider` 内联字面量 | 不变 | 不变（三期才提成 `ImageProviderName`） |

`check_contract.py:151-171` 只收 `export type X = 'a' \| 'b';` 形式的联合，`:274-281` 顺序敏感比对 `Stage`/`StageIndex` 与 `schemas.py` 的 `Literal` —— 两边都写 `xs, zk, gk, cet4, cet6` / `1, 2, 3, 4, 5`。`endpoints.ts:131 VocabStageFilter`、`:196 ScreenStage`、`:328 PrewarmStage` 由 `Stage` 派生，自动。

### 3.3 `docs/API.md`（S4）

| 行 | 旧 | 新 |
|---|---|---|
| `:155` 端点 12 | 「maps it to the 1–4 column index」 | 「1–5」 |
| `:160` 端点 15 | `stages non-empty ⊆ {zk,gk,cet4,cet6}` | `⊆ {xs,zk,gk,cet4,cet6}` |
| `:167` 端点 19 | 「(4 rows, …)」 | 「(5 rows, …)」 |
| `:169` 端点 20 | `stage=all\|zk\|gk\|cet4\|cet6`；「for cet6 this is the 3,694-word CET-6 increment」；`difficulty: ORDER BY COALESCE(difficulty, stage_min, 5)` | `stage=all\|xs\|zk\|gk\|cet4\|cet6`；「for cet6 this is the CET-6 increment (`stats.json.first_stage.cet6`)」；`COALESCE(difficulty + 1, stage_min, 6)` 并注「`difficulty` is the 1–5 Claude scale (1 = 初中 basic) shifted by one onto the 1–5 stage index; 6 = beyond CET-6 or outside every list」 |
| `:187` 端点 31 | `stage=zk\|gk\|cet4\|cet6\|auto` | `stage=xs\|zk\|gk\|cet4\|cet6\|auto` |
| `:230` 端点 67 | `{stage: "zk"\|"gk"\|"cet4"\|"cet6"\|"all", …}` | `"xs"\|"zk"\|"gk"\|"cet4"\|"cet6"\|"all"` |
| `:239-240` §9 | 同 types.ts `:5-6` 旧值 | 同 types.ts `:5-6` 新值（逐字） |
| `:271` | 「the server stores the 1–4 index」 | 「1–5」 |
| `:279` | `// 初中 / 高中 / 四级 / 六级` | `// 小学 / 初中 / 高中 / 四级 / 六级` |
| `:459-460` §9.1 | 「`zk→1, gk→2, cet4→3, cet6→4`」 | 「`xs→1, zk→2, gk→3, cet4→4, cet6→5`」 |

### 3.4 `frontend/src/i18n/zh.ts` ↔ `docs/FRONTEND.md §8`（S4；`zh.test.ts:67-83` 逐行比对、`zh.contract.test.ts:61-83` 键值比对、`npm run lint` = `scripts/check-copy.mjs`）

| `zh.ts` 行 | 旧 | 新（`FRONTEND.md` 对应行逐字相同） |
|---|---|---|
| `:25` `welcome.roles` | `{ zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }` | `{ xs: '小学生', zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }`（`FRONTEND.md:231`） |
| `:28-29` `stages` | `{ zk: '初中', gk: '高中', cet4: '四级', cet6: '六级', zkFull: '初中（中考）', gkFull: '高中（高考）', cet4Full: '大学英语四级', cet6Full: '大学英语六级', newOnly: '仅本阶段新增', newOnlyCet6: '仅六级新增（不含四级）', star: '六级星标词' }` | `{ xs: '小学', zk: '初中', gk: '高中', cet4: '四级', cet6: '六级', xsFull: '小学（课标二级词汇）', zkFull: '初中（中考）', gkFull: '高中（高考）', cet4Full: '大学英语四级', cet6Full: '大学英语六级', newOnly: '仅本阶段新增', newOnlyZk: '仅初中新增（不含小学）', newOnlyCet6: '仅六级新增（不含四级）', outside: '课标外', star: '六级星标词' }`（`FRONTEND.md:234-235`） |
| `:86` `sources.lists` | `'词表范围：中考、高考、大学英语四级与六级大纲'` | `'词表范围：小学（课标二级）、初中（课标三级与上海市初中英语词汇表）、高中（高中课标词表）、大学英语四级与六级大纲'`（`FRONTEND.md:292`） |

`FRONTEND.md` 其余同步行：`:50`（角色加 小学生 → 小学；初中生 → 小学+初中）、`:56`（页签 全部 / 小学 / 初中 / 高中 / 四级 / 六级）、`:85`/`:89`（`StageChips`：五阶段、`only`、课标外芯片）、`:147`（§5.5：最低阶段不显示开关；初中页签文案 仅初中新增（不含小学））。`docs/qa-frontend.md:36,42` 同步。

### 3.5 `docs/CLAUDE_INTEGRATION.md`（S5）

| 位置 | 旧 | 新 |
|---|---|---|
| §4.1 `content_v1.json`（`:146-160`）、`backend/wd/ai/schemas/content_v1.json`、`backend/tests/fixtures/claude_schemas.json` | 三方逐字节相同（`test_schemas.py:56`） | **不改**（`difficulty` enum/description 不动，不加 `image_scene_en`） |
| §5 标题 `:206` | `PROMPT_VERSION = 'content-v1'` | `'content-v2'` |
| §5.1 `:210-226` 代码块 | 现 `content_system.txt` | 与新 `content_system.txt` 逐字节相同（`test_schemas.py:123`；§5.2 全文） |
| §5.2 `:232` 示例 audience | `"Chinese learners, junior high school to CET-6, plus working professionals"` | `"Chinese learners from primary school (小学) to CET-6, plus working professionals"`（= `content.AUDIENCE`） |
| §5.5 `:281-285` | 现 `svg_system.txt` + 旧用户提示词示例 | 新 `svg_system.txt`（§5.1）+ 新用户提示词形状 |
| §6.1 `:296-300` `generate_svg` 行 | — | 加「`prompt_version`/`model`/`text_free` 写入 `word_images`」 |
| §6.4 `:355` | 「`en` 15–240 chars」 | 「10–240」（`docs/AI_FALLBACK_MODEL.md:29` 同步） |
| §6.7 `:401-403` | — | `clean(svg, allow_text=False)`、裸 `&` 修复、`<desc id="aigc-label">`、「never retried automatically」→ 重试规则 |
| §7 `:407,416` | 「$0.028」「≈ 18 cards/day」 | 「$0.0124/次调用（$0.0140/张交付，2026-11-05 实测 34 次）」「≈ 35–40 cards/day」；`budget.ESTIMATES["svg"]` 保持 0.03 |

### 3.6 其他字面量副本（去副本后只剩这些）

| 文件 | 旧 | 新 | 切片 |
|---|---|---|---|
| `backend/wd/seed.py:43` `STAGES` | 四元组 | 删除；`from .schemas import STAGE_ORDER, stage_to_index`，`STAGE_COLUMNS = tuple(f"stage_{s}" for s in STAGE_ORDER)` | S2 |
| `backend/wd/services/words.py:39` `STAGES` | 四元组 | `STAGES = schemas.STAGE_ORDER`（保留名字） | S2 |
| `backend/wd/services/ecdict.py:28` | `STAGE_TAGS` 四元组 | 保留 + `MEMBER_TAGS = ("cet4", "cet6")` | S2 |
| `backend/wd/ai/prewarm.py:32-33` | 两个四阶段字典/元组 | `STAGE_COLUMNS = {s: f"stage_{s}" for s in STAGE_ORDER}`；`STAGES = (*STAGE_ORDER, "all")` | S2 |
| `backend/wd/ai/content.py:49` | `STAGE_ZH` 四键 | `STAGE_ZH = schemas.STAGE_NAMES_ZH` | S5 |
| `backend/wd/services/bank.py:85-86` | `("cet4","cet6")` / `3` | `("xs","zk")` / `1`（绑定 DDL 默认的测试） | S2 |
| `scripts/smoke.py:352,614` | 四阶段 / `== 4` | 五阶段 / `== 5` | S2 |
| `scripts/eval_provider.py:107` | 四阶段 | 五阶段 | S2 |
| `frontend/src/components/word/StageChips.tsx:7-9` | 四阶段三常量 | `['xs','zk','gk','cet4','cet6']`、`{xs:1,…,cet6:5}`、`{1:'xs',…,5:'cet6'}` | S4 |
| `frontend/src/pages/VocabPage.tsx:29` | `['all','zk','gk','cet4','cet6']` | `['all','xs','zk','gk','cet4','cet6']` | S4 |
| `frontend/src/pages/AdminPage.tsx:36` | `['zk','gk','cet4','cet6','all']` | `[...STAGE_ORDER, 'all']` | S4 |
| `frontend/src/pages/ScreenPage.tsx:20` `FULL_NAME`、`WelcomePage.tsx:42` `STAGE_FULL` | 四键 | 加 `xs: zh.stages.xsFull` | S4 |

---

## 4 词表与种子（S3 构建期 · S2 导入期）

### 4.1 `data/lists/` 文件清单与格式

已交付、**一字不改**（文件名、`#` 头注释、括注/斜杠/等号写法、TSV 列都是构建器的输入契约；实测非注释行数）：

| 文件 | 行 | 格式 | manifest `id` / `policy` | 授予 |
|---|---|---|---|---|
| `moe-2022-level2.txt` | 505 | 一行一词头（`a/an`、`colour (AmE color)` 等原件记法） | `moe22:l2` / `main` | xs |
| `moe-2022-level3.txt` | 1600 | 同上（含二级，星号已去） | `moe22:l3` / `main` | zk |
| `moe-2022-appendix.tsv` | 267 | `类别<TAB>词<TAB>附加1<TAB>附加2`；类别实测：数词-基数词 30 · 数词-序数词 28 · 月份 12 · 星期 7 · 地理名称 27 · 地理名称-派生 18 · 地名景点 8 · 节日 13 · 其他专有名词 11 · 缩写 7 · 不规则动词 106 | `moe22:app` / `appendix` | 数词（单 token）/月份/星期 → xs+zk；地理/派生/缩写/节日/景点/其他专名 → zk；不规则动词 `member: false` |
| `shmeea-2020-junior.txt` | 1724 | 一行一词头（`a/an/the` 不在正文） | `shmeea20` / `main` | zk |
| `shmeea-2020-junior-appendix.tsv` | 158 | `词<TAB>节<TAB>注`；节：人称代词 12 · 物主代词 14 · 反身代词 8 · 基数词 39 · 序数词 33 · 月份 12 · 星期 7 · 国家/大洲 13 · 国籍/洲人 14 · 常用学科 6 | `shmeea20:app` / `appendix` | 全部 → zk（数词只收单 token） |
| `shmeea-2020-junior-phrases.txt` | 342 | 一行一词组（`a bit (of)`、`at first/last`、`agree with sb.`） | `shmeea20:phr` / `phrases` | zk（只收 ECDICT 有条目且通过严格门者） |
| `shmeea-2020-junior-forms.tsv` | 146 | `词头<TAB>kind<TAB>原文<TAB>位置` | `shmeea20:forms` / `reference` | 不授予；R2 测试样例来源 |
| `moe-2020-senior.tsv` | 3000 | `词<TAB>level`（0/1/2 = 1500/499/1001） | `hs20` / `main`，`level_token: "hs20:{level}"` | gk |
| `moe-2025rev-senior.tsv` | 3099 | 同上（1600/502/997） | `hs25` / `main`，`level_token: "hs25:{level}"`，`provisional: true` | gk |
| `moe-2020-senior-appendix.tsv` · `moe-2025rev-senior-appendix.tsv` | 55 · 56 | `国名中文<TAB>国名<TAB>人<TAB>形容词` | `hs20:app` · `hs25:app` / `reference` | 不授予（R-5） |
| `moe-2022.README.md` · `shmeea-2020-junior.README.md` · `moe-senior.README.md` · `moe-senior-2020-vs-2025.diff.txt` | — | 来源、页码、解析规则、核验修正 | — | — |

S3 新建（只增不改）：`data/lists/README.md`（索引 + provenance 表 + 许可段 + 行格式）、`manifest.json`（`format: 2`，全文按 `design/word-lists/SYNTHESIS.md §3.2.2`，**两处调整**：`hs20` 加 `"level_token": "hs20:{level}"`；`inherit_stages` 保留 `be/have/do` 三组）、`aliases.tsv`（6 行：`Mr→mr.`、`Mrs→mrs.`、`Ms→ms.`、`PE→p.e.`、`hot-dog→hot dog`、`humourous→humorous`）、`overrides.tsv`（23 行，列 `lemma<TAB>field<TAB>value<TAB>note`，`field ∈ translation|word|phonetic|definition|drop`，全文按 WL §3.2.4，含 `bund/the bund(drop)/mum/p.e./physical education/ai/bce/ce/cpc/un/wto/tcm/qipao/beijing opera/tian'anmen square/communist party of china/world trade organization/children's day/women's day/the changjiang river/stuck/wi-fi/e-mail(word)`；上限 30 条）、`SHA256SUMS`（11 个词表文件的 `shasum -a 256` 格式，构建器校验）。行格式：UTF-8 无 BOM、LF、`#` 整行注释；词头列不得含 CJK（唯一例外：不规则动词组的消歧注 `hang (悬挂)`，在成员判定前即被丢弃）。manifest 不写阶段顺序、不写阶段中文名（唯一真相 `schemas.STAGE_ORDER`/`STAGE_NAMES_ZH`）。

### 4.2 集合代数（`seedbuild/build.collect_members`；元素都是 `words.normalise_lemma(fold(text))` 口径的小写 lemma）

```
L2    = heads(moe22:l2) ∪ variants(moe22:l2)                                   # 505 行 → ≈520 lemma
L3    = heads(moe22:l3) ∪ variants(moe22:l3)                                   # 1600 行 → ≈1,646
APPxs = moe22:app{数词-基数词, 数词-序数词}(单 token) ∪ moe22:app{月份, 星期}          ∩ (ECDICT ∪ 上一版种子)   # ≈77
APPzk = APPxs ∪ moe22:app{地理名称, 地理名称-派生, 缩写, 节日, 地名景点, 其他专有名词} ∩ (ECDICT ∪ 上一版种子)   # ≈168
SH    = heads∪variants(shmeea20) ∪ shmeea20:app(各节; 数词单 token)            ∩ (ECDICT ∪ 上一版种子)   # ≈1,871
SHP   = phrases(shmeea20:phr) ∩ ECDICT ∩ strict_ok                             # 303 条 → ≈333 lemma
HS    = heads∪variants(hs25) ∪ heads∪variants(hs20)                            # ≈3,162 ∪ 3,045 = 3,256
INH   = { f ∈ manifest.inherit_stages[*] : f 是上一版种子的 lemma 且 f ∉ L2∪L3∪SH∪HS }   # 实测 {am, is, are, does}

xs    = L2 ∪ APPxs ∪ { f ∈ INH : base(f) ∈ xs }
zk    = L3 ∪ APPzk ∪ SH ∪ SHP ∪ { f ∈ INH : base(f) ∈ zk }       # xs ⊆ zk 由 L2 ⊆ L3、APPxs ⊆ APPzk 构造保证
gk    = HS ∪ { f ∈ INH : base(f) ∈ gk }                          # 国家名称附表不入
cet4  = 上一版种子的 stage_cet4 ∪ ECDICT tag cet4(新行) ∪ 外部 CET4/CET46∩CET4 表（存在时）
cet6  = 上一版种子的 stage_cet6 ∪ ECDICT tag cet6(新行) ∪ 外部 CET6/CET46∖CET4 表（存在时）
宇宙  = 上一版种子全部 lemma ∪ xs ∪ zk ∪ gk                      # retain：只增不减
stage_min(w) = min{ schemas.stage_to_index(s) : s ∈ stages(w) }；stages 为空 → NULL
```

构建期断言（任一失败 exit 2，不写输出）：① `xs ⊆ zk`；② 每个阶段码 ∈ `schemas.STAGE_ORDER`；③ 宇宙 ⊇ 上一版 lemma 集；④ `policy: main` 的每个词头都解析到 ECDICT 或上一版种子（否则列出缺失）；⑤ 同一 lemma 不产生两条记录（`Miss`/`miss`、`May`/`may`、`A.M.`/`a.m.` 构建期合并：阶段并集、令牌并集）；⑥ 新行 `translation` 首行非空（`stats.empty_translation == 0`）。**不断言** `zk ⊆ gk`（复算 212 个单词 + 333 个词组只在 zk）。

### 4.3 规范化规则（`seedbuild/normalise.py`，纯函数，交付行表驱动测试；以 WL §3.3 为准，这里只列规则名与关键例）

| # | 规则 | 关键例 → 结果 |
|---|---|---|
| R1 折叠 | NFKC → 弯引号/破折号/全角 `（）＝／，` → ASCII（复用 `words._CHAR_MAP` 并补全角）→ NFD 去变音 → 压空白 | `café`→`cafe`；`o’clock`→`o'clock` |
| R2 括注分类（仅最后一个括号） | `pl.`/`复`/含 CJK → 丢弃；项目 > 2 token 则整个括注作一项；项与词头同 lemma → 别名；词头的屈折形（ECDICT `exchange`/`0:` 指针/词头 ∈ {be,have,do}）→ 丢弃；单项 ∈ {to,for,with,on,at,in,of,up,out} 且 `词头 项` ∈ ECDICT → 搭配成员（裸词头只在已是上一版 lemma 时才是成员）；否则 ∈ ECDICT → 变体成员；否则 `unparsed_notes` 警告 | `colour (AmE color)`→变体 `color`；`maths (=mathematics, AmE math)`→两个变体；`PE (=physical education)`→别名 `p.e.` + 变体 `physical education`；`be (am, is, are)`→丢弃（经 R8 继承）；`according (to)`→成员 `according to`；`UNESCO (United Nations Educational, …)`→单项，R12 拒；`bund (the Bund)`→`the bund` 经 overrides `drop` |
| R3 并列 | 词头按 `/` 与 `=` 拆成多个词头 | `a/an`、`exam=examination`、`policeman/policewoman (pl. …)` |
| R4 可选后缀 | 紧贴词头的 `(s)`/`(es)` → 两个词头（**必须**紧贴且内容是 s/es，否则 `a (an)` 会被吃掉） | `manner(s)`→`manner`,`manners`；`toward(s)` |
| R5 别名 | `aliases.tsv` 只作用于官方词头与变体，从不作用于上一版 lemma | `Mr`→`mr.`；`hot-dog`→`hot dog`；`humourous`→`humorous` |
| R6 大小写合并 | lemma 全小写；同 lemma 多词头构建期合并；display 取上一版/ECDICT 原形 | `Miss`/`miss`、`China`/`china` |
| R7 屈折形作词头 | 官方列为词头的分词形容词建独立行；`seed.py:239-241` 表头词守卫让 `excited→excite` 的词形行自然消失 | `excited, frightened, stuck, satisfied, united …`（≈15 行） |
| R8 继承 | `manifest.inherit_stages` 的形式若已是上一版 lemma 且非官方词头 → 继承原形阶段，令牌 `inherit:<base>`；从不建行 | `am, is, are`←`be`；`does`←`do` |
| R9 词组 | `…`→` ... `；可选括号 `(of)`/`(a)` 展开含/不含两种；`/` 按 token 级展开；候选必须含空格、∈ ECDICT、过 R12；模板（`sb./sth./one's/...`）跳过入 `stats.skipped.patterns` | `a bit (of)`→`a bit`,`a bit of`；`at first/last`→两条；`agree with sb.`→跳过 |
| R10 连字符/空格 | 查 ECDICT 依次试原形 → 空格↔连字符；**多词词头禁止去空格匹配** | `break down ≠ breakdown`；`ice-cream` 与 `ice cream` 并存 |
| R11 英美变体 | 由 R2 变体规则覆盖，两边都是成员 | `programme/program`、`realise/realize` |
| R12 严格门 | 每个候选过 `words.normalise_input`（`^[A-Za-z' .\-]+$`、≤ 48 字符、≤ 4 token、无纯标点 token、带点 token ≤ 6）；主表词头不过 → 失败；附表/变体/词组不过 → 警告跳过 | 拒 `The United States of America`（5 token）、UNESCO 全称（66 字符）、7 条 `...` 词组 |

`scripts/build_seed.py:16 RICH_RE` 的缺陷顺带修复（`parse_mahavivo(path, mode)` 先 R1 折叠再用放宽正则；`len(line)==1` 的跳过改为「单个大写字母」），但中考/Highschool 两表已退出，它只服务可选的 CET 四表。

### 4.4 `words.sources` 令牌表（唯一定稿；写进 `data/seed/ATTRIBUTION.md` §5 与 `DESIGN.md §3.2`）

| 令牌 | 含义（来源文件） | 授予 | 复算行数 |
|---|---|---|---|
| `ecdict` | ECDICT 带任一考试标签（不变） | — | 8,285 |
| `cet4` / `cet6` / `cet46` | mahavivo CET 表归属（不变；表缺席时现有行保留） | cet4 / cet6 | 4,539 / 2,220 / 8,007 |
| `moe22:l2` / `moe22:l3` / `moe22:app` | 国家 2022 二级 / 三级 / 附表 | xs / zk / 按类别 | 520 / 1,646 / 168 |
| `shmeea20` / `shmeea20:app` / `shmeea20:phr` | 上海 2020 单词 / 附表 / 词组 | zk | 1,737 / 142 / 333 |
| `hs20:0` / `hs20:1` / `hs20:2` | 高中课标 2020 版 无星（义务教育 1500）/ ★ / ★★ | gk | 合计 3,045 |
| `hs25:0` / `hs25:1` / `hs25:2` | 2025 修订版 无星（1600）/ ★ 必修 / ★★ 选择性必修 | gk | 1,646 / 504 / 1,012 |
| `inherit:be` / `inherit:have` / `inherit:do` | 按 `manifest.inherit_stages` 继承 | 原形的阶段 | 3 / 0 / 1 |
| `legacy:zk` / `legacy:gk` | 75df534 种子里带 `stage_zk` / `stage_gk`（旧中考表 ∪ ECDICT zk / 旧 Highschool ∪ ECDICT gk）；不授予；将来「拓展」层候选集 | — | 2,099 / 3,829 |
| （删除）`zk`、`gk` | 改名为 `legacy:*` | | |

变体与别名不另设令牌（`variant_of`/`aliases` 只在种子文件里）。

### 4.5 构建器：`backend/wd/seedbuild/`（S3）与 `scripts/build_seed.py` 重构范围

```
backend/wd/seedbuild/__init__.py     # 空
backend/wd/seedbuild/normalise.py    # R1–R12：fold, canon, classify_note, split_head, phrase_candidates, strict_ok, merge_heads, ecdict_candidates
backend/wd/seedbuild/build.py        # Manifest 读取/校验、来源加载、集合代数、记录生成、stats、ATTRIBUTION、确定性输出
backend/wd/seedbuild/diff.py         # 两版种子的差异报告与不变量
scripts/build_seed.py                # 全文替换为入口：from wd.seedbuild.build import main; raise SystemExit(main())
scripts/seed_diff.py                 # 新入口：from wd.seedbuild.diff import main
```

CLI（`$(PY)` = `.venv/bin/python`，`-I` 下 `import wd.seedbuild` 成立——实测）：
```
.venv/bin/python -I scripts/build_seed.py --manifest data/lists/manifest.json --previous data/seed/vocab.jsonl.gz \
    [--ecdict PATH] [--wordlists DIR] --out data/seed [--no-strict] [--built-at ISO]
.venv/bin/python -I scripts/seed_diff.py OLD.jsonl[.gz] NEW.jsonl[.gz] [--md PATH] [--json PATH] [--no-invariants]
```
`build.py` 签名：`load_manifest(path) -> Manifest`（校验 `format==2`、policy/format 已知、`stages ⊆ schemas.STAGE_ORDER`、文件存在、`SHA256SUMS` 匹配、`expect_rows == 非注释行数`）；`load_previous(path)`；`class Ecdict`（`word = ? COLLATE NOCASE`；`path=None` 时永远 miss）；`collect_members(m, prev, ec) -> Membership`；`make_records(membership, prev, ec, m, wordlists)`（旧 lemma 逐字复制上一版记录只改 `stages/sources/aliases`，新 lemma 从 ECDICT 生成——字段映射同现 `build_seed.py:180-198` 的 `make_record`，再套 overrides，去 `[网络] ` 前缀并计数）；`build(...) -> BuildStats`；`render_attribution(m, stats)`；`main(argv)`。排序 `(stage_to_index(stage_min) if stage_min else 99, lemma)`；`vocab.jsonl` 固定键序、`ensure_ascii=False`、LF、无时间戳 → **两次构建字节相同**。`Makefile:93-98` 的 `seed` 目标改为 build → seed_diff（与 `git show HEAD:data/seed/vocab.jsonl.gz`）→ `scripts/pack_seed.sh`；`ECDICT_DB` 只在有新词头时需要，`WORDLISTS_DIR` 可选。`pack_seed.sh` 修 BSD 可移植性（`zcat`→`gzip -dc`、`sha256sum`→`shasum -a 256` 回退、`stat -c %s`→`wc -c <`）并校验 `stats.json.content_sha256`。

**种子记录 v2**（S3 产出、S2 消费的格式契约；键序固定）：

| 键 | 含义 | 导入器（S2） |
|---|---|---|
| `word` | display（上一版/ECDICT 原形；`overrides.word` 可改） | → `display`、`derive_kind` |
| `lemma` | 构建器算出的 lemma | 核对：≠ `seed_row` 计算值 → `SeedStats.lemma_mismatch += 1` + WARNING，行为不变 |
| `phonetic, translation[], definition[], pos, collins, oxford, exam_tags[], bnc, frq, exchange{}, ecdict_id, cet6_star` | 同 v1 | 不变 |
| `stages[]` | 阶段码，按 `STAGE_ORDER` 排序 | 五个 `stage_*` + `stage_min = min(stage_to_index)`；未知码计数 + WARNING |
| `sources[]` | §4.4 令牌，排序 | 空格连接（`seed.py:210` 不变） |
| `aliases[]` | 只在有别名的记录出现（如 `["mr"]`，`normalise_lemma` 后） | `word_forms(kind='alias')`，表头词守卫同样适用 |
| `variant_of` | 只在变体记录出现 | 忽略 |
| `seed_v` | `2` | 忽略 |

### 4.6 `stats.json` v2、ATTRIBUTION、许可

`stats.json`：`seed_v, content_sha256, total_words, previous_sha256, ecdict_release, external_lists ("absent"|"present"), per_stage{xs…cet6}, first_stage{xs…cet6, none}, only_stage, per_kind{word,phrase,abbreviation,proper_noun}, lists{<id>: {rows, heads, variants, members, missing[], skipped[]}}, tokens{…}, variants, aliases, inherited[], overrides_applied, network_translations, new_words, stageless, rows_changed_vs_previous{stage_set, sources_only}, with_phonetic, with_translation, with_definition, with_exchange, multiword, uppercase, file_bytes`；`per_stage/first_stage` 键序 = `STAGE_ORDER`；`pack_seed.sh` 只读 `total_words`。`data/seed/ATTRIBUTION.md` 由 `render_attribution` 从 manifest 渲染（§1 ECDICT 不变；§2 官方词表——`main/appendix/phrases` 各一行，含 `provisional`；§3 mahavivo CET 四表——可选、不分发、本次构建是否使用；§4 `overrides.tsv` 人工释义条数；§5 令牌表）。根 `ATTRIBUTION.md:14` 的「9,162 records」改为引用 `stats.json`，`:19-32` §2 改写为「2a 官方词表（只用词头：教育部 2022 课标附录 3、2017 年版 2020 年修订与 2025 修订高中课标附录 2、上海市教育考试院 2020 词汇表——词头清单接近事实数据，不收录释义/音标/选排/版式；未声明许可，《著作权法》第五条是否适用未核实）」+「2b mahavivo CET 四表（可选输入）」，注明 `中考英语词汇表.txt`、`Highschool_edited.txt` 已停用（出处以 `legacy:*` 令牌保留）。`data/licenses/` 不新增文件（没有可引用的许可证文本）。新词头的词典字段来自已校验的 `stardict.db`（`scratchpad/ecdict-dl/extract/stardict.db`，zip sha256 与 `deploy/fetch_ecdict.sh` 钉死值相同；上线前再 `shasum -a 256` 一次）。

### 4.7 导入语义（`backend/wd/seed.py`，S2）

不变：按 lemma UPSERT、覆盖全部种子列、从不删行、不碰内容/配图/`difficulty`/每用户表、一个 `BEGIN IMMEDIATE`。改动：① `:43 STAGES` 删除，`STAGE_COLUMNS` 由 `schemas.STAGE_ORDER` 生成并替换 `SEED_COLUMNS:60-63` 的四个旗标列（`_UPSERT_SQL` 自动）；② `:184-185` 未知码计数（`SeedStats.unknown_stage_codes`，结束时一条 WARNING 列前 5 个码）；③ `:204-208` 五旗标 + `stage_min = min(stage_to_index(s))`；④ `seed_row` 增 `_aliases`、`_lemma_declared`（下划线键，UPSERT 忽略）；⑤ `_rebuild_forms:218-245` 在 exchange 词形之后写别名行（守卫：`form != lemma and form not in lemmas`），`DELETE … kind != 'alt'` 不变（alias 也重建）；⑥ `seed_digest(path)` = 解压后内容 sha256，`kv.seed_version` 写它，`SeedStats` 保留文件 `sha256` 并增 `content_sha256`；⑦ `import_seed(conn, path, *, force=False, dry_run=False)` + `plan_import(conn, rows) -> SeedPlan`（`inserted/updated/unchanged/orphans/flag_added/flag_removed/min_lowered/min_raised/stageless/matrix/samples`），`cmd_import_seed` 加 `--dry-run` 与 `--report PATH`；守卫只报告不拒绝；⑧ docstring `:1-20`。`main.seed_check:307-319` 全文按 WL §3.5 替换（内容哈希比较；`except Exception` → `log.exception` + `system_events('seed_import_failed')` + 继续启动）。`services/ecdict.py`：`MEMBER_TAGS`、`stages`、`has_stage_tag`、`word_columns`（§3.6）。`services/words.py:40-50`：`FORM_KINDS` 加 `"alias"`，`FORM_KIND_ZH["alias"] = "另一种写法"`。

### 4.8 差异报告与预期数字

`seedbuild/diff.py` → `data/seed/DIFF.md`（随种子提交，覆盖式）：(a) 记录数、新增、消失、阶段变化数、字段变化数；(b) `stage_min` 迁移矩阵（旧 1..4/∅ × 新 1..5/∅）与每阶段 ±；(c) 逐词清单；(d) 值得人工看的：失去全部阶段的词、译文含 `[网络]` 的新词、`merged_heads`、`aliases`、display 变化；(e) 不变量：新 lemma 集 ⊇ 旧、`xs ⊆ zk`、`per_stage` 与 `stats.json` 一致——失败 exit 1。

复算预期（`scratchpad/word-lists-synthesis/recount.json`；验收容差 ±1%，最终以 `stats.json` 为准）：

| 旧 \ 新 | 1 xs | 2 zk | 3 gk | 4 cet4 | 5 cet6 | 无 | 行计 |
|---|---|---|---|---|---|---|---|
| 1 (zk) | 573 | 1,117 | 188 | 122 | 30 | 69 | 2,099 |
| 2 (gk) | 8 | 315 | 681 | 399 | 220 | 169 | 1,792 |
| 3 (cet4) | 2 | 68 | 302 | 1,205 | — | — | 1,577 |
| 4 (cet6) | 1 | 24 | 69 | — | 3,600 | — | 3,694 |
| 新行 | 16 | 424 | 15 | — | — | — | 455 |
| 列计 | 600 | 1,948 | 1,255 | 1,726 | 3,850 | 238 | 9,617 |

导入足迹 ≈ 4,357 行 UPDATE（2,601 行旗标变化 + 1,756 行只有 `sources`）+ 455 行 INSERT，4,805 行不动；两位用户 77 个生词 0 个失去阶段（用户 2 的 10 个生词全部多出「小学」，在主攻初中的推荐排序里距离 0 → 2，发布说明写一句）；49 个内容词 0 个失去阶段；238 个无阶段词 0 个被持有、0 个有内容/图。

---

## 5 配图：第一期（无需新 key，S5）与第二期（试点）

### 5.1 第一期范围（= `design/images/SYNTHESIS.md §4.1` C1–C8，去掉两处即时重试挂点 R-16；零 `schemas.py`/`types.ts`/`API.md §9` 改动）

| 提交 | 内容 | 文件（全部属 S5） |
|---|---|---|
| C1 文档数字 | `$0.028/张`→`$0.0124/次（$0.0140/张交付，拒收 11.8%，2026-11-05 实测 34 次）`、`≈18 cards/day`→`≈35–40`；`budget.ESTIMATES["svg"]` 保持 0.03 | `docs/CLAUDE_INTEGRATION.md:407,416`、`docs/DEPLOY.md:326,434`、`deploy/env.example:83`、`backend/wd/ai/budget.py:273`（注释）；`docs/DESIGN.md:28,518,550` 与 `docs/ops.md:198` 由 S6 改（请求） |
| C2 迁移 0012 | §2.3 全文；`store.activate(..., prompt_version=None, model=None, text_free=False, eval_json=None)` INSERT 列清单追加四列（`store.py:76-120`）；`activate_candidate` 不传（照片 `text_free=0`） | `backend/wd/migrations/0012_word_images_meta.sql`、`backend/wd/images/store.py`、`backend/tests/unit/test_db_0012.py`（新：0001 基线插 2 行 `word_images` → `run_migrations` → 四列存在、`text_free` 默认 0、CHECK 拒 2、行数与 id 不变、二次运行空） |
| C3 SVG v2 | 系统提示词整体替换（§5.2 全文）；`svg.py`：`EXAMPLE_MAX=120`、`HOOK_MAX=60`、`HOOK_PREFIXES=("联想：","联想:")`、`SVG_PROMPT_VERSION="svg-v2"`、`STYLE_TEXT{kid,neutral}`、`build_user_prompt(display, meaning, concept, *, example="", hook="", style="neutral")`（保留 `for the word "…"` 片段，`tests/fake_claude.py:160-162` 依赖）、`hook_from(mnemonic)`、`prompt_for(conn, word, *, cfg)` 取 `examples[0].en` 与挂钩；`handle_generate_svg` `:115/:137` 传 `cfg`、`model=result.model_used`、`prompt_version`，`svg_repaired` 日志事件；`sanitize_svg.py`：`BARE_AMP_RE = r"&(?!(?:amp\|lt\|gt\|quot\|apos\|#\d+\|#x[0-9A-Fa-f]+);)"` 在 `DET.fromstring` 前替换、`clean(svg, *, allow_text=True)`、`_serialise(..., allow_text)` 丢 `text/tspan` 子树、`with_label(cleaned, label)` 插 `<desc id="aigc-label">`（`_clean_attrs` 丢弃模型自带的该 id）；`store.activate_svg(conn, cfg, word_id, svg, alt_zh, *, now=None, model=None, prompt_version=None)` = `clean(allow_text=False)` → `with_label(f"AI-generated illustration · word-Dance · {model or 'claude'} · {now[:10]}")` → `write_bytes` → `activate(provider="claude_svg", license="generated", text_free=True, …)`；新 `images/style.py`；`config.py` `image_kid_stages: tuple[str, ...] = ()` + `WD_IMAGE_KID_STAGES` 解析（函数级 `from .schemas import STAGE_ORDER`，未知码 `ConfigError`） | `backend/wd/ai/prompts/svg_system.txt`、`docs/CLAUDE_INTEGRATION.md:281-285,296-300,401-403`、`backend/wd/ai/svg.py`、`backend/wd/images/sanitize_svg.py`、`backend/wd/images/store.py`、`backend/wd/images/style.py`（新）、`backend/wd/config.py:155-168,355-369,522-534`、`deploy/env.example:149-165`（`WD_IMAGE_KID_STAGES=""`）、`docs/DEPLOY.md:339` 后一行 |
| C4 content v2 | `content_system.txt`：第 1 行受众 `(小学, 初中, 高中, CET-4, CET-6 and working professionals)`；规则 1 末尾追加小学白话释义句；规则 3 末尾追加小学（4–8 词、现在时、校园/家庭/操场、原形 ≥ 2 句）与初中（6–12 词、校园与日常、无职场/新闻语域）条款；规则 5 末尾追加「For 小学 words prefer a vivid picture-like association ("联想：…") over morphology.」；规则 6/7 整条替换（例句 1 同一场景、单一主体、无文字无人脸特写、抽象词对齐 `mnemonic_zh`、功能词给裸 lemma）；规则 8 `(1 = 小学/初中 basic, 2 = 高中, 3 = CET-4, 4 = CET-6, 5 = beyond CET-6)`；`content.py`：`:46 PROMPT_VERSION="content-v2"`、`:48 AUDIENCE="Chinese learners from primary school (小学) to CET-6, plus working professionals"`、`:49 STAGE_ZH = schemas.STAGE_NAMES_ZH`、`:54 EXAMPLE_EN_MIN=10`、`:67-69 _is_blocked(keyword, lemma)` = `is_blocked(keyword, allow=select.keyword_tokens(lemma))`、调用处 `:176`；`PREFIX_MIN` 不动；`content_v1.json` 不动；旧卡不 `force` | `backend/wd/ai/prompts/content_system.txt`、`backend/wd/ai/content.py`、`docs/CLAUDE_INTEGRATION.md:206,210-226,232,355`、`docs/AI_FALLBACK_MODEL.md:29`、`backend/tests/unit/test_content_apply.py:81`（`== content.PROMPT_VERSION`）；`docs/WORD_LIBRARY_CURATION.md:65,183`（`content-v1` → 「当前 `PROMPT_VERSION`（`content-v2`）」）由 S6 改（请求） |
| C5 搜索词 | `select.py`：`UNSAFE_RE`（`nude\|nudity\|sex\|porn\|gore\|blood\|weapon\|gun\|corpse`）、`NON_PHOTO_RE`（`map\|diagram\|logo\|flag\|coat of arms\|chart\|graph\|screenshot\|poster\|cover\|scan\|text\|document`，查询自身 token 豁免）、`KID_UNSAFE_RE`（`beer\|wine\|alcohol\|cigarette(s)\|smoking\|horror\|zombie(s)\|skull(s)\|knife\|knives\|bikini\|lingerie`，kid 硬拒）、`is_blocked(text, *, allow=frozenset(), style="neutral")`、`keyword_tokens(text) -> frozenset[str]`、`reject_reason(cand, exclude, *, allow, style)`、`rank(..., allow, style)`；删 `BLOCKLIST_RE`；`handler.py`：`clean_keywords(values, lemma, *, allow_lemma=True) -> (kept, dropped)`，`fetch_for_word` 的 SELECT（`:122`）加 `kind, pos, stage_min`，功能词门（`style.skip_image` 且无管理员 `provider`/`query` → `image_state='failed'`、`FetchOutcome(STATUS_SKIPPED, detail="function word: card only")`，不发请求、不入队 SVG），管理员 `query` 被形状/黑名单丢弃时 `query_ignored` 日志 + `detail` 前缀，API 仍 202；副词无可用关键词时不搜裸 lemma | `backend/wd/images/select.py`、`backend/wd/images/handler.py`、`backend/wd/ai/content.py`（`_is_blocked`）；`docs/DESIGN.md:525-547` 由 S6 改（请求） |
| C6 打分信号 | `score(cand, keyword, *, used_refs=(), style="neutral")` 加：description/object_name 命中 +1（封顶 1）、`extra.category`/`extra.type` 与本轮目标一致 +1 / 相反 −1（kid 目标 `illustration/vector`，neutral `photograph/photo`）、`PEOPLE_RE` 命中 kid −2 / neutral 0、`TEXTY_RE` −1、`aspect < 1.0` −1；`MIN_SCORE=1` 不变；`openverse.py` 解析 `extra["category"]` | `backend/wd/images/select.py:80-101`、`backend/wd/images/providers/openverse.py` |
| C7 夜间重试 | `service.py`：`RETRY_MIN_AGE_H=6`、`RETRY_MAX_AUTO_30D=3`、`RETRY_NIGHTLY_LIMIT=50`、`RETRY_NIGHTLY_PRIORITY=30`、`retry_due(conn, word, now)`、`retry_if_failed(conn, word, *, priority, now)`、`retry_failed_studied(conn, now, *, limit, priority, dry_run=False)`、`enqueue_fetch(..., retry=False)` 写 `payload["retry"]=True`；`images/__init__.py` 导出两函数；`scheduler.maintenance`（`:364-397`）在 `prefetch` 之后调用，`TickResult.image_retries`；CLI `wd images-retry [--limit N] [--dry-run]`（`handler.register_cli` + `cli.py:54` `COMMAND_OWNERS["wd.images.handler"]` 加 `images-retry`）。**不做** `bank.py:636,659` / `batches.py:352-362,639` 的即时挂点（R-16） | `backend/wd/images/service.py`、`backend/wd/images/__init__.py`、`backend/wd/jobs/scheduler.py:66-73,364-397,523`、`backend/wd/images/handler.py:349-361`、`backend/wd/cli.py:54`、`docs/DEPLOY.md:417`；`docs/ops.md:198,202` 由 S6 改（请求） |
| C8 provider 风格参数与插画轮（默认关） | `interfaces.ImageProvider.search(self, query, limit, *, style="neutral")`；Commons：neutral `filetype:bitmap`、kid `filetype:drawing`，`iiprop` 加 `thumbmime`，`maxlag=5`，`error.code=="maxlag"` → `ProviderError(status=503, retry_after_s=Retry-After or 30)`（新 `base.get_json_with_headers`），候选 `mime = thumbmime or mime`；Openverse：删 `PAGE_SIZE`，`page_size=max(1,min(limit,20))`（=10），kid 加 `category=illustration`；Pixabay：kid `image_type=illustration`；Pexels 签名透传、不进 kid 轮；**neutral 轮不加 `category=photograph`/`orientation`**；尺寸门槛 400×300 不放宽；`handler`：`rounds = ((kid, kid_names), (neutral, names))` 当 `style_=="kid"` 且无管理员 provider，否则单轮；`kid_names = tuple(p for p in cfg.image_providers if p != "pexels")`；`PREWARM_SKIP_PROVIDERS=("openverse","pixabay","pexels")` 于 `priority >= 90` 跳过 | `backend/wd/interfaces.py:73-79`、`backend/wd/images/providers/{base,wikimedia,openverse,pixabay,pexels}.py`、`backend/wd/images/handler.py:1-11,139-206`；`docs/DESIGN.md §9` 与根 `ATTRIBUTION.md §3.1/§3.2` 的参数描述由 S6 / S3 改（请求） |

`images/style.py`（S5 对外接口）：`STYLE_KID="kid"`, `STYLE_NEUTRAL="neutral"`, `STYLES`；`FUNCTION_POS = frozenset({"i","c","d","p","a","u","t"})`（与 `frontend/src/utils/pos.ts:8-21` 码表一致，无 `r`、无 `x`）；`NO_BARE_LEMMA_POS = FUNCTION_POS | {"r"}`；`dominant_pos("n:4/v:96") == "v"`（占比最大，平局取首个；`None`/`"v./n."` → `None`）；`skip_image(word)`；`allows_bare_lemma(word)`（未知 pos → True）；`stage_code(stage_min)`（int → `schemas.index_to_stage`，越界 → `None`，str 原样，`None` → `None`）；`style_for(word, cfg)` = `kid` iff `stage_code(word["stage_min"]) in cfg.image_kid_stages`。复算（`scratchpad/synth-images/pos_stats.py`）：`stage_min=1`（旧 zk 2,099）主词性 n 1,043 / v 361 / j 301 / r 105 / 无 100 / m 50 / i 40 / p 40 / d 22 / c 19 / a 11 / u 6 / t 1，门不含副词覆盖 138 词；二级 505 词在库 498，门覆盖 65。

### 5.2 `svg_system.txt` v2 全文（`CLAUDE_INTEGRATION.md §5.5` 代码块逐字节同步；首字符必须是字母，`test_schemas.py:127`）

```
Produce a simple, flat-style educational illustration as a single SVG string for the given English word, so that a learner who sees the picture alone can recall the word's meaning. The picture is a memory cue, not a caption: it must contain NO text of any kind — no letters, digits, words, labels, signs, speech bubbles or captions — and must not spell or hint at the word typographically.
Composition: exactly ONE clearly recognisable central subject (or one simple interaction between two subjects when the Scene says so) on a plain, light, single-colour background; no decorative clutter, borders, frames or patterns; 3–5 harmonious flat colours and large simple shapes; the subject fills at least half of the canvas. Draw the Scene given in the user prompt — the sense used in the example sentence — never a different sense of the word. For an abstract word draw the concrete Memory hook given in the user prompt, not a symbolic diagram. Simple stylised figures are fine, but do not draw human faces in detail. Nothing frightening, violent, romantic or sexual.
Follow the Style line of the user prompt and vary the composition from picture to picture.
Technical constraints: viewBox="0 0 800 500"; use only these elements: svg g rect circle ellipse line polyline polygon path defs linearGradient radialGradient stop title desc; no <text>, no <tspan>, no <script>, no <foreignObject>, no <image>, no <use>, no external references (href, xlink:href, url(...)), no event attributes, no CSS; the SVG must be well-formed XML — write & as &amp; and never put a bare < or & inside attribute values, <title> or <desc>; total length at most 8000 characters. Return {svg, alt_zh} where alt_zh is one Chinese sentence (at most 40 characters) describing what the picture shows.
```

用户提示词形状：`Draw an illustration for the word "{display}" ({meaning}). Scene: {concept}。 Example sentence: "{example}" Memory hook: {hook} Style: {STYLE_TEXT[style]}`（空的 example/hook 段省略）。`STYLE_TEXT["kid"]` = child-friendly picture-book style for 6–11-year-olds（bright warm colours, rounded shapes, friendly simple characters, everyday school / home / playground scenes familiar to a child in China）；`["neutral"]` = clean flat educational illustration for teenagers and adults（calm colours, clear geometry, realistic proportions）。

### 5.3 第一期行为变化与验收（线上）

默认链请求形状只多 `thumbmime`/`maxlag=5`/`page_size=10`；新生成的 SVG 0 个 `<text`、恰 1 个 `aigc-label`、行 `prompt_version='svg-v2'`、`text_free=1`、`model` 非空；功能词（`of`、`despite`…）不再发 provider 请求、直接模板卡；第一次 03:30 维护后 18 个 failed 词中在学的 ≤ 17 个被重排（`payload.retry=true`），48 h 内 `failed` ≤ 3；`WD_IMAGE_KID_STAGES` 未设时无 kid 轮；拒收率预期接近 0（连续 20 次 `generate_svg` 拒收 ≤ 1）。配置：`WD_IMAGE_KID_STAGES=""`（DEPLOY §4 行：「stage codes whose words get the child style and the illustration-first round (empty = off; set to `xs` after the pilot; `zk` is never in the default)」）。

### 5.4 第二期（试点；需智谱 BigModel key + 进程环境无 `HTTP(S)_PROXY` 的机器；不进生产、不进契约、无迁移）

- 合入但默认不在链中：`backend/wd/images/providers/ai_image.py`（`AiImageProvider.generate(prompt, *, user_ref) -> Generated{url,b64,content_filter_max,model,raw_status}`，智谱 `POST {base}/images/generations`，`size="1344x768"`、`n=1`、`watermark_enabled=True`；**不**实现 `search`、不注册到 `PROVIDER_CLASSES`、不读 `Settings`）、`backend/wd/images/gen_prompt.py`（kid/neutral 中文提示词模板，≤ 300 字）、`backend/tests/fake_image_gen.py` + `test_ai_image_provider.py`。
- `scripts/image_pilot.py`（子命令 `sample / content / arm A|B|C|D / sheet / report`）+ `scripts/image_pilot_thresholds.json`（预注册门槛，试点前提交）+ `image_pilot_rubric.csv`：样本框 = `data/lists/moe-2022-level2.txt` ∩ 库（498）去功能词（65）→ 433，按主词性分层 n 110 / v 50 / j 20 / r 20 = 200，每层按 `frq` 升序等距；四臂 A 照片链（kid + neutral 轮）/ B SVG v2 / C CogView-3-Flash / D 模板卡零点，每臂一份 `VACUUM INTO` 私有拷贝；评分页隐藏词头、先猜后翻；两名评分者 κ ≥ 0.6；R1–R5 各 0–2；5–8 名上海三至五年级小学生看图说义 + 24 h 图→词回忆（监护人同意）；可选 GLM-4.6V-Flash 自动评分写 `eval_json`（先在 60 张子集上与人工一致率 ≥ 80%）。成本 ≈ $3.3 + ≈ 5.5 人日。
- 预注册门槛（决定第三期）：① B 或 A-kid 在 xs 词上通过率 ≥ 70% 且每通过图 ≤ $0.02 → `WD_IMAGE_KID_STAGES` 默认 `xs`；② A-kid 通过率 ≥ 60% 才保留照片 kid 轮；③ C ≥ B + 10 pp ∧ R3 ≥ 90% ∧ `content_filter` 拒绝 ≤ 5% ∧ 智谱 URL 过 SSRF 规则 → `ai_image` 进 KID 链首位，|C−B| < 10 → 链尾，C < B − 10 → 不接入；④ 副词层 < 50% → `r` 加入 `FUNCTION_POS`；⑤ Openverse kid 轮因尺寸拒绝且 ≥ 300×200 占 ≥ 30% → `MIN_SIZE_KID`；⑥ 儿童小样本某臂 24 h 回忆低于最佳臂 ≥ 10 pp → 该臂不用于 xs。
- 第三期（条件合入，另行排期）：`ai_image` 进有序链（`WD_IMAGE_PROVIDERS_KID`）、7 个 `WD_IMAGE_GEN_*`、迁移 **0014**（`word_images.provider` CHECK 加 `ai_image`，重建）、一次契约提交（`ImageProviderName` 提成 `export type` + `ai_image`、`AdminOverviewWords.with_ai_image`、`RefetchProvider`）、JPEG XMP/COM 隐式标识、`WD_IMAGE_KID_STAGES` 默认 `("xs",)`。

---

## 6 实现切片计划（给多 agent 实现工作流）

规则：① 文件归属**全局两两不相交**（下表 `files` 列即归属；`backend/tests/unit/test_db.py` 归 S1，S2/S5 的迁移测试用新文件 `test_db_0013.py`/`test_db_0012.py`）；② 其他切片对非己文件只读，需要的改动写成「请求」并在本节列出，归属切片按本文规格实现；③ `depends_on` 表示「从该切片合入后的 main 分支出发」；S2/S3/S4/S5 彼此并行，S6 在 S2 之后，S7 最后；④ 每个切片的验收命令只覆盖自己的节点，全量门禁（§7）在 S7 执行；⑤ 已交付的 `data/lists/` 11 个文件只读（S3 只新增文件）；⑥ 任何切片不得读写 `/Users/sqin/word-dance-data`，排练只用 `scratchpad/live-copy.db` 的私有拷贝。

### S1 `stage-schema-0011` — 阶段枚举 4→5 的唯一真相 + 迁移 0011（0.5 人日）

- 目标：`schemas.py` 五阶段/重编号/显式字典；`0011_primary_stage.sql`（§2.2 全文，注释令牌示例改为 `moe22:l2 …`）；`test_db.py` 新增 `test_upgrade_0011_renumbers_stages_and_rebuilds_two_tables`（仿 `:283-310`：0001 基线建库，插 `users`×2、`user_settings`（`current_stage` 1/3，`stages_json` `'["zk"]'`/`'["zk","gk","cet4","cet6"]'`）、`words`（`stage_min` 1..4 各一行 + NULL 一行 + `merged_into_word_id` 自引用）、`user_words`/`push_items`/`word_contents`/`word_images`/`content_reports`/`bank_suggestions` 各一行、`kv.seed_version` → `run_migrations()` → `(11,'primary_stage')` 已应用；`current_stage` 2/4、`stages_json` 原样；`stage_min` 2..5 且 NULL 保持；`stage_xs` 全 0；子表行数不变；`foreign_key_check` 空；`view_names == ["v_bank"]` 可查；新插设置行默认 `('["xs","zk"]', 1)`；`stage_min 0/6`、`current_stage 0/6` 抛 `IntegrityError`；`kv.seed_version` 不存在；`system_events` 末行 `kind='migration'`；二次运行 `applied == []`；`EXPECTED_TABLES` 不变）；`test_api_schemas.py:32-39` 改五阶段并加 `all(STAGE_INDEX[s] == STAGE_ORDER.index(s) + 1 for s in STAGE_ORDER)`、`index_to_stage(6)` 抛、`VocabQuery/ScreenNextQuery/PrewarmRequest(stage="xs")` 合法、`"xx"` 非法。
- files：`backend/wd/migrations/0011_primary_stage.sql`、`backend/wd/schemas.py`、`backend/tests/unit/test_api_schemas.py`、`backend/tests/unit/test_db.py`
- depends_on：—
- 验收：`.venv/bin/python -m pytest -q backend/tests/unit/test_api_schemas.py backend/tests/unit/test_db.py`；`W=$SCRATCH/s1-rehearsal && mkdir -p $W && .venv/bin/python -I $SCRATCH/synthesis-stage-model/rehearse.py $W $SCRATCH/live-copy.db backend/wd/migrations/0011_primary_stage.sql`（期望与 §2.2 排练结果逐项相同）。
- 文档章节：无（`DESIGN.md §0.3/§3.1/§6.1` 由 S6 改；`API.md §9/§9.1` 由 S4 改）。
- 已知状态：合入后 `make test` 在 S2/S4 合入前为红（`seed.py:43` 仍四阶段、`types.ts` 未改）——属预期。

### S2 `backend-runtime-importer` — 后端运行时常量去副本、默认值、导入器 v2、0013（4 人日）

- 目标：§3.6 的后端副本全部改为从 `schemas` 读；`services/words.py`（`:39`、`:564-586 _word_defaults` + `:589-597 _INSERT_WORD_SQL` 由 `STAGE_ORDER` 生成五旗标、`:40-50` `FORM_KINDS`/`FORM_KIND_ZH` 加 `alias`）；`services/ecdict.py`（§3.6）；`services/bank.py`（`:85-86` 默认、`:181` 过滤后为空 → `log.warning(event="stage_fallback", user_id=…)` 再回落；新增 `current_stage_index(settings_row) -> int`：`None` → `DEFAULT_CURRENT_STAGE` 否则 `int`）；`services/screen.py:44`、`services/batches.py:272,698` 改用 `bank.current_stage_index`；`routers/vocab.py:78` COALESCE；`ai/prewarm.py:32-33`；`security.py:612-614` docstring 示例 `'["xs","zk"]'`；`seed.py` §4.7 全部 + `main.seed_check` 全文；`0013_word_forms_alias.sql`（§2.4）；`scripts/smoke.py:352,614`、`scripts/eval_provider.py:107` 五阶段。
- 夹具 `backend/tests/fixtures/mini_seed.jsonl`（60 → 62 条，v2 键；**最小改动原则**，不按新种子重标 gk）：全部记录加 `"lemma"`、`"seed_v": 2`；`sources` 按 §4.4 重写（`zk→legacy:zk`、`gk→legacy:gk`，官方令牌只给二级词 `moe22:l2 moe22:l3`，上海词头加 `shmeea20`，高中表词头加 `hs20:<level> hs25:<level>`——以夹具里存在的词为准）；给 `a, apple, be, book, cat, child, China, clothes, computer, dog, email, glass, good, happy, house, ice cream, run, some, study, take, teacher, TV, water` 的 `stages` 首位加 `"xs"`（夹具里不存在的词跳过）；**不给 `go` 加 `xs`**（`test_content_apply.py:254-255` 在 S5 合入前会 `KeyError`，R-12）；**不给 `an` 加**（保住 `test_screen.py:129-136` 的 zk 池）；`is` 加 `"xs"` 与令牌 `inherit:be`；`TV` 加 `"aliases": ["t.v."]`；新增第 61 条 `color`（`stages ["xs","zk","gk","cet4"]`、`variant_of "colour"`、`exchange {"s": "colors"}`）与第 62 条 `bookshelf`（`stages []`，`sources ["ecdict","legacy:gk"]`）。新目录 `backend/tests/fixtures/seed_v2/`：`unknown_code.jsonl`（`stages ["xs","cet9"]`）、`bad.jsonl.gz`（截断的 gzip）。
- 测试：`test_seed.py`（`:61-73` 60→62；`:93-97` 用 `stage_to_index("gk")` 等写期望而非字面量；`:98` 无阶段 == 1；`:113/117` 新令牌串；`:136` `NOT IN (…, 'alias')` 且断言 `('t.v.', <TV id>, 'alias')` 存在；`:229-238` 内容哈希使 gz 与 plain 的 `content_sha256` 相同、第二次 `up_to_date`；`:291-298` 六元组；`:338-353 @full_seed` 改为读 `data/seed/stats.json` 的 `total_words/per_stage/first_stage/per_kind` 比对 + 不变量 SQL（§7.3），`:352` 加 `'alias'`；新增 `test_dry_run_writes_nothing`、`test_dry_run_reports_orphans_flag_changes_and_matrix`、`test_unknown_stage_code_is_counted_not_dropped_silently`、`test_alias_rows_written_with_headword_guard`、`test_content_digest_up_to_date_across_gz_and_plain`、`test_lemma_mismatch_counted`、`test_stage_xs_record_gets_stage_min_1`、`test_empty_stages_gives_null_stage_min`）；新 `test_bank_defaults.py`（`pragma_table_info('user_settings').dflt_value` ↔ `bank.DEFAULT_*` ↔ `stage_to_index("xs")`；`user_settings_row` 对 `'["cet9"]'` 回落默认并写 `stage_fallback`）；新 `test_main_seed_check.py`（坏 gzip / monkeypatch 抛异常 → 返回、`system_events('seed_import_failed')` 一行、`kv.seed_version` 不变；正常路径不写事件）；新 `test_db_0013.py`（带 `alt` 行的 v11 库升到 v13：`alt` 保留、可插 `alias`、`bogus` 被拒、`EXPECTED_TABLES` 不变）；`test_words_resolve.py`（`:279,346,478` 索引 +1；ECDICT `tag="zk"` → 无旗标、`stage_min None` 但 `has_stage_tag` 真；`tag="cet4"` → `stage_min == stage_to_index("cet4")`；`word_columns()["stage_xs"] == 0`；`resolve("t.v.")` 命中别名行 `via == "form"`、`lemma_note` 含「另一种写法」）；`test_vocab.py:65-79,107-114,150-161`（5 行 `[1..5]`、第一行 `xs`、`items[4]` 是 cet6、`== 5`、`keys` lambda `(d + 1 if d else stage_min or 6, …)`、`stage=xs&new_only=1` 总数 == `stage_min=1` 数）；`test_onboarding.py:98,120,139`（`1 / '["xs","zk"]'`、4、2）；`test_settings.py:57-58,88-89,109-112`；`test_security.py:315`、`test_auth.py:82`；`test_screen.py:116,129-136`（夹具 `current_stage` +1；期望按新夹具重算；新增主攻 `xs` 的 `auto` 距离 xs 0 / zk 1 / gk 3）；`test_batches.py:120-130`（`current_stage` +1）；`test_reports.py:29,87`（`stage_min` 2→3）；`test_history.py:112`（加 `xs`）；`test_admin_ops.py`（`prewarm {"stage":"xs"}` 202）。
- files：`backend/wd/seed.py`、`backend/wd/main.py`、`backend/wd/services/words.py`、`backend/wd/services/ecdict.py`、`backend/wd/services/bank.py`、`backend/wd/routers/vocab.py`、`backend/wd/services/screen.py`、`backend/wd/services/batches.py`、`backend/wd/ai/prewarm.py`、`backend/wd/security.py`、`backend/wd/migrations/0013_word_forms_alias.sql`、`scripts/smoke.py`、`scripts/eval_provider.py`、`backend/tests/fixtures/mini_seed.jsonl`、`backend/tests/fixtures/seed_v2/`（新目录）、`backend/tests/unit/test_seed.py`、`backend/tests/unit/test_bank_defaults.py`、`backend/tests/unit/test_main_seed_check.py`、`backend/tests/unit/test_db_0013.py`、`backend/tests/unit/test_words_resolve.py`、`backend/tests/integration/test_vocab.py`、`backend/tests/integration/test_onboarding.py`、`backend/tests/integration/test_settings.py`、`backend/tests/unit/test_security.py`、`backend/tests/integration/test_auth.py`、`backend/tests/integration/test_screen.py`、`backend/tests/unit/test_batches.py`、`backend/tests/integration/test_reports.py`、`backend/tests/integration/test_history.py`、`backend/tests/integration/test_admin_ops.py`
- depends_on：S1
- 验收：`.venv/bin/python -m pytest -q backend/tests -k "not test_deploy_files and not test_defaults_without_environment"`（S2 合入点上整套后端应绿：S5 未合入时 `test_content_apply` 仍绿，因夹具未给 `go` 加 `xs`）；`make smoke`。
- 请求：→ S5：`content.py:49 STAGE_ZH = schemas.STAGE_NAMES_ZH`（否则 xs 词 `prompt_entry` KeyError）；`docs/DEPLOY.md:417` CLI 行改 `import-seed [--file PATH] [--force] [--dry-run] [--report PATH]`，`:304` `WD_SEED_PATH` 行「the file's sha256」→「the content sha256 of the (gunzipped) file」，§5 `wd migrate` 段加「0011/0013 是 stop-first 重建」。→ S4：`API.md:169` 排序表达式文字（§3.3）。→ S6：`DESIGN.md:172,184`（种子版本 = 内容 sha256、kv 清单）、`§3.1`（`word_forms` 段加 `'alias'`）、`§6.1/6.2` 默认与预设、`TASKS.md:160-182`（验收脚本读 `stats.json`；`:162` 删「keep verbatim」；`:165` 内容哈希；加 `--dry-run`）、`WORD_LIBRARY_CURATION.md §1.2`（种子从不删词；`seed_check` 已防御；阶段来源 = `data/lists`）。

### S3 `seedbuild-lists-seed` — 构建器包、词表元数据、新种子与差异报告（8 人日）

- 目标：§4.1–4.6、§4.8 全部：`backend/wd/seedbuild/{__init__,normalise,build,diff}.py`；`scripts/build_seed.py` 全文替换为入口、`scripts/seed_diff.py` 新入口、`scripts/pack_seed.sh` BSD 可移植 + `content_sha256` 校验、`Makefile:37-40,93-98`（`seed` 目标三步；`ECDICT_DB`/`WORDLISTS_DIR` 可选）；`data/lists/{README.md, manifest.json, aliases.tsv, overrides.tsv, SHA256SUMS}` 新建；用 `scratchpad/ecdict-dl/extract/stardict.db` 跑 `make seed` 产出 `data/seed/{vocab.jsonl.gz, stats.json, ATTRIBUTION.md, DIFF.md}`；根 `ATTRIBUTION.md:14,19-32`（§4.6）并加 S5 请求的配图句子（§3.1/§3.2 参数描述：`filetype:drawing`、`category=illustration`、`maxlag`、`thumbmime`；`:56`「AI 生成示意图」条补「图内不含文字；SVG 文件内含 `<desc id="aigc-label">` 生成标识」）。
- 测试（新文件）：`test_seedbuild_normalise.py`（R1–R12 每条 ≥ 3 例，样例取自交付文件；含 `split_head("a (an)")` → heads `[a]` variants `[(an, a)]`、`split_head("manner(s)")`、`split_head("be (am, is, are)")` dropped 3、`split_head("according (to)")`、UNESCO 单项、`strict_ok(66 字符全称) is False`、`phrase_candidates("a bit (of)") == {"a bit","a bit of"}`、`phrase_candidates("at first/last")`、`canon("Mr", aliases) == "mr."`、`fold("café") == "cafe"`、`lemma_of(h) == words.normalise_lemma(fold(h))` 对夹具全量成立、`break down` 不匹配 `breakdown`）；`test_seedbuild_build.py`（`tests/fixtures/lists/`：迷你 manifest + 6 个小列表 + `mini_stardict.sql`（≈ 60 行，含 `Mr`/`Mr.`/`hot dog`/`hotdog`/`hot-dog`/`excited`/`the Bund`/`humourous`）+ `previous_seed.jsonl`：(a) 两次构建字节相同且 `content_sha256` 一致；(b) `xs ⊆ zk` 与 retain 断言（删一个旧 lemma → exit 2）；(c) 主表缺失 → exit 2 列出，附表缺失 → 警告 + `skipped`；(d) 旧 lemma 词典字段逐字等于 previous；(e) `inherit_stages` 只影响 previous 已有 lemma；(f) overrides `translation/word/drop` 生效；(g) `[网络] ` 前缀去掉并计数；(h) 外部 CET 目录缺席 → `external_lists == "absent"`、现有行 CET 旗标不变；(i) 产物每条记录的 `stages ⊆ schemas.STAGE_ORDER` 且 `lemma == words.normalise_lemma(word)`（导入往返在 S7 做））；`test_seed_diff.py`（v1 vs v2 夹具的矩阵、新增、消失 → exit 1、`xs ⊆ zk` 失败 → exit 1；md/json 渲染稳定）。
- files：`backend/wd/seedbuild/__init__.py`、`backend/wd/seedbuild/normalise.py`、`backend/wd/seedbuild/build.py`、`backend/wd/seedbuild/diff.py`、`scripts/build_seed.py`、`scripts/seed_diff.py`、`scripts/pack_seed.sh`、`Makefile`、`data/lists/README.md`、`data/lists/manifest.json`、`data/lists/aliases.tsv`、`data/lists/overrides.tsv`、`data/lists/SHA256SUMS`、`data/seed/vocab.jsonl.gz`、`data/seed/stats.json`、`data/seed/ATTRIBUTION.md`、`data/seed/DIFF.md`、`ATTRIBUTION.md`、`backend/tests/unit/test_seedbuild_normalise.py`、`backend/tests/unit/test_seedbuild_build.py`、`backend/tests/unit/test_seed_diff.py`、`backend/tests/fixtures/lists/`（新目录）
- depends_on：S1（`schemas.STAGE_ORDER` 含 `xs`）
- 验收：`.venv/bin/python -m pytest -q backend/tests/unit/test_seedbuild_normalise.py backend/tests/unit/test_seedbuild_build.py backend/tests/unit/test_seed_diff.py`；`make seed ECDICT_DB=$SCRATCH/ecdict-dl/extract/stardict.db` 连跑两次后 `python3 -I -c 'import json;print(json.load(open("data/seed/stats.json"))["content_sha256"])'` 相同；`scripts/pack_seed.sh --check`；`.venv/bin/python -I scripts/seed_diff.py <(git show HEAD:data/seed/vocab.jsonl.gz) data/seed/vocab.jsonl.gz --md /dev/stdout | head -80` 不变量全部 PASS、矩阵与 §4.8 相差 ≤ 1%；`git diff --stat data/lists/` 只有新增文件。
- 请求：→ S6：`DESIGN.md §3.2`（记录 v2 键、`stage_min = min(stage_to_index)`、令牌表 §4.4、`:209` 验收数字改为引用 `stats.json`）、`README.md:5,9,78,103`（五阶段文字 + 「记录数见 `data/seed/stats.json`」）、`TASKS.md:162`。→ S5：`DEPLOY.md:410`（`make seed` 新参数）。

### S4 `frontend-k12-stages` — 前端五阶段、角色、页签、`only` 芯片、课标外、契约文档（1.5 人日）

- 目标（= SM §3.6 全部）：`types.ts:5-6,37,45`；`StageChips.tsx`（`:7-9` 三常量五阶段；props 加 `only?: readonly Stage[]`；`stages.length === 0` 渲染 `<li className="chip chip--stage chip--outside">{zh.stages.outside}</li>`；`ordered = STAGE_ORDER.filter(s => stages.includes(s) && (!only || only.includes(s) || (stageMin !== null && STAGE_INDEX[s] === stageMin)))`）；`WordHeader.tsx`（`:19` props 加 `onlyStages?`；`:33` `hasMeta` 的 `(showStages && word.stages.length > 0)` 改为 `showStages`；`:50` 传 `only={onlyStages}`）；`StudyCard.tsx`（props 加 `onlyStages?`，`:172/:207/:298` 透传）；`WordRow.tsx`（props 加 `onlyStages?`，`:97` 传）；`StudyPage.tsx:625,686`、`ScreenRunPage.tsx`（渲染 `StudyCard` 处）传 `onlyStages={settings?.stages}`；`VocabPage.tsx:282`、`BankPage.tsx:354` 的 `WordRow` 传 `onlyStages={settings?.stages}`（`BankPage` 从 `useAuth()` 取 `settings`）；`WordDetailPage.tsx:360`、`WelcomePage.tsx:323` 不传；`zh.ts:25,28-29,86`（§3.4）；`WelcomePage.tsx`（`:30` `Role` 加 `'xs'`；`:33-38` `xs: {stages:['xs'], current:'xs'}`、`zk: {stages:['xs','zk'], current:'zk'}`，gk/uni/pro 不变；`:40` `ROLES = ['xs','zk','gk','uni','pro']`；`:42` `STAGE_FULL` 加 `xs`；`:72-73` 兜底改 `DEFAULT_PRESET = { stages: ['xs','zk'] as Stage[], current: 'xs' as Stage }  // mirrors user_settings DDL / bank.DEFAULT_*`）；`VocabPage.tsx`（`:29` 六页签；`:202` `tab === 'cet6' ? newOnlyCet6 : tab === 'zk' ? newOnlyZk : newOnly`；`:232` `tab !== 'all' && tab !== STAGE_ORDER[0] && <Switch …/>`）；`ScreenPage.tsx:20` 加 `xs`；`AdminPage.tsx:36` `[...STAGE_ORDER, 'all']`；`ui.css:453-455` 后加 `@media (max-width: 479.98px) { .tabs--fill .tab { padding-inline: var(--space-2); } }`；`word.css` 加 `.chip--outside { border-style: dashed; }`；12 处 `stage_min: <n>` 夹具 +1；`docs/API.md`（§3.3）、`docs/FRONTEND.md`（§3.4）、`docs/qa-frontend.md:36,42`。
- 测试：新 `StageChips.test.tsx`（5 chip 顺序；新索引高亮；`only=['xs']` 时四旗标小学词只渲染「小学」且最低阶段始终保留；`stages=[]` 渲染「课标外」）；新 `ScreenPage.test.tsx`（5 张卡；`items.length === STAGE_ORDER.length`）；`WelcomePage.test.tsx`（每个预设 `current ∈ stages`、`ROLES.length === 5`、兜底 `DEFAULT_PRESET`）；`VocabPage.test.tsx`（`TABS.length === STAGE_ORDER.length + 1`、`tab === 'xs'` 不渲染开关、`tab === 'zk'` 文案）；`zh.test.ts:56` `Record<Stage,string>` 自动；含 chips 断言的既有测试按新行为更新。
- files：`frontend/src/api/types.ts`、`frontend/src/api/endpoints.ts`、`frontend/src/components/word/StageChips.tsx`、`frontend/src/components/word/WordHeader.tsx`、`frontend/src/components/word/word.css`、`frontend/src/components/list/WordRow.tsx`、`frontend/src/components/study/StudyCard.tsx`、`frontend/src/components/ui/ui.css`、`frontend/src/pages/WelcomePage.tsx`、`frontend/src/pages/VocabPage.tsx`、`frontend/src/pages/ScreenPage.tsx`、`frontend/src/pages/AdminPage.tsx`、`frontend/src/pages/StudyPage.tsx`、`frontend/src/pages/ScreenRunPage.tsx`、`frontend/src/pages/BankPage.tsx`、`frontend/src/i18n/zh.ts`、`frontend/src/components/word/StageChips.test.tsx`、`frontend/src/pages/ScreenPage.test.tsx`、`frontend/src/i18n/zh.test.ts`、`frontend/src/pages/WelcomePage.test.tsx`、`frontend/src/pages/VocabPage.test.tsx`、`frontend/src/components/bank/AddWordPreviewRow.test.tsx`、`frontend/src/components/list/WordRow.test.tsx`、`frontend/src/components/study/StudyCard.test.tsx`、`frontend/src/components/word/SpeakButton.test.tsx`、`frontend/src/pages/BankPage.test.tsx`、`frontend/src/pages/ScreenRunPage.test.tsx`、`frontend/src/pages/StudyPage.test.tsx`、`frontend/src/pages/WordDetailPage.test.tsx`、`frontend/src/study/queue.test.ts`、`docs/API.md`、`docs/FRONTEND.md`、`docs/qa-frontend.md`
- depends_on：S1（使 `check_contract` 在本切片验收即可通过）
- 验收：`cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run typecheck && npm test && npm run lint && npm run build`；`.venv/bin/python scripts/check_contract.py`（输出含 `contract OK`）。
- 请求：无（`DESIGN.md:32,40,72,330`、`README.md` 的页签/角色文字由 S6 改）。

### S5 `images-phase1-content-v2` — 配图第一期 + AI 提示词 v2 + 0012（7 人日）

- 目标：§5.1 C1–C8（C7 不含即时挂点）+ R-12 的 content/prompt 归并 + R-13 的 `DEPLOY.md`/`env.example`（含 S2/S3 的请求行）。提交顺序固定 C1 → C8。
- 测试（按 IM §5.1/§5.2）：`test_sanitize_svg.py`（裸 `&` 修复、`&nbsp;` 不再拒收、`allow_text=False` 丢 text/tspan 保留 title/desc、`with_label` 恰一个 id、实体仍拒）；新 `test_style.py`（`dominant_pos`、`skip_image`、`allows_bare_lemma`、`stage_code(1) == "xs"`、`stage_code(99) is None`、`style_for`）；`test_config.py`（`WD_IMAGE_KID_STAGES` `""`/`"zk, gk"`/`"xx"` → `ConfigError`；`entries()`；`:25-39 test_defaults` 加 `cfg.image_kid_stages == ()`）；`test_select.py`（查询 token 豁免、kid 硬拒、五个新信号各一条、`test_score_table` 不变；`is_blocked` 调用处改关键字参数）；`test_providers.py:46-68,172-190`（`iiprop` 加 `thumbmime`、`maxlag`；`page_size` 10；`maxlag` 体 → 503；kid 轮 `drawing` + `thumbmime` 候选 MIME；Openverse `category`；Pixabay `image_type`；`:2` 文档串）；`test_images.py`（`:162` `page_size "10"`；`:535-547` 夹具词改 `apple` + 新增 lemma token 豁免测试；`:608-623` → `"<text" not in stored`、含 `aigc-label`、`text_free == 1`；新增功能词门 / 管理员 query / 副词裸 lemma / kid 两轮 / 默认链形状 / `query_ignored` / 提示词快照 / 版本与 `text_free` 写入 / 6 h 重试 / 30 天 3 次封顶 / 夜间只重排在学词 / `images-retry --dry-run`）；`test_content_apply.py`（`:81 == content.PROMPT_VERSION`；12 字符例句保留、9 字符丢弃；词 `map` 的 `"world map"` 保留；新增 `prompt_entry` 对 `stage_xs=1` 手工行给出「小学」标签）；`test_scheduler.py`（`image_retries` 断言）；`test_cli.py`（`images-retry` 注册）；新 `test_db_0012.py`；`test_schemas.py::test_prompts_are_verbatim_from_section_5` 两个参数绿。
- files：`backend/wd/images/style.py`（新）、`backend/wd/images/sanitize_svg.py`、`backend/wd/images/store.py`、`backend/wd/images/select.py`、`backend/wd/images/handler.py`、`backend/wd/images/service.py`、`backend/wd/images/__init__.py`、`backend/wd/images/providers/base.py`、`backend/wd/images/providers/wikimedia.py`、`backend/wd/images/providers/openverse.py`、`backend/wd/images/providers/pixabay.py`、`backend/wd/images/providers/pexels.py`、`backend/wd/interfaces.py`、`backend/wd/config.py`、`backend/wd/ai/svg.py`、`backend/wd/ai/content.py`、`backend/wd/ai/budget.py`、`backend/wd/ai/prompts/content_system.txt`、`backend/wd/ai/prompts/svg_system.txt`、`backend/wd/jobs/scheduler.py`、`backend/wd/cli.py`、`backend/wd/migrations/0012_word_images_meta.sql`、`docs/CLAUDE_INTEGRATION.md`、`docs/AI_FALLBACK_MODEL.md`、`docs/DEPLOY.md`、`deploy/env.example`、`backend/tests/unit/test_sanitize_svg.py`、`backend/tests/unit/test_style.py`、`backend/tests/unit/test_select.py`、`backend/tests/unit/test_providers.py`、`backend/tests/unit/test_config.py`、`backend/tests/unit/test_cli.py`、`backend/tests/unit/test_content_apply.py`、`backend/tests/unit/test_scheduler.py`、`backend/tests/unit/test_db_0012.py`、`backend/tests/integration/test_images.py`
- depends_on：S1（`STAGE_ORDER` 含 `xs`、`index_to_stage` 1..5）
- 验收：`.venv/bin/python -m pytest -q backend/tests/unit/test_sanitize_svg.py backend/tests/unit/test_style.py backend/tests/unit/test_select.py backend/tests/unit/test_providers.py backend/tests/unit/test_config.py backend/tests/unit/test_cli.py backend/tests/unit/test_content_apply.py backend/tests/unit/test_scheduler.py backend/tests/unit/test_db_0012.py backend/tests/unit/test_schemas.py backend/tests/unit/test_docs_contract.py backend/tests/integration/test_images.py -k "not test_defaults_without_environment"`；排练（私有拷贝 `M`）：`WD_DATA_DIR=$M .venv/bin/wd migrate --dry-run`（列出 11 与 12）→ `wd migrate` → `sqlite3 -readonly $M/word-dance.db "PRAGMA table_info(word_images); SELECT COUNT(*), SUM(text_free), SUM(prompt_version IS NULL) FROM word_images;"`（27 列；`31|0|31`）→ `WD_DATA_DIR=$M WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 .venv/bin/wd images-retry --dry-run`（≤ 17 词，无功能词）→ `WD_DATA_DIR=$M WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 WD_AI_ENABLED=1 WD_CLAUDE_BIN=backend/tests/fake_claude.py .venv/bin/wd fetch-image have --provider claude_svg && … wd worker-once` → 最新 `word_images` 行 `claude_svg | svg-v2 | <model> | 1` 且文件 `grep -c "<text"` 为 0 → `wd fetch-image of --no-svg` → `skipped, function word: card only`。
- 请求：→ S6：`DESIGN.md:28,518,550`（成本数字）、`§9 :525-547`（伪代码加功能词门/两轮/重试；Selection 段三张表 + 豁免规则；参数描述）、`ops.md:198`（处置列加 `wd images-retry --dry-run`、成本）、`:202`（「预生成期间不要跑 prune；重试规则会让在学词重新抓图」）、`WORD_LIBRARY_CURATION.md:65,183`（`content-v1` → 当前 `PROMPT_VERSION`）。→ S3：根 `ATTRIBUTION.md` 的配图句子（见 S3）。→ S2（集成后小提交，R-16）：`bank.py:636,659`、`batches.py:352-362,639` 调 `images.retry_if_failed`。

### S6 `docs-ops-diag-runbook` — 诊断不变量、设计/运维文档、Mac 上线脚本（1.5 人日）

- 目标：`diag.check_db:52-73` 在 `version >= 11` 时追加不变量 `stage_min_consistent`（`SELECT COUNT(*) FROM words WHERE stage_min IS NOT (CASE WHEN stage_xs=1 THEN 1 WHEN stage_zk=1 THEN 2 WHEN stage_gk=1 THEN 3 WHEN stage_cet4=1 THEN 4 WHEN stage_cet6=1 THEN 5 END)`）、`xs_subset_zk`（`stage_xs=1 AND stage_zk=0`）、`stages_json_known`（`json_each` 的值 ∉ 五码；SQLite < 3.38 只报 `query failed`）、`seed_version_matches_file`（`kv.seed_version == seed.seed_digest(cfg.seed_path)`，文件不存在则跳过）——每条 `invariant <name>: ok | N violation(s)`，任一非零 `ok=False`；`scripts/rehearse_migration.py`（新；把 `scratchpad/synthesis-stage-model/rehearse.py` 移植为可在任意机器运行的脚本：参数 `<db 拷贝路径>`，用 `wd.db.run_migrations` 应用待办迁移，打印 §2.2 的全部核对项，0012/0013 的检查按 `schema_migrations` 是否含 12/13 条件执行，退出码 = 核对失败数）；`docs/DESIGN.md`（`:28,518,550` 成本；`:32,40` 五页签；`:72` §0.3 术语表 `小学 / 初中 / 高中 / 四级 / 六级`、`xs / zk / gk / cet4 / cet6 (stage index 1–5)`；`:172,184` 种子版本 = 内容 sha256；`:186` §3.1 旗标说明「cumulative on the national chain by construction (xs ⊆ zk), zk ⊄ gk by design; `stage_min` lowest; NULL = outside the official lists」+ `word_forms` 段加 `'alias'` + 「当前 schema = 0001+0008+0009+0010+0011+0012+0013」+ 目标模型与触发条件一段；`§3.2 :193-209` 记录 v2 键、令牌表、`:209` 引用 `stats.json`；`:321-322,330` 默认 `["xs","zk"]`/xs、预设 小学生 → xs · 初中生 → xs+zk；`§6.3` 注「0011 之前的 `push_batches.settings_json` 用旧索引」；`§9 :523-552` 伪代码加功能词门/两轮/重试、Selection 三张表与豁免、provider 参数与条款（Pixabay 禁批量、Openverse 配额、注册应用）、`WD_IMAGE_KID_STAGES`）；`docs/TASKS.md:160-182`（验收脚本读 `stats.json`、`:162` 删「keep verbatim」、`:165` 内容哈希、加 `--dry-run`）；`docs/ops.md:198,202`；`docs/WORD_LIBRARY_CURATION.md §1.2,:65,:183`；`docs/QUICK_DEPLOY_AND_MOBILE.md` Mac 段加「先备份、再停、再切、再起」与本文 §8 的链接；`README.md:3,5,9,78,103`（五阶段文字；记录数引用 `stats.json`）；新 `docs/releases/2026-11-k12-stages.md`（发布说明：阶段重编号、词集变化与「仅本阶段新增」数字、课标外词、用户 2 推荐顺序变化、`push_batches` 快照旧索引、`sources` 全量换名让 ≈ 4,357 行 `updated_at` 前移 → `/media/card/{id}.svg` LRU 键失效重渲染（无害）、回滚方式与「静默错位」说明、`zk ⊄ gk` 的 212 个反例、配图一期行为变化）。
- files：`backend/wd/diag.py`、`backend/tests/unit/test_diag.py`、`scripts/rehearse_migration.py`、`docs/DESIGN.md`、`docs/TASKS.md`、`docs/ops.md`、`docs/WORD_LIBRARY_CURATION.md`、`docs/QUICK_DEPLOY_AND_MOBILE.md`、`README.md`、`docs/releases/2026-11-k12-stages.md`
- depends_on：S1、S2（`seed.seed_digest` 与 `--dry-run` 口径）
- 验收：`.venv/bin/python -m pytest -q backend/tests/unit/test_diag.py backend/tests/unit/test_docs_contract.py`（`test_diag` 新增：人工制造一行 `stage_min` 不一致 → `1 violation(s)` 且 `ok=False`）；`M=$SCRATCH/s6-rehearsal && mkdir -p $M && cp $SCRATCH/live-copy.db $M/word-dance.db && .venv/bin/python -I scripts/rehearse_migration.py $M/word-dance.db`（退出 0）。
- 请求：无。

### S7 `integration-gate` — 合并后全量门禁、真实种子往返、排练与发布预检（1 人日）

- 目标：在 S2–S6 全部合入的 main 上执行 §7 全部命令；对 `scratchpad/live-copy.db` 私有拷贝跑 §2.5 排练 + `wd import-seed --dry-run`（期望 insert ≈ 455 / update ≈ 4,357 / orphans 0 / stageless ≈ 238 / 矩阵 §4.8 ±1%）+ `wd import-seed` + `full_seed` 硬门 + `wd check db` 四条不变量 ok + 两位用户学过的词落到无阶段的数量 = 0；`seedbuild` 产物导入后 `lemma_mismatch == 0`、`word_forms` 含 `alias` 行且 `JOIN words ON lemma = form` 为 0；375/360 px DevTools 复核六页签不横滚；写出 §8 预检清单的勾选结果。只允许修复性改动（每处写明属哪条规格），不引入新设计。
- files：（无独占文件）
- depends_on：S2、S3、S4、S5、S6
- 验收：§7.1–7.4 全部命令退出 0；`git status` 干净（`data/lists/`、`docs/analysis/` 已随切片入库）。

---

## 7 测试矩阵与门禁命令全文（Mac；`cd /Users/sqin/word-dance`；`SCRATCH=/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad`；Node 用 `PATH=/opt/homebrew/opt/node@22/bin:$PATH`）

### 7.1 每次合入必跑（= `make test` 展开 + Mac 已知失败排除）

```sh
.venv/bin/python -m pytest -q backend/tests -k "not test_deploy_files and not test_defaults_without_environment"   # Mac：19 个 install.sh/fetch_ecdict 干跑测试与 /home 解析测试按设计失败
.venv/bin/python scripts/check_contract.py                                                                       # schemas.py ↔ types.ts：Stage/StageIndex 联合逐值同序；输出 contract OK
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run typecheck && npm test && npm run lint && npm run build && cd ..   # tsc（Record<Stage> 5 处）· vitest（含 zh.test.ts / zh.contract.test.ts 的 FRONTEND.md §8 镜像）· check-copy.mjs · vite build
```

### 7.2 文档镜像与提示词字节绑定（§7.1 已覆盖，单独列出便于定位）

```sh
.venv/bin/python -m pytest -q backend/tests/unit/test_schemas.py        # ai/schemas/*.json ↔ CLAUDE_INTEGRATION §4 ↔ fixtures/claude_schemas.json；prompts/*.txt ↔ §5 代码块逐字节
.venv/bin/python -m pytest -q backend/tests/unit/test_docs_contract.py  # DEPLOY §4 ↔ Settings 字段双向；TASKS/DESIGN 签名；runbook 文案
.venv/bin/python -m pytest -q backend/tests/unit/test_db.py::test_schema_file_is_byte_identical_to_docs_copy_when_present   # docs/SCHEMA.sql == 0001_init.sql
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npx vitest run src/i18n && cd ..                                # zh.ts ↔ FRONTEND.md §8
```

### 7.3 种子重建、导入往返与全量验收（需要 `$SCRATCH/ecdict-dl/extract/stardict.db`；先 `shasum -a 256 $SCRATCH/ecdict-dl/ecdict-sqlite-28.zip` 核对 `ea01f76a…f3f6`）

```sh
make seed ECDICT_DB=$SCRATCH/ecdict-dl/extract/stardict.db           # build_seed → seed_diff(DIFF.md，不变量) → pack_seed.sh；两次运行 stats.json.content_sha256 相同
scripts/pack_seed.sh --check                                         # 记录数 == stats.total_words；gzip -dc | shasum -a 256 == content_sha256
M=$SCRATCH/integration-rehearsal; rm -rf $M; mkdir -p $M && cp $SCRATCH/live-copy.db $M/word-dance.db
export WD_DATA_DIR=$M
.venv/bin/wd migrate --dry-run                                       # 恰好 (11,'primary_stage') (12,'word_images_meta') (13,'word_forms_alias')
.venv/bin/wd migrate && ls $M/backups/pre-migrate-10-to-13.db.gz
.venv/bin/python -I scripts/rehearse_migration.py $M/word-dance.db  # 退出 0：逐行 +1、旗标和、difficulty+1、CHECK 探针、四列、alias CHECK、integrity/fk、二次运行空
.venv/bin/wd import-seed --dry-run --report $M/dry.json              # 期望 insert ≈455 / update ≈4,357 / unchanged ≈4,805 / orphans 0 / stageless ≈238 / flag_removed 非零（只报告）/ 矩阵 §4.8 ±1%
.venv/bin/wd import-seed                                             # 0.2–0.5 s；lemma_mismatch 0；unknown_stage_codes 0
.venv/bin/wd import-seed                                             # 第二次：seed up to date（内容哈希）
WD_FULL_SEED_DB=$M/word-dance.db .venv/bin/python -m pytest -q backend/tests -m full_seed   # 硬门：默认被 conftest 跳过，必须显式设变量
.venv/bin/wd check db                                                # invariant stage_min_consistent / xs_subset_zk / stages_json_known / seed_version_matches_file 全 ok
sqlite3 -readonly "file:$M/word-dance.db?immutable=1" "select sum(stage_xs),sum(stage_zk),sum(stage_gk),sum(stage_cet4),sum(stage_cet6) from words; select stage_min,count(*) from words group by 1; select kind,count(*) from words group by 1; select kind,count(*) from word_forms group by 1; select count(*) from word_forms wf join words w on w.lemma=wf.form and w.merged_into_word_id is null; select uw.user_id,count(*) from user_words uw join words w on w.id=uw.word_id where w.stage_min is null group by 1; select count(*) from words w, json_each('[\"' || replace(w.sources,' ','\",\"') || '\"]') j where w.sources is not null and j.value in ('zk','gk'); pragma integrity_check; pragma foreign_key_check;"
# 期望：旗标和 == stats.json.per_stage；stage_min 分布 == first_stage；kind 分布 == per_kind；word_forms 含 alias；词头守卫 0；无阶段持有 0 行；旧令牌 zk/gk 0；ok；空。`immutable=1`：wd 关闭连接后 -wal/-shm 不在，macOS sqlite3 3.51 对 WAL 库裸 -readonly 报 unable to open database file (14)（或先 touch 两个 sidecar；发布说明第 8 步）
unset WD_DATA_DIR
make smoke                                                           # 假 claude + mock providers 的端到端；smoke.py 期望 5 阶段
```

### 7.4 切片级节点（§6 各切片的验收命令已逐条列出；S7 在合并后再次全部执行）

| 切片 | 命令 |
|---|---|
| S1 | `pytest backend/tests/unit/test_api_schemas.py backend/tests/unit/test_db.py`；`rehearse.py` |
| S2 | 全量后端 pytest（排除 Mac 已知失败）；`make smoke` |
| S3 | `pytest backend/tests/unit/test_seedbuild_normalise.py test_seedbuild_build.py test_seed_diff.py`；`make seed` ×2 字节相同；`pack_seed.sh --check`；`seed_diff.py` 不变量 |
| S4 | `npm run typecheck && npm test && npm run lint && npm run build`；`check_contract.py` |
| S5 | §6 S5 的 pytest 节点；私有拷贝上 `migrate`/`images-retry --dry-run`/`fetch-image … --provider claude_svg`/`fetch-image of --no-svg` |
| S6 | `pytest backend/tests/unit/test_diag.py backend/tests/unit/test_docs_contract.py`；`rehearse_migration.py` 退出 0 |
| S7 | §7.1 + §7.2 + §7.3 全部 |

---

## 8 Mac 上线步骤与回滚（launchd；数据目录 `D=/Users/sqin/word-dance-data`；服务 `com.word-dance.server`，备份代理 `com.word-dance.backup`；所有 `wd` 命令需 `export WD_DATA_DIR=$D`；`wd serve` 启动即执行迁移，所以**先备份、再停、再切、再起**）

0. **预检**（不停机）：S7 的 §7 全部通过；S5 已合入（否则不得对 `xs` 预生成，管理页「小学」预生成项在发布说明标「待提示词更新」）；`shasum -a 256 $SCRATCH/ecdict-dl/ecdict-sqlite-28.zip` 对上；管理页任务列表没有在飞的 `claude` 调用；选无人学习的时段（回滚会丢失迁移后的学习记录）。
1. **构建前端快照**（不影响运行中的服务）：`SHA=$(git rev-parse --short HEAD)`（在新提交上）；`cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm ci && npm run build -- --outDir $D/frontend-releases/$SHA.new --emptyOutDir && cd ..`。
2. **手工全量备份**：`.venv/bin/wd backup --keep-daily 14 --keep-weekly 8 --with-images`，记下文件名。
3. **停服务**：`launchctl bootout gui/$(id -u)/com.word-dance.server`；`launchctl bootout gui/$(id -u)/com.word-dance.backup`（避免 03:30 的备份跑在死实例上）；`pgrep -fl "wd serve"` 为空；`curl --noproxy '*' http://127.0.0.1:8000/api/health` 应被拒。
4. **切代码**：`git checkout <新提交>`；`.venv/bin/pip install -e backend`（无新依赖，可跳过）。
5. **发布前端快照**：`mv $D/frontend-releases/$SHA.new $D/frontend-releases/$SHA && ln -sfn frontend-releases/$SHA $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"`（BSD `mv` 无 `-T`，不能直接 `mv` 到符号链接上）。
6. **迁移 ⚠ 不可逆（之后只能快照回滚）**：`.venv/bin/wd migrate --dry-run`（恰好 0011、0012、0013）→ `.venv/bin/wd migrate` → 输出三个 `applied`，`ls $D/backups/pre-migrate-10-to-13.db.gz`。
7. **导种子 ⚠ 不可逆（改写 ≈ 4,357 行、插入 ≈ 455 行）**：`.venv/bin/wd import-seed --dry-run --report $D/tmp/seed-dry.json`——与 §7.3 排练报告逐项一致才继续（insert/orphans 0/stageless/矩阵）；`.venv/bin/wd import-seed`（`kv.seed_version` 已被 0011 清空且内容哈希不同，不会 no-op；若报 `unknown_stage_codes` 非零 → 代码与种子不配套 → 第 11 步回滚）。
8. **只读验收**：`.venv/bin/wd check db`（四条不变量 ok）；`sqlite3 -readonly "file:$D/word-dance.db?immutable=1"` 跑 §7.3 的 SQL 块（服务停着、`wd` 刚关闭连接时 `-wal`/`-shm` 不在，macOS 自带 sqlite3 3.51 对 WAL 库裸 `-readonly` 报 `unable to open database file (14)`；`immutable=1` 或先 `touch $D/word-dance.db-wal $D/word-dance.db-shm` 都可）；`select user_id, stages_json, current_stage from user_settings` → `(1,'["zk","gk","cet4","cet6"]',4)`、`(2,'["zk"]',2)`。
9. **整理文件**（服务仍停）：`.venv/bin/python -c "import sqlite3; c=sqlite3.connect('$D/word-dance.db', isolation_level=None); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.execute('ANALYZE'); c.execute('VACUUM')"`（≈ 9.4 MB → ≈ 5.6 MB；`VACUUM` 不能在事务内）。
10. **起服务并验证**：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.backup.plist`；`curl --noproxy '*' http://127.0.0.1:8000/api/health`；日志 `~/Library/Logs/word-dance/word-dance.log` 无 `MigrationError`/`seed_import_failed`/`stage_fallback`，也无 `seed version changed; importing`（第 7 步已导入，内容哈希一致时 `seed_check` 静默返回——服务不打印 `seed up to date`，那是 CLI 的输出；核验用 `wd import-seed --dry-run` 的首行 `dry run: seed up to date`，或管理页 `seed_version` = `stats.json.content_sha256`）；登录后 `GET /api/stages` 5 行且 `total/new_only_total` == `stats.json`；`GET /api/vocab?stage=xs&new_only=1` 的 `total` == `first_stage.xs`；`GET /api/lookup?q=mr`（或搜索框输入 `Mr`）解析到 `Mr.`；设置页 5 个阶段 chip，sqin/kimi 主攻分别显示 四级 / 初中；词库 6 个页签在 375/360 px 不横滚；筛词页 5 张卡；管理页预生成下拉含「小学」；注册一个测试账号看欢迎页 5 个角色、默认勾选 小学 + 初中、主攻 小学（看完删除）；对一个在学的词 `.venv/bin/wd fetch-image <lemma> --provider claude_svg`（≈ $0.012）→ 文件无 `<text`、含 `aigc-label`、行 `prompt_version='svg-v2'`、`text_free=1`；次日查 18 个 failed 词的 `image_state` 与 `jobs` 里 `retry=true` 的结果。
11. **回滚**（仅在第 10 步失败时；**库与代码一起回**）：`launchctl bootout gui/$(id -u)/com.word-dance.server` → `.venv/bin/wd restore $D/backups/pre-migrate-10-to-13.db.gz --yes`（要求服务已停，`wal_checkpoint(TRUNCATE)`）→ `git checkout 75df534` → `ln -sfn frontend-releases/75df534 $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"`（快照 75df534 仍在 `frontend-releases/`）→ `launchctl bootstrap …` → `health`。没有「只回代码」的回滚（§2.5）；回滚丢失快照之后的学习记录。只想退种子（保留代码与迁移）：`git checkout 75df534 -- data/seed/vocab.jsonl.gz && .venv/bin/wd import-seed --force`——旧文件只改写它含有的 9,162 个 lemma（`stage_xs` 清零，`stage_min` 回到新索引 2..5，`legacy:*` 令牌换回旧令牌）；新种子新增的 456 行不在旧文件里，导入器从不删行也不改它们，它们**保留新种子的阶段**（`--dry-run` 列为 `orphans … kept`；排练实测 16 行仍 `stage_xs=1`）——要一并退掉用快照回滚，或按 `--dry-run --report` 的 `plan.orphans` 另行 UPDATE；`--dry-run` 会报告 `flag_removed`（xs 584），这是预期；此路径下随后恢复新种子也只是再 `import-seed`。

停机时长：迁移 < 0.1 s + 导种子 ≈ 0.5 s + `VACUUM` 数秒 + 启动 ≈ 1 分钟以内。Lighthouse（Linux/systemd）部署同一提交时：先在目标机用 `scripts/rehearse_migration.py` 对拷贝跑一次（SQLite ≥ 3.26 才能 RENAME；`json_each` 需 ≥ 3.38 仅影响 `wd check db`），然后 `deploy/install.sh`（它会停单元、迁移、`import-seed`、起单元；**不可**用 `--no-restart`）。

---

## 9 替产品负责人做的决定（反悔时影响哪些切片）与未决问题

### 9.1 假设清单（实现按「默认」先行）

| # | 我们替他们定了 | 默认 | 反悔的代价 / 受影响切片 |
|---|---|---|---|
| P1 | 2022 附表的数词（单 token）/月份/星期进「小学」 | 进（xs+zk） | S3：manifest `groups` 改 `stages`，重建；xs 从 ≈ 600 → ≈ 523 |
| P2 | 上海 342 个词组首版入库（303 条有 ECDICT 条目且过严格门 → 333 行，`kind='phrase'`，只在 zk） | 入 | S3：manifest `shmeea20:phr` 改 `policy: reference`，重建；zk 2,548 → ≈ 2,215；无代码改动 |
| P3 | 2025 修订 3100（非官方镜像、文号未见）作为高中依据，与 2020 版 3000 取并集 | 作为依据，标 `provisional` | S3：删 `hs25` 条目重建 → gk 少 ≈ 211 词；或删 `hs20` → 少 94 词 |
| P4 | 括注变体/全称（`color`、`television`、`physical education`…）成为同阶段独立行 | 是（170 条关系，全部在 ECDICT；全称 ≤ 4 token） | S3：`classify_note` 变体分支改为只记录不授阶；美式拼写学习者在「仅本阶段新增」漏词 |
| P5 | `is/are/am/does` 继承 `be/do` 的阶段（显式清单，`saw/bore/shot…` 不继承） | 继承 | S3：删 `inherit_stages` → 小学页签没有 `is` |
| P6 | 掉出所有官方表的 ≈ 238 词保留为「课标外」词典词（`stage_min NULL`，只在「全部」与搜索可见；不删、不下架、不加「拓展」页签；详情页「课标外」芯片） | 保留 | 下架属 WLC 阶段 C；「拓展」层需第 6 个阶段或 tag 表（S1 的触发条件 ②） |
| P7 | 教材拓展层 / 上海-全国双方案 / 省份分层都不做 | 不做 | 触发条件写在 `DESIGN.md §3.1`：届时按 stages-as-data 目标模型做第二次迁移（≈ 11–14 人日） |
| P8 | 新用户默认 `["xs","zk"]`/主攻 `xs`；「初中生」预设含小学；高中生预设保持 `['zk','gk']`（不含小学，与 `zk ⊄ gk` 不闭包一致） | 是 | 改 DDL 默认要再重建一次 `user_settings`（下次迁移）；预设只改 `WelcomePage.tsx` + `DESIGN.md:330` |
| P9 | 现有两位用户只 `current_stage + 1`，不给 kimi（只选初中）自动加小学 | 不加 | S1：0011 加一条 `UPDATE user_settings SET stages_json='["xs","zk"]' WHERE user_id=2` |
| P10 | `difficulty` 尺子不扩 6 级；排序用 `difficulty + 1` 平移 | 不扩 | 扩 6 级 = ≈ 12 文件 + 三方绑定 schema + `PROMPT_VERSION`（另一轮） |
| P11 | 国家高中附表（国家名称）只存档不授予 gk | 不授予 | S3：manifest 两条改 `policy: appendix`, `stages: ["gk"]` |
| P12 | mahavivo CET 四表缺席时允许构建（现有行 CET 旗标与 `cet6_star` 逐字保留；新行只取 ECDICT 标签） | 允许 | S3：`--wordlists` 设为必填 |
| P13 | `overrides.tsv` 自写释义 ≤ 30 条，作为本仓库 MIT 文本 | 允许（23 条） | 不允许则 `bund/mum/un/wto/tcm…` 带 ECDICT 错义项上线 |
| P14 | `WD_IMAGE_KID_STAGES` 默认空（儿童风格与插画优先轮关闭）；试点达标后默认 `xs`；`zk` 永不在默认里 | 关 | 改 `.env` 一行，无代码 |
| P15 | 不做 `image_hint`/正面出图；图只在学习卡背面；`text_free` 列为未来「图→词产出模式」预留 | 不做 | 新学习模式（第四期候选） |
| P16 | content v2 的初中例句改校园/日常语域按**词**生效（学 zk 词的成人用户 1 也会得到校园语域例句）；小学条款只对 `stages ∋ 小学` 的词 | 接受 | 改规则 3 文字 + 再升一次 `PROMPT_VERSION` |
| P17 | 30 张旧 SVG 不重画、49 张旧卡不 `force` | 不重画 | 管理页逐词 `refetch-image {provider:"claude_svg"}` / `regenerate`（≈ $0.42 / ≈ $0.2） |
| P18 | `xsFull` 文案「小学（课标二级词汇）」；`outside` 文案「课标外」；`newOnlyZk`「仅初中新增（不含小学）」 | 如左 | S4：`zh.ts` + `FRONTEND.md §8` |
| P19 | 导入器对未知阶段码只计数告警，硬门在构建期 | 告警 | S2：改抛 `SeedFormatError`（`seed_check` 已捕获，不影响启动） |
| P20 | 失败词即时重试的两处挂点推迟到集成后小提交；一期只有夜间重试 + CLI | 推迟 | 2 行 + import（S2 文件） |

### 9.2 未决问题（无人能立刻回答；不阻塞本轮）

1. 考试院高考 200 个补充词、上海 2026 中考手册（1,785 + 347）无机读件；manifest 预留 `shmeea26`、`shmeea:gk200`。
2. 2025 修订版课标的教育部印发文号未找到（P3 的 `provisional` 标记）。
3. `PLA Day`、`Mount Huangshan`、`Mount Taishan` 三个附表词 ECDICT 无条目（需同时自写音标，本轮跳过入 `stats.skipped`）；39 条词组模板（`agree with sb.`）的归一规则——下一版种子。
4. `a.m`/`a.m.`、`ice cream`/`ice-cream`、`e-mail`/`email`、`miss`/`miss.` 并存的合并需要 `merged_into_word_id` 流程（WLC 阶段 C）；`I` 的 `kind='proper_noun'`（`derive_kind` 副作用）不在本轮改。
5. 小学页签仍按成人 `frq` 排序（前 15 词几乎全是功能词）；教材/年级/单元顺序种子无字段；具体性常模（Lancaster CC BY 4.0）另起任务。
6. 生产机（Lighthouse）SQLite 版本与 `legacy_alter_table` 默认未知——部署前在目标机跑 `scripts/rehearse_migration.py`。
7. 即时重试挂点（P20）、`images-prune` 对导入来源的识别、「不合适」举报阈值 1 → N 个不同用户（WLC 阶段 C，K-12 邀请前必须完成）。
8. 配图二期的前提：智谱 BigModel 账号/key 由谁申请、放哪台机器（东京 Lighthouse 或进程环境无 `HTTP(S)_PROXY` 的 Mac）；5–8 名小学生看图说义 + 24 h 回忆小样本是否做（监护人书面同意）；《人工智能生成合成内容标识办法》下本应用的主体定性与 GB 45438-2025 元数据字段名（公网上线前法务核对）。
9. Openverse 应用注册（匿名 200/日 → 10,000/日）应在小学阶段落地前完成；Pexels 许可页原文未核。
10. 11-02 的 18 个 `fetch_image` 任务在 Wikimedia 有应答却失败的原因（需线上 journal）；黑名单/打分规则的真实命中率只能在试点中测。
