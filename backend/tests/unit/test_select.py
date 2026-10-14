"""images/select.py: blocklist, hard rejects, the DESIGN §9 scoring table, exclude handling, dedupe and the minimum score."""

from __future__ import annotations

import pytest

from wd.images import select
from wd.interfaces import Candidate


def cand(**overrides) -> Candidate:
    base = dict(
        provider="wikimedia",
        ref="1",
        title="Red apple on a table",
        creator="Someone",
        creator_url=None,
        license="CC BY 2.0",
        license_url="https://creativecommons.org/licenses/by/2.0",
        landing_url="https://commons.wikimedia.org/wiki/File:Red_Apple.jpg",
        image_url="https://thumb.wikimedia.org/wikipedia/commons/thumb/1/15/Red_Apple.jpg/800px-Red_Apple.jpg",
        width=800,
        height=600,
        mime="image/jpeg",
        tags=["apples"],
        mature=False,
        extra={},
    )
    base.update(overrides)
    return Candidate(**base)


@pytest.mark.parametrize(
    "word",
    ["map", "diagram", "logo", "flag", "coat of arms", "chart", "graph", "screenshot", "poster", "cover", "scan", "text", "document", "nude", "nudity", "sex", "porn", "gore", "blood", "weapon", "gun", "corpse"],
)
def test_blocklist_words(word):
    assert select.is_blocked(f"a {word} of something")
    assert select.is_blocked(f"A {word.upper()}")


def test_blocklist_respects_word_boundaries():
    assert not select.is_blocked("covered bridge")
    assert not select.is_blocked("textbook on a desk")
    assert not select.is_blocked("mapping the sky")
    assert not select.is_blocked("")
    assert not select.is_blocked(None)


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"mature": True}, "mature"),
        ({"extra": {"sensitivity": ["sexual"]}}, "sensitivity"),
        ({"extra": {"restrictions": "trademarked"}}, "restrictions"),
        ({"license": "CC BY-NC 2.0"}, "license"),
        ({"license": "CC BY-ND 4.0"}, "license"),
        ({"license": "GFDL"}, "license"),
        ({"license": ""}, "license"),
        ({"mime": "image/gif"}, "mime"),
        ({"mime": "image/svg+xml"}, "mime"),
        ({"width": 399}, "size"),
        ({"height": 299}, "size"),
        ({"width": 1000, "height": 300}, "aspect"),  # 3.33
        ({"width": 400, "height": 800}, "aspect"),  # 0.5
        ({"title": "Map of Europe"}, "blocklist"),
        ({"tags": ["apples", "logo"]}, "blocklist"),
        ({"extra": {"description": "Screenshot of an app"}}, "blocklist"),
    ],
)
def test_hard_rejects(overrides, reason):
    assert select.reject_reason(cand(**overrides)) == reason


def test_acceptable_candidate_and_unknown_dimensions_pass():
    assert select.reject_reason(cand()) is None
    assert select.reject_reason(cand(width=None, height=None, mime=None)) is None
    assert select.reject_reason(cand(license="CC0")) is None
    assert select.reject_reason(cand(license="Public domain")) is None
    assert select.reject_reason(cand(license="CC BY-SA 4.0")) is None
    assert select.reject_reason(cand(provider="pixabay", license="Pixabay License")) is None


def test_exclude_matches_ref_provider_ref_and_url():
    c = cand(ref="7823406")
    assert select.reject_reason(c, {"7823406"}) == "excluded"
    assert select.reject_reason(c, {"wikimedia:7823406"}) == "excluded"
    assert select.reject_reason(c, {c.image_url}) == "excluded"
    assert select.reject_reason(c, {"other", "abc123"}) is None


