# 上海初中（中考）与高中（高考）英语词汇要求 vs 本项目现用「全国」词表 — 事实核验

slug：`shanghai-secondary` · 基线：main @ 75df534 · 日期：2026-11-05 · 性质：只读调研，不改代码。

## 范围与方法

**读过的仓库文件（行号按 75df534 核对）**：`scripts/build_seed.py`（15–47 `PLAIN_RE/RICH_RE/POS_RE/parse_list`，82–83 两个词表文件名，205–217 attribution 文案）、`data/seed/ATTRIBUTION.md`、`data/seed/stats.json`、`backend/wd/seed.py`（43、60–64、185、204–208）、`backend/wd/schemas.py`（52–60）、`docs/SCHEMA.sql`（147–148、181–186）、`frontend/src/i18n/zh.ts`（25、28、86）、`frontend/src/api/types.ts:45`、`docs/DESIGN.md:330`；以及 2026-11-04 的 `docs/analysis/2026-11-04-library-curation/facts/seed-pipeline.txt`（只作背景，结论均按当前代码重核）。

**线上库只读副本**：`/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/live-copy.db`，用 `sqlite3 -readonly` 查 `words` 表结构与计数（9,162 词；zk 2099 / gk 3829 / cet4 4722 / cet6 7671；stage_min 1:2099 2:1792 3:1577 4:3694），覆盖率用 Python `sqlite3` 以 `file:...?mode=ro` ATTACH 后 SQL JOIN 计算。

**搜索词（WebSearch/WebFetch，服务端执行）**：上海市初中英语学科教学基本要求 试验本 词汇表；上海市初中毕业统一学业考试 考试手册 词汇；上海高考英语 考纲词汇 词汇手册 2017 修订；上海市高中英语学科教学基本要求 词汇量；github 上海 中考/高考 英语 词汇 txt/json；site:shmeea.edu.cn 英语 考试手册/评价指南；新考纲上海高考英语词汇手册 复旦；上海 2023 取消考纲；中华人民共和国著作权法 第五条；牛津上海版/新世纪英语/上外版/上教版 教材 等。被拒/失败的抓取：zhixue.org（证书不匹配）、zhihu（403）、baike.baidu（403）、CSDN（521）、fudanpress.com.cn（证书不匹配；curl 得到的只是「浏览器版本不兼容」占位页）、sohu 春考 135+200 文章（已 404）。

**下载（每个下载独占一个新目录；均视为不可信数据，只用 `python3 -I` 解析；PDF 因本机无任何 Python PDF 库，用 poppler 的 `pdftotext -layout`（只读解析器，在 `analysis/` 目录以绝对路径运行，输出到 `txt/`）转文本，这是对「只用 python3 -I」规则的唯一偏离）**，根目录 `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/shanghai-secondary/`（sha256 前 16 位 / 字节数）：

| 目录/文件 | 来源 | sha256[:16] / bytes |
|---|---|---|
| `01-mahavivo/zhongkao.txt`（即 `中考英语词汇表.txt`）、`Highschool_edited.txt`、`README.md` | raw.githubusercontent.com/mahavivo/english-wordlists/master/ | f2f67792e3c9f35e / 86,765；974f29c3ed2252ad / 25,353；b224c4e3c2de000d / 2,089 |
| `02-mahavivo-sh2020pdf/sh_junior_2020.pdf`（仓库文件名 `上海市初中英语词汇表（2020年版）.pdf`）、`xiaoxue_dagang.txt`（`小学英语大纲词汇.txt`，顺手取给小学 slug） | 同上 | 11f7bdb6eaba225e / 1,200,683；bb7581da02e735d3 / 2,518 |
| `03-shmeea-2020-guide/guide03.pdf`（2020 年上海市初中英语课程终结性评价指南）+ `probe/01,02,04,05.bin`（同目录语文/数学/物理/化学指南，用于排除） | https://www.shmeea.edu.cn/download/20190926/03.pdf | 5f11609fcd4d8a50 / 887,507 |
| `04-shedu-curriculum-doc/sh_curriculum_std_note.doc`（《上海市中小学英语课程标准（征求意见稿）》说明（社会版）） | https://edu.sh.gov.cn/cmsres/a7/a74f0300fda4480193d663086cf0f408/286a4201624f8b80a88be0d4fc1ed208.doc | f6f23b810f67712f / 50,176 |
| `05-zhongkao-words-json/entries_0..17.json`、`README.en.md`、`index.html` | raw.githubusercontent.com/lolo811109-crypto/zhongkao-words/main/public/atlas/entries/ | entries_0: 0edf983591ad8f5a / 95,328（18 个文件共约 1.7 MB） |
| `06-kylebing/chuzhong_luanxu.txt`、`gaozhong_luanxu.txt`、`README.md` | raw.githubusercontent.com/KyleBing/english-vocabulary/master/ | 97a0c7aa25dc2cc9 / 206,943；7b2905414a9dba3e / 332,886 |
| `07-yr7429/3185.txt`、`kaogang_graded.txt`（`考纲词汇含分级.txt`）、`README.md` | raw.githubusercontent.com/YR7429/english-vocab-cn/main/ | 05a7d2fa2399408b / 73,856；f003d0fbf2570508 / 26,590 |
| `08-shmeea-2019-guide/guide2019.pdf`、`09-shmeea-2017-guide/guide2017.pdf` | https://www.shmeea.edu.cn/resource/upload/www/201812/07150630ozpf.pdf；https://www.shmeea.edu.cn/u/cms/www/201612/08182755iytj.pdf | 79eaec17fde86276 / 888,810；0e56fae41358b909 / 474,684 |
| `10-c3h3/README.md` | raw.githubusercontent.com/C3H3-AI/vocab-wordbank/main/ | 45af13067a6ea0e1 / 3,947 |
| `11-fudanpress/book15569.html`（无内容的占位页） | http://www.fudanpress.com.cn/news/showdetail.asp?bookid=15569 | 5800867158161634 / 13,621 |
| `12-shedu-booklists/booklist_a.pdf`（2021 年秋季上海市小学/初中/高中教学用书补充目录）、`booklist_b.pdf`（2023 年秋季上海市编写教学用书目录 附件2） | https://edu.sh.gov.cn/cmsres/ef/efd7b82180f1448796687fe74ae389ca/8114411131c1a5d5f45862823f30a5f2.pdf；https://edu.sh.gov.cn/cmsres/86/861d20b1f27746bdaf38b351e104be47/14d8bd2ec9d58aa74ee82402622ab67b.pdf | c2d0de8c073f1a25 / 160,768；8f64f54ced0e4e45 / 292,864 |
| `13-csdn-1976/csdn.html`（521 错误页） | https://blog.csdn.net/joeqinyu/article/details/139155018 | 5db3418067410db6 / 2,125 |

