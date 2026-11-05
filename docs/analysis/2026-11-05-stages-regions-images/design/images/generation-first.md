# 配图更易记 · 角度「生成优先」：国产位图生成 provider 的完整路径

设计稿 v1 · 2026-11-05 · 基线 `main @ 75df534`（行号均按此提交，每处都已由本文作者亲自打开核对）· 线上库只读副本 `scratchpad/live-copy.db`（9,162 词；`schema_migrations` = 1 / 8 / 9 / 10）· 本文只设计，不改代码。

读法：每节先给**结论**，再给**依据**（`文件:行` 或 `[INDEX x]` / `[slug-N]` / `[verify slug-N]`）。引用的 INDEX 条目见 `../../INDEX.md`，facts/verify 见 `../../facts/` 与 `../../verify/`。工作量单位人日；「P1 / P2 / P3」= 第一 / 二 / 三期。

本文与同目录其他设计者的文件互不参照（按任务要求独立写作）。但有一个事实必须提前声明：`scratchpad/design-stage-model-minimal/0011_primary_stage.sql` 已存在，说明阶段模型设计占用了迁移号 **0011**；本文的迁移因此编号 **0012**（若 0011 最终未落地，则取当时的下一个空号，`db.list_migration_files` 按文件名排序、不要求连续，`backend/wd/db.py:159`）。

---

## 1. 一页结论

### 1.1 决定了什么

| # | 决定 | 一句话理由 |
|---|---|---|
| D1 | **位图生成按「image provider」接入现有 `fetch_image` 链**（provider 名 `ai_image`），不是新 job 类型，也不写 `ai_calls`。 | 复用 `handler.fetch_for_word` 的 quota / 冷却 / 下载 / 归一化 / 激活全套（`handler.py:156-196`），只需一次 `word_images.provider` CHECK 重建；新 job 类型要重建 `jobs`（`0001_init.sql:487`），进 `ai_calls` 要同时改 `kind` CHECK（`:511`）与 0010 的 `provider` CHECK（`0010_ai_provider.sql:9`）并撞上 failover 状态机——三张表重建换不来任何功能。 |
| D2 | **链位置由两条有序链配置**：`WD_IMAGE_PROVIDERS`（成人链，现有）与新增 `WD_IMAGE_PROVIDERS_KID`（小学/初中链）；`ai_image` 出现在哪条链的哪个位置就在那儿运行；默认两条链都不含 `ai_image`（**默认关闭**，A5）。试点建议：KID 链 `ai_image,wikimedia,openverse`，成人链 `wikimedia,openverse,ai_image`。 | 现有 `WD_IMAGE_PROVIDERS` 本来就是有序链（`config.py:355-369`、`providers/__init__.py:40-59`），一个值表达「生成优先 / 生成兜底 / 不生成」三种策略，不新增模式枚举。 |
| D3 | **风格由词的阶段驱动，不按用户**：`style_for(word) = 'kid'` 当 `stage_min <= STAGE_ORDER.index('zk') + 1`（今天 = 1，即初中及以下；阶段模型加入小学后自动覆盖小学），否则 `'adult'`。Claude SVG 的用户提示词、生成器提示词、照片链的插画参数与打分都读这个值。**每词仍只有一张 active 图**（不改 `ux_word_images_active`）。 | D1 证据只支持「小学插画、成人可照片」的粗分，没有「同词双图」的证据 [INDEX D1]；小学词主要被小学生学，词级风格够用；多图要改唯一索引、`ImageMeta` 按用户解析、`photo_mix`，代价大 [images-pipeline-33]。 |
| D4 | **图出现在回忆之后（卡片背面），正面不出图**；`show_images` 保持全局布尔。「图作提示」只在第三期、且只对**无文字**的新图评估。 | Carpenter & Olson 2012：图先于回忆造成过度自信 [image-memorability-6]；现有 30 张 SVG 与模板卡都印着词头，用作正面提示会泄露答案 [verify images-pipeline O6]。 |
| D5 | **Claude SVG v2**：系统提示词去掉「底部英文词」、加单一主体/无文字/转义要求；`sanitize_svg` 在解析前修复裸 `&`，`activate_svg` 以 `allow_text=False` 剥掉模型文字，再由服务端注入右下角 `AI` 角标与 `<desc id="aigc-label">` 隐式标识；新卡以 `word_images.query='svg-v2'` 标记；**49 个有内容的旧词（30 张 SVG、1 张照片、18 张模板卡）不动**。 | 4/34 次拒收疑为 `<text>` 里的裸 `&`，每次白花 $0.0123 [verify image-memorability 遗漏 1]；去文字本身就能降低拒收；旧卡不会自动重画 [ai-prompts-stages-10]。 |
| D6 | **content 侧只改提示词与两个常量，不加新字段**：`image_alt_zh` 改为「与例句情境一致的单一画面，≤30 字，无文字无人脸特写」，`image_keywords` 改为「描述同一画面的可拍短语」；`EXAMPLE_EN_MIN` 15→10；`PROMPT_VERSION` → `content-v2`。`image_scene_en` 留到第三期（10 处改动面已列出）。 | 国产生图模型中文原生，`image_alt_zh` 直接可作场景描述；加字段要动 schema 文件、文档代码块与 fixture 的逐字节同步 [verify ai-prompts-stages 遗漏 2]，不是「本周可合并」的事。 |
| D7 | **标识合规**：显式 = 厂商水印保持默认开（智谱 `watermark_enabled=true`）+ UI 题注「AI 生成配图」+ SVG 右下角 `AI` 角标；隐式 = 入库 JPEG 写 COM 段与 XMP 包、SVG 写 `<desc>`，内容为统一的 JSON 标签（生产者 / 模型 / 时间 / 传播者）。GB 45438-2025 的字段名**待核对原文**后再定键名。 | 《人工智能生成合成内容标识办法》要求显式 + 文件元数据隐式标识 [verify image-memorability 遗漏 4]；现有 `normalise_image` 把所有元数据剥光（`fetch.py:267`），所以标签必须在重编码那一步写入；Pillow 12.3.0 的 JPEG `save` 接受 `comment` / `xmp`（本机 `.venv` 实测）。 |
| D8 | **成本控制用计数不用美元**：`provider_usage` 的分钟/日窗口对 `ai_image` 生效（默认 4/分、60/日），429/5xx 冷却沿用；生成图**不占** `WD_AI_SVG_DAILY_BUDGET_USD` 也不进 AI 美元日预算；价格只在文档里折算。 | `quota.py` 已按 provider 持久化计数（`quota.py:37-47,75-110`），零新表；CogView-3-Flash 免费、CogView-4 ¥0.06/次 [image-memorability-26]，美元账本对它没有意义。 |
| D9 | **无 key 也能测到可合并**：`backend/tests/fake_image_gen.py`（`httpx.MockTransport`，返回带「AI 生成」字样的 PNG，支持 `url` / `b64_json` / `content_filter` / 429 / 400 等模式）+ `smoke_mock.MockHttp` 新增两条路由；集成测试覆盖链位置、风格、过滤、冷却、标识元数据、迁移、`photo_mix`、`ImageMeta`。 | 与 `fake_openai.py` 同一套路（`backend/tests/fake_openai.py:93-122`）；`MockHttp.overrides[host]` 已支持按主机替换路由（`smoke_mock.py:84,95-96`）。 |
| D10 | **三期**：P1 本周可合并、无 key（SVG v2、sanitize 修复、content 提示词、照片链修补、失败词重试、文档数字）；P2 需智谱 key（provider、配置、迁移 0012、契约、前端、fake、200 词试点）；P3 视评估（正面提示开关、每词多图、VLM 自动评分写 `word_images.score`、`image_scene_en`、Pixabay/Pexels 插画参数）。 | 见 §3.9。 |

### 1.2 为什么是「生成优先」而不是「先修照片链」

- 线上照片命中率是 **0/49**，且 ≥27 个任务因冷却没发请求、11-02 的 18 个失败原因未知 [INDEX D2] [verify images-pipeline-29]；照片链依赖境外出口与匿名配额（Openverse 200/日），全库预抓只对 Commons 可行 [INDEX D3]。生成不依赖出口可达性，境内接口、免费档存在。
- 真正上线的「配图」就是 Claude SVG（30/31），单价 $0.0140/张、拒收 11.8%，且全部违反「图中无文字」[INDEX D2]。位图生成的全库成本 ¥0（Flash）～¥550（CogView-4），低于 SVG 的 ¥807–911 [INDEX 4.3]。
- 但证据对「卡通 vs 照片」在 6–11 岁的直接效果是空白 [INDEX 未解决 8]，所以生成只做**可配置、默认关闭**的试点，用 200 词三臂对照后再决定是否成为小学链的首选（§3.8）。

### 1.3 代价

| 期 | 内容 | 人日 | 前置 |
|---|---|---|---|
| P1 | SVG v2 + sanitize 修复 + content 提示词/常量 + 照片链 7 项修补 + 失败词重试 + 文档数字 + 测试 | **3.5** | 无（不需要任何 key，不需要迁移） |
| P2 | `ai_image` provider + 配置 10 项 + 迁移 0012 + 契约（`ImageProviderName`/`ImageMeta.kind`/`AdminOverviewWords`/`RefetchImageRequest`）+ 前端 + fake + 文档 + 试点脚本与一次真跑 | **6.0** | 智谱 key（免费注册即可）；阶段模型 0011 不是前置，但 0011 若先上，0012 排其后 |
| 试点执行 | 200 词 × 3 臂生成、人工评分 2 人、汇总 | **1.0**（外加 Claude SVG ≈ $2.8、content ≈ $0.8 或走备选免费） | P1 + P2 |
| P3 | 正面提示设置、每词多图、VLM 评分、`image_scene_en`、Pixabay/Pexels 插画参数 | 6–10（不承诺） | 试点结论 |

合计 P1 + P2 + 试点 ≈ **10.5 人日**。

---

## 2. 对照假设 A1–A6 的偏离与理由

