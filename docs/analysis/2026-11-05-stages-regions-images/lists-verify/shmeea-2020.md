# 核验报告（第二轮）：`shmeea-2020-junior*`（上海市教育考试院 2020 初中英语词汇表词表产出）

核验日期 2026-11-06（对抗核验，默认产出有错）。被核验对象：作者按第一轮报告（P1–P8）修正后的 `data/lists/shmeea-2020-junior.txt`、`-phrases.txt`、`-appendix.tsv`、`-forms.tsv`、`.README.md`（工作区未提交文件，仓库 main @ 75df534），以及 `scratchpad/lists-shmeea/{parse.py,emit.py,compare.py,check.py,out/*,out-before/,lists-before/,img220/,*-run.log}`。第一轮报告（2026-11-05）原文保留在本文件附录 A（仅把标题层级下降一级，正文逐字未动），README §9 引用的 P1–P8 编号仍指向附录 A 的「6. 问题清单」。

路径写法：`scratchpad/` = `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/`；`layout 第 N 行` = `pdftotext -layout` 输出的行号（本轮重抽为 `scratchpad/verify2-lists-shmeea/my-layout.txt`，与作者 `lists-shmeea/07-layout.txt`、verify 的 `verify-provinces/dl-shmeea/07.txt` 三者 `cmp` 逐字节相同）；`p-NN.png` = 本轮在 `scratchpad/verify2-lists-shmeea/img/` 用 `pdftoppm -r 220` 渲染的 PDF 第 NN 页。本轮脚本与日志全部在 `scratchpad/verify2-lists-shmeea/`（`struct_check.py`、`derive.py`、`bbox_derive.py`、`compare_prev.py`，对应 `*-run.log`；图像核对记录 `image-check.md`）。

## 0. 结论

**status = ok。** 四个数据文件（单词 1,724 行、词组 342 行、附表 158 行、词形 146 行）经三种独立于作者脚本的手段核对——文字层按我自己的规则重推导、`pdftotext -bbox-layout` 几何位置重推导、22 页图像逐词阅读——**没有发现任何需要改动的条目**；与 8 份此前解析结果的全部差异都能用原件逐条裁决为本表正确。第一轮 P1（+`burn`、+`dream`）、P2（`much`→`comparison`）、P3–P6（README 措辞/计数）的修正在原件和产出中均已落实；作者自报的 36 项计数全部复现（§6）。余下只有三条不阻塞的说明性意见（§7 R1–R3：README §4.1.4 对 `be` 的机制描述不准确、§7.4 的归因措辞宜标明是推断、第一轮 P7 的「同名 README」格式折中仍未落实），均不涉及 `data/lists/` 数据行，不要求再改。

## 1. 核验手段（独立于作者脚本的部分）

| 手段 | 做法 | 结果 |
|---|---|---|
| 原件完整性 | `md5 -q` 三份 PDF 副本；`pdfinfo`；重抽 `pdftotext -layout` 后 `cmp` | `verify-provinces/dl-shmeea/07.pdf`、`list-sources/02/上海市初中英语词汇表（2020年版）.pdf`、`shanghai-secondary/02-mahavivo-sh2020pdf/sh_junior_2020.pdf` 的 md5 均为 `059df9c02684bd989fff6f8849ee1993`；89 页、1,200,683 字节、Creator「Acrobat PDFMaker 17 Word 版」；`my-layout.txt` 2,759 行、89 个 `\f`，与作者 `07-layout.txt`、verify 的 `07.txt` 逐字节相同 |
| 文字层独立推导 | `derive.py`：顶格行 = 词头行，词头 = 行首到第一个词性标记或中文之前，用我自己写的括号取舍规则规范化，逐页输出 | 1,724 条词头、342 条词组，序列与发布文件**完全相同**（唯一 diff 是我的规范化把 `phone (=telephone)`、`photo (=photograph)`、`popular (=pop)` 的 `(=…)` 也去掉了，属我方脚本差异，作者按 README §4.1.4 规则保留括号是对的）；缩进的非词性/非中文续行只有第 162 行 `being, been)` 与第 688–689 行 `adj.远的`/`adv.远地`（`far` 的词性与释义粘连，作者脚本按中文开头归为释义续行，不丢词头） |
| 几何位置独立推导 | `bbox_derive.py`：`pdftotext -bbox-layout`，以每行首词 `xMin` 是否等于本页最小 `xMin`（左边距）判定词头行 | 第 2–84 页左边距恒为 79.4 pt；单词页 1,724 条边距行、词组页 342 条，序列与发布文件相同（同上仅 `(=…)` 三条为我方规范化差异；词组页我的脚本未截中文，`leave (secondary) school (中学)毕业` 为我方差异）。全部 89 页中缩进在 0.3–15 pt 之间的行只有第 32 页 `conj.`（14.55 pt，词性续行）和第 85–87 页表格单元格（`人`、`名词性物主代词`、数字 1–9、`1，000` 等），**没有被当成续行的缩进词头** |
| 图像逐词核对 | 220 dpi 渲染后用 Read 阅读，共 **22 页**：随机抽样（`random.seed(20261106)`，排除第一轮已读的 25 页）单词页 PDF 3、6、9、13、25、55 与词组页 81、82；定向页 4、27、36、39、43、47、63（页首为换页符+续行、第一轮未读）、37（`lie`）、52（页首为字母组标题 R）、72（单词末页）、73（词组首页）、84（词组末页）、86–87（数词表） | 见 §3，22 页「原件有而产出无」「产出有而原件无」均为 0 |
| 集合差异 | `compare_prev.py`：发布文件按 `/` `=` 拆分、去括号、NFKC、小写后与 8 份此前解析结果比较，每个差异词打印其在 layout 中顶格出现的行号 | 见 §4 |
| 文件级结构 | `struct_check.py`：BOM / CR / 末尾换行 / 空行 / 非 ASCII 逐字符 / 不可见字符 / 全角括号与弯引号 / 重复 / 字母序断点（两种键）/ TSV 列数 / README 表格列数 | 见 §2 |
| 仓库状态 | `git status --porcelain` | 只有 `?? data/lists/` 与 `?? docs/analysis/2026-11-05-stages-regions-images/`，作者未改其他仓库文件；`data/lists/README.md` 不存在（§7 R3） |

## 2. 结构检查

| 文件 | 数据行 | 字节 | BOM | CR | 末尾 `\n` | 空行 | 重复 | 非 ASCII | TSV 列数 |
|---|---|---|---|---|---|---|---|---|---|
| `shmeea-2020-junior.txt` | 1,724 | 14,061 | 无 | 0 | 有 | 0 | 精确 0；忽略大小写 1（`miss`/`Miss`） | 仅 `café`（U+00E9 ×1） | — |
| `shmeea-2020-junior-phrases.txt` | 342 | 5,797 | 无 | 0 | 有 | 0 | 0 | 0 | — |
| `shmeea-2020-junior-appendix.tsv` | 158 | 4,962 | 无 | 0 | 有 | 0 | (word, section) 0；跨节 `Chinese/English/her/his/its`（原文如此） | section 列中文 | 全部 3 |
| `shmeea-2020-junior-forms.tsv` | 146 | 9,127 | 无 | 0 | 有 | 0 | 0 | printed 列含中文及原文的全角 `，`×14、`；`×2（照录，README §4.4 已说明） | 全部 4 |
| `shmeea-2020-junior.README.md` | — | 23,965 | 无 | 0 | 有 | — | — | — | 5 张表（第 7–13、17–23、31–39、84–91、138–149 行）列数一致 |

