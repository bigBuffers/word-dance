# 词表来源与种子流水线 — 设计（角度：连续性）

基线：仓库 `/Users/sqin/word-dance` `main @ 75df534`；线上库只读副本 `scratchpad/live-copy.db`（9,162 词，schema v10，2 个用户，49 行 `difficulty`）；日期 2026-11-05。本文只做设计，不改仓库代码。引用格式：`path:line` 按 75df534；`[INDEX …]`、`[facts-N]`、`[verify slug-N]` 指向本目录的调研文件；「本设计复算」= 我在 `scratchpad/word-lists-continuity/quant.py`、`extra.py` 上用 `python3 -I` 对 `live-copy.db`（`?mode=ro`）、已校验的 ECDICT `stardict.db`（851,288,064 B，3,402,564 行）与 verify 步骤产出的词表文件重算的数字（输出存同目录 `quant_output2.txt`、`extra_output.txt`）。

设计角度「连续性」的含义：**线上任何一个词都不失去它今天拥有的阶段；官方词表只做加法**（加小学、补缺口、加来源标签）；旧表（mahavivo 中考/Highschool）的词保留在原阶段，被标为「拓展」。代价用「超纲比例」量化。

---

## 1. 一页结论

**决定了什么**

1. **阶段集合 = 旧集合 ∪ 官方集合，只增不减。** `xs = L2`（国家 2022 二级 505 词）；`zk = Z₀ ∪ L3 ∪ SH`（现有 2,099 ∪ 国家三级 1600 ∪ 上海考试院 2020 词汇表 1,731 词 + 331 词组）；`gk = G₀ ∪ HS3100 ∪ HS3000`（现有 3,829 ∪ 高中课标 2025 修订 3100 ∪ 2020 版 3000）；`cet4/cet6` 不变。不做向上闭包：`xs ⊆ zk` 由官方表本身保证（L2 ⊆ L3，本设计复算差集为空），`zk ⊆ gk` 今天就不成立（62 词）、之后也不强求（94 词）。导入器加一道「单调性守卫」：任何已有词的旗标只能变多、`stage_min` 只能变低，否则拒绝导入。
2. **「拓展」不是新阶段，是来源标签。** 第一期不加列、不改 DTO：`words.sources` 增加官方来源记号（`l2 l3 sh2020 sh2020p hs2020 hs2025 …`），一个词「在阶段 s 里但不在 s 的任何官方表里」即为该阶段的拓展词。第二期（可选）再加 `core_min` 列与「拓展」芯片/排序。
3. **官方词表以派生文本文件进仓库** `data/lists/`（每行一个词头、`#` 注释、按需 TSV 列 `mark`/`alt`），由声明式 `manifest.json` 驱动 `scripts/build_seed.py`；原始 PDF/docx 不入库，只在 `README.md` 记 URL、哈希、获取日期、解析规则与计数。许可姿态不变：只取词头，释义/音标/词频来自 ECDICT（MIT）。mahavivo 的 6 个文件继续从仓库外的 `WORDLISTS_DIR` 读（继续不分发），其中两张来源不明的中小学表降级为「legacy」来源——**保留成员资格，不再算作官方依据**。
4. **`build_seed.py` 重构为「解析 → 解析到现有词 → 查 ECDICT → 人工覆盖 → 确定性输出」五步**，修掉今天把 `best/less/cafe/an` 弄丢的三个解析缺陷，并新增 `scripts/seed_diff.py`（旧 vs 新种子逐词阶段差异报告）与 `wd import-seed --dry-run`。
5. **种子格式不变**（15 个键，`stages[]` 多一个码 `xs`，`sources[]` 多几个记号），所以旧代码遇到新种子只是静默忽略 `xs`（`seed.py:184-185`），新代码遇到旧种子完全正常——可以分步上线。

**为什么**

- 线上只有 2 个用户、49 行 `difficulty`，但「不丢阶段」的承诺比「数据少」更重要：现有 zk/gk 是旧考纲口径 [INDEX A1]，若按国家课标重标会让 680 个 zk 词、1,196 个 gk 词「降级」[INDEX C1/C2]，这对已经在用词库页/筛词的学生是可感知的退步；加法路线让所有现有行为（阶段页签、筛词池、推荐词距离）在旧词上逐字不变。
- 官方表覆盖率极高（L2 99.0%、L3 98.8%、SH 98.3%、HS3000 99.5%、HS3100 96.6% 已在库 [INDEX §4.1]），缺的是**阶段标记**而不是词条：本设计复算只需新建约 30 个单词 + 272 个 ECDICT 收录的上海词组，其余全部是给现有行加旗标。
- 单调守卫 + 差异报告 + dry-run 把「重导种子会覆盖 20 列」[INDEX A6] 这个今天最大的操作风险变成可预演、可拒绝的步骤。

**代价多少（本设计复算，见 §3.6）**

| 指标 | 数值 | 说明 |
|---|---|---|
| 新阶段集合 | xs 505 · zk 2,520（+421）· gk 4,297（+468）· cet4/cet6 不变 | 单词口径；词组另 +272 |
| 新 `stage_min` 分布 | xs 505 / zk 2,015 / gk 1,871 / cet4 1,207 / cet6 3,601 | 今天 2,099 / 1,792 / 1,577 / 3,694；1,269 个词的 `stage_min` 下移 |
| **超纲比例（原始）** | zk 20.1%（506/2,520）· gk 25.4%（1,093/4,297） | 阶段内不在任何官方表的词 |
| **超纲比例（扣除体例差异）** | **zk 16.2%（409）· gk 24.2%（1,042）** | 扣除官方表放在附表的数词/月份/星期/国家（zk 95、gk 25）与括注的美式拼写（zk 2、gk 26） |
| 纯旧表词（不在任何官方表、也非附表/变体） | 999（zk 层 222、仅 gk 777）；其中 227 连 CET 标签都没有 | 这 227 个就是 `abortion/bungalow/yummy` 一类旧高考 3500 谱系词 [INDEX A1] |
| 上海初中生的实际感受（主攻 zk，按词频排序的推荐词/筛词） | 前 50/100/300 个候选里拓展词 0/0/0 个；前 600/1000 里 5/30 个；不在上海表的词 3/5/10/28/88 | 拓展词集中在词频尾部；见 §3.6.3 |
| 两位线上用户 | 用户 1（四阶段、主攻 cet4）候选池 9,162→9,199（+词组 272），370 个词从「主攻阶段」降为更低阶段（推荐词距离 0 → 2–6）；用户 2（只选 zk）候选池 2,099→2,520，499 个最基础词因成为小学词而排到推荐词队尾 | 设置行本身不动（§3.5.6） |
| 工作量 | ≈ 7 人日（6–8），不含阶段枚举/前端/迁移重建本身（属 stage-model 切片） | §7.3 |

---

## 2. 对照假设 A1–A6 的偏离与理由

| 假设 | 本设计 | 偏离？ | 理由 |
|---|---|---|---|
| A1 小学 = 国家 2022 二级 505 词骨架 | `xs = r(L2)`，505 词；另给义务教育附表（数词/月份/星期）一个独立文件，manifest 可选把它归入 xs（约 +65 个今天在 zk 的词，§3.3 N7） | 微偏离（附表可选） | 505 表明文「不列」数词/月份/星期而把它们单列 [verify list-sources-26]，但二级内容标准要求会数数/说日期；是否入 xs 交 manifest 一键切换，默认入 xs |
| A2 初中 = SH2020 ∪ L3；高中 = HS3100（含 3000）；上海 200 补充词暂缺 | 同，但**再并上旧集合 Z₀/G₀**；HS3000 与 HS3100 都读（2025 修订版把约 90 个附表词移出主表、另有约 10 个真删词如 advertisement/cheek/crayon/humorous，本设计复算 H2020−H3100 = 100） | **主要偏离**：旧集合不退出 | 这就是「连续性」角度本身；代价量化在 §3.6 |
| A3 只用官方词头；mahavivo 中考/高中两表不再作为阶段依据；有道系/墨墨只作核验 | 官方表只取词头 ✓；mahavivo 两张来源不明表**不再作为「官方/核心」依据，但其成员资格保留**，在 `sources` 里作为 legacy 记号，构成「拓展」层；有道系/DictionaryData/墨墨不入库 ✓ | 部分偏离 | 不保留就是重标路线（另一位设计者的角度）；保留的许可风险与今天完全相同（只用「在不在表里」这一事实，不分发文件，`data/seed/ATTRIBUTION.md:12-13`） |
| A4 不按省份分层；是否双方案/拓展层由设计决定 | 单方案；上海表作为 zk 的**第二个核心来源**并入，不加地区维度；「拓展」= 来源标签（第一期）/ `core_min` 列（第二期） | 无 | 上海表 25% 不在国家三级 [INDEX B5]，并入即解决覆盖；地区维度留给 `sources` 记号与后续 `word_stage_tags` 路线 [stage-model-17] |
| A5 配图 | 不涉及 | — | — |
| A6 新用户默认 K-12；2 个用户的迁移规则写死 | 两位用户的 `user_settings` 行**一字不动**：用户 1 `["zk","gk","cet4","cet6"]`/3、用户 2 `["zk"]`/1 保持；因为 `xs ⊆ zk`，给他们加 `xs` 不会改变候选池（池按旗标并集算，`screen.py:51-55`、`batches.py:232-234`），只会改筛词页签的可见项——交 stage-model 切片决定 UI 层；DDL 默认值的改动属 0011 重建 | 微偏离（规则 = 无操作） | §3.5.6 |

---

## 3. 详细设计

### 3.1 阶段成员的集合代数与单调性

