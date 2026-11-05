# 词表来源与种子流水线 · 设计「官方纯净」

日期 2026-11-05 · 基线 `main @ 75df534` · 角度：阶段成员**只**由官方词头文件（国家 2022 二级/三级、国家高中 2020 版 3000 / 2025 修订 3100、上海市教育考试院 2020 词汇表）与 ECDICT 的 cet 标签决定；mahavivo 的中考表、Highschool 表、小学表退出。本文只负责「词表 → 种子 → 导入」这一条线；阶段枚举/迁移 0011/前端页签属其他设计线，本文在 §3.1.4 给出对它们的**接口要求**，不替它们做决定。

所有数字口径：线上库只读副本 `scratchpad/live-copy.db`（9,162 词），官方词表用本目录 verify/ 已核验的解析文件重算（脚本 `scratchpad/word-lists-official-purist/{loaders2,final}.py`，`python3 -I`，只读）；最终的 `data/lists/` 文件由本工作流的另一条流水线产出，本文只定义格式与消费方式，所以下文数字标「≈」的都带 ±1% 的解析噪声（见 §7.2）。

---

## 1. 一页结论

**决定了什么**

1. **阶段成员的集合代数**（§3.1）：
   `xs = L2 ∪ V(L2) ∪ A_num ∪ A_cal`；`zk = L3 ∪ V(L3) ∪ A_num ∪ A_cal ∪ A_geo ∪ A_org ∪ A_cult ∪ SH_w`；`gk = HS3100 ∪ V(HS3100) ∪ HS3000`；`cet4 / cet6` 维持现状（ECDICT cet 标签 ∪ mahavivo 三张 CET 表）。V(·) = 官方括注给出的拼写变体/等价形式（colour→color、bike→bicycle），A_* = 课标附录「单列」的数词、月份星期、地理、机构、文化专名。**ECDICT 的 zk/gk 标签不再决定成员**（它们是旧考纲谱系，与现行课标不对应；verify list-sources-2 / 本次实测 release 库 tag 全集 = csv 8 值）。
2. **不做人为闭包**：国家表自身已累计（L2 ⊂ L3 ⊂ HS3100，由文件构造保证，实测 XS ⊆ ZK 成立），只有上海表带来 198 个「初中有、高中无」的词（131 个上海独有派生副词/口语词 + 67 个附录数词/文化专名）；它们保留为 `zk=1, gk=0`，真实反映两份官方文件的关系。`stage_min` = 旗标中最低阶段的序号（`seed.py:208` 公式不变，随 `STAGES` 元组自动变为 1..5）。
3. **官方词表进仓库**：新目录 `data/lists/`，每张表一个纯文本/TSV 文件（一行一词头，`#` 头部注释写来源 URL、md5、获取日期、解析规则、计数），`manifest.json` 声明文件→阶段→解析模式→来源 id，`aliases.tsv`（官方书写 → 库内 lemma：Mr→Mr.、PE→P.E.、café→cafe、hot-dog→hot dog）、`overrides.jsonl`（ECDICT 无条目或义项错误的 ≤10 个官方词的手写释义：bund、mum、bce/ce、Mount Huangshan…）。mahavivo 的 CET 三表仍在仓库外（`WORDLISTS_DIR`），因为它们的来源是 cet.edu.cn 2016 大纲与贵州大学 PDF（mahavivo README 有说明），且现在没有可替代的官方机读件。
4. **种子记录格式 v2**：15 个字段不变，新增可选 `variant_of`、`hs_level`（0/1/2，高中课标星级），`sources` 改为词表 id 词汇（`moe22-l2 / moe22-l3 / moe22-app / shmeea20 / hs20 / hs25 / ecdict-cet4 / cet46 / legacy-zk …`）；`stats.json` 加 `per_source`、`lists[]`、`stageless`、与上一版种子的差异摘要；新脚本 `scripts/seed_diff.py` 产出 `data/seed/DIFF.md`（逐词阶段变化、新增、消失）。
5. **导入语义不变但可见**：`wd import-seed` 仍是「覆盖 20 个种子列、从不删行」（`seed.py:72-82`）；新增 `--dry-run`（打印插入/更新/阶段变化计数与前 N 个差异，不写库）。不在任何官方表里的旧词**不删除**，留在种子中作 `stages: []` 的词典词（`stage_min NULL`，只在「全部」页签与搜索可见），`sources` 带 `legacy-zk/legacy-gk` 记录它们的来历。
6. **修 `build_seed.py` 的已知缺陷**（即使不换词表也该修）：`RICH_RE` 吃掉全角括号/`=`/缺左括号行（`best`、`less`、`cafe`、`wolf…` 共 7 行，verify list-sources-7）、`a (an)` 只产出 `a`、plain 模式丢单字母 `a`/`I`（seed-pipeline-2）。

**为什么**：官方件是唯一许可干净且有现行效力的阶段定义（INDEX C4、Q8-a）；现 zk 有 32.4% 不在国家三级表、现 gk 有 31.2% 不在国家高中表（INDEX C1/C2），不是「补几个词」能修的。合并上海表进 zk（A4 不分省）让上海初中生不漏词：上海表 24.1% 不在国家三级表（INDEX B5）。

**代价多少**（线上 9,162 词 → ≈9,274 词；细表见 §3.6）

| 阶段 | 现在 | 新 | 增 | 减 |
|---|---|---|---|---|
| xs 小学 | — | ≈594 | 578 个现有词加标 + 16 个新词（序数词 14、`excited`、`physical education`） | — |
| zk 初中 | 2,099 | ≈2,194 | +510（416 现有词重标 + 94 新词） | −415（188 留在高中层、155 只剩 CET 层、72 无阶段） |
| gk 高中 | 3,829 | ≈3,253 | +479（449 + 30） | −1,055（764 只剩 CET 层、213 无阶段、78 仍在初中层） |
| cet4 / cet6 | 4,722 / 7,671 | 不变 | | |
| 无阶段（词典词） | 0 | ≈243 | 171 个旧「仅高中」+ 42 个「初中+高中」+ 30 个「仅初中」；0 个被任何用户收藏、0 个有 AI 内容 | |

导入时全部 9,162 旧行都会被「更新」（`sources` 词汇整体改写），其中 2,603 行阶段集合变化、2,562 行最低阶段变化。`stage_min`（新编号 xs=1…cet6=5）分布 ≈ 594 / 1,600 / 1,257 / 1,726 / 3,854 / NULL 243；`docs/TASKS.md:172-175`、`test_seed.py:343-346`、`API.md:169`（3,694）、`DESIGN.md:209` 的验收数字全部作废，以新 `stats.json` 为准。线上 2 个用户的 77 个生词中 64 个阶段集合会变（几乎全是「多了一个阶段」），不影响他们的学习记录。

工作量（本线）：≈8 人日（§7.3）。前置依赖：0011 迁移（`stage_xs` 列 + `stage_min`/`current_stage` CHECK 放宽到 1..5）与 10 份阶段常量的扩展由阶段模型线完成；**部署顺序「停服务 → migrate → import-seed → 起服务」已能保证列先于数据**（`main.py:482-485`，`install.sh:140-141`）。

---

## 2. 对照假设 A1–A6 的偏离

| 假设 | 本设计 | 偏离与理由 |
|---|---|---|
| A1 小学 = 国家二级 505 骨架 | 采用，并**加入课标附录单列的数词/序数词（58）与月份星期（19）**，不加教材词 | 课标二级说明 5「数词…月份、星期等单独列出」（verify list-sources 遗漏 1；转录件 `std2022.txt:1854`）——它们是二级应学内容，只是体例上单列；2011 版二级表把它们列在表内。不加附录会让 `Monday`、`January`、`ten` 落在小学层之外。教材拓展另议（Q2-c），本设计给它预留 `manifest` 的 `member: false` 词表位。 |
| A2 初中 = 上海 2020 ∪ 国家三级；高中 = 3100（含 3000） | 采用；高中写成 `HS3100 ∪ HS3000`（显式并集而非「含」） | 实测 2025 修订主表**不**包含 2020 版主表的 94 个词：月份/星期/数词与国籍词（`african, american, january, monday, one…`）在 2025 版挪进了附录（`provinces` 作者解析 3,221 = 3,104 + 117 国家附表）。按字面「含 3000」会把这 94 个词丢出高中层，所以用显式并集；2025 版的 117 个国家附表词（`afghanistan, argentinian…`，说明 7「供教学参考」）**不**入成员。上海表的 331 个词组见 §3.3.7（本轮不入阶段）。 |
| A3 只用官方词头；mahavivo 中考/高中表退出；有道系/墨墨不入库 | 采用；**额外**把 ECDICT 的 zk/gk 标签也排除出成员判定；**保留** mahavivo 三张 CET 表 | ECDICT zk/gk 标签来自「最初的中高考各类考试大纲」（ECDICT wiki，verify list-sources-2），不是现行课标：它的 1,603 个 zk 词里 117 个不在新初中集合、3,677 个 gk 词里 995 个不在新高中集合。若改用「纯 ECDICT cet 标签」定义 CET（角度的字面读法），cet4 从 4,722 跌到 3,849、cet6 从 7,671 跌到 5,407，另有 2,045 个词变成无阶段——对现有两位 CET 用户是纯损失且没有官方替代件，所以 CET 维持现状（`build_seed.py:84-87,128-142` 逻辑原样保留），并在 §7.2 登记「把 cet.edu.cn 2016 大纲 PDF 解析进 `data/lists/` 以彻底摆脱 `WORDLISTS_DIR`」为后续项。 |
| A4 不按省份分层 | 采用：上海表并入 zk，**不**建「上海/全国」双方案；但 `sources` 逐词记录 `moe22-l3` 与 `shmeea20`，未来要拆方案只需读 `sources`，不必重解析 | 两份表的差异是真实的（国家侧独有 463、上海独有 395、共有 1,336），合并后上海初中生多拿到 463 个国家词、全国初中生多拿到 395 个上海词（其中 154 个本来就是现 zk）。「拓展/超纲」层：本轮**不**加阶段位，用 `sources` 的 `legacy-zk/legacy-gk` 与 `stages: []` 词典词保留信息（§3.7）。 |
| A5 配图 | 不涉及 | — |
| A6 新用户默认 K-12；老用户迁移规则写死 | 本线只提供数据侧事实：用户 2（`stages_json=["zk"]`, `current_stage=1`）与用户 1（四阶段, 3）的词在新集合下的变化见 §3.6.6；`stages_json` 的码是字符串不需重编号，`current_stage` 整数需 +1（阶段模型线） | — |

