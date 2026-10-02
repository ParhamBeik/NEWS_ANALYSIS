/**
 * Every alert lands here, including those held by quiet hours or the daily cap. Cached for
 * 48 h like the radar so it opens offline; "last synced" says how old it is.
 */
import { Redirect, Stack, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, View } from "react-native";
import { Button, CategoryChip, Row, Txt } from "../components/ui";
import { ApiError, fetchInbox, markAllRead, type Inbox } from "../lib/api";
import { useAccount } from "../lib/account";
import { INBOX_KEY, load, save } from "../lib/cache";
import { formatJalali, localDigits } from "../lib/jalali";
import { TIERS } from "../lib/reader";
import { useSettings } from "../lib/settings";
import { useTheme } from "../lib/theme";

const HELD: Record<string, [string, string]> = {
  quiet: ["Held during quiet hours", "در ساعت سکوت نگه داشته شد"],
  cap: ["Over today's 5 notifications", "بیش از سقف ۵ اعلان امروز"],
};

export default function InboxScreen() {
  const { apiBase, lang, token, tr } = useSettings();
  const { refresh: refreshAccount, signOut } = useAccount();
  const theme = useTheme();
  const router = useRouter();
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [syncedAt, setSyncedAt] = useState<number | null>(null);
  const [offline, setOffline] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    if (!token) return;
    setRefreshing(true);
    try {
      const next = await fetchInbox(apiBase, token);
      const now = Date.now();
      setInbox(next); setSyncedAt(now); setOffline(false);
      await save(INBOX_KEY, next, now);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { await signOut(); return; }
      setOffline(true);
    } finally {
      setRefreshing(false);
    }
  }, [apiBase, token, signOut]);

  useEffect(() => {
    (async () => {
      const cached = await load<Inbox>(INBOX_KEY).catch(() => null);
      if (cached) { setInbox(cached.data); setSyncedAt(cached.savedAt); }
      await refresh();
    })();
  }, [refresh]);

  if (!token) return <Redirect href="/login" />;

  async function readAll() {
    if (!token) return;
    await markAllRead(apiBase, token).catch(() => {});
    await Promise.all([refresh(), refreshAccount()]);
  }

  return <>
    <Stack.Screen options={{
      headerRight: () => inbox?.unread
        ? <Pressable onPress={readAll} accessibilityRole="button" hitSlop={8}>
          <Txt bold size={14} style={{ color: theme.accent }}>{tr("Mark all read", "همه خوانده شد")}</Txt>
        </Pressable> : null,
    }} />
    <FlatList
      data={inbox?.results ?? []}
      keyExtractor={(row) => String(row.id)}
      contentContainerStyle={{ padding: 16, gap: 10 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={theme.accent} />}
      ListHeaderComponent={<View style={{ gap: 6, marginBottom: 6 }}>
        <Txt muted size={13}>{inbox?.unread
          ? tr(`${inbox.unread} unread`, `${localDigits(inbox.unread, lang)} خوانده‌نشده`)
          : inbox ? tr("All caught up.", "همه را دیده‌اید.") : ""}</Txt>
        {syncedAt ? <Txt muted size={12}>{`${tr("Last synced", "آخرین همگام‌سازی")}: ${formatJalali(new Date(syncedAt).toISOString(), lang)}`}</Txt> : null}
        {offline ? <Txt muted size={13}>{inbox
          ? tr("Offline: showing your last saved alerts.", "آفلاین: آخرین هشدارهای ذخیره‌شده نمایش داده می‌شود.")
          : tr("Cannot reach the server. Pull down to retry.", "اتصال به سرور برقرار نشد. برای تلاش دوباره صفحه را پایین بکشید.")}</Txt> : null}
      </View>}
      ListEmptyComponent={!inbox && !offline ? <ActivityIndicator color={theme.accent} /> : inbox ? <View style={{ gap: 12, paddingVertical: 24 }}>
        <Txt muted>{tr("No alerts yet. Events on your watchlist that reach your dial appear here.",
          "هنوز هشداری نیست. رویدادهای فهرست پیگیری که به حساسیت انتخابی شما برسند اینجا می‌آیند.")}</Txt>
        <Button kind="ghost" title={tr("Edit watchlist", "ویرایش فهرست پیگیری")} onPress={() => router.push("/watchlist")} />
      </View> : null}
      renderItem={({ item: row }) => <Pressable accessibilityRole="link"
        onPress={() => router.push({ pathname: "/event/[id]", params: { id: String(row.event.id) } })}
        style={({ pressed }) => ({ borderRadius: 16, borderWidth: 1, padding: 14, gap: 6, opacity: pressed ? 0.85 : 1,
          backgroundColor: theme.card, borderColor: row.read ? theme.line : theme.accentStrong })}>
        <Row>
          {row.breaking ? <Txt bold size={12} style={{ color: theme.error }}>{tr("Breaking", "فوری")}</Txt> : null}
          {row.kind === "update" ? <Txt muted size={12}>{tr("Update", "به‌روزرسانی")}</Txt> : null}
          <CategoryChip category={row.event.category} />
          {row.tier ? <Txt muted size={12}>{`${tr("Impact", "اثر")}: ${TIERS[row.tier - 1]?.[lang] ?? ""}`}</Txt> : null}
          {row.held ? <Txt muted size={12}>{tr(...HELD[row.held])}</Txt> : null}
          {!row.read ? <Txt bold size={12} style={{ color: theme.accent }}>{tr("Unread", "خوانده‌نشده")}</Txt> : null}
        </Row>
        <Txt bold>{lang === "en" && row.event.title_en ? row.event.title_en : row.event.title}</Txt>
        <Txt muted size={12}>{formatJalali(row.created_at, lang)}</Txt>
      </Pressable>}
    />
  </>;
}