- 四个数据文件的数据行均无不可见字符（U+200B/U+FEFF/U+00A0/U+3000 等）、无全角括号、无弯引号；单词表字符集只有 `[a-zA-Z é ' . / = ( ) -]`。大写行 14（`A.M. (a.m.)`、`bund (the Bund)`、`Christmas`、`Internet`、`London`、`Miss`、`Mr`、`Mrs`、`Olympic`、`Pacific`、`Paris`、`P.E.`、`P.M. (p.m.)`、`television (TV)`），`/` 5、`=` 6（3 并列 + 3 `(=…)`）、`-` 3、`'` 1、`.` 3 行；非纯小写字母行 32，与 `out/special.tsv` kept 列非纯小写 32 行一致。首字母分布 A 106 / B 110 / C 146 / D 89 / E 79 / F 104 / G 42 / H 78 / I 45 / J 14 / K 19 / L 67 / M 81 / N 44 / O 41 / P 142 / Q 10 / R 80 / S 200 / T 96 / U 26 / V 15 / W 82 / Y 6 / Z 2，与 README §6 相同；layout 字母组标题行（第 4、136、277、461、570、670、806、856、950、1003、1020、1044、1138、1246、1308、1368、1539、1553、1654、1903、2020、2050、2067、2180、2188 行）确无 X。
- **字母序断点**：单词表 8 处（`always → A.M. (a.m.)`、`else → e-mail (email)`、`flash → flag`、`ocean → o'clock`、`pay → P.E.`、`plus → P.M. (p.m.)`、`responsible → responsibility`、`true → truck`），词组表 11 处，与作者 `check-run.log` 及第一轮 §2 完全一致。改用「只保留字母」的排序键复查，单词表只剩 `flash → flag`（本轮 p-25.png 确认原件顺序）、`responsible → responsibility`（layout 1606–1607）、`true → truck`（2005–2006）三处，其余五处只是标点/大小写造成的比较差异；`pay → P.E.` 本轮 p-47.png 亦确认为原件顺序。全部为排印顺序，不是解析错误。
- 词组区（layout 2197–2567）的缩进行恰好 12 行，全部是页码 72–83；以 `\f`+字母开头的行恰好 11 行（2228、2260、2292、2324、2356、2388、2419、2450、2481、2512、2543），与 README §4.2.1、§7.4 一致。括号全部配平；`...` 均为 ASCII 三点。
- 词头区正文确无 `a`/`an`/`the`（顶格行逐条检查）。

## 3. 抽样核对原件（图像逐词，22 页）

产出条数取自我的逐页推导（`verify2-lists-shmeea/out/my_pages_words.tsv`、`my_pages_phrases.tsv`，与发布文件序列相同），逐词与图像比对。

| PDF 页 | 印刷页 | 产出条数 | 原件有而产出无 | 产出有而原件无 | 备注 |
|---|---|---|---|---|---|
| 3 | 2 | 22 | 无 | 无 | `afford` … `along` |
| 4 | 3 | 25 | 无 | 无 | 页首 `adv. 向前…` 是 `along` 续行；`although/though`、`A.M. (a.m.)`、`anybody/anyone` |
| 6 | 5 | 24 | 无 | 无 | A→B 分组；`bad (比较级 worse，最高级 worst)` |
| 9 | 8 | 22 | 无 | 无 | `born (动词 bear 的过去分词)`、`break (broke, broken)` |
| 13 | 12 | 26 | 无 | 无 | `china` 小写、`Christmas` 大写；`click n. & v.（鼠标）点击`（全角括号在释义内） |
| 25 | 24 | 24 | 无 | 无 | `flash → flag` 为原件顺序；`fit (fit, fit；fitted, fitted)` |
| 27 | 26 | 25 | 无 | 无 | 页首 `v. 形成` 是 `form` 续行；F→G |
| 36 | 35 | 21 | 无 | 无 | 页首三行是 `last` 续行；`learn (learnt，learnt；learned，learned)` |
| 37 | 36 | 19 | 无 | 无 | `lie n. & v.` / `v. (lay, lain)`：原件只给一套变化，`-forms.tsv` 一行正确 |
| 39 | 38 | 22 | 无 | 无 | 页首 `n. (大学中的)主修科目` 是 `major` 续行；`manner(s)`、`maths (=mathematics，美 math)`、`may (might)`、`mean v. (meant, meant)` |
| 43 | 42 | 24 | 无 | 无 | 页首两行是 `neither` 续行 |
| 47 | 46 | 26 | 无 | 无 | 页首 `adj. 耐心的` 是 `patient` 续行；`pay → P.E.`；`phone (=telephone)`、`photo (=photograph)` |
| 52 | 51 | 24 | 无 | 无 | 页首为字母组标题 R |
| 55 | 54 | 24 | 无 | 无 | R→S |
| 63 | 62 | 24 | 无 | 无 | 页首 `v. 使惊奇…` 是 `surprise` 续行；S→T；`take (took，taken)` |
| 72 | 71 | 15 | 无 | 无 | `would aux. v. 愿意(will 的过去式)`；Y、Z 组；末词 `zoo` |
| 73 | 72 | 27 | 无 | 无 | `a bit (of )`→`a bit (of)`、`arrive at/ in a place`→`arrive at/in a place` 的空格规范 |
| 81 | 80 | 29 | 无 | 无 | 页首 `not...at all`；`on the/one’s way (to)`→`one's` |
| 82 | 81 | 29 | 无 | 无 | 页首 `prepare for`；`see...off`、`share...with` |
| 84 | 83 | 21 | 无 | 无 | 页首 `to one’s joy/surprise`；末条 `would rather` |
| 86 | 85 | 19+19 | 无 | 无 | `one`…`nineteen` / `first`…`nineteenth` |
| 87 | 86 | 20+14 | 无 | 无 | `twenty`…`one billion` / `twentieth`…`one hundred and second`，其余序数格为「—」 |

22 页合计 0 / 0。加上第一轮的 25 页，两轮图像共覆盖 47 页（单词区 34/71 页、词组区 7/12 页、附表 5/5 页）；未读图像的页面由 §1 的文字层推导与几何推导双重覆盖。

## 4. 与此前独立解析结果的集合差异（用原件裁决）

