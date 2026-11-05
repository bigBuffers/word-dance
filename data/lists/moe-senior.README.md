# moe-senior — 国家高中英语课程标准词汇表（2020 版 3000 词 / 2025 修订版 3100 词）

生成日期 2026-11-05；仓库基线 main @ 75df534。解析脚本与中间文件在
`/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/lists-senior/`
（`parse_list.py`、`parse_table.py`、`build_outputs.py`、`compare_prev.py`、`compare_more.py`，页面图像在 `img/`）。
2026-11-06 按核验报告 `docs/analysis/2026-11-05-stages-regions-images/lists-verify/moe-senior.md` 修正，修正记录见 §10；复核脚本与页面图像在同级目录 `lists-senior-fix/`（`check_lists.py`、`order_rule.py`、`apply_fixes.py`，图像 `img/`）。

## 1. 文件

| 文件 | 内容 | 行数（不含 `#` 注释） |
|---|---|---|
| `moe-2020-senior.tsv` | 《普通高中英语课程标准（2017 年版 2020 年修订）》附录 2 词汇表主表，`word<TAB>level` | 3000 |
| `moe-2020-senior-appendix.tsv` | 同书附录 2 末尾「主要国家名称及相关信息（供教学参考）」表，`country_zh<TAB>country<TAB>person<TAB>adjective` | 55 |
| `moe-2025rev-senior.tsv` | 《普通高中英语课程标准 日常修订版（2017 年版 2025 年修订）》附录 2 词汇表主表，同上格式 | 3099 |
| `moe-2025rev-senior-appendix.tsv` | 同书「部分国家名称及相关信息（供教学参考）」表 | 56 |
| `moe-senior-2020-vs-2025.diff.txt` | 2025 修订版相对 2020 版的 + 新增 / - 删除 / ~ 星级变化 / ≈ 词形改写，附国家附表差异 | +196 / -93 / ~273 / ≈48 |

格式：UTF-8、LF、无 BOM；文件头 `#` 注释记录来源 URL、本地副本 md5、页码、规则与计数，最后一行注释给出列名（`# word<TAB>level`；附表 `# country_zh<TAB>country<TAB>person<TAB>adjective`）。**没有非注释的表头行**：第一条非注释行就是第一个词条（与同目录 `shmeea-*.tsv`、`moe-2022-appendix.tsv` 的写法一致，见 §10 第 9 条）。`level` 列：`0` 无星、`1` 一个 `*`、`2` 两个 `*`（含义见 §3）。词条顺序 = PDF 阅读顺序（左栏→右栏、逐页），不另排序。

## 2. 来源与可信度

### 2020 版（官方，有文字层）
- 教育部教材〔2020〕3 号通知附件 zip `http://www.moe.gov.cn/srcsite/A26/s8001/202006/W020200603315372317586.zip`（通知页 `http://www.moe.gov.cn/srcsite/A26/s8001/202006/t20200603_462199.html`），zip 内 `4.普通高中英语课程标准（2017年版2020年修订）.pdf`，220 页——依据 `docs/analysis/2026-11-05-stages-regions-images/facts/provinces.md` [provinces-3]、[provinces-31]。
- 本地副本 `scratchpad/provinces/dl-moe2020/zip/english-2020.pdf`，`md5 -q` = `2398e9465bac25444a30db7f07a025cc`（zip `std2020.zip` = `42762e0d75efede84e96375deb19c333`），获取日期 2026-11-05（facts 记录）。`pdfinfo`：Founder PDF Library，CreationDate 2020-05-29，538.6×754.0 pt；`pdffonts`：方正字库 CID TrueType + Times-Roman，全部内嵌，有 Unicode 映射。
- 附录 2 在 PDF 第 129–186 页 = 印刷页 121–178：主表 121–176（第 129–184 页），国家表 176–178（第 184–186 页，与主表末尾同页起始）；附录 3「语法项目一览」从印刷页 179 起。

