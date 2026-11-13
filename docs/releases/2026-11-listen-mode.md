# 发布说明 · 2026-11 · 磨耳朵（今日词汇的听力模式：跟着听 + 听写；无迁移）

基线 `main @ bba38fd`（schema 20，本次不变）；本次发布 = 今日页多一个入口「磨耳朵」，进入 `/listen` 后自动把今天的词一个接一个读出来：**跟着听**（单词 → 中文意思 → 例句 → 例句中文）和**听写**（只读单词、留时间写、播完对答案）。你说的「默写模式」在界面上叫「听写」。
设计契约是 `docs/LISTEN_MODE_DESIGN.md`（§3 产品规格、§4 接口；实现时和评审后的修订都已回写，文中标「修订」），接口契约 `docs/API.md` 76（`GET /media/audio` 多一个 `accent=zh-CN`）/ 新接口 123 `GET /api/today/playlist` / §9 `ServerFlags.audio_zh`、`ListenItem`、`ListenPlaylist` / §9.1，前端契约 `docs/FRONTEND.md` §2 / §5.3 / §5.9 / §6.4 / §8，配置 `docs/DEPLOY.md` §4 `WD_AUDIO_SAY_VOICE_ZH`，架构 `docs/DESIGN.md` §6.6，故障表 `docs/ops.md`，手测清单 `docs/qa-study.md` §8。
**没有迁移**、没有新依赖、不花 AI 预算、不动词库与已生成的内容。后端**要重启**，前端**要出新快照**；`.env` 不用改；平板和手机上的 App 不用重装（壳加载的是线上站点）。
状态（2026-11-12 深夜）：代码在工作区 `/Users/sqin/word-dance/.claude/worktrees/listen-mode`（分支 `listen-mode`），门禁全绿，**还没有提交，也没有上线**——线上检出 `/Users/sqin/word-dance` 一个字节都没动。独立评审确认的 16 处问题（3 处中等、13 处轻微）和真机浏览器实测发现的 1 处（重启后头几秒的 `audio_zh`）已经改完 16 处，剩下 1 处（iPhone 上点击之外的设备朗读）按决定只记为已知限制（第 6 节）；设计稿 §1 的 D1–D6 等你确认。
2026-11-13：sqin 确认「用磨耳朵 上线」（按钮名定为「磨耳朵」，其余按默认值），按第 4 节执行；上线记录见文末。

---

## 1 变更概览

| 面向 | 变化 |
|---|---|
| 学习者 | 今日页「开始学习 / 继续学习」下面多一个次级按钮「磨耳朵」（「今日完成」卡片里也有；今天只有推荐词、还没有批次、或今天的词全都已掌握 / 已移出生词库时不显示——入口和播放列表用同一条规则，不会点进去是空的）。点进去是整屏播放器，不用再点就开始。**跟着听**：每个词依次读单词、中文短释义、一个例句、例句的中文，正在读的那一行高亮；「例句」「中文」各有开关，两个都关就是只连读单词。**听写**：每个词读 1 / 2 / 3 遍（默认 2），每遍后停 3 / 5 / 8 / 12 秒（默认 5），屏幕上只有「第 i 个」，播完出「对答案」（序号、单词、🔊、释义；这一遍没读出来或被跳过的词带灰色的「没读」）。上一个 / 播放·暂停 / 下一个 / 重新开始，键盘空格和 ← / →，有耳机线控的设备也能用。读出来的中文是短释义（最多两个义项，不读 `n.` `v.`、不读括号里的内容），屏幕上仍是完整释义。连不上服务器时不会把剩下的词一口气跳完，而是停在当前这个词，提示「连不上服务器，点播放再试一次」 |
| 学习记录 | **不变**：磨耳朵不打分、不动复习间隔、不算今日完成、不算连续学习天数；接口 123 是纯读取，连批次都不会建 |
| 数据 | 无：不加表不加列。模式、两个开关、遍数、间隔存在这台设备的 `localStorage['wd.listen']`（平板和手机各记各的）。中文音频和英文音频一样缓存在 `$WD_DATA_DIR/audio/`，受 `WD_AUDIO_CACHE_MB` 管 |
| 接口 | 新接口 123 `GET /api/today/playlist` → `ListenPlaylist`（今天批次里的复习 / 新词 / 加练，批次顺序，一个词一行，已经不在生词库里的词不在里面：已掌握 / 已认识 / 已移出，按词当前的状态，不按条目的评分）；76 `GET /media/audio` 的 `accent` 多一个取值 `zh-CN`（自己的文本规则：1–300 个字符、至少一个汉字；除汉字、中文标点和英文规则允许的字符外另放行 `℃ ° ％ ￥ ¥ 〇`）；`ServerFlags.audio_zh`（服务器现在能读中文；启动后头两三秒语音还没解析完时按乐观值给 `true`）。`schemas.py` ↔ `types.ts` ↔ API.md §9 一次契约变更，接口目录 1–123 |
| 运维 | 新配置 `WD_AUDIO_SAY_VOICE_ZH`（默认空 = 自动选装好的最好的 `zh_CN` 语音，这台 Mac 上是 Tingting；写了就必须是 `say -v '?'` 列出的中文语音、且不是 Eloquence 语音，否则按没有中文语音处理）；`wd audio-voices` 最后多一行 `zh-CN → …`；`wd audio-probe --accent zh-CN`；`wd check providers` 多一行 `audio zh-CN: …`；启动日志事件 `audio_voice_zh` / `audio_voice_zh_missing`。上线后 `audio_key` 会变一次（中文语音进了指纹），浏览器会重新下载发音片段，服务器上的英文缓存不受影响（英文片段的缓存键没变） |
| 不变 | 学习卡、筛词、🔊 按钮和自动发音（仍是设备语音优先）、英文发音的选音与预生成命令（`audio-prewarm` / `audio-texts` 不产生中文）、`user_settings.accent`（仍只有两个英文口音）、APK |

