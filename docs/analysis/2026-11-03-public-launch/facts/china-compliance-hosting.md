# Fact slice: china-compliance-hosting (31 findings)

## Summary

For a non-commercial indie operator, the mainland-hosted + 备案 route is not realistic with Claude in the loop: ICP备案 (individual, non-commercial) is obtainable in roughly 1–4 weeks, but a free 中考/高考 vocabulary site risks a K-12 校外培训 前置审批 demand that an individual cannot satisfy, the iOS app additionally needs an APP备案号 (which Apple has required for the China storefront since 2023-09-29) tied to mainland hosting, 教育App备案 is organisation-only in practice (单位证明 + ICP + 等保 prerequisites), and the generative-AI regime offers no 登记 path for an app built on a foreign model that has no mainland 备案 — practitioners confirm GPT/Claude cannot be filed, and relaying Anthropic traffic into the mainland is a legal grey zone that also violates Anthropic's regional policy. Hong Kong removes the ICP burden but not the AI problem: Hong Kong is absent from Anthropic's supported-regions list (Japan, Singapore, Taiwan are present) and HK IPs are reported blocked, so a relay would still be needed. The realistic combination is a Singapore/Tokyo VPS (Alibaba Cloud SAS $15/mo, Tencent Lighthouse $8.50/mo, Lightsail $24/mo for 2 vCPU/4 GB; mainland latency ~60–120 ms SG, ~30–60 ms Tokyo), web-first, with Claude accessed through an API key rather than the operator's subscription OAuth — Anthropic's Claude Code legal page explicitly forbids routing requests through Pro/Max credentials on behalf of users, and the runner already passes ANTHROPIC_API_KEY/ANTHROPIC_BASE_URL through (backend/wd/ai/runner.py:49-62). That setup needs no 备案 and no 备案号 footer, costs only the risk of GFW IP/SNI blocking (mitigable by IP change) and leaves mainland users VPN-free unless blocked; its compliance work is PIPL hygiene the app currently lacks (no privacy notice, no consent, no under-14 guardian flow — backend/wd/schemas.py:179-184, frontend/src/pages/RegisterPage.tsx:45-47) plus a visible per-block AI label, since the current disclosure lives only on the Settings page (frontend/src/pages/SettingsPage.tsx:688-689) rather than beside the text as the 2025 标识办法 Art. 4 contemplates. The iOS app is the casualty of this choice: without 备案 it cannot be on the China App Store, so mainland distribution is limited to TestFlight (no territory restriction per Apple staff, 10,000 testers, 90-day builds) or non-China storefronts that mainland Apple IDs cannot use. A mainland server would also lose the Wikimedia image pipeline (upload.wikimedia.org IP-blocked since 2019) and the Claude SVG fallback at once. A separate, unresolved issue is that the operator's own machine gets 403 'Request not allowed' from api.anthropic.com without a tunnel, which suggests the operator is physically in an unsupported region — Anthropic's policy prohibits use from there regardless of where the server sits.

## Findings

### [china-compliance-hosting-1] (high) Code baseline — AI disclosure placement

- CLAIM: The only text-related AI disclosure is one line in Settings → 关于与数据来源 ('例句、搭配与记忆提示由 AI 生成，仅供学习参考'); the study card labels 例句/搭配/记忆 carry no AI marker; images get a caption 'AI 生成示意图' only for Claude-drawn SVGs. README's claim that the UI shows 「例句由 AI 生成」 does not match the actual string or placement.
- EVIDENCE: frontend/src/i18n/zh.ts:86 (string); frontend/src/pages/SettingsPage.tsx:688-689 (only render site, found by grep 2026-11-03); frontend/src/i18n/zh.ts:39 (card labels without AI tag); frontend/src/components/study/WordImage.tsx:27-28 and zh.ts:54 (image caption); README.md:105 and docs/FRONTEND.md:155 (docs wording).
- IMPLICATION: If 标识办法 Art. 4 applies, a settings-page disclaimer is unlikely to qualify as a label 'at the start/end/middle of the text or beside it in the interface'; a per-block 'AI 生成' marker on the card and in e-mail/webhook pushes, plus a user-agreement clause (Art. 8), would be needed for any mainland-facing public release.

### [china-compliance-hosting-2] (high) Code baseline — registration, consent, minors

- CLAIM: Registration collects username, password, optional display name/e-mail and an invite code; there is no privacy-policy page, no terms/consent checkbox, no age or birthdate field and no guardian flow. Default registration mode is invite-only; a public site needs WD_REGISTRATION_MODE=open.
- EVIDENCE: backend/wd/schemas.py:179-184 (RegisterRequest fields); backend/wd/routers/auth.py:79-116; frontend/src/pages/RegisterPage.tsx:45-47,84-86; grep of frontend/src for 隐私|协议|同意 returned no matches (2026-11-03); backend/wd/config.py:36,77,321; docs/DEPLOY.md:311.
- IMPLICATION: PIPL Art. 13 (consent basis), Art. 17 (notice) and Art. 31 (guardian consent + special rules for under-14s) are unmet today; with 中考 word lists the audience includes 12–13-year-olds, so an age gate or 14+ restriction is a prerequisite for a public deployment aimed at mainland users, wherever hosted.

