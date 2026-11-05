"""images/select.py: the three-way blocklist (unsafe / non-photo with the query-token exemption / kid-unsafe), hard rejects
(with the ``allow`` / ``style`` plumbing of reject_reason and rank), the DESIGN §9 scoring table plus the five PLAN §5.1 C6
signals (description hit, provider category vs the round's target, people words in the kid style, signage words, portrait
orientation), exclude handling, dedupe and the minimum score."""

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
    assert select.keyword_tokens("a cup of tea") == frozenset({"cup", "tea"})
    assert select.keyword_tokens("handshake across table") == frozenset({"handshake", "across", "table"})
    assert select.keyword_tokens("World Map") == frozenset({"world", "map"})  # the `allow` set of is_blocked
    assert select.keyword_tokens("a of") == frozenset() and isinstance(select.keyword_tokens(""), frozenset)


# ------------------------------------------------------------ S5 (PLAN §5.1 C5): three lists, query-token exemption, kid style
def test_blocklist_splits_into_unsafe_non_photo_and_kid_unsafe():
    unsafe = ["nude", "nudity", "sex", "porn", "gore", "blood", "weapon", "gun", "corpse"]
    non_photo = ["map", "diagram", "logo", "flag", "coat of arms", "chart", "graph", "screenshot", "poster", "cover", "scan", "text", "document"]
    kid_unsafe = ["beer", "wine", "alcohol", "cigarette", "cigarettes", "smoking", "horror", "zombie", "zombies", "skull", "skulls", "knife", "knives", "bikini", "lingerie"]
    assert all(select.UNSAFE_RE.search(f"a {w} here") for w in unsafe) and not any(select.UNSAFE_RE.search(w) for w in non_photo + kid_unsafe)
    assert all(select.NON_PHOTO_RE.search(f"a {w} here") for w in non_photo) and not any(select.NON_PHOTO_RE.search(w) for w in unsafe + kid_unsafe)
    assert all(select.KID_UNSAFE_RE.search(f"a {w} here") for w in kid_unsafe) and not any(select.KID_UNSAFE_RE.search(w) for w in unsafe + non_photo)
    assert not hasattr(select, "BLOCKLIST_RE")  # the merged list is gone; is_blocked is the one entry point


def test_non_photo_words_are_allowed_when_they_are_query_tokens():
    """`map`, `flag`, `cover`, `text` are 小学 words: a search for "world map" may accept a map, a search for "apple" may not,
    and the unsafe list is never exempted (D-images-10)."""
    assert select.is_blocked("Map of Europe") is True
    assert select.is_blocked("Map of Europe", allow=frozenset({"map"})) is False
    assert select.is_blocked("Map of Europe", allow=select.keyword_tokens("world map")) is False
    assert select.is_blocked("Map of Europe", allow=select.keyword_tokens("apple")) is True
    assert select.is_blocked("Map and flag of Europe", allow=frozenset({"map"})) is True  # every non-photo hit must be allowed
    assert select.is_blocked("Map and flag of Europe", allow=frozenset({"map", "flag"})) is False
    assert select.is_blocked("Coat of arms of Shanghai", allow=frozenset({"coat", "arms"})) is True  # the phrase is one list entry, not two tokens
    assert select.is_blocked("Coat of arms of Shanghai", allow=frozenset({"coat of arms"})) is False
    assert select.is_blocked("gun shop", allow=frozenset({"gun"})) is True
    assert select.is_blocked("blood orange", allow=select.keyword_tokens("blood orange")) is True
    assert select.is_blocked("", allow=frozenset({"map"})) is False and select.is_blocked(None) is False


def test_kid_style_rejects_kid_unsafe_words():
    for text in ("a glass of beer", "Wine cellar", "Smoking man", "zombie parade", "skull and bones", "a kitchen knife", "Knives on a table", "horror movie poster"):
        assert select.is_blocked(text, style="kid") is True, text
    assert select.is_blocked("a glass of beer") is False and select.is_blocked("a glass of beer", style="neutral") is False
    assert select.is_blocked("a kitchen knife", style="kid", allow=frozenset({"knife"})) is True  # the kid list is never exempted
    assert select.is_blocked("red apple on a table", style="kid") is False
    assert select.is_blocked("Map of Europe", style="kid", allow=frozenset({"map"})) is False  # the exemption works in both styles


def test_reject_reason_honours_the_query_token_exemption_and_the_kid_list():
    """reject_reason / rank carry `allow` (the query's tokens) and `style` to is_blocked (PLAN §5.1 C5)."""
    europe = cand(title="Map of Europe")
    assert select.reject_reason(europe) == "blocklist"
    assert select.reject_reason(europe, allow=frozenset({"map"})) is None
    assert select.reject_reason(europe, allow=select.keyword_tokens("world map")) is None
    assert select.reject_reason(europe, allow=select.keyword_tokens("apple")) == "blocklist"
    assert select.reject_reason(cand(extra={"description": "Screenshot of an app"}), allow=frozenset({"screenshot"})) is None
    assert select.reject_reason(cand(title="gun shop"), allow=frozenset({"gun"})) == "blocklist"  # UNSAFE is never exempted
    beer = cand(title="A glass of beer", tags=["beer"])
    assert select.reject_reason(beer) is None and select.reject_reason(beer, style="neutral") is None
    assert select.reject_reason(beer, style="kid") == "blocklist"
    assert select.reject_reason(beer, style="kid", allow=frozenset({"beer", "glass"})) == "blocklist"  # KID_UNSAFE is never exempted
    assert [c.ref for c in select.rank([europe], "world map", allow=select.keyword_tokens("world map"))] == ["1"]
    assert select.rank([europe], "world map") == []  # without allow the handler's exemption is not applied
    assert select.rank([beer], "beer", allow=frozenset({"beer"}), style="kid") == [] and len(select.rank([beer], "beer", allow=frozenset({"beer"}))) == 1


