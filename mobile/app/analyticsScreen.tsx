import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../src/lib/theme';
import { api } from '../src/lib/api';
import { LoadingBlock, ErrorBlock } from '../src/components/StatusBlocks';

const FUNNEL_STAGES = ['prepared', 'submitted', 'response', 'interview', 'offer'];

export default function AnalyticsScreen() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const c = Colors.light;

  const load = useCallback(async () => {
    try {
      const { data: res } = await api.get('/api/v1/analytics/funnel');
      setData(res);
      setError('');
    } catch (e: any) {
      setError(e?.response?.data?.detail?.error || 'Failed to load analytics.');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock /></View>;
  if (error) return <View style={[styles.container, { backgroundColor: c.bg, padding: 20 }]}><ErrorBlock message={error} onRetry={load} /></View>;
  if (!data) return null;

  const conv = data.conversion || {};

  return (
    <ScrollView
      testID="analytics-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
    >
      <Text style={[styles.pageTitle, { color: c.ink }]}>Analytics</Text>
      <Text style={[styles.pageSub, { color: c.inkMuted }]}>Your personal funnel from REAL applications only.</Text>

      {data.empty && (
        <View testID="analytics-empty" style={[styles.emptyBox, { borderColor: c.border }]}>
          <Text style={{ fontSize: 14, color: c.inkMuted }}>{data.sample_note || 'No applications yet.'}</Text>
        </View>
      )}

      {!data.empty && (
        <>
          <Text style={[styles.sectionTitle, { color: c.ink }]}>Personal funnel</Text>
          <View style={styles.funnelRow}>
            {FUNNEL_STAGES.map((stage) => (
              <View key={stage} testID={`funnel-stage-${stage}`} style={[styles.funnelCard, { borderColor: c.border }]}>
                <Text style={{ fontSize: 10, color: c.inkMuted, textTransform: 'uppercase' }}>{stage}</Text>
                <Text style={[styles.funnelNum, { color: c.ink }]}>{data.totals[stage]}</Text>
              </View>
            ))}
          </View>

          <Text style={[styles.sectionTitle, { color: c.ink, marginTop: 20 }]}>Conversion</Text>
          <View style={styles.convGrid}>
            {[
              ['Prep→Sub', conv.prepared_to_submitted],
              ['Sub→Res', conv.submitted_to_response],
              ['Res→Int', conv.response_to_interview],
              ['Int→Offer', conv.interview_to_offer],
            ].map(([label, pct]: any) => (
              <View key={label} style={[styles.convCard, { borderColor: c.border }]}>
                <Text style={{ fontSize: 10, color: c.inkMuted }}>{label}</Text>
                <Text style={[styles.convNum, { color: c.ink }]}>
                  {pct == null ? '—' : `${pct}%`}
                </Text>
              </View>
            ))}
          </View>
        </>
      )}

      <View testID="analytics-qi" style={{ marginTop: 20 }}>
        <View style={styles.qiRow}>
          <Ionicons name="trophy-outline" size={18} color={Colors.accent} />
          <Text style={[styles.sectionTitle, { color: c.ink, marginBottom: 0 }]}>Qualified interviews</Text>
        </View>
        <View style={[styles.qiCard, { borderColor: c.border }]}>
          <Text style={{ fontSize: 28, fontWeight: '700', color: c.ink }}>{data.qi_total}</Text>
          <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 4 }}>Interviews you flagged as qualified.</Text>
        </View>
      </View>

      {data.sample_note && (
        <View testID="analytics-sample-note" style={{ marginTop: 16 }}>
          <Text style={{ fontSize: 12, color: c.inkMuted, fontStyle: 'italic' }}>{data.sample_note}</Text>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSub: { fontSize: 13, marginTop: 4, marginBottom: 16 },
  sectionTitle: { fontSize: 16, fontWeight: '600', marginBottom: 10 },
  funnelRow: { flexDirection: 'row', gap: 6 },
  funnelCard: { flex: 1, borderWidth: 1, borderRadius: 8, padding: 10, backgroundColor: '#FFF' },
  funnelNum: { fontSize: 20, fontWeight: '700', marginTop: 4 },
  convGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  convCard: { width: '48%', borderWidth: 1, borderRadius: 8, padding: 10, backgroundColor: '#FFF' },
  convNum: { fontSize: 18, fontWeight: '700', marginTop: 4 },
  qiRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 },
  qiCard: { borderWidth: 1, borderRadius: 10, padding: 16, backgroundColor: '#FFF' },
  emptyBox: { borderWidth: 1, borderRadius: 10, padding: 24 },
});
