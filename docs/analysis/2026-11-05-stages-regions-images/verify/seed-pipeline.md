# verify/seed-pipeline — 对 facts/seed-pipeline.md 的对抗性核验

核验对象：`docs/analysis/2026-11-05-stages-regions-images/facts/seed-pipeline.md`（31 条结论）。基线 `main @ 75df534`（`git rev-parse HEAD` = 75df534c…，2026-11-05 21:23 +0800）；`git log -1 -- scripts/build_seed.py` = 99a26e3（2026-10-14），`-- backend/wd/seed.py` = fa82106（2026-10-14），与作者所述一致，行号基础成立。核验日期 2026-11-05。

## 范围与方法

- 重新打开并逐行核对的仓库文件（只读，`cat -n` / `sed -n` / `grep -n`）：`scripts/build_seed.py`、`backend/wd/seed.py`、`backend/wd/main.py:295-325`、`backend/wd/config.py`（seed_path / ecdict_db_path）、`backend/wd/migrations/0001_init.sql`（30-36、140-152、180-220 行）及 `migrations/` 目录、`backend/wd/schemas.py`、`backend/wd/services/{words,ecdict,bank,batches,screen,stats}.py`、`backend/wd/security.py:592-599`、`backend/wd/ai/{content,prewarm}.py`、`backend/wd/ai/prompts/content_system.txt`、`scripts/pack_seed.sh`、`Makefile:85-98`、`deploy/fetch_ecdict.sh`、`data/seed/{stats.json,ATTRIBUTION.md}`、根 `ATTRIBUTION.md`、`backend/tests/unit/test_seed.py`、`backend/tests/fixtures/mini_seed.jsonl`、`docs/{API,DESIGN,TASKS}.md`、`README.md`、`frontend/src/api/types.ts`、`frontend/src/i18n/zh.ts`、`frontend/src/pages/WelcomePage.tsx`、`frontend/src/components/word/StageChips.tsx`。全库 grep：`'zk'|"zk"`、`STAGES|STAGE_ORDER|_STAGE_DISTANCE`、`stage_min|current_stage`、`StageIndex`、`difficulty`、`初中|小学|高中`、`stats.json`。
- 自己重算：`sqlite3 -readonly "file:…/live-copy.db?mode=ro"`（只查）；`python3 -I` 脚本放在 `…/scratchpad/verify-seed-pipeline/scripts/`（`ghjson.py` 读作者保存的 GitHub API JSON 并解析 zip 尾部；`csvcheck.py`、`fieldcmp.py` 解析作者下载的 `ecdict.csv`；`lists.py` 用仓库自带 `build_seed.parse_list` 解析作者下载的 mahavivo 文件；`shparse.py` 独立启发式解析上海初中表）。所有下载数据只作为参数路径传入，解释器在脚本目录运行，未 import、未执行任何下载内容。
- 实验（只写 `…/scratchpad/verify-seed-pipeline/`）：`WD_DATA_DIR=…/wd-scratch .venv/bin/wd migrate && wd import-seed`，再导入 5 行补充文件并重导入仓库种子，观察 upsert/`kv.seed_version`/`word_forms`；`gzip -dc` + Apple gzip `-9 -n` 重压比对 sha256；在仓库根运行 `bash scripts/pack_seed.sh --check`（verify-only，不写文件，exit 1 已预期）。
- 复用作者下载：`seed-pipeline/dl-ecdict-csv/ecdict.csv`、`dl-ecdict-readme/README.md`、`dl-gh-api/*.json`、`dl-mahavivo/*`、`dl-zip-tail/tail2.bin`。我自己的下载（各自独立空目录）：`verify-seed-pipeline/dl-mahavivo-readme/README.md`（raw.githubusercontent.com，2,089 B）、`dl-mahavivo-xiaoxue/xiaoxue.txt`（2,518 B，sha256 `bb7581da…ce99` 与作者副本相同）、`dl-shpdf/sh.txt`（用 `pdftotext -layout` 从作者的 PDF 重新抽取，`cmp` 与作者的 .txt 字节相同）。对 `api.github.com` 的 5 次新请求全部 403「API rate limit exceeded」（未认证限额已被本机耗尽），因此 [5]/[6] 的 API 数字用作者保存的 JSON 核对，并用 `curl -sIL` 对 release 资产做 HEAD 取 `content-length`、用 raw URL 探测 mahavivo 的 `LICENSE`。
- 联网：WebFetch `https://raw.githubusercontent.com/skywind3000/ECDICT/master/README.md`（访问 2026-11-05）；WebFetch `https://apps.apple.com/us/app/id1574077669`（访问 2026-11-05）；WebSearch「义务教育英语课程标准 2011/2022 附录 词汇表 二级」「小学英语大纲词汇 mahavivo」「上海市初中英语词汇表 2020年版」各 1–2 次。WebFetch 教育部 2011 课标 PDF（yunyang.gov.cn 转载）失败：「proxy refused the connection」。

