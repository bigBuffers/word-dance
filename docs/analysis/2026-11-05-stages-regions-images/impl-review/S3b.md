# 评审 S3b `seedbuild-build-seed` — 构建器、差异报告、脚本/Makefile、用 ECDICT 重建种子

评审日期 2026-11-06。基线 main @ 75df534（工作区 HEAD 0a62322）。规格：PLAN §1 R-3/R-5…R-9/R-17、§4.2、§4.4、§4.5、§4.6、§4.8、§6 S3、§7.3；WL SYNTHESIS §3.4–§3.7。评审方式：逐文件读 `build.py`（1,307 行）、`diff.py`（466 行）、两个入口脚本、`pack_seed.sh`、Makefile diff、两份 ATTRIBUTION、`data/lists/README.md §5`、两个新测试文件与夹具；用真实 ECDICT（`$SCRATCH/ecdict-dl/extract/stardict.db`，zip sha256 `ea01f76a…f3f6` 核对相同）从 **git HEAD 的 9,162 行种子** 独立重建三次（HEAD+ECDICT / 自身+无 ECDICT / 自身+ECDICT）并与交付产物逐字节比对；写脚本抽查 PLAN §4.2/§4.3 的全部关键例 + 10 个随机课标外词 + 10 个随机新行；对实现做了 6 处临时改坏再恢复的变异测试。评审结束时 `build.py`/`diff.py` sha256 与开始时相同，`data/seed/` 五个文件已恢复为交付字节（`stats.json 59dccdf1…`、`vocab.jsonl.gz f32ab945…`），`git status` 与开始时相同；评审只新增了本文件。

## 1 结论

**通过验收，但有 1 条 major 必须在合入前修**：交付的 `data/seed/stats.json` 与 `data/seed/ATTRIBUTION.md` 不是「HEAD 种子 → 新种子」那次构建的产物，而是一次 **以自己的输出为 `--previous`、且没有 `--ecdict`** 的重跑的产物（`previous_sha256 == content_sha256`、`new_words 0`、`network_translations 0`、`rows_changed_vs_previous 0/0`、`overrides_applied 22`、`unparsed_notes` 多出 UNESCO 与 the Bund 两条、`skipped` 少了 8 条 R12 拒绝）。`vocab.jsonl.gz` / `DIFF.md` 本身正确（三种方式重建的 `vocab.jsonl` 字节全同，`content_sha256 ee985d90…`）。根因是 Makefile `seed` 目标用工作区的 `data/seed/vocab.jsonl.gz` 做 `--previous`，第一次 `make seed` 之后它已被 `pack_seed.sh` 替换，于是任何第二次运行（包括 §6 S3 的「连跑两次」验收本身）都会把 stats/ATTRIBUTION 写成自指版本。其余 7 条 minor（Makefile 的 `git show` 失败静默跳过 diff、无 ECDICT 时的报错不提示、死参数、DIFF 头部标签、`stats.variants` 口径、ATTRIBUTION 写死 zip 名、构建器不自检 lemma）。代码对 PLAN §4.2 集合代数与断言 ①–⑥、§4.4 令牌、§4.5 记录 v2/确定性、§4.8 差异报告的实现忠实；实现者自报的 10 条偏离全部核实，判定见 §5。

