# seed-pipeline — 种子（词典层）流水线事实，以及加入「小学」词表要改什么

基线：仓库 `/Users/sqin/word-dance`，`main @ 75df534`（2026-11-05 21:23 +0800）。`scripts/build_seed.py` 自 `99a26e3`（2026-10-14）、`backend/wd/seed.py` 自 `fa82106`（2026-10-14）之后没有再改动（`git log -1 -- <file>`），因此旧分析引用的行号仍然有效；下文所有行号都按 75df534 重新核对。

## 范围与方法

读过的仓库文件（只读）：`scripts/build_seed.py`（全部 223 行）、`scripts/pack_seed.sh`、`Makefile`（`seed` 目标，93–98 行）、`data/seed/stats.json`、`data/seed/ATTRIBUTION.md`、`data/licenses/ECDICT-LICENSE`（仅目录列表）、`backend/wd/seed.py`（全部 364 行）、`backend/wd/main.py`（`seed_check` 307–318）、`backend/wd/config.py`（seed_path 相关）、`deploy/fetch_ecdict.sh`、`deploy/install.sh`（141、146 行）、`backend/wd/migrations/0001_init.sql`（words / user_settings 表）、`backend/wd/schemas.py`（Stage 相关）、`backend/wd/services/{words,ecdict,bank,batches,screen}.py`（stage 硬编码处）、`backend/tests/fixtures/mini_seed.jsonl`、`backend/tests/unit/test_seed.py`、`docs/DESIGN.md` §3.2（193–209 行）、`docs/TASKS.md:168`、`docs/API.md`（stage 枚举处）、`frontend/src/api/types.ts`、`frontend/src/i18n/zh.ts`，以及旧分析 `docs/analysis/2026-11-04-library-curation/facts/seed-pipeline.txt`（32 条，逐条复核，见第六节）。

`data/seed/vocab.jsonl.gz`：`zcat` 看了前 5 条记录；`gzip -dc | wc -l` = 9162；`shasum -a 256` = `a68127812a43c47ff011828b7894b789ba0fcf69cc8e76f1ec6c2356e81a3336`。

线上库只读副本 `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/live-copy.db`：`sqlite3 -readonly "file:…?mode=ro"` 只查不改（SQL 见各条）。

下载（每个放在 `…/scratchpad/seed-pipeline/` 下独立空目录，只用 `python3 -I` 的脚本解析，脚本放在另一个目录 `scripts/`；没有执行、import 任何下载内容）：
- `dl-ecdict-readme/README.md`：ECDICT master 的 README（18,414 B）。
- `dl-gh-api/*.json`：api.github.com 元数据（ECDICT release 1.0.28 资产、ECDICT 仓库 tree/releases、mahavivo 仓库 contents/commits/license）。
- `dl-mahavivo/`：`小学英语大纲词汇.txt`（2,518 B，保存为 xiaoxue.txt）、`中考英语词汇表.txt`（86,765 B，zhongkao.txt）、`Highschool_edited.txt`（25,353 B）、`README.md`（2,089 B）、`上海市初中英语词汇表（2020年版）.pdf`（1,200,683 B，shanghai-junior-2020.pdf；用 `pdftotext -layout` 抽成 .txt 再用 python3 -I 解析——pdftotext 是解析器而非执行，但严格说超出了「只用 python3 -I」的字面要求，特此声明）。
- `dl-ecdict-csv/ecdict.csv`：ECDICT master 的基础版 CSV（66,009,548 B，sha256 `d1ecbdf9…843cc`）。
- `dl-zip-tail/tail2.bin`：`ecdict-sqlite-28.zip` 最后 65,132 字节（HTTP Range 请求），只为读取 zip 中央目录里的解压大小；**没有**下载 216 MB 整包，也没有下载 `stardict.7z`。

实验（只写临时目录）：用仓库自带 `.venv/bin/wd`（Python 3.12.16）在 `…/scratchpad/seed-pipeline/wd-scratch/` 建空库并导入真实种子计时；再导入一个 9 行的「最小记录」补充文件观察 upsert 行为；用 Apple gzip 重新压缩解出的 vocab.jsonl 比对 sha256；运行 `scripts/pack_seed.sh --check`（verify-only，不写文件）。

搜索：本任务的问题都能从一手文件（仓库、ECDICT README/CSV、GitHub API、mahavivo 原文件）回答，没有再用 WebSearch。

---

## 一、构建端 `scripts/build_seed.py`（问题 a）