说明：下文「确认」= 行号、语义、数字均独立复现；「修正」= 结论成立但有需要改写的细节；每条给出我自己的命令/公式。

---

## 逐条核验

**[seed-pipeline-1] 确认。** `build_seed.py:15-17`（`PLAIN_RE`/`RICH_RE`/`POS_RE`）、`:23`（`utf-8-sig`）、`:25-26`（`len(line) == 1` 跳过）、`:81-88`（六个文件名与模式）、`:38-41`（剥词性）、`:42-47`（小写去重）行号全部正确。重算：`build_seed.parse_list(zhongkao.txt, "rich")` = 1887（= `stats.json:28 "zk": 1887`）；`zhongkao.txt` 前 3 字节 = `EF BB BF`（带 BOM）；`parse_list(Highschool_edited.txt, "plain")` = 3446（= `stats.json:29`）。置信度高。

**[seed-pipeline-2] 确认。** `xiaoxue.txt` 2,518 B、纯 ASCII、无 BOM；非空行 441，长度为 1 的行恰为 `['a', 'I']`；`parse_list(…, "plain")` = 439，被丢的正是这两行（`build_seed.py:25`）。线上 `a`/`i` 的 `sources` 都是 `cet4 ecdict zk`（`select lemma, sources from words where lemma in ('a','i')`），即同时来自 ECDICT 标签和中考 rich 表，与作者解释一致。置信度高。

**[seed-pipeline-3] 确认。** `build_seed.py:105-109`（步骤 1 全部带标签行）、`:96-100`（`lookup` 精确 + 空格→连字符）、`:112-127`（步骤 2）、`:119-121`（查不到即 `missing` 并 `continue`）、`:128-142`（cet46）、`:150-151`（排序键）全部对得上。`stats.json` 的 `missing_from_ecdict` 实际在 35-39 行（作者写 36-40，差一行，无关紧要），内容只有 `cet46: ["instalation"]`。置信度高。

**[seed-pipeline-4] 修正（细节）。** 原说法「`make_record`（180-198 行）产出 15 个字段 … 加上 `cet6_star`」→ 正确说法：`make_record` 返回 **14** 个键（`build_seed.py:183-198`：word, phonetic, translation, definition, pos, collins, oxford, stages, exam_tags, bnc, frq, exchange, sources, ecdict_id），`cet6_star`（`:145`）是第 **15** 个；记录总数 15 个键才是对的。重算：`gzip -dc vocab.jsonl.gz` 后逐行 `len(json.loads(line))` → `{15: 9162}`。其余成立：`:193-194` 的 `int(frq) if frq else None` 使 0 变 null，线上 `select count(*) from words where frq=0` = 0；`:191`/`:192` 过滤元组、`:196` `sources` 初值、`:157-177` 与 `:201-219` 生成 `stats.json`/`ATTRIBUTION.md` 均正确。置信度高。

**[seed-pipeline-5] 确认。** 作者保存的 `dl-gh-api/mahavivo-contents.json`（28 个文件）给出的大小与文中逐一相同：`中考英语词汇表.txt` 86,765、`Highschool_edited.txt` 25,353、`CET4_edited.txt` 198,810、`CET6_edited.txt` 177,864、`CET_4+6_edited.txt` 65,877、`英语六级词汇（星标，1726）.txt` 14,914、`小学英语大纲词汇.txt` 2,518、`上海市初中英语词汇表（2020年版）.pdf` 1,200,683；`mahavivo-repo.json`：`license: null`、`pushed_at 2024-05-11T09:55:45Z`、`stargazers_count 2538`；`mahavivo-commits.json` 最新 `395cebd5 2022-01-30T01:14:32Z "edit"`。我新抓的 README（raw，2,089 B，与作者副本同大小）共 10 条，只说明 CET4（贵州大学 PDF）、CET4+6（2016 大纲 cet.edu.cn）、台灣高中英文參考詞彙表、托福/GRE（2003 金山词霸）、COCA、OALD8 等，**确实没有**中考表、`Highschool_edited.txt`、小学表的来源。补充探测：`raw.githubusercontent.com/mahavivo/english-wordlists/master/LICENSE` 与 `LICENSE.md` 均 404（访问 2026-11-05），佐证无许可证文件。置信度高。

