"""The studio's tools (studio/tools/letters.py, check.py, build_gallery.py) and what is committed next to them.

Run with the studio's OWN virtualenv — fonttools lives only there, and the app's `make test` never comes here:

    studio/.venv/bin/python -m pytest -q -p no:cacheprovider studio/tests

What is pinned:

* letters.py lays a word out on its baseline (centred, left to right, chunk gaps, the split dot of i / j, punctuation that
  is not a letter) and the paths it prints pass check.py as they are;
* check.py accepts each approved card in studio/cards (with no warning left) and what it writes to clean/ is exactly what
  the import would store — the repository's sanitiser with ``effects=True`` and ``wd.images.memo.check_structure`` are run,
  not a copy; it refuses a misspelt word-art, a hand-edited glyph, a ``<text>`` element, letters out of order or too small,
  and whatever the sanitiser drops; it says so plainly when Chrome is missing, and stops without a verdict (exit 2) when
  the checkout's backend has no memory-card rules to apply;
* a glyph pasted unchanged is not yet a letter the pupil can copy — check.py also follows what the card DOES to it: a
  transform may move a letter, scale it uniformly and tip it a few degrees, and a mirrored, flipped, upside-down, squashed
  or skewed letter is refused; so is a letter nobody sees (paint, opacity, display and visibility are read through the
  groups around it) and a letter cut by the canvas edge (the ink box, not the centre); a ``style`` attribute never gets
  that far — the sanitiser drops it and check.py reports it among the dropped attributes; a path under the dot's id
  counts as the dot of i / j only when it is the font's dot in its place;
* a render that Chrome did not finish — the sheet or a zoom missing — is an error, never a quiet ``null``;
* studio/manifest.json and studio/cards/ name the same lemmas, with captions inside the import's limits;
* build_gallery.py turns the two into one page with every card inlined and no id used twice, whichever way a card spells
  its ``url(#id)`` references (the sheet of check.py renames ids with the same function);
* no file of the studio points at a directory outside the repository that will not be there tomorrow, and the handbooks
  name each other and every dependency of the tools.

The CLI is exercised as a subprocess of this interpreter (exit status + the JSON report are the contract an illustrator
relies on); the few in-process calls are the ones that need a monkeypatch.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
REPO = STUDIO.parent
TOOLS = STUDIO / "tools"
CARDS = STUDIO / "cards"
MANIFEST = json.loads((STUDIO / "manifest.json").read_text(encoding="utf-8"))
LEMMAS = list(MANIFEST["cards"])

pytest.importorskip("fontTools", reason="the studio's tools run under studio/.venv (studio/requirements.txt), not the app's .venv")
sys.path.insert(0, str(TOOLS))
import check  # noqa: E402
import letters  # noqa: E402

FONT = letters.load_font(letters.DEFAULT_FONT)
SCENE = '<g id="scene"><rect width="800" height="500" fill="#CFE3F5"/></g>'


def lay(word: str, **kw) -> dict:
    args = {"size": 150.0, "x": 400.0, "baseline": 330.0, "anchor": "middle", "track": 0.0, "chunks": None, "gap": 0.0, "split_dots": False, "prefix": "wa"}
    return letters.layout(FONT, word, **{**args, **kw})


def card(word_art: str, scene: str = SCENE, tail: str = "") -> str:
    """The smallest file that is a memory card: a scene group, then the word layer as the root's last child."""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><title>test</title>{scene}{word_art}{tail}</svg>'


def run_check(svg: Path, out: Path, *args: str) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, str(TOOLS / "check.py"), str(svg), "--out-dir", str(out), *args], capture_output=True, text=True)
    assert p.stdout.strip(), p.stderr
    return p.returncode, json.loads(p.stdout)


def check_text(tmp_path: Path, svg: str, word: str, name: str = "card") -> tuple[int, dict]:
    src = tmp_path / "cards" / f"{name}.svg"
    src.parent.mkdir(exist_ok=True)
    src.write_text(svg, encoding="utf-8")
    return run_check(src, tmp_path, "--word", word, "--no-render")


def card_path(lemma: str) -> Path:
    return CARDS / f"{lemma.replace(' ', '_')}.svg"  # the import's naming rule: a space of the lemma is `_` in the file name


def approved(lemma: str) -> str:
    return card_path(lemma).read_text(encoding="utf-8")


def headword(lemma: str) -> str:
    """The display form an approved card was drawn for. The manifest is keyed by lemma (lower-case) while the picture
    carries the word as the app displays it (`Monday`, `T-shirt`) — the form `check --word` and the import's structure
    check want. The card's own letter ids give the case back; the letters themselves stay pinned to the lemma."""
    drawn = iter(ch for _, ch in sorted((int(i), ch) for i, ch in re.findall(r'id="wa-(\d+)-(\w)"', approved(lemma))))
    word = "".join(next(drawn, ch) if ch.isalnum() else ch for ch in lemma)
    assert word.lower() == lemma and next(drawn, None) is None, f"{card_path(lemma).name} does not spell its lemma {lemma!r}"
    return word


def sub_once(pattern: str, repl, text: str) -> str:
    out, n = re.subn(pattern, repl, text)
    assert n == 1, (pattern, n)
    return out


def with_attrs(snippet: str, path_id: str, attrs: str) -> str:
    """``snippet`` with ``attrs`` written on the one path that has this id."""
    return sub_once(f'<path id="{path_id}"', f'<path id="{path_id}" {attrs}', snippet)


def grouped(snippet: str, attrs: str) -> str:
    """The whole word of ``snippet`` inside one more ``<g …>`` under the word layer (the way a chunk carries its paint)."""
    assert snippet.count("</g>") == 1
    return snippet.replace('<g id="word-art">', f'<g id="word-art"><g {attrs}>').replace("</g>", "</g></g>")


def about(letter: dict, transform: str) -> str:
    """``transform`` applied about the centre of a letter, so that the letter stays where letters.py put it."""
    return f"translate({letter['cx']} {letter['cy']}) {transform} translate({-letter['cx']} {-letter['cy']})"


def verdict(tmp_path: Path, name: str, word_art: str, word: str) -> tuple[int, list[str], list[str]]:
    code, report = check_text(tmp_path, card(word_art), word, name=name)
    return code, report["errors"], report["warnings"]


# ---------------------------------------------------------------- letters.py
def test_letters_lays_a_word_out_centred_on_its_baseline():
    out = lay("moon")
    ls = out["letters"]
    assert [L["id"] for L in ls] == ["wa-0-m", "wa-1-o", "wa-2-o", "wa-3-n"] and [L["ch"] for L in ls] == list("moon")
    assert out["advance_box"][0] + out["advance_box"][1] == pytest.approx(800.0, abs=0.2)  # centred on x = 400
    assert [L["cx"] for L in ls] == sorted(L["cx"] for L in ls)  # left to right
    assert all(L["x0"] < L["cx"] < L["x1"] for L in ls)
    assert all(L["bbox"][3] == pytest.approx(330.0, abs=3.0) for L in ls)  # every letter of `moon` sits on the baseline
    assert out["x_height_y"] < 330.0 < out["descender_y"] and out["ascender_y"] < out["cap_height_y"] < out["x_height_y"]
    assert [sum(c["hole"] for c in L["contours"]) for L in ls] == [0, 1, 1, 0]  # the counters of the two o
    assert all(L["d"].startswith("M") and L["d"].endswith("Z") for L in ls)
    assert out["snippet"].count("<path ") == 4 and out["snippet"].startswith('<g id="word-art">')
    twice = lay("moon", size=300.0)  # the outline scales with the size and nothing else
    assert twice["letters"][1]["bbox"][2] - twice["letters"][1]["bbox"][0] == pytest.approx(2 * (ls[1]["bbox"][2] - ls[1]["bbox"][0]), abs=0.3)


