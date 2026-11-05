# data/lists — 官方词表（词头清单）与构建器元数据

本目录是种子构建器（`backend/wd/seedbuild/`，`make seed`）的输入：11 个只含**词头**的官方词表文件、三份解析说明、一份版本差异，
以及四个构建器元数据文件（`manifest.json`、`aliases.tsv`、`overrides.tsv`、`SHA256SUMS`）。阶段成员的集合代数、12 条归一化规则与令牌表见
`docs/analysis/2026-11-05-stages-regions-images/design/PLAN.md` §4；阶段顺序与阶段中文名只在 `backend/wd/schemas.py`（`STAGE_ORDER` /
`STAGE_NAMES_ZH`），本目录任何文件都不重复它们。

## 1 索引

| 文件 | 内容 | 说明文档 |
|---|---|---|
| `moe-2022-level2.txt` · `moe-2022-level3.txt` · `moe-2022-appendix.tsv` | 《义务教育英语课程标准（2022 年版）》附录 3 二级词汇表、三级词汇表（含二级）、附表 | [`moe-2022.README.md`](moe-2022.README.md) |
| `shmeea-2020-junior.txt` · `shmeea-2020-junior-phrases.txt` · `shmeea-2020-junior-appendix.tsv` · `shmeea-2020-junior-forms.tsv` | 上海市教育考试院《2020 年上海市初中英语课程终结性评价指南》词汇表：单词、词组、附表、词条括号内词形信息 | [`shmeea-2020-junior.README.md`](shmeea-2020-junior.README.md) |
| `moe-2020-senior.tsv` · `moe-2020-senior-appendix.tsv` · `moe-2025rev-senior.tsv` · `moe-2025rev-senior-appendix.tsv` | 《普通高中英语课程标准（2017 年版 2020 年修订）》与《…日常修订版（2017 年版 2025 年修订）》附录 2 词汇表主表与国家名称附表 | [`moe-senior.README.md`](moe-senior.README.md) |
| `moe-senior-2020-vs-2025.diff.txt` | 2025 修订版相对 2020 版的 + 新增 / - 删除 / ~ 星级变化 / ≈ 词形改写 | 同上 §8 |
| `manifest.json` | `format: 2`；每个词表的 `id`（= `words.sources` 令牌前缀）、`file`、`format`（`heads` / `tsv` / `phrases`）、`policy`（`main` 缺词头即失败 · `appendix` 缺则警告跳过 · `phrases` 按 R9 展开 · `reference` 只校验行数与 sha256）、`stages`、`expect_rows`、TSV 的 `columns` 与 `groups`、高中表的 `level_token`、`provisional`；`inherit_stages`（be/have/do 的人称形式继承清单）、`ecdict_member_tags`、可选的 `external` CET 四表 | PLAN §4.1、WL SYNTHESIS §3.2.2 |
| `aliases.tsv` | 6 行 `spelling<TAB>canonical<TAB>note`：官方书写 → 库内 lemma（`Mr`→`mr.`、`PE`→`p.e.`、`hot-dog`→`hot dog`、`humourous`→`humorous`…）；只作用于官方词头与变体，从不改写上一版种子已有的 lemma；导入时写 `word_forms(kind='alias')` | PLAN §4.3 R5 |
| `overrides.tsv` | 28 行 `lemma<TAB>field<TAB>value<TAB>note`，`field ∈ translation \| word \| phonetic \| definition \| drop`，上限 30 条：修正 ECDICT 错义项（`bund`、`mum`、`p.e.`、`ai`、`bce`、`stuck`、`am`、`is`、`download`…）、改 display（`e-mail`、`am`、`Mrs.`）、丢弃重复项（`the bund`） | PLAN §4.1、WL SYNTHESIS §3.2.4 |
| `SHA256SUMS` | 11 个词表文件的 `shasum -a 256` 校验和（不含说明文档与元数据自身）；构建器加载 manifest 时校验，`cd data/lists && shasum -a 256 -c SHA256SUMS` 手工校验 | PLAN §4.1 |

