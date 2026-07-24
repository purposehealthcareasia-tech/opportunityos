import React from 'react';
import { Stack } from 'expo-router';
import { AuthProvider } from '../src/lib/auth';
import { StatusBar } from 'expo-status-bar';

export default function RootLayout() {
  return (
    <AuthProvider>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="index" />
        <Stack.Screen name="login" />
        <Stack.Screen name="signup" />
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="jobs/[jobId]" options={{ headerShown: true, title: 'Job Detail' }} />
        <Stack.Screen name="prep/[applicationId]" options={{ headerShown: true, title: 'Application Prep' }} />
        <Stack.Screen name="preferences" options={{ headerShown: true, title: 'Preferences' }} />
        <Stack.Screen name="eligibility" options={{ headerShown: true, title: 'Eligibility' }} />
        <Stack.Screen name="approvals" options={{ headerShown: true, title: 'Approvals' }} />
        <Stack.Screen name="analyticsScreen" options={{ headerShown: true, title: 'Analytics' }} />
        <Stack.Screen name="privacy" options={{ headerShown: true, title: 'Privacy' }} />
      </Stack>
    </AuthProvider>
  );
}
