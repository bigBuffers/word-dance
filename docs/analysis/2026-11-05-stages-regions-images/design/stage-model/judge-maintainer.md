# 评审：阶段模型与地区维度三份设计 — 角度「维护者怀疑者」

评审对象：同目录 `minimal-delta.md`、`stages-as-data.md`、`learner-first.md`。基线 `main @ 75df534`；调研依据 `INDEX.md`（引用 `[INDEX A3]` 等）；线上只读副本 `scratchpad/live-copy.db`。日期 2026-11-06。

我的视角只盯五件事：契约镜像负担（`types.ts` / `API.md §9` / `FRONTEND §8` / `check_contract.py` / `CLAUDE_INTEGRATION §4.1`）、硬编码是否真的减少、测试与文档改动量是否被低估、工作量估算是否诚实、实现时最容易出错的地方。默认每个未被证明的说法都是错的，下文凡写「核验」都是我按 75df534 重新打开代码或自己跑出来的。

---

## 0 一页结论

| | minimal-delta | stages-as-data | learner-first |
|---|---|---|---|
| fit | 7 | 8 | 8 |
| correctness | 8 | 7 | 6 |
| effort_risk（高 = 量小险低） | 7 | 4 | 7 |
| maintainability | 4 | 8 | 5 |
| evidence | 8 | 7 | 7 |
| rollout | 8 | 7 | 8 |
| **overall** | **7.0** | **6.7** | **6.8** |

**排名**：minimal-delta > learner-first > stages-as-data（后两者分差在误差内；按我的角度——镜像负担与爆炸半径——learner-first 靠前）。

**裁定**：三份设计的 0011 都能在线上副本上通过真实 `run_migrations`（§1.2，我独立复跑），迁移本身都不是问题；差别在词表接口、契约面与自洽性。

- minimal-delta 的模型（`stage_xs` 布尔列 + 索引重编号 1..5 + 一个 0011）最小、最稳，但它完全没有减少硬编码（自己承认），工作量 4.5 人日偏低，且 §3.8.3 的词表接口与词表任务**实际交付**的 `data/lists/` 不符（§3.1）。
- learner-first 与 minimal-delta 是同一个模型，多了显式字典、Mac 可跑的就地重标脚本、学习者影响分析；但它写进验收脚本的「`stage_xs ⇒ stage_zk ⇒ stage_gk` 累计不变量」在它自己的重标规则下**不成立**（约 111–120 个只在上海表的词不在任何高中课标表；§3.3 F1），要么验收红，要么违反 A2 而未声明。
- stages-as-data 是唯一真正消灭 10 份常量的方案，性能与迁移都实测过；但 `zk_ext`/`gk_ext` 以 A3 明令退出「阶段依据」的两张 mahavivo 表为依据，却标成「采用」；`Stage = string` 让 `check_contract.py` 永久失去阶段取值的编译期守卫；`stages_of(row) or []` 配 17 个单行 `word_brief` 调用点是实现期最容易静默出错的地方；9 人日明显偏低。

**最终方案建议**（§5）：以 minimal-delta 的模型为骨架，嫁接 learner-first 的显式字典/单源常量/`relabel_seed.py`/用户影响表，与 stages-as-data 的「导入未知码报错」「默认值绑定测试」「`wd check db` 不变量」；不做 ext 阶段；`stage_defs` 路线保留为 Q3 拍板后的第二次迁移蓝图。

---

## 1 核验记录

### 1.1 抽查引用（≥10 处，全部按 75df534 重新打开）

