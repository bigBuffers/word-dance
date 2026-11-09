# word-Dance 手机 App（iOS / Android 壳）——开发、构建与上架手册

> 2026-11-09 · 代码基线 `main`（P3b 之后）· 应 sqin 的要求（「先把这两个软件开发好，给出上架步骤文档」）由 Claude 实现并撰写。方案依据 `docs/QUICK_DEPLOY_AND_MOBILE.md` §4（2026-11-04 核验）；本文记录实际落地的工程、构建方法和两大商店 + 国内商店的上架步骤。凡是标注「需你本人操作」的步骤都涉及实名、付费或账号登录，无法代做。

## 0. 一页结论

- **App 是什么**：Capacitor 8.6 的「远程壳」。App 里是一个 WebView，直接加载线上站点（`server.url`），登录、学习、单词之舞全部是现有网页代码，后端只为 App 这类没有英文语音的设备加了一个发音接口（`GET /media/audio`，§5 第 5 条）；App 额外给出真图标与独立窗口、本机每日提醒（本地通知）、原生发音（Android 的 WebView 没有 `speechSynthesis`；设备没有英文语音时改放服务器生成的发音）、安卓返回键、状态栏安全区。网站一发布，App 内容就更新，不用重新上架。
- **已完成**：`mobile/` 下的 Android 与 iOS 两个原生工程（图标、启动图、通知小图标、签名配置、版本号规则）；网站侧接入 `frontend/src/native/`（浏览器里零变化，测试数见发布说明 `docs/releases/2026-11-mobile-shell.md`）；Android 工具链装在这台 Mac 上；签名密钥已生成在仓库之外。
- **能立刻拿到的东西**：Android 安装包（§4.1），指向当前局域网地址，手机与 Mac 同一网络即可安装试用；原生功能（本机提醒、系统发音、隐藏导出）随 2026-11-09 的前端快照已经上线；服务器发音兜底随 `docs/releases/2026-11-server-audio.md` 的发布上线（后端要重启）。App 本身不用重装——网站一发布，壳里就是新的。
- **还差什么才能上架**：① 一个公网 HTTPS 地址（App 里写死的 `server.url` 必须等于后端的 `WD_PUBLIC_URL`；家里的 Mac 加公网 IPv6 加域名也可以，见对话结论）；② 苹果开发者账号（¥688/年，需你本人实名）和这台 Mac 上的 Xcode（约 3 GB，需你的 Apple ID 下载）；③ Google Play 开发者账号（25 美元一次性，需你本人实名）；④ 一页隐私政策（网页即可，两家商店都要求 URL）；⑤ 国内商店另需企业主体、软著与备案（§6.3）。
- **建议顺序**：先用 Android 安装包在家里试 → 决定服务器放哪、拿到 HTTPS 地址 → iOS 走 TestFlight 内测给家人（不审核）→ 再决定要不要进商店。

## 1. 架构与目录

```
mobile/
├── capacitor.config.ts        # appId com.worddance.app · appName word-Dance · server.url 由环境变量 WD_APP_SERVER_URL 决定（§3）
├── package.json               # @capacitor/{core,cli,android,ios}@8.6.0（≥ 8.5.1 是硬要求：CVE-2026-103922）、app@8.1.2、
│                              # local-notifications@8.3.1、@capacitor-community/text-to-speech@8.0.2、@capacitor/assets（图标生成）
├── gradle-mirrors.init.gradle # 国内网络构建用的阿里云 Maven 镜像（首选，原仓库兜底）
├── resources/                 # logo.png（启动图与自适应图标）、icon-only.png（传统图标），1024²，由 frontend/public/icon-maskable.svg 栅格化 → `npx capacitor-assets generate`
├── scripts/prepare.mjs        # Capacitor 钩子 capacitor:copy:before：每次 cap copy / sync 前把 templates/index.html 渲染成 www/index.html（写入服务器地址），iOS 上按档位增删 ATS 例外
├── templates/index.html       # 离线 / 重试页模板（没有本地 index.html 壳就显示不了它）。页面从本地源加载，所以「重试」用 location.replace(服务器地址) 回到站点，网络恢复时自动回去
├── www/                       # 只放生成的 index.html（不入库）
├── android/                   # 原生工程（Gradle）。app/build.gradle：versionCode yyyymmddNN、签名读 android/keystore.properties（不入库）
│   └── app/src/main/res/drawable/ic_stat_word_dance.xml   # 通知小图标（白色单色，Android 要求）
└── ios/App/                   # 原生工程（Xcode，SPM）。Info.plist 已写 ITSAppUsesNonExemptEncryption=NO；部署目标 iOS 15
frontend/src/native/
├── capacitor.ts               # isNative()、syncDailyReminder()、requestReminderPermission()、speakNative()、installNativeListeners()
└── NativeBridge.tsx           # 挂在 App.tsx 里；浏览器中三个 effect 都不碰设备（只多一个 auth:signed-out 监听，其处理函数是空操作）
```

