# verify/frontend-stages — 对 facts/frontend-stages.md 的对抗性核验

基线：仓库 `/Users/sqin/word-dance`，分支 main @ `75df534`（`git rev-parse --short HEAD`），核验日期 2026-11-05。只读仓库，未改任何代码；写入仅本文件。

## 范围与方法

- 读完 `facts/frontend-stages.md` 全文（27 条结论 + 7 条未解决问题），对全部 27 条逐条独立复核；所有 path:line 均在 75df534 重新打开（`cat -n` / `sed -n`），计数全部重算。
- 代码复核（`cat -n` + `grep -rn`）：`frontend/src/api/types.ts`、`frontend/src/api/endpoints.ts`、`frontend/src/components/word/StageChips.tsx`、`WordHeader.tsx`、`word.css`、`frontend/src/components/list/WordRow.tsx`、`list.css`、`frontend/src/components/study/StudyCard.tsx`、`ScreenCard.tsx`、`frontend/src/components/ui/Tabs.tsx`、`ui.css`、`frontend/src/components/bank/bank.css`、`frontend/src/i18n/zh.ts`、`zh.test.ts`、`zh.contract.test.ts`、`frontend/scripts/check-copy.mjs`、`frontend/src/pages/{WelcomePage,SettingsPage,VocabPage,ScreenPage,ScreenRunPage,AdminPage,HistoryPage,WordDetailPage,BankPage}.tsx` 及对应 `.css`、`frontend/src/routes.tsx`、`frontend/src/auth/AuthContext.tsx`、`frontend/src/hooks/useLocalPref.ts`、`frontend/src/styles/{tokens,global}.css`、`frontend/vite.config.ts`、`frontend/tsconfig.json`、`frontend/package.json`、`Makefile`、`scripts/check_contract.py`（并实际运行：`cd backend && ../.venv/bin/python ../scripts/check_contract.py` → `contract OK`，只读）。
- 后端对照：`backend/wd/schemas.py`、`backend/wd/routers/vocab.py`、`backend/wd/services/{screen,batches,bank,words,stats,ecdict}.py`、`backend/wd/ai/{content,prewarm}.py`、`backend/wd/seed.py`、`backend/wd/security.py`、`backend/wd/errors.py`、`backend/wd/migrations/*.sql`（4 个文件：0001、0008、0009、0010）。
- 文档：`docs/FRONTEND.md`、`docs/API.md`、`docs/DESIGN.md`、`docs/TASKS.md`、`docs/qa-frontend.md`、`README.md`、`ATTRIBUTION.md`。
- 测试：9 个被引用的 `*.test.*` 文件逐行核对；`find frontend/src -name '*.test.*' | wc -l`；`grep -rl cet6 frontend/src --include='*.test.*' | wc -l`。
- 线上库只读副本 `scratchpad/live-copy.db`（5,644,288 字节）：`sqlite3 -readonly` 重算所有计数（命令见各条）。
- 未联网、未下载：原文件为纯代码核验，无网页结论需复访。
- 页宽算术沿用原文假设（CJK 字形 1em、根字号 16px），但额外核对了该假设成立的前提（`button { font: inherit }`、`.page` 侧边距），未做真机/浏览器量测。

---

## 逐条核验

**[frontend-stages-1]** 结论：**修正（小处）**。
- 事实部分全部确认：`frontend/src/api/types.ts:5` `export type Stage = 'zk' | 'gk' | 'cet4' | 'cet6';           // index 1..4 in that order`，`:6` `StageIndex = 1 | 2 | 3 | 4`；`frontend/src/components/word/StageChips.tsx:7-9` 三张映射表、`:11-13` `isStage()` 用 `STAGE_ORDER.includes`；`types.ts:1-2` 冻结合同注释原文一致。
- 计数有误：原文「`grep -rn 'Record<Stage' frontend/src` 只有这 4 处（含 StageChips 两处）」。实测该命令返回 **5 行 / 4 个文件**：`StageChips.tsx:8`（`Record<Stage, StageIndex>`）、`StageChips.tsx:9`（`Record<StageIndex, Stage>`，被同一 grep 命中但键是索引）、`zh.test.ts:56`、`WelcomePage.tsx:42`、`ScreenPage.tsx:20`。原文正文列了 3 处「其他」+ StageChips 2 处 = 5，与「4 处」自相矛盾。正确说法：5 处字面量映射（4 个文件），其中 `STAGE_BY_INDEX` 是按索引键，加阶段同样缺键报错。置信度高。

