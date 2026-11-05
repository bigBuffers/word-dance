# 阶段模型与地区维度 — 设计「最小增量」：`stage_xs` 列 + 索引重编号 1..5，地区只留在 `words.sources`

基线：仓库 `/Users/sqin/word-dance`，`main @ 75df534`；线上库只读副本 `scratchpad/live-copy.db`（版本 10，9,162 词，2 个用户）；日期 2026-11-05。
角度：**最小增量** — 沿用 `stage_*` 布尔列 + `stage_min` 整数，加一列 `stage_xs`，索引重编号 1..5；「上海/全国」「拓展/超纲」都不做成每用户维度，只以 `words.sources` 的来源令牌保留信息。

本文件的证据来源：`docs/analysis/2026-11-05-stages-regions-images/INDEX.md`（引用格式 `[INDEX A3]`、`[INDEX Q1]`），`facts/<slug>.md` / `verify/<slug>.md`（引用格式 `[stage-model-9]`、`[verify frontend-stages-12]`），以及我自己按 75df534 重新打开过的每一处代码（`path:line`）。我另外做了两次排练，脚本与产物都在 `scratchpad/design-stage-model-minimal/`（见 §5.4）：

- `rehearse_0011.py`：用应用运行时 `.venv/bin/python`（3.12.16 / SQLite 3.54.1）调真实的 `wd.db.run_migrations`，在 `live-copy.db` 的私有拷贝上跑本文 §3.4 的 0011 草案，**一次通过**（0.041 s），并在空库上从 0001 跑到 0011 也通过。
- `retag_sim.py`：按假设 A1/A2/A3 用其他 agent 已抽取的官方词头文件（二级、三级、上海 2020、高中 2020/2025）在只读副本上**模拟**重标 9,162 词。这些文件是调研产物而非词表任务的最终交付，所以下文凡标「模拟」的数字都是量级，不是验收常量。

---

## 1. 一页结论

| # | 决定 | 为什么（一句话） | 代价 |
|---|---|---|---|
| D1 | 阶段枚举 4 → 5：`xs`（小学）/ `zk` / `gk` / `cet4` / `cet6`；列名 `stage_xs`，中文「小学」 | 与 `zk/gk` 同构、能直接进 `f"w.stage_{s} = 1"` 模板（`vocab.py:53`、`screen.py:52`、`batches.py:233`、`prewarm.py:39`、`words.py:229`）；`xx` 不能用——它已是测试里的「非法阶段」探针（`test_screen.py:136` `stage=xx` → 400） | 10 份常量 + 3 个请求 `Literal` 各加一个值 |
| D2 | 整数索引**重编号 1..5**（xs=1 … cet6=5），保持「索引 = `STAGE_ORDER` 位置 + 1 = 难度顺序」不变式 | 它是现有「位置推导」代码（`schemas.py:58`、`seed.py:208`、`ecdict.py:177`）的自然结果：映射函数一行不改，`_STAGE_DISTANCE`、`new_only`、`stage_min IS NOT NULL` 全部原样工作；`=0` 要重写两个映射 + 修 3 处 `or DEFAULT` 陷阱并永久引入「0 为假」这一类 bug；`追加 5` 打破不变式要在 3 处 SQL 加 CASE；字符串码是另一条路线 | 一次性 `+1`（线上 2 行用户设置、9,162 行 `stage_min`——后者随后被种子重导覆盖），全部写死 `1=zk…4=cet6` 的文档作废（§4 列全） |
| D3 | 成员存储沿用 `stage_*` 布尔 + `stage_min`，**只加一列** `stage_xs`；不建 `word_stage_tags` / `stage_defs` | 线上 ≈18,321 个 (词, 阶段) 对用 5 个 0/1 列表达足够；所有选词 SQL 不换形 | 以后每加一个阶段都是一次表重建（见 §7 封死路径） |
| D4 | 「上海/全国」与「拓展/超纲」**都不是维度**：初中 = 上海 2020 表 ∪ 国家三级 1600（并集进同一个 `stage_zk`）；每词来自哪张表只记在 `words.sources` 的来源令牌里（§3.3 令牌表），不建索引、不进 API | 没有方案维度就没有第二套 `stage_min`、`/api/stages?scheme=`、前端数据驱动页签；`sources` 本来就是种子管理列（`seed.py:66`），只是从今天的 6 个令牌扩成 10 个 | 用户层面不可按「上海/全国」切换；拓展层不存在（见 §7） |
| D5 | `difficulty` 1–5 尺子与提示词**不动**（1 = 初中 basic）；小学词由 Claude 共用 1；词库 `sort=difficulty` 的表达式改为 `COALESCE(w.difficulty + 1, w.stage_min, 6)` | 这是唯一让两把尺子重新对齐的一行改动；排练库上 `difficulty + 1 = stage_min` 对 49 行中的 44 行成立——与今天的 44/49 完全一样 | 小学词没有自己的难度档；6 级尺子留待以后 |
| D6 | 老词：按 A2/A3 重算全部 `stages`；mahavivo 中考/高中两表与 ECDICT 的 `zk/gk` 标签不再授予阶段；掉出所有表的词**留在种子里**（`stages=[]` → `stage_min NULL`，只在「全部」页签可见，不进筛词/推荐/预生成）；种子「只增不减」成为规则，由 `build_seed.py --base` 携带上一版全部 lemma 保证 | 导入是覆盖 20 列而**从不删除**（`seed.py:72-82`），不在新种子里的词会带着旧旗标活下去——携带规则把这个坑封掉 | 模拟：237 个词失去全部阶段、初中层 2,099 → ≈1,993、高中层 3,829 → ≈3,204（§3.8） |
| D7 | 新用户默认改 K-12：DDL `stages_json DEFAULT '["xs","zk"]'`、`current_stage DEFAULT 1`（= xs）；`bank.py:85-86` 同步；欢迎页加「小学生」角色，`初中生` 预设改为 `xs+zk` | 注册 `INSERT` 不写这两列（`security.py:662`），默认只能靠 DDL；改 DEFAULT 同样只能重建，所以和 0011 合并 | 现有 2 个用户只做 `current_stage + 1`，不自动加入小学 |
| D8 | 一个迁移 `0011_primary_stage.sql`：先 `DROP VIEW v_bank`，重建 `words`（+`stage_xs`、CHECK 1..5、`stage_min + 1`）与 `user_settings`（CHECK 1..5、新 DEFAULT、`current_stage + 1`），重建 6 + 1 个索引与视图，最后 `DELETE FROM kv WHERE key='seed_version'` 强制下次启动重导种子 | 已在副本上通过 `run_migrations`：0.041 s，25 张表行数不变（只有 `schema_migrations` +1、`kv` −1），`foreign_key_check` 空，`integrity_check ok`，空库 0001→0011 也通过 | 文件 5.6 MB → 9.4 MB（935 个空闲页），迁移后手动 `VACUUM` 回到 5.5 MB |
| D9 | 部署：停服务 → 快照 → `wd migrate` → `wd import-seed`（新种子）→ 发布同一提交的前端快照 → 起服务；后端与前端同一次停机落地，没有「只回代码」的回滚 | `index_to_stage` 旧代码对 5 抛 `ValueError`（`schemas.py:65`）→ 任何六级用户的 `/api/settings` 500；回滚只能 `wd restore backups/pre-migrate-10-to-11.db.gz` | 停机 ≈ 1 分钟；回滚会丢迁移后的学习记录 |

**工作量**：本切片 ≈ 4.5 人日（迁移 + 后端 1.0，种子构建与来源登记 1.0，前端 0.5，测试 1.0，文档 0.5，排练/上线 0.5）；不含词表任务（官方词头清单的 OCR/校对/定稿）与配图/提示词切片。

**被封死或变贵的未来路径（诚实清单，详见 §7.2）**：① 每用户「上海/全国」方案（需要第二个 `stage_min` 与 `/api/stages` 契约变更，等于 INDEX 的路线 B，另一次迁移）；② 「拓展/超纲」层（没有任何表示，词要么在某个阶段要么是词典词）；③ 在 zk 与 gk 之间再插阶段（又一次重编号 + 表重建；追加在末尾则便宜）；④ 阶段成为数据（`stage_defs`）与前端数据驱动页签（本设计把 5 个阶段继续写死在 10 份常量 + 5 个前端文件里）；⑤ 教材/年级/单元顺序（种子格式无字段）；⑥ 6 级 `difficulty` 尺子（未来仍需 ≈12 文件的契约变更）；⑦ 上海高中 200 个补充词（A2 暂缺，落地时只是词表更新，不是模型变更——这一条没有被封死）。

---

## 2. 对照假设 A1–A6 的偏离与理由

