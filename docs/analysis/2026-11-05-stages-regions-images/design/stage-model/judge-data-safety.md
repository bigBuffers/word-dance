# 评审：阶段模型三份设计 — 「迁移与数据安全怀疑者」视角

评审对象：`design/stage-model/{minimal-delta,learner-first,stages-as-data}.md`（全部逐字读完）。基线 `main @ 75df534`；线上只读副本 `scratchpad/live-copy.db`（9,162 词、2 用户、`schema_migrations` 到 10）；日期 2026-11-06。本评审只读仓库，不改代码；所有排练都在我自己的目录 `scratchpad/judge-data-safety/` 下的私有拷贝上做，绝不触碰 `live-copy.db` 本身与 `/Users/sqin/word-dance-data`。

评审姿态：默认每个未被证明的说法都是错的。三份设计里凡是能用代码、线上副本或真实 `run_migrations` 复核的说法我都复核了；复核不了的（性能探针脚本、各自的词表模拟脚本）不替它们执行，只做独立重算或标「未复现」。

---

## 0. 我做了什么（核验范围）

| 项 | 做法 | 结果 |
|---|---|---|
| 引用抽查 | 三份设计引用的代码位置按 75df534 重新打开 ≈45 处（要求 ≥10）：`db.py` 运行器与文件名正则、`0001_init.sql`（`user_settings` :139-160、`words` :166-204、索引 :205-210、`v_bank` :572-576、`kv` :50-54、`system_events` :59-64、`push_batches.settings_json`）、0008/0009/0010 是否 `ALTER` 过 `words`/`user_settings`、`schemas.py` :25/:26/:47/:51/:52/:56-67/:65/:245-249/:360-364/:448-457/:472/:488/:708/:1335、`seed.py` :43/:47-68/:72-82/:184-185/:204-208/:260-263、`services/words.py` :39/:143-151/:228-229/:563-597/:663-677、`services/ecdict.py` :28/:117-123/:173-177、`routers/vocab.py` :52-56/:78/:86-106、`services/bank.py` :85-86/:161-182、`security.py` :597/:612-614/:661-664、`services/screen.py` :34-36/:44/:46-47/:51-56、`services/batches.py` :60/:232-234/:272/:314-318/:698、`ai/prewarm.py` :32-39、`ai/content.py` :46/:48/:49/:88、`main.py` :307-319/:482-485、`scripts/check_contract.py` :157-170/:236-253/:257-281、`types.ts` :5-6/:37/:45/:52/:73、`StageChips.tsx` :7-37、`ScreenPage.tsx` :20/:31、`WelcomePage.tsx` :30-42/:72-73、`VocabPage.tsx` :29/:202/:232、`zh.ts` :25/:28-29/:86、`AdminPage.tsx:36`、`SettingsPage.tsx` :72-77/:301-305、`ScreenRunPage.tsx` :33-35、`routers/auth.py` :154-162、`routers/admin_ops.py` :370-381、`services/stats.py` :173-180、`endpoints.ts` :80-85、`AuthContext.tsx` :66-70、`diag.py` 存在、测试 `test_db.py` :13-17/:50-52/:283-310/:362-366、`test_screen.py` :116/:129-136、`test_api_schemas.py` :32-39、`test_vocab.py` :69-79/:111/:153-161、`test_onboarding.py` :98/:120/:139、`test_settings.py` :57-58/:88/:109-112、`test_seed.py` :90-100/:204/:294-298/:339-353、`test_words_resolve.py` :279/:346/:478、`test_history.py:112`、`test_auth.py:82`、`test_security.py:315`、`test_reports.py` :29/:87、`test_batches.py:127`、`test_content_apply.py` :255-257、`test_schemas.py` :122-127、`conftest.py` :35-46、`Makefile` :77-81、`docs/TASKS.md` :166-182、`docs/DESIGN.md` :72/:186/:202/:209/:322/:330/:345-350、`docs/API.md` :155/:160/:167/:169/:239-240/:459-460、`docs/DEPLOY.md` §5 restore / §10、`docs/CLAUDE_INTEGRATION.md:211`、`content_system.txt` :1/:11、`scripts/build_seed.py` :15-17/:25/:74/:81-88/:105-106/:112-127/:147/:150-151/:191/:196、`smoke.py` :352/:614、`eval_provider.py:107`、`docs/SCHEMA.sql` 与 0001 字节比对 | **全部属实**（行号最多偏 1–3 行，如 `check_contract.py` 的「:158-170」实为 :157-170、「:260-272」实为 :257-272；`content_system.txt:11` 的难度图例实际在第 11 行以「8. difficulty」开头）。三份设计引用的 INDEX/facts/verify 条目（stage-model-9/11/12/13、verify stage-model 遗漏 1-4、seed-pipeline-10/11/12/15/27、verify seed-pipeline O3、ai-prompts-stages-14、verify ai-prompts-stages 遗漏 1、frontend-stages-12/13/14/15/16/19/20）也都存在且内容与引用一致 |
| 线上副本数字 | `python3.12 -I` 以 `?mode=ro` 打开 `live-copy.db` | 2 用户（sqin admin / kimi user）；`user_settings` `(1, ["zk","gk","cet4","cet6"], 3)`、`(2, ["zk"], 1)`；`stage_min` 2,099/1,792/1,577/3,694；旗标 2,099/3,829/4,722/7,671；`difficulty` 49 行（= `stage_min` 44、< 2、> 3；取值 1:2、2:1、3:43、4:3）；`word_contents` 49、`word_images` 31；`kv` 15 键含 `seed_version`；`push_batches` 4 行全部 `"current_stage": 3`；`user_words` 67/10（new+learning 17/1）→ `v_bank` 18 行；25 表 1 视图 0 触发器；引用 `words(id)` 的外键恰 9 条，无表引用 `user_settings`；文件 5,644,288 B（1,378 页 × 4,096，空闲页 0）；Python 侧 `legacy_alter_table=0`，`/usr/bin/sqlite3` 3.51.0 默认 `legacy_alter_table=1`。**三份设计引用的所有线上数字与此一致** |
| 三份 0011 独立复跑 | 不执行任何一份的排练脚本；自写 `judge-data-safety/rehearse.py`，用 `.venv/bin/python -I`（SQLite 3.54.1）调真实 `wd.db.run_migrations`，迁移目录 = 仓库 4 个文件 + 各自的 0011（minimal/stages-as-data 用其 scratchpad 的 SQL 文件；learner-first 的 scratchpad **没有** SQL 文件，从设计稿 §3.6 第 163-280 行原样抽出） | 见第 2 节：三份都一次通过 |
| 词表成员不变式 | 用词表任务**已交付**的 `data/lists/{moe-2022-level2.txt, moe-2022-level3.txt, shmeea-2020-junior.txt, moe-2025rev-senior.tsv, moe-2020-senior.tsv}` 对 `live-copy.db` 独立重算（`judge-data-safety/lists_check.py`） | 见 §3.3 与 §4.4 |
| 性能 | 在我迁移出的 `sad.db`（tag 表）与 `live-copy.db`（旗标列）上各跑 30 次取中位数 | Q1 词库页 cet4 按词频 50 条：旗标 1.13 ms / tag 0.68 ms；Q2 全阶段计数单条 `CROSS JOIN GROUP BY` 3.04 ms vs 单阶段旧查询 1.36 ms（×4 ≈ 5.4）；Q3 候选 `[zk,gk]` 15 条：1.24 → 1.48 ms。与 stages-as-data §3.5.1 的量级一致 |

