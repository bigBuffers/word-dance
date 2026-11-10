# 2026-11：AI 分流模式 `WD_AI_PROVIDER=split`——学习者触发的生成走国产模型

## 1 起因

- 面向大陆学习者，Anthropic 2026-11-12 起的政策按使用者所在地判定支持地区；学习者实时触发的生成（自添词校验、按需例句、夜间整理）把他们的输入送到 Claude，处在条文边缘（`docs/PUBLIC_LAUNCH_AND_IOS.md` §2.3）；运营者在支持地区预生成、学习者只读是站得住的。
- 仓库里已经有备选链路（`docs/AI_FALLBACK_MODEL.md`：OpenAI 格式适配器 + 自动切换状态机，默认目标智谱 GLM-4.7-Flash 免费档），但只有「Claude 挂了才用」（`auto`）和「只用备选」（`openai_http`）两种用法；业主要求把实时生成切过去，同时让预热等运营工作留在 Claude。

## 2 变更

- 新模式 `WD_AI_PROVIDER="split"`（`backend/wd/config.py`、`backend/wd/ai/failover.py`）：`failover.realtime(kind, priority)` 判定「学习者的任务」= `WD_AI_FALLBACK_KINDS` 里的 kind（默认 content / lookup / consolidate）且不是预热组（优先级 ≥ 90；`WD_AI_FALLBACK_PREWARM=1` 时预热组也算）。`choose`：学习者的任务只走备选，备选暂停或被标为不可用时原地等待它恢复，绝不改走 Claude；其余任务（预热内容、SVG、舞步标注、从名单里去掉的 kind）只走 Claude，Claude 暂停只拖住它们。`availability`：学习者任务的原因是 `fallback_paused` / `fallback_unavailable`，运营任务是 `claude_paused`。`record_failure`：两边都不切换、不互相重跑（`retry_provider` 恒为空）；备选一暂停就发 `fallback_paused` 通知（它是学习者唯一的提供方，Claude 正常与否都要告警），质量暂停的通知文案也改为分流版；`maybe_probe` 不工作、`reconcile_mode` 像其他非 `auto` 模式一样清掉残留的粘滞状态。
- **堵住评审发现的泄漏**：学习者添加词时原本会自动排队「舞步标注」（词 + 音标 + 释义送 Claude）和没有照片时的「SVG 配图」（词 + 释义 + 例句送 Claude）。分流模式下 `dance.enqueue_if_needed` 不再为学习者的动作排队（`wd dance-annotate` 以 `operator=True` 照常），`images.handler._svg_allowed` 为假（管理员点名的 `claude_svg` 请求不受影响），切换前已排队的任务由处理器以 `{"skipped": "split_mode"}` 结束——模板卡与规则舞步顶上。备选暂停时，混在学习者批里的预热任务不再陪等：`claude_call` 把它们放回队列单独由 Claude 领取。备选对学习者自添词的 `valid=false` 在此模式下是最终裁决（直接判无效，不再等永远不会来的 Claude 复核）。从 `WD_AI_FALLBACK_KINDS` 去掉学习者任务会在启动时告警（它们会改走 Claude）。`handle_failure` 只在 `auto` 模式才按「另一方更早的暂停」顺延。
- 启动日志事件 `ai_provider_mode`（模式与备选配置）；`wd check` 本就打印 `provider mode`。
- 适配器（`backend/wd/ai/providers/openai_http.py`）：不带 `Retry-After` 的普通 429（智谱 1302 / 1305「访问量过大」）在调用预算内按 2 / 4 / 8 秒退避最多再试三次；带 `Retry-After` ≤ 10 秒的照旧只重试一次，> 10 秒的照旧不重试（重试途中收到长 `Retry-After` 也停止），任务按过载阶梯（2 分钟 × 次数）顺延。起因见 §4 的实测：高峰时段免费档约 70% 的调用先被 1305 拒绝，而成功与拒绝交替出现、间隔只有几秒。
- 没有数据库变更、没有 API 变更（管理页仍显示 `active_provider`、备选配置与暂停）。
- 文档：`docs/AI_FALLBACK_MODEL.md` §4.3 / §6、`docs/CLAUDE_INTEGRATION.md` §10.5 / §10.6、`docs/DEPLOY.md` §4、`deploy/env.example`、`docs/ops.md` §5。

## 3 启用步骤（需要一把智谱 API key——仓库里从未有过真实 key）

1. 在 open.bigmodel.cn 用大陆手机注册、实名，建一把**标准** API key（不是编码计划的 key），看控制台里 `glm-4.7-flash` 的并发数。
2. Mac 上 `install -m 600 /dev/null /Users/sqin/word-dance-data/zhipu.key`，把 key 写进去（只此一处，不进 `.env`、日志与管理页）。
3. `.env` 加：`WD_AI_FALLBACK_KIND="openai_http"`、`WD_AI_FALLBACK_BASE_URL="https://open.bigmodel.cn/api/paas/v4"`、`WD_AI_FALLBACK_MODEL="glm-4.7-flash"`、`WD_AI_FALLBACK_DIALECT="zhipu"`、`WD_AI_FALLBACK_API_KEY_FILE="/Users/sqin/word-dance-data/zhipu.key"`；`WD_AI_PROVIDER` 先不动。
4. `WD_DATA_DIR=/Users/sqin/word-dance-data .venv/bin/wd ai-check --provider fallback`（一次精确匹配探测，成功即 `ai.fallback.available=1`）；可选：按 `docs/AI_FALLBACK_MODEL.md` §5 跑评测成绩单（避开智谱高峰 15:00–23:00）。
5. `WD_AI_PROVIDER="split"`，`launchctl kickstart -k gui/$(id -u)/com.word-dance.server`；启动日志 `ai_provider_mode` 应写 `split`；加一个自添词后看 `ai_calls`：该词引出的全部调用（lookup、content）`provider` 都是 `fallback`，且没有它的 `dance` / `svg` 行；`wd dance-annotate` / 预热仍记 `claude`。
6. 回退：`WD_AI_PROVIDER="claude_cli"`（或 `auto`）+ 重启，无需其他动作。

