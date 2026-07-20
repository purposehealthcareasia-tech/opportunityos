import React from 'react';
import clsx from 'clsx';

export function Input({ label, hint, error, className, id, ...rest }) {
  const inputId = id || rest.name || Math.random().toString(36).slice(2, 10);
  return (
    <div className="space-y-1">
      {label && (
        <label htmlFor={inputId} className="field-label">
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={clsx('field-input', error && 'border-red-500 focus:border-red-500 focus:ring-red-500/20', className)}
        {...rest}
      />
      {error ? (
        <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
      ) : hint ? (
        <p className="text-xs muted">{hint}</p>
      ) : null}
    </div>
  );
}

export default Input;
