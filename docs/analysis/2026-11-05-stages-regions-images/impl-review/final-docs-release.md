# 最终评审 · 文档与发布说明（对抗式）

评审对象：工作区全部改动（基线 `main @ 75df534`）里的文档面——`docs/DESIGN.md`、`docs/TASKS.md`、`docs/ops.md`、`docs/WORD_LIBRARY_CURATION.md`、`docs/QUICK_DEPLOY_AND_MOBILE.md`、`README.md`、`docs/DEPLOY.md`、`deploy/env.example`、`docs/CLAUDE_INTEGRATION.md`、`docs/API.md`、`docs/FRONTEND.md`、`docs/qa-frontend.md`、`docs/AI_FALLBACK_MODEL.md`、根 `ATTRIBUTION.md`、`data/seed/ATTRIBUTION.md`（生成件）、`data/lists/README.md`（新）、`docs/releases/2026-11-k12-stages.md`（新）、`Makefile` 注释；对照 PLAN §0 / §2.5 / §3 / §4.4–4.8 / §5 / §6 各切片的文档清单与「请求」、§8、§9，数字对照 `data/seed/stats.json`，行为对照代码并在线上库的私有拷贝上做了排练。所有核查都没有改动仓库文件；临时文件只在 `$SCRATCH/final-docs-review/`。

## 0 结论

**无 blocker；2 个 major（都在发布说明的上线/回滚步骤，且都是从 PLAN §8 原样继承的错误），8 个 minor（过时文案）。** 文档镜像与字节绑定全部复跑通过；PLAN §6 各切片要求的文档章节逐项都改到了；`$0.028`、`18 张/天`、`四阶段`、「mahavivo 中考/高中表是来源」、`kv.seed_version 是 .gz 文件哈希` 这几类过时描述在契约文档里已清干净（只剩 `TASKS.md:40/:204`、`DESIGN.md:43/:672`、`CLAUDE_INTEGRATION.md:411` 五处边角）；发布说明含 §8 的第 0–10 步、两处 ⚠ 不可逆标记（第 6、7 步）、§7 回滚（库与代码一起回 + 静默错位说明 + 只退种子）、用户 2 推荐顺序变化（§3.4 末条）、`push_batches` 旧索引、LRU 键失效、`zk ⊄ gk` 反例、配图一期行为、P1–P20 摘要与 §9.2 未决。两条 major 建议在打 tag 前修（各一两句话），并同步 PLAN §8 第 10/11 步。

## 1 复跑与核验命令

