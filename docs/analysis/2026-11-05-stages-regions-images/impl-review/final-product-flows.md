# 最终评审 · 产品流程（对抗式）：注册 → 引导 → 词库 / 筛词 / 设置 / 预热，三类用户视角

评审对象：工作区全部改动（`git diff 75df534` + `git status` 新文件，139 条）。方法：不用夹具里的 62 词 mini seed，而是用 **真实新种子** `data/seed/vocab.jsonl.gz`（9,618 条）起一个独立 `WD_DATA_DIR` 的 `create_app` + `TestClient`（环境变量照抄 `backend/tests/conftest.py::test_env`），把任务要求的流程走完；再把 `$SCRATCH/live-copy.db` 复制到私有目录，让 lifespan 自己跑 0011/0012/0013 + 种子导入，用 `security.create_session` 直接给线上两位用户签会话，走同一组接口。所有脚本与数据库都在 `$SCRATCH/final-review-flows/`（`flow.py`、`probe.py`、`fresh/`、`live/`）；仓库文件一个都没改（`git status --short | wc -l` 前后均 139，本报告所在目录 `impl-review/` 本身是已有的未跟踪目录）。只报告跑过命令或读过代码并能引用位置的问题。

## 0 结论

**通过：无 blocker。** 任务列出的每一步都返回了预期状态码与预期数据：`GET /api/stages` 5 行、顺序 `xs zk gk cet4 cet6`、索引 1..5；`/api/vocab?stage=xs` 与 `new_only=1` 都是 600（恒等，前端在小学页签隐藏开关）；`/api/screen/next?stage=auto|xs` 对主攻小学的用户给出相同顺序、全部 `stage_min=1`；设置页 `current_stage=xs` 200，`current_stage ∉ stages` 400；管理员 `prewarm {"stage":"xs"}` 202 `planned 5`；老用户形态（`stages ["zk"]`、`current_stage 2`）的词库 6 个页签 × 3 种排序、推荐、生词库、今日页全部 200，推荐先出「初中新增」再出小学词（与发布说明一致）；线上副本两位用户（`sqin` `["zk","gk","cet4","cet6"]`/4、`kimi` `["zk"]`/2）同样全部 200，`user_words` 落到无阶段词的数量 0。前端 `WelcomePage` / `VocabPage` / `StageChips` / `ScreenPage` / `SettingsPage` 的常量、预设与文案与后端一致（`check_contract OK`；6 个相关测试文件 34 用例 + `tsc` 绿）。

**1 条 major（产品缺口，PLAN §9.2 #5 已登记为「不阻塞本轮」，但建议在邀请小学生前处理）：** 小学阶段的一切顺序（词库页签默认排序、引导期 30 张筛词、每日 15 个推荐词）都由成人语料频率 `frq` 决定，一个上海三年级学生前 60 个词里 43 个是功能词 / 无词性词，第一个具体名词 `time` 排在第 44 位，而 `Monday / January / is / are / colour / schoolbag` 因 `frq` 为空被排到第 572–594 位（共 600）。**4 条 minor**（1 条健壮性：`stages_json` 无已知阶段码时 `/api/auth/me`、`/api/settings` 500 而其余接口靠 `bank` 的回落正常；3 条数据/文案观察）。

## 1 复跑的命令与结果

