// P0 stub — replaced by WP7. Route `/welcome` (user, onboarding_state != 'done'): two-step onboarding (FRONTEND §2).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function WelcomePage() {
  usePageTitle(zh.welcome.title);
  return (
    <section className="page page--narrow">
      <h1 className="page__title">{zh.welcome.title}</h1>
      <p className="muted">{zh.welcome.step1}</p>
    </section>
  );
}
