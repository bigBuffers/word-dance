# 发布说明 · 2026-11 · 单词之舞 P1（拼写舞 + 重音舞，迁移 0015）

基线 `main @ d9d5033`（学习顺序发布已部署，schema 14）；本次发布 = 「单词之舞」第一期：学习卡与详情页的词头会按音节入场、按节拍跳动，设置里多一个开关。
设计契约是 `docs/WORD_DANCE_DESIGN.md`（§4.1、§4.2、§6；2026-11-08 的决定见其 §10），前端契约 `docs/FRONTEND.md` §4 / §5.1.1 / §6.5，接口契约 `docs/API.md` 15 / §9 `DanceSpec` / `Settings.dance_mode` / §9.1。
迁移文件：`0015_dance_mode.sql`（`user_settings` 一条 `ADD COLUMN dance_mode TEXT NOT NULL DEFAULT 'full' CHECK (…)`，纯附加：不重建表、无索引）。后端**只需重启**；没有新依赖、不花 AI 预算、不动词库与图卡。

---

## 1 变更概览

| 面向 | 变化 |
|---|---|
| 学习者 | 新词卡（和复习次数 < 3 的复习 / 加练卡）出现时，词头的字母按**音节**依次入场（双写字母一起跳，不发音字母变浅、不参与节拍），然后全词按音节打拍子，**重读音节跳得最高、变色**；词下方多一行音节芯片（`rab · bit`，重读的那块填色）；点 🔊 或按 `P` 再跳一次并朗读；翻面不重跳；推荐词（筛词卡）不跳。设置 → 学习设置多一个开关「单词之舞」（默认开）。系统「减弱动态效果」下不动，只保留重读音节的静态着色 |
| 数据 | `user_settings.dance_mode`（`full` / `form_only` / `off`，默认 `full`；P1 对 `form_only` 与 `full` 一视同仁）。舞步数据**不落库**：`backend/wd/dance.py` 在序列化 `StudyItem.word` / `WordDetail.word` 时从 `display` + `phonetic` 现算 `dance`（`DanceSpec`），词组、缩写、无音标的词为 `null` |
| 接口 | `Settings.dance_mode`（GET/PUT 15 多一个字段，校验 `∈ {full, form_only, off}`）；`StudyItem.word.dance`、`WordDetail.word.dance`；新类型 `DanceSpec` / `DanceMode`（`schemas.py` ↔ `types.ts` ↔ API.md §9 一次契约变更） |
| 不变 | 复习算法、批次、词库、配图、AI 任务、预算；筛词卡与词库列表的词头；`docs/SCHEMA.sql`（0001 基线） |

**给产品负责人的两句话。** 这是设计稿里的 P1：不依赖 AI、$0，先让孩子看到「拼写舞 + 重音舞」，四周后按词的奇偶 A/B（见设计 §7）再决定做不做语义舞。规则从词库现成的 ECDICT 音标算音节和重音，600 个小学词里 586 个能切开、6 个按单音节处理（hour、fire、our、tired、TV、OK）、8 个词组 / 缩写没有舞步；全部 600 个切法经 6 个评审代理按词典音节划分逐词核对、30 条确认问题全部修进规则（设计稿 §10）。

## 2 机制

