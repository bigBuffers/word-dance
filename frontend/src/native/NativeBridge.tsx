// NativeBridge — mounted once under the router and AuthProvider (App.tsx); renders nothing (FRONTEND §6.6, docs/MOBILE_APP.md §1).
// Installs the shell's listeners once and keeps the device's daily reminder in step with the push settings. In a browser none of
// the three effects touches the device (`isNative()` false; the sign-out listener's handler is then a no-op).
import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { AUTH_SIGNED_OUT_EVENT } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { installNativeListeners, syncDailyReminder } from '@/native/capacitor';

export function NativeBridge() {
  const navigate = useNavigate();
  const { settings, loading } = useAuth();
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const navigateRef = useRef(navigate); // `navigate` changes identity on every route change under <BrowserRouter>; install once
  navigateRef.current = navigate;

  useEffect(
    () =>
      installNativeListeners({
        navigate: (path) => void navigateRef.current(path),
        // a resume re-arms the reminder of a known session; signed out or still loading → leave the device as it is
        onResume: () => {
          if (settingsRef.current) void syncDailyReminder(settingsRef.current);
        },
      }),
    [],
  );

  // re-sync when the fields the reminder depends on change — but never from the loading state (settings null before /api/auth/me
  // answers) and never because the session is missing: a cold start offline or an expired session keeps the device's reminder
  const reminderKey = !loading && settings ? `${settings.push_enabled}|${settings.push_time}|${settings.timezone}` : '';
  useEffect(() => {
    if (reminderKey && settingsRef.current) void syncDailyReminder(settingsRef.current);
  }, [reminderKey]);

  // only an explicit sign-out (AuthContext.logout) cancels the reminder
  useEffect(() => {
    const onSignedOut = () => void syncDailyReminder(null);
    window.addEventListener(AUTH_SIGNED_OUT_EVENT, onSignedOut);
    return () => window.removeEventListener(AUTH_SIGNED_OUT_EVENT, onSignedOut);
  }, []);

  return null;
}
