export type ClassValue = string | false | null | undefined;

/** Joins truthy class names: `cx('btn', active && 'is-active')`. */
export function cx(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(' ');
}
