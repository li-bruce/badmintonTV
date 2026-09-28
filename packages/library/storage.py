"""Conservative, process-safe storage reservations for the library owner.

All library writers must share this ledger. Existing files and the *full* value
of active reservations are counted together: deliberate double counting trades
some utilization for safety. Reservations left by a killed process never expire.
The ledger must not be shared between Windows and WSL SQLite processes.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import sqlite3
import stat
from typing import Iterator
import uuid


OWNER_LIMIT_BYTES = 300_000_000_000
PROJECT_LIMIT_BYTES = 700_000_000_000
OTHER_OWNER_LIMITS = {
    "platform": 60_000_000_000,
    "models": 180_000_000_000,
    "render": 40_000_000_000,
    "runtime": 70_000_000_000,
}
DEFAULT_PROJECT_ROOT = Path("D:/video" if os.name == "nt" else "/mnt/d/video")
DEFAULT_DATA_ROOT = DEFAULT_PROJECT_ROOT / "data"


class StorageError(RuntimeError):
    """A storage invariant could not be satisfied."""


class QuotaExceeded(StorageError):
    """The owner, project, or physical disk has insufficient capacity."""


class UnsafePath(StorageError):
    """A path escapes its owner or includes a symbolic link/junction."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _check_ancestors(path: Path) -> None:
    # Check the lexical path, not just resolve(): resolve would hide a link.
    for current in (path, *path.parents):
        if _is_link(current):
            raise UnsafePath(f"Symbolic links and junctions are not allowed: {current}")


def directory_bytes(root: Path | str) -> int:
    """Count every regular file, including dotfiles and partial downloads.

    Links and filesystem errors fail closed instead of silently hiding storage.
    Hard links count once per name, which is intentionally conservative.
    """
    root = Path(root)
    _check_ancestors(root)
    if not root.exists():
        return 0
    total = 0

    def fail(error: OSError) -> None:
        raise error

    for current, directories, files in os.walk(root, followlinks=False, onerror=fail):
        for name in directories:
            child = Path(current) / name
            if _is_link(child):
                raise UnsafePath(f"Cannot account for a linked directory: {child}")
        for name in files:
            child = Path(current) / name
            try:
                information = child.lstat()
            except FileNotFoundError:
                # Other owners may atomically rename files during this scan.
                # Fixed disjoint owner budgets are the project-wide guarantee.
                continue
            if _is_link(child) or not stat.S_ISREG(information.st_mode):
                raise UnsafePath(f"Cannot account for a non-regular file: {child}")
            total += information.st_size
    return total


@dataclass(frozen=True)
class CapacitySnapshot:
    owner_used_bytes: int
    project_used_bytes: int
    active_reserved_bytes: int
    free_bytes: int
    owner_limit_bytes: int
    project_limit_bytes: int
    min_free_bytes: int
    opaque_project_owners: list[str]
    project_accounting: dict


@dataclass
class Reservation:
    quota: "QuotaManager"
    reservation_id: str
    peak_bytes: int
    released: bool = False

    def release(self, reason: str = "completed") -> None:
        if not self.released:
            self.quota.release(self.reservation_id, reason=reason)
            self.released = True

    def __enter__(self) -> "Reservation":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release("failed" if exc_type else "completed")


