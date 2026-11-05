# shanghai-primary — 上海小学英语的词汇要求与教材词表（官方要求 / 教材结构 / 词量 / 可机读来源）

基线：仓库 `/Users/sqin/word-dance` main @ 75df534；线上库只读副本 `scratchpad/live-copy.db`（words 9,162 行）；调研日期 2026-11-05。本文只做事实核验，不改代码。

## 范围与方法

- **读了的仓库文件**：`scripts/build_seed.py`（阶段集合如何由 ECDICT tag ∪ mahavivo 词表构成）、`data/seed/ATTRIBUTION.md`、`backend/wd/migrations/0001_init.sql`（`words.stage_*`、`stage_min`、`user_settings.stages_json/current_stage`）、`backend/wd/schemas.py`（`Stage`/`STAGE_ORDER`/`STAGE_NAMES_ZH`）、`frontend/src/api/types.ts`、`frontend/src/components/word/StageChips.tsx`、`frontend/src/pages/WelcomePage.tsx`；以及 2026-11-04 的 `docs/analysis/2026-11-04-library-curation/facts/seed-pipeline.txt`（仅作背景，代码结论已按 75df534 重新核对行号）。
- **线上库查询**：`sqlite3 -readonly live-copy.db`（words 计数、stage 分布）；所有重合统计用 `python3 -I` + `sqlite3` 以 `?immutable=1` 只读打开。
- **搜索词（中英）**：上海市中小学英语课程标准 试行稿 2004 词汇量 / 上海市小学英语学科教学基本要求 词汇表 / 牛津上海版 1A–5B 单词数 / 新世纪英语 小学 沪外教 / 上海 教学用书目录 英语 / 义务教育英语课程标准 2022 二级 500 附录 词汇表 / 人教 PEP 小学 词汇量 / 墨墨 百词斩 扇贝 不背单词 牛津上海版 / GitHub：牛津上海版、沪教版 单词、沪教牛津、Oxford Shanghai english words 等（api.github.com `search/repositories`，UA `word-dance-research`；无认证配额在中途耗尽，`gh` 未安装，code search 未能执行）。
- **下载并用 `python3 -I` 解析的文件**（均放在 `scratchpad/shanghai-primary/<目录>/` 各自空目录，未执行任何下载内容）：
  1. `1/OXFORD.apkg`（GitHub djfml/englishoxfordshanghaiedition，sha256 `e5eb6e65…866a1`，146,878 B；zip → `collection.anki21b` 为 zstd 压缩 SQLite，用 `zstd -d` 解出后以 immutable 模式读取 notes 表）
  2. `3/小学英语大纲词汇.txt`（mahavivo/english-wordlists，2,518 B）
  3. `4/shanghai-6-2-word.json`、`5/PEPXiaoXue{3_1…6_2}_T.json`（RealKai42/qwerty-learner `public/dicts/`）
  4. `edu_sh/`：上海市教委教学用书目录 PDF ×6（2024 秋、2025 春、2025 秋、2026 春、2026 秋、2021 秋补充）、沪教委基〔2021〕32 号课程计划 PDF、沪教委基〔2021〕25 号通知、《上海市中小学英语课程标准（征求意见稿）》说明 .doc、沪教委基〔2015〕35 号五四学制通知 .doc、沪教委基〔2024〕26 号 .docx（PDF 用 `pdftotext -layout`，.doc/.docx 用 macOS `textutil -convert txt`）
  5. `moe/english_std_2022.pdf`（教育部《义务教育英语课程标准（2022 年版）》，31.5 MB，201 页，**纯扫描图像、无文字层**：`pdffonts` 为空、`pdfimages -list` 每页一张整页图）、`moe/kcfa_2022.pdf`（《义务教育课程方案（2022 年版）》）。因无文字层，用 `pdftoppm -r 150` 渲染后以 macOS Vision 框架（自写 `ocr_tool/ocr.swift`，`VNRecognizeTextRequest` zh-Hans+en-US）做 OCR；正文句子逐字核对无误，但附录词表的 OCR 只识别出约一半词条（见 [shanghai-primary-21]）。
- **网页**：WebFetch 读取 edu.sh.gov.cn、moe.gov.cn、screle.shisu.edu.cn、apps.apple.com、maimemo.com、sspai.com、zhidao.baidu.com、renrendoc.com、mianfeiwendang.com、book.douban.com、sohu.com、thepaper.cn、blog.sina.com.cn、i-bei.com 等。**zhuanlan.zhihu.com 全部 403**（含 4 篇最相关的词表文章），doc.quark.cn 预览页无正文，okmart.com/yywords.com 连接失败——这些来源只能记录标题，不能引用内容。
- 置信度：高 = 一手文件/本地解析复核；中 = 权威转载或可互证的二手来源；低 = 单一二手来源或存在矛盾。

---

## 编号结论

### A. 学制与课程设置

**[shanghai-primary-1] 事实（高）上海义务教育为五四学制：小学一至五年级，初中六至九年级，依据沪教委基〔2015〕35 号。**
- 证据：`scratchpad/shanghai-primary/edu_sh/docs/wusi_xuezhi.txt`（来源 https://edu.sh.gov.cn/cmsres/8a/8a94ab3e6ec14fccb5f88203abd27c1c/85b1a4dca2064a2a24d0cb1f02ae4c04.doc ，访问 2026-11-05）：「本市义务教育阶段实行五四学制，即实行小学五年、初中四年的学制。小学五个年级分别为一年级、二年级、三年级、四年级、五年级；初中……四个年级分别为六年级、七年级、八年级、九年级。」文件落款「上海市教育委员会 2015年4月23日」，并废止沪教委基〔2004〕50 号。
- 推断：产品若面向上海「小学」，年级范围是 1–5，而不是全国通行的 1–6；国家课标「二级（5–6 年级）」在上海跨越了小学五年级与初中六年级（见 [shanghai-primary-19]）。

