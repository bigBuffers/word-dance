# word-Dance 公网发布与 iOS 应用需求分析

> 日期：2026-11-03 · 代码基线：`main` @ `9ab13a5` · 应 sqin 的要求由 Claude 撰写
>
> 方法：9 个并行切片（5 个精读代码、4 个联网调研，共约 280 条带 `file:line` 或 URL 的结论）→ 对最影响结论的 9 条做对抗性核验（修正了若干日期、价格与适用范围）→ 3 套独立路线图由 3 位评审从产品、工程、合规与成本三个视角打分后综合。原始证据、核验记录与路线图评审见 [`docs/analysis/2026-11-03-public-launch/`](analysis/2026-11-03-public-launch/)。
>
> 本文是分析与建议，不是已做出的决定；第 7 节列出只有你能拍板的问题。文中工作量均按一名有经验的全职开发者估算。

## 0. 一页结论

**0.1 目标澄清：公众可用不等于必须先有 iOS App。** 网页前端是移动优先的（`100dvh` 布局、安全区、44 px 触控目标、跟随系统的深色模式）；iOS 26 起任何网站「添加到主屏幕」默认就以独立 App 形式打开，不需要 manifest；主屏网页应用自 iOS 16.4 起支持 Web Push 与角标，且不需要 Apple 开发者账号。只有原生或混合 App 才能提供的是：App Store 可发现性、小组件与实况活动、本地定时通知、后台同步。因此公网部署是第一优先级，iOS App 是第二阶段的独立决策（第 4、6 节）。

**0.2 真正的前置阻塞是 Claude 的接入方式与地区政策，不是 iOS。**
- 后端现在用你本人的 claude.ai 登录（而且是公司配发的 Enterprise 席位）以 `claude -p` 生成内容。Anthropic 的 Claude Code 法律页写明：OAuth 登录「仅供订阅购买者……普通使用」，开发产品「应通过 Claude Console 使用 API key」，「不允许第三方开发者……代表其用户通过 Free/Pro/Max/Ultra 凭据路由请求」，并可「不经事先通知」执行；Enterprise 席位「分配给一位具名个人，仅该人可使用」。公共服务必须换成你自己控制的 Console 组织 + API key。代码已经把 `ANTHROPIC_API_KEY` 透传给子进程（`backend/wd/ai/runner.py:49-62`），但这条路径在本仓库从未验证过。
- 中国大陆、香港、澳门不在 Anthropic 支持地区名单里（新加坡、日本、台湾、美国在）。2026-11-12 生效的新版政策把判定写成三要件：使用者的实际所在地、实体的注册地或总部、多数股权控制方；同日生效的使用政策禁止「向他人（包括最终用户）提供违反支持地区政策的访问」。**服务器放在哪里不是判定标准，学习者在哪里才是。** 对面向大陆学习者的产品，凡把用户输入实时送给 Claude 的功能（自添生词校验、按需生成例句、夜间整理）都在政策之外；只读运营者预生成的缓存内容在条文上不构成「提交输入」，但这是从定义推出来的立场，不是 Anthropic 书面认可的安全港。
- 两点合起来：**在动 iOS 之前，先决定受众与模型**（第 2 节、决策 D1）。

**0.3 中国境内合规决定了托管在哪、在哪上架。** 境内托管需要 ICP 备案（个人非经营性可办，但「中考 / 高考词汇」定位可能触发 K-12 校外培训前置审批）、APP 备案与公安联网备案；教育移动应用备案实际只对单位开放，且要先有 ICP 与等保；生成式 AI 服务需备案或「登记」，而登记只接受已备案模型，Claude 没有备案路径，2026 年 4–7 月的「清朗·整治 AI 应用乱象」已处置 1.4 万余款未备案 AI 产品。结论：**只要内容由 Claude 生成，就不要规划中国区 App Store 上架。** 境外托管（新加坡 / 东京）免备案，代价是进不了中国区商店（大陆 iPhone 用户只能走 TestFlight 公开链接或主屏网页应用）以及被墙风险。

**0.4 服务端为公网必须补的能力**（第 3.3 节有完整清单）：按用户的 AI 配额与归因（现在任何账号用约 92 次请求就能把 9,162 个种子词全部排进生成队列，约 1 小时耗尽全局 $3/天 预算，之后所有人的 AI 功能顺延到次日）；可配置的可信代理（现在硬编码 `127.0.0.1`，放在云负载均衡后面全站共用一个 IP，每小时只能注册 5 人）；按用户名的登录锁定可被任何人滥用且没有解锁命令；找回密码；服务条款、隐私政策、注册同意、年龄门槛、AI 标识；管理员的词条下架 / 合并工具；监控告警与异地备份；以及 `deploy/install.sh` 对 `sqin` 与 `/home/sqin` 的硬绑定。

**0.5 成本量级（API 牌价、全球路由）。** 例句约 $0.0045–0.0048/词（10 词一批）或 $0.009–0.011/词（单词调用）；一次性预热全部 9,162 个种子词约 $41–44（Batch API 约 $20–22）；每活跃用户每月约 $0.7–3.5（例句 + 夜间整理），外加配图 SVG 项（照片命中率测清之前，小用户量时可达 $2–8/用户·月，随共享缓存填满而摊薄，默认 $0.50/天 子上限封顶约 $15/月）。Console 新组织从 Evaluation / Start 层起步，Start 层 $500/月 上限大约支撑 100–300 个活跃用户。服务器 $9–24/月，Apple 开发者计划 $99（¥688）/年。

**0.6 iOS 路线建议。** 「功能对等」应定义为 15 个学习者路由；管理页本来就不在手机 TabBar 里，留在网页。四条路线：PWA 1–2 周、零审核风险、100% 复用；Capacitor 包壳 3–5 周、约 95% 复用，但要过 4.2「套壳网站」审核，且后端要加 token 或签名媒体 URL；Expo / React Native 6–10 周、只复用约 13–16% 的纯 TypeScript、需重写 9–11 千行 UI，换来原生体验与 Android；SwiftUI 8–14 周、零复用、双份维护。建议顺序：Web 上线 → PWA / Web Push + Bark → 在决策点按证据选 Capacitor 或 Expo（第 6 节）。

**0.7 发布流程概要**（第 5 节）：域名 + HTTPS + `WD_PUBLIC_URL`；Apple Developer Program 个人注册（¥688/年，App Store 卖家名为真实姓名）；Xcode 27.2（本机 macOS 26.7.1 / Apple Silicon 满足要求，需安装：3.1 GB 下载 + 数 GB 模拟器运行时）；TestFlight（内部 100 人、外部 1 万人、构建 90 天过期、每个版本的首个构建要过 Beta 审核、每 24 小时最多 6 个构建）；App Store 审核通常 1–3 天一轮，首个版本可能几轮；不勾选中国大陆就不会遇到 ICP 字段。

**0.8 需要你拍板的问题**（第 7 节）：受众是否以大陆为主；是否接受为大陆版换用国产已备案模型；AI 月预算；是否愿付 $99/年；要的是 App Store 存在还是「装到手机 + 每日提醒」；管理页是否进 App；是否服务 14 岁以下用户；用户贡献词的许可；是否成立运营主体。

## 1. 现状基线（代码事实）

### 1.1 架构与鉴权契约

| 事实 | 出处 | 对公网 / iOS 的含义 |
|---|---|---|
| 单进程 FastAPI + SQLite（WAL）+ 进程内调度器与 worker；拒绝多于 1 个 uvicorn worker；`kv.worker_lease` 保证全部署只有一个进程跑后台任务 | `backend/wd/main.py:504-517`，`backend/wd/jobs/lease.py` | 只能垂直扩展；第二台主机需要重写持久层（数据库、队列、锁、图片存储） |
| 会话是 `wd_session` cookie：`HttpOnly; SameSite=Lax; Path=/; Max-Age=WD_SESSION_DAYS×86400`，https 下 `Secure`；每日滑动续期一次；每用户最多 20 个会话，超出静默淘汰最旧的 | `backend/wd/security.py:62,162-192,229-238`，`backend/wd/deps.py:157-173` | 原生客户端用 URLSession 的 cookie jar 可以直接复用；每次启动都重新登录会把用户的浏览器会话挤掉 |
| 只认 cookie，没有 `Authorization: Bearer`、没有 API key、没有刷新令牌；token 只出现在 `Set-Cookie`，响应体里没有 | `backend/wd/deps.py:146-149` | 需要 token 模式才能用 Keychain 存凭据、给 `<img>` 鉴权（见 4.3） |
| CSRF：非 GET 的 `/api/*` 必须带 `X-WD-Request: 1`；若有 `Origin` 头，须等于 Host 推导的 origin 或 `WD_PUBLIC_URL` 的 origin，否则 403；**没有 Origin 头则放行**；没有 CORS，`OPTIONS` 预检返回 405 | `backend/wd/deps.py:111-129`，`backend/wd/main.py:188-192`；核验时实测：无 Origin → 201，`capacitor://localhost` → 403 | URLSession、React Native fetch、CapacitorHttp 都不发 Origin，可直接用；从 `capacitor://localhost` 发出的浏览器 fetch 会被拒 |
| `/media/images/*` 与 `/media/card/*.svg` 同样要求会话 cookie | `backend/wd/routers/media.py:38-57` | WKWebView 里的 `<img>` 跨站不带 cookie，会 401（见 4.3） |
| 没有 API 版本段、没有最低客户端版本信号；所有请求模型 `extra="forbid"`，新客户端多发一个字段旧服务器就 400 | `backend/wd/routers/health.py:38-44`，`backend/wd/schemas.py` | 网页与 API 今天是原子发布，二进制客户端上架后必须有兼容性契约 |
| OpenAPI 只在 `WD_DEV=1` 时提供；无 securitySchemes，只描述 200 响应 | `backend/wd/main.py:526-533` | 生成 Swift / TS 客户端需要离线导出并后处理 |
| 限流：登录 20 次 / 10 分钟 / IP（成功也计数）、注册 5 次 / 小时 / IP、每用户 300 次变更 / 分钟；按用户名锁定（10 次失败 → 15 分钟，每再 5 次翻倍，最长 24 小时），无管理员 / CLI 解锁 | `backend/wd/security.py:72-82,282-339`，`backend/wd/routers/auth.py:83-84,122-137` | 公网上任何人知道用户名就能把该账号锁 15 分钟到 24 小时；运营商 NAT 后面的手机会误触 IP 限流 |
| `X-Forwarded-For` 仅在 `WD_TRUST_PROXY=1` 且 TCP 对端是 `127.0.0.1` 时生效（uvicorn `forwarded_allow_ips` 写死） | `backend/wd/cli.py:146-148`，`backend/wd/deps.py:37,78-96` | 放在云负载均衡 / CDN 后面时所有访客共用一个 IP，上面的限流变成全站限流 |

