import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, RefreshControl, StyleSheet, Alert } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../../src/lib/theme';
import { api, withIdempotency } from '../../src/lib/api';
import { REASON_LABELS } from '../../src/lib/utils';
import { LoadingBlock, ErrorBlock, EmptyBlock } from '../../src/components/StatusBlocks';

function ScoreBadge({ score, confidence }: { score: number | null; confidence?: number }) {
  if (score == null) return null;
  const pct = Math.max(0, Math.min(100, Math.round(score)));
  const conf = Math.round((confidence || 0) * 100);
  const bg = pct >= 70 ? Colors.accentLight : '#F1F5F9';
  const textColor = pct >= 70 ? Colors.accent : Colors.light.ink;
  return (
    <View style={[styles.scoreBadge, { backgroundColor: bg }]}>
      <Text style={{ fontSize: 18, fontWeight: '700', color: textColor }}>{pct}</Text>
      <Text style={{ fontSize: 10, color: Colors.light.inkMuted }}>/100 c{conf}</Text>
    </View>
  );
}

function JobCard({ job, onShortlist, onPress, busy }: any) {
  const c = Colors.light;
  return (
    <TouchableOpacity
      testID={`job-card-${job.id}`}
      style={[styles.jobCard, { backgroundColor: c.card, borderColor: c.border }]}
      onPress={() => onPress(job)}
      activeOpacity={0.7}
    >
      <View style={styles.jobTop}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.jobTitle, { color: c.ink }]} numberOfLines={2}>{job.title}</Text>
          <View style={styles.jobMeta}>
            <Ionicons name="business-outline" size={12} color={c.inkMuted} />
            <Text style={{ fontSize: 13, color: c.inkMuted }}>{job.company_name}</Text>
            {job.geo && (
              <>
                <Ionicons name="location-outline" size={12} color={c.inkMuted} />
                <Text style={{ fontSize: 13, color: c.inkMuted }}>{job.geo}</Text>
              </>
            )}
          </View>
        </View>
        <ScoreBadge score={job.score} confidence={job.confidence} />
      </View>

      <View style={styles.chipRow}>
        {job.route?.route && (
          <View style={[styles.chip, { backgroundColor: Colors.accentLight, borderColor: Colors.accentBorder }]}>
            <Text style={{ fontSize: 11, color: Colors.accent }}>{job.route.route.replace(/_/g, ' ')}</Text>
          </View>
        )}
        {job.is_sample && (
          <View style={[styles.chip, { backgroundColor: '#FEF3C7', borderColor: '#F59E0B40' }]}>
            <Text style={{ fontSize: 11, color: '#D97706' }}>SAMPLE</Text>
          </View>
        )}
      </View>

      <View style={styles.jobActions}>
        <TouchableOpacity
          testID={`job-shortlist-btn-${job.id}`}
          style={[styles.shortlistBtn, { backgroundColor: Colors.accent }]}
          onPress={() => onShortlist(job)}
          disabled={busy}
        >
          <Ionicons name="send-outline" size={14} color="#FFF" />
          <Text style={{ color: '#FFF', fontSize: 13, fontWeight: '600' }}>Shortlist</Text>
        </TouchableOpacity>
      </View>
    </TouchableOpacity>
  );
}

