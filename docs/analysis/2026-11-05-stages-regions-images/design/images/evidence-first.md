# 配图更易记 · 设计（角度：证据优先）

基线：仓库 `/Users/sqin/word-dance` `main @ 75df534`（`git rev-parse --short HEAD` 实测），2026-11-05。线上库只读副本 `scratchpad/live-copy.db`（只用 `sqlite3 -readonly` / `?mode=ro`）。本文只做设计，不改任何仓库文件。

写法约定：每节先给结论，再给依据。`[slug-N]` 指 `facts/<slug>.md` 第 N 条，`[verify slug-N]` / `[verify slug 遗漏 k]` 指核验文件，`[INDEX Dn]` 指 `INDEX.md` 第 2.D 节；`path:line` 按 75df534，均由我重新打开核对。效应量只引用 INDEX/verify 已核验的数字（Yun 2011 按核验修正为 10 项研究 n = 1,560）。

---

## 1. 一页结论

### 1.1 决定了什么（按对 6–11 岁学习者的预期记忆收益排序）

| # | 决定 | 直接证据（对象年龄） | 效应量 / 方向 | 外推到 6–11 岁的置信 | 期 |
|---|---|---|---|---|---|
| D1 | **图里一个字都不能有**：SVG 提示词删掉「底部英文词」，`sanitize_svg.clean` 对 `claude_svg` 一律丢掉 `<text>/<tspan>`（代码保证，不靠提示词）；模板卡（印词头、音标、释义、例句）永远不当「提示」用 | Boers 2009 / 2017（成人）：配图分走对词形的注意，要求回忆词形时「无图注释反而更好」[image-memorability-8]；Adesope & Nesbit 2012 冗余原则（57 项研究）[12] | 方向一致、中等；儿童更易受无关信息干扰（Kaminski & Sloutsky 2013，6–8 岁，干扰随年龄减弱）[13] | 高（方向）/ 中（幅度） | 一 |
| D2 | **单一主体、去装饰、风格一致构图各异**：提示词硬约束 + 候选打分新信号（描述词、类目、人像/竖图降权） | Flack & Horst 2018（3.5 岁）：一次只看一幅插图学到**两倍**词 [13]；诱人细节元分析 g ≈ −0.33（58 项，>7,500 人，二手）[12]；Nelson 1976：候选图外观相似时图优效应消失甚至反转 [1] | 高（方向）/ 中（幅度） | 一 |
| D3 | **图默认出现在「回忆之后」作反馈；小学/初中用户可开「图作提示」——图先出现、学习者先回忆再翻面**（图是提示不是答案，所以必须先满足 D1） | Carpenter & Olson 2012（成人）：图造成过度自信，**只有配合提取练习**配图才优于译文 [6]；Tonzar 2009（四年级与八年级）：从图学词优于从词学词 [7]；Lotto & de Groot 1998（成人）：方向相反 [7]；Defeyter 2009：7 岁组限时条件下图优效应反转 [2] | 中 | 一（默认后置）/ 二（提示模式） |
| D4 | **画例句用到的那个义项，抽象词画与 `mnemonic_zh` 一致的「记忆挂钩」**：用户提示词带第 1 条例句与「联想：」句，内容提示词第 6/7 条改成「与例句 1 同一义项、单一主体、无文字无人脸」 | Lotto & de Groot 1998 的学/测一致性效应 [7]；Attygalle 2025：把关键词联想画成图显著提升保持（效应量未给）[11]；Pressley & Levin 1978（二手）：二年级只有在**提供**互动图像时受益 [10] | 中（直接实证缺失，见 INDEX 未解决 8） | 一 |
| D5 | **按词的 `stage_min` 决定风格**（小学/初中词 → 儿童绘本式扁平插画，其余 → 中性扁平或照片），**每词一张图，不做每用户多图** | Tonzar 2009 vs Lotto & de Groot 1998：儿童受益于图、成人不受益 [7]；de Groot & Keijzer 2000：具体性是最强预测量 [3] | 中；「成人看儿童插画会受损」无任何证据，故不值得为此改唯一索引 | 一 |
| D6 | **功能词 / 副词不配图**（`words.pos` 主词性 ∈ 介词、连词、限定词、代词、冠词、感叹词、副词 → 直接模板卡，不花配额、不花 SVG 预算） | 图优效应只对具体概念成立（Paivio 双重编码）[1]；具体性最强预测量 [3]；线上 `despite`/`particularly`/`directly`/`suddenly` 的 SVG 即反例 [16] | 高 | 一 |
| D7 | **照片链消歧 + 插画过滤 + 失败词自动重试**（搜索词只来自例句情境；Commons `filetype:drawing` + `thumbmime`、`maxlag`；Openverse `page_size` 20→10；`failed` 词在被学习或冷却结束后重抓） | 这是把 D2/D4 落到检索链；照片命中率从未被测量（49/49 任务失败，≥27 个因冷却未发请求）[verify images-pipeline-29] | — | 一 |
| D8 | **生成式位图只做可配置、默认关闭的试点**（智谱 `images/generations`，`cogview-3-flash` 免费），带显式 + 隐式标识与内容过滤兜底 | 价格与接口 [image-memorability-26]；标识义务 [verify image-memorability 遗漏 4] | — | 二 |
| D9 | **先测量再铺开**：200 个小学高频词、三臂对照（照片链 / 新提示词 SVG / CogView），双人评分表 + GLM-4.6V-Flash 自动评分写入新列 `word_images.eval_json`（不覆盖 `score`） | 多媒体注释总体效应 d = 0.46（Yun 2011，10 项研究，n = 1,560）[verify image-memorability-9] 说明「配图值得做」，但没有任何研究回答「卡通 vs 照片」「图与义项不一致」 | — | 二 |

### 1.2 为什么是这个顺序

- 线上的 31 张图里 30 张是 Claude SVG，**每张都在底部印着英文词**（`backend/wd/ai/prompts/svg_system.txt:1` 要求 "the English word in a <text> at the bottom"），模板卡印词头、音标、释义、例句（`backend/wd/images/card_svg.py:111-118`）——任何「图在回忆前出现」的玩法在改掉这一点之前都是泄露答案 [verify images-pipeline O6]。所以 D1 排第一，且必须是代码保证：4/34 次 SVG 被拒（11.8%，$0.0491 白花）都是 "not well-formed XML … column 224/226/402/410"（live-copy `jobs` 45/88/97/136），裸 `&` 是最可能的原因 [verify image-memorability 遗漏 1]，提示词再怎么写也不能保证模型不犯。
- 对小学生最强的两条直接证据（Flack & Horst 的「一图一主体」、Tonzar 的「儿童从图学词更好」）都指向**插画的构图**而不是**插画的来源**；所以先改构图规则（D2/D4/D5，零 key），再决定来源（D8 试点）。
- 「成人可不配图」有证据（Lotto & de Groot），「成人看到儿童插画会受损」没有证据——因此不为「同一词两张图」改 `ux_word_images_active`（`backend/wd/migrations/0001_init.sql:272`），省下一次数据模型改动。

### 1.3 代价多少

| 期 | 内容 | 人日 | 钱 |
|---|---|---|---|
| 一（本周可合并，无新 key） | 两份提示词重写 + 文档逐字同步；`sanitize_svg` 去文字 / 修裸 `&` / 加 `<desc>` 标识；`images/style.py`（按阶段风格、功能词跳过）；provider 风格参数（Commons drawing + `thumbmime` + `maxlag`、Openverse `page_size`、Pixabay `image_type`）；`select` 新信号；失败词重试（三处挂点）；附加列迁移 `0011_word_images_meta.sql`；文档数字 $0.028 → $0.0140、18 → 35 张/天 | ≈ 5 | 0 新增；SVG 单价不变（$0.0124/次），拒收率预期从 11.8% 降到 ≈ 0 |
| 二（需 key / 试点） | 生成位图适配器 + 配置 + 配额；`0012` 重建 `word_images` CHECK（provider 加 `gen`）；契约变更（`ImageProviderName`、`ImageMeta.text_free`、`Settings.image_hint`）；前端「图作提示」；XMP/`<desc>` 隐式标识；200 词试点脚本、评分表、VLM 评分 | ≈ 9 | 试点 ≈ $3（200 × SVG $0.0124 + 内容 20 次 × $0.04）；CogView-3-Flash 与 GLM-4.6V-Flash 免费 [4.3 节表] |
| 三（视评估） | 每词多图 / 候选选择、DPR 2 尺寸（`THUMB_WIDTH` 可配置）、复杂度启发式、Lancaster 常模门控、管理员词库页换图 | 3–6 | 全库任何一种来源 ≤ ¥911（Claude SVG）或 ¥0（CogView-3-Flash）[INDEX 4.3] |

---

## 2. 对照假设 A1–A6 的偏离与理由

| 假设 | 本设计的处理 | 偏离？ | 理由 |
|---|---|---|---|
| A1 小学 = 国家二级 505 词骨架 | 采用；试点样本框 = 505 转录件 ∩ 现库（我按 lemma 直接匹配得 497；INDEX [B2] 口径 500/505，差异是 `a/an`、`mr.`/`mrs.` 等书写差）| 否 | 试点只需一个稳定的样本框，不依赖 Q2 的最终拍板 |
| A2 初中/高中词表 | 不涉及 | 否 | 配图只读 `words.stage_min`，与词表来源无关 |
| A3 许可姿态 | 不涉及词表；配图许可白名单不变（`backend/wd/images/providers/base.py:184-205`） | 否 | — |
| A4 不按省份分层 | 风格由 `words.stage_min` 驱动，不由地区驱动；不做「上海/全国」双图 | 否 | 见 D5 |
| A5 先改提示词与抓取链，位图生成可配置、默认关闭 | 采用，**两处加码**：① 「无文字」除提示词外还在 `sanitize_svg` 里做硬规则；② 位图适配器按智谱 `POST /api/paas/v4/images/generations` 的形状写（与 OpenAI `images/generations` 请求/响应形状相近但路径不同 [image-memorability-26]），`WD_IMAGE_GEN_BASE_URL` 可配 | 轻微 | 提示词不能保证 XML 合法与无文字（线上 4 次拒收即证）；本机无任何国产 key，适配器只能对着官方文档写并留到试点验证 |
| A6 新用户默认 K-12；现有 2 用户迁移规则写死 | 新增用户设置 `image_hint`（第二期）：默认值由 `current_stage` 推出——主攻阶段 ∈ 儿童阶段集合（现为 `zk`，小学落地后为 `xs,zk`）→ 1，否则 0；线上两行：`user_id 1`（`current_stage 3`）→ 0，`user_id 2`（`current_stage 1`，`stages_json '["zk"]'`）→ 1（live-copy `user_settings` 实查）；`show_images` 两行均为 1 不动 | 否 | 与 A6 一致；规则写进迁移的 `UPDATE … CASE` |

