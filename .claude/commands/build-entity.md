# /build-entity [type]

Build an entity type with FHIR compliance and clinical review.

## Team
- **entity-builder** (sonnet): Implement entity generator module
- **openem-integrator** (sonnet): Wire OpenEM data sources
- **clinical-reviewer** (opus): Validate clinical accuracy

## Workflow
1. entity-builder creates `src/healthcraft/entities/{type}.py` with:
   - Frozen dataclass for the entity
   - Generator function accepting `random.Random` for determinism
   - FHIR R4 resource generation (where applicable)
   - Schema validation
2. openem-integrator connects to OpenEM data (condition_map, confusion_pairs, etc.)
3. entity-builder writes tests in `tests/test_entities/test_{type}.py`
4. clinical-reviewer validates medical accuracy of generated entities

## Validation
- [ ] Entity generates deterministically from seed
- [ ] FHIR R4 schema validation passes (if applicable)
- [ ] Referential integrity with other entity types
- [ ] Clinical accuracy confirmed by reviewer
- [ ] Tests pass
