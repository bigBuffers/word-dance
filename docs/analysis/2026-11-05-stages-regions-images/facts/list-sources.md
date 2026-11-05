# 可机读中国课程英语词表来源清单与许可审计（list-sources）

基线：仓库 `/Users/sqin/word-dance` @ `75df534`（main），线上库只读副本 `scratchpad/live-copy.db`（9,162 词）。日期 2026-11-05。所有网页均为「访问 2026-11-05」。

## 范围与方法

**读过的仓库文件**：`scripts/build_seed.py`（222 行，重点 4–11、15–17、20–47、75–87、102–147、205–217 行）、`data/seed/stats.json`、`data/seed/ATTRIBUTION.md`、`backend/wd/migrations/0001_init.sql`（147–148、181–187、207 行）；线上库 `sqlite3 -readonly live-copy.db ".schema words"` 与计数查询；前次分析 `docs/analysis/2026-11-04-library-curation/facts/seed-pipeline.txt` 仅 grep 核对关键词，结论全部按 75df534 重新核对。

**检索词**（WebSearch）：`牛津上海版 小学英语 单词表 json github`；`上海 中考 英语 词汇表 txt github 沪教版 词汇`；`人教版 PEP 小学英语 单词表 csv json github`；`小学英语单词 json github 词库 人教 外研 译林 北师大`；`义务教育英语课程标准 2022年版 附录 词汇表 小学 词数 一级 二级 三级`；`上海市 初中英语词汇表 2020年版 教委 词数 上海高考英语 考纲词汇 词数`；`huggingface dataset Chinese textbook English vocabulary 小学 初中 高中 单词`；`kaggle dataset 高考 英语 3500 词汇 / gaokao english vocabulary csv`；`上海 高考英语 考纲词汇手册 词汇量 …`；`上海市 小学英语 课程标准 词汇 要求 牛津上海版 …`；`上海市初中英语课程终结性评价指南 2020 词汇表 …`；`义务教育英语课程标准 2011年版 附录 词汇表 二级 …`；`"终结性评价指南" 上海市初中英语课程 …`；`"初中英语课程终结性评价指南" 上海`；`英语课程标准 二级 词汇表 423 …`；`site:kaggle.com dataset English vocabulary Chinese translation CET-4 CET-6 gaokao zhongkao words`。
**GitHub 仓库搜索**（api.github.com/search/repositories，UA `word-dance-research`）：`牛津上海版`、`沪教版 英语 单词`、`上海 中考 词汇`、`小学英语 单词`、`高考 3500 词汇`（`PEP 小学 英语 单词`、`中考 词汇 1600`、`英语 词库 教材 单词表` 三次触发未认证限流 60/h，未取得结果）。
**Hugging Face**：`https://huggingface.co/api/datasets?search=gaokao`、`?search=vocabulary`。

**下载（全部放在 `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/list-sources/`，每项独立目录，只用 `python3 -I`/`pdftotext`/`zstd -d`/只读 sqlite 解析，未执行任何下载内容）**：

| 目录 | 文件 | 来源 | 对应学段/地区 |
|---|---|---|---|
| `01/` | `小学英语大纲词汇.txt`（2,518 B） | mahavivo/english-wordlists | 全国小学（来源未注明） |
| `02/` | `上海市初中英语词汇表（2020年版）.pdf`（1,200,683 B）+ `extracted_layout.txt`/`heads.txt`/`phrases.txt` | mahavivo/english-wordlists | 上海初中（官方词表的第三方转载） |
| `03/` | `中考英语词汇表.txt`（86,765 B） | mahavivo | 全国中考（当前 zk 来源） |
| `04/` | `Highschool_edited.txt`（25,353 B） | mahavivo | 全国高考（当前 gk 来源） |
| `05/` | `OxfordVocabulary_juniorMiddleSH.json`（191,447 B）、`shanghai-6-2-word.json`（17,461 B） | RealKai42/qwerty-learner `public/dicts` | 上海初中 / 上海六年级下 |
| `06/` | `OXFORD.apkg`（146,878 B）+ `extracted/`（zstd 解压的 sqlite） | djfml/englishoxfordshanghaiedition | 上海小学（牛津上海版，非官方） |
| `07/` | `PEPXiaoXue3_1_T.json … PEPXiaoXue6_2_T.json`（8 册，共 127,215 B） | qwerty-learner（源自 kajweb/有道） | 人教 PEP 小学 3–6 年级 |
| `08/` | `ZhongKaoHeXin.json`（496,856 B） | qwerty-learner | 全国中考核心词 |
| `09/` | `GaoKao_3500.json`（679,965 B） | qwerty-learner | 全国高考 3500 |
| `10/` | `book.csv`、`word.csv`（7.26 MB）、`relation_book_word.zip`（10.9 MB → `extracted/relation_book_word.csv` 111 MB）+ `lists/<bk_id>.txt` | LinXueyuanStdio/DictionaryData | 沪教版牛津 7A–9B、牛津上海版 7A/7B、上海市初中英语教学基本要求、2016 高考上海卷、沪教版三年级起点 3–6 |
| `meta/` | 索引/对照文件：`ecdict/ecdict.csv`（66 MB，用于统计 tag 全集与 ECDICT 词形集合）、`kajweb_bookLists.txt`、`qwerty_dictionary.ts`、`lxy_book.csv`、`maimemo_ciku.md`、`zk_words_xcheck/index.json`（zhongkao-words 词表，用于交叉核对 02）、各仓库 `repo_*.json`/README | — | — |

**统计方法**（`tools/stats.py`、`tools/lxy.py`、`tools/compare.py`，位于 `scratchpad/list-sources/tools/`，不在下载目录内）：词头归一化 = NFKC → 小写 → 去首尾空白 → 连续空白压成一个（与 `words.lemma` 的归一化规则一致，见 backend/wd/migrations/0001_init.sql:168 注释 "normalised key: NFKC, lower-case, single spaces, ASCII ' - ."）；「词组」= 归一化后含空格；「重合率」= 归一化词头精确匹配 `select lemma from words`（9,162 行，全部唯一且已小写）；「不在 ECDICT」= 不在 `ecdict.csv` 的 770,611 个 `word`（小写）中；抽样 15 词用 `random.seed(7)`。mahavivo rich 格式的词头解析（`mahavivo_rich` 模式）是对 `build_seed.py:15–17` 三个正则的近似，故 03 的计数（1,897）与 `stats.json` 的 `syllabus_sizes.zk`（1,887）相差 10；04 用 plain 模式，计数 3,448 对 3,446。

---

## 一、当前词库来源（基线事实）

**[list-sources-1] 当前 9,162 词 = ECDICT 1.0.28 中带 zk/gk/cet4/cet6 标签的词 ∪ mahavivo 六个考纲 txt 的词头；阶段 = 两者并集。** 事实，置信度高。
- `scripts/build_seed.py:4-6`：`Inputs (already downloaded): - ECDICT stardict.db (MIT, …) - mahavivo/english-wordlists syllabus lists`；`:10-11`：`Stage codes: zk = 初中(中考), gk = 高中(高考), cet4 …; Each stage set = ECDICT tag ∪ official syllabus list.`
- `scripts/build_seed.py:82-87`：六个文件名 `中考英语词汇表.txt`（rich）、`Highschool_edited.txt`（plain）、`CET4_edited.txt`、`CET6_edited.txt`、`CET_4+6_edited.txt`、`英语六级词汇（星标，1726）.txt`。
- `scripts/build_seed.py:105-106`：`select … from stardict where ' '||tag||' ' like '% zk %' or … '% gk %' or … '% cet4 %' or … '% cet6 %'`——只读四个标签。
- `data/seed/stats.json`：`syllabus_sizes {zk: 1887, gk: 3446, cet4: 4539, cet6: 2220, cet46: 8008, cet6star: 1721}`，`per_stage {zk: 2099, gk: 3829, cet4: 4722, cet6: 7671}`；线上库 `select sum(stage_zk),sum(stage_gk),sum(stage_cet4),sum(stage_cet6) from words` = 2099/3829/4722/7671，`stage_min` 分布 1:2099 2:1792 3:1577 4:3694（与任务背景一致）。
- 推论（高）：zk 层 2,099 = ECDICT `zk` 标签 1,603 词（见 [2]）∪ 中考表 1,887 词头；gk 层 3,829 = ECDICT `gk` 3,677 ∪ Highschool 3,446。

