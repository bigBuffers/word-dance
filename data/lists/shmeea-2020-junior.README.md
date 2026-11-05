# shmeea-2020-junior —— 上海市教育考试院《2020 年上海市初中英语课程终结性评价指南·词汇表》词表文件说明

生成日期 2026-11-05；2026-11-06 按核验报告 `docs/analysis/2026-11-05-stages-regions-images/lists-verify/shmeea-2020.md` 修正，改动清单见 §9。本文件说明同目录下五个 `shmeea-2020-junior*` 文件的来源、页码范围、解析与规范化规则、计数、与此前三次解析的差异裁决，以及仍不确定的条目。路径写法：仓库内文件用相对路径；scratchpad 指 `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/`。

## 1. 来源

| 项目 | 内容 | 依据 |
|---|---|---|
| 文件 | `07.pdf`「2020年上海市初中英语课程终结性评价指南词汇表」，89 页，1,200,683 字节，Word（Acrobat PDFMaker 17）转出，有文字层 | `pdfinfo`；verify/provinces.md [provinces-12] 修正 1 |
| 发布 | 上海市教育考试院 2019-09-26 发布页 `https://www.shmeea.edu.cn/page/08000/20190926/13309.html`，附件 href 原文 `http://www.shmeea.edu.cn/download/20190926/07.pdf`（下载时 302 到 https） | verify/provinces.md [provinces-12] 修正 1、「遗漏」第 1 条；`scratchpad/verify-provinces/dl-shmeea/index.html` 中的 `href`（只 grep，未执行） |
| 本地副本 | `scratchpad/verify-provinces/dl-shmeea/07.pdf`，`md5 -q` = `059df9c02684bd989fff6f8849ee1993` | 本次 `md5 -q` |
| 同一文件的其他副本 | `scratchpad/list-sources/02/上海市初中英语词汇表（2020年版）.pdf`（mahavivo 转载）、`scratchpad/shanghai-secondary/02-mahavivo-sh2020pdf/sh_junior_2020.pdf`：md5 均为 `059df9c0…1993` | 本次 `md5 -q`；facts/list-sources.md [list-sources-6] |
| 元数据 | Title「Medical NOte」、Author「Intergen Administrator」是 Word 模板残留，不是署名 | verify/provinces.md [provinces-12] 修正 1 |

## 2. 产出文件

| 文件 | 内容 | 行数（不含 `#` 注释） |
|---|---|---|
| `shmeea-2020-junior.txt` | 单词表词头，每行一条，与 PDF 词条一一对应，并列保留原貌 | 1,724 |
| `shmeea-2020-junior-phrases.txt` | 词组(Phrases and Expressions)，每行一条 | 342 |
| `shmeea-2020-junior-appendix.tsv` | 附表：代词、基数词/序数词、星期/月份、国家与国籍、常用学科；列 `word / section / note` | 158 |
| `shmeea-2020-junior-forms.tsv` | 单词正文括号里的词形信息（不规则动词变化、复数、比较级、英美拼写、变体/全称），原文照录；列 `headword / kind / printed / where` | 146 |
| `shmeea-2020-junior.README.md` | 本文件 | — |

全部 UTF-8、LF、无 BOM；文件开头的 `#` 注释含来源 URL、本地路径与 md5、获取日期、规则摘要、计数。

## 3. PDF 结构与页码

`pdftotext -layout` 输出 2,759 行、89 个换页符 `\f`（每页第一行以 `\f` 开头），与此前 `scratchpad/verify-provinces/dl-shmeea/07.txt` 逐字节相同（`cmp`）。PDF 第 1 页是标题页，印刷页码 = PDF 页码 − 1。

