# 评审：阶段模型三份设计 —— 角度「产品与学习科学怀疑者」

基线：仓库 `main @ 75df534`（只读）；线上只读副本 `scratchpad/live-copy.db`（`?mode=ro` 打开）；词表任务已交付的 `data/lists/`（未跟踪文件，作为数据用 `python3.12 -I` 解析）；日期 2026-11-06。评审对象：

- **minimal-delta**：`design/stage-model/minimal-delta.md`（加 `stage_xs` 列、索引重编号 1..5、地区/拓展只留在 `words.sources`、0011 已在副本上经 `run_migrations` 排练、`build_seed --base` 携带规则、`COALESCE(difficulty + 1, stage_min, 6)`）。
- **stages-as-data**：`design/stage-model/stages-as-data.md`（`stage_defs` 7 行 + `word_stage_tags` + `stage_presets`，`stage_min`/`current_stage` 改阶段码，`StageIndex` 退出契约，前端数据驱动，0011 已排练，≈9 人日）。
- **learner-first**：`design/stage-model/learner-first.md`（五阶段重编号 1..5 显式字典、布尔列 + `stage_xs`、`sources` token 词汇表、老词重标不剔除、默认初中生预设、`relabel_seed.py` 就地重标、学习卡芯片只显示目标阶段，≈6.5 人日）。

评审立场：盯住上海小学生/初中生/高中生与两名老用户的真实体验、默认值、页签与 chips、排序与推荐、配图证据（INDEX D1）、过度/欠设计；**默认每个未被证明的说法都是错的**，凡能复算的都复算了一遍（§2）。我自己的脚本在 `scratchpad/judge-learner-product/compute_check.py`（只读打开副本；不执行任何其他 agent 的脚本，只读它们的产物）。

---

## 1 引用抽查（≥10 处；结论：三份设计的代码行号基本全部属实，错在推理而不在引用）