| 命令 | 结果 |
|---|---|
| `.venv/bin/python $SCRATCH/final-review-flows/flow.py fresh`（真实种子，4 个新用户 + 管理员，46 项 `check`） | **46 OK / 0 FAIL**（脚本末尾的 `/api/words/ruler` 探针因我把 `WordDetail.word.stages` 写成了顶层键而抛 KeyError，是脚本错误；`probe.py` 修正后 `detail ruler: 200 {'stages': ['xs','zk','gk','cet4','cet6'], 'stage_min': 1}`） |
| `.venv/bin/python $SCRATCH/final-review-flows/flow.py live`（`live-copy.db` 私有副本） | lifespan 应用 `schema_migrations [1, 8, 9, 10, 11, 12, 13]`；`seed_imported inserted 456 / updated 4357 / forms 14196 / aliases 5 / unknown_stage_codes 0`；`user_settings (1,'["zk","gk","cet4","cet6"]',4) (2,'["zk"]',2)`；两位用户 `/api/auth/me` `/api/settings` `/api/stages` `/api/vocab`(6 页签 × difficulty) `/api/screen/next` `/api/bank` `/api/today` `/api/stats` 全部 200；用户持有的无阶段词 0 |
| `.venv/bin/python $SCRATCH/final-review-flows/probe.py`（复用 fresh 库） | 四个人格 `POST /api/today/build` 200；`stages_json='["cet9"]'` 边界见 §4 F2 |
| `.venv/bin/python -m pytest -q backend/tests/integration/{test_vocab,test_onboarding,test_screen,test_settings,test_admin_ops}.py backend/tests/unit/{test_bank_defaults,test_api_schemas}.py` | `98 passed, 1 skipped in 13.49s` |
| `cd frontend && npx vitest run src/components/word/StageChips.test.tsx src/pages/{VocabPage,WelcomePage,ScreenPage}.test.tsx src/i18n/{zh,zh.contract}.test.ts && npm run typecheck` | `6 files / 34 tests passed`；`tsc` 两个 tsconfig exit 0 |
| `.venv/bin/python scripts/check_contract.py` | `contract OK: no property-name or literal-union mismatch` |

## 2 流程逐步核对（fresh 库，真实种子）

| 步骤 | 调用 | 结果 |
|---|---|---|
| 注册 | `POST /api/auth/register`（第一个用户 `admin1` 自动 admin） | 201；新用户 `GET /api/settings` → `stages ["xs","zk"]`、`current_stage "xs"`（0011 DDL 默认 ↔ `bank.DEFAULT_*`，`test_bank_defaults` 钉住） |
| 引导「小学生」 | `POST /api/onboarding {"stages":["xs"],"current_stage":"xs",…}` | 200，`settings.stages ["xs"]`；`onboarding_state screen` |
| 引导「初中生」 | `{"stages":["xs","zk"],"current_stage":"zk"}` | 200；`screen/next?stage=auto` `remaining 2549`，前 30 全部 `stage_min=2`（距离 0 的「初中新增」先于小学词） |
| 阶段表 | `GET /api/stages` | 5 行 `xs/zk/gk/cet4/cet6`，`index 1..5`，`name_zh 小学/初中/高中/四级/六级`；`total 600/2549/3260/4722/7671`，`new_only_total 600/1949/1255/1726/3850` = `stats.json.per_stage/first_stage` |
| 词库 | `GET /api/vocab?stage=xs`、`&new_only=1`、`&sort=difficulty`、`&sort=alpha`、`stage=all` | 均 200；`xs` 与 `xs&new_only=1` 都是 600（恒等）；`difficulty` 排序与 `freq` 排序给出相同前 15（种子 9,618 行 `difficulty` 全部 NULL → `COALESCE(NULL+1, stage_min, 6)` 退化为 `stage_min, frq`） |
| 筛词 | `GET /api/screen/next?stage=auto&count=30` / `stage=xs` / `stage=cet6` | 200；`auto` 与 `xs` 前 30 词序逐一相同、全部 `stage_min=1`、`remaining 600`；小学生点「六级」卡也能筛（`remaining 7671`，设计如此） |
| 引导期判定 | `POST /api/screen/verdict known / unfamiliar (context onboarding)` → `POST /api/onboarding/complete` | 200 / 200 / 200 `done`；之后 `/api/stages` 的 xs 行 `unseen 598 known 1 unfamiliar 1` |
| 设置页 | `PUT /api/settings {"current_stage":"xs"}`；`{"stages":["xs","zk"],"current_stage":"zk"}`；`{"stages":["zk"]}`（current zk）；`{"stages":["xs"]}`（current 仍 zk） | 200 / 200 / 200 / **400 validation_error「主攻阶段必须包含在目标阶段中」**（`routers/settings.py:90-92`） |
| 今日 | `GET /api/today`（不建批）→ `POST /api/today/build` | 200 `status none` → 200 `building`，内容见 §3 |
| 管理员预热 | `POST /api/admin/content/prewarm {"stage":"xs","limit":5,"max_budget_usd":1}`；`{"stage":"all",…}` | **202 `{"job_id":2,"planned":5}`** / 202（`prewarm.STAGE_COLUMNS` 由 `STAGE_ORDER` 生成，`all` = `stage_min IS NOT NULL`，课标外词不入预热） |
| 老用户形态 | `POST /api/onboarding {"stages":["zk"],"current_stage":"zk"}` → 库里 `('["zk"]', 2)` | `vocab?stage=zk` 2549、`vocab?stage=all&sort=difficulty` 9618、`screen/next?stage=auto` 前 30 全 `stage_min=2`、`today/build` 15 个推荐词全 zk 新增 —— 无报错 |
| 成人四级（职场人士预设） | `{"stages":["cet4","cet6"],"current_stage":"cet4"}` | `screen/next auto` 前 50 全部 `stage_min=4`（先四级增量，再六级增量，再被高中/初中表覆盖的四级词）；`vocab?stage=cet4&new_only=1` 1726、`cet6&new_only=1` 3850 |

