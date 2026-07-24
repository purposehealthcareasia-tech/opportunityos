export const Colors = {
  accent: '#059669',
  accentLight: 'rgba(5, 150, 105, 0.1)',
  accentBorder: 'rgba(5, 150, 105, 0.4)',

  light: {
    bg: '#F8FAFC',
    surface: '#FFFFFF',
    surfaceMuted: '#F1F5F9',
    ink: '#1E293B',
    inkMuted: '#64748B',
    border: '#E2E8F0',
    borderLight: '#F1F5F9',
    card: '#FFFFFF',
    error: '#DC2626',
    errorBg: 'rgba(220, 38, 38, 0.05)',
    errorBorder: 'rgba(220, 38, 38, 0.3)',
    warning: '#D97706',
    warningBg: 'rgba(217, 119, 6, 0.05)',
    warningBorder: 'rgba(217, 119, 6, 0.4)',
  },
  dark: {
    bg: '#0F172A',
    surface: '#1E293B',
    surfaceMuted: '#0F172A',
    ink: '#F1F5F9',
    inkMuted: '#94A3B8',
    border: '#334155',
    borderLight: '#1E293B',
    card: '#1E293B',
    error: '#F87171',
    errorBg: 'rgba(248, 113, 113, 0.1)',
    errorBorder: 'rgba(248, 113, 113, 0.3)',
    warning: '#FBBF24',
    warningBg: 'rgba(251, 191, 36, 0.1)',
    warningBorder: 'rgba(251, 191, 36, 0.4)',
  },
};

export function useColors() {
  return Colors.light;
}
