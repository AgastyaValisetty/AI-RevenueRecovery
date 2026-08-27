"""Reset all database tables (including ledger, recovery, payment attempts).

Run from the services/people_service directory:
    python reset_db.py
"""
import sys
sys.path.insert(0, '.')
from app.config import Settings
from app.database import Database

def reset_database():
    settings = Settings.from_env()
    db = Database(settings)
    db.drop_schema()
    db.create_schema()
    print('Database reset - all tables dropped and recreated empty')
    return db

if __name__ == '__main__':
    reset_database()
