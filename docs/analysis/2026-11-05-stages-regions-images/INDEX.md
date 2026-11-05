# INDEX — 2026-11-05 调研总索引：小学阶段 · 上海/省际词表 · 配图记忆效果

基线：仓库 `/Users/sqin/word-dance`，`main @ 75df534`；线上库只读副本 `scratchpad/live-copy.db`（9,162 词）；日期 2026-11-05。本文件只做索引与综合，不改代码。

## 范围与方法

- 读完本目录 20 个文件：`facts/{stage-model,seed-pipeline,ai-prompts-stages,frontend-stages,image-memorability,images-pipeline,list-sources,provinces,shanghai-primary,shanghai-secondary}.md` 与同名 `verify/*.md`（共 287 条编号结论，核验者逐条复核 275 条）。
- 本文件**没有**新下载、没有新联网、没有新跑 SQL；所有数字取自 facts，**凡被 verify 修正的，一律采用修正后的数字并标「核验修正」**；两个作者对同一事实给出不同数字时，采信「用生产代码 / 一手文件 / 独立重算」的一方，理由写在第 3 节。
- 引用格式：`[slug-N]` 指向 `facts/<slug>.md` 的第 N 条；`[verify <slug>-N]` 指向核验文件对应条目；`[verify <slug> 遗漏 k]` 指向核验文件「作者遗漏的重要事实」第 k 条。代码位置 `path:line` 均相对仓库根，按 75df534。
- 置信度沿用各文件标注：高 = 一手文件 / 代码 / 复算；中 = 可互证的二手；低 = 单一二手或推断。

---

## 1. 文件索引

| 文件 | 主题 | 结论数 | 核验：确认 / 修正 / 推翻 / 无法核验 | 作者下载了什么 |
|---|---|---|---|---|
| `facts/stage-model.md` | 后端阶段数据模型；新增「小学」与「上海/全国」维度的改动面；0011 迁移可行性 | 22（+1 表格行） | 20 / 3 / 0 / 0 | ECDICT README（18,414 B）；在 `live-copy.db` 私有拷贝上用真实 `run_migrations` 跑 4 种表重建探针（变体 A–D） |
| `facts/seed-pipeline.md` | `build_seed.py` / `seed.py` 流水线事实；加小学词表要改什么；lemma 冲突实验 | 31 | 28 / 3 / 0 / 0 | ECDICT README、GitHub API 元数据 JSON、mahavivo 5 个文件（含上海初中 PDF 1.2 MB）、`ecdict.csv`（66 MB）、`ecdict-sqlite-28.zip` 尾部 65 KB（Range 请求读中央目录） |
| `facts/ai-prompts-stages.md` | 阶段/难度如何进入 AI 提示词与 schema；小学例句的约束；图意字段 | 16 | 14 / 2 / 0 / 0 | 无（纯代码核验） |
| `facts/frontend-stages.md` | 前端对阶段的全部依赖；加阶段/加地区的改动清单；门禁测试；375px 布局 | 27 | 23 / 4 / 0 / 0 | 无（纯代码核验） |
| `facts/image-memorability.md` | 配图助记的认知科学证据；现有 SVG/照片管线可控项；图片 API 参数；生成模型价格；自动评估 | 35（核验 32，3 条自标推断未计） | 25 / 7 / 0 / 0 | OpenAlex 题录 27 条、Springer PDF ×2（Brysbaert 2014、Glasgow 2019）、Chinese-CLIP README、open_clip `model_profile.csv`；核验者另下载 Openverse OpenAPI YAML、Brysbaert ESM xlsx（2.2 MB）、Schneider 2018 / Hao 2022 PDF |
| `facts/images-pipeline.md` | 配图流水线完整事实（搜索词、provider 参数、打分、存储、展示、SVG、线上统计）；12 个抓手；约束 | 48（核验 38） | 32 / 5 / 0 / 1 | Openverse 源码 7 个文件 + OpenAPI 文本；核验者另发 1 次匿名 Openverse 请求取限流头、3 次 Commons API 只读查询 |
| `facts/list-sources.md` | 可机读课程词表来源清单与许可审计（mahavivo / kajweb / qwerty / KyleBing / DictionaryData / maimemo / djfml / HF）；交叉重合表 | 32 | 27 / 5 / 0 / 0（4 个子项未复现） | mahavivo 4 文件、qwerty 12 个 JSON、djfml `OXFORD.apkg`、DictionaryData（`book.csv`、`word.csv` 7.3 MB、`relation_book_word.zip` 10.9 MB→111 MB）、`ecdict.csv`、各仓库 README/API 元数据；核验者另下载教育部 2022 课标扫描 PDF（31.5 MB） |
| `facts/provinces.md` | 国家课标（2011/2022/2017-2020/2025 修订）词量；中考/高考命题制度；教材版本地图；上海 vs 国家词表量化 | 31 | 18 / 10 / 0 / 3 | 教育部 2022 课标 PDF、2020 高中课标 zip（38.6 MB）、2011 课标扫描件、freemdict 社区转录 docx/PDF ×3、2024 国家教学用书目录、上海/深圳/北京教委文件、2019 高考大纲 PDF、粤教考函〔2026〕1 号；核验者另下载 shmeea `03.pdf`/`07.pdf`（上海 2020 评价指南 + 词汇表）与《课程·教材·教法》2026(5) |
| `facts/shanghai-primary.md` | 上海五四学制与小学英语：官方词汇要求、教材更替、牛津上海版词量、可机读来源 | 22 | 19 / 2 / 0 / 1 | djfml `OXFORD.apkg`、mahavivo 小学表、qwerty 上海六下 + PEP 8 册、上海教委教学用书目录 PDF ×6 + 课程计划/通知 .doc/.docx ×5、教育部 2022 课标与课程方案 PDF（自写 Vision OCR）；核验者另下载 edu.sh.gov.cn 11 个文件、freemdict 义务教育课标转录 docx、`angelachen825-bit/baicizhan` 的 `wordbank.js` |
| `facts/shanghai-secondary.md` | 上海初中（中考）与高中（高考）词汇要求 vs 现用全国词表；覆盖率；许可 | 23 | 16 / 6 / 0 / 1 | mahavivo 3 文件 + 上海 PDF、shmeea 评价指南 PDF ×3（2017/2019/2020）、上海课标说明 .doc、zhongkao-words JSON 18 个、KyleBing 2 个 txt、YR7429 2 个 txt、上海教学用书目录 PDF ×2；核验者另下载 2025 修订高中课标非官方镜像 PDF、`Abyss-of-Dragon/project_english` 数据 docx |
| **合计** | | **287** | **222 / 47 / 0 / 6** | |

读法提示：没有任何一条被「推翻」；47 条「修正」几乎全是数字口径（解析规则、词/词条/词组、页首漏词、省份计数）与「文件已被更新版本取代」，主结论方向在十个切片里是一致的。

---

## 2. 跨切片核心结论（25 条，以核验后的版本为准）

### A. 现有词库与阶段模型的事实（8 条）

**[A1] 现库 9,162 词 = ECDICT 1.0.28 的 zk/gk/cet4/cet6 标签 ∪ mahavivo 六个考纲 txt 的词头；阶段标志不是单调区间，也不严格累计；两份中小学来源文件身份不明。** 事实，高（数字）/ 中（来源身份）。
线上：zk 2,099 / gk 3,829 / cet4 4,722 / cet6 7,671；`stage_min` 1:2,099 2:1,792 3:1,577 4:3,694；全部 `source='seed'`；旗标组合 15 种（`0001` 3,694、`0011` 1,512、`0111` 1,156、`1110` 1,019、`1111` 854、`0101` 349 …）；62 个初中词不在高中表、706 个高中词不在四级表、1,186 个四级词不在六级表；`kind` 分布 word 9,004 / phrase 13 / abbreviation 26 / proper_noun 119。[stage-model-4] [list-sources-1] [verify frontend-stages 遗漏 4] [verify list-sources-3]。来源身份：`Highschool_edited.txt`（3,446）属旧《高考大纲》3500 词谱系（与 aaaaenglish 3500 页前 25 词逐词相同，含 abortion/bungalow/yummy 等课标没有的词），不是 2017 课标表；`中考英语词汇表.txt`（1,887）既不是 2011/2022 课标 1600 也不是上海表；mahavivo README 对中考/小学/上海/Highschool 四个文件一字未提，仓库无 LICENSE。[shanghai-secondary-16/17（核验修正：多词条目 6 个而非 8 个）] [list-sources-4] [verify provinces 遗漏 4]。含义：任何新模型都要保留「每词一个阶段集合」；现有 zk/gk 是旧考纲口径，不是现行课标口径。

**[A2] ECDICT 没有「小学」标签：基础版 `ecdict.csv`（770,611 行）的 `tag` 只有 8 个取值 gre 7,504 / toefl 6,974 / cet6 5,407 / ielts 5,040 / ky 4,801 / cet4 3,849 / gk 3,677 / zk 1,603；csv 的 1,603 个 zk 词全部已在库。** 事实，高（csv）；release 1.0.28 `stardict.db` 全集未在本机核实（中，`stardict.db` 在禁区）。[list-sources-2] [seed-pipeline-22] [verify seed-pipeline O5] [verify stage-model-7]。含义：「小学」成员只能来自 ECDICT 之外的词表。

