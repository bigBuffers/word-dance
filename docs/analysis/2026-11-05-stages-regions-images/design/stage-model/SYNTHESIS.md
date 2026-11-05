# 阶段模型与地区维度 — 综合设计（已决定）SYNTHESIS

基线：仓库 `/Users/sqin/word-dance`，`main @ 75df534`（只读）；线上只读副本 `scratchpad/live-copy.db`（9,162 词、2 用户、`schema_migrations` 1/8/9/10）；词表任务已交付的 `data/lists/`（未跟踪，8 个数据文件 + 3 份 README）；日期 2026-11-06。
输入：三份设计（`minimal-delta.md`、`stages-as-data.md`、`learner-first.md`）与三份评审（`judge-data-safety.md`、`judge-learner-product.md`、`judge-maintainer.md`）全部读完；本文引用的每一处代码位置都按 75df534 重新打开核对（§10 列出核对清单）。
本文自己跑过的东西（全部在 `scratchpad/synthesis-stage-model/`，只读 `live-copy.db`，从不触碰 `/Users/sqin/word-dance-data`）：
- `0011_primary_stage.sql`（§3.4 全文）+ `rehearse.py`：用 `.venv/bin/python -I`（SQLite 3.54.1）调真实 `wd.db.run_migrations`，在 `live-copy.db` 的私有拷贝上**一次通过**（0.050 s），并在空库上 0001→0011 通过；结果见 §5.4。
- `membership_v4.py` → `membership.json` / `final.json`：按 §3.8 决定的归一化规则，用交付的 `data/lists/*` 对只读副本重算成员关系；下文标「**模拟**」的数字全部来自这一次运行（最终以 `relabel_seed.py` 生成的 `stats.json` 为准）。
- `shasum -a 256` 核对 `scratchpad/ecdict-dl/ecdict-sqlite-28.zip` = `ea01f76a…f3f6`，与 `deploy/fetch_ecdict.sh:13` 钉死的值**相同**——三份评审都说「本机没有 `stardict.db`」，实际 `scratchpad/ecdict-dl/extract/stardict.db`（851,288,064 B）就是已校验的正版；`scratchpad/seed-pipeline/dl-ecdict-csv/ecdict.csv`（66,009,548 B）也在。

文风约定：每条决定写「决定 / 理由 / 依据 / 被否决的替代」；不留「可以考虑」。引用格式 `[INDEX A3]`、`[verify stage-model-13]`、`judge-X §n`、`path:line`。

---

## 0 一页结论

**模型**：沿用 `stage_*` 布尔列 + 整数 `stage_min`，加一列 `stage_xs`；阶段枚举 `("xs","zk","gk","cet4","cet6")`，整数索引**重编号 1..5**（xs=1 … cet6=5），映射改为显式字典并用测试钉住「索引 = 位置 + 1」。一个停机迁移 `0011_primary_stage.sql`（已排练）。**不做** `stage_defs`/`word_stage_tags`、**不做**「上海/全国」维度、**不做**「拓展/超纲」阶段；所有回填信息保留在 `words.sources` 令牌里（§3.3）。

**词集**（A1–A3，用交付的官方词头文件）：`xs` = 课标 2022 二级 505 ∪ 2022 附表的数词/月份/星期；`zk` = 课标三级 1600 ∪ 上海考试院 2020 单词表 ∪ 两份附表（代词/数词/月份星期/国家国籍/学科/地理名称/缩写/节日）∪ `xs`；`gk` = 高中课标 2025 修订 3100 ∪ 2020 修订 3000 ∪ 两份国家附表（仅限已在库的词头）；`cet4/cet6` 不变。ECDICT 的 `zk/gk` 标签与 mahavivo 中考/高中两表不再授予阶段。归一化（括号注、斜杠/等号并列、英美变体、句点缩写、连字符、大小写、重音）**写进构建器**，不推给词表任务；官方词头不在库的 **47 个**新建词头（词典字段来自已校验的 `stardict.db`，4 个释义不对的用人工记录），**绝不**把 `excited` 之类映射到 `excite`。

**老词**：重标不剔除；模拟下 227 个词失去全部阶段（0 个有内容/配图，0 个被两位用户持有），只在「全部」页签可见，详情页显示「课标外」芯片。

**默认与老用户**：新用户 DDL 默认 `'["xs","zk"]'` / `current_stage 1`（主攻小学）；欢迎页加「小学生」角色，「初中生」预设改为 `xs+zk`/主攻 zk；线上两行只做 `current_stage + 1`（sqin 3→4=cet4，kimi 1→2=zk），`stages_json` 原样，不自动加 `xs`。

**模拟数字**（`live-copy.db` × 交付词表，§3.8 规则）：各阶段 xs 584 · zk 2,142 · gk 3,276 · cet4 4,722 · cet6 7,671；`stage_min` 分布 584 / 1,558 / 1,271 / 1,722 / 3,847 / NULL 227；词条 9,162 → 9,209；重导改写约 4,359 行 + 插入 47 行；`xs ⊆ zk` 成立，`zk ∖ gk` = 117（**不**作不变量）。

**工作量** ≈ 7 人日（§8.3）；一次 < 1 分钟的停机；没有「只回代码」的回滚（§7）。

**仍需产品负责人拍板的 11 个问题**各带默认值（§8.2），实现按默认先行。

---

## 1 逐条决定（D-stage-model-1 … 24）

### D-stage-model-1　骨架 = minimal-delta 的数据模型；stages-as-data 归档为目标模型
- **决定**：布尔列 + `stage_xs` + 重编号 1..5 + 单一 0011（minimal-delta D1–D3、D8）；不建 `stage_defs`/`stage_presets`/`word_stage_tags`，不做 `zk_ext/gk_ext`。stages-as-data §3.2–3.5 作为「目标模型」写进 `DESIGN.md §3.1` 一段，触发条件写死：① 产品拍板做每用户「上海/全国」方案（需要第二套 `stage_min`），或 ② 出现许可干净的教材词表要做「拓展」层（INDEX Q2-c），或 ③ 第三次要加阶段。届时用 `words.sources` 令牌一条 SQL 回填 tag 表（§3.3）。
- **理由**：三位评审一致把 minimal 排第一（data-safety 6.5、learner-product 7.4、maintainer 7.0），理由相同：爆炸半径最小、编译期门禁（`check_contract.py` 的 `Stage/StageIndex` 联合、tsc `Record<Stage,…>` 5 处、`zh.ts` 镜像）全部保留；stages-as-data 把门禁从编译期挪到运行期且 `Stage = str`、TEXT `stage_min` 引入「漏改比较按字典序静默错」一类错误（judge-data-safety §4.2-1/2），9 人日被两位评审上调到 11–14；A4 已决定本轮不做方案维度，它买不到本轮需要的东西（judge-learner-product §3.2）。
- **依据**：`[INDEX A3]` 四种办法比较、`[INDEX Q1]` 建议 a；judge-data-safety §6/§7-1、judge-maintainer §5、judge-learner-product §6。
- **被否决**：stages-as-data（原因如上）；learner-first 作为骨架（它与 minimal 同一模型，但验收不变量错误、迁移未排练——judge-data-safety §3.2）。

### D-stage-model-2　码名 `xs`；索引重编号 1..5；显式 `STAGE_INDEX` 字典 + 位置断言
- **决定**：`STAGE_ORDER = ("xs","zk","gk","cet4","cet6")`；`STAGE_INDEX = {"xs":1,"zk":2,"gk":3,"cet4":4,"cet6":5}`；`stage_to_index` 查字典，`index_to_stage` 范围 `1..len(STAGE_ORDER)`；新测试断言 `STAGE_INDEX[s] == STAGE_ORDER.index(s) + 1` 对每个 s 成立。
- **理由**：重编号是现有「位置推导」代码（`schemas.py:58`、`seed.py:208`、`ecdict.py:177`）的自然结果，`_STAGE_DISTANCE`（`screen.py:34-36`、`batches.py:60`）、`new_only`（`vocab.py:54-56`）、`COALESCE` 排序、芯片高亮（`StageChips.tsx:31`）零逻辑改动；「小学 = 0」要修 `screen.py:44`、`batches.py:272,698` 的 `int(x or DEFAULT)` 并永久背上 Python/JS 两侧「0 为假」风险；「追加 = 5」打破「索引 = 顺序」要在三处 SQL 加 CASE。显式字典是 learner-first 的改进（judge-maintainer §3.3 值得嫁接），让以后再插阶段时错位在测试里红而不是静默。`xx` 不能用：`test_screen.py:136` 把 `stage=xx` 当非法阶段探针。
- **依据**：`[INDEX A3]`、`[INDEX 矛盾 14]`、`[verify seed-pipeline O3]`（2 用户 / 49 行 difficulty 是历史最低代价）；minimal §3.1、learner-first §3.2。
- **被否决**：小学 = 0（陷阱）；追加 = 5（破坏不变式）；字符串码（D-1）。

### D-stage-model-3　单一迁移 `0011_primary_stage.sql` = minimal 的 SQL + `system_events('migration')`；不改写 `push_batches.settings_json`
- **决定**：§3.4 全文。相对 minimal 增加一行 `INSERT INTO system_events(kind, detail_json, created_at) VALUES ('migration', …)`；**不**采用 learner-first 的 `UPDATE push_batches … json_set(...)`。
- **理由**：`system_events` 的 `kind` 无 CHECK（`0001_init.sql:59-64`），0001 注释本就把 `migration` 列为事件种类，管理页事件表能看到迁移发生——零风险。`push_batches.settings_json` 是「当日所用设置的快照」（`0001_init.sql:387`），只写不读（`batches.py:314-318`，全仓库唯一写入点），快照里同时存着 `"stages": [...]` 码，含义可恢复；而 `json_set/json_type` 要求 SQLite ≥ 3.38，Linux 生产机版本未知（`[INDEX 未解决 10]`）——为 4 行只写不读的数据引入迁移失败风险不值。头注释写明「0011 之前的快照用旧索引」。
- **依据**：judge-data-safety §1 三份 SQL 复跑结论、§7-1；judge-learner-product §3.3-4（快照语义）；judge-maintainer §3.3（JSON1 版本）。本文 §5.4 排练：`system_events` 17→18。
- **被否决**：改写快照（版本风险 + 语义）；在文件内 `VACUUM`（运行器把文件包在事务里，`db.py:229-243`）。

### D-stage-model-4　新用户默认 `'["xs","zk"]'` / `current_stage = 1`（主攻小学）
- **决定**：DDL 默认如上；`bank.DEFAULT_STAGES = ("xs","zk")`、`bank.DEFAULT_CURRENT_STAGE = 1`，并加单元测试把两者与 `pragma_table_info('user_settings').dflt_value` 绑定；`WelcomePage.tsx:72-73` 兜底改为同一预设。
- **理由**：欢迎页在用户点「我是…」之前就按 `settings.stages` 预勾（`WelcomePage.tsx:72-73`），步骤 1 必须提交（`onboarding.py:25-45`、API.md 端点 13），所以默认值是「什么都不点就下一步」的孩子拿到的设置；首要受众是上海小学生；偏低的失败模式（高中生先看到小学词）一眼可见可改，偏高的（小学生拿到初中词）不可见（stages-as-data §2 A6 论证，judge-learner-product §4-2 采纳）。含 `zk` 的好处是初中生少点一下、且 `["xs","zk"]` 配 `xs` 合法（`schemas.py:361-362` 要求 `current_stage ∈ stages`）。
- **依据**：`[INDEX A7]`、`[INDEX Q6-a]`、`security.py:661-664`（注册只插三列吃 DDL 默认）、`bank.py:161-182`。
- **被否决**：learner-first 的主攻 `zk`（「初中人数最多」无来源，方向与首要受众相反）；stages-as-data 的 `["xs"]`（初中生多点一下，收益小）。

### D-stage-model-5　角色预设：加「小学生」；「初中生」含小学
- **决定**：`ROLE_PRESETS = { xs: {stages:['xs'], current:'xs'}, zk: {stages:['xs','zk'], current:'zk'}, gk: {stages:['zk','gk'], current:'gk'}, uni/pro 不变 }`；`ROLES = ['xs','zk','gk','uni','pro']`。
- **理由**：与现有「高中生 → 初中+高中」的向下含一级一致（`WelcomePage.tsx:33-38`）；推荐词排序先主攻再高阶再低阶（`DESIGN.md:350`），多含一级只是在后面多些简单词；`VocabPage` 的「仅初中新增（不含小学）」文案把差异说清（D-19）。
- **依据**：`[verify frontend-stages-14]`；judge-learner-product §4-5。
- **被否决**：高中生预设也含小学（505 个小学词对高三无价值）。

### D-stage-model-6　`difficulty` 1–5 尺子不动；词库难度排序改 `COALESCE(w.difficulty + 1, w.stage_min, 6)`
- **决定**：三份提示词、三个 JSON schema、四个 pydantic `Literal`、`schemas.py:47 Difficulty`、`types.ts:73`、DB CHECK 全不动；只改 `routers/vocab.py:78` 一行。
- **理由**：Claude 的 1=初中 在新索引空间恰好是 2，整体平移一格即对齐；排练库上 `SUM(difficulty + 1 = stage_min)` = 44/49（< 2、> 3），与迁移前 `difficulty = stage_min` 的 44/2/3 **逐项相同**（§5.4）。扩 6 级要动 ≈12 个文件 + `PROMPT_VERSION`，线上只有 49 行且全是四级词。
- **依据**：`[INDEX A5]`、`[INDEX Q5-a]`、`[ai-prompts-stages-14]`；minimal §3.2（三位评审均复现 44/49）。
- **被否决**：6 级尺子（代价/收益不成比例）；stages-as-data 的 `difficulty_hint` 列（无 `stage_defs` 表）。

### D-stage-model-7　词集的集合定义（含附表与 2020∪2025）
- **决定**（记号：L2/L3 = `moe-2022-level2/level3.txt`，A22 = `moe-2022-appendix.tsv`，SH = `shmeea-2020-junior.txt`，ASH = `shmeea-2020-junior-appendix.tsv`，H20/H25 = `moe-2020-senior.tsv`/`moe-2025rev-senior.tsv`，AH20/AH25 = 两份 `*-senior-appendix.tsv`）：
  - `xs` = L2 ∪ A22{数词-基数词, 数词-序数词, 月份, 星期}
  - `zk` = `xs` ∪ L3 ∪ SH ∪ A22{地理名称, 地理名称-派生, 缩写, 节日, 地名景点, 其他专有名词} ∪ ASH（全部节）
  - `gk` = H25 ∪ H20 ∪ AH25 ∪ AH20（附表三列各自成词头；只授予**已在库**的词头，不为国名新建记录）
  - A22{不规则动词} 不授予阶段（原形已在 L2/L3，过去式是屈折形式）；`cet4/cet6` 定义不变。
- **理由**：① 数词/月份/星期在 2022 课标附录「单独列出」（`moe-2022.README.md §3.3/§7-3`），不进 L2/L3 正文；若不处理，`monday`/`one`/`january` 只能从 H20 的无星级（义务教育 1500）进入 `gk`，小学页签里没有星期月份而高中页签里有——荒谬。这些词在 2020 高中表被标为义务教育阶段（level 0），在 2025 表因「2022 课标把它们列在字母表之外」被删（`moe-senior.README.md §8/§9-6`），归 `xs` 是对一手文件最保守的读法。② 其余附表（地名、国籍、缩写、节日）是义务教育阶段整体要求，没有二/三级标记，归 `zk`（而非 `xs`）。③ A2 原文「2025 修订 3100（含 2020 版 3000）」→ 并集；2025 删掉的 93 个词（数词/月份/星期/国名/`crayon`/`pupil`…）仍留在 `gk`，不让高中层出现「比上一版少 93 词」的断崖；`cs2020:*` 令牌单独记录，日后若只认 2025 改一行集合定义即可。④ 词表线三份设计里 official-purist 的集合代数与此相同（judge word-lists/data-safety §3-174 引述：`xs = L2 ∪ A_num ∪ A_cal`、`zk = L3 ∪ A_* ∪ SH_w`、`gk = HS3100 ∪ HS3000`）。
- **依据**：`[INDEX B2][B4][B5][C2]`；`moe-2022.README.md §4.4/§7`、`shmeea-2020-junior.README.md §4.3/§8.2`、`moe-senior.README.md §3/§8/§9`；模拟：附表为 xs 带来 63 个词、为 zk 带来 139 个、为 gk 带来 39 个。
- **被否决**：只用 L2/L3/SH/H25 主表（星期月份落到 gk）；国名新建词头（117 个附表词多为专名，`derive_kind` 会标 `proper_noun` 并以 `safe_for_sharing=1` 入库——minimal §2 A2-②）。

