import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, Linking } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../../src/lib/theme';
import { api } from '../../src/lib/api';
import { REASON_LABELS } from '../../src/lib/utils';
import { LoadingBlock, ErrorBlock } from '../../src/components/StatusBlocks';
import AuthGate from '../../src/components/AuthGate';

export default function JobDetailScreen() {
  return <AuthGate><JobDetailContent /></AuthGate>;
}

function JobDetailContent() {
  const { jobId } = useLocalSearchParams<{ jobId: string }>();
  const [job, setJob] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const c = Colors.light;

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/api/v1/jobs/${jobId}`);
      setJob(data);
      setError('');
    } catch {
      setError('Could not load job details.');
    } finally { setLoading(false); }
  }, [jobId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock /></View>;
  if (error) return <View style={[styles.container, { backgroundColor: c.bg, padding: 20 }]}><ErrorBlock message={error} onRetry={load} /></View>;
  if (!job) return null;

  const gates = job.gates || [];

  return (
    <ScrollView
      testID="job-detail-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
    >
      <Text style={[styles.title, { color: c.ink }]}>{job.title}</Text>
      <View style={styles.metaRow}>
        <Ionicons name="business-outline" size={14} color={c.inkMuted} />
        <Text style={{ fontSize: 14, color: c.inkMuted }}>{job.company_name}</Text>
      </View>
      {job.geo && (
        <View style={styles.metaRow}>
          <Ionicons name="location-outline" size={14} color={c.inkMuted} />
          <Text style={{ fontSize: 14, color: c.inkMuted }}>{job.geo}</Text>
        </View>
      )}
      {job.comp && (
        <View style={styles.metaRow}>
          <Ionicons name="cash-outline" size={14} color={c.inkMuted} />
          <Text style={{ fontSize: 14, color: c.inkMuted }}>{job.comp}</Text>
        </View>
      )}

      {job.score != null && (
        <View style={[styles.scoreCard, { backgroundColor: Colors.accentLight, borderColor: Colors.accentBorder }]}>
          <Text style={{ fontSize: 28, fontWeight: '700', color: Colors.accent }}>{Math.round(job.score)}</Text>
          <Text style={{ fontSize: 12, color: Colors.accent }}>/100 match score</Text>
        </View>
      )}

      {job.route && (
        <View style={[styles.infoCard, { borderColor: c.border }]}>
          <Text style={{ fontSize: 13, fontWeight: '600', color: c.ink }}>Route: {job.route.route?.replace(/_/g, ' ')}</Text>
          {job.route.rationale && <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 4 }}>{job.route.rationale}</Text>}
        </View>
      )}

      {gates.length > 0 && (
        <View style={{ marginTop: 16 }}>
          <Text style={[styles.sectionTitle, { color: c.ink }]}>Gate verdicts ({gates.length})</Text>
          {gates.map((g: any) => (
            <View key={g.gate} style={[styles.gateRow, { borderColor: c.border }]}>
              <Ionicons
                name={g.pass ? 'checkmark-circle' : 'close-circle'}
                size={16}
                color={g.pass ? Colors.accent : c.error}
              />
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 13, fontWeight: '500', color: c.ink }}>{g.gate.replace(/_/g, ' ')}</Text>
                {g.reason && <Text style={{ fontSize: 11, color: c.inkMuted }}>{REASON_LABELS[g.reason] || g.reason}</Text>}
              </View>
              <Text style={{ fontSize: 11, color: g.pass ? Colors.accent : c.error, fontWeight: '600' }}>{g.pass ? 'PASS' : 'FAIL'}</Text>
            </View>
          ))}
        </View>
      )}

      {job.description && (
        <View style={{ marginTop: 16 }}>
          <Text style={[styles.sectionTitle, { color: c.ink }]}>Description</Text>
          <Text style={{ fontSize: 14, color: c.ink, lineHeight: 22 }}>{job.description}</Text>
        </View>
      )}

      {job.origin_url && (
        <View style={{ marginTop: 16 }}>
          <Text style={{ fontSize: 12, color: Colors.accent, textDecorationLine: 'underline' }} onPress={() => Linking.openURL(job.origin_url)}>
            View original posting
          </Text>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  title: { fontSize: 22, fontWeight: '700', lineHeight: 28 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6 },
  scoreCard: { borderWidth: 1, borderRadius: 12, padding: 16, marginTop: 16, flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  infoCard: { borderWidth: 1, borderRadius: 10, padding: 12, marginTop: 12 },
  sectionTitle: { fontSize: 16, fontWeight: '600', marginBottom: 10 },
  gateRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderBottomWidth: 1, paddingVertical: 10 },
});
