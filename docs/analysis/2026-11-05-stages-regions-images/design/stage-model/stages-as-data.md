# 阶段模型与地区维度 — 设计「阶段即数据」（stage_defs + word_stage_tags）

基线：仓库 `/Users/sqin/word-dance`，`main @ 75df534`；线上库只读副本 `scratchpad/live-copy.db`（9,162 词、2 用户）；日期 2026-11-05。调研依据：同目录 `INDEX.md`（[A1]–[D6]、Q1–Q9）与 `facts/`、`verify/`。本文所有 `path:line` 均按 75df534 由本人重新打开核对；所有数字要么来自调研的核验数字，要么来自本文第 5.4 节的排练脚本（`scratchpad/design-stages-as-data/`，只读线上副本的私有拷贝）。本文不改仓库任何代码。

---

## 1 一页结论

**决定了什么**

1. **阶段成为数据，不再是常量。** 新表 `stage_defs`（每阶段一行：`code, scheme, rank, tier, parent, name_zh, full_zh, difficulty_hint, enabled, ecdict_tag, note`）和 `word_stage_tags`（每「词 × 阶段」一行，带 `sources` 记录来源词表）取代 `words` 上的 4 个 0/1 旗标列；`words.stage_min` 与 `user_settings.current_stage` 从 1–4 整数改为**阶段码字符串**（`TEXT REFERENCES stage_defs(code)`）。后端 10 处阶段常量、前端 5 处字面量全部改为读 `stage_defs`（第 3.1 节表）。这是 INDEX Q1 的选项 c / [A3] 的办法 ④，第 3.2 节给出与 =0、追加 5、重编号 1..5 的逐项比较。
2. **5 个核心阶段 + 2 个拓展阶段，一套方案。** `xs` 小学（课标二级 505）、`zk` 初中（上海 2020 表 ∪ 国家三级 1600）、`gk` 高中（国家 2025 修订 3100）、`cet4`、`cet6`（不变）；`zk_ext`、`gk_ext`（`tier='ext'`，`parent` 指向 `zk`/`gk`）收容只因 mahavivo 旧表 / ECDICT `zk`/`gk` 标签而在初中、高中层的旧词。**不做「上海/全国」双方案**（A2 已把上海表并进 `zk`），但每条 tag 的 `sources` 保留「来自哪张表」，`stage_defs.scheme` 列预留，日后加 `sh` 方案只加行不改表（第 3.4 节）。
3. **整数索引退出契约。** `StageIndex` 从 `API.md §9`、`types.ts`、`schemas.py` 删除；`StageInfo.index` → `rank`（来自 `stage_defs.rank`，间隔 10），`WordBrief.stage_min` 与 `Settings.current_stage` 都是阶段码；`Stage` 变为 `string`，由后端在请求时对照 `stage_defs` 校验（未知码仍是 400 `validation_error`）。排序语义（「仅本阶段新增」、推荐词的阶段距离、`sort=difficulty`）全部保留，改由 `rank`/序数与 `difficulty_hint` 驱动（第 3.2.4、3.6 节）。
4. **前端由后端数据驱动。** `GET /api/auth/me` 增加 `stage_defs` 与 `stage_presets`（欢迎页角色含「小学生」，预设存在新表 `stage_presets`），`GET /api/stages` 返回 `StageInfo extends StageDef`（7 行，按 `rank`）；词库页签、筛词卡片、设置 chips、管理页预生成下拉、`StageChips` 全部由此渲染，`ScreenPage.tsx:31` 的静默丢弃与 `bank.py:181` 的静默回落消失（第 3.7 节）。
5. **迁移 0011 一次停机完成两张表重建 + 三张新表 + 数据转换**；已在线上副本的私有拷贝上用真实 `wd.db.run_migrations` 排练通过：0.049 s，17 张表行数不变，`foreign_key_check` 空，`integrity_check ok`，18,321 条 tag 回填与旧旗标完全一致，2 个用户的设置 1:1 转换；代价是库文件 5.6 MB → 10.2 MB（932 个空闲页），上线后手动 `VACUUM`（第 3.3、6 节）。
6. **新用户默认改为 K-12**：DDL `stages_json DEFAULT '["xs"]'`、`current_stage DEFAULT 'xs'`；线上 2 个用户按「码 1:1 映射、不自动加小学」写死在 0011 的 `INSERT … SELECT` 里（第 3.8 节）。
7. **`difficulty` 1–5 尺子不动**（Q5-a）：小学与初中共用 1；`vocab.py:78` 的 `COALESCE(w.difficulty, w.stage_min, 5)` 改为 `COALESCE(w.difficulty, d.difficulty_hint, 5)`，两把尺子从此解耦（第 3.6 节）。

**为什么**

- 现状的根本问题不是「少一个阶段」，而是「阶段 = 元组位置 = 整数 = DB CHECK」这条推导链（`schemas.py:56-67`、`seed.py:208`、`ecdict.py:177`、`0001_init.sql:148,185`）。Q1 的 a/b 两案都要重建两张表（[A4]），却仍留下 10 份常量、`int(x or 3)` 的 0 值陷阱（[A3]）和下一次加阶段再来一遍的账。既然重建不可避免，一次把阶段变成数据，后续「上海方案」「拓展层」「六级星标表」都只是加行。
- 查询性能可控（第 3.5 节实测）：≈18.3 k 条 tag（新种子后 ≈19.7 k）下，词库分页 0.95 ms（旧 1.14 ms）、`/api/stages` 3.4 ms（旧 4 条查询 3.3 ms）、推荐词候选 1.6 ms（旧 1.0 ms）、新增过滤 1.2 ms（旧 0.9 ms）、一页 50 词的 tag 批量读取 0.05 ms——全部在每次请求毫秒级内，无需新索引设计。
- 线上只有 2 个用户、49 行 `difficulty`、4 条 `push_batches` 快照（`live-copy.db`），破坏性契约变更的代价是历史最低（[verify seed-pipeline O3]）。

**代价**

- 一次性工作量约 **9 人日**（范围 8–11，不含官方词表的获取与清洗——那是词表任务的产出，第 7.3 节）。
- 契约破坏性变更一次（`API.md §9` 的 `Stage/StageIndex/StageInfo/WordBrief/MeResponse`），前后端同一提交上线；上线后没有「只回退代码」的回滚，只能恢复 `pre-migrate-10-to-11` 快照（与 Q1 任何方案相同，[verify stage-model 遗漏 2]）。
- 后端约 20 个测试、前端约 16 个测试文件需要同步（第 5 节逐一列出）。

---

## 2 对照本轮假设 A1–A6 的偏离与理由

| 假设 | 采用情况 | 偏离与理由 |
|---|---|---|
| A1 小学 = 国家 2022 二级 505 | **采用**，码 `xs`。 | 无偏离。实测 505 词 500 个已在库、`xs ⊆ zk`（`xs − zk = 0`，因二级 ⊂ 三级），xs 不在旧初中层的只有 `an, astronaut, best, chore, maths` 5 个（第 5.4 节 `fate.py`；与 [B2] 一致）。教材拓展词日后作 `xs_ext` 行加入，不需要改表。 |
| A2 初中 = 上海 2020 ∪ 国家三级；高中 = 国家 2025 修订 3100 | **采用**，码沿用 `zk`/`gk`。 | 无偏离。实测 `zk` 核心 = 1,983 词（上海 1,694 ∪ 三级 1,592，交 1,303），`gk` 核心 = 3,077（2020 版 3000 对应 2,981）。保留旧码名是为了 `stages_json`、`localStorage['wd.vocabTab'/'wd.screenStage']`、路由 `/screen/:stage` 与测试夹具不必迁移。 |
| A3 只用官方词头；mahavivo 中考/高中两表不再作阶段依据 | **采用并细化**：这两表与 ECDICT 的 `zk`/`gk` 标签降为 **拓展层证据**（`zk_ext`/`gk_ext`），不再定义核心层。 | 一处**有意的保留**：`cet4`/`cet6` 的定义不变（ECDICT `cet4`/`cet6` 标签 ∪ mahavivo CET 表，`build_seed.py:105-142`）——A3 只点名中考/高中两表，CET 表按其 README 是 2016 官方大纲的转录（`ATTRIBUTION.md:29`），且本轮调研没有 CET 层的核验数字；若日后要同样「纯化」，`ecdict_tag` 列与 ext 机制已就位，只改构建器一处。 |
| A4 不按省份分层；是否「上海/全国」双方案、是否保留拓展层由设计决定 | **不做双方案；做拓展层。** | 双方案在 A2 的「并集」定义下没有用户可见差别，却让页签/预设翻倍（[frontend-stages-22]）；而拓展层有硬数据支撑：按 A2/A3 重定义后 511 个旧初中词、1,195 个旧高中词会离开核心层，其中 254 个将**不属于任何核心阶段**（第 3.9 节）——没有拓展层它们只能留在「全部」页签里无法被推荐。信息保留靠 `word_stage_tags.sources`（每条 tag 记录来源表码），双方案留作 `scheme` 的加行扩展（第 3.4 节）。 |
| A5 配图先改提示词 | 不在本文范围。 | 本文只保证 `content.py:49 STAGE_ZH` 改为读 `stage_defs.name_zh`，使「小学」标签进入提示词；受众文案与 `PROMPT_VERSION` 交给 Q9 切片。 |
| A6 新用户默认 K-12；2 个用户迁移规则写死 | **采用**：DDL 默认 `'["xs"]'`/`'xs'`；用户 1（sqin）→ `["zk","gk","cet4","cet6"]`/`cet4`，用户 2（kimi）→ `["zk"]`/`zk`，不加 `xs`。 | 默认取**最低**阶段而非 INDEX Q6 建议的 `["xs","zk"]`：欢迎页在用户点「我是…」前就按 `settings.stages` 预勾（`WelcomePage.tsx:72-73`），若默认偏高，一个小学生点「下一步」就会拿到初中词；偏低的失败模式（高中生先看到小学词）一眼可见、可改。 |

---

## 3 详细设计

### 3.1 阶段枚举 4 → 5（+2）：哪些常量消失，去了哪里

现状 10 份后端常量 + 3 个请求 `Literal` + 2 处同类字面量、前端 5 处（[A3]、[verify stage-model-1]）。全部改为读 `stage_defs`：

