# Verification — slice `zhipu` (Zhipu AI / BigModel / Z.ai as word-Dance fallback)

Verifier run 2026-11-04. Every URL below was accessed 2026-11-04 from this Mac. Direct egress geolocates to Shanghai, CN (AS4515 "PCCW Business Internet Access" — an enterprise line, not a consumer ISP); "overseas" probes went through the configured local HTTP proxy whose exit is Santa Clara, US (AS11414). No API key was used, no account was created, the real `claude` was never executed (static string scan only), nothing was written outside `scratchpad/fallback`. Raw downloads (`.md` renderings of docs pages, OpenAPI JSON, GitHub API JSON, HTML) are kept in `scratchpad/fallback/verify/raw/zhipu/`.

Verdict summary: F1 confirmed · F3 corrected · F5 confirmed · F6 confirmed · F7 corrected · F9 confirmed (caveat) · F10 confirmed · F12 confirmed · F14 corrected · F16 corrected.

Freshness flags (>6 months old): equity-explain (2025-11-01), BigModel privacy policy (2025-05-20), Z.ai terms (2026-04-14), Z.ai privacy/DPA (2025-09-29), smzdm/learnku posts (Jan–Feb 2026), openclaw#63687 (2026-04-09). Pricing, rate-limit, model-overview and FAQ pages carry no publication date.

---

## F1 — Free lineup; GLM-4.5-Flash retired; GLM-5.3-Flash paid ¥0.8/¥2.8

**Verdict: confirmed.**

What I read (all `docs.bigmodel.cn`, fetched as `.md`):
- `/cn/guide/start/pricing` (undated) — verbatim rows: `| GLM-5.3-Flash | 1M | 0.8 | 2.8 | 限时免费 | 0.23 | 图片、视频、文件、文本 |`; `| GLM-4.7-Flash | 200K | 免费 | 免费 | 限时免费 | 免费 |`; `| GLM-4-Flash-250414 | 128K | 免费 | 免费 | 限时免费 | 不支持 |`; `| GLM-Z1-Flash | 128K | 免费 | 免费 | 限时免费 | 不支持 |`. Unit: 元/百万 Tokens (input | output | cache storage | cache hit). GLM-4.5-Flash no longer appears on the price list.
- `/cn/guide/start/model-overview`: `| GLM-4.7-Flash | 免费文本模型 延续 GLM-4.7 基座的通用能力 | 200K | 128K |`; `| GLM-4-Flash-250414 | 免费文本模型 | 128K | 16K |`; `| GLM-5.3-Flash | 普惠的全球前沿多模态模型 … | 1M | 128K |` (not marked free; its doc lives under `/guide/models/vlm/`).
- `/cn/guide/models/free/glm-4.5-flash`: `GLM-4.5-Flash 将于2026 年 1 月 30 日下线，请您及时将模型编码更新为最新版本。正式下线后，相关请求将会自动路由至 GLM-4.7-Flash。`
- `/cn/update/new-releases`: `**2026-01-19** GLM-4.7-Flash 免费模型上线`; `**2026-08-26** GLM-5.3-Flash 原生多模态模型上线`.
- `/openapi/openapi.json` (854 KB): chat-completions text enum = `"glm-5.3","glm-5.2","glm-5.1","glm-5-turbo","glm-5","glm-4.7","glm-4.7-flash","glm-4.7-flashx","glm-4.6","glm-4.5-air","glm-4.5-airx","glm-4.5-flash","glm-4-flash-250414","glm-4-flashx-250414"`; `glm-5.3-flash` is listed only in the vision-model enum (`"glm-5.3-flashx","glm-5.3-flashx-legal","glm-5.3-flash","glm-5v-turbo","glm-4.6v",…`).

Notes: the retirement notice is phrased in the future tense and there is no post-fact "retired" banner, but the price list and model overview no longer carry GLM-4.5-Flash, so the claim stands. GLM-5.3-Flash is a multimodal model in the docs taxonomy; the "Flash ≠ free" point is correct. The zhipuai.cn press release was not re-fetched (not load-bearing).

---

## F3 — Concurrency-based limits, console-only numbers, V0–V3 tiers, "1 concurrent", 429 codes 1302/1305

**Verdict: corrected** (mechanism, codes and console-only numbers confirmed; the tier rule is misdescribed; "1 concurrent" is third-party and the unit disagrees between sources; the 15:00–23:00 peak window could not be read verbatim).

