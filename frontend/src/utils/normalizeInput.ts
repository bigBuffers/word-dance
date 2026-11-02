// normalizeInput — client-side mirror of the backend `services/words.normalise_input` (DESIGN §5.1).
// Used by the 添加生词 live preview to skip obviously invalid lines before `GET /api/lookup` and by the
// vocab search box; the server stays authoritative (its `reason_zh` wins whenever a request is made).
// Lines the client rejects are never posted, so the rules, their ORDER and the reason strings
// (`zh.bank.invalidReason`) must match `words.py` exactly — backend/tests/unit/test_words_normalise.py and
// ./normalizeInput.test.ts share the same table.
//
// Rules (DESIGN §5.1, words.py `_clean` / `normalise_input`):
//  1. NFKC; map ’ ‘ ʼ ‛ ′ → ', “ ” „ « » → ", – — ‐ ‑ − → -; collapse whitespace; strip surrounding
//     whitespace and punctuation , ; : ! ? " ( ) [ ] { } < > repeatedly until nothing changes (not `.`,
//     which may belong to an abbreviation).
//  2. Reject, in this order: empty; any CJK character (请输入英文单词); any char outside [A-Za-z' .-];
//     > 48 chars; > 4 space-separated tokens; a token made only of ' - .; a `.` inside a token longer
//     than 6 chars; a leading - or '.
//  3. Casing per token (`_display_token`): an acronym (2–6 letters, all upper case, dots allowed) and a
//     Capitalised token keep their casing; everything else is lower-cased. `lemma` is the lower-cased key.
//     `kind` (`derive_kind`): space → phrase; ^[A-Z]{2,6}$ or a `.` → abbreviation; capital → proper_noun.

export type NormalizedKind = 'word' | 'phrase' | 'abbreviation' | 'proper_noun';

export interface Normalized {
  ok: true;
  /** Lower-cased key used by the server for resolution (`words.lemma`). */
  lemma: string;
  /** What the user typed, cleaned, with the casing rule of step 3 applied. */
  display: string;
  kind: NormalizedKind;
  tokens: string[];
}

export type InvalidReason = 'empty' | 'not_english' | 'charset' | 'too_long' | 'too_many_tokens' | 'bad_token' | 'dot_in_long_token' | 'leading_punct';

export interface Invalid {
  ok: false;
  reason: InvalidReason;
}

export const MAX_INPUT_CHARS = 48;
export const MAX_TOKENS = 4;
/** 'a.m.', 'e.g.', 'etc.', 'U.S.A.' pass; 'example.com' fails (words.py MAX_DOTTED_TOKEN_LEN). */
export const MAX_DOTTED_TOKEN_LEN = 6;
/** `POST /api/bank/add` accepts at most this many tokens per call (API.md 34). */
export const MAX_WORDS_PER_ADD = 50;

/** words.py `_CHAR_MAP`. */
const CHAR_MAP: Record<string, string> = {
  '’': "'",
  '‘': "'",
  'ʼ': "'",
  '‛': "'",
  '′': "'",
  '“': '"',
  '”': '"',
  '„': '"',
  '«': '"',
  '»': '"',
  '–': '-',
  '—': '-',
  '‐': '-',
  '‑': '-',
  '−': '-',
};
const CHAR_MAP_RE = /[’‘ʼ‛′“”„«»–—‐‑−]/g;
const EDGE_PUNCT = /^[,;:!?"()[\]{}<>]+|[,;:!?"()[\]{}<>]+$/g;
const ALLOWED = /^[A-Za-z' .-]+$/;
const PUNCT_ONLY = /^['.-]+$/;
const ACRONYM = /^[A-Z]{2,6}$/;
/** words.py `_CJK_RE`: CJK punctuation, kana, ideographs, hangul, compatibility and full-width forms. */
const CJK = /[　-〿぀-ヿ㐀-䶿一-鿿가-힯豈-﫿＀-￯]/;

/** Step 1 of DESIGN §5.1: the cleaned string (may be empty). */
export function cleanInput(text: string): string {
  let s = text
    .normalize('NFKC')
    .replace(CHAR_MAP_RE, (c) => CHAR_MAP[c] ?? c)
    .replace(/\s+/g, ' ');
  // fixpoint: `, "apple",` → `"apple"` → `apple` (words.py `_clean` loops strip() + strip(punct))
  let prev: string | null = null;
  while (prev !== s) {
    prev = s;
    s = s.trim().replace(EDGE_PUNCT, '');
  }
  return s;
}

/** Casing rule of DESIGN §5.1 step 3 per token (words.py `_display_token`). */
export function displayToken(token: string): string {
  const letters = token.replace(/[^A-Za-z]/g, '');
  if (letters.length >= 2 && letters.length <= MAX_DOTTED_TOKEN_LEN && letters === letters.toUpperCase()) return token;
  const first = token.charAt(0);
  if (first !== '' && first === first.toUpperCase() && first !== first.toLowerCase() && letters.slice(1) === letters.slice(1).toLowerCase()) return token;
  return token.toLowerCase();
}

/** DESIGN §3.2 `kind` rule (words.py `derive_kind`). */
export function deriveKind(display: string): NormalizedKind {
  if (display.includes(' ')) return 'phrase';
  if (ACRONYM.test(display) || display.includes('.')) return 'abbreviation';
  const first = display.charAt(0);
  if (first !== '' && first === first.toUpperCase() && first !== first.toLowerCase()) return 'proper_noun';
  return 'word';
}

export function normalizeInput(text: string): Normalized | Invalid {
  const s = cleanInput(text);
  if (!s) return { ok: false, reason: 'empty' };
  if (CJK.test(s)) return { ok: false, reason: 'not_english' };
  if (!ALLOWED.test(s)) return { ok: false, reason: 'charset' };
  if (s.length > MAX_INPUT_CHARS) return { ok: false, reason: 'too_long' };
  const tokens = s.split(' ');
  if (tokens.length > MAX_TOKENS) return { ok: false, reason: 'too_many_tokens' };
  for (const token of tokens) {
    if (PUNCT_ONLY.test(token)) return { ok: false, reason: 'bad_token' };
    if (token.includes('.') && token.length > MAX_DOTTED_TOKEN_LEN) return { ok: false, reason: 'dot_in_long_token' };
  }
  if (s.startsWith('-') || s.startsWith("'")) return { ok: false, reason: 'leading_punct' };

  const display = tokens.map(displayToken).join(' ');
  const lemma = s.toLowerCase();
  return { ok: true, lemma, display, kind: deriveKind(display), tokens: lemma.split(' ') };
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
