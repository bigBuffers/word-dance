"""images/memo.py — 记忆图卡 (docs/MEMORY_CARDS_DESIGN.md §3.1–§3.2): the recognition rule, the structure check the import gate runs
on a cleaned card (the layers and the spelling, the blur budget, a scene that stands on its own once the word layer is cut), the
string cut behind ``GET /media/images/{path}?plain=1``, and the promise that the file loads without the ``wd`` package (the studio's
validator imports it by path)."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from wd.images import memo, sanitize_svg

SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">'
DEFS = '<defs><filter id="soft"><feGaussianBlur stdDeviation="4"/></filter></defs>'
SCENE = '<g id="scene"><rect width="800" height="500" fill="#2F3F96"/><circle cx="168" cy="126" r="60" fill="#FFF5C4" filter="url(#soft)"/></g>'


def letters(word: str) -> str:
    """One ``<path id="wa-<index>-<char>">`` per letter or digit of ``word``, indexed by position (studio/tools/letters.py)."""
    return "".join(f'<path id="wa-{i}-{ch}" d="M{20 * i} 300H{20 * i + 12}V320Z" fill="#fff"/>' for i, ch in enumerate(word) if ch.isalnum())


def card(word: str = "moon", *, scene: str = SCENE, art: str | None = None, tail: str = "", viewbox: str = "0 0 800 500", defs: str = DEFS, title: str | None = None) -> str:
    """A small memory card in the sanitiser's canonical form (cleaned with effects, text-free) — the input check_structure is defined on."""
    art = f'<g id="word-art">{letters(word)}</g>' if art is None else art
    raw = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}"><title>{word if title is None else title}</title>{defs}{scene}{art}{tail}</svg>'
    return sanitize_svg.clean(raw, allow_text=False, effects=True)


# --------------------------------------------------------------------------------------------- is_memo
def test_is_memo_is_provider_claude_svg_and_a_memo_prompt_version():
    assert memo.PROMPT_PREFIX == "memo-"
    assert memo.is_memo({"provider": "claude_svg", "prompt_version": "memo-1"}) and memo.is_memo({"provider": "claude_svg", "prompt_version": "memo-12"})
    for row in (
        None,
        {},
        {"provider": "claude_svg"},  # a row read before 0012: no prompt_version column
        {"provider": "claude_svg", "prompt_version": None},  # the 30 drawings made before 0012
        {"provider": "claude_svg", "prompt_version": "svg-v2"},  # every online drawing
        {"provider": "claude_svg", "prompt_version": "Memo-1"},
        {"provider": "wikimedia", "prompt_version": "memo-1"},  # a photo is never a card, whatever its columns say
        {"provider": "claude_svg", "prompt_version": 1},
    ):
        assert memo.is_memo(row) is False, row
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    try:
        assert memo.is_memo(c.execute("SELECT 'claude_svg' AS provider, 'memo-1' AS prompt_version").fetchone()) is True
        assert memo.is_memo(c.execute("SELECT 'claude_svg' AS provider, 'svg-v2' AS prompt_version").fetchone()) is False
        assert memo.is_memo(c.execute("SELECT 'claude_svg' AS provider").fetchone()) is False  # sqlite3.Row without the column: IndexError inside
    finally:
        c.close()


# ------------------------------------------------------------------------------------- check_structure
def test_a_well_formed_card_has_no_problems(fixtures_dir):
    assert memo.check_structure(card("moon"), "moon") == []
    # the approved sample card, as cleaned by the studio and as stored (labelled): both pass for its word and fail for another
    approved = (fixtures_dir / "memo" / "moon.svg").read_text(encoding="utf-8")
    assert memo.check_structure(approved, "moon") == []
    labelled = sanitize_svg.with_label(approved, "AI-generated illustration · word-Dance · claude · 2026-11-13")
    assert memo.check_structure(labelled, "moon") == []
    assert len(memo.check_structure(approved, "noon")) == 1 and "spells 'moon'" in memo.check_structure(approved, "noon")[0]
    assert memo.MAX_BYTES == sanitize_svg.MAX_BYTES == 60_000 and memo.VIEWBOX == sanitize_svg.DEFAULT_VIEWBOX  # memo.py repeats them: it must load without the package


