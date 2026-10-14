import { describe, expect, it } from 'vitest';
import type { WordDetail } from '@/api/types';
import { briefOf } from '@/components/bank/AttentionBadge';
import { rowBelongsToTab } from './BankPage';

describe('rowBelongsToTab', () => {
  it('matches the state tabs on mine.state and the attention tab on needs_attention', () => {
    expect(rowBelongsToTab('new', { state: 'new', needs_attention: false })).toBe(true);
    expect(rowBelongsToTab('learning', { state: 'new', needs_attention: false })).toBe(false);
    expect(rowBelongsToTab('attention', { state: 'new', needs_attention: true })).toBe(true);
    expect(rowBelongsToTab('attention', { state: 'new', needs_attention: false })).toBe(false);
    expect(rowBelongsToTab('removed', { state: 'removed', needs_attention: true })).toBe(true);
  });
});

describe('briefOf', () => {
  it('strips the detail-only fields so the list row keeps the WordBrief shape', () => {
    const word: WordDetail['word'] = {
      id: 1,
      lemma: 'abandon',
      display: 'abandon',
      kind: 'word',
      phonetic: null,
      translation_short: 'give up',
      stages: ['cet4'],
      stage_min: 3,
      cet6_star: false,
      frq: 1,
      collins: null,
      oxford: null,
      difficulty: null,
      is_public: true,
      is_valid_english: true,
      my_state: 'new',
      content_state: 'none',
      image_state: 'none',
      definition: 'def',
      translation: 'long translation',
      pos: 'v',
      exam_tags: ['cet4'],
      bnc: 10,
      forms: [{ form: 'abandoned', kind: 'p' }],
      source: 'seed',
      confusables: ['abundant'],
    };
    const brief = briefOf(word);
    expect(brief).toEqual({
      id: 1,
      lemma: 'abandon',
      display: 'abandon',
      kind: 'word',
      phonetic: null,
      translation_short: 'give up',
      stages: ['cet4'],
      stage_min: 3,
      cet6_star: false,
      frq: 1,
      collins: null,
      oxford: null,
      difficulty: null,
      is_public: true,
      is_valid_english: true,
      my_state: 'new',
      content_state: 'none',
      image_state: 'none',
    });
    expect('confusables' in brief).toBe(false);
  });
});