### [china-compliance-hosting-3] (high) Code baseline — data-subject rights already covered

- CLAIM: Self-service export (CSV/JSON incl. 365 days of review logs) and password-confirmed account deletion with cascade exist; the documented personal-data set is username, optional e-mail, display name, learning history, notes; sessions also store the client IP; no third-party analytics; images are self-hosted so providers never see end-user IPs; Claude never receives usernames or e-mails.
- EVIDENCE: backend/wd/routers/account.py:89-111 (DELETE /api/account), :174-193 (GET /api/account/export); docs/DESIGN.md:572; backend/wd/deps.py:79 (sessions.ip).
- IMPLICATION: PIPL Art. 45/47 rights are technically satisfied; the missing pieces are the notice (purposes, retention periods, the IP field) and consent capture, not new endpoints.

### [china-compliance-hosting-4] (high) Code baseline — how Claude is reached

- CLAIM: AI content is produced by spawning the Claude Code CLI ('claude -p … --output-format json …') authenticated by the operator's subscription OAuth login; the docs state there is no ANTHROPIC_API_KEY and that --bare must never be used because it disables OAuth. The runner's child-environment allow-list passes through ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, HTTP_PROXY/HTTPS_PROXY/NO_PROXY and SSL_CERT_* if set, but not the Bedrock/Vertex variables (CLAUDE_CODE_USE_BEDROCK, AWS_*).
- EVIDENCE: docs/CLAUDE_INTEGRATION.md §1.1 and §1.3 (invocation, OAuth rule, env allow-list); backend/wd/ai/runner.py:49-62 (PASSTHROUGH_ENV), :158-174 (claude_env); backend/wd/config.py:85-88 (claude_bin/home/path), :90 (model 'sonnet'), :103-104 ($3/day, $40/month caps); docs/DEPLOY.md:1.
- IMPLICATION: Moving to API-key billing or an Anthropic-compatible gateway (ANTHROPIC_BASE_URL) is a .env change; a Bedrock/Vertex route needs a small code change to the allow-list. Budget caps exist, but per-token API pricing replaces the flat subscription.

### [china-compliance-hosting-5] (medium) Operator network reality

- CLAIM: From the operator's own network api.anthropic.com answers 403 'Request not allowed' directly and only works through a hand-started SSH SOCKS5 tunnel (privoxy 127.0.0.1:8118 → SOCKS 1080), exported only inside bin/claude-wrapper; Wikimedia is reachable directly, Openverse often times out.
- EVIDENCE: /Users/sqin/.claude/projects/-Users-sqin-word-dance/memory/macos-local-install.md ('Network:' bullet, written 2026-11-02).
- IMPLICATION: A 403 at the Anthropic edge is the signature of its geo-block, which implies the operator is physically in an unsupported region; Anthropic's policy prohibits 'use by persons while physically located in an unsupported region', so the operator's personal access — and any public service built on it — is already outside policy irrespective of server location. This needs to be confirmed with the owner.

### [china-compliance-hosting-6] (high) Image pipeline vs. mainland hosting

- CLAIM: Images are fetched server-side from commons.wikimedia.org (API) and Wikimedia thumbnail hosts, api.openverse.org, Pexels and Pixabay, with DNS pinning + SNI that an HTTP proxy breaks; all *.wikipedia.org has been blocked in mainland China since 2019-04-23 (DNS injection, SNI filtering), Wikimedia Commons since June/December 2019, and upload.wikimedia.org by IP since December 2019.
- EVIDENCE: backend/wd/images/providers/wikimedia.py:10,26; openverse.py:25; pexels.py:17; pixabay.py:18; backend/wd/images/fetch.py:6,113,211; memory file (proxy breaks pinning → paid SVG fallback); https://en.wikipedia.org/wiki/Wikimedia_censorship_in_mainland_China (retrieved 2026-11-03); https://ooni.org/post/2019-china-wikipedia-blocking/ (2019-05).
- IMPLICATION: On a mainland server the primary image provider and the Claude SVG fallback (backend/wd/config.py:113 svg_via_claude=True) fail together; mainland hosting would require relaying images or swapping providers, not just the AI calls.

### [china-compliance-hosting-7] (high) ICP备案 — legal basis and footer rule

- CLAIM: 互联网信息服务管理办法 (as amended by State Council decision of 2024-12-06): Art. 4 — non-commercial services are subject to 备案 and '未取得许可或者未履行备案手续的，不得从事互联网信息服务'; Art. 12 — the 备案编号 must appear 在网站主页的显著位置; Art. 22 — failure to display is fined RMB 5,000–50,000 after an order to correct.
- EVIDENCE: https://zh.wikisource.org/zh/互联网信息服务管理办法_(2024年) (retrieved 2026-11-03).
- IMPLICATION: Any mainland-hosted web deployment needs the 备案 before going live and a footer with the number linked to beian.miit.gov.cn; neither applies to a site hosted outside the mainland.

