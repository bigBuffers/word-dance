# 配图更易记 · 评审（角度：迁移与数据安全怀疑者）

评审对象：`design/images/{evidence-first,pipeline-engineer,generation-first}.md`（2026-11-05 版）。基线 `main @ 75df534`（`git rev-parse --short HEAD` 实测），线上库只读副本 `scratchpad/live-copy.db`（`sqlite3 -readonly` / `?mode=ro`）。本文只评审，不改任何仓库文件。

盯住的问题：SQLite 重建、CHECK/DEFAULT、`v_bank`、索引值错位、种子覆盖语义、线上 2 个用户的数据、回滚路径、`docs/SCHEMA.sql` 规则、测试会不会红却没人发现。默认每个未被证明的说法都是错的，直到我在代码或副本里看到它。

---

## 0. 一页结论

| 角度 | fit | correctness | effort_risk | maintainability | evidence | rollout | **overall** |
|---|---|---|---|---|---|---|---|
| evidence-first | 8 | 7 | 5 | 6 | 9 | 7 | **7.3** |
| generation-first | 7 | 6 | 6 | 6 | 7 | 7 | **6.5** |
| pipeline-engineer | 6 | 5 | 7 | 5 | 7 | 7 | **6.1** |

排名：**evidence-first > generation-first > pipeline-engineer**。

- 三份设计对迁移的核心事实判断都对：`word_images` 没有视图、触发器或真实外键引用它（`0001_init.sql:199,559` 两处都是逻辑外键），重建它不需要 `DROP VIEW v_bank`（`v_bank` 只连 `user_words`/`words`，`0001_init.sql:572-576`），运行器自己关/查外键并记 `schema_migrations`（`db.py:222-246`），`docs/SCHEMA.sql` 必须与 0001 字节相同（`test_db.py:362-366`，当前确为相同）。没有任何一份会把线上 31 行图片或 2 行用户设置弄丢。
- 差别在「测试会不会红却没人发现」「默认值在 Q1 各编码下是否仍成立」「契约改动面是否最小」：
  - **pipeline-engineer** 两次断言 §5.1/§5.5 提示词代码块「没有测试绑定」（文件 :82、:162），而 `backend/tests/unit/test_schemas.py:121-127 test_prompts_are_verbatim_from_section_5[content_system|svg_system]` 正是逐字节钉住这两个文件的测试；它的「会变红的测试」表（§5.1）因此漏掉两条。它的 `WD_IMAGE_KID_STAGE_MAX=0`「关闭」只在 `stage_min ≥ 1` 时成立，INDEX Q1-b（小学 = 0）下 `0 <= 0` 会让所有小学词在开关「关」着时进入插画链——正是 INDEX [A3] 警告的 0 值陷阱。
  - **generation-first** 的 0012 重建 DDL 是三份里最干净、逐列核对无误的；但它给 `AdminOverviewWords` 加 `with_ai_image`，却没把 `backend/tests/unit/test_api_schemas.py:113`（该 DTO 字段集合的相等断言）列入红测清单；服务端注入 `<text>AI</text>` 角标与自己的「图中无文字」原则相抵。
  - **evidence-first** 把第一期做成纯附加迁移（4 条 `ADD COLUMN`），第二期才重建；两个线上用户的 `image_hint` 结果逐行写进设计（A6）；红测清单完整（含上述提示词测试、`test_api_schemas.py:108` 的 `Settings` 字段集合）。它的问题是第一期默认 `WD_IMAGE_KID_STAGES=("zk",)` 等于在试点之前就把 2,099 个初中词（含用户 2 的全部学习词）切到「插画优先」链，与它自己的 D9「先测量再铺开」矛盾。

---

## 1. 核验方法与抽查结果

逐字读完三份设计；对每份引用的 INDEX/facts 条目与 `path:line` 抽查。下表只列**决定评分**的核验点（远超 10 处），✓ = 与 75df534 或副本一致，✗ = 不一致，△ = 成立但有保留。