def test_headword_punctuation_and_case():
    """Spaces, hyphens, apostrophes and periods carry no letter path; the index gaps they leave are fine (the paths are read in
    index order); the case is the display form's."""
    for word in ("ice cream", "T-shirt", "o'clock", "a.m.", "China", "3D"):
        assert memo.check_structure(card(word), word) == [], word
    assert memo.spelled_letters("ice cream") == "icecream" and memo.spelled_letters("o'clock") == "oclock" and memo.spelled_letters("a.m.") == "am"
    assert memo.check_structure(card("ice cream"), "icecream") == []  # same letters, the gap at index 3 does not matter
    problems = memo.check_structure(card("china"), "China")
    assert len(problems) == 1 and "spells 'china'" in problems[0] and "expected 'China'" in problems[0]
    assert any("no letter or digit" in p for p in memo.check_structure(card("moon"), "…"))
    # the detached dot of an i / j shares the letter's index and does not count as a second letter
    dotted = card("rain", art='<g id="word-art">' + letters("rain") + '<path id="wa-2-i-dot" d="M40 280H48V288Z" fill="#fff"/></g>')
    assert memo.check_structure(dotted, "rain") == []


@pytest.mark.parametrize(
    "svg,needle",
    [
        pytest.param(card(viewbox="0 0 640 360"), 'viewBox is "0 0 640 360", must be "0 0 800 500"', id="viewbox"),
        pytest.param(card(scene='<g id="backdrop"><rect width="800" height="500"/></g>'), 'no <g id="scene"> as a direct child', id="no-scene"),
        pytest.param(card(scene=f"<g>{SCENE}</g>"), 'no <g id="scene"> as a direct child', id="scene-nested"),
        pytest.param(card(scene=SCENE + SCENE.replace("#2F3F96", "#000")), 'id "scene" appears 2 times', id="two-scenes"),
        pytest.param(card(art=""), "there is none among the root's children", id="no-word-art"),
        pytest.param(card(tail='<rect width="10" height="10"/>'), 'it is not the last one; the last child is <rect id="">', id="word-art-not-last"),
        pytest.param(card(art=f'<g><g id="word-art">{letters("moon")}</g></g>'), "there is none among the root's children", id="word-art-nested"),
        pytest.param(card(art=f'<g id="word-art">{letters("mon")}</g>'), "word-art spells 'mon' (wa-0-m, wa-1-o, wa-2-n), expected 'moon'", id="missing-letter"),
        pytest.param(card(art=f'<g id="word-art">{letters("moons")}</g>'), "word-art spells 'moons'", id="extra-letter"),
        pytest.param(card(art='<g id="word-art"><rect width="300" height="80" fill="#fff"/></g>'), "word-art spells '' (no wa-<index>-<char> path), expected 'moon'", id="no-letters"),
        pytest.param(card(art=f'<g id="word-art">{letters("moon").replace("wa-2-o", "wa-1-o")}</g>'), "letter index 1 appears twice (wa-1-o)", id="index-twice"),
        pytest.param(card(art=f'<g id="word-art">{letters("moon").replace("<path id=" + chr(34) + "wa-0-m", "<rect id=" + chr(34) + "wa-0-m")}</g>'), "wa-0-m: a word-art letter must be a <path>, not <rect>", id="letter-not-a-path"),
        pytest.param(card(scene=SCENE.replace("</g>", '<path id="wa-9-x" d="M0 0H8V8Z"/></g>')), 'wa-9-x: a word-art letter outside <g id="word-art">', id="letter-in-the-scene"),
        pytest.param(card(art=f'<g opacity="1" id="word-art">{letters("moon")}</g>'), "the word layer cannot be cut off for ?plain=1", id="id-not-first"),
    ],
)
def test_structure_problems_are_named(svg: str, needle: str):
    problems = memo.check_structure(svg, "moon")
    assert any(needle in p for p in problems), problems


