import React from 'react';
export function Spinner({ size = 16, className = '' }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block rounded-full border-2 border-current border-r-transparent animate-spin ${className}`}
      style={{ width: size, height: size }}
    />
  );
}
export default Spinner;