解析脚本与输出：`analysis/parse_sh.py`（上海 PDF 文本 → 词头）、`analysis/compare2.py`（交集/差集/覆盖率）、`analysis/compare2_output.txt`（完整输出）、`analysis/sh2020_words.json`、`analysis/lists.json`（四份词表）、`txt/*.txt`（pdftotext 输出与 .doc 粗提取文本）。

---

## 结论

### A. 学制与教材背景

**[shanghai-secondary-1]（事实，置信度 高）上海义务教育为五四学制，初中 = 六至九年级。**
证据：《2020 年上海市初中英语课程终结性评价指南》（shmeea 03.pdf，访问 2026-11-05）原文：「依据《上海市中小学英语课程标准（征求意见稿）》（2004 年版）规定的初中（六至九年级）英语课程目标和教学内容与要求，确定以下能力目标和知识内容。」2023 年秋季上海市编写教学用书目录（booklist_b）标题下即为「义务教育教科书（五·四学制）」。

**[shanghai-secondary-2]（事实，置信度 高）上海初中英语教材为两套并行、由学校选用：牛津上海版（沪教育＝上海教育出版社）六至九年级、新世纪版（沪外教＝上海外语教育出版社）；2024 年 9 月起牛津上海版换新版，逐年级推进。**
证据：2023 年秋季编写教学用书目录·初中阶段（booklist_b 第 757–815 行）：「英语（牛津上海版）（试用本）（六/一）（含音频材料） Ⅱ－CB－2016001 沪教育 六年级第一学期」…「Ⅱ－CB－2016004 … 九年级第一学期」；「英语（新世纪版）（试用本） 沪外教 Ⅱ－CB－2020015 六年级第一学期」…「Ⅱ－CB－2020021 九年级第一学期」；备注「由学校选一种使用」。上海外国语大学基地页（https://screle.shisu.edu.cn/ea/de/c16360a191198/page.htm，访问 2026-11-05）：《义务教育教科书（五•四学制）•英语》（六年级上册～九年级下册）「上海教育出版社出版」「六年级上册和七年级上册已于2024年9月在上海市投入使用」。textbook-info（http://textbook-info.com/post/1451.html，访问 2026-11-05）：「2025年春季上海初中所使用的英语课本是牛津上海版初中英语（大部分区使用）和新世纪版初中英语（使用比较少）」「从六年级新生开始使用2024年新版课本……新生新版本，老生老版本」。（册名 6A–9B 为旧版沪教牛津的商业叫法，官方目录按「六/一」等学期命名。）

### B. 上海初中（中考）词汇要求

**[shanghai-secondary-3]（事实，置信度 高）上海各学段词汇量的法定基准仍是 2004 年《上海市中小学英语课程标准（征求意见稿）》：初中毕业核心词汇累计 ≥1600、总词汇 ≥2100；小学 500/600；高中 2300/4200。**
证据：市教委站 .doc（文件属性：创建 2004-10-25，共 904 字）原文：「词汇量计算方式为：T（总词汇量）＝K（核心词汇量）＋X（扩展词汇量）……《标准》规定小学毕业生核心词汇量不少于500词，总词汇量不少于600词；初中毕业生核心词汇量累计不少于1600词，总词汇量累计不少于2100词；高中毕生毕业核心词汇量累计不少于2300词，总词汇量累计不少于4200词」（原文「毕生毕业」为文件笔误）。2019、2020 两版评价指南的考试范围均写明「以《上海市中小学英语课程标准（征求意见稿）》（2004 年版）规定的内容与要求为考试范围」（guide2019.txt:57；guide03.txt:56–57）；2017 版写法为「以上海市中小学课程教材改革委员会制订的《上海市中小学英语课程标准》规定的教材内容为考试范围」（guide2017.txt:56）。

