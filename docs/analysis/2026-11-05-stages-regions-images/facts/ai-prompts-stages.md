# ai-prompts-stages — 阶段/难度如何进入 AI 生成，以及「小学」阶段对提示词与 schema 的要求

> 日期 2026-11-05 · 仓库 `/Users/sqin/word-dance` @ `75df534`（工作树干净）· 只读调研，未改任何代码 · 线上库只读副本 `scratchpad/live-copy.db`（9,162 词）

## 范围与方法

**读过的代码（按当前 HEAD 核对行号）**：`backend/wd/ai/prompts/{content_system,lookup_system,consolidate_system,svg_system}.txt`；`backend/wd/ai/schemas/{content_v1,lookup_v1,consolidate_v1,svg_v1,probe_v1}.json`；`backend/wd/ai/{content,lookup,consolidate,svg,models,common,prewarm,runner}.py`（runner 只看 `load_prompt/load_schema`）；`backend/wd/ai/providers/openai_http.py`（`compose_system`、`DEFAULT_MAX_TOKENS`、后缀常量）；`backend/wd/ai/failover.py:319-330`；`backend/wd/jobs/{queue,worker,scheduler}.py` 的领取与夜间整理选择；`backend/wd/services/{words,bank,batches,stats,suggestions}.py` 中与 stage/difficulty 相关的函数；`backend/wd/routers/vocab.py:76-80`；`backend/wd/schemas.py:44-67,477,492,549-563`；`backend/wd/config.py`（批大小、`WD_AI_FALLBACK_KINDS`）；`backend/wd/migrations/0001_init.sql:147-148,195,447`；`backend/wd/images/{handler,select,card_svg}.py` 中消费 `image_keywords/image_alt_zh` 的位置；前端 `frontend/src/api/types.ts`、`components/study/{StudyCard,WordImage}.tsx`、`pages/{WordDetailPage,VocabPage}.tsx`、`components/bank/SuggestionRow.tsx`；测试 `backend/tests/unit/{test_content_apply,test_schemas,test_claude_fixtures,test_consolidate_apply}.py`、`backend/tests/fake_claude.py`、`backend/tests/fixtures/`；`scripts/eval_provider.py`（采样、阈值、指标聚合）。

**读过的文档**：`docs/CLAUDE_INTEGRATION.md` §4–§6、§10；`docs/AI_FALLBACK_MODEL.md` §0–§2、§4、§5、§8；`docs/API.md` §9（Content DTO、9.1 字段说明、端点 20 的 `sort=difficulty`）；`docs/DESIGN.md` §9；`docs/WORD_LIBRARY_CURATION.md`（:96、:115、:183）；`docs/analysis/2026-11-04-ai-fallback/{harness-report,judge-J3-quality-terms}.md` 与 `facts/contract.md`（F3）；`docs/analysis/2026-11-04-library-curation/facts/{content-media,docs-intent-gaps}.txt`。

**查过的数据**：`sqlite3 -readonly live-copy.db` 上对 `words`、`word_contents`、`word_forms`、`ai_calls` 的统计（每条数字后附 SQL）。**全文检索**：`grep -rn` 过 `difficulty`、`STAGE_ZH`、`stages_of`、`image_alt_zh`、`syllab|phonics|自然拼读|音节`、`小学|primary school|elementary`。**未联网、未下载任何文件**（本任务是代码与契约核验，没有需要外部来源回答的问题）。

置信度标注：高 = 直接读到代码/数据；中 = 由代码推出的行为后果；低 = 缺证据的推断。

---

## (a) 提示词如何表达学习者阶段；一个 group 能否混合阶段

