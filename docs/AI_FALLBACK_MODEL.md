# word-Dance：Claude 不可用时的国产免费备选模型与自动切换方案

> 日期：2026-11-05 · 代码基线：`main` @ `9ab13a5` · 应 sqin 的要求由 Claude 撰写
>
> 你的问题：如果 Claude 无法使用，评估并匹配国内最优的免费模型做备选；当 Claude 不成功时直接用备选方案。本文回答两件事：选哪个模型（以及免费档不够时的升级档），怎么让切换自动发生并在 Claude 恢复后自动切回。Anthropic 政策与许可问题按你的要求继续搁置，只记录各国产厂商自己的条款（免费档能否用于产品、是否用数据训练、是否要实名、境外能否调用）。
>
> 方法：先从本机对 17 个国产模型接口做了未认证探测（确认路径存在与可达），再用 5 个调研切片（1 个读代码、4 个联网）各配一名独立核验者（50 条关键结论：30 条确认、20 条修正、0 条推翻）；然后 3 套独立架构方案（Claude CLI 网关 / OpenAI 格式 HTTP 适配器 / Anthropic 格式 HTTP 适配器）由 3 位评审从工程正确性、你的时间与可运维性、输出质量与条款三个视角打分并逐条找错；同一工作流里还按契约规格实现了评测脚本并由另一名代理独立运行验证。原始材料见 [`docs/analysis/2026-11-04-ai-fallback/`](analysis/2026-11-04-ai-fallback/)。
>
> 没有任何国产模型被真正调用过（没有 key、不花钱），所以模型质量结论来自公开证据与代码契约，最终由评测脚本在你拿到 key 后约 10 分钟定夺。工作量按你一个人业余做估算。

## 0. 一页结论

**0.1 选哪个。** 国内目前**永久免费、可用于自建应用、能力够用**的文本模型只有一个：智谱 **GLM-4.7-Flash**（30B-A3B，200K 上下文，128K 输出，工具调用，JSON 模式，可关思考；2026-01-19 上线，接替已下线的 GLM-4.5-Flash）。它的短板是稳定性与并发（免费档第三方报告 1 个并发、高峰限流、窗口配额以 429 返回），恰好是切换机制本来就要处理的东西。免费模型更强的魔搭 ModelScope（提供 DeepSeek-V4.1-Flash、GLM-5.2 等，每天 2,000 次）官方定位「非商业化、非盈利」、单模型约 200 次/天、配额随时削减，只适合做评测参照；硅基流动的免费 7–9B 小模型差一个档次，只配做最后应急；百度、腾讯的免费模型已于 2026 年 6 月下线，讯飞 Spark Lite 8K/4K 且无工具调用，不可行。免费档不够时的**升级档**是阿里百炼按量付费的 **qwen3.7-flash**：严格 `json_schema`、1M 上下文、按本应用工作量约 **¥15/月**（前提是显式关闭默认开启的思考），按量数据不用于训练，且与智谱不在同一平台，可做第二条腿。

**0.2 怎么切。** 三位评审一致选择「自己掌握传输层」：在 `runner.run_claude` 之后加一个 OpenAI 格式的 HTTP 适配器（`json_object` + 把 schema 贴进系统提示 + 用 `jsonschema` 按原始 schema 校验 + 一次修复重问），加一个粘滞的提供方状态机。规则：**硬触发**（认证失败——包括本机账本里那串「托管设置拉取失败」、403、402/余额不足、二进制缺失、配额窗口）→ 暂停该提供方 30 分钟、切到备选、**立刻用备选重跑同一组已领取的任务**；**软触发**（连续 3 次过载 / 2 次超时 / 2 次网络错误）→ 再切；`invalid_output` 与内容过滤**永不触发**切换；每 30 分钟用现成的探测机制试 Claude，成功即切回；用户侧的「AI 不可用」门控改为「任一提供方可用」。上周那次 8 小时没有 AI 的故障，在这个设计下变成约 20 秒的空档加每 30 分钟一次免费探测。

**0.3 为什么不直接拿 Claude CLI 当网关。** 现有 runner 已把 `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` 透传给 `claude`，智谱、百炼、DeepSeek 等都有 Anthropic 格式端点，所以零代码就能把同一条命令打到国产模型。但核验出七个坑（结构化输出靠一个不强制的合成工具调用、思考关不掉、成本估算为 0 让美元上限失明、溯源要靠变通、CLI 仍连 anthropic.com、企业托管设置可能直接堵死令牌认证、Anthropic 文档明说不支持）。结论：**今天用它做 10 分钟的手工验证和应急开关可以，不能当长期的自动切换契约。**

**0.4 评测已经准备好。** `scripts/eval_provider.py` 与 `scripts/mock_provider_server.py` 复用生产提示词、schema 与后验证函数，支持 OpenAI / Anthropic / Claude CLI 三种传输，在本地 mock 上六种格式×策略组合全部 100% 通过，15 种错误模式的状态映射与安全属性（只读打开数据库、key 只从环境变量读、绝不自动运行真 `claude`）已由独立代理验证。拿到智谱 key 后一条命令约 10 分钟出成绩单；门槛：schema 有效 ≥98%、条目通过 ≥95%、例句含词头 ≥97%、p95 延迟 ≤ 超时的 60%、截断 0。

**0.5 时间与钱。** 第 0 天约 0.3 人日、¥0（开户、跑评测、改正则、可选的应急包装脚本）；MVP 约 7–8 人日（业余约 3–4 周）即具备自动切换；完整约 11–12 人日。运行成本：免费档 ¥0；升级档约 ¥15/月；全库预生成若放在升级档约 ¥3.3。

**0.6 需要你定的事**（第 7 节）：智谱国内站还是 Z.ai（后者承诺不训练但免费模型是否在列待验）；升级档选百炼还是同 key 的 GLM-4.7-FlashX；备选模型能做哪些任务（建议先只做校验与整理，例句生成等评测通过再开——2026-11-05 决定：切片 2 起例句默认走备选，评测仍建议补做，不达标则从 `WD_AI_FALLBACK_KINDS` 去掉 `content`，见 4.3 / 6）；学习者的备注能否发给国产模型；Claude 恢复后备选生成的卡片是保留还是重做；美元上限用尽时是否也切到免费模型；是否现在就实名。

## 1. 备选模型必须满足什么（代码契约，已核实）

