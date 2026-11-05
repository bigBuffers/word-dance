// ScreenPage (FRONTEND §2, PLAN §6 S4): one stage card per `GET /api/stages` row, ordered by STAGE_ORDER — five cards
// after the primary-school stage. The card count is pinned to STAGE_ORDER so a frontend / backend stage mismatch is red.
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import type { StageInfo } from '@/api/types';
import { STAGE_INDEX, STAGE_ORDER } from '@/components/word/StageChips';
import { zh } from '@/i18n/zh';

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  getStages: vi.fn(),
}));

import { getStages } from '@/api/endpoints';
import ScreenPage from './ScreenPage';

/** One row per stage, the way the server builds them from schemas.STAGE_ORDER (API.md 19: 5 rows). */
const rows: StageInfo[] = STAGE_ORDER.map((stage) => ({
  stage,
  index: STAGE_INDEX[stage],
  name_zh: zh.stages[stage],
  total: 100 * STAGE_INDEX[stage],
  new_only_total: 50,
  unfamiliar: 1,
  known: 2,
  mastered: 3,
  unseen: 90,
}));

describe('ScreenPage', () => {
  it('renders one card per stage in canonical order, each linking to its screening run', async () => {
    vi.mocked(getStages).mockResolvedValue({ items: [...rows].reverse() }); // server order must not matter
    render(
      <MemoryRouter>
        <ScreenPage />
      </MemoryRouter>,
    );
    const cards = await screen.findAllByRole('link');
    expect(cards).toHaveLength(STAGE_ORDER.length);
    expect(cards).toHaveLength(5);
    expect(cards.map((a) => a.getAttribute('href'))).toEqual(STAGE_ORDER.map((s) => `/screen/${s}`));
    expect(cards.map((a) => a.querySelector('.stage-card__name')?.textContent)).toEqual(STAGE_ORDER.map((s) => zh.stages[s]));
    expect(cards[0]?.querySelector('.stage-card__full')?.textContent).toBe(zh.stages.xsFull);
    expect(screen.getAllByText(zh.screen.remaining(90))).toHaveLength(5);
  });

  it('drops rows the client does not know (a newer server) instead of rendering a blank card', async () => {
    vi.mocked(getStages).mockResolvedValue({ items: [...rows, { ...rows[0]!, stage: 'xx' as StageInfo['stage'] }] });
    render(
      <MemoryRouter>
        <ScreenPage />
      </MemoryRouter>,
    );
    expect(await screen.findAllByRole('link')).toHaveLength(STAGE_ORDER.length);
  });
});
