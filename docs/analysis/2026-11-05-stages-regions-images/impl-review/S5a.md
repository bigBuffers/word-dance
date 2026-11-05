# S5a `images-svg-content-v2` 实现评审（对抗式）

评审对象：工作区里 S5a 的 22 个文件（基线 `main @ 75df534`）——新文件 `backend/wd/images/style.py`、`backend/wd/migrations/0012_word_images_meta.sql`、`backend/tests/unit/test_style.py`、`backend/tests/unit/test_db_0012.py`；改动 `backend/wd/images/{sanitize_svg,store,select}.py`、`backend/wd/config.py`、`backend/wd/ai/{svg,content,budget}.py`、`backend/wd/ai/prompts/{svg_system,content_system}.txt`、`docs/{CLAUDE_INTEGRATION,AI_FALLBACK_MODEL,DEPLOY}.md`、`deploy/env.example`、`backend/tests/unit/{test_sanitize_svg,test_config,test_content_apply,test_select}.py`、`backend/tests/integration/test_images.py`。规格：PLAN §1 R-12/R-13/R-15、§2.3、§3.5、§3.6、§5.1 C1–C4、§5.2、§5.3、§6 S5（含 S2/S3 对 DEPLOY.md 的请求）；`design/images/SYNTHESIS.md` §3.1.1–3.1.6、§3.2、§3.3.3（`is_blocked`/`keyword_tokens` 的最小实现）、§4.1 C1–C4、§5.1/§5.2。

评审过程没有修改任何仓库文件：开始与结束时 `git diff | shasum -a 256` 相同（`8180110b…701ba`），`git status --short` 的未跟踪集合相同（期间只多了 S3 并行新增的 `data/lists/README.md`）；7 处突变试验都是「写坏 → 跑目标测试 → 按 sha256 逐字节恢复」。排练只用 `$SCRATCH/s5a-rehearsal/` 下的私有拷贝；没有启动 `wd serve`、没有跑 `make smoke`（S7 门禁）。

## 0 结论

**通过（无 blocker、无 major；7 条 minor，多为文档/风格与跨切片交接）。** 实现与 PLAN §2.3 / §5.1 C1–C4 / §5.2 / §3.5 逐条一致：`0012_word_images_meta.sql` 与 PLAN §2.3 代码块 `diff` 为空；`svg_system.txt` 与 PLAN §5.2 代码块 `diff` 为空，首字符为字母；`content_system.txt` 第 1 行与规则 1/3/5/6/7/8 的文字与 PLAN C4 / SYNTHESIS §3.2 逐字相同，`test_schemas.py` 两个 `test_prompts_are_verbatim_from_section_5` 参数绿。验收 pytest 236 passed；私有拷贝排练得到 27 列、`31|0|31`、`integrity_check ok`、`foreign_key_check` 空；假 claude 端到端得到 `claude_svg | svg-v2 | claude-sonnet-fake | 1`，文件 0 个 `<text`、恰 1 个 `aigc-label`、不含词头；对抗输入（`<text>` 藏在 `<defs>/<g>` 里、`<tspan>` 在 `<title>` 里、大写 `<TEXT>`、外命名空间 text、模型自带 `id=" aigc-label "`、根属性含 `>`、`&#X26;`/`&amp`/`&#38`）全部按设计处理；7 个人工突变全部被新测试抓住。没有发现旧卡被意外重生成的路径（§2.6）。