- **唯一的接缝是 `wd.ai.runner.run_claude`。** 四个任务处理器（例句生成、自添词校验、夜间整理、SVG 示意图）只消费 `ok/status/structured/cost_usd/model_used/call_id/error`，换模型不用改处理器；所有 Anthropic 特定的东西都在 `runner.py`（argv、子进程环境白名单、结果信封解析、正则分类）、`budget.py`（美元预算）、`ledger.py`（`model_requested/model_used`，没有 provider 列）、`probe.py`（flag tier）与 `common.AUTH_BANNER_ZH`。`ClaudeRunner` 协议与 `Runner` 类从未被实例化，`probe._attempt` 直接以 CLI 专有参数调用 `run_claude`，所以提供方门面要保留这个函数签名，并给非 CLI 提供方一条无 tier 的探测路径。（contract F1 及核验）
- **五个 schema 只用 `type/properties/required/items/minItems/maxItems/enum/description`**：整数枚举（`difficulty` 1–5）、嵌套对象数组、整理任务里的「数组的数组」（`confusable_groups`，内层 2–4 项）。测试禁止在 schema 文件里加 `additionalProperties`，所以要在调用时转换：OpenAI 严格模式需要每个对象加 `additionalProperties:false`；Anthropic 自家的 `output_config` 只支持 `minItems` 0/1，`maxItems` 要挪进描述。（contract F2）
- **输出还要过严格的后验证**：`word` 必须逐字等于请求的词；`meaning_zh` 必须含中文；每条例句 10–240 字符（content-v2 起下限 10，容纳小学短句）、≥70% ASCII、**必须包含词头、其屈折形式或 ≥4 字母的前缀**；至少 3 条可用例句（最后一次尝试 2 条）；`difficulty` 必须是 JSON 整数。pydantic 镜像是宽松转换（`true` 会被当成 1），今天挡住这些的是 Claude CLI 自己的 schema 校验，所以 HTTP 适配器必须先用 `jsonschema`（venv 里已有 4.26，但只在 `requirements-dev.txt` 里，要提升为运行时依赖）按原始 schema 校验再进镜像。（contract F4 及核验）
- **实测提示词大小**：10 词例句调用 6.3 KB（系统 2,993 + 用户 1,585 + schema 1,740 字节，约 1.8k token；CLI 自己再加约 1.5k）；20 个字符串的校验 3.9 KB；夜间整理典型 5 KB、最坏 56.5 KB（约 17k token，需要 ≥32k 上下文）；SVG 1.1 KB。输出按 2.55 字节/token 校准：10 词例句约 3,800 token，Sonnet 上 30 秒；整理每项约 100 token；SVG 600–1,050 token。超时 180/120/240/120 秒；一个 30 token/秒的模型跑 10 词要约 130 秒，所以备选路径应把批大小降到 5 并把超时乘 1.5。（contract F3）
- **分类器只认 Claude 的字符串**：`AUTH_RE` 不匹配 403/forbidden/「Request not allowed」、402/余额不足、用量上限、`ENOTFOUND/ECONNREFUSED`，也不匹配智谱的中文 401 正文（「身份验证失败」「令牌已过期」）、硅基流动的「Token is invalid」；`OVERLOADED_RE` 没有 `\b429\b`。这些今天都落到 `error` → 退避 → 二分 → 死信，而不是暂停或切换。（contract F6、zhipu F10、others 核验）
- **`auth`/`spawn_error` 会暂停全部 AI 30 分钟**（`kv.claude.paused_until`），这个键有约 10 处读者（预算、worker、调度器、批次、词条、生词库、诊断、管理页），外加两套独立的 `ai_enabled` 实现；要让「主模型暂停但备选在跑」对用户可见，门控必须改成「任一提供方可用」。经核验，`routers/words.py`、`routers/bank.py`、`jobs/scheduler.py`、`services/batches.py`、`admin_ops.py` 已经通过几个辅助函数读这个键，所以只改辅助函数即可，再加一条 grep 测试禁止新增直接读取。（contract F11 及核验、J2 嫁接）
- **溯源不需要改表**：`word_contents.model` 已记录生成模型 id；`ai_calls` 需要加 `provider` 列（追加式迁移 `0010_ai_provider.sql`；上周策展方案里的 `0010_curation_columns.sql` 顺延为 0011 并去掉它的 provider 列）；`WD_AI_FALLBACK_MODEL` 这个键已被占用（它是 Claude CLI 自己的 `--fallback-model`，只能在 Claude 模型间切换，且在认证/限流错误上从不触发），引入提供方级备选键之前要先改名为 `WD_AI_CLI_FALLBACK_MODEL`。（contract F10、F18）
- **要打破的真实故障循环**：本机账本第 33–47 次调用全部因企业组织的托管设置拉取失败而失败，被分类为 `auth`，14 条 `claude_auth` 事件每 30 分钟一次持续 6 小时以上，没有任何出口。备选方案的第一个硬触发就是这个字符串。（contract F16）

## 2. 候选模型评估（2026-11-04 核实）

工作量假设：每次 10 词例句调用约 2k 输入 + 4k 输出 token，每天 100 次，另有少量校验、≤10 次整理、≤40 张 SVG；一次性预生成 912 次调用。费用按各家官网按量价格换算，不含缓存折扣。

| 候选 | 免费情况 | 限额 | 上下文 / 最大输出 | 结构化输出 | 接口格式 | 条款与数据 | 境外 IP | 质量证据 | 稳定性 | 本应用成本 |
|---|---|---|---|---|---|---|---|---|---|---|
| **智谱 GLM-4.7-Flash**（30B-A3B） | **永久免费**（无合同承诺；历史上约每年换代并自动路由：GLM-4.5-Flash 已于 2026-01-30 下线并路由到 4.7-Flash；GLM-4-Flash-250414、GLM-Z1-Flash 仍免费；GLM-5.3-Flash 收费 ¥0.8/¥2.8） | 按并发限制，控制台才看得到数字，第三方报告免费档 **1 个并发**，15:00–23:00 高峰限流；1302/1305/1308 都以 HTTP 429 返回 | 200K / 128K | `json_object` + 工具调用（`tool_choice` 仅 auto）、可关思考 | OpenAI 格式 + Anthropic 格式（`open.bigmodel.cn/api/anthropic`，标准 key 即可，但免费模型是否在该端点可用未经文档证实） | 调用「目前」不需实名（充值、Batch 需要）；大陆隐私政策允许匿名化训练且 API 无退出项；Z.ai 承诺不训练不存储（但其接口模型枚举里没有 glm-4.7-flash，待验） | 不封；另有 `api.z.ai` | BFCL v3 74.6；LMArena 中文榜未上榜；无 IFEval 公开数据 | 弱：文档明示高峰动态限流，2026-06 多日 429/1305，2026-11 夜间网关故障，无状态页 | ¥0；付费同类 GLM-4.7-FlashX ≈ ¥26–55/月 |
| 魔搭 ModelScope API-Inference | 永久免费 | 2,000 次/天/账号，单模型约 200 次/天，单并发，00:00 重置，配额会不打招呼削减 | 随模型 | 随模型 | OpenAI 格式 + Beta 的 Anthropic 格式 `/v1/messages` | 官方定位「非商业化、非盈利」；需绑定阿里云账号并实名；模型列表频繁更替 | 可达 | 今天提供 DeepSeek-V4.1-Flash（LMArena 中文 1523，对比 Claude Sonnet 5.5 的 1545）、GLM-5.2、Qwen3.5-397B、Qwen3.8-27B | 中 | ¥0 |
| 硅基流动 免费小模型（Qwen3-8B 等 ≤9B） | 永久免费 | 固定 RPM/TPM | 32K 级 | `json_object`；Anthropic 端点支持工具 | OpenAI 格式 + Anthropic 格式（`api.siliconflow.cn/v1/messages`，不是 `/anthropic`） | 实名解锁全部免费模型；承诺不训练 | 待测 | Qwen3-8B IFEval 83–85、BFCL v3 60–68 | 中 | ¥0 |
| 讯飞星火 Spark Lite | 免费 | QPS≈2 | 8K / 4K | 无工具调用 | OpenAI 格式 | — | 待测 | 无任何榜单证据 | — | 不可行 |
| 百度千帆 ERNIE Speed/Lite | 2026-06 已下线；现价目表无免费文本模型 | — | — | — | 千帆另有 Anthropic 格式端点，承载 DeepSeek/Kimi 等付费模型 | — | — | — | — | 不适用 |
| 腾讯混元 hunyuan-lite | 2026-06-22 已下线；TokenHub 新用户 100 万 tokens/90 天 | — | — | — | OpenAI + Anthropic（含新加坡端点） | — | — | — | — | 不适用 |
| 阿里百炼 qwen3.7-flash | 一次性每模型 100 万 tokens、90 天、北京地域、需实名；之后按量 | 30,000 RPM / 500 万 TPM | 1M / 131K | **严格 `json_schema`**；默认开启思考并计入输出计费，必须显式关闭 | OpenAI 格式 + Anthropic 格式（用工作空间域名 `{WorkspaceId}.cn-beijing.maas.aliyuncs.com`；旧域名 2026-09-30 起不再更新） | 按量调用的数据不用于训练；编码计划/Token 计划禁止后端使用且授权训练，不要用 | 可达；东京地域可开但无免费额度 | 无公开榜单分数（同系 qwen3.8-flash SuperCLUE 66.41） | 好（99.9% SLA，下线提前 3 个月通知） | 输入 ¥0.2 / 输出 ¥0.8 每百万（≤32K）→ **≈ ¥15/月**，预生成全库 ≈ ¥3.3；qwen3.8-flash ≈ ¥54/月 |
| DeepSeek deepseek-flash | 无免费 | 无官方限制 | 1M | `json_object` + 严格工具调用（思考开启时不能强制工具）；Anthropic 端点忽略输出格式；思考默认开 | OpenAI + Anthropic 格式 | 输入默认可用于训练，可退出 | 全球可用 | LMArena 中文 1523 | 2026 年第 19 次故障（11-03） | ≈ ¥54 错峰 / ¥108 高峰 |
| 火山方舟 Doubao-Seed-2.0-mini / 2.1-lite | 新用户每模型 50 万 tokens 限时活动 | — | 1M / 256K | 严格 `json_schema`（默认 `max_tokens` 4k，要调到 ≥8k） | OpenAI + Anthropic 格式 | 条款仅授权在中国大陆使用，东京服务器不在其文字范围内 | 待测 | — | 好 | ≈ ¥25 / ¥37 |
| MiniMax-M3 · Kimi K3.1 Pro | 无 / 无 | — | — | 工具调用 / 严格 schema | Anthropic 格式 | — | 地区绑定 / 全球 | — | — | ≈ ¥113 / ≈ ¥894（思考常开） |
| 参考：Claude Sonnet 5.5 | — | — | — | — | — | — | — | LMArena 中文 1545 | — | 实测 $0.0048–0.0059/词 |

