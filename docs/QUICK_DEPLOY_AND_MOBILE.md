# word-Dance 小范围快速上线与 iOS / Android 路线

> 日期：2026-11-04 · 代码基线：`main` @ `9ab13a5` · 应 sqin 的要求由 Claude 撰写
>
> 你的指示：先快速部署，只给不超过 10 位朋友用，受众以大陆手机为主；模型限制与国产替换方案留到后续；除了 iOS 也要规划 Android。本文因此不讨论 Anthropic 政策，只记录影响部署的技术事实，凭据怎么选留给你。
>
> 方法：10 个并行调研切片（5 个读代码、5 个联网）→ 每个切片一名独立核验者（代码切片在临时实例与只读数据库副本上执行验证，联网切片回查一手来源；99 条关键结论中 76 条确认、22 条修正、1 条无法验证、0 条推翻）→ 3 套独立方案（最快 / 稳妥 / 应用优先）由 3 位评审从「你的时间」「朋友的体验」「工程正确性」三个视角打分并逐条指出事实错误 → 综合成本文（评审指出的错误已全部改正）。原始材料见 [`docs/analysis/2026-11-04-quick-deploy-mobile/`](analysis/2026-11-04-quick-deploy-mobile/)。
>
> 工作量按你一个人业余做估算。命令里的 `DOMAIN`、`VPS_IP`、`you@example.com` 请替换；每条命令都以仓库当前代码为准核对过，但没有在真实 VPS 上跑过。

## 0. 一页结论

**0.1 怎么做。** 租一台腾讯云轻量应用服务器（中国站，东京地域，2 vCPU / 4 GB，约 ¥42/月；新加坡同价作备选），用仓库自带的 `deploy/install.sh --with-caddy DOMAIN --with-ecdict` 安装，服务用户就叫 `sqin`（仓库默认路径、单元文件、提示文案全都不用改）。**安装前先把 Mac 上的数据库和图片复制过去**：同一提交、同一 schema、同一种子哈希时不需要迁移也不会重导种子（部署 K-12 五阶段提交则会在停服务后应用迁移 0011–0013 并重导新种子：顺序与排练见 1.3 节末与 `docs/releases/2026-11-k12-stages.md`）；数据库里已经有管理员，所以「第一个注册者自动成为管理员」的竞态根本不会出现。邀请朋友之前不需要改一行代码，所有必做项都是配置或操作。节奏：第 1 天上线，第 2–3 天先请 2–3 位朋友试用，第 4–7 天全员进来，第 14 天关闭注册。

**0.2 移动端怎么办。** 第一个月，「App」就是添加到主屏幕的网页：iOS 26 起任何网站加到主屏幕都默认以独立窗口打开（不需要 manifest），安卓各浏览器都有「添加到桌面」；每日提醒用后端已有的 webhook 渠道（iPhone 用 Bark，其他一切有微信的手机用 Server酱），零代码。只补两个小东西：约 1 小时的图标 + manifest，以及 3–4 小时的「微信里打开请切到浏览器」提示。真正的 App 走 Capacitor「远程壳」：WebView 直接加载线上站点，**后端零改动**，网站一发布 App 就更新；iOS 通过 TestFlight 内部测试分发（免审核），Android 通过自签名 APK 下载链接分发；双端约 6 人日加 ¥688/年苹果开发者费。它对无 Google 服务的国产安卓机收益最大（本机定时提醒 + 原生发音），对 iPhone 只是便利，对鸿蒙 NEXT 手机无能为力（装不了 APK，只能用网页）。建议第 14 天按证据决定是否启动；如果你已经决定要做，苹果账号注册和 Xcode 下载可以第 0 天就开始，它们不影响服务器那条线。

**0.3 三道不能省的检查。** ① 买到机器后第一件事是 `curl https://api.anthropic.com/v1/models`，期望 401（可达但未认证）而不是 403：香港机房 IP 实测被拒，东京/新加坡在支持名单内，但你那台机器的 IP 段要亲测。② 先复制数据库再跑安装脚本。③ `.env` 里必须是 `WD_HOST="127.0.0.1"`、`WD_TRUST_PROXY="1"`、`WD_PUBLIC_URL="https://DOMAIN"`（带 `--with-caddy` 时脚本会写）；否则所有访客共用 IP 127.0.0.1，注册 5 次/小时、登录 20 次/10 分钟的限流变成全站限额，cookie 也不带 `Secure`。

**0.4 模型相关只记两个技术事实。** 其一，Mac 上现在用的登录属于强制「服务端托管设置」且失败即拒绝的企业组织：账本第 33–47 次调用全部因为拉取托管设置失败而失败，被归类成「未登录」，触发了 14 次 30 分钟的全局暂停；这套登录放到 VPS 上，每次调用都要先连一次 Anthropic 才能工作。其二，`claude` 的凭据接线与凭据种类无关：`ANTHROPIC_*` 变量可以放 systemd drop-in，其余一切（`setup-token` 令牌、关闭自动更新、CLI 专用代理）只能放进 `WD_CLAUDE_BIN` 指向的包装脚本，与 Mac 的做法一致。第 2.3 节给出五种凭据各自的接法。

**0.5 时间与钱。** 必做工作约 1.5 人日（第 0–3 天），加上两周内的小补丁约 3–3.5 人日；App 约 6 人日，日历上 3–4 周。月成本：服务器约 ¥42 + AI 实际约 $25–60（硬上限 $100）≈ ¥210–450；一次性：域名约 ¥79、按阶段预生成 $5–12、App 阶段 ¥688/年。

**0.6 需要你定的事**（第 6 节）：地区、域名与 DNS 托管、`claude` 凭据接法、Mac 数据是否原样带走、预生成哪些阶段、AI 上限与 SVG 子上限、邀请码形态、是否现在就注册苹果开发者、朋友里有没有未成年人。

## 1. 现状与前提（均已核实）

### 1.1 本机实例

| 事实 | 数据 | 出处 |
|---|---|---|
| 运行方式 | Mac launchd 代理，`wd serve` 单进程，数据目录 `/Users/sqin/word-dance-data` | 项目记忆 |
| 数据量 | 1 个用户（管理员 `sqin`）、52 条生词、48 个词有内容、31 张图（30 张为 Claude SVG）、数据库 6 MB、图片 216 KB | 只读快照 |
| 关键配置 | `WD_PUBLIC_URL` 为空、`WD_TRUST_PROXY=0`、注册模式 `invite`、AI 上限 $3/天、$40/月 | 本机 `.env` 非敏感键 |
| 推送渠道 | 邮件与 webhook 从未启用，三个批次的送达状态全是 `none` | reminders F15 |
| 网络 | 直连 `api.anthropic.com` 与 `platform.claude.com` 均 403，只有经手工启动的 SOCKS 隧道才通；Wikimedia 与 Openverse 从本机网络不可达，48 次取图全部失败，配图几乎全是 SVG | clivps 核验、security F10 |
| 当前登录的技术脆弱性 | 见 0.4：15 次调用因托管设置拉取失败而失败，被归为登录失败并暂停 | clivps 核验 |
| 本机睡眠 | `pmset` 设为空闲 1 分钟即睡眠，目前只靠一次性的 `caffeinate`；Mac 不适合做服务器 | deploy 核验 |

### 1.2 `deploy/install.sh` 能做什么、不能做什么

- **脚本不安装任何系统级依赖。** 预检硬性要求 `python3 ≥ 3.12`（含 `python3.12-venv`）、Node ≥ 22（Ubuntu 24.04 的 apt 只有 18.19，要用 NodeSource；Vite 8 实际需要 ≥ 22.12，预检只看大版本）、`git`/`curl`/`openssl`、免密 `sudo -n`、PATH 上有 `claude` 可执行文件、`/home` 剩余 > 2 GB（检查的是 `/home` 而不是数据目录）。Caddy 2.6.2 由脚本从 Ubuntu universe 安装。首次全程约 2–3.5 小时，重复约 1 小时。（deploy F1、F13 及核验）
- **服务可以在没有可用 `claude` 的情况下启动。** 健康检查 200，页面与词典数据正常，`wd claude-check` 以 $0 成本退出 2；`WD_AI_ENABLED="0"` 是「先部署、后接凭据」的干净开关。只有脚本预检坚持要有 `claude` 二进制。（deploy F2，已在临时实例验证）
- **用户名与路径写死为 `sqin` / `/home/sqin`。** 换别的用户名要在每次 `wd` 命令前导出 `WD_DATA_DIR`、手工改 `WD_CLAUDE_PATH`，且不能以 root 运行；在 VPS 上建一个叫 `sqin` 的用户最省事。（deploy F3）
- **管理员引导竞态。** `users` 表为空时，第一个注册者在任何注册模式下都成为管理员且不需要邀请码；在首次运行脚本前 `export WD_ADMIN_*` 不起作用（脚本复制模板 `.env` 后 `source` 会把它们覆盖为空，已验证）。先复制 Mac 数据库即可绕过；否则必须在 DNS 解析前 `wd create-admin`。（deploy F5、security F3）
- **数据迁移。** 只需 `word-dance.db`（先 `VACUUM INTO` 出一致副本）与 `images/`（28 个分片目录，216 KB）；**不要**复制 `.env`。（deploy F11 及核验）
- **脚本写入 `.env` 的键。** 首次创建时填 `WD_SECRET_KEY`、`WD_CLAUDE_BIN`、`WD_DATA_DIR`、`WD_CONTACT_EMAIL`；带 `--with-caddy` 时每次都写 `WD_HOST`、`WD_PUBLIC_URL`、`WD_TRUST_PROXY` 并重写 Caddyfile（所以升级时不要再带这个参数）；注册模式、预算、`WD_ADMIN_*`、`WD_CLAUDE_PATH` 永远不碰。`.env` 只接受 `WD_` 开头的行。（deploy F4）
- **升级与回滚。** `git pull && deploy/install.sh` 即升级，停机秒级；连续两次不重启的安装会删掉正在服务的前端快照导致整站 503，所以每次升级后都要重启。（deploy F13、pwa 核验）

### 1.3 对 10 位熟人而言的安全基线

已经具备：CSP/HSTS/nosniff/frame-deny 头、`HttpOnly; SameSite=Lax`（https 下 `Secure`）的 30 天滑动会话、自定义头 CSRF 规则、bcrypt-12 与常见密码表、持久化的按 IP/按用户限流与按用户名锁定、1 MiB 请求体上限、带 DNS 固定的 SSRF 防护、需要 cookie 的 `/media`、0700 数据目录、管理员暂停/开关与全局预算预留。未登录可访问的只有登录、注册、健康检查三个接口加静态文件。会话 GC 每小时运行（上周文档的 C5 项有误）。（security F1、F2、F15）

