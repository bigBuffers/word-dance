# 最终评审 · 配图流水线 + AI 提示词 v2（对抗式）

评审对象：工作区全部改动（`git diff 75df534` + `git status` 新文件）里属于 PLAN §5.1 C1–C8 / §5.2 / §5.3 / §2.3 / §3.5 / §6 S5 的部分，以及其他切片里会影响配图行为的文件（`scheduler.py`、`cli.py`、`logging_setup.py`、`content.py`、`DESIGN.md §9`、`ops.md`、根 `ATTRIBUTION.md`）。规格：PLAN §0、§1（R-6/R-12/R-13/R-15/R-16）、§2.3、§3.5、§5、§6 S5/S7、§7；`design/images/SYNTHESIS.md` §3.1–3.3、§4.1、§5。只报告跑过命令或读过代码并能引用位置的问题。评审没有改动仓库里任何既有文件（本文件是任务指定的新增报告）；排练只用了 `$SCRATCH/live-copy.db` 的私有拷贝 `$SCRATCH/final-images-review/data/`（`VACUUM INTO`），没有触碰 `/Users/sqin/word-dance-data`，没有启动 `wd serve`。

## 0 结论

**通过。无 blocker；1 条按评审规则记为 major 的「文档与行为不符」（`docs/ops.md:205` 一句运维文案，改一句话即可）；5 条 minor。** PLAN §6 S5 的验收 pytest 节点复跑 `344 passed, 1 deselected`；相邻的 8 个测试文件 `107 passed`；`test_deploy_files.py -k env_example` 在 Mac 上单独跑 `4 passed`；`check_contract.py` `contract OK`。私有拷贝排练逐项命中 PLAN §6 S5 的期望值：`migrate --dry-run` 列出 0011/0012/0013 → `word_images` 27 列、`31 | 0 | 31`、integrity ok、fk 空 → `images-retry --dry-run` 17 个词（`employee` 不在学，无功能词）→ 假 claude `fetch-image have --provider claude_svg` + `worker-once` → 最新行 `claude_svg | svg-v2 | claude-sonnet-fake | 1`，文件 0 个 `<text`、恰 1 个 `aigc-label`、不含词头 → `fetch-image of --no-svg` → `skipped / function word: card only`（exit 0）；`despite`（线上带管理员 SVG）→ `function word: current image kept`，`image_state` 回 `ready`。三份字节绑定（`svg_system.txt` ↔ PLAN §5.2 ↔ CLAUDE_INTEGRATION §5.5；`content_system.txt` ↔ §5.1；SYNTHESIS §3.2 的 5 段规则文本逐段在文件里）全部一致；`EXAMPLE_EN_MIN == 10`、规则 8 `(1 = 小学/初中 basic, …)`、`PROMPT_VERSION == "content-v2"`、`AUDIENCE` 与 §5.2 示例相同。默认链（`WD_IMAGE_KID_STAGES` 空）请求形状对基线只多 `thumbmime`（iiprop）/`maxlag=5`/`page_size=10`——由 `test_default_chain_shape_is_unchanged_except_thumbmime_maxlag_page_size` 的整字典断言与本评审在排练库上的录制探针双重确认；`WD_IMAGE_KID_STAGES=xs` 时 `xs` 词 `cat`（导入新种子后 `stage_min=1`）先 `filetype:drawing` + `category=illustration`，再 `filetype:bitmap` + 无 category，`gk` 词只有一轮。旧 SVG / 旧卡不会被重生成（见 §3.8）。

