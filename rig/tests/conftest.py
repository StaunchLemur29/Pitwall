from __future__ import annotations

import pytest

from pitwall_rig.adapters.demo import DemoAdapter
from pitwall_rig.config import Config
from pitwall_rig.storage import Store


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def demo(clock: FakeClock) -> DemoAdapter:
    return DemoAdapter(clock=clock, seed=1, start_in_pit_s=1.0)


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(tmp_path / "config.json")
