# verify/shanghai-primary — 对 `facts/shanghai-primary.md` 的对抗性核验

基线：仓库 `/Users/sqin/word-dance` main @ 75df534（`git rev-parse --short HEAD`）；线上库只读副本 `scratchpad/live-copy.db`（`sqlite3 -readonly … "select count(*) from words"` = 9,162；`stage_min` 分布 1:2099 / 2:1792 / 3:1577 / 4:3694；`word_forms` 14,103 行）；核验日期 2026-11-05。本文只核验，不改代码。

## 范围与方法

- **读了什么**：被核验文件全文（22 条结论 + 8 个未解决问题），22 条全部逐条复核。
- **代码**：用 `grep -n` 重新定位 `scripts/build_seed.py`、`backend/wd/migrations/0001_init.sql`、`backend/wd/schemas.py`、`frontend/src/api/types.ts`、`frontend/src/components/word/StageChips.tsx`、`frontend/src/pages/WelcomePage.tsx` 中被引用的每一行；再用 `grep -rn --include='*.py' --include='*.ts' --include='*.tsx'` 全库搜 `cet6`/`STAGE_ORDER`/`stage_min`/`stage_to_index`/`STAGE_INDEX`，找作者未列出的硬编码点。
- **作者下载件**（`scratchpad/shanghai-primary/…`）：重算 sha256（`OXFORD.apkg` = `e5eb6e65d0974e5d27218f289378f32c29357c46876b4d46bb687ea6cbc866a1`、`english_std_2022.pdf` = `59ec3971e0dbd6ca487c4e4972cbc80effaf2fd62418d07e5f62c6698fa222fb`，与原文一致）；自写 `scratchpad/verify-shanghai-primary/recount.py`、`repro.py`（`python3 -I`，SQLite 以 `?immutable=1` 只读打开）重算 Anki 牌组、mahavivo、PEP、OCR 词表与 live 库的全部计数；`sed -n`/`grep -n` 重读 `edu_sh/` 目录文本、`moe/ocr_*.txt`、`moe/notice.html`、`analyze_anki.py`。
- **我自己的下载**（全部放在 `scratchpad/verify-shanghai-primary/dl/<n>/` 各自空目录，只用 `pdftotext -layout` / `textutil -convert txt` 转文本或 `python3 -I` 解析，未执行任何下载内容）：edu.sh.gov.cn 搜索命中的 6 个 .doc/.docx + 5 个 PDF（`dl/1–11`：2025/2024 学年校历、2025 中职学业考细则、沪教委基〔2011〕56 号课程计划、〔2018〕60 号、《上海市中高职贯通教育英语课程标准》、2025 春/2026 春/2025 秋编写目录、2021 春小学预订单）；shnu 两个 PDF（`dl/12–13`）；forum.freemdict.com 的《义务教育英语课程标准 日常修订版（2022年版2025年修订）》.docx（`dl/14`，966,786 B；`docProps/core.xml` 显示由 Apache POI / HUAWEI 于 2025-11-10 生成——**用户转录件，非官方**）。GitHub：`api.github.com/search/repositories`（q=牛津上海版 / 沪教版 小学 / 上海 小学 英语 单词，UA `word-dance-research`；之后 core 配额为 0）、`github.com/angelachen825-bit/baicizhan` 及其 `tree/main/js` HTML、`raw.githubusercontent.com` 的 `index.html`、`js/app.js`、`js/wordbank.js`（`scratchpad/verify-shanghai-primary/gh/`、`gh2/`）。
- **WebFetch（访问 2026-11-05）**：maimemo.com rankbooks ×2、screle.shisu.edu.cn ×2、edu.sh.gov.cn 说明页、sohu、book.douban.com、apps.apple.com ×2、sspai、m.163.com、renrendoc、mianfeiwendang、gov.cn 著作权法、m.thepaper.cn；`mip.21cnjy.com/P/4673770.html` 两次超时。**WebSearch 10 次**（"上海市小学英语学科教学基本要求"、2025 学年度课程计划、2024 新教材、2022 课标词表 505、牛津上海版 1A–5B 词量、教育部 2025 教学用书目录、2004 试行稿核心词汇表、沪教版 2024 一年级单词表、"2022年版2025年修订"、2024 学年度课程计划），随后会话搜索配额耗尽——下文「搜索配额耗尽」处均因此停止。
- 置信度标注同原文：高 = 一手文件/本地复算；中 = 可互证的二手；低 = 单一二手。「事实」与「推断」分开标注。

