/** Web app manifest: makes the reader installable (iOS "Add to Home Screen", Android). */
export default function manifest() {
  return {
    name: "رادار خبر · News Intelligence",
    short_name: "رادار خبر",
    description: "رویدادهای اقتصادی و ژئوپلیتیکی مؤثر بر بازارهای ایران",
    lang: "fa",
    dir: "rtl",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#0c0d16",
    theme_color: "#4b33c9",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml" },
    ],
  };
}