| 假设 | 本文立场 | 偏离/补充 |
|---|---|---|
| A1 小学 = 国家二级 505 词骨架 | 采用 | 试点样本从 505 词里取（§3.8）：`scratchpad/verify-shanghai-primary/level2_505_from_docx.txt` 504 条 → 497 在库；ECDICT `pos` 主标签 n 179 / v 135 / j 44（本文用 `python3 -I` 对只读库复算），其中只有 1 词有内容、0 词有图。 |
| A2 初中/高中词集 | 不涉及 | 风格阈值以 `schemas.STAGE_ORDER.index('zk')` 计算（`schemas.py:51`），Q1 的任一编码（0 / 重编号 / 字符串码）下都正确覆盖「初中及以下」。 |
| A3 只用官方词头，释义来自 ECDICT | 采用并**延伸到图片**：照片仍走 CC 白名单（`providers/base.py:203-205`）；生成图的版权按智谱用户协议「由您自行维护」[image-memorability-26]，不含第三方素材；`license='generated'` 沿用 claude_svg 的既有取值（`store.py:166`、`0001_init.sql:256` 注释）。 | 新增一条许可事实：`word_images.creator` 存模型 id（如 `cogview-3-flash`）作溯源，不是「作者」。 |
| A4 不按省份分层 | 采用 | 配图不涉及地区维度。 |
| A5 位图生成可配置、默认关闭 | **采用但加重**：不是「脚本级试点」，而是正式 provider 代码 + 迁移 + 契约，用 fake provider 在无 key 的 Mac 上测到可合并；真跑只差 `.env` 三行。 | 偏离点在「试点」的形态：脚本试点会让 200 张图游离在 `word_images` 之外，无法测 UI 题注、标识元数据、举报/换图回路；provider 形态一次做对。代价：P2 多 ≈1.5 人日的迁移与契约工作。 |
| A6 新用户默认受众 K-12 | 采用 | 因此 KID 链（`WD_IMAGE_PROVIDERS_KID`）是必需的配置点，但 `show_images` 不改语义（§3.7）。 |

---

## 3. 详细设计

### 3.1 从 D1 证据推导准则，并落到代码

**结论**：七条准则各有一处代码落点；其中四条（无文字、单一主体、去装饰、风格一致）靠**提示词 + 服务端强制**双保险，两条（画例句义项、抽象词挂钩）只能靠提示词与 content 字段，一条（图作提示非答案）靠去文字 + 背面展示。

| 准则（INDEX D1） | 证据 | 落点 |
|---|---|---|
| 单一清晰所指 | Nelson 1976 相似性反转；Flack & Horst 2018 一次一图 [image-memorability-1,13] | SVG 系统提示词「exactly one central subject」（§3.3）；生成器提示词「画面中只有一个清晰主体」（§3.6.3）；照片打分对竖图/人物类目减分（§3.5）。 |
| 图中无文字 | Boers 2009/2017：图分走对词形的注意 [image-memorability-8]；现状 SVG 与模板卡都印词 [verify images-pipeline O6] | SVG：提示词去掉 `the English word in a <text>`（`svg_system.txt:1`）+ `clean(allow_text=False)` 剥 `<text>/<tspan>`（`sanitize_svg.py:28-31`）；生成器：提示词「不要任何文字、字母、数字、标志」；照片：黑名单已含 `text|poster|document|screenshot`（`select.py:20-24`）。 |
| 去无关细节 | 诱人细节 g≈−0.33；儿童更敏感 [image-memorability-12,13] | 提示词「plain background, no decorative clutter」；kid 风格要求纯色浅背景。 |
| 画例句用到的义项 | Lotto & de Groot 一致性；Mayer 一致性原则（间接）[image-memorability-7,15] | `content_system.txt:10` 的 `image_alt_zh` 改为「与例句 1 情境一致的画面」；SVG 用户提示词与生成器提示词都以 `image_alt_zh` 为场景（`svg.py:51` 已如此）。 |
| 抽象词用记忆挂钩并与 `mnemonic_zh` 对齐 | 关键词法 + 文生图提升保持 [image-memorability-10,11] | 提示词规则：抽象词 `image_alt_zh` 应是具体场景或对比图，与 `mnemonic_zh` 的联想一致；功能词（介词/连词/代词/冠词/助动词）**不搜照片**直接走 SVG/生成（§3.5 第 1 项）。 |
| 风格一致、构图各异 | Nelson 1976 [image-memorability-1] | 两套固定风格前缀（kid / adult）+ 场景由词决定；不再允许模型自选调色板之外的风格。 |
| 图作提示而非答案 | Carpenter & Olson 2012 [image-memorability-6] | 去文字（本期）+ 背面展示（§3.7）；第三期才评估正面提示。 |

### 3.2 风格由阶段驱动：`images/style.py`

**结论**：新增 `backend/wd/images/style.py`：

```python
KID, ADULT = "kid", "adult"
def kid_max_index() -> int:            # 初中及以下 → kid；小学加入后自动包含
    from ..schemas import STAGE_ORDER
    return STAGE_ORDER.index("zk") + 1
def style_for(word) -> str:
    sm = word.get("stage_min")
    return KID if sm is not None and int(sm) <= kid_max_index() else ADULT
```

**依据**：`stage_min` 今天 1=zk…4=cet6（`0001_init.sql:185`），`STAGE_ORDER` 在 `schemas.py:51`；`handler.fetch_for_word` 的 SELECT（`handler.py:121-124`）需要加 `stage_min` 列；`svg.prompt_for` 读 `words.word_row` 的完整行（`svg.py:48-52`、`services/words.py:204-206` `SELECT *`），不用改查询。Q1 若选「小学 = 0」，`0 <= 1` 成立；若重编号 1..5（xs=1, zk=2），`index('zk')+1 = 2` 同样成立。

### 3.3 Claude SVG 路径

**结论**：

1. **系统提示词 v2**（`backend/wd/ai/prompts/svg_system.txt:1`，同步 `docs/CLAUDE_INTEGRATION.md:282` 的代码块，否则 `test_prompts_are_verbatim_from_section_5` 变红，`backend/tests/unit/test_schemas.py:122-127`）。改动三处：
   - 删除 `the English word in a <text> at the bottom (font-size 40, font-family 'Inter, system-ui, sans-serif')`；
   - 加 `exactly one central subject on a plain light background; no text, letters, digits, logos or labels anywhere; no decorative clutter; draw the described scene, not a symbol of the word`；
   - 加 `never use a bare & or < in attribute values or text (write &amp; / &lt;)`。
   schema `svg_v1.json` 不变（`{svg, alt_zh}`，`svg_v1.json:1`）。
2. **用户提示词加风格段**（`svg.py:40-45` `build_user_prompt(display, meaning, concept, style)`）：kid → `Style: bright, rounded, kid-friendly flat shapes, soft colours.`；adult → `Style: clean flat educational illustration, muted palette.`；`prompt_for` 读 `style_for(word)`。`CLAUDE_INTEGRATION.md:285` 的示例句同步。
3. **`&` 修复**（`sanitize_svg._parse`，`sanitize_svg.py:65-79`）：在 `DET.fromstring`（`:74`）之前 `re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)`。只触碰非法实体引用，合法文档字节不变；裸 `<` 无法安全修复，仍拒收。
4. **文字剥离**：`clean(svg, *, allow_text=True)` 新增关键字参数；`allow_text=False` 时 `_serialise`（`:137-166`）把 `text`/`tspan` 当作不在白名单（`title`/`desc` 保留）。`store.activate_svg`（`store.py:152-174`）以 `allow_text=False` 调用，然后在 `</svg>` 前注入两段服务端生成、XML 转义过的内容：`<desc id="aigc-label">{JSON 标签}</desc>` 与 `<text x="786" y="488" text-anchor="end" font-size="14" font-family="system-ui, sans-serif" fill="#000" fill-opacity="0.45">AI</text>`（显式标识，§3.6.8）。`clean()` 的默认行为不变，`test_sanitize_svg.py` 现有用例全部保持。
5. **新旧卡区分**：`activate_svg` 传 `query="svg-v2"`（`store.activate` 已有 `query` 参数，`store.py:87`；线上 30 张 SVG 的 `query` 为 NULL，本文查证）。不加列。
6. **旧卡策略**：**不动**。30 张旧 SVG、1 张 CLI 抓的照片与 18 张模板卡继续服务；管理员可按词用 API 69 `provider:"claude_svg"` 重画（`admin_ops.py:413-427`、`service.py:214-220`、`handler.py:139-147`）。原因：`PROMPT_VERSION` 提升不会让任何 ready 词重新入队 [ai-prompts-stages-10]；这 49 词全是四级词（`stage_min` 3:48、1:1，本文查证），不是本轮受众。
7. **成本预期**：实测 $0.01237/次、$0.0140/张交付、拒收 11.8% [verify image-memorability-17]；去文字 + `&` 修复后拒收预计明显下降（4 次都在前 500 字符内出错，疑为 `<text>` 内容 [verify image-memorability 遗漏 1]），每张交付成本趋近 $0.0124。`budget.ESTIMATES["svg"]` 0.03 → 0.015（`budget.py:33`；`test_budget.py:33` 的 `== 0.03` 断言同步），子预算 $0.50 ≈ 35 张/日（0.50/0.0140 = 35.7）。文档中的 $0.028 / 18 张：`docs/DESIGN.md:28,518,550`、`docs/CLAUDE_INTEGRATION.md:407,416`、`docs/DEPLOY.md:326,434`、`docs/ops.md:198`、`deploy/env.example:83`、`budget.py:273` 注释。

**依据**：现状提示词与 schema 见 `svg_system.txt:1`、`svg_v1.json:1`；用户提示词拼装 `svg.py:40-52`（`CONCEPT_MAX=60`，`:32`）；sanitize 白名单 `sanitize_svg.py:28-31`，解析 `:65-79`；`activate_svg` `store.py:152-174`；拒收路径 `svg.py:134-142`（`SvgRejected` 是 `ValueError`）。

### 3.4 content 生成侧

**结论**：