| # | 引用（设计 → 位置） | 核验结果 |
|---|---|---|
| 1 | 三份 → `schemas.py:25-26,51-52,56-67,65`（`Stage`/`StageIndex` 字面量、`STAGE_ORDER`、位置推导、范围检查 `1 <= int(index) <= 4`） | 属实（逐行打开） |
| 2 | 三份 → `schemas.py:488 / :708 / :1335` 三个请求内联 `Literal` | 属实；`:488` 还含 `"all"`、`:708` 含 `"auto"`、`:1335` 含 `"all"` |
| 3 | 三份 → `seed.py:43,60-64,72-82,184-185,204-208`（覆盖式 UPSERT、未知码静默丢弃、`STAGES.index(stages[0]) + 1`） | 属实 |
| 4 | minimal-delta → `ecdict.py:177` 位置推导「`STAGE_TAGS` 改成 `(cet4, cet6)` 后 cet4 会被算成 1」 | 属实：`ecdict.py:177` 是 `(STAGE_TAGS.index(stages[0]) + 1)`，必须改。但 minimal-delta **没说**同一改动会改变 `has_stage_tag`（`ecdict.py:122-123`），而 `words.py:669,673` 用它决定是否沿 `lemma_pointer` 回指原形——learner-first 第 3.7 节指出了这一点并保留四个标签，只改 `stages` 属性 |
| 5 | 三份 → `vocab.py:53-56,78,86-98`（阶段筛选、`COALESCE(w.difficulty, w.stage_min, 5)`、`/api/stages` 循环） | 属实 |
| 6 | 三份 → `bank.py:85-86,181`（默认副本、未知阶段静默过滤并回落） | 属实 |
| 7 | 三份 → `security.py:597,613,661-664`（`index_to_stage(int(...))`、docstring、注册只插三列） | 属实 |
| 8 | 三份 → `screen.py:35,44,46-47`、`batches.py:60,272,314-318,698`（距离 CASE、`int(x or DEFAULT)`、快照只写不读） | 属实；`grep settings_json` 全仓库只有 `batches.py:316` 一处写入 |
| 9 | 三份 → `prewarm.py:32-39`、`content.py:46-49,88`（`STAGE_ZH[s]` 的 `KeyError` 风险） | 属实 |
| 10 | 三份 → `main.py:307-319,482-485`（`seed_check`、先迁移后导种子）、`db.py:195-249`（运行器） | 属实；`db.py:41` 文件名正则接受三份设计各自的文件名 |
| 11 | 三份 → `StageChips.tsx:7-9,31,33`、`WelcomePage.tsx:30-42,72-73`、`VocabPage.tsx:29,202,232`、`ScreenPage.tsx:20,31`、`AdminPage.tsx:36`、`types.ts:5-6,45,52`、`zh.ts:25,28-29,86`、`word.css:77-84`、`ui.css:453-473` | 属实；`WelcomePage.tsx:72-73` 的兜底确为 `ROLE_PRESETS.pro`（learner-first 要改它，minimal-delta 与 stages-as-data 没提） |
| 12 | minimal-delta → `test_screen.py:136` `stage=xx` → 400（所以码名不能用 `xx`） | 属实 |
| 13 | stages-as-data → `check_contract.py:158-170`「`export type Stage = string` 自动不参与联合比对」 | 属实：`:160-168` 只在全部成员是 `'…'` 或整数时收进 `unions`，否则 `values = []` |
| 14 | 三份 → `test_db.py:362-366`（`docs/SCHEMA.sql` 与 0001 字节一致） | 属实 |
| 15 | learner-first → 0011 里 `INSERT INTO system_events(kind, detail_json, created_at)`、`json_set(push_batches.settings_json …)` | 列名属实（`0001_init.sql:59-64,387`）；`kind` 无 CHECK；JSON1 在 `.venv` SQLite 3.54.1 内置。**但这份迁移没有排练**（见 §3.3） |
| 16 | 三份 → 0011 重建 DDL 复制 0001 的列清单 | 核验 0008/0009/0010：**没有任何后续迁移给 `words`/`user_settings` 加列**（只有 `0010` 对 `ai_calls` 加 `provider`），所以三份 DDL 都是列完整的，不会悄悄丢列 |
| 17 | minimal-delta / stages-as-data「已在副本上经真实 `run_migrations` 排练」 | 属实：`scratchpad/design-stage-model-minimal/rehearse_0011.py:4,26,75,90` 与 `design-stages-as-data/probe0011.py:17,57,86` 都 `from wd import db` 并调 `db.run_migrations`；产物 `live-rehearsal.db` 已到版本 11、`stage_xs` 列存在、`stage_min` 2/3/4/5 分布 2099/1792/1577/3694、两用户 `(4, 2)`、`kv.seed_version` 已删、`v_bank` 在；`new.db` 已到版本 11、`stage_defs` 7 行/预设 5 行/tag 18,321/两用户 `cet4`/`zk`/`foreign_key_check` 空 |
| 18 | learner-first「本稿自己跑过的东西：`compute.py`」 | 属实，且**只有** `compute.py`（`scratchpad/stage-model-learner-first/` 只有 `compute.py` 与 `sets.json`）；迁移 SQL 未跑 |
| 19 | 三份 → INDEX `[A3][A4][A5][A6][A7][B2][B4][B5][C1][C2][D6]`、`[verify seed-pipeline O3]`、`[verify stage-model 遗漏 1-4]`、`[stage-model-13/19/20/21]`、`[frontend-stages-12/13/14/15/16/19/20]`、`[seed-pipeline-12/13/23]` | 条目存在且内容与引用一致（逐条 grep） |
| 20 | stages-as-data「用户 2 只有 1 个生词」 vs learner-first「kimi 10 个生词全是二级词」 | 两者都对、口径不同：`user_words` 用户 2 共 10 行（9 `known` + 1 `new`），`v_bank`（new/learning）只有 1 行；10 个词 `a, and, be, have, i, in, it, of, the, to` 全在二级表（我的复算） |
| 21 | learner-first「sqin 67 词中 55 个最低阶段下移（39 高中首、15 初中首、1 小学首）」 | 复算完全一致：`{3: 39, 2: 15, 1: 1, 4: 12}` |

---

## 2 独立复算（`compute_check.py`，输入 = 已交付的 `data/lists/*` + 只读副本；口径见脚本）

