"""
Decision Engine — evaluates confidence before answering.

Before Brain gives a response, the Decision Engine asks:
1. What do we know?
2. What is still unknown?
3. Is the confidence high enough to proceed?
4. Is the answer safe to give?

Quality Score:
    Every response has an internal score:
    - accuracy:      is the data correct?
    - completeness:  is all required info present?
    - confidence:    how certain is the AI parse?
    - safety:        is giving this response safe?
    - consistency:   is this consistent with known user data?

If overall score < MIN_ACCEPTABLE_SCORE, Brain asks for clarification
instead of saving or responding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import EXPENSE_CATEGORIES, INCOME_CATEGORIES, NON_BUDGET_CATEGORIES, DAFTAR_AKUN

logger = logging.getLogger(__name__)

# Thresholds
MIN_CONFIDENCE_TO_SAVE = 0.65    # below this → ask for clarification
MIN_CONFIDENCE_REPORT  = 0.55    # for reports/answers, slightly more lenient
MAX_REASONABLE_AMOUNT  = 500_000_000  # 500 juta — sanity cap


@dataclass
class QualityScore:
    """Internal quality score for every Brain response."""
    accuracy: float      # 0.0–1.0 — is the data correct/validated?
    completeness: float  # 0.0–1.0 — is all required info present?
    confidence: float    # 0.0–1.0 — how certain is the AI/rule parse?
    safety: float        # 0.0–1.0 — is it safe to act on this?
    consistency: float   # 0.0–1.0 — consistent with known context?

    @property
    def overall(self) -> float:
        """Weighted average — safety has double weight."""
        return (
            self.accuracy * 0.2
            + self.completeness * 0.2
            + self.confidence * 0.3
            + self.safety * 0.2
            + self.consistency * 0.1
        )

    @property
    def is_acceptable(self) -> bool:
        return self.overall >= MIN_CONFIDENCE_TO_SAVE

    @property
    def grade(self) -> str:
        s = self.overall
        if s >= 0.9:
            return "A"
        if s >= 0.75:
            return "B"
        if s >= 0.6:
            return "C"
        if s >= 0.45:
            return "D"
        return "F"

    def summary(self) -> str:
        return (
            f"score={self.overall:.2f} [{self.grade}] "
            f"acc={self.accuracy:.2f} comp={self.completeness:.2f} "
            f"conf={self.confidence:.2f} safe={self.safety:.2f} cons={self.consistency:.2f}"
        )


@dataclass
class DecisionResult:
    """What Brain should do after evaluation."""
    should_proceed: bool                   # True → execute, False → ask clarification
    reason: str                            # why this decision was made
    quality: QualityScore
    clarification_needed: list[str]        # fields that need clarification
    clarification_question: Optional[str]  # pre-built question to ask user
    corrected_data: Optional[dict]         # if we corrected something, what changed


class DecisionEngine:
    """
    Evaluates parsed data before Brain acts on it.

    Called after Router classifies and AI parses (if needed).
    Returns a DecisionResult that tells Brain whether to proceed.
    """

    def evaluate_transaction(
        self,
        parsed: dict,
        user_context: Optional[dict] = None,
    ) -> DecisionResult:
        """
        Evaluate a parsed transaction before saving it.

        Args:
            parsed: output from AIEngine.parse_transaction() as dict
            user_context: optional — known user data for consistency check
        """
        issues: list[str] = []
        corrections: dict = {}

        tipe = parsed.get("tipe", "")
        jumlah = float(parsed.get("jumlah", 0) or 0)
        kategori = parsed.get("kategori", "")
        memo = parsed.get("memo", "")
        akun = parsed.get("akun", "Cash")
        ai_confidence = float(parsed.get("confidence", 0.75))

        # ── Accuracy checks ──
        accuracy = 1.0

        # Amount sanity
        if jumlah <= 0:
            issues.append("jumlah")
            accuracy -= 0.4
        elif jumlah > MAX_REASONABLE_AMOUNT:
            issues.append("jumlah_terlalu_besar")
            accuracy -= 0.2

        # Category validation
        valid_categories = EXPENSE_CATEGORIES + INCOME_CATEGORIES + NON_BUDGET_CATEGORIES
        if kategori not in valid_categories:
            logger.warning(f"Invalid kategori: {kategori!r}")
            corrections["kategori"] = "Lain-lain"
            parsed = {**parsed, "kategori": "Lain-lain"}
            accuracy -= 0.2

        # Account validation
        if akun not in DAFTAR_AKUN:
            logger.warning(f"Invalid akun: {akun!r}, correcting to Cash")
            corrections["akun"] = "Cash"
            parsed = {**parsed, "akun": "Cash"}
            accuracy -= 0.1

        # ── Completeness checks ──
        completeness = 1.0
        if not memo or memo == "-":
            issues.append("memo")
            completeness -= 0.2
        if not tipe:
            issues.append("tipe")
            completeness -= 0.3

        # ── Safety checks ──
        safety = 1.0
        # Pengeluaran should be in expense categories, Pemasukan in income
        if tipe == "Pengeluaran" and kategori in INCOME_CATEGORIES:
            issues.append("kategori_tipe_mismatch")
            safety -= 0.3
        elif tipe == "Pemasukan" and kategori in EXPENSE_CATEGORIES:
            issues.append("kategori_tipe_mismatch")
            safety -= 0.3

        # ── Consistency checks ──
        consistency = 1.0
        # (Future: compare with user's known patterns from memory)

        # Clamp all scores
        accuracy = max(0.0, min(1.0, accuracy))
        completeness = max(0.0, min(1.0, completeness))
        safety = max(0.0, min(1.0, safety))

        quality = QualityScore(
            accuracy=accuracy,
            completeness=completeness,
            confidence=ai_confidence,
            safety=safety,
            consistency=consistency,
        )

        logger.debug(f"Transaction quality: {quality.summary()}")

        # Build decision
        should_proceed = quality.is_acceptable and not bool(
            {"jumlah", "tipe"} & set(issues)
        )

        clarification_q = None
        if not should_proceed:
            clarification_q = self._build_clarification_question(issues, parsed)

        return DecisionResult(
            should_proceed=should_proceed,
            reason=f"quality={quality.grade}, issues={issues}",
            quality=quality,
            clarification_needed=issues,
            clarification_question=clarification_q,
            corrected_data=corrections if corrections else None,
        )

    def evaluate_answer(
        self,
        question: str,
        answer: str,
        data_record_count: int,
    ) -> DecisionResult:
        """
        Evaluate an AI-generated answer before sending it to user.

        Args:
            question: what user asked
            answer: what AI returned
            data_record_count: how many transactions were used as context
        """
        accuracy = 1.0
        completeness = 1.0
        safety = 1.0

        # If no data, answer might be fabricated
        if data_record_count == 0:
            accuracy = 0.5
            safety = 0.7

        # Very short answer might indicate failure
        if len(answer) < 10:
            completeness = 0.3

        # Check for refusal patterns (AI saying it doesn't know)
        refusal_patterns = ["tidak tahu", "tidak bisa", "maaf", "belum ada data"]
        if any(p in answer.lower() for p in refusal_patterns):
            accuracy = 0.7  # honest refusal is still somewhat accurate

        quality = QualityScore(
            accuracy=accuracy,
            completeness=completeness,
            confidence=0.8,  # answers are less binary than transactions
            safety=safety,
            consistency=1.0,
        )

        should_proceed = quality.overall >= MIN_CONFIDENCE_REPORT

        return DecisionResult(
            should_proceed=should_proceed,
            reason=f"answer_quality={quality.grade}, data_records={data_record_count}",
            quality=quality,
            clarification_needed=[],
            clarification_question=None,
            corrected_data=None,
        )

    def evaluate_quick_reply(
        self,
        data_available: bool,
        computation_successful: bool,
    ) -> DecisionResult:
        """
        Evaluate a Pure-Python calculation response (no AI involved).

        These have near-perfect accuracy by definition.
        """
        confidence = 1.0 if (data_available and computation_successful) else 0.3

        quality = QualityScore(
            accuracy=1.0 if computation_successful else 0.0,
            completeness=1.0 if data_available else 0.5,
            confidence=confidence,
            safety=1.0,
            consistency=1.0,
        )

        return DecisionResult(
            should_proceed=data_available and computation_successful,
            reason="pure_python_computation",
            quality=quality,
            clarification_needed=[],
            clarification_question=None,
            corrected_data=None,
        )

    @staticmethod
    def _build_clarification_question(issues: list[str], parsed: dict) -> str:
        """Build a user-friendly clarification question for missing/invalid fields."""
        if "jumlah" in issues:
            memo = parsed.get("memo", "itu")
            return f"Berapa jumlahnya {memo}? Aku kurang yakin dengan angkanya 🤔"

        if "tipe" in issues:
            return "Ini pengeluaran atau pemasukan ya? 💸"

        if "kategori_tipe_mismatch" in issues:
            return (
                f"Hmm, {parsed.get('memo', 'ini')} aku catat sebagai "
                f"*{parsed.get('tipe')}* kategori *{parsed.get('kategori')}*. "
                "Bener ya? 🤔"
            )

        if "memo" in issues:
            return "Ini buat apa ya? Boleh disebutin nama barang/keperluannya? 😊"

        # Generic
        return "Bisa dijelaskan lebih detail? Aku kurang yakin dengan inputnya 🤔"