**[ai-prompts-stages-1] 阶段只以「每个词的中文标签列表」进入 content 提示词，没有任何按阶段变化的生成规则。** 事实，置信度高。
- 系统提示词只在开头一句枚举受众：`backend/wd/ai/prompts/content_system.txt:1` “an English vocabulary app for Chinese learners (初中, 高中, CET-4, CET-6 and working professionals)”。唯一与水平相关的生成规则是 `:6` 里的一句 “Avoid rare vocabulary above the learner's level”——没有定义 level 是什么，也没有按阶段分别规定例句长度、词汇范围或语气。
- 用户提示词的 `audience` 是常量：`backend/wd/ai/content.py:48` `AUDIENCE = "Chinese learners, junior high school to CET-6, plus working professionals"`，`:97` `json.dumps({"audience": AUDIENCE, "words": entries})`——对每次调用都一样，不随批次里的词或用户变化。
- 每个词带自己的阶段标签：`content.py:49` `STAGE_ZH = {"zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}`；`:88` `"stages": [STAGE_ZH[s] for s in words.stages_of(word)]`；`backend/wd/services/words.py:228-229` `stages_of` 读 `stage_zk/gk/cet4/cet6` 四个 0/1 列。标签是累积的，例如测试断言 `backend/tests/unit/test_content_apply.py:255` `"stages": ["初中", "高中", "四级"]`。词条其余字段只有 `dictionary_hint`（译文第一行 ≤ 60 字，`content.py:73-79`）、`pos_hint`、非 word 时的 `kind`（`:82-92`）。
- `STAGE_ZH` 在全仓库只有 `content.py:88` 一处使用（`grep -rn STAGE_ZH backend scripts`）：**它只负责把标签写进提示词，不参与分组、过滤或难度计算。**

**[ai-prompts-stages-2] 一个 group 可以、也经常会混合阶段；分组只按优先级/时间，与阶段无关。** 事实，置信度高。
- `content.select_jobs`（`content.py:374-409`）只做跳过判断（`missing_word`/`merged`/`unvalidated`/`invalid_word`/`already_ready`/`superseded_regenerate`），不重排、不分组。
- 分组发生在领取：`backend/wd/jobs/queue.py:129-160` `claim_batch` 的两条 SQL 都是 `ORDER BY priority, run_after, id LIMIT n`，再按 `payload.group_size` 收缩；没有任何 stage 条件。CLI 上一组 ≤ `WD_AI_BATCH_SIZE=10`（`config.py:115`，`:483` 钳制 1–12，因 `content_v1.json:1` `maxItems: 12`），备选上 ≤ `min(10, WD_AI_FALLBACK_BATCH_SIZE=5)`（`config.py:144`，`failover.py:319-326` `group_cap`）。
- 预生成计划按阶段选词（`backend/wd/ai/prewarm.py:32-51` `_stage_sql`，`:163` 逐词入队、优先级 90、去重键 `content:<id>`），但入队后与其他来源的任务同在一个队列；两个不同阶段的计划并行、或用户触发的 10/20/30 优先级任务，都会在同一组里混合。契约文档的示例本身就是混合的：`docs/CLAUDE_INTEGRATION.md:234-235` 同一批里 `abandon` 带 `["高中","四级","六级"]`、`GDP` 带 `[]`。
- 推断（中）：因此「按阶段换一份系统提示词」在现有结构下做不到——一次调用只加载一份 `content_system`（`content.py:447` `runner.load_prompt("content_system")`，`runner.py:100-103` `lru_cache`）；要么把分阶段规则写进同一份提示词并以每个词的 `stages` 标签触发，要么在领取层新增按阶段分组（新代码）。

**[ai-prompts-stages-3] lookup、consolidate、svg 三条链路完全不携带阶段信息；lookup 的 difficulty 连刻度说明都没有。** 事实，置信度高。
- lookup 用户提示词只有字符串数组：`backend/wd/ai/lookup.py:68-70` `{"items": strings}`；系统提示词 `lookup_system.txt:6` 只写 “difficulty 1–5”，**没有 1=初中…5=beyond CET-6 的图例**（content 与 consolidate 都有：`content_system.txt:11`、`consolidate_system.txt:11`）。即 lookup 写入的 `words.difficulty` 刻度由模型自行理解。
- consolidate 每个 item 带当前 `difficulty`（可能为 null，`consolidate.py:124`），系统提示词要求对缺失者返回 `difficulty_tags`（`consolidate_system.txt:11`），并约定 “use empty strings and difficulty 3 when nothing is needed”（`:10`）。
- svg 用户提示词只有词、释义（≤ 60）与概念句（`image_alt_zh` ≤ 60）：`backend/wd/ai/svg.py:32-33,40-52` `Draw an illustration for the word "{display}" ({meaning}). Concept: {concept}。`；`svg_system.txt:1` 没有年龄/阶段语气要求（只有 “simple, flat-style educational illustration”）。

