# moe-senior 词表产出 — 对抗核验报告

> 本文件含两轮核验。**第一轮**（§0–§6 及其附录，2026-11-06 00:10）针对修正前的产出，结论 status = fix，作者已按其 §5 逐条修正（见 `data/lists/moe-senior.README.md` §10）；**第二轮**（§7–§14，2026-11-06，本轮）针对修正后的产出，独立重做结构检查、解析、图像抽样、差异重算与 provenance 核对。第一轮 §1 表中的「+1 表头行」与 §0 的结论已随修正失效，以第二轮 §7 为准。

核验日期 2026-11-06（任务记录日期 2026-11-05）；仓库基线 main @ 75df534（只读）。
核验对象：`data/lists/moe-2020-senior.tsv`、`moe-2020-senior-appendix.tsv`、`moe-2025rev-senior.tsv`、`moe-2025rev-senior-appendix.tsv`、`moe-senior-2020-vs-2025.diff.txt`、`moe-senior.README.md`。
核验脚本与中间文件：`scratchpad/verify-senior/`（`struct.py`、`myparse.py`、`cmp.py`、`diffcheck.py`、`diff2.py`、`prev.py`、`kaogang.py`、`kb3100.py`、`l3.py`、`stats.py`、`bands.py`、`bands_verbose.py`；页面图像 `img/`，72 dpi 灰度 `pgm/`，`e2020.bbox.xhtml`、`h2025.bbox.xhtml`，独立解析结果 `my2020.tsv`、`my2025.tsv`）。全部以 `python3.12 -I` 运行，未联网，未写入线上数据目录。

## 0. 结论

**status = fix**。四个词表文件（主表 3000 / 3099 条、国家表 55 / 56 行、星级 1500/499/1001 与 1600/502/997）与两份 PDF 原件逐条一致，没有发现词条或星级错误；需要改动的是 **差异文件里 1 处匹配错误**（`application` 被重复匹配，`app (=application)` 实为新增）及其在 README / diff 头部的连带计数，另有 3 处文档不一致与 1 处格式一致性问题（详见 §5）。

| 检查项 | 结果 |
|---|---|
| 结构（行数、重复、空行、非 ASCII、字母序、列数、BOM/LF） | 通过；非 ASCII 仅 `café`（两版）、2025 国家表 `—`/`ü`，均为原文（§1） |
| 独立解析（`pdftotext -layout` 法）与产出逐条比对 | 3000 / 3099 条、全部星级一致；仅差声明过的规范化（`x / y`→`x/y` 4 条、`’`→`'`）（§2.1） |
| 页面图像抽样：10 个随机页 + 10 个特殊页 | 每页「原件有而产出无」= 0、「产出有而原件无」= 0（§2.2） |
| 全部 113 个主表页的像素带 ↔ 文字层行数（226 栏） | 0 处不一致；文字层每一行都可见、可见行都在文字层（§2.3） |
| 与之前解析（H2020 / std2020 / std2025rev / kaogang / kb3100）的差异 | 全部可归因于对方的切分/去括号/小写合并/丢星或国家表混入；无一例原件支持对方（§3） |
| README / 文件头 provenance（URL、md5、日期、页码、字体、说明原文） | 与 facts 一致（§4） |
| 差异文件 | 1 处错误（`application`），1 处说明不准确（§5 #1、#5） |

## 1. 结构检查（`struct.py`）

| 文件 | `#` 注释行 | 数据行 | 列数 | 级别分布 | 重复 | 空行 | BOM / CRLF | 非 ASCII |
|---|---|---|---|---|---|---|---|---|
| moe-2020-senior.tsv | 14 | 3000（+1 表头行） | 全部 2 | 0:1500 1:499 2:1001 | 无（大小写不敏感同形：China/china、March/march、May/may、Miss/miss、US/us——原文如此） | 无 | 无 / 无 | `é`（行 410 `café`） |
| moe-2025rev-senior.tsv | 11 | 3099（+1 表头行） | 全部 2 | 0:1600 1:502 2:997 | 无（China/china、Miss/miss） | 无 | 无 / 无 | `é`（行 410 `café`） |
| moe-2020-senior-appendix.tsv | 4 | 55（+1 表头行） | 全部 4 | — | 无 | 无 | 无 / 无 | 无 |
| moe-2025rev-senior-appendix.tsv | 5 | 56（+1 表头行） | 全部 4 | — | 无 | 无 | 无 / 无 | `—`（行 19、50、60、61）、`ü`（行 59 `Türkiye`） |
| moe-senior-2020-vs-2025.diff.txt | 11 | 624 | — | — | — | 5（节间） | 无 / 无 | `≈`、`—`、`ü` |
| moe-senior.README.md | — | — | — | — | — | — | 无 / 无 | 中文标点等 |

- 计数与作者声明完全一致（3000 = 1500+499+1001；3099 = 1600+502+997；55；56）。
- 字母序断点：2020 版 0 处；2025 版 3 处，全部为原文排列（`a.m.`→`a/an`，印刷页 73 文字层第 21–22 行；`dish`→`disc (disk)**`，印刷页 88 图像 `img/h2025-p91-091.png`；`per cent (percent)`→`per*`，印刷页 110 图像 `img/h2025-p113-113.png`）。
- 非 ASCII 字符全部对应原文：`café` 两版 PDF 文字层均为 `é`；2025 国家表的破折号在文字层为 U+2014（`h2025-app.txt` 第 133–135 页），图像亦为长横线；`Türkiye` 图像可见 `ü`（`img/h2025-p135-135.png`）。
- 无不可见字符、无首尾空白、无双空格。
- 文件末尾均以单个 LF 结束，无 BOM。

## 2. 独立解析与原件核对

### 2.1 独立解析（方法与作者不同）
作者用 `-bbox-layout` 坐标聚类；本次用 `pdftotext -layout` 文本（`e2020-app.txt` PDF 129–186 页、`h2025-app.txt` 76–135 页），按 ≥2 个空格切段、以字符列偏移（<12 左栏）分栏、左栏先于右栏、A→Z 顺序消费单字母标题（标题 `I` 先于词 `I`）、括号未闭合则合并续行、词尾 `*`/`**`（允许前置空格）剥为级别（`myparse.py`）。

结果：2020 = 3000 条（1500/499/1001），2025 = 3099 条（1600/502/997），26 个字母标题全部按序消费，唯一合并为 2020 `kilo (kilogramme, kilogram)`（PDF 156 页）。与产出逐条（顺序 + 词形 + 级别）比对（`cmp.py`）：2020 仅 5 处、2025 仅 1 处差异，全部是作者声明的规范化——`bride / bridegroom`、`chairman / chairwoman`、`policeman / policewoman`、`salesman / saleswoman` → `/`（TSV 行 364、463、2005、2295），`o’clock` → `o'clock`（2020 行 1827、2025 行 1890）。

### 2.2 页面图像抽样（`pdftoppm -r 220`，Read 逐词逐星阅读）
随机页（与作者核对过的页不重叠）：