另两处与 INDEX Q7 建议的差异，显式说明：
1. INDEX Q7-a 说「按词 `stage_min` 选风格（小学 → 插画链）」，本设计把**初中**也划入儿童风格集合：Tonzar 2009 的被试是四年级与八年级，两组都从图受益 [verify image-memorability-7]；初中生 12–15 岁更接近八年级组而不是成人组。集合做成配置 `WD_IMAGE_KID_STAGES`，默认 `zk`，小学落地后 `xs,zk`。
2. INDEX Q7-c 把「照片链加插画过滤 + 申请 key」作为 b 的对照组，本设计的对照组是**不需要新 key 的** Commons + Openverse（匿名）链：Pixabay 条款禁止「Systematic mass downloads」[verify images-pipeline O3]，Openverse 匿名 200/日 [verify images-pipeline O1]，两者都只适合按需抓；200 词试点在 Commons 2,000/日自限内一天可跑完（200 × ≤ 3 关键词 = ≤ 600 次）。Pixabay/Pexels key 是可选项，不是前置。

---

## 3. 详细设计

### 3.0 证据 → 准则 → 代码落点（总表）

| 准则（INDEX D1） | 证据与效应量 | 落点（第一期除非注明） |
|---|---|---|
| 单一清晰所指 | Flack & Horst 2018「一次一图学到两倍词」(3.5 岁) [13]；Nelson 1976 相似性反转 [1] | `svg_system.txt` 构图段；`content_system.txt` 第 6/7 条；`select.score` 人像/竖图降权（3.3.4） |
| 图中无文字 | Boers 2009/2017 [8]；Adesope & Nesbit 2012 冗余（57 项）[12] | `sanitize_svg.clean(allow_text=False)`（3.1.3）；模板卡不作提示（3.5） |
| 去无关细节 | 诱人细节 g ≈ −0.33（58 项，二手）[12]；Kaminski & Sloutsky 2013 [13] | 提示词「plain single-colour background, no clutter」；生成位图提示词的「不要」段（3.4） |
| 画例句用到的义项 | Lotto & de Groot 学/测一致 [7]（间接） | `svg.build_user_prompt` 带第 1 条例句；`content_system.txt` 第 6 条「与例句 1 同一义项」；搜索词只来自 `image_keywords`（3.3.1） |
| 抽象词用与 `mnemonic_zh` 对齐的挂钩 | 关键词法 [10]；Attygalle 2025 [11] | 用户提示词 `Memory hook:` 取 `mnemonic_zh` 中以「联想：」开头的句子（`content_system.txt:8` 已规定该前缀） |
| 风格一致、构图各异 | Nelson 1976 [1] | 固定 Style 段 + 「vary the composition」；VLM 评分的「与库内近似」项（第三期） |
| 图作提示而非答案 | Carpenter & Olson 2012 [6] | 默认翻面后出图（现状，`StudyCard.tsx:302-311`）；第二期 `image_hint` 只在 `ImageMeta.text_free` 时在正面出图（3.5） |
| 儿童 vs 成人差异化 | Tonzar 2009 / Lotto & de Groot 1998 [7] | `images/style.py:style_for()`（3.1.2） |
| 具体性门槛（宁可不配图） | [1] [3]；线上反例 [16] | `images/style.py:skip_image()`（3.3.1） |
| 高图标性 | Ganea 2008（婴幼儿，外推低）[14] | 提示词「clearly recognisable, not a symbol」；小学风格禁用象征（`sexual` → 蜜蜂传粉这类成人向象征不给小学词） |

数据支撑（live-copy，`python3 -I` 脚本 `scratchpad/design-images-evidence/pos_stats.py`）：`stage_min = 1` 的 2,099 词按 ECDICT `pos` 占比最高的代码分布为 n 1,043 / v 361 / j 301 / r 105 / 无 pos 100 / m 50 / i 40 / p 40 / d 22 / c 19 / a 11 / u 6；505 转录件在库 497 词为 n 233 / v 89 / j 73 / r 30 / i 19 / p 12 / d 12 / a 10 / c 7 / 无 5 / u 4 / m 2。即「不配图」规则（r/i/p/d/c/a/u）覆盖初中层 243 词（11.6%）、小学层 94 词（18.9%）；小学层 46.9% 是名词，这是插画最容易做对的部分。497 个小学词中仅 1 个有内容、0 个有图（live-copy），所以试点要先跑内容生成。

### 3.1 Claude SVG 路径

#### 3.1.1 提示词（`backend/wd/ai/prompts/svg_system.txt` 整体重写；`docs/CLAUDE_INTEGRATION.md:279-285` §5.5 代码块必须逐字同步，否则 `backend/tests/unit/test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5` 红）

建议正文（英文，多行；首字符为字母以满足 `test_schemas.py:127`）：

```
Produce a simple, flat-style educational illustration as a single SVG string for the given English word, so that a learner who sees the picture alone can recall the word. The picture is a memory cue, not a caption: it must contain NO text of any kind — no letters, digits, words, labels, signs, speech bubbles or captions — and must not spell or hint at the word typographically.
Composition: exactly ONE clearly recognisable central subject (or one simple interaction between two subjects when the Scene says so) on a plain, light, single-colour background; no decorative clutter, borders, frames or patterns; 3–5 harmonious flat colours and large simple shapes; the subject fills at least half of the canvas. Draw the Scene given in the user prompt — the sense used in the example sentence — never a different sense of the word. For an abstract word draw the concrete Memory hook given in the user prompt, not a symbolic diagram. Simple stylised figures are fine, but do not draw human faces in detail. Nothing frightening, violent, romantic or sexual.
Follow the Style paragraph of the user prompt (child-friendly or neutral adult) and vary the composition from picture to picture.
Technical constraints: viewBox="0 0 800 500"; use only these elements: svg g rect circle ellipse line polyline polygon path defs linearGradient radialGradient stop title desc; no <text>, no <tspan>, no <script>, no <foreignObject>, no <image>, no <use>, no external references (href, xlink:href, url(...)), no event attributes, no CSS; the SVG must be well-formed XML — write & as &amp; and never put a bare < or & inside attribute values, <title> or <desc>; total length at most 8000 characters. Return {svg, alt_zh} where alt_zh is one Chinese sentence (at most 40 characters) describing what the picture shows.
```

依据：每一句对应 3.0 表的一行；「&amp;」一句针对 4 次拒收 [verify image-memorability 遗漏 1]；「no <text>」与 3.1.3 的代码规则双保险。`svg_v1.json`（`backend/wd/ai/schemas/svg_v1.json:1`，`{svg, alt_zh}` 必填）不改。

用户提示词（`backend/wd/ai/svg.py:40-45 build_user_prompt` 与 `:48-52 prompt_for` 改签名）：

```
Draw an illustration for the word "{display}" ({meaning_zh ≤ 60}). Scene: {image_alt_zh ≤ 60}。 Example sentence: "{examples[0].en ≤ 120}" Memory hook: {mnemonic_zh 中以「联想：」开头的句子 ≤ 60，无则省略} Style: {STYLE_KID | STYLE_ADULT}
```

- `STYLE_KID = "child-friendly picture-book style for 6–12-year-olds: bright warm colours, rounded shapes, friendly simple characters, everyday school / home / playground scenes familiar to a child in China."`（「本土场景」一句是 INDEX D1 准则 6 的推断，无直接文献；试点评分表 R5 专门测它，见 3.6）
- `STYLE_ADULT = "neutral flat infographic style for teenagers and adults: calm colours, clean geometry, realistic proportions."`
- 两段都放在用户提示词里，因为一次调用只加载一份系统提示词且被 `lru_cache`（`backend/wd/ai/runner.py:100-103`，[ai-prompts-stages-2]），两种风格必须共存于一份系统提示词之下。
- 新常量：`svg.py` 加 `EXAMPLE_MAX = 120`、`HOOK_MAX = 60`、`SVG_PROMPT_VERSION = "svg-v2"`；`prompt_for` 改为 `prompt_for(conn, word, style)`，`style` 来自 3.1.2。
- `CLAUDE_INTEGRATION.md:285` 的用户提示词示例同步改；`:296` §6.1 表 `generate_svg` 行加「prompt_version 写入 `word_images.prompt_version`」。

#### 3.1.2 按阶段的风格：新模块 `backend/wd/images/style.py`

```python
STYLE_PHOTO = "photo"   # 成人：照片优先，SVG 用 STYLE_ADULT 段
STYLE_KID = "kid"       # 儿童：插画优先，SVG 用 STYLE_KID 段
FUNCTION_POS = frozenset({"i", "c", "d", "p", "a", "u", "r"})  # ECDICT pos 代码：介词 连词 限定词 代词 冠词 感叹词 副词（代码表以 ECDICT README 为准）

def kid_stage_indexes(cfg) -> frozenset[int]: ...   # cfg.image_kid_stages（阶段码）→ schemas.stage_to_index
def style_for(word_row, cfg) -> str: ...            # words.stage_min ∈ kid_stage_indexes → STYLE_KID，否则 STYLE_PHOTO（stage_min 为 NULL → STYLE_PHOTO）
def dominant_pos(pos: str | None) -> str | None: ... # 'n:4/v:96' → 'v'
def skip_image(word_row) -> bool: ...               # dominant_pos ∈ FUNCTION_POS
```

- 配置 `WD_IMAGE_KID_STAGES`（`backend/wd/config.py` 新字段 `image_kid_stages: tuple[str, ...] = ("zk",)`，`from_env` 用 `text()` 解析逗号列表并校验 ∈ `schemas.STAGE_ORDER`（`backend/wd/schemas.py:51`）；小学阶段落地后默认值改为 `("xs", "zk")`——与阶段模型设计的索引方案解耦，因为这里只认阶段码，索引由 `stage_to_index` 算（`schemas.py:56-61`）。
- 读取点：`svg.prompt_for`（需要 `words.word_row` 的 `stage_min`，该函数 SELECT 全列，`backend/wd/ai/svg.py:92`）；`handler.fetch_for_word` 的 SELECT（`backend/wd/images/handler.py:121-124`）加 `stage_min, pos`。
- 风格决定的是**链的顺序与参数**（3.3.2）和**SVG 的 Style 段**，不是数据模型：每词仍只有一张 `active` 图，`ux_word_images_active` 不动。

#### 3.1.3 `sanitize_svg` 三处改动（`backend/wd/images/sanitize_svg.py`）

1. **修裸 `&`**：`_parse`（`:65-79`）在 `DET.fromstring` 之前加 `text = BARE_AMP_RE.sub("&amp;", text)`，`BARE_AMP_RE = re.compile(r"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")`；修复次数记入返回值供 `svg.py` 写事件 `svg_repaired`（`system_events`）。这是对 4 次 "invalid token" 的直接修复，每次拒收白花 $0.0123（`jobs` 45/88/97/136 的 `cost_usd`，[verify images-pipeline-36]）。无法在本机读 `ai_calls.stdout_path` 验证根因（线上目录禁区），所以同时保留提示词的 `&amp;` 要求。
2. **去文字**：`clean(svg, *, allow_text: bool = True)`；`allow_text=False` 时 `_serialise`（`:137-166`）把 `text`、`tspan` 当作不在 `ALLOWED_ELEMENTS` 里处理（连同子树丢弃），`title`/`desc` 保留（它们不渲染）。`store.activate_svg`（`backend/wd/images/store.py:152-174`）对 `provider="claude_svg"` 传 `allow_text=False`。默认值保持 `True`，所以 `backend/tests/unit/test_sanitize_svg.py:158-168 test_text_content_and_structure_preserved` 不受影响。
3. **隐式标识**：新函数 `with_label(cleaned: str, label: str) -> str` 在根元素开标签之后插入 `<desc>{escape(label)}</desc>`（`desc` 在 `ALLOWED_ELEMENTS`，`:28-30`）；`label = f"AI-generated illustration · word-Dance · {model_used} · {now[:10]}"`。`activate_svg` 在 `clean` 之后、`write_bytes` 之前调用；`viewbox_size` 不受影响。这满足《标识办法》「文件元数据中添加隐式标识」对 SVG 文件的最小实现 [verify image-memorability 遗漏 4]；显式标识仍是 UI 题注「AI 生成示意图」（`frontend/src/i18n/zh.ts:54`）。GB 45438-2025 对元数据字段集的具体要求本轮没有读到原文（INDEX 未解决 9），字段名上线前核对。