## 1 验收命令复跑（本评审中执行）

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q backend/tests/unit/test_sanitize_svg.py backend/tests/unit/test_style.py backend/tests/unit/test_select.py backend/tests/unit/test_providers.py backend/tests/unit/test_config.py backend/tests/unit/test_cli.py backend/tests/unit/test_content_apply.py backend/tests/unit/test_scheduler.py backend/tests/unit/test_db_0012.py backend/tests/unit/test_schemas.py backend/tests/unit/test_docs_contract.py backend/tests/integration/test_images.py -k "not test_defaults_without_environment"`（= PLAN §6 S5 验收） | `344 passed, 1 deselected in 26.05s`，exit 0 |
| `pytest -q backend/tests/unit/test_card_svg.py test_quota.py test_budget.py test_api_schemas.py test_runner.py backend/tests/integration/test_admin_ops.py test_words.py test_media.py`（S5 清单之外、读 `word_images`/`image_meta`/预算的相邻文件） | `107 passed in 23.91s` |
| `pytest -q backend/tests/unit/test_deploy_files.py -k env_example` | `4 passed, 29 deselected`（`env.example ↔ Settings` 双向绑定与平台无关，单独跑绿；`WD_IMAGE_KID_STAGES=""` 在 `deploy/env.example:154`） |
| `.venv/bin/python scripts/check_contract.py` | `contract OK: no property-name or literal-union mismatch`（S5 零契约改动，`types.ts`/`API.md §9` 无 images 相关 diff） |
| 字节比对脚本（见 §3.1） | `svg_system.txt == PLAN §5.2` True · `== CI §5.5` True · `content_system.txt == CI §5.1` True · 首字符字母 True · 文件以 `\n` 结尾 |

## 2 私有拷贝排练（`M=$SCRATCH/final-images-review/data`，`WD_DATA_DIR=$M WD_SMOKE_MOCK_HTTP=1 WD_DEV=1`）

| 步骤 | 期望（PLAN §6 S5 / SYNTHESIS §5.3） | 实测 |
|---|---|---|
| `wd migrate --dry-run` | 列出 11、12（合并后还有 13） | `pending 0011_primary_stage.sql / 0012_word_images_meta.sql / 0013_word_forms_alias.sql` |
| `wd migrate` | 应用；快照 | `applied 0011/0012/0013`，`schema version 13`，`backups/pre-migrate-10-to-13.db.gz` |
| `PRAGMA table_info(word_images)`；`SELECT COUNT(*), SUM(text_free), SUM(prompt_version IS NULL)` | 27 列；`31 \| 0 \| 31` | 27 列，末四列 `prompt_version, model, text_free, eval_json`；`(31, 0, 31)`；`integrity_check ok`；`foreign_key_check []` |
| `wd images-retry --dry-run` | ≤ 17 词，无功能词 | `would requeue 17 failed-image word(s) … (limit 50; >= 6 h …, <= 3 …, function words excluded)`：property … species, have；`employee`（不在学）不在列；18 个 failed 词的 `pos` 全是 n/j/v/r，无功能词 |
| `WD_AI_ENABLED=1 WD_CLAUDE_BIN=backend/tests/fake_claude.py wd fetch-image have --provider claude_svg` → `wd worker-once` | `svg_queued` → 最新 `word_images` 行 `claude_svg \| svg-v2 \| <model> \| 1`；文件 `grep -c "<text"` 为 0 | `status: svg_queued`，job 137 `done {"cost_usd": 0.004, "image_id": 32}`；行 `(32, 818, 'claude_svg', 'svg-v2', 'claude-sonnet-fake', 1, '96/9604bd…svg', 'active')`；文件 `<text` 0、`id="aigc-label"` 1、`have` 不出现；开头 `<svg xmlns=… viewBox="0 0 800 500"><desc id="aigc-label">AI-generated illustration · word-Dance · claude-sonnet-fake · 2026-11-05</desc>`；`have` → `('ready', 32)`。相对路径 `WD_CLAUDE_BIN` 之所以能跑，依赖 `config.py:386-396` 的绝对化（见 §4 M-5） |
| `wd fetch-image of --no-svg` | `skipped, function word: card only`，无 provider 请求 | `status: skipped / detail: function word: card only`，exit 0；`of` → `('failed', None)`；`provider_usage` 无新增行 |
| `wd fetch-image despite --no-svg`（线上 `despite` 带管理员 SVG id 7） | 门不与活动图矛盾（S5b F-1） | `detail: function word: current image kept`，`despite` → `('ready', 7)` |
| `WD_IMAGE_KID_STAGES=xx wd migrate --dry-run` | `ConfigError` | `wd: configuration error: WD_IMAGE_KID_STAGES contains an unknown stage 'xx'; allowed: xs, zk, gk, cet4, cet6`，exit 2 |
| `WD_IMAGE_KID_STAGES="zk, gk"` → `Settings.from_env().image_kid_stages` / `entries()` | `("zk","gk")`；`entries()` 输出 | `('zk', 'gk')`；`{'key': 'WD_IMAGE_KID_STAGES', 'value': 'zk,gk', 'source': 'env'}` |
| `wd import-seed` 后，`WD_IMAGE_KID_STAGES=xs`，用录制 `httpx.MockTransport`（空结果）替换 `providers.base.make_client`，对 `cat`（`stage_min=1, stage_xs=1`）跑 `fetch_for_word` | 两轮：drawing+illustration → bitmap+无 category | 4 次请求依次：`commons cat filetype:drawing {iiprop:…thumbmime, maxlag:5}` · `openverse q=cat {page_size:10, category:illustration}` · `commons cat filetype:bitmap` · `openverse q=cat {page_size:10}`；`style_for == "kid"`；`search_rounds == (('kid', ('wikimedia','openverse')), ('neutral', ('wikimedia','openverse')))`。同配置下 `abandon`（`stage_min=3`）只有 `abandon filetype:bitmap` + 一次无 category 的 Openverse |
| 同一探针，`WD_IMAGE_KID_STAGES` 未设（默认） | 单轮 neutral；只多三项 | `commons cat filetype:bitmap` 参数整字典 = `{action, generator, gsrsearch, gsrnamespace 6, gsrlimit 10, prop imageinfo, iiprop url\|extmetadata\|size\|mime\|thumbmime, iiurlwidth 800, format json, maxlag 5}`；`openverse {q, page_size 10, license_type commercial, mature false}`；无 `category`、无 `orientation` |
| 门的覆盖面（导入新种子后） | PLAN §5.1 复算：二级 505 在库 498，门覆盖 65 | `stage_xs=1` 600 行：`skip_image` 67、`allows_bare_lemma` 为假（含副词）99、`pos` 空 30（词组/人称形式，不触发门——R-6） |

## 3 逐项核对

### 3.1 提示词字节绑定（PLAN §3.5、§5.2、R-12）

- 脚本提取 PLAN §5.2 的 ``` 块、`CLAUDE_INTEGRATION.md` §5.5 / §5.1 的 ``` 块，与 `backend/wd/ai/prompts/{svg,content}_system.txt` 做 `rstrip("\n")` 后比较：三处全部 True；`svg_system.txt` 首字符 `P`（`test_schemas.py:123` 的字母要求），4 行、无 `<text`/`tspan` 元素许可。
- SYNTHESIS §3.2 列出的 5 段文本（规则 1 末句、规则 3 末两句、规则 5 末句、规则 6 整条、规则 7 整条）逐段 `in` 文件为 True；第 1 行受众 `(小学, 初中, 高中, CET-4, CET-6 and working professionals)`、规则 8 `(1 = 小学/初中 basic, 2 = 高中, 3 = CET-4, 4 = CET-6, 5 = beyond CET-6)` 与 PLAN §5.1 C4 一致。
- `content.py:47-55`：`PROMPT_VERSION = "content-v2"`、`AUDIENCE = "Chinese learners from primary school (小学) to CET-6, plus working professionals"`（= §5.2 示例 `audience`）、`STAGE_ZH = schemas.STAGE_NAMES_ZH`、`EXAMPLE_EN_MIN, EXAMPLE_EN_MAX = 10, 240`、`PREFIX_MIN = 4` 不动；`_is_blocked(keyword, lemma) = select.is_blocked(keyword, allow=select.keyword_tokens(lemma))`（`:68-71`），调用处 `:180`。`prompt_entry` 的 `stages` 经 `words.stages_of`（`STAGES = schemas.STAGE_ORDER`）取 `STAGE_NAMES_ZH`，`stage_xs=1` → 「小学」（`test_prompt_entry_labels_the_five_stages_from_schemas`）。`content_v1.json` 与 `fixtures/claude_schemas.json` 不在 diff 里（`test_schemas.py` 30 条绿）。
- 文档：§5 标题 `content-v2` / `svg-v2`、§5.2 示例 audience 与新增 `apple` 行、§5.5 用户提示词形状、§6.1 `generate_svg` 行加三列、§6.4 「10–240」、§6.7 全段、§7 `$0.0124 / $0.0140 / 35–40`；`AI_FALLBACK_MODEL.md:29` 「10–240」；仓库内（`docs/`、`deploy/`、`backend/wd`、`README`、`ATTRIBUTION`）再无 `0.028` / `18 cards`。

### 3.2 SVG v2：无文字由代码保证、裸 `&`、`aigc-label` 恰一个、四列写入（C2/C3）

- `store.activate_svg`（`store.py:173-213`）：`clean(svg, allow_text=False)` → `with_label(cleaned, aigc_label(model, now))` → `write_bytes` → `activate(provider="claude_svg", license="generated", prompt_version=…, model=…, text_free=True)`。`activate`（`:82-136`）的 INSERT 列清单含 `prompt_version, model, text_free, eval_json`；`activate_candidate` 不传 → 照片 `text_free=0`、`prompt_version/model/eval_json` NULL。
- `sanitize_svg._serialise`（`:174-177`）：`not allow_text and local in ("text","tspan")` → 连子树丢弃；`<title>`/`<desc>` 仍是 `TEXT_ELEMENTS`。评审探针：含 `<text>word<tspan>x</tspan></text>tail` 的 SVG → 输出无 `<text`，`tail` 也不出现（非文本模式下 tail 不输出）。
- 裸 `&`：`BARE_AMP_RE`（`:68`）= PLAN 正则；`repair_bare_ampersands`（`:85-96`）在 `ENTITY_RE` 拒绝与 DOCTYPE/XML 声明去除之后、`DET.fromstring` 之前执行（`_parse :101-109`），且跳过 `<![CDATA[…]]>`（PLAN 之外的精化，正确：CDATA 里的 `&` 本就是字符数据，修了会变成字面 `&amp;`）。探针：`&nbsp;x&#;y&#xZZ;z&amp q` → `&amp;nbsp;x&amp;#;y&amp;#xZZ;z&amp;amp q` 通过；`fill="url(#a&b)"` 通过且该属性被 `LOCAL_URL_RE` 丢弃（安全）；`<!ENTITY` 仍先被拒（`test_entities_still_rejected_after_repair`）。
- `aigc-label`：`with_label`（`:227-242`）用 `ROOT_TAG_RE = <svg\b[^>]*>` 匹配 `clean()` 输出的根标签（属性值经 `quoteattr` 转义，`>` 不会出现在属性里——探针 `<title>A > B & C</title>` 正常）；空根 `<svg …/>` 也处理。`_clean_attrs :158-159` 丢弃模型自带的 `id == "aigc-label"`（元素上任意位置）；探针里模型写的 `<g id="aigc-label">` 与 `<desc id="aigc-label">` 都失去 id，输出恰 1 个 `id="aigc-label"`。存储文件由 `routers/media.py:46-47` `FileResponse` 原样下发，仓库内没有任何对存储 SVG 再 `clean()` 的调用（`clean_svg` 只在 `images/__init__.py` 导出，无调用者），所以标识不会在服务时被剥掉。
- 迁移 `0012_word_images_meta.sql` 与 PLAN §2.3 全文一致（含注释）；`test_db_0012.py` 覆盖 0001 基线插 2 行 → `run_migrations` → 四列类型/默认/NOT NULL、行与 id 不变、CHECK 拒 2、25 张表不变、二次运行空、文件只含 4 条 `ALTER TABLE … ADD COLUMN`。
- `ai/svg.py`：`EXAMPLE_MAX=120`、`HOOK_MAX=60`、`HOOK_PREFIXES`、`SVG_PROMPT_VERSION="svg-v2"`、`STYLE_TEXT{kid,neutral}` 字面与 SYNTHESIS §3.1.2 / CI §5.5 相同；`build_user_prompt` 保留 `for the word "…"`（`fake_claude.py:160-161` 依赖，排练里假 claude 正确读出 `have`）；`handle_generate_svg :169/:195` 传 `cfg`、`model=result.model_used`、`prompt_version=SVG_PROMPT_VERSION`；`svg_repaired` 事件 `:191-194`（计数口径见 M-2）。