**[seed-pipeline-6] 确认。** `release-1.0.28.json`：`published_at 2017-09-20T10:28:39Z`；`ecdict-sqlite-28.zip` `size 216765132`、`updated_at 2018-05-20T10:03:33Z`（该资产 `created_at 2018-05-16`，比其他资产晚）；`ecdict-releases.json` 长度 1；`ecdict-repo.json` `license MIT`、`pushed_at 2026-11-02T07:58:21Z`。我独立解析 `tail2.bin`（65,132 B）：EOCD 在偏移 65110，1 个条目，中央目录偏移 216,765,017；条目 `stardict.db`，method 8，压缩 216,764,976，**解压 851,288,064**（无 zip64 记录）。今日 `curl -sIL` 该资产：302 → `release-assets.githubusercontent.com`，`HTTP/2 200`、`accept-ranges: bytes`、`content-length: 216765132`。与 `deploy/fetch_ecdict.sh:3-4` 注释及 `:12-13` 的 URL/sha256 常量位置一致；sha256 本次同样未下载整包校验（与作者相同的保留）。置信度高。

**[seed-pipeline-7] 确认。** 复现：`gzip -dc data/seed/vocab.jsonl.gz > vocab.jsonl`（9162 行，sha256 `3b3ed209…22243`），Apple gzip 479.0.0.700.1 `gzip -9 -n -c` → `6841b7df…8aae`（1,266,005 B）≠ 仓库 `a68127…3336`（1,275,527 B）；`cmp` 报「differ: char 11」，前 10 字节头相同（`1f8b 0800 0000 0000 0203`），第 11 字节起 deflate 流不同。`pack_seed.sh:6-7` 与 `Makefile:97` 的「可复现」前提确实只在同一 gzip 实现下成立。GNU gzip 能否复现 `a68127…` 在本机无法验证（与作者一致）。置信度高。

**[seed-pipeline-8] 修正（细节）。** 复现 `bash scripts/pack_seed.sh --check`：输出 `zcat: can't stat: …vocab.jsonl.gz (…vocab.jsonl.gz.Z)`、`vocab.jsonl.gz: 0 records, sha256 a68127…`、`archive record count 0 != stats.json total_words 9162`，exit 1；`/usr/bin/zcat` 为 Apple gzip 479 的 compress 版。原说法「BSD zcat（62、79、90 行）」→ 正确说法：`zcat` 出现在 **62、68、79、90** 四处（68 行是 `--check` 的 round-trip 比对），`stat -c %s` 在 90 行，`Makefile:98` 也用 `zcat`。`fetch_ecdict.sh:23` `df --output=avail`、`:59` `sed -i "s|…|…|"`、`:45` `python3 -m zipfile`、`:48` sqlite 校验行号正确；`/sbin/sha256sum` 本机存在。置信度高。

**[seed-pipeline-9] 确认。** `seed.py:167-214`（`seed_row`）、`:174-179`（`word` 非 str / 空 → None）、`:180-181`（`normalise_input` 失败退回 `normalise_lemma`）、`:142-152`（`_lines`）、`:155-164`（`_int`：`""`/None → None，0 保留）、`:184-185`（`stages` 缺省）、`:269-273`（计入 `skipped_records` 并 warning）全部正确；`test_seed.py:288` 起的 `test_seed_row_mapping_and_validation` 覆盖 `{"word": "x"}` 类最小记录。实验：`{"word":"Kitty","stages":["xx"]}` 导入后 `kind=proper_noun, translation=NULL, source=seed, safe_for_sharing=1`，四个 flag 0、`stage_min NULL`。置信度高。

**[seed-pipeline-10] 确认。** `_UPSERT_SQL`（`seed.py:72-82`）：`:75-77` `DO UPDATE SET <20 列> = excluded.<col>` 加 `source='seed', is_public=1, is_valid_english=1, safe_for_sharing=1, merged_into_word_id=NULL`；`:78-81` WHERE 只是「任一列不同」；无 COALESCE。`SEED_COLUMNS`（`:47-68`）确为 20 项。`--force` 在 `:359`，只跳过 `:260-263` 的哈希相等短路。实验：补充记录 `{"word":"ice cream","translation":["冰淇淋"],"stages":["xx","zk"]}` 把线上原行的 `translation` 从「冰淇淋 | [化] 冰淇淋」改成「冰淇淋」，`sources` 从 `ecdict` 变 NULL（见 [12] 的查询）。置信度高。

