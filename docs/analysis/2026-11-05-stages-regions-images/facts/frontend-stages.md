# frontend-stages — 前端对「阶段」的全部依赖，及新增「小学」阶段 /「上海·全国」开关的前端改动清单

基线：仓库 `/Users/sqin/word-dance`，分支 main @ `75df534`，核验日期 2026-11-05。本文件只做调研与事实核验，未改任何代码。

## 范围与方法

- 逐行读取（`cat -n` / `sed -n`）：`frontend/src/api/types.ts`、`frontend/src/api/endpoints.ts`（阶段相关段落 L90-140、L190-200、L320-340、L395-450、L497、L535）、`frontend/src/components/word/StageChips.tsx`、`word.css`、`WordHeader.tsx`、`frontend/src/components/list/WordRow.tsx`、`list.css`（L11-19、L49-57、L97-103）、`frontend/src/components/study/StudyCard.tsx`（L165-175、L200-210、L295-300）、`ScreenCard.tsx`（L91）、`frontend/src/components/ui/Tabs.tsx`、`Segmented.tsx`、`ui.css`（L440-546）、`frontend/src/components/bank/bank.css`（L144-169）、`frontend/src/i18n/zh.ts`、`zh.test.ts`、`zh.contract.test.ts`、`frontend/scripts/check-copy.mjs`、`frontend/src/pages/WelcomePage.tsx` + `.css`、`SettingsPage.tsx`（L60-80、L195-210、L295-325、L408-445）+ `.css`、`VocabPage.tsx` + `.css`、`ScreenPage.tsx` + `.css`、`ScreenRunPage.tsx`（L28-80、L150-175）、`AdminPage.tsx`（阶段相关行）、`HistoryPage.tsx`（L54-71）、`WordDetailPage.tsx`（L360、L426-442）、`routes.tsx`（L30-45、L80-90）、`auth/AuthContext.tsx`（L37、L142-154）、`styles/tokens.css`、`styles/global.css`、`vite.config.ts`、`tsconfig.json`、`package.json`、仓库根 `Makefile`（L77-85）、`scripts/check_contract.py`（L1-36、L222-292）。
- 测试文件：`grep -rn cet6 frontend/src`（51 个 `*.test.*` 文件中命中的全部）、`SettingsPage.test.tsx`、`WelcomePage.test.tsx`、`VocabPage.test.tsx`、`ScreenRunPage.test.tsx`、`SpeakButton.test.tsx`、`endpoints.test.ts`、`client.test.ts`、`AuthContext.test.tsx`。
- 文档：`docs/FRONTEND.md`（§2 L44-67、§4 L78-101、§5.1 L105-126、§5.5 L147、§5.8 L160、§6.2 L174-176、§7 L207、§8 L209-312）、`docs/API.md`（含 stage 的全部行）、`docs/DESIGN.md`（L28-45、§0.3 L57-80、§6.2 L330、§6.3 L336-356）、`docs/qa-frontend.md`（含阶段的行）、上一轮分析 `docs/analysis/2026-11-04-library-curation/facts/frontend-consumption.txt`（仅引用其结论 6/7/20，行号已按 75df534 重新核对）。
- 后端只读对照（用于确认语义，不在本任务改动范围）：`backend/wd/schemas.py`（L25-26、L51-67、L77-81、L488）、`backend/wd/routers/vocab.py`（L48-62、L83-107）、`backend/wd/migrations/0001_init.sql`（L147-148、L185-186、L207）。
- 线上库只读副本 `scratchpad/live-copy.db`：`sqlite3 -readonly` 查询 `words` 的阶段计数与 `user_settings` 分布（命令见各条）。
- 未做网络检索，未下载任何文件（本任务纯代码核验）。
- 页宽算术的假设：CJK 字形宽 = 1em（PingFang SC 等宽汉字），`1rem = 16px`（`global.css:20` body 用 `var(--text-md)` = `1rem`，`tokens.css:66`）。凡依赖该假设的结论标为「推断」。

---

## A. 现状：前端对「阶段」的全部依赖

**[frontend-stages-1]** 阶段在前端是一条闭合字面量联合 + 三张同构映射表，所有页面都从这里派生。（事实，置信度高）
- `frontend/src/api/types.ts:5` `export type Stage = 'zk' | 'gk' | 'cet4' | 'cet6';           // index 1..4 in that order`；`:6` `export type StageIndex = 1 | 2 | 3 | 4;`
- `frontend/src/components/word/StageChips.tsx:7-9`
  ```ts
  export const STAGE_ORDER: readonly Stage[] = ['zk', 'gk', 'cet4', 'cet6'];
  export const STAGE_INDEX: Record<Stage, StageIndex> = { zk: 1, gk: 2, cet4: 3, cet6: 4 };
  export const STAGE_BY_INDEX: Record<StageIndex, Stage> = { 1: 'zk', 2: 'gk', 3: 'cet4', 4: 'cet6' };
  ```
  `:11-13` `isStage()` 用 `STAGE_ORDER.includes` 做运行时校验（路由参数、localStorage 读回都经它）。
- 其他 `Record<Stage, …>` 字面量（加阶段时缺键即 tsc 报错）：`WelcomePage.tsx:42` `STAGE_FULL`、`ScreenPage.tsx:20` `FULL_NAME`、`zh.test.ts:56` `const stages: Record<Stage, string> = zh.stages;`。`grep -rn 'Record<Stage' frontend/src` 只有这 4 处（含 StageChips 两处）。
- `types.ts:1-2` 声明本文件是冻结合同：`// Any change requires updating API.md, backend/wd/schemas.py and this file in one "contract change" commit.`

