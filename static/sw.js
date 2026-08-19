const CACHE_NAME = 'harry-beer-v2';
const ASSETS = [
    '/',
    '/offline',
    '/static/css/style.css',
    '/static/img/logo.png',
    '/static/img/icon-152x152.png',
    '/static/img/icon-192x192.png',
    '/static/img/icon-512x512.png',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[Service Worker] Caching App Shell');
            // No hacemos fail si algún asset externo no carga
            return Promise.all(ASSETS.map(url => {
                return fetch(url).then(response => {
                    if (!response.ok) throw new Error('Not ok');
                    return cache.put(url, response);
                }).catch(error => {
                    console.error('[Service Worker] Failed to cache:', url, error);
                });
            }));
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keyList) => {
            return Promise.all(keyList.map((key) => {
                if (key !== CACHE_NAME) {
                    console.log('[Service Worker] Removing old cache', key);
                    return caches.delete(key);
                }
            }));
        })
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET' || !event.request.url.startsWith('http')) {
        return;
    }

    event.respondWith(
        fetch(event.request).catch(async () => {
            const cache = await caches.open(CACHE_NAME);
            const cachedResponse = await cache.match(event.request);
            if (cachedResponse) {
                return cachedResponse;
            }
            // Si es una petición de página HTML y falla, mostramos offline
            if (event.request.headers.get('accept').includes('text/html')) {
                return cache.match('/offline');
            }
            return new Response('Network error happened', { status: 408, headers: { 'Content-Type': 'text/plain' } });
        })
    );
});
