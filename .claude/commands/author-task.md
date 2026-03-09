# /author-task [category]

Design a clinical task with rubric and entity reference validation.

## Team
- **task-author** (opus): Design task scenario and rubric
- **clinical-reviewer** (opus): Validate clinical accuracy
- **entity-builder** (sonnet): Verify entity references exist

## Workflow
1. task-author designs task YAML in `configs/tasks/{category}/`
2. task-author creates rubric with score anchors for all 6 dimensions
3. clinical-reviewer validates medical accuracy and clinical plausibility
4. entity-builder verifies all referenced entities exist in world state

## Task YAML Schema
```yaml
id: "TASK-NNN"
category: information_retrieval|clinical_communication|clinical_reasoning|multi_step_workflows|temporal_reasoning|safety_critical_judgment
level: 1-5
title: "Short descriptive title"
description: "What the agent must accomplish"
initial_state: {...}  # World state snapshot
expected_tools: [...]  # Tools the agent should use
rubric: {...}  # 6-dimension scoring
```

## Validation
- [ ] Task ID is unique
- [ ] Category and level are appropriate
- [ ] All referenced entities exist
- [ ] Rubric covers all 6 dimensions with score anchors
- [ ] Clinical scenario is medically plausible
- [ ] Expected tool sequence is achievable
