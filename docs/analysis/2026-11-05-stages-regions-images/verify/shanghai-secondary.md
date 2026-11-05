# 核验：`facts/shanghai-secondary.md`（上海初中/高中词汇要求 vs 本项目词表）

slug：`verify-shanghai-secondary` · 基线：main @ 75df534 · 日期：2026-11-05 · 立场：对抗性复核，只读仓库，不改代码。

## 范围与方法

**读过的文件**：被核验文件 `docs/analysis/2026-11-05-stages-regions-images/facts/shanghai-secondary.md` 全文（23 条结论，全部复核）；仓库 `scripts/build_seed.py`（1–60、75–100、195–225）、`backend/wd/seed.py`（35–70、180–215）、`backend/wd/schemas.py`（25、45–70）、`docs/SCHEMA.sql`（140–195）、`backend/wd/migrations/0001_init.sql`、`frontend/src/i18n/zh.ts`（20–30、84–88）、`frontend/src/api/types.ts`（5、40–50）、`frontend/src/pages/WelcomePage.tsx`（30–40）、`frontend/src/components/word/StageChips.tsx`、`backend/wd/ai/content.py`（45–52）、`backend/wd/services/bank.py`（83–90）、`docs/DESIGN.md:330`、`docs/API.md`、`data/seed/ATTRIBUTION.md`、`data/seed/stats.json`；全库 `grep -rn` 复查阶段硬编码（`BETWEEN 1 AND 4|"cet6"|STAGES|STAGE_NAMES|stage_to_index|stages_json|current_stage`）与地区概念（`上海|Shanghai|省份|province|地区版|region`）。

**作者的下载与脚本**（只读复用，视为不可信数据）：`/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/shanghai-secondary/` 下的 `01-mahavivo/*`、`02-mahavivo-sh2020pdf/sh_junior_2020.pdf`、`05-zhongkao-words-json/entries_*.json`、`07-yr7429/*`、`txt/*.txt`、`analysis/parse_sh.py`、`analysis/compare2.py`、`analysis/compare2_output.txt`、`analysis/sh2020_words.json`。sha256 前 16 位与作者表一致（zhongkao.txt f2f67792e3c9f35e、Highschool_edited.txt 974f29c3ed2252ad、sh_junior_2020.pdf 11f7bdb6eaba225e、kaogang_graded.txt f003d0fbf2570508）。

**我自己的计算**（脚本放在 `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/verify-shanghai-secondary/`，用 `python3 -I` 以绝对路径读取数据，不在下载目录内运行）：`recount.py`——**独立重写**上海 PDF 文本解析（规则：取 pdftotext 输出中顶格行的首个词条，先去掉每页开头的换页符 `\f`，词头止于词性标记/CJK/`&`/`(`；`/`、`=` 并列拆成两个词头），再按 `scripts/build_seed.py:20-48` 的 `parse_list` 逻辑解析两份 mahavivo 词表，加载 zhongkao-words JSON 与 YR7429 词表，求交并集，并以 `ATTACH 'file:live-copy.db?mode=ro'` 对线上只读副本做 JOIN；输出存 `recount_output.txt`、`sh2020_mine.json`。`vocab2025.py`——解析我下载的 2025 修订版高中课标 PDF 附录 2，与 YR7429 的 `kaogang_graded.txt` 逐词比对。PDF 元数据/转文本用 poppler `pdfinfo`/`pdftotext`（只读解析器，与作者相同的唯一偏离）。sqlite3 直接查询：`SELECT count(*) FROM words; SELECT sum(stage_zk),sum(stage_gk),sum(stage_cet4),sum(stage_cet6) FROM words; SELECT stage_min,count(*) FROM words GROUP BY 1;` → 9162；2099/3829/4722/7671；1:2099 2:1792 3:1577 4:3694（与作者及 `stats.json` 一致；`lemma` 全小写、9162 个唯一）。