> **核验修正（INDEX §3 #18，2026-11-05）**：事实成立，推断修正——「二级跨越小五与初六」是按年级数字对号；2022 课标对五四学制有明文映射（PDF 第 18 页：「五四」学制 3～5 年级目标主要参照「六三」学制 5～6 年级目标确定，适当降低要求；第 20 页：「五四」3～5 年级课程内容应覆盖「六三」3～6 年级大部分课程内容），即二级（505 词）对应上海小学毕业（五年级末，要求略降），六年级起进入三级进阶；另沪教委基〔2015〕35 号自载「有效期 5 年」（2020-04 到期），现行依据应为后续文件（未找到），五四学制事实不受影响（沪教委基〔2021〕32 号课程计划仍按 1–5 / 6–9 年级编排），依据 verify/shanghai-primary.md [shanghai-primary-1]。

**[shanghai-primary-2] 事实（高）上海小学从一年级开设英语（1999 年起试点、2004 年时已全部开设）；国家 2022 课程方案的英语起始年级是三年级，一二年级开设属「有条件的地区和学校」。**
- 证据 1：`edu_sh/docs/kcbz_shuoming.txt`（《上海市中小学英语课程标准（征求意见稿）》说明（社会版），https://edu.sh.gov.cn/cmsres/a7/a74f0300fda4480193d663086cf0f408/286a4201624f8b80a88be0d4fc1ed208.doc ，访问 2026-11-05；.doc 元数据 Create 2004-10-25，edu.sh.gov.cn 对应页面 https://edu.sh.gov.cn/zcjd_area_257/20200706/0015-xw_18836.html 显示「发布日期：2005-01-11」）：「本市从1999年起在部分小学一年级进行外语教学的试验（以听说活动为主），至今所有小学的一年级都开设了外语课。」同文：「小学（一至五年级）：启蒙和起始阶段；初中（六至九年级）：基础和发展阶段；高中（十至十二年级）：提高和过关阶段。」
- 证据 2：`moe/ocr_kcfa_1_30.txt`（《义务教育课程方案（2022 年版）》 http://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220420582343217634.pdf PDF 第 14 页 OCR，访问 2026-11-05）：「小学阶段开设英语，起始年级为三年级；有条件的地区和学校可在一至二年级开设，以听说为主。」
- 证据 3（教材侧旁证）：2024–2026 年上海教学用书目录均列出一年级英语课本（见 [shanghai-primary-6]）。

**[shanghai-primary-3] 事实（高）上海小学三至五年级期末考试只限语文、数学；英语在小学阶段只「考查」（沪教委基〔2021〕32 号）。**
- 证据：`edu_sh/pdfs/p7.txt` 第 124–126 行（https://edu.sh.gov.cn/cmsres/43/43cafa83106a4e38b9189613a1b5b33b/66878047d1b1f23add5edcb0d58e39e2.pdf ，访问 2026-11-05）：「小学一、二年级可进行期末考查（一年级不得进行书面考查）；三、四、五年级期末考试仅限语文、数学两门学科，其他学科只进行考查，考查形式可灵活多样,严格执行等第制。」第 127 行：「初中除语文、数学、外语学科可举行期中、期末考试以外……」
- 推断：上海小学阶段没有「中考式」的统一英语词表考试压力；「小学词库」的产品定位更接近教材同步（按册/单元）而非备考清单。

### B. 官方词汇要求

**[shanghai-primary-4] 事实（高）上海 2004 课程标准对词汇量的规定：T（总词汇量）= K（核心词汇量）+ X（扩展词汇量）；小学毕业 K ≥ 500、T ≥ 600；初中毕业累计 K ≥ 1600、T ≥ 2100；高中毕业累计 K ≥ 2300、T ≥ 4200。X 没有固定词表。**
- 证据：`edu_sh/docs/kcbz_shuoming.txt` 第 55–60 行（来源同 [2]）：「12．新《课程标准》对学生的词汇量有什么新的规定?」……「T（总词汇量） =  K（核心词汇量）+  X（扩展词汇量）」「《标准》规定小学毕业生核心词汇量不少于500词，总词汇量不少于600词；初中毕业生核心词汇量累计不少于1600词，总词汇量累计不少于2100词；高中毕生毕业核心词汇量累计不少于2300词，总词汇量累计不少于4200词 。」关于 X：「只有下限，没有上限，要求学生理解，没有固定的词汇表，具体的词汇可由各教材的编写者和学校教师选定。」
- 二手互证：搜狐 2020-06-23 https://www.sohu.com/a/403938881_503508 （访问 2026-11-05）引用《上海中小学英语课程标准》：「小学毕业时，要求掌握的核心词汇量不少于500词，总词汇量不少于600词。」
- 注意：这份是 2004 年「征求意见稿」的官方说明；正式「试行稿」全文及其核心词汇表（K 表）本次**未找到公开 PDF**（豆瓣有《上海市中小学英语课程标准(征求意见稿)》上海教育出版社 ISBN 9787532098613 的条目 https://book.douban.com/subject/3548814/ ，无出版年与页数）。核心词汇表是否随标准附录公开、2004 之后是否修订，无法核实（见未解决问题）。

