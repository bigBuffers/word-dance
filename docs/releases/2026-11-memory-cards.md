# 发布说明 · 2026-11 · 记忆图卡（新一代图片：场景 + 画进图里的单词；设置开关「图片上显示单词」；迁移 0021，加列不停机）

> **2026-11-14 已上线**：按用户「apply the already generated picture」的要求，`main` 快进到 `2bcbf60`，发布前端快照 `frontend-releases/2bcbf60`，完成迁移 0021，导入 **66 张**（原 10 张样例 + 首批 100 词中实际保存的 56 张）。首批仍缺 44 张，不能把 Claude 的工作流“completed”当作全部画完或质检完成。下文是 11-13 的原始发布计划；当前结果以本段和文末上线记录为准。

基线 `main @ ea77832`（磨耳朵已上线，schema 20）；本次发布 = 让线上系统认识「记忆图卡」：一张图分两层（没有任何文字的场景层 + 把单词画进画面的单词层），能带着单词取、也能不带单词取，图自带的记忆钩子显示在「记忆」一栏，设置里多一个开关，图用一条命令从离线的 `studio/` 导入，也能用一条命令撤回。
你的话（11-13）：「按照你的建议，重画范围先 100，单词默认显示还是隐藏，可以做个开关，默认还是显示，人物名字沿用」。对应到这次：**开关**做了，默认显示（`image_word` 默认 1）；**人物**朵朵、乐乐、奶奶、团子的设定收进了 `studio/cast/CAST.md`，名字不变；**先 100**——这次随代码进仓库、可以导入的是你确认过的 **10 张样例**，前 100 个小学词的图**还没有进来**（批量画法 11-13 已经试验选定：和样例同一个模型、每张最多看两次渲染图，第 6 节第 1 条；那 100 张正在工作区的 `studio/tmp/` 里做），画完、评审完、你看过总览页之后用同一条导入命令进来，那一步只是数据，不用再发版。
设计契约是 `docs/MEMORY_CARDS_DESIGN.md`（§3 规格；实现时补的细节回写在 §8，审查之后改了行为的地方在 §8.1）。接口契约 `docs/API.md` 15（`PUT /api/settings` 接受 `image_word`）/ 28（记忆图卡上的「不合适」只记录）/ 29（换一张不换记忆图卡）/ 52（`GET /media/images/{path}?plain=1`）/ 69 / 71（管理员处理反馈时的「换图」）/ 77 / §9 `Settings.image_word`、`ImageMeta.word_layer` / `hook_zh` / `note_zh` / §9.1；前端契约 `docs/FRONTEND.md` §2 / §4 / §5.1.2 / §5.8 / §7 / §8；架构 `docs/DESIGN.md` §0.3 / §6.1 / §9；运维 `docs/DEPLOY.md` §5 / §9 / §10、`docs/ops.md` §4 和故障表；手测清单 `docs/qa-study.md` §9；许可 `ATTRIBUTION.md` §3.4 / §3.5 和站内的「开源许可与数据来源」页。没有新接口（目录仍是 1–123）。
**迁移 `0021_memory_cards.sql`**：三条 `ADD COLUMN`（`user_settings.image_word` 默认 1，`word_images.hook_zh` / `note_zh` 可空），不重建任何表、没有数据步骤——**重启即生效**，服务启动时先写 `backups/pre-migrate-20-to-21.db.gz` 再套用。后端**要重启**，前端**要出新快照**；`.env` 不用改；App 本身没有新依赖（`studio/` 的工具有自己的小虚拟环境，和服务无关）；不花 AI 预算；平板和手机上的 App 不用重装。
状态：**未提交、未部署**（2026-11-13）。代码在工作区 `/Users/sqin/word-dance/.claude/worktrees/memory-cards`（分支 `memory-cards`，和 `main` 同在 `ea77832`，改动都还没提交）。实现之后做了一轮代码审查，28 条发现逐条复核、全部处理（第 3 节末尾「审查与修复」；行为上的变化写在设计稿 §8.1），门禁在那之后整套重跑，全绿（第 3 节）。**上线和导入图片各等你一句话**（设计稿抬头：部署和导入图片前再问 sqin）。

---

## 1 变更概览

| 面向 | 变化 |
|---|---|
| 学习者 | 导入了记忆图卡的词：学习卡背面和单词详情页的配图换成新图。「记忆」一栏显示**图的钩子**（如 moon：「两个 o 像两轮圆月：天上一个，水里一个，oo 读长音 /uː/。」），下面一行小一号、较淡的字是读音 / 词义提醒（没有提醒的图只有一行）；内容里旧的联想句这时不显示（两者常常对不上，旧的里还有谐音）。图下面只有「不合适」，**没有「换一张」**；点「不合适」只是把这条反馈记下来交给管理员（提示「已收到反馈，谢谢」），图不会当场被换掉；图片说明仍是「AI 生成示意图」。设置 → 学习设置里「显示配图」下面多一个开关 **「图片上显示单词」**，默认开，小字说明「关掉后，带单词的配图只显示画面」；关掉后同一张图不带单词层，学习卡、详情页、历史批次回放里都一样。没有导入图卡的词（照片、旧的示意图、系统卡片）一切照旧，开关对它们没有任何影响。顺带的一处观感变化：设置页所有带开关的行（每日推送、邮件推送、Webhook 推送、显示配图、图片上显示单词、自动发音），开关现在都靠右对齐，点这一行的空白处也能切换 |
| 数据 | 迁移 0021 加三列（上面）。图卡是**数据**不是代码：每张是 `word_images` 的一行（`provider = 'claude_svg'`，`prompt_version = 'memo-1'`，`text_free = 1`——字母是路径，没有 `<text>`；`hook_zh` / `note_zh` / `alt_zh` 三句话）加 `images/` 里的一个 SVG 文件（10 张样例存盘后 27–44 KB，一共 379 KB；现在的小学示意图平均 1.8 KB）。被替换的旧图标成 `superseded`，行和文件都留着 |
| 接口 | `Settings.image_word`（布尔，接口 14 / 15 / `auth/me`）；`ImageMeta` 多三个字段，所有带图的接口都有：`word_layer`（真 = 这是记忆图卡，`url + '?plain=1'` 是不带单词的同一张图）、`hook_zh`、`note_zh`（照片、旧图、模板卡、体验区一律 `false` / `null` / `null`）；52 多一个参数 `?plain=1`；29「换一张」遇到记忆图卡照样答 202，但任务什么都不搜、以 `{"skipped": "memory_card"}` 结束，图卡留着；28「不合适」遇到记忆图卡照样答 `201 {id}`，但只记下这条反馈，图卡不下线、不排取图；71 管理员处理反馈时的「换图」才把图卡撤下（照片和旧图上这两个接口不变）；69 管理端换图的任务带 `requested: true`，是唯一会替换记忆图卡的自动取图。`schemas.py` ↔ `types.ts` ↔ API.md §9 一次契约变更 |
| 运维 | 新命令 `wd images-import DIR --manifest FILE [--dry-run] [--only LEMMA …]`（导入）和 `wd images-import --undo FILE [--dry-run] [--only LEMMA …]`（撤回），登记在 `wd.images.handler` 那一组；导入逐词给出 `imported` / `unchanged` / `rejected`，另有两种少见的结果——`retired`（管理员撤下过的图卡，不自动换回）和 `unchanged … (file restored)`（图没变、丢了的文件补回）；`docs/ops.md` §4 有导入 / 撤回的操作步骤；`scripts/smoke.py` 多一步记忆图卡；`scripts/rehearse_migration.py` 多一组 0021 的检查；`make studio-check` 跑 `studio/` 工具的自测（不属于 `make test`） |
| `studio/` | 做图的手册、画风、批量试画时评审的教训（`LESSONS.md`）、人物设定、三个工具（字形 `letters`、校验 + 渲染 `check`、总览页 `build_gallery`）、字体 Andika Bold 和它的许可全文、10 张定稿的图、清单 `manifest.json`，从会话的临时目录收进仓库：38 个文件约 1.7 MB（字体 681 KB，10 张图 379 KB；其中 `studio/cast/family/` 的 10 个文件 355 KB 是 11-13 下午新增的大人角色设定——爸爸、妈妈、爷爷、李老师、路人）。渲染图、清洗后的副本、`studio/.venv/`、`studio/tmp/` 不进 git。没收进来的东西在 `/Users/sqin/word-dance-memory-cards/studio-20261112.tgz`（54.5 MB，在仓库之外，请和别的备份一起保存）；清单见 `studio/README.md` §9 |
| 许可 | 图里单词的字母是开源识字字体 Andika（SIL Open Font License 1.1）的字形轮廓转成的路径：站内「开源许可与数据来源」页新增第 4 节，`ATTRIBUTION.md` 新增 §3.5。站点不分发字体文件，设备上也不用装 |
| 不变 | 线上的自动生成（`generate_svg`）和它的清洗规则——`sanitize_svg.clean` 不带新参数时输出逐字节不变，现有测试原样通过；照片的取图链；内容里的联想句（只是有图钩子时不显示，没有改写）；学习记录、复习间隔；`.env`；APK |