| PDF 页 | 印刷页 | 内容 | layout 文本行 |
|---|---|---|---|
| 1 | — | 标题「英语词汇表」 | 1–2 |
| 2–72 | 1–71 | 「单词(Vocabulary)」A–Z 正文（无 X 组） | 3–2195 |
| 73–84 | 72–83 | 「词组(Phrases and Expressions)」 | 2196–2568 |
| 85 | 84 | 人称代词、物主代词、反身代词 | 2569–2601 |
| 86–87 | 85–86 | 基数词和序数词 | 2602–2686 |
| 88 | 87 | 月份和星期；国家、大洲及其对应的人（上） | 2687–2718 |
| 89 | 88 | 国家（续表）；常用学科 | 2719–2759 |

正文是单栏：`词头  词性.  释义`；同一词头的其他词性另起缩进行；释义过长时折行也缩进；页码居中、字母组标题居中（均缩进）。

## 4. 解析与规范化规则

脚本（本次新写，`python3 -I` 运行，只读 PDF/文本，放在 `scratchpad/lists-shmeea/`）：`parse.py`（解析 → `out/words.txt`、`out/phrases.txt`、`out/appendix.tsv`、`out/forms.tsv`、`out/pages.tsv`、`out/entries.tsv`、`out/special.tsv`、`out/diag.txt`）、`emit.py`（加注释头写入 `data/lists/`）、`compare.py`（与此前三次解析对照；带第 7 个参数 layout 文件时另输出词组差异的成因分解）、`check.py`（2026-11-06 新增：对发布文件复查计数、重复、字母序断点、TSV 列数、`-forms.tsv` 与单词表的一致性，输出 `check-run.log`）。页面图像在 `scratchpad/lists-shmeea/img/p-NN.png`（`pdftoppm -r 110 -png`）；核验修正时另以 220 dpi 渲染第 10、19、41 页到 `scratchpad/lists-shmeea/img220/p-NN.png`。

### 4.1 单词表

1. 范围：从「单词(Vocabulary)」行（layout 第 3 行）之后到「词组(Phrases and Expressions)」行（第 2196 行）之前。
2. 行分类：先去掉行首 `\f`，再看首字符——顶格 = 词头行；缩进 = 续行（词性续行如 `prep. 关于`、释义折行如 `being, been)`、页码、字母组标题）。这一步就是此前 provinces 解析漏掉每页首词的原因（INDEX §3 第 1 条）：单词区 71 页中 57 页的首行是 `\f`+词头，12 页（PDF 4、14、21、23、27、36、39、43、47、61、63、70）的首行是 `\f`+续行，1 页（PDF 52）首行是字母组标题 R，1 页（PDF 2）首行是节标题。
3. 词头 = 词头行从行首到第一个词性标记（`n. v. vt. vi. adj. adv. prep. conj. pron. art. num. int. aux. modal. link &`）或第一个中文字符之前的文本；`P.E. 体育`、`A.M. (a.m.) 上午` 无词性，到中文为止。
4. 括号处理（词头零件里的括号）：
   - 保留——标示词形变体的括号：`A.M. (a.m.)`、`P.M. (p.m.)`、`e-mail (email)`、`manner(s)`、`toward(s)`、`television (TV)`、`phone (=telephone)`、`photo (=photograph)`、`popular (=pop)`、`bund (the Bund)`；
   - 去掉——不规则变化 `bite (bit, bitten)`→`bite`（`-forms.tsv` 中 `irregular-forms` 94 行＝93 个动词，`hang` 两套变化各一行；`burn (burned, burned 或 burnt, burnt)`、`dream (dreamt, dreamt 或 dreamed, dreamed)` 的括号以「或」分隔两套变化，也在其内）、复数 `child (复 children)`→`child`、比较级 `bad (比较级 worse，最高级 worst)`→`bad`、英美拼写 `centre (美 center)`→`centre`、中文说明 `more(much 或 many 的比较级)`→`more`、情态词过去式 `may (might)`→`may`、`shall (should)`→`shall`、`can (could) can’t = can not`→`can`、`ought (to)`→`ought`、跨行未闭合的 `be v. 是；成为(原形，……`→`be`。去掉的内容进 `-forms.tsv`，仅两处例外：`ought (to)` 的用法说明与 `can’t = can not` 的缩约形式只记录在 `out/special.tsv`（layout 第 1355、289 行的记录），不进任何发布文件。
