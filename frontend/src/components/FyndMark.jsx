import React from 'react';

/**
 * FyndWordmark — the F/ligature mark used across the shell.
 * Never emoji, never a stock icon. This is our identity.
 */
export function FyndMark({ size = 24, className = '' }) {
  const s = size;
  return (
    <span
      aria-hidden="true"
      className={`inline-flex items-center justify-center relative ${className}`}
      style={{ width: s, height: s }}
      data-testid="fynd-mark"
    >
      <svg viewBox="0 0 24 24" width={s} height={s} fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* Liquid capsule background — teal gradient with specular */}
        <defs>
          <linearGradient id="fyndMarkBg" x1="0" y1="0" x2="0" y2="24" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#17b0a0" />
            <stop offset="1" stopColor="#0d6b64" />
          </linearGradient>
          <linearGradient id="fyndMarkSpec" x1="0" y1="0" x2="0" y2="12" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#ffffff" stopOpacity="0.55" />
            <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <rect x="0" y="0" width="24" height="24" rx="7" fill="url(#fyndMarkBg)" />
        <rect x="0" y="0" width="24" height="12" rx="7" fill="url(#fyndMarkSpec)" />
        {/* Bold 'F' with a slight kern-up, feels sculpted */}
        <path
          d="M8 6.75h9v2.6h-6.15v3.05h5.15v2.55H10.85v3.85H8V6.75Z"
          fill="#ffffff"
        />
      </svg>
    </span>
  );
}

export function FyndWordmark({ className = '' }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`} data-testid="fynd-wordmark">
      <FyndMark size={22} />
      <span className="font-semibold text-[1.05rem] tracking-display-tight leading-none">Fynd</span>
    </span>
  );
}

export default FyndMark;