**[shanghai-primary-5] 事实（中）「上海市小学英语学科教学基本要求」作为独立公开出版物本次未找到；能核实的是初中版：《上海市初中英语学科教学基本要求》上海市教育委员会教学研究室编，上海教育出版社 2016，ISBN 9787544472685，179 页。**
- 证据：豆瓣 https://book.douban.com/subject/35139941/ （访问 2026-11-05）：标题「上海市初中英语学科教学基本要求」，作者「上海市教育委员会教学研究室」，出版社「上海教育出版社」，出版年「2016」，ISBN「9787544472685」，页数「179」。
- 搜索「"上海市小学英语学科教学基本要求"」仅命中百度教育聚合页 https://easylearn.baidu.com/shijuan/juhe_1211270.html （页面本身无文件描述，只列出「初中英语学科教学基本要求单词（15 页）」等相关文档）；上外英语基地成果页、2018 大事记、ECNU 教师教育学院 2019 PDF 均无该书记载。结论：**小学版教学基本要求是否含词表、哪年、多少词——找不到，不猜**。
- 相关旁证（初中、供 zk 任务参考）：mahavivo/english-wordlists 含 `上海市初中英语词汇表（2020年版）.pdf`（1,200,683 B，`api/mahavivo_contents.json`）；轻松背单词有「2015上海市初中英语教学基本词汇表」词书页 http://book.qsbdc.com/book_info.php?book_id=1710 （证书错误，未读取）。

**[shanghai-primary-6] 事实（高）教育部《义务教育英语课程标准（2022 年版）》：二级「能初步运用 500 个左右单词（见附录 3）」；附录 3 二级词汇表收录 505 个单词；三级词汇表共 1600 个，其中含二级 505 个（用 * 标出），初中新增 1095 个；一级建议 3–4 年级、二级 5–6 年级、三级 7–9 年级。**
- 来源：教育部 教材〔2022〕2 号通知页 http://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html （访问 2026-11-05；`moe/notice.html` 解析出附件链接 `./W020220420582349487953.pdf` = 义务教育英语课程标准（2022年版））。PDF sha256 `59ec3971…222fb`。
- OCR 原文（`moe/ocr_001_100.txt` / `ocr_101_201.txt`，PDF 页码 = pdftoppm 序号；括号内为印刷页码）：
  - PDF 第 27 页（印刷第 20 页）：「3. 能初步运用500个左右单词（见附录3），就规定的主题进行交流与表达，另外可以根据实际情况接触并学习三级词汇和相关主题范围内100~300个单词，以及一定数量的习惯用语或固定搭配。」同页三级：「5. 围绕相关主题学习并使用约1600个单词进行交流与表达（见附录3）……」第 28 页「三级＋」：「围绕相关主题接触并使用约1800个单词进行交流与表达……约200个单词」。
  - PDF 第 94 页（印刷第 87 页）「附录3 词汇表 二级词汇表 说明」：「本词汇表收录505个单词，为小学阶段英语课程应学习和掌握的基本词汇。各地可根据实际情况在本词汇表的基础上，选择增加100~300个单词（主要为三级词汇及少量相关主题范围内词汇）。」并注明「本词汇表不标注单词的词性和中文释义」「本词汇表不列词组和短语」。
  - PDF 第 105 页（印刷第 98 页）「三级词汇表 说明」：「本词汇表共收录1600 个单词，含二级词汇 505个（用“*”标出），确定1095个单词为初中阶段英语课程应学习和掌握的基本词汇。」
  - PDF 第 13 页：「一级建议3~4年级学段应达到的目标，二级建议为5~6年级学段应达到的目标，三级建议为7~9年级学段应达到的目标。」
- 二手互证：网易 https://m.163.com/dy/article/HB20L7VV0536EPBU.html 、新东方在线等多处转述同句（访问 2026-11-05）。

### C. 上海在用的小学英语教材（以市教委教学用书目录为准）

**[shanghai-primary-7] 事实（高）2024 秋以前，上海小学 1–5 年级英语教材是两套「由学校选一种使用」：《英语（牛津上海版）（试用本）》（版别「沪教育」= 上海教育出版社）和《英语（新世纪版）（试用本）》（版别「沪外教」+「沪外音」= 上海外语教育出版社 + 上海外语音像出版社）。目录中没有人教 PEP 等全国版小学英语。**
- 证据：`edu_sh/pdfs/p1.txt`（《2024年秋季上海市编写教学用书目录》附件 2 小学阶段，https://edu.sh.gov.cn/cmsres/97/9705ef64871d45cf984f73d79cae5fd9/d5352cc408d180944636941826a5cdd3.pdf ，访问 2026-11-05）：二至五年级第一学期列「英语（牛津上海版）（试用本）」准用号 Ⅱ－XB－2021022（二/一）、2017013（三/一）、2017014（四/一）、2021023（五/一）与「英语（新世纪版）（试用本）」Ⅱ－XB－2020010（二/一）、2022006（三/一）、2020012（四/一）、2020013（五/一），备注「由学校选一种使用，含配套资源」。2025 春（`p6.txt`）、2025 秋（`p3.txt`）、2026 春（`edu_sh/catalog_2026spring.txt` 第 54–76 行）对尚未换用新教材的年级（见 [shanghai-primary-8]）保持同一「两套择一」结构。
- 旁证：新浪博客 2019-08-27 https://blog.sina.com.cn/s/blog_df4a630f0102yl36.html （访问 2026-11-05）逐年级列出「英语（牛津上海版）（试用本）（一/一）（含音频材料） 沪教育 一年级第一学期」与「英语（新世纪版）（试用本）一/一）（含音频材料）沪外教 沪外音」，并称「上海市有16个区。每个地区使用的教材版本略有不同」。爱贝亲子 2016-06-28 http://www.i-bei.com/shanghai/sxzx/xx/2016/0628/28510.html ：「目前沪上各小学主要使用的英语教材不外乎'新世纪'、'牛津上海版'、'朗文'等几种」（朗文/SBS 为校本补充，不在市教委目录）。
- 哪些区用哪套：**没有找到官方按区的选用名单**；目录措辞是「由学校选一种使用」。

