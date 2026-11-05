# 配图更易记 — 流水线工程师视角（最小安全改动，本周可合并）

基线：`/Users/sqin/word-dance` `main @ 75df534`；线上库只读副本 `scratchpad/live-copy.db`（9,162 词）；2026-11-05。
角度：针对现有 `backend/wd/images/*`、`backend/wd/ai/{svg,content}.py`、`ai/prompts/*.txt` 给出**不引入新 provider**、**无需任何新 key** 的第一期改动，每项附测试思路与回归风险；第二期（需 key / 迁移）只做设计不做代码。
依据标注：`[D1]`…`[D6]` 指 INDEX.md §2.D；`[images-pipeline-N]`、`[verify images-pipeline ON]`、`[image-memorability-N]`、`[ai-prompts-stages-N]` 指 facts / verify 文件条目；`path:line` 均按 75df534 由我重新打开确认（本文引用的每个行号都看过原文）。数字凡来自线上副本的，SQL 在第 3.7 / 5 节给出；未验证的一律标「推断」。

---

## 1. 一页结论

**决定了什么（第一期，本周，零新 key，7 个可独立合并、可独立回退的改动）：**

| # | 改动 | 解决什么 | 代码落点 | 回归风险 |
|---|---|---|---|---|
| P1-1 | **SVG 提示词 v2 + 清洗加固**：去掉「底部英文词」，改为「图中不得有任何文字」；单一主体、素净背景、风格一致；`sanitize_svg._parse` 前修复裸 `&`；`activate_svg` 默认剥离 `<text>/<tspan>`；按 `stage_min` 注入「儿童 / 一般」风格段落；用 `word_images.query='svg:v2'` 标记新卡 | `[D1]` 无文字 / 单一所指；`[D2]` 11.8% XML 拒收（4/34，$0.049 白花）；「图作提示」的前提 | `ai/prompts/svg_system.txt:1`、`ai/svg.py:32-52`、`images/sanitize_svg.py:65-79,169-181`、`images/store.py:152-174` | 低：只影响新生成的卡；1 个断言要翻转（`test_images.py:616` `"<text" in stored`） |
| P1-2 | **content 提示词 v2**：`image_keywords`/`image_alt_zh` 改为「画例句用到的义项、无文字、无人脸特写、抽象词给与 `mnemonic_zh` 对齐的具象挂钩」；小学（阶段标签含 初中 及以下）例句 4–10 词、校园生活语域；`EXAMPLE_EN_MIN` 15→10；`PROMPT_VERSION` → `content-v2` | `[D6]` 图意字段是为照片检索写的；`[ai-prompts-stages-5]` 15 字符下限丢小学句；`[verify images-pipeline O8]` `particularly→one red apple` 这类无关场景 | `ai/prompts/content_system.txt:6,9,10`、`ai/content.py:46,54`、`docs/CLAUDE_INTEGRATION.md:206,355` | 低：不加字段、不改 schema（schema 与文档逐字节绑定的测试不动）；1 个断言要改（`test_content_apply.py:81`） |
| P1-3 | **搜索词构造**：无内容时若词为功能词（ECDICT `pos` 中 a/i/c/p/d/t/x/u 占 ≥ 80%）直接跳过照片搜索；黑名单分「安全词（永不放行）」与「相关词（查询本身含该词时放行）」；管理员 `query` 被形状规则丢弃时写 journal 警告并记入 `detail` | `[D2]` 裸 lemma 搜 `have/despite` 出随机照片、白耗配额；`[verify images-pipeline-9]` `map/flag/text/document…` 这些词永远拿不到标题含该词的照片；`[images-pipeline-2]` 静默回退 | `images/handler.py:64-78,134-137`、`images/select.py:20-24,40-42,54-77` | 低：`test_blocklist_words` 不变（默认不放行）；新增用例 |
| P1-4 | **风格管道 + provider 参数**：`ImageProvider.search(query, limit, *, style)`；`stage_min ≤ WD_IMAGE_KID_STAGE_MAX`（新配置，默认 0=关）的词先走「插画」一遍再走「照片」；Commons `filetype:drawing` + `iiprop` 加 `thumbmime` 并以之为候选 MIME、加 `maxlag=5` 并把 `error.code=maxlag` 当 503 短冷却；Openverse `page_size=limit`（20→10）、插画时 `category=illustration`、读取 `category`；插画候选尺寸门槛 240×180；Pixabay 插画时 `image_type=illustration`、`orientation=horizontal`；Pexels 不变 | `[D1]` 小学配高图标性插画；`[D3]` 参数都存在但现在全锁照片；`[verify images-pipeline O2/O5]`；`[verify image-memorability 遗漏 5]` 剪贴画被 400×300 硬拒 | 中：4 个 provider 的 `params()` 测试要改断言（`test_providers.py:57,61,178,351`；`test_images.py:139,162,540,545` 的 `gsrsearch`/`page_size` 断言）；默认关，线上行为只多 `thumbmime`、`maxlag`、`page_size=10` 三个无害参数 |
| P1-5 | **失败词自动重试**：词进入生词库 / 进入批次时若 `image_state='failed'` 且上次抓图 ≥ 6 h、30 天内自动重试 < 3 次 → 入队（priority 20）；03:30 维护里对「正在被学 + failed」做一次 ≤ 50 词的扫描（priority 30）；`wd images-retry [--limit N] [--dry-run]` | `[D2]`/`[verify images-pipeline O9]` 18 个词永久停在模板卡（15 个因抓图时「尚未被学」没画 SVG，3 个 SVG 被拒），一次冷却整批跳过且不重试 | `images/service.py` 新函数、`services/bank.py:636,659`、`services/batches.py:639`、`jobs/scheduler.py:364-380`、`images/handler.py:349-361`、`cli.py:54` | 低–中：新增任务只在 failed 词上产生；上限封顶；第一晚会补抓 ≤ 17 个词（`employee` 不在学，不补） |
| P1-6 | **打分新信号（纯字符串，无新依赖）**：`description`/`object_name` 命中 +1；Openverse `category` / Pixabay `type` 与风格一致 +1/+2；肖像/自拍/特写类词 −2；标牌/字幕/信息图类词 −1；竖图（宽高比 < 1.0）−1 | `[D2]` 7 个信号全是标题/标签字符串、无人脸/文字/类目信号；竖图在 16:10 `cover` 盒里只剩 ≈ 40% | `images/select.py:80-101`、`providers/openverse.py:114-119`、`docs/DESIGN.md:547` | 低：现有 `test_score_table` 行全部仍成立（默认候选不触发新信号），只加断言 |
| P1-7 | **文档数字**：`$0.028/张` → `$0.0124/次调用、$0.0140/张交付（拒收 11.8%）`；`≈ 18 张/天` → `≈ 35–40 张/天`；DESIGN §9 Selection/Claude SVG 段按上述更新；DEPLOY §4 新增 `WD_IMAGE_KID_STAGE_MAX` 行与 `env.example` | `[D2]` 文档口径过时 | `docs/DESIGN.md:28,518,550`、`docs/CLAUDE_INTEGRATION.md:407,416`、`docs/DEPLOY.md:326,434`、`docs/ops.md:198`、`deploy/env.example:83`、`ai/budget.py:273`（注释） | 零（`test_deploy_files.py:119` 要求 env.example 覆盖每个 Settings 字段恰好一次——新配置必须同时进 env.example） |

**为什么是这 7 个：** 它们覆盖 `[D1]` 推出的全部七条准则里「能在服务端决定」的部分（见 §3.1 表），不碰 API 契约（`schemas.py`/`types.ts`/`API.md` 零改动）、不碰 DDL（无迁移、`docs/SCHEMA.sql` 字节一致测试不动）、不碰 JSON schema（`test_schemas.py:56-62` 三方逐字节绑定不动）、不需要任何 key。每一项都能单独 revert。

**代价：** 约 5 人日（含测试与排练）；运行成本不增加——SVG 单价不变（$0.0124/次），拒收下降后交付价向 $0.0124/张靠拢；插画遍历在默认关闭时零成本，开启后对 kid 词最坏多一倍请求（受现有 Openverse 15/分、160/日与 Wikimedia 2000/日本地限额兜底）。

**决定的产品问题（需负责人确认，§3.6）：** 图默认出现在**回忆之后**（卡片背面，现状不变）；「图作为提示」做成第二期的可选「图像提示」（按 H 键才出现，且只对 `hint_safe` 的无文字图），不做自动前置；**每词一张图不改**（风格由词的 `stage_min` 决定，不按用户分叉）；`show_images` 保持全局布尔，第二期随 0011 的 `user_settings` 重建加 `image_hint` 布尔。

**第二期（需 key / 迁移，§3.5、§3.6、§3.8）：** 生成式位图 provider 试点（智谱 `cogview-3-flash`，默认关）、迁移 0011 的 `word_images` 重建（provider CHECK、`style`、`prompt_version`、`eval_json` 列）、`ImageMeta.hint_safe`/`style`、`Settings.image_hint`、标识办法的显式 + 隐式标识、GLM-4.6V-Flash 自动评分。约 6–8 人日。**第三期**视 200 词试点结果决定默认风格与是否每词多图。

---

## 2. 对照假设 A1–A6 的偏离与理由

| 假设 | 本设计的姿态 | 偏离 / 说明 |
|---|---|---|
| A1 小学 = 国家二级 505 骨架 | 不依赖 | 配图侧只消费 `words.stage_min`（整数）；用阈值 `WD_IMAGE_KID_STAGE_MAX` 而不是阶段码，所以 Q1 的三种编码（重编号 1..5 / 小学=0 / 字符串码）都只需改一个配置值（分别为 2 / 1 / 由映射给出），不改代码 |
| A2 初中/高中词集 | 不依赖 | 同上 |
| A3 许可姿态 | 遵守并收紧 | 第一期只用已存在的 Commons/Openverse；Pixabay/Pexels 参数改动只在给了 key 时生效；全库预抓仍不做（Pixabay「禁系统性批量下载」`[verify images-pipeline O3]`） |
| A4 不按省份分层 | 遵守 | 风格按词的 `stage_min`，不按用户、不按地区 |
| A5 先改提示词与抓取链；位图生成可配置、默认关 | 遵守，但**把「按阶段的插画遍历」也默认关**（`WD_IMAGE_KID_STAGE_MAX=0`） | 偏离点：A5 没说插画链要默认关。理由：Openverse `category=illustration` 的真实返回是 350×400 以下的剪贴画 `[verify image-memorability 遗漏 5]`，Commons `filetype:drawing` 的首批命中含 `Apple structure.svg` 这类结构图 `[verify images-pipeline-31]`，质量在没有 200 词试点前不可知；默认关让代码可合并、线上行为只多三个无害参数；Mac 上两个用户（用户 2 只选了 `zk`，`current_stage=1`）可立即把 `.env` 设为 1 当试点 |
| A6 新用户默认 K-12；2 个用户迁移规则写死 | 不涉及 | 配图侧第一期不改 `user_settings`；第二期 `image_hint` 列搭 0011 的 `user_settings` 重建（`[A7]` 改 DEFAULT 也要重建） |
| Q7 建议「a 立即做」 | 遵守并加码 | a 的三条全做（去文字、构图约束、`&` 转义）；另把「失败词自动重试、journal 排查」也纳入第一期（INDEX §6.2 第 4 条）；c（插画过滤）做成代码就绪、配置关闭；b（生成位图）第二期 |
| Q9 `EXAMPLE_EN_MIN` 15→10、旧卡不动 | 遵守 | `PREFIX_MIN` 不动（§3.3）；49 张旧内容卡与 30 张旧 SVG 都不自动重做（§3.2.5） |