**给你的两句话。** 这是「只能听的时候也能学」的第一版：家里的鸿蒙平板没有任何本机语音，所以中文也由这台 Mac 来读（系统自带的 Tingting，约 0.5 秒一条，读过一次就走缓存）；英文还是 Ava / Serena。全库的内容不用重新生成——读什么是服务器按规则从已有的释义和例句里现算出来的。本机门禁、对真实 `say` 的核对、桌面无头 Chrome 里的播放链都过了，但**没有在任何真机上实际听过**：平板上「中文出声、连播不用再点、熄屏后怎样」这三项要你上线后按 `docs/qa-study.md` §8 走一遍。

## 2 机制

- **播放列表（后端，`backend/wd/services/listen.py`，接口 123）**：取用户当地日期的批次（`building` / `ready` / `published` 都算，不等内容生成），沿用今日页的过期条目规则；只要 `review` / `new` / `extra`，去掉现在已经不在生词库里的词（`user_words.state` 不是 `new` / `learning`：已掌握、已认识、已移出——看词当前的状态，不看条目的评分，所以评完分之后又在单词页标「已掌握」的词也不播，重新加回生词库的词回到列表），按 `position, id` 排，同一个词只留第一条；今天已经学过的照样在里面（`done: true`）。今日页的入口（`TodayPage.tsx`）用的是同一条规则，从 `GET /api/today` 已有的条目上算。每个词现算四段要读的文字，**每一段都先过一遍发音接口自己的文本规则**，过不了的给 `null`，播放器跳过那一段：`spoken_en`（词头，`sb.` → somebody、`sth.` → something、`sb's` → somebody's）、`gloss_zh`（下一条）、`sentence_en` / `sentence_zh`（内容里第一个能读的例句和它的译文）。屏幕上显示的 `meaning_zh` 是内容里的释义，没有内容时退回词典里主词性的那一行。
- **短释义规则（`speakable_gloss`，API.md §9.1）**：先去掉各种括号及其内容（圆括号全角半角混配的一对也算一对），再按 `；` `;`、换行、`，` `,` `、`、斜杠和词性组边界切成义项，每个义项去掉开头的词性标签和首尾符号，发音规则不接受的义项单独丢弃，去重，取前两个用「，」连起来，超过 40 个字符只留第一个。`v. 分享；共用 n. 一份；股份` → `分享，共用`；`adv./prep. 在船(飞机、车)上;上船(车、飞机)` → `在船上，上船`；`国内生产总值（gross domestic product 的缩写）` → `国内生产总值`；`vt. 使（某人)高兴, 取悦` → `使高兴，取悦`。集成时比设计稿多做了两处（第 3 节有实测依据）：词性标签不再是一张固定的表——`n.` `v.` `a.` 加上任何 2–7 个小写字母带点的缩写都算（`phr.` `excl.` 这类模型可能写出来、表里没有的标签原来会被读成「p h r 照顾」）；斜杠也算义项分隔（Tingting 会把 `/` 读成「斜杠」）。
- **中文语音（后端，`backend/wd/audio.py`）**：`accent=zh-CN` 只有 `say` 提供方支持。选音与英文完全分开，互不回退：`WD_AUDIO_SAY_VOICE_ZH` 优先（必须是 `say -v '?'` 列出的中文语音，且不是 Eloquence，否则不探测、直接按没有中文语音处理——实测 `say` 并不解析列表里那几个 `zh_CN` 的 Eloquence 名字，会用 Tingting 顶替；Fred / Albert / Kathy 这几个老的英文语音读中文是 8–11 秒的噪音），否则在 `say -v '?'` 列出的 `zh_CN` 语音里挑档位最高的（高级 > 增强 > 普通），不选 Eloquence 那几个（`Eddy (中文（中国大陆）)` 等）。探测方式也和英文不同，因为在这台 Mac 上实测到两件事：英文语音读中文不报错、只写出 4608 字节的空音频；系统对不认识的语音名的回退语音恰好就是 Tingting，所以「和不存在的名字比较」会把 Tingting 判成没解析到。于是改成看大小：候选语音读「你好，世界」的 AIFF 不小于 8192 字节才算会读中文；每次中文合成也守同一条线，空音频不会进缓存。没有中文语音是正常状态而不是故障：解析完成后 `audio_zh` 为假，中文请求答 503 `failed`，英文不受影响。**启动后头两三秒**语音还没解析完，这时 `audio_zh` 给的是乐观的真（页面只在加载时读一次 `/me`，平板又没有本机语音，这几秒里读到假就整场没有中文）；这时来要中文的请求自己把语音解析出来。`youdao` / `bailian` 对中文答 `failed`，`cache`（将来的 Linux 服务器）答 `missing`。
- **连播（前端，`frontend/src/audio/utter.ts` + `listen/player.ts`）**：平时的 🔊 是设备语音优先，而且浏览器语音没有「读完了」的信号，没法串起来。磨耳朵反过来：**先播服务器的音频**（一个共用的 `<audio>` 元素一条接一条，各设备声音一致，平板上的中文只有这一条路），服务器忙就等 1.5 秒再问一次，连不上就每 1.5 秒再问一次、最多再问两次（一次普通的服务重启不用点任何东西就过去了），给不出来才退到 App 壳的系统语音、再退到浏览器语音（带看门狗），都不行就返回「没读出来」，播放器跳过这一段并计数，不卡住。**连不上服务器而设备自己也读不了**（平板）时不跳，停在当前词并提示「连不上服务器，点播放再试一次」——否则剩下的词会在一两秒内被跳完，听写会提前跳到对答案。浏览器自己把声音停掉（来电、别的 App 抢走音频焦点、拔耳机）时页面回到「点一下开始播放」，而不是显示着「暂停」却没有声音；一条音频 20 秒没有开始播放按连不上处理。播放器是纯状态机：段间停 350 ms、词间停 900 ms；暂停、跳转、改选项都让旧的播放链作废，再从当前词的第一段读起；浏览器要求先点一下才出声时（iPhone Safari）停在「点一下开始播放」。一条中文音频被服务器答 `failed` / `invalid` 之后，这个页面本次不再向服务器要中文（改用设备语音；设备也没有就提示「这台设备读不了中文，只播放英文」）；中途才发现读不了中文（平板 App 事先看不出来）时不再把当前词从头重读，也不留「有 1 段没能读出来」。
- **页面（`frontend/src/pages/ListenPage.tsx`）**：`/listen` 和 `/study` 一样是整屏、不带导航、要求已完成引导；听写时单词、音标、释义都不在页面里（锁屏上的标题也只写「第 i 个」），播完才出现，「对答案」给这一遍没读出来或被跳过的词标「没读」；加载失败时除了「重试」仍有「回到今日」；播完时落空的键盘焦点移到结束页标题；播放期间在支持的浏览器里申请屏幕常亮、注册耳机 / 锁屏控件，没有这些接口就什么也不做；离开页面立即停声，切到后台不暂停。文案全部在 `zh.ts` 的 `listen` 块和 `today.listen`（评审后新增 `listen.offline`、`listen.unread` 两条），FRONTEND §8 逐行镜像。