两条共同事实先摆出来，后面三份都要对照：

- **0008/0009/0010 没有 `ALTER` 过 `words` 或 `user_settings`**（0008 只建索引，0009 只 `UPDATE`，0010 `ALTER TABLE ai_calls`），线上 `words`/`user_settings` 的列集合与 0001 完全相同。所以三份设计把 0001 的 DDL 整段抄进 0011 重建，不会丢任何列——这是我最先要排除的「行数不变但列丢了」风险，已排除。
- **运行器确实把文件包在一个 `BEGIN IMMEDIATE` 里**：`db.connect` 用 `autocommit=True`（`db.py:97`），`executescript` 不会隐式 COMMIT（`:231`），文件自己 COMMIT 会被 `:233-234` 拒绝；`foreign_keys=OFF` 在 BEGIN 之前（`:227`），`foreign_key_check` 后由运行器写 `schema_migrations`（`:239`）。三份设计对运行器约束的描述全部正确。

---

## 1. 三份 0011 的独立复跑结果

| 项 | minimal-delta `0011_primary_stage.sql` | stages-as-data `0011_stages_as_data.sql` | learner-first `0011_stage_xs_renumber.sql` |
|---|---|---|---|
| `applied` / 耗时 | `(11,'primary_stage')` 0.041 s | `(11,'stages_as_data')` 0.049 s | `(11,'stage_xs_renumber')` 0.039 s |
| 行数变化 | `schema_migrations` 4→5、`kv` 15→14，其余 23 表不变 | `schema_migrations` 4→5；新表 `stage_defs` 7 / `stage_presets` 5 / `word_stage_tags` 18,321；其余不变 | `schema_migrations` 4→5、`kv` 15→14、`system_events` 17→18 |
| `integrity_check` / `foreign_key_check` | ok / 空 | ok / 空 | ok / 空 |
| 重建后外键仍生效 | 是（`INSERT user_words(word_id=999999)` 被拒） | 是 | 是 |
| `words` 列 | 0001 的 35 列 + `stage_xs`（插在 `stage_zk` 前，`INSERT…SELECT` 显式列名） | 去 4 旗标列，`stage_min TEXT REFERENCES stage_defs` | 同 minimal |
| 数据映射 | `stage_min` 逐行恰好 +1（0 行不符）；旗标逐行不变；`difficulty + 1 = stage_min` 44/2/3（与迁移前 44/2/3 相同，设计的 D5 论证成立） | `stage_min` 码 `zk 2,099 / gk 1,792 / cet4 1,577 / cet6 3,694`，与整数分布逐一对应（0 行不符）；tag 与旧旗标逐词一致（0 行不符） | `stage_min` 逐行 +1（0 行不符）；`push_batches.settings_json.current_stage` 4 行 3→4；`system_events` 末行 `('migration', {"version": 11, …})` |
| 两个用户 | `(1, 4)` `(2, 2)`，`stages_json` 原样 | `(1, 'cet4')` `(2, 'zk')` | `(1, 4)` `(2, 2)` |
| 新 DEFAULT | `'["xs","zk"]'` / `1` | `'["xs"]'` / `'xs'` | `'["xs","zk"]'` / `2` |
| `v_bank` | 存在，18 行 | 存在，18 行 | 存在，18 行 |
| 文件膨胀 | 2,307 页 / 938 空闲 = 9,449,472 B（与设计说的 9.4 MB 一致） | 2,485 页 / 932 空闲 = 10,178,560 B（一致） | 2,307 页 / 938 空闲（设计说 ≈9.4 MB，一致） |
| 二次运行 | `applied=[]` | `applied=[]` | `applied=[]` |