| 现有位置（75df534） | 现状 | 改后 |
|---|---|---|
| `backend/wd/schemas.py:25` `Stage = Literal[...]` | 闭合字面量 | `Stage = str`（文档型别名；运行时校验见 3.2.3） |
| `schemas.py:26` `StageIndex = Literal[1,2,3,4]` | 整数契约 | **删除**（3.2.4） |
| `schemas.py:51` `STAGE_ORDER`、`:52` `STAGE_NAMES_ZH` | 顺序与中文名 | 删除；`stage_defs.rank` / `name_zh` |
| `schemas.py:56-67` `stage_to_index` / `index_to_stage` | 位置推导 | 删除；码直接入库 |
| `schemas.py:488` `VocabQuery.stage`、`:708` `ScreenNextQuery.stage`、`:1335` `PrewarmRequest.stage` | 三个 `Literal` | `str`（`Field(max_length=16, pattern=r"^[a-z][a-z0-9_]{1,15}$")`）+ `"all"`/`"auto"` 哨兵；路由层 `stages.require_codes()` |
| `backend/wd/seed.py:43` `STAGES`、`:60-64` 四列 + `stage_min`、`:184-185` 过滤、`:204-208` | 常量 + 静默丢弃 | 导入器开始时 `stages.defs(conn)`；未知码 **报错中止**（3.10） |
| `backend/wd/services/words.py:39` `STAGES`、`:228-229 stages_of`、`:576-580`、`:591-594` | 列名模板 | `stages.codes(conn)`；`stages_of` 改为读 `row["stages"]`（由 `word_row`/`word_briefs` 批量附加，3.5.2） |
| `backend/wd/services/ecdict.py:28` `STAGE_TAGS`、`:119`、`:173-177` | ECDICT 标签 = 阶段 | `stage_defs.ecdict_tag` 列（`zk→zk_ext, gk→gk_ext, cet4→cet4, cet6→cet6`）；`word_columns()` 不再产出旗标，另返回 `tags` 由 `_resolve_ecdict` 写入 `word_stage_tags` |
| `backend/wd/ai/prewarm.py:32-33` `STAGE_COLUMNS`/`STAGES`、`:36-39` | 列名 | `stages.member_sql([stage])`；`"all"` 仍是 `w.stage_min IS NOT NULL` |
| `backend/wd/ai/content.py:49` `STAGE_ZH`、`:88` | 第二份中文名 | `stage_defs.name_zh`（`prompt_entry` 读 `word["stages"]` 并映射） |
| `backend/wd/services/bank.py:85-86` `DEFAULT_STAGES`/`DEFAULT_CURRENT_STAGE`、`:181` | 默认复制 + 静默回落 | 唯一保留的常量对 `("xs",)`/`"xs"`，单元测试断言它等于 `pragma_table_info('user_settings')` 的 DEFAULT；`:181` 过滤未知码后若为空 → 回落 + `log.warning(event="stage_fallback")` |
| `backend/wd/services/screen.py:44,46`、`services/batches.py:272,698` `int(x or DEFAULT)` | 0 值陷阱 | 无整数：`cur = s["current_stage"] or bank.DEFAULT_CURRENT_STAGE` → `stages.ordinal(defs, cur)` |
| `scripts/eval_provider.py:107` `STAGES` | 常量 | `SELECT code FROM stage_defs WHERE tier='core' ORDER BY rank` |
| 前端 `types.ts:5-6`、`StageChips.tsx:7-9`、`zh.ts:25,28-29`、`VocabPage.tsx:29`、`AdminPage.tsx:36`、`WelcomePage.tsx:30-42`、`ScreenPage.tsx:20` | 5 份字面量 + 派生 | `useStages()`（来自 `/api/auth/me`）；见 3.7 |

**残留常量（有意）**：① `StageChips.tsx:33` 与 `WordBrief.cet6_star` 对 `'cet6'` 的星标特判——这是六级星标表的产品特性，不是阶段枚举；② `bank.py` 的默认对（与 DDL 互为镜像，有测试钉住）；③ `"all"`/`"auto"` 两个请求哨兵。

### 3.2 索引编码方案：为什么选「字符串码 + stage_defs」

#### 3.2.1 四案比较（INDEX Q1 / [A3]）

| 维度 | ① 小学 = 0 | ② 追加 = 5 | ③ 重编号 1..5 | ④ 字符串码 + `stage_defs`（本文） |
|---|---|---|---|---|
| 必须重建 `words`/`user_settings`（CHECK 变更） | 是 | 是 | 是 | 是（同时改列类型） |
| 现有数据改写 | 不改 | 不改 | `stage_min`/`current_stage` 全部 +1 | 整数 → 码（`CASE`），2 用户 1:1 |
| 「索引 = 顺序」假设 | 保持 | **破坏**：`seed.py:208`/`ecdict.py:177` 的 `stages[0]`、`screen.py:35`/`batches.py:60` 距离算式、`vocab.py:78` 都要查表 | 保持 | 不依赖：顺序来自 `rank` |
| `int(x or 3)` 陷阱（`screen.py:44`、`batches.py:272,698`） | **触发**（0 被当缺失）；改 3 处 | 无 | 无 | 无整数，陷阱消失 |
| `difficulty` 1–5 尺子（`vocab.py:78 COALESCE`） | 错位（小学 0 vs difficulty 1） | 错位（5 既是小学又是 beyond） | 整体错位一格，需 6 级或改提示词 | **解耦**：`stage_defs.difficulty_hint` |
| 文档/契约 | `API.md:460` 映射文字改；`StageIndex` 加 0 | 同左加 5 | `TASKS.md:174`、`API.md:460`、`DESIGN.md:72,186,202,322` 全作废 | `API.md §9` 一次改写（3.2.4） |
| 下次再加阶段（上海方案、教材拓展、`xs_ext`） | 再来一遍 ①–③ | 再来一遍 | 再来一遍 | **加行**：`INSERT INTO stage_defs` + 导种子 |
| 消灭 10 份常量 | 否 | 否 | 否 | 是 |
| 拓展层 / 上海方案 | 另起炉灶（多加列，列数 = 方案 × 阶段，[stage-model-16]） | 同左 | 同左 | 同一张表 |
| 额外工作量（相对 ③） | ≈0 | +0.5 日 | 0 | **+3–4 日**（tag 表、`services/stages.py`、契约） |

结论：①–③ 都要付「停机重建 + 契约改动 + 快照回滚」这笔固定成本，差别只在一两天的代码量；④ 多付 3–4 人日，换来之后每次加阶段/方案只加行，并顺手消灭 0 值陷阱与尺子混用。线上规模（2 用户、49 行 difficulty）让 ④ 的一次性破坏性代价处于最低点。

#### 3.2.2 `stage_defs` 与 `stage_presets` 内容（0011 写入）

| code | scheme | rank | tier | parent | name_zh | full_zh | difficulty_hint | ecdict_tag | 定义（`note`） |
|---|---|---|---|---|---|---|---|---|---|
| `xs` | cn | 10 | core | — | 小学 | 小学（课标二级） | 1 | — | 2022 课标附录 3 二级词汇表 505 |
| `zk` | cn | 20 | core | — | 初中 | 初中（中考） | 1 | — | 上海考试院 2020 词汇表 ∪ 2022 课标三级 1600 |
| `zk_ext` | cn | 21 | ext | zk | 初中拓展 | 初中拓展（旧考纲） | 1 | `zk` | 原初中层不在官方表内的词 |
| `gk` | cn | 30 | core | — | 高中 | 高中（高考） | 2 | — | 高中课标 2017 年版 2025 年修订 附录 2 词汇表 3100 |
| `gk_ext` | cn | 31 | ext | gk | 高中拓展 | 高中拓展（旧考纲） | 2 | `gk` | 原高中层不在官方表内的词 |
| `cet4` | cn | 40 | core | — | 四级 | 大学英语四级 | 3 | `cet4` | 2016 四六级大纲（mahavivo 转录） |
| `cet6` | cn | 50 | core | — | 六级 | 大学英语六级 | 4 | `cet6` | 同上 |

`rank` 间隔 10、ext = parent + 1：两个阶段之间永远能再插行；`UNIQUE (scheme, rank)` 保证同一方案内顺序无歧义。`stage_presets`：`xs 小学生 ["xs"]/xs`、`zk 初中生 ["xs","zk"]/zk`、`gk 高中生 ["zk","gk"]/gk`、`uni 大学生 ["gk","cet4","cet6"]/cet4`、`pro 职场人士 ["cet4","cet6"]/cet4`（现 `WelcomePage.tsx:33-38` 的 4 个预设 + 小学生；`初中生` 预设按 [frontend-stages-14/20] 的建议向下包含小学）。两张表只由迁移写入（见 3.3「运行器约束」），代码只读。

#### 3.2.3 `Stage = str` 后的请求校验

Pydantic 层只做形状校验（`^[a-z][a-z0-9_]{1,15}$`，长度 ≤16）；路由/服务层用 `services/stages.require_codes(conn, codes, field=...)` 对照 `SELECT code FROM stage_defs WHERE enabled = 1`，未知码抛 `ApiError("validation_error", details={"fields": {field: "unknown stage"}})`——与 `screen.py:46-47` 现有写法同型，`errors.py:28` 把它映射成 400，因此 `test_settings.py:109`（`["cet9"]`）、`test_admin_ops.py:477`（prewarm `"nope"`）这类断言继续成立。`_unique_stages`（`schemas.py:77-84`）保留做去重/非空。`stages_json` 写入前校验（`routers/onboarding.py:33-36`、`routers/settings.py:89-92,113-116`），所以库里永远只有已知码；`stage_defs` 行**只禁用不删除**（`enabled=0`），`current_stage`/`stage_min` 的外键因此永远可解析。

#### 3.2.4 `StageIndex` 整数契约的兼容办法

现状：`StageIndex` 出现在 `schemas.py:26`、`types.ts:6`、`API.md:240`，被 `StageInfo.index`（`schemas.py:450`、`types.ts:45`）、`WordBrief.stage_min`（`schemas.py:472`、`types.ts:52`、`API.md:286`）使用；`API.md:460` 规定「服务端把 `zk→1 … cet6→4` 映射到 `user_settings.current_stage`」；`StageChips.tsx:31` 用 `stageMin === STAGE_INDEX[stage]` 高亮最低阶段。