| 假设 | 本设计 | 偏离 | 理由 / 依据 |
|---|---|---|---|
| A1 小学 = 国家 2022 课标二级 505 | 采用：`stage_xs` = 二级 505 词头；教材词不入库 | 无 | 505 词 500/505 已在库、495 个今天 `stage_min=1`，只缺 `excited`（`[INDEX B2]`）；模拟：以二级为 `xs` 后，505 个词里只有 `ice cream` 不同时属于新的 zk 定义，其余都被三级 1600「含二级」自然覆盖——所以**不**强制 `xs ⊂ zk`，旗标仍按来源记录（与 `DESIGN.md:186`「cumulative as in the sources」一致） |
| A2 初中 = 上海 2020 ∪ 国家三级；高中 = 2025 修订 3100（含 2020 版 3000）；考试院 200 词暂缺 | 采用；并细化：① 上海表只取**单词**部分（≈1,731），331 个词组本轮不入库；② 高中取 2025 修订主表 ∪ 2020 版主表，117 个国家/国籍附表词**本轮不加**；③ ECDICT 自带的 `zk/gk` 标签不再授予阶段（CET 标签照旧） | 细化 ①②③ | ① 现库只有 13 个 `kind='phrase'`（`[INDEX A1]`），331 个词组要么没有 ECDICT 词条要么释义不配，属词表任务的另一个决定；② 附表词几乎都是 `proper_noun`（模拟：2025 表 94 个不在库的词头多数是国名），`derive_kind`（`words.py:143-151`）会把它们标成专名并以 `safe_for_sharing=1` 导入（`seed.py:74`）——先不扩这批；③ 若保留 ECDICT `zk/gk` 标签，680 个不在三级表、1,196 个不在国家高中表的现有词就留在初中/高中层（`[INDEX C1][INDEX C2]`），与 A2 的定义矛盾；`seed-pipeline` O5 证实 ECDICT csv 的 zk 标签只是现库 zk 的子集，不带来新信息 |
| A3 只用官方文件词头；mahavivo 中考/高中两表不再作依据；有道系/DictionaryData/墨墨不入库 | 采用；`build_seed.py` 删除 `中考英语词汇表.txt`、`Highschool_edited.txt` 两个输入；CET4/CET6/CET_4+6/六级星标四个 mahavivo 文件保留（README 有来源说明，`[seed-pipeline-5]`） | 无 | 顺带消灭 `RICH_RE` 丢 `best/less/cafe` 的缺陷（`[INDEX A6]`）——那条正则只服务于被删掉的中考表 |
| A4 不按省份分层；「上海/全国」双方案与「拓展/超纲」层由设计决定 | 决定：**都不做**。上海初中表并入 `stage_zk`；来源令牌 `sh_zk_2020` / `l3_2022` 分别保留在 `sources` | 这是本角度的核心取舍 | 代价与封死路径在 §7.2 明说；信息不丢（§3.3） |
| A5 配图先改提示词 | 不属本切片。本切片只保证 AI 侧不崩：`content.STAGE_ZH["xs"]="小学"`（否则 `content.py:88` 对带新旗标的词 `KeyError`，`[verify ai-prompts-stages 遗漏 1]`），并建议 `AUDIENCE` 与 `content_system.txt:1` 加上小学受众（必须与 `docs/CLAUDE_INTEGRATION.md:211` 逐字同步，`test_schemas.py:122-126`） | 无 | 提示词的实质改动（例句长度、`EXAMPLE_EN_MIN`）留给 Q7/Q9 |
| A6 新用户默认 K-12；2 个用户的迁移规则写死 | DDL 默认 `["xs","zk"]` / `current_stage=1`；0011 对所有现有行只做 `current_stage + 1`、`stages_json` 原样（它存的是码不是索引，`security.py:612-614`），**不**给任何人自动加 `xs` | 「主攻默认 = 小学」是我的选择，INDEX Q6-a 列的是 `["xs","zk"]`/xs | 默认值只在用户点「我是…」之前的欢迎页与无设置行的兜底里可见（`WelcomePage.tsx:72-73`、`bank.py:161-182`）；上海小学生是首要受众；初中生点一下角色即覆盖 |

---

## 3. 详细设计

### 3.1 阶段枚举 4 → 5 与整数索引编码（Q1）

**结论**：`STAGE_ORDER = ("xs", "zk", "gk", "cet4", "cet6")`，索引 = 位置 + 1，即 `xs→1, zk→2, gk→3, cet4→4, cet6→5`；`StageIndex = Literal[1, 2, 3, 4, 5]`；DB CHECK `BETWEEN 1 AND 5`。四个候选方案的比较（代价均按 75df534 代码逐处点数）：

| 评价维度 | ① 小学 = 0 | ② 追加 = 5 | **③ 重编号 1..5（选）** | ④ 字符串码 + `stage_defs` |
|---|---|---|---|---|
| 映射函数 `schemas.py:56-67` | 两个函数改成显式字典（`{"xs":0,…}`），范围检查改 `0..4` | 字典 + 单独的 rank 表 | **只改范围常量**：`1 <= i <= len(STAGE_ORDER)`；`stage_to_index` 不动 | 删除整层，`StageIndex` 类型消失 |
| 种子/ECDICT 的 `stage_min` 公式 `seed.py:208`、`ecdict.py:177` | 改查表 | 改「取 rank 最小」 | **不改**（`stages` 已按 `STAGES` 顺序过滤，`stages[0]` 即最低） | 改成码字符串 |
| 排序 SQL `screen.py:34-35`、`batches.py:60`、`vocab.py:78` | 不改（0 < 1 成立） | 三处改成 `CASE … WHEN 5 THEN 0 …` 查表 | **不改**（`vocab.py:78` 因 Q5 另改一次，见 §3.2） | 三处 JOIN `stage_defs.rank` |
| `or DEFAULT` 陷阱 `screen.py:44`、`batches.py:272,698`（`int(x or 3)`） | **必须修**三处为 `is None`，且永久背上「0 为假」风险（Python 与 JS 两侧） | 无 | **无**（索引 ≥ 1） | 无 |
| 数据迁移 | 不重编号（但两表仍要重建改 CHECK，`[stage-model-11]`） | 不重编号 | 两表重建时 `+1`：线上 2 行 `user_settings`、9,162 行 `stage_min`（后者随后被 `import-seed` 按新种子重算） | 重建 + 值转换 `CASE 1 THEN 'zk' …` |
| 文档/契约 | `API.md §9.1` 映射文字改、`StageIndex` 加 0 | 同左，另需解释「5 排在最前」 | `API.md §9.1`、`DESIGN.md:72/186/202/322`、`TASKS.md:174`、`0001` 注释（冻结，写进 0011 头注释）全部改数字——**而这些行因为重标词表本来就要改**（验收数字 2099/1792/1577/3694 不再成立） | 全部改 + `types.ts:45,52` 类型变化 |
| 前端 | `STAGE_INDEX` 加 `xs:0`、`StageIndex` 加 0；12 处数字夹具不动 | 同左 | `STAGE_INDEX/STAGE_BY_INDEX` 重排；12 处 `stage_min: N` 夹具语义漂移（`[verify frontend-stages-12]`），建议同步 +1 | `StageChips.tsx:31` 比较改字符串 |
| 历史快照 `push_batches.settings_json.current_stage`（只写不读，`batches.py:314-318`） | 含义不变 | 含义不变 | 旧快照整数含义偏移一位（4 行，无读取者） | 旧快照成孤儿格式 |
| 回滚 | 都一样：一旦有索引超出旧 CHECK/旧 `index_to_stage` 范围，旧代码 500，只剩快照恢复（`[verify stage-model 遗漏 2]`） | 同 | 同（且立刻成立：任何六级用户的 `current_stage=5`） | 同 |

选 ③ 的理由：它是**改动行数最少且不引入新陷阱**的方案——后端映射/排序/种子公式零改动，付出的只是一次 `+1`（数据代价「历史最低点」，`[verify seed-pipeline O3]`）和一批本来就要重写的文档数字。① 看似「数据不动」，但两表照样要重建（CHECK），还多了三处必修陷阱与一类长期风险；② 让「索引 = 顺序」失效，三处 SQL 与两处公式都要查表；④ 是 INDEX 的路线 B，不在本角度内。

**码名**：`xs`。备选 `xx`（小学拼音首字母）已被 `test_screen.py:136`（`/api/screen/next?stage=xx` → 400）当作「非法阶段」探针使用，且像占位符；`ps`/`pri` 与 `zk/gk` 风格不一致。`xs` 读作「小升」亦可。

### 3.2 与 `difficulty` 1–5 尺子的关系（Q5）

**结论**：尺子、三份提示词、三个 JSON schema、四个 pydantic `Literal`、`schemas.py:47 Difficulty`、`types.ts:73`、DB CHECK **全部不动**；小学词在提示词层共用 1（INDEX Q5-a）。唯一的改动是把两把尺子当一把用的那一处 `routers/vocab.py:78`：

```python
"difficulty": "COALESCE(w.difficulty + 1, w.stage_min, 6), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma",
```

依据：`difficulty d`（1 初中 … 4 六级，5 beyond）在新索引空间恰好是 `d + 1`（2 zk … 5 cet6，6 beyond）。排练库上 `SUM(difficulty + 1 = stage_min)` = 44 / 49，`<` 2、`>` 3，与迁移前 `difficulty = stage_min` 的 44/2/3（`[ai-prompts-stages-14]`）完全一致——证明这一行保住了今天的语义。副作用（要写进 `API.md:169`）：小学词若已有 AI 内容会带 `difficulty=1` → 排序键 2，与初中词并列而排在没有内容的小学词（键 1）之后；只影响词库页的「难度」排序，不影响学习、筛词、推送。

不扩成 6 级的理由：线上只有 49 行非空（全部是四级词，`[verify ai-prompts-stages-10]`），扩尺子要动 ≈12 个文件 + 迁移 + `API.md §9` + `PROMPT_VERSION`（`[INDEX A5]`），而且 `consolidate_system.txt:10` 把 3 当「无需填写」哨兵、`lookup_system.txt:6` 连图例都没有——那是一次独立的契约变更，等真实小学内容生成后再评估。

### 3.3 词的阶段成员如何存储；「上海/全国」「拓展/超纲」为何不是维度（Q3/Q4）

**结论**：每词 5 个 0/1 列 + `stage_min`（最低阶段索引，NULL = 不在任何表）。`stage_zk = 1` 的定义变为「在上海 2020 单词表 **或** 国家三级 1600」。信息保留在 `words.sources`：它是种子管理列（`seed.py:66`，`0001_init.sql:188`「provenance」），由 `build_seed.py:127,139,146` 写入、`seed.py:210` 以空格连接排序后入库，今天的取值是 `zk gk cet4 cet6 cet46 ecdict` 六个令牌（如 `'cet4 cet46 ecdict gk zk'`）。新的令牌登记表（写进 `data/seed/ATTRIBUTION.md` 与 `DESIGN.md §3.2`）：