结论：**三份迁移 SQL 本身在 SQLite 3.54.1 下都是安全的**——没有一份会丢行、丢列、丢外键或留下孤儿。差别不在 SQL，而在（a）证据：learner-first 的 SQL 在设计稿提交时从未被跑过（见 §3.3）；（b）SQL 之外的东西：种子流水线、词表接口、契约门禁、验收能不能真的跑。

---

## 2. minimal-delta 评审

### 2.1 正确性与数据安全（核验属实的部分）

- 0011 全文与其 scratchpad 文件一致，排练数字（0.041 s、`kv` 15→14、9,449,472 B、设置行 `(1,4)/(2,2)`、`difficulty+1=stage_min` 44/2/3）我全部独立复现。
- `ecdict.py:177` **必须改**的判断正确：`STAGE_TAGS` 变成 `("cet4","cet6")` 后 `STAGE_TAGS.index(stages[0]) + 1` 会把 ECDICT 四级词算成 1（= 小学）。这是三份里对这个陷阱写得最明确的一份。
- `DROP VIEW v_bank` 先行、显式列名 `INSERT…SELECT`、`NULL + 1 = NULL`、`merged_into_word_id REFERENCES words(id)` 按名解析、`user_settings` 无子表、索引 6 + 1、`VACUUM` 不能在事务内——逐条与 `db.py`/`0001_init.sql`/线上 `pragma_foreign_key_list` 核对无误。
- `index_to_stage` 的范围硬编码 `4`（`schemas.py:65`）被列为必改项 ✓；`bank.py:181` 静默回落、`ScreenPage.tsx:31` 静默丢弃、`check_contract.py:274-281` 顺序敏感 ✓。
- 「没有只回代码的回滚」成立，但对**线上这两个用户**的实际表现比设计写的更阴险：旧代码对 `current_stage=4` 不会抛错，而是把 sqin 的主攻阶段静默显示成「六级」、kimi 的显示成「高中」（`index_to_stage(4)='cet6'`、`(2)='gk'`）；真正 500 的是词库/筛词列表——`stage_min=5` 的 3,694 个词不满足 `WordBrief.stage_min: StageIndex = Literal[1,2,3,4]`，响应校验失败。建议把「静默错位」写进发布说明，它比 500 更难被发现。

### 2.2 严重缺陷（未必致命，但照设计原文实施会出问题）