决定：**整数离开契约**，理由与办法：

1. 唯一消费者是同仓库的 SPA（`types.ts:1-2` 声明它是 `API.md §9` 的逐字拷贝，改动走一次「contract change」提交）；导出文件（端点 11，`API.md:153` 的 14 列）不含任何阶段字段，不存在外部消费者。
2. 一旦阶段可插入，「第 N 个」就没有稳定含义（小学到底是 0 还是 1 正是 Q1 的争论）。有序性需求由 `StageDef.rank: number` 满足：任何需要整数排序键的客户端直接用 `rank`。
3. 契约改法（同一提交）：
   - `types.ts` / `API.md §9`：删 `StageIndex`；`export type Stage = string;` 注释「a `stage_defs.code`; the set, order and labels come from `MeResponse.stage_defs` / `GET /api/stages`」；新增 `export type StageTier = 'core' | 'ext'`、`export interface StageDef { stage: Stage; scheme: string; rank: number; tier: StageTier; parent: Stage | null; name_zh: string; full_zh: string; difficulty_hint: 1 | 2 | 3 | 4 | 5 }`、`export interface StagePreset { code: string; name_zh: string; stages: Stage[]; current_stage: Stage }`；`StageInfo extends StageDef`（去掉 `index`、`name_zh` 并入基类）；`WordBrief.stage_min: Stage | null`；`Settings` 形状不变。`endpoints.ts:80-85 MeResponse` 加 `stage_defs: StageDef[]; stage_presets: StagePreset[]`（`schemas.py:245-249` 同步）。
   - `schemas.py`：`StageTier = Literal["core","ext"]`、`class StageDef(Model)`、`class StagePreset(Model)`、`class StageInfo(StageDef)`；`WordBrief.stage_min: Stage | None`。
   - `scripts/check_contract.py:158-170` 只把「全部成员是字符串/整数字面量」的 `export type` 收进 `unions`，`export type Stage = string` 自动不参与比对；`StageTier` 作为新字面量联合参与；`StageDef`/`StagePreset` 作为新接口与同名 pydantic 模型逐字段比对（`:260-272`）；`StageInfo extends StageDef` 由 `ts_props`（`:174`）展开继承。审计仍然通过且仍有约束力。
   - `API.md §9.1`（`:459-460`）改写为：「`stages`/`stage_min`/`current_stage` 都是阶段码；服务端原样存码；排序用 `StageDef.rank`；0011 之前的整数索引已不存在」。
4. 数据层兼容：`push_batches.settings_json` 的 4 条历史快照仍含 `"current_stage": 3`（`live-copy.db`），该列只写不读（`batches.py:314-318`，`grep settings_json` 仅此一处）——保留原样，0011 头注释说明；`localStorage` 偏好与路由参数本来就是码，无需迁移（[frontend-stages-10]）。
5. 若产品负责人坚持保留一个整数字段：可在 `WordBrief` 加派生只读字段 `stage_rank: number | null`（= `d.rank`），**不建议**——它会重新把顺序写进每个词的 DTO。

### 3.3 迁移 0011 草案（已排练）

文件：`backend/wd/migrations/0011_stages_as_data.sql`（编号规则 `db.py:41`，下一个编号为 0011，[stage-model-21]）。排练用的完整 SQL 在 `scratchpad/design-stages-as-data/0011_stages_as_data.sql`，与下文一致。

**运行器约束**（`0001_init.sql:25-38`、`db.py:195-249`）：文件内不得 `COMMIT`/`ROLLBACK`（`db.py:232-234`）、不写 `schema_migrations`（运行器在 `:239` 写 `(11, 'stages_as_data')`）、不切换 `PRAGMA foreign_keys`（`:227` 在 BEGIN 前关、`:246` 事后开、`:235-238` `foreign_key_check` 不空则整文件回滚）；运行器 `BEGIN IMMEDIATE`（`:229`），`pre_hook` 先写 `backups/pre-migrate-10-to-11.db.gz`（`backup.py:283-296`，`main.py:482`/`cli.py:100`）。

```sql
-- 1. 定义表（只由迁移写入）
CREATE TABLE stage_defs (
  code TEXT PRIMARY KEY, scheme TEXT NOT NULL DEFAULT 'cn', rank INTEGER NOT NULL,
  tier TEXT NOT NULL DEFAULT 'core' CHECK (tier IN ('core','ext')), parent TEXT REFERENCES stage_defs(code),
  name_zh TEXT NOT NULL, full_zh TEXT NOT NULL,
  difficulty_hint INTEGER NOT NULL CHECK (difficulty_hint BETWEEN 1 AND 5),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)), ecdict_tag TEXT UNIQUE, note TEXT,
  UNIQUE (scheme, rank)) WITHOUT ROWID;
INSERT INTO stage_defs(...) VALUES ('xs','cn',10,'core',NULL,'小学','小学（课标二级）',1,1,NULL,'…'), … 7 行（3.2.2 表）;
CREATE TABLE stage_presets (code TEXT PRIMARY KEY, name_zh TEXT NOT NULL, stages_json TEXT NOT NULL,
  current_stage TEXT NOT NULL REFERENCES stage_defs(code), sort_order INTEGER NOT NULL UNIQUE) WITHOUT ROWID;
INSERT INTO stage_presets VALUES ('xs','小学生','["xs"]','xs',10), ('zk','初中生','["xs","zk"]','zk',20),
  ('gk','高中生','["zk","gk"]','gk',30), ('uni','大学生','["gk","cet4","cet6"]','cet4',40), ('pro','职场人士','["cet4","cet6"]','cet4',50);

-- 2. 成员表 + 从旗标回填（新种子导入后 sources 被改写为真实表码）
CREATE TABLE word_stage_tags (word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  stage TEXT NOT NULL REFERENCES stage_defs(code), sources TEXT, PRIMARY KEY (word_id, stage)) WITHOUT ROWID;
CREATE INDEX ix_word_stage_tags_stage ON word_stage_tags(stage, word_id);
INSERT INTO word_stage_tags SELECT id, 'zk',   'legacy-flag' FROM words WHERE stage_zk = 1;   -- 同样 gk / cet4 / cet6

-- 3. words 重建：去掉 4 个旗标列，stage_min 变码；先 DROP VIEW（[A4]、[stage-model-13]）
DROP VIEW v_bank;
CREATE TABLE words_new ( … 0001_init.sql:166-204 的列，去掉 stage_zk/gk/cet4/cet6，
  stage_min TEXT REFERENCES stage_defs(code), … );
INSERT INTO words_new (…) SELECT …, CASE stage_min WHEN 1 THEN 'zk' WHEN 2 THEN 'gk' WHEN 3 THEN 'cet4' WHEN 4 THEN 'cet6' END, … FROM words;
DROP TABLE words; ALTER TABLE words_new RENAME TO words;
CREATE UNIQUE INDEX ux_words_lemma ON words(lemma); CREATE INDEX ix_words_frq …; ix_words_stage_min ON words(stage_min, frq);
ix_words_content …; ix_words_created_by … WHERE created_by_user_id IS NOT NULL; ix_words_public …;
CREATE VIEW v_bank AS … (0001_init.sql:572-576 原文，仍选 w.stage_min);

-- 4. user_settings 重建：current_stage 变码，K-12 默认；现有行 1:1 映射，不加 xs
CREATE TABLE user_settings_new ( … 0001_init.sql:139-160 的列，
  stages_json TEXT NOT NULL DEFAULT '["xs"]', current_stage TEXT NOT NULL DEFAULT 'xs' REFERENCES stage_defs(code), … );
INSERT INTO user_settings_new (…) SELECT …, stages_json, CASE current_stage WHEN 1 THEN 'zk' WHEN 2 THEN 'gk' WHEN 3 THEN 'cet4' WHEN 4 THEN 'cet6' END, … FROM user_settings;
DROP TABLE user_settings; ALTER TABLE user_settings_new RENAME TO user_settings;
CREATE INDEX ix_user_settings_next_push ON user_settings(next_push_at);
```

要点与依据：

- **顺序**：tag 表在 `words` 重建之前建并回填——它和 `word_forms` 等 9 张子表一样以文本引用 `words`，`DROP`/`RENAME` 期间外键关闭，结束时 `foreign_key_check` 验证（排练结果为空；[stage-model-12] 的变体 B 已证明 9 个子关系在此流程下保留）。
- **`DROP VIEW v_bank` 必须在重建前**，否则 `RENAME` 失败（`legacy_alter_table=OFF` 下实测，[stage-model-13]）；排练必须走 `.venv/bin/python` 的 `run_migrations`，不能用 `/usr/bin/sqlite3`（其 `legacy_alter_table=1` 会掩盖此问题，[verify stage-model-13]）。
- **`user_settings` 没有任何子表**（`pragma_foreign_key_list` 遍历 25 表，[stage-model-12] 变体 C），重建只影响自身。
- **外键到 `stage_defs`**：`word_stage_tags.stage`、`words.stage_min`、`user_settings.current_stage`、`stage_presets.current_stage`。排练中 `INSERT INTO word_stage_tags … 'bogus'` 被 `FOREIGN KEY constraint failed` 拒绝、`UPDATE user_settings SET current_stage='xs'` 被接受——这就是「未知阶段码不再静默丢弃」的数据库层保证（修复 [A6]/[seed-pipeline-11]）。
- **数据迁移规则**：`stage_min` 1–4 → `zk/gk/cet4/cet6`（排练：`cet6 3,694 / zk 2,099 / gk 1,792 / cet4 1,577`，与 `live-copy.db` 的整数分布逐一相同）；`stages_json` 已是码，原样；`current_stage` 同映射（排练：用户 1 → `cet4`，用户 2 → `zk`）；`push_batches.settings_json` 不动。
- **`seed_version`**：不改 `kv`。0011 后 tag 由旗标回填，与旧种子一致；新种子文件哈希不同，`wd import-seed` / 启动 `seed_check`（`main.py:307-319`）会自动导入并改写 tag 与 `sources`（3.10）。
- **`docs/SCHEMA.sql` 规则**：`test_db.py:362-366` 要求它与 `0001_init.sql` 字节相同（[stage-model-14]）——**不改**；在 0011 文件头与 `DESIGN.md §3.1`（`:184-186`）写明「当前 schema = 0001 + 0008 + 0009 + 0010 + 0011；`words` 的旗标列与整数 `stage_min` 自 0011 起不存在」。是否另立 `docs/SCHEMA_CURRENT.sql` 由 `sqlite_master` 导出并加测试，列为未决（7.2）。
- **排练结果**（第 5.4 节脚本，SQLite 3.54.1 / Python 3.12.16）：`applied=[(11,'stages_as_data')]` 0.049 s；17 张表行数不变；`integrity_check ok`；`foreign_key_check` 空；28 张表（25 + 3）、视图 `['v_bank']`；tag 18,321 = 2,099 + 3,829 + 4,722 + 7,671；`words` DDL 不再含 `stage_zk`；6 个 `words` 索引齐全；`v_bank` 18 行（= 线上 `new`+`learning` 的 17 + 1）；默认值 `'["xs"]'`、`'xs'`；二次运行 `applied=[]`；文件 5,644,288 → 10,178,560 B，空闲页 932——与 [verify stage-model 遗漏 4] 一致，上线步骤里加 `VACUUM`（第 6 节）。

