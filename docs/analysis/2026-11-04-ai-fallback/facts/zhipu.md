# Zhipu AI (BigModel / Z.ai) as the fallback provider for word-Dance — fact digest

Slice key: `zhipu` · Research date: 2026-11-04 · All web sources accessed 2026-11-04 unless noted. Sources in Chinese are marked **[zh]**. Code citations refer to `/Users/sqin/word-dance` @ `9ab13a5`.

## Summary

- The one genuinely free, current, capable Zhipu text model is **GLM-4.7-Flash** (30B-A3B MoE, 200K context, 128K max output, tool calling, JSON mode, togglable thinking). It is free on both the mainland platform (open.bigmodel.cn) and the international one (api.z.ai), with no token cap, but with a per-account concurrency limit that the docs do not publish (third-party reports: **1 concurrent request**, peak-hour throttling 15:00–23:00 CST). `GLM-4-Flash-250414` (128K/16K out) and `GLM-Z1-Flash` are also free but older; `GLM-4.5-Flash` was retired 2026-01-30 and auto-routes to GLM-4.7-Flash. "Flash" no longer means free: **GLM-5.3-Flash is paid** (¥0.8/¥2.8 per 1M tokens).
- "Free for good" is not promised anywhere: the user agreement says free services may be adjusted or terminated at any time; the historical pattern is a ~12-month cadence of free-model replacement with automatic routing.
- Structured output is **JSON mode only** (`response_format: {type: json_object}`); the OpenAPI specs of both regions enumerate only `text|json_object`, and `tool_choice` supports only `auto`. Schema enforcement therefore stays client-side (the app already has `content.validate_item`).
- Zhipu ships an **Anthropic-format endpoint** (`https://open.bigmodel.cn/api/anthropic`, `https://api.z.ai/api/anthropic`) that accepts a standard pay-as-you-go key (no Coding Plan needed), so the existing `claude -p … --json-schema` runner can be pointed at GLM via `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_DEFAULT_*_MODEL`. Whether the CLI's structured-output path survives the GLM gateway is untested; the CLI binary contains both an API-native path (`output_config.format` + beta header) and a `StructuredOutput`-tool fallback.
- Terms: no 实名 needed to call the API (needed to recharge); payment 支付宝/微信; overseas phone numbers and overseas server IPs are not blocked; BigModel's privacy policy allows anonymised data to be used for model training with no API opt-out, whereas Z.ai's API terms promise no training without explicit consent and no storage of API content.
- Stability is the main weakness: documented platform-level throttling, a multi-day 429/1305 incident on paid GLM-5.2 in June 2026, nightly gateway failures on a free quota in Nov 2026, and no public status page.
- Cost if you move to the cheapest paid sibling: **GLM-4.7-FlashX ≈ ¥26–55/month** at the friends-phase workload (+¥12 one-time seed prewarm); GLM-5.3-Flash ≈ ¥29–58; GLM-4.7 ≈ ¥131–271; GLM-5.3 ≈ ¥290–578.
- The app's classifier regexes will mis-read Zhipu's Chinese error messages (`令牌已过期或验证不正确`, `该模型当前访问量过大`) and HTTP 429 unless extended; the CLI's USD cost estimate is meaningless for GLM models ("costs may be inaccurate due to usage of unknown models").

## Findings

### F1. Current lineup (Nov 2026) and which models are free

**Claim.** Free text models today: `glm-4.7-flash` (200K ctx / 128K out), `glm-4-flash-250414` (128K / 16K out), `glm-z1-flash` (128K, legacy reasoning). Free vision: `glm-4.6v-flash`, `glm-4.1v-thinking-flash`, `glm-4v-flash`. Everything else — including `glm-5.3-flash` — is paid. `glm-4.5-flash` is retired.

