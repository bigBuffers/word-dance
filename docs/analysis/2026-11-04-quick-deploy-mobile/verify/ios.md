# Verification report — slice `ios` (quick-deploy + mobile research)

Verifier run: 2026-11-04 11:31–11:50 UTC · repo baseline `main` @ 9ab13a5 · all web sources re-fetched today unless a date is given; iTunes lookup JSON and Apple doc JSON saved under `scratchpad/quick/verify/ios-raw/`.
Method: adversarial re-check of each digest claim against a PRIMARY source (Apple developer help / legal / news pages, Apple App Store lookup API, WebKit blog, Apple forum threads read directly), plus extended EN/ZH searches for contradictions. Anything older than 6 months is flagged `[stale]` even when still current. Nothing was written outside the scratchpad; port 8000, the data dir and the real `claude` were not touched.

| Claim | Verdict | One-line reason |
|---|---|---|
| F1 | confirmed | 99 USD / ¥688 auto-renew / no Apple Account balance / CN payment list all verbatim on Apple pages (HT202631 published 2026-08-07) |
| F2 | confirmed | CFCA, 身份证+selfie, same device, legal name as seller, T2/Apple-silicon Mac accepted, app 11.1.1 needs iOS/macOS 26.0; owner Mac = macOS 26.7.1 arm64 |
| F4 | confirmed | All numbers verbatim; "no review for internal" now backed by Apple's build-status reference ("Ready to Submit … can be distributed to internal testers, or submitted to TestFlight App Review for external testing") |
| F5 | confirmed | All six limits verbatim on Apple's page; 2.2 verbatim; guidelines last updated 2026-10-16 without touching 2.2/4.2 |
| F7 | corrected | Availability + staff quote + IP clause confirmed (primary: Apple "TestFlight & Privacy", 2025-01-27), but "the only caveat" is wrong: a recurring, mainland-reported failure mode ties TestFlight installs to the app's App Store availability/state |
| F8 | confirmed | ICP text lives only under App Store availability; no Apple/forum/ZH source ties ICP to TestFlight; one caveat inherited from F7 |
| F11 | confirmed | Lookup (US+CN) 27.2 / 3,119,586,528 B / macOS 26.6 / 2026-10-30; release notes: Swift 6.4, iOS 27.2 SDK, on-device debugging iOS 17+ |
| F12 | confirmed | "uploaded to App Store Connect" wording verbatim for 2026-04-28 and 2026-09-09; April 2027 iOS 27 SDK announced 2026-09-09 |
| F14 | confirmed | WebKit 26.0 post verbatim; Safari 27.0/27.1/27.2 posts (Sep–Oct 2026) contain no web-app changes; repo facts re-run; one digest quote about SVG icons was a paraphrase |
| F20 | corrected | The "browser around someone else's site" line was written by a community member, not Apple staff; no Apple staff replied in thread 812889; conclusion (internal TestFlight only) still stands |

---

## F1 — Apple Developer Program price from mainland China

**Verdict: confirmed.**

What I read (all accessed 2026-11-04):
- "Program enrollment" — https://developer.apple.com/support/enrollment/ (no visible page date): "The Apple Developer Program annual fee is 99 USD and the Apple Developer Enterprise Program annual fee is 299 USD, in local currency where available." · "Prices may vary by region and are listed in local currency during the enrollment process." · "If you haven't received a membership confirmation within 24 hours of your purchase, contact us." · "If you completed your purchase on the Apple Store Online in China mainland and would like to request a fapiao, call 400-666-8800 …" · "If you're paying by credit card and enrolling as an individual, you must use your own credit card to complete your purchase."
- "注册计划" (CN mirror) — https://developer.apple.com/cn/support/enrollment/: "Apple Developer Program 的年费为 99 美元，Apple Developer Enterprise Program 的年费为 299 美元 (如果适用，则以当地货币计费)。"
- "使用 Apple Developer App 注册、验证和续订" — https://developer.apple.com/cn/help/account/membership/enrolling-in-the-app/: "查看你的年度会员资格订阅详情，然后轻点或点按"以每年 ¥688 续订"。" · "会员资格会每年续订，直至你取消为止。" · "Apple Developer Program 会员费用不接受 Apple 账户余额 (通过兑换 Apple Gift Card 或直接充值) 付款方式。" · "你可以使用你 Apple 账户的付款方式之一进行购买。"
- EN twin — https://developer.apple.com/help/account/membership/enrolling-in-the-app/: "Apple Account balances (from redeeming Apple Gift Cards or adding funds) aren't accepted as payment for Apple Developer Program memberships."
- "Payment methods that you can use with your Apple Account" — https://support.apple.com/en-us/HT202631, **Published Date: August 07, 2026**, China mainland row: "Alipay", "Apple Account balance (from App Store top-up card or adding funds)", "Douyin Pay", "Most credit and debit cards", "WeChat Pay".
- Extended search for a 2026 fee change (EN): nothing beyond "$99 USD per year"; no Apple announcement of a change.

