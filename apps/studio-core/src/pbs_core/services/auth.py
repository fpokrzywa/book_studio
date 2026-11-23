"""The studio account and its sign-in sessions.

* One studio has one account (the owner). It is created once, either in the browser with the
  one-time setup code Core writes to ``runtime/setup-code.txt`` (never to the log), or on the
  server's command line (``python -m pbs_core create-user``).
* A session is a random 256-bit token in an HttpOnly, SameSite=Strict cookie. Only its SHA-256
  hash is stored. Sessions end after ``session_idle_minutes`` without use or ``session_max_days``
  after sign-in, whichever comes first, and when the password changes.
* Every session has its own CSRF token, which the browser must echo in ``X-PBS-CSRF`` on every
  state-changing request (checked by the web guard, docs/SECURITY.md section 2).
* Failed sign-ins are slowed down per client address and per username (``LoginThrottle``).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, func, select

from pbs_core.context import AppContext
from pbs_core.contracts_auth import USERNAME_PATTERN, AuthStateOut
from pbs_core.domain.clock import to_iso
from pbs_core.domain.errors import (
    ConflictError,
    TooManyAttemptsError,
    UnauthorizedError,
    ValidationFailedError,
)
from pbs_core.security import passwords
from pbs_core.storage.auth_models import AuthSession, UserAccount
from pbs_core.storage.paths import atomic_write_bytes

log = structlog.get_logger(__name__)

SETUP_CODE_FILE = "setup-code.txt"
LAST_SEEN_GRANULARITY = timedelta(seconds=60)


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    session_id: str
    csrf_token: str
    expires_at: str


def cookie_name(ctx: AppContext) -> str:
    # The __Host- prefix makes browsers refuse the cookie unless it is Secure, host-only and Path=/.
    return "__Host-pbs_session" if ctx.settings.cookie_secure else "pbs_session"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def account_count(ctx: AppContext) -> int:
    with ctx.db.tx() as s:
        return int(s.scalar(select(func.count()).select_from(UserAccount)) or 0)


# ---------- setup code ----------
def ensure_setup_code(ctx: AppContext) -> bool:
    """While no account exists, keep a one-time setup code on disk. Returns True if setup is pending."""
    path = ctx.workspace.runtime_dir / SETUP_CODE_FILE
    if account_count(ctx):
        path.unlink(missing_ok=True)
        return False
    if not path.exists():
        atomic_write_bytes(path, secrets.token_urlsafe(18).encode("ascii"))
        if os.name != "nt":
            os.chmod(path, 0o600)
    log.warning("setup_required", setup_code_file=str(path), detail="create the studio account to start")
    return True


def _check_setup_code(ctx: AppContext, given: str) -> bool:
    path = ctx.workspace.runtime_dir / SETUP_CODE_FILE
    try:
        expected = path.read_text(encoding="ascii").strip()
    except OSError:
        return False
    return bool(expected) and hmac.compare_digest(expected.encode(), given.strip().encode("utf-8", "ignore"))


# ---------- throttle ----------
class LoginThrottle:
    """Failed attempts per key in a sliding window; after `limit` failures the key waits.

    Kept in memory: one web process serves the studio. A restart clears it, which only matters to
    an attacker who can also restart the server.
    """

    def __init__(self, limit: int = 5, window_s: float = 15 * 60, now: object = None) -> None:
        self.limit = limit
        self.window_s = window_s
        self._now = now or time.monotonic
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, *keys: str) -> int:
        now = self._now()  # type: ignore[operator]
        worst = 0.0
        with self._lock:
            for k in keys:
                recent = [t for t in self._fails.get(k, []) if now - t < self.window_s]
                self._fails[k] = recent
                if len(recent) >= self.limit:
                    worst = max(worst, self.window_s - (now - recent[-self.limit]))
        return int(worst) + (1 if worst else 0)

    def fail(self, *keys: str) -> None:
        now = self._now()  # type: ignore[operator]
        with self._lock:
            for k in keys:
                self._fails.setdefault(k, []).append(now)

    def clear(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._fails.pop(k, None)


_throttles: dict[int, LoginThrottle] = {}


def throttle(ctx: AppContext) -> LoginThrottle:
    return _throttles.setdefault(id(ctx), LoginThrottle())


# ---------- sessions ----------
def _new_session(ctx: AppContext, user: UserAccount, user_agent: str) -> tuple[str, Principal]:
    token = secrets.token_urlsafe(32)
    now = ctx.clock.now()
    row = AuthSession(
        id=ctx.ids.new(),
        user_id=user.id,
        token_hash=_hash_token(token),
        csrf_token=secrets.token_urlsafe(32),
        created_at=to_iso(now),
        last_seen_at=to_iso(now),
        expires_at=to_iso(now + timedelta(days=ctx.settings.session_max_days)),
        user_agent=user_agent[:160],
    )
    with ctx.db.tx() as s:
        s.add(row)
    return token, Principal(user.id, user.username, row.id, row.csrf_token, row.expires_at)


def authenticate(ctx: AppContext, token: str | None) -> Principal | None:
    """The signed-in account for a session cookie, or None. Expired sessions are deleted."""
    if not token or len(token) > 200:
        return None
    now = ctx.clock.now()
    idle = timedelta(minutes=ctx.settings.session_idle_minutes)
    with ctx.db.tx() as s:
        row = s.scalars(select(AuthSession).where(AuthSession.token_hash == _hash_token(token))).first()
        if row is None:
            return None
        user = s.get(UserAccount, row.user_id)
        if user is None or user.disabled or now >= _parse(row.expires_at) or now - _parse(row.last_seen_at) > idle:
            s.delete(row)
            return None
        if now - _parse(row.last_seen_at) > LAST_SEEN_GRANULARITY:
            row.last_seen_at = to_iso(now)
        return Principal(user.id, user.username, row.id, row.csrf_token, row.expires_at)


def state(ctx: AppContext, principal: Principal | None) -> AuthStateOut:
    return AuthStateOut(
        setup_required=principal is None and account_count(ctx) == 0,
        signed_in=principal is not None,
        username=principal.username if principal else None,
        csrf_token=principal.csrf_token if principal else None,
        session_expires_at=principal.expires_at if principal else None,
        deployment=ctx.settings.deployment,
        password_min_length=passwords.MIN_LENGTH,
    )


def _policy(password: str, username: str) -> None:
    try:
        passwords.check_policy(password, username)
    except passwords.PasswordPolicyError as exc:
        raise ValidationFailedError("Choose a different password.", detail=str(exc), extra={"reason": "weak"}) from exc


def _normalise(username: str) -> str:
    name = username.strip().lower()
    if not re.fullmatch(USERNAME_PATTERN, name):
        raise ValidationFailedError(
            "Usernames use 1 to 64 letters, digits, dots, dashes, underscores or @.", extra={"reason": "username"}
        )
    return name


def create_account(ctx: AppContext, username: str, password: str) -> UserAccount:
    """Create the one studio account. Refuses if an account already exists."""
    name = _normalise(username)
    _policy(password, name)
    hashed = passwords.hash_password(password)
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        if s.scalar(select(func.count()).select_from(UserAccount)):
            raise ConflictError(
                "This studio already has its account.",
                detail="Sign in instead. To regain access, reset the password on the server.",
                extra={"reason": "account_exists"},
            )
        user = UserAccount(id=ctx.ids.new(), username=name, password_hash=hashed, created_at=now,
                           password_changed_at=now)  # fmt: skip
        s.add(user)
    (ctx.workspace.runtime_dir / SETUP_CODE_FILE).unlink(missing_ok=True)
    log.info("account_created", username=name)
    return user


def setup(ctx: AppContext, username: str, password: str, code: str, user_agent: str) -> tuple[str, Principal]:
    if account_count(ctx):
        raise ConflictError("This studio already has its account.", extra={"reason": "account_exists"})
    t = throttle(ctx)
    if wait := t.retry_after("setup"):
        raise TooManyAttemptsError("Too many wrong setup codes. Try again later.", extra={"retry_after": wait})
    if not _check_setup_code(ctx, code):
        t.fail("setup")
        log.warning("setup_code_rejected")
        raise UnauthorizedError(
            "That setup code is not right.",
            detail="Copy it from runtime/setup-code.txt in the studio's data folder on the server.",
            extra={"reason": "bad_setup_code"},
        )
    user = create_account(ctx, username, password)
    return _new_session(ctx, user, user_agent)


def login(ctx: AppContext, username: str, password: str, client: str, user_agent: str) -> tuple[str, Principal]:
    name = username.strip().lower()
    keys = (f"ip:{client}", f"user:{name}")
    t = throttle(ctx)
    if wait := t.retry_after(*keys):
        log.warning("sign_in_throttled", client=client)
        raise TooManyAttemptsError(
            "Too many failed sign-ins. Wait a few minutes, then try again.", extra={"retry_after": wait}
        )
    with ctx.db.tx() as s:
        user = s.scalars(select(UserAccount).where(UserAccount.username == name)).first()
        stored = user.password_hash if user is not None and not user.disabled else passwords.DUMMY_HASH
    ok = passwords.verify_password(password, stored) and user is not None and not user.disabled
    if not ok or user is None:
        t.fail(*keys)
        log.warning("sign_in_failed", client=client)
        raise UnauthorizedError("That username and password do not match.", extra={"reason": "bad_credentials"})
    t.clear(*keys)
    log.info("signed_in", username=name)
    return _new_session(ctx, user, user_agent)


def logout(ctx: AppContext, principal: Principal) -> None:
    with ctx.db.tx() as s:
        s.execute(delete(AuthSession).where(AuthSession.id == principal.session_id))


def sign_out_others(ctx: AppContext, principal: Principal) -> int:
    with ctx.db.tx() as s:
        res = s.execute(
            delete(AuthSession).where(AuthSession.user_id == principal.user_id, AuthSession.id != principal.session_id)
        )
        return int(res.rowcount or 0)  # type: ignore[attr-defined]


def change_password(ctx: AppContext, principal: Principal, current: str, new: str) -> int:
    with ctx.db.tx() as s:
        user = s.get(UserAccount, principal.user_id)
        stored = user.password_hash if user else passwords.DUMMY_HASH
    if user is None or not passwords.verify_password(current, stored):
        raise UnauthorizedError("Your current password is not right.", extra={"reason": "bad_credentials"})
    _policy(new, user.username)
    hashed = passwords.hash_password(new)
    with ctx.db.tx() as s:
        row = s.get(UserAccount, principal.user_id)
        if row is None:
            raise UnauthorizedError("Sign in to continue.")
        row.password_hash, row.password_changed_at = hashed, ctx.clock.iso()
    log.info("password_changed", username=user.username)
    return sign_out_others(ctx, principal)


def reset_password(ctx: AppContext, username: str, new: str) -> None:
    """Server command line only: set a new password and end every session."""
    name = username.strip().lower()
    _policy(new, name)
    hashed = passwords.hash_password(new)
    with ctx.db.tx() as s:
        user = s.scalars(select(UserAccount).where(UserAccount.username == name)).first()
        if user is None:
            raise ValidationFailedError(f"There is no account called {name!r}.", extra={"reason": "no_account"})
        user.password_hash, user.password_changed_at = hashed, ctx.clock.iso()
        s.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    log.info("password_reset", username=name)


def remaining_seconds(principal: Principal, now: datetime) -> int:
    return max(0, int((_parse(principal.expires_at) - now).total_seconds()))