| 对照文件 | 行 / 唯一 | 本表独有 | 对方独有 | 裁决 |
|---|---|---|---|---|
| `verify-provinces/out/S.txt` | 1,723 / 1,723 | 11：`anyone, bike, café, everyone, examination, grandfather, grandmother, o'clock, someone, stuck, though` | 3：`caf`、`o`、`stuck v. stick` | 对方正则在 `é`（layout 279）、`’`（1313）、多词行（1863）处截断，并在 `/`（68、89、199、636、1792）、`=`（641、837、840）处只取前半；本表为准，与 README §7.1 相同 |
| `list-sources/02/heads.txt` | 1,723 / 1,722（重复 `miss`） | 10：`exam, examination, grandfather, grandma, grandmother, grandpa, manner, more, toward, will` | 1：`will aux .v.` | layout 641、837、840、1157、1219、1987、2137；与 facts/list-sources.md 第 77 行自述的 6 条未命中行一致；本表为准，与 README §7.2 相同 |
| `shanghai-secondary/analysis/sh2020_words.json` | 1,731 / 1,731 | 0 | 0 | 完全相同 |
| `provinces/sh2020_headwords.txt`（原稿解析） | 1,697 / 1,697 | 76 | 42 | 对方独有 42 条全部来自词组区（layout 2198–2536：`a bit, a couple, a kind, a lot, a pair, a piece, according, add...to, as...as, based, both...and, compete, had, keep...from, mobile, no, prefer...to, prevent...from, protect...from, provide...with, refer, see...off, share...with, shopping, sooner, surf, tell...from, the, too...to, used`）和附表（2703–2745：`Africa, America, Asia, Australia, Britain, Canada, England, Europe, France, Germany, Italy, Japan`），不是单词区词头；本表独有 76 = 单词区 57 个 `\f`+词头的页首行全部缺失（我按 `\f`+字母统计单词区页首词头行恰为 57，57/57 不在对方文件；verify/provinces.md [provinces-12] 修正 2 所说「68 个页首词头中 60 个」应是把全部 89 页的页首行都算进去的口径，结论不变）+ `/`、`=` 并列的拆分项 + `café`、`o'clock`、`manner`、`more`。本表为准 |
| `provinces/sh2020_words.txt` | 1,655 / 1,655 | 76（同上） | 0 | 对方是本表的真子集；INDEX §3 第 1 条「漏掉每页首词的伪影」成立 |
| `verify-lists-shmeea/my-words.txt`（第一轮位置法） | 1,724 / 1,723 | — | — | 差异只是对方未拆 `/`、`=`、未去括号变体（18 条并列/括号行 ↔ 26 个拆分词形），集合等价 |
| `list-sources/02/phrases.txt` | 309 / 309 | 40 | 7：`a bit, be located, catch, far away, go to, keep in touch, leave` | 7 条截断 + 22 条含 `/` `(` + 11 条页首 `\f` 行（其中 3 条兼含 `/` `(`）= 40；对方文件 `grep -c '[/(]'` = 0，11 条页首词组 `grep -F -x` 均为 0；与 README §7.4、`compare-run.log` 相同。本表为准 |
| `verify-lists-shmeea/my-phrases.txt` | 342 / 342 | 0 | 0 | 完全相同 |

## 5. README 的 provenance、页码表与格式

| 项目 | README / 注释头写法 | 核对 | 结果 |
|---|---|---|---|
| 发布页 / 文件 URL | `https://www.shmeea.edu.cn/page/08000/20190926/13309.html`；href 原文 `http://www.shmeea.edu.cn/download/20190926/07.pdf`（302 到 https） | verify/provinces.md 第 70 行（[provinces-12] 修正 1）、第 137 行；`dl-shmeea/index.html` 中 `href="http://www.shmeea.edu.cn/download/20190926/07.pdf"`（grep，未执行） | ✓ |
| md5 / 字节 / 页数 / 生成工具 / 元数据 | `059df9c0…1993`、1,200,683 B、89 页、Acrobat PDFMaker 17 Word 版；Title「Medical NOte」为模板残留 | 本轮 `md5 -q`（三份副本相同）、`pdfinfo`；verify/provinces.md 第 12、70 行 | ✓ |
| 获取日期 | 2026-11-05 | verify/provinces.md 第 11–12 行 | ✓ |
| §3 页码 ↔ layout 行号表 | 2–72 → 3–2195；73–84 → 2196–2568；85 → 2569–2601；86–87 → 2602–2686；88 → 2687–2718；89 → 2719–2759 | `\f` 位于第 3, 34, …, 2173, 2196, 2228, …, 2543, 2569, 2602, 2645, 2687, 2719（第 2760 行为文件末尾的 `\f`）；节标题行 3 / 2196 / 2569 / 2602 / 2687 / 2702 / 2749 | ✓ |
| §4.1.2 页首行分类 | 57 页 `\f`+词头、12 页 `\f`+续行（4、14、21、23、27、36、39、43、47、61、63、70）、PDF 52 首行为 R、PDF 2 首行为节标题 | 我的推导：首行为续行的页 = {2, 4, 14, 21, 23, 27, 36, 39, 43, 47, 52, 61, 63, 70}；`\f`+字母的词头行 57；本轮图像 p-04/27/36/39/43/47/63 页首均为续行、p-52 页首为 R | ✓ |
| §4.2.1 / §4.2.3 / §4.2.4 | 12 个缩进行全是页码；9 条悬空 `(`；14 条 `’`→`'` | 缩进行 12 = 页码 72–83；`diag.txt` 9 行；含 `'` 的词组 14 行 | ✓ |
| §6 计数与首字母分布 | 1,724 / 1,732 / 1,731 / 342 / 158（各节）/ 146 | §2 | ✓ |
| §7.1–7.4 差异数字 | 11/3、10/1、0/0、40/7（7+22+11，3 重叠） | §4 | ✓ |
| §9 修正前后 md5 | 三文件不变 `36ac20ef…`、`0fd78e26…`、`52e334b8…` | `lists-before/` 三文件 md5 与现行相同；`-forms.tsv` 由 `5b1526d7…` 变为 `daefba32…`；`diff -r out-before out` 只有 `forms.tsv`（+2 行、`much` 改标）、`diag.txt` 计数、`special.tsv` 8 行标签 | ✓ |
| 统一格式 | 每文件 `#` 注释头含来源文件名与 URL、本地路径与 md5、获取日期、规则摘要、计数；UTF-8、LF、无 BOM | §2；注释头全部在数据行之前 | ✓ |
| 「同名 .README.md 或 data/lists/README.md 一节」 | 五文件共用 `shmeea-2020-junior.README.md`，各文件头以「说明文档：」指向它 | `data/lists/README.md` 不存在；同目录 `moe-2022.README.md`、`moe-senior.README.md` 也是分组 README | 折中可接受，见 §7 R3 |

## 6. 作者自报计数复核

