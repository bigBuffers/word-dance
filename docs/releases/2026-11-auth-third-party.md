# 注册与登录改造 切片 2-A：微信小程序登录桥、QQ 与 Apple 网页登录、第三方身份绑定（迁移 0020，暗上线）

> 设计：[`docs/AUTH_SIGNUP_DESIGN.md`](../AUTH_SIGNUP_DESIGN.md) §5.3「微信、QQ、Apple（第二步）」、§5.6 不变量；业主 2026-11-10 确认 D4（第二步做，带 D8 退出条件）、D6（A：Apple 登录网页 + iOS）、D8（备案在 1-A 上线后启动；小程序内容选 (a)）。上一切片：[`2026-11-auth-signup-1b.md`](2026-11-auth-signup-1b.md)。
> 状态：**〔待填：上线时间 / commit〕**。**暗上线**：`.env` 未改，三个第三方登录都没有配置（`ServerFlags.wechat_enabled / qq_enabled / apple_enabled` 为 false），用户看不到任何变化；等您完成 §3 的账号与备案步骤、把对应配置写入 `.env` 并重启，登录页和设置页的入口才会出现。

## 1 起因

- 第一步（1-A / 1-B）把账号锚在手机号 / 邮箱上，但同类产品的便利入口是微信；个人开发者唯一能用的是「个人小程序 + 备案域名 + 大陆最小中转」路线（设计 §3、§5.3），QQ 互联接受个人开发者（回调域须备案），Apple 登录只需个人开发者计划。
- 备案两道串行要 4–8 周，开发（约 1 周）与等待并行：代码先做成「无配置则不显示」，账号到位后只改 `.env`。

## 2 变更概览

| 领域 | 变更 |
|---|---|
| 数据库 | 迁移 `0020_wechat_tickets.sql`（纯附加，可 `--no-restart`）：新表 `wechat_tickets`（登录 / 绑定票据：小程序码场景值与配对码的哈希、轮询密钥哈希、状态机 pending → scanned → confirmed → consumed / cancelled）。`identities.provider` 的 `wechat_mini` / `qq` / `apple` 值（1-A 预留）本切片开始写入（subject = openid / openid / Apple `sub`，对任何人都不展示） |
| 微信登录桥 | 电脑网页：`POST /api/auth/wechat/ticket` 拿票 → 页面显示以票为场景值的小程序码 + 6 位配对码，每 2 秒 `GET …/ticket/{ticket}` 轮询（必须带发起浏览器的 HttpOnly 轮询 Cookie，否则一律 404）；手机网页 / 壳：同一部手机扫不了自己的屏幕，用户在微信里打开小程序「单词之舞」输入配对码。小程序先 `wx.login` 再 `POST /api/auth/wechat/scan`，**一律先显示确认页**（发起方 IP 掩码、浏览器、时间；绑定时写明绑到哪个昵称），用户点确认才 `POST …/confirm`——防二维码劫持；网页轮询到 confirmed 后一次性换成会话（票转 consumed）。票 3 分钟有效、一次性（确认后 60 秒宽限内网页仍可取到结果）；`session_key` 用完即弃，不入库不下发。中转机会把所有小程序请求汇成同一个来源 IP，所以小程序侧按 IP 的限流只是粗粒度刹车（600/分钟），真正的刹车按 openid（扫码 10/分钟、确认 20/分钟） |
| 新账号 | 未绑定的微信确认登录票时直接建占位账号（与 1-A 验证码建号同形：`needs_profile`，网页端走「首次设置」第 0 步）；`invite` 模式下网页先收邀请码、确认时消耗；`closed` 模式小程序提示暂停注册。**只用第三方登录的账号在首次设置时必须设密码**（修改资料 / 注销要用它验证身份——设计里的「微信再认证」改为这条规则） |
| QQ 登录 | `GET /api/auth/qq/start?kind=login\|bind` → 302 到 QQ 互联授权页 → `GET /api/auth/qq/callback`（备案域名上的回调，由中转机转发到本服务器）→ 把核验过的身份放进 60 秒一次性 grant → 302 到本站 `GET /api/auth/oauth/finish?grant=…`：**只有发起流程的那个浏览器能完成**（`/start` 时在本站种下 HttpOnly Cookie `wd_oauth`，其哈希签进 state 与 grant，`finish` 核对后才绑定 / 登录；绑定还要求当前会话就是发起绑定的账号）——评审发现未绑定浏览器时攻击者可把受害者的 QQ / Apple 身份挂到自己账号上并换掉受害者的会话，已修。回调域与站点域不同，会话 Cookie 不能直接跨过去，所以需要这一跳 |
| Apple 登录 | 网页重定向流（`response_mode=form_post`，不加载第三方脚本——CSP 禁止）：`GET /api/auth/apple/start` → Apple → `POST /api/auth/apple/callback`（CSRF 白名单中唯一的路径，签名的 `state` 是它的防护）→ 用 Apple 公钥本地校验 `id_token`（RS256，纯 Python 实现，无新依赖）→ grant → finish。iOS 壳内的 Apple 登录插件等 iOS 壳做出来再加 |
| 解绑 | `DELETE /api/account/identities/{provider}`（先按端点 7 的方式重认证；账号必须还剩至少一种登录方式；孩子账号不可） |
| 前端 | 登录页「其他方式登录」一行（按服务器开关显示微信 / QQ / 通过 Apple 登录；iOS 壳里微信 / QQ 等 Apple 一起上）；微信扫码 / 配对码弹层；设置页「登录方式」里每个已开启的第三方一行（绑定 / 已绑定 · 解绑）；回调出错时 `?error=` 提示、绑定成功 `?bound=` 提示；首次设置第 0 步对「只有第三方登录」的账号必填密码 |
| 开发自测 | `WD_AUTH_FAKE_PROVIDERS=1`（只允许在 `WD_DEV=1` 下）装上假的微信 / QQ / Apple：`make smoke` 跑通三条链路；开发者可在浏览器里走假授权页 |
| 小程序工程 | `miniprogram/`（原生 WXML / JS，三个页面：今日一句 + 配对码入口、输入配对码、确认页）+ README（注册、填 AppID、开发时「不校验合法域名」、发布前的服务器域名白名单） |
| 中转机 | `deploy/relay/`（备案域名上的 nginx：只转发 `/api/auth/wechat/*`、两个回调和 `/api/health`，其余路径一概不转；最小首页带两个备案号占位）+ README（购买、备案顺序、类目措辞、退出条件、核查风险） |
| 契约 | API.md §1（轮询 Cookie、CSRF 白名单）、§1.1 四个错误码（`provider_unconfigured`、`invalid_identity_token`、`invalid_grant`、`provider_error`）、§2 / §3.3 端点 112–122、§9 `User.providers`、三个开关、票据 DTO；DEPLOY §4 新增环境变量；无新增 Python 依赖 |

