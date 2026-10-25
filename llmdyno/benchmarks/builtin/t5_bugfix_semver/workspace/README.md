# semverlite

Small, dependency-free semantic versioning for Python: parsing, precedence and npm-style ranges.

```python
from semverlite import parse, satisfies, max_satisfying

parse("1.2.3-rc.1") < parse("1.2.3")          # True
satisfies("1.4.2", "^1.2.0")                   # True
max_satisfying(["1.2.3", "1.4.0"], "~1.2.0")   # Version(1, 2, 3)
```

Run the tests with `pytest -q`.
