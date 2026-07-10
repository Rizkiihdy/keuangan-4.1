"""
Message Router — classifies incoming Telegram messages.

Every message MUST be classified before Brain decides the workflow.

Classification goal:
- Avoid calling AI for messages that Python can handle
- Route to the right workflow immediately
- Target: 90-95% of requests classified without AI

Classification types:
    TRANSACTION       — "beli kopi 15rb", "gajian 5 juta"
    TRANSFER          — "transfer dari BCA ke GoPay 500rb"
    QUESTION          — "berapa total makan bulan ini?"
    FINANCIAL_ANALYSIS — "analisa pengeluaran aku", "gimana keuanganku?"
    REPORT            — "ringkasan", "laporan minggu ini"
    BUDGET            — "cek budget", "anggaran makan"
    GOAL              — "nabung buat motor", "progress goal"
    MEMORY_UPDATE     — "ingat ya: gajiku 5 juta", "preferensiku bayar pakai gopay"
    SMALL_TALK        — "oke", "makasih", "haha"
    UNKNOWN           — cannot classify confidently

Confidence score:
    1.0 — certain (exact keyword match, command)
    0.8 — very likely (strong signal)
    0.6 — likely (moderate signal)
    0.4 — uncertain (weak signal, may need AI to confirm)
    0.2 — very uncertain
"""

from __future__ import annotations

import re
from enum import Enum
from dataclasses import dataclass


class MessageType(str, Enum):
    TRANSACTION = "Transaction"
    TRANSFER = "Transfer"
    QUESTION = "Question"
    FINANCIAL_ANALYSIS = "Financial Analysis"
    REPORT = "Report"
    BUDGET = "Budget"
    GOAL = "Goal"
    MEMORY_UPDATE = "Memory Update"
    SMALL_TALK = "Small Talk"
    UNKNOWN = "Unknown"


@dataclass
class RouterResult:
    message_type: MessageType
    confidence: float          # 0.0–1.0
    signals: list[str]         # debug: which signals triggered the classification
    needs_ai: bool             # does this type require an AI call?
    sub_intent: str = ""       # optional refinement (e.g. "pemasukan" vs "pengeluaran")


# ------------------------------------------------------------------ #
# Signal dictionaries                                                  #
# ------------------------------------------------------------------ #

_SMALL_TALK_EXACT = frozenset({
    "haha", "hehe", "hihi", "wkwk", "lol", "oke", "ok", "okay",
    "iya", "yep", "yup", "yes", "no", "nope", "gak", "ga",
    "makasih", "thanks", "thank you", "mantap", "keren", "sip",
    "noted", "siap", "done", "selesai", "beres", "aman",
    "good", "nice", "great", "wow", "wah", "hmm", "hm",
    "😊", "👍", "🙏", "❤️", "😂", "😄",
})

_TRANSFER_KEYWORDS = frozenset({
    "transfer", "pindah", "pindahin", "kirim", "kirimin",
    "dari bca ke", "dari gopay ke", "dari dana ke",
    "dari cash ke", "dari jago ke",
})

_QUESTION_STARTERS = frozenset({
    "berapa", "apa", "apakah", "gimana", "bagaimana", "kenapa",
    "kapan", "siapa", "dimana", "kira-kira", "kira kira",
    "boleh tanya", "mau tanya", "tanya dong",
    "sudah berapa", "total berapa", "udah berapa",
})

_ANALYSIS_KEYWORDS = frozenset({
    "analisa", "analisis", "evaluasi", "review",
    "gimana keuangan", "bagaimana keuangan", "kondisi keuangan",
    "pola pengeluaran", "insight", "rekomendasi",
    "tips", "saran", "apa yang harus", "perlu kurangi",
})

_REPORT_KEYWORDS = frozenset({
    "ringkasan", "rekap", "laporan", "summary", "report",
    "terakhir", "riwayat", "history",
})

_BUDGET_KEYWORDS = frozenset({
    "budget", "anggaran", "batas", "limit", "pengeluaran maksimal",
    "masih bisa belanja", "sisa budget",
})

_GOAL_KEYWORDS = frozenset({
    "goal", "target", "tabungan", "nabung", "saving", "impian",
    "rencana beli", "mau beli", "progress goal", "capai target",
})

_MEMORY_TRIGGERS = frozenset({
    "ingat ya", "ingat:", "catat:", "preferensiku", "gajiku",
    "biasanya aku", "tanggal gajiku", "akunku",
    "remember:", "note:", "simpan info",
})

# Income signal keywords (strong indicator of TRANSACTION/pemasukan)
_INCOME_KEYWORDS = frozenset({
    "gajian", "gaji", "dapat", "terima", "masuk", "bonus",
    "dividen", "profit", "penghasilan", "income", "earned",
    "dibayar", "terbayar", "diterima",
})

# Expense signal keywords (strong indicator of TRANSACTION/pengeluaran)
_EXPENSE_KEYWORDS = frozenset({
    "beli", "bayar", "bayarin", "jajan", "makan", "minum",
    "order", "checkout", "isi", "top up", "topup", "reload",
    "bayar", "lunas", "transfer ke", "kirim ke",
    "belanja", "beli", "habis", "abis", "keluar",
})

# Amount patterns — strong indicator of transaction
_AMOUNT_PATTERN = re.compile(
    r'\b(\d{1,3}(?:[.,]\d{3})*|\d+)\s*(?:rb|ribu|k|rbu|jt|juta|m|M|miliar|000)?\b'
    r'|\bRp\.?\s*\d'
    r'|\d+\s*(?:rb|ribu|k|jt|juta)',
    re.IGNORECASE,
)