| 版本 | PDF 页 | 印刷页 | 产出条数（左/右） | 原件有而产出无 | 产出有而原件无 | 星级 |
|---|---|---|---|---|---|---|
| 2020 | 135 | 127 | 56（28/28）between…bowling** | 0 | 0 | 一致 |
| 2020 | 150 | 142 | 54（28/26）former*…gather*，含标题 G | 0 | 0 | 一致 |
| 2020 | 163 | 155 | 56（28/28）offer…own，含 `organisation (organization)*`、`ought to*` | 0 | 0 | 一致 |
| 2020 | 171 | 163 | 54（26/28）row…sea，含标题 S、`salesman / saleswoman**` | 0 | 0 | 一致 |
| 2020 | 178 | 170 | 56（28/28）telephone…thunder**，含 `television (TV)` | 0 | 0 | 一致 |
| 2025 | 85 | 82 | 56（28/28）certain…circus**，含 `chef **`、`chief *`、`China`/`china*` | 0 | 0 | 一致 |
| 2025 | 95 | 92 | 54（28/26）exhaust**…farmer，含标题 F | 0 | 0 | 一致 |
| 2025 | 110 | 107 | 54（28/26）news…offer，含标题 O、`o’clock` | 0 | 0 | 一致 |
| 2025 | 120 | 117 | 56（28/28）sand…series* | 0 | 0 | 一致 |
| 2025 | 128 | 125 | 56（28/28）too…twice*，含 `towards (toward)`、`T-shirt`、`TV (=television)` | 0 | 0 | 一致 |

特殊页（针对作者自报的不确定项与异常）：

| 版本 | PDF 页 | 印刷页 | 核对点 | 结果 |
|---|---|---|---|---|
| 2020 | 156 | 148 | `kilo (kilogramme,` / `kilogram)` 跨两行；本页 49 条（左 26、右 23 + 标题 K + 1 续行） | 一致 |
| 2020 | 184–186 | 176–178 | 主表末 13 词 + 国家表 55 行：`DPRK=Democratic People's Republic of Korea`、`Frenchman / Frenchwoman`、`Netherlands / Holland`、`ROK=Republic of Korea`、`U.K.=the United Kingdom`、`U.S.A.=the United States of America`、`Viet Nam`、`Turkey`/`Turk`、`Poland`/`Pole` | 与 appendix.tsv 55 行一致（` / `→`/` 为声明规范化） |
| 2025 | 101 | 98 | `humour (humor)`、**`humourous*`**（印刷原文确为此拼写）、标题 `I` 与词 `I`、`ice cream`、`host/hostess` | 一致 |
| 2025 | 91 | 88 | `dish` 后接 `disc (disk)**`（原文顺序） | 一致 |
| 2025 | 113 | 110 | `per cent (percent)` 后接 `per*`（原文顺序）、`photo (=photograph)`、`ping-pong`、`pizza` | 一致 |
| 2025 | 133–135 | 130–132 | 国家表 56 行：图像显示「阿根廷」（文字层仅「阿根」，作者补正正确）、`Democratic People's Republic of Korea—DPRK`、`Frenchman/ Frenchwoman`、`Republic of Korea—ROK`、`Saudi Arabia`、`Türkiye`、`the United Kingdom—UK`、`the United States of America—USA`、`Vietnam`、`Poland`/`Polish`、`Netherlands` | 与 appendix.tsv 56 行一致 |

合计本次图像核对 2020 版 7 页、2025 版 10 页（含 3 页国家表），加上作者核对的 9 页，两版共 24 个不同页面经图像逐词核对，无任何差异。

### 2.3 全页像素带检查（`bands.py`）
因 2025 版为论坛镜像、文字层含不可见页脚文字，补做机器检查：对两版全部 113 个主表页（2020 PDF 129–184、2025 PDF 76–132）渲染 72 dpi 灰度图，用 `-bbox-layout` 取每个文字层行框；按栏统计正文区（首行上 6 pt 至末行下 6 pt）内的可见文字带数，与文字层行数比对，并检查每个文字层行框内是否有墨迹。

结果：**226 栏全部一致，0 个不可见行、0 个多出的可见带**。检测器有效性（`bands_verbose.py`）：2025 PDF 85/101 页文字层中的页脚「普通高中英语课程标准（2017 年版 2025 年修订）」墨迹像素 = 0（证实 README §9 第 3 条的「不可见页脚」），而同页 `chef **` 62 px、`humourous*` 126 px、标题 `I` 16 px / 词 `I` 10 px；2020 版可见页眉 824 px。即：两版文字层在词表区域没有任何看不见的行，也没有任何图像里有而文字层没有的行（星级仍以 §2.2 的 24 页人工核对为准）。

## 3. 与之前解析结果的差异裁决（`prev.py`、`kaogang.py`、`kb3100.py`）

| 对照文件 | 规模 | 对方有、本产出无 | 本产出有、对方无 | 级别不同 | 裁决（依据原件） |
|---|---|---|---|---|---|
| `verify-provinces/out/H2020.txt` | 2997 | 除 `pe`（`PE` 小写）外，全部是本产出词条按空白/括号切出的 token（`according`、`curd`、`due`、`mobile`、`ought`、`an`、`bean`、`kilogramme`…） | 135 条：全部带括号/斜杠/大写/非 ASCII 的词条（对方小写化并切分） | 27（按首词形）：`advertisement (ad)`、`analyse (analyze)` 等 24 条带括号/斜杠词条对方丢星；`china`、`march` 大小写合并取无星；`directory **` 空格星丢失 | 24 页图像与 226 栏像素检查均支持本产出；README §7 归因成立 |
| `provinces/std2020_hs_words.txt` | 3004 | 同上 + 国家表 token `adjectives`、`frenchman`、`frenchwoman`、`korea`、`related`、`states`、`united` | 137 条（同上 + `a.m.`、`p.m.`：对方去掉了尾点） | 27（同上） | 国家表 token 来自 PDF 184–186 页表格（图像可见），不属主表；本产出分离正确 |
| `provinces/std2025rev_hs_words.txt` | 3221 | 117 个国家/国籍/表头 token（`afghan`…`zealander`、`n`、`related`、`adjectives`）+ 切分 token（`kung`、`fu`、`ai`、`bce`、`ce`、`tv`、`mr`…） | 101 条（带括号/斜杠/大写/非 ASCII 词条） | 29：`behalf`、`belief`、`chef`、`chief`、`per`、`staff`、`stuff`、`surf` 空格星丢失；`BCE`/`CE`/带括号词丢星；`phone` 0→1、`to` 0→1 是 `mobile phone*`、`due to*`/`ought to*` 切分后把星号给了末 token；`china` 合并 | 空格星在图像中清晰可见（印刷页 82 `chef **`、`chief *`）；本产出正确 |
| `shanghai-secondary/07-yr7429/kaogang_graded.txt`（仅对照） | 3099 | — | — | 0 | 3099 条词形与级别**逐条一致**，仅 `civilisation(civilization)` 无空格、`o’clock` 弯引号两处格式差异（后者是本产出的规范化所致） |
| `shanghai-secondary/analysis/lists.json` 的 `kb3100`（docx 解析） | 3091；无星 1591 / 一星 **500** / 二星 **1000** | 12 个斜杠拆分形（`an`、`actress`、`anyone`、`bridegroom`、`chairwoman`、`empress`、`everyone`、`hostess`、`policewoman`、`princess`、`saleswoman`、`someone`） | 18 条：全部 `(=…)` 缩写条目（`ad`、`AI`、`app`、`bike`、`exam`、`fridge`、`gym`、`kilo`、`lab`、`maths`、`PE`、`photo`、`TV`）及 `be (am, are, is)`、`mother (mum, mom)`、`café`、`I`、`o'clock` | 1（`china` 0 vs 1，大小写合并） | **其「一星 500 / 二星 1000」恰等于官方数字是伪象**：拆分 `bride/bridegroom`、`chairman/chairwoman`、`salesman/saleswoman` 多出 3 个两星（997+3=1000），丢 `café*` 并合并 `China`/`china*` 少 2 个一星（502−2=500）。因此它不构成对本产出 502/997 的反证，反而佐证镜像 PDF 本身就是 502/997。 |