### 1.2 前端规模与可移植性

- 18 条路由 / 17 个页面；非测试 TS/TSX 12,344 行，CSS 4,661 行，vitest 4,620 行（208 个用例）；全部中文文案集中在 `frontend/src/i18n/zh.ts`（lint 禁止 i18n 之外出现 CJK）。
- 平台无关的纯 TypeScript 约 2,500 行（13–16%）：`api/` 1,015 行（`types.ts` 是冻结契约）、`study/queue.ts` 373 行（纯 reducer，有测试）、`utils/` 770 行、`i18n/zh.ts` 103 行、4 个无 DOM 的 hooks 251 行；其余约 87% 是 React DOM TSX 与 CSS，只有 PWA 与 Capacitor 两条路线能原样复用。
- 最大的屏幕：`AdminPage.tsx` 1,047 行（加 350 行 CSS，约 15% 的 UI 代码）、`StudyPage.tsx` 735、`SettingsPage.tsx` 714、`WordDetailPage.tsx` 610。管理页不在手机 TabBar（`frontend/src/components/layout/TabBar.tsx:27-35`），只在 ≥ 768 px 的 TopNav 出现。
- 用到的浏览器 / 设备 API：`speechSynthesis`（`hooks/useSpeech.ts`，自动发音从 effect 触发，iOS 上首次需用户手势解锁）、localStorage 6 个键（唯一含真实数据的是评分待同步队列 `wd.pendingGrades`，`pages/StudyPage.tsx:53-106`）、`<input type=file>` 导入（发 JSON 体，不是 multipart，1 MiB 上限）、`<a download>` 导出、`navigator.clipboard`（仅管理页）、Pointer Events 滑动（仅筛词卡）、`document.visibilityState` 轮询门控。没有 service worker、manifest、IndexedDB、WebSocket / SSE；`index.html` 已有 `apple-mobile-web-app-capable` 等 meta。
- 轮询：今日页 30 s、例句 5 s × 24、换图 3 s × 20、待处理词 3 s × 30（代码与 `docs/FRONTEND.md` §3 的「都走 usePolling」不一致，移植时以代码为准）。

### 1.3 推送与送达

- 两种任务型渠道：`send_email`（SMTP）与 `send_webhook`（`generic / wecom / feishu / serverchan / bark`）。Bark 是 webhook 格式：用户把 `https://api.day.app/<key>` 填进「Webhook 地址」就能在 iPhone 锁屏收到每日词汇（`backend/wd/delivery/webhook.py:288-291`）；一个用户一个设备，key 明文存在 `user_settings.webhook_url`。
- 没有 APNs、没有 Web Push。新增任何任务类型都要重建 `jobs` 表（`type` 是 `CHECK` 列表，SQLite 不能改 CHECK），并同步 `registry / queue / schemas / test_registry_complete`。
- 推送时间按用户时区（`next_push_at`，`02:30` 本地整理），但 AI 预算日、03:30 维护、备份文件名按 `WD_TZ`。
- 每封邮件 / 每个 webhook 的链接固定为 `<WD_PUBLIC_URL>/today`；`WD_PUBLIC_URL` 为空时退回启动时猜测的内网 IP（`backend/wd/main.py:280-300`），公网部署必须设置。
- 没有找回密码流程；SMTP 只用于邮箱验证码（请求线程内同步发送）、测试邮件、日报；邮件器每封新开连接、无退信处理、无 `List-Unsubscribe`。

### 1.4 AI 层

- 调用：`claude -p <prompt> --output-format json --json-schema … --tools "" --no-session-persistence --model sonnet --max-budget-usd …`（`backend/wd/ai/runner.py:124-149`）；子进程环境白名单透传 `ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL` 与代理变量（`runner.py:49-62`）。没有 `WD_` 配置项承载 key，`install.sh` 的 `.env` 校验拒绝非 `WD_` 行；管理页横幅、探测命令、运维手册都写死「以 sqin 身份登录 claude」。
- 预算：每次调用上限、$3/天、$40/月、60 次/小时（所有种类合计）、预热 $1/天、SVG $0.50/天、并发 1–3。**全部是全局的**：`ai_calls` 没有用户列。
- 按用户的配额只有：自添词 200/天、显式生成 60/天、换图 20/天、举报 20/天。**「标为不熟悉」触发的内容生成没有任何配额**（`backend/wd/services/bank.py:465-478,606-642`；`routers/words.py:114-136` 的批量标记每次最多 100 个），按词去重后上限是该账号可见的全部缺内容的词，也就是整个种子库。
- 结果分类器只认「not logged in / 401」→ 暂停 30 分钟，「529 / 503 / rate limit」→ 过载退避；订阅额度用尽类消息、Console 支出上限的 `enforced_spend_limit_reached` 429 都没有覆盖（`runner.py:71-74`）。
- 本机账本（65 次调用，$0.6576）：10 词例句 $0.0531、单词 $0.012、SVG $0.0124、整理 $0.0198；核验发现账本价含 1.1× 美国专属推理系数、1 小时缓存写价与旧的缓存读价，按 API 牌价全球路由低 10–19%；SVG 占 62% 是代理故障导致照片管线失效的产物，不是真实命中率。
- 每次调用的完整 prompt 与输出保存 14 天（`claude-logs/`），其中夜间整理 prompt 含用户备注前 120 字。

### 1.5 部署与运维

- 文档化的目标是 Ubuntu 24.04 + systemd + 同机 Caddy / nginx；`deploy/install.sh` 假设用户 `sqin`、`/home/sqin`、GNU coreutils、apt、免密 sudo，交互式询问联系邮箱；Docker 被明确排除，理由是 OAuth 凭据文件必须在 `sqin` 的家目录——换成 API key 后这个前提消失。
- 本机 Mac 是 launchd + 手工构建的前端快照 + `bin/claude-wrapper` 包装脚本 + 手动启动的 SSH SOCKS 隧道（本网络直连 `api.anthropic.com` 返回 403「Request not allowed」）。这台 Mac 不能做公网服务器；迁移时只有数据目录（数据库、`.env`、图片）可以带走。
- 监控只有 `/api/health` 与管理页；没有告警、指标、错误追踪；备份是本地的 systemd timer，异地复制与恢复演练是手工步骤；恢复需要停服。

### 1.6 已有与缺失的合规件

- 已有：MIT 许可证、`ATTRIBUTION.md`、设置页「关于与数据来源」、图片署名与来源链接、CSV / JSON 导出与导入、带密码确认的账号删除（级联，孤立私有词一并删除）、每词举报与管理员处理、`safe_for_sharing` 发布门控、无第三方统计、图片自托管。
- 缺失：服务条款、隐私政策、注册时的同意、年龄门槛（中考词表意味着 12–13 岁用户）、用户贡献词的许可声明、向 Anthropic 传输词语与备注的披露、AI 标识只在设置页有一行（`frontend/src/pages/SettingsPage.tsx:688-689`）、公开的联系方式、数据保留期声明；SPA 没有 `/terms`、`/privacy`、`/about` 路由。

## 2. 前置条件：Claude 接入与地区政策

### 2.1 为什么现有登录不能用于公共服务

| 文本（2026-11-03 检索） | 关键句 |
|---|---|
| Claude Code legal-and-compliance（code.claude.com/docs/en/legal-and-compliance） | "OAuth authentication is intended exclusively for purchasers of Claude Free, Pro, Max, Ultra, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications." / "Developers building products or services … should use API key authentication through Claude Console …. Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users." / "Customers may not pay for, resell, or intermediate Claude usage on their end users' behalf." / "may do so without prior notice." |
| Consumer Terms（2025-10-08 生效） | "You also may not make your Account available to anyone else." / 自动访问仅限 "via an Anthropic API Key" |
| Agent SDK overview | "Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK." |
| Enterprise 席位帮助页 | "Each Enterprise seat is assigned to one named individual, and only that person may use it." |
| Usage Policy | 当前生效版（2025-09-15）没有「订阅代理」条款；**2026-11-12 生效的新版**加入 "Resell, proxy, or otherwise provide access to Claude through unauthorized means, including services that route requests through consumer subscriptions"。你的任何发布都在新版之下。 |

2026 年的执法史（1 月封禁第三方 OAuth 后回滚；2 月 19–20 日文档澄清；4 月 4 日封禁 Pro/Max 上的第三方工具；5 月 13 日宣布 Agent SDK 用量改为单独计费、6 月 15 日暂停；10 月 7 日给 Max/Ultra/Team 发月度 API 额度）全部只涉及订阅者**自己**的程序化使用，没有一条开放「替他人服务」。你的 Enterprise 席位还有两层额外问题：它属于雇主与 Anthropic 的合同，企业管理员在用量分析里看得到；Enterprise 与 Pro 都不在 10 月 7 日的 API 额度之列。

`docs/CLAUDE_INTEGRATION.md:33` 规定「永不使用 `--bare`」以保住 OAuth；Anthropic 现在把 `--bare` 列为脚本调用的推荐模式，并宣布它「将成为 `-p` 的默认」，而 bare 模式「从不读取 OAuth 凭据」。也就是说即使不考虑条款，现有 runner 也会在某次 CLI 升级后停止认证。

### 2.2 切换路径与工作量