### 3.3 功能词门与各分支（C5）

`handler.fetch_for_word :221-301`：SELECT 加 `kind, pos, stage_min`；`explicit = provider or query`；`not explicit and style.skip_image(word)` → `set_image_state(failed|ready)` + `skipped "function word: card only" | "current image kept"`，不触 provider、不入队 SVG（排练 `of`/`despite`；`test_function_word_without_admin_override…` 断言 `mock_http.calls == []` 且无 `generate_svg`）。管理员 `query`：`clean_keywords([query], lemma, allow_lemma=False)`，被丢弃 → `log.warning(event=query_ignored)` + `detail` 前缀 `query ignored (shape/blocklist)`，继续内容关键词，API 仍 202（`test_admin_query_dropped_by_shape_rule_is_reported` 四种情形）。副词：`allows_bare_lemma` 假 → 无可用关键词时 `keywords=[]` → 跳过 provider 轮直接到 SVG/卡片判定（`test_adverb_without_content_keywords_skips_the_bare_lemma_search`）。`style.dominant_pos` 探针：`n:4/v:96→v`、`n:50/v:50→n`、`None/""/"v./n."/"abbr."/"n:100/"→None`（不触发门）、`i:100`/`p:1/d:99` 触发；线上库 `pos` 全部是 `[a-z]*:[0-9]*` 形状、无多余斜杠（只读查询 0 行）。