**[list-sources-2] ECDICT 的 `tag` 列全集只有 8 个取值：gre 7,504、toefl 6,974、cet6 5,407、ielts 5,040、ky 4,801、cet4 3,849、gk 3,677、zk 1,603；没有任何小学/课标分级标记。** 事实，置信度高。
- 计算：下载 `https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv`（66,009,548 B，770,611 行，列 `word,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange,detail,audio`），`python3 -I` 用 `csv.DictReader` 按空格切分 `tag` 计数（`meta/ecdict/`）。最常见组合：`gre` 3,489、`toefl` 1,490、`toefl gre` 1,269、`ielts` 594、`zk gk` 478。
- README 字段表（`meta/readme_ecdict.md` 第 40 行）：`| tag | 字符串标签：zk/中考，gk/高考，cet4/四级 等等标签，空格分割 |`。
- Wiki「选词」页 https://github.com/skywind3000/ECDICT/wiki/%E9%80%89%E8%AF%8D（访问 2026-11-05）：「从最初的中高考各类考试大纲开始」「四六级大纲，托福雅思GRE大纲，等，必须覆盖到位」；页面未提及小学。
- 仓库根目录（api `contents`）：`LICENSE`(MIT, 1,063 B)、`ecdict.csv`、`ecdict.mini.csv`、`stardict.7z`(51,577,449 B)、`lemma.en.txt`、`wordroot.txt`、`resemble.txt`、`stardict.py`、目录 `contributions/`、`tests/`——**没有 wordlist 子目录**。
- Releases Atom（`https://github.com/skywind3000/ECDICT/releases.atom`）：`ECDICT - 28` 更新于 2024-12-31，`1.0.27` 2018-05-16；releases 页（访问 2026-11-05）显示 1.0.28 为最新，资产含 `ecdict-sqlite-28.zip`（"有音标"），即仓库当前使用的版本（`ATTRIBUTION.md`：`Release used: 1.0.28 (ecdict-sqlite-28.zip)`）。仓库最近 push 2026-11-02（api `pushed_at`）。

> **核验修正（INDEX §3 #30/#31，2026-11-05）**：① 汇总表里的「ECDICT - 28 更新于 2024-12-31」是 releases feed 的 `updated` 时间戳，不是数据日期——1.0.28 发布于 2017-09-20、`ecdict-sqlite-28.zip` 资产更新于 2018-05-20（GitHub API release JSON），不应读成「数据是 2024 年的」；② 「无小学标签」对 csv 基础版置信为高（8 个 tag 全集已全量计数，且 csv 的 zk 1,603 词与线上 `stage_zk` 100% 一致），对 release `stardict.db` 全集为中（本机无该文件，csv 与 release 有 8 个种子词之差），依据 verify/list-sources.md [list-sources-2]、facts/seed-pipeline.md [seed-pipeline-6]/[seed-pipeline-27]、verify/seed-pipeline.md O5。

**[list-sources-3] 数据模型目前只有四个阶段位，小学没有落点。** 事实，置信度高。
- `backend/wd/migrations/0001_init.sql:181-185`：`stage_zk … stage_gk … stage_cet4 … stage_cet6 INTEGER NOT NULL DEFAULT 0 CHECK (… IN (0,1))`，`stage_min INTEGER CHECK (stage_min BETWEEN 1 AND 4)`；`:147-148`：`stages_json TEXT NOT NULL DEFAULT '["cet4","cet6"]'`，`current_stage INTEGER NOT NULL DEFAULT 3 CHECK (current_stage BETWEEN 1 AND 4)`。
- 线上库 `select count(*) from words where lemma like '% %'` = 13——词库几乎全是单词；下文多个来源含 20–30% 的词组（见表三），接入时要么丢弃词组，要么用 `kind='phrase'`（0001_init.sql:170 `CHECK (kind IN ('word','phrase','abbreviation','proper_noun'))`）。

---

## 二、逐来源清单

### 2.1 mahavivo/english-wordlists（当前考纲来源）

**[list-sources-4] 仓库 28 个文件、无 LICENSE、README 未说明中考/小学/上海三个文件的来源；三文件均在 2021-06-08 一次 "edit" 提交加入。** 事实，置信度高。
- api `repos`：license `None`，stars 2,538，`pushed_at` 2024-05-11，默认分支 master。
- 文件清单（名称, 字节）：`CET4_edited.txt` 198,810；`CET6_edited.txt` 177,864；`CET_4+6_edited.txt` 65,877；`COCA_20000.txt` 170,223；`COCA_abridged.txt` 476,165；`COCA_with_translation.txt` 2,574,417；`GRE_8000_Words.txt` 367,372；`GRE_abridged.txt` 218,859；`GRE_delete_CET4+6+TOEFL.txt` 206,883；`Highschool_edited.txt` 25,353；`NPEE_Wordlist.txt` 300,430；`OALD8_abridged_edited.txt` 1,087,183；`README.md` 2,089；`SUM_of_cet4+6+toefl+gre.txt` 116,972；`TOEFL.txt` 349,781；`TOEFL_abridged.txt` 97,272；`TOEFL_delete_CET4+6.txt` 113,055；`上海市初中英语词汇表（2020年版）.pdf` 1,200,683；`中考英语词汇表.txt` 86,765；`六级词汇表.xlsx` 109,150；`台灣高中英文參考詞彙表.txt` 118,329；`小学英语大纲词汇.txt` 2,518；`柯林斯词频-5星至0星.xlsx` 459,808；`红宝书 GRE词汇精选.csv` 205,335；`英语专业四八级词汇表.docx` 922,877；`英语专业四八级词汇表.txt` 944,986；`英语专业星标八级词汇.txt` 256,862；`英语六级词汇（星标，1726）.txt` 14,914。
- README（`https://raw.githubusercontent.com/mahavivo/english-wordlists/master/README.md`）共 10 条，只说明 CET4（贵州大学 PDF）、CET4+6（cet.edu.cn 2016 大纲）、台灣詞彙表、托福/GRE（2003 版金山词霸）、COCA、OALD8 等；原文：「托福、GRE词汇表来自我个人保存的资料，源于2003年版金山词霸」。中考/小学/上海/Highschool 四个文件在 README 中无一字说明。
- api `commits?path=…`：`小学英语大纲词汇.txt`、`上海市初中英语词汇表（2020年版）.pdf`、`中考英语词汇表.txt` 均只有 1 次提交 2021-06-08 "edit"；`Highschool_edited.txt` 2019-12-15/17。
- 风险：无许可声明；CET4 表源自大学网站 PDF、托福/GRE 源自金山词霸商业产品，权利状态不明；但「考纲词头列表」本身是事实性清单，仓库只用词头（`ATTRIBUTION.md`：`Only the head words are used`）。

**[list-sources-5] `小学英语大纲词汇.txt`：440 条（2 个词组）、全部在 ECDICT、430/440 = 97.7% 已在线上库，且命中的 430 词中 424 词 `stage_min=1`。** 事实（数字），置信度高；文件是哪一版大纲：**未知**（推断为某版课标二级词汇表，低置信）。
- 格式：一行一词、按字母分组空行；含 `colour`/`color`、`bike`/`bicycle` 双写、`China`/`Chinese` 等。缺失的 9 个：`children, feet, has, men, mr, mrs, ms, pe, women`（屈折形/称谓缩写，线上库以原形收录）。
- 抽样 15：grandpa, chinese, is, soup, baby, behind, windy, panda, boat, his, red, banana, night, dog, art。

