import json
from pathlib import Path

from core.image_production_log import ImageProductionTimeline


def test_timeline_writes_ordered_jsonl_and_redacts_secrets(tmp_path: Path):
    output = tmp_path / "image_production_timeline.jsonl"
    timeline = ImageProductionTimeline(output)

    timeline.record(
        "trace-a",
        "prompt.base",
        status="completed",
        prompt="portrait by the window",
        api_key="secret-value",
    )
    timeline.record(
        "trace-a",
        "provider.completed",
        status="success",
        duration_ms=321,
        authorization="Bearer secret-token",
    )

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [record["sequence"] for record in records] == [1, 2]
    assert [record["stage"] for record in records] == ["prompt.base", "provider.completed"]
    assert records[0]["prompt"] == "portrait by the window"
    assert records[0]["api_key"] == "***"
    assert records[1]["authorization"] == "***"
    assert records[1]["duration_ms"] == 321
    assert records[0]["timestamp"] <= records[1]["timestamp"]


def test_timeline_keeps_independent_sequence_per_trace(tmp_path: Path):
    timeline = ImageProductionTimeline(tmp_path / "timeline.jsonl")

    timeline.record("trace-a", "candidate.created")
    timeline.record("trace-b", "candidate.created")
    timeline.record("trace-a", "prompt.final")

    records = [json.loads(line) for line in timeline.path.read_text(encoding="utf-8").splitlines()]
    assert [(record["trace_id"], record["sequence"]) for record in records] == [
        ("trace-a", 1),
        ("trace-b", 1),
        ("trace-a", 2),
    ]