远程壳的机制（Capacitor 8.6 源码核实）：iOS 用 `WKUserScript` 把桥注入每个主框架文档；Android 用 `addDocumentStartJavaScript`，**只对 `server.url` 的精确源生效**——任何跳转（http→https、顶级域→www）都会让安卓壳里没有 `window.Capacitor`。所以 `server.url` 必须等于后端 `WD_PUBLIC_URL` 这个规范源，不能经过重定向。页面源与 API 源相同，所以 `HttpOnly; SameSite=Lax` cookie、只认 Host 的 CSRF 规则、需要 cookie 的 `/media`、CSP 全部原样工作。

网站侧（`frontend/src/native/`，FRONTEND.md §6.6）：
- **每日提醒**：`settings.push_enabled` 开着时，按 `settings.push_time`（学习者时区，夏令时按目标时刻的偏移换算）换算成手机本地时间，排一条每天重复、非精确的本地通知（id 1001，标题 / 正文在 `zh.native`），点开进 `/today`。会话已知时的启动、从后台恢复和设置变化时都取消再重排（插件在第一次触发后会丢掉「休眠中也响」的属性，不重排的话第二天起可能延迟）；`/api/auth/me` 还没回来、请求失败或会话过期时**不动**手机上的提醒，只有在设置页主动退出登录才取消。
- **通知权限**只在用户的手势里申请：点「推送开关」时，或者——装 App 前推送就已打开的账号——设置页显示的「允许通知」按钮；拒绝了仍然保存设置，并提示到系统设置里允许。
- **发音**：`useSpeech` 在壳里走系统 TTS 插件（`rate` 0.92 与网页一致），`supported` / `voicesReady` 为真。插件报错时——引擎不存在（`UNAVAILABLE`：插件只在启动时初始化一次、失败后不再重试，鸿蒙 NEXT 的安卓兼容环境里就是这样）、没有英文语音、引擎出错——只要服务器配了发音（`WD_AUDIO_PROVIDER`，`GET /api/auth/me` 的 `server.audio` 为真），就改放服务器生成的音频（`GET /media/audio`，FRONTEND §6.4）；两边都不行才提示，文案按原因分：网络取不到 `voiceFetchFailed`、服务器忙 `voiceBusy`、服务器合成失败 `voiceServerFailed`、文本不能发音 `voiceTextUnsupported`、设备放不出音频 `voicePlayFailed`、服务器也没配发音 `voiceMissing`；被后一次点击取代的那次失败不提示。Android 插件不会结束被打断的朗读，所以网站侧自己把前一次朗读结束掉，按钮不会卡在「播放中」；浏览器路径只多了「没有英文语音时用服务器音频」这一级。
- **返回键**（Android）：有历史就后退，否则把 App 收到后台。
- **导出按钮**在壳里不显示（WebView 不能下载 `<a download>`）；导入照常。
- **安全区**：`<html>` 加 `native` / `native-ios|android` 类；登录页、欢迎页顶部加状态栏内边距（AppLayout 的顶栏本来就处理了）。

## 2. 开发环境（这台 Mac 已就绪的部分）