---

## 3. 详细设计

### 3.1 从 D1 证据到准则，再到代码落点

结论先行：七条准则里五条能在服务端用提示词 / 参数 / 打分落地（第一期），两条（图作提示、不配图的模式）需要展示挂点与设置项（第二期）。

| 准则（INDEX D1 推断） | 证据 | 落到哪 | 阶段如何驱动 |
|---|---|---|---|
| 单一清晰所指 | Nelson 1976 相似性反转、Flack & Horst「一次一图」学到两倍词 `[image-memorability-1/13]` | SVG 系统提示词「exactly one central subject」；content 规则 6 要 1 个主体的场景；打分对肖像/杂物类词降权（P1-6） | kid 段落更强：「nothing else in the frame」 |
| 图中无文字 | 配图帮义不帮形，文字把注意力从词形挪走 `[image-memorability-8]`；现有 SVG 要求底部印词 `[verify images-pipeline O6]` | 系统提示词禁文字；`activate_svg(drop_text=True)` 剥离 `<text>/<tspan>`；打分对 sign/caption/infographic 降权；黑名单 `text|poster|screenshot|document` 保留 | 对所有阶段一致（成人也受益于回忆前不泄露） |
| 去无关细节 | 诱人细节 g ≈ −0.33；儿童更敏感 `[image-memorability-12/13]` | 提示词「plain background, no decorative clutter」；content 规则 6 禁「busy scenes」 | kid 段落「plain light background」 |
| 画例句用到的义项 | 学/测一致性 `[image-memorability-7]`（直接实证缺，`[image-memorability-15]`） | content 规则 6/7：场景必须来自本条内容的某个例句；SVG 用户提示带该例句（≤ 80 字符）作上下文 | 小学例句本身是校园生活语域，场景随之 |
| 抽象词用与 `mnemonic_zh` 对齐的记忆挂钩 | 关键词法 + 文生图提升保持 `[image-memorability-10/11]` | content 规则 7：抽象词的 `image_alt_zh` 写「联想」挂钩；SVG 用户提示在 `mnemonic_zh` 以「联想：」开头时附上 | 不分阶段 |
| 风格一致、构图各异 | `[image-memorability-1]` | 系统提示词固定调色与线型；用户提示给具体场景 | kid / 一般两套固定风格段 |
| 图作提示而非答案；拼写/听写不配图；成人可不配图 | Carpenter & Olson 过度自信 `[image-memorability-6]`；Boers `[8]`；Lotto & de Groot `[7]` | **第二期**：`ImageMeta.hint_safe` + `Settings.image_hint` + 正面按 H 显示（§3.6） | kid 默认开 `image_hint`，成人默认关 |

### 3.2 Claude SVG 路径

#### 3.2.1 现状（已确认）

- 系统提示词一句话，要求「the English word in a `<text>` at the bottom (font-size 40 …)」，没有受众、没有单一主体/背景约束（`backend/wd/ai/prompts/svg_system.txt:1`）。
- 用户提示 `Draw an illustration for the word "{display}" ({meaning}). Concept: {concept}。`，`concept = content.image_alt_zh or meaning`，各截 60 字（`backend/wd/ai/svg.py:32-33,40-52`）；`prompt_for` 没有 `cfg`、不看 `stage_min`（`:48-52`）。
- 清洗：`_parse` 用 `defusedxml` 解析，解析失败即 `SvgRejected("not well-formed XML: …")`（`images/sanitize_svg.py:73-76`）；`text`/`tspan` 在元素白名单内（`:28-31`）。
- 激活：`store.activate_svg` → `clean` → 写文件 → `activate(provider='claude_svg', license='generated', mime='image/svg+xml')`，`query`、`provider_ref` 留 NULL（`images/store.py:152-174`）。
- 线上：34 次 `kind='svg'` 调用 $0.4207，$0.01237/次，829 输出 token，7.9 s；30 张交付，4 张被拒（jobs 45/88/97/136：election、employee、property、have；错误位置 line 1 column 224/226/402/410）→ $0.0140/张交付（副本 SQL 见 §5.3）。拒收的具体触发字符需看线上 `claude-logs/`（本任务禁区）；column 224–410 都在前 500 字符内，`<text>` 在底部应在文档尾，所以更可能是 `<title>`/`<desc>` 里的裸 `&`（推断，中）。

#### 3.2.2 系统提示词 v2（`svg_system.txt`，整文件替换）

```
Produce a simple, flat-style educational illustration as a single SVG string for the given English word, Chinese concept and example sentence, to help a learner remember the word's meaning. Hard constraints: viewBox="0 0 800 500"; use only these elements: svg g rect circle ellipse line polyline polygon path defs linearGradient radialGradient stop title desc; NO text of any kind — no <text>, no <tspan>, no letters, digits, labels, signs or glyph-like shapes anywhere in the picture (the learner must recall the word from the picture alone); no <script>, no <foreignObject>, no <image>, no <use>, no external references (href, xlink:href, url(...)), no event attributes, no CSS. Composition: exactly ONE central subject (or one clear two-element scene when the concept needs it) on a plain, light, uncluttered background; nothing decorative that is unrelated to the meaning; the subject fills 50–80% of the frame; no faces in detail (simplified heads are fine). Style: 3–5 harmonious flat colours from the palette the Style line names, bold rounded outlines, large shapes, consistent across words. Escape & as &amp; and < as &lt; inside <title> and <desc>; prefer leaving both empty. Total length at most 8000 characters. Return {svg, alt_zh} where alt_zh is one Chinese sentence (≤ 30 characters) describing what the picture shows.
```

依据：无文字 `[D1]`；单一主体 + 素净背景 `[image-memorability-1/12/13]`；转义要求对应 `[images-pipeline-36]` 的失败类。
不改 `svg_v1.json`（schema 与 `docs/CLAUDE_INTEGRATION.md` §4.4、`tests/fixtures/claude_schemas.json` 三方逐字节绑定，`backend/tests/unit/test_schemas.py:24-30,56-62`）。`alt_zh` ≤ 30 字只是提示词软要求，`store.activate_svg` 继续截 200（`store.py:166`）。
`docs/CLAUDE_INTEGRATION.md:279-285` §5.5 的代码块手工同步（该块没有测试绑定，但契约文档要求一致）。

#### 3.2.3 用户提示 v2 与按阶段的风格段落（`ai/svg.py`）

```python
SVG_PROMPT_VERSION = "v2"                # written to word_images.query as "svg:v2" (see 3.2.4)
EXAMPLE_MAX = 80
HOOK_MAX = 60
STYLE_KID = ("Audience: a 7–11-year-old primary-school learner. Palette: bright and friendly (sky blue, grass green, sun yellow, warm red). "
             "Shapes: thick rounded outlines, big simple forms, one friendly subject, nothing else in the frame.")
STYLE_GENERAL = ("Audience: teenage or adult learner. Palette: muted and modern (navy, teal, sand, coral, grey). "
                 "Shapes: clean flat forms, one clear subject or a simple two-element scene, plain background.")

def build_user_prompt(display, meaning, concept, *, kid: bool, example: str = "", hook: str = "") -> str:
    head = f'Draw an illustration for the word "{display}"' + (f" ({meaning[:MEANING_MAX]})" if meaning else "") + "."
    parts = [head]
    if concept: parts.append(f"Concept: {concept[:CONCEPT_MAX]}。")
    if example: parts.append(f"Example sentence (draw this situation): {example[:EXAMPLE_MAX]}")
    if hook:    parts.append(f"Memory hook to echo: {hook[:HOOK_MAX]}")
    parts.append("Style: " + (STYLE_KID if kid else STYLE_GENERAL))
    return " ".join(parts)

def prompt_for(conn, word, *, kid_stage_max: int) -> str:
    content = _active_content(conn, word) or {}
    meaning = str(content.get("meaning_zh") or dictionary_hint(word.get("translation")) or "")
    concept = str(content.get("image_alt_zh") or meaning)
    examples = content.get("examples") or []
    example = str(examples[0].get("en") or "") if examples and isinstance(examples[0], dict) else ""
    mnemonic = str(content.get("mnemonic_zh") or "")
    hook = mnemonic if mnemonic.startswith("联想") else ""
    stage_min = word.get("stage_min")
    kid = stage_min is not None and int(stage_min) <= int(kid_stage_max)
    return build_user_prompt(str(word["display"]), meaning, concept, kid=kid, example=example, hook=hook)
```

- `handle_generate_svg` 第 115 行改为 `user_prompt=prompt_for(conn, word, kid_stage_max=cfg.image_kid_stage_max)`；`words.word_row` 是 `SELECT *`（`services/words.py:204-206`），`stage_min` 已在行里。
- 风格段落放在**用户提示**而不是系统提示词：一次调用只加载一份系统提示词并 `lru_cache`（`[ai-prompts-stages-2]`），系统提示词保持一份便于文档同步。
- `kid` 的判定与 Q1 解耦：Q1 选重编号 1..5 时把 `WD_IMAGE_KID_STAGE_MAX` 设 2；选「小学 = 0」时设 1；选字符串码时在 `stage_to_index` 的替代物上取整数秩。
- 对照 `test_claude_fixtures.py:95` 与 `test_openai_http.py:62`：它们把字面量提示词喂给假 `claude`，不经 `prompt_for`，不受影响；`fake_claude.svg_word` 用正则 `for the word "([^"]+)"` 取词（`fake_claude.py:160-162`），新提示词仍含该片段。

#### 3.2.4 清洗加固（`images/sanitize_svg.py`、`images/store.py`）

1. **裸 `&` 修复**（`_parse`，在 `:70` 去掉 XML 声明之后、`:74` `DET.fromstring` 之前）：
   ```python
   BARE_AMP_RE = re.compile(r"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")
   text = BARE_AMP_RE.sub("&amp;", text)
   ```
   `ENTITY_RE`（`:48`，`<!ENTITY`）的拒绝在它之前执行（`:67-68`），修复不会放行实体声明。裸 `<` 无法安全修复，仍按「not well-formed」拒。
