/**
 * Concrete push providers. Keys come from app.json `expo.extra.push`; see mobile/README.md.
 *
 * TODO(accounts phase): send the returned token to the backend. There is no device-token
 * endpoint yet (AlertSubscription stores browser Web Push only), so the token is shown in
 * Settings and not uploaded.
 */
import Constants from "expo-constants";
import { Platform } from "react-native";
import { configuredProviders, registerForPush, type PushConfig, type PushProvider, type ProviderName } from "./registry";

export function pushConfig(): PushConfig {
  return (Constants.expoConfig?.extra?.push as PushConfig | undefined) || {};
}

const fcm: PushProvider = {
  name: "fcm",
  // Also needs android.googleServicesFile in app.json; `enabled` is the owner's switch.
  isConfigured: (config) => config.fcm?.enabled === true && Platform.OS === "android",
  async register() {
    // Loaded lazily: expo-notifications warns at import time in Expo Go.
    const Notifications = await import("expo-notifications");
    const { status } = await Notifications.requestPermissionsAsync();
    if (status !== "granted") return null;
    const token = await Notifications.getDevicePushTokenAsync();
    return typeof token.data === "string" ? token.data : null;
  },
};

/** Pushe and Najva ship native Android SDKs with no Expo module yet. Until one is added as a
 *  config plugin, a configured key logs once and registers nothing. */
function nativeOnly(name: ProviderName, configured: (config: PushConfig) => boolean): PushProvider {
  return {
    name,
    isConfigured: configured,
    async register() {
      console.warn(`[push] ${name} keys are set but its native SDK is not linked in this build`);
      return null;
    },
  };
}

export const PROVIDERS: Record<ProviderName, PushProvider> = {
  fcm,
  pushe: nativeOnly("pushe", (config) => Boolean(config.pushe?.appId)),
  najva: nativeOnly("najva", (config) => Boolean(config.najva?.apiKey && config.najva?.websiteId)),
};

export const register = () => registerForPush(pushConfig(), PROVIDERS);
export const enabledProviders = () => configuredProviders(pushConfig(), PROVIDERS);