| 命令 / 核验 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q backend/tests/unit/test_schemas.py backend/tests/unit/test_docs_contract.py` | `30 passed`（提示词/schema ↔ CLAUDE_INTEGRATION §4/§5 逐字节；DEPLOY §4 ↔ `Settings` 双向；TASKS/DESIGN 签名） |
| `cd frontend && npx vitest run src/i18n` | `9 passed`（`zh.ts` ↔ FRONTEND.md §8 逐行 + 键值） |
| API.md §9 `ts` 代码块 ⊂ `frontend/src/api/types.ts` 逐字 | `True`（自写脚本比对） |
| `sqlite3 -readonly` S7 排练库 `integration-rehearsal/word-dance.db` | `zk=1 ∧ gk=0`：abbreviation 7 · phrase 376 · proper_noun 5 · word 156 = **544**；只有 zk 旗标 **430**；`total 9618`；`schema_migrations 1,8,9,10,11,12,13`；`user_settings (1,'["zk","gk","cet4","cet6"]',4) / (2,'["zk"]',2)`；`kv.seed_version = ee985d90…c55c` —— 与发布说明 §3.1 / §2 / §6 第 8 步一致 |
| `sqlite3 -readonly "file:<copy>?immutable=1"`（macOS sqlite3 3.51.0，无 `-wal/-shm`） | 成功 `9618`；裸 `-readonly` 同一文件 → `unable to open database file (14)`，与发布说明第 8 步的说明一致 |
| `cd data/lists && shasum -a 256 -c SHA256SUMS` | 11 个文件全部 `OK`；`aliases.tsv` 6 行、`overrides.tsv` 23 行，与 README/ATTRIBUTION 所述一致 |
| `data/seed/DIFF.md` | 9,162 → 9,618（+456）；矩阵列合计 600 / 1,949 / 1,255 / 1,726 / 3,850 / 238；5 条不变量 PASS |
| 只退种子排练（私有拷贝 = S7 排练库；`git show 75df534:data/seed/vocab.jsonl.gz`） | `--dry-run`：`insert 0 / update 4357 / unchanged 4805; orphans 456 (kept); flags −{xs:584, zk:418, gk:450}`；`--force` 后：`stage_xs=1` **16** 行、`stage_min` 1:16 / 2:2524 / 3:1807 / 4:1577 / 5:3694，`a bit`/`qipao`/`hot pot` 仍 `stage_zk=1`，`thirteenth`/`hundredth` 仍 `stage_xs=1` → 见 major 1 |
| `grep` 过时字面量（`0.028`、`18 张`、`9,162`、`四阶段`、`1–4`、`zk→1`、`mahavivo`、`sha256 of the file`） | 契约文档只剩 §3 列出的五处；`0.028` 只在 `test_budget.py`/`test_admin_ops.py` 当任意金额用（无需改）；`mahavivo 中考/Highschool` 全部写成「已停用/`legacy:*`」 |
| 代码核对 | `card_svg.py:6,158` LRU 键 `(word_id, active_content_id, updated_at)`（发布说明 §3.4 正确，DESIGN §9 旧文案错）；`pos.ts` `u: 'int.'`；`0001_init.sql:147-148` 旧默认 `'["cet4","cet6"]'/3`；`config.py:129/158` `0.50` / `image_kid_stages=()`；`budget.py:33` `svg 0.03`；`diag.py:144-156` 文件不可读 = 1 violation；`rehearse_migration.py:205,302-320` 已迁库跳过 +1 比对、空库 0001→latest 检查；`main.py:316-317` 哈希相同时**静默返回** → 见 major 2 |

## 2 PLAN §6 文档清单逐项

| 切片 → 文档 | 结果 |
|---|---|
| S2 → S5：`DEPLOY.md` CLI 行 `import-seed [--file] [--force] [--dry-run] [--report]`、`WD_SEED_PATH` 内容 sha256、§5 `wd migrate` 段 0011/0013 stop-first | ✓ `:417`、`:304`、`:361` |
| S2 → S4：`API.md:169` 排序表达式 `COALESCE(difficulty + 1, stage_min, 6)` + 注释 | ✓ |
| S2 → S6：`DESIGN.md` 种子版本 = 内容 sha256（`:172`）、kv 清单（`:184`）、`word_forms` 加 `alias`（§3.1）、§6.1/6.2 默认与预设；`TASKS.md:160-182` 读 `stats.json`、删「keep verbatim」、内容哈希、`--dry-run`；`WLC §1.2` | ✓ 全部 |
| S3 → S6：`DESIGN §3.2` v2 键、`stage_min = min(stage_to_index)`、令牌表、`:209` 引用 `stats.json`；`README.md:5,9,78,103`；`TASKS.md:162` | ✓ |
| S3 → S5：`DEPLOY.md:410` `make seed` 新参数 | ✓（但 `--previous` 写法与 Makefile 实际不符，minor 5） |
| S4：`API.md` §3.3 十行、`FRONTEND.md` §3.4 + `:50/:56/:85/:89/:147`、`qa-frontend.md:36,42` | ✓ 逐项 |
| S5：`CLAUDE_INTEGRATION.md` §5 标题、§5.1/5.2/5.5、§6.1、§6.4（10–240）、§6.7、§7 成本；`AI_FALLBACK_MODEL.md:29`；`DEPLOY.md` `WD_IMAGE_KID_STAGES` 行 + `:326/:434`；`env.example` | ✓（§7 仍写「9,162-word seed」，minor 4） |
| S5 → S6：`DESIGN.md:28,518,550` 成本、§9 伪代码（功能词门/两轮/重试）、Selection 三张表 + 豁免、provider 参数与条款（Pixabay 禁批量、Openverse 配额与注册、Pexels 不进 kid 轮）、`WD_IMAGE_KID_STAGES`；`ops.md:198,202`；`WLC:65,183` | ✓ 全部 |
| S5 → S3：根 `ATTRIBUTION.md` §3.1/§3.2 参数句、§3.4「图内不含文字 + `aigc-label`」 | ✓ |
| S3：根 `ATTRIBUTION.md:14` 引用 `stats.json`、§2 改写为 2a 官方词表 / 2b mahavivo CET（可选）/ 2c overrides、注明中考/Highschool 两表已停用；`data/seed/ATTRIBUTION.md` §1–§5 由 `render_attribution` 生成（含 `provisional`、`absent`、令牌计数 = `stats.json.tokens`） | ✓ |
| S6：`DESIGN.md:72` 术语表、`:32,40` 五页签、§3.1「当前 schema = 0001+…+0013」+ 目标模型与触发条件、§6.3 `push_batches` 旧索引注、`QUICK_DEPLOY` Mac 段「先备份、再停、再切、再起」+ 链接、`README.md:3` + `docs/releases/` 行 | ✓ |
| S6：发布说明必含项（阶段重编号、词集变化与「仅本阶段新增」、课标外、用户 2 顺序、`push_batches` 旧索引、`updated_at` 前移 → LRU 失效、回滚与静默错位、`zk ⊄ gk` 反例、配图一期）+ 本次评审要求的 §8 步骤、不可逆标记、回滚、P1–P20 | ✓ 全部在（§2、§3.1–3.4、§5、§6 第 0–10 步、§7、§9）；`zk ⊄ gk` 用 SQL 复算为 544 并说明与 PLAN「212」口径不同（正确） |

数字核对（`stats.json`）：`DESIGN`/`README`/`TASKS`/`WLC`/`ATTRIBUTION` 不再手抄验收数字，只引用 `stats.json`；`QUICK_DEPLOY §1.3` 引用的 600 / 2,549 / 3,260 / 4,722 / 7,671 / 9,618 与 `per_stage`/`total_words` 相同；`data/seed/ATTRIBUTION.md` 的 rows/members/tokens 与 `stats.json.lists/tokens` 逐项相同；发布说明 §3.1 的 9,618 正确，§3.2 的 ≈ 值是 PLAN 复算值（minor 1）。

## 3 发现

### Major

**M1 · 发布说明 §7「只想退种子」描述的结果与导入器行为不符**（`docs/releases/2026-11-k12-stages.md:168-169`；PLAN §8 第 11 步同句）
- 文中：「旧文件把 9,162 行的阶段列改回（`stage_xs` 全 0，`stage_min` 按新索引 2..5），新增 ≈ 455 行留下但无阶段」。
- 实测（私有拷贝 = 迁移 + 新种子已导入的 S7 排练库，`wd import-seed --file <75df534 的 vocab.jsonl.gz> --force`）：导入器按 lemma UPSERT、从不删行、**不碰文件里没有的 lemma**（`seed.py:356` 把它们列为 `orphans … kept`），所以新种子新增的 456 行（上海词组、附表专名、16 个只在新词表里的小学词）**保留新种子的阶段**：`stage_xs=1` 仍有 16 行、`stage_min=1` 16 行，`a bit`/`qipao`/`hot pot` 仍 `stage_zk=1`，`thirteenth`/`hundredth` 仍 `stage_xs=1`；初中页签仍会显示 382 条只在初中的词组。`--dry-run` 也只报 `flag_removed xs 584`（不是 600）。
- 后果：操作者按此句预期「退种子后小学页签为空、词组不可见」，与实际相反；若据此判断回滚是否生效会误判。
- 修法：改为「旧文件只改写它含有的 9,162 个 lemma：这些行 `stage_xs` 清零、`stage_min` 回到 2..5、`legacy:*` 令牌被旧 `zk/gk` 令牌替换；新种子新增的 456 行不在旧文件里，导入器从不删行也不改它们，它们保留新种子的阶段（`--dry-run` 列为 `orphans … kept`），需要时用 `UPDATE words SET stage_xs=0,stage_zk=0,stage_gk=0,stage_min=NULL WHERE source='seed' AND sources NOT LIKE '%legacy:%' AND …` 另行处理或直接走快照回滚」。同步 PLAN §8 第 11 步。

**M2 · 发布说明 §6 第 10 步要求日志里「有 `seed up to date`」，但服务启动时不会输出这一行**（`docs/releases/2026-11-k12-stages.md:143`；PLAN §8 第 10 步同句）
- `main.seed_check`（`backend/wd/main.py:316-317`）在 `kv.seed_version == seed_digest(path)` 时 `return`，不记日志；「seed up to date」只由 CLI `wd import-seed` 打印（`seed.py:534,546`）。启动日志只会在哈希不同时出现 `seed version changed; importing`（`event=seed_import`），正常情况下什么都没有。
- 后果：验收清单里有一项永远勾不上，操作者可能误以为导入没生效。
- 修法：把该项改成可核验的信号——「日志**没有** `seed_import` / `seed_import_failed` 事件（第 7 步已导入，启动时哈希一致）；或 `WD_DATA_DIR=$D .venv/bin/wd import-seed --dry-run` 首行为 `seed up to date (…)`；或管理页「词库版本」= `stats.json.content_sha256`」。同步 PLAN §8 第 10 步。

### Minor

**m1 · 发布说明 §3.2 的 ≈ 数字是 PLAN 复算值而非 `stats.json` 实际值，且与 §3.1 自相矛盾**（`:61-62`）——初中 ≈ 2,548 / `stage_min` zk ≈ 1,948 / ≈ 9,617 行 / 新增 ≈ 455 / 词组 ≈ 333，而 `stats.json` 为 2,549 / 1,949 / 9,618 / 456 / 334；同段写的公式「= `total_words` − 9,162」算出来是 456；§3.1 已写 9,618 条；`QUICK_DEPLOY §1.3` 用的是实际值。发布时 `stats.json` 已定稿，建议直接写实际值（或只留指针）。

**m2 · `docs/TASKS.md:40` 仍写 `kv.seed_version` ≠「sha256 of the file at WD_SEED_PATH」，`:204` 仍写「mapped to the 1–4 column」**——P0/WP2 段落未随 WP1 一起更新；改为「content sha256 of the (gunzipped) file（`seed.seed_digest`）」与「1–5 column」。

**m3 · `docs/DESIGN.md` 三处旧文案**：`:43`「(also outside the 4 lists)」→「outside every official list」；`:672` 走查「neither string is in the 9,162-word seed」→「in the seed」；`:588` 模板卡 LRU「keyed by `(word_id, active_content_id)`」与 `images/card_svg.py:6,158` 的 `(word_id, active_content_id, updated_at)` 不符——发布说明 §3.4「`updated_at` 前移 → LRU 键失效」正是依赖第三个分量，DESIGN 应改成三元组。

**m4 · `docs/CLAUDE_INTEGRATION.md:411`「whole 9,162-word seed ≈ $37」**——种子已是 9,618 词（≈ $38.5）；改为「the whole seed (`stats.json.total_words` words) ≈ $38」。

**m5 · `docs/DEPLOY.md:408` `make seed` 注释写 `--previous data/seed/vocab.jsonl.gz`，而 `Makefile:109-113` 实际把 `git show $(SEED_BASE):data/seed/vocab.jsonl.gz`（默认 HEAD）写到临时文件再传 `--previous`，并有 `SEED_BASE` 参数**（S3b F1 的修正）；`data/lists/README.md §5` 写对了。DEPLOY 该行应与 Makefile 一致并列出 `SEED_BASE`。

**m6 · 发布说明 §6 第 0 步依赖会话级临时路径**（`$SCRATCH/live-copy.db`、`$SCRATCH/ecdict-dl/ecdict-sqlite-28.zip`、`/private/tmp/claude-501/…/<会话>/scratchpad`）——这些目录随会话消失，Lighthouse 上也不存在。可持久化的写法：「停服务后 `cp $D/word-dance.db`（或运行中 `VACUUM INTO`）到私有目录」「ECDICT zip 在 `deploy/fetch_ecdict.sh` 下载到的位置核对 `ea01f76a…f3f6`」。

**m7 · 发布说明 §3.1 留有一条待办**：「`stats.json` 目前没有 `zk_not_gk` 键（建议 S3 加上后这里改为引用）」——发布说明不宜带对实现者的建议；要么给 `stats.json` v2 加键（需同步 PLAN §4.6 的键清单与 `seedbuild/build.py`），要么删掉这句、以 SQL 为准。

**m8 · 代码文本里的 9,162 残留**：`backend/tests/conftest.py:41` skip 原因「needs the full 9,162-word seed」；`backend/wd/seedbuild/build.py:9`「the 9,162 existing rows」（下一次重建就不对了，应写「the previous seed's rows」）；`docs/WORD_LIBRARY_CURATION.md:23,165`「现状：9,162 个种子词 / 48 个词有内容 / 31 张图」是 2026-10 的快照，发布后应标注日期或更新。

## 4 未发现问题的核查项（供交叉参考）

- 过时描述清单：`$0.028` ✓ 无；`18 张/天` ✓ 无；`四阶段 / 1–4 / zk→1` ✓ 只剩 m2/m3；`mahavivo 中考/高中表作为来源` ✓ 无（根 ATTRIBUTION 2b、`data/seed/ATTRIBUTION.md §3`、DESIGN §3.2 令牌表、WLC §1.2 都写成「已停用 / `legacy:*`」）；`kv.seed_version 是文件哈希` ✓ 只剩 m2（DESIGN `:172/:184`、DEPLOY `:304`、WLC §1.2、TASKS WP1 都已改为解压内容 sha256）。
- 发布说明 §9 P1–P20 与 PLAN §9.1 逐条一致（默认值与反悔代价均保留），§9.2 未决 10 条有摘要。
- 发布说明 §6 第 0 步说明了与 PLAN §2.5 第 2–3 步的顺序差异（先 `rehearse_migration.py` 再 `wd migrate` 会让脚本 `[skip] 0011 row-level +1`），与 `scripts/rehearse_migration.py:205` 一致。
- `docs/SCHEMA.sql` 未改（`git status` 不含它）；`docs/DEPLOY.md §4` 表与 `Settings` 双向比对、`env.example` 均过 `test_docs_contract`。
- `data/lists/README.md` 的「11 个词表 + 3 份说明 + 1 份差异 = 15 个已交付文件」「`policy: reference` 两份国家名称附表与上海词形表不产生成员」「`make seed` 以已提交种子为基线、两次构建逐字节相同」与 Makefile/`stats.json`（`shmeea20:forms`/`hs25:app`/`hs20:app` members 0）一致；§5「已知口径差异（+1 行：`an`、334 条词组、`weapon`）」与门禁报告一致。
