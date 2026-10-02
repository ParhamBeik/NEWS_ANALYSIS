/**
 * App-wide settings: language and API base URL (AsyncStorage), staff token (SecureStore,
 * never AsyncStorage: it is a full-access credential with no expiry).
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Lang } from "./jalali";

const SETTINGS_KEY = "ni:settings";
const TOKEN_KEY = "ni_token";
export const DEFAULT_API_BASE: string =
  (Constants.expoConfig?.extra?.apiBase as string | undefined) || "https://news.parhambm.ir";

type Settings = {
  ready: boolean;
  lang: Lang;
  apiBase: string;
  token: string | null;
  setLang: (lang: Lang) => void;
  setApiBase: (url: string) => void;
  setToken: (token: string | null) => Promise<void>;
  tr: (en: string, fa: string) => string;
};

const Context = createContext<Settings | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [lang, setLangState] = useState<Lang>("fa");
  const [apiBase, setApiBaseState] = useState(DEFAULT_API_BASE);
  const [token, setTokenState] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const stored = JSON.parse((await AsyncStorage.getItem(SETTINGS_KEY)) || "{}");
        if (stored.lang === "en" || stored.lang === "fa") setLangState(stored.lang);
        if (typeof stored.apiBase === "string" && /^https?:\/\//.test(stored.apiBase)) setApiBaseState(stored.apiBase);
        setTokenState(await SecureStore.getItemAsync(TOKEN_KEY));
      } catch {
        // defaults stand
      }
      setReady(true);
    })();
  }, []);

  const persist = useCallback((next: { lang: Lang; apiBase: string }) => {
    AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(next)).catch(() => {});
  }, []);

  const value = useMemo<Settings>(() => ({
    ready,
    lang,
    apiBase,
    token,
    setLang: (next) => { setLangState(next); persist({ lang: next, apiBase }); },
    setApiBase: (url) => {
      const clean = url.trim().replace(/\/+$/, "") || DEFAULT_API_BASE;
      setApiBaseState(clean);
      persist({ lang, apiBase: clean });
    },
    setToken: async (next) => {
      if (next) await SecureStore.setItemAsync(TOKEN_KEY, next);
      else await SecureStore.deleteItemAsync(TOKEN_KEY);
      setTokenState(next);
    },
    tr: (en, fa) => (lang === "fa" ? fa : en),
  }), [ready, lang, apiBase, token, persist]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSettings(): Settings {
  const value = useContext(Context);
  if (!value) throw new Error("useSettings outside SettingsProvider");
  return value;
}
