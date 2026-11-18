"""The segment hierarchy: countries, issuers, BIN ranges, payment methods, gateways.

Leaves are the full cross product of BIN range x method x gateway, so every
card range can be routed through every gateway (methodology M8). Each level
gets a volume share drawn from a Dirichlet distribution, which gives a mix of
big and small segments, like real cities with big and small neighborhoods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from culprit.segments import Segments


@dataclass(frozen=True)
class Hierarchy:
    segments: Segments
    share: np.ndarray  # (leaves,) share of total volume, sums to 1
    tz_offset: dict[str, int]  # country -> hours added to world time to get local time
    leaf_country: np.ndarray  # (leaves,) country index

    @property
    def countries(self) -> list[str]:
        return self.segments.values["country"]


def build_hierarchy(cfg: dict[str, Any], volume_cfg: dict[str, Any], rng) -> Hierarchy:
    n_c = int(cfg["countries"])
    n_i = int(cfg["issuers_per_country"])
    n_b = int(cfg["bins_per_issuer"])
    methods = list(cfg["methods"])
    n_g = int(cfg["gateways"])
    alpha = float(cfg["share_concentration"])
    gateways = [f"G{g}" for g in range(n_g)]

    def dirichlet(n: int) -> np.ndarray:
        return rng.dirichlet(np.full(n, alpha * 4.0)) if n > 1 else np.ones(1)

    country_share = dirichlet(n_c)
    method_share = dirichlet(len(methods))
    gateway_share = dirichlet(n_g)

    cols: dict[str, list[str]] = {k: [] for k in ("country", "issuer", "bin", "method", "gateway")}
    shares: list[float] = []
    leaf_country: list[int] = []
    for c in range(n_c):
        issuer_share = rng.dirichlet(np.full(n_i, alpha)) if n_i > 1 else np.ones(1)
        for i in range(n_i):
            bin_share = rng.dirichlet(np.full(n_b, alpha)) if n_b > 1 else np.ones(1)
            for b in range(n_b):
                for m, method in enumerate(methods):
                    for g, gw in enumerate(gateways):
                        cols["country"].append(f"C{c}")
                        cols["issuer"].append(f"C{c}-I{i}")
                        cols["bin"].append(f"C{c}-I{i}-B{b}")
                        cols["method"].append(method)
                        cols["gateway"].append(gw)
                        shares.append(
                            country_share[c]
                            * issuer_share[i]
                            * bin_share[b]
                            * method_share[m]
                            * gateway_share[g]
                        )
                        leaf_country.append(c)
    share = np.asarray(shares)
    # Leaf-level wobble so no two leaves are exact products of their levels.
    share = share * rng.lognormal(0.0, 0.2, size=len(share))
    share = share / share.sum()
    max_tz = int(volume_cfg["max_timezone_offset"])
    tz = {f"C{c}": int(rng.integers(-max_tz, max_tz + 1)) if c else 0 for c in range(n_c)}
    return Hierarchy(Segments(cols), share, tz, np.asarray(leaf_country))
