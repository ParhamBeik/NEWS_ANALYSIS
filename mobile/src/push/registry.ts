/**
 * Push registration across providers, tried in order: FCM first, then the Iranian
 * fallbacks (Pushe, Najva) for devices without Google Play services.
 *
 * Every provider is disabled until its keys are in app.json `expo.extra.push`; with nothing
 * configured registerForPush() is a no-op that returns null. Pure: providers are injected,
 * so this file has no native imports and is tested directly.
 */

export type ProviderName = "fcm" | "pushe" | "najva";

export type PushConfig = {
  order?: ProviderName[];
  fcm?: { enabled?: boolean };
  pushe?: { appId?: string };
  najva?: { apiKey?: string; websiteId?: string };
};

export interface PushProvider {
  name: ProviderName;
  /** True only when the keys this provider needs are present. */
  isConfigured(config: PushConfig): boolean;
  /** A device token, or null when the user declined or the SDK is unavailable. */
  register(config: PushConfig): Promise<string | null>;
}

export type Registration = { provider: ProviderName; token: string };

const DEFAULT_ORDER: ProviderName[] = ["fcm", "pushe", "najva"];

export async function registerForPush(
  config: PushConfig,
  providers: Partial<Record<ProviderName, PushProvider>>,
): Promise<Registration | null> {
  for (const name of config.order?.length ? config.order : DEFAULT_ORDER) {
    const provider = providers[name];
    if (!provider || !provider.isConfigured(config)) continue;
    try {
      const token = await provider.register(config);
      if (token) return { provider: name, token };
    } catch {
      // try the next provider
    }
  }
  return null;
}

export function configuredProviders(config: PushConfig, providers: Partial<Record<ProviderName, PushProvider>>): ProviderName[] {
  return Object.values(providers).filter((p): p is PushProvider => Boolean(p?.isConfigured(config))).map((p) => p.name);
}
