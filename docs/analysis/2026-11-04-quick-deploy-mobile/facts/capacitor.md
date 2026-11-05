# Fact slice: capacitor — wrapping the existing SPA for iOS (TestFlight) and Android (APK) for a ≤10-person circle

Date: 2026-11-04 · repo /Users/sqin/word-dance @ 9ab13a5 · Capacitor packages inspected: @capacitor/core 8.6.0, @capacitor/cli 8.6.0, @capacitor/ios 8.6.0, @capacitor/android 8.6.0, @capacitor/local-notifications 8.3.1, @capacitor/app 8.1.2, @capacitor/assets 4.0.0 README (npm registry, downloaded 2026-11-04 into `/private/tmp/claude-501/-Users-sqin-word-dance/729429d5-a7a1-4def-84e7-dc3ba571c437/scratchpad/quick/capacitor-pkgs/`, sources grepped, nothing executed). Package paths below are relative to that directory.

## Summary

1. The backend is same-origin by construction: HttpOnly `SameSite=Lax` cookie, CSRF rule that accepts only the Host-derived or `WD_PUBLIC_URL` origin, no CORS, and cookie-gated `/media`. Of the three modes, only **M1 (remote shell: `server.url = https://<domain>`)** satisfies all of it with **zero backend change**, because the WebView's document origin *is* the server origin; M2 (bundled dist) and M3 (bearer token) each need backend work plus a rebuild-and-redistribute cycle for every web change.
2. Verified from the shipped Capacitor 8.6 sources (not docs): the native bridge **is injected into pages loaded from `server.url`** on both platforms (iOS `WKUserScript` at document start; Android proxies the HTML document and inlines the bridge), so the remote site can call native plugins. `window.Capacitor.Plugins.*` is **not** populated without the npm JS; the website must bundle `@capacitor/core` + the plugin JS (recommended) or use the internal `window.Capacitor.nativePromise(...)`.
3. Nothing native is mandatory for M1. Optional: `@capacitor/local-notifications` daily reminder at `settings.push_time` (iOS = repeating calendar trigger; Android = exact alarm only if the user grants "Alarms & reminders", otherwise inexact), `@capacitor/app` back-button handling (without a listener the root back press is swallowed), nothing for status bar (iOS `.default` style auto-adapts to dark mode), nothing for external links (target=_blank already opens the system browser).
4. Three real code pitfalls: (a) `.page` has no top safe-area padding, so titles sit under the iOS status bar / Dynamic Island and under Android ≥ Chromium-140 edge-to-edge WebViews (≈0.5 d CSS); (b) Android System WebView exposes no Web Speech API, so the Android app has **no pronunciation** unless `useSpeech` is routed to a TTS plugin (0.5–1 d, optional); (c) `<a download>` export does nothing inside either WebView (hide on native or use Filesystem+Share, 0.5 d).
5. Toolchain to add on this Mac: Xcode 27.x (≈3 GB download, 10–15 GB on disk) and, for Android, JDK 21 + command-line SDK tools (Android Studio optional). CocoaPods is **not** needed (Capacitor 8 defaults to SPM). Stay on Capacitor 8.x: 9.0 (beta) requires Node 24, the Mac has Node 22.23.4.
6. Distribution: iOS via TestFlight **internal** testing (friends added as App Store Connect users, no Beta App Review, 90-day build expiry → re-upload every ≤90 days); Android via a self-signed APK served by Caddy (HarmonyOS NEXT phones cannot install APKs). App Store guideline 4.2 is irrelevant for these two channels.
7. Estimate for M1, both platforms: **≈5 person-days (range 4–6.5)** plus external waits (Apple enrolment 1–2 days, downloads). M2 ≈ 7–9 d, M3 ≈ 8–11 d. Recommendation: M1.

## Findings

### F1 (high) The backend's auth/CSRF/media contract is satisfied by M1 without any change
- Claim: With the WebView document at `https://<domain>`, every existing mechanism works unchanged: same-origin cookie, CSRF Origin equality, cookie-gated images, CSP.
- Evidence: cookie `wd_session` is `HttpOnly; SameSite=Lax; Path=/; Max-Age=session_days*86400; Secure` when https (`backend/wd/security.py:230-242`, `cookie_secure()` :213-227). CSRF: non-GET `/api/*` needs `X-WD-Request: 1`; when `Origin` is present it must equal `host_origin()` (scheme from `X-Forwarded-Proto` under `WD_TRUST_PROXY`) or `cfg.public_origin`; `null` rejected (`backend/wd/deps.py:111-129`). Media: `/media/images/{path}` and `/media/card/{id}.svg` call `current_user` → cookie required (`backend/wd/routers/media.py:38-57`). Client: relative paths, `credentials: 'same-origin'`, header added for non-GET (`frontend/src/api/client.ts:99-108`); images are relative `/media/...` URLs (`frontend/src/api/endpoints.ts:502-505`, `frontend/src/components/study/WordImage.tsx:53-64`). CSP `default-src 'self'; img-src 'self' data:; script-src 'self'; connect-src 'self'; frame-ancestors 'none'` (`backend/wd/main.py:93-101`). SPA index served `Cache-Control: no-cache`, hashed assets immutable (`backend/wd/main.py:243-259`).
- Implication: In M1 the WebView sends `Origin: https://<domain>` on POSTs, which equals the Host-derived origin behind Caddy (`WD_TRUST_PROXY=1`, `WD_PUBLIC_URL=https://<domain>`, DEPLOY.md:302-307), the cookie is first-party for fetch and `<img>` alike, and a website deploy is the app update. Prerequisite from the web slice: a domain with TLS (`server.cleartext` stays false; iOS ATS blocks plain http).
- Confidence: high.

