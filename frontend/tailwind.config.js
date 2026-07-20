/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/**/*.{js,jsx,ts,tsx}',
    './public/index.html',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica',
          'Arial',
          'sans-serif',
        ],
      },
      colors: {
        surface: {
          DEFAULT: '#ffffff',
          muted: '#f8fafc',
          dark: '#0b0d10',
          'dark-muted': '#111417',
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
          DEFAULT: '#0f766e', // teal-700, calm and trustworthy
          hover: '#0d6b64',
          soft: '#ccfbf1',
          'soft-dark': '#134e4a',
        },
      },
      boxShadow: {
        subtle: '0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)',
      },
      borderRadius: {
        card: '14px',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: 0, transform: 'translateY(4px)' },
          '100%': { opacity: 1, transform: 'translateY(0)' },
        },
      },
      animation: {
        fadeIn: 'fadeIn 240ms ease-out both',
      },
    },
  },
  plugins: [],
};
