"""SVG sanitiser for Claude-drawn concept cards (DESIGN §9, CLAUDE_INTEGRATION §6.7).

:func:`clean` parses with ``defusedxml`` (DTD / entities / external references forbidden), requires an
``{http://www.w3.org/2000/svg}svg`` root, keeps only allow-listed elements and attributes, drops ``on*``
handlers, ``href`` / ``xlink:href``, ``style`` containing ``url(``, ``<script>``, ``<image>``, ``<foreignObject>``,
``<use>`` (and anything else outside the list), allows ``url(#local)`` paint references only, enforces a
``viewBox`` (the root's own when valid, else ``0 0 800 500``), drops ``width``/``height`` on the root and
re-serialises by hand so nothing unexpected can survive. Input and output are capped at 60 KB.

Two repairs and two options (design/images/SYNTHESIS.md §3.1.4, PLAN §5.1 C3; docs/MEMORY_CARDS_DESIGN.md §3.1):

* a bare ``&`` — anything but the five XML entities and a numeric reference — is rewritten to ``&amp;`` before the
  parse (:data:`BARE_AMP_RE`, applied by :func:`repair_bare_ampersands` outside ``<![CDATA[…]]>`` sections, where a
  bare ``&`` is already legal character data); the model writes ``A & B`` in titles and ``url(#a&b)`` in attributes
  and the parser used to reject the whole drawing (4 of 34 live calls). ``<!ENTITY`` declarations are still rejected
  first, so the repair never lets an entity declaration through, and ``&nbsp;`` becomes the literal text ``&nbsp;``
  instead of a rejection;
* ``clean(svg, allow_text=False)`` drops ``<text>`` / ``<tspan>`` with their subtrees (``<title>`` / ``<desc>`` stay):
  the store calls it that way for every Claude drawing, so "the picture carries no text" is guaranteed by code, not by
  the prompt (``word_images.text_free = 1``);
* ``clean(svg, effects=True)`` additionally keeps what a 记忆图卡 is painted with — :data:`EFFECT_ELEMENTS` (``filter`` with
  its two primitives ``feGaussianBlur`` / ``feDropShadow``, and ``clipPath``) and :data:`EFFECT_ATTRS` — and nothing else of
  SVG's filter vocabulary: ``feImage`` loads a URL, the other primitives and ``mask`` / ``pattern`` / ``use`` are not needed and
  stay dropped. The two attributes that reference another element, ``filter`` and ``clip-path``, are held to :data:`EFFECT_REF_RE`:
  ``none`` or exactly ONE ``url(#local-id)`` — stricter than the paint rule of ``fill`` / ``stroke``, because a filter value is
  a *list* (``url(#a) url(other.svg#b)`` is valid CSS there, while a second ``url()`` after a paint is not) and neither a
  CSS filter function nor a basic shape is part of the card contract. Two more rules of this mode keep that true one
  attribute further: a card has NO ``style`` attribute — every one is dropped, not only those with ``url(`` (CSS says
  ``filter:blur(…)``, ``clip-path:circle(…)``, ``image-set('https://…')`` there, past both rules and past the blur budget
  of ``memo.check_structure``) — and no attribute value with a backslash survives: ``u\\72l(#g)`` is ``url(#g)`` to a
  browser (a CSS escape; it paints the gradient) and to none of the patterns here. ``href`` / ``xlink:href`` are dropped on
  these elements like on every other (a ``<filter href>`` would inherit from another document), so a cleaned card
  references nothing outside itself. Only :func:`wd.images.store.prepare_memo` (the offline cards of ``wd images-import``)
  and the studio's validator pass the flag; every other caller — the online ``generate_svg`` drawings — keeps the output it
  had, byte for byte (a plain ``style`` and an escaped paint included: those drawings are shown through ``<img>`` under the
  media route's CSP, and changing what they get would be a change of its own);
* :func:`with_label` inserts the implicit AIGC marker ``<desc id="aigc-label">…</desc>`` right after the root's opening
  tag; a model-supplied ``id="aigc-label"`` is dropped by the attribute filter, so a labelled file carries exactly one.
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
# clean(effects=True) only (module docstring): the blur / drop-shadow / clipping a 记忆图卡 uses. The lists are the whole
# extension — an element or attribute that is not named here is dropped exactly as without the flag.
EFFECT_ELEMENTS = frozenset({"filter", "feGaussianBlur", "feDropShadow", "clipPath"})
EFFECT_ATTRS = frozenset({"filter", "clip-path", "stdDeviation", "in", "result", "clipPathUnits", "filterUnits", "flood-color", "flood-opacity"})
EFFECT_REF_ATTRS = frozenset({"filter", "clip-path"})
# `none`, or one reference to an id of the same file with matching (or no) quotes — no list, no fallback, no function
EFFECT_REF_RE = re.compile(r"""^(?:none|url\(\s*(?:#[A-Za-z_][\w.:-]*|'#[A-Za-z_][\w.:-]*'|"#[A-Za-z_][\w.:-]*")\s*\))$""")
DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>\[]*(\[[^\]]*\])?\s*>", re.IGNORECASE)
ENTITY_RE = re.compile(r"<!ENTITY", re.IGNORECASE)
VIEWBOX_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)\s*$")
XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
DANGEROUS_VALUE_RE = re.compile(r"javascript:|data:|vbscript:|expression\s*\(|@import|url\s*\(", re.IGNORECASE)
# a `&` that does not start one of the five XML entities or a numeric character reference (HTML names such as &nbsp; are
# NOT XML and would still be rejected by the parser, so they are escaped like any other bare ampersand)
BARE_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")
CDATA_RE = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)  # left untouched by the repair: `&` is plain character data inside
LABEL_ID = "aigc-label"  # the id of the <desc> with_label() inserts; never accepted from the model (see _clean_attrs)
ROOT_TAG_RE = re.compile(r"<svg\b[^>]*>")  # a clean() output: attribute values are quoteattr()-escaped, so `>` ends the tag