| # | 引用（设计文件） | 核验 | 结果 |
|---|---|---|---|
| 1 | `0001_init.sql:245-272` word_images DDL：CHECK `:248`、`query` 注释 `:250`、`license` 注释 `:256`、mime CHECK `:265`、`score :266`、三个索引 `:270-272`（三份） | `sed -n 245,272p` | ✓ 列序 id, word_id, provider, provider_ref, query, source_url, landing_url, title, creator, creator_url, license, license_url, attribution_text, alt_zh, width, height, file_path, file_bytes, sha256, mime, score, status, created_at；generation-first 的 0012 `CREATE TABLE word_images_new` 与之**逐列一致**（含 `NOT NULL`/DEFAULT/CHECK） |
| 2 | `v_bank` 只引用 `user_words`/`words`（`0001_init.sql:572-576`）；`words.active_image_id`、`content_reports.image_id` 为逻辑外键（`:199`、`:559`）；无触发器（三份） | `grep -n -i "trigger\|CREATE VIEW\|word_images" migrations/*.sql` | ✓ 重建 `word_images` 不触发 INDEX [A4] 的 RENAME 陷阱 |
| 3 | 运行器：`PRAGMA foreign_keys=OFF` 在事务外、`BEGIN IMMEDIATE`、`foreign_key_check`、自写 `schema_migrations`（`db.py:222-246`）；`list_migration_files` `:159`；文件名正则 `:41`；`backup_pre_hook` `:252-261`（generation-first、evidence-first） | 读 `db.py` | ✓ |
| 4 | `test_db.py:362-366` SCHEMA.sql 字节一致；`:236-257` 升级测试；`:282-310` 0009 测试；`:128-150 REBUILD_USERS_SQL`；`EXPECTED_TABLES` 25 张（三份） | 读 `test_db.py` | ✓；但 `:236-257` 的 `_counts` 只数 `users` + 8 张用户子表，**不含 `word_images`**，且测试不插图片行——generation-first §5.1 用它证明「重建保留行数」不成立（△） |
| 5 | `test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5` 对 `svg_system`（§5.5）与 `content_system`（§5.1）（evidence-first、generation-first 列入红测；pipeline-engineer 称「无测试绑定」） | 读 `test_schemas.py:121-127` | ✓ 存在，参数化四个提示词文件，`doc_block(heading, lang="")` 逐字节比对 → **pipeline-engineer ✗** |
| 6 | `test_images.py:616` 断言 `"<text" in stored`（三份） | 读 | ✓ |
| 7 | `test_budget.py:33` `estimate("svg") == 0.03`；`budget.py:33` `ESTIMATES["svg"]=(0.03,0)`；`:273` 注释；`estimate()` 只在 `runner.py:443`、`openai_http.py:652` 作预留（generation-first） | 读 + grep | ✓ 改 0.015 只影响预留与这一条断言 |
| 8 | `test_content_apply.py:81` `prompt_version == "content-v1"`；其余 `content-v1` 都是夹具 INSERT 字面量；没有测试钉死 `EXAMPLE_EN_MIN=15`（pipeline-engineer §3.3.3） | grep 全仓库 | ✓（`test_scheduler.py:461`、`test_worker.py:392` 插入的 v1 行只用来表示「有活动版本」，不依赖版本相等；`already_ready` 的两处测试走 apply 路径） |
| 9 | `sanitize_svg.py`：白名单 `:28-31` 含 text/tspan/title/desc；`ENTITY_RE :48`；`_parse :65-79`（`fromstring` 在 `:74`）；`_serialise :137-166`，非白名单元素在 `:139-140` 连子树丢弃；`clean :169-181`（三份） | 读 | ✓ |
| 10 | `store.py`：`attribution_line :68-73`、`activate :76-120` 显式列名 INSERT `:105-113`、`query` 形参 `:87`、`activate_candidate :123-149`、`activate_svg :152-174`、`alt_zh[:200] :166`（三份） | 读 | ✓ 显式列名 ⇒ 新增带默认值的列对旧代码无害（evidence-first 的回滚论证成立） |
| 11 | `service.py`：`active_image_row` `SELECT wi.*` `:44-48`；`image_meta :51-80` 二分 svg/photo；`enqueue_fetch :155-183`；`word_is_studied :223-234`；`photo_mix :237-246` 四家照片源硬编码（三份） | 读 | ✓ |
| 12 | `handler.py`：SELECT `:121-124`、关键词 `:134-137`、`:158-159` priority ≥ 90 只跳 openverse、`:165`、`:182`、`:201-206`、`prune_unused :298-331`、`register_cli :349-361`、`--provider` choices `:352`（三份） | 读 | ✓ |
| 13 | `select.py`：`BLOCKLIST_RE :20-24`、`MIN_WIDTH/HEIGHT :30`、`is_blocked :40-42`、`reject_reason :54-77`（license `:63-64`、mime `:65-66`、description 只用于拒绝 `:72`）、`score :80-101`（haystack 只有 title+tags `:83`）、`rank :104-128`（三份） | 读 | ✓ |
| 14 | `fetch.py`：`validate_url` https `:136`、IP 字面量/主机规则 `:149-154`、`safe_download :194-237`、`normalise_image :241-268`（`img.save` `:267` 不写元数据）、`download_and_store :271-288`（三份） | 读 | ✓ |
| 15 | `quota.py`：`limits_for :37-47`、`check :75-89`（`disabled` `:82-83`）、`cooldown_seconds :113-121` 优先 `Retry-After`、`status :160-179` **只遍历 `cfg.image_providers`**（generation-first §3.6.10） | 读 | △ generation-first 说 `quota.status` 自动显示 `ai_image` 一行：只有 `ai_image` 在成人链 `WD_IMAGE_PROVIDERS` 里才成立；其推荐试点只放 KID 链 → 管理概览不显示 |
| 16 | providers：`wikimedia.py :27/:40-51/:53-57/:97`、`openverse.py :28/:41-42/:65-72/:114-119`、`pixabay.py :30-39/:78`、`pexels.py :29-30/:46`、`__init__.py :21-28/:31-37/:40-59`、`base.py :100-118/:184-205`、`interfaces.py :52-70/:73-79`（三份） | 读 | ✓ |
| 17 | `config.py`：`IMAGE_PROVIDERS :52`、`SECRET_KEYS :65-75`、图片字段 `:155-168`、`from_env` 只收集 `present` 不拒绝未知 `WD_` 键 `:252-256`、`WD_IMAGE_PROVIDERS` 未知值 `ConfigError :355-363`、fallback URL/key-file 校验 `:379-401`、`:522-534`、`entries :554-575`（pipeline-engineer §6 第 7 条、generation-first §3.6.5） | 读 | ✓ `.env` 多出的键在回滚时无害成立 |
| 18 | `content.py`：`:36` 从 `images.select` 导入、`PROMPT_VERSION :46`、`STAGE_ZH :49`、`EXAMPLE_EN_MIN :54`、`KEYWORD_RE :61`、`ALT_MAX :62`、`PREFIX_MIN :63`、`:88` 字典下标、`validate_item :131-203`、`enqueue_image :253-261`、`:347`、`select_jobs :405`（三份） | 读 | ✓ |
| 19 | `svg.py :32-33/:40-52/:115/:134-142/:137/:149`；`runner.load_prompt` `lru_cache` `:100-103`；`ledger.KINDS :20`；`registry.JOB_TYPES :30-39`；`queue.IO_TYPES :34`；`worker.IoWorker :359-362`（三份） | 读 | ✓（generation-first 写 `queue.py:34`、evidence-first 写 `:33`，实为 `:34`，无关紧要） |
| 20 | `schemas.py`：`Stage :25`、`ImageProviderName :46`、`Difficulty :47`、`STAGE_ORDER :51`、`STAGE_NAMES_ZH :52`、`stage_to_index/index_to_stage :56-67`、`Model extra="forbid" :87-90`、`Settings :156-175`、`SettingsUpdateRequest :376-392`、`Content :549-563`、`ImageMeta :576-585`（kind `:579`）、`AdminOverviewWords :1094-1101`、`ProviderQuota :1132-1138`、`RefetchImageRequest :1349-1351`；`check_contract.py:274-281` 顺序敏感比对（三份） | 读 | ✓ |
| 21 | 重试挂点：`bank.py:636,659`（两条 `enqueue_content_if_needed` 之后）、`batches.py:352-356`（`_enqueue_content_for`）与 `:639`（`append_to_today`）、`scheduler.py:364-397 maintenance`、`:298 requeue_dead_once`、`TickResult :66`（三份） | 读 | ✓ |
| 22 | 门禁：`test_deploy_files.py:119`（env.example 覆盖每个 Settings 字段恰一次）、`test_docs_contract.py:114`（DEPLOY §4 命名每个变量）、`test_cli.py:56-58`、`cli.py:54`、`test_config.py:101-107`（含 `wikimedia,unsplash` 非法用例）、`test_api_schemas.py:108/:113`、`test_admin_ops.py:87/:123/:144`、`test_providers.py:46-69/:172-190/:345-359/:374-384`、`test_select.py:71/:92-131`、`test_sanitize_svg.py:103-130/:158-170`、`test_images.py:31-33/:48-52/:139/:162/:350/:535-547/:626-635` | 读 | ✓ |
| 23 | 前端：`types.ts:5/:34-43/:70-75/:80-87`、`endpoints.ts:340/:538-540`、`WordImage.tsx:26-33/:28/:45/:50`、`StudyCard.tsx:171/:201-228/:206-212/:297-311`、`StudyPage.tsx:559/:635/:695-698`、`SettingsPage.tsx:413`、`zh.ts:54/:86/:92`、`AdminPage.tsx:147-154`、`utils/pos.ts:8-20`、`study.css:456-467` | 读 | ✓；`POS_LABELS` 没有 `x`（pipeline-engineer、generation-first 的功能词码表含 `x` 否定——副本里 `pos` 出现过的字母只有 a t n j i r v c d p m u，`x` 一次也没有；无害） |
| 24 | 文档行号：`CLAUDE_INTEGRATION.md:146-160/:206/:208-226/:279-285/:355/:401-403/:407/:416`、`DESIGN.md:28/:518/:546/:547/:550`、`DEPLOY.md:326/:338-345/:417/:421/:434`、`ops.md:198/:202`、`deploy/env.example:83/:149-165`、`ATTRIBUTION.md:34/:54-59/:74-79`、`FRONTEND.md:87/:260/:288/:292/:298`、`API.md:3/:231/:272/:304-308/:314-321/:420-421/:465`、`WORD_LIBRARY_CURATION.md:65/:115/:183`、`AI_FALLBACK_MODEL.md:29`、`scripts/eval_provider.py:115/:1067` | 读 | ✓ 全部命中；`$0.028`/「18 cards」出现在 DESIGN 28/518/550、CLAUDE_INTEGRATION 407/416、DEPLOY 326/434、ops 198、env.example 83、budget.py 273——与三份清单一致 |
| 25 | 线上副本数字：`schema_migrations` = 1/8/9/10；`user_settings` = `1|["zk","gk","cet4","cet6"]|3|1`、`2|["zk"]|1|1`；`word_images` claude_svg active 30（`query` 全 NULL）+ wikimedia 1（id 18）；`image_state` failed 18 / none 9,113 / ready 31；`ai_calls` svg 34 次 $0.4207 = $0.01237/次、829 token、7.9 s；`generate_svg` 34/30/4，被拒 job 45/88/97/136 = word 4259/4275/4935/818，column 226/224/402/410；`fetch_image` 20|failed|19|19、30|failed|30|15；有内容的 49 词 `stage_min` 3:48 / 1:1；18 个 failed 词中 17 个 `word_is_studied` 为真（`employee` 开放批次项 0）；`stage_min=1 AND kind='word'` 2,012 / frq 1,960 / 内容 1 / 图 0；`provider_state` 冷却到 11-05 13:28/13:33Z；`generate_content` 49 全 done | `sqlite3 -readonly` | ✓ 三份引用的每个数字都复现 |
| 26 | evidence-first §3.0 的 `stage_min=1` 主词性分布 n 1,043 / v 361 / j 301 / r 105 / 无 100 / m 50 / i 40 / p 40 / d 22 / c 19 / a 11 / u 6 | `python3 -I` 按最大份额重算 | ✓ 逐项相同（另有 t 1） |
| 27 | pipeline-engineer §3.4.1 的「首位词性 n 808 / v 557 / adj 235 / adv 163 / other 207 / none 42」 | 按 `pos` 字符串首位重算 | ✓ 逐项相同；但其门用的是「功能词码合计 ≥ 80%」，按该规则命中的是 119 词，不是 207（207 是上界） |
| 28 | `scratchpad/design-stage-model-minimal/0011_primary_stage.sql` 已存在（generation-first 开头声明） | `ls` | ✓ 阶段模型设计确已占 0011；evidence-first / pipeline-engineer 以 0011 命名第一期迁移会撞号（两者都写了「顺延」条款） |
| 29 | Pillow 12.3.0 的 `JpegImagePlugin._save` 读取 `xmp` / `comment`（evidence-first、generation-first「本机 .venv 实测」） | `inspect.getsource` | ✓ |
| 30 | `/usr/bin/sqlite3` `legacy_alter_table=1`（3.51.0）；`.venv` python sqlite 3.54.1 默认 0（三份引用 INDEX [A4]） | 实测 | ✓ |
| 31 | 读 `word_images.query` 的消费者（pipeline-engineer、generation-first 用它存 SVG 版本标记） | grep backend/frontend | 没有任何路由/服务读该列（只有 CLI 打印 `outcome.query`）→ 运行期无害，但语义与 `0001_init.sql:250` 注释「image keyword that produced it」相悖 |

