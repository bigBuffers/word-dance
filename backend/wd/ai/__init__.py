"""Claude Code integration (WP5; CLAUDE_INTEGRATION.md).

* :mod:`wd.ai.runner` — the ``claude -p`` spawn (argv tiers, env allow-list, ledger-before-spawn, process-group kill)
* :mod:`wd.ai.budget` — cost model, caps and the atomic reservation (``can_spend`` / ``reserve``)
* :mod:`wd.ai.ledger` — the ``ai_calls`` table
* :mod:`wd.ai.content` / :mod:`wd.ai.lookup` / :mod:`wd.ai.consolidate` / :mod:`wd.ai.svg` / :mod:`wd.ai.prewarm` —
  the five Claude job handlers (imported by ``jobs.registry.HANDLER_MODULES``)
* :mod:`wd.ai.probe` — ``wd claude-check`` / ``POST /api/admin/ai/probe``
* ``prompts/*.txt`` and ``schemas/*.json`` — verbatim from CLAUDE_INTEGRATION §5 and §2/§4
"""
