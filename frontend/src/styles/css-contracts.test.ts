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

  it('a switch row of the settings page spans the row, so every toggle sits at its right edge, and the switch hint wraps at normal weight', () => {
    const settings = sheet('pages/SettingsPage.css');
    // `.settings__row > label:first-child` (hug the text, nowrap, weight 500) also matches the Switch's own <label class="switch">:
    // a hugging label put the toggle wherever its text ended (the 图片上显示单词 row, with a hint, 118 px right of its neighbours)
    // and handed nowrap + 500 down to `.switch__desc`. The switch rule has the same specificity (0,2,1), so it must come later.
    const hugging = settings.search(/\.settings__row > label:first-child,\s*\.settings__row > span:first-child\s*\{[^}]*flex:\s*0 0 auto[^}]*white-space:\s*nowrap[^}]*font-weight:\s*500/);
    const spanning = settings.search(/\.settings__row > label\.switch\s*\{[^}]*flex:\s*1 1 auto/);
    expect(hugging).toBeGreaterThan(-1);
    expect(spanning).toBeGreaterThan(hugging);
    expect(settings).toMatch(/\.settings__row \.switch__desc\s*\{[^}]*white-space:\s*normal[^}]*font-weight:\s*400/);
    // once the label spans the row its own space-between sends the toggle to the far end; the text column may shrink so the hint can wrap
    const ui = sheet('components/ui/ui.css');
    expect(ui).toMatch(/\.switch\s*\{[^}]*justify-content:\s*space-between/);
    expect(ui).toMatch(/\.switch__text\s*\{[^}]*min-width:\s*0/);
    expect(ui).toMatch(/\.switch__control\s*\{[^}]*flex:\s*none/);
  });

  it('the listen player sizes its play button with two classes, so the 64 px outrank the 52 px of `.btn--icon.btn--lg`', () => {
    const listen = sheet('pages/ListenPage.css');
    // ui.css sizes a large icon button with two classes (specificity 0,2,0); a bare `.listen-bar__play` (0,1,0) would lose
    expect(sheet('components/ui/ui.css')).toMatch(/\.btn--icon\.btn--lg\s*\{[^}]*width:\s*52px/);
    expect(listen).toMatch(/\.listen-bar__transport \.listen-bar__play\s*\{[^}]*width:\s*64px[^}]*min-height:\s*64px/);
    expect(listen).not.toMatch(/(^|[^.\w ])\.listen-bar__play\s*\{/m);
    // the side columns are equal, so that button sits on the centre line whatever the restart label measures
    expect(listen).toMatch(/\.listen-bar\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto minmax\(0, 1fr\)/);
  });
});