`shanghai-secondary/analysis/` 其余内容（`sh2020`、`nat_zk`、`nat_gk`）是上海/中考/教辅词表，与本任务无关。

README §5 引用的 L3 对照数字（1611 token、1603 在 2025 主表、1601 为级别 0、例外 `cream`/`per`）已用 `l3.py` 复算，完全一致；8 个不在 2025 表内的 token 为 `e`、`fu`、`kung`、`metr`、`policemen`、`w`、`x`、`yogurt`（L3.txt 自身的切分噪声）。

## 4. README / 文件头 provenance 核对

| 项目 | README / 文件头 | 核验 | 结果 |
|---|---|---|---|
| 2020 来源 URL | `…/202006/W020200603315372317586.zip`，通知页 `t20200603_462199.html` | `facts/provinces.md` [provinces-3] 第 30 行 | 一致 |
| 2020 本地副本 md5 | `2398e9465bac25444a30db7f07a025cc`；zip `42762e0d75efede84e96375deb19c333` | `md5 -q` 实测 | 一致 |
| 2020 页码 | PDF 129–186 = 印刷 121–178；主表 121–176；国家表 176–178 | 图像：PDF 135→127、150→142、156→148、163→155、171→163、178→170、184→176（主表 + 国家表同页）、185→177、186→178 | 一致 |
| 2020 元数据/字体 | Founder PDF Library，2020-05-29；方正 CID TrueType + Times-Roman | `pdfinfo`、`pdffonts -f 129 -l 186` | 一致 |
| 2025 来源 URL | `https://forum.freemdict.com/uploads/short-url/doVmJXenSoIbcg8t5HA0hkWcccm.pdf`，178 页，2025-10-31 | [provinces-4] 第 36 行；`pdfinfo` | 一致 |
| 2025 本地副本 md5 | `77e8f0d793808e59c18dc89fa5f169d6`（两处副本相同） | `md5 -q` 实测两文件 | 一致 |
| 2025 页码 | PDF 76–135 = 印刷 73–132；主表 73–129；国家表 130–132 | 图像：85→82、91→88、95→92、101→98、110→107、113→110、120→117、128→125、133→130、134→131、135→132 | 一致 |
| 2025 字体 | FZZHUNYSK/FZSYK/FZDBSK + TimesNewRomanPSMT | `pdffonts` 全文含这些字体；附录页实际用 FZSYK/FZXBSJW/FZHTJW/FZSSJW + TimesNewRomanPSMT/Times-Bold | 一致（文档级描述） |
| 正式性声明 | moe.gov.cn 未见印发通知；人教社期刊已引用 | `verify/provinces.md` 第 35–37、143 行 | 一致 |
| 「说明」第 1 条原文与 `*` 语义 | 0 = 义务教育已掌握、1 = 必修 500、2 = 选择性必修 1000 | `e2020-app.txt`/`h2025-app.txt` 首页第 8–12 / 4–9 行；[provinces-3]、[provinces-4] | 一致；任务说明中「★★ = 选修」确与原文不符，作者的纠正正确 |
| 格式：`#` 注释头、UTF-8、LF、无 BOM | — | §1 | 一致 |
| 获取日期 2026-11-05 | — | facts 记录 | 一致 |

## 5. 问题清单与建议修正

### #1（必须改）差异文件：`application` 被重复匹配，`app (=application)` 应为新增
- 证据：`moe-2020-senior.tsv:165` `application	1`；`moe-2025rev-senior.tsv:162` `application	1`（两版都有且级别相同）；`moe-2025rev-senior.tsv:154` `app (=application)	0`；`moe-senior-2020-vs-2025.diff.txt:583` 却记为 `≈ application	->	app (=application)	(1->0)`。`diffcheck.py` 的划分检验：2020 侧 精确匹配 2859 + 改写 49 + 删除 93 = 3001 ≠ 3000，多出的正是 `application`（同时出现在精确匹配集与改写集）。
- 原因：第 (2) 步宽松匹配把 2025 `app (=application)` 的括号内容对到了 2020 `application`，而该词已在第 (1) 步与 2025 `application` 精确匹配，未做「已匹配即排除」。
- 修正：
  - `moe-senior-2020-vs-2025.diff.txt`：删除第 583 行；在 `## + 2025 版新增` 节按字母序插入 `+ app (=application)	0`（位于 `+ anniversary` 之后、`+ Antarctica` 之前——该节现有顺序为大小写不敏感字母序）；第 8 行标题改为 `（196）`，第 575 行标题改为 `（48）`；第 5 行小结改为 `+ 新增 196（级别 0: 48，1: 74，2: 74）… ≈ 词形改写 48`。
  - `moe-senior.README.md`：第 15 行 `+195 / -93 / ~273 / ≈49` → `+196 / -93 / ~273 / ≈48`；第 93 行「新增 205→195 因本次把 … `application`→`app (=application)` … 记为词形改写」中删除 `application` 一项并改为 205→196；第 99 行「新增 195（级别 0: 47 …）」→「196（级别 0: 48 …）」。
  - 其余 48 对 ≈ 经 `diff2.py` 复核无类似问题（`actress→actor/actress` 等 5 对「二合一」为有意合并，正确）；`+`/`-` 两节中没有首词形或括号形在另一版存在的词。

### #2（文档）`moe-2025rev-senior.tsv:11` 校验页码与 README 不一致
- 文件头写「印刷页 73、74、127、129」，README §6 表写 2025 印刷页 73、74、98、129、130；作者 `lists-senior/img/` 实际渲染了 PDF 76、77、101、130、132、133、134、135（= 印刷 73、74、98、127、129、130、131、132）。
- 修正：把文件头改为与 README 一致（建议「73、74、98、127、129、130」），或在 README §6 表补上印刷页 127（若确已核对）。本次核验结果不受影响。

### #3（文档）README §4 第 53 行「词条形态统计」的多词条数
- 产出规范化后：2020 多词词条 5 条（`according to`、`bean curd (tofu)`、`due to`、`mobile phone`、`ought to`），README 写 8 条（显然把规范化前的 4 条 `x / y` 形式计入）；2025 为 6 条（README 列 5 条，漏 `per cent (percent)`）。
- 修正：改为「2020 版 5 条多词（另 4 条 `x / y` 并列已折为 `x/y`）；2025 版 6 条（含 `per cent (percent)`）」。

