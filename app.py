import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
from flask import Flask, jsonify, request, send_from_directory
from psycopg.rows import dict_row
from pywebpush import WebPushException, webpush

app = Flask(__name__, static_folder=None)
logging.basicConfig(level=logging.INFO)

DB = os.environ.get("DATABASE_URL", "")
VAPID_PRIVATE = os.environ.get("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
VAPID_PUBLIC = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")
CRON_SECRET = os.environ.get("CRON_SECRET", "")


def db():
    if not DB:
        raise RuntimeError("DATABASE_URL non configurato")
    return psycopg.connect(DB, autocommit=True, row_factory=dict_row)


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                client_id text PRIMARY KEY,
                token text NOT NULL,
                subscription jsonb NOT NULL,
                tasks jsonb NOT NULL DEFAULT '[]',
                done jsonb NOT NULL DEFAULT '{}',
                minutes_before integer NOT NULL DEFAULT 10,
                tz text NOT NULL DEFAULT 'Europe/Rome',
                updated_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_notifications (
                client_id text NOT NULL,
                task_id text NOT NULL,
                event_date text NOT NULL,
                PRIMARY KEY (client_id, task_id, event_date)
            )
        """)
    app.logger.info("Database: tabelle verificate")


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


@app.get("/<path:path>")
def assets(path):
    allowed = {
        "index.html", "manifest.webmanifest", "sw.js",
        "icons/icon-192.png", "icons/icon-512.png",
    }
    if path not in allowed:
        return "Not found", 404
    return send_from_directory(".", path)


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/api/push-key")
def key():
    if not VAPID_PUBLIC:
        return jsonify(error="VAPID_PUBLIC_KEY non configurata"), 503
    return jsonify(publicKey=VAPID_PUBLIC)


def auth_payload():
    data = request.get_json(silent=True) or {}
    client = data.get("clientId", "")
    token = request.headers.get("X-Client-Token", "")
    if not isinstance(client, str) or not re.fullmatch(r"[a-f0-9-]{36}", client):
        raise ValueError("Identificativo client non valido")
    if len(token) < 50:
        raise ValueError("Token client non valido")
    return data, client, token


@app.post("/api/subscribe")
def subscribe():
    try:
        data, client, token = auth_payload()
        sub = data.get("subscription", {})
        if (
            not isinstance(sub, dict)
            or not str(sub.get("endpoint", "")).startswith("https://")
            or not isinstance(sub.get("keys"), dict)
            or not sub["keys"].get("p256dh")
            or not sub["keys"].get("auth")
        ):
            raise ValueError("Subscription non valida")

        tasks = data.get("tasks", [])
        done = data.get("done", {})
        if not isinstance(tasks, list) or not isinstance(done, dict):
            raise ValueError("Formato attività non valido")
        if len(tasks) > 250 or len(done) > 5000:
            raise ValueError("Troppi dati")

        minutes = int(data.get("before", 10))
        if minutes not in (0, 5, 10, 15, 30):
            raise ValueError("Anticipo non valido")
        tz = data.get("timezone", "Europe/Rome")
        ZoneInfo(tz)

        with db() as conn:
            old = conn.execute(
                "SELECT token FROM subscriptions WHERE client_id=%s", (client,)
            ).fetchone()
            if old and old["token"] != token:
                return jsonify(error="Client non autorizzato"), 403
            conn.execute("""
                INSERT INTO subscriptions (
                    client_id, token, subscription, tasks, done, minutes_before, tz
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (client_id) DO UPDATE SET
                    subscription=excluded.subscription,
                    tasks=excluded.tasks,
                    done=excluded.done,
                    minutes_before=excluded.minutes_before,
                    tz=excluded.tz,
                    updated_at=now()
            """, (
                client, token, json.dumps(sub), json.dumps(tasks),
                json.dumps(done), minutes, tz,
            ))

        app.logger.info(
            "PUSH SYNC: tasks=%s, timezone=%s, minutes_before=%s",
            len(tasks), tz, minutes,
        )
        return jsonify(ok=True)
    except (ValueError, KeyError, TypeError) as exc:
        app.logger.warning("PUSH SYNC rifiutato: %s", exc)
        return jsonify(error=str(exc)), 400


def existing(client, token):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM subscriptions WHERE client_id=%s AND token=%s",
            (client, token),
        ).fetchone()


@app.post("/api/unsubscribe")
def unsubscribe():
    try:
        _, client, token = auth_payload()
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    with db() as conn:
        conn.execute(
            "DELETE FROM subscriptions WHERE client_id=%s AND token=%s",
            (client, token),
        )
    return jsonify(ok=True)


def push(sub, title, body, tag):
    webpush(
        subscription_info=sub,
        data=json.dumps({"title": title, "body": body, "tag": tag}),
        vapid_private_key=VAPID_PRIVATE,
        vapid_claims={"sub": VAPID_SUBJECT},
        ttl=3600,
    )


@app.post("/api/test")
def test():
    try:
        _, client, token = auth_payload()
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    row = existing(client, token)
    if not row:
        return jsonify(error="Iscrizione non trovata"), 404
    try:
        push(
            row["subscription"], "⚡ Routine Quest",
            "Le notifiche push funzionano anche con l'app chiusa!", "test",
        )
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else "errore"
        app.logger.warning("PUSH TEST fallito: status=%s", status)
        return jsonify(error=f"Invio push non riuscito: {status}"), 502
    app.logger.info("PUSH TEST: richiesta inviata")
    return jsonify(ok=True)


def due(task, day, weekday):
    if task.get("repeat") == "once":
        return task.get("date") == day
    return weekday in task.get("days", [])


def dispatch(now=None):
    now = now or datetime.now(timezone.utc)
    sent = 0
    with db() as conn:
        rows = conn.execute("SELECT * FROM subscriptions").fetchall()
        app.logger.info(
            "DISPATCH: subscriptions=%s, tasks_per_client=%s",
            len(rows), [len(row["tasks"]) for row in rows],
        )

        for row in rows:
            try:
                tz = ZoneInfo(row["tz"])
                local = now.astimezone(tz)
                app.logger.info(
                    "DISPATCH CLIENT: local_time=%s, timezone=%s, tasks=%s, before=%s",
                    local.strftime("%Y-%m-%d %H:%M:%S"), row["tz"],
                    len(row["tasks"]), row["minutes_before"],
                )
                for delta in (0, 1):
                    day_dt = local.date() + timedelta(days=delta)
                    day = day_dt.isoformat()
                    weekday = day_dt.weekday()  # Lunedi=0, domenica=6
                    for task in row["tasks"]:
                        if not isinstance(task, dict):
                            continue
                        if not due(task, day, weekday):
                            continue

                        tid = str(task.get("id", ""))
                        start = task.get("start", "")
                        # Correzione: una sola barra rovesciata nella raw regex.
                        if not tid or not isinstance(start, str) or not re.fullmatch(r"\d{2}:\d{2}", start):
                            app.logger.info("DISPATCH SKIP: id/orario non valido")
                            continue
                        h, m = map(int, start.split(":"))
                        if h > 23 or m > 59:
                            app.logger.info("DISPATCH SKIP: orario fuori intervallo")
                            continue

                        event = datetime(
                            day_dt.year, day_dt.month, day_dt.day,
                            h, m, tzinfo=tz,
                        )
                        target = event - timedelta(minutes=row["minutes_before"])
                        # Finestra di tolleranza di 5 minuti.
                        if not (target <= local < target + timedelta(minutes=5)):
                            continue

                        app.logger.info(
                            "DISPATCH MATCH: event_date=%s, start=%s, target=%s",
                            day, start, target.strftime("%H:%M"),
                        )
                        if row["done"].get(tid + "@" + day):
                            app.logger.info("DISPATCH SKIP: attività già completata")
                            continue

                        reserved = conn.execute("""
                            INSERT INTO sent_notifications (client_id, task_id, event_date)
                            VALUES (%s, %s, %s)
                            ON CONFLICT DO NOTHING RETURNING client_id
                        """, (row["client_id"], tid, day)).fetchone()
                        if not reserved:
                            app.logger.info("DISPATCH SKIP: notifica già registrata")
                            continue

                        try:
                            push(
                                row["subscription"],
                                "⏰ " + str(task.get("name", "Attività"))[:80],
                                f"Inizia alle {start} · +{task.get('points', 0)} XP",
                                tid + "@" + day,
                            )
                            sent += 1
                            app.logger.info("DISPATCH SENT: event_date=%s", day)
                        except WebPushException as exc:
                            if exc.response is not None and exc.response.status_code in (404, 410):
                                conn.execute(
                                    "DELETE FROM subscriptions WHERE client_id=%s",
                                    (row["client_id"],),
                                )
                                app.logger.warning("DISPATCH: subscription scaduta, eliminata")
                            else:
                                app.logger.exception("DISPATCH: invio Web Push fallito")
                                conn.execute("""
                                    DELETE FROM sent_notifications
                                    WHERE client_id=%s AND task_id=%s AND event_date=%s
                                """, (row["client_id"], tid, day))
            except Exception:
                app.logger.exception("DISPATCH: errore elaborazione subscription")

        conn.execute(
            "DELETE FROM sent_notifications WHERE event_date < %s",
            ((now - timedelta(days=45)).date().isoformat(),),
        )
    app.logger.info("ROUTINE QUEST PUSH: sent=%s", sent)
    return sent


@app.post("/api/dispatch")
def dispatch_route():
    if not CRON_SECRET or request.headers.get("Authorization") != "Bearer " + CRON_SECRET:
        return jsonify(error="Non autorizzato"), 403
    sent = dispatch()
    return jsonify(ok=True, sent=sent)


if __name__ == "__main__":
    app.run(debug=True, port=8000)
