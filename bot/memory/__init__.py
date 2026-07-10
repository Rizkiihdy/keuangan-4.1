"""
Oliv Memory Engine V3

Exports the main public API so callers can simply:
    from memory import MemoryEngine, MemoryCategory, MemoryRetriever, ReflectionEngine

Storage is injection-based:
    from memory import MemoryEngine, JsonMemoryStore
    engine = MemoryEngine(store=JsonMemoryStore("/path/to/memory_store.json"))
"""

from memory.models import (
    MemoryCategory,
    MemoryItem,
    ExtractedFact,
    ReflectionResult,
    guard_sensitive,
)
from memory.store import MemoryStore, JsonMemoryStore
from memory.engine import MemoryEngine
from memory.retriever import MemoryRetriever
from memory.extractor import MemoryExtractor
from memory.reflection import ReflectionEngine, BehaviourAnalyser

__all__ = [
    # Models
    "MemoryCategory",
    "MemoryItem",
    "ExtractedFact",
    "ReflectionResult",
    "guard_sensitive",
    # Storage
    "MemoryStore",
    "JsonMemoryStore",
    # Engine
    "MemoryEngine",
    # Retrieval
    "MemoryRetriever",
    # AI extraction
    "MemoryExtractor",
    # Reflection
    "ReflectionEngine",
    "BehaviourAnalyser",
]
