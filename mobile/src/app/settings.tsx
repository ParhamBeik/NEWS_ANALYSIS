import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Linking, ScrollView, TextInput, View } from "react-native";
import { Button, Row, Txt } from "../components/ui";
import { useAccount } from "../lib/account";
import { localDigits } from "../lib/jalali";
import { DEFAULT_API_BASE, useSettings } from "../lib/settings";
import { FONT, useTheme } from "../lib/theme";
import { enabledProviders } from "../push";

export default function Settings() {
  const { lang, setLang, apiBase, setApiBase, token, tr } = useSettings();
  const { account, signOut, destroy } = useAccount();
  const theme = useTheme();
  const router = useRouter();
  const [draft, setDraft] = useState(apiBase);
  const [deleteError, setDeleteError] = useState("");

  // Irreversible: a native confirm, and the account is only dropped locally once the server
  // has deleted it.
  const confirmDelete = () => Alert.alert(
    tr("Delete your account?", "حساب شما حذف شود؟"),
    tr("Your phone number, email, watchlist, devices and alerts are deleted. This cannot be undone.",
      "شمارهٔ موبایل، ایمیل، فهرست پیگیری، دستگاه‌ها و هشدارهای شما پاک می‌شود. این کار برگشت‌پذیر نیست."),
    [
      { text: tr("Cancel", "انصراف"), style: "cancel" },
      { text: tr("Delete", "حذف"), style: "destructive", onPress: async () => {
        setDeleteError("");
        try {
          await destroy();
          router.replace("/");
        } catch {
          setDeleteError(tr("The account could not be deleted. Check your connection and try again.",
            "حساب حذف نشد. اتصال را بررسی کنید و دوباره امتحان کنید."));
        }
      } },
    ],
  );
  const providers = enabledProviders();
  const valid = /^https?:\/\/[^\s/]+/.test(draft.trim());

  return <ScrollView contentContainerStyle={{ padding: 16, gap: 20 }}>
    <View style={{ gap: 8 }}>
      <Txt bold>{tr("Language", "زبان")}</Txt>
      <Row>
        <Button title="فارسی" kind={lang === "fa" ? "primary" : "ghost"} onPress={() => setLang("fa")} />
        <Button title="English" kind={lang === "en" ? "primary" : "ghost"} onPress={() => setLang("en")} />
      </Row>
    </View>

    <View style={{ gap: 8 }}>
      <Txt bold>{tr("Server address", "نشانی سرور")}</Txt>
      <TextInput value={draft} onChangeText={setDraft} autoCapitalize="none" autoCorrect={false} keyboardType="url"
        placeholder={DEFAULT_API_BASE} placeholderTextColor={theme.muted}
        style={{ borderWidth: 1, borderColor: valid ? theme.line : theme.error, borderRadius: 12, padding: 12, color: theme.ink,
          backgroundColor: theme.card, fontFamily: FONT.regular, textAlign: "left", writingDirection: "ltr" }} />
      <Row>
        <Button title={tr("Save", "ذخیره")} disabled={!valid} onPress={() => setApiBase(draft)} />
        <Button title={tr("Reset", "پیش‌فرض")} kind="ghost" onPress={() => { setDraft(DEFAULT_API_BASE); setApiBase(DEFAULT_API_BASE); }} />
      </Row>
    </View>

    <View style={{ gap: 8 }}>
      <Txt bold>{tr("Notifications", "اعلان‌ها")}</Txt>
      <Txt muted size={13}>{providers.length
        ? `${tr("Enabled providers", "سرویس‌های فعال")}: ${providers.join(", ")}`
        : tr("Notifications are not set up yet.", "اعلان‌ها هنوز راه‌اندازی نشده‌اند.")}</Txt>
    </View>

    <View style={{ gap: 8 }}>
      <Txt bold>{tr("Account", "حساب کاربری")}</Txt>
      {token ? <>
        {account?.phone ? <Txt muted size={13}>{localDigits(account.phone, lang)}</Txt> : null}
        <Row>
          <Button title={tr("Watchlist & alerts", "فهرست پیگیری و هشدارها")} kind="ghost" onPress={() => router.push("/watchlist")} />
          <Button title={tr("Inbox", "صندوق هشدارها")} kind="ghost" onPress={() => router.push("/inbox")} />
          <Button title={tr("Sign out", "خروج")} kind="ghost" onPress={signOut} />
        </Row>
        <Button title={tr("Delete my account", "حذف حساب من")} kind="ghost" onPress={confirmDelete} />
        {deleteError ? <Txt accessibilityRole="alert" style={{ color: theme.error }}>{deleteError}</Txt> : null}
      </> : <Button title={tr("Sign in with your mobile number", "ورود با شمارهٔ موبایل")} onPress={() => router.push("/login")} />}
    </View>

    <View style={{ gap: 8 }}>
      <Txt bold>{tr("Privacy and terms", "حریم خصوصی و شرایط")}</Txt>
      <Row>
        <Button title={tr("Privacy policy", "حریم خصوصی")} kind="ghost" onPress={() => Linking.openURL(`${apiBase}/privacy`)} />
        <Button title={tr("Terms of use", "شرایط استفاده")} kind="ghost" onPress={() => Linking.openURL(`${apiBase}/terms`)} />
      </Row>
    </View>

    <View style={{ gap: 8 }}>
      <Txt bold>{tr("Staff", "کارکنان")}</Txt>
      <Row>
        <Button title={tr("Swipe review", "بازبینی سریع")} kind="ghost" onPress={() => router.push("/review")} />
      </Row>
    </View>
  </ScrollView>;
}
