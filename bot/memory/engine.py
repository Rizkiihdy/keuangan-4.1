"""
Memory Engine V3 — core operations on long-term user facts.

This is the main API for all memory operations.
It is storage-agnostic: pass any MemoryStore implementation.

Public API:
    create()            — create new fact (raises on duplicate key in same category)
    merge()             — smart upsert (preferred write method — no duplicates)
    update()            — update value of an existing fact by ID
    archive()           — soft-delete a fact by ID
    search()            — full-text search across key + value
    get_by_category()   — all facts in one category
    get_relevant()      — top facts for AI context, sorted by composite score
    get_for_query()     — query-aware retrieval (used by MemoryRetriever)
    recalculate_scores()— recompute importance based on access frequency
    get_context_summary()— compact text for AI context injection
    get_all_count()     — count of active facts
    list_all()          — all non-archived facts (for /ingatan command)
"""

from __future__ import annotations

import logging
from typing import Optional

from memory.models import (
    MemoryItem, MemoryCategory, ExtractedFact,
    guard_sensitive, _now_iso,
)
from memory.store import MemoryStore, JsonMemoryStore

logger = logging.getLogger(__name__)


class MemoryEngine:
    """
    Core memory operations.

    Usage:
        store = JsonMemoryStore("/path/to/memory_store.json")
        mem = MemoryEngine(store)

        # Write
        mem.merge(user_id, MemoryCategory.IDENTITY, "nama", "Zee")

        # Read
        items = mem.get_by_category(user_id, MemoryCategory.IDENTITY)

        # Context for AI
        ctx = mem.get_context_summary(user_id)
    """

    def __init__(self, store: Optional[MemoryStore] = None):
        """
        Args:
            store: MemoryStore implementation. Defaults to JsonMemoryStore
                   at the standard path (bot/memory_store.json).
        """
        self._store = store or JsonMemoryStore()

    # ---------------------------------------------------------------- #
    # WRITES                                                             #
    # ---------------------------------------------------------------- #

    def create(
        self,
        user_id: str,
        category: MemoryCategory,
        key: str,
        value: str,
        source: str = "system",
        confidence: float = 0.8,
        importance: float = 0.5,
        tags: Optional[list[str]] = None,
    ) -> MemoryItem:
        """
        Create a new memory item.

        Raises ValueError if:
          - key or value contains sensitive terms
          - an active item with the same category+key already exists
            (use merge() to upsert without caring about duplicates)
        """
        guard_sensitive(key, value)
        existing = self._find_by_key(user_id, category, key)
        if existing:
            raise ValueError(
                f"Memory {category.value}/{key} sudah ada (id={existing.id}). "
                "Gunakan merge() untuk update."
            )

        item = MemoryItem.new(
            category=category,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            importance=importance,
            tags=tags or [],
        )
        items = self._store.read(user_id)
        items.append(item.to_dict())
        self._store.write(user_id, items)
        logger.info(f"Memory created: [{user_id}] {category.value}/{key} = '{value[:40]}'")
        return item

    def merge(
        self,
        user_id: str,
        category: MemoryCategory,
        key: str,
        value: str,
        source: str = "system",
        confidence: float = 0.8,
        importance: float = 0.5,
        tags: Optional[list[str]] = None,
    ) -> tuple[MemoryItem, bool]:
        """
        Smart upsert — preferred write method.

        Creates a new fact if key doesn't exist, or updates the value
        if it already exists. Never creates duplicates.

        Returns:
            (item, was_created) — was_created=True if new, False if updated
        """
        guard_sensitive(key, value)
        existing = self._find_by_key(user_id, category, key)

        if existing:
            updated = self._do_update(
                user_id=user_id,
                item_id=existing.id,
                new_value=value,
                confidence=confidence,
                importance=importance,
                source=source,
            )
            return updated or existing, False

        item = self._do_create(
            user_id=user_id,
            category=category,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            importance=importance,
            tags=tags or [],
        )
        return item, True

    def update(
        self,
        user_id: str,
        item_id: str,
        new_value: str,
        confidence: Optional[float] = None,
        importance: Optional[float] = None,
        source: Optional[str] = None,
    ) -> Optional[MemoryItem]:
        """Update value of an existing memory item by ID."""
        guard_sensitive("value", new_value)
        return self._do_update(user_id, item_id, new_value, confidence, importance, source)

    def archive(self, user_id: str, item_id: str) -> bool:
        """
        Soft-delete a memory item.
        Archived items are hidden from all reads but kept in storage.
        """
        items = self._store.read(user_id)
        for m in items:
            if m.get("id") == item_id and not m.get("archived"):
                m["archived"] = True
                m["updated_at"] = _now_iso()
                self._store.write(user_id, items)
                logger.info(f"Memory archived: [{user_id}] {item_id}")
                return True
        return False

    def apply_facts(
        self,
        user_id: str,
        facts: list[ExtractedFact],
    ) -> tuple[int, int]:
        """
        Apply a list of ExtractedFacts from MemoryExtractor.

        Uses merge() for each fact — no duplicates guaranteed.

        Returns:
            (created, updated) counts
        """
        created = updated = 0
        for fact in facts:
            try:
                _, was_new = self.merge(
                    user_id=user_id,
                    category=fact.category,
                    key=fact.key,
                    value=fact.value,
                    source=fact.source,
                    confidence=fact.confidence,
                    importance=fact.importance_hint(),
                    tags=fact.tags,
                )
                if was_new:
                    created += 1
                else:
                    updated += 1
            except ValueError as e:
                logger.warning(f"Fact rejected: {e}")
        return created, updated

    # ---------------------------------------------------------------- #
    # READS                                                              #
    # ---------------------------------------------------------------- #

    def search(
        self,
        user_id: str,
        query: str,
        category: Optional[MemoryCategory] = None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        """
        Full-text search across key and value fields.
        Returns non-archived items sorted by composite score.
        """
        q = query.lower().strip()
        results = []
        for m in self._store.read(user_id):
            if m.get("archived"):
                continue
            if category and m.get("category") != category.value:
                continue
            if q in m.get("key", "").lower() or q in m.get("value", "").lower():
                results.append(MemoryItem.from_dict(m))

        results.sort(key=lambda x: -self._composite_score(x))
        return results[:limit]

    def get_by_category(
        self,
        user_id: str,
        category: MemoryCategory,
    ) -> list[MemoryItem]:
        """Return all non-archived items in a category, sorted by composite score."""
        items = [
            MemoryItem.from_dict(m)
            for m in self._store.read(user_id)
            if m.get("category") == category.value and not m.get("archived")
        ]
        items.sort(key=lambda x: -self._composite_score(x))
        return items

    def get_relevant(
        self,
        user_id: str,
        limit: int = 10,
        min_importance: float = 0.3,
    ) -> list[MemoryItem]:
        """
        Top relevant memories for AI context.
        Sorted by composite score (importance × confidence × recency).
        Increments access_count for returned items.
        """
        raw = self._store.read(user_id)
        eligible = [
            MemoryItem.from_dict(m)
            for m in raw
            if not m.get("archived") and m.get("importance", 0) >= min_importance
        ]
        eligible.sort(key=lambda x: -self._composite_score(x))
        top = eligible[:limit]

        # Increment access counts
        if top:
            returned_ids = {item.id for item in top}
            now = _now_iso()
            for m in raw:
                if m.get("id") in returned_ids:
                    m["access_count"] = m.get("access_count", 0) + 1
                    m["last_accessed"] = now
            self._store.write(user_id, raw)

        return top

    def get_for_query(
        self,
        user_id: str,
        query: str,
        categories: list[MemoryCategory],
        limit: int = 8,
    ) -> list[MemoryItem]:
        """
        Query-aware retrieval: only fetches from relevant categories,
        with optional keyword matching.

        Used by MemoryRetriever to build focused context.
        """
        raw = self._store.read(user_id)
        cat_values = {c.value for c in categories}
        q = query.lower().strip()

        items = []
        for m in raw:
            if m.get("archived"):
                continue
            if m.get("category") not in cat_values:
                continue
            items.append(MemoryItem.from_dict(m))

        # Boost items whose key/value matches the query
        def _score(item: MemoryItem) -> float:
            base = self._composite_score(item)
            if q and (q in item.key or q in item.value.lower()):
                base *= 1.3
            return base

        items.sort(key=lambda x: -_score(x))
        # Increment access counts
        if items[:limit]:
            returned_ids = {item.id for item in items[:limit]}
            now = _now_iso()
            raw_list = self._store.read(user_id)
            for m in raw_list:
                if m.get("id") in returned_ids:
                    m["access_count"] = m.get("access_count", 0) + 1
                    m["last_accessed"] = now
            self._store.write(user_id, raw_list)

        return items[:limit]

    def list_all(
        self,
        user_id: str,
        include_archived: bool = False,
    ) -> dict[str, list[MemoryItem]]:
        """
        Return all facts grouped by category.
        Used by /ingatan command.
        """
        result: dict[str, list[MemoryItem]] = {}
        for m in self._store.read(user_id):
            if not include_archived and m.get("archived"):
                continue
            cat = m.get("category", "unknown")
            item = MemoryItem.from_dict(m)
            result.setdefault(cat, []).append(item)
        # Sort each group by composite score
        for cat in result:
            result[cat].sort(key=lambda x: -self._composite_score(x))
        return result

    def get_all_count(self, user_id: str) -> int:
        """Count of non-archived memories."""
        return sum(1 for m in self._store.read(user_id) if not m.get("archived"))

    # ---------------------------------------------------------------- #
    # SCORING                                                            #
    # ---------------------------------------------------------------- #

    def recalculate_scores(self, user_id: str) -> None:
        """
        Recalculate importance scores based on access frequency + confidence.

        Should be called periodically (e.g. weekly).
        Formula:
            importance = 0.4 × (access_count / max_access) + 0.6 × confidence
            Minimum floor for IDENTITY and FINANCIAL_GOALS: 0.7
        """
        raw = self._store.read(user_id)
        active = [m for m in raw if not m.get("archived")]
        if not active:
            return

        max_access = max((m.get("access_count", 0) for m in active), default=1) or 1

        HIGH_IMPORTANCE_CATS = {
            MemoryCategory.IDENTITY.value,
            MemoryCategory.FINANCIAL_GOALS.value,
            MemoryCategory.LONG_TERM_CONTEXT.value,
        }

        for m in raw:
            if m.get("archived"):
                continue
            access_score = m.get("access_count", 0) / max_access
            conf = m.get("confidence", 0.5)
            new_imp = min(1.0, (access_score * 0.4) + (conf * 0.6))
            # Floor for high-importance categories
            if m.get("category") in HIGH_IMPORTANCE_CATS:
                new_imp = max(new_imp, 0.7)
            m["importance"] = round(new_imp, 3)

        self._store.write(user_id, raw)

    # ---------------------------------------------------------------- #
    # CONTEXT GENERATION                                                 #
    # ---------------------------------------------------------------- #

    def get_context_summary(
        self,
        user_id: str,
        max_items: int = 8,
        min_importance: float = 0.5,
    ) -> str:
        """
        Compact text summary of top memories for AI context injection.
        Only high-importance facts — keeps context tight.
        """
        items = self.get_relevant(user_id, limit=max_items, min_importance=min_importance)
        if not items:
            return ""
        lines = ["[Ingatan Oliv tentang kamu]"]
        for item in items:
            lines.append(f"  • {item.as_context_line()}")
        return "\n".join(lines)

    def get_context_for_query(
        self,
        user_id: str,
        query: str,
        categories: list[MemoryCategory],
        max_items: int = 6,
    ) -> str:
        """
        Query-aware context: only sends memories relevant to the current request.
        Smaller than get_context_summary() by design.
        """
        items = self.get_for_query(user_id, query, categories, limit=max_items)
        if not items:
            return ""
        lines = ["[Konteks personal]"]
        for item in items:
            lines.append(f"  • {item.as_context_line()}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- #
    # PRIVATE HELPERS                                                    #
    # ---------------------------------------------------------------- #

    def _find_by_key(
        self,
        user_id: str,
        category: MemoryCategory,
        key: str,
    ) -> Optional[MemoryItem]:
        key_lower = key.lower().strip()
        for m in self._store.read(user_id):
            if (
                m.get("category") == category.value
                and m.get("key") == key_lower
                and not m.get("archived")
            ):
                return MemoryItem.from_dict(m)
        return None

    def _do_create(
        self,
        user_id: str,
        category: MemoryCategory,
        key: str,
        value: str,
        source: str,
        confidence: float,
        importance: float,
        tags: list,
    ) -> MemoryItem:
        item = MemoryItem.new(
            category=category,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            importance=importance,
            tags=tags,
        )
        items = self._store.read(user_id)
        items.append(item.to_dict())
        self._store.write(user_id, items)
        logger.info(f"Memory.create [{user_id}] {category.value}/{key} = '{value[:40]}'")
        return item

    def _do_update(
        self,
        user_id: str,
        item_id: str,
        new_value: str,
        confidence: Optional[float],
        importance: Optional[float],
        source: Optional[str],
    ) -> Optional[MemoryItem]:
        items = self._store.read(user_id)
        for m in items:
            if m.get("id") == item_id and not m.get("archived"):
                m["value"] = new_value.strip()
                m["updated_at"] = _now_iso()
                m["version"] = m.get("version", 1) + 1
                if confidence is not None:
                    m["confidence"] = max(0.0, min(1.0, confidence))
                if importance is not None:
                    m["importance"] = max(0.0, min(1.0, importance))
                if source is not None:
                    m["source"] = source
                self._store.write(user_id, items)
                logger.info(f"Memory.update [{user_id}] {item_id} = '{new_value[:40]}'")
                return MemoryItem.from_dict(m)
        return None

    @staticmethod
    def _composite_score(item: MemoryItem) -> float:
        """
        Composite relevance score for sorting.
        Blends importance (base), confidence, and access frequency.
        """
        freq = min(1.0, item.access_count / 10.0)  # normalise to [0,1]
        return item.importance * 0.5 + item.confidence * 0.35 + freq * 0.15