## 2 验收命令复跑

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q backend/tests/unit/test_seedbuild_normalise.py backend/tests/unit/test_seedbuild_build.py backend/tests/unit/test_seed_diff.py` | **340 passed** in 0.96s（238 + 88 + 14） |
| `make seed ECDICT_DB=$SCRATCH/ecdict-dl/extract/stardict.db` ×2 → 比对 `content_sha256` | `same content_sha256: True`；两次的 `stats.json` 逐字节相同；`vocab.jsonl.gz unchanged (archive sha256 f32ab945…)`；GNU Make 3.81 下运行正常（`.SHELLFLAGS` 是 3.82 特性、被 3.81 忽略，但该目标的每一行都自带 rc 处理，不受影响） |
| `scripts/pack_seed.sh --check` | `9618 records, content sha256 ee985d90… == stats.json`；`seed archive OK`，exit 0（macOS：`gzip -dc`/`shasum -a 256`/`wc -c` 路径均已走到） |
| `seed_diff.py <HEAD 种子> data/seed/vocab.jsonl.gz --md /dev/stdout \| head -80` | 5 条不变量全部 **PASS**；矩阵见 §3.4，与 PLAN §4.8 只差 1 行（new→zk 425 vs 424，列计 1,949/9,618 vs 1,948/9,617），≤ 1% |
| `git diff --stat -- data/lists/` | 空；`git ls-files data/lists` = 15 个已交付文件一字未改；5 个新文件均 untracked（manifest/aliases/overrides/SHA256SUMS/README） |

补充核对（不在验收清单内，但与实现者的报告逐项对照）：`seed.seed_row` 对 9,618 条记录逐条计算 → `lemma_mismatch 0`、`unknown_stage_codes 0`；9,618 条 display 全部通过 `words.normalise_input`（R12 对产物成立）；`variant_of` 44 条且目标 lemma 全部存在。

## 3 对规格的逐项核对（真实数据）

### 3.1 §4.2 集合代数与断言 ①–⑥

| 项 | 代码位置 | 结论 |
|---|---|---|
| L2/L3/APPxs/APPzk/SH/SHP/HS/INH | `collect_members`（`build.py:639-781`）：`split_head` / `resolve_phrase` 逐行、`appendix` 组策略（`member:false`、`single_token`）、`known()` = previous ∪ ECDICT(R10 候选)、`merge_heads`、`inherit_forms` | 与 PLAN 公式一致；真实产出 L2 520 / L3 1,646 / APP 168 / SH 1,737 / SH:app 142 / SHP 334 / HS 3,162 ∪ 3,046；INH = {am, are, does, is} |
| ① xs ⊆ zk | `:760-762` → `failures`，strict 下 `BuildError` exit 2 | 真实种子 600 xs 行全带 zk；变异 M1 被两条测试抓住 |
| ② 阶段码 ∈ STAGE_ORDER | `_stages()`（manifest 装载）+ `:763-765` 双保险 | 测试 `test_manifest_errors[xx/cet9]` |
| ③ 宇宙 ⊇ 上一版 | `:766-768`（drop 命中旧 lemma 拒绝）+ `build():1245-1247`（写出前再查一次） | 旧 9,162 lemma 全部仍在；`--no-strict` 也不能绕过（测试 `test_no_strict_…not_retain`） |
| ④ main 词头全部解析 | `:715-718` → `failures` 列出 `<list>: head 'x' (lemma) …` | 真实构建 `missing: []`；缺词头测试 `test_missing_main_head_fails_and_is_listed` |
| ⑤ 同 lemma 一条记录 | `merge_heads` 并集 + `make_records` 按 `sorted(universe)` 一次一条 | 16 组 `merged_heads`（Miss/miss、May/may、A.M./a.m.、PE/P.E.、humorous/humourous…）；输出无重复 lemma |
| ⑥ 新行译文首行非空 | `make_records:916-917` → `build():1234-1235` | 真实 `empty_translation 0`；测试 `test_new_row_with_only_an_empty_network_translation_fails` |
| 不断言 zk ⊆ gk | — | 实测 212 个单词 + 334 个词组只在 zk（与 SYNTHESIS 212 + 333 相符） |
| exit 2 不写输出 | `main()` 捕获 `ManifestError`/`BuildError` → 2；`build()` 在 `out.mkdir` 之前完成全部校验 | 用坏 manifest（`format: 3`、`policy: bogus`、`stages: ["xx"]`、`expect_rows 99`、sha256 不符）逐一验证 exit 2 且 `out/` 不存在 |

### 3.2 §4.4 令牌（真实 `stats.tokens`）

`ecdict` 8,285 · `cet4/cet6/cet46` 4,539/2,220/8,007 · `legacy:zk/gk` 2,099/3,829 · `moe22:l2/l3/app` 520/1,646/168 · `shmeea20/:app/:phr` 1,737/142/334 · `hs25:0/1/2` 1,648/504/1,012 · `hs20:0/1/2` 1,526/505/1,017 · `inherit:be/do` 3/1 —— 与 PLAN §4.4 复算行数逐项相同或相差 ≤ 2；旧令牌 `zk`/`gk` 0 行；新行无 `legacy:*`；`legacy:*` 恰等于 v1 旗标（`test_legacy_tokens…`，变异 M3 抓住）。

### 3.3 §4.5 记录 v2、确定性、CLI、脚本

- 键序 `RECORD_KEYS` 与 PLAN 表相同；`aliases`/`variant_of` 只在出现时写；`seed_v: 2`；`stages` 按 `STAGE_ORDER`；`sources` 排序去重；排序键 `(stage_to_index(stages[0]) or 99, lemma)`；`ensure_ascii=False`、LF、无时间戳（`--built-at` 只进 stats）。三种 `--previous`/ECDICT 组合重建的 `vocab.jsonl` 字节全同 → 重标幂等、ECDICT 只影响新行。
- CLI 与 PLAN 一致，另加 `--ecdict-release`（合理：manifest 不含 release，`stats.ecdict_release` 需要来源）。`scripts/build_seed.py`/`seed_diff.py` 为 PLAN 规定的两行入口，`-I` 下可导入。
- `pack_seed.sh`：BSD 可移植三处修复到位，新增 `content_sha256` 双向校验（jsonl 与解包后的 gz 都比对）；`--check` 可在无 `vocab.jsonl` 时只查归档。
- Makefile `seed`：build → seed_diff（`git show HEAD:…`）→ pack，三步；`ECDICT_DB`/`WORDLISTS_DIR` 可选且有存在性提示；注释按 PLAN 改写。问题见 F1/F2。
- ECDICT 新行字段映射与旧 `make_record` 相同（经 `EcdictEntry.from_row`：音标 `norm_phonetic`、`collins/oxford` 0、`bnc/frq` None、`exam_tags` 过滤、`ecdict` 令牌仅当有 tag）。

### 3.4 §4.8 差异报告（HEAD 9,162 → 9,618）

| 旧 \ 新 | 1 xs | 2 zk | 3 gk | 4 cet4 | 5 cet6 | ∅ | 行计 |
|---|---|---|---|---|---|---|---|
| 1 (zk) | 573 | 1,117 | 188 | 122 | 30 | 69 | 2,099 |
| 2 (gk) | 8 | 315 | 681 | 399 | 220 | 169 | 1,792 |
| 3 (cet4) | 2 | 68 | 302 | 1,205 | — | — | 1,577 |
| 4 (cet6) | 1 | 24 | 69 | — | 3,600 | — | 3,694 |
| new | 16 | **425** | 15 | — | — | — | **456** |
| 列计 | 600 | **1,949** | 1,255 | 1,726 | 3,850 | 238 | **9,618** |

与 PLAN §4.8 完全相同，除粗体四格各 +1（实现者解释成立：词组 token 级 `/` 展开多出 1 条，见 §5 条 9）。(a) 计数、(b) 矩阵+每阶段 ±、(c) 逐词（`--only`）、(d) 失去全部阶段 238 / 含 `[网络]` 的新词 4（均在第 2 行译文，首行前缀已去）/ merged_heads 16 / aliases 6 / display 变化 1（`E-MAIL→e-mail`）、(e) 五条不变量（多出「码有序」与「lemma == normalise_lemma(word)」两条，合理）都在；失败 → exit 1（变异 M5 抓住）；v1 行标签 1..4、v2 列标签 1..5（变异 M6 抓住）。

### 3.5 抽查 40+ 词（PLAN §4.2/§4.3 关键例 + 随机）

全部与规则预期一致，摘要：`colour`/`color`（变体同阶段，`color.variant_of=colour`）；`maths`/`math`/`mathematics`（`math` 因在上海附表作词头而清掉 `variant_of`，正确）；`PE (=physical education)` → `p.e.` 带 `aliases ["pe"]` + 译文 override，`physical education` 变体 + override；`be (am, is, are)` 丢弃、`am/is/are` 经 `inherit:be` 得 xs zk gk（`was/has/did` 不建行）；`according (to)` → `according to` 成员（zk gk，含 `shmeea20:phr`），裸 `according` 不存在；`UNESCO (…)` → `unesco` 成员、66 字符全称被 R12 拒；`bund (the Bund)` → `bund` 带 override 译文、`the bund` 被 drop；`a/an` 两行且 `an` 多得 `hs20:0`（`a (an)`）；`exam=examination`、`manner(s)`、`toward(s)`、`policeman/policewoman` 各两行；`Mr/Mrs/Ms` → `mr./mrs./ms.` + aliases；`hot-dog` → `hot dog`（新行，alias）而 `hotdog` 旧行只剩 cet6；`humourous` → `humorous` 得 gk + alias，旧 `humourous` 行保留无阶段；`excited/stuck/united/frightened` 分词形容词独立行；`a bit`/`a bit of`、`at first`/`at last`；`break down`（新行）≠ `breakdown`（cet6 旧行）；`ice-cream` 与 `ice cream` 并存；`programme/program`、`realise/realize`、`till/until`、`kilo/kilogram/kilogramme`；`café`→`cafe`；`Miss/miss`、`China/china`、`May/may` 合并；`one/first/January/Monday` 经 `moe22:app` 进 xs；`The United States of America` 拒、`USA` 入；22 条 translation/word override 全部生效（含 `ai/bce/ce/cpc/un/wto/tcm/qipao/beijing opera/tian'anmen square/children's day/women's day/the changjiang river/wi-fi/stuck/mum/e-mail`）；10 个随机课标外词（`seagull, bookshop, armchair, stateswoman, firmly, eyewitness, dvd, cance, stairs, bookmark`）全部 `stages []` 且带 `legacy:*`、词典字段逐字等于旧行；10 个随机新行（9 个词组 + `dining`）译文非空、display 非空、`lemma == normalise_lemma(word)`。