**记号。** `Z₀/G₀/C₄/C₆` = 线上今天 `stage_zk/gk/cet4/cet6 = 1` 的词集（2,099 / 3,829 / 4,722 / 7,671，`live-copy.db`）。官方表：`L2`（505）、`L3`（1600 ⊇ L2）、`SH`（上海 2020 单词 1,731）、`SHP`（上海 2020 词组 331）、`HS20`（2020 版 3000）、`HS25`（2025 修订 3100 ⊇ L3 近似成立：本设计复算 `L3 − HS25` = {i, policemen, practice, yogurt}，后两者对应 HS25 的 practise、yoghurt 拼写；其余差异是 3 个解析噪声）；附表 `APP_L`（义务教育附表：数词/月份/星期）、`APP_S`（上海附表：代词/数词/月份/国家与洲/学科）、`APP_H`（高中附表：117 个国家/国籍词 [verify provinces-4]）。`r(X)` = 把 X 的词头按 §3.3 规则解析到库内 lemma（精确/变体/屈折）或新建记录后的 lemma 集合。

**定义（结论）。**

```
xs   = r(L2) ∪ r(APP_L)                       # 附表入 xs 由 manifest 决定，默认入
zk   = Z₀ ∪ r(L3) ∪ r(SH) ∪ r(SHP) ∪ r(APP_S)
gk   = G₀ ∪ r(HS20) ∪ r(HS25) ∪ r(APP_H)
cet4 = C₄ ;  cet6 = C₆                        # 不变：ECDICT 标签 ∪ mahavivo cet 表（build_seed.py:84-87, 105-106, 128-142）
core(xs) = r(L2) ∪ r(APP_L);  core(zk) = r(L3) ∪ r(SH) ∪ r(SHP) ∪ r(APP_S);  core(gk) = r(HS20) ∪ r(HS25) ∪ r(APP_H)
ext(s)   = s − core(s)                        # 「拓展」= 阶段内不在该阶段任何官方表的词（第一期只是统计口径，不是列）
```

**不变量。**

- I1（连续性）：对线上每个词 `stages_new(w) ⊇ stages_old(w)`，且 `rank(stage_min_new) ≤ rank(stage_min_old)`。由 `seed.py` 的新守卫在导入前检查（§3.5.3），`scripts/seed_diff.py` 在构建后报告（§3.4.6）。依据：今天的导入是「覆盖 20 列」而非「只填空」[seed-pipeline-10]、[stage-model-19]，守卫是把不变量从「口头约定」变成拒绝条件。
- I2（`stage_min` 定义不变）：`stage_min = min rank(s) for s in stages`（今天 `seed.py:208` 的 `STAGES.index(stages[0]) + 1`、`ecdict.py:177` 同式）。改为显式秩表 `STAGE_RANK`（§3.5.1），秩值由 stage-model 切片决定。**本设计假定 `xs` 的秩 = 0、其余 1–4 不变**——这是最符合「连续性」的编码：线上每一个已存的 `stage_min`/`current_stage` 数值含义不变，`push_batches.settings_json` 快照 [stage-model-4] 与 `API.md:460`「zk→1 … cet6→4」仍然成立；代价是 `screen.py:44`、`batches.py:272,698` 三处 `int(x or bank.DEFAULT_CURRENT_STAGE)` 对 0 的陷阱与 `schemas.py:65` 的范围检查 [INDEX A3 办法①]。若 stage-model 切片选重编号 1..5，本流水线只改一行秩表 + 迁移里两条 `UPDATE`；种子文件本身**不含**秩值（只有 `stages[]`），与编码无关。
- I3（词组也是词）：`SHP` 以 `kind='phrase'` 入库（`derive_kind` 含空格即 phrase，`services/words.py:143-146`），走今天 13 个 phrase 走的全部路径，不加任何新分支。

**单调性与闭包（结论：不做闭包）。** 今天 `0001_init.sql:181-184` 的注释说旗标「cumulative as in the sources」，但线上 15 种旗标组合不是区间，62 个初中词不在高中表 [stage-model-4]。本设计不引入「小学词自动属于初中/高中」的闭包步骤：`xs ⊆ zk` 由 `L2 ⊆ L3` 保证（复算差集 ∅），`L3 ⊆ HS25` 近似成立（差 4 个词：i、policemen、practice/practise、yogurt/yoghurt），而上海表有 94 个词不在任何高中表（如 aged、amusing、angrily、chopstick、daytime、educational），它们合法地只属于 zk——正如今天 33 个「仅初中」词。闭包会把 94+ 个词硬塞进 gk，是「加法」之外的编辑判断，留给 manifest 的可选开关 `closure: "up"`（默认关）。

**一个词在多个官方表里时 `sources` 怎么记。** `sources` 是种子列（`seed.py:66, 210`），今天是排序去重后的空格分隔记号 `'cet4 cet46 ecdict gk zk'`（线上记号计数：ecdict 8,274 / cet46 8,007 / cet4 4,539 / gk 3,446 / cet6 2,220 / zk 1,887，本设计复算），**没有任何读取者** [stage-model-15]。规则：

- 现有记号一个都不改名（`zk`、`gk` 继续表示「mahavivo 中考表 / Highschool 表」成员），避免 9,162 行无意义重写；
- 新记号：`l2`、`l3`、`l3app`（义务教育附表）、`sh2020`、`sh2020p`（词组）、`sh2020app`、`hs2020`、`hs2025`、`hs2025-m1`/`hs2025-m2`（★/★★ = 必修 500 / 选择性必修 1000，与 `hs2025` 同时出现）、`hs2020-m1`/`-m2` 同理、`hsapp`（国家/国籍附表）；
- 经屈折形式或拼写变体解析到的词也写该表记号（`excited → excite` 得 `l2 l3 sh2020 …`），解析方式写进构建报告 `stats.json.resolution`（§3.4.5），不进 `sources`；
- 多表并集 = 记号并集，排序去重，与今天一致。

### 3.2 官方词表文件如何进仓库（`data/lists/`）

**结论。** 词表文件由本工作流的另一条流水线产出；本节只定义**格式、清单与消费方式**。目录建议：

```
data/lists/
  README.md                         # provenance 表 + 许可说明 + 解析规则版本
  manifest.json                     # 声明式清单（build_seed.py 的唯一输入）
  overrides.jsonl                   # 人工记录：不在 ECDICT 或 ECDICT 义项错误的官方词头
  moe-2022-l2.txt                   # 国家 2022 二级词汇表，505 词头
  moe-2022-l3.tsv                   # 国家 2022 三级词汇表，1600 词头；mark=1 表示原表以 * 标出的二级词
  moe-2022-appendix.tsv             # 义务教育附表：head<TAB>group (numeral|month|weekday|country|holiday)
  shmeea-2020-junior.tsv            # 上海考试院《2020 评价指南·词汇表》单词 1,731；alt 列放并列拼写（bike|bicycle 拆成两行后 alt 互指）
  shmeea-2020-junior-phrases.txt    # 词组 331
  shmeea-2020-junior-appendix.tsv   # 代词/数词/月份星期/国家与洲/学科，group 列同上
  moe-2020-senior.tsv               # 高中课标 2017 版 2020 修订 3000：head<TAB>mark (0/1/2)
  moe-2025-senior.tsv               # 高中课标 2017 版 2025 修订 3100：head<TAB>mark<TAB>alt
  moe-2025-senior-appendix.tsv      # 117 个国家/国籍词
```

**行格式（约定）。** UTF-8、LF、无 BOM；空行忽略；`#` 开头整行为注释（文件头至少写来源、获取日期、解析脚本版本）；**每行一个词头**，保留原件大小写（`China`、`Mr`、`PE`、`a.m.`）；并列条目（`a/an`、`although/though`、`exam=examination`）由产出流水线预先拆成两行，`alt` 列互指；TSV 列由 manifest 的 `columns` 声明（`head` 必有；`mark` 为整数；`alt` 用 `|` 分隔；`group` 为附表分组；`note` 自由文本）。构建器对 `x/y`、`x = y`、`x (y)` 仍做防御性拆分（§3.4.1），以便直接喂 mahavivo 原文件。

**manifest.json（示例节选，字段即规范）。**

