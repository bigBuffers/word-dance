# 注册与登录改造 切片 1-B：家长账号与孩子子账号、家长门、孩子登录码、存量账号补充信息（迁移 0019，加列加表不停机）

> 设计：[`docs/AUTH_SIGNUP_DESIGN.md`](../AUTH_SIGNUP_DESIGN.md) §5.1「家长 + 孩子」、§5.2「切换与边界」「未成年人」「存量账号」、§5.5 行 1-B、§5.6 不变量 2 / 3 / 5；上一切片：[`2026-11-auth-signup-1a.md`](2026-11-auth-signup-1a.md)。业主 2026-11-10 确认 D1b、D3、D10、D12。
> 状态：**已上线**——`dbb6c1a` 于 2026-11-11 12:19 在 Mac 上生效（迁移 0019 启动时自动应用，快照 `backups/pre-migrate-18-to-19.db.gz`）。短信通道仍未开通（`.env` 未改）。**注意：家长功能实际上整体等着短信**——家长账号的两因子规则要求一个已验证的手机号，而手机号只能经短信验证码绑定（81 / 86 / 101 / 109），所以在 `WD_SMS_PROVIDER=off` 的机器上，建子账号（95）、切换（104）、孩子登录码（99）、独立（100 / 101）都会答 409 `guardian_factors_required`，认领（108）答 409 `sms_unconfigured`；页面会提示「服务器尚未开启短信」。短信开通（1-A 发布说明 §3.1）之后这些功能即刻可用，不需再上线。

## 1 起因

- 1-A 让成人和已满 14 岁的学生能用手机号 / 邮箱注册，但未满 14 岁的孩子还没有合规的建号路径（首次设置页只能把他们挡回去），老账号也还没有声明过身份。
- 设计定下的模型是「家长账号 + 孩子子账号」：孩子不需要手机号，账号由家长用自己的已验证手机号创建并随时管理；共用一台平板时一键切到孩子、切回要过家长门；孩子自己的平板用家长生成的一次性登录码进入；满 14 岁后由家长发起「独立」。依据 PIPL 第 31 条与《儿童个人信息网络保护规定》第 20 条（监护人终止使用时删除儿童信息）。

## 2 变更概览