---

## 2. 逐份评审

### 2.1 evidence-first（overall 7.3）

**打分**：fit 8 · correctness 7 · effort_risk 5 · maintainability 6 · evidence 9 · rollout 7。

**迁移与数据安全上做对了什么**

- 第一期 `0011_word_images_meta.sql` 只有 4 条 `ALTER TABLE ADD COLUMN`（`prompt_version`、`model`、`text_free NOT NULL DEFAULT 0 CHECK`、`eval_json`），与 `0010_ai_provider.sql:9` 同一先例；SQLite 3.51/3.54 都接受带 CHECK 的 ADD COLUMN；`store.activate` 显式列名 INSERT（`store.py:105-113`）、`service.active_image_row` `SELECT wi.*`（`service.py:44-48`）→ 旧代码不回滚迁移也能跑（核验 #10、#11）。这是三份里唯一把「第一期零重建」做成事实而不是口号的方案。
- 第二期 `0012` 重建 `word_images`：显式列名 `INSERT … SELECT`、保留 `id`、重建三个索引、正确指出无视图/触发器/真实外键、运行器已有 FK 关/查（核验 #1–#3）。`user_settings.image_hint` 用 `ADD COLUMN`（附加）而不是搭别人的重建，再 `UPDATE … CASE current_stage`——两个线上用户的结果（user 1 → 0、user 2 → 1）写进了设计表（A6 要求的「写死在迁移里」）。
- 不改 `AdminOverviewWords`（避开 `test_api_schemas.py:113`、`types.ts`、`API.md:420-421`），把 `gen` 计入 `with_claude_svg`——对 ≤200 张的试点来说是正确的契约克制。
- 红测清单（§5.1）完整：`test_prompts_are_verbatim_from_section_5[svg_system|content_system]`、`test_providers.py:46-68/:172-190` 参数字典、`test_images.py:616`、`test_content_apply.py:81`、第二期的 `test_api_schemas.py:108`（`Settings` 字段集合）、`test_settings.py`、`zh.test.ts`/`zh.contract.test.ts`、`check_contract.py`、`test_admin_ops.py:87/123/144`、前端 `ImageMeta` 夹具的 tsc 红——我逐条核过，没有漏项。`test_select.py:92-119` 原断言在其新信号下确实不变（800×800 宽高比 = 1.0 不触发 `< 1.0`；人像/文字降权只在 `style="kid"` 或标题不含相关词）。
- 排练一律走 `.venv/bin/python` 的 `run_migrations`（INDEX [A4] 的 `legacy_alter_table` 陷阱），回滚说明区分「代码回退（新列无害）」与「`wd restore` 快照（只在迁移本身失败时）」，并点明 `wd migrate` 的 `pre-migrate-10-to-11.db.gz` 会自动生成。

