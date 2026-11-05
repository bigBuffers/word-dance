# 配图更易记 · 评审（视角：维护者怀疑者）

评审对象：`design/images/{evidence-first,pipeline-engineer,generation-first}.md`（三份全文逐字读完）。基线 `main @ 75df534`（`git rev-parse` 实测），线上库只读副本 `scratchpad/live-copy.db`（`sqlite3 -readonly` / `?mode=ro`），日期 2026-11-05。本文不改任何仓库文件；我自己的脚本放在 `scratchpad/judge-maintainer/`（`pos_dist.py`、`pos505.py`，`python3 -I` 运行）。

评审立场：盯契约镜像负担（`types.ts` / `API.md §9` / `FRONTEND §8` / `check_contract.py` / `CLAUDE_INTEGRATION §4.1`）、硬编码是否真的减少、测试与文档改动量是否被低估、工作量是否诚实、实现时最容易出错的地方。**默认每个未被证明的说法都是错的**；下面每条结论都带 `文件:行` 或 INDEX/facts 编号。

---

## 0. 抽查结果（引用是否属实）

三份设计各抽查 ≥ 10 处引用并逐一打开原文核对；凡标「✗」的都是事实性错误，「△」是口径/范围不准。

### 0.1 三份共同引用的事实（全部属实）

| 引用 | 原文 | 结论 |
|---|---|---|
| `backend/wd/migrations/0001_init.sql:248` `word_images.provider` CHECK 五值；`:270-272` 三个索引；`:250` `query` 注释「image keyword that produced it」；`:266` `score`；`:199` `active_image_id` 逻辑 FK；`:559` `content_reports.image_id` 逻辑 FK；`v_bank` `:572-576` 只连 `user_words`/`words` | 全部一致；`grep TRIGGER` 为空 | ✓ 重建 `word_images` 不需 `DROP VIEW`，三份都对 |
| `0010_ai_provider.sql:9-10` `ALTER TABLE ADD COLUMN … NOT NULL DEFAULT … CHECK` 先例 | 一致 | ✓ |
| `db.py:41` `MIGRATION_FILE_RE`、`:159` `list_migration_files`、`:227/:246` `PRAGMA foreign_keys` 开关与 `foreign_key_check` | 一致 | ✓ |
| `test_db.py:362-366` SCHEMA.sql 字节一致；`:236-257` 基线升级 `_counts` 前后相等；`:132/:185` `REBUILD_USERS_SQL` 重建先例；`:283` 0009 测试 | 一致 | ✓ |
| `sanitize_svg.py:28-31` 白名单含 `text/tspan/title/desc`（无 `metadata`）；`:65-79 _parse`（`:67-68` 实体拒绝在前，`:70` 去 XML 声明，`:74` `DET.fromstring`）；`:137-166 _serialise`（`:139-140` 丢非白名单子树）；`:169-181 clean` | 一致 | ✓ |
| `store.py:76-120 activate`（`:87` `query` 参数、`:105-113` 显式列 INSERT）；`:152-174 activate_svg`（`:166` `alt_zh[:200]`） | 一致 | ✓ |
| `handler.py:121-124` SELECT、`:134-137` 关键词、`:148-153` 链、`:158-159` priority ≥ 90 跳 Openverse、`:165` `p.search(kw, SEARCH_LIMIT)`、`:182` `select.rank`、`:198-206` SVG 兜底、`:352` CLI `--provider` choices | 一致 | ✓ |
| `interfaces.py:73-79` `ImageProvider.search(query, limit)`，`runtime_checkable` | 一致 | ✓（`Candidate.title: str` 非 Optional，见 generation-first △） |
| `select.py:20-24` 黑名单、`:30` 尺寸、`:54-77 reject_reason`（`:63-64` 许可、`:65-66` MIME）、`:80-101 score`、`:104-128 rank` | 一致 | ✓ |
| `wikimedia.py:40-51 params`、`:53-57 search`、`:97` mime；`openverse.py:28 PAGE_SIZE`、`:41-42 params(query)`、`:65-72`、`:114-119 extra`；`pixabay.py:30-39`（`:34 image_type`）、`:78 extra.type`；`pexels.py:29-30`；`base.py:100-118 get_json` 只对 ≥ 400 抛错；`:203-205 license_allowed` | 一致 | ✓ |
| `quota.py:28 DEFAULT_COOLDOWN_S`、`:37-47 limits_for`、`:75-89 check`（`:82-83 disabled`）、`:160-179 status` | 一致 | ✓（`status` 只遍历 `cfg.image_providers`，见 generation-first △） |
| `svg.py:32-33/:40-52/:115/:137`；`content.py:46/:49/:54/:61-63/:88/:131-203/:189-201/:253-261/:405`；`models.py:34-44/:113-126` | 一致 | ✓ |
| `bank.py:636,659`、`batches.py:354-355,639`、`scheduler.py:66 TickResult`、`:364-397 maintenance`、`cli.py:54`、`test_cli.py:51-58`、`registry.py:30-39`、`queue.py:34`、`worker.py:359-362`、`ledger.py:20` | 一致 | ✓ |
| `schemas.py:46/:47/:51/:52/:87-90/:156-175/:376-392/:549-563/:576-585/:1094-1101/:1132/:1349-1351`；`types.ts:5/:34-43/:70-75/:80-87/:185`；`endpoints.ts:340/:538-540` | 一致 | ✓ |
| `test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5`（`svg_system`↔§5.5、`content_system`↔§5.1）、`:56-62` schema 三方字节绑定；`test_images.py:616 "<text" in stored`、`:139/:162` 请求形状、`:535-547`、`:626-635 photo_mix` 精确字典；`test_providers.py:57-64/:178/:351/:374-384`；`test_select.py:92-119`；`test_sanitize_svg.py:124 malformed`、`:158-170 A &amp; B`；`test_content_apply.py:80-81`；`test_budget.py:33`；`test_api_schemas.py:108/:113`；`test_settings.py:59-78`；`test_admin_ops.py:87/:123/:144`；`test_deploy_files.py:119`；`test_docs_contract.py:114` | 一致 | ✓ |
| 文档锚点：`CLAUDE_INTEGRATION.md:206/:208/:279/:355/:403/:407/:416`；`API.md:3/:231/:304/:314-321/:420-421/:457/:465`；`DESIGN.md:28/:518/:521-553`；`DEPLOY.md:296/:326/:339/:345/:417/:434`；`ops.md:198/:202`；`env.example:83/:149-165`；`FRONTEND.md:87/:209/:260/:288/:292/:298`；`ATTRIBUTION.md §3.4/§6`；`AI_FALLBACK_MODEL.md:29`；`WORD_LIBRARY_CURATION.md:65/:115/:183` | 一致 | ✓ |
| live-copy：`schema_migrations` 1/8/9/10；`user_settings` 两行（`1|["zk","gk","cet4","cet6"]|3|1`、`2|["zk"]|1|1`）；`word_images` 30 SVG（`query` 全 NULL）+ 1 wikimedia；`image_state` failed 18 / none 9,113 / ready 31；`ai_calls` svg 34 次 $0.4207 = $0.01237/次；`generate_svg` 34/30/4；`stage_min=1 AND kind='word'` 2,012 / frq>0 1,960 / 1 有内容 / 0 有图；49 个有内容词 `stage_min` 3:48、1:1；`difficulty` 49；`content-v1` 49 行；18 个 failed 词名单含 have/employee/property；`map/flag/cover/sign/text/blood/gun/chart` 均 `stage_min=1` | 全部复现 | ✓ |
| Pillow `.venv` 12.3.0，`JpegImagePlugin._save` 源码含 `xmp` 与 `comment` 参数 | 实测 | ✓ |
| `scratchpad/design-stage-model-minimal/0011_primary_stage.sql` 存在：重建 `words` + `user_settings`，重编号 1..5（xs=1），`DROP VIEW v_bank`，清 `kv.seed_version`；**不碰 `word_images`，不含 `image_hint`** | 实读 | ✓ 0011 已被占用 |
| facts/verify：`[image-memorability-26]`（1344×768 枚举、`watermark_enabled` 默认 true、`content_filter` 0–3、URL 30 天、`user_id`）、`[verify image-memorability-7]`（Tonzar 被试 "fourth and eighth grades"）、`[verify images-pipeline O6–O9]`、`:109` `thumbmime=image/png` 实测、`[images-pipeline-25/28/33]`、`[ai-prompts-stages-5/10/12]` | 一致 | ✓ |