1. **配置级切换（1–2 天）**：Console 组织 + API key，放进服务环境（`-p` 模式下 key 总是优先于 OAuth）。仓库需要：新增 `WD_ANTHROPIC_API_KEY`（映射进 `claude_env`，加入 `SECRET_KEYS` 掩码）、`install.sh` 预检与 `env.example` / `DEPLOY.md`、把「以 sqin 身份登录」的横幅与提示换成「检查 key / Console 余额」（`backend/wd/ai/common.py:37`、`ai/probe.py:200`、`diag.py:99`）、加 `--bare`、让 `ProtectHome=yes` 成为可能、用 `wd claude-check` 复验（估算 ≈ $0.01）。同时给分类器补上 `\b429\b`、`enforced_spend_limit_reached`、订阅额度用尽短语，归为暂停而不是失败（`runner.py:71-74`）。
2. **建议级迁移（1–2 周）**：把 `runner.py` 换成 Messages API（Python SDK）。四个处理器只依赖 `ClaudeResult`（`backend/wd/interfaces.py:83-109`），所以是模块替换而非重写；需要：把 5 个 JSON Schema 改成结构化输出接受的形状（去掉 `maxItems`、`minItems>1`，加 `additionalProperties:false`，服务端后验证继续兜底）、用 `usage × 价格表` 算成本、把 HTTP / stop_reason 映射到现有状态分类、改写以子进程为形的测试替身（约 10 个测试文件、`scripts/smoke.py`、`scripts/dev.sh`）、让 tier / probe / `WD_CLAUDE_*` 机制退役。收益：预热、预取、夜间整理可走 Batch API（半价）、服务端用量账本、摆脱 CLI 二进制 / 登录 / Keychain、Docker 成为可能、消除「在产品内托管 Claude Code」条款的解释风险。
3. **资金**：个人 Max（$100/月 额度）或 Team 订阅链接到 Console 组织可获月度 API 额度，覆盖 Messages / Batches 与带 key 的 `claude -p`；Pro 与 Enterprise 没有。

### 2.3 地区政策与「最终用户」

- 名单：所有能查到的版本（2025-12 至 2026-11 的 Wayback 快照与现行页）都没有中国大陆、香港、澳门；台湾、新加坡、日本、美国都在。
- 判定：2026-10-08 发布、2026-11-12 生效的版本写明三要件——"Use by persons while physically located in an unsupported region"、"entities incorporated or headquartered in an unsupported region"、"majority-owned or controlled … by persons or entities in unsupported regions"；使用政策新增 "Access, facilitate, or provide others (including end users) with access … in violation of our Supported Regions Policy"。现行版（2025-09-15）措辞是 "persons, entities, or users"，并通过 "passthrough access" 覆盖最终用户，实质相同。
- 缓存与实时的区别：商业条款把 Inputs 定义为「客户或其用户向服务的提交」，Outputs 归客户所有且没有分发地域限制。于是「运营者在支持地区预生成、大陆用户只读」在条文上站得住，而自添词校验（`backend/wd/ai/lookup.py:523`）、按需生成（`ai/content.py:392`）、夜间整理（`jobs/scheduler.py:194`、`ai/consolidate.py:470`）是以该用户的输入发起的实时调用。**这是推理，不是 Anthropic 书面认可的安全港**；如果受众以大陆为主或 App 要进中国区，上线前应向 Anthropic 销售 / 支持取得书面确认。
- 代码里的门控点：`deps.client_ip`（`backend/wd/deps.py:78-96`）已经在代理后解析真实 IP，是挂国家判断（Cloudflare `CF-IPCountry`、MaxMind）的自然位置；会话表也存了 IP。
- 你本人的网络：直连 `api.anthropic.com` 返回 403 是 Anthropic 地理封锁的特征。如果你长期身处不受支持地区，政策同样约束你个人的账号与 Console 组织（注册国家、付款方式）；这一点只有你能评估。

### 2.4 替代模型

- 面向大陆合规上架的唯一路径是「已备案的国产模型 + 有营业执照的主体做登记」。部分国产模型提供 Anthropic 兼容端点，runner 已透传 `ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN`，配置即可指向；但结构化输出（`--json-schema`）、例句质量、费用都需要单独验证，本仓库没有任何评测集。
- 走 Messages API 迁移后，接 OpenAI 兼容接口的国产模型只需再写一个 runner 实现。
- 不要做「备案一个国产模型、后端实际调 Claude」的变通：执业律师与中转服务商自己都把它列为违规风险，且设计目的就是规避 Anthropic 的地理政策。

## 3. 公网部署分析

### 3.1 托管地选择

| 方案 | 境内备案 | Claude 可达性 | 中国区 App Store | 大陆延迟 | 2 vCPU / 4 GB 价格 | 主要风险 |
|---|---|---|---|---|---|---|
| 大陆 VPS（阿里云 / 腾讯云） | 需要 ICP + APP 备案 + 公安备案；个人非经营性可办（2–5 周）；教育 App 备案需单位 | 不可达，需中转——违反 Anthropic 政策，且 PRC 侧属灰色地带 | 需 ICP 字段 + 生成式 AI 登记（Claude 无路径） | 最佳 | 最低 | 备案因「中考 / 高考」定位被要求教育部门前置审批；AI 合规；Wikimedia 全系被墙，图片管线与 Claude SVG 兜底同时失效 |
| 香港 | 不需要 | 不在支持地区，HK IP 被拒 | 不可 | 10–30 ms | 阿里 / 腾讯 $15/月 | 仍需中转，被新加坡 / 东京方案支配 |
| 新加坡 / 东京 | 不需要 | 可达 | 不可（不勾选大陆） | 新加坡 60–120 ms，东京 30–60 ms | 腾讯 Lighthouse $8.5/月、阿里 SAS $15/月、Lightsail $24/月 | GFW 封 IP / 域名（备短 TTL DNS 与换 IP 能力）；大陆最终用户的 Anthropic 政策问题（2.3） |
| 美国 | 不需要 | 可达 | 不可 | 150–200 ms | 相近 | 同上，延迟更差 |

对非商业的个人运营者，**现实的组合是新加坡或东京 VPS + Console API key + 境外域名 + 同机 Caddy 终止 TLS**，不做任何境内备案。整个单进程应用放在 $9–24/月 的机器上足够。

### 3.2 中国法规清单与对本项目的适用性

| 法规 / 要求 | 适用对象 | 对 word-Dance 的判断 | 处置 |
|---|---|---|---|
| 《互联网信息服务管理办法》ICP 备案；首页显著位置展示备案号 | 大陆服务器上的网站 | 仅大陆托管时适用；个人主体不得有企业 / 商业内容，站名不得含「教育」等字样；华为云前置审批表列有「校外培训（高中及以下）」 | 境外托管不适用 |
| 工信部〔2023〕105 号 APP 备案；App 内显著位置标备案号 | 在境内提供服务的 App | 需要已备案的大陆主机与域名；境外后端无法备案 | 不进中国区商店则 Apple 侧无此要求（见 5.3） |
| 公安联网备案 | 网站 / App 上线 30 日内 | 仅大陆托管 | 同上 |
| 《生成式人工智能服务管理暂行办法》（2023-08-15）；算法备案 / 生成式 AI 备案与「登记」 | 向境内公众提供生成内容的组织与个人，无规模 / 免费豁免 | 用户可触发生成且输出共享给所有人，「只是展示 AI 内容」的辩护不牢；Claude 无备案，故无登记路径；个人无登记资格 | 境外托管时可执行的制裁只有封锁；大陆上架等于关门 |
| 《人工智能生成合成内容标识办法》（2025-09-01）与 GB 45438-2025 | 深度合成类文本服务 | 现有标识只在设置页，不满足「文本起始 / 末尾 / 周边显著提示」；用户协议须说明标识方式 | 低成本就位：卡片、邮件、webhook 文本旁加「AI 生成」标记 + 协议条款 |
| 《教育移动互联网应用程序备案管理办法》（2019） | 面向师生家长的移动 App | 仅单位可办，需先 ICP + 等保；北京 2026 年白名单里的背单词 App 全是公司 | 个人 + 境外后端无路径 |
| 「双减」相关规定 | 校外培训机构、拍照搜题类 | 免费自学工具不是培训机构，直接下架风险低；风险在备案审查员对「中考 / 高考」定位的解读 | 对外表述避免「培训 / 提分」 |
| PIPL + 《网络数据安全管理条例》（2025-01-01） | 面向境内自然人提供服务的处理者（含境外） | 缺隐私告知、同意、未满 14 岁监护人同意；导出 / 删除已满足；境外处理者理论上需境内代表 | 隐私政策 + 注册同意 + 年龄门槛（14+ 或监护人流程）；代表义务作为已知低执法缺口披露 |
| 跨境数据规定（2024-03-22） | 向境外传输个人信息的处理者 | 10 万人以下非敏感信息免评估；未满 14 岁数据属敏感 | 排除未成年人即不触发 |

### 3.3 服务端缺口清单

按优先级分组；「阶段」对应第 6 节。

**A. 公网前必须（安全与滥用）**

| # | 缺口 | 出处 | 建议 | 估算 |
|---|---|---|---|---|
| A1 | 「不熟悉」触发的内容生成无按用户配额；客户端可通过 `context: detail/today` 自选优先级 10 | `services/bank.py:465-478,606-642`；`routers/words.py:233-255` | 在 `enqueue_content_if_needed` 加每日按用户计数（复用 `check_daily_quota`）；`jobs` / `ai_calls` 增 `user_id` 列以便归因与取消；标记触发的任务固定优先级 ≥ 20 | 2–3 天 (1-A: WD_AI_USER_DAILY_WORDS per-user cap; attribution/cancel deferred) |
| A2 | 预算全部全局；一人耗尽则全员顺延，且无管理员取消队列 | `ai/budget.py:187-235`；`ai/ledger.py` | 按用户 AI 额度（词 / 天）+ 管理员「取消某用户队列」；全局上限按用户数重调 | 含 A1 (1-A: WD_AI_USER_DAILY_WORDS per-user cap; attribution/cancel deferred) |
| A3 | 可信代理写死 `127.0.0.1` | `cli.py:146-148`；`deps.py:37` | 新增 `WD_TRUSTED_PROXIES`，同时喂 uvicorn 与 `client_ip`；文档要求同机 Caddy 终止 TLS，若前置 CDN 则配置 real IP | 0.5 天 |
| A4 | 按用户名锁定可被任意第三方触发，无解锁 | `security.py:282-339` | 改为用户名 + IP（或设备）联合键；N 次失败后 CAPTCHA；`wd unlock <username>` | 1 天 (done in 1-A: the lockout key is `login:user:<identifier>:<ip>`, `wd unlock <identifier>` clears every IP; the self-hosted image captcha gates the public code sends — the password login has no captcha) |
| A5 | 注册只有 5 次 / 小时 / IP，无验证码、无邮箱验证、存在用户名 / 邮箱枚举 | `routers/auth.py:79-117` | 起步用邀请制（`WD_REGISTRATION_MODE=invite`）；开放注册前加 Turnstile 类验证码 + 邮箱验证门控 AI 功能 | 1–2 天 |
| A6 | 无找回密码 | `routers/account.py` | 邮件重置流程（依赖事务邮件服务商） | 1–2 天 (done in 1-A: `POST /api/auth/password/forgot` / `reset` — a code to the bound phone, else the verified e-mail, always 202; a reset revokes every session) |
| A7 | 共享图片可被任一用户「换一张」或单次举报替换（阈值 1，设计给 1–5 人） | `routers/words.py:259-301`；`images/service.py:186-211` | 举报阈值 / 投票；或换图只影响本人 | 1 天 |
| A8 | 登录限流把成功登录也计数；CGNAT 下误伤 | `routers/auth.py:122-131` | 成功不计数或改按账号 | 0.5 天 (done in 1-A: `login:ip` counts failures only — checked before the password, counted on the failure path) |