1. **`image_alt_zh` 语义改为场景句**（`content_system.txt:10`）：「one Chinese sentence (at most 30 characters) describing ONE concrete picture that matches the situation of example 1: a single subject, its action and setting; no text in the picture, no close-up faces, understandable by a primary-school child; for abstract or function words describe a concrete scene or contrast that matches mnemonic_zh」。硬上限 `ALT_MAX=60`（`content.py:62`）不变。
2. **`image_keywords` 语义改为「同一画面的可拍短语」**（`content_system.txt:9`）：「2–4 English stock-photo phrases that describe the SAME picture as image_alt_zh (subject + action or setting, 2–4 words), most literal first; nothing text-heavy, no brands, no faces close-up」。形状正则与黑名单不变（`content.py:61`、`:173-184`）。
3. **是否加新字段 `image_scene_en`**：**不加**（本期）。理由：(a) CogView / 万相 / Seedream 都接受中文提示，`image_alt_zh` 就是场景；(b) 加字段的改动面是 10 处且三方逐字节同步——`content_v1.json:9-12`（properties + `required`）、`content_system.txt`、`models.py:34-44` `ContentItem`（`extra="ignore"`，未声明键在 `valid_items` 被丢，`models.py:113-126`）、`content.validate_item` 返回字典（`content.py:189-201`）、`schemas.Content`（`schemas.py:549-563`，新字段必须 `Optional` 带默认，否则 49 条旧 `content_json` 在 `extra="forbid"` 的 `Model` 下 500，`schemas.py:87-90`）、`types.ts:70-75`、`docs/API.md:307`、`docs/CLAUDE_INTEGRATION.md:157-160`（§4.1 代码块必须与 schema 文件逐字节相同，`test_schemas.py:56-62`）、`backend/tests/fixtures/{claude_schemas.json,claude_content_ok.json}`、`backend/tests/fake_claude.py:170-199`、`scripts/eval_provider.py:115` `CONTENT_ITEM_KEYS`、`test_content_apply.py:80` 的 14 键断言。留给 P3，触发条件：试点显示中文场景句对生成器不够（例如动词/抽象词的构图错误率 > 20%）。
4. **小学例句规则**（Q9）：`content_system.txt:6` 的「8–20 words」改为「6–20 words; for words tagged 初中 (and lower) 4–10 words, simple present, school / home / playground scenes, high-frequency vocabulary only」；`EXAMPLE_EN_MIN` 15 → 10（`content.py:54`；`docs/CLAUDE_INTEGRATION.md:355` 的「15–240」同步）。`PREFIX_MIN=4`（`content.py:63`）不改，改提示词「use the headword in its base form at least once」替代。`PROMPT_VERSION` → `content-v2`（`content.py:46`；`test_content_apply.py:81` 的 `"content-v1"` 断言同步）。白话释义、搭配可空都只是文本改动 [ai-prompts-stages-7]。
5. **阶段标签**：今天标签只有 初中/高中/四级/六级（`content.py:49`），「小学」规则在阶段模型给 `words.STAGES` 加码并同步 `STAGE_ZH` 后自动生效（否则 `prompt_entry` 的字典下标 `KeyError`，`content.py:88` [verify ai-prompts-stages 遗漏 1]）——这是阶段模型设计的责任，本文只依赖。

**依据**：现行规则 `content_system.txt:6,9,10`；后验证 `content.py:131-203`；`enqueue_image` 只在 `image_state != 'ready'` 时入队（`content.py:253-261`，调用点 `:347`）。

### 3.5 照片 / 插画抓取链（P1，无 key）

**结论**：七项修补，每项都在无 key 下可测。

| # | 改动 | 位置 | 约束/依据 |
|---|---|---|---|
| 1 | **功能词不搜裸 lemma**：无内容关键词、且 `words.pos` 主标签 ∈ {i, c, p, d, u, t, x}（介/连/代/限定/感叹/不定式标记/否定）时跳过照片链，直接进入生成/SVG 判定。 | `handler.py:134-137` 后加 `if keywords == [lemma] and is_function_word(word["pos"]): skip photo round`；SELECT 加 `pos`。 | 线上 `have` 的关键词是「holding keys in hand…」[images-pipeline-1]；`particularly` 只剩 `["one red apple"]` [verify images-pipeline O8]；ECDICT `pos` 形如 `i:100`（`0001_init.sql:174`）。 |
| 2 | **Commons**：`iiprop` 加 `thumbmime`，候选 `mime` 取 `thumbmime`；`gsrsearch` 在 kid 风格下用 `filetype:drawing`，否则 `filetype:bitmap`；参数加 `maxlag=5`，响应 `error.code == "maxlag"` → `ProviderError(status=503, retry_after_s=Retry-After)` → 冷却。 | `wikimedia.py:40-51`（`:44`、`:48`）、`:97`、`:53-57`；`base.get_json` 只把 ≥400 当错误（`base.py:100-118`），maxlag 是 200 + JSON error，需在 `search` 里判。 | SVG 的 `thumbmime=image/png`、`mime=image/svg+xml`，否则被 `select.py:65-66` 拒 [verify images-pipeline-31]；API 礼仪要求非交互任务用 `maxlag` [images-pipeline-46]。 |
| 3 | **Openverse**：`page_size = max(1, min(limit, 20))`（不再固定 20）；kid 风格加 `category=illustration`，并把该类目的尺寸门槛放宽到 `MIN_WIDTH, MIN_HEIGHT = 300, 200`（只对 `extra["category"]=="illustration"` 的候选），`aspect_ratio=wide` 不加（会漏掉 1:1 剪贴画）。 | `openverse.py:28,41-42,72`；`select.py:30,67-69` 增加按 `cand.extra.get("category")` 的分支；`openverse.parse_search` 把 `category` 放进 `extra`（`:114-119`）。 | 每次取 20 只用 10 [verify images-pipeline O2]；`illustration` 类目前三条 350×400 / 319×338 / 210×210 全被 400×300 硬拒 [verify image-memorability 遗漏 5]；匿名 20/分、200/日实测 [verify images-pipeline O1]，项目 15/160 不变。 |
| 4 | **Pixabay / Pexels**（有 key 时才生效，代码本期写好）：`search(query, limit, *, style=None)`；kid → Pixabay `image_type=illustration`、`orientation=horizontal`；Pexels 不改参数。两家在 `priority >= 90` 时跳过（同 Openverse）。 | `pixabay.py:30-39`（`:34`）、`pexels.py:29-30`；`interfaces.ImageProvider.search` 加关键字参数 `style: str | None = None`（`interfaces.py:73-79`，带默认值，Protocol 兼容）；`handler.py:158-159` 的跳过条件扩到 `p.name in ("openverse","pixabay","pexels")`。 | Pixabay「Systematic mass downloads are not allowed」与预热冲突 [verify images-pipeline O3]；Pexels 20,000/月。 |
| 5 | **打分新信号（字符串/元数据级，无新依赖）**：`description`/`object_name` 进打分 haystack；`aspect < 1.0` −1（竖图在 16:10 盒子只剩 ≈40%）；kid 风格下 Openverse `category=="illustration"` / Pixabay `type in ("illustration","vector")` +2；标签含 `portrait|headshot|selfie|people` −1。黑名单加 `headshot|selfie`（整词）。人脸/文字/复杂度检测留 P3（VLM）。 | `select.py:83`（haystack）、`:87-92`（宽高比）、`:20-24`（黑名单）；`rank(..., style=None)` 透传。 | 现有 7 个信号全是字符串匹配 [images-pipeline-10,11]；竖图裁切算式 [verify images-pipeline-11]。 |
| 6 | **失败词自动重试**：新 `images.service.retry_failed_if_due(conn, word, *, priority, now, min_age_hours=24)`：`image_state=='failed'` 且该词最近一次 `fetch_image` 的 `finished_at` 早于 24 h（`jobs` 按 `json_extract(payload_json,'$.word_id')` 查）→ `enqueue_fetch(priority)`。调用点：`bank.py:636,659`（紧随 `enqueue_content_if_needed`）、`batches.py:360,639`；夜间 `scheduler.maintenance`（`scheduler.py:364-393`）加 `images.service.retry_failed_batch(conn, now, limit=50)`：对 `word_is_studied` 为真的 failed 词、且 `provider_state` 无进行中冷却时入队（priority 30）。 | 入队点只有内容落地与用户动作 [images-pipeline-25]；15 个预取词永久停在卡片 [images-pipeline-28]；「冷却 → 整批跳过 → 不重试」的组合 [verify images-pipeline O9]。 |
| 7 | **文档数字**：$0.028 → $0.0140、18 → 35（见 §3.3 第 7 条）；DESIGN §9 伪代码加生成步骤（P2）。 | — | [verify image-memorability-17] |

**不做**：`MAX_KEYWORDS` 3 → 4（线上无内容带第 4 个关键词 [verify images-pipeline-2]）；`WD_IMAGE_MAX_EDGE` 提高（Commons `THUMB_WIDTH=800` 常量使其无效 [images-pipeline-12]，留 P3）。

### 3.6 生成式位图 provider（P2，默认关闭）

#### 3.6.1 架构：provider，而不是 job / `ai_calls`

**结论**：`backend/wd/images/providers/ai_image.py` 实现 `ImageProvider`（`name="ai_image"`，新增类属性 `kind="generate"`），`search(prompt, limit)` 发一次 `POST {base}/images/generations`，返回一个 `Candidate`。handler 把链按 `ai_image` 的位置切成「前段照片 provider → 生成 → 后段照片 provider → SVG」。

**依据与取舍**：
- `Candidate` 的字段足够描述一张生成图：`provider="ai_image"`、`ref=<created>-<n>`、`title=None`、`creator=<model>`、`license="generated"`、`landing_url=""`、`image_url=<临时 URL>`、`width/height=<size>`、`mime="image/png"`、`extra={"prompt","content_filter","b64": …}`（`interfaces.py:52-70`）。
- 下载 / 归一化 / 存储 / 激活沿用 `fetch.download_and_store`（`fetch.py:271-288`）与 `store.activate_candidate`（`store.py:123-149`）：SSRF 规则（https、公网 IP、`image/*`、魔数、≤8 MB）天然适用；`normalise_image` 把 PNG 重编码为 JPEG，`mime` CHECK（`0001_init.sql:265`）无需改。
- **必须绕过** `select.rank`：`license_allowed("generated")` 为 False（`base.py:184-205`）→ `reject_reason` 的 `"license"`（`select.py:63-64`）。生成候选不排序、不打分，直接下载。
- **不进 `ai_calls`**：`kind` CHECK（`0001_init.sql:511`）与 `provider` CHECK（`0010_ai_provider.sql:9`）都要重建 `ai_calls`；`budget.can_spend`/`failover` 以 `claude|fallback` 两值为前提（`budget.py:36`、`ledger.py:20-21`）。生成失败也不应触发 AI 故障切换。
- **不新增 job 类型**：`jobs.type` CHECK（`0001_init.sql:487`）、`registry.JOB_TYPES`（`registry.py:30-39`）、`queue.IO_TYPES`（`queue.py:34`）、`test_registry_complete` 全要动；而 `fetch_image` 已在 IoWorker 单线程串行（`worker.py:359-362`），正合适。

