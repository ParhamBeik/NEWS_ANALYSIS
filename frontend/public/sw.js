/**
 * Reader service worker: offline radar + recently viewed events, and Web Push alerts.
 *
 * Pages are network-first: a cached copy is only served when the network fails, so a
 * reader online never sees stale news. Only the public reader pages are stored (the radar
 * and event pages); staff pages are never cached. Hashed build assets are cache-first.
 */
const PAGES = "reader-pages-v1";
const STATIC = "reader-static-v1";
const MAX_PAGES = 30;
const MAX_AGE_MS = 48 * 3600 * 1000;
const READER_PAGE = /^\/(events\/\d+(\/market)?)?$/;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => ![PAGES, STATIC].includes(key)).map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

async function trim(cache, max) {
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - max)).map((key) => cache.delete(key)));
}

async function page(request, url) {
  const cache = await caches.open(PAGES);
  // Key by path only: the radar's ?period= variants and the event page share one offline copy each.
  const key = url.origin + url.pathname;
  try {
    const response = await fetch(request);
    if (response.ok && !response.redirected) {
      await cache.delete(key); // re-insert so trim() keeps the most recently viewed
      await cache.put(key, response.clone());
      await trim(cache, MAX_PAGES);
    }
    return response;
  } catch {
    // Older than 48h is not "the latest news" any more; treat it as missing.
    const fresh = (cached) => cached && Date.now() - Date.parse(cached.headers.get("date") || "") <= MAX_AGE_MS ? cached : null;
    return fresh(await cache.match(key)) || fresh(await cache.match(url.origin + "/")) || new Response(
      "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><body dir=rtl style='font-family:sans-serif;padding:2rem'>اتصال برقرار نیست. پس از اتصال دوباره تلاش کنید.<br><span dir=ltr>You are offline.</span>",
      { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } },
    );
  }
}

async function asset(request) {
  const cache = await caches.open(STATIC);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    await trim(cache, 200);
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === "navigate" && READER_PAGE.test(url.pathname)) {
    event.respondWith(page(request, url));
  } else if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/media/")) {
    event.respondWith(asset(request));
  }
});

self.addEventListener("push", (event) => {
  let message = {};
  try { message = event.data?.json() || {}; } catch { return; }
  const url = typeof message.url === "string" && /^\/events\/\d+$/.test(message.url)
    ? message.url : "/";
  event.waitUntil(self.registration.showNotification(message.title || "News Intelligence", {
    body: message.body || "", icon: "/icon.svg", data: { url },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data?.url || "/"));
});