> **核验修正（INDEX §3 #16，2026-11-05）**：`grep -rn 'Record<Stage' frontend/src` 实测为 5 行 / 4 个文件（`StageChips.tsx:8`、`StageChips.tsx:9`（`Record<StageIndex, Stage>`，键为索引）、`zh.test.ts:56`、`WelcomePage.tsx:42`、`ScreenPage.tsx:20`），正文列的 3 + 2 = 5 与「只有这 4 处」自相矛盾；`STAGE_BY_INDEX` 按索引键，加阶段同样缺键报错；其余事实确认，依据 verify/frontend-stages.md [frontend-stages-1]。

**[frontend-stages-2]** 阶段在 DTO 中出现的位置：`Settings.stages/current_stage`（`types.ts:37`，线上是字符串，服务端存 1–4 索引）、`StageInfo`（`:44-48`，含 `name_zh`、`total`、`new_only_total`）、`WordBrief.stages/stage_min/cet6_star`（`:52`）、`Stats.stages`（`:176`）。请求侧派生类型全部由 `Stage` 推出，无需单独改：`endpoints.ts:99-104` `OnboardingBody{stages, current_stage}`、`:112-113` `SettingsUpdate = Partial<Omit<Settings,…>>`、`:127-129` `StagesResponse`、`:131` `VocabStageFilter = Stage | 'all'`、`:135-141` `VocabQuery{stage?, new_only?…}`、`:196` `ScreenStage = Stage | 'auto'`、`:328-334` `PrewarmStage = Stage | 'all'` / `PrewarmBody`。（事实，高）

**[frontend-stages-3]** 两个阶段 DTO 字段前端根本不渲染：`StageInfo.name_zh`（`grep -rn name_zh frontend/src` 只命中 `types.ts:45`；页面全部用 `zh.stages[...]`）和 `Stats.stages`（`HistoryPage.tsx:54` 调 `getStats`，`:67-71` 只读 `heatmap`、`streak_days`、`longest_streak`、`stubborn`）。因此后端 `STAGE_NAMES_ZH`（`schemas.py:52`）改了用户看不到，中文名只认 `zh.ts:28`。（事实，高）

**[frontend-stages-4]** 文案全部集中在 `zh.ts` 四处（事实，高）：
- `:25` `welcome.roles: { zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }`
- `:28-29` `stages: { zk: '初中', gk: '高中', cet4: '四级', cet6: '六级', zkFull: '初中（中考）', gkFull: '高中（高考）', cet4Full: '大学英语四级', cet6Full: '大学英语六级', newOnly: '仅本阶段新增', newOnlyCet6: '仅六级新增（不含四级）', star: '六级星标词' }`
- `:74-75` `settings.stages: '目标阶段', currentStage: '主攻阶段'`
- `:86` `settings.sources.lists: '词表范围：中考、高考、大学英语四级与六级大纲'`
- 另有 `:45` `screen.remaining: (n) => 本阶段还剩 ${n} 个未筛` 与 `:46` `allDone: '这个阶段的词都筛完了 🎉'`，与具体阶段名无关。

**[frontend-stages-5]** 页面级依赖（事实，高）：
| 页面 | 依赖点 |
|---|---|
| `WelcomePage.tsx` | `:30` `Role = 'zk'|'gk'|'uni'|'pro'`；`:33-38` `ROLE_PRESETS`：`zk→{['zk'],'zk'}`、`gk→{['zk','gk'],'gk'}`、`uni→{['gk','cet4','cet6'],'cet4'}`、`pro→{['cet4','cet6'],'cet4'}`；`:40` `ROLES`；`:42` `STAGE_FULL`；`:45-51` `toggleStage`（非空、`current` 必在集合内、按 `STAGE_ORDER` 排序）；`:72-73` 初值：`settings?.stages.length ? settings.stages : ROLE_PRESETS.pro.stages`；`:97-101` 选角色覆盖阶段；`:103-108` 手动切阶段把 `role` 置 null；`:112` 提交守卫 `!stages.includes(current)`；`:236-240` 角色 chips；`:248-252` 阶段 chips 用全称；`:259-265` 主攻阶段 `Segmented block`，选项 = 已选阶段；`:296` 空集合禁用「下一步」 |
| `SettingsPage.tsx` | `:71-77` `toggleStageSetting`（同样约束）；`:202-205` 只有变化才 `save`；`:301-308` 阶段 chips 用短名 `zh.stages[s]`；`:311-318` `Segmented size="sm"`，选项 = 已选阶段，直接 `save({current_stage})` |
| `VocabPage.tsx` | `:29` `TABS = ['all','zk','gk','cet4','cet6']`；`:69-70` 上次 tab 存 `localStorage['wd.vocabTab']`，读回经 `isStage`；`:81` `effectiveNewOnly = tab !== 'all' && newOnly`；`:202` `newOnlyLabel = tab === 'cet6' ? zh.stages.newOnlyCet6 : zh.stages.newOnly`；`:213` `<Tabs … fill …>`；`:232` 开关在所有非 `all` tab 显示 |
| `ScreenPage.tsx` | `:18` `SCREEN_STAGE_KEY='wd.screenStage'`；`:20` `FULL_NAME`；`:31` 把 `GET /api/stages` 结果按 `STAGE_ORDER` 重排并丢弃未知阶段；`:41-43` 骨架按 `STAGE_ORDER` 数量；`:53-56` 每张卡：短名、全称、`remaining(unseen)`、进度条 |
| `ScreenRunPage.tsx` | `:33-35` 路由参数经 `isStage`，标题 `${zh.screen.title} · ${zh.stages[stage]}`；`:56` `getScreenNext(stage, 30)`；`:67-69` 非法参数重定向 `/screen`；`:73` 写 `wd.screenStage` |
| `AdminPage.tsx` | `:36` `PREWARM_STAGES = ['zk','gk','cet4','cet6','all']`（手写，不从 `STAGE_ORDER` 派生）；`:739` 默认 `'cet4'`；`:842-848` `<select>` 标签 `zh.stages[s]` |
| 展示组件 | `WordHeader.tsx:13` `Pick<WordBrief,…,'cet6_star'>`，`:50` 渲染 `StageChips`（`lg`→`md` 尺寸，否则 `sm`）；`WordRow.tsx:97` `StageChips size="sm"`；`StudyCard.tsx:172/207/298` 通过 `WordHeader` 显示阶段 chips；`ScreenCard.tsx:91` `showStages={false}`（筛词卡不显示阶段）；`WordDetailPage.tsx:360` `WordHeader size="lg"`，`:430-440` 另把 ECDICT 原始 `exam_tags` 原样渲染为 chips（不经 `zh`） |

