// word-Dance typed endpoint wrappers — exactly one function per API.md §2 catalogue entry (1–111; 76 `GET /media/audio`
// builds its URLs in audio/serverAudio.ts and has no wrapper). FROZEN CONTRACT (TASKS P0 step 8). Each wrapper is preceded
// by `// #N METHOD /path` so coverage is checked mechanically by endpoints.test.ts (52 / 53 / 78 are URL builders for
// `<img>`). DTOs come from ./types (API.md §9); request bodies and query shapes that API.md defines only in prose are
// declared here. GET wrappers accept an optional `AbortSignal` as their last argument so `useApi` can cancel stale requests.
import { api, requestText } from './client';
import type {
  AccountKind,
  AddResponse,
  AddResult,
  AdminHealth,
  AdminOverview,
  AdminUser,
  AgeBand,
  AiCall,
  AiProvider,
  BankResponse,
  CaptchaChallenge,
  ChildLoginCode,
  ChildrenResponse,
  ChildResponse,
  CodeChannel,
  CodeLoginResponse,
  CodeSendResponse,
  Content,
  ContentState,
  Counters,
  DayStats,
  DemoResponse,
  DisputedIdentity,
  GateResponse,
  Grade,
  GradeResponse,
  ImageMeta,
  ImportResponse,
  Job,
  LookupPreview,
  MarkAction,
  Origin,
  Page,
  Report,
  ReportReason,
  ScreenResponse,
  ScreenVerdict,
  ScreenWord,
  ServerFlags,
  SessionInfo,
  SessionSummary,
  Settings,
  Stage,
  StageInfo,
  Stats,
  Suggestion,
  SuggestionResult,
  SystemEvent,
  TodayResponse,
  User,
  UserState,
  UserWord,
  WebhookTestReason,
  WordBrief,
  WordDetail,
  BatchSummary,
} from './types';

// ---------------------------------------------------------------------------------------------------
// Shapes defined in API.md prose (§3–§8), not in the §9 DTO block
// ---------------------------------------------------------------------------------------------------

/**
 * Endpoint 1. `status:'degraded'` comes with HTTP 503 (thrown as ApiError), so a resolved value is always `ok`.
 * `sms_enabled` / `email_enabled` decide which code sign-in entries the login page offers (API.md §3.1), `captcha` whether
 * a public code send (80, 90) must carry a `CaptchaToken` from endpoint 79.
 */
export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  registration_mode: ServerFlags['registration_mode'];
  needs_setup: boolean;
  sms_enabled: boolean;
  email_enabled: boolean;
  captcha: boolean;
  time: string;
}
export interface RegisterBody {
  username: string;
  password: string;
  display_name?: string;
  email?: string;
  invite_code?: string;
}
export interface LoginBody {
  username: string;
  password: string;
}
export interface AuthResponse {
  user: User;
  settings: Settings;
}
/** Endpoint 5. `session` (slice 1-B): the guardian who switched this device into a child account, and a guardian's own gate stamp. */
export interface MeResponse {
  user: User;
  settings: Settings;
  server: ServerFlags;
  counters: Counters;
  session: SessionInfo;
}
export interface AccountUpdateBody {
  display_name?: string | null;
  email?: string | null;
}
/** Endpoint 7: exactly one of `current_password` (an account with `has_password`) / `code` (a `reauth` code of endpoint 85). */
export interface PasswordChangeBody {
  current_password?: string;
  code?: string;
  new_password: string;
}
/**
 * Endpoint 8 — the same one-of dispatch as endpoint 7. `delete_children` (slice 1-B): a guardian with children gets 409
 * `has_children` (`details.children: {id, display_name}[]`) until it is true — then a child with its own phone is set free
 * and the others are deleted with the guardian.
 */
