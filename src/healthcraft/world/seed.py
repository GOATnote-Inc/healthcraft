"""Deterministic world seeding for the HEALTHCRAFT simulation."""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.world.state import WorldState


class WorldSeeder:
    """Generates a deterministic world state from a seed and configuration.

    All randomness flows through a seeded ``random.Random`` instance,
    ensuring reproducible world generation.
    """

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.rng = random.Random(seed)

    def seed_world(self, config_path: Path) -> WorldState:
        """Generate a complete world state from a configuration file.

        The config file is a JSON or YAML file specifying entity counts,
        condition distributions, and other generation parameters.

        Args:
            config_path: Path to the world seed configuration file.

        Returns:
            A fully populated WorldState.
        """
        config = self._load_config(config_path)
        start_time = self._parse_start_time(config)
        world = WorldState(start_time=start_time)

        # Generate entities in dependency order
        self._generate_staff(world, config)
        self._generate_locations(world, config)
        self._generate_patients(world, config)
        self._generate_encounters(world, config)

        # Generate domain entities (Corecraft entity graph)
        self._generate_clinical_knowledge(world, config)
        self._generate_protocols(world)
        self._generate_decision_rules(world)
        self._generate_supplies(world)
        self._generate_resources(world)
        self._generate_insurance(world)
        self._generate_treatment_plans(world)
        self._generate_clinical_tasks(world)
        self._generate_reference_materials(world)
        self._generate_regulatory(world)

        return world

    def _load_config(self, config_path: Path) -> dict[str, Any]:
        """Load configuration from JSON or YAML file."""
        suffix = config_path.suffix.lower()
        text = config_path.read_text(encoding="utf-8")

        if suffix in (".yaml", ".yml"):
            try:
                import yaml

                return yaml.safe_load(text)
            except ImportError:
                raise ImportError("PyYAML is required for YAML config files")
        elif suffix == ".json":
            return json.loads(text)
        else:
            raise ValueError(f"Unsupported config format: {suffix}")

    def _parse_start_time(self, config: dict[str, Any]) -> datetime:
        """Extract simulation start time from config."""
        start_str = config.get("start_time")
        if start_str:
            return datetime.fromisoformat(start_str)
        return datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)

    def _generate_staff(self, world: WorldState, config: dict[str, Any]) -> None:
        """Generate staff entities (attending physicians, nurses, etc.)."""
        staff_config = config.get("staff", {})
        count = staff_config.get("count", 8)

        first_names = ["James", "Sarah", "Michael", "Emily", "David", "Lisa", "Robert", "Maria"]
        last_names = ["Chen", "Rodriguez", "Park", "Williams", "Patel", "Johnson", "Kim", "Davis"]
        roles = [
            "attending",
            "resident",
            "nurse",
            "nurse",
            "attending",
            "nurse",
            "resident",
            "tech",
        ]

        for i in range(count):
            staff_id = f"STAFF-{i + 1:03d}"
            name_idx = i % len(first_names)
            staff = {
                "id": staff_id,
                "entity_type": EntityType.STAFF.value,
                "first_name": first_names[name_idx],
                "last_name": last_names[self.rng.randint(0, len(last_names) - 1)],
                "role": roles[i % len(roles)],
                "active": True,
            }
            world.put_entity(EntityType.STAFF.value, staff_id, staff)

    def _generate_locations(self, world: WorldState, config: dict[str, Any]) -> None:
        """Generate ED locations (beds, trauma bays, etc.)."""
        locations_config = config.get("locations", {})
        beds = locations_config.get("beds", 20)
        trauma_bays = locations_config.get("trauma_bays", 2)

        for i in range(beds):
            loc_id = f"BED-{i + 1:03d}"
            location = {
                "id": loc_id,
                "entity_type": EntityType.LOCATION.value,
                "name": f"Bed {i + 1}",
                "type": "bed",
                "zone": "main" if i < beds // 2 else "fast_track",
                "occupied": False,
            }
            world.put_entity(EntityType.LOCATION.value, loc_id, location)

        for i in range(trauma_bays):
            loc_id = f"TRAUMA-{i + 1:03d}"
            location = {
                "id": loc_id,
                "entity_type": EntityType.LOCATION.value,
                "name": f"Trauma Bay {i + 1}",
                "type": "trauma_bay",
                "zone": "trauma",
                "occupied": False,
            }
            world.put_entity(EntityType.LOCATION.value, loc_id, location)

    def _entity_config(self, config: dict[str, Any], key: str) -> dict[str, Any]:
        """Get entity generation config, checking entity_generation section first."""
        eg = config.get("entity_generation", {})
        if key in eg:
            return eg[key]
        return config.get(key, {})

    def _generate_patients(self, world: WorldState, config: dict[str, Any]) -> None:
        """Generate patient entities."""
        from healthcraft.entities.patients import generate_patient

        patients_config = self._entity_config(config, "patients")
        count = patients_config.get("count", 10)
        condition_ids = patients_config.get("condition_ids", [])

        for i in range(count):
            condition_id = condition_ids[i] if i < len(condition_ids) else None
            patient = generate_patient(self.rng, condition_id=condition_id)
            world.put_entity(EntityType.PATIENT.value, patient.id, patient)

    def _generate_encounters(self, world: WorldState, config: dict[str, Any]) -> None:
        """Generate encounter entities for existing patients."""
        from healthcraft.entities.encounters import generate_encounter
        from healthcraft.world.timeline import SimulationClock

        encounters_config = config.get("encounters", {})
        auto_generate = encounters_config.get("auto_generate", True)

        if not auto_generate:
            return

        clock = SimulationClock(start_time=world.timestamp)
        patients = world.list_entities(EntityType.PATIENT.value)

        for patient_id, patient in patients.items():
            encounter = generate_encounter(
                rng=self.rng,
                patient=patient,
                condition_id=None,
                clock=clock,
            )
            world.put_entity(EntityType.ENCOUNTER.value, encounter.id, encounter)

    def _generate_clinical_knowledge(self, world: WorldState, config: dict[str, Any]) -> None:
        """Load clinical knowledge entities into world state."""
        from healthcraft.entities.clinical_knowledge import load_clinical_knowledge

        knowledge = load_clinical_knowledge()
        for ck_id, ck in knowledge.items():
            world.put_entity(EntityType.CLINICAL_KNOWLEDGE.value, ck.id, ck)

    def _generate_protocols(self, world: WorldState) -> None:
        """Load protocol entities into world state."""
        from healthcraft.entities.protocols import load_protocols

        for proto_id, proto in load_protocols().items():
            world.put_entity(EntityType.PROTOCOL.value, proto.id, proto)

    def _generate_decision_rules(self, world: WorldState) -> None:
        """Load decision rule entities into world state."""
        from healthcraft.entities.decision_rules import load_decision_rules

        for rule_id, rule in load_decision_rules().items():
            world.put_entity(EntityType.DECISION_RULE.value, rule.id, rule)

    def _generate_supplies(self, world: WorldState) -> None:
        """Load supply entities into world state."""
        from healthcraft.entities.supplies import load_supplies

        for supply_id, supply in load_supplies().items():
            world.put_entity(EntityType.SUPPLY.value, supply.id, supply)

    def _generate_resources(self, world: WorldState) -> None:
        """Generate ED resource entities."""
        from healthcraft.entities.resources import generate_ed_resources

        for resource in generate_ed_resources(self.rng):
            world.put_entity(EntityType.RESOURCE.value, resource.id, resource)

    def _generate_insurance(self, world: WorldState) -> None:
        """Generate insurance entities for each patient."""
        from healthcraft.entities.insurance import generate_insurance

        patients = world.list_entities(EntityType.PATIENT.value)
        for patient_id, patient in patients.items():
            ins = generate_insurance(self.rng, patient_id)
            world.put_entity(EntityType.INSURANCE.value, ins.id, ins)

    def _generate_treatment_plans(self, world: WorldState) -> None:
        """Generate treatment plans for encounters."""
        from healthcraft.entities.treatment_plans import generate_treatment_plan

        encounters = world.list_entities(EntityType.ENCOUNTER.value)
        knowledge = world.list_entities(EntityType.CLINICAL_KNOWLEDGE.value)
        condition_ids = [
            ck.condition_id for ck in knowledge.values() if hasattr(ck, "condition_id")
        ]

        for enc_id, enc in encounters.items():
            patient_id = enc.patient_id if hasattr(enc, "patient_id") else ""
            condition_ref = self.rng.choice(condition_ids) if condition_ids else ""
            plan = generate_treatment_plan(self.rng, enc_id, patient_id, condition_ref)
            world.put_entity(EntityType.TREATMENT_PLAN.value, plan.id, plan)

    def _generate_clinical_tasks(self, world: WorldState) -> None:
        """Generate clinical tasks for encounters."""
        from healthcraft.entities.clinical_tasks import generate_clinical_task

        encounters = world.list_entities(EntityType.ENCOUNTER.value)
        task_types = (
            "lab_draw",
            "imaging",
            "medication_admin",
            "procedure",
            "consult",
            "nursing",
        )

        for enc_id in encounters:
            # Generate 2-5 tasks per encounter
            num_tasks = self.rng.randint(2, 5)
            for _ in range(num_tasks):
                task_type = self.rng.choice(task_types)
                task = generate_clinical_task(self.rng, enc_id, task_type)
                world.put_entity(EntityType.CLINICAL_TASK.value, task.id, task)

    def _generate_reference_materials(self, world: WorldState) -> None:
        """Load reference material entities into world state."""
        from healthcraft.entities.reference_materials import load_reference_materials

        for ref_id, ref in load_reference_materials().items():
            world.put_entity(EntityType.REFERENCE_MATERIAL.value, ref.id, ref)

    def _generate_regulatory(self, world: WorldState) -> None:
        """Load regulatory entities into world state."""
        from healthcraft.entities.regulatory import load_regulations

        for reg_id, reg in load_regulations().items():
            world.put_entity(EntityType.REGULATORY.value, reg.id, reg)