**[ai-prompts-stages-4] 备选模型收到与 Claude 完全相同的提示词（含阶段标签），只是系统提示词末尾追加了 JSON 输出指令与压缩 schema。** 事实，置信度高。
- `backend/wd/ai/providers/openai_http.py:174-180` `compose_system(system_prompt, schema, json_mode)`：`json_object` 模式返回 `base + JSON_OBJECT_SUFFIX + runner.schema_arg(schema)`，`json_schema` 模式返回 `base + JSON_SCHEMA_SUFFIX`；后缀文本见 `:75-79`（“Output format: respond with ONE JSON object only … that conforms exactly to this JSON Schema:”）。用户消息原样（`:677` 附近组装 messages）。
- 因此针对「小学」改 `content_system.txt` / `prompt_entry`，两条腿同时生效，不需要为备选单独写提示词。

---

## (b) 若加「小学」：哪些能在提示词层解决，哪些要改 schema / 代码

**[ai-prompts-stages-5] 例句长度：提示词要求 8–20 词，后验证硬性要求英文 15–240 字符；要给小学生写 3–6 词的短句，会撞上 `EXAMPLE_EN_MIN = 15` 这个 Python 常量（不是 schema）。** 事实 + 推断，置信度高/中。
- 提示词：`content_system.txt:6` “8–20 words each … not textbook-stilted … Vary the register across the set (daily life, workplace, academic, news)”。对小学阶段，“workplace/news” 语域与 “not textbook-stilted” 都不合适，这些是纯文本修改。
- schema 对例句没有长度约束：`content_v1.json:6` 只有 `minItems 0 / maxItems 4` 与 `required ["en","zh"]`；`backend/tests/unit/test_schemas.py:22-23` 明确禁止 schema 使用 `minLength/maxLength/minimum/maximum`，长度全部由后验证执行。
- 后验证：`content.py:54` `EXAMPLE_EN_MIN, EXAMPLE_EN_MAX = 15, 240`；`:153` `if not (EXAMPLE_EN_MIN <= len(en) <= EXAMPLE_EN_MAX) or common.ascii_ratio(en) < EXAMPLE_ASCII_MIN: continue`；`:162-164` 可用例句 < 3（最后一次尝试 < 2）→ `retry`，整条内容不入库。像 “I like cats.”（12 字符）、“I am a boy.”（11 字符）这类典型小学句会被静默丢弃；若 4 条里有 2 条被丢，该任务重试，耗费一次调用。`docs/CLAUDE_INTEGRATION.md:355` 把 “`en` 15–240 chars” 写进了契约，改常量要同步改文档。
- 线上实测（49 张卡、195 条例句）：英文长度 min 33 / avg 54.6 / max 86 字符；词数 min 6 / avg 9.4 / max 14。
  - SQL：`SELECT MIN(length(json_extract(e.value,'$.en'))), AVG(...), MAX(...) FROM word_contents wc, json_each(wc.content_json,'$.examples') e WHERE wc.status='active'` → `33|54.6|86`；词数用 `length(en) - length(replace(en,' ','')) + 1` → `6|9.39|14`。
- 推断（中）：小学例句可以在提示词层要求「4–8 词、一般现在时、日常校园场景」而不碰 schema，但要么接受 15 字符下限（4 个词通常 ≥ 15 字符，3 个词常不够），要么把 `EXAMPLE_EN_MIN` 降到 ~10 并更新 §6.4——这是一处代码常量改动，不是契约结构改动。

**[ai-prompts-stages-6] 词汇控制（例句只用更基础的词）目前只有一句软要求，服务端没有任何词表校验；可做提示词层改进，但无法在后验证里保证。** 事实，置信度高。
- 仅有 `content_system.txt:6` “Avoid rare vocabulary above the learner's level”。`validate_item`（`content.py:131-203`）检查的是长度、ASCII 比例、CJK、词头出现（`contains_headword`）、关键词正则与屏蔽词表、difficulty 范围——没有任何词汇表比对。
- 推断（中）：若要机器校验「例句只用小学/初中词」，需要新代码（例如用 `words.stage_zk=1` 的 2,099 词作为允许表做软评分），这与 schema 无关，但会增加 retry 率；没有小学词表之前无法实现。

