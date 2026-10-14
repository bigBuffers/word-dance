import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import type { WordBrief } from '@/api/types';
import { zh } from '@/i18n/zh';
import { WordRow } from './WordRow';

const word = (over: Partial<WordBrief> = {}): WordBrief => ({
  id: 12,
  lemma: 'abandon',
  display: 'abandon',
  kind: 'word',
  phonetic: 'əˈbændən',
  translation_short: 'v. give up',
  stages: ['gk', 'cet4', 'cet6'],
  stage_min: 2,
  cet6_star: false,
  frq: 1200,
  collins: 4,
  oxford: true,
  difficulty: null,
  is_public: true,
  is_valid_english: true,
  my_state: null,
  content_state: 'ready',
  image_state: 'ready',
  ...over,
});

const renderRow = (props: Partial<Parameters<typeof WordRow>[0]> = {}) =>
  render(
    <MemoryRouter>
      <ul>
        <WordRow word={word()} {...props} />
      </ul>
    </MemoryRouter>,
  );

describe('WordRow', () => {
  it('links to the word detail and shows display / phonetic / translation / state badge', () => {
    renderRow();
    expect(screen.getByRole('link').getAttribute('href')).toBe('/words/12');
    expect(screen.getByText('abandon')).toBeTruthy();
    expect(screen.getByText('/əˈbændən/')).toBeTruthy();
    expect(screen.getByText('v. give up')).toBeTruthy();
    expect(screen.getByText(zh.vocab.status.unmarked)).toBeTruthy();
  });

  it('unmarked words offer the inline unfamiliar / known quick actions', () => {
    const onMark = vi.fn();
    renderRow({ onMark });
    fireEvent.click(screen.getByRole('button', { name: zh.vocab.markUnfamiliar }));
    fireEvent.click(screen.getByRole('button', { name: zh.vocab.markKnown }));
    expect(onMark.mock.calls.map((c) => c[0])).toEqual(['unfamiliar', 'known']);
  });

  it('bank words show the in-bank button which opens a sheet with mastered / remove', () => {
    const onMark = vi.fn();
    renderRow({ word: word({ my_state: 'learning' }), onMark });
    expect(screen.queryByRole('button', { name: zh.vocab.markKnown })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: zh.vocab.inBank }));
    fireEvent.click(screen.getByRole('button', { name: zh.study.master }));
    expect(onMark).toHaveBeenCalledWith('mastered');
    fireEvent.click(screen.getByRole('button', { name: zh.vocab.inBank }));
    fireEvent.click(screen.getByRole('button', { name: zh.word.remove }));
    expect(onMark).toHaveBeenLastCalledWith('remove');
  });

  it('mastered / known / removed words offer only the deliberate re-add', () => {
    const onMark = vi.fn();
    renderRow({ word: word({ my_state: 'mastered' }), onMark });
    expect(screen.getByText(zh.bank.tabs.mastered)).toBeTruthy();
    expect(screen.queryByRole('button', { name: zh.vocab.markKnown })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: zh.vocab.markUnfamiliar }));
    expect(onMark).toHaveBeenCalledWith('unfamiliar');
  });

  it('bulk mode replaces the quick buttons with a checkbox', () => {
    const onSelect = vi.fn();
    renderRow({ onMark: vi.fn(), selectable: true, selected: false, onSelect });
    expect(screen.queryByRole('button')).toBeNull();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onSelect).toHaveBeenCalledWith(true);
  });

  it('busy rows disable the quick buttons and custom actions / footer slots render', () => {
    renderRow({ onMark: vi.fn(), busy: true, footer: <span>footer-slot</span> });
    expect((screen.getByRole('button', { name: zh.vocab.markUnfamiliar }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('footer-slot')).toBeTruthy();
  });
});
