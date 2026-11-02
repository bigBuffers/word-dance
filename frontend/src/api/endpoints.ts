// word-Dance typed endpoint wrappers — exactly one function per API.md §2 catalogue entry (1–75).
// FROZEN CONTRACT (TASKS P0 step 8). Each wrapper is preceded by `// #N METHOD /path` so coverage is
// checked mechanically by endpoints.test.ts. DTOs come from ./types (API.md §9); request bodies and
// query shapes that API.md defines only in prose are declared here. GET wrappers accept an optional
// `AbortSignal` as their last argument so `useApi` can cancel stale requests.
import { api, requestText } from './client';
import type {
  AddResponse,
  AddResult,
  AdminHealth,
  AdminOverview,
  AdminUser,
  AiCall,
  BankResponse,
  Content,
  ContentState,
  Counters,
  DayStats,
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

/** Endpoint 1. `status:'degraded'` comes with HTTP 503 (thrown as ApiError), so a resolved value is always `ok`. */
export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  registration_mode: ServerFlags['registration_mode'];
  needs_setup: boolean;
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
export interface MeResponse {
  user: User;
  settings: Settings;
  server: ServerFlags;
  counters: Counters;
}
export interface AccountUpdateBody {
  display_name?: string | null;
  email?: string | null;
}
export interface PasswordChangeBody {
  current_password: string;
  new_password: string;
}
export interface EmailCodeResponse {
  sent: true;
  expires_in_s: number;
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
export const deleteAccount = (password: string) => api.delete<void>('/api/account', { password });
// #9 POST /api/account/email/request-code
export const requestEmailCode = () => api.post<EmailCodeResponse>('/api/account/email/request-code');
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
export const adminAiProbe = () => api.post<AiProbeResponse>('/api/admin/ai/probe');
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
