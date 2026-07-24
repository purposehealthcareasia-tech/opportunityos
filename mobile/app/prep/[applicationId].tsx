import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, ScrollView, TextInput, TouchableOpacity,
  RefreshControl, StyleSheet, KeyboardAvoidingView, Platform,
  Switch, Alert,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../../src/lib/theme';
import { api, withIdempotency } from '../../src/lib/api';
import { Card, CardHeader } from '../../src/components/Card';
import Button from '../../src/components/Button';
import { LoadingBlock, ErrorBlock } from '../../src/components/StatusBlocks';
import AuthGate from '../../src/components/AuthGate';

/* ── helpers ───────────────────────────────────────────────── */

function rlabel(code: string): string {
  const MAP: Record<string, string> = {
    empty_claim_ids: 'no claim IDs referenced',
    malformed_line: 'malformed line',
  };
  if (MAP[code]) return MAP[code];
  if (code?.startsWith('unapproved_claim:')) return `unapproved claim (${code.slice(17, 25)}…)`;
  if (code?.startsWith('number_not_in_claims:')) return `unsupported number "${code.slice(21)}"`;
  if (code?.startsWith('date_not_in_claims:')) return `unsupported year "${code.slice(19)}"`;
  if (code?.startsWith('sensitive_leak:')) return `sensitive leak (${code.slice(15)})`;
  return code;
}

const c = Colors.light;

/* ── ValidatorChip ─────────────────────────────────────────── */

function ValidatorChip({ result, outcome }: { result: any; outcome?: string }) {
  if (!result) return null;
  const passed = result.status === 'passed';
  const nRej = (result.rejected_lines || []).length;
  const nPass = (result.passed_lines || []).length;
  const color = passed ? Colors.accent : outcome === 'template_fallback' ? c.warning : c.error;
  const label = passed
    ? `${nPass} grounded · 0 unverified`
    : outcome === 'template_fallback'
    ? `AI draft failed — template (${nPass} lines)`
    : `${nRej} rejected · ${nPass} accepted`;
  const icon = passed ? 'shield-checkmark' : outcome === 'template_fallback' ? 'warning' : 'shield';
  return (
    <View testID="validator-chip" style={[styles.pill, { borderColor: color + '40' }]}>
      <Ionicons name={icon as any} size={12} color={color} />
      <Text style={{ fontSize: 10, color, marginLeft: 4 }}>{label}</Text>
    </View>
  );
}

/* ── LineRow ────────────────────────────────────────────────── */

function LineRow({ line, onAccept, onRevert, busy }: {
  line: any; onAccept: (id: string) => void; onRevert: (id: string) => void; busy: string | null;
}) {
  const status = line.status || 'proposed';
  const borderColor = status === 'accepted' ? Colors.accentBorder
    : status === 'reverted' ? c.errorBorder : c.border;
  const bg = status === 'accepted' ? Colors.accentLight
    : status === 'reverted' ? c.errorBg : 'transparent';
  return (
    <View testID={`resume-line-${line.line_id}`} style={[styles.lineCard, { borderColor, backgroundColor: bg }]}>
      <View style={styles.lineTop}>
        <Text testID={`resume-line-text-${line.line_id}`} style={[styles.lineText, { color: c.ink }]}>{line.text}</Text>
        <View style={[styles.pill, { borderColor: status === 'accepted' ? Colors.accentBorder : status === 'reverted' ? c.errorBorder : c.border }]}>
          <Text style={{ fontSize: 10, color: status === 'accepted' ? Colors.accent : status === 'reverted' ? c.error : c.inkMuted }}>{status}</Text>
        </View>
      </View>
      <Text style={styles.claimMono}>claims: {line.claim_ids?.map((id: string) => id.slice(0, 6)).join(', ') || '—'}</Text>
      <View style={styles.lineActions}>
        {status !== 'accepted' && (
          <Button size="sm" variant="secondary" onPress={() => onAccept(line.line_id)} loading={busy === line.line_id + ':accept'} testID={`resume-line-accept-${line.line_id}`}>
            <Ionicons name="checkmark-circle" size={14} color={Colors.accent} />
            <Text style={{ fontSize: 12, color: c.ink, marginLeft: 4 }}>Accept</Text>
          </Button>
        )}
        {status !== 'reverted' && (
          <Button size="sm" variant="ghost" onPress={() => onRevert(line.line_id)} loading={busy === line.line_id + ':revert'} testID={`resume-line-revert-${line.line_id}`}>
            <Ionicons name="arrow-undo" size={14} color={c.inkMuted} />
            <Text style={{ fontSize: 12, color: c.inkMuted, marginLeft: 4 }}>Revert</Text>
          </Button>
        )}
      </View>
    </View>
  );
}