| 必做（全部是配置或流程） | 做法 | 依据 |
|---|---|---|
| 关闭管理员引导窗口 | 复制 Mac 数据库，或在 DNS 解析前 `wd create-admin` | security F3 |
| 代理与 https 前提 | `WD_HOST=127.0.0.1`、`WD_TRUST_PROXY=1`、`WD_PUBLIC_URL=https://DOMAIN`；用 curl 看到 HSTS、登录响应带 `Secure` | security F5、F6 |
| 注册策略 | 保持 `invite`，每人一个单次邀请码；全部进来后改 `closed` | security F14 |
| 管理员账号 | 没有二次验证：长且唯一的密码，只在自己设备登录 `/admin`；再建一个名字猜不到的备用管理员 | security F13、F4 |
| AI 上限 | 默认 $3/天够用，但 $40/月会在第 2–4 周触顶，之后所有人的 AI 顺延到下月 1 日而文案仍显示「明天补齐」；改为日 6、月 100（硬顶 $180/月，实际预计 $25–60） | security F8、F17 |

锁定与限流的事实：按用户名锁定（键 `login:user:<用户名小写>`），连续 10 次失败锁 15 分钟，每再 5 次翻倍，最长 24 小时，没有 `wd unlock`；解锁语句可在服务运行时执行，但必须带忙等待，否则遇到写入会报 `database is locked` 且什么都没删（已验证）：

```bash
sqlite3 -cmd ".timeout 5000" /home/sqin/word-dance-data/word-dance.db \
  "DELETE FROM auth_throttle WHERE key='login:user:<用户名>'"
```

注册限流 5 次/小时/IP 在校验邀请码**之前**计数：一个朋友输错 5 次，同一 Wi‑Fi 下所有人一小时都注册不了；登录限流 20 次/10 分钟/IP 把成功登录和被锁定的尝试都算在内。对策：让朋友粘贴邀请码、分批注册、用手机流量。（security F4、F5 及核验）

AI 预算算术（10 人）：实测 10 词一批 $0.0048–0.0059/词；每小时 60 次调用约 600 词。10 人默认每天 10 新词 + 15 推荐词，内容生成第一周约 $0.6–2.5/天，之后 $0.5–1.5/天，首月 $20–60。最坏情况：一个账号用桌面端批量标记，92 个请求就能把 9,114 个缺内容的种子词全部排队（约 912 次调用、15 小时、$41–50）；朋友之间没有动机，管理页可暂停 24 小时，或用下面已修正的取消语句（原稿的 `updated_at=finished_at` 会违反非空约束）：

```sql
UPDATE jobs SET status='cancelled', finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),
  updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), locked_at=NULL, locked_by=NULL
 WHERE type IN ('generate_content','fetch_image','generate_svg') AND status='queued' AND priority>=20;
UPDATE words SET content_state='none' WHERE content_state='queued'
  AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.dedupe_key='content:'||words.id AND j.status IN ('queued','running'));
```

预生成是可选项：每日批次会在推送前 3 小时内为当天的词生成内容；不预生成只是朋友从筛词/词库点开没人学过的词时会看到「例句生成中」。按阶段的缺内容词数 ≈ 阶段累计词数（K-12 五阶段种子，以 `data/seed/stats.json.per_stage` / `total_words` 为准：小学 ≈ 600 · 初中 ≈ 2,549 · 高中 ≈ 3,260 · 四级 ≈ 4,722 · 六级 ≈ 7,671 · 全部 ≈ 9,618）减去已有内容的 ≈ 49 个词；成本 = 词数 × $0.0045–0.0059，时间 = 词数 ÷ 600/小时：小学 ≈ $2.7–3.5（1 小时）、初中 ≈ $11.5–15（4.2 小时）、高中 ≈ $14.7–19、四级 ≈ $21–28、六级 ≈ $35–45、全部 ≈ $43–57（16 小时，小时上限提到 120 可减半）；每个阶段最高频 1,000 词约 $4.5–6、1.7 小时。（security F7–F11 及核验；词数按 2026-11 种子更新）

### 1.4 前端的移动端就绪度

已经就绪：iOS 的 `apple-mobile-web-app-*` meta、按配色方案的 `theme-color`、`viewport-fit=cover`、安全区变量、`100dvh` 学习页、可见性门控的轮询。缺的是「可安装」那一层：没有 manifest、没有 PNG 图标（只有 `favicon.svg`）、没有 `<link rel=manifest>` 与 `apple-touch-icon`、没有 service worker、没有安装提示、没有微信/QQ 内置浏览器检测。现有 CSP 已允许同源 manifest 与 SW；本机 `sips` 能直接把 SVG 栅格化成所需 PNG（已验证逐字节一致），不需要新依赖。两个仍待真机确认的点：iOS 26 把网站加到主屏幕时是否复制登录 cookie（苹果文档对 iOS 表述不一，按「要再登录一次」准备）；独立窗口里有没有边缘返回手势（详情页与添加页没有返回按钮）。（pwa F2–F9 及核验）

## 2. 推荐路线（按天）

| 天 | 主题 | 你的时间 | 完成标准 |
|---|---|---|---|
| 0 | 决定第 6 节的默认项，买域名与 VPS，可达性测试，问朋友四个问题 | 1 h | VPS 上 `curl` 得到 401 而不是 403 |
| 1 | 建用户、装依赖、复制 Mac 数据、`install.sh`、`.env`、DNS/TLS、备份拉回 | 3–4 h | 手机用流量打开站点，登录 `sqin`，管理页可用，响应带 HSTS |
| 2 | 凭据接线、`wd claude-check`、开 AI、图标 + manifest、提醒演练、预生成、重启演练、首批 1–2 位朋友 | 2–3 h | `claude check OK`；Bark 与 Server酱 都收到测试；首批朋友登录 |
| 3 | 微信引导卡 + 缓存头一行、自己的手机检查、邀请其余朋友 | 3–5 h | 全员有账号，`sessions.ip` 是真实 IP |
| 4–7 | 恢复上限、监控 cron、外部拨测、快照、sudo 收窄、恢复演练；webhook 补丁后开放其他渠道；延期文案 | ≤ 30 min/天 + 两晚 | 监控推送过一次测试；企业微信坏 key 显示「测试失败」 |
| 8–14 | 观察；第 14 天 `closed`；按触发条件做可选补丁；记录决策数据 | ≤ 10 min/天 | 14 天的 概览 数据写下来 |
| 14–28 | App 决策门；若启动，走第 4.3 节 | — | 书面 go / no-go |

安全暂停点：第 1 天做到「本机健康检查通过、80/443 还没开」就可以停下来第二天再继续；第 2 天任何一步没完成，都不影响朋友继续用网页。

### 2.1 第 0 天（约 1 小时）

1. **域名**：已有域名就用一个子域；否则 Porkbun（支付宝，`.com` $11.81/年，`.top` 首年 $1.63 / 续费 $4.63，即买即用）；万网 `.com` ¥85/¥95 需要实名模板，可能耗 1–2 个工作日。DNS 放 DNSPod 免费版（大陆解析快，最小 TTL 600 秒）或 Cloudflare 仅 DNS（灰云，60 秒 TTL；**绝不**给大陆用户开橙云代理）。只用**一个规范主机名**，不设 `www`、不做跳转：以后 Capacitor 的 Android 桥只对 `server.url` 的精确源注入。
2. **VPS**：腾讯云中国站 → 轻量应用服务器 → 东京 → 2 vCPU / 4 GB / 60 GB / 30 Mbps / 1.5 TB（约 ¥42/月；看一眼活动页，这一档新用户年付促销出现过 ¥199/年，到期按标价续费）→ 镜像 **Ubuntu 24.04**（控制台确认有）→ 密钥登录；防火墙暂时只开 22。公网 IP 整个实例生命周期只能更换一次，这是被墙时的逃生口，别浪费。
3. **可达性测试**（登录后第一件事）：

```bash
for u in https://api.anthropic.com/v1/models https://platform.claude.com/ \
         https://downloads.claude.ai/claude-code-releases/latest https://commons.wikimedia.org/w/api.php \
         https://api.openverse.org/v1/images/?q=apple https://sctapi.ftqq.com/ https://api.day.app/ https://github.com/; do
  printf '%-62s %s\n' "$u" "$(curl -sS -o /dev/null -m 10 -w '%{http_code}' "$u")"; done
```

   期望：`api.anthropic.com` 401（403 = 地区/网段被拒，销毁实例改建新加坡，同价）；`platform.claude.com` 200/302（登录与令牌刷新用它）；其余 2xx/4xx 而不是超时。Wikimedia/Openverse 的结果决定第 2 天的 SVG 子上限。
4. **现在就加 A 记录** `DOMAIN → VPS_IP`（TTL 600 或 60）：此时没有任何东西在监听，管理员竞态由数据库复制关闭，第 1 天的 TLS 就不用等传播。
5. **问朋友四件事**（一条微信）：手机型号与系统（华为是鸿蒙 4 还是 NEXT）、学哪个阶段（中考/高考/四级/六级）、以后是否愿意接受 App Store Connect 的 TestFlight 邀请、Apple 账号用的邮箱。答案决定预生成范围、提醒渠道与 App 是否值得做。

### 2.2 第 1 天（3–4 小时）

**1.1 建用户与防火墙**（以镜像默认用户登录；`sqin` 这个名字让仓库默认值零修改）：

```bash
sudo adduser --disabled-password --gecos "" sqin && sudo usermod -aG sudo sqin
echo 'sqin ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/sqin && sudo chmod 440 /etc/sudoers.d/sqin   # install.sh 需要 sudo -n；第 4 天收窄
sudo install -d -m 700 -o sqin -g sqin /home/sqin/.ssh && sudo cp ~/.ssh/authorized_keys /home/sqin/.ssh/ && sudo chown sqin:sqin /home/sqin/.ssh/authorized_keys
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && sudo systemctl reload ssh
sudo apt-get update && sudo apt-get install -y ufw && sudo ufw allow OpenSSH && sudo ufw --force enable   # 80/443 等本机健康检查通过后再开
```

**1.2 脚本不装的前置依赖**（以 `sqin` 身份；`claude` 用签名 apt 的 `stable` 通道，装到 `/usr/bin/claude`，不会悄悄自动更新）：

```bash
sudo apt-get install -y git curl ca-certificates gnupg openssl python3 python3-venv python3.12-venv sqlite3 rsync
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update && sudo apt-get install -y nodejs && node --version          # v22.2x（≥ 22.12）
python3 -c 'import sys,venv,ensurepip,sqlite3,zoneinfo; print(sys.version)'       # 3.12.x
sudo curl -fsSL https://downloads.claude.ai/keys/claude-code.asc -o /etc/apt/keyrings/claude-code.asc
echo "deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main" | sudo tee /etc/apt/sources.list.d/claude-code.list
sudo apt-get update && sudo apt-get install -y claude-code && claude --version     # 2.1.311
```

