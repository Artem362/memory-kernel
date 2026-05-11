from __future__ import annotations

import os


def _native_disabled() -> bool:
    value = os.getenv("MEMORY_KERNEL_DISABLE_NATIVE", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _experimental_native_rank_enabled() -> bool:
    value = os.getenv("MEMORY_KERNEL_EXPERIMENTAL_NATIVE_RANK", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


if _native_disabled():
    native_accel = None
else:
    try:
        from . import _native as native_accel
    except ImportError:
        native_accel = None


def has_native_acceleration() -> bool:
    return native_accel is not None


def has_experimental_native_ranking() -> bool:
    return native_accel is not None and _experimental_native_rank_enabled()


def light_stem_enabled() -> bool:
    value = os.getenv("MEMORY_KERNEL_DISABLE_STEMMER", "")
    return value.strip().lower() not in {"1", "true", "yes", "on"}