| 令牌 | 含义 | 授予旗标 |
|---|---|---|
| `l2_2022` | 国家 2022 课标附录 3 二级词汇表（505） | `stage_xs` |
| `l3_2022` | 国家 2022 课标附录 3 三级词汇表（1600，含二级） | `stage_zk` |
| `sh_zk_2020` | 上海市教育考试院《2020 年初中英语课程终结性评价指南·词汇表》单词部分 | `stage_zk` |
| `hs_2020` | 普通高中英语课程标准（2017 年版 2020 年修订）词汇表 3000 | `stage_gk` |
| `hs_2025` | 普通高中英语课程标准 2025 年修订词汇表 3100（主表） | `stage_gk` |
| `cet4` / `cet6` / `cet46` | mahavivo `CET4_edited.txt` / `CET6_edited.txt` / `CET_4+6_edited.txt`（不变） | `stage_cet4` / `stage_cet6` |
| `ecdict` | ECDICT 本身带 `cet4`/`cet6` 标签（**不再**因 `zk`/`gk` 标签写入） | `stage_cet4` / `stage_cet6` |
| （删除）`zk`、`gk` | 原 mahavivo 中考表 / `Highschool_edited.txt` | 不再出现 |

这样做保留了什么：日后若要做「上海/全国」双方案（INDEX 路线 B），回填 `word_stage_tags(word_id, scheme, stage)` 只需 `INSERT … SELECT id, 'sh', 'zk' FROM words WHERE instr(' '||sources||' ', ' sh_zk_2020 ')`，一条 SQL 一个令牌——信息在，缺的只是索引与接口。没有保留什么：mahavivo 两张旧表的成员关系（A3 已决定它们不是依据；旧种子在 git 历史 `data/seed/vocab.jsonl.gz@75df534` 里可查），以及「拓展」层——掉出所有表的词不带任何「曾是初中/高中词」的旗标。

不做维度的量化依据：模拟中 `stage_zk` 的 1,993 个词里，只经上海表进入的 395 个、只经三级表进入的 291 个，其余 1,307 两表都有；把两者并集给所有用户看，意味着全国用户多看到 ≈395 个上海词、上海用户多看到 ≈291 个三级功能词——在没有方案维度的前提下，这是「宁多勿漏」的取舍（`[INDEX B5]`：上海表 25% 不在三级表、三级表 19% 不在上海表）。

`/api/stages` 契约：仍是固定顺序的全量清单，从 4 行变 **5 行**（`xs, zk, gk, cet4, cet6`，`index` 1..5）；`StageInfo` 形状不变（`schemas.py:448-457`、`API.md:278-282`）。前端继续以常量驱动页签（`StageChips.tsx:7`、`VocabPage.tsx:29`），不做数据驱动——`ScreenPage.tsx:31` 对未知阶段的静默丢弃在两端同一提交更新后无害，但必须记为部署顺序约束（§3.6）。

### 3.4 迁移 `0011_primary_stage.sql`

**结论**：一个文件、两张表重建、一条 `kv` 清理；运行器约束逐条满足（`db.py:195-249`：`PRAGMA foreign_keys=OFF` 在 `BEGIN IMMEDIATE` 之前、`executescript` 在运行器事务内、`foreign_key_check` 后由运行器写 `schema_migrations(11,'primary_stage')`；文件内不得 `COMMIT`/`ROLLBACK`/切 PRAGMA/自写 bookkeeping，`db.py:232-234`、`0001_init.sql:25-37`）。`docs/SCHEMA.sql` **保持与 0001 字节一致**（`test_db.py:362-366`）；新 DDL 完整写在 0011 里（它本来就要含整段 `CREATE TABLE`），并在 `DESIGN.md §3.1` 加一行「当前 schema = 0001 + 0008 + 0010 + 0011；0011 的差异见文件头」。下面是已在副本上跑通的全文（`scratchpad/design-stage-model-minimal/0011_primary_stage.sql`）：

```sql
-- 0011_primary_stage.sql — add the 小学 stage (code `xs`), renumber the stage index 1..5 and move the new-user default to K-12.
--
-- Why a rebuild: SQLite cannot ALTER a CHECK list or a column DEFAULT, so `words` (stage_min BETWEEN 1 AND 4) and
-- `user_settings` (current_stage BETWEEN 1 AND 4, DEFAULT 3, stages_json DEFAULT '["cet4","cet6"]') are re-created with
-- SQLite's 12-step recipe (CREATE new → INSERT … SELECT → DROP old → RENAME → indexes → views). The runner wraps this file
-- in BEGIN IMMEDIATE with foreign_keys=OFF and runs foreign_key_check before recording schema_migrations(11, 'primary_stage')
-- itself (SCHEMA.sql §1); nothing here toggles PRAGMAs or commits.
--
-- Index renumbering (DESIGN §0.3 / API.md §9.1): old 1=zk 2=gk 3=cet4 4=cet6 → new 1=xs 2=zk 3=gk 4=cet4 5=cet6, so every stored
-- stage_min / current_stage moves +1 (NULL stays NULL). The seed re-import that follows (`kv.seed_version` is cleared below so
-- the next `wd import-seed` / `wd serve` start imports unconditionally) recomputes stage_xs/stage_zk/stage_gk/stage_min for
-- every seed word from the new lists; the +1 here only keeps the database self-consistent in between and for non-seed rows.
--
-- The view v_bank references words: it must be dropped before the DROP TABLE/RENAME and re-created afterwards (verified: with
-- legacy_alter_table=OFF the RENAME fails with "error in view v_bank: no such table: main.words" otherwise). Stop-first migration
-- (DEPLOY §10: never under install.sh --no-restart). docs/SCHEMA.sql stays the 0001 baseline byte-for-byte (test_db.py).

-- ---------------------------------------------------------------------------
-- 1. words: + stage_xs, stage_min 1..5 (renumbered), comments updated
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
  stage_xs            INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs   IN (0,1)),  -- 小学 (国家 2022 课标二级 505 词)
  stage_zk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_zk   IN (0,1)),  -- 初中 (上海市教育考试院 2020 初中词汇表 ∪ 国家 2022 课标三级 1600)
  stage_gk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_gk   IN (0,1)),  -- 高中 (国家高中课标 2017/2020 版 3000 ∪ 2025 修订版 3100)
  stage_cet4          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet4 IN (0,1)),  -- 四级
  stage_cet6          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet6 IN (0,1)),  -- 六级 (cumulative: includes most CET-4)
  stage_min           INTEGER CHECK (stage_min BETWEEN 1 AND 5),  -- lowest stage 1=xs 2=zk 3=gk 4=cet4 5=cet6; NULL = outside the 5 lists.
                                                                  -- 仅本阶段新增 filter == stage_min = <stage index>
  cet6_star           INTEGER NOT NULL DEFAULT 0 CHECK (cet6_star IN (0,1)),   -- starred CET-6 word
  sources             TEXT,                             -- provenance tokens, e.g. 'cet4 cet46 ecdict l3_2022 sh_zk_2020' (ATTRIBUTION.md)
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
--    Existing rows keep their stage codes (stages_json is codes, not indexes): on the live database this maps
--    (user 1: current 3 → 4 = cet4, stages zk/gk/cet4/cet6) and (user 2: current 1 → 2 = zk, stages zk). Nobody is auto-enrolled in xs.
-- ---------------------------------------------------------------------------
CREATE TABLE user_settings_new (
  user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  timezone           TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
  push_time          TEXT    NOT NULL DEFAULT '08:00' CHECK (push_time GLOB '[01][0-9]:[0-5][0-9]' OR push_time GLOB '2[0-3]:[0-5][0-9]'),
  push_enabled       INTEGER NOT NULL DEFAULT 1  CHECK (push_enabled IN (0,1)),
  daily_new_count    INTEGER NOT NULL DEFAULT 10 CHECK (daily_new_count BETWEEN 0 AND 50),
  daily_screen_count INTEGER NOT NULL DEFAULT 15 CHECK (daily_screen_count BETWEEN 0 AND 50),
  max_reviews        INTEGER NOT NULL DEFAULT 60 CHECK (max_reviews BETWEEN 0 AND 300),
  stages_json        TEXT    NOT NULL DEFAULT '["xs","zk"]',  -- 目标阶段: non-empty subset of xs/zk/gk/cet4/cet6 (set by onboarding); K-12 default
  current_stage      INTEGER NOT NULL DEFAULT 1  CHECK (current_stage BETWEEN 1 AND 5),  -- 主攻阶段 1=xs 2=zk 3=gk 4=cet4 5=cet6; Stage string on the wire (API.md §9.1)
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
-- 3. Force the seed re-import on the next start (the importer records the new sha256 again; 0.2 s for 9,162 words)
-- ---------------------------------------------------------------------------
DELETE FROM kv WHERE key = 'seed_version';
```

要点与依据：