What I read:
- `/cn/api/rate-limit` (undated): `速率限制主要体现在：并发请求数限制 / 不同模型设有独立的并发限制 / 不同用户权益等级、不同套餐对应不同的并发限制 / 高峰期的动态限流与平台级保护策略`; `⚠️ 并发数指的是：同一时刻正在处理中的请求数量。`; `可通过 速率限制 (https://bigmodel.cn/usercenter/proj-mgmt/rate-limits) 查看您的账户目前各模型可调用的速率`; 1302 `您的账户已达到速率限制，请您控制请求频率` (typical cause `当前模型的并发请求数已达到账户上限`); 1305 `该模型当前访问量过大，请您稍后再试`; raise requests: `速率限制调整申请 … 平台将在 10 个工作日内完成审核`; `GLM Coding Plan 用户按订阅套餐等级统一并发，暂不支持申请调整。`
- `/cn/faq/api-code`: `| 1302 | 429 | 您的账户已达到速率限制，请您控制请求频率 |`, `| 1305 | 429 | 该模型当前访问量过大，请您稍后再试 |`.
- `/cn/guide/platform/equity-explain` (最新版本生效日期 2025-11-01): `| V0 等级 | [0, 2,000) | 基础服务 |`, `| V1 等级 | [2,000, 10,000) | 并发权益 |`, `| V2 等级 | [10,000, 50,000) | 更高并发 |`, `| V3 等级 | >= 50,000 | 最高并发 |`; `花费金额与积分按 1:1 比例兑换`; `赠金账户的余额消耗不会换算到积分内`; **`平台将于 T+1 日 06:00:00 更新积分，并根据用户最近三个月的最高积分确定本月的用户权益等级。`**; FAQ `消耗资源包中的 Tokens 会增加积分么？ 不会，仅通过消耗现金余额、或三方支付购买产品时，才能产生积分。`; `若用户发生退款动作 … 积分将减去退款金额`.
- Third-party: smzdm `post.smzdm.com/p/ad73vnnd/` (page meta, published 2026-01-20): `免费范围包括API调用（限1个并发请求）和本地下载部署，无Token消耗上限、无试用期限、无隐形收费`. `learnku.com/articles/91710` (early 2026): `并发限制 ： 1 QPS (每秒请求数)` and `价格 ： 0 元 (需实名认证，无需绑定信用卡)`. The two toutiao articles cited in the digest return only a JS shell to curl/WebFetch; the sentence `高峰期（15:00–23:00）可能出现限流` appears only in a search-engine snippet and was not read on any page.

Corrections:
1. "≥¥2,000 cumulative cash spend" is wrong in two ways: the level for a month is set by the **highest points figure within the trailing three months**, and points accrue 1:1 only from cash-balance consumption or resource-pack *purchases* (not 赠金 spend, not tokens drawn from a pack; refunds subtract). For a ≤¥100/month user the practical conclusion (stuck at V0) is unchanged.
2. The "1 concurrent request" figure is third-party only, and sources disagree on the unit (smzdm: 1 个并发请求; learnku: 1 QPS). Plan for 1 in-flight request, but read the console page before sizing the prewarm job.
3. Peak-hour 15:00–23:00 throttling: unverifiable (snippet only). The official doc confirms peak-time dynamic throttling exists but gives no hours.

---

## F5 — JSON mode only; `tool_choice` auto only; thinking toggle (4.7 yes, 5.3-Flash no)

**Verdict: confirmed.**

What I read:
- BigModel `openapi.json` → `response_format`: `"type" 取值收敛为三种：text（普通文本输出）、json_object（JSON 格式输出）` with `"enum": ["text", "json_object"]`; `tool_choice`: `"enum": ["auto"] … 默认auto且仅支持auto`. `json_schema` occurs 0 times.
- Z.ai `docs.z.ai/openapi.json` (145 KB) → `"enum": ["text", "json_object"]` ("`type` converges to three values: `text` (plain text output), `json_object` (JSON output)"); `tool_choice`: `The default value is auto, and only auto is supported.`; `json_schema` occurs 0 times. `/api-reference/llm/chat-completion.md` says the same.
- `/cn/guide/capabilities/function-calling`: `tool_choice: 控制函数调用策略， 默认且仅支持 auto`. `/cn/guide/capabilities/struct-output` uses only `response_format={"type": "json_object"}`.
- `/cn/guide/capabilities/thinking-mode`: `GLM-5.3 GLM-5.3-FLASH GLM-5.2 GLM-5.1 GLM-5 GLM-4.7 系列默认开启 Thinking`; `如果您想关闭 thinking，请使用以下，注意 GLM-5.3 GLM-5.3-FLASH 强制思考不能关闭。` → `"type": "disabled"`. Z.ai mirror: `note that GLM-5.3 and GLM-5.3-FLASH use forced thinking and cannot be disabled`.