| 项 | 我的数字 | minimal-delta | stages-as-data | learner-first | 判读 |
|---|---|---|---|---|---|
| `xs` = 二级 ∩ 库 | 508（含 `a/an` 拆分与带点缩写） | 505 | 500 | 500 + 5 | 一致 |
| `zk` = 上海 2020 ∪ 三级 ∩ 库 | 1,988–2,007 | ≈1,993 | 1,983 | 2,015 | 一致（变体展开口径） |
| `gk` = 2025 修订 3100 ∩ 库 | 3,117（主表）/ 3,175（含附表） | ≈3,204（∪ 2020 版） | 3,077 | 3,134 | stages-as-data 偏低 1.3%，其余一致 |
| 无阶段词 | 250（gk 只取 2025）/ 247（∪ 2020） | ≈237 | 254（全部有 ext） | 248 | 一致；其中**有内容或配图的 0 个**（三份都对） |
| `xs − zk` | **∅** | 「只有 ice cream」 | ∅ | ∅ | 二级 ⊂ 三级成立 |
| **`zk − gk`（learner-first 断言为 0）** | **119**（含 2025 附表与 `=`/`ame`/`pl.` 变体归一后；117 个只来自上海表，2 个来自三级：`media, yourselves`；其中 110 个也不在 2020 版 3000；85 个今天 `stage_gk=1`） | 不作此断言 | 不作此断言 | **断言 `stage_zk=1 ⇒ stage_gk=1`，验收 SQL 期望 0** | **learner-first 的不变量不成立**（见 §3.3） |
| 老 zk 离开核心 / 其中无阶段 | 506 / 77 | ≈506 / 71 | 511 / 80 | 496 / 76 | 一致 |
| 老 gk 离开核心 / 其中无阶段 | 1,157 / 218 | ≈1,078 / 207 | 1,195 / 222 | 1,140 / 216 | 一致 |
| 新 `stage_min` 分布 1..5 / NULL | 508 / 1,480 / 1,251 / 1,813 / 3,860 / 250 | 505 / 1,489 / 1,333 / 1,734 / 3,864 / 237 | 500 / 1,483 / 1,228 / 1,827 / 3,870 / (ext 254) | 500 / 1,515 / 1,235 / 1,807 / 3,857 / 248 | 一致 |

**两组三份设计都没算、但对上海小学生最要紧的数字**（同一脚本）：

1. **教材词 vs 课标词**：牛津上海版小学 Anki 词头（`scratchpad/list-sources/06/heads.txt`，非官方、仅作核验基准 [INDEX C4]）在库 776 个，其中**只有 358 个（46%）在二级 505 内**；258 个落在「初中」（`above, actor, afraid, balloon, bathroom, carrot, chocolate, classmate, cloud…`），41 个只在「高中」，**105 个只在四/六级**，14 个在新定义下**没有任何阶段**（`crayon, sharpener, sunglasses, bookstore, motorbike, computer game, hooray…`）。mahavivo 小学表（旧「小学大纲」）434 个在库词里 421 个在二级内，无阶段的 3 个是 `are, is, crayon`。含义：A1「小学 = 二级 505」让一个三年级学生的「小学」页签覆盖不到课本词汇的一半，而这不是任何一份设计能在模型层解决的——但 stages-as-data 的 `xs_ext` 行是唯一不需要再重建表就能接住它的位置，minimal-delta 与 learner-first 都要再做一次迁移。
2. **小学页签的排序对儿童无用**：`xs` 页签 `sort=freq` 的前 15 个词是 `the, be, and, of, a, in, to, have, it, i, that, for, you, he, with`——全部是功能词；INDEX D1 的证据是「具体性是最强预测量、儿童从图学词优于从词学词」，`seed-pipeline-23` 早已指出 `crayon/panda/blackboard` 会排到最后。三份设计都原样保留 `frq` 作首要排序键；只有 minimal-delta 在 §7.2-5 诚实地把它列为「产品很快会撞到的墙」。

---

## 3 逐份评审

### 3.1 minimal-delta

**做对了什么（对学习者可见的）**
- 新用户默认 `["xs","zk"]` / 主攻 `xs`（§3.7）：在用户点「我是…」之前欢迎页就按 `settings.stages` 预勾（`WelcomePage.tsx:72-73`），步骤 1 必须提交（`onboarding.py:32-43`、`API.md` 端点 13「no path to done that skips step 1」），所以这个默认是「什么都不点就下一步」的孩子真正拿到的设置；主攻 `xs` 让推荐词按 `screen.py:35` 的距离先出小学词（0）再初中词（1）——对首要受众是对的方向。
- `初中生` 预设改为 `xs+zk`（与 `高中生 → zk+gk` 的向下含一级一致，`[frontend-stages-14]`），小学词在初中生的推荐里排在初中词之后（距离 2），不会抢占。
- 最低阶段隐藏「仅本阶段新增」开关（`VocabPage.tsx:232`），顺手修掉今天初中 tab 的空操作（`[frontend-stages-19]`）。
- 6 个页签的 375 px 媒体查询（6×48 + 20 = 308 ≤ 343）与「上线前真机复核」。
- 老用户规则写死：`current_stage + 1`、`stages_json` 原样、不自动加 `xs`，并明确拒绝「给只选初中的用户自动补小学」——尊重用户选择，正确。
- 迁移真的排练过（§1 第 17 行），数字与我的复算一致（§2）。
- 诚实清单 §7.2 列出被封死的路径（方案维度、拓展层、再插阶段、硬编码、教材顺序、6 级尺子）。

