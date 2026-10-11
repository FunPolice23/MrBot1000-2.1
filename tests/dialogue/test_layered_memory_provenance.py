from datetime import datetime

from agents.knowledge.layered_memory import LayeredMemoryRetriever, MemoryLayer


class _Database:
    def get_memories(self, limit=20):
        return [
            {
                "id": 1,
                "category": "archive",
                "title": "Old lesson",
                "content": "Do not reuse",
                "importance": 0.9,
                "confidence": 0.9,
                "source": "outcome:op-1",
                "timestamp": datetime.now().isoformat(),
                "provenance": "verified_payment:ev-1",
                "verification_level": "L3",
                "related_ids": ["op-1", "run-1"],
                "quarantined": False,
            },
            {
                "id": 2,
                "category": "lesson",
                "title": "Contradicted lesson",
                "content": "Unsafe",
                "importance": 1.0,
                "confidence": 1.0,
                "source": "outcome:op-2",
                "timestamp": datetime.now().isoformat(),
                "quarantined": True,
            },
        ]


def test_retrieval_preserves_provenance_and_excludes_quarantine():
    entries = LayeredMemoryRetriever(_Database()).retrieve()

    assert len(entries) == 1
    assert entries[0].layer is MemoryLayer.ARCHIVE
    assert entries[0].provenance == "verified_payment:ev-1"
    assert entries[0].verification_level == "L3"
    assert entries[0].related_ids == ("op-1", "run-1")