**B. 公网前必须（合规与产品）**

| # | 缺口 | 出处 | 建议 | 估算 |
|---|---|---|---|---|
| B1 | 无服务条款 / 隐私政策 / 联系方式页面 | `routes.tsx` | 新增 `/terms`、`/privacy`、`/about` 静态页；注册页同意勾选；说明向 Anthropic 传输的内容、保留期（含 `claude-logs` 14 天）、贡献词许可 | 1–2 天 + 文案 |
| B2 | 无年龄门槛 | `schemas.py:179-184`；`RegisterPage.tsx:45-47` | 注册声明 14 岁以上，或监护人同意流程 | 0.5 天 |
| B3 | AI 标识只在设置页 | `SettingsPage.tsx:688-689`；`zh.ts:86` | 卡片例句 / 搭配 / 助记块旁、邮件与 webhook 文本加「AI 生成」 | 0.5 天 |
| B4 | 账号删除后 `claude-logs` 与日志中的输入仍保留 | `runner.py:289-338` | 缩短保留期或删除时清理；隐私政策如实披露 | 0.5 天 |
| B5 | 词库治理：用户词仅凭 Claude 的 `is_english + safe_for_sharing` 发布；管理员没有下架 / 合并 / 删除 / 改名工具；ECDICT 命中的词不经校验直接公开；贡献无法回流到 `data/seed` | `services/words.py:652-685`；`admin_ops.py` | 管理员词条 API 与页面（unpublish / merge / delete / ban）、审核队列（可选）、`provenance` 与许可列、导出已验证贡献词的命令 | 3–5 天 |

**C. 运维与稳定性**

| # | 缺口 | 出处 | 建议 | 估算 |
|---|---|---|---|---|
| C1 | 无告警 | `routers/health.py` | 外部拨测 `/api/health`；对 `system_events` 的 `claude_auth / budget_* / backup_failed / downtime` 发邮件或 webhook 给管理员 | 1 天 |
| C2 | 备份只在本机 | `backup.py`；`deploy/word-dance-backup.timer` | 定时加密同步到对象存储（含 `.env` 与 `images/`）；季度恢复演练 | 0.5 天 |
| C3 | `install.sh` 与默认值绑定 `sqin` / `/home/sqin`；交互式提示；仅 Ubuntu | `install.sh:4,8,11,48-49`；`config.py:32,85,87` | 通用化服务用户与路径、去交互；（迁移 Messages API 后）提供 Dockerfile | 1–2 天 |
| C4 | 单个 IoWorker 串行处理图片 + 邮件 + webhook；08:00 推送潮排队 | `main.py:105-111`；`worker.py:275-278` | 分离送达 worker 或按类型并发；邮件改事务服务商 | 1 天 |
| C5 | 会话 GC 文档说每小时，代码只在登录时 | `routers/auth.py:138` | 挂进调度器 | 0.2 天 |
| C6 | 图片目录无定期清理；`review_logs` 无保留策略 | `images/handler.py` | 夜间 `images-prune`；磁盘告警 | 0.5 天 |
| C7 | 预热需要在上线前完成，否则首批用户在学习时付内容生成的延迟 | `ai/prewarm.py`；`budget.py:223-227` | 上线前把预热子上限与日 / 月上限临时调高，一次性跑完 9,162 词 | 配置 |

**D. 为二进制客户端准备（iOS 阶段）**：见 4.3。

### 3.4 成本模型

单价（Claude Sonnet 5.5，API 牌价 $2 / $10 每百万 token，全球路由、5 分钟缓存；核验按本机 token 画像重算）：

| 项目 | 单价 | 说明 |
|---|---|---|
| 例句（10 词一批） | $0.0445–0.0482 / 次，即 $0.0045–0.0048 / 词 | 约 3,800 输出 token；`thinking_tokens` 为 0，调 effort 无法省钱 |
| 例句（单词调用） | $0.0086–0.0108 / 词 | 清闲时自添词多半单独成批，成本约 2 倍 |
| 校验（lookup） | 估算 $0.004 + $0.002 × 词；**从未实测** | 20 词一批 |
| SVG 概念卡 | $0.0101–0.0112 / 张 | 仅在照片未命中时为被学习的词绘制 |
| 夜间整理 | $0.010–0.017 / 用户·晚（词库 2,000 词时趋近 $0.07） | 仅词库有变动的夜晚 |
| 一次性预热 9,162 词 | $41–44；Batch API $20–22；Haiku 5.5 约 $2（质量未验证） | 默认 $1/天 子上限下需约 6 周，应临时放开 |
| 种子词全部预绘 SVG（可选） | 约 $93；Batch 约 $46 | 先测真实照片命中率再决定 |

规模推算（每活跃用户每月，预热完成后）：

| 组成 | 金额 | 假设 |
|---|---|---|
| 自添词 | $0.4–3.0 | 每天 1–4 个新词，含校验与可能的 SVG |
| 夜间整理 | $0.3–0.5（随词库增长） | 每月约 30 晚 |
| 首学种子词的 SVG 兜底 | $2.3–7.6（小用户量时）→ 随共享缓存饱和趋近 0 | 每天 25 词 × 未命中率 0.3–1.0；默认子上限封顶全站约 $15/月 |
| **合计** | **约 $0.7–3.5 文本 + SVG 项** | 列表价；Batch 与 Haiku 可再降 |

- 100 活跃用户：约 $70–350/月 文本 + SVG（≤ $15/月 或按放开后的子上限）；Start 层 $500/月 上限基本够用，但默认的 $3/天、$40/月、60 次/小时 都必须上调，否则第一小时就开始顺延。
- 1,000 活跃用户：按核验后的单价约 $0.7–3.5k/月 外加 SVG 项；按代码现状（每晚每人整理、单词调用居多）与本机账本价则是 $1.5–4.5k/月。两者都超过 Start（$500）与 Build（$1,000）层的支出上限；每晚 1,000 次整理在 60 次/小时 下跑不完（16.7 小时），并发 1–3 的 CLI 吞吐也接近极限——这是把夜间任务挪到 Batch API、把整理改为 3 天一次或按需触发的理由（第 6.3 节给出杠杆后的区间）。
- 其他固定成本：VPS $9–24/月、域名约 $10–15/年、事务邮件服务商（多数有免费档）、Apple Developer Program $99 / ¥688 每年、对象存储备份数美元/月。

### 3.5 容量与运维边界

- 单进程 + 40 线程池 + 每请求新建 SQLite 连接 + 每次写请求至少一次限流计数写入：现实上可承载几十到低几百并发学习者；先撞上的墙不是 HTTP，而是全局 AI 预算与串行的 IoWorker。
- 水平扩展没有路径：第二个 `wd serve` 只能是同一 SQLite 文件上的只读副本；跨主机需要换数据库、队列、锁与图片存储，属于重设计。对一个爱好项目，单机是合理的长期形态，前提是上面的配额与告警到位。
- 升级要停服（迁移时间 + 约 3 秒）；恢复要停服；前端在生产机上构建（需要 Node 与内存）。

## 4. iOS 应用分析

### 4.1 「功能对等」的定义

必做（15 个学习者路由，约 8,000 行页面与组件 TSX + CSS）：`/login`、`/register`（含首位管理员与邀请码模式）、`/welcome`（两步引导 + 筛词）、`/today`、`/study`（乐观评分 + 持久化的待同步队列与重试、10 分钟后复现、服务端撤销、例句四态与「生成例句」、批内推荐词、会话总结、历史批次回放）、`/screen` 与 `/screen/:stage`（滑动 + 撤销）、`/vocab`、`/words/:id`（含举报、换图、易混、历史）、`/bank`、`/bank/add`（实时预览、候选词、今天就学）、`/bank/suggestions`、`/history` 与 `/history/:batchId`、`/settings`（推送 / 学习 / 账号，含邮箱验证、webhook 测试、改密、删号、导入导出），以及 en-US / en-GB 发音与自动发音、跟随系统的深色模式、TabBar 两种角标、错误重试态与 401 处理。

可以不做或延后：整个 `/admin`（21 个端点、约 1,400 行，手机上本就只能手输地址进入）、键盘快捷键与 `<kbd>` 提示、桌面批量选择与 `batch-mark`、数字分页器、`<a download>` / `<input type=file>` 的具体机制（换成分享面板与文件选择器，端点不变）、跨标签页同步。

移植时的验收标准应直接搬用页面级测试里钉住的行为：暂存评分重发失败按退避重试、未确认的已掌握撤销不打服务端、双击只评一张卡、250 ms 触控锁、待校验词轮询后变为已校验、webhook 失败文案不回显英文诊断、JSON 导入剔除 `review_logs` 等。

### 4.2 四条路线对比