**致命缺陷**：没有找到会导致线上错误、契约破坏或测试红的缺陷。

**非致命但应修的**
1. `ecdict.STAGE_TAGS = ("cet4","cet6")`（§3.5）同时改变 `has_stage_tag`（`ecdict.py:122-123`），而 `words.py:669,673` 用它决定运行时 ECDICT 词是否回指原形：一个只带 `zk`/`gk` 标签且 `frq=0` 的屈折条目从此会被回指到原形。行为变化很小（Mac 部署根本没装 ECDICT，`WORD_LIBRARY_CURATION.md §1.2`），但设计自称「逐文件、逐函数」却没写这一句；learner-first 的处理（保留四个标签、只改 `stages` 属性）更稳。
2. 种子重建硬依赖 851 MB `stardict.db`，本机没有（§3.8.2 自己承认要下 216 MB、绕开 BSD 工具差异）——4.5 人日里这一天的不确定性最大；learner-first 的 `relabel_seed.py`（就地改旧种子，不需要 stardict）是更现实的生成路径，可以直接嫁接。
3. 对小学生的两处体验欠设计：① 一个二级词带 `xs/zk/gk/cet4` 四五个 chip（我的复算：牛津小学词头 776 个里 358 个会同时属于 ≥4 个阶段），设计只说「接受换行」；② `sort=difficulty` 下有 AI 内容的小学词（`difficulty=1 → 键 2`）排在没有内容的小学词（键 1）之后——恰好把最可能被学的词排后面（§3.2 自己写明，归为「只影响词库页」）。
4. 无阶段的 ≈237–250 个词只在「全部」可见、永不被推荐，且没有任何 UI 告诉学习者为什么；其中就有 `crayon, sharpener, sunglasses` 这类上海小学课本词（§2）。设计把信息保留在 `sources`（`l2_2022 / l3_2022 / sh_zk_2020 / hs_2020 / hs_2025`），但**没有**保留 `hs_2025` 的星级（无星/一星/两星 = 义务教育/必修/选择性必修）——learner-first 的 `cs2025:hs0/hs1/hs2` token 更细，将来做「高一/高二」不必重解析。
5. 词表接口（§3.8.3）假定「一行一个词头、并列已拆、不含变体」，而词表任务实际交付的文件含 `a/an`、`bike (=bicycle)`、`colour (ame color)`、`child (pl. children)` 注记（`data/lists/moe-2022-level2.txt` 等；我的解析若不归一会把 `=bicycle`、`pl. children` 当缺词）。三份设计都有这个接口错位，minimal-delta 把归一化全部推给词表任务，风险最高。

**评分**：fit 6.5 · correctness 8.5 · effort_risk 7.5 · maintainability 4.5 · evidence 8.5 · rollout 8.5 → **overall 7.4**。
理由：正确性与证据最扎实、上线路径最短（11 步 Mac runbook、预先构建 SPA、可选 VACUUM、「没有只回代码的回滚」写得最清楚）；但对小学生的体验只做到「有一个小学页签」，并把下一步产品一定会要的东西（教材拓展、芯片降噪、儿童排序）全部封死或推走。

### 3.2 stages-as-data

