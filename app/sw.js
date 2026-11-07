// Service worker de la web instalable (PWA). Solo guarda la "cáscara" de la app (HTML, JS, CSS, íconos)
// para que abra rápido y muestre algo sin conexión. Nunca guarda datos: Google, el Sheet, Lemon Squeezy,
// Scryfall y demás son de otro dominio y pasan directo; los precios de Card Kingdom (data/) tampoco.
const CACHE = 'tcg-shell-v1';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  const scope = new URL(self.registration.scope);
  if (url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) return;
  const path = url.pathname.slice(scope.pathname.length);
  if (path.startsWith('data/')) return;

  // Los archivos de assets/ llevan un hash en el nombre: nunca cambian, se sirven de la caché.
  if (path.startsWith('assets/')) {
    event.respondWith(caches.match(request).then((hit) => hit || fetchAndKeep(request)));
    return;
  }
  // Todo lo demás (la página, el manifest): primero la red, así siempre está al día; sin red, la copia.
  event.respondWith(
    fetchAndKeep(request).catch(() =>
      caches.match(request, { ignoreSearch: true }).then((hit) => hit || caches.match(scope.href)).then((hit) => hit || Response.error()),
    ),
  );
});

function fetchAndKeep(request) {
  return fetch(request).then((response) => {
    if (response.ok && response.type === 'basic') {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request, copy));
    }
    return response;
  });
}