| 自报项 | 自报值 | 复核 | 依据 |
|---|---|---|---|
| words_lines / words_split_tokens / words_unique_ci / words_dup_ci | 1724 / 1732 / 1731 / 1 | ✓ | `struct-run.log`、`compare-prev-run.log` |
| words_alpha_breakpoints / phrases / phrases_alpha_breakpoints | 8 / 342 / 11 | ✓ | `struct-run.log` |
| appendix_rows | 158 | ✓ | `struct-run.log`（各节 12/7/7/8/39/33/7/12/13/14/6） |
| forms_rows / comparison / alt_form / past_form / us_spelling / plural / full_form / uk_spelling | 146 / 11 / 7 / 5 / 12 / 12 / 4 / 1 | ✓ | `struct-run.log` by kind |
| forms_irregular_forms_rows / distinct_verbs / headword_line_rows | 94 / 93 / 90 | ✓ | `check-run.log`（by where：headword-line 90、continuation 3、gloss 1；`hang` 两行） |
| forms_rows_added / forms_rows_relabelled | 2 / 1 | ✓ | `diff -r out-before out`：+`burn`、+`dream`，`much` 行改标 |
| special_rows / special_kept_non_lowercase / special_category_relabelled_rows | 162 / 32 / 8 | ✓ | `special.tsv` 162 行；kept 非纯小写 32；diff 中 burn、do、dream、fit、learn、pay、put、take 8 行 `drop:zh-explanation`→`drop:inflections` |
| phrases_missing_in_old_309 / only_slash_paren / page_first / page_first_and_slash_paren / truncated_in_old | 33 / 22 / 11 / 3 / 7 | ✓ | `compare-prev-run.log`、`compare-run.log`；老文件无任何 `/` `(` 行 |
| pdf_pages_rerendered_220dpi / files_unchanged_md5 | 3 / 3 | ✓ | `img220/` 三个 PNG；`lists-before/` md5 |

作者自报的不确定项逐条看法：§4.1.4 取 94（而非第一轮建议的 95）是对的，95 只在不做 P2 时成立；P4 取措辞方案、P6 取注明方案都与数据一致；`classify_paren` 复用 `INFL` 的副作用（special.tsv 8 行改标）已在 README §9 写明；`compare.py` 的「截断」判定为启发式这一点见 §7 R2；字母序断点本轮已再回看两处图像（p-25、p-47）；P7 见 R3。

## 7. 问题与建议（均不阻塞，不要求改 `data/lists/`）

**R1（文档，低）README §4.1.4 对 `be` 的机制描述不准确。** 该条写在「括号处理（词头零件里的括号）… 去掉」项下：「跨行未闭合的 `be v. 是；成为(原形，……`→`be`」。但原件第 161 行 `be v. 是；成为(原形，其人称和时态形式有 am, is, are, was, were,` 的括号位于词性 `v.` 之后，词头按 §4.1.3 规则在 `v.` 处截断，括号从未进入词头零件：`out/special.tsv` 没有 `be` 行，`drop:*` 类别计数里也没有 `unclosed`（`inflections` 90、`zh-explanation` 36、`grammar` 4、`trailing-contraction` 1），即 `parse.py` `extract_head` 的「未闭合括号」分支对本 PDF 从未触发。数据结果（词头 `be`、`-forms.tsv` 的 `be … gloss` 行）正确，只是说明文字把一个未发生的处理当成了例子。建议改写为「`be` 的变化形式写在释义括号内且跨行（第 161–162 行），词头在 `v.` 处截断，变化形式按原文补入 `-forms.tsv`（where = gloss）」，并把 `parse.py` 的 unclosed 分支标注为防御性代码。

**R2（文档，低）README §7.4「其正则不接受这两个字符」是由输出形态反推的。** `scratchpad/list-sources/tools/` 只有 `lxy.py`（DictionaryData）、`compare.py`、`stats.py`，没有生成 `phrases.txt` 的脚本；facts/list-sources.md 第 77 行只记录了单词正则。证据链（对方文件 0 行含 `/` `(`、11 条页首词组全部缺失、7 条在 `(` 前截断）足以支持结论，但措辞宜加「推断」。作者自报不确定项已承认这一点。

**R3（格式，低，承自第一轮 P7）** 五个文件共用一份 README，`data/lists/README.md` 不存在；同目录的 `moe-2022.README.md`、`moe-senior.README.md` 也采用分组 README。这是整个 `data/lists/` 的约定问题而非本产出独有，建议在词表任务收尾时建一个 `data/lists/README.md` 索引（每组一节、指向各组 README），本产出不单独改。

**供种子阶段参考（不是问题）：** 释义内含屈折形式但按 README §4.4 规则未收入 `-forms.tsv` 的括号只有 `do … (用以构成疑问句及否定句。第三人称单数现在时用 does)`（layout 542–543，跨行）、`human n. (=human being)`（942）、`like v. … (should/would like)`（1096）、`whom (who 的宾格)`（2129）、`would … (will 的过去式)`（2174）；`-forms.tsv` 的 `where=headword-line` 指括号所在行（`mean v. (meant, meant)` 的括号在词性之后仍标 headword-line），`gloss` 只用于 `be`。`lie` 原件只给 `(lay, lain)` 一套（1089），一行正确。单词区 351 个括号中其余 200 余个全是中文释义括号（`(时间)`、`(复)` 无形式等），逐一扫过，没有遗漏的英文词形。

### 核对过、不构成问题的点

- 并列与括号变体保留原貌（32 行非纯小写字母）符合统一格式「保持原文词形、不拆并列」；`manner(s)`、`toward(s)` 原件即无空格（p-39.png）。
- 词组的空格规范（`a bit (of )`→`a bit (of)`、`arrive at/ in a place`→`arrive at/in a place`）与弯引号转换（14 条）在 README §4.2.4 与注释头均有说明，p-73/81/84.png 确认原件写法。
- `be late for  ……迟到`（layout 2251）截到 `be late for`，README §8.8 已存疑说明。
- 附表：代词三表、数词两表（p-86/87.png 本轮逐格核对）、月份星期、国家/国籍（`British`+`Briton`、`America` 注 `U.S.A.`、`Britain` 注 `U.K.`）、学科 6，与 layout 2569–2759 逐项一致。
- `-forms.tsv` 146 个词头全部在单词表且按单词表顺序；`printed` 列除 `be` 外均能在 layout 中逐字找到。

## 8. 建议修正汇总

无必修项。可选（文档措辞）：

| 文件 | 动作 | 内容 |
|---|---|---|
| `data/lists/shmeea-2020-junior.README.md` | replace（可选） | §4.1.4「跨行未闭合的 `be v. 是；成为(原形，……`→`be`」按 R1 改写为释义括号跨行、词头在 `v.` 处截断的描述 |
| `data/lists/shmeea-2020-junior.README.md` | replace（可选） | §7.4「其正则不接受这两个字符」→「（由输出形态推断）其正则不接受这两个字符」 |
| `data/lists/README.md` | add（目录级跟进，非本产出） | 建立索引，每组词表一节，指向各组 README |

## 9. 声明

本轮没有改动 `data/lists/` 下任何文件，也没有改动仓库其他文件；唯一写入的仓库文件是本报告（覆盖同路径的第一轮报告，第一轮原文见附录 A，覆盖前原文件 md5 记在附录 A 开头）。核验脚本、日志与渲染图像在 `scratchpad/verify2-lists-shmeea/`（`struct_check.py`、`derive.py`、`bbox_derive.py`、`compare_prev.py`、`*-run.log`、`my-layout.txt`、`bbox.html`、`img/p-NN.png`、`image-check.md`、`out/`），全部用 `python3.12 -I`（Homebrew）运行、以参数传路径，未执行任何下载来的代码，未联网，未触碰 `/Users/sqin/word-dance-data`。

---

# 附录 A：第一轮核验报告（2026-11-05）原文