def test_score_table():
    # 600/500 is exactly 1.2 → +1 aspect, licence by-sa +1 → total 2; 600/550 leaves only the licence point
    assert select.score(cand(title="Untitled", tags=[], license="CC BY-SA 2.0", width=600, height=500), "apple") == 2
    assert select.score(cand(title="Untitled", tags=[], license="CC BY-SA 2.0", width=600, height=550), "apple") == 1
    # keyword hits: one per token, capped at 3 (title + tags)
    many = cand(title="Big red apple tree orchard", tags=["fruit", "harvest"], license="CC BY-SA 2.0", width=600, height=550)
    assert select.score(many, "big red apple tree orchard fruit") == 3 + 1
    assert select.score(cand(title="Apples", tags=[], license="CC BY-SA 2.0", width=600, height=550), "apple") == 1 + 1  # prefix match apple→apples
    # licence points
    assert select.score(cand(title="x", tags=[], license="CC0", width=600, height=550), "apple") == 3
    assert select.score(cand(title="x", tags=[], license="Public domain", width=600, height=550), "apple") == 3
    assert select.score(cand(title="x", tags=[], license="CC BY 2.0", width=600, height=550), "apple") == 2
    assert select.score(cand(title="x", tags=[], license="Pixabay License", width=600, height=550, provider="pixabay"), "apple") == 2
    # aspect 1.2–1.8 → +1, width ≥ 800 → +1
    assert select.score(cand(title="x", tags=[], license="CC BY-SA 2.0", width=800, height=500), "apple") == 1 + 1 + 1
    assert select.score(cand(title="x", tags=[], license="CC BY-SA 2.0", width=800, height=800), "apple") == 1 + 1
    # Commons assessments
    assert select.score(cand(title="x", tags=[], license="CC BY-SA 2.0", width=600, height=550, extra={"assessments": "featured|potd"}), "apple") == 3
    assert select.score(cand(title="x", tags=[], license="CC BY-SA 2.0", width=600, height=550, extra={"assessments": "quality"}), "apple") == 3
    assert select.score(cand(title="x", tags=[], license="CC BY-SA 2.0", width=600, height=550, extra={"assessments": "valued"}), "apple") == 3
    # filename-like titles
    assert select.score(cand(title="IMG_1234", tags=[], license="CC BY-SA 2.0", width=600, height=550), "apple") == 0
    assert select.score(cand(title="DSC00123", tags=[], license="CC BY-SA 2.0", width=600, height=550), "apple") == 0
    assert select.score(cand(title="Market day 2019", tags=[], license="CC BY-SA 2.0", width=600, height=550), "apple") == 0
    # already used image −2
    assert select.score(cand(title="x", tags=[], license="CC0", width=600, height=550, ref="42"), "apple", used_refs={"wikimedia:42"}) == 1
    assert select.score(cand(title="x", tags=[], license="CC0", width=600, height=550, ref="42"), "apple", used_refs={"42"}) == 1


def test_rank_sorts_best_first_dedupes_and_applies_min_score():
    weak = cand(ref="w", title="Untitled", tags=[], license="CC BY-SA 2.0", width=600, height=550, image_url="https://x.example/w.jpg")  # score 1 → kept
    dropped = cand(ref="d", title="IMG_0001", tags=[], license="CC BY-SA 2.0", width=600, height=550, image_url="https://x.example/d.jpg")  # 0 → dropped
    strong = cand(ref="s", title="Red apple", tags=[], license="CC0", width=800, height=500, image_url="https://x.example/s.jpg")  # 1+3+1+1 = 6
    rejected = cand(ref="r", title="Red apple map", tags=[], license="CC0", width=800, height=500, image_url="https://x.example/r.jpg")
    dup = cand(ref="s", title="Red apple", tags=[], license="CC0", width=800, height=500, image_url="https://x.example/s.jpg")
    same_url = cand(ref="other", title="Red apple", tags=[], license="CC0", width=800, height=500, image_url="https://x.example/s.jpg")
    ranked = select.rank([weak, dropped, strong, rejected, dup, same_url], "apple")
    assert [c.ref for c in ranked] == ["s", "w"]
    assert ranked[0].extra["score"] == 6 and ranked[1].extra["score"] == 1


def test_rank_is_stable_for_equal_scores_and_honours_exclude():
    a = cand(ref="a", image_url="https://x.example/a.jpg")
    b = cand(ref="b", image_url="https://x.example/b.jpg")
    assert [c.ref for c in select.rank([a, b], "apple")] == ["a", "b"]
    assert [c.ref for c in select.rank([a, b], "apple", exclude={"a"})] == ["b"]
    assert [c.ref for c in select.rank([a, b], "apple", exclude={"wikimedia:b"})] == ["a"]


def test_keyword_tokens_drop_stopwords_and_short_words():
    assert select.keyword_tokens("a cup of tea") == ["cup", "tea"]
    assert select.keyword_tokens("handshake across table") == ["handshake", "across", "table"]