| 引用（三份设计共同或各自） | 结果 |
|---|---|
| `schemas.py:25-26,47,51-52,56-67,472,488,708,1335` | 属实。`index_to_stage` 写死 `<= 4`（`:65`），minimal-delta 说要改成 `len(STAGE_ORDER)` 正确 |
| `seed.py:43,60-64,72-82,184-185,204-208` | 属实。`:185` 未注册阶段码静默丢弃；`:208` `STAGES.index(stages[0]) + 1` |
| `services/ecdict.py:28,117-123,173-177` | 属实。`:177` 用 `STAGE_TAGS.index(stages[0]) + 1`——minimal-delta「若 `STAGE_TAGS` 改成 `("cet4","cet6")` 则 cet4 → 1 = xs」的警告成立；`has_stage_tag = bool(self.stages)`（`:122`）被 `words.py:669,673` 用于屈折形回指 |
| `services/words.py:39,143-151,228-229,576,590-595,663-696` | 属实 |
| `routers/vocab.py:52-56,78,86-107` | 属实（`COALESCE(w.difficulty, w.stage_min, 5)`） |
| `services/bank.py:85-86,161-182`、`security.py:597,613,661-664` | 属实（注册只插三列吃 DDL 默认；`bank.py:181` 静默过滤未知阶段） |
| `services/screen.py:34-36,44,46-47,51-56`、`services/batches.py:60,232-234,272,314-318,698` | 属实（`int(x or DEFAULT)` 三处；`settings_json` 快照存的是**整数** `current_stage`，learner-first 对其 `json_set +1` 语义正确） |
| `ai/prewarm.py:32-39`、`ai/content.py:46,48,49,88`、`services/stats.py:173-196` | 属实 |
| `migrations/0001_init.sql:25-38,139-162,180-212,266,572-576`、`db.py:41,195-249` | 属实（运行器 `PRAGMA foreign_keys=OFF` 在 `BEGIN IMMEDIATE` 之前，`foreign_key_check` 后自写 bookkeeping） |
| `scripts/check_contract.py:150-170,174,260-281` | 属实，且有一个三份设计都没点透的事实：它**只比对属性名**（`compare_shape`）与 `export type` 字面量联合，不解析类型引用。所以 stages-as-data 说 `export type Stage = string` 会自动退出比对是对的（`parse_types_ts` 遇到非字面量成员 `values = []`）；同时意味着 `Stage` 的取值集合从此没有任何工具守卫 |
| `frontend/src/api/types.ts:5-6,37,45,52,73`、`StageChips.tsx:7-9,31,33`、`zh.ts:25,28-29,86`、`WelcomePage.tsx:30-42,72-73`、`VocabPage.tsx:29,202,232`、`ScreenPage.tsx:20,31`、`AdminPage.tsx:36`、`endpoints.ts:80-85,131,328` | 属实。`Record<Stage` 共 5 处（`grep` 复算）；`zh.stages[…]` 下标 9 处；含 `STAGE_ORDER/isStage` 的非测试源文件 6 个 + `AdminPage` 字面量 |
| `tests/unit/test_db.py:13-17,51,362-366`、`test_api_schemas.py:32-39`、`test_screen.py:116,136`、`test_vocab.py:69-79,107-114,150-161`、`test_seed.py:90-100,338-353`、`test_schemas.py:122-126`、`test_onboarding.py:98,120,139`、`test_settings.py:57-58,88-89,109`、`test_security.py:315`、`test_auth.py:82`、`test_words_resolve.py:279,346,478`、`test_reports.py:29,86-87`、`test_history.py:112`、`test_content_apply.py:255-257`、`test_batches.py:127`、`test_admin_ops.py:435,463,477` | 全部属实。触及阶段的后端测试文件共 14 个（含三份设计都没列的 `test_scheduler.py:340`，但它只用 `stages_json` 码，三案下都不红）；前端测试文件匹配阶段相关正则 17 个；`stage_min: N` 夹具 12 处 / 10 文件 |
| `docs/API.md:155,160,167,169,187,230,239-240,271,279,286,459-460`、`FRONTEND.md:231-235,292`、`DESIGN.md:72,186,202,209,321-322,330,344-350`、`DEPLOY.md:361,421`、`CLAUDE_INTEGRATION.md:211,232-235`、`TASKS.md:168-180` | 全部属实 |
| `test_screen.py:136` `stage=xx → 400`（minimal-delta 用来否决码名 `xx`） | 属实 |
| INDEX 条目 [A3]/[A4]/[A5]/[A6]/[A7]/[B2]/[B4]/[B5]/[C1]/[C2]、矛盾 9/14/15、Q1–Q6 | 引用与原文一致 |

线上副本基线（`sqlite3 -readonly`）：用户 `(1, ["zk","gk","cet4","cet6"], 3)`、`(2, ["zk"], 1)`；`stage_min` 2,099/1,792/1,577/3,694；旗标 2,099/3,829/4,722/7,671（(词,阶段) 对 18,321）；`difficulty = stage_min` 44/49（<2、>3）；`push_batches` 4 行 `current_stage` 皆 3；25 张表 + `v_bank`；三份设计引用的数字全部对得上。

### 1.2 我独立复跑了三份 0011

脚本 `scratchpad/judge-maintainer/rehearse_all.py`（`.venv/bin/python -I`，Python 3.12 / SQLite 3.54.1，`legacy_alter_table=0`）：复制 `live-copy.db` 到私有目录，把仓库 4 个迁移 + 各自 0011 放进临时目录，调真实 `wd.db.run_migrations`。learner-first 的 SQL 是从其 §3.6 代码块逐字提取的（它自己**没有**跑过，只给了排练步骤）。