2. **剥离文字**：`clean(svg, *, drop_text: bool = False)`；`drop_text=True` 时 `_serialise`（`:137-166`）把 `text`/`tspan` 当作不在白名单的元素连子树丢弃（`:139-140` 已有该分支）；`title`/`desc` 保留（在 `<img>` 中不可见，`media.py:27` 的 CSP 也不允许任何脚本）。`store.activate_svg(..., drop_text: bool = True)` 默认剥离；`prompt_version: str | None = None` 新参数写入 `word_images.query`（见下）。
3. **版本标记**：`word_images` 没有 `prompt_version` 列；第一期不加迁移，复用对 SVG 行一直为 NULL 的 `query` 列（`0001_init.sql:250` 注释「image keyword that produced it」；`store.py:110` 对 SVG 传 NULL）写 `svg:v2`。约定写进 DESIGN §9；第二期 0011 加真正的 `prompt_version` 列并从 `query LIKE 'svg:%'` 回填（§3.5.3）。它是第二期 `hint_safe` 判定的依据：`provider='claude_svg' AND query='svg:v2'` ⇒ 无文字。
4. **`&` 修复不改变**现有「not well-formed」的测试：`test_sanitize_svg.py:119-130` 的 `malformed` 用例是 `<rect></svg>`（标签不闭合），不是裸 `&`；`:158-170` 的 `A &amp; B` 已转义，经 `BARE_AMP_RE` 不变（负向前瞻命中 `amp;`）。

#### 3.2.5 旧卡处理与成本预期

- **30 张旧 SVG 不动**（Q9 建议一致）：它们底部印词，在第二期开启「图像提示」前无害；第二期的 `hint_safe` 把它们排除在正面提示之外即可。要重画，管理员用 `POST /api/admin/words/{id}/refetch-image {provider:"claude_svg"}`（`routers/admin_ops.py:413-427`）或 `wd fetch-image <word> --provider claude_svg`（`images/handler.py:139-146,352`），逐词 ≈ $0.0124，30 张 ≈ $0.37–0.42。
- **成本预期**：单次调用价不变（$0.01237/次，829 token，与是否画字关系不大）；拒收从 11.8% 降到接近 0（`&` 修复覆盖最可能的失败类；去文字进一步缩小表面），交付价从 $0.0140 向 $0.0124 靠拢，`WD_AI_SVG_DAILY_BUDGET_USD=0.50` ≈ 40 张/天（`0.50/0.01237=40.4`）。预算检查与子额度不变（`ai/budget.py:272-276`），只改 `:273` 注释的数字。
- **风险**：去掉文字后 Claude 可能把「词义」画得更抽象（没有文字兜底）；由 §3.7 的人工评分验证。`drop_text` 对老式「带标签的示意图」（如 ballot 上的 VOTE）会留下空白框——可接受，且新提示词已禁文字。

### 3.3 content 生成侧

#### 3.3.1 结论

**不加新字段**。`image_keywords`（英文检索短语）+ `image_alt_zh`（≤ 30 字中文场景）在语义改写后足够喂三条链：照片检索用 `image_keywords`；SVG 用 `image_alt_zh` + 首条例句（§3.2.3）；第二期的智谱位图生成原生支持中文提示，`image_alt_zh` + 固定风格前缀即可。`image_scene_en` 只有在接 Recraft 之类纯英文生成器时才需要——不在计划内。加字段的 10 处改动面列于 3.3.4 备查。

#### 3.3.2 提示词 v2（`content_system.txt`）

- 规则 6（`:9`）改为：
  ```
  6. image_keywords: exactly 2–3 short, concrete English search phrases (2–4 words each) describing ONE scene that one of your example sentences depicts — a single clear subject, no people's faces in close-up, no text, signs or screens, no brands or named people, nothing violent or adult. Most literal first. For abstract words choose the concrete scene your mnemonic or example makes vivid ("negotiate" → "two people shaking hands"), never an unrelated symbol.
  ```
- 规则 7（`:10`）改为：
  ```
  7. image_alt_zh: one Chinese sentence (at most 30 characters) describing that same scene as a picture a child could recognise, and the one detail that links it to the meaning; for abstract words start with "联想：" and echo mnemonic_zh.
  ```
- 规则 3（`:6`）追加一句：
  ```
  When the word's stages list contains 初中 (or a lower stage), make at least two of the sentences 4–10 words long, present tense, about school, family, food, animals, weather or play, using only everyday vocabulary, and use the headword's base form in at least two sentences.
  ```
  阶段标签已经逐词进入用户提示（`content.py:88` `"stages": [STAGE_ZH[s] …]`），不需要新字段；一个 group 混合阶段时规则按词触发（`[ai-prompts-stages-2]`）。等 Q1 落地「小学」阶段后，把 `STAGE_ZH`（`content.py:49`）与 `schemas.STAGE_NAMES_ZH`（`schemas.py:52`）一起加码，这句话自动覆盖（注意 `[verify ai-prompts-stages 遗漏 1]`：只加 `words.STAGES` 不加 `STAGE_ZH` 会 `KeyError`）。
- 规则 1 的「词典体」不改（`:4`）：白话释义属于 Q9 的产品决定；若要做，只需在同一句加「for 初中 and lower, plain spoken Chinese without POS labels」，后验证只要求 1–120 字含 CJK（`content.py:139-141`）。
- `CLAUDE_INTEGRATION.md` §5.1 的提示词代码块同步（无测试绑定）。

#### 3.3.3 常量与版本

- `EXAMPLE_EN_MIN` 15 → 10（`content.py:54`）；`docs/CLAUDE_INTEGRATION.md:355` 「`en` 15–240 chars」→「10–240」。线上 195 条例句最短 33 字符（`[verify ai-prompts-stages-5]`），对已有内容零影响；"I like cats."（12）通过，"Go home."（8）仍丢——可接受。`backend/tests/unit/test_content_apply.py` 没有钉死 15 的断言（grep `EXAMPLE_EN_MIN|too short|len(en)` 无命中），新增一条「10–14 字符例句被保留」的用例。
- `PREFIX_MIN` 保持 4（`content.py:63`）：放宽会让 3 字母词的前缀匹配（`cat`→`category`）误判词头出现；小学短词的屈折形式大多在 `word_forms`（3 字母词 309 个只有 23 个无屈折行，且多为功能词，`[ai-prompts-stages-11]`），加上提示词「base form in at least two sentences」已够。
- `PROMPT_VERSION` → `content-v2`（`content.py:46`）：否则新旧卡无法从 `word_contents.prompt_version` 区分，§3.7 的试点无法按版本分组。影响面（grep 全仓库 `content-v1`）：`test_content_apply.py:81` 的断言改为 `content.PROMPT_VERSION`；其余 10 处都是测试夹具里的 INSERT 字面量（数据，不比较）；`docs/CLAUDE_INTEGRATION.md:206` 与 `docs/WORD_LIBRARY_CURATION.md:65,183` 的文字改为「当前 `PROMPT_VERSION`（`content-v2`）」。行为影响：`select_jobs` 对「`ready` 且版本相同」才跳过（`content.py:405`），但所有入队点只给 `none/failed` 的词排任务（`services/bank.py:489-492`、`ai/prewarm.py:48`），49 张 `content-v1` 卡不会被重做；唯一例外是夜间 `requeue_dead_once` 复活的旧 dead 任务（`jobs/scheduler.py:298`）会按新版本重生成——可接受（`[ai-prompts-stages-10]`）。

#### 3.3.4 若将来加字段（备查，不在本期）

`content_v1.json:9-12`（properties + `required`）→ `docs/CLAUDE_INTEGRATION.md` §4.1 代码块逐字节同步 → `backend/tests/fixtures/claude_schemas.json` 同步（`test_schemas.py:56-62`）→ `content_system.txt` 新规则 → `ai/models.py:34-44 ContentItem`（`extra="ignore"`，未声明键在 `valid_items` 被丢，`:15-18,113-126`）→ `content.py:131-203 validate_item` 显式 cleaned 字典（`:189-201`）→ `schemas.py:549-563 Content`（新字段必须 `Optional` 带默认：`schemas.py:87-90` `extra="forbid"`，旧 49 行缺键会 500）→ `frontend/src/api/types.ts:70-74` → `docs/API.md:304-308`（三者同一提交，`API.md:3`）→ `backend/tests/fixtures/claude_content_ok.json`、`backend/tests/fake_claude.py:170-199 content_item`、`test_content_apply.py:80`（14 键断言）、`scripts/eval_provider.py:115 CONTENT_ITEM_KEYS`。约 10 个文件，半天到一天。

### 3.4 照片 / 插画抓取链

#### 3.4.1 搜索词构造与消歧（P1-3）

现状：关键词 = 管理员 `query` → `content.image_keywords[:3]` → 裸 `lemma`（`handler.py:134-137`，`:78` 回退），回退值不过形状规则与黑名单（`[verify images-pipeline-9]`）；管理员 `query` 含中文/数字/超 41 字符会被 `clean_keywords` 静默丢弃（`:71`；schema 允许 100 字符，`schemas.py:1351`）。

改动：
1. **功能词门**（`handler.fetch_for_word`，在 `:134-137` 之后）：当关键词只剩 `[lemma]`（没有内容关键词、也没有管理员 `query`）且词的 ECDICT `pos` 中功能词码（`a` 冠词/限定、`i` 介词、`c` 连词、`p` 代词、`d` 限定词、`t` 不定式标记、`x` 否定、`u` 感叹——与前端 `frontend/src/utils/pos.ts:8-20` 的 `POS_LABELS` 同一套码）合计 ≥ 80% → 不发任何 provider 请求，直接进入 `:201-206` 的 SVG/模板卡分支，`detail="function word: photo search skipped"`。`words` 的 SELECT（`:121-124`）加 `pos, stage_min`。线上 `stage_min=1` 的 2,012 个单词里 n/v/adj/adv 首位的有 1,763 个、其它（含功能词）207 个（副本 SQL 见 §5.3），门只影响后者。
2. **黑名单分级**（`select.py:20-24`）：
   ```python
   SAFETY_RE = re.compile(r"\b(nude|nudity|sex|porn|gore|corpse)\b", re.I)                      # never allowed
   KID_SAFETY_RE = re.compile(r"\b(blood|weapon|gun)\b", re.I)                                 # never allowed in kid style
   RELEVANCE_RE = re.compile(r"\b(map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document|blood|weapon|gun)\b", re.I)
   def is_blocked(text, *, allow: frozenset[str] = frozenset(), kid: bool = False) -> bool
   ```
   `reject_reason(cand, exclude, *, allow, kid)`、`rank(..., allow, kid)`；handler 以 `allow = {tok for tok in keyword_tokens(kw) if RELEVANCE_RE.fullmatch(tok)}` 调用——查 `world map` 时允许标题含 `map`，查 `apple` 时仍拒 `map`。`BLOCKLIST_RE` 保留为三者并集（`content.py:67-69` 的 `_is_blocked` 仍用它过滤 Claude 关键词，行为不变）。
3. **`query` 回退可见化**：`clean_keywords` 返回 `(keywords, dropped)`；当管理员 `query` 被丢弃时 `log.warning(..., extra={"event": "query_ignored"})` 并在 `FetchOutcome.detail` 追加 `query ignored (shape/blocklist)`。API 仍 202（契约不变）。
4. `MAX_KEYWORDS` 保持 3（`:37`）：线上没有任何内容带第 4 个关键词（`[verify images-pipeline-2]`），提示词 v2 改为「exactly 2–3」。

#### 3.4.2 风格管道与按阶段选择（P1-4 核心）