### 2025 修订版（非官方镜像，有文字层）
- `https://forum.freemdict.com/uploads/short-url/doVmJXenSoIbcg8t5HA0hkWcccm.pdf`，178 页——依据 facts [provinces-4]、[provinces-31]。封面「普通高中 英语课程标准 日常修订版（2017 年版 2025 年修订）」。
- 本地副本 `scratchpad/provinces/dl-freemdict-hs-pdf/hs2025.pdf`，md5 = `77e8f0d793808e59c18dc89fa5f169d6`；`scratchpad/verify-shanghai-secondary/gkstd2025/std2025.pdf` 为同一文件（md5 相同）。获取日期 2026-11-05。`pdfinfo`：CreationDate 2025-10-31，无 Producer 字段；字体 FZZHUNYSK/FZSYK/FZDBSK + TimesNewRomanPSMT。
- 附录 2 在 PDF 第 76–135 页 = 印刷页 73–132：主表 73–129（第 76–132 页），国家表 130–132（第 133–135 页）；附录 3「语法项目表」从印刷页 133 起。
- **正式性声明**：moe.gov.cn 未检索到该修订版的印发通知（facts [provinces-4]；`verify/provinces.md` 第 7 条：人教社《课程·教材·教法》2026(5) 已以其为研究对象，故标为「学界已采用、文号未见」）。文件来自论坛上传，不能排除转录/重排误差；本次发现的文本层与版面不一致之处见 §9 第 3 条。另一镜像线索：`shanghai-secondary/07-yr7429/README.md` 称其课标下载自 `https://www.xxgc.edu.cn/fll/info/1061/5288.htm`（未核验）。

## 3. `*` 的含义（以 PDF 原文为准）

两版附录 2「说明」第 1 条原文（2020 印刷页 121 / 2025 印刷页 73，均已用页面图像核对）：

- 2020：「本词汇表共收 3000 个单词，含义务教育阶段要求掌握的 1500 个单词。高中英语必修课程应学习和掌握 500 个单词（表中加有一个 * 号），累计达 2000。选择性必修课程应学习和掌握 1000 个单词（表中加有两个 * 号），累计达 3000。各地可根据实际情况在本词汇表所收词的基础上，再选择增加 200 个单词。」
- 2025：「本词汇表共收录 3100 个单词，含《义务教育英语课程标准（2022 年版）》所列义务教育阶段要求掌握的 1600 个单词。高中英语必修课程应学习和掌握 500 个单词（表中加有一个 * 号），累计达 2100。选择性必修课程应学习和掌握 1000 个单词（表中加有两个 * 号），累计达 3100。各地可根据实际情况在本词汇表所收词的基础上，再选择增加 200 个单词。」

因此 **`0` = 无星 = 义务教育阶段已要求掌握（2020 版按 2011 课标 1500 词，2025 版按 2022 课标 1600 词）；`1` = `*` = 高中必修新增 500 词；`2` = `**` = 选择性必修新增 1000 词**。任务说明中「无标记 = 必修、★ = 选择性必修、★★ = 选修（提高类）」与原文不符：选修（提高类）的 1000 词（2020 版「累计掌握 4000~4200」，facts [provinces-3]）**不在**附录词表内。国家表无星级（说明第 7 条「单独列出，供教学参考」）。

星号在两份 PDF 的文字层里都是普通 ASCII `*`（非图形），页面图像中亦显示为上标星号，已逐页核对（§6）。

## 4. 解析方法