**Evidence.**
- Pricing page **[zh]** https://docs.bigmodel.cn/cn/guide/start/pricing (fetched as `.md`): `| GLM-5.3-Flash | 1M | 0.8 | 2.8 | 限时免费 | 0.23 |`, `| GLM-4.7-Flash | 200K | 免费 | 免费 | 限时免费 | 免费 |`, `| GLM-4-Flash-250414 | 128K | 免费 | 免费 | 限时免费 | 不支持 |`, `| GLM-Z1-Flash | 128K | 免费 | 免费 | …`, `| GLM-4.6V-Flash | — | 免费 | 免费 |`, `| GLM-4.1V-Thinking-Flash | 64K | 免费 |`, `| GLM-4V-Flash | 4K | 免费 |`.
- Model overview **[zh]** https://docs.bigmodel.cn/cn/guide/start/model-overview: GLM-4.7-Flash "Free | Context: 200K | Max Output: 128K"; GLM-4-Flash-250414 "Free | 128K | 16K"; GLM-5.3-Flash "1M | 128K" (not marked free).
- Release log **[zh]** https://docs.bigmodel.cn/cn/update/new-releases: "**2026-01-19** GLM-4.7-Flash 免费模型上线 … 为 GLM-4.7 的免费版本，针对高频调用场景进行优化"; "**2026-08-26** GLM-5.3-Flash 原生多模态模型上线".
- Retirement notice **[zh]** https://docs.bigmodel.cn/cn/guide/models/free/glm-4.5-flash: "GLM-4.5-Flash 将于2026 年 1 月 30 日下线，请您及时将模型编码更新为最新版本。正式下线后，相关请求将会自动路由至 GLM-4.7-Flash。"
- Press release **[zh]** https://www.zhipuai.cn/zh/news/148 (2026/01/19): "GLM-4.7-Flash是一个混合思考模型，总参数量为30B，激活参数量为3B … 即日起，GLM-4.7-Flash将替代GLM-4.5-Flash，在智谱开放平台BigModel.cn上线，并供免费调用。" (older than 6 months, but still the governing announcement)
- OpenAPI spec (https://docs.bigmodel.cn/openapi/openapi.json) model enum for chat completions: `["glm-5.3","glm-5.2","glm-5.1","glm-5-turbo","glm-5","glm-4.7","glm-4.7-flash","glm-4.7-flashx","glm-4.6","glm-4.5-air","glm-4.5-airx","glm-4.5-flash","glm-4-flash-250414","glm-4-flashx-250414"]`.

**Implication.** Target `glm-4.7-flash` as the fallback model; keep `glm-4-flash-250414` as a second-level fallback only for lookup_word (16K output is too small for safe consolidate runs, fine for content/lookups). Do not assume `glm-5.3-flash` is free.

**Confidence.** High.

### F2. "Permanent" free tier — no contractual guarantee, but a stable pattern

**Claim.** The free models have no token cap, trial period or expiry, but the terms reserve the right to change or end free services; in practice Zhipu has replaced its free model roughly yearly (GLM-4-Flash 2024 → GLM-4.5-Flash 2025-07 → GLM-4.7-Flash 2026-01) with automatic request routing, so an app pinned to `glm-4.7-flash` keeps working through a retirement.

**Evidence.**
- User agreement **[zh]** https://docs.bigmodel.cn/cn/terms/user-agreement (版本 2026-09-04) §4.6(1): "智谱开放平台可能向您提供各类免费或限时免费的功能与服务（统称为"免费服务"），包括但不限于免费模型 … 免费服务的具体内容、范围及可用性将以平台实际提供情况为准" and "免费服务的目录、内容及可用性可能会不定期调整、变更或终止".
- Service agreement **[zh]** https://docs.bigmodel.cn/cn/terms/service-agreement §1: "这些优惠措施可能是暂时性、阶段性或有数量限制的".
- Retirement/auto-routing text in F1; media **[zh]** https://post.smzdm.com/p/ad73vnnd/ (2026-01-20, >6 months) and https://www.toutiao.com/article/7637491684976198170/ call it "永久免费 … 无 Token 消耗上限、无试用期限、无隐形收费" — marketing language, not a contract.
- Separate one-time quotas exist and should not be confused with the free models: service agreement §2.3 "平台体验金 … 通常平台体验金的使用有效期为自发放之日起 30 天"; media reports of new-account token packs (e.g. "注册还送2000万Token" https://zhuanlan.zhihu.com/p/2039827481071460699 **[zh]**; "500 万 GLM 4.7 token" after 实名 https://blog.csdn.net/weixin_44782294/article/details/158661076 **[zh]**) vary and are promotional.

**Implication.** Treat GLM-4.7-Flash as free-until-replaced, pin the model id but write the fallback so the model id is a config value, and watch the release log twice a year. One-time packs are only useful for the ≈912-call seed prewarm on a paid sibling.

**Confidence.** High that there is no guarantee; medium on the cadence inference.

### F3. Free-tier rate limits: concurrency-based, per model, console-only numbers; third parties report 1 concurrent request

**Claim.** Zhipu limits by *concurrent in-flight requests per model per account*, scaled by a V0–V3 "用户权益" tier earned 1:1 by cash spend (V1 needs ≥¥2,000 in a rolling 3 months — unreachable on free usage). The docs do not print numbers; the console does. Multiple Chinese sources report GLM-4.7-Flash free = 1 concurrent request with peak-hour throttling. Exceeding limits returns HTTP 429 with code 1302 (account) or 1305 (platform overload).

**Evidence.**
- Rate-limit doc **[zh]** https://docs.bigmodel.cn/cn/api/rate-limit: "速率限制主要体现在：并发请求数限制 / 不同模型设有独立的并发限制 / 不同用户权益等级、不同套餐对应不同的并发限制 / 高峰期的动态限流与平台级保护策略"; "并发数指的是：同一时刻正在处理中的请求数量"; "可通过 速率限制 (https://bigmodel.cn/usercenter/proj-mgmt/rate-limits) 查看您的账户目前各模型可调用的速率"; error 1302 "您的账户已达到速率限制，请您控制请求频率", 1305 "该模型当前访问量过大，请您稍后再试"; raise requests via https://bigmodel.cn/rate-limits/form, "平台将在 10 个工作日内完成审核".
- Equity tiers **[zh]** https://docs.bigmodel.cn/cn/guide/platform/equity-explain (生效 2025-11-01, ~12 months old): "V0 等级 [0, 2,000) 基础服务 / V1 [2,000, 10,000) 并发权益 / V2 [10,000, 50,000) 更高并发 / V3 >= 50,000 最高并发"; "花费金额与积分按 1:1 比例兑换"; "赠金账户的余额消耗不会换算到积分内".
- Third-party **[zh]** search digest of https://www.toutiao.com/article/7636089233853153818/ and https://post.smzdm.com/p/ad73vnnd/ (Jan 2026, >6 months): "免费范围包括 API 调用（限 1 个并发请求）", "云端 API 调用限 1 个并发，高峰期（15:00–23:00）可能出现限流". Older GLM-4-Flash-250414 material claimed ~30 concurrency (unverified for 2026).
- Z.ai side: FAQ https://docs.z.ai/help/faq "You can check the rate limits from here: https://z.ai/manage-apikey/rate-limits" (login-walled); third-party tracker https://itsfree.ai/provider/zai/ ("Last verified 2 Sep 2026"): "Concurrency set per account and model, shown in the console."

**Implication.** Run the fallback with `WD_AI_CONCURRENCY=1` (config.py:336 clamps 1–3) and serialise all four job kinds; a 429/1302 must be treated as *defer*, not failure. Serial throughput is sufficient for ≤100 content calls/day; the seed prewarm (912 calls × ~60 s) becomes a ~15 h background job. Buying ¥50 of credit will not raise concurrency.

**Confidence.** High on the mechanism; medium on "1 concurrent" (console-only, third-party reported).

### F4. Context window, max output, speed

**Claim.** GLM-4.7-Flash: 200K context, 128K max output; GLM-4-Flash-250414: 128K / 16K; GLM-5.3-Flash: 1M / 128K; GLM-4.7: 200K / 128K. Measured hosted speed for GLM-4.7-Flash ≈ 96–122 tokens/s, TTFT 1.3–1.9 s.

**Evidence.** Model pages F1; OpenAPI `max_tokens` description **[zh]**: "`GLM-5.3` `GLM-5.2` `GLM-5.1` `GLM-5` `GLM-5-Turbo` `GLM-4.7` `GLM-4.6`系列最大支持`128K`输出长度，`GLM-4.5`最大支持`96K`输出长度，建议设置不小于`1024`". Artificial Analysis https://artificialanalysis.ai/models/glm-4-7-flash (search digest): "GLM-4.7-Flash (Reasoning) … 122 tokens per second", "Non-reasoning … 96.4 tokens per second", TTFT "1.31 s" / "1.93 s".

**Implication.** The ≈96 KB consolidate prompt (≈30–40k tokens) fits every candidate. A content call (≈3,800 output tokens on Sonnet) should take ≈40–60 s on GLM-4.7-Flash plus thinking tokens — inside the 180 s content timeout (config.py:95) but with little headroom if thinking is left on; set `max_tokens` explicitly (default behaviour is unspecified; docs say "建议设置不小于 1024").

**Confidence.** High (specs), medium (speed figures are third-party, provider-aggregated).

### F5. Structured output and tool calling: JSON mode only, `tool_choice=auto` only, thinking togglable on 4.7-Flash

**Claim.** Both regions expose `response_format.type ∈ {text, json_object}`; there is no `json_schema`/`strict` mode and no forced function call. GLM-4.7 series (incl. Flash) defaults to thinking **on** and accepts `thinking.type: disabled`; GLM-5.3/5.3-Flash cannot disable thinking.

**Evidence.**
- OpenAPI (both): `"response_format": {… "enum": ["text", "json_object"]}`; bigmodel description **[zh]** "`type` 取值收敛为三种：`text`（普通文本输出）、`json_object`（`JSON` 格式输出）" (the text says three, lists two). Z.ai chat-completion reference https://docs.z.ai/api-reference/llm/chat-completion: "Only `text` (plain text output), `json_object` (JSON output)"; tool_choice: "default value is auto, and only auto is supported".
- Function-calling guide **[zh]** https://docs.bigmodel.cn/cn/guide/capabilities/function-calling: "`tool_choice`: 控制函数调用策略， 默认且仅支持 `auto`".
- Structured-output guide **[zh]** https://docs.bigmodel.cn/cn/guide/capabilities/struct-output uses only `response_format={"type": "json_object"}`; the Z.ai copy lists "`glm-5`, `glm-4.7`, `glm-4.6`, etc." as supporting models. GLM-4.7-Flash page **[zh]** https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash capability cards: "结构化输出 — 支持 JSON 等结构化格式输出", "强大的工具调用能力", "思考模式 — 提供多种思考模式".
- Thinking **[zh]** https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode: "GLM-5.3 GLM-5.3-FLASH GLM-5.2 GLM-5.1 GLM-5 GLM-4.7 系列默认开启 Thinking … 如果您想关闭 thinking，请使用 `"type": "disabled"`，注意 `GLM-5.3` `GLM-5.3-FLASH` 强制思考不能关闭". GLM-5.3-Flash page: "`thinking.type` 仅支持 `enabled`，不支持关闭思考".
- Third-party corroboration: GitHub issue "AI 网关: OpenAI 兼容协议的 json_schema 结构化输出对不支持该模式的厂商静默失效(如智谱 GLM)" https://github.com/SmartCode-X/SmartAdmin/issues/8 **[zh]**.

**Implication.** On the OpenAI-compatible path, put the schema in the system prompt, send `json_object`, disable thinking for content/lookup (speed, determinism), validate with `jsonschema` + `content.validate_item`, retry once on failure. The HF model card recommends `temperature 0.7` for code/terminal tasks and `1.0` general; test both on the content prompt.

**Confidence.** High (enum, tool_choice), medium (JSON mode + thinking interplay on Flash is undocumented).

### F6. Endpoints: OpenAI-compatible and Anthropic-format, both with a standard key; Coding Plan not required

**Claim.** Mainland: `https://open.bigmodel.cn/api/paas/v4/chat/completions` (OpenAI) and `https://open.bigmodel.cn/api/anthropic` (Anthropic Messages, `/v1/messages`). International: `https://api.z.ai/api/paas/v4` and `https://api.z.ai/api/anthropic`. A standard pay-as-you-go key works on the Anthropic endpoint and is billed to the account balance/resource packs; model ids are the Zhipu codes (list not enumerated for this endpoint). The documented Claude Code setup is `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`. Keys are region-bound.

**Evidence.**
- Claude API 兼容 **[zh]** https://docs.bigmodel.cn/cn/guide/develop/claude/introduction: "替换您访问的 base_url 为 `https://open.bigmodel.cn/api/anthropic` / 在 智谱开放平台 申请您的 `api_key` / 调用时使用智谱模型编码即可"; cURL example `curl https://open.bigmodel.cn/api/anthropic/v1/messages --header "x-api-key: YOUR_API_KEY"` with `"model": "glm-5.3"`; warning "某些场景下智谱与 Claude 接口仍存在差异，但不影响整体兼容性".
- API-key classification notice **[zh]** https://docs.bigmodel.cn/cn/coding-plan/notice/api-key-management (2026-10-16): table row "Anthropic Messages - 通用 | `https://open.bigmodel.cn/api/anthropic` | … 未曾拥有过 Coding Plan 套餐，将消耗账户余额或适用的普通资源包"; "标准 API Key、个人套餐 Key、团队套餐 Key 互不通用". Z.ai mirror https://docs.z.ai/devpack/notice/api-key-management lists "Anthropic Messages — general endpoint https://api.z.ai/api/anthropic".
- Claude Code page **[zh]** https://docs.bigmodel.cn/cn/guide/develop/claude: settings.json env `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL: https://open.bigmodel.cn/api/anthropic`, `ANTHROPIC_DEFAULT_OPUS_MODEL / _SONNET_MODEL / _HAIKU_MODEL`, `API_TIMEOUT_MS: 3000000`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: 1`; model-switch page https://docs.bigmodel.cn/cn/coding-plan/latest-model shows `"ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.3-flash[1m]"`.
- Region binding: GitHub robinebers/openusage#1334 "keys only work in the region that issued them".
- Own probe (this Mac, mainland, dummy key, 2026-11-04): `open.bigmodel.cn/api/anthropic/v1/messages` → `HTTP 401 {"error":{"message":"令牌已过期或验证不正确","type":"401"}}` (TLS 0.16 s); `open.bigmodel.cn/api/paas/v4/chat/completions` → `{"error":{"code":"401","message":"令牌已过期或验证不正确"}}`; `api.z.ai/api/anthropic/v1/messages` → `{"error":{"message":"token expired or incorrect","type":"401"}}` (TLS 0.09 s).

**Implication.** Two integration routes exist without touching the CLI contract: (A) point the existing `claude -p` runner at GLM through a wrapper script that exports the env above (note `PASSTHROUGH_ENV` in runner.py:50–63 forwards only `ANTHROPIC_API_KEY/AUTH_TOKEN/BASE_URL`, proxies and SSL vars, so the wrapper itself must export `ANTHROPIC_DEFAULT_*_MODEL`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `API_TIMEOUT_MS`); or (B) a small shim named by `WD_CLAUDE_BIN` that speaks the OpenAI-compatible API and prints the CLI's JSON envelope. Whether `glm-4.7-flash` is served on `/api/anthropic` is undocumented (the gateway accepts "智谱模型编码"); a one-request test settles it.

**Confidence.** High (endpoints, key type), medium (free model on the Anthropic path).

### F7. How the installed Claude CLI would behave against the GLM gateway

**Claim.** Claude Code 2.1.292 (the cask binary at `/opt/homebrew/Caskroom/claude-code/2.1.292/claude`) implements `--json-schema` through the Messages API structured-outputs beta (`output_config.format` / legacy `output_format`, header `structured-outputs-2025-12-15`) and also carries a `StructuredOutput` tool path with an "unsupported" latch; `--fallback-model` only re-targets model names, never providers; cost for unknown models is flagged inaccurate.

**Evidence.** String scan of the binary (read-only, no execution): `"structured-outputs-2025-12-15"`; `Both output_format and output_config.format were provided. Please use only output_config.format (output_format is deprecated).`; `markStructuredOutputsUnsupported`, `isStructuredOutputsMarkedUnsupported`, `clearStructuredOutputsUnsupported`; `You MUST call the StructuredOutput tool to complete this request.`; `error_max_structured_output_retries`; `--fallback-model <model>  Enable automatic fallback to specified model(s) when the default model is overloaded or not available. Accepts a comma-separated list`; `costs may be inaccurate due to usage of unknown models`. CLI reference https://code.claude.com/docs/en/cli-reference: "`--json-schema` Get validated JSON output matching a JSON Schema after the agent completes its workflow (print mode only)"; "`--max-budget-usd` … checks the cap against its client-side cost estimate". App side: runner.py:126–147 (`build_argv`), runner.py:145–146 (`--fallback-model` only when `WD_AI_FALLBACK_MODEL`), config.py:333–334.

**Implication.** Route (A) is plausible but must be tested end-to-end: if the GLM gateway rejects or ignores the beta `output_config`, the CLI may either fall back to the `StructuredOutput` tool (works only if the gateway supports Anthropic `tools`/`tool_use`, which Claude Code usage implies) or return a text result with no `structured_output` → the app's `invalid_output` path. `total_cost_usd`/`modelUsage` will be 0/unknown for GLM, so the app's USD caps (config.py:100–103) stop protecting spend on paid GLM siblings; compute CNY cost from `usage` in the wrapper or ledger instead. Provider failover cannot be expressed with `--fallback-model`; it belongs in `runner.py` (choose wrapper/env per provider).

**Confidence.** Medium (strings prove the mechanisms exist; runtime behaviour against Zhipu unverified).

### F8. Z.ai (international) — same models, USD pricing, free Flash, Singapore terms, card/PayPal

**Claim.** `api.z.ai` serves the same lineup in USD; `GLM-4.7-Flash` and `GLM-4.5-Flash` are listed free; `GLM-5.3-Flash` is $0.15/$0.50, `GLM-4.7-FlashX` $0.07/$0.40, `GLM-4.7` $0.60/$2.20, `GLM-5.3` $1.40/$4.40 per 1M tokens. Operator is a Singapore entity; mainland China is **not** an excluded region; payment is credit card (no 3-D Secure) or PayPal; API content is not used for training unless the customer agrees and is not stored per the DPA. Reachable directly from the mainland.

**Evidence.** Pricing https://docs.z.ai/guides/overview/pricing: "All prices are in USD", "GLM-5.3-Flash | $0.15 | $0.03 | Limited-time Free | $0.50", "GLM-4.7-Flash | Free | Free | Free | Free", "GLM-4.5-Flash | Free …". Terms https://docs.z.ai/legal-agreement/terms-of-use ("Last Update: April 14, 2026"): "agreement between JINGSHENG HENGXING TECHNOLOGY PTE.LTD … governed by the laws of Singapore"; "You confirm that you are not located in the following regions: Iran, North Korea, Cuba, Crimea, Donetsk, or Zaporizhzhia"; "For enterprises and developers using API Services, we will not use your User Content for developing or improving Services unless you explicitly agree to such use"; Additional Terms §3(b) "[We will not use End User Content to develop or improve Services, unless you explicitly agree to such use.]" (bracketed in the original); §1(a) "right to use Z.ai's API to integrate the Services into your applications or to develop downstream systems, applications or functions to your end users". Privacy/DPA https://docs.z.ai/legal-agreement/privacy-policy ("Last Update: September 29, 2025", >12 months): "The Company do not store any of the content the Customer or its End Users provide or generate while using our Services … processed in real-time … not saved on our servers"; "Customer Data is generally processed in Singapore". Payment: https://docs.z.ai/help/faq "When using a credit card to recharge, please ensure that you are not using 3DS verification"; https://docs.z.ai/devpack/faq "charged from your linked payment method (e.g., bank card or PayPal)". Mainland reachability: own probe (TLS 0.09–0.55 s) and GitHub zai-org/feedback#1366 **[zh]** "中国大陆直连，无 VPN / 无代理".

**Implication.** Z.ai is the better choice if data policy or English-language support matters and the owner has a non-3DS card/PayPal; BigModel is the better choice for 支付宝/微信, fapiao and mainland latency. Both can be configured identically (only base URL + key differ), so support both in the wrapper.

**Confidence.** High.

### F9. Registration, 实名, payment on BigModel

**Claim.** Calling the API does not require 实名认证; recharging does. Individual 实名 = ID document + face recognition (Alipay face API). Overseas phone numbers can register; overseas companies can do enterprise 实名. Recharge via 支付宝/微信 (bank transfer for verified enterprises); balances never expire; refunds are exceptional; invoices on consumed amounts.

**Evidence.** FAQ **[zh]** https://docs.bigmodel.cn/cn/faq/authentication-issues: "目前调用 API 并不强制要求实名认证，但为确保您的账户安全，我们建议您进行实名认证"; "平台是支持海外企业进行认证的"; "个人人脸识别认证：人脸识别通过后，即时完成". Registration FAQ **[zh]** https://docs.bigmodel.cn/cn/faq/registration-login: "智谱开放平台是支持海外手机号注册的". Recharge agreement **[zh]** https://docs.bigmodel.cn/cn/terms/recharge-agreement §3.1 "当您充值时，您应该具有经实名认证成功后的智谱开放平台账户", §5.1 "目前支持支付宝和微信", §7.1 "账户余额的使用不设有效期". Privacy policy **[zh]** §(二) "如您需要使用 API Key 等功能，我们可能需要对您进行实名认证 … 真实姓名、身份证件号码、身份证件 … 正反面照片、手持身份证件照片" and vendor table "支付宝人脸认证API … 人脸识别信息、姓名、身份证号". Fee FAQ **[zh]** https://docs.bigmodel.cn/cn/faq/fee-issues: "智谱开放平台暂时不支持任意形式的退款功能".

**Implication.** The owner can create a key and use the free model with only a phone number; do 实名 only when adding ¥ for a paid sibling. Keep the key out of git and out of the parent env (runner forwards `ANTHROPIC_AUTH_TOKEN`; the wrapper should read it from a 0600 file).

**Confidence.** High.

### F10. Data use and training on BigModel vs Z.ai

**Claim.** BigModel's privacy policy and user agreement allow anonymised/de-identified content to be used for "机器学习或模型算法训练" without further consent; there is no API-specific opt-out; data is stored in mainland China and not transferred abroad. Only the Team Coding Plan agreement promises "数据默认不用于模型训练". Z.ai's API terms promise no training without explicit agreement (F8).

**Evidence.** Privacy policy **[zh]** https://docs.bigmodel.cn/cn/terms/privacy-policy (版本 2025-05-20, >6 months but current) §(七)4: "我们可能会对收集的信息进行匿名化的研究、统计分析和预测 … 以及改进我们的产品和服务（包括使用匿名数据进行机器学习或模型算法训练），按照相关法律法规规定，此类数据已不属于个人信息范畴，因此此类处理后数据的使用无需另行征得您的同意"; §五(一) "我们在中国境内运营中收集和产生的个人信息存储在中国境内 … 目前我们不会跨境传输或存储您的个人信息". User agreement **[zh]** §4.10 repeats the clause. Team plan agreement **[zh]** https://docs.bigmodel.cn/cn/terms/subscription-agreement-team (2026-07-06): "数据默认不用于模型训练". A Zhihu comparison **[zh]** https://zhuanlan.zhihu.com/p/2038936040644325582 (403 to fetch; search digest) draws the same contrast: "标准通用 API 中，智谱保留了'匿名化后可训练'的宽泛通道".

**Implication.** Prompts here are vocabulary lists and generated teaching content, not user PII, so exposure is low; still, never embed learner names/emails in prompts (lookup_word takes user-typed words — fine). If the owner wants a no-training guarantee, use Z.ai.

**Confidence.** High.

### F11. Commercial use, "app for friends", obligations

**Claim.** Integrating the API into your own product for your own end users is explicitly allowed and is not "resale"; commercial use of outputs is permitted "after paying fees per the product rules", which makes commercial use of the *free* model a grey area — but an invite-only, non-commercial app for friends is clearly within scope. Reselling keys/中转 is prohibited with a 5× penalty. The platform's content-safety filter can reject inputs/outputs (code 1301).

**Evidence.** User agreement **[zh]** §3.7(7): "为免疑义，您将本服务依法合规集成至您自有产品、应用或功能中，并向该等产品、应用或功能的终端用户提供服务的，不视为前述受限行为"; §7.2(1) "为免疑义，您可以在按照智谱开放平台届时有效的规则支付费用后，按相应产品的规则商业化使用平台内模型及其生成的内容"; §3.7(7) also bans "服务中转、聚合中转 … 向任何第三方提供 … API Key"; §十三 "要求您承担违规转售期间累计消耗金额的5倍作为违约金". The 模型商用许可协议 **[zh]** https://docs.bigmodel.cn/cn/terms/model-commercial-use concerns open weights ("开源模型和衍生模型"); FAQ **[zh]** https://docs.bigmodel.cn/cn/faq/business-authorization "模型商用授权仅开放给企业用户" — not relevant to API use. Error table **[zh]** https://docs.bigmodel.cn/cn/faq/api-code: "1301 | 400 | 系统检测到输入或生成内容可能包含不安全或敏感内容"; platform note **[zh]** https://docs.bigmodel.cn/cn/guide/platform/securityaudit "内置了安全审核机制". Coding Plan FAQ **[zh]** https://docs.bigmodel.cn/cn/coding-plan/faq: "如需在自建应用、网站、机器人、SaaS 产品等场景中通过 API 集成模型能力，请使用智谱提供的标准 API 服务".

**Implication.** Use the standard API (not a Coding Plan) for word-Dance; keep it non-commercial while on the free model, or move to a paid sibling if it ever charges users. Handle 1301 as a per-batch soft failure (mark the offending words `valid=false`/retry individually) rather than a provider outage — English vocabulary includes words a mainland filter may flag.

**Confidence.** Medium-high.

### F12. Access from an overseas (Tokyo/Singapore) server

**Claim.** There is no evidence of IP geo-fencing on `open.bigmodel.cn`; the terms contemplate overseas use (subject to export-control law); Z.ai support told a European subscriber to use `open.bigmodel.cn`, which worked from Spain. Separately, `api.z.ai` is reachable from the mainland. Choose the region by billing/terms, not by reachability.

**Evidence.** User agreement **[zh]** §3.6: "您在海外使用智谱开放平台应遵守美国、欧盟和/或其他政府机关等外国实体的全部法律、法规、政策的限制与监督"; §十二 export control. GitHub openclaw/openclaw#63687 (2026-04-09): "This domain [open.z.ai] does not resolve via DNS from Europe (tested from Spain …). Z.ai support confirmed that open.z.ai is not deployed globally and European users must use open.bigmodel.cn … The correct working endpoint is open.bigmodel.cn/api/coding/paas/v4 (verified with curl, ~4s response time)". FAQ: overseas phone registration and overseas-enterprise 实名 (F9). Own mainland probes (F6).

**Implication.** A Tokyo Lighthouse VPS can call `open.bigmodel.cn` (expect ~50–100 ms RTT, cross-border links occasionally degrade) and `api.z.ai` alike; verify from the VPS with the same unauthenticated POST before relying on it, and keep both base URLs configurable.

**Confidence.** Medium-high.

### F13. Quality evidence — free Flash vs paid siblings vs Claude/Qwen/DeepSeek

**Claim.** GLM-4.7-Flash is the strongest ~30B open model on agentic/coding benchmarks but has no published Chinese-language or IFEval score; GLM-4.7 (paid) is marketed as on par with Claude Sonnet 4.5 for coding; GLM-5.3 ranks #4 and GLM-5.3-Flash #7 on SuperCLUE (domestic-only, Oct 2026); on an LMArena mirror (Nov 2026) GLM-5.3 (1495) sits above Claude Sonnet 4.6 (1467). Nothing published compares GLM-4.7-Flash to Claude Sonnet on zh-CN explanatory writing — the app's actual job.

**Evidence.**
- Official model card https://huggingface.co/zai-org/GLM-4.7-Flash (Jan 2026, >6 months): "30B-A3B MoE model", MIT license; table GLM-4.7-Flash / Qwen3-30B-A3B-Thinking-2507 / GPT-OSS-20B — AIME 25 91.6/85.0/91.7, GPQA 75.2/73.4/71.5, LCB v6 64.0/66.0/61.0, HLE 14.4/9.8/10.9, SWE-bench Verified 59.2/22.0/34.0, τ²-Bench 79.5/49.0/47.7, BrowseComp 42.8/2.29/28.3. Third-party: BFCL v3 74.6 (https://openrouter.ai/z-ai/glm-4.7-flash search digest), IFBench 60.8 (https://benchmarklist.com/models/z-ai-glm-4.7-flash/).
- Press release **[zh]** (F1): "在编程场景之外，我们也推荐大家在 中文写作、翻译、长文本、情感/角色扮演 等通用场景中体验GLM-4.7-Flash".
- GLM-4.7 page **[zh]** https://docs.bigmodel.cn/cn/guide/models/text/glm-4.7: "GLM-4.7 的代码能力对齐 Claude Sonnet 4.5 … SWE-bench Verified达到 73.8%"; "τ²-Bench 交互式工具调用评测中实现 84.7 分的开源 SOTA，超过 Claude Sonnet 4.5"; "HLE … 42.8%".
- SuperCLUE via mirror https://www.datalearner.com/benchmarks/superclue ("Updated October 22, 2026"): "4 | GLM-5.3 | 71.29", "7 | GLM-5.3-Flash | 68.10", "10 | GLM-5.2 | 63.27"; #1 Qwen3.8-Max-0902 72.62, #2 DeepSeek-V4.1-Flash 71.81; "currently only includes domestic models".
- LMArena via mirror https://www.swfte.com/lmarena (Nov 4, 2026, third-party): "#19 GLM-5.3 – 1495", "#27 GLM-5.3 Flash", "#26 Claude Sonnet 5 – 1479", "#35 Claude Sonnet 4.6 – 1467". GLM-5 launch https://huggingface.co/blog/mlabonne/glm-5 (Feb 17, 2026, >6 months): "#1 among open models on LMArena's Text Arena (score 1452, #11 overall)".
- Z.ai GLM-5.3-Flash page https://docs.z.ai/guides/vlm/glm-5.3-flash: "scoring 57 [Artificial Analysis Intelligence Index v4.1.1] at just $0.045 per task".

**Implication.** Expect GLM-4.7-Flash to produce acceptable but less polished `meaning_zh`/`mnemonic_zh`/examples than Sonnet, with more `validate_item` rejections (headword-in-example, length floors). Measure before trusting: run 100 seed words through both and compare pass rate and spot-checked quality; if the gap is large, use GLM-5.3-Flash (¥0.8/¥2.8, SuperCLUE #7) as the *paid* fallback and keep 4.7-Flash for lookups/SVG.

**Confidence.** Medium (benchmarks are not the app's task; two leaderboards are mirrors).

### F14. Stability and incident history

**Claim.** Zhipu documents platform-wide dynamic throttling; paying users suffered a multi-day 429/1305 incident on GLM-5.2 in June 2026 that staff closed without a fix note; a free GLM-5.3-Flash quota on Z.ai's ZCode gateway failed nightly in Nov 2026; the free API is reported to throttle in peak hours; there is no public status page.

**Evidence.** Rate-limit doc **[zh]** (F3): "平台在以下情况下可能触发 平台级保护机制：某一模型在短时间内整体访问量激增 / 底层算力资源处于高负载状态 / 平台进行系统维护、扩容或异常恢复". GitHub zai-org/GLM-5#83 (opened 2026-06-17): "June 15 … 285 × HTTP 429 errors from midnight through ~16:51 (Beijing time) … Failure rate: ~50% of all requests … Error: `429 该模型当前访问量过大，请您稍后再试`"; follow-ups to 2026-09-14 ("always hitting the limits"); maintainer zRzRzRzRzRzRzR 2026-07-20: "you are welcome to provide feedback through our official API feedback channel and follow our pinned issue #93". GitHub zai-org/feedback#1366 **[zh]** (2026-11-02): "免费 300M GLM-5.3-Flash 额度在 23:00–09:00 窗口内几乎不可用：zcode.z.ai 网关连续 502/503，10 分钟内 20 次请求全部失败". Media **[zh]** (F3): "高峰期（15:00–23:00）可能出现限流". Status: `https://status.bigmodel.cn` → 301 to the homepage; `https://status.z.ai` does not resolve; `https://bigmodel.cn/status` returns the generic SPA shell (checked 2026-11-04).

**Implication.** The fallback must itself be failure-tolerant: treat 1305/1302/429 as defer with exponential backoff (the app's existing "6 overloaded in a row → 15-min pause" is appropriate), schedule prewarm and nightly consolidation in the 00:00–14:00 CST window, and keep a second-level fallback (GLM-4-Flash-250414, or another provider slice) for when GLM-4.7-Flash is throttled.

**Confidence.** Medium.

### F15. Error envelope vs the app's classifier

**Claim.** Zhipu returns business codes with Chinese messages; the app's `AUTH_RE`/`OVERLOADED_RE` only partially match them (HTTP 401 matches via `\b401\b`; 429 does not match at all; Chinese text never matches).

**Evidence.** Error table **[zh]** https://docs.bigmodel.cn/cn/faq/api-code: 1000/401 "身份验证失败", 1001/401 "Header 中未收到 Authentication 参数", 1003/401 "Authentication Token 已过期", 1113/429 "您的账户已欠费，请充值后重试", 1302/429 "您的账户已达到速率限制", 1305/429 "该模型当前访问量过大", 1308/429 "已达到 … 的使用上限", 1211/400 "模型不存在", 1261/400 "Prompt 超长", 1301/400 content safety. Own probe (F6): `{"error":{"code":"401","message":"令牌已过期或验证不正确"}}`. App: runner.py:71 `AUTH_RE = … |\b401\b|…`, runner.py:73 `OVERLOADED_RE = overloaded|\b529\b|\b503\b|rate.?limit|too many requests`, classification at runner.py:271–277.

**Implication.** For the Zhipu provider, classify by business code first (1000/1001/1003 → auth; 1113 → budget; 1302/1305/1308 → overloaded/defer; 1301 → per-item invalid; 1211 → configuration error → pause provider), and extend the regexes with `\b429\b|rate_limit|访问量过大|速率限制|欠费|令牌|身份验证失败` so the CLI route also classifies correctly.

**Confidence.** High.

### F16. Cost at this app's workload on the paid siblings (CNY, mainland prices)

**Claim.** Assumptions: content 25–100 calls/day × (2k in + 4k out); lookups 150/mo × (1k+0.5k); consolidate 300/mo × (35k+3k) (worst case); SVG 1,200/mo × (1.5k+2k); seed prewarm 912 × (2k+4k) one-time; thinking tokens bill as output and can double output on forced-thinking models.

| Model (price ¥/1M in/out) | Content /mo | Other jobs /mo (max) | **Total /mo** | Prewarm (once) | Content if thinking ×2 output |
|---|---|---|---|---|---|
| GLM-4.7-Flash (0/0) | ¥0 | ¥0 | **¥0** | ¥0 | ¥0 |
| GLM-4.7-FlashX (0.5/3) | ¥9.8–39.0 | ¥16.4 | **¥26–55** | ¥11.9 | ¥18.8–75.0 |
| GLM-5.3-Flash (0.8/2.8, thinking forced) | ¥9.6–38.4 | ¥19.4 | **¥29–58** | ¥11.7 | ¥18.0–72.0 |
| GLM-4.5-Air (0.8/6 at out ≥0.2K; 1.2/8 ≥32K in) | ¥19.2–76.8 | ¥30.2 | **¥49–107** | ¥23.4 | ¥37.2–148.8 |
| GLM-4.7 (3/14; 4/16 ≥32K in) | ¥46.5–186.0 | ¥84.6 | **¥131–271** | ¥56.5 | ¥88.5–354.0 |
| GLM-5.3 (8/28) | ¥96–384 | ¥194.1 | **¥290–578** | ¥116.7 | ¥180–720 |

Z.ai USD equivalents: GLM-4.7-FlashX $3.5–7.4/mo, GLM-5.3-Flash $5.3–10.5, GLM-4.5-Air $9.8–20.6, GLM-4.7 $22–45, GLM-5.3 $48–93 (prewarm $1.6–18.6).

**Evidence.** Prices from F1/F8 pricing pages (GLM-4.7 tiers **[zh]**: "输入 [0, 32K)，输出 ≥0.2K | 3 | 14", "输入 [32K, 200K) | 4 | 16"; GLM-4.5-Air "输入 [0, 32K)，输出 ≥0.2K | 0.8 | 6"); cache hits (¥0.1–2/1M) ignored; workload numbers from the task brief; arithmetic in `scratchpad/fallback` (python).

**Implication.** Even the cheapest paid sibling costs less per month than one Claude Sonnet day at the same volume; a ¥100 recharge covers the seed prewarm plus ~2 months on FlashX. Keep `glm-4.7-flash` as the default fallback and `glm-4.7-flashx` (same model class, paid, higher concurrency per tier) as the "pay to escape throttling" option.

**Confidence.** Medium (token assumptions; consolidate upper bound is generous).

### F17. GLM Coding Plan is not a path for this app

**Claim.** Plan quota is restricted to approved coding tools; self-built apps must use the standard API; prices rose on 2026-07-30 to Lite ¥118 / Pro ¥538 / Max ¥1,078 per month; on the plan, GLM-4.7 requests are auto-switched to GLM-5.3-Flash.

**Evidence.** Overview **[zh]** https://docs.bigmodel.cn/cn/coding-plan/overview: "在除规定工具外调用 API，不可享用 Coding 套餐的额度"; "调用 GLM-5-Turbo、GLM-4.7 将自动切换至 GLM-5.3-Flash"; usage notes **[zh]** https://docs.bigmodel.cn/cn/coding-plan/usage-notes: "仅限指定工具使用 … 用于非支持工具将被限制权益"; prices via https://guoneiapi.com/guides/glm-coding-plan/ and https://finance.sina.com.cn/stock/t/2026-07-31/doc-iniksxpi1210399.shtml **[zh]** (third-party summaries of the official site, Oct 2026): "Lite ¥118, Pro ¥538, Max ¥1078".

**Implication.** Ignore the plan for word-Dance (even though the app spawns Claude Code, the FAQ classifies "自建应用" as standard-API use).

**Confidence.** Medium (prices third-party).

## Recommendations

1. **Open an account and run the two decisive tests (effort: S, ~1–2 h).** Register on open.bigmodel.cn with the mainland phone, create a *standard* API key (no 实名 needed). Test 1: OpenAI-compatible call with the real `content_v1` prompt for 10 words, `response_format={"type":"json_object"}`, `thinking={"type":"disabled"}`, `max_tokens=8192`, `temperature` 0.7 and 1.0 — record latency, `usage`, `validate_item` pass rate. Test 2: run the real CLI once with the wrapper env from F6 (`--model glm-4.7-flash --json-schema …`) against `https://open.bigmodel.cn/api/anthropic` and inspect the JSON envelope for `structured_output`. Read the console rate-limit page to learn the actual concurrency for `glm-4.7-flash`.
2. **Implement provider failover in `runner.py`, not via `--fallback-model` (effort: M, 1–2 days).** Add `WD_AI_FALLBACK_PROVIDER=zhipu` + `WD_CLAUDE_BIN_FALLBACK=<wrapper>` (or `WD_ZHIPU_*`), a `provider` column on `ai_calls` (migration 0010), and a selector: when the Claude path yields `auth`, `spawn_error` or trips the overloaded pause, switch `kv.ai.provider` to `zhipu` immediately and re-queue the job; probe Claude every 30 min to switch back. Prefer a Python shim (speaks OpenAI-compatible API, enforces the JSON schema client-side with one retry, prints the CLI's JSON envelope with `usage`, `modelUsage`, and a CNY-derived `total_cost_usd`) over the ANTHROPIC_BASE_URL hack, because it removes the dependency on the gateway's structured-output behaviour.
3. **Extend classification for Chinese envelopes (effort: S, <1 h).** Add `\b429\b|rate_limit|访问量过大|速率限制` to `OVERLOADED_RE`, `令牌|验证不正确|身份验证失败` to `AUTH_RE`, map code 1113 to `budget`, code 1301 to per-item `valid=false` without pausing, code 1211 to a provider-config pause.
4. **Respect the free tier's shape (effort: S).** Force `WD_AI_CONCURRENCY=1` when the provider is Zhipu, schedule prewarm/consolidate in 00:00–14:00 CST, give content calls a 240 s timeout on this provider, and keep `glm-4-flash-250414` as a last-resort model for lookups only.
5. **Gate quality before publishing fallback content (effort: M, half a day).** Generate 100 seed words with GLM-4.7-Flash and compare with existing Sonnet rows (pass rate, zh naturalness, example correctness). Decide: publish directly, publish with a "待校对" flag, or use GLM-5.3-Flash paid (¥29–58/mo) for `generate_content` while 4.7-Flash handles the rest.
6. **Budget guard in CNY (effort: S).** Because the CLI's USD estimate is unreliable for GLM, compute cost in the wrapper from `usage` × the price table and feed the existing daily/monthly caps; keep the Zhipu balance small (≤¥100) so the provider's own balance is the hard stop.
7. **Terms hygiene (effort: S).** Stay invite-only/non-commercial on the free model, label AI-generated content in the UI (the user agreement cites the 标识办法), never put learner PII into prompts, and keep the key in a 0600 file read by the wrapper. If a no-training guarantee matters, use Z.ai with the same wrapper (base URL + key).

## Open questions

1. What concurrency does a fresh V0 account actually get for `glm-4.7-flash` (console-only), and does the 速率限制调整申请 form accept requests for a free model?
2. Does `https://open.bigmodel.cn/api/anthropic` serve `glm-4.7-flash` with a standard key, and does it honour `output_config.format: json_schema` (or trigger the CLI's `StructuredOutput`-tool fallback)? Does the CLI make any Anthropic-only call in `-p` mode that fails under a third-party base URL?
3. Does `json_object` mode behave with thinking enabled on GLM-4.7-Flash, and how much does disabling thinking cost in `validate_item` pass rate?
4. How often does the content-safety filter (1301) reject English vocabulary batches, and does a rejection poison the whole 10-word call?
5. When will GLM-4.7-Flash be retired, and will its successor be free with auto-routing as before?
6. Latency and packet loss from the Tokyo Lighthouse IP to `open.bigmodel.cn` versus `api.z.ai` (needs a probe from the VPS).
7. Current new-account bonus packs (media quote 200万 / 500万 / 2000万 tokens with different validity) — only matters if the seed prewarm runs on a paid sibling.
