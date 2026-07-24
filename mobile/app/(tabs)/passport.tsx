import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, RefreshControl, StyleSheet, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../../src/lib/theme';
import { api, withIdempotency } from '../../src/lib/api';
import { prettyValue, sourceChip, sortGroups, CLAIM_TYPE_ORDER } from '../../src/lib/utils';
import { LoadingBlock, ErrorBlock, EmptyBlock } from '../../src/components/StatusBlocks';
import Button from '../../src/components/Button';

function ClaimRow({ claim, onApprove, onReject, busy }: any) {
  const c = Colors.light;
  const status = claim.status || 'pending';
  const statusColor = status === 'approved' ? Colors.accent : status === 'rejected' ? c.error : c.inkMuted;
  const chip = sourceChip(claim.source);

  return (
    <View style={[styles.claimRow, { borderColor: c.border }]}>
      <Text style={[styles.claimValue, { color: c.ink }]}>{prettyValue(claim.value)}</Text>
      <View style={styles.claimMeta}>
        <View style={[styles.pill, { borderColor: chip.tone === 'accent' ? Colors.accentBorder : c.border }]}>
          <Text style={{ fontSize: 10, color: chip.tone === 'accent' ? Colors.accent : c.inkMuted }}>{chip.label}</Text>
        </View>
        <View style={[styles.pill, { borderColor: statusColor + '40' }]}>
          <Text style={{ fontSize: 10, color: statusColor, fontWeight: '600' }}>{status}</Text>
        </View>
      </View>
      {status === 'pending' && (
        <View style={styles.claimActions}>
          <Button size="sm" onPress={onApprove} loading={busy} testID={`approve-claim-${claim.id}`}>
            <Text style={{ color: '#FFF', fontSize: 12, fontWeight: '600' }}>Approve</Text>
          </Button>
          <Button size="sm" variant="ghost" onPress={onReject} loading={busy}>
            <Text style={{ color: c.inkMuted, fontSize: 12 }}>Reject</Text>
          </Button>
        </View>
      )}
    </View>
  );
}

function ActivationBanner({ status, onActivate, activating }: any) {
  const c = Colors.light;
  if (!status) return null;
  if (status.activated) {
    return (
      <View style={[styles.bannerActivated, { borderColor: Colors.accentBorder, backgroundColor: Colors.accentLight }]}>
        <Ionicons name="shield-checkmark" size={20} color={Colors.accent} />
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 14, fontWeight: '600', color: c.ink }}>Passport activated</Text>
          <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 2 }}>Downstream features are now unlocked.</Text>
        </View>
      </View>
    );
  }

  const req = status.requirements || {};
  const items = [
    { key: 'identity_approved', label: 'At least one approved identity claim', met: req.identity_approved },
    { key: 'education_or_employment_approved', label: 'At least one approved education or employment claim', met: req.education_or_employment_approved },
  ];

  return (
    <View style={[styles.bannerCard, { borderColor: c.border, backgroundColor: c.card }]}>
      <Text style={{ fontSize: 14, fontWeight: '600', color: c.ink }}>Activate your Passport</Text>
      <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 2 }}>Meet the checklist below.</Text>
      {items.map((i) => (
        <View key={i.key} style={styles.checkItem}>
          <Ionicons name={i.met ? 'checkmark-circle' : 'close-circle'} size={18} color={i.met ? Colors.accent : c.error} />
          <Text style={{ fontSize: 13, color: i.met ? c.ink : c.inkMuted, flex: 1 }}>{i.label}</Text>
        </View>
      ))}
      <Button
        testID="activate-passport-btn"
        onPress={onActivate}
        disabled={!status.can_activate}
        loading={activating}
        style={{ marginTop: 12, alignSelf: 'flex-end' }}
      >
        <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14 }}>Activate Passport</Text>
      </Button>
    </View>
  );
}

export default function PassportScreen() {
  const [groups, setGroups] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [activation, setActivation] = useState<any>(null);
  const [activating, setActivating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const c = Colors.light;

  const reload = useCallback(async () => {
    try {
      const [{ data: claims }, { data: act }] = await Promise.all([
        api.get('/api/v1/claims'),
        api.get('/api/v1/passport/activation-status'),
      ]);
      setGroups(sortGroups(claims.groups || []));
      setActivation(act);
      setError('');
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') setError('The process_career_data consent is required. Grant it in Settings.');
      else setError('Could not load your Passport.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const approve = async (claim: any) => {
    setBusyId(claim.id);
    try {
      await api.post(`/api/v1/claims/${claim.id}/approve`, {}, withIdempotency());
      await reload();
    } finally { setBusyId(null); }
  };

  const reject = async (claim: any) => {
    setBusyId(claim.id);
    try {
      await api.post(`/api/v1/claims/${claim.id}/reject`, {}, withIdempotency());
      await reload();
    } finally { setBusyId(null); }
  };

  const activate = async () => {
    setActivating(true);
    try {
      await api.post('/api/v1/passport/activate', {}, withIdempotency());
      await reload();
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail?.hint || 'Activation failed.');
    } finally { setActivating(false); }
  };

  const totalClaims = useMemo(() => groups.reduce((n: number, g: any) => n + g.claims.length, 0), [groups]);

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock /></View>;

  return (
    <ScrollView
      testID="passport-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); reload(); }} tintColor={Colors.accent} />}
    >
      <Text style={[styles.pageTitle, { color: c.ink }]}>Career Passport</Text>
      <Text style={[styles.pageSubtitle, { color: c.inkMuted }]}>
        Every fact about you lives here. Approve what's true, reject what isn't.
      </Text>

      <ActivationBanner status={activation} onActivate={activate} activating={activating} />

      {error ? <ErrorBlock message={error} onRetry={reload} /> : null}

      {!error && totalClaims === 0 && (
        <EmptyBlock title="No claims yet" hint="Upload a resume on the web app to parse it into draft claims." />
      )}

      {groups.map((g: any) => (
        <View key={g.type} style={styles.groupSection}>
          <Text style={[styles.groupTitle, { color: c.inkMuted }]}>{g.type.toUpperCase()}</Text>
          {g.claims.map((claim: any) => (
            <ClaimRow
              key={claim.id}
              claim={claim}
              busy={busyId === claim.id}
              onApprove={() => approve(claim)}
              onReject={() => reject(claim)}
            />
          ))}
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSubtitle: { fontSize: 13, marginTop: 4, marginBottom: 16, lineHeight: 18 },
  bannerActivated: { borderWidth: 1, borderRadius: 12, padding: 14, flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 16 },
  bannerCard: { borderWidth: 1, borderRadius: 12, padding: 16, marginBottom: 16 },
  checkItem: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 8 },
  groupSection: { marginBottom: 24 },
  groupTitle: { fontSize: 12, fontWeight: '700', letterSpacing: 1, marginBottom: 8 },
  claimRow: { borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 8, backgroundColor: '#FFF' },
  claimValue: { fontSize: 14, lineHeight: 20 },
  claimMeta: { flexDirection: 'row', gap: 6, marginTop: 8 },
  pill: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 2 },
  claimActions: { flexDirection: 'row', gap: 8, marginTop: 10, justifyContent: 'flex-end' },
});