- **`DROP VIEW v_bank` 先于重建、最后 `CREATE VIEW`**：不这样做 `RENAME` 在应用运行时（`legacy_alter_table=0`）报 `error in view v_bank: no such table: main.words` 并整体回滚（`[stage-model-13]`，核验升级为实测）；本机 `/usr/bin/sqlite3` 3.51.0 默认 `legacy_alter_table=1` 会把这个错误掩盖掉——排练一律走 `run_migrations`。
- **显式列清单的 `INSERT … SELECT`**：因为 `stage_xs` 插在 `stage_zk` 之前，`SELECT *` 会错位。
- **`stage_min + 1`**：SQLite 中 `NULL + 1 = NULL`，无阶段词保持 NULL（线上 0 行，但用户词路径会产生）。
- **`merged_into_word_id INTEGER REFERENCES words(id)`** 仍写 `words(id)`：`words_new` 重命名为 `words` 后引用按名解析；探针与我的排练 `foreign_key_check` 均为空、随后 `INSERT user_words(word_id=999999)` 被拒，证明外键在重建后仍然生效。引用 `words` 的 9 条外键（`word_forms`/`word_contents`/`word_images`/`user_words.word_id`/`push_items`/`content_reports` CASCADE，`user_words.suggested_word_id`/`bank_suggestions.target_word_id`/自引用 SET NULL，`[verify stage-model-12]`）在 `foreign_keys=OFF` 下不会触发级联——这是运行器把 PRAGMA 放在事务外的全部意义（`db.py:222-227`）。
- **索引 6 + 1**：`0001_init.sql:205-210` 的六个 `words` 索引与 `:161` 的 `ix_user_settings_next_push`；0008 的三个索引在 `push_items`/`bank_suggestions` 上，不受影响。
- **`DELETE FROM kv WHERE key='seed_version'`**：`main.seed_check`（`main.py:307-319`）与 `import_seed`（`seed.py:260-263`）都拿它和文件 sha256 比较；清掉它保证即使运维忘了显式 `wd import-seed`，`wd serve` 启动也会重导一次（0.2 s，`[seed-pipeline-15]`）。这也是数据迁移在文件内的先例（0009 是纯 `UPDATE`）。
- **`user_settings` 没有任何子表**（`[verify stage-model-12]` 对 25 张表跑 `pragma_foreign_key_list`），所以第 2 段没有级联风险；`users` 不动。
- **数据规则（写死）**：所有行 `current_stage + 1`；`stages_json` 原样；不自动加 `xs`。线上两行的结果：`(1, 4, ["zk","gk","cet4","cet6"])`、`(2, 2, ["zk"])`——排练输出逐字相同。
- **`push_batches.settings_json`**（4 行，含 `"current_stage": 3`）不改：只写不读（`[stage-model-4]`）；在 `DESIGN.md §6.3` 注一句「2026-11 之前的快照用旧索引」。
- **VACUUM 不能在迁移文件里做**（运行器把文件包在事务里）；排练：文件 5,644,288 → 9,449,472 字节（935 个空闲页），迁移后手动 `VACUUM` → 5,554,176。上线步骤里放一条可选的 `VACUUM`。
- **排练结果**（§5.4 脚本）：`applied=[(11,'primary_stage')]` 0.041 s；25 张表中只有 `schema_migrations` 4→5、`kv` 15→14；`stage_min` 分布 1/2/3/4 → 2/3/4/5 且逐行恰好 +1；旗标和 `difficulty`/内容/配图计数 `2099|3829|4722|7671|49|49|31` 不变；`stage_xs` 全 0；`stage_min=0/6`、`stage_xs=2`、`current_stage=0/6` 都被 CHECK 拒绝；新插入的设置行默认 `('["xs","zk"]', 1)`；`v_bank` 可查（18 行）；无触发器；二次运行 `applied=[]`；空库 0001→0011 应用列表 `[(1,'init'),(8,…),(9,…),(10,…),(11,'primary_stage')]`，25 张表 + `v_bank`。

### 3.5 后端改动（逐文件、逐函数）

**结论**：代码改动全部是常量级，没有新模块；唯一「逻辑」改动是 `vocab.py:78` 的排序表达式和 `ecdict.py` 的标签→索引映射。

| 文件 | 位置 | 改什么 |
|---|---|---|
| `backend/wd/schemas.py` | `:25` `Stage = Literal["xs", "zk", "gk", "cet4", "cet6"]`；`:26` `StageIndex = Literal[1, 2, 3, 4, 5]`；`:51` `STAGE_ORDER = ("xs", "zk", "gk", "cet4", "cet6")`；`:52` `STAGE_NAMES_ZH` 加 `"xs": "小学"`；`:56-61` `stage_to_index` 只改 docstring（`xs→1 … cet6→5`）；`:65` `if not 1 <= int(index) <= len(STAGE_ORDER)`；`:488` `VocabQuery.stage`、`:708` `ScreenNextQuery.stage`、`:1335` `PrewarmRequest.stage` 各加 `"xs"`（顺序与 `types.ts` 一致——`check_contract.py:274-281` 顺序敏感比对的是 `export type` 别名，这三处是字段内联 `Literal`，不被比对，但保持同序）；`:10` 模块 docstring |
| `backend/wd/seed.py` | `:7` docstring「the four stage flags」→ five；`:43` `STAGES = ("xs", "zk", "gk", "cet4", "cet6")`；`:47-68` `SEED_COLUMNS` 在 `"stage_zk"` 前加 `"stage_xs"`（UPSERT 的 SET/WHERE 由 `:72-82` 自动生成）；`:204` 前加 `"stage_xs": int("xs" in stages)`；`:208` 公式不改 |
| `backend/wd/services/words.py` | `:39` `STAGES` 同上（`stages_of` `:228-229` 自动）；`:576` 前加 `"stage_xs": 0`；`:590-595` `_INSERT_WORD_SQL` 列清单与占位符加 `stage_xs` |
| `backend/wd/services/ecdict.py` | `:28` `STAGE_TAGS = ("cet4", "cet6")`（ECDICT 的 `zk/gk` 标签不再授予阶段，§2 A2-③）；`:177` **必须改**为 `schemas.stage_to_index(stages[0]) if stages else None`——否则位置推导会把 ECDICT `cet4` 算成 1（= xs）；`:173-176` 前加 `"stage_xs": 0`（否则 `_INSERT_WORD_SQL` 缺参数）；`:119` `stages` 属性自动随 `STAGE_TAGS` |
| `backend/wd/routers/vocab.py` | `:78` `_ORDER["difficulty"]` 改为 `COALESCE(w.difficulty + 1, w.stage_min, 6)`（§3.2）；`:53-56`、`:86-98` 循环与模板自动覆盖 5 个阶段 |
| `backend/wd/services/stats.py` | `:177-190` 自动（`STAGE_ORDER`） |
| `backend/wd/services/bank.py` | `:85` `DEFAULT_STAGES = ("xs", "zk")`；`:86` `DEFAULT_CURRENT_STAGE = 1`（= `stage_to_index("xs")`，加注释）；`:181` 的未知阶段过滤自动接受 `xs` |
| `backend/wd/security.py` | `:613` docstring 的默认值示例改 `'["xs","zk"]'`；`:597` `index_to_stage` 自动；`:662` 注册 `INSERT` 不改（继续吃 DDL 默认） |
| `backend/wd/services/screen.py` / `services/batches.py` | `:44` / `:272,698` 的 `int(x or bank.DEFAULT_CURRENT_STAGE)` **不必改**（索引 ≥ 1）；可选加固：改成 `x if x is not None else …`（3 行），防止将来再有人想用 0 |
| `backend/wd/ai/prewarm.py` | `:32` `STAGE_COLUMNS["xs"] = "stage_xs"`；`:33` `STAGES = ("xs", "zk", "gk", "cet4", "cet6", "all")`；`:37-38` `all` 仍是 `stage_min IS NOT NULL`——词典词（无阶段）不会被预生成，与「没人学就不生成」一致 |
| `backend/wd/ai/content.py` | `:49` `STAGE_ZH["xs"] = "小学"`（**必改**，否则 `:88` `KeyError` 整组失败）；`:48` `AUDIENCE = "Chinese learners, primary school to CET-6, plus working professionals"`（建议） |
| `backend/wd/ai/prompts/content_system.txt` | `:1` 受众括号加「小学」（建议；若改，`docs/CLAUDE_INTEGRATION.md:211` 必须逐字同步——`test_schemas.py:122-126` 断言四份提示词与 §5.1–5.5 代码块逐字节相同）；`:11` 难度图例不改；不 bump `PROMPT_VERSION`（输出语义未变，`content.py:46`） |
| `backend/wd/ai/screen.py:44`、`batches.py:272,698` | 见上一行「不必改」 |
| `scripts/eval_provider.py` | `:107` `STAGES` 加 `"xs"`（`:341-348` 每阶段抽 10 词的分组自动多一组） |
| `scripts/smoke.py` | `:352` 期望 `["xs","zk","gk","cet4","cet6"]`；`:614` `len(stats["stages"]) == 5` |
| `scripts/check_contract.py` | 不改（它只比对） |
| `scripts/build_seed.py` | 见 §3.8 |

### 3.6 API 契约与前端

**结论**：契约改动是 `Stage`/`StageIndex` 两个联合 + 几处文字；前端 7 个源文件 ≈ 25 行 + 1 条 CSS + 测试夹具；**后端与前端必须同一提交、同一次停机**。

契约三件套（`types.ts:1-2` 规则：`API.md`、`schemas.py`、`types.ts` 同一提交）：

- `frontend/src/api/types.ts:5` `export type Stage = 'xs' | 'zk' | 'gk' | 'cet4' | 'cet6';           // index 1..5 in that order`；`:6` `StageIndex = 1 | 2 | 3 | 4 | 5`；`:37` 注释「1–5 index」；`:45` 注释「小学 / 初中 / 高中 / 四级 / 六级」。
- `docs/API.md`：`:239-240`（§9 代码块，与 `types.ts` 逐字相同）；`:271,279,286` 注释；`:155`（端点 12「1–5 column index」）；`:160`（端点 15 `⊆ {xs,zk,gk,cet4,cet6}`）；`:167`（端点 19「5 rows」）；`:169`（端点 20 `stage=all|xs|zk|gk|cet4|cet6`，`difficulty` 排序表达式改为 `COALESCE(difficulty + 1, stage_min, 6)`，cet6 增量数字按新种子更新）；`:187`（端点 31）；`:230`（端点 67）；`:459-460`（§9.1 映射 `xs→1, zk→2, gk→3, cet4→4, cet6→5`）。
- `scripts/check_contract.py:274-281` 顺序敏感：两边都是 `xs, zk, gk, cet4, cet6` 与 `1,2,3,4,5`。

前端源文件：