1. **与词表任务的接口约定（§3.8.3）和实际交付不符，而且差在最要命的地方。** 设计要求 5 个文件 `moe2022_level2.txt / moe2022_level3.txt / shmeea2020_junior.txt / moe_hs2020.txt / moe_hs2025.txt`，「一行一个词头、并列项已拆分、缩写书写与 ECDICT 一致」，`parse_headwords` 不做任何括号/斜杠处理。词表任务实际交付的是 `data/lists/moe-2022-level2.txt`（505 行，含 `a/an`、`be (am, is, are)`、`child (pl. children)`、`colour (AmE color)`、`Mr (AmE Mr.)`、`PE (=physical education)`）、`moe-2022-level3.txt`（1,600 行，同样体例，61 条带括号、9 条斜杠并列）、`shmeea-2020-junior.txt`（1,724 行，`although/though`、`exam=examination`、`bund (the Bund)`）、`moe-2025rev-senior.tsv` / `moe-2020-senior.tsv`（**TSV，`word\tlevel` 两列**，`a (an)`、`café`、`ice-cream`）；`moe-2022.README.md §4.2` 第 3-4 条明说「括号注原样保留」「拆分规则留给种子构建阶段」。按设计的解析器，`be`、`child`、`colour`、`mr`、`maths`、`a`（L2 里是 `a/an`）等 23 + 61 条带括号的词头会整行进 `missing_from_ecdict`，对应的库内词**失去 xs/zk 旗标**——我用交付文件直接匹配 `words.lemma`：L2 505 行只有 480 个命中 lemma，10 行未命中里 9 行是这种变体行（`a/an`, `be (am, is, are)`, `bike (=bicycle)`, `child (pl. children)`, `colour (ame color)`, `father (dad)`, `favourite (ame favorite)`, `foot (pl. feet)`, `goodbye (bye)`…），只有 `excited` 是真缺。`be`/`a`/`have` 恰好是 kimi 生词库里的词。设计 §7.1 第一行把「并列未拆」列为中概率风险、缓解是「构建后检查 `missing_from_ecdict`」——人工检查不是机械保证。**归一化（括号剥离、`/` 与 `=` 拆分、`AmE` 变体、句点缩写别名）必须进 `build_seed.py`，不能推给词表任务**；learner-first 的 `relabel_seed.py` 恰好写了这张别名表，可直接嫁接。
2. **`STAGE_TAGS = ("cet4","cet6")` 有一个未列出的副作用。** `ecdict.has_stage_tag`（`ecdict.py:122-123`）= `bool(self.stages)`，而 `services/words.py:669,673` 用它决定「用户输入的屈折形式要不要回指原形」：`if pointer and not entry.has_stage_tag and not entry.frq` / `base.has_stage_tag or base.frq > 0`。缩小 `STAGE_TAGS` 后，只带 `zk`/`gk` 标签的 ECDICT 条目变成「无阶段标签」，回指启发式的触发条件与成功条件同时改变。影响面是用户自添词路径（线上 0 个用户词，且本机未装 ECDICT），所以今天无感，但这是行为变更而非常量变更，设计把它记成「常量级」。learner-first 注意到了（保留四元组，只改 `stages` 属性），stages-as-data 经 `ecdict_tag` 把 `zk→zk_ext` 保住了语义。
3. **`--base` 携带规则依赖 `stardict.db`。** `build_seed.py:74,97,105` 硬性需要 851 MB 的 `stardict.db`，本机没有，`fetch_ecdict.sh` 在 macOS 不能直接跑（设计 §3.8.2 自己写明）。于是「4.5 人日」里种子重建这一步在这台 Mac 上是被 216 MB 下载 + BSD 工具差异卡住的；设计给的替代路径（`ecdict.csv`）自己也标「不推荐」。learner-first 的「从现有种子就地重标」绕开了这个依赖，是明显更稳的上线路径。
4. **`xs ⊂ zk` 的「`ice cream` 例外」是模拟伪影。** 设计 §2 A1 说「505 个词里只有 `ice cream` 不同时属于新的 zk 定义」；用交付文件重算，L2 − L3 = 0、库内 xs − zk = ∅。无害，但说明其 `retag_sim.py` 的口径与最终词表不同，§3.8.4 的量级数字（237 无阶段词）与我的 257、learner-first 的 248、stages-as-data 的 254 一样只是量级——设计自己标了「模拟」，可以接受。
5. **`sources` 令牌全量改写的后果没写。** 删 `zk`/`gk` 令牌、加 5 个官方令牌后，几乎所有原初中/高中词（≥3,829 行）以及新加入的词的 `sources` 都变，UPSERT 的 `WHERE … IS NOT excluded` 会改写这些行并推进 `updated_at`，于是 `/media/card/{id}.svg` 的 LRU 键（词 id, active_content_id, updated_at）全部失效（`WORD_LIBRARY_CURATION.md §1.6`）。无害（重新渲染），但「≈ 旗标变化的行数」的估计偏小。learner-first 提到了缓存键，但把行数估成 2,800，同样偏小。

### 2.3 值得嫁接的好点子

- **「种子只增不减」做成机械保证**（`--base` 必填 + `stats.json.carried_forward`/`no_stage` 计数 + 验收「线上 `source='seed'` 的 lemma 全部在新种子里」）。§3.8.1 对「不在新种子里的词会带着旧旗标活下去」的分析是三份里最透彻的——导入从不删除（`seed.py:72-82`），所以这是真实陷阱。
- `COALESCE(w.difficulty + 1, w.stage_min, 6)` 一行对齐两把尺子，并用 44/49 证明语义不变（我复现）。
- `VocabPage.tsx:232` 改为 `tab !== STAGE_ORDER[0]`，顺手修掉今天初中 tab 的空操作开关（`frontend-stages-19`）。
- 对两个老用户「只 +1、不自动加 xs」并把 `UPDATE … SET stages_json='["xs","zk"]' WHERE stages_json='["zk"]'` 作为可选项明确拒绝——尊重用户已选目标，理由充分。
- §7.2「被封死或变贵的路径」清单诚实，评审者不必自己去挖。

---

## 3. learner-first 评审

### 3.1 正确性与数据安全（核验属实的部分）

- 0011 SQL（§3.6）经我抽出并用真实运行器执行：通过（0.039 s），`+1` 逐行精确，`push_batches` 的 `json_set` 4 行 3→4，`system_events(kind, detail_json, created_at)` 列名正确，`DELETE kv`、`DROP VIEW v_bank` 位置正确。`json_set/json_extract/json_type` 需要 SQLite ≥3.38（设计自己写了，Linux 生产版本未知，INDEX 未解决 10）。
- 显式字典 `STAGE_INDEX` + `min(STAGE_INDEX[s] …)` 替代 `stages[0]`——比 minimal 的「位置推导」多一层保险，并提议加测试 `STAGE_INDEX[s] == STAGE_ORDER.index(s) + 1`。
- 保留 `ecdict.STAGE_TAGS` 四元组、只改 `stages` 属性，明确为了 `words.py:669,673` 的 `has_stage_tag`——三份里唯一注意到这个副作用的。
- 「kimi 10 个生词全是课标二级词」属实（a, and, be, have, i, in, it, of, the, to；`a`/`be`/`have` 在交付文件里是 `a/an`、`be (am, is, are)`、`have (has)` 变体行，归一化后全部命中）。
- 「无阶段词 0 个有 AI 内容或配图」属实（我用交付文件算出 257 个无阶段词，`content_state='ready'` 0 个）。
- `relabel_seed.py`（从现有 `vocab.jsonl.gz` 就地重标，别名表 `Mr→mr.`、`café→cafe`、`a/an` 拆分，新词头走 `ecdict.csv` 或最小记录）不依赖 `stardict.db`，在这台 Mac 上可跑——这是它对上线最有价值的贡献。

