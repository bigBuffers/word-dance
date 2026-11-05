"""images/providers/*: request shapes (the default chain only gained ``thumbmime`` / ``maxlag=5`` / ``page_size=10`` — PLAN
§5.1 C8), legacy Wikimedia parsing (fixtures as captured), utm stripping, dedupe, the Commons ``maxlag`` 200-body → 503
mapping, the kid style (``filetype:drawing`` + ``thumbmime`` as the candidate MIME, Openverse ``category=illustration``,
Pixabay ``image_type=illustration``), Openverse rules (page_size 10, never the API thumbnail), licence normalisation,
Retry-After, the rate gate, Pixabay/Pexels parsing and the chain builder."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import httpx
import pytest

from wd import __version__
from wd.images.providers import OpenverseProvider, PexelsProvider, PixabayProvider, WikimediaProvider, base, build_chain, is_keyed, openverse, wikimedia
from wd.interfaces import Candidate, ImageProvider, ProviderError

RED_THUMB = "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/15/Red_Apple.jpg/960px-Red_Apple.jpg"


def recording_client(payload, status=200, headers=None, *, raise_exc=None):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if raise_exc is not None:
            raise raise_exc
        if isinstance(payload, (bytes, str)):
            return httpx.Response(status, content=payload, headers=headers or {})
        return httpx.Response(status, json=payload, headers=headers or {})

    return (lambda: httpx.Client(transport=httpx.MockTransport(handler))), calls


@pytest.fixture
def wm_fixture(fixtures_dir):
    return json.loads((fixtures_dir / "wikimedia_search.json").read_text(encoding="utf-8"))


@pytest.fixture
def ov_fixture(fixtures_dir):
    return json.loads((fixtures_dir / "openverse_search.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------ wikimedia
def test_wikimedia_request_shape_and_user_agent(settings, wm_fixture):
    factory, calls = recording_client(wm_fixture)
    provider = WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0))
    assert isinstance(provider, ImageProvider) and provider.name == "wikimedia"
    cands = provider.search("apple", 10)
    req = calls[0]
    assert req.method == "GET" and req.url.host == "commons.wikimedia.org" and req.url.path == "/w/api.php"
    params = dict(req.url.params)
    assert params == {
        "action": "query",
        "generator": "search",
        "gsrsearch": "apple filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime|thumbmime",
        "iiurlwidth": "800",
        "format": "json",
        "maxlag": "5",
    }
    assert "formatversion" not in params
    assert req.headers["user-agent"] == f"word-Dance/{__version__} (self-hosted vocabulary trainer; tests@example.com)"
    assert len(cands) == 2


def test_wikimedia_parses_the_legacy_fixture_as_captured(wm_fixture):
    cands = {c.ref: c for c in wikimedia.parse_search(wm_fixture)}
    assert set(cands) == {"7823406", "81528752"}
    red = cands["7823406"]
    assert red.image_url == RED_THUMB and "utm" not in red.image_url
    assert red.title == "Red Apple"
    assert red.license == "CC BY 2.0" and red.license_url == "https://creativecommons.org/licenses/by/2.0"
    assert red.creator == "Abhijit Tembhekar from Mumbai, India"
    assert red.creator_url == "https://www.flickr.com/people/24340456@N03"
    assert red.landing_url == "https://commons.wikimedia.org/wiki/File:Red_Apple.jpg"
    assert red.width == 640 and red.height == 580 and red.mime == "image/jpeg"  # no size/mime in the capture → thumb dims + extension
    assert red.extra["assessments"] == "featured|potd|poty" and red.extra["restrictions"] == ""
    assert red.extra["original_url"] == "https://upload.wikimedia.org/wikipedia/commons/1/15/Red_Apple.jpg"
    assert "featured pictures of fruit" in red.tags and "apples on white background" in red.tags
    assert red.mature is False and red.provider == "wikimedia"
    tree = cands["81528752"]
    assert tree.license == "CC0" and tree.creator == "W.carter" and tree.creator_url == "https://commons.wikimedia.org/wiki/User:W.carter"
    assert tree.image_url.startswith("https://thumb.wikimedia.org/") and "utm_" not in tree.image_url
    assert tree.extra["description"].startswith("Tree with red apples")


def test_wikimedia_dedupes_candidates_that_differ_only_in_utm_params(wm_fixture):
    data = copy.deepcopy(wm_fixture)
    page = copy.deepcopy(data["query"]["pages"]["7823406"])
    page["pageid"] = 999
    page["index"] = 3
    page["imageinfo"][0]["thumburl"] = RED_THUMB + "?utm_source=other&utm_campaign=x&utm_content=y"
    data["query"]["pages"]["999"] = page
    cands = wikimedia.parse_search(data)
    assert [c.ref for c in cands] == ["7823406", "81528752"]


def test_wikimedia_tolerates_empty_formatversion2_and_missing_imageinfo(wm_fixture):
    assert wikimedia.parse_search({}) == []
    assert wikimedia.parse_search({"batchcomplete": ""}) == []
    assert wikimedia.parse_search({"query": {"pages": {"1": {"pageid": 1, "title": "File:x.jpg"}}}}) == []
    as_list = {"query": {"pages": list(wm_fixture["query"]["pages"].values())}}
    assert len(wikimedia.parse_search(as_list)) == 2


def test_wikimedia_http_errors_become_provider_errors(settings):
    factory, _ = recording_client({"error": "rate"}, status=429, headers={"Retry-After": "30"})
    with pytest.raises(ProviderError) as e:
        WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0)).search("apple", 10)
    assert e.value.status == 429 and e.value.retry_after_s == 30
    factory, _ = recording_client("busy", status=503)
    with pytest.raises(ProviderError) as e:
        WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0)).search("apple", 10)
    assert e.value.status == 503 and e.value.retry_after_s is None
    factory, _ = recording_client("not json", status=200)
    with pytest.raises(ProviderError):
        WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0)).search("apple", 10)
    factory, _ = recording_client(None, raise_exc=httpx.ConnectError("down"))
    with pytest.raises(ProviderError) as e:
        WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0)).search("apple", 10)
    assert e.value.status is None


def test_wikimedia_maxlag_body_becomes_a_503_provider_error(settings):
    """MediaWiki answers maxlag with HTTP 200 and an error body (+ Retry-After): the provider maps it onto the 503 cooldown
    path with the header's seconds, or 30 s when the header is missing (PLAN §5.1 C8)."""
    body = {"error": {"code": "maxlag", "info": "Waiting for a database server: 6 seconds lagged.", "host": "db1", "lag": 6}, "servedby": "mw1"}
    factory, calls = recording_client(body, status=200, headers={"Retry-After": "5"})
    with pytest.raises(ProviderError) as e:
        WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0)).search("apple", 10)
    assert e.value.status == 503 and e.value.retry_after_s == 5 and "maxlag" in str(e.value) and "6 seconds lagged" in str(e.value)
    assert calls[0].url.params["maxlag"] == "5"
    factory, _ = recording_client(body, status=200)
    with pytest.raises(ProviderError) as e:
        WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0)).search("apple", 10)
    assert e.value.status == 503 and e.value.retry_after_s == wikimedia.MAXLAG_DEFAULT_RETRY_S == 30
    # any other error body is not a maxlag: no exception, simply no candidates (as before)
    factory, _ = recording_client({"error": {"code": "badvalue", "info": "x"}}, status=200)
    assert WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0)).search("apple", 10) == []
    # get_json_with_headers hands back the headers get_json drops
    factory, _ = recording_client({"ok": 1}, status=200, headers={"Retry-After": "9"})
    with factory() as client:
        data, headers = base.get_json_with_headers(client, "x", "https://example.org/")
        assert data == {"ok": 1} and headers.get("Retry-After") == "9"
        assert base.get_json(client, "x", "https://example.org/") == {"ok": 1}


