# Verification — slice `hosting` (word-Dance quick-deploy + mobile research)

Verifier run 2026-11-04 (UTC 11:36–12:10). Method: adversarial re-sourcing of each claim against primary pages (official docs, pricing pages, source code, vendor APIs), with the digest's own URLs used only as a cross-check. Local commands ran from the repo at `9ab13a5` read-only; nothing was written outside `scratchpad/quick/verify/`. Raw downloads (HTML, PDFs, cloudflared tarball, Porkbun pricing JSON) are kept in `scratchpad/quick/verify/raw/`. "Accessed" = 2026-11-04 unless stated. Anything older than 6 months is marked **[old]**.

Summary of verdicts: F1 confirmed · F2 confirmed · F4 corrected (CNY nuance) · F8 confirmed (price stale) · F12 confirmed · F13 confirmed · F14 corrected (Porkbun .com now $11.81) · F16 corrected (XFF is added by the edge, not cloudflared; conclusion unchanged) · F17 confirmed · F18 corrected (official Android APK exists; iOS conclusion stands).

---

## F1 — Anthropic supported-region list — **confirmed**

**What I read**
- `https://www.anthropic.com/supported-countries` (fetched twice: WebFetch + `curl`, 170,752 bytes). Rendered meta-label is **"Effective"**, not "Last Updated": raw HTML `<p class="text-caption-1">Effective</p><p …><time dateTime="2026-11-12T20:20:00.000Z">Nov 12, 2026</time>`; it is the only `dateTime` on the page. Quote: "Anthropic's products and services — including our apps (such as Claude.ai, Claude Code, and Cowork), our API and developer platform, and Claude models offered through cloud platforms and authorized resellers — are available only in the countries and regions listed below." Japan, Singapore, Taiwan, South Korea listed; `grep -i 'hong kong\|macau\|macao\|>China<\|mainland'` → no matches.
- `https://platform.claude.com/docs/en/api/supported-regions` ("Here are the countries, regions, and territories Anthropic can support access from:") — I counted the list: **175 entries**, including Japan, Singapore, South Korea, Taiwan, United States of America; no China / Hong Kong / Macau entry. No page date shown.

**Correction/notes**: none to the substance. Minor: the page label is "Effective Nov 12, 2026" (a future effective date for the policy text as rendered today), not "Last Updated". Neither page contains proxy/VPN language.

---

## F2 — Hong Kong datacentre IPs get 403 `Request not allowed`; SG/US placements clear it — **confirmed**

**What I read (primary = the merged PRs themselves)**
- theaiinc/leyline PR #17 "Leyline runs in Singapore so Anthropic answers it", author stevetranaiinc, opened/merged 2026-10-14: "From Cloudflare's HKG colo, where most of Leyline's traffic lands, Anthropic's API answered every call with `403 forbidden: Request not allowed`" … "Hong Kong is outside its supported regions." Fix: `"placement": { "mode": "targeted", "region": "gcp:asia-southeast1" }` ("runs the Worker in Singapore … Singapore is supported").
- JingJerYen/rcsolver PR #13 "API 固定在美國機房執行，避免辨識被 403 拒絕", 2026-10-24: "Cloudflare Worker 在離手機最近的機房執行，從台灣連線有時會被分到香港，而 Anthropic API 不服務香港。" / "The Anthropic API answered 403 'Request not allowed' to some recognise calls." Fix: `[placement] region = "aws:us-east-1"`.
- anthropics/claude-code issue #30318, opened 2026-03-03, closed 2026-08-17 by bcherny (Collaborator): "We don't document workarounds for regions where Claude isn't available (see https://www.anthropic.com/supported-countries), so we won't add the region-specific section. Closing." Body: `❌ 302 redirect to https://www.anthropic.com/app-unavailable-in-region`, "API Error: 403 'Request not allowed'".