### [china-compliance-hosting-8] (medium) ICP备案 — who files, what it takes, how long

- CLAIM: Both companies and 中国籍 individuals who pass identity verification can be 备案 subjects; 非经营性互联网信息服务备案管理办法 as revised by 工信部令第68号 (effective 2024-01-18) obliges the 省通信管理局 to file within 20 working days of complete materials; cloud providers report 1–2 working days of their own 初审 plus 1–20 working days at the 管局 (Azure China: 3 days in 上海 up to ~3 weeks in 甘肃/云南). Prerequisites: a mainland-region server bought for ≥3 months (one cloud account = one 主体; up to 5 sites/apps per ECS), a real-named domain at a Chinese registrar, and video/ID verification; a site whose main host is outside the mainland cannot be filed.
- EVIDENCE: https://www.gov.cn/gongbao/2024/issue_11286/202404/content_6945590.html (20-working-day clause; retrieved 2026-11-03); https://www.azure.cn/support/icp/icp-faq/ (page dated 2024-12-31); https://support.huaweicloud.com/prepare-icp/icp_02_0003.html (updated 2026-09-28); https://www.secrss.com/articles/58923 (individuals as subjects; via search 2026-11-03); help.aliyun.com/document_detail/116583.htm (1–20 working days; search summary only, page not fetchable here).
- IMPLICATION: Budget 2–5 weeks and a prepaid mainland VPS; the filing binds the domain to the mainland host, so a hybrid 'mainland front, overseas AI' design means the mainland box is the 备案 subject.

### [china-compliance-hosting-9] (medium) ICP备案 — limits on an individual filing

- CLAIM: Cloud providers reject personal filings whose sites show enterprise or commercial content ('个人备案网站只能是个人介绍或文章分享等内容，个人网站存在企业相关信息会不合格'); site names may not contain words such as 教育/新闻/出版/医疗 without clearance from the relevant authority; Huawei Cloud's 前置审批 table (updated 2025-12-04) lists '校外培训（高中及以下）' as requiring a pre-approval document from the 省/市/区教育行政部门 (职业类培训 exempt), while Azure China's FAQ (2024-12-31) says general 教育 and 医疗保健 no longer need 前置审批; several provinces (北京、广东、四川 named in provider guidance) apply the K-12 training rule.
- EVIDENCE: https://developer.aliyun.com/ask/7221 (via search 2026-11-03); https://support.huaweicloud.com/icp_faq/icp_05_0116.html (2025-03-07); https://support.huaweicloud.com/prepare-icp/zh-cn_topic_0000002085124433.html (2025-12-04); https://www.azure.cn/support/icp/icp-faq/ (2024-12-31); help.aliyun.com/zh/icp-filing/user-guide/pre-approvals (search summary).
- IMPLICATION: word-Dance advertises 中考/高考 word lists (frontend/src/i18n/zh.ts:86) and targets 初中/高中 students, so a 管局 reviewer may read it as K-12 校外培训-adjacent and ask for an education-department pre-approval that an individual cannot obtain; the safe individual filing is 'personal study-notes site', which constrains how the service may describe itself.

### [china-compliance-hosting-10] (medium) ICP备案 — consequences of running without it on a mainland host

- CLAIM: Tencent Cloud's documentation states that a domain resolved to a mainland CVM without a Tencent-side 备案 (or 接入备案) is detected by its unfiled-domain monitoring, blocked and redirected to a fixed notice page, and that HTTPS access is blocked the same way; Alibaba Cloud operates the equivalent block on 80/443.
- EVIDENCE: https://cloud.tencent.com/document/faq/243/20220 and https://cloud.tencent.com/document/product/243/18907 (official FAQ text via search 2026-11-03; page body did not render in fetch); Aliyun equivalent help.aliyun.com/document_detail/36890.html (not fetchable here).
- IMPLICATION: There is no 'launch first, file later' option on mainland clouds; the public URL is dead until the 管局 number arrives.

### [china-compliance-hosting-11] (medium) 公安联网备案 (second filing)

- CLAIM: 计算机信息网络国际联网安全保护管理办法 Art. 12 requires registration with the provincial 公安 within 30 days of the network going live; the 公安部网安局 Q&A (2024-09-13) says an individual 主体 is reviewed by the 网安部门 of the person's 常住地, and the 公安备案编号 HTML must be pasted at the bottom of the page; it applies to websites and APPs after the ICP number is issued.
- EVIDENCE: https://zh.wikisource.org/zh-hans/计算机信息网络国际联网安全保护管理办法 (Art. 12); https://m.thepaper.cn/newsDetail_forward_28754109 (公安部网安局, 2024-09-13).
- IMPLICATION: A mainland deployment carries two filings and two footer numbers; an overseas deployment carries neither.

### [china-compliance-hosting-12] (high) APP备案 (MIIT 2023) — scope and display rule

