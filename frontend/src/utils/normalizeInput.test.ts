// normalizeInput mirrors the DESIGN §5.1 table and the backend's `normalise_input` (words.py) rule for rule —
// same character map, fixpoint edge stripping, check ORDER, casing and kind; test_words_normalise.py covers the
// same cases on the server. Lines the client rejects are never posted, so any drift here silently refuses
// input the server would accept.
import { describe, expect, it } from 'vitest';
import { analyseInput, cleanInput, deriveKind, displayToken, normalizeInput, splitInput, type InvalidReason, type NormalizedKind } from './normalizeInput';

type Accepted = { input: string; lemma: string; display?: string; kind?: NormalizedKind; tokens?: number };
type Rejected = { input: string; reason: InvalidReason };

const accepted: Accepted[] = [
  { input: ' Abandoned ', lemma: 'abandoned', display: 'Abandoned', kind: 'proper_noun' }, // capitalised → proper-noun hint (ops.md behaviour note)
  { input: 'abandon', lemma: 'abandon', display: 'abandon', kind: 'word' },
  { input: 'a.m.', lemma: 'a.m.', display: 'a.m.', kind: 'abbreviation' },
  { input: 'e.g.', lemma: 'e.g.', display: 'e.g.', kind: 'abbreviation' },
  { input: 'etc.', lemma: 'etc.', display: 'etc.', kind: 'abbreviation' },
  { input: 'U.S.A.', lemma: 'u.s.a.', display: 'U.S.A.', kind: 'abbreviation' }, // dotted acronym keeps its case (words.py _display_token)
  { input: 'ice cream', lemma: 'ice cream', display: 'ice cream', kind: 'phrase', tokens: 2 },
  { input: 'ought to', lemma: 'ought to', kind: 'phrase', tokens: 2 },
  { input: 'take off', lemma: 'take off', kind: 'phrase', tokens: 2 },
  { input: 'as a matter of', lemma: 'as a matter of', kind: 'phrase', tokens: 4 },
  { input: 'CPU', lemma: 'cpu', display: 'CPU', kind: 'abbreviation' },
  { input: 'GDP', lemma: 'gdp', display: 'GDP', kind: 'abbreviation' },
  { input: 'NASA', lemma: 'nasa', display: 'NASA', kind: 'abbreviation' },
  { input: 'TV', lemma: 'tv', display: 'TV', kind: 'abbreviation' },
  { input: 'UNESCO', lemma: 'unesco', display: 'UNESCO', kind: 'abbreviation' },
  { input: 'ABCDEFG', lemma: 'abcdefg', display: 'abcdefg', kind: 'word' }, // 7 capitals: not an acronym
  { input: 'GDP growth', lemma: 'gdp growth', display: 'GDP growth', kind: 'phrase', tokens: 2 }, // acronym inside a phrase keeps its case
  { input: 'ICE CREAM', lemma: 'ice cream', display: 'ICE CREAM', kind: 'phrase' }, // every token is a 2–6 letter acronym shape
  { input: 'Kubernetes', lemma: 'kubernetes', display: 'Kubernetes', kind: 'proper_noun' },
  { input: 'China', lemma: 'china', display: 'China', kind: 'proper_noun' },
  { input: 'don’t', lemma: "don't", display: "don't" },
  { input: 'don‛t', lemma: "don't", display: "don't" }, // U+201B single high-reversed-9 quotation mark
  { input: 'don′t', lemma: "don't", display: "don't" }, // U+2032 prime
  { input: 'rockʼn', lemma: "rock'n", display: "rock'n" },
  { input: 'rock–solid', lemma: 'rock-solid', display: 'rock-solid' },
  { input: 'well—known', lemma: 'well-known', display: 'well-known' },
  { input: 'co‐operate', lemma: 'co-operate', display: 'co-operate' }, // U+2010 hyphen (PDF copies)
  { input: 'co‑operate', lemma: 'co-operate', display: 'co-operate' }, // U+2011 non-breaking hyphen
  { input: 'x−ray', lemma: 'x-ray', display: 'x-ray' }, // U+2212 minus sign
  { input: 'ａｂａｎｄｏｎ', lemma: 'abandon', display: 'abandon' },
  { input: 'ｉｃｅ　ｃｒｅａｍ', lemma: 'ice cream', kind: 'phrase' },
  { input: '(abandon)', lemma: 'abandon' },
  { input: '"abandon"', lemma: 'abandon' },
  { input: '“abandon”', lemma: 'abandon' }, // curly double quotes → " → stripped (Chinese IME punctuation mode)
  { input: '«apple»', lemma: 'apple' },
  { input: '„apple“', lemma: 'apple' },
  { input: ', "apple",', lemma: 'apple' }, // nested edge punctuation: strip until nothing changes
  { input: '("abandon")', lemma: 'abandon' },
  { input: 'abandon!', lemma: 'abandon' },
  { input: 'abandon?', lemma: 'abandon' },
  { input: '[abandon]', lemma: 'abandon' },
  { input: '<abandon>', lemma: 'abandon' },
  { input: 'abandon,', lemma: 'abandon' },
  { input: 'abandon;', lemma: 'abandon' },
  { input: 'abandon:', lemma: 'abandon' },
  { input: '{abandon}', lemma: 'abandon' },
  { input: "rock 'n' roll", lemma: "rock 'n' roll", kind: 'phrase', tokens: 3 },
  { input: 'mother-in-law', lemma: 'mother-in-law', kind: 'word', tokens: 1 },
  { input: "o'clock", lemma: "o'clock" },
  { input: 'abandon   ship', lemma: 'abandon ship', tokens: 2 },
  { input: 'abandon\tship', lemma: 'abandon ship', tokens: 2 },
  { input: 'a'.repeat(48), lemma: 'a'.repeat(48) },
  { input: 'Mr.', lemma: 'mr.', display: 'Mr.', kind: 'abbreviation' },
  { input: 'Dr.', lemma: 'dr.', display: 'Dr.', kind: 'abbreviation' },
];

