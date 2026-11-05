# 最终评审 · 数据与迁移安全（0011/0012/0013 · 种子导入 · stats.json · DIFF.md）

评审对象：工作区全部改动（`git diff` + 未跟踪新文件）对基线 `main @ 75df534`。评审方式：**对抗式、独立重跑**——所有排练都在
`$SCRATCH/final-data-migration/` 下自己 `cp` 的私有拷贝上进行（`word-dance.db` = 生产路径 `wd migrate`；`copyA` = `rehearse_migration.py` 路径；
`copyC` = 未迁移库上跑新导入器；`copyD` = 旧种子回退路径），全程未读写 `/Users/sqin/word-dance-data`，未启动 `wd serve`，未修改仓库任何文件。
比对工具：`$SCRATCH/final-data-migration/tools/snap.py`（只读打开，整表导出 words/user_settings/word_forms/word_images/users/user_words/
word_contents/kv/system_events/schema_migrations，其余表取内容 sha256）与 `tools/compare.py`（逐列、逐行、`sqlite_master`、`table_info` 差异）。
`$SCRATCH` = `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad`。

## 0 结论

**通过。** 三个迁移文件与导入器在线上库拷贝上的行为与 PLAN §2.2–§2.5、§4.7、§7.3 逐项一致；`stats.json` 与导入后库内计数完全相等，且构建器从
`data/lists/` + `HEAD` 种子重建的 `vocab.jsonl` / `stats.json` / `ATTRIBUTION.md` / `DIFF.md` 与提交物**字节相同**；回滚快照可还原到与迁移前逐行相同的库。
未发现 blocker / major。4 条 minor（1 条代码健壮性、2 条运维文档措辞、1 条对门禁自报的更正；§5）。

## 1 独立重跑记录