**1.3 Mac 侧冻结并导出数据**（停掉两个 launchd 代理，否则 03:30 的备份还会「运行」在一个死实例上；Mac 数据目录原样保留 14 天作回滚）：

```bash
launchctl bootout gui/$(id -u)/com.word-dance.server
launchctl bootout gui/$(id -u)/com.word-dance.backup
sqlite3 /Users/sqin/word-dance-data/word-dance.db "VACUUM INTO '/Users/sqin/wd-migrate.db'"
tar -C /Users/sqin/word-dance-data -czf /Users/sqin/wd-images.tgz images
ssh sqin@VPS_IP 'install -d -m 0700 /home/sqin/word-dance-data'
scp /Users/sqin/wd-migrate.db sqin@VPS_IP:/home/sqin/word-dance-data/word-dance.db
scp /Users/sqin/wd-images.tgz sqin@VPS_IP:/home/sqin/
ssh sqin@VPS_IP 'tar -C /home/sqin/word-dance-data -xzf /home/sqin/wd-images.tgz && chmod 600 /home/sqin/word-dance-data/word-dance.db && rm /home/sqin/wd-images.tgz && sqlite3 /home/sqin/word-dance-data/word-dance.db "select username, role from users"'   # sqin|admin
```

**升级到 K-12 五阶段提交（迁移 0011–0013 + 新种子）时的顺序——先备份、再停、再切、再起。** `wd serve` 启动即执行迁移，0011/0013 是表重建、不可逆、只能用迁移前快照回滚，所以无论 Mac（launchd）还是 Lighthouse（systemd）都不能先切代码再想备份：① `wd backup --with-images`；② 停服务（Mac 上两个 launchd 代理都停，见上）；③ `git checkout <新提交>` 并发布前端快照；④ `wd migrate --dry-run` 恰好列出 0011/0012/0013 → `wd migrate` → `wd import-seed --dry-run --report …` 与排练报告一致 → `wd import-seed`；⑤ `wd check db` 不变量全部 ok（只升到 K-12 提交时四条；含迁移 0014 的学习顺序提交起八条——0014 起多学习顺序四条）；⑥ 起服务并验证。上线前先在本机、部署前在目标机对数据库**拷贝**各跑一次 `.venv/bin/python -I scripts/rehearse_migration.py <拷贝>`（退出 0；目标机 SQLite ≥ 3.26）。逐步命令、验证项与回滚（库与代码一起回；只回代码不会 500，而是主攻阶段静默显示错位）见 `docs/releases/2026-11-k12-stages.md` §6–§7（= PLAN §8）。Linux 上 `deploy/install.sh` 自己完成「停 → 迁移 → 导种子 → 起」，但这次**不可**带 `--no-restart`；复制过来的 Mac 库若已在 Mac 上完成迁移与导种子，VPS 上就什么都不会再发生（同一提交、同一内容哈希）。

**升级到学习顺序提交（迁移 0014，`docs/releases/2026-11-learn-order.md`）只需重启。** 0014 是 `words` 表的一条 `ADD COLUMN`，`wd serve` 启动时自动应用并在接受第一个请求前填好 `words.learn_rank`（排练库实测几十毫秒）；Mac 上 `launchctl kickstart -k`，Linux 上 `git pull && deploy/install.sh`（脚本在 `import-seed` 之后多跑一步 `wd learn-order`），这次允许 `--no-restart`，但旧进程在重启前仍按 `frq` 出词；之后 `wd check db` 应打印八条 `invariant …: ok`。从已完成该次升级的 Mac 复制过来的库自带 `learn_rank` 与 `kv.learn_order.*` 戳，VPS 上启动只做一次存储值与计算值的比对。

**1.4 克隆、演练、安装**（`npm ci` 占大头，15–25 分钟）：

```bash
git clone https://github.com/bigBuffers/word-dance.git /home/sqin/word-Dance && cd /home/sqin/word-Dance
deploy/install.sh --with-caddy DOMAIN --with-ecdict --contact-email you@example.com --dry-run   # 预检必须通过
deploy/install.sh --with-caddy DOMAIN --with-ecdict --contact-email you@example.com
```

会看到：venv 与 pip、SPA 构建到 `frontend-releases/<sha>`、`.env` 首次创建（含代理三件套）、ECDICT 216 MB 下载解出 851 MB、`wd migrate` → 0 pending、`import-seed` → 已是最新、`wd claude-check` → WARN（还没凭据，正常）、`create-admin --if-none` → 已有用户、systemd 单元以 `User=sqin` 启动、Caddy 装好并写入 Caddyfile、本机健康检查输出 `needs_setup:false`。

**1.5 `.env` 修改并重启**（每行都是 `KEY="value"`）：

```bash
E=/home/sqin/word-dance-data/.env
sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="0"|' $E                          # 先关 AI，claude-check 通过后再开，避免 30 分钟暂停与误导横幅
sed -i 's|^WD_AI_MODEL=.*|WD_AI_MODEL="claude-sonnet-5-5"|' $E               # 固定内容验证时用的模型（别名 sonnet 自 2.1.284 起即它）
sed -i 's|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="6.00"|; s|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="100.00"|' $E
sed -i 's|^WD_IMAGE_KID_STAGES=.*|WD_IMAGE_KID_STAGES="xs"|' $E                       # 小学词卡用儿童绘本风格（2026-11-06 负责人确认；代码默认为空 = 关，Mac 线上已设）
grep -nE '^WD_(HOST|PUBLIC_URL|TRUST_PROXY|REGISTRATION_MODE|DEV|AI_SVG_DAILY_BUDGET_USD|AI_HOURLY_CALL_CAP|ECDICT_DB_PATH)=' $E   # 127.0.0.1 / https://DOMAIN / 1 / invite / 0 / 0.50 / 60 / …stardict.db
sudo systemctl restart word-dance && sleep 3 && curl -fsS http://127.0.0.1:8000/api/health
```

**1.6 开门：防火墙、TLS、手机测试**：

```bash
sudo ufw allow 80,443/tcp            # 同时在轻量控制台防火墙放行 80/443
sudo systemctl reload caddy && sleep 30
curl -sSI https://DOMAIN/api/health | grep -iE '^(HTTP|strict-transport)'   # HTTP/2 200 + strict-transport-security
journalctl -u caddy -n 20 --no-pager | grep -i certificate
```

然后用自己的手机走**流量**打开 `https://DOMAIN`：注册页显示邀请码栏（而不是「尚无账号…」），用 Mac 上的密码登录 `sqin`，管理页能打开。不要用错误密码试：每次都计入 10 次锁定与 IP 窗口。

**1.7 备用管理员**（名字猜不到；密码走交互提示，不要写在命令行里留进 shell 历史）：`/home/sqin/word-Dance/.venv/bin/wd create-admin --username ops_7f3a9`（不带 `--if-none`，已有用户时也会创建）。

**1.8 备份拉回 Mac**：VPS 定时器每天 03:30 产生 `backups/*.db.gz`，但 `images/` 不在其中，所以一起拉。用专用的无口令密钥，先交互 `ssh` 一次接受主机指纹；**不要**用 `--delete`（服务器上误删会同步成本地也没了），日志放在同步目录之外；`RunAtLoad` 让每次登录都补拉一次（Mac 空闲 1 分钟就睡）：

```bash
mkdir -p /Users/sqin/word-dance-vps-backups /Users/sqin/Library/Logs/word-dance
cat > ~/Library/LaunchAgents/com.word-dance.vps-backup-pull.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.word-dance.vps-backup-pull</string>
  <key>ProgramArguments</key><array><string>/bin/sh</string><string>-c</string>
    <string>/usr/bin/rsync -a sqin@VPS_IP:/home/sqin/word-dance-data/backups/ /Users/sqin/word-dance-vps-backups/backups/ &amp;&amp; /usr/bin/rsync -a sqin@VPS_IP:/home/sqin/word-dance-data/images/ /Users/sqin/word-dance-vps-backups/images/</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/Users/sqin/Library/Logs/word-dance/vps-backup-pull.log</string>
  <key>StandardErrorPath</key><string>/Users/sqin/Library/Logs/word-dance/vps-backup-pull.log</string>
</dict></plist>
EOF
ssh sqin@VPS_IP true && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.vps-backup-pull.plist
```

**1.9 收尾**：把 VPS 的 `.env` 存进密码管理器（它不在备份里）；在私人运维笔记里记下 VPS 到期日（促销价到期按标价续）、域名续费日、公网 IP 只能换一次。约 21:00 用手机流量和家里 Wi‑Fi 各开一次站点，Mac 上 `ping -c 20 VPS_IP`：丢包 > 5% 或明显卡顿就第 2 天改建新加坡（同价，用快照约 1 小时）。

### 2.3 第 2 天（2–3 小时）

**2.1 包装脚本 + 凭据**（与凭据种类无关，先把包装脚本建好；它同时固定二进制、关掉自动更新；代理变量**绝不**放进 systemd 单元，图片管线的 DNS 固定 TLS 会被 HTTP 代理弄坏）：

```bash
install -d -m 0700 /home/sqin/word-dance-data/bin
cat > /home/sqin/word-dance-data/bin/claude-wrapper <<'EOF'
#!/bin/sh
export DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1
# 下面五选一（或都不开，使用 /home/sqin/.claude/.credentials.json 里的存盘登录）：
# export CLAUDE_CODE_OAUTH_TOKEN="$(cat /home/sqin/word-dance-data/oauth.token)"      # B：claude setup-token 的一年期令牌；runner 会丢弃 CLAUDE_CODE_*，所以只能放这里
# export ANTHROPIC_API_KEY="$(cat /home/sqin/word-dance-data/anthropic.key)"           # C：Console API key（也可放 systemd drop-in）
# export ANTHROPIC_AUTH_TOKEN="$(cat /home/sqin/word-dance-data/gateway.token)" ANTHROPIC_BASE_URL=https://gateway.example.com   # D：网关
# export HTTPS_PROXY=http://127.0.0.1:8118 NO_PROXY=localhost,127.0.0.1               # 仅 CLI 需要代理时；CLI 不支持 SOCKS
exec /usr/bin/claude "$@"
EOF
chmod 0700 /home/sqin/word-dance-data/bin/claude-wrapper
sed -i 's|^WD_CLAUDE_BIN=.*|WD_CLAUDE_BIN="/home/sqin/word-dance-data/bin/claude-wrapper"|' /home/sqin/word-dance-data/.env
```