另外两个本设计自己拍的板（原假设未提及）：**(a)** 官方括注的变体/等价形式继承阶段（`colour`→`color`、`bike`→`bicycle`、`maths`→`math,mathematics`），共 57 个现有行受益，不建重复行；**(b)** 上海表里的 12 个屈折形容词（`excited, frightened, lost, united…`）与 6 个派生副词成为自己的词条行（ECDICT 有独立义项），`word_forms` 里 `excited→excite(p)` 一类映射按既有「表头词守卫」规则自然消失（§3.3.4）。

---

## 3. 详细设计

### 3.1 阶段成员的集合代数与单调性

#### 3.1.1 记号

| 记号 | 定义 | 口径（核验数字） | 文件 |
|---|---|---|---|
| L2 | 国家《义务教育英语课程标准（2022 年版）》附录 3 二级词汇表主表 | 505（INDEX B2） | `data/lists/moe-2022-l2.txt` |
| L3 | 同上三级词汇表主表（含用 * 标出的二级 505） | 1,600（主表解析 1,611 含噪声，verify provinces-1） | `moe-2022-l3.txt` |
| A_num / A_cal / A_geo / A_org / A_cult | 同一附录的「数词表」「月份、星期词汇表」「部分地理名称及相关信息」「部分国家、重要组织机构名称缩写」「部分重要节日名称、中国文化专有名词」 | 58 / 19 / 46 / 7 / 35（本次从转录件 `std2022.txt:3164-3300` 抽出） | `moe-2022-appendix.tsv`（列 `group`） |
| HS3000 | 《普通高中英语课程标准（2017 年版 2020 年修订）》附录 2 主表（含国籍词、月份、数词） | 3,000（解析 2,997；无星 1,525 / ★ 487 / ★★ 985，verify provinces-3） | `moe-hs-2020.tsv`（列 `level`） |
| HS3100 | 《…（2017 年版 2025 年修订）》附录 2 主表 | 3,100（YR7429 提取 3,091 与 PDF 逐词一致，verify shanghai-secondary-9；无星 1,605 / ★ 501 / ★★ 1,000） | `moe-hs-2025.tsv`（列 `level`）；117 个国家附表词另存 `moe-hs-2025-countries.txt`（`member: false`） |
| SH_w / SH_p | 上海市教育考试院《2020 年上海市初中英语课程终结性评价指南》附《词汇表》（`shmeea.edu.cn/download/20190926/07.pdf`，md5 `059df9c0…`）单词部分 / 词组部分 | 1,731 / 331（INDEX 矛盾 1、verify shanghai-secondary-7） | `shmeea-2020-words.txt` / `shmeea-2020-phrases.txt` |
| V(X) | X 中每个词头的官方括注给出的变体与等价形式（`AmE`、`=`、同义），不含 `pl.` 与 be/have 的屈折 | L2 15 个词头 / L3 39 / HS3100 56；可建行的变体 57 个 | 各 list 文件的第 2 列 `variants` |
| E_cet4 / E_cet6 | ECDICT 1.0.28 release `stardict.db` 中 tag 含 `cet4` / `cet6` 的词 | 3,849 / 5,407（本次对 851 MB release 库实测，与 csv 完全相同；tag 全集只有 8 值 gre/toefl/cet6/ielts/ky/cet4/gk/zk——补上 INDEX 未解决 6） | `--db` |
| C4 / C6 / C46 | mahavivo `CET4_edited.txt` / `CET6_edited.txt` / `CET_4+6_edited.txt` 词头 | 4,539 / 2,220 / 8,008（`stats.json`） | `WORDLISTS_DIR`（仓库外，不变） |

#### 3.1.2 成员定义（最终）

```
xs   = L2 ∪ V(L2) ∪ A_num ∪ A_cal
zk   = L3 ∪ V(L3) ∪ A_num ∪ A_cal ∪ A_geo ∪ A_org ∪ A_cult ∪ SH_w            # SH_p 见 §3.3.7，本轮 member: false
gk   = HS3100 ∪ V(HS3100) ∪ HS3000                                            # 2025 国家附表 117 词不入
cet4 = E_cet4 ∪ C4 ∪ (C46 ∩ C4)                                               # 原样（build_seed.py:113-142）
cet6 = E_cet6 ∪ C6 ∪ (C46 \ C4)                                               # 原样
cet6_star 原样（英语六级词汇（星标，1726）.txt）
种子词集 = xs ∪ zk ∪ gk ∪ cet4 ∪ cet6 ∪ R                                     # R = 旧种子中不再属于任何集合的词，stages: []
```

实测（`final.py`）：|xs| = 594、|zk| = 2,194、|gk| = 3,253、|cet4| = 4,722、|cet6| = 7,671、|R| = 243、总 ≈ 9,274 条。

#### 3.1.3 单调性

- **国家侧自带累计**：L2 ⊂ L3 由课标说明 1「含二级词汇 505 个」保证；L3 ⊂ HS3100 由高中课标说明 1「含义务教育阶段 1600 个」保证。实测 `XS ⊆ ZK` 为真；`L3 \ HS3100(主表)` 只有 `practice`（高中表写 `practise (practice)`，被括注吸收）与 `yogurt/yoghurt` 一类拼写差，经变体继承后为空。所以**不需要**在构建时做 `gk := gk ∪ zk ∪ xs` 的闭包：闭包会把「高中 3100」的官方计数改成 3,100 + 198，并让 `/api/stages` 的 `total` 失去与官方文件的对应。
- **非单调残留只来自上海表**：`zk \ gk` = 198 = 131 个上海独有词（`angrily, beautifully, carefully, dancer, dishonest, luckily, politely, quietly, seafood, bund, hot dog, cafe, e-mail, pineapple, waiter, waitress, supper…`——多为国家表按说明 10「可由构词法推导」而不列的派生副词/口语词）+ 67 个附录项（序数词 `eightieth`、`the great wall`、`cpc`…不在高中主表）。保留为 `zk=1, gk=0`。对用户的影响由**阶段预设**而不是数据闭包解决：高中生预设沿用今天的 `['zk','gk']`（`WelcomePage.tsx:35`），初中生预设改为 `['xs','zk']`（阶段模型/前端线）。
- **stage_min**：`seed.py:208` 的 `(STAGES.index(stages[0]) + 1)` 不改公式，只改 `STAGES`（§4）。在「重编号 1..5」的假设下得到 xs=1 … cet6=5；如阶段模型线最终选「字符串码」或「xs=0」，构建端只需改这一行为查表，其余不受影响。
- **一个词在多个官方表里**：`stages` 取并集（排序按 `STAGES`），`sources` 记录**每一张**命中的表 id（排序去重）。例：`colour` → `stages ["xs","zk","gk","cet6"]`，`sources "cet46 ecdict ecdict-cet6 hs20 hs25 moe22-l2 moe22-l3 shmeea20"`；变体 `color` → 同样的 stages，`sources` 同上，另带 `variant_of: "colour"`。

#### 3.1.4 对阶段模型线的接口要求（本线不实现）

1. `words.stage_xs INTEGER NOT NULL DEFAULT 0 CHECK (stage_xs IN (0,1))`，`stage_min CHECK BETWEEN 1 AND 5`，`user_settings.current_stage CHECK 1..5`（整表重建，先 `DROP VIEW v_bank`，verify stage-model-13）。
2. 0011 在重建 `words` 的 `INSERT … SELECT` 里把 `stage_min` 整体 +1、`user_settings.current_stage` +1：虽然随后的 `import-seed` 会用绝对值覆盖全部 9,162 行，但若导入在迁移之后失败（种子文件损坏、`main.seed_check` 对坏 gzip 无防御——WORD_LIBRARY_CURATION §1.2），库仍要在新编号下自洽。
3. `seed.py:43 STAGES`、`services/words.py:39 STAGES`、`services/ecdict.py:28 STAGE_TAGS`、`ai/prewarm.py:32-33`、`ai/content.py:49 STAGE_ZH`、`schemas.py:25-26,51-52,56-67,488,708,1335` 同一提交扩展；`services/words.py:576-580 _word_defaults` 与 `:589-597 _INSERT_WORD_SQL`、`services/ecdict.py:173-177 word_columns` 必须输出 `stage_xs`，否则导入/自添词 INSERT 缺参数。
4. **与本设计直接相关的一条**：`services/ecdict.py:28 STAGE_TAGS` 在运行时给用户自添词按 ECDICT 标签赋 `stage_zk/gk`（`:118-119`、`:173-177`）。成员既然不再由 ECDICT zk/gk 决定，这里要改成只认 `cet4/cet6`（`STAGE_TAGS = ("cet4", "cet6")`，`stage_min` 公式改查表），否则自添词会得到种子里已经废除的初中/高中标记。

### 3.2 官方词表文件如何进仓库

#### 3.2.1 目录与文件

```
data/lists/
  README.md                      # provenance 表 + 许可说明 + 文件格式（本节）
  manifest.json                  # 声明式清单（§3.2.3）
  moe-2022-l2.txt                # 505 行（+ 第 2 列 variants）
  moe-2022-l3.txt                # 1600 行（+ variants；不重复标 * ——L2 已是独立文件）
  moe-2022-appendix.tsv          # word<TAB>group(number|calendar|geo|org|culture)  ≈165 行
  moe-hs-2020.tsv                # word<TAB>level(0|1|2)  3000 行（主表，含国籍/月份/数词）
  moe-hs-2025.tsv                # word<TAB>level(0|1|2)<TAB>variants  3100 行
  moe-hs-2025-countries.txt      # 117 行，manifest 里 member: false（只存档）
  shmeea-2020-words.txt          # 1731 行（a/an 不在原件文本里，见 §3.3.2）
  shmeea-2020-phrases.txt        # 331 行，manifest 里 member: false（§3.3.7）
  aliases.tsv                    # official<TAB>canonical<TAB>kind<TAB>note
  overrides.jsonl                # 手写字段覆盖（≤ 10 条）
```