**[frontend-stages-6]** 「六级星」是 cet6 的硬编码特例：`StageChips.tsx:19-20` prop `cet6Star`，`:33-37` `{stage === 'cet6' && cet6Star && (<span className="chip__star" … aria-label={zh.stages.star}>★</span>)}`；`WordBrief.cet6_star`（`types.ts:52`）。加小学不碰它。（事实，高）

**[frontend-stages-7]** 文案规则到底是什么（事实，高）：
- 规则 1「中文只能在 `src/i18n/`」：`frontend/scripts/check-copy.mjs:30-33` 对每个 `*.tsx`（`rel.endsWith('.tsx')` 且不在 `i18n/`）逐行测 CJK 正则；`zh.test.ts:45-48` 在 `npm test` 里用 Vite raw glob 做同一检查。`.ts` 文件不受此限（只有 `.tsx`）。
- 规则 2「禁词 单词本」：`check-copy.mjs:14,32`、`zh.test.ts:11,50-53`，对所有 `.ts/.tsx/.css/index.html` 生效。
- 规则 3「`zh.ts` 必须与 `docs/FRONTEND.md` §8 镜像」：`zh.test.ts:67-83` 取两边 `export const zh = {` 到 `} as const;` 的块，`trimEnd()` 后去掉空行，**逐行 `toEqual`**（所以行的切分、键的顺序、每行内容都必须一致，只容忍行尾空白与空行）；`zh.contract.test.ts:21-28` 从 `## 8. i18n strings` 后的首个 ```` ```ts ```` 围栏取块，`:62-83` 用 `typescript.transpileModule` 求值后比较「键集合相同 + 字符串/格式化函数相同」。结论：**新增任何中文文案键（如 `stages.xx`、`welcome.roles.xx`）必须同一提交写进 `docs/FRONTEND.md:211-310` 的代码块，并且逐行一致**，否则 `npm test` 两处失败。`FRONTEND.md:312` 的规则句只提到 CJK grep 与禁词，镜像规则写在 `zh.ts:3-4` 注释和两个测试里。
- 执行链：`package.json:14-16` `typecheck` / `test` / `lint`（lint = `node scripts/check-copy.mjs`）；`Makefile:77-81` `make test` = pytest → `scripts/check_contract.py -q` → `npm run typecheck && npm test && npm run build`，**不含 `npm run lint`**（但 `zh.test.ts` 已覆盖同样规则）。
- 术语表约束：`docs/DESIGN.md:57` 「§0.3 Binding zh-CN glossary (UI copy must use these exact terms)」，`:72` `| Stages | 初中 / 高中 / 四级 / 六级 | zk / gk / cet4 / cet6 (stage index 1–4) |` → 新阶段的 UI 词也要进这张表。

**[frontend-stages-8]** `Stage` 联合还被仓库级合同审计锁死，且**顺序敏感**：`scripts/check_contract.py:274-281` 对 `types.ts` 每个字面量联合取同名 `schemas.py` `Literal`，`py_values = list(typing.get_args(alias)); if py_values != values: out.hard.append(...)`（列表比较）。`schemas.py:25` `Stage = Literal["zk", "gk", "cet4", "cet6"]`、`:26` `StageIndex = Literal[1, 2, 3, 4]`。所以前端把小学放在联合首位而后端追加在末位，`make test` 第二步就会硬失败。（事实，高）

---

## B. (a) 新增「小学」阶段的前端改动清单

下表以「新增代码标识 `xx`（小学拼音首字母，与 `zk/gk` 同构；仅为占位，最终命名需与后端 `Literal`、`words.stage_xx` 列名一致）、`STAGE_ORDER` 置于首位」为前提。估算行数为净改动行（事实部分为位置，行数为推断）。

**[frontend-stages-9]** 必改代码（置信度高）：
| 文件:行 | 要做什么 | 估计 |
|---|---|---|
| `frontend/src/api/types.ts:5-6` | `Stage` 加 `'xx'`（位置须与 `schemas.py:25` 完全一致，见 [8]）；`StageIndex` 按后端索引方案加 `0` 或改为 `1|2|3|4|5`；`:5` 注释「index 1..4」、`:45` 注释「初中 / 高中 / 四级 / 六级」同步 | 3 |
| `frontend/src/components/word/StageChips.tsx:7-9` | `STAGE_ORDER` 首位插 `'xx'`；`STAGE_INDEX`、`STAGE_BY_INDEX` 各加一键；`:1` 注释 | 3 |
| `frontend/src/i18n/zh.ts:28-29` | `stages` 加 `xx: '小学'`、`xxFull: '小学（…）'`（括号内写什么见未解决问题）；`:25` `welcome.roles` 加 `xx: '小学生'`（若要加角色）；`:86` `sources.lists` 补小学词表来源 | 3-4 |
| `docs/FRONTEND.md:231-235, 292` | 与上一行逐行镜像（[7] 规则 3） | 同上 |
| `frontend/src/pages/WelcomePage.tsx:30,33-40,42` | `Role` 加 `'xx'`；`ROLE_PRESETS` 加 `xx: { stages: ['xx'], current: 'xx' }`（并决定 `zk` 预设是否改为 `['xx','zk']`，见 [14]）；`ROLES` 加 `'xx'`；`STAGE_FULL` 加键；`:1-3` 注释 | 6-8 |
| `frontend/src/pages/ScreenPage.tsx:20` | `FULL_NAME` 加键 | 1 |
| `frontend/src/pages/VocabPage.tsx:29` | `TABS` 加 `'xx'`；`:1` 注释；`:202/232` 处理「最低阶段不显示开关」或加 `newOnlyZk` 文案（见 [17]） | 2-4 |
| `frontend/src/pages/AdminPage.tsx:36` | `PREWARM_STAGES` 加 `'xx'`（或改为 `[...STAGE_ORDER, 'all']` 一劳永逸） | 1 |
| 合计 | 7 个源文件 | ≈ 20-25 行 |

**[frontend-stages-10]** 不需要改（事实，高）：`SettingsPage.tsx`（`:303`、`:315` 都遍历 `STAGE_ORDER`，`toggleStageSetting` 泛化）、`ScreenRunPage.tsx`（`isStage`）、`endpoints.ts`（全部由 `Stage` 派生，[2]）、`WordRow/WordHeader/StudyCard/StateBadge`、`routes.tsx:39,84`（`/screen/:stage` 任意字符串）、`useLocalPref`（`wd.vocabTab`、`wd.screenStage` 读回都经 `isStage`，旧值仍合法，无需迁移）。

**[frontend-stages-11]** 必改文档（镜像/合同，事实，高）：`docs/API.md:155`（endpoint 12）、`:160`（endpoint 15 `stages` 非空 ⊆ {zk,gk,cet4,cet6}）、`:167`（endpoint 19 "4 rows"）、`:169`（endpoint 20 `stage=all|zk|gk|cet4|cet6`、cet6 3,694）、`:187`（endpoint 31 `stage=…|auto`）、`:230`（endpoint 67 prewarm 枚举）、`:239-240`（§9 `Stage`/`StageIndex`，与 `types.ts` 逐字相同）、`:279`（`StageInfo.name_zh` 注释）、`:460`（§9.1 `zk→1…` 映射）；`docs/FRONTEND.md:50`（欢迎页角色列表）、`:54-56`（筛词 / 词库 tab 列表）、`:89`（StageChips 行）、`:147`（§5.5 六级标签说明）、`:108-116`（§5.1 示意图里的「高中 · 四级 · 六级」，可选）；`docs/DESIGN.md:32`、`:40`（"four stage tabs"）、`:72`（§0.3 术语表，**绑定**）、`:330`（§6.2 角色预设）；`docs/qa-frontend.md:36,42,70,84`（人工用例）。

**[frontend-stages-12]** 索引方案对前端的影响（事实 + 推断，置信度中）：
- 后端约束：`0001_init.sql:148` `current_stage INTEGER … CHECK (current_stage BETWEEN 1 AND 4)`，`:185` `stage_min INTEGER CHECK (stage_min BETWEEN 1 AND 4)`；推荐词排序用数值距离 `stage_distance(w.stage_min, current_stage)`（`docs/DESIGN.md:347-350`）。因此小学的索引必须与 `STAGE_ORDER` **单调一致**（放首位就得是 0 或把 zk..cet6 顺延为 2..5），否则排序把小学算成离初中最远。
- 方案 A「小学 = 0，其余不动」：前端只改 [9] 所列；`StageIndex = 0|1|2|3|4`；测试夹具不动。
- 方案 B「重编号 1..5」：额外要改 12 处数字夹具（`grep -rn 'stage_min: [0-9]' frontend/src --include='*.test.*' | wc -l` = 12，分布在 10 个测试文件：`queue.test.ts`、`AddWordPreviewRow.test.tsx`、`StudyCard.test.tsx`、`WordRow.test.tsx`、`SpeakButton.test.tsx`、`WordDetailPage.test.tsx`、`ScreenRunPage.test.tsx`、`WelcomePage.test.tsx`、`StudyPage.test.tsx`、`BankPage.test.tsx`）；它们不会报错（只断言文字），但 `chip--min` 高亮（`StageChips.tsx:31` `stageMin === STAGE_INDEX[stage]`）会静默错位，属语义漂移。
- 两案都要改 `types.ts:6` / `schemas.py:26` / `API.md:240` 三处 `StageIndex`，且 [8] 的审计也比较 `StageIndex` 的 `Literal` 顺序。

> **核验修正（INDEX §3 #14，2026-11-05）**：方案 A（小学 = 0）的成本被低估、前提不成立——后端索引由位置推导（`schemas.py:56-61` `stage_to_index = STAGE_ORDER.index(stage) + 1`，`:64-67` `index_to_stage` 断言 `1 <= index <= 4`），把小学插到 `STAGE_ORDER` 首位后端自然得到小学=1、zk=2…（即方案 B）；要得到「小学 = 0」必须改写这两个函数、重建 `words.stage_min` 与 `user_settings.current_stage` 的 CHECK（SQLite 不能 ALTER CHECK）并修 3 处 `or DEFAULT_CURRENT_STAGE` 的 0 值陷阱；两案都要重建两张表，后端成本 A ≥ B，「两案成本差 12 处夹具」只是前端口径；12 处夹具 / 10 个文件与 CHECK 行号确认，依据 verify/frontend-stages.md [frontend-stages-12]、facts/stage-model.md [stage-model-9]。

**[frontend-stages-13]** 部署顺序：`ScreenPage.tsx:31` 对服务端未返回的阶段静默跳过、对服务端多返回的阶段静默丢弃，所以筛词页前后端任一顺序上线都不崩；但词库 tab 会向 `GET /api/vocab?stage=xx` 发请求，后端 `schemas.py:488` `stage: Literal["all","zk","gk","cet4","cet6"]` 未扩展时返回 400 `validation_error`（`docs/TASKS.md:38` 「422 → 400 validation_error」），页面显示错误条（`VocabPage.tsx:263-270`）。应后端先上。（事实 + 推断，高）

---

## C. (b) UX 问题

**[frontend-stages-14]** 欢迎页角色与默认阶段（事实 + 推断/产品决策）：
- 现状（事实）：`WelcomePage.tsx:33-38`，`高中生` 预设向下包含初中（`['zk','gk']`），`初中生` 只有 `['zk']`（当时没有更低阶段）；`docs/DESIGN.md:330` 与 `docs/qa-frontend.md:36` 原文同此。主攻阶段 = 预设 `current`；`Segmented` 只列已选阶段（`:262`）。
- 现状（事实）：未点角色时的初值不是来自角色而是 `settings`——服务端为新用户写死 `stages_json DEFAULT '["cet4","cet6"]'`、`current_stage DEFAULT 3`（`0001_init.sql:147-148`），`WelcomePage.tsx:72-73` 只在 `settings.stages` 为空时才退回 `ROLE_PRESETS.pro`。所以一个上海小学生打开欢迎页，默认勾着「大学英语四级/六级」、主攻「四级」，直到他点「我是…」。线上副本两名用户的设置：`sqlite3 -readonly live-copy.db "SELECT stages_json,current_stage,COUNT(*) FROM user_settings GROUP BY 1,2"` → `["zk","gk","cet4","cet6"]|3|1` 与 `["zk"]|1|1`。
- 建议（推断，低—产品决策）：加 `小学生` 角色，`xx: { stages: ['xx'], current: 'xx' }`；若要与 `高中生` 的「向下包含一级」模式一致，则 `初中生` 改为 `{ stages: ['xx','zk'], current: 'zk' }`（推荐词排序会先出主攻阶段，再高阶，再低阶，`DESIGN.md:347`，所以多含一个低阶只是在后面多一些简单推荐词）。面向上海 K12 时，服务端默认值与 `:72-73` 的兜底都应改成 K12 预设（后端改动）。
- 宽度（推断，中）：角色 chips 用 `.welcome__chips .chip-btn`（`WelcomePage.css:45-49`：`min-height: var(--tap)`=44px、`padding: 0 var(--space-4)`=16px、`font-size: var(--text-md)`=16px），`flex-wrap: wrap`（`:39-43`）。375px 下内容宽 = 375 − 2×16（`tokens.css:53` `--gutter`）= 343px。现有四个角色：3×(48+32) + (64+32) + 3×8 = 360 > 343，**现在已经折成两行**；加「小学生」后为 3 + 2 两行，无溢出。阶段 chips 用全称（6 字 = 96 + 32 = 128px），一行放 2 个（2×128+8 = 264 ≤ 343，3 个 392 > 343），4 个两行 → 5 个三行；主攻阶段 `Segmented block`（`ui.css:513-523`：`padding 0 12px`，md 字 16px）5 项 = 5×(32+24) + 4×2 + 6 = 294 ≤ 343，放得下。

**[frontend-stages-15]** 阶段 chips（`StageChips`）一行放 5 个（推断，中；基于 `word.css:77-103`、`list.css:97-103`、`word.css:58-65`）：
- 容器 `.chips` 是 `inline-flex; flex-wrap: wrap; gap: 4px`，所以**只会换行，不会溢出**。
- 列表行 `sm`：`.chip` `padding 1px 8px`、`border 1px`、`font-size var(--text-xs)`=12px → 「小学」= 24 + 16 + 2 = 42px；5 个 = 5×42 + 4×4 = 226px。同一行 `.word-row__chips`（`gap 8px`，`flex-wrap`）还放 `StateBadge`：未标记词「未标记」≈ 36+16 = 52 → 226+8+52 = 286 ≤ 343 一行放下；在学词「学习中 · 3 天后」≈ 96+16 = 112 → 346 > 343，**在 375px 会折成两行**。
- 学习卡正面 `lg` 头 → chips `md`（`.chips--md .chip` `padding 2px 10px`、14px）→ 「小学」= 28 + 20 + 2 = 50px；5 个 = 266px；`.word-head__meta`（`flex-wrap`，`gap 8px`）还含音标（lg 时 16px，如 `/ˈæpl/` ≈ 60px）与 `KindBadge`「新词」（≈ 40px）→ 266+8+60+8+40 = 382 > 343，**折成两行**。
- 受影响的恰是小学词：它们通常同时带 zk/gk/cet4/cet6（累计标注），所以 5 个 chip 全满的情况在小学词上是常态而非例外。可选对策（推断）：只渲染 `stage_min` 对应 chip + 「+N」，或只渲染用户 `settings.stages` 内的阶段；现有组件无此能力（`StageChips.tsx:26` 直接 `STAGE_ORDER.filter`）。

> **核验修正（INDEX §3 #17，2026-11-05）**：「5 个 chip 全满在小学词上是常态」被数据推翻——线上副本 `SELECT (stage_zk+stage_gk+stage_cet4+stage_cet6) n, COUNT(*) FROM words WHERE stage_zk=1 GROUP BY 1` → 1|33、2|94、3|1118、4|854：2,099 个初中词里只有 854（40.7%）带满四个标签，94% 带 ≥3 个；标注也非严格累计（zk 且非 gk 62、gk 且非 cet4 706、cet4 且非 cet6 1,186）；若小学表 ⊆ 初中表，加小学后「5 个全满」最多约四成、「≥4 个」约九成——换行风险真实但不是常态；CSS 前提与宽度算术确认，依据 verify/frontend-stages.md [frontend-stages-15]。

**[frontend-stages-16]** 词库页 6 个 tab 在 375px（推断，中；基于 `ui.css:440-470`、`global.css:16-26,145-150`、`tokens.css:46-53,64-69`）：
- `.tab`：`padding: 0 var(--space-3)`=12px、`white-space: nowrap`、无 `font-size`（继承 body `1rem`=16px）、`min-height: var(--tap)`=44px；`.tabs--fill .tab { flex: 1 1 0 }` 但 flex 子项默认 `min-width:auto`，不能缩到内容以下；`.tabs` `gap: 4px; overflow-x: auto; scrollbar-width: none`。
- 两字标签最小宽 = 32 + 24 = 56px。现 5 tab：5×56 + 4×4 = 296 ≤ 328（360px 内容宽）—— 现在 360px 也放得下。6 tab：6×56 + 5×4 = **356px**，对比 375px 内容宽 343px 溢出 13px、360px 溢出 28px、390/393px（iPhone 14/15）内容宽 358/361 放得下。溢出表现为 tablist 可横向滚动但不显示滚动条（`scrollbar-width:none`），最右「六级」被裁掉约 13px，用户只能靠滑动发现；`FRONTEND.md:176` 的「no horizontal scroll at 360 px」说的是页面级，tablist 内滚动不违反字面，但正是「挤」的症状。
- 先例：`BankPage.tsx:316` 的 6 个 tab 不加 `fill`，本来就靠 `overflow-x: auto` 横滑。
- 可选对策（推断）：① 去掉 `fill`（与生词库一致，接受横滑）；② `@media (max-width: 479.98px) .tabs--fill .tab { padding-inline: var(--space-2) }` → 6×(32+16)+20 = 308 ≤ 328，360px 也放下；③ 字号降到 `--text-sm`：6×(28+24)+20 = 332，375px 放下、360px 仍溢 4px；④ 把阶段 tab 改成 `Segmented`/`<select>`。

**[frontend-stages-17]** 设置页阶段多选约束（事实，高）：
- 非空子集：`SettingsPage.tsx:73-74` `if (has && stages.length === 1) return { stages: [...stages], current_stage: current };`（最后一个不可取消，无提示，静默不保存：`:204` 只有变化才 `save`）；`WelcomePage.tsx:47` 同逻辑。
- 主攻阶段必在集合内：`SettingsPage.tsx:76` `next.includes(current) ? current : (next[0] ?? current)`——取消主攻阶段时主攻自动落到**最低**的已选阶段（`next[0]`，按 `STAGE_ORDER`）。小学加在首位后，取消主攻会落到「小学」（若已选），这是顺序带来的行为变化。
- 服务端同样校验：`docs/API.md:160` 「`stages` non-empty ⊆ {zk,gk,cet4,cet6} and `current_stage ∈ stages`」；`schemas.py:77-81` `_unique_stages`（空则 `ValueError`）、`:361-363`、`:427`。无上限，5 个可全选。
- 宽度（推断，中）：`.settings__stages` `flex-wrap; gap 8px`（`SettingsPage.css:93-98`），`.chip-btn` `min-height 32px; padding 0 12px; font-size var(--text-sm)`（`bank.css:144-152`）→ 「小学」52px，5 个 = 5×52 + 4×8 = 292 ≤ 343 **一行放下**；`Segmented size="sm"`（`ui.css:521-545`）5 项 = 5×52 + 8 + 6 = 274 ≤ 343 放下。
- 测试：`SettingsPage.test.tsx:216-221` 固定了 `toggleStageSetting` 的四条行为（含 `['zk'],'zk','cet6' → ['zk','cet6'],'zk'`），加阶段不影响其结果。

---

## D. (c) 「仅本阶段新增」在加小学后的语义

**[frontend-stages-18]** 语义定义（事实，高）：`types.ts:46` `new_only_total: number; // … words whose lowest stage is this one`；后端 `backend/wd/routers/vocab.py:51-54`
```py
where.append(f"w.stage_{q.stage} = 1")
if q.new_only == 1:
    where.append("w.stage_min = :stage_idx")
    params["stage_idx"] = stage_to_index(q.stage)
```
`stage_min` = 最低阶段索引（`0001_init.sql:185-186` 「lowest stage … 仅本阶段新增 filter == stage_min = <stage index>」）。前端只是透传 `new_only: true`（`VocabPage.tsx:85`，`client` 序列化为 `new_only=1`，`client.test.ts:56`）。

