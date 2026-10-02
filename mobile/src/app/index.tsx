import { Stack, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, View } from "react-native";
import { EventCard, Row, Txt } from "../components/ui";
import { fetchRadar } from "../lib/api";
import { load, RADAR_KEY, save } from "../lib/cache";
import { formatJalali } from "../lib/jalali";
import type { ReaderEvent } from "../lib/reader";
import { useSettings } from "../lib/settings";
import { useTheme } from "../lib/theme";

export default function Radar() {
  const { apiBase, lang, tr } = useSettings();
  const theme = useTheme();
  const router = useRouter();
  const [events, setEvents] = useState<ReaderEvent[]>([]);
  const [syncedAt, setSyncedAt] = useState<number | null>(null);
  const [offline, setOffline] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const radar = await fetchRadar(apiBase);
      const now = Date.now();
      setEvents(radar.results);
      setSyncedAt(now);
      setOffline(false);
      await save(RADAR_KEY, radar.results, now);
    } catch {
      setOffline(true);
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    (async () => {
      const cached = await load<ReaderEvent[]>(RADAR_KEY).catch(() => null);
      if (cached) {
        setEvents(cached.data);
        setSyncedAt(cached.savedAt);
      }
      await refresh();
    })();
  }, [refresh]);

  const open = (id: number) => router.push({ pathname: "/event/[id]", params: { id: String(id) } });

  return <>
    <Stack.Screen options={{
      headerRight: () => <Row>
        <Pressable onPress={() => router.push("/review")} accessibilityRole="button" hitSlop={8}>
          <Txt bold size={14} style={{ color: theme.accent }}>{tr("Review", "بازبینی")}</Txt>
        </Pressable>
        <Pressable onPress={() => router.push("/settings")} accessibilityRole="button" hitSlop={8}>
          <Txt bold size={14} style={{ color: theme.accent }}>{tr("Settings", "تنظیمات")}</Txt>
        </Pressable>
      </Row>,
    }} />
    <FlatList
      data={events}
      keyExtractor={(event) => String(event.id)}
      contentContainerStyle={{ padding: 16 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={theme.accent} />}
      ListHeaderComponent={<View style={{ marginBottom: 12, gap: 6 }}>
        <Txt muted size={12}>
          {syncedAt ? `${tr("Last synced", "آخرین همگام‌سازی")}: ${formatJalali(new Date(syncedAt).toISOString(), lang)}` : ""}
        </Txt>
        {offline ? <View style={{ borderRadius: 12, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card2, padding: 10 }}>
          <Txt muted size={13}>{events.length
            ? tr("Offline: showing the last saved radar.", "آفلاین: آخرین رادار ذخیره‌شده نمایش داده می‌شود.")
            : tr("Cannot reach the server. Pull down to retry.", "اتصال به سرور برقرار نشد. برای تلاش دوباره صفحه را پایین بکشید.")}</Txt>
        </View> : null}
      </View>}
      ListEmptyComponent={loading ? <ActivityIndicator color={theme.accent} /> : offline ? null
        : <Txt muted>{tr("No events yet. The radar refreshes as sources report.", "هنوز رویدادی ثبت نشده است. رادار با رسیدن خبرها به‌روز می‌شود.")}</Txt>}
      renderItem={({ item, index }) => <EventCard event={item} hero={index === 0} onPress={() => open(item.id)} />}
    />
  </>;
}
