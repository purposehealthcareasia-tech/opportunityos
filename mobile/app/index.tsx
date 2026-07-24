import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '../src/lib/theme';
import { useAuth } from '../src/lib/auth';

function Pillar({ icon, title, body }: { icon: string; title: string; body: string }) {
  const c = Colors.light;
  return (
    <View style={[styles.pillar, { backgroundColor: c.card, borderColor: c.border }]}>
      <View style={[styles.iconBox, { borderColor: c.border }]}>
        <Ionicons name={icon as any} size={16} color={Colors.accent} />
      </View>
      <Text style={[styles.pillarTitle, { color: c.ink }]}>{title}</Text>
      <Text style={[styles.pillarBody, { color: c.inkMuted }]}>{body}</Text>
    </View>
  );
}

export default function LandingScreen() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const c = Colors.light;

  React.useEffect(() => {
    if (!loading && user) {
      router.replace('/(tabs)/feed');
    }
  }, [user, loading]);

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.header}>
          <View style={styles.logoRow}>
            <View style={styles.logoBox}>
              <Text style={styles.logoLetter}>O</Text>
            </View>
            <Text style={[styles.logoName, { color: c.ink }]}>OpportunityOS</Text>
          </View>
        </View>

        <View style={styles.hero}>
          <View style={[styles.badge, { backgroundColor: Colors.accentLight, borderColor: Colors.accentBorder }]}>
            <Text style={{ color: Colors.accent, fontSize: 12, fontWeight: '600' }}>Candidate-fiduciary · Consent-first</Text>
          </View>
          <Text style={[styles.heroTitle, { color: c.ink }]}>
            Apply to the right jobs with applications employers can trust
          </Text>
          <Text style={[styles.heroAccent, { color: Colors.accent }]}>— and see the receipts.</Text>
          <Text style={[styles.heroSub, { color: c.inkMuted }]}>
            Optimized for qualified interviews, not application volume. Your Career Passport is the only factual source of truth.
          </Text>

          <View style={styles.buttonRow}>
            <TouchableOpacity
              testID="get-started-btn"
              style={[styles.primaryBtn, { backgroundColor: Colors.accent }]}
              onPress={() => router.push('/signup')}
            >
              <Text style={styles.primaryBtnText}>Create your account</Text>
              <Ionicons name="arrow-forward" size={16} color="#FFF" />
            </TouchableOpacity>
            <TouchableOpacity
              testID="sign-in-btn"
              style={[styles.secondaryBtn, { borderColor: c.border }]}
              onPress={() => router.push('/login')}
            >
              <Text style={[styles.secondaryBtnText, { color: c.ink }]}>I already have one</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.pillars}>
          <Pillar
            icon="shield-checkmark-outline"
            title="Career Passport, approved by you"
            body="Every claim — skills, projects, education, employment — is stored, versioned, and approved by you before it ever leaves your account."
          />
          <Pillar
            icon="document-text-outline"
            title="Grounded materials, no fabrication"
            body="When materials are drafted for you, they are grounded strictly in your approved Passport. If we can't ground a sentence in a claim, we won't write it."
          />
          <Pillar
            icon="list-outline"
            title="Consent ledger you can audit"
            body="Every grant and revoke is a row in an append-only ledger. Revoke a scope and dependent features stop working immediately."
          />
        </View>

        <View style={[styles.neverCard, { backgroundColor: c.card, borderColor: c.border }]}>
          <View style={styles.neverHeader}>
            <Ionicons name="lock-closed-outline" size={18} color={Colors.accent} />
            <Text style={[styles.neverTitle, { color: c.ink }]}>What we never do</Text>
          </View>
          <Text style={[styles.neverSub, { color: c.inkMuted }]}>
            Operational rules, not marketing copy.
          </Text>
          {[
            'We never scrape employer sites or bypass their terms of service.',
            'We never ask for your account passwords.',
            'We never invent facts or embellish your background.',
            'We never auto-submit without your explicit approval.',
          ].map((item, i) => (
            <View key={i} style={styles.neverItem}>
              <Ionicons name="close-circle-outline" size={16} color="#EF4444" />
              <Text style={[styles.neverItemText, { color: c.ink }]}>{item}</Text>
            </View>
          ))}
        </View>

        <View style={styles.footer}>
          <Text style={{ fontSize: 11, color: c.inkMuted }}>OpportunityOS · v0.1</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  scroll: { paddingHorizontal: 20, paddingBottom: 40 },
  header: { paddingVertical: 16 },
  logoRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  logoBox: { width: 28, height: 28, borderRadius: 6, backgroundColor: '#1E293B', alignItems: 'center', justifyContent: 'center' },
  logoLetter: { color: '#FFF', fontWeight: '700', fontSize: 13 },
  logoName: { fontWeight: '600', fontSize: 16 },
  hero: { paddingTop: 20, paddingBottom: 32 },
  badge: { alignSelf: 'flex-start', borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 4, marginBottom: 16 },
  heroTitle: { fontSize: 30, fontWeight: '700', lineHeight: 36 },
  heroAccent: { fontSize: 30, fontWeight: '700', lineHeight: 36, marginTop: 4 },
  heroSub: { fontSize: 15, lineHeight: 22, marginTop: 12 },
  buttonRow: { flexDirection: 'column', gap: 12, marginTop: 24 },
  primaryBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 14, borderRadius: 10 },
  primaryBtnText: { color: '#FFF', fontWeight: '600', fontSize: 16 },
  secondaryBtn: { borderWidth: 1, paddingVertical: 14, borderRadius: 10, alignItems: 'center' },
  secondaryBtnText: { fontWeight: '500', fontSize: 16 },
  pillars: { gap: 12, marginBottom: 24 },
  pillar: { borderWidth: 1, borderRadius: 12, padding: 16 },
  iconBox: { width: 36, height: 36, borderRadius: 8, borderWidth: 1, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  pillarTitle: { fontSize: 15, fontWeight: '600', marginBottom: 6 },
  pillarBody: { fontSize: 13, lineHeight: 19 },
  neverCard: { borderWidth: 1, borderRadius: 12, padding: 20, marginBottom: 24 },
  neverHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  neverTitle: { fontSize: 18, fontWeight: '600' },
  neverSub: { fontSize: 13, marginBottom: 16 },
  neverItem: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, marginBottom: 12 },
  neverItemText: { fontSize: 14, lineHeight: 20, flex: 1 },
  footer: { paddingVertical: 20, borderTopWidth: 1, borderTopColor: '#E2E8F0', alignItems: 'center' },
});