Note: the thinking doc says "GLM-4.7 系列" and does not name GLM-4.7-Flash explicitly; no page describes `json_object` + thinking interplay on the Flash model (digest already flags this).

---

## F6 — Anthropic-compatible endpoint, standard key billed to balance, Claude Code env vars, region-bound keys

**Verdict: confirmed** (region binding rests on one third-party report; the model list served on `/api/anthropic` is undocumented).

What I read / ran:
- `/cn/guide/develop/claude/introduction`: `替换您访问的 base_url 为 https://open.bigmodel.cn/api/anthropic` / `在 智谱开放平台 申请您的 api_key` / `调用时使用智谱模型编码即可`; warning `某些场景下智谱与 Claude 接口仍存在差异，但不影响整体兼容性。`; curl example `curl https://open.bigmodel.cn/api/anthropic/v1/messages --header "x-api-key: YOUR_API_KEY" … "model": "glm-5.3"`. The page has **no** parameter-compatibility table and no model list.
- `/cn/coding-plan/notice/api-key-management` (公告发布时间 2026-10-16): `| Anthropic Messages - 通用 | https://open.bigmodel.cn/api/anthropic | 如果曾拥有过 Coding Plan 套餐，将消耗套餐额度（套餐到期后会中断服务）； 未曾拥有过 Coding Plan 套餐，将消耗账户余额或适用的普通资源包 |`; `标准 API Key、个人套餐 Key、团队套餐 Key 互不通用`; standard key: `在标准 API Key 页面创建，使用账户余额或适用的普通资源包，不消耗 Coding Plan 套餐额度`. Z.ai mirror `/devpack/notice/api-key-management`: `Anthropic Messages — general endpoint https://api.z.ai/api/anthropic`.
- `/cn/guide/develop/claude`: `"ANTHROPIC_AUTH_TOKEN": "YOUR_API_KEY"`, `"ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic"`, `"API_TIMEOUT_MS": "3000000"`, `"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1`, `ANTHROPIC_DEFAULT_{HAIKU,SONNET,OPUS}_MODEL` (`glm-4.7`, `glm-5.2[1m]`); `/cn/coding-plan/latest-model`: `"ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.3-flash[1m]"`.
- Probes (direct, no valid key): `POST open.bigmodel.cn/api/anthropic/v1/messages` with no credentials → HTTP 401 `{"error":{"message":"Header中未收到Authorization参数，无法进行身份验证。","type":"1001"}}`; with `x-api-key: dummy` → 401 `{"error":{"message":"令牌已过期或验证不正确","type":"401"}}`; with `Authorization: Bearer dummy` + `anthropic-beta: structured-outputs-2025-12-15` → the same 401 body (the gateway reads the Bearer form that `ANTHROPIC_AUTH_TOKEN` produces; the beta header did not change the error). `api.z.ai/api/anthropic/v1/messages` → 401 `{"error":{"message":"token expired or incorrect","type":"401"}}`. `GET open.bigmodel.cn/api/anthropic/v1/models` → HTTP **200** body `{"code":401,"msg":"令牌已过期或验证不正确","success":false}` (non-Anthropic envelope).
- Region binding: GitHub robinebers/openusage#1334 (2026-10-01, open): `Zhipu sells the GLM Coding Plan in two regions: z.ai (international) and open.bigmodel.cn (China). Keys only work in the region that issued them.` — third-party and about Coding Plan keys; no official statement located.

---

## F7 — Claude Code 2.1.292: structured-outputs beta, StructuredOutput-tool fallback, `--fallback-model`, unknown-model cost

**Verdict: corrected** (one quoted string does not exist in this build; the rest is confirmed; one new risk).

What I ran: Python byte scan of `/opt/homebrew/Caskroom/claude-code/2.1.292/claude` (Mach-O arm64, 235,017,328 B, file date Oct 7; never executed), `grep -n` on `backend/wd/ai/runner.py` @ `9ab13a5`, and `code.claude.com/docs/en/cli-reference`.

