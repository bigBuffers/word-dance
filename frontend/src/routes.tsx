// Route table (FRONTEND.md §2) — FROZEN CONTRACT (TASKS P0 step 8). Pages are lazy (per-route code
// splitting); the guards come from auth/AuthContext. `RequireOnboarded` wraps ONLY `/`, `/today`,
// `/study`, `/listen`, `/history` and `/history/:batchId`; vocab / bank / screen / word detail / settings are
// browsable before onboarding (DESIGN §6.2). `<AppLayout/>` (components/layout, WP7) is the shell of every authenticated page.
// Slice 1-B: `/children` (the guardian's children page, under the shell, no onboarding guard — the page itself sends non-guardians to
// /settings) and the guest page `/child-login` (a child's device signs in with the 8-digit code of endpoint 99 → 107).
// Listen mode: `/listen` (the audio-first player of today's words, endpoint 123) — onboarded like `/study` and bare like it (no shell).
import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router';
import { RequireAdmin, RequireAuth, RequireGuest, RequireNotOnboarded, RequireOnboarded } from '@/auth/AuthContext';
import { AppLayout } from '@/components/layout/AppLayout';
import { zh } from '@/i18n/zh';

const LoginPage = lazy(() => import('@/pages/LoginPage'));
const RegisterPage = lazy(() => import('@/pages/RegisterPage'));
const ForgotPasswordPage = lazy(() => import('@/pages/ForgotPasswordPage'));
const WelcomePage = lazy(() => import('@/pages/WelcomePage'));
const TodayPage = lazy(() => import('@/pages/TodayPage'));
const StudyPage = lazy(() => import('@/pages/StudyPage'));
const ListenPage = lazy(() => import('@/pages/ListenPage'));
const ScreenPage = lazy(() => import('@/pages/ScreenPage'));
const ScreenRunPage = lazy(() => import('@/pages/ScreenRunPage'));
const VocabPage = lazy(() => import('@/pages/VocabPage'));
const WordDetailPage = lazy(() => import('@/pages/WordDetailPage'));
const BankPage = lazy(() => import('@/pages/BankPage'));
const AddWordsPage = lazy(() => import('@/pages/AddWordsPage'));
const SuggestionsPage = lazy(() => import('@/pages/SuggestionsPage'));
const HistoryPage = lazy(() => import('@/pages/HistoryPage'));
const BatchPage = lazy(() => import('@/pages/BatchPage'));
const SettingsPage = lazy(() => import('@/pages/SettingsPage'));
const ChildrenPage = lazy(() => import('@/pages/ChildrenPage'));
const AssignPage = lazy(() => import('@/pages/AssignPage'));
const ChildLoginPage = lazy(() => import('@/pages/ChildLoginPage'));
const AdminPage = lazy(() => import('@/pages/AdminPage'));
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'));

/** Path builders so links never hard-code route strings. */
export const routePaths = {
  login: '/login',
  register: '/register',
  forgot: '/forgot',
  childLogin: '/child-login',
  welcome: '/welcome',
  home: '/',
  today: '/today',
  study: '/study',
  studyBatch: (batchId: number) => `/study?batch=${batchId}`,
  listen: '/listen',
  screen: '/screen',
  screenRun: (stage: string) => `/screen/${encodeURIComponent(stage)}`,
  vocab: '/vocab',
  word: (idOrLemma: number | string) => `/words/${encodeURIComponent(String(idOrLemma))}`,
  bank: '/bank',
  bankAdd: '/bank/add',
  bankAddPrefill: (text: string) => `/bank/add?prefill=${encodeURIComponent(text)}`,
  bankSuggestions: '/bank/suggestions',
  history: '/history',
  batch: (batchId: number) => `/history/${batchId}`,
  settings: '/settings',
  children: '/children',
  assign: '/assign',
  admin: '/admin',
} as const;

/**
 * The static legal pages (frontend/public/legal/*.html, served by the backend's dist mount outside the SPA): plain
 * `<a href>` links, never `<Link>` — docs/AUTH_SIGNUP_DESIGN.md §5.2, FRONTEND §2.
 */
export const legalUrls = {
  terms: '/legal/terms.html',
  privacy: '/legal/privacy.html',
  children: '/legal/children.html',
  licenses: '/legal/licenses.html',
} as const;

function PageFallback() {
  return (
    <div className="loading-screen" role="status" aria-busy="true">
      {zh.common.loading}
    </div>
  );
}

export function AppRoutes() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route element={<RequireGuest />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot" element={<ForgotPasswordPage />} />
          <Route path="/child-login" element={<ChildLoginPage />} />
        </Route>

        <Route element={<RequireAuth />}>
          <Route element={<RequireNotOnboarded />}>
            <Route path="/welcome" element={<WelcomePage />} />
          </Route>

          <Route element={<AppLayout />}>
            <Route element={<RequireOnboarded />}>
              <Route path="/" element={<Navigate to="/today" replace />} />
              <Route path="/today" element={<TodayPage />} />
              <Route path="/study" element={<StudyPage />} />
              <Route path="/listen" element={<ListenPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/history/:batchId" element={<BatchPage />} />
            </Route>

            <Route path="/screen" element={<ScreenPage />} />
            <Route path="/screen/:stage" element={<ScreenRunPage />} />
            <Route path="/vocab" element={<VocabPage />} />
            <Route path="/words/:idOrLemma" element={<WordDetailPage />} />
            <Route path="/bank" element={<BankPage />} />
            <Route path="/bank/add" element={<AddWordsPage />} />
            <Route path="/bank/suggestions" element={<SuggestionsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/children" element={<ChildrenPage />} />
            <Route path="/assign" element={<AssignPage />} />

            <Route element={<RequireAdmin />}>
              <Route path="/admin" element={<AdminPage />} />
            </Route>
          </Route>
        </Route>

        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  );
}