```json
{
  "version": 2,
  "stage_rank_note": "秩值不在此文件；种子只写 stages[] 码",
  "lists": [
    {"code": "l2", "title": "义务教育英语课程标准（2022 年版）附录 3 二级词汇表", "file": "moe-2022-l2.txt",
     "format": "plain", "columns": ["head"], "stage": "xs", "official": true, "declared_count": 505,
     "source": {"org": "教育部", "doc": "教材〔2022〕2 号附件", "url": "http://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220420582349487953.pdf",
                "sha256": "59ec3971e0dbd6ca487c4e4972cbc80effaf2fd62418d07e5f62c6698fa222fb", "pages": "印刷页 87–97", "retrieved": "2026-11-05",
                "transcription": "freemdict docx（非官方）与官方扫描件逐词核对"}},
    {"code": "l3", "file": "moe-2022-l3.tsv", "format": "tsv", "columns": ["head", "mark"], "stage": "zk", "official": true, "declared_count": 1600,
     "mark_legend": {"1": "二级词（原表 *）"}},
    {"code": "l3app", "file": "moe-2022-appendix.tsv", "format": "tsv", "columns": ["head", "group"], "stage": "xs", "official": true, "appendix": true,
     "stage_by_group": {"numeral": "xs", "month": "xs", "weekday": "xs", "country": "zk", "holiday": "zk"}},
    {"code": "sh2020", "file": "shmeea-2020-junior.tsv", "format": "tsv", "columns": ["head", "alt"], "stage": "zk", "official": true, "declared_count": 1731,
     "source": {"org": "上海市教育考试院", "doc": "2020 年上海市初中英语课程终结性评价指南·词汇表（07.pdf）",
                "url": "https://www.shmeea.edu.cn/download/20190926/07.pdf", "md5": "059df9c02684bd989fff6f8849ee1993", "bytes": 1200683, "retrieved": "2026-11-05"}},
    {"code": "sh2020p", "file": "shmeea-2020-junior-phrases.txt", "format": "plain", "stage": "zk", "official": true, "phrases": true, "declared_count": 331,
     "skip_patterns": true},
    {"code": "hs2020", "file": "moe-2020-senior.tsv", "format": "tsv", "columns": ["head", "mark"], "stage": "gk", "official": true, "declared_count": 3000,
     "mark_legend": {"1": "必修（*）", "2": "选择性必修（**）"}},
    {"code": "hs2025", "file": "moe-2025-senior.tsv", "format": "tsv", "columns": ["head", "mark", "alt"], "stage": "gk", "official": true, "provisional": true,
     "declared_count": 3100, "note": "日常修订版（2017 年版 2025 年修订）；印发文号未见，学界已采用 [verify provinces-4]；与 YR7429 CC BY-SA 提取逐词一致 [verify shanghai-secondary-9]"},
    {"code": "zk", "file": "$WORDLISTS_DIR/中考英语词汇表.txt", "format": "rich", "stage": "zk", "official": false, "legacy": true,
     "note": "mahavivo，来源不明；保留成员资格，不分发"},
    {"code": "gk", "file": "$WORDLISTS_DIR/Highschool_edited.txt", "format": "plain", "stage": "gk", "official": false, "legacy": true},
    {"code": "cet4", "file": "$WORDLISTS_DIR/CET4_edited.txt", "format": "rich", "stage": "cet4", "official": true},
    {"code": "cet6", "file": "$WORDLISTS_DIR/CET6_edited.txt", "format": "rich", "stage": "cet6", "official": true},
    {"code": "cet46", "file": "$WORDLISTS_DIR/CET_4+6_edited.txt", "format": "plain", "stage": {"in_cet4": "cet4", "else": "cet6"}, "official": true},
    {"code": "cet6star", "file": "$WORDLISTS_DIR/英语六级词汇（星标，1726）.txt", "format": "plain", "flag": "cet6_star"}
  ],
  "ecdict_tags": {"zk": "zk", "gk": "gk", "cet4": "cet4", "cet6": "cet6"},
  "closure": "none",
  "variants": "tag-both-if-present"
}
```

`official:false, legacy:true` 的两张表就是「拓展层」的定义来源；`provisional:true` 只影响 README/统计的措辞，不影响成员资格（加法）。

**README.md 的 provenance 表（列与已知值）。**

| 文件 | 原件（机构 / 文件 / 版本） | URL | 原件哈希 / 大小 | 获取日期 | 解析规则 | 词头数（文件）| 官方声明数 | 差异说明 | 许可说明 |
|---|---|---|---|---|---|---|---|---|---|
| `moe-2022-l2.txt` | 教育部《义务教育英语课程标准（2022 年版）》附录 3 二级 | moe.gov.cn `…/W020220420582349487953.pdf` | sha256 `59ec3971…a222fb`，31,502,213 B，201 页扫描件 | 2026-11-05 | 转录件逐词校对；`a/an` 拆两行 | 505 | 505 | 无 | 政府文件，未声明许可；只取词头 |
| `moe-2022-l3.tsv` | 同上，三级 | 同上 | 同上 | 同上 | 同上；`mark=1` 二级词 | 1,600 | 1600（含二级 505） | 数词/月份/星期在附表文件 | 同上 |
| `shmeea-2020-junior.tsv` | 上海市教育考试院《2020 年…评价指南》词汇表 | shmeea.edu.cn `/download/20190926/07.pdf`（发布页 13309） | md5 `059df9c02684bd989fff6f8849ee1993`，1,200,683 B，89 页 | 2026-11-05 | `pdftotext -layout`，以 `\f` 为页界，并列拆分 | 1,731 | 手册称 1733 | PDF 文本本身缺 `a`/`an`（在 L2/L3 中）[verify shanghai-secondary-8] | 事业单位考试文件，未声明许可；只取词头，不取释义/词性 |
| `shmeea-2020-junior-phrases.txt` | 同上，词组部分 | 同上 | 同上 | 同上 | 词组标题至代词附表之间 | 331 | 手册称 335 | 29 个含 `sb./sth./…` 的句型模板标记 `pattern` | 同上 |
| `moe-2020-senior.tsv` | 教育部《普通高中英语课程标准（2017 年版 2020 年修订）》附录 2 | moe.gov.cn `…/W020200603315372317586.zip` → `4.…英语….pdf` | zip 38,598,043 B；PDF 7,750,611 B（有文本层） | 2026-11-05 | `pdftotext`，`*` 计星 | 2,997 | 3000 | 差 3 为切分噪声 | 同 L2 |
| `moe-2025-senior.tsv` | 《…（2017 年版 2025 年修订）》日常修订版（非官方镜像） | forum.freemdict.com 转载 PDF/docx | PDF 3,978,785 B，CreationDate 2025-10-31 | 2026-11-05 | 同上 | 3,104 | 3100 | 印发文号未见 → `provisional` | 同 L2，另注明镜像非官方 |

**许可说明（README 段落，结论）。** 课标与考试院词汇表是政府/事业单位发布的考试文件，未声明许可；《著作权法》第五条是否适用未核实 [INDEX C4]。本仓库只收录**词头清单**（接近单纯事实数据），不收录任何释义、词性、例句、排版与说明文字；释义/音标/词频/词形全部来自 ECDICT（MIT）。这与今天对 mahavivo 的做法（`data/seed/ATTRIBUTION.md:12-13`「Only the head words are used」）一致。不提交任何原件 PDF/docx。`data/licenses/` 不新增许可证文件（没有可引用的许可证文本），改为 `data/lists/README.md` 承担声明；根 `ATTRIBUTION.md` §2（`:19-32`）增加「官方词表（词头）」一节与上表的缩略版，并把 mahavivo 一节改写为「legacy 成员来源 / 四六级表」。

**`ATTRIBUTION.md`（`data/seed/`）** 由 `build_seed.py:176-177, 201-219` 的常量生成——改为**从 manifest 渲染**（每个 `official:true` 列表一条、legacy 一条、ECDICT 一条），不再手写常量，避免 [seed-pipeline-21] 指出的「重建会覆盖手改」。

**Makefile `seed` 目标（`Makefile:93-98`）。** 参数改为三件：`ECDICT_DB=<stardict.db>`（不变）、`WORDLISTS_DIR=<mahavivo 目录>`（不变，仍指 mahavivo 的 6 个文件：cet 两表 + cet46 + 星标 + 两张 legacy 表）、`LISTS_DIR ?= data/lists`（新，含 manifest）。`:96` 的调用改为 `--manifest $(LISTS_DIR)/manifest.json --lists-dir $(WORDLISTS_DIR)`；`:97-98` 的 `gzip -9 -n -k -f` + `zcat` 换成 `scripts/pack_seed.py`（§3.4.7：Mac 上可复现、无 BSD `zcat` 问题 [seed-pipeline-7/8]）。`make seed` 依旧需要 ECDICT（`build_seed.py:74` `--db required`），本机已有校验副本可用（`scratchpad/ecdict-dl/extract/stardict.db`）。

### 3.3 规范化规则（逐条：规则 → 例子 → 对现库的影响）

解析器把官方词头映射到库内 lemma 的顺序固定为：**精确 → 拼写/书写变体 → 屈折形式（word_forms） → 人工覆盖 → ECDICT 新记录 → 失败**。「精确」用今天 `normalise_lemma`（`services/words.py:183-189`：NFKC、弯引号/长破折转 ASCII `_CHAR_MAP :69-87`、空白压缩、去外围标点 `_STRIP_PUNCT :88`、小写）。本设计复算的解析结果：

| 表 | 词头 | 精确 | 变体 | 屈折 | 缺失（ECDICT 有 / 无） |
|---|---|---|---|---|---|
| L2 505 | 505 | 500 | 3（mr/mrs/ms → `mr./mrs./ms.`）| 1（excited → excite）| 1（`pe`：ECDICT 义项为「相位编码」→ 走变体 `p.e.`，见 N4）|
| L3 1,608（解析口径）| 1,608 | 1,592 | 3 | 5（according→accord, dining→dine, excited, lost→lose, policemen→policeman）| 8（ai, teenage, tofu, yogurt→变体 yoghurt, pe；3 个噪声）|
| HS2020 2,997 | 2,997 | 2,981 | 3 | 6（+confused, embarrassed, frightened）| 7（calligraphy, confucius, curd, entirely, uk, wi-fi, pe）|
| HS2025 3,106（解析口径）| 3,106 | 3,076 | 4（mr/mrs/ms；`per cent → percent`，真正的拼写对，应走 `alt` 列而非去空格规则）| 8（+endangered）| 18（+bce, ce, drone, due to, empathy, kung fu, lifestyle, mobile phone, pagoda, wetland …）|
| SH 1,722（解析口径）| 1,722 | 1,694 | 3（hot-dog→`hotdog`, mr, mrs）| 11（embarrassed, excited, frightened, frightening, frozen→freeze, lost, satisfied, satisfying, surprised, underlined, united）| 14（angrily, beautifully, bund, carefully, dancer, dishonest, luckily, politely, quietly, seafood, unforgettable, yogurt, café→cafe；1 噪声）|
| SHP 309（解析口径）| 309 | 3 | 5（**假阳性**，见 N8）| 0 | 301（ECDICT 有 272 / 无 29）|