| | applied | 耗时 | integrity / FK | 表数 | 用户 1 / 2 | 新默认 | 其他 |
|---|---|---|---|---|---|---|---|
| minimal-delta | `(11,'…')` | 0.045 s | ok / 空 | 25 | `4` / `2`（`stages_json` 原样） | `'["xs","zk"]'` / `1` | `kv.seed_version` 删除；`push_batches` 仍 3；文件 9,449,472 B；二次运行 `[]` |
| stages-as-data | `(11,'…')` | 0.049 s | ok / 空 | **28** | `'cet4'` / `'zk'` | `'["xs"]'` / `'xs'` | tag 18,321（zk 2,099 / gk 3,829 / cet4 4,722 / cet6 7,671）；`stage_min` 变码；`kv` 不动；文件 10,178,560 B |
| learner-first | `(11,'…')` | 0.038 s | ok / 空 | 25 | `4` / `2` | `'["xs","zk"]'` / `2` | `kv.seed_version` 删除；`push_batches` 3→**4**；`system_events` +1；文件 9,449,472 B |

结论：三份 SQL 都正确（`DROP VIEW v_bank` 顺序、显式列清单、外键按名解析），learner-first 的 `json_set`/`system_events(kind, detail_json, created_at)` 列名也对。迁移层面没有可以打分的差距；差距在迁移之外。

### 1.3 我独立重算了词集归宿

脚本 `scratchpad/judge-maintainer/sets.py`（`python3.12 -I`，读**词表任务实际交付**的 `data/lists/*`，括号/斜杠变体展开，`live-copy.db` 以 `?mode=ro` 打开；口径比三份设计的「词头精确匹配」略宽，故 xs 为 518 而非 500）：

- `xs − zk = 0`（二级 ⊂ 三级，三案一致；minimal-delta 说 `ice cream` 是例外，是它用的调研中间文件的伪影，交付件里两表都写 `ice cream`）。
- **`zk(上海 ∪ 三级) − gk(2025 ∪ 2020) = 111`，只对 2025 表 = 120**；上海表减三级表 379 词在库，其中 109 不在任何高中表。
- 旧 zk 2,099 → 离开 496；旧 gk 3,829 → 离开 1,049（只用 2025 表则更多）。
- 新定义下不属任何阶段的词 245（minimal 237 / learner 248 / stages-as-data 的「无核心阶段」254——三案与我都在同一量级），其中有 AI 内容或配图的 **0** 个。
- 新 `stage_min` 分布 518 / 1,497 / 1,327 / 1,727 / 3,848 / NULL 245。
- 用户 2 的 10 个生词全部落在 xs；用户 1 的 67 个生词 0 个落到无阶段、1 个 xs——与 learner-first 的用户影响表一致。

### 1.4 词表任务实际交付了什么（三份设计写接口时都还没有）

`data/lists/`（未跟踪）：`moe-2022-level2.txt`（505 条）、`moe-2022-level3.txt`（1,600 条）、`moe-2022-appendix.tsv`、`moe-2020-senior.tsv` / `moe-2025rev-senior.tsv`（`word<TAB>level`，3000 / 3099 条，`level` 0/1/2 = 无星/必修/选择性必修）、`shmeea-2020-junior.txt`（1,724 条）、`-phrases.txt`（342）、`-appendix.tsv`、`-forms.tsv`、三份 README。**词头保留原貌**：`be (am, is, are)`、`a/an`、`Mr (Mr.)`、`colour (AmE color)`、`PE (=physical education)`、`child (pl. children)`；缩写无点（`Mr`、`PE`），而库里是 `mr.`/`p.e.`（[INDEX 矛盾 9]）。

对照三份设计的接口假设：

| 设计 | 假设的文件 | 假设的格式 | 与交付的差距 |
|---|---|---|---|
| minimal-delta §3.8.3 | `moe2022_level2.txt` 等 5 个 `.txt` | 「并列项已拆分、缩写书写与 ECDICT 词头一致（带点）」，`parse_headwords` 不做任何拆分/归一 | **全部不符**：按设计实现会把 `be (am, is, are)` 整行当词头查 ECDICT；`missing_from_ecdict` 只统计不报错 → 小学/初中层静默少词 |
| stages-as-data §3.10 | `data/lists/MANIFEST.json` 驱动，「每个文件一列词头（plain）」 | 同上，plain | MANIFEST 不存在；plain 解析同样吃不下括号变体 |
| learner-first §3.4/§4.1 | `cs2022_level2.txt`、`cs2025_senior.txt`（带 `*`） | 「可带 `(variant)`/`*`」；别名表 `Mr→mr.`、`café→cafe`、变体归一化（其 `compute.py` 已实现 `split_variants`） | 文件名与 TSV 格式不同，但**归一化层已设计**，改路径即可 |

这不是任何一份设计的「错」（交付在后），但最终方案必须以交付格式为准，而只有 learner-first 的词表→种子入口能直接接上。

---

## 2 契约镜像负担、硬编码、测试/文档量、工作量——横向对照

### 2.1 镜像点逐项

