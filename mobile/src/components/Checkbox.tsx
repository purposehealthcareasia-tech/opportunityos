import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Colors } from '../lib/theme';

interface CheckboxProps {
  checked: boolean;
  onChange: (val: boolean) => void;
  label: string;
  description?: string;
  required?: boolean;
}

export default function Checkbox({ checked, onChange, label, description, required }: CheckboxProps) {
  const c = Colors.light;
  return (
    <TouchableOpacity
      style={styles.row}
      onPress={() => onChange(!checked)}
      activeOpacity={0.7}
    >
      <View style={[styles.box, { borderColor: checked ? Colors.accent : c.border, backgroundColor: checked ? Colors.accent : 'transparent' }]}>
        {checked && <Text style={styles.check}>✓</Text>}
      </View>
      <View style={styles.textCol}>
        <View style={styles.labelRow}>
          <Text style={[styles.label, { color: c.ink }]}>{label}</Text>
          {required && (
            <View style={[styles.pill, { borderColor: c.border }]}>
              <Text style={{ fontSize: 10, color: c.inkMuted }}>required</Text>
            </View>
          )}
        </View>
        {description && <Text style={[styles.desc, { color: c.inkMuted }]}>{description}</Text>}
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingVertical: 8 },
  box: {
    width: 22,
    height: 22,
    borderRadius: 4,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  check: { color: '#FFF', fontSize: 14, fontWeight: '700' },
  textCol: { flex: 1 },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  label: { fontSize: 14, fontWeight: '500' },
  pill: { borderWidth: 1, borderRadius: 4, paddingHorizontal: 6, paddingVertical: 1 },
  desc: { fontSize: 12, marginTop: 2, lineHeight: 17 },
});