#### 3.6.2 适配器 `images/providers/ai_image.py`

**请求**（方言由 `WD_IMAGE_GEN_DIALECT` 或主机推断，复用 `openai_http.resolve_dialect` 的思路，`openai_http.py:117-127`）：

| 方言 | 端点 | 请求体 | 响应 |
|---|---|---|---|
| `zhipu`（默认，`bigmodel.cn`） | `POST {base}/images/generations`（base `https://open.bigmodel.cn/api/paas/v4`） | `{"model": "cogview-3-flash", "prompt": …, "size": "1344x768", "watermark_enabled": true, "user_id": "wd-<sha8(word_id)>"}`（不发 `response_format`） | `data[0].url`（临时链接 30 天）、`content_filter[].level` 0–3 |
| `ark`（`volces.com`） | `POST https://ark.cn-beijing.volces.com/api/v3/images/generations` | `{"model", "prompt", "size", "watermark": true, "response_format": "b64_json"}` | `data[0].b64_json` |
| `generic`（OpenAI 形状） | `POST {base}/images/generations` | `{"model", "prompt", "n": 1, "size", "response_format": "b64_json"}` | `data[0].b64_json` 或 `url` |

百炼万相是异步接口、端点按模型不同 [verify image-memorability-27]，**不纳入**（文档注明）。

**响应处理**：
- HTTP ≥400 / 网络错误 → `ProviderError(status, retry_after_s)`（`base.get_json` 的语义，`base.py:100-118`）；handler 现有逻辑对 `None/429/5xx` 冷却、其他记 `last_error`（`handler.py:165-180`）。冷却默认 `quota.DEFAULT_COOLDOWN_S` 10 分钟（`quota.py:28`）。
- 智谱业务码 1301 的 HTTP 400 体（聊天接口上 `openai_http.py:86` 已把它归为 `content_filter`；图片接口是否同码未核）或 `content_filter` 任一 `level > 0` → **返回空列表**并记日志事件 `image_gen_filtered{word_id, level}`（不是 `ProviderError`，不能触发冷却）；handler 继续后段链。
- `url` 必须是 `https://` 公网主机，否则 `fetch.validate_url` 拒绝（`fetch.py:136,149-154`）——**试点第一步用真实 key 确认智谱返回 URL 的主机**（未核实）。
- `b64_json` → 解码 → 新函数 `fetch.store_image_bytes(data, cfg, *, metadata)`（共享 `normalise_image` + `store.write_bytes`），不经过下载。
- 超时 `WD_IMAGE_GEN_TIMEOUT_SEC`（默认 60）；一次调用一张图。
- 密钥：`WD_IMAGE_GEN_API_KEY` 或 `WD_IMAGE_GEN_API_KEY_FILE`（0600 文件首行），复用 `openai_http.api_key` 的读法（`openai_http.py:206-228`）；`WD_IMAGE_GEN_API_KEY` 加入 `SECRET_KEYS`（`config.py:65-75`）；日志里永不出现 key。

#### 3.6.3 提示词模板 `images/gen_prompt.py`

**结论**：中文模板，两套风格，场景取 `content.image_alt_zh`（≤60 字），没有内容时取 `meaning_zh`/`translation` 首行 + lemma；总长 ≤ 300 字。

```
kid:   儿童教育插画，扁平矢量风格，明亮柔和的配色，白色或浅色纯净背景。画面中只有一个清晰的主体：{scene}。
       不要出现任何文字、字母、数字、标志或水印文字；不要人脸特写；不要复杂背景与装饰元素；适合小学生观看。
adult: 简洁的教学配图，写实风格，自然光，构图干净，画面主体单一：{scene}。
       不要出现任何文字、字母、数字或标志；不要人脸特写；不要多余的装饰元素。
```

**依据**：准则 §3.1；CogView 接口没有 `negative_prompt` 参数 [image-memorability-26]，否定项只能写进提示词；`image_alt_zh` 线上最长 20 字 [ai-prompts-stages-12]。安全兜底：`select.is_blocked(image_alt_zh)` 或 `is_blocked(lemma)` 为真（`select.py:40-42`）→ 跳过生成，日志 `image_gen_skipped{reason:"blocklist"}`。

#### 3.6.4 handler 接入（`handler.fetch_for_word`）

**结论**（伪代码，替换 `handler.py:148-206`）：

```
style   = style_for(word)                                   # §3.2
names   = (provider,) if provider else (cfg.image_providers_kid or cfg.image_providers) if style == KID else cfg.image_providers
chain   = providers.build_chain(cfg, names)                 # 'ai_image' 未配置且被显式点名 → ValueError → skipped（现有路径 :150-153）
before, gen, after = providers.split_generator(chain)       # 按 kind == "generate" 切分，最多一个
outcome = _photo_round(before, keywords, style, …)          # 现有 :156-196 的循环体抽成函数，照片 provider 传 style
if outcome is None and gen is not None:
    outcome = _generate_round(gen, word, content, style, priority, requested=(provider == "ai_image"))
if outcome is None:
    outcome = _photo_round(after, keywords, style, …)
if outcome is None: 现有 :198-206（保留原图 / SVG 入队 / failed）
```

`_generate_round` 的门：`cfg.images_enabled`；`priority < 90`（预热从不生成，与 Openverse 同，`handler.py:158-159`）；`quota.check(conn, "ai_image", cfg, now)` 为 None（`quota.py:75-89`）；不在黑名单；`requested=False` 时词当前无 active 图（与 SVG 规则一致：自动路径永不覆盖已有图，`handler.py:201-204`），`requested=True`（API 69 / CLI `--provider ai_image`）则覆盖。调用后 `quota.record`，成功 `quota.mark_ok`，候选经 `fetch.download_and_store(cand, cfg, metadata=aigc.label(...))` 或 `store_image_bytes`，再 `store.activate_candidate(..., query=prompt, alt_zh=alt_zh, score=None)`。

关键词与功能词：§3.5 第 1 项的「功能词不搜照片」只跳过 `_photo_round`，不跳过生成。

#### 3.6.5 配置项（`config.py` + `deploy/env.example` + `docs/DEPLOY.md §4`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WD_IMAGE_GEN_KIND` | `none` | `none` / `openai_http`；`openai_http` 时下面三项必须齐全，否则 `ConfigError` |
| `WD_IMAGE_GEN_BASE_URL` | 空 | 如 `https://open.bigmodel.cn/api/paas/v4`；遵守 `WD_AI_FALLBACK_BASE_URL` 的 scheme/host 规则（`config.py:380-388`） |
| `WD_IMAGE_GEN_API_KEY` / `WD_IMAGE_GEN_API_KEY_FILE` | 空 | 密钥（掩码）/ 0600 文件；文件存在性与权限检查同 `WD_AI_FALLBACK_API_KEY_FILE`（`config.py:391-401`） |
| `WD_IMAGE_GEN_MODEL` | 空 | 如 `cogview-3-flash`（免费）/ `cogview-4` |
| `WD_IMAGE_GEN_DIALECT` | `auto` | `auto` / `zhipu` / `ark` / `generic` |
| `WD_IMAGE_GEN_MINUTE_LIMIT` / `WD_IMAGE_GEN_DAILY_LIMIT` | `4` / `60` | 写入 `quota.limits_for("ai_image")`；0 = 关闭该 provider（`quota.py:82-83` 的 `disabled` 语义）；智谱并发 V0 为 5 [image-memorability-26] |
| `WD_IMAGE_GEN_TIMEOUT_SEC` | `60` | 单次请求超时 |
| `WD_IMAGE_PROVIDERS_KID` | 空 = 同 `WD_IMAGE_PROVIDERS` | kid 风格词的有序链；允许值 = `IMAGE_PROVIDERS` ∪ {`ai_image`} |

校验：`IMAGE_PROVIDERS`（`config.py:52`）加 `ai_image`；任一链含 `ai_image` 而 `WD_IMAGE_GEN_KIND=none` → `ConfigError`；配置了生成器但两条链都不含 `ai_image` → 启动告警「已配置未启用」。`is_keyed("ai_image", cfg)`（`providers/__init__.py:31-37`）= 生成器配置齐全。`Settings.entries()` 自动输出新字段（`config.py:554-575`）。门禁：`test_deploy_files.py:119` 要求 `env.example` 覆盖每个 Settings 字段恰好一次，`test_docs_contract.py:114` 要求 DEPLOY §4 表命名每个变量。

#### 3.6.6 迁移 `0012_word_images_ai_provider.sql`

**结论**：一次 `word_images` 整表重建，只改 `provider` CHECK；停服务执行（非 additive）。

```sql
-- 0012_word_images_ai_provider.sql — word_images.provider gains 'ai_image' (generated bitmaps; design/images/generation-first.md).
-- SQLite cannot ALTER a CHECK: rebuild. No view references word_images (v_bank joins user_words/words only), nothing declares a
-- FOREIGN KEY to it (content_reports.image_id / words.active_image_id are logical), so RENAME needs no legacy_alter_table help.
-- The runner wraps the file in BEGIN IMMEDIATE, turns foreign keys off around it and records schema_migrations(12, …) itself.
CREATE TABLE word_images_new (
  id               INTEGER PRIMARY KEY,
  word_id          INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  provider         TEXT NOT NULL CHECK (provider IN ('wikimedia','openverse','pixabay','pexels','claude_svg','ai_image')),
  provider_ref     TEXT, query TEXT, source_url TEXT, landing_url TEXT, title TEXT, creator TEXT, creator_url TEXT,
  license TEXT, license_url TEXT, attribution_text TEXT, alt_zh TEXT, width INTEGER, height INTEGER,
  file_path        TEXT NOT NULL, file_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
  mime             TEXT NOT NULL CHECK (mime IN ('image/jpeg','image/svg+xml')),
  score            REAL,
  status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','rejected')),
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
INSERT INTO word_images_new SELECT id, word_id, provider, provider_ref, query, source_url, landing_url, title, creator, creator_url,
  license, license_url, attribution_text, alt_zh, width, height, file_path, file_bytes, sha256, mime, score, status, created_at FROM word_images;
DROP TABLE word_images;
ALTER TABLE word_images_new RENAME TO word_images;
CREATE INDEX        ix_word_images_word   ON word_images(word_id, status);
CREATE INDEX        ix_word_images_sha    ON word_images(sha256);
CREATE UNIQUE INDEX ux_word_images_active ON word_images(word_id) WHERE status = 'active';
```

