"use client";

import { useEffect } from "react";

/** Registers /sw.js so the radar and viewed events open offline, and the PWA installs. */
export default function ServiceWorker() {
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  }, []);
  return null;
}