### 3.6 §4.6 两份 ATTRIBUTION

- `data/seed/ATTRIBUTION.md` 由 `render_attribution` 从 manifest 渲染：§1 ECDICT · §2 官方词表（每个 manifest 条目一行，`provisional`/`level_token` 标注，reference 表也列出）· §3 mahavivo 四表（可选、不分发、本次 absent）· §4 overrides 条数 · §5 令牌表 + 阶段码（来自 `schemas`）。结构合规；**数字陈旧**见 F1。
- 根 `ATTRIBUTION.md`：`:14` 改为引用 `stats.json`（不手抄数字）；§2 → 2a 官方词表（只用词头、未声明许可、《著作权法》第五条未核实、provenance 指向 `data/lists/README.md`）/ 2b mahavivo CET 四表（可选输入；`中考英语词汇表.txt`、`Highschool_edited.txt` 已停用，出处以 `legacy:*` 保留）/ 2c overrides（≤ 30 条 MIT 文本）；S5 请求的句子全部到位且与 S5 代码一致（`filetype:bitmap`/`filetype:drawing`、`thumbmime`、`maxlag=5`→503+Retry-After、Openverse `page_size=10`/`category=illustration`、`<desc id="aigc-label">`、图内无文字）。

## 4 Findings（按严重度）