**[frontend-stages-19]** **zk 的 newOnly 现在是恒等过滤（空操作）**（事实，高）：zk 是最低阶段，`stage_zk=1 ⇒ stage_min=1`。线上副本：`sqlite3 -readonly live-copy.db "SELECT COUNT(*) FROM words WHERE stage_zk=1 AND is_public=1 AND merged_into_word_id IS NULL"` = 2099；`… WHERE stage_min=1 …` = 2099；`SELECT COUNT(*) FROM words WHERE stage_zk=1 AND stage_min<>1` = 0。对照：gk 3829 vs `stage_min=2` 1792；cet6 7671 vs `stage_min=4` 3694。而 `VocabPage.tsx:232` 在所有非 `all` tab 都显示开关，`:202` 只给 cet6 特殊文案——即今天初中 tab 上的「仅本阶段新增」开了没变化，这是一个现存的小 UX 不一致（`docs/qa-frontend.md:42` 只核了六级 3,694）。

**[frontend-stages-20]** 加小学之后（事实推导 + 推断，高/中）：
- 若小学成为新的最低阶段（索引 0 或重编号为 1），zk 的 `new_only` 变成**真过滤**：「初中词里不在小学表的」（`stage_zk=1 AND stage_min=idx(zk)`）。其规模 = 2099 − |小学表 ∩ 初中表|，小学表未定，**无法计算**。
- 「仅本阶段新增」= 「最低阶段是本阶段」这一定义不变，所以通用文案 `newOnly: '仅本阶段新增'` 仍正确；若想对称于 `newOnlyCet6`，可加 `newOnlyZk: '仅初中新增（不含小学）'` 并把 `:202` 的三元改成查表（+2 行 zh + 镜像）。
- 空操作会转移到小学 tab：建议 `:232` 改为 `tab !== 'all' && tab !== STAGE_ORDER[0]` 隐藏最低阶段的开关（+1 行），顺手修掉 [19] 的现存不一致。
- 风险（推断）：`DESIGN.md:186` 假定阶段标注「cumulative as in the sources」。若小学表（上海牛津等）含**不在**初中表的词，这些词 `stages=['xx']`、`stage_min=idx(xx)`，初中 tab 看不到它们——不是前端问题，但会让「初中生 → ['zk']」预设漏掉这些词；这正是 [14] 建议 `初中生` 预设包含 `'xx'` 的另一个理由。