**给你的几句话。** 这次改的是「系统会不会用这种图」，不是「图有没有画完」。上线之后、导入之前，线上看起来和现在完全一样，只是设置里多了一个暂时没有东西可关的开关；导入 10 张样例之后，这 10 个词（moon、breakfast、rain、grandma、autumn、happy、swim、sleep、share、yesterday）换成新图，其余 590 个小学词还是现在的图。门禁、端到端冒烟、对着仓库种子的整套导入 / 取图 / 撤回都跑过了，两种取法的渲染图我逐张看过（第 3 节）；**没有在任何真机上看过**——平板上图清不清楚、翻面卡不卡（每张图有 4–7 个带模糊的图层），要你上线后按 `docs/qa-study.md` §9 走一遍。线上数据这一轮没有读、也没有改。

## 2 机制

- **什么算记忆图卡（`backend/wd/images/memo.py`）**：`word_images` 的一行，`provider = 'claude_svg'` 且 `prompt_version` 以 `memo-` 开头（这一代是 `memo-1`）。不加新的提供方、不加新列来标记它，所以对所有老的读取方它就是一张普通的 AI 示意图（说明文字、`photo_mix` 的统计都不用改）。
- **清洗（`sanitize_svg.clean(…, effects=True)`）**：只有导入这一条路带这个参数。多放行四个元素（`filter`、`feGaussianBlur`、`feDropShadow`、`clipPath`）和九个属性（`filter`、`clip-path`、`stdDeviation`、`in`、`result`、`clipPathUnits`、`filterUnits`、`flood-color`、`flood-opacity`），其余照旧丢弃。`filter` / `clip-path` 的值只接受 `none` 或**恰好一个** `url(#本地id)`——比填充色的规则严，因为滤镜的值在 CSS 里是列表，照搬的话会放过第二个指向外部的引用。这个模式下还有两条：不保留任何 `style` 属性（CSS 能从那里写 `filter:blur(…)`、`image-set('https://…')`，绕过上面的规则），值里带反斜杠的属性一律丢弃（`u\72l(#g)` 这种 CSS 转义，浏览器当它是 `url(#g)`）。清洗后的图不引用自身之外的任何东西。10 张样例的原始文件经它清洗，和你确认的那一版清洗结果逐字节相同；不带新参数的默认模式（线上自动生成的图）一个字节都没变。
- **结构校验（`memo.check_structure`，导入时执行，不需要字体）**：根 `viewBox="0 0 800 500"`；根下有 `<g id="scene">`，最后一个子元素是 `<g id="word-art">`，两个 id 全文件各一次；`#word-art` 里 `wa-<序号>-<字符>` 的 `<path>` 按序号拼出的正是这个词的显示形式里的字母和数字（区分大小写，每个序号一次，不许出现在场景层）；清洗后不超过 60 KB；**模糊预算**——带滤镜的元素最多 16 个、一个 `<filter>` 里最多 3 个模糊 / 投影、每个 `stdDeviation` 是一两个 0–60 的普通数字（10 张样例最多 7 个、1 个、0.8–7；超出的图在没有 GPU 的机器上可能要画几十秒）；并且这个文件确实能被 `?plain=1` 截开，**截出来的画面自己站得住**——场景用到的渐变、滤镜、裁剪路径不能定义在单词层里。字形是不是真的 Andika 轮廓由 `studio/tools/check` 把关（那边有字体）——它跑的是仓库里同一份清洗器和同一份结构校验，没有自带的规则，所以在 studio 里过了的图导入时不会被拒。
- **两种取法（`routers/media.py`，接口 52）**：页面用 `<img>` 显示图片，脚本够不到 SVG 里面的图层，所以「不带单词」只能由服务器给。清洗器的输出是规范化的，单词层又是根的最后一个子元素，`?plain=1` 就是纯字符串操作：存盘的文件截到 `<g id="word-art"` 之前，补上 `</svg>`——场景、`<defs>`、AIGC 标记和完整版逐字节相同。响应头不变（不可变缓存按完整地址区分，两种取法各缓存各的）。不是记忆图卡的文件、`plain` 的其他取值（`0`、`true`、空、重复）都按没有参数处理。
- **导入与撤回（`images/handler.py`、`images/store.py`）**：清单是 `{"prompt_version": "memo-1", "model": "…", "cards": {"<lemma>": {"alt_zh", "hook_zh", "note_zh"}}}`，图在 `DIR/<lemma>.svg`。逐词：lemma 必须是公开、未合并的词 → 清洗 + 结构校验 + 三句话的长度（钩子、提醒各 ≤ 60 字，画面描述 ≤ 200，超长拒绝而不是截断）→ 和在用的图是同一张就记 `unchanged`（三句话有改动会就地更新；`images/` 里它的文件丢了会原样补回）→ 这张图是管理员处理反馈时撤下的就记 `retired`、不动它（`--only <词>` 点名才恢复）→ 否则打上 AIGC 标记、按 sha256 存盘、激活，旧图变 `superseded`。文件只清洗一次：比对用的和存盘的是同一份。每张图一个事务；某一张存不进去（磁盘满、数据库锁住）记为这一张的 `rejected: could not store`，后面的照常处理；有被拒的退出码 1；清单里两个键指向同一个词、或者有存不了的字符时整份拒绝（退出码 2）；`--dry-run` 把上面的检查全做一遍但什么都不写。`--undo`：清单里在用图是记忆图卡的词，图卡标成 `superseded`，这个词回到**图卡到来时**的样子——最近一张不是记忆图卡的旧图重新启用（文件没了就再往前找）；那张旧图要是被反馈撤下了、之后一直没有新图，或者根本没有旧图，就回到模板卡，更早的图不会被翻出来；什么都不删，撤了可以再导。导入和撤回都不发任何网络请求、不调 AI。
- **不让图卡被自动换掉**：前端在记忆图卡上不显示「换一张」；后端的 `fetch_image` 处理到在用图是记忆图卡的词时，除非是管理员明确要求（管理端换图，或带 `provider` / `query` 的任务），否则不搜、不画，任务以 `{"skipped": "memory_card"}` 结束，`image_state` 回到 `ready`——旧版页面发来的「换一张」、失败图的自动重试、内容任务顺带排的取图都在此列。自动补画的 `generate_svg` 本来就不覆盖在用的图，这次补了测试。**「不合适」只记录**（11-13 定，第 6 节第 3 条）：学习者在记忆图卡上点「不合适」，接口照样答 201、反馈照样进「管理 → 内容反馈」，但图卡不标 `rejected`、不排取图——一个孩子点一下，不会把评审过的图换成图库里的图。管理员在那条反馈上点「换图」才是撤下图卡的那一步。照片和旧式示意图上的「不合适」照旧（当场下线、再取一张）。
- **前端（`components/study/WordImage.tsx` 等）**：`image.word_layer && !settings.image_word` 时图片地址是 `image.url + '?plain=1'`，开关经 `StudyPage` → `StudyCard`、`WordDetailPage` 传到 `WordImage`（和「显示配图」同一条路；未登录的体验区固定显示带单词的图）。「记忆」一栏由 `memoryLines` 决定：图显示着且有 `hook_zh` → 钩子 + 较淡的 `note_zh`；否则是内容里的 `mnemonic_zh`。钩子随图而来，所以例句还在生成、顺延或失败时也照常显示。集成时补了一处：记忆图卡的替代文字用图自己的 `alt_zh`（就是这张图的画面描述），不再被内容里早先写的 `image_alt_zh` 盖住。图没加载出来（断网、文件丢了）时不显示钩子，退回联想句。记忆图卡上点完「不合适」，详情页只提示「已收到反馈，谢谢」，不再等新图。文案两条，在 `zh.ts` 的 `settings.imageWord` / `imageWordHint`，FRONTEND §8 逐行镜像。
- **`studio/`**：流程是「美术指导 → 画 → `tools/check` → 看渲染图 → 评审 → `wd images-import`」，写在 `studio/README.md`。`tools/check` 依次做四件事：用仓库的清洗器清洗并报出被丢掉的东西、用仓库的结构校验、只有它能做的字形校验（每个字母的路径必须是 Andika 的字形，手改一个点就不行）、用无界面的 Chrome 渲染。审查之后字形校验又补了几条：字母不能被 `transform` 镜像、翻转、压扁、拉长或斜切（倾斜 5° 以内不提示，5°–15° 警告，超过 15° 报错），看不看得见按外层的组继承着判断，出没出画布按墨迹量，任何一张渲染图没出来都算错误。和设计稿有出入、或者设计稿没写到的细节，逐条列在设计稿 §8 和 §8.1。
- **旧响应的重放**：推荐词判「不熟悉」时整份响应会存下来，设备没收到就重发。上线前存下的响应里没有 `ImageMeta` 新加的三个字段，现在回放时补上（`services/screen.upgrade_stored`），否则是一个设备会一直重试的 500。反方向修不了：新代码存下的响应，回滚到旧代码之后回放是 500，直到新代码回来——所以上线、回滚都挑没人正在学的时候重启（第 4 节第 4 步、第 5 节）。

