
const CACHE = 'routine-quest-v6';

const ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png'
];

// Installazione del Service Worker
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Attivazione e rimozione delle vecchie cache
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys =>
        Promise.all(
          keys
            .filter(key => key.startsWith('routine-quest-') && key !== CACHE)
            .map(key => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// Aggiornamento online, fallback offline
self.addEventListener('fetch', event => {
  const request = event.request;

  if (
    request.method !== 'GET' ||
    new URL(request.url).origin !== self.location.origin
  ) {
    return;
  }

  // Non memorizzare le richieste API
  if (new URL(request.url).pathname.startsWith('/api/')) {
    return;
  }

  event.respondWith(
    fetch(request)
      .then(response => {
        if (response.ok) {
          const copy = response.clone();

          event.waitUntil(
            caches.open(CACHE).then(cache => cache.put(request, copy))
          );
        }

        return response;
      })
      .catch(async () => {
        const cached = await caches.match(request);

        if (cached) {
          return cached;
        }

        throw new Error('Risorsa non disponibile offline');
      })
  );
});

// Ricezione delle notifiche push
self.addEventListener('push', event => {
  let data = {
    title: '⚡ Routine Quest',
    body: 'Hai una nuova attività!',
    tag: 'routine-quest'
  };

  try {
    if (event.data) {
      data = { ...data, ...event.data.json() };
    }
  } catch (error) {
    console.error('Errore lettura push:', error);
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      tag: data.tag,
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      data: {
        url: '/'
      }
    })
  );
});

// Apertura dell'app quando si tocca la notifica
self.addEventListener('notificationclick', event => {
  event.notification.close();

  event.waitUntil(
    self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true
    }).then(async clients => {
      for (const client of clients) {
        if ('focus' in client) {
          return client.focus();
        }
      }

      return self.clients.openWindow('/');
    })
  );
});