**[seed-pipeline-11] 确认。** `seed.py:43` `STAGES`、`:47-68` 含 `stage_*`/`stage_min`、`:184-185` 过滤、`:208` `stage_min = STAGES.index(stages[0]) + 1`；`0001_init.sql:185` `stage_min INTEGER CHECK (stage_min BETWEEN 1 AND 4)`。实验：`stages:["xx"]` 的 `Kitty` 导入无任何告警，flag 全 0、`stage_min NULL`。置信度高。

**[seed-pipeline-12] 确认。** `0001_init.sql:205` `CREATE UNIQUE INDEX ux_words_lemma ON words(lemma)`；`seed.py:274-277` 同文件重复 lemma 先到先得；`test_seed.py:252-259` 覆盖。我的实验（5 行补充文件：May/Kitty/ice cream/Mr/May 重复）：导入前 `may` = `display may, stage_zk 1, stage_min 1, frq 119, sources 'cet4 cet46 ecdict gk zk'`，导入后 = `display May, kind proper_noun, translation 'n. 五月', stage_zk 0, stage_min NULL, frq NULL, sources NULL`；`mr`（新 lemma）与 `mr.`（`display Mr.`）并存为两行；导入器报 `duplicate lemma 'may' … keeping the first record`；`word_forms` 14,132 → 14,130（`mays`、`ice creams` 两条被 `_rebuild_forms` 删除且补充记录无 `exchange`）。作者「14,132 → 14,127」对应其 5 个被更新 lemma，机制一致。线上确有 `mr. / mrs. / ms. / p.e. / ice cream / ice-cream / schoolbag`（`lists.py` 查询）。置信度高。

**[seed-pipeline-13] 确认。** `word_forms` 中 `children→child(s)`、`feet→foot(s)`、`has→have(3)` 与 `has→ha(s)`、`men→man(s)`、`women→woman(s)`（查询 `select w.lemma, wf.kind from word_forms wf join words w … where wf.form=?`）。`seed.py:218-245`、`:45`、`:235-241` 行号正确；我的真实导入同样输出 `11 empty and 520 headword forms skipped`；`0001_init.sql:215` 注释确为「388 in the seed」。置信度高。

**[seed-pipeline-14] 确认。** `main.py:307-319` `seed_check`（作者写 307-318，少算了 319 行的防御性 `kv_set`，无关紧要）比较 `sha256_file(cfg.seed_path)` 与 `kv.seed_version`。实验：补充文件导入后 `kv.seed_version = d0ef13af…` = `shasum -a 256 supplement.jsonl`，`system_events` 新增 `{"file":"supplement.jsonl","records":5,"inserted":2,"updated":2,…}`；再执行默认 `wd import-seed`（等价 `seed_check`）→ `0 inserted, 2 updated`，`may` 回到 `display may / stage_min 1 / frq 119`，`ice cream` 回到 `sources ecdict`，而 `kitty`、`mr` 两个新 lemma 留下，`word_forms` 回到 14,132。置信度高。

**[seed-pipeline-15] 确认。** 本机复现：`wd import-seed` 输出 `9162 inserted, 0 updated; 14132 word forms (11 empty and 520 headword forms skipped); 0.2 s`，`time` 墙钟 0.545 s；第二次 `seed up to date`。线上 `system_events`：`2026-11-02T07:36:59Z {"records": 9162, "inserted": 9162, "forms": 14132, …}`，`kv.seed_version = a68127…`。`docs/TASKS.md:168` 预算 `< 20 s`。置信度高（硬件相关）。

**[seed-pipeline-16] 确认。** 在 `ecdict.csv` 按小写精确匹配（`csvcheck.py`）：`kitty → "n. 小猫, 全部赌注", frq 25372`；`peter → "vi. 逐渐消失, 逐渐减少"`；`ALICE → "[计] 应用语言接口转换与扩充"`；`SAM → "[计] 安全性帐户管理器"`；`PE → "[计] 相位编码"`；`MS → "美国微软公司…"`；`mum → "n. 菊花, 沉默…"`；`Danny/eddie/joe` 为人名释义；`physical education → "[医] 体育"`；`ice cream` tag `zk`、frq 0。`derive_kind` 在 `services/words.py:143-151`，首字母大写 → `proper_noun`；`seed.py:74` 写死 `'seed', 1, 1, 1`；`0001_init.sql:194` 注释「Claude verdict (no personal names etc.)」。置信度高（推断部分同作者，中）。

**[seed-pipeline-17] 确认。** 七处定位全部核对：docstring `:10-11`、`ATTRIBUTION :201-219`、`syllabus :81-88`、`stage_from_list :112`、`:147` 与 `:150` 两个元组、`make_record :191`、标签查询 `:105-106`、统计 `:157-171` 随 `order` 变化。置信度高。补充见「遗漏」O1/O2（还有更多硬编码点）。