| 领域 | 变更 |
|---|---|
| 数据库 | 迁移 `0019_family.sql`（纯附加，可 `--no-restart`）：新表 `family_codes`（孩子登录码与认领码，HMAC 哈希）；`sessions.guardian_gate_at`（家长门在该会话通过的时间，10 分钟有效）；`users.profile_prompted_at`（存量账号「补充信息」被跳过的时间，30 天后再提醒）。1-A 预留的 `account_kind` / `guardian_user_id` / `guardian_consent_at` / `guardian_pin_hash` / `sessions.actor_user_id` 本切片开始写入 |
| 家长账号 | 首次设置（`POST /api/account/profile`）新增「我是家长」；家长账号必须有第二因子（没有已验证邮箱时必须设密码）。两因子规则（已验证手机号 + 密码或已验证邮箱）在建孩子、切换、发登录码、独立、解绑手机、清空邮箱时校验，不满足 → 409 `guardian_factors_required` |
| 子账号 | `POST /api/guardian/children`：昵称 + 首次建号时设 6 位家长 PIN（可选同时给孩子一个简单的用户名 + 密码）；`age_band='u14'`、`guardian_consent_at`、声明 IP 留痕；每位家长最多 10 个。孩子账号不能改自己的昵称 / 邮箱 / 密码 / 手机号、不能注销（403 `guardian_required`），学习、设置、生词库、导出照常 |
| 家长门 | `POST /api/guardian/gate`（PIN / 密码 / 发到家长手机或邮箱的验证码三选一）→ 会话盖 10 分钟戳；「我的孩子」里的改动都要先过门；PIN 连错按登录锁定节奏（10 次锁 15 分钟起步）锁住 → 423；`PUT /api/guardian/pin` 设置 / 修改 PIN（首次设置也要先过门——用密码或验证码；否则拿着家长已登录平板的人就能先设一个 PIN 再开门） |
| 切换 | `POST /api/auth/switch/{child_id}` 把当前设备切成孩子的会话（家长这台设备的会话作废，其他设备不受影响，`sessions.actor_user_id` 记下家长）；`POST /api/auth/switch/back` 过家长门后切回；`GET /api/auth/me` 新增 `session.guardian` 供前端显示「切回家长」 |
| 孩子登录码 | `POST /api/guardian/children/{id}/login-code` 生成 8 位一次性码（10 分钟，每孩子每小时 5 次）；孩子设备在 `/child-login` 输入 → `POST /api/auth/child-login` → 90 天会话（每 IP 每小时 10 次失败 → 429；会话滑动续期不再缩短已有期限） |
| 管理孩子 | 改昵称 / 设用户名密码（`PATCH`）、注销（`DELETE`，级联）、退出所有设备、独立（`…/code` 给孩子自己的手机号发码（认领来的账号本就绑定的号码也可以） → `…/emancipate` 校验码 + 设新密码 → `guardian_user_id` 置空、`age_band='14plus'`，不可逆，写系统事件 `child_emancipated`；此后只能经「认领」重新加入家庭） |
| 家长注销 | `DELETE /api/account` 名下有孩子时 409 `has_children`（列出孩子）；传 `delete_children: true` 时已绑定自己手机号的孩子自动独立（数据保留），其余子账号随家长一并注销，写 `guardian_deleted` 事件 |
| 存量账号 | 已完成引导且未声明身份的账号登录后弹一次「补充信息」：我是家长 / 我是成人学习者 / 我是学生（已满 14 岁）→ `POST /api/account/declare`；「以后再说」→ `POST /api/account/declare/skip`（30 天后再提醒）；「这是孩子的账号」→ 输入家长手机号 → `POST /api/account/guardian/code` 发认领码 → `POST /api/account/guardian` 校验后挂到该家长名下（家长账号不存在则顺带创建，家长首次登录时补密码；号码的主人自称未满 18 的学生、或该手机号身份久未登录触发 1-A 的二次放号规则时拒绝，409 `guardian_minor` / `guardian_stale`）；选「孩子未满 14 岁」时，该账号自带的手机号 / 邮箱随认领一并解除（儿童规则页 §2「不收集儿童的手机号、邮箱」），选「已满 14 岁」则保留。管理员不会被认领为孩子 |
| 前端 | 新页 `/children`「我的孩子」（孩子卡片：进度、设备数、切换、登录码、管理、独立、删除；添加孩子；家长 PIN）、`/child-login`「孩子登录」；壳层「正在使用孩子的账号 · 切回家长」条；首次设置三选一身份；设置页「我的孩子」/「加入家庭」入口，孩子账号显示「由家长管理」说明；管理页用户表 家长 / 孩子 标签；儿童规则页补充机制说明 |
| 契约 | API.md §1 新增 `G` / `G+gate` 鉴权列与孩子账号限制清单，§1.1 五个错误码（`invalid_pin`、`guardian_required`、`guardian_gate_required`、`guardian_factors_required`、`has_children`），§2 / §3.2 端点 94–111，§9 `User.account_kind / is_child / needs_profile_prompt`、`SessionInfo`、`ChildAccount` 等 DTO；无新增环境变量 |

本切片有意推迟：加入码（由「认领为子账号」流程替代，班级 / 老师留第三步）；孩子建号时选年级（孩子首次进入时在引导第 1 步选）；家庭事件通知家长。

## 3 启用步骤

无新增配置。代码上线后，家长功能要等 1-A 的阿里云短信通道开通（见 1-A 发布说明 §3.1）：家长先用手机号验证码注册 / 绑定手机号并设密码，「我的孩子」才会开放建号、切换、登录码和独立；在此之前只有存量账号的「补充信息」声明（110 / 111）和家长 PIN（103）能用。

Mac 上线：`git pull` 后按 1-A 的步骤构建前端快照并 `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`；启动时自动应用 0019 并写 `backups/pre-migrate-18-to-19.db.gz`。先在 `VACUUM INTO` 副本上跑 `scripts/rehearse_migration.py`（新增 `check_0019`，空库 29 表）。

## 4 验收