**我的下载**（各自独占新目录）：`verify-shanghai-secondary/gh/`（GitHub API 响应，全部被限流 `API rate limit exceeded`，仅 search 接口成功）、`verify-shanghai-secondary/lic/`（四个仓库的 raw `LICENSE` 探测）、`verify-shanghai-secondary/abyss/`（Abyss-of-Dragon/project_english 的 README.md 808 B 与 `基于《2021年高考英语词汇手册上海卷》的数据库.docx` 11,023 B）、`verify-shanghai-secondary/gkstd2025/std2025.pdf`（《普通高中英语课程标准 日常修订版（2017 年版 2025 年修订）》非官方镜像，forum.freemdict.com，3,978,785 B，178 页，PDF CreationDate 2025-10-31）。

**重新访问的网页**（WebFetch，均访问 2026-11-05）：douban 23038660/34946354/35139941/10572648/35583255/36758411；sohu 867472653/918312869/415533066；yuntaigo 书页；shmeea 13285/10343/19513/18568；gov.cn 著作权法；screle.shisu.edu.cn 两页；textbook-info 1451；lyzx.xhedu 33230；aaaaenglish 3500 词页；chuzhong.eol.cn 1600 词页；hotbook.nbt 144927；ankichinas 667a83ef60241y5c；zhongkao-words README/CONTENT_LICENSE；YR7429 README；GitHub 提交历史页三份；edu.sh.gov.cn 沪教委基〔2022〕17 号、沪教委规〔2019〕2 号；wangjunjian.com 2025 词汇表文；freemdict 论坛帖。失败：centuryenglish.com（405）、book.qsbdc.com（证书不匹配）、zhuanlan.zhihu（403）、blog.csdn（超时）、moe.gov.cn A26/s8001（http↔https 循环重定向）、GitHub tree 页（504）。WebSearch 共用额度在第 10 次检索后耗尽，之后只用 WebFetch。

---

## 逐条核验（保留原编号）

**[shanghai-secondary-1] 确认。** `txt/guide03.txt:13`：「依据《上海市中小学英语课程标准（征求意见稿）》（2004 年版）规定的初中（六至九」（下行接「年级）」）；`txt/booklist_b.txt:6`：「义务教育教科书（五·四学制）·」。置信度 高。

**[shanghai-secondary-2] 确认。** `txt/booklist_b.txt` 757–815 行区间含「英语（牛津上海版）（试用本）」「英语（新世纪版）（试用本） 沪外教」「由学校选一种使用」（grep 命中）；screle 页（2024-12-30）原文「这套五四制初中英语教材由上海教育出版社出版，六年级上册和七年级上册已于2024年9月在上海市投入使用」；textbook-info 1451（2025-01-20）原文「牛津上海版初中英语（大部分区使用）和新世纪版初中英语（使用比较少）」「从六年级新生开始使用2024年新版课本，其它年级还是使用旧版课本」。置信度 高。

**[shanghai-secondary-3] 修正（数字正确，定性过强）。**
- 数字确认：`file` 读 .doc OLE 属性 → 「Create Time/Date: Mon Oct 25 13:15:00 2004 … Number of Words: 904」；`txt/sh_curriculum_std_note.txt:11` 含原文「小学毕业生核心词汇量不少于500词，总词汇量不少于600词；初中毕业生核心词汇量累计不少于1600词，总词汇量累计不少于2100词；高中毕生毕业核心词汇量累计不少于2300词，总词汇量累计不少于4200词」（「毕生毕业」笔误属实）。
- 引文修正：2019 版指南写的是「以《上海市中小学英语课程标准》（2004 年版）规定的内容与要求为考试范围」（`txt/guide2019.txt:57`，**无**「征求意见稿」字样）；只有 2020 版（`guide03.txt:56-57`）带「（征求意见稿）」。2017 版 `guide2017.txt:56-57` 引文正确。
- 定性修正：「法定基准**仍是** 2004 年标准（置信度 高）」只被 2020 年及以前的指南支持。2022 年起的反证：市教委《上海市中小学 2022 学年度课程计划及其说明的通知》（沪教委基〔2022〕17 号，2022-07-06，https://edu.sh.gov.cn/xxgk2_zdgz_jcjy_01/20220728/2cf6b8d37a234a54a62dbd1d19089649.html，访问 2026-11-05）的依据文件即「《教育部关于印发义务教育课程方案和课程标准（2022年版）的通知》（教材〔2022〕2号）」，并要求「严禁用地方课程、校本课程取代国家课程」；《上海市初中学业水平考试实施办法》（沪教委规〔2019〕2 号）只说「考试内容限定在普通中小学各学科课程标准规定的范围内」，不指明上海版；2024/2026 版考纲手册附录增加「新课标三级词汇（2022版）」（见 [5]）。正确说法：**2004 年标准是 2020 年以前评价指南的明示依据；2022 学年起上海课程计划已以国家 2022 年版课标为依据，中考词表的现行法定基准待查**。置信度 中。