**依据**：原表 `0001_init.sql:245-272`（CHECK `:248`，索引 `:270-272`）；`v_bank` 只连 `user_words`/`words`（`:572-576`）；`words.active_image_id` 是逻辑 FK（`:199`），`INSERT … SELECT id` 保留 id；运行器在文件前后切 `PRAGMA foreign_keys` 并做 `foreign_key_check`（`db.py:15-23,227,246`）。`docs/SCHEMA.sql` 必须与 0001 字节一致（`test_db.py:362`），新 DDL 只进新文件。线上 31 行，毫秒级。不建议顺带加 `'upload'`（策展方案的图片上传尚未设计，CHECK 与 `ImageProviderName` 保持一致更稳）。

#### 3.6.7 许可与署名

- `license='generated'`（与 claude_svg 同），`creator=<model id>`，`creator_url=NULL`，`landing_url=''`，`source_url=<临时 URL 或 NULL(b64)>`，`attribution_text` 由 `attribution_line(None, model, "generated")` 得到 `"cogview-3-flash · generated"`（`store.py:68-73`）——仅供管理员与评估，不对学习者显示。
- `service.image_meta`（`service.py:51-80`）：`generated = provider in ("claude_svg", "ai_image")` → `attribution=None`；`kind = "svg" | "ai" | "photo"`。
- `ATTRIBUTION.md` §3.4（`:54-59`）加一条「**AI 生成配图** — 国产文生图接口（默认智谱 CogView）按管理员配置生成的位图，`provider='ai_image'`，带厂商水印与文件内 AIGC 标签；版权按厂商用户协议由本部署运营者维护，不含第三方素材」；§6 表（`:74-79`）加题注行。智谱协议要点：生成内容版权由用户维护；不得消除/篡改显式与隐式标识；付费功能可按授权商用；不得用于训练其他模型 [image-memorability-26]。
- 前端 `zh.settings.sources.images`（`zh.ts:86`，镜像 `docs/FRONTEND.md:292`）加「AI 生成配图」。

#### 3.6.8 标识合规（《人工智能生成合成内容标识办法》，2025-09-01 施行）

**结论**：

| 层 | 位图（ai_image） | SVG（claude_svg v2） | 模板卡 |
|---|---|---|---|
| 显式标识 | 厂商水印（智谱默认开，关闭需签免责声明 [verify image-memorability-26]；本设计不提供关闭开关）+ UI 题注「AI 生成配图」 | 服务端注入右下角 `AI` 角标（`font-size 14`、`fill-opacity 0.45`）+ UI 题注「AI 生成示意图」 | 题注「系统生成卡片」（非 AI 生成，不含模型输出） |
| 隐式标识（文件元数据） | `normalise_image(..., comment=<JSON>, xmp=<XMP 包>)`：JPEG COM 段 + XMP `rdf:Description`（自定义命名空间 `wd:aigc`） | `<desc id="aigc-label">{JSON}</desc>` 紧随 `<svg …>` | 无 |

JSON 标签字段（本文定义，**GB 45438-2025 的规范字段名待核对国标原文后映射**，INDEX 已注明国标原文未读）：`{"aigc": true, "label": "AI 生成", "producer": "word-Dance/<version> via <vendor>", "model": "<model id>", "generated_at": "<UTC ISO>", "propagator": "<WD_PUBLIC_URL host 或 self-hosted>"}`。实现放在 `backend/wd/images/aigc.py`（`label(cfg, *, vendor, model, now) -> dict`、`xmp_packet(label) -> bytes`、`svg_desc(label) -> str`）。

**依据**：Pillow 12.3.0（`.venv` 实测）的 `JpegImagePlugin._save` 读取 `comment` / `xmp` / `exif` 参数；`normalise_image` 现在把 EXIF/ICC 剥光（`fetch.py:241-268`，`:267` 的 `img.save`），所以必须在这一步写入，而不是事后再编码一次；SVG 白名单含 `desc`（`sanitize_svg.py:28-31`），`<metadata>` 不在白名单且子元素是外命名空间会被丢，故用 `desc`。主体定位（本应用是「服务提供者」还是「传播者」）仍是推断 [verify image-memorability 遗漏 4]——标签同时填 producer 与 propagator 两者，覆盖两种定性。线上 30 张旧 SVG 没有任何文件内标识，P1 不回填（它们服务的是四级词，等 Q7 决策后统一重画）。

#### 3.6.9 内容过滤兜底（面向小学生）

1. 入口：lemma / `image_alt_zh` 命中 `BLOCKLIST_RE` → 不生成（§3.6.3）。
2. 厂商：智谱 `content_filter[].level > 0` 或 1301 → 丢弃、记事件、走后段链（§3.6.2）。
3. 出口：举报路径不变——`POST /api/words/{id}/report {target:'image', reason:'inappropriate_image'}` 立即 `rejected` + 重抓（`words.py:278-280`、`service.py:186-202`）；重抓时 `exclude` 含被拒 sha（`handler.py:153`），生成器每次产出不同图，不会重复命中。
4. 评估：试点统计 `content_filter` 等级分布与人工 Q3（无文字/无人脸/无敏感）通过率，作为是否把生成器放到 kid 链首位的门槛（§3.8）。

#### 3.6.10 成本与预算

- **计数上限**：`quota.limits_for("ai_image") = (cfg.image_gen_minute_limit, cfg.image_gen_daily_limit)`（`quota.py:37-47`）；`quota.status` 自动把 `ai_image` 作为一行报给 `AdminOverview.images.providers`（`quota.py:160-179`，`ProviderQuota.provider` 是 `str`，`schemas.py:1132-1138`，无契约改动）。
- **与 SVG 子预算**：互不相干。生成成功的词不会再入队 SVG（有 active 图，`handler.py:201-204`）；生成失败/过滤/冷却则 SVG 照旧兜底。
- **与 AI 美元日预算**：不计入（§3.6.1）。
- **与 `photo_mix`**：SQL 加 `SUM(wi.provider='ai_image') AS with_ai_image`（`service.py:237-246`）；`AdminOverviewWords` 加 `with_ai_image: int`（`schemas.py:1094-1101`、`docs/API.md:420-421`、`types.ts` 的 `AdminOverview.words`）；`AdminPage.ImageMix`（`AdminPage.tsx:147-154`）加第四段 `zh.admin.images.ai`。
- **全库折算**（9,162 词，7.1 CNY/USD）：Flash ¥0；CogView-4 ¥550；GLM-Image ¥916；Seedream 5.0-flash ¥1,099；对比 Claude SVG ¥807–911 [INDEX 4.3]。默认 60/日时全库需 153 天；试点日临时 `WD_IMAGE_GEN_DAILY_LIMIT=250`。
- `wd images-prune`（`handler.py:298-331`）会删掉无人学的词的生成图，与「全库预生成」相抵 [verify images-pipeline O7]——P2 只在 `docs/ops.md:202` 加一句提醒，不改行为。

#### 3.6.11 API 与前端契约（同一提交，`docs/API.md:3` 规则）

| 契约点 | 后端 | 前端 | 文档 |
|---|---|---|---|
| `ImageProviderName` | `schemas.py:46` 加 `"ai_image"`（顺序：…`claude_svg`, `ai_image`, `card_svg`，与 TS 一致——`check_contract.py:274-281` 顺序敏感） | `types.ts:84` | `API.md:318` |
| `ImageMeta.kind` | `schemas.py:579` `Literal["photo","svg","card","ai"]` | `types.ts:83` | `API.md:317`、§9.1 `:465` |
| `AdminOverviewWords.with_ai_image` | `schemas.py:1094-1101` | `types.ts` `AdminOverview.words` | `API.md:420-421` |
| `RefetchImageRequest.provider` | `schemas.py:1350` 加 `"ai_image"` | `endpoints.ts:340` `RefetchProvider` | `API.md:231`（端点 69） |
| CLI `--provider` | `handler.py:352` choices 加 `ai_image` | — | `DEPLOY.md:417` |
| `WordImage` | — | `WordImage.tsx:45,50`：`generated = kind in ('svg','ai')`；盒子 `--flat` 仅 `svg`/`card`（位图用 `cover`）；`imageCaption`（`:26-33`）`kind==='ai'` → `zh.word.aiPicture` | `FRONTEND.md:87` |
| 文案 | — | `zh.ts:54` 加 `aiPicture: 'AI 生成配图'`；`zh.ts:92` `admin.images` 加 `ai: 'AI 配图'`；`zh.ts:86` 来源行 | `FRONTEND.md:260,298,292` 逐行镜像（`zh.test.ts:67`、`zh.contract.test.ts:61`） |

CSP 不变：图片仍经 `/media/images/...` 同源 cookie 门禁提供（`media.py:38-48`；`main.py:93-102` `img-src 'self' data:`），临时 URL 从不热链。

#### 3.6.12 无 key 的测试替身

**结论**：

1. `backend/tests/fake_image_gen.py`：`transport(mode="ok", *, calls=None) -> httpx.MockTransport`，与 `fake_openai.transport` 同形（`fake_openai.py:93-122`）。路由 `POST */images/generations`：`ok_url`（返回 `data[0].url = https://fake-cdn.example/<id>.png`，同一 transport 对该主机返回一张 Pillow 画的 1344×768 PNG，右下角写有「AI 生成」字样）、`ok_b64`、`filtered`（`content_filter level 2`）、`sensitive_400`（智谱 1301 体）、`401`、`429`（`Retry-After: 2`）、`503`、`invalid_json`。请求体记录到 `calls`（不记 key，只记 sha256，照 `fake_openai.py:104-112`）。
2. `smoke_mock.MockHttp.handle`（`smoke_mock.py:91-103`）加两条默认路由：`open.bigmodel.cn` + `/api/paas/v4/images/generations` → `ok_url` 响应；`fake-cdn.example` 加入 `IMAGE_HOSTS`（`:35`）返回 PNG。这样 `WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 wd fetch-image apple --provider ai_image` 在 Mac 上不出网即可跑通（`smoke_mock.py:114-137` 的安装路径对所有 `wd` 子命令生效）。
3. `pinned_dns` 夹具（`test_images.py:31-33`）已把所有主机解析到公网测试 IP，下载路径无需改。