| # | 命令（在拷贝上） | 结果 |
|---|---|---|
| 1 | `cp $SCRATCH/live-copy.db $M/word-dance.db`；sha256 `1388bf21…1de2`（与 live-copy 相同；`-wal` 0 字节） | 25 张表；`schema_migrations` 1/8/9/10；words 9,162；word_forms 14,132；user_words 77；word_contents 49；word_images 31 |
| 2 | `WD_DATA_DIR=$M wd migrate --dry-run` | 恰好 `pending 0011_primary_stage.sql / 0012_word_images_meta.sql / 0013_word_forms_alias.sql` |
| 3 | `WD_DATA_DIR=$M wd migrate` | `applied` ×3，`schema version 13`；`$M/backups/pre-migrate-10-to-13.db.gz` 1,934,207 B |
| 4 | `rehearse_migration.py $A/word-dance.db`（copyA，未先 migrate） | `rehearsal OK (48 passed, 0 failed)`，退出 0；含逐行 +1（9,162 行 0 不符）、旗标和、`difficulty+1` 44/2/3 前后相同、CHECK/FK 探针、0012 四列、0013 alias、空库 0001→0013 |
| 5 | `wd import-seed --dry-run --report $M/dry.json` | `insert 456 / update 4357 / unchanged 4805; orphans 0; flags +{xs:584, zk:418, gk:450} −{zk:409, gk:1048}; stageless 238`；矩阵 = DIFF.md §(b) 逐格相同 |
| 6 | dry-run 前后 `shasum` 库文件 | `754216c8…e9cf` 不变；无 `-wal` 增长；snap 全表比对 **0 差异** |
| 7 | `wd import-seed` | `456 inserted, 4357 updated; 14196 word forms incl. 5 aliases (11 empty and 548 headword forms skipped); 238 stageless; 0.3 s` |
| 8 | `wd import-seed`（第二次） | `seed up to date (content sha256 ee985d900307…)`；snap 全表比对 0 差异 |
| 9 | `wd import-seed --dry-run`（已导入库） | `--force would insert 0 / update 0 / unchanged 9618; orphans 0`（TASKS WP1 验收行） |
| 10 | `WD_FULL_SEED_DB=$M/word-dance.db pytest -m full_seed` | 2 passed |
| 11 | `WD_DATA_DIR=$M wd check db` | `[ok] db`；`stage_min_consistent / xs_subset_zk / stages_json_known / seed_version_matches_file: ok` |
| 12 | §7.3 SQL 块（`sqlite3 -readonly "file:…?immutable=1"`） | 见 §3.5；`integrity_check ok`，`foreign_key_check` 空 |
| 13 | `gzip -dc pre-migrate-10-to-13.db.gz` → snap → 与迁移前 snap 比对 | **0 差异**（`integrity_check ok`，版本 1/8/9/10，9,162 行，`current_stage` 3/1） |
| 14 | `build_seed.py --previous <HEAD 种子> --ecdict stardict.db --out $M/seedbuild-out` + `seed_diff.py` | `vocab.jsonl` sha256 `ee985d90…c55c` = `stats.json.content_sha256` = `gzip -dc data/seed/vocab.jsonl.gz`；`stats.json` / `ATTRIBUTION.md` / `DIFF.md` 与提交物 `cmp` **IDENTICAL** |
| 15 | `scripts/pack_seed.sh --check`；`shasum ecdict-sqlite-28.zip` | `seed archive OK`（9,618 条）；zip = `ea01f76a…f3f6`（= `deploy/fetch_ecdict.sh` 钉死值） |
| 16 | `cd data/lists && shasum -a 256 -c SHA256SUMS` | 11 个文件全部 OK |
| 17 | pytest `test_db test_db_0012 test_db_0013 test_seed test_seed_diff test_seedbuild_* test_diag test_main_seed_check test_bank_defaults test_words_resolve` | 505 passed, 1 skipped |
| 18 | `cmp docs/SCHEMA.sql backend/wd/migrations/0001_init.sql` | 字节一致 |
| 19 | copyC（**未迁移** v10 拷贝）`wd import-seed --dry-run` / `wd import-seed` | 两者都以 `sqlite3.OperationalError: no such column: stage_xs` 回溯退出；库文件 sha256 不变、无 `-wal`、`kv`/`system_events` 不变 → 无数据危害，但见 F1 |
| 20 | copyD（已迁移+已导入）`wd import-seed --file <75df534 种子> --dry-run` / `--force` | dry-run：`orphans 456; flags +{zk:409, gk:1048} −{xs:584, zk:418, gk:450}`；真导：9,618 行**全部保留**，456 个新行未被触碰（stage_min 1/2/3 = 16/425/15 原样），user_words 77 / word_contents 49 不变 → 「从不删行」成立；见 F2 |

## 2 三个迁移文件的核对

### 2.1 `0011_primary_stage.sql`
- **DDL 覆盖面**：把 0001 的 `words` / `user_settings` 与 0011 的 `words_new` / `user_settings_new` 去注释、去 stage 行后 `diff` → **IDENTICAL**；
  `PRAGMA table_info` 前后比对：`words` 只多 `stage_xs`，其余列的 type / notnull / default / pk 全同；`user_settings` 只有 `stages_json` 默认
  `'["cet4","cet6"]'→'["xs","zk"]'`、`current_stage` 默认 `3→1`；`PRAGMA foreign_key_list` 四张表前后相同；`sqlite_master` 的 index / view / trigger 集合与 SQL 文本前后**完全相同**（`v_bank` 重建后与原定义一致）。0008–0010 对 words/user_settings 没有新增列或索引（已 grep），所以重建没有丢任何东西。
- **数据规则**：9,162 行 `stage_min` 逐行 +1（NULL 保持），`stage_xs` 全 0，其它列逐行相等（copy B 用 `before/words.jsonl` 与 `after-migrate/words.jsonl` 逐 id 比对，0 不符）；`current_stage` (1:3→4, 2:1→2)，`stages_json` 原样；`kv.seed_version` 删除（值 `a6812781…`），`system_events` 新增 1 行 `migration`/`"version": 11`；子表行数全部不变（user_words 77、push_items 98、review_logs 129 …），`foreign_key_check` 空 → `foreign_keys=OFF` 包裹的 DROP 没有级联。
- **CHECK 探针**（copyA）：`stage_min 0/6`、`stage_xs 2`、`current_stage 0/6` 均被拒；`user_words(word_id=999999)` 被 FK 拒；新设置行默认 `('["xs","zk"]', 1)`。
- 只在服务停止时应用（0011/0013 为重建）——与 DEPLOY §10 / 发布说明一致；见 F4 关于 `install.sh --no-restart` 的加固建议。