def test_wikimedia_kid_style_uses_drawing_and_thumbmime_as_candidate_mime(settings):
    """The illustration round searches ``filetype:drawing``; Commons rasterises SVGs into a PNG thumb, so the candidate's
    MIME is the ``thumbmime`` (what is downloaded), not the original's ``image/svg+xml`` — which select would hard-reject."""
    from wd.images import select

    page = {
        "pageid": 4242,
        "ns": 6,
        "title": "File:Cat cartoon.svg",
        "index": 1,
        "imageinfo": [
            {
                "thumburl": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Cat_cartoon.svg/800px-Cat_cartoon.svg.png",
                "thumbwidth": 800,
                "thumbheight": 600,
                "thumbmime": "image/png",
                "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Cat_cartoon.svg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Cat_cartoon.svg",
                "width": 1200,
                "height": 900,
                "mime": "image/svg+xml",
                "extmetadata": {"LicenseShortName": {"value": "CC0"}, "Artist": {"value": "Someone"}, "Categories": {"value": "Cats in art|SVG cats"}},
            }
        ],
    }
    factory, calls = recording_client({"query": {"pages": {"4242": page}}})
    provider = WikimediaProvider(settings, client_factory=factory, gate=base.RateGate(0))
    cands = provider.search("cat", 10, style="kid")
    assert calls[0].url.params["gsrsearch"] == "cat filetype:drawing" and calls[0].url.params["iiprop"] == "url|extmetadata|size|mime|thumbmime"
    assert len(cands) == 1 and cands[0].mime == "image/png" and cands[0].image_url.endswith("800px-Cat_cartoon.svg.png")
    assert select.reject_reason(cands[0], style="kid") is None  # the png thumb passes the MIME gate
    # the neutral round keeps the bitmap filter; a candidate without thumbmime falls back to mime, then to the extension
    provider.search("cat", 10, style="neutral")
    assert calls[1].url.params["gsrsearch"] == "cat filetype:bitmap"
    provider.search("cat", 10)
    assert calls[2].url.params["gsrsearch"] == "cat filetype:bitmap"
    del page["imageinfo"][0]["thumbmime"]
    assert wikimedia.parse_search({"query": {"pages": {"4242": page}}})[0].mime == "image/svg+xml"
    del page["imageinfo"][0]["mime"]
    assert wikimedia.parse_search({"query": {"pages": {"4242": page}}})[0].mime == "image/svg+xml"  # from the original's .svg extension


