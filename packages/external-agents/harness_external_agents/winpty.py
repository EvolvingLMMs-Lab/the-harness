"""Windows ConPTY transport for a host-owned console process."""

import ctypes as c
from ctypes import wintypes as w
import subprocess
import threading


class Coord(c.Structure):
    _fields_ = [("x", c.c_short), ("y", c.c_short)]


class Startup(c.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR), ("title", w.LPWSTR),
                ("x", w.DWORD), ("y", w.DWORD), ("x_size", w.DWORD), ("y_size", w.DWORD),
                ("x_chars", w.DWORD), ("y_chars", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
                ("show", w.WORD), ("reserved_bytes", w.WORD), ("reserved_data", w.LPVOID),
                ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE), ("attributes", w.LPVOID)]


class Process(c.Structure):
    _fields_ = [("handle", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


def api():
    kernel = c.WinDLL("kernel32", use_last_error=True)
    pointer = c.POINTER
    signatures = {
        "CreatePipe": (w.BOOL, pointer(w.HANDLE), pointer(w.HANDLE), w.LPVOID, w.DWORD),
        "CreatePseudoConsole": (c.c_long, Coord, w.HANDLE, w.HANDLE, w.DWORD, pointer(w.HANDLE)),
        "ClosePseudoConsole": (None, w.HANDLE),
        "InitializeProcThreadAttributeList": (w.BOOL, w.LPVOID, w.DWORD, w.DWORD, pointer(c.c_size_t)),
        "UpdateProcThreadAttribute": (w.BOOL, w.LPVOID, w.DWORD, c.c_size_t, w.LPVOID,
                                      c.c_size_t, w.LPVOID, w.LPVOID),
        "DeleteProcThreadAttributeList": (None, w.LPVOID),
        "CreateProcessW": (w.BOOL, w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL,
                           w.DWORD, w.LPVOID, w.LPCWSTR, pointer(Startup), pointer(Process)),
        "CloseHandle": (w.BOOL, w.HANDLE),
        "ReadFile": (w.BOOL, w.HANDLE, w.LPVOID, w.DWORD, pointer(w.DWORD), w.LPVOID),
        "WriteFile": (w.BOOL, w.HANDLE, w.LPVOID, w.DWORD, pointer(w.DWORD), w.LPVOID),
        "WaitForSingleObject": (w.DWORD, w.HANDLE, w.DWORD),
        "GetExitCodeProcess": (w.BOOL, w.HANDLE, pointer(w.DWORD)),
        "TerminateProcess": (w.BOOL, w.HANDLE, w.UINT),
    }
    for name, (result, *arguments) in signatures.items():
        function = getattr(kernel, name)
        function.restype, function.argtypes = result, arguments
    return kernel


def check(success):
    if not success:
        raise c.WinError(c.get_last_error())


class ConPty:
    def __init__(self, argv, cwd, environment):
        if not argv[0].lower().endswith(".exe"):
            raise ValueError("ConPTY requires a Windows executable; configure cmd.exe explicitly for a script")
        self.kernel = api()
        self.input, self.output, self.console = w.HANDLE(), w.HANDLE(), w.HANDLE()
        self.process = Process()
        self.closed = False
        self.close_lock = threading.Lock()
        self.exited = threading.Event()
        self.code = 1
        read_input, write_output = w.HANDLE(), w.HANDLE()
        try:
            check(self.kernel.CreatePipe(c.byref(read_input), c.byref(self.input), None, 0))
            check(self.kernel.CreatePipe(c.byref(self.output), c.byref(write_output), None, 0))
            result = self.kernel.CreatePseudoConsole(Coord(120, 40), read_input, write_output, 0,
                                                      c.byref(self.console))
            if result:
                raise OSError(f"CreatePseudoConsole failed ({result:#x})")
            self._launch(argv, cwd, environment)
        except BaseException:
            for handle in (self.input, self.output):
                if handle:
                    self.kernel.CloseHandle(handle)
            if self.console:
                self.kernel.ClosePseudoConsole(self.console)
            raise
        finally:
            for handle in (read_input, write_output):
                if handle:
                    self.kernel.CloseHandle(handle)
        self.kernel.CloseHandle(self.process.thread)
        self.watcher = threading.Thread(target=self._wait_process, name="conpty-exit", daemon=True)
        self.watcher.start()

    def _launch(self, argv, cwd, environment):
        size = c.c_size_t()
        self.kernel.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
        attributes = c.create_string_buffer(size.value)
        check(self.kernel.InitializeProcThreadAttributeList(attributes, 1, 0, c.byref(size)))
        try:
            check(self.kernel.UpdateProcThreadAttribute(attributes, 0, 0x00020016, self.console,
                                                        c.sizeof(w.HANDLE), None, None))
            startup = Startup()
            startup.cb = c.sizeof(startup)
            startup.attributes = c.cast(attributes, w.LPVOID)
            command = c.create_unicode_buffer(subprocess.list2cmdline(argv))
            env = c.create_unicode_buffer("\0".join(f"{key}={environment[key]}" for key in
                                                     sorted(environment, key=str.upper)) + "\0\0")
            check(self.kernel.CreateProcessW(argv[0], command, None, None, False, 0x00080000 | 0x00000400,
                                             env, str(cwd), c.byref(startup), c.byref(self.process)))
        finally:
            self.kernel.DeleteProcThreadAttributeList(attributes)

    def read(self):
        buffer, count = c.create_string_buffer(8192), w.DWORD()
        if self.kernel.ReadFile(self.output, buffer, len(buffer), c.byref(count), None):
            return buffer.raw[:count.value]
        return b""

    def write(self, data):
        count = w.DWORD()
        check(self.kernel.WriteFile(self.input, data, len(data), c.byref(count), None))
        if count.value != len(data):
            raise OSError("incomplete ConPTY input")

    def wait(self):
        self.exited.wait()
        return self.code

    def _wait_process(self):
        self.kernel.WaitForSingleObject(self.process.handle, 0xFFFFFFFF)
        code = w.DWORD()
        if self.kernel.GetExitCodeProcess(self.process.handle, c.byref(code)):
            self.code = code.value
        self.exited.set()
        self.kernel.ClosePseudoConsole(self.console)

    def close(self):
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
        if self.kernel.WaitForSingleObject(self.process.handle, 0) == 258:
            try:
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.kernel.TerminateProcess(self.process.handle, 1)
        self.kernel.CloseHandle(self.input)
        self.watcher.join(5)
        self.kernel.CloseHandle(self.output)
        if self.exited.is_set():
            self.kernel.CloseHandle(self.process.handle)