---

## E. (d) 若加「地区」（上海/全国）开关

**[frontend-stages-21]** 现状：前端没有任何「地区」概念——`Settings`（`types.ts:34-43`）无相关字段，`zh.ts` 无相关文案，`endpoints.ts` 无相关查询参数（`grep -rn -i 'region\|上海\|全国' frontend/src` 无命中）。（事实，高）

**[frontend-stages-22]** 放在哪一页（推断，中）：
- 首选作为**每用户设置**：`Settings.region: 'sh' | 'cn'`，页面 `SettingsPage.tsx` 「学习设置」`LearnSection`（`:408-445`），照抄「口音」块 `:432-442` 的 `Segmented size="sm"` + `save({ accent })` 模式（+12 行左右），文案 `settings.region: '词表地区'`、`settings.regions: { sh: '上海', cn: '全国' }`（+2 键，镜像 §8）；欢迎页第 1 步在「我是…」与「目标阶段」之间加一组（`WelcomePage.tsx:243-254` 之前，+15 行），并进 `OnboardingBody`（`endpoints.ts:99-104`，+1 行）与 `saveOnboarding` 调用（`:116`）。
- 不建议做成阶段枚举的一部分（如 `xx_sh` / `xx_cn`）：会让 tab、chips、预设、`Record<Stage,…>` 全部翻倍（[1]、[15]、[16]）。
- 由于地区会改变「哪些词属于哪个阶段」，应由**服务端按用户设置解析**，客户端不逐请求传 `region=`；否则 `VocabQuery`（`endpoints.ts:135-141`）、`getStages`（`:421`）、`getScreenNext`（`:445-446`）签名、`useLocalPref` 键都要改，并且每个词的 `WordBrief.stages/stage_min`（`types.ts:52`）会随请求参数变化而失去稳定含义。

