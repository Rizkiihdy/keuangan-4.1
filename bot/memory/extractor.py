"""
Memory Extractor — extract facts from a conversation turn using AI.

DESIGN:
  - Runs AFTER the main response is sent (non-blocking background task)
  - Uses a lightweight, focused prompt — not the full AI engine pipeline
  - Returns empty list if nothing new found (do not write memory on every turn)
  - Sensitive data guard applied before any write

WHEN IT RUNS:
  - Only when the Brain used AI for the current turn (used_ai=True)
  - Not for pure-Python paths (saldo, ringkasan, etc.)
  - Not for small talk

WHAT IT EXTRACTS:
  - Identity facts: name, job, salary date, city, timezone, language
  - Financial goals: saving targets, life plans
  - Preferences: payment methods, account preferences
  - Habits: recurring behaviors explicitly mentioned
  - Long-term context: current life situations
  - NOT: transactions (already stored), sensitive data

WHAT IT DOES NOT EXTRACT:
  - Anything already in existing memory (avoids re-creating)
  - Sensitive data (passwords, PINs, OTPs, card numbers)
  - Transient small talk
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from memory.models import MemoryCategory, ExtractedFact

if TYPE_CHECKING:
    from engine.ai_engine import AIEngine

logger = logging.getLogger(__name__)

# Categories the extractor is allowed to write to.
# BEHAVIOUR is excluded — updated by BehaviourAnalyser from transaction patterns only.
_EXTRACTABLE_CATEGORIES = {
    "identity":           MemoryCategory.IDENTITY,
    "financial_goals":    MemoryCategory.FINANCIAL_GOALS,
    "preference":         MemoryCategory.PREFERENCE,
    "habit":              MemoryCategory.HABIT,
    "long_term_context":  MemoryCategory.LONG_TERM_CONTEXT,
}


class MemoryExtractor:
    """
    Extracts new facts from a conversation turn using a lightweight AI prompt.

    Called by ReflectionEngine after a Brain response is sent.
    """

    def __init__(self, ai_engine: "AIEngine"):
        self._ai = ai_engine

    async def extract_from_turn(
        self,
        user_message: str,
        bot_response: str,
        existing_summary: str = "",
    ) -> list[ExtractedFact]:
        """
        Extract facts from a single conversation turn.

        Args:
            user_message:    what the user said
            bot_response:    what Oliv responded (helps understand context)
            existing_summary: current memory summary (avoid re-extracting known facts)

        Returns:
            list of ExtractedFact — may be empty if nothing new found
        """
        prompt = self._build_prompt(user_message, bot_response, existing_summary)

        try:
            raw = await self._ai.extract_memory_async(prompt)
            if not raw or not raw.strip():
                return []
            return self._parse_response(raw)
        except Exception as e:
            logger.warning(f"Memory extraction failed: {e}")
            return []

    # ---------------------------------------------------------------- #
    # PRIVATE                                                            #
    # ---------------------------------------------------------------- #

    def _build_prompt(
        self,
        user_message: str,
        bot_response: str,
        existing_summary: str,
    ) -> str:
        existing_section = ""
        if existing_summary:
            existing_section = (
                f"\nFakta yang sudah diketahui (JANGAN duplikasi):\n{existing_summary}\n"
            )

        return (
            "Kamu adalah sistem ekstraksi memori untuk Oliv, asisten keuangan personal.\n\n"
            "Dari percakapan berikut, ekstrak HANYA fakta BARU yang penting tentang pengguna.\n\n"
            f"User: \"{user_message}\"\n"
            f"Oliv: \"{bot_response[:200]}\"\n"
            f"{existing_section}\n"
            "Kembalikan JSON array. Kosong jika tidak ada fakta baru:\n"
            "[\n"
            "  {\n"
            '    "category": "identity|preference|habit|financial_goals|long_term_context",\n'
            '    "key": "nama_fakta_singkat_snake_case",\n'
            '    "value": "nilai_fakta",\n'
            '    "confidence": 0.0-1.0\n'
            "  }\n"
            "]\n\n"
            "Kategori:\n"
            "  identity         → nama, pekerjaan, umur, kota, hari_gajian, timezone\n"
            "  preference       → akun_favorit, metode_bayar_favorit, minuman_favorit, merchant_favorit\n"
            "  habit            → kebiasaan rutin (menabung, investasi, bayar orang tua, olahraga)\n"
            "  financial_goals  → target tabungan/beli sesuatu (rumah, motor, liburan, dana darurat)\n"
            "  long_term_context→ kondisi hidup saat ini (nabung rumah, kurangi kopi, lunasi hutang)\n\n"
            "JANGAN ekstrak:\n"
            "  - Transaksi keuangan (sudah tersimpan di database)\n"
            "  - Informasi sudah ada di 'Fakta yang sudah diketahui'\n"
            "  - Data sensitif (password, PIN, OTP, nomor kartu, CVV)\n"
            "  - Small talk biasa\n"
            "  - Informasi yang tidak jelas / terlalu umum\n\n"
            "CONTOH fakta yang LAYAK:\n"
            "  User: 'btw gajiku tanggal 25' → identity/hari_gajian: '25'\n"
            "  User: 'aku lagi nabung buat DP rumah' → financial_goals/dp_rumah: 'sedang ditabung'\n"
            "  User: 'biasanya aku bayar pakai gopay' → preference/metode_bayar_favorit: 'GoPay'\n"
            "  User: 'aku kerja di startup' → identity/pekerjaan: 'startup'\n\n"
            "Kembalikan HANYA JSON array valid, tanpa penjelasan, tanpa ```."
        )

    def _parse_response(self, raw: str) -> list[ExtractedFact]:
        """Parse AI response into list of ExtractedFact."""
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()

        # Extract JSON array from response
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            logger.debug(f"No JSON array found in extraction response: {raw[:100]}")
            return []

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning(f"Extraction JSON parse error: {e}")
            return []

        if not isinstance(data, list):
            return []

        facts = []
        for item in data:
            if not isinstance(item, dict):
                continue

            category_str = str(item.get("category", "")).strip().lower()
            key = str(item.get("key", "")).strip().lower()
            value = str(item.get("value", "")).strip()

            if not category_str or not key or not value:
                continue

            category = _EXTRACTABLE_CATEGORIES.get(category_str)
            if not category:
                logger.debug(f"Unknown category in extraction: {category_str!r}")
                continue

            try:
                confidence = float(item.get("confidence", 0.7))
                confidence = max(0.1, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = 0.7

            facts.append(ExtractedFact(
                category=category,
                key=key,
                value=value,
                confidence=confidence,
                source="ai_extracted",
            ))

        return facts
