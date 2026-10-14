// TabBar — phone (< 768 px) bottom navigation: today · vocab · bank · history · me (FRONTEND §2/§4).
// Badge dot on today while ungraded items exist, number badge on bank = counters.suggestions_open +
// counters.attention (computed by AppLayout from GET /api/auth/me — no extra poll).
import type { ReactNode, SVGProps } from 'react';
import { NavLink } from 'react-router';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import { formatBadge } from '@/utils/format';
import './AppLayout.css';

export interface ShellBadges {
  /** Ungraded items exist in today's (or yesterday's open) batch → dot on today. */
  today: boolean;
  /** `counters.suggestions_open + counters.attention` → number on bank. */
  bank: number;
}

export type NavKey = 'today' | 'vocab' | 'bank' | 'history' | 'me' | 'admin';

export interface NavEntry {
  key: NavKey;
  to: string;
  label: string;
}

/** The five primary destinations shared by TabBar and TopNav (FRONTEND §2). */
export const PRIMARY_NAV: readonly NavEntry[] = [
  { key: 'today', to: '/today', label: zh.nav.today },
  { key: 'vocab', to: '/vocab', label: zh.nav.vocab },
  { key: 'bank', to: '/bank', label: zh.nav.bank },
  { key: 'history', to: '/history', label: zh.nav.history },
  { key: 'me', to: '/settings', label: zh.nav.me },
];

export const ADMIN_NAV: NavEntry = { key: 'admin', to: '/admin', label: zh.nav.admin };

const iconBase: SVGProps<SVGSVGElement> = {
  viewBox: '0 0 24 24',
  width: 24,
  height: 24,
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
};

function TodayIcon() {
  return (
    <svg {...iconBase}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" />
    </svg>
  );
}

function VocabIcon() {
  return (
    <svg {...iconBase}>
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z" />
      <path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" />
      <path d="M8.5 7.5h7M8.5 11h5" />
    </svg>
  );
}

function BankIcon() {
  return (
    <svg {...iconBase}>
      <path d="M6.5 3.5h11v17l-5.5-3.6-5.5 3.6z" />
    </svg>
  );
}

function HistoryIcon() {
  return (
    <svg {...iconBase}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

function MeIcon() {
  return (
    <svg {...iconBase}>
      <circle cx="12" cy="8.5" r="3.8" />
      <path d="M4.5 20.5a7.5 7.5 0 0 1 15 0" />
    </svg>
  );
}

function AdminIcon() {
  return (
    <svg {...iconBase}>
      <path d="M12 3l7.5 3v5.5c0 4.5-3.2 8.1-7.5 9.5-4.3-1.4-7.5-5-7.5-9.5V6z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

export const NAV_ICONS: Record<NavKey, () => ReactNode> = {
  today: TodayIcon,
  vocab: VocabIcon,
  bank: BankIcon,
  history: HistoryIcon,
  me: MeIcon,
  admin: AdminIcon,
};

export function navBadge(key: NavKey, badges: ShellBadges): ReactNode {
  if (key === 'today' && badges.today) {
    return (
      <>
        <span className="tabbar__dot" aria-hidden="true" />
        <span className="visually-hidden">{zh.today.resume}</span>
      </>
    );
  }
  if (key === 'bank' && badges.bank > 0) return <span className="tabbar__badge">{formatBadge(badges.bank)}</span>;
  return null;
}

export interface TabBarProps {
  badges: ShellBadges;
  className?: string;
}

export function TabBar({ badges, className }: TabBarProps) {
  return (
    <nav className={cx('tabbar', className)} aria-label={zh.app.name}>
      <ul className="tabbar__list">
        {PRIMARY_NAV.map((item) => {
          const Icon = NAV_ICONS[item.key];
          return (
            <li key={item.key} className="tabbar__item">
              <NavLink to={item.to} className={({ isActive }) => cx('tabbar__link', isActive && 'is-active')}>
                <span className="tabbar__icon">
                  <Icon />
                  {navBadge(item.key, badges)}
                </span>
                <span className="tabbar__label">{item.label}</span>
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