## 1 验收命令复跑

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q backend/tests/unit/test_sanitize_svg.py …test_style.py …test_config.py …test_content_apply.py …test_db_0012.py …test_schemas.py …test_docs_contract.py …test_select.py backend/tests/integration/test_images.py -k "not test_deploy_files and not test_defaults_without_environment"` | `236 passed, 1 deselected in 21.93s`，exit 0 |
| `M=$SCRATCH/s5a-rehearsal && rm -rf $M && mkdir -p $M && cp $SCRATCH/live-copy.db $M/word-dance.db && WD_DATA_DIR=$M .venv/bin/wd migrate --dry-run && WD_DATA_DIR=$M .venv/bin/wd migrate` | `--dry-run` 列出 `0011_primary_stage.sql`、`0012_word_images_meta.sql`、`0013_word_forms_alias.sql`（S1/S2 的文件也在工作区，与 PLAN §2.5 第 2 步一致）；`applied` 三个，`schema version 13` |
| `sqlite3 -readonly $M/word-dance.db "PRAGMA table_info(word_images); SELECT COUNT(*), SUM(text_free), SUM(prompt_version IS NULL) FROM word_images;"` | `/usr/bin/sqlite3 -readonly` 对这份 WAL 库报 `unable to open database file (14)`（只读打开需要 `-shm`，迁移后连接关闭时已删除）；改用 `.venv/bin/python -I` + `sqlite3.connect("file:…?mode=ro", uri=True)` 读回：**27 列**，末四列 `prompt_version, model, text_free, eval_json`；**`(31, 0, 31)`**；`schema_migrations` = 1/8/9/10/11/12/13；`journal_mode wal`、`integrity_check ok`、`foreign_key_check []`；`provider` 分布 `claude_svg 30 / wikimedia 1` |
| `WD_DATA_DIR=$M WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 WD_AI_ENABLED=1 WD_CLAUDE_BIN=backend/tests/fake_claude.py .venv/bin/wd fetch-image have --provider claude_svg && … wd worker-once` | 环境变量名与子命令都真实存在（`cli.py:183`、`handler.py:350-355`、`worker.py:394`、`smoke_mock.py:167`）。**按 PLAN 原文的相对路径跑会失败**：`claude spawn failed: [Errno 2] No such file or directory: 'backend/tests/fake_claude.py'`——`runner` 在 `$WD_DATA_DIR/claude-cwd` 里 spawn，相对路径解析不到；而且这次 `spawn_error` 把这份拷贝的 Claude 暂停到 +20 min（`kv.claude.paused_until`），必须重新 `cp` 才能继续（见 F-6）。重新拷贝、迁移并用绝对路径 `WD_CLAUDE_BIN=/Users/sqin/word-dance/backend/tests/fake_claude.py` 再跑：`fetch-image have` → `status: svg_queued`，`worker-once: processed 1 job(s)`；最新 `word_images` 行 **`(32, 818, 'claude_svg', 'svg-v2', 'claude-sonnet-fake', 1, None, '96/9604bd….svg', '一幅表示 have 的简单示意图', 'active')`**；文件 266 字节，`<text` 计数 **0**，`id="aigc-label"` 计数 **1**，文件里不含 `have`（假 claude 仍在 `<text>` 里印词头，被代码剥掉）；开头 `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><desc id="aigc-label">AI-generated illustration · word-Dance · claude-sonnet-fake · 2026-11-05</desc><rect …`；`words.have` → `image_state ready`、`active_image_id 32`；`ai_calls` 末行 `svg / claude-sonnet-fake / success`；job `generate_svg done {"cost_usd": 0.004, "image_id": 32}` |
| `.venv/bin/python -m pytest -q backend/tests/unit/test_deploy_files.py -k env_example` | `4 passed, 29 deselected`（Mac 上这个文件按设计失败的只是 install.sh/fetch_ecdict 干跑；`env.example` ↔ `Settings` 的两条镜像测试在 Mac 上可跑且绿） |
| `pytest backend/tests/unit/{test_providers,test_cli,test_scheduler,test_card_svg,test_budget,test_quota}.py`（验收集之外、与 S5a 改动相邻的单元测试） | `103 passed` |
| `.venv/bin/python scripts/check_contract.py` | `contract OK`（S5a 零契约改动，符合 §5.1「零 `schemas.py`/`types.ts`/`API.md §9` 改动」） |
| 全量后端 `pytest backend/tests -k "not test_deploy_files and not test_defaults_without_environment"` | 见 §1.1 |

### 1.1 全量后端套件

`.venv/bin/python -m pytest -q backend/tests -k "not test_deploy_files and not test_defaults_without_environment"` → **`6 failed, 1792 passed, 3 skipped, 34 deselected in 216.78s`**。六个红都不在 S5a 的文件里，也不是 S5a 引起的：

| 测试 | 断言 | 归属 |
|---|---|---|
| `integration/test_failover_flow.py::test_claude_cli_mode_keeps_todays_behaviour` | `['migration', 'claude_auth'] == ['claude_auth']` | 0011 按 PLAN §2.2 写入的 `system_events('migration')` 行——S1 评审（`impl-review/S1.md` §0）已记为交接缺口，路由 S7 |
| `unit/test_backup.py::test_integrity_failure_records_event_and_leaves_nothing` | `2 == 1`（`system_events` 行数） | 同上 |
| `unit/test_failover.py::test_never_triggers_change_nothing` | `1 == 0`（`system_events` 行数） | 同上 |
| `unit/test_runner.py::test_tier1_usage_error_falls_back_to_tier0_once_and_records_the_event` | `['migration', …, 'claude_flag_error'] == ['claude_flag_error']` | 同上 |
| `integration/test_health.py::test_lifespan_migrated_db_and_public_url_guess` | `62 == 60`（词数） | S2 的 `fixtures/mini_seed.jsonl` 60 → 62 条（PLAN §6 S2），这两个测试不在 S2 的 `files` 清单里——S2 评审 / S7 处理 |
| `integration/test_words.py::test_lookup_preview_shapes` | `62 == 60` | 同上 |

S5a 自己改动的 22 个文件所覆盖的测试（§1 第 1 行的 236 个 + 相邻的 103 个）全绿；`test_schemas.py`、`test_docs_contract.py`、`test_db.py::test_schema_file_is_byte_identical_to_docs_copy_when_present` 都在全量里通过（`docs/SCHEMA.sql` 未动）。

## 2 逐条核对

### 2.1 C1 文档数字

- `docs/CLAUDE_INTEGRATION.md:407`（§7 首段）：「an SVG call $0.0124 ($0.0140 per delivered card, 11.8 % rejected — 34 live calls measured on 2026-11-05 …)」；`:416`（SVG sub-cap 行）：「≈ 35–40 cards/day at the measured $0.0124/call; `ESTIMATES['svg']` stays 0.03 as the reservation margin」✓。`docs/DEPLOY.md:326`（§4 `WD_AI_SVG_DAILY_BUDGET_USD`）与 `:434`（§10 故障表）✓；`deploy/env.example:83` ✓；`backend/wd/ai/budget.py:273-274` 只改注释，`ESTIMATES["svg"]` 仍 0.03（`budget.py:29` 未动）✓。`grep "0\.028\|18 cards\|content-v1\|15–240"` 在 S5a 的四个文档与 `backend/wd/ai/` 下为 0 命中。
- `docs/DESIGN.md:28,518,550`、`docs/ops.md:198`、`docs/WORD_LIBRARY_CURATION.md:65,166,183` 仍是旧数字 / `content-v1`——PLAN 把它们归 S6（S5 的请求清单），不算 S5a 的缺口；`DESIGN.md:550` 的「≈ 18 cards/day at the measured $0.028」与 §9 对 v1 提示词的描述都要等 S6。

### 2.2 C2 迁移 0012 + store 四列

- `diff <(PLAN §2.3 代码块) backend/wd/migrations/0012_word_images_meta.sql` 为空（逐字节相同，含注释与行尾注释）。四条 `ALTER TABLE word_images ADD COLUMN`，无 DROP/RENAME/CREATE/PRAGMA/COMMIT/`schema_migrations`（`test_db_0012.py::test_0012_is_additive_and_numbered_after_the_stage_rebuild` 把这条钉住）。
- `store.activate(..., prompt_version=None, model=None, text_free=False, eval_json=None)`：INSERT 列清单追加四列，值 `1 if text_free else 0` ✓；`activate_candidate` 不传（照片行四列默认，`test_images.py:131` 断言 `(None, None, 0, None)`）✓。
- `test_db_0012.py`：0001 基线 + 2 行 `word_images`（一张照片、一张 v1 SVG）→ `run_migrations()` → `(12,'word_images_meta')` 已应用；列序 = 旧列 + 四列（没有重建）；`text_free` `NOT NULL DEFAULT 0 INTEGER`，其余 `TEXT` 可空；行与 id 不变；`(2, 0, 2)`；`words.active_image_id/image_state` 不变；`foreign_key_check` 空、`integrity_check ok`；`text_free=2` → `IntegrityError` 匹配 `CHECK`；可插 `'svg-v2'/'claude-sonnet-4-5'/1/'{"r1": 2}'`；25 张表不变；二次运行 `applied == []`。覆盖了 PLAN C2 列出的每一项。

### 2.3 C3 SVG v2

| 规格项 | 实现 | 结果 |
|---|---|---|
| `svg_system.txt` = PLAN §5.2 全文，首字符字母 | `diff` 为空；以 `\n` 结尾；`CLAUDE_INTEGRATION.md §5.5` 代码块逐字节同步（`test_schemas` 绿） | ✓ |
| `svg.py` 常量 `EXAMPLE_MAX=120 / HOOK_MAX=60 / HOOK_PREFIXES=("联想：","联想:") / SVG_PROMPT_VERSION="svg-v2" / STYLE_TEXT{kid,neutral}` | `svg.py:43-50`；`STYLE_TEXT` 两段文字与 SYNTHESIS §3.1.2 的 Python 字符串逐字相同 | ✓ |
| `build_user_prompt(display, meaning, concept, *, example="", hook="", style="neutral")`，保留 `for the word "…"`，空段省略，形状 `Scene: …。 Example sentence: "…" Memory hook: … Style: …` | `svg.py:57-78`；未知 style 回落 neutral；例句内的 `"` 换成 `'`；`test_images.py::test_svg_prompt_carries_scene_example_hook_and_style` 对整串做精确快照（neutral / kid / 无内容三种） | ✓ |
| `hook_from(mnemonic)`：前缀 → 去前缀、取到第一个句号、截 60 | `svg.py:81-92`；除「。」外也在 ASCII「.」处截断（F-5） | ✓（minor） |
| `prompt_for(conn, word, *, cfg)` 取 `examples[0].en` 与挂钩，style 由 `style_for` | `svg.py:95-105`；`cfg` 默认 `None` → neutral（F-2） | ✓（minor 偏离） |
| `handle_generate_svg` 传 `cfg`、`model=result.model_used`、`prompt_version`，`svg_repaired` 事件 | `svg.py:168,190-194`：`repairs = len(BARE_AMP_RE.findall(svg))`，`>0` 时 `ctx.log.info(..., extra={"event": "svg_repaired", "repairs": …})`；`__all__` 含 `SVG_PROMPT_VERSION` | ✓ |
| 模块文档串「never retried automatically」→ 重试规则 | `svg.py:16-17` | ✓（引用了尚未落地的 S5b 代码，F-3/F-4） |
| `sanitize_svg.BARE_AMP_RE` 在 `DET.fromstring` 前替换；`<!ENTITY` 仍先拒 | `sanitize_svg.py:67,91`：顺序 ENTITY 检查 → DOCTYPE/XML 声明去除 → 空文档检查 → `BARE_AMP_RE.sub("&amp;")` → 解析。对抗验证：`&#X26;`（大写 X 不是合法 XML CharRef）→ `&amp;#X26;`、`&amp`（无分号）→ `&amp;amp`、`&#38`（无分号）→ `&amp;#38`、`&lt;&gt;&quot;&apos;` 原样；`<!DOCTYPE … <!ENTITY xxe …>` 在 `allow_text` 两种取值下都 `SvgRejected("entity")`；裸 `<` 仍拒 | ✓ |
| `clean(svg, *, allow_text=True)`；`_serialise(..., allow_text)` 丢 `text/tspan` 子树，`title/desc` 保留 | `sanitize_svg.py:158-161,190-207`。对抗验证（`allow_text=False`）：`<defs><g><text>` 与三层 `<g>` 里的 `<text>` 连同 tail 一起消失（`<g>` 不是文本元素，tail 不输出）；`<title>T<tspan>X</tspan>Y</title>` → `<title>TY</title>`；`<TEXT>`、`<h:text>` 本来就不在允许表；根下 `<text>abandon</text>TAIL` → 两者都消失；默认 `allow_text=True` 行为不变（`"<text" in s.clean(svg)`） | ✓ |
| `with_label(cleaned, label)` 插恰一个 `<desc id="aigc-label">`；`_clean_attrs` 丢弃模型自带的该 id | `sanitize_svg.py:146-147,211-226`：`ROOT_TAG_RE = <svg\b[^>]*>` 对 `clean()` 输出安全（属性值经 `quoteattr`，`>` → `&gt;`，对抗验证 `role="a>b"` 通过）；空根 `<svg …/>` 展开；非 `clean()` 输出（`<html/>`、前导空格）→ `SvgRejected`；模型写 `id=" aigc-label "`（strip 后相等）被丢、`id="AIGC-LABEL"` 不算同名（大小写敏感，与「恰含一个 `id="aigc-label"`」的定义一致）；标签文本 `escape()`；`viewbox_size` 不受 `<desc>` 影响 | ✓ |
| `store.activate_svg(conn, cfg, word_id, svg, alt_zh, *, now=None, model=None, prompt_version=None)` = `clean(allow_text=False)` → `with_label("AI-generated illustration · word-Dance · {model or 'claude'} · {now[:10]}")` → `write_bytes` → `activate(provider="claude_svg", license="generated", text_free=True, …)` | `store.py:168-212`；`aigc_label()` 抽成函数；`now = now or now_iso()` 先于标签 | ✓ |
| `images/style.py`（§5.1 末段接口） | `STYLE_KID/STYLE_NEUTRAL/STYLES`；`FUNCTION_POS = {i,c,d,p,a,u,t}`（无 r、无 x，与 `frontend/src/utils/pos.ts` 一致）；`NO_BARE_LEMMA_POS = FUNCTION_POS | {"r"}`；`dominant_pos("n:4/v:96") == "v"`、平局取首个、`None`/`""`/`"v./n."`/`"abbr."`/`"n:"`/`"n:x/v:1"` → `None`；`skip_image`、`allows_bare_lemma`（未知 pos → True）；`stage_code`：`int` 经 `index_to_stage`（1 → `xs`，R-15），越界/`0`/`-1`/`99` → `None` 不抛，`str` 原样（`""` → `None`），`None`/`bool`/`float` → `None`；`style_for` = `kid` iff `stage_code(stage_min) in cfg.image_kid_stages`。`test_style.py` 对每条都有用例，`stage_code(1) == "xs"` 按 PLAN R-15 而不是 IM §5.2 的旧编号（实现者的裁定正确） | ✓ |
| `config.image_kid_stages: tuple[str, ...] = ()`；`WD_IMAGE_KID_STAGES` 解析（函数级 `from .schemas import STAGE_ORDER`，未知码 `ConfigError`，去重、小写、空白） | `config.py:158,372-387,542`；`entries()` 对 tuple 输出 `",".join`；`python -I -c "import wd.config; import wd.images.style; import wd.ai.svg; import wd.ai.content"` 与先导入 `wd.images.style` 都无循环导入 | ✓ |
| DEPLOY §4 行（`:339` 后）+ `env.example`（`:149-165` 段） | `DEPLOY.md:340`：以 PLAN §5.3 的原句开头「stage codes whose words get the child style and the illustration-first round (empty = off; set to `xs` after the pilot; `zk` is never in the default)」，后接取值与读取方式；`env.example:152-153` 紧跟 `WD_IMAGE_PROVIDERS`；`test_docs_contract.py` 与 `test_deploy_files.py -k env_example` 绿 | ✓ |
| `CLAUDE_INTEGRATION.md:281-285`（§5.5 新提示词 + 新用户提示词形状）、`:296-300`（§6.1 `generate_svg` 行加三列写入）、`:401-403`（§6.7：`clean(svg, allow_text=False)`、裸 `&` 修复、`<desc id="aigc-label">`、重试规则） | 三处都改了；§6.7 的 `zh.word.aiImage` 引用在 `zh.ts:54` 存在 | ✓ |