**[frontend-stages-23]** 影响哪些请求（事实，高——列出所有带阶段语义的调用）：`GET /api/vocab`、`GET /api/vocab/letters`（`endpoints.ts:423,425`，`stage`/`new_only`）、`GET /api/stages`（`:421`）、`GET /api/screen/next?stage=`（`:445-446`，含 `auto`）、`POST /api/onboarding`（`:397`）、`PUT /api/settings`（`:408`，经 `AuthContext.tsx:142-146` `updateSettings`）、`GET /api/stats`（`:497`，`Stats.stages` 虽不渲染但随之变化）、`POST /api/admin/content/prewarm`（`:535`）；以及所有携带 `WordBrief` 的响应（词库、生词库、今日、批次、筛词、查词、详情）的 `stages/stage_min/cet6_star`。合同改动三件套（`types.ts:1-2` 规则）：`types.ts` `Settings` +1 字段、`Region` 联合；`schemas.py` 同名 `Literal`（顺序一致，[8]）；`API.md` §9 与 endpoint 12/15 校验句。

---

## F. (e) 会因新增阶段而失败的前端测试/门禁

**[frontend-stages-24]** 一定会失败（若只改 `zh.ts` 不改文档）（事实，高）：
- `frontend/src/i18n/zh.test.ts:67-83` 「is mirrored line for line by the binding block in docs/FRONTEND.md §8」。
- `frontend/src/i18n/zh.contract.test.ts:67-73`（键集合）与 `:75-83`（值相同）。
- 触发条件：`stages.xx`/`xxFull`、`welcome.roles.xx`、改 `settings.sources.lists`、新增 `newOnlyZk`、新增 `settings.region*` 中的任一项。