与核验一致：L2 真缺只有 `excited`（屈折）[verify provinces-24]，上海真缺 14 [verify shanghai-secondary-19]。

- **N1 Unicode 与弯引号/重音符。** 规则：`normalise_lemma` 的 NFKC + `_CHAR_MAP`；另加「去重音」候选（NFKD 去组合符）。例：`o’clock → o'clock`（在库，zk）；`café → cafe`（在库，`stage_min 3`，`sources cet4 cet46 ecdict`）。影响：`cafe` 获得 `zk` 旗标与 `sh2020` 记号（它在 mahavivo 中考表里也被 `RICH_RE` 丢了 [verify list-sources-7]）；display 保持 `cafe`（不改 lemma/display，连续性）。
- **N2 英式/美式变体。** 官方表英式为主、美式括注 [provinces-1 说明 2]；产出流水线把括注放进 `alt` 列。规则 `variants: tag-both-if-present`：若 `alt` 本身是库内 lemma，则两者**同时**获得该表的阶段与记号；若 `alt` 不在库，不为拼写新建词。例：`colour/color`、`favourite/favorite`、`maths/math`、`centre/center`、`programme/program`、`realise/realize`、`defence/defense`、`yoghurt/yogurt`（库里只有英式）、`mum/mom`。影响：本设计复算库内有 26 个 gk 层、2 个 zk 层的美式拼写（analyze, behavior, center, color, defense, gray, honor, meter, organize, program, realize, theater …；math, mom）——它们今天已有阶段，N2 只决定它们算核心还是拓展（算核心）。`yogurt`（L3、SH 都列）不新建，`yoghurt` 得 `zk`。
- **N3 并列条目。** `a/an`、`although/though`、`bike/bicycle`、`anybody/anyone`、`everybody/everyone`、`somebody/someone`、`exam=examination`、`grandma=grandmother`、`toward(s)`、`manner(s)`：拆为独立词头，各自获得阶段。影响：`an` 今天 `stage_zk=0, stage_min=2`（`RICH_RE` 对 `a (an)` 只取 `a` [verify shanghai-secondary O8]）→ 变为 xs（L2 含 an）；`toward`/`towards`、`manner`/`manners` 若后者在库则都标（`manners` 不在库则只标 `manner`）。
- **N4 句点缩写。** 规则：候选依次为 `head`、`head.`、去点、按字母加点（`pe → p.e.`，`usa → u.s.a.`）；命中即用库内现有 lemma，不新建、不改名。例：`Mr/Mrs/Ms → mr./mrs./ms.`（在库，zk）、`PE → p.e.`（在库，zk）、`TV/OK → tv/ok`（在库）、`a.m./p.m.` 精确、`UK` 不在库 → ECDICT `UK`「n. 联合王国」新建（kind=abbreviation，`_ACRONYM_RE :91`）。影响：修 display 大小写——`mrs.`→`Mrs.`、`p.e.`→`P.E.`、`a.m.`（保留小写，惯例）；display 是种子列，改它只重写这几行。已知疣：`a.m` 与 `a.m.` 是两个 lemma（cet4 表的书写差异，`a.m` `stage_min 3`），`miss.`/`miss` 并存——连续性原则下**不合并、不删除**，记入 §7.2 待办（合并需要 `merged_into_word_id` 流程，不是种子的事）。
- **N5 屈折形式与 `word_forms`。** 规则：官方词头若是库内 lemma 的 `p/d/i/3/s/r/t` 形式（`word_forms`，`0001_init.sql:219-225`；构建器用 ECDICT `exchange` 现算同一张表，与 `seed.py:218-245` 同规则），阶段与记号落到**原形**，不新建词头。例：上海 12 个「屈折假缺」`excited→excite(p)`、`frozen→freeze(d)`、`lost→lose(p)`、`united→unite(p)`、`satisfying→satisfy(i)` [verify shanghai-secondary O5]；国家表 `according→accord(i)`、`policemen→policeman(s)`。影响：搜索/高亮已经通过 `word_forms` 处理（`vocab.py:40-43` 前缀匹配词形）；`excite` 等 9 个原形今天已是 zk；`according`、`lost`、`frozen` 作为独立义项（分词形容词）的学习价值损失记入风险（§7.1）。
- **N6 派生副词。** 国家表说明「不列可由构词法推导的派生词」[provinces-1 说明 10]，上海表却列了 `angrily, beautifully, carefully, luckily, politely, quietly` 等。规则：上海表列出的派生词**照常入库**（ECDICT 全部有：angrily frq 8069, carefully 1603, quietly 2553 …，本设计复算），不做「还原到词干」。影响：+6 个新 zk 词。
- **N7 专有名词 / 国家名 / 数词 / 月份 / 星期附表。** 规则：附表作为独立文件（`appendix:true`），`stage_by_group` 决定去向——数词/月份/星期 → `xs`（二级内容标准要求「数字、时间、日期」），国家与洲/学科/节日 → `zk`，高中 117 个国家/国籍词 → `gk`；`kind` 由 `derive_kind` 推出（首字母大写 → `proper_noun`，`services/words.py:149-150`；`I` 被归为 proper_noun 是既有规则副作用 [seed-pipeline-31]，不改）。影响（本设计复算，按常用附表近似）：数词 62 个常用形式中 46 在库（45 个 `stage_min=1`）、月份+星期 19 个全在库且 `stage_min=1` → 若附表入 xs，约 65 个今天的 zk 词改为 xs，xs 从 505 升到 ≈570；16 个序数词（thirteenth…millionth）不在库，附表若收录则新建。关闭 `stage_by_group` 的 xs 项即可回到严格 505。
- **N8 词组（上海 331）。** 规则：`kind=phrase`，阶段 zk，记号 `sh2020p`；只收 ECDICT 有词条的 272 条（全部 `frq=0/NULL` → 在默认词频排序中排最后，`vocab.py:76`、`batches.py:61`）；29 条含 `sb./sth./…/one's` 的句型模板（`agree with sb.`、`prevent...from`）标记 `pattern`，第一期跳过；**多词词头禁止用「去空格」匹配**——本设计复算发现 5 个假阳性 `break down→breakdown`、`take off→takeoff`、`turn out→turnout`、`turn over→turnover`、`work out→workout`（名词 ≠ 短语动词），所以 §3.4.3 的变体候选对含空格词头只允许「空格↔连字符」。影响：zk 总数 +272（2,520→2,792），`new_only(zk)` +272；今天 13 个 phrase 所经的每条路径（内容提示词 `content.py:90-91` 带 `kind`、卡片、搜索）都已覆盖 phrase。
- **N9 大小写与 lemma 唯一键。** lemma 全小写（`ux_words_lemma`，`0001_init.sql:205`）。`May`（月份附表）与 `may`（情态动词）是同一行——不新建、不改 display（ECDICT 释义含两义）；`China/Chinese/English` 保留大写 display。规则：解析先按小写 lemma 命中，display 只在「库内 display 全小写而官方词头首字母大写且 kind 为 abbreviation/proper_noun」时修正（N4 的 `Mrs.` 情形）。影响：无新行。今天 `May/may` 追加会覆盖原行 [seed-pipeline-12] 的风险由「同文件先到先得 + 单文件种子」规避——构建器从不为同一 lemma 产出两条记录。
- **N10 连字符/空格。** 规则：候选 `hot-dog → hotdog`、`ice-cream ↔ ice cream`（两者今天都在库，`ice cream` 只有 ecdict 记号、`ice-cream` 五个记号——并存的疣，不合并）、`e-mail/email`（都在库）、`T-shirt`、`CD-ROM`、`ping-pong`（在库，xs 词但 `frq` 空）。影响：无新行；`hotdog` 得 `sh2020`。
- **N11 ECDICT 义项错误的词头。** 本设计复算：`PE`→「相位编码」、`MS`→「微软公司」、`AI`→「附加信息, 人工智能」、`bund`→「(政治上的)同盟」（上海表指外滩）、`BCE`→「化学工程学士」、`CE`→「组件选通」。规则：N4 已把 `PE/Ms` 解析到现有 `p.e./ms.`；其余由 `data/lists/overrides.jsonl` 提供人工记录（`{"word":"AI","translation":["abbr. 人工智能（artificial intelligence）"],"phonetic":"","kind":"abbreviation","note":"ECDICT 义项为计算机术语"}`），构建器**优先**用覆盖记录、其次 ECDICT；若一个官方词头既不在库、不在 ECDICT、也无覆盖 → 构建失败（exit 2），不允许像今天那样静默丢进 `missing_from_ecdict`（`build_seed.py:119-121`）。影响：覆盖文件初版 ≈ 5 条（AI, bund, BCE, CE, 可选 UK）。
- **N12 单字母词。** `parse_list` 跳过长度为 1 的行（`build_seed.py:25`），把小学表的 `a`、`I` 当成分节标题丢掉 [seed-pipeline-2]。规则：只跳过**大写单字母且文件中出现 ≥ 20 次**的分节标题模式，`a`/`I` 白名单直接放行。影响：无新行（`a`、`i` 今天靠 ECDICT 标签在库），但 L2/L3 的 `a`、`I` 记号正确写入。

### 3.4 `build_seed.py` 的重构

**结论：保留单文件脚本形态与 15 键记录格式，内部改为 manifest 驱动的五步流水线；新增 `scripts/seed_diff.py` 与 `scripts/pack_seed.py`。**