---

## 逐条核验（保留原编号）

### [shanghai-primary-1] 五四学制 —— **事实确认；推断修正**
- 事实确认（高）：`scratchpad/shanghai-primary/edu_sh/docs/wusi_xuezhi.txt` 第 14 行原文与引文逐字一致；第 7 行「沪教委基〔2015〕35号」、第 16 行「原《…实行五四学制的通知》（沪教委基〔2004〕50号）同时废止」、第 22 行「2015年4月23日」。
- 作者漏引同文件第 16 行：「本文件发布之日起施行，**有效期5年**。」→ 该通知按自身条款 2020-04 到期，现行依据应是后续文件，本次未找到（搜索配额耗尽）。五四学制事实不受影响：沪教委基〔2021〕32 号课程计划仍按「小学一、二年级…三、四、五年级」「六至九年级」编排（`edu_sh/pdfs/p7.txt` 第 125、232、294 行）。
- 推断修正（高）：作者推断「国家课标二级（5–6 年级）在上海跨越了小学五年级与初中六年级」是按年级数字对号。2022 课标对五四学制有明文映射：PDF 第 18 页（`moe/ocr_001_100.txt` 第 791–794 行，`## PAGE pages/p-018.png` 之后）「“五四”学制3~5年级目标主要参照“六三”学制5～6年级目标确定，适当降低要求。“五四”学制6～7年级目标在“六三”学制5~6年级目标基础上合理提高要求，并结合“六三”学制7~9年级目标确定」；第 20 页（第 850–852 行）「“五四”学制3~5年级课程内容应覆盖“六三”学制3~6年级大部分课程内容，其余课程内容在“五四”学制6~9年级中安排」。**正确说法：二级（505 词）对应上海小学毕业（五年级末，要求略降），六年级起进入三级进阶**；freemdict 转录件同段文字一致。

### [shanghai-primary-2] 一年级开设英语 —— **确认（高）**
- `edu_sh/docs/kcbz_shuoming.txt` 第 22 行「本市从1999年起在部分小学一年级进行外语教学的试验（以听说活动为主），至今所有小学的一年级都开设了外语课。」；第 37–39 行三学段划分。WebFetch https://edu.sh.gov.cn/zcjd_area_257/20200706/0015-xw_18836.html （访问 2026-11-05）：标题「《上海市中小学英语课程标准》说明」、发布日期 2005-01-11、附件即同一 .doc。
- `moe/ocr_kcfa_1_30.txt` 第 222–223 行「小学阶段开设英语，起始年级为三年级；有条件的地区和学校可在一至二年级开设，以听说为主。」；该 PDF 文件名 `W020220420582343217634.pdf` 与通知页附件一致。

### [shanghai-primary-3] 小学期末考试仅限语文数学 —— **确认（高；年份待查）**
- `edu_sh/pdfs/p7.txt` 第 123–126 行原文一致（作者写 124–126，起始行差 1）；第 3 行「沪教委基〔2021〕32 号」、第 9 行「2021 学年度课程计划及其说明的通知」。
- 口径/年份：这是 **2021 学年度**版本。上海 2011（沪教委基〔2011〕56 号，`dl/5`）、2017、2019 年都另发过课程计划；2023/2025 学年度是否有新版、条款是否变化——搜索只命中 2024/2025 学年校历（沪教委基〔2024〕9 号、〔2025〕13 号，`dl/1–2`），随后配额耗尽。**不能确认〔2021〕32 号仍是现行文本**。

### [shanghai-primary-4] 2004 课标 K/X 词汇量 —— **确认（高）**
- `kcbz_shuoming.txt` 第 54–60 行（作者写 55–60）：公式与「小学毕业生核心词汇量不少于500词，总词汇量不少于600词；初中…1600/2100；高中…2300/4200」及「没有固定的词汇表」逐字一致。
- WebFetch https://www.sohu.com/a/403938881_503508 （访问 2026-11-05，2020-06-23）：「小学毕业时，要求掌握的核心词汇量不少于500词，总词汇量不少于600词。」「（数据来自：上海中小学英语课程标准）」。
- 口径提醒：2004 征求意见稿「说明」，K 表本身未见；与 2022 国家课标二级 505 词同量级，但不是同一张表。

