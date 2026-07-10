"""
Memory Retriever — smart, query-aware memory retrieval.

PRINCIPLE: Never send all memories to AI.
           Only send what is needed for the current request.

The retriever maps message types to relevant memory categories,
then filters further by keyword matching against the query text.

Used by ContextBuilder to build the memory_summary field of UserContext.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from memory.models import MemoryCategory

if TYPE_CHECKING:
    from memory.engine import MemoryEngine
    from brain.router import MessageType

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# CATEGORY MAPS per message type                                       #
# ------------------------------------------------------------------ #

# What categories matter for each type of request.
# Ordered by relevance (first = most important).
_CATEGORY_MAP: dict[str, list[MemoryCategory]] = {
    "Transaction": [
        MemoryCategory.PREFERENCE,    # preferred payment method, accounts
        MemoryCategory.BEHAVIOUR,     # typical spend patterns
        MemoryCategory.HABIT,         # recurring habits (coffee, etc.)
    ],
    "Transfer": [
        MemoryCategory.PREFERENCE,    # preferred accounts
        MemoryCategory.IDENTITY,      # account ownership
    ],
    "Question": [
        MemoryCategory.IDENTITY,
        MemoryCategory.FINANCIAL_GOALS,
        MemoryCategory.BEHAVIOUR,
        MemoryCategory.LONG_TERM_CONTEXT,
    ],
    "Financial Analysis": [
        MemoryCategory.IDENTITY,
        MemoryCategory.FINANCIAL_GOALS,
        MemoryCategory.BEHAVIOUR,
        MemoryCategory.HABIT,
        MemoryCategory.LONG_TERM_CONTEXT,
        MemoryCategory.PREFERENCE,
    ],
    "Budget": [
        MemoryCategory.FINANCIAL_GOALS,
        MemoryCategory.BEHAVIOUR,
        MemoryCategory.LONG_TERM_CONTEXT,
    ],
    "Goal": [
        MemoryCategory.FINANCIAL_GOALS,
        MemoryCategory.LONG_TERM_CONTEXT,
        MemoryCategory.IDENTITY,
        MemoryCategory.HABIT,
    ],
    "Report": [
        MemoryCategory.IDENTITY,
        MemoryCategory.BEHAVIOUR,
    ],
    "Memory Update": [
        MemoryCategory.IDENTITY,
        MemoryCategory.PREFERENCE,
        MemoryCategory.HABIT,
        MemoryCategory.FINANCIAL_GOALS,
        MemoryCategory.LONG_TERM_CONTEXT,
        MemoryCategory.BEHAVIOUR,
    ],
    "Small Talk": [],   # no memory needed for small talk
    "Unknown": [
        MemoryCategory.IDENTITY,
        MemoryCategory.PREFERENCE,
    ],
}

# Default when message_type is not recognized
_DEFAULT_CATEGORIES = [MemoryCategory.IDENTITY, MemoryCategory.PREFERENCE]

# Max items to return per request type
_MAX_ITEMS: dict[str, int] = {
    "Transaction":        4,
    "Transfer":           3,
    "Question":           8,
    "Financial Analysis": 10,
    "Budget":             5,
    "Goal":               6,
    "Report":             4,
    "Memory Update":      4,
    "Small Talk":         0,
    "Unknown":            4,
}


class MemoryRetriever:
    """
    Retrieves only the memories relevant to the current request.

    Usage:
        retriever = MemoryRetriever(memory_engine)
        text = retriever.retrieve_as_text(
            user_id="12345",
            message_type_str="Transaction",
            query="beli kopi di kopi kenangan",
        )
    """

    def __init__(self, memory_engine: "MemoryEngine"):
        self._engine = memory_engine

    def retrieve_as_text(
        self,
        user_id: str,
        message_type_str: str,
        query: str = "",
    ) -> str:
        """
        Main entry point — returns compact text for AI context injection.

        Returns empty string if no relevant memories, or for small talk.
        Token budget target: < 200 tokens.
        """
        if message_type_str == "Small Talk":
            return ""

        categories = _CATEGORY_MAP.get(message_type_str, _DEFAULT_CATEGORIES)
        if not categories:
            return ""

        max_items = _MAX_ITEMS.get(message_type_str, 5)

        return self._engine.get_context_for_query(
            user_id=user_id,
            query=query,
            categories=categories,
            max_items=max_items,
        )

    def retrieve_items(
        self,
        user_id: str,
        message_type_str: str,
        query: str = "",
    ):
        """
        Same as retrieve_as_text but returns MemoryItem objects.
        Useful for Brain logic that needs to inspect individual facts.
        """
        categories = _CATEGORY_MAP.get(message_type_str, _DEFAULT_CATEGORIES)
        max_items = _MAX_ITEMS.get(message_type_str, 5)

        if not categories:
            return []

        return self._engine.get_for_query(
            user_id=user_id,
            query=query,
            categories=categories,
            limit=max_items,
        )

    def retrieve_identity(self, user_id: str) -> dict[str, str]:
        """
        Return identity facts as a flat dict.
        Used to personalise responses without an AI call.
        """
        items = self._engine.get_by_category(user_id, MemoryCategory.IDENTITY)
        return {item.key: item.value for item in items}

    def retrieve_active_goals(self, user_id: str) -> list[dict]:
        """Return active financial goals as list of dicts."""
        items = self._engine.get_by_category(user_id, MemoryCategory.FINANCIAL_GOALS)
        return [{"key": item.key, "value": item.value, "importance": item.importance}
                for item in items]