**[A3] 阶段枚举是硬编码，整数索引由元组位置推出，DB 把范围写死；加「小学」的索引方案没有免费选项。** 事实（现状）高；方案代价为推断，中—高。
现状：后端 10 个常量 + 3 个请求 `Literal` + 2 个同类字面量，前端 5 个源文件，文档/测试/脚本 20 余处；`schemas.py:58` `STAGE_ORDER.index(stage) + 1`；`0001_init.sql:148,185` `CHECK (… BETWEEN 1 AND 4)`；`scripts/check_contract.py:274-281` 对 `types.ts` 与 `schemas.py` 的字面量联合做顺序敏感比对。[stage-model-1（核验修正：9→10 个常量，另加 `bank.py:85`、`eval_provider.py:107`）] [stage-model-2] [frontend-stages-1/8] [verify list-sources 遗漏 2] [verify shanghai-primary 遗漏 4]。
四种办法：① 小学 = 0（数据不重编号，但 `screen.py:44`、`batches.py:272,698` 的 `int(x or DEFAULT_CURRENT_STAGE)` 把 0 当缺失→3，三处要改 `is None`；`stage_to_index/index_to_stage` 改显式字典）；② 小学 = 5 追加（破坏「索引 = 顺序」，`stages[0]`、距离 CASE、`COALESCE(difficulty, stage_min, 5)` 都要改查表）；③ 重编号 1..5（现有「位置推导」代码的自然结果，`stage_min`/`current_stage` 全部 +1，文档/契约/验收数字作废，`difficulty` 尺子错位一格）；④ 字符串列 + `stage_defs` 表（唯一让阶段成为数据的方案，改动最大）。[stage-model-9] [frontend-stages-12（核验修正：方案 A「小学 = 0」并不比重编号便宜）] [verify frontend-stages 遗漏 1]。

**[A4] 改 CHECK 必须整表重建（SQLite 无 ALTER CONSTRAINT），运行器支持且毫秒级（`user_settings` 0.007–0.009 s，`words` 0.039–0.041 s），但重建 `words` 必须先 `DROP VIEW v_bank` 再重建，否则 RENAME 失败；本机 `/usr/bin/sqlite3` 的 `legacy_alter_table=1` 会掩盖这个问题（实测），排练必须走 `.venv/bin/python` 的 `run_migrations`；只改常量不迁数据会整体错位。** 事实，高。[stage-model-8/11/12/13] [verify stage-model-13（CLI 部分由推断升为实测）]。补充：一旦有用户选了小学，就不存在「只回退代码」的回滚（旧代码 `schemas.py:65` 对索引 0/5 抛 `ValueError`→500），只剩 `wd restore` 快照 [verify stage-model 遗漏 2]；重建后 db 文件 5.6 MB→9.4 MB 且项目无 VACUUM [verify stage-model 遗漏 4]；下一个迁移编号 0011，部署顺序「停服务 → migrate → import-seed → 启动」已满足「先建列再导种子」[stage-model-20/21]。

**[A5] `difficulty` 1–5 尺子（1 = 初中 … 5 = beyond CET-6）与阶段索引绑定，写死在 3 份提示词、3 份 JSON schema、4 个 pydantic `Literal`、`schemas.py:47 Difficulty`、`types.ts:73`、DB CHECK，且 `vocab.py:78` 用 `COALESCE(w.difficulty, w.stage_min, 5)` 把两把尺子当一把；线上只有 49 词有 `difficulty`（全部是有 AI 内容的词，44/49 与 `stage_min` 相等）。** 事实，高。[ai-prompts-stages-9/14] [stage-model-6] [verify stage-model 遗漏 3]。含义：小学要么共用 1（零代码、丢区分度），要么扩成 6 级（≈12 个文件 + 迁移 + `API.md §9`）。

**[A6] 种子导入对已有行是「覆盖全部 20 个种子列」而非「只填空」，未注册阶段码被静默丢弃，只接受一个文件，lemma 是小写唯一键；而现有 zk 来源文件本身有缺陷。** 事实（实验 + 复算），高。
导入：重导可以改写 `stage_*`/`stage_min`；`May`/`may`、`Mr`/`Mr.`、`ice-cream`/`ice cream` 会冲突或重复；`kv.seed_version` 只存哈希，补充文件会被仓库种子覆盖回去——小学内容必须改 `WD_SEED_PATH` 指向的那一个文件、给现有词加标记要改原行。[seed-pipeline-10/11/12/14] [stage-model-19/20]。
缺陷：`build_seed.py:16 RICH_RE` 丢掉 7 行全角括号/缺括号行，导致 `best`（stage_min=3）、`less`（stage_min=2）不在初中层、`cafe` stage_min=3；`a (an)` 只取到 `a`，`an` 在库但 `stage_zk=0, stage_min=2`；plain 模式会丢单字母词 `a`/`I`；初中 tab 的「仅本阶段新增」今天是空操作（2,099 = 2,099）。核验新发现。[verify list-sources-7 / 遗漏 3] [verify shanghai-secondary O8] [seed-pipeline-2] [frontend-stages-19]。

**[A7] 新用户默认受众写死在 DDL 默认值里，引导页没有「小学生」，前端加阶段本身小但有四道门禁，且必须后端先上。** 事实，高。
默认：`stages_json DEFAULT '["cet4","cet6"]'`、`current_stage DEFAULT 3`，注册 `INSERT` 不写这两列，`bank.py:85-86` 又复制了一份；角色只有 `zk/gk/uni/pro`；AI 受众常量 `AUDIENCE = "… junior high school to CET-6, plus working professionals"`；改列 DEFAULT 同样只能靠重建，应与 0011 合并。[verify stage-model 遗漏 1] [frontend-stages-14] [verify seed-pipeline O2] [verify ai-prompts-stages 遗漏 1]。
前端：加一个阶段 ≈ 7 个源文件 20–25 行；门禁 = `check_contract.py` 顺序敏感联合比对、tsc 对 `Record<Stage,…>`（5 处）与 `zh.stages[s]` 缺键报错、`zh.ts` 必须与 `docs/FRONTEND.md §8` 逐行镜像（两个测试）、后端 pytest 钉死四阶段中文名；部署顺序：后端未扩枚举时词库页 400，更危险的是 `bank.py:181` 会把未知阶段静默过滤、全部未知时回落到 cet4/cet6。6 个 tab 在 375 px 溢出约 13 px（推断，中）；小学词 chips 换行风险真实但非常态（初中词 40.7% 带满四标签）。[frontend-stages-7/9/13/15/16/24/25（核验修正 15）] [verify frontend-stages-13 补强 / 遗漏 2/7]。

**[A8] 「上海/全国」在模型里没有落点：只有阶段一维，`words.sources` 无读取者。** 事实 + 推断，高/中。两条路线——A 多加列（`stage_sh_xs…` + `stage_min_sh`，additive 但列数 = 方案 × 阶段）、B 新表 `word_stage_tags(word_id, scheme, stage)` + `stage_defs`（只加行，顺带消灭 10 份常量，改动面最大；线上 ≈18,321 个 (词, 阶段) 对）；两条路线都要让 `/api/stages` 按方案返回、前端改为由后端数据驱动页签（`ScreenPage.tsx:31` 现在会静默丢掉未知阶段）。前端建议做成每用户 `Settings.region`、服务端解析，不要把地区编进阶段码。[stage-model-15/16/17/18] [frontend-stages-21/22/23]。

### B. 上海学制与词表（小学 / 初中 / 高中）（7 条）

**[B1] 上海五四学制（小学 1–5、初中 6–9），英语从一年级开设；上海自己的词量口径只有 2004 年课标说明（K/X 口径），其作为中考法定基准的地位 2022 年后待查。** 事实，高（引文）/ 中（现行基准）。
学制：沪教委基〔2015〕35 号（自带「有效期 5 年」条款，但 2021 学年课程计划仍按此编排）；1999 年试点、2004 年全部开设一年级英语；国家 2022 课程方案起始年级三年级；2022 课标明文：「五四」3–5 年级目标参照「六三」5–6 年级并适当降低，1–2 年级为预备级、无词表、教材纳入地方管理；小学阶段英语只「考查」不考试。[shanghai-primary-1（核验修正：二级 505 词对应上海小学毕业略降，而非「跨越小五与初六」）/2/3] [verify shanghai-primary 遗漏 1/6]。
口径：2004 年《上海市中小学英语课程标准（征求意见稿）》说明：T = K + X；小学毕业 K ≥ 500 / T ≥ 600；初中累计 K ≥ 1600 / T ≥ 2100；高中累计 K ≥ 2300 / T ≥ 4200；K 表本身未见公开。2020 年及以前的中考评价指南明示以 2004 标准为范围，但 2022 学年起上海课程计划已以国家 2022 课标为依据。[shanghai-primary-4] [shanghai-secondary-3（核验修正：「法定基准仍是 2004」定性过强）] [verify shanghai-secondary O2]。

**[B2] 国家 2022 课标附录 3 是现成的官方「小学 / 初中」定义：二级 505 词（小学），三级 1600 词（含二级 505，初中新增 1095），各地可加 100–300；二级 505 词 99.0% 已在库。** 事实，高（教育部一手扫描 PDF 目视核对；505 清单来自非官方转录、抽样 234 词一致）。
体例：英式拼写为主、不标词性释义、数词/月份/星期/国家名/不规则动词单列、不列词组与可推导派生词；2011 版为 423 / 1500。[provinces-1/2] [list-sources-26（核验升级为一手）] [shanghai-primary-6]。覆盖：**500/505 在库，495 个 `stage_min=1`，真正缺的只有 `excited`**（`mr/mrs/ms/pe` 是句点书写差异，`o'clock` 在库；`an/astronaut/maths` stage_min=2，`best` =3，`chore` =4）。[verify shanghai-primary-21（核验修正）] [verify provinces-24（核验修正）]。含义：「小学」阶段几乎不需要新词，缺的是阶段标记。

