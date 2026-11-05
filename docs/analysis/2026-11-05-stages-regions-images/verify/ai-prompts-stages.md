# verify: ai-prompts-stages — 对 `facts/ai-prompts-stages.md` 的对抗性核验

> 日期 2026-11-05 · 仓库 `/Users/sqin/word-dance` @ `75df534`（`git status --short` 只有未跟踪的 `docs/analysis/2026-11-05-stages-regions-images/`）· 只读，未改任何代码 · 核验者 slug `verify-ai-prompts-stages` · 默认立场：怀疑

## 范围与方法

- **被核验文件**：`docs/analysis/2026-11-05-stages-regions-images/facts/ai-prompts-stages.md`（16 条结论，全部逐条复核，不止任务要求的 12 条）。
- **重新打开并按当前 HEAD 核对行号的代码**（全部用 `cat -n` / `sed -n` / `grep -n` 读原文，不信任原文件的行号）：`backend/wd/ai/prompts/{content_system,lookup_system,consolidate_system,svg_system}.txt`；`backend/wd/ai/schemas/{content_v1,lookup_v1,consolidate_v1,svg_v1,probe_v1}.json`；`backend/wd/ai/{content,models,lookup,consolidate,svg,runner,prewarm,failover,common}.py`；`backend/wd/ai/providers/openai_http.py`；`backend/wd/jobs/{queue,scheduler}.py`；`backend/wd/services/{words,bank,batches,stats,suggestions}.py`；`backend/wd/schemas.py`；`backend/wd/routers/{vocab,words,admin_reports}.py`；`backend/wd/config.py`；`backend/wd/migrations/0001_init.sql`；`backend/wd/images/{handler,select,card_svg}.py` 与 `images/providers/{wikimedia,pexels,openverse,pixabay}.py`；`frontend/src/api/{types,endpoints}.ts`、`components/study/{StudyCard,WordImage}.tsx`、`pages/{WordDetailPage,VocabPage,WelcomePage}.tsx`、`components/bank/SuggestionRow.tsx`、`i18n/zh.ts`；测试 `backend/tests/unit/{test_content_apply,test_schemas,test_claude_fixtures,test_consolidate_apply}.py`、`backend/tests/fake_claude.py`、`backend/tests/fixtures/claude_content_ok.json`；`scripts/eval_provider.py`、`scripts/build_seed.py`。
- **重新读过的文档行**：`docs/CLAUDE_INTEGRATION.md:230-238,352-358`；`docs/API.md:1-5,167-171,302-310`；`docs/WORD_LIBRARY_CURATION.md:94-98,113-117,181-185`；`docs/AI_FALLBACK_MODEL.md:7-11,60-64,141-145`；`docs/analysis/2026-11-04-ai-fallback/{harness-report.md:115-119,judge-J3-quality-terms.md:65-69,facts/contract.md:53-57}`。
- **全库 grep**（`grep -rn`，范围 `backend/wd frontend/src scripts docs/*.md`，另做一次排除 `node_modules/.git/docs/analysis/dist` 的全仓库搜索）：`STAGE_ZH`、`stages_of`、`difficulty`、`image_alt_zh|image_keywords`、`-i -E 'syllab|phonics|自然拼读|音节'`、`-i -E '小学|primary school|elementary'`、`BETWEEN 1 AND [45]|Literal\[1, 2, 3, 4`、`safesearch|mature`、`generate_content.*priority`。
- **数据**：`sqlite3 -readonly /private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/live-copy.db`（5,644,288 字节）上重算原文件的每一个数字，并补查 `bank_suggestions`、`consolidation_runs`、`user_words`；夹具计数用 `python3 -I`。
- **git**：`git log --oneline -- backend/wd/ai/prompts backend/wd/ai/schemas`。
- **联网**：无。原文件是「读代码」类型、未引用任何 URL，任务第 4 点（一手来源 / 年份 / 词与词条口径）不适用；本文也未下载任何文件。
- **判定口径**：行号偏差 ≤ 3 行且语义正确 → 「确认」并注明准确行号；陈述与代码或数据不符 → 「修正」；结论整体不成立 → 「推翻」。数字一律写出 SQL 或公式。

---

## 逐条核验

### [ai-prompts-stages-1] 阶段只以每词的中文标签列表进入 content 提示词 — **确认**（置信度高）