const rejected: Rejected[] = [
  { input: '', reason: 'empty' },
  { input: '   ', reason: 'empty' },
  { input: '()', reason: 'empty' },
  { input: ', ;', reason: 'empty' },
  { input: '放弃', reason: 'not_english' },
  { input: '苹果', reason: 'not_english' },
  { input: 'abandon 放弃', reason: 'not_english' },
  { input: 'りんご', reason: 'not_english' },
  { input: '사과', reason: 'not_english' },
  { input: 'abc123', reason: 'charset' },
  { input: 'e-mail@example', reason: 'charset' },
  { input: 'abandon_ship', reason: 'charset' },
  { input: 'naïve', reason: 'charset' },
  { input: 'hello/world', reason: 'charset' },
  { input: 'a'.repeat(49), reason: 'too_long' },
  { input: 'this is a long sentence', reason: 'too_many_tokens' },
  { input: 'one two three four five', reason: 'too_many_tokens' },
  { input: '-abandon', reason: 'leading_punct' },
  { input: "'abandon", reason: 'leading_punct' },
  { input: '‘quoted’', reason: 'leading_punct' }, // curly single quotes map to ' (DESIGN §5.1 step 1) → leading apostrophe
  { input: 'example.com', reason: 'dot_in_long_token' },
  { input: 'word.press', reason: 'dot_in_long_token' },
  { input: 'abandon.', reason: 'dot_in_long_token' }, // a trailing period is not stripped (DESIGN §5.1 keeps `.`)
  { input: 'abandon -', reason: 'bad_token' },
  { input: '- abandon', reason: 'bad_token' }, // punctuation-only token is checked before the leading-punct rule
  { input: "abandon ' ship", reason: 'bad_token' },
  { input: 'abandon ... ship', reason: 'bad_token' },
  { input: 'ice . cream', reason: 'bad_token' },
  // check order mirrors words.py: CJK → charset → length → token count → token shape → leading punctuation
  { input: '放弃 abc123', reason: 'not_english' },
  { input: `${'a'.repeat(49)}1`, reason: 'charset' },
  { input: 'abc123 one two three four', reason: 'charset' },
  { input: `${'a'.repeat(30)} ${'b'.repeat(30)} c d e`, reason: 'too_long' },
  { input: '-one two three four five', reason: 'too_many_tokens' },
];

describe('normalizeInput', () => {
  it.each(accepted)('accepts %j', (c) => {
    const r = normalizeInput(c.input);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.lemma).toBe(c.lemma);
    if (c.display !== undefined) expect(r.display).toBe(c.display);
    if (c.kind !== undefined) expect(r.kind).toBe(c.kind);
    if (c.tokens !== undefined) expect(r.tokens).toHaveLength(c.tokens);
    expect(r.lemma).toBe(r.lemma.toLowerCase());
    expect(r.display.toLowerCase()).toBe(r.lemma);
  });

  it.each(rejected)('rejects %j', (c) => {
    expect(normalizeInput(c.input)).toEqual({ ok: false, reason: c.reason });
  });

  it('has at least 60 table rows', () => {
    expect(accepted.length + rejected.length).toBeGreaterThanOrEqual(60);
  });

  it('cleanInput applies NFKC, the full quote/dash map and repeated edge stripping only', () => {
    expect(cleanInput('  "Don’t"  ')).toBe("Don't");
    expect(cleanInput('“Don’t”')).toBe("Don't");
    expect(cleanInput(', "apple",')).toBe('apple');
    expect(cleanInput('a.m.')).toBe('a.m.');
    expect(cleanInput('—')).toBe('-');
    expect(cleanInput('«x−ray»')).toBe('x-ray');
  });

  it('displayToken / deriveKind follow words.py', () => {
    expect(displayToken('ICE')).toBe('ICE');
    expect(displayToken('Cream')).toBe('Cream');
    expect(displayToken('cREAM')).toBe('cream');
    expect(displayToken('ABCDEFG')).toBe('abcdefg');
    expect(displayToken('U.S.A.')).toBe('U.S.A.');
    expect(deriveKind('ice cream')).toBe('phrase');
    expect(deriveKind('GDP')).toBe('abbreviation');
    expect(deriveKind('Mr.')).toBe('abbreviation');
    expect(deriveKind('China')).toBe('proper_noun');
    expect(deriveKind('abandon')).toBe('word');
  });
});

describe('splitInput / analyseInput', () => {
  it('splits on newlines, commas, semicolons (ASCII and full-width) and tabs, never on spaces', () => {
    expect(splitInput('abandoned, children\nubiquitous；bases\tabc123，ice cream; take off')).toEqual([
      'abandoned',
      'children',
      'ubiquitous',
      'bases',
      'abc123',
      'ice cream',
      'take off',
    ]);
    expect(splitInput('\n\n , ;')).toEqual([]);
  });

  it('marks lemma duplicates within one paste and keeps invalid lines', () => {
    const lines = analyseInput('Abandon\nabandon, ABANDON\nabc123\nGDP');
    expect(lines.map((l) => l.raw)).toEqual(['Abandon', 'abandon', 'ABANDON', 'abc123', 'GDP']);
    expect(lines.map((l) => l.duplicate)).toEqual([false, true, true, false, false]);
    expect(lines[3]?.result.ok).toBe(false);
    expect(lines[4]?.result).toMatchObject({ ok: true, kind: 'abbreviation', display: 'GDP' });
    expect(lines.map((l) => l.index)).toEqual([0, 1, 2, 3, 4]);
  });
});
