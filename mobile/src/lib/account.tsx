/**
 * The signed-in reader's account (watchlist, dial, quiet hours, unread count), shared by
 * every screen. It follows the token in SettingsProvider: phone sign-in and staff sign-in
 * both just set the token, and this provider loads the account and registers the device.
 *
 * Offline, the last account is read from the 48 h cache so the radar keeps its watchlist
 * badges. Sign-out and deletion drop the cached rows: they are personal data.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { register, watchTokenChanges } from "../push";
import { forgetDevice, syncDevice } from "../push/device";
import { ApiError, deleteAccount, fetchAccount, logout, type Account } from "./api";
import { ACCOUNT_KEY, INBOX_KEY, load, remove, save } from "./cache";
import { useSettings } from "./settings";

type AccountState = {
  account: Account | null;
  /** True while the shown account came from the cache because the server was unreachable. */
  offline: boolean;
  refresh: () => Promise<void>;
  setAccount: (account: Account) => void;
  signOut: () => Promise<void>;
  destroy: () => Promise<void>;
};

const Context = createContext<AccountState | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const { apiBase, token, setToken } = useSettings();
  const [account, setAccountState] = useState<Account | null>(null);
  const [offline, setOffline] = useState(false);

  const forget = useCallback(async () => {
    await remove(ACCOUNT_KEY, INBOX_KEY).catch(() => {});
    setAccountState(null);
    setOffline(false);
    await setToken(null);
  }, [setToken]);

  const setAccount = useCallback((next: Account) => {
    setAccountState(next);
    setOffline(false);
    save(ACCOUNT_KEY, next).catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    if (!token) { setAccountState(null); return; }
    try {
      setAccount(await fetchAccount(apiBase, token));
    } catch (err) {
      // A revoked or deleted token: drop it, as the web does on a 401.
      if (err instanceof ApiError && err.status === 401) { await forget(); return; }
      const cached = await load<Account>(ACCOUNT_KEY).catch(() => null);
      if (cached) setAccountState(cached.data);
      setOffline(true);
    }
  }, [apiBase, token, setAccount, forget]);

  useEffect(() => { refresh(); }, [refresh]);

  // Device registration: on sign-in / start, and again whenever the push token rotates.
  // Without provider keys register() resolves null and syncDevice sends nothing.
  useEffect(() => {
    if (!token) return;
    let stop = () => {};
    let live = true;
    register().then((registration) => syncDevice(apiBase, token, registration)).catch(() => {});
    watchTokenChanges((registration) => { syncDevice(apiBase, token, registration).catch(() => {}); })
      .then((unsubscribe) => { if (live) stop = unsubscribe; else unsubscribe(); })
      .catch(() => {});
    return () => { live = false; stop(); };
  }, [apiBase, token]);

  const value = useMemo<AccountState>(() => ({
    account,
    offline,
    refresh,
    setAccount,
    signOut: async () => {
      await forgetDevice(apiBase, token).catch(() => {});
      if (token) await logout(apiBase, token).catch(() => {}); // revoke server-side; drop locally regardless
      await forget();
    },
    destroy: async () => {
      if (!token) return;
      await deleteAccount(apiBase, token); // throws: the screen says it failed and nothing is dropped
      await forgetDevice(apiBase, null); // the server already deleted the device rows
      await forget();
    },
  }), [account, offline, refresh, setAccount, apiBase, token, forget]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAccount(): AccountState {
  const value = useContext(Context);
  if (!value) throw new Error("useAccount outside AccountProvider");
  return value;
}