**致命/严重缺陷（按严重度）**

1. **第一期默认 `WD_IMAGE_KID_STAGES=("zk",)` 等于试点前就铺开。** `style_for` 对 `stage_min ∈ kid_stage_indexes` 返回 kid，默认集合 `zk` 覆盖线上全部 2,099 个 `stage_min=1` 词（用户 2 只学 zk）。于是「本周合并、无新 key」的第一期就把这些词的链改成 `wikimedia(drawing) → openverse(illustration) → … → bitmap`：每词请求数最坏翻倍（Openverse 本地 160/日），Commons `filetype:drawing` 命中质量未知（INDEX [D3]：结构图、小于 400×300 的剪贴画）。这与它自己的 D9「先测量再铺开」直接矛盾，而且设计文本把它当成默认而不是显式偏离。应默认空集（关闭），试点达标后再改默认。
2. **功能词 `skip_image()` 置 `image_state='failed'` + 夜间 `retry_failed_once` 无每词上限 → 永久性失败词每晚占满 50 个重试名额。** 条件是「failed ∧ 被学 ∧ 上次抓图 > 1 天 ∧ 任一 provider 不在冷却」，功能词每晚都满足，每晚各产生一个「skipped」任务；没有 pipeline-engineer 的 `RETRY_MAX_AUTO_30D` 之类的封顶，也没有把 `detail="function word"` 的词排除出扫描。不丢数据，但会让真正该重试的词排不进去。
3. **`0012` 的 `image_hint` 常量依赖 Q1。** 设计承认（「写当时成立的常量并注释来源」），但若阶段模型 0011 先合入并重编号，user 2 的 `current_stage` 会从 1 变 2，`CASE … IN (…)` 必须写 `(1,2)`；若 0012 先于阶段模型合入则写 `(1)`。这是两条设计线之间的**顺序耦合**，设计没有给出「两种顺序下各写什么」的表。
4. 小错：「注册默认值：`routers/onboarding.py` 按角色写（zk 角色 → 1）」——后端没有角色概念，`OnboardingRequest` 只带 `stages`/`current_stage`（`routers/onboarding.py:33-36`；角色预设在 `WelcomePage.tsx:33-38`），默认值只能由 `current_stage` 推。`media.py:27` 实为 `routers/media.py:27`（三份都这么写）。