> **核验修正（INDEX §3 #13，2026-11-05）**：数字正确，定性过强——「法定基准仍是 2004 年标准」只被 2020 年及以前的评价指南支持（且 2019 版引文为「《上海市中小学英语课程标准》（2004 年版）」，无「征求意见稿」字样，只有 2020 版带）；2022 学年起市教委课程计划（沪教委基〔2022〕17 号，2022-07-06）以国家 2022 年版课标为依据并「严禁用地方课程、校本课程取代国家课程」，《上海市初中学业水平考试实施办法》（沪教委规〔2019〕2 号）只写「课程标准规定的范围内」不指明上海版，2024/2026 版考纲手册附录增列「新课标三级词汇（2022 版）」——中考词表的现行法定基准待查，置信度降为中，依据 verify/shanghai-secondary.md [shanghai-secondary-3]、O2。

**[shanghai-secondary-4]（事实，置信度 高）上海市教育考试院免费公开的《初中英语课程终结性评价指南》（2017、2019、2020 版 PDF）只含能力目标、语法/功能项目、试卷结构与题型示例，不含词汇表；词汇表不在这份文件里。**
证据：三份 PDF 分别 12/13/14 页（pdfinfo），`grep 词汇表|附录` 只命中「五、附录 答题纸仅供形式参考」（guide03.txt:451–452）。试卷结构（guide03.txt:273–296）：「第一部分 听力 30 ……第二部分 语言知识 50 ……第三部分 读写 70」「试卷总分：150 分」「考试时间：100 分钟」。

**[shanghai-secondary-5]（事实＋推断，置信度 中-高）上海中考词表的载体是考试院每年出版的《上海市初中毕业统一学业考试考试手册》（付费出版物），教辅复述的年度词量：2013 年 1669 词 + 323 词组；2020 年 1733 词 + 335 词组；2025 年 1730 词 + 334 词组；2026 年 1785 词 + 347 词组（另附 273 个「新课标三级词汇（除考纲外）」和 129 个「学科教学基本要求词汇（除考纲、新课标外）」）。**
证据（均为出版社/平台的二手转述）：豆瓣《上海市初中英语考纲词汇用法手册》（https://book.douban.com/subject/23038660/，上海译文出版社 2013-4，ISBN 9787532760589，访问 2026-11-05）：「本书是根据2013年上海市初中毕业统一学业考试考试手册上1669个单词和323个词组编写的」。豆瓣《2020年上海市初中英语考纲词汇手册便携版》（https://book.douban.com/subject/34946354/，译文 2019-12，ISBN 9787532783342）：「根据《2020年上海市初中毕业统一学业考试考试手册》中的1733个单词和335个词组进行编写」。搜狐 2025-03-06 出版社稿（https://www.sohu.com/a/867472653_121124330）：「根据《2025年上海市初中毕业统一学业考试考试手册》中的1730个单词和334个词组进行编写」。搜狐 2026 版稿（https://www.sohu.com/a/918312869_121124330）：「1785个考纲词汇、347个考纲词组（常考词汇星号标记）」「273个新课标三级词汇（除考纲外）」「129个学科教学基本要求词汇（除考纲、新课标外）」。2024 版（https://hotbook.nbt.edu.cn/nbt/?what=detail&id=144927，ISBN 9787532794980）：「2024版附录增加了新课标三级词汇219条」。考试院 2025-06-15 试卷点评页（https://www.shmeea.edu.cn/page/03500/20250615/19513.html）将考试称为「2025年上海市初中学业水平考试英语科目考试」。推断：2025→2026 词数由 1730 跳到 1785、词组 334→347，说明 2026 年考试手册修订了词表；考试院出版物页（https://www.shmeea.edu.cn/page/07000/20190916/13285.html）未列中考手册的出版社/定价，所以「付费出版物」这一点只有教辅侧证据。

**[shanghai-secondary-6]（事实，置信度 中）《上海市初中英语学科教学基本要求（试验本）》是市教委教研室编、上海教育出版社出版的教学文件（2016 年版，后有「2017 修订版」），列入上海市教学用书目录，其词汇表与考纲、新课标三者互有出入。**
证据：豆瓣（https://book.douban.com/subject/35139941/，访问 2026-11-05）：书名「上海市初中英语学科教学基本要求」，副标题「试验本」，编者「上海市教育委员会教学研究室」，出版社「上海教育出版社」，2016 年，ISBN 9787544472685，179 页。龙苑中学教研文（https://lyzx.xhedu.sh.cn/cms/app/info/doc/index.php/33230，2019-03-13）：「现行的上海市初中英语教学基本要求（试验本）（2017修订版）」「是2020年新课程标准出台前的过渡期的课程标准」。2023 年秋季教学用书目录（booklist_b 第 1322–1324 行）：「上海市初中英语学科教学基本要求（试验本） Ⅱ－CP－2021010 沪教育 九年级」。词汇差异见 [5] 的「129 个学科教学基本要求词汇（除考纲、新课标外）」。该书的词汇表本身未找到公开电子版。