5. 并列不拆：`/` 并列 5 条（although/though, anybody/anyone, bicycle/bike, everybody/everyone, somebody/someone）、`=` 并列 3 条（exam=examination, grandma=grandmother, grandpa=grandfather）各保留为一行，由种子构建阶段决定拆分规则。
6. 保留原文大小写、句点、连字符、重音：`Christmas, Internet, London, Miss, Mr, Mrs, Olympic, Pacific, Paris, P.E., A.M. (a.m.), P.M. (p.m.), café, hot-dog, ice-cream`。`Mr`/`Mrs` 原文无句点。
7. 唯一的字符规范化：弯引号 `’`(U+2019) → `'`，只影响 `o'clock`。
8. 不去重：`miss v.`（layout 第 1202 行）与 `Miss n.`（第 1203 行）是两条词条，保留两行。

### 4.2 词组表

1. 范围：layout 第 2197–2567 行；顶格行 = 一条词组（12 个缩进行全是页码）。
2. 词组 = 行首到第一个中文字符或省略号「……」之前的文本（`be late for  ……迟到` 的释义以「……」开头，据此截到 `be late for`；图像 PDF 第 74 页核对）。
3. 释义以中文括号开头时会留下悬空的 `(`（如 `dress up (穿着)打扮`），去掉；共 9 条：dress up, far away (from), keep in touch (with), lay the table, leave (secondary) school, not...at all, prefer...to, so that, turn down/up。
4. 保留英文括号与 `/` 并列（`a bit (of)`, `less/more than`, `no longer/not...any longer`, `would like/love (to)`）；括号内外多余空格规范为 `(of)`、`at/in`、`(in/on/at)`；`’` → `'`（one's, what's，共 14 条）。

### 4.3 附表

- 代词三张表（PDF 第 85 页）、数词两页（第 86–87 页）按原文转录为列表，并逐词在抽取文本中回查、与页面图像核对（数词的 `st/nd/rd/th` 上标在文本里单独成行、两格折行，正则不可靠，所以采用转录）。每个词形在同一节内只列一次（`yours` 单复数两格合为一条；`his`/`its`/`her` 在不同节各出现一次）。
- 月份/星期、国家与国籍、学科按行正则抽取并与图像核对：国家/大洲 13（America〔注 U.S.A.〕, Australia, Britain〔注 U.K.〕, Canada, China, England, France, Germany, Italy, Japan, Asia, Africa, Europe），国籍/洲人 14（含 British 与 Briton），学科 6（Chinese, English, Math(s), Biology, Physics, Chemistry）。

### 4.4 词形信息（`-forms.tsv`）

取单词正文每条词条（词头行 + 词性续行）上、位于释义之前或紧跟词性标记的括号，按内容归类：`irregular-forms` 94、`plural` 12、`comparison` 11、`us-spelling` 12、`uk-spelling` 1（`practice v. (英 practise)`）、`past-form` 5、`full-form` 4、`alt-form` 7；`be` 的变化形式写在释义里，按原文补一行（`where = gloss`）。`hang` 有两行（`hanged, hanged` / `hung, hung`）。`burn`、`dream` 的括号以「或」分隔两套变化（`burned, burned 或 burnt, burnt`、`dreamt, dreamt 或 dreamed, dreamed`），照录为一行各一条（2026-11-06 补收，见 §9）。`much (more, most)` 的括号是比较级/最高级而非动词变化，标 `comparison`，与同页 `more`、`most` 及 `many` 条目同类（2026-11-06 改标）。`maths (=mathematics，美 math)` 的括号兼含全称 `=mathematics` 与美式拼写 `math`，只标 `full-form`，其美式拼写未计入 `us-spelling` 12。释义内的 `(=human being)`、`(复)`（无形式）、`(should/would like)` 之类不收。`underground n. (美 subway)` 归入 `us-spelling`，实为美式对应词，标签只是近似。

## 5. 核验