| 组件 | 状态 | 说明 |
|---|---|---|
| Node 22 | 已有 | `export PATH=/opt/homebrew/opt/node@22/bin:$PATH` |
| JDK 21 | 已装 `brew install openjdk@21` | `export JAVA_HOME=/opt/homebrew/opt/openjdk@21` |
| Android 命令行工具 + SDK | 已装 `brew install --cask android-commandlinetools`；`sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"` | `export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools`；`mobile/android/local.properties` 已写 `sdk.dir` |
| Gradle | 包装器自动下载（8.14.3） | 经代理：`GRADLE_OPTS="-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=8118 -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=8118"`；Maven Central 会限流（HTTP 429），所以 npm 脚本带 `--init-script ../gradle-mirrors.init.gradle` 走阿里云镜像 |
| Xcode 27.2 | **未装，需你本人**在 App Store 用 Apple ID 下载（3.12 GB，需 macOS 26.6+，本机 26.7.1 满足；装完约 9–12 GB） | 装完后 `sudo xcode-select -s /Applications/Xcode.app`、`sudo xcodebuild -license accept`，首次打开让它装 iOS 平台组件 |
| 真机 | Android 手机开「开发者选项 → USB 调试」；iPhone 需在 Xcode 里信任 | Android 模拟器未装（真机即可） |

## 3. 两个构建档位（`server.url`）

| 档位 | 用法 | 用途 |
|---|---|---|
| **release** | `WD_APP_SERVER_URL=https://你的域名 npm run sync` | 商店 / TestFlight / 对外分发。只接受 https；Android 不允许明文，iOS 没有 ATS 例外 |
| **dev** | `WD_APP_SERVER_URL=http://192.168.1.250:8000 WD_APP_ALLOW_HTTP=1 npm run sync` | 家里局域网直连 Mac 试用。Android 开 `cleartext`；iOS 由钩子写入 `NSAllowsLocalNetworking`（iOS 17 起 ATS 连 IP 地址的 http 都拒绝，没有它就只见「连不上服务器」），所以 dev 地址用 IP 或 `.local` 名；**绝不能**拿去上架 |

没有 `WD_APP_SERVER_URL`、或它不是规范源（带路径、末尾斜杠、默认端口）时 `capacitor.config.ts` 直接报错（不会悄悄打进占位地址）。`scripts/prepare.mjs` 挂在 Capacitor 的 `capacitor:copy:before` 钩子上，所以无论 `npm run sync*` 还是直接 `npx cap sync`，每次都会先把地址写进离线页、在 iOS 上按档位增删 ATS 例外，再由 `cap sync` 把配置写进 `android/app/src/main/assets/capacitor.config.json` 与 `ios/App/App/capacitor.config.json`，并把 `www/` 复制进两个工程；换地址就重新 sync 再构建。生成图标的 `capacitor-assets` 也要读这份配置，随便给一个地址即可（`WD_APP_SERVER_URL=https://x npx capacitor-assets generate …`）。地址变了旧包就连不上（显示 `www/index.html` 的「连不上服务器」页），这正是对话里建议给 Mac 做 DHCP 保留、或尽早拿公网域名的原因。

## 4. 构建

### 4.1 Android 调试包（给家人试用）

```sh
cd /Users/sqin/word-dance/mobile
export PATH=/opt/homebrew/opt/node@22/bin:/opt/homebrew/opt/openjdk@21/bin:$PATH JAVA_HOME=/opt/homebrew/opt/openjdk@21 ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export GRADLE_OPTS="-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=8118 -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=8118"   # 本机经代理时
WD_APP_SERVER_URL=http://192.168.1.250:8000 WD_APP_ALLOW_HTTP=1 npm run android:debug
# 产物：android/app/build/outputs/apk/debug/app-debug.apk
```

安装：把 APK 传到手机（微信文件、数据线、或放到网站 `/dl/` 下浏览器下载），允许「安装未知应用」。品牌差异：小米纯净模式「授权单次安装」；vivo 设置 → 安全与隐私 → 更多安全设置 → 应用安装；OPPO 设置 → 密码与安全 → 系统安全 → 外部来源应用；华为 / 荣耀 设置 → 系统和更新 → 纯净模式 → 退出。**鸿蒙 NEXT（2024 年底起的华为新机 / 平板）系统本身装不了 APK**；带安卓兼容环境（华为应用市场里的「卓易通」一类——家里平板上装的具体是哪一个没有核对）的机器能装能用：2026-11-09 在家里的华为平板上验证，同一台机器用华为浏览器时 UA 是 `OpenHarmony 7.0 … ArkWeb`，装 APK 后 UA 是 `Android 16; wv; Chrome/114`。在那个环境里 TTS 插件拿不到任何语音引擎（每次 `speak()` 都以 `UNAVAILABLE` 拒绝）、WebView 也旧——发音由网站侧回退到服务器音频（§5 第 5 条）；登录、学习、单词之舞能用，本机提醒与通知在该环境里未验证（§8）；直接用华为浏览器打开网页则一切可用。