**[shanghai-primary-8] 事实（高）2024 年 9 月起上海启用新编《义务教育教科书（五·四学制）·英语》（上海教育出版社，一年级上册～五年级下册），逐年级替换：2024 秋一年级、2025 秋二年级、2026 秋三年级；2026 年秋季目录里牛津上海版/新世纪版已完全消失（小学与初中均无）。**
- 证据 1：上外英语基地页 https://screle.shisu.edu.cn/ea/df/c16360a191199/page.htm （页面日期 2024-12-30，访问 2026-11-05）：书名「《义务教育教科书（五•四学制）•英语》（一年级上册～五年级下册）」，「由上海教育出版社出版」，「一年级上册已于2024年9月投入使用」。
- 证据 2（目录逐年）：
  - 2024 秋 `p1.txt`：「SD－XS－2024001 英语（一年级上册） 沪教育 一年级第一学期 含配套资源」；二至五年级仍为牛津/新世纪。
  - 2025 春 `p6.txt`：「待审 英语（一年级下册） 沪教育」；2026 春 `catalog_2026spring.txt` 第 54 行：「SD－XS－2024002 英语（一年级下册） 沪教育 一年级第二学期 含配套资源」、第 56 行「待审 英语（二年级下册）」。
  - 2025 秋 `p3.txt`：「SD－XS－2024001 英语（一年级上册）」「SD－XS－2025001 英语（二年级上册）」；三至五年级仍牛津/新世纪；初中六至八年级列新教材配套「义务教育教科书（五·四学制）·英语练习部分」（如 SD－CX－2025005 八年级上册），九年级仍「英语（牛津上海版）（试用本）Ⅱ－CB－2016004」/新世纪。
  - 2026 秋 `p2.txt`（https://edu.sh.gov.cn/cmsres/7a/7aed3909441a4c849d5d78b8d914f4fb/00e155989221056fb74efd6f967939f0.pdf ）：小学列「SD－XS－2024001 英语（一年级上册）」「SD－XS－2025001 英语（二年级上册）」「SD－XX－2025005 义务教育教科书（五·四学制）·英语 练习部分（三年级上册）」及「待审」的四、五年级练习部分；全文 `grep 牛津上海版|新世纪版` 为 0 命中。
- 推断（中）：2026 秋目录标题注明「（不包含教育部印发的中小学教学用书目录）」，三至九年级的新教材学生用书本身大概率已进入教育部国家目录（故只列上海编写的「练习部分」）；而 2026 年秋季起 1–5 年级全部使用新教材、牛津上海版退出一线课堂，是从目录推出的结论，**未见市教委明文公告**。对产品的含义：若 2026-11 之后上线「上海小学」词库，**以牛津上海版 1A–5B 为底本已属上一代教材**；在读学生（2026 学年）一至五年级已全部换新教材，但家中/机构沿用旧版复习材料仍常见。

**[shanghai-primary-9] 事实（中）两套旧教材的结构：牛津上海版小学为五四制 1A–5B 共 10 册（每学期一册），每册 4 个 Module、每 Module 3 个 Unit（共 12 Unit）；新世纪版同为 1–5 年级每学期一册。**
- 证据：App Store「三步法记单词-牛津上海版小学英语(五四制)」 https://apps.apple.com/cn/app/id1616878486 （访问 2026-11-05）描述：「上海教育出版社 牛津上海版（五四制）（试用本）：一年级(第一、二学期), 二年级(第一、二学期),三年级(第一、二学期),四年级(第一、二学期),五年级(第一、二学期)」；21 世纪教育网多份教案以「Module x Unit y」编号（如 https://mip.21cnjy.com/P/4673770.html 「Unit 6 Going to school」），搜索摘要称每册「四个模块、十二个单元」（二手，未见出版社原文，故置信度中）。
- 旁证：市教委目录中牛津上海版配套「教学挂图（三/二）」「教学参考资料」逐学期编号（`catalog_2026spring.txt` 第 255–276 行）。

### D. 牛津上海版 1A–5B 词量（多来源互证）

