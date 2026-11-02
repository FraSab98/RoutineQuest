onst CACHE='routine-quest-v4';const ASSETS=['./','./index.html','./manifest.webmanifest','./icons/icon-192.png','./icons/icon-512.png'];self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting()))});self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});self.addEventListener('fetch',e=>{if(e.request.method!=='GET'||new URL(e.request.url).origin!==self.location.origin)return;e.respondWith(caches.match(e.request).then(cached=>cached||fetch(e.request).then(res=>{if(res.ok){const copy=res.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return res}))) });self.addEventListener('notificationclick',e=>{e.notification.close();e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(cs=>cs.length?cs[0].focus():self.clients.openWindow('./index.html')))});self.addEventListener('push',event=>{
 let data={title:'⚡ Routine Quest',body:'Hai una nuova attività!',tag:'routine-quest'};
 try{if(event.data)data={...data,...event.data.json()}}catch(e){}
 event.waitUntil(self.registration.showNotification(data.title,{body:data.body,tag:data.tag,icon:'./icons/icon-192.png',badge:'./icons/icon-192.png',data:{url:'./index.html'}}));
  
self.addEventListener("push", (event) => {
  let data = {};

  try {
    if (event.data) {
      data = event.data.json();
    }
  } catch (error) {
    data = {
      title: "Routine Quest",
      body: event.data ? event.data.text() : "Hai un nuovo promemoria!"
    };
  }

  const title = data.title || "Routine Quest";

  const options = {
    body: data.body || "È il momento della tua attività!",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: data.tag || "routine-quest-reminder",
    data: {
      url: "/"
    }
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});