| 文件 | 改什么 |
|---|---|
| `components/word/StageChips.tsx:7-9` | `STAGE_ORDER = ['xs','zk','gk','cet4','cet6']`；`STAGE_INDEX = { xs: 1, zk: 2, gk: 3, cet4: 4, cet6: 5 }`；`STAGE_BY_INDEX` 对应；`:1` 注释。5 个 chip 的 375 px 布局：`.chips` 是 `inline-flex; flex-wrap: wrap`（`word.css:77-84`），只换行不溢出；线上初中词只有 40.7% 带满标签（`[verify frontend-stages-15]`）——接受换行，不加收敛逻辑 |
| `i18n/zh.ts:28-29` | `stages` 加 `xs: '小学'`、`xsFull: '小学（课标二级）'`（括号内没有对应考试，写词表来源；备选「小学（1–5 年级）」与五四制耦合，不选）；`:25` `welcome.roles` 加 `xs: '小学生'`；`:86` `sources.lists: '词表范围：课标小学二级、上海初中词汇表与课标三级、高中课标词表、大学英语四级与六级大纲'`。**同一提交**把 `docs/FRONTEND.md:231-235, 292` 的镜像块改成逐行相同（`zh.test.ts:67-83` 逐行比对、`zh.contract.test.ts:62-83` 键集合比对，`[frontend-stages-7]`） |
| `pages/WelcomePage.tsx:30-42` | `Role = 'xs' | 'zk' | 'gk' | 'uni' | 'pro'`；`ROLE_PRESETS` 加 `xs: { stages: ['xs'], current: 'xs' }`，`zk` 改为 `{ stages: ['xs', 'zk'], current: 'zk' }`（与「高中生 → 初中+高中」的向下包含一致；推荐词排序先主攻再高阶再低阶，`DESIGN.md:347`，多含一级只是在后面多些简单词）；`ROLES` 加 `'xs'`；`STAGE_FULL` 加键。宽度：角色 chips 现在已折两行，5 个变 3+2（`[frontend-stages-14]`） |
| `pages/ScreenPage.tsx:20` | `FULL_NAME` 加 `xs`；`:31` 的按 `STAGE_ORDER` 重排在两端同步后无需改 |
| `pages/VocabPage.tsx:29` | `TABS = ['all','xs','zk','gk','cet4','cet6']`；`:232` 开关条件改为 `tab !== 'all' && tab !== STAGE_ORDER[0]`（最低阶段的「仅本阶段新增」是恒等过滤，顺手修掉今天初中 tab 上的空操作，`[frontend-stages-19/20]`）；`:202` 文案逻辑不动（六级特例保留，其余用通用「仅本阶段新增」） |
| `components/ui/ui.css` | 6 个 `fill` tab 在 375 px 溢出约 13 px（推断，`[frontend-stages-16]`：6×56 + 5×4 = 356 > 343）。加一条媒体查询：`@media (max-width: 479.98px) { .tabs--fill .tab { padding-inline: var(--space-2); } }` → 6×48 + 20 = 308 ≤ 328，360 px 也放下；上线前在 375/360 真机或 DevTools 复核（算术前提：CJK 1em、根字号 16px） |
| `pages/AdminPage.tsx:36` | `PREWARM_STAGES: readonly PrewarmStage[] = [...STAGE_ORDER, 'all']`（`PrewarmStage = Stage | 'all'` 随 `Stage` 扩展，`endpoints.ts:328`） |
| `pages/SettingsPage.tsx`、`ScreenRunPage.tsx`、`endpoints.ts`、`routes.tsx`、`useLocalPref` | 不改（`[frontend-stages-10]`）；`localStorage['wd.vocabTab'|'wd.screenStage']` 存的是码，旧值仍合法 |
| 测试夹具 | `grep -rn 'stage_min: [0-9]' frontend/src --include='*.test.*'` 的 12 处（10 个文件）按新索引 +1（它们只断言文字，不改也绿，但 `chip--min` 高亮语义会漂移，`[verify frontend-stages-12]`）；`SpeakButton.test.tsx:91,100` 的 chips 顺序断言不变 |

部署顺序：后端未扩枚举时词库页 `stage=xs` 400（`schemas.py:488` → `errors.py` 的 422→400）；更危险的是 `bank.py:181` 会把后端不认识的阶段静默过滤、全部未知时回落到默认（`[verify frontend-stages-13]`）。本项目在 Mac 上由同一个 `wd serve` 进程提供 SPA 快照与 API（`WD_FRONTEND_DIST`），所以规则是：**同一提交构建的前端快照与后端在同一次停机内发布**，不存在先后。

### 3.7 新用户默认（Q6）

**结论**：DDL `stages_json DEFAULT '["xs","zk"]'`、`current_stage DEFAULT 1`；`bank.py:85-86` 镜像为 `("xs","zk")` / `1`；注册流程不改。

依据：注册只插 `user_settings(user_id, next_push_at, updated_at)`（`security.py:661-664`），阶段列吃 DDL 默认（`0001_init.sql:147-148`）；欢迎页用 `settings.stages` 非空时作初值（`WelcomePage.tsx:72-73`），所以在用户点「我是…」之前显示的就是这个默认；`bank.user_settings_row` 在没有设置行时用 `DEFAULT_STAGES/DEFAULT_CURRENT_STAGE` 兜底（`bank.py:164-181`，实际从不缺行）。步骤 1 必须提交（`POST /api/onboarding` 显式写 `stages_json`/`current_stage`，`onboarding.py:32-43`；只有步骤 2 可「跳过引导」），所以默认不会悄悄成为任何人的长期设置。

为什么主攻默认是 `xs` 而不是 `zk`：面向上海的首要受众是小学（1–5 年级），且 `current_stage` 必须 ∈ `stages`（`schemas.py:360-364`、`settings.py:91`）——`["xs","zk"]` 配 `xs` 或 `zk` 都合法，选最低的一个与「初中生预设 = xs+zk、主攻 zk」区分开。

现有 2 个用户：只 `+1`，不加 `xs`（§3.4）。若产品希望给「只选了初中」的用户自动补上小学，可以在 0011 第 2 段加一条 `UPDATE user_settings_new SET stages_json = '["xs","zk"]' WHERE stages_json = '["zk"]'`——我**不**建议：它改变用户明确选择的目标，而设置页点一下即可自助。

### 3.8 老词如何处理；种子流水线与词表接口

**结论**：按新定义全量重算 `stages`；掉出所有表的词留在种子里作「词典词」（`stages=[]`）；`build_seed.py` 加 `--base` 携带上一版全部 lemma，使「种子只增不减」成为机械保证；不删任何线上词。

#### 3.8.1 为什么不能「从种子剔除」

导入是按 lemma 的覆盖式 UPSERT，**从不删除**（`seed.py:72-82`、`[stage-model-19]`）。如果新种子不再含某个词（例如只在 mahavivo 中考表里的词），线上那一行会保留旧旗标：0011 之后它的 `stage_zk=1, stage_min=2`——在新语义下 2 恰好仍是初中，它会继续以初中词身份出现在筛词和推荐里，而它已经不在任何依据表中。模拟显示这类词不少：237 个词在新定义下没有任何阶段，其中 `sources` 只含旧令牌的（`zk` 26、`gk` 16、`gk zk` 1）43 个在 ECDICT 里没有任何阶段标签，纯靠两张旧表进入种子。所以「不出现在新种子里」等于「永远留在旧阶段」，必须排除这种可能：新种子必须包含旧种子的每一个 lemma。

#### 3.8.2 携带规则与 `build_seed.py` 改动

`scripts/build_seed.py`（按 75df534 行号）：

1. 参数：保留 `--db`（stardict.db，`:74`）、`--lists`（mahavivo 目录，只用 CET 四个文件）、`--out`；新增 `--official DIR`（`data/lists/`，词表任务交付的官方词头文件）与 `--base PATH`（上一版 `data/seed/vocab.jsonl.gz`，必填）。
2. 新函数 `parse_headwords(path)`：一行一个词头，UTF-8，`#` 开头为注释，**不丢单字母行**（`parse_list` `:25` 会丢 `a`、`I`，`[seed-pipeline-2]`），`/` 并列由词表任务预先拆开；不用 `RICH_RE`/`POS_RE`。
3. `syllabus`（`:81-88`）删除 `zk`/`gk` 两项，保留 `cet4`/`cet6`/`cet46`/`cet6star`；新增 `official = {"l2_2022": …, "l3_2022": …, "sh_zk_2020": …, "hs_2020": …, "hs_2025": …}`。
4. 步骤 1（`:105-106`）的 ECDICT 查询只取 `cet4`/`cet6` 标签行；`make_record`（`:191`）的 `stages` 只从标签取 `cet4`/`cet6`；`:196` 的 `sources` 初值仍是 `["ecdict"]`。
5. 步骤 2（`:112-127`）：`stage_from_list` 改成 `{"l2_2022": "xs", "l3_2022": "zk", "sh_zk_2020": "zk", "hs_2020": "gk", "hs_2025": "gk", "cet4": "cet4", "cet6": "cet6"}`，`sources` 追加令牌名（即上表令牌）；`cet46` 段（`:128-142`）不变；查不到 ECDICT 的词头照旧进 `missing`（`stats.json.missing_from_ecdict`），由词表任务决定是手写最小记录还是放弃。
6. 新步骤 2b（携带）：读 `--base` 的每条记录，lemma 不在 `words` 时 `lookup()` 后以 ECDICT 字段入集合、`stages=[]`、`sources=[]`；ECDICT 也查不到时（理论上不会——全部 9,162 词都来自 stardict.db）原样保留基线记录但清空 `stages`。
7. `:147` 过滤元组与 `:150` `order` 加 `xs`（`order = {"xs": 0, "zk": 1, "gk": 2, "cet4": 3, "cet6": 4}`）；`:151` 排序键对 `stages=[]` 的记录用 `len(order)` 兜底；`:157-171` 统计多出 `xs` 键并新增 `no_stage` 计数；`ATTRIBUTION`（`:201-219`）重写为：ECDICT（MIT）+ 官方文件词头（教育部课标 2022 附录 3、2017/2020 与 2025 修订高中课标、上海市教育考试院 2020 词汇表——只用词头成员关系，不收录释义/音标/排序）+ mahavivo CET 四文件。
8. 种子记录格式**不变**（15 个键），`stages` 数组可含 `"xs"`；`seed.py:184-185` 的过滤随 `STAGES` 自动接受。