Found in the binary: `structured-outputs-2025-12-15` ×3 — incl. `Pne=y("structured_outputs","structured-outputs-2025-12-15")` and the SDK `parse()` helper that appends it to `anthropic-beta`; `Both output_format and output_config.format were provided. Please use only output_config.format (output_format is deprecated).`; `markStructuredOutputsUnsupported(e){this.#r.add(e)}clearStructuredOutputsUnsupported(){…}` and `structuredOutputsUnsupportedModels()`; `error_max_structured_output_retries` ×6; `costs may be inaccurate due to usage of unknown models` ×2; help text `--fallback-model <model>  Enable automatic fallback to specified model(s) when the default model is overloaded or not available. Accepts a comma-separated list to try each in order. Re-tries the primary at the start of each user turn.`; `--json-schema <schema>  JSON Schema for structured output validation.`; `--max-budget-usd <amount>  Maximum dollar amount to spend on API calls (only works with --print)`.

**Not found:** `You MUST call the StructuredOutput tool to complete this request.` (0 hits for `MUST call the StructuredOutput`). The only StructuredOutput-tool strings belong to the in-process/cloud `agent()` helper: `With schema (a JSON Schema), the subagent is forced to call a StructuredOutput tool and agent() returns the validated object` and `the cloud agent never called the StructuredOutput tool`. So a tool-based fallback for the **top-level** `-p --json-schema` path is not evidenced by strings in this build; the "unsupported" latch is.

New in the binary: `Session cost is not a number (a usage or pricing fault upstream); refusing to continue under --max-budget-usd`.

CLI reference (accessed 2026-11-04): `--json-schema | Get validated JSON output matching a JSON Schema after the agent completes its workflow (print mode only) … accepts the format keyword as an annotation without client-side validation`; `--fallback-model | Enable automatic fallback to the specified model(s) when the primary model is overloaded or not available, for example a retired model. Accepts a comma-separated list tried in order.`; `--max-budget-usd | Stop the run once estimated spend on API calls reaches this amount (print mode only). Claude Code checks the cap against its client-side cost estimate, which can differ from your bill … Spend can pass the cap`.

runner.py: `PASSTHROUGH_ENV` spans lines 49–62 (digest said 50–63) and forwards only `ANTHROPIC_API_KEY/AUTH_TOKEN/BASE_URL`, proxy and SSL vars — no `ANTHROPIC_DEFAULT_*`; `build_argv` is lines 124–149 (digest 126–147) and always passes `--max-budget-usd`; `--fallback-model` is appended at line 146 only when `cfg.ai_fallback_model`. `AUTH_RE`/`OVERLOADED_RE` at lines 71/73 as quoted in the digest.