### [shanghai-primary-5] 小学版《教学基本要求》未找到 —— **确认（中）**
- WebFetch https://book.douban.com/subject/35139941/ （访问 2026-11-05）：书名《上海市初中英语学科教学基本要求》、作者「上海市教育委员会教学研究室」、上海教育出版社、2016、ISBN 9787544472685、179 页（页面另注「试验本」、12.35 元）。
- 我方 WebSearch `"上海市小学英语学科教学基本要求"` 9 条命中全是高校/成教文件（`dl/12`《上海市继续教育外语水平考试大纲（试行）》、`dl/13` 上师大英语师范培养方案等），无小学版记录——与作者一致。

### [shanghai-primary-6] 2022 课标 505 / 1600 / 1095 —— **确认（高）**
- OCR 行号→页面全部对上：第 277 行（p-013）「一级建议3~4年级…二级建议为5~6年级…三级建议为7~9年级」；第 1153 行（p-027）「3. 能初步运用500个左右单词（见附录3）…100~300个单词」；第 1162 行（p-027）「约1600个单词」；第 1172 行（p-028）「约1800个单词」；第 3271 行（p-094，前一页印刷页码 86 → 本页印刷 87）「本词汇表收录505个单词」；第 3286 行「8. 本词汇表不列词组和短语。」；`ocr_101_201.txt` 第 122–123 行（q-105，前页印刷 97 → 印刷 98）「共收录1600 个单词，含二级词汇 505个（用“*”标出），确定1095个单词为初中阶段」。
- `moe/notice.html`：`<title>教育部关于印发义务教育课程方案和课程标准（2022年版）的通知…</title>`、「教材〔2022〕2号」、附件 `W020220420582349487953.pdf` = 义务教育英语课程标准（2022年版）。WebFetch https://m.163.com/dy/article/HB20L7VV0536EPBU.html （访问 2026-11-05，2022-06-29）含「能初步运用500个左右单词」「约1600个单词」，无 505/1095——作者描述准确。年份风险见遗漏 3。

### [shanghai-primary-7] 2024 秋以前两套教材择一 —— **确认（高，附口径）**
- `edu_sh/pdfs/p1.txt` 第 54–84 行：`SD－XS－2024001 英语（一年级上册） 沪教育`；牛津上海版 `Ⅱ－XB－2021022（二/一）`、`2017013（三/一）`、`2017014（四/一）`、`2021023（五/一）`；新世纪版 `Ⅱ－XB－2020010 / 2022006 / 2020012 / 2020013`，版别「沪外教 / 沪外音」，备注「由学校选一种使用，含配套资源」——与原文一致。
- 口径：p1 标题是「2024年秋季上海市**编写**教学用书目录」；沪教委基〔2024〕26 号（`edu_sh/docs2/autumn2024.txt` 第 18 行）写明完整目录 =「教育部印发的中小学教学用书目录」+「上海市编写教学用书目录」。因此「目录中没有人教 PEP」只对上海编写部分成立（按定义不含国家目录教材）；但 2–5 年级英语的「由学校选一种使用」只指这两套，结论实质不变。

