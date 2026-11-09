# 发布说明 · 2026-11 · 服务器发音兜底（`GET /media/audio`）

基线 `main @ c4574cd`（手机 App 壳已上线）。本次发布 = 后端新增发音接口与三条配置、前端的三级发音路线、冒烟脚本加固、文档与手册更新；无数据库迁移（schema 仍为 17），重启即生效。

## 1 起因

- 11-09 晚，家里的华为平板装上 APK 后点发音没有声音，一直提示「语音还没准备好，请再点一次」。服务器 `sessions` 表记下的 UA 是 `Linux; Android 16; SLG-W50 Build/HUAWEISLG-W50; wv … Chrome/114`，同一台机器 11-05 用华为浏览器登录时的 UA 是 `OpenHarmony 7.0 … ArkWeb … HuaweiBrowser`：这是一台鸿蒙 NEXT 平板，APK 跑在它的安卓兼容环境里（华为应用市场里「卓易通」一类的容器；装的具体是哪一个没有核对）。
- 在那个环境里 TTS 插件拿不到任何系统语音引擎。`@capacitor-community/text-to-speech` 只在插件加载时初始化一次引擎，失败后 `isAvailable()` 永远为假，每次 `speak()` 都以 `UNAVAILABLE` 拒绝——网站侧把这个码翻译成「还没准备好，请再点一次」，再点也没用。网页版在华为浏览器里能出声，因为 ArkWeb 用的是鸿蒙自己的语音。
- 同类设备不止这一台：Android WebView 本身没有 `speechSynthesis`，不少国产 ROM 没有英文语音。所以修在服务器侧：没有英文语音的设备改放服务器生成的发音。

## 2 变更