export interface AccountDeleteBody {
  password?: string;
  code?: string;
  delete_children?: boolean;
}
/** Endpoint 79's challenge handed back with the digits the learner read (endpoints 80, 90). */
export interface CaptchaToken {
  id: string;
  exp: number;
  sig: string;
  answer: string;
}
/** Endpoint 80. `consent` must be true for `purpose:'login'` (400 `consent_required`). */
export interface CodeSendBody {
  channel: CodeChannel;
  target: string;
  purpose: 'login' | 'reset_password';
  consent?: boolean;
  captcha?: CaptchaToken;
}
/** Endpoint 81 — `invite_code` is required in `invite` mode for a new account, optional in `open` / `verified`. */
export interface CodeLoginBody {
  channel: CodeChannel;
  target: string;
  code: string;
  invite_code?: string;
}
export interface ChallengeEmailBody {
  token: string;
}
/** Endpoint 83: exactly one of `password` / `code` (the e-mail code of endpoint 82). */
export interface ChallengeConfirmBody {
  token: string;
  password?: string;
  code?: string;
}
export interface ChallengeDisputeBody {
  token: string;
  invite_code?: string;
}
/** Endpoint 85. `target` only for `bind_phone` (the new number); `rebind_phone` / `reauth` go to the bound channel. */
export interface AccountCodeBody {
  channel: CodeChannel;
  purpose: 'bind_phone' | 'rebind_phone' | 'reauth';
  target?: string;
}
export interface PhoneBindBody {
  target: string;
  code: string;
}
/** Endpoint 87: exactly one of `password` / `code` (a `reauth` code of endpoint 85). */
export interface PhoneUnbindBody {
  password?: string;
  code?: string;
}
export interface PhoneRebindBody {
  code_old: string;
  target_new: string;
  code_new: string;
}
/**
 * Endpoint 89 — the first-time setup of a code-created account (`User.needs_profile`); `u14` is refused by the server.
 * `account_kind` (slice 1-B, default `learner`): `guardian` requires `age_band: 'adult'` and — unless the account has a
 * verified e-mail — a `password` (400 `validation_error` on `fields.age_band` / `fields.password`).
 */
export interface ProfileBody {
  display_name: string;
  age_band: Exclude<AgeBand, 'u14'>;
  account_kind?: AccountKind;
  username?: string;
  password?: string;
}
export interface ForgotPasswordBody {
  identifier: string;
  captcha?: CaptchaToken;
}
export interface ResetPasswordBody {
  identifier: string;
  code: string;
  new_password: string;
}
// ---- guardian and child accounts (slice 1-B, API.md §3.2, docs/AUTH_SIGNUP_DESIGN.md §5.2) ----
/** Endpoint 95. `pin` is required (6 digits) while the guardian has no PIN and refused once one exists; `username` / `password` both or neither. */
export interface ChildCreateBody {
  display_name: string;
  pin?: string;
  username?: string;
  password?: string;
}
/** Endpoint 96 — at least one key; a `password` needs a non-placeholder username (the current one or the one in this body). */
export interface ChildUpdateBody {
  display_name?: string;
  username?: string;
  password?: string;
}
/** Endpoint 100: the phone the child will own (E.164), the `bind_phone` code goes there. */
export interface ChildPhoneCodeBody {
  target: string;
}
/** Endpoint 101: the code of endpoint 100 + the child's new password → the child is set free (irreversible). */
export interface ChildEmancipateBody {
  target: string;
  code: string;
  password: string;
}
/** Endpoints 102 / 105 — exactly one of `pin` (6 digits) / `password` / `code` (a `reauth` code of endpoint 85 or 106). */
export interface GateBody {
  pin?: string;
  password?: string;
  code?: string;
}
/** Endpoint 103: the 6-digit guardian PIN (no repeats, no straight runs). */
export interface PinBody {
  pin: string;
}
/** Endpoint 106: where the `reauth` code for endpoint 105 goes — the guardian's phone or verified e-mail. */
export interface SwitchCodeBody {
  channel: CodeChannel;
}
/** Endpoint 107: the 8-digit one-time login code of endpoint 99. */
export interface ChildLoginBody {
  code: string;
}
/** Endpoint 108: the guardian's phone (E.164) — the claim code goes there. */
export interface GuardianClaimCodeBody {
  target: string;
}
/** Endpoint 109: the claim code + the claimant's age band (a child is `u14` or `14plus`). */
export interface GuardianClaimBody {
  target: string;
  code: string;
  age_band: Exclude<AgeBand, 'adult'>;
}
/** Endpoint 110: the legacy profile-prompt declaration — `guardian` requires `adult`. */
export interface DeclareBody {
  account_kind: AccountKind;
  age_band: Exclude<AgeBand, 'u14'>;
}
export type ExportFormat = 'csv' | 'json';
export interface OnboardingBody {
  stages: Stage[];
  current_stage: Stage;
  timezone: string;
  push_time: string;
}
export interface OnboardingResponse {
  settings: Settings;
  onboarding_state: 'screen';
}
export interface OnboardingCompleteResponse {
  onboarding_state: 'done';
}
/** Writable subset of `Settings` for `PUT /api/settings` (any subset; read-only fields excluded). */
export type SettingsUpdate = Partial<Omit<Settings, 'next_push_at' | 'email_verified' | 'updated_at'>>;
export interface TimezonesResponse {
  items: string[];
}
/** Endpoint 17. `error` is the English transport diagnostic kept for the admin ledger — the UI renders `reason` (SettingsPage.webhookFailureReason), never `error`. */
export interface WebhookTestResponse {
  ok: boolean;
  http_status: number | null;
  error: string | null;
  reason: WebhookTestReason | null;
}
export interface EmailTestResponse {
  queued: true;
}
export interface StagesResponse {
  items: StageInfo[];
}

