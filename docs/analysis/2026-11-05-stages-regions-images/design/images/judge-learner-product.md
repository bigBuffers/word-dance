# 评审：配图更易记 · 角度「产品与学习科学怀疑者」

日期 2026-11-06 · 基线 `main @ 75df534` · 被评审文件：同目录 `evidence-first.md`、`pipeline-engineer.md`、`generation-first.md` · 评审者只读仓库与 `scratchpad/live-copy.db`（`?mode=ro`），复算脚本在 `scratchpad/judge-learner-product/pos_stats.py`（`python3 -I`）。

立场：盯住上海小学生 / 初中生 / 高中生与现有 2 个用户的真实体验，默认每个未被证明的说法都是错的。标注：`[文件:行]` 为我重新打开核对的代码位置；`[INDEX Dn]` / `[image-memorability-N]` / `[verify …]` 指调研文件条目；「复算」= 我在只读副本上重跑得到的数字。

---

## 0. 抽查引用：三份设计的 `文件:行` 与 facts 条目是否属实

共重开 60 余处引用，下表只列有代表性或有出入的（✓ 属实；△ 近似 / 行号偏差；✗ 不属实）。

| # | 引用 | 出现在 | 核对结果 |
|---|---|---|---|
| 1 | `svg_system.txt:1` 要求 "the English word in a <text> at the bottom" | 三份 | ✓ 原文一致 |
| 2 | `test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5` 绑定 §5.1 / §5.5 代码块且首字符须为字母 | EF、GF 引用 | ✓ `parametrize` 含 `("content_system","### 5.1")`、`("svg_system","### 5.5")`，`assert text[0].isalpha()` |
| 3 | 「`CLAUDE_INTEGRATION.md:279-285` §5.5 的代码块……**该块没有测试绑定**」「§5.1 ……（无测试绑定）」 | PE §3.2.2、§3.3.2 | **✗** 与第 2 条直接矛盾，见 PE 致命缺陷 1 |
| 4 | `test_images.py:616` 断言 `"<text" in stored` | 三份 | ✓ |
| 5 | `test_images.py:162` 对 Openverse 请求参数**整字典**断言含 `"page_size": "20"` | 仅 PE 列入会红名单 | ✓ 存在；EF、GF 的会红名单**漏掉**它 |
| 6 | `test_providers.py:57-64`（Wikimedia 参数字典）、`:178`（Openverse）、`:351`（Pixabay `image_type`） | 三份 | ✓ |
| 7 | `test_select.py:92-119 test_score_table` 的行「全部仍成立」(PE/EF) vs 「新信号改变个别分值……逐行更新」(GF) | PE、EF、GF | PE/EF ✓：`cand()` 默认无 `description`、各行宽高比 ≥ 1.0、标题无人像/标牌词 `[test_select.py:11-29, 92-119]`；GF 的「需逐行更新」不成立 |
| 8 | `0001_init.sql:248` provider CHECK、`:265` mime CHECK、`:266` score、`:270-272` 三个索引、`:572-576` v_bank 不引用 `word_images`、全文件无 `REFERENCES word_images` | 三份 | ✓ 全部属实（`grep -n word_images` 只命中 199/245/270-272） |
| 9 | `handler.py:121-124` SELECT 无 `stage_min/pos`、`:134-137` 关键词、`:158-159` priority ≥ 90 跳过 openverse、`:201-206` SVG 分支、`:349-361 register_cli`、`:352` `--provider` choices | 三份 | ✓ |
| 10 | `select.py:20-24 BLOCKLIST_RE`、`:30 MIN_WIDTH`、`:65-66` mime 拒、`:72` description 只用于拒、`:83` 打分只看 title+tags | 三份 | ✓ |
| 11 | `wikimedia.py:27 THUMB_WIDTH`、`:40-51 params`、`:97 mime`；`openverse.py:28 PAGE_SIZE`、`:41-42`、`:114-119 extra`；`pixabay.py:30-39`、`:78 extra["type"]`；`pexels.py:29-30` | 三份 | ✓ |
| 12 | `base.get_json:100-118` 只把 ≥ 400 当错误（maxlag 需在 search 里判） | 三份 | ✓ `[base.py:106-111]` |
| 13 | `quota.py:28 DEFAULT_COOLDOWN_S`、`:37-47 limits_for`、`:160-179 status` 只遍历 `cfg.image_providers` | 三份 | ✓；GF「`quota.status` 自动显示 `ai_image`」只在它出现于**成人链**时成立 |
| 14 | `content.py:46 PROMPT_VERSION`、`:49 STAGE_ZH`、`:54 EXAMPLE_EN_MIN`、`:61-63`、`:88 STAGE_ZH[s]`、`:253-261 enqueue_image`、`:405 select_jobs` | 三份 | ✓ |
| 15 | `bank.py:636,659` 两处 `enqueue_content_if_needed`；`batches.py:639` 同类调用 | 三份 | ✓；EF 写成 `:632 append_to_today`（实际调用在 639，`append_to_today` 定义在 642）△ |
| 16 | `scheduler.py:364-393 maintenance`、`:66 TickResult`、`:298 requeue_dead_once` | 三份 | ✓ |
| 17 | `schemas.py:46 ImageProviderName`（含 `card_svg`）、`:51-52`、`:56-61`、`:87-90 extra="forbid"`、`:576-585 ImageMeta`、`:1094-1101`、`:1132-1138`、`:1349-1351` | 三份 | ✓ |
| 18 | `config.py:52 IMAGE_PROVIDERS`、`:64-75 SECRET_KEYS`、`:155-168`、`:252-256 present`、`:355-369`、`:379-401`、`:522-534`、`:554-575 entries` | 三份 | ✓ |
| 19 | `test_deploy_files.py:119` env.example 一一对应、`test_docs_contract.py:114` DEPLOY §4 命名每个变量、`test_cli.py:56-58`、`test_budget.py:33 estimate("svg") == 0.03`、`test_content_apply.py:80-81` | PE、GF | ✓ |
| 20 | Pillow 12.3.0 JPEG `save` 支持 `xmp`/`comment` | EF（`JpegImagePlugin.py:762`）、GF | ✓ `.venv` 实查 `:762 if xmp := info.get("xmp")`、`:791 comment` |
| 21 | `scratchpad/design-stage-model-minimal/0011_primary_stage.sql` 已存在（阶段模型占用 0011） | GF | ✓ 存在 |
| 22 | `StudyCard.tsx:201-228` 正面无图、`:302-311` 背面渲染 `WordImage`；`WordImage.tsx:28` 题注；`zh.ts:54/86/92`；`types.ts:83-84`；`endpoints.ts:340,538-540`；`pos.ts:8-20` | 三份 | ✓ |
| 23 | 线上数字：30 SVG（`query` 全 NULL）+ 1 wikimedia；failed 18 / none 9,113 / ready 31；`ai_calls` svg 34 次 $0.4207 $0.01237；svg jobs 34/30/4；fetch jobs 20:19 + 30:30 全 failed；用户 1 `["zk","gk","cet4","cet6"]`/3、用户 2 `["zk"]`/1 | 三份 | ✓ 复算一致 |
| 24 | `stage_min=1` 词性分布 n 1,043 / v 361 / j 301 / r 105 / 无 100 …；505 转录件在库 497：n 233 / v 89 / j 73 / r 30 …；「不配图」覆盖 243 / 94 | EF §3.0 | ✓ **复算逐项一致**（按占比最高的 pos 代码） |
| 25 | `stage_min=1 AND kind='word'` 2,012 词，「首位词性 n 808 / v 557 / adj 235 / other 207 / adv 163 / none 42」 | PE §3.4.1、§5.3 | △ 数字可复现，但「首位」= ECDICT `pos` 串里**第一个**代码，不是主词性（`pos` 不按占比排序，如 `n:4/v:96`，`[pos.ts:1-3]`）；PE 自己的门用的是「占比 ≥ 80%」，复算该门只命中 120 / 2,099 词 |
| 26 | 「ECDICT `pos` 主标签 n 179 / v 135 / j 44」（497 个小学词） | GF §2 A1、§3.8 | **✗** 这组恰是「首位代码」的分布；按主词性应为 n 233 / v 89 / j 73。GF 的试点分层（100 名词 + 70 动词 + 30 形容词）与功能词门「主标签 ∈ {…}」都建立在错误的口径上 |
| 27 | 195 条线上例句最短 33 字符 | PE（引 `[verify ai-prompts-stages-5]`） | ✓ 复算 `195|33` |
| 28 | 18 个 failed 词中 17 个 `word_is_studied` 为真（`employee` 除外） | PE、EF | ✓ 复算 17 |
| 29 | D1 文献归属（Nelson 1976、Defeyter 2009 七岁组反转、Tonzar 2009 四/八年级、Lotto & de Groot 1998、Carpenter & Olson 2012、Boers 2009/2017、Flack & Horst 3.5 岁、Kaminski & Sloutsky 6–8 岁、Adesope & Nesbit 57 项、诱人细节 58 项 g≈−0.33、Yun 2011 10 项 n=1,560、Attygalle 2025 无效应量、Pressley & Levin 1978 二手） | EF 表 1.1/3.0；PE、GF 表 3.1 | ✓ 与 `facts/image-memorability.md` [1][2][6][7][8][9 核验修正][10][11][12][13][14] 及 `verify` 一致；但 EF 把 Adesope & Nesbit 2012 当「图中无文字」的依据属**误用**（见 EF 缺陷 2） |
| 30 | Openverse `category` 枚举 `digitized_artwork / illustration / photograph` | 三份 | ✓ `openverse_schema.yaml:1526-1531`、`field_values.py:10-14` |

