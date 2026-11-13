// AppLayout — responsive shell around every authenticated page (FRONTEND §2/§4; routes.tsx mounts it
// as the layout route). TopNav ≥ 768 px, TabBar < 768 px; badges from AuthContext.counters (bank) and
// the today-badge store below (today dot while ungraded items exist). Sets `--tabbar-h` on the root
// while the TabBar is shown so fixed bars and toasts clear it, and hides the whole shell on `/study`
// and `/listen` (the study card and the listen player own the viewport, FRONTEND §6.2). The inner <Suspense> keeps the shell visible while
// a lazy page chunk loads. Above the outlet, a dismissible note asks a learner whose account has no password yet
// (`user.has_password === false`, a code-created account; never admins, never a child — its guardian manages the login) to set one —
// `zh.auth.passwordBanner` (docs/AUTH_SIGNUP_DESIGN.md §5.2, the recycled-number defence, rule 2); the dismissal is a per-viewer
// convenience (useLocalPref) that expires after 30 days. Slice 1-B adds two shell-level pieces on every non-bare route: the
// `SwitchBar` while `session.guardian` is set (this device was switched into a child account, API.md 104 — `zh.children.switchBar`
// + the switch-back button → `GateDialog` in switch-back mode → endpoint 105 → `applyAuth` → /children), and the
// `ProfilePromptDialog` (the legacy profile prompt, endpoints 110 / 111, once per sitting).
import { Suspense, useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router';
import * as endpoints from '@/api/endpoints';
import type { SessionInfo, User } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { GateDialog } from '@/components/account/GateDialog';
import { ProfilePromptDialog } from '@/components/account/ProfilePromptDialog';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { CloseIcon } from '@/components/ui/icons';
import { useLocalPref } from '@/hooks/useLocalPref';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { TabBar, type ShellBadges } from './TabBar';
import { TopNav } from './TopNav';
import './AppLayout.css';

export const PHONE_QUERY = '(max-width: 767.98px)';
/** Height reserved for the TabBar (+ the safe-area inset) — mirrors `.tabbar` in AppLayout.css. */
export const TABBAR_HEIGHT_CSS = 'calc(56px + env(safe-area-inset-bottom, 0px))';
/** Routes that render without the shell (full-viewport study session, the listen player). */
export const BARE_ROUTES: readonly string[] = ['/study', '/listen'];
/** The today badge is re-checked at most this often (ms) when the route or tab visibility changes. */
export const TODAY_BADGE_STALE_MS = 60_000;
/** The password note comes back this long after a dismissal (ms). */
export const PASSWORD_BANNER_SNOOZE_MS = 30 * 86_400_000;
export const PASSWORD_BANNER_PREF = 'wd.passwordBannerDismissedAt';

/** `window.matchMedia(query).matches`, live. False during SSR/tests without matchMedia. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => undefined;
      const mq = window.matchMedia(query);
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    },
    [query],
  );
  const getSnapshot = () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : false);
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}

// ---------------------------------------------------------------------------------------------------
// Today badge store — "ungraded items exist". Pages that already hold a TodayResponse (today / study,
// WP8) call `setTodayUngraded(...)` after loading or grading; the shell itself checks GET /api/today
// (side-effect free, API.md 43) once per route change / tab return, at most every minute.
// ---------------------------------------------------------------------------------------------------

let todayUngraded = false;
let lastCheckedAt = 0;
const listeners = new Set<() => void>();

function subscribeToday(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setTodayUngraded(value: boolean): void {
  lastCheckedAt = Date.now();
  if (todayUngraded === value) return;
  todayUngraded = value;
  for (const listener of listeners) listener();
}

/** Derives the badge from a TodayResponse-like value (`counts.done < counts.total`). */
export function hasUngradedItems(today: { batch: { counts: { done: number; total: number } } | null } | null | undefined): boolean {
  return Boolean(today?.batch && today.batch.counts.done < today.batch.counts.total);
}

export function useTodayUngraded(): boolean {
  return useSyncExternalStore(subscribeToday, () => todayUngraded, () => false);
}

/** Test/integration hook: forget the last check so the next shell mount re-fetches. */
export function resetTodayBadge(): void {
  todayUngraded = false;
  lastCheckedAt = 0;
  for (const listener of listeners) listener();
}

function useTodayBadgeCheck(enabled: boolean, pathname: string): void {
  useEffect(() => {
    if (!enabled) {
      if (todayUngraded) setTodayUngraded(false);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const check = async () => {
      if (Date.now() - lastCheckedAt < TODAY_BADGE_STALE_MS) return;
      lastCheckedAt = Date.now();
      try {
        const today = await endpoints.getToday(controller.signal);
        if (!cancelled) setTodayUngraded(hasUngradedItems(today));
      } catch {
        /* 409 before onboarding or a network hiccup: keep the previous value */
      }
    };
    void check();
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void check();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      cancelled = true;
      controller.abort();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, pathname]);
}

/**
 * `zh.auth.passwordBanner` ("set a password, a new number cannot lose your progress") for a learner without a password, dismissible
 * for 30 days; never for an admin or a child account (`user.is_child` — the guardian sets the child's login).
 */
function PasswordBanner({ user }: { user: Pick<User, 'has_password' | 'role' | 'is_child'> | null }) {
  const [dismissedAt, setDismissedAt] = useLocalPref<number>(PASSWORD_BANNER_PREF, 0);
  if (!user || user.has_password || user.role === 'admin' || user.is_child) return null;
  if (dismissedAt > 0 && Date.now() - dismissedAt < PASSWORD_BANNER_SNOOZE_MS) return null;
  return (
    <div className="app-banner" role="status">
      <span className="app-banner__text">{zh.auth.passwordBanner}</span>
      <Link className="app-banner__action" to={routePaths.settings}>
        {zh.auth.passwordBannerAction}
      </Link>
      <Button variant="ghost" iconOnly size="sm" className="app-banner__close" aria-label={zh.common.close} onClick={() => setDismissedAt(Date.now())}>
        <CloseIcon />
      </Button>
    </div>
  );
}

/**
 * The switched-device bar (slice 1-B): `zh.children.switchBar(child, guardian)` while `session.guardian` is set, with the switch-back
 * button → `GateDialog` (switch-back mode: PIN / password / code → endpoint 105 → `applyAuth`) → /children.
 */
export function SwitchBar({ session, user }: { session: SessionInfo | null; user: User | null }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (!session?.guardian || !user) return null;
  return (
    <>
      <div className="app-banner app-banner--switch" role="status">
        <span className="app-banner__text">{zh.children.switchBar(user.display_name || user.username, session.guardian.display_name)}</span>
        <Button variant="primary" size="sm" className="app-banner__action" onClick={() => setOpen(true)}>
          {zh.children.switchBack}
        </Button>
      </div>
      {/* beside the bar, not inside its live region: the dialog's own content must not be announced as a status update */}
      <GateDialog
        open={open}
        mode="switch-back"
        onClose={() => setOpen(false)}
        onSwitched={() => {
          setOpen(false);
          navigate(routePaths.children, { replace: true });
        }}
      />
    </>
  );
}

function useTabBarHeight(active: boolean): void {
  useEffect(() => {
    const root = document.documentElement;
    if (active) root.style.setProperty('--tabbar-h', TABBAR_HEIGHT_CSS);
    else root.style.removeProperty('--tabbar-h');
    return () => {
      root.style.removeProperty('--tabbar-h');
    };
  }, [active]);
}

export function AppLayout() {
  const { user, counters, session } = useAuth();
  const location = useLocation();
  const bare = BARE_ROUTES.includes(location.pathname);
  const isPhone = useMediaQuery(PHONE_QUERY);
  const todayBadge = useTodayUngraded();
  useTodayBadgeCheck(user?.onboarding_state === 'done', location.pathname);
  useTabBarHeight(isPhone && !bare);

  const badges: ShellBadges = {
    today: todayBadge,
    bank: (counters?.suggestions_open ?? 0) + (counters?.attention ?? 0),
  };

  return (
    <div className={cx('app-shell', bare && 'app-shell--bare')}>
      {!bare && <TopNav badges={badges} isAdmin={user?.role === 'admin'} userName={user?.display_name || user?.username} />}
      {!bare && <SwitchBar session={session} user={user} />}
      {!bare && <PasswordBanner user={user} />}
      {!bare && <ProfilePromptDialog />}
      <main className="app-main" id="main">
        <Suspense
          fallback={
            <div className="loading-screen" role="status" aria-busy="true">
              {zh.common.loading}
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
      {!bare && <TabBar badges={badges} />}
    </div>
  );
}
