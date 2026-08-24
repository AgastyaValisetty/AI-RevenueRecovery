from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, func, select, update
from .database import Database
from .domain import BankPolicy, BankState, BankStatus, BankAccount
from .schema import BankRow, BankMetricRow, BankAccountRow


class BankRepository:
    def __init__(self, db: Database):
        self._db = db

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

    def update_state(self, bank_id: str, new_state: BankState) -> None:
        with self._db.session() as session:
            session.execute(
                update(BankRow)
                .where(BankRow.bank_id == bank_id)
                .values(current_state=new_state.value)
            )

    def record_transaction_result(self, bank_id: str, success: bool, ts: datetime) -> None:
        with self._db.session() as session:
            session.add(
                BankMetricRow(
                    bank_id=bank_id,
                    timestamp=ts,
                    success=int(success),
                )
            )

    def get_account(self, account_id: str) -> BankAccount | None:
        with self._db.session() as session:
            row = session.get(BankAccountRow, account_id)
            if row is None:
                return None
            return self._to_domain(row)

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
            return self._to_domain(row)

    def add_account(self, account: BankAccount) -> None:
        with self._db.session() as session:
            session.add(self._to_row(account))

    def update_balance(self, account_id: str, new_balance: float) -> None:
        with self._db.session() as session:
            session.execute(
                update(BankAccountRow)
                .where(BankAccountRow.account_id == account_id)
                .values(balance=new_balance)
            )

    def get_balance(self, account_id: str) -> float:
        with self._db.session() as session:
            row = session.get(BankAccountRow, account_id)
            if row is None:
                return 0.0
            return float(row.balance)

    def get_accounts_by_person(self, person_id: str) -> list[BankAccount]:
        with self._db.session() as session:
            rows = session.scalars(
                select(BankAccountRow).where(BankAccountRow.person_id == person_id)
            ).all()
            return [self._to_domain(r) for r in rows]

    def status(self, bank_id: str) -> BankStatus:
        """Compute a BankStatus snapshot from recent transaction metrics."""
        with self._db.session() as session:
            bank_row = session.get(BankRow, bank_id)
            if bank_row is None:
                return BankStatus(
                    bank_id=bank_id, name="unknown", current_state=BankState.NORMAL,
                    success_rate=0.0, failure_rate=0.0,
                    transactions_last_minute=0, failures_last_minute=0, balance=0.0,
                )

            one_minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
            # bank_id may be a UUID object from the shared banks table; cast to
            # str for the bank_metrics table whose bank_id column is String(64).
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

            return BankStatus(
                bank_id=bank_row.bank_id,
                name=bank_row.name,
                current_state=BankState(bank_row.current_state),
                success_rate=round(success_rate, 2),
                failure_rate=round(failure_rate, 2),
                transactions_last_minute=total,
                failures_last_minute=failures,
                balance=0.0,
            )

    @staticmethod
    def _to_domain(row: BankRow) -> BankPolicy:
        import json
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
            created_at=row.created_at,
        )

    @staticmethod
    def _to_row(bank: BankPolicy) -> BankRow:
        import json
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
            created_at=bank.created_at,
        )

    @staticmethod
    def _to_domain_account(row: BankAccountRow) -> BankAccount:
        return BankAccount(
            account_id=row.account_id,
            person_id=row.person_id,
            bank_id=row.bank_id,
            balance=float(row.balance),
            created_at=row.created_at,
        )

    @staticmethod
    def _to_row_account(account: BankAccount) -> BankAccountRow:
        return BankAccountRow(
            account_id=account.account_id,
            person_id=account.person_id,
            bank_id=account.bank_id,
            balance=account.balance,
            created_at=account.created_at,
        )