小结：三份设计的代码行号总体可靠（EF 与 PE 几乎零错，GF 一处 ✗），**但三份都有「分析性断言」没经过执行验证**：PE 的「无测试绑定」、GF 的「主标签」与「test_score_table 需改」、EF/GF 漏掉 `test_images.py:162`。

---

## 1. 三份设计的共同底座，以及共同的盲区

### 1.1 它们一致的地方（一致处大概率是对的）

SVG 提示词去掉底部英文词、解析前修裸 `&`、`activate_svg` 剥 `<text>/<tspan>`；content 第 6/7 条改为「画例句 1 的义项、单一主体、无文字无人脸特写、抽象词对齐 `mnemonic_zh`」；`EXAMPLE_EN_MIN` 15→10、`PROMPT_VERSION`→`content-v2`、`PREFIX_MIN` 不动、不加 `image_scene_en`；功能词不搜裸 lemma；Commons `filetype:drawing` + `thumbmime` + `maxlag`；Openverse `page_size` 20→10；失败词自动重试（三个挂点）；文档 $0.028→$0.0124/$0.0140、18→35–40；图默认在回忆之后；每词一图不改唯一索引；风格由词的 `stage_min` 决定；生成位图默认关、智谱 CogView-3-Flash 试点、200 个二级词三臂；厂商水印保持开。这一层与 INDEX Q7-a 与 [D1][D2][D3][D4] 完全一致，可以直接作为最终方案的公共部分。

