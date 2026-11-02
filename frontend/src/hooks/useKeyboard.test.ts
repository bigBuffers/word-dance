import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { normalizeKey, useKeyboard } from './useKeyboard';

const press = (key: string, init: KeyboardEventInit & { target?: EventTarget } = {}) => {
  const { target, ...rest } = init;
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...rest });
  (target ?? window).dispatchEvent(event);
  return event;
};

describe('useKeyboard', () => {
  it('normalises keys (Space, lower-case letters)', () => {
    expect(normalizeKey({ key: ' ' })).toBe('Space');
    expect(normalizeKey({ key: 'S' })).toBe('s');
    expect(normalizeKey({ key: '1' })).toBe('1');
    expect(normalizeKey({ key: 'ArrowLeft' })).toBe('ArrowLeft');
  });

  it('calls the handler for mapped keys and prevents the default', () => {
    const reveal = vi.fn();
    const again = vi.fn();
    renderHook(() => useKeyboard({ Space: reveal, '1': again }));
    const e = press(' ');
    press('1');
    press('x');
    expect(reveal).toHaveBeenCalledTimes(1);
    expect(again).toHaveBeenCalledTimes(1);
    expect(e.defaultPrevented).toBe(true);
  });

  it('ignores modifiers, repeats, form controls, open dialogs and the disabled state', () => {
    const fn = vi.fn();
    const { rerender } = renderHook(({ enabled }) => useKeyboard({ s: fn }, { enabled }), { initialProps: { enabled: true } });
    press('s', { ctrlKey: true });
    press('s', { repeat: true });
    const input = document.createElement('input');
    document.body.appendChild(input);
    press('s', { target: input });
    const dialog = document.createElement('dialog');
    dialog.setAttribute('open', '');
    document.body.appendChild(dialog);
    press('s');
    dialog.remove();
    expect(fn).not.toHaveBeenCalled();
    press('s');
    expect(fn).toHaveBeenCalledTimes(1);
    rerender({ enabled: false });
    press('s');
    expect(fn).toHaveBeenCalledTimes(1);
    input.remove();
  });

  it('yields Space to a focused button or summary (native activation) but still handles other keys there', () => {
    const reveal = vi.fn();
    const skip = vi.fn();
    renderHook(() => useKeyboard({ Space: reveal, s: skip }));
    const button = document.createElement('button');
    document.body.appendChild(button);
    const onButton = press(' ', { target: button });
    expect(reveal).not.toHaveBeenCalled();
    expect(onButton.defaultPrevented).toBe(false);
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    details.appendChild(summary);
    document.body.appendChild(details);
    const onSummary = press(' ', { target: summary });
    expect(reveal).not.toHaveBeenCalled();
    expect(onSummary.defaultPrevented).toBe(false);
    // letters and digits never activate a button, so they keep working from a focused one
    const onButtonS = press('s', { target: button });
    expect(skip).toHaveBeenCalledTimes(1);
    expect(onButtonS.defaultPrevented).toBe(true);
    const plain = press(' ');
    expect(reveal).toHaveBeenCalledTimes(1);
    expect(plain.defaultPrevented).toBe(true);
    button.remove();
    details.remove();
  });
});