`store.activate_svg` 新增参数 `model: str | None`、`prompt_version: str | None`，写入 3.1.5 的新列，并置 `text_free = 1`（去文字是代码保证）。

#### 3.1.4 旧卡处理

- 30 张旧 SVG（全部是四级词，`SELECT SUM(stage_cet4) … WHERE content_state='ready'` → 49/49 [verify ai-prompts-stages-10]）**不重画**：收益最低（成人、对成人的证据是「可不配图」），成本 $0.42；它们 `prompt_version IS NULL`、`text_free = 0`，第二期的「图作提示」自动把它们排除。管理员要重画可用现有 `POST /api/admin/words/{id}/refetch-image {provider:"claude_svg"}`（`backend/wd/routers/admin_ops.py:413-427`）。
- 18 个 `image_state='failed'` 词（15 个预取时「尚未被学」+ 3 个 SVG 被拒 `have`/`employee`/`property`，live-copy 实查）由 3.3.5 的重试规则覆盖：它们现在都在开放批次里 [images-pipeline-28]，下一次被标不熟悉/进入批次时自动重抓。
- 1 张照片（`election`）不动。

#### 3.1.5 数据：`0011_word_images_meta.sql`（纯附加，`ALTER TABLE ADD COLUMN`，与 `0010_ai_provider.sql:9-10` 同一先例）

```sql
ALTER TABLE word_images ADD COLUMN prompt_version TEXT;                       -- 'svg-v2' / 'gen-v1'；照片与旧卡 NULL
ALTER TABLE word_images ADD COLUMN model TEXT;                                -- 生成模型 id（claude-sonnet-5-5 / cogview-3-flash）
ALTER TABLE word_images ADD COLUMN text_free INTEGER NOT NULL DEFAULT 0 CHECK (text_free IN (0,1));  -- 1 = 代码保证无文字（可作正面提示）
ALTER TABLE word_images ADD COLUMN eval_json TEXT;                            -- 3.6.4 的 VLM/人工评分，不覆盖 score
```

- 编号：下一个空号是 0011（`backend/wd/db.py:41` 命名规则，[stage-model-21]）；阶段模型设计若先合入其 0011，本文件顺延为 0012，下文 `0012` 顺延为 `0013`。
- 不需要 `DROP VIEW`：`v_bank`（`0001_init.sql:572-576`）只引用 `user_words`、`words`。
- `docs/SCHEMA.sql` 不改（`backend/tests/unit/test_db.py:362-366` 要求与 0001 字节相同）。
- 老代码兼容：`service.active_image_row` 用 `SELECT wi.*`（`service.py:44-48`），`store.activate` 显式列名 INSERT（`store.py:105-113`），所以回滚代码不回滚迁移也能跑。

#### 3.1.6 成本预期

- 现状：34 次调用 $0.4207，$0.01237/次，30 张交付 $0.0140/张，4 次拒收 [verify image-memorability-17]；$0.50/日子额度 ≈ 35–40 张/天（0.50 ÷ 0.0140 ≈ 35；÷ 0.01237 ≈ 40）。
- 变化：输入侧多 ≈ 150 token（例句 + 挂钩 + Style 段），输出仍受 8000 字符约束，平均 829 输出 token 不会系统性增加；拒收率预期 → ≈ 0（`&` 修复 + 去文字减少 `<text>` 里的特殊字符），交付单价回到 ≈ $0.0124。
- 小学 505 词全部画 SVG ≈ $6.3，初中 2,099 词 ≈ $26；不做全库（`wd images-prune` 会删掉没人学的词的图，与全库预生成方向相抵 [verify images-pipeline O7]）。
- 文档里的 $0.028 与「≈18 张/天」改为 $0.0140/张（$0.0124/次）与「≈35 张/天」：`docs/DESIGN.md:28,518,550`、`docs/CLAUDE_INTEGRATION.md:407,416`、`docs/DEPLOY.md:326,434`、`docs/ops.md:198`、`deploy/env.example:83`。

### 3.2 content 生成侧

#### 3.2.1 `image_keywords` / `image_alt_zh` 的语义改写就够了吗？——第一期够，不加字段

结论：第一期**不**加 `image_scene_en`。理由：
- SVG 需要的「场景 + 例句 + 挂钩」三样信息内容里都已经有（`image_alt_zh`、`examples[0].en`、`mnemonic_zh`），只是 `svg.prompt_for` 没用后两样（`backend/wd/ai/svg.py:48-52` 只取 `image_alt_zh` 或 `meaning_zh`）[ai-prompts-stages-3]。
- 位图试点选智谱 CogView，中文提示词原生可用 [image-memorability-26]，`image_alt_zh` 直接可作生图提示；只有换英文系模型时才需要英文场景句，届时再评估。
- 加字段的代价是 10 处同一提交的机械改动 + `PROMPT_VERSION` 提升（清单见 3.2.4），不是架构风险，但本周不值得。

改写（`backend/wd/ai/prompts/content_system.txt:9-10`，§5.1 代码块 `docs/CLAUDE_INTEGRATION.md:219-220` 逐字同步）：

- 第 6 条：`image_keywords: 2–4 short English search phrases (2–4 words each) that all name the SAME concrete scene as example sentence 1 — one visible subject plus its setting, e.g. "abandoned car snow", "car left on road". Most literal first. No people's names or brands; avoid text-heavy scenes (signs, screens, documents), close-up faces and anything unsuitable for children. For a function word, or an abstract word with no natural scene, give the lemma alone.`
- 第 7 条：`image_alt_zh: one Chinese sentence (at most 30 characters) describing the ideal picture as ONE subject doing one thing in one place, in the sense of example sentence 1; the picture contains no text and no close-up face; for an abstract word describe the concrete memory hook that matches mnemonic_zh (an image, never a symbolic explanation).`

后验证不变：形状 `KEYWORD_RE`（`backend/wd/ai/content.py:61`）、黑名单（`:176`）、`ALT_MAX = 60`（`:62`）都容得下新写法。`content_v1.json:9-10` 的 `description` 是 schema 文件的一部分，**不改**（改了要三方逐字同步 `docs/CLAUDE_INTEGRATION.md:146-160` 与 `backend/tests/fixtures/claude_schemas.json`，[verify ai-prompts-stages 遗漏 2]）；描述文本与提示词略有出入不影响生成。

#### 3.2.2 小学例句规则（提示词层 + 一个常量）

- `content_system.txt:6` 第 3 条追加：`If a word's stages include 小学: 4–8 words each, present tense, everyday school / home / playground situations, only vocabulary a 10-year-old knows, and use the headword in its base form in at least two sentences. If the highest stage is 初中: 6–12 words, school and daily life, no workplace or news register.` 阶段标签已经逐词进入提示词（`content.py:88` `"stages": [STAGE_ZH[s] …]`，[ai-prompts-stages-1]），一份系统提示词按标签分条规则即可；「小学」标签要等阶段模型给 `content.STAGE_ZH`（`content.py:49`）加 `"xs": "小学"` 后才会出现，在此之前规则是空操作，初中部分立即生效。
- 第 1 条追加：`For words whose stages include 小学, write meaning_zh in plain words a 10-year-old understands (keep the POS labels).`
- 第 5 条追加：`For 小学 words prefer a vivid picture-like association ("联想：…") over morphology.`——这正是 3.1.1 的 Memory hook 来源。
- `EXAMPLE_EN_MIN` 15 → 10（`content.py:54`）；同步 `docs/CLAUDE_INTEGRATION.md:355` §6.4「`en` 15–240 chars」→「10–240」，`docs/AI_FALLBACK_MODEL.md:29` 的「15–240 字符」。依据：「I like cats.」12 字符会被 `:153` 丢掉，4 条里丢 2 条就整条重试 [ai-prompts-stages-5]。`scripts/eval_provider.py:1067` 引用常量，自动跟随。
- `PREFIX_MIN = 4`（`content.py:63`）**不动**：260 个无屈折行的 zk 词几乎全是功能词 [verify ai-prompts-stages-11]，而功能词按 D6 不配图、例句规则又要求用原形；放宽前缀会放进假阳性。
- `PROMPT_VERSION` → `"content-v2"`（`content.py:46`）：提升不会让任何 ready 词重新入队（`bank.py:489-492`、`prewarm.py:48`，[ai-prompts-stages-10]），只是让新旧卡可区分；`force` 重生成仍走旧路径。同步 `docs/CLAUDE_INTEGRATION.md:206` 与 `docs/WORD_LIBRARY_CURATION.md:65` 里的 `content-v1` 字样，`backend/tests/unit/test_content_apply.py:81` 的断言 `stored["prompt_version"] == "content-v1"` 改。

#### 3.2.3 不重生成旧卡

49 张旧卡（全是四级词）不 `force`；`docs/WORD_LIBRARY_CURATION.md:115` 已写明全库刷新只能逐词 force。

#### 3.2.4 若试点证明需要 `image_scene_en`（第二期备选）——10 处同一提交

1. `backend/wd/ai/schemas/content_v1.json:9-12`：`properties` 加 `"image_scene_en":{"type":"string","description":"…"}`，`required` 加入；
2. `docs/CLAUDE_INTEGRATION.md:146-160` §4.1 代码块逐字节同步，`backend/tests/fixtures/claude_schemas.json["content_v1"]` 同步（`backend/tests/unit/test_schemas.py:55-62`）；
3. `backend/wd/ai/prompts/content_system.txt` 加规则，§5.1 同步；
4. `backend/wd/ai/models.py:34-44 ContentItem` 加字段（否则 `extra="ignore"` 在 `valid_items` 阶段静默丢掉，[ai-prompts-stages-13]）；
5. `backend/wd/ai/content.py:131-203 validate_item`：清洗 + 写进 `:189-201` 的 cleaned 字典；新常量 `SCENE_EN_MAX = 160`；
6. `backend/wd/schemas.py:549-563 Content`：`image_scene_en: str | None = None`（`Model` 是 `extra="forbid"`，`schemas.py:87-90`，旧 49 条 `content_json` 无此键必须 Optional）；
7. `frontend/src/api/types.ts:70-75 Content`：`image_scene_en?: string | null`；
8. `docs/API.md:304-308` §9 `Content` + §9.1 说明；
9. 夹具与测试：`backend/tests/fixtures/claude_content_ok.json` 10 条加键、`backend/tests/fake_claude.py:170-199 content_item` 加键、`backend/tests/unit/test_content_apply.py:80` 键集合、`backend/tests/unit/test_claude_fixtures.py:58-67`、`scripts/eval_provider.py:115 CONTENT_ITEM_KEYS`；
10. `scripts/check_contract.py` 会比对 `Content` 的属性名（`:260-270` 的接口循环），两边同提交。