- **音节与重音（后端规则，`backend/wd/dance.py`）**：音标里的元音核（含双元音；三元音按拼写决定并成一拍还是两拍；iə / uə 在拼写为 i / u + 另一个元音字母时读成两拍：se·ri·ous、Jan·u·a·ry）加上音节辅音（`'æpl`、`'sevn`、`'fainl`、`'stjuːdnt`）= 音节数，音标少写一个 ə 时按拼写补回（in·ter·est·ing）；撇号 / `ˈ` 之前的元音核数 = 重读下标（ECDICT 的双撇号旧记法取最后一个：'fif'tiːn → fif·TEEN；13–19 数词一律重读 -teen；无标记的多音节词重读第一个非 ə 音节；`.` `,` `ˌ` 是次重音，只影响开闭音节）。拼写按元音字母组切块：重读短元音后的单个辅音归前一块（vis·it、sev·en），长元音 / ə / 非重读元音后的归后一块（pa·per、a·bout、be·gin），r 控制元音与非重读 er 带着 r（or·ange、dif·fer·ent），辅音二合字母与 tch 不拆（tea·cher、moth·er、kitch·en），ck / ng 收尾，双写辅音与 s 簇从中间切（rab·bit、bas·ket），流音簇在开音节后不切（ta·ble），拼 /ʃ/ 的 ti / ci / si 归后缀（na·tion·al、spe·cial），-le / -ing / -ieth 词尾与 magic e 特殊处理（ta·ble、meet·ing、twen·ti·eth、cre·ate）；august（月份）与 email 两个词的音标按词覆盖。拼写与音标仍对不上时整词一块（原封不动地退化），词组 / 缩写 / 连字符 / 无音标为 `null`。全部规则由 `tests/unit/test_dance.py` 的 101 条金表（100 词，abandon 的两种音标记法各一条） + 全种子不变量测试钉住。
- **动画（前端，`components/word/dances.ts` + `DancingWord.tsx`）**：纯函数生成关键帧，Web Animations API 播放，只动 `transform` / `opacity` / `color`；字母 85 ms 一个（8 个及以上字母 55 ms），音节边界多停 150 ms（长词 120 ms）；每拍 300 ms（重读那拍 330 ms）；双写字母最后一起跳一下；小学词全部 ≤ 2.5 s（测试钉住最长的 January / February / tomorrow / umbrella）。卡片正面挂载时按 `danceAutoplay` 在布局阶段先于首帧播放（新词与 `repetitions < 3` 的复习 / 加练卡；推荐词不给舞步），`StudyPage` 的 `danceToken` 只为按 `P` 服务，`WordHeader` 的 🔊 另加（没有语音合成时按钮仍可用，标签改为「再跳一次」）；翻面重挂载不重放。jsdom 没有 `element.animate`、或系统减弱动态时直接静态（重读音节着色）。
- **设置**：`PUT /api/settings {dance_mode}`，`SCALAR_COLUMNS` 多一列；`settings_row_to_dto` 对没有该列的旧行回退 `full`。

## 3 验收（提交前门禁）

- `make test`：pytest（新增 `test_dance.py`、`test_db_0015.py`，更新 `test_api_schemas` / `test_settings` / `test_words_resolve`）、`scripts/check_contract.py`、`tsc`、vitest（新增 `dances.test.ts`、`DancingWord.test.tsx`、`WordHeader.test.tsx`，`StudyCard` / `SettingsPage` 各加一组）、`vite build`；`npm run lint`（文案只在 `zh.ts`，FRONTEND §8 镜像由 `zh.contract.test.ts` 钉住）。
- 手测清单 `docs/qa-study.md` §7。

## 4 上线步骤（Mac launchd；只需重启）

0. 本机测试全绿（上一节）。
1. `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build -- --outDir $D/frontend-releases/<sha>.new --emptyOutDir`（`D=/Users/sqin/word-dance-data`），`mv <sha>.new <sha>`，`ln -sfn frontend-releases/<sha> $D/frontend.tmp`，`python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"`。
2. `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`：`wd serve` 启动时自动套用 0015（先写 `backups/pre-migrate-14-to-15.db.gz`），约 3 s 内健康。
3. 验证：`curl -s --noproxy '*' http://127.0.0.1:8000/api/health`；浏览器登录后 设置 → 学习设置 看到「单词之舞」；打开今日学习，新词卡词头跳动、下方有音节芯片；日志里 `applied migration 0015_dance_mode`。
4. 不需要 `wd learn-order`、不需要导种子、不需要 AI。

## 5 回滚

`git checkout <上一版>`，按第 4 节第 1、2 步重新构建前端并重启即可：旧代码不读 `dance_mode`，列与默认值留在库里无害；需要连库一起回退时用 `backups/pre-migrate-14-to-15.db.gz`（`wd restore`）。

## 6 未决（不阻塞）

- 规则层对少数词的切法与词典不同但可辩护（tea·cher、eve·ry、vege·ta·ble、diffe·rent；词典 teach·er、ev·ery、veg·e·ta·ble、dif·fer·ent）；两轮评审挑出并修正的问题、驳回的策略性意见和留给 P2 的事项见 `docs/WORD_DANCE_DESIGN.md` §10。
- 发音与动作并行不同步（Web Speech 无音素时间）；Android WebView 无语音时只有动作。
- 语义舞（P2）、线索复习（P3）、手势（P4）按设计稿分期，等 4 周 A/B 数据。