### D-stage-model-8　归一化规则进构建器，不推给词表任务
- **决定**：`scripts/relabel_seed.py` 按 §3.8.2 的 12 条规则解析交付文件原貌（括号注、`/`、`=`、`AmE`、`pl.`、句点缩写、连字符、大小写、重音、TSV `level` 列、附表类别）；词表任务交付的 8 个文件**一字不改**地消费。
- **理由**：三位评审一致判定三份设计的词表接口都与实际交付不符（judge-data-safety §5-3、judge-maintainer §1.4、judge-learner-product §4-3）；交付 README 明示「拆分规则留给种子构建阶段」（`moe-2022.README.md §4.2-4`、`shmeea-2020-junior.README.md §4.1-5`、`moe-senior.README.md §9-8`）；按 minimal 原文实现，`be (am, is, are)`、`child (pl. children)`、`colour (AmE color)`、`Mr (AmE Mr.)` 等 23+61 行会整行进 `missing`，`be/child/colour/mr` 掉出小学/初中层（judge-data-safety §2.2-1）。
- **依据**：交付文件的变体行清单（本文 §3.8.2 表，由 `grep -E '[()/=]'` 得到：L2 25 行、L3 63、SH 16、H20 58、H25 60）。
- **被否决**：要求词表任务交付预拆分文件（minimal §3.8.3）；MANIFEST 驱动（stages-as-data §3.10，文件不存在）。

### D-stage-model-9　括号变体与词头同享旗标；复数/人称变化不授予；不在库的词头一律新建、绝不映射到原形
- **决定**：`(=全称)`、`(AmE 美式拼写)`、`(别名)`（`father (dad)`、`goodbye (bye)`、`until (till)`）、`(a.m.)` 等括号内的**替代词形**，若本身是种子 lemma，与词头同享旗标；`(pl. …)`、`(复 …)` 复数以及 `be (am, is, are)`/`have (has)` 这类人称变化**不**作为词头授予——例外：括号内的词形若本身已是种子 lemma（`is`、`are`、`am`、`has`）则同享（它们今天就是独立词条且带 zk 旗标，否则会掉成「课标外」）。官方词头不是任何 lemma 时**新建词头**（`excited`、`frightened`、`stuck`、`according`、`manners`…共 47 个，§3.8.4），不借 `word_forms` 映射到 `excite`/`frighten`。
- **理由**：课标把 `excited` 当独立词条，给 `excite` 打小学旗标会让一个初中/高中级动词排进小学页签；`word_forms` 的作用是查词时回指原形（`words.py:663-696`），不是阶段归属。新建词头后 `_rebuild_forms` 的「词头守卫」自动跳过 `excited` 这一形式行（`seed.py:239-241`），查词仍直达词头。变体同享旗标是对「一条词条覆盖两种写法」的忠实解读（SH 列 `bicycle/bike`，L2 列 `bike (=bicycle)`，两表指同一词项）。
- **依据**：`moe-2022.README.md §4.2-3`；模拟审计：L2 变体命中 19（am, is, are, bicycle, color, dad, favorite, bye, grandpa, grandma, mathematics, math, mum, mom, mr., mrs., ms., photograph, television）、别名 4（Mr/Mrs/Ms/PE → `mr./mrs./ms./p.e.`）；SH 13 个分词形容词词头（embarrassed, excited, frightened, frightening, frozen, lost, manners, satisfied, satisfying, stuck, surprised, underlined, united）。
- **被否决**：`word_forms` 回指（judge 们按「不是真缺」统计的 12 个词，是查词口径而非阶段口径）；括号变体一律丢弃（`color`/`television`/`is` 会掉层）。

### D-stage-model-10　老词：重标不剔除；无阶段词是「课标外词典词」；`legacy:*` 令牌保留旧证据
- **决定**：9,162 词全部保留（导入从不删除，`seed.py:72-82`）；按新定义不在任何表的词 `stages=[]`→`stage_min NULL`，只在「全部」页签可见、可搜索、可标记，不进筛词/推荐/预生成（`screen.py:51-56`、`batches.py:232-234`、`prewarm.py:36-38`）；`sources` 加 `legacy:zk`/`legacy:gk`（依据旧记录的 `stages`）。
- **理由**：A3 已判这两张旧表不是依据，把它们包装成「拓展阶段」呈现给 2026 年的学生是误导（judge-learner-product §3.2-2：254 个 ext-only 词是 `crayon/granny/bathtub` 这类日常词，不是「旧考纲」）；而信息不能丢——`legacy:*` 就是将来拓展层的候选集（模拟：zk 离开 406、gk 离开 1,035，其中无阶段 227 = 63 + 203 - 重叠）。
- **依据**：`[INDEX A1][A6]`、`[stage-model-19]`；模拟：227 个无阶段词中有内容/配图 0 个、被两位用户持有 0 个（三位评审各自独立复算同量级：237/245/257）。
- **被否决**：`zk_ext/gk_ext` 阶段（A3）；从种子剔除（导入不删，且剔除会让旧旗标带着新索引活下来——minimal §3.8.1）。

### D-stage-model-11　`sources` 令牌表（统一三份设计的命名）
- **决定**：见 §3.3 表。采用 learner-first 的命名族（`cs2022:l2`、`cs2022:l3`、`sh2020`、`cs2025:hs0|hs1|hs2`、`legacy:zk|gk`），补 `cs2022:app`、`sh2020:app`、`cs2020:hs0|hs1|hs2`、`cs2020:app`、`cs2025:app`；现有 `cet4 cet6 cet46 ecdict` 不变；删除 `zk`、`gk`。
- **理由**：三位评审都要求「定一套并写进 ATTRIBUTION 与 DESIGN §3.2」（judge-maintainer §4-6）；星级令牌让将来「高一/高二」不必重解析（judge-learner-product §5）；`legacy:*` 保留拓展层候选（judge-data-safety §7-7）。
- **依据**：`seed.py:210`（排序空格连接）、`0001_init.sql:188`；线上今天 6 个令牌 38 种组合。
- **被否决**：minimal 的 `l2_2022/sh_zk_2020/hs_2025`（无星级、无 legacy）；stages-as-data 的 `word_stage_tags.sources`（无 tag 表）。

### D-stage-model-12　种子生成路径：`scripts/relabel_seed.py` 就地重标（主路径）；`build_seed.py` 只做词典字段
- **决定**：新增 `scripts/relabel_seed.py`（§3.8）：输入 `data/seed/vocab.jsonl.gz` + `data/lists/*` + 已校验 `stardict.db`（或 `ecdict.csv`）+ `data/lists/headword-overrides.jsonl`，输出新 `vocab.jsonl` / `stats.json` / `ATTRIBUTION.md`；「种子只增不减」由构造保证并由脚本断言（输出 lemma 集 ⊇ 输入）。`build_seed.py` 删除两张 mahavivo 中考/高中输入与 ECDICT `zk/gk` 标签授予，只产出 CET 旗标 + 词典字段，之后**必须**跑 `relabel_seed.py`；`make seed` 串联两步，`make relabel` 只跑第二步。
- **理由**：三位评审都把 learner-first 的就地重标列为最务实路线；Mac 上 `fetch_ecdict.sh` 不能直接跑（`df --output`/`sed -i`，`[seed-pipeline-8/26]`）。虽然本机实际有已校验的 `stardict.db`，但把阶段逻辑集中在一个脚本里避免两处实现（`build_seed.py` 与 `relabel_seed.py` 各算一遍阶段）；`python3 -I` 下脚本目录不在 `sys.path`（`-I` 隐含 `-P`），兄弟模块导入不可行，所以是「两步管线」而不是「共享模块」。
- **依据**：judge-data-safety §7-2、judge-learner-product §5、judge-maintainer §5；`Makefile:93-98`、`scripts/pack_seed.sh`。
- **被否决**：minimal 的 `--base` 携带（在就地重标下由构造满足，只保留其 `carried_forward` 统计与「线上 `source='seed'` 的 lemma 全部在种子里」检查）；MANIFEST。

### D-stage-model-13　导入器与诊断加固（stages-as-data 的防御性工程，用常量实现）
- **决定**：① `seed.seed_row` 对未知阶段码 `raise SeedFormatError`（`ValueError` 子类），`import_seed` 在写任何行之前失败，`cmd_import_seed` 打印并 exit 1；② `main.seed_check` 捕获 `(ValueError, OSError)`（含 `gzip.BadGzipFile`），记日志 + `system_events('seed_import_failed')`，**继续启动**；③ `bank.user_settings_row` 在过滤掉全部阶段码时 `log.warning(event="stage_fallback", user_id=…)` 再回落默认；④ `diag.check_db` 加三条不变量（§3.9）；⑤ `bank.DEFAULT_*` 与 DDL 默认绑定测试；⑥ 迁移后 `ANALYZE`（上线步骤）。
- **理由**：`[INDEX A6]` 未注册阶段码静默丢弃、`WORD_LIBRARY_CURATION.md §1.2` 坏种子让服务进入重启循环、`[INDEX A7]` 双源默认漂移——三位评审都要求嫁接（judge-data-safety §7-4/6、judge-maintainer §5、judge-learner-product §5）。
- **依据**：`seed.py:184-185`、`main.py:307-319`、`bank.py:181`、`diag.py:52-77`。
- **被否决**：外键到 `stage_defs`（无表）；`/api/stages` 单条 `GROUP BY`（与模型无关，5 次循环查询 ≈ 7 ms，本轮不改）。

### D-stage-model-14　`ecdict.py`：`STAGE_TAGS` 四值保留，只有 `cet4/cet6` 授予阶段，`has_stage_tag` 语义解耦
- **决定**：`STAGE_TAGS = ("zk","gk","cet4","cet6")` 不动（它是 ECDICT 标签名）；新增 `GRANTED_TAGS = ("cet4","cet6")`；`stages` 属性 = `[s for s in STAGE_ORDER if s in GRANTED_TAGS and s in self.tags]`；`has_stage_tag` 改为 `any(t in self.tags for t in STAGE_TAGS)`（保持今天「带任一考试标签」的含义，供 `words.py:669,673` 的回指启发式使用）；`word_columns()` 加 `"stage_xs": 0`，`stage_min = min(stage_to_index(s) for s in stages) if stages else None`。
- **理由**：minimal 把 `STAGE_TAGS` 缩成 `("cet4","cet6")` 会连带改变 `has_stage_tag = bool(self.stages)`（`ecdict.py:122-123`），而 `words.py:669,673` 用它决定屈折形式是否回指原形——三位评审都指出这是未声明的行为变更；`ecdict.py:177` 的位置推导在任何缩表下都会把 cet4 算成 1（= 小学），**必须**改成 `stage_to_index`。
- **依据**：judge-data-safety §2.2-2、judge-maintainer §4-2、judge-learner-product §1-4；`ecdict.py:28,117-123,158-181`。
- **被否决**：缩表（副作用）；继续让 ECDICT `zk/gk` 授予阶段（与 A2/A3 矛盾：官方清单词头已全部进种子，一个只在 ECDICT 带 zk 标签的词按定义在清单之外）。

### D-stage-model-15　常量去副本：`seed/words/prewarm/content` 从 `schemas` 导入
- **决定**：`seed.STAGES = schemas.STAGE_ORDER`；`words.STAGES = schemas.STAGE_ORDER`（保留名字，`bank.py:181`、`screen.py:46`、`batches.py:233` 不改调用点）；`prewarm.STAGE_COLUMNS = {s: f"stage_{s}" for s in STAGE_ORDER}`、`prewarm.STAGES = (*STAGE_ORDER, "all")`；`content.STAGE_ZH = schemas.STAGE_NAMES_ZH`。`scripts/eval_provider.py:107`、`scripts/smoke.py:352,614` 改为五阶段字面量（脚本不依赖后端包路径）。
- **理由**：这是布尔列方案能拿到的唯一硬编码收益（10 份 → 5 份），judge-maintainer §2.2/§5 要求把 learner-first 的「或」改成「必须」；`schemas.py` 只依赖 `clock`，无循环导入。
- **依据**：`[INDEX A3]`（10 份常量清单）。
- **被否决**：保留副本（minimal §7.2-4 自己承认的债）。

### D-stage-model-16　`screen.py:44`、`batches.py:272,698` 的 `int(x or DEFAULT)` 改为 `is None` 判断
- **决定**：三处改为 `cur = s.get("current_stage"); cur = bank.DEFAULT_CURRENT_STAGE if cur is None else int(cur)`，并加测试「`current_stage=1` 的用户 `auto` 距离：xs 0、zk 1、gk 3」。
- **理由**：重编号后无 0 值，但三行防御让以后任何人都踩不到这个坑（judge-maintainer §5、learner-first §3.7）。
- **依据**：`[INDEX A3]` 办法 ① 的陷阱描述。
- **被否决**：不改（minimal「不必改」）。

### D-stage-model-17　不做「上海/全国」维度、不做拓展层；`/api/stages` 固定 5 行
- **决定**：初中 = 上海表 ∪ 三级 的并集进同一个 `stage_zk`；没有 `user_settings.scheme`、没有第二个 `stage_min`、没有 `/api/stages?scheme=`、前端继续常量驱动页签；`StageInfo` 形状不变，`/api/stages` 从 4 行变 5 行。
- **理由**：A4 已定不按省份分层；上海高中表没有机读源（`[INDEX B7]`），维度只能做半个；并集方案下上海初二多看 ≈300 个三级功能词、外省初二多看 ≈400 个上海词（其中 259 个在国家高中表）——「宁多勿漏」（minimal §3.3、learner-first §3.4）；成本是 6 处 SQL 模板 + 契约 + 数据驱动页签（`[stage-model-16/17/18]`）。
- **依据**：`[INDEX A8][B5]`；模拟：zk 2,142 中仅经上海表进入的 ≈ 400 级（`zk ∖ gk` 117 个里 108 个只来自上海表）。
- **被否决**：Q3-a 方案维度；Q4-c 拓展层。

### D-stage-model-18　前端改动集：枚举、角色、页签、CSS、最低阶段隐藏开关、「仅初中新增」文案、「课标外」芯片、`StageChips only`、`ScreenPage` 断言
- **决定**：§3.6 逐文件。其中 learner-first 的学习者侧三项全部纳入本切片：① `StageChips` 新增 `only?: readonly Stage[]`，列表与学习卡只渲染「用户目标阶段 ∪ 词的最低阶段」，详情页显示全部；② `stages` 为空时渲染一个 `课标外` 芯片（`zh.stages.outside`）；③ `VocabPage` 最低阶段隐藏「仅本阶段新增」开关，初中页签文案 `仅初中新增（不含小学）`。`WordRow`/`StudyCard`/`WordHeader` 以 prop `onlyStages` 传递（页面层从 `useAuth().settings?.stages` 取），叶子组件不新增 hook 依赖。
- **理由**：一个二级词常带 xs/zk/gk/cet4 四个芯片（模拟：505 个小学词里绝大多数同时属 ≥3 个阶段），375 px 学习卡上是噪音；`only` 是三份里唯一直接服务儿童界面的改动（judge-learner-product §3.3/§5）；judge-maintainer 的顾虑是 `WordHeader` 依赖 `useAuth()` 牵连测试 mock——用 prop 传递消掉这个顾虑；「课标外」让老用户看懂 227 个词为什么不在任何页签。
- **依据**：`StageChips.tsx:25-42`、`WordHeader.tsx:13,32-33,50`、`components/list/WordRow.tsx:97`、`StudyCard.tsx:172/207/298`、`WordDetailPage.tsx:360`、`WelcomePage.tsx:323`、`VocabPage.tsx:202,232`；`[frontend-stages-15/16/19]`。
- **被否决**：把 `only` 推到 P2（judge-maintainer）——它是加阶段的直接后果，与枚举改动同一提交最省；6 个页签去掉 `fill` 接受横滑（媒体查询更省）。