两点横向结论：所有结构化输出研究都表明「schema 合规容易、语义正确难」，所以 `validate_item` 的严格后验证必须保留；≥30B 的 Flash 级 MoE 模型与 7–9B 免费小模型是两个档次，`consolidate_bank` 只能给 ≥128K 上下文的模型。（others Part 3、zhipu F8、alibaba F10）

### 2.1 结论与任务分工

| 任务 | Claude（主） | 备选第一腿：GLM-4.7-Flash（免费） | 升级档 / 第二腿：百炼 qwen3.7-flash | 说明 |
|---|---|---|---|---|
| `lookup_word` 自添词校验 | 20 个字符串/次 | **第 1 天就开**；`max_tokens` 8192（20 个字符串约 3,700 输出 token，4096 没有余量）；提示词里补「JSON」字样 | 可 | 校验结果会写库（判为非英文会把词下架、改词头会合并），所以评测要单看 `is_english` 的假阴性 ≤2%，并考虑先以「建议」而非直写落地 |
| `consolidate_bank` 夜间整理 | 是 | **第 1 天就开**（200K 远大于 17k token 最坏值），`max_tokens` 12288 | 可 | 现有应用规则会把不安全的建议降级为 `ok`；备注是唯一进提示词的用户文字，见第 7 节隐私决策 |
| `generate_content` 用户触发的例句生成 | 批 10 | **切片 2 起默认开**（2026-11-05 决定；第 5 节评测仍建议补做，不达标则从 `WD_AI_FALLBACK_KINDS` 去掉 `content`）；批 5（`WD_AI_FALLBACK_BATCH_SIZE`，实际 `min(WD_AI_BATCH_SIZE, …)`）、`max_tokens` 8192、超时 ×1.5；备选判非种子词 `valid=false` 不下架词——只有 CLI 可以让词失效（CLAUDE_INTEGRATION §6.4） | 是，批 10 | 例句含词头是弱模型最常挂的规则 |
| `generate_content` 预生成计划（优先级 ≥90） | 是 | **默认不开**：912 次调用在单并发、会限流的免费档上要 15–30 小时，且成本为 0 时预算停止条件永不触发 | 可（≈ ¥3.3） | 预生成任务在切换期间顺延到主模型恢复 |
| `generate_svg` | 是 | **不开**：被拒绝的 SVG 会让 `image_state='failed'` 且永不重试 | 不开 | 切换期间 SVG 任务顺延，照片管线照常 |
| 探测 | 分 tier 的 CLI 探测 | 无 tier 的一次 `probe_v1` 调用（`wd ai-check --provider fallback`） | 同左 | 精确匹配答案是最便宜的枚举/数组能力检查 |

## 3. 为什么不用 Claude CLI 当网关，但今天可以用它应急

现有 runner 已把 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 透传给 `claude` 子进程，一个导出这些变量的第二个包装脚本就能让同一条命令打到国产模型的 Anthropic 格式端点（本机探测：智谱、Z.ai、DeepSeek、月之暗面、百炼、火山、MiniMax 的路径都存在，未认证请求返回 401/403，TLS 握手 0.08–1.2 秒）。核验后的七个坑：

1. `--json-schema` 的实现是一个叫 `StructuredOutput` 的合成工具调用加一个 `output_config.format` 测试性字段；第三方上游会拒绝该字段，需要 `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1`（CLI ≥ 2.1.288，本机 2.1.292）；工具调用不是强制的，JSON 可靠性只靠模型听话加 CLI 重试，而且对二进制的字符串扫描没有证实 `-p` 顶层路径在该开关下仍有工具回退——这是必须用一次真实调用验证的前提。
2. 对不认识的模型 id，CLI 会发自适应思考字段且无法关闭（`MAX_THINKING_TOKENS=0` 只是不发该字段，厂商随即按默认开启思考），默认 `max_tokens` 32000、上下文假定 200K；对百炼、DeepSeek 这类默认开思考的模型，输出计费可能是可见 JSON 的数倍。
3. `total_cost_usd` 是客户端估算，外部模型 id 的 `costBasis` 为 `unknown` → 应用的日/月美元上限对备选调用失明，预生成的预算停止条件也不会触发；二进制里还有「Session cost is not a number … refusing to continue」这条拒绝路径。
4. `model_used` 取结果信封里的模型名，网关若把 Claude 别名映射成自家模型（DeepSeek 文档就是这么做的），`word_contents.model` 会写成 Claude 的名字；必须让 `WD_AI_MODEL` 携带厂商 id，并在包装脚本里设置 `ANTHROPIC_DEFAULT_SONNET_MODEL` 等映射。
5. CLI 仍会向 anthropic.com 发非必要流量（版本检查、遥测、快速模式检查），需要 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`，并用独立的 `CLAUDE_CONFIG_DIR` 避开企业登录档案；若企业托管设置带 `forceLoginMethod`，文档明说令牌认证「不能共存」，整条 CLI 网关路线被堵死，一次 `wd claude-check` 可验证。
6. Anthropic 文档写明不支持通过任何网关把 Claude Code 路由到非 Claude 模型，`--fallback-model` 也不能跨提供方。（这是文档陈述，政策评估按你的要求推迟。）
7. 各家错误正文（中文 401、`Token is invalid`、429 的业务码）都不被现有正则识别，备选路径上的认证失败反而会触发 30 分钟全局暂停。

**今天的应急开关（A0，零代码，≈1 小时）**：在数据目录建第二个包装脚本 `bin/claude-fallback`，导出 `ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic`、从 0600 文件读入的 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_DEFAULT_SONNET_MODEL=ANTHROPIC_DEFAULT_HAIKU_MODEL=ANTHROPIC_DEFAULT_OPUS_MODEL=glm-4.7-flash`、空的 `CLAUDE_CONFIG_DIR`、`CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1`、`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`、`DISABLE_AUTOUPDATER=1`、`MAX_THINKING_TOKENS=0`，不带任何代理变量，然后 `exec` 真正的 `claude`。先在一个**临时数据目录**（复制一份数据库，绝不用线上目录）里以 `WD_CLAUDE_BIN=<包装脚本> WD_AI_MODEL=glm-4.7-flash wd claude-check` 验证：它同时回答「企业托管设置是否堵死令牌认证」「`modelUsage` 与 `total_cost_usd` 对外部模型怎么写」「枚举与数组能否精确匹配」三个问题。真要应急时改 `.env`：`WD_CLAUDE_BIN=<包装脚本>`、`WD_AI_MODEL=glm-4.7-flash`、`WD_AI_FALLBACK_MODEL=""`、`WD_AI_BATCH_SIZE=5`、`WD_AI_CONCURRENCY=1`、`WD_AI_TIMEOUT_CONTENT_SEC=270`、`WD_SVG_VIA_CLAUDE=0`，重启；恢复时反向改回。此时美元上限失明、结构化输出靠不强制的工具调用，所以只是桥梁。

