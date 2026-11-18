"""Test-wide settings. Per-officer request limits (ADR-0039) are raised for the suites that drive
many requests as one officer; `test_hardening.py` tests the limits with their own low values."""

import os

os.environ.setdefault("C2_RATE_MODEL_PER_MINUTE", "100000")
os.environ.setdefault("C2_RATE_ANY_PER_MINUTE", "100000")