**[shanghai-primary-10] 事实（中）墨墨背单词公开词书页给出牛津上海版各册词汇量：1A 50、1B 47、2A 41、2B 55、3A 82、3B 68、4A 121、4B 98、5A 95、5B 115；十册合计 772（按册相加，未去重）。初中 6A–9B 为 182/231/208/214/240/242/218/168（合计 1,703）。**
- 证据：https://www.maimemo.com/rankbooks?bookid=1&uid=152 （访问 2026-11-05，页面无日期），条目原文如「牛津上海版一年级上册 - 词汇量：50」「牛津上海版五年级下册 - 词汇量：115」「牛津上海版六年级上册 - 词汇量：182」。计算：50+47+41+55+82+68+121+98+95+115 = 772。
- 同页还列「沪教版一年级上册 59 / 一年级下册 64 / 二年级上册 42 / 二年级下册 43 / 沪教版五四学制三年级上册 159 / 四年级上册 141 / 五年级上册 113」，以及「沪教版五四学制六年级上册（新版）299 / 六年级下册（新版）282 / 七年级上册（新版）270 / 七年级下册（新版）292 / 八年级下册（新版）215 / 九年级上册（新版）203」。推断（低–中）：这组「沪教版（五四学制）/（新版）」对应 2024 年新编教材（21cnjy 把六至八年级新教材标为「沪教版(2024)」），但墨墨页面未写年份，不能确认。
- 互证：GitHub anki 牌组（下节）共 1,040 个唯一条目，其中单词 825、短语/句子/变形对约 215；去掉非单词后 ≈ 825，与 772 同量级（牌组多收录了变形对与句型）。百度知道 2022-11-12 https://zhidao.baidu.com/question/1934061573384122307.html 的「上海版牛津小学英语词汇量800-1000个……分为8册学习……句型130句」与爱贝 2016 文中「牛津 Fun with English 800-1000词左右词汇，130个短语，8 个学习单元」措辞雷同，疑把另一套牛津教材的数字张冠李戴，**低置信度，不采用**；爱贝文中「1A-3B的词汇在2000词左右，4A-5B在2000词左右」与所有其他来源矛盾，亦不采用。

**[shanghai-primary-11] 事实（中）公开可见的牛津上海版小学词表文档均为 Word/PDF 扫描整理件、无出版社来源：人人文库《上海版小学英语牛津词汇表(带音标)》17 页 DOC，2020-10-23 上传，按册列 1A–5A（页面摘录未见 5B）；免费文档网《牛津小学英语上海版单词表[1A-2B][3A-3B]》24 页，1A 以「morning, afternoon, book, ruler, pencil, rubber, pen, bag…」开头（旧版用 rubber，GitHub 牌组用 eraser，提示版本差异）。**
- 证据：https://www.renrendoc.com/paper/99541152.html 、 https://www.mianfeiwendang.com/doc/22e5a39543fcb62eee13f992 （访问 2026-11-05）。两份都**未写明词数**。知乎《牛津上海版小学英语词汇表（2024版手动整理）含氢刻》 https://zhuanlan.zhihu.com/p/682892484 、《沪教版小学各年级英语单词列表》 https://zhuanlan.zhihu.com/p/589199309 为最可能带计数的来源，但 403 无法读取。

### E. 可机读来源逐项记录