Notes: the ¥688 figure is published only in the Apple Developer *app* flow (an auto-renewing App Store subscription); Apple's web page gives no CNY price and says prices vary by region. The CN page also says the subscription can be cancelled "在每年续订日期的前一天在"设置"中" — i.e. it renews like any App Store subscription.

## F2 — Enrollment mechanics in the Apple Developer app

**Verdict: confirmed** (one wording nuance).

What I read:
- CN page (above), section "以个人身份注册 Apple Developer Program": "中国大陆地区的开发者可以使用 Apple Developer App 以自动续期会员身份来注册 Apple Developer Program" · "如果你位于中国大陆地区，这些服务将由中国金融认证中心 (CFCA) 提供。" · "输入你的名字、姓氏、身份证号和电话号码。请勿输入别名、昵称或公司名称作为你的姓氏或名字，错误地输入你的法定姓名将导致注册审核延误。" · "为了验证你的身份，系统会要求你拍摄自拍照" · "你的个人法定姓名将作为供应商列示在 App Store 上。" · device list: "启用了触控 ID、面容 ID 或锁屏密码的 iPhone 或 iPad，或搭载 T2 安全芯片和 Apple 芯片的 Mac。你必须在整个注册流程中使用相同的设备。" · Apple Account: "为 Apple 账户启用双重认证 … 在你的设备上登录 iCloud。"
- EN twin: "An iPhone or iPad with Touch ID, Face ID, or passcode enabled, or a Mac with the T2 Security Chip and Apple Silicon." · "You must use the same device for the entire enrollment process." · "enrollment may not be supported in certain regions, for example due to sanctions or other restrictions. For information about using the Apple Developer app in China mainland, view this page in Simplified Chinese."
- iTunes lookup (`itunes.apple.com/lookup?id=640199958&country=cn` and `country=us`, 11:33 UTC): version 11.1.1, minimumOsVersion 26.0, currentVersionReleaseDate 2026-10-22T22:30:35Z, fileSizeBytes 27609088, CN seller "Apple Distribution International".
- App Store CN page https://apps.apple.com/cn/app/apple-developer/id640199958: iPhone "设备需装有 iOS 26.0 或更高版本", iPad "iPadOS 26.0 或更高版本", Mac "设备需装有 macOS 26.0 或更高版本", 27.6 MB.
- Local: `sw_vers` → macOS 26.7.1 (25G241), `uname -m` → arm64; `xcode-select -p` → /Library/Developer/CommandLineTools (no Xcode).

Nuance: in the page's separate "验证身份" section the Mac requirement is printed as "搭载 T2 安全芯片的 Mac" (Apple silicon not repeated) — an inconsistency on Apple's page; the enrollment section explicitly includes Apple-silicon Macs, so the owner's Mac qualifies. The page says mainland developers "可以" use the app; it does not say the app is the only route. Also: "Apple Developer App 中的会员资格续订功能目前不支持通过 Apple 开发者网站完成注册的账户。" and "某些流程要求必须在此 App 中完成身份验证" — enrol in the app and keep it as the renewal/verification tool.

## F4 — TestFlight internal testing

**Verdict: confirmed.**