| 路线 | 代码复用 | 到 TestFlight | 持续维护 | 体验 | 审核风险 | Android | 需要的后端改动 |
|---|---|---|---|---|---|---|---|
| A. PWA / 主屏网页应用 | ≈ 100%（+0.5–1 千行：manifest、service worker、订阅按钮、Share 导出） | 不上架；1–2 周可装机 + 推送 | 最低，一套代码，无年度 SDK 死线 | 已是移动优先；无振动反馈、仅系统内置语音、导出走分享面板 | 无 | Chrome 可安装；Android 推送依赖 FCM，大陆不可用 | Web Push：订阅表 + VAPID + `send_webpush` 任务 |
| B. Capacitor 8 → 9 | ≈ 95%（17 页与 CSS 不动；平台适配层 0.5–1 千行） | 1–2 周可跑；3–5 周到能过 4.2 的版本 | 低–中：一年一个大版本 + Apple 四月 SDK 死线 + 插件升级 | WKWebView 渲染、原生外壳、插件提供触感 / 系统 TTS / 推送 | **中–高**（4.2「套壳网站」） | 技术上顺带，大陆商店需 ICP + 软著 + 主体 | token 或签名媒体 URL；APNs 设备表 + `send_apns`；版本协商；CSRF 不用改（CapacitorHttp 不发 Origin） |
| C. Expo SDK 58 / RN 0.88 | ≈ 13–16%（api、utils、queue、zh.ts） | 6–10 周（去掉管理页 5–8 周） | 中：季度 SDK 升级、EAS、第二套 UI 与网页同步 | 原生导航 / Tab、触感、系统 TTS、可做小组件 | 低 | 同一代码；同样的大陆商店门槛；FCM 问题 | bearer token；APNs；版本协商 |
| D. SwiftUI（iOS 17/18 起） | 0%（契约 100% 复用；需移植 `srsPreview` 288 行与队列 reducer 373 行） | 8–14 周（不熟 Swift 再加 4–8 周） | 最高：两套 UI、Swift / SDK 年度变动 | 最佳（小组件、实况活动、Siri） | 最低 | 无 | bearer token；APNs；版本协商；导出 OpenAPI |
| Flutter | 0% | 8–14 周 + Dart 学习 | 高（第三个生态） | 自绘 UI，非系统观感 | 低 | 有 | 同 C/D |

决定性的事实：前端 87% 是 DOM 与 CSS，所以只有 A、B 不用重写 UI；同源 cookie + CSRF + cookie 保护的 `/media` 设计迫使每条商店路线都做 token 或签名 URL；4.2 是唯一的大风险且只落在 B；iOS 26 的默认主屏应用 + Web Push + 现成的 Bark 已经给出「装在手机上、每天有提醒」；任何商店路线都要 $99/年 + Xcode 27（或 EAS）+ 年度 SDK 死线；大陆 Android 分发受阻于 ICP / 软著 / 主体，与技术无关。

本机前提：macOS 26.7.1、Apple Silicon、823 GiB 可用，满足 Xcode 27.2（需 macOS 26.6+，仅 Apple Silicon）；尚未安装 Xcode（3.1 GB 下载 + 模拟器运行时数 GB，走代理网络要预留数小时）。Expo + EAS 是唯一不装本地 Xcode 也能出签名包的路线（免费档每月 15 个 iOS 构建，低优先级队列）。

### 4.3 任何原生 / 混合客户端都需要的后端改动

| 项 | 内容 | 出处 | 估算 |
|---|---|---|---|
| Bearer token 模式 | `sessions` 表已是通用令牌存储：`deps.current_user` 接受 `Authorization: Bearer`；登录 / 注册加返回 `{token, expires_at}` 的变体；带 Authorization 的请求跳过 Origin 检查；改密 / 停用 / 删号的吊销自动继承；可选 `client` 列与 `GET/DELETE /api/auth/sessions` 设备管理 | `docs/SCHEMA.sql:87-96`；`deps.py:142-181`；`security.py:174-205` | 1–2 天 |
| `/media` 鉴权 | WebView 的 `<img>` 不能带 Authorization，也跨站不带 cookie：签名 / 带过期的媒体 URL，或 token 查询参数；原生 `AsyncImage` / URLSession 用 cookie 或头即可 | `routers/media.py:38-57` | 1 天 |
| APNs 渠道 | `device_tokens` 表 + `POST/DELETE /api/devices`；`user_settings.apns_enabled`、`push_batches.apns_status`；`send_apns` 任务（需重建 `jobs` 表的 CHECK）；HTTP/2 持久连接 + `.p8` ES256 JWT（venv 缺 `h2`、`cryptography`）；410 剔除、`apns-collapse-id: batch:<id>`；`WD_APNS_*` 配置与掩码 | `delivery/webhook.py` 类比（407 行 + 497 行测试） | 5–8 天（约 800–1,100 行含测试） |
| 版本协商 | `/api/health` 增 `api_version` 与 `min_client_version`；客户端发送版本头；只做加法演进；对过旧客户端返回明确错误 | `routers/health.py:38-44` | 1 天 + 流程纪律 |
| OpenAPI 导出 | `wd openapi` 命令离线生成并提交；后处理补 securitySchemes 与错误信封（仅 Swift 代码生成需要） | `main.py:526-533` | 0.5 天 |
| Universal Links | `/.well-known/apple-app-site-association` 的显式 JSON 路由（SPA 兜底会返回 HTML）；`WD_PUBLIC_URL` 必须是 https | `main.py:242-260` | 0.5 天 |
| 审核账号 | 邀请制下给审核员预建账号并预生成内容；App Review 需从美国访问服务器 | `config.py:321` | 配置 |

### 4.4 推送方案对比

| 方案 | 后端工作 | 用户侧 | 限制 |
|---|---|---|---|
| Bark（现成） | 0 | 装 Bark、粘贴 URL、选格式 | 第三方中继、一人一设备、key 明文；点击打开 `<WD_PUBLIC_URL>/today` |
| 邮件（现成） | 需 SMTP / 事务服务商 | 验证邮箱 | 送达率、大陆邮箱对境外发件的接收 |
| Web Push（PWA） | 与 APNs 同量级：订阅表、VAPID、`send_webpush`（`pywebpush`）、`sw.js` 与 manifest | iOS ≥ 16.4 须先加到主屏，再在手势里点「开启提醒」；主屏应用的存储与 Safari 隔离，需再登录一次 | 推送无通知显示会被撤销权限；角标需通知权限；无本地定时通知；Android 依赖 FCM |
| APNs（原生 / 混合 App） | 见 4.3 | 系统弹窗授权 | 需 $99 账号、`.p8` 密钥、HTTP/2 栈；唯一能直接打开 App 并控制角标的方案 |

### 4.5 iOS 实现要点（按路线通用）

- 发音：`AVSpeechSynthesizer`，`AVAudioSession` 设为 `.playback` 可绕过静音开关；Web Speech 在 WKWebView 与 Safari 里只暴露预装语音（Samantha / Daniel 恰好匹配现有正则）、首次需用户手势、跟随静音开关。
- 待同步队列：`wd.pendingGrades` 必须持久化到 `Preferences` / `AsyncStorage` / `UserDefaults`，并以相同 `client_event_id` 幂等重放；Capacitor 文档明确 WebView 的 localStorage 可能被系统清理。
- 轮询：统一成一个感知 `AppState` / `scenePhase` 的轮询器（现在换图轮询没有可见性门控）。
- 导入导出：主屏网页应用里 `<a download>` 会卡在「打开方式」面板（WebKit bug 290847），用 `navigator.share({files})`；Capacitor 用 `@capacitor/filesystem + @capacitor/share`；原生用分享面板与文档选择器；导入仍发 JSON 体，沿用 1 MiB 上限与剔除 `review_logs` 的逻辑。
- 401 语义：只有信封 `code=unauthorized` 才登出，`invalid_credentials` 不登出；423 显示 `retry_after_s`；429 遵守 `Retry-After`；评分的瞬时失败（0 / 429 / ≥ 500）重试，其余为终态。
- 不要每次启动重新登录（20 会话上限 + 登录 IP 限流）。
- 可访问性：网页已有 190 个 `aria-*`、44 pt 触控目标、`prefers-reduced-motion`；原生需对应 `accessibilityLabel`、Dynamic Type、Reduce Motion。
- 深色模式：仅跟随系统，两套调色板的十六进制值在 `styles/tokens.css`，可直接搬进 asset catalog。
- JS 运行时（RN 路线）：纯 TS 用到 regex lookbehind、`String.normalize('NFKC')`、`Intl.DateTimeFormat` 带 IANA 时区、`TextEncoder`、`crypto.randomUUID`，先在 Hermes 上跑现有 vitest 再声称「原样复用」。

### 4.6 App Store 审核要点

| 条款 | 现状 | 要做 |
|---|---|---|
| 4.2 最低功能性（「超越重新打包的网站」） | Capacitor / WKWebView 路线的最大风险；2025–2026 仍有混合应用被连续拒绝的报告 | 打包本地资源（不要 `server.url` 远程壳）、APNs、离线今日批次缓存、触感、系统 TTS、分享导出、审核说明附演示账号；预留 1–2 周往返 |
| 4.8 登录服务 | 仅用户名 + 密码，豁免 Sign in with Apple | 将来加微信 / Google 登录时才需要 |
| 5.1.1(v) 应用内删号 | `DELETE /api/account` 已有 | App 内暴露同一流程；隐私政策说明去标识的公开词与日志保留 |
| 1.2 用户生成内容 | 举报端点、管理员队列、停用用户、`safe_for_sharing` 门控已有；2026 年三次收紧 | 应用内联系方式与隐私链接；审核说明里描述过滤机制；保持举报处理及时 |
| 5.1.2(i) 第三方 AI 披露（2025-11-13 起） | 用户键入的词与备注前 120 字会送到 Anthropic | 首次添加生词前的一次性具名披露与明确同意；隐私标签「与第三方共享的用户内容」 |
| 5.1.1(i) 隐私政策与隐私标签 | 无 | 元数据与应用内链接；标签：联系信息（可选邮箱）、标识符、用户内容（备注、添加的词）、使用数据 |
| 2.1(a) 完整性 | 默认邀请制 | 审核说明附演示账号与预生成内容 |
| 年龄分级（2025 新问卷） | 4+ 可行 | 声明 UGC 能力、「社交媒体 = 否」、署名链接用 `SFSafariViewController` 避免「无限制网页访问」 |
| 出口合规 | 仅 HTTPS | `ITSAppUsesNonExemptEncryption = NO` |
| ICP 字段 | 「如适用」 | 不勾选中国大陆即不涉及（见 5.3） |
| 3.1.1 | 免费 | 保持免费可避开付费协议与 IAP |

## 5. 发布与分发

### 5.1 Web

