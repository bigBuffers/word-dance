"""SVG sanitiser for Claude-drawn concept cards (DESIGN §9, CLAUDE_INTEGRATION §6.7).

:func:`clean` parses with ``defusedxml`` (DTD / entities / external references forbidden), requires an
``{http://www.w3.org/2000/svg}svg`` root, keeps only allow-listed elements and attributes, drops ``on*``
handlers, ``href`` / ``xlink:href``, ``style`` containing ``url(``, ``<script>``, ``<image>``, ``<foreignObject>``,
``<use>`` (and anything else outside the list), allows ``url(#local)`` paint references only, enforces a
``viewBox`` (the root's own when valid, else ``0 0 800 500``), drops ``width``/``height`` on the root and
re-serialises by hand so nothing unexpected can survive. Input and output are capped at 60 KB.
"""

from __future__ import annotations

import re
from typing import Iterator
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
MAX_BYTES = 60_000
MAX_ELEMENTS = 5000
MAX_DEPTH = 64
DEFAULT_VIEWBOX = "0 0 800 500"

ALLOWED_ELEMENTS = frozenset(
    {"svg", "g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "tspan", "defs", "linearGradient", "radialGradient", "stop", "title", "desc"}
)
TEXT_ELEMENTS = frozenset({"text", "tspan", "title", "desc"})

ALLOWED_ATTRS = frozenset(
    {
        "id", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "fr", "dx", "dy", "d", "points",
        "width", "height", "viewBox", "preserveAspectRatio", "version", "xmlns",
        "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
        "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "stroke-miterlimit", "opacity", "transform",
        "color", "display", "visibility", "paint-order", "vector-effect", "shape-rendering", "text-rendering",
        "font-size", "font-family", "font-weight", "font-style", "font-variant", "text-anchor", "dominant-baseline",
        "alignment-baseline", "letter-spacing", "word-spacing", "text-decoration", "textLength", "lengthAdjust", "rotate",
        "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform", "spreadMethod", "style", "lang", "role",
    }
)
URL_REF_ATTRS = frozenset({"fill", "stroke"})
LOCAL_URL_RE = re.compile(r"^\s*url\(\s*['\"]?#[A-Za-z_][\w.:-]*['\"]?\s*\)\s*(?:[A-Za-z#][\w#(),.\s%-]*)?$")
DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>\[]*(\[[^\]]*\])?\s*>", re.IGNORECASE)
ENTITY_RE = re.compile(r"<!ENTITY", re.IGNORECASE)
VIEWBOX_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)\s*$")
XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
DANGEROUS_VALUE_RE = re.compile(r"javascript:|data:|vbscript:|expression\s*\(|@import|url\s*\(", re.IGNORECASE)


class SvgRejected(ValueError):
    """The SVG cannot be made safe (not SVG, entities, too large, parse error)."""