- `backend/wd/ai/prompts/content_system.txt:1` 原文 “an English vocabulary app for Chinese learners (初中, 高中, CET-4, CET-6 and working professionals)”；`:6` 唯一与水平相关的句子 “Avoid rare vocabulary above the learner's level”，确无 level 定义、无分阶段规则。
- `backend/wd/ai/content.py:48` `AUDIENCE = "Chinese learners, junior high school to CET-6, plus working professionals"`；`:49` `STAGE_ZH = {"zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}`；`:88` `"stages": [STAGE_ZH[s] for s in words.stages_of(word)]`；`:97` `json.dumps({"audience": AUDIENCE, "words": entries}, ensure_ascii=False)`。`dictionary_hint` 在 `:73-79`，`prompt_entry` 在 `:82-92`，行号全部准确。
- `backend/wd/services/words.py:228-229` `def stages_of(row)` → `[s for s in STAGES if int(row.get(f"stage_{s}") or 0)]`，累积标签属实；`backend/tests/unit/test_content_apply.py:255` 断言 `"stages": ["初中", "高中", "四级"]` 属实。
- `grep -rn STAGE_ZH backend scripts frontend/src` → 仅 `content.py:49`（定义）与 `:88`（唯一使用）。属实。
- 补充（作者未提，见遗漏 1）：`backend/wd/schemas.py:52` 有一份内容相同的 `STAGE_NAMES_ZH`，与 `content.STAGE_ZH` 是两份平行映射。

### [ai-prompts-stages-2] 一个 group 可以混合阶段；分组只按优先级/时间 — **确认**（置信度高）

- `backend/wd/ai/content.py:374-409` `select_jobs` 只做六类跳过（`:377` 文档字符串列出 `missing_word/merged/unvalidated/invalid_word/already_ready/superseded_regenerate`），无重排。
- `backend/wd/jobs/queue.py:129` `def claim_batch`，两条 SQL 均 `ORDER BY priority, run_after, id`（head 查询与 `UPDATE … WHERE id IN (SELECT … LIMIT ?)`），只按 `payload.group_size` 收缩，无 stage 条件。
- `backend/wd/config.py:115` `ai_batch_size: int = 10`；`:483` `clamped("WD_AI_BATCH_SIZE", 10, 1, 12)`；`backend/wd/ai/schemas/content_v1.json:1` `"maxItems":12`；`:144` `ai_fallback_batch_size: int = 5`。`group_cap` 实际在 `backend/wd/ai/failover.py:318-328`（作者写 :319-326，指函数体，可忽略）：`return max(1, min(batch, fallback_batch))`。补充旁证：`backend/tests/unit/test_schemas.py:76-79` 把 `maxItems ≥ 12` 与 `WD_AI_BATCH_SIZE` 钳制上限 12 绑定。
- `backend/wd/ai/prewarm.py:29` `PRIORITY = 90`、`:32-33` `STAGE_COLUMNS/STAGES`、`:36-39` `_stage_sql`、`:42-54` `candidates`、`:163` `ctx.enqueue(conn, "generate_content", {"word_id": wid, "plan_id": plan_id}, dedupe_key=f"content:{wid}", priority=PRIORITY, …)`。属实。
- 「用户触发的 10/20/30 优先级」属实：`backend/wd/routers/words.py:32` `CONTENT_REQUEST_PRIORITY = 10`，`backend/wd/services/bank.py:54-55` `CONTENT_PRIORITY_WAITING = 10 / CONTENT_PRIORITY_BANK = 20`，`backend/wd/services/batches.py:45` `CONTENT_PRIORITY_BATCH = 20`，`backend/wd/jobs/scheduler.py:245` prefetch “priority-30”。
- `docs/CLAUDE_INTEGRATION.md:234-235` 示例确为 `abandon` 带 `["高中","四级","六级"]`、`GDP` 带 `[]`。`content.py:447` `runner.load_prompt("content_system")`；`backend/wd/ai/runner.py:100-103` `@lru_cache` + `load_prompt`。推断成立。

### [ai-prompts-stages-3] lookup / consolidate / svg 不携带阶段；lookup 的 difficulty 无刻度 — **确认**（置信度高）

- `backend/wd/ai/lookup.py:68-70` `build_user_prompt(strings)` 只有 `json.dumps({"items": strings})`；`lookup_system.txt:6` 原文 “difficulty 1–5.” 无图例；`backend/wd/ai/schemas/lookup_v1.json:11` `"difficulty":{"type":"integer","enum":[1,2,3,4,5]}` 连 description 都没有（其它字段都有）。
- `content_system.txt:11` “(1 = 初中 basic, 2 = 高中, 3 = CET-4, 4 = CET-6, 5 = beyond CET-6)”；`consolidate_system.txt:11` “(1 初中 … 5 beyond CET-6)”；`:10` “use empty strings and difficulty 3 when nothing is needed”。
- `backend/wd/ai/consolidate.py:118` `def prompt_item`，`:124` `"difficulty": row.get("difficulty")`（可为 None）。
- `backend/wd/ai/svg.py:32-33` `CONCEPT_MAX = 60 / MEANING_MAX = 60`；`:40-45` `build_user_prompt`，`:48-52` `prompt_for`：`concept = str(content.get("image_alt_zh") or meaning)`；`svg_system.txt:1` 只有 “simple, flat-style educational illustration”，无年龄/阶段措辞。属实。

