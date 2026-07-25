# Fynd Mobile — Build Notes

## EAS Build Configuration

### iOS image pin — DELIBERATE OVERRIDE, UNVERIFIED

`eas.json` pins `ios.image` to `macos-sequoia-15.6-xcode-26.0` in both
`production` and `preview` profiles. This is a **deliberate override** of the
SDK 52 default (`macos-sequoia-15.3-xcode-16.2`, alias `sdk-52`).

**Why:** The default image ships Xcode 16.2. Apple requires Xcode 26+ for all
App Store submissions since 28 Apr 2026. A build with the SDK 52 default image
would compile but be **rejected by App Store Connect**.

**Risk:** React Native 0.76.9 on Xcode 26 is **UNVERIFIED**. Known plausible
failure modes:

- `eas-cli#2988` — SDK 52 / RN 0.76.9 local builds report
  `-index-store-path` failures with Xcode 16.3+.
- `react-native#53966` — ReactCodegen broken on Xcode 26 even for
  RN 0.81 / 0.83 (may affect 0.76.9 as well).

The primary Xcode 16.3 blocker (RCT-Folly `std::char_traits<unsigned char>`
LLVM 19 failure) **is** fixed in RN 0.76.9 (React Native PR #50431, merged
3 Apr 2025). However, Xcode 26.0 may introduce additional breakage beyond
the Folly issue.

**If the iOS build fails:** The fallback is to upgrade to Expo SDK 54 (see
upgrade estimate below), which is officially supported on
`macos-sequoia-15.6-xcode-26.0`.

### Android targetSdkVersion — 36

`app.json` configures `expo-build-properties` to set
`android.compileSdkVersion: 36` and `android.targetSdkVersion: 36`.

Google Play requires new apps to target API 36 (Android 16) from 31 Aug 2026.
This override was **empirically verified**: `npx expo prebuild --platform android`
followed by `./gradlew :app:tasks` and `./gradlew assembleRelease --dry-run` both
completed with `BUILD SUCCESSFUL` (AGP 8.6.0, Gradle 8.10.2, JDK 17).

Android can ship on SDK 52 independently of the iOS lane.

### android.versionCode policy

`app.json` sets `android.versionCode: 1` explicitly with
`cli.appVersionSource: "local"` in `eas.json`.

**Upload #2:** Manually bump `android.versionCode` to `2` in `app.json` before
the second EAS build. Google Play requires strictly increasing versionCode.
Alternative: switch to `appVersionSource: "remote"` with `autoIncrement: true`
for automation (founder decision).

### SDK 52 EAS support status

As of July 2026, `sdk-52` is still listed on
[docs.expo.dev/build-reference/infrastructure](https://docs.expo.dev/build-reference/infrastructure/).
SDK 52 was released Nov 2024 (~20 months ago). Expo's stated lifetime is
approximately one year per SDK release. The alias could be removed at any time.

### SDK 54 upgrade fallback estimate

If the iOS build fails on Xcode 26 with SDK 52, upgrading to SDK 54 is the
recommended path. Estimated effort: **4–8 hours**.

Major version changes:

| Dependency | SDK 52 | SDK 54 |
|------------|--------|--------|
| react | 18.3.1 | 19.1.0 |
| react-native | 0.76.9 | 0.81.5 |
| expo-router | ~4.0.0 | ~6.0.3 |
| react-native-reanimated | ~3.16.0 | ~4.1.0 |
| react-native-safe-area-context | 4.12.0 | ~5.6.0 |

Key migration items: React 18→19 (hooks-based code is largely compatible),
expo-router v4→v6 (auth-guard redirect patterns need testing), reanimated
v3→v4 (transitive dep only in this project). No hand-porting identified — all
changes are version bumps with documented migration paths.