## 3 验收（提交前门禁，2026-11-12 深夜，这台 Mac，工作区 `listen-mode`，评审修复之后重跑）

- **pytest 全量**：**2924 passed / 3 skipped / 1 deselected**（6 分 03 秒；Mac 上照例排除 `test_deploy_files.py` 和 `test_config.py::test_defaults_without_environment`；`test_deploy_files.py` 里和这次有关的 `env_example` 四条单独跑过，全过）。新增 `tests/unit/test_listen.py`（84 条：短释义表含混配括号、词头、例句、播放列表的去重 / 不含推荐词 / 按词当前的状态 / 过期条目 / 无批次 / 回退）；`test_audio.py`（177 条）、`test_audio_api.py`、`test_today_flow.py`、`test_auth.py`、`test_api_schemas.py`、`test_cli.py`、`test_config.py`、`test_diag.py` 各有增补。说明：`--deselect` 要写成 `tests/unit/test_config.py::test_defaults_without_environment`（pytest 的根目录是 `backend/`，带 `backend/` 前缀的写法匹配不到）。
- **契约**：`scripts/check_contract.py -q` → `contract OK: no property-name or literal-union mismatch`（只剩一直就有的 9 条可空性 note）；API.md §9 == `types.ts`、FRONTEND §8 == `zh.ts` 由 `test_docs_contract.py` 钉住，在全量里通过。
- **前端**：`npm run typecheck` 通过；vitest **67 个文件 / 644 条**全过（新增 `audio/utter.test.ts`、`audio/utter.server.test.ts`、`listen/player.test.ts`、`listen/screenAwake.test.ts`、`listen/mediaSession.test.ts`、`pages/ListenPage.test.tsx`、`pages/TodayPage.test.tsx`）；`npm run lint` → `copy check OK`；`npm run build` 通过，首屏主包 `index` 350.58 kB（**gzip 115.63 kB**），`ListenPage` 是独立的懒加载块 17.01 kB（**gzip 5.60 kB**），另有它的样式 4.98 kB（gzip 1.28 kB）。
- **评审修复逐条有会失败的测试**：17 项里 16 项改了代码，每一项都把修复临时撤掉重跑了它的测试——前端 26 处、后端 11 处改动，每一处都至少有一条测试失败，撤掉的改动随后逐字节还原（`cmp` 核对过）。例如：把「连不上」重新当成「读不了」→ `utter` / 播放器 / 页面的 5 条失败；去掉 `pause` 事件的两个判断条件中的任何一个 → 「自然播完不算被暂停」那条失败；把入口规则换回计数、换成 `result !== 'master'`、或去掉「推荐词不算」→ 今日页那条失败；`speaks_zh` 改回悲观、改成恒真、改成去拿列表的锁、改成调用 `say`，各自都有测试失败。
- **两半接在一起（进程内，TestClient + 真实 `say`，临时数据目录，不开端口；评审修复后重跑）**：启动 0.04 秒后的第一次 `/api/auth/me` 里 `audio_zh` 已经为真（语音还没解析完时的乐观值，`audio_key` 是占位值）；不等预热，直接按这个页面会发的请求去要第一条中文片段：启动后 2.1 秒答 200（7614 字节；不等预热结束，也不用刷新）；预热结束后 `audio_zh` 仍为真、`audio_key` 定下来不再变。把 `WD_AUDIO_SAY_VOICE_ZH` 设成 `Fred`（列表里有的英文语音，读中文是噪音）：这个覆盖项被拒绝且没有被探测，中文请求答一次 503 `failed`，随后 `audio_zh` 为假，英文照常。带 `℃ ° ％ ￥ ¥ 〇` 的六句中文都由 Tingting 读出来（200），`1+1=2 等于二`、`他得了A+。`、`3~5个`、单独的 `〇` / `℃` 仍是 400。**入口规则和播放列表逐个状态对过**：把今日页的判断式照抄到 `GET /api/today` 的条目上，和 `GET /api/today/playlist` 的行比较——新批次（5 个词）、卡片里评「已掌握」、单词页标「已掌握」、移出生词库、标「已认识」、全部离开生词库（入口隐藏 ↔ 列表为空；旧的计数规则这时仍会显示入口）、重新加回一个（入口回来 ↔ 列表一行、`done: true`），七个状态两边指的都是同一批词（「评过分之后再标已掌握」要等 10 分钟那一步，由 `test_today_flow.py` 用冻结的时钟覆盖）。
- **真实 `say`（临时数据目录，没有碰线上数据和线上服务；首次集成时所测，选音部分修复后由后端同事重测）**：预热 2.3 秒左右，选音 `en-US → Ava (Premium)`、`en-GB → Serena (Premium)`、`zh-CN → Tingting`；`say_resolves('Tingting')` 为假而 `say_speaks_zh('Tingting')` 为真（就是上面说的回退语音的情形），`say_speaks_zh('Ava (Premium)')` 为假。「月亮」约 0.5 秒合成 7614 字节的 m4a（AIFF 26204 字节），「今晚的月亮很亮。」约 0.5 秒 14283 字节（AIFF 71908 字节），两条都在缓存目录里、再查即命中；对照：空音频的 AIFF 是 4608 字节、转成 m4a 是 4108 字节，门槛 8192。绕过规则直接让 Ava 读「月亮」，得到 `silent clip: … wrote 4608 bytes of AIFF`，没有写入缓存。覆盖项：只有 Tingting（默认）、Meijia、Sinji 被接受；Flo、Eddy（两个都是 `zh_CN` 的 Eloquence 行）、Fred、Albert、Kathy、Ava (Premium)、Samantha、`tingting`、`Tingtin` 都被拒绝。预热期间 `speaks_zh` 轮询 106 次全部为真，最慢一次 0.14 毫秒（不等 `say`）。`wd audio-voices` 最后一行 `zh-CN → Tingting (the best installed zh_CN voice; WD_AUDIO_SAY_VOICE_ZH overrides)`，退出码 0；`wd audio-probe --accent zh-CN` 正常。
- **桌面无头 Chrome（静音，对着临时端口上的假服务器，前端同事在修复时所测；不是真机）**：三条音频靠自然播完连起来、没有误判成「被暂停」；23 秒的音频完整播完（看门狗只管 20 秒内没开始播放的）；从外面对 `<audio>` 调 `pause()` → 页面状态 `blocked`，再点播放读到底；自己的上一个 / 下一个 / 暂停不会被误判；服务器停 2 秒 → 不用点、自己接上；一直连不上 → 3.06 秒后停在当前词（`paused` + `offline`），再点一次 0.05 秒内就有答复，恢复后读到底；挂住的请求 → 20 秒后按连不上处理、只问了一次。
- **短释义过一遍仓库里的种子**（9618 个词的词典回退行）：9335 个不同的短释义，没有一个以词性标签开头，发音规则全部接受；3 个词派生不出来（都是纯交叉引用，如 `vt.<主英>=familiarize`），词头没有一个被拒。挑了 214 条（含全部 154 条夹着字母、数字或省略号的）让 Tingting 真读了一遍：最小的 AIFF 24354 字节，没有空音频。括号规则改动前后，种子的 9618 行逐行相同（评审修复后重跑：9335 / 3 / 0 这几个数没有变）。
- **内容库的一份导出**（临时目录里 11-12 21:43 的 `live-words.json`，9380 个词、37348 条例句译文；主会话在 11-12 21:43 用只读连接（`PRAGMA query_only`）从线上库导出的全部在用释义和例句，线上数据没有改动）：`meaning_zh` 里全角半角混配的括号 0 处，短释义规则改动前后 0 条不同、0 条派生不出来（两条以拉丁字母开头：`T恤，短袖圆领衫`、`X光，X光片`，都是对的）；例句译文里没有一条带 `℃ ° ％ ￥ ¥ 〇`，被中文规则拒绝的 7 条（`π`、`Ctrl+Z`、`3x+2`、`*`、`12÷3=4`、`H₂O` 这类）没有一条是被选中播放的那一句。也就是说混配括号和数量符号这两处修的是今后的内容，对现在的词库没有影响。
- **集成时发现并修掉的两处「会读错」**（用 `afinfo` 量 Tingting 的朗读时长）：① `相连/联系` 读出来 1.54 秒，和「相连斜杠联系」一模一样（不带斜杠 1.05 秒）——斜杠会被读成「斜杠」，现在斜杠算义项分隔（种子里受影响的 10 行都变成了「…，…」）；② `phr. 照顾` 2.05 秒，而「照顾」只有 0.46 秒——固定标签表之外的标签会被逐字母读出来，现在按写法识别。省略号（`与...相似`、`与…相似`）只是 0.3 秒的停顿，没有动它。
- **端到端冒烟**（`scripts/smoke.py`，工作区的后端，临时数据目录，端口 8010 / 8011，真实 `say`；主会话在实现后、评审修复后各跑一遍）：35 步全过，其中包括新增的「磨耳朵播放列表」一步和发音一步里的 `zh-CN` 断言。
- **真实浏览器**（无头 Chrome 经调试协议驱动，对着 8011 端口的临时实例和工作区构建的前端，真实 `say`；评审修复后重跑）：今日页出现「磨耳朵」→ 点进去不用再点就开始 → 依次请求单词（`en-US`）、中文短释义（`zh-CN`）、例句、例句译文，全部 206，读完一个词自动进下一个 → 切到「听写」后页面只有「第 i 个」→ 暂停的 5 秒里没有任何音频请求 → 跳到末尾出现「对答案」，被跳过的词带「没读」。服务刚启动（语音还没解析完）就打开页面：`/api/auth/me` 的 `audio_zh` 已为真，中文片段照常由服务器读出，不用刷新。评审修复前同一个实测里，这种情况下整场没有请求过一条中文——这就是第 6 节之外已经改掉的那一处。
- **没有跑的**：任何真机（平板、手机）。手测清单 `docs/qa-study.md` §8。