### 2.2 `0012_word_images_meta.sql`
纯附加：`prompt_version / model / text_free / eval_json` 四列；31 行既有图 `text_free 0`、三列 NULL；`text_free = 2` 被拒；行数与 id 不变。

### 2.3 `0013_word_forms_alias.sql`
与 0001 的 `word_forms` DDL 只差 CHECK 列表多 `'alias'`；14,132 行与 kind 分布 `{'3': 3111, 'd': 70, 'i': 2943, 'p': 3024, 'r': 305, 's': 4366, 't': 313}` 不变；`WITHOUT ROWID` 与 `ix_word_forms_word` 保留；`alias` 可插、`bogus` 被拒。

## 3 导入语义

### 3.1 覆盖（UPSERT）
after-migrate → after-import 逐列变化计数：`sources 4357`、`updated_at 4357`、`stage_min 2559`、`stage_gk 1498`、`stage_zk 827`、`stage_xs 584`、`translation 2`（`p.e.`、`mum` 的 overrides）、`display 1`（`E-MAIL→e-mail`）、`kind 1`（`e-mail` proper_noun→word）；**受保护列 0 变化**：`id / difficulty / content_state / image_state / active_content_id / active_image_id / created_by_user_id / created_at`。
新插 456 行 id 9163–9618 连续、无复用（0001 无 AUTOINCREMENT，但 DROP/RENAME 保留原 id，且 live 无空洞）。线上库没有非 seed 行（0 行 `source≠'seed'`），所以不存在用户词被种子覆盖的碰撞；`merged_into_word_id` 前后都为 0 行非空；trust 三旗标前后都是 (1,1,1)。
每用户表（users / user_words / word_contents / word_images / push_* / review_logs / jobs / …）内容哈希前后相同。

### 3.2 不删行
导入后 `words` 9,618 = 9,162 + 456，`removed 0`；copyD 用 75df534 旧种子 `--force` 回导：456 个不在文件里的行**原样保留**（含阶段旗标），dry-run 把它们列为 `orphans 456` 只报告不处理。

### 3.3 别名守卫
alias 行 5 条：`hot-dog→hot dog`、`mr→mr.`、`mrs→mrs.`、`ms→ms.`、`pe→p.e.`；`humourous` 既是 lemma 被守卫跳过（aliases.tsv 注释已预告；`stats.json.aliases` 6 ≥ 5，TASKS/`full_seed` 的 `0 < aliases ≤ stats.aliases` 成立）。
`word_forms wf JOIN words w ON w.lemma = wf.form AND w.merged_into_word_id IS NULL` = **0**。R7 的副作用正确：`excited→excite`、`stuck→stick`、`united→unite` 三条词形行在导入后消失（它们成了官方词头行）。

### 3.4 dry-run 零写入
库文件 sha256 前后相同（`754216c8…`），`-wal` 0 字节且未增长，整表快照 0 差异；`kv`、`system_events` 不动。第二次真导 `seed up to date`，快照 0 差异。

### 3.5 §7.3 SQL 块与 stats.json 对照（导入后）