### 3.4 黑名单三分与 lemma 豁免（C5）

`select.py:32-34` 三个正则与 PLAN 逐字相同；`is_blocked(text, *, allow, style)`：UNSAFE 恒拒、KID_UNSAFE 仅 kid、NON_PHOTO 每个命中词都须在 `allow` 里；`keyword_tokens` ≥ 3 字母去停用词（`map/flag/text/scan/logo` 都 ≥ 3）。探针：`is_blocked("Map of Europe", allow={"map"})` False、无 allow True、`"beer garden"` kid True / neutral False、`"coat of arms…"` 多词组永不豁免 True。`clean_keywords(["bar chart","red apple"], "apple") → (['red apple'], ['bar chart'])`、`(["bar chart"], "chart") → (['bar chart'], [])`、`(["world map"], "apple", allow_lemma=False) → ([], ['world map'])`。`BLOCKLIST_RE` 已删除（仅 `test_select.py:159` 断言其不存在）。`rank(... allow=keyword_tokens(kw), style=round)`（`handler._search_round :194`）与 `reject_reason` 透传一致。打分五信号（`select.score :131-164`）与 `test_score_table` 原断言并存；`media_category` 处理 Pixabay `vector/svg`（门禁修复）。

### 3.5 provider 风格参数、默认链形状、maxlag、thumbmime（C8）

