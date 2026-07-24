import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, RefreshControl, StyleSheet, Modal, TextInput } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../../src/lib/theme';
import { api } from '../../src/lib/api';
import { LoadingBlock, ErrorBlock } from '../../src/components/StatusBlocks';

const COLUMN_ORDER = ['prepared', 'submitted', 'response', 'interview', 'offer', 'closed'];
const COLUMN_LABEL: Record<string, string> = {
  prepared: 'Prepared', submitted: 'Submitted', response: 'Response',
  interview: 'Interview', offer: 'Offer', closed: 'Closed',
};
const OUTCOME_OPTIONS = [
  { value: 'response', label: 'Response received' },
  { value: 'interview_request', label: 'Interview request' },
  { value: 'offer', label: 'Offer received' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'closed', label: 'Closed / withdrew' },
];

export default function TrackerScreen() {
  const router = useRouter();
  const [columns, setColumns] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [logFor, setLogFor] = useState<any>(null);
  const [logEvent, setLogEvent] = useState('response');
  const [logNote, setLogNote] = useState('');
  const [logBusy, setLogBusy] = useState(false);
  const c = Colors.light;

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/tracker');
      setColumns(data.columns);
      setError('');
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') setError('Grant the track_applications consent in Settings.');
      else setError('Failed to load tracker.');
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const submitLog = async () => {
    if (!logFor) return;
    setLogBusy(true);
    try {
      await api.post(`/api/v1/applications/${logFor.application_id}/outcomes`, { event: logEvent, note: logNote || null });
      setLogFor(null);
      setLogNote('');
      await load();
    } catch { }
    finally { setLogBusy(false); }
  };

  if (loading) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock /></View>;
  if (error) return (
    <View style={[styles.container, { backgroundColor: c.bg, padding: 20 }]}>
      <Text style={[styles.pageTitle, { color: c.ink }]}>Tracker</Text>
      <ErrorBlock message={error} onRetry={load} />
    </View>
  );

  return (
    <ScrollView
      testID="tracker-page"
      style={[styles.container, { backgroundColor: c.bg }]}
      contentContainerStyle={styles.scrollContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.accent} />}
    >
      <Text style={[styles.pageTitle, { color: c.ink }]}>Tracker</Text>
      <Text style={[styles.pageSub, { color: c.inkMuted }]}>Move cards by logging outcomes. Every event is append-only.</Text>

      {COLUMN_ORDER.map((col) => {
        const cards = columns?.[col] || [];
        if (cards.length === 0) return null;
        return (
          <View key={col} testID={`tracker-column-${col}`} style={styles.columnSection}>
            <View style={styles.colHeader}>
              <Text style={[styles.colTitle, { color: c.inkMuted }]}>{COLUMN_LABEL[col]}</Text>
              <Text testID={`tracker-count-${col}`} style={{ fontSize: 12, color: c.inkMuted }}>{cards.length}</Text>
            </View>
            {cards.map((card: any) => {
              const snap = card.job_snapshot || {};
              return (
                <View key={card.application_id} testID={`tracker-card-${card.application_id}`} style={[styles.trackerCard, { backgroundColor: c.card, borderColor: c.border }]}>
                  <Text style={{ fontSize: 14, fontWeight: '500', color: c.ink }} numberOfLines={1}>{snap.title || 'Untitled'}</Text>
                  <Text style={{ fontSize: 12, color: c.inkMuted }}>{snap.company_name || 'Unknown'}</Text>
                  {card.latest_outcome && (
                    <Text style={{ fontSize: 11, color: c.inkMuted, marginTop: 4 }}>
                      {card.latest_outcome.event} · {new Date(card.latest_outcome.ts).toLocaleDateString()}
                    </Text>
                  )}
                  <View style={styles.cardActions}>
                    <TouchableOpacity
                      testID={`tracker-open-${card.application_id}`}
                      style={[styles.smallBtn, { borderColor: c.border }]}
                      onPress={() => router.push(`/jobs/${snap.job_id || card.application_id}`)}
                    >
                      <Text style={{ fontSize: 11, color: c.inkMuted }}>Open</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      testID={`tracker-log-update-${card.application_id}`}
                      style={[styles.smallBtn, { borderColor: c.border }]}
                      onPress={() => { setLogFor(card); setLogEvent('response'); setLogNote(''); }}
                    >
                      <Text style={{ fontSize: 11, color: c.inkMuted }}>Log update</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              );
            })}
          </View>
        );
      })}

      {!columns || COLUMN_ORDER.every((col) => (columns[col] || []).length === 0) && (
        <View style={[styles.emptyBox, { borderColor: c.border }]}>
          <Text style={{ fontSize: 14, color: c.inkMuted, textAlign: 'center' }}>No tracked applications yet.</Text>
        </View>
      )}

      <Modal visible={!!logFor} transparent animationType="fade">
        <View testID="log-update-modal" style={styles.modalBg}>
          <View style={[styles.modalCard, { backgroundColor: c.card }]}>
            <Text style={{ fontSize: 16, fontWeight: '600', color: c.ink }}>Log update</Text>
            <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 4 }}>
              {logFor?.job_snapshot?.company_name} · {logFor?.job_snapshot?.title}
            </Text>

            <Text style={{ fontSize: 13, fontWeight: '500', color: c.ink, marginTop: 16 }}>Event</Text>
            <View style={styles.eventOptions}>
              {OUTCOME_OPTIONS.map((o) => (
                <TouchableOpacity
                  key={o.value}
                  testID={`log-event-${o.value}`}
                  style={[styles.eventBtn, { borderColor: logEvent === o.value ? Colors.accent : c.border, backgroundColor: logEvent === o.value ? Colors.accentLight : 'transparent' }]}
                  onPress={() => setLogEvent(o.value)}
                >
                  <Text style={{ fontSize: 12, color: logEvent === o.value ? Colors.accent : c.ink }}>{o.label}</Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={{ fontSize: 13, fontWeight: '500', color: c.ink, marginTop: 12 }}>Note (optional)</Text>
            <TextInput
              testID="log-update-note"
              style={[styles.noteInput, { borderColor: c.border, color: c.ink }]}
              value={logNote}
              onChangeText={setLogNote}
              multiline
              numberOfLines={3}
              placeholder="Any details..."
              placeholderTextColor={c.inkMuted}
            />

            <View style={styles.modalActions}>
              <TouchableOpacity onPress={() => setLogFor(null)}>
                <Text style={{ fontSize: 14, color: c.inkMuted }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                testID="log-update-submit"
                style={[styles.logSubmitBtn, { backgroundColor: Colors.accent }]}
                onPress={submitLog}
                disabled={logBusy}
              >
                <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14 }}>{logBusy ? 'Logging...' : 'Log'}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  pageTitle: { fontSize: 22, fontWeight: '700' },
  pageSub: { fontSize: 13, marginTop: 4, marginBottom: 16 },
  columnSection: { marginBottom: 20 },
  colHeader: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 },
  colTitle: { fontSize: 12, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
  trackerCard: { borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 8 },
  cardActions: { flexDirection: 'row', gap: 8, marginTop: 8 },
  smallBtn: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 10, paddingVertical: 4 },
  emptyBox: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 12, padding: 32, alignItems: 'center' },
  modalBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'center', padding: 20 },
  modalCard: { borderRadius: 12, padding: 20 },
  eventOptions: { gap: 6, marginTop: 8 },
  eventBtn: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  noteInput: { borderWidth: 1, borderRadius: 8, padding: 10, marginTop: 8, minHeight: 60, textAlignVertical: 'top' },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: 16, marginTop: 16 },
  logSubmitBtn: { paddingHorizontal: 20, paddingVertical: 10, borderRadius: 8 },
});