### D-stage-model-19　AI 侧：本切片只改 `STAGE_ZH`；`AUDIENCE`/`content_system.txt:1` 的受众文案归 Q9 切片同一发布窗口；在此之前不对 `xs` 预生成
- **决定**：`content.STAGE_ZH` 随 D-15 自动含 `xs: 小学`（否则 `content.py:88` 对带新旗标的词 `KeyError` 整组失败）；不动 `content.py:48 AUDIENCE`、`content_system.txt:1`、`PROMPT_VERSION`。发布规则：0011 与 Q9 的提示词改动（受众 + `EXAMPLE_EN_MIN` 15→10 等）在同一发布窗口上线；若 Q9 晚于本切片，上线后**不**运行 `prewarm {"stage":"xs"}`，且管理页预生成下拉的 `小学` 项在发布说明里标「待提示词更新」。
- **理由**：`content_system.txt` 被 `test_schemas.py:122-126` 与 `docs/CLAUDE_INTEGRATION.md §5.1` 逐字节钉住，两条线各改一次同一文件是无谓的合并冲突；受众文案的实质（小学例句规则）属 Q7/Q9（`[INDEX D6]`：`EXAMPLE_EN_MIN = 15` 会丢掉典型小学句）。
- **依据**：`[verify ai-prompts-stages 遗漏 1]`、`[INDEX Q9]`；judge-maintainer §5「与 Q7/Q9 提示词改动同窗口发布」。
- **被否决**：本切片顺手改第一句（minimal「建议」）。

### D-stage-model-20　文档/契约镜像与 `SCHEMA.sql` 的处理
- **决定**：`docs/SCHEMA.sql` **不改**（`test_db.py:362-366` 字节一致）；0011 文件本身是 `words`/`user_settings` 的现行 DDL，`DESIGN.md §3.1` 加一行「当前 schema = 0001 + 0008 + 0009 + 0010 + 0011；两表现行 DDL 见 0011 文件头」；**不**新建 `docs/SCHEMA_CURRENT.sql`。其余镜像点见 §4.4。
- **理由**：再加一份 DDL 镜像就是再加一个漂移点，且需要新测试与导出脚本；`sqlite_master` 随时可查。
- **依据**：judge-maintainer §4-4（提出）；`test_db.py:362-366`。
- **被否决**：`SCHEMA_CURRENT.sql` + 测试（0.3 人日换一个新漂移点）。

### D-stage-model-21　上线：前后端同一次停机；`full_seed` 验收是硬门；回滚只有快照，发布说明写明「静默错位」
- **决定**：§7 的 12 步 runbook。新增硬门：对排练库 `WD_FULL_SEED_DB=<拷贝> .venv/bin/pytest -m full_seed backend/tests/unit/test_seed.py` 必须绿（`conftest.py:38-46` 默认 skip，`make test` 不设该变量）；迁移后 `ANALYZE` + 可选 `VACUUM`；发布说明写明：回退代码而不回库 ≠ 500，而是 sqin 的主攻阶段静默显示为「六级」、kimi 显示为「高中」（`index_to_stage(4)='cet6'`、`(2)='gk'`），真正 500 的是词库/筛词列表（`stage_min=5` 不满足旧 `StageIndex`）。
- **理由**：judge-data-safety §5-1/2/4（三份共同盲点）。
- **依据**：`conftest.py:34-46`、`backend/pyproject.toml:37-38`、`schemas.py:65`、`security.py:597`、`[verify stage-model 遗漏 2]`。
- **被否决**：把 `full_seed` 并进 `make test`（需要 9,162 词的库，CI 不存在）。

### D-stage-model-22　验收不变量：断言 `xs ⊆ zk`，**不**断言 `zk ⊆ gk`，断言 `stage_min` 与旗标一致
- **决定**：§5.3 验收 SQL；`relabel_seed.py` 退出前自检同一组不变量。
- **理由**：`zk ⊆ gk` 在 A2 定义下不成立：模拟 `zk ∖ gk` = 117（108 个只来自上海表：aged, amusement, arrival, chopstick, clearly, dial, ferry…；三位评审独立复算 111–140）；learner-first 把它写进验收/测试/TASKS 是致命缺陷（judge-data-safety §3.2-1）。`xs ⊆ zk` 由 L2 ⊆ L3（`moe-2022.README.md §4.3` 用 `comm -23` 校验）与 §3.8.3 的集合定义保证。
- **依据**：`[INDEX B5]`（仅上海 415 词中 148–156 个两边都没有）。
- **被否决**：强制 `gk ∪= zk` 闭包（违反 A2，且会把 331 个上海词组之类塞进高中层——judge word-lists/data-safety §112）。

### D-stage-model-23　新词头的词典字段来源：已校验的 `stardict.db` 优先，`ecdict.csv` 兜底，`headword-overrides.jsonl` 优先于两者
- **决定**：`relabel_seed.py --ecdict-db` 指向 sha256 已对上 `deploy/fetch_ecdict.sh:13` 的 `stardict.db`（本机 `scratchpad/ecdict-dl/extract/stardict.db`；上线前再 `shasum` 一次），取 `id`（→ `ecdict_id`）、`pos`、全部词典字段；没有 `stardict.db` 时 `--ecdict-csv`（`ecdict_id`/`pos` 为空，`[seed-pipeline-27]`）。`data/lists/headword-overrides.jsonl` 覆盖 ECDICT 释义不对的词头：`bund`（ECDICT「(政治上的)同盟」，上海表意为「外滩」）、`BCE`（ECDICT「化学工程学士」）、`CE`（「组件选通」）、`AI`（「[计] 附加信息」）——4 条人工记录（默认文本在 §3.8.4）。任何新词头若既不在 ECDICT 也不在 overrides → 脚本 exit 1 列出清单，不生成空释义记录。
- **理由**：空释义词条会以空卡片进入词库页与筛词池（judge word-lists/data-safety §118 判为致命）；47 个新词头在 `ecdict.csv` 中 47/47 命中（本文核对），但 4 个义项错误。
- **依据**：`ecdict.csv` 表头 `word,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange,detail,audio`（无 `id`）；`build_seed.py:94-100,180-198` 的 `make_record` 字段映射可直接复用。
- **被否决**：最小记录 `{"word","translation"}` 留空（learner-first §3.5-6 的兜底）。

### D-stage-model-24　工作量按 7 人日排期（不是 4.5）
- **决定**：§8.3 分项合计 7.0 人日，含 0.5 缓冲；不含词表任务与 Q7/Q9。
- **理由**：三位评审都把 minimal 的 4.5 上调到 6–7（判断相同：前端 0.5 低估、种子归一化要按真实格式重写）；本文又加入了 `relabel_seed.py` 的不变量与报告、`StageChips only`、三处 `is None`、诊断不变量。
- **依据**：judge-maintainer §2.4。

---

## 2 对照假设 A1–A6 的偏离与理由

| 假设 | 本设计 | 偏离 | 理由 / 依据 |
|---|---|---|---|
| A1 小学 = 课标二级 505 | 采用，并**加入** 2022 附表的数词/月份/星期（模拟 +63 词），括号变体同享 | 细化（附表） | D-7、D-9；不加附表则 `monday/one/january` 落到 gk 或 NULL |
| A2 初中 = 上海 2020 ∪ 三级；高中 = 2025 修订 3100（含 2020 版 3000）；200 词暂缺 | 采用；细化：① 上海表只取单词部分，342 个词组本轮不入库；② 高中 = 2025 ∪ 2020 主表 ∪ 两份国家附表（仅已在库词头）；③ 两份附表（2022、上海）归 zk；④ ECDICT `zk/gk` 标签不再授予阶段 | 细化 ①–④ | ① 现库 13 个 `kind='phrase'`，342 词组的释义来源与 `kind` 规则是词表线的决定（§9）；② 并集按原文「含 2020 版」；③④ D-7、D-14 |
| A3 只用官方词头；mahavivo 中考/高中两表退出；有道系等只作核验 | 采用；`build_seed.py` 删除两张表输入；CET 四文件保留；旧成员关系只以 `legacy:*` 令牌保留 | 无 | 顺带消灭 `RICH_RE` 丢 `best/less/cafe` 的缺陷（`[INDEX A6]`，那条正则只服务于被删掉的中考表） |
| A4 不按省份分层；双方案/拓展层由设计决定 | **都不做**；信息留在 `sources` | 本设计的核心取舍 | D-17、D-10；封死路径见 §8.1 |
| A5 配图先改提示词 | 不在本线；本线只保证 `STAGE_ZH["xs"]` 不崩，并给配图线一个稳定信号（`stage_min = 1` / `stages ∋ 'xs'`） | 无 | D-19；§9 |
| A6 新用户默认 K-12；2 个用户迁移规则写死 | DDL `'["xs","zk"]'`/1；两行 `current_stage + 1`、`stages_json` 原样、不加 `xs`，写死在 0011 的 `INSERT … SELECT` | 主攻默认取 `xs`（INDEX Q6-a 列的是 `["xs","zk"]`/xs，与此一致） | D-4；排练输出 `(1, 4)`、`(2, 2)` |

---

## 3 详细设计

### 3.1 阶段枚举 4 → 5 与整数索引（Q1）

`backend/wd/schemas.py`（现 `:25-26,51-52,56-67`）改为：

```python
Stage = Literal["xs", "zk", "gk", "cet4", "cet6"]
StageIndex = Literal[1, 2, 3, 4, 5]
…
STAGE_ORDER: tuple[str, ...] = ("xs", "zk", "gk", "cet4", "cet6")
STAGE_INDEX: dict[str, int] = {"xs": 1, "zk": 2, "gk": 3, "cet4": 4, "cet6": 5}  # == position + 1 (test_api_schemas pins it)
STAGE_NAMES_ZH: dict[str, str] = {"xs": "小学", "zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}

def stage_to_index(stage: str) -> int:
    """``xs→1, zk→2, gk→3, cet4→4, cet6→5`` (``user_settings.current_stage`` / ``words.stage_min``)."""
    try:
        return STAGE_INDEX[stage]
    except KeyError:
        raise ValueError(f"unknown stage {stage!r}") from None

def index_to_stage(index: int) -> str:
    if not 1 <= int(index) <= len(STAGE_ORDER):
        raise ValueError(f"stage index out of range: {index!r}")
    return STAGE_ORDER[int(index) - 1]
```

请求字面量：`schemas.py:488` `VocabQuery.stage: Literal["all","xs","zk","gk","cet4","cet6"]`、`:708` `ScreenNextQuery.stage: Literal["xs","zk","gk","cet4","cet6","auto"]`、`:1335` `PrewarmRequest.stage: Literal["xs","zk","gk","cet4","cet6","all"]`；模块 docstring `:9-10` 「1–4 column」→「1–5」。`check_contract.py:232-245` 只比对 `export type` 字面量联合（`Stage`、`StageIndex`），顺序敏感（`:301-308`）：两边都写 `xs, zk, gk, cet4, cet6` / `1..5`。

码名 `xs`：与 `zk/gk` 同构（拼音首字母），能直接进 `f"w.stage_{s} = 1"` 模板（`vocab.py:53`、`screen.py:52`、`batches.py:233`、`prewarm.py:39`、`words.py:229`）。`xx` 已是测试里的非法阶段探针（`test_screen.py:136`）。

### 3.2 与 `difficulty` 1–5 尺子的关系（Q5）

`routers/vocab.py:78`：

```python
"difficulty": "COALESCE(w.difficulty + 1, w.stage_min, 6), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma",
```

`NULL + 1 = NULL`，COALESCE 继续回落到 `stage_min`，无阶段词与 `difficulty=5`（beyond）同键 6（写进 `API.md:169`）。副作用：有 AI 内容的小学词（Claude 给 1 → 键 2）排在没有内容的小学词（键 1）之后，只影响词库页 `sort=difficulty`。`test_vocab.py:150-161` 的断言 `absorption(d=1→2) < abandon(stage_min 3) < absolutely(stage_min 4)` 仍成立，`keys` lambda 改为 `(i["difficulty"] + 1 if i["difficulty"] else i["stage_min"] or 6, …)`。

### 3.3 成员存储、维度与 `sources` 令牌（Q3/Q4）

每词 5 个 0/1 列 + `stage_min`（最低阶段索引，NULL = 不在任何表）。`words.sources`（`0001_init.sql:188`；`seed.py:210` 排序后空格连接；今天无任何读取者）改为下表的令牌集合：

| 令牌 | 含义（来源文件） | 授予 |
|---|---|---|
| `cs2022:l2` | 义务教育课标 2022 二级词汇表词头（`moe-2022-level2.txt`） | `xs`（因此也 `zk`） |
| `cs2022:l3` | 三级词汇表词头（`moe-2022-level3.txt`，含二级） | `zk` |
| `cs2022:app` | 2022 附表（`moe-2022-appendix.tsv`）：数词/月份/星期 → `xs`+`zk`；地理名称(-派生)/缩写/节日/地名景点/其他专有名词 → `zk`；不规则动词不授予 | 见左 |
| `sh2020` | 上海市教育考试院 2020 初中词汇表单词部分（`shmeea-2020-junior.txt`） | `zk` |
| `sh2020:app` | 上海表附表全部节（`shmeea-2020-junior-appendix.tsv`） | `zk` |
| `cs2020:hs0` / `hs1` / `hs2` | 高中课标 2017 年版 2020 年修订（`moe-2020-senior.tsv`，`level` 0/1/2 = 无星/必修/选择性必修） | `gk` |
| `cs2025:hs0` / `hs1` / `hs2` | 2025 修订版（`moe-2025rev-senior.tsv`） | `gk` |
| `cs2020:app` / `cs2025:app` | 两份国家名称附表（仅已在库词头） | `gk` |
| `cet4` / `cet6` / `cet46` / `ecdict` | 不变（`build_seed.py:112-142`；`ecdict` 继续表示「ECDICT 带任一考试标签」） | `cet4`/`cet6` |
| `legacy:zk` / `legacy:gk` | 75df534 种子里该词曾带 `stage_zk`/`stage_gk`（旧中考表 ∪ ECDICT zk / 旧高考 3500 ∪ ECDICT gk） | 不授予 |
| （删除）`zk`、`gk` | | |

回填蓝图（将来做维度或拓展层）：`INSERT INTO word_stage_tags SELECT id, 'sh', 'zk' FROM words WHERE instr(' '||sources||' ', ' sh2020 ')`，每个令牌一条 SQL。`/api/stages`（`vocab.py:83-106`、`stats.py:173-196`）仍是固定顺序全量清单，5 行，`StageInfo` 形状不变。

### 3.4 迁移 `0011_primary_stage.sql`（已排练，全文）

运行器约束（`db.py:195-249`、`0001_init.sql:25-37`）：文件在运行器的 `BEGIN IMMEDIATE` 内执行；不得 `COMMIT`/`ROLLBACK`、不写 `schema_migrations`、不切 `PRAGMA foreign_keys`；`VACUUM` 不能放这里。文件名符合 `db.py:41` 的正则。`docs/SCHEMA.sql` 不改。全文（= `scratchpad/synthesis-stage-model/0011_primary_stage.sql`，排练结果见 §5.4）：