- `interfaces.ImageProvider.search(self, query: str, limit: int, *, style: str = "photo")`（`backend/wd/interfaces.py:73-79`，`runtime_checkable` 只查属性存在，`test_providers.py:49` 的 `isinstance` 不受影响）；四个 provider 的 `search`/`params` 接受 `style`。
- 新配置 `WD_IMAGE_KID_STAGE_MAX`（`Settings.image_kid_stage_max: int = 0`，`integer(..., 0, 0, 9)`；`config.py:155-168` 字段区、`:522-534` 解析区、`deploy/env.example:149-165` 图片段、`docs/DEPLOY.md:338-345` 表格）。`0` = 关闭（`stage_min` 最小为 1，`[A3]`）。
- `handler.fetch_for_word`：`kid = stage_min is not None and stage_min <= cfg.image_kid_stage_max`；`styles = ("illustration", "photo") if kid else ("photo",)`；外层循环 `for style in styles: for kw in keywords: for p in chain: …`，`p.search(kw, SEARCH_LIMIT, style=style)`，`select.rank(cands, kw, excluded, used_refs=…, style=style, allow=…, kid=kid)`。CLI `wd fetch-image` 加 `--style {auto,photo,illustration}`（默认 `auto`）供试点逐臂运行（`handler.py:349-356`）。
- 请求预算：kid 词最坏 2 × 3 × 2 = 12 次（默认链两家），受 `WD_OPENVERSE_MINUTE_LIMIT=15`/`DAILY=160`、`WD_WIKIMEDIA_DAILY_LIMIT=2000`（`quota.py:37-47`）兜底；按日批次 10–30 词估算不会触顶（推断，中）。
- 展示：插画候选来自 `wikimedia/openverse`，`image_meta` 会标 `kind='photo'`（`service.py:58,73`），前端 `object-fit: cover`（`study.css:460`）可能裁掉剪贴画边缘——第一期已知限制；第二期 `ImageMeta.style` 让前端对 `illustration` 用 `contain`（§3.6）。

#### 3.4.3 provider 参数（P1-4）

| provider | 改动 | 依据 | 测试影响 |
|---|---|---|---|
| Wikimedia（`providers/wikimedia.py`） | `params(query, limit, *, style)`：`gsrsearch = f"{query} filetype:drawing"`（插画）/ `filetype:bitmap`（照片）；`iiprop = "url|extmetadata|size|mime|thumbmime"`；新增 `maxlag: 5`。`parse_search:97` 改 `mime = info.get("thumbmime") or info.get("mime") or mime_from_url(...)`（下载的是 `thumburl`，SVG 原件的缩略图是 PNG）。`search()` 在 `get_json` 后检查 `data.get("error", {}).get("code") == "maxlag"` → `raise ProviderError("wikimedia: maxlag", status=503, retry_after_s=30)`（MediaWiki 对 maxlag 回 200 + `error` 体，`base.get_json:106-111` 只对 ≥ 400 抛错，所以要显式处理） | `[verify images-pipeline-31/O5]`（`thumbmime=image/png`，原 `mime=image/svg+xml` 会被 `select.py:65-66` 拒）；API:Etiquette 非交互任务用 `maxlag`（`[images-pipeline-46]`） | `test_providers.py:46-69` 的参数字典断言加 `thumbmime`/`maxlag`；`test_images.py:139,540,545` 的 `gsrsearch` 断言不变（默认 photo）；新增 `test_wikimedia_drawing_style_uses_thumbmime` 用内联夹具（不改「as captured」的 `wikimedia_search.json`，`test_providers.py:70`）；新增 `test_wikimedia_maxlag_error_becomes_a_short_cooldown`（`test_images.py` 仿 `:350`） |
| Openverse（`providers/openverse.py`） | `PAGE_SIZE` 常量 → `params(query, limit, *, style)`：`page_size = max(1, min(int(limit), 20))`（20 → 10）；插画时加 `category: "illustration"`，照片时 `category: "photograph"`（排除 `digitized_artwork`）；`parse_search:114-119` 的 `extra` 加 `"category": r.get("category")`（夹具 `openverse_search.json` 已含该字段，`[verify images-pipeline-11]`） | `[verify images-pipeline O2]`：每次取 20 只用 10；`[image-memorability-24]` 参数枚举 | `test_providers.py:178` 与 `test_images.py:162` 的 `page_size "20"` → `"10"`（且多一个 `category`）；`test_smoke_mock.py:33` 直接请求 `page_size=20` 的 mock 不受影响 |
| 尺寸门槛（`select.py:30`） | `MIN_SIZE = {"photo": (400, 300), "illustration": (240, 180)}`；`GOOD_WIDTH` 加分不变 | `[verify image-memorability 遗漏 5]`：剪贴画 350×400/319×338/210×210 全被硬拒；`fetch.normalise_image` 只缩不放（`fetch.py:264-265`），小图会以原尺寸入库，前端 `contain` 后看着小——试点评分项 | `test_select.py:71` `test_hard_rejects` 的 `size` 行不变；新增 style 参数用例 |
| Pixabay（`providers/pixabay.py:30-39`） | 插画时 `image_type: "illustration"`，照片时保持 `"photo"`；两者都加 `orientation: "horizontal"`；`lang` 保持 `en` | `[image-memorability-22]` 官方参数 | `test_providers.py:351` 断言 `image_type == "photo"` 仍成立；加 `orientation` 断言与插画用例。仅给了 key 才生效，线上无 key |
| Pexels（`providers/pexels.py:29-30`） | 不改（没有插画过滤；`locale` 对英文关键词无益） | — | — |

两家境外 provider 的条款/限额约束（必须写进 DESIGN §9 与 ATTRIBUTION §3）：Pixabay「Systematic mass downloads are not allowed」+ 缓存 24 h + 禁热链 → 只按需抓、不全库预抓；Pexels 200/h、20,000/月（全库 1 关键词 = 月配额 46%）；Openverse 匿名 20/min、200/day（响应头实测，`[verify images-pipeline O1]`），本地 15/160 仍在其下；Commons 无硬性日配额但要求串行 + 有意义 UA + `maxlag`（`[images-pipeline-4/46]`）。

#### 3.4.4 失败词自动重试（P1-5）

现状：`fetch_image` 只有两类入队点——内容落地（`content.enqueue_image`，`content.py:253-261,347`）与用户/管理员动作（`service.enqueue_fetch` 的三个调用者）；`image_state='failed'` 的词被学习时不重抓，也没有定时重试（`[images-pipeline-25]`）。线上 18 个 failed 词里 17 个现在都在学（5 个 `learning`，11 个 `known` 但在未完成批次里，`have` 为 `new`；`employee` 是 `known` 且没有开放批次项），副本 SQL 见 §5.3。

设计（全部在 `images/service.py`，不加任务类型、不改 `jobs.type` CHECK）：

```python
RETRY_MIN_AGE_HOURS = 6
RETRY_MAX_AUTO_30D = 3
RETRY_NIGHTLY_LIMIT = 50

def retry_due(conn, word_id, now) -> bool:
    """image_state='failed' AND the newest fetch_image job for the word (dedupe_key 'image:<id>' or 'image:<id>:r%')
    is not queued/running and finished >= RETRY_MIN_AGE_HOURS ago (or none exists) AND fewer than RETRY_MAX_AUTO_30D
    jobs with payload retry=true were created for it in the last 30 days."""

def enqueue_retry_if_failed(conn, word, *, images_enabled: bool, priority: int, now: str) -> int | None:
    if not images_enabled or word.get("image_state") != "failed" or not retry_due(conn, int(word["id"]), now):
        return None
    return enqueue_fetch(conn, int(word["id"]), priority=priority, now=now, retry=True)   # payload {"word_id", "retry": true}

def retry_failed_studied(conn, now, *, images_enabled: bool, limit: int = RETRY_NIGHTLY_LIMIT, priority: int) -> int:
    """03:30 sweep: words with image_state='failed' that word_is_studied() and retry_due(); oldest failure first."""
```

- 触发点 1：词进入生词库——`services/bank.py:636` 与 `:659` 紧随 `enqueue_content_if_needed` 之后调用（`cfg` 用 `from ..config import get_settings` 懒加载，与 `jobs/scheduler.py:250-253` 同法）。
- 触发点 2：词进入批次——`services/batches.py:639` 同样紧随其后。
- 触发点 3：夜间 `scheduler.maintenance`（`jobs/scheduler.py:364-380`）在 `prefetch` 之后调用 `retry_failed_studied(..., priority=PREFETCH_PRIORITY)`（30 < 90，Openverse 与 SVG 都允许，`handler.py:158-159,203`）；`TickResult` 加 `image_retries: int`。
- 触发点 4（运维）：`wd images-retry [--limit N] [--dry-run]`，注册在 `images/handler.py:349-361` 的 `register_cli`，并加入 `cli.py:54` `COMMAND_OWNERS["wd.images.handler"]`（`test_cli.py:56-58` 只要求命令集合一致）与 `docs/DEPLOY.md:417` 的命令清单。
- `enqueue_fetch` 加 `retry: bool = False` 写入 payload（`service.py:155-183`）；`handler.handle_fetch_image` 忽略该键（旧代码回退也忽略）。去重键仍是 `image:<id>`，与用户的「换一张」自然合并（`_fold_into_live`，`:117-136`）。
- 不改 `_svg_allowed`/`word_is_studied`：重试后若 provider 仍失败，词正在学就会再排 `generate_svg`（`dedupe svg:<id>`，上一任务已 done，可新建），用新提示词重画——这正是 `have/employee/property` 三个被拒 SVG 的修复路径（`employee` 不在学，保持卡片）。
- 预期：部署后第一晚最多补抓 17 个词；`provider_state` 两家现在都在冷却（到 11-05 13:28/13:33Z），之后恢复。

#### 3.4.5 打分新信号（P1-6）

`select.score(cand, keyword, *, used_refs, style="photo")`（`select.py:80-101`）在现有 7 个信号之外加：

| 信号 | 规则 | 依据 |
|---|---|---|
| 描述命中 | 任一关键词 token 出现在 `extra.description`/`object_name` 而不在 title/tags 中 → +1（上限 1） | `[verify images-pipeline-11]`：描述只用于拒绝不用于打分 |
| 类目一致 | Openverse `extra.category == "illustration"` 且 style=illustration → +2；`== "photograph"` 且 style=photo → +1；Pixabay `extra.type in ("illustration","vector")` 且 style=illustration → +2 | `[D2]` 无类目信号；`pixabay.py:78` 已存 `type` |
| 人物特写降权 | title/tags 命中 `\b(portrait|selfie|headshot|close-?up|faces?)\b` → −2 | `[D1]` 无人脸特写；`[verify ai-prompts-stages 遗漏 3]` 儿童向安全控制薄 |
| 文字类降权 | 命中 `\b(sign|signage|caption|typography|infographic|label|banner)\b` → −1（`text|poster|screenshot|document` 仍硬拒） | `[D1]` 无文字 |
| 竖图降权 | `width/height < 1.0` → −1（硬界 0.6–2.2 不变） | 16:10 `cover` 盒竖图只剩 ≈ 40%（`[images-pipeline-11]`） |