### 4.2 Android 正式包与 Play 用的 AAB

```sh
WD_APP_SERVER_URL=https://你的域名 npm run android:release
# 产物：android/app/build/outputs/apk/release/app-release.apk（直接分发用）
#       android/app/build/outputs/bundle/release/app-release.aab（Google Play 只收 AAB）
```

签名：`android/keystore.properties`（已从 `/Users/sqin/word-dance-mobile-keys/keystore.properties` 复制，git 忽略）指向密钥库 `/Users/sqin/word-dance-mobile-keys/word-dance-release.jks`（别名 `word-dance`，RSA 2048，有效期 10000 天；口令在同目录的 properties 文件里，权限 0600）。`keystore.properties` 的四个键（相对路径相对于 `mobile/android/app`，建议写绝对路径）：

```properties
storeFile=/Users/sqin/word-dance-mobile-keys/word-dance-release.jks
storePassword=<口令>
keyAlias=word-dance
keyPassword=<口令>
```

**请把这个目录备份到仓库之外的两处**（如 iCloud 云盘 + U 盘）：密钥丢了就只能换包名重新发布，老用户无法升级。版本号：`versionCode` 用 `yyyymmddNN`（今天 2026110901），每次发布递增；`versionName` 跟仓库版本（0.1.0）。

### 4.3 iOS（需 Xcode）

```sh
cd /Users/sqin/word-dance/mobile
WD_APP_SERVER_URL=https://你的域名 npm run sync:ios     # TestFlight / 商店；家里真机试用可用 dev 档位（钩子会给 Info.plist 加 ATS 例外，正式档位自动去掉）
npx cap open ios                                      # 打开 Xcode
```

Xcode 里：选 App target → Signing & Capabilities → 勾 Automatically manage signing、选你的 Team（会自动在开发者网站注册 Bundle ID `com.worddance.app`）；General → Deployment Target 15.0（有 iOS 16 的家人就够用）；工程已设为只支持 iPhone（`TARGETED_DEVICE_FAMILY = 1`，所以商店不要求 iPad 截图；要上 iPad 再专门打开）。真机调试：插上 iPhone，选它为目标，⌘R。归档：Product → Archive → Distribute App（见 §6.1）。每年 4 月前用当年的 Xcode 重新归档一次（苹果要求用最新 SDK 上传）。

### 4.4 改图标

替换 `mobile/resources/logo.png`（启动图与自适应图标的图样）和 `icon-only.png`（传统图标），都是 1024² 不透明 PNG，然后 `WD_APP_SERVER_URL=https://x npx capacitor-assets generate --ios --android --iconBackgroundColor '#157a73' --splashBackgroundColor '#f7f6f1' --splashBackgroundColorDark '#15191b' --logoSplashScale 0.5`；通知小图标是 `drawable/ic_stat_word_dance.xml`（必须白色单色）。

## 5. 服务器前提与网站发布

1. App 只认一个地址。正式分发前要有公网 HTTPS 地址，并把后端 `.env` 的 `WD_PUBLIC_URL` 设成它（`WD_TRUST_PROXY=1`、`WD_HOST=127.0.0.1` 加 Caddy 反代，见 `docs/QUICK_DEPLOY_AND_MOBILE.md` §2），`server.url` 填同一个字符串，不带末尾斜杠，不经重定向。
2. 网站本身要含 `frontend/src/native/`（2026-11-09 的前端快照已上线，见 `docs/releases/2026-11-mobile-shell.md` §5），否则壳里没有提醒、发音等原生功能，只是普通网页；没有英文语音的设备要能出声，还要部署含 `GET /media/audio` 的后端并重启（`docs/releases/2026-11-server-audio.md`）。
3. 隐私政策：两家商店都要一个可公开访问的 URL。目前站内「关于与来源」只有数据来源说明，**上架前需要补一页隐私政策**（收集什么：用户名、可选邮箱、学习记录；用途；删除账号的途径——设置页已有「删除账号」）。
4. 审核用账号：注册是邀请制，提审时要在「审核备注」里给一个测试账号和邀请码。
5. **服务器发音**：没有英文语音的设备（鸿蒙 NEXT 的安卓兼容环境、不少国产 ROM、Android WebView）靠后端 `GET /media/audio` 出声。Mac 主机默认就开（`WD_AUDIO_PROVIDER=auto` → 系统 `say`，离线、每词约 8 KB，缓存在数据目录 `audio/`）；换到 Linux 服务器后要显式设 `WD_AUDIO_PROVIDER="youdao"`（有道词典的公开发音接口，非官方，每个没缓存的文本都会发给它）或接受没有兜底（DEPLOY §4）。缓存上限 `WD_AUDIO_CACHE_MB`（默认 256 MB，最少播放的先删）。想要更好听的声音：在 系统设置 → 辅助功能 → 朗读内容 → 系统语音 下载 Ava（高级）/ Samantha（增强）等语音，重启服务后自动选用（日志事件 `audio_voice` 显示选了谁）；或用 `WD_AUDIO_SAY_VOICE` 指定，名字要和 `say -v '?'` 列出的一致——写错会 503 并记日志，不会用别的声音凑数。