### 0.2 三份共同的错误（都把一个不存在的门禁当保险）

**✗ `scripts/check_contract.py` 不比对 `ImageMeta.provider` / `ImageMeta.kind` 的字面量。** `parse_types_ts`（`:151-171`）只收 `export type X = 'a' | 'b';` 形式的顶层联合进 `unions`；`compare_shape`（`:222-247`）只比**属性名** + optional/nullable 备注。`types.ts` 没有导出 `ImageProviderName`——`ImageMeta.provider` 与 `kind` 是接口属性上的**内联**字面量（`types.ts:83-84`）。所以三份设计反复写的「`check_contract.py:274-281` 顺序敏感比对 `ImageProviderName`，两边必须同提交」对配图契约**不成立**：后端 `schemas.py:46` 加了值而 `types.ts:84` 没加，`check_contract` 绿、tsc 绿（前端 6 个夹具都用 `card_svg`）、后端 pydantic 也绿——契约静默漂移。真正守门的只有后端 `ImageMeta.model_validate`（`test_images.py:134,620`）与人眼。

含义（维护者角度）：任何加 provider 值的设计都应顺手把 `ImageProviderName`、`ImageMeta.kind` 提成 `types.ts` 的 `export type`（API.md §9 同步），让门禁真正覆盖——这才是「减少镜像负担」的实际改进，三份都没提。

### 0.3 三份都没列全的硬编码 provider 列表

非测试代码里 provider 名单共 ≥ 14 处：`schemas.py:46`（`ImageProviderName`）、`:1350`（`RefetchImageRequest`）、`config.py:52`（`IMAGE_PROVIDERS` 校验）、`:157`（默认链）、`0001_init.sql:248`（CHECK）、`service.py:57`（`is_svg` 二分）、`:241`（`photo_mix` SQL）、**`ledger.py:24 PHOTO_PROVIDERS_SQL`（零消费者的死常量，`grep` 全仓库只此一处）**、`providers/__init__.py:21-28`（`PROVIDER_CLASSES` → `PHOTO_PROVIDERS` → `handler.py:352` CLI choices）、`quota.py:37-47`、`types.ts:84` 与 `:186` 注释、`endpoints.ts:340`、`API.md:231/:318/:421`、`WordImage.tsx:28`、**`scripts/smoke.py:624` 的不变式 `with_photo + with_claude_svg + card_only == with_content`**。三份各列了 8–10 处，都漏了 `ledger.py:24`、`types.ts:186`/`API.md:421` 注释和 `smoke.py:624`。