**[shanghai-secondary-7]（事实＋推断，置信度 高/中）上海中考词表的机读来源只找到一份：mahavivo 仓库里的《上海市初中英语词汇表（2020年版）.pdf》（89 页，Word→PDF，PDF 创建时间 2019-09-30，2021-06-09 入库），解析得 1,733 个词头、去重 1,731 个，与 2020 年考试手册的「1733 个单词」吻合；GitHub 项目 lolo811109-crypto/zhongkao-words 的 1,722 词 JSON 是它的严格子集。**
证据：`pdfinfo`：「Creator: Acrobat PDFMaker 17 Word 版 … CreationDate: Mon Sep 30 11:28:13 2019 … Pages: 89」；文本结构：第 1–71 页「单词(Vocabulary)」按 A–Z，第 71 页起「词组(Phrases and Expressions)」，末尾附代词表、序数词后缀、国家/民族、「常用学科」表（txt 第 3、2196 行及末尾）。`analysis/parse_sh.py` 规则：去掉缩进的续行/字母标题/页码，词头取词性标记之前的部分，去括号内不规则变化，`although/though`、`exam=examination` 这类 8 行拆成两个词头，补回被 pdftotext 拆行丢失的 `hang`；结果「headword tokens: 1733 unique(lower): 1731」。zhongkao-words README（访问 2026-11-05）：「上海中考英语考纲词汇 1,722 词……词表与中文释义：上海市教育考试院《2020年上海市初中英语课程终结性评价指南》词汇表（单词部分；词组部分未收录），PDF 取自 mahavivo/english-wordlists，由脚本解析」；比对：JSON 1,722 词全部在我的 1,731 词里（JSON−PDF＝0），PDF 多出的 9 个全是变体拆分（anyone、bike、café、everyone、examination、grandfather、grandmother、someone、though）。推断：该 README 把词表归到「评价指南」不准确（评价指南 PDF 不含词表，见 [4]），词表实际来自考试手册；PDF 本身无来源页，mahavivo README 也未说明其出处，故「=2020 年考试手册词表」是基于词数吻合的推断。词组部分我粗数到 379 条带释义的行，但其中混有附表（代词表、国家/民族等），与手册的 335 不能直接对比。

> **核验修正（INDEX §3 #1/#2，2026-11-05）**：① 出处推断需反转——上海市教育考试院发布页同时挂出 `03.pdf`（评价指南，本条只看了它）与 `07.pdf`（评价指南词汇表），后者 md5 `059df9c02684bd989fff6f8849ee1993` 与 mahavivo 副本完全相同，zhongkao-words README 的归属实际成立，该表是一手官方件；② 「补回 `hang`」不成立（`txt:864` 顶格本就有 `hang`），1,733 token 是人为重复造成的膨胀，真实为 1,732 token / 1,731 唯一（唯一重复项 `miss`），与手册 1733 只是近似吻合；③ 词组按「词组标题到代词附表标题之间顶格字母行」数为 331 条（含 CJK 行 342）而非 379（379 含附表）；裁定口径 ≈1,720–1,731 单词 + 331–342 词组（手册 1733 + 335）；入库提交 GitHub 显示为 2021-06-08（时区差异），依据 verify/shanghai-secondary.md [shanghai-secondary-7] 修正 1–3、verify/provinces.md [provinces-12] 修正 1。

**[shanghai-secondary-8]（事实，置信度 高）上海 2020 词表（1,731）vs 本项目的全国中考表（mahavivo 1,887）：交集 1,286（占上海表 74.3%），仅上海 445，仅全国 601。**
计算：`compare2.py` 中 `sh`（上海词头小写）与 `zk`（用 `scripts/build_seed.py:20-47` 同一 `parse_list(...,"rich")` 逻辑解析 `中考英语词汇表.txt`）求集合交并；1286/1731=74.3%。仅上海 20 例（按字母序等距抽样）：accurate, angrily, battery, calm, communicate, damage, drive, exit, fried, historical, iron, mainly, occupation, platform, properly, republic, schedule, smart, survive, variety；仅全国中考 20 例：a, beer, cd, crossing, dragon, europe, fourth, growth, indeed, leaf, mobile, no, painter, professor, sail, shopping, spot, the pacific ocean, trade, wallet。（`a` 落在「仅全国」是因上海 PDF 以 `a/an` 合并写法开头而首行被当作表头跳过；影响 1 词。）

**[shanghai-secondary-9]（事实，置信度 中）上海 2020 词表 vs 国家《义务教育英语课程标准（2022 年版）》1600 词（代理：YR7429 从 2017 课标 2025 修订版词汇表提取的无星词 1,591 个）：交集 1,305，仅上海 426，仅课标 286——与译文社 2026 版「273 个新课标三级词汇（除考纲外）」、2024 版「219 条」量级一致。**
证据：`kaogang_graded.txt` 开头为课标原文「本词汇表共收录 3100 个单词，含《义务教育英语课程标准（2022 年版）》所列义务教育阶段要求掌握的 1600 个单词。高中英语必修课程应学习和掌握 500 个单词（表中加有一个 * 号），累计达 2100。选择性必修课程应学习和掌握 1000 个单词（表中加有两个 ** 号），累计达 3100。各地可根据实际情况在本词汇表所收词的基础上，再选择增加 200 个单词。」我按行解析得 3,091 词（无星 1,591、一星 500、二星 1,000；与 3100 的差 9 个来自多词条目/字形缺失，YR7429 README 也说月份星期等在课标 PDF 里字形缺失）。仅上海 20 例：accurate, automatic, broadcast, clinic, decision, dislike, escape, flash, generation, horrible, journalist, major, net, painting, practice, release, saying, spaceship, thankful, united；仅课标 20 例：a, athlete, bleed, champion, corn, doll, eraser, grammar, hostess, laptop, might, notebook, pepper, pressure, risk, shoulder, spirit, theirs, training, whale。置信度「中」的原因：代理词表来自第三方 OCR/提取，且上海表是 2020 版而教辅数字对应 2024/2026 版考纲。

### C. 上海高中（高考）词汇要求

