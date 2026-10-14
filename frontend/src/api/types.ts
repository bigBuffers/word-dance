// word-Dance — shared DTOs. FROZEN CONTRACT: this file is API.md §9 copied verbatim (TASKS P0 step 8).
// Any change requires updating API.md, backend/wd/schemas.py and this file in one "contract change" commit.
// Request bodies / query shapes that API.md defines only in prose live in ./endpoints.ts.

export type Stage = 'zk' | 'gk' | 'cet4' | 'cet6';           // index 1..4 in that order
export type StageIndex = 1 | 2 | 3 | 4;
export type UserState = 'new' | 'learning' | 'mastered' | 'known' | 'removed';
export type Origin = 'browse' | 'custom' | 'screen' | 'push' | 'import';   // 'import' = POST /api/bank/import
export type MarkAction = 'unfamiliar' | 'known' | 'mastered' | 'remove' | 'reset' | 'restore';
export type Grade = 'again' | 'hard' | 'good' | 'master' | 'skip';
export type ScreenVerdict = 'known' | 'unfamiliar' | 'skip';
export type ContentState = 'none' | 'queued' | 'ready' | 'failed';
export type ImageState = 'none' | 'queued' | 'ready' | 'failed';
export type ItemKind = 'review' | 'new' | 'screen' | 'extra';
export type WordKind = 'word' | 'phrase' | 'abbreviation' | 'proper_noun';
export type ReportReason = 'wrong_meaning' | 'unnatural_example' | 'bad_translation' | 'irrelevant_image' | 'inappropriate_image' | 'other';
export type WebhookFormat = 'generic' | 'wecom' | 'feishu' | 'serverchan' | 'bark';

export interface ApiError { error: { code: string; message: string; details?: Record<string, unknown> } }
export interface Page<T> { items: T[]; page: number; page_size: number; total: number }