## 2 来源与对账（provenance）

详情（页码、版式、逐词核对、与早期解析的差异裁决、存疑条目）在三份说明文档里；本表只汇总构建器关心的事实。`expect_rows` = 非注释行数（与每个文件头的
`# 计数` 相同）；拆并列、括注变体后的成员数由 `data/seed/stats.json.lists[].members` 给出。

| manifest `id` | 文件 | 原件 | 官方/发布 URL | 原件校验值 | 获取日期 | 解析规则（摘要） | `expect_rows` | 对账结论 |
|---|---|---|---|---|---|---|---|---|
| `moe22:l2` | `moe-2022-level2.txt` | 教育部《义务教育英语课程标准（2022 年版）》PDF（教材〔2022〕2 号附件，纯扫描无文字层），附录 3 二级词汇表，PDF 95–104 页 = 印刷页 88–97 | `http://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220420582349487953.pdf`（通知页 `…/t20220420_619921.html`） | md5 `2806e276f3486f4bb581d1a0153ef337`，sha256 `59ec3971…222fb` | 2026-11-05 | 渲染图逐词目视转录，与社区 docx 转录件逐词对账；保留原文拼写/大小写/括注、`a/an` 无空格斜杠、`(= x` 写作 `(=x` | 505 | 505 = 官方「收录 505 个单词」；每页计数、字母序断点 0 处 |
| `moe22:l3` | `moe-2022-level3.txt` | 同上，三级词汇表，PDF 105–135 页 = 印刷页 98–128 | 同上 | 同上 | 2026-11-05 | 同上；二级词右上角 `*` 已去（带 `*` 的 505 条与 level2 逐字逐序相同） | 1600 | 1600 = 官方「共收录 1600 个单词，含二级 505 个」 |
| `moe22:app` | `moe-2022-appendix.tsv` | 同上，附表（数词、月份星期、地理名称、缩写、节日/地名景点/其他专有名词、不规则动词），PDF 135 下–144 = 印刷页 128–137 | 同上 | 同上 | 2026-11-05 | 4 列 `类别/词/附加1/附加2`；保留原文消歧注 `hang (悬挂)`、`lie (躺)`；弯引号 → `'`；`/` 可选形式 | 267 | 267 = 30+28+12+7+27+18+7+13+8+11+106；不规则动词 106 行与 docx 表一一对应 |
| `shmeea20` | `shmeea-2020-junior.txt` | 上海市教育考试院 `07.pdf`「2020 年上海市初中英语课程终结性评价指南词汇表」（Word 转出，有文字层），单词正文 PDF 2–72 页 | `https://www.shmeea.edu.cn/page/08000/20190926/13309.html`（附件 `http://www.shmeea.edu.cn/download/20190926/07.pdf`） | md5 `059df9c02684bd989fff6f8849ee1993`（与 mahavivo 转载件逐字节相同） | 2026-11-05 | `pdftotext -layout`，顶格行 = 词头行；词头 = 行首到第一个词性标记/中文前的文本；保留词形、大小写、句点、并列 `/` `=`；`a/an/the` 不在正文 | 1724 | 与 PDF 词条一一对应；89 页全页图像核对；外部口径「1733 个单词」为转述、未证实 |
| `shmeea20:phr` | `shmeea-2020-junior-phrases.txt` | 同上，词组（Phrases and Expressions）PDF 73–84 页 | 同上 | 同上 | 2026-11-05 | 词组 = 行首到第一个中文/省略号前；保留英文括号与 `/` 并列；括号内外空格规范为 `(of)`、`at/in`；弯引号 → `'` | 342 | 无重复；外部口径「335 个词组」之差未能解释（README §8） |
| `shmeea20:app` | `shmeea-2020-junior-appendix.tsv` | 同上，附表 PDF 85–89 页（代词、数词、月份星期、国家/大洲与国籍、学科） | 同上 | 同上 | 2026-11-05 | 3 列 `word/section/note`；保留 `Math(s)`、`one hundred (and) one` 原文词形 | 158 | 158 = 12+7+7+8+39+33+7+12+13+14+6 |
| `shmeea20:forms` | `shmeea-2020-junior-forms.tsv` | 同上，单词正文词条括号内的词形信息（原文照录） | 同上 | 同上 | 2026-11-05 | 4 列 `headword/kind/printed/where`；只存档（`policy: reference`），是 R2 文法测试的样例来源 | 146 | `irregular-forms` 94 行 = 93 个动词 |
| `hs20` | `moe-2020-senior.tsv` | 教育部《普通高中英语课程标准（2017 年版 2020 年修订）》PDF（教材〔2020〕3 号附件 zip 内，有文字层），附录 2 主表，PDF 129–184 页 = 印刷页 121–176 | `http://www.moe.gov.cn/srcsite/A26/s8001/202006/W020200603315372317586.zip`（通知页 `…/t20200603_462199.html`） | PDF md5 `2398e9465bac25444a30db7f07a025cc`（zip `42762e0d75efede84e96375deb19c333`） | 2026-11-05 | `pdftotext -bbox-layout` 按坐标分栏排序；剥离词尾 `*`/`**` 为 `level` 0/1/2；合并跨行词条；保留括号变体与并列、大小写、缩写句点 | 3000 | 3000 = 官方 1500+500+1000（无星 1500 一致；一星/两星各差 1，原文印刷所致） |
| `hs20:app` | `moe-2020-senior-appendix.tsv` | 同上，「主要国家名称及相关信息（供教学参考）」PDF 184–186 页 | 同上 | 同上 | 2026-11-05 | 4 列 `country_zh/country/person/adjective`；只存档，不授予成员（PLAN R-5） | 55 | — |
| `hs25` | `moe-2025rev-senior.tsv` | 《普通高中英语课程标准 日常修订版（2017 年版 2025 年修订）》PDF，**非官方镜像**（freemdict 论坛上传，178 页），附录 2 主表 PDF 76–132 页 = 印刷页 73–129 | `https://forum.freemdict.com/uploads/short-url/doVmJXenSoIbcg8t5HA0hkWcccm.pdf` | md5 `77e8f0d793808e59c18dc89fa5f169d6` | 2026-11-05 | 同 `hs20`；`humourous`（第 1401 行）为镜像原文拼写，经 `aliases.tsv` 归到 `humorous` | 3099 | 官方说明 3100 = 1600+500+1000，镜像少 1（独立提取同为 3099）；`provisional: true`——学界已采用、印发文号未见 |
| `hs25:app` | `moe-2025rev-senior-appendix.tsv` | 同上，「部分国家名称及相关信息（供教学参考）」PDF 133–135 页 | 同上 | 同上 | 2026-11-05 | 同 `hs20:app`；「阿根廷」缺字已按页面图像补正 | 56 | 比 2020 版多「沙特阿拉伯」一行 |