def test_letters_chunks_open_a_gap_and_must_spell_the_word():
    plain = lay("breakfast", size=96.0)
    chunked = lay("breakfast", size=96.0, chunks=["break", "fast"], gap=24.0, anchor="start", x=40.0)
    assert [L["chunk"] for L in chunked["letters"]] == [0] * 5 + [1] * 4 and chunked["chunks"] == ["break", "fast"]
    k, f = chunked["letters"][4], chunked["letters"][5]
    assert f["x0"] - k["x1"] == pytest.approx(24.0, abs=0.2)  # the chunk gap, on top of the font's own advances
    assert chunked["advance_box"][0] == 40.0
    assert (chunked["advance_box"][1] - chunked["advance_box"][0]) - (plain["advance_box"][1] - plain["advance_box"][0]) == pytest.approx(24.0, abs=0.2)
    with pytest.raises(SystemExit, match="does not spell"):
        lay("breakfast", chunks=["brek", "fast"])


def test_letters_split_dot_and_ids_of_what_is_not_a_letter():
    whole = lay("rain")["letters"][2]
    split = lay("rain", split_dots=True)["letters"][2]
    assert "dot" not in whole and split["dot"]["id"] == "wa-2-i-dot"
    assert split["dot"]["bbox"][3] < split["bbox"][1] + (split["bbox"][3] - split["bbox"][1]) / 2  # the dot is the top contour
    assert whole["d"] != split["d"] and whole["d"].count("Z") == split["d"].count("Z") + split["dot"]["d"].count("Z")
    # the import spells the headword from the wa-<index>-<char> ids (letters and digits only): an apostrophe, a hyphen or a
    # space must not look like one — and the index stays the position in the word as typed
    assert [L["id"] for L in lay("o'clock")["letters"]] == ["wa-0-o", "wap-1", "wa-2-c", "wa-3-l", "wa-4-o", "wa-5-c", "wa-6-k"]
    assert [L["id"] for L in lay("T-shirt")["letters"]][:3] == ["wa-0-T", "wap-1", "wa-2-s"]
    assert [L["id"] for L in lay("ice cream", size=90.0)["letters"]] == ["wa-0-i", "wa-1-c", "wa-2-e", "wa-4-c", "wa-5-r", "wa-6-e", "wa-7-a", "wa-8-m"]
    with pytest.raises(SystemExit, match="no glyph"):
        lay("月")


@pytest.mark.parametrize(
    ("word", "kw"),
    [
        ("moon", {}),
        ("breakfast", {"size": 100.0, "chunks": ["break", "fast"], "gap": 12.0}),
        ("rain", {"split_dots": True}),
        ("o'clock", {"size": 120.0}),
        ("T-shirt", {"size": 120.0}),
        ("ice cream", {"size": 90.0}),
    ],
)
def test_letters_paths_validate_as_pasted(tmp_path, word, kw):
    out = lay(word, **kw)
    code, report = check_text(tmp_path, card(out["snippet"]), word)
    assert (code, report["ok"], report["errors"], report["warnings"]) == (0, True, [], [])
    assert report["word_art"]["letter_em_px"] == [pytest.approx(out["size"], abs=0.5)] * sum(ch.isalnum() for ch in word)
    assert [c[1] for c in report["word_art"]["letter_centres"]] == [ch for ch in word if ch.isalnum()]


def test_letters_wrapper_runs_from_any_directory(tmp_path):
    if not (STUDIO / ".venv" / "bin" / "python").exists():
        pytest.skip("studio/.venv is not where the wrappers expect it")
    p = subprocess.run([str(TOOLS / "letters"), "moon", "--brief"], capture_output=True, text=True, cwd=tmp_path)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert [L["id"] for L in out["letters"]] == ["wa-0-m", "wa-1-o", "wa-2-o", "wa-3-n"]
    assert "snippet" not in out and all("d" not in L for L in out["letters"])  # --brief: metrics only


# ---------------------------------------------------------------- the committed cards and their manifest
def test_manifest_and_cards_name_the_same_lemmas_within_the_import_limits():
    assert MANIFEST["prompt_version"] == "memo-1" and MANIFEST["model"]
    assert sorted(p.stem for p in CARDS.glob("*.svg")) == sorted(lemma.replace(" ", "_") for lemma in LEMMAS)
    for lemma, cap in MANIFEST["cards"].items():
        assert set(cap) == {"alt_zh", "hook_zh", "note_zh"}, lemma
        assert 0 < len(cap["alt_zh"]) <= 200 and 0 < len(cap["hook_zh"]) <= 60 and len(cap["note_zh"]) <= 60, lemma  # MEMORY_CARDS_DESIGN §3.4


# Cards that carry a warning ON PURPOSE — their art direction asks for exactly what the checker points at. Each is pinned by
# the start of its message, so a new warning on these cards, or any warning on another card, still fails.
EXPECTED_WARNINGS = {
    "physical education": ["smallest word-art letter is 72 px em"],  # eighteen letters on one line: STUDIO §3 allows 64 px for long words
    "child": ["wa-2-i: dotless glyph"],  # the hook: the dot of the i is the ball the child has thrown (a drawn object, checked in the render)
}


@pytest.mark.parametrize("lemma", LEMMAS)
def test_check_accepts_each_approved_card(tmp_path, lemma):
    word = headword(lemma)
    expected = EXPECTED_WARNINGS.get(lemma, [])
    code, report = run_check(card_path(lemma), tmp_path, "--word", word, "--no-render")
    assert (code, report["ok"], report["errors"]) == (0, True, [])
    assert len(report["warnings"]) == len(expected) and all(w.startswith(e) for w, e in zip(report["warnings"], expected)), report["warnings"]
    assert report["clean_bytes"] <= check.TARGET_BYTES and report["blurred_elements"] <= check.MAX_BLURRED
    assert min(report["word_art"]["letter_em_px"]) >= (check.MIN_FONT_PX if any("px em" in e for e in expected) else check.WARN_FONT_PX)
    assert "".join(c[1] for c in report["word_art"]["letter_centres"]) == "".join(ch for ch in word if ch.isalnum())
    # what the tool wrote is what the import stores: the repository's sanitiser in the memory-card mode, accepted by the
    # repository's structure check, and the word layer comes off cleanly (the picture `?plain=1` serves)
    san, memo = check.load_backend()
    cleaned = (tmp_path / "clean" / card_path(lemma).name).read_text(encoding="utf-8")
    assert cleaned == san.clean(approved(lemma), allow_text=False, effects=True) == san.clean(cleaned, allow_text=False, effects=True)
    assert memo.check_structure(cleaned, word) == []
    plain = memo.strip_word_layer(cleaned)
    assert plain is not None and not re.search(r'id="wa-\d', plain) and '<g id="scene"' in plain and plain.endswith("</svg>") and "<text" not in cleaned


# ---------------------------------------------------------------- check.py refuses …
def test_check_rejects_a_misspelt_word_art(tmp_path):
    # a real card with one of its twin letters lost: h-a-p-y
    svg = sub_once(r'<path id="wa-3-p"[^>]*/>', "", approved("happy"))
    code, report = check_text(tmp_path, svg, "happy")
    assert code == 1 and report["ok"] is False
    assert any("spells 'hapy'" in e and "'happy'" in e for e in report["errors"]), report["errors"]
    # and a fresh one: the right glyphs for the wrong word
    code, report = check_text(tmp_path, card(lay("mon")["snippet"]), "moon", name="mon")
    assert code == 1 and any("spells 'mon'" in e for e in report["errors"]), report["errors"]
    # the same letter index twice is not a spelling either
    twice = lay("moon")["snippet"].replace('id="wa-2-o"', 'id="wa-1-o"')
    code, report = check_text(tmp_path, card(twice), "moon", name="twice")
    assert code == 1 and any("index 1 appears twice" in e for e in report["errors"]), report["errors"]


