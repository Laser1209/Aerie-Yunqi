from __future__ import annotations

import pytest

from memory.layers.long_permanent import LongTermMemoryLayer
from memory.layers.base import MemoryType


class _Collection:
    def __init__(self) -> None:
        self.where = None

    def query(self, **kwargs):
        self.where = kwargs["where"]
        return {"ids": [[]], "distances": [[]], "documents": [[]]}


@pytest.mark.asyncio
async def test_chroma_filters_use_single_top_level_operator_for_persona_scope():
    collection = _Collection()
    layer = LongTermMemoryLayer.__new__(LongTermMemoryLayer)
    layer.db = None
    layer.embedding_fn = lambda _text: [0.1, 0.2]
    layer._collection = collection
    layer._chroma_available = True

    await layer.retrieve(
        user_id=10001,
        query="链路验收",
        memory_type=MemoryType.FACT,
        persona_id="aerie_default",
    )

    assert collection.where == {
        "$and": [
            {"user_id": 10001},
            {"memory_type": "fact"},
            {"$or": [{"persona_id": "aerie_default"}, {"persona_id": ""}]},
        ]
    }
