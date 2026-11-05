# 阶段模型与地区维度 — 设计稿（角度：学习者优先）

基线：仓库 `/Users/sqin/word-dance` `main @ 75df534`；线上库只读副本 `scratchpad/live-copy.db`（9,162 词，2 个用户，`schema_migrations` 已到 10）；日期 2026-11-05。调研依据：`INDEX.md`（25 条跨切片结论、Q1–Q9）与 `facts/`、`verify/` 各切片；代码位置全部按 75df534 本人重新打开核对。

本稿自己跑过的东西（只读，脚本在 `scratchpad/stage-model-learner-first/compute.py`，用 `python3.12 -I` 解析下载的官方词头清单并以 `?mode=ro` 打开 `live-copy.db`）：用 A1/A2 的词集定义对现库做一次「重标排练」，得到每个阶段的进出词数、新的 `stage_min` 分布、两名线上用户生词库受影响的行。这些数字下文标注为 **[排练]**；来自 INDEX/facts 的核验数字标注条目号。两者口径略有差异（排练把官方清单里的英美拼写变体与括注变体都算进去，如 `colour (color)`、`Mr (Mr.)`，所以三级 ∩ 库 1,639 比 [verify provinces-25] 的 1,592 多 47），方向一致。

---

## 1. 一页结论

**决定了什么**

| # | 决定 | 一句话理由 | 代价 |
|---|---|---|---|
| D1 | 阶段枚举 4 → 5：`xs`（小学）/ `zk` / `gk` / `cet4` / `cet6`；整数索引**重编号为 1..5**（xs=1 … cet6=5），映射改为显式字典而不是元组位置 | 学习者看不到索引，但索引决定推荐词顺序、「仅本阶段新增」与芯片高亮；只有「索引 = 顺序」且无 0 值的编码能让这三处在不改一行 SQL 的情况下对小学生正确；现在线上只有 2 个用户、49 行 difficulty、4 条批次快照，重编号代价是历史最低点 [verify seed-pipeline O3] | 一次停机迁移 0011（重建 `user_settings` 与 `words`，毫秒级 [stage-model-12]）；`API.md`/`DESIGN.md`/`TASKS.md` 全部索引数字改写；回滚只能恢复快照 |
| D2 | `difficulty` 1–5 尺子**不动**（提示词、3 份 JSON schema、`Difficulty` 字面量、DB CHECK 全不改），只把 `vocab.py:78` 的排序兜底改为 `COALESCE(w.difficulty + 1, w.stage_min, 6)` | Claude 的 1 = 初中 恰好对应新索引 2，整体平移一格即可对齐两把尺子；小学词没有 difficulty 值，回落到 `stage_min = 1` 排在最前，正是小学生想要的 | 一行 SQL + `API.md:169` 一句话 + `test_vocab.py:153-161` |
| D3 | 词的阶段成员仍用 **布尔列 + `stage_min`**（新增 `stage_xs`），不建 `word_stage_tags`/`stage_defs` 表；「上海/全国」**不做维度**，「拓展/超纲」**不做阶段**；每词来源用 `words.sources` 的新 token 词汇表保留全部信息（`cs2022:l2`、`cs2022:l3`、`sh2020`、`cs2025:hs0/hs1/hs2`、`legacy:zk`、`legacy:gk`、`cet4`、`cet46`、`cet6`、`ecdict`） | 五类用户的旅程里没有一个需要「同一词在两套方案里属不同阶段」：初中词集取「上海 2020 表 ∪ 国家三级」的并集后，上海学生与全国学生看到的是同一个超集，多出的词是他们高中前一定会遇到的词（上海独有 415 词中 259 个在国家高中表 [B5]）；上海高中表根本没有机读源 [B7]，做维度只能做半个；`sources` 列今天无任何读取者 [stage-model-15]，重定义它零代价 | 加维度时需再做一次迁移（届时从 `sources` 回填，不必重导种子） |
| D4 | 老词处理：**重标不剔除**。按 A2/A3 重定义后仍在库里但不属任何官方阶段的 248 词（[排练]：旧 zk 首 76 + 旧 gk 首 172）保留为词典条目（`stage_min NULL`，只在「全部」页签与搜索中出现，不进推荐词与预生成），`sources` 带 `legacy:zk/gk` | 学习者已持有的词一个不丢（`user_words` 是每用户表，种子导入从不触碰 [stage-model-19]）；新学习者不再被推送旧考纲的超纲词（C1/C2）；信息保留，将来要做「拓展」层只需加一列 | 词库「全部」里多 248 个无阶段词；`prewarm all` 范围从 9,162 降到 8,914 |
| D5 | 新用户默认改为 **`stages_json DEFAULT '["xs","zk"]'`、`current_stage DEFAULT 2`**（初中生预设），`bank.py` 的复制值同改；引导页加「小学生」角色（`xs: ['xs'] / xs`），「初中生」预设改为 `['xs','zk'] / zk`（与「高中生 → 初中+高中」的「向下含一级」模式一致）；线上 2 个用户：`stages_json` 原样保留、`current_stage` +1，写死在 0011 里 | 一个上海小学生打开欢迎页今天默认勾着「大学英语四级/六级」[verify frontend-stages-14]；初中是五四学制里人数最多的四年 | 8 处测试断言的默认值要改 |
| D6 | 种子语义：阶段标志的**唯一真相是种子文件**；0011 把 `kv.seed_version` 删掉，强迫启动时重导新种子；旧词不从种子里删（导入本来就不删词 [stage-model-19]），新增官方词头 ≈ 36–40 条（上海表真缺 14 [verify shanghai-secondary-19]、三级/3100 缺约 25 [排练]） | 「迁移建列 → 导种子写标志」的顺序 `main.py:482-485` 已保证；删 `seed_version` 让「代码到位但种子没换」这种半套部署在启动 0.2 s 后自动纠正 | 需要一个就地重标种子的脚本（不依赖 851 MB 的 `stardict.db`，Mac 上可跑） |

**代价合计**：约 6.5 人日（第 7 节分项）；一次 < 1 s 的停机迁移；文件从 5.6 MB 涨到 ≈ 9.4 MB（重建后不自动 VACUUM [verify stage-model 遗漏 4]）。

**对五类用户的直接效果**（[排练]，最终数字以词表任务交付的清单为准）：

| 用户 | 上线前 | 上线后 |
|---|---|---|
| 上海三年级小学生及家长 | 没有「小学」；默认勾四六级；初中 tab 2,099 词 | 「小学生」角色 → 目标阶段「小学」500 词（课标二级 505 词头，库中 500 + 4 个句点缩写别名）；词库/筛词各多一个「小学」页签；学习卡只显示自己目标阶段内的芯片（第 3.8 节） |
| 初二学生 | 初中 = 旧全国中考表 ∪ ECDICT zk，2,099 词，其中 706 不在上海表 [B4] | 初中 = 上海 2020 表 ∪ 国家三级，2,015 词（去 496、进 412）；「仅初中新增（不含小学）」1,515；小学词排在推荐词末尾（主攻阶段优先，DESIGN §6.3 不变） |
| 高三学生 | 高中 = 旧「高考 3500」谱系 ∪ ECDICT gk，3,829 词，31.2% 不在国家表 [C2] | 高中 = 国家高中课标 2025 修订 3100，3,134 词（去 1,140、进 445）；「仅高中新增（不含初中）」1,235 |
| 四六级用户 | cet4 4,722 / cet6 7,671 | **集合不变**；但 412+445 个词的芯片多了「初中/高中」标签，「仅四级新增」1,577 → 1,807、「仅六级新增」3,694 → 3,857（低阶段不再抢占） |
| 管理员 | 预生成 4 个阶段 + all | 预生成多「小学」；`all` = 8,914；`sources` token 可审计每个词为什么在某阶段；`GET /api/stages` 5 行 |

---

## 2. 对照假设 A1–A6 的偏离与理由

| 假设 | 采纳情况 | 偏离/补充 | 理由 |
|---|---|---|---|
| A1 小学 = 国家 2022 课标二级 505 词 | 采纳 | 二级词在库 500/505 [verify shanghai-primary-21]；`Mr/Mrs/Ms/PE` 以别名映射到库中 `mr./mrs./ms./p.e.`；`excited` 作为独立词头新增（课标把它单列为词，ECDICT 有独立条目），而不是把标志打到 `excite` 上 | 不新增词只补标志；别名映射避免 `mr` 与 `mr.` 两条 lemma 并存的重复词条陷阱 [seed-pipeline-12] |
| A2 初中 = 上海 2020 表 ∪ 国家三级；高中 = 2025 修订 3100；200 补充词暂缺 | 采纳 | 补充：**阶段标志按官方体例向上累计**——二级 ⊂ 三级 ⊂ 3100 是课标原文（「含二级词汇 505 个」「含义务教育阶段 1600 个」[provinces-1/4]），所以 `stage_xs=1 ⇒ stage_zk=1 ⇒ stage_gk=1`，[排练] 验证 `xs − zk_new = ∅` | 累计才能让「初中生只勾初中」仍覆盖小学词；DESIGN §3.1 本来就写「cumulative as in the sources」 |
| A3 只用官方词头；mahavivo 中考/高中两表退出阶段依据；有道系只作核验 | 采纳并延伸 | **运行时 ECDICT 直查创建的词不再从 ECDICT 的 `zk/gk` 标签拿阶段**（`ecdict.word_columns` 只保留 cet4/cet6 标签与 `stage_xs=0`）；cet4/cet6 的定义（ECDICT 标签 ∪ 2016 大纲表）不变 | 官方清单的全部词头都已进种子，所以一个「只在 ECDICT 里带 zk 标签」的词按定义在官方清单之外；cet 定义没变，不碰 |
| A4 不按省份分层；是否双方案/拓展层由设计决定 | 采纳 | 决定：**都不做**（D3/D4），但 `sources` token 完整保留「上海表 / 国家三级 / 3100 星级 / 旧表」归属 | 见第 3.4 节：维度的每个受益场景都能用并集 + token 覆盖，而成本是 6 处 SQL 模板和整套前端页签契约 |
| A5 配图 | 不在本线范围 | 只提供一个接口：`WordBrief.stage_min = 1` / `stages ∋ 'xs'` 即「小学词」，配图线可据此选插画链 | — |
| A6 新用户默认 K-12；2 个用户的迁移规则写死 | 采纳 | 默认 = 初中生预设 `["xs","zk"]`/2，而不是小学；2 个用户 `stages_json` 不动、`current_stage` +1（1→2、3→4）；不给任何人自动加 `xs` | 初中是五四学制里最大的学段；用户的目标阶段是他们自己的选择；小学词本就包含在初中池里（累计），不加 `xs` 不丢词 |

