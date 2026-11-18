from __future__ import annotations

import pytest
from worlds import tiny_config

from culprit.config import make_config
from culprit.sim.build import simulate


@pytest.fixture(scope="session")
def tiny_sim():
    return simulate(tiny_config())


@pytest.fixture(scope="session")
def small_sim():
    return simulate(make_config(name="small", seed=11))