export type VocabStageFilter = Stage | 'all';
export type VocabStatusFilter = 'all' | 'unmarked' | 'unfamiliar' | 'known' | 'mastered';
export type VocabSort = 'freq' | 'alpha' | 'difficulty';
/** Query of endpoint 20 (booleans are sent as 0|1). */
export type VocabQuery = {
  stage?: VocabStageFilter;
  new_only?: boolean;
  q?: string;
  status?: VocabStatusFilter;
  sort?: VocabSort;
  letter?: string;
  page?: number;
  page_size?: number;
};
export type VocabLettersQuery = Omit<VocabQuery, 'letter' | 'q' | 'page' | 'page_size'>;
export interface LetterCount {
  letter: string;
  count: number;
}
export interface LettersResponse {
  items: LetterCount[];
}
export interface ContentResponse {
  state: ContentState;
  content: Content | null;
  eta_s: number | null;
  deferred_until: string | null;
}
export type MarkContext = 'browse' | 'detail' | 'bank' | 'today' | 'screen_page';
export interface MarkBody {
  action: MarkAction;
  note?: string;
  context?: MarkContext;
}
export interface MarkResponse {
  word_id: number;
  state: UserState | null;
  mine: UserWord | null;
  status: 'added' | 'readded' | 'exists' | 'noop' | 'restored';
}
export type BatchMarkAction = 'unfamiliar' | 'known';
export interface BatchMarkBody {
  items: { word_id: number; action: BatchMarkAction }[];
}
export interface BatchMarkResponse {
  updated: number;
  results: { word_id: number; ok: boolean; state: UserState | null; error: string | null }[];
}
export type ReportTarget = 'content' | 'image' | 'dictionary';
export interface ReportBody {
  target: ReportTarget;
  reason: ReportReason;
  note?: string;
}
export interface CreatedResponse {
  id: number;
}
export interface ImageRefreshResponse {
  job_id: number;
  image_state: 'queued';
}
export interface ContentRequestResponse {
  job_id: number | null;
  state: ContentState;
}
export type ScreenStage = Stage | 'auto';
export interface ScreenNextResponse {
  items: ScreenWord[];
  remaining: number;
}
export type ScreenContext = 'screen_page' | 'onboarding';
export interface ScreenVerdictBody {
  client_event_id: string;
  word_id: number;
  verdict: ScreenVerdict;
  context?: ScreenContext;
}
export type BankStateFilter = 'active' | 'new' | 'learning' | 'mastered' | 'known' | 'removed' | 'attention';
export type BankSort = 'added' | 'due' | 'alpha' | 'ease' | 'times_added';
/** Query of endpoint 33. */
export type BankQuery = {
  state?: BankStateFilter;
  q?: string;
  sort?: BankSort;
  origin?: Origin;
  page?: number;
  page_size?: number;
};
export interface BankAddBody {
  text: string;
  note?: string;
  study_today?: boolean;
}
export interface BankAddWordBody {
  word_id: number;
  note?: string;
  study_today?: boolean;
}
export type AttentionDecision = 'keep' | 'retry';
/** Body of endpoint 36 — at least one key. */
export interface BankPatchBody {
  note?: string | null;
  attention?: AttentionDecision;
}
export interface AcceptBankSuggestionResponse {
  removed_word_id: number;
  mine: UserWord;
}
export interface JobQueuedResponse {
  job_id: number;
}
export type ImportFormat = 'csv' | 'json';
/** Body of endpoint 75 — for JSON the client posts only `{version, words}` (API.md 11/75). */
export interface ImportBody {
  format: ImportFormat;
  data: string;
}
export type SuggestionStatusFilter = 'open' | 'all';
export interface SuggestionsResponse {
  items: Suggestion[];
  open_count: number;
}
export interface SuggestionResultResponse {
  result: SuggestionResult;
}
export interface GradeBody {
  client_event_id: string;
  grade: Grade | ScreenVerdict;
  elapsed_ms?: number;
}
export type MoreSource = 'new' | 'screen';
export interface MoreBody {
  source: MoreSource;
  /** 1..20, default 10. */
  count?: number;
}
export interface CompleteResponse {
  summary: SessionSummary;
}
/** Query of endpoint 48 (`YYYY-MM-DD`, ≤ 370 days). */
export type HistoryQuery = { from?: string; to?: string };
export interface HistoryResponse {
  days: DayStats[];
  streak_days: number;
  longest_streak: number;
}