### F2 (high) M2 (bundled dist) breaks on CSRF/CORS *and* on cookies; CapacitorHttp fixes only fetch, not `<img>`
- Claim: A bundled build runs at `capacitor://localhost` (iOS) / `https://localhost` (Android). A browser-stack `fetch` to `https://<domain>/api/...` is cross-origin: the custom header forces a CORS preflight, the backend has no CORS ("No CORS", `docs/API.md:11`), and even with CORS the Origin would be rejected (`deps.py:126-129`: allowed = Host-derived origin ∪ `WD_PUBLIC_URL` origin). Cookies would not be attached (SameSite=Lax is cross-site here; iOS blocks third-party cookies by default — `capacitor-core-8.6.0/package/cookies.md:83-88` "As of iOS 14, you cannot use 3rd party cookies by default", WKAppBoundDomains workaround). Enabling CapacitorHttp routes fetch/XHR natively (bridge patches fetch only when the plugin is enabled: `capacitor-ios-8.6.0/package/Capacitor/Capacitor/assets/native-bridge.js:458-464`), so no browser Origin on iOS; **but on Android 8.x CapacitorHttp is a WebView interceptor that forwards every WebView request header to the remote** (`capacitor-android-8.6.0/package/capacitor/src/main/java/com/getcapacitor/WebViewLocalServer.java:290-297`, `shouldInterceptRequest` :187-200) — if the WebView includes `Origin: https://localhost` on POSTs (Chromium sends Origin on non-GET requests), `csrf_violation` answers "Origin mismatch". `<img>` loads are never patched → `/media` 401 for every photo and card.
- Implication: M2 needs either a new allow-list setting + CORS layer, or CapacitorHttp plus a backend change for images (signed/tokenised media URLs, 1 d per `docs/PUBLIC_LAUNCH_AND_IOS.md` §4.3 table) or a client-side blob-fetch rewrite of `WordImage` (0.5 d, memory cost), plus moving `wd.pendingGrades` off localStorage, plus a rebuild per web change. Not worth it for the circle.
- Confidence: high for the backend/code facts; medium for the Android Origin-forwarding risk (header set not verified on a device).

