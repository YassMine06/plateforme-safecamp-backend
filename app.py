from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, hashlib, random, string, os
from datetime import datetime, timedelta
import jwt

app = Flask(__name__)
CORS(app) # Allow all domains for production
SECRET_KEY = "safecamp-secret-key-2024"
DB_PATH = "safecamp.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anonymous_id TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            level TEXT DEFAULT 'Beginner',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            location TEXT NOT NULL,
            lat REAL,
            lng REAL,
            description TEXT,
            created_by TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            confirmations INTEGER DEFAULT 0,
            rejections INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            vote TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(alert_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            reward TEXT NOT NULL,
            points_spent INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

def gen_anon_id():
    chars = string.ascii_uppercase + string.digits
    return "ANON-" + "".join(random.choices(chars, k=4))

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def calc_level(points):
    if points < 50: return "Beginner"
    elif points < 150: return "Watcher"
    elif points < 300: return "Guardian"
    elif points < 500: return "Sentinel"
    else: return "Hero"

def token_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return jsonify({"error": "No token"}), 401
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user_id = data["user_id"]
        except:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.json
    pw = data.get("password", "")
    if len(pw) < 4:
        return jsonify({"error": "Password too short"}), 400
    conn = get_db()
    anon_id = gen_anon_id()
    while conn.execute("SELECT id FROM users WHERE anonymous_id=?", (anon_id,)).fetchone():
        anon_id = gen_anon_id()
    try:
        conn.execute("INSERT INTO users (anonymous_id, password) VALUES (?,?)", (anon_id, hash_pw(pw)))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
    conn.close()
    token = jwt.encode({"user_id": anon_id, "exp": datetime.utcnow() + timedelta(days=7)}, SECRET_KEY, algorithm="HS256")
    return jsonify({"token": token, "anonymous_id": anon_id})

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    anon_id = data.get("anonymous_id", "")
    pw = data.get("password", "")
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE anonymous_id=? AND password=?", (anon_id, hash_pw(pw))).fetchone()
    conn.close()
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401
    token = jwt.encode({"user_id": anon_id, "exp": datetime.utcnow() + timedelta(days=7)}, SECRET_KEY, algorithm="HS256")
    return jsonify({"token": token, "anonymous_id": anon_id})

@app.route("/api/profile", methods=["GET"])
@token_required
def profile():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE anonymous_id=?", (request.user_id,)).fetchone()
    alerts = conn.execute("SELECT * FROM alerts WHERE created_by=? ORDER BY created_at DESC LIMIT 10", (request.user_id,)).fetchall()
    votes = conn.execute("SELECT v.*, a.type, a.location, a.status FROM votes v JOIN alerts a ON v.alert_id=a.id WHERE v.user_id=? ORDER BY v.created_at DESC LIMIT 10", (request.user_id,)).fetchall()
    conn.close()
    return jsonify({
        "anonymous_id": user["anonymous_id"],
        "points": user["points"],
        "level": calc_level(user["points"]),
        "alerts_created": [dict(a) for a in alerts],
        "votes": [dict(v) for v in votes]
    })

@app.route("/api/alerts", methods=["GET"])
@token_required
def get_alerts():
    status = request.args.get("status", "all")
    conn = get_db()
    if status == "all":
        rows = conn.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM alerts WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/alerts", methods=["POST"])
@token_required
def create_alert():
    data = request.json
    atype = data.get("type", "")
    location = data.get("location", "")
    lat = data.get("lat", 0)
    lng = data.get("lng", 0)
    desc = data.get("description", "")
    if not atype or not location:
        return jsonify({"error": "Missing fields"}), 400
    conn = get_db()
    conn.execute("INSERT INTO alerts (type,location,lat,lng,description,created_by) VALUES (?,?,?,?,?,?)",
                 (atype, location, lat, lng, desc, request.user_id))
    conn.execute("UPDATE users SET points=points+10 WHERE anonymous_id=?", (request.user_id,))
    uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({"id": uid, "message": "Alert created, awaiting confirmation"})

@app.route("/api/alerts/<int:alert_id>/vote", methods=["POST"])
@token_required
def vote_alert(alert_id):
    data = request.json
    vote = data.get("vote", "")
    if vote not in ["confirm", "reject"]:
        return jsonify({"error": "Invalid vote"}), 400
    conn = get_db()
    alert = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not alert:
        conn.close()
        return jsonify({"error": "Alert not found"}), 404
    if alert["created_by"] == request.user_id:
        conn.close()
        return jsonify({"error": "Cannot vote on own alert"}), 403
    existing = conn.execute("SELECT id FROM votes WHERE alert_id=? AND user_id=?", (alert_id, request.user_id)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Already voted"}), 409
    conn.execute("INSERT INTO votes (alert_id,user_id,vote) VALUES (?,?,?)", (alert_id, request.user_id, vote))
    if vote == "confirm":
        conn.execute("UPDATE alerts SET confirmations=confirmations+1 WHERE id=?", (alert_id,))
        conn.execute("UPDATE users SET points=points+5 WHERE anonymous_id=?", (request.user_id,))
        new_conf = alert["confirmations"] + 1
        if new_conf >= 3:
            conn.execute("UPDATE alerts SET status='active' WHERE id=?", (alert_id,))
    else:
        conn.execute("UPDATE alerts SET rejections=rejections+1 WHERE id=?", (alert_id,))
        conn.execute("UPDATE users SET points=points+3 WHERE anonymous_id=?", (request.user_id,))
        new_rej = alert["rejections"] + 1
        if new_rej >= 5:
            conn.execute("UPDATE alerts SET status='rejected' WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Vote recorded"})

@app.route("/api/analytics", methods=["GET"])
@token_required
def analytics():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='active'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='pending'").fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='rejected'").fetchone()[0]
    by_type = conn.execute("SELECT type, COUNT(*) as count FROM alerts GROUP BY type").fetchall()
    by_location = conn.execute("SELECT location, COUNT(*) as count FROM alerts GROUP BY location ORDER BY count DESC LIMIT 5").fetchall()
    trend = conn.execute("""SELECT date(created_at) as day, COUNT(*) as count 
        FROM alerts WHERE created_at >= date('now','-7 days') GROUP BY day ORDER BY day""").fetchall()
    conn.close()
    return jsonify({
        "total": total, "active": active, "pending": pending, "rejected": rejected,
        "by_type": [dict(r) for r in by_type],
        "by_location": [dict(r) for r in by_location],
        "trend": [dict(r) for r in trend]
    })

@app.route("/api/rewards/redeem", methods=["POST"])
@token_required
def redeem():
    data = request.json
    reward = data.get("reward", "")
    cost = data.get("cost", 0)
    conn = get_db()
    user = conn.execute("SELECT points FROM users WHERE anonymous_id=?", (request.user_id,)).fetchone()
    if user["points"] < cost:
        conn.close()
        return jsonify({"error": "Not enough points"}), 400
    conn.execute("UPDATE users SET points=points-? WHERE anonymous_id=?", (cost, request.user_id))
    conn.execute("INSERT INTO redemptions (user_id,reward,points_spent) VALUES (?,?,?)", (request.user_id, reward, cost))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Redeemed: {reward}"})

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