## 3 许可与使用范围

- 国家课程标准与上海市教育考试院的词汇表是政府机关 / 事业单位发布的考试文件，**原件未声明许可**；《中华人民共和国著作权法》第五条（官方文件不适用著作权法保护）是否覆盖课标附录的词汇表**未经法律核实**（`docs/analysis/2026-11-05-stages-regions-images/INDEX.md` C4）。
- 本仓库据此只收录**词头清单**（接近事实数据：词形、并列、括注变体、星级），**不收录**原件的释义、词性标注、例句、版式与说明文字；释义、音标、词频、词形变化全部来自 ECDICT（MIT，`data/licenses/ECDICT-LICENSE`，`ATTRIBUTION.md` §1）。
- 2025 修订版高中词表来自非官方镜像，标为 `provisional: true`（学界已采用、印发文号未见；`moe-senior.README.md` §2）；它只影响 README / `data/seed/ATTRIBUTION.md` 的措辞，不影响成员判定。
- `overrides.tsv` 的 ≤ 30 条人工释义是本仓库自己撰写的文本，随仓库以 MIT 许可发布。
- 两份高中国家名称附表与上海词形信息表只存档（`policy: reference`），不产生成员；mahavivo 的 CET 四表是可选输入（`manifest.external`），不随仓库分发。

