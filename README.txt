ROUTINE QUEST 3.0 — PWA + WEB PUSH CON RENDER

1) Crea un repository GitHub e carica TUTTI i file di questa cartella nella radice del repository.
2) Crea le chiavi VAPID sul tuo computer: pip install cryptography && python generate_vapid.py
   Conserva la chiave privata, NON inserirla nel repository.
3) Render Dashboard > New > Blueprint > collega il repository > applica render.yaml.
   Il blueprint richiede un servizio Web, un Cron Job e PostgreSQL.
   Controlla i prezzi correnti Render prima di confermare: queste risorse possono essere a pagamento.
4) Nei servizi Web e Cron, configura le stesse variabili:
   VAPID_PRIVATE_KEY = chiave PEM privata completa generata dal comando
   VAPID_PUBLIC_KEY = chiave pubblica generata dal comando
   VAPID_SUBJECT = mailto:tua-email@example.com (sostituisci con la tua email)
   DATABASE_URL viene collegato automaticamente dal blueprint.
   CRON_SECRET e' creato automaticamente nel Web Service (non serve al cron interno).
   Esegui il deploy di entrambi i servizi dopo aver impostato le variabili.
5) Apri l'URL HTTPS del servizio Web su Render, non il file index.html locale.
   Per iPhone: Safari > Condividi > Aggiungi alla schermata Home, apri l'app installata e attiva i promemoria.
   Per Android/desktop: installa la PWA quando il browser lo propone, poi attiva i promemoria.
6) Nell'app: Promemoria > Attiva promemoria > concedi il permesso > Invia notifica di prova.
   I promemoria vengono inviati ogni 5 minuti circa, non al secondo esatto. La consegna dipende dal sistema operativo,
   dalla connettivita', dai permessi e dal servizio push del browser.
7) Quando modifichi, aggiungi, elimini o completi un'attivita', la PWA sincronizza i dati dei promemoria con Render.
   Le statistiche e i progressi completi restano salvati nel browser: usa Esporta per i backup.
   Se cambi browser o dispositivo devi reimportare il backup e attivare le notifiche anche sul nuovo dispositivo.
8) Migrazione da Routine Quest 2.0: esporta il backup JSON dall'app precedente e importalo nella nuova.
   La migrazione delle iscrizioni push non e' automatica: attivale nuovamente.

NOTE IMPORTANTI
- Non esiste ancora un login multiutente: questa versione e' pensata per uso personale.
- Per una distribuzione pubblica a molti utenti servono autenticazione, rate limiting e misure anti-abuso.
- Render cron deve rimanere attivo per notificare anche quando la PWA e' chiusa.
- Render puo' fatturare il servizio web, il cron e il database: verifica il piano prima di attivare.
- Nessuna garanzia di consegna esatta se il telefono e' offline o blocca le notifiche.