### 3.4 维度：拓展层做成阶段行，「上海/全国」预留为 `scheme`

**拓展层（Q4-c）**：`zk_ext`/`gk_ext` 是普通阶段行（`tier='ext'`、`parent`），所以页签、chips、`stages_json`、`/api/screen/next?stage=`、预生成都天然支持，查询层没有第二个维度。规则：

- 一个词**不会**同时带 `zk` 和 `zk_ext`：构建器只在「有旧证据且不在 `zk` 核心」时打 `zk_ext`（3.10）。
- `stage_min` = 按 `rank` 最低的**核心**阶段；只有 ext 标签时取最低的 ext（排练数字见 3.9）。这样「仅本阶段新增」对核心阶段保持官方口径，254 个 ext-only 词仍有 `stage_min`（能被距离排序与「全部」页签覆盖，`prewarm all` 的 `stage_min IS NOT NULL` 也覆盖它们）。
- 默认 UI 只展示核心页签；`含拓展词` 开关（`include_ext=1`）把父阶段与其 ext 子阶段并集（3.7）；设置页可以把 ext 码加入目标阶段。

**上海/全国（Q3）——预留、不实施**：`stage_defs.scheme` 的语义定为「拥有该阶段的方案」。未来加上海方案只需：① `INSERT INTO stage_defs VALUES ('sh_zk','sh',20,'core',NULL,'初中（上海）',…), ('sh_gk','sh',30,…)`；② 从 `word_stage_tags.sources LIKE '% shmeea2020 %'` 生成 `sh_zk` 的 tag（或由构建器输出）；③ `ALTER TABLE user_settings ADD COLUMN scheme TEXT NOT NULL DEFAULT 'cn'`（纯 additive，0010 先例 `0010_ai_provider.sql:9`）；④ 服务端取用户可见阶段 = `scheme IN ('cn', :user_scheme)`，同一 `rank` 上用户方案的行**替换** `cn` 行（`UNIQUE(scheme, rank)` 保证一对一）。前端完全不改（数据驱动），`/api/stages`/`/api/auth/me` 只是返回另一组行。本文不做它的理由见第 2 节 A4。

**来源保留**：`word_stage_tags.sources` 存空格分隔的表码（`moe2022_l2 moe2022_l3 shmeea2020 moe2025_hs cet2016_4 cet2016_46 cet2016_6 mahavivo_zk mahavivo_hs ecdict_zk ecdict_gk ecdict_cet4 ecdict_cet6`），由构建器写入记录的 `stage_sources`，导入器落库；`words.sources`（`0001_init.sql:188`）继续记录词典来源。`data/seed/ATTRIBUTION.md` 与根 `ATTRIBUTION.md §2` 按表码逐条登记来源与许可姿态（A3/Q8-a：只用词头）。

### 3.5 查询与性能（≈18,321 对，新种子后 ≈19,659）

#### 3.5.1 实测（`scratchpad/design-stages-as-data/probe0011.py`，线上副本私有拷贝，热缓存、30 次中位数，SQLite 3.54.1，Mac）

| 查询 | 旧（旗标列） | 新（tag 表） | 新查询形状 / 计划 |
|---|---|---|---|
| Q1 词库页 `stage=cet4`，`sort=freq`，50 条 | 1.14 ms | **0.95 ms** | `JOIN word_stage_tags t ON t.word_id = w.id AND t.stage = :st`；计划 `SEARCH t USING COVERING INDEX ix_word_stage_tags_stage` → rowid 查 `words`。`EXISTS` 写法 2.19 ms，不采用 |
| Q1b 同筛选 `COUNT(*)` | 0.55 ms | 0.53 ms | 同上 |
| Q1c `stage=cet6&new_only=1` | 0.87 ms | 1.21 ms（`ANALYZE` 后 1.27，用 `ix_words_stage_min`） | `… AND w.stage_min = 'cet6'` |
| Q2 `/api/stages` 全部计数 | 3.32 ms（4 条查询） | **3.43 ms（1 条）** | `FROM word_stage_tags t CROSS JOIN words w ON w.id = t.word_id LEFT JOIN user_words … GROUP BY t.stage`——`CROSS JOIN` 固定驱动顺序，计划 `SCAN t USING COVERING INDEX`；普通 `JOIN` 让优化器从 `words` 驱动，7.36 ms。结果与旧 4 条查询逐值相同 |
| Q3 推荐词/筛词候选 `[zk,gk]`，主攻 gk，15 条 | 0.98 ms | **1.64 ms** | `w.id IN (SELECT word_id FROM word_stage_tags WHERE stage IN (…))` + 序数 CASE 距离；`EXISTS` 写法 3.39 ms，不采用。前 15 个 lemma 与旧查询**顺序完全相同** |
| Q4 字母索引 `stage=gk` | 1.49 ms | 2.05 ms | JOIN tags |
| Q5 一页 50 词的 tag 批量读取（123 行） | — | **0.05 ms** | `WHERE t.word_id IN (…) ORDER BY t.word_id, d.rank` |
| Q6 预生成候选 `gk` | 1.04 ms | 2.28 ms | `EXISTS`；可改 IN 子查询再降 |
| Q7 种子导入：删除并重插 18,321 条 tag | — | 29 ms | 一个事务内 `DELETE` + `executemany` |
| Q8 `sort=difficulty` | 0.83 ms | 1.13 ms | `LEFT JOIN stage_defs d ON d.code = w.stage_min … COALESCE(w.difficulty, d.difficulty_hint, 5)` |

结论：所有路径仍在 0.5–3.5 ms；增量最大的是候选选词（+0.7 ms）与字母索引（+0.6 ms），对每次请求无感。**不需要**新的复合索引：`PRIMARY KEY (word_id, stage)` 服务按词取 tag，`ix_word_stage_tags_stage(stage, word_id)` 服务按阶段扫描；`ix_words_stage_min(stage_min, frq)` 保留。规模上限：即便将来 10 万词 × 3 阶段 = 30 万行 tag，仍是 B 树索引范围扫描，不会改变数量级。

#### 3.5.2 每个消费点的新写法（对应 [stage-model-3/5]）

| 位置 | 现在 | 改后 |
|---|---|---|
| `routers/vocab.py:52-56` 阶段筛选 | `f"w.stage_{q.stage} = 1"`、`w.stage_min = :stage_idx` | `codes = stages.expand(conn, q.stage, q.include_ext)`；`_FROM` 改为 `JOIN word_stage_tags t ON t.word_id = w.id AND t.stage IN (:s0,…)`（`stage='all'` 时不 JOIN）；`new_only` → `w.stage_min IN (:s0,…)` |
| `routers/vocab.py:78` `COALESCE(w.difficulty, w.stage_min, 5)` | 两把尺子混用 | `_FROM` 恒加 `LEFT JOIN stage_defs d ON d.code = w.stage_min`，排序 `COALESCE(w.difficulty, d.difficulty_hint, 5), …`；`API.md:169` 同步 |
| `routers/vocab.py:86-106` `/api/stages`、`services/stats.py:177-196` | 4 次循环查询 | Q2 的单条 `GROUP BY`，按 `stage_defs` 顺序合并（没有 tag 的阶段补 0 行），返回 `StageInfo extends StageDef` 7 行；两处合并为 `stages.stage_infos(conn, user_id)` |
| `services/screen.py:34-36,51-56`、`services/batches.py:60-61,232-234,266-273,690-699` | `w.stage_{s} = 1` 拼接 + 整数距离 | `stages.member_sql(codes)`（IN 子查询）+ `stages.distance_sql(defs)`：`CASE w.stage_min WHEN 'xs' THEN 0 WHEN 'zk' THEN 1 … END` 作为序数，再套现有 `0 / 2·(s−cur)−1 / 2·(cur−s)` 公式（`DESIGN.md:347-350` 语义不变；排练证实前 15 条顺序相同） |
| `services/words.py:228-229 stages_of`、`:264-288 word_brief`、`:291+ word_briefs` | 读行上的旗标 | `word_briefs` 批量 `stages.tags_for(conn, ids)`（Q5）；`word_row()`（`:204`）附加 `row["stages"]`；`stages_of(row)` 返回 `row.get("stages") or []`。`content.py:88 prompt_entry` 因此继续只接收行 |
| `ai/prewarm.py:36-39` | 列名 | `"all"` → `w.stage_min IS NOT NULL`；其他 → `w.id IN (SELECT word_id FROM word_stage_tags WHERE stage = :stage)` |
| `services/bank.py:161-182 user_settings_row` | `s in words.STAGES` 过滤 | `stages.filter_known(conn, codes)`；为空 → 默认 + WARNING 事件 |
| `security.py:597 index_to_stage(int(...))` | 整数→码 | 直接 `row["current_stage"]` |
| `routers/onboarding.py:36`、`routers/settings.py:116 stage_to_index` | 码→整数 | 直接写码；写前 `stages.require_codes` |

### 3.6 `difficulty` 1–5 与阶段的关系（Q5）

