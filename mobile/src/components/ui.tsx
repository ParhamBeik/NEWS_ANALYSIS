import { Image, Pressable, StyleSheet, Text, View, type TextProps, type ViewStyle } from "react-native";
import { formatGregorian, formatJalali } from "../lib/jalali";
import { absoluteUrl, categoryOf, headline, impactScore, impactTier, type ReaderEvent } from "../lib/reader";
import { useSettings } from "../lib/settings";
import { FONT, useTheme } from "../lib/theme";

/** Text in Vazirmatn, aligned to the reading direction of the chosen language. */
export function Txt({ bold, muted, size = 15, style, ...props }: TextProps & { bold?: boolean; muted?: boolean; size?: number }) {
  const theme = useTheme();
  const { lang } = useSettings();
  return <Text {...props} style={[{
    fontFamily: bold ? FONT.bold : FONT.regular,
    fontSize: size,
    lineHeight: Math.round(size * 1.7),
    color: muted ? theme.muted : theme.ink,
    textAlign: lang === "fa" ? "right" : "left",
    writingDirection: lang === "fa" ? "rtl" : "ltr",
  }, style]} />;
}

export function TierChip({ score, label }: { score: number | null; label?: string }) {
  const theme = useTheme();
  const { lang, tr } = useSettings();
  const tier = impactTier(score);
  const [bg, fg] = tier ? theme.tiers[tier.level - 1] : [theme.card2, theme.muted];
  const text = tier ? tier[lang] : tr("Not assessed", "ارزیابی نشده");
  return <View style={[styles.chip, { backgroundColor: bg, borderColor: tier ? bg : theme.line }]}>
    <Text style={{ color: fg, fontFamily: FONT.bold, fontSize: 12 }}>{label ? `${label}: ${text}` : text}</Text>
  </View>;
}

export function CategoryChip({ category }: { category: string | null }) {
  const { lang } = useSettings();
  const meta = categoryOf(category);
  return <View style={[styles.chip, { backgroundColor: meta.color, borderColor: meta.color }]}>
    <Text style={{ color: "#ffffff", fontFamily: FONT.bold, fontSize: 12 }}>{meta[lang]}</Text>
  </View>;
}

/** Jalali first; Gregorian secondary, smaller. */
export function When({ iso }: { iso: string | null }) {
  const { lang } = useSettings();
  return <Txt muted size={12}>{formatJalali(iso, lang)}{iso ? `  ·  ${formatGregorian(iso)}` : ""}</Txt>;
}

/** Image-led card; without a permitted image the category colour stands in. */
export function EventCard({ event, onPress, hero }: { event: ReaderEvent; onPress: () => void; hero?: boolean }) {
  const theme = useTheme();
  const { lang, apiBase } = useSettings();
  const image = absoluteUrl(hero ? event.image_large_url || event.image_url : event.image_url, apiBase);
  return <Pressable onPress={onPress} accessibilityRole="link"
    style={({ pressed }) => [styles.card, { backgroundColor: theme.card, borderColor: theme.line, opacity: pressed ? 0.85 : 1 }]}>
    {image
      ? <Image source={{ uri: image }} style={[styles.image, hero && styles.hero]} resizeMode="cover" accessibilityIgnoresInvertColors />
      : <View style={[styles.image, hero && styles.hero, { backgroundColor: categoryOf(event.category).color }]} />}
    <View style={styles.body}>
      <Row><CategoryChip category={event.category} /><TierChip score={impactScore(event)} /></Row>
      <Txt bold size={hero ? 20 : 16}>{headline(event, lang)}</Txt>
      <When iso={event.event_time} />
    </View>
  </Pressable>;
}

export function Row({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[styles.row, style]}>{children}</View>;
}

export function Button({ title, onPress, kind = "primary", disabled }: { title: string; onPress: () => void; kind?: "primary" | "ghost"; disabled?: boolean }) {
  const theme = useTheme();
  const primary = kind === "primary";
  return <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button"
    style={({ pressed }) => [styles.button, {
      backgroundColor: primary ? theme.accentStrong : "transparent",
      borderColor: primary ? theme.accentStrong : theme.line,
      opacity: disabled ? 0.5 : pressed ? 0.8 : 1,
    }]}>
    <Text style={{ color: primary ? theme.onAccent : theme.ink, fontFamily: FONT.bold, fontSize: 15 }}>{title}</Text>
  </Pressable>;
}

const styles = StyleSheet.create({
  chip: { borderRadius: 999, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 3 },
  card: { borderRadius: 18, borderWidth: 1, overflow: "hidden", marginBottom: 14 },
  image: { width: "100%", aspectRatio: 16 / 9 },
  hero: { aspectRatio: 4 / 3 },
  body: { padding: 14, gap: 6 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  button: { borderRadius: 14, borderWidth: 1, paddingVertical: 12, paddingHorizontal: 16, alignItems: "center" },
});
