"""images/style.py: the dominant ECDICT pos code, the function-word gate, the bare-lemma rule, stage codes and the per-word
picture style driven by WD_IMAGE_KID_STAGES (design/images/SYNTHESIS.md §3.1.3, PLAN §5.1 C3)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from wd.images import style
from wd.schemas import STAGE_ORDER, stage_to_index


@pytest.mark.parametrize(
    "pos, expected",
    [
        ("n:4/v:96", "v"),
        ("v:96/n:4", "v"),
        ("n:50/v:50", "n"),  # ties keep the first listed
        ("i:100", "i"),
        ("d:97/n:3", "d"),
        ("a:99/t:1", "a"),
        ("n:100", "n"),
        (" n:60 / j:40 ", "n"),
        (None, None),
        ("", None),
        ("v./n.", None),  # a Claude label, not a share distribution
        ("abbr.", None),
        ("n:", None),
        ("n:x/v:1", None),
    ],
)
def test_dominant_pos(pos, expected):
    assert style.dominant_pos(pos) == expected


def test_function_pos_matches_the_frontend_code_table_without_adverbs():
    """FUNCTION_POS = prep. conj. det. pron. art. int. inf. (frontend/src/utils/pos.ts POS_LABELS); adverbs are not gated
    (fast / today are drawable, very / why are not — the pilot decides) but never get a bare-lemma search."""
    assert style.FUNCTION_POS == frozenset({"i", "c", "d", "p", "a", "u", "t"})
    assert "r" not in style.FUNCTION_POS and "x" not in style.FUNCTION_POS
    assert style.NO_BARE_LEMMA_POS == style.FUNCTION_POS | {"r"}
    assert style.STYLES == ("kid", "neutral") == (style.STYLE_KID, style.STYLE_NEUTRAL)


@pytest.mark.parametrize("pos", ["i:100", "c:100", "d:97/n:3", "p:80/d:20", "a:99/t:1", "u:100", "t:100"])
def test_skip_image_for_function_words(pos):
    assert style.skip_image({"lemma": "x", "pos": pos}) is True
    assert style.allows_bare_lemma({"pos": pos}) is False


@pytest.mark.parametrize("pos", ["n:100", "v:96/n:4", "r:100", "m:100", "j:100", None, "", "v./n."])
def test_content_words_and_unknown_pos_are_not_skipped(pos):
    assert style.skip_image({"lemma": "x", "pos": pos}) is False


def test_allows_bare_lemma():
    assert style.allows_bare_lemma({"pos": "r:100"}) is False  # an adverb: no bare-lemma photo search (D-images-9)
    assert style.allows_bare_lemma({"pos": "r:60/j:40"}) is False
    assert style.allows_bare_lemma({"pos": "n:100"}) is True
    assert style.allows_bare_lemma({"pos": "j:70/r:30"}) is True
    assert style.allows_bare_lemma({"pos": None}) is True  # a phrase or a Claude word: unknown pos → allowed
    assert style.allows_bare_lemma({}) is True


def test_stage_code_follows_schemas_and_never_raises():
    assert style.stage_code(1) == "xs" == STAGE_ORDER[0]  # 1 = 小学 after the 0011 renumbering
    assert style.stage_code(2) == "zk" and style.stage_code(5) == "cet6"
    assert [style.stage_code(stage_to_index(s)) for s in STAGE_ORDER] == list(STAGE_ORDER)
    assert style.stage_code("xs") == "xs"  # a stages-as-data schema would store the code itself
    assert style.stage_code(None) is None
    assert style.stage_code(0) is None and style.stage_code(99) is None and style.stage_code(-1) is None  # out of range: None, not ValueError
    assert style.stage_code("") is None and style.stage_code(True) is None and style.stage_code(2.0) is None


def test_style_for_is_neutral_by_default_and_kid_only_for_listed_stages(settings):
    assert settings.image_kid_stages == ()
    for stage_min in (1, 2, 3, None, 99):
        assert style.style_for({"stage_min": stage_min}, settings) == "neutral"
    zk_cfg = replace(settings, image_kid_stages=("zk",))
    assert style.style_for({"stage_min": 2}, zk_cfg) == "kid"
    assert style.style_for({"stage_min": 3}, zk_cfg) == "neutral"
    assert style.style_for({"stage_min": 1}, zk_cfg) == "neutral"
    assert style.style_for({"stage_min": None}, zk_cfg) == "neutral"  # outside every list: never a child
    xs_cfg = replace(settings, image_kid_stages=("xs",))
    assert style.style_for({"stage_min": 1}, xs_cfg) == "kid" and style.style_for({"stage_min": 2}, xs_cfg) == "neutral"
    assert style.style_for({"stage_min": "xs"}, xs_cfg) == "kid"
    assert style.style_for({}, xs_cfg) == "neutral"
