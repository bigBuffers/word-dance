// Sheet — a native <dialog> that slides up from the bottom on phones and is a centred modal on
// desktop (FRONTEND §4). Backdrop click / Esc call `onClose` when `dismissible`.
import { useId, useRef, type MouseEvent, type ReactNode, type SyntheticEvent } from 'react';
import { zh } from '@/i18n/zh';
import { Button } from './Button';
import { cx } from './cx';
import { CloseIcon } from './icons';
import { useNativeDialog } from './useNativeDialog';
import './ui.css';

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Backdrop click, Esc and the × button close the sheet (default true). */
  dismissible?: boolean;
  className?: string;
  /** Accessible name when there is no `title`. */
  'aria-label'?: string;
}

export function Sheet({ open, onClose, title, children, footer, dismissible = true, className, 'aria-label': ariaLabel }: SheetProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useNativeDialog(ref, open);

  const handleCancel = (e: SyntheticEvent<HTMLDialogElement>) => {
    e.preventDefault(); // we own the open state; close through the parent
    if (dismissible) onClose();
  };
  const handleBackdrop = (e: MouseEvent<HTMLDialogElement>) => {
    if (dismissible && e.target === ref.current) onClose();
  };
  const handleClosed = () => {
    if (open) onClose(); // closed natively (e.g. a form with method="dialog")
  };

  const hasTitle = title !== undefined && title !== null;
  return (
    <dialog
      ref={ref}
      className={cx('sheet', className)}
      aria-labelledby={hasTitle ? titleId : undefined}
      aria-label={hasTitle ? undefined : ariaLabel}
      onCancel={handleCancel}
      onClick={handleBackdrop}
      onClose={handleClosed}
    >
      <div className="sheet__panel">
        <div className="sheet__handle" aria-hidden="true" />
        {(hasTitle || dismissible) && (
          <header className="sheet__head">
            {hasTitle ? (
              <h2 id={titleId} className="sheet__title">
                {title}
              </h2>
            ) : (
              <span />
            )}
            {dismissible && (
              <Button variant="ghost" iconOnly size="sm" className="sheet__close" aria-label={zh.common.close} onClick={onClose}>
                <CloseIcon />
              </Button>
            )}
          </header>
        )}
        <div className="sheet__body">{children}</div>
        {footer !== undefined && footer !== null && <footer className="sheet__foot">{footer}</footer>}
      </div>
    </dialog>
  );
}