## 4. 推荐架构：HTTP 适配器 + 自动切换

### 4.1 Claude 失败那一刻发生什么

1. 处理器像今天一样调用 `common.claude_call`；它先问 `failover.choose(kind, priority)` 当前该用哪个提供方（粘滞状态 `kv.ai.active_provider`，默认 `claude`），再向该提供方预留预算、调用、分类。
2. Claude 返回硬触发（例如 stderr 里那串「Your organization requires remote managed settings to load」被归为 `auth`）：`failover.record_failure` 作为**唯一写者**把 `claude.paused_until` 设为 30 分钟后、把 `ai.active_provider` 置为 `fallback`、写 `ai_failover` 事件、安排 30 分钟后的恢复探测，然后**同一组仍被领取的任务立刻在备选上重跑**：`providers/openai_http.py` 向 `https://open.bigmodel.cn/api/paas/v4/chat/completions` 发送系统提示（原文 + 「只输出符合以下 JSON schema 的 JSON」+ 压缩 schema）与用户提示（原文含 `<items>` 块），`response_format={"type":"json_object"}`、`thinking={"type":"disabled"}`、`max_tokens` 按任务、`trust_env=False`（不继承 shell 代理）；响应先过 `jsonschema`（原始 schema）→ pydantic 镜像 → 处理器后验证，schema 不合格就带着校验器的错误信息重问一次；账本写 `provider='fallback'`、`model_requested='glm-4.7-flash'`、成本按 CNY 价目表（免费 = 0）。
3. 之后的任务继续走备选；`routers/words.py:326` 等用户侧检查改为问 `failover.availability()`，所以学习者看不到 503，只是例句来自另一个模型。
4. `ClaudeWorker.housekeeping` 每 5 分钟检查，到点就用现成的 `probe.check` 探一次 Claude（固定在已记录的 `claude.flag_tier`，只试一次，不改写 tier；失败的探测成本为 0，成功约 $0.004）；成功 → `ai.active_provider=claude`、清掉暂停、写 `ai_failback`；失败 → 下一次 30 分钟后（持续 6 小时后改 60 分钟）。一次成功的普通 Claude 调用、一次成功的手动探测（`wd claude-check`、管理页「探测 claude」）或管理员「恢复」同样触发切回。
5. 备选自己失败走同一张表（它自己的 `ai.fallback.paused_until`）；两边都挂时任务像今天一样顺延，横幅写「AI 暂时不可用（主模型与备用模型均失败），任务已排队等待」。

### 4.2 失败 → 动作表

| 信号 | 对主模型 | 对备选 | 冷却 / 顺延 | 预算与小时上限 |
|---|---|---|---|---|
| `auth`：未登录、401、凭据、**托管设置字符串**、令牌已过期、身份验证失败、Token is invalid、用量上限字样 | **硬**：暂停 30 分钟、切换、立即重跑 | 硬：备选暂停 30 分钟 | 30 分钟；每 30 分钟探测 | 失败的调用计入两边的小时上限，成本 0 |
| 余额/配额：402、智谱 1113、百炼 Arrearage / FreeTierOnly、余额不足、欠费 | 硬 | 硬，**暂停 24 小时**（需要人工充值，不必每 30 分钟撞一次） | 24 小时 | — |
| 403 / forbidden / Request not allowed（地区封锁） | 硬 | 按正文归为认证或余额 | 同 auth | — |
| `spawn_error`：二进制缺失 / 备选 404、模型不存在 1211、缺 key 或 URL | 硬 + `claude.available=0` | 硬 + `ai.fallback.available=0`，直到一次备选探测或调用成功，或管理员恢复 | 30 分钟 | — |
| 过载：429、1302、1305、5xx、529 | **软**：顺延 2 分钟 × 次数（今天的行为），**连续 3 次切换**；连续 6 次仍触发今天的 15 分钟暂停 | 软：按 `Retry-After` 顺延，连续 3 次切回主模型（若主模型未暂停）或等待 | `Retry-After` ≤ 10 秒时适配器内先重试一次 | 计入；成本 0 |
| 智谱 1308 配额窗口（带 `next_flush_time`） | — | **硬**：备选暂停到窗口重置，任务顺延到该时刻 | 到窗口重置 | — |
| 网络：ENOTFOUND、ECONNREFUSED、ECONNRESET、超时类连接错误 | 软：顺延 2 分钟，**连续 2 次切换** | 同左 | — | 状态记为 `overloaded` 并以 `network:` 前缀标注（`ai_calls.status` 的 CHECK 列表不能加值） |
| `timeout` | 软：退避、第二次二分（今天），**连续 2 次切换** | 同左 | — | 备选超时 = 任务超时 × 1.5，是整次调用（首轮 + 行内重试 + 修复轮）的总预算，每个请求只能用剩余预算；剩余不足 15 秒时不再发修复轮并按 `timeout` 结束 |
| `budget`（CLI 的 `--max-budget-usd` 停止） | 永不 | 不适用 | — | — |
| 日/月美元上限用尽 | 永不，除非 `WD_AI_FAILOVER_ON_BUDGET_CAP=1`（则该组在免费备选上运行） | 同样的上限语义 | 顺延到 00:05 / 下月 1 日 | 免费腿 `reserved_usd=0`、`cost_usd=0` |
| `invalid_output`、内容过滤（1301、DataInspectionFailed） | 永不（退避 → 二分 → 死信） | 永不，但连续 3 次无效（每次调用都计数，同一组的重试也算；新一次切换清零）→ 备选质量暂停 30 分钟（`ai.fallback.pause_reason='quality'`）+ `ai_fallback_quality` 事件 | — | 截断（`truncated:`）时该组像 `budget` 一样立即二分且不消耗尝试次数（切片 2 修订）；仍可提高 `max_tokens` 或降批 |
| 成功（普通调用或探测，任何模式） | 重置主模型连击，解除其自动暂停与 `'0'` 可用标记，放行停在该暂停时刻的任务 | 重置备选连击（质量连击 `ai.fallback.streak.invalid` 除外：仅在一组被成功应用、第三次无效、新一次切换或管理员「恢复」时清零；普通调用的 HTTP 成功也不解除质量暂停——探测成功、成功应用一组或「恢复」才解除），同样解除暂停与标记、放行任务 | — | 成本按价目表（免费为 0） |
| 恢复探测成功（`active=fallback` 时） | 切回、清暂停、写 `ai_failback {outage_min}` | — | — | 一次 ≤ $0.05 |