**[shanghai-secondary-4] 确认（附提醒）。** `pdfinfo` 页数 14/13/12 ✓；`grep 词汇表|附录` 在 guide03 仅命中 `:451`「五、附录」（guide2019 在 `:510`，guide2017 无）✓；`guide03.txt:273-296` 试卷结构 30/50/70、「试卷总分：150 分」「考试时间：100 分钟」✓。提醒：这是 2020 年旧中考结构，已被 2022 年起的新中考取代（见遗漏 O4）。置信度 高。

**[shanghai-secondary-5] 确认。** douban 23038660：「本书是根据2013年上海市初中毕业统一学业考试考试手册上1669个单词和323个词组编写的」（译文 2013-4，ISBN 9787532760589）✓；douban 34946354：「根据《2020年上海市初中毕业统一学业考试考试手册》中的1733个单词和335个词组进行编写」（2019-12，ISBN 9787532783342）✓；sohu 867472653（2025-03-06）：「根据《2025年上海市初中毕业统一学业考试手册》中的1730个单词和334个词组进行编写」✓；sohu 918312869（**发布于 2025-07-28**，作者未注明日期）：「1785个考纲词汇、347个考纲词组（常考词汇星号标记）」「273个新课标三级词汇（除考纲外）」「129个学科教学基本要求词汇（除考纲、新课标外）」，并写明「273个新课标三级词汇（2022版）」✓；nbt 144927：「2024版附录增加了新课标三级词汇219条」✓；shmeea 19513（2025-06-15）：「2025年上海市初中学业水平考试英语科目考试」✓；shmeea 13285 列出的 14 种出版物中确无中考《考试手册》（有「2020年普通高等学校招生全国统一考试（上海卷）考试手册 上海教育出版社 ￥16.00」）。口径说明：全部是教辅转述，「单词」与「词组」分开计数，未混用。置信度 中-高。

**[shanghai-secondary-6] 确认。** douban 35139941：上海市教育委员会教学研究室 / 上海教育出版社 / 2016 / ISBN 9787544472685 / 179 页 ✓；lyzx.xhedu 33230（2019-03-13）：「现行的上海市初中英语教学基本要求（试验本）（2017修订版）是2020年新课程标准出台前的过渡期的课程标准」✓；`txt/booklist_b.txt:1322-1324`：「上海市初中英语学科教学基本要求 / Ⅱ－CP－2021010 沪教育 九年级 /（试验本）」✓。补充：同一目录 `:581` 还有「上海市小学英语学科教学基本要求」、`:1889`「上海市高中英语学科教学基本要求」。置信度 中。