def test_check_rejects_a_hand_edited_glyph(tmp_path):
    # one point of the first o of `moon` pulled 12 px to the right — the kind of "small correction" an illustrator makes
    svg = sub_once(r'(<path id="wa-1-o"[^>]*? d="M)([-\d.]+)', lambda m: f"{m.group(1)}{float(m.group(2)) + 12:.1f}", approved("moon"))
    code, report = check_text(tmp_path, svg, "moon")
    assert code == 1
    assert [e for e in report["errors"] if e.startswith("wa-1-o: the path data is not the glyph")] and len(report["errors"]) == 1, report["errors"]
    # another letter's outline under the right id is no better
    out = lay("moon")
    swapped = out["snippet"].replace(out["letters"][1]["d"], lay("a", x=out["letters"][1]["cx"])["letters"][0]["d"])
    code, report = check_text(tmp_path, card(swapped), "moon", name="swapped")
    assert code == 1 and any(e.startswith("wa-1-o: the path data is not the glyph") for e in report["errors"]), report["errors"]
    # moving or scaling a letter with a transform is the allowed way: still the glyph, and the size is measured through it
    moved = out["snippet"].replace('<path id="wa-3-n"', '<path id="wa-3-n" transform="translate(6 -4)"')
    code, report = check_text(tmp_path, card(moved), "moon", name="moved")
    assert (code, report["errors"]) == (0, [])
    # … but a transform is no way round the font: with every `d` still the pasted glyph, the b and the d of `bed` mirrored
    # about their own centres read `deb` (the centres do not move, so the reading order has nothing to say) …
    bed = lay("bed")
    mirrored = bed["snippet"]
    for L in (bed["letters"][0], bed["letters"][2]):
        mirrored = with_attrs(mirrored, L["id"], f'transform="translate({2 * L["cx"]} 0) scale(-1 1)"')
    code, errors, _ = verdict(tmp_path, "mirrored", mirrored, "bed")
    assert code == 1 and [e[:16] for e in errors] == ["wa-0-b: mirrored", "wa-2-d: mirrored"], errors
    # … and a word squashed to 40 % of its height is no letterform to copy, whatever sqrt(|det|) says about its size (95 px)
    code, report = check_text(tmp_path, card(grouped(bed["snippet"], 'transform="translate(0 198) scale(1 .4)"')), "bed", name="squashed")
    assert code == 1 and [e.split(" by the transform")[0] for e in report["errors"]] == [f"wa-{i}-{ch}: stretched, squashed or skewed" for i, ch in enumerate("bed")], report["errors"]
    assert min(report["word_art"]["letter_em_px"]) > check.WARN_FONT_PX  # the size floor alone would have let it through


def test_check_a_transform_may_move_scale_and_tip_a_letter_never_distort_it(tmp_path):
    out = lay("bed")
    snippet, (b, e, d) = out["snippet"], out["letters"]
    # silently allowed: a move, ONE scale factor (written either way), and a tip of a few degrees — the pilot recipe tips
    # each chunk ∓2.5° about its centre, a hook may lean one letter a little
    allowed = {
        "moved": "translate(6 -4)",
        "bigger": about(e, "scale(1.1)"),
        "smaller-matrix": f"matrix(.9 0 0 .9 {e['cx'] * 0.1:.1f} {e['cy'] * 0.1:.1f})",
        "tipped": f"rotate(-2.5 {e['cx']} {e['cy']})",
        "leaning": f"rotate(5 {e['cx']} {e['cy']})",
        "leaning-matrix": f"matrix(.9962 .0872 -.0872 .9962 {e['cx'] - (0.9962 * e['cx'] - 0.0872 * e['cy']):.2f} {e['cy'] - (0.0872 * e['cx'] + 0.9962 * e['cy']):.2f})",  # the same 5°, as four rounded numbers (5.003°)
    }
    for name, transform in allowed.items():
        assert verdict(tmp_path, name, with_attrs(snippet, e["id"], f'transform="{transform}"'), "bed") == (0, [], []), name
    assert verdict(tmp_path, "chunk", grouped(snippet, f'transform="rotate(2.5 {e["cx"]} {e["cy"]})"'), "bed") == (0, [], [])
    # a tilt anybody can see is the illustrator's call (the handbook wants upright letters, a hook may want a lean): a warning
    code, errors, warnings = verdict(tmp_path, "tilted", with_attrs(snippet, e["id"], f'transform="rotate(-10 {e["cx"]} {e["cy"]})"'), "bed")
    assert (code, errors) == (0, []) and len(warnings) == 1 and warnings[0].startswith("wa-1-e: tilted -10°"), warnings
    # refused: whatever leaves the pupil another letter, or no letter — each on the e alone, the b and the d stay clean
    refused = {
        "mirror-matrix": (f"matrix(-1 0 0 1 {2 * e['cx']} 0)", "wa-1-e: mirrored"),
        "flipped": (f"translate(0 {2 * e['cy']}) scale(1 -1)", "wa-1-e: mirrored"),
        "upside-down": (f"rotate(180 {e['cx']} {e['cy']})", "wa-1-e: turned 180°"),
        "lying": (f"rotate(-90 {e['cx']} {e['cy']})", "wa-1-e: turned -90°"),
        "falling": (f"rotate(25 {e['cx']} {e['cy']})", "wa-1-e: turned 25°"),
        "condensed": (about(e, "scale(.72 1)"), "wa-1-e: stretched, squashed or skewed"),
        "tall": (about(e, "scale(1 1.3)"), "wa-1-e: stretched, squashed or skewed"),
        "slanted": (about(e, "skewX(-12)"), "wa-1-e: stretched, squashed or skewed"),
        "sheared": (about(e, "skewY(8)"), "wa-1-e: stretched, squashed or skewed"),
    }
    for name, (transform, said) in refused.items():
        code, errors, warnings = verdict(tmp_path, name, with_attrs(snippet, e["id"], f'transform="{transform}"'), "bed")
        assert code == 1 and len(errors) == 1 and errors[0].startswith(said) and warnings == [], (name, errors, warnings)
    # the transform that counts is the composed one: a group flips the word, the n of `sun` turned on its head reads `suu`
    code, errors, _ = verdict(tmp_path, "group-mirror", grouped(snippet, "transform=\"translate(800 0) scale(-1 1)\""), "bed")
    assert code == 1 and [x[:16] for x in errors[:3]] == ["wa-0-b: mirrored", "wa-1-e: mirrored", "wa-2-d: mirrored"], errors
    sun = lay("sun")
    n = sun["letters"][2]
    code, errors, _ = verdict(tmp_path, "suu", with_attrs(sun["snippet"], n["id"], f'transform="rotate(180 {n["cx"]} {n["cy"]})"'), "sun")
    assert code == 1 and len(errors) == 1 and errors[0].startswith("wa-2-n: turned 180°"), errors
    # a long word condensed to fit the 720 px zone: every letter is told, and the remedy is another --size
    wide = lay("grandmother", size=120.0)
    code, errors, _ = verdict(tmp_path, "condensed-word", grouped(wide["snippet"], 'transform="translate(400 0) scale(.72 1) translate(-400 0)"'), "grandmother")
    assert code == 1 and len(errors) == 11 and all("stretched, squashed or skewed" in x and "--size" in x for x in errors), errors
    # CSS would reach a letter where no presentation attribute shows it — and a card carries none: the sanitiser's memory-card
    # mode drops EVERY `style` attribute (not only one with url(): backend/wd/images/sanitize_svg.py), so the same mirror
    # written as a style, on the letter or on a group around it, is refused one step earlier — as an attribute the app would
    # not serve — and never reaches the stored card
    code, errors, _ = verdict(tmp_path, "css", with_attrs(snippet, b["id"], f'style="transform: translate({2 * b["cx"]}px, 0) scale(-1, 1)"'), "bed")
    assert code == 1 and len(errors) == 1 and errors[0].startswith("the sanitiser DROPPED these attributes: {'style': 1}"), errors
    code, errors, _ = verdict(tmp_path, "css-group", grouped(snippet, 'style="opacity:0"'), "bed")
    assert code == 1 and len(errors) == 1 and errors[0].startswith("the sanitiser DROPPED these attributes: {'style': 1}"), errors  # said once, not per letter
    assert all("style" not in (tmp_path / "clean" / f"{name}.svg").read_text(encoding="utf-8") for name in ("css", "css-group"))


