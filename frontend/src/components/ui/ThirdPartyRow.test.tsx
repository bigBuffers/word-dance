// ThirdPartyRow (FRONTEND §4, API.md §3.3): one entry per enabled provider, nothing at all while none is on or the flags are
// unknown, QQ / Apple as plain links to endpoints 118 / 120 carrying ?next — in `invite` registration mode behind the invite step,
// whose continue link adds `invite_code` —, the WeChat entry a button for the parent's sheet, and the platform rules: QQ / Apple on
// the web only (a redirect flow cannot finish inside the native shell), on iOS WeChat only next to Apple (design §5.3, App Store 4.8).
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { zh } from '@/i18n/zh';
import { ThirdPartyRow, thirdPartyEntries, type ThirdPartyFlags } from './ThirdPartyRow';

const native = vi.hoisted(() => ({ platform: 'web' as 'web' | 'ios' | 'android' }));
vi.mock('@/native/capacitor', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/capacitor')>()),
  nativePlatform: () => native.platform,
}));

const flags = (over: Partial<ThirdPartyFlags> = {}): ThirdPartyFlags => ({ wechat_enabled: false, qq_enabled: false, apple_enabled: false, ...over });
const allOn = flags({ wechat_enabled: true, qq_enabled: true, apple_enabled: true });

