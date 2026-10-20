import json
from collections import Counter

import pytest

from app.coach import ungrounded_numbers
from app.rules import build_report
from training import build_dataset, label
from training.scenarios import ARCHETYPES, generate


def test_scenarios_are_reproducible():
    a, b = generate(42), generate(42)
    assert a.today == b.today
    assert [s.model_dump() for s in a.sessions] == [s.model_dump() for s in b.sessions]


def test_archetypes_produce_their_signal():
    by_type = {a: Counter() for a in ARCHETYPES}
    for seed in range(200):
        sc = generate(seed)
        st = sc.stats()
        c = by_type[sc.archetype]
        c["n"] += 1
        c["records"] += bool(st.personal_records)
        c["stalled"] += bool(st.stalled_lifts)
        c["trained"] += st.has_training
    assert by_type["new_user"]["trained"] == 0
    assert by_type["record_week"]["records"] >= 0.8 * by_type["record_week"]["n"]
    assert by_type["stalled_lift"]["stalled"] >= 0.8 * by_type["stalled_lift"]["n"]
    assert by_type["volume_drop"]["records"] <= 0.2 * by_type["volume_drop"]["n"]


@pytest.mark.parametrize("seed", range(0, 60, 7))
def test_rule_drafts_are_always_grounded(seed):
    for lang in ("en", "tr"):
        stats = generate(seed).stats()
        assert ungrounded_numbers(build_report(stats, lang), stats) == []


@pytest.fixture
def labels_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(label, "LABELS", tmp_path)
    monkeypatch.setattr(build_dataset, "LABELS", tmp_path)
    monkeypatch.setattr(build_dataset, "OUT", tmp_path / "data")
    return tmp_path


def test_rendered_draft_round_trips(labels_dir):
    label.cmd_new(3)
    for path in labels_dir.glob("*.md"):
        status, problems = label.validate(path)
        assert status == "draft"
        assert problems == []


def test_check_catches_invented_numbers(labels_dir):
    label.cmd_new(1)
    [path] = labels_dir.glob("*.md")
    text = path.read_text().replace("## headline\n", "## headline\nVolume up 987%. ")
    path.write_text(text)
    _, problems = label.validate(path)
    assert any("987" in p for p in problems)


def test_only_done_labels_reach_the_dataset(labels_dir):
    label.cmd_new(4)
    paths = sorted(labels_dir.glob("*.md"))
    paths[0].write_text(paths[0].read_text().replace("status: draft", "status: done"))
    counts = build_dataset.build(rule_examples=5)
    assert sum(counts.values()) == 6
    rows = [
        json.loads(line)
        for name in ("train", "valid", "test")
        for line in (labels_dir / "data" / f"{name}.jsonl").read_text().splitlines()
    ]
    for row in rows:
        roles = [m["role"] for m in row["messages"]]
        assert roles == ["system", "user", "assistant"]
        json.loads(row["messages"][2]["content"])  # the target is valid JSON


def test_splits_never_share_a_seed():
    assert build_dataset.split_for(10) == "test"
    assert build_dataset.split_for(21) == "valid"
    assert build_dataset.split_for(32) == "train"
