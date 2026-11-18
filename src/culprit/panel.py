"""Node-level panels: sum leaf counts up to any set of segments.

Shared by the detectors, the deterministic control, the agent tools and the
data-fit check. Reads only an ObservedWorld (or plain arrays).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from culprit.segments import Segments, node_key
from culprit.world import ObservedWorld


def aggregate(segments: Segments, leaf_values: np.ndarray, nodes: list[Mapping[str, str]]):
    """(nodes, hours[, ...]) sums of `leaf_values` (leaves, hours[, ...]) over each node."""
    m = segments.membership(list(nodes))
    flat = leaf_values.reshape(leaf_values.shape[0], -1)
    out = m @ flat
    return np.asarray(out).reshape((len(nodes),) + leaf_values.shape[1:])


def rate(approved: np.ndarray, attempts: np.ndarray) -> np.ndarray:
    """approved / attempts, NaN where there were no attempts."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(attempts > 0, approved / np.maximum(attempts, 1), np.nan)


@dataclass
class NodePanel:
    nodes: list[dict[str, str]]
    keys: list[str]
    attempts: np.ndarray  # (nodes, hours) float
    approved: np.ndarray  # (nodes, hours) float

    @property
    def rate(self) -> np.ndarray:
        return rate(self.approved, self.attempts)

    def index(self, key: str) -> int:
        return self.keys.index(key)


def node_panel(world: ObservedWorld, nodes: list[Mapping[str, str]] | None = None) -> NodePanel:
    nodes = [dict(n) for n in (nodes if nodes is not None else world.segments.monitored_nodes())]
    att = aggregate(world.segments, world.attempts.astype(float), nodes)
    app = aggregate(world.segments, world.approved.astype(float), nodes)
    return NodePanel(nodes, [node_key(n) for n in nodes], att, app)
