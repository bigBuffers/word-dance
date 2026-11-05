# 核验：list-sources（可机读词表来源清单与许可审计）

被核验文件：`docs/analysis/2026-11-05-stages-regions-images/facts/list-sources.md`。基线：仓库 `/Users/sqin/word-dance` @ `75df534`（main），线上库只读副本 `scratchpad/live-copy.db`（9,162 行）。日期 2026-11-05；所有网页均为「访问 2026-11-05」。立场：对抗性核验，默认怀疑，所有计数自己重算。

## 范围与方法

**读过的仓库文件**：`scripts/build_seed.py`（`grep -n` 核对 4–11、15–17、20–47、81–87、105–106 行；把 15–17 行的三个正则与 `parse_list` 原样复制进我的脚本重跑）、`backend/wd/migrations/0001_init.sql`（147–148、168、170、175–176、181–186、195 行）、`data/seed/stats.json`、`data/seed/ATTRIBUTION.md`；用 `grep -rn` 在 `backend/wd`、`frontend/src`、`scripts` 全库搜 `"zk"`/`STAGES`/`STAGE_`/`stage_min`/`current_stage`，找作者未提到的硬编码点。

**线上库**：`sqlite3 -readonly live-copy.db`：`count(*)`、四个 `sum(stage_*)`、`stage_min` 分布、`lemma like '% %'`、`kind` 分布、`oxford=1` 计数、以及 7 个被正则丢弃的中考词头的 `stage_zk/stage_min/sources`。

**重算脚本**（全部放在 `scratchpad/verify-list-sources/tools/`，用 `python3 -I` 运行、路径作参数、不在下载目录内执行）：
- `recount.py`：对作者下载的 01–10 全部文件独立重算（01 按行；02 用作者的 `heads.txt`/`phrases.txt`；03/04 用 **生产代码的正则**；05/07/08/09 直接解析 JSON `name`；06 直接读 `collection21.sqlite` 的 `notes.flds`（`mode=ro&immutable=1`）；10a–10e **不用作者的 `lists/*.txt`**，而是从 `book.csv` 按书名选 18 个 `bk_id`，扫 111 MB `relation_book_word.csv` 再回查 `word.csv`）；ECDICT 从 `meta/ecdict/ecdict.csv` 用 `csv.DictReader` 重算 `tag` 全集；归一化 = NFKC → 弯引号/长破折转 ASCII → 小写 → 空白压缩；「词组」= 含空格；「在库」= 与 `words.lemma` 精确匹配。输出 `scratchpad/verify-list-sources/recount_output.txt`。
- `followup.py`：作者 `meta/heads/*.txt` 与我的解析逐项 diff（01、03）、小学并集的四表/五表两种算法、`zk_words_xcheck/index.json` 结构。
- `count_bands.py`、`moe_appendix.py`：对教育部 2022 课标 PDF（扫描件）做逐页文字行带计数 / 文本抽取尝试。

**网络**：`raw.githubusercontent.com` 直连（`curl --noproxy '*'`）重新下载了 ECDICT / mahavivo / kajweb / qwerty-learner / KyleBing / DictionaryData / zhongkao-words / chuyi-words / maimemo-export 的 README 与 ECDICT `releases.atom`（存 `scratchpad/verify-list-sources/dl/`）。`api.github.com` 对本机 IP 已限流（作者耗尽 60/h 配额，返回 "API rate limit exceeded"），因此仓库元数据（license/stars/pushed_at）**只能**用作者缓存的 `meta/repo_*.json` 作为数据核对，并用 WebFetch 打开 github.com 页面做第二来源（mahavivo、DictionaryData、zhongkao-words、maimemo-export、pluto0x0/word3500、djfml、word-atlas、textbook-sentence-index、ECDICT releases、qwerty 与 mahavivo 的 commits 页；`kajweb/dict/tree/master/book` 两次 504）。WebFetch 还访问了 ECDICT wiki「选词」、163.com 文章、App Store id1574077669、Hugging Face 数据集页、gov.cn《著作权法》。WebSearch 只成功执行 4 次（`义务教育英语课程标准 2022 附录 词汇表…`、`上海市初中英语课程终结性评价指南 2020…`、`上海高考英语 考纲词汇…`、`普通高中英语课程标准 2017…`，均无一手命中），随后本会话搜索配额用尽，3 个检索（2011 版课标二级词数、高中课标词汇量、评价指南 ISBN）**未能执行**。

**新下载**（`scratchpad/verify-list-sources/dl/`，各自独立目录）：`moe/notice*.html`（教育部通知页，`--noproxy '*'` 直连成功，经代理返回的是 956 B 反爬桩）；`moe_en/yingyu_2022.pdf`（`http://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220420582349487953.pdf`，31,502,213 B，201 页，Producer `Adobe Acrobat 18.11 Image Conversion Plug-in`，**无文本层**，`pdftotext` 输出 0 字节；本机无 tesseract，只能 `pdftoppm` 渲染后目视 + 行带计数）。

---

## 一、逐条核验

