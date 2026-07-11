"""
Brain — Central Decision Orchestrator.

This is the single entry point for all business logic.
Every Telegram handler delegates to Brain. Brain never
delegates back to handlers.

Workflow for any request:
1. Build UserContext (minimal or full depending on request type)
2. Router classifies the message
3. Brain decides the workflow:
   - Pure Python → FinancialEngine (no AI call)
   - NLU needed → AIEngine (structured parse only)
   - Analysis/Q&A → AIEngine with pre-computed context
4. DecisionEngine evaluates confidence
5. If confidence OK → execute and return response
6. If confidence low → return clarification question
7. ReflectionEngine runs in background (asyncio.create_task)

Target: 90-95% of requests resolved without calling Gemini.

AI is NEVER called directly from handlers.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from brain.router import Router, MessageType, RouterResult
from brain.decision import DecisionEngine, QualityScore
from brain.context_builder import ContextBuilder, UserContext
from engine.financial import FinancialEngine
from engine.ai_engine import AIEngine, QuotaExhaustedError, ParsedTransaction
from memory.engine import MemoryEngine
from memory.models import MemoryCategory
from memory.retriever import MemoryRetriever
from utils.formatting import (
    rp, emoji_kategori, komentar_personal, format_transaction_line,
    format_percentage,
)
from config import (
    BOT_NAME, EXPENSE_CATEGORIES, INCOME_CATEGORIES, DAFTAR_AKUN,
    AKUN_KEYWORDS, NON_BUDGET_CATEGORIES, TIPE_PENGELUARAN, TIPE_PEMASUKAN,
)

logger = logging.getLogger(__name__)

WIB_OFFSET = timedelta(hours=7)


@dataclass
class BrainResponse:
    """
    Structured response from Brain to handlers.

    Handlers only send this to Telegram — they don't format content.
    """
    text: str
    parse_mode: str = "Markdown"
    needs_clarification: bool = False
    quality: Optional[QualityScore] = None
    message_type: MessageType = MessageType.UNKNOWN
    used_ai: bool = False
    # For transaction confirmation flow (V2.2 preparation)
    pending_transaction: Optional[dict] = None


class Brain:
    """
    Central decision engine for Oliv.

    Singleton pattern: one Brain instance shared across all handlers.
    Thread-safe for single-user bot workload.
    """

    _instance: Optional["Brain"] = None

    def __init__(
        self,
        sheets_read_fn,       # callable: () → list[dict] (all transactions)
        sheets_write_fn,      # callable: (akun, payee, memo, kategori, payment, deposit) → None
        sheets_transfer_fn,   # callable: (dari, ke, nominal, memo) → None
        sheets_budget_fn,     # callable: () → dict[str, float]
        sheets_goals_fn,      # callable: () → (list[dict], list[dict])
        sheets_manager_fn,    # callable: (key, sheet) → SheetManager
        memory_engine: MemoryEngine,
        reflection_engine=None,  # Optional[ReflectionEngine]
    ):
        self._get_all_transactions = sheets_read_fn
        self._write_transaction = sheets_write_fn
        self._write_transfer = sheets_transfer_fn
        self._get_budget = sheets_budget_fn
        self._get_goals = sheets_goals_fn
        self._get_manager = sheets_manager_fn

        self._router = Router()
        self._decision = DecisionEngine()
        self._memory = memory_engine
        self._retriever = MemoryRetriever(memory_engine)
        self._context_builder = ContextBuilder(memory_engine, self._retriever)
        self._ai = AIEngine()
        self._financial = FinancialEngine()
        self._reflection = reflection_engine  # Optional[ReflectionEngine]

        # Dedicated, bounded thread pool for blocking I/O (Sheets, file access).
        # Using the default executor (None) would share loop.run_in_executor's
        # implicit pool across every async task in the process, which can grow
        # unbounded under concurrent load. A fixed-size pool keeps that bounded.
        self._io_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="brain-io")

        logger.info("Brain initialized.")

    @classmethod
    def get_instance(cls) -> "Brain":
        """Get the singleton Brain instance (must be initialized first)."""
        if cls._instance is None:
            raise RuntimeError("Brain not initialized. Call Brain.initialize() first.")
        return cls._instance

    @classmethod
    def initialize(cls, **kwargs) -> "Brain":
        """Initialize and cache the singleton Brain instance."""
        cls._instance = cls(**kwargs)
        return cls._instance

    def _now_wib(self) -> datetime:
        return datetime.utcnow() + WIB_OFFSET

    async def _io(self, fn, *args, **kwargs):
        """
        Run a synchronous I/O function (gspread, file) in a dedicated thread
        pool so it doesn't block the async event loop.

        Usage:
            txns = await self._io(self._get_all_transactions)
            await self._io(self._write_transaction, akun, payee, ...)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._io_executor, functools.partial(fn, *args, **kwargs))

    def _fire_reflection(
        self,
        user_id: str,
        user_message: str,
        bot_response: str,
        transaction_data: Optional[dict] = None,
        used_ai: bool = False,
    ) -> None:
        """
        Fire-and-forget: run reflection in background after response is sent.
        Never blocks the main response path.
        """
        if self._reflection is None:
            return
        try:
            asyncio.create_task(
                self._reflection.reflect_on_turn(
                    user_id=user_id,
                    user_message=user_message,
                    bot_response=bot_response,
                    transaction_data=transaction_data,
                    used_ai=used_ai,
                )
            )
        except RuntimeError:
            # No running event loop (e.g. test context) — skip
            pass

    # ---------------------------------------------------------------- #
    # PUBLIC INTERFACE — called by handlers                             #
    # ---------------------------------------------------------------- #

    async def process_free_text(
        self,
        text: str,
        chat_id: int,
        user_name: str,
    ) -> BrainResponse:
        """
        Process a free-text message — the most complex workflow.

        Steps:
        1. Router classifies
        2. If small talk → respond directly (no AI)
        3. If transaction/transfer → parse with AI, evaluate, save
        4. If question/analysis → build financial context, ask AI
        5. If unknown → try AI parse, if fails → ask clarification
        """
        # Step 1: Classify
        route = self._router.classify(text)
        logger.info(f"Router: '{text[:40]}' → {route.message_type} (conf={route.confidence:.2f})")

        # Step 2: Small talk — no AI, no sheets
        if route.message_type == MessageType.SMALL_TALK:
            return BrainResponse(
                text=self._small_talk_reply(user_name, text),
                message_type=MessageType.SMALL_TALK,
                used_ai=False,
            )

        # Step 3: Memory update
        if route.message_type == MessageType.MEMORY_UPDATE:
            return await self._handle_memory_update(text, chat_id, user_name)

        # Step 4: Transaction or Transfer
        if route.message_type in (MessageType.TRANSACTION, MessageType.TRANSFER, MessageType.UNKNOWN):
            response = await self._handle_transaction_text(text, chat_id, user_name, route)
            self._fire_reflection(
                user_id=str(chat_id),
                user_message=text,
                bot_response=response.text,
                transaction_data=response.pending_transaction,
                used_ai=response.used_ai,
            )
            return response

        # Step 5: Question / Analysis
        if route.message_type in (MessageType.QUESTION, MessageType.FINANCIAL_ANALYSIS):
            response = await self._handle_question(text, chat_id, user_name)
            self._fire_reflection(
                user_id=str(chat_id),
                user_message=text,
                bot_response=response.text,
                used_ai=response.used_ai,
            )
            return response

        # Step 6: Budget / Goal / Report — Python only
        if route.message_type == MessageType.BUDGET:
            return await self._handle_budget_check(chat_id, user_name)

        if route.message_type == MessageType.GOAL:
            return await self._handle_goal_summary(chat_id, user_name)

        if route.message_type == MessageType.REPORT:
            return await self._handle_report(chat_id, user_name)

        # Fallback: try as transaction
        response = await self._handle_transaction_text(text, chat_id, user_name, route)
        self._fire_reflection(
            user_id=str(chat_id),
            user_message=text,
            bot_response=response.text,
            transaction_data=response.pending_transaction,
            used_ai=response.used_ai,
        )
        return response

    async def process_photo(
        self,
        image_bytes: bytes,
        mime_type: str,
        chat_id: int,
        user_name: str,
    ) -> BrainResponse:
        """Process a receipt photo — always requires AI Vision."""
        try:
            parsed = await self._ai.parse_receipt_photo_async(image_bytes, mime_type)
        except QuotaExhaustedError:
            return BrainResponse(
                text=f"Waduh {user_name}, kuota AI habis nih 😓 Coba lagi nanti ya!",
                used_ai=True,
            )
        except Exception as e:
            logger.error(f"Receipt scan error: {e}")
            return BrainResponse(
                text=(
                    f"Aduh {user_name}, gagal scan struknya 😓\n"
                    "Pastiin foto cukup terang dan angka totalnya keliatan ya!"
                ),
                used_ai=True,
            )

        if parsed is None:
            return BrainResponse(
                text=f"Hmm, kayaknya ini bukan struk belanja deh {user_name} 🤔\n\nCoba kirim foto struk yang lebih jelas ya!",
                used_ai=True,
            )

        # Evaluate quality
        decision = self._decision.evaluate_transaction(parsed.to_dict())
        logger.info(f"Receipt decision: {decision.reason}")

        try:
            await self._io(
                self._write_transaction,
                parsed.akun, parsed.payee, parsed.memo,
                parsed.kategori, int(parsed.jumlah), "",
            )
        except Exception as e:
            logger.error(f"Sheets write error (receipt): {e}")
            return BrainResponse(
                text=f"Duh {user_name}, gagal nyimpen ke Sheet nih 😓 Coba lagi!",
                used_ai=True,
            )

        items_line = f"\n📦 _Item: {parsed.__dict__.get('items', '')}_" if parsed.__dict__.get("items") else ""
        em = emoji_kategori(parsed.kategori)
        komentar = komentar_personal(parsed.memo)

        msg = (
            f"✅ *Struk berhasil di-scan, {user_name}!*\n\n"
            f"{em} *{parsed.memo.title()}*\n"
            f"💰 Total: `{rp(parsed.jumlah)}`\n"
            f"🏪 Payee: {parsed.payee}\n"
            f"🏷️ Kategori: {parsed.kategori}"
            f"{items_line}\n"
            f"💳 Akun: {parsed.akun}"
        )
        if komentar:
            msg += f"\n_{komentar}_"

        response = BrainResponse(
            text=msg,
            message_type=MessageType.TRANSACTION,
            used_ai=True,
            quality=decision.quality,
            pending_transaction=parsed.to_dict(),
        )

        # Reflect: update behaviour from photo transaction
        self._fire_reflection(
            user_id=str(chat_id),
            user_message="[photo receipt]",
            bot_response=msg,
            transaction_data=parsed.to_dict(),
            used_ai=True,
        )
        return response

    async def process_command_ringkasan(self, chat_id: int, user_name: str) -> BrainResponse:
        """Monthly summary — pure Python, no AI."""
        try:
            txns = await self._io(self._get_all_transactions)
            now = self._now_wib()
            ym = now.strftime("%Y-%m")
            summary = FinancialEngine.get_monthly_summary(txns, ym)

            emoji = "🟢" if summary.net >= 0 else "🔴"
            note = "Keuanganmu sehat nih!" if summary.net >= 0 else "Hati-hati, pengeluaran > pemasukan ya!"

            cat_lines = ""
            if summary.by_category:
                cat_lines = "\n\n*Pengeluaran per Kategori:*\n"
                for cat, amt in sorted(summary.by_category.items(), key=lambda x: -x[1])[:10]:
                    em = emoji_kategori(cat)
                    cat_lines += f"  {em} {cat}: `{rp(amt)}`\n"

            return BrainResponse(
                text=(
                    f"Ini rekap keuangan kamu, {user_name}! 💼\n\n"
                    f"📈 Total Pemasukan: `{rp(summary.total_income)}`\n"
                    f"📉 Total Pengeluaran: `{rp(summary.total_expense)}`\n"
                    f"{emoji} Saldo: `{rp(summary.net)}`\n"
                    f"📋 Total Transaksi: `{summary.transaction_count}`\n\n"
                    f"_{note}_"
                    f"{cat_lines}"
                ),
                message_type=MessageType.REPORT,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Ringkasan error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal ngambil data nih. Coba lagi ya! 😓")

    async def process_command_saldo(self, chat_id: int, user_name: str) -> BrainResponse:
        """Account balances — pure Python, no AI."""
        try:
            txns = await self._io(self._get_all_transactions)
            balances = FinancialEngine.get_balance_by_account(txns)
            total = sum(b.balance for b in balances)

            lines = ""
            for b in sorted(balances, key=lambda x: DAFTAR_AKUN.index(x.account) if x.account in DAFTAR_AKUN else 99):
                lines += f"{b.account:<18} {rp(b.balance)}\n"

            return BrainResponse(
                text=(
                    f"💰 *Saldo Saat Ini*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"`{lines}`"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💎 *Total Aset:* {rp(total)}"
                ),
                message_type=MessageType.REPORT,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Saldo error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal ngambil data nih. 😓")

    async def process_command_hariini(self, chat_id: int, user_name: str) -> BrainResponse:
        """Today's transactions — pure Python, no AI."""
        try:
            hari_ini = self._now_wib().strftime("%Y-%m-%d")
            txns = await self._io(self._get_all_transactions)
            data = [
                t for t in FinancialEngine.filter_operational(txns)
                if t["tgl"] == hari_ini and t.get("payment", 0) > 0
            ]
            if not data:
                return BrainResponse(text=f"📭 Belum ada pengeluaran hari ini, {user_name}.")

            total = sum(t["payment"] for t in data)
            lines = ""
            for t in data:
                em = emoji_kategori(t["kategori"])
                label = (t["memo"] or t["kategori"]).title()
                lines += f"{em} {label}\n{rp(t['payment'])}\n\n"

            return BrainResponse(
                text=(
                    f"📅 *Pengeluaran Hari Ini*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{lines}"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💸 *Total:* {rp(total)}"
                ),
                message_type=MessageType.REPORT,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Hariini error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal ngambil data nih. 😓")

    async def process_command_mingguini(self, chat_id: int, user_name: str) -> BrainResponse:
        """Last 7 days by category — pure Python, no AI."""
        try:
            now = self._now_wib()
            today = now.date()
            seven_ago = today - timedelta(days=6)

            txns = await self._io(self._get_all_transactions)
            data = []
            for t in FinancialEngine.filter_operational(txns):
                try:
                    d = datetime.strptime(t["tgl"], "%Y-%m-%d").date()
                    if seven_ago <= d <= today and t.get("payment", 0) > 0:
                        data.append(t)
                except ValueError:
                    continue

            if not data:
                return BrainResponse(text=f"📭 Tidak ada pengeluaran 7 hari terakhir, {user_name}.")

            per_kat: dict[str, float] = {}
            total = 0.0
            for t in data:
                per_kat[t["kategori"]] = per_kat.get(t["kategori"], 0) + t["payment"]
                total += t["payment"]

            lines = ""
            for kat, jml in sorted(per_kat.items(), key=lambda x: -x[1]):
                em = emoji_kategori(kat)
                pct = (jml / total * 100) if total else 0
                lines += f"{em} {kat}: {rp(jml)} ({pct:.0f}%)\n"

            return BrainResponse(
                text=(
                    f"📈 *Ringkasan 7 Hari Terakhir*\n"
                    f"_{seven_ago.strftime('%d %b')} – {today.strftime('%d %b %Y')}_\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{lines}"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💸 *Total:* {rp(total)}\n"
                    f"📝 {len(data)} transaksi"
                ),
                message_type=MessageType.REPORT,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Mingguini error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal ngambil data nih. 😓")

    async def process_command_terbesar(self, chat_id: int, user_name: str) -> BrainResponse:
        """Top 10 biggest expenses this month — pure Python, no AI."""
        try:
            ym = self._now_wib().strftime("%Y-%m")
            month_name = self._now_wib().strftime("%B %Y")
            txns = await self._io(self._get_all_transactions)
            data = [
                t for t in FinancialEngine.filter_operational(txns)
                if t.get("tgl", "").startswith(ym) and t.get("payment", 0) > 0
            ]
            if not data:
                return BrainResponse(text=f"📭 Belum ada transaksi bulan ini, {user_name}.")

            top10 = sorted(data, key=lambda x: -x["payment"])[:10]
            lines = ""
            for i, t in enumerate(top10, 1):
                em = emoji_kategori(t["kategori"])
                label = (t["memo"] or t["kategori"]).title()
                lines += f"{i}. {em} {label} — {rp(t['payment'])}\n"

            return BrainResponse(
                text=(
                    f"🏆 *Top 10 Pengeluaran Terbesar*\n"
                    f"_{month_name}_\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{lines}"
                ),
                message_type=MessageType.REPORT,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Terbesar error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal ngambil data nih. 😓")

    async def process_command_terakhir(self, chat_id: int, user_name: str, n: int = 10) -> BrainResponse:
        """Recent N transactions — pure Python, no AI."""
        try:
            txns = await self._io(self._get_all_transactions)
            recent = txns[-n:][::-1]
            if not recent:
                return BrainResponse(text=f"Belum ada transaksi nih {user_name}. Yuk mulai catat! 😊")

            lines = []
            for t in recent:
                lines.append(format_transaction_line(t))

            return BrainResponse(
                text=f"10 transaksi terakhir kamu, {user_name}! 📋\n\n" + "\n\n".join(lines),
                message_type=MessageType.REPORT,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Terakhir error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal ngambil data nih. Coba lagi ya! 😓")

    async def process_command_budget(self, chat_id: int, user_name: str) -> BrainResponse:
        """Budget status this month — pure Python, no AI."""
        return await self._handle_budget_check(chat_id, user_name)

    async def process_command_analisa(self, chat_id: int, user_name: str) -> BrainResponse:
        """AI-powered spending analysis — uses AI with pre-computed context."""
        try:
            txns = await self._io(self._get_all_transactions)
            ym = self._now_wib().strftime("%Y-%m")
            month_name = self._now_wib().strftime("%B %Y")
            data = [
                t for t in FinancialEngine.filter_operational(txns)
                if t.get("tgl", "").startswith(ym) and t.get("payment", 0) > 0
            ]

            if len(data) < 3:
                return BrainResponse(
                    text=f"📭 Data transaksi masih sedikit, {user_name}. Coba lagi nanti ya!",
                    used_ai=False,
                )

            # Build financial summary with FinancialEngine FIRST (Python, not AI)
            summary = FinancialEngine.get_monthly_summary(txns, ym)
            burn_rate = FinancialEngine.get_burn_rate(txns, months=3)
            top_cats = FinancialEngine.get_top_categories(txns, ym, limit=5)
            cashflow = FinancialEngine.get_cashflow_trend(txns, months=3)

            # Memory context for personalisation
            memory_ctx = self._retriever.retrieve_as_text(
                user_id=str(chat_id),
                message_type_str="Financial Analysis",
                query="analisa pengeluaran",
            )

            # Format as text for AI — AI reasons about pre-computed data
            financial_summary = self._format_analysis_context(
                summary, burn_rate, top_cats, cashflow, month_name
            )
            if memory_ctx:
                financial_summary = f"{memory_ctx}\n\n{financial_summary}"

            # AI only writes the narrative, never recalculates
            narrative = await self._ai.generate_insight_async(
                user_name=user_name,
                financial_summary=financial_summary,
                request_type="analisa pola pengeluaran",
            )

            return BrainResponse(
                text=f"📊 *Analisa Oliv — {month_name}*\n━━━━━━━━━━━━━━━━━━\n{narrative}",
                message_type=MessageType.FINANCIAL_ANALYSIS,
                used_ai=True,
            )
        except QuotaExhaustedError:
            return BrainResponse(text=f"Waduh {user_name}, kuota AI habis nih 😓 Coba lagi besok ya!")
        except Exception as e:
            logger.error(f"Analisa error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal analisa nih. Coba lagi! 😓")

    async def process_command_tanya(self, chat_id: int, user_name: str, question: str) -> BrainResponse:
        """Q&A — uses AI with bounded context (last 3 months only)."""
        try:
            txns = await self._io(self._get_all_transactions)
            ym = self._now_wib().strftime("%Y-%m")

            # Build financial context (Python first)
            summary = FinancialEngine.get_monthly_summary(txns, ym)
            cashflow = FinancialEngine.get_cashflow_trend(txns, months=3)
            top_cats = FinancialEngine.get_top_categories(txns, ym)

            # Only send last 3 months of transactions to AI (not full history)
            cutoff = (self._now_wib() - timedelta(days=90)).strftime("%Y-%m-%d")
            recent_txns = [t for t in txns if t.get("tgl", "") >= cutoff]

            ctx = ContextBuilder(self._memory, self._retriever)
            txn_text = ctx.format_transactions_for_ai(recent_txns, max_rows=100)

            # Query-aware memory — only categories relevant to questions
            memory_ctx = self._retriever.retrieve_as_text(
                user_id=str(chat_id),
                message_type_str="Question",
                query=question,
            )

            financial_summary = (
                f"Data transaksi 3 bulan terakhir (Tanggal|Kategori|Jumlah|Memo):\n{txn_text}\n\n"
                f"Ringkasan bulan {ym}: "
                f"Pemasukan Rp{summary.total_income:,.0f}, "
                f"Pengeluaran Rp{summary.total_expense:,.0f}"
            )

            answer = await self._ai.answer_question_async(
                question=question,
                user_name=user_name,
                financial_summary=financial_summary,
                memory_context=memory_ctx,
            )

            # Evaluate answer quality
            decision = self._decision.evaluate_answer(question, answer, len(recent_txns))
            if not decision.should_proceed:
                return BrainResponse(
                    text=f"Hmm {user_name}, aku kurang punya cukup data untuk jawab pertanyaan itu dengan tepat 🤔\nCoba tanya yang lebih spesifik ya!",
                    used_ai=True,
                )

            return BrainResponse(
                text=f"🤖 *Jawaban {BOT_NAME}:*\n\n{answer}",
                message_type=MessageType.QUESTION,
                used_ai=True,
                quality=decision.quality,
            )
        except QuotaExhaustedError:
            return BrainResponse(text=f"Waduh {user_name}, kuota AI habis nih 😓 Coba lagi besok ya!")
        except Exception as e:
            logger.error(f"Tanya error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, AI-nya lagi gangguan. Coba lagi sebentar! 🙏")

    async def process_command_manual_pengeluaran(
        self,
        chat_id: int,
        user_name: str,
        jumlah: float,
        kategori: str,
        memo: str = "-",
        payee: str = "-",
        akun: str = "Cash",
    ) -> BrainResponse:
        """Manual expense entry — no AI, pure Python validation."""
        try:
            await self._io(self._write_transaction, akun, payee, memo, kategori, int(jumlah), "")
            budget_alert = await self._build_budget_alert_text(chat_id, kategori)
            response = BrainResponse(
                text=(
                    f"Siap, {user_name}! Pengeluaran *{rp(jumlah)}* buat *{memo}* "
                    f"({kategori}) dari *{akun}* udah {BOT_NAME} catat. 📝✅\n"
                    f"🏪 Payee: {payee}"
                    + (f"\n\n{budget_alert}" if budget_alert else "")
                ),
                message_type=MessageType.TRANSACTION,
                used_ai=False,
            )
            # Reflect behaviour from manual transaction
            self._fire_reflection(
                user_id=str(chat_id),
                user_message=f"pengeluaran {rp(jumlah)} {memo}",
                bot_response=response.text,
                transaction_data={"tipe": TIPE_PENGELUARAN, "jumlah": jumlah,
                                   "kategori": kategori, "memo": memo, "akun": akun},
                used_ai=False,
            )
            return response
        except Exception as e:
            logger.error(f"Manual pengeluaran error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal nyimpen nih. Coba lagi ya! 😓")

    async def process_command_manual_pemasukan(
        self,
        chat_id: int,
        user_name: str,
        jumlah: float,
        kategori: str,
        memo: str = "-",
        payee: str = "-",
        akun: str = "Cash",
    ) -> BrainResponse:
        """Manual income entry — no AI, pure Python validation."""
        try:
            await self._io(self._write_transaction, akun, payee, memo, kategori, "", int(jumlah))
            return BrainResponse(
                text=(
                    f"Yeay, ada pemasukan nih {user_name}! 🎉 *{rp(jumlah)}* dari *{memo}* "
                    f"({kategori}) ke *{akun}* udah {BOT_NAME} catat. 📝✅\n"
                    f"🏪 Payee: {payee}"
                ),
                message_type=MessageType.TRANSACTION,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Manual pemasukan error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal nyimpen nih. Coba lagi ya! 😓")

    async def process_command_networth(self, chat_id: int, user_name: str) -> BrainResponse:
        """
        Net worth calculation — pure Python, no AI.

        Combines: account balances + assets + investments - debts.
        This is V4.1 preparation — uses data that already exists.
        """
        try:
            txns = await self._io(self._get_all_transactions)
            balances = FinancialEngine.get_balance_by_account(txns)
            total_liquid = sum(b.balance for b in balances)

            lines = [f"💎 *Net Worth Snapshot*\n"]
            lines.append("*💰 Saldo Akun:*")
            for b in sorted(balances, key=lambda x: -abs(x.balance)):
                if abs(b.balance) > 0:
                    sign = "+" if b.balance >= 0 else ""
                    lines.append(f"  {b.account}: `{sign}{rp(b.balance)}`")

            lines.append(f"\n*Total Likuid: `{rp(total_liquid)}`*")

            return BrainResponse(
                text="\n".join(lines),
                message_type=MessageType.REPORT,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Networth error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal hitung net worth nih. 😓")

    async def process_command_ingatan(
        self,
        chat_id: int,
        user_name: str,
        subcommand: str = "",
        args: list[str] = None,
    ) -> BrainResponse:
        """
        /ingatan — view and manage long-term memories.

        Subcommands:
            (empty)          → show all memories grouped by category
            hapus <id>       → archive a specific memory by ID
            cari <query>     → search memories
            kategori <name>  → show all memories in a category
        """
        args = args or []
        sub = subcommand.lower().strip()

        if sub == "hapus" and args:
            item_id = args[0]
            ok = self._memory.archive(str(chat_id), item_id)
            if ok:
                return BrainResponse(
                    text=f"✅ Memory `{item_id}` sudah dihapus, {user_name}.",
                    used_ai=False,
                )
            return BrainResponse(
                text=f"Hmm, memory `{item_id}` gak ketemu nih {user_name} 🤔",
                used_ai=False,
            )

        if sub == "cari" and args:
            query = " ".join(args)
            results = self._memory.search(str(chat_id), query)
            if not results:
                return BrainResponse(
                    text=f"Gak ada memory yang cocok dengan *{query}*, {user_name} 🔍",
                    used_ai=False,
                )
            lines = [f"🔍 *Hasil cari: \"{query}\"*\n"]
            for item in results[:10]:
                lines.append(
                    f"`{item.id}` [{item.category}] *{item.key}*: {item.value}\n"
                    f"  _(conf={item.confidence:.0%}, v{item.version})_"
                )
            return BrainResponse(text="\n\n".join(lines), used_ai=False)

        # Default: show all memories grouped by category
        grouped = self._memory.list_all(str(chat_id))

        if not grouped:
            return BrainResponse(
                text=(
                    f"Belum ada ingatan tentang kamu nih, {user_name} 📭\n\n"
                    f"Aku akan mulai mengenal kamu lebih baik setiap kali kita ngobrol 🌱\n\n"
                    f"Kamu juga bisa eksplisit bilang:\n"
                    f'_"ingat ya: gajiku tanggal 25"_\n'
                    f'_"ingat ya: aku lagi nabung buat DP rumah"_'
                ),
                used_ai=False,
            )

        # Category labels
        _CAT_LABELS = {
            "identity":           "👤 Identitas",
            "financial_goals":    "🎯 Goal Keuangan",
            "preference":         "❤️ Preferensi",
            "behaviour":          "📊 Perilaku",
            "habit":              "🔁 Kebiasaan",
            "long_term_context":  "🌍 Konteks Jangka Panjang",
        }

        total = self._memory.get_all_count(str(chat_id))
        lines = [f"🧠 *Ingatan Oliv tentang {user_name}*\n_{total} fakta tersimpan_\n"]

        for cat_val, items in sorted(grouped.items()):
            label = _CAT_LABELS.get(cat_val, f"📌 {cat_val.title()}")
            lines.append(f"\n{label}:")
            for item in items[:5]:  # cap at 5 per category in the summary
                lines.append(f"  • *{item.key}*: {item.value}")
            if len(items) > 5:
                lines.append(f"  _...dan {len(items) - 5} fakta lagi_")

        lines.append(
            f"\n\n_Hapus dengan:_ `/ingatan hapus <id>`\n"
            f"_Cari dengan:_ `/ingatan cari <kata>`"
        )

        return BrainResponse(
            text="\n".join(lines),
            used_ai=False,
        )

    async def generate_weekly_report_for_user(
        self, chat_id: int, user_name: str
    ) -> str:
        """Generate weekly report narrative — called by scheduler."""
        try:
            txns = await self._io(self._get_all_transactions)
            now = self._now_wib()
            week_ago = now - timedelta(days=7)
            week_txns = [
                t for t in txns
                if t.get("tgl", "") >= week_ago.strftime("%Y-%m-%d")
            ]

            # Pre-compute summary (Python, not AI)
            ym = now.strftime("%Y-%m")
            summary = FinancialEngine.get_monthly_summary(week_txns, ym)
            top_cats = FinancialEngine.get_top_categories(week_txns, ym, limit=3)

            if not week_txns:
                return (
                    f"Hei {user_name}! Minggu ini belum ada transaksi yang tercatat nih 😅 "
                    "Mulai catat ya supaya aku bisa bantu analisis keuanganmu!"
                )

            cats_text = " | ".join(f"{c}: {rp(a)}" for c, a in top_cats)
            memory_ctx = self._retriever.retrieve_as_text(
                user_id=str(chat_id),
                message_type_str="Report",
                query="laporan mingguan",
            )
            financial_summary = (
                f"Minggu ini: {len(week_txns)} transaksi\n"
                f"Pengeluaran: {rp(summary.total_expense)}\n"
                f"Pemasukan: {rp(summary.total_income)}\n"
                f"Net: {rp(summary.net)}\n"
                f"Top kategori: {cats_text}"
            )
            if memory_ctx:
                financial_summary = f"{memory_ctx}\n\n{financial_summary}"

            return await self._ai.generate_weekly_report_async(user_name, financial_summary)

        except Exception as e:
            logger.error(f"Weekly report error for {chat_id}: {e}")
            return f"Maaf {user_name}, laporan mingguan gagal dibuat nih 😓"

    # ---------------------------------------------------------------- #
    # PRIVATE WORKFLOW HANDLERS                                          #
    # ---------------------------------------------------------------- #

    async def _handle_transaction_text(
        self,
        text: str,
        chat_id: int,
        user_name: str,
        route: RouterResult,
    ) -> BrainResponse:
        """Handle free-text transaction parsing."""
        # Build query-aware memory hint for better AI accuracy
        memory_hint = self._retriever.retrieve_as_text(
            user_id=str(chat_id),
            message_type_str="Transaction",
            query=text,
        )

        try:
            parsed = await self._ai.parse_transaction_async(text, memory_hint)
        except QuotaExhaustedError:
            return BrainResponse(
                text=f"Waduh {user_name}, kuota AI habis nih 😓 Coba lagi besok ya!",
                used_ai=True,
            )
        except Exception as e:
            logger.error(f"AI parse error: {e}")
            return BrainResponse(
                text=f"Aduh {user_name}, AI-nya gangguan nih. Coba lagi ya! 🙏",
                used_ai=True,
            )

        if parsed is None:
            return BrainResponse(
                text=(
                    f"Hmm, aku kurang nangkep maksudnya {user_name} 🤔\n\n"
                    f"Coba tulis lebih jelas:\n"
                    f"• _\"beli makan siang 25.000\"_\n"
                    f"• _\"gajian 4 juta\"_\n"
                    f"• _\"bayar grab 18rb\"_\n\n"
                    f"Kalau mau tanya, pakai /tanya ya!"
                ),
                used_ai=True,
            )

        # Evaluate decision quality
        decision = self._decision.evaluate_transaction(parsed.to_dict())
        logger.info(f"Transaction decision: {decision.reason} — {decision.quality.summary()}")

        if not decision.should_proceed:
            # Ask for clarification instead of saving garbage
            q = decision.clarification_question or "Bisa dijelaskan lebih detail? 🤔"
            return BrainResponse(
                text=q,
                needs_clarification=True,
                quality=decision.quality,
                used_ai=True,
                message_type=MessageType.TRANSACTION,
                pending_transaction=parsed.to_dict(),
            )

        # Handle transfer
        if parsed.is_transfer():
            return await self._save_transfer(parsed, text, user_name)

        # Save transaction
        try:
            if parsed.tipe == TIPE_PENGELUARAN:
                await self._io(
                    self._write_transaction,
                    parsed.akun, parsed.payee, parsed.memo,
                    parsed.kategori, int(parsed.jumlah), "",
                )
                em = emoji_kategori(parsed.kategori)
                komentar = komentar_personal(parsed.memo)
                msg = (
                    f"✅ *Tercatat, {user_name}!*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{em} *{parsed.memo.title()}* — {rp(parsed.jumlah)}\n"
                    f"📂 {parsed.kategori}  |  🏪 {parsed.payee}  |  💳 {parsed.akun}"
                )
                if komentar:
                    msg += f"\n_{komentar}_"

                # Async budget alert (Python calculation)
                budget_alert = await self._build_budget_alert_text(chat_id, parsed.kategori)

                return BrainResponse(
                    text=msg + (f"\n\n{budget_alert}" if budget_alert else ""),
                    message_type=MessageType.TRANSACTION,
                    used_ai=True,
                    quality=decision.quality,
                    pending_transaction=parsed.to_dict(),
                )
            else:
                await self._io(
                    self._write_transaction,
                    parsed.akun, parsed.payee, parsed.memo,
                    parsed.kategori, "", int(parsed.jumlah),
                )
                return BrainResponse(
                    text=(
                        f"💼 *Pemasukan Tercatat!*\n"
                        f"💰 {rp(parsed.jumlah)} ke *{parsed.akun}*\n"
                        f"📦 Kategori: {parsed.kategori}\n"
                        f"📝 Memo: {parsed.memo}\n✅ Cleared"
                    ),
                    message_type=MessageType.TRANSACTION,
                    used_ai=True,
                    quality=decision.quality,
                )

        except Exception as e:
            logger.error(f"Sheets write error: {e}")
            return BrainResponse(text=f"Duh {user_name}, gagal nyimpen ke Sheet nih 😓 Coba lagi!")

    async def _save_transfer(
        self, parsed: ParsedTransaction, original_text: str, user_name: str
    ) -> BrainResponse:
        """Save a transfer transaction."""
        dari_akun, ke_akun = self._detect_transfer_accounts(original_text)
        if dari_akun == ke_akun:
            ke_akun = "GoPay"
        try:
            await self._io(self._write_transfer, dari_akun, ke_akun, int(parsed.jumlah), parsed.payee)
            return BrainResponse(
                text=(
                    f"🔁 *Transfer Tercatat!*\n"
                    f"*{dari_akun}* → *{ke_akun}*\n"
                    f"💰 {rp(parsed.jumlah)}\n✅ Cleared"
                ),
                message_type=MessageType.TRANSFER,
                used_ai=True,
            )
        except Exception as e:
            logger.error(f"Transfer write error: {e}")
            return BrainResponse(text=f"Duh {user_name}, gagal nyimpen transfer nih. Coba lagi! 😓")

    async def _handle_question(self, text: str, chat_id: int, user_name: str) -> BrainResponse:
        """Handle a financial question."""
        return await self.process_command_tanya(chat_id, user_name, text)

    async def _handle_budget_check(self, chat_id: int, user_name: str) -> BrainResponse:
        """Budget status — pure Python."""
        try:
            txns = await self._io(self._get_all_transactions)
            budget_data = await self._io(self._get_budget)
            ym = self._now_wib().strftime("%Y-%m")
            statuses = FinancialEngine.get_budget_status(txns, budget_data, ym)

            lines = ["💰 *Budget Status Bulan Ini*\n_(Anggaran vs Aktual)_\n"]
            has_budget = False
            any_warning = False

            for bs in statuses:
                if bs.budget <= 0:
                    continue
                has_budget = True
                if bs.status in ("Over", "Rawan"):
                    any_warning = True
                lines.append(
                    f"*{bs.category}* — {bs.status_emoji} {bs.status}\n"
                    f"  `{rp(bs.spent)}` / `{rp(bs.budget)}` ({bs.ratio*100:.0f}%)"
                )

            if not has_budget:
                return BrainResponse(
                    text=(
                        f"Belum ada anggaran yang diatur nih, {user_name} 📭\n\n"
                        "Buka tab *Budget* di Google Sheet, isi kolom bulan ini "
                        "per kategori dulu ya! 🎯"
                    )
                )

            if not any_warning:
                lines.append("\n✨ _Semua kategori masih aman! Great job!_ 💪")

            return BrainResponse(
                text="\n\n".join(lines),
                message_type=MessageType.BUDGET,
                used_ai=False,
            )
        except Exception as e:
            logger.error(f"Budget check error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal cek budget nih. Coba lagi ya! 😓")

    async def _handle_goal_summary(self, chat_id: int, user_name: str) -> BrainResponse:
        """Goal progress summary — pure Python."""
        try:
            goals, progress = await self._io(self._get_goals)
            if not goals:
                return BrainResponse(
                    text=(
                        f"Belum ada goal yang dibuat nih, {user_name} 🎯\n\n"
                        "Gunakan /goal untuk bikin target tabungan baru ya!"
                    )
                )
            gp_list = FinancialEngine.get_goal_progress(goals, progress)
            lines = ["🎯 *Goal & Progress Kamu*\n"]
            for gp in gp_list:
                if gp.status == "Selesai":
                    lines.append(f"✅ ~~{gp.name}~~ — Selesai!")
                    continue
                bar = _progress_bar(gp.progress_ratio)
                lines.append(
                    f"🎯 *{gp.name}*\n"
                    f"  {bar} {gp.progress_ratio*100:.0f}%\n"
                    f"  Terkumpul: `{rp(gp.collected)}` / Target: `{rp(gp.target)}`\n"
                    f"  Deadline: {gp.deadline}"
                    + (f"\n  Perlu nabung: `{rp(gp.monthly_needed)}/bulan`" if gp.monthly_needed else "")
                )
            return BrainResponse(text="\n\n".join(lines), message_type=MessageType.GOAL, used_ai=False)
        except Exception as e:
            logger.error(f"Goal summary error: {e}")
            return BrainResponse(text=f"Aduh {user_name}, gagal ngambil data goal nih. 😓")

    async def _handle_report(self, chat_id: int, user_name: str) -> BrainResponse:
        """General report request — routes to monthly summary."""
        return await self.process_command_ringkasan(chat_id, user_name)

    async def _handle_memory_update(self, text: str, chat_id: int, user_name: str) -> BrainResponse:
        """
        Parse and store an explicit memory update instruction.

        Supported formats:
          "ingat ya: gajiku 5 juta"
          "ingat: namaku Zee"
          "catat: aku kerja di startup"
        """
        text_lower = text.lower()
        _TRIGGERS = ["ingat ya:", "ingat:", "catat:", "note:", "remember:", "simpan info:"]

        for trigger in _TRIGGERS:
            if trigger in text_lower:
                content = text[text_lower.index(trigger) + len(trigger):].strip()
                if not content:
                    break

                # Smart category detection from content
                category, key = _classify_explicit_memory(content)

                try:
                    item, was_new = self._memory.merge(
                        user_id=str(chat_id),
                        category=category,
                        key=key,
                        value=content,
                        source="user_explicit",
                        confidence=0.95,
                        importance=0.8,
                    )
                    action = "dicatat baru" if was_new else "diperbarui"
                    return BrainResponse(
                        text=(
                            f"✅ Oke {user_name}, sudah aku {action}! 📝\n\n"
                            f"_{content}_\n\n"
                            f"Aku akan pakai info ini setiap kita ngobrol 🧠"
                        ),
                        used_ai=False,
                        message_type=MessageType.MEMORY_UPDATE,
                    )
                except ValueError as e:
                    return BrainResponse(text=f"Maaf {user_name}, {e} 🔒")
                except Exception as e:
                    logger.error(f"Memory create error: {e}")

        return BrainResponse(
            text=(
                f"Aku dengar kamu {user_name}, tapi belum paham mau dicatat apa nih 🤔\n\n"
                f"Coba format ini:\n"
                f'_"ingat ya: gajiku tanggal 25"_\n'
                f'_"ingat ya: aku lagi nabung buat DP rumah"_\n'
                f'_"catat: aku sering bayar pakai GoPay"_'
            ),
            used_ai=False,
        )

    async def _build_budget_alert_text(self, chat_id: int, kategori: str) -> str:
        """
        Build budget alert text for a category — pure Python.

        Returns empty string if no alert needed.
        """
        if kategori not in EXPENSE_CATEGORIES:
            return ""
        try:
            txns = await self._io(self._get_all_transactions)
            budget_data = await self._io(self._get_budget)
            ym = self._now_wib().strftime("%Y-%m")
            statuses = FinancialEngine.get_budget_status(txns, budget_data, ym)
            for bs in statuses:
                if bs.category == kategori and bs.budget > 0:
                    if bs.status == "Over":
                        return (
                            f"🔴 *Budget Alert — {kategori} OVER!*\n"
                            f"Terpakai: `{rp(bs.spent)}` / Anggaran: `{rp(bs.budget)}` ({bs.ratio*100:.0f}%)\n"
                            f"Kurangi pengeluaran di kategori ini ya 💪"
                        )
                    elif bs.status == "Rawan":
                        return (
                            f"🟡 *Budget Warning — {kategori} Rawan!*\n"
                            f"Terpakai: `{rp(bs.spent)}` / Anggaran: `{rp(bs.budget)}` ({bs.ratio*100:.0f}%)\n"
                            f"Hati-hati, jangan sampai over budget 🙏"
                        )
        except Exception as e:
            logger.warning(f"Budget alert calc error: {e}")
        return ""

    @staticmethod
    def _small_talk_reply(user_name: str, text: str) -> str:
        """Quick, no-AI reply for small talk."""
        greetings = {
            "makasih": f"Sama-sama {user_name}! 😊",
            "thanks": f"No problem {user_name}! 😊",
            "mantap": f"Makasih {user_name}! 💪",
            "keren": f"Makasih ya {user_name}! 🌟",
            "sip": "Siap! 👍",
            "oke": "Oke! 👍",
            "ok": "Oke! 👍",
        }
        tl = text.lower().strip()
        for kw, reply in greetings.items():
            if kw in tl:
                return reply
        return f"Hei {user_name}! 😊 Ada yang bisa aku bantu?"

    @staticmethod
    def _detect_transfer_accounts(text: str) -> tuple[str, str]:
        """Detect source and destination accounts from transfer text."""
        import re as _re
        text_lower = text.lower()

        match = _re.search(r'dari\s+(\w+(?:\s+\w+)?)\s+ke\s+(\w+(?:\s+\w+)?)', text_lower)
        if match:
            dari = _map_akun(match.group(1).strip())
            ke = _map_akun(match.group(2).strip())
            if dari and ke:
                return dari, ke

        match = _re.search(r'ke\s+(\w+(?:\s+\w+)?)\s+dari\s+(\w+(?:\s+\w+)?)', text_lower)
        if match:
            ke = _map_akun(match.group(1).strip())
            dari = _map_akun(match.group(2).strip())
            if dari and ke:
                return dari, ke

        found = [a for a in DAFTAR_AKUN if a.lower() in text_lower]
        if len(found) >= 2:
            return found[0], found[1]
        elif len(found) == 1:
            return "Cash", found[0]

        return "Cash", "GoPay"

    @staticmethod
    def _format_analysis_context(
        summary, burn_rate, top_cats, cashflow, month_name: str
    ) -> str:
        """Format pre-computed financial data for AI analysis prompt."""
        cats_text = "\n".join(
            f"  - {cat}: Rp{amt:,.0f}" for cat, amt in top_cats
        )
        trend_text = "\n".join(
            f"  {m.year_month}: income={rp(m.income)}, expense={rp(m.expense)}, net={rp(m.net)}"
            for m in cashflow
        )
        return (
            f"Bulan: {month_name}\n"
            f"Total Pemasukan: Rp{summary.total_income:,.0f}\n"
            f"Total Pengeluaran: Rp{summary.total_expense:,.0f}\n"
            f"Saldo Bersih: Rp{summary.net:,.0f}\n"
            f"Saving Rate: {summary.saving_rate*100:.1f}%\n"
            f"Total Transaksi: {summary.transaction_count}\n\n"
            f"Top Kategori Pengeluaran:\n{cats_text}\n\n"
            f"Tren 3 Bulan:\n{trend_text}\n\n"
            f"Burn Rate: Rp{burn_rate.monthly_average:,.0f}/bulan ({burn_rate.trend})"
        )


# ------------------------------------------------------------------ #
# MODULE-LEVEL HELPERS                                                 #
# ------------------------------------------------------------------ #

def _map_akun(raw: str) -> Optional[str]:
    """Map free-text account name to valid account."""
    raw_lower = raw.lower()
    for akun in DAFTAR_AKUN:
        if akun.lower() == raw_lower:
            return akun
    for akun, keywords in AKUN_KEYWORDS.items():
        if any(kw in raw_lower for kw in keywords):
            return akun
    return None


def _progress_bar(ratio: float, width: int = 10) -> str:
    """Generate a text progress bar."""
    filled = int(ratio * width)
    return "▓" * filled + "░" * (width - filled)


def _classify_explicit_memory(content: str) -> tuple[MemoryCategory, str]:
    """
    Heuristically determine category and key from explicit user instruction.

    Used in _handle_memory_update for smarter categorisation.
    """
    c = content.lower()

    # Identity signals
    if any(k in c for k in ["namaku", "nama aku", "nama saya", "aku bernama"]):
        return MemoryCategory.IDENTITY, "nama"
    if any(k in c for k in ["gajiku", "gaji aku", "gajian tanggal", "tanggal gaji"]):
        return MemoryCategory.IDENTITY, "hari_gajian"
    if any(k in c for k in ["kerja di", "bekerja di", "pekerjaan", "profesi", "kerjaan"]):
        return MemoryCategory.IDENTITY, "pekerjaan"
    if any(k in c for k in ["tinggal di", "domisili", "kota", "alamat"]):
        return MemoryCategory.IDENTITY, "kota"
    if any(k in c for k in ["umur", "tahun", "usia", "lahir"]):
        return MemoryCategory.IDENTITY, "umur"

    # Financial goals
    if any(k in c for k in ["nabung buat", "target beli", "mau beli", "goal", "impian", "rencana beli"]):
        return MemoryCategory.FINANCIAL_GOALS, "goal_aktif"
    if any(k in c for k in ["dp rumah", "cicilan", "kpr", "beli rumah"]):
        return MemoryCategory.FINANCIAL_GOALS, "goal_rumah"
    if any(k in c for k in ["dana darurat", "emergency fund"]):
        return MemoryCategory.FINANCIAL_GOALS, "goal_dana_darurat"
    if any(k in c for k in ["pensiun", "retire"]):
        return MemoryCategory.FINANCIAL_GOALS, "goal_pensiun"

    # Long-term context
    if any(k in c for k in ["lagi", "sedang", "masih", "proses"]):
        return MemoryCategory.LONG_TERM_CONTEXT, "situasi_saat_ini"

    # Preference
    if any(k in c for k in ["sering pakai", "biasanya pakai", "favorit", "prefer"]):
        return MemoryCategory.PREFERENCE, "preferensi_umum"
    if any(k in c for k in ["bayar pakai", "transfer via", "metode bayar"]):
        return MemoryCategory.PREFERENCE, "metode_bayar_favorit"

    # Habit
    if any(k in c for k in ["rutin", "setiap bulan", "tiap bulan", "selalu", "kebiasaan"]):
        return MemoryCategory.HABIT, "kebiasaan_rutin"

    # Default: long-term context
    return MemoryCategory.LONG_TERM_CONTEXT, "catatan"


from typing import Optional
