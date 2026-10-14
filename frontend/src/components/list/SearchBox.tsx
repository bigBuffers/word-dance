// SearchBox — debounced search input (250 ms by default; FRONTEND §4/§5.5). Enter flushes at once,
// the × button clears; the parent owns the committed value.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { CloseIcon, SearchIcon } from '@/components/ui/icons';
import { useDebouncedCallback } from '@/hooks/useDebounce';
import { zh } from '@/i18n/zh';
import './list.css';

export interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  delayMs?: number;
  autoFocus?: boolean;
  maxLength?: number;
  className?: string;
  'aria-label'?: string;
  id?: string;
}

export function SearchBox({ value, onChange, placeholder, delayMs = 250, autoFocus = false, maxLength = 64, className, 'aria-label': ariaLabel, id }: SearchBoxProps) {
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounced = useDebouncedCallback((next: string) => onChange(next), delayMs);

  // External resets (tab change, "clear" from the parent) win over a stale draft.
  useEffect(() => {
    setDraft(value);
  }, [value]);

  const update = (next: string) => {
    setDraft(next);
    debounced(next);
  };

  const clear = () => {
    debounced.cancel();
    setDraft('');
    onChange('');
    inputRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      debounced.flush();
    } else if (e.key === 'Escape' && draft) {
      e.preventDefault();
      clear();
    }
  };

  return (
    <div className={cx('searchbox', className)}>
      <span className="searchbox__icon" aria-hidden="true">
        <SearchIcon />
      </span>
      <input
        ref={inputRef}
        id={id}
        type="search"
        className="searchbox__input"
        value={draft}
        placeholder={placeholder}
        aria-label={ariaLabel ?? placeholder ?? zh.common.search}
        autoFocus={autoFocus}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        enterKeyHint="search"
        inputMode="search"
        maxLength={maxLength}
        onChange={(e) => update(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {draft && (
        <Button variant="ghost" iconOnly size="sm" className="searchbox__clear" aria-label={zh.common.close} onClick={clear}>
          <CloseIcon />
        </Button>
      )}
    </div>
  );
}