**[shanghai-secondary-10]（事实，置信度 中）上海高中的本地教学文件是《上海市高中英语学科教学基本要求（试验本）》（上海教育出版社），列入 2021 年秋季高中教学用书补充目录「供学校选用」栏；其词汇表未找到电子版。**
证据：booklist_a 第 511–513 行：「上海市高中英语学科教学基本要求 (试验本) Ⅱ－GJ－2021002 沪教育」，栏目「供学校选用」；豆瓣条目（https://book.douban.com/subject/10572648/）仅有「上海教育出版社」「ISBN 9787544422253」，无年份。搜索摘要称 2021-09 上海外语教育出版社《高中英语教学基本要求词汇解析》据其编写（页面 https://www.centuryenglish.com/books/show-649.html 返回 405，未能核实原文）。

**[shanghai-secondary-11]（事实，置信度 高）上海高中英语教材：2020 年秋高一英语、数学先行用新教材，2021 年全面实施；两套均为「教育部审定非统编教材」，学校选一套：上教版（主编邹为诚，上海教育出版社）和上外版（主编束定芳，上海外语教育出版社），各 7 册（必修 3＋选择性必修 4）。**
证据：搜狐 2020-08-28 转市教委通知（https://www.sohu.com/a/415533066_764972，访问 2026-11-05）：「2020年秋季学期高一年级数学、英语学科先行实施新课程新教材；2021年秋季学期高一年级起全面实施新课程新教材」。上外页（https://screle.shisu.edu.cn/a5/2b/c16360a173355/page.htm）：「由上海市教育委员会组织编写」「依据《普通高中英语课程标准（2017年版）》的要求设计」「新教材共7册」。2021 年秋季高中教学用书补充目录（booklist_a 第 140–165 行）：「教育部审定非统编教材 普通高中教科书·英语（必修第一册）（含音视频材料） 沪教育 高一年级第一学期」「…沪外教 高一年级第一学期」，备注「由学校选择一套教材使用」。textbook-info（http://www.textbook-info.com/post/1452.html）：「沪教版高中英语（2020年审核新版）（上海教育出版社）（有必修3本+选择性必修4本共7本课本）」「沪外教版高中英语（2020年审核新版）（上海外语教育出版社）（……共7本课本）」。

**[shanghai-secondary-12]（事实，置信度 高）2023 年以前，上海高考英语词表由考试院通过付费出版物发布：年度《普通高等学校招生全国统一考试（上海卷）考试手册》和单独的《高考英语词汇手册（上海卷）》。**
证据：考试院公告（https://www.shmeea.edu.cn/page/02200/20171229/10343.html，访问 2026-11-05）：「《考试手册》的征订工作于今年9月完成」「考试说明分科目和语种，主要包括考试性质、考试目标、考试内容及要求、考试形式与试卷结构等内容」。考试院出版物页（https://www.shmeea.edu.cn/page/07000/20190916/13285.html）：「2020年全国普通高等学校招生统一考试高考英语词汇手册（上海卷）」，上海译文出版社，定价 ￥16.00，拟出版时间 2019 年 5 月。民间版本：上海交通大学出版社《上海高考英语词汇手册》（上海高考命题研究中心编，2016/09，ISBN 978-7-313-15040-0，https://www.jiaodapress.com.cn/Data/BookContent/3118）；译文社《2022 年上海市高中英语考纲词汇手册（便携版）》（2021-8，ISBN 9787532788071，424 页，「新版增加了新型冠状病毒考点高频词汇」，https://book.douban.com/subject/35583255/）。两者页面都没有给出单词/词组总数。

**[shanghai-secondary-13]（事实＋未核实，置信度 低）上海高考词表 2016/2017 年的增删：只在转载词表里见到标记说明（「带 * 为 2017 年新增词汇；加粗下划线/带 △ 为 2016 年新增」），具体增删数字找不到。**
证据：该说明仅出现在搜索引擎对熊猫办公模板页（https://www.tukuppt.com/wordmuban/shanghaigaokaoyingyukaogangcihui.html）的摘要中，页面本体为加密内容无法核对；多轮检索（「上海高考 考纲词汇 2017 新增 个单词 删除」等）均无带数字的来源。结论：找不到。

**[shanghai-secondary-14]（事实＋推断，置信度 中）2023 年起上海高考英语不再发布考纲/考试手册词汇表（「无考纲，无真题」），词汇范围转为教育部《普通高中英语课程标准（2017 年版 2020 年修订）》词汇表加上海市教育考试院公布的 200 个「新高考英语补充词汇」；复旦大学出版社 2024-01《新考纲上海高考英语词汇手册》即按此编写，附录为「新课标 135＋上海 200 词」。**
证据：云台购书页（http://www.yuntaigo.com/book.action?recordid=bnpuYnpsbWM5Nzg3MzA5MTcwNDA1，访问 2026-11-05）：复旦大学出版社，2024-01-01，ISBN 9787309170405，沈传辰；「根据教育部颁发的《普通高中英语课程标准（2017年版2020年修订）》中的词汇要求、上海市教育考试院公布的新高考英语补充词汇」编写；目录「附录1 新课标135+上海200词」。搜索摘要（引自 fudanpress 页面，本体无法抓取）：「上海市教育考试院在2023年额外新增的200个考纲单词」。知乎专栏标题「无考纲，无真题！2023年春考英语难在哪儿」（https://zhuanlan.zhihu.com/p/584683682，正文 403，仅标题与摘要可见）。网上流传的「2024–2025 上海高考词汇手册＝新课标 3000＋考试院补充 200＋原考纲保留 1100≈4300」只出现在搜索引擎摘要里，没有任何可抓取页面原文支持，**未核实**。推断：课标词汇表说明第 1 条「各地可根据实际情况在本词汇表所收词的基础上，再选择增加 200 个单词」（见 [9] 引文）很可能就是上海 200 词的依据。