### 3.3 照片 / 插画抓取链

#### 3.3.1 搜索词的消歧与构造（`backend/wd/images/handler.py:134-137`）

今天：管理员 `query` → `image_keywords[:3]` → 裸 `lemma`，不消歧 [images-pipeline-1]。改为：

1. 管理员 `query`：不变（含中文/数字时仍静默回退——补一条 `log.info(event="query_dropped")`，不改 API）。
2. 有内容：`image_keywords[:MAX_KEYWORDS]`——消歧由 3.2.1 的提示词完成（三个短语都描述例句 1 的同一场景）。`MAX_KEYWORDS = 3` 不变（每个关键词是一次 provider 请求；线上 49 条内容无一有第 4 个关键词 [verify images-pipeline-2]）。
3. 无内容：**不再搜裸 lemma**，除非 `dominant_pos` 不在 `FUNCTION_POS` 且 `kind == 'word'`（`have`、`despite` 一类不再搜出随机照片 [verify images-pipeline O8]）。
4. 功能词（`style.skip_image()` 为真）且没有管理员 `query`/`provider`：直接 `store.set_image_state(conn, word_id, "failed")` 并返回 `FetchOutcome(STATUS_SKIPPED, detail="function word: card only")`，不消耗配额，不入队 SVG。管理员 `refetch-image` 带 `query` 或 `provider` 可绕过。

#### 3.3.2 provider 的风格参数与链顺序

接口：`interfaces.ImageProvider.search(self, query, limit, *, style: str = "photo")`（`backend/wd/interfaces.py:73-79`；关键字参数带默认值，四个实现与 `test_providers.py` 的现有调用不变）。`handler.fetch_for_word` 按 `style_for(word)` 决定链与参数：

| provider | `style="photo"`（现状） | `style="kid"`（插画优先） | 条款 / 限额约束 |
|---|---|---|---|
| wikimedia（`providers/wikimedia.py:40-51`） | `gsrsearch="{q} filetype:bitmap"` | `gsrsearch="{q} filetype:drawing"`，`iiprop` 加 `thumbmime`，候选 `mime` 优先取 `thumbmime`（`:97`）——Commons 把 SVG 光栅化为 PNG `thumburl`，原 `mime=image/svg+xml` 会被 `select.py:65-66` 拒 [verify images-pipeline-31]；找不到再退回 `filetype:bitmap` | 无硬性日配额，自限 1 req/s、2,000/日（`config.py:161-162`）；**加 `maxlag=5`**（API 礼仪，[images-pipeline-46]）：Commons 对 maxlag 以 HTTP 200 + `error.code == "maxlag"` + `Retry-After` 应答，`base.get_json`（`providers/base.py:100-118`）要能返回响应头——加 `get_json(..., return_headers=True)`，`wikimedia.search` 据此抛 `ProviderError(status=503, retry_after_s=…)` 走现有冷却 |
| openverse（`providers/openverse.py:41-42`） | `page_size` 20 → `max(1, min(limit, 20))` = 10（每次匿名配额只用一半结果 [verify images-pipeline O2]） | 加 `category=illustration`；尺寸门槛不放宽（实时查询前三条 CC0 剪贴画 350×400 / 319×338 / 210×210 [verify image-memorability 遗漏 5]，放大后模糊；接受命中更低，由试点量化） | 匿名 20/min、200/day（响应头实测，[verify images-pipeline O1]），项目自限 15/160；`priority ≥ 90` 跳过（`handler.py:158-159`） |
| pixabay（`providers/pixabay.py:30-39`，需 key） | `image_type=photo` | `image_type=illustration`（`vector` 另起一次搜索太费配额，不做） | 100 次/60 s；「Systematic mass downloads are not allowed」→ 只对被学习的词按需抓，**把 `handler.py:158` 的 `priority ≥ 90` 跳过扩展到 pixabay/pexels** |
| pexels（`providers/pexels.py:29-30`，需 key） | 不变 | 无插画类型 → kid 风格下排在最后 | 200/h、20,000/月；许可页 403 未核 [verify images-pipeline-43] |

链顺序：`style="kid"` → `wikimedia(drawing) → openverse(illustration) → pixabay(illustration) → wikimedia(bitmap) → openverse → …`，实现为 `handler` 里两轮 `names` 列表，不改 `WD_IMAGE_PROVIDERS` 的含义（`config.py:355-369`）。

#### 3.3.3 失败词自动重试（`backend/wd/images/service.py` 新函数 + 三处挂点）

```python
RETRY_MIN_AGE = timedelta(days=1)
def last_fetch_at(conn, word_id) -> str | None:
    # SELECT MAX(COALESCE(finished_at, updated_at)) FROM jobs WHERE type='fetch_image' AND (dedupe_key = 'image:<id>' OR dedupe_key LIKE 'image:<id>:r%')
def retry_if_failed(conn, word, *, priority, now) -> int | None:
    # image_state == 'failed' 且无 live 'image:<id>' 任务（queue.live_job）且 last_fetch_at 早于 now - RETRY_MIN_AGE → enqueue_fetch(conn, word_id, priority=priority, now=now)
def retry_failed_once(conn, cfg, now, *, limit=50) -> int:
    # 03:30 维护：image_state='failed' AND word_is_studied(...) AND 上次抓图 > 1 天 AND 任一 provider 不在冷却 → priority 30，最多 limit 个
```

挂点：
- `backend/wd/services/bank.py:636` 与 `:659`（`_apply_unfamiliar` 两条 `enqueue_content_if_needed` 之后）：`images.retry_if_failed(conn, word, priority=CONTENT_PRIORITY_BANK, now=now)`；
- `backend/wd/services/batches.py:352-356 _enqueue_content_for` 的行循环与 `:632 append_to_today`：同上，优先级 `CONTENT_PRIORITY_BATCH`；
- `backend/wd/jobs/scheduler.py:365-397 maintenance`：`prefetch` 之后调用 `images.retry_failed_once`。

依据：`fetch_image` 只有两类入队点，`failed` 词永远不再被抓 [images-pipeline-25]；11-03 的 30 个任务有 26 个因冷却连请求都没发 [verify images-pipeline O9]，所以触发条件必须含「冷却结束后重跑」，不能只靠「被学习时」。`images.__init__` 导出两个新函数。

#### 3.3.4 候选打分新信号（`backend/wd/images/select.py`）

无新依赖、第一期：
- `score(cand, keyword, *, used_refs=(), style="photo")`：
  - `description` / `object_name` 纳入命中 haystack（`:83` 只有 `title + tags`；`:72` 拒绝用了 description 却不加分 [images-pipeline-11]），封顶仍 +3；
  - Openverse `category`（`openverse.py:114-119 extra` 加 `"category": r.get("category")`）与 Pixabay `extra["type"]`（`pixabay.py:78` 已存）：与 `style` 匹配 +1、相反 −1；
  - 人像/人脸文字信号：`title/tags/categories` 命中 `\b(portrait|portraits|selfie|headshot|face|faces|people|person|man|woman|boy|girl)\b` → `style="kid"` 时 −2（D2「去无关细节」+ 隐私审慎；Pixabay/Pexels 条款都限制「可识别真人不得负面呈现」[images-pipeline-43]）；
  - 竖图：`aspect < 1.0` → −2（前端 16:10 `cover` 裁掉约 60% [images-pipeline-15]）；
  - 文字类软惩罚：`\b(sign|signs|signage|typography|inscription|banner|label|labels)\b` −2（`text/poster/document` 已在硬黑名单）。
- 黑名单修正：`BLOCKLIST_RE`（`:20-24`）拆成 `UNSAFE_RE`（`nude|nudity|sex|porn|gore|blood|weapon|gun|corpse`，永远硬拒）与 `NON_PHOTO_RE`（`map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document`），后者在**候选词条的 lemma 正是该词**时不拒（`reject_reason(cand, exclude, *, lemma=None)`）：`map` 在国家二级 505 词里（转录件第 258 行），`flag`/`cover`/`sign`/`text` 都是 `stage_min = 1` 的词（live-copy 实查），否则这些小学词永远拿不到一张真正的地图/旗帜照片。`is_blocked()` 对 Claude `image_keywords` 的过滤（`content.py:176`、`handler.py:71`）保持用合并后的全表，行为不变。
- 儿童安全硬拒（`style="kid"`）：`\b(beer|wine|alcohol|cigarette|smoking|horror|zombie|skull|knife|bikini|lingerie)\b`——现有安全控制只有 Openverse `mature=false`、Pixabay `safesearch=true`、Commons/Pexels 的 `mature` 为硬编码 False [verify ai-prompts-stages 遗漏 3]。
- 第二期（下载后）：复杂度启发式——`fetch.normalise_image` 顺带算 64×64 缩略图的唯一颜色数与边缘比，`style="kid"` 且超过阈值 → 跳到下一候选（文件已落盘，由 `images-prune` 回收）。阈值靠试点标定，没有数据前不进第一期。

#### 3.3.5 限额与条款小结（全库 9,162 词口径，来自 INDEX 4.3）

Commons 全库 1–3 关键词 4.6–13.7 天；Openverse 匿名 57–172 天（注册应用 10,000/日 → 1–3 天）；Pixabay 禁止系统性批量下载、Pexels 月配额 46%——因此**任何「全库预抓」都只用 Commons**，其余三家只对「正在被学」的词（`word_is_studied`，`service.py:223-234`）按需抓，和 SVG 的触发条件一致。

### 3.4 生成式位图 provider（第二期试点，默认关闭）

#### 3.4.1 为什么是智谱 CogView-3-Flash，为什么默认关

免费（模型概览页「免费模型」）、境内可达、`POST https://open.bigmodel.cn/api/paas/v4/images/generations` 返回 `data[].url`（30 天有效）与 `content_filter` 等级、`watermark_enabled` 默认 `true` 且关水印需签免责声明 [image-memorability-26] [verify images-pipeline-37]。本机没有任何国产 key，适配器只能对着文档写，所以默认 `WD_IMAGE_GEN_KIND=none`，并且**只在显式请求下生成**（`WD_IMAGE_GEN_POSITION=only_requested`），试点通过后才可改为 `before_svg`（kid 风格下排在 SVG 之前）。

#### 3.4.2 配置（`backend/wd/config.py` 新字段，`deploy/env.example` 与 `docs/DEPLOY.md §4` 镜像）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WD_IMAGE_GEN_KIND` | `none` | `none` / `openai_images`（请求 `{model, prompt, size, n:1, …}`，响应 `data[0].url` 或 `data[0].b64_json`；智谱、火山方舟 `…/api/v3/images/generations` 都是这个形状 [image-memorability-28]） |
| `WD_IMAGE_GEN_BASE_URL` | 空 | 如 `https://open.bigmodel.cn/api/paas/v4`；拼 `/images/generations`；校验同 `WD_AI_FALLBACK_BASE_URL`（`config.py:379-388`） |
| `WD_IMAGE_GEN_MODEL` | 空 | `cogview-3-flash`（免费）/ `cogview-4`（¥0.06） |
| `WD_IMAGE_GEN_API_KEY` / `_FILE` | 空 | 同 `WD_AI_FALLBACK_API_KEY[_FILE]` 的文件模式检查（`config.py:389-401`） |
| `WD_IMAGE_GEN_SIZE` | `1344x768` | 16:10 盒子 `cover` 只裁 ≈ 9%；智谱枚举含 1344×768 [image-memorability-26] |
| `WD_IMAGE_GEN_STAGES` | `zk`（小学落地后 `xs,zk`） | 只有这些阶段的词可生成（与 `WD_IMAGE_KID_STAGES` 同码表） |
| `WD_IMAGE_GEN_POSITION` | `only_requested` | `only_requested` / `before_svg` / `after_svg` |
| `WD_IMAGE_GEN_MINUTE_LIMIT` / `_DAILY_LIMIT` | `5` / `50` | 进 `quota.limits_for("gen")`（`backend/wd/images/quota.py:37-47` 加分支），计数走现有 `provider_usage` / `provider_state` |
| `WD_IMAGE_GEN_WATERMARK` | `1` | 只允许 `1`：`0` 需签免责声明，配置校验直接拒绝（`ConfigError`） |

