// SpeakButton — speaker icon button wrapping useSpeech() (FRONTEND §4); disabled with the zh.word.speechUnsupported tooltip when
// nothing can pronounce here — no speechSynthesis, not the native shell, and no server clips (`ServerFlags.audio` false) — unless an
// `onClick` (the word dance replay, §6.5) is passed: then the button stays usable with the zh.word.replayDance label and only skips
// the speech. Defaults to the user's accent setting.
import type { MouseEvent } from 'react';
import { useOptionalAuth } from '@/auth/AuthContext';
import { Button, type ButtonSize } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { SpeakerIcon } from '@/components/ui/icons';
import { useSpeech, type Accent } from '@/hooks/useSpeech';
import { zh } from '@/i18n/zh';
import './word.css';

export interface SpeakButtonProps {
  text: string;
  /** Overrides the accent from settings (`en-US` when neither is available). */
  lang?: Accent;
  size?: ButtonSize;
  className?: string;
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
}

export function SpeakButton({ text, lang, size = 'md', className, onClick }: SpeakButtonProps) {
  const auth = useOptionalAuth();
  const accent: Accent = lang ?? auth?.settings?.accent ?? 'en-US';
  const { supported, speaking, speak } = useSpeech(accent);
  const canAct = supported || onClick !== undefined;
  const label = supported ? zh.word.speak : onClick ? zh.word.replayDance : zh.word.speechUnsupported;

  return (
    <Button
      variant="ghost"
      iconOnly
      size={size}
      className={cx('speak', speaking && 'is-speaking', className)}
      aria-label={label}
      title={label}
      disabled={!canAct}
      onClick={(e) => {
        e.stopPropagation(); // a card tap reveals the back; pronouncing must not
        onClick?.(e);
        if (supported) speak(text, accent);
      }}
    >
      <SpeakerIcon />
    </Button>
  );
}