本切片不含：iOS 壳的 Apple 登录插件；订阅消息提醒；微信作为再认证因子（改为上面的设密码规则）。

## 3 启用步骤（都要您本人操作；代码已就位，每一项完成后只改 `.env` 并重启）

1. **小程序**（不依赖备案即可开发自测）：微信公众平台注册个人小程序「单词之舞」（类目：工具）→ 把 AppID 填进 `miniprogram/project.config.json` 与 `.env` 的 `WD_WECHAT_APPID`，AppSecret 存到一个 0600 文件并把路径写入 `WD_WECHAT_SECRET_FILE`；`WD_WECHAT_ENV="develop"`（未发布时小程序码只对开发者 / 体验者有效）→ 重启 → 登录页出现「微信」。微信开发者工具里勾「不校验合法域名」即可对着本服务器试全流程；正式发布前小程序后台的服务器域名要填备案域名。
2. **备案**（D8，两道串行 4–8 周）：境内注册商买备案域名 + 腾讯云大陆轻量主机预付 ≥ 3 个月 → 网站备案（服务内容「工具」，避免教育 / 培训字样）→ 小程序备案。管局若要求校外培训前置审批 → 放弃第二步（退出条件）。备案后按 `deploy/relay/README.md` 部署中转机，首页挂 ICP 与公安备案号。
3. **QQ 登录**：QQ 互联个人开发者认证（手持身份证照，1–2 个工作日）→ 创建网站应用，回调域填备案域名 → `.env`：`WD_QQ_APPID`、`WD_QQ_KEY_FILE`（0600 文件）、`WD_QQ_CALLBACK_URL="https://<备案域名>/api/auth/qq/callback"`。
4. **Apple 登录**：Apple 开发者计划（个人，年费）→ 创建 App ID + Services ID，验证域名，Return URL 填 `https://<公网 https 域名>/api/auth/apple/callback` → `.env`：`WD_APPLE_CLIENT_ID`（Services ID）、`WD_APPLE_CALLBACK_URL`。前提是站点有公网 HTTPS 域名（目前 Mac 上没有）。
5. 任一项启用后：`wd check` 的 third-party 行应显示 on；`GET /api/health` 的对应开关为 true；用假账号把登录 → 首次设置 → 设置页解绑走一遍。