---

### 3.7 展示与数据模型

**结论**：

1. **图在回忆之后**（现状：`StudyCard.tsx:302-311` 只在背面渲染 `WordImage`，正面 `:201-228` 无图）。不改。依据 §3.1 第 7 行。第三期候选：用户设置 `image_hint: 'off' | 'front'`（`user_settings` `ALTER TABLE ADD COLUMN`，additive；`schemas.Settings`/`SettingsUpdateRequest`/`types.ts`/`API.md`/`SettingsPage`/`zh.ts`/`FRONTEND §8`），且仅当 `word_images.query IN ('svg-v2') OR provider='ai_image'`（无文字图）时正面展示——旧 SVG 与模板卡永不作提示。
2. **每词多图**：不做。若第三期要「同词给小学生插画、给高中生照片」：`word_images` 加 `style TEXT NOT NULL DEFAULT 'any' CHECK (style IN ('any','kid','adult'))`（需再次重建，可并入 0012 预留——**本文不预留**，因为 `ImageMeta` 按用户解析要把 `image_meta(conn, word_id)` 改成带用户阶段的签名，`words.image_meta_for`（`services/words.py:470-479`）、`routers/words.py:226-229`、`StudyItem.image` 的组装全要跟，不是加一列的事）；唯一索引改为 `(word_id, style) WHERE status='active'`；`photo_mix` 按 style 分列。
3. **`show_images` 粒度**：保持全局布尔（`0001_init.sql:149`、`schemas.py:167,387`、`SettingsPage.tsx:413`）。不加「只对小学词显示」之类的细分：A6 下新用户默认 K-12，默认开即可；成人用户可整体关闭（成人配图收益不确定 [image-memorability-6,7]）。

### 3.8 评估试点（P2 末尾，1 人日 + 少量调用费）

**样本**（已用只读库核算）：国家二级 505 词转录件 504 条 → 497 在库 → ECDICT `pos` 主标签 n 179 / v 135 / j 44 = 358 词可画；取 **200** = 名词 100 + 动词 70 + 形容词 30（各按 `frq` 升序）。备选池：`stage_min=1 AND kind='word' AND pos 主标签='n' AND frq BETWEEN 300 AND 3000` 共 442 词。注意 200 词中仅 1 词有内容、0 词有图：先为 200 词生成内容（CLI ≈ 200 × $0.004 = $0.8，或走备选 GLM 免费；`eval_provider.py` 不需要改）。

**三臂（脚本 `scripts/pilot_images.py`，新建；只写自己的 scratch 目录，不激活、不碰线上库）**：

| 臂 | 做法 | 费用 |
|---|---|---|
| A 照片 | 对每词按 `handler` 相同逻辑调用 `providers.build_chain(cfg, ("wikimedia","openverse"))` + `select.rank` + `fetch.download_and_store` 到 `--out`，记录 provider / 分数 / 失败原因；需在出口正常的机器（东京盒）跑，Openverse 注册 app 以免 200/日 | ¥0 |
| B SVG v2 | `svg.prompt_for` + `runner.run_claude(kind="svg")`，对私有拷贝 DB 记账；`sanitize_svg.clean(allow_text=False)` 后转 PNG 预览（用 `rsvg-convert` 或浏览器） | ≈ $0.0140 × 200 = $2.8 |
| C 生成 | `AiImageProvider.search(gen_prompt.build(...), 1)`（Flash 免费；可加 CogView-4 一臂 ¥12 对照） | ¥0 / ¥12 |
| D 零点 | 模板卡（`card_svg.render`） | ¥0 |

产出 `sheet.html`（每词四图并排，不显示词头，评分者先看图写出猜到的词义再翻看答案）+ `scores.csv` 模板。**人工评分表**（每图 0–2 分）：Q1 单一清晰所指；Q2 与例句 1 义项/情境一致；Q3 无文字、无人脸特写、无敏感；Q4 小学生能看懂；Q5 自由项「最能帮我记住这个词」（每词每人选一臂）。两名评分者（一名成人，尽量一名家长代孩子看），计算 Q1–Q4 均值、Q5 票数、一致率。

**可选自动评分**：GLM-4.6V-Flash（官方标免费 [image-memorability-32]）通过 `chat/completions` 的 `image_url` 传 base64 图 + `image_alt_zh` + 例句，要求按 Q1–Q3 输出 0–2 分 JSON；试点阶段写进 `scores.csv` 的 `auto_*` 列并与人工对比一致率；一致率 ≥ 0.7 时第三期再把它接到 `word_images.score`（`0001_init.sql:266`，目前只存 `select.score` 的整数分 [verify image-memorability-21]）。

**决策门槛**：C 臂 Q1+Q2 均值比 B 高 ≥ 0.5、Q3 通过率 ≥ 90%、`content_filter` 拒绝率 ≤ 5% → P3 把 `ai_image` 设为 KID 链首位、CogView-4 作为付费升级档；C 与 B 持平 → 生成留在链末兜底（省下 SVG 的 $）；C 明显差 → 关闭生成，照片链 + SVG v2。另记：平均延迟、URL 主机、水印是否可见、Flash 与 CogView-4 的差异。

**文档更新**（P1 已含）：DESIGN §9 的 $0.028→$0.014、18→35；P2 在 DESIGN §9 伪代码加 `generate` 步骤与 `ai_image` 段落；`docs/ops.md:198` 加「配图来源切到生成」的处置。

### 3.9 分期

| 期 | 范围 | 可合并条件 |
|---|---|---|
| **P1（本周，无 key，无迁移）** | §3.3 全部（SVG v2 / `&` 修复 / 文字剥离 + 角标 + desc / `query='svg-v2'` / ESTIMATES）；§3.4 第 1、2、4 条；§3.5 七项；`images/style.py`；文档数字 | 全部测试绿；`check_contract.py` OK；`npm test` 绿；`docs/SCHEMA.sql` 未动 |
| **P2（需智谱 key）** | §3.6 全部 + 0012 + 契约 + 前端 + fake + `scripts/pilot_images.py` + 一次真跑 | 同上 + 私有拷贝 DB 排练 0012 + `WD_SMOKE_MOCK_HTTP=1` 冒烟 + 真 key 对 3 个词各生成一张并目检水印/元数据 |
| **P3（视评估）** | 正面提示设置；每词多图；VLM 评分写 `score`；`image_scene_en`；Pixabay/Pexels 插画参数与 key；自绘水印（若厂商水印关闭）；`image_calls` 美元账本（若要） | 试点结论 |

---

## 4. 改动清单（文件 → 改什么）

### 4.1 P1

| 文件 | 改什么 |
|---|---|
| `backend/wd/ai/prompts/svg_system.txt:1` | 系统提示词 v2（§3.3 第 1 条） |
| `docs/CLAUDE_INTEGRATION.md:279-285` | §5.5 代码块与示例用户提示词同步；`:407` `$0.028` → `$0.014`；`:416` 「≈ 18 cards」→「≈ 35 cards」；`:355` 「15–240」→「10–240」 |
| `backend/wd/ai/svg.py:40-52` | `build_user_prompt(display, meaning, concept, style)` 加风格句；`prompt_for` 调 `style.style_for(word)` |
| `backend/wd/images/style.py`（新） | `KID/ADULT`、`kid_max_index()`、`style_for(word)` |
| `backend/wd/images/sanitize_svg.py:65-79` | `_parse` 前的裸 `&` 修复；`clean(svg, *, allow_text=True)`；`_serialise` 按 `allow_text` 丢 `text`/`tspan` |
| `backend/wd/images/aigc.py`（新） | `label()`、`xmp_packet()`、`svg_desc()`、`svg_mark()`（P1 先用于 SVG；P2 复用） |
| `backend/wd/images/store.py:152-174` | `activate_svg`：`clean(svg, allow_text=False)` → 注入 `svg_desc` + `svg_mark` → `activate(..., query="svg-v2", ...)` |
| `backend/wd/ai/budget.py:33,273` | `ESTIMATES["svg"]` 0.03 → 0.015；注释数字 |
| `backend/wd/ai/prompts/content_system.txt:6,9,10` + `docs/CLAUDE_INTEGRATION.md:208-225`（§5.1 代码块） | 例句长度/语域规则、`image_keywords`、`image_alt_zh` 新语义（§3.4） |
| `backend/wd/ai/content.py:46,54` | `PROMPT_VERSION="content-v2"`；`EXAMPLE_EN_MIN=10` |
| `backend/wd/images/handler.py:121-124,134-137,148-206,158-159,352` | SELECT 加 `stage_min, pos`；功能词跳过照片；循环体抽成 `_photo_round(providers, keywords, style, …)`；keyed provider 在 priority ≥ 90 跳过；`--provider` choices 留在 P2 |
| `backend/wd/interfaces.py:73-79` | `ImageProvider.search(self, query, limit, *, style: str | None = None)` |
| `backend/wd/images/providers/wikimedia.py:40-51,53-57,97` | `iiprop` 加 `thumbmime`、`maxlag=5`、`filetype:drawing`（kid）、`mime = info.get("thumbmime") or …`、`error.code=="maxlag"` → `ProviderError(503, retry_after)` |
| `backend/wd/images/providers/openverse.py:28,41-42,72,114-119` | `page_size=min(limit,20)`；`category=illustration`（kid）；`extra["category"]` |
| `backend/wd/images/providers/pixabay.py:30-39`、`pexels.py:29-30` | `style` 参数；Pixabay `image_type`/`orientation` 按风格 |
| `backend/wd/images/select.py:20-24,30,67-69,80-101,104-128` | 黑名单加 `headshot|selfie`；插画候选尺寸门槛 300×200；description/object_name 进打分；竖图 −1；插画 +2（kid）；人物标签 −1；`rank(..., style=None)` |
| `backend/wd/images/service.py`（新函数） | `retry_failed_if_due(conn, word, *, priority, now, min_age_hours=24)`、`retry_failed_batch(conn, now, *, limit=50)` |
| `backend/wd/services/bank.py:636,659`、`backend/wd/services/batches.py:360,639` | 调 `retry_failed_if_due` |
| `backend/wd/jobs/scheduler.py:364-393` | `maintenance` 加 `retry_failed_batch` 步骤（try/except 同其他步骤） |
| `docs/DESIGN.md:28,518,550`、`docs/DEPLOY.md:326,434`、`docs/ops.md:198`、`deploy/env.example:83` | $0.028 → $0.014、18 → 35 |
| `docs/DESIGN.md §9`（`:523-553`） | 伪代码加「功能词不搜照片」「失败词重试」「SVG 无文字 + 角标 + desc」 |
| `ATTRIBUTION.md:56` | 「AI 生成示意图」条目补「不含文字、带 AI 角标与文件内标签」 |

