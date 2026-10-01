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