### [shanghai-primary-8] 2024 起新编五四制教材逐年替换 —— **确认（高）**
- 逐条核对：p6（2025 春）第 58 行「待审 英语（一年级下册） 沪教育」；`edu_sh/catalog_2026spring.txt` 第 54 行「SD－XS－2024002 英语（一年级下册）」、第 56 行「待审 英语（二年级下册）」；p3（2025 秋）第 53/55 行 `SD－XS－2024001`/`2025001`、第 56–71 行三至五年级仍牛津/新世纪、第 438–442 行「SD－CX－2025005 …英语练习部分（八年级上册）」与「英语（牛津上海版）（试用本）Ⅱ－CB－2016004 九年级第一学期」；p2（2026 秋）第 51–70 行 `SD－XS－2024001`、`SD－XS－2025001`、「SD－XX－2025005 义务教育教科书（五·四学制）·英语 练习部分（三年级上册）」及四、五年级「待审」，第 3 行「（不包含教育部印发的中小学教学用书目录）」，`grep -c '牛津上海版\|新世纪版'` = 0。
- WebFetch https://screle.shisu.edu.cn/ea/df/c16360a191199/page.htm （访问 2026-11-05）：「由上海教育出版社出版的《义务教育教科书（五•四学制）•英语》小学英语教材一年级上册已于2024年9月投入使用。」标题含「（一年级上册～五年级下册）」，页面日期 2024-12-30。
- 作者的推断「三至九年级学生用书已入国家目录」得到一手旁证（作者未引）：2022 课标 PDF 第 76 页（OCR 第 2779–2782 行）「义务教育英语教材包括供“六三”学制和“五四”学制使用的两种版本。…1～2年级教材以听说为主，纳入地方课程教材管理。」——这正解释为何一、二年级学生用书列在上海目录，三年级起只列「练习部分」。

### [shanghai-primary-9] 牛津上海版每册 4 Module × 3 Unit —— **无法核验（App Store 部分确认）**
- WebFetch https://apps.apple.com/cn/app/id1616878486 （访问 2026-11-05）描述原文一致。「四个模块、十二个单元」仅来自搜索摘要；`https://mip.21cnjy.com/P/4673770.html` 两次 WebFetch 超时，搜索配额耗尽，未找到出版社原文。维持「中/低」。

### [shanghai-primary-10] 墨墨各册词汇量 —— **确认（高，页面为非官方）**
- WebFetch https://www.maimemo.com/rankbooks?bookid=1&uid=152 （访问 2026-11-05，两次）：牛津上海版 1A–5B = 50/47/41/55/82/68/121/98/95/115（Σ = 772，复算一致）；6A–9B = 182/231/208/214/240/242/218/168（Σ = 1,703）；「沪教版一年级上册 59 / 一年级下册 64 / 二年级上册 42 / 二年级下册 43 / 五四学制三年级上册 159 / 四年级上册 141 / 五年级上册 113 / 六年级上册 299 / 六年级下册 282 / 七年级上册 270 / 七年级下册 292 / 八年级下册 215 / 九年级上册 203」均在；作者漏列「沪教版五四学制八年级上册 271」；页面共 2,791 本词书、无日期。
- 口径：墨墨「词汇量」= 词书条目数（可含短语），不是去重单词数；作者已按「按册相加，未去重」表述。

### [shanghai-primary-11] 两份整理稿 —— **确认（中）**
- WebFetch https://www.renrendoc.com/paper/99541152.html （访问 2026-11-05）：《上海版小学英语牛津词汇表(带音标)》、17 页、2020-10-23、DOC、到「五年级上册」为止、未写总词数。WebFetch https://www.mianfeiwendang.com/doc/22e5a39543fcb62eee13f992 ：《牛津小学英语上海版单词表[1A-2B][3A-3B]》、24 页、1A 以 morning afternoon book ruler pencil rubber pen bag 开头、未写总词数。

### [shanghai-primary-12] Anki 牌组结构 —— **确认（高）**
- `recount.py` 复算：notes 1,042；NFKC+小写+压空格后唯一 1,040；重复 `french fries`、`like`；含空格 200、连字符 14、「→」41、首字母大写 64、背面含 `[` 927；作者的词性正则（见 `analyze_anki.py`）复跑 = 716；tags 全为 ` Obsidian_to_Anki `。微差：`decks` 表有 `Default` 与 `OXFORD` 两行（`Default` 为 Anki 内置空牌组），「仅 1 个 deck」可接受。
- 仓库元数据（我方 `api.github.com/search/repositories?q=牛津上海版`）：created/pushed 2025-03-08、license null、描述「上海版牛津小学英语全部单词带音标 anki deck」、stars 0。