## 3 验收（提交前门禁，2026-11-13，这台 Mac，工作区 `memory-cards`；代码审查的修复合在一起、再集成之后的最终状态）

- **pytest 全量**：**3100 passed / 3 skipped / 1 deselected**（6 分 10 秒；Mac 上照例排除 `test_deploy_files.py` 和 `test_config.py::test_defaults_without_environment`；审查之前是 3030）。被排除的两处单独跑过：`test_config` 那 1 条照旧是红的；`test_deploy_files.py` 是 20 failed / 12 passed / 1 skipped——失败的还是基线 `ea77832` 上那 **20 条**（`install.sh` / `fetch_ecdict` 那些只能在 Linux 上跑的，外加第 6 节第 12 条说的那一条），和这次无关；其中和这次有关的 Makefile / `.gitignore` / `env.example` 那几条全过，`make studio-check` 的写法也钉在里面了。同一条命令在修复刚合起来时先跑过一遍，是 3098 passed / 1 failed——失败的是 `integration/test_worker.py::test_worker_threads_start_stop_join`，这台 Mac 连不上 Wikimedia 时的老毛病，第二遍没有再出现。新增 `tests/unit/test_memo.py`（**71 条**：识别规则、结构校验逐项、模糊预算、去掉单词层后的画面自己站得住、`?plain=1` 的截法和它拒绝的形状、脱离 `wd` 包按路径加载）、`tests/unit/test_db_0021.py`（3 条）、`tests/integration/test_memo_cards.py`（**51 条**：存储、几种旧图的 `ImageMeta`、导入 / 空跑 / 拒绝 / `unchanged` / 三句话更新 / 只清洗一次 / 丢了的文件补回 / 清单的键 / 存不进去 / `retired` / `--only`、撤回的几种去向、取图和补画的拦截、记忆图卡上的「不合适」只记录）；`test_sanitize_svg.py`（现在 53 条，`effects` 一组，含「不留 `style`、不留反斜杠、默认模式一字不变」）、`test_today_flow.py` / `test_screen.py`（旧响应的重放各 1 条）、`test_media.py`、`test_settings.py`、`test_images.py`、`test_demo.py`、`test_cli.py`、`test_api_schemas.py`、`test_docs_contract.py` 各有增补，`test_images.py` / `test_admin_ops.py` 里管理端换图的任务参数断言跟着多了 `requested: true`。`--deselect` 的写法同磨耳朵那次（`tests/unit/test_config.py::…`，不带 `backend/` 前缀）。
- **契约**：`scripts/check_contract.py -q` → `contract OK: no property-name or literal-union mismatch`（只剩一直就有的 9 条可空性 note）；API.md §9 == `types.ts`、FRONTEND §8 == `zh.ts` 由 `test_docs_contract.py` 钉住（14 条，含 `test_memory_card_docs_match_the_code`：迁移文件 == 设计稿 §3.4 的 SQL 块、DEPLOY §9 的命令写法 == 解析器登记的选项、DESIGN §9 列出的元素和属性 == 清洗器的两张表、模糊预算的三个数 == `memo.py` 的常数、接口 28 / 71 对「不合适」的说法），在全量里通过。这一轮契约本身（`types.ts`、`schemas.py`、API.md §9）没有动。
- **前端**：`npm run typecheck` 通过；vitest **68 个文件 / 679 条**全过（审查之前 668；`components/study/WordImage.test.tsx` 12 条；`StudyCard`、`WordDetailPage`、`StudyPage`、`SettingsPage`、`LoginPage`、`css-contracts`、`zh` 各有增补，另有 15 个带 `Settings` / `ImageMeta` 夹具的测试文件补了新字段）；`npm run lint` → `copy check OK`；`npm run build` 通过，首屏主包 `index` 350.67 kB（**gzip 115.66 kB**，上一版 115.63），`WordImage` 所在的块 3.82 kB（gzip 1.72 kB），`SettingsPage` 27.30 kB（gzip 7.07 kB）；构建产物 90 个文件，`legal/licenses.html` 里有 Andika 一节，带 `?plain=1` 的块 1 个（就是第 4 节第 3 步那两个 `grep` 的 `1` 和 `3`）。
- **`studio/`**：`studio/.venv/bin/python -m pytest studio/tests` → **42 passed**（15 秒，含真实的 Chrome 渲染；审查之前 34）。10 张定稿的图逐张过 `studio/tools/check`（带渲染）：全部 `ok`，`errors` 和 `warnings` 都是 0，整图和对照图都写出来了；清洗后 27,117–43,920 字节，带模糊的图层 4–7 个。10 份清洗结果、10 张 800×500 渲染图、10 张对照图，和同一天用修复**之前**的工具跑出来的那一轮逐字节相同（审查之前的那次门禁核对过，原来的工具跑出来的和你确认的那一版逐字节相同）——新加的规则没有碰到任何一张定稿的图。
- **端到端冒烟**（`make smoke`，工作区的后端，临时数据目录，端口 8010，不碰线上）：**36 步全过**（46 秒）。记忆图卡那一步现在是：空跑 → 导入 moon → `ImageMeta.word_layer` 为真且带着钩子 → `?plain=1` 返回的图里没有 `word-art`、正好是存盘文件截到单词层之前 → `image_word` 关 / 开都能读回 → 再导一次是 `unchanged` → 「换一张」之后图卡还在、`image_state` 回到 `ready` → **「不合适」答 201、图卡原样、反馈在管理员的列表里是未处理** → `--undo` 回到导入之前。
- **导入 / 撤回从头走一遍**（审查之后；`wd` 命令逐条以子进程运行，`WD_DATA_DIR` 指向工作区 `studio/tmp/` 下的临时数据目录，`wd migrate` + `wd import-seed` 仓库自带的 9618 个词；**144 项检查全部通过**）：
  - 10 个样例词先摆成线上会有的样子：6 个是 `svg-v2` 的旧示意图，2 个是照片，2 个是模板卡（其中 1 个取图失败过、`image_state` 是 `failed`，1 个从没取过）。
  - 空跑 → `10 would be imported, 0 unchanged, 0 rejected`，行、文件、每个词的 `ImageMeta` 都没变。真导入 → `10 imported, 0 unchanged, 0 rejected`；逐张：`word_layer` 为真，三句话和清单一致，存盘的文件 == 清洗结果 + 一行 AIGC 标记（10 张合计 379,114 字节，和审查之前一样），里面没有 `style`、没有反斜杠，`?plain=1` 截出来的部分引用的每个 `url(#id)` 都有定义。再跑一遍 → `0 imported, 10 unchanged, 0 rejected`，没有一行被动过。
  - 删掉 moon 的图片文件：空跑报 `unchanged  moon (file missing from images/ — a real run restores it)`，真跑报 `unchanged  moon (file restored)`，文件逐字节回来，行没动。
  - 模拟管理员在反馈里把 rain 的图卡撤下：整份清单重跑 → `0 imported, 9 unchanged, 0 rejected, 1 retired`，rain 没有被换回来；`--undo --only rain` 是 `kept`；`--only rain` 才把它导回来。
  - `--undo --dry-run` 不写；`--undo` → `10 memory card(s) superseded (8 word(s) back on the previous picture, 2 on the template card), 0 kept, 0 unknown`：10 个词的 `ImageMeta`、`active_image_id`、`image_state` 都和导入之前**完全相同**（取图失败过的那个词回到 `failed`，没取过的回到 `none`）；再撤一次是 `10 kept`；撤完再导 → 又是 `10 imported`，再导 → `10 unchanged`；`--only` 里夹一个不存在的词 → 那个词 `rejected`、退出码 1。最后 `wd check db` 通过，`integrity_check` / `foreign_key_check` 干净。