**[shanghai-secondary-7] 修正（主结论成立，三处细节有误）。**
- 确认：`pdfinfo`「Creator: Acrobat PDFMaker 17 Word 版 … CreationDate: Mon Sep 30 11:28:13 2019 CST … Pages: 89」✓；`txt/sh_junior_2020.txt:2196`「词组(Phrases and Expressions)」✓；我独立解析得 **1,731 个唯一词头，与作者的 `sh2020_words.json` 集合完全相同（双向差集为空）**；zhongkao-words JSON 1,722 词（18 个文件，1722 条、无重复）全部包含于其中，仅差作者列出的 9 个变体 ✓。
- 修正 1：「补回被 pdftotext 拆行丢失的 `hang`」不成立——`txt/sh_junior_2020.txt:864` 顶格为「hang (hanged, hanged) v. 处绞刑；上吊」，解析器本就得到 `hang`；作者手工追加造成重复，所以其「headword tokens: 1733」是人为膨胀。真实词头 token 数为 **1,732**，唯一 1,731，唯一重复项是 `miss`（miss v. / Miss n.）。「与手册 1733 吻合」因此只是近似（推断：若手册把 PDF 文本里缺失的 `a`/`an` 各算一个，1731+2=1733，恰好吻合；未证实）。
- 修正 2：入库日期——GitHub 提交页显示该 PDF 唯一一次提交为 **June 8, 2021**（e2e1aef），作者写 2021-06-09（时区显示差异，不影响结论）。
- 修正 3：词组数——作者「粗数到 379 条」把附表算了进去；我按「词组标题（`:2196`）到代词附表标题（`:2569`）之间顶格以字母开头的行」数得 **331** 条（含 CJK 的行 342），与手册「335 个词组」接近，支持「=2020 年考试手册词表」的推断。
- 另注：PDF 元数据 Title「Medical NOte」、Author「Intergen Administrator」——是套用他人 Word 模板的第三方转换件，不是官方导出；来源不明这一点作者已说，此为佐证。置信度 高/中。

**[shanghai-secondary-8] 修正（数字正确，解释有误）。** 我的重算：|上海|=1731 |全国中考|=1887 交集 1286 仅上海 445 仅全国 601，1286/1731=74.3% ✓，20 例抽样一致。但「`a` 落在仅全国是因上海 PDF 以 `a/an` 合并写法开头而首行被当作表头跳过」不成立：pdftotext 输出的第 1 页只有「英 语 词 / 汇 表」两行标题，第 2 页直接从「ability n.」开始，**全文没有任何 `a`/`an` 词头行**（`grep -E '^a[ /(]|^an[ /]'` 在单词区 0 命中，只在词组区命中「a bit (of)」等）。正确说法：该 PDF 文本本身缺 `a`/`an`。影响仍是 1 词。置信度 高。

**[shanghai-secondary-9] 确认（代理词表可信度上调）。** `07-yr7429/kaogang_graded.txt:1-9` 的说明原文与作者引文一致；我的解析：3,091 词（无星 1,591 / 一星 500 / 二星 1,000）✓；上海 vs 课标 1600：交集 1305、仅上海 426、仅课标 286 ✓。额外核验：我下载的 2025 修订版课标 PDF（178 页）附录 2 说明原文「1. 本 词 汇 表 共 收 录 3100 个 单 词， 含《 义 务 教 育 英 语 课 程 标 准（2022 年版）》所列义务教育阶段要求掌握的 1600 个单词。…再选择增加 200 个单词。」（`gkstd2025/std2025.txt:3059-3064`），我从该 PDF 直接解析出 3,210 个条目，其中 119 个是附录末尾的国家/国籍附表（afghan、afghanistan、american…），剔除后 **3,091 词与 YR7429 完全一致，星级 0 处不一致、YR7429 独有 0 词**。YR7429 README `:60`「LICENSE 授权条款（代码 MIT / 内容 CC BY-SA 4.0）」✓、`:24`「无星号为义务教育阶段已掌握」✓、`:46`「命中 3093 条，未命中 93 条」。置信度 中-高。

**[shanghai-secondary-10] 确认。** `txt/booklist_a.txt:511-513`：「上海市高中英语学科教学基本要求 / Ⅱ－GJ－2021002 沪教育 /(试验本)」，左侧竖排栏「供 学 校 选 用」✓；douban 10572648：上海教育出版社、ISBN 9787544422253、定价 8.50、无年份 ✓。置信度 中。

**[shanghai-secondary-11] 确认。** sohu 415533066（2020-08-28）：「2020年秋季学期高一年级数学、英语学科先行实施新课程新教材；2021年秋季学期高一年级起全面实施新课程新教材」✓；screle a5/2b（2020-07-20）：「由上海市教育委员会组织编写，依据《普通高中英语课程标准（2017年版）》的要求设计」「新教材共7册」✓；`txt/booklist_a.txt:140-165`：「教育部审定非统」「普通高中教科书·英语（必修第一」「Ⅱ－GB－2021013 沪教育」「Ⅱ－GB－2021019 沪外教」「由学校选择一套教材使用」✓。置信度 高。

