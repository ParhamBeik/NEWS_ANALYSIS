/**
 * Keep the server's device row in step with this phone's push token.
 *
 * - sign-in, app start and every token change: POST /api/account/devices/ (idempotent; the
 *   server re-points an existing token at whoever signed in last). A changed token first
 *   drops the old one so the account does not keep a dead endpoint.
 * - sign-out: DELETE the stored token while the auth token still works, then forget it.
 *
 * With no provider keys there is no registration, and both calls are no-ops: nothing is sent.
 * No native imports, so it is tested with a mocked fetch.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { registerDevice, unregisterDevice } from "../lib/api";
import type { Registration } from "./registry";

const STORE_KEY = "ni:push-device";

async function stored(): Promise<Registration | null> {
  try {
    const value = JSON.parse((await AsyncStorage.getItem(STORE_KEY)) || "null");
    return value && typeof value.token === "string" && typeof value.provider === "string" ? value : null;
  } catch {
    return null;
  }
}

/** Register `registration` for the signed-in account. Returns false when there was nothing to send. */
export async function syncDevice(base: string, authToken: string, registration: Registration | null): Promise<boolean> {
  if (!registration) return false;
  const previous = await stored();
  if (previous && (previous.token !== registration.token || previous.provider !== registration.provider)) {
    await unregisterDevice(base, authToken, previous.provider, previous.token).catch(() => {});
  }
  await registerDevice(base, authToken, registration.provider, registration.token);
  await AsyncStorage.setItem(STORE_KEY, JSON.stringify(registration));
  return true;
}

/** Drop this phone's push token from the account. Best effort: sign-out must never block on it. */
export async function forgetDevice(base: string, authToken: string | null): Promise<void> {
  const previous = await stored();
  if (previous && authToken) await unregisterDevice(base, authToken, previous.provider, previous.token).catch(() => {});
  await AsyncStorage.removeItem(STORE_KEY);
}
