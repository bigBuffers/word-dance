// AuthContext — session state (FRONTEND.md §3) and the route guards of FRONTEND §2.
//
// Loads `GET /api/auth/me` once; exposes `user`, `settings`, `server`, `counters`, `loading`,
// `login()`, `register()`, `logout()`, `refresh()`, `refreshCounters()`, `updateSettings()`.
// A 401 `unauthorized` anywhere (the client's `auth:expired` event) clears the context, which makes
// `<RequireAuth/>` redirect to `/login?next=…`. For guests the public `GET /api/health` flags
// (`needs_setup`, `registration_mode`) are exposed as `health` for the login/register pages.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Navigate, Outlet, useLocation, useSearchParams } from 'react-router';
import { AUTH_EXPIRED_EVENT, AUTH_SIGNED_OUT_EVENT, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { HealthResponse, RegisterBody, SettingsUpdate } from '@/api/endpoints';
import type { Counters, ServerFlags, Settings, User } from '@/api/types';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';

export interface AuthState {
  user: User | null;
  settings: Settings | null;
  server: ServerFlags | null;
  counters: Counters | null;
  /** `GET /api/health` flags, fetched while logged out (login/register pages). */
  health: HealthResponse | null;
  /** True until the first `/api/auth/me` attempt has settled. */
  loading: boolean;
}

export interface AuthContextValue extends AuthState {
  login(username: string, password: string): Promise<void>;
  register(body: RegisterBody): Promise<void>;
  logout(): Promise<void>;
  /** Re-fetches `/api/auth/me` (user, settings, server flags, counters). */
  refresh(): Promise<void>;
  /** Same request as `refresh()`; call after suggestion accept/reject/undo, bank adds/import and attention resolution. */
  refreshCounters(): Promise<void>;
  /** `PUT /api/settings` with a partial body; replaces the cached settings. */
  updateSettings(partial: SettingsUpdate): Promise<Settings>;
  /** Patch the cached user/settings after account or onboarding calls that return them. */
  applySession(patch: { user?: User; settings?: Settings }): void;
  refreshHealth(): Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const signedOut = { user: null, settings: null, counters: null } as const;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, settings: null, server: null, counters: null, health: null, loading: true });

  // Whether a session is currently held — lets the auth:expired listener ignore the expected 401 of
  // the bootstrap /me call (the client dispatches the event for every 401 `unauthorized`).
  const hasSession = useRef(false);
  useEffect(() => {
    hasSession.current = state.user !== null;
  }, [state.user]);

  const refreshHealth = useCallback(async () => {
    try {
      const health = await endpoints.getHealth();
      setState((s) => ({ ...s, health }));
    } catch {
      /* keep the previous flags; the page shows its own error if it needs them */
    }
  }, []);

  /** Loads /api/auth/me; resolves false when logged out (401), throws on other failures. */
  const loadMe = useCallback(async (): Promise<boolean> => {
    try {
      const me = await endpoints.getMe();
      setState((s) => ({ ...s, user: me.user, settings: me.settings, server: me.server, counters: me.counters }));
      return true;
    } catch (e) {
      if (isApiError(e) && e.status === 401) {
        setState((s) => ({ ...s, ...signedOut }));
        return false;
      }
      throw e;
    }
  }, []);

  // Bootstrap: one /me call; guests also get the public health flags.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const authed = await loadMe();
        if (!authed && !cancelled) await refreshHealth();
      } catch {
        /* server unreachable: stay signed out, pages surface their own errors */
      } finally {
        if (!cancelled) setState((s) => ({ ...s, loading: false }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadMe, refreshHealth]);

  // Session expired anywhere → clear the context (guards redirect to /login?next=).
  useEffect(() => {
    const onExpired = () => {
      if (!hasSession.current) return;
      hasSession.current = false;
      setState((s) => ({ ...s, ...signedOut }));
      void refreshHealth();
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [refreshHealth]);

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await endpoints.login({ username, password });
      setState((s) => ({ ...s, user: res.user, settings: res.settings }));
      await loadMe().catch(() => undefined); // server flags + counters; the session itself is already established
    },
    [loadMe],
  );

  const register = useCallback(
    async (body: RegisterBody) => {
      const res = await endpoints.register(body);
      setState((s) => ({ ...s, user: res.user, settings: res.settings }));
      await loadMe().catch(() => undefined);
    },
    [loadMe],
  );

  const logout = useCallback(async () => {
    try {
      await endpoints.logout();
    } finally {
      setState((s) => ({ ...s, ...signedOut }));
      window.dispatchEvent(new Event(AUTH_SIGNED_OUT_EVENT)); // an explicit sign-out (the native shell cancels its reminder on it)
      void refreshHealth();
    }
  }, [refreshHealth]);

  const refresh = useCallback(async () => {
    await loadMe();
  }, [loadMe]);

  const updateSettings = useCallback(async (partial: SettingsUpdate) => {
    const settings = await endpoints.updateSettings(partial);
    setState((s) => ({ ...s, settings }));
    return settings;
  }, []);

  const applySession = useCallback((patch: { user?: User; settings?: Settings }) => {
    setState((s) => ({ ...s, ...(patch.user ? { user: patch.user } : {}), ...(patch.settings ? { settings: patch.settings } : {}) }));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, register, logout, refresh, refreshCounters: refresh, updateSettings, applySession, refreshHealth }),
    [state, login, register, logout, refresh, updateSettings, applySession, refreshHealth],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth() must be used inside <AuthProvider>');
  return value;
}