**与另一条流水线实际产出的对照**（2026-11-06 00:00 `data/lists/` 已出现以下文件，本文只看了文件名、未读内容）：`moe-2022-level2.txt` ≙ 本文 `moe-2022-l2.txt`、`moe-2022-level3.txt` ≙ `moe-2022-l3.txt`、`moe-2022-appendix.tsv` 同名、`moe-2020-senior.tsv` ≙ `moe-hs-2020.tsv`、`moe-2025rev-senior.tsv` ≙ `moe-hs-2025.tsv`、`moe-2025rev-senior-appendix.tsv`/`moe-2020-senior-appendix.tsv` ≙ `moe-hs-2025-countries.txt`（高中国家附表，`member: false`）、`shmeea-2020-junior.txt` ≙ `shmeea-2020-words.txt`、`shmeea-2020-junior-phrases.txt` ≙ `shmeea-2020-phrases.txt`、`shmeea-2020-junior-appendix.tsv`（上海附表：代词/数词/国家/学科，按 §3.3.6 的 `group` 规则并入 `moe22-app` 同类处理）、`shmeea-2020-junior-forms.tsv`（上海表括号内的不规则形式，`member: false`，只用于核对 `word_forms`）、两份 `*.README.md` 与 `moe-senior-2020-vs-2025.diff.txt`（provenance，合并进本文 §3.2.2 的表）。**`manifest.json` 以实际文件名为准，list id（`moe22-l2 / moe22-l3 / moe22-app / hs20 / hs25 / shmeea20 / shmeea20-phr`）不变**；若实际文件的列与本文不同（例如 variants 不在第 2 列），改 manifest 的 `columns`，不改构建代码。

**行格式**：UTF-8、LF、一行一个词头；`#` 开头为注释；**不保留**官方件里的字母节标题（A、B、…）——它们与词头 `I`、`a` 同形，YR7429 的提取里 `I` 就被当作节标题丢过（本次解析实测）；字段用 `\t` 分隔；第 1 列是**官方印刷的词头原文**（含大小写、句点、撇号；`a/an` 一类并列拆成两行并在注释里说明）；可选列按文件声明（`variants`：逗号分隔；`level`：0/1/2；`group`）。**不**在列表文件里做任何库内归一化（那是 `aliases.tsv` 和 `build_seed.py` 的事），这样文件可以对着官方件逐行核对。

**头部注释**（机器可读的 `# key: value`，`build_seed.py` 读取并写进 `stats.json.lists[]`）：

```
# list: moe22-l2
# title: 义务教育英语课程标准（2022年版）附录3 二级词汇表
# source-url: http://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220420582349487953.pdf
# source-md5: <由产出流水线填写>
# source-pages: PDF 94-104（印刷页 87-97）
# retrieved: 2026-11-05
# transcription: forum.freemdict.com uN5QN0pLEw6DThoKWkA9y6ApLem.docx（非官方），抽样 234 词与官方扫描件一致（verify shanghai-primary-21）
# parse: 两栏表格按 \t 拆列；去 26 个字母节标题；括注按 §3.3 规则拆为 variants 列；pl./be/have 的屈折不入；a/ an 拆两行
# count: 505
```

#### 3.2.2 `README.md` 的 provenance 表

| id | 文件 | 来源 | URL | md5 | 获取日期 | 解析规则 | 计数 |
|---|---|---|---|---|---|---|---|
| moe22-l2 | moe-2022-l2.txt | 教育部教材〔2022〕2 号附件 6 | …W020220420582349487953.pdf | 待填 | 2026-11-05 | 扫描件无文字层；用社区转录件对账 + 抽样 OCR 核对（verify shanghai-primary-21、list-sources 遗漏 1） | 505 |
| moe22-l3 | moe-2022-l3.txt | 同上 | 同上 | | | 同上；主表到「数词表」止 | 1600 |
| moe22-app | moe-2022-appendix.tsv | 同上 | 同上 | | | 转录件 3164-3300 行五张附表；多词项保留（`The Great Wall`） | 165 |
| hs20 | moe-hs-2020.tsv | 教育部教材〔2020〕3 号附件 zip 内 `4.普通高中英语课程标准（2017年版2020年修订）.pdf` | …W020200603315372317586.zip | | | 文本 PDF；附录 2 主表到「主要国家名称…」止；`*` 计星 | 3000 |
| hs25 | moe-hs-2025.tsv | 《普通高中英语课程标准 日常修订版（2017 年版 2025 年修订）》 | forum.freemdict.com 镜像 PDF（非官方；印发文号未找到，INDEX 未解决 1） | | | 与 YR7429/english-vocab-cn 提取逐词比对一致 | 3100 |
| hs25-countries | moe-hs-2025-countries.txt | 同上附录末「主要国家名称」 | | | | 不入成员 | 117 |
| shmeea20 | shmeea-2020-words.txt | 上海市教育考试院 2019-09-26 发布页 `07.pdf` | https://www.shmeea.edu.cn/download/20190926/07.pdf | 059df9c02684bd989fff6f8849ee1993 | 2026-11-05 | `pdftotext -layout`；每页首词前有 `\f`（verify provinces-12）；`x/y`、`x=y` 并列拆行；括号内不规则形式丢弃 | 1731 |
| shmeea20-phr | shmeea-2020-phrases.txt | 同上「词组」段 | 同上 | 同上 | | 2196–2568 行；`sb./sth./…` 省略句式原样保留，由 manifest 决定是否入库 | 331 |

#### 3.2.3 `manifest.json`

```json
{
  "format": 2,
  "lists": [
    {"id": "moe22-l2",  "file": "moe-2022-l2.txt",  "mode": "official", "stages": ["xs"], "columns": ["word", "variants"], "member": true},
    {"id": "moe22-l3",  "file": "moe-2022-l3.txt",  "mode": "official", "stages": ["zk"], "columns": ["word", "variants"], "member": true},
    {"id": "moe22-app", "file": "moe-2022-appendix.tsv", "mode": "official", "columns": ["word", "group"],
     "stages_by_group": {"number": ["xs", "zk"], "calendar": ["xs", "zk"], "geo": ["zk"], "org": ["zk"], "culture": ["zk"]}, "member": true},
    {"id": "hs20",      "file": "moe-hs-2020.tsv",  "mode": "official", "stages": ["gk"], "columns": ["word", "level"], "member": true},
    {"id": "hs25",      "file": "moe-hs-2025.tsv",  "mode": "official", "stages": ["gk"], "columns": ["word", "level", "variants"], "member": true, "level_field": "hs_level"},
    {"id": "hs25-countries", "file": "moe-hs-2025-countries.txt", "mode": "official", "stages": [], "member": false},
    {"id": "shmeea20",  "file": "shmeea-2020-words.txt", "mode": "official", "stages": ["zk"], "member": true},
    {"id": "shmeea20-phr", "file": "shmeea-2020-phrases.txt", "mode": "official", "stages": ["zk"], "member": false, "kind": "phrase"},
    {"id": "cet4",   "external": true, "file": "CET4_edited.txt",  "mode": "rich",  "stages": ["cet4"]},
    {"id": "cet6",   "external": true, "file": "CET6_edited.txt",  "mode": "rich",  "stages": ["cet6"]},
    {"id": "cet46",  "external": true, "file": "CET_4+6_edited.txt", "mode": "plain", "stages": ["cet4|cet6"], "split_by": "cet4"},
    {"id": "cet6star", "external": true, "file": "英语六级词汇（星标，1726）.txt", "mode": "plain", "flag": "cet6_star"}
  ],
  "ecdict_tags": {"cet4": ["cet4"], "cet6": ["cet6"]},
  "aliases": "aliases.tsv",
  "overrides": "overrides.jsonl",
  "stage_order": ["xs", "zk", "gk", "cet4", "cet6"],
  "missing_policy": {"official": "error", "external": "warn"}
}
```

语义：`mode: official` = 本节格式；`rich/plain` = 现 `build_seed.parse_list` 的两种 mahavivo 格式（修正后，§3.4）；`member: false` = 解析、校验、计数、写入 `stats.json.lists[]`，但不产生 `stages`（词若因其他表入库，`sources` 仍记这个 id）；`missing_policy.official: error` = 官方词头在 ECDICT 查不到又没有 `overrides` 时构建失败并列出，不再像今天那样静默进 `missing_from_ecdict`。

#### 3.2.4 许可说明（写进 `data/lists/README.md` 与根 `ATTRIBUTION.md` §2）

- 教育部课标与上海市教育考试院词汇表是政府/事业单位发布的考试文件，未声明许可；《著作权法》第五条（一）是否适用未核实（INDEX C4、verify list-sources 遗漏 4）。本仓库**只收录词头清单**（事实性数据，独创性极低），不复制任何说明文字、释义、词性、星标以外的编排；释义/音标/词频一律来自 MIT 许可的 ECDICT（现有姿态，`data/seed/ATTRIBUTION.md:12-13`）。高中表的 ★ 级别是官方「必修/选择性必修」归类，属于词表本身的事实信息，收录并在 README 注明出处。
- 2025 修订版高中表的机读件来自非官方镜像与 YR7429（内容 CC BY-SA 4.0；本仓库只用词头，不受 SA 约束，但 README 致谢）。
- mahavivo CET 三表继续按现有说法处理（根 `ATTRIBUTION.md` §2：只用「词头出现在某表」这一事实，不再分发列表文件），表格缩减到 CET 三行；`data/seed/ATTRIBUTION.md` 改为由 `manifest.json` 生成（现在是 `build_seed.py:201-219` 的常量）。
- `data/licenses/` 不新增文件（官方件没有许可文本可放）；`ATTRIBUTION.md:14` 的「9,162 records」与 `frontend/src/i18n/zh.ts:86` 的「词表范围：中考、高考、大学英语四级与六级大纲」改为「小学/初中/高中依据国家课程标准与上海市教育考试院词汇表，四六级依据…」（`docs/FRONTEND.md §8` 镜像，`check-copy.mjs` 与 `zh.test.ts` 门禁）。