- CLAIM: 工信部信管〔2023〕105号 (issued 2023-07-21, published 2023-08-04): APP 主办者 providing internet information services in China must file; '未履行备案手续的，不得从事APP互联网信息服务'; app stores and hosting providers '不得为未履行备案手续的APP提供网络接入、分发、预置等服务'; 'APP主办者应当在APP显著位置标明其备案编号，并在备案编号下方按要求链接备案系统网址'; filing runs through the ICP system via the hosting provider/distribution platform; timeline: existing apps 2023-09→2024-03, inspections 2024-04→06, 常态化 from 2024-07. Individuals can be APP 主办者; the APP number is the site number plus 'A' (e.g. 京ICP备02000001号-2A) shown in 设置/介绍.
- EVIDENCE: https://m.thepaper.cn/newsDetail_forward_24155262 (notice text; retrieved 2026-11-03); https://www.secrss.com/articles/58923; https://www.azure.cn/support/icp/icp-faq/ (2024-12-31).
- IMPLICATION: An APP备案号 presupposes a mainland-hosted backend with a filed domain; an iOS client talking to a Singapore server cannot be filed, so it cannot enter the China App Store.

### [china-compliance-hosting-13] (high) Apple China App Store — ICP enforcement

- CLAIM: Since 2023-09-29 new apps for the China mainland storefront must supply an ICP filing number in App Store Connect; from 2024-04-01 unfiled apps cannot ship updates and face removal; Apple's App Store Connect help says the ICP number and metadata must match the MIIT record and the verified number is shown on the product page; developers who remove China mainland from availability are not subject to it.
- EVIDENCE: https://developer.apple.com/help/app-store-connect/reference/app-information/ (retrieved 2026-11-03); https://appleinsider.com/articles/23/10/03/apple-bows-to-china-starts-enforcing-app-store-rules (2023-10-03); https://appinchina.co/blog/the-complete-guide-to-chinas-mobile-app-filing/; https://developer.apple.com/forums/thread/743661.
- IMPLICATION: For the iOS plan, China-storefront listing is gated on the same mainland hosting + 备案 chain as the website; mainland users with China Apple IDs cannot install from other storefronts.

### [china-compliance-hosting-14] (medium) Apple TestFlight as a non-store path

- CLAIM: An App Store Connect engineer stated (June 2021) that 'TestFlight does not have territory restrictions. When you send invitations or use a public link, any user from any territory is eligible to be a tester'; public links allow up to 10,000 testers and builds expire after 90 days. No Apple document ties TestFlight to the ICP requirement.
- EVIDENCE: https://developer.apple.com/forums/thread/682057 (Apple staff reply, 2021-06); https://developer.apple.com/testflight/ (retrieved 2026-11-03).
- IMPLICATION: A mainland iPhone user can run the app via TestFlight without any 备案 on Apple's side, at the cost of 90-day rebuilds and a beta-only experience; legally it is still 'providing an APP service' under the MIIT notice, so it is a grey channel, not a compliant one.

### [china-compliance-hosting-15] (medium) Apple China App Store — generative-AI features

- CLAIM: Apple removed 100+ generative-AI apps from the China storefront around 2023-08-01 citing government orders; Apple Intelligence itself only completed 大模型备案 on 2026-07-08 (number Shanghai-AppleZhiNeng-202506160057 shown on devices); practitioner guides say mainland stores 'usually ask for model filing information during listing review' for AI-feature apps and that only domestically filed models are accepted; no Apple document naming a dedicated gen-AI 备案 field in App Store Connect was found.
- EVIDENCE: https://techcrunch.com/2023/08/01/generative-ai-services-pulled-from-apple-app-store-in-china-ahead-of-new-regulations (2023-08-01); https://www.guancha.cn/economy/2026_07_15_823819.shtml (2026-07-15); https://tech.ifeng.com/c/8xDRMSyCozg; https://docs.apiyi.com/en/faq/overseas-model-compliance (vendor FAQ, undated); https://appinchina.co/blog/the-complete-guide-to-chinas-aigc-registration/ (2026-08-10).
- IMPLICATION: Even with ICP/APP 备案 in hand, an app whose content is generated by Claude has no 备案/登记 number to show a reviewer; the realistic mainland-store path is a domestic 备案'd model plus 登记.

### [china-compliance-hosting-16] (high) Generative-AI rules — scope has no small/free exemption

- CLAIM: 生成式人工智能服务管理暂行办法 (effective 2023-08-15) applies to anyone — 组织 or 个人, including via API — who uses generative AI to provide generated text to the 境内公众; the only carve-out is R&D/application that does not serve the public; Art. 17 requires 安全评估 and 算法备案 for services 'with 舆论属性或者社会动员能力'; Art. 20 lets the CAC order technical measures against offshore services that do not comply; Art. 23 requires licences where other laws demand them.
- EVIDENCE: https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm (retrieved 2026-11-03).
- IMPLICATION: A free hobby app is inside scope on its face; what differs is enforcement — against an overseas site the instrument is blocking (Art. 20/GFW), against a mainland site or app-store listing it is filing demands and takedown.

### [china-compliance-hosting-17] (high) Generative-AI rules — what 舆论属性 means and the filing clocks