**[ai-prompts-stages-7] 中文释义口吻、助记方式、搭配是否要：三项都是提示词层可解，schema 不必动（字段都允许为空或任意风格）。** 事实，置信度高。
- 释义：`content_system.txt:4` 要求「词典体 + 词性缩写」（例 “v. 放弃；抛弃  n. 放纵”）；后验证只要 1–120 字且含 CJK（`content.py:52,139-141`）。改成小学生能读的「放弃；不要了」只改文本。
- 助记：`content_system.txt:8` 偏好词根词缀、联想要以 “联想：” 开头、可为空；后验证只截断到 100 字（`content.py:59,172`）。线上 49 条里 8 条以 “联想” 开头、2 条为空（SQL：`SUM(json_extract(content_json,'$.mnemonic_zh') LIKE '联想%'), SUM(...='')`）。小学阶段若要图像联想/谐音，只改文本；前端有助记才渲染（`frontend/src/components/study/StudyCard.tsx:254-257`，`pages/WordDetailPage.tsx:476-479`）。
- 搭配：schema 把 `collocations` 列为必填键但允许空数组（`content_v1.json:7,12`；`content_system.txt:7` “Empty array if none are common”），后验证接受空（`content.py:165-171`），前端空则不渲染（`StudyCard.tsx:242`，`WordDetailPage.tsx:464`）。所以「小学阶段不要搭配」或「改成短语搭配」都不需要 schema 改动。

**[ai-prompts-stages-8] 音节 / 自然拼读提示：代码、提示词、schema、前端、文档里完全没有；要加就是新 schema 字段（代价见 -12）。** 事实，置信度高。
- `grep -rn -i "syllab|phonics|自然拼读|音节"` 遍历 `backend/wd`、`frontend/src`、`docs/*.md`、`scripts` → 0 命中。现有发音相关数据只有 `words.phonetic`（种子 IPA 或 lookup 填入，`lookup.py:347-349`）与 `exchange_json/word_forms`（屈折形式）。
- `grep -rn "小学|primary school|elementary"` 遍历同样范围（不含 `docs/analysis`）→ 0 命中：产品文档、提示词、代码里目前没有「小学」概念。

**[ai-prompts-stages-9] 「小学」在 difficulty 刻度上没有位置：1–5 的含义（1=初中…5=beyond CET-6）被写死在 3 份提示词、3 份 schema、4 个 pydantic Literal、API 类型、TS 类型、DB CHECK 与排序 SQL 里。** 事实，置信度高。
- 提示词：`content_system.txt:11`、`consolidate_system.txt:11`（lookup 无图例，见 -3）。schema：`content_v1.json:11`、`lookup_v1.json:11`、`consolidate_v1.json:8,11` 均 `enum [1,2,3,4,5]`。镜像：`backend/wd/ai/models.py:44,61,76,90` `Literal[1, 2, 3, 4, 5]`。API：`backend/wd/schemas.py:47` `Difficulty = Literal[1, 2, 3, 4, 5]`，`:559` `Content.difficulty: Difficulty`；`frontend/src/api/types.ts:73` `difficulty: 1 | 2 | 3 | 4 | 5`。DB：`migrations/0001_init.sql:195` `difficulty INTEGER CHECK (difficulty BETWEEN 1 AND 5) -- 1 初中 … 4 六级, 5 beyond`；`:148` `current_stage … CHECK (current_stage BETWEEN 1 AND 4)`。后验证：`content.py:186-188` 1–5 否则 `invalid: difficulty`（测试 `test_content_apply.py:245`）。
- 排序 SQL 依赖 difficulty 与 stage_min 共用编号：`backend/wd/routers/vocab.py:78` `"difficulty": "COALESCE(w.difficulty, w.stage_min, 5), …"`（`docs/API.md:169` 同）。今天 1=初中=zk、2=高中=gk、3=四级=cet4、4=六级=cet6 对齐；一旦小学成为新的「1」或「0」，这条 COALESCE 的两个分支刻度就不一致。
- 推断（中）：最省事的方案是提示词层把小学词也标 `difficulty 1`（与初中共用，丢失区分度，零代码）；要区分就是 6 级刻度，涉及上面每一处（约 12 个文件 + 迁移改 CHECK + `stage_to_index`/`index_to_stage` `schemas.py:56-67`）。这属于「阶段模型」切片的决定，这里只列出耦合点。