def test_size_limit_and_unparsable_input():
    """The 60 KB limit is on the cleaned file (a labelled one included); what does not parse is one problem, never a traceback —
    and a DTD is refused, although the documented input (a clean() output) never has one."""
    big = card("moon", scene='<g id="scene">' + '<rect width="800" height="500" fill="#2F3F96"/>' * 1200 + "</g>")
    assert len(big.encode()) < memo.MAX_BYTES and memo.check_structure(big, "moon") == []
    over = big.replace("<title>moon</title>", "<title>" + "x" * (memo.MAX_BYTES - len(big.encode()) + len("moon") + 1) + "</title>")
    assert len(over.encode()) == memo.MAX_BYTES + 1
    assert memo.check_structure(over, "moon") == [f"the cleaned file is {memo.MAX_BYTES + 1} bytes, the limit is {memo.MAX_BYTES}"]
    assert len(memo.check_structure("<svg", "moon")) == 1 and memo.check_structure("<svg", "moon")[0].startswith("not well-formed XML")
    assert memo.check_structure("", "moon")[0].startswith("not well-formed XML")
    assert memo.check_structure("<html><body/></html>", "moon") == ["the root element is not <svg>"]
    bomb = '<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><desc>&a;</desc></svg>'
    assert len(memo.check_structure(bomb, "moon")) == 1 and memo.check_structure(bomb, "moon")[0].startswith("not well-formed XML")
    several = memo.check_structure(card(viewbox="0 0 100 100", scene="", art=f'<g id="word-art">{letters("mo")}</g>'), "moon")
    assert len(several) == 3  # every reason is reported, not only the first: viewBox, no scene, the spelling


# --------------------------------------------------------------------------------------- the blur budget
FULL = '<path d="M0 0H800V500H0Z" fill="#345" filter="url(#soft)"/>'  # one full-canvas shape under the blur of DEFS


def blurred(defs: str = DEFS, shapes: str = FULL) -> list[str]:
    """What the gate says about the card `moon` with these definitions and these shapes as its scene."""
    return memo.check_structure(card(defs=defs, scene=f'<g id="scene">{shapes}</g>'), "moon")


