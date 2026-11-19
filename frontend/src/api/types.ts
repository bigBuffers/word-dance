// word-Dance — shared DTOs. FROZEN CONTRACT: this file is API.md §9 copied verbatim (TASKS P0 step 8).
// Any change requires updating API.md, backend/wd/schemas.py and this file in one "contract change" commit.
// Request bodies / query shapes that API.md defines only in prose live in ./endpoints.ts.

export type Stage = 'xs' | 'zk' | 'gk' | 'cet4' | 'cet6';   // index 1..5 in that order
export type StageIndex = 1 | 2 | 3 | 4 | 5;
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
export type WebhookTestReason = 'dns_failed' | 'host_not_public' | 'connect_failed' | 'timeout' | 'tls_failed' | 'http_error' | 'invalid_url';   // endpoint 17 `reason`
export type AiProvider = 'claude' | 'fallback';   // ai_calls.provider: the Claude CLI or the fallback HTTP provider (CLAUDE_INTEGRATION §10)
export type DanceMode = 'full' | 'form_only' | 'off';   // 单词之舞 (docs/WORD_DANCE_DESIGN.md §6.3): full = spelling + stress + semantic dance, form_only = spelling + stress only, off
export type DancePrimitive = 'rise' | 'fall' | 'hop' | 'grow' | 'shrink' | 'dash' | 'creep' | 'enter' | 'exit' | 'arc' | 'onto' | 'under' | 'behind' | 'between' | 'split' | 'join' | 'shiver' | 'shimmer' | 'wave' | 'droop' | 'stretch' | 'squash' | 'thud' | 'float' | 'spin' | 'repeat' | 'multiply' | 'dim' | 'glow' | 'color';   // the semantic dance library (§4.3): one motion per meaning class, chosen by Claude from this closed list
export type DanceColor = 'red' | 'orange' | 'yellow' | 'green' | 'blue' | 'purple' | 'pink' | 'brown' | 'black' | 'white' | 'grey';   // the only colours the `color` primitive may name
export type AgeBand = 'u14' | '14plus' | 'adult';   // users.age_band — the learner's own declaration, never verified (docs/AUTH_SIGNUP_DESIGN.md §5.1)
export type CodeChannel = 'phone' | 'email';         // login_codes.channel (endpoints 80, 81, 85)
export type IdentityProvider = 'phone' | 'wechat_mini' | 'qq' | 'apple';   // identities.provider — only `phone` is issued in slice 1-A
export type AccountKind = 'learner' | 'guardian';   // users.account_kind (slice 1-B) — a guardian creates, switches into and manages child accounts (endpoints 94–105)
export type ThirdPartyProvider = 'wechat_mini' | 'qq' | 'apple';   // identities.provider values of slice 2-A (phone is 1-A's); subject = openid / openid / Apple sub, never shown

export interface ApiError { error: { code: string; message: string; details?: Record<string, unknown> } }
export interface Page<T> { items: T[]; page: number; page_size: number; total: number }