### [list-sources-1] 当前 9,162 词 = ECDICT 四标签 ∪ mahavivo 六表 —— **确认**
- `scripts/build_seed.py:4-6` 为 `Inputs (already downloaded): / - ECDICT stardict.db (MIT, …) / - mahavivo/english-wordlists syllabus lists`；`:10-11` 为 `Stage codes: zk = 初中(中考), gk = 高中(高考), cet4 …` / `Each stage set = ECDICT tag ∪ official syllabus list.`；六个文件名在 `:82-87`（`:81` 是 `syllabus = {`）；四标签查询在 `:105-106`。行号与语义均正确。
- `data/seed/stats.json`：`per_stage {zk 2099, gk 3829, cet4 4722, cet6 7671}`，`syllabus_sizes {zk 1887, gk 3446, cet4 4539, cet6 2220, cet46 8008, cet6star 1721}`；线上库 `select sum(stage_zk),sum(stage_gk),sum(stage_cet4),sum(stage_cet6) from words` → `2099|3829|4722|7671`；`stage_min` 分布 `1:2099 2:1792 3:1577 4:3694`。全部一致。
- 作者的推论「zk 2,099 = ECDICT zk 1,603 ∪ 中考表 1,887」：无 `stardict.db` 可直接验算并集，但我用生产正则重解析中考表得 1,887 个词头、**全部**在库且 `stage_min=1`（见 [7]），与推论相容。置信度高。

### [list-sources-2] ECDICT `tag` 全集 8 个取值、无小学标记 —— **确认**
- 重算 `meta/ecdict/ecdict.csv`：770,611 行（`word` 小写去重也是 770,611），列名与作者一致；`tag` 计数 `gre 7504, toefl 6974, cet6 5407, ielts 5040, ky 4801, cet4 3849, gk 3677, zk 1603`，最常见组合 `gre 3489 / toefl 1490 / toefl gre 1269 / ielts 594 / zk gk 478`——与作者逐字相同。
- 重下的 README 第 40 行：`| tag         | 字符串标签：zk/中考，gk/高考，cet4/四级 等等标签，空格分割 |`。
- Wiki「选词」（https://github.com/skywind3000/ECDICT/wiki/%E9%80%89%E8%AF%8D ，访问 2026-11-05）：「从最初的中高考各类考试大纲开始，到各种语料库和词频库」「中考大纲，高考大纲，四六级大纲，托福雅思GRE大纲，等」；页面未出现「小学」。
- `releases.atom`：`ECDICT - 28` `<updated>2024-12-31T08:04:42Z`，`1.0.27` `2018-05-16`。**口径提醒**：releases 页（访问 2026-11-05）对 1.0.28 只显示「20 Sep」而不显示年份，2024-12-31 是 feed 的 `updated` 时间戳（可能是编辑发布说明），不等于词典数据更新日期；汇总表里「2024-12-31 release 更新」不应被读成「数据是 2024 年的」。

### [list-sources-3] 数据模型只有四个阶段位 —— **确认**
- `0001_init.sql:147` `stages_json … DEFAULT '["cet4","cet6"]'`，`:148` `current_stage … CHECK (current_stage BETWEEN 1 AND 4)`，`:181-185` 四个 `stage_* … CHECK (… IN (0,1))` 与 `stage_min … CHECK (stage_min BETWEEN 1 AND 4)`，`:170` `kind … CHECK (kind IN ('word','phrase','abbreviation','proper_noun'))`，`:168` lemma 归一化注释。行号全部正确。
- `select count(*) from words where lemma like '% %'` = 13；`kind` 分布 `word 9004 / phrase 13 / abbreviation 26 / proper_noun 119`（作者未给，补充口径：9,162「词」里含 158 个非普通单词行）。
- 遗漏的其他硬编码点见「遗漏 2」。

### [list-sources-4] mahavivo 仓库 28 个文件、无 LICENSE、README 未说明中考/小学/上海来源、三文件 2021-06-08 加入 —— **确认**
- 作者缓存 `meta/repo_mahavivo_english-wordlists.json`：`license None, stars 2538, pushed_at 2024-05-11, default master`；`meta/contents_mahavivo.json` 28 个条目、文件名与字节数与作者表逐项一致。github.com 页面（WebFetch）：2.5k stars，未显示 LICENSE。
- 重下 README（10 条）全文无「中考」「小学」「上海」「Highschool」字样；原文第 4 条「托福、GRE词汇表来自我个人保存的资料，源于2003年版金山词霸」属实。
- commits 页（WebFetch）：`小学英语大纲词汇.txt` 仅 1 次提交 2021-06-08 "edit"（SHA 3e20937）；`中考英语词汇表.txt` 同一提交 2021-06-08；`Highschool_edited.txt` 3 次提交 2019-12-15 "edit"、2019-12-17 "init"/"edit"。PDF 的 commits 页未重开（依据作者 API 缓存）。

### [list-sources-5] `小学英语大纲词汇.txt` 440 条、97.7% 在库 —— **确认（数字 ±1）**
- 我的重算：有效行 439（作者 440），全部唯一，2 个词组；在库 429/439 = 97.7%（作者 430/440 = 97.7%）；单词 428/437，`stage_min {1: 422, 2: 6}`（作者「430 词中 424 词 stage_min=1」，差 2）；缺失 9 词 `children, feet, has, men, mr, mrs, ms, pe, women` 与作者完全一致；0 词不在 ECDICT。作者 `meta/heads/01_xiaoxue_dagang.txt` 与我的解析 diff 为空（439 = 439），所以 440 是作者统计口径多算了一行，不影响结论。
- 来源不明：属实（README 无说明）。**但「无法与任何官方数字对账」已不成立**：教育部 2022 课标附录 3「二级词汇表」明确「收录 505 个单词」（见遗漏 1），这就是对账基准；只是该 PDF 为扫描件，需 OCR 才能逐词比对。