def test_blur_budget_counts_filtered_elements_and_primitives_per_filter():
    """Nothing in the sanitiser bounds what a filter costs to paint, so the gate does (docs/MEMORY_CARDS_DESIGN.md §8): at most
    MAX_FILTERED elements whose `filter` is not `none`, at most MAX_FILTER_PRIMITIVES feGaussianBlur / feDropShadow inside one
    <filter> — the number that matters: a chain of shadows can double the painting time with every link. The approved cards
    use 7 and 1."""
    assert (memo.MAX_FILTERED, memo.MAX_FILTER_PRIMITIVES, memo.MAX_STD_DEVIATION) == (16, 3, 60)
    assert blurred(shapes=FULL * 16) == []
    assert blurred(shapes=FULL * 17) == ["17 elements carry a filter, at most 16 may: put the shapes that share a blur into one filtered <g>"]
    # a filtered group is one element however many shapes it holds — the way the message says to draw it
    assert blurred(shapes='<g filter="url(#soft)">' + FULL.replace(' filter="url(#soft)"', "") * 40 + "</g>") == []
    assert blurred(shapes=FULL * 16 + '<rect width="1" height="1" filter="none"/>' * 40) == []  # `none` filters nothing
    # the word layer's filtered elements count like the scene's: 15 + the layer itself + one shape in it
    over = card(scene=f'<g id="scene">{FULL * 15}</g>', art=f'<g id="word-art" filter="url(#soft)"><circle cx="9" cy="9" r="9" filter="url(#soft)"/>{letters("moon")}</g>')
    assert memo.check_structure(over, "moon") == ["17 elements carry a filter, at most 16 may: put the shapes that share a blur into one filtered <g>"]
    for kind in ('<feGaussianBlur stdDeviation="4"/>', '<feDropShadow dx="1" dy="1" stdDeviation="4"/>'):
        assert blurred(f'<defs><filter id="soft">{kind * 3}</filter></defs>') == []
        assert blurred(f'<defs><filter id="soft">{kind * 4}</filter></defs>') == [
            '<filter id="soft"> chains 4 feGaussianBlur / feDropShadow primitives, at most 3 may: use one per filter (a chain of shadows can double the painting time with every link)'
        ]
    mixed = '<feGaussianBlur stdDeviation="4"/><feDropShadow dx="1" dy="1" stdDeviation="4"/>' * 2
    assert len(blurred(f'<defs><filter id="soft">{mixed}</filter></defs>')) == 1  # two of each are four
    # the limit is per filter: sixteen filters of three primitives each are sixteen separate, cheap chains
    many = "".join(f'<filter id="f{i}">{"<feGaussianBlur stdDeviation=" + chr(34) + "2" + chr(34) + "/>" * 3}</filter>' for i in range(16))
    assert blurred(f"<defs>{many}</defs>", "".join(FULL.replace("#soft", f"#f{i}") for i in range(16))) == []
    # a filter that nothing uses is judged too (it is one edit away from being used), a primitive outside a <filter> paints nothing and is not
    assert len(blurred(DEFS[:-7] + '<filter id="spare">' + '<feGaussianBlur stdDeviation="4"/>' * 5 + "</filter></defs>")) == 1
    assert blurred(shapes=FULL + '<g><feGaussianBlur stdDeviation="4"/></g>' * 9) == []


@pytest.mark.parametrize("value", ["60", "0", ".8", "1.6", "07", "3 4", "3,4", "3, 4", "3 , 4", "60 60", "0.50 12"])
def test_blur_budget_std_deviation_in_range(value: str):
    assert blurred(f'<defs><filter id="soft"><feGaussianBlur stdDeviation="{value}"/></filter></defs>') == []
    assert blurred(f'<defs><filter id="soft"><feDropShadow dx="0" dy="4" stdDeviation="{value}"/></filter></defs>') == []


@pytest.mark.parametrize("value", ["61", "250", "60.5", "60.01", "3 61", "61 3", "1e30 1e30", "1e1", "-1", "+4", "7.", "4px", "50%", "3 4 5", "3,,4", ",3", "", "abc", "0x10", "٣", "nan", "inf", "9" * 400])
def test_blur_budget_std_deviation_out_of_range_or_not_a_plain_number(value: str):
    """One or two plain numbers from 0 to MAX_STD_DEVIATION (the approved cards: .8–7): no sign, no exponent, no unit — `1e30`
    is a number to a browser, and the blur it asks for is the whole canvas many times over. Said once per value, however
    many primitives repeat it, and a value of any length is quoted by its first 40 characters."""
    shown = value if len(value) <= 40 else value[:40] + "…"
    for primitive in ("feGaussianBlur", "feDropShadow"):
        problems = blurred(f'<defs><filter id="soft"><{primitive} stdDeviation="{value}"/><{primitive} stdDeviation="{value}"/></filter></defs>')
        assert problems == [f'stdDeviation="{shown}" on <{primitive}>: write one or two plain numbers from 0 to 60 (no unit, no exponent) — the approved cards blur by .8 to 7'], value