class Router:
    """
    Classifies messages without calling AI.

    The Router uses rule-based pattern matching to achieve
    deterministic, fast, zero-cost classification for the
    vast majority of messages.
    """

    def classify(self, text: str) -> RouterResult:
        """
        Classify a free-text message.

        Returns RouterResult with type, confidence, and whether AI is needed.
        """
        if not text or not text.strip():
            return RouterResult(
                message_type=MessageType.SMALL_TALK,
                confidence=1.0,
                signals=["empty_text"],
                needs_ai=False,
            )

        text_stripped = text.strip()
        text_lower = text_stripped.lower()
        words = text_lower.split()

        # 1. Small talk (exact match — highest priority, zero ambiguity)
        if text_lower in _SMALL_TALK_EXACT:
            return RouterResult(
                message_type=MessageType.SMALL_TALK,
                confidence=1.0,
                signals=["exact_small_talk"],
                needs_ai=False,
            )

        # Very short text without numbers → likely small talk
        if len(text_stripped) <= 5 and not _AMOUNT_PATTERN.search(text_stripped):
            return RouterResult(
                message_type=MessageType.SMALL_TALK,
                confidence=0.8,
                signals=["short_no_amount"],
                needs_ai=False,
            )

        # 2. Memory update (explicit instruction)
        for trigger in _MEMORY_TRIGGERS:
            if trigger in text_lower:
                return RouterResult(
                    message_type=MessageType.MEMORY_UPDATE,
                    confidence=0.9,
                    signals=[f"memory_trigger:{trigger}"],
                    needs_ai=False,
                )

        # 3. Transfer (very specific pattern)
        has_transfer = any(kw in text_lower for kw in _TRANSFER_KEYWORDS)
        if has_transfer and _AMOUNT_PATTERN.search(text_stripped):
            return RouterResult(
                message_type=MessageType.TRANSFER,
                confidence=0.9,
                signals=["transfer_keyword", "amount_present"],
                needs_ai=True,
            )

        # 4. Question
        has_question = (
            text_stripped.endswith("?")
            or any(text_lower.startswith(qs) for qs in _QUESTION_STARTERS)
            or any(qs in text_lower for qs in _QUESTION_STARTERS)
        )
        if has_question:
            # Analysis vs simple question
            has_analysis = any(kw in text_lower for kw in _ANALYSIS_KEYWORDS)
            if has_analysis:
                return RouterResult(
                    message_type=MessageType.FINANCIAL_ANALYSIS,
                    confidence=0.8,
                    signals=["question_mark", "analysis_keyword"],
                    needs_ai=True,
                )
            return RouterResult(
                message_type=MessageType.QUESTION,
                confidence=0.8,
                signals=["question_pattern"],
                needs_ai=True,
            )

        # 5. Budget
        if any(kw in text_lower for kw in _BUDGET_KEYWORDS):
            return RouterResult(
                message_type=MessageType.BUDGET,
                confidence=0.85,
                signals=["budget_keyword"],
                needs_ai=False,
            )

        # 6. Goal
        if any(kw in text_lower for kw in _GOAL_KEYWORDS):
            return RouterResult(
                message_type=MessageType.GOAL,
                confidence=0.8,
                signals=["goal_keyword"],
                needs_ai=False,
            )

        # 7. Report / analysis (no question mark)
        if any(kw in text_lower for kw in _REPORT_KEYWORDS):
            return RouterResult(
                message_type=MessageType.REPORT,
                confidence=0.85,
                signals=["report_keyword"],
                needs_ai=False,
            )
        if any(kw in text_lower for kw in _ANALYSIS_KEYWORDS):
            return RouterResult(
                message_type=MessageType.FINANCIAL_ANALYSIS,
                confidence=0.8,
                signals=["analysis_keyword"],
                needs_ai=True,
            )

        # 8. Transaction — key signal: amount present
        has_amount = bool(_AMOUNT_PATTERN.search(text_stripped))
        has_income = any(kw in text_lower for kw in _INCOME_KEYWORDS)
        has_expense = any(kw in text_lower for kw in _EXPENSE_KEYWORDS)

        if has_amount:
            signals = ["amount_present"]
            sub_intent = ""
            if has_income:
                signals.append("income_keyword")
                sub_intent = "pemasukan"
            if has_expense:
                signals.append("expense_keyword")
                sub_intent = "pengeluaran"
            confidence = 0.85 if (has_income or has_expense) else 0.7
            return RouterResult(
                message_type=MessageType.TRANSACTION,
                confidence=confidence,
                signals=signals,
                needs_ai=True,
                sub_intent=sub_intent,
            )

        # 9. Weak signals — needs AI to figure it out
        if len(text_stripped) > 10:
            return RouterResult(
                message_type=MessageType.UNKNOWN,
                confidence=0.4,
                signals=["no_clear_signal"],
                needs_ai=True,
            )

        # Default: small talk
        return RouterResult(
            message_type=MessageType.SMALL_TALK,
            confidence=0.6,
            signals=["default_small_talk"],
            needs_ai=False,
        )

    def needs_ai(self, result: RouterResult) -> bool:
        """Quick check: does this classification require an AI call?"""
        return result.needs_ai and result.message_type not in (
            MessageType.SMALL_TALK,
            MessageType.REPORT,
            MessageType.BUDGET,
            MessageType.GOAL,
        )