### [ai-prompts-stages-4] 备选模型收到相同提示词，只在系统提示词末尾追加 JSON 指令 — **确认**（置信度高）

- `backend/wd/ai/providers/openai_http.py:174-180` `compose_system`：`json_schema` → `base + JSON_SCHEMA_SUFFIX`，否则 `base + JSON_OBJECT_SUFFIX + runner.schema_arg(schema)`；`:75-79` 两个后缀常量原文属实。
- `:677-678` `{"role": "system", "content": compose_system(system_prompt, schema, json_mode)}, {"role": "user", "content": user_prompt}`；`grep -n user_prompt openai_http.py` 只有 `:620`（参数）与 `:678`（原样放入），没有任何改写。`backend/wd/ai/common.py:153-183,261-329` `claude_call` 把 `system_prompt/user_prompt` 原样传给两条腿。
- 唯一补充：修复轮（`:741`）会在原 messages 后追加 assistant + 修复请求两条消息，首轮提示词与 Claude 完全相同——作者结论不受影响。

### [ai-prompts-stages-5] 例句 8–20 词 vs 后验证 15–240 字符；小学短句会撞 `EXAMPLE_EN_MIN=15` — **确认**（事实高 / 推断中）

- `content_system.txt:6` 原文含 “8–20 words each”、“not textbook-stilted, not literary”、“Vary the register across the set (daily life, workplace, academic, news)”。
- `content_v1.json:6` examples 仅 `minItems 0 / maxItems 4` + `required ["en","zh"]`；`backend/tests/unit/test_schemas.py:23` `FORBIDDEN_KEYWORDS = {"$ref", "additionalProperties", "minLength", "maxLength", "minimum", "maximum", …}`（`:22` 为 ALLOWED）。
- `content.py:54` `EXAMPLE_EN_MIN, EXAMPLE_EN_MAX = 15, 240`；`:153` `if not (EXAMPLE_EN_MIN <= len(en) <= EXAMPLE_EN_MAX) or common.ascii_ratio(en) < EXAMPLE_ASCII_MIN: continue`；`:162` `required = EXAMPLES_MIN_LAST_ATTEMPT if last_attempt else EXAMPLES_MIN`，`:164` `return None, f"retry: …"`。`docs/CLAUDE_INTEGRATION.md:355` 原文 “keep those with `en` 15–240 chars”。
- 数字重算（SQL 同作者）：`SELECT COUNT(*), MIN(length(json_extract(e.value,'$.en'))), ROUND(AVG(…),1), MAX(…) FROM word_contents wc, json_each(wc.content_json,'$.examples') e WHERE wc.status='active'` → `195|33|54.6|86`；词数 `length(en)-length(replace(en,' ',''))+1` → `6|9.39|14`。与原文一致。
- 字符数复核：“I like cats.” = 1+1+4+1+5 = 12；“I am a boy.” = 1+1+2+1+1+1+4 = 11，均 < 15，属实。

### [ai-prompts-stages-6] 词汇控制只有一句软要求，无词表校验 — **确认**（置信度高）

- `content.py:131-203` `validate_item` 全文读过：检查项为 word 匹配（`:134-136`）、valid 布尔（`:137-138`）、meaning_zh 长度/CJK（`:139-141`）、meaning_en（`:142-144`）、例句长度/ASCII/CJK/词头（`:153-157`）、搭配（`:165-171`）、助记（`:172`）、关键词正则+屏蔽词（`:173-184`）、alt（`:185`）、difficulty 1–5（`:186-188`）。没有任何词表比对。
- `SELECT SUM(stage_zk) FROM words` → 2099，与原文「2,099 词」一致。

### [ai-prompts-stages-7] 释义口吻 / 助记 / 搭配三项都在提示词层可解 — **确认**（置信度高）

- `content_system.txt:4` “Chinese-dictionary style, e.g. "v. 放弃；抛弃  n. 放纵". At most 80 characters”；`content.py:52` `MEANING_ZH_MAX = 120`，`:139-141` 仅要求非空 + 含 CJK。注意 `backend/wd/ai/common.py:72-73` `clean_text` 超长是**截断**（`s = s[:max_len].rstrip()`）而非拒绝，所以 80（提示词）与 120（后验证）之间只是软/硬上限之别。
- `content_system.txt:8` “if you use a playful association instead, start with "联想："… Empty string if nothing useful”；`content.py:59` `MNEMONIC_MAX = 100`，`:172` 截断。数字重算：`SELECT SUM(json_extract(content_json,'$.mnemonic_zh') LIKE '联想%'), SUM(json_extract(content_json,'$.mnemonic_zh')='') FROM word_contents WHERE status='active'` → `8|2`，一致。
- 前端：`frontend/src/components/study/StudyCard.tsx:254` `{content.mnemonic_zh && (`、`:242` `{content.collocations.length > 0 && (`；`frontend/src/pages/WordDetailPage.tsx:476` 与 `:464` 同样条件。`content_v1.json:7` `collocations … maxItems 4`，`:12` 在 `required` 内；`content_system.txt:7` “Empty array if none are common”；`content.py:165-171` 接受空数组。属实。