WIDE = 'x="-1" y="-1" width="3" height="3"'  # a filter region of three times the shape's box: what the slow cards multiply their cost with
SLOW_CARDS = [  # painted through <img> at 800×500 by headless Chrome without GPU raster on the Mac that timed them (the approved moon: 0.8 s)
    pytest.param('<filter id="soft" x="-9" y="-9" width="99" height="99"><feGaussianBlur stdDeviation="250"/></filter>', FULL.replace(' fill="#345"', "") * 1000, id="1000-shapes-under-one-blur"),  # 37 s
    pytest.param(f'<filter id="soft" {WIDE}>' + '<feGaussianBlur stdDeviation="120"/>' * 1400 + "</filter>", FULL, id="1400-chained-blurs"),  # 51 s
    pytest.param('<filter id="soft">' + '<feDropShadow stdDeviation="9"/>' * 1100 + "</filter>", FULL, id="1100-chained-shadows"),  # no picture after 75 s
    pytest.param(f'<filter id="soft" {WIDE}>' + '<feDropShadow dx="3" dy="3" stdDeviation="60"/>' * 12 + "</filter>", FULL, id="12-chained-shadows-in-1-KB"),  # 41 s — and 3 of them, the limit: 0.7 s
]


@pytest.mark.parametrize("defs,shapes", SLOW_CARDS)
def test_blur_budget_refuses_the_slow_cards_of_the_review(defs: str, shapes: str):
    """The slow cards the code review of the feature built and timed: each is a clean() fixed point under the 60 KB limit with
    the two layers and the spelling in order — nothing but the budget turns it away."""
    svg = card(defs=f"<defs>{defs}</defs>", scene=f'<g id="scene">{shapes}</g>')
    assert sanitize_svg.clean(svg, allow_text=False, effects=True) == svg and len(svg.encode()) <= memo.MAX_BYTES
    problems = memo.check_structure(svg, "moon")
    assert problems and all("filter" in p or "stdDeviation" in p for p in problems), problems


# ------------------------------------------------------------------- the picture without the word layer
INNER_DEFS = (
    '<defs><linearGradient id="sky"><stop offset="0" stop-color="#123"/><stop offset="1" stop-color="#456"/></linearGradient>'
    '<clipPath id="cut"><circle cx="100" cy="100" r="40"/></clipPath><filter id="glow"><feGaussianBlur stdDeviation="3"/></filter></defs>'
)
USING_SCENE = '<g id="scene"><rect width="800" height="500" fill="url(#sky)"/><circle cx="100" cy="100" r="50" fill="#fff" clip-path="url(#cut)" filter="url(#glow)"/></g>'