**[shanghai-secondary-12] 确认。** shmeea 10343（2017-12-29）：「《考试手册》的征订工作于今年9月完成」「考试说明分科目和语种，主要包括考试性质、考试目标、考试内容及要求、考试形式与试卷结构等内容」✓；shmeea 13285：「2020年全国普通高等学校招生统一考试高考英语词汇手册（上海卷）」上海译文出版社 ￥16.00 2019-05 ✓；douban 35583255：译文 2021-8、ISBN 9787532788071、424 页、「新版增加了新型冠状病毒考点高频词汇」✓，页面确无词数。置信度 高。

**[shanghai-secondary-13] 无法核验。** 作者本身结论是「找不到」；tukuppt 页未抓取（加密内容），我的 WebSearch 额度在尝试前已耗尽，无法另找来源。保持「找不到」。

**[shanghai-secondary-14] 确认（附年份提醒）。** yuntaigo 书页：复旦大学出版社、2024-01-01、ISBN 9787309170405、沈传辰；原文「其内容根据教育部颁发的《普通高中英语课程标准（2017年版2020年修订）》中的词汇要求、上海市教育考试院公布的新高考英语补充词汇及上海地区使用的四套英语教材、最近几年上海的一模二模英语卷编写。」目录「附录l 新课标135+上海200词」✓。douban 36758411《新考纲上海高考英语词汇手册（含跟读与朗读音频）》为同一 ISBN，不是新版。提醒：该手册依据的「2020 年修订」已被「2025 年修订」（3100 词）取代，见遗漏 O3。「4300＝3000＋200＋1100」仍只见于搜索摘要，维持未核实。置信度 中。

**[shanghai-secondary-15] 修正（结论成立，检索陈述不准确）。** GitHub 代码搜索 API（`search/repositories?q=上海 高考 词汇手册`）返回 1 个仓库：`Abyss-of-Dragon/project_english`「基于《高考英语词汇手册（上海卷）》的网页应用」（0 star、3 fork、18 commits、无许可证），作者称相近查询「0 结果」。但我下载其唯一数据文件 `基于《2021年高考英语词汇手册上海卷》的数据库.docx`（11,023 B）：`word/document.xml` 仅 1,638 B、**0 个段落、0 个英文词**，README 是课程作业模板。所以「上海高考词表的机读文件找不到」仍然成立。ankichinas 页：「一共有5212个单词，双模式对应有10424张卡片。里面收录了全部新课标词」「包含上教版新教材词汇（1-7册）和上外版新教材词汇（1-7册）」「（吉林大学出版社，红色封面）」、￥89、503.9MB ✓。置信度 高。

**[shanghai-secondary-16] 确认。** aaaaenglish 3500 词页前 25 词「a(an), abandon, ability, able, abnormal, aboard, abolish, abortion, about, above, abroad, abrupt, absence, absent, absolute, absorb, abstract, absurd, abundant, abuse, academic, academy, accelerate, accent, accept」与 `Highschool_edited.txt` 开头逐词一致（文件首词 `a` 被 `parse_list` 的 `len(line) == 1` 规则跳过，解析后首词为 `an`），10 个探针词（abortion、abolish、bungalow、catastrophe、pavement、yummy、zipper、dustbin、sparrow、swap）均在该页 ✓；我的重算：Highschool 3,446 vs 课标 3,091：交集 2574、仅 Highschool 872、仅课标 517 ✓；GitHub 提交页：Highschool_edited.txt 提交于 2019-12-15（edit）与 2019-12-17（init、edit）✓。置信度 高/中。

**[shanghai-secondary-17] 修正（一个计数有误）。** 确认：文件 1,976 行、`parse_list` 得 1,887 词头、26 个单字母节标题、顶格大写词头 70 行（`grep -c -E '^[A-Z][a-z]'`）、`:1382`「really v [ˈrɪəlɪ] ad.」✓；eol.cn 2013 年 1600 词表前 30 词含 according to、achieve、add、address、advise、agreement ✓；提交日期 GitHub 显示 2021-06-08（3e20937）。修正：多词条目按 `parse_list` 逻辑只有 **6** 个（computer game、fruit juice、Middle East、Olympic Games、the Pacific Ocean、swimming pool），不是 8 个。置信度 低-中（来源仍未知）。