## 6. 上架步骤

### 6.1 iOS：App Store Connect 与 TestFlight

**A. 账号（需你本人）**：在 Mac 或 iPhone 的「Apple Developer」App 里报名 Apple Developer Program（个人），身份证 + 人脸识别，¥688/年自动续订（支付宝 / 微信 / 银行卡，不能用账户余额），社区报告 1–3 天通过，姓名地址不一致时可能数周。

**B. 建 App 记录**（appstoreconnect.apple.com → 我的 App → +）：平台 iOS；名称「word-Dance」（全商店唯一，被占就换一个名称，副标题不能用来区分）；主要语言 简体中文；Bundle ID 选 `com.worddance.app`（Xcode 自动签名后出现）；SKU 任意（如 `word-dance-ios`）。

**C. 首次上传**：先确认嵌入的地址是正式地址——`grep -E '"url"|cleartext' mobile/ios/App/App/capacitor.config.json` 必须显示 https 域名且 `"cleartext": false`，`grep 'SERVER =' mobile/ios/App/App/public/index.html` 必须是同一个 https 域名，`grep -c NSAllowsLocalNetworking mobile/ios/App/App/Info.plist` 必须是 0（归档的是最后一次 sync 的结果）；然后 Xcode → Product → Archive → Distribute App → **TestFlight Internal Only**（不审核）。Info.plist 已含 `ITSAppUsesNonExemptEncryption = NO`，构建上传后直接进入「可供测试」，不会停在「缺少出口合规信息」；如果停了，说明 plist 里的键没有打进包，先修再继续。

**D. TestFlight 内部测试（推荐先走这步，家人可用）**：App Store Connect → 用户和访问 → 添加家人为「营销」角色、仅限本 App 的用户（邀请 3 天内接受，Apple 账号必须和受邀邮箱一致，否则用兑换码）→ TestFlight → 内部测试组 → 加入他们 → 他们在手机装 TestFlight（iOS ≥ 16，国区商店有）接受邀请。限制：每组 100 人，每个构建 90 天后过期，所以日历提醒每 ≤ 80 天重新上传一次。**不要**把同一构建随手加进「外部测试组」试试：外部测试要过 Beta App Review，一旦被拒，这个构建连内测都不能再用。

**E. 商店信息**（提审前填齐）：
- 类别 教育；年龄分级问卷按实际答（无暴力 / 赌博 / 无限制网页访问——App 只加载自家站点，选「否」），结果应为 4+。
- App 隐私：「与用户关联的数据」勾 联系方式（邮箱，可选）、标识符（用户 ID）、使用数据（产品互动）；不追踪。
- 隐私政策 URL（§5 第 3 条）、支持 URL（网站首页即可）。
- 截图：6.9 英寸 iPhone 必交（6.5 英寸可由其缩放），只支持 iPhone 就不用 iPad 图；在 iPhone 17 Pro Max 或模拟器截今日、学习卡、单词之舞、设置四张。
- 审核备注：测试账号 + 邀请码 + 一句话说明「中国 K-12 学习者的词汇训练，内容为本站预生成，App 内无第三方内容」。
- 地区：保留全部地区（含中国大陆）——TestFlight 的可安装性与商店可用状态耦合；中国大陆真正上架需要 ICP（见下）。