- CLAIM: The 2018 安全评估规定 Art. 2 defines 舆论属性/社会动员能力 services as 论坛、博客、微博客、聊天室、通讯群组、公众账号、短视频、网络直播、信息分享、小程序等信息服务或者附设相应功能, with Art. 3 triggering assessments on new functions or significant user growth, filed via the 全国互联网安全管理服务平台; 算法推荐管理规定 (effective 2022-03-01) covers 生成合成类 algorithms (Art. 2), requires such providers to 备案 within 10 working days of starting service (Art. 24) and to display the 备案编号 in the site/app (Art. 26); 深度合成规定 (effective 2023-01-10) Art. 19 repeats the 备案 duty and Art. 23 says providers include individuals.
- EVIDENCE: https://www.cac.gov.cn/2018-11/15/c_1123716072.htm; https://www.cac.gov.cn/2022-01/04/c_1642894606364259.htm; https://www.cac.gov.cn/2022-12/11/c_1672221949354811.htm (all retrieved 2026-11-03).
- IMPLICATION: Regulators treat essentially all public-facing gen-AI as having 舆论属性; the shared word library (user-added words published to everyone) adds a '信息分享' flavour even though notes stay private (docs/DESIGN.md:572), so a mainland deployment would be expected to hold both an 算法备案 and a gen-AI 备案/登记.

### [china-compliance-hosting-18] (medium) Generative-AI rules — 备案 vs 登记 and the foreign-model dead end

- CLAIM: CAC practice: 备案 is for the model/service provider; 登记 (handled by the local 网信办, yielding an 上线编号) is for applications that call an already-备案'd model via API; applications must 公示 the model name and 备案号/上线编号 'in a prominent place or product details page'; as of 2025-12-31, 748 services were 备案'd and 435 applications 登记'd. Practitioner sources state that overseas models such as GPT/Claude cannot obtain a mainland filing, so no 登记 is possible for an app built on them, that 登记 presumes a China applicant entity, and that the workaround of filing a domestic model while running a foreign one backend is a grey area that risks being ruled non-compliant.
- EVIDENCE: https://www.cac.gov.cn/2024-04/02/c_1713729983803145.htm (公示 requirement); https://www.thepaper.cn/newsdetail_forward_32368980 (CAC announcement 2026-01-12); https://appinchina.co/blog/the-complete-guide-to-chinas-aigc-registration/ (2026-08-10); https://docs.apiyi.com/en/faq/overseas-model-compliance (vendor FAQ).
- IMPLICATION: A compliant mainland edition means replacing Claude with a 备案'd domestic model (Qwen/DeepSeek/Doubao class) and a 登记 under an entity; keeping Claude means staying outside the mainland filing system entirely.

### [china-compliance-hosting-19] (medium) AI-content labelling (2025) — applicability and sufficiency of the current label

- CLAIM: 标识办法 (国信办通字〔2025〕2号, issued 2025-03-07, effective 2025-09-01) applies to providers falling under the algorithm/deep-synthesis/gen-AI rules; for text whose service is of the 深度合成规定 Art. 17(1) type ('智能对话、智能写作等模拟自然人进行文本的生成或者编辑服务'), Art. 4 requires explicit labels 在文本的起始、末尾或者中间适当位置 or 在交互场景界面、文字周边添加显著的提示标识; Art. 5 requires implicit labels in 文件元数据 (provider name/code, content number); Art. 8 requires the labelling method to be explained in the 用户协议; the mandatory standard GB 45438-2025 took effect the same day; on 2025-11-25 the CAC announced warnings, rectification orders and app-store removals against apps violating the measures.
- EVIDENCE: https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm (text); https://www.cac.gov.cn/2022-12/11/c_1672221949354811.htm (Art. 17); https://www.news.cn/tech/20250319/a572ec4366f149c1b0b04a07ebf4931b/c.html (standard, 2025-03-19); https://digitalpolicyalert.org/event/35745-… (enforcement 2025-11-25; details paywalled).
- IMPLICATION: Whether pre-generated example sentences served without a user prompt count as an 智能写作 service is arguable, but the cheap compliant posture is a visible 'AI 生成' marker beside each AI block (card, e-mail, webhook text) plus a user-agreement clause; the implicit-metadata duty is moot for in-page text but would bite if AI text were ever exported as files.

### [china-compliance-hosting-20] (medium) Mainland relay of Anthropic traffic — legality and policy

- CLAIM: 工信部信管函〔2017〕32号 (2017-01-17) bars establishing or leasing 专线（含虚拟专用网络VPN）等其他信道 for 跨境经营活动 without telecom-authority approval, addressed to carriers/IDC/ISP operators rather than end users; a law-firm analysis (Han Kun, 2026-08-05) says mainland AI-API relay operations can implicate gen-AI 备案/登记, 算法备案, value-added telecom licensing, data-export rules and content-moderation duties, distinguishing integrating a model into one's own product from reselling access and public from closed-client use; a relay vendor concedes the practice sits in a grey area. Separately, Anthropic's policy prohibits use from unsupported regions and via entities controlled from them.
- EVIDENCE: https://www.cac.gov.cn/2017-01/23/c_1120366809.htm; https://hankunlaw.com/portal/article/index/cid/8/id/17050.html (2026-08-05); https://docs.apiyi.com/en/faq/overseas-model-compliance; https://www.anthropic.com/supported-countries (retrieved 2026-11-03).
- IMPLICATION: A mainland server calling a self-hosted HK/SG relay is not literally a VPN and, as a single-operator non-commercial integration, sits at the low-risk end of the grey zone under PRC rules — but it is designed to evade Anthropic's geo-policy, so it is non-compliant on the Anthropic side regardless and could be cut off without notice.

