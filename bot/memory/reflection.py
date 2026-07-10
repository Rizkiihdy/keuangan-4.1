"""
Reflection Engine — post-conversation memory updates.

The Reflection Engine runs AFTER Brain sends a response to the user.
It is always called as a background asyncio task (fire-and-forget).
It must NEVER block the main response path.

TWO SUBSYSTEMS:

1. MemoryExtractor (AI-powered, async)
   - Extracts new facts from the conversation turn
   - Only runs when used_ai=True
   - Only runs for messages with substantive user text (not commands)

2. BehaviourAnalyser (Python-only, sync)
   - Derives behaviour patterns from a new transaction
   - Runs on every transaction save
   - Updates BEHAVIOUR memories (category spend, coffee freq, etc.)

REFLECTION POLICY:
  - Errors are silently logged, never raised (caller never sees errors)
  - Importance scores are recalculated every 50 turns (via counter)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from memory.models import MemoryCategory, ReflectionResult

if TYPE_CHECKING:
    from memory.engine import MemoryEngine
    from memory.extractor import MemoryExtractor

logger = logging.getLogger(__name__)

# How many reflection calls before recalculating importance scores
_RECALC_INTERVAL = 50


class ReflectionEngine:
    """
    Coordinates post-conversation memory updates.

    Usage (in Brain):
        asyncio.create_task(
            self._reflection.reflect_on_turn(
                user_id=str(chat_id),
                user_message=text,
                bot_response=response.text,
                transaction_data=response.pending_transaction,
                used_ai=response.used_ai,
            )
        )
    """

    def __init__(
        self,
        memory_engine: "MemoryEngine",
        extractor: "MemoryExtractor",
    ):
        self._memory = memory_engine
        self._extractor = extractor
        self._analyser = BehaviourAnalyser(memory_engine)
        self._turn_counter: dict[str, int] = {}

    async def reflect_on_turn(
        self,
        user_id: str,
        user_message: str,
        bot_response: str,
        transaction_data: Optional[dict] = None,
        used_ai: bool = False,
    ) -> ReflectionResult:
        """
        Main reflection entry point. Always returns a result, never raises.

        Steps:
        1. Update behaviour from transaction (if any) — pure Python
        2. Extract facts from conversation (if AI was used) — AI call
        3. Periodically recalculate importance scores
        """
        result = ReflectionResult()

        # Step 1: Behaviour update from transaction (sync, fast)
        if transaction_data:
            try:
                added, updated = self._analyser.update_from_transaction(
                    user_id, transaction_data
                )
                result.facts_added += added
                result.facts_updated += updated
                result.notes.append(f"behaviour: +{added} new, ~{updated} updated")
            except Exception as e:
                logger.warning(f"Behaviour update error for {user_id}: {e}")
                result.errors.append(str(e))

        # Step 2: AI extraction (async, only when AI was used)
        if used_ai and _should_extract(user_message):
            try:
                existing_summary = self._memory.get_context_summary(
                    user_id, max_items=5, min_importance=0.3
                )
                facts = await self._extractor.extract_from_turn(
                    user_message=user_message,
                    bot_response=bot_response,
                    existing_summary=existing_summary,
                )
                if facts:
                    created, updated = self._memory.apply_facts(user_id, facts)
                    result.facts_added += created
                    result.facts_updated += updated
                    result.notes.append(
                        f"extraction: {len(facts)} facts → +{created} new, ~{updated} updated"
                    )
            except Exception as e:
                logger.warning(f"Memory extraction error for {user_id}: {e}")
                result.errors.append(str(e))

        # Step 3: Periodic score recalculation
        self._turn_counter[user_id] = self._turn_counter.get(user_id, 0) + 1
        if self._turn_counter[user_id] % _RECALC_INTERVAL == 0:
            try:
                self._memory.recalculate_scores(user_id)
                result.notes.append("importance scores recalculated")
            except Exception as e:
                logger.warning(f"Score recalc error for {user_id}: {e}")

        if result.facts_added + result.facts_updated > 0:
            logger.info(
                f"Reflection [{user_id}]: {result.summary()} | "
                f"total_memories={self._memory.get_all_count(user_id)}"
            )

        return result


# ------------------------------------------------------------------ #
# BEHAVIOUR ANALYSER (pure Python, no AI)                             #
# ------------------------------------------------------------------ #

class BehaviourAnalyser:
    """
    Derives behaviour patterns from new transactions.
    Updates BEHAVIOUR memories without any AI calls.

    Tracked patterns:
      - frekuensi_kopi       — how often the user buys coffee
      - merchant_sering      — most visited merchants
      - kategori_terboros    — category with most transactions count
      - jam_transaksi_utama  — primary hour of day for transactions
      - akun_terbanyak       — most used payment account
    """

    def __init__(self, memory_engine: "MemoryEngine"):
        self._memory = memory_engine

    def update_from_transaction(
        self,
        user_id: str,
        txn: dict,
    ) -> tuple[int, int]:
        """
        Update BEHAVIOUR memories from a new transaction.
        Returns (created, updated) counts.
        """
        updates: list[tuple[str, str, float]] = []   # (key, value, importance)

        memo = (txn.get("memo") or "").lower()
        payee = (txn.get("payee") or "").lower().strip()
        kategori = txn.get("kategori", "")
        akun = txn.get("akun", "")
        jumlah = float(txn.get("jumlah") or txn.get("payment") or 0)

        # Coffee frequency signal
        _COFFEE_SIGNALS = {"kopi", "coffee", "starbucks", "kopi kenangan", "janji jiwa",
                           "fore coffee", "excelso", "gofood kopi", "grabfood kopi", "boba"}
        if any(s in memo for s in _COFFEE_SIGNALS) or any(s in payee for s in _COFFEE_SIGNALS):
            # Get current count and increment
            current = self._get_behaviour_value(user_id, "frekuensi_kopi")
            try:
                count = int(current) + 1 if current else 1
            except (ValueError, TypeError):
                count = 1
            updates.append(("frekuensi_kopi", str(count), 0.6))

        # Merchant tracking (only named merchants, not generic)
        if payee and len(payee) > 3 and payee not in {"-", "unknown", "cash"}:
            merchant_clean = payee[:40].title()
            updates.append(("merchant_terakhir", merchant_clean, 0.4))

        # Most used account
        if akun and akun != "Cash":
            updates.append(("akun_sering_dipakai", akun, 0.5))

        # Transaction time pattern
        now_hour = datetime.now(timezone.utc).hour + 7  # WIB
        if now_hour >= 24:
            now_hour -= 24
        if 5 <= now_hour < 12:
            period = "pagi"
        elif 12 <= now_hour < 15:
            period = "siang"
        elif 15 <= now_hour < 19:
            period = "sore"
        else:
            period = "malam"
        updates.append(("jam_aktif_transaksi", period, 0.4))

        # Big ticket item
        if jumlah >= 500_000:
            updates.append(("pengeluaran_besar_terakhir",
                            f"{kategori} Rp{jumlah:,.0f}", 0.5))

        # Apply all updates
        created = updated = 0
        for key, value, importance in updates:
            try:
                _, was_new = self._memory.merge(
                    user_id=user_id,
                    category=MemoryCategory.BEHAVIOUR,
                    key=key,
                    value=value,
                    source="behaviour_analysis",
                    confidence=0.9,
                    importance=importance,
                )
                if was_new:
                    created += 1
                else:
                    updated += 1
            except ValueError:
                pass   # sensitive data guard — shouldn't happen for behaviour data

        return created, updated

    def _get_behaviour_value(self, user_id: str, key: str) -> Optional[str]:
        items = self._memory.search(
            user_id=user_id,
            query=key,
            category=MemoryCategory.BEHAVIOUR,
            limit=1,
        )
        return items[0].value if items else None


# ------------------------------------------------------------------ #
# HELPERS                                                              #
# ------------------------------------------------------------------ #

def _should_extract(user_message: str) -> bool:
    """
    Decide if this message is worth running AI extraction on.
    Avoids wasting AI calls on short/obvious messages.
    """
    if not user_message or len(user_message.strip()) < 8:
        return False
    # Skip pure numeric (transaction amounts without context)
    stripped = user_message.strip()
    if stripped.replace(".", "").replace(",", "").replace("k", "").replace("rb", "").isdigit():
        return False
    return True