### 4.2 P2

| 文件 | 改什么 |
|---|---|
| `backend/wd/migrations/0012_word_images_ai_provider.sql`（新） | §3.6.6 全文 |
| `backend/wd/images/providers/ai_image.py`（新） | `AiImageProvider(name="ai_image", kind="generate")`：方言、请求体、`search(prompt, limit)`、`content_filter`、`b64`/`url`、`ProviderError` 映射、key 读取 |
| `backend/wd/images/gen_prompt.py`（新） | `build(word, content, style) -> str`（§3.6.3） |
| `backend/wd/images/providers/__init__.py:21-28,31-37` | `PROVIDER_CLASSES["ai_image"]`；`PHOTO_PROVIDERS` 不含它（新增 `GENERATOR_PROVIDERS`）；`is_keyed("ai_image")`；`split_generator(chain)` |
| `backend/wd/images/handler.py:148-206,352` | `_generate_round`；链切分；`names` 按风格选链；`--provider` choices 加 `ai_image` |
| `backend/wd/images/fetch.py:241-268,271-288` | `normalise_image(..., comment=None, xmp=None)`；`download_and_store(..., metadata=None)`；新 `store_image_bytes(data, cfg, *, metadata)` |
| `backend/wd/images/quota.py:37-47` | `limits_for("ai_image")` 读 cfg |
| `backend/wd/images/service.py:51-80,237-246` | `image_meta` 的 `kind`/`attribution`；`photo_mix` 加 `with_ai_image` |
| `backend/wd/config.py:52,65-75,155-168,355-369,522-534` | `IMAGE_PROVIDERS` 加 `ai_image`；`SECRET_KEYS` 加 `WD_IMAGE_GEN_API_KEY`；10 个新字段与解析/校验；`image_providers_kid` |
| `backend/wd/schemas.py:46,579,1094-1101,1350` | `ImageProviderName`、`ImageMeta.kind`、`AdminOverviewWords.with_ai_image`、`RefetchImageRequest.provider` |
| `frontend/src/api/types.ts:83-84` + `AdminOverview.words` | 镜像 |
| `frontend/src/api/endpoints.ts:340` | `RefetchProvider` 加 `'ai_image'` |
| `frontend/src/components/study/WordImage.tsx:26-33,45,50` | `kind==='ai'` 的题注与盒子 |
| `frontend/src/pages/AdminPage.tsx:147-154` | `ImageMix` 第四段 |
| `frontend/src/i18n/zh.ts:54,86,92` + `docs/FRONTEND.md:260,292,298` | `word.aiPicture`、`sources.images`、`admin.images.ai` |
| `docs/API.md:231,317-318,420-421,465` | 端点 69、`ImageMeta`、`AdminOverview.words`、§9.1 |
| `docs/DEPLOY.md §4`（`:296` 起，图片行 `:338-345` 附近）、`deploy/env.example:149-165` 附近 | 10 个新变量的行 |
| `docs/DESIGN.md:28,523-553` | 执行摘要与 §9 加 `ai_image` 段落与伪代码 |
| `docs/ops.md:198,202` | 处置行；`images-prune` 提醒 |
| `ATTRIBUTION.md:54-59,74-79` | §3.4 新条目、§6 题注行 |
| `backend/wd/smoke_mock.py:35,91-103` | 生成端点与假 CDN 路由 |
| `backend/tests/fake_image_gen.py`（新） | §3.6.12 |
| `scripts/pilot_images.py`（新） | §3.8 三臂 + 接触表 + CSV |

### 4.3 P3（仅列标题）

`user_settings.image_hint`（additive 迁移 0013+）与正面提示挂点 `StudyCard.tsx:206`；`word_images.style` 与唯一索引；`images/scorer.py`（GLM-4.6V-Flash）写 `word_images.score`；`image_scene_en`（§3.4 第 3 条清单）；Pixabay/Pexels key 与参数；`WD_IMAGE_MAX_EDGE` + `THUMB_WIDTH` 可配置（`wikimedia.py:27`）。

---

## 5. 测试与验收

### 5.1 会变红的现有测试（及处置）

| 测试 | 为什么红 | 处置 |
|---|---|---|
| `backend/tests/unit/test_schemas.py:122-127` `test_prompts_are_verbatim_from_section_5[svg_system]`、`[content_system]` | 提示词文件改了 | 同步 `CLAUDE_INTEGRATION.md` §5.1 / §5.5 代码块（P1） |
| `backend/tests/unit/test_content_apply.py:81` | `prompt_version == "content-v1"` | 改为 `content-v2`（P1） |
| `backend/tests/unit/test_budget.py:33` | `estimate("svg") == 0.03` | 改 0.015（P1） |
| `backend/tests/integration/test_images.py:608-623` `test_activate_svg_sanitises_and_serves_a_svg_image` | 第 616 行断言 `"<text" in stored`——模型文字被剥离，但角标 `<text>` 仍在，断言恰好仍真；语义需改 | 改为断言词头文字不在、`AI` 角标与 `<desc id="aigc-label"` 在、`query=='svg-v2'`（P1） |
| `backend/tests/integration/test_images.py:535-547` `test_keywords_come_from_content_with_blocklist_and_shape_filter` | 若夹具词无 `pos`（`insert_word` 不设 `pos`，`:48-52`）则功能词规则不触发——应仍绿；需确认 | 跑一遍确认（P1） |
| `backend/tests/unit/test_providers.py:46-70` `test_wikimedia_request_shape_and_user_agent` | `params()` 多了 `thumbmime`/`maxlag` | 更新期望参数（P1） |
| `backend/tests/unit/test_providers.py:172-203`（Openverse 请求形状、`page_size`） | `page_size` 随 `limit` | 更新（P1） |
| `backend/tests/unit/test_select.py:92-119` `test_score_table` | 新信号改变个别分值（竖图 −1、description 命中） | 逐行更新打分表（P1） |
| `backend/tests/unit/test_config.py:25-39,101-107`、`test_deploy_files.py:119-150`、`test_docs_contract.py:114-133` | 新 Settings 字段 → `env.example` 与 DEPLOY §4 必须同步 | 加行（P2） |
| `backend/tests/unit/test_providers.py:374-384` `test_build_chain_respects_order_keys_and_unknown_names` | `ai_image` 未配置时被跳过 / 配置后在链中 | 加断言（P2） |
| `backend/tests/integration/test_images.py:626-635` `test_photo_mix_counts` | 返回字典多 `with_ai_image` | 更新（P2） |
| `backend/tests/integration/test_admin_ops.py:144` `test_overview_numbers` | `words` 多一键 | 更新（P2） |
| `backend/tests/unit/test_db.py:236-257` `test_upgrade_from_the_baseline_schema_applies_the_later_files` | 按 `shipped_migrations()` 动态比对，0012 自动纳入；`_counts` 前后相等——重建保留行数 | 应保持绿；跑一遍（P2） |
| `scripts/check_contract.py` | `ImageProviderName` 顺序 | 两边同序（P2） |
| `frontend/src/i18n/zh.test.ts:67`、`zh.contract.test.ts:61` | `zh.ts` 与 FRONTEND §8 不一致 | 同步（P2） |

### 5.2 新增测试

**P1**
- `test_sanitize_svg.py`：`test_bare_ampersand_is_repaired_before_parse`（`&` 修复后通过，`&amp;` 不被双重转义，`<` 仍拒）；`test_allow_text_false_drops_text_and_tspan_but_keeps_title_desc`。
- `test_images.py`：`test_activate_svg_v2_strips_model_text_adds_mark_desc_and_query_marker`；`test_function_word_without_keywords_skips_photo_providers`（无 provider 请求、直接 SVG 判定）；`test_failed_word_is_retried_when_studied_after_24h`（`retry_failed_if_due` 入队、24h 内不入队）；`test_maintenance_retries_failed_studied_words_only_when_no_cooldown`。
- `test_providers.py`：`test_wikimedia_maxlag_error_body_becomes_a_503_provider_error`；`test_wikimedia_uses_thumbmime_and_drawing_for_kid_style`；`test_openverse_page_size_follows_limit_and_category_for_kid`；`test_pixabay_illustration_params_for_kid_style`。
- `test_select.py`：新打分行（竖图、description、illustration bonus、headshot 黑名单）；`test_small_illustration_passes_relaxed_size_gate`。
- `test_svg_prompt.py`（新，unit）：`build_user_prompt` 带风格句；`style_for` 对 `stage_min` 0/1/2/None 的判定（0 为阶段模型方案 b 的预演）。
- `test_content_apply.py`：`test_example_of_10_to_14_chars_is_now_kept`。