- **后端** `wd/audio.py` + `routers/audio.py`：`GET /media/audio?text=<词 | 短语 | 例句>&accent=en-US|en-GB`（API.md 76）。登录即可用；文本 1–300 个拉丁字母 / 数字 / 空格 / 英文句子里会出现的标点（直引号与弯引号、连字符 / 短横 / 长横、省略号、`$ % & @ /`），不以连字符开头，其余 400——以引号或括号开头的对话体例句能放；首次合成后按「提供方 + 语音 + 口音 + 文本」内容寻址缓存在 `$WD_DATA_DIR/audio/<2hex>/<sha256>`（0600，原子落盘，删目录只是重新合成），缓存上限 `WD_AUDIO_CACHE_MB`（默认 256 MB，超过时先删最久没播放的）；`Cache-Control: private, max-age=604800`、`Accept-Ranges`（Range 请求答 206，前端用 `<audio>` 元素直接播这个地址）；每用户每分钟 60 次缓存未命中（命中不计），合成最多两路并行、最多六个请求排队、等 8 秒即 503 `busy`。放在 `/media/` 下是因为 `/api/*` 的中间件会盖 `no-store`。失败日志只记文本长度，文本本身在 DEBUG。
- **提供方** `WD_AUDIO_PROVIDER`（DEPLOY §4）：`say` = macOS `/usr/bin/say`（文本走 stdin，白名单环境变量，30 秒超时并杀进程组）+ `afconvert` 转 AAC（每词约 8 KB；`say` 自己输出的 m4a 有 30 KB 容器开销）；语音取 `WD_AUDIO_SAY_VOICE` 或按口音在已安装语音里选（Ava / Zoe / Allison / Samantha … 与 Serena / Kate / … Daniel，高级 > 增强 > 普通，玩具音与 Eloquence 音永不选）。`say -v` 对不认识的名字也返回 0 并悄悄换一个固定的声音，所以每个候选语音每进程探测一次（和一个必然不存在的名字比输出），写错的 `WD_AUDIO_SAY_VOICE` 答 503 `failed` 并记日志，不会缓存一堆别的声音。`youdao` = 有道词典公开发音接口（非官方，mp3，需显式开启；每个没缓存的文本都会发给它，User-Agent 不带运营者邮箱 / 网址，不走环境里的代理，最多 2 MB）；`off`；默认 `auto` = 主机有 `/usr/bin/say` 就用 `say`，否则 `off`——**Linux 服务器不设置就没有兜底**。启动日志（事件 `audio_provider`）写明实际生效的提供方。
- **契约**：`ServerFlags.audio`（`GET /api/auth/me`）告诉前端服务器有没有提供方；错误码 `audio_unavailable`（503，`details.reason` = `off` / `busy` / `failed`）；API.md §1 的「GET 不限速」加上了 76 这一例外。
- **前端** `hooks/useSpeech.ts` 每次按 `speechRoute` 选路：壳里走系统 TTS 插件；浏览器列出英文语音（或语音表还没加载出来）就用浏览器；否则服务器有提供方就放服务器音频；插件拒绝（无引擎 / 无英文语音 / 出错）时同样回退到服务器音频。`audio/serverAudio.ts` 把 `GET /media/audio?…` 直接设为同一个 `<audio>` 的 `src` 并在点击里同步 `play()`——同源带 cookie、浏览器自己缓存一周、不碰站点 CSP（`default-src 'self'`，不开 `blob:`），自动播放策略也不受合成耗时影响；元素放不出来才再 fetch 一次拿原因。一次只响一个声音（换路线先把另一条停掉）；连点两次只有后一次拥有「播放中」状态和提示。文案按原因分：断网「发音加载失败，请检查网络后再试」（`voiceFetchFailed`）、服务器忙「发音服务器正忙」（`voiceBusy`）、合成失败「服务器暂时无法生成这条发音」（`voiceServerFailed`）、文本被拒「这段文字无法发音」（`voiceTextUnsupported`）、设备放不出「发音音频无法播放」（`voicePlayFailed`）、彻底没有语音「这台设备没有英文语音，服务器也没有配置发音……」（`voiceMissing`）；`voiceNotReady` 删除。服务器答 `{reason:"off"}` 后本次会话不再问它，还有 `speechSynthesis` 的浏览器退回默认语音。`native/capacitor.ts` 删掉了已无用的 `isSpeechUnavailable`。
- **mobile/**：`appendUserAgent` 原来写在 `server.*` 下（Capacitor 忽略），移到顶层；重装后 UA 才带 `word-Dance-App/1`，与发音无关，可不重装。
- **scripts/smoke.py**：`httpx` 不再读环境里的代理变量（这台 Mac 的 shell 导出 `HTTP(S)_PROXY`，曾把对 127.0.0.1 的请求送进代理导致假失败）；新增一步打真实 `say`（Mac）或确认 503 `off`。
- **文档**：API.md §1 / §1.1 / §2 / §3 / §8 / §9 / §9.1，DEPLOY.md §1 / §4（含 `WD_AUDIO_CACHE_MB`），`deploy/env.example`，ops.md §6 / §9，DESIGN.md §2 / §9 / §10（Throttling / SSRF / Subprocess / Files / Headers 行），FRONTEND.md §1 / §4 / §6.4 / §6.5 / §6.6 / §8，MOBILE_APP.md（§0 不再写「后端零改动」、§1、§4.1 鸿蒙 NEXT 的实际情况与未验证项、§5 服务器前提第 2 / 5 条、§8 限制、QA 清单），qa-study.md，README，`2026-11-mobile-shell.md` 与 `QUICK_DEPLOY_AND_MOBILE.md` 里被取代的说法加了后记。

## 3 验收

- 后端：`tests/unit/test_audio.py`（文本规则含弯引号 / 破折号 / 引号开头，本地化的 `say -v ?` 解析含 19 字名字只隔一个空格的行，语音分级与探测，内容寻址，缓存上限与淘汰，假 `say` / `afconvert` 下的合成、失败清理与超时杀进程，槽位与排队上限，白名单子环境，有道的参数 / 编码 / 匿名 UA / 大小上限 / 异常，`auto` 与 `WD_AUDIO_CACHE_MB` 解析）、`tests/integration/test_audio_api.py`（401 先于校验 / 503 off / 400 / 200 头部含 `Accept-Ranges` 与缓存 / 206 / 每用户限速 / 503 failed 且日志不含文本 / 写错的 `WD_AUDIO_SAY_VOICE` 答 503）；契约测试自动覆盖 API §1.1、DEPLOY §4、env.example、API §9 ↔ types.ts、FRONTEND §8 ↔ zh.ts；全量 pytest 见 §5。
- 前端：`tsc`、文案检查、vitest（`audio/serverAudio.test.ts` 重写：同步播放地址、失败诊断、打断；`hooks/useSpeech.test.ts` 增加空语音表、一次一个声音、连点、文案映射；`AuthContext.test.tsx` 增加 `/me` → `setServerAudio`；`SpeakButton.test.tsx` 增加仅靠服务器标志可用），主包大小见 §5，`scripts/check_contract.py` 通过。
- 冒烟：`make smoke` 新增发音一步（见 §5）。
- 评审：18 个评审 agent × 6 个维度，152 条去重发现各经 3 个反驳者核验，120 条确认（12 高）。已修的要点：站点 CSP 没有 `media-src`，上一版用 blob: URL 播放在真实浏览器里会被拦下（改为直接播同源地址）；`say -v ?` 把名字填充到 20 列，19 字的名字只隔一个空格，原解析正则漏掉「Samantha (Enhanced)」这类行；`say -v` 对不认识的名字静默换声（加探测）；Enhanced 排在 Premium 前（按级别排）；文本规则比文档严且拒绝弯引号 / 破折号 / 引号开头（放宽并对齐文档）；「这台设备没有英文语音，服务器也没有配置发音」被错误地用于文本被拒 / 放不出等情形（按原因分文案）；连点两次「播放中」提前熄灭、两条路线可能同时出声（计数守卫 + 先停另一条）；浏览器语音表还没加载时首个单词被送去服务器（空表视为浏览器）；排队等槽位会占满线程池（排队上限）；缓存无上限（`WD_AUDIO_CACHE_MB`）；有道请求带运营者邮箱与网址（匿名 UA）且不限大小（2 MB）；子进程继承整个环境（白名单）；失败日志写出学习者的文本（只记长度）；`DESIGN §9.6` 并不存在（改为 §9 条目）；API.md §1「GET 不限速」、MOBILE_APP「后端零改动」、`SpeakButton` 文档、鸿蒙「卓易通」的断言强度等文档不一致。未采纳 / 顺延：为小学词表预生成音频的命令（需要时再加）；管理页显示实际生效的提供方（先用启动日志）。

## 4 上线步骤与回滚

1. Mac：`git pull`，构建前端快照并切换符号链接，`launchctl kickstart -k gui/$(id -u)/com.word-dance.server`（后端代码变了，必须重启；`auto` 在 Mac 上自动等于 `say`，`.env` 不用改）。可选：先在 系统设置 → 辅助功能 → 朗读内容 → 系统语音 下载「Ava（高级）」或「Samantha（增强）」，重启后自动选用（日志事件 `audio_voice`）。
2. 验证：`curl --noproxy '*' http://127.0.0.1:8000/media/audio?text=farmer` 未登录应答 401；启动日志有 `audio_provider … say`；登录后 `GET /api/auth/me` 的 `server.audio` 为 `true`；平板 App 里点单词和例句的发音都出声，连点两次只响后一次；华为浏览器里网页发音仍走系统语音。
3. Linux 服务器：在 `.env` 里显式写 `WD_AUDIO_PROVIDER="youdao"`（或接受没有兜底）。
4. 回滚：`git checkout c4574cd`，重建前端快照并重启；`audio/` 目录可留可删（只是缓存）。无迁移，无数据风险。

## 5 上线记录

- 2026-11-10 01:02（Mac，家里网络 192.168.1.250）：`398fcb2` 上线。前端快照 `frontend-releases/398fcb2`（三份 APK 同步放在其 `dl/` 下，内容与 18:20 版相同只多了 UA 标记，不需要重装），`launchctl kickstart -k` 重启后端，2 秒后 `/api/health` 正常；启动日志 `pronunciation clips: provider say (WD_AUDIO_PROVIDER=auto, cache cap 256 MB)`；未登录 `GET /media/audio?text=farmer` 答 401；线上主包含 `media/audio` 路由；`audio/` 目录已建（空，随播放填充）。`.env` 未改。
- 门禁（提交前）：pytest 2264 通过 / 3 跳过（Mac 专属的 `test_defaults_without_environment` 与 Linux 专属的 `test_deploy_files` 除外），契约审计通过，tsc，vitest 50 个文件 412 条，文案检查，主包 101.5 KB gzip（上限 200 KB），`make smoke` 29 步（含真实 `say` 的发音一步，2.7 秒）。对真实 `say` 的直接核对：`say -v ?` 解析出 188 行（含 19 字名字只隔一个空格的 9 行），探测能区分已装的 Samantha 与未装的 Ava (Premium)，一条带弯引号 / 破折号 / 省略号的例句 0.49 秒合成为 21 KB 的 AAC。
- 这台 Mac 只装了普通版 Samantha（en-US）与 Daniel（en-GB）；下载「Ava（高级）」或「Samantha（增强）」并重启服务即可自动换用（§4 第 1 步）。
- 平板上的 App 不用重装：壳加载的是线上站点，下次点发音即走服务器音频；首次播放会在日志里留下 `audio_voice`（选用的语音）与 `/media/audio` 的 200 记录。