**F. 审核风险与对策**：
- 指南 4.2「最低功能」：纯网页壳会被拒。本 App 的原生能力（本地通知、系统发音、离线页、返回键、安全区）要在审核备注里点明；若仍被拒，下一步是改成「打包静态资源 + 远程 API」（`docs/QUICK_DEPLOY_AND_MOBILE.md` §4.3 的 M2，7–9 人日）。
- 5.1.1 隐私：已有账号删除；需隐私政策 URL。
- 中国大陆商店：自 2023 年起 App 需要 ICP 备案号才能在中国区上架，备案要求后端大陆托管与域名备案——与 Claude 的地区限制冲突；可行形态是「境外生成内容、境内只读分发」，但 AI 生成内容的标识与登记要求未核实。没有备案就把中国大陆从「定价与销售范围」里去掉；大陆 Apple ID 看不到其他地区的商店，所以家人只能走 TestFlight。
- 面向儿童：不要勾「儿童」类别（Kids Category 规则严苛，禁第三方分析、要家长门）；按教育类 4+ 上架即可。

**G. 提交**：选构建 → 提交审核，通常 24–48 小时；被拒看「解决方案中心」的具体条款，回复或改后重交。

### 6.2 Android：Google Play

**A. 账号（需你本人）**：play.google.com/console 注册，25 美元一次性，身份证件 + 地址验证；个人账号自 2023-11 起**必须先做封闭测试**：至少 12 位测试者连续 14 天，才能申请正式发布权限（数字以 Console 当前提示为准）。Google 的开发者验证 2027 年在全球已认证设备生效，国内无 GMS 手机不受影响。

**B. 建应用**：名称 word-Dance、默认语言 简体中文、类型 应用、免费。

**C. 签名**：Play 默认「由 Google 管理应用签名密钥」，我们的 `word-dance-release.jks` 作为**上传密钥**；首次上传 AAB 时选择让 Google 生成签名密钥（最省心）。

**D. 必填表单**：
- 隐私政策 URL；
- 应用访问权限：注册需邀请码 → 选「部分功能受限」，填测试账号与邀请码；
- 广告：无；
- 内容分级（IARC 问卷，教育类）；
- 目标受众与内容：按真实受众申报——第一阶段就是小学（6–12 岁），商店图文会出现儿童风格卡片和单词之舞，所以要勾选含 13 岁以下的年龄段（「专为儿童及更大年龄用户设计」），这会触发「家庭政策」：无广告、不接第三方 SDK（本 App 符合），审核更慢；**不要**为省事声明「13 岁及以上 / 非专为儿童设计」，Google 会把申报和商店信息对照，不符是驳回或下架理由；
- 数据安全：收集 个人信息（用户名、可选邮箱）、应用活动（学习记录），均加密传输、可申请删除（设置页删除账号）；
- 权限说明：`POST_NOTIFICATIONS` 运行时申请；`RECEIVE_BOOT_COMPLETED` 重启后恢复提醒。通知插件自带的 `SCHEDULE_EXACT_ALARM` 已在清单里用 `tools:node="remove"` 去掉：本 App 把提醒排成**非精确**闹钟（`isExactNotification: false`），不会弹出系统的「闹钟和提醒」设置页；代价是提醒可能延后，Android 12+ 的保证是「一小时内」（通常几分钟，省电模式下更久）——插件默认的精确模式会在每次 `schedule()` 时打开那个设置页，而我们每次启动 / 恢复都重排，所以不用。
- 目标 API：新应用须 ≥ API 35（2025-08 起）、2026-08 起 ≥ 36；本工程 compile/target 36 ✓。

**E. 轨道**：内部测试（最多 100 人，秒级生效）→ 封闭测试（满足 12 人 × 14 天）→ 正式发布（首次审核数天）。上传的是 `app-release.aab`。

**F. 国内大多数手机没有 Google Play**：Play 上架主要服务海外或装了 GMS 的用户；国内分发见 6.3。

### 6.3 国内应用商店与直接分发

| 渠道 | 要求 | 结论 |
|---|---|---|
| 华为应用市场 | 企业 / 个人开发者实名；APP 备案（前提：大陆托管 + ICP）；软著；AI 内容需算法备案号；鸿蒙 NEXT 需单独的 ArkTS 应用 | 有企业主体再做 |
| 小米 | 已不收录个人及个体工商户的应用（无正式公告，2024 年底媒体报道） | 需企业 |
| OPPO | 2025-10 ODC25 宣布自 2025 年 12 月底起向个人开发者开放应用上传，具体资质以开放平台为准 | 可试 |
| vivo | 个人上架政策未核实，以官网公告为准 | 待核实 |
| 应用宝 | 实名、软著、备案 | 需企业更顺 |
| **自己分发 APK** | 网站上放下载链接（服务器 `/dl/word-dance.apk`，或 Caddy `handle_path /dl/*`）+ 微信发文件 | **当前阶段的国内路线** |

