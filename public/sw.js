const CACHE_NAME = 'lexmatches-v1';
const STATIC_CACHE = 'lexmatches-static-v1';
const DATA_CACHE = 'lexmatches-data-v1';

// Static assets to cache on install
const STATIC_ASSETS = [
  '/',
  '/index.html',
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name.startsWith('lexmatches-') && name !== STATIC_CACHE && name !== DATA_CACHE)
          .map((name) => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

// Fetch event - network first for API, cache first for static
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') return;

  // Handle Supabase API requests (pages, books data)
  if (url.hostname.includes('supabase.co')) {
    event.respondWith(networkFirstThenCache(request, DATA_CACHE));
    return;
  }

  // Handle static assets
  if (request.destination === 'script' || 
      request.destination === 'style' || 
      request.destination === 'image' ||
      request.destination === 'font') {
    event.respondWith(cacheFirstThenNetwork(request, STATIC_CACHE));
    return;
  }

  // For navigation requests, try network first
  if (request.mode === 'navigate') {
    event.respondWith(networkFirstThenCache(request, STATIC_CACHE));
    return;
  }
});

// Network first, fall back to cache
async function networkFirstThenCache(request, cacheName) {
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    throw error;
  }
}

// Cache first, fall back to network
async function cacheFirstThenNetwork(request, cacheName) {
  const cachedResponse = await caches.match(request);
  if (cachedResponse) {
    return cachedResponse;
  }
  
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    throw error;
  }
}

// Listen for messages to cache specific pages
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CACHE_PAGES') {
    const { pages } = event.data;
    event.waitUntil(cachePages(pages));
  }
  
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    event.waitUntil(
      caches.keys().then((cacheNames) => {
        return Promise.all(cacheNames.map((name) => caches.delete(name)));
      })
    );
  }
});

async function cachePages(pages) {
  const cache = await caches.open(DATA_CACHE);
  // Pages data is already JSON, store as-is
  for (const page of pages) {
    const cacheKey = new Request(`/cached-page/${page.id}`);
    const response = new Response(JSON.stringify(page), {
      headers: { 'Content-Type': 'application/json' }
    });
    await cache.put(cacheKey, response);
  }
}
