import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  RefreshControl, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../src/lib/theme';
import { api } from '../src/lib/api';
import { Card, CardHeader } from '../src/components/Card';
import Button from '../src/components/Button';
import { LoadingBlock } from '../src/components/StatusBlocks';
import AuthGate from '../src/components/AuthGate';

const c = Colors.light;

export default function PrivacyScreen() {
  return <AuthGate><PrivacyContent /></AuthGate>;
}

function PrivacyContent() {
  const [scopes, setScopes] = useState<any[]>([]);
  const [releases, setReleases] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState<{ kind: string; message: string } | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cRes, rRes] = await Promise.all([
        api.get('/api/v1/privacy/consents'),
        api.get('/api/v1/privacy/release-log'),
      ]);
      setScopes(cRes.data.scopes || []);
      setReleases(rRes.data.releases || []);
    } catch (e) { console.debug('privacy load error', e); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const revoke = async (scope: string) => {
    setRevoking(scope);
    try {
      await api.post('/api/v1/privacy/consents/revoke', { scope });
      setFlash({ kind: 'ok', message: `Consent revoked for ${scope}.` });
      await load();
    } catch {
      setFlash({ kind: 'warn', message: 'Revoke failed.' });
    } finally { setRevoking(null); }
  };

  const startExport = async () => {
    setExporting(true);
    try {
      const r = await api.post('/api/v1/privacy/export', {});
      const detail = await api.get(`/api/v1/privacy/export/${r.data.job_id}`);
      if (detail.data.status === 'ready') {
        setFlash({ kind: 'ok', message: `Export ready: ${detail.data.download?.filename || 'bundle.json'}. Use the web app to download the file.` });
      } else {
        setFlash({ kind: 'ok', message: 'Export job queued. Check back in a moment.' });
      }
    } catch {
      setFlash({ kind: 'warn', message: 'Export failed.' });
    } finally { setExporting(false); }
  };

  const confirmDelete = async () => {
    try {
      const r = await api.post('/api/v1/privacy/account/delete', { confirm: true });
      setFlash({ kind: 'warn', message: r.data.message || 'Deletion started. 30-day window active.' });
      setShowDeleteConfirm(false);
    } catch (e: any) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail?.message || 'Delete failed.' });
    }
  };

  if (loading && !refreshing) {
    return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock label="Loading privacy data…" /></View>;
  }

  return (
    <ScrollView
      testID="privacy-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.accent} />}
    >
      <View style={styles.titleRow}>
        <Ionicons name="lock-closed" size={22} color={c.ink} />
        <Text style={[styles.pageTitle, { color: c.ink }]}>Privacy</Text>
      </View>
      <Text style={[styles.pageSub, { color: c.inkMuted }]}>Your consents, releases, and a one-click export of everything we have on you.</Text>

      {flash && (
        <View testID="privacy-flash" style={[styles.flashBox, {
          borderColor: flash.kind === 'ok' ? Colors.accentBorder : c.warningBorder,
          backgroundColor: flash.kind === 'ok' ? Colors.accentLight : c.warningBg,
        }]}>
          <Text style={{ fontSize: 13, color: flash.kind === 'ok' ? Colors.accent : c.warning }}>{flash.message}</Text>
        </View>
      )}

      {/* Consent scopes */}
      <Card testID="consent-scopes">
        <CardHeader title="Active consent scopes" />
        {scopes.map((s) => (
          <View key={s.scope} testID={`consent-row-${s.scope}`} style={[styles.consentRow, { borderBottomColor: c.border }]}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 14, fontWeight: '500', color: c.ink }}>{s.label}</Text>
              <Text style={{ fontSize: 11, color: c.inkMuted, fontFamily: 'monospace' }}>{s.scope}</Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <View style={[styles.pill, { borderColor: s.granted ? Colors.accentBorder : c.border }]}>
                <Text style={{ fontSize: 10, color: s.granted ? Colors.accent : c.inkMuted }}>{s.granted ? 'granted' : 'revoked'}</Text>
              </View>
              {s.granted && (
                <TouchableOpacity testID={`consent-revoke-${s.scope}`} onPress={() => revoke(s.scope)} disabled={revoking === s.scope}>
                  {revoking === s.scope ? (
                    <ActivityIndicator size="small" color={Colors.accent} />
                  ) : (
                    <Text style={{ fontSize: 12, color: c.inkMuted, textDecorationLine: 'underline' }}>Revoke</Text>
                  )}
                </TouchableOpacity>
              )}
            </View>
          </View>
        ))}
      </Card>

      {/* Release log */}
      <Card testID="release-log">
        <CardHeader title="Data-release log" />
        {releases.length === 0 ? (
          <Text style={{ fontSize: 13, color: c.inkMuted }}>No releases yet — nothing has been sent to an employer on your behalf.</Text>
        ) : (
          releases.map((r) => (
            <View key={r.receipt_id} style={[styles.releaseRow, { borderColor: c.border }]}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text style={{ fontSize: 13, fontWeight: '500', color: c.ink }}>{r.employer}</Text>
                <Text style={{ fontSize: 10, color: c.inkMuted }}>{new Date(r.ts).toLocaleString()}</Text>
              </View>
              <Text style={{ fontSize: 11, color: c.inkMuted, marginTop: 2 }}>
                {r.role} · req {r.req_ref} · hash {(r.materials_hash || '').slice(0, 10)}
              </Text>
            </View>
          ))
        )}
      </Card>

      {/* Export */}
      <Card testID="export-section">
        <CardHeader title="Export" subtitle="A complete JSON bundle of your profile, claims, documents, applications, consents, and audit trail." />
        <Button variant="accent" onPress={startExport} loading={exporting} testID="export-btn">
          <Ionicons name="download-outline" size={14} color="#FFF" />
          <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14, marginLeft: 4 }}>Export my data</Text>
        </Button>
      </Card>

      {/* Delete account */}
      <Card testID="delete-section">
        <CardHeader title="Delete account" subtitle="Enters a 30-day soft-delete window. Sign in during that window to restore. After 30 days, all your data is permanently removed." />
        {!showDeleteConfirm ? (
          <TouchableOpacity testID="delete-open" onPress={() => setShowDeleteConfirm(true)}>
            <Text style={{ fontSize: 13, color: c.error, textDecorationLine: 'underline' }}>Delete my account…</Text>
          </TouchableOpacity>
        ) : (
          <View testID="delete-confirm" style={[styles.deleteBox, { borderColor: c.errorBorder, backgroundColor: c.errorBg }]}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Ionicons name="warning" size={14} color={c.error} />
              <Text style={{ fontSize: 13, color: c.error }}>This starts the 30-day countdown.</Text>
            </View>
            <View style={{ flexDirection: 'row', gap: 12, marginTop: 12 }}>
              <Button variant="accent" onPress={confirmDelete} testID="delete-confirm-btn" style={{ backgroundColor: c.error }}>
                <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 13 }}>Yes, start deletion</Text>
              </Button>
              <TouchableOpacity onPress={() => setShowDeleteConfirm(false)} style={{ justifyContent: 'center' }}>
                <Text style={{ fontSize: 13, color: c.inkMuted, textDecorationLine: 'underline' }}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSub: { fontSize: 13, marginTop: 4, marginBottom: 16 },
  flashBox: { borderWidth: 1, borderRadius: 8, padding: 12, marginBottom: 12 },
  pill: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 3 },
  consentRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 12, borderBottomWidth: 1, gap: 12 },
  releaseRow: { borderWidth: 1, borderRadius: 8, padding: 12, marginBottom: 6 },
  deleteBox: { borderWidth: 1, borderRadius: 8, padding: 14, marginTop: 8 },
});