**[shanghai-secondary-18] 确认（但枚举不完整，见遗漏 O1）。** 逐行核对：`scripts/build_seed.py:82-83` ✓；`backend/wd/seed.py:43`、`:185`、`:204-208` ✓；`docs/SCHEMA.sql:147-148`、`:181`、`:185` ✓；`backend/wd/schemas.py:52`、`:56-57` ✓；`frontend/src/i18n/zh.ts:28`、`:86` ✓；`grep -rn '上海|Shanghai|省份|province|地区版'` 在 backend/frontend/src/docs 仅命中 `Asia/Shanghai` 时区（含测试）✓。小误差：`ATTRIBUTION` 文案实际在 `scripts/build_seed.py:201-218`，作者写 205–217。置信度 高。

**[shanghai-secondary-19] 修正（SQL 结果全部复现，但「缺 29 个」口径需拆分）。** 复现：在库 1702、stage_min 分布 (1,1393)(2,236)(3,59)(4,14)、未标初中 309、缺 29、库中 zk 词不在上海表 706 ✓。但 29 个「缺词」里：① `o’clock` 是弯引号未归一化的假缺——库里有 `o'clock`（stage_min=1, stage_zk=1），归一化后在库数应为 1,703、标 zk 数 1,394；② `café`→`cafe`（在库，stage_min=3）、`yogurt`→`yoghurt`（在库，stage_min=2）是拼写变体；③ 12 个是库中原形的屈折形式，已在 `word_forms`（`embarrassed→embarrass(p)`、`excited→excite(p)`、`frightened/frightening→frighten(p/i)`、`frozen→freeze(d)`、`lost→lose(p)`、`satisfied/satisfying→satisfy(p/i)`、`stuck→stick(p)`、`surprised→surprise(p)`、`underlined→underline(p)`、`united→unite(p)`；其中 9 个原形已 stage_zk=1）。真正缺席的只有 **14** 个：angrily、beautifully、bund、carefully、dancer、dishonest、hot-dog（`hot dog` 也不在库）、luckily、mr、mrs、politely、quietly、seafood、unforgettable。SQL：`SELECT f.form, w.lemma, f.kind, w.stage_zk FROM word_forms f JOIN words w ON w.id=f.word_id WHERE f.form IN (...)`。置信度 高。

**[shanghai-secondary-20] 确认。** 复现 1580/1591（缺 11 词同作者）、3063/3091（缺 28）、3100 表在库且 stage_gk=1 为 2621、两份 mahavivo 文件 1887/1887、3446/3446 全在库 ✓。置信度 高。

**[shanghai-secondary-21] 确认。** 复现 |上海∩Highschool|=1583（91.5%）、仅上海 148、仅 Highschool 1863 ✓。置信度 高。

**[shanghai-secondary-22] 确认。** raw 探测：`mahavivo/english-wordlists` 的 LICENSE/LICENSE.md/LICENSE.txt 均 404，GitHub 仓库页侧栏无许可证 ✓；`lolo811109-crypto/zhongkao-words/LICENSE` 200，开头「MIT License Copyright (c) 2026 Word Atlas contributors」，`CONTENT_LICENSE.md:11,23,24` 原文含「以 Creative Commons Attribution 4.0 International (CC BY 4.0) 提供，在项目维护者能够授予的权利范围内」「单个英文单词与通用词表本身不主张专有权」「内容由 AI 模型按项目规范生成…未逐条人工审校，按现状提供」✓（GitHub 搜索 API 对该仓库标 `NOASSERTION`，即自动识别失败，不影响文本）；`YR7429/english-vocab-cn/LICENSE` 200「MIT License …」（内容 CC BY-SA 4.0 只写在 README `:60`）✓；`KyleBing/english-vocabulary/LICENSE`「BSD 3-Clause License Copyright (c) 2022-2026, KyleBing」✓。置信度 高。

