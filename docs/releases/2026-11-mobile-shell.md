# 发布说明 · 2026-11 · 手机 App 壳（Capacitor，iOS / Android）与网站侧原生接入（无后端改动）

基线 `main @ 6407787`（P3b 已上线）；本次发布 = `mobile/` 下的 iOS 与 Android 壳工程，和网站侧的原生接入（`frontend/src/native/`）。手册：`docs/MOBILE_APP.md`（架构、构建、上架步骤）；前端契约：`docs/FRONTEND.md` §1 / §6.4 / §6.6 / §8。

## 1 变更概览

- **mobile/**：Capacitor 8.6.0 远程壳（WebView 加载线上站点，`server.url` = 后端 `WD_PUBLIC_URL`，后端零改动）。Android 与 iOS 原生工程、品牌图标与启动图、白色通知小图标、签名配置（密钥在仓库外）、版本号 yyyymmddNN、阿里云 Maven 镜像 init 脚本、离线 / 重试页模板（每次 sync 渲染进服务器地址）。两个构建档位：release 只接受 https；dev 允许家里局域网 http（`WD_APP_ALLOW_HTTP=1`），没有地址直接报错。
- **网站**：`isNative()` 为真时——每日提醒排成本机非精确的本地通知（`push_time` 按学习者时区换算到手机时钟，夏令时按目标时刻的偏移），会话已知时启动 / 恢复 / 设置变化时重排，只在主动退出登录时取消；通知权限只在手势里申请（推送开关，或装 App 前已开推送的账号看到的「允许通知」按钮）；发音走系统 TTS，缺英文语音时提示安装；安卓返回键；导出按钮隐藏；状态栏安全区。浏览器里全部是空操作，行为不变。
- **文案**：`zh.native.*`、`zh.settings.nativeReminderHint / reminderDenied / allowNotifications`、`zh.word.voiceMissing`（FRONTEND §8 同步）。

## 2 验收

- 前端：`tsc`、`npm run lint`（文案检查）、vitest 49 个文件 390 条（新增 `native/capacitor.test.ts`、`native/NativeBridge.test.tsx`、`hooks/useSpeech.native.test.ts`、`pages/SettingsPage.native.test.tsx`，以及 `SettingsPage.test.tsx` 的浏览器模式用例），主包 103 KB gzip（上限 200 KB）。
- Android：这台 Mac 上 `assembleDebug` / `assembleRelease` / `bundleRelease` 全部成功，`apksigner verify` 通过。
- 评审：`review-word-dance-mobile-shell`（5 视角 × 3 反驳者，80 个 agent）确认 22 条（去重 16 条）全部修掉，其中高危一条：通知插件默认请求精确闹钟，Android 14+ 会在每次启动 / 恢复时把用户弹进系统「闹钟和提醒」设置页——改为非精确闹钟（`isExactNotification: false`）并从清单里去掉该权限。验证轮 `verify-word-dance-mobile-fixes`（16 个验证者 + 3 个新视角，20 个 agent）确认 15 条修复、驳回 1 条文档说法（iOS 17 起 ATS 不再豁免 IP 地址的 http，dev 档位改为由钩子写入 `NSAllowsLocalNetworking`），另外 18 条新发现全部处理：被打断的朗读在 Android 上不会结束（网站侧自己结束）、`UNAVAILABLE` 与缺语音分开提示、权限请求失败仍保存设置、设置页权限行随前后台切换刷新、监听器只装一次、离线页模板不再打进包、`capacitor:copy:before` 钩子让直接 `npx cap sync` 也会渲染离线页和 ATS 例外、源地址用 URL 解析校验、iPhone-only、清单去掉 `SCHEDULE_EXACT_ALARM`、文档与 README 的若干过时句子。

## 3 上线步骤

1. `git pull` 后在 Mac 上构建前端快照、切换符号链接并重启服务（`StaticFiles` 启动时解析目录，只换链接会 404）。
2. 安装包放到快照的 `dl/` 下，手机在同一网络用浏览器打开 `http://<Mac 地址>:8000/dl/<文件名>.apk` 下载安装。
3. iOS 需要 Xcode 与开发者账号，见手册 §4.3 / §6.1。

## 4 回滚

网站侧：`git checkout 6407787` 重新构建前端快照并重启即可（壳里只是少了原生功能，变回普通网页）。App 不需要回滚：卸载即可。

## 5 上线记录

（上线后补。）
