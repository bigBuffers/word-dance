// P0 STUB — WP7 owns components/layout/* and replaces this file with the responsive shell
// (TopNav ≥ 768 px, TabBar < 768 px, badges from `counters`; FRONTEND §2/§4). routes.tsx (frozen)
// mounts <AppLayout/> as the layout route around every authenticated page, so only this file changes.
// Keep the inner <Suspense>: a lazily loaded page must never blank the shell.
import { Suspense } from 'react';
import { NavLink, Outlet } from 'react-router';
import { useAuth } from '@/auth/AuthContext';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import './AppLayout.css';

const NAV: { to: string; label: string }[] = [
  { to: '/today', label: zh.nav.today },
  { to: '/vocab', label: zh.nav.vocab },
  { to: '/bank', label: zh.nav.bank },
  { to: '/history', label: zh.nav.history },
  { to: '/settings', label: zh.nav.me },
];

export function AppLayout() {
  const { user } = useAuth();
  const items = user?.role === 'admin' ? [...NAV, { to: '/admin', label: zh.nav.admin }] : NAV;
  return (
    <div className="app-shell">
      <nav className="app-nav" aria-label={zh.app.name}>
        <span className="app-nav__brand">{zh.app.name}</span>
        <ul className="app-nav__list">
          {items.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} className={({ isActive }) => cx('app-nav__link', isActive && 'is-active')}>
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="app-main">
        <Suspense
          fallback={
            <div className="loading-screen" role="status" aria-busy="true">
              {zh.common.loading}
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