def test_rate_gate_enforces_one_request_per_second():
    clock = {"t": 100.0}
    slept: list[float] = []

    def monotonic():
        return clock["t"]

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    gate = base.RateGate(1.0, monotonic=monotonic, sleep=sleep)
    assert gate.wait() == 0.0
    clock["t"] += 0.25
    assert gate.wait() == pytest.approx(0.75)
    assert slept == [pytest.approx(0.75)]
    clock["t"] += 5
    assert gate.wait() == 0.0
    shared = base.gate_for("wikimedia", 1.0)
    assert base.gate_for("wikimedia", 0.5) is shared and shared.min_interval_s == 0.5


def test_wikimedia_provider_waits_on_the_gate(settings, wm_fixture):
    factory, calls = recording_client(wm_fixture)
    waits: list[int] = []

    class Gate:
        def wait(self):
            waits.append(1)
            return 0.0

    provider = WikimediaProvider(settings, client_factory=factory, gate=Gate())  # type: ignore[arg-type]
    provider.search("apple", 10)
    provider.search("apple", 10)
    assert waits == [1, 1] and len(calls) == 2


def test_user_agent_formats(settings):
    assert base.user_agent(settings) == f"word-Dance/{__version__} (self-hosted vocabulary trainer; tests@example.com)"
    cfg = replace(settings, public_url="http://192.168.1.5:8000", contact_email="")
    assert base.user_agent(cfg) == f"word-Dance/{__version__} (self-hosted vocabulary trainer; +http://192.168.1.5:8000; admin@localhost)"


