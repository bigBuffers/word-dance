# 词表来源与种子流水线 · 数据工程设计 — 把 `build_seed.py` 变成可声明、可测试、可复现的流水线

- 日期 2026-11-05 · 基线 `main @ 75df534`（所有 `path:line` 按此提交）· 线上库只读副本 `scratchpad/live-copy.db`（9,162 词）· 角度：数据工程
- 本轮默认假设 A1–A6（见任务书）；本文**采用 A1–A3 定义阶段成员，但重点是把规则写成代码与测试**。索引编码方案（INDEX Q1）、0011 迁移、前端枚举不在本线；本设计让种子与导入器对 Q1 的三种选项都只差一张表。
- 证据标注：`文件:行` 为我自己在 75df534 上打开确认过的代码；`[slug-N]`/`[verify slug-N]`/`[INDEX §x]` 指向调研文件；「预览」= 我在 `scratchpad/word-lists-data-eng/` 下用 `python3 -I` 对调研者的词表抽取件与 `live-copy.db` 只读副本重算的数字（脚本 `preview.py`、`closure.py`、`phrase_ecdict.py`、`richre.py`、`tagdist.py`），**不是最终词表文件的数字**——最终文件由本工作流另一条流水线产出到 `data/lists/`，本文只定义其格式与消费方式。

---

## 1. 一页结论

### 1.1 决定了什么

| # | 决定 | 一句话理由 |
|---|---|---|
| D1 | **阶段成员改为集合代数，由 `data/lists/manifest.json` 声明**：`xs = L2`；`zk = SH2020 ∪ L3`；`gk = (HS3100 ∪ HS3000) ∪ zk`（K-12 链做累计闭包）；`cet4 / cet6` 维持 `ECDICT tag ∪ mahavivo cet 表`。ECDICT 的 `zk`/`gk` 标签与 mahavivo 中考表、`Highschool_edited.txt` **退出阶段定义**，只留在 `sources` 作出处 | 现 zk/gk 是旧考纲口径（[INDEX A1]）；A3 只认官方词头；ECDICT release 的 tag 全集与 csv 完全一致、没有小学标签（§3.7 新核实） |
| D2 | **构建器从 222 行脚本改为可导入的包 `backend/wd/seedbuild/`**（`manifest.py` / `lists.py` / `normalise.py` / `build.py` / `diff.py`），`wd seed-build`、`wd seed-diff` 两个 CLI；`scripts/build_seed.py` 退为 3 行兼容入口 | 现脚本不可单元测试（`main()` 一体，`scripts/build_seed.py:72-177`），且 `RICH_RE`（`:16`）已被证明丢行（§3.3 R12） |
| D3 | **规范化规则写成 12 条带测试的函数**（§3.3）：Unicode 折叠、括注分类、并列拆分、缩写点规范、大小写与 lemma 冲突、屈折形式、派生副词、专名附表、词组、连字符/空格、英美变体、垃圾行；人工层只有两张 TSV：`aliases.tsv`（拼写→规范词头）与 `overrides.tsv`（逐行例外） | 每条规则都对应调研里的真实样例（`a (an)`、`best（…）`、`café`、`Mr`、`May`、`excited`、`angrily`、`hot-dog`、`although/though`） |
| D4 | **种子记录格式 v2**：`stages` 只是阶段码集合（无顺序含义），新增 `lemma`、`kind`、`aliases`、`variants`、`stage_sources`、`list_levels`、`seed_v`；导入器只多读 `kind` 与 `aliases`，其余忽略 | 让 `seed.py` 的 `stage_min` 从「元组位置 +1」（`seed.py:208`）改为查 `schemas.STAGE_ORDER`，与 Q1 解耦 |
| D5 | **词的宇宙单调**：上一版 `data/seed/vocab.jsonl.gz` 作为 `retain` 输入，任何词只会被重标，不会从种子消失；落到任何阶段之外的词（预览 249 个）`stage_min = NULL`，仍公开、可搜索、不入推荐 | 导入器从不删行（`seed.py:280-305` 没有 DELETE），若词从文件消失，旧的 `stage_*=1` 会**永久残留**——这是比「下架」更先要堵的洞 |
| D6 | **确定性与版本**：输出按 `(stage_min 的 rank, lemma)` 排序、`json.dumps(sort_keys=True, ensure_ascii=False)`、LF；`stats.json` 记 `content_sha256`（解压后字节）；`kv.seed_version` 改存 `content_sha256`；`gzip -9 -n` 只是运输格式 | Apple gzip 与 GNU gzip 的字节不同 [verify seed-pipeline-7]，按 .gz 文件哈希做版本会让 Mac 上的每次重打包触发一次空导入 |
| D7 | **差异报告**：`wd seed-diff OLD NEW`（新增 / 消失 / 每词阶段变化矩阵 / 字段变化 / 来源变化，md + json）与 `wd import-seed --dry-run [--report]`（对真实库：将插入 / 将更新及列 / 孤儿行 / 阶段迁移矩阵，零写入） | 上线前要能回答「这版种子会把线上哪些词从初中层拿掉」 |
| D8 | **导入语义不变**：仍是覆盖 20 个种子列的 UPSERT（`seed.py:72-82`）、不碰内容/用户表、不删词；只加 4 处小改（§3.6） | 现语义已被两轮分析实测确认（[seed-pipeline-10/19]、`WORD_LIBRARY_CURATION.md §1.2`） |
| D9 | **上海 331 个词组以 `kind='phrase'` 入库**，阶段 `zk`，释义来自 ECDICT；预览 91%（310/342）有 ECDICT 释义，其余 `translation = NULL`（UI 显示空短译，内容层 `meaning_zh` 补） | 词组是上海中考词表的正式组成部分 [INDEX B4]；现库仅 13 个 phrase（`live-copy.db`） |
| D10 | **不做「上海/全国」双方案、不做「拓展」阶段**（A4 交我决定）：`sources` 已完整记录每词来自哪张表，未来任一维度都可从种子物化，不必现在加列 | 加一个阶段码的代价 = 加 `xs` 的代价（10 份常量 + 契约，[INDEX A3]），本线不该再加一个 |

### 1.2 预览数字（用调研者的抽取件算的，最终以 `data/lists/` 为准）

| 项 | 现库 | A1–A3 新定义（预览） | 依据 |
|---|---|---|---|
| `xs` 成员 | — | 505 = 504 已在库 + `excited` | `preview.py`：L2 505 词头，504 命中 `words.lemma`（含 `mr/mrs/ms/pe → mr./mrs./ms./p.e.` 规范化） |
| `zk` 成员 | 2,099 | 2,022 词头 → 1,987 在库 + 34 新词（33 个在 ECDICT；`metr` 是抽取噪声） | 同上，S（1,722）∪ L3（1,608） |
| `gk` 成员 | 3,829 | 3,211 词头 → 3,173 在库 + 38 新词（26 个在 ECDICT；12 个是 `actor/actress` 类未拆并列，规范化后消失）；累计闭包再并入 `zk − gk` ≈ 150 词 | 同上，HS3100（3,095）∪ HS3000（2,997）；`closure.py` |
| `stage_min` 分布 | 1:2,099 / 2:1,792 / 3:1,577 / 4:3,694 | xs 504 / zk 1,483 / gk 1,313 / cet4 1,747 / cet6 3,866 / **NULL 249** | `preview.py` 迁移矩阵 |
| 旧 `stage_min=1` 的 2,099 词去向 | — | xs 499 · zk 1,093 · gk 270 · cet4 128 · cet6 33 · NULL 76 | 同上 |
| 旧 `stage_min=2` 的 1,792 词去向 | — | zk 300 · gk 674 · cet4 412 · cet6 230 · xs 3 · NULL 173 | 同上 |
| 旧 zk 词不在新 zk | — | 507；旧 gk 词不在新 gk：1,098 | 同上（INDEX 给的 680/706、1,196 是对单张表的数字） |
| 失去全部阶段的词 | 0 | 249（word 206 / proper_noun 26 / abbreviation 8 / phrase 9），**线上 77 条 `user_words` 与 49 条内容行无一命中** | `closure.py`：`airmail, armchair, bathtub, bookcase, bungalow, cd-rom …` |
| 词组 | 13 | ≈ 331 + 13 | `phrase_ecdict.py`：342 个抽取词头中 310 在 ECDICT、18 已在库 |

### 1.3 代价

本线约 **14 人日**（区间 12–16，§7.3），不含 Q1 的 0011 迁移、前端枚举、词表 OCR/抽取（另一条流水线）与 mahavivo CET 外部文件的获取。

---

## 2. 对照假设 A1–A6 的偏离与理由

