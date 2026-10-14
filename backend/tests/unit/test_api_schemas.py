"""schemas.py: every DTO forbids extra fields, the endpoint catalogue is complete, stage mapping, key validators."""

from __future__ import annotations

import inspect

import pytest
from pydantic import BaseModel, ValidationError

from wd import schemas
from wd.schemas import ENDPOINT_MODELS, index_to_stage, stage_to_index

ALL_MODELS = [obj for _, obj in inspect.getmembers(schemas, inspect.isclass) if issubclass(obj, BaseModel) and obj is not BaseModel and obj.__module__ == schemas.__name__]


def test_every_model_forbids_extra_fields():
    assert len(ALL_MODELS) > 100
    for model in ALL_MODELS:
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_endpoint_catalogue_covers_api_md_section_2():
    # endpoint 4 (logout → 204), 52/53 (media files) have no JSON body; every other number 1..75 is present
    expected = set(range(1, 76)) - {4, 52, 53}
    assert set(ENDPOINT_MODELS) == expected
    for num, (req, resp) in ENDPOINT_MODELS.items():
        assert resp is not None and issubclass(resp, BaseModel), num
        if req is not None:
            assert issubclass(req, BaseModel), num


def test_stage_mapping_roundtrip():
    assert [stage_to_index(s) for s in ("zk", "gk", "cet4", "cet6")] == [1, 2, 3, 4]
    assert [index_to_stage(i) for i in (1, 2, 3, 4)] == ["zk", "gk", "cet4", "cet6"]
    with pytest.raises(ValueError):
        stage_to_index("cet8")
    with pytest.raises(ValueError):
        index_to_stage(5)
    assert schemas.STAGE_NAMES_ZH == {"zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}


def test_register_request_validation():
    ok = schemas.RegisterRequest(username="张三_01", password="12345678", display_name=" 小张 ", email=" a@b.cn ", invite_code="")
    assert ok.display_name == "小张" and ok.email == "a@b.cn" and ok.invite_code is None
    for bad in ({"username": "a", "password": "12345678"}, {"username": "alice", "password": "short"}, {"username": "al ice", "password": "12345678"}, {"username": "alice", "password": "12345678", "email": "nope"}, {"username": "alice", "password": "12345678", "role": "admin"}):
        with pytest.raises(ValidationError):
            schemas.RegisterRequest(**bad)


def test_onboarding_and_settings_cross_field_rules():
    schemas.OnboardingRequest(stages=["cet4", "cet6", "cet4"], current_stage="cet6", timezone="Asia/Shanghai", push_time="08:00")
    with pytest.raises(ValidationError):
        schemas.OnboardingRequest(stages=["cet4"], current_stage="cet6", timezone="Asia/Shanghai", push_time="08:00")
    with pytest.raises(ValidationError):
        schemas.OnboardingRequest(stages=[], current_stage="cet6", timezone="Asia/Shanghai", push_time="08:00")
    with pytest.raises(ValidationError):
        schemas.OnboardingRequest(stages=["cet6"], current_stage="cet6", timezone="Mars/Olympus", push_time="08:00")
    with pytest.raises(ValidationError):
        schemas.OnboardingRequest(stages=["cet6"], current_stage="cet6", timezone="Asia/Shanghai", push_time="25:00")
    schemas.SettingsUpdateRequest(push_time="23:59")
    schemas.SettingsUpdateRequest(current_stage="zk")  # stages validated against the stored list by the router
    with pytest.raises(ValidationError):
        schemas.SettingsUpdateRequest(stages=["zk"], current_stage="gk")
    with pytest.raises(ValidationError):
        schemas.SettingsUpdateRequest(daily_new_count=51)


def test_bank_patch_requires_a_key():
    schemas.BankPatchRequest(note="x")
    schemas.BankPatchRequest(attention="keep")
    schemas.BankPatchRequest(note=None)
    with pytest.raises(ValidationError):
        schemas.BankPatchRequest()
    with pytest.raises(ValidationError):
        schemas.BankPatchRequest(attention="later")


def test_grade_and_verdict_requests_validate_uuids():
    schemas.GradeRequest(client_event_id="7d8a8ad0-2c3e-4e8a-9d3a-6a2a2a1b9c11", grade="good", elapsed_ms=1200)
    with pytest.raises(ValidationError):
        schemas.GradeRequest(client_event_id="not-a-uuid", grade="good")
    with pytest.raises(ValidationError):
        schemas.GradeRequest(client_event_id="7d8a8ad0-2c3e-4e8a-9d3a-6a2a2a1b9c11", grade="perfect")
    schemas.ScreenVerdictRequest(client_event_id="7D8A8AD0-2C3E-4E8A-9D3A-6A2A2A1B9C11", word_id=1, verdict="unfamiliar")


def test_query_models():
    schemas.VocabQuery(stage="cet6", new_only=1, letter="a")
    with pytest.raises(ValidationError):
        schemas.VocabQuery(new_only=1)  # needs a specific stage
    with pytest.raises(ValidationError):
        schemas.VocabQuery(page_size=101)
    with pytest.raises(ValidationError):
        schemas.VocabQuery(letter="A")
    h = schemas.HistoryQuery.model_validate({"from": "2026-10-01", "to": "2026-10-14"})
    assert h.from_ == "2026-10-01"


def test_suggestion_payload_serialises_from_alias():
    p = schemas.SuggestionPayload.model_validate({"from": "abandonned", "to": "abandon", "note_zh": "看起来是拼写错误", "confidence": 0.93})
    dumped = p.model_dump(exclude_none=True)
    assert dumped == {"from": "abandonned", "to": "abandon", "note_zh": "看起来是拼写错误", "confidence": 0.93}


def test_dto_shapes_match_api_md_section_9():
    assert set(schemas.WordBrief.model_fields) == {"id", "lemma", "display", "kind", "phonetic", "translation_short", "stages", "stage_min", "cet6_star", "frq", "collins", "oxford", "difficulty", "is_public", "is_valid_english", "my_state", "content_state", "image_state"}
    assert set(schemas.TodayCounts.model_fields) == {"total", "done", "review", "review_done", "new", "new_done", "screen", "screen_done", "extra", "extra_done", "pending_content", "deferred_reviews"}
    assert set(schemas.Settings.model_fields) == {"timezone", "push_time", "push_enabled", "daily_new_count", "daily_screen_count", "max_reviews", "stages", "current_stage", "show_images", "zh_examples", "auto_pronounce", "accent", "email_enabled", "webhook_enabled", "webhook_url", "webhook_format", "next_push_at", "email_verified", "updated_at"}
    assert set(schemas.StudyItem.model_fields) == {"item_id", "kind", "position", "result", "skip_count", "requeue_at", "word", "mine", "content", "content_state", "content_deferred_until", "image"}
    assert set(schemas.TodayResponse.model_fields) == {"status", "local_date", "push_time", "next_push_at", "can_build_now", "batch", "streak_days", "goal_met", "added", "previous_open_batch", "suggestions_open"}
    assert set(schemas.GradeResponse.model_fields) == {"item", "mine", "next_due_zh", "mastery_suggested", "today", "duplicate", "study_item"}
    assert "confusables" in schemas.WordDetailWord.model_fields and "confusables" in schemas.StudyItemWord.model_fields
    assert set(schemas.AdminOverviewWords.model_fields) == {"total", "with_content", "with_photo", "with_claude_svg", "card_only", "user_added", "pending_validation"}
