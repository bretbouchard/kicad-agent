"""Test fixtures for tests/eval directory.

Eval tests are standalone and don't require the parent tests/conftest.py fixtures.
"""

import warnings
import pytest

# Ignore test module that contains non-test dataclasses
collect_ignore = ["testset.py"]

# Ignore PytestCollectionWarning for TestSet and TestCase (dataclasses that look like test classes)
warnings.filterwarnings("ignore", category=pytest.PytestCollectionWarning, module="tests.eval.test_volta_v2_harness")

# Ignore PytestUnraisableExceptionWarning from skidl library loading
# (skidl opens __init___sklib.py file handles that get GC'd after test exec;
# these are not real test failures, just leaked resources from the library)
warnings.filterwarnings("ignore", category=pytest.PytestUnraisableExceptionWarning)