### [ai-prompts-stages-8] 音节/自然拼读与「小学」概念在代码、提示词、文档中为零 — **修正**（结论成立，但所述 grep 结果不实）

- 原文：“`grep -rn -i "syllab|phonics|自然拼读|音节"` 遍历 `backend/wd`、`frontend/src`、`docs/*.md`、`scripts` → 0 命中”。
- 复核：`grep -rn -i -E 'syllab|phonics|自然拼读|音节' backend/wd frontend/src scripts docs/*.md` → **10 处命中**，全部在 `scripts/build_seed.py`（`:6` “mahavivo/english-wordlists syllabus lists”、`:11` “Each stage set = ECDICT tag ∪ official syllabus list.”、`:81` `syllabus = {`、`:113` `cet4_set = {w.lower() for w in syllabus["cet4"]}` 等），`syllab` 匹配的是 **syllabus（考纲）**，与音节无关。正确说法：**没有任何音节 / 自然拼读 / phonics 相关的代码、字段或文案；`syllab` 这个模式会命中 `syllabus`，需排除后才是 0。** 作者的「0 命中」要么是用了未加 `-E` 的 BRE（`|` 被当字面量，整句匹配不到任何东西），要么漏报。
- 第二条 grep 属实：`grep -rn -i -E '小学|primary school|elementary'` 在同范围 → 0；再排除 `node_modules/.git/docs/analysis/dist` 搜整个仓库 → 0。
- `lookup.py:347-349` `clean_phonetic(item.get("phonetic"), max_len=60)` → 只在 `words.phonetic` 为空时写入，属实。
- 语义结论（无音节/拼读能力，要加就是新字段）**成立**；只修正证据陈述。

### [ai-prompts-stages-9] 「小学」在 difficulty 刻度上没有位置；1–5 被写死在多处 — **确认**（置信度高），并补两处作者未列的硬编码

- 逐处复核属实：`content_system.txt:11`、`consolidate_system.txt:11`；`content_v1.json:11`、`lookup_v1.json:11`、`consolidate_v1.json:8,11` 均 `enum [1,2,3,4,5]`；`backend/wd/ai/models.py:44,61,76,90` `Literal[1, 2, 3, 4, 5]`；`backend/wd/schemas.py:47` `Difficulty = Literal[1, 2, 3, 4, 5]`、`:559` `difficulty: Difficulty`；`frontend/src/api/types.ts:73` `difficulty: 1 | 2 | 3 | 4 | 5`；`backend/wd/migrations/0001_init.sql:195` `difficulty INTEGER CHECK (difficulty BETWEEN 1 AND 5), -- 1 初中 … 4 六级, 5 beyond`；`:148` `current_stage … CHECK (current_stage BETWEEN 1 AND 4)`；`content.py:187-188`；`test_content_apply.py:245`；`backend/wd/routers/vocab.py:78` `"difficulty": "COALESCE(w.difficulty, w.stage_min, 5), …"`；`docs/API.md:169` 同；`schemas.py:56-67` `stage_to_index/index_to_stage`（`:65` `if not 1 <= int(index) <= 4`）。
- 作者漏列的同类硬编码（`grep -rn -E 'BETWEEN 1 AND [45]|Literal\[1, 2, 3, 4' backend/wd`）：`backend/wd/schemas.py:26` `StageIndex = Literal[1, 2, 3, 4]`、`backend/wd/migrations/0001_init.sql:185` `stage_min INTEGER CHECK (stage_min BETWEEN 1 AND 4)`。作者把这些归入「阶段模型切片」，可以接受，但「约 12 个文件」的估算应把这两处与遗漏 1 的前端常量计入。
- 「1=初中=zk … 4=六级=cet6 对齐」有注释直接证据：`0001_init.sql:148` “1=zk 2=gk 3=cet4 4=cet6”、`:195` “1 初中 … 4 六级”。

### [ai-prompts-stages-10] 改提示词不改 `PROMPT_VERSION` 老卡不受影响；改了也不会自动重做 — **确认**（置信度高）

