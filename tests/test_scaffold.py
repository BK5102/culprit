"""The scaffold works: the package and the shared Cleanroom both import."""

import culprit


def test_package_imports():
    assert culprit.__version__


def test_cleanroom_imports_from_the_git_tag():
    import cleanroom
    from cleanroom import lock, split

    assert cleanroom.__version__.startswith("0.")
    assert hasattr(split, "Split")
    assert hasattr(lock, "require_lock")