| 项 | 库内 | `stats.json` |
|---|---|---|
| 旗标和 xs/zk/gk/cet4/cet6 | 600 / 2,549 / 3,260 / 4,722 / 7,671 | `per_stage` 相同 |
| `stage_min` 1..5 / NULL | 600 / 1,949 / 1,255 / 1,726 / 3,850 / 238 | `first_stage` 相同 |
| `kind` word/phrase/abbreviation/proper_noun | 9,066 / 395 / 36 / 121（全部 `source='seed'`） | `per_kind` 相同 |
| `word_forms` 按 kind | 3: 3113 · alias: 5 · d: 70 · i: 2942 · p: 3015 · r: 305 · s: 4433 · t: 313（合计 14,196） | — |
| 词头守卫 / 旧令牌 `zk`·`gk` / `legacy:zk`·`legacy:gk` | 0 / 0 / 2,099 · 3,829 | `tokens` 相同 |
| 只有 zk 一个旗标 / zk∧¬gk | 430 / 544（phrase 376 · word 156 · abbreviation 7 · proper_noun 5） | `only_stage.zk` 430；发布说明 §3.1 的 544 一致 |
| `user_settings` | `(1,'["zk","gk","cet4","cet6"]',4)`、`(2,'["zk"]',2)` | PLAN §8 第 8 步 |
| `v_bank` | 18 行（迁移前后、导入前后相同） | — |
| 课标外被持有 / 有内容或图 / 内容词无阶段 | 0 / 0 / 0 | PLAN §4.8 |
| 用户 2 的 10 个生词 | 10 个都带 `stage_xs=1`（发布说明 §3.4 的排序说明成立） | — |
| `tv`/`aids` abbreviation、`a.m.`、`bases` 两义 | 2、`a.m.`/abbreviation、2 | TASKS WP1 |

## 4 DIFF.md 抽查（30 词；「依据」= 在 `data/lists/` 原文件中的位置）

| lemma | 旧 → 新 | 依据 | 判断 |
|---|---|---|---|
| best | cet4 → xs zk gk cet4 | level2:53、level3:155、shmeea:170、hs20/hs25 `best 0` | 合理（旧种子漏了 zk/gk） |
| less | gk cet4 → zk gk cet4 | level3:789、hs20:1561、hs25:1604 | 合理 |
| an | gk cet6 → xs zk gk cet6 | level2:11 / level3:11 `a/an`（R3 并列）、senior `a (an)` | 合理；CET 旗标按规则原样保留（无 cet4） |
| excited | （新行）xs zk gk | level2:146、level3:483、shmeea:532、hs20/hs25 `excited 0`；R7 | 合理；`excited→excite` 词形行随之消失 |
| is | zk gk → xs zk gk | `inherit:be`（be 在 level2:42）；manifest `inherit_stages` | 合理；只继承官方阶段，不继承 be 的 cet4——与 R8 一致 |
| color | gk cet4 → xs zk gk cet4 | level2:106 `colour (AmE color)` 变体、senior `colour (color)` | 合理 |
| colour | zk gk cet6 → xs zk gk cet6 | 同上 + shmeea:321 | 合理 |
| Mr. | zk gk → xs zk gk；alias `mr` | level2:288 `Mr (AmE Mr.)`、shmeea:990、hs25:1803；aliases.tsv | 合理；`resolve("mr")` 经 alias 行命中 |
| a bit / a bit of | （新行）zk，phrase | phrases:14 `a bit (of)`（R9 展开两条） | 合理 |
| one | zk gk cet4 → xs zk gk cet4 | 2022 附表 数词-基数词:13、shmeea 附表:48、hs20 | 合理（A1/P1） |
| Monday | zk gk cet4 → xs zk gk cet4 | 2022 附表 星期:83、shmeea 附表:120、hs20:1719 | 合理 |
| China | zk gk cet4 → xs zk gk cet4（display `China`，proper_noun） | level2:91、附表 地理名称:103、shmeea `china`:286（R6 合并） | 合理 |
| weapon | cet4 cet6 → gk cet4 cet6 | hs20:2914 / hs25:3007 `weapon 2` | 合理（旧种子漏了 gk） |
| being | gk cet4 → zk gk cet4 | shmeea:162 | 合理 |
| billion | zk gk cet4 cet6 → gk cet4 cet6 | 只在 senior（`billion 2`）；shmeea 附表 `one billion` 按单 token 规则跳过 | 合理（P1 的单 token 口径） |
| twenty-first | zk（只 shmeea 附表 序数词:107） | 2022 附表无此词 | 合理 |
| mooncake | （legacy:zk）→ zk | 2022 附表 其他专有名词:167 | 合理 |
| chopstick | cet6 → zk cet6 | shmeea:290 | 合理 |
| email / e-mail | zk cet6 → xs zk gk cet6 / zk gk → zk | level2:142、senior `email`；shmeea:492 `e-mail (email)` | 合理；`e-mail` display 由 overrides 改为小写、kind 改 word |
| hot dog / hotdog | （新行）zk / zk gk cet6 → cet6 | shmeea:756 `hot-dog`（alias）；ECDICT `hotdog` 是另一义 | 合理（aliases.tsv 注释预告） |
| humorous / humourous | zk gk cet4 cet6（hs25:1 经别名）/ 保留行只剩 cet6 | hs25:1401 镜像拼写 `humourous`；aliases.tsv | 合理 |
| stuck / united | （新行）zk | shmeea 词头；overrides 自写 `stuck` 释义 | 合理（R7；对应词形行消失） |
| us | zk cet4 → xs zk gk cet4 | level2:463；`US/us` R6 合并 | 合理 |
| ad | gk cet4 → zk gk cet4 | level3 `AD`（R6 合并） | 合理 |
| cd / dvd / bookshelf / computer game / cd-rom / Dr / dept. / cance | → ∅（课标外） | 都不在任何官方文件（2022 附表 缩写 只有 CPC PLA PRC UN UNESCO WHO WTO） | 符合 A3/P6（只保留 `legacy:*`） |
| delighted | gk → ∅ | senior 只有 `delight 1`（hs25:777） | 符合规则（屈折形不是词头） |
| shanghai | gk → ∅ | 2022 附表 地理名称 27 条里没有 Shanghai；shmeea 附表 国家/大洲 也没有 | 符合规则；**产品可见**：上海本地词成课标外（`beijing` 单词本就不在种子里），可考虑日后经 manifest/overrides 处理，不是本轮缺陷 |
| saw / was / were / has / had / did / done / been | 无变化 / 不建行 | `inherit_stages` 只作用于上一版已有 lemma；`saw` 独立义项不继承 | 符合 R7/R8 |
| i | xs zk gk cet4，display `I`，kind proper_noun | — | 已知遗留（PLAN §9.2 #4），非本轮 |