运行环境：`build_seed.py` 硬性需要 `stardict.db`（`:74,97,105`），本机没有（禁区 `/Users/sqin/word-dance-data` 也未安装 ECDICT）。可行路径是手工 `curl -fL` 下载 `ecdict-sqlite-28.zip`（216,765,132 B，解压 851,288,064 B，约需 1.1 GB 空闲；`deploy/fetch_ecdict.sh` 的 `df --output`/`sed -i` 在 macOS 不能直接跑，`[seed-pipeline-8/26]`），校验 `shasum -a 256` 对照 `fetch_ecdict.sh:13`。在 Mac 上 `gzip -9 -n` 得到的归档与 Linux GNU gzip 字节不同（`[seed-pipeline-7]`）——无害，`kv.seed_version` 本来就随内容变化；`scripts/pack_seed.sh --check` 在 macOS 因 BSD `zcat` 失败，用 `gzip -dc … | wc -l` 代替核对记录数。替代路径（不推荐，只在下载不可行时）：用 `ecdict.csv` 基础版给 ≈100 个新词补字段，`pos` 与 `ecdict_id` 不可复现（`[seed-pipeline-27]`）。

#### 3.8.3 词表接口（与词表任务的约定）

`data/lists/` 下 5 个 UTF-8 文本文件，一行一个词头，`#` 注释，不含词组、不含释义、并列项已拆分、缩写书写与 ECDICT 词头一致（`a.m.`、`p.e.`、`Mr.` 带点——现库 `mr.`/`mrs.`/`ms.`/`p.e.` 是带点形式，`[INDEX 矛盾 9]`）：

| 文件 | 规模（核验口径） | 令牌 |
|---|---|---|
| `moe2022_level2.txt` | 505 | `l2_2022` |
| `moe2022_level3.txt` | 1,600（含二级） | `l3_2022` |
| `shmeea2020_junior.txt` | ≈1,731 单词（331 词组另存 `shmeea2020_junior_phrases.txt`，本轮不入库） | `sh_zk_2020` |
| `moe_hs2020.txt` | 3,000 | `hs_2020` |
| `moe_hs2025.txt` | 3,100 主表（117 个国家附表另存，本轮不入库） | `hs_2025` |

屈折形式（上海表的 `children`、`feet` 等）不作词头：`word_forms` 已能解析（`[seed-pipeline-13]`）；模拟中各表经屈折表才命中的词头 1–12 个，词表任务应在交付文件里改成原形。

#### 3.8.4 老词去向（模拟数字，量级）

用其他 agent 抽取的词头文件在只读副本上模拟（`retag_sim.py`，匹配规则：lemma 精确 → 点/连字符变体 → `word_forms`）：

| 项目 | 现状 | 新定义（模拟） |
|---|---|---|
| 各阶段词数 | zk 2,099 · gk 3,829 · cet4 4,722 · cet6 7,671 | xs 505 · zk ≈1,993 · gk ≈3,204 · cet4 4,722 · cet6 7,671 |
| `stage_min` 分布 | 1:2,099 · 2:1,792 · 3:1,577 · 4:3,694 | 1:505 · 2:≈1,489 · 3:≈1,333 · 4:≈1,734 · 5:≈3,864 · NULL:≈237 |
| 初中层变化 | — | 失去 ≈506（其中 275 仍是高中词、159 只剩四六级、71 落到无阶段）；新增 ≈400（三级/上海表里今天只标 gk/cet 的词） |
| 高中层变化 | — | 失去 ≈1,078（854 仍是四六级词、207 落到无阶段）；新增 ≈453 |
| 无阶段「词典词」 | 0 | ≈237（206 word、15 proper_noun、8 phrase、8 abbreviation；例：`addicted, airmail, armchair, bookcase, bungalow, bathtub, beehive`）；其中 95 个只因 ECDICT `zk/gk` 标签入库、43 个只因 mahavivo 两表入库 |
| 小学词原来的 `stage_min` | — | 505 个里 500 个今天是 1（初中），3 个 2、1 个 3、1 个 4（`best`、`chore` 一类，`[INDEX B2]`） |
| 不在库、需新增的词头 | — | 五表并集 ≈116（含约 10 个解析伪影如 `o'`、`w`、`caf`；真实缺词 ≈ 100，多数是 2025 高中表的国家/国籍附表——按 §2 A2-② 本轮不加则约 20 个：上海表 14 个 `angrily, beautifully, bund, carefully, dancer, dishonest, hot-dog, luckily, mr, mrs, politely, quietly, seafood, unforgettable` + 二级 `excited` + 三级 `teenage, tofu, yogurt` 等） |
| 有 AI 内容的 49 词 | 全部四级词 | 38 个的 `stage_min` 变化超出单纯 +1（如 `have` → xs；多数四级词因 2025 高中表而获得 gk）；内容与 `difficulty` 不动（`seed.py:10-12` 永不触碰） |

这些词的产品含义：

- **降级到更高阶段**的词（275 + 854）：仍可被相应阶段的用户筛到；对「初中生」用户它们从推荐中消失——这正是 A2 要的口径对齐。
- **无阶段的 237 词**：`is_public=1` 不变，词库「全部」页签可见、可搜索、可标记、详情可看；筛词（`screen.py:51-56` 要求命中阶段旗标）、推荐词（`batches.py:232-234`）、预生成 `all`（`prewarm.py:38` `stage_min IS NOT NULL`）都不含它们；已经被用户学过的照常复习（`user_words` 不受种子影响）。线上这两个用户学过的词里有多少落入此类，上线前用 §5.4 的查询在副本上数一遍。
- **「仅本阶段新增」语义**：初中 tab 的开关从恒等过滤变成真过滤（≈1,489 vs 1,993），小学 tab 的开关隐藏（§3.6）；`TASKS.md:174`、`API.md:169`、`DESIGN.md:209`、`qa-frontend.md:42` 的验收数字全部按新种子的 `stats.json` 重写。

---

## 4. 改动清单（文件 → 改什么）

### 4.1 数据库与种子

| 文件 | 改什么 |
|---|---|
| `backend/wd/migrations/0011_primary_stage.sql`（新建） | §3.4 全文 |
| `docs/SCHEMA.sql` | **不改**（`test_db.py:362-366`） |
| `data/seed/vocab.jsonl.gz`、`stats.json`、`ATTRIBUTION.md` | 由改后的 `build_seed.py` 重建；`stats.json.per_stage/only_stage/first_stage` 多 `xs` 键，新增 `no_stage` |
| `data/lists/*.txt`（词表任务交付） | §3.8.3 的 5 个文件 |
| `scripts/build_seed.py` | §3.8.2 的 8 点：`:10-11` docstring、`:20-48` 新增 `parse_headwords`、`:72-77` 参数 `--official`/`--base`、`:81-88` `syllabus`/`official`、`:105-106` 只取 cet 标签、`:112-127` `stage_from_list` 与令牌、新步骤 2b、`:147,150-151` 元组与排序、`:157-171` 统计、`:191,196` `make_record`、`:201-219` `ATTRIBUTION` |
| `scripts/pack_seed.sh`、`Makefile:93-98` | `make seed` 加 `OFFICIAL_DIR`/`BASE_SEED` 变量；macOS 的 `zcat` 问题另记 |
| `ATTRIBUTION.md`（根）`:14,21,25-30` | 记录数、阶段归属说明、来源表（删 mahavivo 中考/高中两行，加 5 个官方文件） |

### 4.2 后端

§3.5 表中的全部位置：`schemas.py:10,25,26,51,52,56-61,65,488,708,1335`；`seed.py:7,43,47-68,204-208`；`services/words.py:39,576,590-595`；`services/ecdict.py:28,173-177`；`routers/vocab.py:78`；`services/bank.py:85-86`；`security.py:613`；`ai/prewarm.py:32-33`；`ai/content.py:48-49`；`ai/prompts/content_system.txt:1`（可选，连带 `docs/CLAUDE_INTEGRATION.md:211`）；`scripts/eval_provider.py:107`；`scripts/smoke.py:352,614`。

### 4.3 契约与前端

§3.6 表中的全部位置：`frontend/src/api/types.ts:5-6,37,45`；`components/word/StageChips.tsx:1,7-9`；`i18n/zh.ts:25,28-29,86`；`pages/WelcomePage.tsx:30-42`；`pages/ScreenPage.tsx:20`；`pages/VocabPage.tsx:29,232`；`pages/AdminPage.tsx:36`；`components/ui/ui.css`（媒体查询）；12 处测试夹具。

### 4.4 文档

| 文件 | 行 | 改什么 |
|---|---|---|
| `docs/API.md` | `155, 160, 167, 169, 187, 230, 239-240, 271, 279, 286, 459-460` | §3.6 所列 |
| `docs/FRONTEND.md` | `50`（角色列表加 小学生）、`54-56`（筛词/词库页签）、`89`（StageChips 行）、`147`（§5.5 开关说明：最低阶段不显示）、`231-235, 292`（§8 镜像块逐行同步 `zh.ts`） |
| `docs/DESIGN.md` | `32`（引导多选）、`40`（"four stage tabs" → five）、`72`（§0.3 术语表：`小学 / 初中 / 高中 / 四级 / 六级`，`xs / zk / gk / cet4 / cet6 (stage index 1–5)`，**绑定**）、`186`（`stage_min` 1–5；加「当前 schema = 0001 + 0008 + 0010 + 0011」）、`202`、`209`（验收数字）、`321-322`、`330`（角色预设）、`§3.2` 新增来源令牌表、`§6.3` 注历史快照索引口径 |
| `docs/CLAUDE_INTEGRATION.md` | `211`（若改提示词第一句）、`234-235` 示例可不改 |
| `docs/TASKS.md` | `173-175` 验收常量按新 `stats.json` 重写 |
| `docs/DEPLOY.md` | `§10` 加一句「0011 是 stop-first 重建迁移；迁移后可 `VACUUM`」 |
| `README.md` | `3, 5, 9, 103`（阶段列表与计数） |
| `docs/qa-frontend.md` | `36, 42`（人工用例：角色 5 个、页签 6 个、数字） |
| `docs/P0_STATUS.md:36` | 历史记录，可不改 |

### 4.5 测试（详见 §5）

---

## 5. 测试与验收