### [shanghai-primary-13] 牌组与线上库重合 —— **确认（高，±1）**
- 复算：精确匹配 `words.lemma` 771 / 不在库 269 / 空格↔连字符变体后 263；其中含空格、「→」或句末标点者 203（作者「约 207」，定义差）。单词条目：按「字母/撇号/连字符」正则 824 个、在库 769、不在库 55、`stage_min` 1/2/3/4 = 671/68/19/11、屈折 15（名单与作者完全一致）；若允许句点则 828 / 770 / 672（多出 `mr.`）。作者的 825 / 769 / 56 / 41 介于两者之间，差异只来自 `catc(bus)`、`noodle(s)`、`underground.` 一类残缺条目的过滤。`frq > 5000` 者 130 一致。结论（≈93% 在库、87% 已 `stage_zk=1`、不能用 `frq` 阈值近似小学词）成立。

### [shanghai-primary-14] qwerty-learner 词书 —— **确认（高）**
- `api/qwerty_dictionary.ts`：`SHjuniormiddleOxford` length 1270、`shanghai-6-2word` length 274（tags `['上海版']`）、PEP 8 册 64/72/84/104/131/156/130/108、新起点 12 册、`Cambridge_JOIN_IN` 1350；`api/qwerty_dicts_dir.json` 380 个文件，含 `Oxford` 的只有 `Oxford3000/5000.json`、`OxfordVocabulary_juniorMiddleSH.json`；`4/shanghai-6-2-word.json` 274 条、首条 `different`。条目总数我方正则得 376（含重复 id 如 `Oxford5000`），作者 361——解析口径差，不影响结论。

### [shanghai-primary-15] kajweb/dict —— **确认（高）**
- `api/kajweb_README.md`：`grep 牛津|上海|沪教|Oxford|Shanghai` = 0；第 257–264 行 8 册 64/72/84/104/131/156/130/108。

### [shanghai-primary-16] mahavivo 小学词表 441 —— **确认（高）**
- 441 行 / 441 唯一 / 2,518 B；含空格 2（`physical education`、`ice cream`，作者只举一例，数量一致）；10 个首字母大写名单一致；在库 431，缺的 10 个名单一致；与牌组重合 317。补充见遗漏 2（与 2022 二级 505 词重合 415）。

### [shanghai-primary-17] ECDICT 无小学标签 —— **确认（高，行号微调）**
- `scripts/build_seed.py:105-106` 才是 LIKE 查询（作者写 104–106，第 104 行是 `missing = collections.defaultdict(list)`）；`:112` `stage_from_list = {"zk": "zk", "gk": "gk", "cet4": "cet4", "cet6": "cet6"}`，`:125-126` `rec["stages"].append(stage)`；另第 147 行 `rec["stages"] = [s for s in ("zk", "gk", "cet4", "cet6") if s in rec["stages"]]` 同样硬编码顺序。`api/ecdict_README.md:40`「| tag | 字符串标签：zk/中考，gk/高考，cet4/四级 等等标签，空格分割 |」。

### [shanghai-primary-18] GitHub 其他仓库 —— **确认（高）+ 补充**
- `search/repositories?q=牛津上海版` 共 4 个仓库（`lolo811109-crypto/chuyi-words`、`djfml/englishoxfordshanghaiedition`、两个无关），小学侧确只有 djfml；`q=沪教版 小学` 2 个均为数学仓库。
- 作者「未能列出」的 `angelachen825-bit/baicizhan`，本次经 github.com HTML + raw 取回：标题「百词斩 - 沪教牛津版小学英语背单词应用」，数据在 `js/wordbank.js`（88,226 B，首行注释「沪教牛津版小学英语词库 [word, meaning, pos, example_en, example_cn]」），键为「四年级上册…六年级下册」、`Unit1…Unit12`，无 Module、无一至三年级——即**六年制、三年级起点的「沪教牛津版」（广东/深圳用）**，不是上海五四制牛津上海版，印证作者的命名陷阱；词条含自撰例句、无来源声明。

### [shanghai-primary-19] 商业 App 自制词书 —— **确认（中）**
- WebFetch https://sspai.com/post/87587 （访问 2026-11-05，2024-03-27）：墨墨「自己自制的词书也可以在墨墨中进行添加」、百词斩「无法自己上传词书」、扇贝「只能将自制词书上传使用」、不背单词「也支持用户自己自制词书进行上传使用」、墨墨「词书涵盖小学、初中、高中、大学四六级」。