/** Like `useAuth()` but returns null outside a provider (presentational components rendered standalone). */
export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}

// ---------------------------------------------------------------------------------------------------
// Route guards (FRONTEND §2). Each renders <Outlet/> as a layout route.
// ---------------------------------------------------------------------------------------------------

/** `/login?next=<path>` for the current location. */
export function loginPathFor(location: { pathname: string; search: string }): string {
  const next = `${location.pathname}${location.search}`;
  return next && next !== '/' ? `/login?next=${encodeURIComponent(next)}` : '/login';
}

/** Only same-origin absolute paths are honoured as a `next` target. */
export function safeNext(raw: string | null | undefined, fallback = '/today'): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return fallback;
  return raw;
}

function LoadingScreen() {
  return (
    <div className="loading-screen" role="status" aria-live="polite" aria-busy="true">
      {zh.common.loading}
    </div>
  );
}

/** Logged-in users only; guests go to `/login?next=`. */
export function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingScreen />;
  if (!user) return <Navigate to={loginPathFor(location)} replace />;
  return <Outlet />;
}

/** `onboarding_state === 'done'` only (applied to `/`, `/today`, `/study`, `/history`, `/history/:batchId`). */
export function RequireOnboarded() {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to={loginPathFor(location)} replace />;
  if (user.onboarding_state !== 'done') return <Navigate to="/welcome" replace />;
  return <Outlet />;
}

/** `/welcome`: users who have not finished onboarding; everyone else goes to `/today`. */
export function RequireNotOnboarded() {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to={loginPathFor(location)} replace />;
  if (user.onboarding_state === 'done') return <Navigate to="/today" replace />;
  return <Outlet />;
}

/** Admins only; others are sent to `/today` with a toast. */
export function RequireAdmin() {
  const { user } = useAuth();
  const location = useLocation();
  const toast = useToast();
  const forbidden = user !== null && user.role !== 'admin';
  useEffect(() => {
    if (forbidden) toast.error(zh.errors.forbidden, { id: 'forbidden' });
  }, [forbidden, toast]);
  if (!user) return <Navigate to={loginPathFor(location)} replace />;
  if (forbidden) return <Navigate to="/today" replace />;
  return <Outlet />;
}

/** Guest pages (`/login`, `/register`): a logged-in user is sent to `next` or `/today`. */
export function RequireGuest() {
  const { user, loading } = useAuth();
  const [params] = useSearchParams();
  if (loading) return <LoadingScreen />;
  if (user) return <Navigate to={safeNext(params.get('next'))} replace />;
  return <Outlet />;
}
