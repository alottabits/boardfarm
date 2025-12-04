# Pattern Detection Tests

This directory contains unit tests for the URL pattern detection feature in `ui_discovery.py`.

## Running the Tests

These are standalone unit tests for the `URLPatternDetector` class. Run them from the **boardfarm** directory:

```bash
cd ~/projects/req-tst/boardfarm
source ../boardfarm-bdd/.venv-3.12/bin/activate
python -m pytest unittests/lib/gui/test_pattern_detection.py -v
```

Or run all GUI unit tests:

```bash
cd ~/projects/req-tst/boardfarm
source ../boardfarm-bdd/.venv-3.12/bin/activate
python -m pytest unittests/lib/gui/ -v
```

## Test Coverage

The tests cover:
- Simple device ID pattern detection
- Pattern threshold filtering
- Multiple pattern detection
- GenieACS-style device patterns
- Page structure extraction
- Path-based vs hash-based routing
- Custom minimum pattern counts
