import React from 'react';
import { TouchableOpacity, Text, ActivityIndicator, StyleSheet, ViewStyle, TextStyle } from 'react-native';
import { Colors } from '../lib/theme';

interface ButtonProps {
  onPress?: () => void;
  title?: string;
  children?: React.ReactNode;
  variant?: 'accent' | 'secondary' | 'ghost';
  size?: 'sm' | 'md';
  loading?: boolean;
  disabled?: boolean;
  testID?: string;
  style?: ViewStyle;
}

export default function Button({ onPress, title, children, variant = 'accent', size = 'md', loading, disabled, testID, style }: ButtonProps) {
  const c = Colors.light;
  const isDisabled = disabled || loading;

  const baseStyle: ViewStyle = {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    borderRadius: 8,
    paddingHorizontal: size === 'sm' ? 12 : 16,
    paddingVertical: size === 'sm' ? 6 : 10,
    opacity: isDisabled ? 0.5 : 1,
  };

  const variantStyles: Record<string, ViewStyle> = {
    accent: { backgroundColor: Colors.accent },
    secondary: { backgroundColor: 'transparent', borderWidth: 1, borderColor: c.border },
    ghost: { backgroundColor: 'transparent' },
  };

  const textStyles: Record<string, TextStyle> = {
    accent: { color: '#FFFFFF', fontWeight: '600', fontSize: size === 'sm' ? 13 : 14 },
    secondary: { color: c.ink, fontWeight: '500', fontSize: size === 'sm' ? 13 : 14 },
    ghost: { color: c.inkMuted, fontWeight: '500', fontSize: size === 'sm' ? 13 : 14 },
  };

  return (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.7}
      style={[baseStyle, variantStyles[variant], style]}
    >
      {loading && <ActivityIndicator size="small" color={variant === 'accent' ? '#FFF' : Colors.accent} />}
      {children ? (
        typeof children === 'string' ? <Text style={textStyles[variant]}>{children}</Text> : children
      ) : title ? (
        <Text style={textStyles[variant]}>{title}</Text>
      ) : null}
    </TouchableOpacity>
  );
}