#### 3.2.5 Makefile

`make seed ECDICT_DB=<stardict.db> WORDLISTS_DIR=<mahavivo dir>` 保留；新增 `LISTS_DIR ?= data/lists`、`PREV_SEED ?= data/seed/vocab.jsonl.gz`：

```
$(PYTHON) -I scripts/build_seed.py --db "$(ECDICT_DB)" --manifest "$(LISTS_DIR)/manifest.json" \
    --external-dir "$(WORDLISTS_DIR)" --previous "$(PREV_SEED)" --out data/seed
$(PYTHON) -I scripts/seed_diff.py "$(PREV_SEED)" data/seed/vocab.jsonl --out data/seed/DIFF.md
scripts/pack_seed.sh
```

`WORDLISTS_DIR` 仍指 mahavivo 目录，但只读 CET 三表 + 星标表；`Makefile:95` 的提示文字改为「holding the mahavivo CET lists」。`ECDICT_DB` 必须是 **release 1.0.28 的 `stardict.db`**（本机已有校验过的副本 `scratchpad/ecdict-dl/extract/stardict.db`，851,288,064 B）：基础版 csv 缺 8 个种子词且 `pos` 全空（seed-pipeline-27），不能用。

### 3.3 规范化规则（逐条，含对现库的影响）

规则在 `build_seed.py` 的 `canon()`（词头 → 库内 lemma 候选）与 `members_of()`（词头 → 成员集合）两步实现；`seed.py:180-181` 的 `normalise_input/normalise_lemma` 不改。

| # | 现象 | 规则 | 例子 | 对现库的影响（实测） |
|---|---|---|---|---|
| 1 | **英式/美式变体**：课标英式为主、美式括注（说明 2） | 第 1 列是英式词头；括注的 `AmE x` 进 `variants` 列；构建时变体若在 ECDICT 中有条目，就产出**自己的记录**，`stages` 与词头相同、`sources` 相同、加 `variant_of: <词头>`。不合并行、不建 `word_forms`（表头词守卫会拒绝，`seed.py:239-241`） | `colour\tcolor`、`favourite\tfavorite`、`maths\tmath,mathematics`、`mother\tmum,mom`、`centre\tcenter`、`programme\tprogram`、`organise\torganize`、`towards\ttoward`、`per cent\tpercent` | 57 个变体/等价形式可建行（54 个现有行 + 3 个新行 `artificial intelligence, common era, physical education`）并获得与词头相同的阶段（`color/favorite/math/mum` 从 `stage_min=2` 升到 xs；`realize/recognize/organize/program/theater…` 进 zk 或 gk）。`mum` 的 ECDICT 义项是「菊花, 沉默」→ 需 `overrides`（§3.3.9） |
| 2 | **并列条目**：`a/an`、`although/though`（上海）、`bike (= bicycle)`、`exam=examination`、`grandma=grandmother`、`toward(s)`、`manner(s)`、`more(much或many的比较级)` | `x/y`、`x=y`、`x (= y)` → 两个词头都是成员（产出流水线把 `/`、`=` 拆成两行；括注里的 `= y` 进 `variants`）；`x(s)` → `x` 与 `xs` 两行（`toward/towards` 都是独立词）；`manner(s)` → 只 `manner`（`manners` 是复数，在 `exchange s`）；`more(…比较级)` → `more`；`be (am, is, are)`、`have (has)`、`child (pl. children)` 的括注**不**产生成员 | `although`/`though` 均 zk；`bicycle`、`examination`、`television`、`photograph`、`refrigerator`、`gymnasium`、`laboratory`、`kilogram`、`advertisement`、`application`、`artificial intelligence` 成为成员 | 上海原件文本没有 `a`/`an` 行（verify shanghai-secondary O6），它们由 L2/L3 覆盖；`an` 今天 `stage_zk=0, stage_min=2`（verify shanghai-secondary O8）→ xs。`is/are/am/does/has/children/feet/men/women` 不是成员：`is`（现 zk+gk）与 `are`（现 gk）、`does` 变成无阶段词典行（§3.7），`children/feet/men/women` 本来就只在 `word_forms`（seed-pipeline-13） |
| 3 | **句点缩写** | 库内规范形 = ECDICT 带 zk/gk 释义的那个条目：`Mr.`、`Mrs.`、`Ms.`、`P.E.`、`a.m.`、`p.m.`、`U.S.A.`；官方的 `Mr`/`PE`/`a. m.` 通过 `aliases.tsv` 改写（`kind: dot`） | `Mr→Mr.`、`Mrs→Mrs.`、`Ms→Ms.`、`PE→P.E.`、`a. m.→a.m.`、`A.M.`（高中表）→`a.m.` | 不新建行；`mr./mrs./ms./p.e.` 四行获得 xs。它们今天 `kind='abbreviation'`（seed-pipeline-31）。注意 ECDICT 的无点 `Mr`（「先生 \| [计] 存储器回收程序」）与 `PE`（「[计] 相位编码」）是错义项，所以必须别名到带点形式而不是反过来（本次 `probe_ecdict.py` 实测） |
| 4 | **屈折形式作词头** | 官方把 `excited, embarrassed, frightened, frightening, frozen, lost, satisfied, satisfying, stuck, surprised, underlined, united, confused, endangered, dining`（上海 12 + 高中 3）列为词头，ECDICT 对它们有独立形容词条目（`excited a. 兴奋的 frq 3426`）→ **建自己的行**，`kind='word'`。重建 `word_forms` 时表头词守卫使 `excited→excite(p)` 一类映射消失（`seed.py:239-241`），`excite` 的 `exchange_json` 不变。`policemen/children/feet` 等纯复数不是词头（产出流水线按 `pl.` 丢弃） | 16 个新行（§3.6.3 新词表里的屈折类）。搜索 `excited` 从「经 word_forms 命中 excite」变成直接命中新行；`/api/lookup` 的 `via` 从 `form` 变 `exact`（无契约变化） |
| 5 | **派生副词** | 国家表按说明 10 不列可推导派生词；上海表列了 `angrily, beautifully, carefully, luckily, politely, quietly…` → 作上海成员建行（ECDICT 有条目）。不做自动派生 | 上海独有 131 词的主要成分；它们 `zk=1, gk=0` |
| 6 | **数词/月份/星期/专有名词** | 附录按 `group` 分配：`number`、`calendar` → xs+zk；`geo`（Africa/African…The Pacific Ocean）、`org`（CPC, PLA, PRC, UN, UNESCO, WHO, WTO）、`culture`（Beijing opera, Spring Festival, The Great Wall, hot pot, qipao…）→ zk。2025 高中国家附表 117 词不入。HS3000 主表里的国籍词（`african, american, british…`）经并集进 gk | 地理 46/46、机构 7/7 在 ECDICT 或现库中有条目；文化 32/35——`Mount Huangshan`、`Mount Taishan`、`PLA Day` 需 `overrides`；`the pacific ocean`（现库 phrase，zk）保留；多词专名 `kind='phrase'`（`derive_kind` 规则，`services/words.py:143-151`） |
| 7 | **上海 331 个词组** | 本轮 `member: false`：文件进仓库、计数、校验，**不**入阶段。理由：国家表不列词组（说明 8），入 zk 会让「初中」计数混入 331 个非单词；ECDICT 覆盖 280/309（29 个含 `sb./sth./…` 的句式模板无条目），且 280 个里只有 2 个有 `frq`，在按频率排序的筛词/推荐里全部排在末尾；现库 13 个 phrase 的学习卡/配图流程未对词组做过验证。第二版种子再以 `kind='phrase'`、`stages ["zk"]`、`sources shmeea20-phr` 入库，`sb./sth.` 模板先归一（`agree with sb.` → `agree with`）或跳过 | 现库只命中 3 个（`according to` 及两个解析噪声）；无影响 |
| 8 | **大小写与 lemma 唯一键** | lemma 全小写（`ux_words_lemma`，`0001_init.sql:205`）；`May`（月份）与 `may`（情态）共用 ECDICT 条目 `may`（「n. 五月 \| aux.」）→ 一行；`I` 的 ECDICT 词头是 `I`，`derive_kind` 判 proper_noun（已知副作用，seed-pipeline-31）不改。**display 以 ECDICT 词头大小写为准**（`China`, `TV`, `a.m.`），列表文件的大小写只用于 ECDICT 查不到的覆盖词 | `may` 加 xs（月份附录）后 display 仍为 `may`；`AI`/`APP` 的 ECDICT 词头是大写（「[计] 附加信息, 人工智能」「[计] 应用」）→ display `AI`/`APP`、kind abbreviation；官方印作 `AI`/`app`，差异可接受（或用 overrides 把 `app` 的 display 改小写） |
| 9 | **弯引号/重音符/连字符** | `canon()`：NFKC → `’‘`→`'` → 小写 → 压空白；`café→cafe`、`hot-dog→hot dog`（ECDICT `hot dog` = 热狗；`hot-dog` 是冲浪术语、`hotdog` 是「v. 卖弄」）、`e-mail`↔`email`、`ice-cream`↔`ice cream`、`ping-pong`/`pingpong`/`ping pong` 按 `aliases.tsv` 的 `kind: hyphen` 成对继承 | `o'clock` 现库已有（verify provinces-24）；`cafe` 从 `stage_min=3` 升 zk；`hotdog`（现 zk，靠 ECDICT zk 标签）变无阶段；`ice cream`（phrase, zk）与 `ice-cream`（word, zk gk cet4）都保留并都拿到 xs |
| 10 | **ECDICT 无条目或错义项的官方词** | `overrides.jsonl` 一行一词：`{"word": "Bund", "translation": ["n. 外滩（上海黄浦江西岸）"], "kind": "proper_noun", "phonetic": "bʌnd"}`；构建时先查 ECDICT，再用 override 覆盖给定字段；完全不在 ECDICT 的词只有 override 字段（`phonetic ""`、`definition []`、`frq null`，`seed.py` 允许，seed-pipeline-9）。初始清单：`bund`（ECDICT 义项「政治同盟」）、`mum`（「菊花」）、`bce/ce/common era`（「化学工程学士」「组件选通」）、`physical education`（「[医] 体育」）、`Mount Huangshan`、`Mount Taishan`、`PLA Day`（无条目） | 新词 112 个全部在 ECDICT release 中（`final.py` 实测），只有上述 ≤10 个需要人工释义 |