### [china-compliance-hosting-21] (high) 教育App备案 (教育部 2019)

- CLAIM: 教育移动互联网应用程序备案管理办法 (教技厅〔2019〕3号, 2019-11-11) defines 教育移动应用 as mobile apps whose main users are 教职工、学生、家长 and whose main scenario is 教育、学习; Art. 9 requires 提供者备案 only after completing ICP备案 and 网络安全等级保护定级备案; Art. 10 lists 教育行政部门、学校、企业和社会组织 as filers (individuals are not mentioned); the filing form (附件1) asks for 单位名称/单位性质/单位有效证明 (组织机构代码证书、统一社会信用代码证书、营业执照…), ICP备案编号, 等级保护备案号 and checkboxes for 论坛/收费/直播/中小学学科培训; Art. 14 requires the 备案 info to be shown in-app; Art. 16 enlists 网信、电信、公安 to make app stores enforce it; Art. 24 blacklists non-compliant providers for six months.
- EVIDENCE: https://cdn.jiemodui.com/pdf/20191203RecordManagement.pdf (full text; extracted with pdftotext to /private/tmp/claude-501/-Users-sqin-word-dance/729429d5-a7a1-4def-84e7-dc3ba571c437/scratchpad/eduapp/faq.txt lines 43-76, 84-120, 134-195); https://www.elawcn.com/rule/2019/1125/490.html; https://m.thepaper.cn/newsDetail_forward_5260418 (2019-12).
- IMPLICATION: The measure covers mobile apps, not websites, so it bites the iOS app rather than the web front end; in practice it is organisation-only (单位证明) and stacks 等保 定级备案 on top of ICP — a third filing an individual cannot realistically complete.

### [china-compliance-hosting-22] (medium) 双减 and K-12 learning apps in stores

- CLAIM: The 2021-12-13 教育部办公厅 notice took 拍照搜题-type homework apps offline pending rectification, stopped accepting 学前线上培训App filings, and suspended 备案 for 中小学线上学科类培训App until provincial approval of the training provider; the targets were training providers and answer-giving features, not self-study tool apps, and no source was found showing K-12 vocabulary apps delisted as a category. The 2019 filing form nonetheless tracks a '中小学学科培训' feature flag.
- EVIDENCE: https://www.xinhuanet.com/politics/2021-12/30/c_1128214944.htm; https://www.chinanews.com.cn/sh/2021/12-21/9634737.shtml; https://www.woshipm.com/it/5254403.html (2022-01); form text in the extracted PDF above.
- IMPLICATION: A free vocabulary trainer with no courses, live teaching or fees is not a 校外培训机构 under 双减, so store delisting on that ground is unlikely; the exposure is instead the ICP/教育App filing reviewers' reading of 中考/高考 positioning.

### [china-compliance-hosting-23] (high) PIPL and the 2025 网络数据安全管理条例 — minimal obligations

- CLAIM: PIPL (effective 2021-11-01) Art. 3(2) applies to overseas processing aimed at providing services to 境内自然人; Art. 13 requires a lawful basis (consent); Art. 17 a prominent, clear notice (identity, purposes, methods, categories, retention, rights procedures); Art. 28 classes under-14s' data as sensitive; Art. 31 requires 父母或者其他监护人的同意 and 专门的个人信息处理规则; Arts. 45/47 give access/copy/portability and deletion rights; Art. 53 requires an overseas processor to 在境内设立专门机构或者指定代表 and report it; Art. 66 sets fines up to RMB 1M (50M/5% for serious cases). 网络数据安全管理条例 (国务院令第790号, effective 2025-01-01) restates this: Art. 2 extraterritorial reach, Art. 21 contents of the processing rules incl. separate rules for under-14s, Art. 22 guardian consent, Art. 26 reporting the 专门机构/代表 to the 设区的市级网信部门.
- EVIDENCE: https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm; https://www.gov.cn/zhengce/content/202409/content_6977766.htm (both retrieved 2026-11-03).
- IMPLICATION: The hobby-app minimum is: a Chinese privacy notice with retention periods, consent at registration, an age gate with guardian consent (or 14+), and the existing export/delete; the Art. 53 'representative in China' duty applies to an overseas-hosted service in theory and is widely ignored by small foreign sites — a known, low-enforcement gap to disclose to the owner rather than solve.

### [china-compliance-hosting-24] (medium) Cross-border data rules when hosting outside the mainland