### 2.4 C4 content v2

- `content_system.txt`：15 行、`\n` 结尾、首字符字母；第 1 行受众 `(小学, 初中, 高中, CET-4, CET-6 and working professionals)`；规则 1/3/5 的追加句与 SYNTHESIS §3.2 逐字相同（程序比对 `endswith`）；规则 6/7 整条、规则 8 `(1 = 小学/初中 basic, 2 = 高中, 3 = CET-4, 4 = CET-6, 5 = beyond CET-6)` 与 PLAN C4 逐字相同；规则 2/4/9/10/11 不动。`CLAUDE_INTEGRATION.md §5.1` 代码块同步（`test_schemas` 绿），§5 标题 `content-v2`，§5.2 示例 audience = `content.AUDIENCE`，§6.4 `:355` 「10–240」，`AI_FALLBACK_MODEL.md:29` 「10–240 字符（content-v2 起下限 10，容纳小学短句）」。
- `content.py`：`PROMPT_VERSION = "content-v2"`；`AUDIENCE = "Chinese learners from primary school (小学) to CET-6, plus working professionals"`；`STAGE_ZH = schemas.STAGE_NAMES_ZH`（同一对象，`test_prompt_entry_labels_the_five_stages_from_schemas` 用 `is` 断言）；`EXAMPLE_EN_MIN, EXAMPLE_EN_MAX = 10, 240`（`validate_item` 用 `EXAMPLE_EN_MIN <= len(en)`，10 字符保留、9 字符丢弃有测试）；`_is_blocked(keyword, lemma) = select.is_blocked(keyword, allow=select.keyword_tokens(lemma))`，调用处 `:180` 传 `lemma`；`PREFIX_MIN = 4`、`KEYWORD_RE`、`ALT_MAX` 不动；`content_v1.json`、`claude_schemas.json` 不在 `git status` 里（未动）。`prompt_entry` 改为直接按 `schemas.STAGE_ORDER` 读旗标（F-1）。
- `test_content_apply.py:81` → `== content.PROMPT_VERSION == "content-v2"`；新增 `prompt_entry` 五阶段标签（含 `stage_xs=1` → 「小学」、缺旗标读 0、课标外 `[]`）、10–14 字符例句、lemma token 豁免（`map`/`apple`/`flag`/`weapon`/`gun` 五组 + `_is_blocked` 直接断言）。