### [shanghai-primary-20] 人教 PEP 词量 —— **确认（高）**
- 8 册 64/72/84/104/131/156/130/108，合计 849、唯一 819、含空格 110、在库 631、不在库 188；字段 `name/trans/ukphone/usphone`、首条 `ruler`。yywords「837」：作者保存的 `web/yywords_1562.html` 中无「837」字样，维持「未核实」。补充：PEP 819 与 2022 二级 505 词重合 360。

### [shanghai-primary-21] 二级词表 OCR 与推断 —— **修正（推断已可定量）**
- OCR 部分确认：247 行 / 247 唯一；在库 240（`stage_min` 1=235、2=5）；不在库 7 = 6 个乱码 + `excited`；与牌组重合 170 / 77。
- 修正点：完整词表已可机读。freemdict 转录 docx（`dl/14`）的附录 3 二级词汇表是两栏、制表符分隔文本，`scratchpad/verify-shanghai-primary/docx_tabs.py` 解析得 **505 个词条**（503 个常规 + 「a/ an」拆为 a、an；去掉误入的栏目字母 w），与「说明」第 1 条「本词汇表收录505个单词」吻合，结果存 `verify-shanghai-primary/level2_505_from_docx.txt`。对照 live 库：**499/505 精确等于 `words.lemma`；`o' clock`（转录件多一空格）对应库内 `o'clock`，实际 500/505 = 99.0%**；未在库 5 个 = `mr, mrs, ms, pe`（称谓/缩写）+ `excited`（`word_forms` 中有，原形 `excite` 在库）。在库 500 词 `stage_min`：1 = 495、2 = 3（`an`、`astronaut`、`maths`）、3 = 1（`best`）、4 = 1（`chore`）。**作者「≈97% 在库、几乎全为 stage_zk=1」应改为 99.0% 在库、99.0% 为 stage_min=1**。
- 另：OCR 247 词中 234 在 505 表内；其余 13 个 = 6 个乱码 + 7 个注释碎片（`a, an, are, cream, education, physical, o'clock`，来自「a/ an」「be (am, is, are)」「PE (= physical education)」「ice cream」）——作者的 OCR 结果混入了非词目。
- 口径提醒：转录件是论坛用户 2025-11-10 生成的非官方文本，自称「2022年版2025年修订」（见遗漏 3）；已抽样 234 个 OCR 词全部一致，但用于产品前仍应与官方扫描件逐页核对。

### [shanghai-primary-22] 四阶段硬编码 —— **确认（高，但清单不完整）**
- 行号全部核对无误：`backend/wd/migrations/0001_init.sql:147` `stages_json … DEFAULT '["cet4","cet6"]'`；`:148` `current_stage INTEGER NOT NULL DEFAULT 3 CHECK (current_stage BETWEEN 1 AND 4)`；`:181-185` 四个 `stage_*` 列 + `stage_min INTEGER CHECK (stage_min BETWEEN 1 AND 4)`；`:207` `ix_words_stage_min`；`backend/wd/schemas.py:25-26`、`:51-52`、`:56`、`:64-65`（`if not 1 <= int(index) <= 4`）；`frontend/src/api/types.ts:5,45`；`frontend/src/components/word/StageChips.tsx:7-9`；`frontend/src/pages/WelcomePage.tsx:30-40`。
- 但「耦合点」只列了 schema/类型层，后端服务层与脚本里还有十余处，见遗漏 4、5。

---

## 作者遗漏的重要事实