DIFF.md §(b) 矩阵与 dry-run 矩阵 23 个格逐一相等；与 PLAN §4.8 复算的差异只有 zk 列 +1（1,949 vs 1,948；`new→2` 425 vs 424）、总行 9,618 vs 9,617，±1% 内。
§(d)「Lost every stage (238)」= 库内 238 个 `stage_min NULL` 行，0 个被持有 / 有内容 / 有图。4 条「译文仍含 `[网络]`」的新词组（`in one's opinion` 等）首行都是正规词典行，`[网络]` 只在第 2 行——与构建器「只去首行前缀」规则一致，属数据质量观察，不是缺陷。

## 5 发现

### F1 · minor · `backend/wd/seed.py:566-577`（`cmd_import_seed`）— 未迁移库上以回溯退出
- **现象**（copyC，schema 10）：`wd import-seed --dry-run` 与 `wd import-seed` 都抛 `sqlite3.OperationalError: no such column: stage_xs`（`plan_import` 的 SELECT，`seed.py:321`），Python 回溯而非一句话；`except (OSError, EOFError, ValueError, zlib.error)` 不含 `sqlite3.Error`，`current_version(conn) == 0` 的守卫只覆盖空库。
- **影响**：无数据危害（库 sha256 不变、无 `-wal`、`kv`/`system_events` 不变；真导入在事务内失败即回滚）。但 PLAN §8 第 6/7 步若颠倒，或 Lighthouse 上有人先 `import-seed`，得到的是回溯而不是「先跑 `wd migrate`」。
- **修法**：在 `cmd_import_seed` 里用 `db.pending_migrations(conn)` 非空即 `print("wd import-seed: N pending migration(s) — run `wd migrate` first")` 返回 1（与空库分支同口径）；并把 `sqlite3.Error` 加入 except 列表兜底。规格依据：PLAN §4.7 ⑦「守卫只报告不拒绝」针对的是种子内容，不是 schema 版本；DEPLOY §9 的 CLI 行为口径。