切换期间：例句批大小 5、校验 20、整理/SVG 1；每提供方一把信号量（免费档 1，Claude 最多 3）；每提供方独立的小时上限（备选建议 40，为探测与立即重跑留出全局 60 的余量）；溯源在每一行：`ai_calls.provider` + `model_requested`（厂商 id）+ `model_used`，`word_contents.model` = 厂商 id。

### 4.3 配置键与状态键（主要）

| 键 | 默认 | 含义 |
|---|---|---|
| `WD_AI_PROVIDER` | `claude_cli` | `claude_cli` = 今天；`openai_http` = 只用备选（安装预检不再要求 `claude` 二进制）；`auto` = 主模型 + 自动切换 |
| `WD_AI_CLI_FALLBACK_MODEL` | 空 | 由 `WD_AI_FALLBACK_MODEL` 改名而来的 CLI 自带 `--fallback-model`；旧键非空时启动报错提示迁移 |
| `WD_AI_FALLBACK_KIND` / `_BASE_URL` / `_API_KEY`（或 `_API_KEY_FILE`，0600 文件）/ `_MODEL` | `none` / 空 / 空 / 空 | 备选传输、端点、密钥（加入 `SECRET_KEYS` 掩码）、厂商模型 id |
| `WD_AI_FALLBACK_DIALECT` / `_JSON_MODE` / `_THINKING` | `auto` / `auto` / `off` | 方言（zhipu / bailian / deepseek / ark / generic）决定 JSON 策略默认值（智谱 `json_object`，百炼与火山 `json_schema`，DeepSeek 强制工具）与关思考的字段 |
| `WD_AI_FALLBACK_BATCH_SIZE` / `_CONCURRENCY` / `_TIMEOUT_SCALE` / `_MAX_OUTPUT_TOKENS` / `_HOURLY_CALL_CAP` | 5（切片 2 已实现：备选接手例句组时每次调用的词数，实际为 `min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)`，1–12 截断；领取时即按此数领，已按 10 领取的 CLI 组在备选上重跑前先重组）/ 1（尚未实现）/ 1.5 / 0（= 适配器内置按任务表：lookup 8192、consolidate 12288、content 8192、svg 4096、probe 512）/ 40 | 免费档的形状 |
| `WD_AI_FALLBACK_KINDS` / `_PREWARM` | `content,lookup,consolidate` / 0 | 切片 2 起默认含 `content`（第 5 节评测仍建议做，但不再是默认的前提；去掉 `content` 即例句只走 CLI；空值或仅空白 = 默认）；`svg` 不开；预热组（优先级 ≥ 90）仍不上备选，除非 `_PREWARM=1`（混合了预热成员的组先拆分，可运行的预热积压一起停到 Claude 暂停时刻；`openai_http` 模式下预热组无限期等待） |
| `WD_AI_FALLBACK_PRICE_JSON` / `WD_AI_CNY_PER_USD` | `{}` / 7.2 | 每百万 token 的人民币价目；空 = 免费 |
| `WD_AI_FAILOVER_COOLDOWN_MIN` / `_PROBE_EVERY_MIN` / `_OVERLOADED_AFTER` / `_TIMEOUT_AFTER` / `_NETWORK_AFTER` / `_ON_BUDGET_CAP` / `WD_AI_FAILBACK` | 30 / 30 / 3 / 2 / 2 / 0 / `auto` | 暂停 / 切换规则（冷却是任何模式下的硬失败暂停与备选的质量暂停；探测间隔与三个软阈值只属于 `auto`） |
| 第二腿 `WD_AI_FALLBACK2_*` | — | 完整版：有序提供方链，付费腿只在免费腿暂停或限流时使用 |

状态键：`ai.active_provider`、`ai.failover.{since,reason,trigger_call_id,next_probe_at}`（回切、管理员「恢复」与非 `auto` 模式启动时的 `reconcile_mode` 一并删除）、`claude.paused_until`（保留原名，语义变为主模型的自动暂停）、`ai.claude.streak.{timeout,network}`、`ai.fallback.{paused_until,pause_reason,available,last_probe_at,model_seen,streak.*}`（`pause_reason='quality'` 标记质量暂停）、`ai.paused_until`（管理员手工暂停改为全局键，恢复时清掉所有自动暂停）、`ai.provider_override`（管理页「自动 / 仅 Claude / 仅备用」）。重启时立即探测一次而不是等 30 分钟；`ai.active_provider` 的切换用比较并交换写入，避免并发线程重复切换与重复重跑。

### 4.4 代码改动与工时

| 范围 | 内容 | 人日 |
|---|---|---|
| 第 0 天 | 开户与 key；用评测脚本跑智谱；正则补丁（`managed settings`、403/forbidden/request not allowed、402/余额不足/令牌已过期/token expired/Token is invalid/身份验证失败、用量上限字样、`\b429\b`、网络错误类）——独立可合并，立刻让现有暂停路径认得地区封锁与中文正文；可选 A0 应急脚本 | 0.3 |
| **MVP（自动切换可用）** | `providers/openai_http.py`（zhipu/bailian/generic 方言、schema 转换、价目、`fake_openai` 测试替身）；`failover.py` 状态机（唯一写者）+ `claude_call` 循环 + `handle_failure` 按提供方作用域 + 预算/账本按提供方 + 迁移 0010 + 门控改为 `availability()` + `words.py:326` 的 `can_spend` 带提供方；探测与 `wd ai-check`；配置与改名；管理页最小字段（当前提供方、横幅、账本「来源」列、「自动 / 仅 Claude / 仅备用」开关、带提供方的探测按钮）；切换事件通过现有 webhook 投递通知你（去重 1 次/小时）；`jsonschema` 进 `requirements.txt`；测试、最小文档；真机测试 L1–L6 | **7–8** |
| 完整版 | 第二腿与有序链、每腿信号量与 1308 `retry_at`、管理页健康卡与 7 日备选占比、夜间备选探测（发现免费模型被静默换代）、`regenerate non-Claude` 筛选与「重新入队在备选上失败的词」、校验/整理的写库动作在备选下降级为建议、smoke 步骤、运维手册、防抖、`ON_BUDGET_CAP`、`providers/claude_cli.py` 迁出 | +4 |

契约切片对完整 B 方案的估算是 8–10 人日（含切换、管理面、测试、smoke、文档），字节切片对纯传输层的估算是约 2 人日；上面的 MVP 把两者拼起来：传输约 2 人日，其余 5 人日是让「直接用备选」真正自动化的状态机、作用域改造、门控与测试。

### 4.5 评审补上的盲点（已并入上表）