## 4 上线步骤（Mac launchd；提交 → 合入线上检出 → 前端快照 → 重启；无迁移）

这次和以往不同的地方：改动**不在线上检出里**。它还没有提交，放在工作区 `/Users/sqin/word-dance/.claude/worktrees/listen-mode`（分支 `listen-mode`，和 `main` 同在 `bba38fd`）；线上服务跑的是 `/Users/sqin/word-dance`（分支 `main`）。`main` 比 `origin/main` 超前 44 个提交，`listen-mode` 只在本机，所以**不是 `git pull`**（它只会答 Already up to date，然后重启的还是旧代码），而是在线上检出里把本地分支快进合并进来——**那一刻线上的文件才变**。下面的命令可以原样粘贴；每一段开头都重新写了三个变量，换终端也不会丢：`W` 工作区、`L` 线上检出、`D` 数据目录。

0. **确认**设计稿 §1 的 D1–D6（都有默认值，不确认就是默认值）。
1. **提交**（只动工作区的分支，线上不变）：
   ```sh
   W=/Users/sqin/word-dance/.claude/worktrees/listen-mode; L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
   cd $W && git status --short        # 只应有这次的文件：50 个修改、12 项未跟踪（`.venv` 和 `frontend/node_modules` 是指向线上检出的软链，已被忽略，不会出现）
   git add -A && git -c user.name=sqin -c user.email=sqin@nvidia.com commit -m "feat(listen): 磨耳朵 — the audio-first /listen page over today's words (跟着听 / 听写), endpoint 123 GET /api/today/playlist, Chinese clips from GET /media/audio with accent=zh-CN, ServerFlags.audio_zh"
   git status --short && git log --oneline -2       # 工作区干净；最上面是新提交，下面是 bba38fd
   ```
   想补跑端到端冒烟的话在这里跑：`cd $W && make smoke`（Makefile 自己把 `PYTHONPATH` 指到工作区的 `backend/`；临时数据目录、端口 8010，不碰线上）。提交前已经跑过（第 3 节），这里是想再确认一遍时用的。