以下为覆盖前同路径文件的全文（`md5 -q` = `80fa22d8ab1f3f6e7a54cac45a7efad0`，23,628 字节；备份 `scratchpad/verify2-lists-shmeea/round1-original.md`），仅把每个标题的层级下降一级，正文逐字未动。README §9 引用的 P1–P8 见其「6. 问题清单」。

## 核验报告：`shmeea-2020-junior*`（上海市教育考试院 2020 初中英语词汇表词表产出）

核验日期 2026-11-05（对抗核验，默认产出有错）。被核验对象：`data/lists/shmeea-2020-junior.txt`、`-phrases.txt`、`-appendix.tsv`、`-forms.tsv`、`.README.md`（工作区未提交文件，仓库 main @ 75df534），以及 `scratchpad/lists-shmeea/{parse.py,emit.py,compare.py,out/pages.tsv,out/special.tsv}`。下文 `scratchpad/` = `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/`；`layout 第 N 行` = `pdftotext -layout` 输出（`scratchpad/verify-provinces/dl-shmeea/07.txt`，与我重抽的 `scratchpad/verify-lists-shmeea/my-layout.txt` 和作者的 `lists-shmeea/07-layout.txt` 三者 `cmp` 逐字节相同）的行号；`p-NN.png` = 我在 `scratchpad/verify-lists-shmeea/img/` 下用 `pdftoppm -r 220` 渲染的 PDF 第 NN 页。

### 0. 结论

**status = fix。** 单词表（1,724 行）、词组表（342 行）、附表（158 行）三个文件经独立手段核对**没有发现任何需要改动的条目**；需要修的是 `-forms.tsv`（漏收 2 行、1 行 kind 标错）以及 README／注释头里随之而来的计数和两处说明性错误（§6 问题清单 P1–P3 为必修，P4–P8 为措辞/格式建议）。作者自报计数中 `forms_rows: 144`、`forms_irregular_verbs: 93` 不成立，应为 146 / 95（若同时按 P2 改 `much` 的标签则 irregular-forms 94、comparison 11）；其余计数全部复现。

### 1. 核验手段（独立于作者脚本的部分）

| 手段 | 做法 | 结果 |
|---|---|---|
| 重抽文字层 | `pdftotext -layout 07.pdf my-layout.txt` | 2,759 行、89 个 `\f`，与作者 `07-layout.txt` 及 verify 的 `07.txt` 逐字节相同（`cmp`）；`md5 -q 07.pdf` = `059df9c02684bd989fff6f8849ee1993`，与 `list-sources/02/上海市初中英语词汇表（2020年版）.pdf`、`shanghai-secondary/02-mahavivo-sh2020pdf/sh_junior_2020.pdf` 相同 |
| 位置法判词头（不依赖「顶格/缩进」文本规则） | `pdftotext -bbox-layout` → `scratchpad/verify-lists-shmeea/bbox_heads.py`（`python3 -I`）：以每行首词 `xMin` 是否等于页面左边距判定词头行 | 页 2–84 左边距恒为 79.4 pt；所有行要么在边距 ±0.1 pt（`below/belt/beside`，第 8 页），要么缩进 ≥ 14.5 pt，没有「半缩进」的可疑行。单词区得 **1,724** 条边距行、词组区 **342** 条，逐页逐条与作者 `out/entries.tsv` 序列相同（脚本无任何 `PAGE … diff` 输出） |
| 图像逐词核对 | 220 dpi 渲染后用 Read 阅读，共 **25 页**：随机抽样（`random.seed(20261105)`）单词页 PDF 14、18、21、23、54、56 与词组页 75、77；定向页 2（首页）、7（`be` 跨行）、10（`burn`）、19（`dream`）、29（`hang`）、40（`miss/Miss`）、41（`much`、`Mr/Mrs`）、61–62（`stick/stuck`）、69–70（`well` 跨页）、74（`be late for`）、附表 85–89 | 见 §3，25 页「原件有而产出无」「产出有而原件无」均为 0 |
| 复跑对照 | `python3 -I compare.py` 以发布文件为输入 | 与 README §7 数字完全一致（§4） |
| 文件级结构 | BOM / CR / 末尾换行 / 空行 / 非 ASCII / 重复 / 字母序断点 / TSV 列数 / 括号配平 | 见 §2 |
| 仓库状态 | `git status --porcelain` | 只有 `?? data/lists/` 与 `?? docs/analysis/2026-11-05-stages-regions-images/`，作者未改其他仓库文件 |

### 2. 结构检查

| 文件 | 数据行 | 字节 | BOM | CR | 末尾 `\n` | 空行 | 重复 | 非 ASCII 行 | TSV 列数 |
|---|---|---|---|---|---|---|---|---|---|
| `shmeea-2020-junior.txt` | 1,724 | 14,061 | 无 | 0 | 有 | 0 | 精确 0；忽略大小写 1（`miss`/`Miss`） | 1（`café`，U+00E9） | — |
| `shmeea-2020-junior-phrases.txt` | 342 | 5,797 | 无 | 0 | 有 | 0 | 0 | 0 | — |
| `shmeea-2020-junior-appendix.tsv` | 158 | 4,962 | 无 | 0 | 有 | 0 | 同节内 0；跨节 `her/his/its/Chinese/English`（原文如此） | 158（section 列为中文） | 全部 3 |
| `shmeea-2020-junior-forms.tsv` | 144 | 8,738 | 无 | 0 | 有 | 0 | — | 144 | 全部 4 |
| `shmeea-2020-junior.README.md` | — | 16,294 | 无 | 0 | 有 | — | — | — | — |

- 单词表非字母字符清单：`/`×5、`=`×6（3 条 `x=y` + 3 条 `(=…)`）、`(`/`)`×10、`.`×10（`A.M. (a.m.)`、`P.M. (p.m.)`、`P.E.`）、`-`×3（`e-mail`、`hot-dog`、`ice-cream`）、`'`×1（`o'clock`）、空格×9（均在括号变体内）。弯引号已全部转为 `'`；无全角括号、无不可见字符。非纯小写行 32 行，与作者 `special_headword_lines: 32` 一致。
- 首字母分布 A 106 / B 110 / C 146 / D 89 / E 79 / F 104 / G 42 / H 78 / I 45 / J 14 / K 19 / L 67 / M 81 / N 44 / O 41 / P 142 / Q 10 / R 80 / S 200 / T 96 / U 26 / V 15 / W 82 / Y 6 / Z 2，与 README §6 完全一致；layout 中的字母组标题行（第 4、136、277 … 2180、2188 行）确无 X。
- **字母序断点（单词表 8 处）**：`always → A.M. (a.m.)`（layout 70–71）、`else → e-mail (email)`（599–600）、`flash → flag`（739–740）、`ocean → o'clock`（1312–1313）、`pay → P.E.`（1399–1401）、`plus → P.M. (p.m.)`（1460–1461）、`responsible → responsibility`（1606–1607）、`true → truck`（2005–2006）。逐一回看原件：全部是 PDF 自身的排印顺序（前六处是标点/大小写排序差异，`flash/flag`、`responsible/responsibility`、`true/truck` 是原件顺序），**不是解析错误**，产出按原件顺序照录是正确的。
- **字母序断点（词组表 11 处）**：`as...as → as long as`、`at/on weekends → at work`、`be/get familiar to/with → be famous for`、`break into → break down`（layout 2272–2273，p-75.png 确认）、`in addition → in a hurry`、`in all → in a minute`、`keep...from → keep in touch (with)`、`on the phone → on the other hand`、`pay for → pay attention to`（2469–2470）、`take an underground → take a message for sb.`、`tell...from → tell a lie`。全部为原件顺序。
- 括号配平：两表无不配对括号。词组表内 `...` 均为 ASCII 三点（原件如此，layout 第 2206、2215、2271 … 行），`……`（U+2026）只出现在释义列；对全部 371 行词组区做「截到第一个中文」与「截到第一个中文或 U+2026」两种切法比较，唯一不同的是第 2251 行 `be late for    ……迟到`（p-74.png 确认省略号在释义列，产出 `be late for` 正确）；释义列中没有任何拉丁字母残留。