```sql
-- 0011_primary_stage.sql — add the 小学 stage (code `xs`), renumber the stage index 1..5 and move the new-user default to K-12.
--
-- Why a rebuild: SQLite cannot ALTER a CHECK list or a column DEFAULT, so `words` (stage_min BETWEEN 1 AND 4) and
-- `user_settings` (current_stage BETWEEN 1 AND 4, DEFAULT 3, stages_json DEFAULT '["cet4","cet6"]') are re-created with
-- SQLite's 12-step recipe (CREATE new → INSERT … SELECT → DROP old → RENAME → indexes → views). The runner wraps this file
-- in BEGIN IMMEDIATE with foreign_keys=OFF and runs foreign_key_check before recording schema_migrations(11, 'primary_stage')
-- itself (SCHEMA.sql §1); nothing here toggles PRAGMAs or commits. Stop-first migration (DEPLOY §10: never under --no-restart).
--
-- Index renumbering (DESIGN §0.3 / API.md §9.1): old 1=zk 2=gk 3=cet4 4=cet6 → new 1=xs 2=zk 3=gk 4=cet4 5=cet6, so every stored
-- stage_min / current_stage moves +1 (NULL stays NULL). stages_json holds stage CODES and is copied as is; nobody is enrolled
-- in xs automatically (live rows: user 1 → current_stage 4 = cet4, user 2 → 2 = zk). The seed re-import that follows
-- (kv.seed_version is cleared below so the next `wd import-seed` / `wd serve` start imports unconditionally) recomputes
-- stage_xs/stage_zk/stage_gk/stage_min for every seed word from the official lists; the +1 here only keeps the database
-- self-consistent in between and for non-seed rows. push_batches.settings_json snapshots written before this migration keep
-- the OLD integer in "current_stage" (write-only column, batches.py; the "stages" codes next to it are unambiguous).
--
-- The view v_bank references words: it must be dropped before the DROP TABLE/RENAME and re-created afterwards (with
-- legacy_alter_table=OFF the RENAME otherwise fails with "error in view v_bank: no such table: main.words"). docs/SCHEMA.sql
-- stays the 0001 baseline byte for byte (test_db.py); the current DDL of words/user_settings is THIS file (DESIGN §3.1).

-- ---------------------------------------------------------------------------
-- 1. words: + stage_xs, stage_min 1..5 (renumbered)
-- ---------------------------------------------------------------------------
DROP VIEW v_bank;

CREATE TABLE words_new (
  id                  INTEGER PRIMARY KEY,
  lemma               TEXT NOT NULL,                    -- normalised key: NFKC, lower-case, single spaces, ASCII ' - .
  display             TEXT NOT NULL,                    -- display form, keeps casing ('China', 'NASA', 'a.m.', 'ice cream')
  kind                TEXT NOT NULL DEFAULT 'word' CHECK (kind IN ('word','phrase','abbreviation','proper_noun')),
  phonetic            TEXT,                             -- 'ə'bændən' (seed: ә→ə, :→ː normalised)
  translation         TEXT,                             -- zh lines joined by '\n' (seed translation[])
  definition          TEXT,                             -- en lines joined by '\n' (seed definition[])
  pos                 TEXT,                             -- ECDICT pos distribution 'n:4/v:96'
  collins             INTEGER,                          -- 0–5
  oxford              INTEGER,                          -- 0/1 (Oxford 3000)
  exam_tags           TEXT,                             -- 'ky toefl ielts gre' (space-joined seed exam_tags[])
  bnc                 INTEGER,                          -- BNC rank; 0/NULL = unknown
  frq                 INTEGER,                          -- COCA-ish rank; 0/NULL = unknown (sorted last)
  exchange_json       TEXT,                             -- seed exchange{} as JSON object ({"p":"went","d":"gone",…})
  stage_xs            INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs   IN (0,1)),  -- 小学 (义务教育课标 2022 二级词汇表 + 附表数词/月份/星期)
  stage_zk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_zk   IN (0,1)),  -- 初中 (课标 2022 三级 1600 ∪ 上海市教育考试院 2020 初中词汇表; ⊇ xs)
  stage_gk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_gk   IN (0,1)),  -- 高中 (普通高中课标 2017 年版 2025 年修订 3100 ∪ 2020 年修订 3000)
  stage_cet4          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet4 IN (0,1)),  -- 四级
  stage_cet6          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet6 IN (0,1)),  -- 六级 (cumulative: includes most CET-4)
  stage_min           INTEGER CHECK (stage_min BETWEEN 1 AND 5),  -- lowest stage 1=xs 2=zk 3=gk 4=cet4 5=cet6; NULL = outside the 5 lists.
                                                                  -- 仅本阶段新增 filter == stage_min = <stage index>
  cet6_star           INTEGER NOT NULL DEFAULT 0 CHECK (cet6_star IN (0,1)),   -- starred CET-6 word
  sources             TEXT,                             -- provenance tokens (data/seed/ATTRIBUTION.md), e.g. 'cet4 cet46 cs2022:l2 cs2022:l3 ecdict sh2020'
  ecdict_id           INTEGER,                          -- stardict.id
  source              TEXT NOT NULL CHECK (source IN ('seed','ecdict','claude','user')),  -- where dictionary fields came from
  is_public           INTEGER NOT NULL DEFAULT 1 CHECK (is_public IN (0,1)),   -- 0 = unvalidated/unsafe user word (visibility rule: API.md §1, DESIGN §5.2)
  is_valid_english    INTEGER CHECK (is_valid_english IN (0,1)),  -- NULL = not yet checked; set by lookup_word / seed import
  safe_for_sharing    INTEGER CHECK (safe_for_sharing IN (0,1)),  -- NULL = not yet checked; Claude verdict (no personal names etc.)
  difficulty          INTEGER CHECK (difficulty BETWEEN 1 AND 5), -- Claude scale, unchanged: 1 初中 … 4 六级, 5 beyond (= stage index − 1; vocab sort uses difficulty + 1)
  merged_into_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,  -- consolidation merged this row into another
  created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  active_content_id   INTEGER,                          -- logical FK → word_contents.id (no constraint: avoids a cycle)
  active_image_id     INTEGER,                          -- logical FK → word_images.id (NULL ⇒ template card is served)
  content_state       TEXT NOT NULL DEFAULT 'none' CHECK (content_state IN ('none','queued','ready','failed')),
  image_state         TEXT NOT NULL DEFAULT 'none' CHECK (image_state  IN ('none','queued','ready','failed')),
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT INTO words_new (id, lemma, display, kind, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq, exchange_json,
                       stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min, cet6_star, sources, ecdict_id, source,
                       is_public, is_valid_english, safe_for_sharing, difficulty, merged_into_word_id, created_by_user_id,
                       active_content_id, active_image_id, content_state, image_state, created_at, updated_at)
SELECT id, lemma, display, kind, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq, exchange_json,
       0, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min + 1, cet6_star, sources, ecdict_id, source,
       is_public, is_valid_english, safe_for_sharing, difficulty, merged_into_word_id, created_by_user_id,
       active_content_id, active_image_id, content_state, image_state, created_at, updated_at
FROM words;

DROP TABLE words;
ALTER TABLE words_new RENAME TO words;

CREATE UNIQUE INDEX ux_words_lemma      ON words(lemma);
CREATE INDEX        ix_words_frq        ON words(frq);
CREATE INDEX        ix_words_stage_min  ON words(stage_min, frq);
CREATE INDEX        ix_words_content    ON words(content_state);
CREATE INDEX        ix_words_created_by ON words(created_by_user_id) WHERE created_by_user_id IS NOT NULL;
CREATE INDEX        ix_words_public     ON words(is_public, is_valid_english);

CREATE VIEW v_bank AS
SELECT uw.*, w.lemma, w.display, w.kind, w.phonetic, w.translation, w.stage_min, w.content_state, w.image_state,
       w.is_public, w.is_valid_english
FROM user_words uw JOIN words w ON w.id = uw.word_id
WHERE uw.state IN ('new','learning');

-- ---------------------------------------------------------------------------
-- 2. user_settings: current_stage 1..5 (renumbered), K-12 defaults for new rows
-- ---------------------------------------------------------------------------
CREATE TABLE user_settings_new (
  user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  timezone           TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
  push_time          TEXT    NOT NULL DEFAULT '08:00' CHECK (push_time GLOB '[01][0-9]:[0-5][0-9]' OR push_time GLOB '2[0-3]:[0-5][0-9]'),
  push_enabled       INTEGER NOT NULL DEFAULT 1  CHECK (push_enabled IN (0,1)),
  daily_new_count    INTEGER NOT NULL DEFAULT 10 CHECK (daily_new_count BETWEEN 0 AND 50),
  daily_screen_count INTEGER NOT NULL DEFAULT 15 CHECK (daily_screen_count BETWEEN 0 AND 50),
  max_reviews        INTEGER NOT NULL DEFAULT 60 CHECK (max_reviews BETWEEN 0 AND 300),
  stages_json        TEXT    NOT NULL DEFAULT '["xs","zk"]',  -- 目标阶段: non-empty subset of xs/zk/gk/cet4/cet6 (set by onboarding); K-12 default, mirrored by services/bank.DEFAULT_STAGES (tested)
  current_stage      INTEGER NOT NULL DEFAULT 1  CHECK (current_stage BETWEEN 1 AND 5),  -- 主攻阶段 1=xs 2=zk 3=gk 4=cet4 5=cet6; Stage string on the wire (API.md §9.1); mirrored by bank.DEFAULT_CURRENT_STAGE
  show_images        INTEGER NOT NULL DEFAULT 1  CHECK (show_images IN (0,1)),
  zh_examples        TEXT    NOT NULL DEFAULT 'tap' CHECK (zh_examples IN ('tap','always')),
  auto_pronounce     INTEGER NOT NULL DEFAULT 1  CHECK (auto_pronounce IN (0,1)),
  accent             TEXT    NOT NULL DEFAULT 'en-US' CHECK (accent IN ('en-US','en-GB')),
  email_enabled      INTEGER NOT NULL DEFAULT 0  CHECK (email_enabled IN (0,1)),
  webhook_enabled    INTEGER NOT NULL DEFAULT 0  CHECK (webhook_enabled IN (0,1)),
  webhook_url        TEXT,
  webhook_format     TEXT    NOT NULL DEFAULT 'generic' CHECK (webhook_format IN ('generic','wecom','feishu','serverchan','bark')),
  next_push_at       TEXT,
  updated_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT INTO user_settings_new (user_id, timezone, push_time, push_enabled, daily_new_count, daily_screen_count, max_reviews, stages_json,
                               current_stage, show_images, zh_examples, auto_pronounce, accent, email_enabled, webhook_enabled,
                               webhook_url, webhook_format, next_push_at, updated_at)
SELECT user_id, timezone, push_time, push_enabled, daily_new_count, daily_screen_count, max_reviews, stages_json,
       current_stage + 1, show_images, zh_examples, auto_pronounce, accent, email_enabled, webhook_enabled,
       webhook_url, webhook_format, next_push_at, updated_at
FROM user_settings;

DROP TABLE user_settings;
ALTER TABLE user_settings_new RENAME TO user_settings;
CREATE INDEX ix_user_settings_next_push ON user_settings(next_push_at);

-- ---------------------------------------------------------------------------
-- 3. Force the seed re-import on the next start and leave an operator-visible trace
-- ---------------------------------------------------------------------------
DELETE FROM kv WHERE key = 'seed_version';
INSERT INTO system_events(kind, detail_json, created_at)
VALUES ('migration', '{"version": 11, "name": "primary_stage", "stages": "xs/zk/gk/cet4/cet6", "index": "1..5", "note": "stage_min and current_stage renumbered +1; stage flags re-derived from the seed at the next import"}',
        strftime('%Y-%m-%dT%H:%M:%SZ','now'));
```

要点与依据：`DROP VIEW v_bank` 先于重建（`[stage-model-13]`，核验升级为实测；本机 `/usr/bin/sqlite3` 的 `legacy_alter_table=1` 会掩盖这个错误，排练一律走 `run_migrations`）；显式列清单（`stage_xs` 插在 `stage_zk` 前，`SELECT *` 会错位）；`NULL + 1 = NULL`；`merged_into_word_id INTEGER REFERENCES words(id)` 在 RENAME 后按名解析，排练 `foreign_key_check` 空且随后 `INSERT user_words(word_id=999999)` 被拒；`user_settings` 没有任何子表（`[verify stage-model-12]`）；索引 6 + 1 与 0001 一致（`0001_init.sql:205-210,161`）；0008/0009/0010 没有 `ALTER` 过这两张表，所以整段 DDL 复制 0001 不会丢列（三位评审各自核过）。

### 3.5 后端改动（逐文件、逐函数）

| 文件 | 位置（75df534） | 改什么 |
|---|---|---|
| `backend/wd/schemas.py` | `:9-10` docstring；`:25-26` 字面量；`:51-52` + 新 `STAGE_INDEX`；`:56-67` 两个映射（§3.1）；`:488`、`:708`、`:1335` 请求字面量加 `"xs"` | 契约三件套同一提交 |
| `backend/wd/seed.py` | `:1-20` docstring（「four stage flags」→ five；加「种子从不删词；未知阶段码报错」）；`:43` `from .schemas import STAGE_INDEX, STAGE_ORDER as STAGES`；`:47-68` `SEED_COLUMNS` 在 `"stage_zk"` 前插 `"stage_xs"`（UPSERT 的 SET/WHERE 由 `:72-82` 自动生成）；`:184-185` 改为 `raw = rec.get("stages") or []; if not isinstance(raw, (list, tuple)): raise SeedFormatError(...)`；`unknown = [s for s in raw if s not in STAGES]; if unknown: raise SeedFormatError(f"unknown stage code(s) {unknown!r} in seed record {word!r}; run the matching `wd migrate` first")`；`stages = [s for s in STAGES if s in raw]`；`:204-208` 加 `"stage_xs": int("xs" in stages)`，`stage_min = min(STAGE_INDEX[s] for s in stages) if stages else None`；新增 `class SeedFormatError(ValueError)`；`cmd_import_seed`（`:333-353`）捕获 `SeedFormatError` → `print(…, file=sys.stderr); return 1` | 解析在事务之前（`:266-278`），所以报错时库未被触碰 |
| `backend/wd/main.py` | `:307-319 seed_check`：`try: import_seed(...) except (ValueError, OSError) as e: log.error("seed import failed: %s", e, extra={"event": "seed_import_failed"}); conn.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES ('seed_import_failed', ?, ?)", (json.dumps({"file": path.name, "error": str(e)[:500]}), now_iso())); return` | 坏种子不再让 `wd serve` 进入重启循环（`WORD_LIBRARY_CURATION.md §1.2`） |
| `backend/wd/services/words.py` | `:39` `STAGES = schemas.STAGE_ORDER`（`stages_of` `:228-229` 自动）；`:563-586 _word_defaults` 加 `"stage_xs": 0`；`:589-597 _INSERT_WORD_SQL` 列清单与占位符加 `stage_xs` | |
| `backend/wd/services/ecdict.py` | `:28` 保留 `STAGE_TAGS`，新增 `GRANTED_TAGS = ("cet4", "cet6")`；`:117-119` `stages` → `[s for s in schemas.STAGE_ORDER if s in GRANTED_TAGS and s in self.tags]`；`:121-123` `has_stage_tag` → `any(t in self.tags for t in STAGE_TAGS)`；`:158-181 word_columns` 加 `"stage_xs": 0`，`stage_zk/gk` 恒 0，`stage_min = min(schemas.stage_to_index(s) for s in stages) if stages else None` | D-14 |
| `backend/wd/routers/vocab.py` | `:78` COALESCE（§3.2）；`:52-56`、`:83-106` 循环自动 5 阶段 | |
| `backend/wd/services/stats.py` | `:173-196` 自动 | |
| `backend/wd/services/bank.py` | `:85` `DEFAULT_STAGES = ("xs", "zk")`；`:86` `DEFAULT_CURRENT_STAGE = 1  # = stage_to_index("xs"); mirrors the user_settings DDL default (test_bank_defaults)`；`:181` → `known = [s for s in stages if s in words.STAGES]; if stages and not known: log.warning("stage_fallback: %r → %r", stages, DEFAULT_STAGES, extra={"event": "stage_fallback", "user_id": int(user_id)}); base["stages"] = known or list(DEFAULT_STAGES)` | |
| `backend/wd/security.py` | `:612-614` docstring 示例改 `'["xs","zk"]'`；`:597` 自动；`:661-664` 不改 | |
| `backend/wd/services/screen.py` | `:44` → `cur = s.get("current_stage"); cur = bank.DEFAULT_CURRENT_STAGE if cur is None else int(cur)` | D-16 |
| `backend/wd/services/batches.py` | `:272`、`:698` 同上（抽成 `bank.current_stage_index(settings_row) -> int` 一个函数，三处调用） | D-16 |
| `backend/wd/ai/prewarm.py` | `:32-33` → `STAGE_COLUMNS = {s: f"stage_{s}" for s in STAGE_ORDER}`；`STAGES = (*STAGE_ORDER, "all")`；`:36-39` 不改（`all` 仍是 `stage_min IS NOT NULL`） | |
| `backend/wd/ai/content.py` | `:49` → `STAGE_ZH = schemas.STAGE_NAMES_ZH`；`:48 AUDIENCE` 不改（D-19） | |
| `backend/wd/diag.py` | `:52-77 check_db` 加三条不变量（§3.9） | |
| `scripts/eval_provider.py` | `:107` `STAGES = ("xs","zk","gk","cet4","cet6")`（`:341-348` 分组自动多一组） | |
| `scripts/smoke.py` | `:352` 期望 `["xs","zk","gk","cet4","cet6"]`；`:614` `len(stats["stages"]) == 5` | |
| `scripts/check_contract.py` | 不改 | |
| `scripts/build_seed.py`、`scripts/relabel_seed.py` | §3.8 | |