2. **等后台空下来**（11-11 开始的全库预生成；合并和重启都放在它之后，免得打断正在跑的那一批，也免得看守脚本派生的 `wd` 命令和服务进程用的不是同一份代码）：
   ```sh
   D=/Users/sqin/word-dance-data
   tail -3 ~/Library/Logs/word-dance/prewarm-all.log       # 最后有一行 `watcher done` = 预生成已收尾（它自己会重启一次服务）
   grep -c TEMPORARY $D/.env                                # 0 = 临时调高的额度已经还原
   sqlite3 -readonly -cmd '.timeout 5000' $D/word-dance.db "SELECT type, status, COUNT(*) FROM jobs WHERE status IN ('queued','running') GROUP BY 1, 2"
   ```
   最后一条没有 `running` 的行再往下走（`queued` 的行留在库里，重启后照常接着跑）。
3. **合入线上检出，出前端快照**（从这里到第 4 步的重启连着做，一两分钟：`git merge` 之后线上检出里的文件已经是新代码，而服务进程里还是旧代码）：
   ```sh
   W=/Users/sqin/word-dance/.claude/worktrees/listen-mode; L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
   cd $L && git status --short && git log --oneline -1      # 期望：没有任何输出的改动；HEAD 是 bba38fd
   git merge --ff-only listen-mode                           # ← 线上检出在这一刻变成新代码；不需要 git pull
   SHA=$(git rev-parse --short HEAD); echo "new $SHA"; readlink $D/frontend | tee $D/frontend.prev             # 上线前的快照（frontend-releases/<旧 sha>）：打印出来并记在 $D/frontend.prev 里，回滚要用
   cd $L/frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build -- --outDir $D/frontend-releases/$SHA.new --emptyOutDir && cd $L
   mkdir -p $D/frontend-releases/$SHA.new/dl && cp -p $D/frontend/dl/*.apk $D/frontend-releases/$SHA.new/dl/   # 三个 APK 从当前快照照抄
   grep -rl 'today/playlist' $D/frontend-releases/$SHA.new/assets | head -1                                     # 有输出 = 新快照里有磨耳朵
   mv $D/frontend-releases/$SHA.new $D/frontend-releases/$SHA && ln -sfn frontend-releases/$SHA $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"   # BSD mv 没有 -T
   ```
   `git merge --ff-only` 如果拒绝（`main` 在这期间多了提交）：`cd $W && git rebase main`，重跑第 3 节的门禁，再回到这一步。`git status --short` 如果有输出（线上检出里有没提交的改动），先弄清楚是什么再合并。没有新依赖，不用 `npm ci`。进程在启动时才解析 `$D/frontend` 这个软链，所以快照切过去之后、重启之前，线上仍是旧前端配旧后端。