### F2 · minor · `docs/releases/2026-11-k12-stages.md:169`、PLAN §8 第 11 步（`PLAN.md:716`）— 「只退种子」路径的描述与行为不符
- **文档说**：旧种子 `--force` 回导后「`stage_xs` 全 0，新增 ≈ 455 行留下但无阶段」。
- **实测**（copyD）：不在文件里的 456 行**原样保留阶段**（`stage_min` 1/2/3 = 16/425/15，旗标和变为 `16|2540|3858|4722|7671`，即仍有 16 行 `stage_xs=1`）；导入器对 orphans 只报告不改写（`seed.py` docstring 与 `plan_import` 都如此，且这是更安全的行为）。
- **修法**：两处改为「新增 ≈ 455 行留下**并保留其阶段**（`--dry-run` 把它们列为 `orphans`）；`stage_xs` 只在这些新行上仍为 1」。只改文档。

### F3 · minor · 门禁自报更正（无需改文件；涉及 `data/seed/DIFF.md:907`）
- S7 门禁写「new→2 is 425 vs 424, the extra row is `an`」。`an` 不是新行：DIFF.md:907 把它列在「Stage changes」（`gk cet6 → xs zk gk cet6`），Added 表里没有 `an`。
- 实际差异来源：DIFF.md Added 的 123 个非词组新词与设计复算（`$SCRATCH/word-lists-synthesis/recount.out.txt`）的 123 个逐一相同；词组新行 333 vs 复算 332——多出的 1 行是上海**词组**，不是 `an`。数字仍在 ±1% 内，验收常量以 `stats.json` 为准（R-17），结论不变。

### F4 · minor（加固建议）· `deploy/install.sh:119-141` — `--no-restart` 下仍对运行中的单元执行重建迁移
- 代码在单元 active 且 `--no-restart` 时只打印 `NOTE: … pending migrations must be purely ADDITIVE`，随后照样 `wd migrate` + `wd import-seed`；0011/0013 是 DROP/RENAME 重建，老进程会在新 schema 上继续服务（PLAN §2.5 描述的「静默错位」），并且 `--no-restart` 末尾只 `start` 不 `restart`。
- 这与 DEPLOY §10 / PLAN §8 的**操作规则**一致（文档明确禁止），不属「规格未落实」，故定 minor；但本次发布正好带两个 stop-first 文件、下一站是 Linux/`install.sh`，建议加一道程序守卫：`--no-restart` 且单元 active 时，若 `wd migrate --dry-run` 列出的待办文件不在附加白名单（或文件头无 `-- additive` 标记）则退出 2 并提示去掉 `--no-restart`。

## 6 观察（非缺陷，记录备查）
- `wd migrate` 打印两次 `WD_SECRET_KEY is not set` 警告（Settings 被构造两次；基线已有，非本轮）。
- 迁移后文件 5.6 MB → 9.4 MB、942 空闲页：PLAN §8 第 9 步的 `ANALYZE + VACUUM` 仍需操作者执行（脚本只提示）。
- `wd` 关闭连接后 `-wal/-shm` 文件被删除（拷贝上验证），所以发布说明第 8 步 `sqlite3 -readonly "file:…?immutable=1"` 读到的是最新数据；若有人在服务运行时用 `immutable=1` 则会漏掉 WAL 里的提交——发布说明已限定「服务停着」。
- 25 个专有名词成为课标外（`shanghai`、`egypt`、`belgium`、`arab` …），是 A3「只用官方词头」的直接后果；对上海用户 `Shanghai` 不可筛选/推荐，值得产品侧知晓（已在 DIFF.md §(d) 可见）。

## 7 验收命令复跑结论
§1 表第 2–18 行全部退出 0 / 全绿；§7.3 期望逐项命中；`rehearse_migration.py` 在未迁移拷贝（48 项）与已迁移拷贝（37 项，含 `[skip] 0011 row-level`）都退出 0。