- **全页图像核对**：89 页全部以 110 dpi 渲染并逐页阅读；对单词区 71 页和词组区 12 页逐页比对 `out/pages.tsv` 的首词头/末词头与页首是否为续行，全部一致；附表 5 页逐项核对。重点确认：`be` 的括号跨行（PDF 第 7 页）；`hang (hanged, hanged)` 为词头行、`(hung, hung)` 为同一词条的续行（第 29 页）；`far` 的 `adj.远的`/`adv.远地` 为续行（第 24 页）；`well` 释义折行跨到下一页首行（第 69→70 页）；`miss`/`Miss` 两条（第 40 页）；`stick` 与 `stuck` 各为词头（第 61–62 页）；第 2 页首词为 `ability`，正文确无 `a`/`an`。
- **文字层可靠性**：该 PDF 由 Word 直接转出（非扫描），文字层内容准确，风险只在版面（拆行/顺序/换页），上面的图像核对针对的正是这些点。
- **正则残留检查**：词头区只有 1 行缩进非词性续行（第 162 行 `being, been)`），已归入 `be`；词组区无异常缩进行。

## 6. 计数

| 口径 | 数字 | 说明 |
|---|---|---|
| 单词表行数（词条数） | **1,724** | 与 PDF 词条一一对应 |
| 按 `/` `=` 拆开并列、去掉括号变体后的词形数 | 1,732 | 1,724 + 5 + 3 |
| 词形忽略大小写去重 | 1,731 | 仅 `miss`/`Miss` 重合 |
| 词组 | **342** | 无重复 |
| 附表 | 158 | 人称代词 12、物主代词(形容词性) 7、物主代词(名词性) 7、反身代词 8、基数词 39、序数词 33、星期 7、月份 12、国家/大洲 13、国籍/洲人 14、常用学科 6 |
| 词形信息 | 146 | 见 §4.4；`irregular-forms` 94 行＝93 个动词 |

按首字母：A 106、B 110、C 146、D 89、E 79、F 104、G 42、H 78、I 45、J 14、K 19、L 67、M 81、N 44、O 41、P 142、Q 10、R 80、S 200、T 96、U 26、V 15、W 82、Y 6、Z 2（无 X）。

外部口径对照（均为转述，未见手册原件）：上海译文《2020年上海市初中英语考纲词汇手册便携版》称「1733 个单词和 335 个词组」（verify/shanghai-secondary.md [shanghai-secondary-5] 引豆瓣 34946354）；App Store 应用称「1719 个」（facts/list-sources.md [list-sources-27]）。1,731 + `a` + `an` = 1,733 只是假设（verify/shanghai-secondary.md [shanghai-secondary-7] 修正 1），未证实；342 与 335 之差未能解释（见 §8）。INDEX §6.2 第 3 条建议固定「1,731 + 331」——其中 331 是换页符造成的少数（见 §7.4），应改为 1,731（或 1,724 行）+ 342。

## 7. 与此前三次解析的差异与裁决

对照用脚本 `compare.py`：把本表按 `/` `=` 拆开、去括号、NFKC、小写后与各文件比较。

### 7.1 `scratchpad/verify-provinces/out/S.txt`（1,723 条；文件末行无换行，`wc -l` 显示 1,722）
- 对方多出 3 条噪声：`caf`（`café` 在 `é` 处截断）、`o`（`o’clock` 在弯引号处截断）、`stuck v. stick`（`stuck v. stick 的过去式及过去分词` 的多词残留）。
- 本表多出 11 条：上述 3 条的正确形式 `café`、`o'clock`、`stuck`；`though, anyone, bike, everyone, someone`（对方正则 `[A-Za-z'\-\.]*` 在 `/` 处停止，只取了并列前半）；`examination, grandfather, grandmother`（同理在 `=` 处停止）。
- 裁决：全部以本表为准。1,731 − 11 + 3 = 1,723，两边完全对账。

