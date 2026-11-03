"""Which systems a car has, so Pitwall only shows (and later coaches) what exists.

Built from the game's static data (DRS, ERS / KERS, engine-brake maps), what
shows up in telemetry (ABS / TC actually doing something) and, when the
in-game CSP app runs, the exact number of ABS / TC levels and deploy modes.
Saved per car, so it's known before the first lap next time.
"""

from __future__ import annotations

from typing import Any

from .models import Frame, SessionInfo

EMPTY: dict[str, Any] = {
    "abs": False,
    "abs_levels": None,
    "tc": False,
    "tc_levels": None,
    "brake_bias": False,
    "drs": False,
    "battery": False,  # ERS or KERS
    "ers": False,  # deploy / recovery modes (hybrids)
    "deploy_modes": None,
    "engine_brake_maps": None,
}


def from_session(s: SessionInfo, saved: dict[str, Any] | None = None) -> dict[str, Any]:
    p = {**EMPTY, **(saved or {})}
    p["drs"] = p["drs"] or s.has_drs
    p["battery"] = p["battery"] or s.has_ers or s.has_kers
    p["ers"] = p["ers"] or s.has_ers
    if s.ers_power_modes > 1:
        p["deploy_modes"] = s.ers_power_modes
    if s.engine_brake_maps > 1:
        p["engine_brake_maps"] = s.engine_brake_maps
    return p


def note_frame(p: dict[str, Any], f: Frame) -> bool:
    """Learn from telemetry; True if anything changed."""
    changed = False
    for key, on in (("abs", (f.abs or 0) > 0), ("tc", (f.tc or 0) > 0), ("brake_bias", f.brake_bias is not None)):
        if on and not p[key]:
            p[key], changed = True, True
    return changed


def note_csp(p: dict[str, Any], el: dict[str, Any]) -> bool:
    """Learn from the in-game app's exact counts; True if anything changed."""
    before = dict(p)
    if el.get("abs_modes"):
        p["abs"], p["abs_levels"] = True, int(el["abs_modes"])
    if el.get("tc_modes"):
        p["tc"], p["tc_levels"] = True, int(el["tc_modes"])
    if el.get("drs_present"):
        p["drs"] = True
    if el.get("kers_present"):
        p["battery"] = True
    if (el.get("mguk_delivery_count") or 0) > 1:
        p["ers"], p["deploy_modes"] = True, int(el["mguk_delivery_count"])
    if (el.get("engine_brake_count") or 0) > 1:
        p["engine_brake_maps"] = int(el["engine_brake_count"])
    return p != before


def summary(p: dict[str, Any]) -> list[str]:
    """Plain list for the UI: ["ABS (12)", "TC (8)", "DRS", "ERS (4 deploy modes)", ...]."""
    out = []
    if p["abs"]:
        out.append(f"ABS ({p['abs_levels']})" if p["abs_levels"] else "ABS")
    if p["tc"]:
        out.append(f"TC ({p['tc_levels']})" if p["tc_levels"] else "TC")
    if p["brake_bias"]:
        out.append("Brake bias")
    if p["drs"]:
        out.append("DRS")
    if p["ers"]:
        out.append(f"ERS ({p['deploy_modes']} deploy modes)" if p["deploy_modes"] else "ERS")
    elif p["battery"]:
        out.append("KERS")
    if p["engine_brake_maps"]:
        out.append(f"Engine braking ({p['engine_brake_maps']} maps)")
    return out