### F1 · major · `data/seed/stats.json` + `data/seed/ATTRIBUTION.md`（Makefile `seed` 目标的 `--previous` 自指）

- **现象**：交付 `stats.json` 与「`--previous data/seed/vocab.jsonl.gz`（已是 v2 产物）、无 `--ecdict`」的重建产物 **逐字节相同**；与「`--previous` = `git show HEAD:data/seed/vocab.jsonl.gz`、有 `--ecdict`」的正确构建相比：`previous_sha256` `ee985d90…`（=自身）vs `3b3ed209…`（HEAD 内容）；`new_words` 0 vs **456**；`network_translations` 0 vs **10**；`rows_changed_vs_previous` 0/0 vs **2,601/1,756**；`overrides_applied` 22 vs 23、`overrides_unused ["the bund drop"]` vs `[]`；`unparsed_notes` 多出 `UNESCO (…)` 与 `bund (the Bund)` 两条（无 ECDICT 时它们成了 unknown 而非 R12 拒绝/drop）；`lists[*].skipped` 少了 8 条 `(strict: …)` 拒绝（UNESCO 全称、`add ... to`、`get into the habit of`、`keep ... from`、`prefer ... to`、`provide ... with`、`see ... off`、`share ... with`）。`ATTRIBUTION.md` 随之写着「`stats.network_translations` = 0」「22 applied」。`DIFF.md` 与 `vocab.jsonl.gz` 正确（DIFF 用的是 HEAD 副本）。
- **为什么是 major**：PLAN R-17 把 `stats.json` 定为唯一验收常量来源（TASKS/DESIGN/README/发布说明引用 `new_words`、`rows_changed_vs_previous` 等），交付文件与同目录 `DIFF.md`（+456）自相矛盾；且 §6 S3 的「连跑两次」验收命令本身就会复现它——第一次 `make seed` 后 `pack_seed.sh` 已把 `vocab.jsonl.gz` 换成新种子，第二次的 `--previous` 就是自己。无运行时影响（导入器不读 stats.json；`total_words/per_stage/first_stage/per_kind` 不受影响）。
- **修法**：① Makefile `seed` 先 `git show HEAD:data/seed/vocab.jsonl.gz > data/seed/.prev.jsonl.gz`，把它同时作为 `build_seed.py --previous` 与 `seed_diff.py` 的 OLD（PLAN §4.5 本就以 HEAD 为差异基准；这样 `make seed` 幂等、两次运行连 `stats.json` 都逐字节相同，也让 `previous_sha256` 有确定含义 = 上一次提交的种子）；② 用 `make seed ECDICT_DB=…` 重新生成并提交 `stats.json`/`ATTRIBUTION.md`（预期值即上文粗体）；③ `test_rebuild_from_own_output_is_idempotent` 保留（它钉的是重标幂等，不是 `make seed` 的口径）。

