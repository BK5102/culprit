"""Small simulated worlds shared by the tests."""

from __future__ import annotations

from culprit.config import make_config


def tiny_config(**world_overrides):
    """A fast world: 2 countries x 2 issuers x 2 BINs x 2 methods x 2 gateways = 32 leaves."""
    world = {
        "weeks": {"context": 3, "calibration": 1, "evaluation": 1},
        "hierarchy": {
            "countries": 2,
            "issuers_per_country": 2,
            "bins_per_issuer": 2,
            "methods": ["card_not_present", "card_present"],
            "gateways": 2,
        },
        "volume": {"mean_attempts_per_hour": 8000},
        "faults": {"per_week": 6.0},
    }
    for k, v in world_overrides.items():
        world[k] = {**world.get(k, {}), **v} if isinstance(v, dict) else v
    return make_config(name="tiny", seed=3, world=world)
