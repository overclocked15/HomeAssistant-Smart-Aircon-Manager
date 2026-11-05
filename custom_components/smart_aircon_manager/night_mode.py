"""Night mode's temperature drop, shared by the Night Mode switch and the
options page so both turn night mode on and off the same way."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_ENABLE_NIGHT_MODE,
    CONF_NIGHT_MODE_SAVED_TARGET,
    CONF_NIGHT_MODE_TEMP_DROP,
    CONF_TARGET_TEMPERATURE,
    DEFAULT_TARGET_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def night_mode_entry_data(
    data: Mapping[str, Any], enable: bool, current_target: float | None = None
) -> dict[str, Any]:
    """Return the config entry data after turning night mode on or off.

    Turning it on (from off) lowers the target once by the configured drop
    and stores the target it replaced; turning it off restores that target.
    Turning it on while it is already on, or off while off, only sets the
    flag. So a target adjusted during the night stands until night mode
    ends, and the drop never compounds from one night to the next.

    ``current_target`` is the live target when the caller has one (the
    switch); otherwise the stored target is used.
    """
    new = dict(data)
    was_on = bool(data.get(CONF_ENABLE_NIGHT_MODE, False))
    new[CONF_ENABLE_NIGHT_MODE] = bool(enable)

    if enable and not was_on:
        new.pop(CONF_NIGHT_MODE_SAVED_TARGET, None)
        drop = _as_float(data.get(CONF_NIGHT_MODE_TEMP_DROP)) or 0.0
        if drop > 0:
            target = current_target
            if target is None:
                target = _as_float(data.get(CONF_TARGET_TEMPERATURE))
            if target is None:
                target = float(DEFAULT_TARGET_TEMPERATURE)
            new[CONF_NIGHT_MODE_SAVED_TARGET] = target
            new[CONF_TARGET_TEMPERATURE] = max(MIN_TARGET_TEMPERATURE, round(target - drop, 1))
    elif not enable and was_on:
        saved = _as_float(data.get(CONF_NIGHT_MODE_SAVED_TARGET))
        if saved is not None:
            new[CONF_TARGET_TEMPERATURE] = saved
        new.pop(CONF_NIGHT_MODE_SAVED_TARGET, None)

    return new