**[shanghai-primary-12] 事实（高）唯一找到的、覆盖「全部」牛津上海版小学单词并可直接解析的开源文件是 GitHub `djfml/englishoxfordshanghaiedition` 的 Anki 牌组 `OXFORD.apkg`：1,042 条笔记 / 1,040 个唯一条目，含中文释义，927 条带 [音标]，716 条末尾带词性缩写；无许可证声明、无按册/单元标签、未写明依据的教材版本年份。**
- 证据：`api/djfml_repo.json`（created 2025-03-08，pushed 2025-03-08，license null，描述「上海版牛津小学英语全部单词带音标 anki deck」）；README 全文：「上海版牛津小学英语全部单词带音标 anki deck文件 自行导入使用」。解析脚本 `scratchpad/shanghai-primary/analyze_anki.py`（读取 notes.flds，`\x1f` 分隔两字段「正面 | 背面」）。
- 统计（`python3 -I analyze_anki.py …` 输出）：notes 1,042；NFKC+小写+压空格后唯一 1,040（重复 2：`french fries`、`like`）；含空格 200（如 `a pair of`, `answer the phone`, `go swimming→went swimmin`）；含连字符 14（`pencil-case`, `exercise-book`, `twenty-one`…）；含「→」变形对 41（`go→goes`, `tall → taller`…）；首字母大写 64（含月份、星期、`China/Chinese/English/American`，也有误大写 `Pen`, `Paper`, `Match`）；句型类条目约 36（`Here you are.`, `What time is it?`）。背面格式示例：`钢笔[pen] n`、`铅笔['pensəl] n`、`远[fɑ:] a n`。标签只有 `Obsidian_to_Anki`，无册别信息；仅 1 个 deck「OXFORD」。
- 20 个随机样例（seed 20261105）：coffee‖咖啡['kɔfi] n；we‖我们[wi:] pron；join‖参加[dʒɔin] n；American‖美国的,美国人[ə'merikən]；front‖前面；前部；正面[frʌnt] n；wait‖等待[weit] v；newspaper‖报纸['nju:s,peipə] n；by‖在…旁；靠近 prep；all right‖好吧；好的；what‖什么；（感叹）多少[hwɔt] pron int；empty‖空的['empti] a；do an experiment‖做实验[du:] [æn] [iks'perimənt]；next week‖下周[wi:k]；collect stamps→collecting stamps‖集邮…；play → played‖玩[plei]；January‖一月['dʒænjueri] n；triangle‖三角铁['traiæŋgl] n；picnic‖野餐['piknik] n；wing‖翅膀[wiŋ] n；dinosaur‖恐龙['dainəsɔ:] n。
- 质量判断（推断）：音标用旧式 DJ 符号且有错（`bag`→`[[bæɡ]`、`skate`→`[skeit ]`），词性标注混乱（join 标 n），有拼写残缺（`go swimmin`, `Catc(bus)`, `tcow`），含麦当劳品牌词（`BigMac`, `McChicken`）。**可做候选词源，不可直接作为释义/音标源**。

**[shanghai-primary-13] 事实（高）该牌组与线上库的重合：1,040 个唯一条目中 771 个与 `words.lemma` 完全相等（269 个不在库中；再做空格↔连字符变体匹配后仍有 263 个不在库，其中约 207 个为短语/句子/变形对）；只看 825 个单词条目（未做变体匹配），769 个在库（93.2%），56 个不在库——其中 15 个是库内词的屈折形式（`children, teeth, mice, geese, got, has, excited, parents, sports, glasses, hiking, dining, hissing, humming, thanks`，存在于 `word_forms`），其余 41 个多为低频具体名词与连字符词（`aquarium, aviary, caterpillar, cocoon, tadpole, duckling, lizard, moth, durian, plum, screwdriver, trolley-bus, pencil-case, picture-book, swimming-pool, exercise-book, eye-exercises, forty-two, thirty-three, twenty-five, fifteenth, thirtieth, can't, cannot, doesn't, mr, pingpong, bigmac, mcchicken…`）。**
- 方法：`SELECT lemma FROM words`（9,162 行）读入集合；条目 NFKC→小写→压空格后求交集；屈折检查用 `SELECT form FROM word_forms`。
- 在库 769 词的 `stage_min` 分布：1(初中)=671、2(高中)=68、3(四级)=19、4(六级)=11。即牛津上海版小学词汇 87% 已带 `stage_zk=1`；「小学」不是库外新词，而是现有初中词的子集加约 60 个库外词。
- 在库 769 词中 `frq > 5000`（COCA-ish 低频）者 130 个（`blackboard, blouse, cabbage, chopsticks, crayon, crocodile, cupboard, dentist, dinosaur, dolphin, aeroplane, accountant…`）：小学教材偏具体名词，与频率排序不一致，**不能用 `frq` 阈值近似「小学词」**。

**[shanghai-primary-14] 事实（高）qwerty-learner（RealKai42）词书目录里没有牛津上海版/新世纪版小学词书；有「上海初中牛津词汇」1,270 词、「上海新教材六年级下」274 词、人教 PEP 三至六年级 8 册、人教新起点一至六年级 12 册、剑桥 JOIN IN 1,350 词。**
- 证据：`api/qwerty_dictionary.ts`（https://raw.githubusercontent.com/RealKai42/qwerty-learner/master/src/resources/dictionary.ts ，访问 2026-11-05，共解析出 361 个词书条目）：`id: 'SHjuniormiddleOxford', name: '上海初中牛津词汇', url: '/dicts/OxfordVocabulary_juniorMiddleSH.json', length: 1270`；`id: 'shanghai-6-2word', name: '上海新教材六年级下', url: '/dicts/shanghai-6-2-word.json', length: 274`；`public/dicts/` 目录列表 380 个文件（`api/qwerty_dicts_dir.json`）中无 `SH*XiaoXue`/`Oxford*Shanghai*Primary` 类文件。下载的 `4/shanghai-6-2-word.json` 为 274 个 `{name, trans[]}`（无音标），首条 `different`。
- 许可：qwerty-learner 仓库 LICENSE 为 GNU GPL v3（`api/qwerty_LICENSE.txt`，https://raw.githubusercontent.com/RealKai42/qwerty-learner/master/LICENSE ，访问 2026-11-05 首行「GNU GENERAL PUBLIC LICENSE Version 3」）；该许可约束代码，词书 JSON 本身的数据来源与许可未在条目中注明。

**[shanghai-primary-15] 事实（高）kajweb/dict（有道词书镜像）README 的 70+ 本词书中无任何「上海/牛津/沪教」条目；含人教版小学英语三至六年级 8 册（64/72/84/104/131/156/130/108 词）。**
- 证据：`api/kajweb_README.md`（https://raw.githubusercontent.com/kajweb/dict/master/README.md ，访问 2026-11-05）`grep -n "牛津\|上海\|沪教\|Oxford\|Shanghai"` 0 命中；第 257–264 行为「人教版小学英语-三年级上册 … 64」等（含有道原始 zip 链接）。README 自述为抓取有道词典词书，侵权联系下架——**版权状态不明**。

**[shanghai-primary-16] 事实（高）mahavivo/english-wordlists 含 `小学英语大纲词汇.txt`：441 个词（按非空行计，大小写去重后仍 441），2 个含空格（`physical education` 等），10 个首字母大写（`China, Chinese, English, I, Miss, Mr, Mrs, Ms, PE, TV`），无释义无音标，README 未说明来源与依据的大纲版本；431 个在线上库中（缺 `children, feet, has, men, mr, mrs, ms, pe, physical education, women`，均为屈折形式/称谓/缩写）；与牛津上海版牌组重合 317 个。**
- 证据：`3/小学英语大纲词汇.txt`（https://raw.githubusercontent.com/mahavivo/english-wordlists/master/小学英语大纲词汇.txt ，2,518 B）；`api/mahavivo_README.md` 的 10 条说明均未提及该文件。该仓库同样**无 LICENSE**（与 `data/seed/ATTRIBUTION.md:10-13` 一致）。
- 推断：441 词与 2001/2011 国家课标二级词表（约 423–500 词）同量级，但不等于 2022 版 505 词；来源不明，不宜直接当「官方小学词表」。

**[shanghai-primary-17] 事实（高）ECDICT 没有「小学」标签：`tag` 字段只有 zk/gk/cet4/cet6/ky/toefl/ielts/gre 类考试标签，现有 seed 构建完全依赖它和四份 mahavivo 考纲词表。**
- 证据：`api/ecdict_README.md` 第 40 行：「| tag | 字符串标签：zk/中考，gk/高考，cet4/四级 等等标签，空格分割 |」；`scripts/build_seed.py:104-106`（`' '||tag||' ' like '% zk %' or … '% cet6 %'`）与 `scripts/build_seed.py:112-126`（`stage_from_list = {"zk": "zk", "gk": "gk", "cet4": "cet4", "cet6": "cet6"}` 逐表并入 `rec["stages"]`）；`data/seed/ATTRIBUTION.md:10-13`。
- 推断：增加「小学」阶段意味着引入一个 ECDICT 之外的新词源（教材词表或 2022 课标二级词表），而不是改 tag 过滤条件。

**[shanghai-primary-18] 事实（高）GitHub 上与「沪教/牛津上海」相关的其他仓库全是初中（6–9 年级）或非上海版本，小学侧只有 [12] 一个：`lolo811109-crypto/chuyi-words`（沪教版牛津英语 7A 2024 版 + 7B）、`andy71111/word-pk`（「沪教版初中英语单词PK……6册1556词，含音标」）、`junglehu/english-trainer`（沪教版 2024 七年级上册）、`Freddiehuhu/English-Learning-Strategy`（八年级上册）、`misymeng-netizen/english-word-trainer`（初一 沪教牛津版）、`angelachen825-bit/baicizhan`（「沪教牛津版小学英语背单词应用」，目录未能列出——API 配额耗尽）、`Andrewyan1234/yuexueci`（广州版小学 + 沪教牛津版初中）、`flyxl/LanguageAstronauts`（沪教牛津**深圳版**小学）。**
- 证据：`api/repos_oxford_sh.json`、`repos_hujiao.json`、搜索输出（api.github.com `search/repositories?q=…`，访问 2026-11-05）。
- 注意命名陷阱（推断，高）：「沪教牛津版」在广东/深圳是**三年级起点**六年制版本（App「小学英语单词卡-沪教牛津版」 https://apps.apple.com/lc/app/id1256280511 的内购按「三年级～六年级 上/下册」划分；墨墨列「沪教版三年级起点三年级下 113」等），「牛津小学英语」常指**译林版（江苏）**（沪江页 https://m.hujiang.com/en_xiaoxue/p129740 实为译林六年级），都不是上海的五四制牛津上海版。抓词表时必须按「一年级起点/五四制/1A–5B」过滤。

**[shanghai-primary-19] 事实（中）商业背词 App 的小学词书覆盖：墨墨背单词有牛津上海版 1A–5B 与「沪教版（五四学制）」新教材词书（见 [10]），并支持用户自制词书；不背单词、扇贝只支持上传自制词书；百词斩不能上传。公开页面均未写明词书的授权来源。**
- 证据：少数派 2024-03-27 https://sspai.com/post/87587 （访问 2026-11-05）：「墨墨背单词：自己自制的词书也可以在墨墨中进行添加」「百词斩：无法自己上传词书」「扇贝单词：只能将自制词书上传使用」；词库范围「涵盖小学、初中、高中……」（墨墨/不背单词）。墨墨词书页见 [10]。百词斩/不背单词/扇贝是否自带牛津上海版小学词书：**页面未写，找不到**。

**[shanghai-primary-20] 事实（高）人教 PEP 小学英语（三年级起点）词量：qwerty-learner 8 册 JSON 合计 849 条、去重后 819 个唯一条目（含 110 个带空格短语），与线上库重合 631，188 个不在库中（多为短语与屈折：`a few, art room, ate, bought, bigger, cleaned, dancing, dining hall…`）。**
- 证据：`5/PEPXiaoXue*_T.json`（每条 `{name, trans[], usphone, ukphone}`，首条 `ruler`），计数脚本见上文方法；与 `api/kajweb_README.md:257-264` 的有道数据逐册一致（64/72/84/104/131/156/130/108）。二手：搜索摘要引「人教版・小学英语教材・词汇量」（yywords.com，页面 444 无法读取）称「总词汇涉及837个单词」——与 819–849 同量级，未核实。
- 对比：人教 PEP 的 ~820 条（含短语）vs 牛津上海版 772（按册相加）vs 2022 课标二级 505 词：教材词量都高于课标核心词表，差额即课标允许的「增加 100~300 个」+ 短语/变形。

**[shanghai-primary-21] 事实（中）2022 课标附录 3 二级词汇表（505 词）本次只能 OCR 到约一半：从 PDF 第 95–104 页识别出 247 个唯一词形，其中 240 个在线上库（`stage_min` 1=235、2=5），6 个为 OCR 乱码（`ajdde`=apple 等镜像误读）、1 个是屈折形式（`excited`）；247 词中 170 个出现在牛津上海版牌组、77 个不在（`autumn, beautiful, favourite, grandfather, hometown, hospital, internet, kite, lovely, minute, never…`）。**
- 证据：`moe/level2_ocr_words.txt`（247 行）；方法：Vision OCR 结果按页提取、去括号注、按空白/逗号切分、过滤无元音/大小写混杂的乱码。**识别率约 49%（247/505），是 OCR 对双栏扫描页的漏读，不是词表本身的问题**；完整 505 词需要有文字层的来源（知乎多篇整理稿 https://zhuanlan.zhihu.com/p/1957530318111219730 、 https://zhuanlan.zhihu.com/p/1987209118293972880 标题即「小学英语词汇表（摘自2022年版义务教育英语课程标准）」「含音标/词性/释义」，均 403）。
- 推断（中）：按已识别样本 97% 在库且几乎全为 `stage_zk=1`，完整 505 词在库比例应与之接近，即「小学」阶段的词几乎都已在库，缺的是**阶段标记**而非词条。

> **核验修正（INDEX §3 #9，2026-11-05）**：完整二级词表已可机读——freemdict 转录 docx 附录 3 解析得 505 个词条（与「本词汇表收录505个单词」吻合）；对照线上库 500/505 = 99.0% 精确等于 `words.lemma`（`o' clock` 为转录多一空格，对应库内 `o'clock`），在库词 `stage_min` 1 = 495、2 = 3（`an`、`astronaut`、`maths`）、3 = 1（`best`）、4 = 1（`chore`）；未命中 5 个 = `mr, mrs, ms, pe`（库中以 `mr.`/`mrs.`/`ms.`/`p.e.` 收录，属书写差异）+ `excited`（`word_forms` 有，原形 `excite` 在库），即真正不在库的只有 `excited`；「≈97% 在库、几乎全为 stage_zk=1」应改为 99.0% 在库、99.0% 为 stage_min=1；OCR 247 词中混入 13 个非词目（6 乱码 + 7 注释碎片），转录件为非官方文本、抽样 234 词一致，依据 verify/shanghai-primary.md [shanghai-primary-21]、verify/provinces.md [provinces-24]。

### F. 与当前代码的衔接（仅陈述事实）

**[shanghai-primary-22] 事实（高）当前 schema 与类型把阶段硬编码为 4 个：`words.stage_zk/stage_gk/stage_cet4/stage_cet6` 四个 0/1 列 + `stage_min CHECK (stage_min BETWEEN 1 AND 4)`；`user_settings.stages_json` 默认 `'["cet4","cet6"]'`、`current_stage CHECK (current_stage BETWEEN 1 AND 4)`；后端 `Stage = Literal["zk","gk","cet4","cet6"]`、`STAGE_ORDER`、`STAGE_NAMES_ZH = {"zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}`；前端 `Stage = 'zk'|'gk'|'cet4'|'cet6'`、`STAGE_INDEX {zk:1,gk:2,cet4:3,cet6:4}`、Welcome 角色 `zk/gk/uni/pro`。**
- 证据：`backend/wd/migrations/0001_init.sql:147-148`（`stages_json … DEFAULT '["cet4","cet6"]'`；`current_stage INTEGER NOT NULL DEFAULT 3 CHECK (current_stage BETWEEN 1 AND 4)`）、`:181-186`（四个 `stage_*` 列与 `stage_min`）、`:207`（`ix_words_stage_min`）；`backend/wd/schemas.py:25-26,51-52,56-67`（`stage_to_index`/`index_to_stage` 以 `STAGE_ORDER` 下标 +1）；`frontend/src/api/types.ts:5,45`；`frontend/src/components/word/StageChips.tsx:7-9`；`frontend/src/pages/WelcomePage.tsx:30-40`。
- 推断：「小学」若作为第 5 个阶段插在 zk 之前，`stage_min` 的「1=zk」语义、CHECK 上限 4、`STAGE_ORDER` 下标映射与前端 `StageIndex` 都要同步改；这属于其他任务（stages 代码切片）的范围，此处只指出耦合点。

---

## 未解决的问题

1. **上海 2004 课程标准正式「试行稿」全文及其核心词汇表（K 表，小学 ≥500 词）**：只找到 2004-10 的征求意见稿《说明》；K 表是否公开、小学段 K 表词目、2004 后是否修订均未核实。
2. **《上海市小学英语学科教学基本要求》**：是否存在独立出版物、哪年、是否含词表——找不到任何一手或权威二手记录（初中版 2016 可确认）。
3. **2024 新编《义务教育教科书（五·四学制）·英语》小学 1–5 年级的词表与词量**：出版社/市教委无公开词表；墨墨的「沪教版一年级上册 59 … 五四学制五年级上册 113」是否就是这套新教材，未确认；GitHub 上尚无该教材小学册次的开源词表（六至八年级有）。
4. **牛津上海版 1A–5B 的权威逐册词数与去重总词量**：只有墨墨的 772（按册相加）和 GitHub 牌组的 ~825 单词两个非官方数字；出版社页面与知乎整理稿不可达，去重总量无法给出。
5. **各区/各校牛津版 vs 新世纪版的选用比例**：目录只写「由学校选一种使用」，无官方分布数据。
6. **2022 课标二级词汇表 505 词的完整机读版**：官方 PDF 为扫描件，本次 OCR 仅得 247 词；需要有文字层的转载或人工校对。
7. **许可**：djfml 牌组、mahavivo 词表、qwerty-learner 词书 JSON、kajweb 有道镜像均无明确的数据许可；教材词表本身的著作权属上海教育出版社/牛津大学出版社，产品若内置需另行评估。
8. **GitHub code search 未执行**（无 `gh`、匿名 API 配额耗尽），`angelachen825-bit/baicizhan` 等仓库内容未列出，可能遗漏 JSON 词表。
