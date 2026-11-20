"""services/listen.py (磨耳朵, API.md 123) on the mini seed: the speakable gloss (labels, brackets, senses, the length rule), the
spoken headword (dictionary shorthand spelled out), the one example sentence, and the playlist — today's review / new / extra
words in batch order, one row per word, without 推荐词, without the words that have left the bank (已掌握 / 已认识 / removed — by
the word's state now, not by the grade of its item), stale items hidden, nothing built and nothing written."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from wd import audio, schemas
from wd.services import bank, batches, listen

UTC = timezone.utc
TZ = "Asia/Shanghai"
NOW = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)  # 09:00 Shanghai → local date 2026-10-14
TODAY = "2026-10-14"


# ------------------------------------------------------------------------------------------- helpers
def make_user(conn: sqlite3.Connection, username: str = "alice", **cols) -> int:
    cur = conn.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES (?, 'x', 'done')", (username,))
    uid = int(cur.lastrowid)
    cols.setdefault("next_push_at", "2026-10-15T00:00:00Z")
    cols.setdefault("daily_screen_count", 0)
    names = ["user_id", *cols]
    conn.execute(f"INSERT INTO user_settings({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", (uid, *cols.values()))
    return uid


def wid(conn: sqlite3.Connection, lemma: str) -> int:
    return int(conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma.lower(),)).fetchone()[0])


def mark(conn, uid, lemma, action="unfamiliar", *, now=NOW, context="browse"):
    return bank.apply_action(conn, uid, wid(conn, lemma), action, origin=bank.origin_for_context(context), context=context, now=now, tz=TZ)


def make_learning(conn, uid, lemma, *, due_at: str = "2026-10-13T00:00:00Z") -> None:
    """A word in the 复习 queue: marked five days ago, graduated, due before today."""
    mark(conn, uid, lemma, now=NOW - timedelta(days=5))
    conn.execute(
        "UPDATE user_words SET state = 'learning', due_at = ?, interval_days = 3, ease = 2.5, repetitions = 2, step = 0 WHERE user_id = ? AND word_id = ?",
        (due_at, uid, wid(conn, lemma)),
    )


def give_content(conn, lemma: str, meaning_zh: str, examples: list) -> None:
    content = {"word": lemma, "valid": True, "meaning_zh": meaning_zh, "meaning_en": "", "examples": examples, "collocations": [], "mnemonic_zh": ""}
    cid = conn.execute(
        "INSERT INTO word_contents(word_id, version, prompt_version, model, content_json) VALUES (?, 1, 'content-v1', 'm', ?)",
        (wid(conn, lemma), json.dumps(content, ensure_ascii=False)),
    ).lastrowid
    conn.execute("UPDATE words SET active_content_id = ?, content_state = 'ready' WHERE id = ?", (cid, wid(conn, lemma)))


def grade(conn, uid, item_id: int, g: str, *, cfg) -> dict:
    return batches.grade_item(conn, uid, item_id, g, client_event_id=str(uuid.uuid4()), elapsed_ms=1500, now=NOW, cfg=cfg)


def lemmas(conn, result: dict) -> list[str]:
    return [conn.execute("SELECT lemma FROM words WHERE id = ?", (it["word_id"],)).fetchone()[0] for it in result["items"]]


@pytest.fixture
def user(seeded) -> int:
    return make_user(seeded, daily_new_count=5)


# ------------------------------------------------------------------------------------ speakable gloss
@pytest.mark.parametrize(
    "meaning, gloss",
    [
        # the four of docs/LISTEN_MODE_DESIGN.md §4.3
        ("v. 分享；共用 n. 一份；股份", "分享，共用"),
        ("adv./prep. 在船(飞机、车)上;上船(车、飞机)", "在船上，上船"),
        ("国内生产总值（gross domestic product 的缩写）", "国内生产总值"),
        ("n. 能力, 才干", "能力，才干"),
        # the content prompt's shapes (content_system.txt rule 1; fixtures/claude_content_ok.json)
        ("v. 放弃；抛弃；离弃 n. 放纵", "放弃，抛弃"),
        ("v. 去；走；离开；运转  n. 尝试", "去，走"),  # a double space before the next group
        ("v. 放弃；抛弃；n. 放纵", "放弃，抛弃"),  # a label right after the separator
        ("adj. 反常的;不正常的;变态的", "反常的，不正常的"),  # ASCII semicolons
        ("n. 月亮 v. 闲逛", "月亮，闲逛"),  # one sense per group: the group boundary is the only separator
        ("斧头（复数）", "斧头"),
        ("v. （使）结束", "结束"),
        ("n. 苹果\nv. 摘苹果", "苹果，摘苹果"),  # clean_text keeps line breaks
        # the dictionary lines of the fallback (ECDICT: `a.` / `ad.` / `vt.`, `, ` between synonyms, [tag] lines, <tags>)
        ("a. 快乐的, 幸福的, 愉快的, 恰当的", "快乐的，幸福的"),
        ("vt.& vi. 放弃, 遗弃", "放弃，遗弃"),
        ("vt.vi. (使)自动化", "自动化"),  # ECDICT's run of labels without a separator
        ("un. 旁路；支路；小路", "旁路，支路"),  # … and its rarer labels (na. / un. / pref.)
        ("n. +体育馆, 体育训练, 体育课", "体育馆，体育训练"),  # a stray symbol at the edge of a sense
        ("n. A+级；优等；上等", "优等，上等"),  # a sense endpoint 76 would refuse is dropped, the others are read
        ("a.m. 上午", "a.m. 上午"),  # an abbreviation is no label
        ("vt. 使…成为, 使(某人)高兴", "使…成为，使高兴"),
        ("[计] 可靠性", "可靠性"),
        ("a. <美>优秀的", "优秀的"),
        ("上午, 午前", "上午，午前"),  # no label at all
        ("n.苹果", "苹果"),  # no space after the label
        ("num. 八, 八个", "八，八个"),
        ("int. 喂；你好", "喂，你好"),
        ("abbr. 国内生产总值（gross domestic prod", "国内生产总值"),  # an aside cut off by the 120-char limit of meaning_zh
        ("n. 猫；猫", "猫"),  # repeats collapse
        ("n. T恤衫", "T恤衫"),  # Latin inside a sense is fine — the Chinese rule lets it through
        ("n. GDP；国内生产总值", "国内生产总值"),  # a sense without a Han character is dropped
        # labels the design's list does not name (a model writes them in the same style): any short lower-case abbreviation with its dot
        ("phr. 照顾；照料", "照顾，照料"),
        ("excl. 哎呀；天哪 quant. 许多", "哎呀，天哪"),
        ("v. 照顾 phr. 照料", "照顾，照料"),  # … which opens the next group like the known ones
        ("modal v. 能；会 n. 罐头", "能，会"),  # `modal` without a dot is cut off before `v.` and, without a Han character, dropped
        ("使 sb. 高兴", "使 sb. 高兴"),  # a headword's shorthand is no label …
        ("Mr. 先生", "Mr. 先生"),  # … nor is a capitalised abbreviation
        # a slash separates senses: the Chinese voice of `say` reads it out as 「斜杠」
        ("pron. 他/她/它的", "他，她"),
        ("vt. 使减到最少/最小, 使降到最低限度", "使减到最少，最小"),
        ("与...相连/联系", "与...相连，联系"),
        ("n. 千米／小时", "千米，小时"),  # the full-width one too (inside a sense endpoint 76 would refuse it)
        # a pair of mixed width — opened full-width and closed ASCII, or the reverse: a common slip in model-written Chinese — is one
        # aside all the same, not a cut-off one that takes the rest of its sense with it
        ("vt. 使（某人)高兴, 取悦", "使高兴，取悦"),
        ("在船(飞机、车）上;上船(车、飞机)", "在船上，上船"),
        ("v. （使)结束；完成", "结束，完成"),
        ("adj. （人)高的", "高的"),
    ],
)
def test_speakable_gloss_reads_two_senses_without_labels_or_asides(meaning: str, gloss: str):
    assert listen.speakable_gloss(meaning) == gloss
    assert audio.normalize_text(gloss, audio.ZH) == gloss  # whatever is handed out, endpoint 76 accepts
    assert "/" not in gloss and "／" not in gloss


@pytest.mark.parametrize("meaning", ["", "   ", "n.", "n. GDP", "(复数)", "adv./prep.", "phr.", "phr. v.", "…", "v. ；；", "vt.<主英>=familiarize", "n. A+级", "km/h"])
def test_speakable_gloss_is_none_when_nothing_chinese_is_left(meaning: str):
    assert listen.speakable_gloss(meaning) is None


def test_speakable_gloss_keeps_to_forty_characters():
    long_first = "一种" + "非常" * 17 + "长的东西"  # 40 characters
    assert len(long_first) == listen.GLOSS_MAX_CHARS
    assert listen.speakable_gloss(f"n. {long_first}；另一个") == long_first  # two senses would exceed the limit: the first alone
    assert listen.speakable_gloss("n. " + "长" * 45) == "长" * 40  # the first alone is still too long: cut
    assert listen.speakable_gloss("n. " + "长" * 39 + "…的东西") == "长" * 39  # … and a cut never ends on punctuation
    fits = "n. " + "短" * 19 + "；" + "句" * 20
    assert listen.speakable_gloss(fits) == "短" * 19 + "，" + "句" * 20 and len(listen.speakable_gloss(fits)) == 40


# ----------------------------------------------------------------------------------- spoken headword
@pytest.mark.parametrize(
    "display, spoken",
    [
        ("farmer", "farmer"),
        ("ice cream", "ice cream"),
        ("give sb. a hand", "give somebody a hand"),  # the two shorthand headwords of the seed
        ("talk to sb.", "talk to somebody"),
        ("take sth. away", "take something away"),
        ("make sb. do sth.", "make somebody do something"),
        ("sb's turn", "somebody's turn"),
        ("at sb.'s expense", "at somebody's expense"),
        ("in sb’s shoes", "in somebody’s shoes"),
        ("a.m.", "a.m."),  # an abbreviation is not shorthand
        ("U.S.A.", "U.S.A."),
        ("  rock 'n'   roll ", "rock 'n' roll"),
        ("café", "café"),
        ("absb. x", "absb. x"),  # `sb.` only as a word of its own
        ("50€", None),  # what the English rule of endpoint 76 refuses has no word segment
        ("你好", None),
        ("", None),
    ],
)
def test_spoken_headword_spells_out_dictionary_shorthand(display: str, spoken: str | None):
    assert listen.spoken_headword(display) == spoken


# ------------------------------------------------------------------------------------- the sentence
def test_pick_sentence_is_the_first_example_endpoint_76_can_speak():
    examples = [{"en": "bad text ✓", "zh": "坏的。"}, {"en": "  The   farmer grows rice. ", "zh": " 农民种水稻。 "}, {"en": "A farmer works hard.", "zh": "农民辛苦劳作。"}]
    assert listen.pick_sentence({"examples": examples}) == ("The farmer grows rice.", "农民种水稻。")  # normalised: the text `wd audio-prewarm` made a clip for
    assert listen.pick_sentence({"examples": [{"en": "The farmer grows rice.", "zh": "nongmin zhong shuidao"}]}) == ("The farmer grows rice.", None)  # a translation without a Han character is not spoken
    assert listen.pick_sentence({"examples": [{"en": "The farmer grows rice."}]}) == ("The farmer grows rice.", None)
    assert listen.pick_sentence({"examples": [{"en": "The car broke down.", "zh": "车坏了之后,车主把它丢弃在了高速公路上。"}]})[1] == "车坏了之后,车主把它丢弃在了高速公路上。"  # ASCII punctuation in a translation
    for content in (None, {}, {"examples": []}, {"examples": "x"}, {"examples": ["junk", {"zh": "只有中文"}, {"en": "✓"}]}):
        assert listen.pick_sentence(content) == (None, None)


# ----------------------------------------------------------------------------------------- playlist
def test_playlist_without_a_batch_is_empty_and_never_builds(seeded, user, settings):
    mark(seeded, user, "apple")
    before = seeded.total_changes
    assert listen.playlist(seeded, user, NOW, cfg=settings) == {"batch_id": None, "local_date": TODAY, "items": []}
    assert seeded.total_changes == before and seeded.execute("SELECT COUNT(*) FROM push_batches").fetchone()[0] == 0
    # yesterday's open batch is not today's list
    batches.build_batch(seeded, user, "2026-10-13", "scheduled", NOW - timedelta(days=1))
    assert listen.playlist(seeded, user, NOW, cfg=settings) == {"batch_id": None, "local_date": TODAY, "items": []}


def test_playlist_lists_todays_study_words_in_batch_order_with_what_a_voice_says(seeded, user, settings):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 2 WHERE user_id = ?", (user,))
    make_learning(conn, user, "ability")
    for lemma in ("apple", "good"):
        mark(conn, user, lemma)
    give_content(conn, "apple", "n. 苹果；苹果树", [{"en": "bad text ✓", "zh": "坏的。"}, {"en": "She eats an apple  every day.", "zh": "她每天吃一个苹果。"}])
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    rows = {r["word_id"]: r for r in batches.visible_items(conn, user, b.id)}
    assert {r["kind"] for r in rows.values()} == {"review", "new", "screen"}  # the batch has 推荐词 …
    before = conn.total_changes
    result = listen.playlist(conn, user, NOW, cfg=settings)
    assert conn.total_changes == before  # read-only
    schemas.ListenPlaylist.model_validate(result)  # exactly the fields of API.md §9
    assert (result["batch_id"], result["local_date"]) == (b.id, TODAY)
    study = [r for r in batches.visible_items(conn, user, b.id) if r["kind"] != "screen"]
    assert [it["item_id"] for it in result["items"]] == [r["id"] for r in study]  # … the playlist does not: position order, study kinds only
    assert sorted(lemmas(conn, result)) == ["ability", "apple", "good"] and all(it["done"] is False for it in result["items"])
    by_lemma = dict(zip(lemmas(conn, result), result["items"]))
    assert by_lemma["apple"] == {
        "item_id": rows[wid(conn, "apple")]["id"], "word_id": wid(conn, "apple"), "kind": "new", "assigned": False, "done": False,
        "display": "apple", "phonetic": "'æpl", "spoken_en": "apple",
        "meaning_zh": "n. 苹果；苹果树", "gloss_zh": "苹果，苹果树",  # the card's meaning, and its speakable form
        "sentence_en": "She eats an apple every day.", "sentence_zh": "她每天吃一个苹果。",  # the first example the text rule accepts
    }
    # without content: the dictionary's main sense (the line of the dominant part of speech — `good` is an adjective 94 % of the time), no sentence
    assert by_lemma["good"]["meaning_zh"] == "a. 好的, 优良的, 上等的, 愉快的, 有益的, 好心的, 慈善的, 虔诚的" and by_lemma["good"]["gloss_zh"] == "好的，优良的"
    assert (by_lemma["good"]["sentence_en"], by_lemma["good"]["sentence_zh"]) == (None, None)
    assert (by_lemma["ability"]["kind"], by_lemma["ability"]["meaning_zh"], by_lemma["ability"]["gloss_zh"]) == ("review", "n. 能力, 才干", "能力，才干")
    for it in result["items"]:  # every string handed out is one endpoint 76 accepts
        assert audio.normalize_text(it["spoken_en"]) == it["spoken_en"] and audio.normalize_text(it["gloss_zh"], audio.ZH) == it["gloss_zh"]


def test_playlist_falls_back_to_empty_strings_when_a_word_has_neither_content_nor_a_dictionary_line(seeded, user, settings):
    conn = seeded
    mark(conn, user, "apple")
    conn.execute("UPDATE words SET translation = NULL, phonetic = '', display = 'give sb. a hand' WHERE lemma = 'apple'")
    batches.build_batch(conn, user, TODAY, "manual", NOW)
    (item,) = listen.playlist(conn, user, NOW, cfg=settings)["items"]
    assert (item["meaning_zh"], item["gloss_zh"], item["phonetic"]) == ("", None, None)
    assert (item["display"], item["spoken_en"]) == ("give sb. a hand", "give somebody a hand")  # shown as written, spoken spelled out
    # content whose strings cannot be spoken: shown, and null for the voice
    give_content(conn, "apple", "n. APPLE (fruit)", [{"en": "✓ only", "zh": "只有这个"}])
    (item,) = listen.playlist(conn, user, NOW, cfg=settings)["items"]
    assert (item["meaning_zh"], item["gloss_zh"], item["sentence_en"], item["sentence_zh"]) == ("n. APPLE (fruit)", None, None, None)


def test_playlist_keeps_graded_words_and_leaves_out_the_mastered_ones(seeded, user, settings):
    conn = seeded
    for lemma in ("ability", "bank", "cat"):
        make_learning(conn, user, lemma)
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    item = {r["word_id"]: r["id"] for r in batches.visible_items(conn, user, b.id)}
    assert grade(conn, user, item[wid(conn, "ability")], "good", cfg=settings)["item"]["result"] == "good"  # a review card: final
    assert grade(conn, user, item[wid(conn, "bank")], "master", cfg=settings)["item"]["result"] == "master"
    assert grade(conn, user, item[wid(conn, "cat")], "again", cfg=settings)["item"]["result"] is None  # the 10-minute step: not done
    result = listen.playlist(conn, user, NOW, cfg=settings)
    assert {lemma: it["done"] for lemma, it in zip(lemmas(conn, result), result["items"])} == {"ability": True, "cat": False}  # today's list, not what is left of it
    assert [it["item_id"] for it in result["items"]] == sorted(it["item_id"] for it in result["items"])  # still batch order: unlike GET /api/today, graded items are not moved to the end


def test_playlist_goes_by_the_words_state_now_not_by_the_grade_of_its_item(seeded, user, settings):
    """D2 「已标「掌握」的不播」 is about the word. One marked 已掌握 on its word page, or removed from the bank, AFTER its item got its
    final grade keeps that grade (`good`), and the stale rule only looks at ungraded rows — so the playlist reads the word's state
    itself; and a word that comes back to the bank comes back to the list."""
    conn = seeded
    for lemma in ("ability", "bank", "cat", "dog"):
        make_learning(conn, user, lemma)
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    item = {r["word_id"]: r["id"] for r in batches.visible_items(conn, user, b.id)}

    def listed() -> dict[str, bool]:
        result = listen.playlist(conn, user, NOW, cfg=settings)
        return {lemma: it["done"] for lemma, it in zip(lemmas(conn, result), result["items"])}

    for lemma in ("ability", "bank"):
        assert grade(conn, user, item[wid(conn, lemma)], "good", cfg=settings)["item"]["result"] == "good"
    assert grade(conn, user, item[wid(conn, "cat")], "master", cfg=settings)["item"]["result"] == "master"
    assert listed() == {"ability": True, "bank": True, "dog": False}
    mark(conn, user, "ability", "mastered", context="bank")  # from the bank or the word page: no push item is touched
    mark(conn, user, "bank", "remove", context="bank")
    states = dict(conn.execute("SELECT w.lemma, uw.state FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ?", (user,)).fetchall())
    assert states == {"ability": "mastered", "bank": "removed", "cat": "mastered", "dog": "learning"}
    assert [r["result"] for r in batches.visible_items(conn, user, b.id)] == ["good", "good", "master", None]  # all four rows are still the batch's
    assert listed() == {"dog": False}
    mark(conn, user, "dog", "known", context="bank")  # 已认识 leaves the bank as well (an ungraded row: stale anyway)
    assert listed() == {}
    # back in the bank, back in the list: a deliberate re-add keeps the item's `master` (listed as done) …
    mark(conn, user, "cat", "unfamiliar")
    assert listed() == {"cat": True}
    # … and an undone 已掌握 has its snapshot and its grade back
    assert mark(conn, user, "ability", "restore", context="bank").state == "learning"
    assert listed() == {"ability": True, "cat": True}


def test_playlist_hides_stale_items_like_the_today_page(seeded, user, settings):
    conn = seeded
    for lemma in ("apple", "bank", "cat"):
        mark(conn, user, lemma)
    batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert sorted(lemmas(conn, listen.playlist(conn, user, NOW, cfg=settings))) == ["apple", "bank", "cat"]
    mark(conn, user, "bank", "known")  # left the bank after the build: an ungraded stale item (DESIGN §6.3)
    conn.execute("UPDATE words SET merged_into_word_id = ? WHERE lemma = 'cat'", (wid(conn, "apple"),))  # merged away
    assert lemmas(conn, listen.playlist(conn, user, NOW, cfg=settings)) == ["apple"]


def test_playlist_has_one_row_per_word(seeded, user, settings):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 1 WHERE user_id = ?", (user,))
    mark(conn, user, "apple")
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    (screen_row,) = [r for r in batches.visible_items(conn, user, b.id) if r["kind"] == "screen"]
    assert [it["kind"] for it in listen.playlist(conn, user, NOW, cfg=settings)["items"]] == ["new"]  # the 推荐词 is not listened to …
    appended = grade(conn, user, screen_row["id"], "unfamiliar", cfg=settings)["study_item"]  # … until 不熟悉 puts it in the bank: a `new` row is appended for the same word
    assert appended is not None and appended["kind"] == "new"
    result = listen.playlist(conn, user, NOW, cfg=settings)
    assert [(it["word_id"], it["kind"]) for it in result["items"]] == [(wid(conn, "apple"), "new"), (screen_row["word_id"], "new")]  # once, as the study row
    assert result["items"][1]["item_id"] == appended["item_id"] != screen_row["id"]
    # two study rows of one word (a `new` and an `extra` row can coexist: UNIQUE(batch_id, word_id, kind)): the first in batch order wins
    conn.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'extra', 99)", (b.id, wid(conn, "apple")))
    again = listen.playlist(conn, user, NOW, cfg=settings)
    assert [it["item_id"] for it in again["items"]] == [it["item_id"] for it in result["items"]]


def test_playlist_is_the_users_own_local_day(seeded, settings):
    conn = seeded
    islander = make_user(conn, "islander", timezone="Pacific/Kiritimati", daily_new_count=5)  # UTC+14
    mark(conn, islander, "apple")
    late = datetime(2026, 10, 14, 11, 0, tzinfo=UTC)  # 01:00 on the 15th in Kiritimati, still the 14th in UTC and in Shanghai
    batches.build_batch(conn, islander, "2026-10-15", "manual", late)
    result = listen.playlist(conn, islander, late, cfg=settings)
    assert result["local_date"] == "2026-10-15" and lemmas(conn, result) == ["apple"]
    assert listen.playlist(conn, islander, NOW, cfg=settings) == {"batch_id": None, "local_date": "2026-10-14", "items": []}  # 15:00 on the 14th there: that day has no batch
    bob = make_user(conn, "bob", daily_new_count=5)
    assert listen.playlist(conn, bob, late, cfg=settings) == {"batch_id": None, "local_date": "2026-10-14", "items": []}  # never another user's batch
