# /review-clinical [target]

Clinical accuracy review of entities, tasks, or rubrics.

## Team
- **clinical-reviewer** (opus): Primary reviewer
- **task-author** (opus): Context provider for task design rationale

## Workflow
1. clinical-reviewer reads the target file(s)
2. Checks against OpenEM source data for condition accuracy
3. Validates:
   - Medical terminology
   - Clinical plausibility of scenarios
   - Correct drug dosing and interactions
   - Appropriate time constraints
   - Decision rule parameters
   - Confusion pair accuracy (conditions that look similar but require different treatment)
4. Produces review with [APPROVED] or [CHANGES REQUESTED] and specific items

## Review Checklist
- [ ] Condition presentation matches OpenEM data
- [ ] Drug doses are within safe ranges
- [ ] Time constraints are evidence-based
- [ ] Decision rules use correct parameters and thresholds
- [ ] Confusion pairs are clinically accurate
- [ ] No treatment would cause harm to a real patient if followed
- [ ] ESI levels match clinical acuity
