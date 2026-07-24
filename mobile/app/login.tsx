import React, { useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../src/lib/theme';
import { useAuth } from '../src/lib/auth';
import Input from '../src/components/Input';
import Button from '../src/components/Button';

export default function LoginScreen() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const c = Colors.light;

  async function handleLogin() {
    setError('');
    setSubmitting(true);
    try {
      await login({ email: email.trim().toLowerCase(), password });
      router.replace('/(tabs)/feed');
    } catch {
      setError('Email or password not recognized.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <TouchableOpacity
            testID="login-back-btn"
            style={styles.backRow}
            onPress={() => router.back()}
          >
            <Ionicons name="arrow-back" size={18} color={c.ink} />
            <Text style={{ color: c.ink, fontSize: 14 }}>Back to home</Text>
          </TouchableOpacity>

          <View style={styles.content}>
            <Text style={[styles.title, { color: c.ink }]}>Sign in</Text>
            <Text style={[styles.subtitle, { color: c.inkMuted }]}>Welcome back. Enter your email and password.</Text>

            <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
              <Input
                label="Email"
                value={email}
                onChangeText={setEmail}
                keyboardType="email-address"
                autoCapitalize="none"
                autoComplete="email"
                placeholder="you@work.com"
                testID="login-email-input"
              />
              <View style={{ height: 12 }} />
              <Input
                label="Password"
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoComplete="password"
                placeholder="Your password"
                testID="login-password-input"
              />

              {error !== '' && (
                <View testID="login-error-message" style={[styles.errorBox, { borderColor: c.errorBorder, backgroundColor: c.errorBg }]}>
                  <Text style={{ color: c.error, fontSize: 14 }}>{error}</Text>
                </View>
              )}

              <View style={styles.actions}>
                <TouchableOpacity onPress={() => router.push('/signup')}>
                  <Text style={{ fontSize: 13, color: c.inkMuted }}>
                    No account? <Text style={{ fontWeight: '600', color: Colors.accent }}>Create one</Text>
                  </Text>
                </TouchableOpacity>
                <Button
                  testID="login-submit-btn"
                  onPress={handleLogin}
                  loading={submitting}
                  disabled={!email.trim() || !password}
                >
                  <Text style={{ color: '#FFF', fontWeight: '600', fontSize: 15 }}>Sign in</Text>
                </Button>
              </View>
            </View>
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
  content: { paddingTop: 16 },
  title: { fontSize: 24, fontWeight: '600', marginBottom: 4 },
  subtitle: { fontSize: 14, marginBottom: 24 },
  card: { borderWidth: 1, borderRadius: 12, padding: 20 },
  errorBox: { borderWidth: 1, borderRadius: 8, padding: 10, marginTop: 12 },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 20 },
});
