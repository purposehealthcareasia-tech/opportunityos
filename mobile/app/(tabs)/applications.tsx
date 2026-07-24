import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, RefreshControl, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../../src/lib/theme';
import { api, withIdempotency } from '../../src/lib/api';
import { STATE_LABELS } from '../../src/lib/utils';
import { LoadingBlock, ErrorBlock, EmptyBlock } from '../../src/components/StatusBlocks';
import Button from '../../src/components/Button';

const STATE_ORDER = [
  'shortlisted', 'preparing', 'awaiting_approval', 'approved',
  'submitting', 'submitted', 'response', 'interview', 'offer', 'closed',
];

function StatePill({ state }: { state: string }) {
  const isAccent = ['approved', 'submitted', 'response', 'interview', 'offer'].includes(state);
  const isWarning = state === 'awaiting_approval';
  const color = isAccent ? Colors.accent : isWarning ? '#D97706' : Colors.light.inkMuted;
  return (
    <View style={[styles.statePill, { borderColor: color + '40' }]}>
      <Text style={{ fontSize: 11, color, fontWeight: '600' }}>{STATE_LABELS[state] || state}</Text>
    </View>
  );
}

function TimelineBar({ state }: { state: string }) {
  const idx = STATE_ORDER.indexOf(state);
  return (
    <View style={styles.timeline}>
      {STATE_ORDER.filter((s) => s !== 'closed').map((s, i) => (
        <View key={s} style={[styles.timelineSegment, { backgroundColor: i <= idx ? Colors.accent : '#E2E8F0' }]} />
      ))}
    </View>
  );
}

export default function ApplicationsScreen() {
  const router = useRouter();
  const [apps, setApps] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const c = Colors.light;

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/applications');
      setApps(data.applications || []);
      setError('');
    } catch {
      setError('Could not load your applications.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const transition = async (app: any, newState: string) => {
    setBusyId(app.id);
    try {
      await api.patch(`/api/v1/applications/${app.id}/state`, { expected_state: app.state, new_state: newState }, withIdempotency());
      await load();
    } catch { }
    finally { setBusyId(null); }
  };

  const real = useMemo(() => apps.filter((a) => !a.job_snapshot?.is_sample), [apps]);
  const openCount = real.filter((a) => a.state !== 'closed').length;

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock /></View>;

  return (
    <ScrollView
      testID="applications-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.accent} />}
    >
      <Text style={[styles.pageTitle, { color: c.ink }]}>Applications</Text>
      <Text style={[styles.pageSub, { color: c.inkMuted }]}>Your shortlisted jobs with state transitions.</Text>

      {error ? <ErrorBlock message={error} onRetry={load} /> : null}

      <View style={styles.statsRow}>
        <View style={[styles.statCard, { borderColor: c.border }]}>
          <Text style={{ fontSize: 11, color: c.inkMuted }}>Open</Text>
          <Text testID="applications-open-count" style={[styles.statNum, { color: c.ink }]}>{openCount}</Text>
        </View>
        <View style={[styles.statCard, { borderColor: c.border }]}>
          <Text style={{ fontSize: 11, color: c.inkMuted }}>Total</Text>
          <Text style={[styles.statNum, { color: c.ink }]}>{apps.length}</Text>
        </View>
      </View>

      {apps.length === 0 ? (
        <EmptyBlock title="No applications yet" hint="Shortlist a job from the Feed to start tracking." />
      ) : (
        apps.map((a: any) => (
          <TouchableOpacity
            key={a.id}
            testID={`application-row-${a.id}`}
            style={[styles.appCard, { backgroundColor: c.card, borderColor: c.border }]}
            onPress={() => router.push(`/jobs/${a.job_id}`)}
            activeOpacity={0.7}
          >
            <View style={styles.appTop}>
              <View style={{ flex: 1 }}>
                <View style={styles.titleRow}>
                  <Text style={[styles.appTitle, { color: c.ink }]} numberOfLines={1}>{a.job_snapshot?.title || 'Untitled'}</Text>
                  {a.job_snapshot?.is_sample && (
                    <View style={[styles.sampleBadge]}>
                      <Text style={{ fontSize: 9, color: '#D97706', fontWeight: '600' }}>SAMPLE</Text>
                    </View>
                  )}
                </View>
                <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 2 }}>{a.job_snapshot?.company_name} · {a.route}</Text>
              </View>
              <StatePill state={a.state} />
            </View>
            <TimelineBar state={a.state} />

            <View style={styles.transitionRow}>
              <TouchableOpacity
                testID={`application-prep-link-${a.id}`}
                onPress={() => router.push(`/prep/${a.id}`)}
                activeOpacity={0.7}
              >
                <Text style={{ fontSize: 12, color: Colors.accent, textDecorationLine: 'underline' }}>Open prep →</Text>
              </TouchableOpacity>
              {a.state !== 'closed' && (
                <View style={{ flexDirection: 'row', gap: 8 }}>
                  {a.state === 'shortlisted' && (
                    <Button size="sm" variant="secondary" onPress={() => transition(a, 'preparing')} loading={busyId === a.id} testID={`app-transition-${a.id}-preparing`}>
                      <Text style={{ fontSize: 12, color: c.ink }}>Start Preparing</Text>
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onPress={() => transition(a, 'closed')} loading={busyId === a.id}>
                    <Text style={{ fontSize: 12, color: c.inkMuted }}>Close</Text>
                  </Button>
                </View>
              )}
            </View>
          </TouchableOpacity>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSub: { fontSize: 13, marginTop: 4, marginBottom: 16 },
  statsRow: { flexDirection: 'row', gap: 8, marginBottom: 16 },
  statCard: { flex: 1, borderWidth: 1, borderRadius: 10, padding: 12, backgroundColor: '#FFF' },
  statNum: { fontSize: 22, fontWeight: '700', marginTop: 4 },
  appCard: { borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 10 },
  appTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  appTitle: { fontSize: 15, fontWeight: '600', flex: 1 },
  sampleBadge: { backgroundColor: '#FEF3C7', borderRadius: 4, paddingHorizontal: 6, paddingVertical: 1 },
  statePill: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 3 },
  timeline: { flexDirection: 'row', gap: 2, marginTop: 10 },
  timelineSegment: { flex: 1, height: 3, borderRadius: 2 },
  transitionRow: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8, marginTop: 10 },
});