| 镜像点（规则出处） | minimal-delta | learner-first | stages-as-data |
|---|---|---|---|
| `API.md §9` 代码块 ↔ `types.ts`（`types.ts:1-2`） | `Stage`、`StageIndex` 两行各加一值 + 3 处注释 | 同左 | 删 `StageIndex`；`Stage` → `string`；新增 `StageTier`、`StageDef`、`StagePreset`；`StageInfo extends StageDef`；`WordBrief.stage_min` 改类型；`MeResponse` +2 字段（`endpoints.ts:80-85` + `schemas.py:245-249`）——约 6 个形状 |
| `check_contract.py` 顺序敏感联合比对（`:274-281`） | 两边同序即过 | 同左 | `Stage` 退出比对（§1.1）；`StageTier` 新联合；`StageDef/StagePreset` 新接口逐字段比对 |
| `FRONTEND.md §8` ↔ `zh.ts`（`zh.test.ts:67-83`、`zh.contract.test.ts:61-83`） | +3 键（`roles.xs`、`stages.xs`、`xsFull`）+ 改 `sources.lists` | +4 键（另加 `newOnlyZk`）+ 改 `lists` | −12 键（`roles`×4、`stages` 短名×4、全称×4、`newOnlyCet6`）+2 键（`includeExt`、`newOnlyBelow`）；9 处 `zh.stages[s]` 全改 `nameOf` |
| tsc `Record<Stage,…>`（5 处 / 4 文件） | 各加一键 | 同左 | 全部删除（`Stage` 成 `string` 后 `Record<Stage>` 无意义） |
| `CLAUDE_INTEGRATION §4.1`（schema 文件/文档/夹具逐字节）与 §5.1 提示词逐字节（`test_schemas.py:122-126`） | 不改 schema；提示词第一句可选，改则同步 `:211` | 同左 | 同左，另需改 §5.2 示例（`:232-235`） |
| `docs/SCHEMA.sql` 字节一致（`test_db.py:362-366`） | 不改 ✓ | 不改 ✓ | 不改 ✓（提出 `SCHEMA_CURRENT.sql` 未决） |
| `test_db.py` `EXPECTED_TABLES`（`:13-17,51`） | 不变 | 不变 | 25 → 28 |
| `DEPLOY §4` + `env.example`（Settings 镜像） | 无 | 无 | 无 |

三案都正确识别了 `SCHEMA.sql` 规则与 `FRONTEND §8` 镜像；stages-as-data 的镜像负担约为另两案的 4–5 倍，且是一次性破坏性契约变更。

### 2.2 硬编码是否真的减少

现状：后端 10 份常量 + 3 个请求 `Literal`（[INDEX A3]），前端 6 个源文件。

- **minimal-delta：没有减少**。10 份常量各加一值，`build_seed.py` 再加一份 `order`，`bank.py` 默认对继续复制 DDL。它在 §7.2 第 4 条诚实写明「阶段仍是硬编码而非数据」。
- **learner-first：有减少的意图但未承诺**。§3.7 对 `seed.py:43`、`words.py:39`、`prewarm.py:33`、`content.py:49` 写的是「或直接 `from .schemas import …`，消灭一份副本」。若真做，后端常量从 10 份降到约 5 份（`schemas` + `bank` 默认 + `ecdict.STAGE_TAGS` + `eval_provider` + `smoke`），这是零风险的收益，最终方案应把「或」改成「必须」。
- **stages-as-data：真正减少**。10 份 → `bank.py` 一对默认值（有测试与 DDL 绑定）+ `"all"/"auto"` 哨兵 + `'cet6'` 星标特判；前端 0 份字面量。代价是新增 `services/stages.py`（13 个函数）与运行时 DB 校验。注意它的「以后加阶段只加行」仍然是一次 NNNN 迁移 + 种子重建 + ATTRIBUTION（`stage_defs` 只由迁移写入），真正省掉的是前端与契约。

### 2.3 测试与文档改动量是否被低估

- 后端触及阶段的测试文件 14 个（§1.1）。minimal-delta 列了 ≈15 个 ✓；learner-first 列了约 14 个 ✓；stages-as-data 「约 20 个测试」按用例数计 ✓。三案都遗漏了 `test_scheduler.py:340`，但它不红。
- 前端：`stage_min: N` 夹具 12 处三案都算对；stages-as-data 另需在 ≥17 个测试文件给 `MeResponse` mock 加 `stage_defs/stage_presets`——它列了 16 个，接近。
- `ScreenPage.test.tsx`、`StageChips.test.tsx` 确实不存在（新建属实）；`VocabPage.test.tsx`、`WelcomePage.test.tsx` 存在（扩展属实）。
- 文档：三案都覆盖 `API.md`/`FRONTEND.md`/`DESIGN.md`/`TASKS.md`/`README`/`qa-frontend`/`ATTRIBUTION`。stages-as-data 另需重写 `API.md §9.1`、端点 5/19/20/21 与 `DESIGN.md:40,72` 的「数据驱动」措辞。

### 2.4 工作量诚实度