// admin
export type AdminUsersQuery = { q?: string; page?: number; page_size?: number };
export interface AdminUserUpdateBody {
  is_active?: boolean;
  role?: 'user' | 'admin';
  new_password?: string;
}
export interface AdminInvite {
  id: number;
  max_uses: number;
  uses: number;
  expires_at: string | null;
  note: string | null;
  created_at: string;
  created_by: string | number | null;
}
export interface AdminInvitesResponse {
  items: AdminInvite[];
}
export interface AdminInviteCreateBody {
  max_uses?: number;
  expires_in_days?: number;
  note?: string;
}
/** `code` is shown once (endpoint 59). */
export interface AdminInviteCreated {
  id: number;
  code: string;
  expires_at: string | null;
}
export type AdminJobsQuery = { status?: string; type?: string; page?: number; page_size?: number };
export interface RequeuedResponse {
  requeued: number;
}
export interface ProcessedResponse {
  processed: number;
}
export type AiCallsResponse = Page<AiCall> & { today_usd: number; month_usd: number; avg_cost_per_word_7d: number | null };
export interface AiPauseResponse {
  paused: boolean;
  paused_until: string | null;
}
export interface AiProbeResponse {
  ok: boolean;
  flag_tier: 0 | 1;
  cost_usd: number;
  duration_ms: number;
  model_used: string | null;
  error: string | null;
}
export type PrewarmStage = Stage | 'all';
export interface PrewarmBody {
  stage: PrewarmStage;
  /** 1..2000 */
  limit: number;
  /** 0.1..50 */
  max_budget_usd: number;
}
export interface PrewarmResponse {
  job_id: number;
  planned: number;
}
export type RefetchProvider = 'wikimedia' | 'openverse' | 'pixabay' | 'pexels' | 'claude_svg';
export interface RefetchImageBody {
  provider?: RefetchProvider;
  query?: string;
}
export type ReportStatusFilter = 'open' | 'resolved' | 'dismissed';
export type AdminReportsQuery = { status?: ReportStatusFilter; page?: number; page_size?: number };
export interface AdminReportResolveBody {
  status: 'resolved' | 'dismissed';
  regenerate?: boolean;
  refetch_image?: boolean;
}
export interface AdminConfigEntry {
  key: string;
  value: string;
  source: 'env' | 'default';
}
export interface AdminConfigResponse {
  entries: AdminConfigEntry[];
}
export interface AdminPushRunResponse {
  batch_id: number;
  status: string;
}

const seg = (v: string | number) => encodeURIComponent(String(v));

// ---------------------------------------------------------------------------------------------------
// §3 Health, auth, account, onboarding
// ---------------------------------------------------------------------------------------------------

// #1 GET /api/health
export const getHealth = (signal?: AbortSignal) => api.get<HealthResponse>('/api/health', undefined, signal);
// #2 POST /api/auth/register
export const register = (body: RegisterBody) => api.post<AuthResponse>('/api/auth/register', body);
// #3 POST /api/auth/login
export const login = (body: LoginBody) => api.post<AuthResponse>('/api/auth/login', body);
// #4 POST /api/auth/logout
export const logout = () => api.post<void>('/api/auth/logout');
// #5 GET /api/auth/me
export const getMe = (signal?: AbortSignal) => api.get<MeResponse>('/api/auth/me', undefined, signal);
// #6 PUT /api/account
export const updateAccount = (body: AccountUpdateBody) => api.put<{ user: User }>('/api/account', body);
// #7 POST /api/account/password
export const changePassword = (body: PasswordChangeBody) => api.post<void>('/api/account/password', body);
// #8 DELETE /api/account
export const deleteAccount = (body: AccountDeleteBody) => api.delete<void>('/api/account', body);
// #9 POST /api/account/email/request-code
export const requestEmailCode = () => api.post<CodeSendResponse>('/api/account/email/request-code');
// #10 POST /api/account/email/verify
export const verifyEmail = (code: string) => api.post<{ user: User }>('/api/account/email/verify', { code });
// #11 GET /api/account/export — returns the file body as text (`word-dance-export-YYYYMMDD.csv|json`)
export const exportAccount = (format: ExportFormat, signal?: AbortSignal) =>
  requestText('GET', '/api/account/export', { query: { format }, signal });
/** URL of endpoint 11 for a direct browser download (cookie session). */
export const exportAccountUrl = (format: ExportFormat) => `/api/account/export?format=${format}`;
// #12 POST /api/onboarding
export const saveOnboarding = (body: OnboardingBody) => api.post<OnboardingResponse>('/api/onboarding', body);
// #13 POST /api/onboarding/complete
export const completeOnboarding = () => api.post<OnboardingCompleteResponse>('/api/onboarding/complete');

// ---------------------------------------------------------------------------------------------------
// §3.1 Sign-in by verification code (slice 1-A, docs/AUTH_SIGNUP_DESIGN.md §5.2) — public unless noted
// ---------------------------------------------------------------------------------------------------