What I read:
- "Add internal testers" — https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers: "Required role: Account Holder, Admin, App Manager, Developer, or Marketing." · "Create a group and add up to 100 internal testers (App Store Connect users with access to your content) to test your app using TestFlight." · "If you choose testers not part of your App Store Connect account, you won't be able to add them to an internal group." · "Internal testers can download and test all builds for 90 days." · "If you have builds available for testing, the users you chose will receive an email inviting them to test the app. The users will be directed to accept the invitation using the TestFlight app on their device or with a redemption code." · "Note: Managed Apple Accounts created in reserved domains can't be used to test builds." No sentence on the page mentions review.
- "Add and edit users" — https://developer.apple.com/help/app-store-connect/manage-your-team/add-and-edit-users: "If you're enrolled in the Apple Developer Program as an individual, you can give up to 50 additional users access to your content in App Store Connect." · "Any email can activate the account. The email doesn't have to be associated with an Apple Account." · "User invitations expire 3 days after the invitation is sent." · "If the user is App Manager, Developer, Marketing, Sales, or Customer Support and you didn't give them reports access, select the apps they can access." · "Required role: Account Holder, Admin, or App Manager."
- **Primary evidence for "no Beta App Review"** — "App build statuses" https://developer.apple.com/help/app-store-connect/reference/app-build-statuses/: "Ready to Submit — Your build can be distributed to internal testers, or submitted to TestFlight App Review for external testing or to App Review for customer distribution." · "Waiting for Review — Your build has been submitted to TestFlight App Review and needs approval before external testing can begin."
- "TestFlight overview": "internal testers (up to 100 App Store Connect users with access to your content)" · "If you invite external testers, your beta build may require review."
- https://developer.apple.com/testflight/: "Designate up to 100 members of your development team who hold the Account Holder, Admin, App Manager, Developer, or Marketing role as beta testers."
- Role matrix https://developer.apple.com/support/roles/: "Manage internal TestFlight groups and add builds" and "Manage TestFlight builds" = Account Holder, Admin, App Manager only (Marketing/Developer can test, not manage).
- Secondary (NoMac 2026-09-02, Newly, ptkd): "Internal testing skips review. External testing does not."

## F5 — External TestFlight limits and review

**Verdict: confirmed.**

What I read:
- "Invite external testers" — https://developer.apple.com/help/app-store-connect/test-a-beta-version/invite-external-testers: "You can submit up to six builds for TestFlight App Review within a 24-hour period." · "The first build you submit requires a full review, but later builds for the same version might not." · "You can only have one build of each version in review at a time." · "After uploading your build, you can invite up to 10,000 external testers per app." · "Optionally, under Tester Limit, click Set Limit … Enter a number between 1 and 10,000." · "Builds uploaded as TestFlight Internal Only from Xcode or Xcode Cloud are marked as internal under the build number and can only be added to internal tester groups."
- App Store Review Guidelines https://developer.apple.com/app-store/review/guidelines/ — "Last Updated: October 16, 2026"; §2.2 verbatim: "Demos, betas, and trial versions of your app don't belong on the App Store – use TestFlight instead. Any app submitted for beta distribution via TestFlight should be intended for public distribution and should comply with the App Review Guidelines. … Significant updates to your beta build should be submitted to TestFlight App Review before being distributed to your testers." The 2026-10-16 change list (https://developer.apple.com/news/?id=92th7e5i: 1.2, 2.3.14, 2.5.19, 3.1.1(a), 5, Before/After You Submit) does not touch 2.2 or 4.2.
- "TestFlight overview": "When you add the first build of your app to a group, the build gets sent to App Review to make sure it follows the App Review Guidelines. A review is required only for the first build. Subsequent builds may not require a full review."
- https://developer.apple.com/testflight/: "Your builds are automatically sent for review once they're added to a group." · "Your beta app description and beta app review information are required in order to share your beta with external testers."
- Xcode doc "Distributing your app for beta testing and releases" (doc JSON): "TestFlight Internal Only — Default settings to distribute through TestFlight and restrict access to your team. Use this option to prevent a development build of your app from being submitted to the App Store." · add-internal-testers: "Note: Builds marked as internal can only be added to internal tester groups."
- Extra (feeds F20/omissions): build status "Rejected — Your build was rejected by TestFlight App Review and can no longer be used in TestFlight. Upload a new build to begin testing."

## F7 — TestFlight availability for mainland users

**Verdict: corrected** (facts confirmed; "the only caveat" framing is wrong; IP clause upgraded to a primary source).