**Correction/notes**: the digest paraphrased the closing comment as "do not provide workarounds"; the verbatim is "We don't document workarounds". Caveat worth keeping: both October fixes are Cloudflare Workers running in the HKG colo, not a Hong Kong VPS; I searched for a Tencent/Alibaba-HK-VPS-specific 403 report and found none (claude-code #28486, which the search surfaced, is an unrelated Cowork/MCP 403). The region filter is nonetheless the documented mechanism, so the HK exclusion stands. Gizmodo article not re-checked (secondary).

---

## F4 — Tencent Lighthouse overseas bundles/prices/overage — **corrected** (USD confirmed; CNY nuance wrong)

**What I read**
- Official "Pricing Details" `https://intl.cloud.tencent.com/document/product/1103/47794`, "Last Updated: 2026-09-24 16:02:27":
  - Hong Kong (China) Linux Starter: "2 core, 2 GB, 40 GB, 20 Mbps, 512 GB, $6.00/Month"; "2 core, 2 GB, 50 GB, 30 Mbps, 1024 GB, $8.50/Month"; "2 core, 4 GB, 70 GB, 30 Mbps, 2048 GB, $15.00/Month".
  - Regions outside China (Singapore, Tokyo, Silicon Valley, Frankfurt, Jakarta, Seoul, Virginia, Sao Paulo, Johor Bahru) Linux Starter: "2 core, 2 GB, 50 GB, 30 Mbps, 1024 GB: $4.50/Month"; "2 core, 4 GB, 60 GB, 30 Mbps, 1536 GB: $6.00/Month".
  - Razor Speed Linux (200 Mbps, unlimited): range "$5.00/Month" (2 core/1 GB) to "$50.00/Month"; the 2 core/2 GB/40 GB row is **$5.60/Month**; footnote "not available in the Johor Bahru region".
  - Overage: "Tokyo: 0.13 USD/GB; Hong Kong, Seoul, Jakarta, São Paulo: 0.12 USD/GB; Silicon Valley, Frankfurt, Johor Bahru: 0.077 USD/GB; Singapore: 0.081 USD/GB".
  - The pricing page carries **no** Starter-bundle / cross-border disclaimer (see Omission 3 for where that text lives).
- 中国站 docs remain unreadable: `cloud.tencent.com`, `cloud.tencent.cn`, `cloud.tencent.com.cn` `/document/product/1207/44232|44231|73452|50103` all return a 985–987-byte JS shell; PDF exports exist only for the FAQ (`1207_44569_cn.pdf`, 4.67 MB) and 产品简介 (`1207_44357_cn.pdf`, 2.68 MB) — none for 价格总览. FAQ PDF (©2013-2026) confirms: "不支持[单独购买流量包]。您在购买时所选择的基础套餐中已包含流量包，当您实际使用流量超出所选基础套餐中的月流量包限额时 … 超出部分将按流量计费（仅统计服务器的出流量）".
- CNY third-party: ittellyou.com/402.html (2026-10-10): HK "2核CPU、2GB内存、40GB SSD、20Mbps峰值带宽及500GB级月流量 … 32.30元/月" described as "渠道宣传价格", members ¥24.70; table "Tokyo/Singapore/Silicon Valley/Frankfurt/Seoul | 2核 | 2GB | 50GB | 30Mbps | 1TB | ¥33.00" and "2核 | 4GB | 60GB | 30Mbps | 1.5TB | ¥42.00". vpsquery.com/archives/8051 (2026-10-10): "即日起至2026-10-31 23:59:59新用户购买香港2核2GB/40GB SSD，20M峰值带宽月流量0.5T，月付仅需32元起"; "此外还有2核2G30M月付99元，可选东京/新加坡/硅谷/法兰克福/首尔机房". vps55.com/archives/3359 (2025-02-20 **[old]**): "2G内存、2核、50G SSD、1024G流量、30M带宽，99元/年", "4G内存、2核、60G SSD、1536G流量、30M带宽，199元/年" (年付, Singapore/Silicon Valley/Frankfurt/Seoul/Tokyo). 2023 tables (nssq.cn/9649, yunloc.com/2304 **[old]**) show ¥32/¥42/¥67 per month for 30G/1TB, 50G/2TB, 80G/3TB variants.

**Correction**: (a) The digest's reading "one source shows a ¥99 non-promo [monthly] price — treat ¥33–¥99 as the range" is wrong: the ¥99 figure is the **new-user annual** price of the same 2c2g/50G/30M/1 TB bundle (¥99/年, 2c4g ¥199/年 in the 2025 run; vpsquery's "月付99元" is inconsistent with its own spec line and with every other source). The ¥33/¥42 monthly figures are the standard rates and agree with the official $4.50/$6.00 within 10 % (USD×6.684 = ¥30.1/¥40.1). (b) The HK ¥32 promo window quoted by vpsquery closed 2026-10-31, i.e. before today. (c) Razor Speed "from $5.00" is the 2c/1 GB row; the 2c/2 GB row is $5.60. Official CNY prices still unverified (console check remains necessary, as the digest already said).

