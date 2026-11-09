// Native shell integration (docs/MOBILE_APP.md §1; FRONTEND.md §6.6). The same site is loaded by the Capacitor remote shell in
// mobile/: there the native bridge injects `window.Capacitor`, `@capacitor/core` picks it up and these functions reach the device
// (the daily reminder as a local notification, the system TTS, the Android back button, a `native` class on <html> for CSS).
// In a browser `isNative()` is false and every function is a no-op or a fallback, so the web app behaves exactly as before.
import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';
import { LocalNotifications } from '@capacitor/local-notifications';
import { TextToSpeech } from '@capacitor-community/text-to-speech';
import type { Settings } from '@/api/types';
import { zh } from '@/i18n/zh';

/** The one daily reminder the shell schedules (cancelled and re-created on every sync). */
export const REMINDER_ID = 1001;
/** Where a tap on the reminder lands. */
export const REMINDER_PATH = '/today';

export function isNative(): boolean {
  return Capacitor.isNativePlatform();
}

export type NativePlatform = 'ios' | 'android' | 'web';

export function nativePlatform(): NativePlatform {
  const platform = Capacitor.getPlatform();
  return platform === 'ios' || platform === 'android' ? platform : 'web';
}

const PUSH_TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

interface WallClock {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

function wallClock(at: Date, timeZone: string): WallClock {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(at);
  const num = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? NaN);
  return { year: num('year'), month: num('month'), day: num('day'), hour: num('hour') % 24, minute: num('minute'), second: num('second') };
}

/** Minutes east of UTC that `timeZone` observes at `at` (Asia/Shanghai → 480, New York in January → -300). Throws for an unknown zone. */
export function zoneOffsetMinutes(timeZone: string, at: Date): number {
  const w = wallClock(at, timeZone);
  const asUtc = Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second);
  return Math.round((asUtc - at.getTime()) / 60_000);
}

/**
 * `push_time` (HH:MM in the learner's `settings.timezone`) as the DEVICE's local hour and minute for today, so a phone whose clock
 * zone differs from the settings zone still rings at the learner's chosen moment. An unknown zone takes the clock as local;
 * a malformed time gives null.
 */
export function localReminderTime(pushTime: string, timeZone: string, now: Date = new Date()): { hour: number; minute: number } | null {
  const m = PUSH_TIME_RE.exec(pushTime);
  if (!m) return null;
  const hour = Number(m[1]);
  const minute = Number(m[2]);
  let today: WallClock;
  let offset: number;
  try {
    today = wallClock(now, timeZone);
    offset = zoneOffsetMinutes(timeZone, now);
  } catch {
    return { hour, minute };
  }
  let instant = new Date(Date.UTC(today.year, today.month - 1, today.day, hour, minute) - offset * 60_000);
  // the zone's offset AT the target moment, not at `now`: on a DST day the two differ by an hour (one refinement suffices)
  const offsetThen = zoneOffsetMinutes(timeZone, instant);
  if (offsetThen !== offset) instant = new Date(Date.UTC(today.year, today.month - 1, today.day, hour, minute) - offsetThen * 60_000);
  return { hour: instant.getHours(), minute: instant.getMinutes() };
}

export type ReminderSync = 'unsupported' | 'cancelled' | 'denied' | 'scheduled';
export type ReminderPermission = 'granted' | 'denied' | 'prompt' | 'unsupported';

/** The notification permission as the OS reports it (`unsupported` in a browser); never prompts. */
export async function reminderPermission(): Promise<ReminderPermission> {
  if (!isNative()) return 'unsupported';
  const { display } = await LocalNotifications.checkPermissions();
  return display === 'granted' || display === 'denied' ? display : 'prompt';
}

/**
 * Cancels the shell's daily reminder and, when push is enabled and notifications are allowed, schedules it again at today's local
 * time of `push_time`. Idempotent: called once the session is known at launch, at every resume and on every settings change (the
 * plugin loses `allowWhileIdle` after the first delivery unless re-scheduled); an explicit sign-out (settings null) cancels it —
 * NativeBridge never passes null while `/api/auth/me` is still loading or failed, so a cold start offline keeps the reminder.
 */
