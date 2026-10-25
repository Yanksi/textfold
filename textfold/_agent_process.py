"""Cancellation of one owned agent process tree, never a process-name search."""
import os
import signal
import subprocess
import tempfile
import time


class _WindowsJob:
    def __init__(self, process):
        import ctypes as c
        from ctypes import wintypes as w
        class Limits(c.Structure):
            _fields_ = [("process_time", c.c_longlong), ("job_time", c.c_longlong), ("flags", w.DWORD),
                        ("min_working", c.c_size_t), ("max_working", c.c_size_t), ("active", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Counters(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in ("read", "write", "other", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(c.Structure):
            _fields_ = [("basic", Limits), ("io", Counters), ("process_memory", c.c_size_t),
                        ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = (c.c_void_p, w.LPCWSTR)
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = (w.HANDLE, c.c_int, c.c_void_p, w.DWORD)
        self.kernel.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
        self.kernel.CloseHandle.argtypes = (w.HANDLE,)
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle: raise c.WinError(c.get_last_error())
        limits = Extended(); limits.basic.flags = 0x2000   # kill only this job's descendants on close
        if not self.kernel.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)) or \
                not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = c.WinError(c.get_last_error()); self.close(); raise error

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run(args, *, stop, timeout, **kwargs):
    """communicate with polling cancellation; output completed before Stop is retained."""
    from .llm import Stopped
    if stop.is_set(): raise Stopped()
    body = kwargs.pop("input", None)
    windows = os.name == "nt"
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if windows else {"start_new_session": True}
    source = tempfile.TemporaryFile()
    try:
        source.write(body.encode(kwargs.get("encoding") or "utf-8") if isinstance(body, str) else body or b"")
        source.seek(0)
        process = subprocess.Popen(args, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **flags, **kwargs)
    except BaseException:
        source.close()
        raise
    job = None
    try:
        if windows: job = _WindowsJob(process)
        deadline = time.monotonic() + timeout
        while True:
            if stop.is_set() and process.poll() is None: raise Stopped()
            left = deadline - time.monotonic()
            if left <= 0: raise subprocess.TimeoutExpired(args, timeout)
            try:
                out, err = process.communicate(timeout=min(.2, left))
                return subprocess.CompletedProcess(args, process.returncode, out, err)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if job:
            job.close()
        elif not windows:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        if process.poll() is None:
            process.kill()   # the handle from this Popen, never an unrelated bridge
        try: process.communicate(timeout=5)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream: stream.close()
            source.close()