class SvgRejected(ValueError):
    """The SVG cannot be made safe (not SVG, entities, too large, parse error)."""


def _split_tag(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


def _split_cdata(text: str) -> list[tuple[str, bool]]:
    """``text`` cut at ``<![CDATA[…]]>`` boundaries (:data:`CDATA_RE`) into ``(segment, is_cdata)`` pieces — the one split
    the repair and its count share, so the handler's ``svg_repaired`` number is exactly what the repair touched."""
    parts: list[tuple[str, bool]] = []
    pos = 0
    for m in CDATA_RE.finditer(text):
        parts.append((text[pos : m.start()], False))
        parts.append((m.group(0), True))
        pos = m.end()
    parts.append((text[pos:], False))
    return parts


def repair_bare_ampersands(text: str) -> str:
    """:data:`BARE_AMP_RE` → ``&amp;`` everywhere except inside ``<![CDATA[…]]>`` sections (:data:`CDATA_RE`): there a bare
    ``&`` is legal as it stands, the parser hands it over as text and the serialiser escapes it exactly once — repairing it
    too would turn ``a & b`` into the literal ``a &amp; b``."""
    return "".join(segment if cdata else BARE_AMP_RE.sub("&amp;", segment) for segment, cdata in _split_cdata(text))


def count_bare_ampersands(text: str) -> int:
    """How many ``&`` :func:`repair_bare_ampersands` rewrites in ``text`` — bare ampersands outside CDATA sections only, so a
    ``<![CDATA[a & b]]>`` the repair deliberately leaves alone is never reported as repaired (``ai.svg`` logs this number
    as ``svg_repaired``; a plain ``BARE_AMP_RE.findall`` over-counted it)."""
    return sum(len(BARE_AMP_RE.findall(segment)) for segment, cdata in _split_cdata(text) if not cdata)


def _parse(svg: str) -> ET.Element:
    text = svg.lstrip("﻿").strip()
    if ENTITY_RE.search(text):
        raise SvgRejected("entity declarations are not allowed")
    text = DOCTYPE_RE.sub("", text)
    text = XML_DECL_RE.sub("", text).strip()
    if not text:
        raise SvgRejected("empty document")
    text = repair_bare_ampersands(text)  # after the entity check (never repairs a declaration), before the parse
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


def _clean_attrs(local: str, attrib: dict[str, str], *, is_root: bool, effects: bool = False) -> list[tuple[str, str]]:
    kept: list[tuple[str, str]] = []
    for raw_name, value in attrib.items():
        ns, name = _split_tag(raw_name)
        if ns and ns not in ("", SVG_NS):
            continue  # xlink:href, xml:*, foreign namespaces
        lname = name.lower()
        if lname.startswith("on") or lname in ("href", "xlink:href", "xmlns:xlink"):
            continue
        if name not in ALLOWED_ATTRS and not (effects and name in EFFECT_ATTRS):
            continue
        v = str(value).strip()
        if is_root and name in ("width", "height", "viewBox", "xmlns", "version"):
            continue  # set explicitly below
        if name == "id" and v == LABEL_ID:
            continue  # the AIGC marker id is ours alone (with_label); a model that writes it must not pass as labelled
        if effects and "\\" in v:
            continue  # a CSS escape: `u\72l(…)` IS url(…) to a browser and no pattern below reads it that way — a card's numbers, colours, ids and path data need none
        if name == "style":
            if effects or DANGEROUS_VALUE_RE.search(v):
                continue  # a card carries no CSS at all: `style` would say filter:blur(…) / clip-path:circle(…) / image-set('https://…') past the two rules below
        elif effects and name in EFFECT_REF_ATTRS:
            if not EFFECT_REF_RE.match(v):
                continue  # anything but `none` / one url(#local-id): an external reference, a list, a CSS function
        elif name in URL_REF_ATTRS and "url(" in v.lower():
            if not LOCAL_URL_RE.match(v):
                continue
        elif DANGEROUS_VALUE_RE.search(v):
            continue
        if len(v) > 20_000:
            continue
        kept.append((name, v))
    return kept


def _serialise(el: ET.Element, out: list[str], counter: list[int], *, in_text: bool, is_root: bool = False, depth: int = 0, allow_text: bool = True, effects: bool = False) -> None:
    ns, local = _split_tag(el.tag)
    allowed = local in ALLOWED_ELEMENTS or (effects and local in EFFECT_ELEMENTS)
    if ns != SVG_NS or not allowed or (not allow_text and local in ("text", "tspan")):
        return  # dropped with its subtree (tail handled by the caller)
    if depth > MAX_DEPTH:
        raise SvgRejected(f"elements nested deeper than {MAX_DEPTH}")
    counter[0] += 1
    if counter[0] > MAX_ELEMENTS:
        raise SvgRejected(f"more than {MAX_ELEMENTS} elements")
    attrs = _clean_attrs(local, dict(el.attrib), is_root=is_root, effects=effects)
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
        _serialise(child, out, counter, in_text=text_mode, depth=depth + 1, allow_text=allow_text, effects=effects)
        if text_mode and child.tail:
            out.append(escape(child.tail))
    out.append(f"</{local}>")


def clean(svg: str, *, allow_text: bool = True, effects: bool = False) -> str:
    """Return a safe, re-serialised SVG string or raise :class:`SvgRejected`.

    ``allow_text=False`` additionally drops every ``<text>`` / ``<tspan>`` subtree (``<title>`` / ``<desc>`` are kept):
    the mode :func:`wd.images.store.activate_svg` uses so that a Claude drawing never shows the headword (DESIGN §9,
    CLAUDE_INTEGRATION §6.7). The default keeps the behaviour every other caller (``images.clean_svg``) had before
    PLAN §5.1 C3: only the store's call changed.

    ``effects=True`` keeps :data:`EFFECT_ELEMENTS` and :data:`EFFECT_ATTRS` as well, with ``filter`` / ``clip-path`` limited
    to ``none`` or one ``url(#local-id)`` (:data:`EFFECT_REF_RE`), and drops every ``style`` attribute and every attribute
    value with a backslash (a CSS escape) — the 记忆图卡 mode of :func:`wd.images.store.prepare_memo`
    (docs/MEMORY_CARDS_DESIGN.md §3.1). Without the flag the output is what it was before the flag existed.
    """
    if not isinstance(svg, str):
        raise SvgRejected("svg must be a string")
    if len(svg.encode("utf-8")) > MAX_BYTES:
        raise SvgRejected(f"svg larger than {MAX_BYTES} bytes")
    root = _parse(svg)
    out: list[str] = []
    _serialise(root, out, [0], in_text=False, is_root=True, allow_text=allow_text, effects=effects)
    result = "".join(out)
    if len(result.encode("utf-8")) > MAX_BYTES:
        raise SvgRejected(f"svg larger than {MAX_BYTES} bytes after cleaning")
    return result


def with_label(cleaned: str, label: str) -> str:
    """Insert ``<desc id="aigc-label">label</desc>`` right after the root's opening tag of a :func:`clean` output.

    The implicit AIGC marker of CLAUDE_INTEGRATION §6.7 (the explicit one is the UI caption): ``<desc>`` is in the
    element allow-list, invisible when rendered, and survives a second ``clean()`` as a plain description. The output
    carries exactly one ``id="aigc-label"`` because ``_clean_attrs`` drops that id from model output. Raises
    :class:`SvgRejected` when ``cleaned`` does not start with a root tag (it was not produced by ``clean()``).
    """
    m = ROOT_TAG_RE.match(cleaned)
    if not m:
        raise SvgRejected("with_label: no <svg> root tag at the start of the document")
    desc = f'<desc id="{LABEL_ID}">{escape(" ".join(str(label).split()))}</desc>'
    tag = m.group(0)
    if tag.endswith("/>"):  # an empty root: <svg …/> → <svg …><desc …/></svg>
        return tag[:-2] + ">" + desc + "</svg>" + cleaned[m.end():]
    return tag + desc + cleaned[m.end():]


def iter_elements(svg: str) -> Iterator[str]:
    """Local names of the elements of a cleaned SVG, in document order (test helper)."""
    for m in re.finditer(r"<([A-Za-z][\w:-]*)", svg):
        yield m.group(1)
