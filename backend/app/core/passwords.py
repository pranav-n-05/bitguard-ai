import re

from app.core.errors import AppError

MIN_LEN = 12


def check_policy(password: str, email: str | None = None) -> None:
    problems = []
    if len(password) < MIN_LEN:
        problems.append(f"at least {MIN_LEN} characters")
    if len(password) > 256:
        problems.append("at most 256 characters")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        problems.append("at least three of: lowercase, uppercase, digit, symbol")
    if email and email.split("@")[0].lower() in password.lower():
        problems.append("must not contain the account name")
    if problems:
        raise AppError("Password does not meet policy: " + "; ".join(problems))
