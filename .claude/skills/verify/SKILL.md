---
name: verify
description: Run full test suite to verify all changes pass before marking work done.
---

Run the project's test suite from the repository root:

```bash
python -m pytest -v
```

If any tests fail, report the failures and fix them before declaring success. Do not skip or ignore failing tests.