**[shanghai-secondary-23] 确认（引文）；法律推断部分不作核验。** gov.cn 页标题《中华人民共和国著作权法》、「2020年11月11日」修正，第五条全文与作者引文逐字一致 ✓。推断链本身无法用事实核验，作者已标注「不构成法律意见」。置信度 中。

---

## 作者遗漏的重要事实

**O1（代码，改变工作量估算）阶段四档的硬编码点远不止 [18] 列出的 6 处。** 全库 grep 另见：`backend/wd/schemas.py:25` `Stage = Literal["zk", "gk", "cet4", "cet6"]`、`:51` `STAGE_ORDER`、`:64-67` `index_to_stage` 的 `if not 1 <= int(index) <= 4`、`:488`/`:708`/`:1335` 三个带阶段字面量的 `Literal`；`backend/wd/services/words.py:39` `STAGES`；`backend/wd/services/ecdict.py:28` `STAGE_TAGS`；`backend/wd/services/bank.py:85-86` `DEFAULT_STAGES = ("cet4","cet6")`、`DEFAULT_CURRENT_STAGE = 3`；`backend/wd/ai/prewarm.py:32-33` `STAGE_COLUMNS`/`STAGES`；`backend/wd/ai/content.py:48-49` `AUDIENCE = "Chinese learners, junior high school to CET-6, plus working professionals"`、`STAGE_ZH`（进入 AI 提示词）；`backend/wd/migrations/0001_init.sql:147-148,185`（线上已生效的 CHECK，SQLite 不能 ALTER CHECK，加阶段需重建表迁移）；`docs/SCHEMA.sql:195` `difficulty … CHECK (difficulty BETWEEN 1 AND 5) -- 1 初中 … 4 六级, 5 beyond`；前端 `frontend/src/api/types.ts:5`、`frontend/src/components/word/StageChips.tsx:7-9`（`STAGE_ORDER/STAGE_INDEX/STAGE_BY_INDEX`）、`frontend/src/pages/VocabPage.tsx:29` `TABS`、`frontend/src/pages/AdminPage.tsx:36` `PREWARM_STAGES`、`frontend/src/pages/WelcomePage.tsx:30-38` `ROLE_PRESETS`（角色只有 zk/gk/uni/pro，**无「小学生」**）、`frontend/src/i18n/zh.ts:25` `roles`；文档 `docs/API.md:160,169,187,230,239,460`。合计 ≥20 处，且含一次破坏性迁移。

**O2（来源年份，改变 [3] 的方向）上海 2022 学年起的课程计划以国家 2022 年版课标为依据。** 沪教委基〔2022〕17 号（2022-07-06）依据「《教育部关于印发义务教育课程方案和课程标准（2022年版）的通知》（教材〔2022〕2号）」，并写明「严禁用地方课程、校本课程取代国家课程」；沪教委规〔2019〕2 号《上海市初中学业水平考试实施办法》（2019-04-02，https://edu.sh.gov.cn/xxgk2_zdgz_rxgkyzs/20230412/ec0b8612c5c14970ad0260593696af43.html）：「考试内容限定在普通中小学各学科课程标准规定的范围内」；2026 版考纲手册附录「273个新课标三级词汇（2022版）」。产品含义：上海初中词表的参照系正在从「2004 上海标准＋考试手册」转向「2022 国家课标 1600 词＋上海手册增量」，与本项目的课标 1600 代理（1,591 词，覆盖率 99.3%）直接相关。

**O3（更新版文件）高中课标已有「2017 年版 2025 年修订」，取代复旦手册所依据的 2020 年修订。** 我下载的 PDF（非官方镜像，178 页，CreationDate 2025-10-31）封面「日常修订版（2017 年版 2025 年修订）」，附录 2 说明「本词汇表共收录 3100 个单词，含《义务教育英语课程标准（2022 年版）》…1600 个单词…累计达 2100…累计达 3100。各地可根据实际情况…再选择增加 200 个单词」；2020 年修订版词表为 3000 词（freemdict 论坛帖提及）。YR7429 的 3,091 词正是这份 2025 修订版的提取（我逐词比对一致）。教育部印发日期未能核实（moe.gov.cn 页面循环重定向、搜索额度耗尽）；上海 2026 届高考是否按 2025 修订执行未核实。

