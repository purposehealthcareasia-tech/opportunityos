import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../src/lib/theme';
import { useAuth } from '../src/lib/auth';
import { api } from '../src/lib/api';
import { CONSENT_SCOPES_FALLBACK, POLICY_TEXT_VERSION_FALLBACK } from '../src/lib/consentScopes';
import Input from '../src/components/Input';
import Button from '../src/components/Button';
import Checkbox from '../src/components/Checkbox';

export default function SignupScreen() {
  const router = useRouter();
  const { signup, user, loading: authLoading } = useAuth();
  const [scopes, setScopes] = useState(CONSENT_SCOPES_FALLBACK);
  const [policyVersion, setPolicyVersion] = useState(POLICY_TEXT_VERSION_FALLBACK);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [consents, setConsents] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const c = Colors.light;

  // Redirect if already authenticated
  React.useEffect(() => {
    if (!authLoading && user) {
      router.replace('/(tabs)/feed');
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get('/api/v1/meta/policy');
        if (Array.isArray(data.scopes)) setScopes(data.scopes);
        if (data.policy_text_version) setPolicyVersion(data.policy_text_version);
      } catch {}
    })();
  }, []);

  const requiredScopes = useMemo(() => scopes.filter((s) => s.required).map((s) => s.scope), [scopes]);
  const canSubmit = useMemo(() => {
    if (!name.trim() || !email.trim() || password.length < 8) return false;
    return requiredScopes.every((s) => consents[s]);
  }, [name, email, password, consents, requiredScopes]);

  async function handleSignup() {
    setError('');
    const payload = scopes.reduce((acc, s) => ({ ...acc, [s.scope]: !!consents[s.scope] }), {} as Record<string, boolean>);
    setSubmitting(true);
    try {
      await signup({
        email: email.trim().toLowerCase(),
        password,
        name: name.trim(),
        consents: payload,
        policy_text_version: policyVersion,
      });
      router.replace('/(tabs)/passport');
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (typeof detail === 'string') setError(detail);
      else if (detail?.error === 'required_consent_missing') setError(`Consent to "${detail.scope}" is required.`);
      else setError('Could not create your account. Please check your details.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <TouchableOpacity
            testID="signup-back-btn"
            style={styles.backRow}
            onPress={() => router.back()}
          >
            <Ionicons name="arrow-back" size={18} color={c.ink} />
            <Text style={{ color: c.ink, fontSize: 14 }}>Back to home</Text>
          </TouchableOpacity>

          <View style={styles.content}>
            <Text style={[styles.title, { color: c.ink }]}>Create your account</Text>
            <Text style={[styles.subtitle, { color: c.inkMuted }]}>
              You control what Fynd does on your behalf. Each scope is a promise about how your data is used.
            </Text>

            <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
              <Input label="Full name" value={name} onChangeText={setName} placeholder="e.g. Ujjwal Singla" autoComplete="name" testID="signup-name-input" />
              <View style={{ height: 12 }} />
              <Input label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" placeholder="you@work.com" autoComplete="email" testID="signup-email-input" />
              <View style={{ height: 12 }} />
              <Input label="Password" value={password} onChangeText={setPassword} secureTextEntry placeholder="At least 8 characters" hint="At least 8 characters." autoComplete="password-new" testID="signup-password-input" />

              <View style={styles.scopeSection}>
                <View style={styles.scopeHeader}>
                  <Text style={[styles.scopeTitle, { color: c.ink }]}>Consent scopes</Text>
                  <Text style={{ fontSize: 11, color: c.inkMuted }}>Policy v{policyVersion}</Text>
                </View>
                <Text style={{ fontSize: 12, color: c.inkMuted, marginBottom: 12 }}>
                  None are pre-checked. Revoke any time in Settings.
                </Text>
                {scopes.map((s) => (
                  <Checkbox
                    key={s.scope}
                    checked={!!consents[s.scope]}
                    onChange={(v) => setConsents((prev) => ({ ...prev, [s.scope]: v }))}
                    label={s.label}
                    description={s.description}
                    required={s.required}
                  />
                ))}
              </View>

              {error !== '' && (
                <View style={[styles.errorBox, { borderColor: c.errorBorder, backgroundColor: c.errorBg }]}>
                  <Text style={{ color: c.error, fontSize: 14 }}>{error}</Text>
                </View>
              )}

              <View style={styles.actions}>
                <TouchableOpacity onPress={() => router.push('/login')}>
                  <Text style={{ fontSize: 13, color: c.inkMuted }}>
                    Already have an account? <Text style={{ fontWeight: '600', color: Colors.accent }}>Sign in</Text>
                  </Text>
                </TouchableOpacity>
                <Button
                  testID="signup-submit-btn"
                  onPress={handleSignup}
                  loading={submitting}
                  disabled={!canSubmit}
                >
                  <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 15 }}>Create account</Text>
                </Button>
              </View>
            </View>

            <Text style={{ fontSize: 12, color: c.inkMuted, marginTop: 16, lineHeight: 17 }}>
              By creating an account, you agree that Fynd will act as a candidate-fiduciary. We will never auto-submit without your explicit approval, and we will never invent facts about you.
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  scroll: { paddingHorizontal: 20, paddingBottom: 40 },
  backRow: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 16 },
  content: { paddingTop: 8 },
  title: { fontSize: 24, fontWeight: '600', marginBottom: 4 },
  subtitle: { fontSize: 14, marginBottom: 24, lineHeight: 20 },
  card: { borderWidth: 1, borderRadius: 12, padding: 20 },
  scopeSection: { marginTop: 20, paddingTop: 16, borderTopWidth: 1, borderTopColor: '#E2E8F0' },
  scopeHeader: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 },
  scopeTitle: { fontSize: 14, fontWeight: '600' },
  errorBox: { borderWidth: 1, borderRadius: 8, padding: 10, marginTop: 12 },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 20, flexWrap: 'wrap', gap: 12 },
});