| 设计 | 自报 | 我的估计 | 被低估的项 |
|---|---|---|---|
| minimal-delta | 4.5 | **6–7** | 前端 0.5（7 文件 + CSS + 12 夹具 + 2 新测试 + §8 镜像 + 375 px 复核）；种子 1.0 含下载 216 MB `stardict.db`、绕 BSD 工具、新 `--base` 机制，且 `parse_headwords` 要按真实交付格式重写（§1.4） |
| learner-first | 6–6.5 | **6.5–7.5** | `StageChips only` 牵连 `WordHeader` 取 `useAuth()`（`WordHeader.tsx:50` 被 StudyCard×3、ScreenCard、WordDetailPage、WelcomePage:323 使用），相关测试要补 auth mock；其余分项合理，`relabel_seed.py` 不依赖 `stardict.db` 是真实的省工 |
| stages-as-data | 9（8–11） | **11–14** | `services/stages.py` 13 函数 + 15 个后端模块改写；17 个 `word_brief(` 单行调用点（§3.2 F2）逐个处理；17 个前端测试文件改 mock；`API.md §9` 重写；`wd check` 不变量；MANIFEST 构建器未交付；首次把 `StageInfo extends` 与 pydantic 继承对上 `check_contract` 的联调 |

---

## 3 逐设计评审

### 3.1 minimal-delta（overall 7.0）

**fit 7**：满足 A1/A2/A6；初中 = 并集进同一列；无拓展层，245 左右的词成为只在「全部」可见的词典词（已声明）。「初中生 = xs+zk、主攻 zk」预设与 INDEX Q6 一致。对上海小学首要受众合格，但对「老词去哪了」没有任何用户可见的解释。

**correctness 8**：0011 在我这里通过（§1.2）；`+1` 对「新代码 + 旧种子」也自洽（旧种子 `stages:["zk",…]` 经新 `STAGES` 推出 2）；指出并处理了 `ecdict.py:177` 的位置推导陷阱与 `v_bank` 顺序；`--base` 携带规则封住「导入从不删除 → 旧旗标带着新索引活下来」的坑（`seed.py:72-82` 核验属实）。扣分：① `STAGE_TAGS = ("cet4","cet6")` 顺带改变 `has_stage_tag`（`ecdict.py:122` → `words.py:669,673`），运行时 ECDICT 屈折形回指行为变化未提及；② `vocab.py:78` 改 `COALESCE(w.difficulty + 1, w.stage_min, 6)` 正确（44/49 对齐核验属实），但 `difficulty=5`（beyond）与无阶段词同键 6，文档要写明。

**effort_risk 7**：改动面最小，但 4.5 人日偏低（§2.4）；最大风险是 §3.8.3 的词表接口与交付不符（§1.4）。

**maintainability 4**：硬编码零减少，再加一个 `--base` 机制；§7.2「封死路径」清单写得诚实，是本案最有价值的部分。

**evidence 8**：数字与 INDEX 一致；`[verify stage-model-13]`、`[verify frontend-stages-12/15]`、`[INDEX B2/B5/C1/C2]` 引用准确；`ice cream` 例外是中间文件伪影（§1.3），无伤。配图线 D1 不在范围，正确地只保证 `STAGE_ZH["xs"]` 不崩。

**rollout 8**：Mac 步骤完整（停→快照→migrate→import-seed→验收→可选 VACUUM→前端快照→起服务），明确「没有只回代码的回滚」，引用 `schemas.py:65`/`security.py:597` 正确。

**致命/严重缺陷**
1. **（致命·阻塞种子步骤）词表接口与交付格式不符**（§1.4）：`parse_headwords` 按设计不拆括号/斜杠、不做 `Mr→mr.`，而交付件保留 `be (am, is, are)`、`a/an`、`Mr (Mr.)`；`build_seed.py:119-121` 的 `missing` 只进 `stats.json` 不报错，结果是小学/初中层静默少词、验收「只增不减」仍绿。
2. （严重）工作量 4.5 低估约 2 人日。
3. （一般）`has_stage_tag` 语义变化未提及。
4. （一般）`WelcomePage.tsx:72-73` 的 `ROLE_PRESETS.pro` 兜底未随默认值改（learner-first 改了）。

**值得嫁接**：`--base` 携带规则 + `stats.json.carried_forward`；§5.3 验收第 7 条「`stage_min` 与旗标一致」SQL；`VocabPage.tsx:232` 隐藏最低阶段开关（顺手修 [frontend-stages-19]）；`ecdict.py:177` 显式 `stage_to_index(stages[0])`；§7.2 封死路径清单作为发布说明附件。

### 3.2 stages-as-data（overall 6.7）

**fit 8**：拓展层回答了「老词去哪了」（254 个 ext-only 词可通过「含拓展词」取回）；预设与中文名进库，未来上海方案只加行；`xs` 预设默认 `["xs"]` 的论证（偏低比偏高安全）成立。扣分：ext 层的产品含义与 A3 冲突（见下）。