`aliases.tsv` 初稿（official → canonical → kind → note）：`Mr→Mr.→dot`、`Mrs→Mrs.→dot`、`Ms→Ms.→dot`、`PE→P.E.→dot`、`A.M./a. m.→a.m.→dot`、`P.M./p. m.→p.m.→dot`、`café→cafe→accent`、`o’clock→o'clock→quote`、`hot-dog→hot dog→hyphen`、`e-mail↔email→hyphen-pair`、`ice-cream↔ice cream→hyphen-pair`、`The United States of America→the united states of america→case`。`kind=dot/accent/quote/case` 是**改写**（不产生第二行），`hyphen-pair` 是**成对继承**（两行都存在时互相继承阶段）。

### 3.4 `build_seed.py` 的重构

保留单文件与 CLI（`Makefile:96` 调用方式兼容），内部拆成可测的函数；`scripts/seed_diff.py` 新文件。

1. **解析层**
   - `parse_official(path, columns)`：读头部 `# key: value`、按 `\t` 取列、`variants` 逗号拆分；校验 `# count` 与行数一致（不一致 → exit 2）。
   - `parse_list(path, mode)` 保留给 CET 表，修三处缺陷：`RICH_RE`（`:16`）前加一步预归一化 `line = line.replace("（", "(").replace("）", ")").replace("=", " = ")`，并把正则的词头部分放宽为 `([A-Za-z][A-Za-z'\-\.]*(?: [A-Za-z][A-Za-z'\-\.]*){0,3})`（已是）后允许 `（`/`(`/`=`/`[`/`/`/空白/行尾任一终止（现在缺左括号 `practice(s)e` 与 `silentˈsailənt]` 这类仍会丢，接受，因为 CET 表没有这类行，中考表已退出）；`a (an)` → 产出 `a` 与 `an`（括注只含字母且无空格时视为并列）；`len(line) == 1` 的跳过（`:25`）改为 `line.isupper() and len(line) == 1`（节标题），小写单字母 `a`/`i` 保留。
   - `canon(word)`：§3.3.9 的归一化 + `aliases.tsv` 改写。
2. **成员层**：`members_of(list, row)` 返回 `{(lemma_candidate, is_variant)}`；`stages_for(list, row)` 按 manifest（`stages` / `stages_by_group` / `cet46 split_by`）。
3. **词典层**：`lookup(w)` 原样（`:96-100`，精确 + 空格→连字符），**去掉**步骤 1「把 ECDICT 全部带 zk/gk/cet4/cet6 标签的行先收进来」（`:102-109`）中的 zk/gk：改为只收 `cet4/cet6` 标签行（`manifest.ecdict_tags`）；步骤 2 逐表并入成员；步骤 3 `--previous` 旧种子：旧 lemma 若不在新词集 → 以 ECDICT 当前条目重建记录（保证字段与其他词一致），`stages: []`，`sources` = 旧 `sources` 中的 `zk/gk` 映射为 `legacy-zk/legacy-gk` + `ecdict`；旧 lemma 在新词集中 → 只追加 `legacy-*` 标记。
4. **记录层** `make_record`：15 个字段不变；`stages` 过滤元组改从 manifest `stage_order` 读；新增 `variant_of`（变体行）、`hs_level`（hs25 的 `level`；HS3000-only 的词为 `null`）；`sources` = 排序去重的 id 列表；`ecdict_id` 原样；override 字段最后覆盖。
5. **输出层**：`vocab.jsonl` 按 `(min stage rank, lemma)` 排序（`:150-151`），无阶段词排最后、按 lemma；`json.dumps(ensure_ascii=False)`，键顺序固定；`stats.json` 结构见下；`ATTRIBUTION.md` 从 manifest 渲染；构建结束打印每张表的 `missing`，官方表非空即 exit 2。
6. **`stats.json`**（v2）：

```json
{"format": 2, "total_words": 9274, "stageless": 243,
 "per_stage": {"xs": 594, "zk": 2194, "gk": 3253, "cet4": 4722, "cet6": 7671},
 "first_stage": {"xs": 594, "zk": 1600, "gk": 1257, "cet4": 1726, "cet6": 3854},
 "only_stage": {...}, "flag_combos": {"00001": 3854, "00011": 1636, ...},
 "per_source": {"moe22-l2": 505, "moe22-l3": 1600, "moe22-app": 165, "shmeea20": 1731, "hs20": 2997, "hs25": 3100, "ecdict-cet4": 3849, "ecdict-cet6": 5407, "cet4": 4539, "cet6": 2220, "cet46": 8008, "legacy-zk": 1887, "legacy-gk": 3446},
 "lists": [{"id": "moe22-l2", "file": "...", "sha256": "...", "count": 505, "members": 505, "variants": 17, "missing": []}, ...],
 "variants": 57, "overrides": 8, "aliases_applied": 12,
 "vs_previous": {"previous_sha256": "a68127…", "new_words": 112, "retired": 243, "rows_updated": 9162, "stage_set_changed": 2603, "stage_min_changed": 2562},
 "with_phonetic": ..., "with_translation": ..., "with_definition": ..., "with_exchange": ..., "multiword": ..., "uppercase": ..., "file_bytes": ...}
```
   `pack_seed.sh:44-47` 只读 `total_words`，不受影响。
7. **`scripts/seed_diff.py old.jsonl[.gz] new.jsonl[.gz] --out DIFF.md`**：按 lemma 对齐；输出 (a) 每阶段 增/减 计数与 20 个样例，(b) `stage_min` 转移矩阵（旧 1..4 → 新 1..5/∅），(c) 新增词全表（按 stages 分组），(d) 消失/无阶段词全表（按旧旗标分组），(e) `sources` 变化统计，(f) **不变量检查**：`新 lemma 集 ⊇ 旧 lemma 集`（除非 `data/lists/retired-allowlist.txt` 列出），`xs ⊆ zk`，`per_stage` 与 `stats.json` 一致——任一失败 exit 1。`make seed` 把它接在构建之后，`DIFF.md` 进仓库供评审。
8. **确定性与打包**：同一 manifest + 同一 `stardict.db` + 同一 CET 表 → 字节相同的 `vocab.jsonl`（输入都有 sha256 写进 stats）。`pack_seed.sh` 保留 `gzip -9 -n`，但把 BSD 不兼容的 `zcat`（`:62,68,79,90`）→ `gzip -dc`、`sha256sum` → `shasum -a 256`、`stat -c %s` → `wc -c <`（seed-pipeline-8）。跨 gzip 实现字节不同的问题（seed-pipeline-7）**不在构建端解决**：推荐（可选，P2）把 `kv.seed_version` 改为**解压后内容**的 sha256（`seed.py:258 sha256_file(p)` → `content_sha256(p)`，`main.py:313` 同步），这样 Mac 重打包不会触发伪重导；代价是 `test_seed.py:229-238`（gz 与 plain 「内容相同但文件不同 → 不算 up to date」）的语义反转，需改测试。本轮不做也可以：伪重导是 `0 inserted, 0 updated` 外加一条 `system_events`，无害（seed-pipeline-7）。

### 3.5 `seed.py` 的导入语义

- **保持**：按 lemma 的 UPSERT、覆盖全部种子列、从不删行、不碰内容/配图/用户表（`seed.py:1-20` docstring 的承诺）。这正是重标阶段所需要的：旧行的 `stage_*`/`stage_min`/`sources` 会被新种子整体改写（stage-model-19 已证）。
- **预期规模**：对线上 9,162 行，新种子会「更新」全部 9,162 行（`sources` 从 `cet4 cet46 ecdict gk zk` 这类旧词汇全部改写），其中 2,603 行阶段集合变化、2,562 行最低阶段变化、6,559 行只有 `sources` 变；`updated_at` 因此对全库刷新一次（`seed.py:77`），`/media/card/{id}.svg` 的 LRU 键含 `updated_at`（WORD_LIBRARY_CURATION §1.6）→ 卡片缓存全部失效一次，无害。
- **改**：`STAGES`（`:43`）→ `("xs","zk","gk","cet4","cet6")`；`SEED_COLUMNS`（`:47-68`）加 `stage_xs`（紧跟 `exchange_json` 之后，顺序与 DDL 一致）；`seed_row`（`:204-208`）加 `"stage_xs": int("xs" in stages)`；docstring（`:6-7`）改「五个阶段旗标」。未知键 `variant_of`/`hs_level` 被 `seed_row` 自然忽略（它只 `rec.get` 已知键），不需要改。
- **新增 `--dry-run`**（`cmd_import_seed`/`import_seed(conn, path, dry_run=True)`）：解析文件、`SELECT lemma, <SEED_COLUMNS> FROM words` 一次取回、按 `SEED_COLUMNS` 逐列比较（`None`/`''` 归一化与 `_text/_lines/_int` 一致），输出：`would insert N / update M / unchanged U`，按阶段的 `+a/−b`，`stage_min` 变化数，`stageless` 记录数，前 30 条 `lemma: old_stages → new_stages`；不开事务、不写 `kv`。`--report PATH` 把同样内容写成 JSON。这是 §5.3 排练与 §6 上线前的检查点。
- **统计补充**：`SeedStats` 加 `stageless_records`（`stages == []` 的记录数）并在 `format_stats` 打印；`system_events.seed_imported.detail_json` 加 `stageless` 与 `stage_changes`。
- **不做**「删除/下架不再在种子中的词」：导入器没有删除路径，也不该有——用户收藏、复习日志、配图都挂在 `words.id` 上（9 条外键，verify stage-model-12）。也**不做**「保留旧阶段」：那会把 mahavivo 的旧考纲口径永久冻结在库里。消失的词由构建端处理成无阶段词典词（§3.7）。
- **kv**：`seed_version` 语义不变（可选项见 §3.4.8）；新增 `kv.seed_format = '2'` 与 `kv.seed_stats = <stats.json 的 per_stage/first_stage/stageless 子集>`（管理页「词库版本」可以显示阶段计数，不再只有哈希）。
- **`WD_SEED_PATH` 陷阱**不变（seed-pipeline-14）：新种子必须替换 `data/seed/vocab.jsonl.gz` 本身。