### F3 (medium) M3 (bearer token) is the largest change and still needs the media fix
- Claim: Prior analysis costed it: `deps.current_user` accepts `Authorization: Bearer` mapped onto the `sessions` table (SCHEMA.sql:87-95), login/register variant returning `{token, expires_at}`, Origin check skipped for bearer requests — 1–2 d; `/media` signed URLs — 1 d (`docs/PUBLIC_LAUNCH_AND_IOS.md` §4.3). Client side: base URL, header injection, token in `@capacitor/preferences`, logout/expiry handling ≈ 1 d.
- Implication: ≈ 3–4 d before the first screen works, and the website's cookie path must keep working in parallel. It only pays off for a future native/RN client.
- Confidence: medium (effort figures are the prior slice's, re-read not re-derived).

### F4 (high) The Capacitor bridge is injected into `server.url` pages on both platforms (verified from source)
- Claim: iOS: `exportCapacitorGlobalJS` injects `window.Capacitor = {DEBUG, isLoggingEnabled, Plugins: {}}; window.WEBVIEW_SERVER_URL=...` as a `WKUserScript(injectionTime: .atDocumentStart, forMainFrameOnly: true)`; `exportBridgeJS` injects `native-bridge.js` the same way; plugin headers are pushed into `window.Capacitor.PluginHeaders` by another user script (`capacitor-ios-8.6.0/package/Capacitor/Capacitor/JSExport.swift:18-21, 24-28, 101, 107, 212`). User scripts run in every main-frame document the WKWebView loads, remote or local, and are not subject to the page's CSP. Android: when `server.url` is set, `isMainUrl()` is false and `isAllowedUrl()` true (`WebViewLocalServer.java:246-252`), so document requests reach `handleProxyRequest`, which — for GET with `Accept: text/html` — fetches the page itself via `HttpURLConnection`, forwards the WebView's request headers and `CookieManager` cookies, stores `Set-Cookie`, and returns the HTML with the bridge `<script>` inlined after `<head>` (`WebViewLocalServer.java:515-571`, `JSInjector.java:92-104`); `Bridge.java:241` adds the server URL to the allowed origin rules for bridge messaging.
- Implication: This is exactly the live-reload mechanism, so it is exercised daily by Capacitor users. Side effects to know: on Android the proxied document loses the backend's response headers (`handler.buildDefaultResponseHeaders()` replaces CSP/HSTS for the HTML only; sub-resources and `/api`/`/media` are untouched and still carry cookies normally); on iOS the backend CSP applies but cannot block user scripts.
- Confidence: high.

### F5 (high) Without the npm JS, `window.Capacitor` exposes `isNativePlatform`/`nativePromise` but `Plugins.*` stays empty
- Claim: `native-bridge.js` defines `cap.isNativePlatform = () => true`, `cap.getPlatform`, `cap.isPluginAvailable` (hasOwnProperty on `cap.Plugins`), `cap.nativeCallback(plugin, method, options, cb)` and `cap.nativePromise(plugin, method, options)` (`.../assets/native-bridge.js:824-836, 991-1008`). `Plugins` is created empty by the native global script (JSExport.swift:19) and is filled only by `registerPlugin()` in `@capacitor/core`'s `dist/index.js` (`createCapacitor` merges with `win.Capacitor`, lines 43-48; `Plugins[pluginName] = proxy` at 174; `isNativePlatform = () => getPlatform() !== 'web'` at 48).
- Implication: Two workable designs for the remote page: (A, recommended) add `@capacitor/core`, `@capacitor/app`, `@capacitor/local-notifications` to `frontend/package.json` and import them normally — on the plain web `Capacitor.getPlatform()` is `'web'` and the code is gated off; in the app the imported `registerPlugin` proxies talk to the injected bridge. Keep the website's `@capacitor/core` on the same major as the native apps. (B) call `window.Capacitor.nativePromise('LocalNotifications','schedule',{...})` directly with no dependency — works today but is an internal API. The toolchain slice should double-check (A) against the Capacitor docs' live-reload workflow.
- Confidence: high for what the sources show; medium for long-term support of (B).

### F6 (high) `capacitor.config` keys relevant to M1, with their documented semantics (CLI 8.6.0 declarations)
- Claim (all quotes from `capacitor-cli-8.6.0/package/dist/declarations.d.ts`): `server.url` "Load an external URL in the Web View. This is intended for use with live-reload servers. **This is not intended for use in production.**" (:566-575); `server.allowNavigation` "By default, all external URLs are opened in the external browser (not the Web View)" + same production warning, default `[]` (:590-601); `server.errorPath` "Specify path to a local html page to display in case of errors. On Android the html file won't have access to Capacitor plugins." since 4.0.0 (:602-609); `server.cleartext` default false (:587-589); `android.minWebViewVersion` default 60, "If `server.errorPath` is configured, the WebView will redirect to that file" (:190-200); `ios.limitsNavigationsToAppBoundDomains` default false, "it blocks navigation outside the domains in the `WKAppBoundDomains` list" (:384-396); `ios.contentInset` default `never` (:329-337); `android.allowMixedContent` default false (:130-133); `android.webContentsDebuggingEnabled` default false, "automatically enabled during development" (:145-152); `plugins.SystemBars.insetsHandling` `'native'|'css'|'disable'`, default `css` (:706-722). `npx cap sync` refuses a `webDir` without `index.html` (`dist/common.js:35-38`); `npx cap init <appName> <appId> --web-dir <dir>` (`dist/tasks/init.js:17-50`); `cap add ios` uses SPM unless `--packagemanager cocoapods` (`dist/index.js:30-37, 183-188`).
- Implication: "Not intended for production" is Ionic's support stance (and the App-Store-4.2 argument), not a technical block; for ≤10 friends on TestFlight-internal/APK it is an accepted, documented risk. Keep `limitsNavigationsToAppBoundDomains` false (true would disable the bridge for `<domain>` unless it is listed in `WKAppBoundDomains`). Keep `allowNavigation` empty so attribution hosts open externally.
- Confidence: high.

### F7 (high) External links need no code: target=_blank and foreign top-level navigations open the system browser
- Claim: iOS `createWebViewWith` (the `_blank`/`window.open` path) calls `UIApplication.shared.open(url)` and returns nil (`WebViewDelegationHandler.swift:334-339`); `decidePolicyFor` allows `allowNavigation` hosts, treats URLs starting with `serverURL` or `localURL` as application navigation, and sends any other top-level navigation to the system (`:101-121`). Android `launchIntent`: if host+scheme ≠ `appUrl` (= `server.url`, `Bridge.java:626-644`) and not in `allowNavigation` → `Intent.ACTION_VIEW` (`Bridge.java:413-426`). The only external link in the learner UI is the attribution anchor `<a href={landing} target="_blank" rel="noopener noreferrer">` (`frontend/src/components/study/WordImage.tsx:70`).
- Implication: Wikimedia/Openverse landing pages open in Safari/the default browser with a way back; `@capacitor/browser` (SFSafariViewController) is optional polish, not a need.
- Confidence: high.

### F8 (medium-high) Offline/error page: `server.errorPath` is honoured on both platforms; the retry link is an application navigation
- Claim: iOS `didFailProvisionalNavigation` and `didFail` load `config.errorPathURL` (local bundle URL + `errorPath`; `WebViewDelegationHandler.swift:155-158, 146-150`; `CAPInstanceConfiguration.swift:18-23`). Android `onReceivedError` on the main frame loads `bridge.getErrorUrl()` = `<scheme>://<host>/<errorPath>` from the bundled webDir (`BridgeWebViewClient.java:45-59`, `Bridge.java:553-565`); the same page is shown when the WebView is older than `minWebViewVersion` (`Bridge.java:305-313`).
- Implication: The stub `webDir` can be a single `index.html` that *is* the offline page (「无法连接，点击重试」 + `location.href='https://<domain>/'`), set `server.errorPath: 'index.html'`. The retry navigation targets `serverURL` so it is allowed in-app (iOS `isApplicationNavigation`; Android host match). Not device-tested here.
- Confidence: medium-high.

### F9 (medium-high) Cookie persistence in the app WebViews; separate jars from Safari/home-screen
- Claim: Capacitor's WKWebView uses the default (persistent) `WKWebsiteDataStore` and attaches a cookie observer (`CAPBridgeViewController.swift:121`); WebKit's 7-day deletion applies to script-writable storage — "Indexed DB, LocalStorage, Media keys, SessionStorage, Service Worker registrations and cache" — not to HTTP cookies set by the server (https://webkit.org/blog/10218/full-third-party-cookie-blocking-and-more/, accessed 2026-11-04). Android `CookieManager` persists cookies. The app's jar is distinct from Safari's and from a Home-Screen web app's, so each friend logs in once more per app; sessions are capped at 20 per user (`backend/wd/security.py:62`) and slid forward once per day with a fresh Max-Age (`backend/wd/deps.py:165-173`, `main.py:128-133`).
- Implication: The 30-day HttpOnly session survives app kills/reboots; `wd.pendingGrades`/UI prefs in localStorage (`frontend/src/pages/StudyPage.tsx:54-55`, `useLocalPref` keys) are script-writable and could in principle be purged after 7 in-app days without interaction — harmless for a daily-use app. Logout works as on the web.
- Confidence: medium-high.

### F10 (high / medium) Safe-area and status bar: the one CSS change M1 needs
- Claim: `viewport-fit=cover` is set (`frontend/index.html:5`) and `--safe-top/--safe-bottom` exist (`frontend/src/styles/tokens.css:55-56`); bottom insets are handled everywhere (TabBar `padding-bottom: var(--safe-bottom)` `AppLayout.css:120`, `--tabbar-h` `AppLayout.tsx:19,112-118`, `.page` bottom padding `global.css:150`, grade bars `study.css:241,373`, FAB `BankPage.css:76`, toasts `ui.css:325`). **Top** insets are only applied to the desktop TopNav (`AppLayout.css:26`) and the sticky letter rail (`list.css:167`); `.page` uses `padding-block: var(--space-4) …` with no `--safe-top` (`global.css:144-151`) and the guest `.auth` layout is `min-height:100dvh; padding-block: var(--space-6)` (`LoginPage.css:2-8`). In a Home-Screen web app with `apple-mobile-web-app-status-bar-style=default` the status bar is opaque so this never showed; in Capacitor the WKWebView extends under the status bar (`ios.contentInset` default `never`, `CAPBridgeViewController.swift:302`). Android: Capacitor 8's built-in `SystemBars` plugin (`insetsHandling` default `css`) pads the WebView and sets `env()` to 0 on Chromium < 140, but on ≥ 140 honours `viewport-fit=cover` so the WebView is edge-to-edge with real `env()` values (`capacitor-core-8.6.0/package/system-bars.md` "Android Note"; `plugin/SystemBars.java:193-248`); apps targeting SDK 36 (the template's `targetSdkVersion = 36`, `tpl-android/variables.gradle`) cannot opt out of edge-to-edge on Android 16 ("For apps targeting Android 16 (API level 36), `R.attr#windowOptOutEdgeToEdgeEnforcement` is deprecated and disabled, and your app can't opt-out of going edge-to-edge", https://developer.android.com/about/versions/16/behavior-changes-16, accessed 2026-11-04). Status bar text: Capacitor's `statusBarStyle` defaults to `.default` (`CAPBridgeViewController.swift:14, 229-231`), which on iOS 13+ "automatically chooses light or dark content based on the user interface style" (Apple UIStatusBarStyle docs via https://developer.apple.com/documentation/uikit/uistatusbarstyle.md and https://sarunw.com/posts/how-to-set-status-bar-style/, accessed 2026-11-04); the SPA follows the OS colour scheme only (`index.html:6-8`, prior slice frontend-parity-24), so they agree.
- Implication: Add `var(--safe-top)` to `.page`'s top padding and to `.auth`, re-check `StudyPage.css:5`/`ScreenRunPage.css:5` (`min-height: calc(100dvh - var(--safe-top))` assumes the top inset is consumed elsewhere) and the fixed `.tabbar`; on the web these resolve to 0 (no regression). ≈0.5 d with a device check on iPhone (Dynamic Island) and one Android ≥ Chromium 140. No `@capacitor/status-bar` needed.
- Confidence: high for the code facts; medium for the Android ≥140 branch (not device-tested).

### F11 (medium) Keyboard: Android resizes via the SystemBars inset listener; iOS behaves like Safari (visual viewport only)
- Claim: Capacitor's Android `SystemBars` listener reads `ime()` insets and keyboard visibility (`plugin/SystemBars.java:197-198, 248`), which gives adjustResize-like behaviour with the template manifest (no `windowSoftInputMode`, `tpl-android/app/src/main/AndroidManifest.xml`); WKWebView shrinks only the visual viewport, `100dvh` layouts (`global.css:23,29`, `AppLayout.css:6`, `LoginPage.css:6`, `StudyPage.css:5`) do not change, and `position: fixed` bars (`AppLayout.css:111`, `study.css:234`, `BankPage.css:74`, `ui.css:187,323`) stay behind the keyboard — only relevant on text-entry screens (login/register/welcome/bank-add/settings), none of which has a fixed bar that must stay visible while typing.
- Implication: No code change expected; verify the login form and the bank textarea on both devices during step 4.
- Confidence: medium.

### F12 (high / medium-high) Pronunciation: works (arguably better) on iOS, **absent** on Android WebView
- Claim: iOS: Capacitor sets `mediaTypesRequiringUserActionForPlayback = []` and `allowsInlineMediaPlayback = true` (`CAPBridgeViewController.swift:122-125`); WebKit only adds the speech restriction when `document->requiresUserGestureForAudioPlayback()` (`if (document->requiresUserGestureForAudioPlayback()) m_restrictions = BehaviorRestrictionFlags::RequireUserGestureForSpeechStart;`, https://raw.githubusercontent.com/WebKit/WebKit/main/Source/WebCore/Modules/speech/SpeechSynthesis.cpp, accessed 2026-11-04), so the auto-pronounce effect on card change (`frontend/src/pages/StudyPage.tsx:206-212`) should speak without the first tap that Safari requires; voices remain the pre-installed Samantha/Daniel matched by `PREFERRED_VOICE` (`frontend/src/hooks/useSpeech.ts:9,24-26`); Web Speech follows the ring/silent switch and nothing in the page can change that. Android: Android System WebView does not expose the Web Speech API — Chromium ships WebView with the speech API disabled ("disable-speech-api" for WebView; reports of `window.speechSynthesis === undefined` on WebView Chromium 138: https://community.xibo.org.uk/t/android-player-speechsynthesis-web-speech-api-unavailable-in-webview-chromium-138/38219, https://issues.chromium.org/41172064, accessed 2026-11-04). The SPA then reports `speechSupported() === false` (`useSpeech.ts:12`), `SpeakButton` renders disabled with 「当前浏览器不支持语音」 (`frontend/src/components/word/SpeakButton.tsx:24-35`) and auto-pronounce is a no-op.
- Implication: The Android app would ship without pronunciation — a visible gap for an English-vocabulary app. Fix (optional, 0.5–1 d): when `Capacitor.isNativePlatform()`, route `speak()` to `@capacitor-community/text-to-speech` (`lang: accent`, iOS `category: 'playback'` also bypasses the silent switch) — requires bundling that plugin's JS into the website and adding it to the native projects. Or accept it for the first circle release.
- Confidence: high for the code paths; medium-high for the WebView fact (web reports; verify on one domestic Android); medium for the iOS "no first tap" inference.

### F13 (high) Downloads, file input, clipboard inside the WebViews
- Claim: Export uses `<a href="/api/account/export?format=csv|json" download>` (`frontend/src/pages/SettingsPage.tsx:597-601`, `endpoints.ts:394`) and the server answers `Content-Disposition: attachment` (`backend/wd/routers/account.py:201`). Neither Capacitor platform implements downloads: no `WKDownloadDelegate` in the iOS sources and no `DownloadListener` in the Android sources (grep of `capacitor-ios-8.6.0/package/Capacitor/Capacitor/*.swift` and `.../getcapacitor/*.java`: zero hits), so the tap does nothing or blanks the view. Import `<input type=file>` (`SettingsPage.tsx:609`) works: Android `BridgeWebChromeClient.onShowFileChooser` (`BridgeWebChromeClient.java:276`), iOS native document picker. `navigator.clipboard.writeText` is used only on the admin page (`frontend/src/pages/AdminPage.tsx:407`), which is not in the phone tab bar; it works on https origins with a gesture in both WebViews. `crypto.randomUUID`, `<dialog>.showModal`, `color-mix()`, `dvh` all need a modern engine; iOS 15+ (Capacitor's floor) is fine for the circle's iPhones, Android WebView needs ≥108 for `dvh`.
- Implication: In the web bridge hide the two export anchors when native (or later replace them with `@capacitor/filesystem` + `@capacitor/share`, 0.5 d); set `android.minWebViewVersion: 108` so a stale OEM WebView shows the error page rather than a broken layout.
- Confidence: high.

### F14 (high) Daily reminder via `@capacitor/local-notifications`: data model, scheduling semantics, permissions
- Claim: The user's schedule is `settings.push_time` (HH:MM), `settings.timezone`, `settings.push_enabled` (`frontend/src/api/types.ts:34-41`), edited in `PushSection` (`SettingsPage.tsx:171-199, 276-293`) and onboarding (`WelcomePage.tsx:74,116,271`); `AuthContext` exposes `settings` and `updateSettings` (`frontend/src/auth/AuthContext.tsx:17-41, 142-146`). Plugin 8.3.1: `schedule.on = {hour, minute}` is "similar to scheduling cron jobs… Only available for iOS and Android" (`dist/esm/definitions.d.ts:944-954, 969-977`); iOS builds `UNCalendarNotificationTrigger(dateMatching:, repeats: true)` from the components without a time zone, i.e. device-local wall time (`ios/Sources/LocalNotificationsPlugin/LocalNotificationsPlugin.swift:553-555, 576-598`); Android computes `on.nextTrigger(now)`, schedules exact only if `isExactNotification && canScheduleExactAlarms()`, else `setAndAllowWhileIdle`/`set` with a warning (`android/src/main/kotlin/.../LocalNotificationManager.kt:339-378`), re-arms after each fire (`TimedNotificationPublisher.kt:42-56`) and after reboot (`LocalNotificationRestoreReceiver`, manifest `BOOT_COMPLETED`). The plugin manifest declares `POST_NOTIFICATIONS`, `SCHEDULE_EXACT_ALARM`, `RECEIVE_BOOT_COMPLETED`, `WAKE_LOCK` (`android/src/main/AndroidManifest.xml`); `requestPermissions()` triggers the Android 13+ runtime prompt (`LocalNotificationsPlugin.kt:32, 474-479`; README:14-16). Android 14+: `SCHEDULE_EXACT_ALARM` "is no longer being pre-granted to most newly installed apps targeting Android 13 and higher (will be set to denied by default)" (https://developer.android.com/about/versions/14/changes/schedule-exact-alarms, accessed 2026-11-04) → `checkExactNotificationSetting()`/`changeExactNotificationSetting()` exist to deep-link the user to "Alarms & reminders" (`definitions.d.ts:216-224`; README:18-26); the schedule result carries a `warning` when it fell back to inexact (README:574). iOS foreground presentation is configurable via `plugins.LocalNotifications.presentationOptions` (since 8.2.0, README:46). `allowWhileIdle` notifications "can only fire once per 9 minutes, per app" (`definitions.d.ts:937-943`).
- Implication: A repeating notification at the user's local push time is ~100 lines of web code (below) and needs no backend. Caveats to state in the UI copy: Android reminders may arrive minutes late unless the user grants exact alarms; OEM battery savers (MIUI/ColorOS/HarmonyOS 4) can suppress alarms for apps not whitelisted ("autostart"); the time is the device's zone — convert from `settings.timezone` when they differ. The server-side push (email/Bark webhook, `docs/PUBLIC_LAUNCH_AND_IOS.md` §1.3) stays the content channel; the local notification is only a reminder that opens `/today`.
- Confidence: high.

### F15 (high) Android back button: add a listener or the root back press does nothing
- Claim: With `@capacitor/app` installed natively and no JS `backButton` listener, the `OnBackPressedCallback` calls `webView.goBack()` when history exists and otherwise swallows the press (`capacitor-app-8.1.2/package/android/src/main/java/com/capacitorjs/plugins/app/AppPlugin.java:46-62`); with a listener it emits `{canGoBack}` and the app decides. `App.minimizeApp()` and `App.exitApp()` exist (`dist/esm/definitions.d.ts:155-188`); the listener disables the default behaviour ("you might want to call `window.history.back()` manually", `:268-275`). The callback is registered on the `OnBackPressedDispatcher`, i.e. compatible with Android 16 predictive back.
- Implication: Web bridge: `App.addListener('backButton', ({canGoBack}) => canGoBack ? window.history.back() : App.minimizeApp())` (react-router pushes history entries, so in-app back works through `history.back()`).
- Confidence: high.

### F16 (medium) Toolchain: what the Mac has, what the repo needs, sizes
- Claim: Mac today (checked 2026-11-04): `xcode-select -p` = `/Library/Developer/CommandLineTools` (no Xcode.app), `java` stub says "Unable to locate a Java Runtime", no `pod`, system Ruby 2.6.10, node 22.23.4 / npm 10.9.9, 830 GiB free, no `~/Library/Android`. Capacitor 8 (`latest` = 8.6.0; `next` = 9.0.0-beta.0, `npm view @capacitor/cli dist-tags` 2026-11-04) needs Node ≥22 (prior slice ios-tech-options-18; Capacitor 9 needs Node 24 — same source), Xcode ≥26 (prior slice), SPM by default (iOS template `Package.swift`: `platforms: [.iOS(.v15)]`, `capacitor-swift-pm` from 8.0.0; `IPHONEOS_DEPLOYMENT_TARGET = 15.0`, `MARKETING_VERSION = 1.0`, `CURRENT_PROJECT_VERSION = 1`, `UIViewControllerBasedStatusBarAppearance = true`, `tpl-ios/App/App/Info.plist`, `project.pbxproj`), Android JDK 21 (`capacitor-android-8.6.0/package/capacitor/build.gradle:66-67` `JavaVersion.VERSION_21`), AGP 8.13.0, Gradle 8.14.3, compileSdk/targetSdk 36, minSdk 24 (`tpl-android/build.gradle:10`, `gradle/wrapper/gradle-wrapper.properties`, `variables.gradle`). Xcode 27.x: 3.12 GB download, ≈10–15 GB installed, iOS simulator runtime ≈8 GB optional (prior slice ios-tech-options-33, not re-verified today). Android: CLI-only route `brew install --cask temurin@21 android-commandlinetools` + `sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"` ≈ 1.5–2 GB plus ≈1 GB Gradle/Maven cache (sizes from experience, low confidence); Android Studio (≈1.3 GB download, 4–5 GB installed, bundles a JBR 21) only if an emulator/debugger is wanted.
- Implication: No CocoaPods/Ruby work at all. Gradle's first run pulls from `dl.google.com`/Maven Central — on this network route it through the existing SOCKS proxy (`~/.gradle/gradle.properties` `systemProp.https.proxyHost/Port`) or Aliyun mirrors. Budget 2–6 h wall-clock for downloads, ≈0.5 person-day of attention.
- Confidence: medium.

### F17 (high) Icons and splash from `favicon.svg` via `@capacitor/assets`
- Claim: Easy Mode takes a single `assets/logo.png` or `logo.svg` ("the tool also supports using SVG files as source images") plus `--iconBackgroundColor`, `--iconBackgroundColorDark`, `--splashBackgroundColor(Dark)`, `--logoSplashScale` (README of @capacitor/assets 4.0.0 fetched from the registry 2026-11-04, lines 21-48; custom mode needs 1024² icons and 2732² splashes, lines 54-67). `frontend/public/favicon.svg` is a 64-unit viewBox: blue `#3b5bdb` rounded square with a white "W" path — vector, so it scales.
- Implication: `cp frontend/public/favicon.svg mobile/assets/logo.svg && npx @capacitor/assets generate --iconBackgroundColor '#3b5bdb' --iconBackgroundColorDark '#3b5bdb' --splashBackgroundColor '#ffffff' --splashBackgroundColorDark '#121620'` (≈15 min). The Android notification small icon (white silhouette drawable, `plugins.LocalNotifications.smallIcon`, README:43) is not generated — hand-draw from the same path (≈15 min).
- Confidence: high.

### F18 (medium) iOS signing and TestFlight for a circle of ≤10 mainland friends
- Claim: Paid Apple Developer Program required for TestFlight (¥688/yr via the Apple Developer app with mainland payment methods; identity check by ID photo — prior slice apple-appstore-1/2, re-read not re-verified). TestFlight: "up to 100 App Store Connect users" as internal testers, "up to 10,000 people" external, "A review is required only for the first build" added to an external group, "Your build becomes unavailable for testers after 90 days" (https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview, accessed 2026-11-04). Territory gotcha: a mainland-developer KB states "you must use an Apple ID from a region where Surge is available to install the TestFlight version (i.e., not a Chinese Apple ID)" with the error "The requested App is not available or does not exist" (https://kb.nssurge.com/surge-knowledge-base/faq/ios-testflight, accessed 2026-11-04) — i.e. TestFlight installs follow the app's App Store availability territories. Apple forum reports of TestFlight showing connection errors for a China-based tester exist without resolution (https://developer.apple.com/forums/thread/702410, 2022-03, accessed 2026-11-04). Free Personal Team: cable install on the owner's own iPhone only, 7-day re-sign, no TestFlight (prior slice). Ad Hoc: ≤100 devices/membership year, OTA `.ipa` + `manifest.plist` over https (prior slice apple-appstore-26).
- Implication: For the circle use **internal testing**: invite each friend's Apple ID as an App Store Connect user (any role with TestFlight access), no Beta App Review, builds appear minutes after processing. Keep **China mainland selected** in Pricing & Availability (the default) so mainland Apple IDs can install; this conflicts with the prior doc's "deselect mainland to avoid the ICP field" advice, which concerned App Store submission — for TestFlight-only use the field is not submitted (open question below). Re-upload a build (bump `CURRENT_PROJECT_VERSION`) at least every 90 days even if nothing changed. Add `ITSAppUsesNonExemptEncryption = NO` to Info.plist to skip the export-compliance prompt per upload.
- Confidence: medium (territory behaviour from a third-party KB; Apple's page does not state it).

### F19 (high / medium) Android signing, APK hosting, versionCode, device realities
- Claim: The template's `release` build type has no `signingConfig` (`tpl-android/app/build.gradle:19-24`), `versionCode 1`, `versionName "1.0"` (`:10-11`); `./gradlew assembleRelease` therefore yields an unsigned APK → sign with a self-generated keystore (`keytool -genkeypair … -validity 10000`) either via a `signingConfigs.release` block + `keystore.properties` (gitignored) or `zipalign -p 4` + `apksigner sign --ks …`. Android refuses updates with a lower/equal `versionCode` or a different signing key. The backend's SPA fallback returns `index.html` for unknown paths (`backend/wd/main.py:243-260`), so the APK must be served by Caddy (e.g. `handle_path /dl/* { root * /srv/dl; file_server }` before `reverse_proxy` in `deploy/Caddyfile.example`), not dropped into the frontend snapshot. HarmonyOS NEXT (HarmonyOS 5) "does not include the Android AOSP core and is incompatible with Android applications" (https://en.wikipedia.org/wiki/HarmonyOS_5; https://m.gsmarena.com/harmonyos_next_wont_have_android_app_support-news-60561.php, accessed 2026-11-04). Capacitor's `minHuaweiWebViewVersion` exists for HarmonyOS ≤4 Huawei WebView (`Bridge.java:107-108`, `CapConfig.java:283`).
- Implication: Friends on HarmonyOS NEXT phones cannot sideload the APK — they use the website (home-screen bookmark); the web slice's PWA/bookmark path remains necessary. Domestic Android phones show "unknown source" warnings; write a 5-line zh install note. Keep `versionCode` monotonic (e.g. `YYYYMMDDn`) and the keystore + password backed up (losing it means a new app id for updates).
- Confidence: high for the template/backend facts; medium for device-specific behaviour.

### F20 (high) Update path and version skew under M1
- Claim: The app always loads the current website: `index.html` is served `Cache-Control: no-cache` and hashed assets `public, max-age=31536000, immutable` (`backend/wd/main.py:251-259`); the deploy publishes an atomic snapshot (`docs/DEPLOY.md:217`). Native rebuilds are needed only for Capacitor/plugin/OS updates and the 90-day TestFlight expiry. The only coupling is the `@capacitor/core` JS major bundled into the website versus the native runtime major.
- Implication: No API versioning gate, no `min_client_version` work (contrast prior §4.3 "版本协商 1 天"), no re-distribution for UI fixes — the main reason M1 is 3–5 days cheaper than M2/M3 for this audience.
- Confidence: high.

### F21 (medium) Store-risk framing: 4.2 applies to App Store review and to Beta App Review for *external* TestFlight only
- Claim: The prior verdict "Do not design around server.url (remote shell): documented as live-reload-only, and it would also maximise App Review 4.2 exposure" (`docs/analysis/2026-11-03-public-launch/verdicts.md:104`; `docs/PUBLIC_LAUNCH_AND_IOS.md:280`) was written for the store route. TestFlight internal testing has no review; external groups get Beta App Review on the first build (F18); APK sideload has no review.
- Implication: For the circle the 4.2 risk is zero (internal) or a possible Beta-review rejection (external link). If an App Store listing is ever wanted, the remote shell must be replaced by M2/M3 plus the 4.2 mitigations the prior doc lists — M1 code is not wasted (bridge, icons, projects, CSS fix carry over).
- Confidence: medium.

### F22 (medium) Decision matrix

| Criterion | M1 remote shell (`server.url`) | M2 bundled dist + CapacitorHttp | M3 bearer token |
|---|---|---|---|
| Web code reuse | 100 % (+≈120 lines bridge, +1 CSS rule) | ≈95 % (client base URL, image loading, pending-grade storage) | ≈90 % (auth flow, headers, media) |
| Backend change | none | 0–1 d (signed media URLs) + Android Origin-forwarding risk (F2) | 2–3 d (token + media) |
| Person-days, both platforms | 4–6.5 (≈5) | 7–9 | 8–11 |
| Store (4.2) risk if ever submitted | highest | medium | medium |
| Risk on TestFlight-internal / APK | none | none | none |
| Offline | local error page only (data online, as on the web) | shell opens offline, data still online | same as M2 |
| Update path | deploy website → instant; rebuild ≤ every 90 d (TestFlight expiry) | rebuild + redistribute per web change; API/version skew | same as M2 |
| Cookies / images | first-party, SameSite=Lax works, `<img>` works | native cookie jar via CapacitorHttp; `<img>` 401 without backend change | token header; `<img>` needs signed URLs |
| Native plugins | yes (bridge injected, F4) | yes | yes |

Recommendation: **M1**.

## Recommendations (M1, step list with estimates)

Prerequisite (web slice, not counted): the site live at `https://<domain>` with `WD_PUBLIC_URL=https://<domain>`, `WD_TRUST_PROXY=1`, Caddy TLS (DEPLOY.md:117, 302-307).

1. **Toolchain** (≈0.5 person-day of attention; 2–6 h wall-clock). Xcode 27.x from the Mac App Store; `sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept && xcodebuild -runFirstLaunch`. Android CLI-only: `brew install --cask temurin@21 android-commandlinetools`; `export JAVA_HOME=$(/usr/libexec/java_home -v 21) ANDROID_HOME=/opt/homebrew/share/android-commandlinetools`; `sdkmanager --licenses && sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"`; proxy settings for Gradle (F16). Exact version pins: toolchain web slice.
2. **Project skeleton** (≈2 h), in a new top-level `mobile/` (keeps `frontend/` clean):
   `npm init -y && npm i @capacitor/core@8 @capacitor/cli@8 @capacitor/ios@8 @capacitor/android@8 @capacitor/app@8 @capacitor/local-notifications@8 && npm i -D @capacitor/assets`
   `npx cap init word-Dance <appId> --web-dir web` — appId suggestion: reverse-DNS of a domain the owner controls (e.g. `app.<domain-reversed>.worddance`; placeholder `com.worddance.app`); it becomes the iOS bundle id and Android `applicationId` and cannot change later without a new app.
   `web/index.html` = the offline/retry page (zh copy, a button doing `location.href='https://<domain>/'`); `capacitor.config.ts`:
   ```ts
   import type { CapacitorConfig } from '@capacitor/cli';
   const SITE = 'https://<domain>';
   const config: CapacitorConfig = {
     appId: 'com.worddance.app',          // replace (see above)
     appName: 'word-Dance',
     webDir: 'web',                       // stub: index.html is the offline page; the UI is remote
     backgroundColor: '#ffffff',
     appendUserAgent: 'word-Dance-App',   // shows up in sessions.user_agent; no backend change
     loggingBehavior: 'production',
     server: {
       url: SITE,                         // M1: the live site is the app
       cleartext: false,
       errorPath: 'index.html',           // shown when the site is unreachable (F8)
       // allowNavigation: []             // keep empty: attribution links open the system browser (F7)
     },
     ios: {
       contentInset: 'never',
       limitsNavigationsToAppBoundDomains: false,   // true would need WKAppBoundDomains incl. <domain> (F6)
       allowsLinkPreview: false,
     },
     android: {
       allowMixedContent: false,
       webContentsDebuggingEnabled: false,
       minWebViewVersion: 108,            // dvh/color-mix/<dialog> floor; older WebViews get the error page (F13)
     },
     plugins: {
       SystemBars: { insetsHandling: 'css' },        // Capacitor 8 default; env()/--safe-area handling (F10)
       LocalNotifications: { smallIcon: 'ic_stat_worddance', iconColor: '#3b5bdb',
                             presentationOptions: ['banner', 'sound', 'list'] },
     },
   };
   export default config;
   ```
   Then `npx cap add ios && npx cap add android && npx cap sync`. Commit `mobile/` minus `ios/App/App.xcodeproj/xcuserdata`, `android/.gradle`, `android/app/build`, keystores.
3. **Icons/splash** (≈0.5 h): `mkdir assets && cp ../frontend/public/favicon.svg assets/logo.svg && npx @capacitor/assets generate --iconBackgroundColor '#3b5bdb' --iconBackgroundColorDark '#3b5bdb' --splashBackgroundColor '#ffffff' --splashBackgroundColorDark '#121620'`; add `android/app/src/main/res/drawable/ic_stat_worddance.xml` (white "W" silhouette) (F17).
4. **First device runs and the verification checklist** (≈0.5 d). `npx cap open ios` → Signing: Team (free Personal Team is enough for the owner's own phone), bundle id, portrait-only, `CFBundleDisplayName` word-Dance, `ITSAppUsesNonExemptEncryption=NO`; run on the iPhone. Android: `cd android && ./gradlew assembleDebug && adb install app/build/outputs/apk/debug/app-debug.apk` (or `npx cap run android`). Check: login → kill app → relaunch still logged in (F9); photos and cards render (F1); TabBar bottom inset and page top inset (F10); attribution link opens Safari/browser (F7); airplane mode → error page → retry (F8); speech on iOS incl. auto-pronounce, disabled button on Android (F12); export anchors (F13); keyboard on login and bank-add (F11); dark mode status bar (F10).
5. **Web-side bridge in `frontend/`** (≈1 d incl. tests). Add deps `@capacitor/core@8`, `@capacitor/app@8`, `@capacitor/local-notifications@8`. New `src/native/capacitor.ts` (strings in `src/i18n/zh.ts` — the copy lint forbids CJK outside `src/i18n`, `frontend/scripts/check-copy.mjs:13-30`):
   ```ts
   import { Capacitor } from '@capacitor/core';
   import { App } from '@capacitor/app';
   import { LocalNotifications } from '@capacitor/local-notifications';
   import type { Settings } from '@/api/types';
   import { zh } from '@/i18n/zh';
   export const isNative = () => Capacitor.isNativePlatform();      // false on the plain website
   const REMINDER_ID = 1;
   /** HH:MM in settings.timezone → the device's local wall-clock hour/minute for today. */
   export function toDeviceWallTime(pushTime: string, tz: string, now = new Date()) {
     const [h, m] = pushTime.split(':').map(Number);
     const device = Intl.DateTimeFormat().resolvedOptions().timeZone;
     if (!tz || tz === device) return { hour: h, minute: m };
     const ymd = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now); // YYYY-MM-DD
     const [y, mo, d] = ymd.split('-').map(Number);
     const guess = new Date(Date.UTC(y, mo - 1, d, h, m));
     const offsetMin = (() => { const p = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).formatToParts(guess);
       const g = (t: string) => Number(p.find((x) => x.type === t)!.value);
       return (Date.UTC(g('year'), g('month') - 1, g('day'), g('hour'), g('minute')) - guess.getTime()) / 60000; })();
     const instant = new Date(guess.getTime() - offsetMin * 60000);
     return { hour: instant.getHours(), minute: instant.getMinutes() };
   }
   /** Call inside a user gesture (the 每日推送 switch or a dedicated 本机提醒 switch). */
   export async function requestReminderPermission(): Promise<boolean> {
     if (!isNative()) return false;
     return (await LocalNotifications.requestPermissions()).display === 'granted';
   }
   /** Idempotent: cancel + reschedule from the current settings; call from an AuthContext effect. */
   export async function syncDailyReminder(settings: Pick<Settings, 'push_enabled' | 'push_time' | 'timezone'> | null) {
     if (!isNative()) return;
     await LocalNotifications.cancel({ notifications: [{ id: REMINDER_ID }] });
     if (!settings?.push_enabled) return;
     if ((await LocalNotifications.checkPermissions()).display !== 'granted') return;
     const { hour, minute } = toDeviceWallTime(settings.push_time, settings.timezone);
     await LocalNotifications.schedule({ notifications: [{
       id: REMINDER_ID, title: zh.app.name, body: zh.native.reminderBody,
       schedule: { on: { hour, minute }, allowWhileIdle: true },
       extra: { route: '/today' },
     }] });
   }
   /** Android back button + notification tap → router. */
   export function installNativeHandlers(navigate: (to: string) => void) {
     if (!isNative()) return () => undefined;
     const subs = [
       App.addListener('backButton', ({ canGoBack }) => { if (canGoBack) window.history.back(); else void App.minimizeApp(); }),
       LocalNotifications.addListener('localNotificationActionPerformed', (a) => { const r = a.notification.extra?.route; if (typeof r === 'string') navigate(r); }),
     ];
     return () => { for (const s of subs) void s.then((h) => h.remove()); };
   }
   ```
   Wiring: in `AuthProvider` add `useEffect(() => { void syncDailyReminder(state.settings); }, [state.settings?.push_enabled, state.settings?.push_time, state.settings?.timezone])` (`AuthContext.tsx` next to the bootstrap effect starting at :81); in `PushSection`'s `Switch` `onChange` call `requestReminderPermission()` before `save({push_enabled: v})` when native (`SettingsPage.tsx:275`); mount `installNativeHandlers(navigate)` once in `AppRoutes`/`App`; wrap the export anchors in `{!isNative() && …}` (`SettingsPage.tsx:597-601`); hide any future "添加到主屏幕" hint behind `!isNative()` (none exists today: grep for manifest/beforeinstallprompt/主屏幕 in `frontend/src` → zero hits). Tests: vitest for `toDeviceWallTime` (same zone, Asia/Shanghai vs Asia/Tokyo, DST zone), and a smoke that the module is inert when `window.Capacitor` is absent.
6. **CSS safe-area fix** (≈0.5 d incl. device check): `.page { padding-block: calc(var(--space-4) + var(--safe-top)) … }` (`global.css:150`), `.auth { padding-block: calc(var(--space-6) + var(--safe-top)) var(--space-6) }` (`LoginPage.css:7`), re-derive `StudyPage.css:5`/`ScreenRunPage.css:5` (then `min-height: 100dvh` with the padding, or keep the subtraction consistently), confirm `.tabbar`/toasts untouched. Zero visual change in browsers (insets are 0 there).
7. **iOS release** (≈0.5 d of work + Apple's 1–2 day enrolment wait): enrol in the Apple Developer Program; App Store Connect → New App (name word-Dance, bundle id, SKU, primary language zh-Hans), leave availability at all territories (F18); Xcode: Team, automatic signing, bump `CURRENT_PROJECT_VERSION`; Product → Archive → Distribute → App Store Connect → Upload (or `xcodebuild -scheme App -configuration Release archive … && xcodebuild -exportArchive -exportOptionsPlist …`); TestFlight → Internal Testing group → add testers (friends invited under Users and Access); they install TestFlight (China App Store has it) and accept. Calendar reminder: re-upload before day 90.
8. **Android release** (≈0.5 d): `keytool -genkeypair -v -keystore ~/secure/word-dance-release.jks -alias worddance -keyalg RSA -keysize 2048 -validity 10000`; `android/keystore.properties` + `signingConfigs.release` in `android/app/build.gradle` (or `apksigner`); set `versionCode`/`versionName`; `./gradlew assembleRelease` → `app/build/outputs/apk/release/app-release.apk`; copy to the server's `/srv/dl/word-dance-<versionName>.apk`, Caddy `handle_path /dl/*` file server (F19); zh install note (allow unknown sources; HarmonyOS NEXT → use the website; MIUI "autostart" for reminders).
9. **Buffer / device matrix** (≈1 d): one domestic Android (MIUI/ColorOS) for notification delivery under battery saver and WebView version, one HarmonyOS 4 Huawei if available, iPhone with Dynamic Island, dark mode on both, 90-day/versionCode bookkeeping notes in `docs/ops.md`.

Optional follow-ups: Android/iOS TTS via `@capacitor-community/text-to-speech` routed from `useSpeech` when native (0.5–1 d, F12); export via `@capacitor/filesystem` + `@capacitor/share` (0.5 d, F13); `SplashScreen` plugin to hide the white gap while the remote page loads (0.25 d); `@capacitor/browser` for in-app attribution pages (0.25 d).

**Total for M1, both platforms: ≈5 person-days (4–6.5)** — iOS-first path ≈2.5–3 d (steps 1–7 without Android parts), Android increment ≈1–1.5 d (steps 1/4/8 Android parts + device testing). External waits: Apple enrolment 1–2 days, toolchain downloads 2–6 h, TestFlight processing 5–30 min per build. Comparison: M2 ≈7–9 d (adds CapacitorHttp enablement, client base URL + cookie verification, image blob/signed-URL work, per-change rebuilds), M3 ≈8–11 d (adds 2–3 backend days and the token client).

## Open questions

1. Reachability: can the chosen host serve `https://<domain>` reliably to mainland phones (web slice)? M1 has no offline mode, so a slow or blocked origin is a blank app — the error page only covers hard failures.
2. Does Android System WebView include `Origin` in `WebResourceRequest.getRequestHeaders()` for POST fetches? Only matters for M2 (F2); if yes, CapacitorHttp on Android would be rejected by the unchanged CSRF rule.
3. TestFlight territories: does leaving "China mainland" available (needed for mainland Apple IDs per the Surge KB, F18) force the ICP filing field for TestFlight-only apps, or only at App Store submission? The prior slice found no documentation either way; the owner's own phone can test the install flow before inviting friends.
4. Does the Capacitor WKWebView really lift the speech user-gesture rule (F12 inference from `mediaTypesRequiringUserActionForPlayback = []`), and does Web Speech in WKWebView follow the app's `AVAudioSession` category if `AppDelegate` sets `.playback`? Device test; fallback is the TTS plugin.
5. Which Android WebView versions do the friends' phones run (Chromium ≥108 for `dvh`; ≥140 changes the SystemBars inset behaviour), and how many are on HarmonyOS NEXT (no APK at all)?
6. Is TestFlight itself usable on the friends' mainland networks? Forum reports of "You are no longer connected to the internet" exist (F18); Ad Hoc OTA (`itms-services://`) is the fallback and needs their UDIDs.
7. Capacitor 9 GA (targeted end of November 2026, Node 24): stay on 8.6 until the Mac's Node is bumped; is the owner fine with a one-major migration in 2027?
8. If an external TestFlight link is ever used, will Beta App Review accept a remote-shell app (4.2 exposure, F21)? Internal testing avoids the question.
9. Keep the server-side reminder channels (email/Bark webhook) as the default for the circle and treat the local notification as optional? It avoids the Android exact-alarm/OEM-killer caveats entirely (F14).