- 后端：`pytest` 全量 **2544 passed / 3 skipped / 1 deselected**（4 分 54 秒；`test_deploy_files.py` 在 Mac 上照例不跑）。新增 `test_family.py`、`test_db_0019.py`、`test_guardian.py`、`test_auth_family.py`、`test_account_family.py`，0019 把 28 → 29 张表的各处固定断言一并更新。
- 契约：`make check-contract` OK（只剩 1-A 之前就有的 9 条可空性 note）；`test_docs_contract.py` 13 passed（API.md §9 == `types.ts`，FRONTEND §8 == `zh.ts`）；`test_api_schemas.py` 固定端点 1–111。
- 前端：`typecheck` 通过；vitest **58 个文件 / 499 个测试**；copy check OK；构建 `index` 346 KB（gzip 114 KB），`ChildrenPage` 13.8 KB 独立分包。
- `make smoke`：29 步通过（8010 端口的临时实例）。
- 迁移演练：`scripts/rehearse_migration.py` 在线上库的只读副本（`VACUUM INTO`，schema 18，2 个用户）上 **102 项检查全部通过**——0019 追加列 / 新表 / 3 个索引、CHECK 与外键、行数不变、二次运行无动作、空库 29 表。
- 对抗评审（7 个视角 + 逐条核实，20 个代理）：9 条成立、4 条驳回、29 条低风险未核实。成立项全部修复：① 首次设置家长 PIN 不过门——拿着家长已登录平板的人可先设 PIN 再开门（高；103 现在一律过门）；② 认领（109）事务内未复核本账号状态，并发时可能出现「孩子名下有孩子」（锁内重读 + 条件更新）；③ 前端弹层在等家长门时丢失 busy 态、可能重复提交（门的 Promise 现在等动作真正完成才结算）；④ 无短信时家长功能整体不可用而页面无提示、发布说明写反（页面加提示，说明改正，见顶部）；⑤ 认领会把自称已满 14 岁的未成年人变成家长（409 `guardian_minor`）；⑥ 认领忽略 1-A 的二次放号规则（409 `guardian_stale`）；⑦ 管理员停用家长时切换出去的孩子会话仍存活（一并删除）；⑧ 认领到「首次设置未完成」的验证码账号会被强行写成 adult（只改 kind，留给首次设置页）。低风险项中顺手修了：孩子已持有号码的独立路径、文档若干处（`invalid_code` / `account_locked` 行、`needs_profile_prompt` 说明、DESIGN §10 隐私行、FRONTEND §4）、前端不再拿设备时钟判断家长门、家长完成首次设置后直达「我的孩子」、切回弹窗移出 live region。未处理的低风险项（原文存于本次会话的 `review_1b.json`）：家长改密码不踢切换中的孩子会话（设计如此，98 是专用工具）、106 会作废家长自己待用的重认证码、家庭内共享私有词在家长注销时的归属、`applyAuth` 后续 `/me` 失败时沿用旧计数等。

## 5 回滚

代码回退即可：0019 只加列加表，老代码不读 `family_codes` / `guardian_gate_at` / `profile_prompted_at`；已建的子账号在老代码下是普通的无密码学习者账号（`guardian_user_id` 非空但老代码不看它），没有登录方式，等再次升级后由家长切换进入。

## 6 上线记录

- 2026-11-11 12:18:59 按 1-A 的步骤上线 `dbb6c1a`：前端构建到 `frontend-releases/dbb6c1a`（APK 三个文件照抄进 `dl/`），软链原子切换，`launchctl kickstart -k` 重启；2 秒后 `/api/health` ok。
- 启动日志：`applied migration 0019_family`；schema 18 → 19；`backups/pre-migrate-18-to-19.db.gz`（2.6 MB）已写；`sign-in channels: sms off, mail off, captcha on, registration invite`（`.env` 未改）；AI 仍为 `split`。
- 上线后检查：`GET /api/guardian/children` 无会话 → 401；`POST /api/auth/child-login` 假码 → 400 `invalid_code`（`attempts_left: 0`）；`POST /api/auth/switch/back` 无会话 → 401；`/api/demo` 200；三个法律页 200（儿童规则页不再写「尚未上线」）；新包里含「我的孩子」文案；`family_codes` 表与 `sessions.guardian_gate_at` / `users.profile_prompted_at` 列就位；`wd check` 全 ok。
- 线上库此时 2 个用户，均未声明身份：两人下次登录会看到一次「补充信息」（可跳过，30 天后再提醒）。短信未开通，所以「我是家长」在当前机器上只能走到「家长账号还缺：绑定手机号」的提示（见顶部说明）。
- 回滚（仅在业主明确要求时）：`git checkout eac30ac`，按同样步骤重建前端快照并重启；数据库不必回退（0019 只加列加表）。
