"""Closed-loop physiology — bounded-residual update for vital signs (PR-C / WS-3).

The existing :mod:`healthcraft.world.physiology` is **open-loop**:
``VitalsTrajectory.interpolate(t)`` returns the base trajectory (e.g.,
untreated sepsis deterioration) regardless of clinical interventions. That
makes the environment a single-step bandit, not an MDP — sequential credit
assignment is impossible and GRPO has nothing time-dependent to learn from.

This module overlays a bounded residual on top of that base:

.. math::
    s_t^{\\rm observed} = {\\rm clip}\\!\\Bigl(
        \\, {\\rm base\\_interp}(t) +
        \\sum_{a} {\\rm effect}\\bigl(a,\\, t - t_a\\bigr) ,\\
        \\text{bounds} \\Bigr)

Each mutating action (extracted from the audit log) contributes a
time-varying delta to selected vitals: linear ramp to peak over
``onset_minutes``, then linear decay to zero over ``duration_minutes``.
The sum is clipped to physiologic bounds so the patient never escapes
plausible ranges (no negative BPs; SpO2 capped at 100%; etc.).

**Deliberately simplified.** This is NOT a clinical-grade physiology
simulator — it maps a handful of action signatures to defensible
directional effects so the environment becomes a genuine sequential MDP
with clinically-directional credit assignment. The goal is RL trainability,
not pharmacology. Extending the model is straightforward: add entries to
``ACTION_EFFECTS`` and signature patterns to ``_classify_action``.

Per the project firewall (``docs/RL_COUPLING.md``): a model trained
against this env is a research artifact; deployment requires held-out
prospective validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from healthcraft.world.physiology import VitalsSnapshot
from healthcraft.world.state import AuditEntry, WorldState


@dataclass(frozen=True)
class ActionEffect:
    """A single action's effect on selected vitals over time.

    ``delta`` gives the at-peak change for each vital it modifies (other
    vitals are untouched). ``onset_minutes`` is the linear ramp to peak;
    ``duration_minutes`` is the linear decay from peak back to zero.
    """

    delta: dict[str, float]
    onset_minutes: float = 1.0
    duration_minutes: float = 30.0
    rationale: str = ""


# --- Action → effect mapping (simplified clinical model) -----------------
# Keys are normalised signatures derived from audit entries via
# ``_classify_action``. PR-C ships this minimal set; extending is a matter
# of adding to ``ACTION_EFFECTS`` and the classifier patterns below.

ACTION_EFFECTS: dict[str, ActionEffect] = {
    "createClinicalOrder:medication:vasopressor": ActionEffect(
        delta={"systolic_bp": 15.0, "diastolic_bp": 8.0, "heart_rate": 5.0},
        onset_minutes=2.0,
        duration_minutes=60.0,
        rationale=(
            "Vasopressors (norepinephrine, epinephrine, vasopressin, "
            "phenylephrine, dopamine) raise MAP via α-adrenergic "
            "vasoconstriction; mild reflex tachycardia."
        ),
    ),
    "createClinicalOrder:medication:fluid": ActionEffect(
        delta={"systolic_bp": 5.0, "heart_rate": -3.0},
        onset_minutes=10.0,
        duration_minutes=120.0,
        rationale=(
            "IV crystalloid expands intravascular volume → modest BP rise; "
            "HR slows as perfusion improves."
        ),
    ),
    "createClinicalOrder:medication:antibiotic": ActionEffect(
        delta={"temperature": -0.5, "heart_rate": -5.0, "respiratory_rate": -1.0},
        onset_minutes=30.0,
        duration_minutes=180.0,
        rationale=(
            "Antibiotics treat the source infection; sepsis trajectory flattens "
            "as bacterial load drops (slow onset, sustained)."
        ),
    ),
    "createClinicalOrder:medication:analgesic": ActionEffect(
        delta={"heart_rate": -5.0, "respiratory_rate": -2.0, "systolic_bp": -3.0},
        onset_minutes=5.0,
        duration_minutes=90.0,
        rationale="Opioid analgesia reduces sympathetic drive; mild RR/BP/HR drops.",
    ),
    "createClinicalOrder:procedure:oxygen": ActionEffect(
        delta={"spo2": 4.0, "respiratory_rate": -2.0},
        onset_minutes=1.0,
        duration_minutes=60.0,
        rationale="Supplemental O2 raises arterial saturation; hypoxic-drive RR drops.",
    ),
}


# --- Physiologic bounds (clipping) --------------------------------------

_DEFAULT_VITAL_BOUNDS: dict[str, tuple[float, float]] = {
    "heart_rate": (20.0, 250.0),
    "systolic_bp": (40.0, 260.0),
    "diastolic_bp": (20.0, 180.0),
    "respiratory_rate": (4.0, 60.0),
    "spo2": (40.0, 100.0),
    "temperature": (32.0, 43.0),
    "gcs": (3.0, 15.0),
}

_VITAL_NAMES: tuple[str, ...] = tuple(_DEFAULT_VITAL_BOUNDS.keys())


# --- Effect evaluation --------------------------------------------------


def evaluate_action_contribution(
    effect: ActionEffect,
    elapsed_minutes: float,
) -> dict[str, float]:
    """Return the action's delta dict scaled by the ramp/decay envelope.

    Ramp linearly from 0 to peak over ``onset_minutes``, then decay
    linearly from peak to 0 over ``duration_minutes``. Returns an empty
    dict when ``elapsed_minutes`` is negative (action hasn't happened
    yet) or past the full window (effect spent).
    """
    if elapsed_minutes < 0:
        return {}
    t = elapsed_minutes
    if t < effect.onset_minutes:
        scale = (t / effect.onset_minutes) if effect.onset_minutes > 0 else 1.0
    elif t < effect.onset_minutes + effect.duration_minutes:
        decay_t = t - effect.onset_minutes
        scale = 1.0 - (decay_t / effect.duration_minutes)
    else:
        scale = 0.0
    if scale <= 0.0:
        return {}
    return {vital: delta * scale for vital, delta in effect.delta.items()}


def apply_action_effects_to_vitals(
    base: VitalsSnapshot,
    actions: list[tuple[float, ActionEffect]],
    current_time_minutes: float,
    bounds: dict[str, tuple[float, float]] | None = None,
) -> VitalsSnapshot:
    """Apply timed action effects to a baseline :class:`VitalsSnapshot`.

    Args:
        base: The open-loop baseline (e.g., ``physiology.interpolate(traj, t)``).
        actions: ``[(action_time_minutes, effect), ...]`` in any order.
        current_time_minutes: Time at which to compute the snapshot.
        bounds: Override the default physiologic bounds.

    Returns:
        A new ``VitalsSnapshot`` with all in-window deltas summed on top
        of ``base`` and clipped to plausible bounds.
    """
    deltas: dict[str, float] = {}
    for action_time, effect in actions:
        elapsed = current_time_minutes - action_time
        contribution = evaluate_action_contribution(effect, elapsed)
        for vital, delta in contribution.items():
            deltas[vital] = deltas.get(vital, 0.0) + delta

    use_bounds = bounds if bounds is not None else _DEFAULT_VITAL_BOUNDS
    new_values: dict[str, Any] = {}
    for vital in _VITAL_NAMES:
        base_val = float(getattr(base, vital))
        delta = deltas.get(vital, 0.0)
        new_val = base_val + delta
        lo, hi = use_bounds.get(vital, (-float("inf"), float("inf")))
        new_val = max(lo, min(hi, new_val))
        if vital == "temperature":
            new_values[vital] = round(new_val, 1)
        else:
            new_values[vital] = int(round(new_val))

    return VitalsSnapshot(offset_minutes=base.offset_minutes, **new_values)


# --- Audit-log → actions extraction -------------------------------------

_VASOPRESSORS = (
    "norepinephrine",
    "epinephrine",
    "vasopressin",
    "phenylephrine",
    "dopamine",
    "levophed",
    "neosynephrine",
)
_ANTIBIOTICS = (
    "antibiotic",
    "vancomycin",
    "piperacillin",
    "ceftriaxone",
    "meropenem",
    "ciprofloxacin",
    "azithromycin",
    "ceftazidime",
    "tobramycin",
    "gentamicin",
    "metronidazole",
)
_FLUIDS = ("saline", "lactated ringer", "lr ", " lr", "crystalloid", "albumin", "fluid bolus")
_ANALGESICS = (
    "morphine",
    "fentanyl",
    "hydromorphone",
    "dilaudid",
    "oxycodone",
    "ketorolac",
    "toradol",
    "acetaminophen",
    "tylenol",
)
_OXYGEN_KEYWORDS = ("oxygen", "nasal cannula", "nrb", "bipap", "cpap", "ventilator")


def _classify_action(entry: AuditEntry) -> str | None:
    """Classify an audit entry into an ``ACTION_EFFECTS`` key, or ``None``.

    Only successful (``result_summary == 'ok'``) ``createClinicalOrder``
    entries with a recognised medication / procedure type currently map
    to an effect. Errors and other tools are ignored.
    """
    if entry.result_summary != "ok":
        return None
    tn = entry.tool_name.lower().replace("_", "")
    if tn != "createclinicalorder":
        return None

    params = entry.params if isinstance(entry.params, dict) else {}
    order_type = str(params.get("order_type", "")).lower()
    details = params.get("details", {})
    if not isinstance(details, dict):
        details = {}
    med_name = str(details.get("medication", details.get("name", ""))).lower()
    details_text = " ".join(str(v).lower() for v in details.values())
    haystack = f"{med_name} {details_text}"

    if order_type == "medication":
        if any(v in haystack for v in _VASOPRESSORS):
            return "createClinicalOrder:medication:vasopressor"
        if any(a in haystack for a in _ANTIBIOTICS):
            return "createClinicalOrder:medication:antibiotic"
        if any(f in haystack for f in _FLUIDS):
            return "createClinicalOrder:medication:fluid"
        if any(a in haystack for a in _ANALGESICS):
            return "createClinicalOrder:medication:analgesic"
    elif order_type == "procedure":
        if any(o in haystack for o in _OXYGEN_KEYWORDS):
            return "createClinicalOrder:procedure:oxygen"
    return None


def actions_from_audit_log(
    audit_log: list[AuditEntry],
    start_time: datetime,
) -> list[tuple[float, ActionEffect]]:
    """Extract all classified action effects from an audit log."""
    actions: list[tuple[float, ActionEffect]] = []
    for entry in audit_log:
        sig = _classify_action(entry)
        if sig is None:
            continue
        effect = ACTION_EFFECTS.get(sig)
        if effect is None:
            continue
        elapsed = (entry.timestamp - start_time).total_seconds() / 60.0
        actions.append((elapsed, effect))
    return actions


def actions_for_patient(
    audit_log: list[AuditEntry],
    patient_id: str,
    world: WorldState,
    start_time: datetime,
) -> list[tuple[float, ActionEffect]]:
    """Filter audit-log actions to those targeting ``patient_id``.

    Resolution order: (1) direct ``params.patient_id`` match; (2) match
    via ``params.encounter_id`` → patient lookup in the world. Entries
    that don't reference the patient are dropped.
    """
    relevant: list[AuditEntry] = []
    for entry in audit_log:
        if _classify_action(entry) is None:
            continue
        params = entry.params if isinstance(entry.params, dict) else {}
        if params.get("patient_id") == patient_id:
            relevant.append(entry)
            continue
        eid = params.get("encounter_id")
        if not eid:
            continue
        enc = world.get_entity("encounter", eid)
        if enc is None:
            continue
        if hasattr(enc, "patient_id"):
            enc_pid = enc.patient_id
        elif isinstance(enc, dict):
            enc_pid = enc.get("patient_id")
        else:
            enc_pid = None
        if enc_pid == patient_id:
            relevant.append(entry)
    return actions_from_audit_log(relevant, start_time)