- `interfaces.ImageProvider.search(self, query, limit, *, style="neutral")`；四个 provider 签名一致（`test_every_provider_implements_the_style_keyword`）。
- Commons：`FILETYPE_BY_STYLE`、`iiprop … thumbmime`、`maxlag: 5`；`search` 用 `base.get_json_with_headers`，`error.code == "maxlag"` → `ProviderError(status=503, retry_after_s=Retry-After or 30)`；`handler._search_round :166-170` 对 503 走 `quota.cooldown(… cooldown_seconds(p.name, e) …)`，`quota.cooldown_seconds :113-116` 优先 `retry_after_s`（`test_wikimedia_maxlag_body_puts_commons_in_cooldown…`：`cooldown_until = +7 s` / 无头 `+30 s`，请求计数 +1，链转 Openverse）。`parse_search :114` `mime = thumbmime or mime or 扩展名`；kid 轮的 SVG 原件 → `image/png` 过 MIME 门（`test_wikimedia_kid_style_uses_drawing_and_thumbmime_as_candidate_mime`）；`fetch.download_and_store` 只认 JPEG/PNG/WEBP 魔数并重编码为 JPEG，PNG 缩略图可下载。
- Openverse：`PAGE_SIZE` 删除，`page_size = max(1, min(limit, 20))` = 10，kid 加 `category=illustration`，`extra["category"]` 解析；Pixabay `IMAGE_TYPE_BY_STYLE`；Pexels 签名透传、`KID_ROUND_EXCLUDED_PROVIDERS=("pexels",)`；neutral 轮无 `category=photograph`、无新增 `orientation`（Pexels 的 `orientation=landscape` 是基线既有）。
- `search_rounds :133-142` = PLAN 的 `rounds` 表达式；空 kid 轮（纯 Pexels 链）`continue`（门禁 S5b 精化）；`PREWARM_SKIP_PROVIDERS` 于 `priority >= 90` 跳过（`test_prewarm_priority_skips_openverse_pixabay_and_pexels`）。

### 3.6 失败词重试（C7，R-16 不做即时挂点）