1. `pdftotext -layout` 全文定位附录页码；`pdftotext -bbox-layout -f … -l …`（poppler 26.10.0）导出附录页每一行的坐标与文本。
2. 主表（`parse_list.py`）：每页取不含 CJK、非纯数字的行 → 按 x 坐标聚类分左右栏（栏距 >100 pt）→ 各栏按 y 排序，左栏先于右栏 → 字母标题行按字高识别（2020：18.7 vs 13.4 pt；2025：16.6 vs 16.2 pt）并与字母顺序 A→Z 交叉校验（词 `I` 与标题 `I` 相邻，靠字高+顺序区分）→ 2020 版最后一页以英文表头 `COUNTRY n.` 的 y 坐标截断，其下归国家表。
3. 词尾 `*`/`**` 剥离为级别，含空格分隔的星号（2020：`directory **`；2025：`behalf **`、`belief **`、`chef **`、`chief *`、`staff *`、`stuff *`、`surf *`）。
4. 跨行词条合并（括号未闭合或下一行缩进）：仅 2020 版 `kilo (kilogramme, kilogram)` 一例（印刷页 148）。
5. 规范化只做三件事：多空格折叠；`a / b` → `a/b`（2020 版 `bride / bridegroom` 等 4 条、2025 版 `Frenchman/ Frenchwoman`）；弯引号 `’` → `'`（`o'clock`、国家表 `People's`）。其余原样：英式拼写与括号内美式变体（`colour (color)`）、并列形式（`a (an)` / `a/an`、`actor/actress`）、括号注（`child (pl. children)`、`ad (=advertisement)`、`according (to)`）、大小写（`I`、`May`/`may`、`March`/`march`、`China`/`china`、`AD`、`PE`、`TV`）、缩写句点（`a.m.`、`Mr (Mr.)`）、重音（`café`）、连字符（`X-ray`、`T-shirt`、`Wi-Fi`、`ping-pong`、2020 版 `ice-cream`）。
6. 国家表（`parse_table.py`）：以英文表头 `COUNTRY n.` / `PERSON n.` / `RELATED ADJECTIVES` 的 x 坐标定列，以中文国名行为行锚，跨行单元格（`Frenchman / Frenchwoman`、`U.K.=the United Kingdom`、`Democratic People's Republic of Korea—DPRK`）按 y 就近合并。2025 版文字层「阿根廷」缺「廷」字，按印刷页 130 图像补正。
7. 未使用网络；之前 agent 的解析结果只作对照（§7），未复制 `shanghai-secondary/07-yr7429/`（CC BY-SA）的任何内容。

词条形态统计（规范化后的产出；「多词」= 去掉括号注后仍含空格）：2020 版 57 条带括号、4 条带 `/`（`bride/bridegroom`、`chairman/chairwoman`、`policeman/policewoman`、`salesman/saleswoman`，原文 `x / y` 已折为 `x/y`，不计入多词）、5 条多词（`according to`、`bean curd (tofu)`、`due to`、`mobile phone`、`ought to`）、69 条首字母大写；2025 版 59 条带括号、12 条带 `/`、6 条多词（`due to`、`ice cream`、`kung fu`、`mobile phone`、`ought to`、`per cent (percent)`）、29 条首字母大写。

## 5. 计数与官方口径

| | 总数 | 无星 (0) | `*` (1) | `**` (2) | 官方说明 |
|---|---|---|---|---|---|
| 2020 主表 | **3000** | 1500 | 499 | 1001 | 3000 = 1500 + 500 + 1000 |
| 2025 主表 | **3099** | 1600 | 502 | 997 | 3100 = 1600 + 500 + 1000 |
| 2020 国家表 | 55 行 | | | | — |
| 2025 国家表 | 56 行（+沙特阿拉伯） | | | | — |

- 2020 版总数与无星数与官方完全一致，一星/两星各差 1：文档中某一条应为 `*` 却印作 `**`（或官方数字为约数），无法从文本判定是哪一条。
- 2025 版比官方 3100 少 1，一星多 2、两星少 3。YR7429 项目对同一 PDF 的独立提取 `kaogang_graded.txt` 也是 3099 条、1600/502/997（§7），说明偏差在镜像文件本身而非本次解析。
- 2025 版无星 1600 词与 2022 版义务教育三级词表基本重合：对照之前解析的 `verify-provinces/out/L3.txt`（1611 个 token，含噪声），1603 个出现在 2025 主表，其中 1601 个为级别 0；例外 `cream`（来自 `ice cream` 的切分，2025 另有 `cream**`）、`per`（来自 `per cent`）。L3.txt 与 2025 主表都不含 `one`…`thousand`、`first`…`twentieth` 共 41 个基数/序数词，也不含月份、星期名；但 `zero`、`half`、`quarter`、`once`、`double` 两边都有，`million`、`billion`、`dozen`、`twice` 另见于 2025 主表（见 §9 第 6 条）。

