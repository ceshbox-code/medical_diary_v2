#!/usr/bin/env python3
import os, sqlite3
from werkzeug.security import generate_password_hash

db = os.getenv("DATABASE_PATH", "/data/medical_diary.db")
u = os.getenv("ADMIN_USERNAME", "admin")
p = os.getenv("ADMIN_PASSWORD")
if not p: raise SystemExit("ADMIN_PASSWORD is not set")
c = sqlite3.connect(db)
h = generate_password_hash(p)
if c.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
    c.execute("UPDATE users SET password_hash=?, status='active', is_admin=1 WHERE username=?", (h, u))
    print(f"Password updated for {u}")
else:
    c.execute("INSERT INTO users(username,password_hash,display_name,status,is_admin) VALUES(?,?,?,'active',1)", (u, h, u))
    print(f"User created: {u}")
c.commit(); c.close()
