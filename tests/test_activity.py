"""
Paged activity reads: newest first across daily files, exact totals, action filter.
"""
import json

import pytest

activity = pytest.importorskip("app.services.activity")


@pytest.fixture()
def logs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(activity, "LOGS_DIR", tmp_path)
    entries = []
    for day in (1, 2, 3):
        with open(tmp_path / f"activity_2026090{day}.json", "w") as f:
            for i in range(10):
                e = {"timestamp": f"2026-09-0{day}T10:00:{i:02d}+00:00", "action": "a" if i % 3 else "b", "status": "success"}
                entries.append(e)
                f.write(json.dumps(e) + "\n")
    # blank line and a half-written final line are ignored, like before
    with open(tmp_path / "activity_20260903.json", "a") as f:
        f.write('\n{"timestamp": "2026-09-03T11:00:00+00:00", "action": "a", "sta')
    return sorted(entries, key=lambda e: e["timestamp"], reverse=True)


@pytest.mark.parametrize("offset,limit", [(0, 5), (8, 5), (25, 10), (40, 5), (0, 100)])
def test_pages_match_full_sorted_list(logs_dir, offset, limit):
    page, total = activity.read_activity_page(None, offset, limit)
    assert total == 30
    assert page == logs_dir[offset:offset + limit]


@pytest.mark.parametrize("action", ["a", "b", "missing"])
def test_action_filter(logs_dir, action):
    want = [e for e in logs_dir if e["action"] == action]
    page, total = activity.read_activity_page(action, 2, 4)
    assert total == len(want)
    assert page == want[2:6]
