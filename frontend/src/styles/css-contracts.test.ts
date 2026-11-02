// Cascade contracts that jsdom cannot measure (vitest runs with `css: false`, which also empties `?raw` imports of
// stylesheets), pinned by reading the stylesheets from disk.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/** Reads a file under frontend/src (vitest runs with the frontend package as cwd; file URL fallback otherwise). */
function sheet(relative: string): string {
  const candidates = [`${process.cwd()}/src/${relative}`, new URL(`../${relative}`, import.meta.url)];
  for (const candidate of candidates) {
    try {
      return readFileSync(candidate, 'utf8');
    } catch {
      /* try the next location */
    }
  }
  throw new Error(`missing src/${relative}`);
}

describe('stylesheet contracts', () => {
  it('the searchbox input rule outranks the global input[type="search"] padding, so the icon never covers the text', () => {
    const list = sheet('components/list/list.css');
    // global.css styles `input[type="search"]` (specificity 0,1,1); a bare `.searchbox__input` (0,1,0) would lose
    expect(sheet('styles/global.css')).toMatch(/input\[type="search"\]/);
    expect(list).toMatch(/input\[type="search"\]\.searchbox__input\s*\{[^}]*padding-left:\s*38px/);
    expect(list).toMatch(/input\[type="search"\]\.searchbox__input\s*\{[^}]*padding-right:\s*40px/);
    expect(list).not.toMatch(/(^|[^.\w"\]])\.searchbox__input\s*\{/m);
  });

  it('the settings time input is sized by the browser (12-hour locales need room for the AM/PM field)', () => {
    const settings = sheet('pages/SettingsPage.css');
    expect(settings).not.toMatch(/input\[type="time"\]\s*\{[^}]*width:\s*7em/);
    expect(settings).toMatch(/\.settings__row input\[type="time"\]\s*\{[^}]*width:\s*auto/);
    expect(settings).toMatch(/\.settings__row input\[type="number"\]\s*\{[^}]*width:\s*7em/);
  });
});