---

## F8 — Alibaba SAS overseas prices + "not recommended for mainland visitors" — **confirmed** (CNY plan price is stale)

**What I read**
- help.aliyun.com "轻量应用服务器所适用的地域及网络连通性" (`document_detail/98714.htm`, no date shown): "与中国内地的网络非直连，如果您在中国内地访问香港及海外地区的服务器，可能出现网络较大延迟及丢包" and "中国香港及海外地区提供的带宽主要面向非中国内地的用户，如果您在中国内地，使用这些地域会有较高的访问延迟，不建议您使用". Overseas regions listed: 中国香港, 新加坡, 马来西亚（吉隆坡）, 印度尼西亚（雅加达）, 菲律宾（马尼拉）, 泰国（曼谷）, 日本（东京）, 韩国（首尔）, 英国（伦敦）, 德国（法兰克福）, 美国（弗吉尼亚）, 美国（硅谷）.
- help.aliyun.com "轻量应用服务器计费项" (`document_detail/86281.htm`): overage "中国香港 1元/GB", "新加坡 0.53元/GB", "日本（东京） 0.8元/GB", "美国（硅谷） 0.8元/GB".
- alibabacloud.com/en/product/swas/pricing: "USD 3.5 per month, CPU 1, RAM 0.5 GB, SSD 20 GB, … 4 Mbit/s, … 1 TB" up to "USD 70 … 4 CPU, 16 GB"; overage "Hong Kong USD 0.153 per GB", "Tokyo USD 0.087", "Singapore USD 0.081", "Silicon Valley USD 0.077"; "if the traffic exceeds the upper limit of the package in the current month, the exceeding traffic will be charged at the Pay-As-You-Go rate."
- developer.aliyun.com/article/1672279 (2025-07-18 **[old]**): "国际型39元/月、468元一年 | 2核 | 2GB | ESSD 40GB | 限峰值带宽200Mbps | 公网线路类型BGP_NCO | 1 IPv4"; "通用型56元/月、672元一年 … BGP"; the article itself says mainland-facing users should "选择通用型轻量服务器" rather than 国际型 (BGP_NCO).
- Looked for a 2026 source with overseas CNY rows: developer.aliyun.com articles 1724308 (2026-04-07), 1736611 (2026-05-25), 1716989 (2026-03-16) are all mainland-only; a search summary repeats "海外地域 … 2核2G+40G ESSD+200M峰值带宽年付468元" and "25元1个月起" but no 2026 page with the table was retrievable.

**Notes**: The warning and overage parts are confirmed verbatim; the ¥39/month plan price has no 2026 confirmation (flag: 15 months old). Also note Tencent carries an equivalent cross-border disclaimer (Omission 3), so "Alibaba's docs warn" is not a differentiator between the two.

---

## F12 — No ICP filing for overseas hosting; 公安联网备案 remark — **confirmed**