下面四条是**审查之前**做的，结论没有因为修复而失效，这一轮没有重跑（第一条的脚本在当时会话的临时目录里，已经不在了；上面那条是它在命令行一侧的重做）：

- **整套流程接在一起**（进程内，`wd.cli.main` + TestClient，临时数据目录 `…/scratchpad/memo/it-data`，仓库自带的种子 9618 个词；**386 项检查全部通过**）：
  - 10 个样例词都在种子里，都是公开的小学词。先给它们摆上线上会有的三种状态：6 个词是 `svg-v2` 的旧示意图，2 个是照片，2 个什么都没有（模板卡）。
  - `wd images-import studio/cards --manifest studio/manifest.json --dry-run` → `10 would be imported, 0 unchanged, 0 rejected`，数据库的行和 `images/` 里的文件都没有变。
  - 真导入 → `10 imported, 0 unchanged, 0 rejected`。逐张核对：`ImageMeta.word_layer` 为真，三句话和清单逐字相同，800×500；行上是 `memo-1`、清单里的模型、`text_free = 1`；存盘的文件 == 你确认的清洗结果 + 一行 AIGC 标记，27,219–44,022 字节，10 张合计 379,114 字节；原来的图变成 `superseded`、文件还在。
  - 再跑一遍 → `0 imported, 10 unchanged, 0 rejected`，没有任何一行被动过。
  - 经 HTTP：`GET /api/words/<词>` 和 `GET /api/words/{id}/image` 给出的 `ImageMeta` 与上面一致；`GET /media/images/<path>` 带单词层，`…?plain=1`（就是前端 `imageSrc()` 拼出来的那个地址）没有 `word-art`、没有任何 `wa-` 路径、仍有场景层和 AIGC 标记、等于完整文件截到单词层之前、四个响应头与完整版相同；截出来的图仍是合法的 XML，引用的每个 `url(#id)` 都有定义，去掉标记后再清洗一遍一字不差。`?plain=0`、`?plain=true`、`?plain=1&plain=1`、`?plain=` 都是完整的图。10 张全部如此。
  - `Settings.image_word` 默认真，关 / 开都能读回（`/api/settings` 和 `/api/auth/me`），`"maybe"` 被拒。
  - 旧版页面发来的「换一张」：202，`wd worker-once` 处理这一个任务，结果 `{"skipped": "memory_card"}`，图卡还在，`image_state` 是 `ready`。
  - `--undo --dry-run` 不写；`--undo` → `10 memory card(s) superseded (8 word(s) back on the previous picture, 2 on the template card)`：10 个词的 `ImageMeta`、`active_image_id`、`image_state` 都和导入之前**完全相同**，图卡的行和文件还在；再撤一次是空操作（`10 kept`）；撤完再导 → 又是 `10 imported`；`--only` 里夹一个不存在的词 → 那个词 `rejected`、退出码 1。最后 `wd check db` 通过，`integrity_check` / `foreign_key_check` 干净。
- **两种取法的渲染图**（把上一条里媒体接口返回的 20 个文件用 `<img>` 摆在一起，经 studio 的 Chrome 渲染，逐张看过）：左边完整的图有单词，右边 `?plain=1` 是完整的场景，没有残留的字母、投影或空白块。几处值得一提：happy 去掉单词后露出朵朵牵着的两只气球（两个 p 本来就叠在气球上）；rain 里落向 i 的那串雨滴属于单词层，一起消失，朵朵手里接住的那一滴在场景层，还在；sleep 的两道睫毛、share 下面的连读弧线也随单词层消失。
- **迁移 0021**：`test_db_0021.py`（3 条，参照 `test_db_0015.py`）；另外在一个按 0001–0020 建好、导了仓库种子、有 3 个用户和 5 张旧图的库上实跑：`wd migrate --dry-run` 列出 `0021_memory_cards.sql`，`wd migrate` 套用并写出 `backups/pre-migrate-20-to-21.db.gz`（解开核对过，是 schema 20 的库）；`image_word` 追加在最后且全是 1，`hook_zh` / `note_zh` 追加在最后且全是 NULL，其余每一行逐列相同，没有哪张旧图变成记忆图卡，再跑一次不做任何事；迁移后的库随即导入 3 张、撤回 3 张都正常。同一个 schema 20 的副本交给 `scripts/rehearse_migration.py`：**124 项检查全部通过**（含新增的 `check_0021` 11 项）。
- **回滚的那一半**（把 `ea77832` 的后端用 `git archive` 取到临时目录，对着上面那个 schema 21、10 张图卡还在用的库的副本跑，15 项检查全过）：旧代码启动正常，`wd migrate` 无事可做，schema 留在 21；设置能读能写（旧的 DTO 里没有 `image_word`，那一列不受影响），新注册的用户得到默认值 1；还挂着图卡的词，旧代码把它当普通的 AI 示意图整张下发（带单词），`?plain=1` 被忽略；`wd check db` 通过。
- **第一次集成时改的三处**（第 2 节、第 6 节各有交代）：替代文字（前端一行 + 一条会失败的测试——把那一行改回去，新测试报 `expected 'CONTENT-ALT' to be 'ALT-ZH'`，随后还原并 `cmp` 核对）；`docs/ops.md` 的导入步骤补了「先确认没有正在跑的取图任务」；设计稿补了 §8。
- **审查与修复**（11-13 下午）。实现和第一次集成之后，五个角度各一位审查者看了一遍（清洗与安全、数据与接口、前端、studio 工具、测试 / 文档 / 上线步骤），提出 **28 条**发现；每一条都由另一个人照着复现之后再下结论：**27 条确认，1 条存疑（第 16 条，开关说明文字的措辞），0 条被推翻**。复核之后定为「中」的 2 条（上线前存下的响应重放时是 500；字形校验放过了被 `transform` 镜像、压扁的字母），其余 26 条是「低」——其中 4 条原报「中」，复核后降了级（要运维自己的清单或做图流程出错才碰得到）。有两对是同一个毛病报了两次（第 6 条就是第 11 条的第一点，第 14 条就是第 25 条），各修一次。
  - **28 条全部处理**：22 条改了代码（含界面文案和 Makefile），每条都有一条「改之前失败、改之后通过」的测试；6 条（第 14、23、24、25、27、28 条）改的是文档、手册和上线步骤。另外做了第 6 节第 3 条（记忆图卡上的「不合适」只记录，11-13 定），它不在 28 条之内，但第 11、13 条是照着它改的。
  - **没有照复核意见原样做的几处**：第 5 条的倾斜做成了分级（第 6 节第 15 条）；第 11 条里「图卡被举报之后 `--undo` 不动这个词」按复核意见保留不改，现在只有管理员撤下图卡之后才会遇到；第 11 条的 `failed` / `none` 用「有没有跑完的取图任务（被图卡拦下的不算）」来判断；第 13 条随着第 3 条的决定改成了「管理员撤下的图卡不自动换回」；第 16 条的措辞在没有问你的情况下改了（第 6 节第 14 条）；第 18 条多做了一步（同一个地址重试成功后钩子会回来）；第 27 条的发布把关多加了一个条件（许可页里有 Andika，防的是合并被拒之后发布了 `main` 的旧前端）。
  - **集成时的核对**：三条线的修复有没有对上——前端对记忆图卡不再等新图，用的是和后端同一个判断（`ImageMeta.word_layer` ⇔ 在用的图是记忆图卡）；`studio/tools/check` 报的就是导入那道门的原话（同一份 `memo.check_structure` 和清洗器），它自己那段已经走不到的 `style` 检查删掉了，提示语跟着改准。逐条验证了「撤掉修复，测试就失败」：后端把这几组测试对着修复之前的代码跑，234 条里 **60 条失败**（现在全过）；前端 8 处修复逐个撤掉再跑，每次都有测试失败，随后还原并逐字节核对；studio 工具在副本上撤了 14 处，全部被测试抓住。集成时补的：一条走命令行的回归测试（导入拒绝「场景用了单词层里的定义」和超出模糊预算的图、存盘的文件里没有 CSS）、Makefile 那条修复的断言、`docs/ops.md` 里排队中的管理员任务的查询（在 zsh 和 bash 里对着临时库跑过）、DESIGN §9 / 设计稿 §8.1 / 本文 / `studio/README.md` / `docs/qa-study.md` 的更新。
  - **测试数的变化**：后端 3030 → 3100，前端 668 → 679，studio 34 → 42；`test_memo.py` 30 → 71，`test_memo_cards.py` 27 → 51，`test_sanitize_svg.py` 50 → 53。
