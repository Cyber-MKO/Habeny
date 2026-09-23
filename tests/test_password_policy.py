import pytest

from app.services.password_policy import password_problems


@pytest.mark.parametrize("password,username", [
    ("short-pass", "alice"),          # too short
    ("Password123!", "alice"),        # common, with the usual suffix
    ("qwertyuiop", "alice"),          # common (and short)
    ("alice-is-great-2026", "alice"),  # contains the username
    ("aaaaaaaaaaaaaaa", "alice"),      # one repeated character
    ("Welcome1234", "bob"),           # common + short
])
def test_rejected(password, username):
    assert password_problems(password, username)


@pytest.mark.parametrize("password", ["mauve-harbor-kettle-41", "Tr0ub4dor&3-horse!", "2026 is the year of LXC"])
def test_accepted(password):
    assert password_problems(password, "alice") == []