- 尺子不改：`content_system.txt:11`、`consolidate_system.txt:11`、三个 JSON schema `enum [1..5]`、`ai/models.py` 四处 `Literal[1..5]`、`schemas.py:47 Difficulty`、`types.ts:73`、`0001_init.sql:195` CHECK 全部不动（[A5] 列出的 12 处零改动）。小学词与初中词共用 1——线上 49 行里 1 只有 2 个，区分度损失当前为零；若真实小学内容生成后需要区分，再评估 6 级。
- 解耦点是 `stage_defs.difficulty_hint`（xs 1 / zk 1 / zk_ext 1 / gk 2 / gk_ext 2 / cet4 3 / cet6 4），只用于 `sort=difficulty` 的兜底（`vocab.py:78`）；`difficulty` 的读者只有这一处排序与夜间整理的 `IS NULL` 条件（[D6]、[verify ai-prompts-stages-15]），不受影响。
- 提示词侧：`content.py:49 STAGE_ZH` → `stage_defs.name_zh`，于是带 `xs` 的词在 `prompt_entry` 里出现 `"stages": ["小学", "初中", …]`；`content.py:48 AUDIENCE` 与 `content_system.txt:1` 的受众文案是否加「小学」及是否提升 `PROMPT_VERSION`（`content.py:46`）交给 Q9 切片；`CLAUDE_INTEGRATION.md:232-235` 的示例需同步「小学」字样（文档层）。`STAGE_ZH[s]` 的 `KeyError` 风险（[D6]）随常量消失。

### 3.7 API 契约与前端

#### 3.7.1 契约（`API.md`、`schemas.py`、`types.ts` 同一提交）

- 端点 5 `GET /api/auth/me`（`routers/auth.py:154-162`、`schemas.py:245-249`、`endpoints.ts:80-85`）：响应增加 `stage_defs: StageDef[]`（已启用、按 `scheme, rank`）与 `stage_presets: StagePreset[]`。SPA 在 `AuthContext.loadMe`（`AuthContext.tsx:66-70`）一次拿到，`useStages()` 对外暴露 `defs, core, byCode, presets, isStage(code), nameOf(code), fullNameOf(code)`。
- 端点 19 `GET /api/stages`（`API.md:167`）：「one row per enabled stage of the user's scheme, ordered by rank（7 rows today）」，`StageInfo extends StageDef`。
- 端点 20/21 `GET /api/vocab`、`/api/vocab/letters`（`API.md:169-170`）：`stage=all|<code>`；新增 `include_ext=0|1`（只对有 ext 子阶段的核心码有效，`new_only` 同时按并集解释）。
- 端点 12/15（`API.md:155,160`）：「`stages` non-empty ⊆ enabled stage codes」。
- 端点 31（`API.md:187`）：`stage=<code>|auto`；端点 67（`API.md:230`）：`stage: <code>|'all'`。
- §9（`API.md:236-291`）：按 3.2.4 改写；§9.1 `:459-460` 两条改写。
- `ENDPOINT_MODELS`（`schemas.py:1409`）不变。

#### 3.7.2 前端改动

| 文件 | 改什么 |
|---|---|
| `api/types.ts:5-6,44-57` | 3.2.4 的类型；`stage_min: Stage \| null` |
| `api/endpoints.ts:80-85,131,135-144,196,328` | `MeResponse` 加两字段；`VocabStageFilter = Stage \| 'all'`、`ScreenStage`、`PrewarmStage` 保持派生；`VocabQuery` 加 `include_ext?: boolean` |
| `auth/AuthContext.tsx:19-24,66-70,142-149` | 状态加 `stageDefs`/`stagePresets`；新 hook `hooks/useStages.ts` |
| `components/word/StageChips.tsx` | 删 `:7-9` 三张表与 `:11-13 isStage`（移到 `useStages`）；按 `defs` 顺序渲染 `stages` 中的码，标签 `nameOf`，高亮 `stage === stageMin`（`:31`）；ext 码默认只在词没有核心码时显示（避免 5 个 chip 外再加拓展 chip）；`'cet6' && cet6Star` 星标保留（`:33-37`） |
| `pages/VocabPage.tsx:29,202,213,232` | `TABS = ['all', ...core.map(d => d.stage)]`；`newOnlyLabel` 用 `zh.stages.newOnlyBelow(nameOf(tab), nameOf(lower))`，最低核心阶段不显示开关（顺手修掉 [frontend-stages-19] 的空操作）；在有 ext 子阶段的页签显示 `含拓展词` 开关 → `include_ext` |
| `pages/WelcomePage.tsx:30-42,236-262` | 删 `Role`/`ROLE_PRESETS`/`ROLES`/`STAGE_FULL`；角色 chips 来自 `presets`，阶段 chips 来自 `core`（文案 `full_zh`），`toggleStage(stages, current, stage, order)` 多一个顺序参数 |
| `pages/SettingsPage.tsx:72-77,303-318` | chips 遍历 `defs`（含 ext，标签 `name_zh`）；`toggleStageSetting` 同上 |
| `pages/ScreenPage.tsx:20,29-57` | 删 `FULL_NAME`；`items = data.items`（服务端顺序），显示 `tier === 'core' \|\| settings.stages.includes(stage)` 的行；`:41-43` 骨架数量 = `core.length` |
| `pages/ScreenRunPage.tsx:33-35` | `isStage` 来自 `useStages`，标题 `nameOf(stage)` |
| `pages/AdminPage.tsx:36,739,842-847` | `PREWARM_STAGES = [...defs.map(d => d.stage), 'all']`，标签 `nameOf` |
| `i18n/zh.ts:25,28-29,86` 与 `docs/FRONTEND.md:231-235,292` | 删 `welcome.roles`、`stages.zk…cet6Full`、`newOnlyCet6`；加 `stages.includeExt: '含拓展词'`、`stages.newOnlyBelow: (s, b) => \`仅${s}新增（不含${b}）\``；`settings.sources.lists` 改为「词表范围：国家课标小学二级、初中三级与上海市初中词汇表、高中课标词汇表、大学英语四级与六级大纲」；两处逐行镜像（`zh.test.ts:67-83`、`zh.contract.test.ts:61-83`） |
| `components/ui/ui.css:453-473` | 6 个 `fill` 页签在 375 px 溢出 13 px（[frontend-stages-16]）：加 `@media (max-width: 479.98px) { .tabs--fill .tab { padding-inline: var(--space-2); } }` → 6×48+20 = 308 ≤ 343 |
| `docs/DESIGN.md:72` 术语表 | 「Stages」行改为「阶段码与中文名以 `stage_defs`（0011 写入）为准：小学/初中/高中/四级/六级 + 初中拓展/高中拓展」 |

`StageChips` 的 375 px 风险：5 个核心 chip（sm 每个 42 px）= 226 px，与「学习中 · 3 天后」徽章同行时折行（[frontend-stages-15]，`word.css:77-103` 的 `flex-wrap` 保证只折不溢）；ext chip 默认隐藏把上限锁在 5。

**部署顺序**：契约变更要求前后端同一提交；Mac 上 SPA 由同一进程服务（快照在停机后切换），不存在「前端先上」的窗口；若先后分开上，仍应后端先上——旧 SPA 对新后端只失去页签（`ScreenPage.tsx:31` 过滤未知码），新 SPA 对旧后端会在 `/api/auth/me` 缺 `stage_defs` 时无页签可渲染。

### 3.8 新用户默认（Q6）

- DDL：`stages_json DEFAULT '["xs"]'`、`current_stage DEFAULT 'xs'`（0011 重建时写入；现 `0001_init.sql:147-148`）。
- 注册流程不变：`security.py:661-664` 的 `INSERT INTO user_settings(user_id, next_push_at, updated_at)` 继续吃 DDL 默认。
- `bank.py:85-86` 的复制值改为 `DEFAULT_STAGES = ("xs",)`、`DEFAULT_CURRENT_STAGE = "xs"`，新增单元测试把它们与 `pragma_table_info('user_settings').dflt_value` 比对，杜绝双源漂移。
- 欢迎页：未点角色时预勾小学（来自 `settings`），角色 chips 由 `stage_presets` 提供「小学生」。
- 线上 2 个用户的迁移规则写死在 0011 的 `INSERT … SELECT`（3.3）：码 1:1，不自动加 `xs`。影响：用户 2（`["zk"]`）的候选池 2,099 → 1,983（第 3.9 节），其 1 个生词仍在自己的阶段内；用户 1 候选池 9,162 → 8,908（254 个 ext-only 词不在其目标阶段，可在设置里勾 `初中拓展`/`高中拓展` 取回）。

### 3.9 老词去哪里（Q4）与「种子里不再出现的词」

按 A2/A3 用本机已有的官方词头清单重算（`verify-provinces/out/{L2,L3,H2020,S}.txt`、`lists-senior/out/h2025.entries.tsv`；脚本 `fate.py`，数字以词表任务最终清单为准，口径误差 ±1%）：

| 项 | 数字 |
|---|---|
| 核心集合（在库） | `xs` 500 · `zk` 1,983（上海 1,694 ∪ 三级 1,592，交 1,303）· `gk` 3,077（2020 版对应 2,981）· `cet4` 4,722 · `cet6` 7,671 |
| 旧 `zk` 2,099 | 留核心 1,588；转 `zk_ext` **511**（其中 191 在 `gk` 核心、424 在四六级、**80 不属任何核心阶段**） |
| 旧 `gk` 3,829 | 留核心 2,634；转 `gk_ext` **1,195**（955 在四六级、100 在 `zk` 核心、**222 不属任何核心阶段**） |
| 官方表新进核心 | `zk` +395（原 `stage_min` 高中 303 / 四级 68 / 六级 24）；`gk` +443（四级 346 / 六级 81 / 初中 16） |
| 无核心阶段的词 | **254**（全部有 ext 标签，0 个孤儿）；`frq` 中位 ≈7,400，多为复合词/地名/口语（`bookshop, crayon, dustbin, granny, armchair, bathtub, bingo…`） |
| 新 `stage_min` 分布 | xs 500 · zk 1,483 · gk 1,228 · cet4 1,827 · cet6 3,870 · zk_ext 80 · gk_ext 174 |
| 新 tag 总数 / 每词标签数 | 19,659（1 个 3,873 · 2 个 1,709 · 3 个 1,996 · 4 个 1,540 · 5 个 44） |
| 官方词头不在库 | 二级：仅 `excited`（`mr/mrs/ms/pe` 以带点形式在库，[verify provinces-24]）；三级 ≈5（`ai, teenage, tofu, yogurt…`）；上海 14（[verify shanghai-secondary-19]）；高中 2025 ≈20（`drone, empathy, lifestyle, wetland, pagoda, wi-fi, kung fu, mobile phone, per cent…`） |