- **没有跑的**：任何真机（平板、手机）；线上数据（没有读过，也没有在线上库的副本上演练——第 4 节第 2 步给了演练的命令）；100 张的批量图（还没有定稿；它们要用修复之后的 `tools/check` 重新过一遍，第 6 节第 1 条）。

## 4 上线步骤（Mac launchd；提交 → 合入线上检出 → 前端快照 → 重启（套用 0021）→ 核对 → 导入图卡 → 核对）

和磨耳朵那次一样：改动**不在线上检出里**，在工作区 `/Users/sqin/word-dance/.claude/worktrees/memory-cards`（分支 `memory-cards`）；线上服务跑的是 `/Users/sqin/word-dance`（分支 `main`）。所以**不是 `git pull`**，而是在线上检出里把本地分支快进合并进来。下面的命令块**都不带注释**，可以原样粘贴到这台 Mac 的 zsh；每一块开头都重新写了变量（`W` 工作区、`L` 线上检出、`D` 数据目录），换终端也不会丢。每块下面写着期望看到什么。

分两段，可以隔开做：**第 1–5 步是代码**（做完线上看起来没有变化，只是设置里多一个开关）；**第 6–7 步是数据**（这 10 个词换图）。

0. **确认**：上线（第 1–5 步）和导入这 10 张图（第 6 步）各要你一句话。

1. **提交**（只动工作区的分支，线上不变）：

   ```sh
   W=/Users/sqin/word-dance/.claude/worktrees/memory-cards
   cd $W && git status --short | wc -l
   git add -A && git -c user.name=sqin -c user.email=sqin@nvidia.com commit -q -m "feat(images): 记忆图卡 — picture cards with the word woven in: sanitiser effects mode, GET /media/images/{path}?plain=1, ImageMeta.word_layer / hook_zh / note_zh, Settings.image_word (migration 0021), wd images-import / --undo, studio/ with the ten approved cards" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
   git status --short | wc -l; git log --oneline -2 | cut -c1-72
   ```

   期望：第一个数是 `86`（76 个修改、10 项未跟踪；`.venv`、`frontend/node_modules`、`frontend/dist`、`studio/.venv`、`studio/tmp`、`studio/png`、`studio/clean` 都被忽略，不会进提交），提交之后是 `0`；最后两行上面是新提交、下面是 `ea77832`。

2. **上线前检查**（只读）：

   ```sh
   L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
   git -C $L status --short; git -C $L log --oneline -1 | cut -c1-60
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT MAX(version) FROM schema_migrations"
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT type, status, COUNT(*) FROM jobs WHERE status IN ('queued','running') GROUP BY 1, 2"
   readlink $D/frontend
   ```

   期望：`git status` 没有输出，HEAD 是 `ea77832`；schema 是 `20`；任务那一条里没有 `running` 的行再往下走（`queued` 的留在库里，重启后照常接着跑——按之前的记录，11-11 那轮补图的看守脚本到 11-16 之前还会不时排 `fetch_image`）；最后一行按磨耳朵的上线记录应当是 `frontend-releases/ea444c8`，**如果不是，把第 5 节回滚命令里的 `PREV` 换成这里打印的值**。 本文里所有 `sqlite3 -readonly` 的查询都要在服务跑着的时候做：库是 WAL 模式，只读连接靠服务进程留着的 `-shm` 文件才能打开，服务停着时会报 `unable to open database file`（在临时目录里实测如此；有连接开着时这些查询逐条跑过）。
   想先在线上库的副本上演练迁移（可选。这一轮没有碰线上数据，所以**这一块没有实跑过**：取副本的写法照抄 `docs/releases/2026-11-k12-stages.md`，演练脚本在按 0001–0020 建的库上跑过，见第 3 节）。合并之前线上检出里还没有 0021，所以脚本和后端都用工作区的：

   ```sh
   W=/Users/sqin/word-dance/.claude/worktrees/memory-cards; L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data; M=$HOME/wd-rehearse-0021
   mkdir $M && $L/.venv/bin/python -c "import sqlite3; sqlite3.connect('$D/word-dance.db').execute(\"VACUUM INTO '$M/word-dance.db'\")"
   cd $W && PYTHONPATH=$W/backend $L/.venv/bin/python scripts/rehearse_migration.py $M/word-dance.db | tail -1
   rm -f $M/word-dance.db* && rmdir $M
   ```

   期望：`rehearsal OK (… passed, 0 failed)`。副本在你的主目录下，不在数据目录里，演练不写线上库。

3. **合入线上检出，出前端快照**（从这里到第 4 步连着做，一两分钟）：

   ```sh
   L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
   cd $L && git merge --ff-only memory-cards
   SHA=$(git rev-parse --short HEAD); echo "new $SHA"; readlink $D/frontend | tee $D/frontend.prev
   cd $L/frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build -- --outDir $D/frontend-releases/$SHA.new --emptyOutDir && cd $L
   mkdir -p $D/frontend-releases/$SHA.new/dl && cp -p $D/frontend/dl/*.apk $D/frontend-releases/$SHA.new/dl/
   grep -l 'plain=1' $D/frontend-releases/$SHA.new/assets/*.js | wc -l; grep -c Andika $D/frontend-releases/$SHA.new/legal/licenses.html
   test -f $D/frontend-releases/$SHA.new/index.html && grep -q Andika $D/frontend-releases/$SHA.new/legal/licenses.html && mv $D/frontend-releases/$SHA.new $D/frontend-releases/$SHA && ln -sfn frontend-releases/$SHA $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')" || echo 'SNAPSHOT NOT PUBLISHED, the old one stays linked: fix the error above (refused merge or failed build), then rerun this block; do NOT restart'
   ```

   期望：`git merge` 报 `Fast-forward`（线上检出在这一刻变成新代码）；构建成功，`index` 约 350 kB / gzip 约 116 kB；`grep` 两个数是 `1` 和 `3`（新快照里有 `?plain=1` 的那个块，许可页里有 Andika）；**最后一行什么都不打印**。整块粘贴时，前面某一行失败了后面的行照样会执行，所以发布由最后一行把关：它是一条 `&&` 链，只有新快照里有 `index.html`（构建确实做完了）、许可页里有 Andika（构建的确实是这一版的代码）才改名、切软链；否则打印 `SNAPSHOT NOT PUBLISHED…`，什么都没有发布，软链还指着旧快照——**这时不要做第 4 步**。两种情形：
   - **构建失败**（`npm run build` 报错，随后 `grep` 那一行多半是 `zsh: no matches found`）：按构建的报错修好，把这一块从头再粘贴一遍（合并那一行会说 `Already up to date.`，`--emptyOutDir` 会清掉上次留下的半成品）。一时修不好想先撤：第 5 节最后一段（合并之后、重启之前反悔）。
   - **`git merge --ff-only` 拒绝**（`main` 在这期间多了提交）：这一块照样往下跑，构建出来的是 `main` 那个提交的前端，`grep` 两个数是 `0` 和 `0`，最后一行拦住不发布。`cd /Users/sqin/word-dance/.claude/worktrees/memory-cards && git rebase main`，重跑第 3 节的门禁，再回到这一步（那次留下的 `frontend-releases/<main 的短号>.new` 可以删）。

   发布成功之后这一块不要再粘贴第二遍：第 3 行会把 `frontend.prev` 改写成新快照的名字，回滚时就没有旧快照可对了。没有新依赖，不用 `npm ci`。进程在启动时才解析 `$D/frontend` 这个软链，所以快照切过去之后、重启之前，线上仍是旧前端配旧后端。

4. **重启**（服务启动时写迁移前快照、套用 0021）：

   ```sh
   launchctl kickstart -k gui/$(id -u)/com.word-dance.server
   for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do sleep 1; curl -sf --noproxy '*' http://127.0.0.1:8000/api/health && break; done; echo
   ```

   期望：几秒内打印健康检查的 JSON。重启尽量挑没人正在学的时候（回滚时的那次重启也一样）：推荐词判了「不熟悉」、回应还没送到设备的那一下如果正好跨过重启，设备会重发，新代码照上线前存下的那份回答并补上新字段（第 2 节「旧响应的重放」），接得上；反过来的方向接不上，见第 5 节。