---

## 3. 详细设计

### 3.1 从五类用户旅程推导模型需求

每个模型决定都要能追溯到下面某一行。

| 旅程环节 | 小学生/家长 | 初二 | 高三 | 四六级 | 管理员 | 模型需求 → 决定 |
|---|---|---|---|---|---|---|
| 注册默认（`security.py:662-664` 只插 `user_id/next_push_at/updated_at`，其余吃 DDL DEFAULT [verify stage-model 遗漏 1]） | 不应默认四六级 | 默认落在初中最合适 | 可点角色 | 可点角色 | — | DDL DEFAULT 改 → 必须重建 `user_settings`（SQLite 不能 ALTER DEFAULT）→ **与 0011 合并**（D5） |
| 引导页角色（`WelcomePage.tsx:30-38`） | 需要「小学生」 | 「初中生」应含小学 | 不变 | 不变 | — | 角色是前端常量，阶段码必须稳定 → 码名 `xs` 固定进 `Stage` 字面量 |
| 词库页页签（`VocabPage.tsx:29`） | 「小学」页签 500 词 | 「初中」页签 | 「高中」页签 | 不变 | — | 每阶段一个布尔列 `stage_<code>`，6 处 SQL 模板自动覆盖 [stage-model-5] → **保留布尔列**（D3） |
| 「仅本阶段新增」（`vocab.py:54-56` `stage_min = idx`） | 小学 = 全部 | 初中 − 小学 | 高中 − 初中 | 四级 − 高中 | — | `stage_min` 必须等于最低阶段的索引且索引单调 → **重编号 1..5**（D1） |
| 学习卡芯片（`StageChips.tsx:26-32`，高亮 `stageMin === STAGE_INDEX[stage]`） | 小学词带 小学/初中/高中/四级 四个芯片是噪音 | 同上 | — | 看到「初中」芯片出现在四级词上（412 个） | — | 芯片只显示用户目标阶段 ∪ 最低阶段（第 3.8 节）；高亮逻辑不变 |
| 筛词/推荐排序（`screen.py:34-36`、`batches.py:60` 数值距离） | 主攻小学：小学 0、初中 1、高中 3… | 主攻初中：初中 0、高中 1、小学 2 | — | — | — | 距离算式只在「索引 = 顺序」时正确 → 排除「追加 5」；0 值会被 `screen.py:44`、`batches.py:272,698` 的 `or DEFAULT` 吞掉 → 排除「小学 = 0」（D1） |
| 预生成（`prewarm.py:32-39`） | — | — | — | — | 按阶段预生成小学内容 | `STAGE_COLUMNS` 加 `xs`；`all = stage_min IS NOT NULL` 自动排除 248 个课标外词（D4） |
| AI 例句（`content.py:88` 每词中文阶段标签） | 提示词里出现「小学」 | — | — | — | — | `STAGE_ZH` 加 `xs: 小学`（否则 `KeyError` 整组失败 [verify ai-prompts-stages 遗漏 1]） |
| 老用户的词集变化 | — | 初中 tab 从 2,099 变 2,015 | 高中 tab 从 3,829 变 3,134 | 芯片变多 | 看 `sources` 解释 | 每用户数据不动；阶段是共享词库属性；变化只体现在计数与芯片（第 3.10 节） |

### 3.2 阶段枚举 4 → 5 与索引编码（Q1）

**结论**：码名 `xs`（小学，与 `zk/gk` 同构的拼音首字母）；`STAGE_ORDER = ("xs","zk","gk","cet4","cet6")`；索引 `{"xs":1,"zk":2,"gk":3,"cet4":4,"cet6":5}`，**现有 `stage_min`/`current_stage` 全部 +1**；`StageIndex = Literal[1,2,3,4,5]`。

**四案比较**（INDEX Q1 / [stage-model-9] / [verify frontend-stages-12]）：

| 方案 | 学习者可见的正确性风险 | 代码改动 | 数据/契约改动 | 判定 |
|---|---|---|---|---|
| a 重编号 1..5 | 无：`stage_distance`（`screen.py:35`、`batches.py:60`）、`new_only`（`vocab.py:55`）、`COALESCE` 排序（`vocab.py:78`）、芯片高亮（`StageChips.tsx:31`）全部按「索引 = 顺序」工作，零逻辑改动 | `schemas.py:25-26,51-52,56-67` 字面量与两个映射函数；`seed.py:208`、`ecdict.py:177` 的 `index+1` 换成字典 | 0011 里 `stage_min + 1`、`current_stage + 1`、`push_batches.settings_json` 的 `current_stage` +1；`API.md:460`、`DESIGN.md:72,186`、`TASKS.md:174` 等数字作废重写；前端 12 处 `stage_min: N` 夹具 +1 [frontend-stages-12] | **选它**：唯一不改任何排序/筛选语义的方案；文档改动是一次性的，而且现在就是文档必须重写的时刻（词集定义也变了） |
| b 小学 = 0，其余不动 | **有**：`screen.py:44` `int(s["current_stage"] or bank.DEFAULT_CURRENT_STAGE)`、`batches.py:272`/`:698` 同型——Python `0 or 3 == 3`，**主攻小学的用户会被静默按四级排推荐词**，受害者正是新目标用户；前端任何 `stage_min || …` 写法同样把 0 当缺失（JS 假值） | 三处 `is None` 改法 + 两个映射函数重写 + `CHECK BETWEEN 0 AND 4`（仍要重建两张表 [verify stage-model-11]） | 数据不动；但契约里要写「0 = 小学」这种反直觉约定 | 排除：节省的只是 `UPDATE … +1` 两句和文档里的数字，换来一个在两种语言里都是「假值」的索引 |
| c 追加 = 5 | **有**：`stage_min` 不再是「最低阶段」，距离算式把小学当最难阶段，`COALESCE(difficulty, stage_min, 5)` 把小学词排最后；`seed.py:208` 的 `stages[0]` 取不到最低 | 三处算式改查表 CASE、`stages[0]` 改取 rank 最小 | 数据不动 | 排除：破坏现有不变量，SQL 与 Python 两边各维护一份 rank 表 |
| d 字符串码 + `stage_defs` 表 | 无 | 去掉 `stage_to_index/index_to_stage` 与 `StageIndex`；`StageInfo.index`、`WordBrief.stage_min` 类型从整数变字符串；排序要 JOIN `stage_defs.rank` 或 CASE；`check_contract.py` 联合比对与 `types.ts:5-6,45,52` 同改 | 迁移要在 `INSERT … SELECT` 里做 `CASE stage_min WHEN 1 THEN 'zk' …` 值转换 | 排除（本轮）：它唯一的独特收益是「阶段成为数据」，而第 3.4 节决定本轮不做方案维度，没有数据驱动页签的需求；改动面最大却不换来任何学习者可见的改进 |

**索引映射改为显式字典**（`schemas.py:51-67`）：

```python
STAGE_ORDER: tuple[str, ...] = ("xs", "zk", "gk", "cet4", "cet6")
STAGE_INDEX: dict[str, int] = {"xs": 1, "zk": 2, "gk": 3, "cet4": 4, "cet6": 5}   # == position + 1, asserted by a test
STAGE_NAMES_ZH = {"xs": "小学", "zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}

def stage_to_index(stage): return STAGE_INDEX[stage]                       # KeyError → ValueError as today
def index_to_stage(index): return STAGE_ORDER[int(index) - 1] if 1 <= int(index) <= len(STAGE_ORDER) else raise …
```

`seed.py:208` 与 `ecdict.py:177` 改为 `min(STAGE_INDEX[s] for s in stages)`，不再依赖「过滤后的第一个元素」。

**全称文案**：`xsFull: '小学（课标二级词汇）'`——不写「1–5 年级」（五四与六三年级切分不同 [B1]），不写考试名（小学无考试 [shanghai-primary-3]）；`zkFull/gkFull` 不变，初中集合的口径写在 `settings.sources.lists`（第 3.8 节）。

### 3.3 与 `difficulty` 1–5 尺子的关系（Q5）

**结论**：尺子不扩、不动；只改排序兜底。