### 3.6 新旧差异量化（live-copy.db × 核验解析件；`final.py`）

#### 3.6.1 各集合的构成

| 集合 | 大小 | 构成 |
|---|---|---|
| xs | 594 | L2 主表 505 + 数词 58 + 月份星期 19 + 括注变体 17（去重后） |
| zk 国家侧 | 1,799 | L3 1,600 + 变体 ≈45 + 附录 ≈160（可建行者） |
| zk 上海侧 | 1,731 | SH_w |
| zk | 2,194 | 国家侧 ∩ 上海侧 1,336；国家侧独有 463（其中 288 个本来就是现 zk）；上海独有 395（其中 154 个本来就是现 zk） |
| gk | 3,253 | HS3100 侧（含变体）3,159 ∩ HS3000 2,997 = 2,903；仅 2025 版 256（`ai, alert, anniversary, app, bias, blog, bully, drone, lifestyle…`）；仅 2020 版 94（月份/星期/数词/国籍词 + `cheek, crayon, foggy, humorous, pupil, swimming, ice-cream, ought…`） |

#### 3.6.2 各阶段的增减

| | 旧 | 新 | 增 | 减 | 减去向 |
|---|---|---|---|---|---|
| zk | 2,099 | 2,194 | 510 = 416 现有行 + 94 新行 | 415 | 188 → 仅高中层（`accent, agreement, beer, beyond, cage, camel, ceiling, chart, cloth, coal, cupboard, curtain, deer, dozen, elevator, frog, goat, golf, harvest…`）、155 → 仅 CET 层（`aircraft, airplane, amaze, bake, broom, cannon, chimney, drum, feather, goose, ladder, melon, minibus…`）、72 → 无阶段 |
| gk | 3,829 | 3,253 | 479 = 449 + 30 | 1,055 | 764 → 仅 CET 层（`abolish, abortion, abrupt, absolute, absurd, abundant, academy, accelerate…`——正是 `Highschool_edited` 的旧「高考 3500」谱系词，shanghai-secondary-16）、213 → 无阶段、78 仍在初中层 |
| xs | 0 | 594 | 578 现有行（旧 `stage_min` 1:569、2:6、3:2、4:1）+ 16 新行（序数词 14、`excited`、`physical education`） | — | 现有行里不是现 zk 的只有 9 个：`an, astronaut, best, chore, color, eleventh, favorite, maths, mum`（与 verify shanghai-primary-21 一致：`best` 靠修 `RICH_RE` 也能救回，`chore` 现在是 cet6） |

#### 3.6.3 `stage_min` 转移矩阵（行 = 旧 1..4，列 = 新 1..5 / 无）

| 旧 \ 新 | 1 xs | 2 zk | 3 gk | 4 cet4 | 5 cet6 | 无 | 行计 |
|---|---|---|---|---|---|---|---|
| 1 (zk) | 569 | 1,115 | 188 | 123 | 32 | 72 | 2,099 |
| 2 (gk) | 6 | 315 | 680 | 398 | 222 | 171 | 1,792 |
| 3 (cet4) | 2 | 68 | 302 | 1,205 | — | — | 1,577 |
| 4 (cet6) | 1 | 24 | 69 | — | 3,600 | — | 3,694 |
| 新行 | 16 | 78 | 18 | — | — | — | 112 |
| **列计** | **594** | **1,600** | **1,257** | **1,726** | **3,854** | **243** | 9,274 |

「仅本阶段新增」（`new_only_total`，`vocab.py:89`）因此从 2,099 / 1,792 / 1,577 / 3,694 变为 594 / 1,600 / 1,257 / 1,726 / 3,854；`API.md:169` 的「3,694-word CET-6 increment」改 3,854，`FRONTEND.md:235`/`VocabPage.tsx:202` 的「仅六级新增（不含四级）」文案逻辑不变。

#### 3.6.4 新增的 112 个词（全部在 ECDICT release 中）

- 屈折/分词形容词与派生副词（上海 + 高中）：`excited, embarrassed, frightened, frightening, frozen, lost, satisfied, satisfying, stuck, surprised, underlined, united, confused, endangered, dining, angrily, beautifully, carefully, luckily, politely, quietly, dancer, dishonest, seafood, unforgettable, yogurt`（26）
- 2025 高中新词：`ai, artificial intelligence, bce, ce, common era, calligraphy, confucius, drone, due to, empathy, entirely, lifestyle, mobile phone, pagoda, teenage, wetland, wi-fi, tofu, curd, kung fu, per cent`（≈21；`app` 现库已有，只是重标）
- 序数词：`thirteenth…ninetieth, hundredth`（13，xs+zk）
- 附录专名（zk）：地理 `new york, new zealand, new zealander, singapore, singaporean, south africa, south african, the atlantic ocean, the indian ocean, the united kingdom, uk`；机构 `cpc, pla, prc, un, unesco, wto`；文化 `beijing opera, peking opera, spring festival, lantern festival, dragon boat festival, mid-autumn festival, the great wall, the palace museum, the silk road, the yellow river, the yangtze river, the changjiang river, tian'anmen square, hot pot, spring roll, paper-cut, qipao, lunar calendar, tcm, traditional chinese medicine, children's day, women's day, teachers' day, labour day, national day, new year's day, tomb-sweeping day, mount qomolangma…`（≈50）
- `bund`、`hot dog`、`physical education`（需 overrides/别名）

#### 3.6.5 消失到无阶段的 243 个词

- 旧旗标：`0100`（仅高中）171、`1100`（初中+高中）42、`1000`（仅初中）30；旧 `sources`：仅 `ecdict`（即只靠 ECDICT zk/gk 标签）101、`ecdict gk` 61、`zk` 26、`ecdict zk` 22、`ecdict gk zk` 17、`gk` 15。
- 类型：word 204、proper_noun 25（`arab, belgium, egypt, greece, iceland, ireland, korea, mexico, moscow, ottawa, scotland, shanghai, switzerland, tibet, tokyo…`）、abbreviation 8（`cd, dept., miss., no., p.c., pc, u.n., u.s.a.`）、phrase 6（`computer game, fruit juice, human being, middle east, olympic games, swimming pool`）。
- 其余多为复合词与低频条目：`bookshop, bookstore, dustbin, flashlight, goldfish, mailbox, motorbike, necktie, postbox, toothbrush, toothpaste, sunglasses, socks, stairs, works, twenty-one…`，以及 be/do 的屈折 `is, are, am, does`。165 个有 ECDICT 词频，78 个没有。
- **0 个被任何用户收藏，0 个有 AI 内容**（`user_words`、`content_state` 实查）。

#### 3.6.6 对现有数据的影响

- `user_words` 77 个 lemma 中 64 个阶段集合变化，几乎全部是「增加阶段」（`actually → +zk +gk`、`career → +gk`、`a/and/be/have/i/in/it/of → +xs`）；学习记录不受阶段影响。
- 有 AI 内容的 49 个词：37 个阶段集合变化、0 个无阶段。提示词里曾用的阶段标签（`content.py:88`）不触发重生成（`PROMPT_VERSION` 不变）。
- ECDICT 标签：1,603 个 zk 标签词 → 1,486 在新 zk；3,677 个 gk 标签词 → 2,682 在新 gk。
- 高中星级（`hs_level`）在 gk 上的分布：0（义务教育 1600 部分）1,605 / ★ 501 / ★★ 1,000 / 无（仅 2020 版与变体）147——为将来的 `difficulty` 尺子或「必修/选择性必修」筛选预留。

### 3.7 「消失 / 降级」的词的处置

| 情形 | 数量 | 处置 | 依据 |
|---|---|---|---|
| 不再属于任何阶段 | 243 | 留在种子里，`stages: []`、`stage_min NULL`、`sources` 保留 `ecdict` 并加 `legacy-zk/legacy-gk`；行不删、`is_public=1` 不变 | 只在「全部」页签与搜索可见（`vocab.py:52-56` 阶段筛选用旗标）；筛词/推荐词的旗标 OR 不会选到它们（`screen.py:52`、`batches.py:233`）；`prewarm all` 的 `stage_min IS NOT NULL`（`prewarm.py:37-38`）跳过它们；`COALESCE(difficulty, stage_min, 5)` 排序把它们当最难（`vocab.py:78`）。与 WORD_LIBRARY_CURATION §1.2 的「种子从不删词」一致 |
| 从初中降到高中 / CET | 188 / 155 | 自然降级，`stage_min` 随之上移；不保留旧旗标 | 保留旧旗标等于保留 mahavivo 口径；需要「拓展层」时从 `sources.legacy-zk` 派生 |
| 从高中降到 CET | 764 | 同上 | 这些就是旧「高考 3500」多出的词（INDEX C2） |
| 用户收藏的降级词 | 0 | — | 实查 |
| 旧种子有、新词集无、ECDICT 也查不到 | 0 | `--previous` 路径用旧记录字段原样回填（防御） | 全部 9,162 旧词都能在 release 库查到（seed-pipeline-27 的 8 个 csv 缺词在 release 里有） |
| 新官方词在 ECDICT 中无条目 | 3（`Mount Huangshan, Mount Taishan, PLA Day`）+ 义项错误 ≤6 | `overrides.jsonl`；无 override → 构建失败 | §3.3.10 |

是否要「拓展/超纲」阶段位（A4）：**本轮不要**。拓展层需要阶段枚举再加一位、前端再加一个 tab，而它的内容（旧考纲多出的 243 + 764 + 155 个词）价值有限；信息已通过 `legacy-*` 与 `stages: []` 保留，Q4-c 可在任何时候从种子派生，不需要重新解析。