- `content.py:46` `PROMPT_VERSION = "content-v1"`。`git log --oneline -- backend/wd/ai/prompts backend/wd/ai/schemas` → 只有 `a0ef789`（WP5），四份提示词与五份 schema 自首次提交从未改过，属实。
- `content.py:405-406` `if not job.payload.get("force") and word.get("content_state") == "ready" and _active_prompt_version(conn, word) == PROMPT_VERSION: _skip(… "already_ready")`。
- `backend/wd/services/bank.py:483` `def enqueue_content_if_needed`，`:489-492` 两道门（`is_valid_english != 1` / `content_state not in ("none","failed")` → `return None`）；`backend/wd/ai/prewarm.py:48` `content_state IN ('none','failed')`；`docs/WORD_LIBRARY_CURATION.md:115` 原文「**提升 PROMPT_VERSION 不会让任何词重新入队**，全库刷新只能逐词 force」。
- `content.py:230-234` `if force or word.get("difficulty") is None: UPDATE words SET … difficulty = ?`；`test_content_apply.py:193-198`（`:198` “force refreshes the difficulty”）。
- 「老卡片 49 张全是 cet4/cet6 词」：`SELECT SUM(stage_zk), SUM(stage_gk), SUM(stage_cet4), SUM(stage_cet6) FROM words WHERE content_state='ready'` → `1|1|49|47`。49 张全部带 cet4 标志（47 张兼 cet6），其中 1 张同时是 zk 词、1 张同时是 gk 词；表述成立，精确说法是「全部是四级词」。

### [ai-prompts-stages-11] ≤3 字母短词只认精确形式与 `word_forms` — **确认**（事实高 / 推断中）

- `content.py:63` `PREFIX_MIN = 4`；`:117-128` `contains_headword`：`:120` needles = lemma/display/forms；`:124` `if len(lemma) >= PREFIX_MIN:`，`:125` `prefix = lemma.lower()[:max(PREFIX_MIN, len(lemma) - 3)]`。3 字母词确无前缀分支。`forms` 来源：`content.py:338` `words.forms_of(conn, int(word["id"]))` → `words.py:370-372` 读 `word_forms`。
- 数字重算（SQL 同作者）：长度分布 `1|1|1`、`2|30|14`、`3|309|23`、`4|946|58`；`stage_zk=1 AND kind='word' AND NOT EXISTS word_forms` → 260（其中 ≤3 字母 31 个：`… AND length(lemma) <= 3` → 31）；`word_forms` 共 14,132 行，kind 分布 `s 4366 / p 3024 / 3 3111 / i 2943 / t 313 / r 305 / d 70`（`alt` 0 行）。按词频前 20 个无屈折 zk 词：`the/of/a/to/it/that/for/you/he/with/on/this/they/but/we/his/from/not/by/she`——与作者「多为功能词」判断一致。全部一致。

### [ai-prompts-stages-12] 已有 `image_keywords` 与 `image_alt_zh` 两个图意字段，均被配图流水线消费 — **确认**（置信度高）

- 定义：`content_system.txt:9-10`、`content_v1.json:9-10`（`image_keywords minItems 1 maxItems 4`）；后验证 `content.py:61` `KEYWORD_RE = ^[A-Za-z][A-Za-z ,'-]{1,40}$`、`:173-184`（`:183-184` 全滤掉 → `[lemma]`）、`:62` `ALT_MAX = 60`、`:185`；屏蔽词表 `backend/wd/images/select.py:40-42` `is_blocked`。
- 消费：`backend/wd/images/handler.py:4` “keywords = query or content.image_keywords[:3] or [lemma]”；`:64-80` `clean_keywords`（作者写 :65-80）；`:131-137` `alt_zh = content["image_alt_zh"].strip()[:200]`、`keywords = clean_keywords(content.image_keywords …)`；`:186` `store.activate_candidate(…, alt_zh=alt_zh, …)` 确把它存入 `word_images`。`svg.py:51` `concept = content.get("image_alt_zh") or meaning`。前端 `WordImage.tsx:16-17`、`StudyCard.tsx:306`、`WordDetailPage.tsx:447` `alt={content?.image_alt_zh ?? null}`。`backend/wd/images/card_svg.py:82-96` `render` 只取 `meaning_zh` 与 `examples[0].en`。`grep -rn -E 'image_alt_zh|image_keywords'` 在 backend/frontend/scripts 没有其它消费点。
- 数字重算：`MAX(length(json_extract(content_json,'$.image_alt_zh')))` → 20（MIN 10）；关键词条数分布 `json_array_length(content_json,'$.image_keywords')` → `1 条:2 / 2 条:8 / 3 条:39`；`particularly` → `["one red apple"]`，`have` → `["holding keys in hand","person holding book","family having dinner"]`。全部一致。

### [ai-prompts-stages-13] 给 content 增加一个字段的代价清单 — **确认**（清单高 / 工作量中），并补上两条使清单「必改」成立的硬证据