// #77 GET /api/demo
export const getDemo = (signal?: AbortSignal) => api.get<DemoResponse>('/api/demo', undefined, signal);
// #78 GET /media/demo/{word_id}.svg — the demo word's card (public, allow-listed ids only; loaded by <img>)
export const demoCardUrl = (wordId: number) => `/media/demo/${seg(wordId)}.svg`;
// #79 GET /api/auth/captcha
export const getCaptcha = (signal?: AbortSignal) => api.get<CaptchaChallenge>('/api/auth/captcha', undefined, signal);
// #80 POST /api/auth/code
export const sendCode = (body: CodeSendBody) => api.post<CodeSendResponse>('/api/auth/code', body);
// #81 POST /api/auth/code/login
export const loginWithCode = (body: CodeLoginBody) => api.post<CodeLoginResponse>('/api/auth/code/login', body);
// #82 POST /api/auth/challenge/email
export const challengeEmail = (body: ChallengeEmailBody) => api.post<CodeSendResponse>('/api/auth/challenge/email', body);
// #83 POST /api/auth/challenge/confirm
export const challengeConfirm = (body: ChallengeConfirmBody) => api.post<AuthResponse>('/api/auth/challenge/confirm', body);
// #84 POST /api/auth/challenge/dispute
export const challengeDispute = (body: ChallengeDisputeBody) => api.post<AuthResponse>('/api/auth/challenge/dispute', body);
// #85 POST /api/account/code
export const requestAccountCode = (body: AccountCodeBody) => api.post<CodeSendResponse>('/api/account/code', body);
// #86 POST /api/account/identities/phone
export const bindPhone = (body: PhoneBindBody) => api.post<{ user: User }>('/api/account/identities/phone', body);
// #87 DELETE /api/account/identities/phone
export const unbindPhone = (body: PhoneUnbindBody) => api.delete<{ user: User }>('/api/account/identities/phone', body);
// #88 POST /api/account/identities/phone/rebind
export const rebindPhone = (body: PhoneRebindBody) => api.post<{ user: User }>('/api/account/identities/phone/rebind', body);
// #89 POST /api/account/profile
export const saveProfile = (body: ProfileBody) => api.post<{ user: User }>('/api/account/profile', body);
// #90 POST /api/auth/password/forgot
export const forgotPassword = (body: ForgotPasswordBody) => api.post<CodeSendResponse>('/api/auth/password/forgot', body);
// #91 POST /api/auth/password/reset
export const resetPassword = (body: ResetPasswordBody) => api.post<void>('/api/auth/password/reset', body);

// ---------------------------------------------------------------------------------------------------
// §3.2 Guardian and child accounts (slice 1-B, docs/AUTH_SIGNUP_DESIGN.md §5.1 / §5.2) — `G` = a guardian in its own
// session, `G+gate` = with the 10-minute guardian-gate stamp of endpoint 102 (403 `guardian_gate_required` otherwise)
// ---------------------------------------------------------------------------------------------------

// #94 GET /api/guardian/children
export const getChildren = (signal?: AbortSignal) => api.get<ChildrenResponse>('/api/guardian/children', undefined, signal);
// #95 POST /api/guardian/children
export const createChild = (body: ChildCreateBody) => api.post<ChildResponse>('/api/guardian/children', body);
// #96 PATCH /api/guardian/children/{id}
export const updateChild = (childId: number, body: ChildUpdateBody) => api.patch<ChildResponse>(`/api/guardian/children/${seg(childId)}`, body);
// #97 DELETE /api/guardian/children/{id}
export const deleteChild = (childId: number) => api.delete<void>(`/api/guardian/children/${seg(childId)}`);
// #98 POST /api/guardian/children/{id}/sessions/revoke
export const revokeChildSessions = (childId: number) => api.post<void>(`/api/guardian/children/${seg(childId)}/sessions/revoke`);
// #99 POST /api/guardian/children/{id}/login-code
export const issueChildLoginCode = (childId: number) => api.post<ChildLoginCode>(`/api/guardian/children/${seg(childId)}/login-code`);
// #100 POST /api/guardian/children/{id}/code
export const requestChildPhoneCode = (childId: number, body: ChildPhoneCodeBody) => api.post<CodeSendResponse>(`/api/guardian/children/${seg(childId)}/code`, body);
// #101 POST /api/guardian/children/{id}/emancipate
export const emancipateChild = (childId: number, body: ChildEmancipateBody) => api.post<ChildResponse>(`/api/guardian/children/${seg(childId)}/emancipate`, body);
// #102 POST /api/guardian/gate
export const passGate = (body: GateBody) => api.post<GateResponse>('/api/guardian/gate', body);
// #103 PUT /api/guardian/pin
export const setGuardianPin = (body: PinBody) => api.put<void>('/api/guardian/pin', body);
// #104 POST /api/auth/switch/{child_id} — the child's AuthResponse + cookie (this device's guardian session is replaced)
export const switchToChild = (childId: number) => api.post<AuthResponse>(`/api/auth/switch/${seg(childId)}`);
// #105 POST /api/auth/switch/back — the guardian's AuthResponse + cookie (the guardian gate passed on the way)
export const switchBack = (body: GateBody) => api.post<AuthResponse>('/api/auth/switch/back', body);
// #106 POST /api/auth/switch/code
export const requestSwitchCode = (body: SwitchCodeBody) => api.post<CodeSendResponse>('/api/auth/switch/code', body);
// #107 POST /api/auth/child-login
export const childLogin = (body: ChildLoginBody) => api.post<AuthResponse>('/api/auth/child-login', body);
// #108 POST /api/account/guardian/code
export const requestGuardianClaimCode = (body: GuardianClaimCodeBody) => api.post<CodeSendResponse>('/api/account/guardian/code', body);
// #109 POST /api/account/guardian
export const claimGuardian = (body: GuardianClaimBody) => api.post<{ user: User }>('/api/account/guardian', body);
// #110 POST /api/account/declare
export const declareAccount = (body: DeclareBody) => api.post<{ user: User }>('/api/account/declare', body);
// #111 POST /api/account/declare/skip
export const skipDeclare = () => api.post<void>('/api/account/declare/skip');