### 3. 抽样核对原件（图像逐词）

单词页：产出词头数取自 `out/pages.tsv`/`entries.tsv`，与图像逐词比对。

| PDF 页 | 印刷页 | 产出词头数 | 原件有而产出无 | 产出有而原件无 | 备注 |
|---|---|---|---|---|---|
| 2 | 1 | 26 | 无 | 无 | 首词 `ability`，页面确无 `a`/`an` |
| 7 | 6 | 25 | 无 | 无 | `be v. 是；成为(原形，…` 括号跨行到 `being, been)`；`behavior` 原文即美式拼写 |
| 10 | 9 | 25 | 无 | 无 | `bund (the Bund) n.外滩` 小写；`burn (burned, burned 或 burnt, burnt)`（见 P1）；`café` |
| 14 | 13 | 24 | 无 | 无 | 页首两行是 `close` 的 adj./adv. 续行 |
| 18 | 17 | 27 | 无 | 无 | |
| 19 | 18 | 25 | 无 | 无 | `dream (dreamt, dreamt 或 dreamed, dreamed)`（见 P1）；`do (did，done)` 全角逗号 |
| 21 | 20 | 23 | 无 | 无 | 页首是 `either` 续行；`e-mail (email)` |
| 23 | 22 | 21 | 无 | 无 | 页首是 `exercise` 续行；E→F 分组 |
| 29 | 28 | 25 | 无 | 无 | `hang (hanged, hanged)` 顶格、`(hung, hung) v.` 缩进，只有一个词头 |
| 40 | 39 | 26 | 无 | 无 | `miss v.` / `Miss n.` 两条 |
| 41 | 40 | 22 | 无 | 无 | `much (more, most) adj.`（见 P2）；`Mr`/`Mrs` 无句点 |
| 54 | 53 | 23 | 无 | 无 | |
| 56 | 55 | 27 | 无 | 无 | |
| 61 | 60 | 21 | 无 | 无 | 页首是 `stay` 续行；`stick n.` + `v. (stuck, stuck)` 缩进 |
| 62 | 61 | 26 | 无 | 无 | `stuck v. stick 的过去式及过去分词 / adj.` 是独立顶格词头 |
| 69 | 68 | 19 | 无 | 无 | `well` 四个词性，释义跨页 |
| 70 | 69 | 22 | 无 | 无 | 页首「好吧；那么」是 `well` 续行；`will aux .v.` |

词组页与附表：

| PDF 页 | 印刷页 | 产出条数 | 原件有而产出无 | 产出有而原件无 | 备注 |
|---|---|---|---|---|---|
| 74 | 73 | 30 | 无 | 无 | `at /on weekends`→`at/on weekends`、`be located (in /on/at)`→`(in/on/at)` 的空格规范正确；`be late for  ……迟到` |
| 75 | 74 | 30 | 无 | 无 | `catch (a) cold`、`change one’s mind`→`one's` |
| 77 | 76 | 30 | 无 | 无 | `go to (the) hospital`、`go to the cinema/movie(s)` |
| 85 | 84 | 12+7+7+8 | 无 | 无 | 三张代词表；`you` 四格、`yours` 两格、`themselves` 三格合并后各一条 |
| 86–87 | 85–86 | 39+33 | 无 | 无 | 基数词到 `one billion`、序数词到 `one hundred and second`，其余格为「—」 |
| 88 | 87 | 7+12 / 4+5 | 无 | 无 | 星期、月份；`America n. 美国 (U.S.A.)`（U.S.A. 在释义中，产出放 note 列）、`Britain (U.K.)`、`British`+`Briton` |
| 89 | 88 | 9+9 / 6 | 无 | 无 | 国家续表；常用学科 `Chinese, English, Math(s), Biology, Physics, Chemistry` |

另外对全部 71 个单词页、12 个词组页用位置法（§1）逐条比对了词头序列，没有差异；因此 §3 的「无差异」不只是抽样结论。

### 4. 与此前独立解析结果的集合差异（用原件裁决）

复跑 `compare.py`（输入为发布文件去掉 `#` 行后的内容；`cmp` 证实其与 `out/words.txt`、`out/phrases.txt` 相同）：

1. **`verify-provinces/out/S.txt`**（1,723 条，末行无换行，`wc -l` 1,722 ✓）：对方独有 `caf`、`o`、`stuck v. stick`；本表独有 `anyone, bike, café, everyone, examination, grandfather, grandmother, o'clock, someone, stuck, though`。原件：`café n.`（layout 279，p-10.png）、`o’clock adv.`（1313）、`stuck v. stick 的过去式及过去分词`（1863，p-62.png）；`although/though`（68）、`anybody/anyone`（89）、`bicycle/bike`（199）、`everybody/everyone`（636）、`somebody/someone`（1792）、`exam=examination`（641）、`grandma=grandmother`（837）、`grandpa=grandfather`（840，p-29.png）。`recount.py` 第 3/28 行的词正则 `[A-Za-z'\-\.]*` 确实在 `é`、`’`、`/`、`=` 处截断。**全部以本表为准**，README §7.1 的说明正确。
2. **`list-sources/02/heads.txt`**（1,723 行 / 1,722 唯一，重复 `miss` ✓）：对方独有 `will aux .v.`（第 1683 行；原件 layout 2137 `will aux .v.` 词性写法异常，p-70.png），本表独有 `exam, examination, grandfather, grandma, grandmother, grandpa, manner, more, toward, will`，与 facts/list-sources.md [list-sources-6] 自述的 6 条未命中行一致。**以本表为准**。
3. **`shanghai-secondary/analysis/sh2020_words.json`**（1,731 唯一）：与本表拆分后的 1,731 **完全相同**。`parse_sh.py` 第 27 行 `heads.append("hang")` 确为人为追加（原件 layout 864 顶格 `hang (hanged, hanged)`，p-29.png），README §7.3 的说明正确。
4. **`list-sources/02/phrases.txt`**（309）：对方独有 7 条截断形（`a bit, be located, catch, far away, go to, keep in touch, leave`），本表独有 40 条，其中 7 条是上述截断的完整形，其余 **33 条**。README §7.4 说这 33 条「全部是含 `/` 或 `(` 的行」——**不对**：其中 8 条 `at present, be responsible for, cut down, get to, in one's opinion, not...at all, prepare for, stop...from` 不含 `/` 或 `(`，它们全是以 `\f` 开头的页首词组行（layout 2228、2260、2292、2324、2388、2450、2481、2512），即与单词表「漏页首词」同一个换页符伪影；另 3 条页首行 `have (got) to, less/more than, to one's joy/surprise` 两种原因兼有；真正只因 `/`、`(` 丢失的是 22 条。对方文件里确实一行 `/` 或 `(` 都没有（`grep -c '[/(]'` = 0），这 11 条页首词组也全部不在其中（`grep -F -x` 均为 0）。**裁决：342 为准**，但 README 的解释要改（P3）。
5. **verify/shanghai-secondary.md [shanghai-secondary-7] 修正 3 的 331**：词组区以 `\f` 开头的行恰好 11 行（`grep -c $'^\f[A-Za-z]'` = 11，PDF 74–84 每页首行），342 − 11 = 331 ✓；README §7.4 第二条与作者「INDEX §6.2 第 3 条的 331 应改为 342」的意见成立。
6. provinces 原稿的 1,655/140 已由 verify/provinces.md [provinces-12] 修正 2 判为伪影，不再对照。