配置好时 `image_providers` 元组追加 `"gen"`（`config.py:366-369` 的 keyed-provider 先例），于是 `quota.status`（`quota.py:160-179`）与管理概览 `images.providers` 自动显示它的配额行。

#### 3.4.3 适配器 `backend/wd/images/providers/generate.py`

```python
class GenerativeProvider:            # 不是 ImageProvider（没有 search）；PROVIDER_CLASSES 不收它
    name = "gen"
    def generate(self, prompt: str, *, size: str, user_ref: str) -> Generated   # Generated(url|None, data|None, content_filter: int|None, model: str)
```

- 请求：`POST {base_url}/images/generations`，`Authorization: Bearer <key>`，`{"model", "prompt", "size", "n": 1, "watermark_enabled": true, "user_id": sha256(word_id)[:16]}`；OpenAI 形状多出的键智谱会忽略，不认识的键按文档只读 `model/prompt/size/quality/watermark_enabled/user_id`。超时 60 s，不重试（免费模型限流未知，文档指向需登录页 [images-pipeline-37]）。
- 响应：`data[0].url` → 走 `fetch.safe_download`（https、443、公网 IP、`image/*`、魔数，`backend/wd/images/fetch.py:194-237`）——智谱文件主机名本机无法核实，**试点第一件事就是看这个 URL 能否过 SSRF 规则**；`b64_json` → 新函数 `fetch.store_bytes(data, cfg, *, label)` 直接 `normalise_image`。`content_filter` 任一级别 ≥ 1 → 不下载，事件 `gen_filtered`，回落到 SVG/模板卡；同一词不重试。
- 提示词（中文，CogView 原生中文）：`f"{STYLE_ZH}。画面中只有一个主体：{image_alt_zh}。与句子「{example_en}」的情境一致。{hook}。整张图没有任何文字、字母、数字、标志或水印以外的符号；纯色浅背景；不画人脸特写；不出现任何恐怖、暴力、亲密内容。"`，`STYLE_ZH = "儿童绘本风格扁平插画，明亮温暖的颜色，圆润的形状，中国小学生熟悉的校园、家庭和操场场景"`。智谱接口无 `negative_prompt`，「不要」只能写进正文 [image-memorability-26]。
- 落库：绕过 `select.rank`（`generated` 许可被 `base.license_allowed` 归为 `other` 硬拒 [images-pipeline-37]），直接 `store.activate(conn, word_id, provider="gen", license="generated", source_url=url, title=None, creator=None, attribution_text=None, alt_zh=image_alt_zh, mime="image/jpeg", prompt_version="gen-v1", model=cfg.image_gen_model, text_free=0, …)`。`text_free` 先 0：位图无法由代码保证无文字，3.6.4 的 VLM 评分「`text_present == 0`」才把它置 1。
- `fetch_for_word` 分支：`provider == "gen"`（管理员/CLI 显式）或 `WD_IMAGE_GEN_POSITION != only_requested` 且 `style == kid` 且 `stage_min ∈ WD_IMAGE_GEN_STAGES` 时在相应位置调用；不新增 job 类型（`jobs.type` CHECK `0001_init.sql:487`、`registry.JOB_TYPES` `backend/wd/jobs/registry.py:30-39`、`queue.IO_TYPES` `backend/wd/jobs/queue.py:33` 都不动），HTTP 调用在 IoWorker 单线程内同步完成。

#### 3.4.4 数据与契约

- `0012_word_images_provider_gen.sql`：重建 `word_images`（CHECK 不能原地改，[stage-model-11]）——`CREATE TABLE word_images_new (…provider CHECK (provider IN ('wikimedia','openverse','pixabay','pexels','claude_svg','gen'))…)` 含 0011 的四列；`INSERT INTO word_images_new SELECT * FROM word_images`（列序一致、显式列名更稳）；`DROP TABLE word_images; ALTER TABLE word_images_new RENAME TO word_images;` 重建 `ix_word_images_word`、`ix_word_images_sha`、`ux_word_images_active`（`0001_init.sql:270-272`）。`word_images` 没有子表、没有视图引用、没有触发器（`grep TRIGGER` 为空），`words.active_image_id` 是逻辑外键（`0001_init.sql:199`，注释 "logical FK → word_images.id"），id 保留即可。运行器的 `PRAGMA foreign_keys=OFF` 包裹与 `foreign_key_check` 已有（`backend/wd/db.py:222-246`）。
- `backend/wd/schemas.py:46 ImageProviderName` 加 `"gen"`；`:1349-1351 RefetchImageRequest.provider` Literal 加 `"gen"`；`frontend/src/api/types.ts:84` 同步；`frontend/src/api/endpoints.ts:340 RefetchProvider` 同步；`docs/API.md:231`（端点 69）与 `:314-321`（`ImageMeta`）同步；`scripts/check_contract.py:274-281` 的字面量联合比对（`:280 if py_values != values`）要求两边同提交。
- `service.image_meta`（`service.py:51-80`）：`is_generated = provider in ("claude_svg", "gen")` → `attribution=None`；`kind` 对 `gen` 返回 `"photo"`（位图用 `cover` 渲染，`study.css:456-467` 按 `kind` 选 `cover/contain`）。
- `service.photo_mix`（`:237-246`）：`with_photo` 的 SQL 明列四家照片源，`gen` 自动不算照片；把 `gen` 计入 `with_claude_svg`（标签「AI 示意图」，`zh.ts:92`），**不改** `AdminOverviewWords` 契约（`schemas.py:1094`、`types.ts:185`、`backend/tests/unit/test_api_schemas.py:113`）；试点规模（≤ 200 张）不值得一次契约变更，第三期再拆 `with_generated`。
- 前端题注：`frontend/src/components/study/WordImage.tsx:28` 改为 `if (image.kind === 'svg' || image.provider === 'claude_svg' || image.provider === 'gen') return zh.word.aiImage;`——复用「AI 生成示意图」，`zh.ts` 零改动（`docs/FRONTEND.md:87` 的 WordImage 行补一句）。
- `ai_calls.kind` CHECK（`0001_init.sql:511`、`backend/wd/ai/ledger.py:20 KINDS`）**不动**：生成调用不进 AI 账本、不占 `WD_AI_*` 美元预算（免费模型；付费模型的人民币计费属第三期，届时再决定是加 `kind='image'` 还是独立表）。配额与冷却走 `provider_usage`/`provider_state`，和照片 provider 一样。

#### 3.4.5 标识合规（《人工智能生成合成内容标识办法》2025-09-01 施行，[verify image-memorability 遗漏 4]）

- 显式标识：① 厂商水印默认开（`watermark_enabled=true`，配置禁止关）；② UI 题注「AI 生成示意图」（`zh.ts:54`）；③ `ATTRIBUTION.md §3.4`（`ATTRIBUTION.md:54-59`）加 `gen` 一行；④ 设置页「关于与数据来源」文案 `zh.settings.sources.images`（`zh.ts:86`）已含「AI 生成示意图」，不改。
- 隐式标识（文件元数据）：
  - JPEG：`fetch.normalise_image(data, max_edge, *, label: AigcLabel | None = None)`，`label` 非空时在 `img.save(...)`（`fetch.py:267`）加 `xmp=…`（Pillow 12.3.0 的 `JpegImagePlugin.py:762` 支持写 XMP，本机 `.venv` 实查）与 `comment=b"AI-generated image"`；XMP 包含 `aigc:generated=true`、`aigc:provider`、`aigc:model`、`aigc:producer=word-Dance`、`aigc:contentId=<sha256 前 16 位>`、`aigc:createdAt`。照片路径 `label=None` 维持现有「去 EXIF/ICC」行为（`fetch.py:9-11`）。
  - SVG：3.1.3 的 `<desc>`。
  - 字段名与 GB 45438-2025 的对应关系本轮无法核实（标准原文未读，INDEX 未解决 9）——列为上线前核对项；本应用是「生成合成服务提供者」还是「内容传播服务提供者」也未定性（INDEX 未解决 9）。
- 智谱用户协议：不得篡改/消除其显式、隐式标识 [image-memorability-26]——我们的重编码（`normalise_image` → JPEG q82）会**丢掉智谱的隐式数字水印**（显式水印在像素里保留）。这正是要在重编码后补写自己 XMP 的原因；是否构成「消除隐式标识」需要法务判断，列入风险。

#### 3.4.6 内容过滤与成本控制

- `content_filter` ≥ 1 → 拒；拒绝率在学校词表上未知（库里有 `weapon`、`sexual`、`blood` 等 [images-pipeline 未解决 5]）——试点记录 `gen_filtered` 事件数。
- 每日 50、每分钟 5（可配）；IoWorker 单线程天然并发 1；URL 30 天内必须下载（立即下载）。
- 与 `photo_mix` / 日预算的关系：不进美元预算；管理概览 `images.providers` 多一行 `gen`；`svg_today_usd` 不受影响。

### 3.5 展示与数据模型

#### 3.5.1 图在回忆前还是回忆后——决定与依据

**决定**：
1. 默认（所有用户）：图在翻面之后作反馈——即现状（`frontend/src/components/study/StudyCard.tsx:302-311` 只在 `study-card__back` 渲染 `WordImage`，正面 `:201-228` 无图）。依据：Carpenter & Olson 2012——图先于回忆出现造成过度自信、抵消收益 [6]；Boers 2009/2017——拼写/词形任务不要同屏出图 [8]。
2. 第二期新增用户设置 `image_hint`（布尔）：开启时正面**直接**显示图（而不是只在按 H 时），学习者看图回忆英文再翻面；只对 `ImageMeta.text_free === true` 的图生效，否则退回现有的例句挖空提示（`StudyCard.tsx:202,208-212`）。默认值由主攻阶段推出（A6，2 节表）。依据：Tonzar 2009「picture-based method」对四年级/八年级更好 [7]——该方法正是「看图学词」；配合「必须先回忆再翻面」满足 Carpenter & Olson 的提取练习条件；Defeyter 2009 提醒 7 岁以下在限时条件下图优效应反转 [2]——所以正面出图不设任何计时，且小学一二年级（无词表的预备级）不在目标用户内。
3. 模板卡永远不作正面提示（印着词头，`card_svg.py:111`）。

