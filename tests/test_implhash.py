"""Impl hash stability: formatting/comments/docstrings must not change the
hash; logic changes must."""

import pytest

from hashloom.errors import HashloomError
from hashloom import implhash  # test_source_hash via module: a bare `test_*` import would be collected as a test
from hashloom.implhash import impl_hash

BASE = '''
def total(items):
    """Sum the ok items."""
    # only the ok ones count
    return sum(i.value for i in items if i.ok)
'''


def write_and_hash(tmp_path, source: str) -> str:
    (tmp_path / "mod.py").write_text(source)
    return impl_hash(tmp_path, "mod.py::total")


def test_identical_source_same_hash(tmp_path):
    assert write_and_hash(tmp_path, BASE) == write_and_hash(tmp_path, BASE)


def test_comments_do_not_change_hash(tmp_path):
    a = write_and_hash(tmp_path, BASE)
    b = write_and_hash(tmp_path, BASE.replace("    # only the ok ones count\n", ""))
    assert a == b


def test_docstring_does_not_change_hash(tmp_path):
    a = write_and_hash(tmp_path, BASE)
    b = write_and_hash(tmp_path, BASE.replace('"""Sum the ok items."""', '"""Different docstring."""'))
    assert a == b


def test_formatting_does_not_change_hash(tmp_path):
    a = write_and_hash(tmp_path, BASE)
    reformatted = '''
def total(items):
    """Sum the ok items."""
    return sum(
        i.value
        for i in items
        if i.ok
    )
'''
    assert a == write_and_hash(tmp_path, reformatted)


def test_surrounding_code_does_not_change_hash(tmp_path):
    a = write_and_hash(tmp_path, BASE)
    b = write_and_hash(tmp_path, "import os\n\nUNRELATED = 1\n" + BASE)
    assert a == b


def test_logic_change_changes_hash(tmp_path):
    a = write_and_hash(tmp_path, BASE)
    b = write_and_hash(tmp_path, BASE.replace("if i.ok", "if not i.ok"))
    assert a != b


def test_class_and_method_resolution(tmp_path):
    (tmp_path / "mod.py").write_text(
        "class Calc:\n    def total(self, items):\n        return sum(items)\n"
    )
    assert impl_hash(tmp_path, "mod.py::Calc") != impl_hash(tmp_path, "mod.py::Calc.total")


def test_missing_function_raises(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    with pytest.raises(HashloomError) as exc:
        impl_hash(tmp_path, "mod.py::nope")
    assert exc.value.code == "impl_not_found"


def test_missing_file_raises(tmp_path):
    with pytest.raises(HashloomError) as exc:
        impl_hash(tmp_path, "absent.py::f")
    assert exc.value.code == "impl_not_found"


def test_syntax_error_raises(tmp_path):
    (tmp_path / "mod.py").write_text("def broken(:\n")
    with pytest.raises(HashloomError) as exc:
        impl_hash(tmp_path, "mod.py::broken")
    assert exc.value.code == "impl_syntax_error"


# --- test_source_hash: same normalised-AST stability, for the verification key ---


def _twrite(tmp_path, body: str):
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "t.py").write_text(body)


def test_test_source_hash_ignores_formatting_and_comments(tmp_path):
    _twrite(tmp_path, "def test_a():\n    assert 1 == 1\n")
    a = implhash.test_source_hash(tmp_path, ["tests/t.py::test_a"])
    _twrite(tmp_path, "def test_a():\n    # a comment\n    assert 1 ==  1\n")
    assert a == implhash.test_source_hash(tmp_path, ["tests/t.py::test_a"])


def test_test_source_hash_changes_on_body_change(tmp_path):
    _twrite(tmp_path, "def test_a():\n    assert 1 == 1\n")
    a = implhash.test_source_hash(tmp_path, ["tests/t.py::test_a"])
    _twrite(tmp_path, "def test_a():\n    assert 1 == 2\n")
    assert a != implhash.test_source_hash(tmp_path, ["tests/t.py::test_a"])


def test_test_source_hash_is_order_independent(tmp_path):
    _twrite(tmp_path, "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n")
    h1 = implhash.test_source_hash(tmp_path, ["tests/t.py::test_a", "tests/t.py::test_b"])
    h2 = implhash.test_source_hash(tmp_path, ["tests/t.py::test_b", "tests/t.py::test_a"])
    assert h1 == h2


def test_test_source_hash_unresolvable_id_does_not_raise(tmp_path):
    h = implhash.test_source_hash(tmp_path, ["tests/absent.py::test_x"])
    assert isinstance(h, str) and len(h) == 64


def test_test_source_hash_resolves_parametrised_id(tmp_path):
    _twrite(tmp_path, "def test_a():\n    assert 1\n")
    before = implhash.test_source_hash(tmp_path, ["tests/t.py::test_a[case1]"])
    _twrite(tmp_path, "def test_a():\n    assert 2\n")
    # the [case1] suffix is stripped and the function body hashed, so it changed
    assert before != implhash.test_source_hash(tmp_path, ["tests/t.py::test_a[case1]"])