**[shanghai-secondary-15]（事实，置信度 高）上海高考词表的机读文件：找不到。**
证据：GitHub 仓库搜索 `上海高考 英语 词汇`、`上海高考 词汇手册`、`shanghai gaokao vocabulary` 均 0 结果，`上海 考纲 词汇` 仅命中 zhongkao-words（中考）；lolo811109-crypto 的其他仓库（chuyi-words、gaoer-words 等）是按教材单元的 7A/7B、上外版选择性必修 1–2 册词表（来自墨墨导出，「非出版社官方数据」），不是考纲表；Anki 中文资源网牌组「2024年上海高考英语考纲词汇」为 5,212 词（「新课标词汇」＋「上教版新教材词汇（1-7册）和上外版新教材词汇（1-7册）」，与「吉林大学出版社，红色封面」一致），收费 ￥89、.apkg 503.9 MB（https://file.ankichinas.cn/card/667a83ef60241y5c，访问 2026-11-05），且含教材词，不是考纲表。最接近的替代：(a) 国家课标 3100 词的机读文本（YR7429/english-vocab-cn，已下载，见 [9]）；(b) 考试院 200 补充词——没有官方机读文件，只有教辅附录。

### D. 本项目现用词表的身份

**[shanghai-secondary-16]（事实＋推断，置信度 高/中）`Highschool_edited.txt`（3,446 个词头，纯词头一行一词，2019-12-15～17 入库）属于旧版《普通高等学校招生全国统一考试大纲》英语词汇表（俗称「高考 3500 词」）谱系，不是 2017 课标词表。**
证据：文件头「a / an / abandon / ability / able / abnormal / aboard / abolish / abortion / about / above / abroad / abrupt / absence / absent / absolute / absorb / abstract / absurd / abundant / abuse / academic / academy / accelerate / accent / accept」与 aaaaenglish「高考考纲要求的3500词汇表」（https://www.aaaaenglish.com/fudaojilu/gz/3/3500words，访问 2026-11-05）前 25 词逐词相同；该页也含 abortion、abolish、bungalow、catastrophe、pavement、yummy、zipper、dustbin、sparrow、swap——这些词都在 `Highschool_edited.txt` 里而不在 2017 课标 3100 表里（探针见 `compare2_output.txt`）。与课标 3100（3,091 解析）比：交集 2,574（覆盖课标 83.3%），仅 Highschool 872（例：abolish, alike, athletic, bravery, classify, criteria, drawback, favor, govern, humorous, luggage, muddy, ox, portable, receiver, seashell, sparrow, swap, translator, vcd），仅课标 517（例：a, boost, claim, cooperate, detail, election, essential, facility, gender, housing, instance, later, marine, mrs, ought to, precisely, recently, safety, stability, threaten）。入库日期（GitHub commits 页 `committedDate`：2019-12-15/17）早于 2020 年起各省以课标取代考试大纲。「哪一年版的考试大纲」无法判定（置信度 中）；mahavivo README 对此文件只字未提。

**[shanghai-secondary-17]（事实＋推断，置信度 低-中）`中考英语词汇表.txt`（1,976 行、1,887 个词头，带音标/词性/释义，2021-06-09 入库）不是 2011/2022 课标 1600 表，也不是上海表；更像一份按教材汇编的「中考词汇」合集，来源无法确认。**
证据：结构：26 个单字母节标题，70 个大写词头含月份、星期、国家/民族（Africa, America, Arab, Canada, Frenchman, Korea, Tokyo…），8 个多词条目（computer game, fruit juice, Middle East, Olympic Games, the Pacific Ocean, swimming pool…），一处明显录入错误「really v [ˈrɪəlɪ] ad.」。与课标 1600（1,591）比：交集 1,272（占本表 67.4%），仅本表 615（例：advertisement, beg, captain, crop, discovery, enjoyable, february, frighten, handwriting, inspect, lip, monument, noisily, pause, quarrel, seagull, southeast, tale, tough, unusual），仅课标 319（例：absent, aim, aware, biscuit, central, coach, creative, driver, fair, glue, ice cream, lightning, method, per cent, prince, relative, shock, spend, tennis, virus）。与上海表交集 1,286（见 [8]）。中国教育在线 2013 年的「中考英语要求掌握的1600词汇表」（https://chuzhong.eol.cn/xxzy/chusan/csyy/201311/t20131127_1044951.shtml）前 30 词含 according to、achieve、add、address、advise、agreement，本文件开头没有这些而有 afford、Africa、aircraft，可排除同源。行数 1,976 与网上流传的「中考英语1976词」（CSDN，页面 521 无法读取）相符，可能是同一合集（推断）。mahavivo README 只说明了四六级/台湾/托福 GRE 等来源，对本文件没有说明。

> **核验修正（INDEX §3 #5，2026-11-05）**：多词条目按 `parse_list` 逻辑只有 6 个（computer game、fruit juice、Middle East、Olympic Games、the Pacific Ocean、swimming pool），不是 8 个；1,887 词头 = `stats.json` 口径 = 库中 `sources` 含 zk 的词数，100% 在库；其余计数确认，来源仍未知，依据 verify/shanghai-secondary.md [shanghai-secondary-17]、verify/list-sources.md [list-sources-7]。

