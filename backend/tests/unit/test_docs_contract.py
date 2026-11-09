"""docs/** ↔ code (integration review, fix/docs). The frozen contracts promise that API.md §1.1, DEPLOY §3/§4, TASKS P0/§I,
DESIGN §7.1 and the runbooks describe what the code does; each test here pins one confirmed finding:

* API.md §1.1 lists exactly the codes of ``errors.CATALOGUE`` with their statuses (405 ``method_not_allowed`` and
  413 ``payload_too_large`` were missing);
* DEPLOY §4 names every ``Settings`` variable (``WD_FRONTEND_DIST`` was missing) and §3 every keyword ``wd serve``
  passes to ``uvicorn.run`` (``access_log=False`` was missing);
* TASKS P0 step 4 / §I and DESIGN §7.1 carry the real ``run_migrations`` / ``on_action`` signatures;
* ops.md §1 and DEPLOY §6 describe ``wd logs`` truthfully (its ring buffer lives inside ``wd serve``; the daily check is
  ``journalctl``); ops.md §5 and DEPLOY §10–§11 move the data directory by passing ``WD_DATA_DIR`` to install.sh instead
  of hand-editing the unit; DEPLOY §8, ops.md §8 and qa-study.md say that Vite binds ``localhost`` only;
* the learning-order release (docs/analysis/2026-11-06-learn-order/DESIGN.md §4.1 item 23): API.md 20 / 22 / 31, DESIGN §3.2 /
  §6.2 / §6.3 step 4, WORD_LIBRARY_CURATION §1.6 and CLAUDE_INTEGRATION's prewarm paragraph quote ``learn_order.ORDER_SQL`` (the
  ``w.`` alias stripped) and the NULL stage distance instead of the pre-0014 frequency order; ops.md §1 and TASKS.md list the
  eight ``wd check db`` invariant names in ``diag`` order; DEPLOY §9 lists ``learn-order`` with the options the parser registers;
  FRONTEND §5.5 / §8 and zh.ts carry the 学习顺序 label while the wire value stays ``freq``;
* API.md §9's ``ts`` block is ``frontend/src/api/types.ts`` verbatim (header comment excluded) — the frozen DTO contract, which
  ``scripts/check_contract.py`` only compares with ``schemas.py`` (单词之舞 P3 review).
"""

from __future__ import annotations

import ast
import inspect
import re
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "docs"