**O4（现行考试结构）[4] 引的 2020 年试卷结构已过时。** 沪教委规〔2019〕2 号：「外语科目考试满分150分，其中，笔试满分140分（含听力25分），听说测试满分10分。」「笔试时间为90分钟（含听力），听说测试时间为10分钟（采用人机对话方式）」；shmeea 18568（2024-06-15）时间表「9:00-10:30 外语笔试」（90 分钟）佐证。与产品相关：上海中考有人机对话听说测试，与本项目的发音/口音设置（`accent`、`auto_pronounce`）相关。

**O5（计数口径）[19] 的「缺 29 个」实际只有 14 个真缺。** 12 个是 `word_forms` 已覆盖的屈折形式，1 个是弯引号归一化假缺（`o’clock`），2 个是拼写变体（café/yogurt）。详见 [19]。

**O6（数据来源细节）上海 PDF 文本没有 `a`/`an`，且元数据显示为第三方 Word 模板转换件**（Title「Medical NOte」、Author「Intergen Administrator」）。见 [7]/[8]。

**O7（小学线索）2023 年教学用书目录已列「上海市小学英语学科教学基本要求」**（`txt/booklist_b.txt:581`），是小学 slug 的本地权威文件线索；作者只用该目录核对初中条目。

**O8（库内一个小坑）`an` 在库但 stage_min=2、stage_zk=0**（`SELECT … WHERE lemma='an'` → `0|1|0|1|2|cet46 gk`）：中考表「a (an)」行经 `RICH_RE` 只取到 `a`，ECDICT 也未给 `an` 打 zk 标签；`a` 则靠 ECDICT zk 标签入库（`1|1|1|0|1|cet4 ecdict zk`）。

---

## 联网类额外核查（一手性 / 年份 / 口径）

- **一手来源**：[1][3][4][11][12] 依赖的 shmeea/edu.sh.gov.cn 文件与 PDF 均为一手 ✓；[2][11] 教材信息混用一手（教学用书目录、上外基地页）与二手（textbook-info）✓ 已标注；[5][6][10][12][14] 的词数/书目信息全部来自出版社/电商/豆瓣二手转述，作者已标明「教辅复述」，核对后数字一致。
- **年份是否已被取代**：[3] 的 2004 标准（见 O2）、[4] 的 2020 试卷结构（见 O4）、[14] 的 2020 修订课标（见 O3）三处存在「有更新文件」的情况，作者未标出；其余引用年份为所见最新。
- **口径（词 vs 词条 vs 词组）**：[5] 单词/词组分列 ✓；[7] 作者的 1733 token 含人为重复、379 词组含附表（已修正为 1732/331）；[9][16][20] 的课标 3100 为「单词」口径，PDF 附录末的国籍附表（119 条）不计入 3100，YR7429 亦未计入 ✓；[15] Anki 牌组 5,212 为「单词」但含教材词，作者已区分 ✓；[17] 1,976 是行数、1,887 是词头，作者区分正确 ✓。

---

## 未解决的问题

1. 教育部印发《普通高中课程方案和…课程标准（2017 年版 2025 年修订）》的日期与文号（我只拿到非官方镜像 PDF）；上海 2026 届高考是否按 2025 修订版（3100 词）命题。
2. 上海中考的现行法定词汇依据（2004 上海标准 vs 2022 国家课标）没有一份 2022 年后的考试院文件直接说明；2026 年考试手册（1785 词 + 347 词组）的官方发布时间与是否已出版未核实（教辅稿发布于 2025-07-28）。
3. 《上海市初中/高中/小学英语学科教学基本要求》词汇表电子版：搜索摘要提到「2015 上海市初中英语教学基本词汇表」（book.qsbdc.com，证书错误无法访问）与百度文库同名文档，均未能核实内容与词数。
4. [13] 2016/2017 年上海高考词表增删数字：仍找不到。
5. 作者的 GitHub API 调用（commits `committedDate`）本次无法复现（限流），日期仅凭 GitHub 页面（显示 2021-06-08 / 2019-12-15、17）。

---

**汇总：核验 23 条：确认 16、修正 6、推翻 0、无法核验 1。**