> **核验修正（INDEX §3 #6，2026-11-05）**：三个数字是三个口径——文件非空行 441（含单字母 `a`、`I`），生产 `parse_list(…, "plain")` 丢掉单字母后得 439（入库口径），本条的 440 是统计多算了一行；在库 429/439 = 97.7%，缺失 9 词清单不变，引用时以 439 为准；另「无法与任何官方数字对账」已不成立：2022 课标附录 3 二级词汇表明确「收录 505 个单词」，可作对账基准，依据 verify/list-sources.md [list-sources-5]、facts/seed-pipeline.md [seed-pipeline-2]。

**[list-sources-6] `上海市初中英语词汇表（2020年版）.pdf`：89 页；单词部分可抽取 1,722 个去重单词 + 309 个词组；1,693/1,722 = 98.3% 已在线上库；与第三方独立解析（zhongkao-words，1,722 词）核对一致 1,711 词，差异 11 项全为格式差异。** 事实，置信度高（内容）；「是否为上海市教育考试院官方原件」中置信（见 [27]）。
- `pdfinfo`：Pages 89，Creator `Acrobat PDFMaker 17 Word 版`，Producer `Adobe PDF Library 15.0`，CreationDate 2019-09-30，Title `Medical NOte`（Word 模板残留，说明是从 Word 转出的文档）。
- 结构（`pdftotext -layout` 后 2,759 行）：第 1–3 行标题「英语词汇表 / 单词(Vocabulary)」，A–Z 单词表至 2,195 行；2,196 行「词组(Phrases and Expressions)」至 2,568 行；2,569–2,601 人称/物主/反身代词表；2,602 基数词和序数词；2,687 月份和星期；2,702 国家、大洲及其对应的人；2,749 常用学科。
- 抽取方法：单词段内取列首为字母的行，正则 `^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-\./]*(?:\s\([^)]*\))?…)\s+(?=词性标记|CJK|()`，去掉括号内不规则形式（如 `bite (bit, bitten)` → `bite`，131 条），把 5 个 `x/y` 行拆成两词（`although/though, anybody/anyone, bicycle/bike, everybody/everyone, somebody/someone`）：1,718 行 → 1,723 → 去重 1,722。未被正则命中的列首行 6 条需人工处理：`exam=examination, grandma=grandmother, grandpa=grandfather, manner(s), more(much 或 many 的比较级), toward(s)`。
- 交叉核对：`meta/zk_words_xcheck/index.json`（lolo811109-crypto/zhongkao-words，`count: 1722`，`fields: [id, word, zh, ipa, cefr, topic, media]`）与我方集合交集 1,711；我方独有 `a.m., anyone, bike, café, everyone, o'clock, p.e., p.m., someone, though, will aux .v.`（变体拆分与 `a.m.`→`a-m` 之类的 id 化），对方独有 `a-m, exam, grandma, grandpa, manner, more, o-clock, p-e, p-m, toward, will`（正是上述 6 条 "=" 行 + id 化拼写）。两套独立解析得到同一规模 1,722，说明该 PDF 单词表规模可信。
- 线上库重合：全部 1,693/1,722（98.3%），单词 1,693/1,721；命中词 `stage_min` 分布 {1: 1,385, 2: 235, 3: 59, 4: 14}——即 308 个上海初中词在线上库被标为高中/四六级层。缺失 28 词：`angrily, beautifully, bund, café, carefully, dancer, dishonest, embarrassed, excited, frightened, frightening, frozen, …`（多为派生副词/分词形容词 + 上海专名 bund）。唯一不在 ECDICT 的词头：`café`（ECDICT 收 `cafe`）。
- 抽样 15：grass, common, judge, select, aunt, belong, will aux .v.（解析残留）, performance, break, humorous, protect, bar, online, download, area。
- 词组 309 条（`a bit, a couple of, … would rather`），线上库仅命中 3 条。

> **核验修正（INDEX §3 #1/#2/#4，2026-11-05）**：① 该 PDF 就是上海市教育考试院发布页同时挂出的「2020年上海市初中英语课程终结性评价指南词汇表」（`download/20190926/07.pdf`），md5 `059df9c02684bd989fff6f8849ee1993` 与 mahavivo 副本完全相同，是一手官方件，「是否官方原件」可由中置信上调为高；② 单词 1,722 与独立解析一致，裁定口径 ≈1,720–1,731 单词（差别只在并列词是否拆分），但词组裁定为 331–342 条（手册 335），本条的 309 是另一种抽取口径、偏少；③ 「缺失 28 词」按 `word_forms` 拆分后真缺只有 14 个（angrily, beautifully, bund, carefully, dancer, dishonest, hot-dog, luckily, mr, mrs, politely, quietly, seafood, unforgettable），12 个是库内原形的屈折形式、`café`/`yogurt` 是拼写变体，依据 verify/list-sources.md [list-sources-6]、verify/provinces.md [provinces-12] 修正 1、verify/shanghai-secondary.md [shanghai-secondary-7]/[shanghai-secondary-19]。

**[list-sources-7] `中考英语词汇表.txt`（当前 zk 来源）：1,899 条/1,897 去重，含音标与释义，147 个词组；词头脏数据明显（43 条非 ASCII、141 条含括号、17 条超长）；与上海 2020 单词表只有 68% 重合。** 事实，置信度高。
- 格式样例（文件第 3 行）：`a (an) [ə, eɪ(ən)] art. 一（个、件……）`。脏词头示例：`begin(began,begun)`、`centre (美 center )`、`child (复children)`、`am/æm/ v. be的人称形式之一 `（私用区字符）、`p.c.(缩) =personal computer`。16 个单词不在 ECDICT（全部是上述未拆开的不规则形式写法）。
- 线上库：1,741/1,897 = 91.8%（单词 1,735/1,750 = 99.1%，命中全部 `stage_min=1`，因为它就是 zk 层来源）。
- 与 02（上海 2020）的差异：沪有全国无 556 词（如 `accurate, ache, achieve, actor, actress, actually, adult, adventure, advise, ambition, amount, ancient, …`），全国有沪无 585 词（如 `action, africa, aircraft, airplane, alike, amaze, america, angel, apology, april, arab, asia, asleep, august, australia, badly, bake, bamboo, band, bang, …`）——其中专有名词/月份在上海表中单列在附表而非 A–Z 正文。
- 抽样 15：go (went, gone), conductor, indeed, refuse, ball, blind, till, nose, bus, hey, people, bedroom, woolen, music, drunk。

> **核验修正（INDEX §3 #5，2026-11-05）**：本条数字来自自写的近似解析，不是生产口径——按 `scripts/build_seed.py:15-17` 的 `RICH_RE`/`POS_RE` 重跑得 1,887 个词头（= `stats.json` 的 zk = 库中 `sources` 含 zk 的词数），词组只有 6 个（computer game, fruit juice, middle east, olympic games, the pacific ocean, swimming pool），1,887/1,887 = 100% 在库且 `stage_min=1`；「147 个词组」「91.8% 在库」「141 条含括号」描述的是原始文件行（`begin(began,begun)` 之类被当成词头），不是入库词头；与上海表重合 `03→02` 1,282/1,881 = 68%、`02→03` 1,282/1,721 = 74%，沪有全国无 439、全国有沪无 599（原 556 / 585）；另生产正则丢弃 7 行（`best`、`café`、`less`、`more`、`practice`、`silent`、`wolf`），其中 `best`（stage_min=3）与 `less`（stage_min=2）因此不在初中层，依据 verify/list-sources.md [list-sources-7]、verify/provinces.md [provinces-25] 修正 1、verify/shanghai-secondary.md [shanghai-secondary-17]。

**[list-sources-8] `Highschool_edited.txt`（当前 gk 来源）：3,468 行/3,448 去重、纯词头无释义、2 个词组；3,447/3,448 = 100% 在线上库（按构造必然）。** 事实，置信度高。命中词 `stage_min` {1: 1,877, 2: 1,570}；唯一不在库/不在 ECDICT 的词头 `café`，另 `sideroad` 不在 ECDICT 但在库。

### 2.2 skywind3000/ECDICT —— 见 [list-sources-2]。MIT；无词表子目录；无小学标签；适用于释义/音标/词频/变形底座，不能提供学段分级。

