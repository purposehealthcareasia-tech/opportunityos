import React from 'react';
import clsx from 'clsx';

export function Card({ className, children, ...rest }) {
  return (
    <div className={clsx('card p-6', className)} {...rest}>{children}</div>
  );
}
export function CardHeader({ title, subtitle, action }) {
  return (
    <div className="flex items-start justify-between gap-4 mb-4">
      <div className="min-w-0">
        <h3 className="text-base font-semibold text-ink dark:text-ink-dark">{title}</h3>
        {subtitle && <p className="text-sm muted mt-0.5">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
export default Card;