**[seed-pipeline-18] 确认（行号微调）。** `seed.py:43/47-68/204-207/208`、`0001_init.sql:185`（`stage_min`）与 `:148`（`current_stage BETWEEN 1 AND 4`）、`:33`（表重建配方注释）正确；`index_to_stage` 实际在 `schemas.py:64-67`（`1 <= int(index) <= 4` 在 65 行），作者写 62-65。`_STAGE_DISTANCE` 在 `batches.py:60`、`screen.py:34-35` 正确。SQLite 不支持修改 CHECK、需整表重建属实。置信度高。补充：`0001_init.sql:148` 还有 `DEFAULT 3`、`:147` `stages_json DEFAULT '["cet4","cet6"]'`、`bank.py:86` `DEFAULT_CURRENT_STAGE = 3`——若小学插在索引 1，这些默认值也要同步（见 O1）。

**[seed-pipeline-19] 修正（清单不完整）。** 已列出的位置全部正确：`schemas.py:25, 51-52, 488, 708, 1335`；`services/words.py:39`（`bank.py:181`、`batches.py:233`、`screen.py:46` 使用）；`services/ecdict.py:28, 119, 173-177`；`bank.py:85-86`；`types.ts:5`；`'zk'` 字面量 10 行 / 6 文件（`grep -rn "'zk'" frontend/src`：StageChips 2、types 1、AdminPage 1、WelcomePage 4、SettingsPage.test 1、VocabPage 1）；`zh.ts:25, 28`；`API.md:160,169,187,230,239`；`DESIGN.md:193-209`；`test_seed.py:338-353`；`mini_seed.jsonl` 60 行。**但遗漏了以下同样写死 4 个阶段/索引的位置**（`grep -rn 'StageIndex\|STAGE_ZH\|difficulty' …`）：`backend/wd/schemas.py:26` `StageIndex = Literal[1, 2, 3, 4]`；`frontend/src/api/types.ts:6` `StageIndex = 1 | 2 | 3 | 4`（`:45`、`:52` 使用）；`frontend/src/components/word/StageChips.tsx:8-9` `STAGE_INDEX`/`STAGE_BY_INDEX`；`backend/wd/ai/content.py:47` `AUDIENCE = "Chinese learners, junior high school to CET-6, …"` 与 `:49` `STAGE_ZH`（`:88` 把阶段中文名送进 Claude 提示）；`backend/wd/ai/prompts/content_system.txt:1`（受众列表）与 `:11`「difficulty: integer 1–5 (1 = 初中 basic, 2 = 高中, 3 = CET-4, 4 = CET-6, 5 = beyond CET-6)」；`backend/wd/ai/prewarm.py:32-33` `STAGE_COLUMNS`/`STAGES`；`0001_init.sql:147-148` 两个 DEFAULT、`:195` `difficulty … -- 1 初中 … 4 六级, 5 beyond`；`services/stats.py:177-180`（按 `STAGE_ORDER` 逐阶段统计 `stage_min = :idx`）；`security.py:597` `index_to_stage`；`API.md:460`（`zk→1 … cet6→4` 映射说明）；以及 `scripts/check_contract.py`（`Makefile:85-87`，schemas.py ↔ types.ts 字段审计，契约改动必须让它通过）。置信度高。

**[seed-pipeline-20] 确认。** `pack_seed.sh:44-47` 读 `total_words`，`:52-57` 不等即 exit 1；`grep -rn stats.json backend scripts deploy Makefile` 只命中 `pack_seed.sh` 与 `build_seed.py`；文档引用 `README.md:78`、根 `ATTRIBUTION.md:14`、`DESIGN.md:149,205,209` 正确。置信度高。

**[seed-pipeline-21] 确认。** `build_seed.py:201-219` 生成 `data/seed/ATTRIBUTION.md`（`:176-177` 覆盖写）；根 `ATTRIBUTION.md:14`「9,162 records」；`zh.ts:86` `lists: '词表范围：中考、高考、大学英语四级与六级大纲'`；`data/seed/ATTRIBUTION.md:12-13`「Only the head words are used to decide stage membership」。置信度高。

**[seed-pipeline-22] 确认。** `ecdict.csv`：数据行 770,611，`tag` 非空 14,942，token 频次与作者完全一致：`gre 7504, toefl 6974, cet6 5407, ielts 5040, ky 4801, cet4 3849, gk 3677, zk 1603`；无任何小学类标记。`zk` 的 1,603 个词（小写）全部在种子里（差集 = ∅）。WebFetch 当前 README（访问 2026-11-05）原文：「tag | 字符串标签：zk/中考，gk/高考，cet4/四级 等等标签，空格分割」，全文无 小学/primary；本地副本第 40 行同。置信度高。