describe('ThirdPartyRow', () => {
  it('renders nothing while the flags are unknown or no provider is on (a dark server shows no trace of slice 2-A)', () => {
    const { container, rerender } = render(<ThirdPartyRow flags={null} onWechat={() => undefined} />);
    expect(container.innerHTML).toBe('');
    rerender(<ThirdPartyRow flags={undefined} onWechat={() => undefined} />);
    expect(container.innerHTML).toBe('');
    rerender(<ThirdPartyRow flags={flags()} onWechat={() => undefined} />);
    expect(container.innerHTML).toBe('');
  });

  it('shows one entry per enabled provider: WeChat as a button for the sheet, QQ and Apple as links to 118 / 120 with ?next', () => {
    const onWechat = vi.fn();
    render(<ThirdPartyRow flags={allOn} next="/bank" onWechat={onWechat} />);
    const group = screen.getByRole('group', { name: zh.auth.thirdParty });
    expect(within(group).getByText(zh.auth.thirdParty)).toBeTruthy();
    expect(within(group).getByRole('link', { name: zh.auth.qq }).getAttribute('href')).toBe('/api/auth/qq/start?kind=login&next=%2Fbank');
    expect(within(group).getByRole('link', { name: zh.auth.apple }).getAttribute('href')).toBe('/api/auth/apple/start?kind=login&next=%2Fbank'); // the HIG wording
    fireEvent.click(within(group).getByRole('button', { name: zh.auth.wechat }));
    expect(onWechat).toHaveBeenCalledTimes(1);
  });

  it('offers only the enabled providers; without ?next the links carry the kind alone (open / verified modes: no invite step)', () => {
    render(<ThirdPartyRow flags={flags({ qq_enabled: true })} registrationMode="verified" onWechat={() => undefined} />);
    expect(screen.queryByRole('button', { name: zh.auth.wechat })).toBeNull();
    expect(screen.queryByRole('link', { name: zh.auth.apple })).toBeNull();
    expect(screen.getByRole('link', { name: zh.auth.qq }).getAttribute('href')).toBe('/api/auth/qq/start?kind=login');
    expect(screen.queryByRole('button', { name: zh.auth.qq })).toBeNull();
  });

  it('QQ / Apple are web-only: inside the shell an off-origin navigation opens the system browser, where the session would land', () => {
    expect(thirdPartyEntries(allOn, 'web')).toEqual({ wechat: true, qq: true, apple: true });
    expect(thirdPartyEntries(allOn, 'android')).toEqual({ wechat: true, qq: false, apple: false }); // the pairing code works in the shell
    expect(thirdPartyEntries(flags({ qq_enabled: true, apple_enabled: true }), 'android')).toEqual({ wechat: false, qq: false, apple: false });
    native.platform = 'android';
    try {
      const { container, rerender } = render(<ThirdPartyRow flags={allOn} onWechat={() => undefined} />);
      expect(screen.getByRole('button', { name: zh.auth.wechat })).toBeTruthy();
      expect(screen.queryByRole('link', { name: zh.auth.qq })).toBeNull();
      expect(screen.queryByRole('link', { name: zh.auth.apple })).toBeNull();
      rerender(<ThirdPartyRow flags={flags({ qq_enabled: true, apple_enabled: true })} onWechat={() => undefined} />);
      expect(container.innerHTML).toBe(''); // nothing left to offer: no row at all
    } finally {
      native.platform = 'web';
    }
  });

  it('on the iOS shell WeChat / QQ are offered only next to Apple (design §5.3 / App Store 4.8) — Apple cannot be offered there, so the row stays empty until a native plugin exists', () => {
    expect(thirdPartyEntries(flags({ wechat_enabled: true, qq_enabled: true }), 'ios')).toEqual({ wechat: false, qq: false, apple: false });
    expect(thirdPartyEntries(allOn, 'ios')).toEqual({ wechat: false, qq: false, apple: false });
    expect(thirdPartyEntries(flags({ wechat_enabled: true }), 'web')).toEqual({ wechat: true, qq: false, apple: false });
    native.platform = 'ios';
    try {
      const { container } = render(<ThirdPartyRow flags={allOn} onWechat={() => undefined} />);
      expect(container.innerHTML).toBe('');
    } finally {
      native.platform = 'web';
    }
  });

  it('in invite registration mode QQ / Apple open the invite step: the continue link carries the trimmed code, the skip link none', () => {
    render(<ThirdPartyRow flags={flags({ qq_enabled: true, apple_enabled: true })} next="/bank" registrationMode="invite" onWechat={() => undefined} />);
    const group = screen.getByRole('group', { name: zh.auth.thirdParty });
    expect(within(group).queryByRole('link', { name: zh.auth.qq })).toBeNull(); // no direct navigation: a new account would bounce with invalid_invite
    expect(within(group).queryByRole('link', { name: zh.auth.apple })).toBeNull();
    fireEvent.click(within(group).getByRole('button', { name: zh.auth.apple }));
    const sheet = screen.getByRole('heading', { name: zh.auth.apple }).closest('dialog') as HTMLDialogElement;
    const field = within(sheet).getByLabelText(new RegExp(`^${zh.auth.inviteForNew}`)) as HTMLInputElement;
    const continueHref = () => within(sheet).getByRole('link', { name: zh.auth.inviteContinue }).getAttribute('href');
    expect(continueHref()).toBe('/api/auth/apple/start?kind=login&next=%2Fbank'); // an empty field sends no code: an existing binding signs in
    fireEvent.change(field, { target: { value: ' INV-2026 ' } });
    expect(continueHref()).toBe('/api/auth/apple/start?kind=login&invite_code=INV-2026&next=%2Fbank');
    expect(within(sheet).getByRole('link', { name: zh.auth.skipInvite }).getAttribute('href')).toBe('/api/auth/apple/start?kind=login&next=%2Fbank');
  });

  it('the QQ step has its own title and no ?next when the page had none', () => {
    render(<ThirdPartyRow flags={flags({ qq_enabled: true })} registrationMode="invite" onWechat={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: zh.auth.qq }));
    const sheet = screen.getByRole('heading', { name: zh.auth.qqTitle }).closest('dialog') as HTMLDialogElement;
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.inviteForNew}`)), { target: { value: 'INV-2026' } });
    expect(within(sheet).getByRole('link', { name: zh.auth.inviteContinue }).getAttribute('href')).toBe('/api/auth/qq/start?kind=login&invite_code=INV-2026');
    expect(within(sheet).getByRole('link', { name: zh.auth.skipInvite }).getAttribute('href')).toBe('/api/auth/qq/start?kind=login');
  });
});