def _split_tag(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


def _parse(svg: str) -> ET.Element:
    text = svg.lstrip("﻿").strip()
    if ENTITY_RE.search(text):
        raise SvgRejected("entity declarations are not allowed")
    text = DOCTYPE_RE.sub("", text)
    text = XML_DECL_RE.sub("", text).strip()
    if not text:
        raise SvgRejected("empty document")
    try:
        root = DET.fromstring(text, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ET.ParseError, ValueError, SyntaxError) as e:
        raise SvgRejected(f"not well-formed XML: {e}") from e
    if root is None or _split_tag(root.tag) != (SVG_NS, "svg"):
        raise SvgRejected("root element is not <svg xmlns='http://www.w3.org/2000/svg'>")
    return root


def valid_viewbox(value: str | None) -> str | None:
    """``'minx miny w h'`` normalised when the four numbers are usable (w, h > 0), else None."""
    if not value:
        return None
    m = VIEWBOX_RE.match(value)
    if not m:
        return None
    minx, miny, w, h = (float(x) for x in m.groups())
    if w <= 0 or h <= 0 or w > 100_000 or h > 100_000:
        return None

    def fmt(v: float) -> str:
        return str(int(v)) if float(v).is_integer() else f"{v:g}"

    return f"{fmt(minx)} {fmt(miny)} {fmt(w)} {fmt(h)}"


def viewbox_size(svg: str) -> tuple[int, int]:
    """``(width, height)`` of the root ``viewBox`` of a cleaned SVG (``(800, 500)`` when absent)."""
    m = re.search(r'viewBox="([^"]*)"', svg)
    vb = valid_viewbox(m.group(1)) if m else None
    if not vb:
        return 800, 500
    _, _, w, h = vb.split()
    return int(round(float(w))), int(round(float(h)))


def _clean_attrs(local: str, attrib: dict[str, str], *, is_root: bool) -> list[tuple[str, str]]:
    kept: list[tuple[str, str]] = []
    for raw_name, value in attrib.items():
        ns, name = _split_tag(raw_name)
        if ns and ns not in ("", SVG_NS):
            continue  # xlink:href, xml:*, foreign namespaces
        lname = name.lower()
        if lname.startswith("on") or lname in ("href", "xlink:href", "xmlns:xlink"):
            continue
        if name not in ALLOWED_ATTRS:
            continue
        v = str(value).strip()
        if is_root and name in ("width", "height", "viewBox", "xmlns", "version"):
            continue  # set explicitly below
        if name == "style":
            if DANGEROUS_VALUE_RE.search(v):
                continue
        elif name in URL_REF_ATTRS and "url(" in v.lower():
            if not LOCAL_URL_RE.match(v):
                continue
        elif DANGEROUS_VALUE_RE.search(v):
            continue
        if len(v) > 20_000:
            continue
        kept.append((name, v))
    return kept


def _serialise(el: ET.Element, out: list[str], counter: list[int], *, in_text: bool, is_root: bool = False, depth: int = 0) -> None:
    ns, local = _split_tag(el.tag)
    if ns != SVG_NS or local not in ALLOWED_ELEMENTS:
        return  # dropped with its subtree (tail handled by the caller)
    if depth > MAX_DEPTH:
        raise SvgRejected(f"elements nested deeper than {MAX_DEPTH}")
    counter[0] += 1
    if counter[0] > MAX_ELEMENTS:
        raise SvgRejected(f"more than {MAX_ELEMENTS} elements")
    attrs = _clean_attrs(local, dict(el.attrib), is_root=is_root)
    if is_root:
        vb = valid_viewbox(el.attrib.get("viewBox")) or DEFAULT_VIEWBOX
        attrs = [("xmlns", SVG_NS), ("viewBox", vb), *attrs]
    text_mode = in_text or local in TEXT_ELEMENTS
    out.append(f"<{local}")
    for name, value in attrs:
        out.append(f" {name}={quoteattr(value)}")
    children = list(el)
    text = el.text if text_mode and el.text else ""
    if not children and not text:
        out.append("/>")
        return
    out.append(">")
    if text:
        out.append(escape(text))
    for child in children:
        _serialise(child, out, counter, in_text=text_mode, depth=depth + 1)
        if text_mode and child.tail:
            out.append(escape(child.tail))
    out.append(f"</{local}>")


def clean(svg: str) -> str:
    """Return a safe, re-serialised SVG string or raise :class:`SvgRejected`."""
    if not isinstance(svg, str):
        raise SvgRejected("svg must be a string")
    if len(svg.encode("utf-8")) > MAX_BYTES:
        raise SvgRejected(f"svg larger than {MAX_BYTES} bytes")
    root = _parse(svg)
    out: list[str] = []
    _serialise(root, out, [0], in_text=False, is_root=True)
    result = "".join(out)
    if len(result.encode("utf-8")) > MAX_BYTES:
        raise SvgRejected(f"svg larger than {MAX_BYTES} bytes after cleaning")
    return result


def iter_elements(svg: str) -> Iterator[str]:
    """Local names of the elements of a cleaned SVG, in document order (test helper)."""
    for m in re.finditer(r"<([A-Za-z][\w:-]*)", svg):
        yield m.group(1)