#### 3.4.1 解析（修三个缺陷）

- `RICH_RE`（`build_seed.py:16`）要求 ASCII 词头后紧跟 `(`/`[`/`/`/空白/行尾，对全角括号、`=`、缺左括号、IPA 紧贴的行整行失败，丢了 7 行：`best（good, well的最高级）`、`less（little的比较级）`、`more（…）`、`wolf（复wolves）`、`practice(s)e`、`silentˈsailənt]`、`café` [verify list-sources-7/遗漏 3]。修法：**先对整行做 NFKC**（U+FF08/FF09 全角括号 → ASCII 括号，`=` 等同），再用「词头 = 行首字母串（允许 Latin-1 字母、`'-. `、≤4 词），其后任意非字母字符即结束」的宽松正则；括号内若是 `^[a-z]+$` 的裸词（`a (an)`）或 `x/y`、`x = y` 的并列，产出多个词头（N3）。效果：`best`、`less` 回到 zk（今天 `stage_min` 3 / 2），`an` 入 zk 并进一步入 xs，`cafe` 入 zk，`wolf/more/practice/silent` 的 `zk` 记号补上（它们今天靠 ECDICT 标签已在 zk 层）。
- plain 模式单字母白名单（N12）。
- 新增 `tsv` 模式（列按 manifest）与 `plain` 的 `#` 注释支持；`utf-8-sig` 继续（`:23`，中考表带 BOM）。

#### 3.4.2 加载与词形索引

与今天相同：先把 ECDICT 带 `zk/gk/cet4/cet6` 标签的全部行载入 `words`（`:105-109`）。新增：从每条记录的 `exchange`（`p d i 3 s r t`）建 `forms: form → [lemma]`，规则与 `seed.py:231-242` 完全一致（空形式跳过、形式本身是词头则不记），供 N5 使用。

#### 3.4.3 解析到现有词（resolver）

对每个 manifest 列表的每个词头，按 §3.3 顺序：精确 → 变体候选（单词：`+.`、`−.`、去重音、`-`↔空格、去 `-`；多词：仅 `-`↔空格）→ `forms` → `overrides.jsonl` → ECDICT（`lookup()` `:96-100` 的 `collate nocase` 精确 + 去重音 + 连字符变体）→ 失败即报错。每次命中记录 `(list_code, head, lemma, how)` 到 `resolution`。对 `legacy:true` 的表，失败沿用今天的「记入 missing、继续」（`:119-122`），因为它们不是官方依据。

#### 3.4.4 不在 ECDICT 的官方词如何生成记录

- 优先 `overrides.jsonl`（字段同种子记录，`word` 必填，其余可空）；
- 其次 ECDICT 行 → `make_record`（`:180-198`，不变）；
- 两者都没有 → 构建失败。**不**生成「音标/释义为空」的最小记录：`seed_row` 虽然接受 `{"word": …}`（`seed.py:174-183`，[seed-pipeline-9]），但空释义的词在卡片上没有任何可学内容，且 `frq` 为空会排到最后却仍出现在 `new_only` 与词库列表里。屈折形式的官方词头一律落到原形（N5），不以 `word_forms` 的形式新建词头。

#### 3.4.5 `stats.json` 结构（v2）

```json
{
  "schema": 2, "built_at": "…", "manifest_sha256": "…", "ecdict_release": "1.0.28",
  "total_words": 9466, "total_single_words": 9194, "total_phrases": 285,
  "per_stage": {"xs": 570, "zk": 2792, "gk": 4297, "cet4": 4722, "cet6": 7671},
  "first_stage": {"xs": 570, "zk": 2222, "gk": 1871, "cet4": 1207, "cet6": 3601},
  "core_per_stage": {"xs": 570, "zk": 2383, "gk": 3255}, "ext_per_stage": {"zk": 409, "gk": 1042},
  "per_source": {"l2": 505, "l3": 1600, "l3app": 84, "sh2020": 1731, "sh2020p": 272, "hs2020": 2997, "hs2025": 3104, "zk": 1887, "gk": 3446, "cet4": 4539, "cet6": 2220, "cet46": 8008, "cet6star": 1721, "ecdict": 8274},
  "resolution": {"l2": {"exact": 500, "variant": 3, "form": 1, "override": 0, "ecdict_new": 0}, "sh2020": {"…": "…"}},
  "forms_resolved": {"l3": [["according", "accord", "i"], ["excited", "excite", "p"]]},
  "variants_tagged": {"hs2025": [["colour", "color"]]},
  "skipped": {"sh2020p": {"pattern": 29}},
  "missing_from_ecdict": {"cet46": ["instalation"]},
  "declared_vs_parsed": {"l2": [505, 505], "sh2020": [1731, 1731], "hs2025": [3100, 3104]},
  "with_phonetic": 0, "with_translation": 0, "with_definition": 0, "with_exchange": 0, "multiword": 0, "uppercase": 0,
  "jsonl_sha256": "…", "file_bytes": 0
}
```

（数值为示意，按 §3.6 的复算量级填写；`pack_seed.sh:44-47` 只读 `total_words`，字段名保留。）`per_stage`/`first_stage` 的键顺序由秩表给出。

#### 3.4.6 种子版本差异报告 `scripts/seed_diff.py`

`seed_diff.py OLD.jsonl(.gz) NEW.jsonl(.gz) [--db live-copy.db] [--md out.md]`：

- 词级：新增（在 NEW 不在 OLD）、消失（在 OLD 不在 NEW，附「线上仍保留」提示）、每词 `stages` 变化按 `(old → new)` 组合分组计数并给前 10 个按 `frq` 的例子；`stage_min` 迁移矩阵；`sources` 新记号计数；display/translation 变化计数；
- `--db`：对照库内行，额外列出「会被覆盖的非阶段列」（例如 translation 变化）与**违反 I1 的词**（旗标变少或 `stage_min` 变高），非空则 exit 1；
- 输出 Markdown 提交为 `data/seed/CHANGES.md`（每次重建追加一节，含旧/新 sha256）。

本设计复算给出的首次报告样例（单词口径）：

| 变化 | 数量 | 例子（按词频） |
|---|---|---|
| zk → xs | 499 | the, be, and, of, a, in, to, have, it, I |
| gk → xs | 3 | an, astronaut, maths |
| cet4 → xs / cet6 → xs | 1 / 1 | best / chore |
| gk → zk | 304 | case, system, power, within, process, local, effect, major, less, view |
| cet4 → zk | 68 | community, actually, finally, economy, quickly, recently, response, resource, suddenly, writer |
| cet6 → zk | 23 | including, interested, educational, landscape, chip, online, mall, homeless, retired, pizza |
| cet4 → gk | 301 | issue, guy, economic, military, site, image, source, opportunity, current, involve |
| cet6 → gk | 69 | client, apparently, context, grab, corporate, ethnic, rating, gender, coverage, intervention |
| 合计 `stage_min` 下移 | 1,269 | 无任何上移（I1） |
| 新增单词 | ≈ 30 | angrily, beautifully, bund, calligraphy, carefully, Confucius, curd, dancer, dishonest, drone, due to, empathy, entirely, kung fu, lifestyle, luckily, mobile phone, pagoda, politely, quietly, seafood, teenage, tofu, UK, unforgettable, wetland, Wi-Fi, AI, BCE, CE |
| 新增词组 | 272 | a bit, in fact, look after, take part in … |
| 消失 | 0 | 加法设计下不会出现 |

#### 3.4.7 确定性输出与 gzip 哈希

- 记录排序键改为 `(rank(stage_min), lemma)`（今天 `:150-151` 用 `order` 字典，同义），JSON `sort_keys=True, ensure_ascii=False`，键集固定 15 个（兼容 `test_seed.py` 对记录形态的假设 [verify seed-pipeline-4]）。
- `kv.seed_version` 是 `.gz` 的 sha256（`seed.py:258, 287`；`main.py:313-314`），而 Apple gzip 与 GNU gzip 的 deflate 流不同（本机重压 `6841b7df…` ≠ 仓库 `a68127…` [seed-pipeline-7]）。结论：用 Python `gzip.GzipFile(mtime=0, compresslevel=9)`（zlib，跨平台同版本字节一致）替代 `gzip -9 -n`：新脚本 `scripts/pack_seed.py`（含 `--check`，不再依赖 BSD/GNU `zcat`、`stat -c`、`sha256sum` [seed-pipeline-8]）；`stats.json.jsonl_sha256` 记录解压内容哈希作为跨实现的「内容版本」。首次切换必然改变 `.gz` 哈希（本来就要变）。

### 3.5 `seed.py` 导入语义

#### 3.5.1 常量与列

- `STAGES`（`seed.py:43`）与 `stage_min` 公式（`:208`）改为引用一个共享秩表：`from .schemas import STAGE_ORDER, stage_to_index`（或 stage-model 切片给出的 `STAGE_RANK`），`stage_min = min(stage_to_index(s) for s in stages)`；同样替换 `services/ecdict.py:177`（运行时 ECDICT 查词也算 `stage_min`——否则重标后新添词仍按旧规则 [verify provinces 遗漏 2]）。
- `SEED_COLUMNS`（`:47-68`）加 `stage_xs`；`seed_row`（`:204-207`）加 `"stage_xs": int("xs" in stages)`；`_UPSERT_SQL`（`:72-82`）由列表自动生成，无需手改。`services/words.py:576-580 _word_defaults` 与 `:589-597 _INSERT_WORD_SQL`、`services/ecdict.py:173-177 word_columns`、`ai/prewarm.py:32-33` 同步加 `stage_xs`（否则 `_INSERT_WORD_SQL` 缺参数）。
- 前置守卫：导入前 `PRAGMA table_info(words)` 必须含 `stage_xs`，否则以清晰错误退出（而不是 SQLite `no such column`）。

