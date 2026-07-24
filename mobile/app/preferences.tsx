import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, TextInput, Switch, KeyboardAvoidingView, Platform } from 'react-native';
import { Colors } from '../src/lib/theme';
import { api, withIdempotency } from '../src/lib/api';
import Input from '../src/components/Input';
import Button from '../src/components/Button';
import { Card, CardHeader } from '../src/components/Card';
import { LoadingBlock, ErrorBlock } from '../src/components/StatusBlocks';

const DEFAULT_PREFS = {
  role_families: [],
  locations: [],
  remote_ok: false,
  salary_floor_usd: null as number | null,
  search_intensity: 'medium',
  employer_include: [],
  employer_exclude: [],
  notes: '',
};

export default function PreferencesScreen() {
  const [prefs, setPrefs] = useState(DEFAULT_PREFS);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [locInput, setLocInput] = useState('');
  const c = Colors.light;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/api/v1/preferences/me');
      setVersion(data.version);
      if (data.payload) setPrefs({ ...DEFAULT_PREFS, ...data.payload });
      setError('');
    } catch { setError('Could not load preferences.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const patch = (upd: any) => setPrefs((p) => ({ ...p, ...upd }));
  const addLocation = () => {
    const v = locInput.trim();
    if (!v || prefs.locations.includes(v)) return;
    patch({ locations: [...prefs.locations, v] });
    setLocInput('');
  };

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.post('/api/v1/preferences', prefs, withIdempotency());
      setVersion(data.version);
    } catch { setError('Could not save.'); }
    finally { setSaving(false); }
  };

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock /></View>;

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
      <ScrollView
        testID="preferences-page"
        style={[styles.container, { backgroundColor: c.bg }]}
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={[styles.pageTitle, { color: c.ink }]}>Preferences</Text>
        <Text style={[styles.pageSub, { color: c.inkMuted }]}>What kind of roles, where, at what floor. Version {version}.</Text>

        {error ? <ErrorBlock message={error} onRetry={load} /> : null}

        <Card>
          <CardHeader title="Locations" subtitle="Free-form city or region." />
          <View style={styles.locRow}>
            <TextInput
              style={[styles.locInput, { borderColor: c.border, color: c.ink }]}
              placeholder="e.g. Phoenix, AZ"
              placeholderTextColor={c.inkMuted}
              value={locInput}
              onChangeText={setLocInput}
              onSubmitEditing={addLocation}
              testID="pref-location-input"
            />
            <Button size="sm" variant="secondary" onPress={addLocation}>
              <Text style={{ fontSize: 13, color: c.ink }}>Add</Text>
            </Button>
          </View>
          <View style={styles.chipRow}>
            {prefs.locations.map((loc: string) => (
              <View key={loc} style={[styles.chip, { backgroundColor: Colors.accentLight, borderColor: Colors.accentBorder }]}>
                <Text style={{ fontSize: 12, color: Colors.accent }}>{loc}</Text>
                <Text style={{ fontSize: 14, color: Colors.accent, marginLeft: 4 }} onPress={() => patch({ locations: prefs.locations.filter((l: string) => l !== loc) })}>×</Text>
              </View>
            ))}
          </View>
          <View style={styles.switchRow}>
            <Text style={{ fontSize: 14, color: c.ink }}>Open to fully remote</Text>
            <Switch value={prefs.remote_ok} onValueChange={(v) => patch({ remote_ok: v })} trackColor={{ true: Colors.accent }} />
          </View>
        </Card>

        <Card>
          <CardHeader title="Comp floor" subtitle="Private — never shared with employers." />
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Text style={{ color: c.inkMuted }}>USD</Text>
            <Input
              keyboardType="numeric"
              placeholder="e.g. 135000"
              value={prefs.salary_floor_usd != null ? String(prefs.salary_floor_usd) : ''}
              onChangeText={(v) => patch({ salary_floor_usd: v === '' ? null : Number(v) })}
              style={{ flex: 1 }}
              testID="pref-salary-input"
            />
          </View>
        </Card>

        <Card>
          <CardHeader title="Search intensity" />
          <View style={styles.intensityRow}>
            {['low', 'medium', 'high'].map((k) => (
              <View
                key={k}
                style={[styles.intensityBtn, { borderColor: prefs.search_intensity === k ? Colors.accent : c.border, backgroundColor: prefs.search_intensity === k ? Colors.accentLight : 'transparent' }]}
              >
                <Text
                  style={{ fontSize: 13, color: prefs.search_intensity === k ? Colors.accent : c.ink, fontWeight: '500' }}
                  onPress={() => patch({ search_intensity: k })}
                >
                  {k.charAt(0).toUpperCase() + k.slice(1)}
                </Text>
              </View>
            ))}
          </View>
        </Card>

        <Button onPress={save} loading={saving} testID="pref-save-btn" style={{ marginTop: 8 }}>
          <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 15 }}>Save preferences</Text>
        </Button>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSub: { fontSize: 13, marginTop: 4, marginBottom: 16 },
  locRow: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  locInput: { flex: 1, borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 },
  chip: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 12, paddingHorizontal: 10, paddingVertical: 4 },
  switchRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 },
  intensityRow: { flexDirection: 'row', gap: 8 },
  intensityBtn: { flex: 1, borderWidth: 1, borderRadius: 8, paddingVertical: 12, alignItems: 'center' },
});