def test_check_reads_a_letters_paint_through_the_groups_around_it(tmp_path):
    out = lay("bed")
    snippet, (b, e, d) = out["snippet"], out["letters"]
    # drawn — the ghost letter of the pilot recipe: the chunk's <g> carries the dashed keyline, the letter itself only says `fill="none"`
    ghost = snippet.replace(f'  <path id="{e["id"]}" d="{e["d"]}"/>', f'  <g stroke="#E8503A" stroke-width="3.5" stroke-dasharray="7 6"><path id="{e["id"]}" fill="none" d="{e["d"]}"/></g>')
    drawn = {
        "ghost-group-stroke": ghost,
        "ghost-house": with_attrs(snippet, e["id"], 'fill="#149082" fill-opacity=".4" stroke="#0B6B66" stroke-width="3.2" stroke-dasharray="7 6"'),
        "outline-only": with_attrs(snippet, e["id"], 'fill="none" stroke="#27307C" stroke-width="4"'),
        "no-keyline": with_attrs(snippet, e["id"], 'stroke="none"'),  # the default fill is black: still a letter
        "pale-group": grouped(snippet, 'fill="#149082" fill-opacity=".35" opacity=".9"'),
        "shown-again": grouped(snippet, 'visibility="hidden"').replace("<path ", '<path visibility="visible" '),
        "refilled": grouped(snippet, 'fill="none"').replace("<path ", '<path fill="#E8503A" '),
    }
    for name, art in drawn.items():
        assert verdict(tmp_path, name, art, "bed") == (0, [], []), name
    # not drawn — one error for the letter nobody sees, the other two stay clean
    hidden = {
        "no-paint": ('fill="none" stroke="none"', "no fill, no stroke"),
        "transparent": ('fill="transparent"', "no fill, no stroke"),
        "zero-width": ('fill="none" stroke="#27307C" stroke-width="0"', "no fill, no stroke"),
        "fill-opacity": ('fill-opacity="0"', "no fill, no stroke"),
        "stroke-opacity": ('fill="none" stroke="#27307C" stroke-opacity="0"', "no fill, no stroke"),
        "opacity": ('opacity="0"', 'opacity="0"'),
        "display": ('display="none"', 'display="none"'),
        "visibility": ('visibility="hidden"', 'visibility="hidden"'),
    }
    for name, (attrs, why) in hidden.items():
        code, errors, _ = verdict(tmp_path, name, with_attrs(snippet, e["id"], attrs), "bed")
        assert code == 1 and len(errors) == 1 and errors[0].startswith(f"wa-1-e: invisible letter ({why}"), (name, errors)
    # … and what a group takes away, every letter under it has lost — the word layer itself included
    for name, art in {
        "group-fill": grouped(snippet, 'fill="none"'),
        "group-display": grouped(snippet, 'display="none"'),
        "group-hidden": grouped(snippet, 'visibility="hidden"'),
        "layer-opacity": snippet.replace('<g id="word-art">', '<g id="word-art" opacity="0">'),
    }.items():
        code, errors, _ = verdict(tmp_path, name, art, "bed")
        assert code == 1 and [x[:24] for x in errors] == [f"wa-{i}-{ch}: invisible letter" for i, ch in enumerate("bed")], (name, errors)
    # a letter filed under <defs> (or serving as a clip path) carries the id but is not what the card paints
    for name, tag in {"in-defs": "defs", "as-clip": 'clipPath id="cut"'}.items():
        art = snippet.replace(f'  <path id="{e["id"]}" d="{e["d"]}"/>', f'  <{tag}><path id="{e["id"]}" d="{e["d"]}"/></{tag.split()[0]}>')
        code, errors, _ = verdict(tmp_path, name, art, "bed")
        assert code == 1 and len(errors) == 1 and errors[0].startswith(f"wa-1-e: invisible letter (inside <{tag.split()[0]}>"), (name, errors)


def test_check_measures_the_canvas_edge_on_the_ink_of_the_letters(tmp_path):
    # `moon` at 180 px pushed into the top-left corner: every letter's centre is inside the old 20 px test, while the m has
    # lost 28 px on the left and the whole word 21 px at the top
    cut = lay("moon", size=180.0, anchor="start", x=-38.0, baseline=70.0)
    assert cut["ink_bbox"][0] < -25 and cut["ink_bbox"][1] < -20 and all(L["cx"] > 20 and L["cy"] > 20 for L in cut["letters"])
    code, report = check_text(tmp_path, card(cut["snippet"]), "moon", name="cut")
    assert code == 1 and len(report["errors"]) == 1 and report["warnings"] == [], report
    assert report["errors"][0].startswith("word-art letters cut by the canvas edge: wa-0-m, wa-1-o, wa-2-o, wa-3-n "), report["errors"]
    assert report["word_art"]["ink_bbox"] == [pytest.approx(v, abs=0.2) for v in cut["ink_bbox"]]  # the word's ink box, through every transform
    # one letter over the right edge is named alone; a word carried off the canvas altogether is no warning either
    over = lay("moon", anchor="end", x=830.0)
    code, errors, warnings = verdict(tmp_path, "over", over["snippet"], "moon")
    assert code == 1 and len(errors) == 1 and errors[0].startswith("word-art letters cut by the canvas edge: wa-3-n ") and warnings == [], errors
    code, errors, warnings = verdict(tmp_path, "gone", grouped(lay("moon")["snippet"], 'transform="translate(0 900)"'), "moon")
    assert code == 1 and len(errors) == 1 and errors[0].startswith("word-art letters cut by the canvas edge: wa-0-m, wa-1-o, wa-2-o, wa-3-n "), errors
    # inside the canvas but closer than 20 px to an edge: a warning; the approved cards come as close as 29.8 px and stay silent
    lsb = lay("moon", anchor="start", x=0.0)["ink_bbox"][0]
    code, errors, warnings = verdict(tmp_path, "near", lay("moon", anchor="start", x=12.0 - lsb)["snippet"], "moon")
    assert (code, errors) == (0, []) and len(warnings) == 1 and warnings[0].startswith("word-art letters within 20 px of the canvas edge: wa-0-m "), warnings
    assert verdict(tmp_path, "clear", lay("moon", anchor="start", x=24.0 - lsb)["snippet"], "moon") == (0, [], [])
    # the detached dot of an i is ink of its letter: `rain` with only that dot over the top edge
    rain = lay("rain", split_dots=True, baseline=0.0)
    top = rain["letters"][2]["dot"]["bbox"][1]
    rain = lay("rain", split_dots=True, baseline=-top - 6.0)
    assert rain["letters"][2]["dot"]["bbox"][1] == pytest.approx(-6.0, abs=0.2) and all(L["bbox"][1] > 0 for L in rain["letters"] if L["ch"] != "i")
    code, errors, _ = verdict(tmp_path, "dot-cut", rain["snippet"], "rain")
    assert code == 1 and len(errors) == 1 and errors[0].startswith("word-art letters cut by the canvas edge: wa-2-i "), errors


def test_check_rejects_a_text_element(tmp_path):
    svg = sub_once(r'<g id="scene">', '<g id="scene"><text x="40" y="60" font-size="40">moon</text>', approved("moon"))
    code, report = check_text(tmp_path, svg, "moon")
    assert code == 1 and report["ok"] is False
    assert any("DROPPED these elements" in e and "'text': 1" in e for e in report["errors"]), report["errors"]
    assert "<text" not in (tmp_path / "clean" / "card.svg").read_text(encoding="utf-8")  # and the app would never serve it
    # a word typed as text instead of drawn as glyph paths is a card without a word
    typed = card('<g id="word-art"><text x="400" y="330" font-size="150" text-anchor="middle">moon</text></g>')
    code, report = check_text(tmp_path, typed, "moon", name="typed")
    assert code == 1 and any("spells ''" in e for e in report["errors"]), report["errors"]


