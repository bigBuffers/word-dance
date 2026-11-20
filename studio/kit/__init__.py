"""studio/kit — the memory-card kit: one short script per card instead of one hand-drawn SVG (see KIT.md)."""
from __future__ import annotations

import json
import pathlib

from . import cast as _cast, props as _props, stage as _stage, word as _word
from .base import Card, H, W, n

for _f in ('sky', 'town', 'far_trees', 'hills', 'ground', 'room', 'window', 'lamp', 'rain', 'motes'):
    setattr(Card, _f, getattr(_stage, _f))
for _f in ('tree', 'big_tree', 'branch', 'bush', 'hedge', 'tufts', 'flowers', 'leaves', 'puddle', 'bench', 'stool', 'chair', 'table', 'tabletop', 'sofa',
           'bed', 'steps', 'door', 'shelf', 'house', 'book', 'bag', 'ball', 'cup', 'bowl', 'pencil', 'paper', 'umbrella', 'bird', 'sound', 'steam', 'glint',
           'bokeh', 'shape', 'plant', 'picture'):
    setattr(Card, _f, getattr(_props, _f))
Card.figure = _cast.build_figure
Card.cat = _cast.build_cat
Card.passerby = _cast.build_passerby


def _word_method(card, zone=None, **kw):
    """The word layer, centred in `zone` (default: the card's calm zone). See KIT.md §5."""
    card.wordart = _word.WordArt(card, zone, **kw)
    return card.wordart


def _caption(card, alt_zh, hook_zh, note_zh='', title=None):
    """The three captions (STUDIO.md §3): alt_zh — the scene in one plain sentence; hook_zh — the hook for the child
    (≤ 34 characters); note_zh — only when the chunks could suggest a wrong sound or meaning (≤ 30)."""
    if len(hook_zh) > 34:
        card.note(f'CAPTION: hook_zh has {len(hook_zh)} characters — at most 34')
    if len(note_zh) > 30:
        card.note(f'CAPTION: note_zh has {len(note_zh)} characters — at most 30')
    if len(alt_zh) > 200:
        card.note('CAPTION: alt_zh is longer than 200 characters')
    card.captions = {'alt_zh': alt_zh, 'hook_zh': hook_zh, 'note_zh': note_zh}
    if title:
        card.title = title
    return card


Card.write = _word_method
Card.caption = _caption


def new(word, light, calm, brief=None, file=None, seed=7, s=.8):
    """Start a card. calm = (x0, y0, x1, y1): the quiet third of the canvas where the word will stand — plan it first.
    brief = the word's brief (a dict or the path of its JSON file): its `dance` drives the word layer."""
    if isinstance(brief, (str, pathlib.Path)):
        brief = json.loads(pathlib.Path(brief).read_text())
    c = Card(word, light=light, file=file, brief=brief, seed=seed)
    c.calm, c.S = tuple(calm), s
    return c


__all__ = ['new', 'Card', 'W', 'H', 'n']