**[frontend-stages-2]** 结论：**确认**。`types.ts:37`（`stages: Stage[]; current_stage: Stage;   // Stage string on the wire; the server stores the 1–4 index`）、`:44-48` `StageInfo`、`:52` `WordBrief.stages/stage_min/cet6_star`、`:176` `Stats.stages`；`endpoints.ts:99-104` `OnboardingBody`、`:113` `SettingsUpdate`、`:127-129` `StagesResponse`、`:131` `VocabStageFilter`、`:135-142` `VocabQuery`、`:196` `ScreenStage`、`:328-334` `PrewarmStage`/`PrewarmBody` 均在所述行。置信度高。

**[frontend-stages-3]** 结论：**确认（附补充）**。`grep -rn name_zh frontend/src` 只命中 `types.ts:45`；`HistoryPage.tsx:54` `getStats`，`:67-71` 只读 `heatmap/streak_days/longest_streak/stubborn`。补充（原文未提）：`STAGE_NAMES_ZH`（`backend/wd/schemas.py:52`）确实不进 UI，但中文阶段名还有第二个消费者——`backend/wd/ai/content.py:49` `STAGE_ZH = {"zk": "初中", …}`，`:88` `"stages": [STAGE_ZH[s] for s in words.stages_of(word)]` 把中文阶段名写进 AI 生成请求（见 `backend/tests/unit/test_runner.py:27` 夹具 `"stages": ["高中", "四级"]`）。所以「改了用户看不到」只对 UI 成立，对 AI 例句/配图提示词不成立。置信度高。

**[frontend-stages-4]** 结论：**确认**。`zh.ts:25` `roles: { zk: '初中生', gk: '高中生', uni: '大学生', pro: '职场人士' }`；`:28-29` `stages` 11 个键原文一致；`:75` `stages: '目标阶段', currentStage: '主攻阶段'`（原文写 `:74-75`，实际同在 75 行）；`:86` `lists: '词表范围：中考、高考、大学英语四级与六级大纲'`；`:45-46` `remaining`/`allDone`。置信度高。

**[frontend-stages-5]** 结论：**确认**。逐格抽核：`WelcomePage.tsx:30,33-38,40,42,45-51,72-73,97-101,103-108,112,236-240,248-252,259-265,296`；`SettingsPage.tsx:71-77,202-205,301-308,311-318`；`VocabPage.tsx:29,69-70,81,202,213,232`；`ScreenPage.tsx:18,20,31,41-43,53-56`；`ScreenRunPage.tsx:33-35,56,67-69,73`；`AdminPage.tsx:36,739,842-848`；`WordHeader.tsx:13,50`；`WordRow.tsx:97`；`StudyCard.tsx:172,207,298`；`ScreenCard.tsx:91` `showStages={false}`；`WordDetailPage.tsx:360,430-440`（`exam_tags` 原样渲染 `<li className="chip">{t}</li>`）。全部与原文一致。置信度高。

**[frontend-stages-6]** 结论：**确认**。`StageChips.tsx:19-20` `cet6Star?: boolean`，`:33-37` `{stage === 'cet6' && cet6Star && (<span className="chip__star" role="img" aria-label={zh.stages.star} …>★</span>)}`；`types.ts:52` `cet6_star: boolean`。置信度高。