class QuotaManager:
    """Guard D:/video/data (or an explicitly opted-in temporary test root).

    Owner limits may be lowered, never raised past their fixed allocation. The
    project scan adds a guard; independent owners must still obey their own
    fixed budgets, since they do not participate in this library-only ledger.
    """

    def __init__(
        self,
        data_root: Path | str = DEFAULT_DATA_ROOT,
        *,
        project_root: Path | str | None = None,
        owner_limit_bytes: int = OWNER_LIMIT_BYTES,
        project_limit_bytes: int = PROJECT_LIMIT_BYTES,
        min_free_bytes: int = 1_000_000_000,
        allow_test_root: bool = False,
    ) -> None:
        for name, value, upper in (
            ("owner_limit_bytes", owner_limit_bytes, OWNER_LIMIT_BYTES),
            ("project_limit_bytes", project_limit_bytes, PROJECT_LIMIT_BYTES),
        ):
            if type(value) is not int or not 0 < value <= upper:
                raise ValueError(f"{name} must be an integer in 1..{upper}")
        if type(min_free_bytes) is not int or min_free_bytes < 0:
            raise ValueError("min_free_bytes must be a nonnegative integer")
        self.data_root = Path(os.path.abspath(data_root))
        self.project_root = Path(os.path.abspath(project_root or self.data_root.parent))
        if self.data_root != self.project_root / "data":
            raise UnsafePath("The library owner must be the project's data directory")
        if not allow_test_root and self.data_root != Path(os.path.abspath(DEFAULT_DATA_ROOT)):
            raise UnsafePath("Production data must live in D:/video/data or /mnt/d/video/data")
        _check_ancestors(self.data_root)
        self.owner_limit_bytes = owner_limit_bytes
        self.project_limit_bytes = project_limit_bytes
        self.min_free_bytes = min_free_bytes
        self.data_root.mkdir(parents=True, exist_ok=True)
        _check_ancestors(self.data_root)
        self.ledger_path = self.data_root / ".library-quota.sqlite3"
        _check_ancestors(self.ledger_path)
        with self._transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS reservations ("
                "reservation_id TEXT PRIMARY KEY, peak_bytes INTEGER NOT NULL, "
                "purpose TEXT NOT NULL, pid INTEGER NOT NULL, created_at TEXT NOT NULL, "
                "released_at TEXT, release_reason TEXT)"
            )
            connection.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            identity = f"{os.name}:{os.path.normcase(str(self.data_root))}"
            connection.execute("INSERT OR IGNORE INTO metadata VALUES ('runtime_root', ?)", (identity,))
            stored = connection.execute("SELECT value FROM metadata WHERE key='runtime_root'").fetchone()[0]
            if stored != identity:
                raise StorageError("Quota ledger belongs to another runtime/root; do not mix Windows and WSL")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        _check_ancestors(self.ledger_path)
        connection = sqlite3.connect(self.ledger_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def resolve_path(self, relative_path: Path | str) -> Path:
        """Validate a relative owner path, rejecting links and Windows aliases."""
        value = str(relative_path).replace("\\", "/")
        posix, windows = PurePosixPath(value), PureWindowsPath(value)
        if not value or posix.is_absolute() or windows.is_absolute() or windows.drive:
            raise UnsafePath("A relative path under the library data directory is required")
        if any(part in ("", ".", "..") for part in value.split("/")):
            raise UnsafePath("Empty, dot, and parent path components are forbidden")
        if any(":" in part or part.endswith((" ", ".")) for part in posix.parts):
            raise UnsafePath("Alternate streams and ambiguous path components are forbidden")
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
        if any(part.split(".")[0].upper() in reserved for part in posix.parts):
            raise UnsafePath("Windows device names are forbidden")
        result = self.data_root.joinpath(*posix.parts)
        _check_ancestors(result)
        if not result.resolve().is_relative_to(self.data_root.resolve()):
            raise UnsafePath("Path escapes library data directory")
        return result

    def _snapshot(self, connection: sqlite3.Connection) -> CapacitySnapshot:
        reserved = connection.execute(
            "SELECT COALESCE(SUM(peak_bytes), 0) FROM reservations WHERE released_at IS NULL"
        ).fetchone()[0]
        owner_used = directory_bytes(self.data_root)
        project_used, opaque, accounting = self._project_usage(owner_used)
        return CapacitySnapshot(
            owner_used, project_used, reserved,
            shutil.disk_usage(self.data_root).free, self.owner_limit_bytes,
            self.project_limit_bytes, self.min_free_bytes, opaque, accounting,
        )

    def _project_usage(self, owner_used: int) -> tuple[int, list[str], dict]:
        """Count opaque *other* owners at their entire fixed allocation.

        WSL runtime symlinks can be unreadable from Windows (WinError 1920).
        Never follow them or treat them as zero. When any part of a known
        foreign owner cannot be measured safely, substitute that owner's whole
        allocated upper bound. This relies on the fixed disjoint quotas in
        EXECUTION_PLAN, and remains visible in every capacity snapshot. The data
        tree and unknown project directories always fail closed.
        """
        total = owner_used
        opaque: list[str] = []
        accounting = {"data": {"mode": "measured", "bytes": owner_used}}
        for child in self.project_root.iterdir():
            if child == self.data_root:
                continue
            owner = child.name.lower() if os.name == "nt" else child.name
            if owner in OTHER_OWNER_LIMITS:
                try:
                    if _is_link(child):
                        raise UnsafePath("Foreign owner contains a link")
                    if not child.is_dir():
                        raise UnsafePath("Foreign owner root is not a directory")
                    size = directory_bytes(child)
                    accounting[owner] = {"mode": "measured", "bytes": size}
                except (OSError, StorageError) as error:
                    size = OTHER_OWNER_LIMITS[owner]
                    opaque.append(owner)
                    accounting[owner] = {
                        "mode": "allocated_upper_bound", "bytes": size,
                        "reason": type(error).__name__,
                    }
                total += size
                continue
            information = child.lstat()
            if _is_link(child):
                raise UnsafePath(f"Unknown project entry is a link: {child}")
            if stat.S_ISDIR(information.st_mode):
                size = directory_bytes(child)
            elif stat.S_ISREG(information.st_mode):
                size = information.st_size
            else:
                raise UnsafePath(f"Unknown project entry is not a regular file/directory: {child}")
            total += size
            accounting[child.name] = {"mode": "measured", "bytes": size}
        return total, opaque, accounting

    def snapshot(self) -> dict:
        with self._transaction() as connection:
            return asdict(self._snapshot(connection))

    def reserve(self, peak_bytes: int, *, purpose: str = "library operation") -> Reservation:
        """Reserve bounded peak growth under a serialized SQLite transaction."""
        if type(peak_bytes) is not int or peak_bytes <= 0:
            raise ValueError("peak_bytes must be a positive integer")
        if len(purpose) > 2048:
            raise ValueError("purpose exceeds 2048 characters")
        reservation_id = uuid.uuid4().hex
        with self._transaction() as connection:
            snapshot = self._snapshot(connection)
            pending = snapshot.active_reserved_bytes + peak_bytes
            if snapshot.owner_used_bytes + pending > self.owner_limit_bytes:
                raise QuotaExceeded("Library owner quota exceeded (existing files + full active reservations + peak)")
            if snapshot.project_used_bytes + pending > self.project_limit_bytes:
                raise QuotaExceeded("Project 700 GB hard limit or configured lower limit exceeded")
            if pending + self.min_free_bytes > snapshot.free_bytes:
                raise QuotaExceeded("Insufficient physical disk space after reservations and safety floor")
            connection.execute(
                "INSERT INTO reservations VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                (reservation_id, peak_bytes, purpose, os.getpid(), _utcnow()),
            )
        return Reservation(self, reservation_id, peak_bytes)

    def release(self, reservation_id: str, *, reason: str) -> None:
        """Explicit release; callers recovering a crash must first verify no writer runs."""
        if not reason or len(reason) > 2048:
            raise ValueError("An explicit release reason of at most 2048 characters is required")
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE reservations SET released_at=?, release_reason=? "
                "WHERE reservation_id=? AND released_at IS NULL",
                (_utcnow(), reason, reservation_id),
            )
            if cursor.rowcount == 0 and not connection.execute(
                "SELECT 1 FROM reservations WHERE reservation_id=?", (reservation_id,)
            ).fetchone():
                raise KeyError(reservation_id)

    def active_reservations(self) -> list[dict]:
        with self._transaction() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM reservations WHERE released_at IS NULL ORDER BY created_at"
            )]
