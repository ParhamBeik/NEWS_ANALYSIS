import { Vazirmatn_400Regular } from "@expo-google-fonts/vazirmatn/400Regular";
import { Vazirmatn_700Bold } from "@expo-google-fonts/vazirmatn/700Bold";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { View } from "react-native";
import { AccountProvider } from "../lib/account";
import { prune } from "../lib/cache";
import { SettingsProvider, useSettings } from "../lib/settings";
import { FONT, useTheme } from "../lib/theme";

export default function RootLayout() {
  const [fontsLoaded] = useFonts({ Vazirmatn_400Regular, Vazirmatn_700Bold });
  return <SettingsProvider><AccountProvider><Shell fontsLoaded={fontsLoaded} /></AccountProvider></SettingsProvider>;
}

function Shell({ fontsLoaded }: { fontsLoaded: boolean }) {
  const { ready, lang, tr } = useSettings();
  const theme = useTheme();

  useEffect(() => {
    prune().catch(() => {});
    // Push registration runs in AccountProvider once someone is signed in.
  }, []);

  if (!fontsLoaded || !ready) return <View style={{ flex: 1, backgroundColor: theme.paper }} />;

  // Layout direction follows the chosen language at runtime; I18nManager.forceRTL would
  // need an app restart for every language switch.
  return <View style={{ flex: 1, direction: lang === "fa" ? "rtl" : "ltr", backgroundColor: theme.paper }}>
    <StatusBar style="auto" />
    <Stack screenOptions={{
      headerStyle: { backgroundColor: theme.card },
      headerTintColor: theme.ink,
      headerTitleStyle: { fontFamily: FONT.bold },
      contentStyle: { backgroundColor: theme.paper },
    }}>
      <Stack.Screen name="index" options={{ title: tr("News radar", "رادار خبر") }} />
      <Stack.Screen name="event/[id]" options={{ title: "" }} />
      <Stack.Screen name="settings" options={{ title: tr("Settings", "تنظیمات") }} />
      <Stack.Screen name="review" options={{ title: tr("Swipe review", "بازبینی سریع") }} />
      <Stack.Screen name="login" options={{ title: tr("Sign in", "ورود") }} />
      <Stack.Screen name="onboarding" options={{ title: tr("Your radar", "رادار شما") }} />
      <Stack.Screen name="watchlist" options={{ title: tr("Watchlist & alerts", "فهرست پیگیری و هشدارها") }} />
      <Stack.Screen name="inbox" options={{ title: tr("Alerts", "هشدارها") }} />
    </Stack>
  </View>;
}
