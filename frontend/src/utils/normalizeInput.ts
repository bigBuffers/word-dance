// normalizeInput — client-side mirror of the backend `services/words.normalise_input` (DESIGN §5.1).
// Used by the 添加生词 live preview to skip obviously invalid lines before `GET /api/lookup` and by the
// vocab search box; the server stays authoritative (its `reason_zh` wins whenever a request is made).
//
// Rules (DESIGN §5.1):
//  1. NFKC; map ’ ‘ ʼ → ', – — → -; collapse whitespace; strip surrounding punctuation
//     , ; : ! ? " ( ) [ ] { } < > (not `.`, which may belong to an abbreviation); trim.
//  2. Reject: empty; > 48 chars; > 4 space-separated tokens; any char outside [A-Za-z' .-];
//     a token made only of ' - .; a `.` inside a token longer than 6 chars; a leading - or '.
//  3. Casing: a single token matching ^[A-Z]{2,6}$ keeps upper case (display) and is an abbreviation;
//     otherwise a capitalised token keeps its first letter (proper-noun hint) and `lemma` is lower-case.

export type NormalizedKind = 'word' | 'phrase' | 'abbreviation';

export interface Normalized {
  ok: true;
  /** Lower-cased key used by the server for resolution (`words.lemma`). */
  lemma: string;
  /** What the user typed, cleaned, with the casing rule of step 3 applied. */
  display: string;
  kind: NormalizedKind;
  tokens: string[];
}

export type InvalidReason = 'empty' | 'too_long' | 'too_many_tokens' | 'charset' | 'bad_token' | 'dot_in_long_token' | 'leading_punct';

export interface Invalid {
  ok: false;
  reason: InvalidReason;
}

export const MAX_INPUT_CHARS = 48;
export const MAX_TOKENS = 4;
/** `POST /api/bank/add` accepts at most this many tokens per call (API.md 34). */
export const MAX_WORDS_PER_ADD = 50;

const QUOTE_DASH_MAP: Record<string, string> = {
  '’': "'",
  '‘': "'",
  'ʼ': "'",
  '–': '-',
  '—': '-',
};
const EDGE_PUNCT = /^[,;:!?"()[\]{}<>]+|[,;:!?"()[\]{}<>]+$/g;
const ALLOWED = /^[A-Za-z' .-]+$/;
const PUNCT_ONLY = /^['.-]+$/;
const ABBREVIATION = /^[A-Z]{2,6}$/;
const CAPITALISED = /^[A-Z][a-z'.-]*$/;

/** Step 1 of DESIGN §5.1: the cleaned string (may be empty). */
export function cleanInput(text: string): string {
  return text
    .normalize('NFKC')
    .replace(/[’‘ʼ–—]/g, (c) => QUOTE_DASH_MAP[c] ?? c)
    .replace(/\s+/g, ' ')
    .trim()
    .replace(EDGE_PUNCT, '')
    .trim();
}

export function normalizeInput(text: string): Normalized | Invalid {
  const s = cleanInput(text);
  if (!s) return { ok: false, reason: 'empty' };
  if (s.length > MAX_INPUT_CHARS) return { ok: false, reason: 'too_long' };
  if (!ALLOWED.test(s)) return { ok: false, reason: 'charset' };
  if (s.startsWith('-') || s.startsWith("'")) return { ok: false, reason: 'leading_punct' };
  const tokens = s.split(' ');
  if (tokens.length > MAX_TOKENS) return { ok: false, reason: 'too_many_tokens' };
  for (const token of tokens) {
    if (PUNCT_ONLY.test(token)) return { ok: false, reason: 'bad_token' };
    if (token.includes('.') && token.length > 6) return { ok: false, reason: 'dot_in_long_token' };
  }

  const lemma = s.toLowerCase();
  if (tokens.length === 1 && ABBREVIATION.test(s)) {
    return { ok: true, lemma, display: s, kind: 'abbreviation', tokens };
  }
  const display = tokens.map((t) => (CAPITALISED.test(t) ? t : t.toLowerCase())).join(' ');
  const kind: NormalizedKind = tokens.length > 1 ? 'phrase' : s.includes('.') ? 'abbreviation' : 'word';
  return { ok: true, lemma, display, kind, tokens };
}

export function isNormalized(result: Normalized | Invalid): result is Normalized {
  return result.ok;
}

/**
 * Splits pasted text the way `POST /api/bank/add` does (DESIGN §5.3): on newlines, commas,
 * semicolons (ASCII and full-width) and tabs — never on spaces, so phrases survive. Empty pieces
 * are dropped; the caller enforces `MAX_WORDS_PER_ADD`.
 */
export function splitInput(text: string): string[] {
  return text
    .split(/[\n\r,;\t，；]+/)
    .map((piece) => piece.trim())
    .filter((piece) => piece.length > 0);
}

export interface InputLine {
  /** 0-based position in the pasted text (stable key for the preview rows). */
  index: number;
  raw: string;
  result: Normalized | Invalid;
  /** True when an earlier line normalises to the same lemma (the server dedupes these too). */
  duplicate: boolean;
}

/** Normalises every piece of `text`, marking lemma duplicates within the same paste. */
export function analyseInput(text: string): InputLine[] {
  const seen = new Set<string>();
  return splitInput(text).map((raw, index) => {
    const result = normalizeInput(raw);
    let duplicate = false;
    if (result.ok) {
      duplicate = seen.has(result.lemma);
      seen.add(result.lemma);
    }
    return { index, raw, result, duplicate };
  });
}
