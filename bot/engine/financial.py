"""
Financial Engine — pure Python financial calculations.

This is the source of truth for all numbers in Oliv.

Gemini NEVER calculates numbers. All saldo, budget, cashflow,
burn rate, saving rate, and projections come from this module.

Principles:
- No AI calls. No external services. Pure Python arithmetic.
- All methods accept pre-fetched data (no internal Sheets calls).
  The caller (Brain) fetches data and passes it in.
- All methods return typed dataclasses.
- All methods are deterministic — same input = same output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from config import EXPENSE_CATEGORIES, NON_BUDGET_CATEGORIES

logger = logging.getLogger(__name__)

# Constants
BUDGET_DANGER_THRESHOLD = 1.0    # 100% — over budget
BUDGET_WARNING_THRESHOLD = 0.85  # 85% — approaching limit
EMERGENCY_FUND_TARGET_MONTHS = 6  # 6x monthly expenses
MIN_TRANSACTIONS_FOR_ANALYSIS = 3


# ------------------------------------------------------------------ #
# Result dataclasses                                                   #
# ------------------------------------------------------------------ #

@dataclass
class MonthlySummary:
    year_month: str        # "2026-07"
    total_income: float
    total_expense: float
    net: float             # income - expense
    by_category: dict[str, float]
    transaction_count: int

    @property
    def has_data(self) -> bool:
        return self.transaction_count > 0

    @property
    def saving_rate(self) -> float:
        """Saving rate as fraction (0-1). Returns 0 if no income."""
        if self.total_income <= 0:
            return 0.0
        return max(0.0, self.net / self.total_income)


@dataclass
class BudgetStatus:
    category: str
    budget: float
    spent: float
    ratio: float           # spent / budget
    status: str            # "Aman" | "Rawan" | "Over" | "No Budget"

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget - self.spent)

    @property
    def status_emoji(self) -> str:
        return {"Aman": "🟢", "Rawan": "🟡", "Over": "🔴"}.get(self.status, "⚪")


@dataclass
class AccountBalance:
    account: str
    balance: float

    @property
    def is_positive(self) -> bool:
        return self.balance >= 0


@dataclass
class CashflowMonth:
    year_month: str
    income: float
    expense: float
    net: float


@dataclass
class BurnRateResult:
    daily_average: float         # avg daily expense
    monthly_average: float       # avg monthly expense
    months_analyzed: int
    trend: str                   # "increasing" | "decreasing" | "stable"


@dataclass
class ForecastResult:
    year_month: str
    days_elapsed: int
    days_remaining: int
    expense_so_far: float
    projected_expense: float     # extrapolated to end of month
    projected_net: float         # income_so_far - projected_expense
    income_so_far: float
    confidence: str              # "high" | "medium" | "low"


@dataclass
class GoalProgress:
    name: str
    target: float
    collected: float
    deadline: str
    status: str              # "Aktif" | "Selesai"
    progress_ratio: float    # collected / target
    days_remaining: Optional[int]
    monthly_needed: Optional[float]  # how much per month to reach goal


@dataclass
class EmergencyFundStatus:
    current_balance: float
    monthly_expense_avg: float
    months_covered: float
    target_months: int
    progress_ratio: float
    is_healthy: bool


# ------------------------------------------------------------------ #
# Financial Engine                                                     #
# ------------------------------------------------------------------ #

class FinancialEngine:
    """
    Pure Python financial calculation engine.

    All methods take pre-fetched transaction/budget data as input
    and return structured result objects. No I/O is performed here.
    """

    # ---------------------------------------------------------------- #
    # CORE CALCULATIONS                                                  #
    # ---------------------------------------------------------------- #

    @staticmethod
    def get_balance_by_account(transactions: list[dict]) -> list[AccountBalance]:
        """
        Calculate current balance for each account.

        Each transaction has payment (outflow) and deposit (inflow).
        Balance = sum(deposit) - sum(payment) per account.
        """
        balances: dict[str, float] = {}
        for txn in transactions:
            akun = txn.get("akun", "Cash")
            deposit = float(txn.get("deposit") or 0)
            payment = float(txn.get("payment") or 0)
            balances[akun] = balances.get(akun, 0.0) + deposit - payment

        return sorted(
            [AccountBalance(account=k, balance=v) for k, v in balances.items()],
            key=lambda x: -abs(x.balance),
        )

    @staticmethod
    def get_total_balance(transactions: list[dict]) -> float:
        """Sum of all account balances."""
        total = 0.0
        for txn in transactions:
            total += float(txn.get("deposit") or 0) - float(txn.get("payment") or 0)
        return total

    @staticmethod
    def get_monthly_summary(
        transactions: list[dict],
        year_month: Optional[str] = None,
    ) -> MonthlySummary:
        """
        Calculate income, expense, and per-category breakdown for a month.

        Args:
            transactions: all transactions (will be filtered by year_month)
            year_month: "YYYY-MM", defaults to current month
        """
        if year_month is None:
            year_month = datetime.utcnow().strftime("%Y-%m")

        total_income = 0.0
        total_expense = 0.0
        by_category: dict[str, float] = {}
        count = 0

        for txn in transactions:
            tgl = txn.get("tgl", "")
            if not tgl.startswith(year_month):
                continue
            kategori = txn.get("kategori", "")
            if kategori in NON_BUDGET_CATEGORIES:
                continue

            payment = float(txn.get("payment") or 0)
            deposit = float(txn.get("deposit") or 0)

            if payment > 0:
                total_expense += payment
                by_category[kategori] = by_category.get(kategori, 0.0) + payment
                count += 1
            if deposit > 0:
                total_income += deposit
                count += 1

        return MonthlySummary(
            year_month=year_month,
            total_income=total_income,
            total_expense=total_expense,
            net=total_income - total_expense,
            by_category=by_category,
            transaction_count=count,
        )

    @staticmethod
    def get_budget_status(
        transactions: list[dict],
        budget_data: dict[str, float],
        year_month: Optional[str] = None,
    ) -> list[BudgetStatus]:
        """
        Compare actual spending against budget for each expense category.

        Args:
            transactions: all transactions
            budget_data: {category: budget_amount} dict
            year_month: month to check, defaults to current month
        """
        if year_month is None:
            year_month = datetime.utcnow().strftime("%Y-%m")

        # Calculate actual spending per category this month
        actual: dict[str, float] = {}
        for txn in transactions:
            if not txn.get("tgl", "").startswith(year_month):
                continue
            if txn.get("kategori") in NON_BUDGET_CATEGORIES:
                continue
            payment = float(txn.get("payment") or 0)
            if payment > 0:
                kat = txn.get("kategori", "Lain-lain")
                actual[kat] = actual.get(kat, 0.0) + payment

        results = []
        for cat in EXPENSE_CATEGORIES:
            budget = float(budget_data.get(cat, 0))
            spent = actual.get(cat, 0.0)

            if budget <= 0:
                status = "No Budget"
                ratio = 0.0
            else:
                ratio = spent / budget
                if ratio >= BUDGET_DANGER_THRESHOLD:
                    status = "Over"
                elif ratio >= BUDGET_WARNING_THRESHOLD:
                    status = "Rawan"
                else:
                    status = "Aman"

            results.append(BudgetStatus(
                category=cat,
                budget=budget,
                spent=spent,
                ratio=ratio,
                status=status,
            ))

        return results

    @staticmethod
    def get_cashflow_trend(
        transactions: list[dict],
        months: int = 6,
    ) -> list[CashflowMonth]:
        """
        Monthly cashflow over the last N months.

        Returns list sorted oldest → newest.
        """
        today = datetime.utcnow()
        result: list[CashflowMonth] = []

        for i in range(months - 1, -1, -1):
            # Calculate year_month for `i` months ago
            year = today.year
            month = today.month - i
            while month <= 0:
                month += 12
                year -= 1
            ym = f"{year:04d}-{month:02d}"

            income = 0.0
            expense = 0.0
            for txn in transactions:
                if not txn.get("tgl", "").startswith(ym):
                    continue
                if txn.get("kategori") in NON_BUDGET_CATEGORIES:
                    continue
                income += float(txn.get("deposit") or 0)
                expense += float(txn.get("payment") or 0)

            result.append(CashflowMonth(
                year_month=ym,
                income=income,
                expense=expense,
                net=income - expense,
            ))

        return result

    @staticmethod
    def get_burn_rate(
        transactions: list[dict],
        months: int = 3,
    ) -> BurnRateResult:
        """
        Average daily and monthly expense rate over the last N months.

        Burn rate = how fast money is being spent.
        """
        cashflow = FinancialEngine.get_cashflow_trend(transactions, months)
        expenses = [m.expense for m in cashflow[:-1]]  # exclude current (incomplete) month

        if not expenses:
            return BurnRateResult(
                daily_average=0,
                monthly_average=0,
                months_analyzed=0,
                trend="stable",
            )

        monthly_avg = sum(expenses) / len(expenses)
        daily_avg = monthly_avg / 30.44  # average days per month

        # Trend detection
        trend = "stable"
        if len(expenses) >= 2:
            first_half = sum(expenses[: len(expenses) // 2]) / max(len(expenses) // 2, 1)
            second_half = sum(expenses[len(expenses) // 2 :]) / max(len(expenses) - len(expenses) // 2, 1)
            if second_half > first_half * 1.1:
                trend = "increasing"
            elif second_half < first_half * 0.9:
                trend = "decreasing"

        return BurnRateResult(
            daily_average=daily_avg,
            monthly_average=monthly_avg,
            months_analyzed=len(expenses),
            trend=trend,
        )

    @staticmethod
    def get_saving_rate(
        transactions: list[dict],
        months: int = 3,
    ) -> float:
        """
        Average saving rate over the last N months.

        saving_rate = (income - expense) / income
        Returns value between 0.0 and 1.0 (or negative if spending > income).
        """
        cashflow = FinancialEngine.get_cashflow_trend(transactions, months)
        completed = cashflow[:-1]  # exclude current (incomplete) month

        if not completed:
            return 0.0

        total_income = sum(m.income for m in completed)
        total_expense = sum(m.expense for m in completed)

        if total_income <= 0:
            return 0.0

        return (total_income - total_expense) / total_income

    @staticmethod
    def forecast_month_end(
        transactions: list[dict],
        year_month: Optional[str] = None,
    ) -> ForecastResult:
        """
        Project how much will be spent/earned by end of this month.

        Uses actual spending so far this month extrapolated to full month.
        """
        today = datetime.utcnow()
        if year_month is None:
            year_month = today.strftime("%Y-%m")

        year, month = int(year_month[:4]), int(year_month[5:7])

        # Days in this month
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        days_in_month = (next_month - datetime(year, month, 1)).days

        days_elapsed = today.day
        days_remaining = days_in_month - days_elapsed

        # Spending so far this month
        expense_so_far = 0.0
        income_so_far = 0.0
        for txn in transactions:
            if not txn.get("tgl", "").startswith(year_month):
                continue
            if txn.get("kategori") in NON_BUDGET_CATEGORIES:
                continue
            expense_so_far += float(txn.get("payment") or 0)
            income_so_far += float(txn.get("deposit") or 0)

        # Extrapolate
        if days_elapsed > 0:
            daily_rate = expense_so_far / days_elapsed
            projected_expense = daily_rate * days_in_month
        else:
            projected_expense = expense_so_far

        projected_net = income_so_far - projected_expense

        # Confidence based on how much of the month has passed
        progress_ratio = days_elapsed / days_in_month
        if progress_ratio >= 0.7:
            confidence = "high"
        elif progress_ratio >= 0.4:
            confidence = "medium"
        else:
            confidence = "low"

        return ForecastResult(
            year_month=year_month,
            days_elapsed=days_elapsed,
            days_remaining=days_remaining,
            expense_so_far=expense_so_far,
            projected_expense=projected_expense,
            projected_net=projected_net,
            income_so_far=income_so_far,
            confidence=confidence,
        )

    @staticmethod
    def get_goal_progress(goals: list[dict], progress_records: list[dict]) -> list[GoalProgress]:
        """
        Calculate progress toward each savings goal.

        Args:
            goals: rows from Goals sheet
            progress_records: rows from Progress sheet
        """
        today = datetime.utcnow().date()
        results = []

        # Sum progress per goal
        collected_by_goal: dict[str, float] = {}
        for rec in progress_records:
            name = rec.get("Nama Goal", "")
            amt = float(rec.get("Jumlah Masuk") or rec.get("Saldo Goal") or 0)
            collected_by_goal[name] = collected_by_goal.get(name, 0.0) + amt

        for goal in goals:
            name = goal.get("Nama Goal", "")
            try:
                target = float(goal.get("Target Jumlah") or 0)
            except (ValueError, TypeError):
                target = 0.0

            collected = float(goal.get("Terkumpul") or collected_by_goal.get(name, 0))
            deadline_str = goal.get("Deadline", "")
            status = goal.get("Status", "Aktif")

            progress_ratio = (collected / target) if target > 0 else 0.0

            # Days remaining until deadline
            days_remaining = None
            monthly_needed = None
            try:
                deadline_date = datetime.strptime(deadline_str, "%Y-%m-%d").date()
                days_remaining = (deadline_date - today).days
                months_remaining = max(days_remaining / 30.44, 0.5)
                remaining_amount = max(target - collected, 0)
                monthly_needed = remaining_amount / months_remaining if months_remaining > 0 else 0
            except (ValueError, TypeError):
                pass

            results.append(GoalProgress(
                name=name,
                target=target,
                collected=collected,
                deadline=deadline_str,
                status=status,
                progress_ratio=min(progress_ratio, 1.0),
                days_remaining=days_remaining,
                monthly_needed=monthly_needed,
            ))

        return results

    @staticmethod
    def get_emergency_fund_status(
        emergency_fund_balance: float,
        monthly_expense_avg: float,
        target_months: int = EMERGENCY_FUND_TARGET_MONTHS,
    ) -> EmergencyFundStatus:
        """
        Evaluate emergency fund health.

        Target: N months of average expenses in the fund.
        """
        if monthly_expense_avg <= 0:
            months_covered = 0.0
        else:
            months_covered = emergency_fund_balance / monthly_expense_avg

        target_balance = monthly_expense_avg * target_months
        progress_ratio = (emergency_fund_balance / target_balance) if target_balance > 0 else 0.0

        return EmergencyFundStatus(
            current_balance=emergency_fund_balance,
            monthly_expense_avg=monthly_expense_avg,
            months_covered=months_covered,
            target_months=target_months,
            progress_ratio=min(progress_ratio, 1.0),
            is_healthy=months_covered >= target_months,
        )

    @staticmethod
    def get_top_categories(
        transactions: list[dict],
        year_month: Optional[str] = None,
        limit: int = 5,
    ) -> list[tuple[str, float]]:
        """Return top spending categories sorted by amount, largest first."""
        summary = FinancialEngine.get_monthly_summary(transactions, year_month)
        sorted_cats = sorted(summary.by_category.items(), key=lambda x: -x[1])
        return sorted_cats[:limit]

    @staticmethod
    def get_daily_trend(
        transactions: list[dict],
        year_month: Optional[str] = None,
    ) -> dict[str, float]:
        """Return expense per day of week {Monday: avg, ..., Sunday: avg}."""
        if year_month is None:
            year_month = datetime.utcnow().strftime("%Y-%m")

        day_totals: dict[int, float] = {i: 0.0 for i in range(7)}
        day_counts: dict[int, int] = {i: 0 for i in range(7)}

        for txn in transactions:
            if not txn.get("tgl", "").startswith(year_month):
                continue
            payment = float(txn.get("payment") or 0)
            if payment <= 0:
                continue
            try:
                date = datetime.strptime(txn["tgl"], "%Y-%m-%d")
                dow = date.weekday()  # 0=Monday
                day_totals[dow] += payment
                day_counts[dow] += 1
            except (ValueError, KeyError):
                continue

        day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        return {
            day_names[i]: (day_totals[i] / day_counts[i] if day_counts[i] > 0 else 0.0)
            for i in range(7)
        }

    @staticmethod
    def filter_operational(transactions: list[dict]) -> list[dict]:
        """
        Filter out transfer, refund, and non-budget category transactions.

        Only returns transactions that represent real income or expense.
        """
        exclude = set(NON_BUDGET_CATEGORIES) | {
            "[Beginning Balance]",
            "[Carryover Balance]",
            "NON-BUDGET CATEGORIES",
        }
        return [t for t in transactions if t.get("kategori") not in exclude]