### 1.2 三份都没有回答「配图是否真的更易记」

- 三个试点量的都是**评分者眼中的图片质量**（单一所指 / 义项一致 / 干净），不是记忆。EF §3.6.3、PE §3.7.3、GF §3.8 都用两名成人评分者；GF 的 Q5「最能帮我记住」是主观投票，EF §3.6.5 承认线上 2 个用户没有统计力。没有任何一份提出哪怕最小的回忆测量（例如评分者看图 24 小时后再猜词），也没有任何一份让一个真实小学生看过一张图——而产品负责人刚刚把受众定为上海小学 1–5 年级。[INDEX D1] 自己说「没有找到 6–11 岁的直接实证」，三份设计的试点都不填这个洞，只是把「卡通 vs 照片」换成「照片链 vs SVG vs 生成」再问成人。**最终方案必须加一个儿童小样本**（见 §5 嫁接 4）。
- 三份都把 `zk`（初中，12–15 岁）划进「儿童风格」：EF 显式（偏离 1，`WD_IMAGE_KID_STAGES` 默认 `zk`，STYLE_KID 写明 "for 6–12-year-olds"）、GF 用 `STAGE_ORDER.index("zk")+1`（今天 = 1 ⇒ 初中即 kid）、PE 默认关但 §6 第 4 步在本机直接开到 1。Tonzar 2009 支持八年级**从图受益**，不支持八年级受益于「六到十二岁绘本风」[image-memorability-7]。初中生对幼稚化画风的排斥没有被任何一份当作风险。更重要的是风格按词而不按用户：用户 1（成人，学 zk–cet6）与用户 2（只学 zk）看到同一张「绘本」`[0001_init.sql:272 ux_word_images_active]`。三份都写了「可接受」，没有一份给出理由。
- **小学生第一周看到的「配图」其实是模板卡。** 线上 497 个二级词 0 张图、1 条内容（复算），SVG 只给「正在被学」的词、每天 ≈ 35–40 张 `[budget.py:273]`，照片链在本机出口 0/49 `[images-pipeline-28]`。一个每天学 10–20 个新词的小学生，在内容任务 → 抓图任务 → SVG 任务排完之前看到的就是 `card_svg`（72 px 词头 + 音标 + 释义 + 例句，`[image-memorability-18]`）。三份都只说「模板卡不当提示用」，没有一份把「模板卡对 6–11 岁可读性」列进范围。这是产品层最大的欠设计，但不是任何一份的独有缺陷。
- 「不合适」举报阈值 1、全局立即生效、并触发重抓（可能再花一次 SVG 预算）`[service.py:186-202]`，`docs/WORD_LIBRARY_CURATION.md:136,234` 已提出要改成 N 个不同用户。面向小学生时误触概率显著上升；三份里只有 GF §3.6.9 提到举报路径且维持原样。
- `wd images-prune` 会删掉无人学的词的图 `[handler.py:298-331]`，三份都只在 ops 文案里提醒，没有改行为——与「给 505 词预生成」方向相抵 [verify images-pipeline O7]。

---

## 2. 逐份评审

### 2.1 evidence-first（EF）