### 5.1 一定会红的已有测试（按 `make test` 顺序：pytest → `check_contract.py` → tsc → vitest → build）

| 测试 | 原因 | 处理 |
|---|---|---|
| `backend/tests/unit/test_api_schemas.py:32-39 test_stage_mapping_roundtrip` | 映射 `[1,2,3,4]`、`index_to_stage(5)` 应抛、`STAGE_NAMES_ZH` 等式 | 改为 5 阶段；`index_to_stage(6)` 抛 |
| `tests/integration/test_vocab.py:69-70,73,76,111` | `/api/stages` 4 行、索引 `[1,2,3,4]`、中文名、`stage_min == 4` | 5 行、`[1,2,3,4,5]`、cet6 增量 `stage_min == 5` |
| `test_vocab.py:153-161` 难度排序 | `COALESCE` 表达式变 | 断言改为 `difficulty + 1` 键 |
| `test_onboarding.py:98,120,139` | 默认 `current_stage == 3 / stages_json '["cet4","cet6"]'`、`'cet4' stored as 3`、`zk` 存 1 | 默认 `1 / '["xs","zk"]'`、cet4 存 4、zk 存 2 |
| `test_settings.py:57-58,79,89,112,124` | 默认 `["cet4","cet6"]`/`cet4`；gk 存 2 | 默认 `["xs","zk"]`/`xs`；gk 存 3；`:112` 的用例（「存的 stages 是 cet4/cet6」）要改前提 |
| `test_security.py:315`、`test_auth.py:82` | 新用户默认 | `["xs","zk"]` / `xs` |
| `test_screen.py:116,129-133` | 夹具 `current_stage=4` 是 cet6 的旧索引；`stage=zk` 的顺序断言 | `current_stage=5`；若 `mini_seed` 加了 `xs`，`be/a/go` 仍 `stage_zk=1`（三级含二级），断言不变 |
| `test_batches.py:127` | 注释「cet4 (stage_min 3)」与夹具 `current_stage` | 夹具 +1 |
| `test_seed.py:90-100` | `abandon` `(0,1,1,1,2)` → 五元组 `(0,0,1,1,1,3)`、`absolutely` 3→4、`email` 1→2、`ought to` 4→5、`a` 1→（若标 xs 则 1） | 按 §5.2 的夹具更新 |
| `test_seed.py:339-353 @full_seed` | 验收常量 | 新 `stats.json` |
| `test_words_resolve.py:279,346,478` | ECDICT cet6 → `stage_min` 4→5；`WordBrief.stage_min` 2→3 | 改常量 |
| `test_reports.py:29,87` | 手工行 `stage_min: 2`（gk 旧索引）与断言 | 改 3 |
| `test_history.py:112` | `Stats.stages` 集合 | 加 `xs` |
| `test_content_apply.py:255`、`test_runner.py:27` | `prompt_entry` 的 `stages` 中文列表（若 `go` 标 xs 则多「小学」） | 按夹具 |
| `test_db.py:41-59` | 25 张表、`shipped_migrations()` 列表自动含 0011；不红，但 §5.2 要加 0011 升级测试 |
| `scripts/check_contract.py` | `Stage`/`StageIndex` 两边不一致即硬失败 | 同一提交改两边 |
| `npm run typecheck` | `Record<Stage,…>` 缺键：`StageChips.tsx:8-9`、`WelcomePage.tsx:42`、`ScreenPage.tsx:20`、`zh.test.ts:56`；`zh.stages[s]` 缺 `xs` | 加键 |
| `zh.test.ts:67-83`、`zh.contract.test.ts:62-83` | `zh.ts` 与 `FRONTEND.md §8` 不镜像 | 同一提交改文档 |
| `scripts/smoke.py:352,614` | 4 阶段钉死 | 改 5 |

### 5.2 要新增/扩展的测试

- `tests/unit/test_db.py`：仿 `:282-310` 加 `test_upgrade_0011_renumbers_stages_and_rebuilds_tables`：从 0001 基线建库，插入带历史的用户（`_seed_user_with_history` + 一行 `current_stage=3`、若干 `words` 行 `stage_min` 1..4 与 NULL、一个 `user_words`），跑 `run_migrations` → 断言 `(11,'primary_stage')` 已应用、`current_stage` 4、每行 `stage_min` +1 且 NULL 保持、`stage_xs` 列存在且为 0、子表行数不变、`v_bank` 可查、`sqlite_master` 中 `words` 含 `BETWEEN 1 AND 5`、`user_settings` 含 `DEFAULT '["xs","zk"]'`、`kv.seed_version` 为空、二次运行幂等。另加一条「`current_stage=0` 被拒」。
- `test_seed.py`：`mini_seed.jsonl` 给 `a, apple, book, cat, dog, happy, water` 等二级词加 `"xs"`（并把 `sources` 改成新令牌），断言 `word(conn,"apple")["stage_xs"] == 1 and stage_min == 1`、`abandon` 为 3；加「`stages: []` 记录导入后 `stage_min IS NULL` 且所有旗标 0」（已有类似断言 `:98` 要反转）；加「重导把旧的 `stage_zk=1` 行按新记录清零」——这是 §3.8.1 携带规则依赖的覆盖语义。
- `test_words_resolve.py`：ECDICT 条目 `tag="zk"` 不再产生旗标（`stage_min IS NULL`）；`tag="cet4"` → `stage_cet4=1, stage_min=4`。
- `test_vocab.py`：`/api/stages` 第一行是 `xs`；`stage=xs&new_only=1` 等于 `stage=xs`（最低阶段）；难度排序的新表达式。
- `test_admin_ops.py`：`prewarm {"stage": "xs"}` 202。
- `test_api_schemas.py`：`VocabQuery(stage="xs")`、`ScreenNextQuery(stage="xs")`、`PrewarmRequest(stage="xs")` 合法；`"xx"` 仍非法。
- 前端 vitest：新增 `StageChips.test.tsx`（5 个 chip 顺序、`stageMin` 高亮用新索引）；`WelcomePage.test.tsx` 加 `ROLE_PRESETS` 每个 `current ∈ stages` 与 `TABS.length === STAGE_ORDER.length + 1`（`[frontend-stages-27]` 指出这两处今天没有回归保护）。
- `scripts/check_contract.py` 跑一次（`make check-contract`）。

### 5.3 验收脚本（替换 `TASKS.md:168-180` 的数字部分；常量在新种子定稿后由 `stats.json` 填入）

```python
import sqlite3, os; c = sqlite3.connect(os.environ["WD_DB_PATH"]); q = lambda s: c.execute(s).fetchone()[0]
assert q("select count(*) from words where source='seed'") == <stats.total_words>          # ≥ 9,162：种子只增不减
assert q("select count(*) from words where stage_xs=1") == 505
assert (q("select count(*) from words where stage_zk=1"), q("…stage_gk=1"), q("…stage_cet4=1"), q("…stage_cet6=1")) == (<per_stage>)
assert [q(f"select count(*) from words where stage_min={i}") for i in (1,2,3,4,5)] == [<first_stage>]
assert q("select count(*) from words where stage_min is null and source='seed'") == <no_stage>
assert q("select count(*) from words where stage_min is not null and stage_xs+stage_zk+stage_gk+stage_cet4+stage_cet6 = 0") == 0
assert q("select count(*) from words where stage_min is not (case when stage_xs=1 then 1 when stage_zk=1 then 2 when stage_gk=1 then 3 when stage_cet4=1 then 4 when stage_cet6=1 then 5 end)") == 0
assert q("select count(*) from user_settings where current_stage not between 1 and 5") == 0
assert q("select count(*) from schema_migrations where version=11") == 1
```

HTTP 验收：`GET /api/stages` 返回 5 行且 `index == [1,2,3,4,5]`；`GET /api/vocab?stage=xs` 的 `total == 505`；`GET /api/settings` 对两个老用户分别返回 `cet4` / `zk`；新注册用户在欢迎页看到「小学生」并默认勾选 小学 + 初中。

### 5.4 在 `live-copy.db` 私有拷贝上排练

- 已做：`scratchpad/design-stage-model-minimal/rehearse_0011.py <dir> <live-copy.db> <0011.sql>`，用 `.venv/bin/python -I`，把仓库 `migrations/` 复制到临时目录再加入 0011，跑 `wd.db.run_migrations`（结果见 §3.4）；同一脚本还在空库上从 0001 跑到 0011。
- 上线前再做一次（代码改完后）：① 复制线上库到私有目录（服务停止后 `cp`，或用 `wd backup` 的产物解压）；② `WD_DATA_DIR=<私有目录> WD_DB_PATH=<拷贝> .venv/bin/wd migrate`；③ `WD_SEED_PATH=<新种子> .venv/bin/wd import-seed`；④ 跑 §5.3；⑤ 用拷贝数一遍「两个老用户学过的词里有多少落到无阶段」：`select uw.user_id, count(*) from user_words uw join words w on w.id=uw.word_id where w.stage_min is null group by 1`。
- 排练**必须**用 `.venv/bin/python`/`wd` 而不是 `/usr/bin/sqlite3`（后者 `legacy_alter_table=1` 会让缺少 `DROP VIEW` 的错误 SQL 看似通过，`[verify stage-model-13]`）。

---

## 6. 上线与回滚（Mac，launchd；对应 `docs/DEPLOY.md §10` 的 Linux 流程）

前提：本机布局见记忆文件 `macos-local-install`——数据目录 `/Users/sqin/word-dance-data`，服务 `~/Library/LaunchAgents/com.word-dance.server.plist`（`wd serve` 启动时自动跑迁移并先做快照），没有 `install.sh`/`systemctl`。所有 `wd` 命令需 `export WD_DATA_DIR=/Users/sqin/word-dance-data`。