**[seed-pipeline-1] 输入文件名与两种解析模式。** 事实，置信度高。
`build_seed.py:81-88` 固定读取 mahavivo 六个文件：`中考英语词汇表.txt`（rich）、`Highschool_edited.txt`（plain）、`CET4_edited.txt`（rich）、`CET6_edited.txt`（rich）、`CET_4+6_edited.txt`（plain）、`英语六级词汇（星标，1726）.txt`（plain）。解析规则 `build_seed.py:20-48`：
- 以 `utf-8-sig` 打开（23 行，吞掉 BOM；`中考英语词汇表.txt` 实测带 BOM）；空行和**长度为 1 的行**一律跳过（25-26 行，本意是跳过 "A" 这类分节标题）。
- plain：整行必须匹配 `PLAIN_RE = ^[A-Za-z][A-Za-z'\-\.]*(?: [A-Za-z][A-Za-z'\-\.]*){0,3}$`（15 行）——最多 4 个 token、只允许字母 `' - .`，不匹配就丢。
- rich：`RICH_RE`（16 行）取行首词头（可带 `(an)` 括注），然后 `POS_RE`（17 行）从尾部剥掉 `n. v. adj.` 等词性 token（38-41 行）。
- 词头按小写去重，保留首次出现的大小写（42-47 行）。
实测（`parse_list(…,"rich")` 跑 `中考英语词汇表.txt`）= 1887 个词头，与 `stats.json.syllabus_sizes.zk` 一致。

**[seed-pipeline-2] 单字母词在 plain 模式下会被当成分节标题丢掉。** 事实，置信度高。
`小学英语大纲词汇.txt` 里 `a`、`I` 各占一行，`parse_list(…,"plain")` 得到 439 个词头，而非空行有 441 行；被丢的恰是 `['a', 'I']`（`len(line) == 1`，`build_seed.py:25`）。它们今天仍在种子里是因为 ECDICT 把 `a`/`I` 打了 zk 标签且中考 rich 表写成 `a (an) […]`；若将来用 plain 格式的小学表决定「小学」成员，这两个词会**拿不到小学标记**，需要给这条过滤加白名单或改成只跳过大写单字母。

> **核验修正（INDEX §3 #6，2026-11-05）**：本条数字确认（非空行 441、`parse_list(…, "plain")` 得 439、被丢的正是 `a`、`I`）；裁定口径：小学 mahavivo 词表的 441 / 440 / 439 分别是「非空行数 / list-sources 多算一行 / 生产入库口径」，引用时以 439 为准，在库 429/439；线上 `a`/`i` 的 `sources` 均为 `cet4 ecdict zk`，依据 verify/seed-pipeline.md [seed-pipeline-2]、verify/list-sources.md [list-sources-5]。

**[seed-pipeline-3] 集合定义：ECDICT 标签 ∪ 大纲词头；不在 ECDICT 里的词头被丢弃并记录。** 事实，置信度高。
步骤 1（105-109 行）把 `stardict` 表中 `tag` 含 `zk/gk/cet4/cet6` 的**全部**行收进来（含多词条目如 `ice cream`、`the pacific ocean`，它们的 `sources` 只有 `ecdict`）。步骤 2（112-127 行）逐表查词头：`lookup()`（96-100 行）先 `word = ? collate nocase` 精确匹配，含空格时再试把空格换成连字符；查不到就 `missing[lst].append(w)` 并 `continue`（119-121 行）——**该词头不会进入种子**，只出现在 `stats.json.missing_from_ecdict`（当前只有 `cet46: ["instalation"]`，`stats.json:36-40`）。`CET_4+6` 表中不在 CET4 表的词归 cet6（128-142 行）。排序键 `(min(stage order), word.lower())`（150-151 行）。

**[seed-pipeline-4] 记录格式与 0 值处理。** 事实，置信度高。
`make_record`（180-198 行）产出 15 个字段：`word, phonetic, translation[], definition[], pos, collins, oxford, stages[], exam_tags[], bnc, frq, exchange{}, sources[], ecdict_id`，加上步骤 2 末尾写入的 `cet6_star`（145 行）。`bnc`/`frq` 为 0 或空时写 `null`（193-194 行 `int(frq) if frq else None`），因此线上库 `frq = 0` 的行数为 0（见 [30]）。`stages` 只保留 `("zk","gk","cet4","cet6")` 中出现的标签（191 行）；`exam_tags` 只保留 `ky/toefl/ielts/gre`（192 行）。`sources` 初值是 `["ecdict"]`（有任何 tag 时）或 `[]`（196 行）。`stats.json` 与 `ATTRIBUTION.md` 都由脚本生成（157-177 行；`ATTRIBUTION` 常量在 201-219 行），不是手写文件。

**[seed-pipeline-5] mahavivo 六个文件的来源与大小；仓库无许可证；另有一份小学表和上海初中表。** 事实，置信度高。
GitHub API（`/repos/mahavivo/english-wordlists/contents/`，访问 2026-11-05）给出大小：`中考英语词汇表.txt` 86,765 B；`Highschool_edited.txt` 25,353 B；`CET4_edited.txt` 198,810 B；`CET6_edited.txt` 177,864 B；`CET_4+6_edited.txt` 65,877 B；`英语六级词汇（星标，1726）.txt` 14,914 B。仓库 `license: null`，最近提交 `395cebd5 2022-01-30 "edit"`，`pushed_at 2024-05-11`，2,538 stars。其 README 只交代了 CET4（贵州大学 PDF）、CET4+6（《全国大学英语四、六级考试大纲》2016 版，cet.edu.cn）、台湾高中表、托福/GRE（2003 版金山词霸）、COCA/OALD 的来源，**对中考表、Highschool、小学表的来源一字未提**。同目录还有 `小学英语大纲词汇.txt`（2,518 B）和 `上海市初中英语词汇表（2020年版）.pdf`（1,200,683 B），现有流水线没有用到。