export interface User {
  id: number; username: string; display_name: string; email: string | null; email_verified: boolean;
  role: 'user' | 'admin'; onboarding_state: 'pending' | 'screen' | 'done'; created_at: string;
  has_password: boolean;                // users.password_set_at IS NOT NULL — false for an account created by a verification code until it sets one (endpoint 89 / 7)
  phone_masked: string | null;          // the live phone identity with its middle digits hidden (`138****8000`); null without one
  needs_profile: boolean;               // a code-created account that has not saved its nickname + age band yet (endpoint 89); the SPA shows 「首次设置」 before step 1 of /welcome
  age_band: AgeBand | null;             // null = not declared
  account_kind: AccountKind;            // 'guardian' unlocks 我的孩子 (endpoints 94–104); chosen at /welcome step 0 (89), the legacy prompt (110) or by a claim (109)
  is_child: boolean;                    // users.guardian_user_id IS NOT NULL — a child account: account / identity changes only through the guardian (403 guardian_required on 6–10, 85–89, 104, 108–111)
  needs_profile_prompt: boolean;        // an account that has not declared its kind / age band (null age_band, no placeholder username, not a child — pre-1-A accounts and password registrations alike) and was not snoozed in the last 30 days (111); the SPA shows 「补充信息」 once per sitting
  providers: ThirdPartyProvider[];      // the third-party identities bound to the account (sorted); the settings page shows 绑定 / 解绑 per provider (117)
}
export interface ServerFlags {
  version: string; registration_mode: 'open' | 'invite' | 'closed' | 'verified'; email_configured: boolean;
  ai_enabled: boolean; images_enabled: boolean; dev: boolean;
  needs_setup: boolean;                 // true while no user exists (also in GET /api/health)
  audio: boolean;                       // GET /media/audio serves pronunciation clips (WD_AUDIO_PROVIDER is not off; endpoint 76) — the fallback for devices without an English voice
  audio_key: string;                    // fingerprint of the provider + voice behind endpoint 76 (empty without a provider): the client appends it to clip URLs as `v`, so a switched voice is a new URL for the browser cache
  audio_zh: boolean;                    // endpoint 76 also speaks Chinese (`accent=zh-CN`): the provider has a Chinese voice, or has not resolved it yet (optimistic for the seconds after a start, §9.1) — 磨耳朵 (endpoint 123) reads glosses and translations with it
  sms_enabled: boolean;                 // WD_SMS_PROVIDER is not off: phone verification codes can be sent (endpoints 80, 85)
  wechat_enabled: boolean;              // the WeChat mini-program bridge is configured (endpoints 112–116) — the login page shows 微信 and settings offers 绑定微信
  qq_enabled: boolean;                  // QQ 互联 login is configured (118 / 119)
  apple_enabled: boolean;               // Sign in with Apple (web redirect flow) is configured (120 / 121)
}
export interface Counters { suggestions_open: number; attention: number }   // GET /api/auth/me → badges
export interface SessionInfo {
  guardian: { id: number; display_name: string } | null;   // the guardian who switched this device into a child account (sessions.actor_user_id, endpoint 104); the SPA shows 「切回家长」 → 105
  gate_until: string | null;            // a guardian's own session: until when the 家长门 is passed (sessions.guardian_gate_at + 10 min, endpoints 102 / 105); null = not passed / not a guardian
}
export interface WechatTicket { ticket: string; pairing_code: string; expires_in_s: number; qr_url: string }   // endpoint 112: the 26-char scene of the 小程序码 (also the poll path), the 6-digit pairing code for the mobile path, the PNG URL (114)
export interface WechatTicketStatus {   // endpoint 113 (polled every 2 s with the wd_wxt cookie)
  status: 'pending' | 'scanned' | 'confirmed' | 'cancelled' | 'expired';
  user: User | null;                    // confirmed: the signed-in / bound account (the session cookie came with this response for a login ticket)
  settings: Settings | null;            // confirmed login tickets only
  created: boolean | null;              // confirmed login tickets: the account was created by this confirmation (→ /welcome)
}
export interface WechatScanInfo {       // endpoint 115 (the mini program's confirmation page)
  mp_token: string;                     // proves the scan to endpoint 116 (5 minutes)
  kind: 'login' | 'bind';
  account: 'bound' | 'new' | 'closed' | 'self' | 'other';   // login: this WeChat has an account / would create one / registration closed; bind: already bound to this account / bound to another account / free
  bind_display_name: string | null;     // kind=bind: the account that asked for the binding
  web_ip_masked: string;                // the initiating browser, e.g. 203.0.113.*
  web_ua_summary: string;               // e.g. Chrome · macOS
  created_at: string;
  expires_in_s: number;
}
export interface WechatConfirmResult { status: 'confirmed' | 'cancelled'; created: boolean }   // endpoint 116
export interface CaptchaChallenge { id: string; image: string; exp: number; sig: string; expires_in_s: number }   // endpoint 79: `image` is a PNG data: URI; the client returns id/exp/sig with the digits it read
export interface CodeSendResponse { sent: boolean; expires_in_s: number }   // endpoints 9, 80, 82, 85, 90 — always `sent: true`; identical for known and unknown targets
export interface StaleChallenge {
  token: string;                        // one-time, 10 minutes (endpoints 82–84)
  display_name_masked: string;          // first character + ＊＊ — 「这是你的账号吗」
  since: string;                        // the account's registration month `YYYY-MM`
  can_password: boolean; can_email: boolean;   // the second factors this account can offer; both false → the SPA shows the contact-admin text
  email_masked: string | null;          // `a***@qq.com` when can_email
}
export interface CodeLoginResponse {
  user: User | null; settings: Settings | null;   // set when a session was issued (cookie in the same response)
  created: boolean;                     // true when this call created the account (HTTP 201)
  challenge: StaleChallenge | null;     // set instead of a session when the phone identity is stale (WD_PHONE_STALE_DAYS)
}
export interface ChildAccount {
  id: number; display_name: string;
  username: string | null;              // the simple login the guardian set (95 / 96); null while the account has only its placeholder username
  has_password: boolean; phone_masked: string | null; age_band: AgeBand | null;
  onboarding_state: 'pending' | 'screen' | 'done'; created_at: string; last_login_at: string | null;
  bank_size: number; streak_days: number;   // the AdminUser figures, for the guardian's overview
  sessions: number;                     // live sessions of the child (signed-in devices); endpoint 98 revokes them
}
export interface ChildrenResponse { items: ChildAccount[]; pin_set: boolean; ready: boolean; missing: ('phone' | 'second_factor')[]; gate_until: string | null }   // endpoint 94: `ready` = the guardian holds a live phone AND a password or verified e-mail (the two-factor rule, docs/AUTH_SIGNUP_DESIGN.md §5.1); `missing` names what is absent
export interface ChildResponse { child: ChildAccount }   // endpoints 95, 96, 101
export interface ChildLoginCode { code: string; expires_in_s: number }   // endpoint 99: the 8-digit one-time code, shown once, never logged
export interface GateResponse { gate_until: string }   // endpoint 102
export interface DemoWord { word: WordBrief; content: Content | null; image: ImageMeta; dance: DanceSpec | null }   // endpoint 77
export interface DemoResponse { items: DemoWord[] }
export interface Settings {
  timezone: string; push_time: string; push_enabled: boolean;
  daily_new_count: number; daily_screen_count: number; max_reviews: number;
  stages: Stage[]; current_stage: Stage;   // Stage string on the wire; the server stores the 1–5 index (§9.1)
  show_images: boolean; zh_examples: 'tap' | 'always'; auto_pronounce: boolean; accent: 'en-US' | 'en-GB';
  dance_mode: DanceMode;                // 单词之舞: full = spelling + stress (card show) + semantic dance (reveal); form_only skips the semantic dance; off = plain headword
  image_word: boolean;                  // 记忆图卡: show the word woven into the picture (default true); false → the client asks for the picture without it (`?plain=1`, endpoint 52)
  email_enabled: boolean; webhook_enabled: boolean; webhook_url: string | null; webhook_format: WebhookFormat;
  next_push_at: string | null;          // read-only
  email_verified: boolean;              // read-only
  updated_at: string;
}
export interface StageInfo {
  stage: Stage; index: StageIndex; name_zh: string;           // 小学 / 初中 / 高中 / 四级 / 六级
  total: number; new_only_total: number;                      // all words in the stage / words whose lowest stage is this one
  unfamiliar: number; known: number; mastered: number; unseen: number;
}
export interface WordBrief {
  id: number; lemma: string; display: string; kind: WordKind; phonetic: string | null;
  translation_short: string;            // the short meaning a list shows, one line of ≤ 60 chars: the active content's meaning_zh, else the dictionary's main sense (§9.1)
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
export interface DanceSpec {                                 // 单词之舞 (docs/WORD_DANCE_DESIGN.md §4): built by wd.dance.spec_for_word at serialisation time — the rule spec from display + phonetic, overlaid with the stored word_dances row's semantic (and its chunks / stress only where the model corrected the suggestion, P3b)
  version: 1; letters: string[];                            // display cut into syllable chunks, letters.join('') === display; one chunk when the rules cannot split the word
  stress: number | null;                                     // index into letters of the primary-stressed chunk (an unmarked split word takes its first non-schwa chunk); null only when the word stays one chunk with two or more nuclei
  marks: { double: [number, number][]; silent: number[] };   // letter indexes into display: doubled letters jump together, silent letters stay put (night's gh, knife's k, the magic e)
  semantic: { primitive: DancePrimitive; params: { n?: number; color?: DanceColor } } | null;   // 语义舞 (§4.3): the word's one meaning motion, played at the reveal; null = no semantic dance (nouns with a picture, function words, rule-only specs)
  source: 'rule' | 'claude';                                 // rule = backend/wd/dance.py at serialisation time; claude = the word has a stored word_dances row (its semantic; its chunks and stress only where the model corrected the rule suggestion, else the current rules')
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
  word_layer: boolean;                                        // 记忆图卡 (a drawing whose last layer `#word-art` is the word itself): `url` + '?plain=1' is the same picture without the word (endpoint 52); false for photos, older drawings and the template card
  hook_zh: string | null; note_zh: string | null;             // 记忆图卡 only: the memory hook the picture acts out, and an optional sound / meaning caveat — the 记忆 section shows them instead of content.mnemonic_zh; null otherwise
}
export interface WordDetail {
  word: WordBrief & {
    definition: string | null; translation: string | null; pos: string | null; exam_tags: string[];
    bnc: number | null; forms: { form: string; kind: string }[]; source: 'seed' | 'ecdict' | 'claude' | 'user';
    confusables: string[];                                    // 易混 chips: this user's accepted confusable_group rows containing the lemma, minus the lemma (§9.1)
    dance: DanceSpec | null;                                  // null for phrases, abbreviations and words without a phonetic (§9.1)
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
  study_item: StudyItem | null; today: TodayCounts | null; // counts of today's batch when one exists (「明天开始学」 when added_to_today is false), else null
  duplicate: boolean;
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
  word: WordBrief & { definition: string | null; translation: string | null; pos: string | null; forms: string[]; confusables: string[]; dance: DanceSpec | null };
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
export interface ListenItem {
  item_id: number; word_id: number; kind: ItemKind; done: boolean;   // kind: review | new | extra (推荐词 are not listened to); done: the item has its final grade
  display: string; phonetic: string | null;
  spoken_en: string | null;             // what to speak for the headword (`sb.` / `sth.` spelled out); null when endpoint 76 would refuse the text
  meaning_zh: string;                   // shown on the player and on the 听写 answer sheet: content.meaning_zh, else the dictionary's main sense ('' when neither exists)
  gloss_zh: string | null;              // speakable Chinese gloss: at most two senses, no part-of-speech labels, no brackets; null when none can be derived
  sentence_en: string | null; sentence_zh: string | null;   // one example sentence endpoint 76 accepts, and its translation (null when it cannot be spoken); both null without content
}
export interface ListenPlaylist { batch_id: number | null; local_date: string; items: ListenItem[] }   // endpoint 123: today's review / new / extra words in batch order, one row per word, without the words that have left the bank since (已掌握 / 已认识 / removed — the word's state now, not the item's grade); batch_id null = no batch today
export interface GradeResponse {
  item: { item_id: number; result: string | null; skip_count: number; requeue_at: string | null };   // result null + requeue_at set = intermediate grade: the item stays ungraded and is graded again later (endpoint 45)
  mine: UserWord | null; next_due_zh: string;                 // '10 分钟后' | '明天' | '今天' | 'N 天后' | '约 N 个月后' | '已掌握' | '已跳过' | '已认识' (thresholds in §9.1)
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
  heatmap: { date: string; graded: number; goal_met: boolean }[];   // last 84 days; goal_met = the §9.1 predicate (completed_at set, or every non-stale study item final)
  stubborn: WordBrief[];                                             // times_added ≥ 3, max 20
}

// ---- admin ----
export interface AdminOverview {
  users: { total: number; active_7d: number };
  words: { total: number; with_content: number; with_photo: number; with_claude_svg: number; card_only: number; user_added: number; pending_validation: number };
  // with_photo = active word_images.provider ∈ wikimedia/openverse/pixabay/pexels · with_claude_svg = provider claude_svg · card_only = content ready but no active image
  bank_entries: number; batches_today: number;
  jobs: { queued: number; running: number; dead: number; by_type: Record<string, number> };
  ai: { enabled: boolean; paused_until: string | null; manual_paused_until: string | null; flag_tier: 0 | 1; today_usd: number; month_usd: number;
        daily_budget_usd: number; monthly_budget_usd: number; svg_today_usd: number; svg_daily_budget_usd: number; dance_today_usd: number; dance_daily_budget_usd: number;
        calls_today: number; avg_cost_per_word_7d: number | null; last_error: string | null;
        active_provider: AiProvider; fallback_configured: boolean; fallback_paused_until: string | null; fallback_calls_today: number; fallback_available: boolean | null };
  // ai.paused_until = the CLI's automatic pause or the admin's global pause, whichever ends later · manual_paused_until = the admin's own pause alone (what the pause/resume toggle keys off)
  // · active_provider = kv ai.active_provider · fallback_* = the HTTP fallback provider; fallback_available null = never probed, false = marked unavailable until the next fallback success (CLAUDE_INTEGRATION §10)
  images: { providers: { provider: string; minute_count: number; day_count: number; minute_limit: number | null; day_limit: number | null; cooldown_until: string | null }[] };
  scheduler: { last_tick_at: string | null; alive: boolean };
  sms: { provider: string; sent_today: number; daily_cap: number; sent_hour: number; hourly_cap: number; registration_open: boolean };   // WD_SMS_* caps (WD_TZ day / current hour); registration_open = new-account code sends still below 70 % of the day cap
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
export interface DisputedIdentity { id: number; user: { id: number; username: string; display_name: string }; provider: IdentityProvider; subject_masked: string; verified_at: string; last_login_at: string | null; disputed_at: string; current_user_id: number | null }   // endpoints 92/93; current_user_id = the account now holding the live binding
export interface Job {
  id: number; type: string; payload: Record<string, unknown>; dedupe_key: string | null; priority: number; status: string;
  attempts: number; max_attempts: number; run_after: string; locked_by: string | null; last_error: string | null; created_at: string; finished_at: string | null;
}
export interface AiCall {
  id: number; kind: string; status: string; provider: AiProvider; model_requested: string; model_used: string | null; flag_tier: 0 | 1; word_count: number;
  cost_usd: number; duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; error: string | null; started_at: string;
}
export interface Report {
  id: number; user: { id: number; username: string }; word: WordBrief; target: 'content' | 'image' | 'dictionary'; reason: ReportReason;
  note: string | null; status: 'open' | 'resolved' | 'dismissed'; resolution: string | null; created_at: string; resolved_at: string | null;
}
export interface SystemEvent { id: number; kind: string; detail: Record<string, unknown>; created_at: string }
