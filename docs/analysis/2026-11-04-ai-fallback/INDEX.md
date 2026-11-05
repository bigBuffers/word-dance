# Evidence for `docs/AI_FALLBACK_MODEL.md` (collected 2026-11-04/05)

Question answered: if Claude cannot be used, which domestic (China) free model is the best fallback for word-Dance's four AI jobs, and how should the app switch to it automatically when the Claude path fails. Anthropic policy / licensing questions were deferred by the owner; provider terms (free-tier commercial use, data retention, 实名, overseas access) are in scope.

Pipeline: 5 research slices (1 code, 4 web) → one adversarial verifier per slice → 3 independent designs + an implemented eval harness → 3 judges + an independent harness verifier → synthesis in the main document.

## facts/ and verify/

| Slice | Scope | Claims verified → confirmed / corrected |
|---|---|---|
| `contract` | the AI contract (seam, schemas, measured prompt sizes, post-validation, classifier gaps, pause consumers), integration options A/B/C, failover state machine, eval-harness spec | 9 → 4 / 5 |
| `zhipu` | Zhipu GLM free models (GLM-4.7-Flash), limits, Anthropic-format endpoint, terms, stability | 10 → 6 / 4 |
| `alibaba` | 阿里云百炼 (qwen3.7-flash, free quota, workspace Anthropic host) and ModelScope API-Inference | 11 → 6 / 5 |
| `bytedance-deepseek` | Volcengine Ark, DeepSeek, Moonshot Kimi, MiniMax | 10 → 6 / 4 |
| `others-and-cli` | Baidu, iFlytek, Tencent, SiliconFlow, Claude Code gateway mechanics, quality evidence table | 10 → 8 / 2 |

Totals: 50 load-bearing claims — 30 confirmed, 20 corrected (none reversed a slice's conclusion), 0 refuted. An endpoint probe from the owner's mainland network (unauthenticated POSTs) preceded the research; its results are quoted in the main document.

## Designs, judgements, harness

- `design-D1-cli-gateway.md` — fallback through the `claude` CLI pointed at a domestic Anthropic-format endpoint (A0 manual switch + A1 CLI-slot failover).
- `design-D2-openai-adapter.md` — OpenAI chat-completions HTTP adapter behind `runner.run_claude` + sticky provider failover (the synthesis base).
- `design-D3-anthropic-adapter.md` — Anthropic Messages HTTP adapter serving domestic Anthropic-format endpoints and a future Console key.
- `judge-J1-eng.md`, `judge-J2-owner.md`, `judge-J3-quality-terms.md` — scores (D1 36/35/34, D2 51/46/47, D3 45/45/45 out of 60), factual errors (all corrected in the main document), grafts, blind spots.
- `harness-report.md` — implementation report of `scripts/eval_provider.py` + `scripts/mock_provider_server.py` (untracked in the working tree), with the exact runs executed against the mock.
- `harness-verify.md` — independent verification (verdict `pass_with_fixes`; two path-handling fixes applied; safety properties checked).

Scratch artefacts (mock runs, rendered prompts, measurement scripts) stayed under the session scratchpad.
