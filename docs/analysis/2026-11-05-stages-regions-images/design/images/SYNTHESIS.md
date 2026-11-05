# 配图更易记 · 综合设计（SYNTHESIS）—— 唯一的、已决定的方案

基线：仓库 `/Users/sqin/word-dance` `main @ 75df534`（`git rev-parse --short HEAD` 实测，2026-11-06）；线上库只读副本 `scratchpad/live-copy.db`（`sqlite3 -readonly`，本文引用的每个线上数字都由我重新查过：`schema_migrations` 1/8/9/10；`user_settings` `1|["zk","gk","cet4","cet6"]|3|1`、`2|["zk"]|1|1`；`word_images` 30 张 `claude_svg`（`query` 全 NULL）+ 1 张 `wikimedia`（id 18，词 4259 `election`，516×800）；`image_state` failed 18 / none 9,113 / ready 31；`ai_calls` svg 34 次 $0.4207 = $0.01237/次、829 token、7.9 s；`generate_svg` 34/30/4，被拒任务 45/88/97/136 均为 `not well-formed (invalid token): line 1, column 226/224/402/410`；有内容的 49 词 `stage_min` 3:48 / 1:1；`stage_min=1 AND kind='word'` 2,012 词、1,960 有 `frq`、1 有内容、0 有图；`content_reports` 0 行；无触发器；`v_bank` 只连 `user_words`/`words`）。

输入：`design/images/{evidence-first,pipeline-engineer,generation-first}.md` 与三份评审 `judge-{data-safety,learner-product,maintainer}.md`。读法：`文件:行` 按 75df534 由我重新打开核对；`[INDEX Dn]` 指 `../../INDEX.md` 第 2.D 节；`[image-memorability-N]`、`[images-pipeline-N]`、`[verify images-pipeline ON]`、`[verify image-memorability 遗漏 k]` 指 `../../facts/`、`../../verify/`；`[EF]`/`[PE]`/`[GF]` 指三份设计，`[J-safety]`/`[J-learner]`/`[J-maint]` 指三份评审。本文只做设计，不改任何仓库文件。

裁决原则（三位评审排名不一致：J-safety 与 J-maint 以 evidence-first 为骨架，J-learner 以 pipeline-engineer 为骨架）：**结构性决定取两位以上评审的共识；评审互斥时按「线上错误 > 学习科学证据 > 契约面 > 工作量」排序裁决，并在 §1 每条决定里写明被否决的替代与原因。**

---

## 0. 一页结论

**骨架 = evidence-first（数据用列不用约定、阶段码配置、`text_free`、证据→准则→代码映射、评分表与门槛），嫁接 pipeline-engineer 的工程纪律（8 个可独立回退的提交、默认关闭、重试封顶 + CLI 排练、查询词驱动的黑名单豁免、`query_ignored` 可见化、`.env` 回滚兼容分析）与 generation-first 的生成器架构（provider-in-chain、有序链表达位置、`word_images` 重建 DDL、回滚前置 SQL、fake provider、严格 `&` 正则、隐藏词头的评分表）。** 三份设计一致的公共部分（SVG 无文字 + 裸 `&` 修复、content 第 6/7 条改写、`EXAMPLE_EN_MIN` 15→10、Commons `filetype:drawing` + `thumbmime` + `maxlag`、Openverse `page_size` 10、失败词重试、文档 $0.028→$0.0124/$0.0140、图默认在回忆后、每词一图、生成默认关）全部采纳 [J-learner §1.1]。

**三期，每期一个门：**

| 期 | 门 | 内容 | 契约 | 迁移 | 人日 / 钱 |
|---|---|---|---|---|---|
| 一（本周可合并） | 无：零 key、零前端、零 API 契约 | SVG v2（无文字由代码保证、`&` 修复、`<desc>` 隐式标识、例句 + 挂钩 + 风格段）；content v2（例句义项、小学/初中例句规则、`EXAMPLE_EN_MIN` 10、`content-v2`）；功能词门；黑名单拆分 + 查询词豁免；provider 风格参数（默认链只多 `thumbmime`/`maxlag`/`page_size=10`）；打分新信号；失败词重试（6 h / 30 天 ≤ 3 次 / 夜间 ≤ 50 / `wd images-retry`）；**插画优先链代码就绪、`WD_IMAGE_KID_STAGES` 默认空 = 关**；一次附加迁移 `0012_word_images_meta.sql`（`prompt_version`、`model`、`text_free`、`eval_json`）；文档数字 | 0（`schemas.py`/`types.ts`/`API.md §9` 不动） | 0012（4 条 `ADD COLUMN`） | ≈ 7 人日；$0 新增 |
| 二（试点，需智谱 key + 一台出口正常的机器） | 产品负责人同意跑试点（Q-img-3/6） | `backend/wd/images/providers/ai_image.py` 纯 HTTP 适配器 + `tests/fake_image_gen.py`（可合并、默认不在链中）；`scripts/image_pilot.py`：200 个二级词（n 110 / v 50 / j 20 / r 20）四臂（照片链 / SVG v2 / CogView-3-Flash / 模板卡零点）在线上库私有拷贝上跑、导出到 scratch、隐藏词头的评分页、双评分者 κ ≥ 0.6、预注册门槛；5–8 名小学生看图说义 + 24 h 图→词回忆；可选 GLM-4.6V-Flash 自动评分写 `eval_json` | 0 | 0 | ≈ 4.5 人日 + 儿童样本 1 人日；≈ $3.3（内容 $0.8 + SVG $2.5；CogView / GLM-4.6V 免费） |
| 三（条件合入） | 试点达到 §3.6.4 的预注册门槛 | `ai_image` 进有序链（`WD_IMAGE_PROVIDERS_KID`）、8 个 `WD_IMAGE_GEN_*`/链配置、`0013_word_images_ai_provider.sql` 重建 CHECK、一次契约提交（`ImageProviderName` 提成 `export type` + `ai_image`、`AdminOverviewWords.with_ai_image`、`RefetchImageRequest`）、JPEG XMP/COM 隐式标识、`WD_IMAGE_KID_STAGES` 默认改 `xs` | 1 次（4 个点，同一提交） | 0013（重建） | ≈ 9 人日；CogView-3-Flash ¥0 |

**对评审分歧的五项裁决**：① 第一期**带**一次附加迁移（J-safety 要求 1、J-maint 嫁接 1 vs J-learner/PE 零迁移）——列优于 `query` 约定，且 `db.pending_migrations` 按「未记录即待办」选文件（`backend/wd/db.py:187-189`），与阶段模型的 0011 谁先合入都不会互相卡住；② `zk` **不**划入儿童风格（J-learner），`WD_IMAGE_KID_STAGES` 默认空，试点达标后默认 `xs`；③ **不做** `Settings.image_hint` / 正面出图（J-learner 致命缺陷 3：词头仍在正面，图即答案；J-maint：≥ 13 处契约 + 迁移常量钉死 Q1）——EF 的 D3 第二项与 PE 的「按 H 出图」一并否决，`text_free` 列保留为任何未来「图→词产出模式」的唯一数据门；④ 生成器第二期只做**脚本 + 适配器**试点、第三期才进链与契约（J-learner、J-maint 一致，J-safety 的 0012 DDL / 回滚 SQL 原样嫁接到第三期）；⑤ 功能词门用**主词性**（占比最大的 ECDICT 代码）且**不含副词**（J-learner），副词进试点专门分层，第三期再决定是否加入。

**代价与收益数字**：SVG 单价不变 $0.01237/次，拒收 11.8% → 预期接近 0（4 次拒收全在前 500 字符、与 `<text>` 底部位置不符，裸 `&` 是最可能原因 [verify image-memorability 遗漏 1]，修复 + 提示词双保险）；$0.50/日子额度 ≈ 35–40 张/天；505 个二级词全部 SVG ≈ $6.3，2,099 个初中词 ≈ $26；第一期线上行为变化：仅默认链多三个参数（`thumbmime`、`maxlag=5`、`page_size=10`）、新生成的卡无文字、18 个 failed 词在第一晚最多补抓 17 个。

---

## 1. 决定清单（D-images-1 … D-images-24）

每条：决定 / 理由 / 依据 / 被否决的替代及原因。

**D-images-1 骨架与分期。** 决定：EF 骨架 + PE 提交纪律 + GF 生成器架构；三期，第二期为脚本试点，第三期以预注册门槛为合入条件。理由：J-safety 7.3 与 J-maint 7.2 都把 EF 排第一且原因一致（数字可复核、用列承载语义、A6 写死、红测完整）；J-learner 把 PE 排第一的理由（零迁移、可回退、默认关、按 H 读证据）里，除「零迁移」外全部可以嫁接而不改骨架。依据：三份评审 §0 排名表。否决：纯 PE 骨架——它把版本号塞进 `word_images.query`（`0001_init.sql:250` 注释「image keyword that produced it」受 `docs/SCHEMA.sql` 字节绑定不可改，`backend/tests/unit/test_db.py:362-366`），且 `WD_IMAGE_KID_STAGE_MAX=0` 哨兵在 INDEX Q1-b（小学 = 0）下失效 [J-safety 2.2 缺陷 2]；纯 GF 骨架——为默认关的功能一次铺满四项契约、角标违反自采准则、POS 口径错 [J-learner 2.3]。

**D-images-2 图中无文字由代码保证，不画任何角标。** 决定：`sanitize_svg.clean(svg, *, allow_text=True)`，`store.activate_svg` 以 `allow_text=False` 调用，`<text>/<tspan>` 连子树丢弃，`title`/`desc` 保留；`text_free=1` 只在这条路径写入；服务端**不**注入 `<text>AI</text>`。理由：图在正面出现之前、模板卡与 30 张旧 SVG 都印着词头，「无文字」是「图作提示」的前提 [verify images-pipeline O6]；Boers 2009/2017 配图分走对词形的注意 [image-memorability-8]（**不**引 Adesope & Nesbit 2012——它支持屏幕上的关键词冗余有益，方向相反，J-learner 2.1 缺陷 2）；角标让 `test_images.py:616` 的 `"<text" in stored` 空转、让 `text_free` 无法由文件判断、坐标假设 800×500 而 sanitizer 保留任意合法 viewBox（`sanitize_svg.py:147-149`）。依据：`sanitize_svg.py:28-31,137-166`；`store.py:152-174`。否决：GF D5 角标（显式标识用 UI 题注 `zh.word.aiImage`（`zh.ts:54`）已满足）。

