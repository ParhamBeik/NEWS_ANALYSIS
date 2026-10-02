# News radar — Android app

Expo (React Native, TypeScript, expo-router). Android ships from this app (Bazaar, Myket,
Play); iOS uses the installable web app (PWA) at https://news.parhambm.ir.

Screens: radar (image-led cards, "on your watchlist" badge) → event detail (brief, sources,
link to the market page on the web) · phone sign-in → onboarding (≥3 watch items + alert dial)
· watchlist & alerts (dial, quiet hours) · inbox · settings (فارسی/English, server address,
account, delete account, privacy/terms on the web) · staff swipe review (staff login).

## Reader accounts

Phone sign-in uses `POST /api/auth/otp/request/` then `/api/auth/otp/verify/`, which returns
the same DRF token as staff sign-in; it is kept in expo-secure-store (`src/lib/settings.tsx`).
`src/lib/account.tsx` loads `/api/account/` whenever the token changes and registers the
device for push. Until the server has `KAVENEGAR_API_KEY` + `KAVENEGAR_OTP_TEMPLATE`, sign-in
answers `sms_unavailable` and the screen says "SMS sign-in is not available yet".

On the radar, watched events are marked and lifted 5 places (`boostWatched` in
`src/lib/reader.ts`, a port of `frontend/lib/reader.js`; keep them in step). Deleting the
account calls `DELETE /api/account/` and drops the token and cached account data.

## Run

```bash
cd mobile
npm ci
npm start            # Expo dev server; press `a` for an Android emulator, or scan with Expo Go
npm run typecheck    # tsc --noEmit
npm test             # jest: Jalali dates, tiers, offline cache, push registry
```

The app talks to `extra.apiBase` in `app.json` (default `https://news.parhambm.ir`); it can be
changed in Settings, e.g. `http://10.0.2.2:8000` for a local Django from the Android emulator.

**Server prerequisite:** the edge Caddy must route the reader API to Django. Apply the
`@mobile_api` block in `deploy/Caddyfile.snippet` to `/opt/apps/vps-edge/Caddyfile` and reload
Caddy; without it every `/api/...` call returns the Next 404 page.

## Build an APK

Local (needs Android Studio / SDK and JDK 17):

```bash
npx expo run:android --variant release   # generates android/ (git-ignored); signed with the debug key
```

Cloud (EAS, needs an Expo account):

```bash
npx eas-cli@latest build -p android --profile preview   # first run creates eas.json
```

Use an APK (`"buildType": "apk"` in the preview profile) for Bazaar/Myket; Play wants an
AAB (the default production profile). Keep the upload keystore safe: losing it means a new
package listing.

## Offline

The last radar, every opened event, and for a signed-in reader the account (watchlist) and
inbox are saved to AsyncStorage for 48 hours (`src/lib/cache.ts`) and shown with "last synced"
when the network fails. Older rows are pruned at start-up; account and inbox rows are removed
on sign-out and account deletion.

## Push notifications

`src/push/` tries providers in `extra.push.order` (FCM, then Pushe, then Najva). Each is off
until its keys exist, so today registration is a no-op.

- **FCM:** add `google-services.json` from Firebase, set `"android": {"googleServicesFile": "./google-services.json"}`
  and `extra.push.fcm.enabled: true`, then rebuild.
- **Pushe / Najva:** set `extra.push.pushe.appId` or `extra.push.najva.apiKey` + `websiteId`. Their
  native SDKs have no Expo module yet; a config plugin must be added before they can register.
- **Backend:** after sign-in, on start and whenever FCM rotates the token, `src/push/device.ts`
  posts `{kind: fcm|pushe|najva, token}` to `/api/account/devices/` (a changed token first
  deletes the old one); sign-out deletes it. With no keys nothing is registered or sent.

## Staff review

Sign in from the Review screen with a staff account. The app uses the same DRF token as the web
(`POST /api/auth/token/`), stored in the device keystore (expo-secure-store); Sign out revokes it.