### F2 · minor · `Makefile` `seed` 目标：`git show` 失败时静默跳过差异报告

`git show HEAD:… > .prev && { seed_diff … || rc=$?; }; rm -f .prev; exit ${rc:-0}` —— `git show` 失败（无 HEAD 种子、损坏的对象库）时 `&&` 短路、`rc` 未设、整行 exit 0，`DIFF.md` 陈旧而流水线继续打包。实测 `sh -c '…does-not-exist…'` 返回 0。修法：`git show … || { echo "make: cannot read HEAD:data/seed/vocab.jsonl.gz" >&2; exit 2; }` 后再跑 diff。

### F3 · minor · `build.py` `collect_members` / `main`：忘记 `--ecdict` 时的报错不说原因

无 `--ecdict` 从 HEAD 种子构建时输出 456 行「head 'x' is in neither ECDICT nor the previous seed」，没有一句「本次未提供 `--ecdict`，N 个新词头需要 ECDICT」。建议 `ec.available is False` 且 `failures` 非空时在首行加这句提示（`Makefile` 注释已说明 `ECDICT_DB` 只在有新词头时需要，报错应呼应）。

### F4 · minor · `build.py:639` `collect_members(…, *, strict=True)`：参数未使用

函数体没有引用 `strict`（strict 的裁决在 `build()`），只在 docstring 提到。删掉参数或在 docstring 说明「由 `build()` 决定」。

### F5 · minor · `data/seed/DIFF.md` 首行把旧种子标成 `data/seed/.prev.jsonl.gz`

临时文件名进了提交物。`seed_diff.py` 可加 `--old-label`/`--new-label`，或 Makefile 把临时文件命名为 `data/seed/HEAD-vocab.jsonl.gz`；新种子一侧标 `data/seed/vocab.jsonl` 也宜写成 `vocab.jsonl.gz`。

### F6 · minor · `stats.variants` 口径与 SYNTHESIS §3.4 示例不同，未在产物中说明

实现计「带 `variant_of` 的记录数」（44），SYNTHESIS 示例 `"variants": 170` 是变体关系数（按表的 `lists[*].variants` 合计 168）。已自报；建议在 `data/lists/README.md §5` 的 stats 一句里写明两处口径，避免 S6 发布说明引错。

### F7 · minor · `render_attribution` §1 写死 `ecdict-sqlite-28.zip`

`--ecdict-release` 改为其他版本时，句子「Release used: X (`ecdict-sqlite-28.zip` → …)」会自相矛盾；用 release 推导 zip 名或只写 release。

### F8 · minor · 构建器不自检 `lemma == words.normalise_lemma(word)`（只靠 diff 兜底）

旧行的 `lemma` 由 `normalise.lemma_of(word)`（R1 折叠会去变音符）算出，而导入器 `seed_row` 用 `words.normalise_lemma`（`_clean` 不去变音符）：若上一版某行 display 含 `é` 之类字符，两者会不一致 → 导入 `lemma_mismatch`。当前真实种子 0 处不一致（`seed_diff` 的不变量与我的 `seed_row` 复算都为 0），且 `make seed` 中 diff 会在打包前抓住；但构建器写出前加一条断言（与 ⑤ 同级，成本一次遍历）更稳。

## 5 实现者自报偏离的核实