契约改动（第二期）：`ImageMeta` 加 `text_free: boolean`（`schemas.py:576-585`、`types.ts:80-87`、`docs/API.md:314-321` 与 `:465`），`service.image_meta`/`card_meta`（`service.py:29-41,51-80`）与 `services/words.card_image_meta`（`backend/wd/services/words.py:455-467`）同步；`Settings` 加 `image_hint: boolean`（`schemas.py:156-175` 与 `:376-392 SettingsUpdateRequest`、`backend/wd/security.py:586-606 settings_row_to_dto`、`security.SETTINGS_BOOL_COLUMNS`、`backend/wd/routers/settings.py:80-122`、`types.ts:34-43`、`docs/API.md` 端点 14/15 与 §9 `Settings`）；列 `user_settings.image_hint INTEGER NOT NULL DEFAULT 0 CHECK (image_hint IN (0,1))` 用 `ALTER TABLE ADD COLUMN`（附加，放进 `0012`），再 `UPDATE user_settings SET image_hint = CASE WHEN current_stage IN (<儿童阶段索引>) THEN 1 ELSE 0 END`——索引值取决于阶段模型设计的 Q1 结论，迁移文件里写当时成立的常量并注释来源。注册默认值：`routers/onboarding.py` 按角色写（`zk` 角色 → 1）。前端：`StudyCard` 新 prop `imageHint`，`StudyPage.tsx:635,695` 传 `settings?.image_hint`，`SettingsPage.tsx:413` 旁加开关，`zh.ts` 加 `settings.imageHint: '先看图再回忆（适合小学生）'` 并同步 `docs/FRONTEND.md §8`（`frontend/src/i18n/zh.test.ts` 钉两块相同）。

#### 3.5.2 每词多图？——否

同一词「给小学生插画、给高中生照片」要改 `ux_word_images_active`（`0001_init.sql:272`）、`words.active_image_id` 语义、`ImageMeta` 按用户阶段选图、`photo_mix`、`exclude_for`——代价大 [images-pipeline-33]，而收益没有证据（1.2 节）。风格由词决定、一词一图；第三期若评估显示成人对儿童插画有明确负面反馈（`content_reports` 的 `inappropriate_image`/`irrelevant_image` 计数，现为 0 [images-pipeline-27]），再加 `word_images.audience` 列与 `(word_id, audience)` 部分唯一索引。

#### 3.5.3 `show_images` 开关粒度

保持全局布尔（`user_settings.show_images`，`0001_init.sql:149`）；新增的 `image_hint` 是第二个布尔，不做三态枚举（枚举要同时改 `Settings` Literal、前端 Switch 组件与文案，收益不大）。拼写/听写模式目前不存在，不需要按模式关图。

#### 3.5.4 清晰度（第三期）

`WD_IMAGE_MAX_EDGE` 800 → 1200 且 `wikimedia.THUMB_WIDTH`（`providers/wikimedia.py:27`）改为跟随配置、`pexels.py:46` 取 `large2x` [verify images-pipeline O10]；磁盘 ×2–3；SVG 与位图生成不受影响（矢量 / 1344 px）。

### 3.6 评估：200 个小学高频词的试点

#### 3.6.1 样本

- 样本框：505 转录件 ∩ 现库（497 词）去掉功能词（94）→ ≈ 403 词；分层：名词 120、动词 50、形容词 30（`words.pos` 主代码），每层按 `frq` 升序等距抽样（`frq` 已知 492 词、中位数 596）。SQL 骨架：`SELECT lemma, pos, frq FROM words WHERE lemma IN (<505 词>) AND stage_min = 1 ORDER BY frq`，分层在脚本里做。
- 这 200 词只有 1 个有内容：试点先用 `POST /api/admin/content/prewarm`（`stage=zk, limit=…` 覆盖不到小学集合）之外的办法——对指定词逐个 `POST /api/admin/words/{id}/regenerate`（`routers/admin_ops.py:392-411`，`:405` 入队 `{"word_id", "force": True}`，priority 10）或新 CLI `wd prewarm --lemmas <file>`（`docs/WORD_LIBRARY_CURATION.md` 阶段 C 已提议）；成本 ≈ 20 次 × $0.04 = $0.8（Claude）或 0（备选 GLM 免费）。

#### 3.6.2 三臂（+1 可选）

| 臂 | 命令（在出口正常的机器、线上库的**私有拷贝**上） | 配额/成本 |
|---|---|---|
| A 照片链（新查询词、kid 风格的 Commons drawing → bitmap、Openverse illustration） | `wd fetch-image <lemma> --no-svg` × 200 | Commons ≤ 600 次（1 天内）；Openverse 匿名 160/日 → 分 2–4 天或注册应用 |
| B 新提示词 Claude SVG | `wd fetch-image <lemma> --provider claude_svg` × 200（`handler.py:139-146` 入队 `generate_svg`，需 worker 排空） | 200 × $0.0124 ≈ $2.5；子额度 $0.50/日 → 调高 `WD_AI_SVG_DAILY_BUDGET_USD` 或分 6 天 |
| C CogView-3-Flash | `wd fetch-image <lemma> --provider gen` × 200 | ¥0；每日 50 上限 → 4 天，或临时调高 |
| D（可选）Commons `filetype:drawing` 单独跑 | 与 A 同命令但 `WD_IMAGE_PROVIDERS=wikimedia` 且强制 drawing | 0 |

三臂写进同一张表的不同行需要「每词多张」，而当前唯一索引只允许一张 active：试点脚本 `scripts/image_pilot.py`（与 `scripts/eval_provider.py` 一样先不入库）在每臂跑完后把 `word_images` 行与文件导出到 `pilot/<arm>/`（CSV：`lemma, arm, provider, file_path, alt_zh, query, provider_ref, score, prompt_version, model, cost_usd`），再 `UPDATE word_images SET status='superseded'`，释放唯一索引给下一臂；最后生成一张 HTML 对照表（每词三格）供评分。

#### 3.6.3 人工评分表（0–2 分，双评分者，Cohen κ ≥ 0.6 才采信）

| 项 | 问题 | 2 | 1 | 0 |
|---|---|---|---|---|
| R1 单一所指 | 10 岁孩子能一眼说出图里是什么吗 | 立刻能 | 犹豫 | 不能/多个主体 |
| R2 义项一致 | 图画的是例句 1 的那个意思吗 | 是 | 相关但不是那句 | 另一个义项/无关 |
| R3 干净安全 | 无文字、无人脸特写、无不当内容 | 全满足 | 有少量无关文字或细节 | 有文字/人脸特写/不当 |
| R4 风格一致 | 与同臂其他图风格一致且不雷同 | 是 | 风格漂移 | 雷同或风格乱 |
| R5 亲和/本土（仅 kid 臂） | 场景是中国小学生熟悉的吗 | 是 | 中性 | 陌生 |

通过 = R1 = 2 ∧ R2 ≥ 1 ∧ R3 = 2。指标：每臂通过率、交付率（拿到图/200）、每张通过图的成本、拒收率（B）、`content_filter` 率（C）、provider 请求数、平均延迟。采用门槛（事先定）：kid 词采用某臂需通过率 ≥ 70% 且每通过图 ≤ $0.02；照片臂通过率 ≥ 60% 才保留在 kid 链里。

#### 3.6.4 自动评分（可选，GLM-4.6V-Flash 免费 [image-memorability-32]）

提示词：给模型 `image_alt_zh`、例句 1、词义，要求 JSON `{"single_subject":0-2,"meaning_match":0-2,"clean":0-2,"text_present":0|1,"face_closeup":0|1,"note":"…"}`；走 `/paas/v4/chat/completions` 的 `image_url` 内容块；写 `word_images.eval_json`（3.1.5 新列），`text_present == 0` 时置 `text_free = 1`。先在 60 词子集上与人工比对，通过/不通过一致率 ≥ 80% 才用于批量；`word_images.score` 继续只存 `select.score` 的选择分（`store.activate_candidate`，`store.py:123-149`），语义不混。qwen3-vl-flash 作仲裁按付费计（新用户免费额度已下架 [verify image-memorability 遗漏 8]），全库 ≈ ¥33。

#### 3.6.5 产品内度量（第三期）

`review_logs` 已记每次评分；按 `word_images.provider`/`prompt_version` 分组统计首轮「不熟悉」率与 7 天后「记住了」率，是唯一能回答「哪种图更易记」的线上数据——但只有 2 个用户时没有统计力，先把分组键（`word_images.prompt_version`）存下来即可。

#### 3.6.6 文档数字

`docs/DESIGN.md:28,518,550`、`docs/CLAUDE_INTEGRATION.md:407,416`、`docs/DEPLOY.md:326,434`、`docs/ops.md:198`、`deploy/env.example:83`：$0.028 → $0.0140/张（$0.0124/次），≈18 张/天 → ≈35 张/天。

### 3.7 分期

| 期 | 条件 | 内容 |
|---|---|---|
| 一 | 本周合并；只用已有 Claude CLI 与匿名 Commons/Openverse | 3.1.1–3.1.3、3.1.5（0011 附加列）、3.1.6 文档、3.2.1–3.2.2、3.3.1–3.3.4（含黑名单修正与重试）、3.6.6 |
| 二 | 需智谱 key、一台出口正常的机器；需产品拍板 Q1（迁移里的阶段索引常量）与 A6 | 3.4 全部（含 0012 重建）、3.5.1 契约与前端、3.6.1–3.6.4 试点 |
| 三 | 视试点结果 | 3.3.4 复杂度启发式、3.5.2 多图、3.5.4 清晰度、`with_generated` 拆分、付费生成模型的计费、Lancaster 常模门控（CC BY 4.0，39,707 概念 [verify image-memorability 遗漏 3]）替代 `FUNCTION_POS` 硬编码、管理员词库页「指定关键词换图」（`endpoints.ts:538-540 adminRefetchImage` 今天无调用方 [images-pipeline-24]） |

---

## 4. 改动清单（文件 → 改什么）

### 4.1 第一期

