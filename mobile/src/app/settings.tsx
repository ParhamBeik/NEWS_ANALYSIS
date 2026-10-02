import { useRouter } from "expo-router";
import { useState } from "react";
import { ScrollView, TextInput, View } from "react-native";
import { Button, Row, Txt } from "../components/ui";
import { logout } from "../lib/api";
import { DEFAULT_API_BASE, useSettings } from "../lib/settings";
import { FONT, useTheme } from "../lib/theme";
import { enabledProviders } from "../push";

export default function Settings() {
  const { lang, setLang, apiBase, setApiBase, token, setToken, tr } = useSettings();
  const theme = useTheme();
  const router = useRouter();
  const [draft, setDraft] = useState(apiBase);
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
      <Txt bold>{tr("Staff", "کارکنان")}</Txt>
      <Row>
        <Button title={tr("Swipe review", "بازبینی سریع")} kind="ghost" onPress={() => router.push("/review")} />
        {token ? <Button title={tr("Sign out", "خروج")} kind="ghost" onPress={async () => {
          await logout(apiBase, token).catch(() => {}); // revoke server-side; drop locally regardless
          await setToken(null);
        }} /> : null}
      </Row>
    </View>
  </ScrollView>;
}
