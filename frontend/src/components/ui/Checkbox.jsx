import React from 'react';
import clsx from 'clsx';
import { Check } from 'lucide-react';

export function Checkbox({ id, checked, onChange, disabled, label, description, required, className }) {
  const cbId = id || 'cb-' + Math.random().toString(36).slice(2, 10);
  return (
    <label htmlFor={cbId} className={clsx('flex items-start gap-3 cursor-pointer select-none group', disabled && 'opacity-60 cursor-not-allowed', className)}>
      <span className="relative mt-0.5 flex-shrink-0">
        <input
          id={cbId}
          type="checkbox"
          checked={!!checked}
          onChange={(e) => onChange?.(e.target.checked)}
          disabled={disabled}
          className="peer sr-only"
        />
        <span
          aria-hidden
          className={clsx(
            'inline-flex h-5 w-5 items-center justify-center rounded-md border transition-colors',
            'border-line dark:border-line-dark bg-white dark:bg-neutral-900',
            'peer-focus-visible:ring-2 peer-focus-visible:ring-accent/30',
            'peer-checked:bg-accent peer-checked:border-accent',
          )}
        >
          {checked && <Check className="h-3.5 w-3.5 text-white" strokeWidth={3} />}
        </span>
      </span>
      <span className="min-w-0">
        {label && (
          <span className="block text-sm font-medium text-ink dark:text-ink-dark">
            {label}
            {required && <span className="ml-1 text-accent" title="Required">*</span>}
          </span>
        )}
        {description && <span className="block text-xs muted mt-0.5 leading-relaxed">{description}</span>}
      </span>
    </label>
  );
}

export default Checkbox;