**[ai-prompts-stages-10] 改提示词文本而不改 `PROMPT_VERSION`，已生成的 49 张卡不受影响；改了 `PROMPT_VERSION` 也不会自动重做任何词。** 事实，置信度高。
- `content.py:46` `PROMPT_VERSION = "content-v1"`，自 `a0ef789` 以来提示词与 schema 文件从未改过（`git log --oneline -- backend/wd/ai/prompts/content_system.txt backend/wd/ai/schemas/content_v1.json` 只有一次提交）。
- `select_jobs` 只在「已 ready 且版本相同」时跳过（`content.py:405`）；但入队方 `bank.enqueue_content_if_needed`（`backend/wd/services/bank.py:489-492`）与预生成候选（`prewarm.py:48` `content_state IN ('none','failed')`）都不会给 `ready` 的词排任务。`docs/WORD_LIBRARY_CURATION.md:115`：「提升 PROMPT_VERSION 不会让任何词重新入队，全库刷新只能逐词 force」。
- 后果：小学提示词上线后，老卡片（目前 49 张，全是 cet4/cet6 词）不会变；只有新生成的词用新规则。`force` 重生成会刷新 `words.difficulty`（`content.py:230-234`，测试 `test_content_apply.py:193-198`）。

**[ai-prompts-stages-11] 词头检测对 ≤ 3 字母的短词只认精确形式与 `word_forms`，小学高频短词里有一部分没有屈折行，例句用复数/过去式会被当作「不含词头」丢弃。** 事实 + 推断，置信度高/中。
- `content.py:63` `PREFIX_MIN = 4`；`:117-128` `contains_headword`：先匹配 lemma/display/forms 的整词，再在 `len(lemma) >= 4` 时允许「前 max(4, len-3) 个字母」前缀。3 字母词没有前缀分支。
- 线上副本：3 字母 word 共 309 个，其中 23 个没有任何 `word_forms` 行；2 字母 30 个（14 个无）；4 字母 946 个（58 个无）；`stage_zk=1` 且无 `word_forms` 的词 260 个（样例 `the/for/you/but/his/not/she/her/all/how/its/our/any/too`——多为无屈折的功能词，所以实际影响比数字小）。
  - SQL：`SELECT length(lemma) L, COUNT(*), SUM(NOT EXISTS (SELECT 1 FROM word_forms wf WHERE wf.word_id = w.id)) FROM words w WHERE length(lemma) <= 4 AND kind='word' GROUP BY L` → `1|1|1`、`2|30|14`、`3|309|23`、`4|946|58`；`SELECT COUNT(*) FROM words w WHERE stage_zk=1 AND kind='word' AND NOT EXISTS (...)` → 260。`word_forms` 共 14,132 行（kind `s` 4,366、`p` 3,024、`i` 2,943、`3` 3,111、`t` 313、`r` 305、`d` 70）。
- 推断（中）：小学词库会比现有四级词更短、更常以复数/第三人称出现（cats, runs），对缺屈折行的词，提示词应明确「用词头原形」，或把 `PREFIX_MIN` 的规则放宽——后者是代码常量改动。

---

## (c) 现有 content 有没有「图意」字段可供配图流水线使用

