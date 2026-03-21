# Contributing to HEALTHCRAFT

Thank you for your interest in contributing to HEALTHCRAFT.

## Getting Started

```bash
git clone https://github.com/GOATnote-Inc/healthcraft.git
cd healthcraft
pip install -e ".[dev]"
make test
```

## Development Workflow

1. Create a feature branch from `main`
2. Make your changes
3. Run `make lint` and `make test`
4. Open a pull request

## Code Style

- Python 3.10+
- Ruff for linting and formatting (line length 100)
- Type hints on all public functions
- Tests for all new functionality

## Clinical Accuracy

Tasks and entities involving clinical content must be reviewed for medical
accuracy. Use the `/review-clinical` workflow to request a clinical review.

All clinical content is synthetic and for training/evaluation purposes only.
HEALTHCRAFT is not a medical device and must not be used for clinical decision-making.

## Entity and Task Contributions

- Entity generators should produce deterministic output from a seed
- Tasks must include rubrics with score anchors for all 6 dimensions
- FHIR R4 compliance is required for all patient/encounter/condition entities
- Reference OpenEM conditions by `condition_id` where applicable

## Contributing Evaluation Results

We welcome evaluation results from models not yet tested. See
[Evaluate Your Model](docs/EVALUATE_YOUR_MODEL.md) for protocol and
submission instructions.

## Reporting Evaluation Issues

If you suspect an infrastructure bug in the evaluator, rubric criteria,
or tool implementations, please open an issue with:
- The task ID and criterion ID affected
- Expected vs. actual behavior
- Evidence (trajectory excerpt, audit log entry)

Evaluation integrity is a first-class concern. Every reported issue is
investigated and, if confirmed, corrected in a new evaluation version.

## License

By contributing, you agree that your contributions will be licensed under Apache 2.0.