### 2.5 `select.py` 最小实现（供 content.py；S5b 再扩展）

`UNSAFE_RE / NON_PHOTO_RE / KID_UNSAFE_RE` 三张表与 PLAN C5 的词项逐一相同（`test_blocklist_splits_into_unsafe_non_photo_and_kid_unsafe` 对每个词正反各断言一次）；`BLOCKLIST_RE` 删除且测试钉住 `not hasattr`；`is_blocked(text, *, allow=frozenset(), style="neutral")` 与 SYNTHESIS §3.3.3 伪代码逐行相同（UNSAFE 永远拒；kid 时 KID_UNSAFE 拒；NON_PHOTO 的每个命中都必须在 `allow` 里）；`keyword_tokens -> frozenset[str]`（`score()` 唯一的内部读者只做 `sum(... for tok in keyword_tokens(keyword))`，`handler.py` 不读它）。`reject_reason/score/rank` 仍用默认参数——与任务说明一致（S5b 穿线）。

### 2.6 旧卡会不会被意外重生成（PLAN C4「旧卡不 `force`」）

`PROMPT_VERSION` 提升后唯一读它做判断的地方是 `content.select_jobs` 的 `already_ready` 跳过（`content.py:411`：非 `force` 且 `content_state == 'ready'` 且活动卡 `prompt_version == PROMPT_VERSION` 才跳过）。所有非 `force` 的 `generate_content` 生产者都先判 `content_state`：`routers/words.py:319-323`（`ready`/`queued` 直接 200，不入队）、`bank.enqueue_content_if_needed` `:517`（不在 `('none','failed')` 就返回；`batches.py:359` 经它）、`scheduler.py:282`（prefetch SQL `content_state IN ('none','failed')`）、`prewarm.py:50,63`；`force` 的两处（`admin_ops.py:405` 管理员重生成、`admin_reports.py:54` 举报）本来就是有意重做。所以一张 v1 卡**不会**因为版本号变化而被重生成；唯一的边角是「部署前因预算延期的非 force 任务 + 同一词期间被管理员 force 重做」——部署后那条旧任务会多打一次（旧代码下它会被 `already_ready` 跳过），这是 `select_jobs` 文档串里「ready under the current prompt version」的既定语义，不是 S5a 引入的。没有任何代码按 `prompt_version != PROMPT_VERSION` 扫表入队。

