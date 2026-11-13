// WordImage and memory cards (FRONTEND §4; docs/MEMORY_CARDS_DESIGN.md §3.6–3.7): a picture with a word layer is fetched
// with `?plain=1` while the learner's image_word is off — and only such a picture; it never offers refresh-image, flag-image
// stays; its caption is the AI-image one. `memoryLines` picks the mnemonic section's text: the picture's hook (+ caveat)
// while the picture is shown, else the content's mnemonic.
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ImageMeta } from '@/api/types';
import { zh } from '@/i18n/zh';
import { imageCaption, imageSrc, memoryLines, WordImage } from './WordImage';

const URL_SVG = '/media/images/ab/0123.svg';
/** An older drawing (svg-v2): same provider, no word layer, no texts of its own. */
const drawing: ImageMeta = { id: 7, url: URL_SVG, kind: 'svg', provider: 'claude_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: 'ALT-ZH', attribution: null, word_layer: false, hook_zh: null, note_zh: null };
const memoryCard: ImageMeta = { ...drawing, id: 8, word_layer: true, hook_zh: 'HOOK-ZH', note_zh: 'NOTE-ZH' };
const photo: ImageMeta = {
  id: 9, url: '/media/images/cd/4567.jpg', kind: 'photo', provider: 'wikimedia', mime: 'image/jpeg', width: 1024, height: 640, alt_zh: 'PHOTO-ALT-ZH',
  attribution: { title: 'Red Apple', creator: 'Abhijit Tembhekar', creator_url: null, license: 'CC BY 2.0', license_url: null, landing_url: 'https://commons.wikimedia.org/wiki/File:Red_Apple.jpg', text: '"Red Apple" · Abhijit Tembhekar · CC BY 2.0' },
  word_layer: false, hook_zh: null, note_zh: null,
};

const img = () => screen.getByRole('img') as HTMLImageElement;
const actionNames = () => screen.queryAllByRole('button').map((b) => b.textContent);

describe('imageSrc', () => {
  it('adds ?plain=1 only for a picture with a word layer whose learner switched image_word off', () => {
    expect(imageSrc(memoryCard, true)).toBe(URL_SVG);
    expect(imageSrc(memoryCard, false)).toBe(`${URL_SVG}?plain=1`);
    expect(imageSrc(drawing, false)).toBe(URL_SVG); // an older drawing has no layer to drop
    expect(imageSrc(photo, false)).toBe(photo.url);
  });
});

describe('WordImage', () => {
  it('a memory card is fetched whole with image_word on and without its word layer with it off; other images never change', () => {
    const first = render(<WordImage image={memoryCard} showImages imageWord />);
    expect(img().getAttribute('src')).toBe(URL_SVG);
    expect(img().getAttribute('alt')).toBe('ALT-ZH');
    expect(screen.getByText(zh.word.aiImage)).toBeTruthy(); // the caption stays the AI-image one
    first.rerender(<WordImage image={memoryCard} showImages imageWord={false} />);
    expect(img().getAttribute('src')).toBe(`${URL_SVG}?plain=1`);
    first.unmount();

    const second = render(<WordImage image={drawing} showImages imageWord={false} />);
    expect(img().getAttribute('src')).toBe(URL_SVG);
    second.unmount();
    render(<WordImage image={photo} showImages imageWord={false} />);
    expect(img().getAttribute('src')).toBe(photo.url);
  });

  it("a memory card's alt text is its own scene description, before the content's; every other image keeps the content's first", () => {
    const card = render(<WordImage image={memoryCard} showImages imageWord alt="CONTENT-ALT" />);
    expect(img().getAttribute('alt')).toBe('ALT-ZH'); // written with this very picture; the content's alt predates the card
    card.rerender(<WordImage image={memoryCard} showImages imageWord={false} alt="CONTENT-ALT" />);
    expect(img().getAttribute('alt')).toBe('ALT-ZH'); // the scene is the same without the word
    card.unmount();
    const bare = render(<WordImage image={{ ...memoryCard, alt_zh: '  ' }} showImages imageWord alt="CONTENT-ALT" />);
    expect(img().getAttribute('alt')).toBe('CONTENT-ALT'); // a card imported without a description falls back
    bare.unmount();
    const older = render(<WordImage image={drawing} showImages imageWord alt="CONTENT-ALT" />);
    expect(img().getAttribute('alt')).toBe('CONTENT-ALT');
    older.unmount();
    render(<WordImage image={photo} showImages imageWord alt=" " />);
    expect(img().getAttribute('alt')).toBe('PHOTO-ALT-ZH');
  });

  it('switching the variant loads a new <img>: the skeleton is back until the other file has arrived', () => {
    const { container, rerender } = render(<WordImage image={memoryCard} showImages imageWord />);
    fireEvent.load(img());
    expect(img().classList.contains('is-loaded')).toBe(true);
    expect(container.querySelector('.word-image__skeleton')).toBeNull();
    rerender(<WordImage image={memoryCard} showImages imageWord={false} />);
    expect(img().classList.contains('is-loaded')).toBe(false);
    expect(container.querySelector('.word-image__skeleton')).not.toBeNull();
    fireEvent.load(img());
    expect(img().classList.contains('is-loaded')).toBe(true);
  });

  it('tells its parent which source could not be loaded and which has loaded, one variant at a time', () => {
    const onFailed = vi.fn();
    const onLoaded = vi.fn();
    const { rerender } = render(<WordImage image={memoryCard} showImages imageWord onFailed={onFailed} onLoaded={onLoaded} />);
    fireEvent.error(img());
    expect(screen.queryByRole('img')).toBeNull(); // the box stays empty
    expect(onFailed.mock.calls).toEqual([[URL_SVG]]);
    expect(onLoaded).not.toHaveBeenCalled();
    rerender(<WordImage image={memoryCard} showImages imageWord={false} onFailed={onFailed} onLoaded={onLoaded} />);
    fireEvent.load(img()); // the other variant is another request: tried afresh, and this one arrives
    expect(onLoaded.mock.calls).toEqual([[`${URL_SVG}?plain=1`]]);
    expect(onFailed).toHaveBeenCalledTimes(1);
  });

  it('a memory card never offers refresh-image, in either variant; flag-image stays', () => {
    const onRefresh = vi.fn();
    const onFlag = vi.fn();
    const whole = render(<WordImage image={memoryCard} showImages imageWord onRefresh={onRefresh} onFlag={onFlag} />);
    expect(actionNames()).toEqual([zh.word.flagImage]);
    fireEvent.click(screen.getByRole('button', { name: zh.word.flagImage }));
    expect(onFlag).toHaveBeenCalledTimes(1);
    whole.unmount();

    const plain = render(<WordImage image={memoryCard} showImages imageWord={false} onRefresh={onRefresh} onFlag={onFlag} />);
    expect(actionNames()).toEqual([zh.word.flagImage]);
    plain.unmount();

    // with nothing but a refresh handler the caption carries no action at all
    const bare = render(<WordImage image={memoryCard} showImages imageWord onRefresh={onRefresh} />);
    expect(actionNames()).toEqual([]);
    expect(bare.container.querySelector('.word-image__actions')).toBeNull();
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it('an older drawing and a photo keep both actions', () => {
    const onRefresh = vi.fn();
    const first = render(<WordImage image={drawing} showImages imageWord onRefresh={onRefresh} onFlag={vi.fn()} />);
    expect(actionNames()).toEqual([zh.word.changeImage, zh.word.flagImage]);
    fireEvent.click(screen.getByRole('button', { name: zh.word.changeImage }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
    first.unmount();
    render(<WordImage image={photo} showImages imageWord={false} onRefresh={onRefresh} onFlag={vi.fn()} />);
    expect(actionNames()).toEqual([zh.word.changeImage, zh.word.flagImage]);
    expect(screen.getByRole('link').getAttribute('href')).toBe(photo.attribution?.landing_url);
  });

  it('show_images off renders nothing, whatever the image', () => {
    const { container } = render(<WordImage image={memoryCard} showImages={false} imageWord onFlag={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('captions a memory card like every AI drawing', () => {
    expect(imageCaption(memoryCard)).toBe(zh.word.aiImage);
    expect(imageCaption(drawing)).toBe(zh.word.aiImage);
  });
});

describe('memoryLines', () => {
  it("shows the picture's hook with its caveat while the picture is shown, instead of the content's mnemonic", () => {
    expect(memoryLines(memoryCard, true, 'MNEMONIC-ZH')).toEqual({ text: 'HOOK-ZH', note: 'NOTE-ZH' });
    expect(memoryLines({ ...memoryCard, note_zh: null }, true, 'MNEMONIC-ZH')).toEqual({ text: 'HOOK-ZH', note: null });
    expect(memoryLines({ ...memoryCard, note_zh: '  ' }, true, null)).toEqual({ text: 'HOOK-ZH', note: null });
    expect(memoryLines(memoryCard, true, null)).toEqual({ text: 'HOOK-ZH', note: 'NOTE-ZH' }); // the hook needs no content
  });

  it("falls back to the content's mnemonic when the picture is not on screen (hidden, or failed to load — the caller says which) or brings no hook", () => {
    expect(memoryLines(memoryCard, false, 'MNEMONIC-ZH')).toEqual({ text: 'MNEMONIC-ZH', note: null });
    expect(memoryLines(drawing, true, 'MNEMONIC-ZH')).toEqual({ text: 'MNEMONIC-ZH', note: null });
    expect(memoryLines({ ...memoryCard, hook_zh: '  ' }, true, 'MNEMONIC-ZH')).toEqual({ text: 'MNEMONIC-ZH', note: null });
    // a caveat alone is no hook: it qualifies a line that is not there, so it is not shown under the content's mnemonic either
    expect(memoryLines({ ...memoryCard, hook_zh: null }, true, 'MNEMONIC-ZH')).toEqual({ text: 'MNEMONIC-ZH', note: null });
  });

  it('is null when there is nothing to show', () => {
    expect(memoryLines(memoryCard, false, null)).toBeNull();
    expect(memoryLines(drawing, true, '')).toBeNull();
    expect(memoryLines(drawing, true, undefined)).toBeNull();
  });
});
