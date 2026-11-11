# 大陆中转机（relay host）— 微信小程序登录桥与 QQ 登录的备案域名

切片 2-A（`docs/releases/2026-11-auth-third-party.md`、`docs/AUTH_SIGNUP_DESIGN.md` §5.3、`docs/DEPLOY.md` §7.1、`docs/API.md` §3.3）。微信小程序的「服务器域名」与 QQ 互联的「回调域」只接受**已备案的大陆域名**，而应用本体跑在境外（`docs/QUICK_DEPLOY_AND_MOBILE.md` 的东京轻量主机）。中转机就是那台挂着备案域名的大陆小主机：nginx 只把第三方登录的几个路径转发到应用本体，其余路径一律返回一个静态首页。这里的文件：

| 文件 | 用途 |
|---|---|
| `nginx.relay.conf.example` | 备案域名的 TLS 站点：只转发 `/api/auth/wechat/`（端点 112–116）、`/api/auth/qq/callback`（119）、`/api/auth/apple/callback`（121，仅当 Apple 的 Return URL 也注册在这个域名上）和 `/api/health`（1）；`location /` 是静态目录 `/var/www/relay`。**没有别的路径会过境**：AI 端点、学习数据、媒体、SPA 都不经过中转机 |
| `index.html` | 最小首页：产品名、一段说明、指向应用本体法律页面的链接、`〔ICP 备案号〕` 与 `〔公安备案号〕` 两个占位（分别链接 beian.miit.gov.cn 与 beian.mps.gov.cn） |

登录结果如何回到应用本体：QQ / Apple 的回调落在中转域名上，服务器不在那里写会话 Cookie（写了也到不了应用本体的域），而是签发一个 60 秒、一次性的 grant，302 到 `WD_PUBLIC_URL` 上的 `GET /api/auth/oauth/finish?grant=…`（端点 122）再换成会话——所以 `.env` 里 **`WD_PUBLIC_URL` 必须是应用本体的 https 地址**，否则 finish 会落回中转域名。微信桥（112–116）本来就不发 Cookie 给小程序，网页端轮询的是应用本体自己的域名；只有小程序 → 服务器的请求走中转。

## 1 购买与备案（D8；两道串行，4–8 周）

1. **主机**：腾讯云（中国站）轻量应用服务器，**大陆地域**（上海 / 广州 / 北京任一），最低配即可（1–2 vCPU / 2 GB），**预付 ≥ 3 个月**——备案要求主机包年包月不少于 3 个月。公网 IP 整个实例生命周期只能更换一次，别浪费。
2. **域名**：在工信部批复的**境内注册商**（腾讯云 DNSPod / 阿里云万网）注册一个备案专用域名并完成实名；主体必须与备案主体（您本人）一致；与东京主站的境外域名分开，不要混用。
3. **网站备案**（第一道）：腾讯云控制台 → 网站备案 → 个人 → 填主机与域名 → 服务内容选 **「工具」**（不是教育 / 培训），网站名称、简介避免「教育 / 培训 / 中考 / 高考 / 提分」字样，把产品表述为「个人英语单词学习工具」——网站备案与小程序备案的前置审批表里都有「校外培训」一项（需省级教育部门批文），个人拿不到。资料：身份证、手持照 / 人脸核验、承诺书。平台初审 1–2 个工作日，管局 1–20 个工作日。
4. **小程序备案**（第二道）：网站备案下号后，在微信公众平台 → 小程序 → 备案 → 用同一主体、同一域名申请；同一主体证件不能同时在两个平台提交首次备案，所以只能串行。类目同样选「工具」。
5. **退出条件**（D4 / D8）：任一环节管局要求「校外培训」前置审批，**放弃第二步**——微信 / QQ 登录等有公司主体再做；应用本体不受影响（三个开关保持 false，用户什么也看不到）。

备案后的义务：首页悬挂 ICP 备案号并链接工信部网站；**30 日内**完成公安联网备案并悬挂公安备案号（把 `index.html` 里的两个占位换成真实号码，公安备案的链接带上备案号参数）；网站内容与备案信息一致。

## 2 核查风险（接入商抽查）

接入商会核查实际解析 IP 必须是其境内服务器、内容与备案一致。中转机本身满足「域名解析到接入商的大陆主机」，但「个人备案的域名把业务反代到境外」属于灰色地带，抽查时可能被取消接入（设计 R6-09～13）。因此：

- 首页必须是真实可访问的产品说明页（`index.html`），不是空白或跳转页；
- 中转只转发登录相关的几个路径，不转发任何学习接口、AI 接口；
- 预先准备退路：若接入被取消，把 `.env` 里的 `WD_QQ_APPID` / `WD_WECHAT_APPID` 清空并重启，登录页的微信 / QQ 入口消失，已绑定的账号仍可用手机号 / 邮箱 / 密码登录（设置页里仍能解绑）；
- 若将来小程序内容改为 (b)「展示进度」，需要把整套小程序 API 迁到大陆主机，而不是继续反代——那是另一个切片。

## 3 部署步骤

