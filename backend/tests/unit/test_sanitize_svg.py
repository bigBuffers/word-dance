"""images/sanitize_svg.py: the allow-list sanitiser for Claude-drawn SVGs (DESIGN §9, CLAUDE_INTEGRATION §6.7)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from wd.images import sanitize_svg as s

# scratchpad/probe/abandon.svg — the verified Claude output, embedded verbatim (TASKS WP6: "valid probe abandon.svg passes")
ABANDON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#f2c9a0"/><stop offset="1" stop-color="#fbe8d0"/></linearGradient></defs>'
    '<rect width="640" height="360" fill="url(#sky)"/><circle cx="500" cy="95" r="45" fill="#fff3dc"/>'
    '<path d="M0 270 Q160 240 320 262 T640 255 V360 H0Z" fill="#c9b28f"/><rect x="0" y="285" width="640" height="75" fill="#a8916c"/>'
    '<path d="M0 300 H640 V360 H0Z" fill="#8f7a58"/><rect x="380" y="170" width="150" height="110" fill="#8b7f8f"/>'
    '<path d="M365 175 L455 105 L545 175Z" fill="#5f5565"/><rect x="480" y="120" width="22" height="45" fill="#6e6373"/>'
    '<rect x="398" y="195" width="30" height="34" fill="#3b3442"/><rect x="480" y="195" width="30" height="34" fill="#3b3442"/>'
    '<path d="M480 195 L510 229" stroke="#8b7f8f" stroke-width="3"/><rect x="437" y="298" width="0" height="0"/>'
    '<rect x="437" y="225" width="36" height="55" fill="#3b3442"/><path d="M437 225 L455 215 L473 225" fill="none" stroke="#6e6373" stroke-width="3"/>'
    '<rect x="408" y="150" width="14" height="12" fill="#3b3442"/><path d="M370 175 L420 205" stroke="#5f5565" stroke-width="0"/>'
    '<path d="M455 105 L520 160 L500 165Z" fill="#6e6373" opacity=".4"/><path d="M385 280 q-5 -25 5 -40 q4 20 12 40z" fill="#6f8f5f"/>'
    '<path d="M515 280 q10 -20 0 -38 q-10 18 -6 38z" fill="#7fa06c"/><path d="M360 285 q10 -30 18 0z" fill="#6f8f5f"/>'
    '<path d="M100 140 q15 -10 30 0 q15 -8 28 2" fill="none" stroke="#7a6a68" stroke-width="3" stroke-linecap="round"/>'
    '<path d="M200 90 q10 -8 20 0 q10 -6 20 1" fill="none" stroke="#7a6a68" stroke-width="3" stroke-linecap="round"/>'
    '<rect x="230" y="262" width="52" height="38" rx="5" fill="#c2553f"/><path d="M244 262 v-8 h24 v8" fill="none" stroke="#7b2f22" stroke-width="4"/>'
    '<rect x="230" y="276" width="52" height="4" fill="#7b2f22"/><rect x="252" y="272" width="8" height="10" fill="#e8b04a"/>'
    '<ellipse cx="256" cy="304" rx="34" ry="5" fill="#000" opacity=".15"/><circle cx="130" cy="213" r="14" fill="#3b3442"/>'
    '<path d="M118 230 h24 l6 50 h-36z" fill="#4a7c8c"/><path d="M122 280 l-6 26 h14 l4 -26z M136 280 l8 24 h12 l-8 -24z" fill="#3b3442"/>'
    '<path d="M120 235 l-14 30" stroke="#4a7c8c" stroke-width="7" stroke-linecap="round"/><path d="M142 235 l12 30" stroke="#4a7c8c" stroke-width="7" stroke-linecap="round"/>'
    '<path d="M60 322 h30 M30 335 h22" stroke="#6e5c40" stroke-width="3" stroke-linecap="round"/></svg>'
)

SVG_NS = "{http://www.w3.org/2000/svg}"


def tags(svg: str) -> list[str]:
    return [el.tag.replace(SVG_NS, "") for el in ET.fromstring(svg).iter()]


def test_probe_abandon_svg_passes_unchanged_in_substance():
    out = s.clean(ABANDON_SVG)
    assert out.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360">')
    assert tags(out) == tags(ABANDON_SVG)  # every element survives, in order
    assert 'fill="url(#sky)"' in out and '<linearGradient id="sky"' in out
    assert "width=" not in out.split(">", 1)[0]  # no width/height on the root
    assert s.viewbox_size(out) == (640, 360)
    assert s.clean(out) == out  # idempotent


def test_strips_script_event_handlers_and_hrefs():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 800 500" onload="alert(1)">'
        '<script>alert(2)</script><rect x="1" y="1" width="10" height="10" onclick="alert(3)" fill="red"/>'
        '<a href="https://evil.example"><circle cx="5" cy="5" r="2"/></a>'
        '<use xlink:href="#x"/><use href="data:image/svg+xml,evil"/>'
        '<text x="10" y="20" onmouseover="x()">hello <tspan fill="blue">world</tspan> again</text></svg>'
    )
    out = s.clean(svg)
    lowered = out.lower()
    assert "<script" not in lowered and "onload" not in lowered and "onclick" not in lowered and "onmouseover" not in lowered
    assert "href" not in lowered and "evil" not in lowered and "<use" not in lowered and "<a " not in lowered
    assert '<rect x="1" y="1" width="10" height="10" fill="red"/>' in out
    assert '<text x="10" y="20">hello <tspan fill="blue">world</tspan> again</text>' in out
    assert "xmlns:xlink" not in out


def test_style_url_dropped_plain_style_kept_and_paint_urls_local_only():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">'
        '<rect width="10" height="10" style="fill:url(https://evil.example/x.svg#a)"/>'
        '<rect width="10" height="10" style="fill: red; stroke: blue"/>'
        '<rect width="10" height="10" fill="url(http://evil.example/g.svg#g)"/>'
        '<rect width="10" height="10" fill="url(#g1)" stroke="url( #g2 )"/>'
        '<rect width="10" height="10" fill="javascript:alert(1)"/>'
        '<rect width="10" height="10" style="background:url(#ok)"/>'
        "</svg>"
    )
    out = s.clean(svg)
    assert "evil" not in out and "javascript" not in out
    assert 'style="fill: red; stroke: blue"' in out
    assert 'fill="url(#g1)" stroke="url( #g2 )"' in out
    assert out.count("<rect") == 6
    assert 'style="background:url(#ok)"' not in out  # style may never carry url()


def test_image_foreignobject_and_unknown_elements_are_removed_with_their_subtrees():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">'
        '<image href="https://evil.example/x.png" width="10" height="10"/>'
        '<foreignObject width="100" height="50"><div xmlns="http://www.w3.org/1999/xhtml">html<script>x</script></div></foreignObject>'
        '<filter id="f"><feGaussianBlur stdDeviation="3"/></filter>'
        '<g><circle cx="1" cy="1" r="1"/><switch><rect width="1" height="1"/></switch></g>'
        '<style>rect{fill:red}</style>'
        "</svg>"
    )
    out = s.clean(svg)
    assert tags(out) == ["svg", "g", "circle"]
    assert "html" not in out and "filter" not in out and "<style" not in out


def test_doctype_stripped_but_entities_rejected():
    plain_doctype = '<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="1" height="1"/></svg>'
    out = s.clean(plain_doctype)
    assert "DOCTYPE" not in out and "<?xml" not in out and tags(out) == ["svg", "rect"]
    xxe = '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg"><text>&xxe;</text></svg>'
    with pytest.raises(s.SvgRejected):
        s.clean(xxe)
    internal = '<!DOCTYPE svg [<!ELEMENT svg ANY>]><svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
    assert tags(s.clean(internal)) == ["svg", "rect"]


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("<html><body>hi</body></html>", id="html"),
        pytest.param('<svg viewBox="0 0 1 1"><rect/></svg>', id="no-namespace"),
        pytest.param('<svg xmlns="http://www.w3.org/2000/svg"><rect></svg>', id="malformed"),
        pytest.param("just text", id="text"),
        pytest.param('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' + "<g/>" * 5001 + "</svg>", id="too-many-elements"),
        pytest.param('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' + "<g>" * 100 + "</g>" * 100 + "</svg>", id="too-deep"),
    ],
)
def test_rejections(bad):
    with pytest.raises(s.SvgRejected):
        s.clean(bad)


def test_many_siblings_and_moderate_nesting_are_fine():
    out = s.clean('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' + '<rect width="1" height="1"/>' * 1500 + "<g>" * 30 + "</g>" * 30 + "</svg>")
    assert out.count("<rect") == 1500 and out.count("<g") == 30 and out.endswith("<g/>" + "</g>" * 29 + "</svg>")


def test_rejects_non_string_and_oversized_input():
    with pytest.raises(s.SvgRejected):
        s.clean(None)  # type: ignore[arg-type]
    big = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><desc>' + "x" * 61_000 + "</desc></svg>"
    with pytest.raises(s.SvgRejected, match="60000"):
        s.clean(big)


def test_viewbox_enforced_and_width_height_dropped():
    out = s.clean('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="1" height="1"/></svg>')
    assert out.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">')
    out = s.clean('<svg xmlns="http://www.w3.org/2000/svg" viewBox="garbage"><rect width="1" height="1"/></svg>')
    assert 'viewBox="0 0 800 500"' in out
    out = s.clean('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 500"><rect width="1" height="1"/></svg>')
    assert 'viewBox="0 0 800 500"' in out
    out = s.clean('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,400.5,250" width="400"><rect width="1" height="1"/></svg>')
    assert 'viewBox="0 0 400.5 250"' in out and s.viewbox_size(out) == (400, 250)
    assert s.viewbox_size("<svg/>") == (800, 500)
    assert s.valid_viewbox("0 0 800 500") == "0 0 800 500" and s.valid_viewbox("0 0 -1 5") is None and s.valid_viewbox(None) is None


def test_text_content_and_structure_preserved():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">\n  <title>A &amp; B</title>\n'
        '  <g transform="translate(1 2)">\n    <text x="1" y="2" font-size="40" font-family="Inter, system-ui">abandon</text>\n  </g>\n</svg>'
    )
    out = s.clean(svg)
    assert "<title>A &amp; B</title>" in out
    assert '<g transform="translate(1 2)"><text x="1" y="2" font-size="40" font-family="Inter, system-ui">abandon</text></g>' in out
    root = ET.fromstring(out)
    assert root.find(f"{SVG_NS}title").text == "A & B"
    assert "\n" not in out.replace("&#10;", "")  # whitespace between structural elements is dropped


def test_comments_and_processing_instructions_vanish():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><!-- a comment --><?pi x?><rect width="1" height="1"/></svg>'
    out = s.clean(svg)
    assert "<!--" not in out and "<?" not in out and tags(out) == ["svg", "rect"]