`service.py:36-40` 四常量 = PLAN；`retry_due`：`failed` ∧ 非功能词 ∧ 无 live `fetch_image`（`dedupe_key = image:<id>` 或 `LIKE image:<id>:r%`，不会前缀撞 `image:12`）∧ 上次结束 ≥ 6 h（`MAX(COALESCE(finished_at, updated_at))`，全库时间戳统一 `YYYY-MM-DDTHH:MM:SSZ`，字符串比较安全）∧ 30 天内 `payload.retry = true` 的行 < 3。计数能工作的前提是每次重试都是新行：`ux_jobs_dedupe_live` 是 `status IN ('queued','running')` 的部分唯一索引，`queue.enqueue` 的 UPSERT 只对 live 行冲突（`queue.py:86-108`），终态行不会被复用；仓库内没有 `DELETE FROM jobs`，计数不会被 GC 清零。`retry_failed_studied` SELECT 口径、`ORDER BY updated_at, id`、`limit`、`dry_run` 与 PLAN 一致；`enqueue_fetch(retry=True)` 写 `payload["retry"]=True`，`handle_fetch_image` 忽略该键；`merge_fetch_payloads` 不合并 `retry`（无 live 任务时才会入队，所以无影响）。`scheduler.retry_failed_images` 在 `prefetch` 之后、`requeue_dead_once` 之前，`images_enabled=0` 时返回 0（否则词会卡在 `queued`）；`TickResult.image_retries`、`cmd_tick` 打印、`EXTRA_FIELDS` 加 `word_ids`；CLI `images-retry` 注册 + `COMMAND_OWNERS`。`bank.py`/`batches.py` 无 `retry_if_failed` 调用（R-16 ✓）。测试 `test_failed_word_is_retried…`（1 h 不重抓、6 h 重抓、live 阻塞、功能词永不、从未抓过立即可）、`test_retry_is_capped_at_three_per_thirty_days`（第 4 次拒、手动 换一张 不计数、31 天后归零）、`test_nightly_retry_requeues_only_studied_failed_words_within_limit`（在学过滤、顺序、limit、dry_run、优先级 30）、`test_cli_images_retry_dry_run_lists_candidates`、`test_maintenance_requeues_failed_image_words_being_studied` 全绿。

### 3.7 配置与文档（C1/C3，R-13）

`config.py:158` `image_kid_stages: tuple[str, ...] = ()`；`:372-385` 解析（函数级 `from .schemas import STAGE_ORDER`，未知码 `ConfigError`，去重、小写）；`:553` 构造；`entries()` 输出 `WD_IMAGE_KID_STAGES`。`docs/DEPLOY.md:340` 一行含 PLAN §5.3 的原句「stage codes whose words get the child style and the illustration-first round (empty = off; set to `xs` after the pilot; `zk` is never in the default)」；`:420` 命令清单含 `images-retry [--limit N] [--dry-run]`；`deploy/env.example:153-154`。`budget.py:273-274` 只改注释，`ESTIMATES["svg"]` 0.03 不动。根 `ATTRIBUTION.md:50/55/65`（`filetype:drawing`、`maxlag`、`category=illustration`、「图内不含文字 + `<desc id="aigc-label">`」）；`DESIGN.md:556-586` 伪代码含门/两轮/重试、三张表与豁免规则、`WD_IMAGE_KID_STAGES`；`ops.md:205/209`；`WORD_LIBRARY_CURATION.md:65` 「当前 `content.PROMPT_VERSION`（`content-v2`）」（`:166` 的 `content-v1` 是线上库快照事实，保留正确）。

### 3.8 旧 SVG / 旧卡不被重生成

- 旧 SVG：`generate_svg` 只由 `fetch_for_word` 在 `not has_active` 时入队（`handler.py:291-294`），`handle_generate_svg` 非 `requested` 时两次检查 `_has_active_image` 后跳过；夜间重试只选 `image_state='failed'`（线上 30 个 v1 SVG 全是 `ready`）；`requeue_dead_once` 只复活 `generate_content`/`lookup_word`。0012 让这 30 行 `text_free=0`、`prompt_version NULL`，与 PLAN §2.3 注释一致（排练 `31 | 0 | 31`）。
- 旧卡：`PROMPT_VERSION` 升到 `content-v2` 后 `select_jobs` 的 `already_ready` 只对「`ready` 且版本相同」生效，但全部 6 个 `generate_content` 生产者都先按 `content_state` 把关：`bank.enqueue_content_if_needed :517`（`none|failed`）、`batches._enqueue_content_for`（经 bank）、`scheduler.prefetch :283-284`（`IN ('none','failed')`）、`prewarm.py:5/165`（同）、`routers/words.py:320-323`（`ready|queued` 直接 200 返回现状）、`lookup.py`（只对缺内容的最终词）；只有管理员显式 `regenerate`（`admin_ops.py:405`、`admin_reports.py:54`）带 `force` 走 `content:<id>:r<n>`。`DESIGN.md:541` 「Cards generated under `content-v1` are not regenerated; the admin's 重新生成 does it per word」与行为一致。

