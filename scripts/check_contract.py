#!/usr/bin/env python3
"""Contract audit (TASKS post-step 2): backend/wd/schemas.py ↔ frontend/src/api/types.ts.

Both files mirror API.md §9. This script compares them field by field and prints every mismatch:

* every ``export interface`` in types.ts is matched with the Pydantic model of the same name (a few names differ,
  see ALIASES) and the **property names** are compared with the model's JSON-schema ``properties`` (serialization
  mode, so aliases such as ``SuggestionPayload.from`` count). ``extends`` is followed on the TS side; an inline object
  property (``word: WordBrief & { definition: … }``, ``item: { item_id: … }``) is compared recursively with the
  referenced ``$defs`` entry of the Pydantic field.
* every ``export type X = 'a' | 'b'`` string/number-literal union is compared with ``typing.get_args(schemas.X)``.
* optional (``?:``) vs required and ``| null`` vs non-nullable differences are reported as notes (they do not fail
  the run — API.md treats them loosely for read-only fields), missing/extra property names do.

Exit status 0 when no hard mismatch was found, 1 otherwise. Run from the repository root::

    .venv/bin/python scripts/check_contract.py            # or: make check-contract
"""

from __future__ import annotations

import argparse
import re
import sys
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
TYPES_TS = REPO / "frontend" / "src" / "api" / "types.ts"
sys.path.insert(0, str(REPO / "backend"))

# TS interface → Pydantic model when the names differ (API.md §9 keeps the TS spelling)
ALIASES: dict[str, str] = {"ApiError": "ApiErrorEnvelope"}
# TS interfaces with no wire counterpart in schemas.py (generic helpers only)
SKIP: frozenset[str] = frozenset()


# ------------------------------------------------------------------------------------------ TS parsing
@dataclass
class TsProp:
    name: str
    optional: bool
    nullable: bool
    type_text: str
    inline: "TsShape | None" = None  # the `{ … }` part of an inline object type (also `X & { … }` and `{ … }[]`)
    inline_bases: tuple[str, ...] = ()  # interfaces intersected with the inline object (`WordBrief & { … }`)


@dataclass
class TsShape:
    props: dict[str, TsProp] = field(default_factory=dict)


@dataclass
class TsInterface:
    name: str
    extends: str | None
    shape: TsShape


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    out: list[str] = []
    for line in src.splitlines():
        # drop // comments outside string literals
        in_str: str | None = None
        for i, ch in enumerate(line):
            if in_str:
                if ch == in_str:
                    in_str = None
            elif ch in "'\"`":
                in_str = ch
            elif ch == "/" and line[i : i + 2] == "//":
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