**[seed-pipeline-6] ECDICT 1.0.28 发布资产：zip 216,765,132 B，内含单个成员 `stardict.db` 851,288,064 B。** 事实，置信度高。
GitHub API `releases/tags/1.0.28`：发布于 2017-09-20，资产更新于 2018-05-20；`ecdict-sqlite-28.zip` size 216,765,132（≈206.7 MiB / 216.8 MB）。对该资产（302 → `release-assets.githubusercontent.com`，`accept-ranges: bytes`）做 Range 请求取最后 65,132 字节，解析 zip 中央目录：1 个条目 `stardict.db`，deflate，压缩 216,764,976 B，**解压 851,288,064 B（851.3 MB / 811.9 MiB）**。与 `deploy/fetch_ecdict.sh:3-4` 注释「216 MB」「851 MB」一致；脚本钉死的 `ECDICT_SHA256=ea01f76a…`（13 行）本次**未**重新校验（需整包下载）。仓库 `releases` 列表只有这一个 release；ECDICT 仓库本身 `pushed_at 2026-11-02`，MIT。

**[seed-pipeline-7] 「可复现 gzip」只在同一 gzip 实现下成立：这台 Mac 重压得到不同的 sha256。** 事实，置信度高。
`pack_seed.sh:6-7` 与 `Makefile:97` 依赖 `gzip -9 -n` 产生字节一致的归档。实测：`gzip -dc data/seed/vocab.jsonl.gz > vocab.jsonl`（9162 行，sha256 `3b3ed209…22243`），再用 Apple gzip 479.0.0.700.1 `gzip -9 -n -c` 重压 → sha256 `6841b7df…8aae`，与仓库 `a68127…3336` 不同（`cmp` 在第 11 字节即 deflate 流首字节分歧）。后果：在 Mac 上重打包即使内容完全不变，`kv.seed_version` 也会变化并触发一次「0 inserted, 0 updated」的重导入（无害，但多一条 `system_events`，且 `git diff` 会显示二进制变更）。原归档应是在 Linux GNU gzip 下生成的（推断，置信度中：无法从 Mac 验证 GNU gzip 的字节）。

**[seed-pipeline-8] 打包/下载脚本在 macOS 上不可用：`pack_seed.sh --check` 实测失败，`fetch_ecdict.sh` 会在 `df --output` 处失败。** 事实，置信度高。
`scripts/pack_seed.sh --check` 在本机输出 `zcat: can't stat: …vocab.jsonl.gz (…vocab.jsonl.gz.Z)`、`archive record count 0 != stats.json total_words 9162`，exit 1——BSD `zcat`（62、79、90 行；`Makefile:98` 同）是 compress 版，会给文件名追加 `.Z`；`stat -c %s`（90 行）也是 GNU 选项。（本机 macOS 26 自带 `/sbin/sha256sum`，所以 `sha256sum` 这一项反而不是问题。）`deploy/fetch_ecdict.sh:23` 的 `df --output=avail`（本机报 `unrecognized option`）、59 行 GNU 风格 `sed -i "s|…|…|"` 都不能在 BSD 工具下运行；45、48 行的 `python3 -m zipfile` 与 `sqlite3` 校验是可移植的。手工等价步骤：`curl -fL … ; shasum -a 256 … ; python3 -m zipfile -e …`。旧分析 #30 的结论因此细化：问题点是 `zcat`/`df`/`stat`/`sed -i`，而非 `sha256sum`。

---

## 二、导入端 `backend/wd/seed.py`（问题 b）

**[seed-pipeline-9] 必填字段只有 `word`（非空字符串）；其余全部可选。** 事实，置信度高。
`seed_row`（167-214 行）：`word` 不是 `str` 或去空白后为空 → 返回 None → 该记录计入 `skipped_records` 并记 warning（174-179、269-273 行）。`lemma = normalise_input(display).lemma`，严格归一化失败时退回 `normalise_lemma`（180-181 行，永不丢词）。其余字段都有缺省：`phonetic/pos → _text()` 空即 NULL，`translation/definition` 可给字符串或列表（`_lines`，142-152 行），数值走 `_int`（155-164 行，`""`/None → NULL，**0 保留为 0**），`stages` 缺省 `[]`，`exchange` 非映射即 `{}`，`cet6_star` 缺省 0。`test_seed.py:288-300` 覆盖了 `{"word":"x"}` 这类最小记录。实测把 `{"word": "Peter"}` 导入临时库：生成 `lemma=peter, display=Peter, kind=proper_noun, translation=NULL, source=seed, is_valid_english=1, safe_for_sharing=1`，stage 全 0、`stage_min NULL`。