### 2.3 kajweb/dict（任务原文写「百词斩词书」，实为**有道背单词**词书爬取）

**[list-sources-9] kajweb/dict 是网易有道「背单词」词书的爬取镜像：81 本词书，含人教小学 3–6（8 册 849 词）、人教初中/高中、外研初中、北师大高中、有道中考/高考词、新东方初中/高中词；没有任何上海/牛津上海/沪教/译林词书；无 LICENSE。** 事实，置信度高。
- README 首行：`# 单词本源 / Crawl from "X 道背单词(app)"`；`bookLists.txt`（68,798 B）是一行 JSON `{"reason":"succ","code":200,"data":{"normalBooksInfo":[…]}}`，81 本；`offlinedata` 全部指向 `ydschool-online.nos.netease.com`（有道学堂对象存储）；`bookOrigin.originName` 分布：人教版教材 24、有道词典 20、北师大版高中教材 11、有道考神团队 9、外研社初中教材 6、新东方系列 10。
- 与 小学/初中/高中/人教/外研/北师大/中考/高考 相关的 47 本（id, 词数）：`PEPXiaoXue3_1…6_2` 64/72/84/104/131/156/130/108；`PEPChuZhong7_1…9_1` 392/492/419/466/551；`PEPGaoZhong_1…11` 311/319/366/307/357/391/384/420/352/361/309；`BeiShiGaoZhong_1…11` 226–364；`WaiYanSheChuZhong_1…6` 629/438/320/266/381/128；`ChuZhongluan_2`/`ChuZhong_2` 中考必备词汇 1,420；`GaoZhongluan_2`/`GaoZhong_2` 高考必备词汇 3,668（tags 人教版）；`ChuZhong_3` 新东方初中词汇 1,803；`GaoZhong_3` 新东方高中词汇 2,340。**不含** 上海、牛津、沪教、译林。
- `book/` 目录 93 个 zip（GitHub tree 页，访问 2026-11-05：「93 zip files」），每个 zip 内为逐词 JSON；README「JSON 格式说明」示例 `CET4_3.json` 第一词 `cancel`：字段 `wordRank, headWord, content.word.content.{exam[], usphone, ukphone, trans[], sentence, phrase, …}`——**含音标、释义、例句、选择题**。
- README 另附 `replaceFran()` 代码：「部分字典混入了少量法语字母」——词头可能含 é/ê/ç 等需清洗。
- 许可/风险：api license `None`；`pushed_at` 2024-04-05；数据权利属有道/新东方/教材出版社，非开放许可。

### 2.4 RealKai42/qwerty-learner

**[list-sources-10] qwerty-learner 的 `public/dicts` 有 380 个文件、索引 `src/resources/dictionary.ts` 373 条；「青少年英语」类覆盖人教/外研/冀教/北师大/译林高中/北京初中/RAZ/EF/新概念/剑桥 JOIN IN，上海相关只有两条：`SHjuniormiddleOxford`（1,270，"上海初中牛津词汇"）与 `shanghai-6-2word`（274，"上海新教材六年级下"）；没有沪教/牛津上海版小学 1–5 年级或高中词书。** 事实，置信度高。
- api `contents/public/dicts`：380 entries；`dictionary.ts` 4,200 行，解析得 373 条，分类计数：`('青少年英语','人教版') 36`、`('青少年英语','外研版') 30`、`RAZ 30`、`EF 16`、`冀教版 13`、`北师大 11`、`新概念英语 8`、`译林版 3`、`('青少年英语','牛津版') 1`、`('青少年英语','上海版') 1`、`('中国考试','其他') 23` 等。
- 人教：`san1…liu2` 小学三年级起点 3上–6下（64/72/84/104/131/156/130/108）、`pep-sl-yi1…liu2` 新起点 1上–6下（52/45/54/55/103/84/116/87/66/96/102/41）、`qi1…jiu` 初中 392/492/419/466/551、`renjiaogaozhong1…11` 高中 311–420。外研：一年级起点 1上–6下（138/118/118/110/82/106/116/78/80/72/61/91）、新起点 3上–6下（134/156/144/134/152/147/83/105）、初中 7上–9下（629/438/320/266/381/128）、新外研 7 上/下（294/306）、高中必修 1–2（411/272）。冀教 3上–9（75–636）。北师大高中必修 1–选修 11。译林高中必修 1–3（276/297/295）。`BJJuniorHigh` 北京初中 1,844。`Cambridge_JOIN_IN` 1,350。中国考试：`zhongkaohexin` 2,140、`gaokao3500` 3,893、`gaokaozhentihexin` 799、`gaokao-yuedu-gaopin` 688。
- 文件格式：JSON 数组 `[{name, trans[], usphone, ukphone}]`（部分无音标）。
- 许可/来源：仓库 GPL-3.0（api）；README 第 304 行「字典数据来自于 kajweb（https://github.com/kajweb/dict），项目爬取了常见的字典」，第 306 行「语音数据来源于有道词典开放 API」——即数据与 kajweb 同源（有道）；上海两条为社区贡献：`OxfordVocabulary_juniorMiddleSH.json` 首次提交 2023-02-10 "feat: add SHjuniormiddleOxford dictionary (#310)"（Yangthemob），之后 2023-05-13 去首尾空格、2023-09-08 更新音标、2025-12-12 "fix: chinese punctuation"；`shanghai-6-2-word.json` 2025-02-24 "feat: add dict"（RealKai42，commit 737772c）。两者 README 均未说明教材版本与出处。

**[list-sources-11] `OxfordVocabulary_juniorMiddleSH.json`（05a）质量差：1,270 条/1,258 去重，123 词组，91 个"单词"是去掉空格的词组（`accordingto, aimat, asaresult, aswellas, atnight…`），拼写错误（`angency, archtecture`），单词层面仅 83.1% 在线上库；与上海 2020 官方表仅 47% 重合，但 DictionaryData 的「牛津上海版七年级上/下」99% 包含于它。** 事实（数字）；「它是牛津上海版 6–9 年级教材词表的转录」为推断，中置信。
- 线上库：943/1,258 = 75.0%；单词 943/1,135 = 83.1%；命中 `stage_min` {1: 518, 2: 261, 3: 116, 4: 48}；缺失 192（含 `abacus, airconditioner, amazed, …`）。
- 抽样 15：level, cruise, pain, atleast（脏）, bite, such as, calculator, nasty, unhappy, balance, slide, faithfully, architect, bubble, publish。

**[list-sources-12] `shanghai-6-2-word.json`（05b）：274 条，14 词组，0 条不在 ECDICT，251/274 = 91.6%（单词 96.5%）在线上库；单册、来源未注明。** 事实，置信度高。缺失 9：`changer, heatwave, low-energy, nightingale, noticeboard, penicillin, reusable, saver, storyteller`。抽样 15：performance, festival, save, bulb, cloth, daily, ready, celebrate, unique, international, break out, country, sort, skin, check out。

**[list-sources-13] PEP 小学 3–6（07，8 册）：849 条 → 819 去重（30 跨册重复）、110 词组、709 单词中 630 = 88.9% 在线上库；缺失多为屈折形与专名（`ate, bought, bigger, cleaned, climbing, alaska, canberra, bunny, cheetah…`）；仅 4 条脏词头（`have...class, having...class, house., wear.`）。** 事实，置信度高。各册计数与 kajweb/有道 `wordNum` 完全一致（64/72/84/104/131/156/130/108），证实同源。命中 `stage_min` {1: 595, 2: 19, 3: 9, 4: 8}。抽样 15：high, deep, living room, studies, beef, bread, pupil, car, keep your desk clean, seventeen, bird, picnic, family, basket, by。

**[list-sources-14] `ZhongKaoHeXin.json`（08）：2,140 条 → 2,135 去重，4 词组，0 条不在 ECDICT，2,034/2,135 = 95.3% 在线上库；缺失 99 词多为派生词（`anymore, backpack, beautifully, believable, burning, carefully, carelessly, caring, cheaply, climber…`）；索引描述只有「中考核心词」，来源未注明（与有道「中考必备词汇」1,420 规模不同）。** 事实，置信度高。命中 `stage_min` {1: 1,682, 2: 225, 3: 77, 4: 50}。抽样 15：perhaps, fascinating, seventeen, boring, cheese, could, regret, butterfly, will, i, bee, communication, study, song, chalk。