def matching_brace(src: str, open_at: int) -> int:
    depth = 0
    for i in range(open_at, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced braces")


def split_members(body: str) -> list[str]:
    """Split an interface body into member declarations at depth-0 ``;`` / newlines."""
    members: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in body:
        if ch in "{<([":
            depth += 1
        elif ch in "}>)]":
            depth -= 1
        if depth == 0 and ch in ";\n":
            text = "".join(buf).strip()
            if text:
                members.append(text)
            buf = []
            continue
        buf.append(ch)
    text = "".join(buf).strip()
    if text:
        members.append(text)
    return members


def parse_shape(body: str) -> TsShape:
    shape = TsShape()
    for member in split_members(body):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(\?)?\s*:\s*(.+)$", member, flags=re.S)
        if not m:
            continue  # method signatures / index signatures do not occur in types.ts
        name, opt, type_text = m.group(1), bool(m.group(2)), " ".join(m.group(3).split())
        inline = None
        bases: tuple[str, ...] = ()
        brace = type_text.find("{")
        if brace != -1 and (type_text.strip().startswith("{") or "&" in type_text[:brace]):
            end = matching_brace(type_text, brace)
            inline = parse_shape(type_text[brace + 1 : end])
            bases = tuple(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", type_text[:brace]))
        nullable = bool(re.search(r"(^|\|)\s*null\s*($|\|)", strip_top_level_braces(type_text)))
        shape.props[name] = TsProp(name, opt, nullable, type_text, inline, bases)
    return shape


def strip_top_level_braces(text: str) -> str:
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch in "{<([":
            depth += 1
            continue
        if ch in "}>)]":
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def parse_types_ts(src: str) -> tuple[dict[str, TsInterface], dict[str, list[Any]]]:
    src = strip_comments(src)
    interfaces: dict[str, TsInterface] = {}
    for m in re.finditer(r"export interface ([A-Za-z0-9_]+)(?:<[^>]*>)?\s*(?:extends\s+([A-Za-z0-9_]+)(?:<[^>]*>)?)?\s*\{", src):
        end = matching_brace(src, m.end() - 1)
        interfaces[m.group(1)] = TsInterface(m.group(1), m.group(2), parse_shape(src[m.end() : end]))
    unions: dict[str, list[Any]] = {}
    for m in re.finditer(r"export type ([A-Za-z0-9_]+)\s*=\s*([^;]+);", src):
        parts = [p.strip() for p in m.group(2).split("|")]
        values: list[Any] = []
        for p in parts:
            if re.fullmatch(r"'[^']*'", p):
                values.append(p[1:-1])
            elif re.fullmatch(r"-?\d+", p):
                values.append(int(p))
            else:
                values = []
                break
        if values:
            unions[m.group(1)] = values
    return interfaces, unions


def ts_props(name: str, interfaces: dict[str, TsInterface]) -> dict[str, TsProp]:
    """Own properties plus the inherited ones (``extends``)."""
    iface = interfaces[name]
    props: dict[str, TsProp] = {}
    if iface.extends and iface.extends in interfaces:
        props.update(ts_props(iface.extends, interfaces))
    props.update(iface.shape.props)
    return props


# --------------------------------------------------------------------------------------- Pydantic side
def model_schema(model: Any) -> dict[str, Any]:
    return model.model_json_schema(mode="serialization")


def resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any] | None:
    """Follow ``$ref`` / ``anyOf`` / ``allOf`` / array ``items`` to the object schema a field refers to."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return root.get("$defs", {}).get(name)
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        return resolve_ref(schema["items"], root)
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in schema.get(key, []):
            found = resolve_ref(sub, root)
            if found is not None and found.get("type") == "object":
                return found
    if schema.get("type") == "object" and "properties" in schema:
        return schema
    return None


def is_nullable(schema: dict[str, Any]) -> bool:
    if schema.get("type") == "null":
        return True
    for sub in schema.get("anyOf", []) + schema.get("oneOf", []):
        if sub.get("type") == "null":
            return True
    return False


# ------------------------------------------------------------------------------------------ comparison
@dataclass
class Findings:
    hard: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def compare_shape(path: str, ts: dict[str, TsProp], py: dict[str, Any], root: dict[str, Any], out: Findings, interfaces: dict[str, TsInterface]) -> None:
    props = py.get("properties", {})
    required = set(py.get("required", []))
    ts_names, py_names = set(ts), set(props)
    for name in sorted(ts_names - py_names):
        out.hard.append(f"{path}.{name}: in types.ts, missing from schemas.py")
    for name in sorted(py_names - ts_names):
        out.hard.append(f"{path}.{name}: in schemas.py, missing from types.ts")
    for name in sorted(ts_names & py_names):
        tp, ps = ts[name], props[name]
        if tp.optional == (name in required):
            out.notes.append(f"{path}.{name}: {'optional' if tp.optional else 'required'} in types.ts, {'required' if name in required else 'optional'} in schemas.py")
        if tp.nullable != is_nullable(ps):
            out.notes.append(f"{path}.{name}: {'nullable' if tp.nullable else 'non-null'} in types.ts, {'nullable' if is_nullable(ps) else 'non-null'} in schemas.py")
        if tp.inline is not None:
            target = resolve_ref(ps, root)
            if target is None:
                out.hard.append(f"{path}.{name}: inline object in types.ts but no object schema in schemas.py")
                continue
            inline_props: dict[str, TsProp] = {}
            for base in tp.inline_bases:
                if base in interfaces:
                    inline_props.update(ts_props(base, interfaces))
            inline_props.update(tp.inline.props)
            compare_shape(f"{path}.{name}", inline_props, target, root, out, interfaces)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="schemas.py ↔ types.ts contract audit (property names, literal unions)")
    parser.add_argument("--types", default=str(TYPES_TS), help="path to types.ts (default: frontend/src/api/types.ts)")
    parser.add_argument("-q", "--quiet", action="store_true", help="print mismatches only")
    args = parser.parse_args(argv)

    from wd import schemas

    interfaces, unions = parse_types_ts(Path(args.types).read_text(encoding="utf-8"))
    out = Findings()
    compared: list[str] = []
    for name, iface in interfaces.items():
        if name in SKIP:
            continue
        py_name = ALIASES.get(name, name)
        model = getattr(schemas, py_name, None)
        if model is None or not (isinstance(model, type) and issubclass(model, schemas.Model)):
            out.hard.append(f"{name}: interface in types.ts has no Pydantic model {py_name} in schemas.py")
            continue
        if py_name == "Page":
            model = schemas.Page[Any]  # the generic itself
        root = model_schema(model)
        compare_shape(name, ts_props(name, interfaces), root, root, out, interfaces)
        compared.append(name)

    for name, values in unions.items():
        alias = getattr(schemas, name, None)
        if alias is None:
            out.hard.append(f"type {name}: literal union in types.ts has no Literal alias in schemas.py")
            continue
        py_values = list(typing.get_args(alias))
        if py_values != values:
            out.hard.append(f"type {name}: types.ts {values} ≠ schemas.py {py_values}")

    # the reverse direction is informational: request bodies, query models and prose-defined responses have no TS interface
    ts_models = {ALIASES.get(n, n) for n in interfaces}
    unmirrored = sorted(
        n
        for n, obj in vars(schemas).items()
        if isinstance(obj, type) and issubclass(obj, schemas.Model) and obj is not schemas.Model and n not in ts_models and not n.endswith(("Request", "Query"))
    )

    if not args.quiet:
        print(f"compared {len(compared)} interfaces and {len(unions)} literal unions of {Path(args.types).relative_to(REPO) if Path(args.types).is_relative_to(REPO) else args.types}")
        if unmirrored:
            print(f"schemas.py models without a types.ts interface (expected: endpoint-local responses): {', '.join(unmirrored)}")
    for note in out.notes:
        print(f"note  {note}")
    for hard in out.hard:
        print(f"MISMATCH  {hard}")
    if out.hard:
        print(f"{len(out.hard)} mismatch(es)")
        return 1
    print("contract OK: no property-name or literal-union mismatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