**做对了什么**
- 唯一把「阶段是数据」做实的方案：10 份后端常量 + 5 个前端字面量消失，`content.STAGE_ZH` 的 `KeyError` 类风险（`[D6]`）、`bank.py:181` 的静默回落（改为 WARNING 事件）、`seed.py:184-185` 的静默丢弃（改为报错中止、`seed_check` 捕获）、`screen.py:44` 的 0 值陷阱全部随常量消失；`bank.DEFAULT_*` 与 DDL 默认用测试钉死——这些是三份里最好的工程卫生。
- 拓展层让 254 个掉出官方表的词仍可被找到（`含拓展词` 开关、设置页可勾），`stage_min` 对 ext-only 词仍非空，`prewarm all` 覆盖它们——这是三份中唯一不让 `crayon/granny/bathtub` 从所有推荐里消失的设计。
- 默认 `["xs"]` / `xs`，理由是「偏低的失败模式一眼可见、可改；偏高会让小学生点下一步就拿到初中词」（§2 A6）——这是三份里对默认值最清醒的论证。
- 迁移真的排练过且产物与文本一致（§1 第 17 行）；性能探针存在（`probe0011.py`），数字量级合理。
- `scheme` 列预留：上海方案日后只加行；这是 INDEX Q3-a 推荐路线的落点。

**致命缺陷**：没有找到会导致线上错误或测试红的缺陷（排练与 FK 检查都在）。

**严重但已声明的风险（扣分项）**
1. `Stage = str` 让 `check_contract.py` 不再比对阶段集合（自己在 §3.2.4 承认）。`API.md §9` 的「冻结契约」哲学靠这个脚本和 tsc 的 `Record<Stage,…>` 缺键报错支撑（`[A7]`），两道门禁同时消失，换成运行期 `require_codes` + 一条测试。对单人维护的项目，这是把编译期错误换成运行期 400。
2. 拓展层的**第一批内容就是 A3 说「不再作为依据」的两张来源不明的表**（`[A1]`：`中考英语词汇表.txt`、`Highschool_edited.txt`）加 ECDICT `zk/gk` 标签，却以「初中拓展（旧考纲）」「高中拓展（旧考纲）」的名义出现在设置页、欢迎页可选阶段和 `/api/stages` 里。254 个 ext-only 词（`bookshop, crayon, dustbin, granny, armchair, bathtub, bingo…`）是日常/课本词，不是「旧考纲」；1,195 个 `gk_ext` 里 955 个本来就在四六级。对一个 2026 年的高三学生，「高中拓展（旧考纲）1,195 词」是误导性的学习信号（`[C2]`：高考自 2019 起不以旧大纲为依据）。机制是对的，首批载荷与文案是错的。
3. 工作量被低估：前端 10 个源文件 + `useStages` hook + `AuthContext` + 16 个测试文件 + CSS 估 2.5 人日；后端新模块 + 15 个文件 3 人日。按经验 9 人日会变成 12–14；「2 用户时代价最低」的论证对工作量不成立，只对数据成立。
4. `/api/stages` 对所有用户返回 7 行、设置页 7 个 chips（今天 4 个一行放下，`[frontend-stages-17]`；7 个在 375 px 必然两行），`ScreenPage` 要按 `tier`/用户阶段过滤——未决问题 1、2 自己也承认 UX 没验证。
5. `gk` 核心 3,077 比 INDEX 的 3,112 与我的 3,117 少 1.3%（`h2025.entries.tsv` 解析口径），文中按「±1%」声明，踩线。

**评分**：fit 7.5 · correctness 7.5 · effort_risk 4.0 · maintainability 8.5 · evidence 8.0 · rollout 7.0 → **overall 7.0**。
理由：这是唯一能接住 §2 两组数字里「教材拓展」那一半的模型，也是工程卫生最好的；但它用 9+ 人日和一次契约破坏，换来的近期可见收益只有「254 个词还能找到」和一个默认隐藏的开关，而首批拓展内容恰恰是产品负责人已经不认的词表。对 2 个用户、≤10 个朋友的近期规模，这是过度设计；作为「目标模型」它仍是对的。

### 3.3 learner-first