**[list-sources-15] `GaoKao_3500.json`（09）：3,893 条 → 3,875 去重，182 词组，单词 3,650/3,693 = 98.8% 在线上库；10 个词头不在 ECDICT（`ad., department-store, gettogether, softdrink, zebra-crossing…`），另有 `understand understood understood`、`vcd = versatile compact disk`、`grey / gray` 等需清洗；与 `Highschool_edited` 重合 88%。** 事实，置信度高。命中 `stage_min` {1: 1,947, 2: 1,706, 3: 3, 4: 2}。抽样 15：fence, cater, hawk, railway, anyway, authentic, tear, negotiate, bedroom, gesture, part-time, arm, watermelon, microscope, cotton。

### 2.5 KyleBing/english-vocabulary

**[list-sources-16] KyleBing/english-vocabulary：BSD-3-Clause；7 个词库（初中 3,223 / 高中 6,008 / 四级 7,508 / 六级 5,651 / 考研 9,602 / 托福 13,477 / SAT 8,887 = 54,356 条）txt/json/jsonl/tsv 四种格式；README 自述 `kajweb/dict → fork → KyleBing/dict → 简化 → 本库`，即同为有道数据；无小学、无上海。** 事实，置信度高。
- api：license BSD-3-Clause，stars 2,175，`pushed_at` 2026-09-30。文件：`1 初中-乱序.txt` 206,943 B … `7 SAT-乱序.txt`；`json/1-初中-顺序.json` 2,986,964 B … `7-SAT-顺序.json`；目录 `full_line_jsonl/`、`full_line_tsv/`、`乱序sql/`。README：「乱序是另一套词表，词数不同」；jsonl 含「词条、词组、近义词、释义、例句」。
- 风险：BSD 声明由镜像作者作出，不能覆盖上游有道/新东方内容的权利；「初中 3,223 词」远大于课标 1,600，说明是商业词书而非考纲。未下载。

### 2.6 LinXueyuanStdio/DictionaryData

**[list-sources-17] DictionaryData：Apache-2.0；583 本词书、70,164 词、1,044,580 条书–词关系；25 个顶级分类中「小学英语」含 149 本（19 个教材系列）；上海相关 5 组词书全部可抽取：沪教版牛津英语 7A–9B、牛津上海版七年级上/下（2008/2009 第 2 版）、上海市初中英语教学基本要求（2,201，上海教育出版社 2008-11）、2016 高考英语词汇上海卷（4,022，人民教育出版社 2015-10）、沪教版三年级起点 3上–6下；README 没有任何数据来源说明。** 事实，置信度高；「数据来自某背单词 App 数据库导出」为推断，低置信（`vc_id` 为 MongoDB ObjectId、字段有 `vc_acknowledge_rate` 认识率）。
- 文件：`book.csv` 163,644 B（583 行，`>` 分隔，字段 `bk_id>bk_parent_id>bk_level>bk_order>bk_name>bk_item_num>…>bk_publisher>bk_version>bk_flag`）、`word.csv` 7,255,538 B（`vc_vocabulary, vc_phonetic_uk, vc_phonetic_us, vc_frequency, vc_difficulty, vc_acknowledge_rate`）、`word_translation.csv` 4,715,776 B、`relation_book_word.zip` 10,899,013 B（解压 110,974,824 B，字段 `bv_book_id>bv_voc_id>bv_flag>bv_tag(单元)>bv_order`）。api：license Apache-2.0，stars 666，`pushed_at` 2025-03-28。
- 顶级分类（名称, 条目数）：大学英语四级词汇 74,062；小学英语 15,233；高中英语 99,952；新概念英语 7,593；分频词汇 52,790；托福 29,618；GRE 22,993；雅思 50,216；六级 75,817；专八 43,013；BEC 10,335；GMAT 10,028；考研英语 256,390；其他书籍 37,488；专四 23,899；大学英语教科书类 26,722；托业 5,037；SAT 11,460；初中英语 23,885；ACT 3,541；全国等级考试 27,078；词典单词 6,187；考博 6,916；MBA 6,731；老版词书 78,984。
- 小学英语 149 本 = 人教一年级起点 12 本 908 词、人教三年级起点 8 本 851、冀教三起 8 本 605、北京版一起 12 本 808、北师大一起 12 本 925、北师大三起 8 本 699、外研三起 8 本 1,157、广东版 8 本 741、广州版 8 本 1,269、教科版 EEC 8 本 1,093、沪教版三起 8 本 1,080、湘少版 8 本 698、科普版 8 本 772、译林三起 8 本 1,036、译林小学 1–2 年级 4 本 255、译林牛津 1A–2B 4 本 163、闽教版 8 本 772、陕西版 8 本 917、另 1 本教辅 1,181（版次多为 2012–2016 年第 1 版）。
- 上海书目（bk_id, 名称, 词数, 出版社, 版次）：`58b2991c…` 沪教版牛津英语七年级上册 222（上海教育出版社 2012-07）、`58b29c2d…` 七下 232、`58b29ef2…` 八上 232、`58b2a072…` 八下 257、`58b2a18a…` 九上 262、`58b2a32f…` 九下 195；`5ca45fab…` 牛津上海版七年级上册 207（2008 年 7 月第 2 版）、`5ca460c0…` 七下 214；`e7b24b11…` 上海市初中英语教学基本要求 2,201（2008-11 第 1 版，单元标签「基本词汇表 表（一）单词（Words） A…」26 组）；`94f6d7e0…` 2016高考英语词汇上海卷 4,022（人民教育出版社 2015-10）；`5881d206…`/`5881d2ea…`/`5881d537…`/`5881d60d…`/`5881d6af…`/`5881d6be…`/`5881d869…`/`5881d92c…` 沪教版三年级起点 3上–6下 75/114/139/151/164/165/135/137。关系表与 `bk_item_num` 完全一致，`vc_id` 全部可解析（unresolved 0）。
- 注意：「沪教版三年级起点」是上海教育出版社面向外省（6-3 学制）的牛津英语版本，**不是**上海本地 5-4 学制使用的「牛津上海版 1A–5B」；本仓库没有牛津上海版小学与高中册。

**[list-sources-18] DictionaryData 上海五组词表的实测：** 事实，置信度高（表中数字来自 `tools/stats.py`，命令见「方法」）。

| 组 | 条目 → 去重 | 词组 | 单词在线上库 | 命中 stage_min 分布 | 缺失示例 | 抽样 15 |
|---|---|---|---|---|---|---|
| 10a 沪教版牛津 7A–9B | 1,400 → 1,362 | 341 | 985/1,021 = 96.5% | 1:754 2:164 3:47 4:21 | annoying, anytime, asteroid, braces, brightly, celebrated, chessboard, cola, confidently, congratulations, cormorant, doorbell | invitation, countryside, natural disaster, wheel, ask permission, be made up of, shoot, building, magazine, superman, awful, risk, fair, anytime, boss |
| 10b 牛津上海版 7A+7B（2008/09） | 421 → 421 | 71 | 324/350 = 92.6% | 1:193 2:71 3:41 4:19 | brightly, bund, coloured, creek, dice, dimple, floating, hard-working, helper, iced, icing, karaoke | hate, check, knock down, silly, at last, bathroom, yourselves, play with, booklet, in the end, reel, australian, oven, direction, anything |
| 10c 上海市初中英语教学基本要求（2008） | 2,201 → 2,191 | 365 | 1,681/1,826 = 92.1% | 1:1409 2:205 3:53 4:17 | accurately, angrily, ate, beaten, beautifully, became, been, began, begun, bitten, blew, blown（该表把不规则动词各形式单列） | nobody, enjoyable, responsible, be strict with, burn, choose, policemen, bill, waitress, guest, bag, center, slowly, series, broke |
| 10d 2016 高考英语词汇上海卷 | 4,021 → 4,016 | 142 | 3,706/3,874 = 95.7% | 1:1797 2:1129 3:628 4:153 | according, air-conditioned, analyses, antipollution, anymore, aspirin, audio-visual, awaken, bamboos, bases, bathing, bears | fax, weapon, cigarette, hanged, poem, arouse, barely, stadium, mend, bless, geography, now, atmosphere, turn out, look out of |
| 10e 沪教版三年级起点 3上–6下 | 1,080 → 1,008 | 203 | 768/805 = 95.4% | 1:715 2:30 3:19 4:6 | bedtime, bigger, carefully, children, cola, craftsman, dancer, dr., duckling, e-friend, excited, fairest | get off, where, children, help, police, august, before, swing, mooncake, book, handsome, oil painting, bathroom, us, man |

