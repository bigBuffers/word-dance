import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Page } from '@/api/types';
import { zh } from '@/i18n/zh';
import { pageCount, Pager, pageWindow, usePagedList } from './Pager';

describe('pageWindow / pageCount', () => {
  it('collapses far pages into gaps around the current page', () => {
    expect(pageWindow(3, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(pageWindow(1, 12)).toEqual([1, 2, 3, 4, 'gap', 12]);
    expect(pageWindow(5, 12)).toEqual([1, 'gap', 4, 5, 6, 'gap', 12]);
    expect(pageWindow(12, 12)).toEqual([1, 'gap', 9, 10, 11, 12]);
    expect(pageCount(0, 50)).toBe(1);
    expect(pageCount(101, 50)).toBe(3);
  });
});

describe('Pager', () => {
  it('renders nothing for a single page', () => {
    const { container } = render(<Pager page={1} pageSize={50} total={30} onChange={vi.fn()} />);
    expect(container.innerHTML).toBe('');
  });

  it('desktop numbers replace the page, the phone button appends the next one', () => {
    const onChange = vi.fn();
    render(<Pager page={1} pageSize={50} total={120} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: zh.common.pageOf(2, 3) }));
    expect(onChange).toHaveBeenLastCalledWith(2, 'replace');
    fireEvent.click(screen.getByRole('button', { name: zh.common.loadMore }));
    expect(onChange).toHaveBeenLastCalledWith(2, 'append');
    expect(screen.getByRole('button', { name: zh.common.pageOf(1, 3) }).getAttribute('aria-current')).toBe('page');
  });

  it('hides load-more on the last page and disables the previous arrow on the first', () => {
    render(<Pager page={3} pageSize={50} total={120} onChange={vi.fn()} />);
    expect(screen.queryByRole('button', { name: zh.common.loadMore })).toBeNull();
    expect((screen.getByRole('button', { name: `${zh.common.more} ${zh.common.pageOf(4, 3)}` }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: `${zh.common.back} ${zh.common.pageOf(2, 3)}` }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe('usePagedList', () => {
  const pageOf = (page: number): Page<{ id: number }> => ({ items: [{ id: page * 10 }, { id: page * 10 + 1 }], page, page_size: 2, total: 6 });

  it('replaces or appends rows depending on the pager mode and restarts on reset', async () => {
    const fetcher = vi.fn((page: number) => Promise.resolve(pageOf(page)));
    const { result } = renderHook(() => usePagedList<{ id: number }, Page<{ id: number }>>(fetcher, []));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.total).toBe(6);
    expect(result.current.items.map((i) => i.id)).toEqual([10, 11]);

    act(() => result.current.goTo(2, 'append'));
    await waitFor(() => expect(result.current.items).toHaveLength(4));
    expect(result.current.items.map((i) => i.id)).toEqual([10, 11, 20, 21]);
    expect(result.current.page).toBe(2);

    act(() => result.current.goTo(3, 'replace'));
    await waitFor(() => expect(result.current.items.map((i) => i.id)).toEqual([30, 31]));

    act(() => result.current.reset());
    await waitFor(() => expect(result.current.page).toBe(1));
    await waitFor(() => expect(result.current.items.map((i) => i.id)).toEqual([10, 11]));
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
});
