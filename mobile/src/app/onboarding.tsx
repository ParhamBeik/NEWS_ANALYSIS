/**
 * First run after phone sign-in: pick at least three watch items and an alert dial. Same
 * rules as the web /onboarding; the server enforces the minimum again.
 */
import { Redirect, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, View } from "react-native";
import { DialPicker, WatchPicker } from "../components/watch";
import { Button, Txt } from "../components/ui";
import { ApiError, fetchWatchItems, saveWatchlist, updateAccount, type Dial, type WatchItem } from "../lib/api";
import { useAccount } from "../lib/account";
import { localDigits } from "../lib/jalali";
import { useSettings } from "../lib/settings";
import { useTheme } from "../lib/theme";
import { MIN_WATCH_ITEMS } from "../lib/watch";

export default function Onboarding() {
  const { apiBase, lang, token, tr } = useSettings();
  const { account, setAccount } = useAccount();
  const theme = useTheme();
  const router = useRouter();
  const [items, setItems] = useState<WatchItem[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dial, setDial] = useState<Dial>("medium");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchWatchItems(apiBase).then((page) => setItems(page.results))
      .catch(() => setError(tr("Cannot reach the server.", "اتصال به سرور برقرار نشد.")));
  }, [apiBase, tr]);

  useEffect(() => {
    if (!account) return;
    setSelected(new Set(account.watchlist.map((item) => item.slug)));
    setDial(account.dial);
  }, [account]);

  if (!token) return <Redirect href="/login" />;

  const toggle = (slug: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(slug)) next.delete(slug); else next.add(slug);
    return next;
  });

  async function finish() {
    if (!token) return;
    setBusy(true); setError("");
    try {
      await saveWatchlist(apiBase, token, [...selected]);
      setAccount(await updateAccount(apiBase, token, { dial, onboarded: true }));
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tr("Cannot reach the server.", "اتصال به سرور برقرار نشد."));
    } finally {
      setBusy(false);
    }
  }

  const missing = Math.max(0, MIN_WATCH_ITEMS - selected.size);
  return <ScrollView contentContainerStyle={{ padding: 16, gap: 18 }} keyboardShouldPersistTaps="handled">
    <Txt bold size={22}>{tr("What do you follow?", "چه چیزهایی را دنبال می‌کنید؟")}</Txt>
    <Txt muted>{tr(
      `Pick at least ${MIN_WATCH_ITEMS}. Events about them are marked and moved up your radar, and can alert you.`,
      `دست‌کم ${localDigits(MIN_WATCH_ITEMS, lang)} مورد انتخاب کنید. رویدادهای مربوط به آن‌ها در رادار شما علامت می‌خورند، بالاتر می‌آیند و می‌توانند هشدار بدهند.`)}</Txt>
    {items ? <WatchPicker items={items} selected={selected} onToggle={toggle} /> : error ? null : <ActivityIndicator color={theme.accent} />}
    <DialPicker value={dial} onChange={setDial} />
    {error ? <Txt accessibilityRole="alert" style={{ color: theme.error }}>{error}</Txt> : null}
    <View style={{ gap: 6 }}>
      {missing ? <Txt muted size={13}>{tr(`${missing} more to go`, `${localDigits(missing, lang)} مورد دیگر`)}</Txt> : null}
      <Button title={busy ? tr("Saving…", "در حال ذخیره…") : tr("Start my radar", "شروع رادار من")} disabled={busy || missing > 0} onPress={finish} />
    </View>
  </ScrollView>;
}
