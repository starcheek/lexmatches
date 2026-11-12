// Retired service worker. Earlier versions cached authenticated /api responses by URL, so a second
// user on the same browser could be served the first user's books. Browsers that still have it
// installed fetch this file on their next update check: it deletes every lexmatches cache,
// unregisters itself and reloads open tabs so they are no longer controlled. Keep this file until
// old installs have had time to update (it is never registered by the app any more).
self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k.startsWith('lexmatches-')).map((k) => caches.delete(k)));
      await self.registration.unregister();
      const clients = await self.clients.matchAll({ type: 'window' });
      clients.forEach((client) => client.navigate(client.url));
    })(),
  );
});