- `content_v1.json:12` `required` 列出 10 键；`models.py:15-18` `Mirror … ConfigDict(extra="ignore")`，`:34-44` `ContentItem` 10 字段；`models.py:123` `model.model_validate(item).model_dump()` → 未声明键在 `valid_items` 被丢弃，属实。`content.py:189-201` cleaned 字典显式 10 键。`schemas.py:549-563` `Content` 14 字段全部无默认值；`types.ts:70-74`；`docs/API.md:304-308`，`API.md:3` “Any change requires updating `schemas.py`, `types.ts` and this file in one commit.”
- 测试：`test_content_apply.py:80` 断言 14 键集合；`claude_content_ok.json` `structured_output.items` 长度 10（`python3 -I` 计数）；`test_claude_fixtures.py:46-53`；`fake_claude.py:170-199` `content_item`；`scripts/eval_provider.py:115` `CONTENT_ITEM_KEYS`。
- 「缺键或多键 → 500」的代码依据（作者只引了文档 `WORD_LIBRARY_CURATION.md:183`）：`backend/wd/schemas.py:87-90` `class Model(BaseModel): … model_config = ConfigDict(extra="forbid")`——多键被拒、缺必填键被拒，所以新字段在 `schemas.Content` 上必须 `Optional` 带默认，结论成立。
- 清单还应加一条（见遗漏 2）：`backend/tests/unit/test_schemas.py:56-62` 要求 schema 文件与 `docs/CLAUDE_INTEGRATION.md` §4.1 代码块**逐字节相等**（`:59` `assert text.rstrip("\n") == doc_block(...)`）且等于 `backend/tests/fixtures/claude_schemas.json[name]`（`:61`）。

### [ai-prompts-stages-14] 9,113 词 difficulty 为空；49 个非空值即 49 个有内容的词，全由 `store_content` 写入 — **确认**（置信度高），且「全由 store_content 写入」从推断升级为有数据支持

- 数字重算：`SELECT COUNT(*), SUM(difficulty IS NULL), SUM(difficulty IS NOT NULL) FROM words` → `9162|9113|49`；分布 `NULL 9113 / 1:2 / 2:1 / 3:43 / 4:3`；`content_state` `none 9113 / ready 49`；`word_contents` 49 行 `active|content-v1|claude-sonnet-5-5`；`ai_calls` `content|success` 10 次、`SUM(word_count)` 49，`content|auth` 12 次；`SELECT COUNT(*) FROM words WHERE difficulty IS NOT NULL AND content_state='ready'` → 49。
- 一致性：`SUM(difficulty = stage_min), SUM(<), SUM(>)` → `44|2|3`；偏低 `suddenly 2 vs 3`、`writer 1 vs 3`，偏高 `executive/republican/senate 4 vs 3`；5/49 = 10.2%，「10%」属实。
- 「全部由 store_content 写入」：补查 `SELECT type, status, COUNT(*) FROM bank_suggestions GROUP BY 1,2` → 只有 `confusable_group|accepted|6`，**没有任何 `difficulty` 类型的建议行**；`consolidation_runs` 4 次 `done` 的 `summary_json` 全部 `"auto_applied": 0`。因此 lookup/consolidate 两条写入路径在线上从未写过 difficulty，结论由数据直接支持。
- 四条写入路径行号：`content.py:230-234` ✓；`lookup.py:353-355` `if word.get("difficulty") is None and … 1 <= difficulty <= 5` ✓；`consolidate.py:263-266` `_fill_data` 开头 `if word is None or word.get("source") == "seed": return False`（「非种子词」属实），`:282-285` `… and difficulty != 3`（忽略哨兵 3 属实）；`consolidate.py:308-327` `_difficulty_tag` 的 SQL `UPDATE words SET difficulty = ? … WHERE id = ? AND difficulty IS NULL` 无 source 条件，调用方 `:451-459` 也无 source/provider 门控；`test_consolidate_apply.py:313` `a["difficulty"] == 1`（种子词 apple）；`docs/WORD_LIBRARY_CURATION.md:96`「给任何词（含种子词）写 `difficulty`」。「7 天可撤销」：`lookup.py:62` `AUTO_EXPIRES = timedelta(days=7)`，`0001_init.sql:447` type CHECK 含 `'difficulty'`，`services/suggestions.py:44` `RESTORABLE_WORD_COLUMNS` 含 `difficulty`。

### [ai-prompts-stages-15] `difficulty` 的读者只有排序与夜间整理条件 — **修正**（事实部分确认；「每晚持续开销」的推断需修正）