**P2**
- `test_ai_image_provider.py`（新，unit，`fake_image_gen.transport`）：请求体按方言（zhipu 无 `response_format`、`watermark_enabled` 为 true、`size`）；`url` 与 `b64_json` 两种响应都给出 `Candidate`；`content_filter level>0` → `[]` + 事件；1301 体 → `[]`；401/429/503 → `ProviderError(status, retry_after)`；key 从环境或 0600 文件读，错误与日志不含 key。
- `test_images.py`：`test_ai_image_first_in_kid_chain_generates_before_photos`（`stage_min=1`，`image_providers_kid=("ai_image","wikimedia")`，Commons 未被调用）；`test_ai_image_last_in_adult_chain_runs_after_photos_and_before_svg`；`test_ai_image_never_runs_at_prewarm_priority`；`test_ai_image_respects_minute_and_day_limits_and_cooldown`（`provider_usage` 计数、429 → `provider_state.cooldown_until`）；`test_ai_image_filtered_falls_through_to_svg`；`test_ai_image_row_shape`（`provider='ai_image'`, `license='generated'`, `creator=model`, `query=prompt`, `mime='image/jpeg'`, `alt_zh`）；`test_ai_image_meta_kind_and_caption`（`kind=='ai'`, `attribution is None`, `ImageMeta.model_validate`）；`test_jpeg_carries_aigc_comment_and_xmp`（Pillow 读回 `info["comment"]`、`info.get("xmp")` 含 `"aigc": true`）；`test_explicit_ai_image_request_overrides_an_active_photo`；`test_blocklisted_alt_skips_generation`；`test_photo_mix_counts_ai_image`。
- `test_db.py`：`test_0012_rebuild_keeps_rows_ids_indexes_and_accepts_ai_image`（在基线 + 31 行样本上跑 `run_migrations`，断言 `ids` 不变、三索引存在、插入 `provider='ai_image'` 成功、`'flickr'` 失败）。
- `test_config.py`：`test_image_gen_requires_full_config_when_listed`、`test_image_providers_kid_defaults_to_main_chain`、`test_image_gen_key_is_masked`。
- `test_admin_ops.py`：overview 含 `with_ai_image` 与 `ai_image` 的 `ProviderQuota` 行。
- `test_smoke_mock.py`：新路由命中。
- 前端：`StudyCard.test.tsx` 加一例 `kind:'ai'` 的题注与 cover 盒子；`zh` 两个契约测试自动覆盖。

### 5.3 在 live-copy 的私有拷贝上排练（不碰 `/Users/sqin/word-dance-data`）

```
MINE=/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/design-images-generation
/opt/homebrew/bin/python3.12 -I -c "import sqlite3; s=sqlite3.connect('file:$SP/live-copy.db?mode=ro', uri=True); s.execute(\"VACUUM INTO '$MINE/rehearsal.db'\")"
mkdir -p $MINE/data
WD_DATA_DIR=$MINE/data WD_DB_PATH=$MINE/rehearsal.db .venv/bin/wd migrate --dry-run      # 列出 0011?/0012
WD_DATA_DIR=$MINE/data WD_DB_PATH=$MINE/rehearsal.db .venv/bin/wd migrate                # 走 run_migrations，不用 /usr/bin/sqlite3
sqlite3 -readonly $MINE/rehearsal.db "SELECT sql FROM sqlite_master WHERE name='word_images'; SELECT COUNT(*), MIN(id), MAX(id) FROM word_images; PRAGMA foreign_key_check; PRAGMA integrity_check;"
WD_DATA_DIR=$MINE/data WD_DB_PATH=$MINE/rehearsal.db WD_DEV=1 WD_SMOKE_MOCK_HTTP=1 WD_IMAGE_GEN_KIND=openai_http WD_IMAGE_GEN_BASE_URL=https://open.bigmodel.cn/api/paas/v4 WD_IMAGE_GEN_MODEL=cogview-3-flash WD_IMAGE_GEN_API_KEY=fake WD_IMAGE_PROVIDERS_KID=ai_image,wikimedia,openverse .venv/bin/wd fetch-image apple --provider ai_image
```

验收点：`word_images` 31 行 id 不变；CHECK 含 `ai_image`；`fetch-image` 输出 `provider: ai_image`、文件为 JPEG 且 Pillow 读到 `comment` 含 `"aigc": true`；`wd fetch-image despite --no-svg` 对功能词不发任何 provider 请求（日志无 `provider_skipped`/`provider_error`，`MockHttp.calls` 为空）。排练用 `.venv/bin/python` 的 `run_migrations`，不要用 `/usr/bin/sqlite3` 手工跑 DDL（其 `legacy_alter_table=1` 会掩盖问题 [INDEX A4]）。

---

## 6. 上线与回滚（Mac，launchd）

P1 不含迁移：`git pull` → `.venv/bin/pip install -e backend`（无新依赖）→ `cd frontend && npm ci && npm run build` → 重启 launchd agent（label 见 `memory/macos-local-install.md`）→ `GET /api/health`。新提示词只影响新生成的卡与图。

P2（含 0012，非 additive，**必须停服务**）：

1. `launchctl bootout gui/$(id -u)/<label>`；`pgrep -fl "wd serve"` 确认无进程。
2. 手工快照：`.venv/bin/wd backup`（`wd migrate` 自己还会写 `backups/pre-migrate-<from>-to-12.db.gz`，`db.py:252-261`）。
3. `git pull` → `pip install -e backend` → `npm ci && npm run build`。
4. `.env`：先**不**启用生成（`WD_IMAGE_GEN_KIND=none`，两条链不含 `ai_image`），仅为迁移上线。
5. `.venv/bin/wd migrate --dry-run` 应只列 0012（或 0011+0012）；`.venv/bin/wd migrate`；`sqlite3 -readonly <db> "SELECT COUNT(*) FROM word_images"` = 31（或当时值）。
6. `wd import-seed`：本设计不改种子，`kv.seed_version` 哈希不变 → 空操作，可跳过。
7. `launchctl bootstrap gui/$(id -u) <plist>`；`GET /api/health`；管理页概览 `images.providers` 列表正常、`words.with_ai_image = 0`。
8. 启用试点：`.env` 写 `WD_IMAGE_GEN_KIND=openai_http`、`WD_IMAGE_GEN_BASE_URL`、`WD_IMAGE_GEN_MODEL=cogview-3-flash`、`WD_IMAGE_GEN_API_KEY_FILE=<0600 文件>`、`WD_IMAGE_PROVIDERS_KID=ai_image,wikimedia,openverse`，重启；`wd fetch-image <某小学词> --provider ai_image` 目检：水印可见、题注「AI 生成配图」、`sqlite3 … SELECT provider, creator, query FROM word_images ORDER BY id DESC LIMIT 1`。
9. 回滚：代码回滚到上一个 tag 即可（0012 只放宽 CHECK，旧代码读写 `word_images` 不受影响——但旧代码的 `ImageMeta.provider` Literal 不含 `ai_image`，已生成的行会让 `/api/words/{id}` 500）；因此回滚前先 `UPDATE word_images SET status='rejected' WHERE provider='ai_image' AND status='active'` 并把对应 `words.active_image_id` 置 NULL、`image_state='failed'`，或直接 `wd restore backups/pre-migrate-*-to-12.db.gz`（需停服务，`DEPLOY.md:421`）。

---

## 7. 风险、未决问题、工作量

### 7.1 风险（按影响排序）

1. **标识合规的主体定位与国标字段**：本应用是否构成「服务提供者」为推断；GB 45438-2025 原文未读，JSON 键名可能需要重命名（代价小：`images/aigc.py` 一处 + 回填脚本）。缓解：标签同时写 producer 与 propagator；厂商水印保持开启。
2. **智谱返回 URL 的主机/协议未核实**：若非 https 公网主机，`fetch.validate_url` 拒绝，生成臂整体失败。缓解：适配器支持 `b64_json`（generic/ark），真跑第一步就验证；必要时为 zhipu 增加「先 HEAD 再下载」不是选项（仍受 SSRF 规则），只能改用 b64 若厂商支持。
3. **生成图对「义项一致」的真实表现未知**（直接实证空白 [INDEX 未解决 8]）；中文场景句 ≤30 字可能不足。缓解：试点三臂对照；`image_scene_en` 的 10 处改动面已备案。
4. **内容过滤拒绝率**对学校词表未知（`weapon`、`blood` 等词 [verify images-pipeline 未解决 3]）。缓解：黑名单前置跳过 + 过滤事件统计 + SVG 兜底。
5. **阶段模型迁移与 0012 的顺序**：两者都是停机重建，建议同一次停机先后执行（0011 → 0012），排练在同一私有拷贝上串行跑。
6. **提示词变更的回归**：`content-v2` 的例句下限 10 字符放宽后，备选模型的「词头出现」规则更易过，但 4 词以下短句质量未测；`eval_provider.py` 成绩单不按阶段拆分 [ai-prompts-stages-16]。
7. **Pixabay 条款**：`image_type=illustration` 代码写好但无 key 不启用；一旦启用仍受「禁系统性批量下载」约束，只能按需抓（预热跳过已实现）。
8. **`wd images-prune`** 会删无人学的词的生成图；若未来做全库预生成需改该命令或文档。

### 7.2 未决问题（需产品负责人或真跑回答）

1. 生成器放在 KID 链首位还是链末（Q7-b 的最终形态）——等试点数据。
2. 成人链是否完全不配图、只在用户开启时才生成（省钱）——证据偏向「成人配图收益不确定」[image-memorability-6,7]，本文默认成人链末尾兜底。
3. 旧 30 张 SVG 与 18 张模板卡是否批量重画（API 69 逐词 ≈ $0.42）。
4. 是否把生成成本接入 `ai_calls`（美元账本）——本文判断不值一次 `ai_calls` 重建；若要统一「AI 花费」视图，留 P3。
5. 智谱国内站 vs Z.ai、是否实名、水印是否申请关闭——与 `docs/AI_FALLBACK_MODEL.md` §7 的同类问题一起定。

### 7.3 工作量

| 项 | 人日 |
|---|---|
| P1：SVG v2 + sanitize（0.75）、content 提示词/常量/文档（0.5）、照片链七项（1.0）、失败词重试（0.5）、文档数字与 DESIGN §9（0.25）、测试（0.5） | 3.5 |
| P2：适配器 + 提示词模板 + fake（1.5）、handler 接入/quota/style/配置（1.25）、迁移 0012 + 契约 + 前端 + 文案（1.25）、文档（DEPLOY/env/API/DESIGN/ATTRIBUTION/ops）（0.5）、测试与排练（1.0）、试点脚本（0.5） | 6.0 |
| 试点执行与评分汇总 | 1.0 |
| **合计** | **10.5**（P3 另计 6–10） |