### #4（文档）README §6 第 84 行「2020 第 156 页 26 行×2 − 1 跨行 = 49」算式不成立
- 26×2−1 = 51。实际：左栏 26 条，右栏 23 条（右栏另占 1 个字母标题 `K` 和 1 个续行 `kilogram)`），26 + 23 = 49（图像 `img/e2020-p156-156.png`）。
- 修正：改写为「左 26 + 右 23（右栏含标题 K 与 1 个续行）= 49」。

### #5（文档）差异文件第 4 行与 README 对 ≈ / ~ 的口径说明不准确
- 第 4 行称「第 (2)(3) 步匹配上的记为 ≈」，但 ≈ 节实际还包含第 (1) 步首词形相同而全文不同的 40 余对（如 `child (pl. children)→child`、`grey→grey (gray)`）；且 `emperor/empress`、`gym (=gymnasium)`、`host/hostess`、`medium` 4 条同时出现在 ~（273）与 ≈ 两节，而 ≈ 中首词形不同且级别变化的 3 对（`advertisement (ad)→ad`、`percent→per cent (percent)`、`bean curd (tofu)→tofu (bean curd)`；修正 #1 后 `app` 不再在列）不计入 273。
- 修正：第 4 行改为「≈ = 已匹配但全文不同的所有对（含第 (1) 步）；~ = 首词形相同且级别变化（可与 ≈ 重叠）」，并在 README §8 注明两节有 4 条重叠、273 不含首词形不同的级别变化。

### #6（格式一致性，低）四个 TSV 的非注释表头行
- `moe-2020-senior.tsv:15`、`moe-2025rev-senior.tsv:12` 有 `word	level`，两份 appendix 第 5/6 行有 `country_zh	country	person	adjective`。统一格式只规定「`#` 注释头 + 每行一个词头」；同目录的 `shmeea-2020-junior-forms.tsv`、`shmeea-2020-junior-appendix.tsv` 没有表头行。按行计数会得到 3001/3100/56/57，朴素消费者会把 `word` 当词头。
- 建议：把表头行改为注释（如 `# columns: word<TAB>level`），或在 README §1 明示「首个非注释行为表头」。属一致性问题，不影响内容正确性。

### #7（文档，极低）README §7 第 94 行 kaogang 对照「唯一差别 `civilisation(civilization)` 无空格」
- 实测还有 `o’clock` 弯引号一处差异（由本产出的 `’`→`'` 规范化造成）。可补一句。

## 6. 不需改动的观察

1. **2020 版 499 / 1001 的那一颗星**：两版之间级别由 2 变 1 的只有 `million`（2020 `million**`，2025 `million*`，diff 第 462 行）；这与「2020 版某个 `**` 本应是 `*`」的假设相容，但不能证明（推断，置信低）。按原文输出是对的。
2. **2025 版 3099 / 502 / 997**：本次独立解析、YR7429 的 `kaogang_graded.txt`、作者解析三者一致；`kb3100` 的 500/1000 已证明是切分伪象（§3）。镜像与正式印刷本是否一致仍无法在本地判定，README 的「待核」标注恰当。
3. **数词/月份/星期不在 2025 主表**：`hs2025.txt` 全文检索 `Monday`、`January`、`hundred`、`thousand` 等仅出现在正文例文（第 4775 行起的案例语篇），不在词表；README §9 第 6 条的推断（2022 课标另列）未在本任务中核对 2022 PDF，保持「置信中」即可。
4. **不可见页脚**：README §9 第 3 条所述已由像素检查证实（§2.3），且不影响词表区域。
5. 2020 版 `a.m.*`、`p.m.*` 在 PDF 中位于 `always`/`plus` 附近（PDF 131、165 页），产出顺序 = 原文顺序，不是字母序错误。

## 附：本次产生的文件
- `scratchpad/verify-senior/my2020.tsv`、`my2025.tsv`：独立解析结果（词、级别、PDF 页、印刷页、栏、行、原文）。
- `scratchpad/verify-senior/img/*.png`：本次渲染的 20 页 220 dpi 图像；`pgm/*.pgm`：113 页 72 dpi 灰度图。
- 未修改 `data/lists/` 下任何文件；未写入仓库其他路径。

---

# 第二轮核验（修正后产出，2026-11-06）

核验对象：作者按第一轮报告 §5 修正后的 `data/lists/moe-2020-senior.tsv`、`moe-2020-senior-appendix.tsv`、`moe-2025rev-senior.tsv`、`moe-2025rev-senior-appendix.tsv`、`moe-senior-2020-vs-2025.diff.txt`、`moe-senior.README.md`（README §10 列出的 9 项修正），以及修正脚本 `scratchpad/lists-senior-fix/{check_lists.py, order_rule.py, apply_fixes.py}`。
本轮脚本与中间文件全部在 `scratchpad/verify2-senior/`（`struct2.py` 结构检查、`parse2.py` 独立解析、`diff2.py` 差异重算、`table2.py` 国家表解析、`prev2.py` 与早先解析对照；`txt/` 为本轮用 `pdftotext -layout` 逐页重新导出的文字层，`img/` 为本轮用 `pdftoppm -r 220 -x/-W` 渲染的分栏图像，`my2020.tsv`/`my2025.tsv` 为独立解析结果）。全部以 `python3.12 -I` 运行，未联网，未读写 `word-dance-data`，未改动 `data/lists/`，`git status` 仍只有两个未跟踪目录。两份 PDF 的 `md5 -q` 仍为 `2398e9465bac25444a30db7f07a025cc`、`77e8f0d793808e59c18dc89fa5f169d6`。

## 7. 结论

**status = fix（仅文档）**。四个词表文件与差异文件的**内容全部正确**：独立解析（与作者的 bbox 法、第一轮的 layout 法都不同的代码）得到 2020 = 3000（1500/499/1001）、2025 = 3099（1600/502/997），逐条（顺序 + 词形 + 级别）与 TSV 零差异；15 个新抽样页 820 个词条的图像逐词逐星核对零差异；差异文件 +196/−93/~273 的集合与全部级别标注重算一致，第一轮 #1（`application` 重复匹配）已正确修正。需要改动的只有 README 中 **1 处数字错误**（§8「5 对二合一」实为 4 对）和几处措辞不精确（§7、§9 第 6 条、2020 文件头校验页码），见 §13。

| 检查项 | 结果 |
|---|---|
| 第一轮 §5 的 7 项修正（作者 §10 的 9 项） | 9 项全部按原件再次确认，改动与声明一致（§8） |
| 结构（行数、重复、空行、非 ASCII、不可见字符、字母序、列数、BOM/LF） | 通过；非注释行数 = 词条数 3000/3099/55/56（§9） |
| 独立解析 ↔ 产出 | 2020、2025 均 0 处差异（`difflib` 逐位对齐）（§10.1） |
| 图像抽样：10 个随机未核对页 + 5 个针对性页 | 每页「原件有而产出无」= 0、「产出有而原件无」= 0、星级全部一致（§10.2） |
| 差异文件重算 | +/~ 集合、全部级别标注、各节排列顺序一致；≈/− 的差异仅为 4 对「二合一」的记法（§11） |
| 与早先解析的差异 | 全部可归因于对方切分/小写化/丢星/国家表混入，与原件裁决一致（§12） |
| provenance（URL、md5、字节数、页码、字体、许可、日期） | 与 facts/verify 一致（§12.3） |