4. **重启**：`launchctl kickstart -k gui/$(id -u)/com.word-dance.server`。没有迁移，不会写迁移前快照；以往 2–3 秒内健康。
5. **验证**：
   ```sh
   L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
   curl -s --noproxy '*' http://127.0.0.1:8000/api/health                                              # "status":"ok"
   grep -E 'say voice for|no say voice for' ~/Library/Logs/word-dance/word-dance.log | tail -3          # 预热线程的三行：en-US、en-GB，再加 `say voice for zh-CN: Tingting`
   WD_DATA_DIR=$D $L/.venv/bin/wd audio-voices | tail -1                                                # zh-CN → Tingting (the best installed zh_CN voice; …)
   curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/today/playlist      # 401（未登录）；404 = 重启的还是旧代码
   readlink $D/frontend                                                                                 # frontend-releases/<新的 SHA>
   ```
   日志里如果是 `no say voice for zh-CN: …`（事件 `audio_voice_zh_missing`），按 `docs/ops.md` 故障表里「磨耳朵只读英文」那一行处理。然后在浏览器里：登录后 `GET /api/auth/me` 的 `server.audio_zh` 为 `true`（重启后头两三秒语音还没解析完时也是 `true`，那是乐观值；以上面日志里 `zh-CN` 那一行为准）；今日页出现「磨耳朵」，点进去自动开始读，中文有声音。
