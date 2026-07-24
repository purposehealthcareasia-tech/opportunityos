import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, RefreshControl, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../../src/lib/theme';
import { api, withIdempotency } from '../../src/lib/api';
import { useAuth } from '../../src/lib/auth';
import Input from '../../src/components/Input';
import Button from '../../src/components/Button';
import { Card, CardHeader } from '../../src/components/Card';
import { LoadingBlock } from '../../src/components/StatusBlocks';

function ConsentRow({ scope, meta, granted, ts, onToggle, saving }: any) {
  const c = Colors.light;
  return (
    <View style={[styles.consentRow, { borderBottomColor: c.border }]}>
      <View style={{ flex: 1 }}>
        <View style={styles.consentLabelRow}>
          <Text style={{ fontSize: 14, fontWeight: '500', color: c.ink }}>{meta?.label || scope}</Text>
          {meta?.required && (
            <View style={[styles.pill, { borderColor: c.border }]}>
              <Text style={{ fontSize: 10, color: c.inkMuted }}>required</Text>
            </View>
          )}
          <View style={[styles.pill, { borderColor: granted ? Colors.accentBorder : c.border }]}>
            <Ionicons name={granted ? 'shield-checkmark' : 'shield-outline'} size={10} color={granted ? Colors.accent : c.inkMuted} />
            <Text style={{ fontSize: 10, color: granted ? Colors.accent : c.inkMuted, marginLeft: 2 }}>{granted ? 'granted' : 'revoked'}</Text>
          </View>
        </View>
        <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 4, lineHeight: 17 }}>{meta?.description}</Text>
      </View>
      <Button
        size="sm"
        variant={granted ? 'secondary' : 'accent'}
        onPress={() => onToggle(!granted)}
        loading={saving}
      >
        <Text style={{ fontSize: 12, color: granted ? c.ink : '#FFF', fontWeight: '500' }}>{granted ? 'Revoke' : 'Grant'}</Text>
      </Button>
    </View>
  );
}