## 8. 第一轮修正项复核

| 作者 §10 # | 改动 | 本轮用原件复核 | 结果 |
|---|---|---|---|
| 1 | 删 `≈ application -> app (=application)`，加 `+ app (=application)\t0`（diff 第 13 行） | 本轮自渲染 `img/e2020-p132-L-132.png`：2020 印刷 124 左栏 `application*`，无 `app`；`img/h2025-p79-L-079.png`：2025 印刷 76 左栏 `app (=application)`（无星）与 `application*` 并存；TSV：2020 第 165 行 `application\t1`、2025 第 154 行 `app (=application)\t0`、第 162 行 `application\t1` | 正确；插入位置与 2025 原文顺序一致（`anniversary` 133 → `Antarctica` 140 → `app` 154 → `Arctic` 171 行），`diff2.py` 对 + 节 vs 2025 顺序 0 处倒置 |
| 2 | 计数 196/48、48 | `diff2.py` 重算：+196（0:48，1:74，2:74）、−93（0:89，2:4）、~273（1→0 136、0→1 65、2→0 71、2→1 1）；≈ 48 对、2025 侧 44 词形；划分 2859+48+93 = 3000、2859+44+196 = 3099 | 一致 |
| 3 | diff 第 4 行口径、第 6 行排列说明 | 重算：≈ 与 ~ 重叠恰为 `emperor/empress`、`gym (=gymnasium)`、`host/hostess`、`medium` 4 条；首词形不同的级别变化 3 对；各节 vs 2025 顺序（− 节 vs 2020 顺序）0 处倒置，`p.m.` 在 2025 TSV 第 2083 行、`player` 第 2074 行，故 ~ 节 `p.m.` 在 `player` 之后是原文顺序 | 一致 |
| 4 | README §1/§7/§8 计数 | 与重算一致（但 §8 多出一处「5 对二合一」，见 §13 #1） | 1 处新错误 |
| 5 | 2025 文件头校验页码 73、74、98、127、129、130 | 与 README §6 表 2025 行一致；印刷 127 本轮自渲染 `img/h2025-p130-{L,R}-130.png` 复核 53 词（左 24 + 标题 W + `wage**` = 25，右 `waist**`…`web*` 28）与 TSV 2958–3010 行一致 | 一致 |
| 6 | README §4 形态统计 5/6 多词 | `struct2.py`：2020 多词 5、括号 57、`/` 4、首字母大写 69；2025 多词 6、括号 59、`/` 12、大写 29 | 一致 |
| 7 | README §6 第 156 页算式 左 26 + 右 23 | `img/e2020-p156-L-156.png` 26 行 `jam**`…`justify**`；`img/e2020-p156-R-156.png` 标题 K + 23 词（`kilo (kilogramme,`/`kilogram)` 跨两行）；TSV 1470–1518 行 = 49 | 一致 |
| 8 | README §7 kaogang 补 `o’clock` | `kaogang_graded.txt` 第 544 行 `civilisation(civilization)**`、第 1955 行 `o’clock`；2025 TSV 第 537、1902 行 | 一致 |
| 9 | 四个 TSV 表头行改注释 | 2020 第 15 行 `# word\tlevel`、2025 第 12 行、附表第 5/6 行 `# country_zh\tcountry\tperson\tadjective`（`cat -vet` 确认真实制表符）；`grep -vc '^#'` = 3000/3099/55/56；README 第 18 行已明示无表头行 | 一致；第一轮 §1 表的「+1 表头行」自此失效 |

`apply_fixes.py` 每处先断言旧内容再写、断言行号（第 4/5/6/8/13/576/583 行），`check_lists.py` 的 `check-before.txt` 复现第一轮的 3001 划分错误、`check-after.txt` 为 3000——脚本逻辑与输出相符。

## 9. 结构检查（`struct2.py`）

| 文件 | 总行 | `#` 注释 | 数据行 | 列数 | 级别分布 | 重复 | 空行 | BOM/CR/末尾 | 非 ASCII（数据行） | 不可见/格式字符 |
|---|---|---|---|---|---|---|---|---|---|---|
| moe-2020-senior.tsv | 3015 | 15 | 3000 | 全 2 | 0:1500 1:499 2:1001 | 无（大小写同形 China/china、March/march、May/may、Miss/miss、US/us 为原文） | 无 | 无/无/单个 LF | `é`×1（`café`） | 无 |
| moe-2025rev-senior.tsv | 3111 | 12 | 3099 | 全 2 | 0:1600 1:502 2:997 | 无（China/china、Miss/miss） | 无 | 无/无/单个 LF | `é`×1 | 无 |
| moe-2020-senior-appendix.tsv | 60 | 5 | 55 | 全 4 | — | 中英文均无重复 | 无 | 同上 | 仅中文国名 | 无 |
| moe-2025rev-senior-appendix.tsv | 62 | 6 | 56 | 全 4 | — | 无 | 无 | 同上 | 中文国名、`—` U+2014 ×4（第 19/50/60/61 行）、`ü`（第 59 行） | 无 |
| moe-senior-2020-vs-2025.diff.txt | 635 | 6 | 629 | +/−/~ 行 1 个制表符 ×562，≈ 与国家行 3 个 ×57 | — | — | 节间 5 空行 | 同上 | `≈`、`—`、`ü` | 无 |
| moe-senior.README.md | 135 | — | — | — | — | — | 32 | 同上 | 中文 | 无 |

- 无首尾空白、无双空格、无含 `*` 或数字的词形、括号全部配对。
- 字母序断点：2020 版 0 处；2025 版 3 处（第 13→14 行 `a.m.`→`a/an`、847→848 `dish`→`disc (disk)`、2020→2021 `per cent (percent)`→`per`），文字层 `txt/h2025-76.txt` 第 21–22 行、`txt/h2025-91.txt` 第 11 行、`txt/h2025-113.txt` 第 3–4 行均为原文排列。首字母游程两版都恰为 `a…z` 26 段。
- 非 ASCII 全部对应原文：`café` 两版文字层均为 `é`；`—` 见 `txt/h2025-133.txt` 第 33 行 `Korea—DPRK`、`txt/h2025-135.txt` 第 27/31 行；`Türkiye` 见 `txt/h2025-135.txt` 第 23 行。2025 国家表英文序唯一「倒置」`Denmark`→`Democratic People's Republic of Korea—DPRK` 为原文（`txt/h2025-133.txt` 第 29–33 行：丹麦在前、朝鲜在后，沿用 2020 版按 `DPRK` 排序的位置）。
- 与作者 `check-after.txt` 的所有数字一致。

## 10. 独立解析与原件抽样

### 10.1 独立解析（`parse2.py`，方法与作者、第一轮均不同）
逐页 `pdftotext -layout` → 按 ≥2 个空格切段 → 段起始列 ≤3 为左栏、否则右栏 → 左栏先于右栏 → 跳过含 CJK 或纯数字的行 → 2020 第 184 页在「主要国家名称及相关信息」行截断 → 单个大写字母且等于下一个待出现的标题字母则为标题（因此第一个 `I` 是标题、第二个是词）→ 括号未闭合则并入同栏下一段 → 词尾 `*`/`**`（可带前置空格）剥为级别。26 个字母标题两版全部按序消费（2020 在 PDF 129/133/136/…/184，2025 在 76/80/83/…/132）。