- 现状 [A5]：`difficulty` 1 = 初中 … 4 = 六级、5 = beyond，写死在 `content_system.txt:11`、`consolidate_system.txt:11`、3 份 schema `enum`、`ai/models.py` 四处 `Literal`、`schemas.py:47 Difficulty`、`types.ts:73`、`0001_init.sql:195`；`vocab.py:78` 用 `COALESCE(w.difficulty, w.stage_min, 5)` 把它和 `stage_min` 当一把尺子。线上 49 行非空，44/49 等于旧 `stage_min` [ai-prompts-stages-14]。
- 重编号后旧对齐关系「difficulty k ↔ stage_min k」变成「difficulty k ↔ stage_min k+1」，**恰好是一次平移**：`_ORDER["difficulty"] = "COALESCE(w.difficulty + 1, w.stage_min, 6), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"`（`NULL + 1` 仍是 NULL，COALESCE 继续回落）。49 行数据不动，提示词不动，`PROMPT_VERSION` 不必为此提升。
- 小学词：提示词无法给出「小学」难度，Claude 会按规则给 1（初中 basic）→ 排序键 2；没有内容的小学词回落 `stage_min = 1` → 排序键 1。只影响 `sort=difficulty` 下 500 个小学词内部的先后，学习者不会察觉。扩成 6 级的 ≈12 个文件改动 [stage-model-9 1'②] 留到小学内容真的生成之后再评估（Q5 建议 a）。
- `API.md:169` 的 `sort=difficulty` 一句改写；`test_vocab.py:153-161` 的 `keys` lambda 改成 `(i["difficulty"] + 1 if i["difficulty"] else i["stage_min"] or 6, …)`。

### 3.4 词的阶段成员如何存储；「上海/全国」「拓展/超纲」是否成为维度（Q3/Q4）

**结论**：布尔列 + `stage_min`（加 `stage_xs`）；不做维度；信息进 `sources`。

**为什么不做「上海/全国」方案维度**（逐个受益场景核对）：

| 可能受益的场景 | 并集方案下的实际体验 | 维度方案的额外收益 |
|---|---|---|
| 上海初二学生按「初中」筛词 | 看到上海 2020 表全部 1,703 个库内词 + 303 个仅国家三级的词 [verify provinces-13]；后者是他们初中结束前课内也会接触的基础词（三级是全国义务教育底线） | 少看 303 个词 |
| 外省初二学生 | 看到国家三级 + 415 个仅上海词，其中 259 个在国家高中表 [B5] | 少看 415 个高中前一定会遇到的词 |
| 上海高三 | 国家 3100；上海 200 补充词没有机读源 [B7] | 无（数据不存在） |
| 教材同步（牛津上海版/新五四制沪教版） | 不在本轮；是「教材标签」不是「地区方案」[C3/provinces-27] | 无 |

维度的成本是真实的：`user_settings.scheme` 列、6 处 `f"w.stage_{s} = 1"` 模板多一个前缀 [stage-model-16]、`/api/stages` 按方案返回、前端页签改为数据驱动（`ScreenPage.tsx:31` 现在会静默丢掉未知阶段 [stage-model-18]）、`WordBrief.stages/stage_min` 失去稳定含义 [frontend-stages-22]。收益只是让两类初中生各少看三四百个「稍早遇到」的词。判定：不做。

**信息如何保留以便日后加维度**：`words.sources`（`0001_init.sql:188`，无索引、无读取者 [verify stage-model-15]，种子列、重导覆盖 [seed-pipeline-11]）改为以下 token 词汇表（空格分隔、排序）：

| token | 含义 | 来源文件（词表任务交付，名称待对齐） |
|---|---|---|
| `cs2022:l2` | 义务教育课标 2022 二级词汇表词头 | `data/lists/cs2022_level2.txt` |
| `cs2022:l3` | 三级词汇表词头（含二级） | `data/lists/cs2022_level3.txt` |
| `sh2020` | 上海市教育考试院 2020 初中英语词汇表单词部分 | `data/lists/sh2020_junior.txt` |
| `cs2025:hs0` / `hs1` / `hs2` | 高中课标 2017 版 2025 修订 附录 2：无星（义务教育 1600）/ 一星（必修 500）/ 两星（选择性必修 1000） | `data/lists/cs2025_senior.txt`（带 `*`/`**`） |
| `cet4` `cet46` `cet6` `cet6star` | 现有 CET 词表归属（不变） | mahavivo（不分发，同今天） |
| `ecdict` | ECDICT 带任一考试标签（不变） | — |
| `legacy:zk` / `legacy:gk` | 75df534 种子里该词曾带 `stage_zk`/`stage_gk`（旧中考表 ∪ ECDICT zk / 旧高考 3500 ∪ ECDICT gk） | 由重标脚本从旧记录推出 |

有了这些 token：① 将来做「上海/全国」= 加 `user_settings.region` + 从 `sources` 回填两列 `stage_zk_sh`/`stage_zk_cn`（或生成列），不必重导种子；② 将来做「拓展/超纲」层 = `legacy:*` 直接给出 1,375 个候选（[排练] 496 ∪ 1,140）；③ 将来做「高一/高二」= `cs2025:hs1/hs2`。`DESIGN.md §3.2` 的 `sources[]` 行改写为这个词汇表；0011 的新 DDL 注释里写明。

**为什么不做「拓展」阶段**：一个「拓展」页签对学习者意味着「这些词也该学」，但 1,375 个候选的来源是身份不明的旧表（`中考英语词汇表.txt`、`Highschool_edited.txt` 来源未知 [A1]）；把它们作为课标外词典条目保留（D4）比作为一个阶段呈现更诚实。

### 3.5 老词如何处理；种子语义

**[排练] 重标后的进出**（词头精确匹配 lemma；最终以词表任务清单为准）：

| 阶段 | 现状 | 新定义 ∩ 库 | 保留 | 离开 → 去向 | 新加入 ← 来源 |
|---|---|---|---|---|---|
| xs | — | 500（+ `mr./mrs./ms./p.e.` 别名 4 + `excited` 新词头 1 → 505） | — | — | 全部来自现 `stage_min=1` 的词（[verify shanghai-primary-21]：495 个 `stage_min=1`，`an/astronaut/maths` =2、`best` =3、`chore` =4） |
| zk | 2,099 | 2,015 | 1,603 | 496：189 → 仍是高中（在 3100）、231 → 只剩四/六级、**76 → 无阶段** | 412：320 原高中首、68 原四级首、24 原六级首（account, accurate, actor, adult, athlete, attitude, badminton…） |
| gk | 3,829 | 3,134 | 2,689 | 1,140：82 仍是初中、842 → 只剩四/六级、**216 → 无阶段** | 445：347 原四级首、82 原六级首、16 原初中首 |
| cet4 / cet6 | 4,722 / 7,671 | 不变 | — | — | — |

新 `stage_min` 分布（1..5）：**500 / 1,515 / 1,235 / 1,807 / 3,857 / NULL 248**（合计 9,162）。无阶段的 248 词：76 个原初中首（CD、DVD、Korea、Olympic Games、mooncake、crayon、sharpener、swimming pool…，多为专名/合成词/旧考纲产物）、172 个原高中首（bungalow、ballpoint、bathrobe、beehive、birdcage…）；**没有一个有 AI 内容或配图**，不涉及已花费。旗标组合从 15 种变 20 种；441 个小学词带 xs+zk+gk+cet4 四个标志。

**处理规则**：

1. **不从种子剔除任何词**。导入是按 lemma 的 UPSERT，从不删除 [stage-model-19]；9,162 条全部保留，只改 `stages`/`sources`。
2. **离开所有阶段的 248 词**：`stage_min = NULL`，`sources` 含 `legacy:zk|gk`。可见性不变（`is_public=1`），词库「全部」页签、搜索、添加生词、详情页都照常；推荐词（`screen.py:51-56`、`batches.py:268-273` 要求某个 `stage_* = 1`）与预生成（`prewarm.py:37-38` `stage_min IS NOT NULL`）自然排除。已经在某用户生词库里的这类词继续按 SRS 学习（线上两名用户都没有 [排练]）。
3. **降级/升级的词**：只是标志变化；`word_contents`/`word_images`/`difficulty` 不动（导入明确排除这些列 [seed-pipeline-10]）。
4. **「覆盖 20 列」的后果**：重导会把 9,162 行的词典列按新种子写一遍——新种子由旧种子就地修改而来（第 4 节 `scripts/relabel_seed.py`），词典列字节不变，`WHERE … IS NOT excluded …` 只让标志变化的行真正写入（约 2,800 行），`updated_at` 只在这些行移动。`updated_at` 变化会让这些词的 `/media/card/{id}.svg` 缓存键失效（`WORD_LIBRARY_CURATION.md §1.6`），无害。
5. **不再出现在种子里的线上词**：本轮没有（全部保留）。规则写进 `seed.py` 文档串：「种子从不删词；要下架用 `is_public=0`（见 WORD_LIBRARY_CURATION §2.4）」。
6. **新增词头**（约 36–40）：上海表真缺 14（angrily, beautifully, bund, carefully, dancer, dishonest, hot-dog, luckily, mr, mrs, politely, quietly, seafood, unforgettable [verify shanghai-secondary-19]）、三级/3100 缺约 25（kung fu, teenage, tofu, per cent, AI, app, calligraphy, Confucius, drone, lifestyle, wetland, wi-fi, pagoda, empathy, mobile phone…）、`excited`。词典字段来源：优先本机已下载的 `ecdict.csv`（66 MB，[seed-pipeline-27]：`pos` 为空、`ecdict_id` 不可复现，可接受），否则最小记录 `{"word","translation"}`；`bund`（外滩）、`Confucius` 等专名走最小记录并人工给译文。`derive_kind` 会把 `Confucius` 标为 `proper_noun`、`kung fu` 为 `phrase`（`words.py:142-151`）。
7. **屈折形式与变体**：`frightened/surprised/lost/united…` 已由 `word_forms` 覆盖 [verify shanghai-secondary-19]，不加词头；`café→cafe`、`yogurt→yoghurt`、`colour/color` 等变体在重标脚本里做归一化匹配（官方表本身以英式为主、美式括注 [provinces-1]）。

### 3.6 迁移 0011 完整 SQL 草案

文件名 `backend/wd/migrations/0011_stage_xs_renumber.sql`（`db.py:41` 的命名正则；下一个编号 0011 [stage-model-21]）。运行器约束（`db.py:195-249`）：文件在运行器的 `BEGIN IMMEDIATE` 内执行、不得 `COMMIT`/`ROLLBACK`、不得自写 `schema_migrations`、不得切 `PRAGMA foreign_keys`（运行器在 BEGIN 前已 OFF，结束后 `foreign_key_check`）；`VACUUM` 不能在事务内，不放在这里。停机迁移（重建表非 additive，`DEPLOY.md:421`）。

```sql
-- 0011_stage_xs_renumber.sql — five stages (xs/zk/gk/cet4/cet6), stage index 1..5, K-12 defaults.
--
-- Why a rebuild: SQLite cannot ALTER a CHECK list or a column DEFAULT (0001_init.sql §1, db.py). Two tables change:
--   user_settings: current_stage CHECK 1..5 (was 1..4) and the K-12 defaults; existing rows keep stages_json and get
--                  current_stage + 1 (zk 1→2, gk 2→3, cet4 3→4, cet6 4→5);
--   words:         new stage_xs flag, stage_min CHECK 1..5 with stage_min + 1 for existing rows; stage flags are
--                  re-derived from the seed right after this file (kv.seed_version is cleared below).
-- v_bank references words and must be dropped before the RENAME and re-created verbatim (0001_init.sql:572-576;
-- without this the runner fails with "error in view v_bank: no such table: main.words").
-- The runner wraps the file in BEGIN IMMEDIATE, runs foreign_key_check and records schema_migrations(11, …) itself.

-- 1. user_settings -------------------------------------------------------------------------------------------------
CREATE TABLE user_settings_new (
  user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  timezone           TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
  push_time          TEXT    NOT NULL DEFAULT '08:00' CHECK (push_time GLOB '[01][0-9]:[0-5][0-9]' OR push_time GLOB '2[0-3]:[0-5][0-9]'),
  push_enabled       INTEGER NOT NULL DEFAULT 1  CHECK (push_enabled IN (0,1)),
  daily_new_count    INTEGER NOT NULL DEFAULT 10 CHECK (daily_new_count BETWEEN 0 AND 50),
  daily_screen_count INTEGER NOT NULL DEFAULT 15 CHECK (daily_screen_count BETWEEN 0 AND 50),
  max_reviews        INTEGER NOT NULL DEFAULT 60 CHECK (max_reviews BETWEEN 0 AND 300),
  stages_json        TEXT    NOT NULL DEFAULT '["xs","zk"]',  -- 目标阶段: non-empty subset of xs/zk/gk/cet4/cet6; K-12 default = the 初中生 preset
  current_stage      INTEGER NOT NULL DEFAULT 2  CHECK (current_stage BETWEEN 1 AND 5),  -- 主攻阶段 1=xs 2=zk 3=gk 4=cet4 5=cet6 (Stage string on the wire)
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
INSERT INTO user_settings_new (user_id, timezone, push_time, push_enabled, daily_new_count, daily_screen_count, max_reviews,
                               stages_json, current_stage, show_images, zh_examples, auto_pronounce, accent, email_enabled,
                               webhook_enabled, webhook_url, webhook_format, next_push_at, updated_at)
SELECT user_id, timezone, push_time, push_enabled, daily_new_count, daily_screen_count, max_reviews,
       stages_json, current_stage + 1, show_images, zh_examples, auto_pronounce, accent, email_enabled,
       webhook_enabled, webhook_url, webhook_format, next_push_at, updated_at
FROM user_settings;
DROP TABLE user_settings;
ALTER TABLE user_settings_new RENAME TO user_settings;
CREATE INDEX ix_user_settings_next_push ON user_settings(next_push_at);

-- 2. words ---------------------------------------------------------------------------------------------------------
DROP VIEW v_bank;
CREATE TABLE words_new (
  id                  INTEGER PRIMARY KEY,
  lemma               TEXT NOT NULL,
  display             TEXT NOT NULL,
  kind                TEXT NOT NULL DEFAULT 'word' CHECK (kind IN ('word','phrase','abbreviation','proper_noun')),
  phonetic            TEXT,
  translation         TEXT,
  definition          TEXT,
  pos                 TEXT,
  collins             INTEGER,
  oxford              INTEGER,
  exam_tags           TEXT,
  bnc                 INTEGER,
  frq                 INTEGER,
  exchange_json       TEXT,
  stage_xs            INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs   IN (0,1)),  -- 小学: 义务教育课标 2022 二级词汇表 (505)
  stage_zk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_zk   IN (0,1)),  -- 初中: 上海市初中英语词汇表 2020 ∪ 课标三级 (1600, ⊇ 二级)
  stage_gk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_gk   IN (0,1)),  -- 高中: 普通高中英语课程标准 2017 年版 2025 年修订 (3100, ⊇ 三级)
  stage_cet4          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet4 IN (0,1)),  -- 四级 (unchanged: 2016 CET syllabus ∪ ECDICT cet4)
  stage_cet6          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet6 IN (0,1)),  -- 六级 (unchanged)
  stage_min           INTEGER CHECK (stage_min BETWEEN 1 AND 5),  -- lowest stage 1=xs 2=zk 3=gk 4=cet4 5=cet6; NULL = outside every list
  cet6_star           INTEGER NOT NULL DEFAULT 0 CHECK (cet6_star IN (0,1)),
  sources             TEXT,  -- provenance tokens, space-joined, sorted: cs2022:l2 cs2022:l3 sh2020 cs2025:hs0|hs1|hs2 cet4 cet46 cet6 cet6star ecdict legacy:zk legacy:gk
  ecdict_id           INTEGER,
  source              TEXT NOT NULL CHECK (source IN ('seed','ecdict','claude','user')),
  is_public           INTEGER NOT NULL DEFAULT 1 CHECK (is_public IN (0,1)),
  is_valid_english    INTEGER CHECK (is_valid_english IN (0,1)),
  safe_for_sharing    INTEGER CHECK (safe_for_sharing IN (0,1)),
  difficulty          INTEGER CHECK (difficulty BETWEEN 1 AND 5),  -- Claude's scale is unchanged: 1 初中 … 4 六级, 5 beyond (= stage index + 1 for sorting)
  merged_into_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,
  created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  active_content_id   INTEGER,
  active_image_id     INTEGER,
  content_state       TEXT NOT NULL DEFAULT 'none' CHECK (content_state IN ('none','queued','ready','failed')),
  image_state         TEXT NOT NULL DEFAULT 'none' CHECK (image_state  IN ('none','queued','ready','failed')),
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
INSERT INTO words_new (id, lemma, display, kind, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq,
                       exchange_json, stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min, cet6_star, sources, ecdict_id,
                       source, is_public, is_valid_english, safe_for_sharing, difficulty, merged_into_word_id, created_by_user_id,
                       active_content_id, active_image_id, content_state, image_state, created_at, updated_at)
SELECT id, lemma, display, kind, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq,
       exchange_json, 0, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min + 1, cet6_star, sources, ecdict_id,
       source, is_public, is_valid_english, safe_for_sharing, difficulty, merged_into_word_id, created_by_user_id,
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

-- 3. data -----------------------------------------------------------------------------------------------------------
-- batch settings snapshots carry the stage index of their day (batches.py:314-318, write-only); keep them meaningful
UPDATE push_batches
   SET settings_json = json_set(settings_json, '$.current_stage', json_extract(settings_json, '$.current_stage') + 1)
 WHERE json_type(settings_json, '$.current_stage') = 'integer';
-- the stage flags are owned by the seed: force main.seed_check / `wd import-seed` to re-import the shipped seed at the
-- next start even if its sha256 were unchanged (it is not — the relabelled seed is a new file)
DELETE FROM kv WHERE key = 'seed_version';
INSERT INTO system_events(kind, detail_json, created_at)
VALUES ('migration', '{"version": 11, "stage_model": "xs/zk/gk/cet4/cet6", "index": "1..5", "note": "stage_min/current_stage renumbered +1; flags re-derived from the seed"}',
        strftime('%Y-%m-%dT%H:%M:%SZ','now'));
```

要点与依据：

- `INSERT … SELECT` **按列名**而不是 `SELECT *`（新表多一列、顺序变）；`id` 显式复制，9 条引用 `words(id)` 的外键关系在 `foreign_keys=OFF` 下不受 DROP 影响、RENAME 后按名解析（探针变体 B 实测 [verify stage-model-12]）。
- `user_settings` 没有任何子表引用（25 张表的 `pragma_foreign_key_list` 核过 [verify stage-model-12]）。
- `DROP VIEW v_bank` 必须在 `DROP TABLE words` 之前，`CREATE VIEW` 用 0001:572-576 原文；本机 `/usr/bin/sqlite3` 的 `legacy_alter_table=1` 会掩盖这个错误，**排练一律走 `.venv/bin/python` 的 `run_migrations`** [verify stage-model-13]。
- 线上两行用户数据的结果：`(1, '["zk","gk","cet4","cet6"]', 3)` → `current_stage 4`（cet4）；`(2, '["zk"]', 1)` → `2`（zk）。4 条 `push_batches.settings_json` 的 `"current_stage": 3` → 4。
- `json_set/json_extract/json_type` 是 SQLite 内置 JSON1（.venv SQLite 3.54.1；生产 Linux 的版本未知 [verify stage-model 未解决 4]，3.38+ 内置）。
- `seed_version` 删除后，`main.seed_check`（`main.py:307-319`）在 `run_migrations` 之后 `import_seed`（`main.py:482-485`），顺序满足「先建列再导种子」[stage-model-20]。
- `difficulty` CHECK 不变（D2）。
- **`docs/SCHEMA.sql` 规则**：`test_db.py:362-366` 要求它与 0001 字节一致，所以**不改**；在 `DESIGN.md §3.1` 词汇表一行加「当前 schema = 0001 + 0008 + 0010 + 0011；`words`/`user_settings` 的现行 DDL 见 0011」；0011 文件自身就是这两张表的完整 DDL（上面已是全文）。
- 文件膨胀：重建后 5.6 → ≈9.4 MB，迁移后手动 `VACUUM`（第 6 节）。

### 3.7 后端改动

| 文件:行 | 改什么 |
|---|---|
| `backend/wd/schemas.py:25` | `Stage = Literal["xs", "zk", "gk", "cet4", "cet6"]`（顺序与 `types.ts:5` 逐值相同，`check_contract.py:274-281` 顺序敏感） |
| `schemas.py:26` | `StageIndex = Literal[1, 2, 3, 4, 5]` |
| `schemas.py:51-52` | `STAGE_ORDER` 加 `xs` 首位；新增 `STAGE_INDEX` 字典；`STAGE_NAMES_ZH["xs"] = "小学"` |
| `schemas.py:56-67` | `stage_to_index` 查 `STAGE_INDEX`；`index_to_stage` 范围 `1..len(STAGE_ORDER)`；文档串 `xs→1 … cet6→5` |
| `schemas.py:488` `VocabQuery.stage`、`:708` `ScreenNextQuery.stage`、`:1335` `PrewarmRequest.stage` | 字面量加 `"xs"` |
| `schemas.py:1-12` 模块文档「1–4 column」 | 改 1–5 |
| `backend/wd/seed.py:43` | `STAGES = ("xs", "zk", "gk", "cet4", "cet6")`（或直接 `from .schemas import STAGE_ORDER, STAGE_INDEX`，消灭一份副本） |
| `seed.py:47-68` `SEED_COLUMNS` | 在 `stage_zk` 前加 `stage_xs`（UPSERT 列清单与 `WHERE … IS NOT excluded` 由 `:72-82` 自动生成） |
| `seed.py:204-208` | 加 `"stage_xs": int("xs" in stages)`；`stage_min = min(STAGE_INDEX[s] for s in stages) if stages else None` |
| `seed.py:1-20` 文档串 | 「the four stage flags」→ five；加「种子从不删词」规则 |
| `backend/wd/services/words.py:39` | `STAGES` 加 `xs`（同上建议改为 `schemas.STAGE_ORDER`） |
| `words.py:563-586 _word_defaults` | 加 `"stage_xs": 0` |
| `words.py:589-597 _INSERT_WORD_SQL` | 列清单与占位符加 `stage_xs` |
| `words.py:228-229 stages_of` | 自动（按 `STAGES` 迭代） |
| `backend/wd/services/ecdict.py:28` `STAGE_TAGS` | 保留四个 ECDICT 标签名（`has_stage_tag` 仍用于 `words.py:669,673` 的原形回指判断） |
| `ecdict.py:117-119 stages` | 只返回 `cet4/cet6`（A3：zk/gk 不再由 ECDICT 标签赋予） |
| `ecdict.py:173-177 word_columns` | 加 `"stage_xs": 0`；`stage_zk/gk` 恒 0；`stage_min = min(STAGE_INDEX[s] …)`；`sources` 写 `"ecdict"`（不变） |
| `backend/wd/routers/vocab.py:78` | `"difficulty": "COALESCE(w.difficulty + 1, w.stage_min, 6), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` |
| `vocab.py:83-107 /api/stages` | 自动 5 行（`STAGE_ORDER` 循环） |
| `backend/wd/services/stats.py:173-196` | 自动 |
| `backend/wd/services/bank.py:85-86` | `DEFAULT_STAGES = ("xs", "zk")`、`DEFAULT_CURRENT_STAGE = 2` |
| `bank.py:181` | 不变（过滤未知阶段并回落默认——部署顺序见第 3.8 节） |
| `backend/wd/security.py:612-614 stages_json` | 文档串默认值改 `'["xs","zk"]'` |
| `backend/wd/services/screen.py:44`、`services/batches.py:272,698` | 重编号后无 0 值陷阱，**可不改**；建议顺手改为 `cur = s.get("current_stage"); cur = bank.DEFAULT_CURRENT_STAGE if cur is None else int(cur)`，杜绝以后再踩 |
| `backend/wd/ai/prewarm.py:32-33` | `STAGE_COLUMNS["xs"] = "stage_xs"`；`STAGES = (*schemas.STAGE_ORDER, "all")` |
| `backend/wd/ai/content.py:48-49` | `AUDIENCE = "Chinese learners, primary school to CET-6, plus working professionals"`；`STAGE_ZH["xs"] = "小学"`（或 `= schemas.STAGE_NAMES_ZH`，消灭副本） |
| `backend/wd/ai/prompts/content_system.txt:1` | 受众列表加「小学」；`:11` 难度图例不变（D2），可加半句「primary-school words: use 1」。提示词文本变了但规则未变，`PROMPT_VERSION`（`content.py:46`）的提升与 Q9 的小学例句规则一起由配图/提示词线决定 |
| `scripts/eval_provider.py:107` | `STAGES` 加 `xs`（`sample_words :326-348` 自动多抽 10 个小学词） |
| `scripts/smoke.py:352,614` | 期望 5 个阶段 / `len(stats["stages"]) == 5` |
| `scripts/build_seed.py` | 保留为「从 `stardict.db` 全量重建」路径但同步常量（`:10-11,112,147,150,191`、`ATTRIBUTION :201-219`）；**新增 `scripts/relabel_seed.py`**（第 4 节）作为本轮实际使用的生成器 |

### 3.8 API 契约与前端

**契约三件套**（`types.ts:1-2`：`API.md`、`schemas.py`、`types.ts` 同一提交）：

- `types.ts:5` `export type Stage = 'xs' | 'zk' | 'gk' | 'cet4' | 'cet6';  // index 1..5 in that order`；`:6` `StageIndex = 1 | 2 | 3 | 4 | 5`；`:37` 注释「1–4 index」→ 1–5；`:45` 注释「初中 / 高中 / 四级 / 六级」→ 加小学；`:52` 不变。
- `API.md`：`:155` 端点 12「1–4 column index」；`:160` 端点 15「⊆ {xs,zk,gk,cet4,cet6}」；`:167` 端点 19「5 rows」；`:169` 端点 20 `stage=all|xs|zk|gk|cet4|cet6`、`new_only` 的例子改为「for gk this is the 1,235-word 高中 increment」、`sort=difficulty` 的 COALESCE 句；`:187` 端点 31；`:230` 端点 67；`:239-240` §9 两行；`:279` `StageInfo.name_zh` 注释；`:459-460` §9.1 映射 `xs→1, zk→2, gk→3, cet4→4, cet6→5`。
- `scripts/check_contract.py` 无需改；`make test` 第二步会校验顺序。

**前端**（[frontend-stages-9] 清单 + 本稿的两处体验改动）：

| 文件:行 | 改什么 |
|---|---|
| `frontend/src/components/word/StageChips.tsx:7-9` | `STAGE_ORDER = ['xs','zk','gk','cet4','cet6']`；`STAGE_INDEX = { xs: 1, zk: 2, gk: 3, cet4: 4, cet6: 5 }`；`STAGE_BY_INDEX` 对应 |
| `StageChips.tsx:15-32` | 新增可选 prop `only?: readonly Stage[]`：传入时只渲染 `stages ∩ (only ∪ {STAGE_BY_INDEX[stageMin]})`。`WordRow.tsx:97`、`StudyCard.tsx:172/207/298`（经 `WordHeader.tsx:50`）传 `settings.stages`（`useAuth()`）；`WordDetailPage.tsx:360`（`size="lg"`）不传，显示全部。效果：小学生的学习卡只看到「小学」一个芯片；四级用户不会被 412 个新「初中」芯片打扰；顺带消除 375 px 下 5 个芯片换行的风险 [verify frontend-stages-15] |
| `frontend/src/i18n/zh.ts:25` | `roles: { xs: '小学生', zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }` |
| `zh.ts:28-29` | `stages: { xs: '小学', zk: '初中', …, xsFull: '小学（课标二级词汇）', …, newOnly: '仅本阶段新增', newOnlyZk: '仅初中新增（不含小学）', newOnlyCet6: '仅六级新增（不含四级）', star: '六级星标词' }` |
| `zh.ts:86` | `lists: '词表范围：义务教育课标二级、三级词汇，上海市初中英语词汇表，高中课标 3100 词，大学英语四级与六级大纲'` |
| `docs/FRONTEND.md:231-235, 292` | 与上三行**逐行镜像**（`zh.test.ts:67-83`、`zh.contract.test.ts:62-83`，[frontend-stages-7]）；`:50`、`:54-56`、`:89`、`:147` 文案 |
| `frontend/src/pages/WelcomePage.tsx:30` | `Role = 'xs' \| 'zk' \| 'gk' \| 'uni' \| 'pro'` |
| `WelcomePage.tsx:33-38` | `xs: { stages: ['xs'], current: 'xs' }`；`zk: { stages: ['xs','zk'], current: 'zk' }`；其余不变 |
| `WelcomePage.tsx:40` | `ROLES = ['xs','zk','gk','uni','pro']`（5 个角色 chips 在 375 px 折成 3+2 两行，今天 4 个已是两行 [verify frontend-stages-14]） |
| `WelcomePage.tsx:42` | `STAGE_FULL` 加 `xs` |
| `WelcomePage.tsx:72-73` | 兜底 `ROLE_PRESETS.pro` → `ROLE_PRESETS.zk`（与服务端默认一致） |
| `frontend/src/pages/VocabPage.tsx:29` | `TABS = ['all','xs','zk','gk','cet4','cet6']` |
| `VocabPage.tsx:202` | `newOnlyLabel = tab === 'cet6' ? zh.stages.newOnlyCet6 : tab === 'zk' ? zh.stages.newOnlyZk : zh.stages.newOnly` |
| `VocabPage.tsx:232` | `{tab !== 'all' && tab !== STAGE_ORDER[0] && <Switch …/>}`——最低阶段的开关是空操作，隐藏（同时修掉今天初中 tab 的恒等过滤 [frontend-stages-19]） |
| `frontend/src/components/ui/ui.css:453-473` | 加 `@media (max-width: 479.98px) { .tabs--fill .tab { padding-inline: var(--space-2); } }`：6 个 tab 6×(32+16)+20 = 308 px ≤ 343（375 px）且 ≤ 328（360 px）[frontend-stages-16 ②]。真机复核列入验收 |
| `frontend/src/pages/ScreenPage.tsx:20` | `FULL_NAME` 加 `xs` |
| `ScreenPage.tsx:31` | 改为 `[...data.items].filter(i => isStage(i.stage)).sort((a, b) => a.index - b.index)`：以服务端顺序为准、仍丢弃未知码；再加一条测试断言 `items.length === STAGE_ORDER.length` 提醒前后端不同步 |
| `frontend/src/pages/AdminPage.tsx:36` | `PREWARM_STAGES = [...STAGE_ORDER, 'all']`（类型 `PrewarmStage = Stage \| 'all'` 自动） |
| `frontend/src/pages/SettingsPage.tsx:301-318` | 自动（遍历 `STAGE_ORDER`）；5 个 chip-btn 一行放下 [verify frontend-stages-17] |
| `docs/DESIGN.md:72` §0.3 术语表 | `小学 / 初中 / 高中 / 四级 / 六级`，`xs / zk / gk / cet4 / cet6 (stage index 1–5)`；`:32,40`「four stage tabs」；`:186,202,209` 数字；`:330` 角色预设；`:345-350` 不变（算式不变） |
| `docs/qa-frontend.md:36,42` | 人工用例改 5 阶段与新计数 |

**部署顺序**：后端未扩枚举时，词库「小学」tab 请求 `stage=xs` 得 400（`schemas.py:488`）；更危险的是旧后端的 `bank.py:181` 会把 `["xs"]` 静默过滤成四六级 [verify frontend-stages-13]。Mac 上前后端在同一次重启里发布（SPA 快照 symlink 在停服务时切换，第 6 节），不存在混合状态；Linux `install.sh` 路径同样是停机后一起切换。规则写进 `DEPLOY.md §10`：「阶段枚举变更的发布不可用 `--no-restart`」。

### 3.9 新用户默认（Q6）

- DDL：`stages_json DEFAULT '["xs","zk"]'`、`current_stage DEFAULT 2`（0011 §1）。
- 注册流程不改：`security.py:662-664` 继续只插三列，默认来自 DDL。
- `bank.py:85-86` 复制值同改；`bank.py:172-173`、`:181` 用它兜底。
- `WelcomePage.tsx:72-73` 兜底 `ROLE_PRESETS.zk`。
- 文档：`API.md` 端点 2 若提到默认（`test_auth.py:82` 钉住 `["cet4","cet6"]/cet4`），`DESIGN.md §6.1/6.2` 表格的默认列。
- 测试：`test_auth.py:82`、`test_security.py:315`、`test_onboarding.py:98` 改为新默认。

### 3.10 老用户：「我看到的初中/高中词集变了」

**原则**：阶段是共享词库的属性，学习进度是用户的属性；重标只动前者。保证（都有代码依据）：

1. 生词库行、SRS、批次、记录一个不动——种子导入排除所有每用户表 [stage-model-19]；0011 不碰它们（`user_words` 等只是 `words(id)` 的子表，重建后行数不变 [verify stage-model-12]）。
2. 今天批次里的词继续可学——`push_items.word_id` 不变；一个词离开某阶段不影响它已在批次里的事实。
3. 已在生词库但离开所有阶段的词继续复习，只是详情页不再有阶段芯片（`StageChips` 对空列表返回 `null`，`StageChips.tsx:27`）。可选小改：`stage_min === null` 时显示一个 `zh.stages.outside: '课标外'` 芯片，告诉学习者为什么它不在任何页签（+1 个 zh 键 + 镜像；P2）。
4. 用户的目标阶段与主攻阶段原样保留（0011 §1 只重编号）。

**可见的变化**与解释口径（放进发布说明与 `settings.sources.lists`）：

| 用户 | 看到什么 | 为什么是对的 |
|---|---|---|
| kimi（`["zk"]`，主攻初中，10 个生词全是课标二级词 [排练]） | 初中 tab 2,099 → 2,015；「仅初中新增（不含小学）」1,515；她的 10 个词芯片高亮从「初中」变成「小学」（`stage_min` 1 = xs），但仍在初中池里（累计） | 初中集合现在是上海中考词汇表 ∪ 国家三级；小学词是初中的子集 |
| sqin（全部阶段，主攻四级，67 个生词） | 67 个词里 55 个的最低阶段下移（39 个成为高中首、15 个初中首、1 个小学首）；四级 tab 不变 | 这些词在国家高中 3100 / 三级表里；四级大纲本来就与高中重叠 |
| 未来的高三用户 | 高中 tab 少了 1,140 个旧 3500 词（842 个在四/六级 tab 仍可见，216 个只在全部） | 2019 年起高考不再以旧大纲为依据 [C2] |

**不做**：不弹一次性通知（无机制，且 2 个用户产品负责人都认识）；不给老用户自动加 `xs`。

---

## 4. 改动清单（文件 → 改什么）

### 4.1 数据与种子

| 文件 | 改什么 |
|---|---|
| `backend/wd/migrations/0011_stage_xs_renumber.sql` | 新建，第 3.6 节全文 |
| `scripts/relabel_seed.py` | 新建。输入 `data/seed/vocab.jsonl.gz` + `data/lists/{cs2022_level2,cs2022_level3,sh2020_junior,cs2025_senior}.txt`（+ 可选 `--ecdict-csv` 或 `--ecdict-db`）；对每条记录：`stages` = `xs` if lemma ∈ L2 ∪ `zk` if ∈ SH ∪ L3 ∪ `gk` if ∈ H3100，`cet4/cet6` 原样；`sources` 重写为第 3.4 节 token（含 `legacy:zk/gk`，依据旧记录的 `stages`）；别名表 `Mr→mr.`、`Mrs→mrs.`、`Ms→ms.`、`PE→p.e.`、`café→cafe`、`yogurt→yoghurt`、`a.m./p.m.` 空格归一；官方清单里不在库的词头 → 从 csv 取字段或最小记录，并打印清单供人工核对；输出 `vocab.jsonl`、`stats.json`（加 `per_stage.xs`、`list_sizes`、`new_headwords`）、`ATTRIBUTION.md`；排序键 `(min index, lower)` 与 `build_seed.py:150-151` 一致。用 `python3 -I` 运行，词表以路径参数传入 |
| `data/seed/vocab.jsonl.gz` | 重新打包（Mac gzip 哈希与 Linux 不同 [seed-pipeline-7]，`kv.seed_version` 随之变化，可接受） |
| `data/seed/stats.json`、`data/seed/ATTRIBUTION.md` | 由脚本生成；署名加教育部课标附录词头、上海市教育考试院 2020 词汇表词头、高中课标 2025 修订附录词头（只用词头，[C4]） |
| `data/lists/*` | 词表任务交付；本稿只约定文件名与格式（一行一个词头，可带 `(variant)`/`*`）；`data/lists/README.md` 写来源 URL/日期/许可姿态 |
| `scripts/build_seed.py:10-11,112,147,150,191,201-219` | 常量同步到 5 阶段；说明它现在只用于从 `stardict.db` 全量重建词典字段，阶段来自 `relabel_seed.py` 的清单（或直接调用同一函数） |
| `README.md:3,9,103`、根 `ATTRIBUTION.md:14`、`data/seed/ATTRIBUTION.md:10-16` | 五阶段、新计数、「官方课标词头清单随仓库分发（`data/lists/`），mahavivo 文件仍不分发」 |

### 4.2 后端

见第 3.7 节表格（`schemas.py` 8 处、`seed.py` 4 处、`services/words.py` 3 处、`services/ecdict.py` 3 处、`routers/vocab.py` 1 处、`services/bank.py` 1 处、`security.py` 1 处、`ai/prewarm.py` 1 处、`ai/content.py` 2 处、`ai/prompts/content_system.txt` 1 处、`scripts/eval_provider.py` 1 处、`scripts/smoke.py` 2 处；可选 `screen.py:44`、`batches.py:272,698`）。

### 4.3 契约与前端

见第 3.8 节表格（`types.ts` 3 行、`API.md` 10 处、`StageChips.tsx`、`zh.ts` 3 处 + `FRONTEND.md §8` 镜像、`WelcomePage.tsx` 5 处、`VocabPage.tsx` 3 处、`ui.css` 1 处、`ScreenPage.tsx` 2 处、`AdminPage.tsx` 1 处、`WordHeader.tsx`/`WordRow.tsx`/`StudyCard.tsx` 传 `only`、`DESIGN.md` 7 处、`qa-frontend.md` 2 处）。

### 4.4 文档

| 文件:行 | 改什么 |
|---|---|
| `docs/API.md:155,160,167,169,187,230,239-240,279,459-460` | 第 3.8 节 |
| `docs/DESIGN.md:32,40,72,186,202,209,330` + §3.1 加「当前 schema = 0001+0008+0010+0011」、§3.2 `stages[]`/`sources[]` 两行 | 第 3.4/3.6 节 |
| `docs/FRONTEND.md:50,54-56,89,147,231-235,292` | 第 3.8 节 |
| `docs/TASKS.md:172-175` | 验收数字改为新种子的（词表任务交付后填） |
| `docs/DEPLOY.md:360-361,421` | 「阶段枚举/索引变更不可 `--no-restart`；回滚只能 `wd restore`；迁移后 `VACUUM`」 |
| `docs/WORD_LIBRARY_CURATION.md §1.2` | 「种子从不删词」与 `sources` token 的一句话 |
| `docs/SCHEMA.sql` | **不改**（字节一致测试） |

---

## 5. 测试与验收

### 5.1 会变红的已有测试（按 `make test` 顺序）

**pytest**：

| 测试 | 原因 | 改法 |
|---|---|---|
| `tests/unit/test_api_schemas.py:33-39 test_stage_mapping_roundtrip` | 4 阶段往返、`index_to_stage(5)` 期望抛错、`STAGE_NAMES_ZH` 等式 | 5 阶段往返；`index_to_stage(6)` 抛错；字典加 `xs` |
| `tests/integration/test_vocab.py:69-70` | 4 行/索引/名称 | 5 行 `[1..5]`、名称含「小学」 |
| `test_vocab.py:75-79` `items[3]` 为 cet6 | 位置 | `items[4]`；`new_only_total == 3` 取决于夹具（见 5.3） |
| `test_vocab.py:111` `stage_min == 4` | 重编号 | `== 5` |
| `test_vocab.py:153-161` difficulty 排序 | `COALESCE(difficulty + 1, …, 6)` | 注释与 `keys` lambda 同步；断言 `absorption(difficulty 1 → 2) < abandon(stage_min 3) < absolutely(stage_min 4)` 仍成立 |
| `tests/integration/test_history.py:112` | 阶段集合 | 加 `xs` |
| `tests/integration/test_screen.py:116` `current_stage=4` | 重编号（六级） | `=5` |
| `test_screen.py:129-133` | 注释里的 `stage_min 4/1` | `5/1`；`["be","a","go"]` 顺序不变（xs ⊂ zk，累计） |
| `tests/integration/test_onboarding.py:98` | 默认 `3 / '["cet4","cet6"]'` | `2 / '["xs","zk"]'` |
| `test_onboarding.py:120,139` | `'cet4' stored as 3`、`zk → 1` | 4、2 |
| `tests/integration/test_settings.py:88` | 存库整数 | gk → 3 |
| `tests/unit/test_security.py:315`、`tests/integration/test_auth.py:82` | 默认设置 DTO | `["xs","zk"]`、`"zk"` |
| `tests/unit/test_seed.py:93-97` | `stage_min` 值；`a` 若在夹具里标 `xs` 则仍为 1 | `abandon → 3`、`absolutely → 4`、`email → 2`（或 1 若标 xs）、`ought to → 5` |
| `test_seed.py:204,294,298` | 重导后 `stage_min == 1`（`zk`）→ 2；最小记录 `(1,0,0,1,1,1)` → `stage_min 2`；`r2` 不变 | 同步 |
| `test_seed.py:340-353 test_full_seed_acceptance_numbers`（`full_seed` 标记） | 全部计数 | 新种子数字（词表任务交付后由 `stats.json` 填入） |
| `tests/unit/test_words_resolve.py:279,346` | ECDICT 路径 `stage_min 4` | 5（cet6 仍由 ECDICT 标签赋予） |
| `test_words_resolve.py:478` | `stage_min == 2` | 3 |
| `tests/unit/test_batches.py:127` 注释 | `stage_min 3` | 4 |
| `tests/unit/test_content_apply.py:255` | `go` 的阶段标签 | 若夹具给 `go` 标 `xs`：`["小学","初中","高中","四级"]` |
| `tests/integration/test_reports.py:29,87` | 夹具 `stage_min 2`（gk） | 3 |
| `tests/integration/test_admin_ops.py` | `stage: "cet4"` 仍合法 | 不变；加一条 `stage: "xs"` 202 |
| `tests/test_fake_claude.py:26`、`tests/unit/test_runner.py:27` | 提示词夹具只含中文标签 | 不变 |

**契约审计**：`scripts/check_contract.py` 对 `Stage`/`StageIndex` 顺序敏感 → 两边同提交。

**vitest / tsc**：`zh.test.ts:67-83` 与 `zh.contract.test.ts`（镜像）；tsc 对 `Record<Stage,…>` 5 处缺键（`StageChips.tsx:8-9`、`WelcomePage.tsx:42`、`ScreenPage.tsx:20`、`zh.test.ts:56`）与 `zh.stages[s]` 索引；12 处 `stage_min: N` 夹具（`queue.test.ts:52`、`StudyCard.test.tsx:29`、`AddWordPreviewRow.test.tsx:15`、`WordRow.test.tsx:16`、`SpeakButton.test.tsx:91`、`WelcomePage.test.tsx:21`、`WordDetailPage.test.tsx:62`、`ScreenRunPage.test.tsx:34`、`StudyPage.test.tsx:79`、`BankPage.test.tsx:35,108,137`）不会报错但语义漂移（`chip--min` 高亮）→ 全部 +1；`SettingsPage.test.tsx:218-221` 四例不变。

### 5.2 要加的测试

| 位置 | 断言 |
|---|---|
| `backend/tests/unit/test_db.py` 新增 `test_upgrade_0011_renumbers_stages_and_rebuilds_two_tables` | 用 0001 基线建库，插 `users`×2、`user_settings`（`current_stage` 1 与 3，`stages_json` `'["zk"]'`/`'["zk","gk","cet4","cet6"]'`）、`words`（`stage_min` 1..4 各一行 + `merged_into_word_id` 自引用）、`user_words`/`push_items`/`word_contents`/`word_images`/`content_reports`/`bank_suggestions` 各一行、`push_batches.settings_json` 含 `"current_stage": 3`、`kv.seed_version`；`run_migrations()` 后：`applied` 含 `(11, 'stage_xs_renumber')`；`current_stage` 为 2/4，`stages_json` 原样；`words.stage_min` 为 2..5，`stage_xs` 全 0；`settings_json` 的 `current_stage` 为 4；`kv.seed_version` 不存在；子表行数不变（`_counts` 模式，`test_db.py:155-199`）；`PRAGMA foreign_key_check` 空；`db.view_names(c) == ["v_bank"]` 且 `SELECT * FROM v_bank` 可执行；新插 `user_settings` 行默认 `'["xs","zk"]'`/2；`UPDATE words SET stage_min = 6` 抛 `IntegrityError`、`= 1` 通过；`EXPECTED_TABLES` 不变（25 张） |
| `test_db.py::test_schema_file_is_byte_identical_to_docs_copy_when_present` | 不变（SCHEMA.sql 不改） |
| `backend/tests/unit/test_api_schemas.py` | `tuple(STAGE_INDEX) == STAGE_ORDER` 且 `STAGE_INDEX[s] == STAGE_ORDER.index(s) + 1` |
| `backend/tests/unit/test_seed.py` | 一条 `stages: ["xs"]` 的记录 → `stage_xs 1, stage_min 1`；`["xs","zk","gk","cet4"]` → `stage_min 1`；`["cet6"]` → 5；`sources` 原样写入 token |
| `backend/tests/integration/test_vocab.py` | `/api/vocab?stage=xs&new_only=1` 总数 == `stage_min=1` 数；`/api/stages` 第一行 `stage == "xs" and index == 1` |
| `backend/tests/integration/test_screen.py` | `stage=xs` 候选顺序；主攻 `xs` 的用户 `auto` 距离：xs 0、zk 1、gk 3（钉住「0 值陷阱不存在」：`current_stage=1` 不会被当成缺失） |
| `backend/tests/unit/test_content_apply.py` | 带 `stage_xs=1` 的行 `prompt_entry` 得 `"小学"` 且不抛 `KeyError` |
| `frontend/src/pages/ScreenPage.test.tsx`（新建） | 6 项 `/api/stages` 时按 `index` 排序渲染 5 张卡；未知码被丢弃 |
| `frontend/src/components/word/StageChips.test.tsx`（新建或并入 `SpeakButton.test.tsx`） | `only=['xs']` 时一个带 4 标志的小学词只渲染「小学」；`stageMin` 对应的阶段始终保留 |
| `frontend/src/pages/WelcomePage.test.tsx` | `ROLE_PRESETS` 每个 `current ∈ stages`；`xs` 预设；`ROLES.length === 5` |
| `frontend/src/pages/VocabPage.test.tsx` | `TABS.length === STAGE_ORDER.length + 1`；`tab === 'xs'` 时不渲染「仅本阶段新增」开关 |

### 5.3 夹具 `backend/tests/fixtures/mini_seed.jsonl`（60 条）

给 `a, apple, be, book, cat, child, dog, glass, go, good, happy, house, teacher, water` 等二级词加 `"xs"`（`stages` 首位），其余不动；连锁核对：`test_seed.py:97` `a → stage_min 1` 仍成立；`test_screen.py:133` `zk` 顺序 `["be","a","go"]` 不变（累计）；`test_vocab.py:78` cet6 `new_only_total == 3`（absorption/axe/ought to）不变；`test_content_apply.py:255` 按 5.1 更新。

### 5.4 在 `live-copy.db` 的私有拷贝上排练（不碰 `/Users/sqin/word-dance-data`）

```bash
S=/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/stage-model-learner-first/rehearsal
mkdir -p $S && cp …/scratchpad/live-copy.db $S/word-dance.db      # 私有拷贝；live-copy.db 本身不写
cd /Users/sqin/word-dance
WD_DATA_DIR=$S .venv/bin/wd migrate --dry-run                       # 列出 0011
WD_DATA_DIR=$S .venv/bin/wd migrate                                 # 走 run_migrations（legacy_alter_table=0），自动写 $S/backups/pre-migrate-10-to-11.db.gz
WD_DATA_DIR=$S .venv/bin/wd import-seed --file data/seed/vocab.jsonl.gz   # 新种子；期望 ~36–40 inserted, ~2,800 updated, 0.3 s
sqlite3 -readonly $S/word-dance.db "PRAGMA integrity_check; PRAGMA foreign_key_check;
  SELECT stage_min, COUNT(*) FROM words GROUP BY 1;                                   -- 500/1515/1235/1807/3857/NULL 248（排练口径）
  SELECT SUM(stage_xs), SUM(stage_zk), SUM(stage_gk), SUM(stage_cet4), SUM(stage_cet6) FROM words;
  SELECT COUNT(*) FROM words WHERE stage_xs=1 AND stage_zk=0;                        -- 0（累计不变量）
  SELECT COUNT(*) FROM words WHERE stage_zk=1 AND stage_gk=0;                        -- 0
  SELECT COUNT(*) FROM words WHERE stage_min IS NOT (CASE WHEN stage_xs=1 THEN 1 WHEN stage_zk=1 THEN 2 WHEN stage_gk=1 THEN 3 WHEN stage_cet4=1 THEN 4 WHEN stage_cet6=1 THEN 5 END);  -- 0
  SELECT user_id, stages_json, current_stage FROM user_settings;                     -- (1, [zk,gk,cet4,cet6], 4) (2, [zk], 2)
  SELECT COUNT(*) FROM user_words; SELECT COUNT(*) FROM word_contents; SELECT COUNT(*) FROM word_images;  -- 77 / 49 / 31 不变
  SELECT COUNT(*) FROM words WHERE content_state='ready' AND stage_min IS NULL;      -- 0"
WD_DATA_DIR=$S .venv/bin/wd serve &  # 可选：起在 8000 以外的端口（WD_PORT）跑 scripts/smoke.py 的 stages/vocab/screen 段
```

不变量 `stage_xs ⇒ stage_zk ⇒ stage_gk` 来自课标的嵌套定义（3.4 节），写进 `test_full_seed_acceptance_numbers` 与 `TASKS.md` 验收。

---

## 6. 上线与回滚（Mac，launchd）

Mac 上没有 `install.sh`/`systemctl`（memory `macos-local-install`）：`wd serve` 启动时自己跑迁移（先快照 `backups/pre-migrate-10-to-11.db.gz`，`backup.py:283-295`）再 `seed_check`。因此**启动新代码 = 执行不可逆迁移**，顺序必须是：先备份、再停、再切、再起。

```bash
export WD_DATA_DIR=/Users/sqin/word-dance-data   # CLI 需要（memory）
D=$WD_DATA_DIR; cd /Users/sqin/word-dance
# 0. 门禁：make test（Mac 上 test_deploy_files 与 test_config::test_defaults_without_environment 按设计失败，其余必须绿）；5.4 排练已通过
# 1. 手动全量备份（在自动 pre-migrate 快照之外再留一份带时间戳的）
.venv/bin/wd backup --keep-daily 14 --keep-weekly 8
# 2. 构建新 SPA 快照（发布前；不影响运行中的服务）
SHA=$(git rev-parse --short HEAD)
(cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm ci && npm run build -- --outDir $D/frontend-releases/$SHA.new --emptyOutDir)
# 3. 停服务（launchd 不会再拉起）
launchctl bootout gui/$(id -u)/com.word-dance.server
# 4. 发布 SPA 快照（BSD mv 无 -T，用 rename）
mv $D/frontend-releases/$SHA.new $D/frontend-releases/$SHA
ln -sfn frontend-releases/$SHA $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"
# 5. 显式迁移 + 导种子（比让 wd serve 顺带做更可控；两者等价）
.venv/bin/wd migrate                      # 写 backups/pre-migrate-10-to-11.db.gz，应用 0011（< 0.1 s）
.venv/bin/wd import-seed                  # kv.seed_version 已被 0011 删除 → 必导；期望 ~36–40 inserted / ~2,800 updated
sqlite3 $D/word-dance.db "PRAGMA integrity_check; PRAGMA foreign_key_check;" && sqlite3 $D/word-dance.db "VACUUM;"   # 收回重建产生的空闲页（5.6→9.4 MB），服务已停
# 6. 起服务并验证
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist   # 或 kickstart -k
curl --noproxy '*' -s http://127.0.0.1:8000/api/health
# 登录后：GET /api/stages 返回 5 行且 index 1..5；GET /api/settings 两个账号的 current_stage 仍是 'cet4' / 'zk'；
# 词库页 6 个 tab 在 375 px 不横滚；筛词页 5 张卡；管理页预生成下拉含「小学」；~/Library/Logs/word-dance/word-dance.log 有 applied migration 0011 与 seed_imported
```

**回滚**（唯一路径是恢复快照 [verify stage-model 遗漏 2]：旧代码 `schemas.py:65` 对索引 5 抛 `ValueError` → 任何六级主攻用户的 `GET /api/settings` 500；`bank.py:181` 把 `["xs"]` 静默换成四六级）：

```bash
launchctl bootout gui/$(id -u)/com.word-dance.server
git checkout 75df534
.venv/bin/wd restore $D/backups/pre-migrate-10-to-11.db.gz --yes     # 迁移后产生的学习记录丢失——发布后尽快决定是否回滚
ln -sfn frontend-releases/75df534 $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"   # 75df534 快照仍在（保留两份）
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist
```

Linux（`deploy/install.sh`）路径：同 `DEPLOY.md §10`，但在文档里加粗「0011 不可 `--no-restart`」。

---

## 7. 风险、未决问题、工作量

### 7.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 词表任务交付的清单口径与本稿排练不同（上海表 1,731 vs 手册 1,733；三级转录件抽样核对 234/505 [B2]；2025 修订版印发文号未找到 [未解决 1]） | 各阶段计数与 `TASKS.md` 验收数字需重填 | 所有数字由 `relabel_seed.py` 的 `stats.json` 生成，测试与文档引用它；设计不依赖具体数字 |
| 新增 ≈36–40 词头的词典字段来自 `ecdict.csv`（`pos` 空、`ecdict_id` 不可复现）或人工 | 这些词在 `sort=freq` 下排最后（`frq` 空） | 可接受；清单随 PR 人工过目 |
| 一次性、不可代码回滚的迁移 | 发布后若发现问题只能恢复快照，丢失其间学习记录 | 5.4 排练 + 发布后立即验证清单；选低活跃时段 |
| `sources` 语义变更没有读取者，但 `seed-pipeline` 文档与 `DESIGN §3.2` 仍写旧 token | 日后误解 | 同提交改文档；0011 DDL 注释 |
| 提示词里出现「小学」标签但生成规则未按小学调整（Q9 属另一条线） | 小学词的例句可能偏长（`EXAMPLE_EN_MIN = 15`）| 本稿不入队任何小学词的生成；预生成小学前先落地 Q9 |
| 6 个页签在 375 px 的算术未真机量测 [verify frontend-stages 未解决 1] | 右侧被裁 | 列入验收；备选去掉 `fill` 接受横滑 |
| 运行时 ECDICT 词不再拿 zk/gk 标志 | 极少数用户自添词的芯片变少 | 按定义正确；无用户路径依赖 |
| Mac 打包的 gzip 哈希与 Linux 不同 | 跨机种子版本号不一致 | 已知、无害 |

### 7.2 未决问题（需要产品负责人或词表任务回答）

1. `xsFull` 文案：本稿用「小学（课标二级词汇）」；若要面向家长更口语（如「小学（1–5 年级）」）需接受与六三学制的措辞差异。
2. 「初中生」预设是否含小学（本稿：含，`['xs','zk']`）；新用户默认是否就是这个预设（本稿：是）。
3. `data/lists/` 文件名与格式由词表任务最终确定；本稿按 3.4 节的名字写脚本接口。
4. 课标外 248 词是否要在详情页显示「课标外」芯片（P2，+1 个 zh 键）。
5. `PROMPT_VERSION` 是否随「小学」标签进入提示词而提升——建议与 Q9 的小学例句规则一起提升一次，而不是为本改动单独提升。
6. 上海高考 200 补充词、2026 年中考手册 1,785 词 [B6/B7] 出现机读源后：追加 `sources` token 并重导即可，不需要再改模型。

### 7.3 工作量（人日）

| 工作 | 人日 |
|---|---|
| 0011 迁移 + `test_db` 升级测试 + 排练 | 1.0 |
| 后端常量/映射/排序/默认值 + 现有测试更新 + 新测试 | 1.5 |
| `relabel_seed.py` + 别名/变体归一 + 新词头核对 + `stats/ATTRIBUTION` 生成（词表任务交付后） | 1.5 |
| 前端：枚举、角色、页签、`StageChips only`、CSS、测试、`FRONTEND.md §8` 镜像 | 1.0 |
| 契约与文档（`API.md`、`DESIGN.md`、`TASKS.md`、`README`、`DEPLOY.md`） | 0.5 |
| Mac 发布 + 验证 + 发布说明 | 0.5 |
| **合计** | **≈ 6.0–6.5** |

---

## 附：排练数字的来源与口径

`scratchpad/stage-model-learner-first/compute.py`（本稿编写；`python3.12 -I`）：

- 清单：二级 = `verify-shanghai-primary/level2_505_from_docx.txt` ∪ `provinces/std2025rev_level2.txt`（506 词头，含 `a/an`、`I`）；三级与 3100 = `shanghai-secondary/07-yr7429/kaogang_graded.txt`（无星 1,655 / 一星 503 / 两星 1,013，括注变体展开）；上海 = `verify-shanghai-secondary/sh2020_mine.json`（1,731，与作者解析双向差集为空 [verify shanghai-secondary-7]）；2020 版 3000 = `provinces/std2020_hs_words.txt`。
- 匹配：NFKC、小写、弯引号归一后与 `words.lemma` 精确匹配；未匹配但在 `word_forms` 中的不计为缺失（如 `excited`）。
- 关键输出：xs 500；zk 2,015（保留 1,603 / 离开 496 / 加入 412）；gk 3,134（2,689 / 1,140 / 445）；新 `stage_min` 500 / 1,515 / 1,235 / 1,807 / 3,857 / NULL 248；无阶段词中有内容或配图的 0；kimi 10 词全部仍在初中池；sqin 67 词中 55 词最低阶段下移。
- 已知口径差异：三级 ∩ 库 1,639（含英美变体）vs [verify provinces-25] 1,592；3100 ∩ 库 3,134 vs [verify provinces-4/22] 3,112。方向与量级一致，最终以词表任务交付清单重算。
