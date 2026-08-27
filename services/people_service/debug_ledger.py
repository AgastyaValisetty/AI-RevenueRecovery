import sys
sys.path.insert(0, '.')
from app.config import Settings
from app.database import Database
from app.repositories import LedgerRepository, PaymentIntentRepository

db = Database(Settings(db_host='localhost', db_port=5433, db_user='simulator', db_password='simulator_dev', db_name='revenue_recovery'))
ledger_repo = LedgerRepository(db)
intent_repo = PaymentIntentRepository(db)

# Check failed ledger entries
entries = ledger_repo.find_failed(limit=5)
print(f'=== Failed ledger entries ({len(entries)} found) ===')
for e in entries:
    print(f'  amount: {e.amount}, attempt_id: {e.related_attempt_id}')
    meta = e.metadata_json or {}
    print(f'  person_id: {meta.get("person_id")}, merchant_id: {meta.get("merchant_id")}')
    print(f'  failure_code: {meta.get("failure_code")}, attempt_id: {meta.get("attempt_id")}')
    print(f'  amount meta: {meta.get("amount")}, payment_method: {meta.get("payment_method")}')
    print()

# Check failed payment intents
intents = intent_repo.find_failed()
print(f'=== Failed payment intents ({len(intents)} found) ===')
for i in intents[:5]:
    print(f'  intent_id: {i.intent_id}, amount: {i.amount}, method: {i.payment_method}')
    print(f'  person_id: {i.person_id}, merchant_id: {i.merchant_id}')
    print()
