"""Checks for the filesystem trust boundary."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from figma_parity.config import ConfigError, Settings  # noqa: E402


def _settings(roots):
    return Settings(api_key="test", allowed_roots=[Path(r).resolve() for r in roots])


def test_path_inside_root_is_accepted():
    with tempfile.TemporaryDirectory() as root:
        sub = Path(root) / "myapp"
        sub.mkdir()
        s = _settings([root])
        assert s.validate_project_path(sub) == sub.resolve()
        assert s.validate_project_path(root) == Path(root).resolve()


def test_path_outside_root_is_refused():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
        s = _settings([root])
        try:
            s.validate_project_path(other)
        except ConfigError:
            return
        raise AssertionError("path outside the allowed roots must be refused")


def test_dotdot_traversal_cannot_escape():
    with tempfile.TemporaryDirectory() as root:
        sub = Path(root) / "myapp"
        sub.mkdir()
        s = _settings([sub])
        try:
            s.validate_project_path(str(sub / ".." / ".."))
        except ConfigError:
            return
        raise AssertionError("`..` traversal must not escape the allowed root")


def test_empty_allowlist_refuses_everything():
    with tempfile.TemporaryDirectory() as d:
        s = Settings(api_key="test", allowed_roots=[])
        try:
            s.validate_project_path(d)
        except ConfigError:
            return
        raise AssertionError("an empty allowlist must refuse, not allow")


def test_nonexistent_directory_is_refused():
    with tempfile.TemporaryDirectory() as root:
        s = _settings([root])
        try:
            s.validate_project_path(Path(root) / "does-not-exist")
        except ConfigError:
            return
        raise AssertionError("a nonexistent path must be refused")


def test_missing_api_key_raises_a_useful_error():
    s = Settings(api_key=None, allowed_roots=[])
    try:
        s.require_api_key()
    except ConfigError as e:
        assert ".env" in str(e)
        return
    raise AssertionError("missing key must raise")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
