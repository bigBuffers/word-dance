#!/usr/bin/env python3
"""build_gallery.py — the overview page of a set of memory cards: what the owner looks at before an import.

    studio/tools/build_gallery                  # studio/cards + studio/manifest.json → studio/tmp/gallery/memory-cards.html
    studio/tools/build_gallery --cards studio/tmp/batch-01/cards --manifest studio/tmp/batch-01/manifest.json \
                               --out studio/tmp/batch-01/gallery.html --title "记忆图卡 · 第一批"

Reads the manifest `wd images-import` reads (docs/MEMORY_CARDS_DESIGN.md §3.5: `cards.<lemma>.{alt_zh, hook_zh, note_zh}`)
and, for every lemma in it, `<cards dir>/<lemma>.svg` (a space in the lemma is `_` in the file name). Each card is cleaned
with the repository's sanitiser exactly as the import cleans it, so the page shows what the app would serve, and inlined:
the page is ONE self-contained file in which every card can be looked at with and without its word layer (the switch the
app's setting 「图片上显示单词」 flips). A card the manifest names but the directory lacks, or the sanitiser rejects, is
left out and reported on stderr (exit status 1).

The page is written the way a claude.ai Artifact wants it (no doctype / html / head / body of its own, web fonts from
Google Fonts) and opens as a local file in a browser just as well. The output belongs under studio/tmp/ (gitignored):
it is a render, never commit it. This tool validates nothing — that is studio/tools/check, card by card (it needs the
headword in its display form, which a manifest keyed by lemma does not carry).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent

sys.path.insert(0, str(HERE))
import check as check_tool  # noqa: E402  (load_backend: the repository's own sanitiser, no copy here; reid: one id-renaming rule for the sheet and this page)


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def inline_card(svg: str, suffix: str, label: str) -> str:
    svg = re.sub(r"<title>.*?</title>", "", svg, count=1, flags=re.S)
    svg = re.sub(r'<g id="word-art"', '<g class="wa" id="word-art"', svg, count=1)
    svg = check_tool.reid(svg, suffix)  # ten inlined cards all call their sky gradient `sky`: every id, and every url(#id) in whatever spelling, gets the card's suffix
    return svg.replace("<svg ", f'<svg class="card-svg" role="img" aria-label="{esc(label)}" ', 1)


def card_file(cards_dir: Path, lemma: str) -> Path:
    return cards_dir / f"{lemma.replace(' ', '_')}.svg"  # the import's naming rule (MEMORY_CARDS_DESIGN §3.5)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cards", default=str(STUDIO / "cards"), help="directory with <lemma>.svg (default: studio/cards)")
    ap.add_argument("--manifest", default=str(STUDIO / "manifest.json"), help="the import manifest (default: studio/manifest.json)")
    ap.add_argument("--out", default=str(STUDIO / "tmp" / "gallery" / "memory-cards.html"), help="the page to write (default: studio/tmp/gallery/memory-cards.html)")
    ap.add_argument("--title", default="记忆图卡总览", help="the page's title and headline")
    ap.add_argument("--only", nargs="+", default=[], metavar="LEMMA", help="only these lemmas of the manifest, in the manifest's order")
    a = ap.parse_args()
    cards_dir, manifest_path, out = Path(a.cards).resolve(), Path(a.manifest).resolve(), Path(a.out).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cards = manifest.get("cards") or {}
    unknown = [w for w in a.only if w not in cards]
    if unknown:
        ap.error(f"--only names lemmas the manifest does not have: {unknown}")
    san, _memo = check_tool.load_backend()
    cards_html = []
    total = 0
    skipped = 0
    for n, (lemma, cap) in enumerate(cards.items()):
        if a.only and lemma not in a.only:
            continue
        path = card_file(cards_dir, lemma)
        if not path.is_file():
            print(f"skip {lemma}: no {path}", file=sys.stderr)
            skipped += 1
            continue
        try:
            svg = san.clean(path.read_text(encoding="utf-8"), allow_text=False, effects=True)
        except san.SvgRejected as e:
            print(f"skip {lemma}: the sanitiser rejected {path.name}: {e}", file=sys.stderr)
            skipped += 1
            continue
        size =len(svg.encode("utf-8"))
        total += size
        note = f'<p class="note"><span class="tag">提醒</span>{esc(cap["note_zh"])}</p>' if cap.get("note_zh") else ""
        cards_html.append(f'''
<article class="card" data-memory="on" id="card-{n}">
  <button class="pic" type="button" aria-pressed="true" aria-label="{esc(lemma)}：点一下隐藏或显示单词">
    {inline_card(svg, f"-{n}", cap.get("alt_zh") or lemma)}
    <span class="pic-hint" aria-hidden="true">点图藏起单词</span>
  </button>
  <div class="meta">
    <div class="headword">
      <span class="word" lang="en">{esc(lemma)}</span>
      <span class="size">{size / 1024:.0f} KB</span>
    </div>
    <p class="hook"><span class="tag">记忆点</span>{esc(cap.get("hook_zh") or "")}</p>
    {note}
    <p class="scene"><span class="tag">画面</span>{esc(cap.get("alt_zh") or "")}</p>
  </div>
</article>''')
    n_cards = len(cards_html)
    page = TEMPLATE
    for k, v in {
        "{{CARDS}}": "\n".join(cards_html),
        "{{TITLE}}": esc(a.title),
        "{{N}}": str(n_cards),
        "{{AVG}}": f"{total / max(1, n_cards) / 1024:.0f}",
        "{{TOTAL_MB}}": f"{total / 1024 / 1024:.1f}",
        "{{VERSION}}": esc(str(manifest.get("prompt_version") or "")),
        "{{MODEL}}": esc(str(manifest.get("model") or "")),
    }.items():
        page = page.replace(k, v)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(out, f"{len(page.encode()) / 1024:.0f} KB", f"{n_cards} cards" + (f", {skipped} skipped" if skipped else ""))
    return 1 if skipped else 0


TEMPLATE = r'''<title>{{TITLE}}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Andika:wght@400;700&family=Noto+Serif+SC:wght@600;900&display=swap">
<style>
/* layout: one quiet column of text, then a two-up wall of pictures; the pictures are the only colour on the page */
:root {
  --bg: #eef1f5; --surface: #ffffff; --ink: #1b2740; --ink-2: #51607c; --line: #d5dbe6;
  --warm: #d8432c; --chip: #e3e8f1;
  --font-display: "Noto Serif SC", "Songti SC", "STSong", serif;
  --font-body: -apple-system, BlinkMacSystemFont, "PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
  --font-word: "Andika", "Comic Sans MS", "Arial Rounded MT Bold", sans-serif;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #121826; --surface: #1b2334; --ink: #e8ecf5; --ink-2: #a3aec5; --line: #2e3950;
  --warm: #ff7a63; --chip: #263048; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #121826; --surface: #1b2334; --ink: #e8ecf5; --ink-2: #a3aec5; --line: #2e3950;
  --warm: #ff7a63; --chip: #263048; color-scheme: dark }
* { box-sizing: border-box }
body { background: var(--bg); color: var(--ink); font: 16px/1.7 var(--font-body); }
.wrap { max-width: 1180px; margin: 0 auto; padding-block: 40px 72px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); display: flex; flex-direction: column; gap: 40px }
header.top { display: flex; flex-direction: column; gap: 14px }
header.top h1, header.top .lede { max-width: 44rem }
.eyebrow { font-size: 13px; letter-spacing: .12em; color: var(--ink-2) }
h1 { font: 900 clamp(30px, 5vw, 46px)/1.15 var(--font-display); margin: 0; text-wrap: balance }
h2 { font: 600 24px/1.3 var(--font-display); margin: 0; text-wrap: balance }
p { margin: 0 }
.lede { color: var(--ink-2); font-size: 17px }
.bar { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--bg); padding-block: 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; border-bottom: 1px solid var(--line) }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--bg) }
.seg { display: inline-flex; border: 1.5px solid var(--ink); border-radius: 999px; overflow: hidden }
.seg button { font: inherit; font-size: 14px; padding: 6px 16px; border: 0; background: transparent; color: var(--ink); cursor: pointer }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--bg) }
.seg button:focus-visible, .pic:focus-visible { outline: 3px solid var(--warm); outline-offset: 2px }
.bar .tip { font-size: 14px; color: var(--ink-2) }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 36px 28px }
@media (max-width: 860px) { .grid { grid-template-columns: minmax(0, 1fr) } }
.card { display: flex; flex-direction: column; gap: 14px; min-width: 0 }
.pic { all: unset; display: block; position: relative; cursor: pointer; border-radius: 14px; overflow: hidden; background: var(--surface); box-shadow: 0 1px 2px rgba(20, 30, 60, .12), 0 12px 28px -14px rgba(20, 30, 60, .35) }
.card-svg { display: block; width: 100%; height: auto; aspect-ratio: 16 / 10 }
.card[data-memory="off"] .wa { display: none }
.pic-hint { position: absolute; right: 10px; top: 10px; font-size: 12px; line-height: 1; padding: 6px 9px; border-radius: 999px; background: rgba(18, 24, 38, .55); color: #fff; opacity: 0; transition: opacity .15s }
.pic:hover .pic-hint, .pic:focus-visible .pic-hint { opacity: 1 }
@media (prefers-reduced-motion: reduce) { .pic-hint { transition: none } }
.meta { display: flex; flex-direction: column; gap: 8px }
.headword { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px }
.word { font: 700 34px/1.1 var(--font-word); letter-spacing: .01em }
.size { font-size: 13px; color: var(--ink-2); font-variant-numeric: tabular-nums }
.meta p { font-size: 15px; color: var(--ink-2); min-width: 0 }
.meta p.hook { color: var(--ink); font-size: 16px }
.tag { display: inline-block; font-size: 12px; line-height: 1; padding: 4px 7px; margin-right: 8px; border-radius: 4px; background: var(--chip); color: var(--ink-2); vertical-align: 2px; white-space: nowrap }
@media (max-width: 480px) { .word { font-size: 30px } }
section { display: flex; flex-direction: column; gap: 18px }
.facts li { color: var(--ink-2) }
.facts b { color: var(--ink) }
.facts { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px 28px; font-size: 15px }
.facts li { border-top: 1px solid var(--line); padding-top: 10px }
.facts b { display: block; font-variant-numeric: tabular-nums }
</style>

<div class="wrap">
  <header class="top">
    <span class="eyebrow">单词之舞 · 记忆图卡</span>
    <h1>{{TITLE}}</h1>
    <p class="lede">共 {{N}} 张。每张图是一个生活瞬间，单词用标准字形融进画面：按拼读块分色，不发音的字母画成虚影，再配一个由画面演出来的记忆钩子。图下面是随图保存的三句话：记忆点、读音或词义提醒、画面描述。</p>
  </header>

  <div class="bar" role="group" aria-label="单词层开关">
    <div class="seg">
      <button type="button" id="mem-on" aria-pressed="true">显示单词</button>
      <button type="button" id="mem-off" aria-pressed="false">只看画面</button>
    </div>
    <span class="tip">也可以点任意一张图单独切换。「只看画面」就是在设置里关掉「图片上显示单词」后看到的样子。</span>
  </div>

  <main class="grid" id="grid">
{{CARDS}}
  </main>

  <section aria-labelledby="h-facts">
    <h2 id="h-facts">关于这批图</h2>
    <ul class="facts">
      <li><b>平均每张 {{AVG}} KB，合计 {{TOTAL_MB}} MB</b>都是矢量图（SVG），放大不糊。这里显示的是清洗之后的文件，和导入后 App 里用的一样。</li>
      <li><b>字母是真字形，不是手画</b>用开源识字字体 Andika（SIL OFL 许可）的轮廓转成路径，拼写和字形由程序核对，孩子照着抄不会学歪。</li>
      <li><b>两层结构</b>场景层不含任何文字；单词层可以整层拿掉，画面仍然完整。</li>
      <li><b>画法版本 {{VERSION}}</b>做图的模型：{{MODEL}}。</li>
    </ul>
  </section>
</div>

<script>
(function () {
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var on = document.getElementById('mem-on'), off = document.getElementById('mem-off');
  function setCard(card, state) {
    card.dataset.memory = state;
    var b = card.querySelector('.pic');
    b.setAttribute('aria-pressed', state === 'on' ? 'true' : 'false');
    b.querySelector('.pic-hint').textContent = state === 'on' ? '点图藏起单词' : '点图显示单词';
  }
  function setAll(state) {
    cards.forEach(function (c) { setCard(c, state); });
    on.setAttribute('aria-pressed', state === 'on' ? 'true' : 'false');
    off.setAttribute('aria-pressed', state === 'off' ? 'true' : 'false');
  }
  on.addEventListener('click', function () { setAll('on'); });
  off.addEventListener('click', function () { setAll('off'); });
  cards.forEach(function (c) {
    c.querySelector('.pic').addEventListener('click', function () {
      setCard(c, c.dataset.memory === 'on' ? 'off' : 'on');
      var states = cards.map(function (x) { return x.dataset.memory; });
      on.setAttribute('aria-pressed', states.every(function (s) { return s === 'on'; }) ? 'true' : 'false');
      off.setAttribute('aria-pressed', states.every(function (s) { return s === 'off'; }) ? 'true' : 'false');
    });
  });
})();
</script>
'''

if __name__ == "__main__":
    sys.exit(main())