**[B3] 上海小学教材正在换代，牛津上海版词表只有非官方机读源；各小学候选表之间重合度低，新增小学层还要下调一批现有词的 `stage_min`。** 事实，高/中。
教材：2024 秋以前牛津上海版（沪教）与新世纪版（沪外教）两套择一；2024 年 9 月起新编《义务教育教科书（五·四学制）·英语》逐年替换（2024 一年级、2025 二年级、2026 三年级），2026 秋目录里两套旧教材已完全消失。牛津上海版 1A–5B 词量只有墨墨按册相加 772（6A–9B 1,703）；唯一可机读全套是 GitHub `djfml` Anki 牌组：1,040 条 / 825 个单词 / 769 在库（93.2%）/ 671 个 `stage_min=1`（87%），无许可、无来源、无册别；小学词不能用 `frq` 阈值近似（牌组在库词里 130 个 `frq > 5000`）。[shanghai-primary-7/8/10/12/13]。
候选并集：四表（mahavivo 439、PEP 819、沪教三起 1,008、djfml 840）单词并集 1,365，170 不在库、160 在库但 `stage_min>1`（五表再并入上海六下为 1,520 / 179 / 210；原文把五表数字写成四表，核验修正）；初中七表并集 3,425，437 不在库（原文 451）、917 在库但 `stage_min>1`。[list-sources-28/29（核验修正）]。

**[B4] 上海初中词表有一手官方出处：上海市教育考试院 2019-09-26 发布页同时挂出《2020 年上海市初中英语课程终结性评价指南》（`03.pdf`）与其《词汇表》（`07.pdf`），后者 md5 与 mahavivo 转载 PDF 完全相同；规模 ≈1,720–1,731 单词 + 331–342 词组；98.3% 在库但只有 80.5% 标了初中。** 事实，高。
规模差异来自 `although/though`、`bike/bicycle` 等并列是否拆分；译文社手册称 1733 + 335，App 文案 1719。[verify provinces-12（核验修正：1,655/140 是作者解析漏掉每页首词的伪影）] [list-sources-6] [shanghai-secondary-7（核验修正：1,732 token / 1,731 唯一；词组 331）]。与现库：1,702–1,703（98.3%）在库；1,393–1,394（80.5%）`stage_zk=1`；309 个在库但 `stage_min>1`（2:236 / 3:59 / 4:14）；**真正缺席 14 个**（angrily, beautifully, bund, carefully, dancer, dishonest, hot-dog, luckily, mr, mrs, politely, quietly, seafood, unforgettable），其余「缺词」是屈折形式（已在 `word_forms`）或拼写变体。[shanghai-secondary-19（核验修正：29→14）] [provinces-26]。

**[B5] 上海初中表与全国/国家表的差异是真实且双向的。** 事实，高。与现用全国中考表 1,887 交集 1,286（占上海表 74.3%），仅上海 445、仅全国 601；与国家三级 1600 交集 ≈1,305–1,308（75.9–76.3%），仅上海 415–426（其中 244–259 个出现在国家高中 3000 表，148–156 个两边都没有：派生副词、分词形容词、`bund`），仅三级 286–303；上海表 91.5% 落在 `Highschool_edited` 内；现库 2,099 个 zk 词有 706 个（33.6%）不在上海表。[shanghai-secondary-8/9/21] [provinces-13（核验修正：|L3−S| 419→303）] [list-sources-7/29（核验修正）]。含义：上海初中「比国家基准多学高中词、少列小学功能词」，只拿国家三级表会漏掉约 1/4；「按省份分层」至少对上海必须是独立词集，不能只在全国表上加标签。

**[B6] 上海中考词表的载体是考试院每年出版的付费《考试手册》，2020 年之后没有任何机读副本；中考外语含人机对话听说测试。** 事实，中—高（教辅转述，两源一致）。教辅复述的年度词量：2013 年 1669 + 323，2020 年 1733 + 335，2025 年 1730 + 334，2026 年 1785 + 347（附 273 个「新课标三级词汇（2022 版）」与 129 个「学科教学基本要求词汇」）；《上海市初中英语学科教学基本要求（试验本）》（2016 / 2017 修订）词表未见电子版。考试结构（沪教委规〔2019〕2 号）：150 分 = 笔试 140（含听力 25）+ 听说测试 10（人机对话）——与本项目的发音/口音设置相关。[shanghai-secondary-5/6] [verify shanghai-secondary O4]。

**[B7] 上海高中：两套教材各 7 册，高考自主命题；2023 年起「无考纲」，依据转为国家高中课标词表 + 考试院 200 个补充词；上海高考词表没有任何机读文件，是最大的地区缺口。** 事实，高/中。
教材上教版/上外版（2020 秋高一先行）；2023 年以前词表经付费《考试手册》《高考英语词汇手册（上海卷）》（考试院官方出版物，上海译文）发布；2023 年起依据 = 国家课标词表（2017/2020 版 3000 词，2025 修订版 3100 词）+ 考试院 200 词（复旦手册附录「新课标 135 + 上海 200」）。唯一可机读的上海高中词集是 DictionaryData 的「2016 高考英语词汇上海卷」4,016 词（Apache-2.0 声明、来源不明）：只有 75% 在现库 gk 层，948 词超出全国高中层（780 在库属 cet4/cet6，168 不在库）。[shanghai-secondary-10/11/12/14/15] [provinces-20（核验补充：考试院确有官方词汇手册，纸质可购）] [list-sources-17/30]。

### C. 省际差异（4 条）

**[C1] 中考：全国统一以课程标准命题、考试大纲已取消、省级统一命题推进中；除上海外没有任何省/市公开中考词表。国家三级 1600 对现库覆盖 98.8%，但要让 `stage_zk` 覆盖它需重标约 190 词。** 事实（制度、数字）高；「国家三级 + 上海标签足够」为推断，中。
制度：教基〔2019〕15 号「取消初中学业水平考试大纲，严格依据义务教育课程标准命题」；浙江、湖北 2024 起省级统一命题，广东除广州/深圳外省统一，江苏 2025 仍 13 市各自命题；北京、广州、深圳自主命题但依据课标、无公开词表。[provinces-5/14/15/16/17/28]。
数字：三级主表 1,611 中 1,592（98.8%）在库，1,419（88.1%）带 `stage_zk`，138 个只带 gk、35 个只带 cet；现库 2,099 个 zk 词有 680（32.4%）不在三级表；`中考英语词汇表.txt` 1,887 与三级表交集 1,282、超出 605、缺 329，其中 ECDICT 的 zk 标签只补回 137 个（41.6%）。[provinces-25（核验修正：1,774→1,887；「弥补大部分」→41.6%）] [verify provinces 遗漏 5]。含义：其他地区差异只是教材版本标签，不是词集差异。

**[C2] 高考：新课程省份不再制定考试大纲；2025 年 28 个省份用全国卷（原文「29」为核验修正）、京津沪自主命题；旧「高考 3500」已不是命题依据而现用 `Highschool_edited.txt` 正是它；国家高中 3000/3100 对现库覆盖 99.5%/96.6%，但现 gk 有 31.2% 超出国家表。** 事实，高（数字）/ 中（2025 修订的正式性）。
国办发〔2019〕29 号；2019 大纲「词汇量为 3500 左右」。国家高中词表：2020 版 3000 词（解析 2,997）在库 2,981（99.5%），带 `stage_gk` 2,633（87.9%）；`stage_gk` 3,829 词中 1,196（31.2%）不在国家表内；`Highschool_edited` 对它：共 2,519 / 超 927 / 缺 478。2025 修订版主表 3,104 ≈ 官方 3100，较 2020 版新增约 205 词（原文 ≥291 为核验修正），在库 96.6%、带 gk 82.7%；YR7429 的 3,091 提取与 PDF 逐词一致；学界已采用但教育部印发通知未找到。[provinces-3/4/6/19/22/29（核验修正）] [shanghai-secondary-16/20]。

**[C3] 教材版本：国家目录小学英语 23 套（三年级起点）+ 五四制 2 套、初中 8 套 + 五四制 3 套，没有一年级起点国审小学英语；教材由区（市）在目录内选用；所有版本依据同一课标，差异在词汇出现的年级/册次与超纲词，而非目标词集；「沪教牛津」命名有陷阱。** 事实，高（目录）/ 低—中（省际分布）。深圳全段用上海教育出版社教材（三年级起点六年制「沪教牛津」，**不是**上海五四制牛津上海版；`angelachen825-bit/baicizhan` 词库即此版本）；广州教科版；江苏译林、浙江 PEP 等只有二手来源；DictionaryData 的「沪教版牛津 7A–9B」很可能也是外省版（与牛津上海版七年级只互含 14%/42%）。[provinces-7/8/10/11/27] [shanghai-primary-18] [verify shanghai-primary-18] [verify list-sources 遗漏 5]。

**[C4] 可机读词表来源与许可总表：只有 ECDICT（MIT）与官方文件的「词头」是许可干净的；其余要么无许可、要么禁商用、要么许可只覆盖代码。** 事实，高。
教育部课标与上海考试院词汇表为政府/事业单位发布的考试文件，未声明许可，《著作权法》第五条是否适用未核实；**词头清单接近事实数据、释义/词性/选排可能构成汇编作品**（现有做法「只用词头」与此一致）；mahavivo 无 LICENSE；DictionaryData Apache-2.0 只是仓库作者声明；kajweb / qwerty / KyleBing 同源有道（GPL-3 / BSD-3 只约束代码）；maimemo-export 唯一覆盖上海三学段但「禁止商用」；zhongkao-words 内容 CC BY 4.0（AI 生成未审校）；YR7429 内容 CC BY-SA 4.0；djfml 无许可；HF SwiftieJerry CC BY-NC-ND。[list-sources-32 汇总表] [shanghai-secondary-22/23] [provinces-31（核验修正：上海一行改为官方件）] [verify list-sources 遗漏 4]。