**值得嫁接**

- 附加列优先：`prompt_version` / `model` / `text_free` / `eval_json` 四个真列，而不是把版本号塞进 `query`。
- A6 的落地写法：迁移里的 `UPDATE … CASE` 加上「线上两行各得什么值」的表，评审者可以直接对照副本核对。
- 不为试点改 `AdminOverviewWords`。
- 以阶段**码**（`WD_IMAGE_KID_STAGES`）而不是整数阈值做配置，索引由 `stage_to_index` 算，对 Q1 三种编码都不需要改语义。
- `text_free` 只由代码保证（`claude_svg` 去 `<text>/<tspan>` 后置 1，位图先 0），这是第二期「图作提示」唯一可信的门。
- 黑名单的 lemma 豁免（`map`、`flag`、`cover`、`sign`、`text` 都是 `stage_min=1` 的词）。
- `pos` 分布数字是实算的（核验 #26），可以直接用于试点样本框。

### 2.2 pipeline-engineer（overall 6.1）

**打分**：fit 6 · correctness 5 · effort_risk 7 · maintainability 5 · evidence 7 · rollout 7。

**迁移与数据安全上做对了什么**

- 第一期无迁移、无契约改动、无前端改动，7 个可独立回退的提交并给出合并顺序；`.env` 新键在回滚时无害的论证我核过（`config.from_env` 只收集 `present` 做改名检测，`:252-256`；全文件只对 `WD_TZ`/`WD_IMAGE_PROVIDERS`/`WD_AI_FALLBACK_PRICE_JSON` 抛 `ConfigError`）。
- 重试设计最稳：`RETRY_MIN_AGE_HOURS=6`、`RETRY_MAX_AUTO_30D=3`、夜间 ≤50、payload `retry:true` 标记、`wd images-retry --dry-run` 可排练；18 个 failed 词的学习状态逐词核对（核验 #25）。
- 第二期回滚说明诚实：一旦写入 `provider='zhipu_image'` 的行，旧代码 `ImageMeta.provider` 校验 500，「不存在只回退代码」。
- 「没有测试钉死 `EXAMPLE_EN_MIN=15`」「`content-v1` 其余出现都是夹具 INSERT」两条我都复核为真（核验 #8）。

**致命/严重缺陷（按严重度）**

