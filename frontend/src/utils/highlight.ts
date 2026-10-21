// highlight — marks the headword and its inflected forms inside an example sentence (FRONTEND §4
// `study/ExampleList`): one alternation of all forms, longest first, case-insensitive, matched only at
// word boundaries so `abandon` never lights up inside `abandonment`. Also builds the 提示 cloze
// (headword/forms → `___`) of FRONTEND §5.1.1.
export interface Segment {
  text: string;
  /** True for a matched headword/form (rendered as `<mark>`). */
  hit: boolean;
}

export const CLOZE_BLANK = '___';

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Unique, trimmed, non-empty forms ordered longest first (then alphabetically for determinism). */
export function normaliseForms(forms: readonly (string | null | undefined)[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of forms) {
    const f = (raw ?? '').trim();
    if (!f) continue;
    const key = f.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(f);
  }
  return out.sort((a, b) => b.length - a.length || a.localeCompare(b));
}

/**
 * `(?<![A-Za-z0-9])(?:form1|form2…)(?![A-Za-z0-9])` with the `gi` flags — the `\b` boundary of the
 * contract expressed so that forms ending in a dot (`a.m.`) or containing spaces (`ice cream`) still
 * match whole words. Returns null when there is nothing to match.
 */
export function buildPattern(forms: readonly (string | null | undefined)[]): RegExp | null {
  const list = normaliseForms(forms);
  if (list.length === 0) return null;
  const alternation = list.map((f) => escapeRegExp(f).replace(/\s+/g, '\\s+')).join('|');
  return new RegExp(`(?<![A-Za-z0-9])(?:${alternation})(?![A-Za-z0-9])`, 'gi');
}

/** Splits `text` into plain and matched segments (consecutive plain text is merged). */
export function highlight(text: string, forms: readonly (string | null | undefined)[]): Segment[] {
  if (!text) return [];
  const re = buildPattern(forms);
  if (!re) return [{ text, hit: false }];
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const start = m.index ?? 0;
    const matched = m[0];
    if (!matched) continue;
    if (start > last) out.push({ text: text.slice(last, start), hit: false });
    out.push({ text: matched, hit: true });
    last = start + matched.length;
  }
  if (last < text.length) out.push({ text: text.slice(last), hit: false });
  return out;
}

/** True when `text` contains the headword or one of its forms as a whole word. */
export function containsForm(text: string, forms: readonly (string | null | undefined)[]): boolean {
  const re = buildPattern(forms);
  return re ? re.test(text) : false;
}

/** The sentence with every headword/form replaced by `___` (the 提示 cloze). */
export function cloze(text: string, forms: readonly (string | null | undefined)[], blank = CLOZE_BLANK): string {
  return highlight(text, forms)
    .map((s) => (s.hit ? blank : s.text))
    .join('');
}