// ---------------------------------------------------------------------------------------------------
// §4 Settings
// ---------------------------------------------------------------------------------------------------

// #14 GET /api/settings
export const getSettings = (signal?: AbortSignal) => api.get<Settings>('/api/settings', undefined, signal);
// #15 PUT /api/settings
export const updateSettings = (body: SettingsUpdate) => api.put<Settings>('/api/settings', body);
// #16 GET /api/settings/timezones
export const getTimezones = (all = false, signal?: AbortSignal) => api.get<TimezonesResponse>('/api/settings/timezones', { all }, signal);
// #17 POST /api/settings/webhook/test
export const testWebhook = () => api.post<WebhookTestResponse>('/api/settings/webhook/test');
// #18 POST /api/settings/email/test
export const testEmail = () => api.post<EmailTestResponse>('/api/settings/email/test');

// ---------------------------------------------------------------------------------------------------
// §5 Vocabulary, words, screening
// ---------------------------------------------------------------------------------------------------

// #19 GET /api/stages
export const getStages = (signal?: AbortSignal) => api.get<StagesResponse>('/api/stages', undefined, signal);
// #20 GET /api/vocab
export const getVocab = (query: VocabQuery = {}, signal?: AbortSignal) => api.get<Page<WordBrief>>('/api/vocab', query, signal);
// #21 GET /api/vocab/letters
export const getVocabLetters = (query: VocabLettersQuery = {}, signal?: AbortSignal) => api.get<LettersResponse>('/api/vocab/letters', query, signal);
// #22 GET /api/lookup
export const lookup = (q: string, signal?: AbortSignal) => api.get<LookupPreview>('/api/lookup', { q }, signal);
// #23 GET /api/words/{id_or_lemma}
export const getWord = (idOrLemma: number | string, signal?: AbortSignal) => api.get<WordDetail>(`/api/words/${seg(idOrLemma)}`, undefined, signal);
// #24 GET /api/words/{id}/content
export const getWordContent = (wordId: number, signal?: AbortSignal) => api.get<ContentResponse>(`/api/words/${seg(wordId)}/content`, undefined, signal);
// #25 GET /api/words/{id}/image
export const getWordImage = (wordId: number, signal?: AbortSignal) => api.get<ImageMeta>(`/api/words/${seg(wordId)}/image`, undefined, signal);
// #26 POST /api/words/{id}/mark
export const markWord = (wordId: number, body: MarkBody) => api.post<MarkResponse>(`/api/words/${seg(wordId)}/mark`, body);
// #27 POST /api/words/batch-mark
export const batchMark = (body: BatchMarkBody) => api.post<BatchMarkResponse>('/api/words/batch-mark', body);
// #28 POST /api/words/{id}/report
export const reportWord = (wordId: number, body: ReportBody) => api.post<CreatedResponse>(`/api/words/${seg(wordId)}/report`, body);
// #29 POST /api/words/{id}/image/refresh
export const refreshWordImage = (wordId: number) => api.post<ImageRefreshResponse>(`/api/words/${seg(wordId)}/image/refresh`);
// #30 POST /api/words/{id}/content/request
export const requestWordContent = (wordId: number) => api.post<ContentRequestResponse>(`/api/words/${seg(wordId)}/content/request`);
// #31 GET /api/screen/next
export const getScreenNext = (stage: ScreenStage, count = 30, signal?: AbortSignal) =>
  api.get<ScreenNextResponse>('/api/screen/next', { stage, count }, signal);