Confirmed:
- iTunes lookup `id=899247664&country=cn` (11:33 UTC): resultCount 1, TestFlight 4.4.1, minimumOsVersion 16.0, currentVersionReleaseDate 2026-10-22T16:40:36Z, sellerName "Apple Distribution International", trackViewUrl https://apps.apple.com/cn/app/testflight/id899247664; US storefront identical version. testflight.apple.com: "iPhone or iPad running iOS 16 or iPadOS 16 or later."
- Apple forum thread 682057 "Is Testflight region-locked as per App?" (Jun 2021, `[stale]` 5 years): App Store Connect Engineer (Apple staff badge): "TestFlight does not have territory restrictions. When you send invitations or use a public link, any user from any territory is eligible to be a tester."
- IP clause — **primary**: Apple Legal, "TestFlight & Privacy", https://www.apple.com/legal/privacy/data/en/test-flight/, Published January 27, 2025 (`[stale]` but still the live text): "Apple may use the IP address of your internet connection to approximate your location in order to determine whether certain beta apps that are subject to legal restrictions in some regions can be made available to you." The same page: email-invited testers' "Email address" and "Name" are shared with the developer; "If you accept an invitation to test a beta app through a public link only, your email address and name are not visible to the Application Provider". MacRumors 2025-01-18 confirmed as secondary. The CN TestFlight terms https://www.apple.com/legal/internet-services/itunes/testflight/cn/terms.html (last updated 21/06/2023) still only say "Beta 版 App 可能只会以部分语言或在部分国家或地区提供".