**[frontend-stages-25]** 会在 `make test` 更早的两道门失败（事实，高）：
- `scripts/check_contract.py:274-281`（`Makefile:80`）：`type Stage`/`type StageIndex` 的成员列表与 `schemas.py:25-26` 不等（含顺序）即硬失败。
- `npm run typecheck`（`Makefile:81`，先于 vitest；`tsconfig.json:30` `include: ["src"]` 覆盖测试文件）：`Stage` 扩展后以下 `Record<Stage,…>` 字面量缺键报错——`StageChips.tsx:8-9`、`WelcomePage.tsx:42`、`ScreenPage.tsx:20`、`zh.test.ts:56`（该「测试」实为编译期断言：vitest 走 esbuild 不做类型检查，`vite.config.ts:39-43` 未开 `typecheck`，所以它只在 tsc 阶段生效）。按键索引的 `zh.stages[s]`（`VocabPage.tsx:213`、`SettingsPage.tsx:305,315`、`ScreenPage.tsx:54,57`、`ScreenRunPage.tsx:35`、`AdminPage.tsx:845`）在 `zh.stages` 缺 `xx` 时同样报错。

**[frontend-stages-26]** 固定了四阶段细节、但**只要现有键与索引不变就不会失败**的断言（事实，高）：`SettingsPage.test.tsx:218-221`（`toggleStageSetting` 四例）、`SpeakButton.test.tsx:91,100`（chips 顺序 `[gk, cet4, cet6★]`、`:102` 星标 `aria-label`）、`endpoints.test.ts:24,46,51`（`stage=cet6&new_only=1`、`stage=auto&count=30`）、`client.test.ts:54-56,147`、`ScreenRunPage.test.tsx:51`（`/screen/cet4`）、`WelcomePage.test.tsx:63-64`（mock `settings.stages: ['cet4']`）、`AuthContext.test.tsx:18-19`。若采用重编号（[12] 方案 B），12 处 `stage_min` 数字夹具需同步，否则语义漂移而测试仍绿。