### 7.2 `scratchpad/list-sources/02/heads.txt`（1,723 行 / 1,722 唯一，`miss` 重复）
- 对方多出 1 条：`will aux .v.`（原文 `will aux .v.` 的词性写法异常，对方正则未截断）→ 本表为 `will`。
- 本表多出 10 条：`exam, examination, grandma, grandmother, grandpa, grandfather, manner, more, toward`——正是 facts/list-sources.md [list-sources-6] 自述「未被正则命中、需人工处理」的 6 行（`exam=examination, grandma=grandmother, grandpa=grandfather, manner(s), more(much 或 many 的比较级), toward(s)`）；加 `will`。
- 裁决：以本表为准。1,731 − 10 + 1 = 1,722，对账成立。

### 7.3 `scratchpad/shanghai-secondary/analysis/sh2020_words.json`（1,731 唯一）
- 集合与本表拆分后的 1,731 **完全相同**，无差异。
- 作者报告的「1,733 token」含其脚本 `parse_sh.py` 末尾人为追加的 `hang`（注释称 pdftotext 拆行丢失）；核验（verify/shanghai-secondary.md [shanghai-secondary-7] 修正 1）与本次图像核对（PDF 第 29 页）都表明 `hang (hanged, hanged)` 本就是顶格词头行，追加造成重复。真实 token 数 1,732，与本表一致。

### 7.4 词组：`scratchpad/list-sources/02/phrases.txt`（309）与 verify 的 331 / 342
- 309 对 342：对方少 33 条：22 条含 `/` 或 `(`（其正则不接受这两个字符，对方文件中 `grep -c '[/(]'` = 0；如 `a lot of/lots of`, `at first/last`, `be busy with/doing sth.`, `would like/love (to)`），11 条是以 `\f` 开头的页首词组行 `at present, be responsible for, cut down, get to, have (got) to, in one's opinion, less/more than, not...at all, prepare for, stop...from, to one's joy/surprise`（layout 第 2228、2260、2292、2324、2356、2388、2419、2450、2481、2512、2543 行；其中 `have (got) to`、`less/more than`、`to one's joy/surprise` 3 条也含 `/` 或 `(`；这与单词表「漏页首词」是同一个换页符伪影）；另有 7 条被截断（`a bit`←`a bit (of)`, `be located`←`be located (in/on/at)`, `catch`←`catch (a) cold`, `far away`←`far away (from)`, `go to`←`go to (the) hospital`, `keep in touch`←`keep in touch (with)`, `leave`←`leave (secondary) school`）。分解由 `compare.py`（带 layout 参数）输出，见 `scratchpad/lists-shmeea/compare-run.log`。裁决：309 是解析正则的产物，以 342 为准。
- verify/shanghai-secondary.md [shanghai-secondary-7] 修正 3 的 331 =「顶格以字母开头的行」：词组区 12 页中后 11 页的首条词组行以 `\f` 开头，不以字母开头，342 − 11 = 331。本次逐行确认这 11 行（layout 第 2228、2260、2292、2324、2356、2388、2419、2450、2481、2512、2543 行）都是词组。裁决：342。
- verify/provinces.md [provinces-12] 修正 2 的 342 与本表一致。

### 7.5 provinces 原稿的 1,655 词 / 140 词组
已由 verify/provinces.md [provinces-12] 修正 2 判为漏掉页首词的伪影（INDEX §3 第 1 条），本次不再对照其文件。

## 8. 存疑与留给种子构建阶段的决定