**长处**
- 证据→准则→代码的映射（§3.0）是三份里最完整、引用最准确的；词性统计用的是**主词性**（复算逐项一致），功能词覆盖 243 / 94 的数字可靠。
- 风格集合用阶段**码**配置并经 `stage_to_index` 解析（§3.1.2），在 Q1 的 a / b 两种编码下都成立；还注意到 `config.py` 不能循环导入 `schemas` 而把校验延迟到 `style.py`。
- `text_free` 作为**代码保证**的属性随激活写入（§3.1.3/3.1.5），比 PE / GF 用 `query` 字符串反推干净；`eval_json` 与 `score` 分列，语义不混。
- 儿童安全硬拒词表、人像降权只在 kid 风格、黑名单拆 `UNSAFE/NON_PHOTO` 并对 lemma 本身豁免（`map/flag/cover/sign/text` 都是 `stage_min=1` 的词，复算属实）——这是唯一真正站在小学词表上想过黑名单副作用的设计。
- A6 的两用户迁移规则写进 `UPDATE … CASE`（用户 1→0、用户 2→1），与 live-copy 一致。
- 试点评分表有 κ ≥ 0.6 与事先定的采用门槛；R5「本土场景」是唯一把 INDEX D1 准则 6 当假设去测的项。

**缺陷（按对小学生体验的影响排序）**
1. **「图作提示」把证据用反了（学习科学层面最严重）。** D3 / §3.5.1 说开启 `image_hint` 后「正面直接显示图，学习者看图回忆英文再翻面」，但 StudyCard 正面始终渲染 `WordHeader`（英文词头）`[StudyCard.tsx:204-206]`，设计只在正面**加**一个 `<WordImage>`（§4.2 改动清单），没有提出隐藏词头。于是小学生看到的是「英文词 + 这个词的画」，再被要求「回忆」中文义——对具体名词（小学词 47% 是名词）画就是答案。这正是 [image-memorability-6] Carpenter & Olson 的过度自信场景、也是 INDEX D1 标题里的「图不能先于回忆出现」。Tonzar 的 picture-based method 是**遮住词、看图产出 L2 词**，与此处的任务方向相反。更糟的是默认对 `current_stage ∈ 儿童集合` 的用户**开启**（用户 2 → 1）。PE 的「按 H 才出现」是对同一证据的正确读法。
2. **Adesope & Nesbit 2012 不支持「图里一个字都不能有」。** 该元分析被引用的结论是「从旁白里抽出的关键词显示在屏幕上**有助**学习」[image-memorability-12]，即短文字冗余有益；拿它给 D1 背书是误用。「无文字」真正站得住的依据只有 [verify images-pipeline O6]（印词头 = 泄露答案）与 Boers [8]（分走对词形的注意），这两条已够，不必借一个方向相反的元分析。
3. **功能词「直接 `failed`」与自动重试互相打架。** §3.3.1 第 4 条把功能词写成 `image_state='failed'`，§3.3.3 的 `retry_if_failed` / `retry_failed_once` 只看 `failed + 被学 + 超过一天 + provider 不冷却`，没有排除 `skip_image()` 为真的词 → 每个被学的功能词每天入队一次、立刻以 `STATUS_SKIPPED` 结束，吃掉夜间 `limit=50` 名额并污染 `jobs`。`image_state` 的 CHECK 只有四个值 `[0001_init.sql:201]`，需要另一个标记（或在重试函数里复用 `skip_image`）。
4. **`FUNCTION_POS` 把全部副词（`r`）排除在配图之外。** 505 词里 30 个主词性为副词的词：again / always / back / down / far / **fast** / here / now / off / out / sometimes / today / tomorrow / up / yesterday / well……（复算）。fast、up/down、today/tomorrow、back 对小学生都可画（蜗牛 vs 猎豹、箭头、日历）。规则用「宁可不配图」做辩护，但试点只抽名词/动词/形容词（§3.6.1），所以这条规则本身永远测不到。至少应降为「可配置、试点里单独抽 20 个副词验证」。
5. **会红名单漏了 `backend/tests/integration/test_images.py:162`**（Openverse 参数整字典含 `"page_size": "20"`，`[test_images.py:162]`）。第一期把 `page_size` 改成 10 会让它红；§5.1 只列了 `test_providers.py:172-190`。
6. **第一期就带迁移，且与阶段模型抢 0011。** `db.list_migration_files` 把重复版本号视为错误 `[db.py:159-161 docstring]`——若两条线各自以 0011 合入，服务启动时 `run_migrations` 直接失败。EF 在 §3.1.5 / §7.1-8 承认并说「顺延」，但这让「本周可合并」依赖另一条线的合入顺序；PE / GF 的第一期都不需要迁移。
7. **`&` 修复正则只把「长得不像实体」的 `&` 转义**（`&(?!(?:[A-Za-z][A-Za-z0-9]*|#…);)`）：模型写出 `&nbsp;` 这类 HTML 实体仍是 XML 未定义实体、仍被拒。GF 的正则只放行 XML 五个命名实体 + 数字引用，更严也更对。
8. **第二期过重且先于证据。** 9 人日里把 `gen`、`text_free`、`image_hint` 三项契约变更 + 0012 重建 + XMP + 正面出图 UI 一次做完，而 §3.6 的试点只需要适配器 + 脚本；`text_free` / `image_hint` 的 UI 在试点结论之前没有用户。
9. 「拒收率预期 → ≈ 0」没有依据（4 次拒收的原文未读，`[verify image-memorability 遗漏 1]` 标为推断）；EF 自己列为风险 2，但 §1.3 成本表把它当成结论用。

