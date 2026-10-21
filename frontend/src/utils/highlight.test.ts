import { describe, expect, it } from 'vitest';
import { buildPattern, cloze, containsForm, highlight, normaliseForms } from './highlight';

const hits = (text: string, forms: string[]) => highlight(text, forms).filter((s) => s.hit).map((s) => s.text);

describe('highlight', () => {
  it('marks the headword and keeps the surrounding text intact', () => {
    const segs = highlight('They had to abandon the car.', ['abandon']);
    expect(segs).toEqual([
      { text: 'They had to ', hit: false },
      { text: 'abandon', hit: true },
      { text: ' the car.', hit: false },
    ]);
    expect(segs.map((s) => s.text).join('')).toBe('They had to abandon the car.');
  });

  it('is case-insensitive and keeps the original casing', () => {
    expect(hits('Abandon ship! ABANDON it.', ['abandon'])).toEqual(['Abandon', 'ABANDON']);
  });

  it('prefers the longest form (abandoned, not abandon + ed)', () => {
    expect(hits('She abandoned the plan while abandoning hope.', ['abandon', 'abandoned', 'abandoning'])).toEqual(['abandoned', 'abandoning']);
    expect(normaliseForms(['go', 'went', 'Going', 'going', '', '  gone '])).toEqual(['Going', 'gone', 'went', 'go']);
  });

  it('never matches inside another word', () => {
    expect(hits('Their abandonment was total; unabandoned too.', ['abandon'])).toEqual([]);
    expect(hits('data-driven database', ['data'])).toEqual(['data']); // hyphen is a boundary, "database" is not
  });

  it('handles punctuation, possessives and sentence edges', () => {
    expect(hits('abandon, abandon. (abandon) "abandon"', ['abandon'])).toHaveLength(4);
    expect(hits("abandon's", ['abandon'])).toEqual(['abandon']);
    expect(hits('abandon', ['abandon'])).toEqual(['abandon']);
  });

  it('matches phrases and abbreviations with dots', () => {
    expect(hits('I love ice  cream in summer.', ['ice cream'])).toEqual(['ice  cream']);
    expect(hits('We met at 5 a.m. today.', ['a.m.'])).toEqual(['a.m.']);
    expect(hits('ought to go', ['ought to'])).toEqual(['ought to']);
  });

  it('escapes regex metacharacters in forms', () => {
    expect(() => buildPattern(['c++', 'what?', '(x)'])).not.toThrow();
    expect(hits('I learnt c++ (x) what?', ['c++', '(x)'])).toEqual(['c++', '(x)']);
  });

  it('returns plain text when there is nothing to match and [] for empty text', () => {
    expect(highlight('nothing here', [])).toEqual([{ text: 'nothing here', hit: false }]);
    expect(highlight('nothing here', ['', '  '])).toEqual([{ text: 'nothing here', hit: false }]);
    expect(highlight('', ['x'])).toEqual([]);
    expect(buildPattern([])).toBeNull();
  });

  it('builds the cloze hint and reports containment', () => {
    expect(cloze('They had to abandon the car and abandoned hope.', ['abandon', 'abandoned'])).toBe('They had to ___ the car and ___ hope.');
    expect(containsForm('abandonment', ['abandon'])).toBe(false);
    expect(containsForm('to abandon', ['abandon'])).toBe(true);
  });
});
