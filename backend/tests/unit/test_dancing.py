"""images.dancing — the stage record of a 跳动图卡 (prompt svg-v3): what the model names is validated and written by us."""

import json

import pytest

from wd.ai import models, runner
from wd.images import dancing, sanitize_svg

CLEAN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><rect width="800" height="500" fill="#fff"/><g id="actor"><circle cx="400" cy="200" r="80"/></g></svg>'


def record(svg: str) -> dict:
    assert svg.count('<desc id="wd-stage">') == 1
    body = svg.split('<desc id="wd-stage">')[1].split("</desc>")[0]
    return json.loads(body.replace("&quot;", '"'))


def test_stage_record_follows_the_root_tag_and_keeps_the_drawing():
    staged = dancing.stage_svg(CLEAN, "hear", motion="pulse", highlight="EAR")
    assert staged.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><desc id="wd-stage">')
    assert record(staged) == {"v": 1, "motion": "pulse", "highlight": "ear"}
    assert staged.replace(staged[staged.index("<desc") : staged.index("</desc>") + 7], "") == CLEAN
    # the record survives the label and a second cleaning as a plain description
    labelled = sanitize_svg.with_label(staged, "AI")
    assert labelled.count('id="aigc-label"') == 1 and record(sanitize_svg.clean(labelled, allow_text=False)) == record(staged)


@pytest.mark.parametrize("motion", ["explode", None, "", 3, "Hop"])
def test_a_motion_outside_the_closed_list_is_a_still_picture(motion):
    assert record(dancing.stage_svg(CLEAN, "jump", motion=motion, highlight=""))["motion"] == "none"


def test_no_actor_or_two_actors_or_an_actor_that_is_not_a_group_means_no_motion():
    without = CLEAN.replace(' id="actor"', "")
    twice = CLEAN.replace("</svg>", '<g id="actor"/></svg>')
    not_a_group = without.replace("<circle ", '<circle id="actor" ')
    for svg in (without, twice, not_a_group):
        assert record(dancing.stage_svg(svg, "jump", motion="hop", highlight=""))["motion"] == "none"
    assert record(dancing.stage_svg(CLEAN, "jump", motion="hop", highlight=""))["motion"] == "hop"


def test_an_id_of_our_prefix_written_by_the_model_is_removed_first():
    forged = CLEAN.replace("<rect ", '<desc id="wd-stage">{"v":1,"motion":"spin","highlight":"x"}</desc><rect id="wd-x" ')
    staged = dancing.stage_svg(forged, "jump", motion="hop", highlight="")
    assert staged.count('id="wd-') == 1 and record(staged) == {"v": 1, "motion": "hop", "highlight": ""}


@pytest.mark.parametrize(
    "display,given,kept",
    [("hear", "ear", "ear"), ("Book", "OO", "oo"), ("hear", "hear", ""), ("hear", "eye", ""), ("hear", "e", ""), ("ice cream", "e c", ""), ("hear", None, ""), ("hear", " ear ", "ear")],
)
def test_highlight_is_a_shorter_run_of_letters_found_in_the_headword(display, given, kept):
    assert dancing.highlight_of(display, given) == kept


def test_hook_is_one_line_of_at_most_sixty_characters_or_none():
    assert dancing.hook_of("  hear 里藏着\n ear ") == "hear 里藏着 ear"
    assert dancing.hook_of("") is None and dancing.hook_of(None) is None
    assert len(dancing.hook_of("长" * 80)) == dancing.HOOK_MAX_CHARS


def test_recognition_rule_and_the_one_motion_list():
    assert dancing.is_dancing({"provider": "claude_svg", "prompt_version": "svg-v3"})
    for row in ({"provider": "claude_svg", "prompt_version": "svg-v2"}, {"provider": "claude_svg", "prompt_version": "memo-1"}, {"provider": "claude_svg", "prompt_version": None}, {"provider": "wikimedia", "prompt_version": "svg-v3"}, {"provider": "claude_svg"}, None):
        assert not dancing.is_dancing(row)
    schema = runner.load_schema("svg_v1")
    assert tuple(schema["properties"]["motion"]["enum"]) == dancing.MOTIONS
    assert schema["required"] == ["svg", "alt_zh"]  # the three stage fields are optional: an older or fallback answer is a still drawing
    assert models.SvgOutput.model_validate({"svg": "<svg/>", "alt_zh": "x"}).motion == "none"
    prompt = runner.load_prompt("svg_system")
    for motion in dancing.MOTIONS:
        assert motion in prompt
