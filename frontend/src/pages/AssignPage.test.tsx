import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createAssignment, getAssignLearners, getAssignment, getAssignments, getVocab, previewAssignment, withdrawAssignment } from '@/api/endpoints';
import type { AssignmentDetail, AssignmentWord, AssignPreviewItem } from '@/api/types';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import AssignPage, { wordProgress } from './AssignPage';

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  getAssignLearners: vi.fn(), getAssignments: vi.fn(), getAssignment: vi.fn(), previewAssignment: vi.fn(), createAssignment: vi.fn(), withdrawAssignment: vi.fn(), getVocab: vi.fn(),
}));

const word = (over: Partial<AssignmentWord> = {}): AssignmentWord => ({
  word_id: 1, display: 'apple', meaning: 'MEANING', status: 'pending', scheduled_date: null, kind: null, result: null, skip_count: 0, graded_at: null, learner_state: 'new', waiting_lookup: false, ...over,
});
const detail = (over: Partial<AssignmentDetail> = {}): AssignmentDetail => ({
  id: 5, learner: { id: 2, name: 'kimi' }, title: 'UNIT-3', mode: 'today', created_at: '2026-11-20T02:00:00Z', counts: { total: 2, pending: 1, scheduled: 1, done: 1, withdrawn: 0 },
  words: [word({ status: 'scheduled', scheduled_date: '2026-11-20', kind: 'new', result: 'good' }), word({ word_id: 2, display: 'bank' })], ...over,
});
const rows: AssignPreviewItem[] = [
  { input: 'apple', status: 'new', word_id: 1, display: 'apple', meaning: 'MEANING', message: null },
  { input: 'dog', status: 'known', word_id: 3, display: 'dog', meaning: 'DOG', message: null },
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/assign']}>
      <ToastProvider>
        <AssignPage />
      </ToastProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAssignLearners).mockResolvedValue({ items: [{ id: 2, name: 'kimi' }, { id: 3, name: 'tao' }] });
  vi.mocked(getAssignments).mockResolvedValue({ items: [] });
  vi.mocked(getVocab).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 } as never);
});

describe('AssignPage', () => {
  it('explains itself to someone who may assign to nobody', async () => {
    vi.mocked(getAssignLearners).mockResolvedValue({ items: [] });
    renderPage();
    expect(await screen.findByText(zh.assign.noLearners)).toBeTruthy();
    expect(screen.queryByRole('button', { name: zh.assign.submit })).toBeNull();
  });

  it('previews the typed words for the chosen learner, then assigns them and opens the new list', async () => {
    vi.mocked(previewAssignment).mockResolvedValue({ items: rows });
    vi.mocked(createAssignment).mockResolvedValue({ assignment: detail(), results: rows });
    vi.mocked(getAssignment).mockResolvedValue(detail());
    renderPage();
    const box = await screen.findByLabelText(zh.assign.words);
    expect(screen.getByRole('button', { name: zh.assign.submit }).hasAttribute('disabled')).toBe(true); // nothing typed yet
    fireEvent.change(screen.getByLabelText(zh.assign.learner), { target: { value: '3' } });
    fireEvent.change(box, { target: { value: 'apple\ndog' } });
    fireEvent.click(screen.getByRole('button', { name: zh.assign.preview }));
    expect(await screen.findByText(zh.assign.status.known)).toBeTruthy();
    expect(previewAssignment).toHaveBeenCalledWith(3, 'apple\ndog');
    expect(createAssignment).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('radio', { name: zh.assign.modes.spread }));
    fireEvent.change(screen.getByLabelText(zh.assign.name), { target: { value: ' UNIT-3 ' } });
    vi.mocked(getAssignments).mockResolvedValue({ items: [detail()] });
    fireEvent.click(screen.getByRole('button', { name: zh.assign.submit }));
    await waitFor(() => expect(createAssignment).toHaveBeenCalledWith({ learner_id: 3, text: 'apple\ndog', mode: 'spread', title: 'UNIT-3' }));
    expect(await screen.findByText(zh.assign.submitted(2))).toBeTruthy();
    expect((box as HTMLTextAreaElement).value).toBe('');
    expect(await screen.findByText(zh.assign.summary(2, 1, 1), { exact: false })).toBeTruthy();
    expect(await screen.findByText('bank')).toBeTruthy(); // the new list is open
    expect(getAssignment).toHaveBeenCalledWith(5, expect.anything());
  });

  it('shows the server refusal under the words and keeps what was typed', async () => {
    vi.mocked(createAssignment).mockRejectedValue(Object.assign(new Error('REFUSED'), { status: 400, code: 'validation_error', message: 'REFUSED' }));
    renderPage();
    const box = await screen.findByLabelText(zh.assign.words);
    fireEvent.change(box, { target: { value: 'dog' } });
    fireEvent.click(screen.getByRole('button', { name: zh.assign.submit }));
    await waitFor(() => expect(createAssignment).toHaveBeenCalled());
    await waitFor(() => expect(box.getAttribute('aria-invalid')).toBe('true'));
    expect((box as HTMLTextAreaElement).value).toBe('dog');
  });

  it('appends a word picked from the library search', async () => {
    vi.mocked(getVocab).mockResolvedValue({ items: [{ id: 9, display: 'ice cream', translation_short: 'ICE' }], total: 1, page: 1, page_size: 8 } as never);
    renderPage();
    const box = await screen.findByLabelText(zh.assign.words);
    fireEvent.change(box, { target: { value: 'apple' } });
    fireEvent.change(screen.getByLabelText(zh.assign.search), { target: { value: 'ice' } });
    fireEvent.click(await screen.findByRole('button', { name: /ice cream/ }));
    expect((box as HTMLTextAreaElement).value).toBe('apple\nice cream');
    expect(getVocab).toHaveBeenCalledWith({ q: 'ice', page_size: 8 });
  });

  it('opens a list to its words and takes back the ones not scheduled yet', async () => {
    vi.mocked(getAssignments).mockResolvedValue({ items: [detail()] });
    vi.mocked(getAssignment).mockResolvedValue(detail());
    vi.mocked(withdrawAssignment).mockResolvedValue(detail({ counts: { total: 2, pending: 0, scheduled: 1, done: 1, withdrawn: 1 }, words: [detail().words[0]!, word({ word_id: 2, display: 'bank', status: 'withdrawn' })] }));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: zh.assign.detail }));
    expect(await screen.findByText('bank')).toBeTruthy();
    expect(screen.getByText(zh.assign.word.pending)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: zh.assign.withdraw }));
    expect(await screen.findByText(zh.assign.word.withdrawn)).toBeTruthy();
    expect(withdrawAssignment).toHaveBeenCalledWith(5);
    expect(screen.queryByRole('button', { name: zh.assign.withdraw })).toBeNull(); // nothing pending any more
  });

  it('says what each word of a list is doing', () => {
    expect(wordProgress(word())).toBe(zh.assign.word.pending);
    expect(wordProgress(word({ waiting_lookup: true }))).toBe(zh.assign.word.waiting);
    expect(wordProgress(word({ status: 'withdrawn' }))).toBe(zh.assign.word.withdrawn);
    expect(wordProgress(word({ status: 'scheduled', scheduled_date: '2026-11-20', result: 'good' }))).toContain(zh.study.good);
    expect(wordProgress(word({ status: 'scheduled', scheduled_date: '2026-11-20', skip_count: 2 }))).toContain(zh.assign.word.skipped(2));
    expect(wordProgress(word({ status: 'scheduled', scheduled_date: '2026-11-20' }))).toContain(zh.assign.word.open);
  });
});