#### 3.5.2 覆盖 20 列的现状对线上词的影响（结论：接受，但可预演）

upsert 覆盖全部种子列且只在有差异时写（`:75-81`），从不触碰 `active_content_id/difficulty/content_state/image_state/created_by_user_id` 与每用户表（`:10-12` docstring，[stage-model-19]）。新种子对现有 9,162 行的实际写入：旗标与 `stage_min` 变化 1,269+ 行、`sources` 变化约 6,000 行（所有在官方表里的词都多出记号）、display 修正几行、ECDICT 字段零变化（同一 release）。`updated_at` 随之更新 → `/media/card/{id}.svg` 的 LRU 键含 `updated_at`，卡片缓存失效一次（无害）。`word_forms` 删后重建（`:218-245`），`alt` 行保留。49 条 AI 内容、31 张图、77 行 `user_words` 不受影响。

#### 3.5.3 「删除/下架不再在种子中的词」与「保留旧阶段」策略（结论：永不删除；守卫单调）

- 从种子消失的词今天就留在库里 [seed-pipeline-14]，本设计不改（加法设计下也不会消失）。
- 新增 `plan(conn, rows) → SeedPlan`：对比库内 `lemma, stage_*, stage_min, display, translation` 与待导入行，产出 `inserted/updated/flag_added/flag_removed/min_lowered/min_raised/display_changed/translation_changed` 计数与样例。`import_seed(..., guard="monotonic")`（默认）在 `flag_removed > 0 or min_raised > 0` 时抛 `SeedGuardError` 并打印违例词；`--allow-regress` 关闭（回滚到旧种子时需要，§6.3）。
- `wd import-seed --dry-run`：只算 `plan`，打印报告，不开事务、不写 `kv`。

#### 3.5.4 `kv.seed_version`

语义不变（文件 sha256，`main.seed_check :307-319` 比较）。新增 `kv.seed_stats = {"schema":2, "jsonl_sha256":…, "lists_manifest_sha256":…}` 由导入器从随种子一起提交的 `stats.json` 读取（若文件存在），供管理页「词库版本」显示——可选。`--file` 指向补充文件后被仓库种子覆盖回去的陷阱 [seed-pipeline-14] 仍在：官方词只能进 `WD_SEED_PATH` 指向的那一个文件。

#### 3.5.5 测试夹具与测试的更新

- `backend/tests/fixtures/mini_seed.jsonl`（60 条，zk 35 / gk 52 / cet4 45 / cet6 24；first zk 35 / gk 19 / cet4 3 / cet6 3，本设计复算）：给 a, apple, be, book, cat, dog, good, happy, house, is, teacher, water, China, TV 等约 14 条加 `"xs"`（都已有 zk，保持 xs ⊆ zk）；`a` 的 `sources` 加 `l2 l3`；不加「仅 xs」的合成词。
- `test_seed.py::test_stage_flags_stage_min_and_cet6_star`（`:90-103`）：`:97` `word(conn,"a")["stage_min"] == 1` → `== stage_to_index("xs")`；加 `stage_xs` 计数断言。`::test_dictionary_column_mapping :113` `a["sources"] == "cet4 ecdict zk"` → `"cet4 ecdict l2 l3 zk"`。`::test_seed_row_mapping_and_validation :288-300`：加 `stages: ["xs","zk"]` 用例。`::test_full_seed_acceptance_numbers :338-353`：`:344-346` 改为新数字（§3.6.1），加 `stage_xs` 总数与 phrase 数（13 → 285）。
- `test_api_schemas.py:32-39`、`test_vocab.py:69-70`（5 行）、`test_vocab.py:232-234`（`3694 → 3601`，`7671` 不变）、`test_screen.py:133`（`stage=zk` 顺序 `["be","a","go"]`：若 be/a 得 xs 而 go 不得，xs 词在 `cur=1` 下距离为 2，顺序变 `["go", …]`——改断言或不给 be/a 加 xs；建议改断言以覆盖这条真实语义）、`test_content_apply.py:255`（`go` 的 `stages` 中文名列表若含小学）、`scripts/smoke.py:352, 614`（4 → 5）、`test_batches.py:127`（cur=cet4 不受影响，回归即可）。
- 新测试：`backend/tests/unit/test_build_seed.py`（`importlib` 载入 `scripts/build_seed.py`）：7 条问题行的解析、`a (an)`→两词头、单字母白名单、TSV 列、resolver 的 dot/hyphen/accent/forms 四类变体、多词禁止去空格、overrides 优先、官方词头缺失即失败；用临时 SQLite 造 10 行 `stardict`。`test_seed.py` 新增：单调守卫拒绝/放行、dry-run 不写、`stage_xs` 列缺失的错误信息、phrase 记录。`test_seed_diff.py`：两份小 jsonl → 报告与 exit code。

#### 3.5.6 两位线上用户

`user_settings` 两行（`(1, 3, ["zk","gk","cet4","cet6"])`、`(2, 1, ["zk"])`，`live-copy.db`）不由种子触碰；0011 的迁移文件（stage-model 切片）对它们写死的规则建议为**无操作**：`xs ⊆ zk` 使候选池不变；UI 层「是否默认勾选小学页签」是前端问题。效果见 §3.6.4。

### 3.6 对调研数字的使用与量化代价

#### 3.6.1 采用的数字

INDEX §4.1 修正后数字全部采用（L2 505 / 500 在库；L3 1600 / 1,592；SH 1,731 + 331 / 1,702–1,703；HS3000 2,997 / 2,981；HS3100 3,104 / 3,112）；上海口径固定 **1,731 + 331** [verify provinces-12]。本设计复算基于 verify 产出的解析文件（S 1,722 词头版，与 1,731 的差是 9 个并列拼写，它们都已在库，不影响集合大小 ±9），对照结果与 INDEX 一致：L2 500 精确 + 3 变体 + 1 屈折 + 1 缺；SH 1,694 精确、309→ 本设计 326 个 S 词今天无 zk 旗标（含 17 个经变体/屈折/新建才进入的词）。ECDICT release `stardict.db` 的 `tag` 全集（本设计复算，851 MB 文件、3,402,564 行、14,942 行有标签）与 csv 完全相同：`gre 7504 / toefl 6974 / cet6 5407 / ielts 5040 / ky 4801 / cet4 3849 / gk 3677 / zk 1603`——**release 也没有小学标签**，关闭 INDEX 未解决问题 6 的这一半。

#### 3.6.2 新阶段集合与验收数字（单词口径，附表未入 xs，词组另计）

| | 今天 | 连续性设计 | 变化 |
|---|---|---|---|
| `stage_xs=1` | — | 505 | +505（+65 若附表入 xs）|
| `stage_zk=1` | 2,099 | 2,520 | +421（S 326、L3 183、重叠 88）；+272 词组 → 2,792 |
| `stage_gk=1` | 3,829 | 4,297 | +468 |
| `stage_cet4/cet6` | 4,722 / 7,671 | 不变 | — |
| `stage_min` 分布 | 2,099 / 1,792 / 1,577 / 3,694 | xs 505 / zk 2,015 / gk 1,871 / cet4 1,207 / cet6 3,601 | 1,269 词下移；`new_only(cet6)` 3,694 → 3,601 |
| 总词数 | 9,162 | ≈ 9,194 单词（+ 272 词组 = 9,466）| 新建 ≈ 30 单词 |
| 初中页签「仅本阶段新增」 | 2,099（= 全部，空操作 [INDEX A6]）| 2,015（不含 505 小学词）| 变成有意义的筛选 |

这些是 `docs/TASKS.md:172-178`、`test_seed.py:343-346`、`test_vocab.py:232-234`、`DESIGN.md:186, 209`、`API.md:169`、`README.md:9, 103` 需要改写的验收数字；最终值以词表流水线交付的文件为准（预期 ±1%）。

#### 3.6.3 超纲比例（代价）与上海学生的排序体验

- **原始口径**：阶段内不在该阶段任何官方表的词——zk 506/2,520 = **20.1%**，gk 1,093/4,297 = **25.4%**。
- **扣除体例差异**：官方表把数词/月份/星期/国家放附表、把美式拼写放括注，这些不是真超纲。zk 层有 95 个附表词（two, three, million, four, hundred, Monday…）与 2 个美式拼写（math, mom），gk 层 25 个附表词与 26 个美式拼写（program, center, realize, defense, behavior, color…）→ 超纲 zk **409/2,520 = 16.2%**，gk **1,042/4,297 = 24.2%**。
- **只看单一官方表**：zk 中 36.3% 不在国家三级、31.9% 不在上海表——说明「只认一张表」会把今天三分之一的初中词踢出去，这正是连续性路线要避免的。
- **纯旧表词**：999 个（zk 层 222、仅 gk 777）既不在任何官方表，也非附表/变体；其中 772 个同时带 cet4/cet6 标签（对大学用户仍是核心），**227 个没有任何官方或 CET 归属**（旧高考 3500 谱系 [INDEX A1]）——这是连续性设计真正「多背」的部分，占全库 2.5%。
- **上海初中生（目标阶段 xs+zk，主攻 zk）看到的推荐词/筛词**：候选按 `stage_distance → frq` 排序（`batches.py:60-61`、`screen.py:34-36`），本设计复算 zk 层按词频前 50 / 100 / 300 / 600 / 1,000 个候选里，拓展词 **0 / 0 / 0 / 5 / 30** 个，不在上海表的词 3 / 5 / 10 / 28 / 88 个（例：policy, drug, leader, federal, movement, thus, treatment, beyond, growth, professor）。也就是说一个学生要做完约 600 个推荐词才会碰到第一批拓展词；按每天 15 个推荐词（`daily_screen_count` 默认），是 40 天以后。词组（`frq` 空）全部排在 2,520 个单词之后。结论：第一期不做核心优先排序也可接受；第二期的 `core_min` 排序键把 409 个拓展词整体后移，是改善尾部体验的杠杆（§7.2）。
- **`difficulty` 尺子**：`vocab.py:78` 的 `COALESCE(difficulty, stage_min, 5)` 在 xs 秩 = 0 时把小学词排最前，49 行 `difficulty`（1:2 / 2:1 / 3:43 / 4:3）含义不变（Q5 选项 a），零代码。

