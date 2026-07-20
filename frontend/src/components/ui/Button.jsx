import React from 'react';
import clsx from 'clsx';

export function Button({ variant = 'primary', size = 'md', className, disabled, loading, children, ...rest }) {
  const variants = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    ghost: 'btn-ghost',
    accent: 'btn-accent',
    danger:
      'bg-red-600 text-white hover:bg-red-700 dark:bg-red-500 dark:hover:bg-red-600 focus-visible:ring-red-500/30',
  };
  const sizes = { sm: 'px-3 py-1.5 text-xs', md: '', lg: 'px-5 py-2.5 text-base' };
  return (
    <button
      className={clsx('btn', variants[variant], sizes[size], className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && (
        <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-current border-r-transparent animate-spin" aria-hidden />
      )}
      {children}
    </button>
  );
}

export default Button;