通知：切换/切回/两边都挂时用已有的 webhook 投递给你（业余运维者可能几天不开管理页，上次故障 8 小时无人知晓）。探测阻塞：`probe.check` 先 tier 1 再 tier 0，在单 worker 线程上最长卡 2 分钟，切换期间固定一个 tier。重启与恢复备份：重启立即探测；`wd restore` 旧备份可能复活过期的粘滞状态，启动时校验时间戳。并发幂等：比较并交换写入 `ai.active_provider`。租约：`queue.STALE_LOCK_MINUTES=15` 与「主模型尝试 + 备选重跑 ×1.5」的整理任务可能超过 15 分钟，信号量等待要受限。备注隐私：整理提示词含 ≤120 字的学习者备注，智谱国内站允许匿名化训练且无退出项——要么只把整理任务给不训练的提供方（Z.ai、百炼），要么加每提供方的「是否发送备注」开关，并告知朋友。校验任务会写库：备选判「非英文」会把词下架、改词头会合并，评测要单列假阴性，必要时在备选下只产出建议。整理的直写（`fill_data`、`invalid_word`）在备选下应降级为建议。高峰即学习时段：智谱 15:00–23:00 限流与朋友学习时间重合，傍晚可优先付费腿。窗口配额未知：1308 证明有周期上限，把控制台限额写进配置并给探测与重跑留预算。死词：在备选上因内容过滤或三次无效而 `failed` 的词，切回后应重新入队（切片 2 已实现：回切时——以及 Claude 暂停在未切换的情况下解除时——重排故障期间死掉的例句 / 校验任务，复活的任务按正常批大小领取、词状态回到 `queued`；切换前死在 CLI 上的任务不算，等夜间重排）。重生成会换卡：`store_content(force)` 会替换学习者正在复习的卡片，只重做未学过的词或保留已学版本（切片 2 修订：复活的强制重生成若其词已有更新的卡片则跳过，`superseded_regenerate`）。管理页统计：今日花费、调用数、7 日每词均价要按提供方分开。密钥轮换：厂商控制台用量与 `ai_calls` 按提供方对账的流程写进手册。

## 5. 评测脚本与上线门槛

`scripts/eval_provider.py`（2,087 行）与 `scripts/mock_provider_server.py`（439 行）已随本方案提交到仓库。它们只读导入生产代码的提示词构建函数、schema、pydantic 镜像与后验证（`content.validate_item`、`words.validate_headword`、整理的目标校验、SVG 清洗、探测的精确匹配），以 `mode=ro` 打开数据库副本，密钥只能通过 `--api-key-env` 从环境变量读取且从不打印，`claude_cli` 传输必须显式指定 `--wrapper` 且拒绝任何解析到 Homebrew 真 `claude` 的路径，mock 只绑定 127.0.0.1。独立验证结论：`pass_with_fixes`（修了两处相对路径处理），六种格式×策略在 mock 上全部 100%，15 种错误模式映射正确，密钥泄漏扫描 0 命中，数据库副本哈希不变。已知局限：对 429 没有重试退避（免费档高峰时可能把可用性问题读成质量问题，建议错峰跑或重跑比较）、修复重问是单轮、没有真实厂商被调用过。

拿到智谱 key 后（在 Mac 上，用一份数据库副本）：

```bash
PY=/Users/sqin/word-dance/.venv/bin/python
sqlite3 /Users/sqin/word-dance-data/word-dance.db ".backup '/tmp/wd-eval.db'"      # 只读副本，绝不直接用线上文件
export ZHIPU_API_KEY=...                                                           # 只放环境变量
$PY scripts/eval_provider.py --db /tmp/wd-eval.db --format openai --vendor zhipu \
  --base-url https://open.bigmodel.cn/api/paas/v4 --api-key-env ZHIPU_API_KEY --model glm-4.7-flash \
  --strategy json_object --thinking off --kinds probe --out ~/eval/glm-probe        # 先只跑探测
$PY scripts/eval_provider.py --db /tmp/wd-eval.db --format openai --vendor zhipu \
  --base-url https://open.bigmodel.cn/api/paas/v4 --api-key-env ZHIPU_API_KEY --model glm-4.7-flash \
  --strategy json_object --thinking off --paired --kinds content,lookup,consolidate --batch-size 5 \
  --concurrency 1 --out ~/eval/glm                                                  # 约 10 分钟，¥0
# 升级档（百炼，需实名与工作空间 id）：
# --vendor bailian --base-url https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1 \
# --model qwen3.7-flash --strategy json_schema --thinking off
$PY scripts/eval_provider.py --compare ~/eval/glm ~/eval/qwen
jq -c 'select(.paired) | {key, passed, reasons, new: .item.meaning_zh, sonnet: .paired.meaning_zh}' ~/eval/glm/items.jsonl   # 与 48 条 Sonnet 内容并排人工抽查
```

门槛（按任务分别看，`--gates all`）：schema 有效 ≥98%（允许一次修复）、**条目通过 `validate_item` ≥95%**、例句含词头 ≥97%、≥3 条可用例句的条目 ≥95%、中文字段 100% 含中文、p95 延迟 ≤ 0.6 ×（任务超时 × 1.5，例句即 162 秒）、截断 0、修复率 ≤10%、校验任务与内置 40 例的一致率 ≥90% 且 `is_english` 假阴性 ≤2%、整理未知 id 为 0、降级目标 ≤10%；另加 20 条人工抽查（释义与助记自然度、例句正确性，对照配对的 Sonnet 行平均 ≥4/5）。**通过** → 保持默认（切片 2 起 `content` 已在 `WD_AI_FALLBACK_KINDS` 默认值中，批 5 = `WD_AI_FALLBACK_BATCH_SIZE`）。**85–95%** → 从 `WD_AI_FALLBACK_KINDS` 去掉 `content`（`WD_AI_FALLBACK_KINDS=lookup,consolidate`，例句回到 CLI，Claude 暂停期间例句任务等待），校验与整理留给 GLM；「例句生成走升级档」待第二腿落地后再开。**<85% 或延迟/截断不达标** → 同样去掉 `content`；升级档成为第一腿、GLM 只做校验，同样待第二腿落地。两条线：「默认备选」线如上，「仅应急」线（schema ≥95%、条目 ≥85%）允许留在链末而不做首选。

## 6. 实施路线

