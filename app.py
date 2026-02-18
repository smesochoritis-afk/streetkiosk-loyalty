from __future__ import annotations

import io
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

import qrcode
from flask import Flask, Response, g, redirect, render_template, request, url_for

APP_TITLE = "QR Loyalty Demo"
DB_PATH = os.environ.get("QR_LOYALTY_DB", os.path.join(os.path.dirname(__file__), "demo.sqlite"))

# Demo rule: 5 scans -> 1 free coffee reward
TARGET_SCANS = 5
# Anti-abuse for demo: at most 1 scan per user per 30 seconds
MIN_SECONDS_BETWEEN_SCANS = 30

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")


def get_db() -> sqlite3.Connection:
    db = getattr(g, "_db", None)
    if db is None:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        g._db = db
    return db


@app.teardown_appcontext
def close_db(_exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS progress (
            user_id TEXT PRIMARY KEY,
            stamps INTEGER NOT NULL DEFAULT 0,
            reward_available INTEGER NOT NULL DEFAULT 0,
            last_scan_at INTEGER,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        """
    )
    db.commit()


def ensure_user(user_id: str) -> None:
    now = int(time.time())
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO users(user_id, created_at) VALUES(?, ?)",
        (user_id, now),
    )
    db.execute(
        "INSERT OR IGNORE INTO progress(user_id, stamps, reward_available, last_scan_at, updated_at) VALUES(?, 0, 0, NULL, ?)",
        (user_id, now),
    )
    db.commit()


@dataclass
class Status:
    user_id: str
    stamps: int
    reward_available: bool
    last_scan_at: Optional[int]


def get_status(user_id: str) -> Status:
    ensure_user(user_id)
    row = get_db().execute(
        "SELECT user_id, stamps, reward_available, last_scan_at FROM progress WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return Status(
        user_id=row["user_id"],
        stamps=int(row["stamps"]),
        reward_available=bool(row["reward_available"]),
        last_scan_at=(int(row["last_scan_at"]) if row["last_scan_at"] is not None else None),
    )


def can_scan(status: Status) -> tuple[bool, int]:
    if status.last_scan_at is None:
        return True, 0
    elapsed = int(time.time()) - status.last_scan_at
    if elapsed >= MIN_SECONDS_BETWEEN_SCANS:
        return True, 0
    return False, (MIN_SECONDS_BETWEEN_SCANS - elapsed)


@app.before_request
def _before_request():
    init_db()


@app.get("/")
def index():
    # Choose a demo user id (can be changed via ?user=)
    user_id = request.args.get("user", "demo")
    status = get_status(user_id)
    scan_url = url_for("scan", _external=True) + f"?user={user_id}"
    status_url = url_for("status", _external=True) + f"?user={user_id}"
    redeem_url = url_for("redeem", _external=True) + f"?user={user_id}"
    return render_template(
        "index.html",
        title=APP_TITLE,
        user_id=user_id,
        target=TARGET_SCANS,
        status=status,
        scan_url=scan_url,
        status_url=status_url,
        redeem_url=redeem_url,
    )


@app.get("/qr")
def qr():
    # QR that points to the scan endpoint
    user_id = request.args.get("user", "demo")
    ensure_user(user_id)
    scan_url = url_for("scan", _external=True) + f"?user={user_id}"

    img = qrcode.make(scan_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


@app.get("/status")
def status():
    user_id = request.args.get("user", "demo")
    status = get_status(user_id)
    remaining = max(0, TARGET_SCANS - status.stamps)
    return render_template(
        "status.html",
        title=f"Κατάσταση - {APP_TITLE}",
        user_id=user_id,
        target=TARGET_SCANS,
        remaining=remaining,
        status=status,
        scan_url=url_for("scan") + f"?user={user_id}",
        redeem_url=url_for("redeem") + f"?user={user_id}",
        home_url=url_for("index") + f"?user={user_id}",
    )


@app.get("/scan")
def scan():
    user_id = request.args.get("user", "demo")
    st = get_status(user_id)
    ok, wait_s = can_scan(st)

    if not ok:
        return render_template(
            "scan_result.html",
            title=f"Scan - {APP_TITLE}",
            user_id=user_id,
            ok=False,
            message=f"Πολύ γρήγορα! Ξαναδοκίμασε σε {wait_s} δευτερόλεπτα.",
            status=st,
            target=TARGET_SCANS,
            home_url=url_for("index") + f"?user={user_id}",
            status_url=url_for("status") + f"?user={user_id}",
        )

    now = int(time.time())
    db = get_db()

    # If reward already available, scans don't add more (demo behavior)
    if st.reward_available:
        db.execute(
            "UPDATE progress SET last_scan_at=?, updated_at=? WHERE user_id=?",
            (now, now, user_id),
        )
        db.commit()
        st2 = get_status(user_id)
        return render_template(
            "scan_result.html",
            title=f"Scan - {APP_TITLE}",
            user_id=user_id,
            ok=True,
            message="Έχεις ήδη διαθέσιμο δώρο 🎁 Πήγαινε για εξαργύρωση!",
            status=st2,
            target=TARGET_SCANS,
            home_url=url_for("index") + f"?user={user_id}",
            status_url=url_for("status") + f"?user={user_id}",
        )

    new_stamps = st.stamps + 1
    reward = 1 if new_stamps >= TARGET_SCANS else 0

    db.execute(
        "UPDATE progress SET stamps=?, reward_available=?, last_scan_at=?, updated_at=? WHERE user_id=?",
        (new_stamps if not reward else TARGET_SCANS, reward, now, now, user_id),
    )
    db.commit()

    st2 = get_status(user_id)
    if st2.reward_available:
        msg = "ΤΕΛΕΙΑ! Μόλις ξεκλείδωσες δώρο 🎉"
    else:
        msg = f"Καταχωρήθηκε! +1 σφραγίδα. Θέλεις ακόμη {TARGET_SCANS - st2.stamps}."

    return render_template(
        "scan_result.html",
        title=f"Scan - {APP_TITLE}",
        user_id=user_id,
        ok=True,
        message=msg,
        status=st2,
        target=TARGET_SCANS,
        home_url=url_for("index") + f"?user={user_id}",
        status_url=url_for("status") + f"?user={user_id}",
    )


@app.get("/redeem")
def redeem():
    user_id = request.args.get("user", "demo")
    st = get_status(user_id)
    if not st.reward_available:
        return render_template(
            "redeem.html",
            title=f"Εξαργύρωση - {APP_TITLE}",
            user_id=user_id,
            ok=False,
            message="Δεν υπάρχει διαθέσιμο δώρο ακόμα.",
            status=st,
            target=TARGET_SCANS,
            home_url=url_for("index") + f"?user={user_id}",
            status_url=url_for("status") + f"?user={user_id}",
        )

    # Redeem: reset stamps and reward flag (new cycle)
    now = int(time.time())
    db = get_db()
    db.execute(
        "UPDATE progress SET stamps=0, reward_available=0, updated_at=? WHERE user_id=?",
        (now, user_id),
    )
    db.commit()
    st2 = get_status(user_id)

    return render_template(
        "redeem.html",
        title=f"Εξαργύρωση - {APP_TITLE}",
        user_id=user_id,
        ok=True,
        message="Το δώρο εξαργυρώθηκε ✅ Καλό καφέ!",
        status=st2,
        target=TARGET_SCANS,
        home_url=url_for("index") + f"?user={user_id}",
        status_url=url_for("status") + f"?user={user_id}",
    )


@app.get("/admin/reset")
def admin_reset():
    # Very simple demo admin reset
    user_id = request.args.get("user", "demo")
    ensure_user(user_id)
    now = int(time.time())
    db = get_db()
    db.execute(
        "UPDATE progress SET stamps=0, reward_available=0, last_scan_at=NULL, updated_at=? WHERE user_id=?",
        (now, user_id),
    )
    db.commit()
    return redirect(url_for("index") + f"?user={user_id}")


if __name__ == "__main__":
    # Run: python app.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