**[frontend-stages-27]** 覆盖空白（事实，高）：没有 `ScreenPage.test.tsx`；`VocabPage.test.tsx` 不断言 tab 数量或标签（`:15-33` 只测两个 `<select>` 的可访问名）；`WelcomePage.test.tsx` 只测第 2 步（`:100-146`），第 1 步角色/预设无自动化测试，只有 `docs/qa-frontend.md:36` 的人工项。新增阶段/角色时若想有回归保护，需要新写断言（例如 `TABS.length === STAGE_ORDER.length + 1`、`ROLE_PRESETS` 每个 `current ∈ stages`）。

---

## 未解决的问题

1. 代码标识与索引：小学用 `xx` 还是其他（须与后端 `Literal`、`words.stage_<name>` 列名、`STAGE_NAMES_ZH` 一致，且联合顺序一致 [8]）；索引取 0 还是重编号 1..5（[12]）——由后端/数据切片决定，前端两案成本差 12 处夹具。
2. `xxFull` 的全称写什么：对称于「初中（中考）」的「小学（…）」括号内无对应考试；若按上海教材写「小学（上海牛津）」则与地区开关耦合。
3. 小学表是否完全包含于初中表（决定 [20] 的风险与 `初中生` 预设是否该含 `'xx'`）；小学 ∩ 初中的规模无法在现有库里计算。
4. 地区开关是否只影响小学，还是也影响初中/高中词表；若只影响小学，是否值得做成全局设置而非小学 tab 内的子选项。
5. 服务端新用户默认 `'["cet4","cet6"]'/3`（`0001_init.sql:147-148`）是否随 K12 定位调整；前端 `WelcomePage.tsx:72-73` 的兜底只在服务端返回空集合时生效。
6. 页宽算术全部基于「CJK 字形 1em、根字号 16px」的假设，未在真机/浏览器量测；`fill` tab 的 13px 溢出需在 375px 设备或 DevTools 复核。
7. 是否要在 `StageChips` 引入「只显示 `stage_min` + N」或「只显示用户目标阶段」的收敛策略（[15]），属设计决策。
