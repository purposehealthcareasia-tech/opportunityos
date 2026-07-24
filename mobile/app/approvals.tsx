import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, RefreshControl, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../src/lib/theme';
import { api } from '../src/lib/api';
import { LoadingBlock, ErrorBlock } from '../src/components/StatusBlocks';
import Button from '../src/components/Button';

export default function ApprovalsScreen() {
  const router = useRouter();
  const [apps, setApps] = useState<any[]>([]);
  const [approved, setApproved] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [sub, setSub] = useState<any>(null);
  const [receipts, setReceipts] = useState<any[]>([]);
  const c = Colors.light;

  const load = useCallback(async () => {
    try {
      const [appsRes, subRes, recRes] = await Promise.all([
        api.get('/api/v1/applications'),
        api.get('/api/v1/subscriptions/me'),
        api.get('/api/v1/applications/receipts/mine'),
      ]);
      const all = appsRes.data.applications || [];
      setApps(all.filter((a: any) => a.state === 'awaiting_approval'));
      setApproved(all.filter((a: any) => a.state === 'approved'));
      setSub(subRes.data);
      setReceipts(recRes.data.receipts || []);
      setError('');
    } catch { setError('Failed to load approvals.'); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const approveOne = async (appId: string) => {
    try {
      await api.post(`/api/v1/applications/${appId}/approve`, {});
      await load();
    } catch {}
  };

  const revokeOne = async (appId: string) => {
    try {
      await api.post(`/api/v1/applications/${appId}/revoke-authorization`, {});
      await load();
    } catch {}
  };

  const usedToday = useMemo(() => {
    const today = new Date();
    today.setUTCHours(0, 0, 0, 0);
    return receipts.filter((r: any) => new Date(r.ts).getTime() >= today.getTime()).length;
  }, [receipts]);

  const cap = sub?.daily_submit_cap ?? 3;

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock /></View>;

  return (
    <ScrollView
      testID="approvals-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.accent} />}
    >
      <Text style={[styles.pageTitle, { color: c.ink }]}>Approvals</Text>
      <Text style={[styles.pageSub, { color: c.inkMuted }]}>Final go-ahead. Approving creates a 72h authorization window.</Text>

      {error ? <ErrorBlock message={error} onRetry={load} /> : null}

      <View style={[styles.capCard, { borderColor: c.border }]}>
        <Text style={{ fontSize: 12, color: c.inkMuted }}>Daily submit cap</Text>
        <Text testID="daily-cap-meter" style={[styles.capNum, { color: c.ink }]}>{usedToday}/{cap} today</Text>
        <Text style={{ fontSize: 11, color: c.inkMuted }}>{sub ? `Plan: ${sub.label}` : 'Loading...'}</Text>
      </View>

      {apps.length === 0 && approved.length === 0 && (
        <View testID="approvals-empty" style={[styles.emptyBox, { borderColor: c.border }]}>
          <Text style={{ fontSize: 14, color: c.inkMuted, textAlign: 'center' }}>Nothing awaiting approval.</Text>
        </View>
      )}

      {apps.length > 0 && (
        <View testID="approvals-queue">
          <Text style={[styles.sectionTitle, { color: c.ink }]}>Awaiting approval ({apps.length})</Text>
          {apps.map((a: any) => (
            <View key={a.id} testID={`approvals-row-${a.id}`} style={[styles.rowCard, { borderColor: c.border }]}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 14, fontWeight: '500', color: c.ink }} numberOfLines={1}>{a.job_snapshot?.title || 'Untitled'}</Text>
                <Text style={{ fontSize: 12, color: c.inkMuted }}>{a.job_snapshot?.company_name}</Text>
              </View>
              <Button size="sm" onPress={() => approveOne(a.id)} testID={`approvals-approve-${a.id}`}>
                <Text style={{ color: '#FFF', fontSize: 12, fontWeight: '600' }}>Approve</Text>
              </Button>
            </View>
          ))}
        </View>
      )}

      {approved.length > 0 && (
        <View testID="approvals-approved-list" style={{ marginTop: 16 }}>
          <Text style={[styles.sectionTitle, { color: c.ink }]}>Approved — awaiting submit ({approved.length})</Text>
          {approved.map((a: any) => (
            <View key={a.id} testID={`approvals-approved-row-${a.id}`} style={[styles.rowCard, { borderColor: Colors.accentBorder, backgroundColor: Colors.accentLight }]}>
              <Ionicons name="shield-checkmark" size={18} color={Colors.accent} />
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 14, fontWeight: '500', color: c.ink }} numberOfLines={1}>{a.job_snapshot?.title || 'Untitled'}</Text>
                <Text style={{ fontSize: 12, color: c.inkMuted }}>{a.job_snapshot?.company_name}</Text>
              </View>
              <TouchableOpacity testID={`approvals-revoke-${a.id}`} onPress={() => revokeOne(a.id)}>
                <Text style={{ fontSize: 12, color: c.inkMuted }}>Revoke</Text>
              </TouchableOpacity>
            </View>
          ))}
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
  capCard: { borderWidth: 1, borderRadius: 10, padding: 14, marginBottom: 16, backgroundColor: '#FFF' },
  capNum: { fontSize: 24, fontWeight: '700', marginVertical: 4 },
  sectionTitle: { fontSize: 16, fontWeight: '600', marginBottom: 10 },
  rowCard: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 8, backgroundColor: '#FFF' },
  emptyBox: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 12, padding: 32, alignItems: 'center' },
});