线上副本：`kimi`（`["zk"]`/2）推荐前 30 = `as if would into just could than other more thing …` 全 `stage_min=2`，与 `docs/releases/2026-11-k12-stages.md:79` 的预期一致；`sqin`（cet4）推荐前 30 全 `stage_min=4`，生词库 17 词都仍有阶段；`/api/stages` 为 `sqin` 报 xs `known 1`（他以前标过一个现在落入小学表的词）。

## 3 前端与后端的一致性（读代码 + 跑测试）

| 处 | 核对 | 结论 |
|---|---|---|
| `StageChips.tsx:12-14` `STAGE_ORDER / STAGE_INDEX / STAGE_BY_INDEX` | 与 `schemas.py:56-57` 同序同值；`StageChips.test.tsx` 钉「索引 = 位置 + 1」 | 一致 |
| `StageChips` `only` 逻辑 `:43` | `stages.includes(s) && (!only || only.includes(s) || STAGE_INDEX[s] === stageMin)`；`stages=[]` → 单个虚线「课标外」芯片（P6/P18） | 与 PLAN S4 规格逐字一致；`WordHeader.tsx:35` `hasMeta` 已改为 `showStages`，否则课标外词在卡片上没有 meta 行 |
| `WelcomePage.tsx:30-40` `ROLE_PRESETS / ROLES / DEFAULT_PRESET` | `xs {['xs'],'xs'}`、`zk {['xs','zk'],'zk'}`、`gk {['zk','gk'],'gk'}`、uni/pro 不变、`DEFAULT_PRESET {['xs','zk'],'xs'}` = DDL 默认；`toggleStage` 保持非空且 `current ∈ stages`；主攻 `Segmented` 只列已选阶段 | 与后端 `OnboardingRequest._current_in_stages`（`schemas.py:372`）互补；`WelcomePage.test.tsx:176-224` 覆盖 |
| `VocabPage.tsx:30` `TABS`、`:83-84` `newOnlyAvailable = tab !== 'all' && tab !== STAGE_ORDER[0]`、`:205` 文案三分 | 后端对 `stage=xs&new_only=1` 不拒绝但恒等（`stage_min=1 ⇔ stage_xs=1`，实测 600=600），前端隐藏并忽略；`zk` → `仅初中新增（不含小学）`、`cet6` → `仅六级新增（不含四级）`、其余 `仅本阶段新增` | 一致；`VocabPage.test.tsx:37-54` 覆盖 |
| `ScreenPage.tsx:20` `FULL_NAME`、`:31` 按 `STAGE_ORDER` 排 `data.items` | 5 张卡，`xsFull '小学（课标二级词汇）'` | 一致 |
| `ScreenRunPage.tsx:34` `isStage(stageParam)` | `/screen/xs` 合法；`ScreenCard.tsx:91` `showStages={false}`——筛词卡根本不显示阶段芯片，所以 PLAN S4 里「ScreenRunPage 传 `onlyStages`」一项无对象，`FRONTEND.md:89` 也只写了列表/学习卡/详情页 | 无问题 |
| `SettingsPage.tsx:17,72-76,303-317` | 用 `STAGE_ORDER`，`toggleStageSetting` 与欢迎页同规则 | 一致 |
| `AdminPage.tsx:37` `[...STAGE_ORDER, 'all']` | 预热下拉含「小学」 | 一致 |
| `zh.ts:25,28-29,86` ↔ `docs/FRONTEND.md:231,234-235,292` | 逐字相同（`zh.test.ts`、`zh.contract.test.ts` 绿） | 一致 |
| 全仓库四阶段字面量 | 前端非测试文件 0 处；后端只剩 `ecdict.STAGE_TAGS`（ECDICT 标签名，按设计保留）与 `seedbuild/diff.V1_ORDER`（v1 种子读取） | 无遗漏 |