// #32 POST /api/screen/verdict
export const postScreenVerdict = (body: ScreenVerdictBody) => api.post<ScreenResponse>('/api/screen/verdict', body);

// ---------------------------------------------------------------------------------------------------
// §6 Bank and suggestions
// ---------------------------------------------------------------------------------------------------

// #33 GET /api/bank
export const getBank = (query: BankQuery = {}, signal?: AbortSignal) => api.get<BankResponse>('/api/bank', query, signal);
// #34 POST /api/bank/add
export const addWords = (body: BankAddBody) => api.post<AddResponse>('/api/bank/add', body);
// #35 POST /api/bank/add-word
export const addWord = (body: BankAddWordBody) => api.post<AddResult>('/api/bank/add-word', body);
// #36 PATCH /api/bank/{word_id}
export const patchBankEntry = (wordId: number, body: BankPatchBody) => api.patch<UserWord>(`/api/bank/${seg(wordId)}`, body);
// #37 POST /api/bank/{word_id}/accept-suggestion
export const acceptBankSuggestion = (wordId: number) => api.post<AcceptBankSuggestionResponse>(`/api/bank/${seg(wordId)}/accept-suggestion`);
// #38 POST /api/bank/consolidate
export const consolidateBank = () => api.post<JobQueuedResponse>('/api/bank/consolidate');
// #39 GET /api/suggestions
export const getSuggestions = (status: SuggestionStatusFilter = 'open', signal?: AbortSignal) =>
  api.get<SuggestionsResponse>('/api/suggestions', { status }, signal);
// #40 POST /api/suggestions/{id}/accept
export const acceptSuggestion = (id: number) => api.post<SuggestionResultResponse>(`/api/suggestions/${seg(id)}/accept`);
// #41 POST /api/suggestions/{id}/reject
export const rejectSuggestion = (id: number) => api.post<Record<string, never>>(`/api/suggestions/${seg(id)}/reject`);
// #42 POST /api/suggestions/{id}/undo
export const undoSuggestion = (id: number) => api.post<SuggestionResultResponse>(`/api/suggestions/${seg(id)}/undo`);

// ---------------------------------------------------------------------------------------------------
// §7 Today, history, stats
// ---------------------------------------------------------------------------------------------------

// #43 GET /api/today
export const getToday = (signal?: AbortSignal) => api.get<TodayResponse>('/api/today', undefined, signal);
// #44 POST /api/today/build
export const buildToday = () => api.post<TodayResponse>('/api/today/build');
// #45 POST /api/today/items/{item_id}/grade
export const gradeItem = (itemId: number, body: GradeBody) => api.post<GradeResponse>(`/api/today/items/${seg(itemId)}/grade`, body);
// #46 POST /api/today/more
export const requestMore = (body: MoreBody) => api.post<TodayResponse>('/api/today/more', body);
// #47 POST /api/today/complete
export const completeToday = () => api.post<CompleteResponse>('/api/today/complete');
// #48 GET /api/history
export const getHistory = (query: HistoryQuery = {}, signal?: AbortSignal) => api.get<HistoryResponse>('/api/history', query, signal);
// #49 GET /api/history/batches
export const getHistoryBatches = (page = 1, signal?: AbortSignal) => api.get<Page<BatchSummary>>('/api/history/batches', { page }, signal);
// #50 GET /api/batches/{id}
export const getBatch = (batchId: number, signal?: AbortSignal) => api.get<TodayResponse>(`/api/batches/${seg(batchId)}`, undefined, signal);
// #51 GET /api/stats
export const getStats = (signal?: AbortSignal) => api.get<Stats>('/api/stats', undefined, signal);

// ---------------------------------------------------------------------------------------------------
// §8 Media (URL builders — loaded by <img>, cookie session) and admin
// ---------------------------------------------------------------------------------------------------

// #52 GET /media/images/{path} — `path` matches ^[0-9a-f]{2}/[0-9a-f]{64}\.(jpg|svg)$
export const mediaImageUrl = (path: string) => `/media/images/${path}`;
// #53 GET /media/card/{word_id}.svg — template card, always available for a visible word
export const cardUrl = (wordId: number) => `/media/card/${seg(wordId)}.svg`;