决定与理由：

1. **降级 + 拓展层，不剔除。** 核心层按官方表（A3），旧证据进 `zk_ext`/`gk_ext`：254 个词不会从任何视图消失，用户生词库里的引用（`user_words.word_id`）不受任何影响；提供「含拓展词」即可重新看到。剔除会与「种子从不删词」的导入语义冲突（`seed.py:1-20` docstring、`WORD_LIBRARY_CURATION.md §1.2`），留在库里却无阶段则只在「全部」可见且永不被推荐——最差的一种。
2. **种子是超集。** 构建器输出今天全部 9,162 词 + 官方表缺席的 ≈40 个新词头（归一化后，见上表），因此「不再出现在种子里的线上词」在本设计下**不存在**；若将来真要剔除，需要另加 `retired.jsonl` 机制（`WORD_LIBRARY_CURATION.md §2.4 阶段 C`「种子回流」），不在本文范围。
3. **`sources` 记录证据**：`zk_ext` 的 tag `sources` 为 `mahavivo_zk` / `ecdict_zk`，`zk` 的为 `shmeea2020 moe2022_l3`——这正是日后 `sh_zk` 方案或「纯国家口径」切换需要的全部信息。
4. 验收数字（`TASKS.md:172-178`、`test_seed.py:338-353`、`README.md:9,103`、`DESIGN.md:209`、`API.md:169` 的 3,694）全部按新 `stats.json` 重写；上表给出预期值。

### 3.10 种子流水线

**记录格式**（`DESIGN.md §3.2`）：`stages` 仍是字符串数组（现有格式已是码，顺序不再有意义）；新增可选 `stage_sources: {"zk": ["shmeea2020","moe2022_l3"], "zk_ext": [...]}`；`sources` 与 `cet6_star` 保留。老记录（无 `stage_sources`）照常导入，tag 的 `sources` 为 NULL。

**构建器 `scripts/build_seed.py`**：
- `:81-88 syllabus` 改为读 `data/lists/MANIFEST.json`（由词表任务产出：`[{code, stage, file, issuer, year, title, url, license_posture, sha256}]`），每个文件一列词头（plain）；`:15-17` 的 `RICH_RE` 只对 mahavivo 旧 rich 文件保留（并修 [A6] 的全角括号/单字母缺陷，INDEX 6.2-1）。
- 步骤 1（`:105-109`）ECDICT 标签行仍全部收录，但 `make_record(:191)` 的 `stages` 改为按 `stage_defs.ecdict_tag` 映射（`zk→zk_ext, gk→gk_ext, cet4→cet4, cet6→cet6`，映射表由脚本从 0011 文件或 `--db` 读取，避免第 11 份常量）；步骤 2（`:112-127`）按 MANIFEST 给核心码并记 `stage_sources`；新规则「有 `zk` 核心则去掉 `zk_ext`」在 `:143-147` 的收尾处执行；`:150-151 order` 由 MANIFEST 的阶段顺序推出。
- 官方表词头不在 ECDICT（`:119-121` 现在直接丢弃）→ 输出最小记录 `{"word", "stages", "stage_sources", "sources": [list]}`，并照旧写进 `stats.json.missing_from_ecdict` 供补释义。
- `stats.json`：`per_stage`/`first_stage` 键变为 7 个码；新增 `tags_total`；`pack_seed.sh:44-57` 只读 `total_words`，不受影响（[seed-pipeline-20]）。
- `:201-219 ATTRIBUTION` 常量按表码逐条写来源、年份、许可姿态；根 `ATTRIBUTION.md §2` 同步。

**导入器 `backend/wd/seed.py`**：
- `import_seed` 开始时 `defs = stages.defs(conn)`；`seed_row(rec, now, defs)`：未知码 → `raise ValueError(f"unknown stage code {code!r} in seed record {word!r}; run `wd migrate` first")`，整次导入回滚（`db.maybe_tx`）；`cmd_import_seed`（`:333-353`）打印并 exit 1；`main.seed_check`（`:307-319`）捕获 `ValueError`，记 `system_events('seed_import_failed')` 并继续以旧种子启动（现在它对坏种子不设防，[WORD_LIBRARY_CURATION §1.2]）。
- `SEED_COLUMNS` 去掉 4 个旗标，保留 `stage_min`（码，按 3.4 规则计算）；UPSERT 的「有差异才写」语义不变。
- 新增 `_rebuild_tags(conn, rows, stats)`：对本次导入的 lemma `DELETE FROM word_stage_tags WHERE word_id IN (…)` 后 `executemany INSERT (word_id, stage, sources)`（Q7 实测 29 ms），`stats.tags` 计数；与 `_rebuild_forms`（`:218-245`）同模式。
- `wd check db` 增加不变量：`stage_min` 与 tag 一致（`SELECT COUNT(*) FROM words w WHERE stage_min IS NOT (<按 rank 的最低核心/ext 子查询>)` = 0）、`user_settings.stages_json` 的每个码存在于 `stage_defs`。

**ECDICT 运行时路径**（`services/words.py:663-696 _resolve_ecdict`、`services/ecdict.py:173-181 word_columns`）：`word_columns()` 不再含旗标，返回的 `stage_min` 由 `stages.min_stage(defs, tags)` 计算，`tags` = `[d.code for d in defs if d.ecdict_tag in entry.tags]`；`_insert_word` 后调用 `stages.replace_tags(conn, word_id, tags, sources={code: ["ecdict_" + tag]})`。由构造可知：一个不在种子里的词不可能在任何官方表里（种子是官方词头的超集），因此 ECDICT 的 `zk`/`gk` 标签在运行时映射到 `zk_ext`/`gk_ext` 与种子一致。

---

## 4 改动清单（文件 → 改什么）

### 4.1 数据库与种子

| 文件 | 改什么 |
|---|---|
| `backend/wd/migrations/0011_stages_as_data.sql`（新） | 3.3 全文；头注释写明运行器规则、`DROP VIEW` 原因、数据映射、`SCHEMA.sql` 为 0001 基线、`push_batches.settings_json` 旧快照不动、上线后 `VACUUM` |
| `docs/SCHEMA.sql` | **不改**（`test_db.py:362-366`） |
| `backend/wd/seed.py` | 删 `:43 STAGES`；`:47-68 SEED_COLUMNS` 去旗标；`seed_row(rec, now, defs)`（`:167-214`）校验码、计算 `stage_min`、收集 `_tags`/`_tag_sources`；新增 `_rebuild_tags`；`import_seed`（`:248-316`）加载 defs、调用重建、`SeedStats.tags`；docstring `:1-20` 改写 |
| `backend/wd/main.py:307-319 seed_check` | 捕获 `ValueError` → 日志 + `system_events('seed_import_failed')`，不中断启动 |
| `scripts/build_seed.py` | 3.10；`data/lists/MANIFEST.json` 驱动；ext 规则；最小记录；`stats.json`/`ATTRIBUTION` |
| `data/seed/vocab.jsonl.gz`、`stats.json`、`ATTRIBUTION.md`、根 `ATTRIBUTION.md:19-32`、`README.md:3,5,9,103` | 重建后的产物与说明（在 Linux 上 `pack_seed.sh`，或接受 Mac gzip 哈希不同，[seed-pipeline-7]） |

### 4.2 后端

| 文件 | 改什么 |
|---|---|
| `backend/wd/services/stages.py`（新） | `defs/by_code/codes/require_codes/filter_known/ordinal/distance_sql/member_sql/expand/tags_for/min_stage/replace_tags/presets/stage_infos`；不缓存（7 行表，每次 ≈0.02 ms） |
| `backend/wd/schemas.py` | `:25` `Stage = str`；删 `:26`、`:51-52`、`:56-67`；新增 `StageTier`、`StageDef`、`StagePreset`；`:448-457 StageInfo(StageDef)`（删 `index`）；`:472 stage_min: Stage \| None`；`:488`、`:708`、`:1335` 改 `str` + pattern；`:245-249 MeResponse` 加两字段；`:9-10` docstring；`:485-501 VocabQuery` 加 `include_ext: Literal[0,1] = 0` |
| `backend/wd/routers/vocab.py` | `:17` 导入；`:48-72 vocab_filters` 用 `stages.expand/member`；`:75-80 _ORDER/_FROM` 加 `LEFT JOIN stage_defs d`；`:83-107 stages()` → `stages.stage_infos`；`:112,124` `int_fields` 加 `include_ext` |
| `backend/wd/services/stats.py:17,173-196` | 复用 `stages.stage_infos` |
| `backend/wd/services/screen.py:25,34-56` | 删 `_STAGE_DISTANCE`；`_stage_scope` 返回 `(codes, cur_ordinal)`，`:44` 去 `int()`，`:46-47` 用 `require_codes`；`_candidate_sql` 用 `member_sql` |
| `backend/wd/services/batches.py:60-61,232-234,266-273,690-699` | 同上；`:314` 快照原样记录码 |
| `backend/wd/services/bank.py:85-86,161-182` | 默认对；`filter_known` + 回落 WARNING |
| `backend/wd/services/words.py:39,204-213,228-229,264-310,564-597,663-696` | 删 `STAGES`；`word_row` 附加 `stages`；`word_briefs` 批量附加；`_word_defaults`/`_INSERT_WORD_SQL` 去旗标；`_resolve_ecdict` 写 tag |
| `backend/wd/services/ecdict.py:28,117-123,159-181` | `STAGE_TAGS` → defs 注入；`word_columns()` 去旗标 |
| `backend/wd/security.py:51,587-614,661-664` | `:597` 直接取码；`:613` docstring 默认值文字；注册 INSERT 不变 |
| `backend/wd/routers/onboarding.py:20,31-44` | 写码前 `require_codes`；去 `stage_to_index` |
| `backend/wd/routers/settings.py:27,89-92,113-116` | 同上 |
| `backend/wd/routers/auth.py:154-162` | `me()` 加 `stage_defs`、`stage_presets` |
| `backend/wd/routers/admin_ops.py:370-381` | prewarm 前 `require_codes(allow=("all",))` |
| `backend/wd/ai/prewarm.py:32-60` | 删常量；`_stage_sql` 用 `member_sql` |
| `backend/wd/ai/content.py:48-49,82-92` | 删 `STAGE_ZH`；`prompt_entry` 用 `row["stages"]` × `name_zh`；`AUDIENCE` 文案交 Q9 |
| `backend/wd/ai/prompts/content_system.txt:1`、`docs/CLAUDE_INTEGRATION.md:211,232-235` | 受众括号加「小学」（随 Q9 决定是否 bump `PROMPT_VERSION`） |
| `backend/wd/diag.py`（`wd check db`） | 3.10 的两条不变量 |
| `scripts/eval_provider.py:107,326-348` | `STAGES` 从 DB 读 |
| `scripts/smoke.py:352,614` | 期望改为读 `/api/stages` 行数 = `stage_defs` 已启用行数（7）；按 `rank` 排序 |