export default function SettingsScreen() {
  const { user, refresh, logout } = useAuth();
  const router = useRouter();
  const [profileName, setProfileName] = useState(user?.name || '');
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMsg, setProfileMsg] = useState('');

  const [consentState, setConsentState] = useState<any>({ scopes: [], policy_text_version: '1.0' });
  const [catalog, setCatalog] = useState<any[]>([]);
  const [cLoading, setCLoading] = useState(true);
  const [savingScope, setSavingScope] = useState<string | null>(null);
  const c = Colors.light;

  useEffect(() => { setProfileName(user?.name || ''); }, [user]);

  const loadConsents = useCallback(async () => {
    setCLoading(true);
    try {
      const [meta, live] = await Promise.all([
        api.get('/api/v1/meta/policy'),
        api.get('/api/v1/consents'),
      ]);
      setCatalog(meta.data.scopes || []);
      setConsentState(live.data);
    } catch {}
    finally { setCLoading(false); }
  }, []);

  useEffect(() => { loadConsents(); }, [loadConsents]);

  const catalogByScope = useMemo(() => Object.fromEntries(catalog.map((c: any) => [c.scope, c])), [catalog]);

  async function saveProfile() {
    setSavingProfile(true); setProfileMsg('');
    try {
      await api.patch('/api/v1/users/me', { name: profileName.trim() }, withIdempotency());
      await refresh();
      setProfileMsg('Saved.');
    } catch { setProfileMsg('Could not save.'); }
    finally { setSavingProfile(false); }
  }

  async function toggleScope(scope: string, next: boolean) {
    setSavingScope(scope);
    try {
      await api.post('/api/v1/consents', { scope, granted: next, policy_text_version: consentState.policy_text_version }, withIdempotency());
      await loadConsents();
    } catch {}
    finally { setSavingScope(null); }
  }

  async function handleLogout() {
    await logout();
    router.replace('/login');
  }

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
      <ScrollView
        testID="settings-page"
        style={[styles.container, { backgroundColor: c.bg }]}
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={[styles.pageTitle, { color: c.ink }]}>Settings</Text>
        <Text style={[styles.pageSub, { color: c.inkMuted }]}>Profile, security, and consent ledger.</Text>

        <Card>
          <CardHeader title="Profile" subtitle="Your name is used across the product interface." />
          <Input label="Email" value={user?.email || ''} editable={false} />
          <View style={{ height: 12 }} />
          <Input label="Full name" value={profileName} onChangeText={setProfileName} testID="settings-name-input" />
          <View style={styles.profileActions}>
            {profileMsg ? <Text style={{ fontSize: 12, color: Colors.accent }}>{profileMsg}</Text> : <View />}
            <Button onPress={saveProfile} loading={savingProfile} testID="settings-save-profile">
              <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14 }}>Save changes</Text>
            </Button>
          </View>
        </Card>

        <Card>
          <CardHeader title="Consent scopes" subtitle={`Append-only ledger · policy v${consentState.policy_text_version}`} />
          {cLoading ? <LoadingBlock label="Loading consents..." /> : (
            consentState.scopes.map((s: any) => (
              <ConsentRow
                key={s.scope}
                scope={s.scope}
                meta={catalogByScope[s.scope]}
                granted={s.granted}
                ts={s.ts}
                saving={savingScope === s.scope}
                onToggle={(next: boolean) => toggleScope(s.scope, next)}
              />
            ))
          )}
        </Card>

        <View style={styles.navLinks}>
          <TouchableOpacity style={[styles.navLink, { borderColor: c.border }]} onPress={() => router.push('/preferences')}>
            <Ionicons name="options-outline" size={18} color={c.ink} />
            <Text style={{ fontSize: 14, color: c.ink, flex: 1 }}>Preferences</Text>
            <Ionicons name="chevron-forward" size={16} color={c.inkMuted} />
          </TouchableOpacity>
          <TouchableOpacity style={[styles.navLink, { borderColor: c.border }]} onPress={() => router.push('/eligibility')}>
            <Ionicons name="shield-checkmark-outline" size={18} color={c.ink} />
            <Text style={{ fontSize: 14, color: c.ink, flex: 1 }}>Eligibility</Text>
            <Ionicons name="chevron-forward" size={16} color={c.inkMuted} />
          </TouchableOpacity>
          <TouchableOpacity style={[styles.navLink, { borderColor: c.border }]} onPress={() => router.push('/approvals')}>
            <Ionicons name="checkmark-done-outline" size={18} color={c.ink} />
            <Text style={{ fontSize: 14, color: c.ink, flex: 1 }}>Approvals</Text>
            <Ionicons name="chevron-forward" size={16} color={c.inkMuted} />
          </TouchableOpacity>
          <TouchableOpacity style={[styles.navLink, { borderColor: c.border }]} onPress={() => router.push('/analyticsScreen')}>
            <Ionicons name="bar-chart-outline" size={18} color={c.ink} />
            <Text style={{ fontSize: 14, color: c.ink, flex: 1 }}>Analytics</Text>
            <Ionicons name="chevron-forward" size={16} color={c.inkMuted} />
          </TouchableOpacity>
        </View>

        <TouchableOpacity testID="logout-btn" style={[styles.logoutBtn, { borderColor: c.error }]} onPress={handleLogout}>
          <Ionicons name="log-out-outline" size={18} color={c.error} />
          <Text style={{ color: c.error, fontWeight: '600', fontSize: 14 }}>Sign out</Text>
        </TouchableOpacity>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSub: { fontSize: 13, marginTop: 4, marginBottom: 16 },
  profileActions: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 16 },
  consentRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingVertical: 12, borderBottomWidth: 1 },
  consentLabelRow: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  pill: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 10, paddingHorizontal: 6, paddingVertical: 1 },
  navLinks: { marginBottom: 16 },
  navLink: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderWidth: 1, borderRadius: 10, marginBottom: 8, backgroundColor: '#FFF' },
  logoutBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, padding: 14, borderWidth: 1, borderRadius: 10 },
});