#### 3.6.4 对两位线上用户

- 用户 1（四阶段、主攻 cet4）：候选池 9,162 → 9,199（+272 词组后 9,471）；370 个词的 `stage_min` 从 cet4 降到 gk/zk/xs，对主攻 cet4 的推荐词排序意味着它们从距离 0 变为距离 2–6（`issue, guy, economic, military, site, image…`）——这些词确实是高中课标词，排序变化方向合理。
- 用户 2（只选 zk、主攻 zk）：候选池 2,099 → 2,520（+词组 272）；499 个最基础词变为小学词（距离 2），推荐词先给 2,015 个纯初中词——对初中生是正确方向，但要在发布说明里写明「推荐词顺序会变」。

---

## 4. 改动清单（文件 → 改什么）

| 文件 | 改什么 |
|---|---|
| `data/lists/README.md`、`manifest.json`、`overrides.jsonl`、`*.txt/*.tsv`（新） | §3.2 的格式、清单、provenance 表、许可段；文件由词表流水线产出，本切片提供格式与 `overrides.jsonl` 初版（AI, bund, BCE, CE, UK） |
| `scripts/build_seed.py` | `:15-17` 正则重写（NFKC 预处理、宽松词头、并列拆分）；`:20-48 parse_list` 加 `tsv` 模式、`#` 注释、单字母白名单；`:72-88` 参数改 `--manifest/--lists-dir/--db/--out`，`syllabus` 由 manifest 构造；`:96-100 lookup` 加去重音/连字符候选；`:102-147` 改为 resolver 五步（§3.4.3），legacy 表保留「记 missing 继续」，官方表失败即 exit 2；`:112 stage_from_list`、`:147`、`:150 order`、`:191` 的四码元组改为从秩表/manifest 推出；`:157-171` stats v2；`:176-177, 201-219` ATTRIBUTION 从 manifest 渲染；排序键与 `sort_keys=True` |
| `scripts/seed_diff.py`（新） | §3.4.6 |
| `scripts/pack_seed.py`（新）；`scripts/pack_seed.sh` 删除或改为薄包装 | Python gzip `mtime=0`，`--check`；`Makefile:97-98` 改调用 |
| `Makefile:93-98` | 加 `LISTS_DIR ?= data/lists`；`build_seed.py --manifest …`；去掉 `gzip`/`zcat` |
| `backend/wd/seed.py` | `:7` docstring；`:43 STAGES` → 秩表；`:47-68 SEED_COLUMNS` + `stage_xs`；`:204-208` 加 `stage_xs`、`stage_min = min(rank)`；新增 `plan()`、`SeedGuardError`、`guard` 参数、`stage_xs` 列前置检查；`:333-360` CLI 加 `--dry-run`、`--allow-regress`；`:287-305` 可选写 `kv.seed_stats` |
| `backend/wd/services/words.py` | `:39 STAGES` + `xs`（或引用 schemas）；`:576-580 _word_defaults`、`:589-597 _INSERT_WORD_SQL` 加 `stage_xs` |
| `backend/wd/services/ecdict.py` | `:28 STAGE_TAGS` 不加 xs（ECDICT 无此标签，已核实）；`:173-177 word_columns` 加 `"stage_xs": 0` 并用共享秩表算 `stage_min` |
| `backend/wd/ai/prewarm.py:32-33` | `STAGE_COLUMNS["xs"]="stage_xs"`、`STAGES` 加 `xs` |
| `backend/wd/ai/content.py:49` | `STAGE_ZH["xs"]="小学"`（否则 `prompt_entry :88` 对小学词 `KeyError` 整组失败 [INDEX D6]）；`:48 AUDIENCE` 与 `prompts/content_system.txt:1` 的受众文案属 AI 切片 |
| `backend/wd/migrations/0011_*.sql`（stage-model 切片拥有） | 本切片的依赖：`ALTER TABLE words ADD COLUMN stage_xs INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs IN (0,1))`（0010 先例，additive）；`stage_min`/`current_stage` 的 CHECK 放宽到 xs 的秩（整表重建，先 `DROP VIEW v_bank` [stage-model-13]）；两位用户的设置行不改 |
| `backend/wd/schemas.py:25-26, 51-52, 56-67, 488, 708, 1335`；`frontend/src/api/types.ts:5-6`；`docs/API.md:239-240, 460` | 阶段枚举扩展与 `StageIndex` 值域（含 0 或 5）——stage-model / 前端切片拥有；`scripts/check_contract.py:274-281` 顺序敏感比对要求同一提交 |
| `backend/tests/fixtures/mini_seed.jsonl` | ≈14 条加 `"xs"`，`a` 的 `sources` 加 `l2 l3` |
| `backend/tests/unit/test_seed.py` | `:97, :113, :288-300, :343-353` 按 §3.5.5；新增守卫/dry-run/列缺失/phrase 测试 |
| `backend/tests/unit/test_build_seed.py`、`test_seed_diff.py`（新） | §3.5.5 |
| `backend/tests/integration/test_vocab.py:69-70, 232-234`、`test_screen.py:133`、`test_content_apply.py:255`、`unit/test_api_schemas.py:32-39`、`scripts/smoke.py:352, 614` | 行数 4→5、新验收数、顺序断言 |
| `backend/tests/unit/test_db.py` | 若 0011 只加列不加表，`:13-17 EXPECTED_TABLES`/`:51` 不变；加 0011 升级测试（仿 `:236-257`、`:283-310`） |
| `docs/DESIGN.md:186, 193-209（§3.2 表与验收数）, 321-322` | `stage_xs`、秩表、新数字、`sources` 记号、词组口径 |
| `docs/TASKS.md:168-178` | 验收脚本数字 |
| `docs/API.md:167（"4 rows"）, 169（3,694）` | 行数与数字（§9 字面量由 stage-model 切片） |
| `docs/DEPLOY.md` | §4 不变（无新 Settings 字段，`deploy/env.example` 不变）；§5/§10 加一句「导入前 `wd import-seed --dry-run`；守卫拒绝时的处理」 |
| `README.md:5, 9, 78-79, 103` | 词表范围与数字 |
| `ATTRIBUTION.md`（根）§2 `:19-32`；`data/seed/ATTRIBUTION.md`（生成） | 官方词表一节；mahavivo 一节改写 |
| `frontend/src/i18n/zh.ts:86` 与 `docs/FRONTEND.md:292` | `sources.lists` 文案改为「词表范围：义务教育课标二级/三级、上海初中词汇表、高中课标、大学英语四级与六级大纲」——两处必须逐字一致（`zh.test.ts:19-30` 读取 FRONTEND.md §8 校验） |
| `docs/SCHEMA.sql` | **不改**（`test_db.py:362-366` 要求与 0001 字节一致）；`0001_init.sql:186` 的「cet6: 3,694 words」与 `:215`「388 in the seed」注释随之陈旧，接受 |

---

## 5. 测试与验收

**会红的已有测试（按上面改动）**：`test_seed.py::test_stage_flags_stage_min_and_cet6_star`（`:97`）、`::test_dictionary_column_mapping`（`:113`）、`::test_full_seed_acceptance_numbers`（`:343-346`，仅 `full_seed` 标记下）；`test_vocab.py::test_stages_totals_and_progress`（`:69-70`）、`::test_full_seed…`（`:232-234`）；`test_api_schemas.py::test_stage_mapping_roundtrip`（`:33-39`）；`test_screen.py`（`:133`）；`test_content_apply.py::test_prompt_shape…`（`:255`，若 `go` 得 xs）；`scripts/smoke.py`（`:352, 614`）；前端 `zh.test.ts` 若只改 `zh.ts:86` 不改 `FRONTEND.md:292`。

**要加的测试**：§3.5.5 的三组（build_seed 解析/解析器、seed 守卫与 dry-run、seed_diff）；一条「新种子对旧库的 I1 不变量」集成测试：在 `seeded` 夹具（`conftest.py:203-209`）上导入「加了 xs 的 mini seed」→ 旗标只增、`stage_min` 只降、`user_words`/`word_contents` 字节不变；一条「旧代码读新种子」回归：`stages` 含未知码时静默忽略（今天的行为 `seed.py:184-185`，固定下来）。

**在 `live-copy.db` 私有拷贝上的排练（一律 `.venv/bin/python`，不用 `/usr/bin/sqlite3` 排练迁移 [verify stage-model-13]）**：