## 4 行格式（构建器的输入契约）

- 全部 UTF-8 无 BOM、LF 行尾；`#` 开头的整行是注释（文件头的来源注释与 TSV 的 `# 列名` 表头都靠这一条共存）；空行忽略。
- `.txt`（`format: heads` / `phrases`）：一行一个词头或词组，**原件记法**：并列 `a/an`、`exam=examination`；括注 `colour (AmE color)`、`be (am, is, are)`、`child (pl. children)`、`PE (=physical education)`；紧贴的可选后缀 `manner(s)`、`toward(s)`；词组的可选括号 `a bit (of)`、`catch (a) cold` 与 token 级并列 `at first/last`、`by bus/train/plane`；模板 `agree with sb.`、`add...to`。
- `.tsv`（`format: tsv`）：列由 `manifest.json` 的 `columns` 声明，**没有非注释表头行**；附加列为空时以 TAB 占位（行可以 TAB 结尾）；高中表 `level` 为 `0/1/2`（无星 / `*` / `**`）。
- 词头列不得含中文释义、音标或词性；唯一例外是 2022 附表「不规则动词」组的消歧注 `hang (悬挂)`、`lie (躺)`——该组 `member: false`，在成员判定之前即被丢弃。
- 已交付的 11 个词表文件与三份说明、一份差异文件**一字不改**（文件名、头注释、括注/斜杠/等号写法与 TSV 列都是构建器的输入契约）；修正原件转录请改文件并同步 `SHA256SUMS`、`expect_rows` 与对应 README 的核验修正章节。
- 归一化（R1–R12）的实现与逐规则测试：`backend/wd/seedbuild/normalise.py`、`backend/tests/unit/test_seedbuild_normalise.py`；迷你夹具 `backend/tests/fixtures/lists/`。

## 5 构建（`make seed`；构建器 `backend/wd/seedbuild/`）

```
make seed [ECDICT_DB=<stardict.db>] [WORDLISTS_DIR=<mahavivo 目录>] [SEED_BASE=<git 版本，默认 HEAD>]
#  prev = git show $(SEED_BASE):data/seed/vocab.jsonl.gz   （临时文件；基线永远是已提交的种子，不是工作区里会被 pack_seed.sh 替换的 .gz）
#  → .venv/bin/python -I scripts/build_seed.py --manifest data/lists/manifest.json --previous $prev [--ecdict …] [--wordlists …] --out data/seed
#  → .venv/bin/python -I scripts/seed_diff.py $prev data/seed/vocab.jsonl --md data/seed/DIFF.md --old-label $(SEED_BASE):data/seed/vocab.jsonl.gz --new-label data/seed/vocab.jsonl.gz
#  → scripts/pack_seed.sh   （gzip -9 -n；校验记录数与 stats.json.content_sha256）
```