**实施状态（2026-11-05，MVP 切片 1）**：已实现——`backend/wd/ai/providers/openai_http.py`（OpenAI 格式适配器：方言 zhipu / bailian / deepseek / generic，`json_object` + schema 贴入系统提示或百炼 `json_schema` 严格副本，关思考字段，按原始 schema 的 `jsonschema` 校验 + 一次修复重问，HTTP 错误分类表（含智谱 `sensitive` / `network_error` 完成原因），CNY 价目成本，超时是整次调用——首轮 + 行内重试 + 修复轮——的总预算；原始 schema 与提示词文件不动）；`backend/wd/ai/failover.py`（粘滞状态机：`choose` / `availability` / `record_failure` / `record_success` / `maybe_probe` / `set_manual_pause` / `clear_pauses`，`ai.active_provider` 比较并交换写入，管理员 webhook 通知每类事件每小时一次；任一提供方的任一成功——普通调用或探测、任何模式——即解除该提供方的自动暂停、清掉 `'0'` 可用标记并放行停在该暂停时刻的任务，管理员「恢复」同样放行并删除标记；回切探针固定在已记录的 `claude.flag_tier`，一次尝试，不改写 tier）；配置校验（`WD_AI_FALLBACK_BASE_URL` 须为带主机的 `http://` / `https://` URL，明文 `http://` 到非回环主机只告警；`WD_AI_FALLBACK_PRICE_JSON` 价目键名只许 `input` / `output` / `cache_read`；`WD_AI_FALLBACK_API_KEY_FILE` 启动时须存在且可读；`openai_http` 模式下不在 `WD_AI_FALLBACK_KINDS` 里的任务种类启动时告警「无限期等待」）；`common.claude_call` 的「选提供方 → 按提供方预留 → 调用 → 硬触发或软阈值即在另一提供方立刻重跑同一组」循环与 `handle_failure` 按提供方作用域；迁移 `0010_ai_provider.sql`（`ai_calls.provider`）、账本与预算按提供方（各自的小时上限：Claude 60、备选 40；备选预留为 0，付费价目事后计入 `cost_usd`）、`budget.paused_until` 兼顾全局手工暂停 `ai.paused_until`；配置键 `WD_AI_PROVIDER`、`WD_AI_FALLBACK_*`、`WD_AI_FAILOVER_*`、`WD_AI_CNY_PER_USD`（旧 `WD_AI_FALLBACK_MODEL` 改名为 `WD_AI_CLI_FALLBACK_MODEL`，旧键非空且未配置备选时启动报错提示迁移）；`runner` 正则补丁（托管设置、403 / forbidden、402 / 余额、429 / 502 / 504、网络错误类，`balance:` / `network:` 前缀）；`wd ai-check [--provider claude|fallback]` 与 `POST /api/admin/ai/probe {provider}`；用户侧门控改为「任一提供方可用」；管理页最小字段（当前提供方、备选暂停提示、「探测备用」按钮、账本「来源」列）；测试替身 `backend/tests/fake_openai.py`、单测与集成测试；文档（CLAUDE_INTEGRATION §10、DEPLOY §4 / §9、API.md、`deploy/env.example`）。切片 1 默认只把 `lookup` 与 `consolidate` 交给备选（`WD_AI_FALLBACK_KINDS`）。**切片 2（2026-11-05）**：`content` 默认也走备选（`WD_AI_FALLBACK_KINDS` 默认 `content,lookup,consolidate`——第 5 节评测仍建议做，但不再是默认的前提；`svg` 仍只走 CLI，预热组仍需 `WD_AI_FALLBACK_PREWARM=1`）；备选接手例句组时批大小 5（`WD_AI_FALLBACK_BATCH_SIZE`，实际 `min(WD_AI_BATCH_SIZE, …)`：`failover.claim_limit` 在领取时就按 5 领，已按 10 领取的 CLI 组在备选上重跑前由 `claude_call` 重组为 5 并归还本次领取的尝试次数；混合了预热（优先级 ≥ 90）与普通任务的例句组在备选上运行前先拆分——普通成员立即单独重领、预热成员连同全部可运行的预热积压一起停到 Claude 暂停时刻（回切或管理员「恢复」即放行；CLI 可接手时 +2 分钟；无人可接手如 `openai_http` 模式时 +30 分钟），日志事件 `ai_failover_split`）；备选质量暂停（`invalid_output`——仅由处理器的后验证产生，适配器自己的 schema 不合格是 `error` `schema:`——或 `content_filter:` / `truncated:` / `invalid_json:` / `schema:` 错误，连续 3 次——每次调用都计数、同一组的重试也算——→ 备选暂停 30 分钟并标记 `ai.fallback.pause_reason='quality'`、`ai_fallback_quality` 事件与 webhook（结尾三选一：Claude 暂停中 / Claude 状态未知 / Claude 正常已切回），无效组永不重跑；至少存入一项的组才清零连击——全部异常或全部被拒的备选例句组反而记一次无效——新一次切换也清零；质量暂停只由备选探测成功、成功应用一组或管理员「恢复」解除，普通调用的 HTTP 成功不解除；`truncated:` 的组像 `budget` 一样立即二分、不消耗尝试；备选判非种子词 `valid=false` 不下架词、按后验证失败处理，只有 CLI 可以让词失效；`apply_item` 的 sqlite 错误按「应用失败」处理、不计质量连击）；回切时重排故障期间死掉的例句 / 校验任务（`requeue_dead_jobs(died_after=ai.failover.since, group_size=None)`：复活的任务去掉 `group_size` 标记、按正常批大小领取——夜间与管理员重排仍为 1——上限 200 按真实候选计数、触顶告警，词状态从 `failed` 回到 `queued`——夜间重排同样——已被更新卡片取代的强制重生成跳过 `superseded_regenerate`；`ai_failback` 明细 `requeued_dead`，管理员「恢复」同样；Claude 暂停在未切换的情况下解除时——备选在 `ai.active_provider` 仍为 `claude` 时顶替——也按暂停开始时刻重排；回切与「恢复」一并删除 `ai.failover.{since,reason,trigger_call_id}`，非 `auto` 模式下 worker 启动后的首次 housekeeping 由 `reconcile_mode` 清理残留的粘滞状态，日志事件 `ai_failover_reconciled`；`WD_AI_FALLBACK_KINDS` 为空或仅空白均为默认）；用户侧例句门控在备选服务例句期间报告可用。**尚未实现**：第二腿（`WD_AI_FALLBACK2_*` 有序链、百炼付费档）；管理页「自动 / 仅 Claude / 仅备用」覆盖开关（`ai.provider_override`）；以及第 4.4 节「完整版」的其余条目（每腿信号量、夜间备选探测、`regenerate non-Claude` 筛选、备选下校验 / 整理直写降级为建议、`ON_BUDGET_CAP`、运维手册）。

**今天（0.3 人日，¥0）**：在 open.bigmodel.cn 用大陆手机注册、建标准 API key（不是编码计划的 key）、看控制台的 `glm-4.7-flash` 并发数字、建议顺手实名；用第 5 节命令先跑探测再跑成绩单（智谱的高峰 15:00–23:00 之外跑）；若决定 Z.ai，用同一脚本改 `--base-url https://api.z.ai/api/paas/v4` 先确认该模型在列；在东京服务器上 `curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' -X POST https://open.bigmodel.cn/api/paas/v4/chat/completions` 期望 401（可达）；合并正则补丁；若 Claude 此刻就不可用，按第 3 节装 A0 应急脚本并先在临时数据目录 `wd claude-check`。

**本周起 MVP（7–8 人日，业余 3–4 周）**：第 1–2 天适配器 + 方言 + schema 转换 + 价目 + `fake_openai` + 单测；第 3 天 `failover.py`、`claude_call` 循环、`handle_failure` 作用域、预算/账本、迁移 0010；第 4 天门控、探测与 `ai-check`、配置与改名、管理页字段与 webhook 通知；第 5 天集成测试、最小文档、用假 `claude` 与 `fake_openai` 做 smoke；然后真机测试：L1 `wd ai-check --provider fallback` 精确匹配；L2 评测脚本成绩单；L3 思考开/关对比 token；L4 从东京跑 L1/L2；L5 切换演练——把 `WD_CLAUDE_BIN` 指向一个打印托管设置字符串并退出 1 的假脚本（绝不是真 `claude`），入队 10 个例句任务与 1 个校验，看 `ai_calls.provider`、`kv.ai.active_provider`、横幅，恢复真脚本后点探测；L6 一晚 soak，`WD_AI_PROVIDER=auto` 下 Claude 健康时不应出现备选调用。然后在 VPS 上 `WD_AI_PROVIDER=auto`、`WD_AI_FALLBACK_KIND=openai_http`、`WD_AI_FALLBACK_BASE_URL=https://open.bigmodel.cn/api/paas/v4`、`WD_AI_FALLBACK_MODEL=glm-4.7-flash`，其余默认。

**之后（+4 人日）**：完整版条目（第 4.4 节）；升级档开通时才开百炼账号（90 天免费额度从开户起算，开启「用完即停」）；每半年看一次智谱发布日志里免费模型的换代与隐私政策变化。

## 7. 需要你决定的事