### 4.3 前端与文档

见 3.7.2 表；另：`docs/API.md`（§9、§9.1、端点 5/12/15/19/20/21/31/67、`:3` 规则句不变）、`docs/FRONTEND.md`（`:50` 角色、`:54-56` 页签、`:89` StageChips、§8 块）、`docs/DESIGN.md`（`:32,40` 「four stage tabs」→ 数据驱动；`:72` 术语；`:184-186,202,209,321-322,330,344-350`）、`docs/DEPLOY.md`（§5 迁移说明加 0011 的 `VACUUM`；§10 升级段加「0011 不可只回代码」）、`docs/TASKS.md:172-178` 验收脚本、`docs/qa-frontend.md:36,42,70` 人工用例、`docs/ops.md`（Mac 版步骤见第 6 节，可写入 `docs/QUICK_DEPLOY_AND_MOBILE.md` 的 Mac 段）。

---

## 5 测试与验收

### 5.1 会变红的现有测试（必须同步）

后端（pytest）：
- `tests/unit/test_api_schemas.py:11,32-39`（导入 `stage_to_index/index_to_stage` 与 `STAGE_NAMES_ZH` 等式）→ 改为「`StageInfo` 继承 `StageDef`、`Stage` 请求校验走路由」的断言。
- `tests/unit/test_db.py:13-17,51`（25 表 → 28，加 `stage_defs`, `stage_presets`, `word_stage_tags`）；`:52` 视图断言保留。
- `tests/unit/test_seed.py:90-99`（旗标列）、`:190-206`（`stage_zk`）、`:338-353`（验收数字、列名）。
- `tests/integration/test_vocab.py:69-70`（index/name 列表）、`:72-73`（`stage_{stage}`、`stage_min = index`）、`:107-114`（`stage_cet6 = 1`、`stage_min == 4` → `'cet6'`）。
- `tests/integration/test_screen.py:126,134`（`stage_cet4 = 1` SQL）。
- `tests/integration/test_settings.py:57-58`（默认 `cet4/cet6` → `["xs"]/xs`）、`:88-89`（`row[0] == 2` → `'gk'`）。
- `tests/integration/test_onboarding.py:98,120,139`（`current_stage == 3/1`、默认 `'["cet4","cet6"]'`）。
- `tests/unit/test_security.py:315`、`tests/integration/test_auth.py:82`（默认值）。
- `tests/integration/test_history.py:112`（4 个阶段集合 → 7）。
- `tests/integration/test_admin_ops.py:435`（`stage_cet4 = 1`）；`:463`、`:477` 语义不变。
- `tests/unit/test_words_resolve.py:478`、`tests/integration/test_reports.py:86-87`（`stage_min == 2` → `'gk'`）。
- `tests/unit/test_content_apply.py:255`（若夹具 `go` 加 `xs`，标签多「小学」）、`:257`（`stage_zk` 键 → `"stages": ["zk"]`）；`tests/unit/test_runner.py:27` 夹具不变。
- `tests/fixtures/mini_seed.jsonl`（60 条）：给 `a, apple, go, be…` 加 `xs`，加 1 条 `zk_ext`、1 条 `gk_ext` 样例；连锁：`test_screen.py:129-134`（`["be","a","go"]` 的 `stage=zk` 顺序）、`test_batches.py:127`（`screens == ["absolutely","axis"]`）、`test_seed.py:97`（`a` 的 `stage_min`）需按新夹具重算。
- `scripts/check_contract.py`：两侧同步后应 `contract OK`；中途任何一侧先改即硬失败（`:274-281`）。
- `scripts/smoke.py:352,614`。

前端（vitest / tsc）：
- `npm run typecheck`：`Record<Stage,…>` 五处（`StageChips.tsx:8-9`、`WelcomePage.tsx:42`、`ScreenPage.tsx:20`、`zh.test.ts:56`）随删除消失；`zh.stages[s]` 索引全部改 `nameOf`。
- `i18n/zh.test.ts:55-65`（`Record<Stage,string> = zh.stages` 删除）、`:67-83` 与 `zh.contract.test.ts:61-83`（§8 镜像）。
- 12 处 `stage_min: <数字>` 夹具（`grep -rn 'stage_min: [0-9]' frontend/src --include='*.test.*'` = 12，10 个文件）→ 码。
- `AuthContext.test.tsx:18-19` 等 mock 的 `MeResponse` 加 `stage_defs/stage_presets`；`SettingsPage.test.tsx:216-222`（`toggleStageSetting` 多一个顺序参数）、`WelcomePage.test.tsx:63-64`（`ROLE_PRESETS` 导入）、`SpeakButton.test.tsx:91-102`（chips 顺序/标签现在来自 defs mock）、`ScreenRunPage.test.tsx:51`、`endpoints.test.ts:24,46,51`、`client.test.ts:54-56,147`、`BankPage.test.tsx`、`WordRow.test.tsx`、`StudyCard.test.tsx`、`WordDetailPage.test.tsx`、`StudyPage.test.tsx`、`AddWordPreviewRow.test.tsx`、`queue.test.ts`。

### 5.2 要加的测试

- `test_db.py`：`test_upgrade_0011_converts_stage_integers_to_codes`（仿 `:283-310`：0001 基线 → 插入带旗标的词、`current_stage=3` 的用户 → `run_migrations` → 断言 tag 行、`stage_min` 码、`current_stage='cet4'`、DDL 默认、`stage_defs` 7 行、`stage_presets` 5 行、`v_bank` 可查、行数不变、外键拒绝 `'bogus'`、二次运行空）；`test_stage_defs_seeded`（码/rank/tier/parent/name_zh/difficulty_hint/ecdict_tag 逐行钉死——它取代 `test_api_schemas.py:39` 成为中文阶段名的「绑定」处）。
- `test_stages.py`（新）：`min_stage` 规则（核心优先、ext 兜底、空 → None）；`distance_sql` 序数与 `DESIGN §6.3` 公式一致；`require_codes` 对禁用/未知码 400；`filter_known` 回落 + 事件；`DEFAULT_STAGES`/`DEFAULT_CURRENT_STAGE` 等于 DDL 默认；`expand('zk', include_ext=1) == ['zk','zk_ext']`。
- `test_seed.py`：未知码整次回滚且 `kv.seed_version` 不变；`stage_sources` 落库；重导只改 tag 不动 `updated_at`；`stage_min` 对 ext-only 记录取 ext。
- `test_vocab.py`：`/api/stages` 7 行按 `rank`，`total/new_only_total` 与 tag 表 SQL 相等；`include_ext=1` 的总数 = 并集；`stage=zk_ext` 合法、`stage=xx` 400。
- `test_screen.py`/`test_batches.py`：主攻 `gk` 时 `gk_ext` 词排在 `cet4` 之前、`zk` 之后（序数公式）。
- `test_words_resolve.py`：ECDICT `zk` 标签词进 `zk_ext` 并带 `sources='ecdict_zk'`。
- `test_auth.py`：`/api/auth/me` 含 `stage_defs`（7）与 `stage_presets`（5）。
- 前端：`ScreenPage.test.tsx`（新）渲染服务端顺序与 ext 可见规则；`VocabPage.test.tsx` 断言页签数 = core + 1、最低阶段无「仅新增」开关、`含拓展词` 发送 `include_ext=1`；`StageChips.test.tsx` 按码高亮；`useStages.test.ts`。

### 5.3 验收（新 `TASKS.md:172-178` 脚本的预期值）

以 3.9 表为准：`words` 总数 = 9,162 + 新官方词头；`SELECT stage, COUNT(*) FROM word_stage_tags GROUP BY 1` ≈ xs 500 / zk 1,983 / zk_ext 511 / gk 3,077 / gk_ext 1,195 / cet4 4,722 / cet6 7,671；`stage_min` ≈ xs 500 / zk 1,483 / gk 1,228 / cet4 1,827 / cet6 3,870 / zk_ext 80 / gk_ext 174；`SELECT COUNT(*) FROM words WHERE stage_min IS NULL` = 0；词形行 14,000–14,300 不变；`cet6_star` 1,714 不变。最终数字由词表任务的清单决定，脚本随 `stats.json` 生成。

### 5.4 在 `live-copy.db` 的私有拷贝上排练

已做（本文数字来源），可重复：

```
S=/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad
cp $S/live-copy.db $S/design-stages-as-data/base.db           # 只读副本 → 私有拷贝（-wal 为空）
cd $S/design-stages-as-data
/Users/sqin/word-dance/.venv/bin/python probe0011.py "$PWD"   # 复制 base.db → new.db/old.db，拷贝仓库 migrations + 0011 草案，
                                                              # 跑真实 wd.db.run_migrations，校验行数/FK/integrity/tag/默认值/外键拒绝，
                                                              # 再对 old.db(旗标) 与 new.db(tag) 跑 3.5.1 的 8 组基准
/opt/homebrew/bin/python3.12 -I fate.py "$S" "$PWD/base.db"  # 官方清单 × 库：3.9 的全部数字
```