- 事实部分确认：`grep -rn difficulty backend/wd --include='*.py'`（排除 ai/ 写入模块）→ 逻辑读者只有 `routers/vocab.py:78`（ORDER BY）与 `jobs/scheduler.py:237`（`_bank_needs_consolidation`，函数在 `:229-240`）；其余是 DTO 透传（`services/words.py:282`）、插入时置 NULL（`words.py:584,592,595`）、撤销恢复（`suggestions.py:44`）、类型声明（`schemas.py:44,477,492,559`）。前端：`frontend/src/pages/VocabPage.tsx:31` `SORTS`、`i18n/zh.ts:48` `difficulty: '难度'`、`api/endpoints.ts:133`、`types.ts:53,73,128`、`SuggestionRow.tsx:30-32`，没有任何对 `difficulty` 值的渲染，属实。`consolidate.py:77` `select_items`、`:87` `… OR w.difficulty IS NULL)`、`:46` `MAX_ITEMS = 80`；`batches.py:232-234,270,694`、`stats.py:173-185`、`prewarm.py:36-39` 都只用 `stage_*`。
- 需修正的推断：原文「任何加入生词库的种子词都会**每晚**进入整理提示词，直到某次 `difficulty_tags` 把它填上……这是一笔持续的 Claude/备选调用开销」。遗漏了另一条填充路径：加入生词库本身就会入队 `generate_content`（`bank.py:636,659` 调 `enqueue_content_if_needed`，优先级 10/20），成功后 `store_content`（`content.py:230-234`）当场写入 `difficulty`，通常早于当晚的整理；只有内容生成失败/未跑（AI 关闭、预算耗尽、死任务）的词才会落入夜间 `difficulty IS NULL` 条件。线上副本印证：`SELECT COUNT(*) FROM user_words uw JOIN words w ON w.id=uw.word_id WHERE uw.state IN ('new','learning') AND w.difficulty IS NULL` → **0**（活跃生词 18 条）；19 次 `consolidation_runs` 中 `done 4 / failed 3 / skipped 12（"deferred"）`，`done` 的 4 次 `auto_applied` 均为 0。正确说法：**机制存在，但只在内容生成失败或滞后时才产生重复整理开销；当前线上没有一条处于该状态。** 这同时回答了原文「未解决的问题 4」。

### [ai-prompts-stages-16] 备选模型对小学例句是否更可靠：没有证据 — **确认**（置信度高）

- `docs/AI_FALLBACK_MODEL.md:9` 原文「没有任何国产模型被真正调用过（没有 key、不花钱）」；`:143`「……没有真实厂商被调用过」；`docs/analysis/2026-11-04-ai-fallback/harness-report.md:117` “**No real provider was called** (no key, no spend)”。
- `scripts/eval_provider.py:326` `def sample_words`，`:347-348` 按 `STAGES` 每阶段抽样并打 `"sample_group": stage`；`:1883` `--per-stage … default=10`；`grep -n sample_group` → 仅 `:339,348,356,375,1095,1829,1832,2046`，`:1095` 只写进 extras，`:1829/:2046` 只做计数；成绩单聚合（`:1455-1530`，键 `schema_valid_rate/item_pass_rate/items_passed/…`）全按 kind，没有按 `sample_group` 的拆分；`:111` `THRESHOLDS = {"schema_valid": 0.98, "item_pass": 0.95, "headword_present": 0.97, "three_examples": 0.95, …}` 全局。属实。
- `AI_FALLBACK_MODEL.md:62`「例句含词头是弱模型最常挂的规则」；`judge-J3-quality-terms.md:67` “Predicates a 30B-A3B model is most likely to fail: headword … in ≥3 of ≤4 examples; meaning_zh CJK + ≤120; integer difficulty; verbatim word”；`facts/contract.md:55` “averages **1,006 bytes** … **2.47–2.63 bytes per output token**”；`openai_http.py:60` `DEFAULT_MAX_TOKENS … "content": 8192`；`config.py:144` 批 5。全部属实。

---

## 作者遗漏的重要事实

