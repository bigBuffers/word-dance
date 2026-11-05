"""Model providers behind the ``run_claude`` seam (AI_FALLBACK_MODEL §4, CLAUDE_INTEGRATION §10).

* ``claude`` — today's ``claude -p`` CLI path, :func:`wd.ai.runner.run_claude`;
* ``fallback`` — the OpenAI-format HTTP adapter, :func:`wd.ai.providers.openai_http.run_openai`.

The names are the values of ``ai_calls.provider`` (migration 0010) and of ``kv.ai.active_provider``; ``ai/failover.py``
and the adapters import them from here, so none of them depends on another at import time.
"""

from __future__ import annotations

CLAUDE = "claude"
FALLBACK = "fallback"
PROVIDERS: tuple[str, ...] = (CLAUDE, FALLBACK)

__all__ = ["CLAUDE", "FALLBACK", "PROVIDERS"]