| # | 自报 | 核实 | 判定 |
|---|---|---|---|
| 1 | stats 多 4 键（`empty_translation/unparsed_notes/merged_heads/overrides_unused`）+ 可选 `built_at`；PLAN 键全在且同序 | `BuildStats` 字段顺序 = PLAN §4.6 顺序，4 键追加在末尾；S2 `full_seed` 读的四键无影响 | 接受（PLAN §4.2 ⑥/§4.3 R2/§4.8 (d) 都要用到） |
| 2 | `variants` 计记录数 44；per-list `heads` 含重复 | 属实 | 接受，见 F6 |
| 3 | `Ecdict(connection=)`/`from_sql`；`build()` 接受实例或路径 | 测试用；签名改为关键字参数（`out` 必填 kw）与 PLAN 的位置参数形式不同，无其他调用方 | 接受 |
| 4 | `reference` tsv 不要求 `word` 列 | 两份国名附表/词形表列名确实不同；只校验行数与 sha256 | 接受 |
| 5 | `--ecdict-release` | 见 §3.3 | 接受 |
| 6 | `--no-strict` 只降级内容类检查 | 代码与 README §5 一致；结构类（format/sha/expect_rows/未知码/retain/重复 lemma）始终失败（测试 `test_no_strict_…not_retain`） | 接受（PLAN 未定义其语义） |
| 7 | overrides 也作用于旧行（mum/p.e./e-mail），测试 (d) 排除这 3 个 | PLAN §4.1 把 `mum`、`e-mail(word)` 列进 overrides，SYNTHESIS §3.2.4 注明「现库该行今天就是这个错义项」，只对新行应用会让这几条永远 unused；实测 DIFF (a) 的 3 处字段变化恰为这 3 行 | 接受，但 PLAN §4.5「旧 lemma 逐字复制…只改 stages/sources/aliases」的措辞需由 S6/PLAN 负责人补一句「overrides 例外」 |
| 8 | DIFF.md 把 (e) 放到 (b) 之后 | 内容齐全，便于 `head -80` 验收 | 接受 |
| 9 | 沿用 S3a 两个 open point → 334 词组 / 456 新行 | PLAN §4.3 明言 R1–R12「以 WL §3.3 为准」，WL R9 的模板判定只用于归类跳过原因；多出的 1 条在 ±1% 内，README §5 已记录 | 接受；是否给 `overrides.tsv` 加 `phrase` 字段仍待 PLAN 负责人 |
| 10 | 未改 normalise.py 与夹具 | `normalise.py` sha256 与 S3a 评审记录一致 | 属实 |

## 6 测试质量

88 + 14 条新测试覆盖 PLAN §6 S3 (a)–(i) 全部条目，另有 manifest/overrides/aliases 校验 11+6 组参数化、外部 CET 表的在/不在两路、CLI exit 0/2、Ecdict 缓存与 R10 否定例、v2→v2 矩阵、`--only`、`--stats`、`--no-invariants`、`/dev/stdout` 写入。变异测试（改后立即恢复，sha256 核对相同）：

| 变异 | 被抓住的测试 |
|---|---|
| M1 关掉 `xs ⊆ zk` 断言 | `test_xs_not_subset_of_zk_fails_with_exit_2_and_writes_nothing`、`test_no_strict_downgrades_the_content_checks_but_not_retain` |
| M2 `NETWORK_PREFIX` 改成 `[网路]` | `test_network_prefix_is_removed_from_new_rows_and_counted` |
| M3 `LEGACY_CODES` 去掉 `gk` | `test_legacy_tokens_come_from_the_v1_flags_and_old_zk_gk_tokens_vanish` |
| M4 overrides 只作用于新行 | `test_overrides_translation_word_and_drop` |
| M5 diff「新 ⊇ 旧」不变量恒 ok | `test_removed_lemma_fails_the_superset_invariant` |
| M6 v1 旧文件也用 v2 标签 | `test_record_lemma_and_versions`、`test_fixture_pair_counts_matrix_and_invariants` |

未发现被削弱的断言；唯一放宽的是测试 (d) 排除 3 个被 override 的旧 lemma（见 §5 条 7，且 `test_overrides_translation_word_and_drop` 正向钉住了这 3 行的新值）。可加强处：`test_fixture_rows` 对 `sources` 用子集 `<=` 而非相等。

## 7 给 S6 / PLAN 负责人的两句话

- `data/lists/README.md §5`、`DESIGN.md §3.2`、发布说明引用 `stats.json` 时，`new_words`/`rows_changed_vs_previous`/`network_translations` 必须取 F1 修复后的文件（456 / 2,601+1,756 / 10）。
- PLAN §4.5 旧 lemma「只改 stages/sources/aliases」需补「`overrides.tsv` 的 translation/word 同样作用于旧行」（§5 条 7）。
