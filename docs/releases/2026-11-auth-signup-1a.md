# 注册与登录改造 切片 1-A：手机号 / 邮箱验证码、`verified` 注册模式、重认证与找回密码（迁移 0018，加列不停机）

> 设计：[`docs/AUTH_SIGNUP_DESIGN.md`](../AUTH_SIGNUP_DESIGN.md) §5.1、§5.2、§5.5 行 1-A、§5.6；证据：[`docs/AUTH_SIGNUP_EVIDENCE.md`](../AUTH_SIGNUP_EVIDENCE.md)。业主 2026-11-10 按建议默认值确认了全部 13 项决定（D1a–D12），本切片实现 D1a、D2（含按用户 AI 配额）、D5、D7、D9、D10。
> 状态：实现中（本文随实现更新；「验收」「上线记录」在上线后补齐）。

## 1 起因

- 今天的注册只有「用户名 + 密码 (+ 邀请码)」，没有手机号、没有第三方身份、没有找回密码；改密与注销只认当前密码。同类 App 都以手机号 + 验证码为主身份，邀请码从不作门槛。
- 个人开发者只能用阿里云「号码认证服务 → 短信认证」发验证码（系统签名 + 固定文案，仅 +86），微信 / QQ / Apple 要等备案域名（第二步）。
- 2022 年《移动互联网应用程序信息服务管理规定》第 13 条要求落实未成年人账号的真实身份注册，所以未成年学习者的账号要挂在已验证手机号上；成人保留邮箱路径与不注册的只读演示。

## 2 变更概览

| 领域 | 变更 |
|---|---|
| 数据库 | 迁移 `0018_auth_identities.sql`（纯附加，可 `--no-restart`）：新表 `identities`（手机号等第三方身份，`(provider, subject)` 在未争议行上唯一）、`login_codes`（所有验证码，HMAC 哈希，10 分钟，5 次尝试；取代 `email_codes`，旧表只停写不删）；`users` 加 `password_set_at`（回填为 `created_at`）、`age_band` / `age_declared_at` / `age_declared_ip`（由首次设置 `POST /api/account/profile` 写入）、`account_kind`、`guardian_user_id`、`guardian_consent_at`、`guardian_pin_hash`（后四列供 1-B）；`sessions.actor_user_id`（1-B） |
| 注册模式 | `WD_REGISTRATION_MODE` 新增 `verified`：必须先验证手机号或邮箱；用户名密码只作登录 / 附加方式；邀请码可选。`open` / `invite` / `closed` 行为不变；首个用户仍只能用用户名密码创建（验证码路径在站点未初始化时 403 `setup_required`，永不创建管理员） |
| 验证码登录 | `POST /api/auth/code`（发码）+ `POST /api/auth/code/login`（校验即登录或建号，同一事务）；新账号得到占位用户名 `u_xxxxxxxx`、不可用密码，首次设置（`POST /api/account/profile`）填昵称、年龄段声明，可选用户名与密码 |
| 短信通道 | `WD_SMS_PROVIDER=aliyun_verify`：阿里云 `SendSmsVerifyCode` 只负责代发本地生成的 6 位码（`TemplateParam`），不用阿里云校验；系统签名名 `WD_ALIYUN_SMS_SIGN_NAME`；模板 100001 登录注册 / 100002 换绑 / 100003 重置密码 / 100004 绑定 / 100005 验证绑定 |
| 邮件通道 | `WD_MAIL_PROVIDER=aliyun_dm`：阿里云邮件推送 `SingleSendMail` 作为第二个 `Mailer`（与短信共用 AccessKey，发件地址用 `WD_SMTP_FROM`）；默认仍为 `smtp` |
| 防刷与预算 | 每目标 1/分钟、5/小时、10/天；每 IP 每小时 `WD_CODE_IP_HOURLY`（20）；同号段每小时 5；全站 `WD_SMS_HOURLY_CAP`（40）与 `WD_SMS_DAILY_CAP`（200，新账号发码在 70 % 处停止）；50 / 80 / 100 % 写系统事件，80 / 100 % 推送管理员 webhook；图形验证码（自托管 4 位数字图片，`WD_CAPTCHA=on`）只拦未登录的发码请求 |
| 重认证 | 无密码账号的改密、注销、解绑用验证码代替密码（`POST /api/account/code {purpose:'reauth'}`）；错误次数并入原 10 次 / 15 分钟预算 |
| 找回密码 | `POST /api/auth/password/forgot` + `/reset`：对未知标识、额度耗尽、供应商失败一律 202（不泄露账号是否存在；失败只记日志）；成功后吊销全部会话 |
| 手机号绑定 | 绑定 / 换绑 / 解绑（至少保留一种登录方式，否则 409 `last_login_method`）；密码登录框接受用户名 / 手机号 / 邮箱 |
| 二次放号防护 | 手机号身份 ≥ `WD_PHONE_STALE_DAYS`（90）天未登录即先问「这是你的账号吗」：是 → 密码或邮箱验证码；不是 → 旧绑定标记争议、用该号新建账号，管理页可恢复（`GET/POST /api/admin/identities/...`） |
| 登录限流 | `login:ip` 只计失败；锁定键改为「规范化标识（手机号 E.164 / 小写邮箱 / 小写用户名）+ IP」；验证码校验的 `code_check` 窗口同样只计失败；新增 `wd unlock <标识>` |
| 管理员 | 管理员只能密码登录（验证码命中管理员 → 403 `password_required`）；无密码账号不能提升为管理员（管理页 409 `admin_needs_password`，`wd promote` 拒绝并退出 1） |
| 只读演示 | 登录页「先看看」：`GET /api/demo` + `GET /media/demo/{id}.svg`，三个固定公开词（up / jump / cold）的卡片、释义、例句与单词之舞，无需登录 |
| AI 配额 | `WD_AI_USER_DAILY_WORDS`（80，0 = 不限）：学习者标记触发的例句生成按用户、按 UTC 日计数（北京时间 08:00 重置，与其他 bank 配额一致；AI 预算日仍按 `WD_TZ`），超出后静默跳过并写系统事件 `ai_quota_user`；显式「生成例句」共用计数，且只有真正入队的请求才计数；自定义生词经校验后的内容生成也计入（D2 的前提，PUBLIC_LAUNCH A1 / A2） |
| 其他 | `wd sms-probe <手机号>`（第 0 天实测）；`httpx` 日志降到 WARNING（避免把请求 URL 写进日志）；隐私政策 / 用户协议 / 儿童规则三页静态页面 `/legal/*.html`（文案待业主审定，带〔…〕占位） |