export interface User {
  id: number; username: string; display_name: string; email: string | null; email_verified: boolean;
  role: 'user' | 'admin'; onboarding_state: 'pending' | 'screen' | 'done'; created_at: string;
}
export interface ServerFlags {
  version: string; registration_mode: 'open' | 'invite' | 'closed'; email_configured: boolean;
  ai_enabled: boolean; images_enabled: boolean; dev: boolean;
  needs_setup: boolean;                 // true while no user exists (also in GET /api/health)
}
export interface Counters { suggestions_open: number; attention: number }   // GET /api/auth/me → badges
export interface Settings {
  timezone: string; push_time: string; push_enabled: boolean;
  daily_new_count: number; daily_screen_count: number; max_reviews: number;
  stages: Stage[]; current_stage: Stage;   // Stage string on the wire; the server stores the 1–4 index (§9.1)
  show_images: boolean; zh_examples: 'tap' | 'always'; auto_pronounce: boolean; accent: 'en-US' | 'en-GB';
  email_enabled: boolean; webhook_enabled: boolean; webhook_url: string | null; webhook_format: WebhookFormat;
  next_push_at: string | null;          // read-only
  email_verified: boolean;              // read-only
  updated_at: string;
}
export interface StageInfo {
  stage: Stage; index: StageIndex; name_zh: string;           // 初中 / 高中 / 四级 / 六级
  total: number; new_only_total: number;                      // all words in the stage / words whose lowest stage is this one
  unfamiliar: number; known: number; mastered: number; unseen: number;
}
export interface WordBrief {
  id: number; lemma: string; display: string; kind: WordKind; phonetic: string | null;
  translation_short: string;            // first translation line, ≤ 60 chars
  stages: Stage[]; stage_min: StageIndex | null; cet6_star: boolean;
  frq: number | null; collins: number | null; oxford: boolean | null; difficulty: number | null;
  is_public: boolean; is_valid_english: boolean | null;
  my_state: UserState | null;
  content_state: ContentState; image_state: ImageState;
}
export interface Srs {
  ease: number; interval_days: number; step: 0 | 1; repetitions: number; lapses: number; consecutive_good: number;
  due_at: string | null; last_graded_at: string | null; mastery_suggested: boolean;
}
export interface UserWord {
  id: number; word_id: number; state: UserState; origin: Origin; priority: number;
  note: string | null; input_text: string | null;
  needs_attention: boolean; attention_msg: string | null; suggested_word: WordBrief | null;
  srs: Srs; times_pushed: number; times_added: number;
  added_at: string; first_added_at: string; mastered_at: string | null;
}
export interface Example { en: string; zh: string }
export interface Content {
  word: string; valid: boolean; meaning_zh: string; meaning_en: string;
  examples: Example[]; collocations: string[]; mnemonic_zh: string;
  image_keywords: string[]; image_alt_zh: string; difficulty: 1 | 2 | 3 | 4 | 5;
  version: number; prompt_version: string; model: string; created_at: string;
}
export interface Attribution {
  title: string | null; creator: string | null; creator_url: string | null;
  license: string; license_url: string | null; landing_url: string | null; text: string;   // text = ready-to-display line
}
export interface ImageMeta {
  id: number | null;                                          // null for the template card
  url: string;                                                // '/media/images/ab/ab12….jpg' | '/media/card/123.svg'
  kind: 'photo' | 'svg' | 'card';
  provider: 'wikimedia' | 'openverse' | 'pixabay' | 'pexels' | 'claude_svg' | 'card_svg';
  mime: 'image/jpeg' | 'image/svg+xml'; width: number | null; height: number | null;
  alt_zh: string | null; attribution: Attribution | null;      // null for the card
}
export interface WordDetail {
  word: WordBrief & {
    definition: string | null; translation: string | null; pos: string | null; exam_tags: string[];
    bnc: number | null; forms: { form: string; kind: string }[]; source: 'seed' | 'ecdict' | 'claude' | 'user';
    confusables: string[];                                    // 易混 chips: this user's accepted confusable_group rows containing the lemma, minus the lemma (§9.1)
  };
  content: Content | null; content_state: ContentState;
  content_deferred_until: string | null;                      // == GET /api/words/{id}/content.deferred_until (budget deferral / AI paused → no polling, 「明天补齐」 copy)
  image: ImageMeta; mine: UserWord | null; redirected_from: string | null;
  history: ReviewLogItem[];                                   // my last 20 actions on this word
}
export interface ReviewLogItem {
  id: number; created_at: string; action: string; context: string;
  prev_state: UserState | null; new_state: UserState | null; prev_interval: number | null; new_interval: number | null;
}
export interface LookupPreview {
  input: string; normalized: string | null; valid: boolean; reason_zh: string | null;
  via: 'exact' | 'form' | 'ambiguous' | 'ecdict' | 'none' | 'invalid';
  match: WordBrief | null; lemma_note_zh: string | null;      // e.g. 已归为原形 go（过去式）
  candidates: WordBrief[];                                    // ambiguous forms (bases → base / basis)
  suggestions: WordBrief[];                                   // ≤ 5 prefix matches
  mine: UserWord | null;
}
export interface ScreenWord { word: WordBrief; phonetic: string | null }
export interface ScreenResponse {
  word_id: number; verdict: ScreenVerdict; mine: UserWord | null; added_to_today: boolean;
  study_item: StudyItem | null; today: TodayCounts | null; duplicate: boolean;
}
export interface AddResult {
  input: string; status: 'added' | 'readded' | 'exists' | 'pending_ai' | 'ambiguous' | 'invalid';
  word: WordBrief | null; mine: UserWord | null;
  resolved_via: 'exact' | 'form' | 'ecdict' | 'provisional' | null; lemma_note_zh: string | null;
  candidates: WordBrief[]; error: string | null; message: string | null; added_to_today: boolean;
}
export interface AddResponse { results: AddResult[]; added: number; readded: number; exists: number; pending_ai: number; ambiguous: number; invalid: number }
export interface ImportResponse extends AddResponse { rows: number; skipped: number }   // POST /api/bank/import; results holds the first 200 rows
export interface BankItem extends WordBrief { mine: UserWord }
export interface BankCounts { new: number; learning: number; mastered: number; known: number; removed: number; attention: number; due_today: number }
export interface BankResponse extends Page<BankItem> { counts: BankCounts }
export interface Suggestion {
  id: number; type: 'fix_spelling' | 'lemmatize' | 'merge_duplicate' | 'invalid_word' | 'split_phrase' | 'confusable_group' | 'fill_data' | 'difficulty';
  status: 'open' | 'accepted' | 'rejected' | 'expired' | 'auto' | 'undone';
  user_word: BankItem | null; target: WordBrief | null;
  payload: { from?: string; to?: string; note_zh?: string; confidence?: number; group?: string[]; fields?: string[] };
  created_at: string; expires_at: string | null; resolved_at: string | null;
}
export interface SuggestionResult { applied: boolean; mine: UserWord | null; removed_word_id: number | null; message_zh: string }