### 2.7 S2/S3 对 DEPLOY.md 的请求

- S2：`:417` CLI 行 → `import-seed [--file PATH (default: WD_SEED_PATH)] [--force] [--dry-run] [--report PATH]` + 一句说明 ✓；`:304` `WD_SEED_PATH` 行「the content sha256 of the (gunzipped) file, so re-packing the same records with another gzip does not re-import」✓；§5 `wd migrate` 段加「`0011_primary_stage.sql` … 和 `0013_word_forms_alias.sql` … 是 **stop-first** — never under `--no-restart`，pre-migrate 快照是唯一回滚；`0012_word_images_meta.sql` 是 additive」✓，§10 的 `--no-restart` 句同步 ✓。
- S3：`:410` `make seed` 行改为 `build_seed.py --manifest … --previous … [--ecdict $(ECDICT_DB)] [--wordlists $(WORDLISTS_DIR)] --out data/seed → seed_diff.py → pack_seed.sh` ✓——但工作区里 `Makefile`/`scripts/build_seed.py` 尚未改（S3 未落地），参数名以 S3 的 Makefile 为准（N-2）。

## 3 突变试验（全部按 sha256 逐字节恢复；`git diff` 哈希前后相同）

| # | 写坏的地方 | 目标测试 | 结果 |
|---|---|---|---|
| 1 | `sanitize_svg._serialise` 去掉 `not allow_text and local in ("text","tspan")` 条件 | `test_sanitize_svg.py` + `test_images.py::test_activate_svg_sanitises_and_serves_a_svg_image` | 1 failed（`test_allow_text_false_drops_text_and_tspan_but_keeps_title_desc`），抓住 |
| 2 | `_clean_attrs` 不再丢弃 `id="aigc-label"` | `test_with_label_inserts_one_desc_after_root` | 1 failed，抓住 |
| 3 | `select.is_blocked` 忽略 `allow`（NON_PHOTO 一律拒） | `test_select.py` + `test_content_apply.py::test_lemma_token_is_exempt_in_image_keywords` | 1 failed（`test_non_photo_words_are_allowed_when_they_are_query_tokens`），抓住 |
| 4 | `config.from_env` 不再对未知阶段码抛 `ConfigError` | `test_config.py` | 4 failed（`test_image_kid_stages_parse_as_stage_codes` + 参数化 `test_invalid_values_raise_config_error` 的 `xx`、`xs,cet9`、`xs;zk`），抓住 |
| 5 | `style.stage_code` 对越界索引改为抛出 | `test_style.py` | 2 failed，抓住 |
| 6 | `store.activate_svg` 传 `text_free=False` | `test_images.py` 两条 SVG 测试 | 2 failed，抓住 |
| 7 | `content.EXAMPLE_EN_MIN` 改回 15 | `test_example_of_10_to_14_chars_is_now_kept` | 1 failed，抓住 |