**[seed-pipeline-10] 对已存在的 lemma，upsert 覆盖全部 20 个种子列——不是「只填空值」。** 事实，置信度高。
`_UPSERT_SQL`（72-82 行）：`ON CONFLICT(lemma) DO UPDATE SET <每个 SEED_COLUMNS> = excluded.<col>`（75-77 行），再强制 `source='seed', is_public=1, is_valid_english=1, safe_for_sharing=1, merged_into_word_id=NULL`；`WHERE` 子句（78-81 行）只是「有任一列不同才写」，避免无谓重写 `updated_at`。没有任何 `COALESCE`。实测补充文件里 `{"word":"ice cream","translation":["冰淇淋"],"stages":["xx","zk"]}` 导入后，线上原有的 ECDICT 音标/英释/`ecdict_id`/`sources` 全部变成 NULL，`translation` 变为单行「冰淇淋」。`--force`（359 行）的含义只是跳过「`kv.seed_version` 已等于文件 sha256 则直接返回」这一步（260-263 行），不改变 upsert 语义。

**[seed-pipeline-11] `stage_*` 与 `stage_min` 都是种子管理列，重导入会更新；未知 stage 码被静默丢弃。** 事实，置信度高。
`SEED_COLUMNS`（47-68 行）包含 `stage_zk/gk/cet4/cet6/stage_min`，所以一份把 430 个现有词标成「小学」的新种子**可以**通过重导入改写它们的 stage 列（无需 SQL）。但 `stages` 过滤只认 `STAGES = ("zk","gk","cet4","cet6")`（43、184-185 行）：实测 `{"word":"Kitty","stages":["xx"]}` 得到 4 个 flag 全 0、`stage_min NULL`，没有任何告警。`stage_min = STAGES.index(stages[0]) + 1`（208 行），`words.stage_min CHECK (BETWEEN 1 AND 4)`（`0001_init.sql:185`）。

**[seed-pipeline-12] lemma 冲突是小学词表的首要陷阱：`May`/`may`、`Mr`/`Mr.`、`ice-cream`/`ice cream`。** 事实（实验），置信度高。
lemma 是小写键（`ux_words_lemma` 唯一索引，`0001_init.sql:205`）。实测补充记录 `{"word":"May","translation":["n. 五月"],"stages":["xx"]}` 直接改写了情态动词 `may` 那一行：`display → May, kind → proper_noun, translation → n. 五月, phonetic/frq/bnc → NULL, stage_zk 1→0, stage_min 1→NULL`，`word_forms` 从 14,132 降到 14,127：被更新的 5 个现有 lemma（`may / p.e. / ice cream / ice-cream / schoolbag`）各有一条 `s` 复数词形（`mays / p.e.s / ice creams / ice-creams / schoolbags`），`_rebuild_forms` 先删后建，而补充记录没有 `exchange`，于是 5 条全部消失。同理 `ice-cream`（线上已有，`sources = cet4 cet46 ecdict gk zk`，`stage_min 1`）被补充记录覆盖成「冰淇淋（连字符写法）」，四个 stage 标志全部清零、`stage_min → NULL`。而 `Mr`（无点）归一化为 `mr`，与现有 `mr.`（`display Mr.`，sources `ecdict gk zk`）是**两个不同 lemma**，会产生重复词条；小学表里 `Mr/Mrs/Ms/PE` 都是这种情况（线上已有 `mr. / mrs. / ms. / p.e.`）。同一文件内重复 lemma 则「先到先得」（274-277 行；`test_seed.py:252-259`）——所以给现有词加小学标记必须**改原行**，追加一行无效。

**[seed-pipeline-13] 屈折形式不需要作为词头加入：已有 `word_forms` 解析。** 事实，置信度高。
小学表缺失的 10 个词里 `children/feet/has/men/women` 在线上 `word_forms` 中分别映射到 `child(s)/foot(s)/have(3)/man(s)/woman(s)`（另有 `has → ha(s)` 一条歧义行）。`_rebuild_forms`（218-245 行）只用 `p d i 3 s r t` 码（45 行），跳过空形式与「本身就是 lemma 的形式」（235-241 行）；本次真实导入报告「11 empty and 520 headword forms skipped」——注意 `0001_init.sql:215` 注释写的是「388 in the seed」，与实测 520 不一致（文档数字陈旧，低优先级）。

**[seed-pipeline-14] `kv.seed_version` 只存哈希不存路径：用 `--file` 导入补充文件后，下次 `wd serve` 会把仓库种子重新导入并覆盖回去。** 事实（实验），置信度高。
实测补充文件导入后 `kv.seed_version = 39edec96…`（= 补充文件 sha256），`system_events` 新增一行 `{"file":"supplement.jsonl","records":9,"inserted":3,"updated":5}`。`main.seed_check`（`main.py:307-318`）比较的是 `sha256(cfg.seed_path)`，不等即 `import_seed(conn, str(path))`——`may`/`ice cream`/`p.e.`/`ice-cream`/`schoolbag` 会被仓库种子改回，新 lemma `kitty/peter/mr` 因为「从不删除」而留下。结论同旧分析 #17：小学内容必须进入 `WD_SEED_PATH` 指向的那一个文件。

