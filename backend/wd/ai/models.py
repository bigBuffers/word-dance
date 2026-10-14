"""Pydantic mirrors of the ``--json-schema`` payloads (CLAUDE_INTEGRATION §2/§4).

The handlers use them for the first, structural pass over ``structured_output`` (an item missing a required key or
carrying the wrong type never reaches the semantic post-validation of §6.4–6.6); ``tests/unit/test_schemas.py``
checks that the fixture outputs validate against both the JSON schema files and these mirrors.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError


class Mirror(BaseModel):
    """Unknown keys are ignored (the schemas carry no ``additionalProperties``), values are coerced leniently."""

    model_config = ConfigDict(extra="ignore")


class ProbeOutput(Mirror):
    ok: bool
    echo: str
    level: Literal[1, 2, 3]
    mode: Literal["a", "b"]
    tags: list[str]


class ContentExample(Mirror):
    en: str
    zh: str


class ContentItem(Mirror):
    word: str
    valid: bool
    meaning_zh: str
    meaning_en: str
    examples: list[ContentExample]
    collocations: list[str]
    mnemonic_zh: str
    image_keywords: list[str]
    image_alt_zh: str
    difficulty: Literal[1, 2, 3, 4, 5]


class ContentOutput(Mirror):
    items: list[ContentItem]


class LookupItem(Mirror):
    input: str
    is_english: bool
    kind: Literal["word", "phrase", "abbreviation", "proper_noun", "invalid"]
    headword: str
    form_note_zh: str
    phonetic: str
    pos: str
    meaning_zh: str
    definition_en: str
    difficulty: Literal[1, 2, 3, 4, 5]
    suggested_correction: str
    safe_for_sharing: bool
    note_zh: str


class LookupOutput(Mirror):
    items: list[LookupItem]


class ConsolidateFill(Mirror):
    phonetic: str
    pos: str
    meaning_zh: str
    definition_en: str
    difficulty: Literal[1, 2, 3, 4, 5]


class ConsolidateItem(Mirror):
    id: int
    verdict: Literal["ok", "lemmatize", "merge_duplicate", "fix_spelling", "invalid_word", "split_phrase", "fill_data"]
    target: str
    confidence: float
    note_zh: str
    fill: ConsolidateFill


class DifficultyTag(Mirror):
    id: int
    difficulty: Literal[1, 2, 3, 4, 5]


class ConsolidateOutput(Mirror):
    items: list[ConsolidateItem]
    confusable_groups: list[list[str]]
    difficulty_tags: list[DifficultyTag]


class SvgOutput(Mirror):
    svg: str
    alt_zh: str


OUTPUT_MODELS: dict[str, type[Mirror]] = {
    "probe_v1": ProbeOutput,
    "content_v1": ContentOutput,
    "lookup_v1": LookupOutput,
    "consolidate_v1": ConsolidateOutput,
    "svg_v1": SvgOutput,
}


def valid_items(structured: Any, model: type[Mirror]) -> list[dict[str, Any]]:
    """The ``items`` of a response that validate against ``model``, as plain dicts; invalid or non-dict items are dropped."""
    items = structured.get("items") if isinstance(structured, dict) else None
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            out.append(model.model_validate(item).model_dump())
        except ValidationError:
            continue
    return out


__all__ = [
    "ConsolidateFill",
    "ConsolidateItem",
    "ConsolidateOutput",
    "ContentExample",
    "ContentItem",
    "ContentOutput",
    "DifficultyTag",
    "LookupItem",
    "LookupOutput",
    "Mirror",
    "OUTPUT_MODELS",
    "ProbeOutput",
    "SvgOutput",
    "valid_items",
]