/* ── ResumeTab ─────────────────────────────────────────────── */

function ResumeTab({ packet, onReload }: { packet: any; onReload: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [instruction, setInstruction] = useState('');
  const [regenLog, setRegenLog] = useState<any>(null);

  const tailored = packet.resume_version;
  const base = packet.base_resume;
  const manifest = tailored?.render_manifest || {};
  const lines = manifest.lines || [];
  const validator = manifest.validator_result;

  const act = async (lineId: string, action: string) => {
    setBusy(`${lineId}:${action}`);
    try {
      await api.post(`/api/v1/applications/${packet.application.id}/resume-lines/${lineId}`, { action }, withIdempotency());
      await onReload();
    } finally { setBusy(null); }
  };

  const regenerate = async () => {
    setBusy('regen');
    setRegenLog(null);
    try {
      const { data } = await api.post(`/api/v1/applications/${packet.application.id}/regenerate`,
        { instruction: instruction.trim() || null }, withIdempotency());
      setRegenLog({
        outcome: data.outcome,
        refusal: data.refusal,
        n_lines: data.resume_version?.render_manifest?.lines?.length || 0,
      });
      setInstruction('');
      await onReload();
    } catch (e: any) {
      setRegenLog({ outcome: 'error', error: e?.response?.data?.detail?.error || 'unknown' });
    } finally { setBusy(null); }
  };

  return (
    <View>
      {/* Regeneration card */}
      <Card testID="regenerate-card">
        <CardHeader
          title="Grounded regeneration"
          subtitle="Instructions are checked against your APPROVED claims. Requests to include facts we don't have are refused."
        />
        <TextInput
          testID="regenerate-instruction-input"
          style={[styles.textArea, { borderColor: c.border, color: c.ink }]}
          placeholder='e.g., "Emphasize simulation work"'
          placeholderTextColor={c.inkMuted}
          value={instruction}
          onChangeText={setInstruction}
          multiline
          numberOfLines={2}
        />
        <View style={{ marginTop: 8 }}>
          <Button variant="accent" onPress={regenerate} loading={busy === 'regen'} testID="regenerate-btn">
            <Ionicons name="refresh" size={14} color="#FFF" />
            <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14, marginLeft: 4 }}>Regenerate</Text>
          </Button>
        </View>
        {regenLog && (
          <View testID="regenerate-log" style={[styles.logBox, {
            borderColor: regenLog.refusal ? c.errorBorder : regenLog.outcome === 'passed' ? Colors.accentBorder : c.warningBorder,
            backgroundColor: regenLog.refusal ? c.errorBg : regenLog.outcome === 'passed' ? Colors.accentLight : c.warningBg,
          }]}>
            {regenLog.refusal ? (
              <>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <Ionicons name="ban" size={14} color={c.error} />
                  <Text style={{ fontSize: 13, fontWeight: '600', color: c.error }}>Instruction refused</Text>
                </View>
                <Text style={{ fontSize: 12, color: c.ink, marginTop: 4 }}>{regenLog.refusal.message}</Text>
                <Text style={{ fontSize: 11, color: c.inkMuted, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', marginTop: 2 }}>reason: {regenLog.refusal.reason}</Text>
              </>
            ) : (
              <Text style={{ fontSize: 12, color: c.ink }}>Outcome: {regenLog.outcome} · {regenLog.n_lines} lines</Text>
            )}
          </View>
        )}
      </Card>

      {/* Base résumé */}
      <Card>
        <CardHeader title="Base résumé" subtitle="Deterministic bullets from your approved claims." />
        {(base?.render_manifest?.lines || []).length === 0 ? (
          <Text style={{ fontSize: 13, color: c.inkMuted }}>No base yet.</Text>
        ) : (base?.render_manifest?.lines || []).map((L: any) => (
          <View key={L.line_id} style={[styles.baseLineCard, { borderColor: c.border }]}>
            <Text style={{ fontSize: 13, color: c.ink, lineHeight: 19 }}>{L.text}</Text>
            <Text style={styles.claimMono}>claims: {L.claim_ids?.map((id: string) => id.slice(0, 6)).join(', ') || '—'}</Text>
          </View>
        ))}
      </Card>

      {/* Tailored résumé */}
      <Card>
        <CardHeader title="Tailored résumé" subtitle="Every line is grounded in an approved claim. Accept the ones you want." />
        <ValidatorChip result={validator} outcome={manifest.outcome} />
        {lines.length === 0 ? (
          <Text style={{ fontSize: 13, color: c.inkMuted, marginTop: 8 }}>No tailored lines yet — tap Regenerate above.</Text>
        ) : (
          <View style={{ marginTop: 8 }}>
            {lines.map((L: any) => (
              <LineRow key={L.line_id} line={L} onAccept={(id) => act(id, 'accept')} onRevert={(id) => act(id, 'revert')} busy={busy} />
            ))}
          </View>
        )}
        {(validator?.rejected_lines || []).length > 0 && (
          <View style={[styles.rejectedBox, { borderColor: c.errorBorder, backgroundColor: c.errorBg }]}>
            <Text style={{ fontSize: 12, fontWeight: '600', color: c.error, marginBottom: 4 }}>Rejected ({validator.rejected_lines.length})</Text>
            {validator.rejected_lines.slice(0, 5).map((r: any, i: number) => (
              <Text key={`rej-${i}`} style={{ fontSize: 11, color: c.ink, marginBottom: 2 }}>
                "{(r.text || '').slice(0, 80)}…" — {r.reasons.map(rlabel).join(', ')}
              </Text>
            ))}
          </View>
        )}
      </Card>
    </View>
  );
}

/* ── ScreenerRow ───────────────────────────────────────────── */

function ScreenerRow({ q, onSave, busy }: { q: any; onSave: (qid: string, payload: any) => void; busy: string | null }) {
  const [answer, setAnswer] = useState(q.answer || '');
  const [approved, setApproved] = useState(!!q.approved);
  const [autoBusy, setAutoBusy] = useState(false);
  const isSensitive = q.sensitive;
  const isStatic = q.static_only;
  const dirty = (answer !== (q.answer || '')) || (approved !== !!q.approved);

  const generate = async () => {
    setAutoBusy(true);
    try {
      const { data } = await api.post(
        `/api/v1/applications/${q.applicationId}/screeners/${encodeURIComponent(q.question_id)}/generate`,
        {}, withIdempotency());
      if (data.generated_answer) setAnswer(data.generated_answer);
    } finally { setAutoBusy(false); }
  };

  if (isStatic) {
    return (
      <View testID={`screener-${q.question_id}-static`} style={[styles.screenerStatic, { borderColor: c.border, backgroundColor: c.surfaceMuted }]}>
        <Ionicons name="help-circle-outline" size={16} color={c.inkMuted} />
        <View style={{ flex: 1, marginLeft: 8 }}>
          <Text style={{ fontSize: 10, color: c.inkMuted, textTransform: 'uppercase', letterSpacing: 1 }}>Static · never stored</Text>
          <Text style={{ fontSize: 13, color: c.ink, marginTop: 4, lineHeight: 18 }}>{q.text}</Text>
        </View>
      </View>
    );
  }

  return (
    <View testID={`screener-${q.question_id}`} style={[styles.screenerCard, {
      borderColor: isSensitive ? c.warningBorder : c.border,
      backgroundColor: isSensitive ? c.warningBg : 'transparent',
    }]}>
      <View style={styles.screenerHeader}>
        <Text style={{ fontSize: 13, fontWeight: '500', color: c.ink, flex: 1 }}>{q.text}</Text>
        {isSensitive && (
          <View testID={`screener-${q.question_id}-sensitive-badge`} style={[styles.pill, { borderColor: c.warningBorder }]}>
            <Ionicons name="warning" size={10} color={c.warning} />
            <Text style={{ fontSize: 9, color: c.warning, marginLeft: 3 }}>sensitive</Text>
          </View>
        )}
      </View>
      <TextInput
        testID={`screener-${q.question_id}-input`}
        style={[styles.textArea, { borderColor: c.border, color: c.ink, marginTop: 8 }]}
        placeholder={isSensitive ? 'Type your answer — never AI-generated.' : 'Your answer'}
        placeholderTextColor={c.inkMuted}
        value={answer}
        onChangeText={setAnswer}
        multiline
        numberOfLines={3}
      />
      <View style={styles.screenerFooter}>
        <Text style={{ fontSize: 10, color: c.inkMuted }}>provenance: {q.provenance || '—'}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          {!isSensitive && (
            <Button size="sm" variant="ghost" onPress={generate} loading={autoBusy} testID={`screener-${q.question_id}-generate`}>
              <Ionicons name="sparkles" size={12} color={c.inkMuted} />
              <Text style={{ fontSize: 11, color: c.inkMuted, marginLeft: 3 }}>Suggest</Text>
            </Button>
          )}
          {isSensitive && (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Switch
                testID={`screener-${q.question_id}-approve`}
                value={approved}
                onValueChange={setApproved}
                trackColor={{ true: Colors.accent, false: c.border }}
                style={{ transform: [{ scaleX: 0.75 }, { scaleY: 0.75 }] }}
              />
              <Text style={{ fontSize: 10, color: c.inkMuted }}>Approved</Text>
            </View>
          )}
          <Button size="sm" variant="accent" onPress={() => onSave(q.question_id, { answer, approved })} loading={busy === q.question_id} disabled={!dirty} testID={`screener-${q.question_id}-save`}>
            <Text style={{ fontSize: 12, color: '#FFF', fontWeight: '500' }}>Save</Text>
          </Button>
        </View>
      </View>
    </View>
  );
}

/* ── ScreenersTab ──────────────────────────────────────────── */

function ScreenersTab({ packet, onReload }: { packet: any; onReload: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const questions = (packet.screeners_view?.questions || []).map((q: any) => ({ ...q, applicationId: packet.application.id }));

  const save = async (qid: string, payload: any) => {
    setBusy(qid);
    try {
      await api.post(
        `/api/v1/applications/${packet.application.id}/screeners/${encodeURIComponent(qid)}/answer`,
        { ...payload, provenance: 'user' }, withIdempotency());
      await onReload();
    } finally { setBusy(null); }
  };

  if (questions.length === 0) {
    return <Text style={{ fontSize: 13, color: c.inkMuted, padding: 16 }}>No screening questions for this application.</Text>;
  }

  return (
    <View>
      {questions.map((q: any) => <ScreenerRow key={q.question_id} q={q} onSave={save} busy={busy} />)}
    </View>
  );
}

/* ── RouteDrawer ───────────────────────────────────────────── */

function RouteDrawer({ packet, onSubmit, submitting }: { packet: any; onSubmit: () => void; submitting: boolean }) {
  const app = packet.application;
  const route = app.route || 'guided_manual';
  const alternatives = ['guided_manual', 'email_application', 'manual_queue'].filter((r: string) => r !== route);
  return (
    <View testID="route-drawer" style={[styles.routeBox, { borderColor: Colors.accentBorder, backgroundColor: Colors.accentLight }]}>
      <Text style={{ fontSize: 10, color: c.inkMuted, textTransform: 'uppercase', letterSpacing: 1 }}>Chosen route</Text>
      <Text style={{ fontSize: 18, fontWeight: '600', fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', color: c.ink }}>{route}</Text>
      <Text style={{ fontSize: 12, color: c.inkMuted, lineHeight: 17, marginTop: 4 }}>
        {app.route_rationale || 'The route the eligibility engine picked for this job.'}
      </Text>
      <Text style={{ fontSize: 11, color: c.inkMuted, marginTop: 8 }}>Alternatives: {alternatives.join(', ')}</Text>
      <View testID="platform-safety-note" style={[styles.safetyNote, { borderColor: c.warningBorder, backgroundColor: c.warningBg }]}>
        <Text style={{ fontSize: 11, color: c.warning }}>We never automate restricted platforms. You submit in your own browser — we just prepare the packet.</Text>
      </View>
      <Button variant="accent" onPress={onSubmit} loading={submitting} testID="submit-btn" style={{ marginTop: 12 }}>
        <Ionicons name="send" size={14} color="#FFF" />
        <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14, marginLeft: 4 }}>Start submit</Text>
      </Button>
    </View>
  );
}

/* ── SubmitPacketPane ──────────────────────────────────────── */

function SubmitPacketPane({ packet, submitPacket, onAttest, attesting }: {
  packet: any; submitPacket: any; onAttest: () => void; attesting: boolean;
}) {
  const lines = submitPacket.packet?.accepted_lines || [];
  const answers = submitPacket.packet?.approved_answers || [];
  const [showLines, setShowLines] = useState(false);
  const [showAnswers, setShowAnswers] = useState(false);

  return (
    <View testID="submit-packet-pane" style={[styles.submitBox, { borderColor: c.border }]}>
      <View style={styles.submitHeader}>
        <View>
          <Text style={{ fontSize: 10, color: c.inkMuted, textTransform: 'uppercase' }}>Materials hash (locked)</Text>
          <Text testID="submit-materials-hash" style={{ fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', fontSize: 12, color: c.ink }}>{submitPacket.materials_hash_short}</Text>
        </View>
        <Text style={{ fontSize: 11, color: c.inkMuted }}>
          {submitPacket.usage?.used_today ?? '?'} / {submitPacket.usage?.cap ?? '?'} today
        </Text>
      </View>

      {/* Expandable résumé lines */}
      <TouchableOpacity testID="toggle-resume-lines" onPress={() => setShowLines(!showLines)} style={styles.expandRow}>
        <Text style={{ fontSize: 12, color: c.inkMuted }}>Résumé lines ({lines.length})</Text>
        <Ionicons name={showLines ? 'chevron-up' : 'chevron-down'} size={14} color={c.inkMuted} />
      </TouchableOpacity>
      {showLines && lines.map((L: any, i: number) => (
        <Text key={L.line_id || i} style={{ fontSize: 12, color: c.ink, paddingLeft: 12, marginBottom: 4 }}>{i + 1}. {L.text}</Text>
      ))}

      {/* Expandable answers */}
      {answers.length > 0 && (
        <>
          <TouchableOpacity testID="toggle-screener-answers" onPress={() => setShowAnswers(!showAnswers)} style={styles.expandRow}>
            <Text style={{ fontSize: 12, color: c.inkMuted }}>Approved answers ({answers.length})</Text>
            <Ionicons name={showAnswers ? 'chevron-up' : 'chevron-down'} size={14} color={c.inkMuted} />
          </TouchableOpacity>
          {showAnswers && answers.map((a: any) => (
            <View key={a.question_id} style={{ paddingLeft: 12, marginBottom: 6 }}>
              <Text style={{ fontSize: 11, color: c.inkMuted }}>{a.question_id.split('#').slice(-1)[0]}</Text>
              <Text style={{ fontSize: 12, color: c.ink }}>{a.answer}</Text>
            </View>
          ))}
        </>
      )}

      <Text style={{ fontSize: 11, color: c.inkMuted, fontStyle: 'italic', marginTop: 12 }}>
        After you finish on the employer's site, tap "I submitted" to write the receipt.
      </Text>
      <Button variant="accent" onPress={onAttest} loading={attesting} testID="attest-btn" style={{ marginTop: 10 }}>
        <Ionicons name="send" size={14} color="#FFF" />
        <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14, marginLeft: 4 }}>I submitted</Text>
      </Button>
    </View>
  );
}

/* ── ReceiptCard ───────────────────────────────────────────── */

function ReceiptCard({ receipt, showTrackerLink }: { receipt: any; showTrackerLink?: boolean }) {
  const router = useRouter();
  if (!receipt) {
    return (
      <View testID="receipt-card-empty" style={[styles.receiptEmpty, { borderColor: c.border }]}>
        <Text style={{ fontSize: 12, color: c.inkMuted }}>Submitted — receipt not loaded yet.</Text>
        <TouchableOpacity onPress={() => router.push('/(tabs)/tracker')}>
          <Text style={{ fontSize: 12, color: Colors.accent, textDecorationLine: 'underline' }}>Open tracker</Text>
        </TouchableOpacity>
      </View>
    );
  }
  return (
    <View testID="receipt-card" style={[styles.receiptBox, { borderColor: Colors.accentBorder, backgroundColor: Colors.accentLight }]}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Ionicons name="checkmark-circle" size={16} color={Colors.accent} />
          <Text style={{ fontSize: 14, fontWeight: '600', color: c.ink }}>Submission receipt</Text>
        </View>
        <Text testID="receipt-hash-short" style={{ fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', fontSize: 10, color: c.inkMuted }}>{receipt.materials_hash_short}</Text>
      </View>
      <View style={styles.receiptGrid}>
        <Text style={styles.receiptLabel}>req_ref</Text>
        <Text style={styles.receiptVal}>{receipt.req_ref}</Text>
        <Text style={styles.receiptLabel}>submitted</Text>
        <Text style={styles.receiptVal}>{new Date(receipt.ts).toLocaleString()}</Text>
        <Text style={styles.receiptLabel}>route</Text>
        <Text style={styles.receiptVal}>{receipt.submit_channel}</Text>
        <Text style={styles.receiptLabel}>receipt id</Text>
        <Text style={styles.receiptVal}>{receipt.id}</Text>
      </View>
      <Text testID="receipt-duplicate-check" style={{ fontSize: 11, color: c.ink, marginTop: 6 }}>no prior application to this employer/req ✓</Text>
      {showTrackerLink && (
        <TouchableOpacity onPress={() => router.push('/(tabs)/tracker')} style={{ marginTop: 8 }}>
          <Text style={{ fontSize: 12, color: Colors.accent, textDecorationLine: 'underline' }}>Open tracker</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

/* ── SummaryTab ────────────────────────────────────────────── */

function SummaryTab({ packet, onReadyForApproval, submitBusy, onSubmit, onAttest, submitting, attesting, submitPacket, receipt, flash }: {
  packet: any; onReadyForApproval: () => void; submitBusy: boolean;
  onSubmit: () => void; onAttest: () => void; submitting: boolean;
  attesting: boolean; submitPacket: any; receipt: any; flash: any;
}) {
  const router = useRouter();
  const app = packet.application;
  const validator = packet.resume_version?.render_manifest?.validator_result;
  const nSensitiveOpen = (packet.screeners_view?.questions || []).filter((q: any) => q.sensitive && !q.approved).length;
  const canGo = app.state === 'preparing' && nSensitiveOpen === 0 && !!validator;

  return (
    <View>
      {flash && (
        <View testID="prep-flash" style={[styles.flashBox, {
          borderColor: flash.kind === 'ok' ? Colors.accentBorder : c.warningBorder,
          backgroundColor: flash.kind === 'ok' ? Colors.accentLight : c.warningBg,
        }]}>
          <Text style={{ fontSize: 13, color: flash.kind === 'ok' ? Colors.accent : c.warning }}>{flash.message}</Text>
        </View>
      )}

      <Card testID="summary-overview-card">
        <CardHeader title="Packet overview" subtitle="The materials-hash below is what the server signs when you approve." />
        <View style={styles.summaryGrid}>
          <Text style={styles.summaryLabel}>Job</Text>
          <Text style={styles.summaryVal}>{app.job_snapshot?.title} @ {app.job_snapshot?.company_name}</Text>
          <Text style={styles.summaryLabel}>Route</Text>
          <Text style={[styles.summaryVal, styles.mono]}>{app.route}</Text>
          <Text style={styles.summaryLabel}>State</Text>
          <Text testID="summary-state" style={[styles.summaryVal, styles.mono]}>{app.state}</Text>
          <Text style={styles.summaryLabel}>Résumé</Text>
          <Text style={styles.summaryVal}>{packet.resume_version ? '✓ present' : '— none'}</Text>
          <Text style={styles.summaryLabel}>Validator</Text>
          <View><ValidatorChip result={validator} outcome={packet.resume_version?.render_manifest?.outcome} /></View>
          <Text style={styles.summaryLabel}>Sensitive open</Text>
          <Text testID="summary-sensitive-open" style={styles.summaryVal}>{nSensitiveOpen}</Text>
        </View>
      </Card>

      {app.state === 'preparing' && (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 8 }}>
          <Button variant="accent" onPress={onReadyForApproval} loading={submitBusy} disabled={!canGo} testID="ready-for-approval-btn">
            <Ionicons name="send" size={14} color="#FFF" />
            <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14, marginLeft: 4 }}>Ready for approval</Text>
          </Button>
          {!canGo && <Text style={{ fontSize: 11, color: c.inkMuted, flex: 1 }}>Fill and approve every sensitive screener first.</Text>}
        </View>
      )}

      {app.state === 'awaiting_approval' && (
        <View testID="summary-await-approval" style={[styles.awaitBox, { borderColor: Colors.accentBorder, backgroundColor: Colors.accentLight }]}>
          <Text style={{ fontSize: 14, fontWeight: '600', color: c.ink }}>Awaiting your approval.</Text>
          <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 4 }}>Approving locks the materials to a 72-hour authorization scope.</Text>
          <TouchableOpacity onPress={() => router.push('/approvals')} style={{ marginTop: 8 }}>
            <Text style={{ fontSize: 12, color: Colors.accent, textDecorationLine: 'underline' }}>Go to Approvals</Text>
          </TouchableOpacity>
        </View>
      )}

      {app.state === 'approved' && (
        <RouteDrawer packet={packet} onSubmit={onSubmit} submitting={submitting} />
      )}

      {app.state === 'submitting' && submitPacket && (
        <SubmitPacketPane packet={packet} submitPacket={submitPacket} onAttest={onAttest} attesting={attesting} />
      )}

      {app.state === 'submitted' && (
        <ReceiptCard receipt={receipt} />
      )}

      {['response', 'interview', 'offer', 'closed'].includes(app.state) && (
        <ReceiptCard receipt={receipt} showTrackerLink />
      )}
    </View>
  );
}

/* ── Main page ─────────────────────────────────────────────── */

export default function ApplicationPrepScreen() {
  return <AuthGate><PrepContent /></AuthGate>;
}

function PrepContent() {
  const { applicationId } = useLocalSearchParams<{ applicationId: string }>();
  const router = useRouter();
  const [packet, setPacket] = useState<any>(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('resume');
  const [submitBusy, setSubmitBusy] = useState(false);
  const [prepBusy, setPrepBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [attesting, setAttesting] = useState(false);
  const [submitPacket, setSubmitPacket] = useState<any>(null);
  const [receipt, setReceipt] = useState<any>(null);
  const [flash, setFlash] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [{ data: p }, { data: s }] = await Promise.all([
        api.get(`/api/v1/applications/${applicationId}/prep`),
        api.get(`/api/v1/applications/${applicationId}/screeners`),
      ]);
      setPacket({ ...p, screeners_view: s });
      if (['submitted', 'response', 'interview', 'offer', 'closed'].includes(p.application?.state)) {
        try {
          const r = await api.get(`/api/v1/applications/${applicationId}/receipt`);
          setReceipt(r.data);
        } catch { /* receipt may not exist yet */ }
      }
      setError('');
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') setError('generate_materials consent is required to prepare an application.');
      else if (detail === 'application_not_found') setError('Application not found.');
      else setError('Could not load application.');
    } finally {
      setRefreshing(false);
    }
  }, [applicationId]);

  useEffect(() => { load(); }, [load]);

  const triggerPrepare = async () => {
    setPrepBusy(true);
    try {
      await api.post(`/api/v1/applications/${applicationId}/prepare`, {}, withIdempotency());
      await load();
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') setError('generate_materials consent is required.');
      else setError('Prepare failed.');
    } finally { setPrepBusy(false); }
  };

  const ready = async () => {
    setSubmitBusy(true);
    try {
      await api.post(`/api/v1/applications/${applicationId}/ready-for-approval`, {}, withIdempotency());
      await load();
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'sensitive_screener_gate') setFlash({ kind: 'warn', message: d.message });
      else if (d?.error === 'state_precondition_failed') setFlash({ kind: 'warn', message: 'State changed elsewhere.' });
      else setFlash({ kind: 'warn', message: 'Ready-for-approval failed.' });
    } finally { setSubmitBusy(false); }
  };

  const submitApp = async () => {
    setSubmitting(true);
    try {
      const res = await api.post(`/api/v1/applications/${applicationId}/submit`, {}, withIdempotency());
      setSubmitPacket(res.data);
      await load();
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'duplicate_application' && d?.prior_receipt) {
        setReceipt(d.prior_receipt);
        setFlash({ kind: 'warn', message: `Already submitted on ${new Date(d.prior_receipt.ts).toLocaleString()}.` });
      } else {
        setFlash({ kind: 'warn', message: d?.message || d?.error || 'Submit failed.' });
      }
    } finally { setSubmitting(false); }
  };

  const attest = async () => {
    setAttesting(true);
    try {
      const res = await api.post(`/api/v1/applications/${applicationId}/attest`, { confirm_method: 'user_attest' }, withIdempotency());
      setReceipt(res.data.receipt);
      setSubmitPacket(null);
      setFlash({ kind: 'ok', message: 'Receipt written. Duplicate check: clean.' });
      await load();
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      setFlash({ kind: 'warn', message: d?.message || d?.error || 'Attest failed.' });
    } finally { setAttesting(false); }
  };

  if (error && !packet) return (
    <View style={[styles.container, { backgroundColor: c.bg }]}>
      <View style={styles.scrollContent}>
        <ErrorBlock message={error} onRetry={load} />
        <TouchableOpacity testID="back-to-applications" onPress={() => router.push('/(tabs)/applications')} style={{ marginTop: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
            <Ionicons name="arrow-back" size={14} color={c.inkMuted} />
            <Text style={{ fontSize: 13, color: c.inkMuted, textDecorationLine: 'underline' }}>Back to applications</Text>
          </View>
        </TouchableOpacity>
      </View>
    </View>
  );

  if (!packet) return <View style={[styles.container, { backgroundColor: c.bg }]}><LoadingBlock label="Loading prep packet…" /></View>;

  const app = packet.application;
  const validator = packet.resume_version?.render_manifest?.validator_result;
  const isSample = !!app.job_snapshot?.is_sample;
  const needsPrepare = app.state === 'shortlisted' || !packet.resume_version;

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
      <ScrollView
        testID="application-prep-page"
        style={[styles.container, { backgroundColor: c.bg }]}
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.accent} />}
      >
        {/* Header */}
        <TouchableOpacity testID="prep-back-btn" onPress={() => router.push('/(tabs)/applications')} style={styles.backRow}>
          <Ionicons name="arrow-back" size={14} color={c.inkMuted} />
          <Text style={{ fontSize: 12, color: c.inkMuted }}>Back to Applications</Text>
        </TouchableOpacity>

        <View style={styles.headerRow}>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <Ionicons name="document-text" size={18} color={c.ink} />
              <Text style={[styles.pageTitle, { color: c.ink }]} numberOfLines={2}>{app.job_snapshot?.title}</Text>
              {isSample && (
                <View testID="sample-badge" style={[styles.pill, { backgroundColor: '#FEF3C7', borderColor: '#F59E0B40' }]}>
                  <Ionicons name="flask" size={10} color="#D97706" />
                  <Text style={{ fontSize: 9, color: '#D97706', fontWeight: '600', marginLeft: 3 }}>SAMPLE</Text>
                </View>
              )}
            </View>
            <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 4 }}>
              {app.job_snapshot?.company_name} · {app.state} · {app.route}
            </Text>
          </View>
          <ValidatorChip result={validator} outcome={packet.resume_version?.render_manifest?.outcome} />
        </View>

        {/* Prepare button (shortlisted / no resume) */}
        {needsPrepare && (
          <Card testID="prepare-card">
            <CardHeader title="Prepare this application" subtitle="We tailor your résumé using ONLY your approved Career Passport claims. Validator will reject any AI line that references facts you don't actually have." />
            <Button variant="accent" onPress={triggerPrepare} loading={prepBusy} testID="prepare-btn">
              <Ionicons name="sparkles" size={14} color="#FFF" />
              <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 14, marginLeft: 4 }}>Prepare packet</Text>
            </Button>
          </Card>
        )}

        {/* Tab bar + content */}
        {!needsPrepare && (
          <>
            <View style={[styles.tabBar, { borderBottomColor: c.border }]}>
              {['resume', 'screeners', 'summary'].map((k) => (
                <TouchableOpacity
                  key={k}
                  testID={`prep-tab-${k}`}
                  onPress={() => setTab(k)}
                  style={[styles.tabBtn, { borderBottomColor: tab === k ? Colors.accent : 'transparent' }]}
                >
                  <Text style={{ fontSize: 14, color: tab === k ? Colors.accent : c.inkMuted, fontWeight: tab === k ? '600' : '400' }}>
                    {k[0].toUpperCase() + k.slice(1)}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {tab === 'resume' && <ResumeTab packet={packet} onReload={load} />}
            {tab === 'screeners' && <ScreenersTab packet={packet} onReload={load} />}
            {tab === 'summary' && (
              <SummaryTab
                packet={packet}
                onReadyForApproval={ready}
                submitBusy={submitBusy}
                onSubmit={submitApp}
                onAttest={attest}
                submitting={submitting}
                attesting={attesting}
                submitPacket={submitPacket}
                receipt={receipt}
                flash={flash}
              />
            )}
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

/* ── styles ────────────────────────────────────────────────── */

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  backRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 12 },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 },
  pageTitle: { fontSize: 20, fontWeight: '700' },
  pill: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 3 },
  tabBar: { flexDirection: 'row', borderBottomWidth: 1, marginBottom: 16 },
  tabBtn: { paddingVertical: 10, paddingHorizontal: 16, borderBottomWidth: 2, marginBottom: -1 },
  lineCard: { borderWidth: 1, borderRadius: 8, padding: 12, marginBottom: 8 },
  lineTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 },
  lineText: { fontSize: 13, lineHeight: 19, flex: 1 },
  lineActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8, marginTop: 8 },
  claimMono: { fontSize: 9, color: Colors.light.inkMuted, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', marginTop: 4 },
  baseLineCard: { borderWidth: 1, borderRadius: 8, padding: 12, marginBottom: 6 },
  textArea: { borderWidth: 1, borderRadius: 8, padding: 12, fontSize: 14, textAlignVertical: 'top', minHeight: 60 },
  logBox: { borderWidth: 1, borderRadius: 8, padding: 12, marginTop: 12 },
  rejectedBox: { borderWidth: 1, borderRadius: 8, padding: 12, marginTop: 12 },
  screenerCard: { borderWidth: 1, borderRadius: 8, padding: 14, marginBottom: 10 },
  screenerStatic: { borderWidth: 1, borderRadius: 8, padding: 14, marginBottom: 10, flexDirection: 'row', alignItems: 'flex-start' },
  screenerHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 },
  screenerFooter: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 10, flexWrap: 'wrap', gap: 8 },
  summaryGrid: { marginTop: 8 },
  summaryLabel: { fontSize: 12, color: Colors.light.inkMuted, marginTop: 6 },
  summaryVal: { fontSize: 13, color: Colors.light.ink },
  mono: { fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  routeBox: { borderWidth: 1, borderRadius: 10, padding: 16, marginTop: 12 },
  safetyNote: { borderWidth: 1, borderRadius: 8, padding: 10, marginTop: 10 },
  awaitBox: { borderWidth: 1, borderRadius: 10, padding: 16, marginTop: 12 },
  submitBox: { borderWidth: 1, borderRadius: 10, padding: 16, marginTop: 12 },
  submitHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 },
  expandRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: Colors.light.border },
  receiptEmpty: { borderWidth: 1, borderRadius: 8, padding: 12, marginTop: 12, flexDirection: 'row', alignItems: 'center', gap: 8 },
  receiptBox: { borderWidth: 1, borderRadius: 10, padding: 16, marginTop: 12 },
  receiptGrid: { marginTop: 8 },
  receiptLabel: { fontSize: 11, color: Colors.light.inkMuted, marginTop: 4 },
  receiptVal: { fontSize: 12, color: Colors.light.ink, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  flashBox: { borderWidth: 1, borderRadius: 8, padding: 12, marginBottom: 12 },
});