**[seed-pipeline-15] 导入时长：这台 Mac 上 0.2 s（9,162 条 + 14,132 词形）。** 事实，置信度高（硬件相关）。
`WD_DATA_DIR=<scratch> .venv/bin/wd migrate` 0.94 s 墙钟；`wd import-seed` 输出 `imported 9162 seed records …: 9162 inserted, 0 updated; 14132 word forms (11 empty and 520 headword forms skipped); 0.2 s`，`/usr/bin/time` 墙钟 0.55 s；第二次运行 `seed up to date`。`docs/TASKS.md:168` 的预算是「< 20 s」。线上库 `system_events` 记录 2026-11-02T07:36:59Z 的真实导入同为 9162/14132，`kv.seed_version = a68127…`。

**[seed-pipeline-16] ECDICT 里没有的词：构建端丢弃，导入端接受最小记录；但人名/缩写若恰好命中 ECDICT 会拿到错误义项。** 事实 + 推断，置信度高/中。
事实：构建端对 ECDICT 查不到的词头只记 `missing`（[3]）；导入端接受 `{"word": …, "translation": [...]}`（[9]）。在基础版 `ecdict.csv`（770,611 行）里按小写精确匹配探针：`Kitty → kitty "n. 小猫, 全部赌注"（frq 25372）`、`Peter → peter "vi. 逐渐消失"`、`Alice → ALICE "[计] 应用语言接口转换与扩充"`、`Sam → SAM "[计] 安全性帐户管理器"`、`PE → "[计] 相位编码"`、`Ms → MS "美国微软公司"`、`mum → "n. 菊花, 沉默"`；`Danny/eddie/joe` 有人名释义；`physical education` 有「[医] 体育」；`ice cream` 有（tag zk，frq 0）。推断：对课本人名、称谓缩写、PE 一类，用「词 + 中文释义」的最小手写记录比自动查 ECDICT 更可靠；并且 `derive_kind` 会把首字母大写词标为 `proper_noun`（`services/words.py:143-151`），种子导入又一律写 `safe_for_sharing=1`（`seed.py:74`），与 `0001_init.sql:194` 注释「Claude verdict (no personal names etc.)」的本意相冲突——这是产品决策点，不是 bug。

---

## 三、要把「小学」加进来，各处需改什么（问题 c）

**[seed-pipeline-17] `build_seed.py` 需改 7 处。** 事实（代码定位）+ 推断（改法），置信度高。
(1) 10-11 行 docstring 与 201-219 行 `ATTRIBUTION` 常量加小学表来源；(2) 81-88 行 `syllabus` 增加小学文件（若用 mahavivo 那份是 plain 模式，且要处理 [2] 的单字母问题）；(3) 112 行 `stage_from_list` 增加映射；(4) 147、150 行两处 `("zk","gk","cet4","cet6")`/`order` 元组加新码并决定顺序（见 [18]）；(5) 191 行 `make_record` 的 `stages` 过滤元组同步；(6) 105-106 行 ECDICT 标签查询**不必**改，因为 ECDICT 没有小学标签（[22]）；(7) 157-171 行统计自动跟随 `order`，但 `stats.json` 的 `per_stage/only_stage/first_stage` 会多出一个键。新码名需与 `seed.py`/`schemas.py` 一致（例如 `xx`，任何未在 `seed.py:43` 注册的码都会被 [11] 静默丢弃）。

**[seed-pipeline-18] `seed.py` 本身改动很小，真正的工作量在 schema CHECK 与编号。** 事实 + 推断，置信度高。
事实：`seed.py` 只需改 `STAGES`（43 行）、`SEED_COLUMNS`（47-68 行，加 `stage_xx`）、`seed_row` 的四个 flag（204-207 行，加一个）；`stage_min` 公式（208 行）自动随 `STAGES` 顺序变化。但 `words.stage_min CHECK (BETWEEN 1 AND 4)`（`0001_init.sql:185`）、`user_settings.current_stage CHECK (BETWEEN 1 AND 4)`（148 行）、`schemas.index_to_stage` 的 `1 <= index <= 4`（`schemas.py:62-65`）都写死了 4；SQLite 不能 ALTER CHECK，需要新迁移做整表重建（`0001_init.sql:33` 注释已写明该配方）。推断：若小学插在最前（索引 1，zk 变 2），迁移还要把已存 `words.stage_min` 与 `user_settings.current_stage` 全部 +1（否则老用户的「主攻阶段」会错位），`_STAGE_DISTANCE`（`batches.py:60`、`screen.py:34`）与「仅本阶段新增 = stage_min = idx」语义才能保持；若把小学追加为索引 5，可避免重编号，但 `stage_min = 最低阶段` 的排序语义会把小学当成最难阶段，`new_only` 与筛词顺序都会反直觉。两种方案都需要产品决定，本文不替代。