### 3.2 致命缺陷

1. **累计不变式 `stage_xs ⇒ stage_zk ⇒ stage_gk` 是错的，而设计把它写进了验收 SQL、`test_full_seed_acceptance_numbers` 和 `TASKS.md`。** §2 A2 说「二级 ⊂ 三级 ⊂ 3100 是课标原文，所以 `stage_xs=1 ⇒ stage_zk=1 ⇒ stage_gk=1`」，§5.4 写死 `SELECT COUNT(*) FROM words WHERE stage_zk=1 AND stage_gk=0; -- 0`。但 A2 的 zk 定义是「上海 2020 表 ∪ 国家三级」，上海表不是国家高中表的子集（INDEX B5：仅上海 415 词中 148–156 个既不在三级也不在高中表）。用交付文件重算：库内 `zk ∖ gk` = **140 个词**（advertisement, aged, amusement, amusing, apologize, arrange, arrival, attractive, beg, beginning, businessman, changeable, chopstick, clearly, completely, confuse, correctly, dial, directly, disadvantage, dislike, dull, easily …）。设计自己的 §3.5 表也写着「gk 离开 1,140 → 82 仍是初中」——即它自己的排练数据里就有 82 个 `zk=1, gk=0` 的词，与它的不变式矛盾，作者没有对账。后果二选一：要么验收脚本红、`test_full_seed_acceptance_numbers` 红（若有人设 `WD_FULL_SEED_DB` 跑它）；要么为了让它绿把 ~140 个上海词强行标 gk——这是把非官方高中词写进「高中 = 国家 3100」，**违反 A3 且设计没有说明**。`xs ⊂ zk` 那一半成立（我算 xs − zk = ∅），`zk ⊂ gk` 这一半必须删掉。
2. **迁移从未排练。** §5.4 写成「在 live-copy.db 的私有拷贝上排练」的 bash 流程，§1 开头却只说「本稿自己跑过的东西：compute.py」；其 scratchpad `stage-model-learner-first/` 只有 `compute.py` 与 `sets.json`，没有 SQL 文件、没有拷贝库、没有 `backups/pre-migrate-10-to-11.db.gz`。另两份都有可复查的产物。我替它跑了，SQL 是对的——但设计稿交付时「排练通过」这一项是空的，证据分必须扣。

### 3.3 其他问题

- `updated_at` 变动「约 2,800 行」低估：`sources` 令牌表整体换名（`zk→legacy:zk`、`gk→legacy:gk`、新增 `cs2022:*`/`sh2020`/`cs2025:*`），原初中∪高中 ≥3,829 行 + 新加入 ≈800 行都会被 UPSERT 改写。无害（只是卡片缓存失效），但数字不对。
- 「将来做上海/全国 = 从 `sources` 回填两列 `stage_zk_sh`/`stage_zk_cn`」低估了 INDEX A8/stage-model-16 列出的成本（第二个 `stage_min`、`/api/stages?scheme=`、6 处模板）；minimal-delta 对同一路径的成本描述诚实得多。
- `StageChips only` 属性是 UI 新特性，不属于数据模型切片，却进了 6.5 人日；无害但跑题。
- 共用盲点见第 5 节（`full_seed` 门禁、无 CI）。

### 3.4 值得嫁接的好点子

- **`relabel_seed.py`：从现有种子就地重标**（不需要 `stardict.db`）+ **别名/变体归一化表**（`Mr→mr.`、`PE→p.e.`、`café→cafe`、`colour (AmE color)` 双收、`a/an` 拆分）——正好对上交付文件的体例，也堵住 minimal-delta §2.2-1 的坑。
- `push_batches.settings_json` 的 `+1` 与 `system_events('migration')` 一行——便宜、让历史快照与事件表自洽。
- 保留 `ecdict.STAGE_TAGS` 四元组、只改 `stages` 属性，并把 `has_stage_tag` 的消费点写进改动清单。
- 「阶段是共享词库的属性，学习进度是用户的属性；重标只动前者」+ 对 sqin/kimi 逐人列出可见变化（§3.10）——发布说明可直接用。
- 建议把 `seed.py`/`words.py`/`prewarm.py`/`content.py` 的常量副本改为 `from .schemas import STAGE_ORDER, STAGE_NAMES_ZH`，把 10 份常量减到 1–2 份——在不做 `stage_defs` 的前提下这是最便宜的去重。

---

## 4. stages-as-data 评审

### 4.1 正确性与数据安全（核验属实的部分）

