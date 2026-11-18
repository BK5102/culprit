"""The scaffold works: the package and the shared Cleanroom both import."""

import culprit


def test_package_imports():
    assert culprit.__version__


def test_cleanroom_imports_from_the_git_tag():
    import cleanroom
    from cleanroom import events, guard, lock, split, vault

    assert cleanroom.__version__ == "0.2.0"
    assert hasattr(split, "Split")
    assert hasattr(lock, "require_lock")
    assert hasattr(events, "threshold_for_alarm_rate")
    assert hasattr(vault, "release_answer_key")
    assert hasattr(guard, "sealed_run")
