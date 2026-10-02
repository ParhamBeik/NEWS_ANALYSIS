import { Stack, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, View } from "react-native";
import { EventCard, Row, Txt } from "../components/ui";
import { fetchRadar } from "../lib/api";
import { load, RADAR_KEY, save } from "../lib/cache";
import { formatJalali, localDigits } from "../lib/jalali";
import { boostWatched, type ReaderEvent } from "../lib/reader";
import { useSettings } from "../lib/settings";
import { useAccount } from "../lib/account";
import { useTheme } from "../lib/theme";

export default function Radar() {
  const { apiBase, lang, token, tr } = useSettings();
  const { account } = useAccount();
  const theme = useTheme();
  const router = useRouter();
  const [events, setEvents] = useState<ReaderEvent[]>([]);
  const [ranked, setRanked] = useState(true);
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
      setRanked(radar.ranked !== false);
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

  // Personal radar, as on the web: watched events are marked, and lifted only when ranked.
  // The account (and so the watchlist) comes from the cache when offline. A cached radar is
  // treated as ranked: the latest-first fallback only shows when the last 24 h are empty.
  const slugs = useMemo(() => account?.watchlist.map((item) => item.slug) ?? [], [account]);
  const shown = useMemo(() => boostWatched(events, slugs, { boost: ranked }), [events, slugs, ranked]);

  const open = (id: number) => router.push({ pathname: "/event/[id]", params: { id: String(id) } });
  const link = (title: string, onPress: () => void) => <Pressable onPress={onPress} accessibilityRole="button" hitSlop={8}>
    <Txt bold size={14} style={{ color: theme.accent }}>{title}</Txt>
  </Pressable>;

  return <>
    <Stack.Screen options={{
      headerRight: () => <Row>
        {token
          ? link(account?.unread
            ? `${tr("Alerts", "هشدارها")} (${localDigits(account.unread, lang)})`
            : tr("Alerts", "هشدارها"), () => router.push("/inbox"))
          : link(tr("Sign in", "ورود"), () => router.push("/login"))}
        <Pressable onPress={() => router.push("/settings")} accessibilityRole="button" hitSlop={8}>
          <Txt bold size={14} style={{ color: theme.accent }}>{tr("Settings", "تنظیمات")}</Txt>
        </Pressable>
      </Row>,
    }} />
    <FlatList
      data={shown}
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
        {account?.phone && !account.onboarded ? <Pressable onPress={() => router.push("/onboarding")} accessibilityRole="link"
          style={{ borderRadius: 12, borderWidth: 1, borderColor: theme.accentStrong, backgroundColor: theme.card2, padding: 10 }}>
          <Txt size={13}>{tr("Pick what you follow to personalise your radar.", "موارد مورد علاقه‌تان را انتخاب کنید تا رادار شخصی شود.")}</Txt>
        </Pressable> : null}
      </View>}
      ListEmptyComponent={loading ? <ActivityIndicator color={theme.accent} /> : offline ? null
        : <Txt muted>{tr("No events yet. The radar refreshes as sources report.", "هنوز رویدادی ثبت نشده است. رادار با رسیدن خبرها به‌روز می‌شود.")}</Txt>}
      renderItem={({ item, index }) => <EventCard event={item} hero={index === 0} onPress={() => open(item.id)} />}
    />
  </>;
}