`test_select.py:92-119` 的每一行断言仍成立：默认候选 `title="Red apple on a table"`, `tags=["apples"]`, 无 `description`, 宽高比 ≥ 1.09，不触发任何新信号；新增一组断言。`docs/DESIGN.md:547`（Selection 段）同步。`word_images.score` 仍存这个选择分（`0001_init.sql:266`）；VLM 质量分第二期另起列（§3.7.3）。

### 3.5 生成式位图 provider（第二期，默认关闭；本节是设计不是本周代码）

#### 3.5.1 适配器

- 文件 `backend/wd/images/providers/generative.py`，类 `GenerativeImageProvider(name="zhipu_image")`，**不实现 `ImageProvider.search`**（它不检索），实现 `generate(prompt: str, *, size: str) -> Generated(url, content_filter: int | None, raw: dict)`：`POST {base_url}/images/generations`，body `{"model", "prompt", "size", "watermark_enabled": true, "user_id": <hash>}`（智谱 `/api/paas/v4/images/generations`，`model ∈ cogview-3-flash / cogview-4 / glm-image`，返回 `data[].url`、`content_filter`，URL 30 天有效，`[image-memorability-26]`）；OpenAI 格式兼容（火山方舟同路径形状，`[image-memorability-28]`）。下载走现有 `fetch.download_and_store`（https、公网 IP、`image/*`、JPEG/PNG/WebP、≤ 8 MB，`fetch.py:124-237`）→ 入库前经 §3.5.4 的隐式标识写入。
- 配置（`Settings`，全部有默认且默认不启用）：`WD_IMAGE_GEN_KIND=""|"openai_images"`、`WD_IMAGE_GEN_BASE_URL`、`WD_IMAGE_GEN_MODEL="cogview-3-flash"`、`WD_IMAGE_GEN_KEY` / `WD_IMAGE_GEN_KEY_FILE`、`WD_IMAGE_GEN_SIZE="1344x768"`（最接近 16:10 的枚举档，`[image-memorability-26]`）、`WD_IMAGE_GEN_MINUTE_LIMIT=5`、`WD_IMAGE_GEN_DAILY_LIMIT=100`、`WD_IMAGE_GEN_STAGE_MAX`（默认 = `WD_IMAGE_KID_STAGE_MAX`）。`WD_IMAGE_GEN_KEY` 加入 `SECRET_KEYS`（`config.py:64-72`：被 `GET /api/admin/config` 掩码为 `***` 且不入日志的名单，现含 `WD_OPENVERSE_CLIENT_SECRET`/`WD_PIXABAY_KEY`/`WD_PEXELS_KEY`）。
- 位置：`handler.fetch_for_word` 在所有检索 provider 失败之后、SVG 之前：`if cfg.image_gen_enabled and kid and service.word_is_studied(...) and quota.allow(conn, "zhipu_image", cfg, now): generated = provider.generate(prompt_for_generation(content, word))`，成功即 `store.activate(provider="zhipu_image", license="generated", source_url=url, query="gen:<model>", alt_zh=image_alt_zh, ...)`，失败/过滤则落到现有 SVG 分支。IoWorker 单线程（`jobs/worker.py:359-362`），一次生成 5–20 s 可接受；不新增任务类型（避免重建 `jobs`）。
- 提示词：`"{风格前缀（与 §3.2.3 的 STYLE_KID 同义的中文）}。画面：{image_alt_zh}。情境：{例句中文译文 ≤ 40 字}。画面中不出现任何文字、字母、数字。"`；负面约束由 provider 的 `content_filter` 与我们的 SAFETY/KID_SAFETY 词表双重把关（关键词或 lemma 命中则不生成）。
- 预算：免费模型零成本；`provider_usage` 的分钟/日窗口计数复用（`quota.limits_for` 加分支）；不写 `ai_calls`（它的 `kind` CHECK 只有 content/lookup/consolidate/svg/probe，`0001_init.sql:511`；免费模型无成本可记）。换到 `cogview-4`（¥0.06/次）时再决定是否入 `ai_calls` 台账（需迁移 `kind` CHECK）。与 `WD_AI_SVG_DAILY_BUDGET_USD` 的关系：生成成功的词不会再排 SVG（`has_active`），所以 SVG 子额度自然下降；两者互不计入。

#### 3.5.2 契约与数据模型改动面（全部第二期）

- `word_images.provider` CHECK（`0001_init.sql:248`）加 `'zhipu_image'`（或泛化为 `'generated'`）→ 整表重建（见 3.5.3）。
- `schemas.ImageProviderName`（`schemas.py:46`）、`frontend/src/api/types.ts:84`、`docs/API.md:318` 同一提交加值（`scripts/check_contract.py:275-281` 按顺序比对字面量联合）；`ImageMeta.kind` 加 `'generated'`（`schemas.py:579`、`types.ts:83`、`API.md:317`）；`service.image_meta:57-73` 的 `is_svg` 二分改为按 provider 查表：`claude_svg → svg`、`zhipu_image → generated`（无署名）、其余 → photo；`service.photo_mix:241-242` 的 provider 列表不含生成，新增 `with_generated` 计数 → `AdminOverview.words`（`API.md:420-421`、`schemas`、`types.ts`）。
- 前端：`WordImage.imageCaption`（`WordImage.tsx:26-33`）对 `kind === 'generated'` 显示 `zh.word.aiPicture: 'AI 生成配图'`（`zh.ts:54` 同行；`docs/FRONTEND.md` §8 镜像块同步，`zh.test.ts:67` 逐行比对）；`kind !== 'photo'` 已走 `contain`（`WordImage.tsx:50`，`study.css:465-467`）。
- `ATTRIBUTION.md` §3.4 加一条「AI 生成配图（智谱）」；智谱用户协议禁止去除其标识（`[image-memorability-26]`）。

#### 3.5.3 迁移 0011（与阶段模型切片的 0011 合并发布；若分开则为 0012）

`word_images` 重建（SQLite 无 ALTER CONSTRAINT，`[A4]`）：
```sql
CREATE TABLE word_images_new (... provider TEXT NOT NULL CHECK (provider IN ('wikimedia','openverse','pixabay','pexels','claude_svg','zhipu_image')), ...,
  style TEXT NOT NULL DEFAULT 'photo' CHECK (style IN ('photo','illustration','svg','generated')),
  prompt_version TEXT, eval_json TEXT, ...);
INSERT INTO word_images_new (<old columns>, style, prompt_version)
  SELECT <old columns>, CASE provider WHEN 'claude_svg' THEN 'svg' ELSE 'photo' END,
         CASE WHEN provider = 'claude_svg' AND query LIKE 'svg:%' THEN substr(query, 5) ELSE NULL END FROM word_images;
UPDATE word_images_new SET query = NULL WHERE provider = 'claude_svg';
DROP INDEX ix_word_images_word; DROP INDEX ix_word_images_sha; DROP INDEX ux_word_images_active;
DROP TABLE word_images; ALTER TABLE word_images_new RENAME TO word_images;
CREATE INDEX ix_word_images_word ON word_images(word_id, status); CREATE INDEX ix_word_images_sha ON word_images(sha256);
CREATE UNIQUE INDEX ux_word_images_active ON word_images(word_id) WHERE status = 'active';
```
`words.active_image_id` 是逻辑外键（`0001_init.sql:199` 注释「logical FK → word_images.id」，`:198` 对 `active_content_id` 写明「no constraint: avoids a cycle」），重建不触发级联；运行器自己关/查外键（DEPLOY §5）。排练前要确认 `v_bank` 视图不引用 `word_images`（`[A4]` 的 RENAME 陷阱只对被视图引用的表成立）。`docs/SCHEMA.sql` 不动（它只镜像 0001）。`user_settings.image_hint INTEGER NOT NULL DEFAULT 0 CHECK (image_hint IN (0,1))` 搭 Q1/Q6 的 `user_settings` 重建（`[A7]`）；Q6 的 K-12 预设在注册/引导时把它置 1。

#### 3.5.4 《人工智能生成合成内容标识办法》的实现

- **显式标识**：UI 题注已有「AI 生成示意图」（`zh.ts:54`）；生成位图用「AI 生成配图」；智谱 `watermark_enabled=true` 保留其水印（关水印需签免责声明，`[verify image-memorability-26]`）。
- **隐式标识（文件元数据）**：`fetch.normalise_image` 重编码为无元数据 JPEG（`fetch.py:267`），所以 provider 自带的隐式标识会丢——必须由本应用写入。方案：`images/marking.py`：JPEG 在 SOI 后插入一个 APP1 XMP 段（`http://ns.adobe.com/xap/1.0/\0` + 含 `AIGC` 命名空间字段的 XMP 包：`Label`、`ContentProducer`、`ProduceID`、`ReservedCode1`、`ContentPropagator`、`PropagateID`）；SVG 在根元素下追加服务端生成的 `<metadata>`（`sanitize_svg` 清洗之后再拼接，白名单不放开 `metadata`）。GB 45438-2025 对 JPEG/PNG/SVG 的字段命名与放置位置本文**未读到原文**（`[verify image-memorability 遗漏 4]` 标「国标原文未读」），实现前必须核对标准文本；Pillow 是否能直接写 XMP 也需在目标 Python/Pillow 版本上验证（未验证）。
- **主体定位**：本应用是否构成「服务提供者」为推断（INDEX 未解决 9）；按「传播生成内容的服务」从严处理，两类标识都做。
- **内容过滤兜底**：`content_filter` 等级 ≥ 1（kid）或 ≥ 2（一般）→ 丢弃并落到 SVG/卡；SAFETY/KID_SAFETY 词不生成；生成图也进 `[verify ai-prompts-stages 遗漏 3]` 指出的「不合适」反馈路径（`reject_active_image`，阈值 1）。

### 3.6 展示与数据模型

**决定：图默认出现在回忆之后（卡片背面，现状），不自动前置；「图作提示」做成第二期的可选、可知情的提示动作。**

- 依据：配图在回忆前出现造成过度自信，只有配合提取练习才兑现收益 `[image-memorability-6]`；配图分走对词形的注意 `[8]`；儿童从图学词优于从词学词 `[7]` 支持「提示」而非「禁用」。现状：图只在背面（`StudyCard.tsx:297-310`），正面有「提示」动作——按 H 显示首条例句的挖空句（`:206-212`、`StudyPage.tsx:559,697-698`）。
- 第二期做法：`Settings.image_hint: boolean`（默认 0；K-12 预设 1）；`ImageMeta.hint_safe: boolean`（服务端：`style='illustration'` 或 `provider='zhipu_image'` 或 `claude_svg AND prompt_version='svg-v2'`；照片默认 false，因为照片可能含文字）；`StudyCard` 正面在 `hint && image_hint && item.image.hint_safe` 时在挖空句上方渲染 `WordImage`（`showImages` 复用），筛词卡（`:171`）永不显示。契约改动：`schemas.py:167,387`、`types.ts:38,80-84`、`API.md:272,314-321` 同一提交；`check_contract.py` 比对属性名。
- **每词多图：不做。** 风格由词的 `stage_min` 决定（全局一张），不按用户分叉。理由：部分唯一索引 `ux_word_images_active`（`0001_init.sql:272`）与 `words.active_image_id` 单指针（`:201`）决定了「按用户选图」要改 `image_meta` 签名、`StudyItem`/`WordDetail` 的组装路径与举报/换图语义（现在都是全局，`[images-pipeline-22/23]`），改动量是数据模型级的；而线上 2 个用户里 zk-only 的用户 2 与四阶段的用户 1 学到同一个 zk 词时看到同一张插画，可接受。第三期若评分显示成人明显排斥插画，再把唯一索引改为 `(word_id, style)` 并给 `image_meta` 加 `style` 参数。
- `show_images` 粒度：保持全局布尔（`0001_init.sql:149`、`schemas.py:167,387`、`SettingsPage.tsx:413`），第二期加 `image_hint`；不引入「按阶段开关」——风格已由词驱动。