---

## 1. 逐份评审

### 1.1 evidence-first（`evidence-first.md`）

**抽查（额外 14 处）**：`card_svg.py:111-118` 印词头/音标/释义/例句 ✓；`config.py:379-388/:389-401` 回退 URL/key 文件校验 ✓；`fetch.py:194-237/:241-268/:267` ✓；`security.py:586-606 settings_row_to_dto`、`:87 SETTINGS_BOOL_COLUMNS`、`routers/settings.py:110` ✓；`StudyCard.tsx:201-228`（提示 `:206-212`）/`:302-311` ✓；`StudyPage.tsx:635/:695` ✓；`SettingsPage.tsx:413` ✓；`zh.ts:54/:82/:86`、`FRONTEND.md:87/:288` ✓；`admin_ops.py:392-411`（`force: True` `:405`）/`:413-427` ✓；`eval_provider.py:115` ✓；`words.py:455-467/:470-479` ✓；pos 分布「n 1,043 / v 361 / j 301 / r 105 / 无 100 / m 50 / i 40 / p 40 / d 22 / c 19 / a 11 / u 6」与「505 转录件在库 497 词 n 233 / v 89 / j 73 / r 30 / i 19 / p 12 / d 12 / a 10 / c 7 / 无 5 / u 4 / m 2」——我用 `pos_dist.py`/`pos505.py` 按「占比最高的代码」**逐字复现**，功能词 243 词（11.6%）也对 ✓。

**不实 / 不准**：
- ✗ 「`check_contract.py:274-281` 的字面量联合比对要求两边同提交」（3.4.4、5.1）——见 0.2。
- △ 第二期「前端 `StudyCard.test.tsx:11` / `WordDetailPage.test.tsx:85` / `StudyPage.test.tsx:38` 的 `ImageMeta` 夹具（缺 `text_free` → tsc 红）」：实际 **6 处**（另有 `study/queue.test.ts:33`、`bank/AttentionBadge.test.tsx:57`、`pages/AddWordsPage.test.tsx:62`），红面低估一倍。
- △ 文档数字清单漏 `backend/wd/ai/budget.py:273` 注释（另两份都列了）。
- △ 「阶段模型设计若先合入其 0011，本文件顺延为 0012」——阶段模型的 0011 草稿已在 scratchpad，顺延几乎必然，第一期文件应直接按 0012 写并说明。

**契约镜像负担（第二期，三条契约线叠加）**：
1. `ImageProviderName` + `gen`：`schemas.py:46`、`:1350`、`types.ts:84`、`endpoints.ts:340`、`API.md:231/:318`、CHECK 重建、`WordImage.tsx:28`、`service.image_meta:57`——8 处，且 0.2 说明门禁不覆盖。
2. `ImageMeta.text_free`：`schemas.py:576-585`、`types.ts:80-87`、`API.md:314-321`、`service.image_meta`/`card_meta`、`words.card_image_meta`、6 个前端夹具、`StudyCard.test.tsx`——≥ 12 处。
3. `Settings.image_hint`：`schemas.py:156-175/:376-392`、`types.ts:34-43`、`API.md` 端点 14/15 + §9、`security.py:87/:586-606`、`routers/settings.py`、`onboarding.py`、`test_api_schemas.py:108`、`test_settings.py:59/75-78`、`SettingsPage.tsx`、`zh.ts` + `FRONTEND §8`（两个测试）——≥ 13 处。
4. 配置 9 个 `WD_IMAGE_GEN_*` + `WD_IMAGE_KID_STAGES`：`config.py` 字段 + 解析 + `env.example` + `DEPLOY §4` 各 10 行（`test_deploy_files.py:119`、`test_docs_contract.py:114` 钉死）。
5. 两个迁移：0011/0012 四列附加 + 下一号 `word_images` 重建 + `user_settings ADD COLUMN image_hint` + `UPDATE … CASE current_stage IN (<索引>)`。

**硬编码是否减少**：没有减少，净增。新增 `FUNCTION_POS` frozenset、`is_generated = provider in ("claude_svg","gen")`（第 15 处 provider 列表）、迁移里按 Q1 钉死的阶段索引常量、`KID_UNSAFE_RE`/`PEOPLE_RE`/`TEXTY_RE` 三张词表。做对的地方：`WD_IMAGE_KID_STAGES` 用**阶段码**而非整数（对 Q1 三种编码都鲁棒，`stage_to_index` 算索引）；`prompt_version`/`model`/`text_free` 做成**列**，用数据而不是约定承载语义——这是三份里唯一在数据层消灭「`query` 列复用」这种约定的设计。`gen` 计入 `with_claude_svg`（标签「AI 示意图」）是为了试点期不改 `AdminOverviewWords` 契约——可接受，但 `photo_mix` SQL 必须注释并承诺第三期拆 `with_generated`，否则两年后没人知道那一格为什么混着位图。

