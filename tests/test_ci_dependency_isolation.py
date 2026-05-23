"""CI/offline test dependency isolation invariants."""

import sys


def test_offline_tests_use_akshare_test_double():
    """Offline tests must not import the real akshare package."""
    akshare = sys.modules.get("akshare")
    assert akshare is not None
    assert getattr(akshare, "__manmankan_test_double__", False) is True