## 4 三类用户各自看到什么（真实种子数据）

### 4.1 上海三年级学生（角色「小学生」→ `['xs']`/xs）

- 欢迎页：五个角色；选「小学生」后目标阶段只亮「小学（课标二级词汇）」，主攻只有「小学」一个选项；下一步进入 30 张筛词。
- **筛词前 30 张**（= `/api/screen/next?stage=auto`）：`the be and of a in to have it I that for you he with on do say this they at but we his from not by she or what`。**每日批次**（`POST /api/today/build`）：`new: be` + 15 个推荐词 `and of a in to have it I that for you he with on do`。词库「小学」页签默认排序前 15 同上。量化：小学 600 词按 `frq` 排序，前 60 个里 43 个主词性 ∈ {介/连/限/代/冠/感/不定式标记/副词} 或无词性；第一个实词名词 `time` 在第 44 位，`year` 46、`people` 54；而 `are / colour / is / January / Monday / schoolbag` 等 30 个 `frq` 为空的小学词排在第 572–594 位。三种排序里 `difficulty` 与 `freq` 完全相同（`difficulty` 全 NULL），`alpha` 从 `a / a.m. / about…` 起 —— 没有一种顺序适合八九岁的孩子。配图线的功能词门会让这些推荐词直接走模板卡（无图）。→ **F1**
- 词库「全部」页签：9,618 词，含 238 个「课标外」虚线芯片的词（`hey works totally arab mexican viewer …`）与 `Shanghai`（`stages []`：2022 附表地理名称里没有上海，上海附表也没有；`Beijing` 根本不在任何表与种子里，只有 `Beijing opera / Beijing roast duck`）。按 P6 这是设计，但对上海的孩子搜 `Shanghai` 看到「课标外」会有点怪；属词表事实，不是实现错误。
- 芯片：列表与学习卡只显示「小学」（`only=['xs']`），`stage_min=2` 的词显示「初中」—— 信号清晰。
- 词条细节：`am` 继承 `be` 的小学阶段（R-8 显式清单），但库里该 lemma 唯一的 ECDICT 行是缩写 `AM`（`display 'AM'`、`kind abbreviation`、`pos r:100`、释义「be的单数第一人称 | [计] 存取管理程序, 寻址方式…」）→ 小学页签里出现一个带「缩写」徽章的大写 **AM**。`mrs.` 小写而 `Mr. / Ms.` 大写；`august / march / may` 小写（ECDICT 原形，R6 规定 display 取 ECDICT 原形，首行释义是月份，可接受）。→ **F3**

### 4.2 上海初中生（角色「初中生」→ `['xs','zk']`/zk）

- 筛词 / 推荐先出「初中新增」1,949 词：`as if would into just could than other more thing only even through life still need state become high something …`（前 60 里 24 个功能词，可接受），小学词排在其后（距离 2）。
- 词库「初中」页签默认排序前 15 仍是 `the be and of …`（累积表），需要打开「仅初中新增（不含小学）」才看到 1,949 个增量——与四级/六级页签的既有体验一致。
- 上海词组 383 条（`kind='phrase'`，`shmeea20:phr` 333 行 + 附表短语）**`frq` 全部为空**，在「初中」页签与推荐里排在全部 2,100+ 单词之后，实际上几乎不会被推荐到。→ **F4**

### 4.3 成人四级用户（角色「职场人士」→ `['cet4','cet6']`/cet4）