**[seed-pipeline-19] 其他硬编码 stage 枚举的位置（需同步）。** 事实，置信度高。
`backend/wd/schemas.py:25`（`Stage = Literal[...]`）、51-52（`STAGE_ORDER`、`STAGE_NAMES_ZH`）、488/708/1335（三个请求参数 Literal）；`services/words.py:39`（`STAGES`，`bank.py:181`、`batches.py:233`、`screen.py:46` 都用它过滤）；`services/ecdict.py:28,119,173-177`（运行时 ECDICT 查词也按 4 个标签算 stage）；`services/bank.py:85-86`（默认 `("cet4","cet6")`、`current_stage=3`）；前端 `frontend/src/api/types.ts:5`（`Stage` 类型，`// index 1..4`）及 `'zk'` 字面量共 10 处 / 6 个文件（StageChips、AdminPage、WelcomePage、VocabPage、SettingsPage.test、types），`i18n/zh.ts:25,28`（角色与阶段名）；契约文档 `docs/API.md:160,169,187,230,239`、`docs/DESIGN.md:193-209`；测试 `backend/tests/unit/test_seed.py:338-353`（钉死 9162/2099/3829/4722/7671 与 stage_min 分布）、`fixtures/mini_seed.jsonl`（60 条，每条 15 个键，无小学记录）。

**[seed-pipeline-20] `stats.json` 的消费者只有 `pack_seed.sh` 的 `total_words`。** 事实，置信度高。
`pack_seed.sh:44-47` 读取 `total_words`，52-57 行记录数不等即 exit 1；`grep -rn stats.json` 在后端代码中无命中，只有 `README.md:78`、根 `ATTRIBUTION.md:14`、`docs/DESIGN.md:149,205,209`、`docs/TASKS.md` 引用其数字。手工加词后至少改 `total_words`；若不用 `build_seed.py` 重建，`per_stage` 等统计需手工更新或接受过期。

**[seed-pipeline-21] 归属说明需改三处。** 事实，置信度高。
`data/seed/ATTRIBUTION.md` 由 `build_seed.py:201-219` 的常量生成（重建会覆盖手改）；根 `ATTRIBUTION.md:14` 写着「9,162 records」；前端 `frontend/src/i18n/zh.ts:86` 的「词表范围：中考、高考、大学英语四级与六级大纲」要加小学。mahavivo 仓库无许可证（[5]），现有做法是只使用「词头成员关系」且不再分发列表文件（`data/seed/ATTRIBUTION.md:12-13`）；小学表若来自上海牛津教材配套，版权状态需另行确认。

**[seed-pipeline-22] ECDICT 的 `tag` 没有小学标记：只有 8 个取值。** 事实，置信度高。
README（`dl-ecdict-readme/README.md:40`，访问 2026-11-05）：「| tag | 字符串标签：zk/中考，gk/高考，cet4/四级 等等标签，空格分割 |」。基础版 `ecdict.csv` 770,611 行中 14,942 行有 tag，token 频次：`gre 7504, toefl 6974, cet6 5407, ielts 5040, ky 4801, cet4 3849, gk 3677, zk 1603`；没有任何小学/primary 类标记。csv 中 1,603 个 zk 行**全部**已在线上种子里（差集为 0）。因此「小学」成员只能来自外部词表。

**[seed-pipeline-23] `frq`/`bnc` 可作排序依据但不是教学顺序。** 事实 + 推断，置信度高/中。
事实（live-copy.db）：mahavivo 小学表 439 个词头中 429 个在线上库，其中 422 个有 `frq`（缺 7 个：`an, are, colour, email, ice cream, is, schoolbag`），423 个有 `bnc`；`frq` 分位：min 1 / q25 168 / 中位 598 / q75 1609 / max 38684；相比整个 zk 集合（1,988 个有 frq）中位 1523、q90 6718。高 rank（即罕见）的小学词：`maths 38684, favourite 22274, bye 18387, panda 14691, grandpa 14478, mum 14080, blackboard 13322, crayon 12296, cloudy 10229`。`frq` 与 `bnc` 常不一致（`basketball` frq 1799 / bnc 16051；`favourite` frq 22274 / bnc 2527；`English` frq 1782 / bnc 18425）。应用现有排序键是 `(frq IS NULL OR frq = 0), frq, lemma`（`docs/API.md:169`、`batches.py:61`）。推断：对 6–10 岁学习者，英美成人语料词频把 `crayon/blackboard/panda` 排到最后、`be/and/the` 排最前，与课本单元顺序无关；frq 只宜作同一单元内的次级排序，首要顺序应来自词表自带的年级/单元字段（需要词表本身提供，mahavivo 那份没有）。

**[seed-pipeline-24] mahavivo `小学英语大纲词汇.txt`：439 词，基本是现有 zk 的子集，来源不明。** 事实，置信度高（来源：低）。
2,518 B，ASCII，按字母分组、空行分隔，441 个非空行；`parse_list(plain)` 439 个词头（丢 `a`、`I`，[2]），其中多词 `ice cream`、`physical education`，大写 `China Chinese English Miss Mr Mrs Ms PE TV`。与线上库按小写 lemma 对照：429 个已存在（423 个 `stage_zk=1`；6 个 `stage_zk=0` 且 `stage_min=2`（最低阶段为高中）：`an are color favorite maths mum`），10 个缺失：5 个屈折形式（[13]）、`Mr Mrs Ms`（无点写法，[12]）、`PE`、`physical education`（线上有 `p.e.`）。文件名的「大纲」与 441 行的规模不符合上海牛津 1A–5B 的量级（推断，无法核实），mahavivo README 也未说明出处——**不能把它当成上海小学词表使用**。