### 3.6 API 契约与前端

契约三件套（`types.ts:1-2` 规则）：
- `frontend/src/api/types.ts:5` `export type Stage = 'xs' | 'zk' | 'gk' | 'cet4' | 'cet6';           // index 1..5 in that order`；`:6` `export type StageIndex = 1 | 2 | 3 | 4 | 5;`；`:37` 注释「1–5 index」；`:45` 注释「小学 / 初中 / 高中 / 四级 / 六级」；`:52`、`:73` 不变。
- `docs/API.md`：`:155`（端点 12「1–5 column index」）、`:160`（端点 15 `⊆ {xs,zk,gk,cet4,cet6}`）、`:167`（端点 19「5 rows」）、`:169`（端点 20 `stage=all|xs|zk|gk|cet4|cet6`，`new_only` 例子改「for zk this is the 初中 increment, 1,558 words on the shipped seed」，`sort=difficulty` 表达式改 `COALESCE(difficulty + 1, stage_min, 6)` 并注「6 = beyond CET-6 or outside every list」）、`:187`（端点 31）、`:230`（端点 67）、`:239-240`（§9 两行）、`:271`（Settings 注释「1–5」）、`:279`（StageInfo 注释加小学）、`:286` 不变、`:459-460`（§9.1：`xs→1, zk→2, gk→3, cet4→4, cet6→5`）。
- `scripts/check_contract.py:301-308` 两边同序。

前端源文件：

| 文件 | 改什么 |
|---|---|
| `components/word/StageChips.tsx` | `:7-9` `STAGE_ORDER = ['xs','zk','gk','cet4','cet6']`、`STAGE_INDEX = { xs: 1, zk: 2, gk: 3, cet4: 4, cet6: 5 }`、`STAGE_BY_INDEX` 对应；`:15-23` props 加 `only?: readonly Stage[]`；`:25-27` 渲染逻辑：`if (stages.length === 0) return <ul className={cx('chips', …)}><li className="chip chip--stage chip--outside">{zh.stages.outside}</li></ul>;` `const ordered = STAGE_ORDER.filter((s) => stages.includes(s) && (!only || only.includes(s) || (stageMin !== null && STAGE_INDEX[s] === stageMin)));` 其余不变（`:31` 高亮、`:33-37` 星标） |
| `components/word/WordHeader.tsx` | `:13` props 加 `onlyStages?: readonly Stage[]`；`:32-33` `hasMeta` 把 `(showStages && word.stages.length > 0)` 改为 `showStages`（课标外芯片也算 meta）；`:50` `<StageChips … only={onlyStages} />` |
| `components/study/StudyCard.tsx` | props 加 `onlyStages?: readonly Stage[]`，`:172/:207/:298` 三处 `<WordHeader … onlyStages={onlyStages} />`；`StudyPage`/`ScreenRunPage`（凡渲染 `StudyCard` 的页面）传 `onlyStages={settings?.stages}` |
| `components/list/WordRow.tsx` | props 加 `onlyStages?`；`:97` `<StageChips … only={onlyStages} />`；`VocabPage`/`BankPage` 等列表页传 `settings?.stages` |
| `pages/WordDetailPage.tsx:360`、`pages/WelcomePage.tsx:323` | 不传 `onlyStages`（详情页与引导期显示全部） |
| `i18n/zh.ts` | `:25` `roles: { xs: '小学生', zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }`；`:28-29` `stages: { xs: '小学', zk: '初中', gk: '高中', cet4: '四级', cet6: '六级', xsFull: '小学（课标二级词汇）', zkFull: '初中（中考）', gkFull: '高中（高考）', cet4Full: '大学英语四级', cet6Full: '大学英语六级', newOnly: '仅本阶段新增', newOnlyZk: '仅初中新增（不含小学）', newOnlyCet6: '仅六级新增（不含四级）', outside: '课标外', star: '六级星标词' }`；`:86` `lists: '词表范围：义务教育课标二级与三级词汇、上海市初中英语词汇表、高中课标词汇表、大学英语四级与六级大纲'`。**同一提交**把 `docs/FRONTEND.md:231,234,292` 的镜像块改成逐行相同（`zh.test.ts:67-83` 逐行比对、`zh.contract.test.ts:61-83` 键与值比对） |
| `pages/WelcomePage.tsx` | `:30` `Role = 'xs' \| 'zk' \| 'gk' \| 'uni' \| 'pro'`；`:33-38` 预设（D-5）；`:40` `ROLES` 加 `'xs'`；`:42` `STAGE_FULL` 加 `xs: zh.stages.xsFull`；`:72-73` 兜底 → `const DEFAULT_PRESET = { stages: ['xs', 'zk'] as Stage[], current: 'xs' as Stage }; // mirrors user_settings DDL / bank.DEFAULT_*` |
| `pages/VocabPage.tsx` | `:29` `TABS = ['all','xs','zk','gk','cet4','cet6']`；`:202` `const newOnlyLabel = tab === 'cet6' ? zh.stages.newOnlyCet6 : tab === 'zk' ? zh.stages.newOnlyZk : zh.stages.newOnly;`；`:232` `{tab !== 'all' && tab !== STAGE_ORDER[0] && <Switch …/>}`（最低阶段的开关是恒等过滤，隐藏；顺手修掉今天初中页签的空操作 `[frontend-stages-19]`） |
| `pages/ScreenPage.tsx` | `:20` `FULL_NAME` 加 `xs`；`:31` 保留按 `STAGE_ORDER` 重排，另加测试 `items.length === STAGE_ORDER.length`（前后端不同步时红） |
| `pages/AdminPage.tsx:36` | `PREWARM_STAGES: readonly PrewarmStage[] = [...STAGE_ORDER, 'all']` |
| `pages/SettingsPage.tsx:72-77,303-317`、`pages/ScreenRunPage.tsx:34-35`、`routes.tsx`、`endpoints.ts:131,328` | 自动（遍历 `STAGE_ORDER` / 派生类型）；5 个 chip-btn 一行放下（`[verify frontend-stages-17]`） |
| `components/ui/ui.css` | 在 `:453-455 .tabs--fill .tab` 后加 `@media (max-width: 479.98px) { .tabs--fill .tab { padding-inline: var(--space-2); } }`（6 × 48 + 5 × 4 = 308 ≤ 343 @375 px、≤ 328 @360 px；`[frontend-stages-16]`，上线前 DevTools 375/360 复核） |
| `components/word/word.css` | `.chip--outside { border-style: dashed; }`（与 `.chip` 同色系，仅虚线边） |
| 测试夹具 | `grep -rn 'stage_min: [0-9]' frontend/src --include='*.test.*'` 的 12 处（10 个文件：`study/queue.test.ts`、`StudyCard.test.tsx`、`AddWordPreviewRow.test.tsx`、`list/WordRow.test.tsx`、`SpeakButton.test.tsx`、`WordDetailPage.test.tsx`、`ScreenRunPage.test.tsx`、`WelcomePage.test.tsx`、`StudyPage.test.tsx`、`BankPage.test.tsx`）全部 +1 |

部署顺序：Mac 上 `wd serve` 同一进程提供 SPA 快照与 API（`WD_FRONTEND_DIST`），同一提交的前端快照与后端在同一次停机内切换，不存在混合状态；若有人分开发布，旧后端对 `stage=xs` 返回 400、`bank.py:181` 把 `["xs"]` 静默过滤成默认（`[verify frontend-stages-13]`）——`DEPLOY.md §10` 写明「阶段枚举变更不可 `--no-restart`、不可分开发布」。

### 3.7 新用户默认（Q6）

DDL（§3.4 第 2 段）、`bank.py:85-86`、`WelcomePage.tsx:72-73` 三处同值；注册流程不改（`security.py:661-664`）。新增 `backend/tests/unit/test_bank_defaults.py::test_defaults_mirror_user_settings_ddl`：

```python
def test_defaults_mirror_user_settings_ddl(conn):            # conn = migrated test DB
    cols = {r["name"]: r["dflt_value"] for r in conn.execute("PRAGMA table_info(user_settings)")}
    assert json.loads(cols["stages_json"].strip("'")) == list(bank.DEFAULT_STAGES)
    assert int(cols["current_stage"]) == bank.DEFAULT_CURRENT_STAGE == stage_to_index("xs")
```

现有两个用户：只 `+1`，不加 `xs`。「给只选初中的用户自动补小学」明确拒绝：它改变用户已选目标，设置页点一下即可。

### 3.8 老词处理与种子流水线（`scripts/relabel_seed.py`）

#### 3.8.1 原则

1. 阶段旗标的唯一真相是种子文件；0011 清掉 `kv.seed_version`，启动或 `wd import-seed` 必导。
2. 种子只增不减：`relabel_seed.py` 的输出 lemma 集 ⊇ 输入（断言，exit 1），所以「不在新种子里的词带着旧旗标活下来」（minimal §3.8.1）这一陷阱由构造排除；另加验收「线上 `source='seed'` 的 lemma 全部在种子里」（§5.3）。
3. 阶段是共享词库的属性，学习进度是用户的属性；重标不触碰 `word_contents`/`word_images`/`difficulty`/任何每用户表（`seed.py:10-12`）。
4. 不生成空释义词条；不把官方词头映射到原形。

#### 3.8.2 归一化规则（按交付文件逐条，写进 `relabel_seed.py` 并有单元测试）

输入原貌（`grep -v '^#' | grep -E '[()/=]'`）：L2 25 行、L3 63 行、SH 16 行（另 `café`、`P.E.`、`A.M. (a.m.)`、`hot-dog`、`ice-cream`）、H20 58 行、H25 60 行；TSV 两列 `word<TAB>level`，无非注释表头。规则（`parse_official_headword(raw) -> ParsedHead(heads, variants, level)`）：

| # | 规则 | 例 | 结果 |
|---|---|---|---|
| R1 | `#` 行与空行跳过；TSV 取第 1 列，`level` 取第 2 列（`0/1/2`） | `abandon\t2` | head `abandon`, level 2 |
| R2 | 字符规范化：NFKD 去重音（`café`→`cafe`）、`’`→`'`、折叠空白、小写比较 | `café`、`o’clock` | `cafe`、`o'clock` |
| R3 | 斜杠并列拆为多个词头 | `a/an`、`actor/actress`、`although/though`、`policeman/policewoman (pl. …)` | `a`,`an` / `actor`,`actress` … |
| R4 | 等号并列（上海表）拆为多个词头 | `exam=examination`、`grandma=grandmother` | 两个词头 |
| R5 | 括号注先从词头剥离；括号内容按 `,` `，` `;` 切分，去掉标记词 `AmE`/`美`/`英`/`=`，残余按「标记留下的 ≥2 空格」再切；得到 **variants** | `maths (=mathematics, AmE math)` → `mathematics`,`math`；`mother (mum AmE mom)` → `mum`,`mom`；`PE (=physical education)` → `physical education`（整体短语，不再按空格拆） | variants |
| R6 | 以 `pl.`/`复` 开头的括号内容整体丢弃（复数） | `child (pl. children)`、`medium (pl. media)` | 只剩词头 |
| R7 | variants 只在**本身已是种子 lemma** 时授予旗标，否则忽略；绝不为 variant 新建词头 | `be (am, is, are)` → `am`,`is`,`are` 都是 lemma → 同享；`bund (the Bund)` → `the bund` 不是 lemma → 忽略 | |
| R8 | 显式例外表 `OVERRIDES`（原文整行 → 词头列表），只收通用规则会算错的行：`according (to)` → `according`, `according to`；`toward(s)` → `toward`, `towards`；`manner(s)` → `manner`, `manners`；`bund (the Bund)` → `bund`；`BCE (Before the Common Era)` → `BCE`；`CE (Common Era)` → `CE` | | |
| R9 | 词头解析为 lemma 的顺序：精确 lemma → 别名表 `ALIASES`（`Mr→mr.`, `Mrs→mrs.`, `Ms→ms.`, `PE→p.e.`, `P.E.→p.e.`, `A.M.→a.m.`, `P.M.→p.m.`, `yogurt→yoghurt`）→ 2–4 字母全大写缩写试 `x.y.`/`xy.` 形（`UK`→`u.k.` 若存在）→ 连字符规则（`ice-cream`→`ice cream`、`hot-dog`→`hotdog`；反向：官方 `goodbye` 匹配库内 `good-bye`）→ **否则记为新词头**。**不**把空格折叠成一个词（`break down ≠ breakdown`，judge word-lists/data-safety §93 的实证陷阱） | | |
| R10 | 大小写同形条目合并到同一 lemma（`miss`/`Miss`、`China`/`china`、`May`/`may`、`March`/`march`），`level` 取最小 | | |
| R11 | 附表：`moe-2022-appendix.tsv` 第 1 列类别决定授予（D-7），第 2 列按 R2–R9 解析（`The United Kingdom (UK)` → head `The United Kingdom`、variant `UK`），`地理名称-派生` 的附加列不解析；`shmeea-2020-junior-appendix.tsv` 第 1 列全部 → zk；两份国家附表第 2–4 列按 `/`、`—` 拆、去前导 `the`，只授予已在库词头 | `U.S.A.`、`the Pacific Ocean` 在库 → zk | |
| R12 | `shmeea-2020-junior-forms.tsv`、`-phrases.txt` 本轮不读（词组是词表线决定，§9） | | |

模拟审计（`membership.json.audit`）：精确 lemma 命中 L2 501 / L3 1,596 / SH 1,706 / H20 2,989 / H25 3,082；variants 命中 19 / 42 / 7 / 48 / 57；别名 4 / 5 / 3 / 4 / 4；连字符 1（`hot-dog→hotdog`）；新词头 1 / 9 / 24 / 12 / 26（并集 47）。

#### 3.8.3 集合与旗标

```
xs = L2 ∪ A22[数词-基数词|数词-序数词|月份|星期]
zk = xs ∪ L3 ∪ SH ∪ A22[地理名称|地理名称-派生|缩写|节日|地名景点|其他专有名词] ∪ ASH
gk = H25 ∪ H20 ∪ AH25 ∪ AH20                    # 附表只对已在库词头
stages(record) = [s for s in STAGE_ORDER if record.lemma in set_s]   # cet4/cet6 来自旧记录，不动
sources(record) = (old_sources − {zk, gk}) ∪ {legacy:zk if old stage_zk} ∪ {legacy:gk if old stage_gk} ∪ 命中的官方令牌（含星级 hs0/1/2 与 :app）
```

#### 3.8.4 新词头（47 个，模拟清单；最终以脚本输出为准）

`according, AI, angrily, BCE, beautifully, bund, calligraphy, carefully, CE, Confucius, confused, dancer, dining, dishonest, drone, due to, embarrassed, empathy, endangered, entirely, excited, frightened, frightening, frozen, kung fu, lifestyle, lost, luckily, manners, mobile phone, pagoda, per cent, politely, quietly, satisfied, satisfying, seafood, stuck, surprised, teenage, tofu, UK, underlined, unforgettable, united, wetland, Wi-Fi`（按 `stage_min`：xs 1、zk 30、gk 16）。词典字段：`--ecdict-db`（已校验 `stardict.db`，复用 `build_seed.make_record` 的字段映射 `build_seed.py:180-198`，含 `ecdict_id`）优先，`--ecdict-csv` 兜底；`display` 保留官方大小写（`AI`、`UK`、`BCE`、`Confucius`、`Wi-Fi` → `derive_kind` 自动得 abbreviation/proper_noun，`words.py:143-151`）。`data/lists/headword-overrides.jsonl` 覆盖 4 条（默认内容，词表线可改释义文字）：