**[seed-pipeline-23] 确认。** 重算（`lists.py`，`statistics.quantiles(n=4)`）：小学表 439 词中 429 在库，422 有 `frq`，缺 `frq` 的 7 个 = `an, are, colour, email, ice cream, is, schoolbag`；缺 `bnc` 6 个（429−6 = 423 有 bnc）；`frq` min 1 / q25 167.75 / 中位 597.0 / q75 1610.25 / max 38684（作者 168/598/1609，差异来自分位插值法）；最高 rank 依次 `maths 38684, favourite 22274, bye 18387, panda 14691, grandpa 14478, mum 14080, blackboard 13322, crayon 12296, cloudy 10229`；zk 集合 1,988 个有 frq，中位 1522.0、q90 6718.5；`basketball 1799/16051`、`favourite 22274/2527`、`English 1782/18425`。README 第 41-42 行：`bnc` 英国国家语料库、`frq` 当代语料库词频顺序。`API.md:169` 与 `batches.py:61` 的排序键正确。推断部分（词频≠教学顺序）合理。置信度高/中。

**[seed-pipeline-24] 确认。** 全部数字复现：439 词头；多词 `ice cream, physical education`；大写 `China Chinese English Miss Mr Mrs Ms PE TV`；429 在库（423 个 `stage_zk=1`；6 个 `stage_zk=0` 且 `stage_min=2`：`an are color favorite maths mum`）；缺失 10 个：`children feet has men women Mr Mrs Ms PE physical education`。补充：439 词中 410 个也在中考 rich 表里（`lists.py`），不在的 29 个全是变体/屈折/功能词（`an are bag between children color crayon driver email favorite feet goodbye grandfather grandmother has ice cream men maths math Mr Mrs Ms mum PE physical education shorts us wash women`）。来源仍不明（见 O7 的未验证假设）。置信度高（来源：低）。

**[seed-pipeline-25] 确认（量级）。** `pdfinfo`：89 页、Title「Medical NOte」、Author「Intergen Administrator」、Creator「Acrobat PDFMaker 17 Word 版」、CreationDate 2019-09-30 11:28 CST；我重新 `pdftotext -layout` 的文本与作者的字节相同。我用**独立**启发式（行首非空白 + 两个以上空格或 CJK 处截断 + 剥括注/斜杠/词性）得 2,002 词头 = 1,688 单词 + 314 短语（作者 2,032 / 1,722 / 310）；单词 ∩ 中考表 1,247、上海独有 441、中考表独有 640（作者 1,285 / 437 / 602）；在库 1,649、缺 39（我的规则多保留了 `add...to` 一类省略号条目）、在库但 `stage_zk=0` 302 个（`stage_min` 2:230 / 3:58 / 14）（作者 1,696 / 26 / 309，236/59/14）；短语只有 `according to` 在库。两套规则都给出「上海初中表 ≈ 2,000 词头，约 1,700 单词，其中 ≈ 97% 已在种子中，≈ 300 个缺 zk 标记」。措辞提醒：「只重合约三分之二」是中考表侧（1,285/1,887 = 68%）；上海侧为 1,285/1,722 = 75%，Jaccard 1,285/2,324 = 55%。第二来源：App Store「上海中考英语词汇 听说测试」（`apps.apple.com/us/app/id1574077669`，访问 2026-11-05，v3.2 2023-11-22，第三方）称「本应用涵盖1719个上海中考英语考纲词汇」，与 1,688–1,722 单词量级吻合，但未注明版本/年份。置信度中。

**[seed-pipeline-26] 确认。** `fetch_ecdict.sh:14` `NEED_MB=1100`；`build_seed.py:74` `--db required=True`，`:97`/`:105` 直接查 `stardict` 表；Apple gzip 支持 `-k -n`（本机 `gzip -9 -n -c` 可运行）；`Makefile:98` `zcat` 在 BSD 下报错（[8]）。置信度高。

**[seed-pipeline-27] 确认。** `ecdict.csv` 66,009,548 B、770,611 行、表头 `word,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange,detail,audio`；README 第 143 行「…外面默认的 ecdict.csv 算是一个基础版本（76 万词条）」、第 95 行「CSV 里 id 为行号，其他两者是自增量」（WebFetch 当前 README 同文）。逐 lemma 比对（`fieldcmp.py`，csv 同 lemma 取首行）：命中 9,154；`frq/bnc/collins/oxford/definition` 9,154 全等；`translation` 9,146；`phonetic`（`norm_phonetic` 后）9,148；`exchange` 相等 7,130 → 不同 **2,024**（例：`a` 在 csv 无 `s:some`）；csv `pos` 全部为空（770,611 行中 0 行非空），种子 8,835 条有 `pos`（作者说线上 8,834，差 1 条应为空白被 `_text()` 置 NULL，不影响结论）；`ecdict_id` 0 条可复现（`a` 在 csv 第 608 个数据行，种子 7909）。不在 csv 的 8 词与作者完全一致：`babyboomer, celcius, honourary, microwavable, miss., sideroad, sobre, the pacific ocean`。`stardict.7z` 51,577,449 B（tree JSON），本机无 7z，未验证。置信度高。

