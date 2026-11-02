import json, os, re, logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, send_from_directory
import psycopg
from psycopg.rows import dict_row
from pywebpush import webpush, WebPushException

app=Flask(__name__,static_folder=None)
logging.basicConfig(level=logging.INFO)
DB=os.environ.get("DATABASE_URL","")
VAPID_PRIVATE=os.environ.get("VAPID_PRIVATE_KEY","").replace("\\\\n","\\n")
VAPID_PUBLIC=os.environ.get("VAPID_PUBLIC_KEY","")
VAPID_SUBJECT=os.environ.get("VAPID_SUBJECT","mailto:admin@example.com")
CRON_SECRET=os.environ.get("CRON_SECRET","")

def db():
    if not DB: raise RuntimeError("DATABASE_URL non configurato")
    return psycopg.connect(DB,autocommit=True,row_factory=dict_row)

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
          client_id text PRIMARY KEY, token text NOT NULL, subscription jsonb NOT NULL,
          tasks jsonb NOT NULL DEFAULT '[]', done jsonb NOT NULL DEFAULT '{}',
          minutes_before integer NOT NULL DEFAULT 10, tz text NOT NULL DEFAULT 'Europe/Rome',
          updated_at timestamptz NOT NULL DEFAULT now())""")
        c.execute("""CREATE TABLE IF NOT EXISTS sent_notifications (
          client_id text NOT NULL, task_id text NOT NULL, event_date text NOT NULL,
          PRIMARY KEY(client_id,task_id,event_date))""")

@app.get("/")
def home():return send_from_directory(".","index.html")
@app.get("/<path:path>")
def assets(path):
    if path not in ("index.html","manifest.webmanifest","sw.js","icons/icon-192.png","icons/icon-512.png"):return ("Not found",404)
    return send_from_directory(".",path)
@app.get("/api/health")
def health():return jsonify(ok=True)
@app.get("/api/push-key")
def key():
    if not VAPID_PUBLIC:return jsonify(error="VAPID_PUBLIC_KEY non configurata"),503
    return jsonify(publicKey=VAPID_PUBLIC)

def auth_payload():
    data=request.get_json(silent=True) or {}
    client=data.get("clientId","")
    token=request.headers.get("X-Client-Token","")
    if not re.fullmatch(r"[a-f0-9-]{36}",client) or len(token)<50:raise ValueError("Identificativo client non valido")
    return data,client,token

@app.post("/api/subscribe")
def subscribe():
    try:
        data,client,token=auth_payload()
        sub=data.get("subscription",{})
        if not isinstance(sub,dict) or not str(sub.get("endpoint","")).startswith("https://") or not sub.get("keys",{}).get("p256dh") or not sub.get("keys",{}).get("auth"):raise ValueError("Subscription non valida")
        tasks=data.get("tasks",[]);done=data.get("done",{})
        if not isinstance(tasks,list) or not isinstance(done,dict) or len(tasks)>250 or len(done)>5000:raise ValueError("Troppi dati")
        minutes=int(data.get("before",10))
        if minutes not in (0,5,10,15,30):raise ValueError("Anticipo non valido")
        tz=data.get("timezone","Europe/Rome")
        ZoneInfo(tz)
        with db() as c:
            old=c.execute("SELECT token FROM subscriptions WHERE client_id=%s",(client,)).fetchone()
            if old and old["token"]!=token:return jsonify(error="Client non autorizzato"),403
            c.execute("""INSERT INTO subscriptions(client_id,token,subscription,tasks,done,minutes_before,tz)
             VALUES(%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT(client_id) DO UPDATE SET subscription=excluded.subscription,tasks=excluded.tasks,
             done=excluded.done,minutes_before=excluded.minutes_before,tz=excluded.tz,updated_at=now()""",
             (client,token,json.dumps(sub),json.dumps(tasks),json.dumps(done),minutes,tz))
        return jsonify(ok=True)
    except (ValueError,KeyError) as e:return jsonify(error=str(e)),400

def existing(client,token):
    with db() as c:return c.execute("SELECT * FROM subscriptions WHERE client_id=%s AND token=%s",(client,token)).fetchone()

@app.post("/api/unsubscribe")
def unsubscribe():
    try:data,client,token=auth_payload()
    except ValueError as e:return jsonify(error=str(e)),400
    with db() as c:c.execute("DELETE FROM subscriptions WHERE client_id=%s AND token=%s",(client,token))
    return jsonify(ok=True)

def push(sub,title,body,tag):
    webpush(subscription_info=sub,data=json.dumps({"title":title,"body":body,"tag":tag}),
            vapid_private_key=VAPID_PRIVATE,vapid_claims={"sub":VAPID_SUBJECT},ttl=3600)

@app.post("/api/test")
def test():
    try:data,client,token=auth_payload()
    except ValueError as e:return jsonify(error=str(e)),400
    row=existing(client,token)
    if not row:return jsonify(error="Iscrizione non trovata"),404
    try:push(row["subscription"],"⚡ Routine Quest","Le notifiche push funzionano anche con l'app chiusa!","test")
    except WebPushException as e:return jsonify(error=f"Invio push non riuscito: {e.response.status_code if e.response else 'errore'}"),502
    return jsonify(ok=True)

def due(t,day,weekday):
    if t.get("repeat")=="once":return t.get("date")==day
    return weekday in t.get("days",[])

def dispatch(now=None):
    now=now or datetime.now(timezone.utc)
    sent=0
    with db() as c:
        rows=c.execute("SELECT * FROM subscriptions").fetchall()
        for row in rows:
            try:
                local=now.astimezone(ZoneInfo(row["tz"]))
                for delta in (0,1):
                    day_dt=local.date()+timedelta(days=delta)
                    day=day_dt.isoformat()
                    weekday=day_dt.weekday()
                    for t in row["tasks"]:
                        if not isinstance(t,dict) or not due(t,day,weekday):continue
                        tid=str(t.get("id",""))
                        start=t.get("start","")
                        if not tid or not re.fullmatch(r"\\d{2}:\\d{2}",start):continue
                        h,m=map(int,start.split(":"))
                        if h>23 or m>59:continue
                        event=datetime(day_dt.year,day_dt.month,day_dt.day,h,m,tzinfo=ZoneInfo(row["tz"]))
                        target=event-timedelta(minutes=row["minutes_before"])
                        # Five-minute cron tolerance; never send old reminders.
                        if not (target<=local<target+timedelta(minutes=5)):continue
                        if row["done"].get(tid+"@"+day):continue
                        # Reserve first to prevent duplicates if cron jobs overlap.
                        reserved=c.execute("""INSERT INTO sent_notifications(client_id,task_id,event_date)
                          VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING client_id""",(row["client_id"],tid,day)).fetchone()
                        if not reserved:continue
                        try:
                            push(row["subscription"],"⏰ "+str(t.get("name","Attività"))[:80],
                                 f"Inizia alle {start} · +{t.get('points',0)} XP",tid+"@"+day)
                            sent+=1
                        except WebPushException as e:
                            if e.response is not None and e.response.status_code in (404,410):
                                c.execute("DELETE FROM subscriptions WHERE client_id=%s",(row["client_id"],))
                            else:
                                logging.exception("Invio fallito per %s",row["client_id"])
                                c.execute("DELETE FROM sent_notifications WHERE client_id=%s AND task_id=%s AND event_date=%s",(row["client_id"],tid,day))
            except Exception:logging.exception("Errore subscription")
        c.execute("DELETE FROM sent_notifications WHERE event_date < %s",((now-timedelta(days=45)).date().isoformat(),))
    return sent

@app.post("/api/dispatch")
def dispatch_route():
    if not CRON_SECRET or request.headers.get("Authorization")!="Bearer "+CRON_SECRET:return jsonify(error="Non autorizzato"),403
    return jsonify(ok=True,sent=dispatch())

if __name__=="__main__":app.run(debug=True,port=8000)