**做对了什么（这一份的产品思考最好）**
- §3.1 用五类用户旅程逐行推导每个模型决定，是三份里唯一把「学习者看到什么」放在第一位的；§1 末尾与 §3.10 的「上线前/后对比表」「老用户看到什么、为什么是对的」可以直接变成发布说明。
- **学习卡芯片只显示用户目标阶段 ∪ 最低阶段**（`StageChips only` prop，`WordRow.tsx:97`、`WordHeader.tsx:50` 经 `StudyCard.tsx:172/207/298`，详情页 `WordDetailPage.tsx:360` 仍显示全部；消费点我逐一核过）：小学生的卡只看到「小学」一个 chip，四级用户不被 412 个新「初中」chip 打扰，顺带消掉 375 px 换行——这是三份里唯一直接改善儿童界面噪音的改动。
- `relabel_seed.py`：就地重标旧种子，不依赖 `stardict.db`，带别名表（`Mr→mr.`、`café→cafe`、`colour/color`）与 `legacy:zk/gk` token；在 Mac 上可跑。比 minimal-delta 的「下 216 MB 再 build」现实得多。
- 保留 `ecdict.STAGE_TAGS` 四个值、只改 `stages` 属性，保住 `words.py:669,673` 的回指逻辑（§1 第 4 行）。
- `sources` token 细到 `cs2025:hs0/hs1/hs2`（课标星级），为「高一/高二」留了数据。
- 建议把 `seed.STAGES`、`words.STAGES`、`content.STAGE_ZH` 改为引用 `schemas.STAGE_ORDER/STAGE_NAMES_ZH`，消灭副本——在不改模型的前提下减少镜像负担的务实一步。
- 用户归宿数字与我的复算**完全一致**（sqin 67 词 `{39, 15, 1, 12}`，kimi 10 词全 `xs`）。

**致命缺陷（按本轮定义：会导致测试红或违反假设而未说明）**
1. **累计不变量 `stage_xs=1 ⇒ stage_zk=1 ⇒ stage_gk=1` 在它自己的 A2 定义下不成立。** §2 A2 行说「二级 ⊂ 三级 ⊂ 3100 是课标原文 … 所以 `stage_xs=1 ⇒ stage_zk=1 ⇒ stage_gk=1`」，§5.4 验收 SQL `SELECT COUNT(*) FROM words WHERE stage_zk=1 AND stage_gk=0; -- 0`，§5.4 末尾要把它写进 `test_full_seed_acceptance_numbers` 与 `TASKS.md`。但 `zk` = 上海 2020 ∪ 三级，而上海表有一批派生副词/形容词不在任何国家表里（INDEX `[B5]`：仅上海 415 词中 148–156 个两边都没有）。我的复算：含 2025 附表与变体归一后仍有 **119** 个 `zk` 词不在 3100 内（117 个只来自上海表：`clearly, happily, arrival, importance, chopstick, e-mail, ferry, foreigner, headmaster, luggage…`；2 个来自三级：`media, yourselves`），其中 110 个也不在 2020 版 3000。它自己的 `compute.py:155` 构造旗标时也没有强制累计（`(w in xs, w in zk_new, w in gk_new, …)`），§3.5 的 `gk` 3,134 ≈ 3100 ∩ 库，说明模拟里确实没有把这 119 个词补进 `gk`。所以二选一：要么验收红（119 ≠ 0），要么 `relabel_seed.py` 强制 `gk=1`，那样「高中 = 国家高中课标 3100」就变成「3100 ∪ 上海初中表」——对 A2 的偏离没有声明。它用这条不变量支撑「初中生只勾初中仍覆盖小学」——那一半（`xs ⊂ zk`）是对的，`zk ⊂ gk` 这一半是错的。
2. **0011 迁移没有排练**，却以「期望 ~36–40 inserted / ~2,800 updated」「500/1515/1235/1807/3857/NULL 248」的口吻写成已验证的样子（§5.4、§6）。`scratchpad/stage-model-learner-first/` 只有 `compute.py` 与 `sets.json`。我逐列核过它的 SQL（`system_events(kind, detail_json, created_at)`、`push_batches.settings_json`、JSON1 函数、`DROP VIEW` 顺序、显式列清单）没有发现错误，但在另两份都真跑过 `run_migrations` 的对照下，这是证据等级的实质差距。

**非致命但应修的**
3. 默认 `["xs","zk"]` / **主攻 `zk`**（D5），理由是「初中是五四学制里人数最多的四年」——没有任何来源；产品负责人说的首要受众是小学。一个三年级学生什么都不点就「下一步」，`screen.py:35` 会先推初中词（距离 0）、小学词排后（距离 2）——正是 stages-as-data 警告的「偏高的失败模式」。改一行就好，但方向反了。
4. `UPDATE push_batches SET settings_json = json_set(…)` 改写历史快照：`settings_json` 的语义是「当日所用设置的快照」（`0001_init.sql:387`），改写它等于否认快照属性；另两份选择不动并在 0011 头注释说明口径，更对。
5. 与 minimal-delta 同样：无阶段 248 词从推荐中消失且无 UI 解释（它提了一个 P2 的「课标外」chip，比 minimal-delta 好一点）；`frq` 排序对儿童无用的问题没有提。
6. 工作量 6.5 人日里没有包含修第 1 条（重算验收数字、重写 §2/§3.5/§5.4 的不变量）。

