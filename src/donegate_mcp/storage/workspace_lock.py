from __future__ import annotations

from pathlib import Path
from threading import RLock, local
from types import TracebackType

from donegate_mcp.storage.fs import ensure_dir

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-Unix platforms.
    fcntl = None  # type: ignore[assignment]


class WorkspaceWriteLock:
    """Coarse, reentrant write lock for one DoneGate data root."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._thread_lock = RLock()
        self._state = local()

    def __enter__(self) -> "WorkspaceWriteLock":
        self._thread_lock.acquire()
        depth = getattr(self._state, "depth", 0)
        if depth == 0:
            ensure_dir(self.lock_path.parent)
            handle = self.lock_path.open("a+", encoding="utf-8")
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            self._state.handle = handle
        self._state.depth = depth + 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        depth = getattr(self._state, "depth", 0) - 1
        self._state.depth = depth
        if depth == 0:
            handle = self._state.handle
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            self._state.handle = None
        self._thread_lock.release()