## 3 启用步骤

### 3.1 需业主本人操作（约 2 小时 + 等待）

1. 阿里云账号完成**个人实名认证**；开通「号码认证服务」并进入「短信认证」，记下控制台显示的**系统签名**名称（短信里用户看到的【…】）。
2. 创建一个 RAM 子用户，只授予号码认证服务（和邮件推送，若启用）的系统策略；把 AccessKey Secret 写进数据目录下一个 0600 文件（例如 `aliyun.secret`），AccessKey ID 放进 `.env`。
3. 在号码认证控制台添加 ≤ 5 个**测试号码**（开通前只能发给它们）。
4. 第 0 天实测：`WD_DATA_DIR=… .venv/bin/wd sms-probe +86139xxxxxxxx` → 看手机收到的签名与正文，截图留档；文案可接受则进入 D5 的「接受」。
5. 若启用邮件推送：在阿里云邮件推送控制台添加发信域名（主站域名的子域，如 `mail.<域名>`），按提示加 SPF / DKIM / DMARC / MX 四条 DNS 记录并通过验证，创建发信地址，填到 `WD_SMTP_FROM`。
6. 审定 `frontend/public/legal/privacy.html`、`terms.html`、`children.html` 的文案，替换〔运营者姓名〕〔联系邮箱〕〔服务器位置〕〔备份保留天数〕占位。

### 3.2 服务器（Mac 或 Linux）

1. 备份后编辑 `.env`（先 `cp .env .env.bak-$(date +%Y%m%d-%H%M%S)`）：
   ```
   WD_SMS_PROVIDER="aliyun_verify"
   WD_ALIYUN_ACCESS_KEY_ID="LTAI…"
   WD_ALIYUN_ACCESS_KEY_SECRET_FILE="/path/to/aliyun.secret"
   WD_ALIYUN_SMS_SIGN_NAME="<控制台里的系统签名>"
   # 可选：WD_MAIL_PROVIDER="aliyun_dm"（需要已验证的发信域名；WD_SMTP_FROM 为发信地址）
   # 开放注册时：WD_REGISTRATION_MODE="verified"
   ```
   其余新变量（`WD_SMS_DAILY_CAP` 200、`WD_SMS_HOURLY_CAP` 40、`WD_CODE_IP_HOURLY` 20、`WD_PHONE_STALE_DAYS` 90、`WD_CAPTCHA` on、`WD_AI_USER_DAILY_WORDS` 80）有默认值，不写即生效。
2. 迁移 0018 是纯附加：Linux 上 `deploy/install.sh --no-restart` 后随下一次重启应用，或直接重启；Mac 上一次 `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`。启动时自动写 `backups/pre-migrate-17-to-18.db.gz`。先在 `VACUUM INTO` 副本上 `scripts/rehearse_migration.py` 演练。
3. 验证：`curl --noproxy '*' http://127.0.0.1:8000/api/health` 应含 `sms_enabled` / `email_enabled` / `captcha`；管理页概览出现短信额度卡片；`wd sms-probe` 成功。
4. 私测期间保持 `WD_REGISTRATION_MODE="invite"`：老用户不受影响，已有账号可在设置页绑定手机号；切到 `verified` 之前确认 `WD_AI_USER_DAILY_WORDS` 生效。

## 4 验收

（上线前补：pytest / vitest / tsc / lint / build / check_contract / smoke 的结果，迁移演练输出，评审结论。）

## 5 回滚

代码回退即可（`git checkout <上一版>` + 重启）：0018 只加列加表，老代码的 INSERT 都写明列名、不读新列新表；`login_codes` / `identities` 留着无害。回退后验证码登录与手机号绑定不可用，已用验证码建号的账号只能等再次升级后登录（它们没有密码）。AI 配额没有迁移：回退代码即关闭，`auth_throttle` 里的 `ai:user:*` 行一天后由小时 GC 清掉。

## 6 上线记录

（待填：时间、commit、迁移快照文件、健康检查、首个真实验证码登录。）