### 3.7 评估

#### 3.7.1 200 个小学高频词的选样

词集：`stage_min = 1 AND kind = 'word' AND frq > 0 AND is_public = 1`，去掉功能词（§3.4.1 的 80% 规则，用 `python3 -I` 解析 `pos`），按 `frq` 升序取 200。副本上 `stage_min=1` 的单词 2,012 个、1,960 个有 `frq`，n/v/adj 首位 1,600 个，样本充足；这 2,012 个词里只有 `have` 有内容、0 个有图，所以试点必须先生成内容（200 词 ≈ $0.80，`[CLAUDE_INTEGRATION §7]` $0.004/词）。脚本放 `scratchpad/images-pilot/select_words.py`（不入仓库），输出 `pilot_words.txt`。

#### 3.7.2 流程（私有拷贝 + 出口正常的机器）

1. `cp live-copy.db scratchpad/images-pilot/data/word-dance.db`（绝不写原副本），`WD_DATA_DIR=scratchpad/images-pilot/data`，`.env` 最小化（`WD_IMAGES_ENABLED=1`，`WD_IMAGE_PROVIDERS=wikimedia`，`WD_IMAGE_KID_STAGE_MAX=1`，`WD_SVG_VIA_CLAUDE=0`）。进程环境里**不能**有 `HTTP(S)_PROXY`（`fetch.safe_download` 用 DNS 固定 IP + `sni_hostname`，经 HTTP 代理会 `CERTIFICATE_VERIFY_FAILED`，见用户记忆 2026-11-02 事故）。
2. 内容：`POST /api/admin/prewarm`（priority 90，不抓图）或逐词 `generate_content`；记录 `prompt_version=content-v2`。
3. 臂 A（照片）：`wd fetch-image <lemma> --no-svg --style photo`；臂 B（插画）：`--style illustration`（每词前先 `reject_active_image` 或用新库，避免 `has_active` 短路）；臂 C（SVG v2）：`--provider claude_svg`（200 × $0.0124 ≈ $2.5；受 `WD_AI_SVG_DAILY_BUDGET_USD` 子额度，试点期临时提到 3.00）；臂 D（第二期）：生成位图。
4. 速率：Wikimedia 1 req/s，200 词 × ≤ 6 次 ≤ 20 分钟；Openverse 匿名 160/日只够 ≈ 27 词 × 2 风格 × 3 关键词 → 臂 A/B 的 Openverse 部分抽 50 词，或先注册 Openverse 应用（INDEX §6.2 第 6 条）。
5. journal 事件：`provider_skipped`/`provider_cooldown`/`provider_error`/`image_refused`/`query_ignored`/`image_retry`（`handler.py:162,170,173,178`、`fetch.py:277`）按词汇总，回答 INDEX 未解决 7（11-02 的 18 个任务为何失败）。

#### 3.7.3 评分表与自动评分

人工表（CSV：`lemma, arm, image_path, r1_single, r1_sense, r1_clean, r1_kid, r2_…`），每项 0–2：所指单一可辨认 / 与例句义项一致 / 无文字无面孔无敏感 / 「10 岁孩子看图能想起意思」；两位评分者，报告均值、≥ 5/8 的比例、臂间差异与评分者一致率。决策阈值（建议）：插画臂 ≥ 5/8 的比例高于照片臂 15 个百分点以上才把 `WD_IMAGE_KID_STAGE_MAX` 默认设为非 0。
自动评分（第二期，需智谱 key）：GLM-4.6V-Flash（官方标免费，`[D5]`）对同一三项打分，写入 0011 新增的 `word_images.eval_json`（`{"model","scores":{...},"at"}`），**不覆盖** `score`（它是选择分，`0001_init.sql:266`）；与人工表算 Spearman，一致再用于全库筛选。

#### 3.7.4 文档数字更新（P1-7）

| 位置 | 现文 | 改为 |
|---|---|---|
| `docs/DESIGN.md:28`、`:518`、`:550`；`docs/CLAUDE_INTEGRATION.md:407`、`:416`；`docs/DEPLOY.md:326`、`:434`；`docs/ops.md:198`；`deploy/env.example:83`；`backend/wd/ai/budget.py:273`（注释） | `$0.028`、`≈ 18 cards/day` | `$0.0124/次调用（$0.0140/张交付，拒收 11.8%，2026-11-05 实测 34 次）`、`≈ 35–40 cards/day` |
| `docs/DESIGN.md:546` | Openverse「anonymous limits measured 20/min burst, 200/day」 | 加「（响应头 `x-ratelimit-limit-anon_*` 实测 2026-11-05）」 |
| `docs/DESIGN.md:547` Selection | 7 信号 | 加 §3.4.5 的 5 个信号与风格化尺寸门槛、黑名单分级 |
| `docs/DESIGN.md:523-553` §9 伪代码 | 单风格 | 加 `styles` 外层循环、功能词门、重试规则、`query='svg:<version>'` 约定 |
| `docs/DEPLOY.md:338-345`、`deploy/env.example:149-165` | — | 新增 `WD_IMAGE_KID_STAGE_MAX` 行（`test_deploy_files.py:119` 要求 env.example 与 `Settings` 一一对应） |
| `docs/DEPLOY.md:417` | 命令清单 | 加 `images-retry [--limit N] [--dry-run]` |
| `docs/CLAUDE_INTEGRATION.md:206`、`:279-285`、`:355`、`:401-403` | content-v1 / 旧 SVG 提示词 / 15–240 / 「never retried automatically」 | content-v2 / 新提示词 / 10–240 / 「retried through the failed-image retry rules of DESIGN §9」 |
| `ATTRIBUTION.md` §3（`:34` 起） | — | 加 Pixabay 批量下载条款与 Openverse 限额来源一句 |

### 3.8 分期

- **第一期（本周，零 key）**：P1-1 … P1-7，7 个提交，每个独立可回退；无迁移、无契约改动、无前端改动。合并顺序建议 P1-7（纯文档）→ P1-1 → P1-2 → P1-3 → P1-6 → P1-5 → P1-4（最大、默认关）。
- **第二期（需 key / 试点 / 迁移）**：生成式 provider（§3.5）、0011 的 `word_images`/`user_settings` 改动（§3.5.3）、`ImageMeta.hint_safe/style`、`Settings.image_hint`、正面「图像提示」、`ImageMeta.style` 驱动 `contain`、标识办法实现、GLM-4.6V-Flash 评分、Openverse 应用注册。前置：产品负责人对 §3.6 决定的确认、Q1 编码、智谱 key。
- **第三期（视评估）**：默认风格、每词多图（唯一索引改 `(word_id, style)`）、下载后再比的复杂度信号（Pillow 边缘密度/颜色数）、CLIP 离线筛选、管理员上传。

---

## 4. 改动清单（文件 → 改什么）

### P1-1 SVG v2

- `backend/wd/ai/prompts/svg_system.txt:1` — 整文件替换为 §3.2.2。
- `backend/wd/ai/svg.py` — `:32-33` 旁加 `SVG_PROMPT_VERSION = "svg-v2"`、`EXAMPLE_MAX = 80`、`HOOK_MAX = 60`、`STYLE_KID`、`STYLE_GENERAL`；`:40-45 build_user_prompt(display, meaning, concept, *, kid, example="", hook="")`；`:48-52 prompt_for(conn, word, *, kid_stage_max)`；`:115` 传 `kid_stage_max=cfg.image_kid_stage_max`；`:137` `activate_svg(conn, cfg, wid, svg, alt, now=now, prompt_version=SVG_PROMPT_VERSION)`；`__all__`（`:149`）不变。
- `backend/wd/images/sanitize_svg.py` — `:48` 旁加 `BARE_AMP_RE`；`_parse`（`:65-79`）在 `:70` 后 `text = BARE_AMP_RE.sub("&amp;", text)`；`clean(svg, *, drop_text=False)`（`:169-181`）；`_serialise(..., drop_text)`（`:137-166`）在 `:139` 判断 `local in ("text","tspan") and drop_text → return`。
- `backend/wd/images/store.py` — `activate_svg(conn, cfg, word_id, svg, alt_zh, *, now=None, drop_text=True, prompt_version=None)`（`:152-174`）：`cleaned = sanitize_svg.clean(svg, drop_text=drop_text)`，`activate(..., query=f"svg:{prompt_version}" if prompt_version else None, ...)`；`ai/svg.py` 的常量取 `SVG_PROMPT_VERSION = "v2"`，于是列值恰为 `svg:v2`（§3.2.4 第 3 条的约定）。
- `backend/wd/images/__init__.py:19` — 导出不变。
- `docs/CLAUDE_INTEGRATION.md:279-285` §5.5、`:401-403` §6.7（加「`<text>/<tspan>` are stripped; bare `&` is repaired before parsing; `word_images.query` carries `svg:<version>`」）；`docs/DESIGN.md:550`。
- 测试：`backend/tests/unit/test_sanitize_svg.py` 新增 `test_bare_ampersand_is_repaired_but_entities_still_rejected`、`test_drop_text_removes_text_and_tspan_but_keeps_title`；`backend/tests/integration/test_images.py:608-625` 把 `"<text" in stored` 改为 `"<text" not in stored`，并断言 `row["query"] == "svg:v2"`（需把 `prompt_version` 传入）；新增 `backend/tests/unit/test_svg_prompt.py`：`build_user_prompt` 的 kid/general 段落、例句与挂钩截断、`prompt_for` 对 `stage_min` 的判定（用 `conn` 夹具插入 `stage_min=1/3` 的词）。

### P1-2 content v2

- `backend/wd/ai/prompts/content_system.txt:6,9,10` — §3.3.2 文案。
- `backend/wd/ai/content.py:46` `PROMPT_VERSION = "content-v2"`；`:54` `EXAMPLE_EN_MIN, EXAMPLE_EN_MAX = 10, 240`。
- `docs/CLAUDE_INTEGRATION.md:206`（标题）、`:208-226` §5.1 代码块、`:355`；`docs/WORD_LIBRARY_CURATION.md:65,183`（「content-v1」→「当前 `PROMPT_VERSION`」）。
- 测试：`backend/tests/unit/test_content_apply.py:81` → `== content.PROMPT_VERSION`；新增「10–14 字符例句保留、9 字符丢弃」用例。

### P1-3 搜索词