**[shanghai-secondary-18]（事实，置信度 高）本项目的阶段模型把两份全国文件硬编码为 zk/gk 两个阶段，且阶段集合、CHECK 约束、文案均为固定四档，仓库中没有任何「地区/省份」概念。**
证据：`scripts/build_seed.py:82-83`：`"zk": parse_list(os.path.join(L, "中考英语词汇表.txt"), "rich"), "gk": parse_list(os.path.join(L, "Highschool_edited.txt"), "plain")`；`backend/wd/seed.py:43`：`STAGES: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")`，`:204-208` 写入 `stage_zk/stage_gk/stage_cet4/stage_cet6` 与 `stage_min = STAGES.index(stages[0]) + 1`；`docs/SCHEMA.sql:147-148`：`stages_json … non-empty subset of zk/gk/cet4/cet6`、`current_stage INTEGER NOT NULL DEFAULT 3 CHECK (current_stage BETWEEN 1 AND 4)`；`:181`、`:185`：`stage_zk … CHECK (stage_zk IN (0,1))`、`stage_min INTEGER CHECK (stage_min BETWEEN 1 AND 4)`；`backend/wd/schemas.py:52`：`STAGE_NAMES_ZH = {"zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}`，`:56-57` `stage_to_index` 「zk→1, gk→2, cet4→3, cet6→4」；`frontend/src/i18n/zh.ts:28`：`stages: { zk: '初中', gk: '高中', … zkFull: '初中（中考）', gkFull: '高中（高考）' }`，`:86` 自述「词表范围：中考、高考、大学英语四级与六级大纲」。`grep -rn "上海|Shanghai|省份|province|地区版" docs backend frontend/src` 只命中 `Asia/Shanghai` 时区。`data/seed/ATTRIBUTION.md`：「Only the head words are used to decide stage membership」。

### E. 与线上库的覆盖率

**[shanghai-secondary-19]（事实，置信度 高）上海 2020 词表 1,731 词中 1,702 个（98.3%）已在 `words.lemma` 里；但其中只有 1,393 个（占上海表 80.5%）被标为 `stage_zk=1`，另有 309 个在库却未标初中（stage_min=2：236，=3：59，=4：14）；缺 29 个。反向看，库里 2,099 个 zk 词有 706 个（33.6%）不在上海表里。**
SQL（`compare2.py`，上海词头先写入内存表 `sh_zk(word)`，再 `ATTACH 'file:live-copy.db?mode=ro' AS live`）：
`SELECT count(*) FROM sh_zk l JOIN live.words w ON w.lemma = l.word;` → 1702；
`SELECT w.stage_min, count(*) FROM sh_zk l JOIN live.words w ON w.lemma=l.word GROUP BY 1;` → (1,1393),(2,236),(3,59),(4,14)；
`SELECT count(*) FROM live.words w WHERE w.stage_zk=1 AND w.lemma NOT IN (SELECT word FROM sh_zk);` → 706。
缺的 29 个：angrily, beautifully, bund, café, carefully, dancer, dishonest, embarrassed, excited, frightened, frightening, frozen, hot-dog, lost, luckily, mr, mrs, o’clock, politely, quietly, satisfied, satisfying, seafood, stuck, surprised, underlined, unforgettable, united, yogurt——多为派生副词/分词形容词（ECDICT 未单列）、专名（bund＝外滩）、拼写变体（hot-dog、yogurt）。在库但未标 zk 的 20 例：accurate, amusing, battle, cave, collection, debate, dull, extra, freezing, honey, kindergarten, major, occupation, pineapple, project, relative, root, settle, support, unhealthy。

> **核验修正（INDEX §3 #4，2026-11-05）**：SQL 结果全部复现，但「缺 29 个」需拆分：`o’clock` 是弯引号未归一化的假缺（库里有 `o'clock`，stage_min=1、stage_zk=1；归一化后在库应为 1,703、标 zk 1,394）；`café`→`cafe`（在库，stage_min=3）、`yogurt`→`yoghurt`（在库，stage_min=2）是拼写变体；12 个是库中原形的屈折形式且已在 `word_forms`（embarrassed/excited/frightened/frightening/frozen/lost/satisfied/satisfying/stuck/surprised/underlined/united，其中 9 个原形已 stage_zk=1）；真缺只有 14 个：angrily、beautifully、bund、carefully、dancer、dishonest、hot-dog（`hot dog` 也不在库）、luckily、mr、mrs、politely、quietly、seafood、unforgettable，依据 verify/shanghai-secondary.md [shanghai-secondary-19]、O5。

**[shanghai-secondary-20]（事实，置信度 高）国家课标词表的覆盖：1600 表 1,580/1,591（99.3%，缺 according, dining, excited, kung fu, lost, mr, mrs, ms, per cent, teenage, tofu）；3100 表 3,063/3,091（99.1%，缺 28 个，如 bce, calligraphy, ce, confucius, confused, drone, due to, empathy, endangered, lifestyle, mobile phone, pagoda, wetland, wi-fi…）；3100 表在库的词里 2,621 个已 `stage_gk=1`（84.8%），442 个未标高中。**
SQL 同上（表 `kb1600`/`kb3100`）；`SELECT count(*) FROM kb3100 l JOIN live.words w ON w.lemma=l.word WHERE w.stage_gk=1;` → 2621。两份 mahavivo 文件本身 100% 在库（1887/1887、3446/3446），与 `stats.json` 的 `missing_from_ecdict` 仅 cet46 一词一致。