**评分**：fit 7.0 · correctness 5.0 · effort_risk 7.0 · maintainability 5.5 · evidence 6.0 · rollout 7.0 → **overall 6.2**。
理由：产品思考最好、对老用户的解释最清楚、芯片降噪是唯一直接服务儿童界面的改动；但一条自相矛盾的核心不变量、一份未排练的迁移和一个背离首要受众的默认值，让它不能原样采用。

---

## 4 三份共同的盲点（从学习者与学习科学看）

1. **小学页签的内容与顺序都不是给小学生的**（§2）：二级 505 只覆盖上海课本词汇的 46%；`frq` 排序把功能词排最前。INDEX D1 的证据（具体性是最强预测量、儿童从图学词更好、一次一图）指向的是「具体名词 + 干净插画 + 按课本单元」，三份设计的模型层都没有给「顺序/单元」留字段（minimal-delta §7.2-5 承认）。这不是本轮能解决的，但应作为 Q2-c 与「种子格式加 `order`/`unit` 字段」的明确后续项写进最终方案。
2. **默认值与引导**：三份给出三个不同默认（`xs+zk/xs`、`xs/xs`、`xs+zk/zk`），都没有引用任何用户数据。从「失败模式可见、可改」与首要受众出发，主攻必须是 `xs`；`stages` 含不含 `zk` 影响不大（主攻优先排序），含 `zk` 的好处是初中生少点一下。
3. **词表接口与交付不匹配**：交付文件带 `a/an`、`(=bicycle)`、`(ame color)`、`(pl. children)`、TSV 星级列，三份设计各自假设了不同的格式（plain txt / MANIFEST / `(variant)`），没有一份对着 `data/lists/` 的实际文件写归一化规则；最终方案必须以交付文件为准重写接口段。
4. **配图线的挂点**：三份都只给了「`stage_xs=1`/`xs` tag 即小学词」这一个信号；但 D1 的准则（图在回忆之后出现、无文字、风格按**学习者**而非按词）和 D2 的约束（每词只有一张 active 图，`show_images` 只有全局开关）意味着「同一个 `apple` 给小学生插画、给四级用户照片」在三份模型里都不可表达。不是本切片的错，但最终方案应明说：配图风格先按词的 `stage_min=1` 选插画链（505 词的儿童插画对成人也无害——D1「成人可不配图」），per-learner 风格留待 `word_images` 多图模型。
5. **「初中生预设含小学」的学习意义**：三份都接受了 `[frontend-stages-14]` 的建议，没有问「初二学生要不要 505 个小学词进推荐池」。按距离公式它们永远排在初中词之后，实际影响是 chips 噪音与「初中 tab 2,015 vs 仅新增 1,515」的数字差——可接受，但应在文案里解释（learner-first 的 `newOnlyZk: '仅初中新增（不含小学）'` 是对的做法）。

---

## 5 值得嫁接到最终方案的点