**[frontend-stages-7]** 结论：**确认**。
- `frontend/scripts/check-copy.mjs:30` `const copyAllowed = rel.startsWith('i18n/')`，`:33` `if (!copyAllowed && rel.endsWith('.tsx') && CJK.test(line))`——确只管 `.tsx`；`:14,32` 禁词对所有文件。`zh.test.ts:13` glob 只取 `/src/**/*.tsx`（`:45-48`），`:14-18` 禁词 glob 含 `.ts/.tsx/.css/index.html`（`:50-53`）。
- 镜像规则：`zh.test.ts:71-82` 取 `export const zh = {` 到 `} as const;`，`trimEnd()` 后过滤空行，`expect(block(frontendMd)).toEqual(block(zhSource))`——逐行相等，确认。`zh.contract.test.ts:21-28` 从 `## 8. i18n strings` 后首个 ```` ```ts ```` 取块，`:67-73` 键集合、`:75-83` 值比较，确认。
- 执行链：`frontend/package.json:14-16`（`lint` = `node scripts/check-copy.mjs`）；`Makefile:77-81` `test` = pytest → `scripts/check_contract.py -q` → `npm run typecheck && npm test && npm run build`，**不含 lint**，确认。`docs/FRONTEND.md:312` 规则句只提 CJK grep 与禁词，确认；`docs/DESIGN.md:57` §0.3 标题、`:72` 阶段术语行原文一致。置信度高。

**[frontend-stages-8]** 结论：**确认（并实测）**。`scripts/check_contract.py:274-281` `py_values = list(typing.get_args(alias)); if py_values != values: out.hard.append(...)`——列表比较、顺序敏感；`:157-170` 的联合解析同时接受字符串与整数字面量（`:163-164` `re.fullmatch(r"-?\d+", p)` → `int(p)`），所以 `StageIndex = 1 | 2 | 3 | 4` 也在比较范围内。`backend/wd/schemas.py:25-26` `Stage = Literal["zk", "gk", "cet4", "cet6"]`、`StageIndex = Literal[1, 2, 3, 4]`。实际运行（只读）：`cd backend && ../.venv/bin/python ../scripts/check_contract.py` → `contract OK: no property-name or literal-union mismatch`。置信度高。

**[frontend-stages-9]** 结论：**确认**（位置为事实、行数为推断，原文已标注）。各文件:行核对无误：`types.ts:5-6,45`；`StageChips.tsx:1,7-9`；`zh.ts:25,28-29,86`；`docs/FRONTEND.md:231-235,292`（镜像块中 `welcome`/`stages` 在 231-235、`sources` 在 292，确认）；`WelcomePage.tsx:1-3,30,33-40,42`；`ScreenPage.tsx:20`；`VocabPage.tsx:1,29,202,232`；`AdminPage.tsx:36`。补充：`PREWARM_STAGES` 的类型 `PrewarmStage = Stage | 'all'`（`endpoints.ts:328`）会随 `Stage` 扩展，改成 `[...STAGE_ORDER, 'all']` 可直接通过类型检查。置信度高。

**[frontend-stages-10]** 结论：**确认**。`SettingsPage.tsx:303` `STAGE_ORDER.map`、`:315` `STAGE_ORDER.filter`；`ScreenRunPage.tsx:34` `isStage(stageParam)`；`routes.tsx:38-39` `screen: '/screen'`、`screenRun: (stage: string) => …`，`:83-84` 两条 `<Route>`；`frontend/src/hooks/useLocalPref.ts:38` 存在；`VocabPage.tsx:70` 读回经 `isStage`；`ScreenPage.tsx:30` `readPref(SCREEN_STAGE_KEY)` 只用于高亮 `last === info.stage`，旧值无需迁移。置信度高。

**[frontend-stages-11]** 结论：**修正（清单不全）**。
- 已列项全部确认：`docs/API.md:155,160,167`（「4 rows」）、`:169`（`stage=all|zk|gk|cet4|cet6`、3,694）、`:187,230,239-240,279,460`；`docs/FRONTEND.md:50,54-56,89,147`；`docs/DESIGN.md:32,40`（"four stage tabs"）、`:72,330`；`docs/qa-frontend.md:36,42,84`。
- 遗漏（会被同一 grep 命中、且面向用户/许可）：`README.md:3`「内置初中、高中、大学英语四级、六级的全部词汇」、`:9`「初中 / 高中 / 四级 / 六级全部词汇（9,162 词）」、`:103`「按阶段累计：初中 2,099 · 高中 3,829 · 四级 4,722 · 六级 7,671」；`ATTRIBUTION.md:21`（阶段归属说明）、`:25-30`（逐阶段来源文件表：`中考英语词汇表.txt` → zk 等）——新增小学词表必须在此登记来源与许可。另有后端测试直接钉住四阶段中文名：`backend/tests/integration/test_vocab.py:70` `assert [i["name_zh"] …] == ["初中", "高中", "四级", "六级"]`、`backend/tests/unit/test_api_schemas.py:39`。证据：`grep -rn '六级\|四级\|初中\|高中' --include='*.md' --include='*.py' . | grep -v '^./docs/\|^./frontend/src/'`。置信度高。

**[frontend-stages-12]** 结论：**修正（方案 A 的成本被低估，前提不成立）**。
- 已确认：`backend/wd/migrations/0001_init.sql:148` `CHECK (current_stage BETWEEN 1 AND 4)`、`:185` `CHECK (stage_min BETWEEN 1 AND 4)`；后续迁移（`ls backend/wd/migrations/` → 0001、0008、0009、0010）均未触碰这两列（`grep -n 'current_stage\|stage_min' backend/wd/migrations/*.sql` 只命中 0001）；`docs/DESIGN.md:347-350` 与实现 `backend/wd/services/batches.py:60`、`services/screen.py:34-36` 的 `CASE WHEN w.stage_min = :cur THEN 0 WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END` 一致，是纯数值距离；12 处夹具 / 10 个文件重算一致（`grep -rn 'stage_min: [0-9]' frontend/src --include='*.test.*' | wc -l` = 12）；`StageChips.tsx:31` `stageMin === STAGE_INDEX[stage]`。
- 需修正：原文把「方案 A 小学 = 0，其余不动」描述为只改前端 [9] 所列、更省事。但后端索引不是查表而是**由位置推导**：`backend/wd/schemas.py:56-61` `stage_to_index` = `STAGE_ORDER.index(stage) + 1`，`:64-67` `index_to_stage` 断言 `1 <= index <= 4`。把小学插到 `STAGE_ORDER` 首位，后端自动得到小学=1、zk=2…（即方案 B）；要得到「小学 = 0」必须改写这两个函数、`words.stage_min` 与 `user_settings.current_stage` 的 CHECK（SQLite 不能 ALTER CHECK，需重建两张表），以及 `stage_distance` 的 0 值并不冲突但 `DEFAULT 3` 等默认值语义全变。因此两案在后端成本上 A ≥ B，「前端两案成本差 12 处夹具」只是前端口径。正确说法：方案 B（重编号 1..5）是现有代码的自然结果，方案 A 需要额外重写索引推导与两处 CHECK。置信度高（事实）。

**[frontend-stages-13]** 结论：**确认（并补强）**。`ScreenPage.tsx:31` `STAGE_ORDER.map(…find…).filter(…)` 确实双向静默；`backend/wd/schemas.py:488` `stage: Literal["all", "zk", "gk", "cet4", "cet6"] = "all"`；422→400 映射在 `backend/wd/errors.py:8,28,69`（`"validation_error": (400, "请求参数无效")`），`docs/TASKS.md:38` 原文含「incl. 422 → 400 `validation_error`」；`VocabPage.tsx:263-270` 错误条。补强：筛词跑页也会 400——`backend/wd/services/screen.py:46-47` `if stage not in words.STAGES: raise ApiError("validation_error", …)`；更危险的是 `backend/wd/services/bank.py:181` `base["stages"] = [s for s in stages if s in words.STAGES] or list(DEFAULT_STAGES)`：若 `stages_json` 里出现后端尚不认识的阶段，用户目标阶段会被**静默过滤、全部未知时回落到 cet4/cet6**。「后端先上」的结论成立且更重要。置信度高。

**[frontend-stages-14]** 结论：**确认**（建议部分为产品决策，原文已标）。
- `WelcomePage.tsx:33-38` 预设、`:72-73` 初值 `settings?.stages.length ? settings.stages : ROLE_PRESETS.pro.stages` 确认；`0001_init.sql:147-148` 默认 `'["cet4","cet6"]'`/`3`；注册只插 `INSERT INTO user_settings(user_id, next_push_at, updated_at)`（`backend/wd/security.py:662`），其余列吃 SQL 默认；`AuthContext.tsx:70` 从 `/api/auth/me` 取 `settings`，所以 pending 用户在欢迎页确实拿到 cet4/cet6。`docs/DESIGN.md:330` 也写明注册即插 settings 行。线上副本：`sqlite3 -readonly live-copy.db "SELECT stages_json,current_stage,COUNT(*) FROM user_settings GROUP BY 1,2"` → `["zk","gk","cet4","cet6"]|3|1`、`["zk"]|1|1`，一致。
- 宽度算术：`WelcomePage.css:45-49` + `bank.css:147` 有 1px 边框，原文漏算边框：3×(48+32+2)+(64+32+2)+3×8 = **368px**（原文 360），结论「现在已折两行」不变（> 343）。
- 补充：同一默认值在 `backend/wd/services/bank.py:85-86` `DEFAULT_STAGES = ("cet4", "cet6")`、`DEFAULT_CURRENT_STAGE = 3` 又写了一遍（`:172`、`:181` 使用），改 K12 默认要同时改 SQL 默认与这里。置信度高。

**[frontend-stages-15]** 结论：**修正（「常态」说法被数据推翻；宽度算术前提确认）**。
- CSS 前提确认：`word.css:77-84` `.chips { inline-flex; gap 4px; flex-wrap: wrap }`，`:86-98` `.chip { padding: 1px 8px; border: 1px; font-size: var(--text-xs) }`，`:100-103` `.chips--md .chip { padding: 2px 10px; font-size: var(--text-sm) }`；`list.css:97-103` `.word-row__chips { gap 8px; flex-wrap }`；`word.css:58-65` `.word-head__meta`，`:67-69` `.word-head--lg .word-head__meta { font-size: var(--text-md) }`（lg 音标 16px 的假设成立）。算术（sm「小学」42px、md 50px）按假设可复现；StateBadge/音标的像素宽未渲染量测，维持「推断」。
- 需修正：「小学词通常同时带 zk/gk/cet4/cet6（累计标注），5 个 chip 全满在小学词上是常态而非例外」。线上副本 `sqlite3 -readonly live-copy.db "SELECT (stage_zk+stage_gk+stage_cet4+stage_cet6) n, COUNT(*) FROM words WHERE stage_zk=1 GROUP BY 1"` → `1|33  2|94  3|1118  4|854`：2,099 个初中词里只有 **854（854/2099 = 40.7%）** 带满四个标签，94% 带 ≥3 个。而且标注并非严格累计：`SELECT SUM(stage_zk=1 AND stage_gk=0), SUM(stage_gk=1 AND stage_cet4=0), SUM(stage_cet4=1 AND stage_cet6=0) FROM words` → `62|706|1186`。正确说法：若小学表 ⊆ 初中表，加小学后「5 个全满」最多占小学词的四成左右，「4 个以上」约九成；换行风险真实但不是「常态」。置信度高（数据）。

**[frontend-stages-16]** 结论：**确认**（推断，前提全部核实，未量测）。`ui.css:440-447` `.tabs { gap: var(--space-1); overflow-x: auto; scrollbar-width: none }`，`:453-455` `.tabs--fill .tab { flex: 1 1 0 }`，`:457-473` `.tab { min-height: var(--tap); padding: 0 var(--space-3); white-space: nowrap }` 无 `font-size`；字号继承成立的前提是 `global.css:70-74` `button, select, textarea { font: inherit }`（原文未引，但确实存在）→ 16px；`tokens.css:46-53` `--space-1: 4px; --space-3: 12px; --tap: 44px; --gutter: 16px`；`global.css:145-150` `.page { padding-inline: var(--gutter) }`；`VocabPage.tsx:213` `<Tabs … fill …>`；先例 `BankPage.tsx:316` `<Tabs aria-label={zh.bank.title} items=…>` 无 `fill`，`:33` `TABS` 6 项。算术：6×(2×16+24)+5×4 = 356 > 375−32 = 343，溢出 13px；390px 下 358 ≥ 356 放得下。`FRONTEND.md:176` 原句「no horizontal scroll at 360 px」确认。置信度中（算术可复现，渲染未测）。

**[frontend-stages-17]** 结论：**确认**。`SettingsPage.tsx:73-74,76`、`WelcomePage.tsx:47,49` 同逻辑；`docs/API.md:160` 原句「`stages` non-empty ⊆ {zk,gk,cet4,cet6} and `current_stage ∈ stages`」；`schemas.py:77-79` `_unique_stages` 空则 `ValueError`，`:360-364`、`:425-429` 两个 `model_validator`；`SettingsPage.test.tsx:216-222` 四例原文一致。宽度：`SettingsPage.css:93-97` `.settings__stages { flex-wrap; gap 8px }`，`bank.css:144-152` `.chip-btn { min-height 32px; padding 0 12px; border 1px; font-size sm }` → 「小学」= 28+24+2 = 54px（原文 52 漏边框），5×54+4×8 = 302 ≤ 343 仍一行放下；`ui.css:502-510` `.segmented { gap: 2px; padding: 3px }`，`:542-545` `--sm` 14px → 5×52+8+6 = 274，结论不变。置信度高。

**[frontend-stages-18]** 结论：**确认**。`types.ts:46` 注释原文；`backend/wd/routers/vocab.py:52-56`（原文写 51-54，差 1 行，引用片段正确）`where.append(f"w.stage_{q.stage} = 1") … where.append("w.stage_min = :stage_idx")`；`0001_init.sql:185-186`；`VocabPage.tsx:85` `...(effectiveNewOnly ? { new_only: true } : {})`；`client.test.ts:56` `'/api/vocab?stage=cet6&new_only=1&page=2'`。置信度高。

**[frontend-stages-19]** 结论：**确认（全部重算）**。`sqlite3 -readonly live-copy.db`：`stage_zk=1 AND is_public=1 AND merged_into_word_id IS NULL` = 2099；`stage_min=1`（同过滤）= 2099；`stage_zk=1 AND (stage_min<>1 OR stage_min IS NULL)` = 0；gk 3829 vs `stage_min=2` 1792；cet4 4722 vs `stage_min=3` 1577；cet6 7671 vs `stage_min=4` 3694；不加过滤的原始计数相同（`SUM(stage_zk)…COUNT(*)` = `2099|3829|4722|7671|9162`）。`VocabPage.tsx:232` `{tab !== 'all' && <Switch …>}`、`:202` 三元只认 cet6；`docs/qa-frontend.md:42` 只核六级。置信度高。

**[frontend-stages-20]** 结论：**确认（并补证据）**。推导成立；「小学 ∩ 初中 无法计算」属实（库中无小学列）。补充：`docs/DESIGN.md:186`「cumulative as in the sources」在线上数据里已不严格成立（见 [15]：62 个初中词不在高中表、706 个高中词不在四级表、1186 个四级词不在六级表），所以「小学表含不在初中表的词」不是假想风险而是沿用现有来源时的既有模式，支持原文让 `初中生` 预设包含小学的理由。置信度高。

**[frontend-stages-21]** 结论：**确认**。`grep -rn -i 'region\|上海\|全国' frontend/src` 无输出；`types.ts:34-43` `Settings` 无地区字段。置信度高。

**[frontend-stages-22]** 结论：**确认**（设计建议，推断）。引用位置核对：`SettingsPage.tsx:408-446` `LearnSection`，口音块 `:431-443` `Segmented size="sm" … save({ accent: v })`；`WelcomePage.tsx:243-254` 目标阶段组、`:116` `endpoints.saveOnboarding({ stages, current_stage: current, timezone, push_time: pushTime })`；`endpoints.ts:99-104` `OnboardingBody`。「服务端按用户设置解析」的论证与 `_stage_scope`（`services/screen.py:40-48`）按用户设置解析 `auto` 的现有模式一致。置信度中（建议）。

**[frontend-stages-23]** 结论：**确认**。`endpoints.ts:397` `saveOnboarding`、`:408` `updateSettings`、`:421` `getStages`、`:423` `getVocab`、`:425` `getVocabLetters`、`:445-446` `getScreenNext(stage: ScreenStage, …)`、`:497` `getStats`、`:535` `adminPrewarm`；`AuthContext.tsx:142-146` `updateSettings`。置信度高。

**[frontend-stages-24]** 结论：**确认**。`zh.test.ts:67-83`、`zh.contract.test.ts:67-73,75-83`（见 [7]）。置信度高。

**[frontend-stages-25]** 结论：**确认**。`Makefile:80-81` 顺序；`frontend/tsconfig.json:10` `"strict": true`、`:30` `"include": ["src"]`（覆盖测试）；`frontend/vite.config.ts:39-46` `test` 块无 `typecheck`；`Record<Stage,…>` 缺键与 `zh.stages[s]`（`s: Stage`）索引缺键在 strict 下均为 tsc 错误（TS2741 / TS7053）；引用点 `VocabPage.tsx:213`、`SettingsPage.tsx:305,315`、`ScreenPage.tsx:54,57`、`ScreenRunPage.tsx:35`、`AdminPage.tsx:845` 全部存在。置信度高。

**[frontend-stages-26]** 结论：**确认**。`SettingsPage.test.tsx:218-221`；`SpeakButton.test.tsx:91` `stages: ['cet6', 'gk', 'cet4'], stage_min: 2, cet6_star: true`、`:100` 断言 chips 文本顺序为 `zh.stages.gk`, `zh.stages.cet4`, `zh.stages.cet6` + ★、`:102` `getByRole('img', { name: zh.stages.star })`；`endpoints.test.ts:24,46,51`；`client.test.ts:54-56,147`；`ScreenRunPage.test.tsx:51` `'/screen/cet4'`；`WelcomePage.test.tsx:63-64` `stages: ['cet4'], current_stage: 'cet4'`；`AuthContext.test.tsx:18-19`。置信度高。

**[frontend-stages-27]** 结论：**确认**。`ls frontend/src/pages/ScreenPage.test.tsx` → 不存在；`VocabPage.test.tsx` 的 `describe` 为 `filter controls`(:15)、`optimisticState`(:35)、`markToast / markUndoable`(:49)，无 tab 断言；`WelcomePage.test.tsx` 共 146 行，唯一 `describe('WelcomePage step 2')` 在 :100。置信度高。

**范围与方法一节的计数错误**（非编号结论，顺带修正）：原文「51 个 `*.test.*` 文件」有误。`find frontend/src -name '*.test.*' | wc -l` = **39**（`frontend/` 下无 `e2e/` 目录，`find frontend -name '*.test.*' -not -path '*/node_modules/*'` 亦为 39）；其中含 `cet6` 的 `grep -rl cet6 frontend/src --include='*.test.*' | wc -l` = 18。

---

## 作者遗漏的重要事实

1. **后端索引由位置推导，决定了「小学 = 0」不可行（改变 [12] 的决策方向）。** `backend/wd/schemas.py:56-61` `return STAGE_ORDER.index(stage) + 1`；`:64-67` `if not 1 <= int(index) <= 4: raise ValueError`。CHECK 约束 `0001_init.sql:148,185` 自 0001 之后无迁移改动（`backend/wd/migrations/` 只有 0001/0008/0009/0010），SQLite 改 CHECK 需重建表。结论：重编号 1..5 是默认路径，前端应直接按方案 B 预算（12 处夹具）。事实，置信度高。
2. **后端还有 8 处与 `Stage` 同构的硬编码，必须与前端同一提交联动；其中两处有静默失败风险。** `backend/wd/seed.py:43` `STAGES`；`backend/wd/ai/prewarm.py:32-33` `STAGE_COLUMNS`/`STAGES`；`backend/wd/ai/content.py:49` `STAGE_ZH`（`:88` 写进 AI 提示词）；`backend/wd/services/ecdict.py:28` `STAGE_TAGS`；`backend/wd/services/words.py:39` `STAGES`、`:578-581` 新词默认列、`:591-594` INSERT 列清单；`backend/wd/services/bank.py:85-86` `DEFAULT_STAGES`/`DEFAULT_CURRENT_STAGE`、`:181` **未知阶段被静默丢弃并回落到 cet4/cet6**；`backend/wd/services/screen.py:46-47` 未知阶段 400；`backend/wd/security.py:613` `stages_json()` 文档串。事实，置信度高。
3. **许可/署名文件与 README 未列入文档改动清单。** `ATTRIBUTION.md:21,25-30` 逐阶段登记来源文件（`中考英语词汇表.txt` → zk …）与「只使用词是否出现在表中这一事实」的许可说明；新增小学词表（上海牛津/沪教版等）需同样登记并核许可。`README.md:3,9,103` 三处面向用户的四阶段与计数文案。事实，置信度高。
4. **阶段标注并非严格累计，且初中词只有四成带满标签。** `SELECT SUM(stage_zk=1 AND stage_gk=0), SUM(stage_gk=1 AND stage_cet4=0), SUM(stage_cet4=1 AND stage_cet6=0) FROM words` → `62|706|1186`；初中词标签数分布 `1|33 2|94 3|1118 4|854`。直接影响 [15] 的换行判断与 [20] 的「初中生预设漏词」论证（漏词模式已存在于现有来源之间）。事实，置信度高。
5. **中文阶段名的第二个消费者是 AI 提示词。** `backend/wd/ai/content.py:88` `"stages": [STAGE_ZH[s] for s in words.stages_of(word)]`——新增「小学」后生成的例句/配图提示词会带「小学」受众标签，这与需求 (4)「配图更有助记忆」直接相关（可按年龄段调提示词），原文 [3] 只说「用户看不到」。事实，置信度高。
6. **页宽算术的隐含前提。** 原文的 16px tab 字号依赖 `frontend/src/styles/global.css:70-74` `button, select, textarea { font: inherit; color: inherit; }`（未引用）；`.chip-btn` 有 1px 边框（`bank.css:147`），[14]/[17] 的像素数应各加 2px/个（结论不变）。事实，置信度高。
7. **后端测试也钉住四阶段。** `backend/tests/integration/test_vocab.py:70`、`backend/tests/unit/test_api_schemas.py:39`、`backend/tests/unit/test_runner.py:27` 等；`make test` 第一步 pytest 会先于前端门禁失败。事实，置信度高。

## 未解决的问题

1. 所有像素宽度（[14]-[17]）仍是按「CJK 1em、根字号 16px、PingFang SC」算的，未在 375/360px 真机或 DevTools 量测；StateBadge「学习中 · 3 天后」≈112px 之类的估值无法在不渲染的情况下核验。
2. `docs/qa-frontend.md:70` 被原文列为阶段相关人工用例，该行是「推送设置」段落（行被截断，未逐字确认是否包含阶段 chips 条目）。
3. 本文件未评估上海小学词表本身（来源、许可、与初中表的交集），那是其他 facts 文件的范围。

---

核验 27 条：确认 23、修正 4、推翻 0、无法核验 0。