1. **「该块没有测试绑定」是错的，红测清单漏两条。** §3.2.2（:82）对 §5.5、§3.3.2（:162）对 §5.1 都说提示词代码块「没有测试绑定（但契约文档要求一致）」，而 `backend/tests/unit/test_schemas.py:121-127 test_prompts_are_verbatim_from_section_5` 参数化 `content_system`/`lookup_system`/`consolidate_system`/`svg_system` 四个文件，与 `docs/CLAUDE_INTEGRATION.md` 对应小节的无语言代码块逐字节比对。P1-1、P1-2 一合入这两个用例必红，而设计 §5.1 的「会变红的测试」表没有它们。CI 会抓住，但这正是本评审角度要抓的「设计说不会红、实际会红」。
2. **`WD_IMAGE_KID_STAGE_MAX=0` 当「关闭」在 Q1-b 下失效。** `kid = stage_min is not None and stage_min <= cfg.image_kid_stage_max`，设计注「`0` = 关闭（`stage_min` 最小为 1，[A3]）」。INDEX Q1 选项 b 是「小学 = 0」：届时 `stage_min=0` 的小学词在开关「关」着时也满足 `0 <= 0` → 插画链对小学词静默打开。设计 §2 还宣称三种编码「都只需改一个配置值」，但没有看到自己的哨兵值与选项 b 冲突——与 INDEX [A3] 指出的 `int(x or DEFAULT)` 0 值陷阱同源。
3. **SVG 版本标记自相矛盾，且它是第二期 `hint_safe` 与回填的键。** §3.2.3 代码 `SVG_PROMPT_VERSION = "v2"`（写成 `svg:v2`）；§4 P1-1 第二条先写「加 `SVG_PROMPT_VERSION = "svg-v2"`」，同一段末尾又写「常量取 `"v2"`，于是列值恰为 `svg:v2`」。按前者会写出 `svg:svg-v2`，第二期 0011 的 `CASE WHEN query LIKE 'svg:%' THEN substr(query, 5)` 回填出的 `prompt_version` 就会是 `svg-v2` 而不是 `v2`，`hint_safe` 的 `prompt_version='svg-v2'` 判定随之漂移。把版本号塞进 `query`（`0001_init.sql:250` 注释「image keyword that produced it」）本身也是未写进 schema 的约定；运行期没有读者（核验 #31）所以不会炸，但这是典型的「语义债 + 回填依赖」。
4. **「线上行为只多 `thumbmime`/`maxlag`/`page_size=10` 三个无害参数」不实。** P1-4 还给默认（photo）风格的 Openverse 请求加了 `category: "photograph"`（§3.4.3 表），这会排除 `digitized_artwork`/`illustration` 类目，是默认链上的结果集收窄，不是「无害参数」。另外 `maxlag=5` 在复制延迟时让 Commons 以 200 + `error.code=maxlag` 应答→设计映射为 503 + 30 s 冷却（`quota.cooldown_seconds` 优先 `Retry-After`，核验 #15 ✓），行为合理但也是新的失败模式。
5. 第二期把 `user_settings.image_hint` 「搭 Q1/Q6 的 `user_settings` 重建」——`image_hint` 只需 `ADD COLUMN`（附加），不需要重建；这样写把配图线的发布与阶段模型迁移**文件**耦合在一起（必须去改别人的 0011，或者等它）。同样，「0011 与阶段模型切片合并发布；若分开则为 0012」把编号留给合入顺序决定，设计里却到处写 0011。
6. 小错：功能词码表含 `x`（副本里不存在，`pos.ts` 也没有）；「门只影响 207 词」是首位词性口径，按它自己的 80% 规则是 119 词（核验 #27）。

**值得嫁接**

- `RETRY_MAX_AUTO_30D=3` + `retry:true` payload 标记 + `wd images-retry [--dry-run]`：防止永久失败词每晚占名额，也给上线后一个可排练的运维入口。
- 7 个独立提交 + 合并顺序（文档 → 提示词 → … → 默认关的大改动最后）。
- 「默认关」的姿态本身（但要用阶段码 + 空集表示关闭，不能用 0 哨兵）。
- `query_ignored` journal 事件与 `FetchOutcome.detail` 追加，解决管理员 `query` 被静默丢弃。
- 指出 `requeue_dead_once` 复活的旧 dead 内容任务会按新 `PROMPT_VERSION` 重做（线上 0 个 dead，核验 #25）。

### 2.3 generation-first（overall 6.5）

**打分**：fit 7 · correctness 6 · effort_risk 6 · maintainability 6 · evidence 7 · rollout 7。

**迁移与数据安全上做对了什么**

- `0012_word_images_ai_provider.sql` 是三份里唯一写全的 DDL：与 0001 逐列一致（核验 #1），文件头注释说明为何不需要 `DROP VIEW`、为何不需要 `legacy_alter_table`、运行器负责 FK 与 bookkeeping；`INSERT … SELECT` 显式列、保留 `id`；不夹带 `user_settings` 改动（`image_hint` 留到 P3 作附加列）。一次重建只改一个 CHECK，是最小、最可审计的重建。
- 正确声明 0011 已被阶段模型占用（`scratchpad/design-stage-model-minimal/0011_primary_stage.sql` 存在，核验 #28），自取 0012，并指出 `list_migration_files` 不要求连续（`db.py:159`）。
- 不动 `jobs.type`、`ai_calls.kind`/`provider` 三个 CHECK（`0001_init.sql:487,511`、`0010:9`），理由（撞上 failover 状态机、三张表重建换不来功能）成立。
- 排练脚本用 `VACUUM INTO` 做私有拷贝、`wd migrate --dry-run`、`PRAGMA integrity_check/foreign_key_check`，全部走 `.venv` 的 `run_migrations`。
- 回滚段给出了必须先执行的 SQL（把 `ai_image` 活动行置 `rejected`、清 `words.active_image_id`、`image_state='failed'`），并说明原因（旧 `ImageMeta.provider` Literal 不含 `ai_image`）。
- 生成候选复用 `fetch.download_and_store`（SSRF、`image/*`、魔数、≤8 MB）与 `normalise_image`（重编码 JPEG → `mime` CHECK 自然满足）；明确必须绕过 `select.rank`（`license_allowed("generated")` 为 False，`base.py:184-205`，核验 #16）。
- 无 key 可测：`fake_image_gen.py` + `smoke_mock` 路由，沿用 `fake_openai.py:93-122` 的形状（核验 #25 的 fake 行号 ✓）。