```jsonl
{"word": "bund", "phonetic": "bʌnd", "translation": ["n. （上海）外滩 the Bund；堤岸"], "definition": ["n. the Bund, the waterfront in Shanghai; an embankment"], "pos": "n:100", "stages_note": "sh2020"}
{"word": "BCE", "phonetic": "", "translation": ["abbr. 公元前（Before the Common Era）"], "definition": ["abbr. Before the Common Era"], "pos": ""}
{"word": "CE", "phonetic": "", "translation": ["abbr. 公元（Common Era）"], "definition": ["abbr. Common Era"], "pos": ""}
{"word": "AI", "phonetic": "", "translation": ["abbr. 人工智能（artificial intelligence）"], "definition": ["abbr. artificial intelligence"], "pos": ""}
```

（`stages_note` 仅供人读，导入器忽略未知键——`seed_row` 只取已知字段。）

#### 3.8.5 `scripts/relabel_seed.py` 规格

```
python3 -I scripts/relabel_seed.py --base data/seed/vocab.jsonl.gz --lists data/lists --out data/seed \
    (--ecdict-db <stardict.db> | --ecdict-csv <ecdict.csv>) [--overrides data/lists/headword-overrides.jsonl] \
    [--dry-run] [--report <path outside the repo>]
```

- 函数：`parse_official_headword(raw: str) -> ParsedHead`；`load_lists(dir) -> Lists`（五个主表 + 三类附表，按 §3.3 令牌登记）；`Resolver(lemmas: set[str]).resolve(head) -> tuple[str | None, str]`（返回 lemma 与解析方式，§3.8.2 R9）；`assign(records, lists, resolver) -> Assignment`（每 lemma 的 `stages`、`sources`，新词头清单及其令牌）；`fetch_dictionary(words, *, db=None, csv=None, overrides) -> dict[str, Record]`；`check_invariants(records, base_lemmas)`（只增不减；`xs ⊆ zk`；有阶段 ⇒ 有官方/CET 令牌；无未知码；新词头 `translation` 非空；`per_stage` 复算一致）→ 任一失败 exit 1；`write_outputs(records, out)`。
- 排序键与 `build_seed.py:150-151` 一致：`(min STAGE_INDEX or 6, lemma)`。
- `stats.json` 新键：`per_stage/only_stage/first_stage` 含 `xs`；`no_stage`；`carried_forward`（= 输入记录数）；`new_headwords: [...]`；`list_matches: {cs2022:l2: {rows, lemmas, variants, aliases, new}, …}`；`unresolved: []`（必须为空）；`invariants: {xs_subset_zk: true, …}`；`legacy: {zk: n, gk: n}`。`pack_seed.sh:44-47` 只读 `total_words`，不受影响。
- `--report` 写一份与本文 `membership.json` 同形的审计 JSON（放 scratchpad，不入库）；`--dry-run` 只打印 §5.3 口径的预期计数与新词头清单。
- `ATTRIBUTION`（`data/seed/ATTRIBUTION.md`）由脚本生成：ECDICT（MIT）+ 五份官方文件词头（教育部课标 2022 附录 3、2017 年版 2020 年修订与 2025 修订高中课标附录 2、上海市教育考试院 2020 词汇表——只用词头成员关系，不收录释义/音标/排序；来源 URL/md5/获取日期从各文件 `#` 头注释抄录）+ mahavivo CET 四文件。
- `scripts/build_seed.py` 改动：`:4-11` docstring；`:81-88 syllabus` 删 `zk`/`gk` 两项；`:105-106` 的 ECDICT 查询只取 `cet4`/`cet6` 标签行；`:112` `stage_from_list = {"cet4": "cet4", "cet6": "cet6"}`；`:147` 过滤元组与 `:150` `order` 用五阶段；`:191` `make_record` 的 `stages` 只取 cet 标签；`:201-219` `ATTRIBUTION` 常量删除（由 `relabel_seed.py` 生成）；`Makefile:93-98` `make seed` 串联 `build_seed.py → relabel_seed.py → gzip -9 -n`，新增 `make relabel ECDICT_DB=… LISTS_DIR=data/lists`。`RICH_RE`（`:16`）保留给 CET rich 文件但修复全角括号/`=`/单字母（`[INDEX 6.2-1]`）。
- 在 Mac 上打包：`gzip -9 -n` 得到的归档与 Linux GNU gzip 字节不同（`[seed-pipeline-7]`），无害（`kv.seed_version` 本来随内容变）；`pack_seed.sh --check` 的 `zcat` 在 BSD 上失败，用 `gzip -dc … | wc -l` 核对记录数。

#### 3.8.6 老词去向（模拟；三位评审独立复算同量级）

| 项目 | 现状 | 新定义（模拟） |
|---|---|---|
| 各阶段词数 | zk 2,099 · gk 3,829 · cet4 4,722 · cet6 7,671 | xs 584 · zk 2,142 · gk 3,276 · cet4 4,722 · cet6 7,671（含 47 个新词头） |
| `stage_min` 分布 | 1:2,099 · 2:1,792 · 3:1,577 · 4:3,694 | 1:584 · 2:1,558 · 3:1,271 · 4:1,722 · 5:3,847 · NULL:227（合计 9,209） |
| 初中层进出 | — | 离开 406（63 落到无阶段）、加入 418 + 30 新词头 |
| 高中层进出 | — | 离开 1,035（203 落到无阶段）、加入 455 + 16 新词头 |
| 无阶段「课标外」 | 0 | 227（word 200 / proper_noun 15 / abbreviation 6 / phrase 6；例 `addicted, airmail, armchair, bathtub, bookshop, bungalow, cd-rom, crayon, dustbin, granny, motorbike`）；有内容或配图 **0**；被 sqin/kimi 持有 **0** |
| 两位用户 | sqin 67 个生词全在旧 zk/gk/cet；kimi 10 个 | sqin：xs 1 · zk 15 · gk 39 · cet4 12 · 无阶段 0；kimi：10 个全部 xs（a, and, be, have, I, in, it, of, the, to），仍在她的初中池里 |
| 重导写入 | — | ≈4,359 行 `updated` + 47 行 `inserted`（`sources` 令牌全量换名 → 这些行的 `updated_at` 前移 → `/media/card/{id}.svg` 的 LRU 键失效，重渲染，无害） |
| 不变量 | — | `xs ∖ zk = ∅`；`zk ∖ gk` = 117（不作断言）；H25 无星词不在 zk 的只有 `bean curd`、`practise`（拼写变体，各自仍是 gk） |

产品含义：降级到更高阶段的词仍可被相应阶段的用户筛到；227 个课标外词在「全部」页签可见、详情页显示「课标外」芯片；已在生词库的词照常复习。

### 3.9 诊断不变量（`diag.check_db`）

在 `diag.py:66` 的 `lines +=` 之后追加（只对 `version >= 11` 执行）：

```python
INVARIANTS = (
    ("stage_min_consistent", "SELECT COUNT(*) FROM words WHERE stage_min IS NOT (CASE WHEN stage_xs=1 THEN 1 WHEN stage_zk=1 THEN 2 "
                             "WHEN stage_gk=1 THEN 3 WHEN stage_cet4=1 THEN 4 WHEN stage_cet6=1 THEN 5 END)"),
    ("xs_subset_zk",         "SELECT COUNT(*) FROM words WHERE stage_xs = 1 AND stage_zk = 0"),
    ("stages_json_known",    "SELECT COUNT(*) FROM user_settings us, json_each(us.stages_json) j WHERE j.value NOT IN ('xs','zk','gk','cet4','cet6')"),
)
for name, sql in INVARIANTS:
    n = int(conn.execute(sql).fetchone()[0]); lines.append(f"invariant {name}: {'ok' if n == 0 else f'{n} violation(s)'}"); ok = ok and n == 0
```

（`json_each` 是 JSON1 读函数，SQLite ≥ 3.38 内置；`wd check` 是诊断命令而非迁移，旧版本上这一条失败只会报 `query failed`，不影响服务。）

---

## 4 改动清单（文件 → 改什么）

### 4.1 数据库与种子

| 文件 | 改什么 |
|---|---|
| `backend/wd/migrations/0011_primary_stage.sql`（新建） | §3.4 全文 |
| `docs/SCHEMA.sql` | **不改** |
| `scripts/relabel_seed.py`（新建） | §3.8.5 |
| `scripts/build_seed.py` | §3.8.5 末段 |
| `scripts/pack_seed.sh`、`Makefile:93-98` | `make seed` 串联两步；`make relabel`；macOS `zcat` 注记 |
| `data/lists/headword-overrides.jsonl`（词表线交付，默认内容 §3.8.4） | 4 条人工记录 |
| `data/seed/vocab.jsonl.gz`、`stats.json`、`ATTRIBUTION.md` | 由 `relabel_seed.py` 重建 |
| 根 `ATTRIBUTION.md:19-32` | §2 改为五份官方文件词头 + CET 四文件；删 mahavivo 中考/高中两行 |
| `backend/tests/fixtures/mini_seed.jsonl`（60 条） | 给 `a, apple, be, book, cat, child, dog, glass, go, good, happy, house, is, teacher, water, TV, a.m.` 等二级词 `stages` 首位加 `"xs"`，`sources` 改新令牌（`cs2022:l2 cs2022:l3 …`、`legacy:*`）；加一条 `stages: []` 的课标外记录（如 `bungalow`）；连锁：`test_seed.py:97` `a → stage_min 1` 仍成立；`test_screen.py:133` `zk` 顺序 `["be","a","go"]` 不变（xs ⊂ zk）；`test_vocab.py:78` cet6 `new_only_total == 3` 不变；`test_batches.py:127` `screens == ["absolutely","axis"]`（主攻 cet4 现为索引 4，夹具 `current_stage` +1） |

### 4.2 后端

§3.5 表中全部位置：`schemas.py:9-10,25-26,51-52,56-67,488,708,1335`；`seed.py:1-20,43,47-68,184-185,204-208,333-353`（+ `SeedFormatError`）；`main.py:307-319`；`services/words.py:39,563-586,589-597`；`services/ecdict.py:28,117-123,158-181`；`routers/vocab.py:78`；`services/bank.py:85-86,181`（+ `current_stage_index`）；`security.py:612-614`；`services/screen.py:44`；`services/batches.py:272,698`；`ai/prewarm.py:32-33`；`ai/content.py:49`；`diag.py:52-77`；`scripts/eval_provider.py:107`；`scripts/smoke.py:352,614`。

### 4.3 契约与前端

§3.6 表中全部位置：`api/types.ts:5-6,37,45`；`components/word/StageChips.tsx`；`components/word/WordHeader.tsx:13,32-33,50`；`components/study/StudyCard.tsx:172,207,298`（+ prop）；`components/list/WordRow.tsx:97`（+ prop）；调用页面传 `onlyStages`；`i18n/zh.ts:25,28-29,86`；`pages/WelcomePage.tsx:30-42,72-73`；`pages/VocabPage.tsx:29,202,232`；`pages/ScreenPage.tsx:20`（+ 测试）；`pages/AdminPage.tsx:36`；`components/ui/ui.css`（媒体查询）；`components/word/word.css`（`.chip--outside`）；12 处夹具。

### 4.4 文档

| 文件 | 行 | 改什么 |
|---|---|---|
| `docs/API.md` | `155, 160, 167, 169, 187, 230, 239-240, 271, 279, 459-460` | §3.6 |
| `docs/FRONTEND.md` | `50`（角色加 小学生）、`56`（页签 6 个）、`89`（StageChips：五阶段 + `only` + 课标外）、`147`（§5.5：最低阶段不显示开关；初中页签文案）、`231, 234, 292`（§8 镜像块逐行同步 `zh.ts`） |
| `docs/DESIGN.md` | `32`（引导多选五阶段）、`40`（"four stage tabs" → five）、`72`（§0.3 术语表 `小学 / 初中 / 高中 / 四级 / 六级`，`xs / gk … (stage index 1–5)`，**绑定**）、`186`（`stage_min` 1–5；加「当前 schema = 0001 + 0008 + 0009 + 0010 + 0011；两表现行 DDL 见 0011」）、`202`（`stages[]` 行：1 xs … 5 cet6）、`209`（验收数字按新 `stats.json`）、`321-322`（设置表默认 `["xs","zk"]`/`xs`，`current_stage` 1–5）、`330`（预设：小学生 → xs · 初中生 → xs+zk …）、§3.2 新增来源令牌表（§3.3）、§3.1 新增「目标模型（stage_defs）与触发条件」一段（D-1）、§6.3 注「0011 之前的 `push_batches.settings_json` 用旧索引」 |
| `docs/TASKS.md` | `166-182` | 验收脚本改为 §5.3，常量由新 `stats.json` 填入 |
| `docs/DEPLOY.md` | `283`（`wd migrate` 段加「0011 是 stop-first 重建」）、`294-296`（§10：阶段枚举变更不可 `--no-restart`、不可分开发布；迁移后 `ANALYZE`/`VACUUM`；回滚只有快照 + 静默错位说明） |
| `docs/QUICK_DEPLOY_AND_MOBILE.md` | Mac 段 | 加「先备份、再停、再切、再起」（`main.py:478-485` 启动即迁移） |
| `docs/CLAUDE_INTEGRATION.md` | `211, 232-235` | **本切片不改**（D-19，归 Q9） |
| `docs/WORD_LIBRARY_CURATION.md` | §1.2 | 一句话：种子从不删词；阶段由官方词头清单 + `relabel_seed.py` 决定；`sources` 令牌表见 DESIGN §3.2 |
| `README.md` | `3, 5, 9, 78, 103` | 五阶段与新计数 |
| `docs/qa-frontend.md` | `36, 42` | 角色 5 个、页签 6 个、`仅初中新增（不含小学）`、课标外芯片 |
| `data/seed/ATTRIBUTION.md` | 全文 | 由脚本生成 |

---

## 5 测试与验收

### 5.1 一定会红的已有测试（按 `make test` 顺序：pytest → `check_contract.py` → tsc → vitest → build）

| 测试 | 原因 | 处理 |
|---|---|---|
| `tests/unit/test_api_schemas.py:32-39` | 映射 `[1,2,3,4]`、`index_to_stage(5)` 应抛、`STAGE_NAMES_ZH` 等式 | 5 阶段；`index_to_stage(6)` 抛；字典加 `xs` |
| `tests/integration/test_vocab.py:65-79,107-114,150-161` | 4 行/索引/名称、`items[3]` 是 cet6、`stage_min == 4`、COALESCE | 5 行 `[1..5]`、`items[4]`、`== 5`、`keys` lambda `+1`/`6` |
| `test_onboarding.py:98,120,139` | 默认 `3 / '["cet4","cet6"]'`、cet4 存 3、zk 存 1 | `1 / '["xs","zk"]'`、4、2 |
| `test_settings.py:57-58,88-89,109-112` | 默认 DTO、gk 存 2、`:112` 前提「存的是 cet4/cet6」 | `["xs","zk"]`/`xs`、3、改前提 |
| `test_security.py:315`、`test_auth.py:82` | 新用户默认 | `["xs","zk"]` / `xs` |
| `test_screen.py:116,129-136` | 夹具 `current_stage=4`（旧 cet6）；注释 | `=5`；`["be","a","go"]` 不变 |
| `test_batches.py:127` | 夹具 `current_stage` 与注释「cet4 (stage_min 3)」 | +1 |
| `test_seed.py:90-100` | `abandon (0,1,1,1,2)` → 六元组 `(0,0,1,1,1,3)`、`absolutely` 3→4、`email` 1→2、`ought to` 4→5、`a` 1（若标 xs 仍 1）；`stage_min IS NULL` 为 0 的断言随课标外夹具改为 1 | 按新夹具 |
| `test_seed.py:338-353 @full_seed` | 全部常量 | 新 `stats.json`（§5.3） |
| `test_words_resolve.py:279,346,478` | ECDICT cet6 → `stage_min` 4→5；`WordBrief.stage_min` 2→3 | 改常量 |
| `test_reports.py:29,87` | 手工行 `stage_min: 2`（旧 gk） | 3 |
| `test_history.py:112` | 阶段集合 | 加 `xs` |
| `test_content_apply.py:255-257` | `go` 的中文阶段列表；手工行多 `stage_xs` 键 | `["小学","初中","高中","四级"]`（若夹具给 `go` 加 xs）；加键 |
| `tests/unit/test_runner.py:27`、`tests/test_fake_claude.py:26` | 提示词夹具只含中文标签 | 不变 |
| `test_db.py:13-17,51` | 25 张表不变 | 不红；新增升级测试（§5.2） |
| `scripts/check_contract.py` | `Stage`/`StageIndex` 两边不一致即硬失败 | 同一提交改两边 |
| `npm run typecheck` | `Record<Stage,…>` 缺键：`StageChips.tsx:8-9`、`WelcomePage.tsx:42`、`ScreenPage.tsx:20`、`zh.test.ts:56` | 加键 |
| `zh.test.ts:67-83`、`zh.contract.test.ts:61-83` | `zh.ts` 与 `FRONTEND.md §8` 不镜像 | 同一提交改文档 |
| `SpeakButton.test.tsx:91-102` 等含 chips 断言的测试 | 课标外芯片 / `only` | 按新行为更新 |
| `scripts/smoke.py:352,614` | 4 阶段钉死 | 5 |

