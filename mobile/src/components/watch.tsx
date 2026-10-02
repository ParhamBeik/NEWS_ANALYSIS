import { useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";
import type { Dial, WatchItem } from "../lib/api";
import { localDigits } from "../lib/jalali";
import { useSettings } from "../lib/settings";
import { FONT, useTheme } from "../lib/theme";
import { DIALS, groupItems } from "../lib/watch";
import { Field, Row, Txt } from "./ui";

/** Watch-item chips grouped by kind, with a filter box. Controlled: the screen owns `selected`. */
export function WatchPicker({ items, selected, onToggle }: {
  items: WatchItem[]; selected: Set<string>; onToggle: (slug: string) => void;
}) {
  const { lang, tr } = useSettings();
  const theme = useTheme();
  const [filter, setFilter] = useState("");
  const groups = useMemo(() => groupItems(items, filter), [items, filter]);
  return <View style={{ gap: 14 }}>
    <Field value={filter} onChangeText={setFilter} autoCorrect={false}
      placeholder={tr("Search: dollar, oil, central bank…", "جست‌وجو: دلار، نفت، بانک مرکزی…")}
      accessibilityLabel={tr("Filter items", "جست‌وجوی موارد")} />
    <Txt muted size={13} accessibilityLiveRegion="polite">
      {lang === "fa" ? `${localDigits(selected.size, lang)} مورد انتخاب شده` : `${selected.size} selected`}
    </Txt>
    {groups.map(([kind, en, fa, rows]) => rows.length ? <View key={kind} style={{ gap: 8 }}>
      <Txt bold muted size={13}>{lang === "fa" ? fa : en}</Txt>
      <Row>{rows.map((item) => {
        const on = selected.has(item.slug);
        return <Pressable key={item.slug} onPress={() => onToggle(item.slug)} hitSlop={4}
          accessibilityRole="checkbox" accessibilityState={{ checked: on }}
          style={{ borderRadius: 999, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 7,
            borderColor: on ? theme.accentStrong : theme.line, backgroundColor: on ? theme.accentStrong : theme.card }}>
          <Text style={{ fontFamily: FONT.regular, fontSize: 14, color: on ? theme.onAccent : theme.ink }}>
            {lang === "fa" ? item.name_fa : item.name_en}
          </Text>
        </Pressable>;
      })}</Row>
    </View> : null)}
  </View>;
}

/** The alert dial: which event tiers on the watchlist alert at all. */
export function DialPicker({ value, onChange }: { value: Dial; onChange: (dial: Dial) => void }) {
  const { lang, tr } = useSettings();
  const theme = useTheme();
  return <View style={{ gap: 8 }} accessibilityRole="radiogroup">
    <Txt bold>{tr("Alert sensitivity", "حساسیت هشدار")}</Txt>
    {DIALS.map(([key, en, fa, hintEn, hintFa]) => {
      const on = key === value;
      return <Pressable key={key} onPress={() => onChange(key)} accessibilityRole="radio" accessibilityState={{ checked: on }}
        style={{ borderRadius: 14, borderWidth: 1, padding: 12, gap: 2,
          borderColor: on ? theme.accentStrong : theme.line, backgroundColor: on ? theme.card2 : theme.card }}>
        <Txt bold>{lang === "fa" ? fa : en}</Txt>
        <Txt muted size={13}>{lang === "fa" ? hintFa : hintEn}</Txt>
      </Pressable>;
    })}
  </View>;
}