**[seed-pipeline-28] 确认。** `import_seed(conn, path, …)`（`seed.py:248`）单文件；`config.py:92` `seed_path: Path = DEFAULT_SEED_PATH`、`:334` 读 `WD_SEED_PATH`；实验 5 行补充文件导入 9,162 词的库：`2 inserted, 2 updated, 1 duplicate lemmas; 0.0 s`，随后仓库种子重导入覆盖回去（[14]）。结论（必须就地修改 `WD_SEED_PATH` 指向的那一个文件）成立。置信度高。

**[seed-pipeline-29] 确认。** 线上副本：`stage_zk=1 and frq is null` = 111；`bnc is null` = 55；两者皆空 45；`frq = 0` = 0；全库 `frq is null` = 354；`phonetic` 空 165（zk 内 37）；`select source, count(*) … group by source` = `seed|9162`。置信度高。

**[seed-pipeline-30] 确认。** `display like '% %'` = 13 = `kind='phrase'`，列表逐词相同；zk 内 7；`stats.json:25 multiword 13`。置信度高。

**[seed-pipeline-31] 确认。** `substr(display,1,1) glob '[A-Z]'` = 141 = `display != lower(display)`；按 kind：proper_noun 119 + abbreviation 20 + phrase 2；abbreviation 全库 26，小写开头 6 个 `a.m. mrs. no. p.e. a.m i.e.`；zk 内 78（列表含 国名/语言/月份/星期/`Mr. Ms. Miss.`/`CD-ROM`/`E-MAIL`/`T-shirt`/`I`），`I` 的 kind = `proper_noun`。置信度高。

---

## 作者遗漏的重要事实

**O1（会改变决策方向）「小学插在索引 1」还会打乱 `difficulty` 1–5 的语义锚点与默认值。** 事实：`backend/wd/ai/prompts/content_system.txt:11` 让 Claude 按「1 = 初中 basic, 2 = 高中, 3 = CET-4, 4 = CET-6, 5 = beyond」打 `difficulty`；`0001_init.sql:195` 注释同义；`docs/API.md:169` `sort=difficulty` 用 `COALESCE(difficulty, stage_min, 5)`——即 `difficulty` 与 `stage_min` 被当作同一刻度混用。若 `stage_min=1` 改表示小学而 `difficulty=1` 仍表示初中，排序会错位；线上已有 49 个词写入了 `difficulty`（`select difficulty, count(*) from words where difficulty is not null group by 1` → 1:2, 2:1, 3:43, 4:3）。同时 `0001_init.sql:148` `current_stage … DEFAULT 3`、`:147` `stages_json DEFAULT '["cet4","cet6"]'`、`bank.py:86` `DEFAULT_CURRENT_STAGE = 3` 在重编号后会指向 gk。facts 文件 [18] 只提到 CHECK 与 `_STAGE_DISTANCE`。置信度高（事实）。

**O2 产品面：引导页角色与 AI 受众都没有「小学生」。** `frontend/src/pages/WelcomePage.tsx:30` `Role = 'zk' | 'gk' | 'uni' | 'pro'`，`:33-38` `ROLE_PRESETS`（zk→['zk']，gk→['zk','gk']…），`zh.ts:25` `roles: { zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }`，`docs/DESIGN.md:330` 记录了这一映射；`backend/wd/ai/content.py:47` `AUDIENCE = "Chinese learners, junior high school to CET-6, plus working professionals"`，`content_system.txt:1` 同，`:6` 例句要求 8–20 词、取材「daily life, work, study or news」，`:9` `image_keywords` 要「stock-photo search」能匹配的 2–4 词短语。与需求 (4)「配图更利于记忆」直接相关：配图关键词由同一提示词生成（`content.py:174-198` 只做 blocklist 过滤），面向 6–10 岁学习者需要改提示词而不只是改抓图源。置信度高（事实）+ 推断。