1. **（高，事实）2022 课标对五四学制有专门条款，直接决定「小学」阶段的目标映射与教材归口。** 证据：`moe/ocr_001_100.txt` 第 791–794 行（PDF 第 18 页）、第 850–852 行（第 20 页）见 [1]；第 834–836 行（第 20 页）「兼顾小学英语开设起始年级区域差异，设置预备级和三个“级别＋”…预备级主要满足1~2年级教学需要，以视听说为主。」；第 2779–2782 行（第 76 页）「“五四”学制6年级教材的内容与体例要求等应符合初中学生的学习和生活特点。1～2年级教材以听说为主，纳入地方课程教材管理。」推断：上海小学 1–2 年级没有国家词表（预备级无词表），3–5 年级目标 ≈ 二级 505 词略降；这改变 [1] 的推断，也解释 [8] 的目录结构。
2. **（高，事实）二级 505 词已有带文字层的完整版本，且与现有词库/词表的关系可以定量。** 方法与数字见 [21]。进一步对照（`docx_tabs.py` 输出）：505 词与牌组重合 349（牌组未覆盖 155 个，如 `again, always, beautiful, brother, father, hello, hospital, internet…`）；与 mahavivo 441 重合 **415**，mahavivo 独有 26 个全是 `a/am/an/are/is/i/has` 类功能词、屈折形式（`children, feet, men, women`）或美式拼写/口语体（`color, favorite, math, mom, mum, dad, grandma, grandpa, bicycle, bye, crayon, pupil, afraid, high, physical education`）→ mahavivo 词表基本是某版课标二级表的子集，不是独立来源；与 PEP 819 重合 360。推断：「小学」阶段核心应以课标二级表为骨架，教材词表只补具体名词；仅靠现有 `stage_zk` 标记不能推出小学词——live 库里 `an` 的 `stage_min=2、stage_zk=0`（`sqlite3 -readonly live-copy.db "select lemma,stage_min,stage_zk from words where lemma in ('a','an')"` → `a|1|1`、`an|2|0`），说明中考表∪ECDICT 在最基础词上有漏标。
3. **（中，事实）2022 课标可能已有 2025 年「日常修订」版，作者全文只按「2022 年版」引用。** 证据：WebFetch https://m.thepaper.cn/newsDetail_forward_32979539 （访问 2026-11-05，2026-04-15）：「2025年秋季起在全国分批启用《义务教育科学课程标准（2022年版2025年修订）》」「2025年修订版属于'日常修订'——不推翻原有框架」（该文只谈科学）；freemdict 转录件封面自称「义务教育 英语课程标准 日常修订版（2022年版2025年修订）」，其二级/三级词表说明仍为 505 / 1600 / 1095。英语课标是否有官方 2025 修订、词表是否变化，教育部一手来源未找到（搜索配额耗尽）——引用时应注明版本待确认。
4. **（高，事实）硬编码四阶段的代码点远多于 [22] 所列**（`grep -rn` 结果，均 @75df534）：
   - `backend/wd/seed.py:43` `STAGES: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")`，`:207-208` `"stage_cet6": int("cet6" in stages), "stage_min": (STAGES.index(stages[0]) + 1) if stages else None`；
   - `backend/wd/services/ecdict.py:28` `STAGE_TAGS = ("zk", "gk", "cet4", "cet6")`，`:176-177` 同样的 `stage_min` 公式；`backend/wd/services/words.py:39` `STAGES`，`:591,594` INSERT 列表写死四个 `stage_*` 列；
   - `backend/wd/ai/prewarm.py:32-33` `STAGE_COLUMNS` / `STAGES = ("zk","gk","cet4","cet6","all")` 与 `frontend/src/pages/AdminPage.tsx:36` `PREWARM_STAGES`；`backend/wd/ai/content.py:49` `STAGE_ZH = {"zk": "初中", …}`（提示词用的第二份中文名映射）；`backend/wd/services/bank.py:85` `DEFAULT_STAGES = ("cet4", "cet6")`；
   - `backend/wd/services/screen.py:35` 与 `backend/wd/services/batches.py:60` `_STAGE_DISTANCE = "CASE WHEN w.stage_min = :cur THEN 0 WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END"`——依赖阶段序号的数值相邻关系，在 zk 之前插入「小学」会改变所有已存 `stage_min`（live 库 2,099 行 `stage_min=1`）与 `user_settings.current_stage` 的语义，需要数据迁移；
   - `frontend/src/pages/VocabPage.tsx:29` `TABS = ['all', 'zk', 'gk', 'cet4', 'cet6']`；`frontend/src/i18n/zh.ts:28-29` `stages: { zk: '初中', gk: '高中', cet4: '四级', cet6: '六级', zkFull…, newOnlyCet6, star }`；`ScreenPage.tsx:20`、`WelcomePage.tsx:42` 的 `Record<Stage, string>`；
   - `scripts/smoke.py:352` `expect([x["stage"] for x in stages] == ["zk", "gk", "cet4", "cet6"], …)`。