def test_check_rejects_letters_out_of_order_too_small_or_invisible(tmp_path):
    # `on` drawn as n-o with the ids exchanged: the spelling is right, the reading order is not
    out = lay("no")
    crossed = out["snippet"].replace('id="wa-0-n"', 'id="wa-1-n"').replace('id="wa-1-o"', 'id="wa-0-o"')
    code, report = check_text(tmp_path, card(crossed), "on", name="crossed")
    assert code == 1 and [e for e in report["errors"] if "left-to-right reading order" in e] and len(report["errors"]) == 1, report["errors"]
    # 150 px letters inside a group scaled to 40 %: 60 px on the canvas, below the 64 px floor
    small = lay("moon")["snippet"].replace('<g id="word-art">', '<g id="word-art"><g transform="translate(240 200) scale(.4)">').replace("</g>", "</g></g>")
    code, report = check_text(tmp_path, card(small), "moon", name="small")
    assert code == 1 and any("60 px em" in e and "minimum" in e for e in report["errors"]), report["errors"]
    assert report["word_art"]["letter_em_px"] == [pytest.approx(60.0, abs=0.3)] * 4
    # between the floor and the preferred size it is a warning, not an error
    code, report = check_text(tmp_path, card(lay("moon", size=70.0)["snippet"]), "moon", name="modest")
    assert code == 0 and any("70 px em" in w for w in report["warnings"]), report
    ghost = lay("moon")["snippet"].replace('<path id="wa-0-m"', '<path id="wa-0-m" fill="none"')
    code, report = check_text(tmp_path, card(ghost), "moon", name="ghost")
    assert code == 1 and any("wa-0-m: invisible letter" in e for e in report["errors"]), report["errors"]


def test_check_reports_structure_faults_in_the_imports_words(tmp_path):
    art = lay("moon")["snippet"]
    code, report = check_text(tmp_path, card(art, tail='<rect width="10" height="10"/>'), "moon", name="tail")
    assert code == 1 and any("must be the LAST child" in e for e in report["errors"]), report["errors"]
    code, report = check_text(tmp_path, card(art, scene='<g id="backdrop"><rect width="800" height="500"/></g>'), "moon", name="noscene")
    assert code == 1 and any('no <g id="scene">' in e for e in report["errors"]), report["errors"]
    code, report = check_text(tmp_path, card(art).replace('viewBox="0 0 800 500"', 'viewBox="0 0 1600 1000"'), "moon", name="viewbox")
    assert code == 1 and any('must be "0 0 800 500"' in e for e in report["errors"]), report["errors"]
    san, memo = check.load_backend()  # the sentences are memo.check_structure's own, passed through — no copy of the rules is kept in the studio
    said = memo.check_structure(san.clean(card(art).replace('viewBox="0 0 800 500"', 'viewBox="0 0 1600 1000"'), allow_text=False, effects=True), "moon")
    assert said and set(said) <= set(report["errors"])
    # the scene's sky gradient defined inside the word layer: every id resolves and the full card paints, so nothing of the
    # studio's own notices it — the sheet's scene-only panel merely hides the layer — but `?plain=1` cuts the definition away.
    # The gate's sentence is the one error, exactly as `wd images-import` would print it
    sky = '<defs><linearGradient id="sky"><stop offset="0" stop-color="#CFE3F5"/></linearGradient></defs>'
    cut = card(art.replace('<g id="word-art">', f'<g id="word-art">{sky}', 1), scene='<g id="scene"><rect width="800" height="500" fill="url(#sky)"/></g>')
    code, report = check_text(tmp_path, cut, "moon", name="cut")
    assert code == 1 and report["errors"] == memo.check_structure(san.clean(cut, allow_text=False, effects=True), "moon"), report["errors"]
    assert len(report["errors"]) == 1 and report["errors"][0].startswith('the picture without the word layer (?plain=1) uses #sky, defined inside <g id="word-art"> and cut away with it')
    code, report = check_text(tmp_path, card(art, scene=f'{sky}<g id="scene"><rect width="800" height="500" fill="url(#sky)"/></g>'), "moon", name="root-defs")
    assert (code, report["errors"]) == (0, [])  # the same gradient in the root <defs>: the card as the handbook writes it


def test_check_reports_what_the_sanitiser_drops_and_dangling_references(tmp_path):
    art = lay("moon")["snippet"]
    blur = '<defs><filter id="b3"><feGaussianBlur stdDeviation="3"/></filter><clipPath id="c"><rect width="400" height="500"/></clipPath></defs>'
    ok_scene = f'{blur}<g id="scene"><g filter="url(#b3)" clip-path="url(#c)"><rect width="800" height="500" fill="#CFE3F5"/></g></g>'
    code, report = check_text(tmp_path, card(art, scene=ok_scene), "moon", name="effects")
    assert (code, report["errors"]) == (0, []) and (report["blur_filters"], report["blurred_elements"]) == (1, 1)  # the memory-card mode keeps blur and clipping
    masked = '<defs><mask id="m"><rect width="800" height="500" fill="#fff"/></mask></defs><g id="scene"><rect width="800" height="500" fill="#CFE3F5" class="sky" filter="url(other.svg#b)"/></g>'
    code, report = check_text(tmp_path, card(art, scene=masked), "moon", name="masked")
    assert code == 1
    assert any("DROPPED these elements" in e and "'mask': 1" in e for e in report["errors"]), report["errors"]
    assert any("DROPPED these attributes" in e and "'class': 1" in e and "'filter': 1" in e for e in report["errors"]), report["errors"]
    dangling = '<g id="scene"><rect id="sky" width="800" height="500" fill="url(#nowhere)"/><rect id="sky" width="8" height="5"/></g>'
    code, report = check_text(tmp_path, card(art, scene=dangling), "moon", name="dangling")
    assert code == 1 and any("duplicate ids: ['sky']" in e for e in report["errors"]) and any("no matching id: ['nowhere']" in e for e in report["errors"]), report["errors"]
    code, report = check_text(tmp_path, card(art)[: -len("</svg>")], "moon", name="broken")  # the root never closes
    assert code == 1 and report["ok"] is False and "not well-formed XML" in report["errors"][0]


