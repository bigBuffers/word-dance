# Verification: slice "android" (word-Dance quick-deploy + mobile research)

Verified 2026-11-04 against git main @ 9ab13a5 by an adversarial re-check of every claim in `facts/android.md`. Every URL below was fetched on 2026-11-04 unless marked "(search snippet)"; quotes are verbatim from the fetched page. Prices carry currency and the page's own update date. Sources older than 6 months are flagged "[stale]". No repo file, data dir or port was touched; only this report was written.

Verdict summary: F1 confirmed · F4 corrected · F3 confirmed (cap resolved: 50) · F5 corrected · F7 confirmed · F9 confirmed · F11 confirmed · F12 corrected (effort) · F13 confirmed · F14 corrected.

---

## F1 — enforcement since 2026-09-30 only in BR/ID/SG/TH, only participating stores, certified Android 7+; sideloading untouched until 2027

**Verdict: confirmed** (one wording inconsistency inside Google's own docs noted below).

What I read:
- developer.android.com/developer-verification (landing page, timeline table, verbatim): "August 2026 | Developer APIs, limited distribution accounts, and power user advanced flow launch." / "September 30, 2026 | Protections begin for all users who install apps from participating stores in Brazil, Indonesia, Singapore, and Thailand on certified devices running Android 7+." / "2027 and beyond | Verification capability will be expanded globally for all apps on certified Android devices in 2027."
- developer.android.com/developer-verification/guides/faq: "What happens starting September 30, 2026 if I sideload my app or distribute it through another store that isn't included in the list of participating stores? The September 30, 2026 deadline only applies to the specific participating stores. If you distribute your app through other stores, or if users sideload your app directly, these new verification requirements won't apply to your app yet. … *Last updated: July 15, 2026*". Also: "Enforcement starting September 30, 2026, is limited only to the specific stores mentioned in the blog post … *Last updated: June 18, 2026*".
- android-developers.googleblog.com/2026/06/android-developer-verification.html ("Android developer verification: Building a safer ecosystem together", June 18, 2026 — the digest's URL slug was wrong, this is the live one): participating stores Google Play, HONOR App Market, OPPO App Market, Galaxy Store, Palm Store, V-Appstore, GetApps; "a new system service that will be automatically installed on most Android devices".
- androidauthority.com/android-sideloading-developer-verification-first-wave-rollout-3717921/ ("Oct 1, 2026 — 8:21 AM ET"): "Apps installed through participating stores must be registered to a verified developer" on "certified devices running Android 7 or newer"; "no changes to sideloading outside of the listed app stores is happening today, even in the four impacted countries."
- Rollout status corroboration: xda-developers.com (Aug 19, 2026) — advanced flow "is rolling out gradually", setting "Allow Apps From Unverified Developers", 24-hour wait; malaysianwireless.com (2026-10-30) reports the four-country rollout under way.

Inconsistency to carry forward: Google's user-facing help page support.google.com/android/answer/17065026 ("Learn about Android developer verification") says "This initiative applies to certified Android devices running Android 8 and up.", while the developer FAQ (March 23, 2026) and timeline say Android 7+. Immaterial for this circle (all phones are far newer), but do not quote "Android 7" as settled.

---

## F4 — verifier "delivered through Google Play services" on certified devices; default-state mainland phones unaffected; "no Google statement about China exists"

**Verdict: corrected.** Mechanism confirmed and strengthened; the sub-claim "no Google statement exists" is wrong in substance — Google publishes an exemption that covers GMS-less devices and GMS-unsupported regions (it does not name China).

What I read:
- FAQ (same page as F1): "What Android versions will the developer verification requirements be enforced on? It will apply to all certified Android devices running Android 7 or higher. These updates are delivered through Google Play services to help maintain consistent security across the ecosystem. *Last updated: March 23, 2026*". New item: "the Android developer verification checks won't run on certified Android devices physically located in comprehensively sanctioned countries. Any app can be installed by a user in a country where verification checks are not run. *Last updated: Sept 30, 2026*" (shows per-device-location gating exists).
- support.google.com/android/answer/17065026 (Android Help, no date shown): "Requirements apply only to Certified Android devices. Android Open Source Project (AOSP) and non-certified devices are exempt from this requirement. Additionally, this requirement does not apply in regions where Google Mobile Services are unsupported or in territories subject to applicable trade sanctions." and "To support this initiative, a Google system service called Android Developer Verifier (package name: `com.google.android.verifier`) is installed on your device."
- androidauthority.com/android-developer-verifier-app-rollout-3689106/ ("Jul 20, 2026"): the verifier app is "automatically installed and updated through Google System Updates"; described as a "Google system service that verifies whether an app being sideloaded/installed is associated with a 'verified developer account'". (Google System Updates ship through Play on GMS devices — so GMS-less ROMs never receive the verifier.)
- support.google.com/googleplay/answer/7165974: certified devices "Include proprietary apps under license from Google" and "Have passed Android compatibility testing"; "Google apps on devices that aren't Play Protect certified aren't licensed and aren't real Google apps." No China mention.
- consumerrights.wiki/w/Android_Developer_Verification (last edited September 22, 2026): affected "Devices with Google Play Store", "Devices with Google Mobile Services (GMS)", "The vast majority of Android devices sold outside of China"; "Custom ROMs without Google services and non-certified devices are not affected by these restrictions".
- sunsetbrowser.app/blog/google-play-services-china-android-2026-cn (dated 2026-10-18): "ColorOS 6.0 及以上，Google 服务框架为内置、无法卸载"; Honor "设置 > 用户和账户 > Google Play 服务" (MagicOS 8.0–10.0); "Mate 30 系列及后续机型没有预装 GMS 与 Google 应用"; "只有通过 Play 保护机制认证的设备，才有资格搭载 Google 应用"; play.google.com "13 次全部被封锁" (GreatFire, last test 2026-10-11).
- cyrusyip.org/zh-cn/posts/2023/05/05/google-play-miui/ ("2023年5月5日（修改于2024年10月12日）") [stale, >6 months]: HyperOS path "设置 -> 更多设置 -> 帐号与同步 -> 谷歌基础服务"; supported-list Xiaomi/Redmi phones "已预装谷歌服务".

Correction to record: replace "no Google statement about China exists" with "Google names no country, but its Android Help page exempts AOSP/non-certified devices and 'regions where Google Mobile Services are unsupported'; the enforcement component is a discrete Play-delivered app (com.google.android.verifier)". The practical conclusion (default-state domestic phones and all Huawei phones are outside the regime) stands and is now backed by a Google sentence rather than only inference. Still open: whether a mainland-sold, certified Xiaomi/OPPO unit with Google services switched on counts as "region where GMS is unsupported" — Google does not say.

---

## F3 — free limited-distribution account (no government ID), small set of authorised devices; 50 per guide vs 20 per June FAQ/blog

**Verdict: confirmed**, and the 20-vs-50 question is resolved: 50 is current.

What I read:
- developer.android.com/developer-verification/guides/limited-distribution: "Share apps with up to 50 devices that end-users have explicitly authorized."; "This account is free."; "a secure handshake process involving QR codes or links, user consent on the device, and registration using the Android Developer Console"; requirements "A Google Account … 2-Step verification … Google payments profile … Contact email address"; "you don't need to provide a government ID".
- support.google.com/android-developer-console/answer/17131204 ("Limited distribution accounts in Android Developer Console" — the operational help article, not read by the original slice): "You can have up to 50 authorized devices at any one time."; steps "provide a device friendly name" → "use the physical device to generate a unique authorization code" (QR scan or shared link) → "enter the authorization code into Android Developer Console, and select Add device"; removal: "This action cannot be undone; to re-enable installs or updates, you would need to authorize the device again."; "Any devices not authorized won't be able to install or receive updates from apps that use your registered package names."
- Stale "20" copies, all June 2026: FAQ "This lets you share apps with up to 20 specific devices for testing and personal use at no cost and without ID verification. *Last updated: June 18, 2026*"; landing page "share apps with up to 20 devices without a government-issued ID or registration fee"; June 18 blog "lets you share your apps to up to 20 devices without a government-issued ID or a fee". Third-party explainers from June 2026 (testerscommunity.com, June 20, 2026) also say 20 and cite nothing newer.

Correction to record: treat the cap as 50 (guide + console help article, both current); the 20 figure is pre-launch copy that was never updated. Note for the plan: the authorising device must itself generate the code (so the enrolment presumably needs the verifier/Play stack on the phone — undocumented), and un-authorising a device is irreversible.

---

## F5 — HarmonyOS NEXT (5: 2024-11-26, 6: 2025-11-25/Mate 80, 7: 2026-09-07/Mate XT 2) has no AOSP layer and cannot install APKs; 4.x (4.3 on 2024-11-26) can; MagicOS 11 = Android 17, installs APKs

**Verdict: corrected.** All dates and the architecture statement check out; "cannot install APKs" is true of the OS but misleading for the user-level decision because Huawei's AppGallery ships 卓易通, an Android-app container that installs local APKs (with restrictions) on HarmonyOS 5/6/7.

What I read:
- en.wikipedia.org/wiki/HarmonyOS_version_history: 4.2 "April 26, 2024" (Pura 70); 4.3 "November 26, 2024" (Mate 70 series, Mate X6 non-Pioneer SKUs); HarmonyOS 5 general release "November 26, 2024" for Mate 70 / Mate X6 / MatePad Pro 13.2; 5.1 "June 11, 2025" (Pura 80); HarmonyOS 6 announced "June 20, 2025", public release "November 25, 2025" with Mate 80, "Update ArkWeb to Chromium 132 LTS"; HarmonyOS 7 "September 7, 2026" with "Mate XT 2".
- en.wikipedia.org/wiki/HarmonyOS_5: "the Next version … does not include the Android AOSP core and is incompatible with Android applications"; "The kernel of HarmonyOS NEXT no longer includes the compatibility layer of AOSP framework with Android libraries from EMUI in the user space and cannot run Android apk apps natively."
- Corroboration beyond Wikipedia: gizmochina.com (2026-08-25) "Huawei Mate XT 2 launch set for September 7"; androidheadlines.com (Sept 2026) HarmonyOS 7 rollout; ithome.com/0/900/135.htm and pandaily (2025-11-25) HarmonyOS 6 + Mate 80 launch; gsmarena.com "Honor MagicOS 11 debuts" — "On 15 September 2026, Honor announced MagicOS 11, based on Android 17"; en.wikipedia.org/wiki/Magic_OS: "MagicOS is an Android-based mobile operating system developed by Honor"; "The Honor Magic9 series, which went on sale in China on 28 September 2026, was the first smartphone lineup shipped with MagicOS 11"; package management "HONOR App Market and APK files".
- 卓易通 (the omission): info.congci.com article (2025-01-11): made by "华为第三方合作伙伴上海卓易科技", found by searching "卓易通" in the "华为官方应用市场", "该工具底层基于华为isulad容器"; "已适配鸿蒙的知名App应用，则因为性能考量，不予在该模拟器中安装运行". yeyulingfeng.com/81869.html (updated 2025-01-09): needs "鸿蒙系统已更新到5.0.0.113及以上版本"; when an app is not in 卓易通's catalogue, transfer the APK and open it through 卓易通's "文件互传"/"文件管理" to install; requires leaving 纯净模式. yeyulingfeng.com/71918.html (2024-12-10) [stale]: "This method has whitelist restrictions—not all APKs can be installed" (Futu/Binance installed; Teams/APKPure failed). developer.huawei.com/consumer/cn/blog/topic/03203162361635369 (Huawei developer community, 2026-01-07): manual path "打开手机的文件管理器，找到刚传输过来的APK文件，直接点击打开". ithome.com/0/971/261.htm (2026-07-01): "卓易通今日宣布全面支持华为鸿蒙 HarmonyOS 7.0 系统"; m.ithome.com/html/963603.htm (2026-06-12): "华为鸿蒙 HarmonyOS 7 系统上的卓易通 App 已升级安卓 16".

Correction to record: "HarmonyOS NEXT cannot run APKs natively; however 卓易通 (AppGallery, Droi) provides an Android 16 container on HarmonyOS 5–7 that can install side-loaded APKs subject to its own allow/deny rules" — so the table's class-D cell "Impossible" should read "possible only inside 卓易通, untested (notifications/background/TTS inside the container unknown)". Honor/MagicOS and HarmonyOS 4.x statements stand.

---

## F7 — Huawei Browser on NEXT: only 添加至桌面 shortcuts (max 10), no documented manifest/standalone/PWA; ArkWeb implements Web Speech API (SpeechSynthesis disabled only in 坚盾守护 mode)

**Verdict: confirmed** (medium; the "ArkWeb implements SpeechSynthesis" part is an inference from the secure-shield doc, not a positive Huawei statement).

What I read:
- consumer.huawei.com/cn/support/content/zh-cn16032141/: "适用版本： HarmonyOS 5.0及以上"; three entry points (page menu ∷ → 添加至桌面; long-press bookmark; long-press history); "华为浏览器中添加至桌面的快捷方式上限为10个"; the page contains none of PWA / manifest / 全屏 / 快应用 / 元服务 / 独立窗口.
- geekpark.net/news/345787 (2025/02/10) [stale]: requires "HarmonyOS NEXT 5.0.0.123 SP19" and Huawei Browser "5.0.8.300"; "直接在桌面一键点击即可直达此网页"; no PWA/manifest/快应用/元服务/全屏/独立窗口 mention.
- developer.huawei.com/consumer/cn/doc/harmonyos-guides-V5/web-secure-shield-mode-V5 (the real Huawei doc; "HarmonyOS 5.0.0 Release", updated 2025-03-17) [stale]: "禁止使用Web Speech API语音识别能力。" and the troubleshooting hint to "排查前端代码是否存在SpeechRecognition（语言识别）、SpeechSynthesis（语音合成）等接口调用". The un-versioned URL the digest cited only returns a navigation shell. Mirror cnblogs.com/samex/p/18474396 (2024-10-18) [stale]: "禁用Web speech api： Web speech api允许开发者使用语音识别和语音合成功能。Web speech api可能被恶意开发者滥用…".
- openpwa.net was not re-fetched; bbs.itying.com/topic/67ffe64d687c4e0048a99db6 (forum, not vendor): one user claims ArkWeb "支持最新的Web标准，包括Service Worker、Web App Manifest等PWA核心技术", another reports on a Huawei tablet "无法添加到桌面，尝试过多个浏览器，多个支持pwa的网页均无法安装到桌面".
- github.com/ShwStone/AnyPWA (README): "面向 HarmonyOS PC/2-in-1 的原生网页应用管理器", "AnyPWA 已在华为应用市场正式上架", supports Web App Manifest (name/start_url/scope/display/icons) and pinned desktop shortcuts — PC/2-in-1 only, not phones.

Nothing to correct; keep the device test in the plan. The official doc's explicit prohibition sentence names speech recognition; synthesis is mentioned only in the troubleshooting hint, so "SpeechSynthesis works outside secure mode" remains untested.

---

## F9 — only Chrome-with-GMS and Samsung Internet mint WebAPKs; GMS-less Chrome, Firefox, Edge, Opera, Brave add browser-badged shortcuts

**Verdict: confirmed.**

What I read:
- developer.mozilla.org/…/Making_PWAs_installable ("last modified on Oct 6, 2026"): "On Android, the only browsers that install PWAs as WebAPKs are: Chrome on devices with Google Mobile Services (GMS), and Samsung Internet on Samsung devices. … Firefox, Edge, Opera, and other browsers including Chrome on devices where GMS is not present, instead add a browser-badged home-screen shortcut that opens the site in the browser."; "While not a requirement for a PWA to be installable, many PWAs use service workers".
- web.dev/learn/pwa/installation: "A WebAPK is an Android package (APK) created by a trusted provider of the user's device, typically in the cloud, on a WebAPK minting server."; "Because Firefox, Microsoft Edge, Opera, Brave, and Samsung Internet (on non-Samsung devices) don't have minting servers they trust, they'll create shortcuts."; "Google Chrome will too if the minting service is unavailable or your PWA doesn't meet installation requirements".
- Primary code: chromium.googlesource.com/…/chrome/browser/webapps/WebApkInstaller.java — the install delegate field is documented "Talks to Google Play to install WebAPKs."; when `mInstallDelegate == null` the installer returns `WebApkInstallResult.NO_INSTALLER` (metric `FAILED_NO_DELEGATE`); the delegate comes from `AppHooks.get().getGooglePlayWebApkInstallDelegate()`. (ChromeWebApkHost.java, also checked, has no Play logic.)

---

## F11 — Web Push not a mainland Android reminder path (Chrome throws "Google Play Services missing"; Firefox push = Firebase; Edge Android invalid endpoints since Oct 30 2025 builds; no domestic browser documents Web Push)

**Verdict: confirmed** (two citation details corrected).

What I read:
- chromium.googlesource.com/…/gcm_driver/GoogleCloudMessagingV2.java (decoded): `private static final String GOOGLE_PLAY_SERVICES_PACKAGE = "com.google.android.gms";` / `private static final String ACTION_C2DM_REGISTER = "com.google.android.c2dm.intent.REGISTER";` / `if (!PackageUtils.isPackageInstalled(GOOGLE_PLAY_SERVICES_PACKAGE)) { throw new IOException("Google Play Services missing"); }`.
- raw.githubusercontent.com/mozilla-firefox/firefox/main/mobile/android/android-components/components/lib/push-firebase/README.md: implementation "uses Firebase Cloud Messaging. It can be used by Android devices that are supported by Google Play Services." (the digest's "supposed [sic]" is a misquote of "supported").
- learn.microsoft.com/en-us/answers/questions/5781524/… (asked 2026-02-19): Edge/Edge Beta on Android return `https://permanently-removed.invalid/fcm/send/…` instead of `https://fcm.googleapis.com/fcm/send/…`; build timeline in the thread: May 29 / Aug 28 / Sep 4 builds worked, "September 28 onwards" and "October 30 onwards" fail to subscribe (script errors), "November 25" and current builds mint the invalid URL; no accepted answer and no Microsoft response as of the latest comments (August 2026). (techcommunity thread 1774677 is a different, 2020–21 bug.)
- learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/how-to/push (updated 2026-09-02): read in full — it does NOT contain the "Android's WebView … doesn't support the Push API" sentence the digest attributed to it; that wording comes from pushpad.xyz's blog ("The Android WebView does not support the Push API yet", search snippet). The fact is still right (Chromium WebView lacks Push API) but cite Chromium, not Microsoft.
- F-Droid "5 years of UnifiedPush" and openpwa.net were not re-fetched (unchanged relevance).

Corrections: (1) Edge breakage dates: failing since the Sept 28, 2025 builds, invalid endpoint observed from the Nov 25 build — "since Oct 30 2025 builds" is approximate. (2) Fix the Edge-docs citation as above.

---

## F12 — reminders already work on GMS-less phones via serverchan/wecom/feishu formats (Server酱 free 5/day, 50/min; ¥8/月 for 1000/day); ntfy format ≈ 0.5 day

**Verdict: corrected** (repo facts and service limits confirmed; the 0.5-day estimate omits a schema CHECK constraint that forces a table-rebuild migration — closer to 1 day).

What I ran/read:
- `sed -n '1,60p;215,300p;335,360p' backend/wd/delivery/webhook.py` @ 9ab13a5: docstring lines 5–8 list the five shapes; line 37 `FORMATS: tuple[str, ...] = ("generic", "wecom", "feishu", "serverchan", "bark")`; `safe_post` starts line 224 (https/SSRF pin, JSON body, `follow_redirects=False`, `timeout=timeout_s` = 10 s); `build_payload` lines 267–291 (`if fmt == "serverchan": return {"title": title, "desp": body}`); `send_test_webhook` lines 342–352.
- `sed -n '150,175p' docs/API.md`: line 160 (endpoint 15) "`webhook_url` https + public host (SSRF host check) required when `webhook_enabled`"; line 162 (endpoint 17) "sends the configured format with a test text synchronously (10 s timeout) … 429 (1 per 10 min)".
- sct.ftqq.com/docs/getting-started/faq/ (page "Updated 2026-07-28"): "每天最多 5 条" (free), "每分钟最多发送 50 条", paid "每天最多可发 1000 条", "8 元/1 个月", "39 元/12 个月", "180 元/60 个月", "企业版（可开票）720 元/60 个月", with the caveat "以上为当前促销价，最终以订阅页面实际价格为准" — i.e. CNY ¥8/month promotional price as of 2026-07-28.
- sct.ftqq.com/docs/getting-started/channels/ (updated July 28, 2026): channels 微信服务号, 微信测试号, 企业微信应用消息, 企业微信群机器人, 钉钉群机器人, 飞书群机器人, Bark iOS, PushDeer, 官方 Android 客户端, 自定义 Webhook; Android client push "无需保活" on 小米、华为、荣耀、vivo、OPPO、iQOO、Realme、OnePlus、魅族.
- docs.ntfy.sh/subscribe/phone/: "The F-Droid build does not include Firebase, all subscriptions use instant delivery by default"; instant delivery works "even when your phone is in doze mode" and "is achieved with a foreground service"; "The ntfy Android app uses Firebase only for the main host ntfy.sh, and only in the Google Play flavor of the app." docs.ntfy.sh/publish/: `curl -d "Backup successful 😀" ntfy.sh/mytopic`; JSON `{"topic","message","title","click"}` must be POSTed to the root URL, not the topic URL.
- Effort check: `grep -rn webhook_format|WebhookFormat` — the format enum lives in 9 places: `backend/wd/migrations/0001_init.sql:156` `CHECK (webhook_format IN ('generic','wecom','feishu','serverchan','bark'))` (mirrored in `docs/SCHEMA.sql:156`), `backend/wd/schemas.py:37` Literal, `backend/wd/delivery/webhook.py:37`, `frontend/src/api/types.ts:17`, `frontend/src/i18n/zh.ts:77`, `frontend/src/pages/SettingsPage.tsx:27`, `docs/API.md:251`, `docs/DESIGN.md:325,425`, `docs/FRONTEND.md:278`, plus tests (`backend/tests/integration/test_delivery.py:254` parametrised over `webhook.FORMATS`; `test_settings.py:115` rejects unknown formats). `backend/wd/db.py` (run_migrations comment) states: "SQLite's table-rebuild recipe (CREATE new → INSERT … SELECT → DROP old → RENAME) is the only way to change a CHECK list" — so a new `ntfy` value needs migration 0010 rebuilding `user_settings` (existing migrations 0008/0009 are index/data only; no precedent to copy).

Correction: the webhook/Server酱/ntfy facts hold; budget ~1 day (rebuild migration + schema docs + enum in 8 files + tests), not 0.5, for an `ntfy` format. Reachability of sct.ftqq.com / ntfy.sh from the future host remains untested.

---

## F13 — Android System WebView exposes no speechSynthesis (undefined on WebView Chromium 138, July 2026); Chrome bridges to android.speech.tts; WebView shell needs native TTS; English voices on domestic engines untested

**Verdict: confirmed** (Chromium issue statuses unverifiable behind the tracker's login wall; titles confirmed).

What I read:
- chromium.googlesource.com/…/content/browser/TtsPlatformImpl.java (decoded): "This class is the Java counterpart to the C++ TtsPlatformImplAndroid class. It implements the Android-native text-to-speech code to support the web speech synthesis API."; imports `android.speech.tts.TextToSpeech`; voices enumerated from `Locale.getAvailableLocales()` filtered by `mTextToSpeech.isLanguageAvailable(locale)`.
- community.xibo.org.uk/t/android-player-speechsynthesis-web-speech-api-unavailable-in-webview-chromium-138/38219 (July 18, 2026): WebView "Chrome/138.0.7204.179"; `typeof window.speechSynthesis` → "undefined", `typeof window.SpeechSynthesisUtterance` → "undefined"; "the same webpage works correctly in Google Chrome (Android, Windows)"; thread auto-closed after 91 days with no staff answer.
- issues.chromium.org/issues/40417848 and /40468168: pages require sign-in; titles via search results: "Support for Web Speech API in Android WebView [40417848]" and "SpeechSynthesisUtterance not supported in Android WebView [40468168]" — status/open-closed not verifiable.
- Repo: `frontend/src/hooks/useSpeech.ts` lines 11–13 `speechSupported()` checks `'speechSynthesis' in window && typeof window.SpeechSynthesisUtterance === 'function'`; lines 22–26 `pickVoice` = exact lang (preferring Google/Microsoft/Samantha/Daniel) → any `en*` voice → undefined; `SpeakButton.tsx` header comment confirms the disabled-with-tooltip behaviour.

No correction. Domestic TTS engine English-voice availability remains untested (not verifiable from the desk).

---

## F14 — every major store needs APP备案号 + 软著/电子版权; Xiaomi accepts individuals; OPPO individuals may publish only 快应用/主题 etc.; APK link is the realistic route

**Verdict: corrected.** The 备案 rule and Xiaomi's material list are confirmed; the per-store individual-developer facts are out of date in three places (Xiaomi closed, OPPO opening, vivo opening), and two citations carry wrong dates. The conclusion (APK link for ≤ 10 friends) still holds — more strongly.

What I read:
- ithome.com/0/753/548.htm (article date "2024/3/4", not 2024-03-16) [stale]: "今年 4 月 1 日前，存量移动互联网应用程序（含 App、小程序、快应用等）需履行备案手续"; "逾期未履行备案程序的 App 将依法依规采取下架、关停、限制更新等处理措施"; "网络接入服务提供者、应用分发平台、智能终端生产企业不得为未履行备案手续的 App 提供网络接入、分发、预置等服务".
- dev.mi.com/xiaomihyperos/documentation/detail?pId=1322 (last updated "2025-09-02 12:41:00") [stale]: requires "《计算机软件著作权证书》（或《APP电子版权认证证书》）", "有效ICP证明" (filing entity must match the developer's enterprise), "按相关规定履行APP备案手续", and "应用内需在显著位置展示APP备案编号，并支持备案编号可点击跳转至备案系统"; the page is written for enterprise submitters.
- dev.mi.com/docs/appsmarket/distribution/account_register/ (no date): 个人开发者 = "没有在工商部门注册备案，仅是个人身份或者小团队身份进行应用开发的开发者"; "本人手持身份证正面照"; "1-3个工作日内完成开发者身份审核" — this describes the account, not store eligibility.
- Xiaomi store closure (the digest missed it): dev.mi.com/distribute/doc/details?pId=1259 "应用商店个人开发者升级公告" (JS-rendered; text via search snippet, updated 2024年10月18日): "小米应用商店即日起暂停收录个人开发者账号发布的APP，针对已在架APP，需在6月30日前，完成开发者身份类型的变更（个人开发者转企业开发者）。6月30日后，对个人开发者旗下的应用，将依照《应用发布协议》采取相关措施。" Corroborated by landian.news/archives/107285.html ("小米应用商店已经不再支持个人工商户身份进行注册认证", Dec 2024) and dev.mi.com pId=1354 (应用商店暂不收录类应用 lists individual-developer apps, search snippet). [stale sources, but no reversal found through 2026-11-04]
- OPPO: open.oppomobile.com/bbs/forum.php?…tid=1745 is dated June 15, 2020 (updated November 23, 2020) [stale]: individuals "快应用、主题、壁纸、动态壁纸、视频铃声、铃声、锁屏杂志、短视频小视频", enterprises "Android应用游戏，快应用，…". Newer: zhidx.com/p/508945.html (2025/10/15, ODC25): "平台首次向个人开发者全面开放应用上传权限"; "相关能力于2025年12月底正式对外开放，平台将以'邀请制'形式定向邀约个人开发者进行合作，并在后续陆续扩大开放规模。" No OPPO open-platform page confirming the post-December status was found — treat as "announced, invite-only, status unverified".
- vivo: news.qq.com/rain/a/20260916A0710U00 (2026-09-16): vivo opened an 个人开发者通道 — "个人开发者通道只需要个人实名认证"; "官方将有序开放 AI 应用、蓝河应用、IoT 应用" — ordinary Android APK apps are not mentioned. Earlier policy (individuals cannot publish apps) only in secondary CSDN posts; no vivo doc fetched.
- Huawei: developer.huawei.com/consumer/cn/doc/app/80301 returns a navigation shell; the "非必选资质" wording is confirmed only by search snippets — unverifiable beyond that.

Corrections to record: (a) "Xiaomi accepts individual developers" → Xiaomi 应用商店 has refused apps from individual accounts since 2024-10-18 (individual→enterprise conversion deadline 6月30日 [2025]); (b) "OPPO individual accounts may publish only 快应用/主题…" is the 2020 rule; OPPO announced invite-only individual app publishing from end-Dec 2025; (c) vivo opened a real-name individual channel in Sept 2026 limited (so far) to AI/蓝河/IoT apps; (d) ithome article date is 2024-03-04. Net effect on the plan: unchanged — a store listing for an individual remains weeks of 备案/软著 work plus store-specific gates, and the APK link is the realistic route.

---

## Omissions / new findings

1. **卓易通 makes "no APK on HarmonyOS NEXT" an overstatement.** Huawei's AppGallery distributes 卓易通 (上海卓易科技), an Android container ("底层基于华为isulad容器", congci 2025-01-11) that installs local APKs via its 文件管理/文件互传 (yeyulingfeng updated 2025-01-09; Huawei developer-community post 2026-01-07), excludes apps already adapted to HarmonyOS, reportedly applies a whitelist (2024-12 reports), was upgraded to an Android 16 base on HarmonyOS 7 (IT之家 2026-06-12) and officially supports HarmonyOS 7.0 (IT之家 2026-07-01). A Capacitor APK might therefore reach class-D friends — but notifications, background alarms and TTS inside the container are untested; add it to the device-test matrix rather than the "impossible" cell.
2. **Google does publish a GMS-less exemption and a conflicting Android floor.** support.google.com/android/answer/17065026: "Android Open Source Project (AOSP) and non-certified devices are exempt from this requirement. Additionally, this requirement does not apply in regions where Google Mobile Services are unsupported or in territories subject to applicable trade sanctions." The same page says "certified Android devices running Android 8 and up" while the developer FAQ/timeline say Android 7+. Cite the Help page for F4 and stop saying "no Google statement exists".
3. **The enforcement component is a discrete Play-delivered app, and the limited-distribution handshake needs the target phone to generate a code.** Android Developer Verifier = `com.google.android.verifier`, "automatically installed and updated through Google System Updates" (Android Authority, 2026-07-20; Google Help page). support.google.com/android-developer-console/answer/17131204: "use the physical device to generate a unique authorization code" (QR/link), "up to 50 authorized devices at any one time", and removal "cannot be undone". Implication: GMS-less friends cannot be enrolled and do not need to be; enrol only the GMS-phone friends, and do not churn device slots.
4. **Store policy has moved since the digest's sources (2020–2024).** Xiaomi stopped listing individual-developer apps on 2024-10-18 (notice pId=1259) and reportedly also refuses 个体工商户 (Dec 2024); OPPO announced invite-only individual app upload from end-Dec 2025 (ODC25, 智东西 2025-10-15); vivo opened a real-name individual channel on 2026-09-16 for AI/蓝河/IoT apps. None of this changes the "APK link" recommendation, but the table's store column should say "Xiaomi: closed to individuals; OPPO: invite-only pilot; vivo: individual channel, APK apps not yet included".
5. **An `ntfy` webhook format is a schema change, not a 20-line patch.** `user_settings.webhook_format` carries `CHECK (webhook_format IN ('generic','wecom','feishu','serverchan','bark'))` (`backend/wd/migrations/0001_init.sql:156`, `docs/SCHEMA.sql:156`); `backend/wd/db.py` documents that changing a CHECK list requires the SQLite table-rebuild recipe (no existing migration does one). Add migration 0010 + schemas.py:37 + webhook.py:37/build_payload + frontend types.ts:17, zh.ts:77, SettingsPage.tsx:27 + API.md:251, DESIGN.md:325/425, FRONTEND.md:278 + the parametrised tests — about 1 day.
6. **Citation hygiene for the Android write-up.** The June 2026 blog URL is `…/2026/06/android-developer-verification.html` (the digest's slug 404s); the Huawei secure-shield doc is only readable at the `harmonyos-guides-V5/…-V5` URL (updated 2025-03-17); the "WebView doesn't support the Push API" sentence is not on Microsoft's Edge push page (updated 2026-09-02) — it is pushpad's wording; the Edge-Android breakage starts with the Sept 28, 2025 builds per the Q&A timeline; the Firefox README says "supported by Google Play Services" (not "supposed"); ithome's 备案 article is dated 2024-03-04; cyrusyip (2024-10-12) and the OPPO forum post (2020) are both well past the 6-month freshness bar — replace with sunsetbrowser.app (2026-10-18) and the ODC25 reports.