**D-images-3 版本、模型、无文字、评分用四个列承载，不复用 `query`。** 决定：`0012_word_images_meta.sql` 四条 `ALTER TABLE ADD COLUMN`（全文 §3.1.5）。理由：PE 的 `svg:v2` 与 GF 的 `svg-v2` 拼法互不兼容，PE 自己的常量写法前后矛盾 [J-safety 2.2 缺陷 3]；`query` 运行期无读者但语义与 DDL 注释相悖 [J-safety 核验 #31]；`store.activate` 用显式列名 INSERT（`store.py:105-113`）、`service.active_image_row` 用 `SELECT wi.*`（`service.py:44-48`），所以加列对旧代码无害、回滚只需回代码 [J-safety 核验 #10/#11]。依据：`0010_ai_provider.sql:9` 的 `ADD COLUMN … NOT NULL DEFAULT … CHECK` 先例。否决：PE/GF 的 `query` 约定（已述）；把四列推迟到第二期重建（EF 原案）——第一期就要写 `prompt_version`/`text_free`，否则一期生成的「新卡」与旧卡仍不可区分。

**D-images-4 迁移编号 0012 / 0013，不依赖与阶段模型的合入顺序。** 决定：第一期 `0012_word_images_meta.sql`，第三期 `0013_word_images_ai_provider.sql`；0011 留给阶段模型（`scratchpad/design-stage-model-minimal/0011_primary_stage.sql` 已存在，重建 `words`/`user_settings`，不碰 `word_images`）。理由：`db.list_migration_files` 只要求编号唯一、不要求连续（`db.py:159-172`），`pending_migrations` 取「文件里有、`schema_migrations` 里没有」的全部文件（`:187-189`），所以 0012 先于 0011 合入时 0011 之后仍会被应用；唯一副作用是快照文件名 `pre-migrate-12-to-11.db.gz`（`from_version`/`to_version` 取 max，`:202-205`），可接受。依据：J-safety 核验 #28、要求 1；J-maint 1.1 △。否决：EF/PE 的「先写 0011，撞号再顺延」——顺延几乎必然，且两线同编号会让 `run_migrations` 直接抛 `duplicate migration version`（`db.py:169-170`）。

**D-images-5 风格由词的阶段码集合决定；默认关；`zk` 不是儿童风格。** 决定：`Settings.image_kid_stages: tuple[str, ...] = ()`（`WD_IMAGE_KID_STAGES`，逗号分隔阶段码，空 = 关），`from_env` 用函数级 `from .schemas import STAGE_ORDER` 校验未知码抛 `ConfigError`；`images/style.py:style_for(word, cfg)` 返回 `"kid"`/`"neutral"`，`stage_min` 经 `style.stage_code()` 转码（整数索引 → `schemas.index_to_stage`，字符串码原样）；`kid` 驱动 SVG 的 Style 段与「插画优先」第一轮；试点达标后默认改 `("xs",)`，`zk` 永远不在默认里。理由：三位评审一致要求默认关（J-safety 要求 3、J-learner 嫁接 4(c)、J-maint 3）；Tonzar 2009 的八年级组支持「初中生从图受益」，不支持「六到十二岁绘本风」[image-memorability-7]，初中生对幼稚画风的排斥没有任何一份设计当作风险 [J-learner 1.2]；阶段码 + `stage_to_index` 对 Q1 的 a/b/c 三种编码都正确 [J-safety 横向对比]。依据：`schemas.py:51,57-67`；`config.py:355-363`（`WD_IMAGE_PROVIDERS` 未知值的 `ConfigError` 先例）。否决：EF 默认 `("zk",)`（试点前铺开 2,099 词 [J-safety 2.1 缺陷 1]）；PE `WD_IMAGE_KID_STAGE_MAX` 整数哨兵（Q1-b 下 `0 <= 0`）；GF `STAGE_ORDER.index("zk")+1`（`xs` 插入后高中词被当儿童词 [J-learner 2.3 缺陷 3]）。

**D-images-6 SVG 提示词 v2 与用户提示词。** 决定：系统提示词整体替换（全文 §3.1.1）：无文字、单一主体、素净背景、画例句义项、抽象词画挂钩、Style 行、`&amp;` 要求、禁用 `text`/`tspan`；用户提示词带 `Scene`（`image_alt_zh`）、`Example sentence`（`examples[0].en` ≤ 120）、`Memory hook`（`mnemonic_zh` 中以「联想：」开头的句子 ≤ 60）、`Style`（`STYLE_KID_TEXT` / `STYLE_NEUTRAL_TEXT`）；`SVG_PROMPT_VERSION = "svg-v2"` 写入 `word_images.prompt_version`。理由：风格段必须在用户提示词里——一次调用只加载一份系统提示词且 `lru_cache`（`runner.py:100-103`）；例句 + 挂钩是现有内容里已有但 `prompt_for` 没用的信息（`svg.py:48-52` 只取 `image_alt_zh`/`meaning_zh`）[D1 准则 4/5]。依据：Lotto & de Groot 学/测一致 [image-memorability-7]、Attygalle 2025 [11]、Flack & Horst 一次一图 [13]、Nelson 相似性反转 [1]。否决：PE 的「prefer leaving title/desc empty」——`<desc>` 是我们自己的隐式标识载体（D-images-17）；GF 的三处小改（不够具体，缺例句与挂钩）。

**D-images-7 清洗三处改动。** 决定：① `_parse` 在 `DET.fromstring` 前 `BARE_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")` → `&amp;`（只放行 XML 五个命名实体与数字引用，GF 的正则）；② `clean(svg, *, allow_text=True)`；③ `with_label(cleaned, label) -> str` 在根开标签后插入 `<desc id="aigc-label">{escape(label)}</desc>`，`svg.py` 以 `len(BARE_AMP_RE.findall(svg))` 记日志事件 `svg_repaired`。理由：EF 的正则会放行 `&nbsp;` 这类 HTML 实体仍被 XML 拒 [J-learner 2.1 缺陷 7]；`ENTITY_RE` 的拒绝在前（`sanitize_svg.py:67-68`）修复不会放行实体声明；`test_sanitize_svg.py:158-170` 的 `A &amp; B` 经负向前瞻不变。依据：`sanitize_svg.py:65-79`；4 次拒收位置 column 224–410 [images-pipeline-21]。否决：GF 的 `<metadata>`（不在白名单，子元素外命名空间会被丢）。

**D-images-8 content 提示词 v2 与两个常量。** 决定：规则 6/7 改写为「例句 1 的同一场景、单一主体、无文字无人脸特写、抽象词对齐 `mnemonic_zh`、功能词/无场景词给裸 lemma」；规则 3 追加小学（4–8 词、现在时、校园/家庭/操场、原形 ≥ 2 句）与初中（6–12 词、校园与日常、无职场/新闻语域）；规则 1 追加小学白话释义（保留词性标签）；规则 5 追加小学优先「联想：」；`EXAMPLE_EN_MIN` 15→10；`PROMPT_VERSION = "content-v2"`；`PREFIX_MIN` 不动；**不加** `image_scene_en`；49 张旧卡不 `force`。理由：`EXAMPLE_EN_MIN=15` 会丢「I like cats.」（12）[INDEX D6]；线上 195 条例句最短 33 字符，降到 10 对已有内容零影响 [verify ai-prompts-stages-5]；`PROMPT_VERSION` 提升不会让任何 ready 词重新入队（`bank.py:489-492`、`prewarm.py:48`、`content.py:405` 只对有任务的词比较）[ai-prompts-stages-10]；`image_scene_en` 要改 schema 文件 + §4.1 代码块 + fixture 三方逐字节同步（`test_schemas.py:56-62`）共 10 处 [EF 3.2.4]，智谱 CogView 中文原生，`image_alt_zh` 就是场景。依据：`content_system.txt:4,6,8,9,10`；`content.py:46,54,63`。否决：PE 规则 3 的「阶段含初中及以下 4–10 词」把小学与初中合并（初中 4–10 词过短）；放宽 `PREFIX_MIN`（260 个无屈折行的 zk 词几乎全是功能词 [verify ai-prompts-stages-11]）。权衡声明：初中规则按**词**生效，用户 1（成人）学 zk 词时也会得到校园语域例句 [J-learner 2.2 缺陷 7]——接受，见 Q-img-7。

**D-images-9 功能词门：主词性 ∈ {i,c,d,p,a,u,t} → 卡片；副词不在门内但不搜裸 lemma。** 决定：`style.dominant_pos(pos)` 取 ECDICT `pos` 串中占比最大的代码（`n:4/v:96` → `v`）；`FUNCTION_POS = frozenset({"i","c","d","p","a","u","t"})`（介词、连词、限定词、代词、冠词、感叹词、不定式标记；码表与 `frontend/src/utils/pos.ts:8-21` 一致，**无** `x`）；`skip_image()` 为真且无管理员 `provider`/`query` → `image_state='failed'`、`FetchOutcome(STATUS_SKIPPED, detail="function word: card only")`，不发 provider 请求、不入队 SVG；`r`（副词）加入 `NO_BARE_LEMMA_POS`：无可用内容关键词时不搜裸 lemma，SVG 仍允许。理由：我在副本上重算（`scratchpad/synth-images/pos_stats.py`，`python3 -I`，`?mode=ro`）：`stage_min=1` 的 2,099 词主词性 n 1,043 / v 361 / j 301 / r 105 / 无 100 / m 50 / i 40 / p 40 / d 22 / c 19 / a 11 / u 6 / t 1——与 EF §3.0 及三位评审的复算逐项一致；门含副词覆盖 243 词、不含副词 138 词；`data/lists/moe-2022-level2.txt` 505 词在库 498，主词性 n 233 / v 89 / j 73 / r 31 / i 19 / p 13 / d 12 / a 10 / c 7 / 无 4 / u 4 / m 2 / t 1，门含副词 96、不含 65；505 词的 31 个副词里 `fast / up / down / back / today / tomorrow / yesterday / here / out / off / far / now / again / always / sometimes` 可画，`please / ok / not / so / too / very / why / how` 不可画——按词性一刀切会错一半，所以副词交给试点分层（D-images-18）与内容提示词「无自然场景给裸 lemma」的信号。依据：J-learner 2.1 缺陷 4、嫁接 2；[image-memorability-3] 具体性最强预测量；线上反例 `despite`（i）/`particularly`、`directly`、`suddenly`（r）[image-memorability-16]。否决：EF `FUNCTION_POS` 含 `r`（规则永远测不到）；PE「功能词码合计 ≥ 80%」（统计口径与规则口径不一致，命中 119–120 词而非 207 [J-safety 核验 #27]）；GF 首位代码口径（`pos` 不按占比排序 [J-learner 2.3 缺陷 2]）；做成环境变量（没人会翻的开关，多一行 env.example/DEPLOY 门禁）。

**D-images-10 黑名单三分 + 查询词驱动豁免。** 决定：`UNSAFE_RE`（`nude|nudity|sex|porn|gore|blood|weapon|gun|corpse`，永拒）、`NON_PHOTO_RE`（`map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document`，命中词是**查询本身的 token** 时放行）、`KID_UNSAFE_RE`（`beer|wine|alcohol|cigarette(s)|smoking|horror|zombie(s)|skull(s)|knife|knives|bikini|lingerie`，`style="kid"` 硬拒）；`is_blocked(text, *, allow=frozenset(), style="neutral")`；`handler.clean_keywords` 与 `content.validate_item` 都传 `allow=select.keyword_tokens(lemma)`，`select.rank` 传 `allow=keyword_tokens(kw)`。理由：`map / flag / cover / sign / text / chart / blood / gun` 都是 `stage_min=1` 的词（副本实查），否则这些小学词永远拿不到一张真正的地图/旗帜 [EF 3.3.4]；查询 token 豁免比 lemma 豁免更通用（查 `world map` 放行 `map`，查 `apple` 仍拒 [J-maint 1.2 嫁接]）；`blood`/`gun` 留在 `UNSAFE`：儿童向不要真实照片，SVG 扁平插画即可（`weapon` 的 SVG 并非黑名单造成 [verify images-pipeline-9]）。依据：`select.py:20-24,40-42,54-77`；`handler.py:64-78`；`content.py:66-68,174-184`；现有儿童向安全控制只有 Openverse `mature=false`、Pixabay `safesearch` [verify ai-prompts-stages 遗漏 3]。否决：PE 把 `blood|weapon|gun` 放进「查询含该词时放行」的 `RELEVANCE_RE`（儿童向不放行）。

**D-images-11 provider 风格参数：默认链形状不变。** 决定：`ImageProvider.search(self, query, limit, *, style: str = "neutral")`；Commons：kid 轮 `filetype:drawing`、`iiprop` 加 `thumbmime`、候选 `mime` 取 `thumbmime` 优先、加 `maxlag=5`、`error.code=="maxlag"` → `ProviderError(status=503, retry_after_s=Retry-After or 30)`；Openverse：`page_size=max(1, min(limit, 20))`（=10）、kid 轮加 `category=illustration`、`extra["category"]`；Pixabay：kid 轮 `image_type=illustration`；Pexels：签名透传；**默认（neutral）轮不加 `category=photograph`、不加 `orientation`**；`priority ≥ 90` 跳过扩展到 `pixabay`/`pexels`；尺寸门槛 400×300 **不**放宽。理由：`category=photograph` 排除未分类图，是默认链召回的收窄而非「无害参数」[J-learner 2.2 缺陷 3；J-safety 2.2 缺陷 4]；Commons 把 SVG 光栅化为 PNG `thumburl` 但原 `mime=image/svg+xml` 会被 `select.py:65-66` 拒 [verify images-pipeline-31]；`maxlag` 是 API 礼仪 [images-pipeline-46]，MediaWiki 以 200 + `error` 体应答，`base.get_json` 只对 ≥ 400 抛错（`base.py:100-118`）；每次取 20 只用 10 [verify images-pipeline O2]；Pixabay「Systematic mass downloads are not allowed」[verify images-pipeline O3]。否决：PE/GF 放宽插画尺寸到 240×180 / 300×200（DPR 2–3 屏上模糊 [J-learner 2.2 缺陷 4]；GF 的放宽只对带 `category` 的 Openverse 生效、对 Commons 无效 [J-maint 1.3 △]）——改为试点预注册规则：kid 轮中 Openverse 因 `size` 被拒且两边 ≥ 300×200 的候选占该轮拒绝 ≥ 30% 时，第三期加 `MIN_SIZE_KID = (300, 200)`。

**D-images-12 打分新信号（纯字符串，无新依赖）。** 决定：`score(cand, keyword, *, used_refs=(), style="neutral")` 加：任一关键词 token 命中 `extra.description`/`object_name` → +1（上限 1）；Openverse `extra.category` / Pixabay `extra.type` 与本轮目标一致 +1、相反 −1（kid 目标 `illustration`/`vector`，neutral 目标 `photograph`/`photo`，缺失 0）；`PEOPLE_RE`（`portrait|portraits|selfie|selfies|headshot|close-?up|face|faces|people|person|man|woman|boy|girl`）命中 title/tags → kid −2、neutral 0；`TEXTY_RE`（`sign|signs|signage|caption|captions|typography|infographic|inscription|banner|banners|label|labels`）→ −1；`aspect < 1.0` → −1。`MIN_SCORE=1` 不变。理由：`test_select.py:92-119` 全表仍成立——默认 `cand()` 无 `description`、宽高比 ≥ 1.0（800×800 恰为 1.0）、标题无人像/标牌词 [J-learner §0 第 7 条]；16:10 `cover` 对竖图只剩 ≈ 40% [verify images-pipeline-11]。依据：`select.py:80-101`；[images-pipeline-32]。否决：EF 的 description 并入 haystack 封顶 +3（描述长文易刷分）、人像 −2 对成人也生效（Pixabay/Pexels 条款只限制「真人负面呈现」，与风格无关）；GF「`test_score_table` 需逐行更新」（不成立）。

**D-images-13 失败词自动重试：PE 的封顶 + 排除功能词。** 决定：`images/service.py` 新增 `RETRY_MIN_AGE_H = 6`、`RETRY_MAX_AUTO_30D = 3`、`RETRY_NIGHTLY_LIMIT = 50`、`RETRY_NIGHTLY_PRIORITY = 30`；`retry_due(conn, word, now)` = `image_state=='failed'` ∧ `not style.skip_image(word)` ∧ 无 live `image:<id>` 任务 ∧ 上次 `fetch_image` 结束 ≥ 6 h（或无记录）∧ 30 天内 `payload.retry=true` 的任务 < 3；`retry_if_failed(conn, word, *, priority, now)`；`retry_failed_studied(conn, now, *, limit, priority, dry_run=False)`；`enqueue_fetch(..., retry: bool = False)` 写 `payload["retry"]=true`；挂点 `bank.py:636,659`、`batches.py:352-362`（SELECT 加 `pos, image_state`）与 `:639`、`scheduler.maintenance`（`prefetch` 之后，`TickResult.image_retries`）；CLI `wd images-retry [--limit N] [--dry-run]`。理由：18 个 failed 词里 17 个正在被学却永远不再抓图 [images-pipeline-25/28]，11-03 的 30 个任务 26 个因冷却连请求都没发 [verify images-pipeline O9]；EF 无封顶 + 功能词置 `failed` → 243 个功能词每晚占满 50 个名额 [J-safety 2.1 缺陷 2；J-learner 2.1 缺陷 3]。依据：`jobs` 列 `dedupe_key`/`payload_json`/`finished_at`/`updated_at`/`created_at`（`0001_init.sql:485-504`）；`service.enqueue_fetch:155-183`；`queue` 去重键 `image:<id>` / `image:<id>:r<n>`（`service.py:24-25`）。否决：EF 1 天最小间隔（冷却只有 10–15 分钟，6 h 足够）；GF 24 h 无封顶。

**D-images-14 图在回忆之后；不做 `image_hint`、不做正面出图。** 决定：`StudyCard` 正面不出图（现状 `StudyCard.tsx:201-228` 只有 `WordHeader` + 挖空提示），背面出图（`:302-310`）；**不**加 `Settings.image_hint`、**不**加 `user_settings.image_hint`、**不**改 `onboarding`；`text_free` 列保留为未来「图→词产出模式」（正面只出图、隐藏词头、学习者产出英文词再翻面）的唯一数据门，该模式是新学习模式而非开关，列入 Q-img-2。理由：正面始终渲染 `WordHeader`（`StudyCard.tsx:205`），任何「正面加图」对具体名词（小学词 47% 是名词）就是在回忆前给答案，正是 Carpenter & Olson 的过度自信场景 [image-memorability-6]；Tonzar 的 picture-based method 是遮住词、看图产出 L2 词，方向相反 [J-learner 2.1 缺陷 1]；按 H 出图同样是在词头可见时出图，只是把答案延迟到按键——与挖空例句提示不同，图对具体词的泄露是完全的。依据：J-learner 4（EF 致命缺陷 3）、6；J-maint 1.1（契约 ≥ 13 处、迁移 CASE 钉死 Q1）。否决：EF 3.5.1 第 2 项（默认对儿童开）；PE 3.6 的「按 H 显示、只对 `hint_safe`」。

**D-images-15 每词一图、`show_images` 全局布尔不变、A6 对本线无数据影响。** 决定：不改 `ux_word_images_active`（`0001_init.sql:272`）、不加 `audience`/`style` 列、不按用户选图；用户 1/2 的设置不迁移（本线不再有用户设置列）。理由：「成人看儿童插画会受损」无任何证据 [EF 1.2]；默认 `WD_IMAGE_KID_STAGES` 空、试点后只含 `xs`，用户 1（zk–cet6）与用户 2（zk）学的词都不会被画成绘本风。依据：[images-pipeline-33] 多图代价；三份设计一致。否决：GF/PE 的第三期 `(word_id, style)` 唯一索引（无需求）。

**D-images-16 生成式位图：第二期脚本试点、第三期 provider-in-chain。** 决定：第二期合入 `backend/wd/images/providers/ai_image.py`（`AiImageProvider.generate(prompt, *, size) -> Generated`，智谱 `POST {base}/images/generations` 形状，**不**实现 `ImageProvider.search`，不进 `PROVIDER_CLASSES`，无配置字段、无迁移）+ `backend/tests/fake_image_gen.py`；试点脚本直接用适配器；第三期按 GF 架构接入：provider 名 `ai_image`（通用名）、`WD_IMAGE_PROVIDERS_KID` 有序链表达位置（空 = `WD_IMAGE_PROVIDERS` 去掉 `pexels`）、handler 在链中遇到 `AiImageProvider` 走 `_generate_round`、`content_filter > 0` → 空结果不冷却、不新增 `jobs.type`、不进 `ai_calls`、计数走 `provider_usage`（表无 provider CHECK，`0001_init.sql:534-549`）、`quota.limits_for("ai_image")`、`quota.status` 遍历两条链的并集、`kind` 仍为 `photo`（位图 `cover` 渲染）而由 `provider` 区分题注、`photo_mix` 加 `with_ai_image`。理由：J-learner 2.3 缺陷 5（GF 的「试点需落库」与自己的脚本试点矛盾）、J-maint 1.3（为默认关功能铺满契约）；GF 的架构理由成立（`jobs.type` CHECK `0001_init.sql:487`、`ai_calls.kind` CHECK `:511`、0010 的 provider CHECK 三张表重建换不来功能）；`generated` 许可被 `base.license_allowed` 硬拒（`base.py:203-205`）所以必须绕过 `select.rank`。依据：[image-memorability-26]（接口形状、免费、水印默认开、URL 30 天、`content_filter` 0–3）；`quota.py:160-179` 只遍历 `cfg.image_providers`（J-safety 核验 #15）。否决：EF `gen` 名 + `WD_IMAGE_GEN_POSITION` 枚举（链位置本身就是机制 [J-maint 1.3]）；GF 三方言表（本机一把 key 都没有，目标只有智谱）；GF `kind='ai'`（二分变三分，`WordImage.tsx:50` 的 `kind !== 'photo'` 判断全要改）。

**D-images-17 标识合规：显式 = UI 题注 + 厂商水印；隐式 = `<desc>`（SVG）/ XMP + COM（JPEG，第三期）。** 决定：`store.activate_svg` 在 `clean(allow_text=False)` 之后、`write_bytes` 之前 `with_label(cleaned, f"AI-generated illustration · word-Dance · {model} · {now[:10]}")`；第三期 `fetch.normalise_image(data, max_edge, *, label: AigcLabel | None = None)` 对 `ai_image` 写 `xmp=`（自定义命名空间 `wd:aigc`：`generated=true`、`producer`、`model`、`propagator`、`contentId`、`createdAt`）与 `comment=b"AI-generated image"`（Pillow 12.3.0 `JpegImagePlugin._save` 读 `xmp`/`comment`，本机 `.venv` 实测）；`watermark_enabled` 固定 `true`（无配置项）；字段名与 GB 45438-2025 的对应、本应用的主体定性列为 Q-img-4。理由：《人工智能生成合成内容标识办法》要求显式 + 文件元数据隐式标识 [verify image-memorability 遗漏 4]；重编码为 JPEG q82 会丢掉智谱的隐式数字水印（`fetch.py:241-268`），所以必须在这一步补写自己的；智谱协议禁止消除其标识 [image-memorability-26]，是否构成「消除」需法务判断。依据：`sanitize_svg.py:29`（`desc` 在白名单）。否决：GF 角标（D-images-2）；EF 的 `WD_IMAGE_GEN_WATERMARK` 配置项（只允许 1 的配置项就不该存在）。

**D-images-18 评估：四臂 + 隐藏词头 + 预注册门槛 + 儿童小样本 + 副词分层。** 决定：样本框 `data/lists/moe-2022-level2.txt` ∩ 现库（498）去掉 `FUNCTION_POS`（65）→ 433；分层按**主词性**抽 n 110 / v 50 / j 20 / r 20 = 200，每层按 `frq` 升序等距；臂 A 照片链（kid 轮 + neutral 轮）、B SVG v2、C CogView-3-Flash、D 模板卡零点；每臂在线上库的独立 `VACUUM INTO` 拷贝上跑，产物导出到 scratch；评分页隐藏词头、评分者先写猜到的词义再翻看答案；R1–R5 各 0–2，两名成人评分者，Cohen κ ≥ 0.6 才采信；门槛见 §3.6.4；另加 5–8 名上海三至五年级小学生（监护人同意）看图说义 + 24 h 图→词回忆；副词 20 词单独报告。理由：三份设计的试点都只量「评分者眼中的图片质量」，没有一个真实小学生看过一张图 [J-learner 1.2]；GF 的「先猜后翻」是三份里唯一接近可记性的代理 [J-learner 2.3 长处]；EF 的 κ 与事先门槛 [J-maint 1.1 嫁接]；抽样必须按占比最大代码而非首位 token [J-maint 3.5]。依据：`words.pos` 格式 `n:4/v:96`（`0001_init.sql:174`、`pos.ts:1-3`）；505 词只有 1 个有内容 [images-pipeline-28 口径]。否决：GF 名词 100 / 动词 70 / 形容词 30（主词性为动词的只有 89 个，抽 70 会混入名词主导词 [J-learner 2.3 缺陷 2]）。

**D-images-19 文档数字与 `ESTIMATES["svg"]`。** 决定：`$0.028/张` → `$0.0124/次调用（$0.0140/张交付，拒收 11.8%，2026-11-05 实测 34 次）`，`≈ 18 cards/day` → `≈ 35–40 cards/day`，九处：`docs/DESIGN.md:28,518,550`、`docs/CLAUDE_INTEGRATION.md:407,416`、`docs/DEPLOY.md:326,434`、`docs/ops.md:198`、`deploy/env.example:83`、`backend/wd/ai/budget.py:273`（注释）；`budget.ESTIMATES["svg"]` 保持 `0.03`。理由：估算值用于预留与日预算预检（`budget.py:268-278`），减半意味着接近上限时放过更多 SVG 任务，是行为变化不是文档数字 [J-maint 1.3 △]。否决：GF 0.03 → 0.015（`test_budget.py:33` 跟着改）。

**D-images-20 契约面：一、二期零契约；三期一次提交并修门禁。** 决定：一、二期不碰 `schemas.py` 的 DTO、`types.ts`、`API.md §9`、`FRONTEND.md §8`；第三期一次「contract change」提交：`types.ts` 把 `ImageMeta.provider` 的内联字面量提成 `export type ImageProviderName = …`（`API.md §9` 同步，让 `check_contract.py` 的联合比对真正覆盖它）、加 `'ai_image'`（顺序 `…,'claude_svg','ai_image','card_svg'`，与 `schemas.py:46` 一致）、`AdminOverview.words.with_ai_image`、`RefetchProvider`；同提交清理 provider 硬编码（≥ 14 处，含 `ledger.py:24 PHOTO_PROVIDERS_SQL` 死常量删除、`scripts/smoke.py:624` 不变式）。理由：`check_contract.parse_types_ts` 只把 `export type X = 'a' | 'b';` 收进 `unions`（`check_contract.py:160-170`），`compare_shape` 只比属性名（`:222-247`），所以今天后端加值而 `types.ts:84` 不加会静默漂移 [J-maint 0.2]；一、二期不动 `types.ts`/`API.md` 也避免与阶段模型线在同一文件（`Stage` 字面量 `types.ts:5`）上冲突。依据：`schemas.py:46,1098,1350`；`types.ts:84,185-186`；`endpoints.ts:340`；`API.md:231,318,420-421`。否决：三份都写的「`check_contract.py:274-281` 顺序敏感比对要求同提交」（对内联字面量不成立）。

**D-images-21 旧卡不重画、失败词交给重试、唯一照片不动。** 决定：30 张旧 SVG（全部四级词，`stage_min` 3:48 / 1:1 的内容分布）保留，`prompt_version IS NULL`、`text_free=0`；18 个 failed 词由 D-images-13 覆盖（`employee` 不在学，保持卡片）；`election` 照片不动；管理员要重画走现有 `POST /api/admin/words/{id}/refetch-image {provider:"claude_svg"}`（`admin_ops.py:414-427`）。理由：对成人的证据是「可不配图」[image-memorability-7]，$0.42 的重画收益最低。依据：INDEX Q9 建议；三份设计一致。

**D-images-22 第一期切成 8 个可独立回退的提交，顺序固定。** C1 文档数字 → C2 迁移 0012 + 测试 → C3 SVG v2（提示词 + §5.5 + sanitizer + `store.activate_svg` + `svg.py` + `style.py` + `WD_IMAGE_KID_STAGES` + env/DEPLOY）→ C4 content v2 → C5 搜索词（功能词门、黑名单三分、`query_ignored`）→ C6 打分信号 → C7 重试 → C8 provider 风格参数与插画优先轮（最大、默认关、最后）。理由：PE 的合并顺序「纯文档先、默认关的大改动最后」[J-safety 2.2 嫁接]；C3 依赖 C2 的列与 `style.py`，C8 依赖 `style.py`。

**D-images-23 `images-prune` 与举报阈值不在本线改。** 决定：`handler.prune_unused`（`handler.py:298-331`）行为不变，只在 `docs/ops.md:202` 加一句「重试规则会让正在被学的词重新抓图；预生成期间不要跑 prune」；「不合适」阈值 1 → N 个不同用户归 `docs/WORD_LIBRARY_CURATION.md` 阶段 C（`:234`）。理由：本线不做全库预抓（D-images-11 的 Pixabay 条款、Openverse 配额）；阈值是词库治理问题。依据：[verify images-pipeline O7]；[images-pipeline-23]。

**D-images-24 试点与统计一律按「占比最大的 pos 代码」口径，脚本只读。** 决定：所有词性统计、样本分层、功能词门都用 `style.dominant_pos()` 同一函数；试点脚本以 `python3 -I`/`.venv/bin/python` 对 `?mode=ro` 或 `VACUUM INTO` 拷贝工作，永不写 `/Users/sqin/word-dance-data`。依据：J-maint 3.5；本文件头的读写规则。

---

## 2. 对照假设 A1–A6 的偏离与理由

| 假设 | 本设计 | 偏离 | 理由 |
|---|---|---|---|
| A1 小学 = 国家 2022 二级 505 词骨架 | 采用：试点样本框 = `data/lists/moe-2022-level2.txt`（词表任务已交付，505 行，在库 498——`a`/`an`、`mr.`/`mrs.` 等书写差由词表线裁决）∩ 现库 | 否 | 配图只读 `words.stage_min`/`pos`，不依赖 Q2 的最终拍板 |
| A2 初中/高中词表 | 不涉及 | 否 | 同上 |
| A3 许可姿态 | 不涉及词表；图片许可白名单不变（`base.py:184-205`）；`ai_image` 的 `license='generated'` 沿用 `claude_svg` 取值（`0001_init.sql:256` 注释、`store.py:165`） | 否 | — |
| A4 不按省份分层 | 风格由词的阶段码决定，不按地区、不按用户；不做「上海/全国」双图 | 否 | D-images-5/15 |
| A5 先改提示词与抓取链；位图生成可配置、默认关 | 采用并加码三处：① 「无文字」由代码保证（D-images-2）；② 「插画优先链」也默认关（`WD_IMAGE_KID_STAGES` 默认空），不只是生成器默认关；③ 生成器第二期只做脚本试点，第三期才可配置 | 轻微（比 A5 更保守） | 剪贴画质量与 Commons `drawing` 命中率在 200 词试点前不可知 [verify image-memorability 遗漏 5；verify images-pipeline-31]；三位评审一致 |
| A6 新用户默认 K-12；现有 2 用户迁移规则写死 | 本线不再有任何用户设置列（D-images-14），对 A6 无数据影响；`WD_IMAGE_KID_STAGES` 是部署配置不是用户设置 | 否 | 用户 1/2 的 `current_stage` 重编号由阶段模型线的 0011 处理 |
| INDEX Q7 建议 | a 全做（去文字、构图、`&`）+ 失败词重试 + `query_ignored`；c 代码就绪、配置关闭；b 第二期试点、第三期条件合入 | 否 | — |
| INDEX Q9 | `EXAMPLE_EN_MIN` 10、旧卡不动、`PREFIX_MIN` 不动；白话释义只对小学词（规则 1 追加） | 否 | — |

---

## 3. 详细设计

### 3.0 证据 → 准则 → 代码落点

| 准则（[INDEX D1]） | 证据（对象年龄）/ 效应量 | 落点（期） |
|---|---|---|
| 单一清晰所指 | Flack & Horst 2018（3.5 岁）一次一图学到两倍词 [13]；Nelson 1976 相似性反转 [1] | `svg_system.txt` 构图段；`content_system.txt` 第 6/7 条；`select.score` 人像/竖图/标牌降权（一） |
| 图中无文字 | Boers 2009/2017（成人）[8]；现状 SVG 与模板卡印词头 [verify images-pipeline O6] | `clean(allow_text=False)` + `text_free`（一）；模板卡永不作提示（一） |
| 去无关细节 | 诱人细节 g ≈ −0.33（58 项，二手）[12]；Kaminski & Sloutsky 2013（6–8 岁）[13] | 提示词「plain single-colour background, no clutter」（一）；生成提示词「不要」段（三） |
| 画例句用到的义项 | Lotto & de Groot 1998 学/测一致（成人，间接）[7]；直接实证缺失 [15] | `svg.build_user_prompt` 带例句 1（一）；规则 6/7「与例句 1 同一义项」；查询词只来自 `image_keywords`（一） |
| 抽象词用与 `mnemonic_zh` 对齐的挂钩 | 关键词法 [10]；Attygalle 2025（效应量未给）[11] | 用户提示词 `Memory hook:`（一）；规则 7（一） |
| 风格一致、构图各异 | Nelson 1976 [1] | 固定 Style 行 + 「vary the composition」（一） |
| 图作提示而非答案 | Carpenter & Olson 2012（成人）[6]；Tonzar 2009 四/八年级 picture-based = 遮词看图产出 [7] | 图只在背面（现状）；`text_free` 为未来图→词模式的门（一）；不做正面出图（D-images-14） |
| 儿童 vs 成人差异化 | Tonzar 2009 / Lotto & de Groot 1998 [7]；Defeyter 2009 7 岁组限时反转 [2] | `style.style_for()`（一，默认关）；`xs` 才是儿童风格（D-images-5） |
| 具体性门槛（宁可不配图） | de Groot & Keijzer 2000 [3]；线上反例 `despite/particularly/directly/suddenly` [16] | `style.skip_image()`（一）；副词不搜裸 lemma + 试点分层（一/二） |
| 高图标性 | Ganea 2008（婴幼儿，外推低）[14] | 提示词「clearly recognisable, not a symbol」（一）；试点 R1（二） |

### 3.1 Claude SVG 路径

#### 3.1.1 系统提示词 v2（`backend/wd/ai/prompts/svg_system.txt` 整体替换；`docs/CLAUDE_INTEGRATION.md:281-283` §5.5 代码块逐字节同步，否则 `backend/tests/unit/test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5[svg_system]` 红；首字符必须是字母 `:127`）

```
Produce a simple, flat-style educational illustration as a single SVG string for the given English word, so that a learner who sees the picture alone can recall the word's meaning. The picture is a memory cue, not a caption: it must contain NO text of any kind — no letters, digits, words, labels, signs, speech bubbles or captions — and must not spell or hint at the word typographically.
Composition: exactly ONE clearly recognisable central subject (or one simple interaction between two subjects when the Scene says so) on a plain, light, single-colour background; no decorative clutter, borders, frames or patterns; 3–5 harmonious flat colours and large simple shapes; the subject fills at least half of the canvas. Draw the Scene given in the user prompt — the sense used in the example sentence — never a different sense of the word. For an abstract word draw the concrete Memory hook given in the user prompt, not a symbolic diagram. Simple stylised figures are fine, but do not draw human faces in detail. Nothing frightening, violent, romantic or sexual.
Follow the Style line of the user prompt and vary the composition from picture to picture.
Technical constraints: viewBox="0 0 800 500"; use only these elements: svg g rect circle ellipse line polyline polygon path defs linearGradient radialGradient stop title desc; no <text>, no <tspan>, no <script>, no <foreignObject>, no <image>, no <use>, no external references (href, xlink:href, url(...)), no event attributes, no CSS; the SVG must be well-formed XML — write & as &amp; and never put a bare < or & inside attribute values, <title> or <desc>; total length at most 8000 characters. Return {svg, alt_zh} where alt_zh is one Chinese sentence (at most 40 characters) describing what the picture shows.
```

`svg_v1.json`（`backend/wd/ai/schemas/svg_v1.json`，`{svg, alt_zh}` 必填）不改；`CLAUDE_INTEGRATION.md:285` 的用户提示词示例改为 3.1.2 的新形状。

#### 3.1.2 用户提示词与常量（`backend/wd/ai/svg.py`）

```python
CONCEPT_MAX = 60          # :32 不变
MEANING_MAX = 60          # :33 不变
EXAMPLE_MAX = 120
HOOK_MAX = 60
HOOK_PREFIXES = ("联想：", "联想:")
SVG_PROMPT_VERSION = "svg-v2"
STYLE_TEXT = {
    "kid": "child-friendly picture-book style for 6–11-year-olds: bright warm colours, rounded shapes, friendly simple characters, everyday school, home and playground scenes familiar to a child in China.",
    "neutral": "clean flat educational illustration for teenagers and adults: calm colours, clear geometry, realistic proportions.",
}

def build_user_prompt(display: str, meaning: str, concept: str, *, example: str = "", hook: str = "", style: str = "neutral") -> str:
    # Draw an illustration for the word "{display}" ({meaning}). Scene: {concept}。 Example sentence: "{example}" Memory hook: {hook} Style: {STYLE_TEXT[style]}
    # 空的 example / hook 段省略；"for the word \"…\"" 片段保留（tests/fake_claude.py:160-162 `svg_word` 的正则依赖它）

def hook_from(mnemonic: str | None) -> str:
    # 以 HOOK_PREFIXES 开头 → 去前缀、取到第一个句号、截 HOOK_MAX；否则 ""

def prompt_for(conn, word, *, cfg: Settings) -> str:
    content = _active_content(conn, word) or {}
    meaning = str(content.get("meaning_zh") or dictionary_hint(word.get("translation")) or "")
    concept = str(content.get("image_alt_zh") or meaning)
    examples = content.get("examples") or []
    example = str(examples[0].get("en") or "") if examples and isinstance(examples[0], dict) else ""
    return build_user_prompt(str(word["display"]), meaning, concept, example=example, hook=hook_from(content.get("mnemonic_zh")), style=style.style_for(word, cfg))
```

`handle_generate_svg`：`:115` 改 `user_prompt=prompt_for(conn, word, cfg=cfg)`；`:137` 改 `activate_svg(conn, cfg, wid, svg, alt, now=now, model=result.model_used, prompt_version=SVG_PROMPT_VERSION)`（`result.model_used` 是 `runner.py:198` 的字段）；在 `activate_svg` 之前 `repairs = len(sanitize_svg.BARE_AMP_RE.findall(svg))`，`repairs > 0` 时 `ctx.log.info(..., extra={"event": "svg_repaired", "repairs": repairs, ...})`；模块文档串 `:1-11` 末句「never retried automatically」改为「retried through the failed-image retry rules of DESIGN §9」；`__all__`（`:149`）加 `SVG_PROMPT_VERSION`。`words.word_row` 是 `SELECT *`（`services/words.py:204-206`），`stage_min`/`pos` 已在行里。

#### 3.1.3 风格模块 `backend/wd/images/style.py`（新）

```python
STYLE_KID, STYLE_NEUTRAL = "kid", "neutral"
STYLES = (STYLE_KID, STYLE_NEUTRAL)
FUNCTION_POS = frozenset({"i", "c", "d", "p", "a", "u", "t"})      # ECDICT pos codes, see frontend/src/utils/pos.ts POS_LABELS
NO_BARE_LEMMA_POS = FUNCTION_POS | {"r"}

def dominant_pos(pos: str | None) -> str | None:
    """'n:4/v:96' → 'v' (largest share, ties keep the first); None / a plain label ('v./n.') → None."""

def skip_image(word: Mapping[str, Any]) -> bool:
    return dominant_pos(word.get("pos")) in FUNCTION_POS

def allows_bare_lemma(word: Mapping[str, Any]) -> bool:
    return dominant_pos(word.get("pos")) not in NO_BARE_LEMMA_POS   # unknown pos → True

def stage_code(stage_min: Any) -> str | None:
    """words.stage_min → stage code: an int index goes through schemas.index_to_stage; a str (stages-as-data) is returned as is; None → None; an out-of-range index → None (never raises inside a job)."""

def style_for(word: Mapping[str, Any], cfg: Settings) -> str:
    code = stage_code(word.get("stage_min"))
    return STYLE_KID if code is not None and code in cfg.image_kid_stages else STYLE_NEUTRAL
```

配置（`backend/wd/config.py`）：字段区 `:155-168` 加 `image_kid_stages: tuple[str, ...] = ()`；`from_env` 的图片段（`:355-369` 之后）：

```python
kid_raw = text("WD_IMAGE_KID_STAGES", "")
kid_stages: list[str] = []
if kid_raw.strip():
    from .schemas import STAGE_ORDER  # function-level: schemas imports only pydantic + clock, config imports only clock → no cycle
    for code in (x.strip().lower() for x in kid_raw.split(",")):
        if not code:
            continue
        if code not in STAGE_ORDER:
            raise ConfigError(f"WD_IMAGE_KID_STAGES contains an unknown stage {code!r}; allowed: {', '.join(STAGE_ORDER)}")
        if code not in kid_stages:
            kid_stages.append(code)
```
构造处（`:522-534`）加 `image_kid_stages=tuple(kid_stages)`；`entries()`（`:554-575`）对 tuple 已输出 `",".join`。`deploy/env.example` 图片段（`:149-165`）加 `WD_IMAGE_KID_STAGES=""` + 注释「stage codes whose words get the child style and the illustration-first round (empty = off; set to xs after the pilot)」；`docs/DEPLOY.md §4` 在 `:339` `WD_IMAGE_PROVIDERS` 行后加一行（`test_deploy_files.py:119-134`、`test_docs_contract.py:114-133` 钉死）。

#### 3.1.4 清洗（`backend/wd/images/sanitize_svg.py`）

```python
BARE_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")
LABEL_ID = "aigc-label"

def _parse(svg: str) -> ET.Element:          # :65-79
    ...                                       # ENTITY_RE 拒绝（:67-68）与 DOCTYPE / XML 声明去除（:69-70）之后、DET.fromstring（:74）之前：
    text = BARE_AMP_RE.sub("&amp;", text)

def _serialise(el, out, counter, *, in_text, is_root=False, depth=0, allow_text=True):   # :137-166
    ns, local = _split_tag(el.tag)
    if ns != SVG_NS or local not in ALLOWED_ELEMENTS or (not allow_text and local in ("text", "tspan")):
        return                                # dropped with its subtree

def clean(svg: str, *, allow_text: bool = True) -> str:   # :169-181，默认行为不变

def with_label(cleaned: str, label: str) -> str:
    """Insert <desc id="aigc-label">…</desc> right after the root's opening tag of a clean() output; raises SvgRejected when the root tag is not found."""
    # 幂等定义：输出恰含一个 id="aigc-label"；clean() 的输出里不可能已有它（我们从不接受带该 id 的模型输出：_clean_attrs 对 id == LABEL_ID 的属性丢弃）
```

`store.activate_svg(conn, cfg, word_id, svg, alt_zh, *, now=None, model: str | None = None, prompt_version: str | None = None) -> int`：`cleaned = sanitize_svg.clean(svg, allow_text=False)` → `cleaned = sanitize_svg.with_label(cleaned, f"AI-generated illustration · word-Dance · {model or 'claude'} · {(now or now_iso())[:10]}")` → `write_bytes` → `activate(..., provider="claude_svg", license="generated", prompt_version=prompt_version, model=model, text_free=True, ...)`。`store.activate` 新增关键字参数 `prompt_version: str | None = None, model: str | None = None, text_free: bool = False, eval_json: str | None = None`，INSERT 列清单（`:105-113`）追加四列；`activate_candidate` 不传（照片 `text_free=0`）。`viewbox_size` 不受 `<desc>` 影响（正则取根 `viewBox`，`:99-106`）。

#### 3.1.5 迁移 `backend/wd/migrations/0012_word_images_meta.sql`（全文）

```sql
-- 0012_word_images_meta.sql — word_images gains prompt_version / model / text_free / eval_json
-- (docs/analysis/2026-11-05-stages-regions-images/design/images/SYNTHESIS.md §3.1.5).
--
-- Additive only: four ADD COLUMN statements, the 0010_ai_provider.sql precedent (ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT …
-- CHECK). Existing rows keep their meaning: the 30 Claude SVGs drawn before this migration printed the headword (svg_system v1),
-- so text_free stays 0 for them; prompt_version / model stay NULL (photos never get a prompt_version). No view, trigger or real
-- foreign key references word_images (v_bank joins user_words/words only; words.active_image_id and content_reports.image_id are
-- logical), nothing is rebuilt, so the file is safe under `deploy/install.sh --no-restart` (DEPLOY §10). The runner wraps the
-- file in BEGIN IMMEDIATE and records schema_migrations(12, 'word_images_meta') itself (SCHEMA.sql §1) — nothing else belongs
-- here. Numbered 0012 because 0011 belongs to the stage-model migration (design/stage-model); db.list_migration_files does not
-- require consecutive numbers and pending_migrations applies every file not yet in schema_migrations, so the two may land in
-- either order.
ALTER TABLE word_images ADD COLUMN prompt_version TEXT;                                             -- 'svg-v2' | 'ai-v1' | NULL (photos, pre-0012 SVGs)
ALTER TABLE word_images ADD COLUMN model TEXT;                                                      -- generator model id (ai_calls.model_used or the vendor model); NULL for photos
ALTER TABLE word_images ADD COLUMN text_free INTEGER NOT NULL DEFAULT 0 CHECK (text_free IN (0,1));  -- 1 = code-guaranteed text-free file (<text>/<tspan> stripped): the only gate for any picture-first mode
ALTER TABLE word_images ADD COLUMN eval_json TEXT;                                                  -- pilot / VLM rubric scores (SYNTHESIS §3.6); never overwrites `score`
```

- `docs/SCHEMA.sql` 不改（`test_db.py:362-366`）；`EXPECTED_TABLES`（`test_db.py:13-17`）不变。
- 老代码兼容：显式列名 INSERT 与 `SELECT wi.*` → 代码回退不回迁移也能跑（D-images-3）。

#### 3.1.6 成本预期与文档数字

现状 34 次 $0.4207、$0.01237/次、30 张交付 $0.0140/张、4 次拒收；$0.50/日 ≈ 35–40 张/天；输入侧多 ≈ 150 token（例句 + 挂钩 + Style），输出仍受 8000 字符约束；拒收率预期接近 0（`&` 修复 + 无 `<text>` 减少特殊字符）。九处文档数字见 D-images-19。

### 3.2 content 生成侧（`backend/wd/ai/prompts/content_system.txt`；`docs/CLAUDE_INTEGRATION.md:210-226` §5.1 代码块逐字节同步，`test_schemas.py:122-127[content_system]`）

- 第 1 条（`:4`）末尾追加：`For words whose stages include 小学, write meaning_zh in plain words a 10-year-old understands (keep the POS labels).`
- 第 3 条（`:6`）末尾追加：`If the word's stages include 小学: 4–8 words each, present tense, everyday school / home / playground situations, only vocabulary a 10-year-old knows, and use the headword in its base form in at least two sentences. If the highest stage is 初中: 6–12 words, school and daily life, no workplace or news register.`
- 第 5 条（`:8`）末尾追加：`For 小学 words prefer a vivid picture-like association ("联想：…") over morphology.`
- 第 6 条（`:9`）整条替换：`6. image_keywords: 2–4 short English search phrases (2–4 words each) that all name the SAME concrete scene as example sentence 1 — one visible subject plus its setting, e.g. "abandoned car snow", "car left on road". Most literal first. No people's names or brands; avoid text-heavy scenes (signs, screens, documents), close-up faces and anything unsuitable for children. For a function word, or an abstract word with no natural scene, give the lemma alone.`
- 第 7 条（`:10`）整条替换：`7. image_alt_zh: one Chinese sentence (at most 30 characters) describing the ideal picture as ONE subject doing one thing in one place, in the sense of example sentence 1; the picture contains no text and no close-up face; for an abstract word describe the concrete memory hook that matches mnemonic_zh (an image, never a symbolic explanation).`
- 第 1 行受众句与第 8 条难度尺子**不改**（归阶段模型线，§8.1）。
- `backend/wd/ai/content.py`：`:46 PROMPT_VERSION = "content-v2"`；`:54 EXAMPLE_EN_MIN, EXAMPLE_EN_MAX = 10, 240`；`:63 PREFIX_MIN = 4` 不动；`:66-68 _is_blocked(keyword)` → `_is_blocked(keyword, lemma)` = `is_blocked(keyword, allow=select.keyword_tokens(lemma))`，调用处 `:177`。
- 后验证其余不变：`KEYWORD_RE :61`、`ALT_MAX :62`；`content_v1.json:9-10` 的 `description` **不改**（三方字节绑定，`test_schemas.py:56-62`）。
- 文档：`docs/CLAUDE_INTEGRATION.md:206`（标题 `content-v1` → `content-v2`）、`:355`（「15–240」→「10–240」）；`docs/AI_FALLBACK_MODEL.md:29`（「15–240」）；`docs/WORD_LIBRARY_CURATION.md:65,183`（`content-v1` → 「当前 `PROMPT_VERSION`（`content-v2`）」；`:183` 的内容包导入说明必须写新版本号，否则残留任务会覆盖手工内容）。
- 「小学」标签只有在阶段模型给 `content.STAGE_ZH`（`content.py:49`）加 `"xs": "小学"` 后才会出现在 `prompt_entry`（`:88`）里，在此之前规则 1/3/5 的小学部分是空操作；初中部分立即生效。

### 3.3 照片 / 插画抓取链

#### 3.3.1 查询词构造（`backend/wd/images/handler.py`）

```python
def clean_keywords(values, lemma, *, allow_lemma: bool = True) -> tuple[list[str], list[str]]:
    """(kept, dropped): shape rule + blocklist with the lemma's own tokens allowed; [lemma] when none survive and allow_lemma, else []."""
```
`fetch_for_word`：
1. SELECT（`:121-124`）加 `kind, pos, stage_min`。
2. `style_ = style.style_for(word, cfg)`；`explicit = bool(provider) or bool(query and query.strip())`。
3. `if not explicit and style.skip_image(word)`: `store.set_image_state(conn, word_id, STATUS_FAILED, now=now)`；`return FetchOutcome(STATUS_SKIPPED, detail="function word: card only")`。
4. 管理员 `query`：`kept, dropped = clean_keywords([query], lemma, allow_lemma=False)`；`dropped` 非空 → `log.warning("admin query ignored", extra={"event": "query_ignored", ...})` 且 `detail` 前缀 `"query ignored (shape/blocklist); "`，再按内容关键词继续（API 仍 202，契约不变）。
5. 内容关键词：`clean_keywords(content.image_keywords or [], lemma, allow_lemma=style.allows_bare_lemma(word))`；结果为空（副词无可用关键词）→ 跳过 provider 轮次，直接进入 SVG/卡片判定（`:198-206`）。
6. 轮次：`rounds = ((STYLE_KID, kid_names), (STYLE_NEUTRAL, names)) if style_ == STYLE_KID and not provider else ((style_, names),)`，其中 `names = (provider,) if provider else cfg.image_providers`，`kid_names = tuple(p for p in cfg.image_providers if p != "pexels")`（第三期改为 `cfg.image_providers_kid`）。
7. 循环体抽成 `_search_round(ctx, conn, chain, keywords, *, round_style, ...) -> FetchOutcome | None`，内部：`if priority >= 90 and p.name in PREWARM_SKIP_PROVIDERS: continue`（`PREWARM_SKIP_PROVIDERS = ("openverse", "pixabay", "pexels")`）；`p.search(kw, SEARCH_LIMIT, style=round_style)`；`select.rank(cands, kw, excluded, used_refs=used_refs, allow=frozenset(select.keyword_tokens(kw)), style=round_style)`；`store.activate_candidate(...)` 不变。
8. 文档串 `:1-11` 更新（功能词门、两轮、重试）。

`MAX_KEYWORDS = 3` 不变（线上 49 条内容无一有第 4 个关键词 [verify images-pipeline-2]）。

#### 3.3.2 provider 参数（接口 `backend/wd/interfaces.py:73-79`：`def search(self, query: str, limit: int, *, style: str = "neutral") -> list[Candidate]`；`runtime_checkable` 只查属性存在，`test_providers.py:49` 的 `isinstance` 不受影响）

| provider | neutral（现状 + 三个无害参数） | kid | 错误处理 |
|---|---|---|---|
| wikimedia（`wikimedia.py:40-57,97`） | `gsrsearch="{q} filetype:bitmap"`；`iiprop="url\|extmetadata\|size\|mime\|thumbmime"`；`maxlag: 5` | `gsrsearch="{q} filetype:drawing"` | `search()` 用新的 `base.get_json_with_headers(...) -> tuple[dict, httpx.Headers]`（`get_json` 改为其包装）；`data.get("error", {}).get("code") == "maxlag"` → `raise ProviderError(f"wikimedia: maxlag ({info})", status=503, retry_after_s=base.parse_retry_after(headers.get("Retry-After")) or 30)` → 现有冷却路径（`handler.py:168-170`，`quota.cooldown_seconds` 优先 `Retry-After`，`quota.py:113-121`）；`parse_search:97` → `mime = info.get("thumbmime") or info.get("mime") or base.mime_from_url(original_url or image_url)` |
| openverse（`openverse.py:28,41-42,65-72,114-119`） | 删 `PAGE_SIZE`；`params(query, limit, *, style)`：`page_size = max(1, min(int(limit), 20))`（=10） | 加 `category: "illustration"` | `extra["category"] = r.get("category")` |
| pixabay（`pixabay.py:30-46`） | `image_type: "photo"` | `image_type: "illustration"` | — |
| pexels（`pexels.py:29-37`） | 签名加 `*, style="neutral"`，参数不变 | 不进 kid 轮 | — |

条款约束写进 `docs/DESIGN.md §9`：Pixabay 禁系统性批量下载 → 只按需抓；Openverse 匿名 200/日（本地 160）→ kid 词最坏 2 轮 × 3 关键词 = 6 次/词，小学阶段落地前注册 Openverse 应用（INDEX §6.2 第 6 条）。

#### 3.3.3 候选选择（`backend/wd/images/select.py`）

```python
UNSAFE_RE     = re.compile(r"\b(nude|nudity|sex|porn|gore|blood|weapon|gun|corpse)\b", re.I)
NON_PHOTO_RE  = re.compile(r"\b(map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document)\b", re.I)
KID_UNSAFE_RE = re.compile(r"\b(beer|wine|alcohol|cigarette|cigarettes|smoking|horror|zombie|zombies|skull|skulls|knife|knives|bikini|lingerie)\b", re.I)
PEOPLE_RE     = re.compile(r"\b(portrait|portraits|selfie|selfies|headshot|close-?up|face|faces|people|person|man|woman|boy|girl)\b", re.I)
TEXTY_RE      = re.compile(r"\b(sign|signs|signage|caption|captions|typography|infographic|inscription|banner|banners|label|labels)\b", re.I)
STYLE_TARGET  = {"kid": {"illustration", "vector"}, "neutral": {"photograph", "photo"}}

def is_blocked(text: str | None, *, allow: frozenset[str] = frozenset(), style: str = "neutral") -> bool:
    if not text: return False
    if UNSAFE_RE.search(text): return True
    if style == "kid" and KID_UNSAFE_RE.search(text): return True
    return any(m.group(1).lower() not in allow for m in NON_PHOTO_RE.finditer(text))

def reject_reason(cand, exclude=(), *, allow=frozenset(), style="neutral") -> str | None   # :54-77，黑名单一步改为 is_blocked(haystack, allow=allow, style=style)
def score(cand, keyword, *, used_refs=(), style="neutral") -> int                            # :80-101 + D-images-12 五个信号
def rank(cands, keyword, exclude=(), *, used_refs=(), allow=frozenset(), style="neutral")  # :104-128 透传
```
`BLOCKLIST_RE` 删除（唯一外部读者 `content.py:36` 只用 `is_blocked`；`docs/DESIGN.md:547` 同步三张表）。模块文档串 `:1-10` 更新。

#### 3.3.4 失败词自动重试（`backend/wd/images/service.py` 新函数；`images/__init__.py:18,21-35` 导出 `retry_if_failed`、`retry_failed_studied`）

```python
RETRY_MIN_AGE_H = 6
RETRY_MAX_AUTO_30D = 3
RETRY_NIGHTLY_LIMIT = 50
RETRY_NIGHTLY_PRIORITY = 30

def _live_fetch_exists(conn, word_id) -> bool:
    # SELECT 1 FROM jobs WHERE type='fetch_image' AND status IN ('queued','running') AND (dedupe_key = 'image:<id>' OR dedupe_key LIKE 'image:<id>:r%')
def last_fetch_finished_at(conn, word_id) -> str | None:
    # SELECT MAX(COALESCE(finished_at, updated_at)) FROM jobs WHERE type='fetch_image' AND status IN ('done','dead','cancelled') AND (dedupe_key = 'image:<id>' OR dedupe_key LIKE 'image:<id>:r%')
def auto_retries_30d(conn, word_id, now) -> int:
    # SELECT COUNT(*) FROM jobs WHERE type='fetch_image' AND json_extract(payload_json,'$.word_id') = ? AND json_extract(payload_json,'$.retry') = 1 AND created_at >= <now-30d>
def retry_due(conn, word, now) -> bool:
    # image_state == 'failed' and not style.skip_image(word) and not _live_fetch_exists and (last is None or last <= now-6h) and auto_retries_30d < 3
def retry_if_failed(conn, word, *, priority: int, now: str) -> int | None:
    # retry_due → enqueue_fetch(conn, word_id, priority=priority, now=now, retry=True)
def retry_failed_studied(conn, now, *, limit=RETRY_NIGHTLY_LIMIT, priority=RETRY_NIGHTLY_PRIORITY, dry_run=False) -> list[int]:
    # SELECT id, lemma, pos, image_state FROM words WHERE image_state='failed' AND merged_into_word_id IS NULL ORDER BY updated_at, id
    # keep those with word_is_studied(conn, id, now) and retry_due(...); enqueue (unless dry_run) until limit; return the word ids
```
`enqueue_fetch(..., retry: bool = False)`：`if retry: payload["retry"] = True`（`handler.handle_fetch_image` 忽略该键，旧代码回退也忽略）。`images_enabled` 门：`bank`/`batches` 挂点用 `from ..config import get_settings` 懒加载（`scheduler.py:250-253` 先例），`cfg.images_enabled` 为假直接返回 None。

挂点：
- `backend/wd/services/bank.py:636` 与 `:659`：`enqueue_content_if_needed(...)` 之后 `images.retry_if_failed(conn, word, priority=CONTENT_PRIORITY_BANK, now=now)`（`word` 来自 `words.word_row`，`SELECT *`，`bank.py:193-208`）；文件头 `from .. import images`（`images` 包不导入 `services`，`services/words.py` 已导入 `images`，方向可行）。
- `backend/wd/services/batches.py:352-362 _enqueue_content_for`：SELECT（`:359`）加 `pos, image_state`，循环内同上，优先级 `CONTENT_PRIORITY_BATCH`；`:639`（`_append_item`，`word` 来自 `words.word_row`）同上。
- `backend/wd/jobs/scheduler.py:364-397 maintenance`：`prefetch` 之后 `try: from .. import images; result.image_retries = len(images.retry_failed_studied(conn, to_iso(now), limit=..., priority=...)) except Exception: log.exception(...)`；`TickResult`（`:66-73`）加 `image_retries: int = 0`；`:523` 的 tick 打印加 `image_retries`。
- CLI：`handler.register_cli` 加 `images-retry [--limit N] [--dry-run]` → `cmd_images_retry`（打印 lemma 列表与数量）；`backend/wd/cli.py:54` 改 `("fetch-image", "images-prune", "images-retry")`；`docs/DEPLOY.md:417` 命令清单。

### 3.4 生成式位图（第二期适配器 + 第三期接入）

#### 3.4.1 适配器 `backend/wd/images/providers/ai_image.py`（第二期合入，默认不在链中）

```python
GEN_SIZE = "1344x768"            # 16:10 盒子 cover 只裁 ≈ 9%；智谱枚举含 1344×768 [image-memorability-26]
GEN_TIMEOUT_S = 60.0
GEN_PROMPT_VERSION = "ai-v1"

@dataclass
class Generated:
    url: str | None
    b64: bytes | None
    content_filter_max: int      # max(level) over the response's content_filter list, 0 when absent
    model: str
    raw_status: int

class AiImageProvider:           # NOT an ImageProvider: no search(); the handler branches on isinstance
    name = "ai_image"
    def __init__(self, cfg: Settings, *, client_factory=None): ...
    def generate(self, prompt: str, *, user_ref: str) -> Generated:
        # POST {base}/images/generations  Authorization: Bearer <key>
        # {"model": cfg.image_gen_model, "prompt": prompt, "size": GEN_SIZE, "n": 1, "watermark_enabled": True, "user_id": user_ref}
        # HTTP ≥ 400 / network → ProviderError(status, retry_after_s)（base.get_json 语义）；data[0].url 或 data[0].b64_json
```
密钥读法复用 `ai/providers/openai_http.py` 的 `api_key`（环境变量或 0600 文件首行）；`WD_IMAGE_GEN_API_KEY` 进 `SECRET_KEYS`（`config.py:65-75`）。第二期该模块的配置来自构造参数（`base_url`、`model`、`api_key`），不读 `Settings`，试点脚本直接构造；第三期改为读 `Settings`。

`backend/wd/images/gen_prompt.py`（第二期）：
```
kid:     儿童绘本风格扁平插画，明亮温暖的颜色，圆润的形状，中国小学生熟悉的校园、家庭和操场场景。画面中只有一个清晰的主体：{scene}。与句子「{example_en}」的情境一致。{hook}整张图没有任何文字、字母、数字或标志；纯色浅背景；不画人脸特写；不出现任何恐怖、暴力、亲密内容。
neutral: 简洁的教学配图，扁平插画风格，构图干净，画面主体单一：{scene}。与句子「{example_en}」的情境一致。{hook}整张图没有任何文字、字母、数字或标志；不画人脸特写；不出现多余的装饰元素。
```
`scene = image_alt_zh`（≤ 60）或 `meaning_zh` 首行；`hook` 为「联想：…。」或空；总长 ≤ 300 字；CogView 无 `negative_prompt`，「不要」只能写进正文 [image-memorability-26]。

`backend/tests/fake_image_gen.py`（第二期）：`transport(mode="ok_url", *, calls=None) -> httpx.MockTransport`（与 `tests/fake_openai.py:93-122` 同形），路由 `POST */images/generations`：`ok_url`（`data[0].url = https://fake-cdn.example/<id>.png`，同一 transport 对该主机返回 Pillow 画的 1344×768 PNG）、`ok_b64`、`filtered`（`content_filter level 2`）、`sensitive_400`（智谱 1301 体）、`401`、`429`（`Retry-After: 2`）、`503`、`invalid_json`；请求体记录到 `calls`，key 只记 sha256。

#### 3.4.2 第三期接入（条件：§3.6.4 门槛）

- `providers/__init__.py`：`PROVIDER_CLASSES["ai_image"] = AiImageProvider`；`SEARCH_PROVIDERS = tuple(n for n in PROVIDER_CLASSES if n != "ai_image")`（`PHOTO_PROVIDERS` 改名为它，`handler.py:352` 的 CLI choices 改为 `[*SEARCH_PROVIDERS, "claude_svg", "ai_image"]`）；`is_keyed("ai_image", cfg)` = 生成器配置齐全；`build_chain` 返回 `list[ImageProvider | AiImageProvider]`。
- 配置（8 项）：`WD_IMAGE_GEN_KIND`（`none` / `openai_images`）、`WD_IMAGE_GEN_BASE_URL`（校验同 `WD_AI_FALLBACK_BASE_URL`，`config.py:379-388`）、`WD_IMAGE_GEN_MODEL`、`WD_IMAGE_GEN_API_KEY` / `_FILE`（文件检查同 `:389-401`）、`WD_IMAGE_GEN_MINUTE_LIMIT`（4）、`WD_IMAGE_GEN_DAILY_LIMIT`（60）、`WD_IMAGE_PROVIDERS_KID`（空 = `image_providers` 去 `pexels`；允许值 `IMAGE_PROVIDERS ∪ {ai_image}`；含 `ai_image` 而 `KIND=none` → `ConfigError`）。`IMAGE_PROVIDERS`（`config.py:52`）加 `ai_image`（`WD_IMAGE_PROVIDERS` 也可含它，成人链不推荐）。
- handler：`_search_round` 遇到 `isinstance(p, AiImageProvider)` → `_generate_round(...)`：门 = `priority < 90` ∧ `quota.check(conn, "ai_image", cfg, now) is None` ∧ `not select.is_blocked(image_alt_zh or lemma, style=...)` ∧（`requested` 或无 active 图）；`quota.record`；`Generated.content_filter_max > 0` 或 1301 → 事件 `image_gen_filtered`，返回 None 不冷却；`url` → `fetch.download_and_store`（SSRF 规则 `fetch.py:124-155,194-237` 天然适用；**试点第一件事是确认智谱文件主机能过 https/443/公网 IP 规则**）；`b64` → 新 `fetch.store_image_bytes(data, cfg, *, label)`；`normalise_image(..., label=AigcLabel(...))` 写 XMP/COM；`store.activate(conn, word_id, provider="ai_image", license="generated", creator=model, source_url=url, alt_zh=image_alt_zh, mime="image/jpeg", prompt_version="ai-v1", model=model, text_free=False, query=None, ...)`。
- `quota.limits_for("ai_image")` → `(cfg.image_gen_minute_limit, cfg.image_gen_daily_limit)`；`quota.status` 遍历 `dict.fromkeys([*cfg.image_providers, *cfg.image_providers_kid])`；`diag.check_providers`（`diag.py:136-149`）同样遍历并集。
- `service.image_meta`：`generated = provider in ("claude_svg", "ai_image")` → `attribution=None`；`kind = "svg" if provider == "claude_svg" else "photo"`；`photo_mix` 加 `SUM(wi.provider='ai_image') AS with_ai_image`。
- 迁移 `0013_word_images_ai_provider.sql`（全文）：

```sql
-- 0013_word_images_ai_provider.sql — word_images.provider gains 'ai_image' (generated bitmaps; SYNTHESIS.md §3.4.2).
-- SQLite cannot ALTER a CHECK list: rebuild. No view references word_images (v_bank joins user_words/words only), nothing declares
-- a FOREIGN KEY to it (words.active_image_id / content_reports.image_id are logical), so RENAME needs no legacy_alter_table help and
-- the row ids are preserved. The four 0012 columns are carried over in place. Stop-first migration (DEPLOY §10: never under
-- install.sh --no-restart). The runner wraps the file in BEGIN IMMEDIATE, turns foreign keys off around it, runs
-- foreign_key_check and records schema_migrations(13, 'word_images_ai_provider') itself (SCHEMA.sql §1).
CREATE TABLE word_images_new (
  id               INTEGER PRIMARY KEY,
  word_id          INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  provider         TEXT NOT NULL CHECK (provider IN ('wikimedia','openverse','pixabay','pexels','claude_svg','ai_image')),
  provider_ref     TEXT,
  query            TEXT,
  source_url       TEXT,
  landing_url      TEXT,
  title            TEXT,
  creator          TEXT,
  creator_url      TEXT,
  license          TEXT,
  license_url      TEXT,
  attribution_text TEXT,
  alt_zh           TEXT,
  width            INTEGER,
  height           INTEGER,
  file_path        TEXT NOT NULL,
  file_bytes       INTEGER NOT NULL,
  sha256           TEXT NOT NULL,
  mime             TEXT NOT NULL CHECK (mime IN ('image/jpeg','image/svg+xml')),
  score            REAL,
  status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','rejected')),
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  prompt_version   TEXT,
  model            TEXT,
  text_free        INTEGER NOT NULL DEFAULT 0 CHECK (text_free IN (0,1)),
  eval_json        TEXT
);
INSERT INTO word_images_new (id, word_id, provider, provider_ref, query, source_url, landing_url, title, creator, creator_url,
                             license, license_url, attribution_text, alt_zh, width, height, file_path, file_bytes, sha256, mime,
                             score, status, created_at, prompt_version, model, text_free, eval_json)
SELECT id, word_id, provider, provider_ref, query, source_url, landing_url, title, creator, creator_url,
       license, license_url, attribution_text, alt_zh, width, height, file_path, file_bytes, sha256, mime,
       score, status, created_at, prompt_version, model, text_free, eval_json
FROM word_images;
DROP TABLE word_images;                       -- drops ix_word_images_word / ix_word_images_sha / ux_word_images_active with it
ALTER TABLE word_images_new RENAME TO word_images;
CREATE INDEX        ix_word_images_word   ON word_images(word_id, status);
CREATE INDEX        ix_word_images_sha    ON word_images(sha256);
CREATE UNIQUE INDEX ux_word_images_active ON word_images(word_id) WHERE status = 'active';
```

- 契约（同一提交，`docs/API.md:3` 规则）：`schemas.py:46` `ImageProviderName` 加 `"ai_image"`（在 `"claude_svg"` 后、`"card_svg"` 前）；`:1350 RefetchImageRequest.provider` 加；`:1094-1101 AdminOverviewWords` 加 `with_ai_image: int`；`routers/admin_ops.py:133-141` 填值；`types.ts:84` → `provider: ImageProviderName` 且新增 `export type ImageProviderName = 'wikimedia' | 'openverse' | 'pixabay' | 'pexels' | 'claude_svg' | 'ai_image' | 'card_svg';`；`types.ts:185-186` 加 `with_ai_image` 与注释；`endpoints.ts:340 RefetchProvider` 加；`API.md:231`（端点 69）、`:314-321`、`:420-421`、`:465` 同步；`WordImage.tsx:28` → `if (image.kind === 'svg' || image.provider === 'claude_svg') return zh.word.aiImage; if (image.provider === 'ai_image') return zh.word.aiPicture;`（位图保持 `cover`，`:50` 不变）；`zh.ts:54` 加 `aiPicture: 'AI 生成配图'`，`:92 admin.images` 加 `ai: 'AI 配图'`，`:86 sources.images` 加「AI 生成配图」；`docs/FRONTEND.md:258,292,298` 逐行镜像（`zh.test.ts`、`zh.contract.test.ts`）；`AdminPage.tsx:147-160 ImageMix` 加第四段（`AdminPage.css:172-186` 加 `.mix__seg--ai, .mix__swatch--ai`）；`scripts/smoke.py:12,624` 不变式改为 `with_photo + with_claude_svg + with_ai_image + card_only == with_content`；`backend/wd/ai/ledger.py:24 PHOTO_PROVIDERS_SQL` 删除（零消费者）；`ATTRIBUTION.md:54-59 §3.4` 加「**AI 生成配图**」条目（`provider='ai_image'`、厂商水印、文件内 XMP 标签、版权按智谱用户协议由运营者维护、不含第三方素材）、`:76 §6` 题注行；`docs/DEPLOY.md §4` 8 行、`deploy/env.example` 8 行；`docs/DESIGN.md §9` 伪代码加 `ai_image` 步骤。

### 3.5 展示与数据模型

1. **图在回忆之后**（现状不变）：`StudyCard.tsx:302-310` 背面 `WordImage`；正面 `:201-228` 无图。
2. **不做** `image_hint` / 正面出图（D-images-14）；**不做** 每词多图（D-images-15）；`show_images` 全局布尔（`0001_init.sql:149`、`schemas.py:167`、`SettingsPage.tsx:413`）不变。
3. **前端一、二期零改动**；第三期只有 `WordImage.tsx:28` 题注分支、`AdminPage` 第四段、`zh.ts` 三个键与 `types.ts`/`endpoints.ts` 镜像。
4. **清晰度**（`WD_IMAGE_MAX_EDGE` 800 → 1200、`wikimedia.THUMB_WIDTH` 跟随配置、`pexels.py:46` 取 `large2x`）不在三期内；[verify images-pipeline O10] 留作后续，与本线证据无关。

### 3.6 评估：200 个二级词的四臂试点（第二期，脚本 `scripts/image_pilot.py`，只写 scratch 与私有拷贝）

#### 3.6.1 样本

- 样本框：`data/lists/moe-2022-level2.txt`（以 `#` 开头为注释、每行一个词头；并列/括注按词表线 README 的规则取第一个词头）∩ `words.lemma`（498）；去 `style.skip_image()`（65）→ 433。
- 分层（主词性 `style.dominant_pos`）：n 110 / v 50 / j 20 / r 20 = 200；每层按 `frq` 升序（`frq` 为 0/NULL 的排最后）等距抽样。
- 内容：200 词只有 1 个有内容，先为其余 199 词生成 content-v2 内容：在私有拷贝上入队 `generate_content {"word_id", "force": true}`（`admin_ops.py:392-411` 的同一 payload）并 `wd worker-once` 排空（拷贝上无 `kv.worker_lease`，不会被拒）；≈ 20 次调用 × $0.04 = $0.8（Claude）或 ¥0（`WD_AI_PROVIDER=openai_http` 走 GLM 免费档）。

#### 3.6.2 四臂（每臂一份 `VACUUM INTO` 的私有拷贝 `scratchpad/image-pilot/<arm>/word-dance.db`，`WD_DATA_DIR` 指向各自目录；进程环境里不能有 `HTTP(S)_PROXY`——`fetch.safe_download` 用 DNS 固定 IP + `sni_hostname`，经 HTTP 代理会 `CERTIFICATE_VERIFY_FAILED`）

| 臂 | 命令 / 做法 | 配额 / 成本 |
|---|---|---|
| A 照片链（kid 轮 + neutral 轮） | `WD_IMAGE_KID_STAGES=<这些词当时的阶段码：迁移前 zk、迁移后 xs> wd fetch-image <lemma> --no-svg` × 200；记录每轮 `reject_reason` 计数（脚本在 `select.rank` 外层统计） | Commons ≤ 1,200 次（2 轮 × 3 关键词 × 200，1 req/s，≤ 25 分钟，日限 2,000 内）；Openverse 匿名 160/日 → 分 4–8 天或先注册应用 |
| B SVG v2 | `wd fetch-image <lemma> --provider claude_svg` × 200 + `wd worker-once`；拷贝 `.env` 临时 `WD_AI_SVG_DAILY_BUDGET_USD="3.00"` | 200 × $0.0124 ≈ $2.5 |
| C CogView-3-Flash | 脚本直接构造 `AiImageProvider(base_url, model="cogview-3-flash", api_key)`，`gen_prompt.build(word, content, "kid")`，结果 `fetch.normalise_image` 后存 `pilot/C/<lemma>.jpg`；记录 `content_filter_max`、URL 主机、延迟 | ¥0；并发 1、≈ 10–20 s/张 → ≈ 1 h |
| D 模板卡零点 | `card_svg.render(word, content)` → `pilot/D/<lemma>.svg` | ¥0 |

导出：每臂 `pilot/<arm>/rows.csv`（`lemma, arm, provider, file, alt_zh, query, provider_ref, score, prompt_version, model, cost_usd, content_filter, latency_ms, reject_counts_json`）。

#### 3.6.3 评分页与评分表

`pilot/sheet.html`：每词一行、四臂乱序并排、**词头与释义默认隐藏**；评分者先在「我猜的词义」栏填写再点「显示答案」；`pilot/scores.csv` 列 `lemma, arm, rater, guess, guess_correct, r1, r2, r3, r4, r5`。两名成人评分者；Cohen κ（R1–R3 的通过/不通过）≥ 0.6 才采信。

| 项 | 问题 | 2 | 1 | 0 |
|---|---|---|---|---|
| R1 单一所指 | 10 岁孩子能一眼说出图里是什么吗 | 立刻能 | 犹豫 | 不能 / 多个主体 |
| R2 义项一致 | 图画的是例句 1 的那个意思吗 | 是 | 相关但不是那句 | 另一义项 / 无关 |
| R3 干净安全 | 无文字、无人脸特写、无不当内容 | 全满足 | 少量无关文字或细节 | 有文字 / 人脸特写 / 不当 |
| R4 风格一致 | 与同臂其他图风格一致且不雷同 | 是 | 风格漂移 | 雷同或风格乱 |
| R5 亲和 / 本土（仅 kid 风格臂） | 场景是中国小学生熟悉的吗 | 是 | 中性 | 陌生 |

通过 = R1 = 2 ∧ R2 ≥ 1 ∧ R3 = 2。指标：每臂通过率、交付率（拿到图 / 200）、每通过图成本、拒收率（B）、`content_filter` 率（C）、provider 请求数、平均延迟、`guess_correct` 率；副词层与名/动/形层分别报告。

#### 3.6.4 预注册门槛（写进脚本的 `thresholds.json`，试点前提交）

1. `WD_IMAGE_KID_STAGES` 默认改 `xs`（第三期）：B 或 A 的 kid 风格图在 xs 词上通过率 ≥ 70% 且每通过图 ≤ $0.02。
2. 照片臂留在 kid 轮：A 的 kid 轮通过率 ≥ 60%；否则 kid 轮只保留 SVG（`kid_names = ()`）。
3. `ai_image` 进 KID 链首位：C 通过率 ≥ B + 10 个百分点 ∧ R3 ≥ 90% ∧ `content_filter` 拒绝 ≤ 5% ∧ 智谱 URL 过 SSRF 规则；|C − B| < 10 → `ai_image` 放链尾（兜底，省 SVG 预算）；C < B − 10 → 不接入（第三期取消）。
4. 副词：r 层通过率 < 50% → 第三期把 `r` 加入 `FUNCTION_POS`。
5. 尺寸门槛：kid 轮 Openverse 因 `size` 拒绝且两边 ≥ 300×200 的候选占该轮拒绝 ≥ 30% → 第三期 `MIN_SIZE_KID = (300, 200)`。
6. 儿童小样本：5–8 名上海三至五年级小学生，监护人书面同意，每人看 20 张（各臂通过图均衡、隐藏词头）：任务 1「这是什么意思」正确率；24 h 后任务 2「看图说英文词」正确率。某臂 24 h 回忆比最佳臂低 ≥ 10 个百分点 → 该臂不用于 xs 词。n 太小不做统计检验，作为预注册的否决条件使用。

#### 3.6.5 自动评分（可选，GLM-4.6V-Flash 免费 [image-memorability-32]）

`chat/completions` 的 `image_url` 内容块 + `image_alt_zh` + 例句 1 + 词义 → JSON `{"single_subject":0-2,"meaning_match":0-2,"clean":0-2,"text_present":0|1,"face_closeup":0|1,"note":"…"}` 写入拷贝的 `word_images.eval_json`；先在 60 张子集上与人工「通过/不通过」比一致率 ≥ 80% 才用于批量；`word_images.score` 继续只存 `select.score`。C 臂图片 `text_present == 0` 时，第三期才允许置 `text_free=1`。

#### 3.6.6 产品内度量（第三期之后）

`review_logs` 按 `word_images.prompt_version`/`provider` 分组的首轮「不熟悉」率与 7 天「记住了」率——2 个用户没有统计力，第一期只保证分组键（`prompt_version`、`model`）已经存下。

### 3.7 分期

| 期 | 条件 | 内容 |
|---|---|---|
| 一 | 无 | 3.1 全部（含 0012）、3.2、3.3 全部（插画轮代码就绪、默认关）、3.6.6 的分组键、文档数字 |
| 二 | 智谱 key；出口正常的机器；Q-img-3/6 | 3.4.1 适配器 + fake + `gen_prompt`；`scripts/image_pilot.py`；3.6.1–3.6.5 |
| 三 | 3.6.4 门槛 | 3.4.2 全部（0013、8 个配置、契约提交、XMP）；`WD_IMAGE_KID_STAGES` 默认 `("xs",)`；按门槛 4/5 调整 `FUNCTION_POS`/`MIN_SIZE_KID` |

---

## 4. 改动清单（文件 → 改什么）

### 4.1 第一期（8 个提交，顺序 C1 → C8）

**C1 文档数字**（零代码）：`docs/DESIGN.md:28,518,550`、`docs/CLAUDE_INTEGRATION.md:407,416`、`docs/DEPLOY.md:326,434`、`docs/ops.md:198`、`deploy/env.example:83`、`backend/wd/ai/budget.py:273`（注释）。

**C2 迁移 0012**：`backend/wd/migrations/0012_word_images_meta.sql`（§3.1.5 全文）；`backend/tests/unit/test_db.py` 新增 `test_0012_adds_word_images_meta_columns_and_keeps_rows`（仿 `:283-310`：0001 基线上插 2 行 `word_images` → `run_migrations` → `PRAGMA table_info` 含四列、`text_free` 默认 0、`CHECK (text_free IN (0,1))` 拒 2、行数与 id 不变、二次运行 `applied == []`）；`backend/wd/images/store.py:76-120 activate` 加四个关键字参数并写入 INSERT。

**C3 SVG v2**：`backend/wd/ai/prompts/svg_system.txt`（§3.1.1）；`docs/CLAUDE_INTEGRATION.md:281-283,285`（§5.5 代码块与示例）、`:296-300`（§6.1 `generate_svg` 行加「`prompt_version`/`model`/`text_free` 写入 `word_images`」）、`:401-403`（§6.7：`clean(svg, allow_text=False)`、裸 `&` 修复、`<desc id="aigc-label">`、「never retried automatically」→ 重试规则）；`backend/wd/ai/svg.py`（§3.1.2）；`backend/wd/images/sanitize_svg.py`（§3.1.4）；`backend/wd/images/store.py:152-174 activate_svg`；`backend/wd/images/style.py`（新，§3.1.3）；`backend/wd/config.py:155-168,355-369,522-534`（`image_kid_stages`）；`deploy/env.example:149-165`、`docs/DEPLOY.md:339` 后一行；`ATTRIBUTION.md:56`（「AI 生成示意图」条补「图内不含文字；SVG 文件内含 `<desc id="aigc-label">` 生成标识」）。

**C4 content v2**：`backend/wd/ai/prompts/content_system.txt:4,6,8,9,10`；`docs/CLAUDE_INTEGRATION.md:206,210-226,355`；`backend/wd/ai/content.py:46,54,66-68,177`；`docs/AI_FALLBACK_MODEL.md:29`；`docs/WORD_LIBRARY_CURATION.md:65,183`；`backend/tests/unit/test_content_apply.py:81`。

**C5 搜索词**：`backend/wd/images/select.py:20-24,40-42,54-77,104-128`（三分黑名单、`allow`、`style`；删 `BLOCKLIST_RE`）；`backend/wd/images/handler.py:64-78,121-124,134-137`（`clean_keywords` 二元组、SELECT 加列、功能词门、`query_ignored`）；`backend/wd/ai/content.py:66-68`（`_is_blocked(keyword, lemma)`）；`docs/DESIGN.md:547`（Selection 段三张表 + 豁免规则）、`:525-541`（伪代码加功能词门）。

**C6 打分信号**：`backend/wd/images/select.py:80-101`（§3.3.3 五个信号）；`backend/wd/images/providers/openverse.py:114-119`（`extra["category"]`）；`docs/DESIGN.md:547`。

**C7 重试**：`backend/wd/images/service.py`（§3.3.4）；`backend/wd/images/__init__.py:18,21-35`；`backend/wd/services/bank.py`（import + `:636,659`）；`backend/wd/services/batches.py:352-362,639`；`backend/wd/jobs/scheduler.py:66-73,364-397,523`；`backend/wd/images/handler.py:349-361`（`images-retry`）；`backend/wd/cli.py:54`；`docs/DESIGN.md:525-541`（伪代码加重试规则）；`docs/DEPLOY.md:417`；`docs/ops.md:198`（处置列加「`wd images-retry --dry-run`」）、`:202`（prune 提醒）。

**C8 provider 风格参数与插画轮**（默认关）：`backend/wd/interfaces.py:73-79`；`backend/wd/images/providers/base.py:100-118`（`get_json_with_headers`）；`wikimedia.py:3-13,40-57,97`；`openverse.py:1-8,28,41-42,65-72`；`pixabay.py:30-46`；`pexels.py:29-37`；`backend/wd/images/handler.py:1-11,139-206`（两轮、`_search_round`、`PREWARM_SKIP_PROVIDERS`、`style=` 透传）；`docs/DESIGN.md:525-541,545,546`；`ATTRIBUTION.md §3.1/§3.2`（参数描述：`filetype:drawing`、`category=illustration`、`maxlag`）；`backend/wd/smoke_mock.py` 不改（`handle` 按主机与路径匹配，不看 `page_size`，`smoke_mock.py:91-103`）。

### 4.2 第二期

| 文件 | 改什么 |
|---|---|
| `backend/wd/images/providers/ai_image.py`（新） | §3.4.1 适配器（不注册到 `PROVIDER_CLASSES`） |
| `backend/wd/images/gen_prompt.py`（新） | `build(word, content, style) -> str` |
| `backend/tests/fake_image_gen.py`（新）、`backend/tests/unit/test_ai_image_provider.py`（新） | §3.4.1、§5.2 |
| `scripts/image_pilot.py`（新）、`scripts/image_pilot_thresholds.json`（新）、`scripts/image_pilot_rubric.csv`（新） | §3.6.1–3.6.5（`sample` / `content` / `arm A|B|C|D` / `sheet` / `report` 子命令） |
| `docs/DESIGN.md §9` | 一段「试点与门槛」（引用本文 §3.6.4） |

### 4.3 第三期（条件合入，一次契约提交 + 一次迁移）

| 文件 | 改什么 |
|---|---|
| `backend/wd/migrations/0013_word_images_ai_provider.sql`（新） | §3.4.2 全文 |
| `backend/wd/config.py:52,65-75,155-168,355-401,522-534` | `IMAGE_PROVIDERS` 加 `ai_image`；`SECRET_KEYS` 加 `WD_IMAGE_GEN_API_KEY`；8 个字段与校验；`image_kid_stages` 默认 `("xs",)` |
| `backend/wd/images/providers/__init__.py:21-59` | `PROVIDER_CLASSES["ai_image"]`、`SEARCH_PROVIDERS`、`is_keyed`、`build_chain` 类型 |
| `backend/wd/images/handler.py` | `_generate_round`、`kid_names = cfg.image_providers_kid`、CLI `--provider ai_image` |
| `backend/wd/images/fetch.py:241-288` | `normalise_image(..., label=None)`、`store_image_bytes`、`AigcLabel` |
| `backend/wd/images/quota.py:37-47,160-179`、`backend/wd/diag.py:136-149` | `ai_image` 限额；遍历两条链并集 |
| `backend/wd/images/service.py:51-80,237-246` | `generated` 二元组、`with_ai_image` |
| `backend/wd/schemas.py:46,1094-1101,1350`；`backend/wd/routers/admin_ops.py:133-141` | 契约 |
| `backend/wd/ai/ledger.py:24` | 删除 `PHOTO_PROVIDERS_SQL` |
| `frontend/src/api/types.ts:80-87,185-186`、`endpoints.ts:340`、`components/study/WordImage.tsx:28`、`pages/AdminPage.tsx:147-160`、`pages/AdminPage.css:172-186`、`i18n/zh.ts:54,86,92` | 镜像、题注、第四段、三个键 |
| `docs/API.md:231,314-321,420-421,465`、`docs/FRONTEND.md:87,258,292,298`、`docs/DEPLOY.md §4/§9`、`deploy/env.example`、`docs/DESIGN.md §9`、`docs/ops.md:198`、`ATTRIBUTION.md:54-59,76` | 契约与运维文档 |
| `scripts/smoke.py:12,624`、`backend/wd/smoke_mock.py:35,91-103` | 不变式加 `with_ai_image`；`open.bigmodel.cn` 与 `fake-cdn.example` 路由 |

---

## 5. 测试与验收

### 5.1 会变红的既有测试（必须随同一提交修；三份清单合并并补齐 [J-safety 要求 5]）

| 提交 | 测试 | 为什么红 | 改法 |
|---|---|---|---|
| C3 | `backend/tests/unit/test_schemas.py:122-127 test_prompts_are_verbatim_from_section_5[svg_system]` | 提示词文件变了 | 同步 `CLAUDE_INTEGRATION.md:281-283` 代码块（逐字节，`rstrip("\n")`） |
| C3 | `backend/tests/integration/test_images.py:608-623 test_activate_svg_sanitises_and_serves_a_svg_image`（`:616` `"<text" in stored`） | `claude_svg` 去文字 | 改为 `"<text" not in stored and '<desc id="aigc-label">' in stored`，并断言 `row["text_free"] == 1` 且 `row["prompt_version"] is None`（该测试不传版本；版本/模型写入由新测试 `test_svg_activation_records_prompt_version_model_and_text_free` 覆盖） |
| C3 | `backend/tests/unit/test_config.py:25-39 test_defaults_without_environment`、`test_deploy_files.py:119-134 test_env_example_covers_every_setting_exactly_once`、`:136 test_env_example_defaults_build_the_default_settings`、`test_docs_contract.py:114-133 test_deploy_config_table_names_every_setting` | 新 `Settings` 字段 `image_kid_stages` | `env.example` 与 DEPLOY §4 各加一行；`test_defaults` 加 `cfg.image_kid_stages == ()` |
| C4 | `backend/tests/unit/test_schemas.py:122-127 […][content_system]` | 提示词文件变了 | 同步 `CLAUDE_INTEGRATION.md:210-226` |
| C4 | `backend/tests/unit/test_content_apply.py:81` `prompt_version == "content-v1"` | 版本号 | 改为 `== content.PROMPT_VERSION`；`:80` 键集合不变 |
| C5 | `backend/tests/integration/test_images.py:535-547 test_keywords_come_from_content_with_blocklist_and_shape_filter` | `chart` 的 lemma token 现在豁免 `NON_PHOTO`：`set_content(["bar chart", …])` 的 `"bar chart"` 不再被滤掉，第一次请求变成 `"bar chart filetype:bitmap"` | 把夹具词改为 `apple` + 关键词 `["bar chart", …]`（`chart` 非 lemma → 仍滤掉，断言不变），并新增 `test_lemma_token_is_exempt_from_the_non_photo_blocklist`（词 `chart`，`"bar chart"` 保留） |
| C5 | `backend/tests/unit/test_select.py:71 test_hard_rejects`（`description: "Screenshot of an app"` → `blocklist`） | 签名变（`allow`/`style` 关键字默认值） | 不红；但 `select.is_blocked` 直接调用处（`grep` 40 处引用集中在该文件）改用关键字参数 |
| C7 | `backend/tests/unit/test_scheduler.py`（`maintenance(` 调用） | `TickResult` 新字段默认 0 | 不红；加一条 `image_retries` 断言 |
| C7 | `backend/tests/unit/test_cli.py:50-58` | `COMMAND_OWNERS` 与注册命令集合必须一致 | `cli.py:54` 加 `images-retry` 的同时 `register_cli` 注册，否则红 |
| C8 | `backend/tests/unit/test_providers.py:46-68 test_wikimedia_request_shape_and_user_agent`（`:57-64` 参数字典全等） | `iiprop` 加 `thumbmime`、新 `maxlag` | 更新字典 |
| C8 | `backend/tests/unit/test_providers.py:172-190 test_openverse_request_shape_and_parse`（`:178` `"page_size": "20"`） | 10 | 更新 |
| C8 | `backend/tests/integration/test_images.py:162`（Openverse 参数整字典 `"page_size": "20"`） | 10 | 更新（EF/GF 漏列，PE 列了 [J-learner §0 第 5 条]） |
| C8 | `backend/tests/unit/test_providers.py:2` 文档串「page_size 20」 | 文字 | 改 10 |
| C8 | `backend/tests/unit/test_providers.py:70-88 test_wikimedia_parses_the_legacy_fixture_as_captured` | 夹具无 `thumbmime` → 回退 `mime` → 不红 | 回归确认（`grep -c thumbmime backend/tests/fixtures/wikimedia_search.json` = 0） |
| 三期 | `backend/tests/unit/test_api_schemas.py:113`（`AdminOverviewWords` 字段集合）、`:108` 不变；`backend/tests/integration/test_admin_ops.py:144`；`test_images.py:626-635 test_photo_mix_counts`；`test_providers.py:374-384 test_build_chain_respects_order_keys_and_unknown_names`；`test_config.py:101-107`；`test_deploy_files.py:119,136`、`test_docs_contract.py:114`（8 个新变量）；`scripts/check_contract.py`（`ImageProviderName` 联合顺序）；`frontend/src/i18n/zh.test.ts`、`zh.contract.test.ts`；前端 6 个 `ImageMeta` 夹具（`study/queue.test.ts:33`、`components/study/StudyCard.test.tsx:11`、`components/bank/AttentionBadge.test.tsx:57`、`pages/WordDetailPage.test.tsx:85`、`pages/StudyPage.test.tsx:38`、`pages/AddWordsPage.test.tsx:62`——`provider` 改为 `ImageProviderName` 类型后仍是 `'card_svg'`，tsc 不红，但 `with_ai_image` 进 `AdminOverview` 夹具处要补）；`scripts/smoke.py:624` | 契约变更 | 同一提交 |

不受影响：`backend/tests/unit/test_sanitize_svg.py`（`clean()` 默认 `allow_text=True`；`:124` `<rect></svg>` 与 `:103-112` 实体用例在 `&` 修复后仍 `SvgRejected`；`:158-170` `A &amp; B` 不被双重转义）、`test_card_svg.py`、`test_quota.py`、`test_media.py`、`test_budget.py:33`（`ESTIMATES` 不动）、`test_select.py:92-131`（默认候选不触发新信号）、`test_images.py:139,540,545`（默认 neutral 轮 `filetype:bitmap`）、`test_db.py:41-56`（25 张表不变）、`test_db.py:236-257`（0012 自动纳入 `shipped_migrations()`，`_counts` 不含 `word_images`——所以 C2 必须自带行数断言）。

### 5.2 要加的测试

- `tests/unit/test_sanitize_svg.py`：`test_bare_ampersand_is_repaired_before_parse`（`<title>A & B</title>`、属性值 `fill="url(#a&b)"` 的裸 `&` → 通过且输出 `&amp;`；`&amp;`/`&#38;`/`&lt;` 不重复转义；`&nbsp;` → `&amp;nbsp;` 字面量、不再拒收）；`test_allow_text_false_drops_text_and_tspan_but_keeps_title_desc`；`test_with_label_inserts_one_desc_after_root`（输出恰含一个 `id="aigc-label"`；模型自带 `id="aigc-label"` 的属性被 `_clean_attrs` 丢弃）；`test_entities_still_rejected_after_repair`。
- `tests/unit/test_style.py`（新）：`dominant_pos("n:4/v:96") == "v"`、`dominant_pos("n:50/v:50") == "n"`、`dominant_pos(None) is None`、`dominant_pos("v./n.") is None`；`skip_image` 对 `i:100`、`c:100`、`d:97/n:3` 真，`n:…`、`v:…`、`r:…`、`m:…`、NULL 假；`allows_bare_lemma` 对 `r:100` 假、`n:100` 真；`stage_code(1) == "zk"`、`stage_code("xs") == "xs"`、`stage_code(None) is None`、`stage_code(99) is None`；`style_for` 对 `image_kid_stages=()` 恒 `neutral`，`("zk",)` 下 `stage_min=1` → `kid`、`stage_min=3` → `neutral`。
- `tests/unit/test_config.py`：`WD_IMAGE_KID_STAGES=""` → `()`；`"zk, gk"` → `("zk","gk")`；`"xx"` → `ConfigError`；`entries()` 输出 `WD_IMAGE_KID_STAGES`。
- `tests/unit/test_select.py`：`test_non_photo_words_are_allowed_when_they_are_query_tokens`（`reject_reason(cand(title="Map of Europe"), allow=frozenset({"map"})) is None`；无 `allow` → `"blocklist"`；`UNSAFE` 永远拒）；`test_kid_style_rejects_kid_unsafe_words`；`score` 新信号各一条（description 命中 +1、category 一致 +1 / 相反 −1、人像 kid −2 / neutral 0、texty −1、竖图 −1）；`test_score_table` 原断言保持。
- `tests/unit/test_providers.py`：`test_wikimedia_maxlag_body_becomes_a_503_provider_error`（200 + `{"error":{"code":"maxlag",...}}` + `Retry-After: 5` → `ProviderError(status=503, retry_after_s=5)`；无头 → 30）；`test_wikimedia_kid_style_uses_drawing_and_thumbmime_as_candidate_mime`（内联夹具 `thumbmime: image/png`, `mime: image/svg+xml` → 候选 `mime == "image/png"` 且过 `select.reject_reason`）；`test_openverse_page_size_follows_limit_and_category_for_kid`；`test_pixabay_image_type_follows_style`。
- `tests/integration/test_images.py`：`test_function_word_without_admin_override_gets_the_card_and_no_provider_call`（`insert_word(conn, "of", pos="i:100")` → `mock_http.calls == []`、`image_state == "failed"`、无 `generate_svg`）；`test_function_word_with_admin_query_is_fetched`；`test_adverb_without_content_keywords_skips_the_bare_lemma_search`；`test_kid_stage_word_tries_drawing_then_bitmap`（`cfg = replace(cfg, image_kid_stages=("zk",))`，`stage_min=1`：第一次 Commons 请求 `gsrsearch == "cat filetype:drawing"`，第二轮 `bitmap`）；`test_default_chain_shape_is_unchanged_except_thumbmime_maxlag_page_size`；`test_admin_query_dropped_by_shape_rule_is_reported`（`detail` 含 `query ignored`）；`test_svg_prompt_carries_scene_example_hook_and_style`（`build_user_prompt` 快照）；`test_svg_activation_records_prompt_version_model_and_text_free`；`test_failed_word_is_retried_when_marked_unfamiliar_after_six_hours`（`frozen_clock` +6 h；1 h 内不重抓；live 任务存在不重抓；功能词永不重抓）；`test_retry_is_capped_at_three_per_thirty_days`；`test_nightly_retry_requeues_only_studied_failed_words_within_limit`；`test_cli_images_retry_dry_run_lists_candidates`。
- `tests/unit/test_db.py`：C2 的 `test_0012_adds_word_images_meta_columns_and_keeps_rows`（§4.1）；三期 `test_0013_rebuild_keeps_rows_ids_indexes_and_accepts_ai_image`（基线 + 0012 + 31 行样本 → `run_migrations`：id 不变、三个索引在、`words.active_image_id` 全部可解析、`provider='ai_image'` 可插、`'flickr'` 被拒、`text_free` CHECK 仍在）。
- `tests/unit/test_content_apply.py`：`test_example_of_10_to_14_chars_is_now_kept`（12 字符保留、9 字符丢弃）；`test_lemma_token_is_exempt_in_image_keywords`（词 `map`，关键词 `"world map"` 保留）。
- 第二期：`tests/unit/test_ai_image_provider.py`（`fake_image_gen.transport`：请求体 `watermark_enabled is True`、`size == "1344x768"`、`n == 1`；`url`/`b64_json` 两种响应；`content_filter level>0` → `content_filter_max > 0`；401/429/503 → `ProviderError(status, retry_after)`；key 不出现在日志与 `calls`）。
- 第三期：`test_images.py::test_ai_image_first_in_kid_chain_generates_before_photos`、`::test_ai_image_never_runs_at_prewarm_priority`、`::test_ai_image_filtered_falls_through_to_svg`、`::test_ai_image_row_shape`（`provider='ai_image'`、`license='generated'`、`creator=model`、`prompt_version='ai-v1'`、`text_free=0`、`mime='image/jpeg'`）、`::test_jpeg_carries_aigc_xmp_and_comment`（Pillow 读回 `info["comment"]`、XMP 含 `generated="true"`）、`::test_photo_mix_counts_ai_image`；`test_config.py::test_image_gen_requires_full_config_when_listed`、`::test_image_providers_kid_defaults_to_main_chain_without_pexels`；前端 `StudyCard.test.tsx` 加 `provider: 'ai_image'` 题注用例。

### 5.3 在 live-copy 的私有拷贝上排练（永远不碰 `/Users/sqin/word-dance-data`；一律走 `.venv/bin/python` 的 `run_migrations`，不用 `/usr/bin/sqlite3`——其 `legacy_alter_table=1` 会掩盖重建问题 [INDEX A4]）

```
SP=/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad
MINE=$SP/synth-images/rehearsal; mkdir -p $MINE/data
/opt/homebrew/bin/python3.12 -I -c "import sqlite3; s=sqlite3.connect('file:$SP/live-copy.db?mode=ro', uri=True); s.execute(\"VACUUM INTO '$MINE/data/word-dance.db'\")"
cd /Users/sqin/word-dance
WD_DATA_DIR=$MINE/data .venv/bin/wd migrate --dry-run        # 期望列出 (12, 'word_images_meta')（阶段模型先合入时还有 11）
WD_DATA_DIR=$MINE/data .venv/bin/wd migrate
sqlite3 -readonly $MINE/data/word-dance.db "PRAGMA table_info(word_images); SELECT COUNT(*), SUM(text_free), SUM(prompt_version IS NULL) FROM word_images; PRAGMA integrity_check; PRAGMA foreign_key_check;"
#   期望：27 列；31 | 0 | 31；ok；空
WD_DATA_DIR=$MINE/data WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 .venv/bin/wd images-retry --dry-run          # 期望 ≤ 17 个词：副本时刻 17（employee 不在学；功能词不出现）；`word_is_studied` 的开放批次窗口只有 2 天（service.py:26），排练日期越晚、只靠批次在学的词越少
WD_DATA_DIR=$MINE/data WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 WD_AI_ENABLED=1 WD_CLAUDE_BIN=backend/tests/fake_claude.py .venv/bin/wd fetch-image have --provider claude_svg && WD_DATA_DIR=$MINE/data WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 .venv/bin/wd worker-once   # 假 claude 可执行文件（PE §5.3 第 5 步同法）
sqlite3 -readonly $MINE/data/word-dance.db "SELECT provider, prompt_version, model, text_free FROM word_images ORDER BY id DESC LIMIT 1;"   # claude_svg | svg-v2 | … | 1
grep -c "<text" $MINE/data/images/*/$(sqlite3 -readonly $MINE/data/word-dance.db "SELECT sha256 FROM word_images ORDER BY id DESC LIMIT 1").svg   # 0
WD_DATA_DIR=$MINE/data WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 .venv/bin/wd fetch-image of --no-svg          # status: skipped, detail: function word: card only；MockHttp.calls 为空
```
第三期在同一拷贝上追加 `0013`：`SELECT sql FROM sqlite_master WHERE name='word_images'` 含 `'ai_image'`；`SELECT COUNT(*) FROM words WHERE active_image_id IS NOT NULL AND active_image_id NOT IN (SELECT id FROM word_images)` = 0；`WD_IMAGE_GEN_KIND=openai_images WD_IMAGE_GEN_BASE_URL=https://open.bigmodel.cn/api/paas/v4 WD_IMAGE_GEN_MODEL=cogview-3-flash WD_IMAGE_GEN_API_KEY=fake WD_IMAGE_PROVIDERS_KID=ai_image,wikimedia,openverse WD_IMAGE_KID_STAGES=xs WD_SMOKE_MOCK_HTTP=1 wd fetch-image <小学词> --provider ai_image` → `provider: ai_image`，文件为 JPEG 且 Pillow 读到 `comment`。

### 5.4 验收标准

- 第一期：`make test` 全绿（Mac 上既知红的 `test_deploy_files.py` 19 个与 `test_config.py::test_defaults_without_environment` 按记忆忽略）；`python scripts/check_contract.py` 「contract OK」（第一期不改契约）；`npm test`、`npm run lint`（`scripts/check-copy.mjs`）不变；`make smoke` 通过；新 SVG 文件 0 个 `<text`、恰 1 个 `aigc-label`；部署后连续 20 次 `generate_svg` 拒收 ≤ 1；第一次 03:30 维护 journal 出现 `image_retry` 事件且 48 h 内 18 词的 `failed` ≤ 3；`WD_IMAGE_KID_STAGES` 未设时线上请求形状只多 `thumbmime`/`maxlag`/`page_size=10`，`provider_usage` 日计数不高于改前同口径。
- 第二期：`scores.csv` 两评分者 κ ≥ 0.6；`report` 子命令按 §3.6.4 逐条输出 PASS/FAIL；儿童小样本记录表完整。
- 第三期：`check_contract.py` 对 `ImageProviderName` 联合比对通过；`make smoke` 的 `with_photo + with_claude_svg + with_ai_image + card_only == with_content`；`wd check providers` 列出 `ai_image` 与两条链；真 key 对 3 个小学词各生成一张并目检水印、题注「AI 生成配图」、`SELECT provider, creator, prompt_version, text_free FROM word_images ORDER BY id DESC LIMIT 3`。

---

## 6. 上线与回滚（Mac，launchd；与 `docs/DEPLOY.md` Linux 版的差异：无 `install.sh`/`systemctl`，服务是 launchd agent，`wd serve` 启动时自动 `run_migrations`（先 `backup.snapshot_before_migrate` 快照）再 `seed_check`；label 与路径按 memory `macos-local-install.md`）

**第一期（附加迁移 0012，停机 < 1 分钟）**
1. `cd /Users/sqin/word-dance && git pull`（或合并分支）；`make test`。
2. `launchctl bootout gui/$(id -u)/<word-dance label>`；`pgrep -fl "wd serve"` 为空。
3. `WD_DATA_DIR=/Users/sqin/word-dance-data .venv/bin/wd backup --with-images`（手工全量；`wd migrate` 还会自动写 `backups/pre-migrate-10-to-12.db.gz`——阶段模型先上时为 `11-to-12`）。
4. `WD_DATA_DIR=… .venv/bin/wd migrate --dry-run` → 只列 `(12, 'word_images_meta')`；`.venv/bin/wd migrate`。
5. `.env` 不改（`WD_IMAGE_KID_STAGES` 缺省 = 关；**不**在生产上把它当试点开关——试点在私有拷贝上做，D-images-5）。
6. `wd import-seed`：不需要（种子未变）；若与阶段模型同批上线，按其顺序「migrate → import-seed」。
7. `launchctl bootstrap gui/$(id -u) <plist>`；`curl --noproxy '*' http://127.0.0.1:8000/api/health`；`WD_DATA_DIR=… .venv/bin/wd check providers`。
8. 验证：`sqlite3 -readonly <db> "PRAGMA table_info(word_images)"` 含四列；管理页概览 `images.providers` 正常；对一个在学的初中词 `wd fetch-image <lemma> --provider claude_svg`（≈ $0.012）→ 文件无 `<text`、含 `aigc-label`、行 `prompt_version='svg-v2'`、`text_free=1`；`tail -f ~/Library/Logs/word-dance/*.log | grep -E 'svg_rejected|svg_repaired|image_retry|query_ignored'`；次日查 18 个 failed 词的 `image_state` 与 `jobs` 里 `retry=true` 的结果。
9. 回滚：`launchctl bootout` → `git checkout 75df534` → `launchctl bootstrap`。新列对旧代码无害（显式列名 INSERT、`SELECT wi.*`）；新写入的 `prompt_version`/`text_free`、`jobs.payload_json` 的 `retry:true`、`word_contents.prompt_version='content-v2'` 对旧代码都是不读的值；`.env` 没有新键。只有迁移本身失败才 `wd restore backups/pre-migrate-*-to-12.db.gz`（运行器失败会整文件回滚，不留 bookkeeping 行，`db.py:241-244`）。

**第二期**：不碰生产；试点机器与拷贝见 §3.6.2；智谱 key 只在试点机 `.env`（0600 文件）。

**第三期（重建迁移 0013，停机 < 1 分钟）**
1–3 同第一期；4. `.env` 先加 `WD_IMAGE_GEN_KIND="none"`（默认即关，仅为迁移上线）；`wd migrate --dry-run` 只列 `(13, 'word_images_ai_provider')`；`wd migrate`；`SELECT COUNT(*) FROM word_images` 与迁移前相等。5. `npm ci && npm run build`（契约提交含前端）。6. 起服务；管理页 `words.with_ai_image = 0`。7. 启用：`.env` 写 `WD_IMAGE_GEN_KIND="openai_images"`、`WD_IMAGE_GEN_BASE_URL="https://open.bigmodel.cn/api/paas/v4"`、`WD_IMAGE_GEN_MODEL="cogview-3-flash"`、`WD_IMAGE_GEN_API_KEY_FILE="<0600 文件>"`、`WD_IMAGE_PROVIDERS_KID="ai_image,wikimedia,openverse"`（按 §3.6.4 第 3 条的结论定首位或链尾）、`WD_IMAGE_KID_STAGES="xs"`，重启。8. 回滚：旧代码的 `ImageMeta.provider` Literal 不含 `ai_image`，已生成的行会让 `/api/words/{id}` 500——**先**执行 GF 的中和 SQL：`UPDATE word_images SET status='rejected' WHERE provider='ai_image' AND status='active'; UPDATE words SET active_image_id=NULL, image_state='failed' WHERE active_image_id NOT IN (SELECT id FROM word_images WHERE status='active');` 再回代码；或 `wd restore backups/pre-migrate-12-to-13.db.gz`（丢回滚窗口内的学习记录）。

---

## 7. 风险、待拍板问题、工作量

### 7.1 风险

1. 「无文字」让抽象词的 SVG 更难辨认（`particularly` 一类本来就靠文字兜底）——缓解：功能词不配图、副词不搜裸 lemma、试点 R1 直接测量、不达标的层退回模板卡。
2. 4 次拒收的根因是推断（`ai_calls.stdout_path` 在禁区）——缓解：`&` 修复 + 提示词双保险 + `svg_repaired`/`svg_rejected` 事件可观测。
3. Commons `filetype:drawing` 命中含结构图（`Apple structure.svg`）、Openverse 插画多为 < 400×300 的剪贴画 [verify images-pipeline-31；verify image-memorability 遗漏 5]——缓解：默认关、试点 A 臂量化、门槛 2/5。
4. 初中词例句改校园语域对成人用户 1 同样生效——Q-img-7。
5. 两轮抓取耗 Openverse 匿名配额（160/日）——缓解：默认关；小学阶段落地前注册 Openverse 应用。
6. `maxlag` 路径未对真实 API 验证——缓解：只在 `error.code=="maxlag"` 触发、`Retry-After` 或 30 s、单元测试。
7. 第一晚重试集中入队——≤ 17 词、上限 50、priority 30、IoWorker 串行（`worker.py:359-362`）。
8. 智谱返回 URL 的主机能否过 SSRF 规则、`b64_json` 是否可用——试点第一天验证；两条路径都写。
9. 标识合规字段与主体定性未定、重编码丢厂商隐式水印——Q-img-4；试点图片不公开分发。
10. 与阶段模型线的文件重叠：`content_system.txt`（我们 1/3/5/6/7 条，他们第 1 行与第 8 条）与 §5.1 同步、`STAGE_ZH`——§8.1 的落地顺序规则。
11. `WD_IMAGE_KID_STAGES` 校验依赖 `schemas.STAGE_ORDER`；若阶段模型选「阶段即数据」，校验要改为查 `stage_defs`——§8.1。

### 7.2 仍需产品负责人拍板的问题（每个都给默认，实现先按默认进行）

| # | 问题 | 默认（实现据此进行） |
|---|---|---|
| Q-img-1 | `zk`（初中）是否也用儿童风格 / 插画优先 | 否：试点后默认只含 `xs`；若要含 `zk`，改 `.env` 一行，无代码 |
| Q-img-2 | 是否要做「图→词产出模式」（正面只出图、隐藏词头、学习者产出英文词）这一新学习模式 | 不做（第四期候选）；`text_free` 列已预留为门 |
| Q-img-3 | 智谱 BigModel 账号/key 由谁申请、放哪台机器、试点出口 | 产品负责人注册；试点在东京 Lighthouse 盒或进程环境无 `HTTP(S)_PROXY` 的 Mac 上跑 |
| Q-img-4 | 《标识办法》下本应用的主体定性与 GB 45438-2025 元数据字段名 | 按「传播者」从严：`<desc id="aigc-label">` + XMP 自定义字段 + 题注 + 厂商水印；公网上线前法务核对字段名 |
| Q-img-5 | 30 张旧 SVG 是否一次性重画（≈ $0.42） | 否 |
| Q-img-6 | 是否做 5–8 名小学生的看图说义 + 24 h 回忆小样本（需监护人同意） | 做；非正式、预注册为否决条件 |
| Q-img-7 | 接受初中词例句改为校园/日常语域（按词生效，影响学 zk 词的成人） | 接受 |
| Q-img-8 | 「不合适」举报阈值 1 → N 个不同用户（WLC 阶段 C）在 K-12 邀请前是否必须完成 | 必须（归词库线，本线不动代码） |
| Q-img-9 | 是否在小学阶段落地前注册 Openverse 应用（10,000/日） | 是 |
| Q-img-10 | 第三期 `ai_image` 是否允许出现在成人链 `WD_IMAGE_PROVIDERS` | 允许配置、默认不配；证据偏向成人可不配图 |

### 7.3 工作量（人日）

| 项 | 人日 |
|---|---|
| 一期：C1 0.2；C2 0.4；C3（提示词 + §5.5 + sanitizer + store + svg.py + style.py + 配置 + 测试）1.6；C4 0.5；C5 0.8；C6 0.4；C7（服务函数 + 三挂点 + 夜间 + CLI + 测试）1.2；C8（接口 + 四 provider + `get_json_with_headers` + 两轮 handler + 测试 + 文档）1.6；排练与上线 0.3 | **≈ 7** |
| 二期：适配器 + fake + `gen_prompt` + 单测 1.5；试点脚本（抽样 / 内容 / 四臂 / 评分页 / 报告）1.5；跑四臂与两人评分 1.0；VLM 评分 0.5；儿童小样本组织与两晚测试 1.0 | **≈ 5.5**（+ ≈ $3.3） |
| 三期：链接入 + `_generate_round` + quota/diag 1.5；0013 + 测试 0.5；8 个配置 + env/DEPLOY 0.7；契约提交（`types.ts` 提类型 + 4 点 + 6 夹具 + i18n 两测试 + API/FRONTEND 文档）2.5；XMP/COM 标识 0.7；`with_ai_image` 管理页 + smoke 0.6；硬编码清理 0.5；smoke_mock 路由 + 排练 + 上线 1.0 | **≈ 9** |
| 合计 | **≈ 21.5**（一 + 二 ≈ 12.5 可在无拍板状态下推进；三期以门槛为条件） |

---

## 8. 对其他两条线的依赖与接口

### 8.1 阶段模型与地区维度（`design/stage-model/`）

1. **迁移编号**：本线取 0012（一期）与 0013（三期），0011 留给阶段模型；两线谁先合入都可（`db.pending_migrations` 按未记录集合选文件，`db.py:187-189`）；若同批上线，同一停机窗口内按编号顺序应用；快照名 `pre-migrate-<from>-to-<to>` 取 max，可能出现 `12-to-11`，无害。
2. **`words.stage_min` 的表示**：本线通过 `style.stage_code()` 同时接受整数索引（经 `schemas.index_to_stage`，`schemas.py:64-67`，其范围检查必须随新阶段数扩大）与字符串码（阶段即数据路线）。接口要求：阶段模型线保证 `schemas.STAGE_ORDER`（或替代物）在导入 `wd.schemas` 时可用且含小学码（`xs`）；若改为 `stage_defs` 表，`config.from_env` 对 `WD_IMAGE_KID_STAGES` 的校验改为延迟到首次 `style.style_for` 并记一次 `ConfigError` 级日志（本线负责改）。
3. **`content.STAGE_ZH`（`content.py:49`）与 `content_system.txt`**：「小学」标签、第 1 行受众句、第 8 条难度尺子、`AUDIENCE`（`content.py:48`）归阶段模型线；本线改第 1/3/5/6/7 条。两线都要求 `CLAUDE_INTEGRATION.md §5.1` 逐字节同步——**后合入者负责重新同步代码块**，并在 PR 里跑 `test_schemas.py::test_prompts_are_verbatim_from_section_5`。`STAGE_ZH` 不加 `xs` 时 `prompt_entry` 的 `STAGE_ZH[s]`（`content.py:88`）对带 `stage_xs=1` 的词会 `KeyError` [verify ai-prompts-stages 遗漏 1]——这是阶段模型线的验收项，本线依赖它。
4. **`WD_IMAGE_KID_STAGES` 默认值**只在 (a) `xs` 码存在且已随种子重导写入 `stage_xs`/`stage_min` 并且 (b) 试点达标后改为 `("xs",)`；在此之前小学词按 neutral 风格处理。
5. 本线**不**读 `user_settings.current_stage`/`stages_json`，用户 1/2 的重编号与本线无关（D-images-14 之后再无用户设置列）。
6. `index_to_stage(int(row["current_stage"]))`（`security.py:597`）等阶段模型线的改动不影响本线；`schemas.StageIndex`、`WordBrief.stage_min` 本线不用。

### 8.2 词表来源与种子流水线（`design/word-lists/`、已交付的 `data/lists/`）

1. **试点样本框** = `data/lists/moe-2022-level2.txt`（505 行，`#` 注释；并列与括注的拆分规则以 `data/lists/moe-2022.README.md` 为准，脚本只取每行第一个词头并 `normalise_lemma` 后匹配 `words.lemma`，在库 498）。词表线若调整该文件格式，脚本的解析函数同步。
2. **`words.pos`** 来自 ECDICT 种子列（`seed.py` 20 个种子列之一），重标阶段不改它；`FUNCTION_POS`/`dominant_pos` 依赖它保持 `n:4/v:96` 格式（`0001_init.sql:174`）。
3. 若词表线把上海初中 331/342 个**词组**以 `kind='phrase'` 入库：`pos` 为空 → `dominant_pos()` 为 None → 不跳过、允许裸 lemma 搜索（短语作查询词合理）；无需本线改动。
4. 种子重导（`wd import-seed`）从不触碰 `word_images`/`word_contents`（`docs/WORD_LIBRARY_CURATION.md §1.2`），本线的列与行不受影响；`kv.seed_version` 被阶段模型 0011 删除以强制重导，与本线无关。
5. 内容包导入（WLC 阶段 C）必须写 `prompt_version='content-v2'`（`docs/WORD_LIBRARY_CURATION.md:183` 现写 `content-v1`，C4 改为「当前 `PROMPT_VERSION`」）；导入的配图行建议带 `prompt_version`/`model`/`text_free`（三列可空，不带也兼容）。
6. 「不合适」阈值（WLC 阶段 C）与 `wd images-prune` 的导入来源识别（WLC 评审遗漏项）归词库线；本线只在 ops 文案提醒。

### 8.3 本线对外提供的接口（供两线与后续引用）

- `wd.images.style`：`dominant_pos(pos)`、`skip_image(word)`、`allows_bare_lemma(word)`、`stage_code(stage_min)`、`style_for(word, cfg)`、常量 `FUNCTION_POS`、`STYLES`。
- `wd.images`：新增导出 `retry_if_failed(conn, word, *, priority, now)`、`retry_failed_studied(conn, now, *, limit, priority, dry_run)`。
- `wd.images.select.is_blocked(text, *, allow, style)` 的新签名（`content.py` 唯一外部调用者已在 C5 改）。
- 配置：`WD_IMAGE_KID_STAGES`（一期）；`WD_IMAGE_GEN_*` 7 项 + `WD_IMAGE_PROVIDERS_KID`（三期）。
- 数据：`word_images.prompt_version / model / text_free / eval_json`（0012）；`provider` 取值加 `ai_image`（0013）。