### D. 配图记忆效果的证据与接口能力（6 条）

**[D1] 认知科学证据指向「小学配高图标性的干净插画、成人可不配图、图不能先于回忆出现、图中无文字」；现有 SVG 与模板卡都违反「无文字」。** 事实，高（引文）/ 低（外推到小学）；准则为推断，中。
证据：图优效应稳健但在儿童更弱更晚（7 岁组限时反转，Defeyter 2009）；具体性是最强预测量（de Groot & Keijzer 2000）；儿童从图学词优于从词学词（Tonzar 2009），成人相反（Lotto & de Groot 1998）；配图造成过度自信，只有配合提取练习才兑现收益（Carpenter & Olson 2012）；配图帮「义」不帮「形」（Boers 2009/2017）；无关细节对儿童伤害更大（Kaminski & Sloutsky；Flack & Horst 2018「一次一图」学到两倍词）；多媒体注释元分析 d = 0.46（Yun 2011，**10 项研究 n = 1,560**，原文「35 项」为核验修正）；诱人细节 g ≈ −0.33（58 项研究）；文生图把关键词联想画出来提升保持（Attygalle 2025）。没有找到 6–11 岁「卡通 vs 照片」或「图与例句义项不一致」的直接实证。[image-memorability-1…15] [verify image-memorability-9]。
准则：单一清晰所指、图中无文字、去装饰细节、画例句用到的义项、抽象词用与 `mnemonic_zh` 对齐的「记忆挂钩」、风格一致构图各异、图作为提示而非答案。现状：SVG 提示词要求「the English word in a <text> at the bottom」，模板卡印词头/音标/释义/例句——都不能当「正面回忆提示」用。[image-memorability B 节/18] [verify images-pipeline O6]。

**[D2] 线上配图现状与管线可控项：31 张图（30 SVG + 1 张 CLI 手抓照片），照片任务 49/49 失败，18 个词永久失败且无自动重试；SVG 每张交付 $0.0140（拒收 11.8%）；搜索词不消歧、全锁照片、打分只看字符串、每词只能一张图。** 事实，高。
现状：49 个 `fetch_image` 任务全部「no acceptable photo from any provider」（原文「除 1 个外」为核验修正）——≥27 个因 provider 冷却未发请求，11-02 的 18 个 Wikimedia 有应答但原因未知（需 journal）；18 个 `failed` = 15 个预取时「尚未被学」没画 SVG + 3 个 SVG 被拒；SVG $0.01237/次（34 次）、$0.0140/张（30 张，4 次 XML 不合法，疑为 `<text>` 里未转义的 `&`）；文档 $0.028 与「≈18 张/天」已过时（$0.50 ≈ 35–40 张/天）；全库 ≈ $113–128 ≈ ¥807–911，按日预算 229 天。[images-pipeline-20/21/25/26/28/29（核验修正）] [image-memorability-16/17（核验修正）] [verify images-pipeline O9]。
可控项：搜索词 = 管理员 `query` → `content.image_keywords[:3]` → 裸 lemma，不消歧，第 4 个关键词永不搜索，含中文/数字的 query 静默回退；默认 provider 链只有 wikimedia + openverse；所有 provider 锁在「照片」（`filetype:bitmap`、`image_type=photo`、不传 `category`）；打分 7 个信号全是标题/标签字符串匹配，没有人脸、文字、复杂度、语义、`description`、Openverse `category` 信号；`generated` 许可会被硬拒（生成图必须绕过 `select.rank`）；存储长边 800 px（Commons `THUMB_WIDTH=800` 常量）在 DPR 2–3 屏放大 1.5–1.8 倍；16:10 `cover` 裁切（竖图只剩 ≈40%）；图只在学习卡背面，换图/举报只在详情页，`show_images` 是全局开关；每词只能一张 active 图（部分唯一索引）→「同一词给小学生插画、给高中生照片」需改数据模型。[images-pipeline-1…19/33] [image-memorability-18…21（核验修正：`score` 列在 `0001_init.sql:266`）] [verify images-pipeline-9（核验修正：lemma 回退不过黑名单，`weapon` 的 SVG 不是黑名单造成）] [verify image-memorability 遗漏 6]。

**[D3] 图片来源接口的官方能力与约束（访问 2026-11-05）：插画过滤参数都存在，但配额与条款让「全库预抓」只对 Commons 可行。** 事实，高。
Pixabay `image_type=illustration|vector`、`category`、`lang=zh`，100 次/60 s，缓存 24 h，禁永久热链，**「Systematic mass downloads are not allowed」与全库预抓冲突**；Pexels `locale=zh-CN`、`size`，200 次/h 与 20,000 次/月（全库 1 关键词 = 月配额 46%），许可页 403 未核；Openverse `category=illustration|photograph|digitized_artwork`、`aspect_ratio`、`size`，匿名限额从响应头实测 20/min、200/day（注册应用 100/min、10,000/day；匿名全库 ≈ 57 天），但 `illustration` 类目返回的 CC0 剪贴画多小于 400×300 会被尺寸门槛硬拒；Commons `filetype:drawing` 可搜到 SVG 且 `thumburl` 是 PNG，但现有代码取原文件 `mime=image/svg+xml` 会被拒——需 `iiprop` 加 `thumbmime`（不是零改动）；`haswbstatement:P180=Q…` 经 `generator=search` 可用但返回「含有」而非「典型」图；Wikimedia 无硬性日配额，项目自限 1 req/s、2000/日（全库 4.6–13.7 天），未传 `maxlag`；Openverse 每次取 20 条只用 10 条。[images-pipeline-4/5/6/7/31/46（核验修正）] [image-memorability-22/23/24/25（核验修正）] [verify images-pipeline O1/O2/O3/O5] [verify image-memorability 遗漏 5]。

**[D4] 生成式替代方案与合规：境内有免费/低价位图生成接口（CogView-3-Flash 免费、CogView-4 ¥550 全库），但代码没有任何生成适配器，且 AI 生成图片有法定标识义务。** 事实（价格、法规）高；换算为推断。
价格：智谱 CogView-3-Flash 免费、CogView-4 ¥0.06/次、GLM-Image ¥0.10/次（中文文字渲染准确率 0.9788），水印默认开、**关水印需签免责声明**，URL 30 天，返回 `content_filter` 0–3；百炼 wan2.2-t2i-flash ¥0.14（RPM 120）、wan2.6 ¥0.20，端点按模型不同（原文混为一个为核验修正），新用户免费额度 2026-10-29 下架；火山 Seedream 5.0-flash ¥0.12、4.0 ¥0.20，水印默认开；Gemini 2.5 Flash Image $0.039、Recraft V3 位图 $0.04 / 矢量 $0.08（风格含 Child book）；OpenAI `gpt-image-1` 未退役（原文第三方说法与官方弃用页不符，核验修正）。全库（¥，7.1 CNY/USD）：CogView-3-Flash 0 / CogView-4 550 / Claude SVG 807–911 / GLM-Image 916 / Seedream flash 1,099 / 万相 flash 1,283 / Seedream 4.0 与 wan2.6 1,832 / Gemini 2,540。[image-memorability-26…30（核验修正 27）] [images-pipeline-37（核验修正）] [verify images-pipeline O4]。
代码与合规：没有 `images/generations` 适配器；接入需迁移 `word_images.provider` CHECK、绕过许可白名单、改 `image_meta` 的 kind/署名分支、`photo_mix`、`ImageProviderName`、前端类型、`ai_calls.kind` CHECK，并定义内容过滤兜底；《人工智能生成合成内容标识办法》（2025-09-01 施行）要求显式标识 + 文件元数据隐式标识，现有 SVG 只有 UI 文字「AI 生成示意图」、文件本身无标识（本应用是否构成「服务提供者」为推断）；`wd images-prune` 会删「没人在学」的词的图，与全库预生成方向相抵。[images-pipeline-37/42/43] [verify image-memorability 遗漏 4] [verify images-pipeline O7]。

**[D5] 自动评估「是否贴切」与具体性常模：多模态模型打分便宜（GLM-4.6V-Flash 免费、qwen3-vl-flash 全库 ≈ ¥33 但价格为二手且免费额度已下架）；CLIP 可离线批处理但偏名词；有 CC BY 4.0 的 4 万词级常模可用。** 事实（规则、参数）高 / 中（价格）/ 低（CPU 延迟）。
Qwen3-VL 图像 token 公式 → 800×500 = 402 token；CLIP ViT-B/32 8.82 GFLOPs/图，2 vCPU 全库一轮估 5.6–11 CPU 小时（未实测），对动词/抽象词弱；常模：Brysbaert 2014（37k 词，Springer ESM 可下载，再分发许可未明示；原文「官方 404」仅对 crr.ugent.be 成立，核验修正）、Glasgow Norms CC BY（5.5k）、**Lancaster Sensorimotor Norms CC BY 4.0（39,707 概念）**——不必在「无许可 40k」与「CC BY 5.5k」间二选一；评分可写进已存在的 `word_images.score` 列。[image-memorability-4/5/32/33/34/35（核验修正 4）] [verify image-memorability 遗漏 2/3/8]。