1. 域名（境外注册商）、Caddy 同机终止 TLS、`WD_HOST=127.0.0.1`、`WD_TRUST_PROXY=1`、`WD_PUBLIC_URL=https://<domain>`（决定 CSRF 允许的 Origin、cookie `Secure`、所有推送链接）。
2. DNS 生效前先用 `wd create-admin --if-none` 建好管理员，否则第一个访客成为管理员（`/api/health` 会广播 `needs_setup=true`）。
3. 起步 `WD_REGISTRATION_MODE=invite`，用邀请码分发给种子用户；开放注册只在 A5 到位后。
4. 上线前一次性预热种子词（临时调高 `WD_AI_PREWARM_DAILY_BUDGET_USD`、日 / 月上限）；上线后从干净出口测照片命中率再定 SVG 子上限。
5. 升级流程维持 `git pull && deploy/install.sh`（短暂停服）；备份异地化。

### 5.2 iOS：从账号到上架

1. **Apple Developer Program**：在 iPhone 的 Apple Developer App 以个人身份注册（¥688/年，支付宝 / 微信 / 银行卡，不能用账户余额；身份证拍照核验；通常 24 小时内确认）；卖家名显示法定姓名，想用公司名需要法人实体 + D-U-N-S（约 1 周）。
2. **工具链**：安装 Xcode 27.2（Mac App Store，3.1 GB 下载；另需 iOS 27 模拟器运行时）；2026-04-28 起上传必须用 Xcode 26 + iOS 26 SDK，2027 年 4 月起要求 iOS 27 SDK，所以直接从 Xcode 27 开始；部署目标 ≥ iOS 13（建议 iOS 17/18，覆盖约 80–86% 设备）。Xcode 自动签名管理证书与描述文件。CI 可选 Xcode Cloud（会员含 25 小时/月）、GitHub Actions macOS runner（$0.062/分钟）、EAS（Expo 路线）。
3. **App Store Connect**：创建 App 记录（Bundle ID、名称、分级、隐私政策 URL、隐私标签、截图：6.9 与 6.5 英寸 iPhone，若支持 iPad 另加）。
4. **TestFlight**：内部测试 100 人（即时）；外部测试最多 1 万人、公开链接可限额，首个构建需 Beta App Review（适用完整审核指南）；构建 90 天过期，每 24 小时最多提交 6 个构建；自 2025-01 起 Apple 可按 IP 对受法律限制的 Beta 做地域限制（目前仅见于美国 TikTok 案例）。
5. **App Review**：Apple 声称 50% 在 24 小时内、90% 在 48 小时内；首个版本按 2–3 轮准备；版本更新可分阶段发布（首发不可）。
6. **周期性义务**：每年续费；每年 4 月 SDK 死线；Capacitor 每年一个大版本；Expo 每季度一个 SDK。

### 5.3 中国大陆分发的现实

- App Store：在 Pricing and Availability 中不勾选中国大陆，ICP 字段即不适用；若勾选，大陆注册的开发者账号在新 App 提交时会被要求填备案号，否则状态为「ICP Filing Number Missing：你的 App 在中国大陆不可用」；境外账号目前实际上仍能不填发布（2026 年 7–10 月的从业者报告与仍在架的海外独立开发者 App 为证），但这是选择性执法，不要把计划建在上面。
- TestFlight：没有地域限制（Apple 员工 2021 年论坛答复；TestFlight App 本身在中国区在架），大陆 iPhone 用户可通过公开链接安装；但 MIIT 的备案义务落在运营者身上，TestFlight 只是绕开了 Apple 的检查，不是法律豁免。
- Android：大陆各商店要求 ICP + 软件著作权 + 中国主体或本地发行商，没有 Google Play；Capacitor / RN 的 Android 产物在大陆只能以 APK 链接侧载。
- 主屏网页应用：Apple 对主屏网页应用没有任何地域限制；网站本身若境外托管也不受备案约束，只承担被墙风险。

### 5.4 作为开源软件发布给他人自托管

仓库已经是公开的 MIT 项目，这本身就是一种「让他人使用」的发布方式。要让别人能顺利部署，需要：去掉 `sqin` / `/home/sqin` 的硬编码与交互提示（C3）、把 API key 模式做成一等公民并写进 `DEPLOY.md`（2.2）、提供 Dockerfile（迁移 Messages API 后）、打版本标签与 Release 说明、在 README 写明 Anthropic 条款与地区限制以及中国境内合规提示，让每个自托管者自己承担与评估。

## 6. 推荐路线图

> 本节综合自 3 套独立路线图（Web 优先 / 先上架的 Capacitor / 原生对等的 Expo）与 3 位评审从产品、工程、合规与成本三个视角的打分：三位评审都把「Web 优先、iOS 由证据决定」评为最佳（53 / 53 / 50.5 分，满分 60），另两套分别为 35 / 40 / 35.5 与 30 / 36 / 34.5。下文吸收了另两套方案的可取之处并修正了评审指出的错误（附录 8.3）。阶段 1–3 的顺序是强建议；阶段 4 是一个明确的决策点而不是既定计划。工作量按一名有经验的全职开发者估算，兼职则日历时间大致翻倍。

### 6.1 决策树（iOS 不是一个答案，而是一棵树）

- **Q0（第 1 周，书面 go / no-go）**：你本人与目标受众是否在 Anthropic 支持地区？能否以支持地区的注册 IP、账单国与支付方式开设 Console 组织？
  - 否 → 基于 Claude 的公共服务不上线；Mac 保留为个人实例；面向大陆的版本只能是另一个产品（已备案国产模型 + 有营业执照的主体做登记）。iOS 的问题随之消失。
  - 是 → 进入阶段 1。
- **Q1（阶段 1–2 期间，由注册地区数据回答）**：受众是否以中国大陆为主？
  - 是 → App Store 路线被结构性关闭（大陆 Apple ID 装不了其他地区商店；中国区上架需要挂钩大陆主机的备案，Claude 没有登记路径）。iOS 的终局答案是主屏网页应用 + Bark + Web Push；阶段 4 不启动；大陆用户在地区门控下只能使用预生成内容与字典模式。
  - 否 → 进入 Q2。
- **Q2（开放注册约 12 周后的证据闸门）**：是否出现任一信号——iPhone 用户占比高但主屏安装 / 推送开启率持续偏低；用户明确索要 App Store 版本；你需要小组件、本地提醒或 Siri；商店可发现性成为增长瓶颈？
  - 否 → PWA 即产品，6 个月后复议。
  - 是 → Q3。
- **Q3（路线）**：要最快的商店存在感且接受 4.2 风险 → **Capacitor**（默认；约 7 周；先 TestFlight；预先约定两次 4.2 拒绝即回退到 TestFlight + PWA，后端工作保留给后续路线）。原生打磨与商店本身就是目标、并接受第二套 UI 的长期维护 → **Expo / React Native**（多 5–8 周；EAS 云构建可以不装本地 Xcode）。只有小组件 / 实况活动 / Siri 是目标且你会写 Swift → **SwiftUI**。Android 在任何路线下都只是可侧载的 APK，不进大陆商店。

### 6.2 阶段与退出标准