**致命/严重缺陷（按严重度）**

1. **红测清单漏 `backend/tests/unit/test_api_schemas.py:113`。** P2 给 `AdminOverviewWords` 加 `with_ai_image`（`schemas.py:1094-1101`、`API.md:420-421`、`types.ts`），而 `test_api_schemas.py:113` 断言 `set(schemas.AdminOverviewWords.model_fields) == {"total","with_content","with_photo","with_claude_svg","card_only","user_added","pending_validation"}`——必红。§5.1 列了 `test_admin_ops.py:144`、`test_images.py:626-635`、`check_contract.py`，唯独没有这条。evidence-first 正是为此不改该 DTO。
2. **服务端注入 `<text … >AI</text>` 角标与「图中无文字」自相矛盾，并污染机械检查。** D5/§3.3 第 4 条在 `clean(allow_text=False)` 之后拼回一个 `<text>`，于是「`<text` 不在文件里 ⇒ 无文字」不再可用（它自己也注意到 `test_images.py:616` 的 `"<text" in stored` 因此「恰好仍真」）；文件也不再是 `sanitize_svg.clean()` 的输出。显式标识用 UI 题注即可满足，角标是新增文字而非证据要求。
3. **`quota.status` 自动显示 `ai_image` 配额行的说法只在 `ai_image ∈ WD_IMAGE_PROVIDERS` 时成立**（`quota.py:160-179` 只遍历 `cfg.image_providers`）；其推荐试点配置（`WD_IMAGE_PROVIDERS_KID=ai_image,wikimedia,openverse`，成人链不动）下管理概览看不到它的分钟/日计数——与 D8「成本控制用计数」的可观测性承诺不符。
4. `query='svg-v2'` 同样是把版本号塞进 `query` 列（与 pipeline-engineer 的 `svg:v2` 拼法不兼容；若两份被嫁接到一起，任何 `LIKE 'svg:%'` 回填都会漏掉另一种）。
5. 以 `test_db.py:236-257` 证明「重建保留行数」不成立（该测试不数 `word_images`，也不插图片行；核验 #4）。它自己新增的 `test_0012_rebuild_keeps_rows_ids_indexes_and_accepts_ai_image` 才是证据。
6. P1 的 `style_for` 对 `stage_min ≤ STAGE_ORDER.index('zk')+1` 立即生效 → 与 evidence-first 同样的问题：第一期就把 2,099 个初中词的 Commons/Openverse 请求改成 `filetype:drawing`/`category=illustration`（§3.5 第 2、3 项没有开关），试点前铺开。
7. 回滚第一句「代码回滚到上一个 tag 即可」被同段后半句自己否定（需先跑 SQL 或 `wd restore`）；应以后者为准。

**值得嫁接**

- `0012` 的 DDL 与文件头注释原样可用（把 `'ai_image'` 换成最终 provider 名即可）；`VACUUM INTO` 排练 + 验收 SQL 清单。
- 回滚前置 SQL（`UPDATE word_images … rejected` + 清指针）写进发布说明。
- 两条有序链（`WD_IMAGE_PROVIDERS` / `WD_IMAGE_PROVIDERS_KID`）一个值表达「首选 / 兜底 / 不生成」，不新增模式枚举。
- `style_for` 用 `STAGE_ORDER.index("zk") + 1` 计算阈值，对 Q1 三种编码都正确（0 ≤ 1；重编号后 index+1 = 2）。
- 不碰 `ai_calls` / `jobs` 的 CHECK。
- `fake_image_gen.py` + `smoke_mock` 路由，让 provider 在无 key 的 Mac 上测到可合并。
- 生成候选走 `Candidate` + `download_and_store`，复用 SSRF 与归一化；`license='generated'` 必须绕过 `select.rank` 的判断。

---

## 3. 横向对比（只列本角度关心的）