BASE = dict(title="x", tags=[], license="CC BY-SA 2.0", width=600, height=550)  # scores exactly 1 (licence) for "apple"


def test_score_description_or_object_name_hit_adds_one_capped():
    assert select.score(cand(**BASE), "apple") == 1
    assert select.score(cand(**BASE, extra={"description": "A red apple on a table"}), "apple") == 2
    assert select.score(cand(**BASE, extra={"object_name": "Red apple"}), "apple") == 2
    # several tokens in the description still add only one point; title/tags hits stay capped at 3 on their own
    assert select.score(cand(**BASE, extra={"description": "red apple tree orchard"}), "red apple tree orchard") == 2
    assert select.score(cand(**BASE, extra={"description": "A red pear"}), "apple") == 1
    assert select.score(cand(**BASE, extra={"description": "Apples in a bowl"}), "apple") == 2  # prefix match like the title


def test_score_provider_category_matches_the_round_target():
    """Openverse `category` / Pixabay `type`: +1 for the round's own kind, −1 for the other style's kind, 0 when missing or
    something else (digitized_artwork)."""
    assert select.STYLE_TARGET == {"kid": {"illustration", "vector"}, "neutral": {"photograph", "photo"}}
    photo = cand(**BASE, extra={"category": "photograph"})
    illus = cand(**BASE, extra={"category": "illustration"})
    vector = cand(**{**BASE, "provider": "pixabay", "license": "Pixabay License"}, extra={"type": "vector"})
    pix_photo = cand(**{**BASE, "provider": "pixabay", "license": "Pixabay License"}, extra={"type": "photo"})
    artwork = cand(**BASE, extra={"category": "digitized_artwork"})
    assert select.score(photo, "apple") == 2 and select.score(photo, "apple", style="neutral") == 2 and select.score(photo, "apple", style="kid") == 0
    assert select.score(illus, "apple") == 0 and select.score(illus, "apple", style="kid") == 2
    assert select.score(vector, "apple", style="kid") == 3 and select.score(vector, "apple") == 1  # permissive licence 2 ± 1
    vector_svg = cand(**{**BASE, "provider": "pixabay", "license": "Pixabay License"}, extra={"type": "vector/svg"})  # the real Pixabay value
    assert select.media_category(vector_svg) == "vector" and select.score(vector_svg, "apple", style="kid") == 3 and select.score(vector_svg, "apple") == 1
    assert select.score(pix_photo, "apple") == 3 and select.score(pix_photo, "apple", style="kid") == 1
    assert select.score(artwork, "apple") == 1 and select.score(artwork, "apple", style="kid") == 1
    assert select.score(cand(**BASE, extra={"category": None}), "apple") == 1
    assert select.media_category(cand(extra={"category": " Illustration "})) == "illustration" and select.media_category(cand()) is None


def test_score_people_words_cost_two_only_in_the_kid_style():
    for text in ("Portrait of a man", "Selfie at the beach", "Close-up of a face", "people in a park", "Girl with apple"):
        c = cand(**{**BASE, "title": text})
        assert select.score(c, "zzz") == 1 and select.score(c, "zzz", style="neutral") == 1, text
        assert select.score(c, "zzz", style="kid") == -1, text
    tagged = cand(**{**BASE, "tags": ["woman", "kitchen"]})
    assert select.score(tagged, "zzz", style="kid") == -1 and select.score(tagged, "zzz") == 1
    assert select.score(cand(**{**BASE, "title": "Manual gearbox"}), "zzz", style="kid") == 1  # word boundaries: man ≠ manual


def test_score_signage_words_cost_one_in_every_style():
    for text in ("Stop sign", "Street signs", "Infographic about apples", "Banner at the fair", "Caption contest", "Label on a jar"):
        c = cand(**{**BASE, "title": text})
        assert select.score(c, "zzz") == 0 and select.score(c, "zzz", style="kid") == 0, text
    assert select.score(cand(**{**BASE, "tags": ["typography"]}), "zzz") == 0
    assert select.score(cand(**{**BASE, "title": "Signature dish"}), "zzz") == 1  # sign ≠ signature


def test_score_portrait_orientation_costs_one():
    assert select.score(cand(**{**BASE, "width": 500, "height": 600}), "apple") == 0  # 0.83: taller than wide
    assert select.score(cand(**{**BASE, "width": 600, "height": 600}), "apple") == 1  # exactly 1.0 is not portrait
    assert select.score(cand(**{**BASE, "width": 800, "height": 1000}), "apple") == 1  # +1 width ≥ 800, −1 portrait
    assert select.score(cand(**{**BASE, "width": None, "height": None}), "apple") == 1  # unknown size: no orientation signal


def test_rank_orders_by_the_new_signals_too():
    tall = cand(ref="t", title="Red apple", license="CC0", width=500, height=700, image_url="https://x.example/t.jpg")  # 1+3−1 = 3
    wide = cand(ref="w", title="Red apple", license="CC0", width=800, height=500, image_url="https://x.example/w.jpg")  # 1+3+1+1 = 6
    face = cand(ref="f", title="Red apple portrait", license="CC0", width=800, height=500, image_url="https://x.example/f.jpg")  # 6 neutral, 4 kid
    ranked = select.rank([tall, face, wide], "apple")
    assert [c.ref for c in ranked] == ["f", "w", "t"] and [c.extra["score"] for c in ranked] == [6, 6, 3]  # ties keep provider order
    ranked_kid = select.rank([tall, face, wide], "apple", style="kid")
    assert [c.ref for c in ranked_kid] == ["w", "f", "t"] and [c.extra["score"] for c in ranked_kid] == [6, 4, 3]