**打分**：fit 6 · correctness 6 · effort_risk 5 · maintainability 6 · evidence 7 · rollout 6 → **overall 6.0**

### 2.2 pipeline-engineer（PE）

**长处**
- 7 个可独立回退的提交、无迁移、无契约、无前端——第一期的爆炸半径是三份里最小的；§6 的 launchd 上线与 `.env` 回滚兼容分析（`from_env` 不拒绝未知 `WD_` 键，`[config.py:252-256]`）是三份里唯一真正读了代码路径的回滚论证。
- 会红名单最准：抓到 `test_images.py:162`、`test_deploy_files.py:119`、`test_docs_contract.py:114`、`test_providers.py:2` 文档串。
- 重试带 `RETRY_MAX_AUTO_30D = 3` 上限 + `wd images-retry --dry-run`，不会无限打转；黑名单「查询本身含该词时放行」（`allow = RELEVANCE_RE` 命中的关键词 token）比 EF 的 lemma 豁免更精确（查 `world map` 放行 `map`，查 `apple` 仍拒）。
- 「图像提示」只在按 H 时出现、且只对 `hint_safe` 图——这是对 Carpenter & Olson 最保守、最正确的读法。
- 插画链默认关（`WD_IMAGE_KID_STAGE_MAX=0`），并说明了为什么：Openverse illustration 返回 350×400 以下剪贴画 `[verify image-memorability 遗漏 5]`、Commons drawing 首批含结构图 `[verify images-pipeline-31]`。

**缺陷**
1. **「§5.5 / §5.1 代码块没有测试绑定」是错的，而且会导致测试红。** `backend/tests/unit/test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5` 对 `content_system`→§5.1、`svg_system`→§5.5 做逐字节比对。PE §3.2.2、§3.3.2 两次写「无测试绑定」，§5.1 会红名单也没有它。改动清单（§4 P1-1/P1-2）里虽然列了同步文档，但任何把「无绑定」当真、先合代码后补文档的实施都会让两个参数化用例变红。这是事实错误，必须改。
2. **`WD_IMAGE_KID_STAGE_MAX=0` 作为「关闭」哨兵与 Q1-b 冲突。** PE §2 A1 行声称 Q1 任一编码都只改一个配置值；但若产品选「小学 = 0」，`stage_min=0 <= 0` 对所有小学词成立——开关显示「关」而小学词已走插画链。应改为 `None` / 阶段码（EF 的做法）。
3. **给默认照片链加 `category=photograph` 不是「无害参数」。** Openverse 的 `category` 是对 provider 提供字段的过滤 `[openverse_schema.yaml:1526-1531]`，未分类的图会被排除；这改变了成人链在一个 0/49 命中率的链上的召回，没有任何测量就写进「线上行为只多三个无害参数」（§1 P1-4、§5.4）。第一期对默认链的请求形状应保持不变，`category` 只在 kid/illustration 一遍加。
4. **§6 第 4 步直接在生产 `.env` 里 `WD_IMAGE_KID_STAGE_MAX="1"`——「这就是试点」。** 这与 §3.7.3「插画臂高出照片臂 15 个百分点才改默认」自相矛盾：两位真实用户（其中用户 2 就是 K-12 画像）成了没有评分表的试验对象；而且 240×180 的尺寸门槛（§3.4.3）意味着他们会在 DPR 2–3 的手机上看到 `contain` 后的小模糊剪贴画。
5. **「首位词性」不是主词性。** §3.4.1 / §5.3 的 n 808 / v 557 / adj 235 / adv 163 / other 207 是 ECDICT `pos` 串里第一个代码的分布（`pos` 不排序，`[pos.ts:1-3]`）；门本身用「占比 ≥ 80%」，复算只命中 120 / 2,099 词，与「207 个其它」口径不同。数字可复现、标签误导。
6. **`word_images.query='svg:v2'` 当版本号**是没有约束的约定（§3.2.4 第 3 条），第二期 `hint_safe` 的判定与 `WORD_LIBRARY_CURATION.md` 的内容包导入都要依赖这个字符串；PE 自己列为风险。可接受，但不该沉淀到第二期以后。
7. **初中词的例句规则按词生效、对成人同样生效**（§3.3.2 规则 3 对 stages 含 初中 的词写 4–10 词校园句）。用户 1 学 zk 词时会得到儿童语域例句。按词决定不可避免，但 PE 没有把它列为产品权衡。
8. 第二期把 `image_hint` 列搭阶段模型 0011 的 `user_settings` 重建（§3.5.3）——两条线的回滚被绑死；`AI_FALLBACK_MODEL.md:29` 的「15–240」没有列入同步（EF 列了）。琐碎。