- 0011 独立复跑通过：3 张新表、18,321 条 tag 与旧旗标逐词一致（0 行不符）、`stage_min` 码分布与整数分布逐一对应、外键在重建后仍生效、`v_bank` 18 行、10,178,560 B。
- **外键到 `stage_defs` 是三份里唯一的数据库层保证**：`word_stage_tags.stage`、`words.stage_min`、`user_settings.current_stage`、`stage_presets.current_stage` 都 `REFERENCES stage_defs(code)`，未知码在库层被拒——直接修复 INDEX A6/seed-pipeline-11「未注册阶段码被静默丢弃」。配套的 `seed.py` 未知码 `raise` + `main.seed_check` 捕获写 `system_events('seed_import_failed')`，也补上 `WORD_LIBRARY_CURATION §1.2` 指出的「坏种子让服务进入重启循环」的空档。
- `Stage = str` 后 `check_contract.py` 的行为判断正确：`parse_types_ts`（:157-170）只把全部成员为字符串/整数字面量的 `export type` 收进 `unions`，`export type Stage = string;` 自动不参与比对；`compare_shape`（:236-253）只比属性名/可选/可空，不比标量类型名，所以 `parent: Stage | null` ↔ `str | None` 能过；`StageInfo extends StageDef` 由 `ts_props`（:171-178）展开。
- 性能：我独立测得 Q1 0.68 ms（旧 1.13）、Q2 单条 3.04 ms（旧 4 条 ≈5.4）、Q3 1.48 ms（旧 1.24），与 §3.5.1 的方向与量级一致。
- 老词去向数字（`zk_ext` 511 / `gk_ext` 1,195 / 254 个无核心阶段）与我用交付文件算的（535 / 1,154 / 257 无阶段）同量级。

### 4.2 严重缺陷（没有「迁移会坏数据」级别的致命伤，但以下每条都是上线风险）

1. **编译期门禁被换成运行期门禁，而且是净减少。** `Stage = str` 让 `check_contract.py` 对阶段码**不再有任何可比对的东西**（它今天比对 `Stage` 与 `StageIndex` 两个联合），`Record<Stage,…>` 的 5 处 tsc 缺键检查（`StageChips.tsx:8-9`、`WelcomePage.tsx:42`、`ScreenPage.tsx:20`、`zh.test.ts:56`）随之消失。设计用 `require_codes` + 外键 + `test_stage_defs_seeded` 补——这些是运行期/测试期保护，不是契约审计。§7.1 承认了，但评分上这是维护性的双刃剑：常量少了，门禁也少了。
2. **`stage_min` 变 TEXT 引入一类「静默错」。** 今天 `w.stage_min > :cur`（`screen.py:35`、`batches.py:60`）、`COALESCE(w.difficulty, w.stage_min, 5)`（`vocab.py:78`）、`stage_min = :stage_idx`（`vocab.py:55`）都是整数语义；改成码之后，任何漏改的比较都会按**字典序**比较字符串而不报错（`'cet4' > 'zk'` 为假、`'gk' > 'cet6'` 为真）。设计列出了每个消费点的新写法（§3.5.2），但保护它们的只有新测试；这正是我这个视角最警惕的失败模式——线上不红、排序悄悄错。
3. **种子流水线仍需 `stardict.db`，且 `MANIFEST.json` 并不存在。** §3.10 让 `build_seed.py` 读 `data/lists/MANIFEST.json`、每文件「一列词头（plain）」，步骤 1 仍从 `--db`（stardict）取 ECDICT 行。本机没有 `stardict.db`（minimal-delta §3.8.2 写明；本设计只字未提），词表任务交付的是 5 个 txt/tsv + 3 份 README，没有 MANIFEST，senior 两表是 `word\tlevel` 的 TSV 而非 plain。于是「9 人日」里种子这 1.5 人日的前提在这台 Mac 上不成立。
4. **全有或全无。** 契约、DTO、`/api/auth/me`、7 个前端页面、≈20 个后端测试 + 16 个前端测试文件一次换完，没有中间可停的点；`stage_defs.xs.enabled=0` 只能隐藏小学，救不了「`zk`/`gk` 页签挂着官方定义的名字却装着旧旗标成员」的过渡态（若词表晚于代码）。
5. 小问题：`has_stage_tag`（`words.py:669,673`）的新定义没写（经 `ecdict_tag` 映射后 `tags` 含 `zk_ext/gk_ext`，语义应能保住，但要写进改动清单）；`ix_words_stage_min(stage_min, frq)` 在 TEXT 列上仍可用但 `new_only` 的计划会漂（设计建议迁后 `ANALYZE`，合理）；7 行 `/api/stages` 与设置页 7 个 chip 的 UX 未验证（设计承认）。

### 4.3 值得嫁接的好点子

- **「未知阶段码必须报错而不是静默丢弃」**：导入器 `raise` + `seed_check` 记事件；即使保留布尔列方案也应做（在 `seed.py:184-185` 处把过滤改成校验）。
- **`wd check db` 不变量**：`stage_min` = 最低旗标/最低 rank；`stages_json` 的每个码都是已知码——这两条在布尔列方案里同样成立，应进 `diag.py`。
- **`bank.DEFAULT_STAGES/DEFAULT_CURRENT_STAGE` 与 `pragma_table_info('user_settings').dflt_value` 的单元测试**，杜绝 INDEX A7 指出的双源漂移。
- **每条成员关系带来源**（`word_stage_tags.sources` / 种子 `stage_sources`）——在布尔列方案里对应「`sources` 令牌按阶段可区分」（minimal 的 `sh_zk_2020`/`l3_2022`、learner-first 的 `legacy:zk`）；三份都保留了信息，stages-as-data 的粒度最细。
- `/api/stages` 单条 `CROSS JOIN … GROUP BY` 替代 4 次循环查询（我测 3.0 ms vs ≈5.4 ms），与模型无关，可独立落地。
- 迁移后 `ANALYZE` 一次。
- 「初中生预设含小学」「新用户默认取最低阶段并解释失败模式（偏低可见、偏高会把小学生送进初中词）」——产品论证清楚。

