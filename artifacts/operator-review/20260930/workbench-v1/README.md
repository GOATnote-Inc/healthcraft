# Offline operator workbench demonstration

These are additional views of six unchanged, exposed development assignments. No operator responses were imported and no models were called. The original issuer manifests and response importers remain authoritative.

Distribute only the `public/` directory within a chosen view. Open its `report.html`. Draft preview/apply/undo works locally; download responses to preserve work. There is no autosave, network service or activity timer.

| View | Cases | Original bytes | Workbench bytes | Original start tags | Workbench start tags |
|---|---:|---:|---:|---:|---:|
| native-raw | 4 | 2634986 | 243774 | 33433 | 988 |
| native-assisted | 4 | 2746793 | 375013 | 34507 | 1908 |
| model-raw | 3 | 21935273 | 3583528 | 171687 | 751 |
| model-assisted | 3 | 22040567 | 3709039 | 172697 | 1616 |
| synthetic-reviewer-a | 4 | 2693230 | 224669 | 34526 | 597 |
| synthetic-resolver | 1 | 889556 | 105402 | 11286 | 186 |

The table measures serialized UTF-8 bytes and HTMLParser start tags. It is not a browser speed, memory, visual-quality or intended-user study. Browser visual QA remains unavailable. The synthetic reviewer and resolver views retain software-authored demonstration declarations, not human review.

`receipt.json` records the six-view denominator, exact original packet/template byte identity, CLI verification, source hashes and original-artifact preservation. `commands/` retains the exact CLI argv and stdout/stderr. Each view has its own manifest. No frozen original artifact is replaced.

Reproduce in a fresh directory using the same recorded implementation and runtime:

```sh
/opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/bin/python3.14 /Users/kiteboard/healthcraft/artifacts/operator-review/20260930/workbench-v1/reproduce.py.txt --repo-root /Users/kiteboard/healthcraft --python /opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/bin/python3.14 --output-dir /private/tmp/healthcraft-workbench-reproduction
```

The destination must not exist or lie within an already sealed manifest inventory. The reproducibility script calls the real build and verify CLI for each view, then writes the outer manifest after all content is complete.
