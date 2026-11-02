"""images/fetch.py: the SSRF guard (addresses, URL shape, DNS pinning with sni_hostname, redirects), the byte cap,
magic bytes, Pillow re-encoding (EXIF stripped, transposed, ≤ 800 px JPEG) and content-hash storage."""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import replace

import httpx
import pytest
from PIL import Image

from wd.images import fetch, store
from wd.images.fetch import FetchError, SsrfError
from wd.interfaces import Candidate

PUBLIC_IP = "93.184.216.34"
HOST = "thumb.wikimedia.org"
URL = f"https://{HOST}/wikipedia/commons/thumb/1/15/Red_Apple.jpg/800px-Red_Apple.jpg"


def jpeg_bytes(size=(640, 400), *, exif: bytes | None = None, color=(200, 60, 40)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if exif is not None:
        img.save(buf, format="JPEG", quality=85, exif=exif)
    else:
        img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def png_header_only(width: int, height: int) -> bytes:
    """A PNG signature + IHDR chunk claiming ``width × height`` (no pixel data)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk


class Chunks(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __iter__(self):
        yield from self.chunks


def client_with(handler):
    return lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(fetch, "resolve_host", lambda host: [PUBLIC_IP])


# ------------------------------------------------------------------------------------------ addresses
@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.5.5", "169.254.169.254", "100.64.0.1", "::1", "fe80::1", "fc00::1", "fd12::1",
     "224.0.0.1", "0.0.0.0", "255.255.255.255", "240.0.0.1", "::ffff:10.0.0.1", "::ffff:127.0.0.1", "64:ff9b::a00:1", "2002:0a00:0001::1", "not-an-ip"],
)
def test_private_and_special_addresses_are_rejected(ip):
    assert fetch.is_public_ip(ip) is False


@pytest.mark.parametrize("ip", [PUBLIC_IP, "151.101.1.195", "2606:4700::1111", "::ffff:93.184.216.34"])
def test_public_addresses_are_accepted(ip):
    assert fetch.is_public_ip(ip) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://thumb.wikimedia.org/x.jpg",  # http
        "https://93.184.216.34/x.jpg",  # IP literal
        "https://[2606:4700::1111]/x.jpg",
        "https://user:pw@thumb.wikimedia.org/x.jpg",
        "https://thumb.wikimedia.org:8443/x.jpg",
        "https://localhost/x.jpg",
        "https://nas.local/x.jpg",
        "https://db.internal/x.jpg",
        "https:///x.jpg",
        "ftp://thumb.wikimedia.org/x.jpg",
        "https://bad_host!/x.jpg",
        "https://thumb.wikimedia.org/a\x7f.jpg",  # DEL in the path: httpx.InvalidURL (not an HTTPError) when the request is built
        "https://thumb.wikimedia.org/x.jpg?q=\x01",  # C0 byte in the query
        "https://thumb.wikimedia.org/a\tb.jpg",
        "https://thumb.wikimedia.org:abc/x.jpg",  # urlsplit().port raises a bare ValueError
        "https://thumb.wikimedia.org:99999/x.jpg",
        "https://[abc/x.jpg",  # urlsplit itself raises ("Invalid IPv6 URL")
    ],
)
def test_validate_url_rejects(url):
    with pytest.raises(SsrfError):
        fetch.validate_url(url)


def test_malformed_urls_become_fetch_errors_before_any_request(settings, public_dns):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=jpeg_bytes(), headers={"Content-Type": "image/jpeg"})

    for url in ("https://thumb.wikimedia.org/a\x7f.jpg", "https://thumb.wikimedia.org:abc/x.jpg"):
        with pytest.raises(FetchError, match="invalid URL"):
            fetch.safe_download(url, settings, client_factory=client_with(handler))
    assert calls == []
    cand = Candidate("openverse", "3", "x", None, None, "CC0", None, "", "https://live.staticflickr.com/8035/807\x7f4168006.jpg", 800, 600, "image/jpeg")
    assert fetch.download_and_store(cand, settings, client_factory=client_with(handler)) is None  # "None on any failure" holds


def test_validate_url_accepts_and_normalises():
    host, url = fetch.validate_url("https://Thumb.Wikimedia.org/a/b.jpg?x=1#frag")
    assert host == "thumb.wikimedia.org"
    assert url == "https://thumb.wikimedia.org/a/b.jpg?x=1"
    assert fetch.validate_url("https://thumb.wikimedia.org:443/a.jpg")[0] == "thumb.wikimedia.org"


def test_pin_requires_every_record_public(monkeypatch):
    monkeypatch.setattr(fetch, "resolve_host", lambda host: ["10.0.0.1"])
    with pytest.raises(SsrfError):
        fetch.pin(URL)
    monkeypatch.setattr(fetch, "resolve_host", lambda host: [PUBLIC_IP, "10.0.0.1"])
    with pytest.raises(SsrfError):
        fetch.pin(URL)
    monkeypatch.setattr(fetch, "resolve_host", lambda host: [])
    with pytest.raises(SsrfError):
        fetch.pin(URL)
    monkeypatch.setattr(fetch, "resolve_host", lambda host: [PUBLIC_IP, "2606:4700::1111"])
    host, pinned = fetch.pin(URL)
    assert host == HOST and pinned.startswith(f"https://{PUBLIC_IP}/wikipedia/")
    monkeypatch.setattr(fetch, "resolve_host", lambda host: ["2606:4700::1111"])
    assert fetch.pin(URL)[1].startswith("https://[2606:4700::1111]/")


def test_resolve_host_uses_getaddrinfo(monkeypatch):
    import socket

    def fake_getaddrinfo(host, port, type=0):
        assert host == HOST and port == 443
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 443)), (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert fetch.resolve_host(HOST) == [PUBLIC_IP]

    def failing(host, port, type=0):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", failing)
    with pytest.raises(SsrfError):
        fetch.resolve_host(HOST)


# -------------------------------------------------------------------------------------------- download
def test_download_connects_to_the_pinned_ip_with_host_and_sni(settings, public_dns):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=jpeg_bytes(), headers={"Content-Type": "image/jpeg"})

    result = fetch.safe_download(URL, settings, client_factory=client_with(handler))
    assert result.data == jpeg_bytes() and result.content_type == "image/jpeg" and result.final_url == URL
    req = seen[0]
    assert req.url.host == PUBLIC_IP and req.url.scheme == "https"
    assert req.headers["host"] == HOST
    assert req.extensions["sni_hostname"] == HOST
    assert req.headers["user-agent"].startswith("word-Dance/")


def test_redirect_to_private_host_is_rejected(settings, monkeypatch):
    monkeypatch.setattr(fetch, "resolve_host", lambda host: [PUBLIC_IP] if host == HOST else ["10.0.0.1"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == HOST:
            return httpx.Response(302, headers={"Location": "https://internal.example.org/x.jpg"})
        return httpx.Response(200, content=jpeg_bytes(), headers={"Content-Type": "image/jpeg"})

    with pytest.raises(SsrfError):
        fetch.safe_download(URL, settings, client_factory=client_with(handler))


def test_redirect_to_http_or_ip_literal_is_rejected(settings, public_dns):
    for location in ("http://cdn.example.org/x.jpg", "https://10.0.0.1/x.jpg", "https://93.184.216.34/x.jpg"):

        def handler(request: httpx.Request, location=location) -> httpx.Response:
            return httpx.Response(302, headers={"Location": location})

        with pytest.raises(SsrfError):
            fetch.safe_download(URL, settings, client_factory=client_with(handler))


def test_public_redirects_are_followed_and_capped_at_three(settings, public_dns):
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        hops.append(host)
        if request.url.path == "/relative/next.jpg":
            assert host == HOST  # a relative Location is resolved against the original URL, still on the first host
            return httpx.Response(302, headers={"Location": "https://cdn.example.org/final.jpg"})
        if host == HOST:
            return httpx.Response(301, headers={"Location": "/relative/next.jpg"})
        return httpx.Response(200, content=jpeg_bytes(), headers={"Content-Type": "image/jpeg"})

    result = fetch.safe_download(URL, settings, client_factory=client_with(handler))
    assert result.final_url == "https://cdn.example.org/final.jpg" and hops == [HOST, HOST, "cdn.example.org"]

    def forever(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://cdn.example.org/again.jpg"})

    with pytest.raises(FetchError, match="redirects"):
        fetch.safe_download(URL, settings, client_factory=client_with(forever))

    def no_location(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    with pytest.raises(FetchError):
        fetch.safe_download(URL, settings, client_factory=client_with(no_location))


def test_default_cap_is_8_mb_and_oversized_bodies_abort(settings, public_dns):
    assert settings.image_max_bytes == 8_000_000
    small = replace(settings, image_max_bytes=20_000)
    big = jpeg_bytes((1600, 1000), color=(10, 20, 30))
    assert len(big) > 20_000

    def declared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big, headers={"Content-Type": "image/jpeg"})

    with pytest.raises(FetchError, match="cap"):
        fetch.safe_download(URL, small, client_factory=client_with(declared))

    def streamed(request: httpx.Request) -> httpx.Response:  # no Content-Length: the streaming counter must abort
        return httpx.Response(200, stream=Chunks([big[i : i + 4096] for i in range(0, len(big), 4096)]), headers={"Content-Type": "image/jpeg"})

    with pytest.raises(FetchError, match="cap"):
        fetch.safe_download(URL, small, client_factory=client_with(streamed))

    def under(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=Chunks([jpeg_bytes()]), headers={"Content-Type": "image/jpeg"})

    assert fetch.safe_download(URL, small, client_factory=client_with(under)).data == jpeg_bytes()


def test_wrong_content_type_status_and_magic_bytes(settings, public_dns):
    cases = [
        (200, {"Content-Type": "text/html"}, b"<html>oops</html>", "Content-Type"),
        (200, {"Content-Type": "image/gif"}, b"GIF89a" + b"\x00" * 100, "magic"),
        (200, {"Content-Type": "image/jpeg"}, b"<html>oops</html>", "magic"),
        (404, {"Content-Type": "image/jpeg"}, jpeg_bytes(), "HTTP 404"),
        (500, {"Content-Type": "image/jpeg"}, b"", "HTTP 500"),
    ]
    for status, headers, body, needle in cases:

        def handler(request: httpx.Request, status=status, headers=headers, body=body) -> httpx.Response:
            return httpx.Response(status, content=body, headers=headers)

        with pytest.raises(FetchError, match=needle):
            fetch.safe_download(URL, settings, client_factory=client_with(handler))


def test_network_errors_become_fetch_errors(settings, public_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(FetchError, match="ConnectTimeout"):
        fetch.safe_download(URL, settings, client_factory=client_with(handler))


def test_sniff_mime():
    assert fetch.sniff_mime(jpeg_bytes()) == "image/jpeg"
    assert fetch.sniff_mime(png_header_only(10, 10)) == "image/png"
    assert fetch.sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert fetch.sniff_mime(b"GIF89a") is None
    assert fetch.sniff_mime(b"") is None


# ------------------------------------------------------------------------------------------- normalise
def test_html_disguised_as_jpeg_passes_magic_but_fails_pillow(settings, public_dns):
    body = b"\xff\xd8\xff" + b"<html><body>not an image</body></html>" * 10

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"Content-Type": "image/jpeg"})

    download = fetch.safe_download(URL, settings, client_factory=client_with(handler))
    assert download.data == body
    with pytest.raises(FetchError, match="decode"):
        fetch.normalise_image(download.data, 800)


def test_normalise_strips_exif_transposes_and_reencodes_progressive_jpeg():
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90° CW
    exif[0x010F] = "ACME camera"
    exif[0x0131] = "word-Dance test"
    src = jpeg_bytes((640, 400), exif=exif.tobytes())
    assert dict(Image.open(io.BytesIO(src)).getexif())[0x0112] == 6  # the source really carries EXIF
    out = fetch.normalise_image(src, 800)
    assert (out.width, out.height) == (400, 640) and out.source_format == "JPEG"
    img = Image.open(io.BytesIO(out.data))
    assert img.format == "JPEG" and img.size == (400, 640) and img.mode == "RGB"
    assert dict(img.getexif()) == {} and "icc_profile" not in img.info
    assert img.info.get("progressive") in (1, True)


def test_normalise_downscales_to_the_long_edge_and_keeps_small_images():
    out = fetch.normalise_image(jpeg_bytes((1600, 1000)), 800)
    assert (out.width, out.height) == (800, 500)
    small = fetch.normalise_image(jpeg_bytes((640, 400)), 800)
    assert (small.width, small.height) == (640, 400)


def test_normalise_accepts_png_with_alpha_and_webp():
    rgba = Image.new("RGBA", (500, 400), (255, 0, 0, 0))
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    out = fetch.normalise_image(buf.getvalue(), 800)
    img = Image.open(io.BytesIO(out.data))
    assert img.mode == "RGB" and img.getpixel((10, 10)) == (255, 255, 255)  # transparent → white
    assert out.source_format == "PNG"
    wbuf = io.BytesIO()
    Image.new("RGB", (500, 400), (0, 255, 0)).save(wbuf, format="WEBP")
    assert fetch.normalise_image(wbuf.getvalue(), 800).source_format == "WEBP"


def test_normalise_rejects_other_formats_and_decompression_bombs():
    gif = io.BytesIO()
    Image.new("P", (10, 10)).save(gif, format="GIF")
    with pytest.raises(FetchError, match="unsupported"):
        fetch.normalise_image(gif.getvalue(), 800)
    assert fetch.Image.MAX_IMAGE_PIXELS == 40_000_000
    with pytest.raises(FetchError, match="decode"):
        fetch.normalise_image(png_header_only(20_000, 20_000), 800)  # 400 Mpx → DecompressionBombError
    with pytest.raises(FetchError, match="decode"):
        fetch.normalise_image(png_header_only(8_000, 8_000), 800)  # 64 Mpx → the warning is an error too


# --------------------------------------------------------------------------------------------- storage
def test_store_dedupes_by_sha_and_sets_0600(settings):
    data = fetch.normalise_image(jpeg_bytes(), 800).data
    first = store.write_bytes(settings, data, "jpg")
    second = store.write_bytes(settings, data, "jpg")
    assert first.created is True and second.created is False
    assert first.file_path == second.file_path == f"{first.sha256[:2]}/{first.sha256}.jpg"
    path = settings.images_dir / first.file_path
    assert path.is_file() and (path.stat().st_mode & 0o777) == 0o600 and path.read_bytes() == data
    assert store.list_files(settings) == [first.file_path]
    with pytest.raises(ValueError):
        store.write_bytes(settings, data, "png")


def test_download_and_store_returns_none_on_refusal_and_stores_on_success(settings, public_dns):
    cand = Candidate("wikimedia", "1", "Red Apple", None, None, "CC0", None, "https://commons.wikimedia.org/x", URL, 800, 600, "image/jpeg")

    def good(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=jpeg_bytes((1600, 1000)), headers={"Content-Type": "image/jpeg"})

    stored = fetch.download_and_store(cand, settings, client_factory=client_with(good))
    assert stored is not None and (stored.width, stored.height) == (800, 500) and stored.mime == "image/jpeg"
    assert (settings.images_dir / stored.file_path).is_file() and stored.source_url == URL

    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>", headers={"Content-Type": "text/html"})

    assert fetch.download_and_store(cand, settings, client_factory=client_with(bad)) is None
    private = Candidate("wikimedia", "2", "x", None, None, "CC0", None, "", "https://10.0.0.1/x.jpg", 800, 600, "image/jpeg")
    assert fetch.download_and_store(private, settings, client_factory=client_with(good)) is None
