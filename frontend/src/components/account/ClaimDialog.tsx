// ClaimDialog — "this is a child's account" (owner decision D12; docs/AUTH_SIGNUP_DESIGN.md §5.2, legacy accounts; API.md 108 / 109; FRONTEND §4): a
// learner hands the account to the guardian who owns a phone number. The guardian's phone receives a claim code (endpoint 108 —
// the answer is the same whether or not the number has an account), the learner types it with the child's age band (109) and the
// account becomes a child of that guardian — created on the spot when the number has none (the guardian then finishes /welcome
// step 0 as a guardian). Opened from the legacy profile prompt and from the settings row (the callers hide it for children, guardians with
// children and admins — the server refuses those too). Needs SMS on the server (`ServerFlags.sms_enabled`): otherwise the sheet
// carries only `zh.children.claimSmsOff`. Errors are toasts through `errorMessage` (a `validation_error` shows its field text).
// Mounted only while `open`.
import { useState, type FormEvent } from 'react';
import { errorMessage } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { GuardianClaimBody } from '@/api/endpoints';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { CodeField, CODE_LENGTH } from '@/components/ui/CodeField';
import { PhoneField } from '@/components/ui/PhoneField';
import { Sheet } from '@/components/ui/Sheet';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { isMainlandPhone, phoneToE164, validationFieldMessages } from '@/utils/auth';
import '@/components/ui/auth.css';

export interface ClaimDialogProps {
  open: boolean;
  onClose: () => void;
}

type ClaimBand = GuardianClaimBody['age_band'];

export function ClaimDialog({ open, onClose }: ClaimDialogProps) {
  const { server, user, applySession } = useAuth();
  const toast = useToast();
  const [digits, setDigits] = useState('');
  const [code, setCode] = useState('');
  const [ageBand, setAgeBand] = useState<ClaimBand | null>(null);
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const smsOn = server?.sms_enabled === true;
  const hasContacts = Boolean(user?.phone_masked || user?.email); // a u14 claim detaches them (API.md 109; children.html §2)
  const target = isMainlandPhone(digits) ? phoneToE164(digits) : null;
  const ready = !busy && target !== null && code.length === CODE_LENGTH && ageBand !== null;

  const close = () => {
    if (busy) return;
    setDigits('');
    setCode('');
    setAgeBand(null);
    onClose();
  };

  const send = async () => {
    if (!target) return;
    try {
      await endpoints.requestGuardianClaimCode({ target });
      toast.success(zh.auth.codeSent);
    } catch (e) {
      toast.error(validationFieldMessages(e) ?? errorMessage(e));
      throw e; // the CodeField skips its countdown
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || target === null || ageBand === null) return;
    setBusy(true);
    try {
      const res = await endpoints.claimGuardian({ target, code, age_band: ageBand });
      applySession({ user: res.user }); // `is_child` is now true: the account page switches to the child note
      toast.success(zh.children.claimed);
      setBusy(false);
      setDigits('');
      setCode('');
      setAgeBand(null);
      onClose();
    } catch (err) {
      toast.error(validationFieldMessages(err) ?? errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Sheet open onClose={close} title={zh.children.claimTitle} dismissible={!busy}>
      {!smsOn ? (
        <p className="auth__lead" role="status">
          {zh.children.claimSmsOff}
        </p>
      ) : (
        <form className="auth__form" onSubmit={submit} noValidate>
          <p className="auth__lead">{zh.children.claimLead}</p>
          <PhoneField label={zh.children.guardianPhone} value={digits} onChange={setDigits} hint={zh.auth.phoneHint} disabled={busy} autoFocus />
          <CodeField key={target ?? ''} value={code} onChange={setCode} onSend={send} canSend={target !== null} disabled={busy} />
          <div className="auth__radios" role="radiogroup" aria-label={zh.welcome.ageBand}>
            <label className="auth__radio">
              <input type="radio" name="claim_age_band" value="u14" checked={ageBand === 'u14'} disabled={busy} onChange={() => setAgeBand('u14')} />
              <span>{zh.children.claimU14}</span>
            </label>
            <label className="auth__radio">
              <input type="radio" name="claim_age_band" value="14plus" checked={ageBand === '14plus'} disabled={busy} onChange={() => setAgeBand('14plus')} />
              <span>{zh.children.claim14plus}</span>
            </label>
          </div>
          {ageBand === 'u14' && hasContacts ? (
            <p className="auth__hint" role="note">
              {zh.children.claimDetach}
            </p>
          ) : null}
          <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!ready}>
            {zh.common.confirm}
          </Button>
        </form>
      )}
    </Sheet>
  );
}