---

## 5. 三份共同的盲点（我的视角下最重要的一节）

1. **验收数字的测试默认不跑。** `test_seed.py:339 @pytest.mark.full_seed` 在 `conftest.py:38-46` 被无条件 skip，除非设 `WD_FULL_SEED_DB`；`make test`（`Makefile:77-81`）不设它。三份设计都把 `test_full_seed_acceptance_numbers` 列为「会红、要改」，**没有一份说它默认不跑**，也没有一份把「对排练库设 `WD_FULL_SEED_DB` 跑 `pytest -m full_seed`」写进上线清单。这正是任务提醒的「测试会不会红却没人发现」：新种子的阶段计数、`stage_min` 一致性、learner-first 的（错误）不变式，都只在有人手动设环境变量时才被检查。
2. **没有 CI。** 仓库没有 `.github/workflows`；`check_contract.py`、`zh.test.ts` 镜像、tsc 的 `Record<Stage>` 全靠本地 `make test`。设计里反复说「同一提交改两边即可」，前提是有人在该提交上跑了 `make test`。上线清单第 1 步「`make test` 全绿」必须是硬门，并且要包含第 1 条的 `full_seed` 运行。
3. **词表交付格式与三份的接口假设都不一致。** 交付文件保留括号注与并列（README 明示拆分留给种子构建）、高中表是 TSV 带 `level` 列；minimal-delta 要求词表任务预拆分（错位）、stages-as-data 要求不存在的 MANIFEST、learner-first 的别名表最接近现实但文件名（`cs2022_level2.txt`）也不对。最终方案必须把归一化规则写进构建器并对照 `moe-2022.README.md §4.2`、`shmeea-2020-junior.README.md §4.1`、`moe-senior.README.md §4` 逐条实现。
4. **「只回代码」对线上两个用户是静默错位而非 500**（见 §2.1 末条）；stages-as-data 下是 `int('cet4')` 直接 500——反而更安全。三份都应把「回滚 = 恢复 `pre-migrate-10-to-11.db.gz`，且发布后立刻验证」写成硬规则（都写了），并补「静默错位」这一句。
5. **Linux 生产机 SQLite 版本未知**（INDEX 未解决 10）：`RENAME` 新语义需 ≥3.26，learner-first 的 JSON 函数需 ≥3.38；三份都只在 3.54.1 上排练。Lighthouse 部署前要在目标机跑同一探针。
6. **种子重导会改写所有变化行的 `updated_at`** → 卡片 SVG 缓存全部失效（无害），以及**今天 0 个用户自添词、ECDICT 未安装**——所以 `ecdict.py` 的改动在线上无感，但测试必须覆盖（三份都列了 `test_words_resolve.py`）。

---

## 6. 打分（1–10，分高 = 好；effort_risk 分高 = 工作量小风险低）

| 维度 | minimal-delta | stages-as-data | learner-first | 依据摘要 |
|---|---|---|---|---|
| fit | 6 | 8 | 7 | minimal/learner-first 没有拓展层，237–257 个旧词从推荐与预生成中消失、只在「全部」可见；stages-as-data 的 ext 层让它们可达且默认隐藏；三份都保住了两个老用户的设置与生词库（种子不碰 `user_words`，0011 子表行数不变——我已验证）。learner-first 的默认「初中生预设」与 `only` 芯片贴近使用者，但其不变式若强行成立会把 ~140 个上海词塞进高中层 |
| correctness | 7 | 6 | 4 | 三份 SQL 都经我复跑通过。minimal：`ecdict.py:177` 陷阱抓准，但 `STAGE_TAGS` 缩小的 `has_stage_tag` 副作用未列、词表接口与交付不符会让 `be/child/colour/mr…` 掉阶段。stages-as-data：外键级保证是加分，`Stage=str` 与 TEXT `stage_min` 的静默错位类是减分。learner-first：累计不变式错误并写进验收/测试/TASKS（致命） |
| effort_risk | 7 | 4 | 6 | 4.5 / 9 / 6.5 人日；minimal 的种子步骤被 `stardict.db` 卡住；stages-as-data 一次性换契约 + ≈36 个测试文件、无中间停点；learner-first 的 `relabel_seed.py` 绕开 stardict，但验收脚本按原文会红 |
| maintainability | 4 | 8 | 4 | minimal/learner-first 保留 10 份常量 + 5 个前端文件 + `/api/stages` 固定行数，下一个阶段又是一次重建；learner-first 提议常量集中到 `schemas` 略好；stages-as-data 加阶段 = 加行，但以编译期门禁换运行期检查 |
| evidence | 7 | 7 | 4 | minimal、stages-as-data 都有可复查的排练产物且数字与我的复跑逐项一致（minimal 的「ice cream」是模拟伪影，stages-as-data 未提 stardict 缺失）；learner-first 无迁移排练产物，不变式与「2,800 行」两处与数据相悖，其余数字（kimi 10 词、无阶段词 0 内容）属实 |
| rollout | 7 | 5 | 6 | 三份都正确写出 Mac/launchd 停机流程、快照回滚、`VACUUM`。minimal 步骤最完整（含前端快照 `os.rename`、`VACUUM` 可选、回滚第 11 步），但种子构建依赖下载；stages-as-data 只有快照回滚且前置条件最多（词表 + MANIFEST + stardict + 全契约）；learner-first 流程清楚、无 stardict 依赖，但验收 SQL 第 4 条按原文必红 |
| **overall** | **6.5** | **6.0** | **4.5** | |