### [list-sources-6] 上海 2020 PDF：89 页、1,722 词 + 309 词组、98.3% 在库、与 zhongkao-words 一致 —— **确认**
- `pdfinfo`：Pages 89、Creator `Acrobat PDFMaker 17 Word 版`、Producer `Adobe PDF Library 15.0`、CreationDate 2019-09-30、Title `Medical NOte`，全部一致。`extracted_layout.txt` 2,759 行；第 2,196 行「词组(Phrases and Expressions)」、2,569 行「人称代词、物主代词、反身代词」。
- `heads.txt` 1,723 行 → 1,722 唯一；在库 1,693/1,722 = 98.3%，单词 1,693/1,721，`stage_min {1: 1385, 2: 235, 3: 59, 4: 14}`，缺失 28 词（`angrily, beautifully, bund, café, carefully, dancer, dishonest, embarrassed, excited, frightened, frightening, frozen, hot-dog, lost, luckily, mr, mrs, politely, quietly, satisfied, satisfying, seafood, stuck, surprised, underlined, unforgettable, united, yogurt`），唯一不在 ECDICT 的是 `café`——全部与作者一致。309 词组在库 3 条，一致。
- 交叉核对：`meta/zk_words_xcheck/index.json` 的 `words` 数组 1,722 行（`[id, word, zh, ipa, cefr, topic, media]`，`license: CC BY 4.0`）；用 `word` 字段归一化后与 `heads.txt` 交集 1,710（作者用 id 口径得 1,711），差异仍是变体拆分（`although/though` 等 5 对）与 6 条 `=` 行 + `will`。两套独立解析同为 1,722，结论成立。

### [list-sources-7] `中考英语词汇表.txt`（zk 来源）1,897 条、147 词组、脏词头、与上海表 68% 重合 —— **修正**
- **作者的数字来自自己写的近似解析（`mahavivo_rich` 模式），不是生产代码**。我把 `scripts/build_seed.py:15-17` 的 `RICH_RE`/`POS_RE` 与 `parse_list` 原样复制重跑：得 **1,887** 个词头（= `stats.json.syllabus_sizes.zk`），其中词组只有 **6** 个（`computer game, fruit juice, middle east, olympic games, the pacific ocean, swimming pool`），**1,887/1,887 = 100% 在库且 `stage_min=1`**。
- 作者的「147 个词组」实际上是把 `awake (awoke, awoken)`、`child (复children)`、`bike = bicycle`、`a.m./a.m. n. 午前,上午` 这类带括号/等号的整行当成了词头（`followup.py`：作者 1,896 个词头中 156 个不在生产解析结果里，形如 `begin(began,begun)`；生产解析用 `(?:\s*\([^)]*\))?` 吃掉括号后得到 `begin`）。因此「91.8% 在库、单词 99.1%」「141 条含括号」描述的是**原始文件行**，不是进入词库的词头；按生产口径这些脏点大多已被正则处理。
- 与 02 的重合：`03→02` 1,282/1,881 = 68%（作者 68%，巧合一致），但 `02→03` = 1,282/1,721 = **74%**（作者表 [29] 写 68%）；「沪有全国无」= **439**（作者 556），「全国有沪无」= **599**（作者 585）。
- 新发现（作者未报告）：生产正则**丢弃** 7 行——`best（good, well的最高级）…`、`café …`、`less（little的比较级）…`、`more（much或many的比较级）…`、`practice(s)e …`、`silentˈsailənt] …`、`wolf（复wolves）…`（全角括号/缺左括号/无空格）。查库：`more, practice, silent, wolf` 靠 ECDICT `zk` 标签仍在 zk 层，但 **`best`（stage_zk=0, stage_min=3）与 `less`（stage_zk=0, stage_min=2）不在初中层**，`cafe` 在库但 stage_min=3。这是「检测词库」应修的具体缺陷。
- 作者关于原始文件格式脏（私用区字符、括号变体）的描述本身属实。

### [list-sources-8] `Highschool_edited.txt` 3,448 去重、100% 在库 —— **确认（±1）**
- 原始 3,467 有效行 → 3,447 唯一（作者 3,468/3,448，多算 1）；生产 `PLAIN_RE` 解析 3,446（= `stats.json` 3446），其中 2 个词组；3,446/3,447 在库，唯一缺失/不在 ECDICT 的是 `café`，`sideroad` 不在 ECDICT 但在库——与作者一致。`stage_min {1: 1876, 2: 1568}`（作者 1,877/1,570，差 ±2，口径含词组）。

### [list-sources-9] kajweb/dict 是有道词书镜像、81 本、无上海 —— **确认（「93 zip」无法核验）**
- 重下 README 首行 `# 单词本源` / `Crawl from "X 道背单词(app)"`；第 10 行「部分字典混入了少量法语字母」+ `replaceFran()`。
- `meta/kajweb_bookLists.txt` 解析：81 本；`originName` 分布 人教版教材 24 / 有道词典 20 / 北师大版高中教材 11 / 有道考神团队 9 / 外研社初中教材 6 / 新东方系列 10 本；`PEPXiaoXue3_1…6_2` `wordNum` = 64/72/84/104/131/156/130/108；标题/标签无「上海|牛津|沪教|译林」；`offlinedata` 81 个全在 `ydschool-online.nos.netease.com`。作者缓存 API：license None，pushed 2024-04-05。
- 「`book/` 目录 93 个 zip」：WebFetch 该 tree 页两次 504，**未能复核**（不影响结论）。

