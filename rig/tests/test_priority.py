"""Priority boost for Pitwall's windows (priority.py)."""

from __future__ import annotations

from pitwall_rig import browser
from pitwall_rig.priority import Keeper, boost_self, descendants

# Chrome's browser (100) with a GPU (101) and page (102) process, a utility
# process under the page (103), and an unrelated program (200) and its child.
PAIRS = [(0, 0), (4, 0), (100, 50), (101, 100), (102, 100), (103, 102), (200, 4), (201, 200)]


def test_descendants_cover_the_whole_tree_and_nothing_else():
    assert sorted(descendants(PAIRS, 100)) == [100, 101, 102, 103]
    assert descendants(PAIRS, 999) == [999]  # gone already: just itself
    assert sorted(descendants(PAIRS, 4)) == [4, 200, 201]
    assert 0 in descendants(PAIRS, 0)  # the idle process is its own parent: no endless loop


def test_keeper_boosts_every_window_process_each_tick():
    boosted: list[int] = []
    k = Keeper(lambda: [100], pairs=lambda: PAIRS, boost=lambda pid: boosted.append(pid) or True)
    assert k.tick() == 4
    assert sorted(boosted) == [100, 101, 102, 103]
    assert k.tick() == 4  # again: Chrome may have lowered one


def test_keeper_survives_processes_it_cannot_touch():
    def boost(pid: int) -> bool:
        if pid == 101:
            raise OSError("access denied")
        return pid != 102

    k = Keeper(lambda: [100], pairs=lambda: PAIRS, boost=boost)
    assert k.tick() == 2


def test_keeper_does_nothing_without_windows():
    k = Keeper(list, pairs=lambda: (_ for _ in ()).throw(AssertionError("listed processes")))
    assert k.tick() == 0


def test_boost_self_is_a_no_op_off_windows():
    assert boost_self() is False


def test_windows_launch_unthrottled_on_the_gpu(monkeypatch, tmp_path):
    seen: dict = {}

    class FakePopen:
        pid = 1

        def __init__(self, args):
            seen["args"] = args

        def poll(self):
            return None

    monkeypatch.setattr(browser, "_browser", lambda which: "/bin/chrome")
    monkeypatch.setattr(browser.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(browser, "default_data_dir", lambda: tmp_path)
    started: list[bool] = []
    monkeypatch.setattr(browser._keeper, "start", lambda: started.append(True))
    assert browser._launch("http://x", {"browser": "auto"}, 0, 0, 10, 10, "p", [], "test")
    args = seen["args"]
    assert "--disable-renderer-backgrounding" in args and "--ignore-gpu-blocklist" in args
    feats = [a for a in args if a.startswith("--disable-features=")]
    assert len(feats) == 1 and "UseEcoQoSForBackgroundProcess" in feats[0]  # Chrome only reads one
    assert started == [True]
    browser._windows.pop("test")
    started.clear()
    browser._launch("http://x", {"browser": "auto", "high_priority": False}, 0, 0, 10, 10, "p", [], "test")
    assert started == []
    browser._windows.pop("test")
