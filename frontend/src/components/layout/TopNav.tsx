// TopNav — desktop (≥ 768 px) top navigation: the five primary items plus admin for admins, with the
// same badges as the TabBar (FRONTEND §2).
import { Link, NavLink } from 'react-router';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import { ADMIN_NAV, PRIMARY_NAV, navBadge, type ShellBadges } from './TabBar';
import './AppLayout.css';

export interface TopNavProps {
  badges: ShellBadges;
  isAdmin: boolean;
  /** Shown at the right edge (e.g. the display name linking to me). */
  userName?: string | null;
  className?: string;
}

export function TopNav({ badges, isAdmin, userName, className }: TopNavProps) {
  const items = isAdmin ? [...PRIMARY_NAV, ADMIN_NAV] : PRIMARY_NAV;
  return (
    <header className={cx('topnav', className)}>
      <div className="topnav__inner">
        <Link to="/today" className="topnav__brand">
          {zh.app.name}
        </Link>
        <nav className="topnav__nav" aria-label={zh.app.name}>
          <ul className="topnav__list">
            {items.map((item) => (
              <li key={item.key}>
                <NavLink to={item.to} className={({ isActive }) => cx('topnav__link', isActive && 'is-active')}>
                  <span>{item.label}</span>
                  {navBadge(item.key, badges)}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        {userName ? (
          <Link to="/settings" className="topnav__user" title={zh.nav.me}>
            {userName}
          </Link>
        ) : null}
      </div>
    </header>
  );
}
