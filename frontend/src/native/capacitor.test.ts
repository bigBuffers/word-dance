// Native shell integration (FRONTEND §6.6, docs/MOBILE_APP.md §3): in a browser everything is a no-op; in the shell the reminder is
// scheduled at the learner's push_time converted to the device's clock, permission is asked only inside a gesture, listeners wire
// the back button / resume / notification tap. The Capacitor plugins are mocked; `state` switches the platform per test.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Listener = (event: never) => void;
const { state, plugin, app, tts } = vi.hoisted(() => {
  const state = { native: false, platform: 'web' as 'web' | 'ios' | 'android', permission: 'granted' as 'granted' | 'denied' | 'prompt' };
  const handle = () => ({ remove: vi.fn(async () => undefined) });
  const plugin = {
    cancel: vi.fn(async (_opts: unknown) => undefined),
    checkPermissions: vi.fn(async () => ({ display: state.permission })),
    requestPermissions: vi.fn(async () => ({ display: 'granted' as const })),
    schedule: vi.fn(async (_opts: unknown) => ({ notifications: [] })),
    addListener: vi.fn(async (_name: string, _fn: Listener) => handle()),
  };
  const app = { addListener: vi.fn(async (_name: string, _fn: Listener) => handle()), minimizeApp: vi.fn(async () => undefined) };
  const tts = { speak: vi.fn(async (_opts: unknown) => undefined), stop: vi.fn(async () => undefined) };
  return { state, plugin, app, tts };
});

vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => state.native, getPlatform: () => state.platform } }));
vi.mock('@capacitor/local-notifications', () => ({ LocalNotifications: plugin }));
vi.mock('@capacitor/app', () => ({ App: app }));
vi.mock('@capacitor-community/text-to-speech', () => ({ TextToSpeech: tts }));

import { zh } from '@/i18n/zh';
import {
  REMINDER_ID,
  installNativeListeners,
  isNative,
  localReminderTime,
  nativePlatform,
  reminderPermission,
  requestReminderPermission,
  speakNative,
  stopNativeSpeech,
  syncDailyReminder,
  zoneOffsetMinutes,
} from './capacitor';

const JAN = new Date(Date.UTC(2026, 0, 15, 12, 0, 0));
const JUL = new Date(Date.UTC(2026, 6, 15, 12, 0, 0));

function wallIn(zone: string, at: Date): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(at);
}

beforeEach(() => {
  state.native = false;
  state.platform = 'web';
  state.permission = 'granted';
});

afterEach(() => {
  document.documentElement.className = '';
});

describe('zone arithmetic', () => {
  it('knows the offsets of fixed and DST zones', () => {
    expect(zoneOffsetMinutes('Asia/Shanghai', JAN)).toBe(480);
    expect(zoneOffsetMinutes('UTC', JAN)).toBe(0);
    expect(zoneOffsetMinutes('America/New_York', JAN)).toBe(-300);
    expect(zoneOffsetMinutes('America/New_York', JUL)).toBe(-240);
    expect(() => zoneOffsetMinutes('Mars/Olympus', JAN)).toThrow();
  });

  it('converts push_time in the settings zone to the device clock (round trip through the zone)', () => {
    for (const [zone, time] of [
      ['Asia/Shanghai', '08:00'],
      ['America/New_York', '21:30'],
      ['Europe/London', '00:05'],
      ['Pacific/Auckland', '23:59'],
    ] as const) {
      const at = localReminderTime(time, zone, JAN);
      expect(at).not.toBeNull();
      // the device-local moment, read back in the settings zone, is the chosen time again
      const today = new Date(JAN);
      const local = new Date(today.getFullYear(), today.getMonth(), today.getDate(), at!.hour, at!.minute);
      const candidates = [local, new Date(local.getTime() - 86_400_000), new Date(local.getTime() + 86_400_000)];
      expect(candidates.map((c) => wallIn(zone, c))).toContain(time);
    }
  });

  it('uses the zone offset at the target moment on DST days (New York: 08:00 stays 08:00 when synced at 01:30 on the switch day)', () => {
    for (const now of [new Date('2026-03-08T06:30:00Z'), new Date('2026-11-01T05:30:00Z'), new Date('2026-03-08T12:00:00Z'), new Date('2026-11-01T12:00:00Z')]) {
      const at = localReminderTime('08:00', 'America/New_York', now)!;
      const local = new Date(now.getFullYear(), now.getMonth(), now.getDate(), at.hour, at.minute);
      const candidates = [local, new Date(local.getTime() - 86_400_000), new Date(local.getTime() + 86_400_000)];
      expect(candidates.map((c) => wallIn('America/New_York', c))).toContain('08:00');
    }
  });

  it('keeps the clock as local for an unknown zone and rejects a malformed time', () => {
    expect(localReminderTime('07:45', 'Mars/Olympus', JAN)).toEqual({ hour: 7, minute: 45 });
    expect(localReminderTime('7:45', 'Asia/Shanghai', JAN)).toBeNull();
    expect(localReminderTime('24:00', 'Asia/Shanghai', JAN)).toBeNull();
    expect(localReminderTime('', 'Asia/Shanghai', JAN)).toBeNull();
  });
});

describe('in a browser', () => {
  it('is not native and touches no plugin', async () => {
    expect(isNative()).toBe(false);
    expect(nativePlatform()).toBe('web');
    expect(await reminderPermission()).toBe('unsupported');
    expect(await syncDailyReminder({ push_enabled: true, push_time: '08:00', timezone: 'Asia/Shanghai' })).toBe('unsupported');
    expect(await requestReminderPermission()).toBe(false);
    const uninstall = installNativeListeners({ navigate: vi.fn(), onResume: vi.fn() });
    expect(document.documentElement.classList.contains('native')).toBe(false);
    uninstall();
    expect(plugin.cancel).not.toHaveBeenCalled();
    expect(plugin.schedule).not.toHaveBeenCalled();
    expect(app.addListener).not.toHaveBeenCalled();
  });
});