**[ai-prompts-stages-12] 已有两个图意字段：`image_keywords`（2–4 条可拍照的英文检索短语）与 `image_alt_zh`（≤ 30 字的中文「理想画面 + 与词义的联系」）。两者都已被配图流水线消费；没有单独的 `image_hint`/生成提示词字段。** 事实，置信度高。
- 定义：`content_system.txt:9-10`；schema `content_v1.json:9-10`（`image_keywords minItems 1 maxItems 4`）；后验证 `content.py:61` `KEYWORD_RE = ^[A-Za-z][A-Za-z ,'-]{1,40}$`、`:173-184`（小写、去重、过 DESIGN §9 屏蔽词表 `images/select.py:40-42`，全部被滤掉则退回 `[lemma]`）、`:62,185` `image_alt_zh` ≤ 60 字。
- 消费点：照片检索 `backend/wd/images/handler.py:4` “keywords = query or content.image_keywords[:3] or [lemma]”，`:65-80` `clean_keywords`，`:131-137`（`image_alt_zh` 截到 200 字存进 `word_images.alt_zh`）；SVG 生成 `svg.py:48-52` 把 `image_alt_zh` 当 “Concept:”（≤ 60 字）；前端把它当 `<img alt>`（`frontend/src/components/study/WordImage.tsx:16`，`StudyCard.tsx:306`，`WordDetailPage.tsx:447`）。模板卡片 `images/card_svg.py:82-96` 只用 `meaning_zh` 与第一条例句，不用图意字段。
- 线上 49 张卡：`image_alt_zh` 最长 20 字（SQL `MAX(length(json_extract(content_json,'$.image_alt_zh')))` → 20），关键词每词 1–3 条（例 `particularly` 只有 `["one red apple"]`，`have` 为 `["holding keys in hand","person holding book","family having dinner"]`）。即现有图意信息很短，偏「检索关键词」而非「可直接喂给生图模型的场景描述」。
- 推断（中）：要让配图更利于记忆，**先在提示词层**改 `image_keywords`/`image_alt_zh` 的写法（例如要求画面与例句情境一致、避免抽象象征）零代码即可；若要加一个更长的英文场景描述字段供生图/检索排序使用，就是 -13 的 schema 改动。

**[ai-prompts-stages-13] 给 content 增加一个字段的代价清单：schema + 提示词 + 后验证 + pydantic 镜像 + API 模型 + TS 类型 + 契约文档 + 4 处测试夹具/断言 + 评测脚本，并且必须给旧卡片留兼容默认值。** 事实（清单每项都读到）+ 推断（工作量），置信度高/中。
- 必改：`content_v1.json`（properties + `required`，`:12`）；`content_system.txt`（新规则）；`models.py:34-44` `ContentItem`（`Mirror` 配置 `extra="ignore"`，`:15-18`，**未声明的键会在 `models.valid_items` 阶段被静默丢弃**，根本到不了 `validate_item`）；`content.py:131-203` `validate_item`（返回的 cleaned 字典是显式列出的 10 个键，`:189-201`，新字段不加就不会入库）；`backend/wd/schemas.py:549-563` `Content`（所有字段必填，无默认）；`frontend/src/api/types.ts:70-74` `Content`；`docs/API.md:304-308` 与 `docs/CLAUDE_INTEGRATION.md` §4.1/§5.1/§6.4（`API.md:3`：schemas.py、types.ts、API.md 必须同一提交改）。
- 测试：`test_content_apply.py:80` 断言入库键集合恰为 14 个键；`backend/tests/fixtures/claude_content_ok.json`（10 条）与 `claude_schemas.json` 由 `test_claude_fixtures.py:46-53` 按 schema 校验；`backend/tests/fake_claude.py:170-199` `content_item` 要补字段；`scripts/eval_provider.py:115` `CONTENT_ITEM_KEYS`。
- 兼容：`docs/WORD_LIBRARY_CURATION.md:183`（核验 C4）——`content_json` 缺键或多键会让内容接口、详情、今日页返回 500；旧的 49 条 `content_json` 没有新键，所以 `schemas.Content` 里新字段必须 `Optional` 带默认，前端同样按可选处理；同时建议 bump `PROMPT_VERSION`（否则新旧卡片无法从 `prompt_version` 区分）。
- 推断（中）：10 个文件左右的机械改动 + 一次 1477 项测试跑通；比起提示词层改动是「小时级 vs 分钟级」的差别，但没有架构风险。

---

## (d) `words.difficulty` 现状与使用者