def test_the_picture_without_the_word_layer_must_stand_on_its_own():
    """`?plain=1` cuts the file at the word layer, so a gradient / clip path / filter the scene uses may not be defined inside
    it: the full card paints (the studio's scene-only preview hid the layer with display="none" and painted too), the cut one
    shows a white background, an unclipped circle, no blur. The gate looks at the parsed tree, at exactly what the cut keeps."""
    svg = card(scene=USING_SCENE, art=f'<g id="word-art">{INNER_DEFS}{letters("moon")}</g>')
    plain = memo.strip_word_layer(svg)
    assert plain is not None and "url(#sky)" in plain and "url(#cut)" in plain and "url(#glow)" in plain and not any(f'id="{i}"' in plain for i in ("sky", "cut", "glow"))
    assert memo.check_structure(svg, "moon") == [
        'the picture without the word layer (?plain=1) uses #cut, #glow, #sky, defined inside <g id="word-art"> and cut away with it: move the definitions to the root <defs>'
    ]
    # the same definitions in the root <defs>: the card of the handbook
    assert memo.check_structure(card(defs=INNER_DEFS, scene=USING_SCENE), "moon") == []
    # the word layer may keep definitions of its own, and may use the root's (the letters' shadow lives in the root <defs> on every approved card)
    own = '<defs><linearGradient id="gold"><stop offset="0" stop-color="#fc0"/></linearGradient></defs><rect width="9" height="9" fill="url(#gold)" filter="url(#soft)"/>'
    assert memo.check_structure(card(art=f'<g id="word-art" filter="url(#soft)">{own}{letters("moon")}</g>'), "moon") == []
    # a reference the file defines nowhere is the other way for the scene to dangle — said in its own words
    nowhere = card(scene='<g id="scene"><rect width="800" height="500" fill="url(#nowhere)" stroke="url(#sky)"/></g>', art=f'<g id="word-art">{INNER_DEFS}{letters("moon")}</g>')
    assert memo.check_structure(nowhere, "moon") == [
        'the picture without the word layer (?plain=1) uses #sky, defined inside <g id="word-art"> and cut away with it: move the definition to the root <defs>',
        "the picture without the word layer uses #nowhere, which no element of the file defines: define it in the root <defs> or drop the reference",
    ]
    # every spelling of a reference the sanitiser keeps is read: quotes, spaces, a fallback colour after the paint
    for ref in ("url('#sky')", "url(&quot;#sky&quot;)", "url( #sky )", "url(#sky) #fff"):
        spelled = card(scene=f'<g id="scene"><rect width="800" height="500" fill="{ref}"/></g>', art=f'<g id="word-art">{INNER_DEFS}{letters("moon")}</g>')
        assert len(memo.check_structure(spelled, "moon")) == 1 and "uses #sky," in memo.check_structure(spelled, "moon")[0], ref
    # on the tree, not by a pattern over the text: what a <title> says is neither a definition nor a use
    told = card(title='id="sky" id="cut" id="glow"', scene=USING_SCENE, art=f'<g id="word-art">{INNER_DEFS}{letters("moon")}</g>')
    assert 'id="sky"' in memo.strip_word_layer(told) and len(memo.check_structure(told, "moon")) == 1
    assert memo.check_structure(card(title="fill=url(#gone) filter=url(#soft)"), "moon") == []
    # the stored file carries the AIGC label before everything else: its id is outside the layer and changes nothing
    labelled = sanitize_svg.with_label(svg, "AI-generated illustration · word-Dance · claude · 2026-11-13")
    assert len(memo.check_structure(labelled, "moon")) == 1 and "#cut, #glow, #sky" in memo.check_structure(labelled, "moon")[0]


def test_what_plain_serves_of_the_approved_card_is_self_contained(fixtures_dir):
    """The cut of the approved sample card: every url(#id) it keeps names an element it keeps (the root <defs> hold them all)."""
    cut = memo.strip_word_layer((fixtures_dir / "memo" / "moon.svg").read_text(encoding="utf-8"))
    root = ET.fromstring(cut)
    ids = {el.get("id") for el in root.iter()}
    used = {ref for el in root.iter() for value in el.attrib.values() for ref in memo.URL_REF_RE.findall(value)}
    assert used and used <= ids


# ------------------------------------------------------------------------------------ strip_word_layer
def test_strip_word_layer_cuts_the_last_group_and_nothing_else(fixtures_dir):
    svg = card("moon")
    plain = memo.strip_word_layer(svg)
    assert plain == f"{SVG_OPEN}<title>moon</title>{DEFS}{SCENE}</svg>"
    assert plain == svg[: svg.index('<g id="word-art"')] + "</svg>" and "wa-" not in plain
    assert sanitize_svg.clean(plain, allow_text=False, effects=True) == plain  # still a canonical, well-formed drawing
    assert memo.strip_word_layer(plain) is None  # nothing left to cut
    # nested groups inside the layer, attributes after the id, a self-closing layer, a trailing newline
    nested = card(art=f'<g id="word-art" filter="url(#soft)"><g opacity=".5"><g>{letters("mo")}</g></g><g>{letters("moon")[-80:]}</g><circle cx="1" cy="1" r="1"/></g>')
    assert memo.strip_word_layer(nested) == plain
    assert memo.strip_word_layer(f'{SVG_OPEN}{SCENE}<g id="word-art"/></svg>') == f"{SVG_OPEN}{SCENE}</svg>"
    assert memo.strip_word_layer(svg + "\n") == plain
    # the approved card: the scene stays byte for byte, the stored (labelled) file keeps its AIGC label
    approved = (fixtures_dir / "memo" / "moon.svg").read_text(encoding="utf-8")
    labelled = sanitize_svg.with_label(approved, "AI-generated illustration · word-Dance · claude · 2026-11-13")
    cut = memo.strip_word_layer(labelled)
    assert cut is not None and cut.startswith(SVG_OPEN + '<desc id="aigc-label">') and cut.endswith("</g></svg>") and "word-art" not in cut and "wa-" not in cut
    root = ET.fromstring(cut)
    assert [el.get("id") for el in root if el.tag.endswith("}g")] == ["scene"] and len(cut) < len(labelled) - 3000