- 推荐前 15：`oh federal simply republican congress stock media particularly growth analysis democratic executive entire religious management`——四级增量按 COCA 频率，第一个词是感叹词 `oh`，随后是美国政治词汇。这是 ECDICT `frq` 的语料偏差，75df534 之前就如此（旧索引下同一顺序），不是本次改动引入；`oh`（`pos u`）会被 S5 功能词门判为模板卡。→ **F5（观察）**
- 四级页签默认排序仍以 `the be and …` 开头（累积表），「仅本阶段新增」1,726；六级增量 3,850；排序表达式 `COALESCE(difficulty + 1, stage_min, 6)` 在「全部」页签把课标外词排到最后。
- 距离排序把 3,850 个六级增量词排在「也在高中表里的四级词」之前（距离 1 < 2）——与旧索引下行为相同，非回归。

## 5 问题清单

| # | 严重度 | 位置 | 问题 | 证据 | 修法 |
|---|---|---|---|---|---|
| F1 | **major**（产品缺口；PLAN §9.2 #5 与 `docs/releases/2026-11-k12-stages.md:210` 已登记为「不阻塞本轮」） | `backend/wd/services/screen.py:34-35,63`、`services/batches.py:60-61,266-272`、`routers/vocab.py:63-70`（排序键 `(frq IS NULL OR frq=0), frq, lemma`，对 `xs` 无特殊处理）；种子 `frq` 来自 ECDICT | 小学生的引导筛词、每日推荐词与小学页签全部以成人语料频率排序：前 30 张卡 `the be and of a in to have it I that for you he with on do say this they at but we his from not by she or what`，前 60 个里 43 个功能词/无词性；`Monday / January / is / are / colour / schoolbag` 等 30 个 `frq` 为空的词排到第 572–594/600 位 | `flow.py fresh` 输出「pupil auto screen」「pupil3 today/build」；`probe` SQL：`first 15 content-word positions [1,7,16,17,30,32,34,38,40,41,43,44,46,48,54]`、`function/unknown-pos share in first 60: 43/60`、`positions of … (572,'are') (573,'colour') (580,'is') (581,'january') (584,'monday') (594,'schoolbag')` | 本轮可不改（PLAN 明示）；邀请小学生前任选其一：① 对 `cur = stage_to_index("xs")` 的用户在 `_STAGE_DISTANCE` 之后、`frq` 之前加一个按主词性的键（`n/v/j` 先、功能词后；`images/style.dominant_pos` 已有现成解析），同时把 `frq` 为空的小学词视作中频而非末位；② 构建期给附表的星期/月份/人称形式按原形回填 `frq`（`Monday` 取 ECDICT `monday`、`is/are/am` 取 `be`），让它们离开末位；③ 长期：教材/年级顺序字段（PLAN §9.2 #5） |
| F2 | minor（健壮性；PLAN §2.1 只给 `bank.user_settings_row` 规定了回落） | `backend/wd/security.py:588-597 settings_row_to_dto`（`stages = json.loads(row["stages_json"])` 原样进 `SettingsDTO`） | `stages_json` 里没有任何已知阶段码时（手工改库、或旧服务器读到新 schema 写的码），`GET /api/auth/me` 与 `GET /api/settings` 返回 500 `internal_error`（`response validation failed … 'cet9'`），SPA 无法启动；同一用户的 `/api/today`、`/api/screen/next`、`/api/vocab` 却因 `bank.user_settings_row:181-195` 的回落（`stage_fallback` WARNING）正常 200，`PUT /api/settings {"stages":["zk"],"current_stage":"zk"}` 也能修复 | `probe.py`：`cet9 GET /api/auth/me → 500`、`GET /api/settings → 500`、`GET /api/today → 200`、`screen/next → 200`、`vocab?stage=zk → 200`、`PUT settings repair → 200`；日志 `stage_fallback: user 5 stages_json '["cet9"]' has no known stage code; using ['xs','zk']` | 在 `settings_row_to_dto` 里按 `schemas.STAGE_ORDER` 过滤 `stages`、为空时回落 `bank.DEFAULT_STAGES` 并记同一条 `stage_fallback`（或抽一个 `security`/`bank` 共用的 `known_stages(stages_json)`），`current_stage` 越界同样回落而不是抛；加一条 `test_settings.py` 用例。无产品路径写出未知码，故不阻塞 |
| F3 | minor（数据） | `data/lists/overrides.tsv`（23 条，P13 上限 30）；种子记录 `am` | `am` 经 `inherit:be` 入小学，但 ECDICT 只有缩写行 `AM`：`display 'AM'`、`kind 'abbreviation'`、`pos 'r:100'`、释义第二行 `[计] 存取管理程序, 寻址方式, 地址标记, 变址数, 调幅…`；小学页签/学习卡显示带「缩写」徽章的大写 **AM**。同类小瑕疵：`mrs.` 小写（`Mr.`/`Ms.` 大写），`august / march / may` 小写（R6 取 ECDICT 原形，首行是月份义，可接受） | `probe.py` 「suspicious xs rows」行 `{'lemma':'am','display':'AM','kind':'abbreviation','pos':'r:100','t':'be的单数第一人称\n[计] …','sources':'cet46 ecdict inherit:be legacy:gk legacy:zk'}`；`detail am: 200 {'display':'AM','kind':'abbreviation',…}` | `overrides.tsv` 加两行：`am	word	am`（display 小写 → `derive_kind` 判为 `word`）、`am	translation	v. 是（be 的第一人称单数现在式）`；可顺手 `mrs.	word	Mrs.`。重建种子（`make seed`）即可，无代码改动 |
| F4 | minor（数据/体验观察；R-6 只要求入库） | 种子 `kind='phrase' AND stage_zk=1` 383 行 | 全部 `frq` 为空（`SUM(frq>0) = 0 / 383`），在「初中」页签与推荐排序（`(frq IS NULL OR frq=0)` 为第一子键）里排在所有单词之后，初中生几乎不会经推荐遇到上海词组 | `probe` SQL `zk phrases with frq: (0, 383)`；`vocab?stage=zk` 前页无词组 | 构建期给词组一个合成频率（例如取成分词 `frq` 的最大值）或在推荐里给 `kind='phrase'` 单独配额；留待词表线下一版 |
| F5 | minor（观察，75df534 前行为相同） | `screen.py:63` / `batches.py:61` 排序 | 成人四级用户推荐前 15 以感叹词 `oh` 开头，随后 `federal republican congress democratic senate troop`（COCA 美国政治偏差） | `flow.py fresh` 「adult」行 | 非本轮范围；若做 F1 的主词性键，`oh`（`pos u`）会自然后移 |

