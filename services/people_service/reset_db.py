import sys
sys.path.insert(0, '.')
from app.config import Settings
from app.database import Database
db = Database(Settings(db_host='localhost', db_port=5433, db_user='simulator', db_password='simulator_dev', db_name='revenue_recovery'))
db.drop_schema()
db.create_schema()
print('Database reset - all tables dropped and recreated empty')