**[seed-pipeline-25] 旁证：mahavivo 的《上海市初中英语词汇表（2020年版）》与现用中考表只重合约三分之二，说明现有 zk 阶段不是上海口径。** 推断，置信度中（启发式解析）。
PDF 89 页（pdfinfo；元数据 Title "Medical NOte"、CreationDate 2019-09-30、Acrobat PDFMaker 17——第三方上传，真实性未验）。`pdftotext -layout` 后用「行首词头 + 剥词性」规则解析得 2,032 个词头：1,722 个单词、310 个短语（`a bit, be able to, as…as…`）。单词部分与 `中考英语词汇表.txt`（1,887）对照：交集 1,285、上海独有 437（`accurate, achieve, actor, attitude, available…`）、中考表独有 602（`aircraft, bamboo, baseball, camel…`）。与线上库：1,696 个单词已存在、26 个缺失（`angrily, beautifully, carefully, excited, frightened, surprised, satisfied, lost, united, bund, hot-dog, seafood, yogurt, mr, mrs…`），已存在但 `stage_zk=0` 的有 309 个（`stage_min` 2:236 / 3:59 / 4:14）；310 个短语只有 `according to` 在库中。这些数字取决于我的解析规则，只能说明量级；精确口径由 regions 任务负责。

---

## 四、这台 Mac 没有 `stardict.db`：重建种子的几条路（问题 d）

**[seed-pipeline-26] 走官方路径：下载 216,765,132 B，解压 851,288,064 B，期间需约 1.1 GB 空闲。** 事实，置信度高。
见 [6]；`fetch_ecdict.sh:14` `NEED_MB=1100`。脚本本身在 macOS 不能直接跑（[8]），但可手工 `curl -fL` + `shasum -a 256` 对照 13 行的钉死值 + `python3 -m zipfile -e`；`make seed` 之后的 `gzip -9 -n -k -f`（`Makefile:97`，Apple gzip 支持 `-k -n`，实测可用）会得到一个 sha256 与现有归档不同的文件（[7]），且 `Makefile:98` 的 `zcat` 会报错。`build_seed.py` 硬性要求 `--db`（74 行）并直接查 `stardict` 表（97、105 行），没有 `--db` 就无法运行。

**[seed-pipeline-27] 替代 A：用仓库里的基础版 `ecdict.csv`（66 MB）——对新增词查词可行，但不能原样复现现有种子。** 事实，置信度高。
`ecdict.csv` 66,009,548 B，770,611 行，列 `word,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange,detail,audio`；README 143 行：「最新版数据太大，我已经把数据库压缩成 stardict.7z 了，外面默认的 ecdict.csv 算是一个基础版本（76 万词条）」。与线上 9,162 条逐 lemma 比对（csv 多行同 lemma 取首个，译文/英释先把字面 `\n`/`\r\n` 还原为换行）：命中 9,154；其中 `frq/bnc/collins/oxford/definition` 9,154 全等，`phonetic`（经 `norm_phonetic`）9,148 等，`translation` 9,146 等（差异例：`arm` 线上多出「ARM 处理器」）；但 **`pos` 在 csv 中全部为空**（线上 8,834 条有值），`exchange` 有 2,024 条不同（csv 常缺 `s:` 复数项，如 `abandon` 缺 `s:abandons`），**`ecdict_id` 不可复现**（README 95 行：「CSV 里 id 为行号，其他两者是自增量」；`a` 在 csv 第 609 行而线上 `ecdict_id=7909`）。8 个种子词不在 csv 中：`babyboomer, celcius, honourary, microwavable, miss., sideroad, sobre, the pacific ocean`（其中 4 个正是旧分析 #27 指出的仅有 `[网络]` 释义的词）。`build_seed.py` 需要 SQLite 表，用 csv 要么先转成 `stardict` 表（ECDICT 自带 `stardict.py` 可转，但那是下载的代码；自写 20 行 csv→sqlite 也行），要么加一条 csv 查询路径。`stardict.7z`（51,577,449 B）本机无 7z 工具、Python 标准库不支持，内容未验证。

**[seed-pipeline-28] 替代 B：现有 9,162 条记录作为词典底座 + 小学补丁，是改动最小的路。** 事实 + 推断，置信度高。
事实：`import_seed` 只接受**一个**文件（248 行；`seed_check` 用 `cfg.seed_path`，`config.py:92,334`），没有多文件合并；同文件重复 lemma 先到先得（[12]）。因此做法只能是：`gzip -dc vocab.jsonl.gz` → 用脚本**就地修改**约 430 条现有记录的 `stages`（加小学码）→ **追加**不在库里的新词（最小记录或从 csv 取字段，[27]）→ 更新 `stats.json.total_words`（[20]）→ 在 Linux 上 `pack_seed.sh`（或接受 Mac 的不同哈希，[7]）→ 提交并重启服务（`seed_check` 自动导入）。实测 9 行补充文件导入 9,162 词的库：`3 inserted, 5 updated, 1 skipped, 0.0 s`，说明增量成本可忽略。推断：这条路不需要 ECDICT 下载，但新增词的 `phonetic/definition/frq` 要么留空（[9] 允许），要么从 csv 查（[27]）；留空的词在 `sort=freq` 下排最后（`API.md:169`）。

