const CACHE_NAME = 'zuihouYiwu-v1';

// 需要缓存的静态资源
const STATIC_ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/main.js',
  '/static/js/local_storage.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// ==================== 安装：缓存静态资源 ====================
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// ==================== 激活：清理旧缓存 ====================
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// ==================== 请求拦截策略 ====================
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API请求：永远走网络，不缓存
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // 静态资源：缓存优先，缓存没有再走网络
  if (
    url.pathname.startsWith('/static/') ||
    url.pathname === '/'
  ) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        return cached || fetch(event.request).then(response => {
          // 顺手缓存新资源
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, clone);
          });
          return response;
        });
      })
    );
    return;
  }

  // 其他页面请求：网络优先，断网时用缓存
  event.respondWith(
    fetch(event.request)
      .then(response => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, clone);
        });
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});