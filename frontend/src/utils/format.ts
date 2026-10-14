// format — small display helpers shared by the WP7 pages (numbers, money, bytes, text) plus the
// `client_event_id` generator (UUID v4, API.md §1 idempotency). No UI copy lives here (FRONTEND §8).

const intFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 });

/** Integer with locale grouping (`4,722`); non-finite input renders as `0`. */
export function formatInt(n: number): string {
  return intFormatter.format(Number.isFinite(n) ? Math.round(n) : 0);
}

/** `$0.04` — two decimals, three when the amount is positive but under one cent. */
export function formatUsd(n: number): string {
  if (!Number.isFinite(n)) return '$0.00';
  const digits = n > 0 && n < 0.01 ? 3 : 2;
  return `$${n.toFixed(digits)}`;
}

/** `1.2 MB` / `512 KB` / `0 B`. */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'] as const;
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  const unit = units[i] ?? 'B';
  return `${i === 0 ? Math.round(value) : value < 10 ? value.toFixed(1) : Math.round(value)} ${unit}`;
}

/** `42%` of `part / total` (clamped 0–100; `0%` when total is 0). */
export function formatPercent(part: number, total: number): string {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) return '0%';
  return `${Math.max(0, Math.min(100, Math.round((part / total) * 100)))}%`;
}

/** Fixed decimals without trailing noise: `formatDecimal(2.5, 2)` → `2.50`. */
export function formatDecimal(n: number, digits = 2): string {
  return Number.isFinite(n) ? n.toFixed(digits) : (0).toFixed(digits);
}

/** Truncates to `max` characters (code points) with an ellipsis. */
export function truncate(s: string, max: number): string {
  const chars = Array.from(s);
  if (chars.length <= max) return s;
  return `${chars.slice(0, Math.max(0, max - 1)).join('')}…`;
}

/** Parses an integer from an input value and clamps it into `[min, max]`; `null` when not a number. */
export function parseIntInRange(raw: string, min: number, max: number): number | null {
  const n = Number.parseInt(raw.trim(), 10);
  if (!Number.isFinite(n)) return null;
  return Math.max(min, Math.min(max, n));
}

/** Badge text capped at `99+`. */
export function formatBadge(n: number, cap = 99): string {
  return n > cap ? `${cap}+` : String(n);
}

/** UUID v4 for `client_event_id` (API.md §1). Falls back to `getRandomValues` where `randomUUID` is missing. */
export function clientEventId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Builds the display text of an image/content attribution-free value list: `a · b · c`. */
export function joinDot(parts: ReadonlyArray<string | null | undefined>): string {
  return parts.filter((p): p is string => typeof p === 'string' && p.length > 0).join(' · ');
}
