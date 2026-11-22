"""
AI Engine — Natural Language Understanding and reasoning only.

CONTRACT:
    AI is allowed to:
    - Parse natural language into structured transaction data
    - Understand receipt photos
    - Reason about financial patterns given pre-calculated data
    - Generate human-friendly suggestions and reflections
    - Answer conversational questions

    AI is NOT allowed to:
    - Calculate saldo, budget totals, or any arithmetic
    - Access Google Sheets
    - Return numbers without being given data
    - Run without confidence scoring

This module wraps gemini_ai.GeminiAI and enforces these contracts.
It also fixes the async issue (CQ-07) and category mismatch (CQ-05).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import os
from typing import Optional

from google import genai
from google.genai import types as genai_types
from google.genai import errors as genai_errors

from config import (
    EXPENSE_CATEGORIES, INCOME_CATEGORIES, NON_BUDGET_CATEGORIES,
    DAFTAR_AKUN, AKUN_KEYWORDS, FALLBACK_KEYWORDS,
)

logger = logging.getLogger(__name__)

# Model priority chains.
# New Gemini projects should use current 3.x models. Gemini 2.5 inference
# can return 404 for projects without prior usage, even when listed in AI Studio.
TEXT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
]

VISION_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
]

# CQ-05 fix: only use categories that exist in the system
_EXPENSE_STR = '", "'.join(EXPENSE_CATEGORIES)
_ALL_CAT_STR = '", "'.join(EXPENSE_CATEGORIES + INCOME_CATEGORIES + NON_BUDGET_CATEGORIES)


class QuotaExhaustedError(Exception):
    """All Gemini models have reached rate limit."""
    pass


class AIParseError(Exception):
    """AI returned unparseable or invalid response."""
    pass


from dataclasses import dataclass as _dataclass, field as _field


@_dataclass
class ParsedTransaction:
    """
    Result of transaction parsing.

    confidence is added to every parse result so Decision Engine
    can evaluate whether to ask for clarification (AI-01 fix).
    """
    tipe: str
    jumlah: float
    kategori: str
    memo: str
    payee: str
    akun: str
    confidence: float   # 0.0-1.0
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "tipe": self.tipe,
            "jumlah": self.jumlah,
            "kategori": self.kategori,
            "memo": self.memo,
            "payee": self.payee,
            "akun": self.akun,
            "confidence": self.confidence,
        }

    def is_transfer(self) -> bool:
        return self.kategori == "[Transfer]"


class AIEngine:
    """
    AI Engine — enforces the AI contract.

    Instantiation is lazy: the Gemini client is created on first use,
    not at import time (CQ-02 fix).
    """

    def __init__(self):
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            api_key = os.environ.get("GEMINI_API_KEY", "")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
            self._client = genai.Client(api_key=api_key)
            logger.info("Gemini AI client initialized.")
        return self._client

    # ---------------------------------------------------------------- #
    # NLU — Transaction Parsing                                          #
    # ---------------------------------------------------------------- #

    def parse_transaction(self, text: str, user_context_hint: str = "") -> ParsedTransaction | None:
        """
        Parse free-text into a structured transaction.

        Args:
            text: raw user message
            user_context_hint: optional snippet from Memory for better accuracy

        Returns:
            ParsedTransaction with confidence score, or None if not a transaction.
        """
        context_section = ""
        if user_context_hint:
            context_section = (
                f"\nKonteks user (gunakan untuk akurasi lebih baik):\n{user_context_hint}\n"
            )

        prompt = (
            "Kamu adalah Oliv, asisten keuangan pribadi.\n"
            "Analisis teks transaksi dan kembalikan JSON.\n"
            f"{context_section}\n"
            "Format JSON WAJIB:\n"
            "{\n"
            '  "tipe": "Pengeluaran" atau "Pemasukan",\n'
            '  "jumlah": angka bulat (contoh: "10.000"→10000, "2 juta"→2000000, "50k"→50000),\n'
            f'  "kategori": pilih HANYA dari: "{_ALL_CAT_STR}",\n'
            '  "memo": nama barang/item singkat (maks 3 kata, contoh: "Kopi", "Nasi Padang"),\n'
            '  "payee": keterangan lengkap (toko + konteks, bebas panjang),\n'
            '  "akun": nama akun (Cash, BCA, GoPay, ShopeePay, DANA, RDN, Jago, Tabungan 27Th, Dana Darurat, Investasi),\n'
            '  "confidence": angka 0.0-1.0 seberapa yakin kamu dengan parsing ini\n'
            "}\n\n"
            "Panduan kategori:\n"
            "- Makan/minum/kopi/rokok → Makan & Minum\n"
            "- Grab/Gojek/bensin/parkir/tol → Transportasi\n"
            "- Pulsa/kuota/wifi/internet → Pulsa / Internet\n"
            "- Listrik/air/gas/cicilan/asuransi → Cicilan & Tagihan\n"
            "- Bioskop/game/Netflix/Spotify/gym → Hiburan & Lifestyle\n"
            "- Sewa/kos/renovasi → Tempat Tinggal (Housing)\n"
            "- Dokter/obat/apotek → Kesehatan\n"
            "- Baju/sepatu/tas/skincare/elektronik → Belanja Pakaian & Barang\n"
            "- Kursus/buku/sekolah → Pendidikan\n"
            "- Sedekah/infaq/donasi/hadiah → Hadiah & Sosial\n"
            "- Supplies/marketing/iklan → Bisnis\n"
            "- Transfer antar akun → [Transfer]\n"
            "- Gaji → Gaji | Bonus/THR → Bonus | Dividen → Dividen | Freelance → Usaha\n\n"
            "PENTING:\n"
            "- Rokok SELALU 'Makan & Minum'\n"
            "- Jika bukan transaksi keuangan: {\"tipe\": null}\n"
            "- Kembalikan HANYA JSON valid, tanpa markdown, tanpa penjelasan\n\n"
            f'Teks: "{text}"'
        )

        try:
            raw = self._strip_json(self._generate_text(prompt))
            data = json.loads(raw)

            if data.get("tipe") is None:
                return None

            akun = data.get("akun", "Cash")
            if akun not in DAFTAR_AKUN:
                akun = "Cash"

            # Validate and clamp confidence
            confidence = float(data.get("confidence", 0.75))
            confidence = max(0.0, min(1.0, confidence))

            # If kategori is invalid, lower confidence
            kategori = str(data.get("kategori", "Lain-lain"))
            from config import ALL_CATEGORIES
            if kategori not in ALL_CATEGORIES:
                logger.warning(f"AI returned unknown kategori: {kategori!r}, falling back to Lain-lain")
                kategori = "Lain-lain"
                confidence = min(confidence, 0.5)

            return ParsedTransaction(
                tipe=str(data["tipe"]),
                jumlah=float(data["jumlah"]),
                kategori=kategori,
                memo=str(data.get("memo", "-")),
                payee=str(data.get("payee", "-")),
                akun=akun,
                confidence=confidence,
                raw_text=text,
            )

        except QuotaExhaustedError:
            raise
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Transaction parse failed: {e} | raw: {raw!r}")
            return None

    def parse_receipt_photo(
        self, image_bytes: bytes, mime_type: str
    ) -> ParsedTransaction | None:
        """
        Parse a receipt photo into a structured transaction.

        CQ-05 fix: only uses categories that exist in the system.
        """
        prompt = (
            "Kamu adalah Oliv, asisten keuangan pribadi.\n"
            "Analisis foto struk/nota/receipt ini.\n\n"
            "Kembalikan HANYA JSON valid:\n"
            "{\n"
            '  "tipe": "Pengeluaran",\n'
            '  "jumlah": total yang dibayar (angka bulat, tanpa simbol),\n'
            f'  "kategori": pilih HANYA dari: "{_EXPENSE_STR}",\n'
            '  "memo": nama barang/item utama (maks 3 kata),\n'
            '  "payee": nama toko + keterangan (bebas panjang),\n'
            '  "items": item utama yang dibeli, pisahkan koma (maks 5 item),\n'
            '  "akun": deteksi dari struk (Cash, GoPay, BCA, ShopeePay, DANA, dll),\n'
            '  "confidence": 0.0-1.0 seberapa yakin dengan data yang dibaca\n'
            "}\n\n"
            "Panduan kategori (HANYA gunakan yang ada di list):\n"
            "- Indomaret/Alfamart → lihat isi: makanan → Makan & Minum, produk → Belanja Pakaian & Barang\n"
            "- Restoran/warung/kafe → Makan & Minum\n"
            "- Apotek/klinik/RS → Kesehatan\n"
            "- Grab/Gojek/bensin/parkir → Transportasi\n"
            "- Supermarket/dept store → Belanja Pakaian & Barang\n"
            "- Listrik/air/internet/pulsa → Cicilan & Tagihan\n"
            "- Bioskop/game/rekreasi → Hiburan & Lifestyle\n"
            "- Salon/spa/barbershop/gym → Hiburan & Lifestyle\n"
            "- Toko HP/elektronik → Belanja Pakaian & Barang\n\n"
            "Jika BUKAN struk belanja: {\"tipe\": null}\n\n"
            "PENTING: Kembalikan HANYA JSON, tanpa penjelasan, tanpa ```."
        )

        try:
            raw = self._strip_json(self._generate_vision(image_bytes, mime_type, prompt))
            data = json.loads(raw)

            if data.get("tipe") is None:
                return None

            akun = data.get("akun", "Cash")
            if akun not in DAFTAR_AKUN:
                akun = "Cash"

            confidence = float(data.get("confidence", 0.7))
            confidence = max(0.0, min(1.0, confidence))

            kategori = str(data.get("kategori", "Lain-lain"))
            if kategori not in EXPENSE_CATEGORIES:
                logger.warning(f"Receipt: unknown kategori {kategori!r}, using Lain-lain")
                kategori = "Lain-lain"
                confidence = min(confidence, 0.5)

            # Attach items as extra field (not in ParsedTransaction slots)
            result = ParsedTransaction(
                tipe="Pengeluaran",
                jumlah=float(data.get("jumlah", 0)),
                kategori=kategori,
                memo=str(data.get("memo", "-")),
                payee=str(data.get("payee", "-")),
                akun=akun,
                confidence=confidence,
            )
            # Attach items as attribute (dynamic)
            object.__setattr__(result, "items", str(data.get("items", ""))) if False else None
            result.__dict__["items"] = str(data.get("items", ""))
            return result

        except QuotaExhaustedError:
            raise
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Receipt parse failed: {e} | raw: {raw!r}")
            return None

    # ---------------------------------------------------------------- #
    # REASONING — called only with pre-calculated data from FinancialEngine
    # ---------------------------------------------------------------- #

    def generate_insight(
        self,
        user_name: str,
        financial_summary: str,
        request_type: str = "analisa",
    ) -> str:
        """
        Generate a human-friendly insight based on pre-calculated financial data.

        IMPORTANT: financial_summary must be pre-calculated by FinancialEngine.
        This method does NOT receive raw transactions — it receives already-computed
        summaries. AI reasons about the numbers, never recalculates them.
        """
        prompt = (
            f"Kamu adalah Oliv, asisten keuangan personal untuk {user_name}. "
            "Berikan insight berdasarkan DATA BERIKUT yang sudah dihitung:\n\n"
            f"{financial_summary}\n\n"
            f"Tugas: {request_type}\n\n"
            "Panduan:\n"
            "- Gunakan angka yang SUDAH ADA di data. Jangan hitung ulang.\n"
            "- Fokus pada insight yang actionable\n"
            "- Bahasa Indonesia casual, gaya teman dekat\n"
            "- Maks 200 kata\n"
            "- Gunakan emoji secukupnya\n"
            "- Format Markdown (bold angka penting)"
        )
        return self._generate_text(prompt)

    def answer_question(
        self,
        question: str,
        user_name: str,
        financial_summary: str,
        memory_context: str = "",
    ) -> str:
        """
        Answer a financial question based on pre-calculated data.

        Args:
            question: user's question
            user_name: for personalization
            financial_summary: pre-calculated by FinancialEngine (NOT raw txns)
            memory_context: relevant long-term memory facts
        """
        memory_section = ""
        if memory_context:
            memory_section = f"\nKonteks tambahan tentang {user_name}:\n{memory_context}\n"

        prompt = (
            f"Kamu adalah Oliv, asisten keuangan untuk {user_name}.\n"
            f"Data keuangan yang sudah dihitung:\n{financial_summary}\n"
            f"{memory_section}\n"
            f"Pertanyaan: {question}\n\n"
            "Jawab berdasarkan data di atas. Jangan mengarang angka.\n"
            "Jika data tidak cukup, katakan dengan jujur.\n"
            "Bahasa Indonesia casual, singkat, dan spesifik."
        )
        return self._generate_text(prompt)

    def generate_weekly_report(
        self,
        user_name: str,
        financial_summary: str,
    ) -> str:
        """
        Generate weekly report narrative from pre-calculated summary.

        The summary is built by FinancialEngine, AI only writes the narrative.
        """
        prompt = (
            f"Kamu adalah Oliv, asisten keuangan personal untuk {user_name}.\n"
            f"Buat laporan mingguan berdasarkan DATA BERIKUT:\n\n"
            f"{financial_summary}\n\n"
            "Laporan harus:\n"
            f"1. Sapa {user_name} dengan hangat\n"
            "2. Ringkas kondisi minggu ini (pakai angka yang sudah ada)\n"
            "3. Highlight 1 kategori yang perlu perhatian\n"
            "4. 1-2 saran actionable\n"
            "5. Motivasi penutup\n\n"
            "Bahasa Indonesia casual, emoji secukupnya, format Markdown. Maks 250 kata."
        )
        return self._generate_text(prompt)

    def suggest_clarification(
        self,
        ambiguous_text: str,
        partial_parse: dict | None = None,
    ) -> str:
        """
        Generate a clarification question for ambiguous input.

        Called by DecisionEngine when confidence is below threshold.
        """
        context = ""
        if partial_parse:
            context = (
                f"Aku menangkap: {partial_parse.get('memo', '?')} "
                f"Rp {partial_parse.get('jumlah', '?')}, "
                f"kategori {partial_parse.get('kategori', '?')}.\n"
            )
        prompt = (
            f"User menulis: \"{ambiguous_text}\"\n"
            f"{context}"
            "Buat SATU pertanyaan klarifikasi singkat untuk memastikan parsing yang benar.\n"
            "Fokus pada apa yang paling tidak jelas (jumlah? kategori? akun?).\n"
            "Bahasa Indonesia, casual, maks 30 kata."
        )
        try:
            return self._generate_text(prompt)
        except Exception:
            return "Bisa dijelaskan lebih detail? Jumlah dan kategorinya apa ya? 🤔"

    # ---------------------------------------------------------------- #
    # INTERNAL: model calls                                              #
    # ---------------------------------------------------------------- #

    def _generate_text(self, prompt: str) -> str:
        """Call text models with fallback; only classify all-429 failures as quota exhaustion."""
        client = self._get_client()
        failures = []
        for model in TEXT_MODELS:
            try:
                result = client.models.generate_content(model=model, contents=prompt).text
                if not result:
                    raise RuntimeError(f"Gemini returned an empty text response from {model}.")
                logger.info(f"Text model used: {model}")
                return result
            except genai_errors.ClientError as e:
                err = str(e)
                failures.append((model, err))
                if "429" in err:
                    delay = _parse_retry_delay(err)
                    logger.warning(f"Gemini rate/quota limit on {model}, retry_delay={delay}s; trying fallback.")
                    continue
                if "404" in err:
                    logger.error(f"Gemini model unavailable for this project: {model}; response={err}")
                    continue
                logger.exception(f"Gemini text request rejected by {model}: {err}")
                raise
            except Exception as e:
                logger.exception(f"Gemini text error on {model}: {e}")
                raise

        if failures and all("429" in err for _, err in failures):
            raise QuotaExhaustedError(
                "Semua model Gemini mengembalikan HTTP 429 (rate limit/kuota). "
                + " | ".join(f"{model}: {err}" for model, err in failures)
            )
        details = " | ".join(f"{model}: {err}" for model, err in failures)
        raise RuntimeError(
            "Semua model Gemini gagal; kegagalan bukan semata-mata kuota. "
            f"Periksa model/project/API access. Detail: {details}"
        )

    def _generate_vision(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:
        """Call vision models with fallback; distinguish missing models from rate limits."""
        client = self._get_client()
        parts = [
            genai_types.Part(
                inline_data=genai_types.Blob(mime_type=mime_type, data=image_bytes)
            ),
            genai_types.Part(text=prompt),
        ]
        failures = []
        for model in VISION_MODELS:
            try:
                result = client.models.generate_content(model=model, contents=parts).text
                if not result:
                    raise RuntimeError(f"Gemini returned an empty vision response from {model}.")
                logger.info(f"Vision model used: {model}")
                return result
            except genai_errors.ClientError as e:
                err = str(e)
                failures.append((model, err))
                if "429" in err:
                    delay = _parse_retry_delay(err)
                    logger.warning(f"Gemini vision rate/quota limit on {model}, retry_delay={delay}s; trying fallback.")
                    continue
                if "404" in err:
                    logger.error(f"Gemini vision model unavailable for this project: {model}; response={err}")
                    continue
                logger.exception(f"Gemini vision request rejected by {model}: {err}")
                raise
            except Exception as e:
                logger.exception(f"Gemini vision error on {model}: {e}")
                raise

        if failures and all("429" in err for _, err in failures):
            raise QuotaExhaustedError(
                "Semua model vision Gemini mengembalikan HTTP 429 (rate limit/kuota). "
                + " | ".join(f"{model}: {err}" for model, err in failures)
            )
        details = " | ".join(f"{model}: {err}" for model, err in failures)
        raise RuntimeError(
            "Semua model vision Gemini gagal; kegagalan bukan semata-mata kuota. "
            f"Periksa model/project/API access. Detail: {details}"
        )

    @staticmethod
    def _strip_json(raw: str) -> str:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        return raw

    async def parse_transaction_async(self, text: str, user_context_hint: str = "") -> ParsedTransaction | None:
        """Async wrapper — runs blocking parse in executor to not block event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.parse_transaction, text, user_context_hint)

    async def parse_receipt_photo_async(self, image_bytes: bytes, mime_type: str) -> ParsedTransaction | None:
        """Async wrapper for receipt parsing."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.parse_receipt_photo, image_bytes, mime_type)

    def transcribe_voice(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
        """Transcribe a Telegram voice note with Gemini audio understanding."""
        prompt = (
            "Transkripsikan audio bahasa Indonesia ini secara akurat. "
            "Pertahankan angka, nominal uang, nama merchant, nama akun pembayaran, "
            "dan kata-kata seperti pengeluaran, pemasukan, transfer. "
            "Kembalikan hanya teks transkripsi, tanpa penjelasan. "
            "Jika audio tidak dapat dipahami, kembalikan string kosong."
        )
        client = self._get_client()
        parts = [
            genai_types.Part(
                inline_data=genai_types.Blob(mime_type=mime_type, data=audio_bytes)
            ),
            genai_types.Part(text=prompt),
        ]
        failures = []
        for model in TEXT_MODELS:
            try:
                response = client.models.generate_content(model=model, contents=parts)
                transcript = (response.text or "").strip()
                if transcript:
                    logger.info("Voice transcription model used: %s", model)
                    return transcript
                return ""
            except genai_errors.ClientError as e:
                err = str(e)
                failures.append((model, err))
                if "404" in err or "429" in err:
                    logger.warning("Voice model %s unavailable/rate-limited; trying fallback.", model)
                    continue
                raise
        if failures and all("429" in err for _, err in failures):
            raise QuotaExhaustedError("Gemini voice transcription quota/rate limit reached.")
        raise RuntimeError("Gemini voice transcription failed: " + " | ".join(f"{m}: {e}" for m, e in failures))

    async def transcribe_voice_async(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
        """Async wrapper for voice transcription."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.transcribe_voice, audio_bytes, mime_type)

    async def generate_insight_async(self, user_name: str, financial_summary: str, request_type: str = "analisa") -> str:
        """Async wrapper for insight generation."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate_insight, user_name, financial_summary, request_type)

    async def answer_question_async(self, question: str, user_name: str, financial_summary: str, memory_context: str = "") -> str:
        """Async wrapper for Q&A."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.answer_question, question, user_name, financial_summary, memory_context)

    async def generate_weekly_report_async(self, user_name: str, financial_summary: str) -> str:
        """Async wrapper for weekly report."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate_weekly_report, user_name, financial_summary)

    def extract_memory(self, prompt: str) -> str:
        """
        Run a memory extraction prompt and return the raw response.

        The prompt is fully built by MemoryExtractor — this method
        just calls the text model and returns raw output.
        Uses the fastest available model (lite first).
        """
        return self._generate_text(prompt)

    async def extract_memory_async(self, prompt: str) -> str:
        """Async wrapper for memory extraction."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.extract_memory, prompt)


def _parse_retry_delay(error_str: str) -> float | None:
    """Extract retry delay from Gemini error message."""
    m = re.search(r"retry[_ ](?:in|delay)['\"]?\s*[:\s]+['\"]?(\d+(?:\.\d+)?)", error_str, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)s", error_str)
    return float(m.group(1)) if m else None