**[shanghai-secondary-21]（事实，置信度 高）上海初中表 1,731 词中 1,583 个（91.5%）落在全国高考表 `Highschool_edited` 内；仅上海 148 个（例：actually, better, china, contest, detail, embarrassed, exciting, fisherman, happily, including, kilometre, lost, mrs, pearl, proverb, responsible, sauce, snack, survey, united）。**
计算：`compare2.py` 「上海初中2020 vs Highschool_edited」块；1583/1731=91.5%。

### F. 许可与来源风险

**[shanghai-secondary-22]（事实，置信度 高）各来源的许可状态：mahavivo/english-wordlists 无许可证（GitHub API `license: None`，README 未声明；仅对四六级/台湾表注明出处）；lolo811109-crypto/zhongkao-words 代码 MIT、词库/释义/插画/录音 CC BY 4.0 并声明「单个英文单词与通用词表本身不主张专有权」，内容为 AI 生成「未逐条人工审校」；YR7429/english-vocab-cn README 第 60 行「授权条款（代码 MIT / 内容 CC BY-SA 4.0）」；KyleBing/english-vocabulary BSD-3-Clause（本次只作参考，未用于统计）。**
证据：zhongkao-words `CONTENT_LICENSE.md`（访问 2026-11-05）：「以下内容以 Creative Commons Attribution 4.0 International (CC BY 4.0) 提供，在项目维护者能够授予的权利范围内」「单个英文单词与通用词表本身不主张专有权」「内容由 AI 模型按项目规范生成……未逐条人工审校，按现状提供」。

**[shanghai-secondary-23]（事实＋推断，置信度 中）考纲词表的法律性质：考试院网站免费发布的《评价指南》《考试说明》属行政机关发布的考试文件，中国《著作权法》第五条将「国家机关的……其他具有立法、行政、司法性质的文件」排除在保护之外；但词表实际随付费出版的《考试手册》《词汇手册》发行，手册中的释义、例句、用法属出版社/编者的编辑性内容。仅复用词头（不含释义）风险低，复用释义/例句/星标/分级风险高。以下为推断，不构成法律意见。**
证据：中国政府网《中华人民共和国著作权法》（2020 年 11 月 11 日修正，https://www.gov.cn/guoqing/2021-10/29/content_5647633.htm，访问 2026-11-05）第五条全文：「本法不适用于：（一）法律、法规，国家机关的决议、决定、命令和其他具有立法、行政、司法性质的文件，及其官方正式译文；（二）单纯事实消息；（三）历法、通用数表、通用表格和公式。」推断链：① 上海市教育考试院是市教委所属考试机构，其《评价指南》《考试说明》是否构成第五条（一）项的「文件」存在解释空间；② 词表作为对公众公开的考试范围，词头选择本身独创性极低，即使不落入第五条，单纯的词头列表也难以构成受保护的「作品」（与 zhongkao-words 的声明一致）；③ 本项目现有做法——只取词头判定阶段、释义来自 MIT 许可的 ECDICT——与此一致（`ATTRIBUTION.md`）；④ 但 2020 年 PDF 来源未知（mahavivo 未注明），若直接分发该 PDF 或其释义栏，风险转为出版物复制。另需注意：2023 年后上海高考词表基础是教育部课标（教育部文件，第五条更明确适用），而考试院 200 补充词目前只见于教辅附录，来源页不可得。

---

## 未解决的问题

1. 上海中考《考试手册》（考试院）的出版社、定价、是否可公开购买未能从考试院页面核实；2026 年版 1,785 词 + 347 词组的词表没有任何机读副本，手头机读版只有 2020 年版（1,731 词）。
2. mahavivo 的《上海市初中英语词汇表（2020年版）.pdf》的原始出处（考试手册扫描？教研室文件？）不明；「＝2020 年考试手册词表」仅凭词数 1733 吻合推断。
3. 上海高考 2023 年起的 200 个考试院补充词：官方发布文件（通知/考试说明）没有找到，也没有机读列表；「新课标 135＋上海 200」的 135 词是什么（2020 修订新增？）未核实；「4300＝3000＋200＋1100」说法未核实。
4. 2016/2017 年上海高考词表增删的具体数字：找不到。
5. `中考英语词汇表.txt` 的真实来源（哪一年、哪套教材/地区）未能确认；是否与「中考英语1976词」同源只是推断。
6. 上海 2004 年课程标准在 2022 年国家义务教育课标发布后是否仍是中考的正式依据：2020 版评价指南仍引 2004 标准，2025 年考试院点评只说「遵循课程标准」，未指明版本。
7. 《上海市初中/高中英语学科教学基本要求（试验本）》的词汇表均未见电子版，无法量化它们与考纲/课标的差异（只有教辅给出的 129 词）。
8. 产品层面（非本任务范围，供后续决定）：上海初中表的 445 个「仅上海」词与 309 个「在库未标初中」词是否要作为新阶段/标签接入；上海中考 335–347 个词组与现行 `words` 表（seed 仅 13 个多词条目，`stats.json` `multiword: 13`）的关系；以及 2023 年后上海高考不再有独立词表时，`gk` 阶段应改以课标 3100（+200）为准还是沿用旧 3500。