```bash
# 在中转机上（Ubuntu 24.04，以 root 或 sudo）
apt-get update && apt-get install -y nginx certbot python3-certbot-nginx
mkdir -p /var/www/relay && cp index.html /var/www/relay/index.html        # 先把两个备案号占位改成真实号码、APP-DOMAIN 改成应用本体域名（法律页面链接保留 .html 后缀：应用只以 /legal/*.html 提供它们）
sed -e 's/RELAY-DOMAIN/relay.example.cn/g' -e 's/TOKYO-HOST/words.example.com/g' nginx.relay.conf.example > /etc/nginx/sites-available/relay
ln -s /etc/nginx/sites-available/relay /etc/nginx/sites-enabled/relay && rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d relay.example.cn          # 证书路径就是模板里写的 /etc/letsencrypt/live/<域名>/
ufw allow 80,443/tcp                          # 同时在轻量控制台防火墙放行 80 / 443
curl -fsS https://relay.example.cn/api/health  # 应得到应用本体的 {"status":"ok",…}
curl -fsS https://relay.example.cn/            # 应得到首页
curl -s -o /dev/null -w '%{http_code}\n' https://relay.example.cn/api/vocab   # 200 的首页 HTML，而不是应用的 JSON：非白名单路径不过境
```

`TOKYO-HOST` 必须是应用本体 https 前端（`deploy/install.sh --with-caddy DOMAIN` 的域名）；模板用 `proxy_ssl_server_name on` 带 SNI，`Host` 头改写为应用本体的域名，所以应用本体的 CSRF 同源规则（API.md §1，`Host` 推导的 origin 或 `WD_PUBLIC_URL`）不受影响——小程序的 POST 带 `X-WD-Request: 1` 且没有 `Origin`，Apple 的 form_post 走白名单路径。

应用本体的 `.env`（`docs/DEPLOY.md` §4）：

```
WD_PUBLIC_URL="https://words.example.com"                                  # 应用本体；122 的落点
WD_QQ_APPID="…"  WD_QQ_KEY_FILE="/home/sqin/word-dance-data/qq.key"        # 0600 文件，第一行 APP Key
WD_QQ_CALLBACK_URL="https://relay.example.cn/api/auth/qq/callback"         # QQ 互联后台登记的回调地址，须与这里逐字一致
WD_WECHAT_APPID="…"  WD_WECHAT_SECRET_FILE="/home/sqin/word-dance-data/wechat.secret"
# Apple 的 Return URL 一般直接注册在应用本体域名上（它不要求备案）：WD_APPLE_CALLBACK_URL="https://words.example.com/api/auth/apple/callback"
```

小程序后台 → 开发 → 服务器域名：request 合法域名填 `https://relay.example.cn`（`miniprogram/README.md`）。QQ 互联后台 → 网站应用：网站地址与回调地址都填备案域名。

## 4 验证

- `wd check` 的 `third-party sign-in:` 行显示对应提供方 `on`；`GET https://words.example.com/api/health` 的 `qq_enabled` / `wechat_enabled` 为 true。
- 浏览器（电脑）：登录页 → QQ → QQ 授权页 → 回到 `https://relay.example.cn/api/auth/qq/callback?...` → 302 到 `https://words.example.com/api/auth/oauth/finish?grant=…` → 302 到 `/welcome`（新账号）或 `/`；Cookie 只在应用本体域名上。
- 手机微信：小程序「单词之舞」→ 输入网页上的配对码 → 确认 → 网页轮询到 confirmed。
- 出错时网页落到 `/login?error=<code>`（`invalid_identity_token` = state 过期或被改；`provider_error` = QQ / 微信接口不可用，看应用本体日志的 `qq_provider_error` / `wx_*` 事件；`invalid_grant` = finish 的 grant 超过 60 秒或已用过）。

## 5 日常

- 证书：certbot 的 systemd timer 自动续期；`certbot renew --dry-run` 验证一次。
- 日志：模板在 http 上下文定义了自定义格式 `log_format relay '$remote_addr [$time_local] "$request_method $uri" $status $body_bytes_sent'` 并以 `access_log … relay` 使用它——只记录来源 IP、时间、方法、路径（`$uri` 不含查询串）、状态码与字节数。**不要**换回 nginx 默认的 `combined` 格式：它会把整条请求行连同查询串写盘，而 QQ 回调（119）的查询串里有一次性 `code` 和签名的 `state`；同样不要开 `$request_body` 日志。每天看一眼 4xx / 5xx 的比例即可。应用本体那边照常 `journalctl -u word-dance`。
- 限频：所有小程序请求经中转机到达应用本体时，`client_ip` 都是中转机自己的地址（东京前端只信任本机代理，取 X-Forwarded-For 最右一跳），所以 115 / 116 的按 IP 窗口（`wx_scan:ip` / `wx_confirm:ip`，各 600/分钟）是全站共享的洪峰闸，真正的防猜窗口按微信用户计（`wx_scan:openid` 10/分钟、`wx_confirm:openid` 20/分钟）。用户在小程序里看到「操作太频繁」时按 `docs/ops.md` §6 的「小程序提示操作太频繁」一行排查。
- 监控：外部拨测 `https://relay.example.cn/api/health`（UptimeRobot 免费档）；监控绿而用户说扫码不行，多半是微信侧服务器域名白名单或 `WD_WECHAT_ENV` 没对上（`docs/ops.md`）。
- 升级应用本体不需要动中转机；中转机的系统补丁 `apt-get upgrade` 按月。
