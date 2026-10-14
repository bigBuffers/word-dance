// EmptyState — every empty state carries exactly one action (FRONTEND §6.1).
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { Button } from './Button';
import { cx } from './cx';
import './ui.css';

export interface EmptyStateAction {
  label: string;
  /** Internal route to navigate to… */
  to?: string;
  /** …or a handler. */
  onClick?: () => void;
}

export interface EmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  action?: EmptyStateAction;
  icon?: ReactNode;
  className?: string;
}

export function EmptyState({ title, description, action, icon, className }: EmptyStateProps) {
  return (
    <div className={cx('empty', className)} role="status">
      {icon !== undefined && icon !== null && (
        <div className="empty__icon" aria-hidden="true">
          {icon}
        </div>
      )}
      <p className="empty__title">{title}</p>
      {description !== undefined && description !== null && <p className="empty__desc">{description}</p>}
      {action &&
        (action.to ? (
          <Link className="btn btn--primary btn--md empty__action" to={action.to}>
            <span className="btn__label">{action.label}</span>
          </Link>
        ) : (
          <Button variant="primary" className="empty__action" onClick={action.onClick}>
            {action.label}
          </Button>
        ))}
    </div>
  );
}