**correctness 7**：0011 通过（§1.2，28 表、18,321 tag、外键拒绝伪码）；性能实测 0.5–3.5 ms 可信；`Stage = str` 后 `test_settings.py:109`/`test_admin_ops.py:477` 继续 400 的推理正确（`errors.py:28` `validation_error → 400` 核验属实）。扣分见 F2/F3。

**effort_risk 4**：最大爆炸半径：契约一次性破坏、15 个后端模块、8 个页面 + 新 hook + AuthContext、17 个前端测试、`EXPECTED_TABLES`；9 人日偏低。

**maintainability 8**：唯一真正消灭常量、前端数据驱动、未知码由外键与 `require_codes` 双重拒绝、`bank` 默认值与 DDL 绑定测试、`wd check db` 不变量——这些都是维护者想要的。扣分：`check_contract` 守卫丢失是永久性的；`services/stages.py` 是新的单点。

**evidence 7**：数字与 INDEX 一致（`xs − zk = 0`、511/1,195/254 与我的 496/1,049/245 同量级）；对 A3 的解读有倾向性（见 F1）。

**rollout 7**：步骤与回滚同另两案；`xs.enabled=0` 临时隐藏是好杠杆；`ANALYZE` 步骤考虑周到。扣分：0011 之后、新种子之前 `/api/stages` 显示 7 行、其中 3 行为空；设置页 chips 从 4 个变 7 个（含 ext），[verify frontend-stages-17]「5 个 chip-btn 一行放下」不再适用，未提。

**致命/严重缺陷**
1. **（致命·违反假设未声明）A3 说 mahavivo 中考/高中两表「不再作为阶段依据」；本案把这两表 + ECDICT `zk/gk` 标签作为 `zk_ext`/`gk_ext` 两个用户可选阶段（可进 `stages_json`、页签、筛词、预生成）的唯一依据**，却在 §2 标为「采用并细化」。这是实质偏离，应明写为偏离并论证（许可面：[INDEX C4] 只有 ECDICT 与官方词头干净；mahavivo 无 LICENSE）。
2. **（严重·实现最易出错处）`stages_of(row)` 改为 `row.get("stages") or []`**：`word_brief(` 单行调用共 17 处、`word_briefs(` 3 处（`grep` 复算），行来自各路 SELECT；任何一处没附加 tag 就静默得到 `stages: []`（无 chips、`prompt_entry` 的 `stages: []`、而 `stage_min` 仍有值→前后矛盾），没有测试能抓；要么退化成每行一次 tag 查询（N+1）。设计只说了 `word_row()` 与 `word_briefs` 两处。
3. **（严重）`Stage = string` 使 `check_contract.py` 不再比对阶段取值**，`VocabStageFilter/ScreenStage/PrewarmStage` 退化为 `string`，SPA 里阶段码拼写错误不再被 tsc 抓到；守卫移到运行期 + `test_stage_defs_seeded`。已承认，但这是我的角度最不愿接受的永久降级。
4. （严重）工作量 9 低估（§2.4）。
5. （一般）`data/lists/MANIFEST.json` 不存在，构建器设计悬空；plain 解析吃不下括号变体（§1.4）。
6. （一般）ext 与 core 可同时存在于一词（191 个 `zk_ext` 词在 `gk` 核心），「初中 + 含拓展词」页签会混入高中核心词，文案需说明。

**值得嫁接**：导入器对未知阶段码**报错中止**（替代 `seed.py:185` 静默丢弃，[INDEX A6]）+ `main.seed_check` 捕获不致崩（`main.py:307-319`）；`bank.DEFAULT_STAGES/DEFAULT_CURRENT_STAGE` 与 `pragma_table_info('user_settings').dflt_value` 的绑定测试；`wd check db` 两条不变量；`ANALYZE` 上线步骤；`/api/stages` 单条 `GROUP BY`（可选）；`enabled`/隐藏空阶段的思路（布尔列方案可用常量 `HIDDEN_STAGES` 过渡）；整份 §3.3/§3.5 作为 Q3 拍板后路线 B 的蓝图保存。

### 3.3 learner-first（overall 6.8）

**fit 8**：从五类用户旅程推导每个决定（§3.1 表）；默认 = 初中生预设 `["xs","zk"]`/zk；学习卡只显示目标阶段 ∪ 最低阶段的 chips（解决四级用户被 412 个新「初中」chip 打扰）；对 kimi/sqin 的影响逐行算出并与我的复算一致（§1.3）。

**correctness 6**：SQL 我跑通（§1.2），`push_batches.settings_json +1` 与 `system_events` 记录都是另两案没有的周到之处。扣分见 F1：验收不变量与自身规则冲突。

