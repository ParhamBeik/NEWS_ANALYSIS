import { Vazirmatn_400Regular } from "@expo-google-fonts/vazirmatn/400Regular";
import { Vazirmatn_700Bold } from "@expo-google-fonts/vazirmatn/700Bold";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { View } from "react-native";
import { prune } from "../lib/cache";
import { SettingsProvider, useSettings } from "../lib/settings";
import { FONT, useTheme } from "../lib/theme";
import { register } from "../push";

export default function RootLayout() {
  const [fontsLoaded] = useFonts({ Vazirmatn_400Regular, Vazirmatn_700Bold });
  return <SettingsProvider><Shell fontsLoaded={fontsLoaded} /></SettingsProvider>;
}

function Shell({ fontsLoaded }: { fontsLoaded: boolean }) {
  const { ready, lang, tr } = useSettings();
  const theme = useTheme();

  useEffect(() => {
    prune().catch(() => {});
    register().catch(() => {}); // no-op until push keys are configured
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
    </Stack>
  </View>;
}