**What I read**
- help.aliyun.com "不同场景下ICP备案的常见问题" (`knowledge_detail/102270.html`): "若解析指向境外服务器（如中国香港），则无需ICP备案，但需完成公安联网备案。" and "当域名解析指向中国内地的服务器并开通Web服务时，需进行ICP备案。"
- help.aliyun.com "阿里云ICP备案流程概述" (`document_detail/36922.htm`): "用阿里云香港、海外服务器？-- 无需备案。" and "使用海外或中国香港节点服务器无需ICP备案，但若网站在中国内地可访问，仍须在网站/App开通后30天内完成公安联网备案。" — cites 《计算机信息网络国际联网安全保护管理办法》.
- help.aliyun.com "网站备案" (建站产品, `/zh/dws/icp-filing`): "中国香港节点：无需进行ICP备案，网站可直接解析上线。"
- Second provider, same rule (Inspur cloud filing FAQ): "无论网站部署在中国内地或非中国内地的服务器上，只要在中国内地可访问该网站服务，均需进行公安联网备案。"
- Not re-checked: the URL-forwarding ("URL转发") 备案 gate quote (digest snippet only).

**Notes**: Substance confirmed. The 公安联网备案 expectation is not merely "Alibaba's reading": two providers state it identically and tie it to the 1997 regulation, keyed on mainland *accessibility* within 30 days of launch, not on server location. Still a legal call the owner deferred; it is not an ICP blocker.

---

## F13 — Domestic DNS for an un-filed domain pointing abroad; the two 实名 gates — **confirmed**

