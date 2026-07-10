"""
Memory Models — data structures for Oliv Memory Engine V3.

These are pure data objects with no I/O. All persistence
is handled by MemoryStore (store.py), not here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ------------------------------------------------------------------ #
# CATEGORIES (6 — matching product spec)                              #
# ------------------------------------------------------------------ #

class MemoryCategory(str, Enum):
    """
    Six categories of long-term user facts.

    identity          → who the user is
    financial_goals   → what the user wants to achieve financially
    preference        → how the user prefers to do things
    behaviour         → how the user actually behaves (derived from patterns)
    habit             → recurring actions the user does deliberately
    long_term_context → overarching life situations that affect decisions
    """
    IDENTITY         = "identity"
    FINANCIAL_GOALS  = "financial_goals"
    PREFERENCE       = "preference"
    BEHAVIOUR        = "behaviour"
    HABIT            = "habit"
    LONG_TERM_CONTEXT = "long_term_context"


# ------------------------------------------------------------------ #
# SENSITIVE DATA GUARD                                                 #
# ------------------------------------------------------------------ #

_SENSITIVE_TERMS: frozenset[str] = frozenset({
    "password", "kata_sandi", "otp", "pin", "api_key", "api key",
    "credential", "credentials", "token", "secret", "private_key",
    "passphrase", "kunci", "sandi", "nomor kartu", "cvv", "expiry",
    "rekening lengkap", "no rek",
})


def guard_sensitive(key: str, value: str) -> None:
    """
    Raise ValueError if key or value contains sensitive terms.
    Called by MemoryEngine before any write.
    """
    combined = f"{key} {value}".lower()
    for term in _SENSITIVE_TERMS:
        if term in combined:
            raise ValueError(
                f"Memory tidak bisa menyimpan data sensitif. "
                f"Kata yang ditolak: '{term}'"
            )


# ------------------------------------------------------------------ #
# CORE MEMORY ITEM                                                     #
# ------------------------------------------------------------------ #

@dataclass
class MemoryItem:
    """
    One unit of long-term memory.

    Fields:
        id          — short UUID (8 chars) — unique identifier
        category    — MemoryCategory value (string)
        key         — normalized fact name  (e.g. "nama", "hari_gajian")
        value       — the fact value        (e.g. "Zee", "25")
        source      — how this was learned:
                       "user_explicit"     → user typed "ingat ya: ..."
                       "ai_extracted"      → AI noticed it in conversation
                       "behaviour_analysis"→ derived from transaction patterns
                       "system"            → set by code directly
        confidence  — 0.0–1.0 how sure we are this is accurate
        importance  — 0.0–1.0 recalculated dynamically
        version     — increments on each update (for audit)
        access_count— how many times this was retrieved (for scoring)
        last_accessed—ISO string of last retrieval
        created_at  — ISO string
        updated_at  — ISO string
        archived    — soft delete flag
        tags        — free-form semantic tags for search
    """
    id:            str
    category:      str
    key:           str
    value:         str
    source:        str   = "system"
    confidence:    float = 0.8
    importance:    float = 0.5
    version:       int   = 1
    access_count:  int   = 0
    last_accessed: str   = ""
    created_at:    str   = ""
    updated_at:    str   = ""
    archived:      bool  = False
    tags:          list  = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryItem":
        # Tolerate extra/missing keys gracefully
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    def as_context_line(self) -> str:
        """Compact single-line representation for AI context injection."""
        return f"{self.key}: {self.value}"

    def as_text(self) -> str:
        """Human-readable form with metadata."""
        return (
            f"[{self.category}] {self.key}: {self.value} "
            f"(conf={self.confidence:.0%}, v{self.version})"
        )

    @classmethod
    def new(
        cls,
        category: MemoryCategory,
        key: str,
        value: str,
        source: str = "system",
        confidence: float = 0.8,
        importance: float = 0.5,
        tags: Optional[list[str]] = None,
    ) -> "MemoryItem":
        """Factory — creates a new item with auto-generated id and timestamps."""
        now = _now_iso()
        return cls(
            id=_short_id(),
            category=category.value,
            key=key.lower().strip(),
            value=value.strip(),
            source=source,
            confidence=max(0.0, min(1.0, confidence)),
            importance=max(0.0, min(1.0, importance)),
            version=1,
            access_count=0,
            last_accessed="",
            created_at=now,
            updated_at=now,
            archived=False,
            tags=tags or [],
        )


# ------------------------------------------------------------------ #
# EXTRACTED FACT  (output of MemoryExtractor)                         #
# ------------------------------------------------------------------ #

@dataclass
class ExtractedFact:
    """
    A raw fact extracted from a conversation turn by AI.

    Not yet persisted — MemoryEngine.merge() decides whether to
    create new or update existing item.
    """
    category:   MemoryCategory
    key:        str
    value:      str
    confidence: float = 0.8
    source:     str   = "ai_extracted"
    tags:       list  = field(default_factory=list)

    def importance_hint(self) -> float:
        """Base importance based on category."""
        _IMPORTANCE = {
            MemoryCategory.IDENTITY:          0.9,
            MemoryCategory.FINANCIAL_GOALS:   0.85,
            MemoryCategory.LONG_TERM_CONTEXT: 0.8,
            MemoryCategory.HABIT:             0.7,
            MemoryCategory.PREFERENCE:        0.65,
            MemoryCategory.BEHAVIOUR:         0.5,
        }
        return _IMPORTANCE.get(self.category, 0.5)


# ------------------------------------------------------------------ #
# REFLECTION RESULT  (output of ReflectionEngine)                     #
# ------------------------------------------------------------------ #

@dataclass
class ReflectionResult:
    """
    Summary of what the Reflection Engine did after a conversation turn.
    """
    facts_added:    int = 0
    facts_updated:  int = 0
    facts_archived: int = 0
    errors:         list = field(default_factory=list)
    notes:          list = field(default_factory=list)   # debug/audit trail

    def summary(self) -> str:
        parts = []
        if self.facts_added:
            parts.append(f"+{self.facts_added} new")
        if self.facts_updated:
            parts.append(f"~{self.facts_updated} updated")
        if self.facts_archived:
            parts.append(f"-{self.facts_archived} archived")
        return ", ".join(parts) if parts else "no changes"


# ------------------------------------------------------------------ #
# HELPERS                                                              #
# ------------------------------------------------------------------ #

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_id() -> str:
    return str(uuid.uuid4())[:8]