### [list-sources-10] qwerty-learner 380 文件 / 373 条索引 / 上海仅两条 —— **确认**
- `meta/contents_qwerty_dicts.json` 380 条；`meta/qwerty_dictionary.ts` 4,200 行，`grep -c "^    id: '"` = 373。`SHjuniormiddleOxford`（`name: '上海初中牛津词汇'`, `category: '青少年英语'`, `tags: ['牛津版']`, `length: 1270`）与 `shanghai-6-2word`（`'上海新教材六年级下'`, `tags: ['上海版']`, `length: 274`）与作者描述一致。
- README 第 304 行「字典数据来自于kajweb…」、第 306 行「语音数据来源于有道词典开放 API」属实；作者缓存 API：GPL-3.0，push 2026-09-08。
- commits 页（WebFetch）：`OxfordVocabulary_juniorMiddleSH.json` 2023-02-10 Yangthemob "feat: add SHjuniormiddleOxford dictionary (#310)"、2023-05-13 (#460 去首尾空格)、2023-09-08 (#640 音标)、2025-12-12 RealKai42 "fix: chinese punctuation"；`shanghai-6-2-word.json` 2025-02-24 RealKai42 "feat: add dict" 737772c。全部与作者一致。

### [list-sources-11] 05a 质量差、1,258 去重、83.1% —— **确认**
重算：1,270 → 1,258 唯一，123 词组，1,135 单词，在库 943/1,258 = 75.0%、单词 943/1,135 = 83.1%，`stage_min {1: 518, 2: 261, 3: 116, 4: 48}`，91 个单词不在 ECDICT（`talkto, canadan, maganize, takenotes, …`），缺失 192；`02→05a` 31%、`05a→02` 47%、`10b→05a` 346/350 = 99%。全部与作者逐字相同。

### [list-sources-12] 05b 274 条、91.6%/96.5% —— **确认**
274 / 14 词组 / 0 不在 ECDICT / 251/274 = 91.6% / 单词 251/260 = 96.5% / 缺失 9 词与作者列表相同。

### [list-sources-13] PEP 3–6：849 → 819、630/709 = 88.9% —— **确认**
8 册各 64/72/84/104/131/156/130/108（与有道 `wordNum` 一致）；849 → 819 唯一、110 词组、709 单词、630 在库 = 88.9%，4 条脏词头 `house., have...class, having...class, wear.`。细节：命中 `stage_min` 为 `{1: 594, 2: 19, 3: 9, 4: 8}`（作者写 595——作者四项之和 631 ≠ 630，应为 594）。

### [list-sources-14] 中考核心词 2,135 去重、95.3% —— **确认**
2,140 → 2,135、4 词组、0 不在 ECDICT、2,034/2,135 = 95.3%、缺失 99，样例一致。

### [list-sources-15] 高考 3500：3,875 去重、98.8%、与 Highschool 88% —— **确认**
3,893 → 3,875、182 词组、3,650/3,693 = 98.8%、10 个词头不在 ECDICT（`department-store, ad., gettogether, … zebra-crossing`）；`04→09` 3,247/3,444 = 94%，`09→04` 3,247/3,693 = 88%。一致。

### [list-sources-16] KyleBing/english-vocabulary —— **确认**
重下 README 表：初中 3,223 / 高中 6,008 / 四级 7,508 / 六级 5,651 / 考研 9,602 / 托福 13,477 / SAT 8,887 = 54,356；第 17 行「乱序是另一套词表，词数不同」；第 115 行 `kajweb/dict → fork → KyleBing/dict → 简化 → 本库`。作者缓存 API：BSD-3-Clause、2,175★、pushed 2026-09-30。

### [list-sources-17] DictionaryData：583 本 / 70,164 词 / 1,044,580 关系 / 小学 149 本 / 上海五组 —— **确认**
- `wc -l`：`book.csv` 584（含表头）、`word.csv` 70,165、`relation_book_word.csv` 1,044,581 → 583 / 70,164 / 1,044,580。25 个顶级分类（`bk_level=1`）；「小学英语」`bk_item_num 15233`，叶子书 149 本；初中 47 本 23,885；高中 71 本 99,952。
- 我按书名独立选书并从关系表重建词表：沪教版牛津英语七上 222（上海教育出版社 2012年7月第1版）、七下 232、八上 232、八下 257、九上 262、九下 195（2015年1月）；牛津上海版七上 207（2008年7月第2版）、七下 214（2009年1月第2版）；上海市初中英语教学基本要求 2,201（上海教育出版社 2008年11月第1版）；2016高考英语词汇上海卷 4,022（人民教育出版社 2015年10月第1版）；沪教版三年级起点 3上–6下 75/114/139/151/164/165/135/137。18 本关系行数 = `bk_item_num`，`vc_id` 未解析 0。全部与作者一致。
- github.com 页面：666★、Apache-2.0、根目录 `LICENSE, README.md, book.csv, relation_book_word.zip, word.csv, word_translation.csv`，README 无任何数据来源说明——属实。
- 补充口径问题见「遗漏 5」（「沪教版牛津英语 7A–9B」很可能不是上海本地教材）。

### [list-sources-18] 上海五组实测表 —— **确认（±1）**
| 组 | 作者 | 我的重算（独立抽取） |
|---|---|---|
| 10a | 1,400→1,362；341 词组；985/1,021 = 96.5%；1:754 2:164 3:47 4:21 | 1,400→1,362；341；985/1,021 = 96.5%；1:754 2:164 3:47 4:20（+1 词组命中） |
| 10b | 421→421；71；324/350 = 92.6%；1:193 2:71 3:41 4:19 | 完全相同 |
| 10c | 2,201→2,191；365；1,681/1,826 = 92.1%；1:1409 2:205 3:53 4:17 | 2,201→2,191；365；1,681/1,826 = 92.1%；1:1409 2:204 3:53 4:15（差额为词组命中） |
| 10d | 4,021→4,016；142；3,706/3,874 = 95.7%；1:1797 2:1129 3:628 4:153 | 4,022→4,017；142；3,707/3,875 = 95.7%；1:1798 2:1129 3:628 4:152 |
| 10e | 1,080→1,008；203；768/805 = 95.4%；1:715 2:30 3:19 4:6 | 1,080→1,008；203；768/805 = 95.4%；1:713 2:30 3:19 4:6 |
不在 ECDICT 的仅 10d 的 `hitech, résumé`，其余 0——一致。缺失样例一致。

### [list-sources-19] lolo811109-crypto/zhongkao-words —— **确认**
重下 README 第 3–7 行原文与作者引文逐字一致（「词表与中文释义：上海市教育考试院《2020年上海市初中英语课程终结性评价指南》词汇表（单词部分；词组部分未收录），PDF 取自 mahavivo/english-wordlists，由脚本解析。」）。github.com 页：2★、1 commit、MIT。`index.json`：`count 1722`、`license CC BY 4.0`、`fields [id, word, zh, ipa, cefr, topic, media]`。上游 word-atlas（WebFetch）：7,298 词条 / 14,596 例句 / 7,298 张 512px WebP / 22,905 段音频，「文字与插画使用生成式 AI，语音使用 ElevenLabs」「尚未逐条人工审校」，代码 MIT、内容 CC BY 4.0——一致。

### [list-sources-20] chuyi-words —— **确认**
重下 README 第 5 行与作者引文逐字一致（含「非出版社官方数据」）。

### [list-sources-21] maimemo-export 词库目录唯一覆盖上海三学段、禁止商用 —— **确认**
`meta/maimemo_ciku.md` 表格 1,123 行（含表头+分隔 = 1,121 本）；关键词计数 上海 26 / 沪教 16 / 牛津上海版 24 / 小学 10 / 初中 46 / 高中 111 / 中考 8 / 高考 35，与作者完全相同；「牛津上海版」24 条 = 一年级上…五年级下 10 + 六年级上…九年级下 8 + 高一上…高三下 6（第 878–901 行）。重下 README：第 52 行「仅用于学习，禁止用于商业用途。词库版权归 墨墨背单词 所有」，第 5 行「中文翻译并非导出自墨墨背单词，而是使用 ECDICT(-ultimate) 的数据」。github.com 页：1.0k★、35 commits、MIT；最近更新日期仍未取得。

### [list-sources-22] djfml OXFORD.apkg 1,042 卡、91.7%、无许可无来源 —— **修正（一处数字）**
- 结构数字确认：`notes` 1,042 = `cards` 1,042，牌组表为 `['Default', 'OXFORD']`（`Default` 是 Anki 内置空牌组，作者「单一牌组 OXFORD」可接受）；1,040 唯一、200 词组/句、840 单词、770/840 = 91.7%、18 个不在 ECDICT（`tcow, noodle(s), sock(s), …, go→goes`）；github.com 页：无 LICENSE、README 仅一句「上海版牛津小学英语全部单词带音标 anki deck文件 自行导入使用」、0★。
- **错误**：「与其他小学表重合：含 01 大纲表的 83%」——实际 `|06∩01|/|01|` = 316/437 = **72%**；83% 是 `01→10e`（363/437）的数字。作者自己的表 [28] 第一行也写的是 06 列 72%、10e 列 83%，正文与表格互相矛盾。「与 PEP 3–6 互含 49%/58%、与沪教三起 57%/59%」正确。

### [list-sources-23] 高考 3500 类仓库 —— **确认（部分）**
pluto0x0/word3500（WebFetch）：43★、MIT、19 commits、根目录含 `3500.txt` 与 PHP 文件、「高考英语词汇3500」PHP+MySQL 应用——与作者一致；LazuliKao、WhaleFell 两个仓库未复核（低影响）。

### [list-sources-24] textbook-sentence-index —— **确认**
WebFetch：人教版 2019 与沪教版 高中必修 1–4 / 选择性必修 1–4，`textbook_index_data.zip` 28.58 MB，MIT，「数据来源于公开出版教材，仅供学习研究使用」，>10,000 词。一致。

### [list-sources-25] Hugging Face / Kaggle —— **确认（HF 部分）**
HF 数据集页（访问 2026-11-05）：CC BY-NC-ND 4.0（「禁止商业使用、再分发、公开镜像与演绎」）、85 个文件 442.74 MB、8,257 条、初中 1,835/1,994、高中 2,434、来源「绿新的教研资料」、v1.0.0 2026-08-29——一致。`search=gaokao` 45 个与 Kaggle 两次检索未重跑。

### [list-sources-26] 2022 课标：二级 500 左右、三级约 1600、可另接触 100–300 —— **确认，并升级为一手来源**
- 163.com 文章（访问 2026-11-05，2022-06-29，作者「小伦敦」，注明源自中国日报双语新闻）确实含作者引用的两句原文。
- 一手核实：教育部通知页 `http://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html`（`publishdate 2022-04-21`，直连成功）附件「义务教育英语课程标准（2022年版）」= `W020220420582349487953.pdf`。渲染第 94 页（印刷页 87）「附录 3 词汇表 / 二级词汇表 / 说明 1. …本词汇表收录 505 个单词，为小学阶段英语课程应学习和掌握的基本词汇。各地可根据实际情况在本词汇表的基础上，选择增加 100～300 个单词（主要为三级词汇及少量相关主题范围内词汇）。」；第 105 页（印刷页 98）「三级词汇表 / 说明 1. …本词汇表共收录 1600 个单词，含二级词汇 505 个（用"*"标出），确定 1095 个单词为初中阶段英语课程应学习和掌握的基本词汇。各地可根据实际情况在本词汇表的基础上，选择增加 100～300 个单词。」说明 2–10：英式拼写、不标词性释义、数词/月份/星期单列、不规则动词表单列（印刷页 133）、不列词组短语、不列可构词法推导的派生词。
- 行带计数交叉验证（`count_bands.py`，72 dpi 灰度，两栏，去页眉页脚）：二级表所在第 94–104 页共 566 行带（含 26 个字母标题与说明行）≈ 505 词；三级表第 105–139 页共 1,841 行带（含字母标题、专有名词/机构缩写/节日表）≈ 1,600 + 附表。与说明数字量级相符。
- 作者把本条标为「中置信（二手）」是对的；现在可升到高置信，且数字口径从「约」变成精确的 **505 / 1600（含 505）/ 1095**。

### [list-sources-27] 上海官方词表电子版未找到；App 文案 1719 —— **确认（App 数字）**
App Store（https://apps.apple.com/cn/app/id1574077669 ，访问 2026-11-05）：应用「上海中考英语词汇 听说测试 AI批改英语作文」，开发者「建政 朱」，描述原文「本应用涵盖1719个上海中考英语考纲词汇。」，版本 3.2（2023-11-22）。「官方站点未找到」部分因搜索配额用尽无法独立复核。

### [list-sources-28] 小学候选表交叉表 / 「四表并集 1,521」 —— **修正**
- 表格本身确认：01 行 `07 73% / 10e 83% / 06 72% / 05b 0% / DB.zk 97% / DB.all 98%`，`06↔07` 49%/58%，`06↔10e` 57%/59% 均与我的重算一致。
- **标题数字错**：「四表（01、07、10e、06）单词并集 1,521，179 不在库、210 在库但 stage_min>1」——四表并集实际为 **1,365 词、170 不在库、160 在库但 stage_min>1**；作者的 1,521/179/210 是**五表**（再并入 05b 上海六年级下 260 词）的结果（我算得 1,520/179/210）。[32]-4 同样沿用了这组数字。

### [list-sources-29] 初中交叉表 / 七表并集 3,425、451 不在库、917 层级偏高 —— **修正（一处）**
- 3,425 与 917 重算一致；`02→10c` 88%、`10c→02` 83%、`02→08` 83%、`02→DB.zk` 80%、`02→DB.all` 98% 一致。
- 「451 词不在库」应为 **437**：多出的 14 个是作者近似解析得到的脏词头（`a (an)`、`awake (awoke, awoken)` 之类），按生产正则它们不存在。涉及 03 列的百分比也随之变动（`02→03` 74% 而非 68%；其它行的 03 列差 1–3 个百分点）。

### [list-sources-30] 高中：上海 2016 表 75%/76%、948 超出、780/168、94%/88% —— **确认**
重算：`10d→DB.gk` 2,904/3,875 = 75%，`→zk∪gk` 2,927/3,875 = 76%，超出 948，其中在库 780、不在库 168；`04→09` 94%、`09→04` 88%；`10d→04` 2,809/3,875 = 72%（作者 73%，四舍五入边界）。一致。

### [list-sources-31] 上海 vs 全国差异真实且双向（推断） —— **确认（结论成立，数字需改）**
依据生产口径：初中层「沪有全国无 439 / 全国有沪无 599」（非 556/585），高中层多出 948 不变；「至少上海需要独立的 zk/gk 词集」的推断仍然成立。

### [list-sources-32] 判断摘要 —— **修正（两处）**
1. 「推荐采用 02 作上海 zk 词集的权威来源」成立，但应限定**只取词头**：02 的中文释义/词性标注与选排可能受《著作权法》第十五条汇编作品保护，而「词头清单」接近单纯事实（见遗漏 4）。
2. 「mahavivo 现用三表可用」：需补一句——生产正则对 `中考英语词汇表.txt` 丢弃 7 行，导致 `best`、`less` 不在初中层（见 [7]）。
3. 第 4 点「并集 1,521 / 179 / 210」是五表并集（见 [28]）。
其余判断（ECDICT 底座、DictionaryData 需清洗+权利待定、05a/06/KyleBing/HF 不建议、maimemo 只作对照）与证据相符。

---

## 二、联网类附加核查（一手性 / 年份 / 口径）

- **一手 vs 二手**：作者对 2022 课标只用了 163.com 转载（二手）；教育部官网有可直连的一手 PDF（扫描件）。对上海 2020 词表只有 mahavivo 转载的 PDF（Word 转出、2019-09-30 生成），考试院原始发布页仍未找到（本次因搜索配额用尽也未能再找）。mahavivo 的中考/小学/高考三表来源仍不明。
- **年份**：ECDICT 1.0.28 的发布年份页面不显示（见 [2]）；2016 高考上海卷（人教社 2015-10）与 2008 教学基本要求都早于上海 2017 新高考 / 2022 新中考，作者在「未解决」里已列，属实。
- **口径**：作者在 [7] 把带括号的屈折说明当成「词组」（147），与真实词组（6）混淆；[1]/[3] 的「9,162 词」含 13 词组、26 缩写、119 专有名词；[28] 把五表并集写成四表。其他条目的 词/词条/词组 区分是清楚的。

---

## 三、作者遗漏的重要事实

**遗漏 1（会改变决策方向）：教育部 2022 课标附录 3 词汇表是现成的官方「小学」与「初中」定义，且可直连下载。** 事实，置信度高。
- `http://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220420582349487953.pdf`（访问 2026-11-05，31,502,213 B，201 页，扫描件无文本层）。印刷页 87「二级词汇表…收录 505 个单词，为小学阶段英语课程应学习和掌握的基本词汇」；印刷页 98「三级词汇表…共收录 1600 个单词，含二级词汇 505 个（用"*"标出），确定 1095 个单词为初中阶段…基本词汇」；两表都允许「各地…选择增加 100～300 个单词」。二级表在 PDF 第 94–104 页，三级表第 105–138 页，不规则动词表第 140 页。
- 含义：(a)「小学」层有官方清单（505 词），mahavivo 440 词表不再是唯一候选，只需 OCR 这 11 页即可拿到权威词头（词头清单无词性释义，许可风险最低）；(b) 三级表是**累计** 1,600（含二级 505），而线上 zk 层 2,099、mahavivo 中考表 1,887 都明显大于现行课标，说明现 zk 来源是旧考纲口径；(c) 上海 2020 表 1,722 ≈ 1,600 + 不超过 300 的地方增补，与课标「各地可增加」条款一致，解释了 [31] 的差异来源。
- 待办：本机无 tesseract，未能逐词抽取；若 OCR，还需按说明 4/5 处理 `child (pl. children)`、`be (am, is, are)`、`PE (=physical education)` 与单列的数词/月份/星期/专有名词。

**遗漏 2：阶段集合在代码里至少还有 20 处硬编码，不止 `0001_init.sql`。** 事实，置信度高（`grep -rn`，基线 75df534）。
- 后端：`backend/wd/schemas.py:25` `Stage = Literal["zk", "gk", "cet4", "cet6"]`、`:51` `STAGE_ORDER`、`:52` `STAGE_NAMES_ZH = {"zk": "初中", …}`、`:488` `stage: Literal["all","zk","gk","cet4","cet6"]`、`:708`、`:1335`；`backend/wd/seed.py:43` `STAGES`；`backend/wd/services/words.py:39` `STAGES`；`backend/wd/services/ecdict.py:28` `STAGE_TAGS`（`:177` 用其下标算 `stage_min`）；`backend/wd/ai/prewarm.py:32-33` `STAGE_COLUMNS`/`STAGES`；`backend/wd/ai/content.py:49` `STAGE_ZH`（送给 AI 的提示里只有四个阶段名）；`0001_init.sql:195` `difficulty INTEGER CHECK (difficulty BETWEEN 1 AND 5), -- 1 初中 … 4 六级, 5 beyond`（难度刻度同样没有小学位）。
- 前端：`frontend/src/api/types.ts:5` `export type Stage = 'zk' | 'gk' | 'cet4' | 'cet6'`、`:45`、`:52`；`frontend/src/components/word/StageChips.tsx:7-9` `STAGE_ORDER/STAGE_INDEX/STAGE_BY_INDEX`；`frontend/src/pages/WelcomePage.tsx:30-37` 角色只有 `zk | gk | uni | pro`（`roles: { zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }`，`frontend/src/i18n/zh.ts:25`）——**没有「小学生」入口**；`VocabPage.tsx:29` `TABS`、`AdminPage.tsx:36` `PREWARM_STAGES`、`ScreenPage.tsx:20`、`i18n/zh.ts:28`。
- 含义：「增加小学词库」是一次跨 schema/后端/前端/AI 提示的枚举扩展，而不是加一列；作者 [3] 只讨论了 SQL 约束。

**遗漏 3：现有 zk 来源文件有 7 行被生产正则丢弃，造成 `best`、`less` 不在初中层。** 事实，置信度高。
- `scripts/build_seed.py:16` `RICH_RE` 要求 ASCII 词头后跟 `(`/`[`/`/`/空白；`中考英语词汇表.txt` 中 `best（good, well的最高级）[best] …`、`less（little的比较级） [les] …`、`more（much或many的比较级）…`、`wolf（复wolves）…` 用全角括号，`practice(s)e`、`silentˈsailənt]`、`café` 另有拼写/缺括号问题，`re.match` 失败（`followup.py` 列出全部 7 行）。
- 线上库：`select lemma, stage_zk, stage_min, sources from words where lemma in (...)` → `best|0|3|cet4 cet46 ecdict`、`less|0|2|cet4 cet46 ecdict`、`cafe|0|3|…`、`more|1|1|… gk`、`practice|1|1`、`silent|1|1`、`wolf|1|1`（后四个靠 ECDICT `zk` 标签补上）。`stats.json.missing_from_ecdict` 只记录了 `cet46: ["instalation"]`，因为被正则丢弃的行根本没进入 missing 统计。

**遗漏 4：许可分析缺少「词头 vs 释义」的法律区分。** 事实（法条）+ 推断（适用），置信度中。
- 《中华人民共和国著作权法》（2020 修正，https://www.gov.cn/guoqing/2021-10/29/content_5647633.htm ，访问 2026-11-05）第五条：「本法不适用于：（一）法律、法规，国家机关的决议、决定、命令和其他具有立法、行政、司法性质的文件，及其官方正式译文；（二）单纯事实消息；（三）历法、通用数表、通用表格和公式。」第十五条：「汇编若干作品、作品的片段或者不构成作品的数据或者其他材料，对其内容的选择或者编排体现独创性的作品，为汇编作品，其著作权由汇编人享有…」
- 推断：上海市教育考试院的《评价指南》是事业单位编制并出版发行的考试文件，不一定落入第五条「国家机关…具有行政性质的文件」；其词汇表的**词头集合**接近不受保护的事实/数据，但**中文释义、词性标注与选排**可能构成汇编作品。作者 [32] 推荐「采用 02」时把它当成无风险官方文件，应限定为只取词头（与 `ATTRIBUTION.md` 对 mahavivo 的做法一致）。对 DictionaryData/kajweb/qwerty 的中文释义同理。

**遗漏 5：「沪教版牛津英语 7A–9B」（10a）很可能不是上海本地（5-4 学制）使用的教材，作者只对 10e 做了这个提醒。** 推断，置信度中。
- 数据证据：DictionaryData 中「牛津上海版七年级上/下」（10b，2008/2009 第 2 版）与「沪教版牛津英语七年级上…九年级下」（10a，2012–2015 第 1 版）是两套不同的书：`10b→10a` 42%、`10a→10b` 14%（作者表 [29]）；qwerty「上海初中牛津词汇」05a 包含 10b 的 99%，却只包含 10a 的 42%。上海本地初中用 6A–9B（预备班起，`shanghai-6-2-word.json` 即「六年级下」），而 10a 从 7A 起，符合 6-3 学制外省版。
- 含义：汇总表把「沪教牛津 7A–9B」列为上海材料会误导选型；上海本地教材词表应以 牛津上海版 6A–9B（maimemo 目录有）为准。此点未找到出版社一手页面证实（搜索配额用尽），建议下一步核对上海教育出版社书目。

**遗漏 6：ECDICT 的 `oxford`（Oxford 3000）标记已在库，是唯一许可干净的「基础词」客观信号。** 事实，置信度高。
- `0001_init.sql:176` `oxford INTEGER, -- 0/1 (Oxford 3000)`；线上库 `select count(*) from words where oxford=1` = 3,103，按 `stage_min` 分布 `1:1636 2:858 3:497 4:112`。作者 [2]/汇总表只写「ECDICT 不能提供小学分级」，没有提到这个可用于排序/初筛小学层的字段（与 505 词官方表对账后可作补充）。

**遗漏 7（口径）**：[1]/[3] 的「9,162 词」含 `kind` 为 `phrase 13 / abbreviation 26 / proper_noun 119` 的 158 行；[7] 把 141 个带括号的屈折说明当作词组；[28] 四表/五表混写。已在各条说明。

---

## 四、未解决的问题

1. 2022 课标二级 505 词 / 三级 1,600 词的逐词清单仍需 OCR（扫描件），本机无 tesseract；与 mahavivo 440、PEP 819、上海 1,722 的逐词对账未做。
2. 上海市教育考试院《评价指南》原始发布页、是否有 2021–2025 新版、以及 2017 新高考后的上海高考词汇表官方电子版：本次搜索配额用尽，未能再核。
3. 「沪教版牛津英语 7A–9B」是否为外省（6-3）版本：仅有数据侧推断，缺出版社一手书目。
4. `kajweb/dict/book` 的 zip 数量（作者称 93）与 mahavivo PDF 的提交记录：github.com 页面 504 / 未重开，沿用作者 API 缓存。
5. ECDICT 1.0.28 的实际发布年份：页面只显示「20 Sep」。

---

**汇总：核验 32 条：确认 27、修正 5（[7]、[22]、[28]、[29]、[32]）、推翻 0、无法核验 0（[9]「93 zip」、[23] 两个小仓库、[25] Kaggle、[27]「官方站点未找到」四个子项未能复核，均不影响主结论）。**