五种接法：**A 存盘登录** — 以 `sqin` 身份 `claude auth login`，把打印的 URL 复制到 Mac 浏览器（Mac 直连 `platform.claude.com` 是 403，要经你现有代理）打开，粘贴回代码，`claude auth status --text` 退出 0；再交互运行一次 `claude` 过首轮引导；登录会过期（提前 3 天警告），过期后每次调用报 `Login expired` 并触发暂停，重新以同一用户执行即可；2.1.318 起 `claude auth status` 带 `loginExpiresAt`，每周看一眼。**B `setup-token`** — 在任一有浏览器的机器生成一年期令牌，存 `oauth.token`（0600），只能走包装脚本。**C API key** — 包装脚本，或 `claude.env` + `sudo systemctl edit --drop-in=claude word-dance.service` 写入 `[Service]` `EnvironmentFile=-/home/sqin/word-dance-data/claude.env`。**D 网关** — 同 C。**E `apiKeyHelper`** — `/etc/claude-code/managed-settings.json` 或 `WD_AI_EXTRA_ARGS="--settings 路径"`（tier 1 的 `--restricted` 忽略 `~/.claude/settings.json`）。

**2.2 验证并开 AI**：

```bash
export WD_DATA_DIR=/home/sqin/word-dance-data
/home/sqin/word-Dance/.venv/bin/wd claude-check      # claude check OK: tier 1, cost $0.00xx, model claude-sonnet-5-5, claude 2.1.311（≤ $0.05）
sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="1"|' $WD_DATA_DIR/.env && sudo systemctl restart word-dance
```

管理页若显示「已暂停」（复制过来的 kv 可能残留 `claude.paused_until`），点「恢复 AI」。在手机上加一个自添词，约 1 分钟内应出现内容。

**2.3 照片源与 SVG 子上限**：加两个词并打开，看 管理 → 概览 的图片来源配额与图片构成（`wd check providers` 只读旧状态行，复制过来的是 Mac 的错误记录，不能作为依据）。Wikimedia/Openverse 在东京可用 → `WD_AI_SVG_DAILY_BUDGET_USD` 设 1.00（约 80 张/天）；仍失败 → 申请免费的 `WD_PIXABAY_KEY`/`WD_PEXELS_KEY`，或设 0 只用文字卡片。48 小时内定。

**2.4 图标 + manifest**（Mac 上约 1 小时，分支提交后 `git pull && deploy/install.sh` 部署，升级不带 `--with-caddy`）：按 pwa 切片的 A1–A3 建 `frontend/public/manifest.webmanifest`（`start_url` `/today`、`scope` `/`、`display` `standalone`、192/512 普通与 maskable 图标）、用 `sips` 从 `favicon.svg` 与全出血的 `icon-maskable.svg` 生成 PNG（含不透明的 180 px `apple-touch-icon.png`，总计约 40 KB），`index.html` 第 13 行后加 `mobile-web-app-capable` meta、`<link rel="manifest">`、`<link rel="apple-touch-icon">`。门禁 `npm run lint && npm run typecheck && npm test && npm run build`。

**2.5 提醒演练（自己的设备）**：iPhone 装 Bark → 复制 `https://api.day.app/<key>` → 我的 → 推送设置 → Webhook 地址，格式 Bark，开启，发送测试；微信走 Server酱 Turbo：`sct.ftqq.com` 微信扫码登录（**在手机上注意**：页面上的二维码没法用同一部手机扫，要在微信里打开页面长按识别，或在电脑上登录——这是调研没亲手走过的一步，演练时记下确切步骤）→ SendKey → `https://sctapi.ftqq.com/<SendKey>.send`，格式 Server酱 → 发送测试。然后给自己发一条真实摘要看深链与标题截断：管理员会话里 `POST /api/admin/push/run {"user_id": 1}`（会立刻构建并发布你今天的批次，只影响你自己）。只有 Bark 与 Server酱 Turbo 在坏 key 时返回 400 被如实报告；企业微信、飞书、Server酱³ 坏 key 也返回 200，界面会显示「测试成功」，补丁之前不要给朋友用。

**2.6 预生成**（当晚跑，第二天早上恢复上限；预生成从不触发 SVG）：

```bash
E=/home/sqin/word-dance-data/.env
sed -i 's|^WD_AI_PREWARM_DAILY_BUDGET_USD=.*|WD_AI_PREWARM_DAILY_BUDGET_USD="20.00"|; s|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="40.00"|; s|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="150.00"|; s|^WD_AI_HOURLY_CALL_CAP=.*|WD_AI_HOURLY_CALL_CAP="120"|' $E
sudo systemctl restart word-dance
# 管理 → AI → 预生成：stage = 朋友的主攻阶段，limit 1000 或 2000，max_budget_usd 15；1,000 词约 1 小时（上限 120）
# 次日早上：
sed -i 's|^WD_AI_PREWARM_DAILY_BUDGET_USD=.*|WD_AI_PREWARM_DAILY_BUDGET_USD="1.00"|; s|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="6.00"|; s|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="100.00"|; s|^WD_AI_HOURLY_CALL_CAP=.*|WD_AI_HOURLY_CALL_CAP="60"|' $E
sudo systemctl restart word-dance
```

**2.7 重启演练**：`sudo reboot`，回来后确认 `systemctl is-active word-dance caddy word-dance-backup.timer`、`ufw status`、`claude --version`。Ubuntu 的无人值守更新迟早会重启机器，现在验证比朋友依赖之后再发现强。

**2.8 首批试用**：如果 claude-check 当天通过，当晚邀请 1 位 iPhone 朋友和 1 位国产安卓朋友（每人一个 `wd invite --uses 1 --days 14 --note 名字` 的单次邀请码，附第 7 节说明），陪他们 30 分钟：注册 → 引导（阶段、推送时间）→ 添加到主屏幕 → Bark 或 Server酱 → 发送测试。验证代理信任生效：

```bash
sqlite3 -readonly -cmd ".timeout 5000" /home/sqin/word-dance-data/word-dance.db \
  "select user_id, ip, created_at from sessions order by created_at desc limit 5"   # 真实公网 IP，而不是 127.0.0.1
```

### 2.4 第 3 天（3–5 小时，建议周末）

**3.1 微信/QQ 引导卡 + 缓存头**（3–4 h + 1 h）：`frontend/src/utils/platform.ts`（UA 识别 `MicroMessenger`、`QQ/`、iOS、Android、`display-mode: standalone`）、`components/layout/InstallHint.tsx` 挂在 `/today`（微信/QQ 内不可关闭：「微信内无法添加到主屏幕：点右上角「⋯」→「在浏览器打开」」；iOS/Android 的提示可关闭 14 天）、「我的」里加一行「添加到主屏幕」，文案进 `zh.ts` 并逐行镜像到 FRONTEND.md §8（契约测试会比对）；后端 `_mount_spa` 给 `index.html` 字面路径、`manifest.webmanifest`、`sw.js` 返回 `no-cache`，`/assets/*` 不存在时返回 404 而不是 `index.html` 200。部署后 `curl -sI https://DOMAIN/manifest.webmanifest` 应为 `application/manifest+json`。
**3.2 自己的手机检查清单**：iPhone Safari 添加到主屏幕后图标与名称、是否独立窗口、是否要重新登录、深色模式状态栏、首张卡片自动发音需不需要先点一下、导出按钮行为、详情页能否返回；微信里打开链接 → 引导卡出现 → 「在 Safari 中打开」是否顺畅、有没有「非微信官方网页」拦截页；安卓（手头有的）浏览器菜单添加到桌面、发音是否出声。
**3.3 邀请其余朋友**：每个 Wi‑Fi 每小时 ≤ 4 人注册，同一屋的人用流量；邀请码粘贴。
**3.4 鸿蒙 NEXT 的朋友**：先在一台真机上验证华为浏览器快捷方式是否独立窗口、登录能否保持、发音是否出声；否则明确告知「网页版，部分功能未测」。

### 2.5 第 4–7 天

**4.1 运维收口**（第 4 天，约 1.5 小时）：恢复上限；把 `/etc/sudoers.d/sqin` 收窄到安装脚本需要的命令（`systemctl`、`tee /etc/systemd/system/*`、`apt-get`、`cp` 到 systemd 目录）或升级时再临时放开——`wd serve` 和 `claude` 子进程都以 `sqin` 运行，全量免密 sudo 意味着任何代码执行漏洞都是 root；轻量控制台做一次快照；外部拨测（UptimeRobot 免费档每 5 分钟查 `https://DOMAIN/api/health`，监控绿而朋友说打不开 = 大陆链路问题）；恢复演练（`gunzip -c 最新备份 > $D/tmp/drill.db && wd check db --db $D/tmp/drill.db`）。
**4.2 监控 cron**（以 `sqin` 每 10 分钟运行，推送到你自己的 Bark 或 Server酱 URL；只读查询必须带 `.timeout`；事件种类按代码实际写入的列出，`provider_blocked` 只存在于注释里从不写入）：

```bash
cat > /home/sqin/word-dance-data/bin/wd-watch.sh <<'EOF'
#!/bin/sh
D=/home/sqin/word-dance-data; DB=$D/word-dance.db; ST=$D/tmp/watch.last; NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
Q() { sqlite3 -readonly -cmd ".timeout 5000" "$DB" "$1" 2>/dev/null; }
m=""
curl -fsS -m 10 http://127.0.0.1:8000/api/health >/dev/null || m="$m health:DOWN;"
p=$(Q "select value from kv where key='claude.paused_until'"); [ -n "$p" ] && [ "$p" \> "$NOW" ] && m="$m ai_paused_until:$p;"
[ "$(Q "select value from kv where key='claude.available'")" = "0" ] && m="$m claude_unavailable;"
k=$(Q "select group_concat(distinct kind) from system_events where created_at > strftime('%Y-%m-%dT%H:%M:%SZ','now','-10 minutes') and kind in ('claude_auth','claude_unavailable','claude_paused','claude_overloaded','budget_daily','budget_monthly','budget_svg','backup_failed','downtime','lease_lost')")
[ -n "$k" ] && m="$m events:$k;"
f=$(Q "select count(*) from push_batches where webhook_status='failed' and published_at > strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 day')"); [ "${f:-0}" != "0" ] && m="$m webhook_failed_24h:$f;"
a=$(df --output=avail -m "$D" | tail -1); [ "${a:-99999}" -lt 2048 ] && m="$m disk_free_mb:$a;"
[ -z "$m" ] && { rm -f "$ST"; exit 0; }
[ -f "$ST" ] && [ "$(cat "$ST")" = "$m" ] && [ "$(( $(date +%s) - $(stat -c %Y "$ST") ))" -lt 21600 ] && exit 0   # 同一告警 6 小时内只发一次
printf '%s' "$m" > "$ST"
curl -fsS -m 10 -H 'Content-Type: application/json' -d "{\"title\":\"word-Dance watch\",\"body\":\"$m\",\"desp\":\"$m\"}" "$(cat $D/watch.url)" >/dev/null
EOF
chmod 700 /home/sqin/word-dance-data/bin/wd-watch.sh
# 把你自己的 Bark 或 Server酱 URL 写进 $D/watch.url（0600），然后：
( crontab -l 2>/dev/null; echo '*/10 * * * * /home/sqin/word-dance-data/bin/wd-watch.sh' ) | crontab -
```