### 5. README 的 provenance、页码表与格式

| 项目 | README 写法 | 核对 | 结果 |
|---|---|---|---|
| 发布页 / 文件 URL | `https://www.shmeea.edu.cn/page/08000/20190926/13309.html`，href `http://www.shmeea.edu.cn/download/20190926/07.pdf` | verify/provinces.md [provinces-12] 修正 1、第 137 行「遗漏」1；`dl-shmeea/index.html` 中 `href="http://www.shmeea.edu.cn/download/20190926/07.pdf"`（grep） | ✓ |
| md5 / 字节数 / 页数 / 生成工具 | `059df9c0…1993`，1,200,683 B，89 页，Acrobat PDFMaker 17 Word 版 | 本次 `md5 -q`、`pdfinfo`；三份副本 md5 相同 | ✓ |
| 获取日期 | 2026-11-05 | verify/provinces.md 第 11–12 行（访问/下载 2026-11-05） | ✓ |
| 元数据说明 | Title「Medical NOte」/ Author「Intergen Administrator」为模板残留 | `pdfinfo`；[provinces-12] 修正 1 | ✓ |
| 页码 ↔ layout 行号表（§3） | 2–72 → 3–2195；73–84 → 2196–2568；85 → 2569–2601；86–87 → 2602–2686；88 → 2687–2718；89 → 2719–2759 | `\f` 位于第 3, 34, …, 2173, 2196, 2228, …, 2543, 2569, 2602, 2645, 2687, 2719（末尾第 2760 行是文件结尾的 `\f`）；节标题行 3/2196/2569/2602/2687/2702/2749 | ✓ |
| §4.1.2 页首行分类 | 57 页 `\f`+词头、12 页 `\f`+续行（4、14、21、23、27、36、39、43、47、61、63、70）、PDF 52 首行为 R、PDF 2 首行为节标题 | `pages.tsv` 的 `first_line_is_continuation`=1 共 14 页 = 上述 12 + {2, 52}；layout 1553 为 `R`（第 52 页首行） | ✓ |
| §5 `being, been)` 唯一缩进非词性续行 | 第 162 行 | `diag.txt`；位置法也无其他可疑行 | ✓ |
| 外部口径 1733/335、1719 | 引 [shanghai-secondary-5]、[list-sources-27] | verify/shanghai-secondary.md 第 32 行；facts/list-sources.md 第 187 行 | ✓（均为转述，作者已注明） |
| 统一格式 | 每文件 `#` 注释头含来源/URL/本地路径+md5/日期/规则/计数；UTF-8、LF、无 BOM | §2 | ✓ |
| 「同名 .README.md」 | 五个文件共用一份 `shmeea-2020-junior.README.md`，各文件头以「说明文档：…」指向它 | 统一格式允许「同名 .README.md 或 data/lists/README.md 一节」，此处是折中 | 可接受（P7） |

### 6. 问题清单（逐条，含依据与建议修正）

**P1（数据，必修）`-forms.tsv` 漏收 `burn` 与 `dream` 的不规则变化。**
依据：layout 第 264 行 `burn (burned, burned 或 burnt, burnt)  v.`（PDF 第 10 页，p-10.png）、第 554 行 `dream (dreamt, dreamt 或 dreamed, dreamed)  n. & v.`（PDF 第 19 页，p-19.png）；`out/special.tsv` 第 18、36 行记录了这两处括号被「drop:zh-explanation」从词头去掉，但 `forms.tsv` 中 `grep '^burn\|^dream'` 为空。原因在 `parse.py` 的 `classify_form`：`INFL = ^[a-z]+(?:\s*[,，/；;]\s*(?:或\s*)?[a-z]+)+$` 只接受「分隔符后可跟 或」，不接受「空格+或+空格」单独作分隔（`burned 或 burnt`），于是返回 `None` 被丢弃。对全部 2,192 行单词区做括号扫描，含拉丁字母而不在 `forms.tsv` 的括号只有 10 个，其余 8 个（`100 cents = 1 dollar`、`=human being`、`should/would like`、`to`、`who 的宾格`、`will 的过去式`、`用于 have got 短语中`、`后接不带 to 的…`）按 README 规则确应排除，所以漏收仅此 2 条。
后果：README §4.1.4「去掉的内容全部进 `-forms.tsv`」、§4.4/§6/注释头「irregular-forms 93」「144 行」、作者自报 `forms_rows 144`/`forms_irregular_verbs 93` 均不成立。
修正：在 `bund (the Bund)` 与 `buy` 之间加 `burn\tirregular-forms\tburned, burned 或 burnt, burnt\theadword-line`；在 `draw` 与 `drink` 之间加 `dream\tirregular-forms\tdreamt, dreamt 或 dreamed, dreamed\theadword-line`；注释头与 README 计数改为 146 行、irregular-forms 95（若同时做 P2 则 94）；`parse.py` 的 `INFL` 改为接受 `\s+或\s+` 作为分隔，或更稳妥地：凡 `extract_head` 判为 `drop:inflections`/`drop:zh-explanation` 且括号内含 ≥ 2 个英文词形的，一律写入 forms。

**P2（数据，建议修）`much\tirregular-forms\tmore, most` 的 kind 应为 `comparison`。**
依据：layout 第 1236 行 `much (more, most)  adj.`（p-41.png），`more, most` 是 much 的比较级/最高级，与同页 `more(much 或 many 的比较级)`、`most (much 或 many 的最高级)` 及 `many (比较级 more，最高级 most)` 同类，后三者都标了 `comparison`。`INFL` 正则把它当成动词不规则变化是误判。修正后 comparison 11、irregular-forms 94（含 P1 的 2 条）。

