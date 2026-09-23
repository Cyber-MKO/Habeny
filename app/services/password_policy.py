"""
Password rules for new passwords (setup, new users, changes, resets). Existing
passwords keep working; the rules apply the next time one is set.
"""
from app import config

MIN_LENGTH = config.get("HABENY_PASSWORD_MIN_LENGTH")
MAX_LENGTH = 256

# Frequently breached passwords (and obvious product-specific ones), compared case-insensitively
COMMON_PASSWORDS = {
    "123456", "123456789", "12345678", "1234567890", "12345", "1234567", "123123", "111111", "000000",
    "password", "password1", "password12", "password123", "password1234", "passw0rd", "p@ssw0rd", "p@ssword",
    "qwerty", "qwerty123", "qwertyuiop", "qwerty12345", "1q2w3e4r", "1q2w3e4r5t", "1qaz2wsx", "zaq12wsx",
    "abc123", "abcd1234", "abcdef123", "iloveyou", "letmein", "letmein123", "welcome", "welcome1",
    "welcome123", "admin", "admin123", "admin1234", "administrator", "root", "toor", "changeme",
    "changeme123", "default", "secret", "secret123", "monkey", "dragon", "football", "baseball",
    "sunshine", "princess", "master", "superman", "batman", "trustno1", "shadow", "michael", "jennifer",
    "hunter2", "starwars", "whatever", "freedom", "login", "access", "passpass", "test", "test123",
    "test1234", "testing123", "guest", "user", "user123", "operator", "support", "security", "siem",
    "wazuh", "wazuh123", "elastic", "changeit", "habeny", "habeny123", "lxc", "container",
    "correcthorsebatterystaple", "aaaaaaaaaaaa", "qazwsxedcrfv", "asdfghjkl", "zxcvbnm", "11111111",
    "00000000", "987654321", "123321", "654321", "666666", "121212", "112233", "q1w2e3r4t5y6",
}


def password_problems(password: str, username: str = "") -> list[str]:
    """Human-readable reasons a new password is not acceptable (empty list: OK)."""
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append(f"at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        problems.append(f"at most {MAX_LENGTH} characters")
    lowered = password.lower()
    stripped = lowered.rstrip("0123456789!@#$%^&*.?")  # "Password123!" is still "password"
    if lowered in COMMON_PASSWORDS or stripped in COMMON_PASSWORDS:
        problems.append("not a commonly used password")
    if username and len(username) >= 3 and username.lower() in lowered:
        problems.append("must not contain the username")
    if password and len(set(password)) == 1:
        problems.append("not a single repeated character")
    return problems


def enforce_password_policy(password: str, username: str = "") -> None:
    """For routes: reject a password that breaks the rules with HTTP 400."""
    from fastapi import HTTPException, status
    problems = password_problems(password, username)
    if problems:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Password must be " + "; ".join(problems) + ".")


def check_password(password: str, username: str = "") -> None:
    """Raise ValueError with a readable message if the password breaks the rules."""
    problems = password_problems(password, username)
    if problems:
        raise ValueError("Password must be " + "; ".join(problems) + ".")