| 阶段 | 历时 / 工作量 | 目标 | 主要工作（编号见第 3.3、4.3 节） | 退出标准 |
|---|---|---|---|---|
| **1. 公开服务器与邀请制内测** | 5 周 / ≈ 23.5 人日 | 从 Mac 迁到东京或新加坡 VPS，用 API key 认证 Claude，在第一个受邀用户之前上线地区门控、法律层、备份、告警与 CI | Console 组织；`WD_ANTHROPIC_API_KEY` 一等配置 + `--bare` + 分类器补 429 / 额度用尽短语 + 钉住 `claude-sonnet-5-5`；布局通用化（代码到 `/opt`、数据到 `/var/lib`，去 `sqin` 化，`ProtectHome`）；`install.sh --with-caddy`、`WD_HOST=127.0.0.1`、同机终止 TLS、先 `wd create-admin --if-none` 再解析 DNS、公开模式强制持久 `WD_SECRET_KEY`、2–4 GB swap；**地区门控**（按请求判定，触发端点返回 503，标记路径只跳过入队而不报错，夜间整理跳过）；预热种子（**同时上调月 / 日 / 预热 / 小时上限**，否则 $40 月上限在约 750 次调用后把预热推迟到下月）；内测上限基线 + Pixabay / Pexels key + 实测照片命中率；A3、A4、A8、B1–B4；GitHub Actions CI；restic 异地备份 + 恢复演练 + `images-prune` 入夜间维护；告警到 Bark；永久演示账号；staging 数据目录 | HTTPS + Secure cookie + HSTS，`:8000` 外部不可达；`wd claude-check` 无隧道通过，账本显示 `claude-sonnet-5-5` 与真实花费；≥ 99% 种子词有内容且花费 ≤ $55；用 CN 出口 IP 验证门控生效、向 Anthropic 的书面询问已发出；20–50 位受邀者连续 7 天学习、零预算事件；恢复演练与告警各演练一次；每个新账号有 `terms_accepted_at`；CI 绿色 |
| **2. 开放注册与词库治理闭环** | 5 周 / ≈ 24.5 人日 | 让陌生人安全注册，不让一个账号耗尽全员 AI，不让坏词进入共享词库，贡献者看得见自己的贡献 | 事务邮件 + SPF / DKIM / DMARC（验 QQ、163、Gmail）；验证码发送移出请求线程 + 第二个 IoWorker；触发 AI 的动作要求已验证邮箱；找回密码（A6）；A1、A2（`ai_calls.user_id`、按用户每日触发配额、整理间隔 3 天、配额日按用户时区）；用户可见的 `ai_status`（区分「你的今日额度」与「服务今日额度」）与公开 `/status` 页；B5 词库治理（管理员词条 API 与页面、`WD_PUBLIC_WORDS_REQUIRE_REVIEW` 隔离开关并覆盖 ECDICT 直接公开路径、禁止 Claude 重命名 / 合并种子或已公开行、脏词表、图片举报阈值 3、换图改为用户级偏好、`wd words-audit`）；贡献许可 + `wd export-words` 回流 + 「我的贡献」与「你的词已公开」通知；未成年人措施（child-safety 提示词要点、生成例句敏感词过滤）；注销时清理 `claude-logs`；A5（Turnstile 的大陆可达性需实测）后 `WD_REGISTRATION_MODE=open` | 首月 ≥ 100 自助注册且 < 5% 触发配额 429；共享 NAT 多用户测试通过；无单用户超过日成本 10%；14 天零 `budget_daily`；验证码 < 60 s 送达；每个公开用户词有 `curation_state`、至少一次通过 UI 完成下架 / 合并、举报 48 小时内处理；QQ 邮箱与 Gmail 重置端到端成功；首份回流 JSONL 已审阅并提 PR（或记录不做的决定） |
| **3. iPhone 级网页应用与 iOS 闸门证据** | 4 周 / ≈ 19 人日 | 不依赖 Apple 把网页做成最好的 iPhone 体验，并埋下决策所需信号与二进制客户端的廉价准备 | **一次性重建 `jobs` 表同时加入 `send_webpush` 与 `send_apns`**（并改 `test_registry_complete` 读取有效 schema）；Web Push（订阅表、VAPID、发送器、404 / 410 剪除）；manifest + PNG 图标 + service worker（单独 no-cache 路由）、手势内订阅按钮、角标、微信内置浏览器检测与「在 Safari 中打开」引导、standalone 下用分享面板导出；投递状态可见、Bark 测试带 URL、脱敏 device key；埋点（平台、display-mode、推送开启率、留存、地区）；`api_version` / `min_client_version` + `X-WD-Client` 的 426 中间件、`wd openapi` 导出与漂移测试、AASA / assetlinks 路由；把学习会话编排提取为平台无关的 SessionController；限时 Messages API spike（Haiku 校验 + Batch 整理的实测成本与质量） | iOS 26 手机在 `push_time` 收到 Web Push、角标正确、点按打开 `/today`；从微信打开的用户能完成安装与订阅；迁移在副本演练后一次完成；埋点累积 4 周数据；426 与漂移测试在 CI 运行；spike 报告给出 runner 切换的 go / no-go |
| **4. 决策闸门 →（有条件）Capacitor** | 7 周 / ≈ 25.5 人日 | 按 Q1–Q3 决定是否值得 $99/年 与年度 SDK 死线；若是，15 路由对等 + APNs，先 TestFlight，再 App Store（不含中国大陆） | 闸门记录与带日期的维护日历；Apple Developer Program、Xcode 27.2、App ID、`.p8`；Capacitor 项目（bundled dist、CapacitorHttp + CapacitorCookies、绝对 API base、平台适配层：TTS / 文件 / 分享 / Preferences 存 outbox / AppState 轮询 / 触感）；后端 bearer token（**存 Keychain 类插件，不是 Preferences**）+ 签名媒体 URL（有效期对齐会话，避免每天改 URL 打破 immutable 缓存）+ 设备会话管理 + APNs 发送器（HTTP/2、ES256 JWT、410 剪除、collapse-id）；4.2 差异化（离线今日批次、触感、原生分享、可选小组件）；审核包（演示账号、隐私政策 URL、5.1.2(i) 明确同意、UGC 说明、4+ 分级、`ITSAppUsesNonExemptEncryption=NO`、不勾选中国大陆） | 书面 go / no-go；若 go：TestFlight 构建在 iOS 26/27 设备通过 15 路由对等清单、APNs 按时送达、评分 outbox 在 App 被终止后仍无重复回放；App Store 在大陆以外获批，或两次 4.2 拒绝后记录留在 TestFlight + PWA、后端工作保留 |

合计约 92.5 人日；阶段 1–3 约 67 人日，即约 14 个全职周到 iOS 闸门。每个阶段都独立产生价值：阶段 1–2 本身就是「让公众使用并壮大词库」，阶段 3 之后随时可以停。

### 6.3 成本预期

- 一次性约 $60–115：域名 $10–15、种子预热 $41–49、Console 首充；阶段 4 触发再加 $99（¥688）。
- 100 活跃用户：稳态约 $150–300/月；前 1–2 个月可能 $350–500，因为筛词与自添词需求、首学种子词的 SVG 兜底跑在共享缓存前面。在 Console Start 层之内。
- 1,000 活跃用户：按代码现状与账本价约 $1.6–4.7k/月；启用整理 3 天间隔、全量预热、Batch 整理与 Haiku 校验后约 $0.5–0.9k/月（标注为最佳情形）。需申请 Build 或 Scale 层；此时下一道天花板是单进程 SQLite 与串行 IoWorker，而不是 Anthropic 的速率限制。

### 6.4 前两周（阶段 1 起步）

1. 第 1 天：书面回答 Q0 与第 7 节的 D1–D5、D10；创建 Console 组织、API key 与 $100/月 支出上限；购买域名；租 VPS；开对象存储桶；向 Anthropic 支持发出关于缓存输出的书面询问；暂不解析 DNS。
2. 第 2–3 天：分支实现 `WD_ANTHROPIC_API_KEY`（配置、`claude_env`、掩码、`install.sh` 校验器、文案、测试）、分类器补丁、钉住模型 id、在 key 下试 `claude -p --bare`；提交 GitHub Actions 工作流并取得第一次绿色。
3. 第 3–4 天：布局改造（`/opt` 与 `/var/lib`、`WD_CLAUDE_HOME`、unit 渲染、`ProtectHome`、去 `sqin` 默认值与 pinned tests、非交互安装、公开模式强制 `WD_SECRET_KEY`）。
4. 第 4–5 天：VPS 上 `deploy/install.sh --with-caddy DOMAIN --contact-email ADDR`；`.env` 设置 `WD_HOST=127.0.0.1`、`WD_TRUST_PROXY=1`、`WD_PUBLIC_URL=https://DOMAIN`、`WD_REGISTRATION_MODE=invite`；`wd create-admin --if-none` 后清除引导密码；验证 `api.anthropic.com`、Wikimedia、Openverse、`api.day.app` 直连可达；然后才解析 DNS、开放 443；搭 staging 数据目录。
5. 第 5 天：临时上调月 / 日 / 预热 / 小时上限与并发到 3，触发预热（约 3 小时、$41–49）；记录 claude 进程内存；完成后恢复内测上限并启用 Pixabay / Pexels key。
6. 第 6–8 天：地区门控（GeoLite2、按请求判定、触发端点 503、标记路径跳过入队、夜间整理跳过、管理页地区计数），用 CN 出口 IP 在 staging 验证；同时做限流改动（A3、A4、A8、注册枚举中性化、Caddy 层 GET 限流与 `/admin` IP 白名单）。
7. 第 8–10 天：法律层（`/terms`、`/privacy`、`/about`、同意勾选与 `terms_accepted_at`、14+ 自述、联系邮箱、逐块「AI 生成」标签、首次添加生词前的第三方 AI 告知、`ATTRIBUTION.md` 改为 Powered by Claude）；中文文本由你在第 8 天前提供。
8. 第 11–14 天：异地备份定时器与恢复演练、journald 限额、夜间 `images-prune`、告警 hook 到 Bark、外部拨测；创建演示账号；向 20–50 位（位于支持地区的）测试者发邀请码；每天看 `ai_calls`、`system_events`、`auth_throttle` 与 Caddy 日志，记录首周每活跃用户成本与照片命中率。

### 6.5 主要风险与对策

| 风险 | 可能性 / 影响 | 对策 |
|---|---|---|
| 真实受众在中国大陆：这些用户触发的实时 Claude 调用属不支持地区使用，Anthropic 可不经通知执法 | 高 / 高 | 地区门控在第一个受邀用户之前上线；ToS 写明受众；书面询问 Anthropic 对缓存输出的态度并为「否」准备整站 geo-block；runner 接缝保持可换供应商 |
| 运营者本人所在地不受支持（本机网络对 `api.anthropic.com` 返回 403） | 中 / 高 | 第 1 周书面 go / no-go；开 Console 组织前确认所在地、账单国、支付工具与注册 IP；生产流量绝不经过 Mac |
| 缓存输出可供不支持地区用户阅读的解读被 Anthropic 否定 | 中 / 高 | 整站 geo-block 该人群；大陆受众的 AI 功能只能来自另起的国产模型版本 |
| GFW 成批封锁域名或 IP | 中 / 中 | 300 s TTL、换 IP 手册、不依赖第三方 CDN；视为可达性风险而非法律风险 |
| 热情用户群或恶意账号耗尽预算，AI 对全员关闭到次日或次月 | 高 / 中 | 按用户配额与归因、验证邮箱门控、3 天整理间隔、上限按用户数放大、`budget_*` 告警、Console 支出上限作硬停 |
| 共享词库污染：Claude 的 `safe_for_sharing` 是唯一门控，管理员不用 SQL 无法下架 | 中 / 中 | 阶段 2 策展工具、隔离开关、重命名 / 合并保护、脏词表、举报 SLA |
| 单进程 SQLite 与串行 IoWorker 在登录风暴、批量标记与 08:00 投递潮先于 HTTP 容量退化 | 中 / 中 | 第二个 IoWorker、验证码异步、分散默认推送时间、上调并发与小时上限；持续 > 300 并发或队列滞后 > 1 小时时再考虑 Postgres / 对象存储 |
| `--bare` 成为 `claude -p` 默认或 CLI 升级改变输出信封，现有 runner 失效 | 中 / 高 | 阶段 1 切 API key 并采用 `--bare`；`install.sh` 固定 CLI 版本；Messages API runner 是结构性逃生口 |
| 阶段 4 的 Capacitor 构建被 4.2 拒绝 | 中 / 中 | TestFlight 先行；差异化证据；两次拒绝后按约定留在 TestFlight + PWA，后端工作转给后续路线 |
| 境外 VPS 的邮件到不了 QQ / 163，阻塞验证与找回 | 中 / 中 | 选有大陆投递能力的服务商，开放注册前实测三大邮箱；Bark / 企业微信 / 飞书继续承担提醒 |
| 微信内置浏览器是大陆手机主要入口，其中无法添加到主屏、订阅 Web Push 或过 Turnstile | 高 / 中 | 阶段 3 的微信检测与「在 Safari 中打开」引导；真机测试微信到 Safari 的交接与 `api.day.app` 可达性 |
| 单人时间：到 iOS 闸门约 14 个全职周 | 中 / 高 | 阶段 1 刻意小而偏基础设施；Web Push、投递可见性与 spike 可后移；阶段 1–2 不依赖 Apple |