**[D6] AI 提示词侧：阶段只以每词中文标签进入 content 提示词，群组混合阶段，例句后验证硬下限 15 字符会丢掉典型小学句，图意字段是为照片检索写的，加字段代价约 10 个文件；备选模型对小学例句是否更可靠没有证据。** 事实，高。
`"stages": [STAGE_ZH[s] …]` 字典下标——`words.STAGES` 加码而 `STAGE_ZH` 不加会 `KeyError` 整组失败；`AUDIENCE` 常量；一次调用只加载一份系统提示词；备选模型收到完全相同的提示词；`EXAMPLE_EN_MIN = 15` 会丢掉 "I like cats."（12），`PREFIX_MIN = 4` 对 ≤3 字母词只认精确形式与 `word_forms`；`image_keywords`/`image_alt_zh`（≤30 字）是为「照片检索」写的；加字段 = schema + 提示词 + 后验证 + pydantic 镜像 + `schemas.Content`（新字段必须 Optional）+ `types.ts` + `API.md` + `CLAUDE_INTEGRATION.md §4.1`（测试要求 schema 文件与文档代码块、fixture 逐字节相同）+ 4 处测试；提升 `PROMPT_VERSION` 不会让任何已 ready 的词重新入队（49 张旧卡不受影响）；面向小学生的内容/图片安全控制很薄（Wikimedia/Pexels 的 `mature=False` 是硬编码）；没有任何国产模型被真正调用过，评测成绩单不按阶段拆分。夜间整理因 `difficulty IS NULL` 的重复开销只在内容生成失败时发生、线上尚未出现（原文「每晚持续开销」为核验修正）。[ai-prompts-stages-1…16（核验修正 8/15）] [verify ai-prompts-stages 遗漏 1/2/3/4]。

---

## 3. 互相矛盾之处（逐条列出，并说明采信）

