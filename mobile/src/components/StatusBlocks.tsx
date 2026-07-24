import React from 'react';
import { View, Text, ActivityIndicator, TouchableOpacity, StyleSheet } from 'react-native';
import { Colors } from '../lib/theme';

export function LoadingBlock({ label = 'Loading...' }: { label?: string }) {
  return (
    <View style={styles.center}>
      <ActivityIndicator color={Colors.accent} />
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const c = Colors.light;
  return (
    <View style={[styles.errorBox, { borderColor: c.errorBorder, backgroundColor: c.errorBg }]}>
      <Text style={{ color: c.error, fontSize: 14, flex: 1 }}>{message}</Text>
      {onRetry && (
        <TouchableOpacity onPress={onRetry}>
          <Text style={{ color: c.error, fontSize: 12, textDecorationLine: 'underline' }}>Retry</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

export function EmptyBlock({ title, hint }: { title: string; hint?: string }) {
  const c = Colors.light;
  return (
    <View style={[styles.emptyBox, { borderColor: c.border }]}>
      <Text style={{ fontSize: 14, fontWeight: '600', color: c.ink, textAlign: 'center' }}>{title}</Text>
      {hint && <Text style={{ fontSize: 13, color: c.inkMuted, marginTop: 4, textAlign: 'center' }}>{hint}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 24,
  },
  muted: { color: Colors.light.inkMuted, fontSize: 14 },
  errorBox: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  emptyBox: {
    borderWidth: 1,
    borderStyle: 'dashed',
    borderRadius: 12,
    padding: 32,
    alignItems: 'center',
  },
});
