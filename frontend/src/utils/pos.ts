// formatPos — ECDICT's `pos` column is a part-of-speech frequency distribution ("n:4/v:96", every ratio sums
// to 100), not a label (SCHEMA.sql `words.pos`). The detail page and the study card render it for the learner
// as "v. 96% · n. 4%"; Claude-filled words carry real labels ("v./n.", "abbr.") which pass through unchanged.

const RATIO_RE = /^[a-z]:\d+(\/[a-z]:\d+)*$/;

/** ECDICT tag letters → the dictionary abbreviations learners know. */
export const POS_LABELS: Readonly<Record<string, string>> = {
  n: 'n.',
  v: 'v.',
  j: 'adj.',
  r: 'adv.',
  i: 'prep.',
  p: 'pron.',
  m: 'num.',
  c: 'conj.',
  d: 'det.',
  u: 'int.',
  a: 'art.',
  t: 'inf.',
};

/** Shares below this percentage are dropped from the rendered distribution (never the dominant one): "a:99/t:1" → "art. 99%". */
export const MIN_POS_SHARE = 2;

export function isPosRatio(pos: string): boolean {
  return RATIO_RE.test(pos.trim());
}

/**
 * "n:4/v:96" → "v. 96% · n. 4%" (dominant class first, shares < 2 % dropped); any other string is returned
 * trimmed, and empty / null input yields null so callers can keep their `&&` guards.
 */
export function formatPos(pos: string | null | undefined): string | null {
  const raw = pos?.trim() ?? '';
  if (!raw) return null;
  if (!isPosRatio(raw)) return raw;
  const parts = raw
    .split('/')
    .map((part) => {
      const [tag = '', pct = ''] = part.split(':');
      return { tag, pct: Number(pct) };
    })
    .filter((p) => Number.isFinite(p.pct) && p.pct > 0)
    .sort((a, b) => b.pct - a.pct);
  if (parts.length === 0) return null;
  const kept = parts.filter((p, i) => i === 0 || p.pct >= MIN_POS_SHARE);
  return kept.map((p) => `${POS_LABELS[p.tag] ?? `${p.tag}.`} ${p.pct}%`).join(' · ');
}