**O3 重编号迁移的现实成本目前极低，但只在现在。** 线上副本：`users` 2 行；`user_settings.current_stage` 取值 1 和 3 各 1，`stages_json` 为 `["zk","gk","cet4","cet6"]` 与 `["zk"]`；`user_words` 77 行；有内容的词 49 个（`stage_min` 1:1、3:48）；`schema_migrations` 已到 10（`0010_ai_provider.sql`，2026-11-05 应用），新迁移应编号 0011。facts [18] 把「插前 vs 追加」留为产品决策，但没有给出「现在做几乎零代价、对外开放后代价随用户增长」这一时间维度。置信度高（数字）/中（推断）。

**O4 量化：若小学插在最前，zk 的「仅本阶段新增」会从 2,099 缩到约 1,676。** 公式：小学表 439 词中 423 个当前 `stage_zk=1`（即 `stage_min=1`），插前后它们的 `stage_min` 变为小学；6 个 `stage_min=2` 的词（`an are color favorite maths mum`）也变为小学；10 个新词按最小记录加入 → 小学 `stage_min` 计数 ≈ 439，zk 新增 = 2,099 − 423 = 1,676（`select count(*) from words where stage_min=1` = 2,099）。这会改变 `docs/API.md:169`、`DESIGN.md:186/209` 写死的「3,694 / 2,099」类数字与 `test_seed.py:338-353` 的验收常量。置信度中（推断，取决于最终采用的小学表）。

**O5 基础版 csv 的 `zk` 标签与 1.0.28 release 一致——csv 不仅能替代字段，也能替代阶段标签。** 验证：csv 1,603 个 zk 词全部在线上且 `stage_zk=1`；反向，线上 2,099 个 zk 词中 212 个不在中考表（`sources` 不含 ` zk `，故只能来自 ECDICT 标签），这 212 个全部在 csv 的 zk 集合里（差集 ∅）。facts [27] 只比对了 frq/bnc/collins/oxford/definition/phonetic/translation，没有比对 `tag`。其他标签（gk/cet4/cet6）未做同样检查。置信度高（zk）。

**O6 上海初中表有第二个独立计数可参照。** App Store「上海中考英语词汇 听说测试 AI批改英语作文」（`https://apps.apple.com/us/app/id1574077669`，访问 2026-11-05）：「本应用涵盖1719个上海中考英语考纲词汇」，与 facts [25] 的 1,722 个单词（我的 1,688）在同一量级，支持「上海初中表 ≈ 1,700 单词 + ≈ 300 短语」的解读；但该应用未写明依据的年份/版本，PDF 本身的元数据（Word→Acrobat PDFMaker 17，作者「Intergen Administrator」，标题「Medical NOte」）表明它是第三方转排版而非教委/考试院原件，官方版本与是否已被更新仍需 regions 任务核实。置信度中。

**O7（未验证的假设，供 regions/curation 任务追查）mahavivo「小学英语大纲词汇」可能是国家课标「二级（小学毕业）」词汇表的转录。** 线索：规模 439；410/439 在中考表内；同时收录英美拼写变体（colour/color、favourite/favorite、maths/math）与 `PE`/`physical education`、`TV`、`Mr/Mrs/Ms/Miss`，是课标附录词表的典型写法；WebSearch 摘要（m.163.com 转述，非一手）称 2022 版课标二级「初步运用 500 个左右的单词」。反证/缺口：我无法打开教育部 2011 版课标 PDF（yunyang.gov.cn 转载，WebFetch「proxy refused the connection」），也没找到任何一手页面写明二级词表的确切词数或与该文件逐词对照。即便假设成立，它也只是全国课标基线，不是上海牛津版 1A–5B 的词表。置信度低（假设）。

---

## 未解决的问题

1. O7 的假设需要拿到《义务教育英语课程标准》（2011 或 2022 年版）附录词汇表原文逐词对照后才能定论。
2. `ecdict-sqlite-28.zip` 的 `ECDICT_SHA256`（`fetch_ecdict.sh:13`）仍未整包校验（216 MB）；GNU gzip 能否复现 `a68127…` 仍只能在 Linux 验证。
3. 上海初中表的官方当前版本（是否仍是「2020年版」、官方词数是否为 1,719）未得到一手来源；App Store 页面为第三方。
4. csv 与 release 在 `gk/cet4/cet6` 标签上的一致性未检查（只验了 zk）。
5. `api.github.com` 未认证限额今日已耗尽，所有 API 数字来自作者 21:53 保存的 JSON；若需要再次核对可改用 `gh api`（已登录）或等待限额重置。

## 汇总

核验 31 条：确认 28、修正 3（[4] 字段计数、[8] zcat 行号清单、[19] 硬编码清单不完整）、推翻 0、无法核验 0。