def test_check_reports_the_blur_budget_in_the_imports_words(tmp_path):
    """The limits that turn a card away are the import's (`memo.check_structure`: the elements under a filter, the primitives
    chained in one filter, the reach of a stdDeviation) — the tool passes its sentences on and keeps no number of its own
    beside them. Its own, softer advice is the warning above MAX_BLURRED filtered elements, which names the import's limit;
    the handbook states the same numbers."""
    san, memo = check.load_backend()
    art = lay("moon")["snippet"]
    blur = '<defs><filter id="b3"><feGaussianBlur stdDeviation="3"/></filter></defs>'
    shape = '<circle cx="400" cy="250" r="60" fill="#FFF8E7" filter="url(#b3)"/>'

    def blurred(defs: str, n: int) -> str:
        return card(art, scene=f'{defs}<g id="scene"><rect width="800" height="500" fill="#CFE3F5"/>{shape * n}</g>')

    assert check.MAX_BLURRED < memo.MAX_FILTERED
    code, report = check_text(tmp_path, blurred(blur, check.MAX_BLURRED), "moon", name="dozen")
    assert (code, report["errors"], report["warnings"], report["blurred_elements"]) == (0, [], [], check.MAX_BLURRED)
    code, report = check_text(tmp_path, blurred(blur, memo.MAX_FILTERED), "moon", name="many")  # between the two: the tool's warning, no error
    assert (code, report["errors"]) == (0, []) and len(report["warnings"]) == 1
    assert report["warnings"][0].startswith(f"{memo.MAX_FILTERED} elements use a blur filter") and report["warnings"][0].endswith(f"the import refuses a card with more than {memo.MAX_FILTERED}")
    code, report = check_text(tmp_path, blurred(blur, memo.MAX_FILTERED + 1), "moon", name="too-many")
    assert code == 1 and report["errors"] == memo.check_structure(san.clean(blurred(blur, memo.MAX_FILTERED + 1), allow_text=False, effects=True), "moon")
    assert len(report["errors"]) == 1 and report["errors"][0].startswith(f"{memo.MAX_FILTERED + 1} elements carry a filter, at most {memo.MAX_FILTERED} may")
    chain = '<defs><filter id="b3">' + '<feDropShadow dx="0" dy="4" stdDeviation="4"/>' * (memo.MAX_FILTER_PRIMITIVES + 1) + "</filter></defs>"
    code, report = check_text(tmp_path, blurred(chain, 1), "moon", name="chain")  # ONE filtered element: nothing the warning could count
    assert code == 1 and len(report["errors"]) == 1 and report["warnings"] == []
    assert report["errors"][0].startswith(f'<filter id="b3"> chains {memo.MAX_FILTER_PRIMITIVES + 1} feGaussianBlur / feDropShadow primitives, at most {memo.MAX_FILTER_PRIMITIVES} may')
    wide = blur.replace('stdDeviation="3"', f'stdDeviation="{memo.MAX_STD_DEVIATION + 1}"')
    code, report = check_text(tmp_path, blurred(wide, 1), "moon", name="wide")
    assert code == 1 and len(report["errors"]) == 1 and report["errors"][0].startswith(f'stdDeviation="{memo.MAX_STD_DEVIATION + 1}" on <feGaussianBlur>: write one or two plain numbers from 0 to {memo.MAX_STD_DEVIATION}')
    rule = " ".join((STUDIO / "STUDIO.md").read_text(encoding="utf-8").split())  # §1, the blur rule: the three numbers of memo.py and the tool's warning level
    assert f"more than {memo.MAX_FILTERED} elements with a `filter`" in rule and f"more than {memo.MAX_FILTER_PRIMITIVES} `feGaussianBlur` / `feDropShadow` inside one `<filter>`" in rule
    assert f"one or two plain numbers from 0 to {memo.MAX_STD_DEVIATION}" in rule and f"`check` warns above {check.MAX_BLURRED} filtered elements" in rule


def test_check_a_dotless_i_is_only_a_warning_when_its_dot_path_is_gone(tmp_path):
    out = lay("rain", split_dots=True)
    code, report = check_text(tmp_path, card(out["snippet"]), "rain", name="dotted")
    assert (code, report["warnings"]) == (0, [])
    no_dot = sub_once(r'\s*<path id="wa-2-i-dot"[^>]*/>', "", out["snippet"])  # a drawn raindrop is meant to sit there instead
    code, report = check_text(tmp_path, card(no_dot), "rain", name="dotless")
    assert code == 0 and report["errors"] == [] and any(w.startswith("wa-2-i: dotless glyph") for w in report["warnings"]), report


def test_check_a_path_under_the_dots_id_is_the_dot_only_when_it_is_the_fonts_dot_in_its_place(tmp_path):
    """`wa-<i>-i-dot` used to silence the dotless warning by existing. It counts now when it is the font's dot (shape and
    size), where the font puts it over the stem, moved by the same transform as the stem, and drawn; anything else under
    that id leaves the pupil an ı and the illustrator the warning — still a warning: a drawn object may stand in for the dot."""
    out = lay("rain", split_dots=True)
    dot = out["letters"][2]["dot"]
    its_d = f'd="{dot["d"]}"'
    assert out["snippet"].count(its_d) == 1
    not_the_dot = {
        "speck": out["snippet"].replace(its_d, 'd="M5 5H6V6H5Z"'),  # a 1 px square in the corner of the canvas
        "emptied": out["snippet"].replace(its_d, 'd=""'),
        "carried-off": with_attrs(out["snippet"], dot["id"], 'transform="translate(200 -150)"'),  # the genuine outline, somewhere else
        "nudged": with_attrs(out["snippet"], dot["id"], 'transform="translate(5 0)"'),
        "shifted-in-d": out["snippet"].replace(its_d, f'd="{lay("rain", split_dots=True, x=410.0)["letters"][2]["dot"]["d"]}"'),  # 10 px to the right, written into the d
        "swollen": out["snippet"].replace(its_d, f'd="{lay("rain", split_dots=True, size=300.0)["letters"][2]["dot"]["d"]}"'),
        "switched-off": with_attrs(out["snippet"], dot["id"], 'display="none"'),
        "unpainted": with_attrs(out["snippet"], dot["id"], 'fill="none"'),
    }
    for name, art in not_the_dot.items():
        code, errors, warnings = verdict(tmp_path, name, art, "rain")
        assert (code, errors) == (0, []) and len(warnings) == 1 and warnings[0].startswith("wa-2-i: dotless glyph") and "wa-2-i-dot" in warnings[0], (name, warnings)
    # the dot that travels with its stem is the dot: one group moves, scales and tips both; the same transform on each; another size
    assert verdict(tmp_path, "together", grouped(out["snippet"], 'transform="translate(30 20) scale(.8) rotate(2)"'), "rain") == (0, [], [])
    each = with_attrs(with_attrs(out["snippet"], "wa-2-i", 'transform="translate(0 -6)"'), dot["id"], 'transform="translate(0 -6)"')
    assert verdict(tmp_path, "each", each, "rain") == (0, [], [])
    for size in (64.0, 96.0, 180.0):  # i and j, at the smallest size a card may use and at the largest the house style asks for
        code, errors, warnings = verdict(tmp_path, f"jig-{size:.0f}", lay("jig", size=size, split_dots=True)["snippet"], "jig")
        assert (code, errors) == (0, []) and not any("dotless" in w for w in warnings), (size, warnings)
    # the first ten cards carry the font's raw contours: their split dot is the dot as well (rain.svg is one of them)
    assert verdict(tmp_path, "raw", lay("rain", split_dots=True, simplify=False)["snippet"], "rain") == (0, [], [])


def test_check_sheet_mode_skips_the_card_contract_and_usage_errors_exit_2(tmp_path):
    code, report = run_check(STUDIO / "cast" / "cards" / "sheet.svg", tmp_path, "--sheet", "--no-render")
    assert code == 0 and report["errors"] == [] and "word_art" not in report  # 1200×760, no layers: fine for a sheet
    assert (tmp_path / "clean" / "sheet.svg").is_file()
    p = subprocess.run([sys.executable, str(TOOLS / "check.py"), str(CARDS / "moon.svg"), "--no-render"], capture_output=True, text=True)
    assert p.returncode == 2 and "--word is required" in p.stderr and not p.stdout
    p = subprocess.run([sys.executable, str(TOOLS / "check.py"), str(tmp_path / "nothing.svg"), "--word", "moon"], capture_output=True, text=True)
    assert p.returncode == 2 and "no such file" in p.stderr