**P3（文档，必修）README §7.4 第一条「对方少 33 条，全部是含 `/` 或 `(` 的行」不实。**
依据见 §4 第 4 点：8 条是不含 `/`、`(` 的页首 `\f` 行，3 条兼有两种原因，22 条才是纯因 `/`、`(`。建议改为：「对方少 33 条：22 条含 `/` 或 `(`（其正则不接受这两个字符），11 条是以 `\f` 开头的页首词组行（其中 3 条也含 `/` 或 `(`）；另有 7 条被截断」。

**P4（文档，轻微）README §8.3「`can’t = can not` 也在 `can` 一行；本表不新增词头，信息保留在 `-forms.tsv`（`past-form`）」。**
`-forms.tsv` 中 `can` 只有 `past-form could`（layout 289 `can (could) can’t = can not  aux. v.`），`can’t = can not` 这条信息没有保留在任何产出文件里（`special.tsv` 里有，但那是 scratchpad）。建议改措辞为「`could` 保留在 `-forms.tsv`，`can’t = can not` 只见于 `out/special.tsv`」，或加一行 `can\talt-form\tcan’t = can not\theadword-line`（需在注释头说明 alt-form 也含缩约形式）。

**P5（文档，轻微）README §8.4「（32 行非纯小写字母，见各文件注释头和 `out/special.tsv`）」。**
`out/special.tsv` 有 162 行（所有词头零件里有括号/并列/大写的行，含 130 行去括号记录），32 是其中第 3 列仍非纯小写者（与 §2 复核一致）。建议写成「`out/special.tsv` 162 行中 kept 列非纯小写的 32 行」。

**P6（文档，轻微）`maths\tfull-form\t=mathematics，美 math` 同时含美式拼写信息，但 README §4.4 的 us-spelling 12 条未计 `math`。**
layout 1168 `maths (=mathematics，美 math)`。一行两类信息，现行单 kind 列放不下；建议在 README §4.4 注明「`maths` 的括号兼含全称与美式拼写，只标 full-form」，或拆成两行（full-form `=mathematics` + us-spelling `美 math`，计数随之 147）。

**P7（格式，轻微）五个文件共用一份 README。** 统一格式要求「每个产出文件旁边写同名 `.README.md`（或在 `data/lists/README.md` 里加一节）」；现状是分组 README + 各文件头指向它，`-phrases.txt`/`-appendix.tsv`/`-forms.tsv` 没有同名 README 也没有 `data/lists/README.md`。内容上 §2、§4.2–4.4 已覆盖每个文件，可接受；建议在后续建立 `data/lists/README.md` 索引时加一节指向本 README，或把本 README 的 §2 表复制为该索引的一节。

**P8（自报计数）** `forms_rows 144 → 146`、`forms_irregular_verbs 93 → 95`（P2 后为 94，另 `comparison 10 → 11`）。其余自报计数（`words_lines 1724`、`words_split_tokens 1732`、`words_unique_ci 1731`、`phrases 342`、`appendix_rows 158` 及各节、`pdf_pages 89`、`word_pages 71`、`phrase_pages 12`、`special_headword_lines 32`、四组 diff 计数、`diff_vs_phrases_txt_309_missing 33`）全部复现。

#### 核对过、不构成问题的点（供种子阶段参考）

- 正文确无 `a`/`an`/`the`，人称/物主/反身代词只在附表（p-02.png、p-85.png，`grep` 亦无）；`could`/`might` 只以括号形式出现；`should`/`would` 为独立词头（layout 1729、2174）。README §8.1–8.3 的存疑描述准确。
- `behavior`（layout 180，p-07.png）是原件的美式拼写，产出照录正确；`hot-dog`（928）、`ice-cream`（952）原件带连字符。
- 词组 `take an underground`（2516）、`lose temper`（2431）、`huge amounts of`（2370）、`once every four years`（2463）、`big deal`（2270）、`tour guide`（2545）看似可疑，均为原件原文。
- `would (will 的过去式)`、`whom (who 的宾格)` 的括号在释义内，按 README §4.4 规则不收，与 `should (shall 的过去时态)`（括号在词性前，收为 past-form）处理不同，是规则位置依赖所致，README 已写明规则，不算错。
- `underground n. (美 subway)` 标 `us-spelling` 为近似标签，README §4.4/§8.7 已自报。
- `A.M. (a.m.)`、`P.M. (p.m.)`、`bund (the Bund)` 等 10 条括号变体与 5 条 `/`、3 条 `=` 并列保留原貌，符合统一格式「保持原文词形、不拆并列」，拆分留给种子阶段。

### 7. 建议修正汇总（具体到文件/动作/词）

| 文件 | 动作 | 内容 |
|---|---|---|
| `data/lists/shmeea-2020-junior-forms.tsv` | add | `burn\tirregular-forms\tburned, burned 或 burnt, burnt\theadword-line`（插在 `bund (the Bund)` 行后） |
| `data/lists/shmeea-2020-junior-forms.tsv` | add | `dream\tirregular-forms\tdreamt, dreamt 或 dreamed, dreamed\theadword-line`（插在 `draw` 行后） |
| `data/lists/shmeea-2020-junior-forms.tsv` | replace | `much\tirregular-forms\tmore, most\theadword-line` → `much\tcomparison\tmore, most\theadword-line` |
| `data/lists/shmeea-2020-junior-forms.tsv` | replace | 注释头 `# 计数：144 行：alt-form 7；comparison 10；irregular-forms 93；…` → `146 行：alt-form 7；comparison 11；irregular-forms 94；past-form 5；us-spelling 12；plural 12；full-form 4；uk-spelling 1` |
| `data/lists/shmeea-2020-junior.README.md` | replace | §2 表 `144` → `146`；§4.1.4「（93 条动词）」→「（95 条）」；§4.4 `irregular-forms 93`→`94`、`comparison 10`→`11`，并补「`burn`、`dream` 的括号以「或」分隔两套变化」；§6 表「词形信息 144」→「146」 |
| `data/lists/shmeea-2020-junior.README.md` | replace | §7.4 第一条按 P3 改写（22 条 `/`、`(` + 11 条页首 `\f` 行，其中 3 条重叠；另 7 条截断） |
| `data/lists/shmeea-2020-junior.README.md` | replace | §8.3 按 P4、§8.4 按 P5 改措辞；§4.4 按 P6 加一句 `maths` 说明 |
| `scratchpad/lists-shmeea/parse.py` | replace | `INFL` 增加 `\s+或\s+` 分隔；或对 `drop:inflections`/`drop:zh-explanation` 且含 ≥2 英文词形的括号一律写入 forms；修复后重跑 `parse.py` + `emit.py` 使注释头计数自动更新，并复跑本报告 §2 的结构检查 |

### 8. 声明

本次核验没有改动 `data/lists/` 下任何文件，也没有改动仓库其他文件；唯一写入的仓库文件是本报告。核验脚本与渲染图像在 `scratchpad/verify-lists-shmeea/`（`my-layout.txt`、`bbox.html`、`bbox_heads.py`、`my-words.txt`、`my-phrases.txt`、`img/p-NN.png`），全部用 `python3 -I`（Homebrew python3.12）运行、以参数传路径，未执行任何下载来的代码，未联网，未触碰 `/Users/sqin/word-dance-data`。