结果：2020 = 3000（1500/499/1001），2025 = 3099（1600/502/997）。与产出用 `difflib.SequenceMatcher` 逐位对齐：**两版都是 0 个差异片段**；我的规范化只触及作者声明的几处（2020 `bride / bridegroom` 等 4 条 `x / y`→`x/y`、两版 `o’clock`→`o'clock`）。逐页词数：2020 首页 16、满页 56、含标题页 54/52、第 156 页 49、末页 13；2025 首页 19、第 130 页 53、末页 45——与 README §6 的页面算式一致。

### 10.2 页面图像抽样（`pdftoppm -r 220`，左右栏分别裁剪，Read 逐词逐星阅读）
随机页用 `random.Random(20261106)` 从两版**此前任何人都没有图像核对过的页**（2020 剩余 45 页、2025 剩余 44 页）各抽 5 页；另加 5 个针对性页（2020 PDF 132、154、156；2025 PDF 79、130）。期望值取自我的独立解析（已证明与 TSV 相同）。

| 版本 | PDF 页 | 印刷页 | 产出条数（左/右） | 原件有而产出无 | 产出有而原件无 | 星级 | 备注 |
|---|---|---|---|---|---|---|---|
| 2020 | 136 | 128 | 54（28/26） | 0 | 0 | 一致 | 标题 C；`bride / bridegroom**`、`café*`、`Britain`/`British` |
| 2020 | 138 | 130 | 56（28/28） | 0 | 0 | 一致 | `chairman / chairwoman**`、`chef**`、`chief*`、`China`/`china*`、`child (pl. children)`、`civilisation (civilization)**` |
| 2020 | 141 | 133 | 56（28/28） | 0 | 0 | 一致 | `criterion (pl. criteria)**`、`criticise (criticize)**`、`crayon`、`cream**` |
| 2020 | 149 | 141 | 56（28/28） | 0 | 0 | 一致 | `flavour (flavor)**`、`foot (pl. feet)`、`foggy**`、`first`、`five`、`finally`（无星） |
| 2020 | 180 | 172 | 54（28/26） | 0 | 0 | 一致 | 标题 U；`T-shirt`、`Tuesday`、`twelfth`…`two`、`UK`、`until (till)`、`twice`（无星） |
| 2020 | 132 | 124 | 56（28/28） | 0 | 0 | 一致 | `application*`；无 `app`（修正 #1 的 2020 侧） |
| 2020 | 154 | 146 | 54（26/28） | 0 | 0 | 一致 | 标题 `I` 在词 `I` 之前；`ice-cream`、`hundred`、`India`/`Indian`；TSV 第 1370 行 `I\t0` |
| 2020 | 156 | 148 | 49（26/23） | 0 | 0 | 一致 | 标题 K；`kilo (kilogramme,`/`kilogram)` 跨两行（修正 #7） |
| 2025 | 78 | 75 | 56（28/28） | 0 | 0 | 一致 | `AI (=artificial intelligence)`、`America*`、`anniversary*`、`Antarctica**` |
| 2025 | 99 | 96 | 54（28/26） | 0 | 0 | 一致 | 标题 H；`goodbye (bye)`、`gramme (gram)**`、`grey (gray)`、`gym (=gymnasium)`（无星）、`granddaughter*` |
| 2025 | 103 | 100 | 54（28/26） | 0 | 0 | 一致 | 标题 J；`internet`（小写）、`jeans`/`jog`/`joy`（无星，对应 ~ 1→0） |
| 2025 | 108 | 105 | 56（28/28） | 0 | 0 | 一致 | `million*`（~ 2→1）、`Miss`/`miss`、`missing*`、`mobile`、`mobile phone*`、`mother (mum, mom)`、`millimetre (millimeter)**` |
| 2025 | 125 | 122 | 56（28/28） | 0 | 0 | 一致 | `surf*`（空格星）、`successful*`、`suggestion*`、`sweep`/`symbol`/`suit`（无星） |
| 2025 | 79 | 76 | 56（28/28） | 0 | 0 | 一致 | `anybody/anyone`、`app (=application)`（无星）、`application*`、`Arctic**`、`Asia*`（修正 #1 的 2025 侧） |
| 2025 | 130 | 127 | 53（25/28） | 0 | 0 | 一致 | 左 24 + 标题 W + `wage**`，右 `waist**`…`web*`（修正 #5） |
| 2025 | 133（上部） | 130 | 国家表前 4 行 | 0 | 0 | — | 图像清晰显示「阿根廷」，文字层 `txt/h2025-133.txt` 第 11 行仅「阿根」——TSV 补正正确 |

合计 15 个主表页 820 个词条，**0 处词形或星级差异**；两版图像中 `pl.` 为斜体、星号为上标，TSV 以普通字符保留，符合统一格式。这些页上涉及 diff `~` 节的词（如 `apartment`/`argue` 1→0、`agreement`/`America`/`Asia` 0→1、`cheese`/`cheat`/`cabbage`/`budget` 2→0、`greet`/`suit`/`sweep`/`symbol`/`virus`/`vote`/`wave` 2→0、`million` 2→1、`twice`/`finally`/`fisherman`/`visitor` 0→1）在对应版本的图像里星级与 diff 记录一致；`million**`、`greet**`、`missing` 的 2020 侧另由文字层 `txt/e2020-160.txt` 第 16/29 行、`txt/e2020-152.txt` 第 4 行确认。

### 10.3 国家表（`table2.py`）
按版面行块解析 2020 PDF 184–186（标题行之后）与 2025 PDF 133–135，逐行比较英文 token 多重集与中文国名：2020 55 行、2025 56 行全部一致；唯一差别是 2025 第 3 行文字层「阿根」（图像为「阿根廷」，见 §10.2 末行）。原文 `People’s`（U+2019）、`Frenchman /`+`Frenchwoman`（2020）/`Frenchman/`+`Frenchwoman`（2025）、`DPRK=Democratic`+`People’s Republic of`+`Korea` 等跨行单元格的合并与规范化均如文件头所述。

## 11. 差异文件重算（`diff2.py`）

从两份 TSV 独立实现三步匹配（首词形精确 → 宽松词形 → 大小写不敏感，已匹配者排除）：
- `+` 196（0:48，1:74，2:74）与文件逐词相同；`~` 273 与文件逐词相同，方向 1→0 136 / 0→1 65 / 2→0 71 / 2→1 1；全部 `+`/`−`/`≈` 行的级别标注与 TSV 一致（0 处错误）。
- 我的一对一匹配把 `actress`、`anyone`、`everyone`、`someone` 记为 `−`、把 `≈` 记为 44 对；文件把它们记为 4 条额外的 `≈`（`actor`+`actress`→`actor/actress` 等，diff 第 579–580、582–583、591–592、617–618 行），即 ≈ 48 对 / 44 个 2025 词形、`−` 93。两种记法都自洽，文件的记法已在第 4 行与 README §8 声明——但 README §8 把这 4 对写成「5 对」（§13 #1）。
- 排列顺序：`+`、`~`、`≈`（按 2025 词形）vs 2025 TSV 顺序、`−` vs 2020 TSV 顺序，均 0 处倒置（含 `~ p.m.` 在 `~ player` 之后）。
- 国家附表节：按中文国名比较两份附表，新增 1（沙特阿拉伯）、改写 8（朝鲜、荷兰、波兰、韩国、土耳其、英国、美国、越南）与文件第 627–635 行一致。
- 机械规则下的「近似对」：`humorous`（− 0）/`humourous`（+ 1）、`Olympics`（− 0）/`Olympic`（+ 0）按声明的规则确实不匹配（拼写/单复数差异不在宽松规则内），作为 −/+ 列出不算错误，但读者可能误读为「删了 humorous、新增 humourous」（§13 #5）。