6. 平板 App 不用重装，重新打开即可。按 `docs/qa-study.md` §8 走一遍，把平板上的三项（中文出声、连播不用再点、熄屏后的表现）记进本文件的上线记录。
7. 不需要：迁移、导种子、`wd learn-order`、AI、改 `.env`。想换更好的中文语音：系统设置 → 辅助功能 → 朗读内容 → 系统语音 → 管理语音 → 中文（中国大陆），下载后重启服务即自动换用（或在 `.env` 里写 `WD_AUDIO_SAY_VOICE_ZH`，写的必须是 `say -v '?'` 那一列里的中文语音名，Eloquence 的不行）；旧的中文片段会按新语音重新生成。

## 5 回滚

```sh
L=/Users/sqin/word-dance; D=/Users/sqin/word-dance-data
PREV=$(cat $D/frontend.prev); echo $PREV; ls -d $D/$PREV   # 上线第 3 步记下的旧快照（frontend-releases/<旧 sha>），目录还在
cd $L && git checkout bba38fd                                # 线上检出回到上线前的代码（分离 HEAD；main 仍指着新提交，重新上线时 git checkout main）
ln -sfn $PREV $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"
launchctl kickstart -k gui/$(id -u)/com.word-dance.server
curl -s --noproxy '*' http://127.0.0.1:8000/api/health && curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/today/playlist   # ok；404 = 已是旧代码
```

没有迁移，没有数据风险：`audio/` 里多出来的中文片段只是缓存，留着无害（受 `WD_AUDIO_CACHE_MB` 上限管，最久没播的先清）；设备上的 `localStorage['wd.listen']` 留着无害；`audio_key` 会再变一次（浏览器再重新下载一遍发音片段）；`.env` 里如果写了 `WD_AUDIO_SAY_VOICE_ZH`，旧代码不认识这个变量、也不会因为它拒绝启动。只在第 3 步合并之后、第 4 步重启之前想反悔：上面的命令去掉 `launchctl` 那一行即可（`git checkout bba38fd`，软链指回 `$PREV`），不用重启。`$D/frontend.prev` 只是一行文本，确认不回滚之后可以删。

## 6 未决（不阻塞）