- CLAIM: 促进和规范数据跨境流动规定 (effective 2024-03-22) Art. 5 exempts non-CIIO processors that have cumulatively transferred personal information of fewer than 100,000 individuals (no sensitive data) since 1 January from 安全评估/标准合同/认证; 100k–1M requires a 标准合同 or certification, ≥1M a security assessment, and any sensitive data of ≥10k people a 标准合同. These mechanisms address 数据处理者 transferring data out of China; an overseas server collecting directly from mainland users is governed by PIPL Art. 3(2)/53 rather than by the export mechanisms, which is unsettled in practice.
- EVIDENCE: https://www.cac.gov.cn/2024-03/22/c_1712776611775634.htm (retrieved 2026-11-03); PIPL Arts. 3, 53 as above.
- IMPLICATION: At hobby scale (username/e-mail/learning history, no sensitive data if under-14s are excluded) the export-mechanism thresholds are not reached; note that under-14 users' data is sensitive and would count toward the 10k sensitive-data trigger.

### [china-compliance-hosting-25] (high) Anthropic availability — regions

- CLAIM: Anthropic's supported-regions page (as retrieved 2026-11-03; the page carries an effective date of Nov 12, 2026) lists Japan, Singapore and Taiwan but not China, Hong Kong or Macau; the policy covers Claude.ai, Claude Code, Cowork, the API/developer platform and Claude models offered through cloud platforms and resellers; it prohibits use by persons physically located in an unsupported region, by entities incorporated/headquartered there, and by entities majority-owned or controlled from there. Secondary sources report Hong Kong IPs are turned away with 'Claude is only available in certain regions'.
- EVIDENCE: https://www.anthropic.com/supported-countries (retrieved 2026-11-03); https://www.eigent.ai/blog/how-to-use-claude-in-hong-kong (secondary).
- IMPLICATION: A Hong Kong server offers no ICP burden but no Claude either (and Bedrock/Vertex in HK are covered by the same policy); Singapore/Tokyo servers are inside policy for the server — the open question is the operator's own location.

### [china-compliance-hosting-26] (high) Anthropic terms — subscription OAuth cannot back a multi-user service

- CLAIM: Claude Code's legal page states OAuth is 'intended exclusively for purchasers of Claude Free, Pro, Max, Ultra, Team, and Enterprise subscription plans … to support ordinary use of Claude Code', that developers building products 'should use API key authentication', that 'Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users', and that Anthropic may enforce without notice; press reports describe server-side enforcement from January 2026 and a Consumer-Terms update in February 2026.
- EVIDENCE: https://code.claude.com/docs/en/legal-and-compliance (retrieved 2026-11-03); https://gigazine.net/gsc_news/en/20260220-anthropic-third-party-block (2026-02-20).
- IMPLICATION: The design in docs/CLAUDE_INTEGRATION.md (operator OAuth, never --bare) is acceptable for a personal instance but not for a public service; the public deployment must authenticate the CLI with an API key (already passed through at backend/wd/ai/runner.py:54) and budget per-token spend.

### [china-compliance-hosting-27] (high) Alternative inference route via AWS Bedrock

- CLAIM: Claude Code can run against Amazon Bedrock with CLAUDE_CODE_USE_BEDROCK=1, AWS_REGION and AWS credentials or AWS_BEARER_TOKEN_BEDROCK, with model IDs pinned via ANTHROPIC_MODEL/ANTHROPIC_DEFAULT_*_MODEL (apac. prefix for ap-* regions); none of these variables are in the runner's pass-through list.
- EVIDENCE: https://code.claude.com/docs/en/amazon-bedrock (retrieved 2026-11-03); backend/wd/ai/runner.py:49-62.
- IMPLICATION: A Tokyo/Singapore deployment could bill through AWS instead of an Anthropic Console account, but still falls under Anthropic's regional policy and needs an allow-list code change.

### [china-compliance-hosting-28] (medium) Hosting prices (2 vCPU / 4 GB)

- CLAIM: Alibaba Cloud Simple Application Server: $15/month in Singapore, Tokyo and Hong Kong (15 Mbit/s, 4 TB). Tencent Cloud Lighthouse: $8.50/month Singapore/Tokyo, $15.00/month Hong Kong (30 Mbps, ~1.5–2 TB; doc updated 2026-09-24). AWS Lightsail: $24/month (80 GB SSD, 4 TB; some APAC regions halve the transfer). Hetzner: CX23 €5.99/month in Europe, with Hetzner stating that the ap-southeast (Singapore) zone is priced higher (exact Singapore plans not verified). Vultr: ≈$24/month per third-party comparisons (vultr.com refused the fetch).
- EVIDENCE: https://www.alibabacloud.com/en/product/swas/pricing (retrieved 2026-11-03); https://intl.cloud.tencent.com/document/product/1103/47794 (2026-09-24); https://aws.amazon.com/lightsail/pricing/ (retrieved 2026-11-03); https://docs.hetzner.com/cloud/general/locations/; https://kimmo.suominen.com/stuff/cpc-2026-08.txt (Aug 2026); Vultr figure from search summaries only.
- IMPLICATION: The whole single-process app (FastAPI+SQLite, docs/DEPLOY.md) fits a $9–24/month box; price is not the deciding factor between SG/Tokyo/HK.