Corrections: drop the "You MUST call the StructuredOutput tool" quote; say the tool fallback is evidenced only for `agent()`; add the NaN-cost refusal as a risk for route A (see omission 3). The conclusions (provider failover belongs in runner.py; USD budgets don't protect GLM spend) hold.

---

## F9 — No 实名 to call the API; 实名 to recharge (支付宝/微信, ID + face); overseas phone registration and overseas-enterprise 实名

**Verdict: confirmed** (with a caveat that the no-实名 path is "currently" policy, not a guarantee).

What I read:
- `/cn/faq/authentication-issues` (undated): `目前调用 API 并不强制要求实名认证，但为确保您的账户安全，我们建议您进行 实名认证`; `平台是支持海外企业进行认证的，您需要在 实名认证 页面选择海外企业并上传相关的认证材料即可`; `个人人脸识别认证：人脸识别通过后，即时完成`.
- `/cn/terms/recharge-agreement`: `3.1 当您充值时，您应该具有经实名认证成功后的智谱开放平台账户。`; `5.1 用户充值可以选择智谱科技认可的第三方支付企业（目前支持支付宝和微信）支付充值金额。`; `7.1 您充值后，账户余额的使用不设有效期，不能转移、转赠。`
- `/cn/faq/registration-login`: `智谱开放平台是支持海外手机号注册的。在注册过程中，请您选择相应的国家区号，并通过短信验证码进行验证，即可完成注册。`
- `/cn/terms/privacy-policy` (2025-05-20) §二(二): `如您需要使用 API Key 等功能，我们可能需要对您进行实名认证` + `真实姓名、身份证件号码、身份证件 … 正反面照片、手持身份证件照片`; vendor table `支付宝人脸认证API … 人脸识别信息、姓名、身份证号 | 蚂蚁云创数字科技(北京)有限公司`.

Caveat: "目前" in the FAQ; the privacy policy reserves 实名 for "API Key 等功能"; the Batch API page says `调用 Batch API 必须实名认证`; a Jan-2026 third-party post says the free API `需实名认证`. Not testable without creating an account (not done).

---

## F10 — BigModel may train on anonymised content with no API opt-out; Z.ai promises no training / no storage

**Verdict: confirmed.**

What I read:
- `/cn/terms/privacy-policy` (最新版本生效日期 2025-05-20) §二(七)4 "征得授权同意的例外": `…或我们可能会对收集的信息进行匿名化的研究、统计分析和预测，用于改善智谱开放平台的内容和布局，为商业决策提供产品或服务支撑，以及改进我们的产品和服务（包括使用匿名数据进行机器学习或模型算法训练），按照相关法律法规规定，此类数据已不属于个人信息范畴，因此此类处理后数据的使用无需另行征得您的同意。` §五(一): `我们在中国境内运营中收集和产生的个人信息存储在中国境内`; `目前我们不会跨境传输或存储您的个人信息`.
- `/cn/terms/user-agreement` (最新版本生效日期 2026-09-04) §四.10: the same clause verbatim. §三.10 bans the *user* from using outputs to train other models.
- Opt-out search (`退出|撤回|拒绝|不用于|选择不`): the only mechanism is privacy §(三) "撤回您授权同意的范围" for personal information; the training clause places anonymised data outside that scope. `/cn/terms/subscription-agreement-team` (2026-07-06) `数据默认不用于模型训练` applies to the Team Coding Plan only.
- `docs.z.ai/legal-agreement/terms-of-use` (Last Update April 14, 2026): `For enterprises and developers using API Services, we will not use your User Content for developing or improving Services unless you explicitly agree to such use.`; Additional Terms 3(b): `[We will not use End User Content to develop or improve Services, unless you explicitly agree to such use.]`; operator `JINGSHENG HENGXING TECHNOLOGY PTE.LTD`, Singapore law/SIAC.
- `docs.z.ai/legal-agreement/privacy-policy` (Last Update September 29, 2025 — >12 months old): `The Company do not store any of the content the Customer or its End Users provide or generate while using our Services … This information is processed in real-time … and is not saved on our servers.`; `Customer Data is generally processed in Singapore`.

---

## F12 — No geo-fencing evidence for overseas server IPs; api.z.ai reachable from the mainland

**Verdict: confirmed** (first-hand for one US exit; Tokyo/Singapore not tested).

What I read / ran:
- `/cn/terms/user-agreement` §三.6: `您在海外使用智谱开放平台应遵守美国、欧盟和/或其他政府机关等外国实体的全部法律、法规、政策的限制与监督。` §十二 出口管制 (sanctions lists, no country-blocking of ordinary users).
- GitHub openclaw/openclaw#63687 (opened 2026-04-09, closed 2026-04-25; >6 months): `This domain [open.z.ai] does not resolve via DNS from Europe (tested from Spain, Ubuntu 24.04 server). Z.ai support confirmed that open.z.ai is not deployed globally and European users must use open.bigmodel.cn … The correct working endpoint is open.bigmodel.cn/api/coding/paas/v4 (verified with curl, ~4s response time)`.
- Own probes through the local proxy (exit Santa Clara, US, AS11414): `POST open.bigmodel.cn/api/paas/v4/chat/completions` → HTTP 401 `令牌已过期或验证不正确` in 1.32 s; `/api/anthropic/v1/messages` → 401 in 1.28 s; `api.z.ai/api/anthropic/v1/messages` → 401 in 1.80 s. Direct from the Shanghai line: all four endpoints 401 in 0.18–0.66 s (TLS 0.26 s to open.bigmodel.cn, 0.56 s to api.z.ai). DNS: `open.bigmodel.cn` → `ga-bp1xx4zeq2vdhs6phnk7v.aliyunga0018.com` → 47.86.227.136 / 47.86.179.135 (Alibaba Global Accelerator); `api.z.ai` → `ga-bp19xpcxwu77sm2gcpqo3.aliyunga0017.com` → 8.217.100.151 / 8.217.233.95.
- zai-org/feedback#1366 (2026-11-02): `固定环境（非本地网络问题，中国大陆直连，无 VPN / 无代理）` reaching zcode.z.ai.

Note: the Shanghai egress is an enterprise (PCCW) line; consumer-ISP reachability of api.z.ai is corroborated only by #1366. Both hosts sit behind Alibaba GA, which is consistent with no per-region blocking.

---

## F14 — Platform-level throttling; multi-day 429/1305 incident (June 2026); nightly gateway failures (Nov 2026); no status page

**Verdict: corrected** (every fact checks out, but both incidents are Coding-Plan / ZCode-gateway incidents, not standard pay-as-you-go API incidents).

What I read / ran:
- `/cn/api/rate-limit` §三.4: `平台在以下情况下可能触发 平台级保护机制： 某一模型在短时间内整体访问量激增 / 底层算力资源处于高负载状态 / 平台进行系统维护、扩容或异常恢复 … 此类情况属于 平台服务过载，与单一账户的调用行为无直接关系。`
- GitHub zai-org/GLM-5#83 via api.github.com (opened 2026-06-17T04:36Z, closed 2026-07-20, last comment 2026-09-14, 15 comments): `285 × HTTP 429 errors from midnight through ~16:51 (Beijing time) - Failure rate: ~50% of all requests … Error: 429 该模型当前访问量过大，请您稍后再试`; Environment: `Endpoint: zhipuai/glm-5.2 via OpenClaw Gateway (OpenAI-compatible API) - Account type: Paid GLM Coding Plan`; maintainer zRzRzRzRzRzRzR 2026-07-20: `you are welcome to provide feedback through our official API feedback channel and follow our pinned issue #93`; vonpupp 2026-09-14: `I am having similar problems, always hitting the limits.`
- GitHub zai-org/feedback#1366 (2026-11-02): title `[Bug] 免费 300M GLM-5.3-Flash 额度在 23:00–09:00 窗口内几乎不可用：zcode.z.ai 网关连续 502/503，10 分钟内 20 次请求全部失败、0 次成功`; body: `本条是免费 Start Plan 包 + zcode.z.ai 网关，#1214 是付费 Coding Plan + api.z.ai`.
- Status hosts: `https://status.bigmodel.cn` → 301 → `https://bigmodel.cn/`; `status.z.ai` → NXDOMAIN; `https://bigmodel.cn/status` → 200 generic SPA shell (`<meta name="author" content="北京智谱华章科技股份有限公司"/>`).

Correction: label the June incident "Coding Plan subscriber, GLM-5.2 via an OpenAI-compatible gateway" and the Nov incident "free Start Plan quota on the zcode.z.ai gateway". Coding Plan concurrency is explicitly dynamic (`平台会根据资源进行动态调整`), so these are indirect evidence for the standard API. 1305 is nevertheless a platform-level code; the defer/backoff and off-peak advice stands.

---

## F16 — Monthly cost on paid siblings

**Verdict: corrected** (GLM-4.7-FlashX, GLM-5.3-Flash, GLM-5.3 and the prewarm reproduce exactly; GLM-4.7 and GLM-4.5-Air totals understate the ≥32K input tier that the 35k-token consolidate prompt falls into).

Verified prices (`/cn/guide/start/pricing`, 元/百万 Tokens in | out): GLM-4.7-FlashX `0.5 | 3`; GLM-5.3-Flash `0.8 | 2.8`; GLM-4.7 `输入 [0, 32K)，输出 ≥0.2K | 3 | 14` and `输入 [32K, 200K) | 4 | 16`; GLM-4.5-Air `输入 [0, 32K)，输出 ≥0.2K | 0.8 | 6` and `输入 [32K, 128K) | 1.2 | 8`; GLM-5.3 `8 | 28`.

Recomputed (30-day month; content 25–100/day × 2k in + 4k out; lookups 150 × 1k/0.5k; consolidate 300 × 35k/3k; SVG 1,200 × 1.5k/2k; prewarm 912 × 2k/4k; cache ignored):

| Model | Content /mo | Other jobs /mo | Total /mo | Prewarm | Digest said |
|---|---|---|---|---|---|
| GLM-4.7-FlashX | ¥9.8–39.0 | ¥16.4 | **¥26–55** | ¥11.9 | same |
| GLM-5.3-Flash | ¥9.6–38.4 | ¥19.4 | **¥29–58** | ¥11.7 | same |
| GLM-4.5-Air | ¥19.2–76.8 | ¥36.2 (digest ¥30.2) | **¥55–113** | ¥23.3 | ¥49–107 |
| GLM-4.7 | ¥46.5–186.0 | ¥96.9 (digest ¥84.6) | **¥143–283** | ¥56.5 | ¥131–271 |
| GLM-5.3 | ¥96–384 | ¥194.1 | **¥290–578** | ¥116.7 | same |

The difference is entirely the consolidate job priced at the [0,32K) tier in the digest. Not in the digest: Batch API at 50% and cache-hit pricing (FlashX ¥0.1/1M) — see omissions.

---

## Omissions / new findings

1. **Batch API fits the 912-call prewarm and sidesteps the concurrency limit, but requires 实名.** `/cn/guide/tools/batch`: `通过 Batch API，开发者可以通过文件提交大量任务，且价格降低 50%（GLM-4-Flash 免费）、无并发限制。`; `单个文件最多支持 50000 个请求且大小不超过 100M`; `预计任务将在 24 小时内完成，如果任务超过 7 天未处理完，将自动取消`; FAQ `价格是标准 API 的 50%`; `调用 Batch API 必须实名认证 … 成功认证后，将免费获得 500 万 tokens`. Whether `glm-4.7-flash` is accepted in Batch is not stated (only "GLM-4-Flash 免费"). Also equity: `Batch 推理按实际扣费金额计算积分`.
2. **Windowed usage caps exist in the platform's error vocabulary**, so "无 Token 消耗上限" is marketing, not a documented property of free models: `/cn/faq/api-code` row `| 1308 | 429 | 已达到 ${number} ${unit} 的使用上限。您的限额将在 ${next_flush_time} 重置 |`. The fallback should parse 1308 and defer until `next_flush_time`, in addition to 1302/1305.
3. **Route A has a hard-stop risk in the CLI's budget guard.** The binary contains `Session cost is not a number (a usage or pricing fault upstream); refusing to continue under --max-budget-usd`, and `runner.py` (`build_argv`, lines 124–149) always passes `--max-budget-usd`. If the GLM gateway's `usage`/model fields yield a non-numeric client-side estimate, every call aborts regardless of the "unknown models" warning path. The decisive one-request test must inspect `total_cost_usd` and the exit subtype, and the wrapper may need `WD_AI_EXTRA_ARGS`-level control over the budget flag.
4. **The Anthropic-compatible path has no published parameter/model compatibility table**, and shows non-standard behaviour already at the unauthenticated layer: `/cn/guide/develop/claude/introduction` only says `某些场景下智谱与 Claude 接口仍存在差异`; `GET /api/anthropic/v1/models` returns HTTP 200 with `{"code":401,…}`; the error envelope is `{"error":{"message":…,"type":"1001"|"401"}}` rather than Anthropic's `authentication_error` types; handling of `thinking` (incl. the CLI's adaptive-thinking default), `anthropic-beta` and `output_config` is undocumented and could not be probed without a key. The Python-shim route (OpenAI-compatible API) avoids all of this.
5. **The no-实名 claim is current practice, not a guarantee, and conflicts with other official text.** Privacy policy §二(二): `如您需要使用 API Key 等功能，我们可能需要对您进行实名认证`; Batch doc: `调用 Batch API 必须实名认证`; FAQ: `目前调用 API 并不强制要求实名认证`; a Jan-2026 third-party post (learnku) states the free API `需实名认证`. Since recharging needs 实名 anyway, plan for it (ID + 支付宝 face check, "即时完成").
6. **Per-region model availability diverges and must be configured per region.** Z.ai pricing (`docs.z.ai/guides/overview/pricing`, USD) still lists `| GLM-4.5-Flash | Free | Free | Free | Free |` next to `| GLM-4.7-Flash | Free | Free | Free | Free |` and `| GLM-5.3-Flash | $0.15 | $0.03 | Limited-time Free | $0.50 |`, while BigModel retired GLM-4.5-Flash on 2026-01-30; Z.ai's OpenAPI chat enum lists only `glm-5.3, glm-5.2, glm-5.1, glm-5, glm-4.7, glm-4.6` (no `glm-4.7-flash`), so the free model's presence on `api.z.ai` should be confirmed with one call rather than assumed from the price list. Z.ai FAQ also notes `3DS verification is not supported in our platform at this moment` for card recharges.