| 来源 | 点子 | 为什么 |
|---|---|---|
| learner-first | `StageChips only={settings.stages}`：列表/学习卡只渲染目标阶段 ∪ 最低阶段，详情页显示全部 | 儿童界面降噪、消掉 375 px 换行；消费点已核（`WordRow.tsx:97`、`WordHeader.tsx:50`、`StudyCard.tsx:172/207/298`、`WordDetailPage.tsx:360`） |
| learner-first | `scripts/relabel_seed.py`：就地重标旧种子 + 别名表 + `legacy:*` token，不依赖 `stardict.db` | Mac 可跑；把 minimal-delta 的「种子只增不减」从 `--base` 携带变成「同一文件改写」的天然保证 |
| learner-first | 保留 `ecdict.STAGE_TAGS` 四值，只改 `stages` 属性 | 保住 `words.py:669,673` 的回指逻辑 |
| learner-first | `sources` token 带课标星级 `cs2025:hs0/hs1/hs2` | 将来「高一/高二」不必重解析 |
| learner-first | 老用户影响表 + 发布说明口径；`stage_min IS NULL` 显示「课标外」chip（P2） | 让 kimi/sqin 看懂「初中 tab 为什么变了」 |
| learner-first | `seed.STAGES` / `words.STAGES` / `content.STAGE_ZH` 改为引用 `schemas` 常量 | 不改模型也能减少镜像负担 |
| minimal-delta | 已排练的 0011 全文（含 `DROP VIEW v_bank` 顺序、显式列清单、`DELETE FROM kv WHERE key='seed_version'`、不动 `push_batches`）与 11 步 Mac runbook | 直接可用 |
| minimal-delta | 最低阶段隐藏「仅本阶段新增」；`xx` 是测试探针不可作码名；`test_upgrade_0011_*` 规格；「`source='seed'` 的线上 lemma 全在种子里」检查 | 低成本、防回归 |
| minimal-delta | 诚实的「封死路径」清单 | 应原样进入最终方案的「已知债务」 |
| stages-as-data | 默认取最低阶段（主攻 `xs`）的论证；`WelcomePage.tsx:72-73` 兜底改为小学预设 | 失败模式可见 |
| stages-as-data | 导入器对未知阶段码**报错中止**（替代 `seed.py:184-185` 的静默丢弃），`seed_check` 捕获并记 `system_events`；`bank.py:181` 回落时记 WARNING；`DEFAULT_STAGES/DEFAULT_CURRENT_STAGE` 与 `pragma_table_info` 默认值用测试钉死；`wd check db` 加「`stage_min` 与旗标一致」不变量；迁移后 `ANALYZE` | 工程卫生，不依赖 tag 表也能做 |
| stages-as-data | 拓展层的**概念**（词掉出官方表后仍可被找到），以及 `sources`/tag 的 `sources` 按表码登记 | 在布尔列模型里先用 `words.sources` 令牌 + 一个「全部」页签的「课标外」筛选实现其 80% |
| 本评审 | 验收只断言 `xs ⊂ zk`，**不**断言 `zk ⊂ gk`；把 119 个上海独有非 3100 词列进发布说明 | 避免 learner-first 的矛盾 |

---

## 6 排名与裁定

**排名**：1. minimal-delta（7.4） 2. stages-as-data（7.0） 3. learner-first（6.2）。

| 维度 | minimal-delta | stages-as-data | learner-first |
|---|---|---|---|
| fit | 6.5 | 7.5 | 7.0 |
| correctness | 8.5 | 7.5 | 5.0 |
| effort_risk（高 = 量小险低） | 7.5 | 4.0 | 7.0 |
| maintainability | 4.5 | 8.5 | 5.5 |
| evidence | 8.5 | 8.0 | 6.0 |
| rollout | 8.5 | 7.0 | 7.0 |
| **overall** | **7.4** | **7.0** | **6.2** |

**裁定**：以 **minimal-delta 为骨架**（布尔列 + `stage_xs`、重编号 1..5、已排练的 0011、`sources` 令牌、`COALESCE(difficulty + 1, stage_min, 6)`、默认 `["xs","zk"]` / 主攻 `xs`），**嫁接 learner-first 的全部学习者侧改动**（`StageChips only`、`relabel_seed.py`、`STAGE_TAGS` 四值保留、星级 token、老用户影响表、「课标外」chip、常量去副本）和 **stages-as-data 的防御性工程**（导入器拒绝未知码、默认值钉 DDL、回落 WARNING、`check db` 不变量、`ANALYZE`）。不采用 learner-first 的 `zk ⇒ gk` 不变量、`push_batches` 快照改写与主攻 `zk` 默认；不在本轮做 `stage_defs`/tag 表与拓展层——但把 stages-as-data 写进 DESIGN 作为**目标模型**，触发条件写死：上海高中 200 词/手册词表取得（`[B7]`）或出现许可干净的教材词表（Q2-c）时，用 `words.sources` 令牌一次回填 `word_stage_tags`。

同时必须交给产品负责人的两条「三份都没解决」的决定（§2、§4-1）：① 上海小学生的课本词汇只有 46% 在二级 505 内——是接受「小学 = 课标二级」的口径，还是立刻启动教材拓展层（许可问题见 `[C4]`）；② 小学页签按成人词频排序对儿童无用——是否在种子格式加 `order`/`unit`，或先用具体性常模（Lancaster CC BY 4.0，`[D5]`）作小学词的次级排序。任何一份设计上线后，这两条会是上海家长最先反馈的问题。
