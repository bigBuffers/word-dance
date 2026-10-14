import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { zh } from '@/i18n/zh';
import { LETTERS, LetterIndex } from './LetterIndex';

describe('LetterIndex', () => {
  const letters = [
    { letter: 'a', count: 412 },
    { letter: 'b', count: 0 },
    { letter: 'c', count: 9 },
  ];

  it('renders all 26 letters plus an all-chip, disabling letters without words', () => {
    render(<LetterIndex letters={letters} active={null} onPick={vi.fn()} />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(LETTERS.length + 1);
    expect(buttons[0]?.textContent).toBe(zh.common.all);
    expect(buttons[0]?.getAttribute('aria-pressed')).toBe('true');
    expect((screen.getByRole('button', { name: 'A (412)' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: 'B (0)' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'D (0)' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('picks a letter, toggles it off when active, and clears through the all-chip', () => {
    const onPick = vi.fn();
    const { rerender } = render(<LetterIndex letters={letters} active={null} onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: 'A (412)' }));
    expect(onPick).toHaveBeenLastCalledWith('a');
    rerender(<LetterIndex letters={letters} active="a" onPick={onPick} />);
    expect(screen.getByRole('button', { name: 'A (412)' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'A (412)' }));
    expect(onPick).toHaveBeenLastCalledWith(null);
    fireEvent.click(screen.getByRole('button', { name: zh.common.all }));
    expect(onPick).toHaveBeenLastCalledWith(null);
  });

  it('moves focus with the arrow keys across enabled letters only', () => {
    render(<LetterIndex letters={letters} active={null} onPick={vi.fn()} />);
    const all = screen.getByRole('button', { name: zh.common.all });
    all.focus();
    fireEvent.keyDown(all, { key: 'ArrowRight' });
    expect(document.activeElement?.textContent).toBe('A');
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'ArrowRight' });
    expect(document.activeElement?.textContent).toBe('C'); // B is disabled
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Home' });
    expect(document.activeElement?.textContent).toBe(zh.common.all);
  });
});