**打分**：fit 6 · correctness 6 · effort_risk 8 · maintainability 6 · evidence 6 · rollout 8 → **overall 6.7**

### 2.3 generation-first（GF）

**长处**
- 生成器作为 `ImageProvider` 进有序链、`split_generator` 切前后段、不加 job 类型、不进 `ai_calls`（§3.6.1）——这是三份里对生成接入**架构最省**的方案，理由（`jobs.type` / `ai_calls.kind` / `0010 provider` 三张表重建换不来功能）成立 `[0001_init.sql:487,511; 0010_ai_provider.sql:9]`。
- `content_filter` → 返回空列表、不触发冷却；`fake_image_gen.py` + `smoke_mock` 两条路由让无 key 的 Mac 能跑到 `wd fetch-image apple --provider ai_image`。
- 回滚分析诚实：承认 0012 之后旧代码的 `ImageMeta.provider` Literal 会让 `/api/words/{id}` 500，给出数据手术步骤。
- `&` 正则只放行 XML 五个命名实体 + 数字引用——最严谨。
- 试点对照表**不显示词头、让评分者先猜词义**（§3.8），是三份里唯一接近「可记性」代理的设计。
- `budget.ESTIMATES["svg"]` 0.03 → 0.015 并同步 `test_budget.py:33`——另两份都漏了预留估算与实测的差距。

**缺陷**
1. **D5 在剥掉模型文字之后再注入 `<text>AI</text>` 角标，自己违反自己的「无文字」。** §3.3 第 4 条、§3.6.8：显式标识同时有 UI 题注（GF 自己的表承认题注就是显式标识）与厂商水印，SVG 里的字母角标并非合规必需；它让 `test_images.py:616` 的 `"<text" in stored` 「恰好仍真」、让 `text_free` 无法再从文件判断，还假设 viewBox 一定是 800×500——而 `sanitize_svg` 会保留模型给出的任何合法 viewBox `[sanitize_svg.py:147]`，角标可能落在画布外。对 6–11 岁学习者，画面里的任何字母都是 D1 准则要去掉的对象。
2. **「ECDICT `pos` 主标签」用的是首位代码。** §2 A1 / §3.8 的 n 179 / v 135 / j 44 与复算的「首位」分布完全一致，与主词性（n 233 / v 89 / j 73）不一致。后果：试点要抽 70 个「动词」，而 497 个小学词里主词性为动词的只有 89 个，抽样会混入大量名词主导的词；§3.5 第 1 项的功能词门若按同样口径实现（首位 ∈ {i,c,p,d,u,t,x}）会误判 `right`、`back` 一类词。
3. **`kid_max_index() = STAGE_ORDER.index("zk") + 1` 在 Q1-b 下错。** §3.2 说三种编码都对；但若 `xs` 插到 `STAGE_ORDER` 开头并映射为 0，`index("zk")+1 == 2`，高中词（`stage_min=2`）会被当成儿童词。应直接用 `schemas.stage_to_index("zk")`（Q1-b 会把它改成显式字典）。
4. **会红名单漏了 `test_images.py:162`**（同 EF），并误判 `test_select.py:92-119` 需「逐行更新」（见 §0 第 7 条）——说明影响分析没有对着夹具跑。
5. **A5 的「加重」与自己的试点设计矛盾。** §2 A5 行拒绝脚本式试点的理由是「200 张图游离在 `word_images` 之外，无法测 UI 题注、标识元数据、举报回路」；但 §3.8 的 `scripts/pilot_images.py` 恰恰「只写自己的 scratch 目录，不激活、不碰线上库」。于是 6 人日的 P2（0012 重建 + `ImageProviderName` / `ImageMeta.kind` / `AdminOverviewWords` / `RefetchImageRequest` 四项契约 + 前端 + 文案镜像）在试点给出任何结论之前就要合入主干，而试点本身并不使用这些。
6. **成人链末尾放生成器**（§1.1 D2 建议 `wikimedia,openverse,ai_image`）：对成人，[image-memorability-6/7] 的结论是「可不配图」；把生成额度、内容过滤风险和标识义务花在 CET 词上，与 GF 自己引用的证据相反（GF 在未决问题 2 里也意识到了）。
7. **`query` 列三义**：照片 = 关键词、SVG = `svg-v2` 版本号、生成图 = 整段中文提示词（≤ 300 字）。同一列按 provider 变含义，没有约束，比 PE 的单一约定更难维护。
8. `quota.status` 只遍历 `cfg.image_providers` `[quota.py:164]`——`ai_image` 只在 KID 链时管理概览不会显示其配额行，§3.6.10「自动把 `ai_image` 作为一行报给 AdminOverview」只在成人链也含它时成立。
9. 文档同步漏项：`AI_FALLBACK_MODEL.md:29`、`WORD_LIBRARY_CURATION.md:65,183` 的 `content-v1` / 「15–240」未列。琐碎。

