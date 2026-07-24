import React from 'react';
import { View, Text, TextInput, StyleSheet, TextInputProps } from 'react-native';
import { Colors } from '../lib/theme';

interface InputProps extends TextInputProps {
  label?: string;
  hint?: string;
  error?: string;
}

export default function Input({ label, hint, error, style, ...props }: InputProps) {
  const c = Colors.light;
  return (
    <View style={styles.container}>
      {label && <Text style={[styles.label, { color: c.ink }]}>{label}</Text>}
      <TextInput
        style={[
          styles.input,
          {
            color: c.ink,
            backgroundColor: c.surface,
            borderColor: error ? Colors.light.error : c.border,
          },
          props.editable === false && styles.disabled,
          style,
        ]}
        placeholderTextColor={c.inkMuted}
        {...props}
      />
      {hint && !error && <Text style={[styles.hint, { color: c.inkMuted }]}>{hint}</Text>}
      {error && <Text style={[styles.hint, { color: c.error }]}>{error}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { marginBottom: 4 },
  label: { fontSize: 13, fontWeight: '500', marginBottom: 6 },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  hint: { fontSize: 12, marginTop: 4 },
  disabled: { opacity: 0.6 },
});
