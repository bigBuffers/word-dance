// AdminPage — `/admin` (FRONTEND 5.8, API.md endpoints 54-74, 92-93): tabs overview / users & invites / jobs /
// AI / reports / events / config. Overview tiles show users, spend today/month vs caps, the SVG budget, the SMS
// counters against the WD_SMS_* caps (`AdminOverview.sms`), the word image mix (photo / claude svg / card only),
// queue, provider quotas, scheduler and health. The users tab marks accounts without a password (`zh.admin.noPassword`),
// guardians (`zh.admin.guardian`, `account_kind`) and children (`zh.admin.child`, `is_child` — slice 1-B) next to the role,
// and lists the disputed phone bindings (`zh.admin.disputed`, endpoint 92) with a restore action (endpoint 93).
// Admin copy may show error codes (FRONTEND §5.8) — job types, status tags, config keys; every heading, table
// header, form label and tile caption comes from zh.admin / zh.admin.labels.
import { useState, type FormEvent, type ReactNode } from 'react';
import { Link } from 'react-router';
import { errorMessage, type ApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { AdminInviteCreated, AdminUserUpdateBody, AiCallsResponse, PrewarmStage, ReportStatusFilter } from '@/api/endpoints';
import type { AdminHealth, AdminOverview, AdminUser, AiCall, AiProvider, DisputedIdentity, Job, Page, Report, SystemEvent } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { Pager, usePagedList } from '@/components/list/Pager';
import { SearchBox } from '@/components/list/SearchBox';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Sheet } from '@/components/ui/Sheet';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tabs } from '@/components/ui/Tabs';
import { STAGE_ORDER } from '@/components/word/StageChips';
import { useApi } from '@/hooks/useApi';
import { useLocalPref } from '@/hooks/useLocalPref';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { formatDateTime } from '@/utils/date';
import { formatBytes, formatInt, formatPercent, formatUsd, truncate } from '@/utils/format';
import '@/components/ui/auth.css';
import './AdminPage.css';

type AdminTab = keyof typeof zh.admin.tabs;
/** Column / field / tile labels (zh-CN) for the raw DTO fields the admin tables show. */
const L = zh.admin.labels;
const TABS: readonly AdminTab[] = ['overview', 'users', 'jobs', 'ai', 'reports', 'events', 'config'];
const PAGE_SIZE = 50;
const JOB_STATUSES = ['queued', 'running', 'done', 'failed', 'dead', 'cancelled'] as const;
const PREWARM_STAGES: readonly PrewarmStage[] = [...STAGE_ORDER, 'all'];
const REPORT_STATUSES: readonly ReportStatusFilter[] = ['open', 'resolved', 'dismissed'];

function isAdminTab(value: unknown): value is AdminTab {
  return typeof value === 'string' && (TABS as readonly string[]).includes(value);
}

/** Meter tone by consumption of a cap (status is always paired with the percentage label). */
export function meterTone(part: number, total: number): 'normal' | 'warning' | 'critical' {
  if (total <= 0) return 'normal';
  const ratio = part / total;
  if (ratio >= 1) return 'critical';
  if (ratio >= 0.8) return 'warning';
  return 'normal';
}

// ---------------------------------------------------------------------------------------------------
// shared pieces
// ---------------------------------------------------------------------------------------------------