| 项 | evidence-first | pipeline-engineer | generation-first |
|---|---|---|---|
| 第一期是否有迁移 | 有，纯附加（4 × ADD COLUMN） | 无 | 无 |
| `word_images` 重建 | 第二期 0012（含 0011 四列） | 第二期（编号随合入顺序） | 第二期 0012，DDL 写全、逐列核对 ✓ |
| `user_settings.image_hint` | `ADD COLUMN` + `UPDATE CASE`，两用户结果写明 | 搭阶段模型的重建（不必要的耦合） | P3 附加列，未展开 |
| 迁移编号 | 0011（撞号，有顺延条款） | 0011（撞号，有顺延条款） | 0012 ✓ |
| `v_bank` / 触发器判断 | 正确 | 正确（「排练前要确认」） | 正确且写进文件头 |
| 索引值错位风险 | 以阶段码配置，`stage_to_index` 解析 ✓ | 整数阈值，`0` 哨兵在 Q1-b 失效 ✗ | `STAGE_ORDER.index('zk')+1` ✓ |
| 契约改动（第二期） | `gen`、`ImageMeta.text_free`、`Settings.image_hint`；**不改** `AdminOverviewWords` | `zhipu_image`、`ImageMeta.kind/hint_safe/style`、`Settings.image_hint`、`with_generated`（设计级） | `ai_image`、`ImageMeta.kind 'ai'`、`AdminOverviewWords.with_ai_image`、`RefetchImageRequest` |
| 红测清单完整性 | 完整 | 漏 `test_prompts_are_verbatim_from_section_5` ×2 | 漏 `test_api_schemas.py:113` |
| 版本标记落点 | 新列 `prompt_version` | `query='svg:v2'`（常量拼写自相矛盾） | `query='svg-v2'` |
| 第一期对线上行为 | zk 词链默认切插画优先（铺开） | 默认关，但 Openverse 多 `category=photograph` | zk 词链默认切插画优先（铺开） |
| 失败词重试 | 1 天最小间隔，无每词上限 | 6 h、30 天 ≤3 次、CLI 排练 ✓ | 24 h，无每词上限 |
| 回滚说明 | 代码回退 / 快照，分情况 ✓ | 第一期代码回退 + `.env` 兼容核过 ✓；第二期诚实 | 给出回滚前置 SQL ✓（首句措辞过强） |
| 排练 | `run_migrations`，验收 SQL | pytest 子集 + `images-retry --dry-run` | `VACUUM INTO` + `wd migrate --dry-run` + 验收 SQL ✓ |
| 种子/`import-seed` | 正确指出不需要 | 正确 | 正确 |
| `docs/SCHEMA.sql` | 不动 ✓ | 不动 ✓ | 不动 ✓ |

三份都没有触碰种子覆盖语义（`kv.seed_version`、20 列覆盖）、`difficulty` 尺子或 `words` 表 CHECK——这是正确的：配图线只读 `stage_min`。

---

## 4. 对最终方案的数据安全要求（评审意见，供整合者采用）

1. **第一期只允许附加迁移**（evidence-first 的四列），编号在合入时取下一个空号；版本标记一律写 `prompt_version` 列，不用 `query`。
2. **第二期重建 `word_images` 用 generation-first 的 DDL**（逐列核对过），单文件只改一个 CHECK；`image_hint` 走 `ADD COLUMN`，`UPDATE … CASE` 的常量按「阶段模型迁移是否已合入」两种情形各写一行，并在文件头注明依据的 `current_stage` 口径。
3. **「插画优先链」第一期默认关闭**，开关用阶段码集合（空 = 关），不用 0 哨兵；试点通过后再把默认改成 `xs,zk`。
4. **失败词重试加每词封顶**（30 天 ≤3 次）并把功能词/明确「card only」的词排除出夜间扫描。
5. **红测清单**合并三份并补齐：`test_prompts_are_verbatim_from_section_5[svg_system|content_system]`、`test_images.py:616`、`test_content_apply.py:81`、`test_budget.py:33`（若改 `ESTIMATES`）、`test_providers.py` 两处参数字典、`test_deploy_files.py:119` / `test_docs_contract.py:114`（每个新 Settings 字段）、第二期的 `test_api_schemas.py:108`（Settings）与 `:113`（若动 `AdminOverviewWords`）、`check_contract.py` 顺序、`zh.test.ts`/`zh.contract.test.ts`、前端 `ImageMeta` 夹具的 tsc。
6. **发布说明**写明：停服务 → `wd backup` → `wd migrate --dry-run` → `wd migrate` → 验收 SQL → 启动；回滚分「仅代码（无新 provider 行）」与「先跑 generation-first 的中和 SQL 或 `wd restore pre-migrate-*.db.gz`」两档；排练只用 `.venv/bin/python` 的 `run_migrations`。
7. 不要在图里注入任何 `<text>`；显式标识用 UI 题注，隐式标识用 `<desc>`/XMP，`text_free` 只由代码保证。

---

## 5. 结论

evidence-first 胜在「附加优先 + A6 规则写死 + 红测清单完整 + 契约克制」，是最适合做最终方案骨架的一份；它需要修两处：第一期默认关闭插画链、重试加封顶。generation-first 的 0012 DDL、排练与回滚 SQL、provider 链架构应整体嫁接；它自己则要补 `test_api_schemas.py:113`、删掉 `AI` 角标、修正 `quota.status` 的说法。pipeline-engineer 的「默认关、七个独立提交、重试封顶、CLI 排练」是好的工程纪律，但它对测试绑定的误判、0 哨兵与 Q1-b 的冲突、版本常量的自相矛盾，使它不适合直接作为合入依据。