没有发现被削弱的既有断言：`test_images.py:616` 的 `"<text" in stored` → `"<text" not in stored` 是 C3 的必然后果且 IM §5.1 明文要求；`test_select.py:142-143` 的列表断言改为 `frozenset` 等式是返回类型按 PLAN C5 变化的直接后果；`test_content_apply.py:81` 改为 `== content.PROMPT_VERSION == "content-v2"` 比 IM §5.1 建议的 `== content.PROMPT_VERSION` 更严。

## 4 Findings（按严重度）

| # | 严重度 | 文件 | 问题 | 证据 | 建议 |
|---|---|---|---|---|---|
| F-1 | minor | `backend/wd/ai/content.py:90-92` | `prompt_entry` 不再经 `words.stages_of(word)`，而是内联 `[STAGE_ZH[s] for s in schemas.STAGE_ORDER if int(word.get(f"stage_{s}") or 0)]`——旗标→阶段码的映射多了一份副本（R-1「不再保留任何副本」）。实现者的理由（`services/words.STAGES` 仍是四元组）在当前工作区已不成立：`services/words.py:41` 已是 `STAGES: tuple[str, ...] = STAGE_ORDER`，`stages_of` 与内联表达式逐字等价 | `git diff backend/wd/ai/content.py`；`sed -n 41p;233-234p backend/wd/services/words.py` | S7 合并后改回 `[STAGE_ZH[s] for s in words.stages_of(word)]`（测试 `test_prompt_entry_labels_the_five_stages_from_schemas` 不用改） |
| F-2 | minor | `backend/wd/ai/svg.py:95` | `prompt_for(conn, word, *, cfg: Settings \| None = None)`：PLAN C3 / SYNTHESIS §3.1.2 写的是必填 `cfg: Settings`。默认 `None` → neutral 是为了 S2 文件 `scripts/eval_provider.py:529` 的 `svg.prompt_for(conn, w)` 不红；处理器总是传 `cfg=ctx.cfg`，行为无差 | `svg.py:95-105`；`scripts/eval_provider.py:529` | 接受为过渡；S2/S7 让 `eval_provider.py` 传 `cfg=`（它已有 `Settings`）后把参数改回必填，避免将来新的调用点悄悄拿到 neutral |
| F-3 | minor | `backend/wd/images/style.py:6`、`backend/wd/ai/svg.py:17` | 生产代码文档串引用工作流切片名（「once S5b lands」「S5b」）；仓库惯例是引用文档章节 / PLAN 条目，切片名合并后无人能解 | `grep -n "S5b" backend/wd/images/style.py backend/wd/ai/svg.py` | 改为「PLAN §5.1 C8」「PLAN §5.1 C7 / DESIGN §9」 |
| F-4 | minor | `docs/CLAUDE_INTEGRATION.md:407`（§6.7 末句）、`backend/wd/ai/svg.py:16-17` | 已把失败词重试规则（nightly `retry_failed_studied`、≥ 6 h、≤ 3 次/30 天、`wd images-retry`）写成现状，而 `service.py`/`scheduler.py`/`cli.py` 里还没有这些代码（S5b）。PLAN §3.5 要求 §6.7 写重试规则，所以方向正确，但在 S5b 合入前文档先于代码 | `grep -rn "retry_failed_studied\|images-retry" backend/wd` 只命中文档串 | S7 门禁核对 S5b 是否落地；若 S5b 推迟，改回「retried by the failed-image retry rules (pending)」 |
| F-5 | minor | `backend/wd/ai/svg.py:87-90` | `hook_from` 除「。」外也在第一个 ASCII「.」处截断（PLAN：「取到第一个句号」）：`联想：3.5 米的长颈鹿` → `3`；`联想：像 U.S. 国旗` → `像 U`。挂钩只是提示，不影响正确性，但会把带小数 / 缩写的挂钩截成无意义片段 | `svg.py:88`：`for stop in ("。", "."):` | 只按「。」截断，或要求「.」后跟空白/行尾（`re.split(r"。|\.(?=\s|$)")`） |
| F-6 | minor | `docs/analysis/…/design/PLAN.md` §6 S5 验收、§7.4 | 验收命令用相对路径 `WD_CLAUDE_BIN=backend/tests/fake_claude.py`，但 `runner` 在 `$WD_DATA_DIR/claude-cwd` 里 spawn，实际报 `spawn_error` 并把那份拷贝的 Claude 暂停 20 分钟（`kv.claude.paused_until`）；实现者报告的成功结果只能是用绝对路径得到的 | §1 第 4 行的复跑记录 | S7 跑排练时用 `WD_CLAUDE_BIN=$PWD/backend/tests/fake_claude.py`，并在 PLAN/发布说明里订正；排练失败后要重新 `cp` 拷贝 |
| F-7 | minor | `backend/wd/images/sanitize_svg.py:91` | `BARE_AMP_RE` 作用于整份原文，也会改写 `<![CDATA[…]]>` 里本来合法的 `&`：`<title><![CDATA[a & b]]></title>` → `<title>a &amp;amp; b</title>`（title 文本变成字面 `a &amp; b`）。只影响 `<title>/<desc>` 文本（不渲染），模型几乎不写 CDATA | 对抗用例 `cdata amp` 的输出 | 可接受；若要严谨，替换前先把 CDATA 段摘出，或在文档串里注明「CDATA 不豁免」 |