**4.3 第 5–6 天：webhook 补丁**（约 1 人日，仅后端，无 schema 改动）：`safe_post` 保留响应体并按格式解析（企业微信 `errcode`、飞书 `code`、Server酱 Turbo 与 ³ 的 `code`）≠ 0 时抛 `WebhookError`（重试与 `delivery_error` 从此真实，测试按钮如实显示失败）；企业微信改 `msgtype: markdown`（4,096 字节上限，带 `[打开 word-Dance](url)` 链接）或截断到 2,048 字节；测试消息带上 `/today` 链接；若第 2 天演练发现 Server酱标题被截断/拒绝，则给它一个 ≤ 32 字的标题。部署后再向用企业微信/飞书/Server酱³ 的朋友开放。
**4.4 第 7 天**：延期文案改为显示真实恢复时间（按小时、次日 00:05 或下月 1 日 00:05，约 1.5 小时）；把解锁 SQL、取消队列 SQL、换 IP 流程、续费日期、80 天 TestFlight 周期写进私人运维笔记。

第一周每天看一眼的清单：

| 看什么 | 怎么看 | 什么时候动手 |
|---|---|---|
| 花费与队列 | 管理 → 概览：今日/本月花费、SVG、队列中/运行中/失败 | 中午前今日花费 > $4 → 查批量标记洪峰（1.3 节取消语句）；失败 > 0 → 任务页重试 |
| AI 健康 | 事件 `claude_auth`/`claude_unavailable`/`budget_*`；横幅「Claude CLI 未登录」 | 先 `wd claude-check`；通过则管理页「恢复 AI」；失败且是登录字样 → 重做 2.1 的 A/B；横幅无论真实原因都写「以 sqin 身份登录」 |
| 送达 | `GET /api/admin/jobs?type=send_webhook` 的 `last_error`；第一天直接问朋友 | 没收到 → 对方的 key；补丁前企业微信/飞书/Server酱³ 的失败是看不见的 |
| 照片与 SVG | 概览的照片/AI 示意图/仅文字卡片构成，来源冷却 | 多是 SVG/文字 → Pixabay key 或调 SVG 子上限 |
| 锁定与限流 | `select key, count, blocked_until from auth_throttle` | 被锁 → 1.3 节解锁语句；忘密码 → 管理 → 用户 → 重置密码 |
| 备份 | `systemctl status word-dance-backup.timer`；Mac 上 `ls ~/word-dance-vps-backups/backups` | 文件缺失 → `journalctl -u word-dance-backup`；事件 `backup_failed` |
| 大陆可达性 | 第 4、7 天晚上再测一次 | 丢包 > 5% → 新加坡；被墙 → 控制台换 IP（一生一次）+ 改 A 记录（TTL 600 → 10 分钟内生效）；第二次 → 用快照重建新实例 |

### 2.6 第 8–14 天

每天 2 分钟看概览，或者信任 cron。第 14 天：`WD_REGISTRATION_MODE="closed"` 并重启（以后来新朋友再开一晚 `invite`）。按触发条件做可选补丁：主屏网页里的导出回退（iPhone 独立窗口下 `<a download>` 会卡在「打开方式」面板，改用 `navigator.share({files})` 或剪贴板，1.5–2 h）；运行器分类器与横幅中性化（若凭据是 claude.ai 登录：把托管设置拉取失败、403、用量上限等字样归为短重试而不是 30 分钟暂停，横幅不再写「以 sqin 身份登录」，约 4 h）；`wd unlock`（1.5 h）；详情页返回按钮（若独立窗口没有边缘返回手势，0.5 h）。把第 14 天的数据记下来：各设备类别的活跃人数、本月花费、失败任务、送达失败、朋友对提醒与发音的反馈、鸿蒙 NEXT 人数。

### 2.7 第 14–28 天：App 决策门

启动 App 的条件（同时满足）：(a) 网站稳定运行 14 天，无计划外中断或换 IP 事件；(b) 至少 3 位 iPhone 朋友明确要 App 图标或嫌中继提醒不够，**或** 至少 2 位安卓朋友在浏览器里没有可用发音或没有可接受的提醒渠道；(c) 你在两周内有 3 个晚上加一个周末日；(d) 朋友已告知 iOS 版本（TestFlight 需 ≥ 16）与 Apple 账号邮箱、并愿意接受 App Store Connect 邀请。鸿蒙 NEXT 的朋友永远不构成启动理由（网页是唯一选项）。启动后按 4.3 节执行：第 1 周注册苹果账号、下载工具链、搭骨架；第 2 周网站侧适配、TTS、安全区、真机 QA；第 3 周发布——**Android 先、iOS 后**（APK 不用等苹果，且无 GMS 国产机收益最大）。不要向朋友承诺日期：苹果注册通常 1–3 天但有数周的离群值，TestFlight 安装与 App 的商店状态耦合，还有过长达数月的苹果侧故障。

## 3. 托管：把服务放在哪

硬性过滤：Anthropic 支持地区名单包含日本、新加坡、台湾、韩国、美国，不含中国大陆、香港、澳门，且香港机房 IP 实测被 `api.anthropic.com` 以 403 `Request not allowed` 拒绝（2026 年 10 月两个独立项目因此把工作负载从 Cloudflare 香港节点迁到新加坡/美国）。**香港虽然延迟最好（12–45 ms），但不能选。**（hosting F1、F2）

| 方案 | 地区 | 价格 | 大陆延迟 | 服务器到 Anthropic | 开户摩擦 | 主要风险 |
|---|---|---|---|---|---|---|
| **腾讯云轻量 中国站 2c4g/60G/30M/1.5TB** | 东京（默认）或新加坡 | 约 ¥42/月（第三方 2026-10 数据；国际站官方 $6.00）；新用户年付促销 ¥199/年，2c2g 为 ¥33/月或 ¥99/年 | 东京到上海 45–70 ms、北京 60–80 ms、华南 80–120 ms；电信晚高峰有丢包报告 | 直连（日本/新加坡在名单内） | 最低：已有实名、微信/支付宝、人民币发票 | 腾讯对所有境外地域都声明不保证跨境质量；公网 IP 整个生命周期只能更换一次；促销价每月变 |
| 阿里云轻量 国际型 2c2g | 新加坡/东京 | 约 ¥39/月 | 同上 | 直连 | 低 | 阿里文档明确「非直连…不建议」大陆用户使用 |
| Vultr / DigitalOcean | 东京 / 新加坡 | $5–12 / $6–18 | 东京走 NTT，电信晚高峰丢包 10–20% | 直连 | 境外账户（支持支付宝/微信） | 价格与线路都不优于腾讯 |
| Hetzner | 新加坡或欧洲 | €15.5–26.5 / €5.49 | 绕日美，250 ms+ | 直连 | 需要身份证件核验 | 线路差 |
| 腾讯云轻量 香港 | 香港 | ¥32–55/月 | 最佳 | **403，不可用** | 低 | 需要再加一台中转，直接淘汰 |
| Cloudflare Tunnel（Mac 直接对外） | 美西节点 | ¥0 | 80–300 ms+，40 KB/s 级吞吐报告，周期性 IP/SNI 封锁 | 复用 Mac 的 SOCKS 隧道 | 命名隧道要求域名托管在 Cloudflare DNS | 不是 7×24 服务；仅适合当晚演示（`trycloudflare.com` 快速隧道连账号都不用） |
| Tailscale | — | ¥0 | — | — | **大陆 App Store 没有 Tailscale**（商店查询 `country=cn` 返回 0 条） | 对这群朋友是死路 |

配套事实：境外托管不需要 ICP 备案（阿里云 FAQ 原文）；DNSPod/阿里云 DNS 会解析未备案域名到境外 IP，但要求账号实名与域名实名；免费版 DNSPod/阿里云 DNS 的最小 TTL 是 600 秒（Cloudflare 仅 DNS 为 60 秒），所以「换 IP 几分钟生效」要按 10 分钟计；GFW 对不跑代理流量的小型私人站点很少封锁，风险形态是「换 IP 前不可达几小时」。阿里云 FAQ 还提到指向境外服务器的域名仍应做公安联网备案，这属于你已推迟的法律判断。（hosting F12–F14、F20 及核验）

## 4. iOS 与 Android：路线与事实

### 4.1 按设备类别看朋友能得到什么

| 设备类别 | 安装入口（网页） | 每日提醒 | 发音 | App 能多给什么 |
|---|---|---|---|---|
| iPhone（Safari） | 分享 → 添加到主屏幕；iOS 26 起默认独立窗口，不需要 manifest；加了图标补丁后更像 App | Bark（锁屏推送，¥0）、Server酱 → 微信 | 可用；冷启动首张卡可能要先点一下 | 便利：本机定时提醒、无需 Bark、启动不经 Safari；代价是 ASC 邀请与 90 天重装 |
| iPhone（从微信点开） | 微信内置浏览器不能添加到主屏幕：右上角「···」→「在 Safari 中打开」；可能出现「非微信官方网页」拦截页 | 同上 | 同上（微信内置浏览器内未验证） | 同上 |
| 有 GMS 的 Android | Chrome「安装」生成 WebAPK（需要 manifest + 图标） | Server酱 / ntfy | Chrome 桥接系统 TTS，需装英文语音 | 本机提醒、原生 TTS；Google 的开发者验证 2027 年才全球生效，届时注册免费的「有限分发账号」（20–50 台设备）或走高级流程 |
| 无 GMS 的国产 Android（小米/OPPO/vivo/荣耀，大陆默认） | 自带浏览器「添加到桌面」（是否独立窗口未验证）；Chrome 若有也只是快捷方式 | Server酱 → 微信（任何手机）；Server酱³（走厂商系统推送通道，补丁后开放）；Web Push 不可用 | 取决于机型有无英文 TTS 引擎；**Android System WebView 没有 `speechSynthesis`**，所以 APK 壳必须接原生 TTS 插件 | **收益最大**：真图标与独立窗口、本机定时提醒、原生发音；代价是「未知来源」与各品牌纯净模式弹窗、自启动/省电白名单 |
| 鸿蒙 4.x | 华为浏览器「添加至桌面」；APK 仍可侧载 | 同上 | 未测 | 可装 APK，但这一类随升级到 NEXT 而缩小 |
| 鸿蒙 NEXT（2024 年底起所有华为新机） | 华为浏览器桌面快捷方式（最多 10 个，无 manifest/独立窗口说明） | Server酱 → 微信、企业微信、飞书（三者都有鸿蒙原生版） | ArkWeb 实现了 SpeechSynthesis，语音包未测 | **无**：装不了 APK；AppGallery 的「卓易通」安卓容器能装本地 APK，但通知/后台/TTS 未测，只能作为实验，不能承诺 |