# ------------------------------------------------------------------------------------------ openverse
def test_openverse_request_shape_and_parse(settings, ov_fixture):
    factory, calls = recording_client(ov_fixture)
    provider = OpenverseProvider(settings, client_factory=factory)
    cands = provider.search("apple", 10)
    req = calls[0]
    assert req.url.host == "api.openverse.org" and req.url.path == "/v1/images/"
    assert dict(req.url.params) == {"q": "apple", "page_size": "10", "license_type": "commercial", "mature": "false"}  # no category / orientation on the default chain
    assert "authorization" not in req.headers
    assert len(cands) == 2
    first = cands[0]
    assert first.extra["category"] is None  # the capture has no category; select.score treats None as 0
    assert first.provider == "openverse" and first.ref == "abe939b0-9741-4d30-b63e-19b08b3baf71"
    assert first.image_url == "https://live.staticflickr.com/8035/8074168006_dd24e474ac_b.jpg"
    assert first.license == "CC BY 2.0" and first.license_url == "https://creativecommons.org/licenses/by/2.0/"
    assert first.creator == "Carriagehouse2011" and first.creator_url == "https://www.flickr.com/photos/87866532@N04"
    assert first.landing_url == "https://www.flickr.com/photos/87866532@N04/8074168006"
    assert first.width == 1024 and first.height == 682 and first.mime == "image/jpeg"
    assert first.tags == ["apples"] and first.mature is False and first.extra["sensitivity"] == []
    assert first.extra["attribution"].startswith('"Apples" by Carriagehouse2011 is licensed under CC BY 2.0')
    assert all(httpx.URL(c.image_url).host != "api.openverse.org" for c in cands)


def test_openverse_never_uses_the_api_thumbnail_and_truncates_to_limit(settings, ov_fixture):
    data = copy.deepcopy(ov_fixture)
    data["results"][0]["url"] = data["results"][0]["thumbnail"]  # a result whose only URL is the API thumbnail
    cands = openverse.parse_search(data)
    assert [c.ref for c in cands] == ["c4939b4c-aa73-4256-bb52-9b25962562d9"]
    assert openverse.parse_search({"results": []}) == [] and openverse.parse_search({}) == []
    factory, _ = recording_client(ov_fixture)
    assert len(OpenverseProvider(settings, client_factory=factory).search("apple", 1)) == 1


def test_openverse_skips_results_whose_url_httpx_refuses(ov_fixture):
    data = copy.deepcopy(ov_fixture)
    data["results"][0]["url"] = "https://live.staticflickr.com/8035/807\x7f4168006.jpg"  # a DEL byte: httpx.URL raises InvalidURL
    assert [c.ref for c in openverse.parse_search(data)] == ["c4939b4c-aa73-4256-bb52-9b25962562d9"]
    unusable = [{"id": "x", "url": "https://live.staticflickr.com/a\tb.jpg"}, {"id": "y", "url": "https://live.staticflickr.com:abc/b.jpg"}]
    assert openverse.parse_search({"results": unusable}) == []