---

## 五、live-copy.db 的几个数字（问题 e）

**[seed-pipeline-29] zk 集合 2,099 词：`frq` 为空 111，`bnc` 为空 55，两者皆空 45。** 事实，置信度高。
`select count(*) from words where stage_zk=1 and frq is null` = 111；`… and bnc is null` = 55；`… and frq is null and bnc is null` = 45；`frq = 0` 为 0 行（构建端已把 0 转 NULL，[4]）。全部种子 `frq is null` = 354；`phonetic` 为空 165（zk 内 37）。线上 `words` 9,162 行全部 `source='seed'`（没有 `ecdict/claude/user` 来源的行）。

**[seed-pipeline-30] 多词短语 13 个（zk 内 7 个）。** 事实，置信度高。
`display like '% %'` = 13 = `kind='phrase'`：`Middle East, Olympic Games, according to, bean curd, buzz word, computer game, fruit juice, human being, ice cream, ought to, owing to, swimming pool, the pacific ocean`；zk 内 7 个：`Middle East, Olympic Games, computer game, fruit juice, ice cream, swimming pool, the pacific ocean`。与 `stats.json.multiword = 13` 一致。

**[seed-pipeline-31] 大写开头的词 141 个（zk 内 78 个）。** 事实，置信度高。
`substr(display,1,1) glob '[A-Z]'` = 141 = `display != lower(display)`（两种口径相同，即没有「仅内部含大写」的词），与 `stats.json.uppercase = 141` 一致；按 `kind` 拆分：proper_noun 119 + abbreviation 20（`TV`、`OK`、`U.S.A.`、`Mr.` 等）+ phrase 2（`Middle East`、`Olympic Games`）= 141；abbreviation 全库共 26 个，另 6 个是小写开头（`a.m. mrs. no. p.e. a.m i.e.`）。zk 内 78 个：国名/语言/月份/星期/`Mr. Ms. Miss.`/`CD-ROM`/`E-MAIL`/`T-shirt`/`I`（`I` 被 `derive_kind` 归为 `proper_noun`，是规则副作用）。小学词表的星期、月份、国名、人名会进一步放大这一类。

---

## 六、与旧分析（2026-11-04，基线 9ab13a5）的核对

- #2、#3、#5、#6、#10、#11、#13、#17、#19、#20、#21、#22、#26、#31 全部按 75df534 复核成立；`seed.py`/`build_seed.py` 未改，行号一致。
- #7「851 MB」本次用 zip 中央目录验证为 851,288,064 B（[6]）。
- #27 四个 `[网络]` 词：补充事实——它们不在基础版 csv 里，只在 1.0.28 的 SQLite 库里（[27]）。
- #30「GNU 工具」细化为 `zcat/df/stat/sed -i`，`sha256sum` 在本机存在（[8]）；并新增 [7] gzip 字节不可跨实现复现。
- 新增可验证事实：[12]（lemma 冲突实测）、[14]（kv 覆盖实测）、[15]（导入时长实测 0.2 s）、[22]（ECDICT 无小学标签）、[24]/[25]（两份 mahavivo 文件）。

## 未解决的问题

1. `小学英语大纲词汇.txt`（439 词）的出处与版本；是否存在可用的上海牛津 1A–5B 词表数据（mahavivo 没有；需要 regions/curation 任务或人工整理），以及它的版权状态。
2. 小学阶段编号：插在索引 1（需迁移重编号 `stage_min`/`current_stage`）还是追加索引 5（破坏「最低阶段」语义）——产品决策，见 [18]。
3. 课本人名/称谓（Kitty、Peter、Mr）是否应作为公开可信词进入共享词库（`safe_for_sharing=1`），以及与 `Mr.`/`may` 等现有 lemma 的合并策略（[12]、[16]）。
4. `fetch_ecdict.sh` 钉死的 sha256 未重新校验；`stardict.7z` 的内容、以及 1.0.28 SQLite 与 master csv 在种子以外词条上的差异未知。
5. GNU gzip 在 Linux 上是否仍能产出 `a68127…`（假设成立，Mac 上无法验证）；若以后在 Mac 打包，是否接受 `kv.seed_version` 随之变化。
6. 导入时长只在本机测得（0.2 s）；Lighthouse 东京实例未测（TASKS 预算 < 20 s，余量很大，风险低）。
7. 线上 `.env` 是否设置了 `WD_ECDICT_DB_PATH`（`words` 表没有 `source='ecdict'` 的行，说明运行时 ECDICT 查词从未创建过词条，但不能区分「未配置」与「没人加过生词」）。
8. 小学词表若自带年级/单元信息，种子格式里没有对应字段（15 个字段见 [4]）；要按单元排序需要新增字段并改 `seed.py`/schema，本文未评估。