def test_check_stops_when_the_repository_cannot_judge_a_memory_card(tmp_path):
    """No private copy of the rules to fall back on: a backend without ``memo.py``, or whose sanitiser has no ``effects``
    mode, cannot import a card either — the tool says which piece is missing and exits 2 without a verdict. (Run in a
    child interpreter: the stand-in backend must not stay in this process's ``sys.modules``.)"""
    driver = "import sys; sys.path.insert(0, sys.argv[1]); import check; from pathlib import Path; check.BACKEND = Path(sys.argv[2]); check.load_backend(); print('loaded')"
    real = REPO / "backend" / "wd" / "images"
    no_memo = tmp_path / "no-memo" / "wd" / "images"
    no_memo.mkdir(parents=True)
    (no_memo / "sanitize_svg.py").write_text((real / "sanitize_svg.py").read_text(encoding="utf-8"), encoding="utf-8")
    p = subprocess.run([sys.executable, "-c", driver, str(TOOLS), str(tmp_path / "no-memo")], capture_output=True, text=True)
    assert p.returncode == 2 and not p.stdout and p.stderr.startswith("check.py: cannot load the repository's sanitiser / structure check") and "wd.images.memo" in p.stderr
    old = tmp_path / "old" / "wd" / "images"
    old.mkdir(parents=True)
    (old / "sanitize_svg.py").write_text("def clean(svg, *, allow_text=True):\n    return svg\n", encoding="utf-8")
    (old / "memo.py").write_text((real / "memo.py").read_text(encoding="utf-8"), encoding="utf-8")
    p = subprocess.run([sys.executable, "-c", driver, str(TOOLS), str(tmp_path / "old")], capture_output=True, text=True)
    assert p.returncode == 2 and not p.stdout and "has no sanitize_svg.clean(…, effects=True) or no memo.check_structure" in p.stderr
    p = subprocess.run([sys.executable, "-c", driver, str(TOOLS), str(REPO / "backend")], capture_output=True, text=True)
    assert (p.returncode, p.stdout.strip()) == (0, "loaded"), p.stderr  # and this checkout's backend is one that can


def test_check_without_chrome_says_so_and_still_validates(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check, "CHROME", str(tmp_path / "no-such-chrome"))
    monkeypatch.setattr(sys, "argv", ["check.py", str(CARDS / "moon.svg"), "--word", "moon", "--out-dir", str(tmp_path)])
    assert check.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and len(report["errors"]) == 1
    assert "Google Chrome not found at" in report["errors"][0] and "--no-render" in report["errors"][0]
    assert (tmp_path / "clean" / "moon.svg").is_file() and not (tmp_path / "png").exists()
    assert report["word_art"]["letter_em_px"]  # the validation ran; only the render is missing


@pytest.mark.skipif(not Path(check.CHROME).exists(), reason="Google Chrome is not installed where check.CHROME points")
def test_check_renders_the_card_the_sheet_and_a_zoom(tmp_path):
    code, report = run_check(CARDS / "moon.svg", tmp_path, "--word", "moon", "--zoom", "330,20,460,160")
    assert (code, report["errors"]) == (0, [])

    def png_size(path: str) -> tuple[int, int]:
        head = Path(path).read_bytes()[:24]
        assert head[:8] == b"\x89PNG\r\n\x1a\n"
        return struct.unpack(">II", head[16:24])

    assert report["png"] == str(tmp_path / "png" / "moon.png") and png_size(report["png"]) == (800, 500)
    assert png_size(report["sheet_png"]) == (800, 290)
    assert report["zoom_pngs"] == [str(tmp_path / "png" / "moon.zoom1.png")] and png_size(report["zoom_pngs"][0]) == (800, 278)


def stub_chrome(tmp_path: Path, monkeypatch, pages: str) -> None:
    """A shell script stands in for Chrome: it "renders" (writes a file for) the pages whose path matches the sh pattern
    ``pages`` and crashes on every other one. The render scaffolding goes to the test's own directory, not studio/tmp."""
    stub = tmp_path / "chrome"
    stub.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in --screenshot=*) out="${a#--screenshot=}";; file://*) url="$a";; esac; done\n'
        f'case "$url" in {pages}) printf PNG > "$out";; *) echo "renderer crashed" >&2; exit 1;; esac\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setattr(check, "CHROME", str(stub))
    monkeypatch.setattr(check, "TMP", tmp_path / "tmp")


def run_main(monkeypatch, capsys, *argv: str) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["check.py", *argv])
    code = check.main()
    return code, json.loads(capsys.readouterr().out)


def test_check_a_sheet_or_a_zoom_chrome_did_not_write_is_an_error(tmp_path, monkeypatch, capsys):
    """Chrome draws the card and then crashes — or runs into the 90 s timeout — on the next page: a busy machine, a batch
    of a hundred. The report used to say ``ok: true`` with ``sheet_png: null`` and a zoom file that did not exist, and a
    loop keyed on the exit status moved on without the scene-only / phone-size view the handbook makes everybody look at."""
    zooms = ("--zoom", "330,20,460,160", "--zoom", "40,300,720,180")
    png = tmp_path / "png"
    stub_chrome(tmp_path, monkeypatch, "*/full-*")
    code, report = run_main(monkeypatch, capsys, str(CARDS / "moon.svg"), "--word", "moon", "--out-dir", str(tmp_path), *zooms)
    assert code == 1 and report["ok"] is False and report["warnings"] == []
    assert sorted(e.split(" was not written")[0] for e in report["errors"]) == ["render failed: moon.sheet.png", "render failed: moon.zoom1.png", "render failed: moon.zoom2.png"]
    assert (report["png"], report["sheet_png"], report["zoom_pngs"]) == (str(png / "moon.png"), None, [])  # only what is on disk is listed
    # one zoom of the two is lost: the other is listed, and the sheet is there
    stub_chrome(tmp_path, monkeypatch, "*/full-*|*/sheet-*|*/zoom-*-2.html")
    code, report = run_main(monkeypatch, capsys, str(CARDS / "moon.svg"), "--word", "moon", "--out-dir", str(tmp_path), *zooms)
    assert code == 1 and len(report["errors"]) == 1 and report["errors"][0].startswith("render failed: moon.zoom1.png was not written"), report["errors"]
    assert (report["sheet_png"], report["zoom_pngs"]) == (str(png / "moon.sheet.png"), [str(png / "moon.zoom2.png")])
    # the sheet mode has no second page, but its zooms are held to the same rule
    code, report = run_main(monkeypatch, capsys, str(STUDIO / "cast" / "cards" / "sheet.svg"), "--sheet", "--out-dir", str(tmp_path), "--zoom", "0,0,300,300")
    assert code == 1 and [e.split(" was not written")[0] for e in report["errors"]] == ["render failed: sheet.zoom1.png"] and report["zoom_pngs"] == []
    # nothing at all rendered: the card's own PNG is named the same way
    stub_chrome(tmp_path, monkeypatch, "*/no-such-page")
    code, report = run_main(monkeypatch, capsys, str(CARDS / "moon.svg"), "--word", "moon", "--out-dir", str(tmp_path))
    assert code == 1 and [e.split(" was not written")[0] for e in report["errors"]] == ["render failed: moon.png", "render failed: moon.sheet.png"]
    assert (report["png"], report["sheet_png"]) == (None, None) and "zoom_pngs" not in report
    assert not (png / "moon.png").exists() and not (png / "moon.sheet.png").exists()  # the earlier run's files are not left to pass for this one's
    # every page rendered: nothing to say
    stub_chrome(tmp_path, monkeypatch, "*")
    code, report = run_main(monkeypatch, capsys, str(CARDS / "moon.svg"), "--word", "moon", "--out-dir", str(tmp_path), *zooms)
    assert (code, report["errors"]) == (0, []) and report["zoom_pngs"] == [str(png / "moon.zoom1.png"), str(png / "moon.zoom2.png")]


# ---------------------------------------------------------------- url(#id) in every spelling the sanitiser keeps
QUOTED_DEFS = (
    '<defs><linearGradient id="sky" x2="0" y2="1"><stop offset="0" stop-color="#8FB8F0"/><stop offset="1" stop-color="#FFF3D6"/></linearGradient>'
    '<linearGradient id="lc" x2="0" y2="1"><stop offset="0" stop-color="#F0705A"/><stop offset="1" stop-color="#D8432C"/></linearGradient>'
    '<filter id="ws" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3"/></filter></defs>'
)


def quoted_card() -> str:
    """`moon` on a card that writes none of its three references the handbook's way: ``url('#sky')``, ``url("#ws")`` (which
    the sanitiser serialises inside a single-quoted attribute) and ``url( #lc )``. The app paints all three."""
    scene = QUOTED_DEFS + '<g id="scene"><rect width="800" height="500" fill="url(\'#sky\')"/><ellipse cx="400" cy="420" rx="300" ry="30" fill="#FFF8E7" filter="url(&quot;#ws&quot;)"/></g>'
    return card(lay("moon")["snippet"].replace('<g id="word-art">', '<g id="word-art" fill="url( #lc )">'), scene=scene)


