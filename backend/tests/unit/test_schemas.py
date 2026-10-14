"""ai/schemas/*.json: verbatim copies of CLAUDE_INTEGRATION §2/§4, keyword restrictions, the batch-size clamp, the probe
schema's enum/array coverage, and the fixture outputs validating against both the schema files and the Pydantic mirrors."""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

from wd.ai import models, runner
from wd.config import Settings

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = ROOT / "backend/wd/ai/schemas"
PROMPTS_DIR = ROOT / "backend/wd/ai/prompts"
FIXTURES = ROOT / "backend/tests/fixtures"
DOC = (ROOT / "docs/CLAUDE_INTEGRATION.md").read_text(encoding="utf-8")
NAMES = ("probe_v1", "content_v1", "lookup_v1", "consolidate_v1", "svg_v1")
ALLOWED_KEYWORDS = {"type", "properties", "required", "items", "minItems", "maxItems", "description", "enum"}
FORBIDDEN_KEYWORDS = {"$ref", "additionalProperties", "minLength", "maxLength", "minimum", "maximum", "anyOf", "oneOf", "allOf"}
DOC_HEADINGS = {
    "probe_v1": "## 2. Install-time probe",
    "content_v1": "### 4.1 `content_v1.json`",
    "lookup_v1": "### 4.2 `lookup_v1.json`",
    "consolidate_v1": "### 4.3 `consolidate_v1.json`",
    "svg_v1": "### 4.4 `svg_v1.json`",
}


def doc_block(heading: str, lang: str = "json") -> str:
    start = DOC.index(heading)
    m = re.compile(r"```" + lang + r"\n(.*?)\n```", re.DOTALL).search(DOC, start)
    assert m, heading
    return m.group(1)


def keywords_of(node, found: set[str]) -> None:
    if not isinstance(node, dict):
        return
    for k, v in node.items():
        if k == "properties":
            for sub in v.values():
                keywords_of(sub, found)
            found.add(k)
        elif k == "items":
            found.add(k)
            keywords_of(v, found)
        else:
            found.add(k)


@pytest.mark.parametrize("name", NAMES)
def test_schema_file_is_verbatim_from_the_contract_and_the_fixture_copy(name):
    text = (SCHEMAS_DIR / f"{name}.json").read_text(encoding="utf-8")
    parsed = json.loads(text)
    assert text.rstrip("\n") == doc_block(DOC_HEADINGS[name])  # byte-for-byte the §2/§4 code block
    fixture = json.loads((FIXTURES / "claude_schemas.json").read_text(encoding="utf-8"))
    assert parsed == fixture[name]
    assert runner.load_schema(name) == parsed


@pytest.mark.parametrize("name", NAMES)
def test_schema_uses_only_the_probe_validated_keywords(name):
    schema = runner.load_schema(name)
    found: set[str] = set()
    keywords_of(schema, found)
    assert found <= ALLOWED_KEYWORDS, found - ALLOWED_KEYWORDS
    assert not (found & FORBIDDEN_KEYWORDS)
    assert "$ref" not in json.dumps(schema)
    jsonschema.Draft202012Validator.check_schema(schema)


def test_content_schema_max_items_matches_the_batch_size_clamp():
    max_items = runner.load_schema("content_v1")["properties"]["items"]["maxItems"]
    assert max_items >= 12
    assert Settings.from_env({"WD_AI_BATCH_SIZE": "99", "WD_DATA_DIR": "/tmp/wd-schemas-test"}).ai_batch_size == 12 == max_items


def test_probe_schema_exercises_enum_and_bounded_array():
    props = runner.load_schema("probe_v1")["properties"]
    assert props["level"] == {"type": "integer", "enum": [1, 2, 3]}
    assert props["mode"] == {"type": "string", "enum": ["a", "b"]}
    assert props["tags"]["type"] == "array" and props["tags"]["minItems"] == 1 and props["tags"]["maxItems"] == 2
    assert props["ok"]["type"] == "boolean" and props["echo"]["type"] == "string"


@pytest.mark.parametrize(
    "fixture,name,n",
    [("claude_content_ok.json", "content_v1", 10), ("claude_lookup_ok.json", "lookup_v1", 5), ("claude_consolidate_ok.json", "consolidate_v1", 7)],
)
def test_fixture_outputs_validate_against_schema_and_pydantic_mirror(fixture, name, n):
    data = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))["structured_output"]
    jsonschema.validate(data, runner.load_schema(name))
    mirror = models.OUTPUT_MODELS[name].model_validate(data)
    assert len(mirror.items) == n  # type: ignore[attr-defined]
    assert len(models.valid_items(data, {"content_v1": models.ContentItem, "lookup_v1": models.LookupItem, "consolidate_v1": models.ConsolidateItem}[name])) == n


def test_probe_and_svg_mirrors():
    probe = {"ok": True, "echo": "word-dance", "level": 2, "mode": "b", "tags": ["probe"]}
    jsonschema.validate(probe, runner.load_schema("probe_v1"))
    assert models.ProbeOutput.model_validate(probe).model_dump() == probe
    with pytest.raises(Exception):
        models.ProbeOutput.model_validate({**probe, "level": 7})
    svg = {"svg": "<svg xmlns='http://www.w3.org/2000/svg'/>", "alt_zh": "示意图"}
    jsonschema.validate(svg, runner.load_schema("svg_v1"))
    assert models.SvgOutput.model_validate(svg).svg.startswith("<svg")


def test_valid_items_drops_invalid_entries():
    good = json.loads((FIXTURES / "claude_lookup_ok.json").read_text(encoding="utf-8"))["structured_output"]["items"][0]
    bad = {**good}
    bad.pop("headword")
    assert len(models.valid_items({"items": [good, bad, "junk", 3]}, models.LookupItem)) == 1
    assert models.valid_items({"items": "nope"}, models.LookupItem) == []
    assert models.valid_items(None, models.LookupItem) == []


@pytest.mark.parametrize("name,heading", [("content_system", "### 5.1"), ("lookup_system", "### 5.3"), ("consolidate_system", "### 5.4"), ("svg_system", "### 5.5")])
def test_prompts_are_verbatim_from_section_5(name, heading):
    text = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n")
    assert text == doc_block(heading, lang="")
    assert runner.load_prompt(name) == text
    assert text and text[0].isalpha()  # the prompt argument can never be parsed as a flag
