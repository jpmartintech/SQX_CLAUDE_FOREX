"""Predicate evaluation to boolean arrays and packing into uint64 bitsets.

Bitset layout: ``bits[row, w]`` bit ``b`` (LSB first) is bar ``64 * w + b``. Bits beyond the last bar are 0.
"""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from sqxf.strategy.definition import Predicate


def predicate_mask(values: np.ndarray, pred: Predicate) -> np.ndarray:
    """Boolean mask; NaN compares False for every operator."""
    with np.errstate(invalid="ignore"):
        if pred.operator == ">":
            return values > pred.value
        if pred.operator == "<":
            return values < pred.value
        return values == pred.value


def predicate_matrix(features: dict[str, np.ndarray], preds: Iterable[Predicate]) -> np.ndarray:
    preds = list(preds)
    n = len(next(iter(features.values())))
    out = np.empty((len(preds), n), dtype=bool)
    for i, p in enumerate(preds):
        out[i] = predicate_mask(features[p.feature], p)
    return out


def pack_bits(masks: np.ndarray) -> np.ndarray:
    """``bool[rows, n]`` (or ``bool[n]``) -> ``uint64[rows, ceil(n/64)]`` (or 1-D)."""
    one_d = masks.ndim == 1
    m = np.atleast_2d(np.asarray(masks, dtype=bool))
    rows, n = m.shape
    n_words = (n + 63) // 64
    padded = np.zeros((rows, n_words * 64), dtype=bool)
    padded[:, :n] = m
    packed = np.packbits(padded, axis=1, bitorder="little")  # uint8[rows, n_words*8]
    words = np.ascontiguousarray(packed).view("<u8").astype(np.uint64)
    return words[0] if one_d else words


def unpack_bits(words: np.ndarray, n: int) -> np.ndarray:
    w = np.atleast_2d(words).astype("<u8")
    bits = np.unpackbits(w.view(np.uint8), axis=1, bitorder="little")[:, :n].astype(bool)
    return bits[0] if words.ndim == 1 else bits