## 5 Notes（不计入 findings）

- N-1 **C4 的 lemma 豁免目前到不了抓取链**：`images/handler.py:71 clean_keywords` 仍调用 `select.is_blocked(kw)`（无 `allow`），所以 `content.py` 为 `map` 保留的 `"world map"` 在 `fetch_for_word` 里会再次被滤掉，直到 S5b 按 PLAN C5 把 `clean_keywords(values, lemma, *, allow_lemma=True)` 穿线。这是 S5a/S5b 拆分的既定顺序，S7 应在 S5b 合入后用 `test_images.py` 的 `test_lemma_token_is_exempt_from_the_non_photo_blocklist`（IM §5.1 C5）确认端到端。
- N-2 `DEPLOY.md:410` 的 `make seed` 行描述的是 PLAN §4.5 的流水线，`Makefile:93-98` 与 `scripts/build_seed.py` 在工作区里还是旧的；S3 落地时以 Makefile 为准校对参数名（`--manifest/--previous/--ecdict/--wordlists/--out`）。
- N-3 `docs/DESIGN.md:28,518,550`、`docs/ops.md:198,202`、`docs/WORD_LIBRARY_CURATION.md:65,166,183` 的旧数字 / `content-v1` / v1 提示词描述按 PLAN 归 S6；`DESIGN.md:550` 现仍写「≈ 18 cards/day at the measured $0.028」。
- N-4 `word_images.model` 写的是 `result.model_used`（PLAN 原文），`modelUsage` 缺席时为 NULL（`content.py` 对 NOT NULL 的 `word_contents.model` 用 `model_used or model_requested`）；PLAN §5.3 期望线上 `model` 非空，S7 上线后用 `SELECT model FROM word_images WHERE prompt_version='svg-v2'` 复核一次。
- N-5 `/usr/bin/sqlite3 -readonly` 读迁移后的 WAL 拷贝会报 `unable to open database file (14)`（没有 `-shm` 时只读打开不能创建），PLAN §6 S5 / §7.3 的 `sqlite3 -readonly …` 命令在这种状态下要改用 `sqlite3 "file:…?mode=ro"` 或 Python `uri=True`。
- N-6 实现者报告的其余偏离——`test_images.py` 属 S5 的 `files` 清单（PLAN §6 S5），`stage_code(1) == "xs"` 按 R-15 修正 IM §5.2 的旧编号，`keyword_tokens` 返回 `frozenset` 使 `test_select.py:142-143` 改断言——都成立。
- N-7 `make smoke` 未跑（启动 `wd serve :8010`，S7 门禁）；`scripts/smoke.py` 里没有对 `<text` 或 SVG 文本的断言（`grep` 为空），C3 不会让它红。
