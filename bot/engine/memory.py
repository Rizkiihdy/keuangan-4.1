"""
engine/memory.py — BACKWARD COMPATIBILITY SHIM

The real Memory Engine now lives in the `memory/` package.
This module re-exports everything so existing imports still work:

    from engine.memory import MemoryEngine, MemoryCategory   ← still works

New code should import directly:
    from memory import MemoryEngine, MemoryCategory, MemoryRetriever, ...
"""

from memory.models import MemoryCategory, MemoryItem, ExtractedFact, ReflectionResult
from memory.store import MemoryStore, JsonMemoryStore
from memory.engine import MemoryEngine
from memory.retriever import MemoryRetriever
from memory.extractor import MemoryExtractor
from memory.reflection import ReflectionEngine, BehaviourAnalyser

__all__ = [
    "MemoryCategory",
    "MemoryItem",
    "ExtractedFact",
    "ReflectionResult",
    "MemoryStore",
    "JsonMemoryStore",
    "MemoryEngine",
    "MemoryRetriever",
    "MemoryExtractor",
    "ReflectionEngine",
    "BehaviourAnalyser",
]