规则：排练一律走 `.venv/bin/python`（`legacy_alter_table=0`），绝不用 `/usr/bin/sqlite3` 执行迁移 SQL；绝不触碰 `live-copy.db` 本身与 `/Users/sqin/word-dance-data`。进入实现后，把同一流程做成 `backend/tests/unit/test_db.py` 的 0011 升级测试（夹具库）和一条 `make`/脚本（对线上库最近的 `wd backup` 产物解压后跑 `wd migrate --dry-run` + 真跑）。

---

## 6 上线与回滚（Mac，launchd；见 memory「macOS local install layout」，本机没有 `install.sh`/`systemctl`）

前提：新代码（含前端快照）与新种子在同一提交；`make test`（Mac 上允许 `test_deploy_files.py`、`test_config.py::test_defaults_without_environment` 的已知失败）与 `scripts/check_contract.py` 通过；本节在 03:30 自动备份之后、用户不活跃的时段执行。`D=/Users/sqin/word-dance-data`，`export WD_DATA_DIR=$D`。

1. **停服务**：`launchctl bootout gui/$(id -u)/com.word-dance.server`；确认 `curl --noproxy '*' http://127.0.0.1:8000/api/health` 失败、`kv.worker_lease` 过期（`wd restore` 同款检查）。
2. **手动快照**（在运行器的自动 `pre-migrate-10-to-11.db.gz` 之外再留一份）：`.venv/bin/wd backup --keep-daily 14 --keep-weekly 8`，记下文件名。
3. **迁移**：`.venv/bin/wd migrate --dry-run`（应只列 `0011_stages_as_data`）→ `.venv/bin/wd migrate`；检查日志 `applied migration 0011_stages_as_data`，`ls $D/backups/pre-migrate-10-to-11.db.gz`。
4. **导种子**：`.venv/bin/wd import-seed`（输出应含 `… inserted, … updated; … tags`）；若报 `unknown stage code`，说明代码与种子不配套——回到第 8 步回滚。
5. **只读校验**（`sqlite3 -readonly $D/word-dance.db`）：`SELECT * FROM schema_migrations` 末行为 11；`SELECT stage, COUNT(*) FROM word_stage_tags GROUP BY 1`；`SELECT stage_min, COUNT(*) FROM words GROUP BY 1`；`SELECT user_id, stages_json, current_stage FROM user_settings`（应为 `1|[…四个]|cet4`、`2|["zk"]|zk`）；`PRAGMA foreign_key_check`（空）；`.venv/bin/wd check db`。
6. **收缩文件**（可选但建议）：停机状态下 `sqlite3 $D/word-dance.db 'PRAGMA wal_checkpoint(TRUNCATE); VACUUM;'`（重建后约 900 个空闲页；`VACUUM` 不能在迁移事务内做，[verify stage-model 遗漏 4]）。
7. **前端快照 + 启动**：按 memory 配方构建到 `$D/frontend-releases/<sha>.new`，`mv` 为 `<sha>`，用 `python3 -c "os.rename"` 原子替换 `frontend` 符号链接；`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist`（或 `kickstart -k`）；`wd serve` 启动时不会再有待应用迁移，`seed_check` 因哈希一致不再导入。
8. **验证**：`curl --noproxy '*' http://127.0.0.1:8000/api/health`；浏览器登录 sqin → 词库 6 个页签、`/api/stages` 7 行、设置页 7 个 chips 与主攻 `四级`、筛词页、管理页预生成下拉含 `小学`；以 kimi 登录确认目标阶段仍只有 `初中`、生词库原样；`~/Library/Logs/word-dance/word-dance.log` 无 `stage_fallback`/错误。
9. **回滚**（唯一路径是快照，[verify stage-model 遗漏 2]——旧代码对 `current_stage='cet4'` 会在 `security.py:597` 的 `int()` 抛异常 → 500）：`launchctl bootout …` → `.venv/bin/wd restore $D/backups/pre-migrate-10-to-11.db.gz --yes` → `git checkout 75df534` → 把 `frontend` 链接指回 `frontend-releases/75df534` → `launchctl bootstrap …` → `health`。迁移之后产生的学习记录随快照丢失，所以第 1 步要选用户不活跃时段并当场完成第 8 步验证。

---

## 7 风险、未决问题、工作量

### 7.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 词表任务的官方清单晚于代码就绪 | 0011 可以先上（tag 由旗标回填），但 `小学` 页签为 0 词、`xs` 预设选不到词 | 迁移与新种子同一次停机上线；若必须分开，`stage_defs.xs.enabled=0` 临时隐藏（数据改动，无需发版） |
| 契约一次性破坏，前后端错配 | 旧 SPA 无页签 / 新 SPA 无 defs | 同一提交；Mac 单进程部署无窗口；`check_contract` 门禁 |
| 没有「只回代码」的回滚 | 需快照恢复，丢失迁移后学习记录 | 低活跃时段、立即验证、两份快照（第 6 节） |
| `check_contract.py` 不再比对 `Stage` 的取值集合 | 码集合的保护从编译期移到运行期 | `test_stage_defs_seeded` 钉死 7 行；请求层 `require_codes`；DB 外键 |
| 库文件膨胀 5.6 → 10.2 MB | 无功能影响 | 上线步骤 6 `VACUUM` |
| 优化器计划漂移（`new_only` 曾选 `ix_words_public`） | 1–2 ms 级别 | 迁移后 `ANALYZE` 一次（可放在上线步骤 6） |
| 拓展层的 UX 未经验证（254 个 ext-only 词、`含拓展词` 开关） | 用户可能找不到旧词 | 默认隐藏但一键可见；设置页可长期勾选 |
| 提示词出现「小学」标签改变 AI 输出 | 例句风格变化 | 与 Q9 切片协调 `AUDIENCE`/`PROMPT_VERSION` |
| `kind=proper_noun`、`Mr/Mrs/Ms/PE` 等词头归一化（[A6]、[seed-pipeline-12]） | 重复词条或错误释义 | 词表任务的 MANIFEST 归一化规则；导入前在副本上 `wd import-seed --file` 排练 |
| Linux 生产机的 SQLite 版本未知（[verify stage-model 未解决 4]） | `RENAME` 行为依赖 ≥3.26 | 排练时用 `.venv` 的 3.54.1；Lighthouse 部署前在目标机跑同一探针 |

### 7.2 未决问题（需产品负责人或其他切片回答）

1. 页签是否对所有用户显示全部 5 个核心阶段（现状：4 个对所有人），还是只显示用户目标阶段 + 全部？本文保留「全部核心」。
2. 拓展层默认可见性与文案（「初中拓展」/「超纲」）；是否在欢迎页提供。
3. `cet4`/`cet6` 是否也改为「只用 2016 大纲词头」（去掉 ECDICT-only 的 633 词或降为 `cet4_ext`）——机制已备，未决。
4. `docs/SCHEMA.sql` 的定位：维持 0001 基线并在 DESIGN §3 注明差异，还是新增由 `sqlite_master` 导出的当前 schema 文件加测试。
5. 上海方案（`sh_zk`/`sh_gk`）何时启用——取决于上海高中 200 词与手册词表的获取（[B7]、INDEX 未解决 2）。
6. `AUDIENCE`/`PROMPT_VERSION`（Q9）。
7. 新官方词头（≈40 个不在 ECDICT 的词）的释义来源：最小记录留空排在词频末尾，还是由词表任务补中文释义。

### 7.3 工作量（人日，不含官方词表获取/清洗）

| 块 | 内容 | 人日 |
|---|---|---|
| 迁移 | 0011 定稿、`test_db` 升级测试、副本排练、`VACUUM`/`ANALYZE` 步骤 | 1.0 |
| 后端 | `services/stages.py`、schemas/DTO、vocab/stats/screen/batches/bank/security/onboarding/settings/auth/admin_ops/prewarm/content/words/ecdict、`wd check` 不变量、`eval_provider`/`smoke` | 3.0 |
| 种子 | `seed.py` 导入器（校验、tag 重建、`seed_check` 防御）、`build_seed.py` MANIFEST 化与 ext 规则、`stats.json`/ATTRIBUTION、副本导入排练 | 1.5 |
| 前端 | `useStages`、AuthContext、StageChips、Vocab/Welcome/Settings/Screen/ScreenRun/Admin、zh.ts + FRONTEND §8、CSS、16 个测试文件 + 新测试 | 2.5 |
| 文档 | API.md §9 与端点、DESIGN、FRONTEND、DEPLOY、TASKS、README、qa-frontend、CLAUDE_INTEGRATION 示例 | 0.5 |
| 上线 | Mac 停机流程、验证、回滚演练一次 | 0.5 |
| **合计** | | **9.0（8–11）** |

---

## 附录 A　排练脚本与产物

- `scratchpad/design-stages-as-data/0011_stages_as_data.sql` — 本文 3.3 的完整草案（含 `ecdict_tag` 列）。
- `scratchpad/design-stages-as-data/probe0011.py` — 迁移排练 + 8 组基准（输出见 3.3、3.5.1）。
- `scratchpad/design-stages-as-data/fate.py` — 官方清单 × 库的归宿计算（输出见 3.9）。
- 产物：`base.db`（私有拷贝）、`new.db`（已迁移）、`old.db`（对照）、`migrations/`（仓库 4 个文件 + 0011）。

## 附录 B　引用的调研条目

[A1] 现库阶段事实；[A3]/[stage-model-1,2,9] 常量与索引方案；[A4]/[stage-model-11,12,13]/[verify stage-model-13] 重建与 `v_bank`；[A5]/[ai-prompts-stages-9] 难度尺子；[A6]/[seed-pipeline-10,11,12,14] 导入语义；[A7]/[frontend-stages-13,14] 默认与门禁；[A8]/[stage-model-15,16,17,18] 维度路线；[B2]/[verify shanghai-primary-21]/[verify provinces-24] 二级 505；[B4]/[B5]/[verify shanghai-secondary-19] 上海初中表；[C1]/[verify provinces-25] 三级 1600；[C2]/[verify provinces-22] 高中 3000/3100；[D6] 提示词；[frontend-stages-7,8,15,16,19,20,22,24,25] 前端门禁与布局；[verify stage-model 遗漏 1,2,3,4]；INDEX Q1–Q9、§4.1、§6.2。
