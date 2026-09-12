from datetime import datetime, timedelta

from agents.layered_memory import LayeredMemoryRetriever, MemoryLayer
from agents.program_knowledge import MemoryDatabase


def test_retrieval_classifies_layers_and_filters_expired_entries(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    database.add_memory("fact", "Current rule", "Use the official source", importance=0.9,
                        source="verified", expires_days=2)
    database.add_memory("lesson", "Old lesson", "Do not repeat stale research", importance=1.0,
                        source="learning", expires_days=1)
    database.add_memory("conversation", "Recent exchange", "Discussed a listing", importance=0.5)

    retriever = LayeredMemoryRetriever(database)
    semantic = retriever.retrieve(layers=[MemoryLayer.SEMANTIC])
    assert [entry.title for entry in semantic] == ["Current rule"]
    assert retriever.retrieve(layers=[MemoryLayer.POLICY], now=(datetime.now() + timedelta(days=2)).timestamp()) == []


def test_retrieval_respects_confidence_and_unknown_categories(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    database.add_memory("custom", "Unverified", "Maybe true", importance=0.2)
    database.add_memory("knowledge", "Strong fact", "Known", importance=0.9)

    retriever = LayeredMemoryRetriever(database)
    results = retriever.retrieve(min_confidence=0.8)
    assert [entry.title for entry in results] == ["Strong fact"]
    assert results[0].layer is MemoryLayer.SEMANTIC


def test_retrieval_can_reject_non_expiring_stale_memory(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    database.add_memory("fact", "Old fact", "Needs reconfirmation", importance=1.0)
    retriever = LayeredMemoryRetriever(database)
    assert retriever.retrieve(max_age_seconds=0, now=(datetime.now() + timedelta(seconds=1)).timestamp()) == []