## 6. 校验

页面图像（`pdftoppm -r 220`）与解析结果逐词、逐星核对，全部一致：

| 版本 | PDF 页 | 印刷页 | 内容 | 结果 |
|---|---|---|---|---|
| 2020 | 129 | 121 | 附录 2 说明 + 首页 16 词（含 `a (an)`、`abandon**`、`absolutely*`） | 一致 |
| 2020 | 130 | 122 | 56 词，大量 `**`，`according to`、`advertisement (ad)**`、`AD**` | 一致 |
| 2020 | 144 | 136 | `directory **`（空格分隔的两星）等 56 词 | 一致 |
| 2020 | 184 | 176 | 主表末页 13 词 + 国家表前 13 行（`DPRK=Democratic People's Republic of Korea`） | 一致 |
| 2025 | 76 | 73 | 附录 2 说明 + 首页 19 词（`a.m.`、`a/an`） | 一致 |
| 2025 | 77 | 74 | 56 词，`according (to)`、`actor/actress`、`ad (=advertisement)`、`Africa*` | 一致 |
| 2025 | 101 | 98 | `humour (humor)`、`humourous*`、标题 `I` 与词 `I`、`ice cream` | 一致（`humourous` 确为印刷原文） |
| 2025 | 130 | 127 | 53 词：左栏 `video`…`voyage**` 24 词 + 标题 `W` + `wage**`，右栏 `waist**`…`web*` 28 词（TSV 第 2958–3010 行） | 一致（原已渲染 `lists-senior/img/h2025-p130-130.png` 而漏列；2026-11-06 用 `lists-senior-fix/img/h2025-p130-{L,R}-130.png` 逐词逐星复核） |
| 2025 | 132 | 129 | 主表末页 45 词（`X-ray`、`yield**`、`zone**`） | 一致 |
| 2025 | 133 | 130 | 国家表首页 21 行（图像显示「阿根廷」，文字层缺「廷」） | 一致（已补正） |

修正轮（2026-11-06，§10）另用图像核对了 2020 版印刷页 124（PDF 132，左栏 `application*`，§10 第 1 条）与 148（PDF 156，`kilo (kilogramme, kilogram)` 跨行词条所在页，§10 第 7 条），结果一致；这两页未列入上表，`moe-2020-senior.tsv` 文件头的校验页码（121、122、136、176）亦未含它们。

其他一致性检查：每页词条数符合版面（满页 28 行×2 栏 = 56，含字母标题的页 54/52；2020 第 156 页左栏 26 + 右栏 23（右栏另含字母标题 `K` 与 1 个续行 `kilogram)`）= 49，2025 第 130 页左 25（含标题 `W`）+ 右 28 = 53，均用行坐标确认无遗漏）；字母序检查仅有源文件自身的排列（如 2025 印刷页 88 `dish` 后接 `disc (disk)**`——2020 版在该位置为 `disk (disc)**`，2025 换了主词形但未移动位置）；两版各只有一个 `I` 词条；无重复词条。

## 7. 与之前各次解析的差异