五组中单词不在 ECDICT 的仅 10d 的 `hitech, résumé`，其余为 0——词头本身干净，脏点在于屈折形式单列与词组占比 10–25%。

### 2.7 其他 GitHub 结果

**[list-sources-19] lolo811109-crypto/zhongkao-words：上海中考 1,722 词的背词网站，词表声明来自上海市教育考试院《2020年上海市初中英语课程终结性评价指南》，PDF 取自 mahavivo 并由脚本解析；代码 MIT，内容标 CC BY 4.0（改编自 designfuchen/word-atlas）。** 事实（声明内容），置信度高；词表与官方一致性见 [6]。
- README 原文（`https://raw.githubusercontent.com/lolo811109-crypto/zhongkao-words/main/README.md` 第 3–7 行）：「上海中考英语考纲词汇 1,722 词的背词网站，改编自 designfuchen/word-atlas」「词表与中文释义：上海市教育考试院《2020年上海市初中英语课程终结性评价指南》词汇表（单词部分；词组部分未收录），PDF 取自 mahavivo/english-wordlists，由脚本解析。」「与原词库重合词的插画、例句、录音、释义：Word Atlas contributors — CC BY 4.0，已修改。」
- 数据文件：`public/atlas/index.json`（134,274 B，`name: 词光 中考`，`license: CC BY 4.0`，`count: 1722`，`fields: [id, word, zh, ipa, cefr, topic, media]`，另有 `topics` 19 个主题）+ `public/atlas/{entries,img,thumb,audio}/`；GitHub 搜索显示 stars 2、`pushed_at` 2026-10-25、1 次提交。
- 上游 designfuchen/word-atlas（访问 2026-11-05）：7,298 个 CEFR A1–C2 雅思导向词条、14,596 例句、7,298 张 512px WebP 插画、22,905 段音频；README 自述「text and illustrations use generative AI」「speech uses ElevenLabs」「has not undergone line-by-line human review」；代码 MIT、内容 CC BY 4.0。——对本项目的意义：词表部分是官方表的再解析（可作核对），插画/例句是 AI 生成、未人工审核，不宜直接当权威内容。

**[list-sources-20] lolo811109-crypto/chuyi-words：沪教版牛津英语 7A（2024 版）+ 7B 词表，自述取自 busiyiworld/maimemo-export（墨墨背单词导出），「非出版社官方数据」。** 事实，置信度高。README 第 5 行：「词表与中文释义：沪教版牛津英语七年级上册（2024版）、七年级下册，来自 busiyiworld/maimemo-export（墨墨背单词词库导出，MIT）；源数据中无释义的专有名词/短语未收录。非出版社官方数据。」

**[list-sources-21] busiyiworld/maimemo-export 的词库目录（`词库.md`，1,121 本）是本次唯一同时覆盖上海三学段的来源：牛津上海版一年级上册…五年级下册（10 册）、六年级上册…九年级下册（8 册）、高一上…高三下（6 册），另有沪教版牛津英语 7A（含 2024 版）–9B、沪教版三年级起点（含「三年级上（2024新版）」）、「上海市初中英语考纲词汇」、「2024上海市高考英语考纲词汇用法手册」；但许可为「仅用于学习，禁止用于商业用途。词库版权归 墨墨背单词 所有」。** 事实，置信度高（目录）；各册词数未核验（未下载）。
- `https://raw.githubusercontent.com/busiyiworld/maimemo-export/main/词库.md`：表头 `| 词库名 | 仅单词 | 单词和章节 | 单词和翻译 |`；关键词计数：上海 26、沪教 16、牛津上海版 24、牛津 48、小学 10、初中 46、高中 111、中考 8、高考 35、人教 52、外研 53、译林 30、北师大 46、冀教 26。链接形如 `./exported/word/牛津上海版一年级上册.txt`、`./exported/list/…txt`（含章节）、`./exported/translation/…csv`（含释义）。
- README（访问 2026-11-05）：MIT 许可 + 「仅用于学习，禁止用于商业用途。词库版权归 墨墨背单词 所有」；中文释义「来源于 ECDICT-ultimate」而非墨墨导出。
- 结论：可作**核验基准**（例如核对 02/10a/06 的覆盖面、获取牛津上海版 1A–5B 与高中册的词头），不能作为产品数据来源直接分发。

**[list-sources-22] djfml/englishoxfordshanghaiedition 的 `OXFORD.apkg`（自述「上海版牛津小学英语全部单词带音标 anki deck」）：1,042 张卡/1,040 去重，单一牌组「OXFORD」，无年级/册别字段，正面=词、背面=`释义[音标] 词性`；200 条是词组或整句，43 条含「→」变形对，含拼写错误；单词层面 770/840 = 91.7% 在线上库；无许可、无来源、无版本。** 事实，置信度高。
- 结构：zip 内 `collection.anki21b`（zstd，解压 421,888 B sqlite，表 notes/cards/decks/notetypes…）、`collection.anki2`（旧格式占位，仅 1 条「Please update to the latest Anki version」）、`media` 9 B（无媒体）。notetype「基本」，字段「正面/背面」。样例：`Pen | 钢笔[pen] n`、`pencil-case | 铅笔盒['penslkeis] n`、`very much | 非常 ad`。
- 脏数据：`big → bigger`、`collect stamps→collecting stamps`、`how do you spell that in englis?`、`can i have......,please?`、`take a no.7 bus`、`catc(bus)`、`bigmac`/`mcchicken`；18 个单词不在 ECDICT（上述拼接物）。缺失（真实词）示例：aquarium, aviary, caterpillar, cocoon, corm, dining。
- 抽样 15：playground, food, sock(s), bottle, chopsticks, cross, see, by underground, zoo keeper, hurry up!, big, comic, their, swimming-pool, children。
- 与其他小学表重合（单词）：含 01 大纲表的 83%，与 PEP 3–6 互含 49%/58%，与沪教三起 57%/59%。

**[list-sources-23] 高考 3500 类仓库：pluto0x0/word3500（MIT，`3500.txt`，PHP+MySQL 应用，19 次提交，2019-10-24 最后 push，43★）、LazuliKao/brochure-of-vocabularies（Apache-2.0，8★，2021-09）、WhaleFell/GK3500EnglishWord（无许可，2023-11）。** 事实（元数据），置信度高；内容未下载，因 qwerty `GaoKao_3500`（3,875）已覆盖同一需求且 98.8% 在库。

**[list-sources-24] 上海高中教材没有找到可机读词表；最接近的是 ZhangYixuan-in-BUPT/textbook-sentence-index（MIT，`textbook_index_data.zip` 28.58 MB）：人教版 2019 与沪教版高中必修 1–4、选修 1–4 的句子倒排索引（>10,000 词为键，每句标注教材/册/单元），自述「数据来源于公开出版教材，仅供学习研究使用」。** 事实，置信度高（访问 2026-11-05 的仓库自述）。它不是词汇表（键是出现过的所有词形），只能用来反推沪教版高中教材用词与例句。其余搜索命中（andy71111/word-pk 沪教版初中单词 PK，MIT；junglehu/english-trainer 沪教版 2024 七上；Freddiehuhu/English-Learning-Strategy 沪教版八上 Anki 卡；johnsonleecplus-png/English-Book 上海中考词汇 PWA）均为 0–1★ 个人项目，未核验数据文件。

