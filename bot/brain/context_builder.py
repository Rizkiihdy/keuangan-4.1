"""
User Context Builder — assembles context package for AI and Brain.

Every AI request must carry context. Context is built here from:
- User identity (name, preferences from Memory)
- Financial state (calculated by FinancialEngine from current data)
- Active goals (from Goals sheet)
- Budget status (from Budget sheet)
- Recent transactions (last 30 days only — not entire history)
- Relevant memory (via MemoryRetriever — query-aware, not full dump)

Principle: send only what is needed, not the entire database.
Context size is bounded to prevent token waste.

V3 change: ContextBuilder now uses MemoryRetriever (not raw MemoryEngine)
           so memory context is filtered per message type.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from memory.engine import MemoryEngine
    from memory.retriever import MemoryRetriever
    from engine.financial import MonthlySummary, BudgetStatus

logger = logging.getLogger(__name__)


@dataclass
class UserContext:
    """
    Assembled context for a single request.

    Passed to Brain and from there to AI Engine when needed.
    Only contains information relevant to the current request.
    """
    # Identity
    chat_id: int
    user_name: str
    user_full_name: str = ""

    # Temporal
    current_date: str = ""        # "2026-07-09"
    current_month: str = ""       # "2026-07"
    day_of_week: str = ""         # "Kamis"

    # Financial snapshot (pre-calculated by FinancialEngine)
    monthly_income: float = 0.0
    monthly_expense: float = 0.0
    monthly_net: float = 0.0
    top_categories: list[tuple[str, float]] = field(default_factory=list)

    # Recent transactions (last 30 days only, not full history)
    recent_transactions: list[dict] = field(default_factory=list)

    # Budget summary
    budget_alerts: list[str] = field(default_factory=list)   # categories over/near limit

    # Memory (query-aware, compact — not full dump)
    memory_summary: str = ""

    # Session state (within current conversation)
    last_transaction_id: Optional[str] = None   # for "yang tadi" references

    def to_ai_prompt_snippet(self, max_recent: int = 10) -> str:
        """
        Format context as a compact snippet for AI prompt injection.

        Only includes what AI needs. Budget numbers come from FinancialEngine,
        not re-calculated by AI.
        """
        lines = []

        if self.memory_summary:
            lines.append(self.memory_summary)

        if self.monthly_income > 0 or self.monthly_expense > 0:
            lines.append(
                f"[Bulan {self.current_month}] "
                f"Pemasukan: Rp{self.monthly_income:,.0f} | "
                f"Pengeluaran: Rp{self.monthly_expense:,.0f} | "
                f"Saldo bulan ini: Rp{self.monthly_net:,.0f}"
            )

        if self.top_categories:
            cats = " | ".join(
                f"{cat}: Rp{amt:,.0f}"
                for cat, amt in self.top_categories[:3]
            )
            lines.append(f"[Top Kategori] {cats}")

        if self.budget_alerts:
            lines.append(f"[Budget Alert] {', '.join(self.budget_alerts)}")

        return "\n".join(lines) if lines else ""


class ContextBuilder:
    """
    Assembles UserContext for each request.

    Called by Brain before processing any request.
    V3: Uses MemoryRetriever for query-aware memory context.

    Balances completeness against efficiency: only fetches
    what is needed for the request type.
    """

    def __init__(
        self,
        memory_engine: "MemoryEngine",
        memory_retriever: Optional["MemoryRetriever"] = None,
    ):
        self._memory = memory_engine
        self._retriever = memory_retriever
        self._WIB_OFFSET = timedelta(hours=7)

    def _now_wib(self) -> datetime:
        return datetime.utcnow() + self._WIB_OFFSET

    def build_minimal(
        self,
        chat_id: int,
        user_name: str,
        user_full_name: str = "",
    ) -> UserContext:
        """
        Minimal context — just identity and temporal info.

        Used for commands that don't need financial data (e.g. /start, /help).
        """
        now = self._now_wib()
        day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

        return UserContext(
            chat_id=chat_id,
            user_name=user_name,
            user_full_name=user_full_name,
            current_date=now.strftime("%Y-%m-%d"),
            current_month=now.strftime("%Y-%m"),
            day_of_week=day_names[now.weekday()],
        )

    def build_with_memory(
        self,
        chat_id: int,
        user_name: str,
        user_full_name: str = "",
        message_type_str: str = "Unknown",
        query: str = "",
    ) -> UserContext:
        """
        Context with memory — for AI-assisted requests.

        V3: Uses MemoryRetriever for query-aware memory context.
        Only fetches categories relevant to this message type.
        """
        ctx = self.build_minimal(chat_id, user_name, user_full_name)
        try:
            if self._retriever is not None:
                # V3: query-aware retrieval
                ctx.memory_summary = self._retriever.retrieve_as_text(
                    user_id=str(chat_id),
                    message_type_str=message_type_str,
                    query=query,
                )
            else:
                # Fallback: use full context summary
                ctx.memory_summary = self._memory.get_context_summary(str(chat_id))
        except Exception as e:
            logger.warning(f"Failed to load memory for {chat_id}: {e}")
        return ctx

    def build_full(
        self,
        chat_id: int,
        user_name: str,
        all_transactions: list[dict],
        budget_data: dict[str, float],
        user_full_name: str = "",
        message_type_str: str = "Financial Analysis",
        query: str = "",
    ) -> UserContext:
        """
        Full context — for analysis and Q&A requests.

        Includes financial snapshot and recent transactions.
        """
        from engine.financial import FinancialEngine

        ctx = self.build_with_memory(
            chat_id, user_name, user_full_name,
            message_type_str=message_type_str,
            query=query,
        )

        # Recent transactions only (last 30 days)
        cutoff = (self._now_wib() - timedelta(days=30)).strftime("%Y-%m-%d")
        recent = [t for t in all_transactions if t.get("tgl", "") >= cutoff]
        ctx.recent_transactions = recent[-50:]  # cap at 50

        # Monthly summary from FinancialEngine (Python, not AI)
        summary = FinancialEngine.get_monthly_summary(all_transactions, ctx.current_month)
        ctx.monthly_income = summary.total_income
        ctx.monthly_expense = summary.total_expense
        ctx.monthly_net = summary.net
        ctx.top_categories = sorted(summary.by_category.items(), key=lambda x: -x[1])[:5]

        # Budget alerts
        budget_status = FinancialEngine.get_budget_status(
            all_transactions, budget_data, ctx.current_month
        )
        ctx.budget_alerts = [
            f"{bs.category} {bs.status_emoji} ({bs.ratio:.0%})"
            for bs in budget_status
            if bs.status in ("Rawan", "Over")
        ]

        return ctx

    def format_transactions_for_ai(
        self,
        transactions: list[dict],
        max_rows: int = 100,
    ) -> str:
        """
        Format transactions as compact text for AI context.

        Only sends last N rows. AI does NOT get the full history.
        """
        relevant = transactions[-max_rows:]
        if not relevant:
            return "Belum ada transaksi."
        rows = []
        for t in relevant:
            amt = t.get("payment", 0) or t.get("deposit", 0)
            direction = "-" if t.get("payment", 0) > 0 else "+"
            rows.append(
                f"{t.get('tgl', '-')} | {t.get('kategori', '-')} | "
                f"{direction}Rp{float(amt):,.0f} | {t.get('memo', '-')}"
            )
        return "\n".join(rows)
