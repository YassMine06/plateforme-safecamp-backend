import sqlite3
import random
from datetime import datetime, timedelta

DB_PATH = "safecamp.db"

def seed():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Clear existing demo data if any, keep ANON-DEMO and ANON-TEST possibly, but we can just clear alerts and votes since that's what shows on the map.
    c.execute("DELETE FROM alerts")
    c.execute("DELETE FROM votes")

    print("Populating database with realistic data...")

    alerts_data = [
        # Active Alerts (3 confirmations or more)
        ("fire", "Lab Block", "Smoke coming from the chemistry lab on the 2nd floor", "active", 4, 0),
        ("suspicious", "Parking", "Person looking into cars near the east exit", "active", 3, 1),
        ("medical", "Cafeteria", "Student fainted near the main counter", "active", 5, 0),
        
        # Pending Alerts (Less than 3 confirmations)
        ("theft", "Library", "Backpack stolen from reading room B", "pending", 2, 0),
        ("vandalism", "Classrooms A", "Graffiti on the hallway walls", "pending", 1, 2),
        ("other", "Amphitheater A", "Projector is sparking during lecture", "pending", 2, 1),
        
        # Rejected Alerts (5 rejections or more)
        ("suspicious", "Main Entrance", "Thought I saw someone jump the fence, maybe not", "rejected", 0, 5),
    ]

    base_time = datetime.utcnow()

    for i, (atype, loc, desc, status, conf, rej) in enumerate(alerts_data):
        # Stagger the created_at times so the trend charts look nice
        created_at = (base_time - timedelta(days=random.randint(0, 5), hours=random.randint(1, 10))).strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("""
            INSERT INTO alerts (type, location, description, status, confirmations, rejections, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (atype, loc, desc, status, conf, rej, "ANON-DEMO", created_at))
        
        alert_id = c.lastrowid
        
        # Insert some dummy votes for these alerts
        if conf > 0:
            for j in range(conf):
                c.execute("INSERT INTO votes (alert_id, user_id, vote) VALUES (?, ?, ?)", (alert_id, f"ANON-VOTER-{j}", "confirm"))
        if rej > 0:
            for j in range(rej):
                c.execute("INSERT INTO votes (alert_id, user_id, vote) VALUES (?, ?, ?)", (alert_id, f"ANON-REJECTER-{j}", "reject"))

    # Also add some recent alerts without status change yet
    c.execute("""
        INSERT INTO alerts (type, location, description, status, confirmations, rejections, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("medical", "Classrooms B", "Twisted ankle on the stairs", "pending", 0, 0, "ANON-TEST", base_time.strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    conn.close()
    print("Database populated successfully!")

if __name__ == '__main__':
    seed()
