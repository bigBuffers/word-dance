# 单词之舞 小程序（word-Dance 微信登录桥）

`miniprogram/` 是 docs/API.md §3.3 微信登录桥的小程序端（slice 2-A；设计见 docs/AUTH_SIGNUP_DESIGN.md §5.3，决定 D4 / D8）。内容只有两件事：**登录 / 绑定确认**（扫网页上的小程序码，或输入 6 位配对码）和一条**静态「今日一句」**（按星期几轮换七句）。小程序本身不保存任何会话——网页端（打开小程序码的浏览器）轮询 `GET /api/auth/wechat/ticket/{ticket}` 拿到登录；小程序只证明「扫了」（`POST /api/auth/wechat/scan`）和「确认 / 取消」（`POST /api/auth/wechat/confirm`）。纯 WXML / WXSS / JS，无框架，约 300 行。

```
project.config.json   appid 占位 wx0000000000000000；setting.urlCheck=false（开发期不校验合法域名）
app.json / app.js     三个页面：pages/index/index · pages/pair/pair · pages/confirm/confirm；requiredPrivateInfos: []（不申请任何隐私接口）
config.js             apiBase: 'https://RELAY-DOMAIN'（占位，见下）
utils/api.js          wx.request 封装：JSON、X-WD-Request: 1、错误信封 → {status, code, message}
utils/login.js        wx.login → js_code（每次扫码 / 配对前重新取，code 一次性、5 分钟）
pages/index           今日一句 + 「输入配对码」按钮 + 扫码提示
pages/pair            6 位配对码 → wx.login → POST /api/auth/wechat/scan {js_code, pairing_code} → 跳转确认页
pages/confirm         onLoad(options)：小程序码带来的 scene（= 26 位 ticket）→ scan {ticket}；或配对页传来的 WechatScanInfo。
                      显示 登录 / 绑定到 X、设备、IP（已打码）、时间、账号状态；确认 / 取消 → POST /api/auth/wechat/confirm
```

账号状态文案（`WechatScanInfo.account`，按 kind 区分）：登录票 `new` 「将为这个微信创建新账号」· 绑定票 `new` 「将把这个微信绑定到「<bind_display_name>」」· `bound` 「将登录这个微信已绑定的账号」· `closed` 「暂停注册，无法创建新账号」（确认按钮禁用）· `other` 「该微信已绑定其他账号」（禁用）· `self` 「已绑定本账号」。错误以 toast 显示：404 「二维码已过期，请在网页上刷新」、429 「操作太频繁」（中转机把所有小程序请求收敛成同一个来源 IP，服务器按微信用户限频：每分钟 10 次扫码、20 次确认，见 docs/ops.md）、502 「微信服务暂时不可用」、401 `invalid_identity_token` 「确认已超时，请重新扫码」、409 `invalid_transition`：`scanned_elsewhere` 「这个二维码已被另一个微信扫过，请在网页上刷新」、`wrong_state` 「这个请求已经处理过了」（同一次确认点了两下，或网页已经处理）、409 `identity_taken` 「该微信已绑定其他账号」、403（`registration_closed` / `invalid_invite` / `password_required` / `account_disabled`）直接显示服务器的中文消息。

## 注册与配置（需你本人）

1. **注册小程序**（mp.weixin.qq.com → 立即注册 → 小程序；主体 **个人**，个人主体可用的服务类目选 **工具**，例如 工具 → 效率 / 信息查询）。实名 + 手机号即可，不需要企业资质。
2. **拿 AppID 与 AppSecret**：开发 → 开发管理 → 开发设置。AppID 填进 `project.config.json` 的 `appid`，以及服务器 `.env` 的 `WD_WECHAT_APPID`；AppSecret 只放进一个 0600 文件的第一行，路径写进 `WD_WECHAT_SECRET_FILE`（DEPLOY §4；AppSecret 泄露就在后台重置）。两项都在时 `GET /api/health` 的 `wechat_enabled` 变为 true，网页出现「微信登录」。
3. **服务器地址**：`config.js` 的 `apiBase`。正式版必须是**已备案的境内域名**（小程序的 request 合法域名只收备案域名，且必须 https），由中转机的 nginx 把 `/api/auth/wechat/*` 转到东京的服务器（deploy/relay/README.md）；把该域名加进 开发 → 开发设置 → 服务器域名 → request 合法域名。
4. **开发期**：微信开发者工具里导入本目录，详情 → 本地设置 → 勾选「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」（`project.config.json` 的 `urlCheck: false` 已预设），`apiBase` 直接填服务器的 `WD_PUBLIC_URL`。真机预览时同样要在开发者工具里开启「不校验合法域名」。扫码调试：小程序码的 `page` 是 `pages/confirm/confirm`、`scene` 是 26 位 ticket，可在「添加编译模式」里填 `scene=<ticket>` 模拟。
5. **版本与 `WD_WECHAT_ENV`**：小程序码由服务器调用 `getwxacodeunlimit` 生成（endpoint 114），其 `env_version` 来自 `.env` 的 `WD_WECHAT_ENV`：小程序未发布时用 `develop`（开发版，须先在开发者工具上传过）或 `trial`（体验版，体验成员才能打开），正式发布后改回 `release`（默认）。开发版 / 体验版的小程序码只有开发者 / 体验成员能扫开，普通用户扫到的是「小程序尚未发布」。
6. **发布**：开发者工具 → 上传 → 后台 版本管理 → 提交审核（类目 工具；审核会打开小程序，首页的「今日一句」+ 配对入口足以说明用途）→ 发布。之后把 `WD_WECHAT_ENV` 改为 `release`，重启服务。

## 本地验证（不用真微信）

服务器用 `WD_AUTH_FAKE_PROVIDERS=1`（需 `WD_DEV=1`）时，`POST /api/auth/wechat/scan` 的 `js_code` 不经微信：任意 `js_code` 得到 openid `wx_<js_code>`，`bad*` 得 400、`down*` 得 502；小程序码是一张写着 ticket 的占位 PNG。`make smoke` 用这套假桥把 112–117 走一遍（scripts/smoke.py）。
