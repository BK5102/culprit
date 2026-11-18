"""Segments (slices): filters over the leaf table, and the hierarchy between them.

A leaf segment is one (BIN range, payment method, gateway) combination. A BIN
range belongs to one issuer, and an issuer to one country, so the geography
dimensions nest: country > issuer > bin. Method and gateway cut across them.

A node is a filter such as {"issuer": "C1-I2", "method": "card_not_present"}.
Filters are kept canonical: only the most specific geography key is stored,
because ids embed their parents (bin "C1-I2-B0" is in issuer "C1-I2").

This module only knows the public leaf table. It never touches the simulator
or the answer key, so detectors, the control and the agent may import it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
from scipy import sparse

GEO = ("country", "issuer", "bin")
CROSS = ("method", "gateway")
DIMS = GEO + CROSS
TOTAL = "total"

Filter = dict[str, str]


def canonical(f: Mapping[str, str]) -> Filter:
    out: Filter = {}
    geo = [k for k in GEO if k in f]
    if geo:
        out[geo[-1]] = f[geo[-1]]
    for k in CROSS:
        if k in f:
            out[k] = f[k]
    unknown = set(f) - set(DIMS)
    if unknown:
        raise KeyError(f"unknown segment dimensions {sorted(unknown)}")
    return out


def node_key(f: Mapping[str, str]) -> str:
    c = canonical(f)
    return "|".join(f"{k}={c[k]}" for k in DIMS if k in c) or TOTAL


def parse_key(key: str) -> Filter:
    if key == TOTAL:
        return {}
    return canonical(dict(part.split("=", 1) for part in key.split("|")))


def geo_level(f: Mapping[str, str]) -> int:
    """0 for no geography key, 1 country, 2 issuer, 3 bin."""
    for i, k in reversed(list(enumerate(GEO))):
        if k in f:
            return i + 1
    return 0


def depth(f: Mapping[str, str]) -> int:
    """How specific a filter is: geography level plus one per cross dimension."""
    c = canonical(f)
    return geo_level(c) + sum(k in c for k in CROSS)


class Segments:
    """The leaf table and node arithmetic. Leaves are indexed 0..n_leaves-1."""

    def __init__(self, leaves: Mapping[str, Iterable[str]]):
        self.cols = {k: np.asarray(list(leaves[k]), dtype=object) for k in DIMS}
        self.n_leaves = len(self.cols["bin"])
        for k in DIMS:
            if len(self.cols[k]) != self.n_leaves:
                raise ValueError("every leaf column must have the same length")
        self.values = {k: sorted(set(self.cols[k].tolist())) for k in DIMS}
        pairs_ci = set(zip(self.cols["country"], self.cols["issuer"], strict=True))
        pairs_ib = set(zip(self.cols["issuer"], self.cols["bin"], strict=True))
        self.issuers_of = {
            c: sorted(i for cc, i in pairs_ci if cc == c) for c in self.values["country"]
        }
        self.bins_of = {
            i: sorted(b for ii, b in pairs_ib if ii == i) for i in self.values["issuer"]
        }

    def leaf_filter(self, leaf: int) -> Filter:
        return canonical({k: self.cols[k][leaf] for k in ("bin", "method", "gateway")})

    def leaf_keys(self) -> list[str]:
        return [node_key(self.leaf_filter(i)) for i in range(self.n_leaves)]

    def mask(self, f: Mapping[str, str]) -> np.ndarray:
        m = np.ones(self.n_leaves, dtype=bool)
        for k, v in canonical(f).items():
            m &= self.cols[k] == v
        return m

    def exists(self, f: Mapping[str, str]) -> bool:
        try:
            return bool(self.mask(f).any())
        except KeyError:
            return False

    def refinements(self, f: Mapping[str, str]) -> dict[str, list[Filter]]:
        """Children of a node, one list per dimension that can be refined next."""
        c = canonical(f)
        out: dict[str, list[Filter]] = {}
        level = geo_level(c)
        if level == 0:
            out["country"] = [{**c, "country": v} for v in self.values["country"]]
        elif level == 1:
            out["issuer"] = [canonical({**c, "issuer": v}) for v in self.issuers_of[c["country"]]]
        elif level == 2:
            out["bin"] = [canonical({**c, "bin": v}) for v in self.bins_of[c["issuer"]]]
        for k in CROSS:
            if k not in c:
                out[k] = [{**c, k: v} for v in self.values[k]]
        return {
            dim: [canonical(x) for x in kids if self.mask(x).any()] for dim, kids in out.items()
        }

    def monitored_nodes(self, include_leaves: bool = True) -> list[Filter]:
        """The series every detector watches: total, each single dimension value, each leaf."""
        nodes: list[Filter] = [{}]
        for k in DIMS:
            nodes += [{k: v} for v in self.values[k]]
        if include_leaves:
            nodes += [self.leaf_filter(i) for i in range(self.n_leaves)]
        return [canonical(n) for n in nodes]

    def membership(self, nodes: list[Mapping[str, str]]) -> sparse.csr_matrix:
        """Sparse (nodes x leaves) 0/1 matrix; multiply leaf counts by it to get node counts."""
        rows, cols = [], []
        for r, f in enumerate(nodes):
            idx = np.flatnonzero(self.mask(f))
            rows.append(np.full(len(idx), r))
            cols.append(idx)
        r = np.concatenate(rows) if rows else np.array([], dtype=int)
        c = np.concatenate(cols) if cols else np.array([], dtype=int)
        data = np.ones(len(r), dtype=np.float64)
        return sparse.csr_matrix((data, (r, c)), shape=(len(nodes), self.n_leaves))