export interface TodayCounts {
  total: number; done: number; review: number; review_done: number; new: number; new_done: number;   // *_done = items with result !== null (final grade); the 10-minute step is not done
  screen: number; screen_done: number; extra: number; extra_done: number; pending_content: number; deferred_reviews: number;   // pending_content excludes budget-deferred items (endpoint 43)
}
export interface StudyItem {
  item_id: number; kind: ItemKind; position: number; result: string | null; skip_count: number;   // result: FINAL grade only (null while the card sits in the 10-minute step)
  requeue_at: string | null;                                  // learning step due (UTC) → client re-inserts the card; always paired with result === null
  word: WordBrief & { definition: string | null; translation: string | null; pos: string | null; forms: string[]; confusables: string[] };
  mine: UserWord | null; content: Content | null; content_state: ContentState; content_deferred_until: string | null; image: ImageMeta;
}
export interface Batch {
  id: number; local_date: string; timezone: string; status: 'building' | 'ready' | 'published'; trigger: string;
  gradable: boolean;                                          // today's batch, or yesterday's while it has ungraded items (endpoint 50); false → replay only, no grade bar
  counts: TodayCounts; items: StudyItem[];                    // ungraded first (skipped after unskipped), then graded
  extra_rounds: number; can_request_more: boolean; built_at: string; published_at: string | null; completed_at: string | null;
}
export interface PreviousOpenBatch { id: number; local_date: string; remaining: number }   // yesterday's batch with ungraded review/new/extra items (endpoint 43)
export interface TodayResponse {
  status: 'none' | 'building' | 'ready' | 'published'; local_date: string; push_time: string; next_push_at: string | null;
  can_build_now: boolean; batch: Batch | null; streak_days: number; goal_met: boolean; added: number | null;   // added: items appended by /more
  previous_open_batch: PreviousOpenBatch | null;              // 「继续昨天的学习（还剩 N 个）」 on 今日
  suggestions_open: number;                                   // open 整理建议 (badge on 今日)
}
export interface GradeResponse {
  item: { item_id: number; result: string | null; skip_count: number; requeue_at: string | null };   // result null + requeue_at set = intermediate grade: the item stays ungraded and is graded again later (endpoint 45)
  mine: UserWord | null; next_due_zh: string;                 // '10 分钟后' | '明天' | 'N 天后' | '约 N 个月后' | '已掌握' | '已跳过' (thresholds in §9.1)
  mastery_suggested: boolean; today: TodayCounts; duplicate: boolean;
  study_item: StudyItem | null;                               // the kind='new' card appended when a screen item was graded unfamiliar in-batch
}
export interface SessionSummary {
  local_date: string; review: number; new: number; extra: number; screen: number; again: number; hard: number; good: number;
  mastered: number; known: number; unfamiliar: number; study_minutes: number; streak_days: number; goal_met: boolean;
  next_push_at: string | null; can_request_more: boolean;
}
export interface DayStats {
  date: string; graded: number; again: number; hard: number; good: number; mastered: number; known: number; screened: number; added: number;
  study_minutes: number; batch_id: number | null; batch_total: number | null; batch_done: number | null; offline: boolean;
}
export interface BatchSummary { id: number; local_date: string; status: string; trigger: string; counts: TodayCounts; published_at: string | null; completed_at: string | null }
export interface Stats {
  bank: BankCounts; stages: StageInfo[]; custom_words: number; streak_days: number; longest_streak: number;
  today: { done: number; total: number } | null; total_graded: number; total_mastered: number;
  heatmap: { date: string; graded: number; goal_met: boolean }[];   // last 84 days
  stubborn: WordBrief[];                                             // times_added ≥ 3, max 20
}

// ---- admin ----
export interface AdminOverview {
  users: { total: number; active_7d: number };
  words: { total: number; with_content: number; with_photo: number; with_claude_svg: number; card_only: number; user_added: number; pending_validation: number };
  // with_photo = active word_images.provider ∈ wikimedia/openverse/pixabay/pexels · with_claude_svg = provider claude_svg · card_only = content ready but no active image
  bank_entries: number; batches_today: number;
  jobs: { queued: number; running: number; dead: number; by_type: Record<string, number> };
  ai: { enabled: boolean; paused_until: string | null; flag_tier: 0 | 1; today_usd: number; month_usd: number;
        daily_budget_usd: number; monthly_budget_usd: number; svg_today_usd: number; svg_daily_budget_usd: number;
        calls_today: number; avg_cost_per_word_7d: number | null; last_error: string | null };
  images: { providers: { provider: string; minute_count: number; day_count: number; minute_limit: number | null; day_limit: number | null; cooldown_until: string | null }[] };
  scheduler: { last_tick_at: string | null; alive: boolean };
  events_24h: SystemEvent[];
}
export interface AdminHealth {
  db_ok: boolean; db_size_bytes: number; disk_free_bytes: number; data_dir: string;
  scheduler_alive: boolean; scheduler_last_tick_at: string | null; claude_worker_alive: boolean; io_worker_alive: boolean;
  claude_bin: { path: string; version: string | null; ok: boolean; flag_tier: 0 | 1; last_probe_at: string | null };
  seed_version: string | null; migrations_version: number; worker_lease: { instance: string; expires_at: string } | null;
  last_backup: { file: string; at: string; bytes: number } | null;
}
export interface AdminUser extends User { is_active: boolean; last_login_at: string | null; bank_size: number; streak_days: number }
export interface Job {
  id: number; type: string; payload: Record<string, unknown>; dedupe_key: string | null; priority: number; status: string;
  attempts: number; max_attempts: number; run_after: string; locked_by: string | null; last_error: string | null; created_at: string; finished_at: string | null;
}
export interface AiCall {
  id: number; kind: string; status: string; model_requested: string; model_used: string | null; flag_tier: 0 | 1; word_count: number;
  cost_usd: number; duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; error: string | null; started_at: string;
}
export interface Report {
  id: number; user: { id: number; username: string }; word: WordBrief; target: 'content' | 'image' | 'dictionary'; reason: ReportReason;
  note: string | null; status: 'open' | 'resolved' | 'dismissed'; resolution: string | null; created_at: string; resolved_at: string | null;
}
export interface SystemEvent { id: number; kind: string; detail: Record<string, unknown>; created_at: string }