@pytest.mark.parametrize(
    "svg",
    [
        pytest.param(f"{SVG_OPEN}{SCENE}</svg>", id="no-layer"),
        pytest.param(f'{SVG_OPEN}{SCENE}<g id="word-art"><path id="wa-0-a" d="M0 0Z"/></g><g id="word-art"><path id="wa-1-b" d="M0 0Z"/></g></svg>', id="two-layers"),
        pytest.param(f'{SVG_OPEN}{SCENE}<g id="word-art"><path id="wa-0-a" d="M0 0Z"/></g><rect width="1" height="1"/></svg>', id="sibling-after"),
        pytest.param(f'{SVG_OPEN}<g id="scene"><g id="word-art"><path id="wa-0-a" d="M0 0Z"/></g></g></svg>', id="nested-in-scene"),
        pytest.param(f'{SVG_OPEN}{SCENE}<g><g id="word-art"><path id="wa-0-a" d="M0 0Z"/></g></g></svg>', id="nested-in-group"),
        pytest.param(f'{SVG_OPEN}{SCENE}<g opacity="1" id="word-art"><path id="wa-0-a" d="M0 0Z"/></g></svg>', id="id-not-first"),
        pytest.param(f'{SVG_OPEN}{SCENE}<g id="word-art"><path id="wa-0-a" d="M0 0Z"/>', id="truncated"),
        pytest.param(f'{SVG_OPEN}{SCENE}<g id="word-art"><path id="wa-0-a" d="M0 0Z"/></g></svg><svg/>', id="trailing-garbage"),
        pytest.param("", id="empty"),
        pytest.param('<g id="word-art"', id="only-the-marker"),
    ],
)
def test_strip_word_layer_refuses_anything_but_the_canonical_shape(svg: str):
    """None = the route serves the file whole: no layer, two layers, a layer that is not the root's last child."""
    assert memo.strip_word_layer(svg) is None


# -------------------------------------------------------------------------------------- the studio contract
def test_memo_loads_by_path_without_the_wd_package(tmp_path: Path):
    """studio/tools/check.py loads backend/wd/images/memo.py by path next to sanitize_svg.py, in a virtualenv that has
    fonttools + defusedxml and no `wd` install: the module must not import from the package (docs/MEMORY_CARDS_DESIGN.md §3.8)."""
    source = Path(memo.__file__)
    text = source.read_text(encoding="utf-8")
    assert "from ." not in text and "import wd" not in text and "from wd" not in text
    spec = importlib.util.spec_from_file_location("studio_memo", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("PROMPT_PREFIX", "is_memo", "check_structure", "strip_word_layer", "MAX_FILTERED"):  # exactly these names: the studio's tools import them (check.py's blur warning quotes the limit)
        assert hasattr(module, name), name
    assert module.check_structure(card("moon"), "moon") == [] and module.strip_word_layer(card("moon")) == memo.strip_word_layer(card("moon"))