def test_openverse_bearer_token_when_registered(settings, ov_fixture):
    cfg = replace(settings, openverse_client_id="cid", openverse_client_secret="sec")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/auth_tokens/token/":
            assert request.method == "POST" and b"grant_type=client_credentials" in request.content and b"client_id=cid" in request.content
            return httpx.Response(200, json={"access_token": "tok123", "expires_in": 3600})
        return httpx.Response(200, json=ov_fixture)

    openverse._token_cache.update({"token": None, "expires_at": 0.0, "client_id": None})
    provider = OpenverseProvider(cfg, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    provider.search("apple", 10)
    provider.search("apple", 10)
    token_calls = [c for c in calls if c.url.path.startswith("/v1/auth_tokens")]
    search_calls = [c for c in calls if c.url.path == "/v1/images/"]
    assert len(token_calls) == 1 and len(search_calls) == 2  # token cached
    assert all(c.headers["authorization"] == "Bearer tok123" for c in search_calls)
    openverse._token_cache.update({"token": None, "expires_at": 0.0, "client_id": None})


def test_openverse_falls_back_to_anonymous_when_the_token_request_fails(settings, ov_fixture):
    cfg = replace(settings, openverse_client_id="cid", openverse_client_secret="sec")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth_tokens/token/":
            return httpx.Response(500, text="boom")
        assert "authorization" not in request.headers
        return httpx.Response(200, json=ov_fixture)

    openverse._token_cache.update({"token": None, "expires_at": 0.0, "client_id": None})
    provider = OpenverseProvider(cfg, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(provider.search("apple", 10)) == 2


def test_openverse_page_size_follows_limit_and_category_for_kid(settings, ov_fixture):
    """``page_size = max(1, min(limit, 20))`` (the handler asks for 10 and looks at 10); the kid round adds
    ``category=illustration`` and the parser keeps the result category for the scoring signal (PLAN §5.1 C6/C8)."""
    factory, calls = recording_client(ov_fixture)
    provider = OpenverseProvider(settings, client_factory=factory)
    provider.search("apple", 10)
    provider.search("apple", 50)
    provider.search("apple", 0)
    provider.search("apple", 10, style="kid")
    provider.search("apple", 10, style="neutral")
    sizes = [c.url.params["page_size"] for c in calls]
    assert sizes == ["10", "20", "1", "10", "10"]
    assert [c.url.params.get("category") for c in calls] == [None, None, None, "illustration", None]
    assert not hasattr(openverse, "PAGE_SIZE")
    data = copy.deepcopy(ov_fixture)
    data["results"][0]["category"] = "Illustration"
    data["results"][1]["category"] = ""
    parsed = openverse.parse_search(data)
    assert parsed[0].extra["category"] == "illustration" and parsed[1].extra["category"] is None


@pytest.mark.parametrize(
    "code, version, expected",
    [("by", "2.0", "CC BY 2.0"), ("by-sa", "4.0", "CC BY-SA 4.0"), ("cc0", "1.0", "CC0 1.0"), ("cc0", None, "CC0 1.0"), ("pdm", "1.0", "Public domain"), ("by-nc", "2.0", "CC BY-NC 2.0"), (None, None, "unknown")],
)
def test_openverse_license_names(code, version, expected):
    assert base.openverse_license_name(code, version) == expected


# -------------------------------------------------------------------------------------- base helpers
@pytest.mark.parametrize(
    "name, family, allowed",
    [
        ("CC0", "cc0", True),
        ("CC0 1.0", "cc0", True),
        ("Public domain", "cc0", True),
        ("PD-US", "cc0", True),
        ("CC BY 2.0", "by", True),
        ("CC-BY-4.0", "by", True),
        ("CC BY-SA 4.0", "by-sa", True),
        ("CC BY-SA-3.0", "by-sa", True),
        ("CC BY-NC 2.0", "other", False),
        ("CC BY-NC-SA 2.0", "other", False),
        ("CC BY-ND 4.0", "other", False),
        ("GFDL", "other", False),
        ("Copyrighted free use", "other", False),
        ("Pixabay License", "permissive", True),
        ("Pexels License", "permissive", True),
        ("", "other", False),
        (None, "other", False),
    ],
)
def test_license_family_and_allow_list(name, family, allowed):
    assert base.license_family(name) == family
    assert base.license_allowed(name) is allowed


def test_strip_utm_mime_and_html_helpers():
    assert base.strip_utm(RED_THUMB + "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail") == RED_THUMB
    assert base.strip_utm("https://x.example/a.jpg?w=1&utm_x=2&h=3#f") == "https://x.example/a.jpg?w=1&h=3#f"
    assert base.strip_utm("https://x.example/a.jpg") == "https://x.example/a.jpg"
    assert base.strip_utm("") == ""
    assert base.mime_from_url("https://x/a.JPG?x=1") == "image/jpeg" and base.mime_from_url("https://x/a.png") == "image/png"
    assert base.mime_from_url("https://x/a.webp") == "image/webp" and base.mime_from_url("https://x/noext") is None and base.mime_from_url(None) is None
    assert base.mime_from_filetype("jpg") == "image/jpeg" and base.mime_from_filetype(None) is None
    artist = '<a rel="nofollow" class="external text" href="https://www.flickr.com/people/24340456@N03">Abhijit Tembhekar</a> from Mumbai, India'
    assert base.html_to_text(artist) == "Abhijit Tembhekar from Mumbai, India"
    assert base.first_href(artist) == "https://www.flickr.com/people/24340456@N03"
    assert base.first_href('<a href="//commons.wikimedia.org/wiki/User:W.carter">W.carter</a>') == "https://commons.wikimedia.org/wiki/User:W.carter"
    assert base.first_href('<a href="javascript:x()">x</a>') is None and base.first_href("plain") is None
    assert base.html_to_text("A &amp; B  <br/> C") == "A & B C" and base.html_to_text(None) == ""


def test_parse_retry_after():
    from datetime import datetime, timezone

    assert base.parse_retry_after("120") == 120
    assert base.parse_retry_after(None) is None and base.parse_retry_after("soon") is None
    now = datetime(2026, 10, 14, 8, 0, 0, tzinfo=timezone.utc)
    assert base.parse_retry_after("Wed, 14 Oct 2026 08:01:00 GMT", now=now) == 60
    assert base.parse_retry_after("Wed, 14 Oct 2026 07:00:00 GMT", now=now) == 0


# ------------------------------------------------------------------------------------- pixabay / pexels
PIXABAY = {
    "total": 1,
    "hits": [
        {
            "id": 195893,
            "pageURL": "https://pixabay.com/photos/apple-fruit-195893/",
            "type": "photo",
            "tags": "apple, fruit, red",
            "previewURL": "https://cdn.pixabay.com/photo/2013/10/15/09/12/apple-195893_150.jpg",
            "webformatURL": "https://pixabay.com/get/35bbf209e13e39d2_640.jpg",
            "largeImageURL": "https://pixabay.com/get/ed6a99fd0a76647_1280.jpg",
            "imageWidth": 4000,
            "imageHeight": 2250,
            "user_id": 48777,
            "user": "Josch13",
        }
    ],
}
PEXELS = {
    "photos": [
        {
            "id": 1510392,
            "width": 5184,
            "height": 3456,
            "url": "https://www.pexels.com/photo/red-apple-1510392/",
            "photographer": "Mali Maeder",
            "photographer_url": "https://www.pexels.com/@mali",
            "avg_color": "#8C1B22",
            "src": {"original": "https://images.pexels.com/photos/1510392/pexels-photo-1510392.jpeg", "large": "https://images.pexels.com/photos/1510392/pexels-photo-1510392.jpeg?auto=compress&cs=tinysrgb&h=650&w=940"},
            "alt": "Red apple fruit",
        }
    ],
}


def test_pixabay_request_and_parse(settings):
    cfg = replace(settings, pixabay_key="k123")
    factory, calls = recording_client(PIXABAY)
    cands = PixabayProvider(cfg, client_factory=factory).search("apple", 10)
    params = dict(calls[0].url.params)
    assert calls[0].url.host == "pixabay.com" and params["key"] == "k123" and params["q"] == "apple"
    assert params["image_type"] == "photo" and params["safesearch"] == "true" and params["per_page"] == "10" and params["min_width"] == "400"
    c = cands[0]
    assert c.provider == "pixabay" and c.ref == "195893" and c.image_url.endswith("_1280.jpg") and c.license == "Pixabay License"
    assert c.creator == "Josch13" and c.creator_url == "https://pixabay.com/users/Josch13-48777/" and c.tags == ["apple", "fruit", "red"]
    assert c.width == 4000 and c.height == 2250 and c.landing_url == "https://pixabay.com/photos/apple-fruit-195893/" and c.title == "Apple"
    with pytest.raises(ProviderError):
        PixabayProvider(settings, client_factory=factory).search("apple", 10)  # no key


def test_pixabay_image_type_follows_style(settings):
    cfg = replace(settings, pixabay_key="k123")
    factory, calls = recording_client(PIXABAY)
    provider = PixabayProvider(cfg, client_factory=factory)
    cands = provider.search("apple", 10, style="kid")
    provider.search("apple", 10, style="neutral")
    provider.search("apple", 10)
    assert [c.url.params["image_type"] for c in calls] == ["illustration", "photo", "photo"]
    assert all(c.url.params["safesearch"] == "true" for c in calls)
    assert cands[0].extra["type"] == "photo"  # hit.type stays on the candidate for select.score's category signal


def test_pexels_request_and_parse(settings):
    cfg = replace(settings, pexels_key="pk")
    factory, calls = recording_client(PEXELS)
    cands = PexelsProvider(cfg, client_factory=factory).search("apple", 5)
    req = calls[0]
    assert req.url.host == "api.pexels.com" and req.url.path == "/v1/search" and req.headers["authorization"] == "pk"
    assert dict(req.url.params) == {"query": "apple", "per_page": "5", "orientation": "landscape"}
    c = cands[0]
    assert c.provider == "pexels" and c.ref == "1510392" and c.image_url.startswith("https://images.pexels.com/photos/1510392/") and "w=940" in c.image_url
    assert c.license == "Pexels License" and c.creator == "Mali Maeder" and c.title == "Red apple fruit" and c.width == 5184
    with pytest.raises(ProviderError):
        PexelsProvider(settings, client_factory=factory).search("apple", 5)
    # the style keyword of interfaces.ImageProvider is accepted and ignored (no illustration filter; never in the kid round)
    PexelsProvider(cfg, client_factory=factory).search("apple", 5, style="kid")
    assert dict(calls[-1].url.params) == {"query": "apple", "per_page": "5", "orientation": "landscape"}


def test_every_provider_implements_the_style_keyword(settings):
    import inspect

    from wd.images.providers import PROVIDER_CLASSES

    for cls in PROVIDER_CLASSES.values():
        param = inspect.signature(cls.search).parameters["style"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default == "neutral", cls
    assert inspect.signature(ImageProvider.search).parameters["style"].default == "neutral"


def test_build_chain_respects_order_keys_and_unknown_names(settings):
    chain = build_chain(settings)
    assert [p.name for p in chain] == ["wikimedia", "openverse"]
    assert all(isinstance(p, ImageProvider) for p in chain)
    assert [p.name for p in build_chain(settings, ["openverse", "wikimedia"])] == ["openverse", "wikimedia"]
    assert [p.name for p in build_chain(settings, ["pixabay", "pexels"])] == []  # unkeyed → skipped
    keyed = replace(settings, pixabay_key="k", pexels_key="p")
    assert [p.name for p in build_chain(keyed, ["pixabay", "pexels"])] == ["pixabay", "pexels"]
    assert is_keyed("wikimedia", settings) and not is_keyed("pixabay", settings) and is_keyed("pixabay", keyed)
    with pytest.raises(ValueError):
        build_chain(settings, ["flickr"])


def test_candidate_dataclass_round_trip():
    c = Candidate("wikimedia", "1", "t", None, None, "CC0", None, "l", "https://i", 1, 2, "image/jpeg")
    assert c.tags == [] and c.mature is False and c.extra == {}