function ErrorBox({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  return (
    <div className="admin__error" role="alert">
      <span>
        {errorMessage(error)} <code>{error.code}</code>
      </span>
      <Button size="sm" onClick={onRetry}>
        {zh.common.retry}
      </Button>
    </div>
  );
}

function Meter({ part, total, label }: { part: number; total: number; label: string }) {
  const tone = meterTone(part, total);
  const pct = total > 0 ? Math.min(100, Math.max(0, (part / total) * 100)) : 0;
  return (
    <div className="meter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={Math.max(total, 0)} aria-valuenow={Math.max(0, Math.min(part, total))}>
      <span className="meter__track">
        <span className="meter__fill" data-tone={tone} style={{ width: `${pct}%` }} />
      </span>
      <span className="meter__label" data-tone={tone}>
        {formatPercent(part, total)}
      </span>
    </div>
  );
}

function Tile({ label, value, sub, meter, tone }: { label: string; value: ReactNode; sub?: ReactNode; meter?: { part: number; total: number }; tone?: 'good' | 'bad' }) {
  return (
    <div className={`tile${tone ? ` tile--${tone}` : ''}`}>
      <span className="tile__label">{label}</span>
      <span className="tile__value">{value}</span>
      {sub !== undefined && sub !== null && <span className="tile__sub">{sub}</span>}
      {meter && <Meter part={meter.part} total={meter.total} label={label} />}
    </div>
  );
}

function When({ iso, tz }: { iso: string | null | undefined; tz: string | undefined }) {
  if (!iso) return <span className="muted">—</span>;
  return <time dateTime={iso}>{formatDateTime(iso, tz)}</time>;
}

function JsonCell({ value }: { value: unknown }) {
  const text = JSON.stringify(value) ?? '';
  return <code title={text}>{truncate(text, 120)}</code>;
}

function StatusTag({ status }: { status: string }) {
  const tone = status === 'done' || status === 'ok' || status === 'resolved' ? 'good' : status === 'dead' || status === 'failed' || status === 'error' ? 'bad' : status === 'running' || status === 'queued' ? 'brand' : status === 'dismissed' || status === 'cancelled' ? '' : 'warn';
  return <span className={`tag${tone ? ` tag--${tone}` : ''}`}>{status}</span>;
}

function useTz(): string | undefined {
  return useAuth().settings?.timezone;
}

/**
 * The pause note of the AI status (API.md 54): the admin's own pause (`manual_paused_until`, what the toggle keys off)
 * reads as paused; the CLI's automatic pause alone (`paused_until` set while `manual_paused_until` is null — the
 * fallback may be serving learners meanwhile, CLAUDE_INTEGRATION §10.5) is a note, never the "paused" state.
 */
function PauseNote({ ai, tz }: { ai: Pick<AdminOverview['ai'], 'paused_until' | 'manual_paused_until'>; tz: string | undefined }) {
  if (ai.manual_paused_until) {
    return (
      <>
        <StatusTag status="paused" /> {zh.admin.paused} · <When iso={ai.manual_paused_until} tz={tz} />
      </>
    );
  }
  if (ai.paused_until) {
    return (
      <>
        <StatusTag status="paused" /> {zh.admin.claudeAutoPaused} <When iso={ai.paused_until} tz={tz} />
      </>
    );
  }
  return null;
}

/** kv ai.fallback.available as copy: null = never probed, true = usable, false = marked unavailable (CLAUDE_INTEGRATION §10.6). */
function fallbackAvailability(available: boolean | null): string {
  if (available === null) return zh.admin.fallbackAvailability.unprobed;
  return available ? zh.admin.fallbackAvailability.available : zh.admin.fallbackAvailability.unavailable;
}

// ---------------------------------------------------------------------------------------------------
// overview
// ---------------------------------------------------------------------------------------------------

function ImageMix({ words }: { words: AdminOverview['words'] }) {
  const total = words.with_photo + words.with_claude_svg + words.card_only;
  const width = (n: number) => `${total > 0 ? (n / total) * 100 : 0}%`;
  const legend = [
    { key: 'photo', label: zh.admin.images.photo, value: words.with_photo },
    { key: 'svg', label: zh.admin.images.svg, value: words.with_claude_svg },
    { key: 'card', label: zh.admin.images.card, value: words.card_only },
  ] as const;
  return (
    <section className="card admin__card" aria-labelledby="admin-mix">
      <h2 id="admin-mix">{legend.map((l) => l.label).join(' / ')}</h2>
      <div className="mix" role="img" aria-label={legend.map((l) => `${l.label} ${formatInt(l.value)}`).join(' · ')}>
        {legend.map((l) => (
          <span key={l.key} className={`mix__seg mix__seg--${l.key}`} style={{ width: width(l.value) }} />
        ))}
      </div>
      <ul className="mix__legend">
        {legend.map((l) => (
          <li key={l.key}>
            <span className={`mix__swatch mix__swatch--${l.key}`} aria-hidden="true" />
            <span>{l.label}</span>
            <strong>{formatInt(l.value)}</strong>
            <span className="muted">{formatPercent(l.value, total)}</span>
          </li>
        ))}
      </ul>
      <p className="admin__footnote">
        {L.withContent} {formatInt(words.with_content)} · {L.total} {formatInt(words.total)} · {L.userAdded} {formatInt(words.user_added)} · {L.pendingValidation}{' '}
        {formatInt(words.pending_validation)}
      </p>
    </section>
  );
}

function HealthCard({ h, tz }: { h: AdminHealth; tz: string | undefined }) {
  return (
    <section className="card admin__card" aria-labelledby="admin-health">
      <h2 id="admin-health">{L.health}</h2>
      <dl className="kv">
        <dt>{L.db}</dt>
        <dd>
          <StatusTag status={h.db_ok ? 'ok' : 'error'} /> {formatBytes(h.db_size_bytes)} · {L.diskFree} {formatBytes(h.disk_free_bytes)}
        </dd>
        <dt>{L.dataDir}</dt>
        <dd>
          <code>{h.data_dir}</code>
        </dd>
        <dt>{L.threads}</dt>
        <dd>
          {L.scheduler} <StatusTag status={h.scheduler_alive ? 'ok' : 'error'} /> {L.claudeWorker} <StatusTag status={h.claude_worker_alive ? 'ok' : 'error'} /> {L.ioWorker}{' '}
          <StatusTag status={h.io_worker_alive ? 'ok' : 'error'} />
        </dd>
        <dt>{zh.admin.lastTick}</dt>
        <dd>
          <When iso={h.scheduler_last_tick_at} tz={tz} />
        </dd>
        <dt>{L.claudeBin}</dt>
        <dd>
          <StatusTag status={h.claude_bin.ok ? 'ok' : 'error'} /> <code>{h.claude_bin.path}</code> {h.claude_bin.version ?? ''} · {zh.admin.flagTier} {h.claude_bin.flag_tier} ·{' '}
          <When iso={h.claude_bin.last_probe_at} tz={tz} />
        </dd>
        <dt>{L.seedVersion}</dt>
        <dd>
          <code>{h.seed_version ? truncate(h.seed_version, 16) : '—'}</code> · {L.migrations} {h.migrations_version}
        </dd>
        <dt>{L.workerLease}</dt>
        <dd>{h.worker_lease ? `${h.worker_lease.instance} · ${formatDateTime(h.worker_lease.expires_at, tz)}` : '—'}</dd>
        <dt>{L.lastBackup}</dt>
        <dd>{h.last_backup ? `${h.last_backup.file} · ${formatDateTime(h.last_backup.at, tz)} · ${formatBytes(h.last_backup.bytes)}` : '—'}</dd>
      </dl>
    </section>
  );
}

function EventsTable({ events, tz }: { events: SystemEvent[]; tz: string | undefined }) {
  if (events.length === 0) return <p className="admin__empty">{zh.common.none}</p>;
  return (
    <div className="table-scroll">
      <table className="admin-table">
        <thead>
          <tr>
            <th>{L.id}</th>
            <th>{L.kind}</th>
            <th>{L.createdAt}</th>
            <th>{L.detail}</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td className="num">{e.id}</td>
              <td>
                <StatusTag status={e.kind} />
              </td>
              <td>
                <When iso={e.created_at} tz={tz} />
              </td>
              <td className="wrap">
                <JsonCell value={e.detail} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OverviewTab() {
  const tz = useTz();
  const overview = useApi((signal) => endpoints.adminOverview(signal), []);
  const health = useApi((signal) => endpoints.adminHealth(signal), []);
  if (overview.error) return <ErrorBox error={overview.error} onRetry={() => void overview.reload()} />;
  const d = overview.data;
  if (!d) return <Skeleton lines={6} />;
  const ai = d.ai;
  return (
    <div className="admin__stack">
      <div className="tiles">
        <Tile
          label={zh.admin.tabs.users}
          value={formatInt(d.users.total)}
          sub={`${L.active7d} ${formatInt(d.users.active_7d)} · ${L.bankEntries} ${formatInt(d.bank_entries)} · ${L.batchesToday} ${formatInt(d.batches_today)}`}
        />
        <Tile label={zh.admin.spendToday} value={formatUsd(ai.today_usd)} sub={`${zh.admin.cap} ${formatUsd(ai.daily_budget_usd)} · ${L.calls} ${formatInt(ai.calls_today)}`} meter={{ part: ai.today_usd, total: ai.daily_budget_usd }} />
        <Tile label={zh.admin.spendMonth} value={formatUsd(ai.month_usd)} sub={`${zh.admin.cap} ${formatUsd(ai.monthly_budget_usd)}`} meter={{ part: ai.month_usd, total: ai.monthly_budget_usd }} />
        <Tile label={zh.admin.images.svgBudget} value={formatUsd(ai.svg_today_usd)} sub={`${zh.admin.cap} ${formatUsd(ai.svg_daily_budget_usd)}`} meter={{ part: ai.svg_today_usd, total: ai.svg_daily_budget_usd }} />
        <Tile label={zh.admin.queue} value={formatInt(d.jobs.queued)} sub={`${L.running} ${formatInt(d.jobs.running)} · ${L.dead} ${formatInt(d.jobs.dead)}`} tone={d.jobs.dead > 0 ? 'bad' : undefined} />
        <Tile
          label={zh.admin.sms}
          value={`${formatInt(d.sms.sent_today)} / ${formatInt(d.sms.daily_cap)}`}
          sub={`${zh.admin.smsHour} ${formatInt(d.sms.sent_hour)} / ${formatInt(d.sms.hourly_cap)} · ${d.sms.registration_open ? zh.admin.smsRegistrationOpen : zh.admin.smsRegistrationClosed} · ${d.sms.provider}`}
          meter={{ part: d.sms.sent_today, total: d.sms.daily_cap }}
          tone={d.sms.registration_open ? undefined : 'bad'}
        />
        <Tile
          label={zh.admin.lastTick}
          value={d.scheduler.last_tick_at ? formatDateTime(d.scheduler.last_tick_at, tz) : '—'}
          sub={`${L.scheduler} ${d.scheduler.alive ? L.alive : L.stopped}`}
          tone={d.scheduler.alive ? 'good' : 'bad'}
        />
      </div>

      <section className="card admin__card" aria-labelledby="admin-ai">
        <h2 id="admin-ai">{zh.admin.tabs.ai}</h2>
        <dl className="kv">
          <dt>{L.status}</dt>
          <dd>
            <StatusTag status={ai.enabled ? 'ok' : 'error'} />
            {(ai.manual_paused_until || ai.paused_until) && (
              <>
                {' '}
                <PauseNote ai={ai} tz={tz} />
              </>
            )}
          </dd>
          <dt>{zh.admin.flagTier}</dt>
          <dd>{ai.flag_tier}</dd>
          <dt>{L.avgCostPerWord7d}</dt>
          <dd>{ai.avg_cost_per_word_7d === null ? '—' : formatUsd(ai.avg_cost_per_word_7d)}</dd>
          <dt>{L.lastError}</dt>
          <dd>{ai.last_error ? <code>{truncate(ai.last_error, 160)}</code> : '—'}</dd>
        </dl>
      </section>

      <ImageMix words={d.words} />

      <section className="card admin__card" aria-labelledby="admin-jobs">
        <h2 id="admin-jobs">{zh.admin.queue}</h2>
        {Object.keys(d.jobs.by_type).length === 0 ? (
          <p className="admin__empty">{zh.common.none}</p>
        ) : (
          <dl className="kv">
            {Object.entries(d.jobs.by_type).map(([type, n]) => (
              <div key={type} style={{ display: 'contents' }}>
                <dt>{type}</dt>
                <dd>{formatInt(n)}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section className="card admin__card" aria-labelledby="admin-providers">
        <h2 id="admin-providers">{L.providers}</h2>
        {d.images.providers.length === 0 ? (
          <p className="admin__empty">{zh.common.none}</p>
        ) : (
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>{L.provider}</th>
                  <th className="num">{L.perMinute}</th>
                  <th className="num">{L.perDay}</th>
                  <th>{L.cooldownUntil}</th>
                </tr>
              </thead>
              <tbody>
                {d.images.providers.map((p) => (
                  <tr key={p.provider}>
                    <td>{p.provider}</td>
                    <td className="num">
                      {formatInt(p.minute_count)}
                      {p.minute_limit !== null ? ` / ${formatInt(p.minute_limit)}` : ''}
                    </td>
                    <td className="num">
                      {formatInt(p.day_count)}
                      {p.day_limit !== null ? ` / ${formatInt(p.day_limit)}` : ''}
                    </td>
                    <td>
                      <When iso={p.cooldown_until} tz={tz} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {health.data && <HealthCard h={health.data} tz={tz} />}
      {health.error && <ErrorBox error={health.error} onRetry={() => void health.reload()} />}

      <section className="card admin__card" aria-labelledby="admin-events24">
        <h2 id="admin-events24">{zh.admin.tabs.events} · 24h</h2>
        <EventsTable events={d.events_24h} tz={tz} />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
// users & invites
// ---------------------------------------------------------------------------------------------------

function UsersTab() {
  const tz = useTz();
  const toast = useToast();
  const { user: me } = useAuth();
  const [q, setQ] = useState('');
  const users = usePagedList<AdminUser, Page<AdminUser>>((page, signal) => endpoints.adminUsers({ ...(q ? { q } : {}), page, page_size: PAGE_SIZE }, signal), [q]);
  const invites = useApi((signal) => endpoints.adminInvites(signal), []);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [resetFor, setResetFor] = useState<AdminUser | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [maxUses, setMaxUses] = useState('1');
  const [expiresDays, setExpiresDays] = useState('7');
  const [inviteNote, setInviteNote] = useState('');
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<AdminInviteCreated | null>(null);

  const update = async (u: AdminUser, body: AdminUserUpdateBody) => {
    setBusyId(u.id);
    try {
      const res = await endpoints.adminUpdateUser(u.id, body);
      users.setItems((prev) => prev.map((x) => (x.id === u.id ? res : x)));
      toast.success(zh.common.saved);
      return true;
    } catch (e) {
      toast.error(errorMessage(e));
      return false;
    } finally {
      setBusyId(null);
    }
  };

  const submitReset = async (e: FormEvent) => {
    e.preventDefault();
    if (!resetFor || newPassword.length < 8) return;
    if (await update(resetFor, { new_password: newPassword })) {
      setResetFor(null);
      setNewPassword('');
    }
  };

  const createInvite = async (e: FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      const res = await endpoints.adminCreateInvite({
        max_uses: Math.max(1, Math.min(100, Number(maxUses) || 1)),
        expires_in_days: Math.max(1, Math.min(365, Number(expiresDays) || 7)),
        ...(inviteNote.trim() ? { note: inviteNote.trim() } : {}),
      });
      setCreated(res);
      void invites.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  const copy = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      toast.success(zh.common.copied);
    } catch {
      toast.error(zh.common.copy);
    }
  };

  return (
    <div className="admin__stack">
      <section className="card admin__card" aria-labelledby="admin-users">
        <h2 id="admin-users">{zh.admin.tabs.users}</h2>
        <div className="admin__toolbar">
          <SearchBox
            value={q}
            onChange={(v) => {
              setQ(v.trim());
              users.reset();
            }}
            placeholder={zh.auth.username}
          />
          <span className="muted">{users.data ? formatInt(users.total) : ''}</span>
        </div>
        {users.error && <ErrorBox error={users.error} onRetry={() => void users.reload()} />}
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>{L.id}</th>
                <th>{zh.auth.username}</th>
                <th>{zh.settings.displayName}</th>
                <th>{L.phone}</th>
                <th>{L.role}</th>
                <th>{L.active}</th>
                <th>{L.lastLogin}</th>
                <th className="num">{L.bankSize}</th>
                <th className="num">{L.streak}</th>
                <th>{zh.word.actions}</th>
              </tr>
            </thead>
            <tbody>
              {users.items.map((u) => (
                <tr key={u.id}>
                  <td className="num">{u.id}</td>
                  <td>
                    {u.username}
                    {!u.has_password && <span className="tag tag--warn admin__tag">{zh.admin.noPassword}</span>}
                  </td>
                  <td>{u.display_name}</td>
                  <td>{u.phone_masked ?? ''}</td>
                  <td>
                    <StatusTag status={u.role} />
                    {u.account_kind === 'guardian' && <span className="tag tag--brand admin__tag">{zh.admin.guardian}</span>}
                    {u.is_child && <span className="tag admin__tag">{zh.admin.child}</span>}
                  </td>
                  <td>
                    <StatusTag status={u.is_active ? 'ok' : 'disabled'} />
                  </td>
                  <td>
                    <When iso={u.last_login_at} tz={tz} />
                  </td>
                  <td className="num">{formatInt(u.bank_size)}</td>
                  <td className="num">{formatInt(u.streak_days)}</td>
                  <td>
                    <div className="actions">
                      <Button size="sm" disabled={busyId === u.id || u.id === me?.id} onClick={() => void update(u, { is_active: !u.is_active })}>
                        {u.is_active ? zh.admin.disable : zh.admin.enable}
                      </Button>
                      {u.role !== 'admin' && (
                        <Button size="sm" disabled={busyId === u.id} onClick={() => void update(u, { role: 'admin' })}>
                          {zh.admin.makeAdmin}
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" disabled={busyId === u.id} onClick={() => setResetFor(u)}>
                        {zh.admin.resetPassword}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager page={users.page} pageSize={PAGE_SIZE} total={users.total} loading={users.loading} onChange={users.goTo} />
      </section>

      <section className="card admin__card" aria-labelledby="admin-invites">
        <h2 id="admin-invites">{zh.admin.invite}</h2>
        <form className="admin__form" onSubmit={createInvite}>
          <Field label={L.maxUses}>{(c) => <input {...c} type="number" min={1} max={100} value={maxUses} onChange={(e) => setMaxUses(e.target.value)} />}</Field>
          <Field label={L.expiresInDays}>{(c) => <input {...c} type="number" min={1} max={365} value={expiresDays} onChange={(e) => setExpiresDays(e.target.value)} />}</Field>
          <Field label={L.note}>{(c) => <input {...c} type="text" maxLength={120} value={inviteNote} onChange={(e) => setInviteNote(e.target.value)} />}</Field>
          <Button type="submit" variant="primary" loading={creating}>
            {zh.admin.invite}
          </Button>
        </form>
        {created && (
          <div className="invite-code" role="status">
            <code>{created.code}</code>
            <Button size="sm" onClick={() => void copy(created.code)}>
              {zh.common.copy}
            </Button>
            <span className="muted">{zh.admin.inviteOnce}</span>
          </div>
        )}
        {invites.error && <ErrorBox error={invites.error} onRetry={() => void invites.reload()} />}
        {invites.data && invites.data.items.length > 0 && (
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>{L.id}</th>
                  <th className="num">{L.uses}</th>
                  <th>{L.expiresAt}</th>
                  <th>{L.note}</th>
                  <th>{L.createdAt}</th>
                  <th>{L.createdBy}</th>
                </tr>
              </thead>
              <tbody>
                {invites.data.items.map((inv) => (
                  <tr key={inv.id}>
                    <td className="num">{inv.id}</td>
                    <td className="num">
                      {inv.uses} / {inv.max_uses}
                    </td>
                    <td>
                      <When iso={inv.expires_at} tz={tz} />
                    </td>
                    <td className="wrap">{inv.note ?? ''}</td>
                    <td>
                      <When iso={inv.created_at} tz={tz} />
                    </td>
                    <td>{inv.created_by ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <DisputedIdentities />

      <Sheet open={resetFor !== null} onClose={() => setResetFor(null)} title={`${zh.admin.resetPassword} · ${resetFor?.username ?? ''}`}>
        <form className="auth__form" onSubmit={submitReset}>
          <Field label={zh.settings.newPassword} hint={zh.auth.passwordHint} required>
            {(c) => <input {...c} type="password" autoComplete="new-password" minLength={8} maxLength={64} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />}
          </Field>
          <Button type="submit" variant="primary" block loading={busyId !== null} disabled={newPassword.length < 8}>
            {zh.common.save}
          </Button>
        </form>
      </Sheet>
    </div>
  );
}

/** Disputed bindings (API.md 92 / 93): phone bindings a new owner disputed; restore clears `disputed_at` unless the number is live elsewhere (409 identity_taken). */
function DisputedIdentities() {
  const tz = useTz();
  const toast = useToast();
  const rows = usePagedList<DisputedIdentity, Page<DisputedIdentity>>((page, signal) => endpoints.adminDisputedIdentities(page, signal), []);
  const [busyId, setBusyId] = useState<number | null>(null);
  const restore = async (row: DisputedIdentity) => {
    setBusyId(row.id);
    try {
      await endpoints.adminRestoreIdentity(row.id);
      rows.setItems((prev) => prev.filter((x) => x.id !== row.id)); // no longer disputed → out of the list
      toast.success(zh.admin.restored);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusyId(null);
    }
  };
  return (
    <section className="card admin__card" aria-labelledby="admin-disputed">
      <h2 id="admin-disputed">{zh.admin.disputed}</h2>
      {rows.error && <ErrorBox error={rows.error} onRetry={() => void rows.reload()} />}
      {!rows.loading && rows.items.length === 0 ? (
        <p className="admin__empty">{zh.common.none}</p>
      ) : (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>{L.id}</th>
                <th>{L.user}</th>
                <th>{L.phone}</th>
                <th>{L.verifiedAt}</th>
                <th>{L.lastLogin}</th>
                <th>{L.disputedAt}</th>
                <th>{L.currentHolder}</th>
                <th>{zh.word.actions}</th>
              </tr>
            </thead>
            <tbody>
              {rows.items.map((r) => (
                <tr key={r.id}>
                  <td className="num">{r.id}</td>
                  <td>
                    {r.user.display_name || r.user.username} <span className="muted">#{r.user.id}</span>
                  </td>
                  <td>{r.subject_masked}</td>
                  <td>
                    <When iso={r.verified_at} tz={tz} />
                  </td>
                  <td>
                    <When iso={r.last_login_at} tz={tz} />
                  </td>
                  <td>
                    <When iso={r.disputed_at} tz={tz} />
                  </td>
                  <td className="num">{r.current_user_id === null ? '—' : `#${r.current_user_id}`}</td>
                  <td>
                    <Button size="sm" disabled={busyId === r.id} onClick={() => void restore(r)}>
                      {zh.admin.restore}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={rows.page} pageSize={PAGE_SIZE} total={rows.total} loading={rows.loading} onChange={rows.goTo} />
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------
// jobs
// ---------------------------------------------------------------------------------------------------

function JobsTab() {
  const tz = useTz();
  const toast = useToast();
  const { server } = useAuth();
  const [status, setStatus] = useState('');
  const [type, setType] = useState('');
  const jobs = usePagedList<Job, Page<Job>>(
    (page, signal) => endpoints.adminJobs({ ...(status ? { status } : {}), ...(type ? { type } : {}), page, page_size: PAGE_SIZE }, signal),
    [status, type],
  );
  const [busy, setBusy] = useState(false);

  const retry = async (job: Job) => {
    try {
      const res = await endpoints.adminRetryJob(job.id);
      jobs.setItems((prev) => prev.map((j) => (j.id === job.id ? res : j)));
      toast.success(zh.admin.retry);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };
  const requeueDead = async () => {
    setBusy(true);
    try {
      const res = await endpoints.adminRequeueDead();
      toast.success(`${zh.admin.requeueDead} · ${formatInt(res.requeued)}`);
      void jobs.reload();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const runOnce = async () => {
    setBusy(true);
    try {
      const res = await endpoints.adminRunOnce();
      toast.success(`run-once · ${formatInt(res.processed)}`);
      void jobs.reload();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card admin__card" aria-labelledby="admin-jobs-tab">
      <h2 id="admin-jobs-tab">{zh.admin.tabs.jobs}</h2>
      <div className="admin__toolbar">
        <select
          aria-label={L.status}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            jobs.reset();
          }}
        >
          <option value="">
            {L.status}: {zh.common.all}
          </option>
          {JOB_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <SearchBox
          value={type}
          onChange={(v) => {
            setType(v.trim());
            jobs.reset();
          }}
          placeholder={L.type}
          aria-label={L.type}
        />
        <span className="admin__spacer" />
        <Button size="sm" loading={busy} onClick={() => void requeueDead()}>
          {zh.admin.requeueDead}
        </Button>
        {server?.dev && (
          <Button size="sm" variant="ghost" loading={busy} onClick={() => void runOnce()}>
            run-once
          </Button>
        )}
      </div>
      {jobs.error && <ErrorBox error={jobs.error} onRetry={() => void jobs.reload()} />}
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>{L.id}</th>
              <th>{L.type}</th>
              <th>{L.status}</th>
              <th className="num">{L.priority}</th>
              <th className="num">{L.attempts}</th>
              <th>{L.runAfter}</th>
              <th>{L.lockedBy}</th>
              <th>{L.payload}</th>
              <th>{L.lastError}</th>
              <th>{zh.word.actions}</th>
            </tr>
          </thead>
          <tbody>
            {jobs.items.map((j) => (
              <tr key={j.id}>
                <td className="num">{j.id}</td>
                <td>{j.type}</td>
                <td>
                  <StatusTag status={j.status} />
                </td>
                <td className="num">{j.priority}</td>
                <td className="num">
                  {j.attempts} / {j.max_attempts}
                </td>
                <td>
                  <When iso={j.run_after} tz={tz} />
                </td>
                <td>{j.locked_by ?? ''}</td>
                <td className="wrap">
                  <JsonCell value={j.payload} />
                </td>
                <td className="wrap">{j.last_error ? <code title={j.last_error}>{truncate(j.last_error, 100)}</code> : ''}</td>
                <td>
                  {j.status !== 'running' && j.status !== 'queued' && (
                    <Button size="sm" onClick={() => void retry(j)}>
                      {zh.admin.retry}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!jobs.loading && jobs.items.length === 0 && <p className="admin__empty">{zh.common.none}</p>}
      <Pager page={jobs.page} pageSize={PAGE_SIZE} total={jobs.total} loading={jobs.loading} onChange={jobs.goTo} />
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------
// AI
// ---------------------------------------------------------------------------------------------------

function AiTab() {
  const tz = useTz();
  const toast = useToast();
  const overview = useApi((signal) => endpoints.adminOverview(signal), []);
  const calls = usePagedList<AiCall, AiCallsResponse>((page, signal) => endpoints.adminAiCalls(page, signal), []);
  const [busy, setBusy] = useState<'pause' | 'probe' | 'probeFallback' | 'prewarm' | null>(null);
  const [stage, setStage] = useState<PrewarmStage>('cet4');
  const [limit, setLimit] = useState('50');
  const [budget, setBudget] = useState('1');

  const ai = overview.data?.ai;
  // the toggle is the admin's own pause; the CLI's automatic pause (fallback serving) is a note, see PauseNote
  const paused = Boolean(ai?.manual_paused_until);

  const togglePause = async () => {
    setBusy('pause');
    try {
      const res = await endpoints.adminAiPause(!paused);
      // a pause sets the global pause (the merged paused_until follows it); a resume clears every pause (CLAUDE_INTEGRATION §10.5)
      overview.setData((prev) => (prev ? { ...prev, ai: { ...prev.ai, manual_paused_until: res.paused_until, paused_until: res.paused_until } } : prev));
      void overview.reload(); // a resume also clears the fallback pause and resets the active provider
      toast.success(res.paused ? zh.admin.paused : zh.admin.resume);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const probe = async (provider: AiProvider = 'claude') => {
    setBusy(provider === 'fallback' ? 'probeFallback' : 'probe');
    try {
      const res = await endpoints.adminAiProbe(provider);
      const prefix = provider === 'fallback' ? `${zh.admin.providerFallback} · ` : '';
      const okText = provider === 'fallback' ? zh.admin.probeFallbackOk(res.model_used ?? '') : zh.admin.probeOk(res.flag_tier);
      if (res.ok) toast.success(`${provider === 'fallback' ? '' : prefix}${okText} · ${formatUsd(res.cost_usd)} · ${formatInt(res.duration_ms)} ms`);
      else toast.error(res.error ?? zh.errors.server);
      void overview.reload();
      void calls.reload();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const prewarm = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('prewarm');
    try {
      const res = await endpoints.adminPrewarm({
        stage,
        limit: Math.max(1, Math.min(2000, Number(limit) || 1)),
        max_budget_usd: Math.max(0.1, Math.min(50, Number(budget) || 0.1)),
      });
      toast.success(`${zh.admin.prewarm} · ${formatInt(res.planned)} · ${zh.admin.tabs.jobs} ${res.job_id}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="admin__stack">
      <section className="card admin__card" aria-labelledby="admin-ai-tab">
        <h2 id="admin-ai-tab">{zh.admin.tabs.ai}</h2>
        {overview.error && <ErrorBox error={overview.error} onRetry={() => void overview.reload()} />}
        {ai && (
          <div className="tiles">
            <Tile label={zh.admin.spendToday} value={formatUsd(calls.data?.today_usd ?? ai.today_usd)} sub={`${zh.admin.cap} ${formatUsd(ai.daily_budget_usd)}`} meter={{ part: ai.today_usd, total: ai.daily_budget_usd }} />
            <Tile label={zh.admin.spendMonth} value={formatUsd(calls.data?.month_usd ?? ai.month_usd)} sub={`${zh.admin.cap} ${formatUsd(ai.monthly_budget_usd)}`} meter={{ part: ai.month_usd, total: ai.monthly_budget_usd }} />
            <Tile label={zh.admin.flagTier} value={ai.flag_tier} sub={ai.enabled ? L.enabled : L.disabled} tone={ai.enabled ? 'good' : 'bad'} />
            <Tile
              label={zh.admin.activeProvider}
              value={ai.active_provider === 'fallback' ? zh.admin.providerFallback : zh.admin.providerClaude}
              sub={ai.fallback_configured ? `${zh.admin.providerFallback} ${fallbackAvailability(ai.fallback_available)} · ${L.calls} ${formatInt(ai.fallback_calls_today)}` : undefined}
              tone={ai.active_provider === 'fallback' ? 'bad' : 'good'}
            />
            <Tile
              label={L.avgCostPerWord7d}
              value={(calls.data?.avg_cost_per_word_7d ?? ai.avg_cost_per_word_7d) === null ? '—' : formatUsd(calls.data?.avg_cost_per_word_7d ?? ai.avg_cost_per_word_7d ?? 0)}
            />
          </div>
        )}
        <div className="admin__toolbar" style={{ marginTop: 'var(--space-3)' }}>
          <Button size="sm" variant={paused ? 'primary' : 'secondary'} loading={busy === 'pause'} disabled={!ai} onClick={() => void togglePause()}>
            {paused ? zh.admin.resume : zh.admin.pause}
          </Button>
          {ai && (ai.manual_paused_until || ai.paused_until) && (
            <span className="muted">
              <PauseNote ai={ai} tz={tz} />
            </span>
          )}
          {ai?.fallback_paused_until && (
            <span className="muted">
              {zh.admin.fallbackPaused} · <When iso={ai.fallback_paused_until} tz={tz} />
            </span>
          )}
          <Button size="sm" loading={busy === 'probe'} onClick={() => void probe()}>
            {zh.admin.probe}
          </Button>
          {ai?.fallback_configured && (
            <Button size="sm" loading={busy === 'probeFallback'} onClick={() => void probe('fallback')}>
              {zh.admin.probeFallback}
            </Button>
          )}
        </div>
        <form className="admin__form" onSubmit={prewarm}>
          <Field label={zh.admin.prewarm}>
            {(c) => (
              <select {...c} value={stage} onChange={(e) => setStage(e.target.value as PrewarmStage)}>
                {PREWARM_STAGES.map((s) => (
                  <option key={s} value={s}>
                    {s === 'all' ? zh.common.all : zh.stages[s]}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={L.limit}>{(c) => <input {...c} type="number" min={1} max={2000} value={limit} onChange={(e) => setLimit(e.target.value)} />}</Field>
          <Field label={L.maxBudgetUsd}>{(c) => <input {...c} type="number" min={0.1} max={50} step={0.1} value={budget} onChange={(e) => setBudget(e.target.value)} />}</Field>
          <Button type="submit" variant="primary" loading={busy === 'prewarm'}>
            {zh.admin.prewarm}
          </Button>
        </form>
      </section>

      <section className="card admin__card" aria-labelledby="admin-ledger">
        <h2 id="admin-ledger">{L.ledger}</h2>
        {calls.error && <ErrorBox error={calls.error} onRetry={() => void calls.reload()} />}
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>{L.id}</th>
                <th>{L.kind}</th>
                <th>{L.source}</th>
                <th>{L.status}</th>
                <th>{L.model}</th>
                <th className="num">{L.tier}</th>
                <th className="num">{L.words}</th>
                <th className="num">{L.cost}</th>
                <th className="num">{L.durationMs}</th>
                <th className="num">{L.tokens}</th>
                <th>{L.startedAt}</th>
                <th>{L.error}</th>
              </tr>
            </thead>
            <tbody>
              {calls.items.map((c) => (
                <tr key={c.id}>
                  <td className="num">{c.id}</td>
                  <td>{c.kind}</td>
                  <td>{c.provider === 'fallback' ? zh.admin.providerFallback : zh.admin.providerClaude}</td>
                  <td>
                    <StatusTag status={c.status} />
                  </td>
                  <td>{c.model_used ?? c.model_requested}</td>
                  <td className="num">{c.flag_tier}</td>
                  <td className="num">{c.word_count}</td>
                  <td className="num">{formatUsd(c.cost_usd)}</td>
                  <td className="num">{c.duration_ms === null ? '' : formatInt(c.duration_ms)}</td>
                  <td className="num">{c.input_tokens === null && c.output_tokens === null ? '' : `${formatInt(c.input_tokens ?? 0)} / ${formatInt(c.output_tokens ?? 0)}`}</td>
                  <td>
                    <When iso={c.started_at} tz={tz} />
                  </td>
                  <td className="wrap">{c.error ? <code title={c.error}>{truncate(c.error, 100)}</code> : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!calls.loading && calls.items.length === 0 && <p className="admin__empty">{zh.common.none}</p>}
        <Pager page={calls.page} pageSize={PAGE_SIZE} total={calls.total} loading={calls.loading} onChange={calls.goTo} />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
// reports
// ---------------------------------------------------------------------------------------------------

function ReportsTab() {
  const tz = useTz();
  const toast = useToast();
  const [status, setStatus] = useState<ReportStatusFilter>('open');
  const reports = usePagedList<Report, Page<Report>>((page, signal) => endpoints.adminReports({ status, page, page_size: PAGE_SIZE }, signal), [status]);
  const [busyId, setBusyId] = useState<number | null>(null);

  const resolve = async (r: Report, body: { status: 'resolved' | 'dismissed'; regenerate?: boolean; refetch_image?: boolean }) => {
    setBusyId(r.id);
    try {
      const res = await endpoints.adminResolveReport(r.id, body);
      reports.setItems((prev) => prev.map((x) => (x.id === r.id ? res : x)).filter((x) => x.status === status));
      toast.success(zh.common.saved);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="card admin__card" aria-labelledby="admin-reports">
      <h2 id="admin-reports">{zh.admin.tabs.reports}</h2>
      <div className="admin__toolbar">
        <select
          aria-label={L.status}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as ReportStatusFilter);
            reports.reset();
          }}
        >
          {REPORT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <span className="muted">{reports.data ? formatInt(reports.total) : ''}</span>
      </div>
      {reports.error && <ErrorBox error={reports.error} onRetry={() => void reports.reload()} />}
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>{L.id}</th>
              <th>{L.word}</th>
              <th>{L.user}</th>
              <th>{L.target}</th>
              <th>{zh.word.report}</th>
              <th>{L.note}</th>
              <th>{L.createdAt}</th>
              <th>{L.status}</th>
              <th>{zh.word.actions}</th>
            </tr>
          </thead>
          <tbody>
            {reports.items.map((r) => (
              <tr key={r.id}>
                <td className="num">{r.id}</td>
                <td>
                  <Link to={routePaths.word(r.word.id)} lang="en">
                    {r.word.display}
                  </Link>
                </td>
                <td>{r.user.username}</td>
                <td>{r.target}</td>
                <td>{zh.word.reportReasons[r.reason]}</td>
                <td className="wrap">{r.note ?? ''}</td>
                <td>
                  <When iso={r.created_at} tz={tz} />
                </td>
                <td>
                  <StatusTag status={r.status} />
                  {r.resolution ? <code title={r.resolution}> {truncate(r.resolution, 40)}</code> : null}
                </td>
                <td>
                  {r.status === 'open' && (
                    <div className="actions">
                      {r.target !== 'image' && (
                        <Button size="sm" disabled={busyId === r.id} onClick={() => void resolve(r, { status: 'resolved', regenerate: true })}>
                          {zh.admin.regenerate}
                        </Button>
                      )}
                      {r.target !== 'content' && (
                        <Button size="sm" disabled={busyId === r.id} onClick={() => void resolve(r, { status: 'resolved', refetch_image: true })}>
                          {zh.admin.refetchImage}
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" disabled={busyId === r.id} onClick={() => void resolve(r, { status: 'dismissed' })}>
                        {zh.admin.dismiss}
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!reports.loading && reports.items.length === 0 && <p className="admin__empty">{zh.common.none}</p>}
      <Pager page={reports.page} pageSize={PAGE_SIZE} total={reports.total} loading={reports.loading} onChange={reports.goTo} />
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------
// events, config
// ---------------------------------------------------------------------------------------------------

function EventsTab() {
  const tz = useTz();
  const events = usePagedList<SystemEvent, Page<SystemEvent>>((page, signal) => endpoints.adminEvents(page, signal), []);
  return (
    <section className="card admin__card" aria-labelledby="admin-events">
      <h2 id="admin-events">{zh.admin.tabs.events}</h2>
      {events.error && <ErrorBox error={events.error} onRetry={() => void events.reload()} />}
      {events.loading && events.items.length === 0 ? <Skeleton lines={4} /> : <EventsTable events={events.items} tz={tz} />}
      <Pager page={events.page} pageSize={PAGE_SIZE} total={events.total} loading={events.loading} onChange={events.goTo} />
    </section>
  );
}

function ConfigTab() {
  const config = useApi((signal) => endpoints.adminConfig(signal), []);
  return (
    <section className="card admin__card" aria-labelledby="admin-config">
      <h2 id="admin-config">{zh.admin.tabs.config}</h2>
      {config.error && <ErrorBox error={config.error} onRetry={() => void config.reload()} />}
      {!config.data ? (
        <Skeleton lines={6} />
      ) : (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>{L.key}</th>
                <th>{L.value}</th>
                <th>{L.source}</th>
              </tr>
            </thead>
            <tbody>
              {config.data.entries.map((entry) => (
                <tr key={entry.key}>
                  <td>
                    <code>{entry.key}</code>
                  </td>
                  <td className="wrap">
                    <code title={entry.value}>{truncate(entry.value, 120)}</code>
                  </td>
                  <td>
                    <StatusTag status={entry.source} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------

export default function AdminPage() {
  usePageTitle(zh.admin.title);
  const [tabPref, setTabPref] = useLocalPref<string>('wd.adminTab', 'overview');
  const tab: AdminTab = isAdminTab(tabPref) ? tabPref : 'overview';
  return (
    <section className="page admin">
      <h1 className="page__title">{zh.admin.title}</h1>
      <Tabs aria-label={zh.admin.title} items={TABS.map((t) => ({ key: t, label: zh.admin.tabs[t] }))} value={tab} onChange={(k) => setTabPref(k)} />
      <div className="admin__panel" role="tabpanel">
        {tab === 'overview' && <OverviewTab />}
        {tab === 'users' && <UsersTab />}
        {tab === 'jobs' && <JobsTab />}
        {tab === 'ai' && <AiTab />}
        {tab === 'reports' && <ReportsTab />}
        {tab === 'events' && <EventsTab />}
        {tab === 'config' && <ConfigTab />}
      </div>
    </section>
  );
}
