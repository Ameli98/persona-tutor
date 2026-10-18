"""Silence chatty libraries (GPT-SoVITS prints its input text, sentence splits, progress bars and timings for
every sentence) without hiding anything else.

`with quiet():` drops console output from the *current thread* only, so errors printed by other threads
(request handlers, tracebacks) still reach the terminal. install() must run once at startup.
"""
import contextlib
import sys
import threading

_local = threading.local()


class _ThreadFilter:
    def __init__(self, stream):
        self._stream = stream

    def write(self, s):
        if getattr(_local, "quiet", False):
            return len(s)
        return self._stream.write(s)

    def __getattr__(self, name):  # flush, isatty, fileno, encoding, ...
        return getattr(self._stream, name)


def install():
    if not isinstance(sys.stdout, _ThreadFilter):
        sys.stdout = _ThreadFilter(sys.stdout)
        sys.stderr = _ThreadFilter(sys.stderr)


@contextlib.contextmanager
def quiet():
    before = getattr(_local, "quiet", False)
    _local.quiet = True
    try:
        yield
    finally:
        _local.quiet = before