def doc(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """Body of the markdown section whose heading line starts with ``heading``, up to the next heading of the same or a
    higher level."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    body: list[str] = []
    fenced = False  # `# comment` lines inside ``` blocks are not headings
    for line in lines[start + 1 :]:
        if line.startswith("```"):
            fenced = not fenced
        m = re.match(r"^(#{1,6}) ", line)
        if m and len(m.group(1)) <= level and not fenced:
            break
        body.append(line)
    return "\n".join(body)


def table_rows(text: str) -> list[list[str]]:
    """Cells of every ``| `code` | … |`` table row (header and separator rows excluded)."""
    return [[c.strip() for c in line.strip().strip("|").split("|")] for line in text.splitlines() if line.startswith("| `")]


def param_names(fn) -> list[str]:
    """Parameter names of ``fn`` with the keyword-only marker, e.g. ``['conn', '*', 'pre_hook']``."""
    out: list[str] = []
    for p in inspect.signature(fn).parameters.values():
        if p.kind is inspect.Parameter.KEYWORD_ONLY and "*" not in out:
            out.append("*")
        out.append(p.name)
    return out


def plain_signature(fn) -> str:
    """``name(a, *, b=None)`` — names, the keyword-only marker and defaults, no annotations (how the docs quote calls)."""
    parts: list[str] = []
    for p in inspect.signature(fn).parameters.values():
        if p.kind is inspect.Parameter.KEYWORD_ONLY and "*" not in parts:
            parts.append("*")
        parts.append(p.name if p.default is inspect.Parameter.empty else f"{p.name}={p.default!r}")
    return f"{fn.__name__}({', '.join(parts)})"


def doc_signature(text: str, name: str) -> tuple[list[str], str | None]:
    """Parameter names (with the ``*`` marker) and the whitespace-free return annotation of ``def name(...)`` quoted in a
    doc code block."""
    start = text.index(f"def {name}(") + len(f"def {name}")
    depth, i = 0, start
    while True:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    params: list[str] = []
    for raw in re.split(r",(?![^\[\]()]*[\]\)])", text[start + 1 : i]):  # commas outside [] and ()
        raw = raw.strip()
        if raw:
            params.append("*" if raw == "*" else re.split(r"[:=]", raw, maxsplit=1)[0].strip())
    ret = re.match(r"\s*->\s*([^#\n]+)", text[i + 1 :])
    return params, (re.sub(r"\s", "", ret.group(1)) if ret else None)


# ------------------------------------------------------------------------------------------ API.md §1.1
def test_api_error_table_matches_the_catalogue():
    from wd.errors import CATALOGUE

    documented: dict[str, int] = {}
    for cells in table_rows(section(doc("API.md"), "### 1.1 Error codes")):
        for code in re.findall(r"`([a-z_]+)`", cells[0]):
            documented[code] = int(cells[1])
    expected = {code: status for code, (status, _msg) in CATALOGUE.items()}
    assert documented == expected, {
        "undocumented": sorted(set(expected) - set(documented)),
        "unknown_to_code": sorted(set(documented) - set(expected)),
        "status_mismatch": sorted(c for c in set(documented) & set(expected) if documented[c] != expected[c]),
    }
    # the two transport-level codes are real behaviour (main.py body limit, Starlette 405 → errors._STATUS_TO_CODE)
    assert documented["method_not_allowed"] == 405 and documented["payload_too_large"] == 413


# -------------------------------------------------------------------------------------------- DEPLOY §3/§4
def test_deploy_config_table_names_every_setting():
    from dataclasses import fields

    from wd.config import Settings

    known = {"WD_" + f.name.upper() for f in fields(Settings) if f.name != "env_sources"}
    named: set[str] = set()
    for cells in table_rows(section(doc("DEPLOY.md"), "## 4. Configuration")):
        last = None
        for token in re.findall(r"`([A-Z0-9_]+)`", cells[0]):
            if token.startswith("WD_"):
                named.add(token)
                last = token
            elif token.startswith("_") and last:  # `WD_AI_BUDGET_CONTENT` / `_LOOKUP` abbreviates WD_AI_BUDGET_LOOKUP
                parts = last.split("_")
                full = next(("_".join(parts[:i]) + token for i in range(len(parts), 0, -1) if "_".join(parts[:i]) + token in known), None)
                assert full, f"cannot expand {token!r} after {last!r}"
                named.add(full)
    assert known - named == set(), f"Settings variables missing from DEPLOY §4: {sorted(known - named)}"
    assert named - known == set(), f"DEPLOY §4 rows for unknown variables: {sorted(named - known)}"


def uvicorn_run_keywords() -> list[str]:
    tree = ast.parse((REPO / "backend" / "wd" / "cli.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "uvicorn"
        ):
            return [k.arg for k in node.keywords if k.arg]
    raise AssertionError("uvicorn.run(...) not found in cli.py")


def test_deploy_serve_line_lists_every_uvicorn_keyword():
    keywords = uvicorn_run_keywords()
    assert "access_log" in keywords  # the P0 addition the sentence used to omit (P0_STATUS §3 item 9)
    bullet = next(l for l in section(doc("DEPLOY.md"), "## 3. systemd units").splitlines() if l.startswith("* `wd serve` = `uvicorn.run("))
    call = bullet.split("`")[3]  # the `uvicorn.run(...)` code span
    assert sorted(re.findall(r"(\w+)=", call)) == sorted(keywords), (call, keywords)
    assert "access_log=False" in call and "os.umask(0o077)" in bullet


# -------------------------------------------------------------------------------------- TASKS §I / DESIGN §7.1
def test_tasks_and_design_carry_the_real_signatures():
    from wd import db
    from wd.services import stats_core

    tasks = doc("TASKS.md")
    # P0 step 4: the connection is the first positional argument (P0_STATUS §3 item 1)
    assert plain_signature(db.run_migrations) == "run_migrations(conn, *, pre_hook=None, migrations_dir=None, dry_run=False)"
    assert plain_signature(db.run_migrations) in tasks
    assert "run_migrations(pre_hook=None)" not in tasks
    # §I: the prev_state keyword and the returned delta dict (P0_STATUS §3 item 4)
    params, ret = doc_signature(tasks, "on_action")
    assert params == param_names(stats_core.on_action)
    assert ret == re.sub(r"\s", "", str(inspect.signature(stats_core.on_action).return_annotation))
    block = tasks[tasks.index("def on_action(") :]
    block = block[: block.index("\n\n")]
    assert "push_items" in block and "item_kind" in block  # how `undone` must be built for the restore reversals
    # DESIGN §7.1 quotes the same call
    assert plain_signature(stats_core.on_action) in doc("DESIGN.md")


# ------------------------------------------------------------------------------------- ops.md §1 / DEPLOY §6
def test_wd_logs_reads_only_a_configured_log_file_outside_the_server(tmp_path, monkeypatch):
    """The premise of the docs wording: a CLI process has an empty ring buffer, and only WD_LOG_FILE can feed `wd logs`."""
    from wd import diag
    from wd.config import Settings

    monkeypatch.setattr(diag, "RING", deque())  # a fresh `wd logs` process: nothing was logged through the ring handler
    cfg = Settings.from_env({"WD_DATA_DIR": str(tmp_path)})
    assert cfg.log_file == ""  # env.example leaves it empty and install.sh never sets it
    assert "WD_LOG_FILE" not in (REPO / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert diag.tail_lines(cfg, 200) == []
    log = tmp_path / "wd.log"
    log.write_text("a\nb\nc\n", encoding="utf-8")
    assert diag.tail_lines(Settings.from_env({"WD_DATA_DIR": str(tmp_path), "WD_LOG_FILE": str(log)}), 2) == ["b", "c"]


def test_runbooks_describe_wd_logs_truthfully():
    row = next(l for l in section(doc("ops.md"), "## 1. Daily checks").splitlines() if l.startswith("| Last 200 log lines"))
    command = row.split("|")[2].strip()
    assert command.startswith("`journalctl -u word-dance -n 200"), command
    assert "wd logs" in command and "WD_LOG_FILE" in command and "wd serve" in command
    logs = section(doc("DEPLOY.md"), "## 6. Logs")
    sentence = next(s for s in re.split(r"(?<=\.)\s+", logs) if "wd logs" in s)
    assert "WD_LOG_FILE" in sentence and "journalctl -u word-dance -n N" in sentence and "wd serve" in sentence, sentence
    assert "prints the in-memory ring buffer (2000 lines) for quick debugging" not in logs


# ----------------------------------------------------------------------------- ops.md §4–§6 / DEPLOY §10–§11
def test_move_data_dir_runbook_passes_wd_data_dir_to_install_sh():
    install = (REPO / "deploy" / "install.sh").read_text(encoding="utf-8")
    # the premise: install.sh takes the data directory from the environment variable, else from the installed unit's
    # EnvironmentFile= line (fix2/deploy-docs; never from a relocated .env), then sources .env — so the resolved value
    # and the file must agree — and re-renders both units
    assert re.search(r"^DATA=\$\{WD_DATA_DIR:-", install, re.M)
    assert re.search(r"^UNIT_FILE=\$\{WD_UNIT_FILE:-/etc/systemd/system/word-dance\.service\}", install, re.M)
    assert re.search(r'^\s*set -a; \. "\$DATA/\.env"; set \+a', install, re.M)
    for unit in ("word-dance.service", "word-dance-backup.service"):
        assert "EnvironmentFile=__DATA__/.env" in (REPO / "deploy" / unit).read_text(encoding="utf-8")

    ops = doc("ops.md")
    procedure = section(ops, "## 5. Configuration changes")
    assert "Moving the data directory" in procedure
    assert "EnvironmentFile=__DATA__/.env" in procedure and "never edited by hand" in procedure
    block = re.search(r"```bash\n(.*?)```", procedure, re.S)
    assert block, "the move procedure must be a runnable block"
    positions = []
    for pattern in (
        r"^sudo systemctl stop word-dance",
        r"^mv /home/sqin/word-dance-data ",
        r"^sed -i .*WD_DATA_DIR=",  # the moved .env is rewritten BEFORE install.sh sources it
        r"^WD_DATA_DIR=\S+ deploy/install\.sh",  # the only way install.sh learns the new path
        r"^echo .*export WD_DATA_DIR=",  # every later `wd …` / install.sh run defaults to the old path otherwise
    ):
        m = re.search(pattern, block.group(1), re.M)
        assert m, pattern
        positions.append(m.start())
    assert positions == sorted(positions), "steps out of order"
    assert "edit `.env` + unit `EnvironmentFile`" not in ops  # the instruction install.sh step 7 would have overwritten

    row = next(l for l in section(ops, "## 6. Runbook").splitlines() if l.startswith("| Disk low"))
    assert "§5" in row and "WD_DATA_DIR=<new> deploy/install.sh" in row and "unit `EnvironmentFile`" not in row
    assert "WD_DATA_DIR" in section(ops, "## 4. Upgrade")  # every later install.sh run needs the prefix too

    deploy = doc("DEPLOY.md")
    row11 = next(l for l in section(deploy, "## 11. Runbook").splitlines() if l.startswith("| Disk low"))
    assert "WD_DATA_DIR=<new> deploy/install.sh" in row11 and "ops.md §5" in row11
    assert "WD_DATA_DIR=<dir>" in section(deploy, "## 10. Upgrade")


# --------------------------------------------------------------------------- DEPLOY §8 / ops.md §8 / qa-study.md
def test_dev_docs_say_vite_binds_localhost_only():
    vite = (REPO / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    server = re.search(r"server: \{(.*?)proxy:", vite, re.S)
    assert server and "host" not in server.group(1)  # the premise: no server.host → Vite listens on localhost only
    for name, heading in (("DEPLOY.md", "## 8. Development workflow"), ("ops.md", "## 8. Tests and smoke")):
        text = section(doc(name), heading)
        assert "http://localhost:5173" in text and "npm run dev -- --host" in text, name
    qa = doc("qa-study.md")
    assert "npm run dev -- --host" in qa and "http://localhost:5173" in qa


# ------------------------------------------------------------------------------------------ FRONTEND §8
def test_frontend_copy_contract_lists_the_p0_keys():
    """FRONTEND §8 is 'binding' and zh.ts claims to be '§8 verbatim': the three keys P0 had to add are in both
    (frontend/src/i18n/zh.contract.test.ts compares the whole table)."""
    block = re.search(r"## 8\. i18n strings.*?```ts\n(.*?)```", doc("FRONTEND.md"), re.S)
    assert block
    zh = (REPO / "frontend" / "src" / "i18n" / "zh.ts").read_text(encoding="utf-8")
    for key in ("backToToday: '回到今日'", "speak: '发音'", "speechUnsupported: '当前浏览器不支持语音'"):
        assert key in block.group(1) and key in zh, key


# ------------------------------------------------------------------------------------------ API.md §9 ↔ types.ts
def test_types_ts_is_api_section_9_verbatim():
    """types.ts calls itself 'API.md §9 copied verbatim' (its header comment) and scripts/check_contract.py compares it with
    schemas.py only: this pins the §9 ``ts`` block to the file — the header comment and the blank line after it excluded — so a DTO
    or a literal union (``DancePrimitive``, 单词之舞 P3) edited in one place fails here instead of drifting."""
    block = re.search(r"```ts\n(.*?)\n```", section(doc("API.md"), "## 9. Shared TypeScript DTOs"), re.S)
    assert block
    lines = (REPO / "frontend" / "src" / "api" / "types.ts").read_text(encoding="utf-8").splitlines()
    header, lines = lines[:4], lines[4:]  # exactly the three-line header comment and its blank line — a stray comment is drift
    assert header[0].startswith("// word-Dance — shared DTOs. FROZEN CONTRACT") and all(l.startswith("//") for l in header[:3]) and header[3] == ""
    assert lines[0].startswith("export type Stage")
    assert "\n".join(lines).rstrip("\n") == block.group(1).rstrip("\n")
    # the DanceSpec header describes the P3b serving rule (spec_for_word), not P2's "stored spec wins"
    header_line = next(l for l in block.group(1).splitlines() if l.startswith("export interface DanceSpec"))
    assert "spec_for_word" in header_line and "when the word has one, else derived" not in header_line


# ------------------------------------------------------ learning order (docs/analysis/2026-11-06-learn-order/DESIGN.md §4.1 item 23)
def sql_shape(fragment: str) -> str:
    """An ``ORDER BY`` fragment the way the docs quote it: no ``w.`` alias, no ``ASC``, no cosmetic whitespace."""
    text = re.sub(r"\bw\.", "", fragment)
    text = re.sub(r"\s+ASC\b", "", text)
    text = re.sub(r"\s*=\s*", "=", text)
    return re.sub(r"\s+", " ", text).strip()


def endpoint(api: str, number: int) -> str:
    """The paragraph of API.md endpoint ``number``: its ``**N `…`**`` line and the lines up to the next endpoint or blank line."""
    lines = api.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"**{number} `"))
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip() or re.match(r"^\*\*\d+ `", line) or line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def test_docs_quote_the_learning_order():
    """API.md 20 / 22 / 31, DESIGN §3.2 / §6.2 / §6.3 step 4, WORD_LIBRARY_CURATION §1.6 and CLAUDE_INTEGRATION's prewarm paragraph
    quote ``learn_order.ORDER_SQL`` (the ``w.`` alias stripped) and the NULL stage distance, not the pre-0014 frequency order; the
    lookup suggestions are the documented exception that keeps ``FRQ_TAIL``."""
    from wd.services import learn_order

    order = sql_shape(learn_order.ORDER_SQL)
    tail = sql_shape(learn_order.FRQ_TAIL)
    assert order.startswith("learn_rank IS NULL, learn_rank, ") and order.endswith(tail)  # the module keeps the fail-soft tail
    null_distance = learn_order.STAGE_NULL_DISTANCE

    api = doc("API.md")
    vocab = endpoint(api, 20)
    assert "学习顺序" in vocab and sql_shape(vocab).count(order) == 2, vocab  # the `freq` and the `difficulty` sort
    assert f"NULL → {null_distance}" in vocab
    lookup = endpoint(api, 22)
    assert "suggestions keep raw frequency" in lookup and tail in sql_shape(lookup) and order not in sql_shape(lookup)
    screen = endpoint(api, 31)
    assert "by frequency" not in screen and "`learn_rank`" in screen and f"distance {null_distance}" in screen

    design = doc("DESIGN.md")
    mapping = section(design, "### 3.2")
    assert "| `learn_rank` |" in mapping and "`wd learn-order`" in mapping and "0014" in mapping
    assert "`learn_rank`" in section(design, "### 6.2")
    step4 = section(design, "### 6.3")
    assert order in sql_shape(step4) and f"{null_distance} if s is NULL" in step4
    assert "frq=0) ASC, w.frq ASC, w.lemma ASC" not in step4  # the pre-0014 tail

    curation = section(doc("WORD_LIBRARY_CURATION.md"), "### 1.6")
    assert "`learn_rank`" in curation and "`wd learn-order`" in curation and f"距离为 {null_distance}" in curation
    prewarm = next(l for l in doc("CLAUDE_INTEGRATION.md").splitlines() if l.startswith("**`prewarm_plan` mechanics**"))
    assert "`words.learn_rank`" in prewarm and "by frequency" not in prewarm


def test_runbooks_name_the_eight_invariants_and_the_learn_order_command(settings, seeded):
    """ops.md §1 and TASKS.md list the ``wd check db`` invariant names in ``diag`` order (the order ``check_db`` prints them); the
    release note carries every ``invariant <name>: ok`` line; DEPLOY §9 lists `learn-order` with exactly the options the parser
    registers (DESIGN §2.5) under its owning module."""
    from wd import cli, diag

    result = diag.check_db(settings)
    names = tuple(m.group(1) for line in result.lines if (m := re.match(r"invariant (\w+):", line)))
    assert len(names) == 8 == len(set(names)) and names[:3] == tuple(n for n, _ in diag.STAGE_INVARIANTS), names

    daily = section(doc("ops.md"), "## 1. Daily checks")
    positions = [daily.find(f"`{name}`") for name in names]
    assert min(positions) >= 0 and positions == sorted(positions), dict(zip(names, positions))
    assert "`wd learn-order`" in daily
    assert "# invariant " + " / ".join(names) + ": ok" in doc("TASKS.md")
    release = doc("releases/2026-11-learn-order.md")
    assert all(f"invariant {name}: ok" in release for name in names), names

    cli_ref = section(doc("DEPLOY.md"), "## 9. CLI reference")
    usage = re.search(r"`learn-order ([^`]*)`", cli_ref)
    assert usage and "[`wd.services.learn_order`]" in cli_ref, cli_ref
    choices = cli.build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    registered = {o for o in choices["learn-order"]._option_string_actions if o.startswith("--") and o != "--help"}
    assert set(re.findall(r"--[a-z][a-z-]*", usage.group(1))) == registered, (usage.group(1), registered)


def test_learning_order_copy_and_release_note():
    """FRONTEND §5.5 / §8 and zh.ts carry the 学习顺序 label (the wire value stays `freq`); DEPLOY §5 / §10 and ops.md §4 call 0014
    additive; the K-12 note, PLAN §9.2 #5 and the quick-deploy guide point at the new release note, which names the migration, the
    launchd agent, the restart command, the pre-migrate snapshot and the rollback target."""
    frontend = doc("FRONTEND.md")
    block = re.search(r"## 8\. i18n strings.*?```ts\n(.*?)```", frontend, re.S)
    assert block
    zh = (REPO / "frontend" / "src" / "i18n" / "zh.ts").read_text(encoding="utf-8")
    line = "sort: { freq: '学习顺序', alpha: '字母', difficulty: '难度' }"
    assert line in block.group(1) and line in zh and "freq: '词频'" not in zh
    browser = section(frontend, "### 5.5")
    assert "学习顺序" in browser and "`sort=freq`" in browser

    deploy = doc("DEPLOY.md")
    assert "`0014_learn_rank.sql`" in section(deploy, "## 5. Backups and restore")
    assert "`0014_learn_rank.sql`" in section(deploy, "## 10. Upgrade and rollback")
    upgrade = section(doc("ops.md"), "## 4. Upgrade and rollback")
    assert "`0014_learn_rank.sql`" in upgrade and "eight invariants" in upgrade and "four stage invariants" not in upgrade

    assert "docs/releases/2026-11-learn-order.md" in doc("releases/2026-11-k12-stages.md")
    plan = (DOCS / "analysis" / "2026-11-05-stages-regions-images" / "design" / "PLAN.md").read_text(encoding="utf-8")
    assert "已解决（2026-11-06，docs/analysis/2026-11-06-learn-order/DESIGN.md）" in plan
    assert "八条" in doc("QUICK_DEPLOY_AND_MOBILE.md") and "docs/releases/2026-11-learn-order.md" in doc("QUICK_DEPLOY_AND_MOBILE.md")

    release = doc("releases/2026-11-learn-order.md")
    for needle in (
        "0014_learn_rank.sql",
        "com.word-dance.server",
        "launchctl kickstart -k gui/$(id -u)/com.word-dance.server",
        "pre-migrate-13-to-14.db.gz",
        "applied migration 0014_learn_rank",
        "deploy/install.sh",
        "git checkout cd3df8c",
        "data/seed/learn_order.json",
    ):
        assert needle in release, needle
