/** Watchlist and alert settings: items, dial and quiet hours. Mirrors the web /settings. */
import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, View } from "react-native";
import { Button, Field, Row, Txt } from "../components/ui";
import { DialPicker, WatchPicker } from "../components/watch";
import { ApiError, fetchWatchItems, saveWatchlist, updateAccount, type Dial, type WatchItem } from "../lib/api";
import { useAccount } from "../lib/account";
import { localDigits } from "../lib/jalali";
import { useSettings } from "../lib/settings";
import { useTheme } from "../lib/theme";
import { cleanTime, MIN_WATCH_ITEMS } from "../lib/watch";

export default function Watchlist() {
  const { apiBase, lang, token, tr } = useSettings();
  const { account, offline, setAccount } = useAccount();
  const theme = useTheme();
  const [items, setItems] = useState<WatchItem[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dial, setDial] = useState<Dial>("medium");
  const [quietStart, setQuietStart] = useState("23:00");
  const [quietEnd, setQuietEnd] = useState("07:00");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchWatchItems(apiBase).then((page) => setItems(page.results)).catch(() => setItems(null));
  }, [apiBase]);

  useEffect(() => {
    if (!account) return;
    setSelected(new Set(account.watchlist.map((item) => item.slug)));
    setDial(account.dial);
    setQuietStart(account.quiet_start);
    setQuietEnd(account.quiet_end);
  }, [account]);

  if (!token) return <Redirect href="/login" />;
  if (!account) return <View style={{ padding: 24 }}><ActivityIndicator color={theme.accent} /></View>;

  const start = cleanTime(quietStart);
  const end = cleanTime(quietEnd);
  const toggle = (slug: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(slug)) next.delete(slug); else next.add(slug);
    return next;
  });

  async function save() {
    if (!token || !start || !end) return;
    setBusy(true); setMessage(null);
    try {
      if (items) await saveWatchlist(apiBase, token, [...selected]);
      setAccount(await updateAccount(apiBase, token, { dial, quiet_start: start, quiet_end: end }));
      setMessage({ ok: true, text: tr("Saved.", "ذخیره شد.") });
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : tr("Cannot reach the server.", "اتصال به سرور برقرار نشد.") });
    } finally {
      setBusy(false);
    }
  }

  return <ScrollView contentContainerStyle={{ padding: 16, gap: 20 }} keyboardShouldPersistTaps="handled">
    {offline ? <Txt muted size={13}>{tr("Offline: showing your last saved settings.", "آفلاین: آخرین تنظیمات ذخیره‌شده نمایش داده می‌شود.")}</Txt> : null}
    <View style={{ gap: 10 }}>
      <Txt bold size={18}>{tr("Watchlist", "فهرست پیگیری")}</Txt>
      {items ? <WatchPicker items={items} selected={selected} onToggle={toggle} />
        : <Txt muted size={13}>{account.watchlist.map((item) => tr(item.name_en, item.name_fa)).join("، ")}</Txt>}
      {items && selected.size < MIN_WATCH_ITEMS
        ? <Txt muted size={13}>{tr(`Keep at least ${MIN_WATCH_ITEMS} for a useful radar.`, `برای رادار مفید دست‌کم ${localDigits(MIN_WATCH_ITEMS, lang)} مورد نگه دارید.`)}</Txt> : null}
    </View>
    <DialPicker value={dial} onChange={setDial} />
    <View style={{ gap: 8 }}>
      <Txt bold>{tr("Quiet hours (Tehran time)", "ساعت سکوت (به وقت تهران)")}</Txt>
      <Txt muted size={13}>{tr(
        "Inside these hours alerts wait in your inbox; tier-5 events still notify you.",
        "در این ساعت‌ها هشدار فقط در صندوق هشدارها می‌نشیند؛ رویدادهای سطح ۵ همچنان اعلان می‌شوند.")}</Txt>
      <Row style={{ direction: "ltr" }}>
        <Txt size={14}>{tr("From", "از")}</Txt>
        <Field ltr value={quietStart} onChangeText={setQuietStart} invalid={!start} keyboardType="numbers-and-punctuation"
          maxLength={5} placeholder="23:00" accessibilityLabel={tr("Quiet hours start", "شروع ساعت سکوت")} style={{ minWidth: 90 }} />
        <Txt size={14}>{tr("To", "تا")}</Txt>
        <Field ltr value={quietEnd} onChangeText={setQuietEnd} invalid={!end} keyboardType="numbers-and-punctuation"
          maxLength={5} placeholder="07:00" accessibilityLabel={tr("Quiet hours end", "پایان ساعت سکوت")} style={{ minWidth: 90 }} />
      </Row>
    </View>
    {message ? <Txt accessibilityRole={message.ok ? undefined : "alert"} style={{ color: message.ok ? theme.accent : theme.error }}>{message.text}</Txt> : null}
    <Button title={busy ? tr("Saving…", "در حال ذخیره…") : tr("Save settings", "ذخیرهٔ تنظیمات")} disabled={busy || !start || !end} onPress={save} />
  </ScrollView>;
}
