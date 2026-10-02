/**
 * Colours copied from the web reader (frontend/app/globals.css `.reader-theme`). Impact
 * tiers are one violet hue at five intensities; red is reserved for errors.
 */
import { useColorScheme } from "react-native";

const dark = {
  paper: "#0c0d16",
  card: "#151726",
  card2: "#1c1f33",
  line: "#2a2e47",
  ink: "#eef0fa",
  muted: "#a7acc4",
  accent: "#a99bff",
  accentStrong: "#4b33c9",
  onAccent: "#ffffff",
  error: "#f87171",
  tiers: [
    ["#24204a", "#c9c2ff"],
    ["#352c78", "#e0dbff"],
    ["#5a46cc", "#ffffff"],
    ["#8b78f5", "#0e0a2e"],
    ["#c4b8ff", "#120d3a"],
  ] as [string, string][],
};

const light: typeof dark = {
  paper: "#f5f5fa",
  card: "#ffffff",
  card2: "#eeeef7",
  line: "#dfe0ec",
  ink: "#14152a",
  muted: "#52566e",
  accent: "#4b33c9",
  accentStrong: "#4b33c9",
  onAccent: "#ffffff",
  error: "#b91c1c",
  tiers: [
    ["#ece9fd", "#3a2d91"],
    ["#d6cffb", "#2f2380"],
    ["#a597f2", "#160f45"],
    ["#6b54e0", "#ffffff"],
    ["#3d22b5", "#ffffff"],
  ],
};

export type Theme = typeof dark;

export function useTheme(): Theme {
  return useColorScheme() === "light" ? light : dark;
}

export const FONT = { regular: "Vazirmatn_400Regular", bold: "Vazirmatn_700Bold" };
