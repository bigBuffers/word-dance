// Pure helpers of the vocabulary browser (optimistic state, toast copy, undo eligibility — FRONTEND 5.5 / API.md 26)
// plus the accessible names of the filter controls.
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { zh } from '@/i18n/zh';
import VocabPage, { markToast, markUndoable, optimisticState } from './VocabPage';

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  getVocab: vi.fn(async () => ({ items: [], page: 1, page_size: 50, total: 0 })),
  getVocabLetters: vi.fn(async () => ({ items: [] })),
}));

describe('filter controls', () => {
  it('the status and sort selects are named after their purpose, not their current option', async () => {
    render(
      <MemoryRouter>
        <VocabPage />
      </MemoryRouter>,
    );
    const status = (await screen.findByRole('combobox', { name: zh.common.status })) as HTMLSelectElement;
    const sort = screen.getByRole('combobox', { name: zh.common.sort }) as HTMLSelectElement;
    fireEvent.change(status, { target: { value: 'unfamiliar' } });
    fireEvent.change(sort, { target: { value: 'alpha' } });
    expect(status.value).toBe('unfamiliar');
    expect(sort.value).toBe('alpha');
    expect(screen.getByRole('combobox', { name: zh.common.status })).toBe(status);
    expect(screen.getByRole('combobox', { name: zh.common.sort })).toBe(sort);
    expect(screen.queryByRole('combobox', { name: zh.vocab.status.all })).toBeNull();
    expect(screen.queryByRole('combobox', { name: zh.vocab.sort.freq })).toBeNull();
  });
});

describe('optimisticState', () => {
  it('mirrors the DESIGN 4 transitions', () => {
    expect(optimisticState('unfamiliar', null)).toBe('new');
    expect(optimisticState('unfamiliar', 'mastered')).toBe('new');
    expect(optimisticState('known', null)).toBe('known');
    expect(optimisticState('known', 'learning')).toBe('mastered'); // known on a bank word is the mastered synonym
    expect(optimisticState('mastered', null)).toBe('known'); // never studied → treated as known
    expect(optimisticState('mastered', 'new')).toBe('mastered');
    expect(optimisticState('remove', 'learning')).toBe('removed');
    expect(optimisticState('reset', 'learning')).toBe('new');
    expect(optimisticState('restore', 'mastered')).toBe('mastered');
  });
});

describe('markToast / markUndoable', () => {
  it('picks the copy from the action and server status', () => {
    expect(markToast('unfamiliar', 'added')).toBe(zh.vocab.addedToBank);
    expect(markToast('unfamiliar', 'readded')).toBe(zh.bank.status.readded);
    expect(markToast('unfamiliar', 'exists')).toBe(zh.vocab.inBank);
    expect(markToast('known', 'added')).toBe(zh.vocab.status.known);
    expect(markToast('mastered', 'added')).toBe(zh.study.mastered);
    expect(markToast('remove', 'added')).toBe(zh.bank.tabs.removed);
  });

  it('offers the server undo only when a restore can succeed', () => {
    expect(markUndoable('unfamiliar', 'added')).toBe(true);
    expect(markUndoable('known', 'added')).toBe(true);
    expect(markUndoable('mastered', 'added')).toBe(true);
    expect(markUndoable('unfamiliar', 'exists')).toBe(false);
    expect(markUndoable('unfamiliar', 'readded')).toBe(false);
    expect(markUndoable('mastered', 'noop')).toBe(false);
    expect(markUndoable('remove', 'added')).toBe(false);
    expect(markUndoable('reset', 'added')).toBe(false);
  });
});