Mac 上线（暗）：`git pull` 后按 1-A 的步骤构建前端快照并 `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`；启动时自动应用 0020 并写 `backups/pre-migrate-19-to-20.db.gz`。先在 `VACUUM INTO` 副本上跑 `scripts/rehearse_migration.py`（新增 `check_0020`，空库 30 表）。

## 4 验收

- 后端：`pytest` 全量 **2675 passed / 3 skipped / 1 deselected**（5 分 08 秒；`test_deploy_files.py` 在 Mac 上照例不跑）。新增 `test_db_0020.py`、`test_wechat_bridge.py`、`test_rsa_verify.py`、`test_apple_token.py`、`test_oauth_state.py`、`test_qq_client.py`、`test_auth_wechat.py`、`test_auth_oauth.py`、`test_identity_unbind.py`；0020 把 29 → 30 张表的各处固定断言一并更新。
- 契约：`make check-contract` OK（只剩 1-A 之前就有的 9 条可空性 note）；`test_docs_contract.py` 13 passed（API.md §9 == `types.ts`，FRONTEND §8 == `zh.ts`）；`test_api_schemas.py` 固定端点 1–122。
- 前端：`typecheck` 通过；vitest **60 个文件 / 537 个测试**；copy check OK；构建 `index` 348 KB（gzip 115 KB）。
- `make smoke`：**34 步通过**，新增 5 步在 `WD_AUTH_FAKE_PROVIDERS=1` 下跑通：三个开关、微信桥（拿票 → 假 `js_code` 扫码 → 确认 → 轮询拿到会话）、第三方账号的首次设置必须设密码 + 解绑最后一种登录方式 → 409、QQ（start → 假授权页 → callback → finish）、Apple（form_post 回调，CSRF 白名单）。
- 迁移演练：`scripts/rehearse_migration.py` 在线上库只读副本（schema 19，2 个用户）上 **115 项检查全部通过**：`wechat_tickets` 18 列、2 个索引（含 partial）、CHECK 与外键、二次运行无动作、空库 30 表。
- 对抗评审（8 个视角 + 逐条核实，30 个代理）：22 条成立（8 高、14 中；多个视角重复命中同一问题）、0 条驳回、33 条低风险未核实。成立项全部修复：① **OAuth 的 state / grant 没有绑定发起流程的浏览器**（5 个视角同时发现，高）——攻击者可把受害者的 QQ / Apple 身份挂到自己账号并换掉受害者的会话（也构成登录 CSRF）；修法：`/start` 种 HttpOnly Cookie `wd_oauth` 并把哈希签进 state 与 grant，回调只核验身份并放进 grant，`finish` 核对 Cookie 后才绑定 / 登录，绑定还要求当前会话就是发起者；② **中转机把小程序请求汇成同一个 IP**（4 个视角，高）——按 IP 的 30/分钟会变成全站上限：小程序侧放宽为 600/分钟并新增按 openid 的确认限流，网页侧票据 30/分钟·300/小时、轮询 1200/分钟，二维码不计入；③ Apple 未知 `kid` 触发无限制的 JWKS 重取 + 回调无限流（中）——每进程 60 秒最多重取一次，回调 600/分钟；④ state / `mp_token` 的非 ASCII 输入导致 500（中）——严格解析；⑤ 已确认的票过期后仍能换会话（中）——60 秒宽限后作废；⑥ `identity_taken` 对第三方身份显示手机号文案（中）——按提供方措辞；⑦ 原生壳里显示 QQ / Apple 入口但流程无法完成（中）——壳内只保留微信配对码路径；⑧ 邀请模式下 QQ / Apple 新用户无处填邀请码（中）——先收邀请码再跳转；⑨ 中转机 nginx 默认日志会记下 `code` 与 `state`（中）——自定义日志格式不记 query。低风险项中顺手修了：RSA 公钥指数奇数校验、JWKS 刷新失败时沿用缓存、Apple `error` 参数日志清洗、`WD_PUBLIC_URL` 缺失时启动告警、微信登录替换当前浏览器旧会话、禁用账号的票据立即作废、配对码路径二次确认返回 409、密钥文件权限只告警一次、小程序确认页文案、中转机首页法律链接、前端 StrictMode 双票、轮询遇到 4xx 即停、死文案键。未处理的低风险项（原文存于本次会话的 `review_2a.json`）：同一浏览器两个标签页只能有一张票（`wd_wxt` Cookie 只有一个）、小程序里被拒的确认网页端只看到「已扫码」、httpx 超时按阶段计。

## 5 回滚

代码回退即可：0020 只加一张表，老代码不读 `wechat_tickets`；`identities` 里新 provider 的行在老代码下不会被读到（老代码只查 `provider = 'phone'`），但也不会被清理——回退后再前进不受影响。

## 6 上线记录

〔待填〕