### 2.8 非 GitHub 公开数据

**[list-sources-25] Hugging Face：`search=gaokao` 返回 45 个数据集，全部是试题/评测集（AGIEval、GAOKAO-Bench 等），无词表；`search=vocabulary` 中唯一相关的是 `SwiftieJerry/english-vocabulary-materials`（85 个文件 442.74 MB，8,257 条结构化词条，含「初中词汇 1,835/1,994」「高中词汇 2,434」与雅思分级词表，来源「绿新」教学材料，许可 CC BY-NC-ND 4.0，v1.0.0 2026-08-29）；Kaggle 两次检索没有任何中国课程词表数据集命中。** 事实，置信度高（访问 2026-11-05）。NC-ND 禁止商用与演绎 → 不可采用。

### 2.9 官方文件线索（供其他任务衔接）

**[list-sources-26] 2022 年版义务教育英语课程标准的词汇量：二级（小学毕业）「能初步运用500个左右单词」，三级（初中毕业）「学习并使用约1600个单词」，各可另接触 100–300 词。** 事实，置信度中（二手转述，未取得教育部原件电子版）。
- https://m.163.com/dy/article/HB20L7VV0536EPBU.html（访问 2026-11-05）：「二级：能初步运用500个左右单词，就规定的主题进行交流与表达，另外可以根据实际情况接触并学习三级词汇和相关主题范围内100-300个单词」「三级：围绕相关主题学习并使用约1600个单词进行交流与表达，另外可以根据实际情况接触并学习相关主题范围内100-300个单词」。
- 2011 年版官方 PDF（`https://www.yunyang.gov.cn/...W020210412555161173233.pdf`）WebFetch 失败（proxy refused），二级/五级词表规模未核实；mahavivo 的 440 词小学表无法与任何官方数字对账。

**[list-sources-27] 上海官方词表的电子版均未在官方站点找到：2020 版初中词表只有 mahavivo 转载的 PDF（[6]）及其第三方再解析（[19]）；上海中考 App 商店文案称「1719 个词汇」（apps.apple.com id1574077669，访问 2026-11-05：「上海中考英语考纲词汇 1719」），与 PDF 的 1,722 相差 3；上海高考考纲词汇仅见于 maimemo 目录「2024上海市高考英语考纲词汇用法手册」与 DictionaryData「2016高考英语词汇上海卷」4,022 词；牛津上海版小学 1A–5B 官方词表未找到。** 事实（未找到）+ 低置信的 App 文案数字。

---

## 三、交叉比较（单词层，归一化后精确匹配；`tools/compare.py`，输出 `meta/compare_output.txt`）

**[list-sources-28] 小学候选表之间重合度低、规模 440–840：四表单词并集 1,521，其中 179 词完全不在线上库、210 词在库但 `stage_min>1`。** 事实，置信度高。

| A \ B（|A∩B|/|A|） | 01大纲(438) | 07PEP3–6(709) | 10e沪教三起(805) | 06apkg(840) | 05b沪6B(260) | DB.zk | DB.all |
|---|---|---|---|---|---|---|---|
| 01 大纲 440 | 100% | 73% | 83% | 72% | 0% | 97% | 98% |
| 07 PEP 3–6 | 45% | 100% | 62% | 58% | 5% | 84% | 89% |
| 10e 沪教三起 3–6 | 45% | 55% | 100% | 59% | 9% | 89% | 95% |
| 06 apkg 上海牛津小学 | 38% | 49% | 57% | 100% | 6% | 80% | 92% |
| 05b 上海 6B | 0% | 13% | 28% | 18% | 100% | 74% | 97% |

> **核验修正（INDEX §3 #7，2026-11-05）**：标题数字错——四表（01、07、10e、06）单词并集为 1,365 词、170 不在库、160 在库但 `stage_min>1`；1,521 / 179 / 210 是再并入 05b（上海 6B，260 词）的五表并集（核验重算 1,520 / 179 / 210）；表格各格重算一致；[list-sources-32]-4 沿用了同一组数字，应按五表并集理解，依据 verify/list-sources.md [list-sources-28]。

**[list-sources-29] 初中：上海 2020 表（1,721 单词）80% 落在线上库 zk 层、98% 在库；与 2008《教学基本要求》重合 88%；与全国中考表（当前 zk 来源）仅 68%；与中考核心词 83%；七表并集 3,425 词，451 词不在库，917 词在库但 `stage_min>1`。** 事实，置信度高。

| A \ B | 02沪2020 | 10c沪2008 | 05a | 10a沪教牛津7–9 | 10b牛津上海7 | 03全国中考 | 08中考核心 | DB.zk | DB.all |
|---|---|---|---|---|---|---|---|---|---|
| 02 沪2020 (1,721) | 100% | 88% | 31% | 41% | 11% | 68% | 83% | 80% | 98% |
| 10c 沪2008 (1,826) | 83% | 100% | 27% | 37% | 10% | 65% | 78% | 77% | 92% |
| 05a (1,135) | 47% | 44% | 100% | 38% | 30% | 39% | 47% | 46% | 83% |
| 10a 沪教牛津7–9 (1,021) | 69% | 66% | 42% | 100% | 14% | 60% | 77% | 74% | 96% |
| 10b 牛津上海7 (350) | 52% | 52% | 99% | 42% | 100% | 48% | 59% | 55% | 93% |
| 03 全国中考 (1,750) | 67% | 68% | 25% | 35% | 10% | 100% | 79% | 99% | 99% |
| 08 中考核心 (2,131) | 67% | 67% | 25% | 37% | 10% | 65% | 100% | 79% | 95% |

> **核验修正（INDEX §3 #1/#5，2026-11-05）**：「451 词不在库」应为 437——多出的 14 个是近似解析得到的脏词头（`a (an)`、`awake (awoke, awoken)` 之类），按生产正则它们不存在；03 列（全国中考表）应按生产口径 1,887 词头计，`02→03` 为 74% 而非 68%，其它行的 03 列差 1–3 个百分点；3,425 与 917 重算一致；上海 2020 表的裁定口径为 ≈1,720–1,731 单词，本条的 1,721 在区间内，依据 verify/list-sources.md [list-sources-29]、[list-sources-7]。

**[list-sources-30] 高中：「2016 高考英语词汇上海卷」3,874 单词中只有 75% 在线上库 gk 层、76% 在 zk∪gk；948 词超出全国高中层，其中 780 词在库但属 cet4/cet6 层（如 assign, breed, cable, chop, detail, device, discipline, exhibit, justify, resistant, shortage, volume），168 词不在库（多为复数/屈折形与合成词：ducks, gentlemen, thieves, scarfs, tornadoes, high-rise, hitech, storekeeper, storyteller, one-sided）。全国 `Highschool_edited` 与 `GaoKao_3500` 互含 94%/88%。** 事实，置信度高。

| A \ B | 10d沪高考2016 | 04Highschool | 09GaoKao3500 | DB.gk | DB.zk∪gk | DB.all |
|---|---|---|---|---|---|---|
| 10d 沪高考 2016 (3,874) | 100% | 73% | 72% | 75% | 76% | 96% |
| 04 Highschool (3,446) | 82% | 100% | 94% | 100% | 100% | 100% |
| 09 GaoKao3500 (3,693) | 75% | 88% | 100% | 98% | 99% | 99% |

**[list-sources-31] 推断（中置信）：上海 vs 全国的差异是真实且双向的——初中层 556/585 词互不包含（[7]），高中层上海表多出 948 词；因此「按省份/地区分层」不能只靠在全国表上加标签，至少上海需要独立的 zk/gk 词集。** 依据 [7][29][30] 的计数。

---

## 四、汇总表与判断