export async function syncDailyReminder(settings: Pick<Settings, 'push_enabled' | 'push_time' | 'timezone'> | null): Promise<ReminderSync> {
  // inexact (see below): Android delivers within the hour of the trigger on API 31+, usually within minutes; longer under battery saver
  if (!isNative()) return 'unsupported';
  await LocalNotifications.cancel({ notifications: [{ id: REMINDER_ID }] }).catch(() => undefined);
  if (!settings?.push_enabled) return 'cancelled';
  const at = localReminderTime(settings.push_time, settings.timezone);
  if (!at) return 'cancelled';
  const permission = await LocalNotifications.checkPermissions();
  if (permission.display !== 'granted') return 'denied';
  await LocalNotifications.schedule({
    notifications: [
      {
        id: REMINDER_ID,
        title: zh.native.reminderTitle,
        body: zh.native.reminderBody,
        schedule: { on: { hour: at.hour, minute: at.minute }, repeats: true, allowWhileIdle: true },
        // Android: an INEXACT alarm (a few minutes' drift is fine for a study reminder). The plugin's default, exact, would open the
        // system "Alarms & reminders" page from schedule() whenever SCHEDULE_EXACT_ALARM is not granted — denied by default on
        // Android 14+ — and this sync runs at every launch and resume, which would trap the learner in that page.
        isExactNotification: false,
        extra: { path: REMINDER_PATH },
      },
    ],
  });
  return 'scheduled';
}

/** Asks for notification permission (call it from a user gesture — the push toggle); true when granted. */
export async function requestReminderPermission(): Promise<boolean> {
  if (!isNative()) return false;
  const current = await LocalNotifications.checkPermissions();
  if (current.display === 'granted') return true;
  return (await LocalNotifications.requestPermissions()).display === 'granted';
}

let interruptCurrent: (() => void) | null = null;

/**
 * The system TTS of the shell (Android's WebView has no speechSynthesis). Resolves when the utterance has finished — or when a later
 * `speakNative` / `stopNativeSpeech` flushes it: the Android plugin discards the callback of an interrupted utterance and never settles
 * that call, so the previous caller is settled here (resolved, not rejected) before the next plugin call goes out.
 */
export async function speakNative(text: string, lang: string, rate: number): Promise<void> {
  interruptCurrent?.();
  let settle!: () => void;
  const interrupted = new Promise<void>((resolve) => {
    settle = resolve;
  });
  interruptCurrent = settle;
  try {
    await Promise.race([TextToSpeech.speak({ text, lang, rate, category: 'ambient' }), interrupted]);
  } finally {
    if (interruptCurrent === settle) interruptCurrent = null;
  }
}

export async function stopNativeSpeech(): Promise<void> {
  interruptCurrent?.();
  interruptCurrent = null;
  await TextToSpeech.stop();
}

/** The TTS plugin's "engine not initialised yet / not available" rejection (Android), as opposed to a missing voice. */
export function isSpeechUnavailable(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { code?: unknown }).code === 'UNAVAILABLE';
}

export interface NativeHandlers {
  navigate: (path: string) => void;
  onResume: () => void;
}

/**
 * Installs the shell's listeners once — Android back button (history back, else minimise), resume (`onResume`, used to re-sync
 * the reminder) and the notification tap (navigate to its path) — and tags <html> with `native` / `native-<platform>` for CSS.
 * Returns the uninstaller; in a browser installs nothing.
 */
export function installNativeListeners(handlers: NativeHandlers): () => void {
  if (!isNative()) return () => undefined;
  const root = document.documentElement;
  const classes = ['native', `native-${nativePlatform()}`];
  root.classList.add(...classes);
  const handles = [
    App.addListener('backButton', ({ canGoBack }) => {
      if (canGoBack) window.history.back();
      else void App.minimizeApp();
    }),
    App.addListener('appStateChange', ({ isActive }) => {
      if (isActive) handlers.onResume();
    }),
    LocalNotifications.addListener('localNotificationActionPerformed', (event) => {
      const path: unknown = event.notification.extra?.path;
      handlers.navigate(typeof path === 'string' && path.startsWith('/') ? path : REMINDER_PATH);
    }),
  ];
  return () => {
    root.classList.remove(...classes);
    for (const handle of handles) void handle.then((listener) => listener.remove()).catch(() => undefined);
  };
}