---

## 4. 改动清单（文件 → 改什么）

**数据与脚本（本线）**

| 文件 | 改动 |
|---|---|
| `data/lists/`（新建） | §3.2.1 的 11 个文件；词表正文由另一条流水线产出，本线写 `README.md`、`manifest.json`、`aliases.tsv`、`overrides.jsonl` |
| `scripts/build_seed.py` | docstring `:1-12`（来源与阶段码改为五个 + manifest）；`:15-17` 正则按 §3.4.1 修；`parse_list :20-48`（全角括号/`=`预归一化、`a (an)` 产出两个词头、`:25` 只跳大写单字母）；新增 `parse_official`、`canon`、`load_aliases`、`load_overrides`、`members_of`、`stages_for`、`load_previous`；`main :72-177` 改为 manifest 驱动（`--manifest/--external-dir/--previous`，`--lists` 保留为 `--external-dir` 的别名）；`:102-109` 只收 ECDICT cet 标签行；`:112-127` 改成遍历 manifest；`:144-147` `stages` 过滤用 `stage_order`；`:150` `order` 字典改从 manifest；`:157-171` stats v2；`:176-177` ATTRIBUTION 从 manifest 渲染（删 `:201-219` 常量）；`make_record :180-198` 加 `variant_of`/`hs_level`、`sources` 词汇；官方表 missing → exit 2 |
| `scripts/seed_diff.py`（新建） | §3.4.7 |
| `scripts/pack_seed.sh` | `:62,68,79,90` `zcat`→`gzip -dc`；`:63,84,90` `sha256sum`→`shasum -a 256`；`:90` `stat -c %s`→`wc -c <`；头注释 `:12` 的 `make seed` 用法 |
| `Makefile` | `:37-40` 注释与变量（加 `LISTS_DIR`、`PREV_SEED`）；`:93-98` `seed` 目标按 §3.2.5；`:95` 提示改「mahavivo CET lists」 |
| `data/seed/vocab.jsonl.gz`、`stats.json`、`ATTRIBUTION.md`、`DIFF.md`（新） | 重建产物 |
| `ATTRIBUTION.md`（根） | `:14` 记录数与字段说明；`:19-32` §2 改为「2a 国家课标/上海考试院词头（官方文件，只取词头）」+「2b mahavivo CET 三表」 |
| `deploy/fetch_ecdict.sh` | 不改（仍是 release 1.0.28）；`docs/DEPLOY.md:413` 补一句「`make seed` 需要 release `stardict.db`（csv 基础版不行）」 |

**后端（本线负责 `seed.py`；其余为依赖，归阶段模型线，列出以便同一提交）**

| 文件 | 改动 |
|---|---|
| `backend/wd/seed.py` | `:43 STAGES`；`:47-68 SEED_COLUMNS` 加 `stage_xs`；`:204-208` 加 `stage_xs`；`:85-100 SeedStats` 加 `stageless_records`；`import_seed :248` 加 `dry_run` 参数与比较逻辑（§3.5）；`:289-305 system_events` detail 加 `stageless`；`cmd_import_seed/register_cli :333-360` 加 `--dry-run/--report`；`format_stats :319-329` 打印 stageless；docstring `:6-7` |
| `backend/wd/migrations/0011_*.sql`（阶段模型线） | `stage_xs` 列、CHECK 1..5、`stage_min + 1` / `current_stage + 1`、`DROP/CREATE VIEW v_bank` |
| `backend/wd/schemas.py:25-26,51-52,56-67,488,708,1335`（阶段模型线） | 五阶段 |
| `backend/wd/services/words.py:39,576-580,589-597`（阶段模型线） | `STAGES`、`_word_defaults`、`_INSERT_WORD_SQL` 加 `stage_xs` |
| `backend/wd/services/ecdict.py:28,118-119,173-177` | **`STAGE_TAGS = ("cet4", "cet6")`**，`stage_min` 公式改查 `schemas.stage_to_index`（§3.1.4 第 4 条） |
| `backend/wd/ai/prewarm.py:32-33`、`ai/content.py:49`、`main.py:307-319`（可选 kv 变更） | 阶段模型线 / 可选 |

**文档**

| 文件 | 改动 |
|---|---|
| `docs/DESIGN.md` §3.2 `:193-209` | 表增 `stage_xs`、`variant_of`、`hs_level`；`:202` `stage_min` 1..5；`:209` 验收数字换成新 `stats.json`；§3.1 `:186` 的「cumulative as in the sources」改为 §3.1.3 的表述 |
| `docs/API.md` | `:167`「4 rows」→ 5；`:169` 3,694 → 3,854 与 `new_only` 说明；`:239-240,459-460` 五阶段与映射（阶段模型线，契约提交） |
| `docs/TASKS.md:164-178` | 验收脚本的常量换新；加 `wd import-seed --dry-run` |
| `docs/DEPLOY.md` | `:304` `WD_SEED_PATH` 行加「种子格式 2」；`:413,417` `import-seed --dry-run`；§10 加本次停机迁移说明 |
| `docs/WORD_LIBRARY_CURATION.md` §1.2 | 加一段「阶段来源 = 官方词头清单（data/lists）」与 `DIFF.md` 评审流程 |
| `frontend/src/i18n/zh.ts:86` + `docs/FRONTEND.md §8` 对应行 | `sources.lists` 文案（前端线，门禁 `check-copy.mjs`/`zh.test.ts`） |
| `README.md:78` | 记录数 |

---

## 5. 测试与验收

### 5.1 会变红的现有测试（按 75df534 行号）与处理

| 测试 | 为什么红 | 处理 |
|---|---|---|
| `backend/tests/unit/test_seed.py:93`（abandon `stage_min == 2`）、`:94`（absolutely 3）、`:96`（ought to 4）、`:97`（a 1 ✓） | 重编号 1..5：abandon gk → 3，absolutely cet4 → 4，ought to cet6 → 5 | 改常量；`a` 加 xs 后仍为 1 |
| `test_seed.py:98`（无 `stage_min NULL`） | 若夹具加入无阶段记录 | 改为 `== 1`（见 5.2） |
| `test_seed.py:197`（改 abandon `stages` 为四阶段后断言 `stage_min == 1`） | 五阶段下应写 `["xs","zk","gk","cet4","cet6"]` | 改列表；`:204` 断言不变 |
| `test_seed.py:291-298 test_seed_row_mapping_and_validation` | `seed_row` 返回多一个键 `stage_xs`；`:294` 的元组要加一项 | 加 `r["stage_xs"]` 并断言 `("ice cream" stages cet6,zk)` → stage_min 2 |
| `test_seed.py:339-353 test_full_seed_acceptance_numbers`（`full_seed` 标记） | 全部数字作废 | 改为读 `data/seed/stats.json` 的 `per_stage/first_stage/total_words` 做比对 + 保留 `phrase`/`cet6_star`/`word_forms` 的不变量；`kind='phrase'` 数将从 13 变为 ≈13 + 新多词专名数 |
| `backend/tests/unit/test_api_schemas.py:33-39` | 五阶段、`index_to_stage(6)` 才抛、`STAGE_NAMES_ZH` 多 `xs` | 阶段模型线 |
| `backend/tests/integration/test_vocab.py:69-70,75-76,111` | `/api/stages` 5 行、`items[3]`→`items[4]`、`stage_min == 5` | 阶段模型线 + 本线夹具 |
| `backend/tests/integration/test_screen.py:129-130,133-134` | 注释里的「stage_min 4」→5；`stage=zk` 的 `["be","a","go"]` 在夹具里仍是 zk 旗标词、按 frq 排序不变 | 只改注释；若夹具给 `an` 加 zk 可能挤进前三，所以 5.2 不给 `an` 加 |
| `backend/tests/unit/test_batches.py:127`（主攻 cet4 `absolutely, axis`） | 夹具里二者仍是 cet4 首阶段 | 不变 |
| `backend/tests/unit/test_content_apply.py:255`（go 的 `stages` 中文标签） | `go` 加 xs → `["小学","初中","高中","四级"]`（需 `STAGE_ZH["xs"]`） | 改期望 |
| `backend/tests/unit/test_words_resolve.py:478`、`integration/test_reports.py:86-87`（abandon `stage_min == 2`） | 重编号 → 3 | 改常量（`test_reports` 自插的行若写死 `stage_min=2` 同步改 3） |
| `backend/tests/unit/test_db.py:362-366` | 不红（0011 是新文件，`SCHEMA.sql` 不动） | — |
| `scripts/smoke.py:352` | 五阶段列表 | 改 |
| `scripts/check_contract.py:274-281` | `Stage/StageIndex` 两边同改即过 | 契约提交 |
| 前端 16 个 `*.test.ts(x)`（verify stage-model 第二节修正） | 前端线 | — |

### 5.2 夹具 `backend/tests/fixtures/mini_seed.jsonl`（60 条，15 键）

只改 `stages`/`sources`，不动其他字段（它们是手工精简的 ECDICT 数据）；**不**按新种子重标 gk（那会让 `abolish/abrupt/absurd/AIDS/running` 掉出高中层、`ought to/absolutely` 进高中层，连锁打破 `test_screen.py:130`、`test_batches.py:127` 的排序断言）。最小改动：

- 给 L2 成员加 `"xs"`（且 `sources` 加 `moe22-l2`）：`a, apple, be, book, cat, child, China, clothes, computer, dog, email, glass, go, good, happy, house, ice cream, run, some, study, take, teacher, TV, water`（24 个，按 `final.py` 的夹具映射；`an` 故意不加）。
- 新增 2 条：`is` 改为 `stages: []`（它在新种子里正是无阶段词）→ 覆盖 `stage_min NULL` 的导入路径（`test_seed.py:98` 改 `== 1`，`test_vocab.py` 的 `total == 60` 不变因为 `is` 本来就在）；`color` 加为 `stages ["xs","zk","gk","cet4"], variant_of: "colour"`（第 61 条）→ `test_seed.py:61,63,64,73` 的 60 → 61，`test_vocab.py:93,99` 的 60/10 → 61/11，`test_seed.py:122-138` 的 `word_forms` 断言不受影响（`color` 的 exchange 只给 `s`）。
- 新增单测：`test_seed_row_ignores_unknown_keys`（`variant_of`/`hs_level` 不报错）、`test_import_dry_run_writes_nothing`（`dry_run=True` 后 `words`/`kv`/`system_events` 字节不变，返回的计数与真实导入一致）、`test_stageless_record_is_imported_with_null_stage_min`。