```
D=scratchpad/word-lists-continuity/rehearsal; mkdir -p $D && cp scratchpad/live-copy.db $D/word-dance.db
export WD_DATA_DIR=$D WD_DB_PATH=$D/word-dance.db WD_SEED_PATH=data/seed/vocab.jsonl.gz
.venv/bin/wd migrate --dry-run && .venv/bin/wd migrate             # 0011；pre-migrate 快照落在 $D/backups
.venv/bin/wd import-seed --dry-run                                  # 守卫报告：flag_removed=0, min_raised=0, 1,269 min_lowered …
.venv/bin/wd import-seed                                            # 0.2–0.5 s [seed-pipeline-15]
python3 -I scripts/seed_diff.py <old.gz> data/seed/vocab.jsonl.gz --db $D/word-dance.db
sqlite3 -readonly "file:$D/word-dance.db?mode=ro" "select sum(stage_xs),sum(stage_zk),sum(stage_gk),sum(stage_cet4),sum(stage_cet6) from words; select stage_min,count(*) from words group by 1; select count(*) from words where kind='phrase'; select count(*) from user_words; select count(*) from word_contents;"
WD_FULL_SEED_DB=$D/word-dance.db .venv/bin/pytest -q backend/tests -m full_seed
```

验收口径：`sum(stage_xs)` = 505（或 ≈570）；`stage_zk` ≈ 2,520 (+272)；`stage_gk` ≈ 4,297；`cet4/cet6` 不变；`stage_min` 无 NULL；`user_words` 77、`word_contents` 49、`word_images` 31 不变；`/api/stages` 5 行且 `new_only_total` 之和 = 词总数；`/api/vocab?stage=zk&new_only=1` total ≈ 2,015 (+272)。

---

## 6. 上线与回滚（Mac：launchd，无 install.sh/systemctl）

本机布局见记忆文件 `macos-local-install.md`：数据目录 `/Users/sqin/word-dance-data`，服务 `~/Library/LaunchAgents/com.word-dance.server.plist`，`wd serve` 启动时自动 `run_migrations`（先 `snapshot_before_migrate` 写 `backups/pre-migrate-<from>-to-<to>.db.gz`，`backup.py:283-296`）再 `seed_check`（`main.py:477-485`）。顺序「先迁移后导种子」已满足 `stage_xs` 列先于新种子 [stage-model-20]。

**步骤（由运维者在本机执行；本设计者不触碰该目录）**

1. 停服务：`launchctl bootout gui/$(id -u)/com.word-dance.server`；确认 `curl --noproxy '*' http://127.0.0.1:8000/api/health` 失败。
2. 手工快照（双保险）：`WD_DATA_DIR=/Users/sqin/word-dance-data .venv/bin/wd backup --keep-daily 14 --keep-weekly 8`。
3. 更新代码与种子：`git pull`/checkout 含 0011 + 新 `data/seed/vocab.jsonl.gz` + `data/lists/` 的提交；`make setup PYTHON=python3.12`（若依赖变）；前端按记忆文件的快照方式发布到 `frontend-releases/<sha>`（阶段枚举变了，前端必须同次上线：否则旧 SPA 的 `ScreenPage.tsx:31` 静默丢掉 xs 页签、`VocabPage.tsx:29` 没有 xs tab，但后端已正常）。
4. 显式迁移并预演导入：`WD_DATA_DIR=… .venv/bin/wd migrate`（0011；`pre-migrate-10-to-11.db.gz`）→ `.venv/bin/wd import-seed --dry-run` → 报告无 `flag_removed/min_raised` → `.venv/bin/wd import-seed`。
5. 起服务：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist`（或 `kickstart -k`）；`wd serve` 发现种子哈希已一致，不再重导。
6. 验证：`/api/health`；登录后 `GET /api/stages` 5 行；`sqlite3 -readonly` 跑 §5 的计数；检查日志 `~/Library/Logs/word-dance/word-dance.log` 中 `seed_imported` 事件；`PRAGMA integrity_check`。
7. 事后：重建 `words` 使文件 5.6 MB → 9.4 MB [verify stage-model 遗漏 4]，可在停服时 `sqlite3 word-dance.db VACUUM`（迁移文件内不能 VACUUM）。

**回滚**

- 迁移后、导入前出问题：`launchctl bootout` → `wd restore backups/pre-migrate-10-to-11.db.gz --yes` → checkout 旧提交 → 起服务。
- 导入后要退种子但保留 0011：`wd import-seed --file <旧 vocab.jsonl.gz> --allow-regress`（守卫会拒绝旗标回退，必须显式放行）；`stage_xs` 全部归 0、`stage_min` 回升；新建的 ≈30 词 + 272 词组留在库里（从不删除）。
- 一旦有用户选了 xs，只回退代码不可行（旧 `schemas.py:65` 对越界索引抛 `ValueError` → 500 [verify stage-model 遗漏 2]），只剩快照恢复，且丢失快照后的学习记录——写进发布说明。

---

## 7. 风险、未决问题、工作量

### 7.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 词表文件尚未由另一条流水线交付；本设计的数字基于 verify 产出的解析文件（S 为 1,722 词头版、HS3100 为 3,106 解析口径） | 验收数字 ±1% | 所有验收常量在文件交付后由 `build_seed` 的 stats 重新生成；`declared_vs_parsed` 必须一致才允许提交 |
| 2025 修订版 3100 印发文号未见 [verify provinces-4] | 若正式版有增删，需重建 | manifest `provisional:true`；加法设计下只会多出记号，不会降级 |
| 秩值编码（xs=0 vs 重编号）由 stage-model 切片决定；0 值在 `screen.py:44`、`batches.py:272, 698` 的 `or DEFAULT` 处被当作缺失 | 主攻小学的用户推荐词按 cet4 排 | 本切片不受影响（秩表一处）；在集成测试里加「`current_stage` 为最小秩」用例，提醒另一切片 |
| 272 个词组进入 zk | 初中用户的词库页/「仅本阶段新增」多出 272 条 `frq` 为空的条目，排在最后 | manifest `phrases:true` 可关；内容生成对 phrase 已有路径 |
| 屈折形式落到原形（N5）：`lost/frozen/united/according` 作为形容词/介词的义项不单独成卡 | 学习者查 `lost` 得到 `lose` | 记录在 `stats.json.forms_resolved`；第二期可用 `word_forms.kind='alt'` 或独立词头 |
| ECDICT 义项错误的新词头（AI/bund/BCE/CE） | 释义误导 | `overrides.jsonl` + 构建失败规则（N11）；覆盖记录需人工复核（管理员维护共享词库路线，`docs/WORD_LIBRARY_CURATION.md` §2.4 阶段 C） |
| 导入改写 ≈6,000 行 `sources` 与 1,269 行旗标，`updated_at` 变化使 SVG 卡片缓存失效 | 一次性 | 无害；`seed_diff --db` 预览 |
| 旧 `data/seed/ATTRIBUTION.md` 手改被覆盖 | 文档漂移 | 从 manifest 渲染后不再手改 |

### 7.2 未决问题

1. 附表（数词/月份/星期）是否入 xs（默认入，≈+65 词）；国家名/学科入 zk 的分组表由词表流水线按原件产出。
2. 上海 PDF 文本缺 `a`/`an`（手册 1733 vs PDF 1731）[verify shanghai-secondary-8]：按 PDF 收录，`a/an` 由 L2/L3 覆盖，不人工补。
3. 第二期「拓展」的落地方式：`core_min INTEGER`（additive 列、种子列）+ 三处 ORDER BY 加次级键 `(w.core_min IS NULL)` + `WordBrief` 可选字段 + 「拓展」芯片（契约变更：`API.md §9`、`types.ts`、`schemas.py` 同提交）；还是走 `word_stage_tags`/`stage_defs`（[stage-model-17]）一并解决地区维度。本设计推荐先观察第一期的 16.2%/24.2% 是否被用户感知再决定。
4. 并存疣的合并（`a.m`/`a.m.`、`ice cream`/`ice-cream`、`miss`/`miss.`、`e-mail`/`email`）需要 `merged_into_word_id` 流程与前端跟随，不属于种子。
5. 上海高中 200 个补充词与 2026 年手册（1,785 + 347）无机读版 [INDEX B6/B7]；manifest 预留 `sh_gk`、`sh2026` 码位。
6. 是否把 `scripts/build_seed.py` 的纯函数搬进 `backend/wd/`（便于 pytest 直接导入而非 `importlib`）。
7. `kv.seed_stats` 与管理页展示是否需要（可选）。

### 7.3 工作量（本切片，人日）

| 项 | 人日 |
|---|---|
| `data/lists/` 格式、manifest、README provenance/许可、overrides 初版（消费另一流水线的文件） | 1.0 |
| `build_seed.py` 重构（解析修复、manifest、resolver、overrides、stats v2、ATTRIBUTION 渲染、确定性输出）+ `pack_seed.py` | 2.5 |
| `seed_diff.py` + `seed.py`（`stage_xs`、秩表、`plan`/守卫、`--dry-run`/`--allow-regress`、列前置检查）+ `words.py`/`ecdict.py`/`prewarm.py`/`content.py` 常量 | 1.5 |
| 夹具与测试（现有 10 处 + 新 3 组）、full_seed 验收数、smoke | 1.0 |
| 文档（DESIGN §3.2、TASKS、API 数字、README、ATTRIBUTION ×2、FRONTEND §8/zh.ts 文案、DEPLOY 一句） | 0.5 |
| `live-copy.db` 排练 + Mac 发布说明与执行陪护 | 0.5 |
| **合计** | **≈ 7（6–8）** |

不含：0011 的表重建与 CHECK 放宽、阶段枚举在后端/前端/契约的扩展、引导页「小学生」角色、`difficulty` 尺子（均属 stage-model / 前端 / AI 切片，INDEX §6.3 估计 ≈ 迁移 100 行 + 后端 30–50 + 测试 70–120 + 前端 30–50 行）。