| # | 决策 | 建议默认 |
|---|---|---|
| D1 | 智谱国内站 vs Z.ai | **国内站**（支付宝/微信、大陆延迟；提示词不含个人信息）；想要「不训练」承诺就 Z.ai，但先用一次调用确认免费模型在列 |
| D2 | 升级档 | **百炼 qwen3.7-flash 作第二腿**（新账号 + 实名，严格 schema，≈ ¥15/月，不训练）；不想开第二个账号则同 key 的 GLM-4.7-FlashX；长期留在境外且接受故障史则 DeepSeek-flash |
| D3 | 备选可做的任务 | **校验 + 整理第 1 天开，例句生成评测通过后开，SVG 不开，预生成不开**（2026-11-05 决定：切片 2 起例句默认走备选，评测仍建议补做，不达标则去掉 `content`；SVG 不开、预生成不开不变） |
| D4 | 学习者备注可否发给国内站 | 若不接受：整理任务只给不训练的提供方，或加「不发送备注」开关，并写进给朋友的说明 |
| D5 | 美元上限用尽时切到免费模型 | **否**（上限的含义是停止，不是降级） |
| D6 | Claude 恢复后备选生成的卡片 | **保留**，完整版加管理员「重做非 Claude 卡片」筛选，只重做未学过的词；卡片标注留到按块 AI 标识落地时 |
| D7 | 切回粒度 | 第一次探测成功即切回，固定 30 分钟（6 小时后 60 分钟） |
| D8 | 管理员「暂停 AI」语义 | 暂停全部提供方 |
| D9 | 智谱实名 | **现在就做**（即时完成，消除「目前不强制」的政策风险） |
| D10 | 密钥存放 | **0600 文件** 由适配器读取，不进 `.env`、日志与管理页配置 |

## 8. 风险（前 8 项）

| 风险 | 可能性 / 影响 | 对策 |
|---|---|---|
| GLM-4.7-Flash 的 `json_object` 输出过不了后验证（词头、例句数、中文） | 中 / 备选只能做校验 | 评测门槛分两线；85–95% 时例句走升级档；schema 校验 + 一次修复重问 |
| 智谱免费档限流、1 并发、高峰不可用 | 高 / 切换期间慢 | 信号量 1、批 5、超时 ×1.5、`Retry-After` 与 1308 窗口、第二腿在另一平台 |
| 免费模型被换代或下线（历史上约每年一次） | 中 / 静默换模型 | 探测记录 `model_seen`，变化即事件；半年看一次发布日志 |
| 思考未真正关闭导致输出 token 与延迟暴涨 | 中 / 升级档费用数倍 | 评测断言 `completion_tokens ≈ 可见 JSON`；每方言显式关思考字段 |
| 切换机制自身出错：主模型暂停时用户仍看到 503、重复切换、重启后卡在备选 | 中 / 体验倒退 | 门控统一走 `availability()`、比较并交换写入、重启立即探测、grep 测试禁止直接读旧键、演练 L5 |
| 备选的认证/余额失败被当成主模型故障 | 中 / 全局暂停 | 状态机按提供方作用域；余额类暂停 24 小时并通知 |
| 学习者备注进入会训练的模型 | 低概率 / 隐私承诺 | 决策 D4；整理任务路由或开关 |
| 评测脚本对 429 无重试，把可用性问题读成质量问题 | 中 / 误判 | 错峰运行、看状态直方图、必要时重跑 |

## 9. 成本

| 项目 | 一次性 | 每月 |
|---|---|---|
| GLM-4.7-Flash（第一腿） | ¥0 | ¥0 |
| 百炼 qwen3.7-flash（第二腿，可选） | 首个模型 100 万 tokens 免费 90 天；预生成全库 ≈ ¥3.3 | ≈ ¥15（100 次例句调用/天，思考关闭）；qwen3.8-flash ≈ ¥54 |
| Claude 恢复探测 | — | 失败为 0，成功约 $0.004/次 |
| 你的时间 | MVP 7–8 人日，完整 +4 人日 | 每周看一次管理页的备选占比与无效率 |

## 10. 附录

### 10.1 证据索引

`docs/analysis/2026-11-04-ai-fallback/`：`facts/` 5 个调研切片（`contract`、`zhipu`、`alibaba`、`bytedance-deepseek`、`others-and-cli`），`verify/` 5 份核验报告（每条结论的执行命令或一手来源，含「遗漏/新发现」），`design-D1-cli-gateway.md`、`design-D2-openai-adapter.md`、`design-D3-anthropic-adapter.md` 三套方案，`judge-J1-eng.md`、`judge-J2-owner.md`、`judge-J3-quality-terms.md` 三份评审，`harness-report.md` 与 `harness-verify.md` 评测脚本的实现与独立验证，`INDEX.md` 说明。

### 10.2 核验统计

| 切片 | 核验结论数 | 确认 | 修正 |
|---|---|---|---|
| contract | 9 | 4 | 5 |
| zhipu | 10 | 6 | 4 |
| alibaba | 11 | 6 | 5 |
| bytedance-deepseek | 10 | 6 | 4 |
| others-and-cli | 10 | 8 | 2 |
| 合计 | 50 | 30 | 20 |

没有一条修正推翻切片结论；影响本文的主要修正：pydantic 镜像的宽松转换意味着必须先跑 `jsonschema`；真正的接缝是 `run_claude` 函数而非协议类；暂停键的读者比最初列出的多且已经走辅助函数；DeepSeek 的 Anthropic 端点在非思考模式下支持强制工具但思考开启时 400；智谱的「1 并发」只有第三方来源且 1308 证明存在窗口配额；百炼的 `additionalProperties:false` 只在 Anthropic 路径强制、旧域名已冻结、qwen3.7-flash 默认开思考；ModelScope 单模型上限已降到约 200 次/天；SuperCLUE 数字来自跨版本的第三方汇编，不作决策依据；百度千帆与腾讯 TokenHub 都有 Anthropic 格式端点（付费模型）；硅基流动的 Anthropic 路径是 `/v1/messages`；本机 CLI 为 2.1.292，结构化输出开关可用但 `API_TIMEOUT_MS=0` 不可用。

### 10.3 方案评审

三位评审打分（六项各 0–10，满分 60）：

| 视角 | D1 CLI 网关 | D2 OpenAI 格式适配器 | D3 Anthropic 格式适配器 |
|---|---|---|---|
| 工程正确性 | 36 | 51 | 45 |
| 你的时间与可运维性 | 35 | 46 | 45 |
| 输出质量、条款与成本 | 34 | 47 | 45 |

三位一致以 D2 为底：免费模型唯一有文档的结构化模式是 OpenAI 端点的 `json_object` + 关思考，备选路径完全不依赖 `claude` 二进制，约 7 人日即可自动化；D3 更面向未来（同一适配器以后可接 Anthropic Console key），但先做要 10 人日且把免费模型押在智谱未成文的 Anthropic 路径上；D1 把一串未经验证的 CLI 行为叠在未经验证的网关上，备选仍绑着导致上次故障的那个二进制。从 D3 嫁接：有序提供方链、`record_failure` 唯一写者、余额/配置类 24 小时暂停、1308 窗口硬触发、`jsonschema` 进运行时依赖、条款标志（火山仅大陆、魔搭非商业）、`model_seen`、两条质量线；从 D1 嫁接：A0 包装脚本 + 临时目录探测作为今天的桥梁与诊断、`KINDS` 默认只开校验与整理、密钥放 0600 文件、备选小时上限低于全局、假 `claude` 的托管设置/403/网络/429/中文认证等新模式。

评审指出并已在本文修正的错误：三套方案都把评测脚本当成待建（它已在工作区且已验证）；D2 漏把 `jsonschema` 加进 `requirements.txt`（安装脚本只装该文件）；D1 把「结构化输出开关下工具路径仍在」当成事实（二进制字符串扫描未证实）、工时表合计比标题低约 15%、把「调用不需实名」当成保证；D3 把百炼与 DeepSeek 的错误信封都写成 Anthropic 嵌套格式（实为扁平 403 / 纯文本 401）、探测费用算法有误（失败的探测成本为 0）、`refusal` 停止原因并非各家通用；三套方案对业余开发者的日历都过于乐观（7 人日约 3–4 周，10 人日约 4–5 周）；重做备选卡片的单价按账本是约 $0.006/词而非 $0.005。
