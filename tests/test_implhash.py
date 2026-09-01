"""Impl hash stability: formatting/comments/docstrings must not change the
hash; logic changes must."""

import hashlib

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


# --- the fixture closure: conftest fixtures are part of the test-source hash ---


def _cwrite(tmp_path, body: str, where: str = "tests"):
    d = tmp_path / where if where else tmp_path
    d.mkdir(parents=True, exist_ok=True)
    (d / "conftest.py").write_text(body)


_NID = "tests/t.py::test_a"


def test_fixture_body_change_busts_the_test_source_hash(tmp_path):
    _twrite(tmp_path, "def test_a(numbers):\n    assert sum(numbers) == 3\n")
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [1, 2]\n")
    base = implhash.test_source_hash(tmp_path, [_NID])
    # comment/docstring-only fixture edit: no bust
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    '''doc'''\n    # same value\n    return [1, 2]\n")
    assert implhash.test_source_hash(tmp_path, [_NID]) == base
    # unrelated def in the same conftest: no bust (closure, not whole file)
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [1, 2]\n\ndef helper():\n    return 7\n")
    assert implhash.test_source_hash(tmp_path, [_NID]) == base
    # fixture body change: bust
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [2, 1]\n")
    assert implhash.test_source_hash(tmp_path, [_NID]) != base


def test_fixtureless_tests_keep_their_prefixture_hash_shape(tmp_path):
    # builtins (tmp_path) resolve to no project fixture, so the hash part is
    # byte-identical to the pre-coverage format: no upgrade wave for these
    _twrite(tmp_path, "def test_a(tmp_path):\n    assert tmp_path\n")
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef unused():\n    return 1\n")
    expected = hashlib.sha256(
        f"{_NID}={implhash._hash_def(tmp_path, 'tests/t.py', 'test_a')}".encode()
    ).hexdigest()
    assert implhash.test_source_hash(tmp_path, [_NID]) == expected


def test_dynamic_fixture_use_degrades_to_whole_chain(tmp_path):
    # a fixture name no static walk can see: hash the whole module + conftest
    # chain, so ANY edit there busts — over-sensitive, never under-sensitive
    _twrite(
        tmp_path,
        "def test_a(request):\n    name = 'num' + 'bers'\n"
        "    assert sum(request.getfixturevalue(name)) == 3\n",
    )
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [1, 2]\n")
    base = implhash.test_source_hash(tmp_path, [_NID])
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [1, 2]\n\ndef unrelated():\n    return 7\n")
    assert implhash.test_source_hash(tmp_path, [_NID]) != base


def test_fixture_of_fixture_is_in_the_closure(tmp_path):
    _twrite(tmp_path, "def test_a(numbers):\n    assert sum(numbers) == 3\n")
    _cwrite(
        tmp_path,
        "import pytest\n\n@pytest.fixture\ndef seed():\n    return [1, 2]\n\n"
        "@pytest.fixture\ndef numbers(seed):\n    return list(seed)\n",
    )
    base = implhash.test_source_hash(tmp_path, [_NID])
    _cwrite(
        tmp_path,
        "import pytest\n\n@pytest.fixture\ndef seed():\n    return [2, 1]\n\n"
        "@pytest.fixture\ndef numbers(seed):\n    return list(seed)\n",
    )
    assert implhash.test_source_hash(tmp_path, [_NID]) != base


def test_autouse_fixture_is_in_the_closure_without_being_requested(tmp_path):
    _twrite(tmp_path, "def test_a():\n    assert 1\n")
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture(autouse=True)\ndef env():\n    return 1\n")
    base = implhash.test_source_hash(tmp_path, [_NID])
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture(autouse=True)\ndef env():\n    return 2\n")
    assert implhash.test_source_hash(tmp_path, [_NID]) != base


def test_nearest_fixture_wins_and_shadowed_one_is_ignored(tmp_path):
    _twrite(tmp_path, "def test_a(numbers):\n    assert sum(numbers) == 3\n")
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [1, 2]\n")
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [3]\n", where="")
    base = implhash.test_source_hash(tmp_path, [_NID])
    # the root-level fixture is shadowed by tests/conftest.py: editing it is inert
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [4]\n", where="")
    assert implhash.test_source_hash(tmp_path, [_NID]) == base
    # the nearest one is live
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef numbers():\n    return [2, 1]\n")
    assert implhash.test_source_hash(tmp_path, [_NID]) != base


def test_usefixtures_mark_pulls_the_fixture_into_the_closure(tmp_path):
    _twrite(
        tmp_path,
        "import pytest\n\n@pytest.mark.usefixtures('env')\ndef test_a():\n    assert 1\n",
    )
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef env():\n    return 1\n")
    base = implhash.test_source_hash(tmp_path, [_NID])
    _cwrite(tmp_path, "import pytest\n\n@pytest.fixture\ndef env():\n    return 2\n")
    assert implhash.test_source_hash(tmp_path, [_NID]) != base