**核对过、没有问题的点**：`stage_min` 不变量与 `xs ⊆ zk` 在导入后的库里都是 0 违例；课标外词（238）不进 `screen/next`、`today/build`、`today/more`、`prewarm all`（四处 SQL 都以阶段旗标或 `stage_min IS NOT NULL` 过滤，实测推荐与批次里 `stage_min` 无 NULL）；`is_valid_english=1` 覆盖全部 9,618 行（词组可进筛词）；`word_forms` 别名 5 行（`hot-dog mr mrs ms pe`）经 `/api/lookup` 走 `via=form` 并给出「已归为原形 …（另一种写法）」；`color/colour`、`math/maths`、`mom/mum` 同为小学独立行（P4）；`PUT /api/settings` 的 `current_stage ∉ stages` 校验与前端 `toggleStage` 互为冗余；`push_batches.settings_json` 新快照写新索引（只写不读）。

## 6 残留与说明

- F1 是任务特别点名的「小学页签全是功能词」：**实测属实，且不只页签——引导筛词与每日推荐词同样如此**。PLAN 已把它列为未决 #5，本报告不把它算作本轮实现缺陷，但建议把「先于邀请小学生」写进发布说明的待办。
- 「课标外词出现在推荐里」：**未发生**（四条候选 SQL 都过滤）。课标外词只在「全部」页签与搜索可见、带虚线芯片，与 P6 一致。
- 本评审没有改任何仓库文件；`$SCRATCH/final-review-flows/` 下的两个数据库是私有副本，可直接删除。