## 4 问题清单

| # | 严重度 | 位置 | 问题 | 证据 | 修法 |
|---|---|---|---|---|---|
| M-1 | **major**（按本次评审规则「文档与行为不符」归类；影响只是一句运维文案，不阻塞上线） | `docs/ops.md:205` | 「Function words … are card-only by design and never retried; **the admin's 换一张** / `refetch-image {provider:"claude_svg"}` still works per word」——换一张（API 29 `request_refresh`，无 `provider`/`query`）和不带覆盖项的 `refetch-image` 对功能词**不会**抓图：门只被显式 `provider`/`query` 绕过 | `handler.py:227-228` `explicit = bool(provider) or bool(query…)`；`test_function_word_with_an_active_image_keeps_it_and_stays_ready`：`request_refresh` → `skipped "function word: current image kept"`，`mock_http.calls == []`；排练 `fetch-image despite --no-svg` 同样 | 改为「the admin's `refetch-image` with a `provider` or `query` (e.g. `{provider:"claude_svg"}`) still works per word; 换一张 keeps the card」 |
| M-2 | minor | `backend/wd/ai/svg.py:191-194` | `svg_repaired` 事件的 `repairs = len(BARE_AMP_RE.findall(svg))` 把 `<![CDATA[…]]>` 里（`repair_bare_ampersands` 刻意不修）的 `&` 也算进去，且在 `activate_svg` 之前计数——被拒的 SVG 也会先记一条 `svg_repaired` | 探针：`<desc><![CDATA[a & b]]></desc><title>c & d</title>` → `findall` 2，实际只修 1 | 在 `sanitize_svg` 暴露 `count_bare_ampersands(text)`（与 `repair_bare_ampersands` 同一 CDATA 切分），`activate_svg` 成功后再记日志 |
| M-3 | minor（既有缺口，与 C7 相邻） | `backend/wd/images/handler.py:323-332`、`backend/wd/images/service.py:331` | `fetch_image` 任务异常 3 次后 `queue.fail` 置 `dead`，没有任何 on_dead 把 `words.image_state` 从 `queued` 改回；夜间重试只选 `failed`，`requeue_dead_once` 又只复活 content/lookup——这样的词会永远停在 `queued` + 模板卡，无 live 任务、无自愈路径 | `queue.py:173-190` 无回调；`grep image_state = 'failed'` 只有 `handler.py:247,299` 与 `svg.py:120`；线上副本目前 `queued` 0 行（failed 18 / none 9113 / ready 31），所以不是现状问题 | `handle_fetch_image` 在 `queue.fail(...) == "dead"` 时调用 `store.set_image_state(conn, word_id, STATUS_FAILED)`（无活动图时），对齐 `svg._on_dead`，让 C7 规则接管；不在 PLAN 范围，可随 R-16 小提交一起做 |
| M-4 | minor | `backend/wd/logging_setup.py:20-34`、`backend/wd/images/handler.py:260` | `query_ignored` 的 `extra={"word_id": …}` 不在 `EXTRA_FIELDS`，JSON/纯文本两种格式器都不会输出它（消息正文里有 `for word %d`，信息不丢） | `logging_setup.py:48-51/60` 只遍历 `EXTRA_FIELDS` | 把 `word_id` 加进 `EXTRA_FIELDS`，或去掉这个 extra |
| M-5 | minor（出 PLAN 范围、已文档化、有测试） | `backend/wd/config.py:386-396`、`docs/DEPLOY.md:317` | `WD_CLAUDE_BIN` 含路径分隔符时按启动工作目录绝对化——不在 PLAN §5.1 C1–C8，也不在门禁「Fix-only changes」清单里；它是 PLAN §6 S5 排练命令 `WD_CLAUDE_BIN=backend/tests/fake_claude.py` 能跑的前提（CLI 在 `claude_cwd` 里 spawn）。语义变化：相对路径现在相对服务启动目录而非子进程 cwd 解析；Mac 线上 `.env` 指向绝对路径 `/Users/sqin/word-dance-data/bin/claude-wrapper`（memory `claude-cli-macos-needs-login-env`），不受影响 | `test_config.py`/`test_docs_contract.py` 绿；排练 `have --provider claude_svg` 成功即依赖此改动 | 在门禁/发布说明里补记这条「配置语义微调」，并在 `docs/releases/2026-11-k12-stages.md` 提一句 |
| M-6 | minor | `backend/wd/ai/svg.py:97` | `prompt_for(conn, word, *, cfg: Settings \| None = None)`，PLAN §5.1 C3 / SYNTHESIS §3.1.2 的签名是 `cfg` 必填；可选默认让漏传 `cfg` 的未来调用者静默得到 neutral | `handle_generate_svg :169` 正确传了 `cfg`，`test_svg_prompt_carries_scene_example_hook_and_style` 还专门断言 `prompt_for(conn, word) == neutral` | 要么把 `cfg` 改回必填并删掉那条断言，要么在 SYNTHESIS 里把可选写成设计 |