Google 开发者验证的现状：2026-09-30 起在巴西、印尼、新加坡、泰国对「参与商店」的安装生效，2027 年扩展到全球已认证设备；Google 帮助页写明 AOSP 与未认证设备、以及不支持 GMS 的地区不适用，所以大陆无 GMS 手机今天不受影响。国内应用商店上架需要 APP 备案（前提是大陆托管与 ICP）+ 软著，小米 2024-10 起不再收录个人开发者应用，OPPO/vivo 不对个人开放普通 APK 上架——本轮不考虑商店。（android F1–F5、F14 及核验）

### 4.2 iOS 分发路径

| 路径 | 费用 | 人数上限 | 审核 | 过期 | 对大陆朋友的摩擦 | 结论 |
|---|---|---|---|---|---|---|
| 主屏网页应用 | ¥0 | 无限 | 无 | 无 | 要离开微信到 Safari；是否要再登录一次待真机确认 | **先做** |
| TestFlight 内部测试组 | ¥688/年 + Xcode | 每组 100 人；个人账号可加 50 个 App Store Connect 用户 | **无** | 每个构建 90 天 | 朋友要有邮箱与 Apple 账号、3 天内接受 ASC 邀请（账号必须与受邀邮箱一致，否则用兑换码）、安装 TestFlight（iOS ≥ 16，国区商店有）；大陆 Apple ID 可以 | **做 App 时的首选** |
| TestFlight 外部公开链接 | 同上 | 10,000 | 每个版本首个构建要过 Beta App Review，远程壳有 4.2 风险；被拒的构建连内测也不能再用 | 90 天 | 最省事 | 只在构建能过 4.2 时用 |
| Ad Hoc | 同上 + https 托管 | 每年 100 台设备 | 无 | 描述文件约 1 年 | 每人提供 UDID | 拒绝开 ASC 账号的朋友的备选 |
| 免费个人团队 | ¥0 | 3 台 | 无 | 7 天 | 每周连线重签 | 不可行 |
| App Store（非中国区 / 中国区） | ¥688 / + ICP | 公开 | 完整审核 / + ICP 字段 | 无 | 大陆 Apple ID 看不到其他区商店；中国区需要大陆托管与备案 | 本轮不做 |

其他已核实事实：Apple Developer Program 用 Mac 上的 Apple Developer 应用注册（身份证 + 人脸，¥688/年自动续订，支付宝/微信/银行卡，不能用账户余额；社区报告 1–3 天，姓名地址不一致时有数周离群值）；Xcode 27.2（2026-10-30，3.12 GB，需 macOS 26.6+，本机满足）；2026-04-28 起所有上传（含 TestFlight）必须用 iOS 26 SDK；每个上传的构建都会停在「缺少出口合规信息」，Info.plist 写 `ITSAppUsesNonExemptEncryption = NO` 可免每 90 天手动回答；TestFlight 能否安装在实践中与 App 的商店可用性状态耦合，所以 App Store Connect 里保留全部 175 个地区（含中国大陆）的默认可用性，且不要设「Removed from Sale」；中国 iOS 约 75% 在 iOS 26、16% 在 iOS 18（2026 年 8–9 月数据，9 月发布的 iOS 27 行为一致）。（ios F1–F12、F21 及核验）

### 4.3 做 App 的技术路线：Capacitor 远程壳

三种模式对照（capacitor 摘要与核验）：

| 模式 | 后端改动 | 原因 | 人日（双端） |
|---|---|---|---|
| **M1 远程壳**：`server.url = https://DOMAIN`，WebView 直接加载线上站点 | **无** | 页面源与 API 源相同：`HttpOnly; SameSite=Lax` cookie、只认 Host/`WD_PUBLIC_URL` 的 CSRF 规则、需要 cookie 的 `/media`、CSP 全部原样工作（已在临时实例用 curl 矩阵复现）；网站一发布 App 就更新 | ≈ 6（5–7.5） |
| M2 打包静态资源 + CapacitorHttp | 需要 | WebView 源是 `capacitor://localhost`（iOS）/`https://localhost`（Android），CSRF 直接 403（实测）；`<img>` 跨站不带 cookie 导致 `/media` 401，要签名 URL；核验澄清 CapacitorHttp 的 POST 不带 Origin，所以卡点只在图片鉴权与绝对 API 地址 | 7–9 |
| M3 Bearer token | 需要（2–3 人日后端） | 上周文档 §4.3 | 8–11 |

M1 的机制已从 Capacitor 8.6 源码核实：iOS 用 `WKUserScript` 把桥注入每个主框架文档；Android 用 `addDocumentStartJavaScript` 且**只对 `server.url` 的精确源生效**，任何跳转（http→https、顶级域→www）都会让 Android 壳里没有 `window.Capacitor`，所以 `server.url` 必须等于 `WD_PUBLIC_URL` 这个规范源，QA 要断言 Android 上 `window.Capacitor.isNativePlatform() === true`。`window.Capacitor.Plugins` 对远程页面为空，网站要自己引入 `@capacitor/core` 与插件 JS，并用 `Capacitor.isNativePlatform()` 特性检测，浏览器里零变化。即使内容远程，iOS 壳仍要求本地 `webDir` 里有 `index.html`（兼作离线/重试页）。Ionic 文档称 `server.url` 「不用于生产」，App Store 4.2 对远程壳也适用——这两点只在上架或外部 TestFlight 时才成为问题，内部测试与 APK 侧载没有审核。（capacitor F4、captool 核验）

**工具链（本机）**：Xcode 27.2（3.12 GB，装完约 9–12 GB；iOS 模拟器运行时约 7.9 GB 可省，直接用真机）；Android 走命令行 `brew install --cask temurin@21 android-commandlinetools` + `sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"`（约 1–2 GB；Gradle 走 `~/.gradle/gradle.properties` 的 HTTP 代理或阿里云 Maven 镜像）；Node 保持 22（Capacitor 8 需 22+，9 需 24，9 的 GA 定在 2026 年 11 月底）；不需要 CocoaPods（SPM 默认，CocoaPods trunk 2026-12-02 起只读）。本机经代理下载，时间按 2–4 倍估；合计约 15 GB 下载。

**工程与配置**（仓库顶层 `mobile/`，约 0.5 人日）：`@capacitor/core|cli|ios|android` 全部 **精确 8.6.0**（≥ 8.5.1 是硬要求：CVE-2026-103922，CVSS 9.3，远程内容可经内部代理路径以应用源加载，8.4.3/8.5.1 修复）、`@capacitor/app@8.1.2`、`@capacitor/local-notifications@8.3.1`、`@capacitor-community/text-to-speech@8.0.2`、`@capacitor/assets`。`appId` 一经选定不可更改。`capacitor.config.ts` 要点：`server.url` 规范源、`cleartext: false`、`errorPath: 'index.html'`、`allowNavigation` 留空（署名链接走系统浏览器）、`appendUserAgent: 'word-Dance-App/1'`、`ios.limitsNavigationsToAppBoundDomains: false`、`android.minWebViewVersion: 108`、`plugins.SystemBars: { insetsHandling: 'native', initialViewportFitValueHint: 'cover' }`（避免 WebView ≥ 140 的首屏跳动，Capacitor 9 默认）、`plugins.LocalNotifications: { smallIcon, iconColor: '#3b5bdb', presentationOptions: ['banner','sound','list'] }`；Android 清单加 `USE_EXACT_ALARM`（侧载不受 Play 政策约束，自动授予，省掉 `schedule()` 默认会跳到的「闹钟和提醒」设置页）。

**网站侧适配**（约 1 人日含测试）：`frontend/src/native/capacitor.ts` — `isNative()`、把 `settings.push_time` + 时区换算成设备本地时间、在用户手势内申请通知权限、幂等地取消再重排每日本地通知（通知正文固定为「今日词汇已准备好，点开复习」，点击跳 `/today`）、Android 返回键、**每次启动/恢复时重排**（插件首次触发后重排会丢掉 `allowWhileIdle` 与唤醒型闹钟，不重排的话从第 2 天起休眠中的手机会延迟）；`AuthProvider` 按推送设置变化同步；`useSpeech` 原生分支走 TTS 插件（Android 必做，iOS 可选统一）并在无英文语音时提示 `openInstall()`；导出按钮在壳里隐藏或改 `Filesystem + Share`；CSS 给 `.page`、`.auth`、学习页与筛词页加顶部安全区内边距（0.5 人日，浏览器里零变化）。

**iOS 发布**（0.5 人日 + 苹果等待）：App Store Connect 建 App（主语言简体中文，**保留全部地区**）→ Xcode 自动签名、部署目标 17.0（有 iOS 16 朋友则 16.0）、`ITSAppUsesNonExemptEncryption = NO` → Product → Archive → Distribute → **TestFlight Internal Only** → 内部测试组 → 把朋友加为 Marketing 角色、仅限本 App 的 ASC 用户（邀请 3 天内接受，必须用受邀邮箱对应的 Apple 账号，否则兑换码）→ 他们装 TestFlight 接受。**永远不要**把这个构建加进外部组「试试看」：Beta App Review 一旦拒绝，内测也不能再用。日历每 ≤ 80 天重新上传一次；每年 4 月前用当年的 Xcode 重新归档。

**Android 发布**（0.5 人日）：`keytool` 生成签名库并备份到仓库之外两处（丢了就是新包名），`signingConfigs.release` + 单调递增的 `versionCode`（如 `2026120101`），`./gradlew assembleRelease`，APK 放到服务器 `/srv/word-dance-dl/`，Caddy 在 `reverse_proxy` 之前加 `handle_path /dl/* { root * /srv/word-dance-dl; header /*.apk Content-Type application/vnd.android.package-archive; file_server }`（手改 `/etc/caddy/Caddyfile`，之后升级永远不要再带 `--with-caddy`）。中文安装说明按品牌：允许未知来源；小米纯净模式「授权单次安装」；vivo 设置 → 安全与隐私 → 更多安全设置 → 应用安装；OPPO 设置 → 密码与安全 → 系统安全 → 外部来源应用；华为/荣耀 设置 → 系统和更新 → 纯净模式 → 退出；小米自启动 + 省电策略「无限制」。网站改动不需要新 APK，只有壳/插件变了才需要。