**effort_risk 7**：6–6.5 基本诚实；`relabel_seed.py` 就地重标、不依赖 851 MB `stardict.db`、Mac 可跑，是三案中唯一能在本机直接生成新种子的路径；归一化层已设计（§1.4）。

**maintainability 5**：显式 `STAGE_INDEX` 字典 + 断言 `== position + 1`；建议其余常量从 `schemas` 导入（未承诺）；`sources` 令牌词汇表（`cs2022:l2`、`cs2025:hs0/1/2`、`legacy:zk/gk`）与交付 README 的星级语义（0 = 义务教育已掌握、1 = 必修、2 = 选择性必修）一致，核验属实。

**evidence 7**：排练数字方向与我一致（离开 zk 496 = 我的 496；无阶段 248 ≈ 我的 245；kimi 10 词全 xs ✓）；`sets.json` 只留了 3 个键，大部分数字不可直接复现（`compute.py` 可重跑）。扣分：把「二级 ⊂ 三级 ⊂ 3100 是课标原文」外推成「上海 ∪ 三级 ⊂ 3100」。

**rollout 8**：Mac 版最到位的一条：「`wd serve` 启动时自跑迁移 ⇒ 启动新代码 = 执行不可逆迁移，顺序必须是先备份、再停、再切、再起」；`DEPLOY §10` 加「不可 `--no-restart`」。

**致命/严重缺陷**
1. **（致命·验收红或违反 A2 未声明）累计不变量不成立**：§2 A2 行与 §3.5 规则是 `gk` iff ∈ 3100，而 §5.4 排练与 `test_full_seed_acceptance_numbers`/`TASKS.md` 写入 `SELECT COUNT(*) FROM words WHERE stage_zk=1 AND stage_gk=0; -- 0`。按它自己的数字：zk 2,015、gk 3,134、「仅高中新增」1,235 ⇒ zk ∩ gk = 1,899 ⇒ **116 个 zk 词不在 gk**；我的复算 111–120（§1.3，上海表独有且不在任何高中课标表的词，[INDEX B5] 早已指出 148–156 个两边都没有）。要让断言成立只能把这 ~111 词强行标 `stage_gk=1`——这违反 A2「高中 = 国家高中课标 2025 修订 3100」且未声明。
2. （一般）`StageChips only` 让 `WordHeader` 依赖 `useAuth()`；`WelcomePage.tsx:323` 在引导期（设置未保存）也渲染 `WordHeader`；StudyCard/WordRow/ScreenCard 测试需 auth mock，未计入清单。
3. （一般）§3.7 说保留四个 `STAGE_TAGS` 名是因为 `has_stage_tag` 仍被 `words.py:669,673` 使用，但同时把 `stages` 属性改成只返回 cet4/cet6——`has_stage_tag = bool(self.stages)`（`ecdict.py:122`）会一起变，理由落空，除非改写 `has_stage_tag`。
4. （一般）文件名 `cs2022_level2.txt` 等与交付不符；TSV 星级列与其假设的 `*` 后缀不同——归一化层在，改路径与读列即可。

**值得嫁接**：显式字典 + 位置断言；其余常量改为 `from .schemas import STAGE_ORDER, STAGE_NAMES_ZH`（把「或」改成「必须」）；`relabel_seed.py` 与别名/变体归一化表（直接对接 `data/lists/*` 的真实格式）；`sources` 令牌词汇表（含 `legacy:*` 与 `cs2025:hs0/1/2`）；用户影响表与发布说明口径；`push_batches.settings_json +1`；`screen.py:44`、`batches.py:272,698` 改 `is None`；`VocabPage.tsx:202` 的 `newOnlyZk` 文案；Mac 发布顺序警示。

---

## 4 跨切片发现（对最终方案同样成立）

1. **词表→种子入口是三份设计共同的空档**（§1.4）。交付件保留原貌，任何方案都需要一个归一化层：拆 `(…)`/`/` 并列、`Mr/Mrs/Ms/PE → mr./mrs./ms./p.e.`、`café → cafe`、`mum (AmE mom)` 展开、屈折形查 `word_forms`（`shmeea-2020-junior-forms.tsv` 已单列）、TSV 第一列 + `level`。learner-first 的 `split_variants` 是现成起点。
2. **`has_stage_tag` 的副作用**：两份布尔列方案都会无意改变 `words.py:669,673` 的屈折形回指判断；最终方案应把 `has_stage_tag` 改为「原始 ECDICT tag 含任一 zk/gk/cet4/cet6」而与阶段授予解耦。
3. **`check_contract.py` 的能力边界**：它不校验类型引用，所以 `Stage`/`StageIndex` 的真正守卫是两个 `export type` 联合 + tsc。布尔列方案保留它；数据方案放弃它——这应作为 Q1 拍板时的明示代价。
4. **`docs/SCHEMA.sql` 的定位**：三案都正确地不改它，但 0011 之后「当前 schema = 0001 + 0008 + 0010 + 0011」只靠 `DESIGN.md §3.1` 一句话维持；stages-as-data 提出的 `SCHEMA_CURRENT.sql`（由 `sqlite_master` 导出 + 测试）值得在 0011 同一提交里做，否则下一个人仍会把 `SCHEMA.sql` 当现行 DDL 读。
5. **Mac 部署顺序**：`main.py:482-485` 启动即迁移，learner-first 的「先备份、再停、再切、再起」应写进 `docs/QUICK_DEPLOY_AND_MOBILE.md` 的 Mac 段与 `DEPLOY §10`。
6. **`sources` 列**：三案都把它从「6 个令牌」扩成来源登记（`seed.py:210` 排序空格连接核验属实），但令牌集合三案不同；最终方案定一套并写进 `data/seed/ATTRIBUTION.md` 与 `DESIGN.md §3.2`。