**测试/文档改动量**：第一期红名单 5 项（含 `test_schemas` 两个参数化用例）**准确**；5.2 新测试 ≈ 20 条、5.3 排练命令用 `.venv/bin/python` 的 `run_migrations` ✓。第二期红名单基本全，但前端夹具 3 → 6。

**工作量诚实度**：第一期 5 人日中「`style.py` + handler 改造 1.0」要同时做功能词短路、两轮 `names`、`get_json(return_headers)`、`maxlag → ProviderError`、`select` 的 `reject_reason/score/rank` 三个签名变更贯穿 handler——偏乐观，我估 **6–7 人日**。第二期「契约（`gen`、`text_free`、`image_hint`）前后端 + 文档 + 测试 1.5」：按本仓库纪律每条契约线至少 0.75–1 人日（三方逐字同步 + 夹具 + 两套 i18n 测试），应为 ≈ 3；加上 `image_hint` 的注册默认与迁移 CASE，第二期我估 **11–12 人日**（设计写 8.5–9）。合计 ≈ 18 vs 14。

**最容易出错处**：
1. `with_label` 在 `clean()` 之后插 `<desc>`：若 Claude 自己也画了 `<desc>`（白名单允许）文件里会有两个；幂等测试要先定义「幂等」的含义。
2. `BARE_AMP_RE` 对 `&amp`（漏分号）会变成 `&amp;amp`——可接受，但要写进测试。
3. `last_fetch_at` 用 `dedupe_key = 'image:<id>' OR LIKE 'image:<id>:r%'` ✓ 不会误配 `image:12`，但 `jobs.finished_at` 对 `cancelled` 任务为空，`COALESCE(finished_at, updated_at)` 必须保留。
4. `image_hint` 的两处默认（迁移 CASE 与注册按角色）要互相一致，且迁移 CASE 的索引只在阶段模型 0011 定稿后才能写死——发布后不可改。
5. `handler` SELECT 要同时加 `stage_min, pos, kind`（4.1 表有 `kind`，3.1.2 正文没有）。

**致命缺陷**（会导致线上错误/契约破坏/测试红/违规而未说明）：无「线上错误」级别。严重项：① 依赖不存在的 `check_contract` 覆盖（0.2）；② 第二期前端夹具数低估一倍 + 三条契约线 1.5 人日；③ `image_hint` 迁移 CASE 常量钉死 Q1 索引（已自认，但「迁移发布后不可改」没写）；④ `gen` 混入 `with_claude_svg` 的语义债。

**值得嫁接**：`text_free`/`prompt_version`/`model`/`eval_json` 列（数据级保证，`eval_json` 与 `score` 分列）；`WD_IMAGE_KID_STAGES` 阶段码配置；黑名单拆 `UNSAFE_RE` / `NON_PHOTO_RE` + lemma 豁免（`map/flag/cover/sign/text` 都是 `stage_min=1`，已核）；副词入不配图集合（243 词，有线上反例 `despite/particularly/directly/suddenly`）；试点预注册门槛（通过率 ≥ 70% 且每通过图 ≤ $0.02）+ Cohen κ ≥ 0.6；`<desc>` 隐式标识 + UI 题注；`get_json(return_headers=True)` 取 `Retry-After`；`WD_IMAGE_GEN_POSITION=only_requested` 默认；旧 30 张卡「`text_free=0` 自动排除在正面提示之外」。

### 1.2 pipeline-engineer（`pipeline-engineer.md`）

**抽查（额外 14 处）**：`config.py:256` `present = frozenset(k for k in e if k.startswith("WD_"))`，`from_env` 没有「未知 `WD_` 键即拒绝」的分支，只对取值抛 `ConfigError`（`:342 WD_TZ`、`:361 WD_IMAGE_PROVIDERS`）——`.env` 多出 `WD_IMAGE_KID_STAGE_MAX` 对旧代码无害 ✓（这是三份里唯一做了回滚兼容分析的）；`openverse.params(query)` 没有 `limit` 参数 ✓（改签名是真改动）；`test_sanitize_svg.py:124` `<rect></svg>` ✓、`:158-170` `A &amp; B` ✓；`test_providers.py:2` 文档串「page_size 20」✓；`smoke_mock.py:37 EMPTY_OPENVERSE` ✓；`scheduler.py:250-253` `get_settings` 懒加载 ✓、`:298 requeue_dead_once` ✓；`media.py:27 SVG_CSP` ✓；`worker.py:359-362 IoWorker` ✓；`words.py:204-206 SELECT *` ✓；基线 SQL 八条**全部复现**（§5.3）；`pos.ts:8-20 POS_LABELS` ✓（但见下）；`WordImage.tsx:50` `kind !== 'photo'` → `--flat` ✓；`StudyPage.tsx:697-698` 提示 ✓。