## 5 核对过、未发现问题的对抗假设

- `with_label` 幂等：对已带标识的文件再 `clean()` + `with_label()`，旧 `<desc>` 失去 id、文本保留，输出仍恰 1 个 `id="aigc-label"`（无再清洗调用方，纯防御核对）。
- `thumbmime` 在 neutral 轮的副作用：TIFF/XCF 原件的 JPEG/PNG 缩略图现在能过 MIME 门（以前按原件 MIME 拒）——是 PLAN 明示的 `mime = thumbmime or mime`，下载的本来就是缩略图，`fetch.sniff_mime` 再把关。
- kid 轮的尺寸门用原件 `width/height`（SVG 名义尺寸）而非 `thumbwidth`：PLAN 说「尺寸门槛 400×300 不放宽」并把 `MIN_SIZE_KID` 留给试点门槛 ⑤，按设计。
- `UNSAFE_RE` 含 `blood/gun/sex` 这类真实词：lemma 为 `blood` 时 Claude 关键词全被拒 → `[lemma]` 裸搜 → 候选标题含 blood 的全被拒 → 多半落到 SVG；基线 `BLOCKLIST_RE` 已如此，PLAN 规定 UNSAFE 恒拒，不是回归。
- 夜间 50 次重试 × SVG：优先级 30 < 90 可入队 `generate_svg`，受 `WD_AI_SVG_DAILY_BUDGET_USD` 子上限与 Openverse 日配额（`quota.py`）双重约束。
- `ROOT_TAG_RE` 对属性值含 `>` 的根标签：`quoteattr` 转义为 `&gt;`，探针通过。
- `auto_retries_30d` 的 `json_extract(payload_json,'$.retry') = 1`：`dump_payload` 写 `true`，SQLite `json_extract` 返回 1；`'$.word_id'` 为整数。
- `fake_claude.py` 仍输出带词头的 `<text>`：正好验证「无文字由代码保证」（排练文件 0 个 `<text`、不含 `have`）。
- `maxlag` 参数不破坏 `WD_SMOKE_MOCK_HTTP`（按主机/路径匹配，门禁 `make smoke` 28 步通过；排练里 `fetch-image` 走 mock 无报错）。

## 6 评审方法与状态

- 读：PLAN §0/§1/§2.3/§3.5/§5/§6/§7、SYNTHESIS §3.0–3.3/§4.1/§5；`images/{handler,select,service,store,sanitize_svg,style}.py`、`providers/*`、`interfaces.py`、`ai/{svg,content}.py`、两份提示词、`config.py`/`scheduler.py`/`cli.py`/`logging_setup.py`/`budget.py` 的 diff、`0012`、`jobs/queue.py`（UPSERT/`fail`）、`clock.py`、`quota.py`、`routers/media.py`、6 个 `generate_content` 生产者、`CLAUDE_INTEGRATION.md` diff、`DEPLOY/ops/DESIGN/ATTRIBUTION/AI_FALLBACK_MODEL/WORD_LIBRARY_CURATION` 相关行、`test_images.py` 新增 16 条与 `test_providers.py`/`test_db_0012.py`/`test_config.py` 的新增断言。
- 跑：§1 的 5 组命令；§2 的 12 步排练（私有拷贝，`import-seed` 也只在拷贝上）；§3.2–3.4 的 Python 探针（`sanitize_svg`、`style`、`select`、`clean_keywords`）。
- 状态：评审未修改任何既有文件（`git status --short` 的修改/新增集合与开始时一致，本报告位于已是未跟踪目录的 `impl-review/`）；临时产物只在 `$SCRATCH/final-images-review/` 与 `$SCRATCH/final-images-s5-pytest.log`。