**打分**：fit 5 · correctness 5 · effort_risk 5 · maintainability 5 · evidence 5 · rollout 5 → **overall 5.0**

---

## 3. 六维评分汇总

| 维度 | evidence-first | pipeline-engineer | generation-first | 评分依据（择要） |
|---|---|---|---|---|
| fit（上海 K-12 + 现有用户） | 6 | 6 | 5 | EF：K-12 思考最多（功能词、儿童安全词表、本土场景），但 `image_hint` 默认对儿童开且方向用反、初中=绘本风；PE：默认关、提示按 H，但生产直接开插画链、初中句式对成人生效；GF：以生成为中心、成人链也生成、角标字母、试点无儿童 |
| correctness（迁移/数据/契约/测试） | 6 | 6 | 5 | EF：功能词×重试打转、漏 `test_images.py:162`、0011 撞号；PE：「无测试绑定」事实错、0 哨兵撞 Q1-b、`category=photograph` 未验证；GF：角标自相矛盾、主标签口径错、`kid_max_index` 在 Q1-b 下错、漏同一测试 |
| effort_risk（高 = 量小险低） | 5 | 8 | 5 | EF 第一期 5 人日且带迁移、第二期 9；PE 第一期 5 人日无迁移/契约/前端、7 个可独立回退提交；GF 第一期 3.5 人日偏乐观（七项照片修补 + `style.py` + `aigc.py`），第二期 6 + 重建 + 四项契约 |
| maintainability（硬编码/镜像负担） | 6 | 6 | 5 | EF：阶段码配置、真列而非约定，但三项契约；PE：整数阈值 + `query` 约定；GF：`query` 三义、两条链配置、`ImageProviderName`/`kind` 同时扩 |
| evidence（与调研证据一致；D1） | 7 | 6 | 5 | EF 映射最全、词性统计正确，但两处误用（image_hint 方向、Adesope & Nesbit）；PE 映射正确、统计标签误导、尺寸门槛无据；GF 引用正确但违反自己的无文字规则、分层口径错 |
| rollout（顺序与回滚） | 6 | 8 | 5 | EF：0011 附加可回滚、0012 重建 + 契约；PE：无迁移、`.env` 兼容分析到位，但把生产当试点；GF：0012 重建与契约先于证据，回滚需数据手术 |
| **overall** | **6.0** | **6.7** | **5.0** | |

**排序：pipeline-engineer > evidence-first > generation-first。**

说明：PE 领先不是因为它最懂小学生，而是因为它的第一期最接近「本周可合并且可逐项回退」，并且在唯一真正触及学习科学的产品决定（图在回忆前还是回忆后）上读对了证据；它的三处事实错误都能在不改架构的前提下修正。EF 的产品洞察最多、证据映射最好，应作为嫁接来源；但它最有野心的一招（`image_hint`）恰好把 D1 用反，且第一期带迁移。GF 的生成接入架构值得保留给第二期，但作为「第一优先」的方案与证据（成人可不配图、6–11 岁无直接实证）和假设 A5（试点、默认关）的精神相悖。

---

## 4. 致命缺陷清单（会导致线上错误、契约破坏、测试红，或违反规则/假设而未说明）

**evidence-first**
1. 测试红：第一期改 Openverse `page_size` 20→10 会让 `backend/tests/integration/test_images.py:162` 的整字典断言红，§5.1 未列。
2. 线上错误（条件性）：与阶段模型同用 0011 编号；`db.list_migration_files` 对重复版本报错 `[db.py:159-161]`，两线同时合入会让 `wd serve` 的 `run_migrations` 失败。EF 已声明顺延，但第一期的「可合并」因此依赖外部顺序。
3. 违反自身证据：`image_hint` 正面出图时英文词头仍在，等于回忆前给答案（[image-memorability-6]、INDEX D1「图不能先于回忆出现」），且默认对儿童用户开启。
4. 资源打转：功能词写 `failed` 后被 `retry_if_failed` / `retry_failed_once` 每日重新入队（243 个初中功能词），没有排除条件。

**pipeline-engineer**
1. 测试红（若按其文字执行）：「§5.5 / §5.1 代码块没有测试绑定」为假，`test_schemas.py:122-127` 逐字节绑定两份提示词；会红名单缺此项。
2. 静默行为错误（Q1-b 下）：`WD_IMAGE_KID_STAGE_MAX=0` 既是「关闭」又满足 `stage_min=0 <= 0`，小学词在「关」的状态下走插画链。
3. 未验证的默认链变更：给默认 Openverse 照片搜索加 `category=photograph`，排除未分类图，却声称「无害」。
4. 违反自身门禁：§6 第 4 步在生产 `.env` 开插画链当「试点」，没有评分表、没有儿童、尺寸门槛 240×180 的模糊图直达用户 2。