| 文件 | 改什么 |
|---|---|
| `backend/wd/ai/prompts/svg_system.txt` | 整体替换为 3.1.1 正文 |
| `docs/CLAUDE_INTEGRATION.md:279-285` §5.5 | 代码块逐字同步；用户提示词示例改为 3.1.1 新形状；`:296` §6.1 `generate_svg` 行加 `prompt_version` 说明；`:401-403` §6.7 加「`claude_svg` 去 `<text>/<tspan>`、修裸 `&`、插 `<desc>` 标识、写 `prompt_version/model/text_free`」；`:407,416` 数字 |
| `backend/wd/ai/svg.py` | `:32-33` 加 `EXAMPLE_MAX = 120`、`HOOK_MAX = 60`、`SVG_PROMPT_VERSION = "svg-v2"`；`:40-45 build_user_prompt(display, meaning, scene, example, hook, style)`；`:48-52 prompt_for(conn, word, style)` 读 `examples[0].en`、`mnemonic_zh` 的「联想：」句；`:109-119` 调用处传 `style=style.style_for(word, cfg)`；`:137` `activate_svg(..., model=result.model_used, prompt_version=SVG_PROMPT_VERSION)`；拒收路径记 `svg_rejected`，修复路径记 `svg_repaired` 事件 |
| `backend/wd/images/sanitize_svg.py` | `:65-79 _parse` 加 `BARE_AMP_RE` 修复并返回修复次数；`clean(svg, *, allow_text=True)`；`_serialise` 按 `allow_text` 丢 `text/tspan`；新 `with_label(cleaned, label)` |
| `backend/wd/images/store.py` | `:152-174 activate_svg(conn, cfg, word_id, svg, alt_zh, *, model=None, prompt_version=None, now=None)`：`clean(allow_text=False)` → `with_label` → `write_bytes`；`:76-120 activate` 加参数 `prompt_version/model/text_free/eval_json` 并写入 INSERT（`:105-113` 列清单） |
| `backend/wd/images/style.py`（新） | 3.1.2 |
| `backend/wd/config.py` | `:155-168` 加 `image_kid_stages: tuple[str, ...] = ("zk",)`；`from_env` 解析 `WD_IMAGE_KID_STAGES` 并校验 ∈ `schemas.STAGE_ORDER`（注意 `config.py` 不能循环导入 `schemas`——把 `STAGE_ORDER` 校验放到 `style.kid_stage_indexes` 里延迟做，`from_env` 只做非空与逗号拆分） |
| `backend/wd/images/handler.py` | `:121-124` SELECT 加 `stage_min, pos, kind`；`:134-137` 查询词构造改为 3.3.1；功能词短路；`:148-152` 链按 `style` 生成两轮 `names`；`:158-159` `priority ≥ 90` 跳过扩展到 `pixabay/pexels`；`:165` `p.search(kw, SEARCH_LIMIT, style=…)`；`:182` `select.rank(..., style=…, lemma=lemma)`；docstring `:1-11` 更新 |
| `backend/wd/interfaces.py:73-79` | `ImageProvider.search(self, query, limit, *, style: str = "photo")` |
| `backend/wd/images/providers/base.py:100-118` | `get_json(..., return_headers=False)` |
| `backend/wd/images/providers/wikimedia.py` | `:40-51 params(query, limit, style)`：`filetype:drawing`/`bitmap`、`iiprop` 加 `thumbmime`、加 `maxlag: 5`；`:53-57 search` 识别 `error.code == "maxlag"` → `ProviderError(status=503, retry_after_s=…)`；`:97` `mime = info.get("thumbmime") or info.get("mime") or …`；docstring `:3-6` 更新 |
| `backend/wd/images/providers/openverse.py` | `:28` `PAGE_SIZE` 删除或改为上限 20；`:41-42 params(query, limit, style)` → `page_size=min(limit,20)`，kid 加 `category=illustration`；`:114-119 extra` 加 `"category"` |
| `backend/wd/images/providers/pixabay.py:30-39` | `image_type` 按 `style`（photo/illustration） |
| `backend/wd/images/providers/pexels.py:29-30` | 签名加 `style`，参数不变 |
| `backend/wd/images/select.py` | `:20-24` 拆 `UNSAFE_RE`/`NON_PHOTO_RE` + `KID_UNSAFE_RE`、`PEOPLE_RE`、`TEXTY_RE`；`:54-77 reject_reason(cand, exclude=(), *, lemma=None, style="photo")`；`:80-101 score(..., style="photo")` 新信号；`:104-128 rank(..., lemma=None, style="photo")`；模块 docstring 更新 |
| `backend/wd/images/service.py` | 加 `last_fetch_at`、`retry_if_failed`、`retry_failed_once`（3.3.3）；`backend/wd/images/__init__.py:18,21-35` 导出 |
| `backend/wd/services/bank.py:636,659` | 调 `images.retry_if_failed`（`from .. import images` 已在 `bank.py`？若无则加；注意 `images` 包不反向依赖 `services.bank`） |
| `backend/wd/services/batches.py:352-356,632` | 同上 |
| `backend/wd/jobs/scheduler.py:365-397` | `maintenance` 加 `images.retry_failed_once(conn, cfg, now, limit=50)`，`TickResult` 加 `image_retries` |
| `backend/wd/migrations/0011_word_images_meta.sql`（新） | 3.1.5 的四条 `ALTER TABLE` + 头注释（运行器写 `schema_migrations(11, 'word_images_meta')`） |
| `backend/wd/ai/prompts/content_system.txt:1,4,6,8,9,10` | 3.2.1/3.2.2 的规则改写；`docs/CLAUDE_INTEGRATION.md:208-225` §5.1 逐字同步 |
| `backend/wd/ai/content.py` | `:46 PROMPT_VERSION = "content-v2"`；`:54 EXAMPLE_EN_MIN = 10` |
| `docs/CLAUDE_INTEGRATION.md:206,355`、`docs/AI_FALLBACK_MODEL.md:29`、`docs/WORD_LIBRARY_CURATION.md:65` | `content-v2`、`10–240` |
| `docs/DESIGN.md §9`（`:523-553`） | 伪代码加风格分支、功能词短路、重试；Selection 段加新信号与黑名单拆分；Claude SVG 段改「无文字、`<desc>` 标识、`prompt_version`」；`:28,518,550` 数字 |
| `docs/DEPLOY.md:338-345`、`deploy/env.example:149-165` | 加 `WD_IMAGE_KID_STAGES`（默认 `zk`）；`:326,434` 数字 |
| `docs/ops.md:198` | 数字；`:202` `images-prune` 行加「重试规则会让被学的词重新抓图」 |
| `ATTRIBUTION.md:54-59` §3.4 | 「AI 生成示意图」加一句「SVG 文件内含 `<desc>` 生成标识；图内不含文字」 |

### 4.2 第二期

| 文件 | 改什么 |
|---|---|
| `backend/wd/images/providers/generate.py`（新） | 3.4.3 |
| `backend/wd/images/fetch.py` | `:241-268 normalise_image(data, max_edge, *, label=None)` 写 XMP/comment；新 `store_bytes(data, cfg, *, label)`；`AigcLabel` 数据类 |
| `backend/wd/images/handler.py` | `gen` 分支（显式 `provider="gen"` 与 `WD_IMAGE_GEN_POSITION`）；`register_cli` `--provider` choices 加 `gen`（`:352`） |
| `backend/wd/images/quota.py:37-47` | `limits_for("gen")` |
| `backend/wd/config.py` | 3.4.2 的 9 个字段 + 校验；`image_providers` 追加 `gen` |
| `backend/wd/migrations/0012_word_images_provider_gen.sql`（新） | `word_images` 重建（CHECK 加 `gen`）+ `user_settings ADD COLUMN image_hint` + `UPDATE … CASE current_stage` |
| `backend/wd/schemas.py` | `:46 ImageProviderName` 加 `"gen"`；`:1349-1351 RefetchImageRequest` 加 `"gen"`；`:576-585 ImageMeta` 加 `text_free: bool`；`:156-175 Settings` 与 `:376-392 SettingsUpdateRequest` 加 `image_hint` |
| `backend/wd/images/service.py:29-41,51-80` / `backend/wd/services/words.py:455-467` | `text_free`、`gen` 分支 |
| `backend/wd/security.py:586-606`、`SETTINGS_BOOL_COLUMNS`、`backend/wd/routers/settings.py:80-122`、`backend/wd/routers/onboarding.py` | `image_hint` |
| `frontend/src/api/types.ts:34-43,80-87,84`、`frontend/src/api/endpoints.ts:340` | 契约镜像 |
| `frontend/src/components/study/WordImage.tsx:28` | 题注含 `gen` |
| `frontend/src/components/study/StudyCard.tsx:201-228` | prop `imageHint`：正面在 `item.image.text_free && imageHint` 时渲染 `<WordImage … showImages>`，否则现有挖空提示 |
| `frontend/src/pages/StudyPage.tsx:635,695`、`frontend/src/pages/SettingsPage.tsx:413` | 传值 / 开关 |
| `frontend/src/i18n/zh.ts:82` + `docs/FRONTEND.md §8`（`:288`）、`:87`、`:105-132` §5.1 | `settings.imageHint` 新文案；WordImage 行；学习卡正面说明 |
| `docs/API.md` | 端点 14/15、25、69；§9 `Settings`/`ImageMeta`；§9.1 `:465` |
| `docs/DEPLOY.md §4/§9`、`deploy/env.example` | `WD_IMAGE_GEN_*`；CLI `fetch-image --provider gen` |
| `scripts/image_pilot.py`（新，先不入库） | 3.6.2 导出与对照表；评分表 CSV 模板 `scripts/image_pilot_rubric.csv` |
| `ATTRIBUTION.md §3.4` | `gen` 行（智谱用户协议、水印、XMP） |

---

## 5. 测试与验收

### 5.1 会变红的既有测试（必须在同一提交修）

| 测试 | 为什么红 | 改法 |
|---|---|---|
| `backend/tests/unit/test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5[svg_system]`、`[content_system]` | 提示词文件变了 | 同步 `docs/CLAUDE_INTEGRATION.md` §5.5/§5.1 代码块 |
| `backend/tests/unit/test_providers.py:46-68 test_wikimedia_request_shape_and_user_agent` | `params` 字典精确相等：`iiprop` 加 `thumbmime`、新增 `maxlag` | 更新期望字典；另加一条 `style="kid"` 的 `filetype:drawing` 断言 |
| `backend/tests/unit/test_providers.py:172-190 test_openverse_request_shape_and_parse` | `page_size` `"20"` → `"10"` | 更新；加 `category` 断言 |
| `backend/tests/integration/test_images.py:608-624 test_activate_svg_sanitises_and_serves_a_svg_image` | `:616` 断言 `"<text" in stored`；现在 `claude_svg` 去文字 | 改为 `"<text" not in stored and "<desc>" in stored`，并断言 `text_free == 1`、`prompt_version` |
| `backend/tests/unit/test_content_apply.py:71-83` | `:81` `prompt_version == "content-v1"` | 改 `content-v2`；`:80` 键集合不变（第一期不加字段） |
| `backend/tests/integration/test_images.py:535-547 test_keywords_come_from_content_with_blocklist_and_shape_filter` | 词 `pear` 无内容、无 pos → 仍搜 lemma（`insert_word` 夹具不写 `pos`），绿；但若夹具词 `chart` 的 lemma 豁免影响 `set_content(["bar chart"])` 的关键词过滤——关键词过滤用全表，仍被滤掉 → 绿 | 回归确认；另加功能词用例 |
| `backend/tests/unit/test_db.py:36-56 test_fresh_migration_creates_schema…` | `EXPECTED_TABLES`/25 张表不变（只加列）→ 绿 | 新增 0011 列的断言（见 5.2） |
| 第二期：`backend/tests/unit/test_api_schemas.py:108`（`Settings` 字段集合）、`backend/tests/integration/test_settings.py:59,75-78`、`frontend/src/i18n/zh.test.ts`/`zh.contract.test.ts`（新键）、`scripts/check_contract.py`（`ImageProviderName`）、`backend/tests/integration/test_admin_ops.py:87,123,144`（`photo_mix` 分类）、前端 `StudyCard.test.tsx:11`/`WordDetailPage.test.tsx:85`/`StudyPage.test.tsx:38` 的 `ImageMeta` 夹具（缺 `text_free` → tsc 红） | 契约变更 | 同提交更新 |

不受影响：`backend/tests/unit/test_sanitize_svg.py`（`clean()` 默认 `allow_text=True`）、`test_card_svg.py`、`test_quota.py`、`test_media.py`、`test_deploy_files.py:143`、`test_config.py:33,53,73,102-103`（默认 provider 链不变）。