| 对照文件 | 规模 | 与本次的差异 | 原因 |
|---|---|---|---|
| `verify-provinces/out/H2020.txt`（词\t级别） | 2997 | 本次多 `according to`、`due to`、`ought to`、`mobile phone`、`bean curd (tofu)`、`café`、`o'clock`；对方多 `according`/`curd`/`due`/`mobile`/`ought` 等单 token；27 条级别不同 | 对方按空白切分多词词条并丢弃非 ASCII 词；先去星再处理括号，使 `advertisement (ad)**`、`analyse (analyze)**`、`directory **` 等 24 条带括号/空格的词条丢星；`China`/`china*`、`March`/`march*` 小写合并后取无星 |
| `provinces/std2020_hs_words.txt` | 3004 | 同上，另含国家表 token（`frenchman`、`korea`、`united`、`states`、表头 `related`、`adjectives`） | 对方未把国家表与主表分开 |
| `provinces/std2025rev_hs_words.txt` | 3221 | 对方多 117 个国家/国籍 token 与表头 token、`due`/`ought`/`kung`/`fu` 等切分 token；本次多 `due to`、`ice cream`、`kung fu`、`mobile phone`、`ought to`、`per cent (percent)`、`X-ray`、`café`、`o'clock`；29 条级别不同（`behalf **`、`chief *`、`staff *` 等空格星号被丢） | 同上 |
| `INDEX.md` §3 第 11 条 / `verify/provinces.md` [provinces-4] 修正：主表 3,104、新增 ≈205 | — | 本次 3,099 / 新增 196 | 3,104 = `provinces/std2025rev_hs_words.txt` 的 3,221 个 token − 117 个国家表/表头 token（docx 版按空白/括号切分并小写化后的唯一 token）；它与本产出 3,099 的差是切分（+88）+ 小写化（+18）− 本产出带括号/斜杠/空格/大写的词条（−101）的净效应（+5）；新增 205→196 因本次把 `ice-cream`→`ice cream`、`Internet`→`internet`、`toward(s)`→`towards (toward)`、`practice`→`practise (practice)`、`percent`→`per cent (percent)`、`bean curd (tofu)`→`tofu (bean curd)`、`television (TV)`→`TV (=television)`、`advertisement (ad)`→`ad (=advertisement)`、`disk (disc)`→`disc (disk)` 记为词形改写而非新增（`app (=application)` 仍计为新增：`application*` 在两版主表均存在，见 §10 第 1 条） |
| `shanghai-secondary/07-yr7429/kaogang_graded.txt`（CC BY-SA，仅对照） | 3099 | 词条与级别**完全一致**（仅两处格式差别：`civilisation(civilization)` 无空格；`o’clock` 用弯引号——本产出已规范化为 `o'clock`） | 同一 PDF 的独立提取 |
| `shanghai-secondary/07-yr7429/3185.txt`（CC BY-SA，仅对照） | 3157 个编号词 | 3020 个在本次 2025 表内；缺的 137 个是 OCR 噪声（`l00k`、`Z00`、`0bey`）和只见于 2020 版的词（月份、数词、国名）；442 条星级不同（3020 与 442 的口径是 `compare_more.py` 的 `forms` 展开匹配——按括号/斜杠备选形展开、大小写不敏感；若只做整条精确匹配，则按不同词计为 2935 个在表内、418 条星级不同，按 3159 个编号 token 计为 2937 / 418） | 该文件是作者的「原始资料」，看起来基于 2020 版词表加补充，不是 2025 版的干净提取 |

## 8. 2025 修订版相对 2020 版的变化（详见 diff 文件）

