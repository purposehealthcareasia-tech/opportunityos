/** @type {import('tailwindcss').Config}
 *  FYND LIQUID — token layer. Never write ad-hoc glass in components;
 *  compose via the utility classes defined here and in fynd-liquid.css.
 */
module.exports = {
  content: [
    './src/**/*.{js,jsx,ts,tsx}',
    './public/index.html',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        // Apple-first system stack (per directive §2). Falls back gracefully.
        sans: [
          '-apple-system', 'BlinkMacSystemFont', 'SF Pro Text', 'SF Pro Display',
          'Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto',
          'Helvetica', 'Arial', 'sans-serif',
        ],
      },
      // 3-level display hierarchy per directive §2. Tracking gets tighter
      // as size grows — feels Apple-native without being loud.
      letterSpacing: {
        'display': '-0.03em',
        'display-tight': '-0.045em',
      },
      colors: {
        surface: {
          DEFAULT: '#ffffff',
          muted: '#f6f7f9',
          dark: '#0B0D10',            // Fynd Liquid dark-first base
          'dark-muted': '#0F1216',
          'dark-elev': '#131820',
        },
        ink: {
          DEFAULT: '#0b0d10',
          muted: '#4b5563',
          dark: '#e5e7eb',
          'dark-muted': '#9ca3af',
        },
        line: {
          DEFAULT: '#e5e7eb',
          dark: '#1f2328',
        },
        accent: {
          DEFAULT: '#0f766e',          // calm teal
          hover: '#0d6b64',
          soft: '#ccfbf1',
          'soft-dark': '#134e4a',
        },
      },
      boxShadow: {
        subtle: '0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)',
        // Fynd Liquid depth shadows — soft, low-opacity, layered
        'liquid-1': '0 1px 0 rgba(255,255,255,0.06) inset, 0 6px 20px -8px rgba(0,0,0,0.35), 0 2px 6px -2px rgba(0,0,0,0.25)',
        'liquid-2': '0 1px 0 rgba(255,255,255,0.08) inset, 0 12px 40px -12px rgba(0,0,0,0.5), 0 4px 12px -4px rgba(0,0,0,0.3)',
        'liquid-3': '0 1px 0 rgba(255,255,255,0.12) inset, 0 24px 60px -20px rgba(0,0,0,0.6), 0 8px 24px -8px rgba(0,0,0,0.35)',
        'liquid-1-light': '0 1px 0 rgba(255,255,255,0.9) inset, 0 6px 20px -8px rgba(15,23,42,0.10), 0 2px 6px -2px rgba(15,23,42,0.05)',
        'liquid-2-light': '0 1px 0 rgba(255,255,255,1) inset, 0 12px 40px -12px rgba(15,23,42,0.14), 0 4px 12px -4px rgba(15,23,42,0.08)',
      },
      borderRadius: {
        // Concentric geometry per directive §2 — outer 24-28px, capsule.
        card: '20px',
        'liquid-lg': '28px',
        'liquid-md': '20px',
        'liquid-sm': '14px',
      },
      backdropBlur: {
        // 3 elevations per directive §2
        'liquid-1': '12px',
        'liquid-2': '20px',
        'liquid-3': '28px',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: 0, transform: 'translateY(4px)' },
          '100%': { opacity: 1, transform: 'translateY(0)' },
        },
        // Liquid morph — spring-ease, transform/opacity only, 60fps friendly
        liquidIn: {
          '0%':   { opacity: 0, transform: 'translateY(6px) scale(0.985)' },
          '60%':  { opacity: 1, transform: 'translateY(-1px) scale(1.005)' },
          '100%': { opacity: 1, transform: 'translateY(0) scale(1)' },
        },
        liquidRipple: {
          '0%':   { opacity: 0.55, transform: 'scale(0.4)' },
          '80%':  { opacity: 0.05, transform: 'scale(1.6)' },
          '100%': { opacity: 0, transform: 'scale(1.8)' },
        },
        surpriseCondense: {
          '0%':   { opacity: 0, transform: 'translateY(24px) scale(0.9) blur(6px)', filter: 'blur(6px)' },
          '60%':  { opacity: 1, transform: 'translateY(-2px) scale(1.01)', filter: 'blur(0)' },
          '100%': { opacity: 1, transform: 'translateY(0) scale(1)', filter: 'blur(0)' },
        },
      },
      animation: {
        fadeIn: 'fadeIn 240ms ease-out both',
        liquidIn: 'liquidIn 260ms cubic-bezier(0.34, 1.28, 0.64, 1) both',
        liquidRipple: 'liquidRipple 520ms ease-out forwards',
        surpriseCondense: 'surpriseCondense 380ms cubic-bezier(0.22, 1.2, 0.36, 1) both',
      },
      transitionTimingFunction: {
        'liquid-spring': 'cubic-bezier(0.34, 1.28, 0.64, 1)',
        'liquid-ease': 'cubic-bezier(0.22, 1.2, 0.36, 1)',
      },
    },
  },
  plugins: [],
};
