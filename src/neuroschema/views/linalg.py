"""LU decomposition with partial pivoting, the one solver the view algorithms name.

``nemar.sensor-field.v1`` solves its interpolation matrix with it and
``nemar.sensor-layout.v1`` its sphere fit, so every implementation uses the
same elimination order and pivot rule. numpy only: install the ``views`` extra.
"""

from __future__ import annotations

import numpy as np


class SingularMatrix(ArithmeticError):
    """A pivot at or below the solver's threshold."""


def lu_solve(a: np.ndarray, b: np.ndarray, *, tiny: float | None = None) -> np.ndarray:
    """Solve ``a @ w = b`` by LU decomposition with partial pivoting, in float64.

    At step k the pivot is the entry of largest magnitude in column k, at or
    below the diagonal; on a tie, the first such row. Rows of ``a`` and ``b``
    are swapped, the rows below are eliminated, and ``w`` is found by back
    substitution.

    With ``tiny`` given, a pivot whose magnitude is at most ``tiny`` raises
    :class:`SingularMatrix`. Without it, every pivot is used as it is, so an
    exactly zero pivot divides by zero and gives a weight that is not finite,
    as IEEE 754 arithmetic does in any language; the caller checks for that.
    """
    a = np.array(a, dtype=np.float64)
    b = np.array(b, dtype=np.float64)
    n = len(b)
    if a.shape != (n, n):
        raise ValueError(f"a is {a.shape}; b needs a {n}-by-{n} matrix")
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        for k in range(n):
            pivot = k + int(np.argmax(np.abs(a[k:, k])))
            if tiny is not None and not abs(a[pivot, k]) > tiny:
                raise SingularMatrix(f"pivot {k} of {n} is {a[pivot, k]!r}")
            if pivot != k:
                a[[k, pivot]] = a[[pivot, k]]
                b[[k, pivot]] = b[[pivot, k]]
            factors = a[k + 1 :, k] / a[k, k]
            a[k + 1 :, k + 1 :] -= np.outer(factors, a[k, k + 1 :])
            b[k + 1 :] -= factors * b[k]
        w = np.empty(n)
        for k in range(n - 1, -1, -1):
            w[k] = (b[k] - a[k, k + 1 :] @ w[k + 1 :]) / a[k, k]
    return w