---

## 5 结论与建议

**排名**：minimal-delta（7.0）> learner-first（6.8）> stages-as-data（6.7）。

**裁定**：采用 minimal-delta 的数据模型（`stage_xs` 布尔列 + 索引重编号 1..5 + 单一 0011，`difficulty` 不动、排序改 `COALESCE(difficulty + 1, stage_min, 6)`），因为它是 INDEX Q1 建议 a 的直接落地、迁移与旧种子兼容、镜像负担最小、封死路径说得最清楚。在此骨架上：

- 从 learner-first 嫁接：显式 `STAGE_INDEX` 字典与位置断言；`seed.py`/`words.py`/`prewarm.py`/`content.py` **必须**改为从 `schemas` 导入常量（10 份 → 5 份，这是布尔列方案唯一能拿到的硬编码收益）；`relabel_seed.py` 就地重标 + 别名/变体归一化（按 `data/lists/*` 实际格式）；`sources` 令牌词汇表（含 `legacy:zk/gk`，保留日后拓展层/上海方案的回填信息）；`push_batches.settings_json +1`；三处 `or DEFAULT` 改 `is None`；用户影响表；Mac 发布顺序；默认预设 `["xs","zk"]`/zk（初中生）或 /xs 由产品定。**删除**其 `zk ⊂ gk` 不变量，只保留 `xs ⊂ zk`。`StageChips only` 作为 P2 单独评审。
- 从 stages-as-data 嫁接：导入器对未知阶段码报错中止 + `seed_check` 捕获；`bank` 默认值与 DDL 绑定测试；`wd check db` 不变量；`ANALYZE`；`SCHEMA_CURRENT.sql`；其 §3.3/§3.5 作为路线 B 蓝图归档。**不采用** `zk_ext/gk_ext`（A3）。
- 从 minimal-delta 自身保留：`--base` 携带规则（若用 learner-first 的就地重标，它由构造满足，但 `stats.json.carried_forward` 与「线上 `source='seed'` 的 lemma 全部在种子里」的检查仍要有）；§5.3 验收脚本；§7.2 封死路径清单进发布说明。

**实现前必须先做的三件事**：① 以交付的 `data/lists/*` 真实文件名与格式重写词头解析并在副本上 `wd import-seed --file` 排练，核对 `stats.json.missing_from_ecdict` 与新增 lemma 清单（预期 ≈ 20–40 个真实缺词，见 [INDEX B2/B4] 与 §1.3）；② 把工作量按 6–7 人日而非 4.5 排期；③ 发布窗口与 Q7/Q9 的提示词改动对齐——本切片把「小学」标签送进提示词后，`EXAMPLE_EN_MIN = 15` 会立刻暴露（[INDEX D6]），这一点 minimal-delta §7.1 已指出。

---

## 附录 排练与复算产物

- `scratchpad/judge-maintainer/rehearse_all.py` — 三份 0011 走真实 `run_migrations` 的脚本；产物 `scratchpad/judge-maintainer/work/{minimal-delta,stages-as-data,learner-first}/db.db`（线上副本的私有拷贝，未触碰 `live-copy.db` 与 `/Users/sqin/word-dance-data`）。
- `scratchpad/judge-maintainer/0011_learner_first.sql` — 从 `learner-first.md §3.6` 代码块逐字提取（117 行）。
- `scratchpad/judge-maintainer/sets.py` — 交付词表 × 线上副本的集合算术（§1.3 全部数字）。
- 引用的调研条目：[INDEX A1/A3/A4/A5/A6/A7/A8/B2/B4/B5/C1/C2/C4/D6]、[INDEX 矛盾 9/14/15]、[INDEX Q1–Q6]、[verify stage-model-12/13/遗漏 1-4]、[verify frontend-stages-12/13/15/17/19]、[seed-pipeline-10/11/12]、[ai-prompts-stages-14]。