| # | 矛盾 | 采信 | 为什么 |
|---|---|---|---|
| 1 | 上海 2020 初中词表规模：provinces 1,655 词 + 140 词组；list-sources 1,722 + 309；shanghai-secondary 1,733 token / 1,731 唯一 + 379 词组 | **≈1,720–1,731 单词 + 331–342 词组**（手册 1733 + 335） | provinces 的解析漏掉每页首词（68 个页首词头中 60 个缺失，核验用 `\f` 换页符证明）；shanghai-secondary 的 1,733 含人为补回的重复 `hang`、379 含附表；list-sources 与 zhongkao-words 独立解析同为 1,722；差异只剩并列词是否拆分 [verify provinces-12] [verify shanghai-secondary-7] |
| 2 | 该 PDF 的出处：shanghai-secondary-7 推断「评价指南 PDF 不含词表，zhongkao-words README 归属不准确，词表来自考试手册」；list-sources-6 / provinces-12 称「官方件转载、机构未署名」 | **上海市教育考试院发布页同时挂出 `03.pdf`（指南）与 `07.pdf`（指南词汇表），后者 md5 与 mahavivo 副本相同——一手官方件** | 核验者下载并比对 md5（`059df9c0…`）；shanghai-secondary 只看了 `03.pdf`，zhongkao-words 的归属实际成立 [verify provinces-12 修正 1 / 遗漏 1] |
| 3 | 上海表「缺」的二级基础词：provinces-12 举例 apple/blue/cake/happy，约 65 个 | **54–56 个，几乎全是功能词与少量具体名词（a, an, he, I, my, the …）；apple/blue/cake/happy 都在表里** | 原例词正是被漏掉的页首词 [verify provinces-12 修正 3] |
| 4 | 上海表与现库「缺 29 个」（shanghai-secondary-19 / list-sources-6 缺 28 / provinces-26 缺 26） | **真缺 14 个** | 核验按 `word_forms` 拆分：12 个是库内原形的屈折形式、`o’clock` 是弯引号归一化假缺、`café`/`yogurt` 是拼写变体 [verify shanghai-secondary-19 / O5] |
| 5 | `中考英语词汇表.txt`：list-sources-7 1,897 词头 / 147 词组 / 91.8% 在库；provinces-25 写 1,774；shanghai-secondary-17 多词条目 8 个 | **1,887 词头（= `stats.json`，= 库中 `sources` 含 zk 的词数），6 个词组，100% 在库** | 只有生产正则 `build_seed.py:15-17` 的口径对应入库结果；list-sources 用了自己的近似解析把 `begin(began,begun)` 当词头；1,774 不知出处 [verify list-sources-7] [verify provinces-25] [verify shanghai-secondary-17] |
| 6 | 小学 mahavivo 词表：list-sources 440；seed-pipeline / verify 439；shanghai-primary 441 | **441 个非空行；生产 plain 解析得 439（丢 `a`、`I`）；在库 429/439** | 三个数字是三个口径：行数 / 去单字母 / 作者多算 1 行；入库口径是 439 [seed-pipeline-2] [verify list-sources-5] |
| 7 | 四表 vs 五表并集：list-sources-28 标题写「四表 1,521 / 179 / 210」 | **四表 1,365 / 170 / 160；五表 1,520 / 179 / 210** | 核验重算；作者表格与标题自相矛盾 [verify list-sources-28] |
| 8 | 国家三级 vs 上海：provinces-13 「仅课标 419」 | **303** | 作者把三级表后单列的数词/月份/星期算进三级表而上海侧未算附表——正是 provinces-1 自己提醒要排除的体例差异 [verify provinces-13] |
| 9 | 国家二级 505 对现库：provinces-24 「缺 6：excited, Mr, Mrs, Ms, o'clock, PE」 | **只缺 `excited`**；`o'clock` 在库，`Mr/Mrs/Ms/PE` 以 `mr./mrs./ms./p.e.` 在库 | 核验直接查 `lemma` [verify provinces-24] [verify shanghai-primary-21] |
| 10 | `中考表` 缺的 329 个三级词：provinces-25 「ECDICT zk 标签弥补大部分」 | **只补 137 个（41.6%）**，需重标 ≈190 词 | 核验逐词查 `stage_zk` [verify provinces-25 修正 3 / 遗漏 5] |
| 11 | 2025 修订高中词表：provinces-4 「3,221 词、新增 ≥291」 | **主表 3,104（≈官方 3100），新增 ≈205**；3,221 含 117 个国家/国籍附表词 | 作者两侧解析不对称 [verify provinces-4] |
| 12 | 全国卷省份数：provinces-6/29 「29 个」 | **28 个**（31 − 京津沪） | 作者自己在 provinces-19 列出的 11 + 17 = 28 [verify provinces-6] |
| 13 | 上海中考法定词汇基准：shanghai-secondary-3 「仍是 2004 标准（高）」 | **2004 标准只被 2020 年及以前的评价指南支持；2022 学年起课程计划以国家 2022 课标为依据，现行基准待查（中）** | 沪教委基〔2022〕17 号、沪教委规〔2019〕2 号、2026 版手册附录「新课标三级词汇（2022 版）」 [verify shanghai-secondary-3 / O2] |
| 14 | 索引方案成本：frontend-stages-12 「方案 A（小学 = 0）只改前端清单、更省」；stage-model-9 「办法 1（= 0）改动最小但有 0 值陷阱」 | **两案都要重建两张表；重编号 1..5 是现有「位置推导」代码的自然结果；= 0 需改写 `stage_to_index/index_to_stage` + 修 3 处 `or DEFAULT` 陷阱；都不便宜** | 核验者指出前端作者只算了前端口径 [verify frontend-stages-12] [stage-model-9] |
| 15 | 阶段常量数：stage-model-1 「9 个」 | **10 个**（+ `bank.py:85`、`eval_provider.py:107` 两处同类字面量） | 按作者自己的清单点数 [verify stage-model-1] |
| 16 | `Record<Stage>` 处数：frontend-stages-1 「4 处」 | **5 处 / 4 个文件** | 正文自己列了 5 处 [verify frontend-stages-1] |
| 17 | 小学词「5 个 chip 全满是常态」（frontend-stages-15） | **初中词只有 40.7% 带满四个标签，94% 带 ≥3 个；换行风险真实但非常态** | 线上 `GROUP BY` 标签数 [verify frontend-stages-15] |
| 18 | 2022 课标二级与上海学制：shanghai-primary-1 推断「二级跨越小五与初六」 | **课标明文：五四 3–5 年级参照六三 5–6 年级目标略降；二级 505 对应上海小学毕业** | 一手条款（课标 PDF 第 18/20 页） [verify shanghai-primary-1] |
| 19 | SVG 单价：image-memorability-17 / images-pipeline-20 「$0.0124/张」 | **$0.01237/次调用，$0.0140/张交付**（4/34 被拒） | 口径区分：调用 vs 交付 [verify image-memorability-17] |
| 20 | 照片任务：image-memorability-16 「除 1 个外全部失败」 | **49/49 失败；唯一照片来自 CLI** | `jobs` 表 `json_extract(status)`；`provider_state.last_ok_at` 与图片 `created_at` 相同 [verify image-memorability-16] [images-pipeline-28] |
| 21 | 失败归因：images-pipeline-29 「绝大多数任务根本没拿到候选（网络）」 | **≥27 个任务因冷却未发请求（成立）；11-02 的 18 个任务 Wikimedia 有应答（≤33 次请求、无冷却），失败原因未知** | 若有 429/5xx 会触发 15 分钟冷却，不可能出现 33 次请求 [verify images-pipeline-29] |
| 22 | Commons `filetype:drawing`「几乎零改动即可用」（images-pipeline-31） | **不是零改动**：原文件 `mime=image/svg+xml` 会被 `select.py:65-66` 拒，需 `iiprop` 加 `thumbmime` 并用它作候选 MIME | Commons API 实测三个 SVG 的 `thumbmime=image/png` [verify images-pipeline-31] |
| 23 | 黑名单副作用：images-pipeline-9 「weapon/gun/blood… 连 lemma 都不能作关键词，永远拿不到照片」 | **lemma 回退不过黑名单；`weapon` 的三个关键词均未被挡；其 SVG 不是黑名单造成** | `handler.py:78`、`content.py:183-184`；线上 `weapon` 内容关键词 [verify images-pipeline-9] |
| 24 | Openverse 匿名限额：images-pipeline-5 「官方未公开、DESIGN §9 是项目自测值」 | **响应头 `x-ratelimit-limit-anon_burst: 20/min`、`anon_sustained: 200/day` 就是当前生产限额** | 核验者一次匿名请求实测 [verify images-pipeline O1] |
| 25 | 万相接口路径（image-memorability-27） | **wan2.6 用 `/image-generation/generation`，≤2.5 用 `/text2image/image-synthesis`** | 官方 API 参考同页列两条路径 [verify image-memorability-27] |
| 26 | OpenAI `gpt-image-1`「2026-10-23 退役」（images-pipeline-37，第三方） | **未退役**；官方弃用页只列 dall-e-2/3（2026-05-12）与 gpt-image-1-mini/1.5（2026-12-01） | 一手弃用页 [verify images-pipeline-37] |
| 27 | Yun 2011 元分析「35 项研究」（image-memorability-9） | **10 项，n = 1,560** | Hao 2022 *ReCALL* 原文 + 第二来源 [verify image-memorability-9] |
| 28 | Brysbaert 2014 数据「官方下载 404」（image-memorability-4） | **Springer ESM xlsx 可下载（2.2 MB）；404 只对 crr.ugent.be** | 核验者下载并解析表头 [verify image-memorability-4] |
| 29 | 夜间整理「每晚持续开销」（ai-prompts-stages-15） | **机制存在但只在内容生成失败/滞后时触发；线上活跃生词 18 条中 0 条 `difficulty IS NULL`** | `bank_suggestions` 无 difficulty 行、`consolidation_runs` 4 次 done 均 `auto_applied 0` [verify ai-prompts-stages-15] |
| 30 | ECDICT 「2024-12-31 release 更新」（list-sources-2 汇总表） | **1.0.28 发布于 2017-09-20、资产更新 2018-05-20；2024-12-31 是 feed `updated` 时间戳，不是数据日期** | GitHub API release JSON [seed-pipeline-6] [verify list-sources-2] |
| 31 | 「ECDICT 无小学标签」置信度：stage-model 维持「中」；list-sources / seed-pipeline 为「高」 | **对 csv 基础版为高（8 个 tag 全集已算），对 release `stardict.db` 全集为中** | csv 的 zk 1,603 与库 100% 一致，但 csv 与 release 有 8 个种子词之差 [seed-pipeline-27] [verify seed-pipeline O5] |

---

## 4. 修正后的关键数字表（只放有证据的数字）

### 4.1 词表词量与现库 9,162 词的重合

| 词表（口径） | 词量 | 在库 | 已带目标阶段标志 | 备注 | 来源 |
|---|---|---|---|---|---|
| 现库 | 9,162 词条（word 9,004 / phrase 13 / abbr 26 / proper 119） | — | zk 2,099 · gk 3,829 · cet4 4,722 · cet6 7,671；`stage_min` 2,099 / 1,792 / 1,577 / 3,694 | 49 词有 AI 内容与 `difficulty`；31 词有图 | [stage-model-4] [verify list-sources-3] |
| ECDICT `ecdict.csv` 基础版 | 770,611 行；tag 8 值；zk 1,603 | zk 1,603 全在库 | — | release 1.0.28 `stardict.db` 851,288,064 B；8 个种子词不在 csv | [list-sources-2] [seed-pipeline-6/27] |
| mahavivo `中考英语词汇表.txt`（现 zk 来源，生产正则） | 1,887（6 词组） | 1,887（100%），全 `stage_min=1` | — | 7 行被正则丢弃 → `best`/`less` 不在初中层；来源不明 | [verify list-sources-7] |
| mahavivo `Highschool_edited.txt`（现 gk 来源） | 3,446 | 3,446（100%） | — | 旧高考 3500 谱系 | [verify list-sources-8] [shanghai-secondary-16] |
| mahavivo `小学英语大纲词汇.txt` | 441 行 → 439（生产 plain） | 429（97.7%） | `stage_min=1` 422；=2 共 6（an, are, color, favorite, maths, mum） | 缺 10 个屈折/称谓；与 2022 二级重合 415；推断 ≈ 2011 二级 423 + 变体（中） | [seed-pipeline-24] [verify shanghai-primary 遗漏 2] |
| 国家 2022 二级词汇表（小学） | 505（转录 docx，非官方；抽样 234 词与官方扫描一致） | 500（99.0%） | `stage_min=1` 495；=2 3（an, astronaut, maths）；=3 1（best）；=4 1（chore） | 真缺仅 `excited` | [verify shanghai-primary-21] [verify provinces-24] |
| 国家 2022 三级词汇表（初中，含二级） | 1600（主表解析 1,611） | 1,592（98.8%） | `stage_zk` 1,419（88.1%）；只 gk 138；只 cet 35 | 现 zk 2,099 中 680（32.4%）不在表内 | [verify provinces-25] |
| 国家高中课标 2017/2020 版 | 3000（主表解析 2,997；无星 1,525 / ★ 487 / ★★ 985） | 2,981（99.5%） | `stage_gk` 2,633（87.9%） | 现 gk 3,829 中 1,196（31.2%）不在表内；`Highschool_edited` 对它：共 2,519 / 超 927 / 缺 478 | [verify provinces-3/22] |
| 国家高中课标 2025 修订版（日常修订） | 3100（主表 3,104；+117 国家附表 = 3,221）；较 2020 版新增 ≈205 | 3,112（96.6%） | `stage_gk` 2,665（82.7%） | YR7429 提取 3,091 与 PDF 逐词一致，3,063 在库（99.1%）、2,621 带 gk；印发文号未找到 | [verify provinces-4/22] [verify shanghai-secondary-9/20] |
| 上海市初中英语词汇表（2020，考试院 `07.pdf`） | ≈1,720–1,731 单词 + 331–342 词组（手册 1733 + 335） | 1,702–1,703（98.3%） | `stage_zk` 1,393–1,394（80.5%）；在库但 `stage_min>1` 309（236 / 59 / 14） | 真缺 14；∩全国中考 1,286（74.3%）、仅沪 445 / 仅全国 601；∩国家三级 ≈1,308（75.9%）、仅沪 415（259 在国家高中表）/ 仅三级 303；⊂ `Highschool_edited` 1,583（91.5%）；现 zk 有 706 不在表内 | [verify provinces-12/13] [shanghai-secondary-8/19/21] |
| 上海中考手册年度词量（教辅转述） | 2013 1669 + 323；2020 1733 + 335；2025 1730 + 334；2026 1785 + 347（+273 新课标三级、+129 基本要求） | — | — | 2020 之后无机读 | [shanghai-secondary-5] |
| 牛津上海版 1A–5B（墨墨，按册相加，非官方） | 772（6A–9B 1,703） | — | — | 条目数含短语 | [shanghai-primary-10] |
| djfml `OXFORD.apkg`（牛津上海版小学，非官方） | 1,040 唯一 / 825 单词 | 769 单词（93.2%） | `stage_min=1` 671（87%） | 15 个屈折形、41 个低频具体名词/连字符词不在库；130 个在库词 `frq > 5000` | [shanghai-primary-13] |
| 人教 PEP 小学 3–6（有道/qwerty） | 849 → 819 唯一（110 词组） | 630/709 单词（88.9%） | `stage_min=1` 594 | 与 2022 二级重合 360 | [list-sources-13] [verify shanghai-primary-20] |
| DictionaryData「2016 高考英语词汇上海卷」 | 4,016–4,017（142 词组） | 3,706/3,874 单词（95.7%） | gk 层 75%；zk∪gk 76% | 948 超出全国高中层（780 在库属 cet / 168 不在库） | [list-sources-18/30] |
| DictionaryData「上海市初中英语教学基本要求 2008」 | 2,191（365 词组） | 1,681/1,826（92.1%） | `stage_min=1` 1,409 | 不规则动词各形式单列 | [list-sources-18] |
| qwerty `OxfordVocabulary_juniorMiddleSH.json` | 1,258（123 词组；91 个去空格脏词头） | 943/1,135 单词（83.1%） | — | 与上海 2020 表仅 47%；不建议 | [list-sources-11] |
| qwerty 中考核心 / 高考 3500 | 2,135 / 3,875 | 95.3% / 98.8% | — | 来源有道 | [list-sources-14/15] |
| 小学四表并集（mahavivo 439 ∪ PEP ∪ 沪教三起 ∪ djfml） | 1,365 | 1,195（170 不在库） | 160 在库但 `stage_min>1` | 五表（+上海六下）1,520 / 179 / 210 | [verify list-sources-28] |
| 初中七表并集 | 3,425 | 437 不在库 | 917 在库但 `stage_min>1` | | [verify list-sources-29] |

### 4.2 各来源许可状态

| 来源 | 许可 | 备注 | 来源 |
|---|---|---|---|
| skywind3000/ECDICT | MIT | 释义/音标/词频底座；无分级 | [list-sources-2] |
| 教育部课标（2011 / 2022 / 2017-2020 / 2025 修订） | 政府文件，未声明许可；《著作权法》第五条是否适用未核实 | 2022 扫描件需 OCR；社区转录（freemdict）非官方；2025 修订印发通知未找到 | [provinces-31] [verify list-sources 遗漏 4] |
| 上海市教育考试院《2020 评价指南·词汇表》 | 事业单位发布的考试文件，未声明许可 | 词头接近事实数据；释义/词性/选排可能是汇编作品 → 只取词头 | [verify provinces-12] [verify list-sources-32] [shanghai-secondary-23] |
| mahavivo/english-wordlists | 无 LICENSE（`LICENSE*` 404） | README 未说明中考/小学/上海/Highschool 来源 | [list-sources-4] |
| LinXueyuanStdio/DictionaryData | Apache-2.0（仓库作者声明） | 数据来源未说明（疑为背词 App 导出） | [list-sources-17] |
| kajweb/dict | 无（自述爬取有道） | 数据权利属有道/新东方/出版社 | [list-sources-9] |
| RealKai42/qwerty-learner | GPL-3.0（代码）；词书自 kajweb | 上海两条为社区贡献、未注明出处 | [list-sources-10] |
| KyleBing/english-vocabulary | BSD-3-Clause（镜像作者） | 上游有道 | [list-sources-16] |
| busiyiworld/maimemo-export | MIT 代码 + 「仅用于学习，禁止商用，词库版权归墨墨」 | 唯一覆盖上海三学段；只可作核验基准 | [list-sources-21] |
| lolo811109-crypto/zhongkao-words | 代码 MIT；内容 CC BY 4.0 | 词表 = 考试院表再解析；插画/例句 AI 生成未审校 | [list-sources-19] [shanghai-secondary-22] |
| YR7429/english-vocab-cn | 代码 MIT；内容 CC BY-SA 4.0 | 课标 3100 提取与 2025 修订 PDF 逐词一致 | [verify shanghai-secondary-9/22] |
| djfml/englishoxfordshanghaiedition | 无 | 教材衍生内容 | [shanghai-primary-12] |
| HF SwiftieJerry/english-vocabulary-materials | CC BY-NC-ND 4.0 | 禁商用/演绎 | [list-sources-25] |
| Pixabay | Content License：无需署名、不得独立分发；API：100 次/60 s、缓存 24 h、禁热链、**禁系统性批量下载** | 与全库预抓冲突 | [image-memorability-22] [verify images-pipeline O3] |
| Pexels | API 文档要求显著链接 + 署名；许可页 403 未核 | 200 次/h、20,000 次/月 | [images-pipeline-7/43] |
| Openverse / Commons | 逐图 CC 许可（白名单 CC0/PD/BY/BY-SA，NC/ND 拒）；BY/BY-SA 须署名 | 署名四字段已存并显示 | [images-pipeline-42] |
| 具体性常模 | Brysbaert 2014：Springer ESM 可下载、再分发未明示；Glasgow 2019 CC BY（5,553 词）；Lancaster 2020 CC BY 4.0（39,707 概念） | | [image-memorability-4/5] [verify image-memorability 遗漏 2/3] |

### 4.3 接口价格与限额（官方页，访问 2026-11-05；全库 = 9,162 × 单价，7.1 CNY/USD）

| 接口 | 单价 | 全库 | 限额/约束 | 来源 |
|---|---|---|---|---|
| Claude SVG（实测 `ai_calls`） | $0.01237/次；$0.0140/张交付（拒收 11.8%） | $113–128 ≈ ¥807–911 | 日子预算 $0.50 ≈ 35–40 张/天 → 229 天；`svg` 不走备选模型 | [verify image-memorability-17] [images-pipeline-20] |
| 智谱 CogView-3-Flash | 免费 | ¥0 | 并发/限流需登录查看；水印默认开 | [image-memorability-26] [images-pipeline-37] |
| 智谱 CogView-4 / GLM-Image | ¥0.06 / ¥0.10 每次 | ¥550 / ¥916 | 并发 V0–V3 5–20；URL 30 天；关水印需签免责声明 | 同上 |
| 百炼 wan2.2-t2i-flash / wan2.6-t2i | ¥0.14 / ¥0.20 每张 | ¥1,283 / ¥1,832 | RPM 120 / 60；URL 24 h；新用户免费额度 2026-10-29 下架 | [image-memorability-27] |
| 火山 Seedream 5.0-flash / 4.0 / 4.5 / 5.0-pro | ¥0.12 / 0.20 / 0.25 / 0.30（>2.61 MP 0.60） | ¥1,099 / 1,832 | 水印默认开；免费额度未见 | [image-memorability-28] |
| Gemini 2.5 Flash Image / 3 Pro Image | $0.039 / $0.134 | $357 ≈ ¥2,540 | | [image-memorability-29] |
| Recraft V3 位图 / 矢量 | $0.04 / $0.08 | $366 / $733 | 风格枚举含 Child book、Vector art | 同上 |
| qwen3-vl-flash / plus（评估候选图，二手价格） | 输入 ¥0.15 / ¥1 每 M token；800×500 图 = 402 token | 10 候选/词 ≈ ¥33 / ¥220 | 免费额度已下架 | [image-memorability-32] |
| GLM-4.6V-Flash（评估） | 官方标「完全免费」 | ¥0 | 图像 token 计法未写 | 同上 |
| Wikimedia Commons | 免费；无硬性日配额，须有意义 UA、串行、`maxlag` | 项目自限 1 req/s、2000/日 → 4.6–13.7 天 | 现未传 `maxlag` | [images-pipeline-4/46] |
| Openverse | 免费；匿名 20/min、200/day（实测头）；注册 100/min、10,000/day | 匿名 1 关键词/词 ≈ 57 天 | 项目本地 15/min、160/day；每次取 20 用 10 | [verify images-pipeline O1/O2] |
| Pixabay / Pexels | 免费 | — | 100 次/60 s；200 次/h 与 20,000 次/月（全库 1 关键词 = 46% 月配额） | [images-pipeline-6/7] |

---

## 5. 需要产品负责人拍板的问题（按影响排序）

**Q1. 「小学」在阶段模型里怎么编码？**（决定 0011 迁移、契约、difficulty 尺子，是其他一切的前置）
- 选项 a：重编号 1..5（xs=1 … cet6=5），一次停机迁移 `stage_min`/`current_stage` +1；代码最自然，但 `API.md`/`DESIGN.md`/`TASKS.md` 全部索引文字作废，`difficulty` 尺子要同步决定。
- 选项 b：小学 = 0，其余不动；数据不动，改两个映射函数为显式字典 + 修 3 处 `or DEFAULT` 陷阱；文档改动最少，但 0 值语义要写进契约。
- 选项 c：阶段改为数据（`stage_defs(code, scheme, rank, name_zh)` + `word_stage_tags`），字符串码；一次性把 10 份常量与「上海/全国」维度都解决，工作量最大。
- **建议**：若 Q3 决定要做地区维度，直接选 c（否则两次迁移）；若近期只做小学，选 a（现在线上只有 2 个用户、49 行 difficulty，重编号代价是历史最低点 [verify seed-pipeline O3]）。无论哪种，都需停机迁移、先 `DROP VIEW v_bank`、只能快照回滚。

**Q2. 「小学」词集用哪张表定义？**
- 选项 a：国家 2022 二级 505 词（官方、99.0% 已在库、许可风险最低、与上海小学毕业目标对应）。
- 选项 b：教材同步（牛津上海版 ≈772–825 / 新五四制沪教版词表未知 / PEP 819），按册/单元；但唯一机读源 djfml 无许可无来源，且牛津上海版已是上一代教材。
- 选项 c：a 为骨架 + 教材词作「拓展」标签（课标本身允许各地加 100–300）。
- **建议**：c，先上 505 核心（只需 OCR 校对 11 页并与转录件对账），教材标签等新教材词表出现再加。

**Q3. 上海 vs 全国：是「方案维度」还是「教材/地区标签」？**
- 选项 a：每用户 `region ∈ {sh, cn}`，服务端按方案解析阶段成员（上海 zk = 考试院 2020 表 ≈1,720；上海 gk = 暂无机读、用国家 3100 + 待补 200 词）。
- 选项 b：不做方案维度，只给词加 `sh_zk`/`sh_gk` 标签并在词库页提供筛选（信息展示，不改排序/推荐）。
- 选项 c：暂不区分，先把全国层对齐国家课标。
- **建议**：a 的数据模型（Q1-c）+ 先只落地初中层（证据充分：上海表 25% 不在国家三级、33.6% 的现 zk 不在上海表）；高中层等上海 200 词与手册词表取得后再做。

**Q4. 现有 zk/gk 是否按国家课标重标？**
- 选项 a：重标：`stage_zk` 对齐三级 1600（补约 190 词、把 680 个超纲词降为「拓展」），`stage_gk` 对齐 3100（1,196 个超纲词降级）。
- 选项 b：保留现状（旧考纲口径，覆盖更宽），只补缺口（修 `best/less/an`，补 505 词中漏标的 10 个）。
- 选项 c：a 的同时保留旧标志作「拓展」层（需要阶段集合能表达「拓展」）。
- **建议**：先做 b（零风险、修 bug），把 a/c 放进 Q1-c 的设计里一并评审，因为「拓展」本身就是第二维度。

**Q5. `difficulty` 尺子：小学共用 1 还是扩到 6？**
- 选项 a：共用 1（零代码，丢区分度，`COALESCE` 排序把小学词与初中词并列）。
- 选项 b：扩成 6 级（≈12 文件 + 3 个 JSON schema + `API.md §9` + `types.ts:73` + DB CHECK + 三份提示词 + `PROMPT_VERSION`）。
- **建议**：a 先行；线上只有 49 行非空，扩尺子可以等真实小学内容生成后再看是否需要。

**Q6. 新用户默认与引导：**
- 选项 a：改 DDL 默认为 K-12 预设（如 `["xs","zk"]`/xs）+ 加「小学生」角色 + `初中生` 预设含小学；
- 选项 b：保留 cet4/cet6 默认，只加角色；
- **建议**：a，且与 0011 同一次重建（改 DEFAULT 也要重建）。线上 2 个用户的 `stages_json` 迁移规则要在 0011 里写死。

**Q7. 配图策略（小学向）：**
- 选项 a：先改提示词、零代码：SVG 去掉底部英文词、加「exactly one central subject, plain background, kid-friendly」、`&` 转义；content 的 `image_keywords/image_alt_zh` 改为「与例句情境一致、无文字、无人脸特写」；按词 `stage_min` 选风格（小学 → 插画链）。
- 选项 b：接入生成式位图（CogView-3-Flash 免费试点 → CogView-4 ¥550 全库），需新 provider + CHECK 迁移 + 标识合规（显式 + 元数据隐式标识）+ 内容过滤兜底。
- 选项 c：照片链加插画过滤（Pixabay `image_type=illustration`、Openverse `category=illustration` + 放宽尺寸、Commons `filetype:drawing` + `thumbmime`）并申请 key；受 Pixabay 批量下载条款与 Openverse 限额约束，只适合按需抓。
- **建议**：a 立即做（并加失败词自动重试、补 journal 排查 11-02 的失败原因）；b 用 CogView-3-Flash 在 200 个小学词上试点并人工评分后再决定；c 作为 b 的对照组同步跑。任何方案都要先决定「图在回忆前还是回忆后出现」（需要新的展示挂点，`show_images` 现在只有全局开关）。

**Q8. 词表许可姿态：**
- 选项 a：只用官方文件（课标、考试院表）的**词头**，释义继续来自 ECDICT——与现有 `ATTRIBUTION.md` 做法一致，风险最低；
- 选项 b：引入有道系（kajweb/qwerty/KyleBing）或 DictionaryData 的教材词表与释义，需法律意见；
- **建议**：a；DictionaryData / maimemo 只作核验基准。

**Q9. 小学例句与内容规则：** `EXAMPLE_EN_MIN` 15 → ~10？`PREFIX_MIN` 放宽？释义改白话、搭配可空、助记改图像联想；是否 `force` 重生成 49 张旧卡。**建议**：先改提示词 + 把 `EXAMPLE_EN_MIN` 降到 10（同步 `CLAUDE_INTEGRATION.md §6.4`），旧卡不动。

---

## 6. 建议的下一步

### 6.1 设计评审应比较的方案维度

| 维度 | 要比较的方案 | 评审依据 |
|---|---|---|
| 数据模型 | 多加列（路线 A）vs `word_stage_tags` + `stage_defs`（路线 B）；索引 0 / 重编号 / 字符串码；「拓展」层如何表达 | [stage-model-9/16/17] [verify frontend-stages-12]；线上 ≈18,321 个 (词, 阶段) 对，2 万行 tag 表对 9k 词的查询规模可控（未实测） |
| 词表来源 | 小学：国家二级 505 骨架 + 教材拓展；初中：国家三级 1600 + 上海 2020 表（≈1,720）；高中：国家 2025 修订 3100 + 上海 200（待取）；清洗规则：屈折形式用 `word_forms`、并列拆分、英式/美式变体、句点缩写、词组（13 → 300+）如何入库 | 第 4.1 节；[seed-pipeline-12/13/16] |
| 地区标签 | 每用户 `region` 服务端解析 vs 词级标签筛选；前端由 `/api/stages` 驱动页签；阶段码是否带前缀 | [frontend-stages-22/23] [stage-model-18] |
| 配图策略 | 提示词层（SVG 去文字、风格按 `stage_min`）vs 生成位图（智谱/百炼/火山）vs 插画类照片链；评估手段（GLM-4.6V-Flash / qwen3-vl / CLIP 离线）；标识合规；图在回忆前/后；每词一图 vs 多图 | 第 2.D 节；[images-pipeline-30…41] [image-memorability-35] |

### 6.2 可以立即开始（不依赖拍板）

1. **修现有 zk 来源缺陷**：`build_seed.py:16 RICH_RE` 兼容全角括号/`=`（修回 `best`、`less`、`cafe`、`wolf…`）；`a (an)` 产出 `an`；plain 模式单字母白名单（`a`、`I`）。[verify list-sources-7/遗漏 3] [seed-pipeline-2] [verify shanghai-secondary O8]
2. **拿到官方词头清单**：OCR/校对 2022 课标附录 3（二级 11 页、三级 34 页）并与 freemdict 转录件逐词对账（二级已有 505 词机读版，抽样 234 一致）；用 `pdftotext` 从 2020 高中课标 PDF 取 3000 词（已可机读）。[verify shanghai-primary-21] [provinces-3/31]
3. **以考试院 `07.pdf` 为准重解析上海 2020 词表**（处理页首 `\f`、并列拆分、`a/an` 缺失），固定一个口径（建议 1,731 + 331）。[verify provinces-12] [verify shanghai-secondary-7]
4. **配图管线低风险修补**：SVG 提示词加 `&` 转义要求 / 在 `sanitize_svg` 前修复裸 `&`；Commons `iiprop` 加 `thumbmime`、传 `maxlag`；Openverse `PAGE_SIZE` 20→10；`failed` 词在被学习或冷却结束后自动重抓；更新文档 $0.028→$0.014、18 张/天→35。[verify images-pipeline O2/O5/O9/遗漏 1] [images-pipeline-36/39]
5. **测量而不是猜**：在出口正常的机器上对 200 个小学高频词跑 `wd fetch-image --no-svg` 并人工评分（照片命中率从未被测量）；读线上 journal 的 `provider_error/cooldown/skipped` 事件解释 11-02 的 18 次失败；用 CogView-3-Flash（免费）对同一批词生成并与 SVG 对照评分；测 Lancaster 常模对 9,162 词的覆盖率。[images-pipeline 未解决 6] [verify images-pipeline 未解决 1] [verify image-memorability 遗漏 3]
6. **申请 key / 注册**：Openverse 应用（10,000/日）、Pixabay、Pexels（并在浏览器人工核对 Pexels 许可页）。[verify images-pipeline O1/O3]
7. **0011 排练**：按 [stage-model-12/13] 的探针方式在副本上排练 `user_settings` + `words` 重建（含 `DROP VIEW v_bank`），一律走 `run_migrations`；写发布说明（停机、快照回滚、VACUUM）。
8. **把本目录的修正回写到 facts**：至少 provinces-12/13/24/25、list-sources-7/28/29、shanghai-secondary-19、image-memorability-9/16/17、images-pipeline-9/29/31/37 的数字（避免后续设计引用错误口径）。（已于 2026-11-05 回写）

### 6.3 需要等拍板

- 0011 迁移本身（Q1、Q6）与阶段枚举在后端/前端/文档/测试的扩展（≈ 迁移 100 行 + 后端 30–50 + 测试 70–120 + 脚本 20–40 + 文档 40–60 + 前端 30–50 行，[stage-model 第二节]）。
- 地区/方案模型与 `/api/stages` 契约变更（Q3）。
- 重标 `stage_zk/stage_gk`（Q4）与 `difficulty` 6 级（Q5）。
- 生成式图片 provider 接入与标识合规实现（Q7-b）；每词多图/候选选择（Q7）。
- content schema 新字段（如英文场景描述）与 `PROMPT_VERSION` 提升（Q9）。
- 引入任何有道系/DictionaryData 数据（Q8）。

---

## 未解决的问题（跨切片，只列尚无人能回答的）

1. 2022 课标二级 505 / 三级 1600 的逐词官方清单仍需 OCR 校对（扫描件无文字层）；教育部「2017 年版 2025 年修订」「2022 年版 2025 年修订」的印发通知/文号未找到。[verify provinces 未解决 1] [verify shanghai-primary 未解决 2]
2. 上海高考：考试院 200 个补充词的官方发布文件、《高考英语词汇手册（上海卷）》收词数、2016/2017 增删数字——均未获取；上海高中词表是最大的地区缺口。[shanghai-secondary 未解决 3/4] [provinces 未解决 2]
3. 上海中考现行法定词汇依据（2004 上海标准 vs 2022 国家课标）无 2022 年后的考试院文件；2026 年手册（1785 + 347）无机读版。[verify shanghai-secondary 未解决 2]
4. 2024 新编五四制沪教版小学 1–5 年级词表与词量（墨墨「沪教版…」条目是否即此套未确认）；牛津上海版 1A–5B 的权威去重词量。[shanghai-primary 未解决 3/4]
5. `中考英语词汇表.txt`（1,887）与 `Highschool_edited.txt`（3,446）的原始出处与年份。[verify provinces 遗漏 4]
6. ECDICT release `stardict.db` 的 tag 全集（本机只能查 csv）；`fetch_ecdict.sh` 钉死的 sha256 未整包校验；GNU gzip 能否复现 `a68127…`。[stage-model 未解决 4] [seed-pipeline 未解决 4/5]
7. 11-02 的 18 个 `fetch_image` 任务在 Wikimedia 有应答的情况下为何失败（需线上 journal）；打分/黑名单规则的真实命中率仍无数据。[verify images-pipeline 未解决 1]
8. 6–11 岁「卡通 vs 照片」、「图与例句义项不一致」的直接实证——没有找到。[image-memorability 未解决 1/2]
9. 本应用在《标识办法》下的主体定位与 SVG 文件隐式标识的实现方式；Pexels 许可原文。[verify image-memorability 未解决 5] [images-pipeline 未解决 2]
10. 生产服务器（Linux）的 SQLite 版本与重建耗时；`/usr/bin/sqlite3` 默认 `legacy_alter_table=1` 的来源。[verify stage-model 未解决 2/4]
