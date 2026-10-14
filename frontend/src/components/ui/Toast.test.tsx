import { act } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MAX_VISIBLE_TOASTS, UNDO_LIST_MS, useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { ToastProvider } from './Toast';

function Trigger({ onUndo }: { onUndo: () => void }) {
  const toast = useToast();
  return (
    <>
      <button type="button" onClick={() => toast.toast(`info-${Date.now()}-${Math.random()}`)}>
        info
      </button>
      <button type="button" onClick={() => toast.success('saved-ok', { action: { label: zh.common.undo, onClick: onUndo }, durationMs: UNDO_LIST_MS })}>
        undo
      </button>
      <button type="button" onClick={() => toast.error('failed', { id: 'same' })}>
        error
      </button>
    </>
  );
}

describe('ToastProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows at most MAX_VISIBLE_TOASTS at once and queues the rest', () => {
    render(
      <ToastProvider>
        <Trigger onUndo={() => undefined} />
      </ToastProvider>,
    );
    for (let i = 0; i < 5; i++) fireEvent.click(screen.getByText('info'));
    expect(screen.getAllByRole('status')).toHaveLength(MAX_VISIBLE_TOASTS);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    // the three visible ones expired together; the two queued ones are now visible
    expect(screen.getAllByRole('status')).toHaveLength(2);
  });

  it('runs the action, then dismisses; shows a countdown and the close button', async () => {
    const onUndo = vi.fn();
    render(
      <ToastProvider>
        <Trigger onUndo={onUndo} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText('undo'));
    const action = screen.getByRole('button', { name: new RegExp(`^${zh.common.undo}`) });
    expect(action.textContent).toBe(`${zh.common.undo}${UNDO_LIST_MS / 1000}`);
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(action.textContent).toBe(`${zh.common.undo}${UNDO_LIST_MS / 1000 - 1}`);
    await act(async () => {
      fireEvent.click(action);
    });
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('replaces a toast with the same id instead of stacking and auto-dismisses errors after 5 s', () => {
    render(
      <ToastProvider>
        <Trigger onUndo={() => undefined} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText('error'));
    fireEvent.click(screen.getByText('error'));
    expect(screen.getAllByRole('status')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: zh.common.close }));
    expect(screen.queryByRole('status')).toBeNull();
    fireEvent.click(screen.getByText('error'));
    act(() => {
      vi.advanceTimersByTime(4999);
    });
    expect(screen.getAllByRole('status')).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(2);
    });
    expect(screen.queryByRole('status')).toBeNull();
  });
});