### 5.3 新增的流水线测试（`backend/tests/unit/test_build_seed.py`，新文件，直接 import `scripts/build_seed.py`）

- `parse_list` 对 `best（good, well的最高级）[best] …`、`less（little的比较级） [les]`、`wolf（复wolves）`、`a (an) [ə, eɪ(ən)] art.`、`practice(s)e` 五类行的产出（修复 verify list-sources 遗漏 3）；plain 模式保留 `a`/`I`、跳过 `A`。
- `parse_official` 读头注释、`count` 不一致报错、`variants` 列拆分、`group` 列。
- `canon`/aliases：`Mr→mr.`、`o’clock→o'clock`、`café→cafe`、`hot-dog→hot dog`。
- `members_of` + `stages_for`：`colour\tcolor` → 两条记录同阶段、后者带 `variant_of`；`be (am, is, are)` 不产生成员；`moe22-app` 的 `number` 组 → `["xs","zk"]`。
- 用一个 10 词的迷你 `stardict` SQLite（测试内建）跑 `main`：官方词缺失 → exit 2 并列出；`--previous` 回填无阶段词并带 `legacy-gk`；输出排序稳定（两次构建字节相同）。
- `seed_diff.py`：不变量失败 exit 1；矩阵数字正确。

### 5.4 在 `live-copy.db` 私有拷贝上的排练（不碰线上目录）

```
D=/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/word-lists-official-purist/rehearsal
mkdir -p $D && cp …/scratchpad/live-copy.db $D/word-dance.db                  # 私有拷贝；live-copy.db 本身只读
export WD_DATA_DIR=$D WD_DB_PATH=$D/word-dance.db
/Users/sqin/word-dance/.venv/bin/wd migrate --dry-run                         # 应列出 0011
/Users/sqin/word-dance/.venv/bin/wd migrate                                   # 走 run_migrations（不要用 /usr/bin/sqlite3 排练：legacy_alter_table=1 会掩盖 v_bank 问题，verify stage-model-13）
/Users/sqin/word-dance/.venv/bin/wd import-seed --file data/seed/vocab.jsonl.gz --dry-run --report $D/dry.json
/Users/sqin/word-dance/.venv/bin/wd import-seed --file data/seed/vocab.jsonl.gz
sqlite3 -readonly $D/word-dance.db "select sum(stage_xs),sum(stage_zk),sum(stage_gk),sum(stage_cet4),sum(stage_cet6) from words; select stage_min,count(*) from words group by 1;"
WD_FULL_SEED_DB=$D/word-dance.db .venv/bin/pytest -m full_seed backend/tests/unit/test_seed.py
```
验收：计数与 `stats.json` 一致；`user_words` 77 行、`word_contents`、`word_images`、`review_logs` 字节不变（`dump` 前后对比）；`foreign_key_check` 空；`integrity_check ok`；第二次 `import-seed` 打印 `seed up to date`。

---

## 6. 上线与回滚（Mac，launchd）

前提：合并了 0011 迁移 + 五阶段常量 + 新种子的同一个提交（或连续提交）已 `git pull`，前端快照已按 memory 中的 Mac 流程构建；`export WD_DATA_DIR=/Users/sqin/word-dance-data`（CLI 默认是 Linux 路径）。

1. 手工备份：`.venv/bin/wd backup --keep-daily 14 --keep-weekly 8`（在 03:30 的 `com.word-dance.backup` 之外多留一份）。
2. 停服务：`launchctl bootout gui/$(id -u)/com.word-dance.server`；确认 `kv.worker_lease` 过期后再继续（`wd restore` 也会检查）。
3. 迁移：`.venv/bin/wd migrate --dry-run`（看到 0011）→ `.venv/bin/wd migrate`（自动写 `backups/pre-migrate-10-to-11.db.gz`，`backup.py:283-292`）。重建后库文件会从 ≈5.6 MB 涨到 ≈9.4 MB 且不会自动收缩（verify stage-model 遗漏 4），可在服务停着时手动 `sqlite3 word-dance.db 'VACUUM'`。
4. 预览：`.venv/bin/wd import-seed --dry-run`——应报 ≈112 inserted、≈9,162 updated（**每一行**的 `sources` 词汇都变了，UPSERT 的 WHERE 对全部旧行成立），其中阶段集合变化 2,603 行、`stage_min` 变化 2,562 行、stageless 243、各阶段增减与 `DIFF.md` 一致；不一致就停下。
5. 导入：`.venv/bin/wd import-seed`（0.2 s 量级，seed-pipeline-15）。
6. 起服务：`launchctl kickstart -k gui/$(id -u)/com.word-dance.server`（`wd serve` 启动时 `run_migrations` 无事可做、`seed_check` 因 `kv.seed_version` 相同为 no-op，`main.py:482-485`）。
7. 验证：`curl --noproxy '*' http://127.0.0.1:8000/api/health`；登录后 `GET /api/stages` 5 行且 `total` = `stats.json.per_stage`、`new_only_total` = `first_stage`；`GET /api/vocab?stage=xs&new_only=1` 总数 594；`GET /api/settings` 两个用户的 `current_stage` 字符串不变（`zk`、`cet4`）；`~/Library/Logs/word-dance/word-dance.log` 无 `MigrationError`/`seed` 告警。
8. 回滚：`launchctl bootout …` → `.venv/bin/wd restore /Users/sqin/word-dance-data/backups/pre-migrate-10-to-11.db.gz --yes` → `git checkout 75df534`（或前一标签）→ 重建前端快照指向旧 sha → `launchctl kickstart -k …`。注意：新代码 + 旧库（只回代码不回库）会在 `schemas.py:65` 对 `current_stage=5` 抛 `ValueError`→500（verify stage-model 遗漏 2），所以**库与代码必须一起回**；回滚会丢失快照之后的学习记录。

---

## 7. 风险、未决问题、工作量

### 7.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 官方 L2/L3 的机读件是社区转录（官方 PDF 为扫描件） | 个别词漏/错（本次解析 L2 504–506、L3 1,606–1,611 带 ±1% 噪声：`metr e`、`kung fu` 拆行、页首词） | 产出流水线按页与官方扫描件对账并在头注释记录 `count`；`parse_official` 校验计数；`DIFF.md` 评审 |
| 2025 修订版高中表的印发文号未找到（INDEX 未解决 1） | 若正式性存疑，gk 多出 256 个词 | `hs25` 单独成文件、`sources` 可追溯；必要时把 `hs25.member` 置 false 重建，gk 退回 HS3000 |
| 上海 2026 手册已到 1,785 词（INDEX B6），我们只有 2020 版机读件 | 上海初中层缺最近增补的 ≈50 词 | 文件名带年份，后续替换；`shmeea20` id 不变 |
| ECDICT 错义项（bund、mum、PE、bce/ce、hotdog） | 小学/初中生看到错释义 | `overrides.jsonl` + 构建期「官方词缺失即失败」；建议产出流水线对全部新词的首行译文做一次人工扫读（112 个，半小时） |
| `is/are/am/does` 变无阶段 | 学习者按阶段浏览看不到 `is` | 它们不是任何官方表的词头；`be` 是成员；搜索仍能命中。若产品不接受，可在 `moe-2022-appendix.tsv` 加 `group: forms`（`member: false`）之外给 be 的屈折一个 `aliases` 继承——不建议 |
| 阶段编号假设（1..5）与阶段模型线最终方案不一致 | `seed.py:208` 与 `ecdict.py:177` 的公式 | 两处都改成查 `schemas.stage_to_index`，与编码无关 |
| `kv.seed_version` 跨平台 gzip 差异 | Mac 打包后伪重导（无害） | §3.4.8 可选项 |
| 夹具连锁 | 排序类测试被无意改动 | §5.2 的最小改动原则 |
| 用户看到自己收藏的词「阶段变了」 | 64/77 个生词多了一个 chip | 无数据损失；发布说明一句话 |

### 7.2 未决问题

1. 上海 331 个词组何时入库（§3.3.7 建议第二版），`sb./sth.` 模板的归一规则由谁定。
2. 教材拓展层（Q2-c）与「拓展/超纲」阶段位（Q4-c）——本设计只预留了 `member: false` 词表位与 `legacy-*` 来源标记。
3. 把 cet.edu.cn 2016 大纲 PDF 解析进 `data/lists/`，彻底去掉 `WORDLISTS_DIR`（CET 的「纯净化」）。
4. `kv.seed_version` 是否改为内容哈希（§3.4.8）。
5. `hs_level` 是否进 DB（为 `difficulty` 尺子或「必修/选择性必修」筛选服务）——本轮只进种子文件。
6. 显示大小写：`AI`/`APP` 用 ECDICT 大写还是官方 `app` 小写（§3.3.8）。

### 7.3 工作量（本线，人日）

| 项 | 人日 |
|---|---|
| `build_seed.py` 重构 + manifest/aliases/overrides + `seed_diff.py` + `pack_seed.sh` 可移植 | 3 |
| `data/lists/README.md`、provenance、`ATTRIBUTION.md` 两处、`zh.ts` 文案（含 FRONTEND §8 镜像） | 1 |
| `seed.py`（`stage_xs`、`--dry-run`、stats）+ 单测 + 夹具最小改动 + `test_build_seed.py` | 2 |
| 文档（DESIGN §3.2、API 数字、TASKS 验收、DEPLOY、CURATION） | 1 |
| 排练（§5.4）、上线（§6）、发布说明 | 1 |
| **合计** | **≈8**（不含 0011 迁移、10 份阶段常量、前端页签——阶段模型/前端线；不含 `data/lists` 正文的产出——另一条流水线） |