| 假设 | 采用情况 | 偏离 / 补充 | 理由 |
|---|---|---|---|
| A1 小学 = 国家 2022 二级 505 | 采用 | **补充**：二级附表（数词、月份、星期、国家名）作为 `xs` 成员，通过 `moe-2022-appendix.tsv` 的 `group` 列声明，不规则动词附表不入（它们是屈折形式，走 `word_forms`）；manifest 可关 | 课标「单独列出」不等于「不要求」（[verify provinces-13] 正是因两侧附表口径不对称才算错 419）；但月份/星期等与现有词 `may`/`march`/`turkey` 共享 lemma，见 §3.3 R5 |
| A2 初中 = SH2020 ∪ L3；高中 = HS3100 ∪ HS3000 | 采用 | **偏离 1**：`gk := gk ∪ zk`（累计闭包，预览 ≈ 150 个上海初中词补进高中层）；**偏离 2**：考试院 200 个高中补充词在 manifest 里预留 `shmeea_gk_200`，`enabled: false` | 国家表自身是累计的（HS3100 含 1600，L3 含 505），上海独有词不在 HS 只是「上海初中先学了」，对一个上海高中生它仍是必备词；`xs ⊆ zk` 已由构造成立（预览 `|xs − zk| = 0`） |
| A3 只用官方词头，释义/音标/词频来自 ECDICT | 采用 | **明示**：ECDICT 的 `zk`/`gk` 标签也不再定义阶段（A3 没写）；`cet4/cet6` 仍用 ECDICT 标签 ∪ mahavivo CET 表；**小例外**：`overrides.tsv` 允许维护者为 ECDICT 义项明显不符的词**自写**一行释义（如 `bund`：ECDICT 为「(政治上的)同盟」，官方表指「外滩」；`mum`：ECDICT 为「菊花, 沉默」），这是我们自己的 MIT 文本，不是从官方文件复制 | ECDICT release 的 zk 1,603 词与 csv 完全一致（§3.7），其中 212 个只靠 ECDICT 标签才在 zk 层 [verify seed-pipeline O5]，它们多数不在现行课标 |
| A4 不按省份分层 | 采用 | 不做双方案、不做「拓展」阶段；超纲词 `stage_min = NULL` 保留 | §1.1 D10 |
| A5 配图 | 不涉及 | — | — |
| A6 新用户默认 / 迁移 | 不涉及 | 本线交付的是与 Q1 无关的种子格式和导入器；`stage_min` 的具体整数由 `schemas.STAGE_ORDER` 决定 | §3.6 |

**对 Q1 的依赖（必须说明）**：种子文件里 `stages` 是阶段码，不含索引；导入器用 `schemas.stage_to_index`（`schemas.py:56-61`）算 `stage_min`。Q1 选 a（重编号 1..5）→ 只改 `STAGE_ORDER`；选 b（xs = 0）→ 改 `stage_to_index/index_to_stage` 为显式字典，种子不变；选 c（字符串列）→ 导入器写字符串而不是索引，种子仍不变。本线不替 Q1 做决定。

---

## 3. 详细设计

### 3.1 阶段成员的集合代数与单调性

**结论**：五个阶段码 `xs, zk, gk, cet4, cet6`，rank 顺序即此；成员定义写在 manifest，构建器按下式计算并**断言**不变量：

```
L2      = heads(moe2022_l2) ∪ heads(moe2022_l2_appendix)                    # 505 + 附表
L3      = heads(moe2022_l3) ∪ heads(moe2022_l3_appendix)                    # 1600（含 L2）
SH      = heads(shmeea2020_words) ∪ heads(shmeea2020_appendix)               # ≈1,731 + 附表
SHP     = heads(shmeea2020_phrases)                                          # 331，kind=phrase
HS3000  = heads(moe_hs2020) ∪ heads(moe_hs_appendix)                         # 3000 + 117 国家/国籍
HS3100  = heads(moe_hs2025) ∪ heads(moe_hs_appendix)                         # 3100
CET4    = ecdict_tag(cet4) ∪ heads(cet4) ∪ (heads(cet46) ∩ heads(cet4))
CET6    = ecdict_tag(cet6) ∪ heads(cet6) ∪ (heads(cet46) − heads(cet4))      # 与 build_seed.py:128-142 相同

xs  = L2
zk  = SH ∪ SHP ∪ L3                 （断言 xs ⊆ zk）
gk  = HS3100 ∪ HS3000 ∪ zk          （累计闭包；断言 zk ⊆ gk）
cet4 = CET4 ;  cet6 = CET6          （不强制单调：现库 1,186 个四级词不在六级 [INDEX A1]，UI 文案「仅六级新增（不含四级）」依赖此语义）

stage_min(w) = min_rank{ s : w ∈ s }   ；无阶段 → NULL（"outside the lists"，0001_init.sql:185 注释的既有语义）
sources(w)   = sorted({ list_id : w ∈ heads(list_id) } ∪ {"ecdict"} if w 有 ECDICT tag)   # 空格连接写入 words.sources（seed.py:210）
stage_sources(w) = { s : [list_id …] }    # 结构化版本，导入器忽略（words 表无列），diff/报表用
list_levels(w)   = { "moe_hs2025": 0|1|2, "moe_hs2020": 0|1|2 }   # ★ 等级，导入器忽略
```

**为什么这样（依据）**

- 「每词一个阶段集合」必须保留，旗标组合有 15 种、不是区间 [stage-model-4]；闭包只做在 K-12 链上，因为国家表自身累计（HS3100 说明「含 1600 个单词」[verify shanghai-secondary-9]；L3 说明「含二级词汇 505 个」[verify list-sources-26]），而四六级表不是。
- 一个词在多张官方表里时：阶段取并集；`sources` 记全部 list_id（现库 `sources` 就是这样记的，如 `'cet4 cet46 ecdict gk zk'`，`0001_init.sql:188`）。`sources` 当前无读取者 [stage-model-15]，所以改它零风险。
- `stage_min` 用 rank 而不是「过滤后第一个」：`seed.py:208` 与 `services/ecdict.py:177` 的 `STAGES.index(stages[0]) + 1` 在 Q1-b（xs = 0）下会错，统一改为 `min(stage_to_index(s) for s in stages)`。
- 单调性结果（预览）：`xs ⊆ zk` 成立；`|zk − gk| = 152`（143 个上海独有词、8 个 L3 独有词、1 个 `an` 的抽取伪影），闭包后 gk 的「新增」= `stage_min = gk` 不受影响（这些词的 `stage_min` 是 zk）。

### 3.2 官方词表如何进仓库：`data/lists/`

**结论**：目录 `data/lists/`（本文开写时不存在，`ls data` 只有 `licenses`、`seed`；写作期间另一条流水线已放入 11 个文件，见本节末的对账），**文件忠于原件记法，规范化全在代码里**；manifest 声明每个文件的用途、期望计数与 sha256；README 放 provenance 表。mahavivo 的 CET 文件继续留在仓库外（`WORDLISTS_DIR`），不再分发。

#### 3.2.1 目录与文件

| 文件 | 内容 / 格式 | 期望计数 | 来源（另一条流水线产出；本列是验收口径） |
|---|---|---|---|
| `manifest.json` | 声明式清单，§3.2.3 | — | 本线 |
| `README.md` | provenance 表 + 许可说明 + 文件格式说明 | — | 本线 |
| `moe-2022-l2.txt` | 一行一词头；`#` 注释；原件记法（`colour (color)`、`a/an`、`PE (=physical education)`） | 505 | 教育部 2022 课标附录 3 二级表，扫描件 `W020220420582349487953.pdf`（31,502,213 B，无文字层，需 OCR + 与 freemdict 转录件对账 [verify list-sources 遗漏 1] [verify shanghai-primary-21]） |
| `moe-2022-l3.txt` | 同上（含二级 505；原件的 `*` 标记可保留为行尾 `\t*`） | 1600 | 同一 PDF 第 105–138 页 |
| `moe-2022-appendix.tsv` | 表头 `head\tgroup\tlevel`；`group ∈ number, month, weekday, country, nationality, language, irregular_verb`；`level ∈ l2, l3` | 待定 | 同一 PDF 单列附表 |
| `moe-hs-2020.tsv` | `head\tstar`（0/1/2） | 3000（抽取 2,997 [verify provinces-3]） | 教材〔2020〕3 号附件 zip 内英语 PDF（7,750,611 B，可机读） |
| `moe-hs-2025.tsv` | `head\tstar` | 3100（主表 3,104 / YR7429 提取 3,091 逐词一致 [verify provinces-4] [verify shanghai-secondary-9]） | 2025 日常修订版 PDF（非官方镜像，印发文号未见 → README 标「学界已采用、文号待补」） |
| `moe-hs-appendix.tsv` | `head\tgroup`（country / nationality） | ≈117 | 同上附表 |
| `shmeea-2020-words.txt` | 一行一词头，原件记法（`although/though`、`exam=examination`、`begin (began, begun)`、`bund (the Bund)`） | ≈1,731（口径见 §3.7） | 上海市教育考试院 2019-09-26 发布页 `download/20190926/07.pdf`，md5 `059df9c02684bd989fff6f8849ee1993`，与 mahavivo 转载件相同 [verify provinces-12] |
| `shmeea-2020-phrases.txt` | 一行一词组，原件记法（`a bit (of)`、`add…to`、`agree with sb.`、`a lot of/lots of`） | 331 [verify shanghai-secondary-7] | 同一 PDF 词组段 |
| `shmeea-2020-appendix.tsv` | `head\tgroup`（country 13 / subject 6 / number / month / weekday） | 待定 | 同一 PDF 附表（代词表不入：全是普通词头） |
| `aliases.tsv` | `spelling\tcanonical`：`Mr\tMr.`、`Mrs\tMrs.`、`Ms\tMs.`、`PE\tp.e.`、`A.M.\ta.m.`、`hot-dog\thot dog`、`o’clock\to'clock` | ≈20 | 本线（人工，带 `#` 理由） |
| `overrides.tsv` | `list_id\traw\taction\tvalue`：`action ∈ drop, head, kind, display, translation, variant_of, stages` | ≈10 | 本线（人工） |