**排名：minimal-delta > stages-as-data > learner-first。**

为什么 minimal 排在 stages-as-data 前面（尽管后者 fit/maintainability 更高）：从「迁移与数据安全」的角度，决定性的不是 SQL（三份都安全），而是**爆炸半径与可验证性**——minimal 改动面最小、全是常量级、门禁（`check_contract` 的 `Stage/StageIndex` 联合、`Record<Stage>`、`zh.ts` 镜像）全部保留并会在第一时间变红；stages-as-data 把阶段码的集合从编译期挪到运行期、把整数排序挪到 CASE/rank，这两类错误都不会红、只会悄悄错，而它要同时改的测试文件最多。线上只有 2 个用户的「历史最低代价」对两者同样成立，不构成偏向 stages-as-data 的理由；真正需要 `stage_defs` 的触发条件——上海方案、教材拓展——A4 已决定本轮不做，INDEX Q1 的建议也是「若近期只做小学选 a」。learner-first 排最后不是因为它的 SQL（它也通过了），而是它把一个错误的数据不变式写进了三处验收，且提交时没有任何排练证据。

---

## 7. 对最终方案的嫁接建议（按价值排序）

1. **以 minimal-delta 的 0011 为骨架**（已三方核验：`DROP VIEW` 先行、显式列名、`+1`、K-12 DEFAULT、清 `seed_version`），加上 learner-first 的两行：`push_batches.settings_json` `+1` 与 `system_events('migration')`。
2. **种子生成用 learner-first 的 `relabel_seed.py` 路线**（从现有 `vocab.jsonl.gz` 就地重标，不需要 `stardict.db`），把 minimal 的「只增不减」`--base` 语义与 `carried_forward`/`no_stage` 统计并进去；归一化规则对照 `data/lists/*.README.md §4` 实现（括号注剥离、`/` 与 `=` 拆分、`AmE` 变体双收、`Mr→mr.`/`PE→p.e.`、TSV `level` 列）。
3. **删掉 learner-first 的 `zk ⊂ gk` 不变式**，只保留 `xs ⊂ zk`（交付文件验证成立）与「`stage_min` = 最低旗标」；把 stages-as-data 的两条 `wd check db` 不变量（`stage_min` 一致、`stages_json` 码已知）加进 `diag.py`。
4. **导入器对未知阶段码报错**（stages-as-data），`seed_check` 捕获并记 `system_events('seed_import_failed')`——用常量实现同样可行，直接修 INDEX A6。
5. **上线清单加一条硬门**：对排练库 `WD_FULL_SEED_DB=<拷贝> .venv/bin/pytest -m full_seed`，并在 `make test` 之外明示它默认被 skip。
6. `bank.DEFAULT_*` ↔ DDL 默认的单元测试（stages-as-data）；`/api/stages` 单条 `GROUP BY`（stages-as-data，与模型无关）；`VocabPage` 最低阶段隐藏空操作开关（minimal/learner-first）；迁后 `ANALYZE` + `VACUUM`。
7. **`sources` 令牌表统一**：采用 learner-first 的 `legacy:zk/gk` 保留旧成员证据（将来拓展层的候选集），其余用 minimal 的官方令牌命名；写进 `ATTRIBUTION.md` 与 `DESIGN §3.2`。
8. 保留 `ecdict.STAGE_TAGS` 四元组、只改 `stages` 属性（learner-first），并把 `words.py:669,673` 写进改动清单。
9. 发布说明补一句：代码回退而不回库 = sqin 的主攻阶段静默变「六级」、kimi 变「高中」、词库页 500；回滚只能 `wd restore pre-migrate-10-to-11.db.gz`。
10. 若产品负责人在 Q3/Q4 上拍板要「上海方案」或「拓展层」，再上 stages-as-data——届时它的 0011 草案与 tag 回填已经过两次独立复跑，可直接复用；但要先补 MANIFEST/归一化与 `stardict.db` 的获取路径，并把 TEXT `stage_min` 的每个比较点写成测试。

---

## 附：本评审的产物

- `scratchpad/judge-data-safety/rehearse.py`：三份 0011 的独立复跑脚本（`.venv/bin/python -I`，真实 `wd.db.run_migrations`）；产物 `minimal.db`、`sad.db`、`lf.db` 与各自的 `mig-*/` 目录。
- `scratchpad/judge-data-safety/0011_stage_xs_renumber.sql`：从 learner-first.md §3.6 第 163-280 行抽出的 SQL。
- `scratchpad/judge-data-safety/lists_check.py`：用 `data/lists/` 交付文件对 `live-copy.db` 重算成员关系（`python3.12 -I`，只读）。关键输出：`L2 ⊆ L3`（0 差）；库内 `xs ⊆ zk`、`xs ⊆ gk`；库内 `zk ∖ gk` = 140；无阶段词 257（0 个有内容）；旧 zk 离开 535 / 加入 382，旧 gk 离开 1,154 / 加入 436；L2 未命中 10 行中 9 行为括号/斜杠变体、1 行 `excited`。