5. **（高，事实）`difficulty` 量表与阶段序号绑定，没有给「小学」留位置。** `backend/wd/migrations/0001_init.sql:195` `difficulty INTEGER CHECK (difficulty BETWEEN 1 AND 5), -- 1 初中 … 4 六级, 5 beyond`；`backend/wd/schemas.py:47` `Difficulty = Literal[1, 2, 3, 4, 5]`；`backend/wd/routers/vocab.py:78` 排序表达式 `"difficulty": "COALESCE(w.difficulty, w.stage_min, 5), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"`——`stage_min` 直接充当难度回退值。
6. **（高，事实）沪教委基〔2015〕35 号自带「有效期5年」条款**（`wusi_xuezhi.txt` 第 16 行），作者引为现行依据而未注明；后续文件未找到（见 [1]）。
7. **（高，事实）2022 课标二级词表采用英式拼写、美式拼写括注**（OCR 第 3275 行「2. 本词汇表采用英式英语拼写形式，常见的美式拼写形式用括号标注」；转录件说明第 2 条同），且「不列可根据构词法推导出的部分名词、形容词、副词」（说明第 10 条）。推断：导入时要按 `favourite/colour` 匹配（live 库两者均在），mahavivo 的 `color/favorite` 是美式变体而非新词。
8. **（中，推断待法律评估）作者的许可风险清单（未解决问题 7）漏了最可能低风险的来源。** WebFetch https://www.gov.cn/guoqing/2021-10/29/content_5647633.htm （访问 2026-11-05）《中华人民共和国著作权法》第五条：「本法不适用于：（一）法律、法规，国家机关的决议、决定、命令和其他具有立法、行政、司法性质的文件，及其官方正式译文；…」课标以教育部通知（教材〔2022〕2 号）附件印发，但同时由出版社出版成书，词表是否属第五条范围需法律意见——相对教材词表（出版社/牛津著作权）与无许可的 GitHub/有道镜像，这是作者未评估的选项。
9. **（高，事实）作者 [7] 引用的 2024 秋目录只是「上海市编写」部分**，完整目录含教育部目录（`autumn2024.txt` 第 18 行）；「没有人教 PEP」是口径产物，见 [7]。

---

## 联网类额外核查（一手性 / 年份 / 口径）

- **一手性**：edu.sh.gov.cn 文件、moe.gov.cn PDF、GitHub 原仓库、App Store 页面为一手；maimemo、sspai、renrendoc、mianfeiwendang、163、sohu、百度知道为二手，作者均已标注。freemdict 转录件为二手文本，本文按二手使用并与一手 OCR 抽样比对。
- **年份是否最新**：2015 五四学制通知已过其自定有效期（遗漏 6）；2021 学年度课程计划可能有更新（[3]）；2022 课标可能有 2025 日常修订（遗漏 3）；2004 征求意见稿说明 2005 年发布（[2]）。
- **数字口径**：墨墨「词汇量」= 词书条目数；牌组 1,040 条含 200 个短语/句型、41 个变形对；505 词表「不列词组和短语」；PEP 819 条含 110 短语；mahavivo 441 含 2 短语。作者在 [10][12][13][20] 已分别说明，未混用；本文 [21] 新增「OCR 247 含 7 个注释碎片」的口径修正。

## 未解决的问题

1. 沪教委基〔2021〕32 号是否仍是现行课程计划；2015 五四学制通知的后续文件（搜索配额耗尽）。
2. 《义务教育英语课程标准》是否有官方「2022年版2025年修订」、词表是否变化（仅见科学课标的媒体报道与论坛转录件）。
3. 牛津上海版每册 Module/Unit 结构的出版社原文（21cnjy 超时）。
4. freemdict 转录件 505 词与官方扫描件的逐页核对（本次只抽样 234 个 OCR 词）。
5. 原文未解决问题 1–5、7 本次未能推进。

**汇总：核验 22 条：确认 19、修正 2、推翻 0、无法核验 1。**