1. **手册口径 1,733 / 335 无法复现**：1,733 可能 = 1,731 + `a` + `an`（未证实）；335 对 342 的 7 条之差无法解释（可能是并列条目计数方式不同），未见手册原件。
2. **`a`、`an`、`the` 不在正文**（图像与 grep 均确认），人称/物主/反身代词只在附表，`this/that/these/those` 在正文。是编制口径还是遗漏不可知；是否补入由种子阶段决定。
3. **`could`、`might` 不是独立词头**，只以 `can (could)`、`may (might)` 出现；`can’t = can not` 也在 `can` 一行；`should`、`would` 是独立词头。本表不新增词头；`could`、`might` 保留在 `-forms.tsv`（`can`、`may` 的 `past-form` 行），`can’t = can not` 只见于 `out/special.tsv`（layout 第 289 行的记录），未进入任何发布文件。
4. **并列与括号变体保留原貌**（单词表有 32 行非纯小写字母，即 `out/special.tsv` 162 行中 kept 列非纯小写的 32 行；各文件注释头另有说明）：`although/though` 等 5 条 `/`、`exam=examination` 等 3 条 `=`、`A.M. (a.m.)` 等 10 条括号、`Mr`/`Mrs`/`Miss`/`P.E.`/`Christmas` 等大写、`café`、`o'clock`、`hot-dog`、`ice-cream`。拆分、去括号、大小写归一都留给种子阶段。
5. **`miss`/`Miss` 两行**：是否合并由种子阶段决定（ECDICT 的 lemma 是小写）。
6. **`stuck`** 在 PDF 中是独立词头（`v. stick 的过去式及过去分词；adj. 被卡住的`），照录；`bund (the Bund)` 原文小写。
7. **`underground n. (美 subway)`** 在 `-forms.tsv` 中标为 `us-spelling`，实为美式对应词。
8. 词组 `be late for` 的释义以「……迟到」开头，截断点依据的是 `……` 位于释义列（图像核对），若手册原文是 `be late for…` 则词组形应带省略号；此处按不带处理。

## 9. 核验修正（2026-11-06）

依据核验报告 `docs/analysis/2026-11-05-stages-regions-images/lists-verify/shmeea-2020.md`（status = fix，P1–P8）逐条处理。每条先以原件再次确认——文字层用 `scratchpad/lists-shmeea/07-layout.txt`（与 `scratchpad/verify-provinces/dl-shmeea/07.txt` `cmp` 逐字节相同；`07.pdf` 的 `md5 -q` 仍为 `059df9c02684bd989fff6f8849ee1993`），图像用本次以 220 dpi 重新渲染的 `scratchpad/lists-shmeea/img220/p-10.png`、`p-19.png`、`p-41.png`——然后修 `parse.py`，重跑 `parse.py` + `emit.py` 生成产出，不手改产出文件。单词表、词组表、附表三个文件修正前后 `md5 -q` 相同（`36ac20ef04fd5ddd0e73b473eebe022b`、`0fd78e26c571dfc647f99289dfd6c0d2`、`52e334b89924552414c4992cce0d163b`），`out/words.txt`、`out/phrases.txt`、`out/appendix.tsv`、`out/entries.tsv`、`out/pages.tsv` 亦无差异。