Correction — a second, recurring failure mode exists that the digest does not mention: TestFlight installs fail with "Could not install … The requested app is not available or doesn't exist" when the app's App Store availability/state does not cover the tester's storefront, and mainland users specifically report it:
- Apple forum thread 673860 (Feb 2021–Apr 2023, 30 replies): patrick (Mar '21): "Apple told me that my problem is the current app state (Removed from Sale). I had to release a new app version, after the app state changed to Ready for Sale I also could install TestFlight builds again."; Dmitriy-Mi: "Our problem was with app availability. External testers have Apple accounts which aren't available for this country."
- Apple forum thread 778597 (Mar 2025–Jun 2026, 29 replies, 5.6k views): samkudr (Apr 2025): "in the Monetization -> Pricing and Availability -> App Availability section … 2 countries in the Processing state. If your account is in the 'Processing' country then you can view the app in TestFlight but can't install it."; TumayHeron (Apr 2026): "every build across every one of our apps transitioned to 'Expired' status simultaneously … Internal testers … tapping Install returns … not available or doesn't exist"; (Jun 2026): "It's a known issue on Apple-side". No Apple staff reply in either thread.
- Apple Support Communities CN thread 255646803 (2024-06-14): community user: "有些App在某些地区未上架或者无法上架，在这些地区的TF测试也不可用"; OP: only mainland China showed the restriction. Thread 252420194 (2021-02-07): top answer: switch the Apple ID region from 中国大陆 to US/UK to install, switch back afterwards; another user: when an app is removed from the China region App Store, TestFlight removes it simultaneously.
- Apple's "Manage availability for your app on the App Store" page never mentions TestFlight; default for new apps is "All Countries or Regions … all 175 countries or regions".

Implication: keep the default all-territory availability (China mainland included), never set the app to "Removed from Sale", and expect occasional Apple-side TestFlight outages (the 2025–2026 thread) — have the web-app path as fallback. The sub-claim "so far used only for TikTok in the US" is an absence claim I could not verify.

## F8 — ICP requirement vs TestFlight

**Verdict: confirmed (medium).**

What I read:
- "App information" — https://developer.apple.com/help/app-store-connect/reference/app-information/: "Chinese law requires additional documentation for some apps to be available on the App Store in China mainland. China's Ministry of Industry and Information Technology (MIIT) requires that some apps possess a valid Internet Content Provider (ICP) Filing Number. The ICP number and metadata on the App Information page should match with the information you have filed with MIIT. … Once the provided ICP Filing Number is verified and saved, it will be displayed on your App Store product page." The words TestFlight/beta/tester occur on the page only in the navigation and footer.
- "Manage availability for your app on the App Store": no TestFlight mention; "When you deselect a country or region where your app was available, the app will be removed from the App Store in that country or region."
- Extended ZH search (TestFlight 内测 ICP备案): the 2024 enforcement articles (21经济网 2024-04-04, 腾讯新闻 2024-04-02, IT之家) all concern 上架/提审 to the App Store; TF-signing vendor pages (lianzhushou, haolinsh), CSDN and Zhihu state that TF 内测 itself needs no 备案; no source ties an ICP number to TestFlight. Apple forum thread 743661 (Dec 2023–Mar 2024) likewise.

Caveat inherited from F7: if TestFlight installability follows App Store availability in practice, China mainland must stay selected in availability. Whether App Store Connect allows an app that is never submitted for review to keep China mainland selected without an ICP number cannot be checked without an ASC login — verify on day 1 after enrollment.

## F11 — Xcode 27.2

**Verdict: confirmed.**

What I read:
- iTunes lookup `id=497799835` US and CN (11:33 UTC): version 27.2, fileSizeBytes 3119586528, minimumOsVersion 26.6, currentVersionReleaseDate 2026-10-30T00:02:26Z; releaseNotes: "Xcode 27.2 includes Swift 6.4 and SDKs for iOS 27.2, iPadOS 27.2, tvOS 27.2, watchOS 27.2, visionOS 27.2, and macOS 27.2."
- Xcode 27.2 Release Notes (doc JSON https://developer.apple.com/tutorials/data/documentation/xcode-release-notes/xcode-27_2-release-notes.json): "Xcode 27.2 supports on-device debugging in iOS 17 and later, tvOS 17 and later, watchOS 10 and later, and visionOS." · "Xcode 27.2 requires a Mac running macOS Tahoe 26.6 or later."
- https://developer.apple.com/xcode/system-requirements/: Xcode 27.3 beta / 27.2 / 27.1 / 27 — "macOS Tahoe 26.6 or later"; 26.4.1–26.6 — "macOS Tahoe 26.2 - macOS Tahoe 26.x"; 26–26.3 — "macOS Sequoia 15.6 - macOS Tahoe 26.x".
- Local: macOS 26.7.1 arm64 ⇒ qualifies. On-disk size after install and the iOS 27.2 simulator runtime size remain unpublished by Apple (unverified, as the digest says).

## F12 — Upload requirements

**Verdict: confirmed.**

What I read:
- https://developer.apple.com/news/upcoming-requirements/: "September 9, 2026 — iOS and iPadOS apps uploaded to App Store Connect must target iOS 13 or later." · "April 28, 2026 — Apps uploaded to App Store Connect must be built with Xcode 26 or later using an SDK for iOS 26, iPadOS 26, tvOS 26, visionOS 26, or watchOS 26." The page's 2025-02-18 entry shows Apple's own framing that uploads cover TestFlight: "macOS apps distributed on TestFlight and the App Store shouldn't include the quarantine extended file attribute … you must remove this attribute … in order to upload to App Store Connect."
- https://developer.apple.com/news/?id=ueeok6yw ("Upcoming SDK minimum requirements", 2026-02-03): "Starting April 28, 2026, apps and games uploaded to App Store Connect need to meet the following minimum requirements: iOS and iPadOS apps must be built with the iOS 26 & iPadOS 26 SDK or later".
- https://developer.apple.com/news/?id=k1mtkt1k ("App Store submissions now open for the latest OS releases", 2026-09-09): "Starting April 2027, apps and games uploaded to App Store Connect need to meet the following minimum requirements: iOS and iPadOS apps must be built with the iOS 27 & iPadOS 27 SDK or later". No exact day published yet.
- "Complying with Encryption Export Regulations" (Apple doc JSON): "When you submit your app to TestFlight or the App Store, you upload your app to a server in the United States." — TestFlight builds are uploads.

## F14 — iOS 26 Home Screen web apps; repo state

**Verdict: confirmed** (one quotation in the digest was a paraphrase).

What I read:
- WebKit, "WebKit Features in Safari 26.0", https://webkit.org/blog/17333/ (2025-09-15, `[stale]` 13 months but superseded by nothing): "Now, we are revising the behavior on iOS 26 and iPadOS 26." · "By default, every website added to the Home Screen opens as a web app. If the user prefers to add a bookmark for their browser, they can disable 'Open as Web App' when adding to Home Screen" · "There are now zero requirements for 'installability' in Safari." · "If you include a Web Application Manifest with your site, the benefits it provides will be part of the user's experience. If you define your icons in the manifest, they're used." · "Giving users a web app experience simply no longer requires a manifest file. It's similar to how Home Screen web apps on iOS and iPadOS never required Service Workers". SVG, verbatim: "Safari 26.0 now supports the SVG file format for icons everyplace there are icons in the interface, including favicons." and "For web apps, this same icon represents the website on the user's Home Screen or in their Dock." — the digest's quote "throughout the interface, including favicons and Home Screen app icons" is a paraphrase, not verbatim; the substance (SVG accepted for Home Screen icons) holds.
- Safari 27 line, none of which changes web-app behaviour: "News from WWDC26: WebKit in Safari 27 beta" https://webkit.org/blog/17967/ (2026-06-08) — only "Service Worker static routing API"; "WebKit Features for Safari 27.0" https://webkit.org/blog/18325/ (2026-09-17, read in full, 147k chars) — no Home Screen/web-app items, "Safari 27.0 comes automatically with macOS 27 Golden Gate, iOS 27, iPadOS27 and visionOS 27."; "WebKit Features for Safari 27.1" https://webkit.org/blog/18486/ (2026-10-23) — none; "WebKit Features for Safari 27.2" https://webkit.org/blog/18515/ (2026-10-26, ships with iOS 27.2) — none.
- Local (2026-11-04, `main` @ 9ab13a5): `sed -n 1,25p frontend/index.html` → lines 7–8 two `theme-color` metas, line 10 `application-name`, lines 11–13 `apple-mobile-web-app-capable` / `-status-bar-style` / `-title`, line 14 `<link rel="icon" href="/favicon.svg">`; `ls -la frontend/public` → only `favicon.svg` (248 B); `grep -rniE "manifest|serviceWorker|pushManager|MicroMessenger" frontend/src frontend/index.html frontend/vite.config.*` → no hits; `find frontend -maxdepth 3 -iname '*manifest*' -o -iname 'sw.js' …` → nothing; `backend/wd/main.py:94-95` CSP `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; …`.

## F20 — Guideline 4.2 enforcement and Beta App Review

**Verdict: corrected** (conclusion stands; one key quote is misattributed and the forum evidence is weaker than stated).

What I read:
- Apple forum thread 812889 "App Store Rejection Under Guideline 4.2 (Minimum Functionality) – Hybrid Capacitor App With Native iOS Features and External Booking System" (created Jan '26): OP davidhdavidh2003 describes a Capacitor limo app whose booking/payment runs in a third-party web page (RideBits); the rejection text is the OP's paraphrase ("feedback stating the experience is not sufficiently differentiated from web browsing and that features such as Core Location or sharing alone are not robust enough"), not a pasted Apple message. Replies: "Tomato" (Jan '26, no badge) and "AaryanSolankii" (≈3 weeks ago, no badge): "Right now the core flow (booking and paying) happens inside a RideBits web page, so to the reviewer the app is a browser around someone else's site." **No reply in this thread carries an Apple staff badge** — the digest's "Apple staff saying 'to the reviewer the app is a browser around someone else's site'" is wrong.
- Thread 806726 "Guideline 4.2 - Design - Minimum Functionality" (Nov '25): OP ahomag: "My app has been rejected for the 10th time for the same reason. My app was a web app running in WebView. … The main screen is native … However, 2-3 screens inside open WebView." Reply by **App Review (Apple staff badge)**: "We recommend that you sign up for a session with App Review during the weekly Meet with Apple event…" — confirmed.
- Thread 762413 "Apple Vision Pro: TestFlight external testing submission rejected due to use of Safari" (Aug '24): "Our app has been repeatedly rejected when adding external testers to a TestFlight build due to the use of an 'external' browser for user authentication"; no guideline number cited; **App Review (Apple staff)**: "We believe we have resolved this issue." — confirmed as a Beta App Review rejection on design grounds.
- Guidelines (Last Updated 2026-10-16) §4.2: "Your app should include features, content, and UI that elevate it beyond a repackaged website. If your app is not particularly useful, unique, or 'app-like,' it doesn't belong on the App Store." §4.2.2: "Other than catalogs, apps shouldn't primarily be marketing materials, advertisements, web clippings, content aggregators, or a collection of links." §4.2.7(e): "Thin clients for cloud-based apps are not appropriate for the App Store." §2.2 as in F5. The 2026-10-16 revision touched none of these.
- Extended search for a documented Beta App Review 4.2 rejection of a WebView/Capacitor shell: none found (same as the digest); practitioner guides (NoMac 2026-09-02; ptkd; Newly) say Beta App Review most often rejects under 2.1 for crashes/incomplete apps and that "a WebView-shaped app that would get a 4.2 rejection tends to hit trouble in TestFlight external testing first".
- New fact that strengthens the "never submit the shell to Beta App Review" advice: Apple build status "Rejected — Your build was rejected by TestFlight App Review and can no longer be used in TestFlight. Upload a new build to begin testing." — a rejected build is dead for internal testers too.

Correction summary: replace "Apple staff saying …" with "a community member in thread 812889 saying …"; the App Store 4.2 cases (806726, 812889) and the external-TestFlight design rejection (762413) still support the recommendation that only internal TestFlight is review-free.

---

## Omissions / new findings

1. **Export-compliance gate on every TestFlight build.** Apple marks a fresh build "Missing Compliance — Your build is missing export compliance documentation. Action is needed." (app-build-statuses) and only a "Ready to Submit" build "can be distributed to internal testers". Fix once in the Capacitor Xcode project: `ITSAppUsesNonExemptEncryption = NO` in Info.plist ("Complying with Encryption Export Regulations": HTTPS via the OS is "exempt from export documentation upload requirements"; "Provide export compliance information for beta builds": "Specify encryption use for your build to avoid the beta being marked as Missing Compliance", required role Account Holder/Admin/App Manager). Otherwise each of the 90-day re-uploads stalls until someone answers the questionnaire in ASC.
2. **TestFlight installability is coupled to App Store availability/app state in practice, and Apple had a months-long TestFlight outage in 2025–2026.** See F7: "Removed from Sale" apps, territories stuck in "Processing", and apps not offered on the CN storefront produce "The requested app is not available or doesn't exist" (forum 673860, 778597; Apple Support Communities CN 255646803, 252420194). Keep the default "All Countries or Regions" (175, China mainland included), never remove China mainland, and keep the Home-Screen web app as the fallback channel.
3. **A Beta App Review rejection kills the build for everyone.** "Rejected — Your build was rejected by TestFlight App Review and can no longer be used in TestFlight. Upload a new build to begin testing." (app-build-statuses). Combined with §2.2 ("Significant updates to your beta build should be submitted to TestFlight App Review before being distributed to your testers"), the practical rule is: upload the shell as "TestFlight Internal Only" and never add it to an external group even to "try".
4. **Internal-tester invitations are bound to one Apple Account.** Apple: "The users will be directed to accept the invitation using the TestFlight app on their device or with a redemption code." (add-internal-testers); the ASC invite goes to the e-mail you enter and that e-mail becomes the tester's Apple Account; forum 853308 (Oct 2026, unanswered): "TestFlight says the currently signed-in Apple Account does not match the account associated with the invitation"; forum 738484 (2023–2024): invites route to the Apple Account e-mail, not an alias. Also, per Apple's "TestFlight & Privacy" (2025-01-27), e-mail-invited testers' name and e-mail are visible to the developer (only public-link testers are hidden). Onboarding text for the friends must say: accept with the Apple Account whose e-mail received the invite (or use the redemption code), and that is the account to sign into TestFlight with.
5. **Safari 27.x shipped (iOS 27, 2026-09-17; 27.1 2026-10-23; 27.2 2026-10-26) with no change to Home-Screen web-app behaviour** — the digest only checked the June beta post. Consequence for F21: the China iOS-version mix quoted there (Aug/Sep 2026) predates iOS 27; by now a large share of "iOS 26" devices are on iOS 27, which behaves identically for Add-to-Home-Screen; the iOS 17 deployment-target recommendation is unaffected.
6. **The ¥688 membership is an auto-renewing App Store subscription with app-only renewal/verification mechanics.** "会员资格会每年续订，直至你取消为止。" · "你可以在每年续订日期的前一天在"设置"中取消订阅。" · "Apple Developer App 中的会员资格续订功能目前不支持通过 Apple 开发者网站完成注册的账户。" · "某些流程要求必须在此 App 中完成身份验证 … (例如，续订会员资格、接受账户持有人转让 …)". Budget it as a subscription on the owner's Apple Account (Alipay/WeChat Pay/card, never balance), and keep the Apple Developer app installed on the enrolling Mac for later identity re-verification.

Raw artefacts: `scratchpad/quick/verify/ios-raw/{testflight,appledev,xcode}-{cn,us}.json`, `xcode272.json`, `distrib.json`, `encexport.json`.
