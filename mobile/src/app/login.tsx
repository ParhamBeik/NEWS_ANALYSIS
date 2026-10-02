/**
 * Reader sign-in: mobile number, then the texted six-digit code. The token lands in the
 * secure store (SettingsProvider.setToken); AccountProvider then loads the account and
 * registers this device for push. Staff keep username sign-in on the Review screen.
 */
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Linking, Pressable, ScrollView } from "react-native";
import { Button, Field, Row, Txt } from "../components/ui";
import { requestCode, verifyCode } from "../lib/api";
import { localDigits } from "../lib/jalali";
import { cleanCode, CODE_LENGTH, displayPhone, normalizePhone, otpMessage, otpReason, resendIn } from "../lib/phone";
import { useSettings } from "../lib/settings";
import { useTheme } from "../lib/theme";

export default function Login() {
  const { apiBase, lang, setToken, tr } = useSettings();
  const theme = useTheme();
  const router = useRouter();
  const [raw, setRaw] = useState("");
  const [phone, setPhone] = useState<string | null>(null); // set once a code is on its way
  const [code, setCode] = useState("");
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const wait = resendIn(sentAt, now);
  useEffect(() => {
    if (!wait) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [wait]);

  const candidate = normalizePhone(raw);
  const typedCode = cleanCode(code);

  async function send(target: string) {
    setBusy(true); setError("");
    try {
      await requestCode(apiBase, target);
      setPhone(target); setSentAt(Date.now()); setNow(Date.now());
    } catch (err) {
      const reason = otpReason(err);
      setError(otpMessage(reason, lang));
      // A code already on its way: show the code step and the countdown anyway.
      if (reason === "too_soon") { setPhone(target); setSentAt((at) => at ?? Date.now()); setNow(Date.now()); }
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    if (!phone || !typedCode) return;
    setBusy(true); setError("");
    try {
      const result = await verifyCode(apiBase, phone, typedCode);
      await setToken(result.token);
      router.replace(result.onboarded ? "/" : "/onboarding");
    } catch (err) {
      setError(otpMessage(otpReason(err), lang));
    } finally {
      setBusy(false);
    }
  }

  const link = (path: string, en: string, fa: string) =>
    <Pressable onPress={() => Linking.openURL(`${apiBase}${path}`)} accessibilityRole="link" hitSlop={6}>
      <Txt size={13} style={{ color: theme.accent, textDecorationLine: "underline" }}>{tr(en, fa)}</Txt>
    </Pressable>;

  return <ScrollView contentContainerStyle={{ padding: 20, gap: 14 }} keyboardShouldPersistTaps="handled">
    <Txt bold size={22}>{tr("Sign in to the news radar", "ورود به رادار خبر")}</Txt>
    <Txt muted>{tr(
      "Sign in with your mobile number to follow the assets and topics you care about and get alerts.",
      "با شمارهٔ موبایل وارد شوید تا دارایی‌ها و موضوع‌های مورد نظرتان را دنبال کنید و هشدار بگیرید.")}</Txt>

    {!phone ? <>
      <Txt bold size={14}>{tr("Mobile number", "شمارهٔ موبایل")}</Txt>
      <Field ltr value={raw} onChangeText={setRaw} keyboardType="phone-pad" autoComplete="tel" textContentType="telephoneNumber"
        placeholder="0912 123 4567" accessibilityLabel={tr("Mobile number", "شمارهٔ موبایل")}
        invalid={Boolean(raw) && !candidate && raw.replace(/\D/g, "").length >= 10} onSubmitEditing={() => candidate && send(candidate)} />
      <Button title={busy ? tr("Please wait…", "صبر کنید…") : tr("Send code", "دریافت کد")}
        disabled={busy || !candidate} onPress={() => candidate && send(candidate)} />
    </> : <>
      <Txt size={14}>{tr(`Code sent to ${displayPhone(phone)}`, `کد به ${localDigits(displayPhone(phone), lang)} پیامک شد`)}</Txt>
      <Field ltr value={code} onChangeText={setCode} keyboardType="number-pad" autoComplete="one-time-code" textContentType="oneTimeCode"
        maxLength={CODE_LENGTH} placeholder="••••••" accessibilityLabel={tr("Code we texted you", "کد پیامک‌شده")} autoFocus
        style={{ textAlign: "center", fontSize: 22, letterSpacing: 8 }} onSubmitEditing={verify} />
      <Txt muted size={13}>{tr("The 6-digit code is valid for 2 minutes.", "کد ۶ رقمی تا ۲ دقیقه معتبر است.")}</Txt>
      <Button title={busy ? tr("Please wait…", "صبر کنید…") : tr("Sign in", "ورود")} disabled={busy || !typedCode} onPress={verify} />
      <Row>
        <Button kind="ghost" disabled={busy || wait > 0}
          title={wait > 0
            ? tr(`Send again in ${wait}s`, `ارسال دوباره تا ${localDigits(wait, lang)} ثانیه`)
            : tr("Send the code again", "ارسال دوبارهٔ کد")}
          onPress={() => send(phone)} />
        <Button kind="ghost" title={tr("Use a different number", "تغییر شماره")} disabled={busy}
          onPress={() => { setPhone(null); setCode(""); setError(""); }} />
      </Row>
    </>}

    {error ? <Txt accessibilityRole="alert" style={{ color: theme.error }}>{error}</Txt> : null}

    <Row style={{ marginTop: 12 }}>
      <Txt muted size={13}>{tr("By signing in you accept the", "با ورود، این‌ها را می‌پذیرید:")}</Txt>
      {link("/terms", "terms", "شرایط استفاده")}
      <Txt muted size={13}>{tr("and", "و")}</Txt>
      {link("/privacy", "privacy policy", "حریم خصوصی")}
    </Row>
  </ScrollView>;
}