- `backend/wd/images/select.py:20-24` — `SAFETY_RE`、`KID_SAFETY_RE`、`RELEVANCE_RE`，`BLOCKLIST_RE` 保留为并集；`:40-42 is_blocked(text, *, allow=frozenset(), kid=False)`；`:54-77 reject_reason(cand, exclude=(), *, allow=frozenset(), kid=False, style="photo")`；`:104-128 rank(..., allow, kid, style)`。
- `backend/wd/images/handler.py` — `:38` 旁加 `FUNCTION_POS = frozenset("aicpdtxu")`、`FUNCTION_POS_SHARE = 80`、`def is_function_word(pos: str | None) -> bool`（解析 `n:4/v:96` 形状，`pos` 为空返回 False）；`:64-78 clean_keywords` 返回 `tuple[list[str], list[str]]`（keywords, dropped）；`:121-124` SELECT 加 `pos, stage_min`；`:134-137` 之后：若 `keywords == [lemma]` 且无 `query` 且 `is_function_word(word["pos"])` → 跳到 `:201-206` 分支（抽成 `_fallback(...)` 内部函数避免重复）；`query` 被丢弃时 `log.warning(..., extra={"event": "query_ignored"})`；`:182` 传 `allow`/`kid`。
- 测试：`backend/tests/unit/test_select.py` 新增 `test_blocklist_allows_the_queried_relevance_word_but_never_safety_words`、`test_kid_style_blocks_weapon_words_even_when_queried`；`backend/tests/integration/test_images.py` 新增 `test_function_word_without_content_skips_every_provider`（`insert_word(conn, "of", pos="i:100")`，断言 `mock_http.calls == []` 且 `image_state == "failed"`）、`test_admin_query_dropped_by_shape_rule_is_reported_in_detail`。

### P1-4 风格管道

- `backend/wd/interfaces.py:73-79` — `search(self, query: str, limit: int, *, style: str = "photo")`。
- `backend/wd/config.py` — `:168` 后 `image_kid_stage_max: int = 0`；`:534` 后 `image_kid_stage_max=integer("WD_IMAGE_KID_STAGE_MAX", 0, 0, 9)`。
- `deploy/env.example:165` 后 `WD_IMAGE_KID_STAGE_MAX="0"` + 注释；`docs/DEPLOY.md:345` 后表格行。
- `backend/wd/images/providers/wikimedia.py` — `:40-51 params(query, limit, *, style)`（`filetype:drawing|bitmap`、`iiprop` 加 `thumbmime`、`maxlag: 5`）；`:53-57 search(..., *, style)` 加 maxlag 错误体检查；`:97` MIME 取 `thumbmime` 优先；模块文档串 `:3-6` 同步。
- `backend/wd/images/providers/openverse.py` — 删 `:28 PAGE_SIZE`，`:41-42 params(query, limit, *, style)`：`page_size=max(1, min(int(limit), 20))`、`category`；`:65-72 search(..., *, style)`；`:114-119 extra["category"]`；文档串 `:3-4`。
- `backend/wd/images/providers/pixabay.py:30-39` — `image_type` 按 style、加 `orientation: "horizontal"`；`:41 search(..., *, style)`。
- `backend/wd/images/providers/pexels.py:29-37` — 签名加 `*, style` 并忽略。
- `backend/wd/images/select.py:30` — `MIN_SIZE: dict[str, tuple[int,int]]`，`reject_reason` 按 `style` 取。
- `backend/wd/images/handler.py` — `fetch_for_word(..., style: str = "auto")`；`styles` 外层循环；CLI `:349-356` 加 `--style {auto,photo,illustration}`；`:276` 传入。
- `backend/wd/smoke_mock.py` — 若其 Openverse 夹具按 `page_size` 匹配（`:37` 的 `EMPTY_OPENVERSE` 只是响应体），应无需改；跑 `make smoke` 验证。
- 文档：`docs/DESIGN.md:523-553` §9 伪代码与 Commons/Openverse 两条（`:545-546`）；`ATTRIBUTION.md` §3.1/§3.2 的参数描述。
- 测试：`backend/tests/unit/test_providers.py:46-69`（参数字典加 `"iiprop": "url|extmetadata|size|mime|thumbmime"`, `"maxlag": "5"`）、`:172-192`（`page_size "10"`, `category "photograph"`）、`:345-359`（加 `orientation`；新增插画风格断言）；新增 `test_wikimedia_drawing_style_uses_thumbmime_as_candidate_mime`（内联 `thumbmime: image/png`, `mime: image/svg+xml` 夹具，断言候选 `mime == "image/png"` 且通过 `select.reject_reason`）、`test_wikimedia_maxlag_body_raises_provider_error_503`；`backend/tests/integration/test_images.py:162` 改 `page_size "10"` + `category`；新增 `test_kid_stage_word_tries_illustration_then_photo`（`insert_word(conn, "cat", stage_min=1)`，`cfg=replace(cfg, image_kid_stage_max=1)`，断言第一次 Commons 请求 `gsrsearch == "cat filetype:drawing"`、第二轮为 `bitmap`）、`test_illustration_style_accepts_240x180_candidates`；`backend/tests/unit/test_config.py` 新增默认值与范围用例；`backend/tests/unit/test_deploy_files.py:119` 自动覆盖新变量。

### P1-5 重试

- `backend/wd/images/service.py` — 常量 + `retry_due`、`enqueue_retry_if_failed`、`retry_failed_studied`；`enqueue_fetch(..., retry: bool = False)`（`:155-183`）。
- `backend/wd/images/__init__.py:18` — 导出 `enqueue_retry_if_failed`、`retry_failed_studied`。
- `backend/wd/services/bank.py:636,659` — 调用 `images.enqueue_retry_if_failed(conn, word, images_enabled=get_settings().images_enabled, priority=<同一优先级>, now=now)`（注意 `wd.images` 已 import `wd.services.words`？`images/service.py` 不导入 `services`，`bank.py` 导入 `images` 不会成环；`content.py:36` 已从 `images.select` 导入，证明方向可行）。
- `backend/wd/services/batches.py:639` — 同上，priority `CONTENT_PRIORITY_BATCH`。
- `backend/wd/jobs/scheduler.py:66 TickResult` 加 `image_retries: int = 0`；`maintenance`（`:364-380`）在 `prefetch` 后调用 `images.retry_failed_studied(conn, to_iso(now), images_enabled=cfg.images_enabled, priority=PREFETCH_PRIORITY)`；模块文档串 `:17` 同步。
- `backend/wd/images/handler.py:349-361` — `images-retry` 子命令（`--limit`, `--dry-run`），`cmd_images_retry` 打印将入队/已入队的 lemma。
- `backend/wd/cli.py:54` — `("fetch-image", "images-prune", "images-retry")`。
- 文档：`docs/DESIGN.md` §9 伪代码加重试规则；`docs/CLAUDE_INTEGRATION.md:401-403`（去掉「never retried automatically」）；`docs/DEPLOY.md:417`；`docs/ops.md` 运行手册加一行「Many text-only cards → `wd images-retry --dry-run`」。
- 测试：`backend/tests/integration/test_images.py` 新增 `test_failed_word_is_requeued_when_added_to_a_bank_after_six_hours`（用 `frozen_clock` 推进）、`test_retry_is_capped_at_three_per_thirty_days`、`test_nightly_sweep_requeues_only_studied_failed_words`（调用 `scheduler.maintenance` 或直接 `retry_failed_studied`）、`test_cli_images_retry_dry_run_lists_candidates`；`backend/tests/unit/test_scheduler.py` 对 `TickResult.image_retries` 的一条断言。

### P1-6 打分

- `backend/wd/images/select.py:80-101` — 新信号常量 `PORTRAIT_RE`、`TEXTISH_RE`、`DESCRIPTION_HIT = 1`、`CATEGORY_POINTS`，`score(cand, keyword, *, used_refs=(), style="photo")`；`rank` 透传。
- `docs/DESIGN.md:547`。
- 测试：`backend/tests/unit/test_select.py:92-119` 末尾追加断言组；`test_rank_sorts_best_first…`（`:121-131`）数值不变（strong 候选无描述/类目）。

### P1-7 文档数字

见 §3.7.4 表；另 `backend/wd/ai/budget.py:273` 注释。

---

## 5. 测试与验收

### 5.1 已有测试中会红的（必须随改动同提交修）

| 测试 | 为什么红 | 处理 |
|---|---|---|
| `backend/tests/integration/test_images.py:616` `assert … "<text" in stored` | P1-1 默认剥离文字 | 翻转为 `not in`；加 `query == "svg:v2"` 断言 |
| `backend/tests/unit/test_content_apply.py:81` `== "content-v1"` | P1-2 版本号 | 改引用 `content.PROMPT_VERSION` |
| `backend/tests/unit/test_providers.py:57-64`（参数字典全等） | P1-4 `thumbmime`、`maxlag` | 更新字典 |
| `backend/tests/unit/test_providers.py:178`、`backend/tests/integration/test_images.py:162`（Openverse 参数全等） | P1-4 `page_size=10`、`category` | 更新字典 |
| `backend/tests/unit/test_providers.py:2` 文档串「page_size 20」 | 文字 | 改 10 |
| `backend/tests/unit/test_deploy_files.py:119,136` | 新 Settings 字段必须出现在 env.example 且默认值能构造 Settings | 加 `WD_IMAGE_KID_STAGE_MAX="0"` |
| `backend/tests/unit/test_docs_contract.py`（DEPLOY §4 列出每个 Settings 变量） | 新变量 | DEPLOY §4 加行 |
| `backend/tests/unit/test_cli.py:56-58` | 只要求 `COMMAND_OWNERS` 与 `CLI_MODULES` 键集一致；加命令到既有元组不红 | 无 |
| `scripts/check_contract.py` | 第一期不改 `schemas.py`/`types.ts` | 无 |
| `frontend` vitest / `check-copy.mjs` | 第一期无前端改动 | 无 |

不会红但要确认的：`test_sanitize_svg.py:119-130` 的 `malformed` 用例（`<rect></svg>`）与 `:103-116` 的实体用例在 `&` 修复后仍 `SvgRejected`；`test_select.py:92-119` 全表；`test_images.py:139,540,545` 的 `filetype:bitmap` 断言（默认 photo）。

### 5.2 要加的测试（汇总）

见 §4 各段；核心九个：裸 `&` 修复、`drop_text`、kid/general 提示词、功能词门、黑名单分级、`thumbmime` 作候选 MIME、`maxlag` 短冷却、插画→照片两遍、失败词三个触发点与上限。

### 5.3 在 live-copy 的私有拷贝上排练