**What I read**
- docs.dnspod.cn "关于暂停未实名用户解析服务公告" (updated 2024-01-16 17:32 **[old]**): "未实名认证的用户将会被暂停解析服务". The page shows no "2023-08" start date (the digest's "since 2023-08" is unsupported by the page itself).
- docs.dnspod.cn "域名实名认证相关" (2021-11-26 **[old]**): "未完成实名认证的域名会被注册局暂停解析（Serverhold），无法正常访问。" and "非腾讯云注册域名，您可咨询您对应的域名注册商进行实名。"
- help.aliyun.com "创建域名信息模板" (`document_detail/35881.htm`): "所有域名必须完成实名认证，才能正常解析和使用。若未完成认证，域名将被注册局锁定（域名状态为serverHold）".
- Non-registrar domains are accepted: docs.dnspod.cn "域名解析托管在 DNSPod" (2022-04-01 **[old]**) — add the domain, then "将DNS 服务器修改为 DNSPod 提供的DNS 服务器地址", with per-registrar guides for GoDaddy, Namecheap, Google Domains, Alibaba Cloud etc.; help.aliyun.com `/zh/dns/add-domain` (批量添加非阿里云注册域名) confirms Alibaba DNS takes non-Alibaba domains.

**Notes**: Confirmed. Precision: the serverHold gate is a registry/registrar mechanism enforced for domains under MIIT-regulated (Chinese) registrars and for `.cn` at CNNIC; a Porkbun/Cloudflare `.com/.top/.xyz` has no such gate, as the digest's implication already says. See Omission 2 for the free-tier TTL floor (600 s) that affects the digest's "TTL 300 s" plan.

---

## F14 — Domain prices 2026 — **corrected**

**What I ran/read**
- **Porkbun pricing API** (`POST https://api.porkbun.com/api/json/v3/pricing/get`, status SUCCESS, 2026-11-04): `com {'registration': '11.81', 'renewal': '11.81', 'transfer': '11.81'}` (first-year coupon `AWESOMENESS`, $1 off, one per user); `xyz {'registration': '2.04', 'renewal': '14.21', 'transfer': '14.21'}`; `top {'registration': '1.63', 'renewal': '4.63', 'transfer': '4.63'}`. porkbun.com/tld/com raw HTML: "$11.81 everyday low price"; /tld/top: "$1.63 first year sale", "$4.32 regular registration", "$4.63 renewal / transfer".
- Verisign increase: domainnamewire.com 2026-04-23 "Effective November 1, the price will increase 7% from $10.26 to $10.97 per year." ICANN announcement 2025-07-21: "$0.20 per transaction is assessed on each annual increment of an add, renew, or transfer transaction…", effective 1 July 2025. ⇒ registrar floor $10.97 + $0.20 = **$11.17** after 2026-11-01 (the digest's figure). Cloudflare publishes no public price table (tldes.com returned 403 to the fetcher); Cloudflare's own number after Nov 1 is therefore *derived*, not observed.
- porkbun.com/support/payment_options: cards, "Alipay is a popular digital wallet in China…", Apple Pay, Google Pay, Amazon Pay, PayPal, USDC, ACH — no UnionPay/WeChat.
- Namecheap KB #35: "Visa, MasterCard, Discover, American Express, Diners Club, JCB, and UnionPay" plus PayPal and crypto.
- developers.cloudflare.com/billing/create-billing-profile/ (updated 2026-05-29): "Card (Visa, Mastercard, American Express, Discover, UnionPay)", PayPal, "Apple Pay, Google Pay, Link, and Instant Bank Payments via Link (US-based self-serve accounts)".
- Alibaba: developer.aliyun.com/article/1709331 (2026-01-29): "com域名注册85元1年、续费95元一年，cn域名注册38元1年，续费42元一年。" wanwang.aliyun.com/domain/com is JS-rendered (no list price in HTML); help 44007 (优惠口令) also JS. So ¥85/¥95 rests on a community article, not an official price page.

**Correction**: Porkbun `.com` is **$11.81** (reg = renew = transfer) as of 2026-11-04, not $11.08 (the digest's number was costgoat's pre-increase snapshot of 2026-10-20). `.xyz` and `.top`, Alipay, UnionPay and the $11.17 at-cost derivation are confirmed.

---

## F16 — Cloudflare Tunnel header semantics vs. the backend — **corrected** (mechanism), conclusion unchanged

**What I ran/read**
- cloudflared source: `raw.githubusercontent.com/cloudflare/cloudflared/master/ingress/origin_proxy.go` lines 47-51 inside `httpService.RoundTrip`: `if o.hostHeader != "" { // Pass the original Host header as X-Forwarded-Host. req.Header.Set("X-Forwarded-Host", req.Host); req.Host = o.hostHeader }` → Host passes through unchanged by default. Full tarball of `master` (RELEASE_NOTES top = 2026.10.7, 2026-10-30): `grep -rn --include='*.go' -i 'x-forwarded-for' --exclude-dir=vendor` → **zero hits**; `X-Forwarded-Proto` appears only in a test ("Tunnel uses scheme defined in the service field of the ingress rule, independent of the X-Forwarded-Proto header").
- developers.cloudflare.com "Origin parameters" (updated 2026-04-17): `httpHostHeader` Default `""`, "Sets the HTTP `Host` header on requests sent to the local service."
- developers.cloudflare.com "Cloudflare HTTP headers" (updated 2026-10-28): "`CF-Connecting-IP` provides the client IP address connecting to Cloudflare to the origin web server" (all plans); "`X-Forwarded-Proto` … By default, the protocol used is `https`"; "If there was no existing `X-Forwarded-For` header in the request sent to Cloudflare, `X-Forwarded-For` has an identical value to the `CF-Connecting-IP` header", otherwise Cloudflare appends the connecting IP.
- cloudflared issue #1426 (2025-02-27, **open**): visitor 203.0.113.1 sending `X-Forwarded-For: a,b,c,d,e,f,g` → origin receives `a,b,c,d,e,f,g,203.0.113.1`.
- Backend at `9ab13a5` (read with `sed -n`): `backend/wd/cli.py:147-148` `proxy_headers=cfg.trust_proxy, forwarded_allow_ips="127.0.0.1"`; `backend/wd/security.py:213-226` `cookie_secure()` returns True when `cfg.trust_proxy` and `x-forwarded-proto` first hop is `https`; `backend/wd/deps.py:78-105` `client_ip()` takes the **last** XFF hop when the peer is a trusted proxy, `host_origin()` takes scheme from `X-Forwarded-Proto` when `WD_TRUST_PROXY=1`; `backend/wd/main.py:159` same rule for `is_https`; `docs/DEPLOY.md:117` `--with-caddy` writes `WD_HOST="127.0.0.1"`, `WD_PUBLIC_URL="https://$DOMAIN"`, `WD_TRUST_PROXY="1"`.
- Timeout sanity: `docs/API.md` endpoint 24/30 — content generation is queued and polled every 5 s (`202 {job_id…}`), so Cloudflare's proxy response timeout does not affect the tunnel path.

**Correction**: cloudflared itself neither sets nor appends `X-Forwarded-For`; the header (and `X-Forwarded-Proto`, `CF-Connecting-IP`) is added by the Cloudflare edge before the request reaches cloudflared, and the append-at-end behaviour in #1426 is the edge's documented behaviour. What the origin sees is exactly what the digest described (right-most hop = connecting visitor), so the backend compatibility conclusion holds.

---

## F17 — Cloudflare Tunnel from the mainland — **confirmed**

**What I read**
- developers.cloudflare.com/china-network/ (updated 2026-04-30): "The Cloudflare China Network is available as a separate subscription for customers on an Enterprise plan"; partner "JD Cloud"; "You must have a valid ICP (Internet Content Provider) filing or license for each apex domain".
- developers.cloudflare.com support doc "Cloudflare traffic not being sent to the geographically closest data center" (updated 2026-10-14): "Cloudflare's global network does not include data centers in mainland China, so visitors there are served from data centers outside the country." / "Traffic that crosses China's network boundaries often has higher latency and lower reliability." (official backing for the "no mainland PoPs" part; the specific "US-West/SJC/LAX" attribution remains practitioner-sourced).
- V2EX t/1009839 (2024-01-18 **[old]**) "有人用过 cloudflare tunnel 把内网服务暴露到公网吗？实测网速 40k 左右": OP on 联通 ~40 KB/s; replies "速度 2MB/s", "切换到 http2 能快好几倍".
- V2EX t/1143620 (2025-07-08 **[old]**) "部分 Cloudflare 的域名近期在大陆无法访问": "cloudflare 为一些域名分配的 cdn 的 ip 为 x.x.x.1（如 104.21.32.1），.1 结尾的该类 ip 被 GFW 批量屏蔽"; recovery reports around 2025-07-10; a later comment reports 188.114.96.0/97.0 blocks.
- XIU2/CloudflareSpeedTest discussion #382 (2022-05-24 **[old]**): "一旦 HTTPS 访问很快就 443 端口 TCP 超时了 … ICMP、TCP 80 通顺"; comments from 2024-12-31 add "104.16.0.0/13 联通和电信都被阻断".
- Not re-fetched: V2EX t/941418 (2023), blog.xmgspace.me (2024), geekswg, smzdm.

**Notes**: Confirmed; most practitioner evidence is 1–4 years old, but the official "served from outside the country" statement is current (2026-10-14). See Omission 5 for a prerequisite the digest missed (zone must be on Cloudflare DNS; Quick Tunnels as the zero-setup alternative).

---

## F18 — Tailscale cannot serve mainland iPhones — **corrected** (Android part wrong; iOS conclusion stands)

**What I ran/read**
- `curl https://itunes.apple.com/lookup?id=1470499037&country=cn` → `resultCount 0`; `country=us|jp|sg|hk` → `1 [('Tailscale', '1.104.5', '2026-11-03T16:59:13Z', 'Tailscale Inc.')]`; CN storefront search "tailscale" → 6 unrelated third-party apps.
- tailscale/tailscale issue #19625 (opened 2026-05-03, closed 2026-05-04), bradfitz: "Tailscale relies on Apple's Network Extension APIs, and apps using those APIs need to be properly signed, distributed, and notarized/approved through Apple's iOS app distribution mechanisms." … "For iPhone and iPad users, the supported installation path is still the Apple App Store."
- tailscale.com/kb/1232/derp-servers ("validated Jan 21, 2026"): regions Sydney, São Paulo, Toronto, Helsinki, Paris, Frankfurt/Nuremberg, Hong Kong, Bengaluru, Tokyo, Nairobi, Amsterdam, Warsaw, Singapore, Johannesburg, Madrid, Dubai, London, 10 US cities — no mainland location.
- **Android**: tailscale.com/download/android and KB 1079 (2026-01-05) list only Google Play — but the official repo README (`github.com/tailscale/tailscale-android`): "The latest stable release APK can be obtained from the [Tailscale Packages Stable Track](https://pkgs.tailscale.com/stable/#android)." `pkgs.tailscale.com/stable/` lists `tailscale-android-universal-1.104.5.apk`; `curl -I` → `HTTP/2 200`, `content-type: application/vnd.android.package-archive`. F-Droid also carries Tailscale 1.104.4 (2026-10-31, BSD-3, built from the official repo).
- **iOS side-channel**: tailscale.com/kb/1083/install-unstable ("validated Jan 7, 2025" **[old]**) offers a TestFlight unstable track; the public link `testflight.apple.com/join/tLcYLZJV` today renders "Join the Tailscale beta … beta is full." TestFlight itself is in the CN App Store (`lookup?id=899247664&country=cn` → 1, v4.4.1).

**Correction**: "Android is Google Play only" is false — Tailscale ships an official universal APK (and F-Droid has it), so a domestic-Android friend *could* install it; this resolves the digest's open question 7. For iPhones the conclusion holds: no CN App Store listing, no sideloadable .ipa, and the only Apple-sanctioned side path (TestFlight unstable track) is full today and would expire builds every 90 days. No mainland DERP relay confirmed.

---

## Omissions / new findings

1. **Lighthouse public IP can be swapped in place exactly once per instance** (resolves the digest's "not verified" re-IP point). Official EN doc "Adjusting the Public IP Address of an Instance" (intl.cloud.tencent.com/document/product/1103/46401, last updated 2022-09-26 **[old]**): "The public IP can be changed only once for each instance throughout its entire lifecycle."; "You can change instance public IPs only three times per day in each region, and this quota is shared with other Tencent Cloud products using public IPs."; "The public IP cannot be changed when the instance status is Frozen, Blocked, or Pending released."; "After the change, the previous public IP is released and cannot be restored." CN FAQ PDF (©2026): "支持更换公网 IP，详情请参见 更换实例公网 IP。" / "不支持更换内网 IP，也不支持绑定弹性公网 IP。" idcspy.com/50560.html (2022-04-13) adds "每台实例在整个生命周期内仅支持更换1次公网IP" and that it is free. ⇒ The re-IP runbook has one in-place shot; a second GFW event means rebuild from snapshot as a new instance (new IP, new instance id).

2. **"TTL 300 s" is not possible on the free tiers of DNSPod or Alibaba DNS.** docs.dnspod.com plan comparison (updated 2025-04-10): minimum TTL Free "600s", Professional "120s", Enterprise "30s", Ultimate "1s". help.aliyun.com "TTL值原理取值范围配置方法": 免费版 and 个人版 "600秒（10分钟）" minimum, 企业旗舰版/尊享版 "1秒". Cloudflare DNS-only (developers.cloudflare.com TTL reference, updated 2026-04-16): "30 seconds (Enterprise) or 60 seconds (non-Enterprise)", "Auto is set to 300 seconds". ⇒ Either accept a 10-minute floor on domestic DNS, pay for a DNSPod/Alibaba plan, or host DNS at Cloudflare (DNS-only, 60 s).

3. **Tencent disclaims cross-border quality for all overseas regions, including the recommended Starter bundle — the same caveat the digest used against Alibaba.** 产品简介 PDF (`1207_44357_cn.pdf`, ©2026), twice: "对于中国港澳台地区和其他国家地域的轻量应用服务器，从中国内地跨境访问时，受运营商网络线路影响可能出现较大延迟和丢包（非跨境访问时通常无影响）。" and "峰值带宽不作为业务承诺指标，当腾讯云在业务高峰期出现资源争抢时，公网带宽可能会受到限制". Intl "Region and Network Connectivity" (updated 2026-09-24): "Users may experience significant latency and packet loss when accessing Lighthouse from the Chinese mainland due to the ISP network lines". A 2026 Tencent promo for the exact 2c4g/30M/60 GB/1.5 TB bundle (quoted by @gwvpsceping, 2026, Seoul/Jakarta/Bangkok/Virginia/Silicon Valley at ¥199/年) carries: "本套餐无法保障跨境公网质量，在跨境连接时可能出现较大网络延迟和丢包。推荐面向海外客户且对跨境网络质量要求低的的业务使用。" Tencent community article 2657269 (2026-04-20) relays the docs: "腾讯云文档注明香港入门型套餐无法保障跨境（内地与香港之间）公网质量" and recommends 锐驰型/通用型 for mainland-facing use. ⇒ Alibaba's "不建议" is not a differentiator; the choice Tencent-vs-Alibaba should rest on price/console/measurement, and the owner's step-7 evening measurement is the real gate.

4. **Geo-IP sanity check of Chinese-cloud overseas IPs came back clean** (bears on open question 4). Tencent Tokyo test IP 43.128.240.50 → ip-api: Japan/Tokyo, ISP "Aceville Pte.ltd", AS132203; ipinfo: JP; `whois` netname ACEVILLEPTELTD-SG, country JP. Tencent Singapore 150.109.0.191 → SG (both DBs). Alibaba Tokyo 47.91.8.42 → JP ("ALICLOUD-JP", AS45102 "Alibaba (US) Technology"); Alibaba Singapore 47.74.196.40 → SG. Caveats: the IPs are from 2023/2024 published test lists (blog.asuhu.com 2023-05-18, hostzg.com 2024-07-23), not necessarily the Lighthouse pool; Anthropic's geo database is unknown. Still, the "Chinese-cloud IP geolocated to CN" failure mode has no support in these two public DBs. Keep the post-provisioning `curl -I https://api.anthropic.com` test.

5. **Cloudflare Tunnel public hostnames require the zone to be on Cloudflare DNS; a Quick Tunnel needs no domain at all.** developers.cloudflare.com "Create a tunnel (dashboard)" (updated 2026-06-23): "Before you publish an application through your tunnel, you must add a website to Cloudflare." Partial (CNAME) setup is not available to free zones: "A CNAME setup (partial) is only available to customers on a Business or Enterprise plan." (updated 2026-10-15). So the free demo path conflicts with "keep DNS at DNSPod/Alibaba DNS" unless a throwaway domain is used. Alternative the digest missed: Quick Tunnels (trycloudflare.com, updated 2026-09-30): "You do not need a Cloudflare account or domain.", "The hostname changes each time you create a Quick Tunnel.", "Each Quick Tunnel supports up to 200 in-flight requests.", "Quick Tunnels are for testing and development." — enough for a one-evening look, zero setup, same mainland-reachability caveats as F17 (and `WD_PUBLIC_URL` would need to be set to the random hostname for the CSRF origin check).

6. **Overseas Lighthouse first-year promo pricing is annual, not monthly** (ties to F4): new-user 2c2g/50G/30M/1 TB at ¥99/年 and 2c4g/60G/30M/1.5 TB at ¥199/年 were the 2025 and 2026 promo shapes (vps55 2025-02-20; 2026 promo per the X post above, region list varies by campaign and did not include Tokyo/Singapore in the 2026 snippet). Combined with the standard ¥33/¥42 monthly, a first-year total of ≈¥99–199 instead of ≈¥400–500 is plausible — check the 中国站 活动 page at purchase time; 续费 is at list price.

Minor additional notes: (a) Porkbun's API shows a first-year `.com/.net/.org` coupon (`AWESOMENESS`, $1 off, one per user); (b) the DNSPod 实名 announcement page carries no 2023-08 effective date; (c) the digest's Tencent "¥32.30 promo" is a channel price ("渠道宣传价格") with a members' ¥24.70 tier.
