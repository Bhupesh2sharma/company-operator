import fcntl
from contextlib import contextmanager
from pathlib import Path


LOCK_PATH = Path(__file__).resolve().parent / ".worker.lock"


@contextmanager
def worker_lock():
    with LOCK_PATH.open("a+") as lock_file:
        try:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            raise RuntimeError(
                "Another worker is already running. "
                "Wait for it to finish before starting or resuming work."
            ) from None

        try:
            yield
        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )