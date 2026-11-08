#!/usr/bin/env python3
"""Fake ``claude`` CLI for tests and smoke runs (CLAUDE_INTEGRATION.md §8). Stdlib only (runs under ``python -I``).

Same argv contract as the real binary: ``-p <prompt> --output-format json --json-schema <schema> --tools ""
--no-session-persistence --model <m> --max-budget-usd <usd>`` plus the tier-1 flags (``--system-prompt``,
``--restricted``, ``--strict-mcp-config``, ``--disable-slash-commands``). Unknown flags are ignored (the
``WD_AI_EXTRA_ARGS`` escape hatch).

The kind is inferred from the schema: ``items[].examples`` → content, ``items[].is_english`` → lookup,
``confusable_groups`` → consolidate, ``svg`` → svg, ``echo`` → probe (answers exactly
``{"ok":true,"echo":"word-dance","level":2,"mode":"b","tags":["probe"]}``). Words/strings/items come from the
``<items>`` block of the prompt. One envelope is printed::

    {"type":"result","subtype":"success","is_error":false,"structured_output":{…},"total_cost_usd":0.004×n,
     "duration_ms":1200,"usage":{"input_tokens":2,"output_tokens":330×n,"cache_read_input_tokens":0,
     "cache_creation_input_tokens":1691},"modelUsage":{"claude-sonnet-fake":{}},"session_id":"fake","num_turns":2}

``FAKE_CLAUDE_MODE``: ok (default) · invalid_json · schema_mismatch · partial · invalid_word · budget · timeout ·
auth · managed_settings · forbidden · balance · network · rate429 · overloaded · usage_error · stdin_hang. Contract assertions (exit 3): ``--tools ""``,
``--no-session-persistence``, ``--output-format json``, ``--json-schema`` and ``-p`` must be present and
``CLAUDECODE`` must be absent from the environment (the runner's env allow-list, §1.3).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

PROBE_ANSWER = {"ok": True, "echo": "word-dance", "level": 2, "mode": "b", "tags": ["probe"]}
TIER1_FLAGS = ("--system-prompt", "--restricted", "--strict-mcp-config", "--disable-slash-commands")
VALUE_FLAGS = {
    "-p",
    "--output-format",
    "--json-schema",
    "--model",
    "--max-budget-usd",
    "--tools",
    "--system-prompt",
    "--append-system-prompt",
    "--fallback-model",
    "--effort",
    "--permission-mode",
    "--setting-sources",
    "--mcp-config",
}
BOOL_FLAGS = {"--no-session-persistence", "--restricted", "--strict-mcp-config", "--disable-slash-commands", "--bare", "--verbose"}
COST_PER_ITEM = 0.004
CJK_NOTE = "（测试释义）"


def parse_argv(argv: list[str]) -> dict:
    """Minimal, order-independent argv parser: known value flags consume the next argument."""
    opts: dict = {"flags": set(), "unknown": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in VALUE_FLAGS:
            if i + 1 >= len(argv):
                opts["unknown"].append(a)
                break
            opts[a] = argv[i + 1]
            opts["flags"].add(a)
            i += 2
            continue
        if "=" in a and a.split("=", 1)[0] in VALUE_FLAGS:
            k, v = a.split("=", 1)
            opts[k] = v
            opts["flags"].add(k)
            i += 1
            continue
        if a in BOOL_FLAGS:
            opts["flags"].add(a)
            i += 1
            continue
        opts["unknown"].append(a)
        i += 1
    return opts


def contract_violation(opts: dict) -> str | None:
    if "CLAUDECODE" in os.environ:
        return "CLAUDECODE is set in the environment (the runner must build the child env from an allow-list)"
    if "-p" not in opts:
        return "missing -p <prompt>"
    if opts.get("--output-format") != "json":
        return "missing --output-format json"
    if "--json-schema" not in opts:
        return "missing --json-schema"
    if "--tools" not in opts or opts.get("--tools") != "":
        return 'missing --tools ""'
    if "--no-session-persistence" not in opts["flags"]:
        return "missing --no-session-persistence"
    return None


def infer_kind(schema: dict) -> str:
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if "echo" in props:
        return "probe"
    if "svg" in props:
        return "svg"
    if "confusable_groups" in props:
        return "consolidate"
    items = props.get("items", {})
    item_props = items.get("items", {}).get("properties", {}) if isinstance(items, dict) else {}
    if "examples" in item_props:
        return "content"
    if "is_english" in item_props:
        return "lookup"
    if "letters" in item_props:
        return "dance"
    return "content"


def items_block(prompt: str):
    m = re.search(r"<items>\s*(.*?)\s*</items>", prompt, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def content_words(prompt: str) -> list[str]:
    data = items_block(prompt)
    words: list[str] = []
    if isinstance(data, dict):
        for w in data.get("words", []):
            if isinstance(w, dict) and isinstance(w.get("word"), str):
                words.append(w["word"])
            elif isinstance(w, str):
                words.append(w)
    return words or ["unknown"]


def lookup_strings(prompt: str) -> list[str]:
    data = items_block(prompt)
    out: list[str] = []
    if isinstance(data, dict):
        for s in data.get("items", []):
            if isinstance(s, str):
                out.append(s)
            elif isinstance(s, dict) and isinstance(s.get("input"), str):
                out.append(s["input"])
    return out or ["unknown"]


def consolidate_items(prompt: str) -> list[dict]:
    data = items_block(prompt)
    out: list[dict] = []
    if isinstance(data, dict):
        for it in data.get("items", []):
            if isinstance(it, dict) and "id" in it:
                out.append(it)
    return out or [{"id": 0, "input": "unknown", "headword": "unknown"}]


def svg_word(prompt: str) -> str:
    m = re.search(r'for the word "([^"]+)"', prompt)
    return m.group(1) if m else "word"


def ascii_keyword(word: str) -> str:
    kw = re.sub(r"[^A-Za-z ]", "", word).strip().lower() or "word"
    return f"{kw} photo"


def content_item(word: str, mode: str) -> dict:
    invalid = mode == "invalid_word" and "zzz" in word.lower()
    if invalid:
        return {
            "word": word,
            "valid": False,
            "meaning_zh": "这不是一个英文单词",
            "meaning_en": "",
            "examples": [],
            "collocations": [],
            "mnemonic_zh": "",
            "image_keywords": ["question mark"],
            "image_alt_zh": "一个问号",
            "difficulty": 1,
        }
    return {
        "word": word,
        "valid": True,
        "meaning_zh": f"n./v. {word} 的释义{CJK_NOTE}",
        "meaning_en": f"a test definition of {word} used by the fake claude",
        "examples": [
            {"en": f"I saw the word {word} in a report at work this morning.", "zh": "今天早上我在工作报告里看到了这个词。"},
            {"en": f"Our teacher asked us to use {word} in a sentence today.", "zh": "老师今天让我们用这个词造句。"},
            {"en": f"The article explains what {word} means with a clear example.", "zh": "这篇文章用一个清晰的例子解释了这个词的意思。"},
            {"en": f"She wrote {word} on the board and underlined it twice.", "zh": "她把这个词写在黑板上，还画了两条下划线。"},
        ],
        "collocations": [f"{word} example", f"use {word}"],
        "mnemonic_zh": f"联想：{word}（测试助记）",
        "image_keywords": [ascii_keyword(word)],
        "image_alt_zh": f"与 {word} 相关的画面",
        "difficulty": 3,
    }


def lookup_item(text: str, mode: str) -> dict:
    invalid = mode == "invalid_word" and "zzz" in text.lower()
    is_abbr = bool(re.fullmatch(r"[A-Z]{2,6}", text.strip()))
    headword = text.strip() if is_abbr else text.strip().lower()
    if invalid:
        return {
            "input": text,
            "is_english": False,
            "kind": "invalid",
            "headword": text.strip().lower(),
            "form_note_zh": "",
            "phonetic": "",
            "pos": "",
            "meaning_zh": "",
            "definition_en": "",
            "difficulty": 1,
            "suggested_correction": "",
            "safe_for_sharing": True,
            "note_zh": "这不是一个英文单词",
        }
    kind = "abbreviation" if is_abbr else ("phrase" if " " in headword else "word")
    return {
        "input": text,
        "is_english": True,
        "kind": kind,
        "headword": headword,
        "form_note_zh": "",
        "phonetic": "",
        "pos": "n.",
        "meaning_zh": f"{headword} 的中文释义{CJK_NOTE}",
        "definition_en": f"a test definition of {headword}",
        "difficulty": 3,
        "suggested_correction": "",
        "safe_for_sharing": True,
        "note_zh": "",
    }


def consolidate_item(it: dict, mode: str) -> dict:
    text = str(it.get("input") or it.get("headword") or "")
    invalid = mode == "invalid_word" and "zzz" in text.lower()
    return {
        "id": it.get("id", 0),
        "verdict": "invalid_word" if invalid else "ok",
        "target": "",
        "confidence": 0.9 if invalid else 1.0,
        "note_zh": "这似乎不是英文单词" if invalid else "",
        "fill": {"phonetic": "", "pos": "", "meaning_zh": "", "definition_en": "", "difficulty": 3},
    }


def svg_output(word: str) -> dict:
    safe = word.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">'
        '<rect width="800" height="500" fill="#e0f2fe"/><circle cx="400" cy="220" r="120" fill="#38bdf8"/>'
        f'<text x="400" y="440" font-size="40" text-anchor="middle" font-family="Inter, system-ui, sans-serif">{safe}</text></svg>'
    )
    return {"svg": svg, "alt_zh": f"一幅表示 {word} 的简单示意图"}


REQUIRED_DROP = {"content": "meaning_zh", "lookup": "headword", "consolidate": "verdict", "svg": "alt_zh", "probe": "echo", "dance": "letters"}

DANCE_PRIMITIVES = {"up": ("rise", 0, ""), "down": ("fall", 0, ""), "in": ("enter", 0, ""), "out": ("exit", 0, ""), "big": ("grow", 0, ""), "small": ("shrink", 0, ""),
                    "cold": ("shiver", 0, ""), "hot": ("shimmer", 0, ""), "happy": ("wave", 0, ""), "sad": ("droop", 0, ""), "two": ("multiply", 2, ""), "three": ("multiply", 3, ""),
                    "red": ("color", 0, "red"), "yellow": ("color", 0, "yellow"), "jump": ("hop", 0, ""), "on": ("onto", 0, ""), "turn": ("spin", 0, ""), "again": ("repeat", 0, "")}


def dance_words(prompt: str) -> list[dict]:
    data = items_block(prompt)
    out: list[dict] = []
    if isinstance(data, dict):
        for w in data.get("words", []):
            if isinstance(w, dict) and isinstance(w.get("word"), str):
                out.append(w)
    return out or [{"word": "unknown"}]


def dance_item(entry: dict, mode: str) -> dict:
    """Echo the rule chunks (or a corrected split for `abandon`) and pick a primitive from a tiny table; 'none' otherwise."""
    word = str(entry["word"])
    letters = list(entry.get("rule_letters") or [word])
    stress = int(entry.get("rule_stress") or 0)
    if word.lower() == "abandon":
        letters, stress = ["a", "ban", "don"], 1  # the rule split; a corrected one would differ
    primitive, n, color = DANCE_PRIMITIVES.get(word.lower(), ("none", 0, ""))
    return {"word": word, "letters": letters, "stress": stress, "primitive": primitive, "n": n, "color": color, "reason": "测试" if primitive == "none" else "动作即词义"}


def structured_output(kind: str, prompt: str, mode: str) -> tuple[dict, int]:
    if kind == "probe":
        out, n = dict(PROBE_ANSWER), 1
    elif kind == "svg":
        out, n = svg_output(svg_word(prompt)), 1
    elif kind == "lookup":
        strings = lookup_strings(prompt)
        out, n = {"items": [lookup_item(s, mode) for s in strings]}, len(strings)
    elif kind == "consolidate":
        items = consolidate_items(prompt)
        out, n = {"items": [consolidate_item(it, mode) for it in items], "confusable_groups": [], "difficulty_tags": []}, len(items)
    elif kind == "dance":
        entries = dance_words(prompt)
        out, n = {"items": [dance_item(e, mode) for e in entries]}, len(entries)
    else:
        words = content_words(prompt)
        out, n = {"items": [content_item(w, mode) for w in words]}, len(words)

    if mode == "partial" and isinstance(out.get("items"), list) and len(out["items"]) > 1:
        out["items"] = out["items"][:-1]
    if mode == "schema_mismatch":
        key = REQUIRED_DROP[kind]
        if isinstance(out.get("items"), list):
            for it in out["items"]:
                it.pop(key, None)
        else:
            out.pop(key, None)
    return out, n


def envelope(output: dict, n: int) -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "structured_output": output,
        "total_cost_usd": round(COST_PER_ITEM * n, 6),
        "duration_ms": 1200,
        "usage": {"input_tokens": 2, "output_tokens": 330 * n, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1691},
        "modelUsage": {"claude-sonnet-fake": {}},
        "session_id": "fake",
        "num_turns": 2,
    }


def main(argv: list[str]) -> int:
    opts = parse_argv(argv)
    violation = contract_violation(opts)
    if violation:
        print(f"fake_claude: contract violation: {violation}", file=sys.stderr)
        return 3
    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok").strip() or "ok"
    try:
        schema = json.loads(opts["--json-schema"])
    except ValueError:
        print("fake_claude: --json-schema is not valid JSON", file=sys.stderr)
        return 3
    prompt = opts["-p"]
    try:
        budget = float(opts.get("--max-budget-usd", "0.25"))
    except ValueError:
        budget = 0.25

    if mode == "usage_error":
        for flag in TIER1_FLAGS:
            if flag in opts["flags"]:
                print(f"error: unknown option '{flag}'", file=sys.stderr)
                return 1
        mode = "ok"
    if mode == "timeout":
        time.sleep(600)
        return 0
    if mode == "auth":
        print("Not logged in. Please run claude login", file=sys.stderr)
        return 1
    if mode == "managed_settings":  # the 2026-11 enterprise outage string (AI_FALLBACK_MODEL §1) → `auth`
        print("Your organization requires remote managed settings to load, but they could not be fetched", file=sys.stderr)
        return 1
    if mode == "forbidden":  # region block → `auth`
        print("API Error: 403 Request not allowed", file=sys.stderr)
        return 1
    if mode == "balance":  # → `auth` with the `balance:` prefix (failover pauses 24 h)
        print("API Error: 402 insufficient balance", file=sys.stderr)
        return 1
    if mode == "network":  # → `overloaded` with the `network:` prefix
        print("TypeError: fetch failed: connect ECONNREFUSED 127.0.0.1:8118", file=sys.stderr)
        return 1
    if mode == "rate429":  # → `overloaded`
        print("API Error: 429 Too Many Requests", file=sys.stderr)
        return 1
    if mode == "overloaded":
        print("API overloaded (529)", file=sys.stderr)
        return 1
    if mode == "budget":
        body = {
            "type": "result",
            "subtype": "error_max_budget_usd",
            "is_error": True,
            "total_cost_usd": budget,
            "duration_ms": 1200,
            "result": f"Max budget of ${budget:.2f} exceeded",
            "usage": {"input_tokens": 2, "output_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1691},
            "modelUsage": {"claude-sonnet-fake": {}},
            "session_id": "fake",
            "num_turns": 1,
        }
        print(json.dumps(body, ensure_ascii=False))
        return 1
    if mode == "stdin_hang":
        sys.stdin.read()  # returns at once under stdin=DEVNULL; blocks forever on an open pipe
    if mode == "invalid_json":
        print("this is not json {{{ garbage")
        return 0

    kind = infer_kind(schema)
    output, n = structured_output(kind, prompt, mode)
    print(json.dumps(envelope(output, n), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