- **新增 196**（级别 0: 48，1: 74，2: 74）：如 `AI (=artificial intelligence)`、`app (=application)`、`drone*`、`alert**`、`bacteria*`、`bias**`、`brand*`、`bully`、`capture*`、`collaborate*`、`confident*`、`currency**`、`empathy**`、`gene**`、`heritage*`、`patriotism*`、`rejuvenate**`、`socialism`、`teamwork`、`wetland*`；196 条中的 `humourous*`（1）与 `Olympic`（0）只是 2020 版 `humorous`、`Olympics` 的拼写/单复数变体，并非真正的新增（见下「删除」）。
- **删除 93**（级别 0: 89，2: 4）：基数/序数词 `one`…`thousand`、`first`…`twentieth`（共 41 个）、12 个月份、7 个星期、国名/国籍词（`African`、`American`、`Asian`、`Australia(n)`、`Britain`、`British`、`Canada`、`Canadian`、`England`、`European`、`France`、`French`、`German(y)`、`India(n)`、`Japan(ese)`、`London`、`Russia(n)`、`UK`、`US`），以及 `crayon`、`pupil`、`swimming`、`humorous`、`Olympics`（后两者是拼写/单复数变体：2025 版作 `humourous*`、`Olympic`，在「新增」中另记为 +，并非真正的删除）；两星词 `AD`、`BC`（改为 `CE (Common Era)**`、`BCE (Before the Common Era)**`）、`cheek`、`foggy`（新增 `fog`）。
- **星级变化 273**：`1→0` 136 条、`2→0` 71 条（如 `astronaut`、`biology`、`emergency`、`laptop`、`virus`）、`0→1` 65 条（如 `Africa*`、`Asia*`、`Europe*`、`Pacific*`、`agreement*`、`communication*`、`national*`）、`2→1` 1 条（`million`）。方向与基线从 2011 版 1500 词换成 2022 版 1600 词一致。
- **词形改写 48**：`a (an)`→`a/an`、`according to`→`according (to)`、`actor`+`actress`→`actor/actress`、`emperor`→`emperor/empress`、`Mr`→`Mr (Mr.)`、`behaviour (behavior)`→`behaviour`（删美式变体）、`grey`→`grey (gray)`、`Internet`→`internet` 等。口径：≈ 收录**所有已匹配但全文不同**的对，包括第 (1) 步首词形相同而括号注变化者（`child (pl. children)`→`child` 等）；4 对「二合一」（`actor`+`actress`、`anybody`+`anyone`、`everybody`+`everyone`、`somebody`+`someone`）在 2025 侧各只对应 1 条，故 48 对的 2025 词形只有 44 个（48 − 4）。~（273）只统计首词形相同的级别变化，其中 `emperor/empress`、`gym (=gymnasium)`、`host/hostess`、`medium` 4 条同时出现在 ≈ 节；≈ 中首词形不同且级别变化的 3 对（`advertisement (ad)`→`ad (=advertisement)` 2→0、`percent`→`per cent (percent)` 1→0、`bean curd (tofu)`→`tofu (bean curd)` 2→0）不计入 273。划分检验：2020 侧 全文相同 2859 + ≈ 48 + 删除 93 = 3000；2025 侧 2859 + 44 + 新增 196 = 3099。
- **国家表**：新增 `沙特阿拉伯 Saudi Arabia / Saudi Arabian / Saudi Arabian`；`Turkey`→`Türkiye`、`Viet Nam`→`Vietnam`、`Netherlands/Holland`→`Netherlands`、波兰 PERSON `Pole`→`Polish`；缩写写法由 `DPRK=…`/`ROK=…`/`U.K.=…`/`U.S.A.=…` 改为 `…—DPRK`/`…—ROK`/`the United Kingdom—UK`/`the United States of America—USA`。

## 9. 仍不确定的条目与注意事项

1. 2020 版一星 499 / 两星 1001（官方 500/1000）：无法判定哪一条星号有误；按原文输出。
2. 2025 版 3099 / 502 / 997（官方 3100/500/1000）：镜像文件本身如此（独立提取结果相同）；与正式印刷本是否一致待核。
3. 2025 镜像的文字层含页面上不可见的页脚文字（如印刷页 74、129 的文字层有「普通高中英语课程标准（2017 年版 2025 年修订）」「│ 附录 │」而渲染图像只有页码），且「阿根廷」缺字——说明文件经过转换/重排，不是出版社印刷 PDF；词表内容已逐页抽检，但整体仍应标为「镜像」。
4. `humourous*`（2025 印刷页 98）为镜像原文拼写（2020 版为 `humorous`，标准拼写亦为 humorous）；按原文保留，种子阶段应决定是否归一。
5. 2025 印刷页 88 `disc (disk)**` 排在 `dish` 之后（沿用 2020 版 `disk (disc)**` 的位置）；按原文顺序保留。
6. 2025 版主表相对 2020 版删去了 `one`…`thousand`、`first`…`twentieth` 共 41 个基数/序数词，以及全部 12 个月份、7 个星期（小写的 `march`、`may` 是另外的词，仍在表内）；但 `zero`、`million*`、`billion**`、`dozen**`、`half`、`quarter`、`once`、`twice*`、`double` 仍在表内，所以 2025 版主表并非完全没有数词。2022 版义务教育三级词表的早先解析 `L3.txt` 同样不含这 41 个词和月份、星期，推断 2022 课标把它们列在字母表之外（未在本任务中核对 2022 PDF，置信中）。种子构建若需要这些词，应另取来源。
7. 规范化：`’`→`'`（线上库 `words.lemma` 用 `o'clock`）、`a / b`→`a/b`；`café` 保留重音（库中为 `cafe`），由种子阶段折叠。
8. 拆分规则留给种子构建阶段。建议：`/` 并列拆为多词头；`(=X)` 为缩写展开、`(pl. X)` 为复数、`(X)` 为英美/变体拼写或别名（`father (dad)`）、`be (am, are, is)` 为屈折形式、`according (to)`/`toward(s)` 为可选成分，需分别处理；国家表三列各自成词头，`Frenchman/Frenchwoman` 拆开，`the United Kingdom—UK` 取 `the United Kingdom` 与 `UK`。
9. 大小写同形词在同一版内是不同词条（2020：`March`/`march*`、`May`/`may`、`China`/`china*`；2025：`China`/`china*`），合并时须保留级别较高者或分别入库。