## 4 验收

- **2026-11-10 16:45 实测（智谱免费档，高峰时段，评测脚本对数据库只读副本）**：`wd ai-check --provider fallback` 精确匹配探测成功（¥0）；评测脚本探测 100%、1.3 秒。配对评测（例句 / 校验 / 整理，批 5，并发 1）被 1305 过载大面积拒绝：例句 165 次调用里 118 次 429-1305、26 次成功，返回的 47 个 200 应答里 14 个不合 schema、7 个不是合法 JSON，16 次修复重问全部又撞上 1305；校验与整理的全部调用被拒，无法评分。能评的部分：条目后验证通过率 95.4%（124/130）、例句含词头 95.7%、≥3 条可用例句 95.4%、延迟 p50 241 毫秒 / p95 18.6 秒。结论：免费档在高峰时段的可用性是切换的主要风险，JSON 稳定性是第二风险；评测脚本本身对 429 不退避，须错峰（23:00 后或上午）重跑才能评质量；适配器已加退避（§2），服务侧实际体验会好于脚本数据。

- 单测：`tests/unit/test_failover.py`（split 的 `choose` / `availability` / `record_failure` 含 `fallback_paused` 通知 / `reconcile_mode`）、`tests/unit/test_config.py`（`split` 接受且要求备选配置完整；去掉学习者任务时告警）、`tests/unit/test_openai_http.py`（1305 退避）；端到端 `tests/integration/test_failover_flow.py`：split 模式下自添词的校验与按需例句在备选上完成、优先级 90 的预热组由假 CLI 完成，备选 401 时只暂停备选、任务顺延到暂停结束而不在 CLI 上重跑，CLI 失败不切换，学习者动作不排舞步 / SVG 任务（切换前排的被跳过、`wd dance-annotate` 照常走 Claude），备选暂停时混合批的预热成员单独由 CLI 完成，备选的 `valid=false` 直接判无效，整理在备选上完成。
- 评审：`review-word-dance-ai-split`（4 个视角、42 条发现、每条 3 人复核：36 条确认、6 条驳回）——最重的是上述舞步 / SVG 泄漏与混合批陪等，其余为通知、文案与文档；全部修正。随后的复核（4 位）又指出 26 处（2 条中等：备选被标为不可用时告警不该说「暂停至」、文档仍按三种模式描述；其余为低：混合批重排的触发条件与时点、`wd dance-annotate` 遇到学习者已排队的任务时 `operator` 标记丢失、备选 `valid=false` 在 `openai_http` 模式同样应为最终裁决、重试途中的长 `Retry-After`、若干文档与测试表述），同样全部修正。
- 门禁与上线记录见 §5。

## 5 上线记录

- 门禁（提交前）：pytest 2298 通过 / 3 跳过（Mac 专属的 `test_defaults_without_environment` 与 Linux 专属的 `test_deploy_files` 除外），`make smoke` 29 步；前端无改动。
- 2026-11-10 17:53（Mac，`8329511`）：`.env` 先备份为 `.env.bak-20261110-175257`（0600），写入 `WD_AI_PROVIDER="split"`、`WD_AI_FALLBACK_KIND="openai_http"`、`WD_AI_FALLBACK_BASE_URL="https://open.bigmodel.cn/api/paas/v4"`、`WD_AI_FALLBACK_MODEL="glm-4.7-flash"`、`WD_AI_FALLBACK_DIALECT="zhipu"`、`WD_AI_FALLBACK_API_KEY_FILE="/Users/sqin/word-dance-data/zhipu.key"`（业主放置的 0600 文件，49 字符）；`launchctl kickstart -k` 重启，4 秒后健康；启动日志 `AI provider mode split (fallback: openai_http glm-4.7-flash for content,lookup,consolidate)`（事件 `ai_provider_mode`）；`wd check`：`provider mode: split; active: claude`，`fallback … available=1`；`wd ai-check --provider fallback` 成功（高峰时段 43 秒：1305 退避重试后成功）。无迁移；回滚 = `.env` 改回 `WD_AI_PROVIDER="claude_cli"` + 重启（备选配置可留着）。
- 待办：错峰（23:00 后或上午）重跑 `docs/AI_FALLBACK_MODEL.md` §5 的配对评测，决定 `content` 是否留在 `WD_AI_FALLBACK_KINDS`；若高峰可用性仍不够，同一把 key 可换 `glm-4.7-flashx`（付费、限流更宽）；观察第一周 `ai_calls.provider` 分布与 `fallback_paused` 通知。
