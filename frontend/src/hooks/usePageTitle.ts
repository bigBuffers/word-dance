// usePageTitle — sets `document.title` to `<title> · word-Dance` (FRONTEND §2 page titles).
import { useEffect } from 'react';
import { zh } from '@/i18n/zh';

export function usePageTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} · ${zh.app.name}` : zh.app.name;
  }, [title]);
}