**估算**：工具链 0.5 + 骨架 0.5 + 网站侧适配 1 + TTS 0.5 + 安全区 0.5 + 真机 QA 1 + iOS 发布 0.5 + Android 发布 0.5 + 缓冲 0.5 ≈ **6 人日**；Android 优先路径约 2.5–3 人日即可交付 APK。

### 4.4 其他壳方案为什么不选

PWABuilder iOS（社区维护，推送只支持 Firebase，没有定时器）、TWA/Bubblewrap（需要 Chrome，无提醒 API，无 GMS 机型退化成普通 WebView）、Tauri 2（多一套 Rust/CocoaPods/NDK 工具链，没有收益）、Expo + WebView（更重，只有本机装不了 Xcode 时才值得，EAS 每月 15 次免费 iOS 云构建是唯一优势）。（captool 对照表）

## 5. 每日提醒：朋友今天就能用的渠道

后端已有 `send_email` 与 `send_webhook`（`generic`/`wecom`/`feishu`/`serverchan`/`bark` 五种格式），在每个用户自己时区的推送时间发一次摘要（标题 43–44 字，正文约 1.9–2.0 KB 含 10 个词与 `<WD_PUBLIC_URL>/today` 链接），批次在推送前 3 小时内构建，晚于 6 小时则跳过，webhook 失败重试 2 次（2 分钟、10 分钟后）。晚上注册的朋友第一条「今日词汇」在次日早上的推送时间到。（reminders F1、F2、F11）

| 渠道 | iPhone | 无 GMS 的 Android | 有 GMS 的 Android | 鸿蒙 NEXT | 朋友要装什么 / 费用 | 已核实的坑 |
|---|---|---|---|---|---|---|
| Bark（格式 Bark） | ✓ 锁屏推送 | ✗ | ✗ | ✗ | Bark（App Store 免费）；`api.day.app` 本机网络 0.2 秒可达 | 一人一台设备，key 明文存在服务器；坏 key 返回 400 能被正确报告；换机重装 Bark 后 key 会变，要重新粘贴 |
| Server酱 Turbo → 微信服务号（格式 Server酱） | ✓ | ✓ | ✓ | ✓ | 只要有微信；免费 5 条/天，付费 ¥39/年 | 卡片只显示标题，正文在详情页；文档说标题 32 字而我们是 43–44 字，截断还是拒绝待真 key 测试；链接在微信内置浏览器打开（另一套 cookie），建议朋友收到提醒后点桌面图标进 |
| Server酱³ 应用（同一格式，URL 换成 `<uid>.push.ft07.com`） | ✓ | ✓ 走小米/华为/荣耀/vivo/OPPO 系统推送通道 | ✓ | ？无鸿蒙版说明 | 独立 App；测试期免费 | API 路径本机 0.54 秒可达，但错误也返回 HTTP 200，补丁后再用 |
| 企业微信群机器人 | ✓* | ✓* | ✓* | ✓* | 企业微信 + 入群 | **正文上限 2048 字节而真实摘要是 1,982–2,061 字节**，超长会被拒；错误以 HTTP 200 返回，服务器会误记为已发送 |
| 飞书自定义机器人 | ✓* | ✓* | ✓* | ✓* | 飞书 + 入群 | 错误以 HTTP 200 返回；不能开签名校验 |
| ntfy（格式 通用 JSON + 模板 URL） | ✓ | ✓* F-Droid 版前台服务 | ✓ | ✗ | ntfy 应用；ntfy.sh 免费 250 条/天/发送 IP | 模板 URL 已端到端验证；服务器在境外 |
| 邮件 | ✓* | ✓* | ✓* | ✓* | 无；需要配置 SMTP | 境外 VPS 发往 QQ/163 的到达率未验证 |

代码缺陷（第 2.5 节补丁解决）：`safe_post` 把任何 2xx 都当成功且不读响应体，所以企业微信、飞书、Server酱³ 的坏 key 会显示「测试成功」、批次被标为 `sent`、任务账本 `last_error` 为空。送达状态目前对用户与管理页都不可见，只能查数据库或任务接口。（reminders F3、F7 及核验）

## 6. 需要你决定的事

| # | 决策 | 选项 | 建议默认 |
|---|---|---|---|
| D1 | 地区 | 东京 / 新加坡（香港排除） | **东京**；第 0 天 curl 403 或第 1 天晚上丢包 > 5% 则新加坡，同价 |
| D2 | 机型 | 2c2g ¥33 / 2c4g ¥42 | **2c4g**（机上构建前端与 CLI 的内存余量）；看活动页年付价 |
| D3 | 域名与 DNS | 已有域名的子域 / Porkbun 支付宝 / 万网实名；DNSPod（600 s）/ Cloudflare 仅 DNS（60 s） | **已有域名优先，否则 Porkbun `.com`；DNS 放 DNSPod**；要 60 秒 TTL 就 Cloudflare 灰云 |
| D4 | `claude` 凭据接法 | 存盘登录 / `setup-token` / API key / 网关 / `apiKeyHelper` | **你的决定（已推迟）**；无论哪种都走包装脚本或 drop-in，永远不进 `.env` 或单元文件；技术事实见 0.4 |
| D5 | Mac 数据 | 原样复制（含 48 条内容、30 张 SVG）/ 新库 + 导入 | **原样复制**（关闭管理员竞态，保留你的生词库）；上周文档建议重做那 48 条内容属于已推迟的问题，以后用管理页「重新生成」< $1 |
| D6 | 预生成 | 不做 / 每个阶段最高频 1,000–2,000 词（$5–12）/ 全部（$41–54） | **朋友主攻阶段的前 2,000 词，第 2 天晚上跑** |
| D7 | AI 上限与 SVG 子上限 | 日 6 / 月 100 / 小时 60；SVG 0.5 / 1.0 / 0 | **6 / 100 / 60 邀请前设好；SVG 48 小时后按东京能否取到照片定** |
| D8 | 邀请码 | 每人一个单次 14 天码 / 一个 10 次共用码 | **每人一个**，全员进来后 `closed` |
| D9 | 第一周提醒渠道 | 只开 Bark + Server酱 Turbo / 全部 | **只开前两个**，补丁后再开企业微信/飞书/Server酱³ |
| D10 | 备用管理员 | 建 / 不建 | **建**（2 分钟；任何知道你用户名的人都能把它锁 15 分钟到 24 小时，没有解锁命令） |
| D11 | 苹果开发者注册（¥688） | 现在 / 第 14 天决策门之后 | **决策门之后**（注册通常只要 1–3 天，不必先花钱）；你若已决定要 App，则第 0 天就注册并开始下载 Xcode，不影响服务器那条线 |
| D12 | App 顺序 | Android 先 / iOS 先 | **Android 先**（不等苹果，收益最大） |
| D13 | 朋友里有未成年人 | 有 / 无 | 有则在说明里加一句请家长先看注意事项（没有年龄门槛） |
| D14 | Mac 实例 | 保留 14 天作回滚后退役 / 继续开发用 | **数据目录保留 14 天，两个代理保持停用**；`make dev` 不受影响 |

## 7. 给朋友的中文说明（粘贴到微信，替换 ⟨⟩ 两处）

```
嗨，我做了一个每天背几个英语单词的小工具 word-Dance，邀请你一起用（只有几个朋友在用，算内测）。

网址：https://⟨DOMAIN⟩
你的邀请码：⟨XXXX-XXXX-XXXX-XXXX⟩（只能用一次，14 天内有效，请复制粘贴，不要手打）

一、注册（2 分钟）
1. 重要：不要在微信里直接打开。iPhone 请点右上角「···」→「在 Safari 中打开」；安卓请点「···」→「在浏览器打开」。微信里打开的页面没法添加到桌面，还要多登录一次。
2. 点「去注册」，填用户名、密码（至少 8 位，别用太常见的）、邀请码。邮箱可以不填。
3. 按提示选「目标阶段」「主攻阶段」「每日推送时间」，时区点「自动检测」就行。
   提示：同一个 Wi-Fi 一小时内最多注册 5 个账号（输错邀请码也算次数），如果提示「稍后再试」，换成手机流量或者等一小时。

二、添加到桌面（像 App 一样打开）
- iPhone：Safari 底部「分享」按钮 →「添加到主屏幕」→「添加」。以后从桌面图标进，第一次可能要再登录一次，之后 30 天内不用重复登录。
- 安卓（小米/OPPO/vivo/荣耀自带浏览器、Chrome、QQ浏览器）：浏览器菜单 →「添加到桌面」或「安装应用」。
- 华为（鸿蒙）：华为浏览器右下角「∷」→「添加至桌面」。鸿蒙 NEXT 的手机只能用网页版，个别功能我还没测过，有问题告诉我。

三、每天的提醒（选一个就好，1 分钟）
- iPhone 推荐 Bark：App Store 装免费的 Bark → 打开复制那串 https://api.day.app/… 的地址 → 回到 word-Dance「我的」→「推送设置」→ 打开「Webhook 推送」→ 粘贴到「Webhook 地址」→「格式」选 Bark →「发送测试」，手机收到通知就成了。
- 任何手机用微信收：在微信里打开 sct.ftqq.com（Server酱），长按识别页面上的二维码登录 → 复制 SendKey → 回到 word-Dance「我的」→「推送设置」→ 打开「Webhook 推送」→ 地址填 https://sctapi.ftqq.com/你的SendKey.send →「格式」选 Server酱 →「发送测试」，微信里的「方糖」服务号会收到一条消息（免费版每天 5 条，够用）。收到提醒后请点桌面图标进去学，别在微信里面点。
提醒会在你设的「每日推送时间」到；今晚注册的话，第一条明天早上才有。暂时先别用「企业微信机器人」和「飞书机器人」，下周我修好一个小问题再开放。

四、几件要知道的事
- 密码连输错 10 次会锁 15 分钟，再错会锁更久；忘了密码直接找我重置。
- 单词卡上的「发音」第一次可能要先点一下才出声；如果按钮是灰的或没声音，换个浏览器试试（iPhone 用 Safari，安卓优先用系统自带浏览器或 Chrome），安卓还可能需要在系统「文字转语音」里装一个英文语音包。
- 图片是大家共用的：「换一张」和「不合适」会换掉所有人看到的那张图，别随手点着玩。
- 例句、搭配、记忆提示由 AI 生成，仅供参考；你标记的单词和写的短备注会发给 AI 服务来生成例句。每天的 AI 额度用完时例句会延后补齐。随时可以在「我的」里导出或删除自己的全部数据。
- 这是业余做的内测，服务器在东京，偶尔抽风请直接微信我，我每天都会看一眼后台。
```