### 5.2 新增/扩展的测试

- `test_db.py`：`test_upgrade_0011_renumbers_stages_and_rebuilds_two_tables`（仿 `:283-310`：0001 基线建库；插 `users`×2、`user_settings`（`current_stage` 1 与 3，`stages_json` `'["zk"]'`/`'["zk","gk","cet4","cet6"]'`）、`words`（`stage_min` 1..4 各一行 + NULL 一行 + `merged_into_word_id` 自引用）、`user_words`/`push_items`/`word_contents`/`word_images`/`content_reports`/`bank_suggestions` 各一行、`kv.seed_version`；`run_migrations()` → `(11,'primary_stage')` 已应用；`current_stage` 2/4，`stages_json` 原样；`stage_min` 2..5 且 NULL 保持；`stage_xs` 全 0；子表行数不变；`PRAGMA foreign_key_check` 空；`db.view_names(c) == ["v_bank"]` 且可查；新插 `user_settings` 行默认 `('["xs","zk"]', 1)`；`stage_min = 6`/`0`、`current_stage = 6`/`0` 抛 `IntegrityError`；`kv.seed_version` 不存在；`system_events` 末行 `kind='migration'`；二次运行 `applied == []`；`EXPECTED_TABLES` 不变）。
- `test_api_schemas.py`：`all(STAGE_INDEX[s] == STAGE_ORDER.index(s) + 1 for s in STAGE_ORDER)`；`VocabQuery(stage="xs")`、`ScreenNextQuery(stage="xs")`、`PrewarmRequest(stage="xs")` 合法，`"xx"` 非法。
- `test_bank_defaults.py`（新）：§3.7 的 DDL 绑定；`user_settings_row` 对 `'["cet9"]'` 回落默认并写 `stage_fallback` 日志（`caplog`）。
- `test_seed.py`：`stages: ["xs"]` → `stage_xs 1, stage_min 1`；`["xs","zk","gk","cet4"]` → 1；`["cet6"]` → 5；`stages: []` → 全 0、`stage_min IS NULL`；`sources` 原样写入新令牌；**未知码 `["xs","zk9"]` → `SeedFormatError`，库未写入，`kv.seed_version` 不变**；重导把旧 `stage_zk=1` 行按新记录清零（携带规则依赖的覆盖语义）。
- `test_main.py`/`test_startup`：`seed_check` 对坏文件（截断 gzip、未知码）写 `system_events('seed_import_failed')` 且 `startup` 不抛。
- `test_words_resolve.py`：ECDICT `tag="zk"` 不再产生旗标（`stage_min IS NULL`，`stages == []`）但 `has_stage_tag` 为真；`tag="cet4"` → `stage_cet4=1, stage_min=4`；`word_columns()["stage_xs"] == 0`。
- `test_screen.py`：主攻 `xs`（`current_stage=1`）的 `auto` 顺序：xs 0、zk 1、gk 3（钉住 `is None` 改动）。
- `test_vocab.py`：`/api/stages` 第一行 `xs`、`index == 1`；`stage=xs&new_only=1` 总数 == `stage_min=1` 数。
- `test_admin_ops.py`：`prewarm {"stage":"xs"}` 202。
- `test_diag.py`：`check_db` 对人工制造的 `stage_min` 不一致行报 `1 violation(s)` 且 `ok=False`。
- `scripts/test_relabel_seed.py`（新，pytest 收集 `scripts/`）：R1–R11 的表驱动用例（每条 §3.8.2 示例一个断言）；`Resolver` 的解析顺序；不变量检查对「少一个 lemma」「xs 不在 zk」「新词头无释义」各 exit 1。
- 前端 vitest：`StageChips.test.tsx`（新：5 个 chip 顺序；`stageMin` 用新索引高亮；`only=['xs']` 时四旗标小学词只渲染「小学」、最低阶段始终保留；`stages=[]` 渲染「课标外」）；`WelcomePage.test.tsx`（`ROLE_PRESETS` 每个 `current ∈ stages`、`ROLES.length === 5`、兜底 `DEFAULT_PRESET`）；`VocabPage.test.tsx`（`TABS.length === STAGE_ORDER.length + 1`、`tab === 'xs'` 不渲染开关、`tab === 'zk'` 文案）；`ScreenPage.test.tsx`（新：5 张卡；`items.length === STAGE_ORDER.length`）。

### 5.3 验收脚本（替换 `TASKS.md:166-182` 的数字部分；常量在 `relabel_seed.py` 定稿后由 `stats.json` 填入；下列数字为模拟）

```python
import sqlite3, os; c = sqlite3.connect(os.environ["WD_DB_PATH"]); q = lambda s: c.execute(s).fetchone()[0]
assert q("select count(*) from words where source='seed'") == <stats.total_words>          # 模拟 9,209；≥ 9,162 种子只增不减
assert q("select count(*) from words where stage_xs=1") == <per_stage.xs>                  # 模拟 584
assert (q("select count(*) from words where stage_zk=1"), q("…stage_gk=1"), q("…stage_cet4=1"), q("…stage_cet6=1")) == (<per_stage>)   # 模拟 2142, 3276, 4722, 7671
assert [q(f"select count(*) from words where stage_min={i}") for i in (1,2,3,4,5)] == [<first_stage>]   # 模拟 584, 1558, 1271, 1722, 3847
assert q("select count(*) from words where stage_min is null and source='seed'") == <no_stage>        # 模拟 227
assert q("select count(*) from words where stage_xs=1 and stage_zk=0") == 0                             # xs ⊆ zk
assert q("select count(*) from words where stage_min is not (case when stage_xs=1 then 1 when stage_zk=1 then 2 when stage_gk=1 then 3 when stage_cet4=1 then 4 when stage_cet6=1 then 5 end)") == 0
assert q("select count(*) from words where stage_min is not null and sources is null") == 0           # 有阶段必有来源令牌
assert q("select count(*) from words w, json_each('[\"' || replace(w.sources, ' ', '\",\"') || '\"]') j where w.sources is not null and j.value in ('zk','gk')") == 0  # 旧令牌 zk/gk 已换名为 legacy:*（按令牌比对，不用 LIKE）
assert q("select count(*) from words where content_state='ready' and stage_min is null") == 0         # 模拟 0
assert q("select count(*) from user_settings where current_stage not between 1 and 5") == 0
assert q("select count(*) from schema_migrations where version=11") == 1
assert q("select count(*) from word_forms wf join words w on w.lemma=wf.form and w.merged_into_word_id is null") == 0   # 词头守卫（含新词头 excited 等）
assert q("select count(*) from words where kind='phrase'") == <stats.phrases>  # 模拟 13 + 4（due to, kung fu, mobile phone, per cent）
```

HTTP 验收：`GET /api/stages` 5 行且 `index == [1,2,3,4,5]`、第一行 `xs`；`GET /api/vocab?stage=xs` 的 `total == per_stage.xs`；`GET /api/settings` 对 sqin/kimi 分别返回 `cet4`/`zk`；新注册用户欢迎页看到「小学生」并默认勾选 小学 + 初中、主攻 小学；详情页一个课标外词（如 `bungalow`）显示「课标外」芯片；学习卡只显示目标阶段芯片。**硬门**：`WD_FULL_SEED_DB=<排练库> .venv/bin/pytest -m full_seed backend/tests/unit/test_seed.py` 绿。

### 5.4 排练（已做）与上线前再做一次

已做（`scratchpad/synthesis-stage-model/rehearse.py`，`.venv/bin/python -I`，SQLite 3.54.1，`legacy_alter_table=0`）：`applied [(11,'primary_stage')] 0.050 s`；行数变化只有 `schema_migrations 4→5`、`kv 15→14`、`system_events 17→18`；`integrity_check ok`、`foreign_key_check []`；`stage_min` 1/2/3/4 → 2/3/4/5 逐行恰好 +1（不符 0 行）；旗标 `(0, 2099, 3829, 4722, 7671)`、`difficulty` 49 行且 `difficulty + 1 = stage_min` 44 / < 2 / > 3；用户 `(1, '["zk","gk","cet4","cet6"]', 4)`、`(2, '["zk"]', 2)`；`v_bank` 18 行；`words` DDL 含 `BETWEEN 1 AND 5` 与 `stage_xs`，`user_settings` 默认 `'["xs","zk"]'` / `1`；`stage_min = 6/0`、`stage_xs = 2`、`current_stage = 6/0` 被 CHECK 拒绝；`INSERT user_words(word_id=999999)` 被外键拒绝；新插设置行默认 `('["xs","zk"]', 1)`；二次运行 `[]`；`word_contents/word_images/user_words` 49/31/77 不变；文件 2,307 页 / 937 空闲页 = 9,449,472 B；空库 0001→0011 应用列表 `[1, 8, 9, 10, 11]`，25 张表 + `v_bank`。

上线前（代码与新种子改完后）：① `cp` 停服务后的线上库到私有目录；② `WD_DATA_DIR=<私有目录> .venv/bin/wd migrate`；③ `.venv/bin/wd import-seed --file data/seed/vocab.jsonl.gz`（期望 ≈47 inserted / ≈4,300–4,400 updated）；④ §5.3 全部断言 + `WD_FULL_SEED_DB=<拷贝> pytest -m full_seed`；⑤ `.venv/bin/wd check db --db <拷贝>` 三条不变量 ok；⑥ 在拷贝上数「两位用户学过的词里落到无阶段的」（`select uw.user_id, count(*) from user_words uw join words w on w.id=uw.word_id where w.stage_min is null group by 1` → 模拟 0/0）。排练**必须**用 `.venv/bin/python`/`wd`，不能用 `/usr/bin/sqlite3`（`legacy_alter_table=1` 会掩盖缺 `DROP VIEW` 的错误）。

---

## 6 上线与回滚（Mac，launchd；对应 `docs/DEPLOY.md §10` 的 Linux 流程）

前提：数据目录 `/Users/sqin/word-dance-data`，服务 `~/Library/LaunchAgents/com.word-dance.server.plist`，`wd serve` 启动时自动跑迁移并先做 `backups/pre-migrate-10-to-11.db.gz`（`backup.py:54,284`）——**启动新代码 = 执行不可逆迁移**，所以顺序是先备份、再停、再切、再起。所有 `wd` 命令需 `export WD_DATA_DIR=/Users/sqin/word-dance-data`；`D=$WD_DATA_DIR`。

1. **预检**（不停机）：新提交上 `make test` 全绿（Mac 上 `test_deploy_files.py` 与 `test_config.py::test_defaults_without_environment` 的已知失败除外）；§5.4 排练通过（含 `full_seed` 硬门）；`shasum -a 256` 再核一次用于取词典字段的 `stardict.db` 的 zip；确认管理页任务列表没有在飞的 `claude` 调用；Q9 提示词改动已合入同一提交或已登记「不对 xs 预生成」。
2. **构建前端快照**（不影响运行中的服务）：`SHA=$(git rev-parse --short <新提交>)`；`cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm ci && npm run build -- --outDir $D/frontend-releases/$SHA.new --emptyOutDir`。
3. **手工全量备份**：`.venv/bin/wd backup --keep-daily 14 --keep-weekly 8`，记下文件名。
4. **停服务**：`launchctl bootout gui/$(id -u)/com.word-dance.server`；`curl --noproxy '*' http://127.0.0.1:8000/api/health` 应被拒。
5. **切代码**：`git checkout <新提交>`（依赖无变化，跳过 `make setup`）。
6. **发布前端快照**：`mv $D/frontend-releases/$SHA.new $D/frontend-releases/$SHA`；`ln -sfn frontend-releases/$SHA $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"`（BSD `mv` 无 `-T`）。
7. **迁移**：`.venv/bin/wd migrate --dry-run`（只应列 `0011_primary_stage.sql`）→ `.venv/bin/wd migrate` → 输出 `applied 0011_primary_stage.sql`，`ls $D/backups/pre-migrate-10-to-11.db.gz`。
8. **导种子**：`.venv/bin/wd import-seed`（`kv.seed_version` 已被 0011 清空，不会 no-op；期望 ≈47 inserted / ≈4,300–4,400 updated；若报 `unknown stage code` 说明代码与种子不配套 → 第 12 步回滚）。
9. **只读验收**：`sqlite3 -readonly $D/word-dance.db` 跑 §5.3；`.venv/bin/wd check db`。
10. **整理文件**（服务仍停）：`.venv/bin/python -c "import sqlite3; c=sqlite3.connect('$D/word-dance.db', isolation_level=None); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.execute('ANALYZE'); c.execute('VACUUM')"`（`isolation_level=None` = 自动提交，`VACUUM` 不能在事务内）（9.4 MB → ≈5.6 MB；`ANALYZE` 让 `ix_words_stage_min` 的计划不漂）。
11. **起服务并验证**：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist`；`curl --noproxy '*' http://127.0.0.1:8000/api/health`；登录后 `GET /api/stages` 5 行；设置页 5 个阶段 chip，sqin/kimi 主攻分别显示 四级 / 初中；词库 6 个页签在 375 px 不横滚；筛词页 5 张卡；管理页预生成下拉含「小学」（Q9 未合入则不点）；注册测试账号看欢迎页 5 个角色与默认勾选；`~/Library/Logs/word-dance/word-dance.log` 有 `applied migration 0011_primary_stage` 与 `seed_imported`，无 `stage_fallback`/`seed_import_failed`。
12. **回滚**（仅在第 11 步失败时）：`launchctl bootout …` → `.venv/bin/wd restore $D/backups/pre-migrate-10-to-11.db.gz --yes`（`DEPLOY.md:284`：要求服务已停，`wal_checkpoint(TRUNCATE)`）→ `git checkout 75df534` → `ln -sfn frontend-releases/<上一个 sha> $D/frontend.tmp && python3 -c "import os; os.rename(...)"` → `bootstrap` → `health`。**没有「只回代码」的回滚**：旧代码对新库不是 500 而是**静默错位**——`index_to_stage(4)='cet6'` 让 sqin 的主攻阶段显示为「六级」、kimi 显示为「高中」，而词库/筛词列表因 `stage_min=5` 不满足旧 `StageIndex` 返回 500（`schemas.py:65`、`security.py:597`）。回滚丢失迁移后的学习记录，所以第 4–11 步一气呵成，选无人学习的时段。

停机时长：迁移 0.05 s + 导种子 ≈0.5 s + `VACUUM` 数秒 + 启动 ≈ 1 分钟以内。

---

## 7 风险（含三份评审点名的致命缺陷在本设计中的归宿）