**[ai-prompts-stages-14] 线上副本 9,162 词中 9,113 词 `difficulty` 为空，49 个非空值恰好就是 49 个有 AI 内容的词，全部由 `store_content` 写入；分布 1:2、2:1、3:43、4:3；与 `stage_min` 一致 44/49。** 事实，置信度高。
- SQL：`SELECT COUNT(*), SUM(difficulty IS NULL), SUM(difficulty IS NOT NULL) FROM words` → `9162|9113|49`；`SELECT difficulty, COUNT(*) FROM words GROUP BY difficulty` → `NULL 9113 / 1:2 / 2:1 / 3:43 / 4:3`；`SELECT content_state, COUNT(*) FROM words GROUP BY content_state` → `none 9113 / ready 49`；`word_contents` 49 行均 `active / content-v1 / claude-sonnet-5-5`；`ai_calls` 中 `content|success` 10 次调用合计 `word_count` 49（另有 12 次 `auth` 失败）。
- 一致性：`SELECT SUM(difficulty = stage_min), SUM(difficulty < stage_min), SUM(difficulty > stage_min) FROM words WHERE difficulty IS NOT NULL` → `44|2|3`。偏低的两例 `writer`（AI 1，stage_min 3）、`suddenly`（2 vs 3）；偏高的三例 `executive`、`republican`、`senate`（4 vs 3）。即 Claude 的 difficulty 与考纲阶段大体一致但不是复制：它在 10% 的词上给出了与词表不同的判断。
- 写入路径有四条（都只在 NULL 时写，`force` 例外）：`content.store_content` `content.py:230-234`；`lookup.fill_fields` `lookup.py:353-355`；`consolidate._fill_data` `consolidate.py:282-285`（非种子词，且 **忽略值 3**——3 是提示词约定的「无需填写」哨兵，`consolidate_system.txt:10`）；`consolidate._difficulty_tag` `consolidate.py:308-326`（**不检查 source，种子词也写**，测试 `test_consolidate_apply.py:305-313` 断言种子词 apple 被标为 1；`docs/WORD_LIBRARY_CURATION.md:96` 同）。写入会留 7 天可撤销的 `difficulty` 建议行（`0001_init.sql:447`，`services/suggestions.py:44`）。

**[ai-prompts-stages-15] `difficulty` 的读者只有两处：词库页 `sort=difficulty` 的 ORDER BY，以及夜间整理的「待检查」条件；学习批次、筛词、统计、SRS 都不用它。** 事实，置信度高。
- 排序：`routers/vocab.py:78`（见 -9），前端只在排序下拉里暴露 `'difficulty'`（`frontend/src/pages/VocabPage.tsx:31`，`i18n/zh.ts:48` “难度”），`WordBrief.difficulty` 传到前端后没有任何渲染（`grep -rn difficulty frontend/src` 其余全是测试夹具与 `SuggestionRow.tsx:30-32` 的建议文案回退）。
- 夜间整理：`backend/wd/jobs/scheduler.py:229-240` `_bank_needs_consolidation` 与 `consolidate.select_items` `consolidate.py:87` 都把 `w.difficulty IS NULL` 当作「需要检查」。推断（中）：在 9,113 词为空的现状下，任何加入生词库的种子词都会**每晚**进入整理提示词，直到某次 `difficulty_tags` 把它填上（每用户每晚 ≤ 80 项，`consolidate.py:46`）；这是一笔持续的 Claude/备选调用开销，与「小学」无关但与 difficulty 空值直接相关。
- 不用它的地方：批次选词只看阶段标志与词频（`backend/wd/services/batches.py:232-234` `_stage_flags`，`:270,:694`）；阶段统计 `services/stats.py:173-185` 用 `stage_*`；预生成用 `stage_*`（`prewarm.py:36-39`）。所以对「小学」而言，决定学什么的是 `stage_*` 列，`difficulty` 只是排序与整理触发器。

> **核验修正（INDEX §3 #29，2026-11-05）**：事实部分确认，「每晚持续开销」的推断需修正——加入生词库本身就会入队 `generate_content`（`bank.py:636,659` 调 `enqueue_content_if_needed`），成功后 `store_content`（`content.py:230-234`）当场写入 `difficulty`，通常早于当晚整理；只有内容生成失败/滞后（AI 关闭、预算耗尽、死任务）的词才落入夜间 `difficulty IS NULL` 条件。线上副本：活跃生词 18 条中 `difficulty IS NULL` 为 0；19 次 `consolidation_runs` 为 done 4 / failed 3 / skipped 12（"deferred"），done 的 4 次 `auto_applied` 均为 0。机制存在但当前没有一条处于该状态；同时回答了「未解决的问题 4」，依据 verify/ai-prompts-stages.md [ai-prompts-stages-15]。