1. **「小学」标签与阶段键的硬编码远不止 `content.STAGE_ZH` 一处，且有一处会直接崩溃。** `words.stages_of`（`backend/wd/services/words.py:228-229`）遍历的是 `words.py:39` `STAGES = ("zk", "gk", "cet4", "cet6")`；`content.py:88` 用 **字典下标** `STAGE_ZH[s]`（不是 `.get`）。若阶段模型切片给 `words.STAGES` 加 `"xx"`（小学）而未同步 `content.STAGE_ZH`，每个带新标志的词在 `prompt_entry` 抛 `KeyError`，整组 `generate_content` 失败。平行的重复映射/枚举还有：`backend/wd/schemas.py:25` `Stage = Literal["zk","gk","cet4","cet6"]`、`:26` `StageIndex`、`:51` `STAGE_ORDER`、`:52` `STAGE_NAMES_ZH`（与 `STAGE_ZH` 内容相同）；`backend/wd/ai/prewarm.py:32-33` `STAGE_COLUMNS/STAGES`；`backend/wd/services/bank.py:85-86` `DEFAULT_STAGES = ("cet4","cet6") / DEFAULT_CURRENT_STAGE = 3`；前端 `frontend/src/api/types.ts:5` `Stage = 'zk' | 'gk' | 'cet4' | 'cet6'`、`i18n/zh.ts:25` 角色 `{ zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }`、`:28` `stages: { zk: '初中', gk: '高中', cet4: '四级', cet6: '六级', … }`、`:86`「词表范围：中考、高考、大学英语四级与六级大纲」、`pages/WelcomePage.tsx:30` `Role = 'zk' | 'gk' | 'uni' | 'pro'`、`pages/VocabPage.tsx:29` `TABS = ['all','zk','gk','cet4','cet6']`。（事实，置信度高；来自 grep 与读源。）
2. **schema 改动受测试强制的三方逐字节同步。** `backend/tests/unit/test_schemas.py:56-62` `test_schema_file_is_verbatim_from_the_contract_and_the_fixture_copy`：`:59` `assert text.rstrip("\n") == doc_block(DOC_HEADINGS[name])`（schema 文件 == `docs/CLAUDE_INTEGRATION.md` §4.x 的 ```json 代码块，逐字节）、`:61` `assert parsed == fixture[name]`（== `backend/tests/fixtures/claude_schemas.json`）。原文 -13 列了这些文件，但没有说明是测试强制、必须同一提交完成，且 `:66-73` 还限制 schema 只能用 `ALLOWED_KEYWORDS`（`type/properties/required/items/minItems/maxItems/description/enum`），所以新字段不能用 `minLength` 等约束，一切长度仍要落在 `validate_item`。（事实，置信度高。）
3. **面向小学生的内容/图片安全控制目前很薄，作者在 (c) 没有提。** 文本侧唯一规则是 `content_system.txt:6` “sensitive topics (violence, sex, politics, religion, drugs)”；图片侧是 `backend/wd/images/select.py:20-24` `BLOCKLIST_RE`（`map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document|nude|nudity|sex|porn|gore|blood|weapon|gun|corpse`）加提供方参数：Pixabay `safesearch=true`（`images/providers/pixabay.py:35`）、Openverse `mature=false`（`openverse.py:42`）；而 Wikimedia 与 Pexels 的候选 `mature=False` 是**硬编码**（`wikimedia.py:116`、`pexels.py:65`），没有来自提供方的成人内容信号。没有任何按年龄分级的词（酒精、吸烟、恐怖、亲密等）。这直接影响需求 (4)「配图更利于小学生记忆」的方案选择。（事实，置信度高。）
4. **提示词软上限与后验证硬上限成对错位，且后验证只截断不拒绝。** `content_system.txt:4/5/8/10` 分别写 meaning_zh ≤80、meaning_en ≤160、mnemonic ≤60、image_alt_zh ≤30；`content.py:52,53,59,62` 对应 120/200/100/60；`common.py:72-73` 超长截断。`scripts/eval_provider.py:109-110` 已把它们记成 `SOFT_CAPS/HARD_CAPS`。若为小学缩短输出，改提示词数字即可生效，但不会有任何机器校验兜底；原文 -7 提到个别数字却未点明「截断而非拒绝」这一行为。（事实，置信度高。）
5. **原文「未解决的问题 4」可以用线上副本直接回答（见 -15）**：`bank_suggestions` 没有 `difficulty` 行、`consolidation_runs` 的 4 次 `done` 均 `auto_applied: 0`、活跃生词 18 条中 0 条 `difficulty IS NULL`。夜间整理因 difficulty 空值反复检查种子词的开销在当前数据里**尚未发生过**。（事实，置信度高。）

---

## 未解决的问题

1. 原文 -8 的「0 命中」如何得出无法复现；若作者的 grep 实际未加 `-E`，同一方法得到的其它「0 命中」（`小学|primary school|elementary`）也可能只是模式失效——我用 `-E` 复查后该条确实为 0，但建议后续 facts 文件把 grep 命令原样贴出。
2. 遗漏 1 的 `KeyError` 是读码推断（`STAGE_ZH[s]` 下标访问），未实际构造带新 `stage_*` 列的行运行 `prompt_entry` 验证；由于本工作流禁止改代码，未做。
3. -5 的「4 个词通常 ≥ 15 字符」是经验判断，线上 195 条例句最短 33 字符、最少 6 词，没有小学语料可以校准 3–5 词句被丢弃的真实比例。
4. 图片安全（遗漏 3）属于配图切片范围，本文只指出控制点与空白，未评估各提供方的实际内容分布。

---

核验 16 条：确认 14、修正 2、推翻 0、无法核验 0。