function ExcludedCard({ job }: { job: any }) {
  const c = Colors.light;
  return (
    <View testID={`excluded-card-${job.id}`} style={[styles.excludedCard, { borderColor: c.border }]}>
      <Text style={{ fontSize: 14, fontWeight: '500', color: c.ink }} numberOfLines={1}>{job.title}</Text>
      <Text style={{ fontSize: 12, color: c.inkMuted }}>{job.company_name}</Text>
      <View style={[styles.chipRow, { marginTop: 6 }]}>
        {(job.fail_reasons || []).map((r: string) => (
          <View key={r} style={[styles.chip, { borderColor: '#EF444440' }]}>
            <Text style={{ fontSize: 10, color: '#EF4444' }}>{REASON_LABELS[r] || r}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

export default function FeedScreen() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const c = Colors.light;

  const load = useCallback(async () => {
    try {
      const { data: res } = await api.get('/api/v1/jobs/feed');
      setData(res);
      setError('');
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') {
        setError('Grant the discover_jobs consent in Settings to access the feed.');
      } else if (detail?.error === 'passport_not_activated') {
        setError('Activate your Passport first. Go to Passport, approve claims, then activate.');
      } else {
        setError('Could not load your feed.');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = () => { setRefreshing(true); load(); };

  const passing = useMemo(() => data?.passing || [], [data]);
  const excluded = useMemo(() => data?.excluded || [], [data]);

  const shortlist = async (job: any) => {
    setBusy(job.id);
    try {
      await api.post(`/api/v1/jobs/${job.id}/shortlist`, {}, withIdempotency());
      Alert.alert('Shortlisted', `"${job.title}" added to your applications.`);
      await load();
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'already_shortlisted') Alert.alert('Already shortlisted', 'You have an open application for this job.');
      else Alert.alert('Error', 'Could not shortlist.');
    } finally { setBusy(null); }
  };

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock label="Scoring your feed..." /></View>;
  if (error) return (
    <View style={[styles.container, { backgroundColor: c.bg, padding: 20 }]}>
      <Text style={[styles.pageTitle, { color: c.ink }]}>Opportunity Feed</Text>
      <ErrorBlock message={error} onRetry={load} />
    </View>
  );

  return (
    <ScrollView
      testID="feed-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.accent} />}
    >
      <Text style={[styles.pageTitle, { color: c.ink }]}>Opportunity Feed</Text>
      <Text style={[styles.pageSubtitle, { color: c.inkMuted }]}>
        Live jobs your Passport passes eligibility for. Sorted by score.
      </Text>

      <View style={styles.statsRow}>
        <View style={[styles.statCard, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={{ fontSize: 11, color: c.inkMuted }}>Passing</Text>
          <Text testID="feed-totals-passing-real" style={[styles.statNum, { color: c.ink }]}>
            {passing.filter((j: any) => !j.is_sample).length}
          </Text>
        </View>
        <View style={[styles.statCard, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={{ fontSize: 11, color: c.inkMuted }}>Excluded</Text>
          <Text testID="feed-totals-excluded" style={[styles.statNum, { color: c.ink }]}>
            {excluded.length}
          </Text>
        </View>
        <View style={[styles.statCard, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={{ fontSize: 11, color: c.inkMuted }}>Total</Text>
          <Text style={[styles.statNum, { color: c.ink }]}>
            {(data?.totals?.passing || 0) + (data?.totals?.excluded || 0)}
          </Text>
        </View>
      </View>

      <Text style={[styles.sectionTitle, { color: c.ink }]}>Passing ({passing.length})</Text>
      {passing.length === 0 ? (
        <EmptyBlock title="Nothing passes all your gates yet" hint="Check excluded list for reasons." />
      ) : (
        passing.map((j: any) => (
          <JobCard
            key={j.id}
            job={j}
            busy={busy === j.id}
            onShortlist={shortlist}
            onPress={(job: any) => router.push(`/jobs/${job.id}`)}
          />
        ))
      )}

      {excluded.length > 0 && (
        <>
          <Text style={[styles.sectionTitle, { color: c.ink, marginTop: 24 }]}>Excluded ({excluded.length})</Text>
          {excluded.map((j: any) => <ExcludedCard key={j.id} job={j} />)}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSubtitle: { fontSize: 13, marginTop: 4, marginBottom: 16, lineHeight: 18 },
  statsRow: { flexDirection: 'row', gap: 8, marginBottom: 20 },
  statCard: { flex: 1, borderWidth: 1, borderRadius: 10, padding: 12 },
  statNum: { fontSize: 22, fontWeight: '700', marginTop: 4 },
  sectionTitle: { fontSize: 17, fontWeight: '600', marginBottom: 12 },
  jobCard: { borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 10 },
  jobTop: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  jobTitle: { fontSize: 15, fontWeight: '600', lineHeight: 20 },
  jobMeta: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 4, flexWrap: 'wrap' },
  scoreBadge: { alignItems: 'center', borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginTop: 8 },
  chip: { borderWidth: 1, borderRadius: 12, paddingHorizontal: 8, paddingVertical: 2 },
  jobActions: { flexDirection: 'row', justifyContent: 'flex-end', marginTop: 10 },
  shortlistBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8 },
  excludedCard: { borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 8 },
});