**格式规则**（写进 README，并由 `lists.py` 测试钉死）：UTF-8 无 BOM、LF、一行一条；空行与 `#` 开头行忽略（文件头部的 `#` 来源注释正是靠这条规则共存）；行内 `\t#` 之后为注释；TSV 第一个非注释行是表头，词头列由 manifest `head_column` 指定（默认 `head`），其余列按 `level_column` / `group_column` 取用；**词头列**不得含中文释义、音标、词性（A3；`lists.py` 对词头列遇到 CJK 直接报错，这也是「只取词头」的机械保证），附表 TSV 的其他列（如国家中文名）允许。

**与已落地文件的对账（2026-11-05 23:52，另一条流水线已写入 `data/lists/`，本设计不改它们）**：已有 `moe-2020-senior.tsv`、`moe-2020-senior-appendix.tsv`、`moe-2025rev-senior.tsv`、`moe-2025rev-senior-appendix.tsv`、`moe-senior-2020-vs-2025.diff.txt`、`moe-senior.README.md`、`shmeea-2020-junior.txt`、`shmeea-2020-junior-phrases.txt`、`shmeea-2020-junior-appendix.tsv`、`shmeea-2020-junior-forms.tsv`、`shmeea-2020-junior.README.md`——命名与上表不同，但 manifest 以 `path` 绑定文件，**以落地命名为准**（上表的文件名只是占位）；每个文件自带 `#` 来源头（URL、md5、页码、规则），与本节 README provenance 表的列一一对应，可直接汇总；`shmeea-2020-junior-forms.tsv`（括号内词形：不规则变化、复数、英美拼写、变体/全称）正是 §3.3 R2/R6 的输入，构建器应读取它而不是自己再去猜括注；高中附表的列为 `国家(中文) / COUNTRY n. / PERSON n. / RELATED ADJECTIVES`，由 `head_column: "COUNTRY n."` 加 `extra_head_columns` 取国名与国籍。二级/三级（`moe-2022-l2/l3`）与 `aliases.tsv`/`overrides.tsv` 尚未落地。

#### 3.2.2 README provenance 表（列定义）

`id · 文件 · 原件 URL · 获取日期 · 原件 sha256/md5 · 解析规则（页码范围、分栏、页首 `\f` 处理、并列/括注保留）· 期望计数与实得计数 · 与独立抽取件（zhongkao-words 1,722 / YR7429 3,091 / freemdict 转录）的对账结果 · 许可说明`。许可说明统一写：课标与考试院词汇表为政府/事业单位发布的考试文件，未声明许可，本仓库只收录**词头清单**（接近事实数据），不复制释义、词性、音标与版式（[verify list-sources 遗漏 4] 的「词头 vs 释义」区分）；2025 修订版标「非官方镜像、印发文号待补」。

#### 3.2.3 `manifest.json`（声明式；`backend/wd/seedbuild/manifest.schema.json` 校验，`jsonschema` 已是运行依赖：`backend/requirements.txt:9`）

```json
{
  "version": 2,
  "stage_rank": ["xs", "zk", "gk", "cet4", "cet6"],
  "cumulative": ["xs", "zk", "gk"],
  "ecdict": {"release": "1.0.28", "zip_sha256": "ea01f76a3b3351021ce47077e89234465cc9441c8793054495320d06c0c3f3f6",
             "stage_tags": {"cet4": "cet4", "cet6": "cet6"}, "exam_tags": ["ky", "toefl", "ielts", "gre"]},
  "retain_previous_seed": "data/seed/vocab.jsonl.gz",
  "aliases": "aliases.tsv", "overrides": "overrides.tsv",
  "lists": [
    {"id": "moe2022_l2", "path": "moe-2022-l2.txt", "format": "heads", "stages": ["xs"], "expect": 505, "sha256": "…", "source": "教育部 2022 课标附录3 二级"},
    {"id": "moe2022_l2_appendix", "path": "moe-2022-appendix.tsv", "format": "tsv", "stages_by": {"column": "level", "map": {"l2": ["xs"], "l3": ["zk"]}}, "exclude_groups": ["irregular_verb"]},
    {"id": "moe2022_l3", "path": "moe-2022-l3.txt", "format": "heads", "stages": ["zk"], "expect": 1600},
    {"id": "shmeea2020", "path": "shmeea-2020-words.txt", "format": "heads", "stages": ["zk"], "expect": 1731, "tolerance": 5},
    {"id": "shmeea2020_phr", "path": "shmeea-2020-phrases.txt", "format": "phrases", "stages": ["zk"], "kind": "phrase", "expect": 331},
    {"id": "shmeea2020_appendix", "path": "shmeea-2020-appendix.tsv", "format": "tsv", "stages": ["zk"]},
    {"id": "moe_hs2020", "path": "moe-hs-2020.tsv", "format": "tsv", "stages": ["gk"], "level_column": "star", "expect": 3000, "tolerance": 5},
    {"id": "moe_hs2025", "path": "moe-hs-2025.tsv", "format": "tsv", "stages": ["gk"], "level_column": "star", "expect": 3100, "tolerance": 10},
    {"id": "moe_hs_appendix", "path": "moe-hs-appendix.tsv", "format": "tsv", "stages": ["gk"]},
    {"id": "shmeea_gk_200", "enabled": false, "note": "考试院高考 200 补充词：无机读件 [INDEX B7]"},
    {"id": "cet4", "external": "CET4_edited.txt", "format": "mahavivo_rich", "stages": ["cet4"], "sha256": "…", "expect": 4539},
    {"id": "cet6", "external": "CET6_edited.txt", "format": "mahavivo_rich", "stages": ["cet6"], "sha256": "…", "expect": 2220},
    {"id": "cet46", "external": "CET_4+6_edited.txt", "format": "mahavivo_plain", "stages_rule": "cet4_if_in:cet4|else:cet6", "sha256": "…", "expect": 8008},
    {"id": "cet6star", "external": "英语六级词汇（星标，1726）.txt", "format": "mahavivo_plain", "flag": "cet6_star", "sha256": "…", "expect": 1721}
  ]
}
```

要点：`external` 条目相对 `--wordlists DIR` 解析（Makefile `WORDLISTS_DIR` 保留，只装 4 个 CET 文件；`中考英语词汇表.txt` 与 `Highschool_edited.txt` 不再读取）；`sha256` 让「上游文件变了」显式失败而不是悄悄改种子；`expect` + `tolerance` 把 INDEX §4.1 的计数变成构建断言；`stage_tags` 只映射 cet4/cet6（D1）。

#### 3.2.4 ATTRIBUTION / licenses / Makefile 的变化

- `data/seed/ATTRIBUTION.md` 继续由构建器生成（现 `scripts/build_seed.py:176-177, 201-219`），内容从 manifest 渲染：ECDICT（MIT）一节不变；第 2 节改为「官方词表（只用词头）」列出 manifest 里 `enabled` 的官方条目与 README 链接；第 3 节「mahavivo CET 表（只用词头，不分发）」。
- 根 `ATTRIBUTION.md` §2（`ATTRIBUTION.md:19-32`）改写同上，表格列出 `中考英语词汇表.txt` / `Highschool_edited.txt` 已停用；`:14`「9,162 records」改为引用 `stats.json`。
- `data/licenses/` 不新增文件（官方文件无许可文本可放）；在 README 里写明法律定性与「只取词头」。
- `Makefile:93-98` `seed` 目标：`$(WD) seed-build --manifest data/lists/manifest.json --ecdict "$(ECDICT_DB)" --wordlists "$(WORDLISTS_DIR)" --out data/seed --strict && scripts/pack_seed.sh`；`:98` 的 `zcat` 改 `gzip -dc`；新增 `seed-diff`（对 `git show HEAD:data/seed/vocab.jsonl.gz`）与 `seed-check`（`pack_seed.sh --check` + `content_sha256` 比对）。`ECDICT_DB` 在 Mac 上指向已校验的 `scratchpad/ecdict-dl/extract/stardict.db`（851,288,064 B，§3.7），因为 `deploy/fetch_ecdict.sh:23` 的 `df --output` 在 BSD 下不可用 [seed-pipeline-8]。

### 3.3 规范化规则（逐条：规则 → 函数 → 例子 → 对现库的影响）

**结论**：全部规则在 `backend/wd/seedbuild/normalise.py`，纯函数、表驱动测试；最终 lemma 一律 `wd.services.words.normalise_lemma(fold(head))`（`words.py:183-189`），并在测试里断言「构建器预测的 lemma == 导入器算出的 lemma」，这样重复词头的合并在构建期就发生，不会再依赖导入器的「先到先得」（`seed.py:274-277`）。