软著：中国版权保护中心免费申请约 1–2 个月，代办 ¥300–1000 加急 1–2 周，需提交源码前后各 30 页与说明书。APP 备案：在 ICP 备案基础上向接入商提交，个人备案不得含经营性内容，教育类可能被要求企业资质——这些是组织层面的决定，不是代码问题。

## 7. 日常维护

- **版本**：Android `versionCode` 与 iOS `CURRENT_PROJECT_VERSION` 都用 yyyymmddNN（当前 2026110901），每次发布递增；`versionName` / `MARKETING_VERSION` 跟仓库版本（当前 0.1.0，两端已对齐）。
- **TestFlight 90 天**：日历提醒每 ≤ 80 天重新归档上传。
- **升级 Capacitor**：锁在 8.6.x；Capacitor 9 需 Node 24 与 Xcode 27，升级前先在分支验证 `WD_APP_ALLOW_HTTP` 的明文开关和 Android 的 `window.Capacitor.isNativePlatform() === true`。
- **密钥**：`/Users/sqin/word-dance-mobile-keys/` 两处备份；Play 用 Google 托管签名时上传密钥丢了可以申请重置，自己分发的 APK 密钥丢了不能。
- **QA 清单**（每次发布）：安卓壳里 `window.Capacitor.isNativePlatform()` 为真（证明 `server.url` 与线上源完全一致）；设置页看得到「在 App 里，提醒由手机本机……」提示且导出按钮不显示；开推送 → 系统弹权限 → 次日按时收到通知并点开进今日页（装 App 前推送就已打开的账号：设置页出现「允许通知」按钮，点一下走同样的流程）；发音按钮出声——设备有英文语音时是系统语音，没有时（鸿蒙兼容环境、无英文 TTS 的国产机）是服务器音频（例句也要能放：含引号、破折号的句子不能报错；连点两次只响后一次），两者都没有才弹「这台设备没有英文语音，服务器也没有配置发音……」，服务器端出问题时按原因提示（正忙 / 暂时无法生成这条发音 / 这段文字无法发音），断网才是「发音加载失败，请检查网络后再试」；连点两个发音按钮时前一个不会卡在「播放中」；断网 → 显示「连不上服务器」→ 恢复网络后点「重试」能回到登录 / 今日页；返回键在首页收到后台而不是退出。

## 8. 已知限制

- 微信内置浏览器打开网站不能「添加到主屏幕」；App 不受此影响。
- 鸿蒙 NEXT 系统本身不能装 APK；其安卓兼容环境（「卓易通」一类，具体是哪个未核对）能跑这个 App，但 TTS 插件在里面拿不到语音引擎、WebView 为 Chrome 114，发音全靠服务器音频（§5 第 5 条）；本机提醒 / 通知在该环境里未验证。
- 发音的兜底依赖服务器的 `WD_AUDIO_PROVIDER`：Mac 主机自动用系统 `say`；Linux 服务器不设置就没有兜底，没有英文语音的设备会提示安装语音包。
- 提醒是非精确闹钟（设计如此，见 §6.2 D）：Android 12+ 保证一小时内送达，通常几分钟，省电模式下更久；精确模式会把用户弹进系统设置页，所以不用。
- iOS 的本地通知只在用户打开过 App 并授权后生效；系统升级或换机后要再开一次 App。
- 远程壳在没网时只显示「连不上服务器」页，没有离线学习。

## 9. 费用汇总

| 项目 | 费用 |
|---|---|
| Apple Developer Program | ¥688 / 年 |
| Google Play 开发者 | 25 美元一次性 |
| 软著（国内商店） | ¥0（自办，1–2 个月）或 ¥300–1000（代办） |
| 公网服务器（如 Tencent Lighthouse 东京 2c4g） | 约 ¥42 / 月（家里电脑 + 公网 IPv6 + 域名 ≈ 域名费） |
| 本机工具链 | ¥0（已装；Xcode 免费） |