| 来源 | 格式 | 学段/地区 | 词数（去重） | 释义/音标 | 许可 | 最近更新 | 与线上库重合（单词） | 判断 |
|---|---|---|---|---|---|---|---|---|
| ECDICT 1.0.28 | csv / sqlite | 词典底座；tag 仅 zk/gk/cet4/cet6/ky/toefl/ielts/gre | 770,611（csv 基础版） | 是 | MIT | 2024-12-31 release 更新；push 2026-11-02 | — | **推荐继续采用**（释义/音标/词频/变形），不能提供小学分级 |
| mahavivo 上海初中 2020 PDF（02） | PDF → 文本 | 上海初中/中考 | 1,722 词 + 309 词组 | 是（词性+中文，无音标） | 无声明；官方考试院文件的转载 | 2021-06-08 | 98.3% | **推荐采用**作上海初中词集（自行解析，6 行人工补；需确认是否有更新版本） |
| mahavivo 中考英语词汇表（03） | txt rich | 全国中考（现 zk） | 1,897（147 词组） | 是 | 无声明 | 2021-06-08 | 99.1% | 可用但需清洗（141 条括号词头、私用区字符；来源未注明） |
| mahavivo Highschool_edited（04） | txt plain | 全国高考（现 gk） | 3,448 | 否 | 无声明 | 2019-12-17 | 100% | 可用（现状），来源未注明 |
| mahavivo 小学英语大纲词汇（01） | txt plain | 小学（全国，版本不明） | 440 | 否 | 无声明 | 2021-06-08 | 97.9% | 可用但需确认来源；规模与 2022 课标二级「500 左右」接近 |
| kajweb/dict（有道词书） | JSON（zip） | PEP 小学 3–6、PEP/外研初中、PEP/北师大高中、有道中考/高考 | 81 本 | 是（含例句、测试题） | 无；有道/新东方/出版社权利 | 2024-04-05 | 见 07 | 可用但需清洗；**许可风险高**；无上海 |
| qwerty-learner `public/dicts` | JSON | 同上 + 外研/冀教/北师大/译林/北京/RAZ/KET/PET；上海 2 条 | 373 本 | 是（部分） | GPL-3.0 仓库；数据自 kajweb | push 2026-09-08 | 07: 88.9%；08: 95.3%；09: 98.8% | PEP 小学 3–6 / 中考核心 / 高考 3500 **可用但需清洗 + 许可待定**；上海 05a **不建议**（7% 脏词头，与官方表 47%），05b 可用但仅一册 |
| KyleBing/english-vocabulary | txt/json/jsonl/tsv | 初中/高中/四六级/考研/托福/SAT | 54,356 | 是（含例句） | BSD-3（镜像作者）；上游有道 | 2026-09-30 | 未测 | 不建议（无小学/上海；BSD 不能覆盖上游） |
| DictionaryData | csv（`>` 分隔） | 583 本：小学 149 本、沪教牛津 7A–9B、牛津上海版 7、上海初中基本要求 2008、2016 高考上海卷、沪教三起 | 70,164 词 | 音标两套 + 译文表 | Apache-2.0 声明；来源未说明 | 2025-03-28 | 92–97% | **可用但需清洗 + 权利待定**；上海高中目前唯一可机读词表（4,016）在此 |
| lolo811109-crypto/zhongkao-words | JSON + 图/音 | 上海中考 1,722 | 1,722 | 是（含 IPA、CEFR） | 代码 MIT；内容 CC BY 4.0（AI 生成未审核） | 2026-10-25 | （同 02） | 词表可作核对；插画/例句不建议作权威内容 |
| busiyiworld/maimemo-export | txt/csv | 1,121 本；牛津上海版 1–5、6–9、高一–高三；上海初中考纲；2024 上海高考手册 | 未测 | 释义来自 ECDICT-ultimate | MIT 代码；「禁止商用，词库版权归墨墨」 | （未取得日期） | 未测 | **不建议作数据源；推荐作核验基准**（唯一覆盖上海三学段） |
| djfml OXFORD.apkg（06） | Anki (zstd sqlite) | 上海小学（牛津上海版，版本不明） | 1,040（200 词组/句） | 是（中文+旧式音标） | 无 | 未知 | 91.7% | 不建议直接采用；可作牛津上海版小学覆盖面的粗略对照 |
| pluto0x0/word3500 等 | txt | 全国高考 3500 | ~3,500 | 否 | MIT/Apache-2.0/无 | 2019–2023 | 未测 | 可用但被 09 覆盖 |
| textbook-sentence-index | JSON 倒排索引 | 人教 2019 + 沪教版高中 必修1–4/选修1–4 | >10,000 词键 | 例句 | MIT；「仅供学习研究」 | 2026-09-14 | 未测 | 非词表；可用于沪教高中例句/用词反推 |
| HF SwiftieJerry/english-vocabulary-materials | csv/jsonl/pdf/xlsx | 初中 1,835–1,994、高中 2,434、雅思分级 | 8,257 | 是 | CC BY-NC-ND 4.0 | 2026-08-29 | 未测 | 不建议（禁止商用/演绎） |
| HF `gaokao` 45 个数据集 / Kaggle | — | 试题集 | — | — | — | — | — | 无词表，不适用 |

**[list-sources-32] 判断摘要。** 推断，置信度中（基于上表事实）：
1. **推荐采用**：ECDICT（底座不变）；上海 2020 初中词表 PDF（02）作为上海 zk 词集的权威来源（官方考试院文件，自行解析可复现 1,722 词，与独立解析一致）。
2. **可用但需清洗/许可待定**：DictionaryData 的上海五组（尤其「2016 高考上海卷」4,016 词——目前唯一可机读的上海高中词集，和「上海市初中英语教学基本要求 2008」2,191 词）；qwerty/kajweb 的 PEP 小学 3–6（819）、中考核心（2,135）、高考 3500（3,875）；mahavivo 现用三表。共同清洗项：拆出词组（10–25%）、去掉屈折形式单列（ate/been/children…）、括号/斜杠变体、私用区与法语字母。共同许可问题：均为爬取或来源不明的教材/词书数据。
3. **不建议采用**：qwerty `OxfordVocabulary_juniorMiddleSH.json`（05a）、djfml apkg（06）、KyleBing、HF SwiftieJerry（NC-ND）、word-atlas 的 AI 插画/例句作为权威内容；maimemo-export 只作对照。
4. **小学层的现实**：没有找到任何带开放许可、来源明确的上海（牛津上海版 1A–5B）小学词表；可机读的只有 maimemo（禁商用）与 djfml（无来源）。全国层面可用 PEP 3–6（819）/ 沪教三起（1,008）/ 大纲 440 构造「小学」集合，并集 1,521 词，其中 179 词不在库、210 词在库但现标为 gk/cet 层——意味着新增小学层不仅是加词，还要**下调**一批现有词的 `stage_min`。

---

## 五、未解决的问题

1. 上海市教育考试院《2020年上海市初中英语课程终结性评价指南》的官方下载页未找到；是否有 2021–2025 年新版词表（App 文案的 1,719 与 PDF 的 1,722 不一致）无法确认。
2. 上海高考考纲词汇：官方电子版未找到；「2016 高考英语词汇上海卷」（4,022，人民教育出版社）与「2024 上海市高考英语考纲词汇用法手册」（maimemo 目录）之间的差异未核验。
3. 牛津上海版小学 1A–5B 与高中各册的官方词表不存在可机读开放版本；maimemo-export 的册目可作核验，但其许可禁止商用，且各册词数未验证。
4. `小学英语大纲词汇.txt`（440）与 `中考英语词汇表.txt` 的真实出处未知（README 未说明）；2011 版课标官方 PDF 抓取失败，二级/五级词表规模未对账。
5. DictionaryData 的原始数据来源（哪款 App 的导出）与权利状态不明；Apache-2.0 只是仓库作者的声明。
6. kajweb/qwerty/KyleBing 三者同源有道，是否可在合规前提下用于公开产品需要法律判断；本文件只记录事实。
7. api.github.com 未认证限流导致 `PEP 小学 英语 单词`、`中考 词汇 1600`、`英语 词库 教材 单词表` 三个仓库搜索未执行；可能遗漏小型仓库。
8. 本次未下载 maimemo-export 任何词表文件（下载上限 10 项），其「牛津上海版」各册的词数、格式细节与 06 apkg 的来源关系未核实。
