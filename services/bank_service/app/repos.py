"""Bank Service repository layer.

Provides read/write access to shared tables (banks, bank_accounts,
ledger_entries) and the service-owned bank_metrics table.
"""
import json
from datetime import datetime, timedelta, timezone

from decimal import Decimal

from sqlalchemy import Integer, func, select, update

from .database import Database
from .domain import BankPolicy, BankState, BankStatus, BankAccount
from .schema import BankRow, BankMetricRow, BankAccountRow, LedgerEntryRow


class BankRepository:
    def __init__(self, db: Database):
        self._db = db

    # ------------------------------------------------------------------
    # Bank policy
    # ------------------------------------------------------------------

    def find_by_name(self, name: str) -> BankPolicy | None:
        with self._db.session() as session:
            row = session.scalar(select(BankRow).where(BankRow.name == name))
            if row is None:
                return None
            return self._to_domain(row)

    def find_by_id(self, bank_id: str) -> BankPolicy | None:
        with self._db.session() as session:
            row = session.get(BankRow, bank_id)
            if row is None:
                return None
            return self._to_domain(row)

    def add(self, bank: BankPolicy) -> None:
        with self._db.session() as session:
            session.add(self._to_row(bank))

    def update_settlement_account(self, bank_id: str, settlement_account_id: str | None) -> None:
        """Link (or unlink) a settlement account to a bank."""
        with self._db.session() as session:
            session.execute(
                update(BankRow)
                .where(BankRow.bank_id == bank_id)
                .values(settlement_account_id=settlement_account_id)
            )

    def get_or_create_settlement_account(self, bank_id: str) -> str:
        """Return the settlement account ID for *bank_id*, creating one if needed.

        A settlement account is a bank-owned account (``person_id IS NULL``)
        that receives funds when payments are settled.  The account is
        persisted in the shared ``bank_accounts`` table and its ID is stored
        on the ``banks`` row for fast lookup.
        """
        with self._db.session() as session:
            bank_row = session.get(BankRow, bank_id)
            if bank_row is not None and bank_row.settlement_account_id is not None:
                return bank_row.settlement_account_id

            # Create a new settlement account
            from uuid import uuid4
            settlement_account_id = f"settlement-{uuid4().hex[:12]}"
            session.add(
                BankAccountRow(
                    account_id=settlement_account_id,
                    person_id=None,
                    bank_id=bank_id,
                    created_at=datetime.now(timezone.utc),
                )
            )

            if bank_row is not None:
                bank_row.settlement_account_id = settlement_account_id
            else:
                # Bank doesn't exist yet — create a link so it can be set later
                session.add(BankRow(
                    bank_id=bank_id,
                    name="RupeeBank",
                    authorization_success_rate=99.1,
                    timeout_rate=0.3,
                    issuer_decline_rate=0.4,
                    network_error_rate=0.2,
                    current_state="NORMAL",
                    state_multipliers_json=json.dumps(
                        {"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0}
                    ),
                    settlement_account_id=settlement_account_id,
                    created_at=datetime.now(timezone.utc),
                ))

            session.flush()
            return settlement_account_id

    def update_state(self, bank_id: str, new_state: BankState) -> None:
        with self._db.session() as session:
            session.execute(
                update(BankRow)
                .where(BankRow.bank_id == bank_id)
                .values(current_state=new_state.value)
            )

    # ------------------------------------------------------------------
    # Account balance (calculated from ledger_entries, not stored)
    # ------------------------------------------------------------------

    def get_balance(self, account_id: str) -> Decimal:
        """Calculate balance from ledger entries.

        balance = sum(credits where to_account_id == account_id)
                - sum(debits where from_account_id == account_id)
        """
        with self._db.session() as session:
            credits = session.scalar(
                select(func.coalesce(func.sum(LedgerEntryRow.amount), 0)).where(
                    LedgerEntryRow.to_account_id == account_id
                )
            )
            debits = session.scalar(
                select(func.coalesce(func.sum(LedgerEntryRow.amount), 0)).where(
                    LedgerEntryRow.from_account_id == account_id
                )
            )
            return Decimal(credits) - Decimal(debits)

    def get_account(self, account_id: str) -> BankAccount | None:
        with self._db.session() as session:
            row = session.get(BankAccountRow, account_id)
            if row is None:
                return None
            balance = self.get_balance(account_id)
            return BankAccount(
                account_id=row.account_id,
                person_id=row.person_id,
                bank_id=row.bank_id,
                balance=float(balance),
                created_at=row.created_at,
            )

    def find_account_by_person_and_bank(self, person_id: str, bank_id: str) -> BankAccount | None:
        with self._db.session() as session:
            row = session.scalar(
                select(BankAccountRow).where(
                    BankAccountRow.person_id == person_id,
                    BankAccountRow.bank_id == bank_id,
                )
            )
            if row is None:
                return None
            balance = self.get_balance(row.account_id)
            return BankAccount(
                account_id=row.account_id,
                person_id=row.person_id,
                bank_id=row.bank_id,
                balance=float(balance),
                created_at=row.created_at,
            )

    def add_account(self, account: BankAccount) -> None:
        with self._db.session() as session:
            session.add(self._to_row_account(account))

    def get_accounts_by_person(self, person_id: str) -> list[BankAccount]:
        with self._db.session() as session:
            rows = session.scalars(
                select(BankAccountRow).where(BankAccountRow.person_id == person_id)
            ).all()
            return [self._to_domain_account(r) for r in rows]

    # ------------------------------------------------------------------
    # Transaction metrics and state transitions
    # ------------------------------------------------------------------

    def record_transaction_result(
        self,
        bank_id: str,
        success: bool,
        ts: datetime,
        response_time_ms: int = 0,
        outcome: str = "UNKNOWN",
    ) -> None:
        """Record a transaction result for metrics and state transitions."""
        with self._db.session() as session:
            session.add(
                BankMetricRow(
                    bank_id=str(bank_id),
                    timestamp=ts,
                    success=int(success),
                    response_time_ms=response_time_ms,
                    outcome=outcome,
                )
            )

    def status(self, bank_id: str) -> BankStatus:
        """Compute a BankStatus snapshot from recent transaction metrics.

        The ``balance`` field reflects the funds held in the bank's
        settlement account (total settled payments).
        """
        with self._db.session() as session:
            bank_row = session.get(BankRow, bank_id)
            if bank_row is None:
                return BankStatus(
                    bank_id=bank_id, name="unknown",
                    current_state=BankState.NORMAL,
                    success_rate=0.0, failure_rate=0.0,
                    transactions_last_minute=0, failures_last_minute=0, balance=0.0,
                )

            one_minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
            bank_id_str = str(bank_id)
            metrics_result = session.execute(
                select(
                    func.count(BankMetricRow.metric_id).label("total"),
                    func.sum(func.cast(BankMetricRow.success, Integer)).label("successes"),
                ).where(
                    BankMetricRow.bank_id == bank_id_str,
                    BankMetricRow.timestamp >= one_minute_ago,
                )
            ).first()

            total = metrics_result.total or 0
            successes = metrics_result.successes or 0
            failures = total - successes
            success_rate = (successes / total * 100.0) if total > 0 else 0.0
            failure_rate = (failures / total * 100.0) if total > 0 else 0.0

            # Balance from the bank's settlement account (if it exists)
            balance = 0.0
            if bank_row.settlement_account_id is not None:
                balance = float(self.get_balance(bank_row.settlement_account_id))

            return BankStatus(
                bank_id=bank_row.bank_id,
                name=bank_row.name,
                current_state=BankState(bank_row.current_state),
                success_rate=round(success_rate, 2),
                failure_rate=round(failure_rate, 2),
                transactions_last_minute=total,
                failures_last_minute=failures,
                balance=balance,
            )

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_domain(row: BankRow) -> BankPolicy:
        smj = row.state_multipliers_json
        state_multipliers = smj if isinstance(smj, dict) else json.loads(smj)
        return BankPolicy(
            bank_id=row.bank_id,
            name=row.name,
            authorization_success_rate=float(row.authorization_success_rate),
            timeout_rate=float(row.timeout_rate),
            issuer_decline_rate=float(row.issuer_decline_rate),
            network_error_rate=float(row.network_error_rate),
            current_state=BankState(row.current_state),
            state_multipliers=state_multipliers,
            settlement_account_id=row.settlement_account_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_row(bank: BankPolicy) -> BankRow:
        sm_json = bank.state_multipliers
        if not isinstance(sm_json, str):
            sm_json = json.dumps(sm_json)
        return BankRow(
            bank_id=bank.bank_id,
            name=bank.name,
            authorization_success_rate=bank.authorization_success_rate,
            timeout_rate=bank.timeout_rate,
            issuer_decline_rate=bank.issuer_decline_rate,
            network_error_rate=bank.network_error_rate,
            current_state=bank.current_state.value,
            state_multipliers_json=sm_json,
            settlement_account_id=bank.settlement_account_id,
            created_at=bank.created_at,
        )

    @staticmethod
    def _to_domain_account(row: BankAccountRow) -> BankAccount:
        return BankAccount(
            account_id=row.account_id,
            bank_id=row.bank_id,
            person_id=row.person_id,
            balance=0.0,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_row_account(account: BankAccount) -> BankAccountRow:
        return BankAccountRow(
            account_id=account.account_id,
            person_id=account.person_id,
            bank_id=account.bank_id,
            created_at=account.created_at,
        )
