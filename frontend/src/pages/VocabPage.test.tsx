// Pure helpers of the vocabulary browser (optimistic state, toast copy, undo eligibility — FRONTEND 5.5 / API.md 26).
import { describe, expect, it } from 'vitest';
import { zh } from '@/i18n/zh';
import { markToast, markUndoable, optimisticState } from './VocabPage';

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