---

## (e) 备用模型对更简单的小学例句是否更可靠

**[ai-prompts-stages-16] 没有证据。所有质量结论都来自公开榜单与代码契约，没有任何国产模型被真正调用过；评测门槛是按任务整体设定的，不分阶段，成绩单也没有按阶段拆分的指标。** 事实，置信度高。
- `docs/AI_FALLBACK_MODEL.md:9`「没有任何国产模型被真正调用过（没有 key、不花钱）」；`:143`（§5）「已知局限：…没有真实厂商被调用过」；`docs/analysis/2026-11-04-ai-fallback/harness-report.md:117` “No real provider was called (no key, no spend)”。
- 评测采样按阶段各 10 词（`scripts/eval_provider.py:326-348` `sample_words`，`:1883` `--per-stage` 默认 10），但 `sample_group` 只写进 `items.jsonl` 的 extras（`:1095`）与 dry-run 计数（`:1829,:2046`）；成绩单指标在 `:1485-1530` 全部按 kind 聚合，门槛 `:111` `THRESHOLDS`（schema ≥ 98%、条目 ≥ 95%、词头 ≥ 97%、≥ 3 例句 ≥ 95%…）也是全局的。要回答「小学词是否更可靠」，需要给成绩单加按 `sample_group` 的拆分（小改），并真的跑一次。
- 契约侧提到的弱模型易错点与句子难度无关：`AI_FALLBACK_MODEL.md:62`（§2.1 content 行）「例句含词头是弱模型最常挂的规则」；`judge-J3-quality-terms.md:67`「Predicates a 30B-A3B model is most likely to fail: headword (or inflection / ≥4-letter prefix) in ≥3 of ≤4 examples; meaning_zh CJK + ≤120; integer difficulty; verbatim word」。
- 推断（低）：更短的小学例句会减少输出 token（契约 F3：每条内容约 1,006 字节、2.47–2.63 字节/token，`facts/contract.md:55`；备选 content `max_tokens 8192`、批 5，`openai_http.py:60`、`config.py:144`），对 `truncated:`/超时路径是利好；而「词头原形出现」在短句里也更容易满足。但反向风险是 -5 的 15 字符下限与 -11 的短词形式问题——这些对两条腿同样生效。没有数据之前不应把「小学例句交给备选」当成已证明的结论。

---

## 未解决的问题

1. **小学的 difficulty 位置**：共用 1（零代码）还是扩成 6 级（跨 12 个文件 + DB CHECK）？需要阶段模型切片先决定 `stage_min`/`current_stage` 的编号方案，本文只列耦合点（-9）。
2. **`EXAMPLE_EN_MIN=15` 与 `PREFIX_MIN=4` 要不要为小学放宽**：取决于小学例句的目标长度（4 词以上基本安全，3 词句会被丢）与小学词表里缺屈折行的词有多少（现库 zk 为 260，但多为功能词；小学表未知）。
3. **lookup 的 difficulty 刻度缺图例**（`lookup_system.txt:6`）——现在就是个瑕疵，与小学无关，但若加小学应一并补齐三份提示词的刻度说明。
4. **夜间整理因 `difficulty IS NULL` 反复检查种子词的实际开销**：推断自 `select_items` 条件，未在 `consolidation_runs` 上统计过重复项数；可用 live-copy 的 `consolidation_runs.summary_json` 核对（本次未做）。
5. **图意字段的产品目标**：若配图优化的方向是「生图」（而非检索照片），`image_alt_zh` 30 字的中文概念句是否够用，还是需要一个英文场景描述字段——取决于配图切片选择的流水线；代价见 -13。
6. **备选模型对小学例句的真实表现**：需要真实 key 跑 `eval_provider.py`，并给成绩单补按 `sample_group` 的拆分；在那之前 (e) 只能回答「没有证据」。
