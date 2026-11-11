// CodeField (FRONTEND §4): the send button turns into the 60-s countdown only once `onSend` resolved and offers the resend (`zh.auth.resend`) after it;
// a rejected send leaves the button usable — except a 429 `rate_limited`, which counts the server's `retry_after_s` down (the
// send already counted against the per-target window); `canSend=false` blocks the send; the input keeps six digits only — or
// `length` digits (eight for the child login code of endpoint 107, slice 1-B).
import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import { zh } from '@/i18n/zh';
import { CodeField, RESEND_COOLDOWN_S } from './CodeField';

function Harness({ onSend, canSend }: { onSend: () => Promise<void>; canSend?: boolean }) {
  const [code, setCode] = useState('');
  return <CodeField value={code} onChange={setCode} onSend={onSend} canSend={canSend} />;
}

const button = () => screen.getByRole('button') as HTMLButtonElement;
const input = () => screen.getByLabelText(new RegExp(`^${zh.auth.code}`)) as HTMLInputElement;
/** Clicks the send button and lets the `onSend` promise settle. */
const click = () =>
  act(async () => {
    fireEvent.click(button());
    await Promise.resolve();
    await Promise.resolve();
  });
/** Advances the fake clock one second at a time (the countdown chains one timeout per tick). */
const seconds = async (n: number) => {
  for (let i = 0; i < n; i += 1) {
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
  }
};

describe('CodeField', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('a successful send starts the 60-s countdown with the validity hint, then offers the resend', async () => {
    const onSend = vi.fn(async () => undefined);
    render(<Harness onSend={onSend} />);
    expect(button().textContent).toBe(zh.auth.sendCode);
    expect(button().disabled).toBe(false);
    expect(screen.queryByText(zh.auth.codeHint)).toBeNull();
    await click();
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(button().textContent).toBe(zh.auth.resendIn(RESEND_COOLDOWN_S));
    expect(button().disabled).toBe(true);
    expect(screen.getByText(zh.auth.codeHint)).toBeTruthy();
    await seconds(RESEND_COOLDOWN_S - 1);
    expect(button().textContent).toBe(zh.auth.resendIn(1));
    expect(button().disabled).toBe(true);
    await seconds(1);
    expect(button().textContent).toBe(zh.auth.resend);
    expect(button().disabled).toBe(false);
    expect(screen.getByText(zh.auth.codeHint)).toBeTruthy();
    await click();
    expect(onSend).toHaveBeenCalledTimes(2);
    expect(button().textContent).toBe(zh.auth.resendIn(RESEND_COOLDOWN_S));
  });

  it('a rejected send (503) leaves the button usable with no countdown and no hint', async () => {
    const onSend = vi.fn(async () => {
      throw new ApiError('sms_send_failed', 503, '');
    });
    render(<Harness onSend={onSend} />);
    await click();
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(button().textContent).toBe(zh.auth.sendCode);
    expect(button().disabled).toBe(false);
    await seconds(2);
    expect(button().textContent).toBe(zh.auth.sendCode);
    expect(screen.queryByText(zh.auth.codeHint)).toBeNull();
    await click();
    expect(onSend).toHaveBeenCalledTimes(2); // still usable
  });

  it('a 429 counts the button down for the server window (retry_after_s) and then offers the first send again', async () => {
    const onSend = vi.fn(async () => {
      throw new ApiError('rate_limited', 429, '', { retry_after_s: 30 });
    });
    render(<Harness onSend={onSend} />);
    await click();
    expect(button().textContent).toBe(zh.auth.resendIn(30));
    expect(button().disabled).toBe(true);
    expect(screen.queryByText(zh.auth.codeHint)).toBeNull(); // nothing was sent
    await seconds(29);
    expect(button().textContent).toBe(zh.auth.resendIn(1));
    await seconds(1);
    expect(button().textContent).toBe(zh.auth.sendCode);
    expect(button().disabled).toBe(false);
  });

  it('a 429 without retry_after_s waits the default cooldown', async () => {
    const onSend = vi.fn(async () => {
      throw new ApiError('rate_limited', 429, '');
    });
    render(<Harness onSend={onSend} />);
    await click();
    expect(button().textContent).toBe(zh.auth.resendIn(RESEND_COOLDOWN_S));
  });

  it('does not send while canSend is false, and keeps only the first six digits of what is typed', async () => {
    const onSend = vi.fn(async () => undefined);
    render(<Harness onSend={onSend} canSend={false} />);
    expect(button().disabled).toBe(true);
    await click();
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.change(input(), { target: { value: '12x34567' } });
    expect(input().value).toBe('123456');
    expect(input().getAttribute('autocomplete')).toBe('one-time-code');
    expect(input().getAttribute('inputmode')).toBe('numeric');
  });
});

describe('CodeField length', () => {
  it('accepts `length` digits (8 for the child login code) and cuts the rest', () => {
    function Eight() {
      const [code, setCode] = useState('');
      return <CodeField value={code} onChange={setCode} length={8} />;
    }
    render(<Eight />);
    const field = screen.getByLabelText(new RegExp(`^${zh.auth.code}`)) as HTMLInputElement;
    expect(field.maxLength).toBe(8);
    expect(field.getAttribute('pattern')).toBe('[0-9]{8}');
    fireEvent.change(field, { target: { value: '1234-5678-90' } });
    expect(field.value).toBe('12345678');
    expect(screen.queryByRole('button')).toBeNull(); // no onSend: no send button
  });
});