### [china-compliance-hosting-29] (low) Reachability from the mainland — latency and GFW risk

- CLAIM: Vendor measurements put mainland→Hong Kong at 10–30 ms on CN2 routes, Tokyo 30–60 ms (east China), Singapore 60–120 ms and US-west 150–200 ms, with evening international congestion; the GFW combines IP blacklists, DNS tampering and SNI/DPI filtering, and foreign VPS providers document whole IP ranges being blocked in waves, with IP swaps only a temporary fix. Mainland users need no VPN to reach an overseas HTTPS site unless its domain/IP is blocked.
- EVIDENCE: https://server.hk/blog/speed-comparison-hong-kong-vps-vs-global-vps-providers/ (2025); https://www.simcentric.com/japan-dedicated-server/normal-latency-to-japan-servers-from-mainland-china/; https://www.varidata.com/blog-en/normal-network-latency-from-mainland-to-us-servers/; https://billing.virmach.com/knowledgebase/37/Chinese-Customers-Unable-to-access-your-IP.html; https://forestvpn.com/en/blog/technology/great-firewall-china-blocks-internet/ (all vendor/secondary).
- IMPLICATION: Tokyo or Singapore are workable for a text-heavy app; plan for a clean dedicated IP, the ability to re-IP, and a short-TTL DNS so a block costs hours rather than weeks.

### [china-compliance-hosting-30] (medium) Hong Kong hosting specifically

- CLAIM: Cloud providers require 备案 only for 中国大陆 nodes, so HK servers need no ICP; HK VPS pricing is $15/month at both Alibaba and Tencent; but Hong Kong is outside Anthropic's supported regions and HK IPs are reportedly refused, so the AI calls would still have to be relayed from a supported region.
- EVIDENCE: https://support.huaweicloud.com/prepare-icp/icp_02_0003.html (2026-09-28); pricing pages above; https://www.anthropic.com/supported-countries.
- IMPLICATION: HK buys low latency without the ICP burden but re-creates the relay problem; it is dominated by Singapore/Tokyo unless latency is paramount.

### [china-compliance-hosting-31] (high) 备案号 display requirements (all regimes)

- CLAIM: Mainland rules require: the ICP 备案编号 on the website homepage (办法 Art. 12) linked to beian.miit.gov.cn; the APP 备案编号 in a prominent in-app location with the filing-system link (MIIT 2023 notice; Azure China notes 设置/介绍 pages); the 公安备案编号 at the page bottom; the 算法备案编号 in the site/app (算法推荐规定 Art. 26); the gen-AI model name plus 备案号/上线编号 on a prominent place or product page (CAC 2024/2026 announcements); and 教育App 备案 info in-app (教技厅 2019 Art. 14).
- EVIDENCE: Sources cited in the respective findings above (wikisource 办法; thepaper 24155262; thepaper 28754109; cac.gov.cn 2022-01-04; cac.gov.cn 2024-04-02; extracted 2019 PDF).
- IMPLICATION: Only the mainland-hosted scenario needs a footer/关于 block of filing numbers; the existing Settings → 关于与数据来源 section (frontend/src/pages/SettingsPage.tsx:688-689) is the natural home if that path is ever taken.

## Open questions

- Where is the operator physically located? The 403 'Request not allowed' from api.anthropic.com without a tunnel (memory file) suggests an unsupported region; if so, Anthropic's policy bars the operator's own use and an API-key account would also need a supported billing country.
- Would a 省通信管理局 treat a free, individually filed 中考/高考 vocabulary site as needing 教育/校外培训 前置审批? This is province-specific and provider guidance conflicts (Huawei lists K-12 校外培训; Azure China says general 教育 needs none).
- Does Apple's China App Store review currently demand gen-AI 备案/登记 evidence for an app whose AI content is pre-generated server-side with no chat UI? Only practitioner reports ('stores usually ask') were found, no Apple document.
- Is TestFlight distribution to mainland testers treated by MIIT/CAC as 'providing an APP service' without 备案, and is a 90-day rebuild cycle acceptable to the owner as a distribution model?
- Does 标识办法 Art. 4 apply to cached, operator-initiated AI example sentences (深度合成规定 Art. 17(1) '智能写作' scope), and does GB 45438-2025 require per-item metadata when such text is served via JSON/API or pushed by e-mail/webhook?
- Does the shared word library (user-added words validated and published to all users) make the service an '信息分享' function under the 2018 舆论属性 规定, triggering 安全评估 and 算法备案 in a mainland scenario? Notes are private (docs/DESIGN.md:572) but headwords and AI sentences are shared.
- Exact Singapore prices for Hetzner and Vultr were not verified from primary pages (Hetzner only states ap-southeast is priced higher; vultr.com returned 403).
- Does api.anthropic.com actually refuse Hong Kong datacentre IPs for API-key traffic (only secondary claims about claude.ai were found)?
- How would an individual overseas operator satisfy PIPL Art. 53 / 条例 Art. 26 (designated representative reported to a 市级网信部门), and is e-mail delivery from an overseas VPS to QQ/163 mailboxes reliable (not researched in this slice)?
