#!/usr/bin/env python3
"""
Feature extraction utilities for EEG mental-state classification.

This module defines a simple feature set that can be used both for
training (on an external EEG dataset) and for real-time prediction
inside the GUI.
"""

from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np


DEFAULT_FS = 100.0  # Hz, approximate sampling rate from Arduino sketch (delay(10))


def _bandpower(
    signal: np.ndarray,
    fs: float,
    band: Tuple[float, float],
) -> float:
    """
    Compute band power in a given frequency band using FFT.
    """
    if signal.size == 0:
        return 0.0

    # Remove DC offset
    x = signal - np.mean(signal)

    freqs = np.fft.rfftfreq(x.size, d=1.0 / fs)
    fft_vals = np.abs(np.fft.rfft(x)) ** 2

    fmin, fmax = band
    idx = np.where((freqs >= fmin) & (freqs <= fmax))[0]
    if idx.size == 0:
        return 0.0
    return float(np.trapz(fft_vals[idx], freqs[idx]))


def extract_features(
    signal: Iterable[float],
    fs: float = DEFAULT_FS,
) -> np.ndarray:
    """
    Extract a simple feature vector from a 1D EEG segment.

    Features:
        - mean, std, min, max, max-min
        - band power in delta, theta, alpha, beta ranges
    """
    x = np.asarray(list(signal), dtype=float)
    if x.size == 0:
        # Return zeros with the expected feature length
        return np.zeros(9, dtype=float)

    # Time-domain statistics
    mean = float(np.mean(x))
    std = float(np.std(x))
    xmin = float(np.min(x))
    xmax = float(np.max(x))
    peak_to_peak = xmax - xmin

    # Simple EEG frequency bands (Hz)
    delta = _bandpower(x, fs, (0.5, 4.0))
    theta = _bandpower(x, fs, (4.0, 8.0))
    alpha = _bandpower(x, fs, (8.0, 13.0))
    beta = _bandpower(x, fs, (13.0, 30.0))

    feats = np.array(
        [
            mean,
            std,
            xmin,
            xmax,
            peak_to_peak,
            delta,
            theta,
            alpha,
            beta,
        ],
        dtype=float,
    )
    return feats


__all__ = ["extract_features", "DEFAULT_FS"]