**不实 / 不准**：
- ✗ **§3.2.2「`docs/CLAUDE_INTEGRATION.md:279-285` §5.5 的代码块手工同步（该块没有测试绑定）」与 §3.3.2「§5.1 的提示词代码块同步（无测试绑定）」都是假的**：`backend/tests/unit/test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5` 以 `rstrip("\n")` 逐字节比对 `svg_system.txt`/`content_system.txt` 与 §5.5/§5.1 的 ``` 块，并要求首字符为字母。§5.1「已有测试中会红的」表漏了这两个参数化用例。P1-1/P1-2 一合并就红，除非实现者碰巧逐字节同步。这是本设计最明显的事实错误，而且正是「维护者怀疑者」最在意的那类（测试清单不可信）。
- ✗ `WD_IMAGE_KID_STAGE_MAX=0` = 关闭 建立在「`stage_min` 最小为 1」之上（`[A3]`）。Q1 选 b（小学 = 0）时 `0 <= 0` 为真：「关闭」态对小学词**静默开启**插画链。设计自己说 Q1-b 时该设 1，却没发现 0 这个哨兵值在 Q1-b 下失效。
- △ 「首位词性 n 808 / v 557 / adj 235 / other 207 / adv 163 / none 42」：我按**第一个 token** 复现得 n 812 / v 559 / r 165（全 kind），即他们数的是 pos 串里**排第一**的代码，而 ECDICT 的 pos 串不按占比排序（`fuse: n:46/v:54`）。他们的门却是「功能词码合计 ≥ 80%」。统计口径 ≠ 规则口径，「门只影响 207 个」的结论无依据。
- △ 功能词码含 `x`（否定）：`pos.ts:8-20` 没有 `x`；线上 `stage_min=1` 的 2,099 词 pos 字母集为 `n v j r m a c i t p d u`，无 `x`。无害但无依据，且「与前端 `POS_LABELS` 同一套码」不成立。
- ✗ 「`scripts/check_contract.py:275-281` 按顺序比对字面量联合」（P2）——见 0.2。
- △ `word_images.query='svg:v2'` 约定：`0001_init.sql:250` 注释「image keyword that produced it」受 `docs/SCHEMA.sql` 字节绑定不可改，约定只能活在 DESIGN §9；`query` 还会进 `FetchOutcome.query`/`result_json` 与管理员视图。第二期 `substr(query,5)` 回填得到 `v2` 而非 `svg-v2`——两份设计（本份与 generation-first）用了不同字符串，本身就是「约定会漂」的证据。
- △ P1-4 说默认关时线上「只多 `thumbmime`、`maxlag`、`page_size=10` 三个无害参数」，但同一节给照片风格加了 `category=photograph`——这会排除 `digitized_artwork`，改变所有词的 Openverse 结果集，不是无害参数。
- △ P2 `provider` CHECK 用厂商名 `zhipu_image`（给了 `generated` 备选但没选）；`style` 列四值 CHECK 又是一张要重建才能改的表；`ImageMeta.kind` 加 `generated`、`hint_safe`、`Settings.image_hint`、`with_generated` → **四条契约线**，比 evidence-first 还多一条，却估 6–8 人日且只是设计。
- ✗ P2 把 `user_settings.image_hint` 「搭 0011 的 `user_settings` 重建」：阶段模型 0011 草稿（scratchpad）没有这列。要么改别人的迁移文件（跨设计耦合，未声明），要么自己再写一个附加迁移（与「搭车」的说法矛盾）。
- △ §6 上线第 4 步直接在**线上** `.env` 写 `WD_IMAGE_KID_STAGE_MAX="1"`（两位真实用户立即进入未评测的插画链），与 §2「默认关让代码可合并」、§3.7.3「评分阈值才改默认」、§3.7.2「私有拷贝 + 出口正常的机器」三处自相矛盾；且 Mac 出口正是 49/49 失败（≥ 27 个因冷却未发请求）的那条出口，两轮抓取等于在失败链路上加倍请求。

**契约镜像负担**：第一期 **0**（无 `schemas.py`/`types.ts`/`API.md`/DDL/前端改动，`check_contract` 与 vitest 不动）——维护者最喜欢的形态；只新增一个 `Settings` 字段（`env.example` + `DEPLOY §4` 各一行）。第二期四条契约线 + `style`/`prompt_version`/`eval_json` 列 + `zhipu_image` CHECK + `image_hint`，是三份里**第二期镜像最多**的。

**硬编码是否减少**：第一期不增镜像，但新增三张正则词表 + `FUNCTION_POS` + 整数阈值配置。`WD_IMAGE_KID_STAGE_MAX` 是**与 Q1 编码耦合的配置级硬编码**：重编号时值要从 1 改 2，Q1-b 时 0 失效——把本该由代码按阶段码推导的东西推给运维记忆。`query` 复用是约定不是约束。第二期 `style` 列与 `provider → kind` 推导重复（同一事实两处存）。净效果：短期最省，长期最多。

**测试/文档改动量**：第一期红名单 10 行里漏了 `test_schemas` 两条（见上），其余准确；`test_deploy_files.py:119,136`、`test_docs_contract.py` 都列了 ✓。新增测试 9 组合理。

**工作量诚实度**：P1 5.0 人日：P1-4（4 个 provider 签名 + handler 双层循环 + CLI `--style` + `MIN_SIZE` 字典 + ≈ 8 条新测试 + 文档）1.5 偏紧；P1-1 0.5 还要加上他们不知道的 §5.5 同步与 `test_svg_prompt.py` 新文件。我估 **6–6.5 人日**。P2 6–8：四条契约线 + 重建 + fake + 标识 + VLM——我估 ≥ 10。

**最容易出错处**：① 提示词与 §5.1/§5.5 不逐字节相同（他们以为没测试）；② `kid_stage_max` 哨兵值；③ `clean_keywords` 返回值改成二元组后所有调用方与 `test_images.py:535-547`；④ `retry_due` 用 `json_extract(payload_json,'$.retry')` 在 `jobs` 上全表扫描（表小，可接受，但要注释）；⑤ `category=photograph` 对现有命中率的影响没人测过。

**致命缺陷**：① 测试绑定断言为假 → P1-1/P1-2 红且清单误导；② `KID_STAGE_MAX=0` 在 Q1-b 下失效；③ 上线即在线上 `.env` 开插画链，与自己的默认关/私有拷贝试点矛盾且未标为偏离；④ P2 `image_hint` 寄生在他人 0011 上（跨设计耦合未声明）。

**值得嫁接**：7 个可独立回退提交及合并顺序（P1-7 → P1-1 → … → P1-4 最大最后）；`wd images-retry [--limit] [--dry-run]`；`query_ignored` 日志事件 + `FetchOutcome.detail` 可见化；30 天 ≤ 3 次自动重试封顶（`payload retry=true`）；按风格的 `MIN_SIZE` 字典；**查询词驱动**的相关词豁免（`allow = 查询 token ∩ RELEVANCE_RE`，比 evidence-first 的 lemma 豁免更通用：搜 `world map` 时允许标题含 map）；`.env` 未知键的回滚兼容分析；基线 SQL 八条作为排练核对表；`ESTIMATES["svg"]` 不动只改注释（比 generation-first 改估算值稳妥）。

### 1.3 generation-first（`generation-first.md`）

**抽查（额外 15 处）**：`db.py:159` 不要求编号连续 ✓；0011 被占用 ✓；`providers/__init__.py:21-28/:31-37/:40-59` ✓；`interfaces.py:52-70 Candidate` ✓（`title: str`，设计传 `None`，dataclass 不校验、`attribution_line` 容忍 ✓ 但类型不符）；`fetch.py:136/:149-154` https + 443 ✓、`:271-288 download_and_store` ✓；`select.py:63-64` 许可拒绝 → 必须绕过 `rank` ✓；`quota.py:28/:82-83/:160-179` ✓；`schemas.py:1132 ProviderQuota.provider: str` ✓；`openai_http.py:117-127 resolve_dialect`、`:86` 1301、`:206-228 api_key` ✓；`smoke_mock.py:35 IMAGE_HOSTS`、`:84/:95-96 overrides`、`:91-103 handle` ✓；`main.py:93-102` `img-src 'self' data:` ✓；`media.py:38-48` ✓；`test_db.py:236-257` 动态 `shipped_migrations()` ✓；`test_budget.py:33 == 0.03` ✓；`budget.py:33/:273` ✓；live-copy「49 词 `stage_min` 3:48、1:1」「30 张 SVG `query` NULL」「`schema_migrations` 1/8/9/10」✓；`FRONTEND.md:260/:292/:298`、`zh.ts:54/:86/:92`、`zh.contract.test.ts:61` ✓；Pillow 12.3.0 `comment`/`xmp` ✓。

**不实 / 不准**：
- ✗ **505 词样本的 POS「主标签 n 179 / v 135 / j 44 = 358 词可画」**：按占比最高的代码，497 个在库词是 **n 233 / v 89 / j 73**（与 evidence-first 一致，`pos505.py` 复现）；179/135/44 恰是**首位 token** 的分布（我复现得 n 179 / v 135 / j 44 / r 59）。§3.8 的「名词 100 + 动词 70 + 形容词 30」分层建立在错误词性上——「动词」池里有 46 个主词性是名词的词。
- ✗ **服务端注入 `<text … >AI</text>` 角标**（D5、§3.3 第 4 条、§3.6.8）违反自己在 §3.1 第 2 行采纳的「图中无文字」准则，并使 `test_images.py:616 "<text" in stored` 「恰好仍真」——一个不再检验所指的测试被保留。对小学生而言右下角 14 px 的「AI」是诱人细节；对第三期「无文字图才能作正面提示」的判据，这张图在代码层面**不是**无文字的；对 VLM 的 `text_present` 评分会假阳性。显式标识用 UI 题注即可（`WordImage.tsx:28`），把它画进像素是产品代价而非合规必需，且设计没有把这个取舍标为偏离。
- ✗ 「`check_contract.py:274-281` 顺序敏感」——见 0.2（他们甚至为此规定了 `…claude_svg, ai_image, card_svg` 的顺序）。
- △ 「`quota.status` 自动把 `ai_image` 作为一行报给 `AdminOverview.images.providers`」：`quota.py:163` 只遍历 `cfg.image_providers`。按他们推荐的试点配置（KID 链首位 + 成人链末位）成立；只配 `WD_IMAGE_PROVIDERS_KID` 时管理概览看不到生成配额。
- ✗ `AdminOverviewWords.with_ai_image` 会打破 `scripts/smoke.py:624` 的不变式 `with_photo + with_claude_svg + card_only == with_content`（他们同时给 `smoke_mock` 加了 `bigmodel.cn` 路由，所以 `make smoke` 一旦带 KID 链就红）——未列。
- △ `budget.ESTIMATES["svg"]` 0.03 → 0.015 不是「文档数字」：估算值用于预留与日预算预检（`budget.py:268-278`），减半意味着接近上限时更多 SVG 任务通过预检，可能小幅超子额度。应保留 0.03 或单独论证。
- △ `test_select.py:92-119`「新信号改变个别分值」→ 默认 `cand()` 是 800×600、`CC BY 2.0`、无 description（`test_select.py:11-25`），没有一行触发竖图/描述/人物信号；过度谨慎，但说明没有真的对照表格推演。
- △ 3.5 第 3 项放宽尺寸只对 `extra["category"]=="illustration"`——Commons `filetype:drawing` 候选没有 category，放宽永远不作用于 Commons。
- △ `ai_image` 实现 `ImageProvider` 但 `search(prompt, limit)` 的语义与协议不同（提示词而非关键词、返回一个候选、绕过 `rank`）：任何按 `chain` 泛型迭代 provider 的代码（`wd check providers` 的 `diag.py`、未来代码）都会把它当检索 provider 用；API 69 显式 `provider="ai_image"` 时 `build_chain(cfg, ("ai_image",))` 进入 `_photo_round` 还是 `_generate_round`，伪代码没说清。
- △ 1.2「线上照片命中率 0/49」作为「生成优先」论据：INDEX D2 说 ≥ 27 个因冷却未发请求、18 个原因未知——它证明的是出口/冷却问题，不是照片链不可用。

**契约镜像负担（P2，全部一次到位）**：`ImageProviderName` + `ai_image`、`ImageMeta.kind` + `'ai'`、`AdminOverviewWords.with_ai_image`、`RefetchImageRequest`/`RefetchProvider`、`zh.ts` 3 个键 + `FRONTEND §8` 3 行、**10 个 `Settings` 字段**（`env.example` + `DEPLOY §4` 各 10 行）、`IMAGE_PROVIDERS`/`SECRET_KEYS`、CHECK 重建、`AdminPage.ImageMix` 第四段、`ATTRIBUTION` 两处。为一个默认关闭、可能被试点否决的功能一次性铺满契约面——维护者会问：如果 C 臂输了，这些镜像谁来拆？

**硬编码是否减少**：做对的：`kid_max_index()` 由 `STAGE_ORDER.index("zk") + 1` 推导（Q1 a/b 下自动正确，`style_for` 对 `stage_min` 0 的测试也写了）；通用名 `ai_image`（不是厂商名）；**有序链表达生成器位置**（`WD_IMAGE_PROVIDERS_KID`）——一个机制表达「首选/兜底/不用」，不加模式枚举，优于另两份的 `POSITION` 枚举。做错的：`query='svg-v2'` 约定（同上）；三方言表（`zhipu/ark/generic`）是新硬编码且本机一把 key 都没有；`kind='ai'` 让 `image_meta` 从二分变三分、`WordImage` 从 `kind !== 'photo'` 变成枚举判断；10 个配置项。

**测试/文档改动量**：P1 红名单含 `test_budget.py:33`（他们改了估算值才红）、`test_select` 过度列；P2 列了 `test_db.py:236-257` 会自动纳入 0012 ✓、`test_admin_ops.py:144` ✓、`test_photo_mix_counts` ✓——但漏 `smoke.py:624`。新增测试清单最长（P2 ≈ 20 条），与 0.5 人日的测试预算不匹配。

**工作量诚实度**：**P1 3.5 人日（其中测试 0.5）不可信**：范围与另两份的第一期几乎相同（SVG v2 + sanitize + `aigc.py` 的 desc/角标 + content 提示词 + 照片链七项含 `maxlag`/`thumbmime`/四 provider 签名/尺寸门槛/打分 + 三挂点重试 + 夜间 + 文档），另两份都估 5.0；`aigc.py` 还是本期新增。P2 6.0 含三方言适配器 + fake + handler 链切分 + quota + 10 配置 + 0012 + 四契约点 + 前端 + 文案 + 文档 + 排练 + 试点脚本。我估 P1 ≈ 5.5、P2 ≈ 8.5–9，合计 ≈ 15 vs 10.5。

**最容易出错处**：① `_photo_round` / `_generate_round` 链切分与 API 69 显式 provider 的路径；② `ai_image` 配了但只在 KID 链 → 配额行不可见；③ 角标 `<text>` 与 `clean()` 顺序（注入在清洗之后，60 KB 上限不再覆盖）；④ 回滚：`ImageMeta.provider` Literal 不含 `ai_image` 的旧代码对已生成行 500——他们给了 `UPDATE … status='rejected'` 配方 ✓（诚实）；⑤ `ESTIMATES` 变更的预算副作用。

**致命缺陷**：① 角标文字违反自采准则并掏空 `test_images:616`；② 试点分层基于错误 POS 口径；③ P1 3.5 人日与测试 0.5 不可信；④ `smoke.py:624` 不变式未列、`quota.status` 半真、`ESTIMATES` 行为变化被当文档数字。默认关闭所以没有「上线即错」，但「为试点铺满契约」是维护者视角的最大风险。

**值得嫁接**：`WD_IMAGE_PROVIDERS_KID` 有序链 + 生成器按位置运行；`kid_max_index()` 从 `STAGE_ORDER` 推导；`backend/tests/fake_image_gen.py` + `smoke_mock` 两条路由（无 key 可合并、`WD_SMOKE_MOCK_HTTP=1 wd fetch-image apple --provider ai_image` 冒烟）；`content_filter > 0` → 返回空列表不触发冷却；`creator=<model id>` 溯源；0012 显式列名 `INSERT … SELECT`；回滚前 `UPDATE … rejected` 配方；标签同时写 producer 与 propagator 以覆盖两种主体定性；「百炼万相是异步接口不纳入」的取舍。

---

## 2. 打分（1–10；`effort_risk` 高 = 工作量小、风险低）

| 维度 | evidence-first | pipeline-engineer | generation-first | 依据摘要 |
|---|---|---|---|---|
| fit | 8 | 6 | 7 | ef：text_free 正面提示、小学/初中集合、A6 两用户迁移规则写明；pe：插画链默认关、提示模式后置，对 K-12 目标最保守；gf：K-12 生成链，但提示模式推到 P3 |
| correctness | 7 | 6 | 5 | ef：迁移/红名单准确，夹具 3→6；pe：测试绑定断言为假、哨兵值陷阱、统计口径错；gf：角标违规、POS 口径错、smoke 不变式、ESTIMATES 副作用 |
| effort_risk | 5 | 7 | 4 | ef：契约面最大但自认，实估 18 vs 14；pe：P1 零契约零 DDL 可独立回退，实估 6.5 vs 5；gf：P1 3.5 不可信，P2 为默认关功能铺满契约 |
| maintainability | 6 | 6 | 6 | ef：阶段码配置 + 数据列替代约定，但 +3 契约线 +10 配置；pe：P1 零镜像，但整数阈值耦合 Q1、`query` 复用、P2 四契约线 + 厂商名 CHECK；gf：链位置配置、派生索引、通用名，但 10 配置 + 方言表 + `kind='ai'` |
| evidence | 9 | 7 | 6 | ef：所有数字逐字复现、D1 逐条落点、Tonzar 年级正确；pe：基线 SQL 全复现，但「首位词性」≠ 规则；gf：POS 口径错、0/49 论据过度 |
| rollout | 7 | 8 | 6 | ef：附加迁移先行、代码可回退、排练用 run_migrations；pe：7 个独立提交 + .env 兼容分析，但线上日 1 开链自相矛盾；gf：P2 一次停机叠加重建 + 4 契约 + 10 变量，回滚配方诚实 |
| **overall** | **7.2** | **6.6** | **5.8** | |

排名：**evidence-first > pipeline-engineer > generation-first**。差距不大：pipeline-engineer 的第一期是维护者最想合并的形态，但它对测试绑定的事实错误和与 Q1 耦合的整数哨兵把它拉下来；generation-first 的工程想法（链位置、fake provider）最好，但为默认关功能铺满契约、角标违规与工作量不可信让它垫底。

---

## 3. 嫁接到最终方案的建议

1. **骨架用 evidence-first**：第一期就把 `prompt_version` / `model` / `text_free` / `eval_json` 做成列（附加迁移，与 0011 重建**合并到同一停机窗口**，编号按当时空号），不要用 `query` 列承载版本。`WD_IMAGE_KID_STAGES` 用阶段码。
2. **提交切分用 pipeline-engineer**：7 个可独立回退的提交与顺序；重试 30 天 ≤ 3 次封顶 + `wd images-retry --dry-run`；`query_ignored` 可见化；查询词驱动的相关词豁免替代 lemma 豁免。
3. **生成器接入用 generation-first 的形态**：`WD_IMAGE_PROVIDERS_KID` 有序链表达位置，不加 `POSITION` 枚举；`fake_image_gen.py` + `smoke_mock` 路由让 P2 在无 key 的 Mac 上测到可合并；`content_filter` → 空列表。但**不要**画角标，显式标识只用 UI 题注 + 厂商水印，隐式标识用 evidence-first 的 `<desc>` / XMP。
4. **三份共有的修正**：把 `ImageProviderName`、`ImageMeta.kind` 提成 `types.ts` 的 `export type`（`API.md §9` 同步），让 `check_contract.py` 真正覆盖；删除 `ledger.py:24` 死常量；`photo_mix` SQL、`API.md:421`、`types.ts:186`、`smoke.py:624` 四处 provider 分类同一次提交更新；`ESTIMATES["svg"]` 不动。
5. **试点抽样按「占比最高」的 pos 代码分层**（`pos505.py` 口径），不按首位 token。
6. **工作量按 7 + 12 人日重估**，并把「§5.1/§5.5 逐字节同步」「6 个前端 `ImageMeta` 夹具」「`env.example`/`DEPLOY §4` 每字段一行」写进 DoD。

---

## 4. 结论

evidence-first 胜出，理由是维护者最看重的两点它都做到了：**它的数字和引用经得起逐条复核**（唯一完全复现 pos 分布的设计），并且用**列**而不是**约定**承载新语义。它的短板是契约面与工作量低估，但它把每一处都列出来了，可以砍。pipeline-engineer 的第一期应整段吸收，但它关于测试绑定的错误断言必须纠正，`WD_IMAGE_KID_STAGE_MAX` 改为阶段码集合。generation-first 的链位置配置与 fake provider 值得保留，其余（角标、10 个配置、`kind='ai'`、`with_ai_image`、方言表）在试点证明生成器值得之前不应进入主干。