## 10. 核验修正（2026-11-06）

依据 `docs/analysis/2026-11-05-stages-regions-images/lists-verify/moe-senior.md` §5 的 7 项问题逐条修正；每条先用原件页面图像或文字层再次确认（图像由 `pdftoppm -r 220` 渲染到 `scratchpad/lists-senior-fix/img/`，文字层由 `pdftotext -layout` 导出到 `lists-senior-fix/txt/`；两份 PDF 的 md5 仍为 `2398e9465bac25444a30db7f07a025cc`、`77e8f0d793808e59c18dc89fa5f169d6`）。词条内容与星级**没有任何改动**：两版主表仍为 3000（1500/499/1001）与 3099（1600/502/997），国家表 55 / 56 行。

| # | 文件 | 改动 | 依据 |
|---|---|---|---|
| 1 | `moe-senior-2020-vs-2025.diff.txt` | 删除 `≈ application -> app (=application) (1->0)`（原第 583 行）；在「+ 2025 版新增」节插入 `+ app (=application)\t0`（现第 13 行，`+ Antarctica` 之后、`+ Arctic` 之前） | 2020 PDF 132 页（印刷 124）左栏 `application*`；2025 PDF 79 页（印刷 76）左栏同时有 `app (=application)`（无星）与 `application*`（图像 `e2020-p132-L-132.png`、`h2025-p079-Ltop-079.png`、`h2025-p079-Lbot-079.png`；文字层 `txt/e2020-app.txt`、`txt/h2025-app.txt`）。`application`(1) 已在第 (1) 步精确匹配，第 (2) 步又把 2025 `app (=application)` 的括号内容对到它上面，属重复匹配；`app (=application)` 实为新增。插入位置：核验报告建议放在 `+ anniversary` 之后、`+ Antarctica` 之前，但 ann < ant < app，该节实际按 2025 版原文顺序（= 大小写不敏感字母序）排列（2025 TSV 中 `anniversary` 133 行、`Antarctica` 140 行、`app (=application)` 154 行、`Arctic` 171 行），故放在 `+ Antarctica` 之后（`order_rule.py` 复核各节顺序：+/~/≈ 节与 2025 原文顺序 0 处倒置、- 节与 2020 原文顺序 0 处倒置） |
| 2 | 同上 | 计数：第 5 行小结 新增 195→196（级别 0: 47→48）、词形改写 49→48；第 8 行标题（196）、第 576 行标题（48） | `check_lists.py` 重算：+ 196 = 48/74/74；- 93 = 89/0/4；~ 273（1→0 136、2→0 71、0→1 65、2→1 1）；≈ 48 对、2025 侧 44 个词形；划分 2859 + 48 + 93 = 3000、2859 + 44 + 196 = 3099，无遗漏、无重复匹配 |
| 3 | 同上 | 第 4 行口径改为「≈ = 已匹配但全文不同的所有对（含第 (1) 步首词形相同者）；~ = 首词形相同且级别变化，可与 ≈ 重叠（4 条）；首词形不同的级别变化 3 对不计入 ~」；第 6 行补各节排列顺序说明 | 脚本枚举：≈ 中与 ~ 重叠的恰为 `emperor/empress`、`gym (=gymnasium)`、`host/hostess`、`medium`；首词形不同且级别变化的为 `advertisement (ad)`→`ad (=advertisement)`、`percent`→`per cent (percent)`、`bean curd (tofu)`→`tofu (bean curd)`（修正 #1 后 `application` 不再在列） |
| 4 | `moe-senior.README.md` | §1 表 `+196 / -93 / ~273 / ≈48`；§7 INDEX 对照行删去 `application`→`app (=application)`，205→196；§8 新增 196（级别 0: 48）、词形改写 48 并补 ≈/~ 口径 | 同 #1–#3 |
| 5 | `moe-2025rev-senior.tsv` 第 11 行 | 校验页码「73、74、127、129」→「73、74、98、127、129、130」，并注明 130 为国家表首页（130–132） | 与 §6 表一致；印刷页 127（PDF 130）原已渲染但未列入 §6，本次用左右栏图像逐词逐星复核 53 词（TSV 2958–3010 行）并补入 §6 |
| 6 | README §4 词条形态统计 | 2020「8 条多词」→「5 条多词」（`according to`、`bean curd (tofu)`、`due to`、`mobile phone`、`ought to`；4 条 `x / y` 已折为 `x/y` 不计）；2025「5 条」→「6 条」（补 `per cent (percent)`） | `check_lists.py` 按「去括号注后含空格」统计：2020 = 5、2025 = 6；带括号 57/59、带 `/` 4/12、首字母大写 69/29 复算一致 |
| 7 | README §6 | 「2020 第 156 页 26 行×2 − 1 跨行 = 49」（算式 = 51）→「左 26 + 右 23（右栏另含标题 K 与 1 个续行 `kilogram)`）= 49」 | 图像 `e2020-p156-L-156.png`（`jam**`…`justify**` 26 行）、`e2020-p156-R-156.png`（标题 `K`、`kangaroo*`…`knowledge` 23 词、`kilo (kilogramme,` / `kilogram)` 跨两行）；文字层同页左 26 行、右 25 行（含标题与续行）；TSV 第 1470–1518 行 = 49 条 |
| 8 | README §7 kaogang 对照 | 「唯一差别 `civilisation(civilization)` 无空格」→ 补 `o’clock` 弯引号（本产出规范化为 `'`） | `kaogang_graded.txt` 第 544 行 `civilisation(civilization)**`、第 1955 行 `o’clock`（U+2019）；本产出 2025 TSV 第 537、1902 行 |
| 9 | 四个 TSV | 非注释表头行 `word\tlevel`（2020 第 15 行、2025 第 12 行）与 `country_zh\tcountry\tperson\tadjective`（附表第 5 / 6 行）改为注释 `# word\tlevel`、`# country_zh\t…`（保留原位置、真实制表符），与 `shmeea-2020-junior-*.tsv`（`# word\tsection\tnote`、`# headword\tkind\tprinted\twhere`）和 `moe-2022-appendix.tsv`（`# 类别\t词\t附加1\t附加2`）的写法一致 | 现在非注释行数 = 词条数：3000 / 3099 / 55 / 56（`grep -vc '^#'`）；核验报告 §1 表中的「+1 表头行」自此不再适用 |

修正后复核（`check_lists.py`、`order_rule.py`，`python3.12 -I`）：两版主表无完全重复词条，大小写不敏感同形仅原文如此的 `China/china` 等；字母序断点 2020 版 0 处、2025 版 3 处（`a.m.`→`a/an`、`dish`→`disc (disk)`、`per cent (percent)`→`per`，均为原文排列，同 §6）；diff 各节无重复键（≈ 节 4 个「二合一」目标重复为有意合并），+/~/≈ 节与 2025 原文顺序、- 节与 2020 原文顺序均无倒置；全部文件 UTF-8、LF、无 BOM、末尾单个换行。未改动的已知差异：2020 版 499/1001 与 2025 版 3099/502/997 仍按原文输出（§9 第 1、2 条）。