## 12. 与之前解析结果的差异裁决（`prev2.py`）

| 对照文件 | 规模 | 对方有、本产出无 | 本产出有、对方无 | 级别不同 | 裁决 |
|---|---|---|---|---|---|
| `verify-provinces/out/H2020.txt` | 2997 | 132 = 69 个多部分词条的切分 token（`a`、`according`、`curd`、`bridegroom`、`kilogramme`…）+ 63 个小写化形（`ad`、`africa`、`i`、`internet`…）；**0 个无法解释** | 135 = 65 条带括号/斜杠/空格 + 68 条首字母大写 + `café`、`o'clock` | 27：24 条带括号/斜杠/空格星号的词条对方记 0（`advertisement (ad)` 2、`directory` 2、`bride/bridegroom` 2…），`china`/`march` 大小写合并取 0 | 图像：`bride / bridegroom**`（p136）、`chairman / chairwoman**`、`china*`、`civilisation (civilization)**`（p138）、`criterion (pl. criteria)**`（p141）、`flavour (flavor)**`（p149）均带星；本产出正确 |
| `provinces/std2020_hs_words.txt` | 3004 | 同上 + 7 个国家表 token（`adjectives`、`frenchman`、`frenchwoman`、`korea`、`related`、`states`、`united`）+ `a.m`/`p.m` 去点形 | 137（同上 + `a.m.`、`p.m.`） | 27（同上） | 国家表 token 来自 PDF 184–186 表格；本产出分离正确 |
| `provinces/std2025rev_hs_words.txt` | 3221 | 223 = 88 个切分 token + 117 个国家表/表头 token + 18 个小写化形；0 个无法解释 | 101 = 77 条带括号/斜杠/空格/连字符 + 20 条大写 + `a.m.`/`p.m.` + `café`/`o'clock` | 29：`behalf`/`belief`/`chef`/`chief`/`per`/`staff`/`stuff`/`surf` 的空格星丢失、`BCE`/`CE`/带括号词丢星、`phone` 0→1 与 `to` 0→1 是 `mobile phone*`/`due to*`/`ought to*` 切分后星号归末 token、`china` 合并 | 图像：`surf*`（p125）、`mobile phone*`（p108）、`chief*`（第一轮 p85）；本产出正确。3221 − 117 = 3104 即 INDEX 的「主表 3,104」 |
| `shanghai-secondary/07-yr7429/kaogang_graded.txt` | 3099（含标题 `I` 与词 `I` 各一行，第 1441–1442 行） | 0 | 0 | 0 | 完全一致；格式差别仅 `civilisation(civilization)`、`o’clock`（README §7 已写） |
| `shanghai-secondary/analysis/lists.json` → `kb3100` | 3091（0:1591 / 1:500 / 2:1000） | 0（按斜杠/括号备选形匹配） | 18：全部 `(=…)` 缩写条目（`ad`、`AI`、`app`、`bike`、`exam`、`fridge`、`gym`、`kilo`、`lab`、`maths`、`PE`、`photo`、`TV`）及 `be (am, are, is)`、`mother (mum, mom)`、`café`、`I`、`o'clock` | 0 | 与第一轮 §3 结论相同：500/1000 是切分伪象 |
| `verify-provinces/out/L3.txt` | 1611 token | 按备选形匹配后 8 个未命中（`e`、`fu`、`kung`、`metr`、`policemen`、`w`、`x`、`yogurt`，均为对方切分噪声） | — | 1603 命中中非 0 级只有 `cream`(2)、`per`(1)（`china` 对应 `China` 0） | README §5 的 1611/1603/1601 成立 |
| `shanghai-secondary/07-yr7429/3185.txt` | 用作者 `compare_more.py` 第 34 行的正则复现：3159 个编号 token、3157 个不同编号（0–3185） | README「3157 个编号词」可复现；「3020 在表内 / 442 星级不同」依赖其 `forms` 展开，本轮精确匹配得 2937 / 418，未逐一复现（口径问题，§13 #6） | | | 仅对照件，不影响产出 |

`shanghai-secondary/analysis/` 其余（`sh2020`、`nat_zk`、`nat_gk`）与 `list-sources/02/`（上海初中表）与本任务无关。

### 12.3 README / 文件头 provenance 核对

| 项目 | README / 文件头 | 核验依据 | 结果 |
|---|---|---|---|
| 2020 URL（zip、通知页）、zip 内文件名、220 页 | README 第 23 行；2020 TSV 第 2–3 行 | `facts/provinces.md` 第 30 行 [provinces-3]、第 179 行 [provinces-31] | 一致 |
| 2020 zip 38,598,043 字节、PDF 7,750,611 字节 | — | `ls`；facts 第 30 行 | 一致 |
| 2020 md5 `2398e946…`、zip `42762e0d…` | README 第 24 行；TSV 第 5–6 行 | `md5 -q` 实测 | 一致 |
| 2020 页码 PDF 129–186 = 印刷 121–178、主表 129–184、国家表 184–186、附录 3 自印刷 179 | README 第 25 行；TSV 第 7 行；附表第 2 行 | 本轮逐页文字层页脚（129→121、156→148、184→176）；`pdftotext -f 187` 首行「附录 3 语法项目一览」 | 一致 |
| 2020 `pdfinfo`（Founder PDF Library、2020-05-29、538.6×754.0 pt）、字体 | README 第 24 行 | `pdfinfo`、`pdffonts -f 129 -l 132`（FZ* CID TrueType + Times-Roman/Times-Bold/TimesNewRomanPS-BoldMT） | 一致 |
| 2025 URL、178 页、CreationDate 2025-10-31、无 Producer | README 第 28–29 行；TSV 第 2 行 | facts 第 36 行 [provinces-4]、第 180 行 [provinces-31]；`pdfinfo` | 一致 |
| 2025 md5 `77e8f0d7…`，两处副本相同 | README 第 29 行；TSV 第 4–5 行 | `md5 -q` 两文件 | 一致 |
| 2025 页码 PDF 76–135 = 印刷 73–132、主表 76–132、国家表 133–135、附录 3 自印刷 133 | README 第 30 行；TSV 第 6 行；附表第 2 行 | 文字层页脚（76→73、130→127、132→129、133→130）；`pdftotext -f 136` 首行「附录 3 语法项目表」 | 一致 |
| 2025 字体 FZZHUNYSK/FZSYK/FZDBSK + TimesNewRomanPSMT | README 第 29 行 | `pdffonts -f 76 -l 80`：FZSYK/FZXBSJW/FZHTJW/FZSSJW + TimesNewRomanPSMT/Times-Bold（文档级描述，与第一轮判断相同） | 一致 |
| 正式性声明、人教社期刊、xxgc 镜像线索 | README 第 31 行 | `verify/provinces.md` 第 35–37 行与第 143 行第 7 条；`07-yr7429/README.md` 第 7 行 | 一致 |
| kaogang 为 CC BY-SA、仅对照未复制 | README 第 52、96 行 | `07-yr7429/README.md` 第 338 行「词表内容 … CC BY-SA 4.0」 | 一致 |
| 获取日期 2026-11-05 | 各文件头 | facts 记录 | 一致 |
| 统一格式：`#` 注释头、UTF-8、LF、无 BOM、末尾单个 LF、列名在最后一行注释 | README 第 18 行 | §9 | 一致 |