| 风险 / 评审指出的缺陷 | 本设计的处置 |
|---|---|
| minimal 的词表接口与交付不符（三位评审一致） | §3.8.2 按交付原貌写规则；`scripts/test_relabel_seed.py` 表驱动钉住每条；`unresolved` 必须为空 |
| minimal 的 `STAGE_TAGS` 缩表改变 `has_stage_tag`（三位评审） | D-14 解耦 |
| minimal/stages-as-data 依赖 `stardict.db`（两位评审） | 主路径就地重标；新词头字段取自**已校验**的本机 `stardict.db`（sha256 对上 `fetch_ecdict.sh:13`），没有时 `ecdict.csv` |
| learner-first 的 `zk ⊂ gk` 不变量（三位评审致命） | D-22 不断言；117 个反例写进发布说明 |
| learner-first 的迁移未排练 | 本文 §5.4 已排练最终 SQL |
| learner-first 的主攻 `zk` 默认 | D-4 改 `xs` |
| stages-as-data 的 `zk_ext/gk_ext`（A3）、`Stage = str`、TEXT `stage_min` | 不采用；目标模型归档 |
| 三份共同：`full_seed` 默认 skip、无 CI | D-21 硬门写进 runbook 第 1 步与 §5.4 |
| 三份共同：「只回代码」是静默错位 | 第 12 步与发布说明 |
| 三份共同：词表归一化缺口 | D-8/D-9 |
| `sources` 全量换名让 ≈4,359 行 `updated_at` 前移 → 卡片 SVG 缓存失效 | 无害（重渲染），写进发布说明 |
| 6 个页签 375/360 px 算术未真机量测 | 第 11 步 DevTools 复核；备选去 `fill` |
| 小学词的 AI 内容按成人提示词生成 | D-19：同窗口发布 Q9；否则不对 xs 预生成 |
| 新词头 4 条人工释义质量 | 词表线复核（§9） |
| Linux 生产机 SQLite 版本未知（`RENAME` 新语义 ≥ 3.26；`json_each` ≥ 3.38 只影响 `wd check`） | Lighthouse 部署前用同一 `rehearse.py` 在目标机跑一次 |
| 小学页签按成人 `frq` 排序（前 15 词全是功能词）；上海课本词只有 46% 在二级 505 内 | 模型层不解决；§8.2 Q-10 交产品负责人；`legacy:*` 与 `cs2025:hs*` 令牌为后续拓展层/排序字段留足信息 |

### 8.1 被封死或变贵的未来路径（诚实清单，承自 minimal §7.2）

1. 每用户「上海/全国」方案：需要 `word_stage_tags` 或 `stage_sh_*` 列、第二个 `stage_min`、`user_settings.scheme`、`/api/stages?scheme=`、6 处选词模板按方案取列、前端数据驱动页签——即 stages-as-data 的全部工作 + 第二次迁移；本设计只保留回填令牌。
2. 「拓展/超纲」层：不存在；`legacy:zk/gk` 是候选集，但要表达它需要第 6 个阶段或 tag 表。
3. 再加阶段 = 一次表重建 + 10→5 份常量 + 契约 + 前端 7 文件（毫秒级，但停机）。
4. 阶段仍是硬编码（5 份常量 + 5 个前端文件 + `/api/stages` 固定 5 行）。
5. 教材/年级/单元顺序：种子格式无字段；小学词按成人 `frq` 排序。
6. 6 级 `difficulty`：仍需 ≈12 文件的契约变更；`+1` 是推迟不是解决。
7. **没有**封死：上海 342 词组、2025 高中 117 个国家附表新建词头、考试院 200 个高中补充词——都是词表更新（改 `data/lists/`、重跑 `relabel_seed.py`、`import-seed`），模型不变。

### 8.2 仍需产品负责人拍板的问题（每个都有默认值，实现先按默认进行）

| # | 问题 | 默认（本设计按此实现） | 改变默认的代价 |
|---|---|---|---|
| Q-1 | 2022 附表的数词/月份/星期是否归「小学」 | 是（D-7） | 一行集合定义 + 重跑 `relabel_seed.py` |
| Q-2 | 高中 = 2025 ∪ 2020 还是只认 2025 | 并集（A2 原文「含 2020 版」） | 一行集合定义；`cs2020:*` 令牌已记录 |
| Q-3 | 括号变体（英美拼写、全称、`dad/mum/bye`、`is/are/has`）是否与词头同享旗标 | 同享（D-9） | 改 R7 为「只授予词头」；`color/television/is` 会掉层 |
| Q-4 | 47 个新词头（含 `excited/frightened/stuck` 等分词形容词）是否入库 | 入（D-9/D-23），4 条人工释义 | 否则这些课标词没有阶段 |
| Q-5 | 上海表 342 个词组是否入库 | 本轮不入 | 词表线定释义来源与 `kind='phrase'` 规则后，只是词表更新 |
| Q-6 | 新用户默认 `["xs","zk"]`/主攻 `xs`；初中生预设含小学 | 是（D-4/D-5） | 改 DDL 默认要再重建一次 `user_settings`（下次迁移） |
| Q-7 | 是否给 kimi（只选初中）自动加小学 | 否 | 0011 加一条 `UPDATE` |
| Q-8 | `xsFull` 文案 | 「小学（课标二级词汇）」 | 改 `zh.ts` + `FRONTEND.md §8` |
| Q-9 | `StageChips only` 与「课标外」芯片是否纳入本切片 | 纳入（D-18） | 删两段前端代码 |
| Q-10 | 小学页签仍按成人 `frq` 排序；上海小学课本词只有 46% 在二级 505 内（judge-learner-product §2） | 接受课标口径与 `frq` 排序上线；拓展层与 `order`/`unit` 字段留待教材词表与具体性常模（`[INDEX D5]` Lancaster CC BY 4.0） | 模型层另一次迁移（触发条件见 D-1） |
| Q-11 | `AUDIENCE`/提示词第一句何时加「小学」 | 随 Q9 切片同窗口；之前不对 xs 预生成 | 本切片顺手改两处 + `CLAUDE_INTEGRATION.md:211` |

### 8.3 工作量（人日）

| 项 | 人日 | 说明 |
|---|---|---|
| 0011 定稿 + `test_db` 升级测试 + 后端常量/映射/排序/默认/`is None`/`ecdict`/导入器报错/`seed_check`/`diag` 不变量 | 1.5 | SQL 已排练；其余常量级 + 3 个小函数 |
| `relabel_seed.py`（解析/归一/集合/新词头/不变量/stats/ATTRIBUTION）+ `build_seed.py` 瘦身 + `scripts/test_relabel_seed.py` + 在本机跑出新种子并排练导入 | 1.5 | 规则已在 `membership_v4.py` 验证过一遍 |
| 前端：枚举、角色、页签、CSS、`only`、课标外、文案、12 处夹具、4 个新测试、`FRONTEND.md §8` 镜像 | 1.0 | |
| 后端测试更新（§5.1 ≈15 个文件）+ 新测试（§5.2） | 1.5 | 机械但多 |
| 文档（API/FRONTEND/DESIGN/TASKS/DEPLOY/README/ATTRIBUTION/qa/CURATION） | 0.5 | |
| 排练、上线、验证、发布说明 | 0.5 | |
| 缓冲 | 0.5 | |
| **合计** | **7.0** | 词表任务、Q7/Q9 切片另计 |

---

## 9 对其他两条线的依赖与接口

### 9.1 词表来源与种子流水线线

本线**消费**：`data/lists/moe-2022-level2.txt`、`moe-2022-level3.txt`、`moe-2022-appendix.tsv`、`shmeea-2020-junior.txt`、`shmeea-2020-junior-appendix.tsv`、`moe-2020-senior.tsv`、`moe-2025rev-senior.tsv`、`moe-2020-senior-appendix.tsv`、`moe-2025rev-senior-appendix.tsv` 的**现有原貌**（文件名、`#` 头注释、括号/斜杠/等号写法、TSV 列）；三份 README §4 的规则就是 §3.8.2 的输入契约。请求：
1. **不要**改文件名、不要预拆分、不要加 MANIFEST；任何体例变更先改 README 再通知本线改 R1–R11。
2. 交付 `data/lists/headword-overrides.jsonl`（默认 4 条见 §3.8.4；释义文字由词表线复核），并复核 47 个新词头清单（`relabel_seed.py --dry-run` 输出）。
3. 词组（`shmeea-2020-junior-phrases.txt` 342 条）本轮不入库；若词表线综合稿决定入库，接口是：每条词组必须有非空 `translation`（ECDICT 命中或人工），`kind` 由 `derive_kind` 得 `phrase`，阶段 `zk`，令牌 `sh2020:phr`——模型不需改动，只是 `relabel_seed.py` 多读一个文件。
4. 若词表线也设计了构建器（data-engineering 的 `normalise.py`、official-purist 的 `seed_diff.py`、`--dry-run`/`DIFF.md` 报告），以本文 §3.8.5 的接口为准，可嫁接其 `seed_diff` 式 exit-1 检查与 `SeedPlan` 报告；阶段逻辑只在 `relabel_seed.py` 一处。
5. `TASKS.md`/`README`/`DESIGN.md:209` 的验收常量由 `relabel_seed.py` 的 `stats.json` 填入，词表线不要另行手填数字。

### 9.2 配图更易记线

本线**提供**的稳定接口：
1. 「小学词」= `words.stage_xs = 1`，等价于 `WordBrief.stage_min === 1` / `stages ∋ 'xs'`；`stage_min` 永远 ≥ 1 或 NULL（无 0），`schemas.stage_to_index("xs") == 1`、`stage_to_index("zk") == 2`。配图线的风格开关请用**阶段码集合**（`WD_IMAGE_KID_STAGES`，空 = 关），不用 `0` 哨兵（images 三位评审都指出 `KID_STAGE_MAX=0` 在「小学 = 0」下失效——本设计不取 0，但码集合更稳）；`kid_max_index()` 用 `schemas.stage_to_index(...)` 而不是 `STAGE_ORDER.index(...) + 1`。
2. 迁移编号：**0011 已被本线占用**，配图线的第一个迁移从 **0012** 起（`db.py:159` 不要求连续）；`user_settings.image_hint` 用 `ALTER TABLE ADD COLUMN`，不搭本线的重建；其 `UPDATE … CASE current_stage` 常量按本设计的 1..5 写：儿童集合 = `current_stage IN (1, 2)`（xs/zk），线上 user 2 迁移后为 2。
3. 每词仍只有一张 active 图、`show_images` 仍是全局开关：「同一词给小学生插画、给成人照片」在本模型里不可表达（per-learner 风格留待 `word_images` 多图模型）；风格按**词**的 `stage_min` 选是本轮唯一可行的挂点。
4. 提示词文件 `content_system.txt`、`content.AUDIENCE`、`PROMPT_VERSION`、`CLAUDE_INTEGRATION.md:211/232-235` 由 Q7/Q9 切片改（本线只改 `STAGE_ZH` 常量来源）；本线在该改动合入前不对 `xs` 预生成。
5. `/api/stages` 5 行、`StageInfo` 形状不变；`WordBrief.stages` 多一个可能值 `'xs'`，前端 `isStage` 自动接受。

---

## 10 核对清单与产物

**按 75df534 重新打开核对的代码位置**：`schemas.py:9-10,25-26,47,51-52,56-67,65,77,245-249,361-362,427,448-457,471-472,488,708,1335`；`seed.py:1-20,43,47-68,72-82,184-185,204-210,239-241,248-316,333-353`；`services/words.py:39,143-151,228-229,264-288,563-597,663-696(669,673)`；`services/ecdict.py:28,117-123,158-181(177)`；`routers/vocab.py:52-56,75-80(78),83-106`；`services/bank.py:85-86,161-182(181)`；`security.py:587-610(597),612-614,661-664`；`services/screen.py:34-36,39-48(44,46-47),51-56`；`services/batches.py:60,232-234,266-273(272),314-318,690-699(694,698)`；`ai/prewarm.py:32-39`；`ai/content.py:46,48,49,88`；`services/stats.py:173-196,229`；`routers/onboarding.py:25-45(36)`；`routers/settings.py:90,116`；`routers/admin_ops.py:369-381`；`main.py:307-319,478-485`；`db.py:41,195-249`；`diag.py:52-77`；`cli.py:87-110`；`backup.py:54,284`；`migrations/0001_init.sql:25-37,50-54,59-64,139-162(147-148),166-204(181-186,188,195),205-210,383-390(387),572-576`；`0008/0009/0010`（未 `ALTER` 两表）；`scripts/build_seed.py:15-17,81-88,105-106,112-142,147,150-151,180-198,201-219`；`scripts/pack_seed.sh:44-47`；`scripts/check_contract.py:226-246,301-308`；`scripts/eval_provider.py:107,341-348`；`scripts/smoke.py:352,614`；`Makefile:77-81,93-98`；`frontend/src/api/types.ts:5-6,37,45,52,73`；`api/endpoints.ts:80-85,131,328`；`components/word/StageChips.tsx:7-42`；`components/word/WordHeader.tsx:13,32-33,50`；`components/list/WordRow.tsx:97`；`components/study/StudyCard.tsx:172,207,298`；`pages/WordDetailPage.tsx:360`；`pages/WelcomePage.tsx:30-51,72-73,236-262,323`；`pages/VocabPage.tsx:29,70,202,213,232`；`pages/ScreenPage.tsx:20,31,41,54-57`；`pages/ScreenRunPage.tsx:34-35`；`pages/SettingsPage.tsx:72-77,303-317`；`pages/AdminPage.tsx:36,845`；`i18n/zh.ts:25,28-29,86`；`i18n/zh.test.ts:56,67-83`；`i18n/zh.contract.test.ts:61-83`；`components/ui/ui.css:453-470`；`components/word/word.css:77-98`；`frontend/scripts/check-copy.mjs`、`package.json` scripts；测试 `conftest.py:34-46`、`test_db.py:13-17,283-310,362-366`、`test_api_schemas.py:32-39`、`test_vocab.py:65-79,107-114,150-161`、`test_screen.py:116,129-136`、`test_seed.py:90-100,338-353`、`test_onboarding.py:98,120,139`、`test_settings.py:57-58,88-89,109-112`、`test_security.py:315`、`test_auth.py:82`、`test_words_resolve.py:279,346,478`、`test_reports.py:29,87`、`test_history.py:112`、`test_content_apply.py:255-257`、`test_batches.py:120-130`、`test_scheduler.py:336-344`、`test_schemas.py:122-126`、`fixtures/mini_seed.jsonl`（60 条）；文档 `API.md:155,160,167,169,187,230,239-240,271,279,286,459-460`、`FRONTEND.md:50,56,89,147,231,234,292`、`DESIGN.md:32,40,72,186,202,209,321-322,330,350`、`TASKS.md:166-182`、`DEPLOY.md:283-284,294-296`、`CLAUDE_INTEGRATION.md:211,232-235`、`README.md:3,5,9,78,103`、`qa-frontend.md:36,42`、`WORD_LIBRARY_CURATION.md §1.2/§1.6`；`docs/SCHEMA.sql` 与 0001 `cmp` 字节相同。

**本文产物**（`scratchpad/synthesis-stage-model/`）：`0011_primary_stage.sql`（§3.4 全文）；`rehearse.py` + `rehearsal.db`/`empty.db`/`migrations/`（§5.4）；`membership.py`→`membership_v4.py`（规则 v1→v4 的演进：v2 修多词括注被按空格拆开的 bug、v3 把屈折形式回指改为新建词头、v4 加连字符反向等价）与 `membership.json`、`final.json`、`run2–4.txt`（§3.8.6 全部数字的出处）。

**引用的评审与设计**：`minimal-delta.md` §1–§7（骨架、0011、runbook、封死路径）；`learner-first.md` §3.4/§3.5/§3.7/§3.8/§3.10/§4.1（令牌族、`relabel_seed.py`、`only`、用户影响表、常量去副本、`is None`）；`stages-as-data.md` §3.1/§3.10/§5.2（导入报错、默认绑定测试、`check db` 不变量、`ANALYZE`、目标模型）；`judge-data-safety.md` §1/§2.2/§3.2/§4.2/§5/§7；`judge-learner-product.md` §2/§3/§4/§5/§6；`judge-maintainer.md` §1.2–§1.4/§2/§3/§4/§5。
