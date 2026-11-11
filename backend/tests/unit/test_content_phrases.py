"""Phrase-aware example validation (ai/content.py, CLAUDE_INTEGRATION §6.4): a multi-word headword counts as used when the sentence
realises it — inflected verb, filled slots (be / one's / oneself / sb. / sth.), a word or two inside — which the literal check rejected
(the 2026-11-11 whole-library run killed 148 phrase words with 「0 usable example(s)」)."""

from __future__ import annotations

import pytest

from wd.ai import content


@pytest.mark.parametrize(
    "display, sentence",
    [
        ("go on", "He went on talking for an hour."),
        ("go on", "What is going on here?"),
        ("be good at", "She is good at math."),
        ("be good at", "They were good at singing."),
        ("be good at", "He's good at football."),
        ("be made of", "The table is made of wood."),
        ("be made up of", "Water is made up of hydrogen and oxygen."),
        ("on one's way", "I met her on my way home."),
        ("on one's way", "Tom is on his way to school."),
        ("on one's way", "We are on Tom's way now."),
        ("give sb. a hand", "Can you give me a hand with this box?"),
        ("give sb. a hand", "She gave her little brother a hand."),
        ("turn over", "Please turn the paper over."),
        ("turn over", "He turned over and went back to sleep."),
        ("think about", "I thought about it all night."),
        ("look for", "They are looking for a new house."),
        ("come from", "Where do you come from?"),
        ("do one's best", "I will do my best to help."),
        ("do one's best", "She did her best in the exam."),
        ("lose one's way", "We lost our way in the forest."),
        ("die of", "Many people died of hunger."),
        ("a lot of", "There are a lot of books here."),
        ("take off", "The plane took off at nine."),
        ("be able to", "I am able to swim."),
        ("ask for", "He asked for a glass of water."),
        ("enjoy oneself", "The children enjoyed themselves at the party."),
    ],
)
def test_phrase_realisations_match(display, sentence):
    assert content.contains_phrase(sentence, display)


@pytest.mark.parametrize(
    "display, sentence",
    [
        ("go on", "He goes to school by bus."),
        ("be good at", "The food is good."),
        ("look for", "Look at the blackboard."),
        ("turn over", "Turn left at the corner."),
        ("give sb. a hand", "My hand hurts."),
        ("on one's way", "The way is long."),
    ],
)
def test_other_sentences_do_not_match(display, sentence):
    assert not content.contains_phrase(sentence, display)


def test_single_words_have_no_phrase_pattern():
    assert content.phrase_pattern("apple") is None and not content.contains_phrase("I like apples.", "apple")


def test_library_forms_extend_the_token():
    # a verb whose forms the library knows (word_forms of its own row) is accepted in those forms even without the built-in tables
    assert content.contains_phrase("She brought up three children.", "bring up", {"bring": {"brought", "bringing", "brings"}})
    assert content.contains_phrase("He swept away the leaves.", "sweep away", {"sweep": {"swept"}})
    assert not content.contains_phrase("He swept away the leaves.", "sweep away")  # 'swept' is neither regular nor in IRREGULAR_VERBS


def test_validate_item_accepts_phrase_examples():
    word = {"lemma": "go on", "display": "go on"}
    item = {
        "word": "go on",
        "valid": True,
        "meaning_zh": "继续；发生",
        "meaning_en": "to continue; to happen",
        "examples": [
            {"en": "He went on talking for an hour.", "zh": "他继续讲了一个小时。"},
            {"en": "What is going on here?", "zh": "这里发生了什么？"},
            {"en": "Please go on with your story.", "zh": "请继续讲你的故事。"},
        ],
        "collocations": ["go on a trip"],
        "mnemonic_zh": "go（走）+ on（继续）= 继续走下去",
        "image_keywords": ["walking"],
        "image_alt_zh": "一个人继续向前走",
        "difficulty": 2,
    }
    cleaned, reason = content.validate_item(item, word, [], last_attempt=False)
    assert cleaned is not None and reason == "" and len(cleaned["examples"]) == 3
    literal_only = dict(item, examples=[{"en": "He goes to school by bus.", "zh": "他坐公交车上学。"}] * 3)
    cleaned, reason = content.validate_item(literal_only, word, [], last_attempt=False)
    assert cleaned is None and reason.startswith("retry: 0 usable")