def references(page: str) -> list[str]:
    """What stands between the brackets of every ``url(…)`` of a page."""
    return re.findall(r"url\(([^)]*)\)", page)


def test_reid_follows_a_reference_in_every_spelling_the_sanitiser_keeps(tmp_path, monkeypatch, capsys):
    san, _memo = check.load_backend()
    cleaned = san.clean(quoted_card(), allow_text=False, effects=True)
    assert sorted(references(cleaned)) == [" #lc ", '"#ws"', "'#sky'"]  # the three spellings reach the cleaned file as they were written
    renamed = check.reid(cleaned + '<rect fill="url(#sky) #fff"/>', "_a")  # … and a paint with a fallback colour after it
    assert sorted(references(renamed)) == ["#lc_a", "#sky_a", "#sky_a", "#ws_a"] and 'fill="url(#sky_a) #fff"' in renamed
    assert sorted(re.findall(r'\bid="([^"]+)"', renamed)) == sorted(f"{i}_a" for i in ["sky", "lc", "ws", "scene", "word-art", "wa-0-m", "wa-1-o", "wa-2-o", "wa-3-n"])
    # the validation counts the blurred element however its filter is spelled (the old-tablet budget) …
    code, report = check_text(tmp_path, quoted_card(), "moon", name="quoted")
    assert (code, report["errors"], report["warnings"]) == (0, [], []) and (report["blur_filters"], report["blurred_elements"]) == (1, 1)
    # … and the sheet page — two copies of the card side by side, every id suffixed — keeps every reference attached: with
    # the suffix on the ids only, the scene-only and phone-size views of this card were two empty panels beside a perfect PNG
    stub_chrome(tmp_path, monkeypatch, "*")
    code, report = run_main(monkeypatch, capsys, str(tmp_path / "cards" / "quoted.svg"), "--word", "moon", "--out-dir", str(tmp_path))
    assert (code, report["errors"]) == (0, []) and report["sheet_png"]
    (sheet,) = (tmp_path / "tmp").glob("sheet-quoted-*.html")
    page = sheet.read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', page)
    assert len(ids) == len(set(ids)) == 18
    assert sorted(references(page)) == ["#lc_a", "#lc_b", "#sky_a", "#sky_b", "#ws_a", "#ws_b"] and {r[1:] for r in references(page)} <= set(ids)


# ---------------------------------------------------------------- build_gallery.py
def test_gallery_is_one_page_with_every_card_inlined(tmp_path):
    out = tmp_path / "gallery.html"
    p = subprocess.run([sys.executable, str(TOOLS / "build_gallery.py"), "--out", str(out)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    page = out.read_text(encoding="utf-8")
    assert page.count('<article class="card"') == len(LEMMAS) and page.count('<g class="wa" id="word-art-') == len(LEMMAS)
    ids = re.findall(r'\bid="([^"]+)"', page)
    assert len(ids) == len(set(ids))  # ten cards, each with a gradient called `sky`: every id carries its card's suffix
    assert set(re.findall(r"url\(#([^)]+)\)", page)) <= set(ids)
    for cap in MANIFEST["cards"].values():
        assert cap["hook_zh"].split("：")[0].split("，")[0] in page
    assert "<text" not in page and "{{" not in page
    # a lemma of the manifest without its file is left out, said on stderr, and fails the run
    manifest = tmp_path / "manifest.json"
    assert not (CARDS / "polar_bear.svg").exists()  # a lemma no card has been drawn for (`ice cream` served here until its card arrived)
    manifest.write_text(json.dumps({**MANIFEST, "cards": {**MANIFEST["cards"], "polar bear": {"alt_zh": "…", "hook_zh": "…", "note_zh": ""}}}, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(TOOLS / "build_gallery.py"), "--manifest", str(manifest), "--out", str(out), "--only", "moon", "polar bear"], capture_output=True, text=True)
    assert p.returncode == 1 and "skip polar bear" in p.stderr and "polar_bear.svg" in p.stderr
    assert out.read_text(encoding="utf-8").count('<article class="card"') == 1
    # a card that quotes its references (url('#sky'), url("#ws"), url( #lc ) — the sanitiser keeps them, the app paints them)
    # is shown painted on the page the owner approves the import from: the references follow their ids
    batch = tmp_path / "batch" / "cards"
    batch.mkdir(parents=True)
    (batch / "moon.svg").write_text(quoted_card(), encoding="utf-8")
    (batch / "rain.svg").write_text(approved("rain"), encoding="utf-8")
    manifest.write_text(json.dumps({**MANIFEST, "cards": {k: MANIFEST["cards"][k] for k in ("moon", "rain")}}, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(TOOLS / "build_gallery.py"), "--cards", str(batch), "--manifest", str(manifest), "--out", str(out)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    page = out.read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', page)
    assert len(ids) == len(set(ids)) and {"sky-0", "lc-0", "ws-0", "word-art-0", "word-art-1"} <= set(ids)
    assert {"#sky-0", "#lc-0", "#ws-0"} <= set(references(page)) and {r.lstrip("#") for r in references(page)} <= set(ids) and all(r.startswith("#") for r in references(page))


# ---------------------------------------------------------------- the move into the repository
def test_nothing_in_the_studio_points_outside_the_repository():
    """The studio came out of a session's temporary directory; a path into it (or into any private temp directory) left in
    a tool or a handbook would work today and break when that directory is cleaned. The one absolute path a text may
    carry is the owner's archive, named in README.md as the place of what was NOT moved."""
    gone = ("claude" + "-501", "scratch" + "pad", "/private/" + "tmp")
    skipped = {".venv", "tmp", "png", "clean", "fonts", "__pycache__", ".pytest_cache"}
    hits = []
    for root, dirs, files in os.walk(STUDIO):
        dirs[:] = [d for d in dirs if d not in skipped]
        for name in files:
            text = (Path(root) / name).read_text(encoding="utf-8", errors="replace")
            hits += [f"{Path(root, name).relative_to(STUDIO)}: {g}" for g in gone if g in text]
    assert hits == []
    for tool in ("letters", "check", "build_gallery"):
        wrapper = (TOOLS / tool).read_text(encoding="utf-8")
        assert os.access(TOOLS / tool, os.X_OK) and "studio/.venv/bin/python" in wrapper and 'PYTHONPATH="$repo/backend' in wrapper and f"$here/{tool}.py" in wrapper


def test_the_handbooks_name_each_other_and_every_dependency_of_the_tools():
    """An illustrator is handed STUDIO.md and reads the files it lists; whoever sets the tools up reads README.md, or the
    message of a tool that could not start. A handbook neither list names is never opened (LESSONS.md — "read before you
    plan or draw" — was written after the lists), a dependency missing from the prose is missing from a virtualenv built
    by hand, and a switch only `--help` knows is not used."""
    readme, handbook = ((STUDIO / name).read_text(encoding="utf-8") for name in ("README.md", "STUDIO.md"))
    books = sorted(p.name for p in STUDIO.glob("*.md"))
    assert "LESSONS.md" in books
    for name in books:
        assert f"studio/{name}" in readme and f"studio/{name}" in handbook, name
    deps = [line.split("==")[0] for line in (STUDIO / "requirements.txt").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert deps == ["fonttools", "defusedxml", "skia-pathops"]
    for dep in deps:
        assert dep in readme and dep in inspect.getsource(check.load_backend), dep  # README §2 / §4, and what `check` says when it cannot load the backend
        assert dep in (TOOLS / "check").read_text(encoding="utf-8"), dep
    assert "--raw-outlines" in handbook and "--raw-outlines" in readme  # the switch that reproduces the first ten cards' outlines
    assert "overlap-free" in handbook  # §3 describes the outlines `letters` prints today (LESSONS.md #10 relies on them)