若朋友中有未成年人，加一句：「如果是给孩子用，请家长先看一下上面第四条再帮忙注册。」不要在说明里承诺 App 的日期；真要发 TestFlight 邀请时再单独告知。

## 8. 风险与对策（前 8 项）

| # | 风险 | 可能性 / 影响 | 对策 |
|---|---|---|---|
| 1 | VPS 的 IP 被 `api.anthropic.com` / `platform.claude.com` 拒绝（403） | 东京/新加坡低，香港确定 / 没有 AI | 第 0 天先 curl；403 换新加坡；绝不选香港；站点在 AI 关闭时照常可用 |
| 2 | 凭据脆弱：登录过期、托管设置拉取失败、用量上限、403 都表现为 30 分钟暂停加误导横幅 | 中（账本里已有 15 次）/ 卡片没例句、补救方向错 | 包装脚本 + 固定版本 + 固定模型；`wd claude-check` 是唯一结论性测试；监控 cron；每周看 `loginExpiresAt`；第 2 周分类器补丁 |
| 3 | 大陆链路：晚高峰丢包、IP 被墙 | 每年低到中 / 几小时不可达 | 21:00 测速；TTL 600；控制台换 IP（一生一次）+ 快照重建流程；机器上不跑任何代理软件 |
| 4 | AI 花费：月上限触顶后全员显示「明天补齐」数周；或一人批量标记洪峰 | 中 / 困惑 | 上限 6/100；每周看本月花费；24 小时暂停 + 已修正的取消语句；夜间整理每人每晚 ≤ $0.40 有界 |
| 5 | 共享 NAT 的限流与锁定 | 邀请当晚中 / 朋友恼火 | 单次邀请码、粘贴、分批、流量；`.timeout` 解锁语句；备用管理员 |
| 6 | webhook 假成功（企业微信/飞书/Server酱³） | 一旦开放必现 / 朋友静默收不到 | 第一周只开 Bark 与 Server酱 Turbo；补丁后再开放；cron 读真实的 `failed` |
| 7 | 微信内置浏览器陷阱：不能加主屏、另一套 cookie、可能的拦截页或域名封禁 | 高 / 中 | 说明第一条就是「别在微信里打开」；第 3 天引导卡；先用自己的微信测域名 |
| 8 | 照片源不可达 → SVG 烧预算或全是文字卡 | 中 / 低 | 第 0 天 curl Wikimedia；第 2 天真实取图；SVG 子上限按结果定；Pixabay/Pexels key 兜底 |

另外两条工程卫生：升级后必须重启（连续两次不重启会删掉在服务的前端快照导致整站 503）；`install.sh` 永远不要在 Mac 上跑（仅 Linux）。

## 9. 成本

| 项目 | 一次性 | 每月 | 说明 |
|---|---|---|---|
| 腾讯云轻量 东京 2c4g | — | 约 ¥42（国际站 $6.00） | 新用户年付促销 ¥199/年出现过，到期按标价续；新加坡同价 |
| 域名 | ¥79（Porkbun `.com` $11.81）或 ¥85（万网） | 约 ¥7 摊销 | `.top` 首年 $1.63 / 续费 $4.63 |
| 预生成 | 每个阶段前 1,000–2,000 词 $5–12；全库 $41–54 | — | 实测 $0.0048–0.0059/词 |
| AI 日常 | — | 实际 $25–60（≈ ¥170–400），硬上限 $100 | 按 API 牌价；若凭据是包月套餐则另计 |
| Bark、Server酱 免费档、DNSPod、Caddy 证书、UptimeRobot 免费档 | ¥0 | ¥0 | Server酱 ¥39/年仅当某人每天 > 5 条 |
| Apple Developer Program（App 阶段） | ¥688/年 | 约 ¥57 摊销 | 自动续订 |
| Xcode、Android 工具链、签名库 | ¥0（约 15 GB 下载） | — | 时间成本 |
| **合计** | 首月约 ¥300–560（域名 + 预生成 + 服务器 + AI） | 稳态约 ¥210–450 | App 阶段再加 ¥57/月 |

## 10. 明确不做的事

| 不做 | 原因 |
|---|---|
| 用 Mac 当服务器（Cloudflare Tunnel / 快速隧道 / ssh -R / frp） | Mac 空闲 1 分钟即睡眠、注销即停、AI 依赖手工隧道、备份只在本机；Cloudflare 免费版无大陆节点且有封锁波次；一台 VPS 多花 2–3 小时一次性解决全部 |
| 香港、阿里云境外、Vultr/DO/Hetzner、Cloudflare 代理、Tailscale | 香港 403；其余价格与线路不优；Tailscale 不在国区商店 |
| Web Push | 6–10 人日（任务类型表重建、VAPID、pywebpush 依赖），只覆盖主屏 iPhone 与有 GMS 的安卓，大陆安卓无效；Bark/Server酱 零成本覆盖同样需求 |
| APNs / FCM 原生推送 | 做了 App 之后的事；FCM 在大陆手机上不可用；本地通知即可 |
| service worker（vite-plugin-pwa） | +338 个包与版本错配窗口，只换来 Android 的安装弹窗与预缓存外壳；iPhone 毫无收益 |
| 邮件渠道 | 境外发往 QQ/163 的到达率要专门处理；所有朋友都有微信 |
| 企业微信 / 飞书 / Server酱³ 在补丁前开放 | 假成功会静默丢失摘要 |
| ntfy 一等格式 | 需要重建 `user_settings` 表（CHECK 约束）加 8 处枚举约 1 人日；模板 URL 今天就能用 |
| 国内应用商店、App Store、外部 TestFlight | 备案 + 软著且多数不收个人；远程壳面对 4.2 审核；被拒即全体不可用 |
| 鸿蒙 NEXT 原生应用 | 新 ArkTS 代码库、DevEco、同样的备案问题，以周计 |
| Capacitor M2/M3 | 7–11 人日且需后端改动与每次重打包，只有上架才需要 |
| 公网级加固（条款/隐私页、管理员二次验证、按用户 AI 配额、图片投票阈值、邮件找回密码、词库治理工具） | 对 10 位熟人而言全是「以后」项，流程足以覆盖 |
| 策展模式开关、国产模型适配器、内容包工具（`docs/WORD_LIBRARY_CURATION.md`） | 你已推迟的问题；本方案不依赖它们 |
| `sqin` 路径通用化、`forwarded_allow_ips` 可配置 | 服务用户就叫 `sqin`、Caddy 同机时无意义 |

## 11. 附录

### 11.1 证据索引

`docs/analysis/2026-11-04-quick-deploy-mobile/`：`facts/` 10 个调研切片（`deploy`、`security`、`pwa`、`capacitor`、`reminders`、`hosting`、`ios`、`android`、`captool`、`clivps`），`verify/` 10 份核验报告（含每条结论的执行命令或一手来源与「遗漏/新发现」），`design-D1-fast.md`、`design-D2-solid.md`、`design-D3-apps.md` 三套方案，`judge-J1-owner.md`、`judge-J2-friends.md`、`judge-J3-eng.md` 三份评审，`INDEX.md` 说明。

### 11.2 核验统计

| 切片 | 核验结论数 | 确认 | 修正 | 无法验证 |
|---|---|---|---|---|
| deploy | 10 | 9 | 1 | 0 |
| security | 10 | 8 | 2 | 0 |
| pwa | 10 | 7 | 2 | 1 |
| capacitor | 10 | 6 | 4 | 0 |
| reminders | 10 | 8 | 2 | 0 |
| hosting | 10 | 6 | 4 | 0 |
| ios | 10 | 8 | 2 | 0 |
| android | 10 | 6 | 4 | 0 |
| captool | 10 | 9 | 1 | 0 |
| clivps | 9 | 9 | 0 | 0 |
| 合计 | 99 | 76 | 22 | 1 |

没有一条修正推翻切片的结论；影响本文的主要修正：`sqlite3` 解锁必须带 `.timeout`；取消队列语句的 `updated_at` 必须显式赋值；注册限流在校验邀请码前计数；Server酱³ 坏 key 也返回 200；`/index.html` 字面路径可缓存 1 小时且 `FileResponse` 不返回 304；Capacitor 的 Android 桥按精确源注入、CapacitorHttp 的 POST 不带 Origin；CVE-2026-103922 的受影响区间；本地通知插件重排时丢失 `allowWhileIdle` 且默认会跳设置页；华为「卓易通」容器可装 APK；Google 帮助页明文豁免 AOSP/未认证设备；小米 2024-10 起不收个人开发者应用；轻量服务器公网 IP 一生只能换一次；免费 DNS 的 TTL 下限 600 秒；腾讯云对所有境外地域都不保证跨境质量；Tailscale 安卓有 APK 但 iPhone 结论不变；TestFlight 安装与商店可用性状态耦合；导出合规键 `ITSAppUsesNonExemptEncryption`。

### 11.3 方案评审

三位评审打分（六项各 0–10，满分 60）：

| 视角 | D1 最快 | D2 稳妥 | D3 应用优先 |
|---|---|---|---|
| 你的时间与日历现实性 | 47 | 44 | 38 |
| 朋友的体验 | 48 | 49 | 43 |
| 工程正确性与运维风险 | 44 | 45 | 40 |

三位一致：D1 与 D2 架构相同（都是东京轻量 + `install.sh` + 先复制数据库 + 零代码邀请），差别只在节奏与第一周的补丁量；D3 的 App 规格正确但把约 11 人日塞进 14 个日历天不现实，且不该向朋友承诺日期。本文以 D2 的可观测、可恢复为底，嫁接 D1 的第 2 天试用、备用管理员、第 1 天关 AI、14 天邀请码、`RunAtLoad`，把 D3 的 App 规格作为第 14 天之后的门控阶段并改为 Android 先行。

评审指出并已在本文修正的错误：三套方案都用 `sessions ORDER BY id`（该表无 `id` 列，应按 `created_at`）；监控脚本监听从不写入的 `provider_blocked`、漏掉实际写入的 `claude_paused`/`claude_overloaded`/`lease_lost`；`wd check providers` 只读旧状态行不能当可达性测试；`provider_state` 的列是 `provider` 不是 `name`；预生成吞吐应按 60 次/小时 = 600 词/小时而不是 300；`rsync --delete` 会把服务器误删同步成本地丢失、日志不能放在同步目录内；`exec $SHELL -l && …` 后半句永远不执行；22.04 镜像下 `PY=python3.12` 对脚本无效（脚本写死 `PY=python3`）；苹果商店 CDN 大陆直连速度是未经验证的假设；全量免密 sudo 应在安装后收窄；`images/` 不在 `wd backup` 里；Server酱 网页二维码无法用同一部手机扫；密码不应写在命令行里。