### 5.2 要加的测试

- `tests/unit/test_sanitize_svg.py`：`test_bare_ampersand_is_repaired_before_parse`（`<title>A & B</title>` 与属性值里的 `&` → 通过且输出 `&amp;`；已转义的 `&amp;`/`&#38;` 不重复转义）；`test_allow_text_false_drops_text_and_tspan_but_keeps_title_desc`；`test_with_label_inserts_desc_after_root`（幂等、转义）。
- `tests/unit/test_style.py`（新）：`style_for` 对 `stage_min` 1/2/3/None 与 `WD_IMAGE_KID_STAGES="zk"`/`"xs,zk"`；`dominant_pos("n:4/v:96") == "v"`；`skip_image` 对 `i/c/d/p/a/u/r` 真、`n/v/j/m` 假、`pos NULL` 假。
- `tests/unit/test_select.py`：黑名单拆分（`reject_reason(cand(title="Map of Europe"), lemma="map") is None`、`lemma="apple"` 仍 `"blocklist"`、`UNSAFE` 永远拒）；`score` 新信号各一条（description 命中、category 匹配 ±1、人像 −2 仅 kid、竖图 −2、texty −2）；`test_score_table` 原断言保持。
- `tests/unit/test_providers.py`：Commons `maxlag` 应答（200 + `{"error":{"code":"maxlag"}}` + `Retry-After: 5`）→ `ProviderError(status=503, retry_after_s=5)`；`thumbmime` 优先；Openverse `category`；Pixabay `image_type` 随 style。
- `tests/integration/test_images.py`：`test_function_word_gets_the_card_without_any_provider_call`；`test_kid_style_chain_tries_drawing_before_bitmap`；`test_failed_word_is_refetched_when_marked_unfamiliar_after_a_day`（冻结时钟 +1 天；1 小时内不重抓；live 任务存在不重抓）；`test_nightly_retry_respects_limit_and_cooldown`；`test_svg_prompt_carries_example_hook_and_style`（`build_user_prompt` 快照）；`test_svg_activation_records_prompt_version_model_and_text_free`。
- `tests/unit/test_db.py`：仿 `:282-310`（0009）——在 0001 基线上插入一行 `word_images` 再 `run_migrations`，断言四列存在、默认值、`text_free` CHECK 生效、行数不变；第二期仿 `:128-211`（`REBUILD_USERS_SQL`）——`word_images` 重建后行数/`id`/`words.active_image_id` 指向不变、`provider='gen'` 可插入、`'flickr'` 被拒、三个索引都在（`SELECT name FROM sqlite_master WHERE tbl_name='word_images'`）、`image_hint` 由 `current_stage` 推出。
- `tests/unit/test_content_apply.py`：12 字符例句现在被接受（`"I like cats."`），9 字符仍丢。
- 第二期：`tests/unit/test_generate_provider.py`（`httpx.MockTransport`：url 路径、`content_filter` ≥ 1 拒、`b64_json` 路径、配置缺失 → `ProviderError`、水印参数固定 true）；`tests/unit/test_fetch.py`：`normalise_image(label=…)` 产出含 XMP 包且 `label=None` 时无 APP1；`tests/integration/test_images.py::test_gen_provider_is_explicit_only_by_default`。
- 前端：`StudyCard.test.tsx` 加「`imageHint && text_free` → 正面出现 `<figure class="word-image">`；`text_free=false` → 挖空提示」。

### 5.3 在 live-copy.db 的私有拷贝上排练

```
cp scratchpad/live-copy.db scratchpad/design-images-evidence/rehearsal.db     # 永远不碰 /Users/sqin/word-dance-data
WD_DATA_DIR=scratchpad/design-images-evidence/data WD_DB_PATH=…/rehearsal.db \
  PYTHONPATH=backend .venv/bin/python -c "from wd import db; c=db.connect('…/rehearsal.db'); print(db.run_migrations(c, dry_run=True).pending); print(db.run_migrations(c).applied)"
```
- 一律走 `.venv/bin/python` 的 `run_migrations`，不用 `/usr/bin/sqlite3`（其 `legacy_alter_table=1` 会掩盖重建问题 [verify stage-model-13]）。
- 验证 SQL（只读）：`PRAGMA table_info(word_images)` 含四列；`SELECT COUNT(*) FROM word_images` = 31；第二期 `SELECT sql FROM sqlite_master WHERE name='word_images'` 含 `'gen'`，`SELECT COUNT(*) FROM words WHERE active_image_id IS NOT NULL AND active_image_id NOT IN (SELECT id FROM word_images)` = 0；`PRAGMA integrity_check`；`PRAGMA foreign_key_check` 为空。
- 功能排练（不联网）：`backend/tests/integration/test_images.py` 用 `mock_http` 夹具（`wikimedia_search.json`、`openverse_search.json`）即可覆盖链与重试；真实抓取只在试点机上做。
- 验收：`make test`（后端 1,490 个用例 + 前端 vitest）全绿；`python scripts/check_contract.py` 「contract OK」；`npm run lint`（`scripts/check-copy.mjs`）无中文泄漏；`wd check providers` 列出 `gen`（第二期）。

---

## 6. 上线与回滚（Mac，launchd）

本机与 `docs/DEPLOY.md` 的 Linux 版差异：没有 `install.sh`/`systemctl`，服务由 launchd agent 管理，`wd serve` 启动时自动 `run_migrations`（先 `backup.snapshot_before_migrate` 快照）再 `seed_check`（`backend/wd/main.py:482-485`，[stage-model-11]）。label 与路径按 memory `macos-local-install.md`。

第一期（附加迁移 0011，停机 < 1 分钟）：
1. `launchctl bootout gui/$(id -u)/<word-dance label>`；确认 `pgrep -f 'wd serve'` 为空。
2. `wd backup --with-images`（手工全量；迁移前快照 `backups/pre-migrate-10-to-11.db.gz` 会再自动生成）。
3. `git pull`（或 checkout 该提交）；`cd frontend && npm ci && npm run build`（第一期无前端改动可跳过）。
4. `wd migrate --dry-run` → 只列 `(11, 'word_images_meta')`；`wd migrate`。
5. `wd import-seed`：不需要（种子未变，`kv.seed_version` 不变）；若阶段模型同批上线则按其顺序「迁移 → import-seed」。
6. `launchctl bootstrap gui/$(id -u) <plist>`；`curl -s localhost:8000/api/health`。
7. 验证：`sqlite3 -readonly <db> "PRAGMA table_info(word_images)"`；管理页概览 `images.providers` 正常；对一个在学的初中词执行 `wd fetch-image <lemma> --provider claude_svg`（花 ≈ $0.012），检查 `/media/images/<sha>.svg` 无 `<text`、含 `<desc>`，`word_images.prompt_version='svg-v2'`、`text_free=1`；journal 里 `svg_rejected` 不再出现。
8. 回滚：代码回退即可（新列对旧代码无害，见 3.1.5）；若要连列一起回退 `wd restore backups/pre-migrate-10-to-11.db.gz`（会丢回滚窗口内的学习记录——仅在迁移本身失败时用；运行器失败会整文件回滚，不留 bookkeeping 行 [stage-model-21]）。

第二期（重建迁移 0012）：步骤同上；第 4 步 dry-run 应列 `(12, 'word_images_provider_gen')`；`.env` 先加 `WD_IMAGE_GEN_KIND=none`（默认即关）——试点机另配 key；回滚：`gen` 行只在试点机上存在，本机代码回退即可。

---

## 7. 风险、未决问题、工作量

### 7.1 风险

1. **「无文字」会不会让 Claude 画不出可辨认的图**：去掉文字后，抽象词的 SVG 可能更难辨认（现有 30 张里 `particularly`「一圈绿苹果中一个红苹果」这类本来就靠文字兜底）。缓解：功能词/副词不配图（D6）；试点 R1 直接测量；不达标则抽象词退回模板卡。
2. **4 次拒收的根因是推断**（未读 `stdout_path`）。缓解：`&` 修复 + 提示词双保险 + `svg_repaired` 事件可观测；上线后看拒收率。
3. **智谱返回 URL 的主机能否过 SSRF 规则**（https/443/公网 IP）未知；`b64_json` 智谱文档未列。缓解：适配器两条路径都写；试点第一天验证。
4. **标识合规字段**：GB 45438-2025 元数据字段集未读；重编码会丢智谱隐式水印，是否违反其用户协议需法务判断。缓解：XMP 自带字段；试点阶段图片不公开分发；上线前核对。
5. **儿童安全**：照片 provider 的 `mature` 信号薄；生成模型 `content_filter` 拒绝率未知。缓解：kid 风格硬拒词表、人像降权；试点记录 `gen_filtered`。
6. **Commons `filetype:drawing` 的剪贴画质量与 `haswbstatement` 的「含有而非典型」问题** [verify images-pipeline O5]：命中率未知。缓解：试点 D 臂单独量化。
7. **`image_hint` 正面出图对初中用户的过度自信风险**（Carpenter & Olson 的对象是成人；Tonzar 的八年级支持出图）。缓解：默认只对主攻阶段 ∈ 儿童集合的用户开；可关。
8. **迁移编号冲突**：阶段模型设计也用 0011。缓解：以合入顺序顺延；两份重建迁移若同批上线合成一个停机窗口。
9. **Openverse 匿名配额被试点耗尽**会影响线上同出口的抓图（[verify images-pipeline 未解决 5]）。缓解：试点在另一出口（东京）或注册应用。

### 7.2 未决问题（需要拍板或数据）

1. Q1 的阶段索引方案（决定 `0012` 里 `image_hint` 的 `CASE current_stage IN (…)` 常量与 `WD_IMAGE_KID_STAGES` 默认值何时改成 `xs,zk`）。
2. 是否接受「初中词也用儿童风格」（本设计的偏离 1）。
3. 智谱 key 由谁申请、放在哪台机器；试点机器的出口。
4. 隐式标识字段集（GB 45438-2025）与本应用的主体定位。
5. 旧 30 张 SVG 是否在第二期一次性重画（$0.42）以便全部 `text_free`。
6. `with_generated` 是否值得一次契约变更（第三期）。
7. 11-02 的 18 次 Wikimedia 有应答却失败的原因仍需线上 journal（INDEX 未解决 7）；它决定 3.3.4 的打分规则是否曾被真正检验。

### 7.3 工作量（人日）

| 项 | 人日 |
|---|---|
| 第一期：提示词 + 文档同步 0.5；sanitizer + 测试 0.5；`style.py` + handler 改造 1.0；provider 参数/`maxlag`/`thumbmime` + 测试 1.0；`select` 信号 + 黑名单拆分 + 测试 0.5；重试三挂点 + 测试 1.0；0011 + 测试 0.3；数字文档 0.2 | **≈ 5** |
| 第二期：生成适配器 + 配置 + 配额 + 测试 2.0；0012 重建 + 测试 0.5；契约（`gen`、`text_free`、`image_hint`）前后端 + 文档 + 测试 1.5；正面出图 UI + 设置 1.0；标识（XMP/`<desc>`）0.5；试点脚本 + 评分表 + 跑三臂 + 分析 2.0；VLM 评分 1.0 | **≈ 8.5–9** |
| 第三期（可选） | 3–6 |
| 合计（一 + 二） | **≈ 14** |
