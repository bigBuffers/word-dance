// ProfilePromptDialog — the legacy profile prompt `zh.children.promptTitle` (owner decision D12; docs/AUTH_SIGNUP_DESIGN.md §5.2, legacy accounts; API.md 110 / 111;
// FRONTEND §2 / §4). A pre-1-A account that never declared its kind / age band (`User.needs_profile_prompt`) is asked once per
// sitting, after onboarding (`onboarding_state === 'done'`): guardian (guardian / adult), adult learner (learner / adult) and
// student aged 14+ (learner / 14plus) → endpoint 110 → `applySession({user})`; `promptChild` (never for admins) closes the
// prompt and opens `ClaimDialog` (108 / 109); `promptLater` — the button, Esc or the backdrop — → endpoint 111 (a 30-day snooze; its
// failure is ignored) → closed. A 409 `invalid_transition` (declared in another tab, or a placeholder account that must use
// /welcome step 0) refreshes the session and closes. The module-level `shownForUser` set keeps the prompt from re-opening on every
// route change in the same sitting; `resetProfilePrompt()` is for tests. Mounted by the shell (`AppLayout`) on every non-bare route.
import { useEffect, useState, type FormEvent } from 'react';
import { errorMessage, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { DeclareBody } from '@/api/endpoints';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { Sheet } from '@/components/ui/Sheet';
import { zh } from '@/i18n/zh';
import { validationFieldMessages } from '@/utils/auth';
import { ClaimDialog } from './ClaimDialog';
import '@/components/ui/auth.css';

export type Declaration = 'guardian' | 'adult' | '14plus';
export const DECLARATIONS: readonly Declaration[] = ['guardian', 'adult', '14plus'];
/** The body of endpoint 110 for each declaration. */
export const DECLARE_BODY: Record<Declaration, DeclareBody> = {
  guardian: { account_kind: 'guardian', age_band: 'adult' },
  adult: { account_kind: 'learner', age_band: 'adult' },
  '14plus': { account_kind: 'learner', age_band: '14plus' },
};
const LABEL: Record<Declaration, string> = { guardian: zh.children.roleGuardian, adult: zh.children.roleAdult, '14plus': zh.children.roleStudent };

const shownForUser = new Set<number>();
/** Test hook: forget which users saw the prompt in this sitting. */
export function resetProfilePrompt(): void {
  shownForUser.clear();
}

export function ProfilePromptDialog() {
  const { user, applySession, refresh } = useAuth();
  const [open, setOpen] = useState(false);
  const [claimOpen, setClaimOpen] = useState(false);
  const [choice, setChoice] = useState<Declaration | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const due = user !== null && user.needs_profile_prompt && user.onboarding_state === 'done';
  const userId = user?.id ?? null;
  useEffect(() => {
    if (!due || userId === null || shownForUser.has(userId)) return;
    shownForUser.add(userId);
    setOpen(true);
  }, [due, userId]);

  if (!user) return null;

  const close = () => {
    setOpen(false);
    setChoice(null);
    setError(null);
    setBusy(false);
  };

  const later = () => {
    if (busy) return;
    close();
    void endpoints.skipDeclare().catch(() => undefined); // a 30-day snooze; the prompt comes back later if this fails
  };

  const declare = async (e: FormEvent) => {
    e.preventDefault();
    if (!choice || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await endpoints.declareAccount(DECLARE_BODY[choice]);
      applySession({ user: res.user });
      close();
    } catch (err) {
      if (isApiError(err) && err.code === 'invalid_transition') {
        await refresh().catch(() => undefined); // declared elsewhere (or a placeholder account): take the server's user
        close();
        return;
      }
      setError(validationFieldMessages(err) ?? errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <>
      {open && (
        <Sheet open onClose={later} title={zh.children.promptTitle} dismissible={!busy}>
          <form className="auth__form" onSubmit={declare} noValidate>
            <p className="auth__lead">{zh.children.promptLead}</p>
            <div className="auth__radios" role="radiogroup" aria-label={zh.welcome.ageBand}>
              {DECLARATIONS.map((d) => (
                <label key={d} className="auth__radio">
                  <input type="radio" name="declare" value={d} checked={choice === d} disabled={busy} onChange={() => setChoice(d)} />
                  <span>{LABEL[d]}</span>
                </label>
              ))}
            </div>
            {error && (
              <p className="auth__error" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={choice === null}>
              {zh.common.confirm}
            </Button>
            <div className="auth__links">
              {user.role !== 'admin' && (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    close();
                    setClaimOpen(true);
                  }}
                >
                  {zh.children.promptChild}
                </Button>
              )}
              <Button type="button" variant="ghost" disabled={busy} onClick={later}>
                {zh.children.promptLater}
              </Button>
            </div>
          </form>
        </Sheet>
      )}
      <ClaimDialog open={claimOpen} onClose={() => setClaimOpen(false)} />
    </>
  );
}