describe('in the shell', () => {
  beforeEach(() => {
    state.native = true;
    state.platform = 'android';
  });

  it('cancels, then schedules the daily reminder at the device-local push time with the copy from zh.ts', async () => {
    const settings = { push_enabled: true, push_time: '08:00', timezone: 'Asia/Shanghai' };
    expect(await syncDailyReminder(settings)).toBe('scheduled');
    expect(plugin.cancel).toHaveBeenCalledWith({ notifications: [{ id: REMINDER_ID }] });
    const expected = localReminderTime('08:00', 'Asia/Shanghai')!;
    expect(plugin.schedule).toHaveBeenCalledWith({
      notifications: [
        {
          id: REMINDER_ID,
          title: zh.native.reminderTitle,
          body: zh.native.reminderBody,
          schedule: { on: { hour: expected.hour, minute: expected.minute }, repeats: true, allowWhileIdle: true },
          isExactNotification: false, // never the plugin's default: exact alarms open the system settings page from schedule() on Android 14+
          extra: { path: '/today' },
        },
      ],
    });
    expect(plugin.cancel.mock.invocationCallOrder[0]!).toBeLessThan(plugin.schedule.mock.invocationCallOrder[0]!);
  });

  it('only cancels when push is off, when signed out, or when the time is malformed', async () => {
    expect(await syncDailyReminder({ push_enabled: false, push_time: '08:00', timezone: 'Asia/Shanghai' })).toBe('cancelled');
    expect(await syncDailyReminder(null)).toBe('cancelled');
    expect(await syncDailyReminder({ push_enabled: true, push_time: 'noon', timezone: 'Asia/Shanghai' })).toBe('cancelled');
    expect(plugin.cancel).toHaveBeenCalledTimes(3);
    expect(plugin.schedule).not.toHaveBeenCalled();
  });

  it('never prompts from a sync: without permission it reports denied', async () => {
    state.permission = 'prompt';
    expect(await syncDailyReminder({ push_enabled: true, push_time: '08:00', timezone: 'Asia/Shanghai' })).toBe('denied');
    expect(plugin.requestPermissions).not.toHaveBeenCalled();
    expect(plugin.schedule).not.toHaveBeenCalled();
  });

  it('reports the permission state without prompting', async () => {
    expect(await reminderPermission()).toBe('granted');
    state.permission = 'prompt';
    expect(await reminderPermission()).toBe('prompt');
    state.permission = 'denied';
    expect(await reminderPermission()).toBe('denied');
    expect(plugin.requestPermissions).not.toHaveBeenCalled();
  });

  it('requests permission only when it is not granted yet', async () => {
    expect(await requestReminderPermission()).toBe(true);
    expect(plugin.requestPermissions).not.toHaveBeenCalled();
    state.permission = 'prompt';
    expect(await requestReminderPermission()).toBe(true);
    expect(plugin.requestPermissions).toHaveBeenCalledTimes(1);
  });

  it('speaks through the TTS plugin', async () => {
    await speakNative('abandon', 'en-US', 0.92);
    expect(tts.speak).toHaveBeenCalledWith({ text: 'abandon', lang: 'en-US', rate: 0.92, category: 'ambient' });
  });

  it('settles an utterance the next speak() or stop() flushes (Android never resolves the interrupted call)', async () => {
    tts.speak.mockImplementationOnce(() => new Promise<undefined>(() => undefined)); // the flushed call: pending for ever
    let firstDone = false;
    const first = speakNative('abandon', 'en-US', 0.92).then(() => (firstDone = true));
    await Promise.resolve();
    expect(firstDone).toBe(false);
    await speakNative('apple', 'en-US', 0.92); // flushes the first
    await first;
    expect(firstDone).toBe(true);
    tts.speak.mockImplementationOnce(() => new Promise<undefined>(() => undefined));
    let secondDone = false;
    const second = speakNative('banana', 'en-US', 0.92).then(() => (secondDone = true));
    await stopNativeSpeech();
    await second;
    expect(secondDone).toBe(true);
    expect(tts.stop).toHaveBeenCalledTimes(1);
  });

  it('installs the back button, resume and notification-tap listeners and tags <html>', async () => {
    const navigate = vi.fn();
    const onResume = vi.fn();
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => undefined);
    const uninstall = installNativeListeners({ navigate, onResume });
    expect(document.documentElement.classList.contains('native')).toBe(true);
    expect(document.documentElement.classList.contains('native-android')).toBe(true);
    const listeners = Object.fromEntries(app.addListener.mock.calls.map(([name, fn]) => [name, fn as (e: unknown) => void]));
    listeners['backButton']!({ canGoBack: true });
    expect(back).toHaveBeenCalledTimes(1);
    listeners['backButton']!({ canGoBack: false });
    expect(app.minimizeApp).toHaveBeenCalledTimes(1);
    listeners['appStateChange']!({ isActive: true });
    listeners['appStateChange']!({ isActive: false });
    expect(onResume).toHaveBeenCalledTimes(1);
    const tap = plugin.addListener.mock.calls[0]![1] as unknown as (e: unknown) => void;
    tap({ notification: { extra: { path: '/study' } } });
    tap({ notification: { extra: {} } });
    tap({ notification: { extra: { path: 'https://evil.example' } } });
    expect(navigate.mock.calls.map((c) => c[0])).toEqual(['/study', '/today', '/today']);
    uninstall();
    expect(document.documentElement.classList.contains('native')).toBe(false);
    await Promise.resolve();
    back.mockRestore();
  });
});
