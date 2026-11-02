
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