- 输入只有三样：本目录（manifest + 11 个词表 + `aliases.tsv` + `overrides.tsv`，由 `SHA256SUMS` 与 `expect_rows` 钉住）、上一版种子（`--previous`；`make seed` 取 `git show $(SEED_BASE):data/seed/vocab.jsonl.gz`、默认 HEAD，即上一次**提交**的种子；其中每个 lemma 都保留——构建是对上一版的**重标**，从不删行）、ECDICT `stardict.db`（只在词表带来上一版没有的词头时需要；`deploy/fetch_ecdict.sh` 下载，851 MB，不入库）。mahavivo 的 CET 四表可选（`manifest.external`），缺席时现有行保留上一版的 CET 旗标与 `cet4/cet6/cet46` 令牌、新行取 ECDICT 的 `cet4/cet6` 标签（`stats.external_lists = absent`）。
- 流程（PLAN §4.5）：校验 manifest → 读上一版 → 每行过 R1–R12（`normalise.py`）→ 成员集合代数（PLAN §4.2：`xs = L2 ∪ APPxs ∪ 继承`、`zk = L3 ∪ APPzk ∪ SH ∪ SHP ∪ 继承`、`gk = HS ∪ 继承`）→ 构建期断言（`xs ⊆ zk`、阶段码 ∈ `schemas.STAGE_ORDER`、宇宙 ⊇ 上一版 lemma、`policy: main` 词头全部解析到 ECDICT ∪ 上一版、新行译文首行非空；任一失败 exit 2、不写输出）→ 生成记录（旧 lemma 的词典字段逐字复制，只改 `stages/sources/aliases/variant_of`；新 lemma 取 ECDICT；再套 `overrides.tsv`；新行译文去 `[网络] ` 前缀）→ 按 `(stage_min, lemma)` 排序写出。
- 产物（`data/seed/`）：`vocab.jsonl`（中间件，gitignored；记录格式 v2，键序固定：`word, lemma, phonetic, translation, definition, pos, collins, oxford, exam_tags, bnc, frq, exchange, ecdict_id, cet6_star, stages, sources, [aliases], [variant_of], seed_v`）→ `vocab.jsonl.gz`（入库）、`stats.json`（v2：`content_sha256` = 解压内容的 sha256，即导入器写入 `kv.seed_version` 的值；`per_stage/first_stage` 键序 = `STAGE_ORDER`；`lists[<id>]` 每表 `rows/heads/variants/members/missing/skipped`（这里的 `variants` 是该表拆出的括注变体**关系**数）；顶层 `variants` 则是带 `variant_of` 的**记录**数——两处口径不同，引用时写明；`tokens`；`inherited`；`previous_sha256` = 基线（上一次提交的种子）解压内容的 sha256；`new_words` / `rows_changed_vs_previous` 都相对该基线；验收数字只从这里引用，不手填）、`ATTRIBUTION.md`（由 manifest 渲染）、`DIFF.md`（与 `git show HEAD:` 的上一版比较：计数、`stage_min` 迁移矩阵、逐词清单、值得人工看的条目、不变量）。
- 确定性：无时间戳（`--built-at` 只写进 `stats.json`）、集合全部排序、`ensure_ascii=False`、LF。同样输入两次构建字节相同；把上一次的产物当 `--previous` 再构建也得到相同字节（重标幂等）。`make seed` 仍然始终以**已提交**的种子（`git show $(SEED_BASE):…`，默认 HEAD）作 `--previous` 与 DIFF 基线，而不是工作区的 `.gz`：后者第一次运行后已被 `pack_seed.sh` 换成新种子，再拿它当基线会让 `stats.json` 变成自指（`previous_sha256 == content_sha256`、`new_words 0`、`rows_changed_vs_previous 0/0`，评审 S3b F1）。因此连跑两次不只 `content_sha256` 不变，`stats.json`、`ATTRIBUTION.md`、`DIFF.md` 也逐字节相同；`git show` 读不到该版本的种子时 exit 2、不打包。
- 调试：`--no-strict` 把词表内容类断言（主表缺词头 / 主表词头过不了 R12 / `xs ⊄ zk` / 新行空译文）降为警告并照常写出，便于排查转录问题；结构类校验（format、sha256、`expect_rows`、未知阶段码、retain、重复 lemma）始终失败。单元测试：`backend/tests/unit/test_seedbuild_build.py`、`test_seed_diff.py`（夹具 `backend/tests/fixtures/lists/`，迷你 ECDICT 与 53 条上一版记录）。
- 已知口径差异（2026-11-06 首次重建，与 PLAN §4.8 复算相比 +1 行）：上海词组展开得 334 条而非 333（token 级 `/` 展开多出 `be familiar to/with`、`get familiar with`、`go to the movies`，跨 token 并列 `a lot of/lots of`、`no longer/not...any longer` 展不出成员——见 S3a 评审 F8，待 PLAN 负责人决定是否给 `overrides.tsv` 加 `phrase` 字段）；`a (an)`（2020 高中表）使 `an` 多得 `hs20:0`；`weapon` 在两份高中表（★★）里，是 `gk` 而非课标外。
