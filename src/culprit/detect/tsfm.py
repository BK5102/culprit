"""Detector C: a time series foundation model forecasts the approval rate (methodology M25).

The detector asks a `QuantileForecaster` for the next `horizon` hours of every
series from its last `context_hours` hours, at forecast origins every
`horizon` hours starting at the first scored hour. Origins are fixed points
on the timeline, not "the end of the data", so the forecast for hour t uses
only hours before t's origin (which is at or before t). Score: how far the
actual rate falls below the median, in units of the spread implied by the
lower quantile, (median - actual) / ((median - q10) / 1.2816).

Two forecasters:

- `FakeForecaster`: deterministic, no model, for tests. Its median is the mean
  of the same hour in earlier weeks of the context; its spread is the robust
  spread of the context around that.
- `ChronosBoltForecaster`: amazon/chronos-bolt-tiny at a pinned revision,
  CPU only, behind the optional `tsfm` extra. Imported lazily, so nothing
  here imports torch unless this class is built. Tests never download weights.

Forecasts can be cached to disk, keyed by the forecaster version, the
settings, and a hash of the input rates (`cache_dir`).
"""

from __future__ import annotations

import hashlib
import json
import warnings
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path
from typing import Protocol

import numpy as np

from culprit.detect.base import finish, rate

MODEL_ID = "amazon/chronos-bolt-tiny"
# Exact weights (Hugging Face commit, the same one Tells pinned on 2026-11-17).
REVISION = "a0e552de83495b5c28c14c71c374f3e33280b340"
Z10 = 1.2815515655446004  # standard normal 90th percentile


class QuantileForecaster(Protocol):
    name: str

    @property
    def version(self) -> str: ...

    def forecast(
        self, contexts: list[np.ndarray], horizon: int, quantiles: Sequence[float]
    ) -> np.ndarray:
        """(series, horizon, quantiles) forecasts. Contexts may contain NaN (missing hours)."""
        ...


class FakeForecaster:
    """Seasonal-mean median and robust spread. Deterministic and instant."""

    name = "fake"
    version = "fake-1"

    def __init__(self, season: int = 168):
        self.season = season

    def forecast(
        self, contexts: list[np.ndarray], horizon: int, quantiles: Sequence[float]
    ) -> np.ndarray:
        from statistics import NormalDist

        zq = np.array([NormalDist().inv_cdf(q) for q in quantiles])
        out = np.empty((len(contexts), horizon, len(quantiles)))
        s = self.season
        for i, c in enumerate(contexts):
            c = np.asarray(c, dtype=float)
            n = len(c)
            med = np.empty(horizon)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                for h in range(horizon):
                    idx = np.arange(n + h - s, -1, -s)  # same hour in earlier weeks
                    idx = idx[idx < n]
                    vals = c[idx] if len(idx) else c[-1:]
                    m = np.nanmean(vals)
                    med[h] = m if np.isfinite(m) else np.nanmean(c)
                resid = c[s:] - c[:-s] if n > s else c - np.nanmean(c)
                spread = 1.4826 * np.nanmedian(np.abs(resid - np.nanmedian(resid))) / np.sqrt(2)
            spread = spread if np.isfinite(spread) and spread > 0 else 1e-3
            out[i] = med[:, None] + spread * zq[None, :]
        return out


class ChronosBoltForecaster:
    """Chronos-Bolt-tiny on CPU (needs `uv sync --extra tsfm`; weights load from Hugging Face)."""

    name = "chronos_bolt"

    def __init__(self, batch_size: int = 256, threads: int | None = None):
        try:
            import torch
            from chronos import BaseChronosPipeline
        except ImportError as err:  # pragma: no cover - depends on the optional extra
            raise ImportError(
                "the TSFM detector needs the optional extra: uv sync --extra tsfm"
            ) from err
        if threads:
            torch.set_num_threads(threads)
        self._torch = torch
        self.batch_size = batch_size
        self._pipe = BaseChronosPipeline.from_pretrained(
            MODEL_ID, revision=REVISION, device_map="cpu", torch_dtype=torch.float32
        )

    @property
    def version(self) -> str:
        package = metadata.version("chronos-forecasting")
        return f"{MODEL_ID}@{REVISION[:12]}/chronos-forecasting-{package}"

    def forecast(
        self, contexts: list[np.ndarray], horizon: int, quantiles: Sequence[float]
    ) -> np.ndarray:  # pragma: no cover - needs model weights
        torch = self._torch
        out = np.empty((len(contexts), horizon, len(quantiles)))
        for lo in range(0, len(contexts), self.batch_size):
            batch = [
                torch.tensor(np.asarray(c, dtype=np.float32))
                for c in contexts[lo : lo + self.batch_size]
            ]
            q, _mean = self._pipe.predict_quantiles(
                batch, prediction_length=horizon, quantile_levels=list(quantiles)
            )
            out[lo : lo + len(batch)] = q.float().cpu().numpy()
        return out


def make_forecaster(name: str | None) -> QuantileForecaster | None:
    if name is None:
        return None
    if name == "fake":
        return FakeForecaster()
    if name == "chronos_bolt":
        return ChronosBoltForecaster()
    raise ValueError(f"unknown TSFM adapter {name!r}")


class TSFMDetector:
    name = "TSFM"

    def __init__(
        self,
        forecaster: QuantileForecaster,
        context_hours: int = 512,
        horizon: int = 24,
        quantiles: Sequence[float] = (0.1, 0.5, 0.9),
        cache_dir: str | Path | None = None,
    ):
        if 0.1 not in quantiles or 0.5 not in quantiles:
            raise ValueError("quantiles must include 0.1 and 0.5")
        self.forecaster = forecaster
        self.context_hours = context_hours
        self.horizon = horizon
        self.quantiles = tuple(quantiles)
        self.cache_dir = Path(cache_dir) if cache_dir else None

    def _cache_key(self, r: np.ndarray, start: int) -> str:
        h = hashlib.sha256()
        meta = [self.forecaster.version, self.context_hours, self.horizon, self.quantiles, start]
        h.update(json.dumps(meta).encode())
        h.update(np.ascontiguousarray(np.nan_to_num(r, nan=-1.0)).tobytes())
        return h.hexdigest()[:24]

    def forecasts(self, r: np.ndarray, start: int) -> np.ndarray:
        """(series, hours, quantiles), NaN before `start`."""
        if self.cache_dir is not None:
            path = self.cache_dir / f"tsfm-{self._cache_key(r, start)}.npy"
            if path.exists():
                return np.load(path)
        n, t_n = r.shape
        out = np.full((n, t_n, len(self.quantiles)), np.nan)
        for origin in range(start, t_n, self.horizon):
            lo = max(0, origin - self.context_hours)
            contexts = [r[i, lo:origin] for i in range(n)]
            fc = self.forecaster.forecast(contexts, self.horizon, self.quantiles)
            stop = min(t_n, origin + self.horizon)
            out[:, origin:stop] = fc[:, : stop - origin]
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            np.save(path, out)
        return out

    def score(self, attempts: np.ndarray, approved: np.ndarray, start: int) -> np.ndarray:
        r = rate(approved, attempts)
        fc = self.forecasts(r, start)
        med = fc[..., self.quantiles.index(0.5)]
        q10 = fc[..., self.quantiles.index(0.1)]
        spread = np.maximum((med - q10) / Z10, 1e-4)
        return finish((med - r) / spread, start)