5. **核对**：

   ```sh
   L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT MAX(version) FROM schema_migrations"
   ls -l $D/backups/pre-migrate-20-to-21.db.gz
   grep -c 'applied migration 0021_memory_cards' ~/Library/Logs/word-dance/word-dance.log
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT COUNT(*), SUM(image_word) FROM user_settings"
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT COUNT(*) FROM word_images WHERE hook_zh IS NOT NULL OR prompt_version LIKE 'memo-%'"
   readlink $D/frontend; git -C $L log --oneline -1 | cut -c1-60
   ```

   期望：`21`（只有新代码启动过才会是 21，所以这一行同时说明跑着的是新代码）；迁移前快照在；日志里那一行出现 `2` 次（同一次启动里 `wd.db` 和 `wd.main` 各记一行）；用户数和 `image_word` 之和相等（人人都是 1）；记忆图卡 `0` 张；软链指向新的 SHA。然后在浏览器里：设置 → 学习设置，「显示配图」下面有「图片上显示单词」，默认开，关了再开都提示「已保存」；`/legal/licenses.html` 有第 4 节「图卡里的字母：Andika 字体」。这时学习卡和详情页的图都还是原来的。

6. **导入 10 张样例**（数据；要你点头）：

   ```sh
   L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT type, COUNT(*) FROM jobs WHERE type IN ('fetch_image','generate_svg') AND status = 'running' GROUP BY 1"
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT j.id, j.type, w.lemma FROM jobs j JOIN words w ON w.id = json_extract(j.payload_json, '$.word_id') WHERE j.type IN ('fetch_image','generate_svg') AND j.status = 'queued' AND (json_extract(j.payload_json, '$.requested') = 1 OR json_extract(j.payload_json, '$.provider') IS NOT NULL OR json_extract(j.payload_json, '$.query') IS NOT NULL)"
   cd $L && WD_DATA_DIR=$D .venv/bin/wd backup
   cd $L && WD_DATA_DIR=$D .venv/bin/wd images-import studio/cards --manifest studio/manifest.json --dry-run
   ```

   期望：前两条都没有输出。第一条查的是**正在跑**的取图 / 画图任务（有就等它跑完——它开始时看到的还是旧图，几秒后可能把自己取到的图盖在图卡上面）。第二条逐行列出**还在排队、而且是管理员要求的**换图任务（任务号、类型、词）：管理端换图，或带 `provider` / `query` 的任务——排队的任务里只有这一种轮到时会把图卡换掉；别的（补图看守脚本排的、失败图的自动重试、学习者的「换一张」、自动补画）遇到图卡都会跳过，所以不列。列出的词如果在这次要导入的清单里，等那个任务跑完再导入（被当天预算顺延的画图任务要到第二天才跑）；不想等也可以照常导入，那个任务轮到时会把这个词的图卡换掉，之后把下面真导入的那条命令加上 `--only <词>` 再跑一次即可。`backup written: …`；空跑的最后一行是 `images-import: 10 would be imported, 0 unchanged, 0 rejected (memo-1, claude-fable-5-2) — dry run, nothing written`。有 `rejected` 就停下，把那一行发给我。空跑没问题再真导入：

   ```sh
   L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
   cd $L && WD_DATA_DIR=$D .venv/bin/wd images-import studio/cards --manifest studio/manifest.json
   cd $L && WD_DATA_DIR=$D .venv/bin/wd images-import studio/cards --manifest studio/manifest.json | tail -1
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT COUNT(*) FROM word_images WHERE status = 'active' AND prompt_version LIKE 'memo-%'"
   ```

   期望：第一条的最后一行 `images-import: 10 imported, 0 unchanged, 0 rejected (memo-1, claude-fable-5-2)`；第二条（再跑一遍，顺便确认没有哪张被正在跑的任务盖掉）`images-import: 0 imported, 10 unchanged, 0 rejected (…)`；最后是 `10`。不用重启：学习者下一次打开页面就是新图（图片地址是新的，没有旧缓存的问题）。

7. **看一眼**：浏览器里打开 `/words/moon`、`/words/happy`：新图、带单词；「记忆」是图的钩子，下面一行较淡的提醒；图下只有「不合适」。设置里关掉「图片上显示单词」再回来看：同一张图只剩画面。然后按 `docs/qa-study.md` §9 在电脑、手机、**鸿蒙平板 App** 上各走一遍（平板不用重装，重新打开即可），把平板上的两项——图清不清楚、连着翻 10 张卡不卡——记进本文件的上线记录。

8. 不需要：改 `.env`、导种子、`wd learn-order`、AI、重装 APK。以后在线上检出里做图或跑工具自测才需要 `make studio-check`（它会建 `studio/.venv`，第一次要联网装 fonttools、skia-pathops、defusedxml，外加自测用的 pytest）；只是导入不需要。**以后那 100 张**：图放进 `studio/cards/`、三句话写进 `studio/manifest.json`、提交、合入，然后重复第 6–7 步（已经在用的 10 张会是 `unchanged`；这期间如果管理员在反馈里撤下过哪张图卡，它列为 `retired`、不会被换回来，汇总末尾多一截 `, 1 retired`，不算错误，想恢复就加 `--only <词>` 再跑）——不用重启，不用出前端快照。那 100 张收进 `studio/cards/` 之前，先用现在的 `studio/tools/check` 逐张重新过一遍（第 6 节第 1 条：它们是用审查之前冻结的工具做的）。

## 5 回滚

**顺序要紧：先撤图，再退代码。** 撤图用的是新代码里的命令和新检出里的清单，代码退回去之后这两样都不在了；而且旧界面没有开关、图卡上还会出现「换一张」（旧后端真的会把它换成图库里的图）。下面两段都不带注释，可以直接粘贴。

只撤图（代码不动；这 10 个词各自回到导入之前的那张图）：

```sh
L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
cd $L && WD_DATA_DIR=$D .venv/bin/wd images-import --undo studio/manifest.json --dry-run
cd $L && WD_DATA_DIR=$D .venv/bin/wd images-import --undo studio/manifest.json
sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT COUNT(*) FROM word_images WHERE status = 'active' AND prompt_version LIKE 'memo-%'"
```

期望：空跑逐词列出会换回哪张图；真撤的最后一行 `images-import --undo: 10 memory card(s) superseded (10 word(s) back on the previous picture, 0 on the template card), 0 kept, 0 unknown`（小学词原来都有示意图；哪个词原来没有图，就回到模板卡，计在后一个数里）；最后是 `0`。什么都没删，想再上就重新导入。还没导入过图卡时这一段是空操作（`10 kept`），可以跳过。导入之后被管理员在反馈里撤下过图卡的词，在用的已经不是图卡，这里同样列为 `kept`，不动它（计在 `kept` 那个数里，前面的数相应少一个）。「回到导入之前的那张图」说的是图卡到来时这个词显示的东西：那张图期间要是被反馈撤下了，就回模板卡，不会翻出更早的图。

再退代码（旧代码 `ea77832`，旧前端快照 `frontend-releases/ea444c8`——`ea77832` 只改了文档，所以快照名不是它）：

```sh
L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data; PREV=frontend-releases/ea444c8
cat $D/frontend.prev; git -C $L status --short
cd $L && test -f $D/$PREV/index.html && git checkout ea77832 && ln -sfn $PREV $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')" && launchctl kickstart -k gui/$(id -u)/com.word-dance.server || echo 'ROLLBACK NOT COMPLETED, service NOT restarted: fix the error above, then rerun this line'
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do sleep 1; curl -sf --noproxy '*' http://127.0.0.1:8000/api/health && break; done; echo
git -C $L log --oneline -1 | cut -c1-50; readlink $D/frontend; sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT MAX(version) FROM schema_migrations"
```

期望：第 2 行打印 `frontend-releases/ea444c8`（上线第 3 步记下的旧快照；不一样就以它为准，改 `PREV` 再跑——除非它打印的正是新快照的名字：那是第 3 步在发布成功之后又被粘贴了一遍，这时用上线第 2 步核对时 `readlink` 打印的那个旧快照），`git status` 没有输出；第 3 行是 git 的分离 HEAD 提示，它是一条 `&&` 链，哪一步失败后面都不执行，改掉原因后重跑这一行即可；第 4 行几秒内打印健康检查的 JSON；第 5 行依次是 `ea77832 docs(listen)…`、`frontend-releases/ea444c8`、`21`。

