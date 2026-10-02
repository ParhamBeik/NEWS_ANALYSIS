/**
 * Staff swipe review: right agrees with the model, left opens the fix pickers, Skip and Undo
 * are buttons. Same endpoints and token as the web review (/review/swipe).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Animated, PanResponder, ScrollView, TextInput, View } from "react-native";
import { Button, EventCard, Row, Txt } from "../components/ui";
import { ApiError, decide, login, me, reviewQueue, type Decision, type ReviewCard } from "../lib/api";
import { localDigits } from "../lib/jalali";
import { CATEGORIES } from "../lib/reader";
import { useSettings } from "../lib/settings";
import { gestureAction, REVIEW_TIERS } from "../lib/swipe";
import { FONT, useTheme } from "../lib/theme";

export default function Review() {
  const { token } = useSettings();
  return token ? <Queue token={token} /> : <Login />;
}

function Login() {
  const { apiBase, setToken, tr } = useSettings();
  const theme = useTheme();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const input = { borderWidth: 1, borderColor: theme.line, borderRadius: 12, padding: 12, color: theme.ink, backgroundColor: theme.card, fontFamily: FONT.regular };

  async function submit() {
    setBusy(true); setError("");
    try {
      const { token } = await login(apiBase, username.trim(), password);
      if (!(await me(apiBase, token)).is_staff) { setError(tr("This account is not staff.", "این حساب دسترسی کارکنان ندارد.")); return; }
      await setToken(token);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 400
        ? tr("Wrong username or password.", "نام کاربری یا گذرواژه نادرست است.")
        : tr("Cannot reach the server.", "اتصال به سرور برقرار نشد."));
    } finally {
      setBusy(false);
    }
  }

  return <ScrollView contentContainerStyle={{ padding: 16, gap: 12 }} keyboardShouldPersistTaps="handled">
    <Txt muted>{tr("Staff sign-in", "ورود کارکنان")}</Txt>
    <TextInput value={username} onChangeText={setUsername} autoCapitalize="none" autoCorrect={false} autoComplete="username"
      placeholder={tr("Username", "نام کاربری")} placeholderTextColor={theme.muted} style={input} />
    <TextInput value={password} onChangeText={setPassword} secureTextEntry autoComplete="password"
      placeholder={tr("Password", "گذرواژه")} placeholderTextColor={theme.muted} style={input} />
    {error ? <Txt style={{ color: theme.error }}>{error}</Txt> : null}
    <Button title={tr("Sign in", "ورود")} disabled={busy || !username || !password} onPress={submit} />
  </ScrollView>;
}

function Queue({ token }: { token: string }) {
  const { apiBase, lang, setToken, tr } = useSettings();
  const theme = useTheme();
  const [cards, setCards] = useState<ReviewCard[] | null>(null);
  const [pending, setPending] = useState(0);
  const [message, setMessage] = useState("");
  const [fixing, setFixing] = useState<{ category: string; iran_tier: number; global_tier: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const lastDecided = useRef<number | null>(null);
  const drag = useRef(new Animated.Value(0)).current;

  const fail = useCallback(async (err: unknown) => {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) await setToken(null);
    else setMessage(err instanceof ApiError ? err.message : tr("Cannot reach the server.", "اتصال به سرور برقرار نشد."));
  }, [setToken, tr]);

  const reload = useCallback(async () => {
    try {
      const queue = await reviewQueue(apiBase, token);
      setCards(queue.results); setPending(queue.pending);
    } catch (err) { await fail(err); }
  }, [apiBase, token, fail]);

  useEffect(() => { reload(); }, [reload]);

  const card = cards?.[0];

  // Each save is awaited before the next card shows, so the count is what the server holds.
  const send = useCallback(async (decision: Decision) => {
    if (!card && decision.action !== "undo") return;
    setBusy(true); setMessage("");
    try {
      const target = decision.action === "undo" ? lastDecided.current : card!.id;
      if (target == null) return;
      await decide(apiBase, token, target, decision);
      lastDecided.current = decision.action === "undo" ? null : target;
      setFixing(null);
      await reload();
    } catch (err) { await fail(err); } finally {
      setBusy(false);
      drag.setValue(0);
    }
  }, [apiBase, token, card, reload, fail, drag]);

  const startFix = useCallback(() => {
    if (!card) return;
    setFixing({ category: card.category && CATEGORIES[card.category] ? card.category : "macro", iran_tier: card.iran_tier ?? 2, global_tier: card.global_tier ?? 2 });
  }, [card]);

  const handlers = useRef({ send, startFix });
  handlers.current = { send, startFix };
  const pan = useRef(PanResponder.create({
    onMoveShouldSetPanResponder: (_, g) => Math.abs(g.dx) > 12 && Math.abs(g.dx) > Math.abs(g.dy),
    onPanResponderMove: (_, g) => drag.setValue(g.dx),
    onPanResponderRelease: (_, g) => {
      const action = gestureAction(g.dx, g.dy);
      Animated.spring(drag, { toValue: 0, useNativeDriver: true }).start();
      if (action === "agree") handlers.current.send({ action: "agree" });
      else if (action === "fix") handlers.current.startFix();
    },
  })).current;

  if (!cards) return <View style={{ flex: 1, justifyContent: "center", padding: 24 }}>
    {message ? <Txt style={{ color: theme.error }}>{message}</Txt> : <ActivityIndicator color={theme.accent} />}
  </View>;

  const tierLabel = (value: number | null) => value == null ? tr("Not assessed", "ارزیابی نشده") : REVIEW_TIERS[value][lang];
  const picker = (label: string, options: [string | number, string][], value: string | number, set: (v: never) => void) =>
    <View style={{ gap: 6 }}>
      <Txt bold size={14}>{label}</Txt>
      <Row>{options.map(([key, text]) => <Button key={String(key)} title={text} kind={key === value ? "primary" : "ghost"} onPress={() => set(key as never)} />)}</Row>
    </View>;

  return <ScrollView contentContainerStyle={{ padding: 16, gap: 12 }}>
    <Txt muted size={13}>{`${tr("Pending", "در انتظار")}: ${localDigits(pending, lang)}`}</Txt>
    {message ? <Txt style={{ color: theme.error }}>{message}</Txt> : null}
    {!card ? <Txt muted>{tr("Nothing to review right now.", "فعلاً موردی برای بازبینی نیست.")}</Txt> : <>
      <Animated.View {...pan.panHandlers} style={{ transform: [{ translateX: drag }] }}>
        <EventCard event={card} onPress={() => {}} />
      </Animated.View>
      <Txt size={14}>{`${tr("Model: Iran", "مدل: ایران")} ${tierLabel(card.iran_tier)} · ${tr("Global", "جهانی")} ${tierLabel(card.global_tier)}`}</Txt>
      {fixing ? <View style={{ gap: 12 }}>
        {picker(tr("Category", "دسته"), Object.entries(CATEGORIES).map(([key, meta]) => [key, meta[lang]]), fixing.category, (category: string) => setFixing({ ...fixing, category }))}
        {picker(tr("Impact on Iran", "اثر بر ایران"), REVIEW_TIERS.map((tier, index) => [index, tier[lang]]), fixing.iran_tier, (iran_tier: number) => setFixing({ ...fixing, iran_tier }))}
        {picker(tr("Global impact", "اثر جهانی"), REVIEW_TIERS.map((tier, index) => [index, tier[lang]]), fixing.global_tier, (global_tier: number) => setFixing({ ...fixing, global_tier }))}
        <Row>
          <Button title={tr("Save correction", "ثبت اصلاح")} disabled={busy} onPress={() => send({ action: "fix", ...fixing })} />
          <Button title={tr("Cancel", "انصراف")} kind="ghost" onPress={() => setFixing(null)} />
        </Row>
      </View> : <Row style={{ direction: "ltr" }}>
        <Button title={tr("Fix ←", "← اصلاح")} kind="ghost" disabled={busy} onPress={startFix} />
        <Button title={tr("Skip", "رد کردن")} kind="ghost" disabled={busy} onPress={() => send({ action: "skip" })} />
        <Button title={tr("Agree →", "تأیید →")} disabled={busy} onPress={() => send({ action: "agree" })} />
      </Row>}
    </>}
    {lastDecided.current != null ? <Button title={tr("Undo last", "بازگرداندن آخرین")} kind="ghost" disabled={busy} onPress={() => send({ action: "undo" })} /> : null}
  </ScrollView>;
}