| # | 规则 | 函数 | 例子 | 对现库的影响（`live-copy.db` 只读查得） |
|---|---|---|---|---|
| R1 | **Unicode 折叠**：NFKC → 弯引号/撇号/破折号转 ASCII（复用 `words._CHAR_MAP`，`words.py:69-87`）→ 全角 `（）＝／` 转半角 → **去除组合变音符**（NFD 后丢 `Mn`）→ 空白压缩 | `fold(text) -> str` | `o’clock → o'clock`；`café → cafe`；`best（good…）→ best(good…)` | `o'clock` 在库（`stage_min 1`），消灭 [verify shanghai-secondary-19] 的「假缺」；`cafe` 在库 `stage_min 3`（`sources 'cet4 cet46 ecdict'`）→ 进 zk；`words._clean` 不去变音符，所以这一步必须在构建器做，否则 `café` 会成为新 lemma |
| R2 | **括注分类**：`head (note)` 的 `note` 四类：① 含 CJK 或逗号分隔多项 → 屈折说明，丢弃（`begin (began, begun)`、`best（good, well 的最高级）`、`bad (比较级 worse…)`）；② `=X`/`= X` → **展开**，`X` 成为同阶段的第二个词头，`variants` 互链（`exam (=examination)`、`PE (=physical education)`、`bike (=bicycle)`）；③ 单个字母串且与 head 不同 → **拼写/口语变体**，同阶段第二个词头，互链（`colour (color)`、`centre (center)`、`father (dad)`、`a (an)`）；④ 其他（`the Bund`、`a.m.`）→ 记入 `unparsed_notes`，由 `overrides.tsv` 决定 | `classify_note(head, note) -> NoteKind`；`split_head(raw) -> list[Head]` | HS3100 原件 59 行含括号、SH 词表 136 行（绝大多数是①）；`a (an)` 在中考表里只取到 `a`，`an` 在库但 `stage_zk=0, stage_min=2` [verify shanghai-secondary O8] → 新规则下 `an` 进 xs | `color/favorite/math/center` 现 `stage_min 2`（如 `color` `0|1|1|0|2`）→ 与英式形同阶段；两者都已是独立 lemma，不能做 `word_forms`（词头守卫 `seed.py:239-241`），所以只能「同阶段 + `variants` 互链」 |
| R3 | **并列拆分**：`X/Y`、`X=Y` → 两个词头，同阶段，`variants` 互链 | `split_head` | SH 词表 7 行（`although/though`、`bicycle/bike`、`exam=examination`、`grandma=grandmother`…）；HS3100 12 行（`a/an`、`actor/actress`、`policeman/policewoman`…） | 预览里 12 个「gk 新词」全是未拆并列，拆后消失；`though`、`bike` 都已在库 |
| R4 | **缩写点规范**：`aliases.tsv` 把官方表的无点写法映射到库内/ECDICT 的有点规范形；未映射的无点大写缩写若 ECDICT 只有有点形，则自动取有点形并把无点形写入 `aliases`（→ `word_forms(kind='alt')`，§3.6） | `canonical_abbrev(head, aliases) -> (canonical, [alias…])` | `Mr → Mr.`（ECDICT `Mr.` zk gk「阁下, 先生」；`Mr` 无点条目是「[计] 存储器回收程序」）；`Ms → Ms.`（无点 `MS` 是「美国微软公司」）；`PE → p.e.`（`PE` 是「[计] 相位编码」）；`A.M. → a.m.` | 现库 15 个带点 lemma（`a.m, a.m., b.c., dept., i.e., miss., mr., mrs., ms., no., p.c., p.e., p.m., u.n., u.s.a.`）；L2 的 `mr/mrs/ms/pe` 四个「缺词」[INDEX §3 #9] 全部落到现有行；`a.m`（无尾点，来自 CET 表）与 `a.m.` 是两行重复 → `a.m` 作为 retain 词保留但无阶段，列入 diff 报告的「重复变体」 |
| R5 | **大小写与 lemma 冲突**：lemma 一律小写（`ux_words_lemma`，`0001_init.sql:205`）；display 取 ECDICT 原形；同 lemma 的多个词头在构建期合并（阶段并集、`sources` 并集、display 取先出现的 ECDICT 命中）；`I` 的 `kind` 由 overrides 设为 `word`（`derive_kind` 把首字母大写判为 `proper_noun`，`words.py:143-151`，现库 `i` 是 `proper_noun` [seed-pipeline-31]） | `merge_heads(heads) -> dict[lemma, Head]` | 附表 `May`（月份）与情态动词 `may`、`March/march`、`Turkey/turkey`、`China/china` | 现库 141 个 display 含大写、78 个在 zk 层 [seed-pipeline-31]；月份/国名已多数在库（来自旧中考表）；合并后 `may` 这一行同时承担两义，ECDICT `may` 的译文含「五月」，可接受并写进 README；`kind` 覆盖需要导入器读 `rec["kind"]`（§3.6 改动 2）——这是对 DESIGN §3.2「kind 派生」契约的一处放宽，必须同步改 `docs/DESIGN.md:206` |
| R6 | **屈折形式 vs `word_forms`**：官方表把屈折形当独立词头列出（多为分词形容词）→ **官方词头优先**，建独立 `words` 行（ECDICT 对这 12 个都有独立条目与 `0:` 指针：`excited` frq 3426、`frightened` 5786、`lost` 2675…）；不在任何官方表里的屈折形仍只走 `word_forms`。导入器的词头守卫（`seed.py:239-241`）自动不再把 `excited` 作为 `excite` 的形式插入；搜索 `excited` 直接命中新词头 | `is_inflection_headword(head, ecdict_row) -> bool`（只用于统计） | SH 的 12 个「屈折假缺」`embarrassed, excited, frightened, frightening, frozen, lost, satisfied, satisfying, stuck, surprised, underlined, united` [verify shanghai-secondary O5]；L2 的 `excited` | 现 `word_forms` 有 `excited→excite(p)`、`frightened→frighten(p)`、`lost→lose(p)`（我查）；导入后这些行消失、变成词头，`word_forms` 总数 −12 左右；`test_seed.py:348` 的 `14000 ≤ forms ≤ 14300` 仍成立 |
| R7 | **派生副词**：官方表列出的派生词成为词头（国家表体例「不列可推导派生词」只是不列，不是禁止；上海表列了） | 无特殊代码，走正常路径 | `angrily, beautifully, carefully, luckily, politely, quietly`（SH 真缺 14 中的 6 个，ECDICT 全有，frq 1603–8175） | 6 个新词，释义来自 ECDICT |
| R8 | **专有名词/数词/月份/星期/国家附表**：按 TSV `group` 入阶段；`irregular_verb` 组排除；`kind` 由 `derive_kind` 得 `proper_noun`（现有行为） | `lists.parse_tsv` + manifest `exclude_groups` | SH 附表 13 国家 + 6 学科；L2/L3 附表；HS 117 国家/国籍 | 现库 119 个 `proper_noun` 多数来自旧中考表的国名/月份 [seed-pipeline-31]；它们现在能继续留在 zk/gk 层（否则会落到 249 个无阶段词里的 26 个专名） |
| R9 | **词组**（`format: phrases`）：`fold` 后 `…`/`...` 规范为 ` ... `（NFKC 已把 `…` 变 `...`），保证含空格 → `derive_kind` 判 `phrase`（`words.py:145-146`；否则 `add...to` 会因含 `.` 被判 `abbreviation`，`words.py:147-148`）；`sb.`/`sth.` 保留（点号 token ≤ 6 字符通过严格归一化，`words.py:174-175`）；`(of)` 可选成分 → 两个词组（有/无），互链；`/` 并列 → 拆；`>4` token 的 5 个走导入器的宽松回退（`seed_row` `seed.py:180-181`，`normalise_input` 失败时用 `normalise_lemma`）；释义：ECDICT 精确匹配（先带 `sb.` 原形，再去可选成分） | `phrase_variants(raw) -> list[str]` | `a lot of/lots of → a lot of, lots of`；`a bit (of) → a bit, a bit of`；`add…to → add ... to`；`agree with sb.` | 预览 342 个抽取词组：含省略号 16、`sb./sth.` 19、括号 12、斜杠 25、撇号 14、>4 token 5、含点 35；ECDICT 命中 310、未命中 32（几乎全是 `sb./sth.` 与省略号型）；`kind='phrase'` 从 13 增至 ≈ 345；`VocabQuery.q` 的前缀搜索对 lemma 仍有效 |
| R10 | **连字符/空格变体**：`fold` 不改连字符；查 ECDICT 时依次试原形 → 空格↔连字符 → 去连字符（与 `build_seed.py:96-100` 的回退一致但三向）；多形共存且义项不同的写进 `aliases.tsv`/`overrides.tsv` | `ecdict_candidates(head) -> list[str]` | `hot-dog`：ECDICT `hot dog`「n. 热狗」、`hot-dog`「表演技巧」、`hotdog`（zk，「v. 卖弄」）→ alias `hot-dog → hot dog`；`e-mail`/`email`、`ice-cream`/`ice cream` | 现库 47 个含连字符 lemma、`ice cream`/`ice-cream` 并存、`E-MAIL` 被判 `proper_noun`（ECDICT display 全大写）→ overrides `display=e-mail` |
| R11 | **英式/美式**：课标以英式为准、美式括注 [verify shanghai-primary 遗漏 7]；R2③ 已覆盖；`variants` 字段让 UI 将来能显示「美式拼写 color」 | 同 R2 | `colour/color`、`favourite/favorite`、`maths/math`（ECDICT `maths` 有 `0:math` 指针） | 美式形同阶段，否则美式拼写的学习者会在「仅本阶段新增」里漏掉它们 |
| R12 | **垃圾行与未解析**：`lists.py` 不丢行——任何无法解析的行进入 `unparsed`；`--strict` 下若 `unparsed` 不被 `overrides.tsv` 覆盖则构建失败（仓库内官方文件）；外部 mahavivo 文件只告警并计入 `stats.unparsed` | `parse_* -> (entries, unparsed)` | 中考表 7 行：`best（…）`、`café [...]`、`less（…）`、`more（…）`、`practice(s)e`、`silentˈsailənt]`、`wolf（复wolves）` [verify list-sources-7]；`practice(s)e` 必须 override | 虽然中考表退出阶段定义，`mahavivo_rich` 解析器仍服务 CET4/CET6 表（`build_seed.py:84-85` 用 rich 模式），同一类缺陷在那里同样存在 |

**`RICH_RE` 的修法（实验 `richre.py`，对 `zhongkao.txt` 跑）**：生产正则 `build_seed.py:16` 产出 1,887 词头、丢 7 行；先做 R1 折叠再用

```
HEAD  = [A-Za-z][A-Za-z'\-\.]*(?: [A-Za-z][A-Za-z'\-\.]*){0,3}
RICH2 = ^(?P<head>HEAD)(?:\s*\((?P<paren>[^)]*)\))?(?:\s*=\s*(?P<eq>HEAD))?\s*(?:\[|/|=|$|\s|[^\x00-\x7f])
```

可挽回 6/7 行（`practice(s)e` 仍需 override），`a (an)` 产出 `an`，`café → cafe`（R1）；但按 R2② 也会多出 `daddy, examination, grandfather, grandmother, math, mister, mistress, mum, mummy, personal computer, physical education, refrigerator, versatile compact disk`（`=` 展开）和 `s`（`manner(s)` 的括注）——因此 R2③ 要求括注至少 2 个字母，R2② 的展开词头需在 ECDICT 命中才成为词头，`mister/mistress` 这类展开由 `overrides.tsv` 标 `drop`。`plain` 模式的单字母白名单：`parse_list` 的 `len(line) == 1` 跳过（`build_seed.py:25`）改为「只跳过与节标题相同的单个大写字母，且 `a`/`I` 白名单」——对 CET 表无影响，对任何 `heads` 格式文件必要（L2 含 `a`、`I`）。

### 3.4 `build_seed.py` 的重构

**结论**：代码进包 `backend/wd/seedbuild/`（服务器运行时不导入它），`scripts/build_seed.py` 只剩 `from wd.seedbuild.cli import main; raise SystemExit(main())`；构建流程 9 步，全部确定性。

```
backend/wd/seedbuild/
  __init__.py
  manifest.py      Manifest / ListSpec dataclass；load(path) → jsonschema 校验 → sha256 核对 → 路径解析（repo / external）
  lists.py         parse_heads / parse_tsv / parse_phrases / parse_mahavivo(mode) → (list[RawEntry], list[Unparsed])
  normalise.py     fold / classify_note / split_head / canonical_abbrev / phrase_variants / merge_heads / lemma_of   （§3.3）
  ecdict_source.py 只读打开 stardict.db；tagged_rows(tags) 按 id 排序；lookup(head, candidates) ；复用 services/ecdict.py 的
                   Row.from_sqlite / word_columns 风格字段映射与 norm_phonetic（services/ecdict.py:34-36 已镜像构建器的音标规则）
  build.py         build(manifest, ecdict_db, wordlists_dir, previous_seed, out_dir, strict) -> BuildStats
  diff.py          load(path) → dict[lemma, rec]；diff(old, new) → Report；render_md / render_json
  cli.py           seed-build / seed-diff 子命令（注册到 cli.CLI_MODULES / COMMAND_OWNERS，cli.py:31-56；test_cli.py:51-58 会检查）
  manifest.schema.json   （pyproject package-data 加 "seedbuild/*.json"，backend/pyproject.toml:27-28）
```

**构建步骤（`build.py`）**

1. 读 manifest，校验 schema；对仓库内文件核 `sha256`（不符 → 失败），外部文件核 `sha256`（不符 → `--strict` 失败，否则告警）。
2. 逐表解析 → `RawEntry(list_id, raw, level, group)`；`heads` 格式按 R1–R4、R10 得 `Head(text, lemma, kind_hint, relation, parent)`；`phrases` 按 R9；`tsv` 加 `level/group`；`mahavivo_*` 用修正后的正则；期望计数 ± tolerance 断言。
3. 应用 `overrides.tsv`（按 `(list_id, raw)` 精确匹配）与 `aliases.tsv`。
4. 聚合 `membership[lemma][stage] = {list_id…}`，`levels`，`variants`，`aliases`；对 `cumulative` 链做闭包；断言 `xs ⊆ zk ⊆ gk`。
5. 宇宙 = ECDICT `cet4|cet6` 标签行（release 中 5,805 行，§3.7）∪ 所有列表 lemma ∪ `retain`（上一版种子的全部 lemma）。ECDICT 查询顺序：`word = ? COLLATE NOCASE` 精确 → alias 形 → 空格/连字符三向；retain 词优先按 `ecdict_id` 取（同一 release 内 id 稳定，§3.7），再按 word。
6. 不在 ECDICT 的官方词头：生成**最小记录**（`word`、`lemma`、`kind`、`stages`、`sources`，其余 `null`/空）并计入 `stats.missing_from_ecdict[list_id]`；`--strict` 下每表允许的缺失数上限由 manifest `max_missing`（默认 0.5%）控制。预览里官方词头不在 ECDICT 的只有抽取噪声（`metr`、`caf`）与未拆并列——真实缺失预期接近 0；词组预计 32 个。
7. `make_record_v2`：字段见 §3.4.1；`stages` 按 rank 排序；`sources` 排序；`lemma = words.normalise_lemma(fold(word))`；同 lemma 多词头 → `merge_heads`（R5）。
8. 排序 `(rank(stage_min) if stage_min else 99, lemma)`；写 `vocab.jsonl`（`json.dumps(rec, ensure_ascii=False, sort_keys=True)` + `\n`）；写 `stats.json`、`ATTRIBUTION.md`（由 manifest 渲染）。
9. 计算 `content_sha256`（`vocab.jsonl` 字节）写入 `stats.json`；返回 `BuildStats`。

**确定性保证**：sqlite 查询全部 `ORDER BY id`；任何 `set` 在输出前排序；无时间戳进入 `vocab.jsonl`（时间戳只在 `stats.json.built_at`，且 `--reproducible` 时省略）；`PYTHONHASHSEED` 无关（不依赖 set 顺序）；测试「构建两次字节相同」+「`content_sha256` 与 `stats.json` 一致」。`gzip -9 -n` 继续用于归档（`pack_seed.sh:78`），但版本判断不再看 .gz 字节（§3.6）。

#### 3.4.1 种子记录 v2（`seed_v: 2`；导入器只读标 ✓ 的键）

| 键 | 含义 | 导入器 |
|---|---|---|
| `word` | display（ECDICT 原形；无 ECDICT 时为官方词头折叠后的原形） | ✓（`seed.py:174-177`） |
| `lemma` | 构建器预测的 lemma（`words.normalise_lemma(fold(word))`） | 读并校验：与自己算的不等 → 告警计数 `lemma_mismatch`（不改行为） |
| `kind` | `word/phrase/abbreviation/proper_noun`，仅在 overrides 设定或 `format: phrases` 时出现 | ✓ 新增：合法则覆盖 `derive_kind` |
| `phonetic, translation[], definition[], pos, collins, oxford, bnc, frq, exchange{}, exam_tags[], ecdict_id, cet6_star` | 同 v1（`build_seed.py:183-198`） | ✓ 不变 |
| `stages[]` | 阶段码集合，按 rank 排序 | ✓ `stage_*` 旗标 + `stage_min = min(stage_to_index)` |
| `sources[]` | `ecdict` + list_id… | ✓（空格连接，`seed.py:210`） |
| `aliases[]` | 官方表的其他拼写（`mr`、`hot-dog`） | ✓ 新增：写 `word_forms(form, word_id, 'alt')`（INSERT OR IGNORE；形式等于某 lemma 时跳过） |
| `variants[]` | 互链的变体 lemma（`color`） | 忽略 |
| `stage_sources{}` | `{stage: [list_id…]}` | 忽略 |
| `list_levels{}` | `{moe_hs2025: 0|1|2, moe_hs2020: …}` | 忽略 |
| `seed_v` | 2 | 忽略（diff 工具用） |

#### 3.4.2 `stats.json` v2 结构

```json
{"seed_v": 2, "content_sha256": "…", "total_words": 0, "builder": "wd.seedbuild 2", "ecdict_release": "1.0.28",
 "per_stage": {"xs": 0, "zk": 0, "gk": 0, "cet4": 0, "cet6": 0},
 "first_stage": {"xs": 0, "zk": 0, "gk": 0, "cet4": 0, "cet6": 0, "none": 0},
 "only_stage": {…}, "per_kind": {"word": 0, "phrase": 0, "abbreviation": 0, "proper_noun": 0},
 "per_source": {"moe2022_l2": 505, "shmeea2020": 0, "...": 0},
 "stage_by_source": {"zk": {"shmeea2020": 0, "moe2022_l3": 0, "both": 0}},
 "closure_added": {"gk": 0}, "variants": 0, "aliases": 0, "inflection_headwords": 0, "merged_heads": [["may", ["may", "May"]]],
 "missing_from_ecdict": {"shmeea2020_phr": ["add ... to", "..."]}, "unparsed": {"cet4": ["…"]},
 "retained_without_stage": 249, "lists": {"moe2022_l2": {"sha256": "…", "heads": 505, "expect": 505}},
 "with_phonetic": 0, "with_translation": 0, "with_definition": 0, "with_exchange": 0, "multiword": 0, "uppercase": 0, "file_bytes": 0}
```

`pack_seed.sh:44-47` 读 `total_words` 的用法不变；`--check` 增加 `content_sha256` 比对（`gzip -dc "$gz" | shasum -a 256`）。`stats.json` 的其他消费者只有文档（[seed-pipeline-20]）。

### 3.5 种子版本差异报告

**结论**：`wd seed-diff OLD NEW [--md out.md] [--json out.json]`，按 lemma 对齐（v1 记录没有 `lemma` 键时用 `words.normalise_lemma(word)` 现算，保证能比较 2026-10-14 的旧种子），输出：

1. 汇总：记录数、新增、消失（在 D5 下应为 0，非 0 则醒目告警）、阶段变化词数、字段变化词数。
2. **阶段迁移矩阵** `old stage_min × new stage_min`（§1.2 那张表的形态）与「每阶段旗标增减」。
3. 逐词清单（可按 `--only stages|fields|added|removed` 过滤）：`lemma · 旧 stages → 新 stages · 旧/新 sources · 变动字段名`。
4. 「值得人工看」的列表：失去全部阶段的词；新增且无 ECDICT 释义的词；`merged_heads`；`aliases` 新增；`kind` 变化。

实现 `diff.py` 不依赖数据库、不依赖 `Settings`（`wd seed-diff` 不读 `.env`）；`make seed-diff` 默认比较 `git show HEAD:data/seed/vocab.jsonl.gz` 与工作区。

### 3.6 `seed.py` 导入语义：现状、要改的 4 处、策略

**现状（已核实）**：`import_seed`（`seed.py:248-316`）读文件 → `seed_row`（`:167-214`）→ `_UPSERT_SQL`（`:72-82`）覆盖 20 个种子列并强制 `source='seed', is_public=1, is_valid_english=1, safe_for_sharing=1, merged_into_word_id=NULL`，`WHERE` 只是「任一列不同」；`_rebuild_forms`（`:218-245`）删非 `alt` 形式后重建；`kv.seed_version = sha256(文件)`（`:258, :287`）；`main.seed_check`（`main.py:307-319`）启动时比较同一哈希；`install.sh:168-169`/`main.py:482-485` 顺序都是先迁移后导种子。未知阶段码静默丢弃（`:184-185`）；`stage_min` 按元组位置（`:208`）。

**对线上词的影响**：新种子对已有 9,162 行全部是 UPDATE（阶段列、`sources`、少数 `kind`/`display`），不触碰 `active_content_id/difficulty/content_state` 与用户表（`:10-12` docstring，`test_seed.py:171-187`）；49 条内容、31 张图、77 条 `user_words` 不动（我查过：249 个将失去阶段的词里没有任何一条被持有或有内容）。

**要改的 4 处**

| # | 改动 | 位置 | 理由 |
|---|---|---|---|
| 1 | `STAGES`（`seed.py:43`）删除，改用 `schemas.STAGE_ORDER` 与 `stage_to_index`；`SEED_COLUMNS` 的旗标列由 `[f"stage_{s}" for s in STAGE_ORDER]` 生成（`:60-64`）；`stage_min = min(stage_to_index(s) for s in stages) if stages else None`（`:208`）；未知码计入 `SeedStats.unknown_stage_codes` 并告警一次 | `seed.py:43, 60-64, 184-185, 204-208` | 去掉 10 份常量中的 1 份 [verify stage-model-1]；与 Q1 解耦；`"xs"` 不再被静默丢弃 [stage-model-20] |
| 2 | `kind`：`rec.get("kind") in words.KINDS` 时采用，否则 `derive_kind(display)` | `seed.py:193` | R5（`I`）、R9（词组）、R10（`E-MAIL`）；同步 `docs/DESIGN.md:206`「kind derived」一行 |
| 3 | `aliases` → `word_forms(form, word_id, 'alt')`：在 `_rebuild_forms` 末尾 `INSERT OR IGNORE`，跳过等于任何 lemma 的形式；`alt` 行不会被下次导入删除（`:222` 只删 `kind != 'alt'`），所以移除别名需要手动清理——写进 docstring | `seed.py:218-245` | 让搜索 `mr`、`hot-dog` 命中规范词头（`vocab.py:41-42` 的前缀搜索已包含 `word_forms.form`） |
| 4 | 版本 = 内容哈希：新增 `seed_digest(path)`（流式解压后 sha256）；`import_seed` 用它与 `kv.seed_version` 比较并写入；`SeedStats` 保留 `sha256`（文件）并新增 `content_sha256`；`main.seed_check` 同步 | `seed.py:107-112, 258-263, 287`；`main.py:313-318` | D6；代价是升级后第一次启动必然导入一次（`kv` 存的是旧的文件哈希），日志 `0 inserted, N updated` |

**新增**：`wd import-seed --dry-run [--report PATH]`（`seed.py:356-360` 加参数）：读文件、`SELECT lemma, <20 列> FROM words WHERE source='seed'`（9k 行）在 Python 里比对，打印 §3.5 的 2/4 两项 + 「将插入 / 将更新（按列计数）/ 孤儿行（库里 `source='seed'` 但不在文件）」，不开事务、不写 kv、不写 `system_events`；`--report` 同样可用于真实导入（在事务提交后写文件）。

**策略**

- **删除/下架不再在种子中的词**：不做。D5 的 `retain` 使「不在新种子」成为构建错误而非运行时状态；孤儿行只在 dry-run 报告里出现。真正的下架属于 `WORD_LIBRARY_CURATION.md §2.4 阶段 C` 的审核/下架功能，不在种子线。
- **保留旧阶段**：不保留。旧旗标就是旧考纲口径，保留等于把两套口径混在同一列；需要「拓展」层时从 `sources`（含 `ecdict` 的 zk/gk 标签要另记：`exam_tags` 不含 zk/gk，所以 v2 在 `sources` 里保留 `ecdict_zk`/`ecdict_gk` 两个来源记号）物化。
- **`kv.seed_version`**：语义改为内容哈希（上文 4）；`kv.seed_imported_at`、`system_events('seed_imported')` 不变，`detail_json` 加 `content_sha256`。
- **`WD_SEED_PATH` 陷阱**（[seed-pipeline-14]）不变：仍只认一个文件；本设计不引入多文件合并，所有变化都进 `data/seed/vocab.jsonl.gz`。
- **运行时 ECDICT 路径的一致性**：`services/ecdict.py:173-177` 对用户新添的词按 ECDICT 标签赋 `stage_zk/gk`，与 D1 冲突（会给运行时词打上旧口径的初中/高中标签）。建议同一提交把 `STAGE_TAGS`（`ecdict.py:28`）改为只含 `cet4, cet6`，`stage_min` 用同一 `min(stage_to_index)`；影响 `test_words_resolve.py` 里按 ECDICT 行断言阶段的用例（需核对）。这是一个必须明说的决定点（§7.2 Q-d）。

### 3.7 对调研数字的使用与两处新核实

| 用途 | 采用的数字 | 来源 |
|---|---|---|
| 现库基线 | 9,162；2,099/3,829/4,722/7,671；`stage_min` 2,099/1,792/1,577/3,694；kind 9,004/13/26/119；`word_forms` 14,132；用户 2、`user_words` 77、内容 49、图 31 | `live-copy.db` 只读复算，与 [INDEX §4.1] 一致 |
| 上海初中表口径 | **≈1,731 单词 + 331 词组**（抽取件 S.txt 1,722 行缺 `a`/`an`，是 PDF 文本本身缺失 [verify shanghai-secondary O6]） | [verify provinces-12] [verify shanghai-secondary-7]；manifest `expect 1731, tolerance 5` |
| 国家表 | L2 505；L3 1600（抽取 1,611 含噪声）；HS2020 3000（抽取 2,997）；HS2025 3100（主表 3,104，YR7429 3,091 逐词一致）；附表 117 | [INDEX §4.1] |
| 真缺与假缺 | SH 真缺 14、屈折假缺 12、弯引号假缺 1、变体 2；L2 真缺只有 `excited` | [verify shanghai-secondary-19/O5] [verify shanghai-primary-21] |
| 现 zk 来源缺陷 | `RICH_RE` 丢 7 行；`best` 3、`less` 2、`cafe` 3、`an` 2 | [verify list-sources-7/遗漏 3]，`richre.py` 复现 |

**新核实 1（关掉 INDEX「未解决」6 与 stage-model「未解决」4）**：对 `scratchpad/ecdict-dl/extract/stardict.db`（851,288,064 B，3,402,564 行）只读统计：带 tag 的行 14,942，tag 全集与 csv 完全一致——`gre 7504, toefl 6974, cet6 5407, ielts 5040, ky 4801, cet4 3849, gk 3677, zk 1603`；**release 库没有任何小学/课标分级标签**，「ECDICT 无小学标签」从「中」升为「高」。四标签行 7,116，`cet4|cet6` 行 5,805（= D1 后 ECDICT 对宇宙的贡献）。

**新核实 2（可复现性基线）**：该库的 `stardict.id` 与现种子的 `ecdict_id` 逐一相同（`a` 7909、`a.m.` 15081、`abandon` 16425、`ability` 19124、`ice cream` 1451887、`ought to` 2159481），即它就是 2026-10-14 构建所用的同一 release——新构建器的第一个验收是「用它 + 旧 manifest（六张 mahavivo 表）重建出 `content_sha256` 与现 `vocab.jsonl`（sha256 `3b3ed209…22243` [seed-pipeline-7]）相同」；本机缺 4 个 CET 文件，这一步要等 `WORDLISTS_DIR` 就位。

---

## 4. 改动清单（文件 → 改什么）

| 文件 | 改什么 |
|---|---|
| `data/lists/manifest.json`、`README.md`、10 个列表文件、`aliases.tsv`、`overrides.tsv` | 新建（§3.2）；列表文件由另一条流水线产出，必须满足 §3.2.1 的格式与计数 |
| `backend/wd/seedbuild/__init__.py`、`manifest.py`、`lists.py`、`normalise.py`、`ecdict_source.py`、`build.py`、`diff.py`、`cli.py`、`manifest.schema.json` | 新建（§3.3–3.5）；`cli.py` 注册 `seed-build`、`seed-diff` |
| `backend/wd/cli.py:31-42 CLI_MODULES`、`:45-56 COMMAND_OWNERS` | 加 `"wd.seedbuild": ("seed-build", "seed-diff")` |
| `backend/pyproject.toml:26-28` package-data | 加 `"seedbuild/*.json"` |
| `scripts/build_seed.py` | 全文替换为兼容入口（或删除并改 `Makefile`）；`TASKS.md:162`「keep verbatim unless a bug is proven」的前提已不成立 |
| `scripts/pack_seed.sh:62, 68, 79, 90` `zcat` → `gzip -dc`；`:90` `stat -c %s` → `wc -c <`；`:63, 84, 90` `sha256sum` → 有则用、无则 `shasum -a 256`；`--check` 加 `content_sha256` 比对 | BSD/macOS 可用 [seed-pipeline-8] |
| `Makefile:93-98` | `seed` 目标改调 `$(WD) seed-build … --strict` + `scripts/pack_seed.sh`；新增 `seed-diff`、`seed-check`；`:98` `zcat` → `gzip -dc` |
| `backend/wd/seed.py` | `:1-20` docstring（v2 键、kind、aliases、内容哈希、dry-run）；删 `:43 STAGES`、改 `:60-64 SEED_COLUMNS` 生成、`:184-185` 未知码计数、`:193 kind`、`:204-208 stage_min`、`:218-245 _rebuild_forms` 加 aliases、`:107-112` 加 `seed_digest`、`:258-263, 287` 用内容哈希、`:85-103 SeedStats` 加 `content_sha256 / unknown_stage_codes / lemma_mismatch / aliases`、`:319-329 format_stats`、`:333-360` 加 `--dry-run/--report`、`:363 __all__` |
| `backend/wd/main.py:307-319 seed_check` | 用 `seed_digest`；日志字段加 `content_sha256` |
| `backend/wd/services/ecdict.py:28 STAGE_TAGS`、`:173-177 word_columns` | 只映射 `cet4/cet6`；`stage_min` 改 `min(stage_to_index)`（决定点 Q-d） |
| `backend/wd/services/words.py:143-151 derive_kind` | 不改；R5 的 `I` 通过 `kind` 覆盖解决 |
| `backend/tests/fixtures/mini_seed.jsonl` | 升到 v2：加 `lemma/seed_v`；给 `a, apple, cat, dog, book, happy, water, teacher, good, go, house` 等加 `xs`；加 1 个 `kind=phrase` 词组记录（含 `...`）、1 个带 `aliases` 的缩写（`Mr.` + `["mr"]`）、1 个 `kind`/display 覆盖（`E-MAIL → e-mail, word`；**不加 `I`**——`test_seed.py:86` 故意把它排除在 fixture 外以免掩盖大小写 bug，`I` 的覆盖只在 `seed_row` 单测里验）；保持 60 条 |
| `backend/tests/fixtures/lists/`（新） | `manifest.json` + 6 个小列表（含 §3.3 每条规则的样例行）+ `mini_stardict.sql`（≈60 行 `stardict` 表 DDL + 数据，含 `Mr.`/`Mr`/`hot dog`/`hot-dog`/`excited`/`café→cafe`）+ `previous_seed.jsonl`（retain 用） |
| `backend/tests/unit/test_seedbuild_normalise.py`、`test_seedbuild_lists.py`、`test_seedbuild_manifest.py`、`test_seedbuild_build.py`、`test_seed_diff.py`（新） | §5.2 |
| `backend/tests/unit/test_seed.py` | `:61` 计数随 fixture；`:93-97` `stage_min` 值随 Q1 的 `STAGE_ORDER`（写成 `stage_to_index("gk")` 而不是字面量 2）；`:197-204` 的 `stage_min == 1` 同样改为 `== stage_to_index("zk")`（Q1-a 重编号下它会变 2）；`:234` 改为「gz 与 plain 的 `content_sha256` 相同、第二次导入 `up_to_date`」；`:338-353` 验收数字待真实词表后重写（§5.1） |
| `backend/tests/unit/test_api_schemas.py:33-39`、`integration/test_vocab.py:69-70, 111, 216-234`、`scripts/smoke.py:352, 614` | 属 Q1/阶段枚举线，但种子 v2 一到位就会红（新增 `xs`、3,694 变化）——列出以便排期 |
| `backend/tests/unit/test_cli.py:51-58` | 自动覆盖新命令（它读 `COMMAND_OWNERS`） |
| `docs/DESIGN.md:193-209 §3.2` | 记录 v2 键、`kind` 覆盖、`stage_min = min rank`、`aliases → alt`、内容哈希；`:209` 验收数字改为引用 `stats.json` |
| `docs/TASKS.md:160-180 WP1` | 验收脚本改为读 `stats.json` 的 `per_stage/first_stage` 比对，不再写死 9162/2099…；`:162` 删「keep verbatim」 |
| `docs/DEPLOY.md:304`（`WD_SEED_PATH` 说明加内容哈希）、`:407, 413`（`make seed` 新参数）、`:417 §9`（加 `seed-build`、`seed-diff`、`import-seed --dry-run`） | — |
| `docs/API.md` | 不改（`WordBrief.stage_min`/`StageIndex` 属 Q1 线） |
| `ATTRIBUTION.md:12-14, 19-32`、`README.md:9, 78, 103`、`data/seed/ATTRIBUTION.md`（生成） | 官方词表来源、停用的两张 mahavivo 表、数字改引用 |
| `frontend/src/i18n/zh.ts:86` `sources.lists` | 「词表范围：小学（课标二级）、初中（课标三级与上海市初中英语词汇表）、高中（高中课标词表）、大学英语四级与六级大纲」+ `docs/FRONTEND.md §8`（`:209` 起）镜像行 + `npm run lint`（`frontend/scripts/check-copy.mjs`）/`zh.test.ts` |

---

## 5. 测试与验收

### 5.1 会变红的既有测试（与原因）

| 测试 | 原因 | 处置 |
|---|---|---|
| `test_seed.py::test_import_counts_and_bookkeeping`（`:58-73`）| fixture 升 v2 后记录数/插入数若变 | 保持 60 条，断言不变 |
| `test_seed.py::test_stage_flags_stage_min_and_cet6_star`（`:90-103`） | `stage_min` 字面量 1/2/3/4 依赖 Q1 | 改为 `stage_to_index(...)` |
| `test_seed.py::test_gzip_and_plain_inputs_are_equivalent`（`:229-238`） | `:234` 断言 gz/plain 的 sha 不同且第二次导入不是 `up_to_date` | 改为内容哈希语义 |
| `test_seed.py::test_full_seed_acceptance_numbers`（`:338-353`，`full_seed` 标记） | 全部数字变化 | 真实词表就位后重写为读 `stats.json` |
| `test_seed.py::test_kind_derivation_and_display_casing`（`:76-87`） | fixture 加词组/缩写 | 增加断言（`add ... to` 是 `phrase`、`mr` 别名可搜） |
| `test_api_schemas.py::test_stage_mapping_roundtrip`（`:33-39`）、`test_vocab.py::test_stages_totals_and_progress`（`:65-70`）、`test_vocab.py:216-234`（3,694）、`smoke.py:352/614` | 阶段枚举 + 数字 | Q1 线；本线种子 v2 合入前必须先合 Q1 的枚举改动，否则 `xs` 被导入器丢弃（无害但无效） |
| `test_cli.py:51-58` | 新命令 | 自动覆盖 |
| `test_deploy_files.py` 19 个 | Mac 上本就失败（GNU 工具） | 不变 |

### 5.2 要加的测试

- `test_seedbuild_normalise.py`：表驱动，每条 R1–R12 ≥ 3 例（含 §3.3 的真实样例与反例：`manner(s)` 不产出 `s`；`practice(s)e` 进 `unparsed`；`fold("café") == "cafe"`；`fold("o’clock") == "o'clock"`；`split_head("a (an)") → [a, an]`；`split_head("begin (began, begun)") → [begin]`；`classify_note("bund", "the Bund") == unknown`；`phrase_variants("a bit (of)") → ["a bit", "a bit of"]`；`lemma_of(h) == words.normalise_lemma(fold(h))` 对 fixture 全量成立）。
- `test_seedbuild_lists.py`：三种格式 + 两种 mahavivo 模式；CJK 行报错；`#` 注释；TSV 表头校验；单字母 `a`/`I` 不丢、节标题 `A` 丢；修正正则对 fixture 中 7 行脏数据的挽回。
- `test_seedbuild_manifest.py`：schema 校验失败信息；sha256 不符；`expect` 超 tolerance；`enabled: false` 跳过；`external` 路径解析。
- `test_seedbuild_build.py`：在 `tmp_path` 用 `mini_stardict.sql` 建库 → 构建 → (a) 两次字节相同、`content_sha256` 一致；(b) 闭包与 `xs ⊆ zk ⊆ gk` 断言；(c) retain：前一版种子里的词不丢、无阶段 → `stages == []`；(d) 不在 ECDICT 的词头生成最小记录并计入 `missing_from_ecdict`；(e) `merged_heads`（`May`/`may`）；(f) `variants`/`aliases` 互链；(g) 输出能被 `seed.import_seed` 导入且 `seed_row` 算出的 lemma 与记录 `lemma` 全等。
- `test_seed_diff.py`：旧 v1 fixture vs 新 v2 fixture 的矩阵、新增、消失、字段变化；md/json 渲染稳定。
- `test_seed.py` 新增：`kind` 覆盖；`aliases` → `alt` 行且遇 lemma 跳过；未知阶段码计数 + 告警；`--dry-run` 零写入（`words`/`kv`/`system_events` 字节不变）且报告含孤儿行；内容哈希 up-to-date。
- 不变量测试（沿用 `test_seed.py:171-187` 模式）：对含内容/图/用户行的库 `--force` 导入 v2 种子，内容指针、`difficulty`、`user_words` 不变。

### 5.3 在 `live-copy.db` 私有拷贝上排练（不碰 `/Users/sqin/word-dance-data`）

```
S=/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad
mkdir -p $S/word-lists-data-eng/rehearsal && cp $S/live-copy.db $S/word-lists-data-eng/rehearsal/word-dance.db
export WD_DATA_DIR=$S/word-lists-data-eng/rehearsal WD_DB_PATH=$WD_DATA_DIR/word-dance.db
.venv/bin/wd migrate                      # 若 Q1 的 0011 已存在：必须走 run_migrations（DROP VIEW v_bank 陷阱 [INDEX A4]），不要用 /usr/bin/sqlite3
.venv/bin/wd seed-diff $S/old/vocab.jsonl.gz data/seed/vocab.jsonl.gz --md $WD_DATA_DIR/diff.md
.venv/bin/wd import-seed --file data/seed/vocab.jsonl.gz --dry-run --report $WD_DATA_DIR/dry.json   # 期望：inserted ≈ 新词数，updated ≈ 9,000+，orphans 0
.venv/bin/wd import-seed --file data/seed/vocab.jsonl.gz
sqlite3 -readonly $WD_DB_PATH "select count(*) from word_contents where status='active'; select count(*) from user_words; select stage_min, count(*) from words group by 1; select kind, count(*) from words group by 1"
WD_FULL_SEED_DB=$WD_DB_PATH .venv/bin/pytest backend/tests -m full_seed
```

通过标准：内容 49 / `user_words` 77 不变；`stage_min` 分布与 `stats.json.first_stage` 一致；`kind='phrase'` ≈ 331 + 13；`dry.json.orphans == []`；第二次 `import-seed` 打印 `seed up to date`；Mac 上重打包 .gz 后 `seed_check` 不再触发导入。

---

## 6. 上线与回滚（Mac，launchd；无 `install.sh`/`systemctl`）

前提：Q1 的 0011 迁移与阶段枚举改动已合并（否则 `xs` 无列可写）；词表文件已入 `data/lists/`；`make seed`、`make seed-diff` 已在工作区跑过并人工看过 diff。

1. 构建与审阅（仓库）：`make seed ECDICT_DB=<stardict.db> WORDLISTS_DIR=<mahavivo cet 目录>` → `make seed-diff` → `make test`（含新 seedbuild 测试与 `check_contract.py`）→ 提交 `data/lists/*`、`data/seed/*`、代码、文档（按仓库约定 `-c user.name=sqin -c user.email=sqin@nvidia.com`）。
2. 停服务：`launchctl bootout gui/$(id -u)/com.word-dance.server`（避免 `wd serve` 启动时自己跑迁移和 `seed_check`，让每一步可观察）。
3. 快照：`export WD_DATA_DIR=/Users/sqin/word-dance-data; .venv/bin/wd backup --keep-daily 14 --keep-weekly 8`（`wd migrate` 另会写 `backups/pre-migrate-<from>-to-<to>.db.gz`，DEPLOY §5）。
4. 迁移：`.venv/bin/wd migrate`（0011；属 Q1 线）。
5. 排练式导入：`.venv/bin/wd import-seed --dry-run --report $WD_DATA_DIR/tmp/seed-dry.json` → 看 `orphans`、阶段矩阵与 §5.3 的预期一致 → `.venv/bin/wd import-seed` → 日志 `seed imported: … inserted, … updated`。
6. 起服务：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist`（或 `kickstart -k`）；`curl --noproxy '*' http://127.0.0.1:8000/api/health`；登录后 `GET /api/stages` 的 `total/new_only_total` 对照 `stats.json`；`~/Library/Logs/word-dance/word-dance.log` 里无第二次 `seed_import`（内容哈希已一致）。
7. 回滚：
   - 只回退种子（代码不回退）：`git checkout <上一提交> -- data/seed/vocab.jsonl.gz` → `wd import-seed --force`。因为新种子 ⊇ 旧种子（D5），旧文件会把 9,162 词的阶段列全部改回；新增的 ≈ 100 个词留下但阶段不变（无害）。
   - 回退迁移：只能 `wd restore backups/pre-migrate-*.db.gz`（丢失其后学习记录，[verify stage-model 遗漏 2]）；这是 Q1 线的回滚，不是种子的。
   - `kv.seed_version` 已是内容哈希：回退到旧代码（文件哈希语义）会在下次启动触发一次重导入，无害。

---

## 7. 风险、未决问题、工作量

### 7.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| `data/lists/` 文件质量（OCR、页首 `\f`、并列未拆、附表口径）| 阶段成员错 ⇒ 全库重标错 | manifest `expect ± tolerance` + sha256 + README 对账列；`--strict`；diff 报告人工审 |
| Q1 未定 | `stage_min` 整数含义、`mini_seed` 断言、验收数字都要等 | 种子格式已与索引解耦；只有 `test_seed.py:93-97` 与 `:338-353` 依赖 Q1 |
| 用户可见变化：初中层 2,099 → ≈1,987（+闭包不影响），「仅初中新增」2,099 → ≈1,483；249 词失去阶段 | 线上 2 个用户中 `current_stage=1` 的那位看到的初中总数变小 | 线上 `user_words` 与内容均不受影响（已查）；发布说明写明；249 词仍可搜索 |
| 词组 32 个无 ECDICT 释义 | 列表里短译为空 | diff 报告列出；内容层 `meaning_zh` 补；或 overrides 自写释义 |
| `kind` 覆盖与 `derive_kind` 契约 | DESIGN §3.2 需改 | 只允许 overrides/phrases 设置，默认行为不变 |
| 运行时 ECDICT 仍按旧标签赋 zk/gk（`ecdict.py:173-177`） | 用户新添词口径不一致 | 同提交改 `STAGE_TAGS`（Q-d） |
| `kv.seed_version` 语义切换 | 升级后首次启动多一次导入 | 预期行为，日志可见 |
| Apple gzip 字节不同 | `.gz` 在 Mac 重打包会出现二进制 diff | 版本不看 .gz；提交前用 Linux/CI 打包或接受 diff |
| ECDICT 义项错位（`bund`、`mum`、`p.e.` 首行「排字错误」） | 释义误导 | overrides 自写释义（我们自己的文本） |

### 7.2 未决问题（需要拍板或等输入）

- Q-a：`gk ⊇ zk` 闭包是否接受（偏离 A2，预览 +≈150 词进高中层）。
- Q-b：二级/三级/上海附表是否入阶段、`irregular_verb` 组排除（我建议入、排除）。
- Q-c：词组是否随首版一起上（我建议上；也可 manifest `enabled: false` 先观察）。
- Q-d：`services/ecdict.py` 运行时赋阶段是否同步改为只认 cet4/cet6。
- Q-e：`overrides.tsv` 的自写释义是否允许（≤ 10 词，MIT 文本）。
- Q-f：是否保留 `sources` 里的 `ecdict_zk/ecdict_gk` 记号以便将来物化「拓展」层（零成本，我建议保留）。
- 等输入：`data/lists/` 全部文件及 README 对账；mahavivo 4 个 CET 文件的本地副本（本机缺，无法做 §3.7 新核实 2 的字节级重建验证）；考试院高考 200 词（无机读件）。

### 7.3 工作量（人日，本线）

| 工作 | 人日 |
|---|---|
| `data/lists` 格式、manifest + schema、README 模板、aliases/overrides 初稿 | 1.5 |
| `normalise.py` 12 条规则 + 表驱动测试 | 3 |
| `lists.py` 四种解析器 + 修正正则 + 测试 | 1.5 |
| `build.py`/`ecdict_source.py`（宇宙、retain、闭包、v2 记录、stats v2、确定性）+ `mini_stardict` fixture + 测试 | 3 |
| `diff.py` + CLI + 测试 | 1 |
| `seed.py` 4 处改动 + `--dry-run/--report` + `main.seed_check` + `ecdict.py` 同步 + 测试 + DESIGN/TASKS/DEPLOY 文档 | 2.5 |
| `pack_seed.sh`/`Makefile` 可移植性、`full_seed` 验收重写、live-copy 排练、发布说明 | 1 |
| ATTRIBUTION/README/zh.ts 文案与 FRONTEND §8 镜像 | 0.5 |
| **合计** | **14（12–16）** |

不含：Q1 的 0011 迁移与枚举扩展（[stage-model 第二节] 估 ≈ 迁移 100 行 + 后端 30–50 + 测试 70–120 + 前端 30–50）；词表 OCR/抽取；CET 外部文件获取。
