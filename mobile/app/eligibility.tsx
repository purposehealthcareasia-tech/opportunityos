import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../src/lib/theme';
import { api, withIdempotency } from '../src/lib/api';
import Button from '../src/components/Button';
import { Card, CardHeader } from '../src/components/Card';
import { LoadingBlock, ErrorBlock } from '../src/components/StatusBlocks';

const STATUSES = [
  { k: 'citizen', label: 'US citizen' },
  { k: 'permanent_resident', label: 'Permanent resident' },
  { k: 'ead_opt', label: 'EAD (OPT)' },
  { k: 'stem_opt', label: 'STEM OPT' },
  { k: 'h1b', label: 'H-1B' },
  { k: 'tn', label: 'TN' },
  { k: 'other', label: 'Other' },
  { k: 'unspecified', label: 'Prefer not to say' },
];

export default function EligibilityScreen() {
  const [status, setStatus] = useState('unspecified');
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const c = Colors.light;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/api/v1/eligibility/me');
      setStatus(data.status || 'unspecified');
      setVersion(data.version || 0);
      setError('');
    } catch { setError('Could not load eligibility.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.post('/api/v1/eligibility', { status, dates: {} }, withIdempotency());
      setVersion(data.version);
    } catch { setError('Could not save.'); }
    finally { setSaving(false); }
  };

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock /></View>;

  return (
    <ScrollView
      testID="eligibility-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
    >
      <Text style={[styles.pageTitle, { color: c.ink }]}>Eligibility</Text>
      <Text style={[styles.pageSub, { color: c.inkMuted }]}>Work-authorization status. This is sealed — only you see real values. Version {version}.</Text>

      <View style={[styles.infoBox, { borderColor: Colors.accentBorder, backgroundColor: Colors.accentLight }]}>
        <Ionicons name="information-circle-outline" size={16} color={Colors.accent} />
        <Text style={{ fontSize: 13, color: c.ink, flex: 1 }}>This is not legal advice. Gates are heuristics.</Text>
      </View>

      {error ? <ErrorBlock message={error} onRetry={load} /> : null}

      <Card>
        <CardHeader title="Work-authorization status" />
        <View style={styles.statusGrid}>
          {STATUSES.map((s) => (
            <TouchableOpacity
              key={s.k}
              testID={`eligibility-status-${s.k}`}
              style={[styles.statusBtn, { borderColor: status === s.k ? Colors.accent : c.border, backgroundColor: status === s.k ? Colors.accentLight : 'transparent' }]}
              onPress={() => setStatus(s.k)}
            >
              <Text style={{ fontSize: 14, fontWeight: '500', color: status === s.k ? Colors.accent : c.ink }}>{s.label}</Text>
              <Text style={{ fontSize: 11, color: c.inkMuted, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' }}>{s.k}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </Card>

      <Button onPress={save} loading={saving} testID="eligibility-save-btn" style={{ marginTop: 8 }}>
        <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 15 }}>Save & preview coverage</Text>
      </Button>
    </ScrollView>
  );
}

import { Platform } from 'react-native';

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSub: { fontSize: 13, marginTop: 4, marginBottom: 16, lineHeight: 18 },
  infoBox: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 16 },
  statusGrid: { gap: 8 },
  statusBtn: { borderWidth: 1, borderRadius: 10, padding: 14 },
});
