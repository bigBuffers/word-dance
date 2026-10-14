// ConfirmDialog — modal confirmation on a native <dialog> (FRONTEND §4), e.g. the mastered confirmation (zh.study.masterConfirm).
import { useEffect, useId, useRef, type ReactNode, type SyntheticEvent } from 'react';
import { zh } from '@/i18n/zh';
import { Button } from './Button';
import { useNativeDialog } from './useNativeDialog';
import './ui.css';

export interface ConfirmDialogProps {
  open: boolean;
  title?: ReactNode;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive action: red confirm button. */
  danger?: boolean;
  /** The confirm action is in flight: spinner on confirm, cancel disabled, Esc ignored. */
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = zh.common.confirm,
  cancelLabel = zh.common.cancel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const messageId = useId();
  useNativeDialog(ref, open);

  // Focus the safe option first (the destructive button is never the default).
  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);

  const handleCancel = (e: SyntheticEvent<HTMLDialogElement>) => {
    e.preventDefault();
    if (!busy) onCancel();
  };
  const handleClosed = () => {
    if (open && !busy) onCancel();
  };

  const hasTitle = title !== undefined && title !== null;
  return (
    <dialog
      ref={ref}
      className="confirm"
      role="alertdialog"
      aria-labelledby={hasTitle ? titleId : undefined}
      aria-describedby={messageId}
      onCancel={handleCancel}
      onClose={handleClosed}
    >
      {hasTitle && (
        <h2 id={titleId} className="confirm__title">
          {title}
        </h2>
      )}
      <p id={messageId} className="confirm__message">
        {message}
      </p>
      <div className="confirm__actions">
        <Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={busy}>
          {cancelLabel}
        </Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={() => void onConfirm()} loading={busy}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