**schema 留在 21，这是对的**：迁移只加了三列，旧代码不读它们（它的 INSERT 都写明了列名，新用户的 `image_word` 由列的默认值补上），留着无害——第 3 节「回滚的那一半」就是照这个状态实测的，连「图卡还没撤、代码先退了」的情形也测了（旧代码把图卡当普通示意图整张下发）。**不要为了这次回滚去恢复 `pre-migrate-20-to-21.db.gz`**：那会把重启之后所有人的学习记录一起退掉；真要连库一起退，按 `docs/ops.md` §4 / `docs/DEPLOY.md` §10 的 `wd restore` 步骤做（先停服务）。**退代码的那次重启挑没人正在学的时候**：新代码存下的「不熟悉」响应如果还没送到设备，旧代码回放它是 500（旧的响应模型不认识新加的三个字段），那台设备会一直重试，直到新代码回来；这一点在旧代码里修不了，只能靠避开。

回滚之后：线上检出处于分离 HEAD（`main` 仍指着新提交），`studio/` 和本文件在线上检出里看不到了，可以在工作区里看，或 `git -C /Users/sqin/word-dance show main:docs/releases/2026-11-memory-cards.md`。**原样重新上线**（不用重新构建）：

```sh
L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data; NEW=frontend-releases/$(git -C $L rev-parse --short memory-cards)
cd $L && test -f $D/$NEW/index.html && git checkout main && ln -sfn $NEW $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')" && launchctl kickstart -k gui/$(id -u)/com.word-dance.server || echo 'NOT REDEPLOYED: fix the error above, then rerun this line'
```

新快照的目录名是上线第 3 步打印的 `new <短号>`，也就是那时 `memory-cards` 分支的头；之后分支上又有了提交的话，`test -f` 会拦住，把 `NEW` 改成那个目录名再跑。然后按第 4 节第 6 步重新导入。**修了再上**：改动在工作区里做并提交，`cd /Users/sqin/word-dance && git checkout main && git merge --ff-only memory-cards`，再从第 4 节第 3 步的 `SHA=` 那一行往下做。不要在分离 HEAD 的线上检出里提交。

只在第 4 节第 3 步合并之后、第 4 步重启之前想反悔：「再退代码」那一段的第 3 行去掉 `&& launchctl kickstart -k gui/$(id -u)/com.word-dance.server` 这一截即可（这时还没有迁移，也没有图卡，不用重启）。设置里关过开关的人，`image_word = 0` 留在库里，旧代码不看它，重新上线后仍然有效。

## 6 未决（不阻塞上线；第 3 条已定、已实现；第 14–16 条是审查时替你拿的主意，可以否决）

1. **那 100 张还在做；批量画法已经定了**（2026-11-13，设计稿 §6 的试验；分数表在 `studio/README.md` §3）。四种画法各画同样的四个词（kite、jump、hungry、library），场景和钩子都出自自动的美术指导；16 张图打乱编号，三位评审（孩子和家长、美术指导、英语老师）对着确认过的样例盲评，8 分 = 样例的水平，每种画法 12 票：
   - 会话模型（做图的会话自己用的模型，也就是画那 10 张样例的 `claude-fable-5-2`）、最多看两次渲染图：**7.54** 分，9 票「可直接用」、3 票「小修」、0 票「不可用」；
   - 会话模型、不看渲染图直接画：7.21 分，6 / 6 / 0；
   - Opus、看两次：6.96 分，3 / 9 / 0；
   - Sonnet、看三次：6.38 分，1 / 9 / 2。

   每种画法每张都要 20–25 万 token：大头是读手册和写出约 35 KB 的 SVG，不是看图的那几次。**选定：会话模型，每张最多看两次。** 它就是画那 10 张样例的模型，所以这 100 张和样例进同一份 `studio/manifest.json`、同一个 `model`——原先担心的「换了模型就得另写一份清单、撤回也要逐份执行」不会发生。美术指导每批 11 个词，由一位策划和一位挑错的人完成，再由一位编辑通看全部 100 个词。评审扣分的地方整理成了 `studio/LESSONS.md`（随这次进仓库，动笔之前读）。之后的路不变：每张过 `tools/check` → 整批评审 → 总览页给你看 → 你点头 → 第 4 节第 8 步说的导入。
   **这 100 张是用一份冻结的工具做的**（`studio/tmp/frozen/`，审查之前的规则）。收进 `studio/cards/` 之前，要用现在的 `studio/tools/check` 逐张重新过一遍。新规则下可能冒出来的错误：字母被 `transform` 弄走样或倾斜超过 15°、`style` 属性、看不见的字母、字母出了画布、带滤镜的元素超过 16 个、一个滤镜里串了 4 个以上的模糊 / 投影、场景用了定义在单词层里的渐变或滤镜；警告：倾斜 5°–15°、字母离边不到 20 px、挪动或改过形的 i / j 的点。试验留下的 16 张图在新规则下没有一张出错，所以预计不多。
   试验的图和这 100 张的工作文件在工作区的 `studio/tmp/` 下（写这一条时是 `studio/tmp/scratch-archive/exp/` 和 `studio/tmp/run100/`）：不进 git，也不在那份归档里，**只存在于这个工作区**——那 100 张定稿、收进 `studio/cards/` 之前，不要删工作区，也不要清 `studio/tmp/`。
2. **真机没有验证**：平板 App 和手机上图的清晰度、翻面是否卡顿（模糊滤镜，设计稿 §5 风险 3）、`?plain=1` 在不可变缓存下的表现，都只在桌面的无界面 Chrome 里看过。`docs/qa-study.md` §9。
3. **「不合适」会让图卡下线——已定，已改**（2026-11-13）。原来任何学习者在记忆图卡上点一下「不合适」，图卡就被标成 `rejected`，系统随即去图库取图或补画一张旧式示意图——正是去掉「换一张」想避免的结果。现在：学习者的「不合适」**只记录**（接口 28 照样答 201，反馈进「管理 → 内容反馈」，记着是哪张图卡），图卡不下线、不排取图；管理员在那条反馈上点「换图」（接口 71）才撤下图卡，点「忽略」什么都不变。撤下之后想恢复：`wd images-import studio/cards --manifest studio/manifest.json --only <词>`（整份清单重跑不会把它换回来，只列一行 `retired`）。照片和旧式示意图上的「不合适」照旧。契约（`types.ts`、API.md §9）没动。随之而来的三件小事，都没有改，记在这里：
   - 图卡留着、按钮也不变灰，孩子可能连点几下，每点一下是一条新的反馈（每人每天上限 20 条）。嫌吵的话可以改成同一个人对同一张图只留一条未处理的反馈。
   - 管理员的「换图」撤下的是**处理那一刻在用的图**，不是反馈当时指的那张（一直如此）。图卡的反馈现在会留着等处理，所以如果先 `--undo` 了图卡、再去点那条旧反馈的「换图」，撤下的会是恢复回来的旧图。处理图卡的反馈之前先看一眼这个词现在显示的是什么。
   - 管理员在词上直接换图（接口 69）换掉的图卡，状态是 `superseded`，和 `--undo` 撤下的一样，下一次整份清单导入会把它当普通的 `imported` 换回来。只有经反馈撤下的（`rejected`）才受 `retired` 保护；要分清这两种得另外记一笔状态，没有做。