// #54 GET /api/admin/overview
export const adminOverview = (signal?: AbortSignal) => api.get<AdminOverview>('/api/admin/overview', undefined, signal);
// #55 GET /api/admin/health
export const adminHealth = (signal?: AbortSignal) => api.get<AdminHealth>('/api/admin/health', undefined, signal);
// #56 GET /api/admin/users
export const adminUsers = (query: AdminUsersQuery = {}, signal?: AbortSignal) => api.get<Page<AdminUser>>('/api/admin/users', query, signal);
// #57 POST /api/admin/users/{id}
export const adminUpdateUser = (userId: number, body: AdminUserUpdateBody) => api.post<AdminUser>(`/api/admin/users/${seg(userId)}`, body);
// #58 GET /api/admin/invites
export const adminInvites = (signal?: AbortSignal) => api.get<AdminInvitesResponse>('/api/admin/invites', undefined, signal);
// #59 POST /api/admin/invites
export const adminCreateInvite = (body: AdminInviteCreateBody = {}) => api.post<AdminInviteCreated>('/api/admin/invites', body);
// #60 GET /api/admin/jobs
export const adminJobs = (query: AdminJobsQuery = {}, signal?: AbortSignal) => api.get<Page<Job>>('/api/admin/jobs', query, signal);
// #61 POST /api/admin/jobs/{id}/retry
export const adminRetryJob = (jobId: number) => api.post<Job>(`/api/admin/jobs/${seg(jobId)}/retry`);
// #62 POST /api/admin/jobs/requeue-dead
export const adminRequeueDead = () => api.post<RequeuedResponse>('/api/admin/jobs/requeue-dead');
// #63 POST /api/admin/jobs/run-once (WD_DEV=1 only)
export const adminRunOnce = () => api.post<ProcessedResponse>('/api/admin/jobs/run-once');
// #64 GET /api/admin/ai/calls
export const adminAiCalls = (page = 1, signal?: AbortSignal) => api.get<AiCallsResponse>('/api/admin/ai/calls', { page }, signal);
// #65 POST /api/admin/ai/pause
export const adminAiPause = (paused: boolean) => api.post<AiPauseResponse>('/api/admin/ai/pause', { paused });
// #66 POST /api/admin/ai/probe
export const adminAiProbe = (provider: AiProvider = 'claude') => api.post<AiProbeResponse>('/api/admin/ai/probe', { provider });
// #67 POST /api/admin/content/prewarm
export const adminPrewarm = (body: PrewarmBody) => api.post<PrewarmResponse>('/api/admin/content/prewarm', body);
// #68 POST /api/admin/words/{id}/regenerate
export const adminRegenerateWord = (wordId: number) => api.post<JobQueuedResponse>(`/api/admin/words/${seg(wordId)}/regenerate`);
// #69 POST /api/admin/words/{id}/refetch-image
export const adminRefetchImage = (wordId: number, body: RefetchImageBody = {}) =>
  api.post<JobQueuedResponse>(`/api/admin/words/${seg(wordId)}/refetch-image`, body);
// #70 GET /api/admin/reports
export const adminReports = (query: AdminReportsQuery = {}, signal?: AbortSignal) => api.get<Page<Report>>('/api/admin/reports', query, signal);
// #71 POST /api/admin/reports/{id}
export const adminResolveReport = (reportId: number, body: AdminReportResolveBody) => api.post<Report>(`/api/admin/reports/${seg(reportId)}`, body);
// #72 GET /api/admin/events
export const adminEvents = (page = 1, signal?: AbortSignal) => api.get<Page<SystemEvent>>('/api/admin/events', { page }, signal);
// #73 GET /api/admin/config
export const adminConfig = (signal?: AbortSignal) => api.get<AdminConfigResponse>('/api/admin/config', undefined, signal);
// #74 POST /api/admin/push/run
export const adminPushRun = (userId: number) => api.post<AdminPushRunResponse>('/api/admin/push/run', { user_id: userId });
// #92 GET /api/admin/identities/disputed
export const adminDisputedIdentities = (page = 1, signal?: AbortSignal) => api.get<Page<DisputedIdentity>>('/api/admin/identities/disputed', { page }, signal);
// #93 POST /api/admin/identities/{id}/restore
export const adminRestoreIdentity = (identityId: number) => api.post<DisputedIdentity>(`/api/admin/identities/${seg(identityId)}/restore`);

// ---------------------------------------------------------------------------------------------------
// §6 (cont.) Import — catalogue entry 75
// ---------------------------------------------------------------------------------------------------

// #75 POST /api/bank/import
export const importBank = (body: ImportBody) => api.post<ImportResponse>('/api/bank/import', body);

/**
 * Builds the JSON import payload from a previous `GET /api/account/export?format=json` file:
 * keeps only `{version, words}` and drops `review_logs` (several MB) so the body stays under 1 MB
 * (API.md 11/75). Returns null when the text is not a JSON export of the expected shape.
 */
export function importPayloadFromJsonExport(text: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null) return null;
  const { version, words } = parsed as { version?: unknown; words?: unknown };
  if (typeof version !== 'number' || !Array.isArray(words)) return null;
  return JSON.stringify({ version, words });
}