**generation-first**
1. 违反 D1 与自身 D5：服务端注入 `<text>AI</text>` 字母角标；角标坐标假设 800×500 而 sanitizer 保留任意合法 viewBox。
2. 口径错误影响试点与规则：「`pos` 主标签」实为首位代码（n 179 / v 135 / j 44 vs 真值 n 233 / v 89 / j 73），分层与功能词门都建立其上。
3. Q1-b 下逻辑错误：`STAGE_ORDER.index("zk") + 1` 在 `xs` 插入后变为 2，高中词被当儿童词；声称「任一编码下都正确」。
4. 测试红：同样漏掉 `test_images.py:162`；并误报 `test_score_table` 需改。
5. 与 A5 精神不符且自相矛盾：第二期在试点之前合入 0012 重建 + 四项契约 + 前端，而理由（试点需落在 `word_images`）与 §3.8「不激活、不碰库」的试点脚本相冲突。

---

## 5. 值得嫁接到最终方案的好点子

1. **PE 的第一期骨架**：7 个独立可回退的零迁移提交；重试带 30 天 ≤ 3 次上限 + `wd images-retry [--dry-run]`；`RELEVANCE_RE`「查询含该词才放行」；会红名单的完整性（`test_images.py:162`、`test_deploy_files.py:119`、`test_docs_contract.py:114`、`test_providers.py:2`）；`.env` 新键的回滚兼容论证；图像提示只在按 H 时出现。
2. **EF 的 K-12 细节**：`WD_IMAGE_KID_STAGES` 用阶段码并经 `stage_to_index` 解析（Q1-a/b 皆安全；GF 的 `kid_max_index` 与 PE 的整数哨兵都应换成它）；`text_free` 作为激活时写入的代码保证属性（不要从 `query` 反推）；儿童安全硬拒词表（beer / wine / knife / horror …）与 kid 风格限定的人像降权；对小学词 lemma 本身豁免 `map/flag/cover/sign/text`；功能词门用**主词性**（复算正确）但去掉 `r`、改为可配置并在试点里单独抽副词验证；`<desc>` 隐式标识；`WD_IMAGE_GEN_WATERMARK` 只允许 1；两用户迁移的 `UPDATE … CASE`；评分表 κ ≥ 0.6 与事先定的采用门槛；`eval_json` 与 `score` 分列；R5 本土场景项。
3. **GF 的生成接入架构（留给第二期）**：生成器作为 `ImageProvider` 进有序链 + `split_generator`，不加 job 类型、不进 `ai_calls`；`content_filter` → 空列表不冷却；`fake_image_gen.py` + `smoke_mock` 路由；只放行五个 XML 命名实体的 `&` 正则；`ESTIMATES["svg"]` 0.03→0.015 同步 `test_budget.py:33`；试点对照表隐藏词头、先猜义再看答案；`aigc.py` 同时写 producer 与 propagator；回滚前把 `ai_image` 行置 `rejected` 的手术步骤。
4. **评审者补充（三份都没有）**：(a) 试点加一个儿童小样本——5–8 名上海小学生（监护人同意），每人看 20 张无词头图「说出意思」，24 小时后再做图→词回忆；这是唯一能碰到「更易记」而不是「更好看」的数据，成本是一两个晚上。(b) 在任何 K-12 邀请之前把「不合适」的共享图废弃阈值从 1 改为 N 个不同用户（`WORD_LIBRARY_CURATION.md:234` 已提议）。(c) 儿童风格默认只给 `xs`（阶段落地后），`zk` 用中性扁平风；在此之前 `WD_IMAGE_KID_STAGES` 默认空。(d) 把模板卡的 K-12 可读性（更大的中文义、去音标、不印例句）列入第一期——那是小学生前两周最常看到的「图」。(e) `images-prune` 对 `stage_min` ∈ 小学/初中的词免删，或在预生成期间停用。

---

## 6. 结论

**建议采用 PE 的第一期为骨架**（修正其三处事实错误：恢复 `test_schemas.py` 的提示词绑定说明与会红项；把 `WD_IMAGE_KID_STAGE_MAX` 换成 EF 的阶段码配置；默认链不加 `category=photograph`；生产 `.env` 不开插画链），**嫁接 EF 的功能词门（主词性、去副词）、`text_free` 列语义、儿童安全词表与 lemma 豁免**，**第二期用 GF 的 provider-in-chain 架构与 fake provider 做智谱试点，但试点先以脚本跑、不合入 0012 与契约**，直到试点（含儿童小样本）给出采用结论。任何「图在正面出现」的玩法在没有「遮住词头的图→词产出模式」之前不要做；初中词不要用六到十二岁绘本风。

排序：**pipeline-engineer（6.7） > evidence-first（6.0） > generation-first（5.0）**。