4. **`wd images-prune` 不认识记忆图卡**：磁盘不够时手工跑的那条命令，会把「N 天没人学的词」的图连行带文件一起清掉，记忆图卡和 `--undo` 要用的旧图也在其中（重新导入可以恢复图卡，旧图就没有了）。它不会自动运行；`docs/ops.md` 的故障表写了。要不要让它跳过图卡，等真有磁盘压力时再说。
5. **导入时还没跑完的取图任务**：正在跑的那一个有几秒的窗口会把图卡盖掉；排队中的任务轮到时遇到图卡会跳过，管理员要求的换图除外（第 6 步第二条查询）。操作步骤里写了先查这两种、导完再跑一遍确认；没有在代码里加锁。
6. **导入和撤回不留系统事件**：痕迹只有命令的输出和 `word_images` 的行（`prompt_version LIKE 'memo-%'`、`created_at`、`status`）。管理后台看不到「谁在什么时候导入了哪一批」。
7. **开关关着时的钩子**：钩子说的常常是字母（「两个 o 像两轮圆月」），关掉单词层之后图里没有字母，「记忆」一栏仍显示这句话（卡片上方的词头里有这个词）。按设计稿如此；用起来别扭的话可以改成关着时不显示钩子里讲字母的那类，或者整栏退回旧联想句——那就又回到谐音的问题上。
8. **「显示配图」关掉时**，「记忆」退回内容里旧的联想句（含谐音的那些）。按 D5 如此（钩子是「图演出来的」，没有图就不成立）。
9. **体验区**（登录页的三个示例词 up、jump、cold）：以后它们有了记忆图卡，未登录的人看到的是带单词的整图，那里没有开关，图片缓存一天。
10. **做图工具**：机器忙的时候 Chrome 偶尔在画完之前截图，渲染图上出现一条边缘整齐的空白带（做工具的同事统计：约 440 次里见过 3 次，重跑即好；这一轮 `tools/check` 给 10 张图出的 20 张渲染图与确认版逐字节相同，没有遇到；`studio/README.md` §5 写了）。`tools/check` 现在带着 Chrome 的 `--run-all-compositor-stages-before-draw` 参数（同事试过约 330 次没有再出现，但不算定论），批量做 100 张时仍建议每张渲染两次比对。任何一张渲染图没写出来现在是错误（退出码 1），不会再悄悄过去。批量脚本逐张调用 `tools/check --word` 时要的是词的**显示形式**（`Monday`），而清单的键是 lemma，脚本得从词库或资料里拿到前者。
11. **`studio/.venv` 只在工作区里有**（54 MB，不进 git）。合并之后线上检出里要用工具，得先 `make studio-check`（联网装 fonttools、skia-pathops、defusedxml，外加 pytest）。它每次运行都按 `studio/requirements.txt` 核一遍依赖：装齐之后是空操作、不用联网；第一次装到一半断了（这台 Mac 上 pip 走的代理没开时就会这样），代理通了再跑一次就补齐，不用删 `studio/.venv`。
12. **与本次无关、但这一轮碰到的**：
    - `docs/DEPLOY.md` §2 里照抄的 `install.sh` 比真正的 `deploy/install.sh` 少一行（`wd learn-order` 那一行），`test_deploy_files.py::test_deploy_doc_section_2_mirrors_install_sh` 因此是红的——在基线 `ea77832` 上就是这样，只是这台 Mac 上照例整文件排除 `test_deploy_files.py`，所以一直没被看见。搬 Linux 服务器之前要补上。
    - 只跑 `integration/test_media.py` + `test_demo.py` 这两个文件（前者先跑）时，`test_demo_is_public_and_lists_the_allow_listed_words_in_order` 会失败（后端同事判断是进程级的模板卡缓存）；在基线 `ea77832` 上同样复现，全量的默认顺序不触发，是绿的。
    - `PUT /api/settings` 的布尔字段接受 `"yes"` / `"no"` / `"on"` / `"off"` 这类字符串（pydantic 的宽松模式；实测 `image_word` 和 `show_images` 都是 200，`"maybe"` 和 `2` 是 400，`null` 表示不改）；前端只发真正的布尔值。
    - vitest 会通过 `node_modules` 软链把结果缓存写到线上检出的 `frontend/node_modules/.vite/vitest/`（只是缓存，11-06 起就在）。
13. **与本次有关、审查时发现但没有改的**：
    - 模糊预算不限滤镜一层套一层的深度，也不限滤镜区域的大小：卡在三个上限里的图，最坏量到 8 秒（16 层互相嵌套、滤镜区域是画布的几千倍）；正常平铺的 1–1.5 秒。要堵就再加一条滤镜区域的上限（样例最大是 -20% / -40% 到 140% / 180%）。
    - 线上自动生成的图走的默认清洗模式没有跟着收紧：`style` 和 `u\72l(…)` 这种转义的写法在那边照旧保留（一直如此，靠 `<img>` 和媒体接口的 CSP 挡着）。改它会动现有图的清洗结果，要单独决定。
    - 清洗器的一个老问题（基线就有）：同一个属性用两个都指向 SVG 命名空间的前缀各写一遍（`fill="red" s:fill="blue"`），输出里这个属性会出现两次，不是合法的 XML。图卡这边导入的结构校验会拒绝；线上自动生成的图遇到会存下一张坏图。
    - 导入的最后一行汇总原样打印清单里的 `model`；里面有控制字符时每张图都已经被拒绝并说明了原因，但这一行本身没有转义。
    - `tools/check` 的字形校验看不到的（只能看渲染图）：被裁剪路径裁掉的字母、被后画的图形盖住的字母、和底色一样的字母；连字符、撇号（`wap-<序号>`）不做字形、变形和出界检查。一个 `transform` 里夹着浏览器不认识的函数时，浏览器整条忽略，`check` 却按它认识的部分算。
    - 320 px 宽、系统字号调到 130% 以上时，设置页「例句译文」的分段按钮会把页面撑出横向滚动——和这次无关，开关那几行是好的。
14. **开关说明文字的措辞**（可以否决）。审查认为「记忆图卡」这个词在 App 的界面上别处都不出现，孩子和家长不知道指什么，所以说明文字从「关掉后，记忆图卡只显示画面」改成了「关掉后，带单词的配图只显示画面」（设计稿 §3.7 写着措辞可微调；标题「图片上显示单词」没动）。想改回去要动的地方：`frontend/src/i18n/zh.ts` 的 `imageWordHint`、`docs/FRONTEND.md` §8 的同一行、`docs/qa-study.md` §9 开关第一条、设计稿 §3.7 的两处、本文第 1 节，再删掉 `frontend/src/i18n/zh.test.ts` 里针对这句话的那一条测试。
15. **字母倾斜的尺度**（可以否决）。审查的建议是倾斜超过 5° 一律报错；实际做成了分级——5° 以内不提示，5°–15° 警告，超过 15° 报错（手册要求字母直立，但为了钩子让某个字母歪一点，是画图的人的判断）。想从严：`studio/tools/check.py` 里把 `TILT_MAX_DEG` 改成 `5.0`，自测里 10° 的那个用例相应从警告改成错误。
16. **`studio/cast/family/` 跟着这次提交进仓库**（可以否决）。11-13 下午做那 100 张的同事新增的大人角色设定（爸爸、妈妈、爷爷、李老师、路人：`CAST-family.md` 和 9 个 SVG 源文件，共 355 KB），第 4 节第 1 步的 `git add -A` 会把它一起提交；`studio/README.md` §2 有一行说明，`STUDIO.md` 的文件清单和本文开头的人物名单没有提它。不想让它进这次提交就先告诉我。
17. **本期不做**（设计稿 §4）：线上自动生成记忆图卡；其余 500 个小学词和其他阶段的重画；点图藏词之类图卡自带的互动；改写内容里的旧联想句。`README.md` 的功能列表也还没有提到记忆图卡。

## 7 上线记录（2026-11-14，Mac）

- 用户确认访问故障来自用错 IP，正确地址为 `http://192.168.1.250:8000`；无需修改网络或睡眠配置。
- 复用已提交的实现 `2bcbf60`。上线前在生产库副本演练迁移：125 项通过；后端相关测试 264 项、前端相关测试 80 项、契约、TypeScript、Vite 构建通过。服务已重启，schema 为 21，首页、健康接口、前端资源正常。
- `studio/cards/` 和 `studio/manifest.json` 已收齐 66 张可导入图片。新增的 56 张全部通过当前工具的清洗、结构、Andika 字形及 Chrome 渲染校验。8 张在 Claude 报错前已写出的成图另做了目视抽查。没有重新画图或发起 AI 请求。
- 导入前无正在运行或管理员指定的排队换图任务。空跑 `66 would be imported, 0 rejected`；实际 `66 imported, 0 rejected`；导入后空跑 `66 unchanged, 0 rejected`。生产库中恰有 66 张在用记忆图卡，文件校验和全部匹配，SQLite 完整性和外键检查通过。
- 用一个短期验证会话逐张检查真实服务：66 个词条 API、66 个完整 SVG、66 个 `?plain=1` SVG，合计 198 次 HTTP 200。隐藏单词版本均保留场景并移除单词层。验证会话已删除，既有会话未改变。未在手机或平板真机上复验。
- 美术质检尚未全部完成：`physical education` 的体育老师仍缺嘴和眉毛；`family`、`father` 仍有记录中的小缺陷。本次按用户要求应用已有成图，保留已保存的返修，不宣称已全部达到美术验收标准。
- 完整进度、缺失词清单见 `studio/recovery-20261114.json`。原图及工作流结果、56 份技术校验报告、112 张渲染图保存在 `/Users/sqin/word-dance-memory-cards/recovered-20261114/`。
- 上线前数据库备份：`/Users/sqin/word-dance-data/backups/word-dance-20261114-0704.db.gz`；迁移前备份：同目录 `pre-migrate-20-to-21.db.gz`。旧前端为 `frontend-releases/ea444c8`，旧代码为 `ea77832`。演练及导入日志：`/Users/sqin/wd-deploy-memory-5qizyw0t/`。撤图仍用第 5 节的 `images-import --undo studio/manifest.json`，当前清单覆盖全部 66 张。