1. `cp /private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/live-copy.db scratchpad/images-pilot/data/word-dance.db`（原副本只读，`sqlite3 -readonly`）。
2. 核对基线数字（本文引用的全部来自以下 SQL，在 `-readonly` 下执行）：
   - `SELECT provider, status, COUNT(*), ROUND(AVG(file_bytes)) FROM word_images GROUP BY 1,2;` → `claude_svg|active|30|1407`、`wikimedia|active|1|95117`
   - `SELECT image_state, COUNT(*) FROM words GROUP BY 1;` → `failed 18 / none 9113 / ready 31`
   - `SELECT COUNT(*), ROUND(SUM(cost_usd),4), ROUND(SUM(cost_usd)/COUNT(*),5), ROUND(AVG(output_tokens)), ROUND(AVG(duration_ms)) FROM ai_calls WHERE kind='svg';` → `34|0.4207|0.01237|829|7931`
   - `SELECT COUNT(*), SUM(result_json LIKE '%image_id%'), SUM(result_json LIKE '%rejected%') FROM jobs WHERE type='generate_svg';` → `34|30|4`；被拒任务 45/88/97/136（词 4259/4275/4935/818），错误 column 226/224/402/410
   - `SELECT priority, json_extract(result_json,'$.status'), COUNT(*), SUM(result_json LIKE '%svg_job_id%') FROM jobs WHERE type='fetch_image' GROUP BY 1,2;` → `20|failed|19|19`、`30|failed|30|15`
   - 18 个 failed 词的学习状态：`have new`、`critical/investment/property/senate/species learning`、其余 `known`，其中 `employee` 开放批次项 0、其他 known 词 2–3 → `word_is_studied` 对 17 个为真
   - `SELECT COUNT(*), SUM(frq>0), SUM(content_state='ready'), SUM(image_state='ready') FROM words WHERE stage_min=1 AND kind='word';` → `2012|1960|1|0`；首位词性 `n 808 / v 557 / adj 235 / other 207 / adv 163 / none 42`
   - `SELECT user_id, stages_json, current_stage, show_images FROM user_settings;` → `1|["zk","gk","cet4","cet6"]|3|1`、`2|["zk"]|1|1`
3. 用 `.venv/bin/python -m pytest backend/tests/unit/test_select.py backend/tests/unit/test_sanitize_svg.py backend/tests/unit/test_providers.py backend/tests/integration/test_images.py -q` 跑受影响子集，再 `make test`（Mac 上 `test_deploy_files.py` 19 个与 `test_config.py::test_defaults_without_environment` 按用户记忆本来就红，忽略）。
4. 排练重试：`WD_DATA_DIR=scratchpad/images-pilot/data WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 .venv/bin/wd images-retry --dry-run` 应列出 17 个词；再去掉 `--dry-run`，`SELECT dedupe_key, priority, json_extract(payload_json,'$.retry') FROM jobs WHERE type='fetch_image' AND status='queued';` 应为 17 行、`retry=1`。
5. 排练 SVG v2：`WD_AI_ENABLED=1` + 假 `claude`（`backend/tests/fake_claude.py`，`WD_CLAUDE_BIN` 指向它）对 `have` 跑 `wd fetch-image have --provider claude_svg`，检查文件无 `<text`、`word_images.query='svg:v2'`。
6. 排练真实抓图（可选，出口正常的机器）：§3.7.2。

### 5.4 验收标准（第一期）

- 全部 pytest 通过（Mac 上除既知红的 20 个）；`make smoke` 通过；`scripts/check_contract.py` 零 hard finding；frontend `npm test` 不变。
- 新 SVG 文件 0 个 `<text` 元素；连续 20 次 `generate_svg` 拒收 ≤ 1。
- 部署后第一次 03:30 维护把 ≥ 15 个 failed 词重新入队（journal `image_retry` 事件），48 h 内 `SELECT image_state, COUNT(*) FROM words WHERE id IN (18 词)` 的 `failed` ≤ 3。
- `WD_IMAGE_KID_STAGE_MAX=0` 时线上请求形状只多 `thumbmime`/`maxlag`/`page_size=10`/`category=photograph`，`provider_usage` 日计数不高于改前同口径。

---

## 6. 上线与回滚（Mac，launchd）

第一期**没有迁移、没有前端改动**，所以步骤比 DEPLOY §10 的 Linux 流程短（本机差异见用户记忆：没有 `install.sh`/`systemctl`，服务是 `~/Library/LaunchAgents/com.word-dance.server.plist`，`wd serve` 启动时自动跑迁移并先做快照）。

1. 准备：`cd /Users/sqin/word-dance && git pull`（或合并分支到 main），`make test`（接受既知的 20 个红）。
2. 停服务：`launchctl bootout gui/$(id -u)/com.word-dance.server`（`com.word-dance.backup` 不动）。
3. 快照（虽无迁移，仍做）：`WD_DATA_DIR=/Users/sqin/word-dance-data .venv/bin/wd backup --keep-daily 14 --keep-weekly 8`，确认 `backups/` 新文件与 `kv.backup.last`。
4. `.env`（`/Users/sqin/word-dance-data/.env`，每行必须 `KEY="value"`）：加 `WD_IMAGE_KID_STAGE_MAX="1"`（本机两位用户都学 zk 词，用户 2 只学 zk；这就是试点）；不要把 `HTTP(S)_PROXY` 写进服务环境（会破坏 `fetch.py` 的 DNS 固定下载）。
5. 起服务：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist`（或 `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`）；`wd serve` 发现无 pending 迁移，直接启动。
6. 验证：`curl --noproxy '*' http://127.0.0.1:8000/api/health`；`WD_DATA_DIR=… .venv/bin/wd check providers`（`diag.py:136-149`，列出链与 SVG 子额度）；`tail -f ~/Library/Logs/word-dance/word-dance.log | grep -E 'image_|svg_|provider_'`；第二天早上查 `SELECT lemma, image_state FROM words WHERE id IN (<18 词>)` 与 `jobs` 里的 `retry=1` 任务结果；管理页概览 `with_photo/with_claude_svg/card_only`（`service.photo_mix`）。
7. 回滚：`launchctl bootout …` → `git checkout 75df534` → `launchctl bootstrap …`。数据兼容性：新代码写入的 `word_images.query='svg:v2'`、`jobs.payload_json` 中的 `retry:true`、`word_contents.prompt_version='content-v2'` 对旧代码都是不读或读不懂也不报错的值（旧 `select_jobs` 对 `content-v2` 的词只在有任务时才会重做，而入队点不给 `ready` 词排任务）；`.env` 多出的 `WD_IMAGE_KID_STAGE_MAX` 对旧代码无害：`Settings.from_env`（`config.py:252-256`）只把出现的 `WD_*` 名字收进 `present` 用于改名检测，没有任何「未知 `WD_` 键即拒绝」的分支（全文件只对 `WD_TZ`、`WD_IMAGE_PROVIDERS`、`WD_AI_FALLBACK_PRICE_JSON` 的取值抛 `ConfigError`，`:342,361,451`）；install.sh 的 `.env` 校验只在 Linux 流程里存在，Mac 不经过它。
8. 第二期（有迁移）时改走完整流程：停 → `wd backup` → `wd migrate`（预迁移快照 `backups/pre-migrate-*.db.gz`）→ `wd import-seed`（若词表同期变更）→ 起 → 验证；回滚只能 `wd restore backups/pre-migrate-*.db.gz`（`[A4]`：一旦有新 provider/新列的数据写入，旧代码对 `provider='zhipu_image'` 的 `image_meta` 会按照片分支拼署名、`ImageMeta.provider` 校验 500——不存在「只回退代码」）。

---

## 7. 风险、未决问题、工作量

### 7.1 风险

| 风险 | 概率/影响 | 缓解 |
|---|---|---|
| 去掉文字后 Claude SVG 的可辨认度下降（尤其抽象词） | 中/中 | 用户提示带例句与「联想」挂钩；§3.7 评分；抽象副词（`despite/particularly/directly/suddenly` 已是 SVG）本就不该配图，第三期考虑按具体性常模（Lancaster CC BY，`[D5]`）跳过 |
| 裸 `&` 修复只覆盖一类拒收；真实根因未看 journal | 中/低 | 部署后读 `claude-logs/` 的被拒原文（线上目录，本任务禁区）；去文字缩小了表面 |
| 插画链质量不可知（剪贴画小图、结构图） | 高/中 | 默认关；Mac 试点开；评分阈值才改默认；`diagram` 仍在相关黑名单（查询不含该词时拒） |
| 两遍抓取耗尽 Openverse 匿名配额 | 中/低 | 本地 15/160 封顶；注册 Openverse 应用（第二期） |
| `maxlag` 处理路径未对真实 API 验证 | 中/低 | 只在 `error.code == "maxlag"` 时触发；冷却 30 s；加单元测试 |
| 重试第一晚集中入队 | 低/低 | 17 个词、上限 50、priority 30、IoWorker 串行 |
| `PROMPT_VERSION` 变更让夜间复活的旧 dead 内容任务重做卡片 | 低/低 | 线上 `generate_content` 任务全部 `done`（49/49），无 dead |
| `.env` 新键在回滚时的兼容 | 中/低 | §6 第 7 条：回滚前先删该行或先验证 `from_env` 行为 |
| `query` 列承载 SVG 版本是约定而非约束 | 低/低 | 第二期 0011 加 `prompt_version` 列并回填 |
| 第二期标识办法的元数据字段未读国标原文；Pillow 写 XMP 能力未验证 | 高/中 | 实现前核对 GB 45438-2025；必要时手写 APP1 段 |

### 7.2 未决问题（需负责人或后续工作回答）

1. §3.6 的三项产品决定（图在回忆后为默认、提示模式可选、每词一图不改）——需确认。
2. Q1 编码落定后 `WD_IMAGE_KID_STAGE_MAX` 的默认值（重编号 1..5 → 2；小学=0 → 1）与是否把默认从 0 改为非 0（取决于 §3.7 评分）。
3. 11-02 的 18 个任务在 Commons 有应答却失败的原因（需线上 journal；INDEX 未解决 7）；本文的功能词门、黑名单分级、重试都不依赖它，但它决定打分规则是否真被检验过。
4. 第二期生成 provider 的内容过滤拒绝率、智谱 `cogview-3-flash` 的限流数字（需登录查看）、免费模型是否允许商用场景（用户协议付费条款）。
5. 标识办法下本应用的主体定位与 JPEG/SVG 隐式标识的具体字段（INDEX 未解决 9）。
6. 白话释义（Q9）是否做——提示词一句话，但要产品决定。

### 7.3 工作量

| 项 | 人日 |
|---|---|
| P1-1 SVG v2 + 清洗 + 测试 + 文档 | 0.5 |
| P1-2 content v2 + 常量 + 版本 + 文档 | 0.5 |
| P1-3 搜索词（功能词门、黑名单分级、query 可见化）+ 测试 | 0.5 |
| P1-4 风格管道 + 四 provider 参数 + 尺寸门槛 + 配置 + 测试 + 文档 | 1.5 |
| P1-5 重试（服务函数、三个触发点、夜间、CLI）+ 测试 + 文档 | 1.0 |
| P1-6 打分 + 测试 + 文档 | 0.5 |
| P1-7 文档数字 + 排练 + 上线 | 0.5 |
| **第一期合计** | **5.0** |
| 试点评估（选样、三臂运行、两人评分 600 张、报告） | 2.0 |
| 第二期（生成 provider、0011 的 `word_images`/`user_settings` 部分、契约与前端、标识办法、VLM 评分） | 6–8 |