### 6.6 评审指出、已并入上表的盲点

贡献者反馈闭环（没人告诉学习者他加的词被校验、公开、被他人学习）；获客与公开只读词页（等 Anthropic 对缓存输出的答复与策展工具稳定后再做）；微信入口；AI 预算日按 `WD_TZ` 重置对海外用户的不公平；用户不知道 AI 为何延期；投递状态对任何人都不可见；无邮箱用户的找回只到管理员（短信或恢复码未纳入）；开源自托管路径（API key 模式 + Docker）未被利用；词库质量的「好词」标准与全局去重；`ProtectHome` 与 `/home` 布局冲突；`jobs` 重建必须同时改读取 `0001_init.sql` 文本的测试；2 vCPU / 4 GB 机器要同时跑 2–3 个 claude Node 进程与宿主上的 `vite build`，需要 swap 与实测；GET 端点与导出无限流；没有 staging 环境。

## 7. 需要你决定的问题

| # | 决策 | 为什么现在就要定 | 影响 |
|---|---|---|---|
| D1 | 受众主要在中国大陆，还是境外华人 / 支持地区用户？ | 决定 Claude 能否承担实时功能、是否要地理门控、是否值得考虑国产模型 | 架构（预生成 vs 实时）、托管地、App 发行范围 |
| D2 | 是否接受为大陆用户换用已备案的国产模型（并成立主体做登记）？ | 这是中国区上架与大陆合规的唯一路径 | 模型质量评测、Messages API 迁移、公司主体 |
| D3 | 每月 AI 预算与可接受的活跃用户规模？ | 决定全局上限、按用户配额、是否预热与预绘 SVG | 成本上限、用户体验（顺延频率） |
| D4 | 要的是 App Store 存在，还是「装到 iPhone + 每日提醒」？ | 后者 1–2 周内用 PWA + Bark 即可；前者才需要 $99/年、Xcode、审核与年度维护 | 是否进入阶段 3 |
| D5 | 若做 App：优先最快上架（Capacitor，接受 4.2 风险）还是原生体验与 Android（Expo）？ | 决定后端 token / 媒体 URL 的形态与时间 | 3–5 周 vs 6–10 周 |
| D6 | 管理页是否进 App？ | 影响约 15% 的 UI 工作量与审核观感 | 建议留在网页 |
| D7 | 是否服务 14 岁以下用户？ | 决定年龄门槛 vs 监护人同意流程、Anthropic 未成年人指南、PIPL 敏感信息 | 注册流程、隐私政策 |
| D8 | 用户贡献词以何种许可接受？是否回流到 `data/seed`？ | 决定注册同意文本与 `provenance` 列 | 词库治理闭环 |
| D9 | 是否成立运营主体（境外或境内）？ | 影响 Anthropic 三要件、Apple 卖家名、中国备案资格 | 法律与税务成本 |
| D10 | 你的个人 Console 组织以哪个国家注册、如何付款？ | Anthropic 地区政策同样适用于运营者本人 | 整个 AI 路径的前提 |

## 8. 附录

### 8.1 证据索引

`docs/analysis/2026-11-03-public-launch/facts/` 下 9 个切片（每条结论带 `file:line` 或 URL 与置信度）：`auth-contract`（23 条）、`ai-runner-cost`（33）、`frontend-parity`（39）、`delivery-push`（25）、`public-readiness`（38）、`anthropic-policy`（24）、`apple-appstore`（34）、`china-compliance-hosting`（31）、`ios-tech-options`（36）。核验记录在 `verdicts.md`，路线图与评审在 `design-panel.md`。

### 8.2 对抗性核验结果摘要

| 结论 | 裁定 | 主要修正 |
|---|---|---|
| V1 订阅 / Enterprise 登录不能驱动公共服务；API key 是正道 | 基本确认 | 「订阅代理」禁令写在 2026-11-12 生效的新版使用政策里；Enterprise 的禁止依据是「普通使用」范围、具名席位与 Agent SDK 规则；10 月 7 日的 API 额度不含 Enterprise / Pro；`--bare` 将成默认 |
| V2 大陆 / 港 / 澳不受支持，政策覆盖最终用户 | 基本确认 | 三要件文本自 2026-10-08 发布；现行版通过「persons, entities, or users」与「passthrough」覆盖；缓存 vs 实时的区分是推理 |
| V3 中国区 App Store 需 ICP；TestFlight 无地域限制 | 基本确认 | Apple 的机制是「中国大陆不可用」状态而非拒审或禁更新；境外账号实际仍可发布（选择性执法）；Apple 自 2025-01 可按 IP 限制 Beta |
| V4 Xcode 26+ / iOS 26 SDK 自 2026-04-28 必需；Xcode 27.2 需 macOS 26.6+ | 基本确认 | Xcode 27.2 发布于 2026-10-29；iOS 27 SDK「2027 年 4 月起」无具体日；仅 Apple Silicon；上传须面向 iOS 13+ |
| V5 iOS 26 主屏网页应用默认独立运行；Web Push 自 16.4；Declarative Web Push 自 18.4 | 确认 | 推送仅限主屏应用；订阅须在手势处理器内；角标需通知权限；主屏应用存储与 Safari 隔离；Screen Wake Lock 已支持 |
| V6 Capacitor：CapacitorHttp 不发 Origin 可过 CSRF；`<img>` 跨站不带 cookie | 基本确认 | 相对路径必须改绝对 URL；存在重复 cookie 风险，建议 token；Capacitor 9 需 Xcode 27 + Node 24；CocoaPods trunk 2026-12-02 只读 |
| V7 生成式 AI 办法适用、Claude 无登记路径、标识办法要求就近标注 | 确认并加强 | 2026 清朗专项处置 1.4 万余款；华为应用市场要求算法备案号；教育 App 备案有背单词类公司在册；备案 / 登记数 1,112 / 731（2026-08-31） |
| V8 价格与实测成本 | 基本确认 | 账本价含 1.1× 美国专属系数等，牌价低 10–19%；SVG 占比是故障产物；`thinking_tokens` 为 0；每用户成本假设每天 1–4 个自添词并需加 SVG 项 |
| V9 标记触发的生成无配额；可信代理硬编码；用户名锁定可滥用 | 确认 | 洪峰上限为可见的缺内容词数（整个种子库约 92 次请求）；可自选优先级；无管理员取消；锁定无人能解 |

### 8.3 路线图评审摘要

三套独立设计（完整内容见 `design-panel.md`）：

| 设计 | 取向 | 阶段数 / 总工作量 | iOS 结论 | 到 App Store 的时间 |
|---|---|---|---|---|
| Web 优先 | 最小后悔：先让陌生人用起来，iOS 由证据决定 | 4 / 74.5 人日 | 现在不做原生 App；主屏网页应用 + Bark + Web Push；12 周后闸门，触发则 Capacitor | 闸门触发后约 7 周 |
| 先上架 | 不重写 UI 的前提下尽快有商店存在感 | 4 / 61 人日 | Capacitor 8 → 9 包壳；TestFlight 作为大陆渠道 | 约 16 周 |
| 原生对等 | 为长期而建的原生客户端 | 6 / 102 人日 | Expo / React Native（EAS 云构建），SwiftUI 仅在原生打磨是目标时 | 约 21 周 |

三位评审的打分（六项各 0–10，总分 60）：

| 视角 | Web 优先 | 先上架 | 原生对等 | 最佳 |
|---|---|---|---|---|
| 产品与目标达成 | 53 | 35 | 30 | Web 优先 |
| 工程现实性 | 53 | 40 | 36 | Web 优先 |
| 合规、法律与成本 | 50.5 | 35.5 | 34.5 | Web 优先 |

评审发现并已在本文修正的错误：三套方案的 1,000 用户成本都低于事实库的「代码现状」区间（本文同时给出两个区间）；两套方案在预热时只上调了日上限而没有上调月上限（`can_spend` 先查月上限）；三套都在只搬走 CLI 家目录的情况下打开 `ProtectHome=yes`，而数据目录、虚拟环境与工作目录仍在 `/home`；「原生对等」方案以「CSRF 与 cookie 会让 Capacitor 包壳无法工作」为由否定 Capacitor，与事实库相反（CapacitorHttp 不发 Origin，现有规则可过，只有 `<img>` 与下载需要改动）；「先上架」方案把 bearer token 存在 Preferences（UserDefaults）而非 Keychain，并把地区门控当作「可接受的风险」而非合规约束，还把 TestFlight 当作大陆分发渠道（与地区门控自相矛盾）。

从非获胜方案嫁接进第 6 节的内容：GitHub Actions CI；第二个 IoWorker；换图改为用户级偏好；`openapi.json` 与 `types.ts` 漂移测试；SessionController 无悔重构；`/admin` 的 Caddy IP 白名单；永久演示账号；注册枚举中性化与强制持久 `WD_SECRET_KEY`；发布节奏规则与预先约定的 4.2 回退；`jobs` 表只重建一次并同时容纳 Web Push 与 APNs；带日期的维护日历；地区门控提前到第一个受邀用户之前。

### 8.4 关键链接

- Anthropic：code.claude.com/docs/en/legal-and-compliance · code.claude.com/docs/en/agent-sdk/overview · code.claude.com/docs/en/authentication · anthropic.com/legal/aup · anthropic.com/supported-countries · anthropic.com/legal/commercial-terms · platform.claude.com/docs/en/about-claude/pricing · platform.claude.com/docs/en/api/rate-limits
- Apple：developer.apple.com/app-store/review/guidelines · developer.apple.com/news/upcoming-requirements · developer.apple.com/help/app-store-connect/reference/app-information · developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview · developer.apple.com/support/enrollment · developer.apple.com/xcode/system-requirements
- WebKit：webkit.org/blog/17333（Safari 26.0）· webkit.org/blog/13878（Web Push 16.4）· webkit.org/blog/16535（Declarative Web Push）· webkit.org/blog/14403（存储策略）
- 中国法规：gov.cn 生成式人工智能服务管理暂行办法 · cac.gov.cn 人工智能生成合成内容标识办法 · 工信部信管〔2023〕105 号 · 教技厅〔2019〕3 号 · 促进和规范数据跨境流动规定
- 工具链：capacitorjs.com/docs/getting-started/environment-setup · docs.expo.dev/billing/plans · expo.dev/changelog/sdk-58