1. **预检**（不停机）：新提交上 `make test` 全绿（Mac 上 `test_deploy_files.py` 19 个与 `test_config.py::test_defaults_without_environment` 按已知原因失败除外）；§5.4 排练通过；确认没有 `claude` 调用在飞（管理页任务列表为空或等它结束）。
2. **停服务**：`launchctl bootout gui/$(id -u)/com.word-dance.server`；确认 `curl --noproxy '*' http://127.0.0.1:8000/api/health` 连接被拒。
3. **手工快照**：`.venv/bin/wd backup`（除了运行器自动写的 `backups/pre-migrate-10-to-11.db.gz` 之外再留一份带时间戳的）。
4. **切代码**：`git checkout <新提交>`；依赖无变化（`make setup` 可跳过）。
5. **迁移**：`.venv/bin/wd migrate` → 期望输出 `applied 0011_primary_stage`，并在 `backups/` 看到 `pre-migrate-10-to-11.db.gz`。
6. **导种子**：`.venv/bin/wd import-seed` → 期望「N inserted, M updated」（`kv.seed_version` 已被 0011 清空，不会 no-op）；N ≈ 新增词头数，M 是旗标变化的行数。
7. **验收**：§5.3 的 SQL 对线上库跑一遍（只读 `sqlite3 -readonly`）。
8. **可选 `VACUUM`**（服务仍停）：`.venv/bin/python -c "import sqlite3; sqlite3.connect('/Users/sqin/word-dance-data/word-dance.db').execute('VACUUM')"` —— 9.4 MB → 5.5 MB；跳过也无害。
9. **发布前端快照**（同一提交）：`cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build -- --outDir $D/frontend-releases/<sha>.new --emptyOutDir`；`mv <sha>.new <sha>`；`ln -sfn frontend-releases/<sha> $D/frontend.tmp` 后用 `python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"`（BSD `mv` 无 `-T`）。
10. **起服务**：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist`（或 `kickstart -k`）；`curl --noproxy '*' http://127.0.0.1:8000/api/health`；登录后 `GET /api/stages` 5 行；设置页 5 个阶段 chip、两个老用户的主攻阶段分别显示 四级 / 初中；词库页 6 个页签在手机宽度不溢出；注册一个测试账号看欢迎页的 5 个角色与默认勾选。
11. **回滚**（仅在第 10 步失败时）：`launchctl bootout …`；`.venv/bin/wd restore /Users/sqin/word-dance-data/backups/pre-migrate-10-to-11.db.gz --yes`（`restore` 要求服务已停并会 `wal_checkpoint(TRUNCATE)`，`DEPLOY.md:361`）；`git checkout 75df534`；前端 symlink 指回上一个快照目录（`frontend-releases/` 保留最近两个）；`bootstrap`。**没有「只回代码」的回滚**：新库里任何 `current_stage=5`（六级用户）或 `stage_min=5` 都会让旧代码 `index_to_stage` 抛 `ValueError` → 500（`schemas.py:65`、`security.py:597`）；回滚意味着丢掉迁移后产生的学习记录，所以第 2–10 步一气呵成，选在无人学习的时段。

停机时长：迁移 0.04 s + 导种子 0.2 s + 前端构建（可在停服务前做好 `<sha>.new`）≈ 1 分钟以内。

---

## 7. 风险、未决问题、工作量

### 7.1 风险

| 风险 | 概率/影响 | 缓解 |
|---|---|---|
| 词表任务交付的词头文件格式/规模与 §3.8.3 不符（并列未拆、屈折形式、缩写无点、含词组） | 中 / 中：`missing_from_ecdict` 变多、`mr` 与 `mr.` 并存成重复词条（`[seed-pipeline-12]`） | 构建后检查 `stats.json.missing_from_ecdict` 与「新增 lemma 清单」；对 `Mr/Mrs/Ms/PE` 一类在词表里统一为带点形式 |
| 忘记携带 `--base`，新种子少了旧 lemma | 低 / 高：旧词带着 `stage_min=2`（初中）活下来 | `build_seed.py` 把 `--base` 设为必填并在 `stats.json` 输出 `carried_forward` 计数；验收 §5.3 第 7 条（`stage_min` 与旗标一致）能抓到一部分，另加一条「线上 `source='seed'` 的 lemma 全部在种子里」的脚本检查 |
| `ecdict.py:177` 漏改 | 低 / 高：用户自添的 ECDICT 四级词被标成小学（`stage_min=1`）并排在所有推荐之前 | `test_words_resolve.py` 新断言（§5.2） |
| 旧代码与新库共存（回滚代码不回滚库） | 低 / 高：六级用户 500 | §6 第 11 步明文「没有只回代码的回滚」 |
| 提示词改动与 `CLAUDE_INTEGRATION.md §5.1` 不同步 | 中 / 低：`test_schemas.py:122-126` 直接红，不会漏到线上 | 同一提交改两处或干脆不改提示词（`STAGE_ZH` 是必改项，提示词文本是可选项） |
| 6 个页签在 360/375 px 的实际渲染与算术不符 | 中 / 低：最右页签被裁 13 px 要靠横滑发现 | 上线前 DevTools 复核；备用方案去掉 `fill`（与生词库一致） |
| 小学词的 AI 内容按成人提示词生成（例句 8–20 词、`EXAMPLE_EN_MIN=15`） | 高 / 中：这不是本切片的范围，但本切片把「小学」标签送进提示词后会立刻暴露 | Q7/Q9 的提示词工作应与本切片同一发布窗口，至少先于任何面向小学生的邀请 |
| `difficulty + 1` 表达式与「小学词 difficulty=1」的并列 | 确定 / 低：仅词库页难度排序 | 写进 `API.md:169` |
| 文件膨胀到 9.4 MB 不自动回收 | 确定 / 可忽略 | §6 第 8 步可选 `VACUUM` |

### 7.2 被封死或变贵的未来路径（诚实清单）

1. **每用户「上海/全国」方案**：本设计没有方案维度。日后要做，至少需要：`word_stage_tags(word_id, scheme, stage)` 或一组 `stage_sh_*` 列、第二个 `stage_min`（上海方案的最低阶段）、`user_settings.scheme`、`/api/stages?scheme=`、6 处选词模板与 5 个 `stage_min` 消费点按方案取列、前端数据驱动页签（`[stage-model-16/17/18]`）——即 INDEX 路线 B 的全部工作加第二次迁移。本设计保留的只是回填所需的来源令牌（§3.3）。
2. **「拓展/超纲」层**：不存在。掉出所有表的词是「词典词」（无阶段），不可被筛词/推荐；mahavivo 两表的成员关系不再保留在数据库里（git 历史有）。要补一个拓展层等于加第 6 个阶段：追加在末尾（`ext=6`）便宜但语义上「比六级更高」不成立；插在中间又是一次重编号 + 表重建。
3. **再加阶段的成本固定为「一次表重建」**：`stage_*` 布尔列模式下每个新阶段 = 新列 + `SEED_COLUMNS` + `_INSERT_WORD_SQL` + `word_columns` + 10 份常量 + 契约；CHECK 范围每次都要重建两张表（毫秒级，但必须停机）。
4. **阶段仍是硬编码而非数据**：10 份后端常量、5 个前端文件、`/api/stages` 固定 5 行；没有 `stage_defs`，中文名改一次要动 `schemas.STAGE_NAMES_ZH`、`content.STAGE_ZH`、`zh.ts`、`FRONTEND.md §8`、`DESIGN.md §0.3` 五处。
5. **教材/年级/单元顺序**：种子 15 个字段里没有位置（`[seed-pipeline 未解决 8]`）；小学词仍按成人语料 `frq` 排序（`crayon/panda/blackboard` 排最后，`[seed-pipeline-23]`）。这是产品很快会撞到的墙，但不属于本角度。
6. **6 级 `difficulty`**：仍需 ≈12 文件的契约变更；本设计用 `+1` 把问题推迟而不是解决。
7. **上海初中 331 个词组、2025 高中 117 个国家附表词、考试院 200 个高中补充词**：都只是词表更新（改 `data/lists/`、重建种子、`import-seed`），模型无需再变——这些路径**没有**被封死。

### 7.3 未决问题

1. `xsFull` 的中文全称（「小学（课标二级）」vs「小学（1–5 年级）」）——文案决定，影响 `zh.ts`/`FRONTEND.md §8`/`DESIGN.md §0.3` 三处。
2. 是否给现有「只选初中」的用户自动加上小学（本设计：否，见 §3.7）。
3. 2025 高中表的 117 个国家/国籍附表词与上海 331 个词组是否入库（本设计：本轮不入；由词表任务与产品决定）。
4. 提示词第一句是否现在就加「小学」并同步 `CLAUDE_INTEGRATION.md:211`（本设计：建议加，不 bump `PROMPT_VERSION`；最终归 Q7/Q9）。
5. `build_seed.py` 在哪台机器跑：Mac 需手工下载 216 MB 的 `stardict.db` 并绕开 BSD 工具差异；若将来有 Linux 盒子（Lighthouse），在那里跑并提交归档更省事。
6. 线上两个用户已学过的词中有多少会变成「词典词」——只能在上线排练时用 §5.4 的查询回答（取决于最终词表）。

### 7.4 工作量（人日）

| 项 | 人日 | 说明 |
|---|---|---|
| 0011 迁移 + 后端常量/ecdict/vocab 改动 + `test_db` 升级测试 | 1.0 | SQL 已排练；后端全是常量级 |
| `build_seed.py` 改造（官方词头读取、携带规则、令牌、ATTRIBUTION）+ 在有 `stardict.db` 的机器上重建种子 + `stats.json`/`ATTRIBUTION.md` | 1.0 | 不含词表任务的清单定稿；含一次 216 MB 下载 |
| 前端 7 文件 + CSS + 12 处夹具 + 2 个新测试 | 0.5 | |
| 后端测试更新（§5.1 的 ≈15 个文件）+ 新测试（§5.2） | 1.0 | 大头是逐个常量的机械更新 |
| 文档（API/FRONTEND/DESIGN/TASKS/README/ATTRIBUTION/CLAUDE_INTEGRATION/qa） | 0.5 | 镜像规则让这部分不能偷懒 |
| 排练、上线、验收、回滚预案 | 0.5 | |
| **合计** | **4.5** | 词表任务、配图/提示词切片另计 |