| 编号 | 文件 | 改动 | 依据 |
|---|---|---|---|
| P1 | `-forms.tsv` | 新增 `burn\tirregular-forms\tburned, burned 或 burnt, burnt\theadword-line`（`bund (the Bund)` 行后）和 `dream\tirregular-forms\tdreamt, dreamt 或 dreamed, dreamed\theadword-line`（`draw` 行后） | layout 第 264、554 行；PDF 第 10 页（印刷页 9）`burn (burned, burned 或 burnt, burnt) v. 燃烧；着火；使烧焦`、第 19 页（印刷页 18）`dream (dreamt, dreamt 或 dreamed, dreamed) n. & v. 梦，梦想`，`img220/p-10.png`、`p-19.png` 逐字核对 |
| P2 | `-forms.tsv` | `much` 行 kind `irregular-forms` → `comparison` | layout 第 1236 行；PDF 第 41 页（印刷页 40）`much (more, most) adj.`，同页 `more(much 或 many 的比较级)`、`most (much 或 many 的最高级)`，`img220/p-41.png` |
| P1/P2 | `-forms.tsv` 注释头 | 计数 144 → 146；comparison 10 → 11；irregular-forms 93 → 94；按 P6 加「每行只标一个 kind」说明 | `emit.py` 重新生成；`out/diag.txt` |
| 脚本 | `scratchpad/lists-shmeea/parse.py` | `INFL` 改为 `^[a-z]+(?:(?:\s*[,，/；;]\s*(?:或\s*)?\|\s+或\s+)[a-z]+)+$`（表格内把正则的竖线写成 `\|`），接受「空格+或+空格」作分隔；`classify_form(c, head)` 对词头 much/many/little 或括号内容为 `more, most`/`less, least` 返回 `comparison`；`classify_paren` 复用 `INFL`，`out/special.tsv` 第 4 列对 burn、do、dream、fit、learn、pay、put、take 8 行改标 `drop:inflections`（原误标 `drop:zh-explanation`；kept 列与行数 162 不变） | 重跑后 `diff -r out-before out` 只有上述差异及 `diag.txt` 计数 |
| P3 | README §7.4 | 「33 条全部含 `/` 或 `(`」改为 22 条含 `/` `(` + 11 条页首 `\f` 行（3 条重叠）+ 7 条截断 | `compare.py` 新增成因分解（`scratchpad/lists-shmeea/compare-run.log`）；layout 第 2228…2543 行 |
| P4 | README §8.3 | `could`/`might` 在 `-forms.tsv`，`can’t = can not` 只见于 `out/special.tsv`；未新增 forms 行 | `-forms.tsv` 中 `can` 仅 `past-form could`；layout 第 289 行 |
| P5 | README §8.4 | 「32 行」改为「`out/special.tsv` 162 行中 kept 列非纯小写的 32 行」 | `check-run.log` |
| P6 | README §4.4、forms 注释头 | 注明 `maths (=mathematics，美 math)` 只标 `full-form`，美式拼写未计入 us-spelling；未拆行 | layout 第 1168 行 |
| 计数同步 | README §2、§4.1.4、§6 | 144 → 146；§4.1.4「93 条动词」改为「`irregular-forms` 94 行＝93 个动词」；「去掉的内容全部进 `-forms.tsv`」改为注明 `ought (to)`、`can’t = can not` 两处例外 | `check-run.log` |
| P7 | — | 未改：五个文件仍共用本 README，待建立 `data/lists/README.md` 索引时补一节 | 核验报告判「可接受」 |

关于 §4.1.4 的数字：核验报告建议把「93 条」改为「95 条」，那是只做 P1（+2）而不做 P2 的数字；本次同时做了 P2（`much` 移出 `irregular-forms`），所以 `irregular-forms` 为 94 行，对应 93 个动词（`hang` 两行），其中词头行括号 90 行、续行 3 行（`hang`、`lie`、`stick`）、释义 1 行（`be`）。

修正后复查（`check.py`，输出 `scratchpad/lists-shmeea/check-run.log`）：
- 单词表 1,724 行，精确重复 0，忽略大小写重复仅 `miss`/`Miss`；字母序断点 8 处（`always → A.M. (a.m.)`、`else → e-mail (email)`、`flash → flag`、`ocean → o'clock`、`pay → P.E.`、`plus → P.M. (p.m.)`、`responsible → responsibility`、`true → truck`），均为原件排印顺序（核验报告 §2 已逐一回看原件）；首字母分布与 §6 相同。
- 词组表 342 行，无重复，括号配平；字母序断点 11 处（`as...as → as long as`、`at/on weekends → at work`、`be/get familiar to/with → be famous for`、`break into → break down`、`in addition → in a hurry`、`in all → in a minute`、`keep...from → keep in touch (with)`、`on the phone → on the other hand`、`pay for → pay attention to`、`take an underground → take a message for sb.`、`tell...from → tell a lie`），均为原件顺序。
- 附表 158 行，全部 3 列，同节内无重复。
- `-forms.tsv` 146 行，全部 4 列；146 个词头全部存在于单词表并按单词表顺序排列；无重复 (headword, kind, printed)；printed 含「或」的 5 行为 burn、dream、far、more、most。
- 五个文件均 UTF-8、LF、无 BOM、无 CR、末尾有换行。