## 13. 问题清单与建议修正

### #1（必须改，文档）README §8 第 104 行「5 对「二合一」」应为 4 对
- 证据：diff 第 579–580（`actor`/`actress`→`actor/actress`）、582–583（`anybody`/`anyone`）、591–592（`everybody`/`everyone`）、617–618（`somebody`/`someone`）行，共 4 个目标、8 个 2020 词条；48 对 − 44 个词形 = 4；README 第 135 行自己写的也是「≈ 节 4 个「二合一」目标」，`check-after.txt` 的 `duplicate keys` 亦为 4 个。`emperor→emperor/empress`、`host→host/hostess` 在 2020 侧只有 1 条，不是二合一；`prince/princess` 是 `+`。
- 修正：第 104 行「5 对「二合一」（`actor`+`actress` 等）在 2025 侧只对应 1 条」→「4 对「二合一」（`actor`+`actress`、`anybody`+`anyone`、`everybody`+`everyone`、`somebody`+`someone`）各在 2025 侧只对应 1 条」。

### #2（文档，低）README §9 第 6 条（第 114 行）与 §5 第 67 行「2025 版主表不含数词」过宽
- 2025 TSV 仍含 `zero`（第 3109 行）、`million*`（1747）、`billion**`（311）、`dozen**`（882）、`half`（1307）、`quarter`（2218）、`once`（1917）、`twice*`（2905）、`double`（876）；被删的是 `one`…`thousand`、`first`…`twentieth` 共 41 个基数/序数词（diff − 节），月份 12、星期 7 则确实全部删除。
- 修正：两处改为「不含 `one`…`thousand`、`first`…`twentieth` 的基数/序数词（`zero`、`million`、`billion`、`dozen`、`half`、`quarter`、`once`、`twice` 仍在）以及月份、星期」。

### #3（文档，低）README §7 第 95 行对 INDEX「3,104」的解释算式不成立
- 「3,104 为 docx 版按空白切分（`ice cream`、`kung fu`、`due to`、`ought to`、`mobile phone`、`per cent` 各计 2）」：3099 + 6 = 3105 ≠ 3104；实际 3,104 = `provinces/std2025rev_hs_words.txt` 3,221 个 token − 117 个国家表/表头 token（`prev2.py`），与 3,099 的差是「对方多 88 个切分 token + 18 个小写化形、本产出多 101 条带括号/斜杠/空格/大写词条」的净效应 +5，并非恰好 6 个多词词条各计 2。
- 修正：改为「3,104 = docx 版按空白/括号切分并小写化后的唯一 token 数（3,221 − 117 个国家表 token），与 3,099 的差为切分/合并的净效应」。

### #4（文档/一致性，低）2020 文件头校验页码与 README §6 表未纳入修正轮新核对的 2020 页
- 修正轮对 2025 侧把印刷 127 补进了 TSV 第 11 行与 §6 表（§10 #5），但 2020 侧同轮核对的印刷 124（PDF 132 左栏，§10 #1）与 148（PDF 156，§10 #7）只出现在 §6 正文与 §10，`moe-2020-senior.tsv` 第 14 行仍为「121、122、136、176」。
- 建议：第 14 行补「124（左栏）、148」，§6 表补两行，或在 §6 表下注明「另见 §10 第 1、7 条」。不影响内容正确性。

### #5（建议，差异文件语义）`humorous`/`humourous` 与 `Olympics`/`Olympic` 被记为 −/+
- 按 diff 第 2–4 行声明的规则这是正确结果（拼写/单复数差异不在宽松匹配内），README §9 第 4 条也已说明 `humourous` 是镜像拼写；但 §8 第 101–102 行把 `humorous` 列入「删除」、`humourous*` 列入「新增」，读者可能当作两个不同词。
- 建议：在 diff 第 4 行末或 README §8 补一句「`humorous`(0)→`humourous`(1)、`Olympics`→`Olympic` 为拼写/单复数变体，按规则记为 −/+」。可不改。

### #6（文档，极低）README §7 第 97 行 3185.txt 行的口径
- 「3157 个编号词」可用 `compare_more.py` 第 34 行正则复现（3159 token / 3157 编号）；「3020 个在本次 2025 表内」「442 条星级不同」依赖其 `forms` 展开匹配，精确匹配为 2937 / 418。建议括注匹配口径（「按括号/斜杠备选形、大小写不敏感匹配」）。可不改。

## 14. 不需改动的观察

1. 第一轮 §6 的 5 条观察仍成立（`million` 是唯一 2→1；2025 镜像 3099/502/997 与 kaogang 独立提取一致；数词/月份/星期不在 2025 主表——以 #2 的精确表述为准；不可见页脚；2020 `a.m.`/`p.m.` 位置为原文）。
2. 2025 版 `p.m.` 仍在 `plus` 之后（TSV 第 2082→2083 行），只有 `a.m.` 被移到表首（第 13 行）——两处都是原文排列，不是解析错误。
3. `− AD`/`+ CE (Common Era)`、`− March`/`− May`/`− US`（2025 只保留小写 `march*`、`may`、`us`）是声明规则下的正确结果，语义上也对（月份与国名缩写被删、普通词保留）。
4. `check_lists.py` 把首个以 `word`/`country_zh` 开头的非注释行当表头，`order_rule.py` 跳过 `word\t` 开头行——修正 #9 后这两个分支不再触发，但不影响结果。
5. 第一轮报告 §1 表中「+1 表头行」、§0 的「status = fix」描述的是修正前的产出，已被本轮取代；因 README §10 引用「第一轮 §5 的 7 项问题」，第一轮正文原样保留在上方。

## 附：本轮产生的文件
- `scratchpad/verify2-senior/struct2.py`、`parse2.py`、`diff2.py`、`table2.py`、`prev2.py`；`txt/e2020-{129..186}.txt`、`txt/h2025-{76..135}.txt`（逐页 layout 文字层）；`my2020.tsv`、`my2025.tsv`（词、级别、PDF 页、栏、行号）。
- `scratchpad/verify2-senior/img/`：2020 PDF 132/136/138/141/149/154/156/180 与 2025 PDF 78/79/99/103/108/125/130 的左右栏裁剪图（30 幅）及 2025 PDF 133 上部。
- 未修改 `data/lists/` 下任何文件；仓库跟踪文件 0 处改动；未读写线上数据目录；未联网。