- **真机没有验证**：平板 APK 里一个 `<audio>` 连续换源播放、熄屏后是否继续，都只是从 Capacitor 源码和浏览器规范推出来的。局域网 `http://` 下网页不能保持屏幕常亮（`navigator.wakeLock` 只在 https 下有），平板会按系统设置熄屏；临时办法是把休眠时间调长，根治要 https 或改 APK（常亮 / 前台服务），都不在本期。浏览器自己暂停 `<audio>`（切 App、来电、拔耳机）在哪些设备上发生，也只在桌面 Chrome 里模拟过。
- **iPhone / iPad 上的设备朗读**（评审第 7 条，决定本期只记录、不改代码；设计稿 §7.10，手工清单 qa-study §8「手机浏览器」）：iOS 不让网页在点击之外开始 `speechSynthesis` 朗读。服务器不读中文而 iPhone 自己有中文语音时（一条中文音频失败过之后的本次会话；将来 `cache` 提供方的服务器上是常态），中文段在 iPhone 的浏览器里没有声音——每段静默 5–10 秒后被跳过并计数，直到有一下点击把朗读解锁（本次打开网页后点过任何 🔊 就不受影响）。没有真机，修法（在点击里先 `speak` 一条空的朗读）要在真机上确认不会打断同一下点击里开始的音频才能上。**上 Linux 服务器之前必须解决。**
- **重启后的头两三秒**（已改，原先列在这里）：中文语音还没解析完，`audio_key` 还是占位值；`audio_zh` 这时按乐观值给 `true`，这几秒里打开的页面不用刷新，第一条中文片段的请求自己完成解析（实测启动后 2.1 秒拿到）。只有服务器确实没有中文语音时，这样的页面会多要一次中文、得到 503 `failed`，然后本次会话只读英文。
- **连不上服务器时**：重试只覆盖 3 秒（第 0、1.5、3 秒各问一次），重启得比这慢就会停在当前词，点一下播放继续；有英文语音而没有中文语音的浏览器，断网时会停在第一段中文上（以前是只读英文、中文逐段计数），想只听英文可以关掉「中文」；诊断用的那次请求本身没有超时，音频已经开始播放之后中途断流靠浏览器的 `error` 事件。服务器搬到反向代理后面以后，重启期间代理答的 502 / 504 现在会被当成 `failed`（中文还会因此整场关掉），到时要映射成「连不上」。
- **浏览器自己暂停之后**：页面回到「点一下开始播放」。系统如果随后自己恢复了那段声音（短暂的打断），会多响半句、然后停住等你点——修复之前这种短暂的打断会自己接上，长久的打断则卡在「暂停」图标上；现在两种都是点一下继续（设计稿 §7.11）。
- **一条中文失败就整场关掉**：服务器对任何一条中文音频答 `failed`（包括 `say` 偶发超时），这个页面直到刷新都不再向服务器要中文，平板上之后就只有英文。这是设计稿 §6.1 的规则，先照做；真机上遇到过再改成「连续两条失败才关」。（关掉时不再重读当前词，也不计数。）
- **线上内容库的释义**：线上数据没有读过；第 3 节那份导出（9380 个词）上规则全部走通，但它不是这一轮导出的。上线前想再确认一遍，就在数据库的只读副本上把全部 `meaning_zh` 过一遍 `speakable_gloss`，列出派生不出来的和仍以拉丁字母开头的，数一下匹配 `（[^（）()]*\)|\([^（）()]*）` 的条数（全角半角混配的括号），并把每个词选中的例句译文过一遍中文文本规则。已知的边角：词典回退行偶尔不自然（`normalise的变形`、`Mississippi 美国密西西比州州名`）；释义里夹的 `sb.` 会被读成字母；不带点的标签（`idiom 加油`）识别不了；纯交叉引用的释义派生不出来，那一段直接跳过；`〈〉` `［］` `〔〕` 这三种括号不认识（含它们的义项整个跳过，不会读错）；全角数字 / 字母、`・` `•` `‧`、`+` `=` `~` 仍被中文文本规则拒绝（带它们的译文那一句不读中文）。
- **中文音质与首播延迟**：Tingting 是普通档语音，句子里夹的英文读得生硬；中文没有预生成，每条第一次播放多等约 0.5 秒。
- **上 Linux 服务器之前**：`cache` / `bailian` / `youdao` 都没有中文，`audio_zh` 恒为假，鸿蒙平板上会没有中文。要先做中文的预生成和 `cache` 的中文（设计稿 §8），或者百炼的中文语音；连同上面 iPhone 的那一条和 502 / 504 的映射。
- **授权**：`say` 的语音（包括 Tingting）按 macOS 许可只能非商用，和英文语音同一条限制；商用前要换云端语音。
- **键盘与焦点**：焦点停在模式 / 遍数 / 间隔这几个分段控件上时，← / → 切的是控件的选项而不是上一个 / 下一个（分段控件自己的键盘规则）；点一下页面空白处即可。「再听一遍」/「再听写一遍」/「点一下开始播放」按下后按钮消失，焦点落到 `<body>`，没有移回播放键；加载中的骨架屏没有顶栏（只是一闪）。中途发现读不了中文时，「有 1 段没能读出来」可能闪现一两帧才消失。
- **`scripts/smoke.py` 的中文那一步**在 `say -v '?'` 本身读不出来的机器上会报「`audio_zh` 为真而中文答 503」（那种机器上英文那一步已经先失败了）；这台 Mac 上两处新增都跑过（第 3 节）。
- **与本次无关、但门禁里会碰到的**：`integration/test_worker.py::test_worker_threads_start_stop_join` 会连真实的 Wikimedia，在办公室网络 TLS 被重置时偶发失败（这一轮的全量里没有出现）；vitest 会通过 `node_modules` 软链把结果缓存写到线上检出的 `frontend/node_modules/.vite/vitest/`（只是缓存，11-06 起就在）。
- **本期不做**（设计稿 §8）：计入学习统计或连续天数、听写批改与错词回写、昨天的词汇 / 任意词表的磨耳朵、语速选项、循环播放、睡眠定时、APK 改动。`README.md` 的功能列表和 `manifest.webmanifest` 的快捷方式也还没有提到磨耳朵。
