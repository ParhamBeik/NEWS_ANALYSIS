import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Image, Linking, Pressable, ScrollView, View } from "react-native";
import { Button, CategoryChip, Row, TierChip, Txt, When } from "../../components/ui";
import { fetchEvent } from "../../lib/api";
import { eventKey, load, RADAR_KEY, save } from "../../lib/cache";
import { formatJalali, localDigits } from "../../lib/jalali";
import { absoluteUrl, headline, pick, type ReaderEvent } from "../../lib/reader";
import { useSettings } from "../../lib/settings";
import { useTheme } from "../../lib/theme";

export default function EventDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { apiBase, lang, tr } = useSettings();
  const theme = useTheme();
  const [event, setEvent] = useState<ReaderEvent | null>(null);
  const [syncedAt, setSyncedAt] = useState<number | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "offline" | "missing">("loading");

  useEffect(() => {
    let alive = true;
    (async () => {
      // Opened before: show the saved copy at once, then refresh it.
      const cached = await load<ReaderEvent>(eventKey(id)).catch(() => null);
      if (cached && alive) { setEvent(cached.data); setSyncedAt(cached.savedAt); setState("ok"); }
      try {
        const fresh = await fetchEvent(apiBase, id);
        const now = Date.now();
        await save(eventKey(id), fresh, now);
        if (alive) { setEvent(fresh); setSyncedAt(now); setState("ok"); }
      } catch (error) {
        if (!alive || cached) { if (alive) setState("offline"); return; }
        // Never opened: the radar's summary copy is better than nothing offline.
        const radar = await load<ReaderEvent[]>(RADAR_KEY).catch(() => null);
        const summary = radar?.data.find((row) => String(row.id) === String(id));
        if (summary) { setEvent(summary); setSyncedAt(radar!.savedAt); setState("offline"); }
        else setState((error as { status?: number }).status === 404 ? "missing" : "offline");
      }
    })();
    return () => { alive = false; };
  }, [apiBase, id]);

  if (!event) {
    return <View style={{ flex: 1, padding: 24, justifyContent: "center" }}>
      {state === "loading" ? <ActivityIndicator color={theme.accent} />
        : <Txt muted>{state === "missing" ? tr("This event is not available.", "این رویداد در دسترس نیست.")
          : tr("Offline, and this event was not saved yet.", "آفلاین هستید و این رویداد هنوز ذخیره نشده است.")}</Txt>}
    </View>;
  }

  const image = absoluteUrl(event.image_large_url || event.image_url, apiBase);
  const title = headline(event, lang);
  const block = (label: string, text: string | null, muted = false) => text
    ? <View style={{ borderRadius: 16, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card, padding: 14, gap: 4 }}>
      <Txt bold size={16}>{label}</Txt><Txt muted={muted}>{text}</Txt>
    </View> : null;

  return <ScrollView contentContainerStyle={{ padding: 16, gap: 14 }}>
    {image ? <Image source={{ uri: image }} style={{ width: "100%", aspectRatio: 16 / 9, borderRadius: 16 }} resizeMode="cover" /> : null}
    <Row><CategoryChip category={event.category} /></Row>
    <Txt bold size={22}>{title}</Txt>
    {title !== event.original_title ? <Txt muted size={13}>{event.original_title}</Txt> : null}
    <When iso={event.event_time} />
    {state === "offline" && syncedAt ? <Txt muted size={12}>
      {`${tr("Offline copy, saved", "نسخهٔ آفلاین، ذخیره‌شده در")} ${formatJalali(new Date(syncedAt).toISOString(), lang)}`}
    </Txt> : null}
    <Row>
      <TierChip score={event.iran_score} label={tr("Iran", "ایران")} />
      <TierChip score={event.global_score} label={tr("Global", "جهانی")} />
    </Row>
    <Button title={tr("Market impact (web)", "اثر بر بازار (وب)")}
      onPress={() => Linking.openURL(`${apiBase}/events/${event.id}/market`)} />

    {block(tr("What happened", "چه اتفاقی افتاد"), pick(event, "brief", lang))
      || <Txt muted size={13}>{tr("Developing: the summary is still being prepared.", "در حال تکمیل: خلاصهٔ این رویداد هنوز آماده نشده است.")}</Txt>}
    {block(tr("Why it may matter", "چرا ممکن است مهم باشد"), pick(event, "channels", lang))}
    {block(tr("What is still unclear", "آنچه هنوز روشن نیست"), pick(event, "uncertainty", lang), true)}
    <Txt muted size={12}>{tr("Impact is an assessment, not a forecast or proof of a price effect.", "میزان اثر یک ارزیابی است؛ پیش‌بینی یا اثبات اثر بر قیمت نیست.")}</Txt>

    <Txt bold size={18}>{`${tr("Sources", "منابع")} (${localDigits(event.sources.length, lang)})`}</Txt>
    {event.sources.map((source) => <Pressable key={source.url} onPress={() => Linking.openURL(source.url)} accessibilityRole="link"
      style={{ borderRadius: 14, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card, padding: 12, gap: 2 }}>
      <Txt bold size={14}>{source.original_outlet || source.name}</Txt>
      <Txt size={14} style={{ color: theme.accent }}>{source.headline || source.url}</Txt>
      <When iso={source.published_at || source.first_seen_at} />
    </Pressable>)}
  </ScrollView>;
}
