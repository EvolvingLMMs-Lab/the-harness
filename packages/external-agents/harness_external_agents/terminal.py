"""Interactive terminal processes owned by the session host."""

from contextlib import suppress
import codecs
import os
import signal
import subprocess
import sys

from .session import Session


class PosixTerminal:
    def __init__(self, argv, cwd, env):
        import pty

        self.master, slave = pty.openpty()
        # The helper becomes a session leader before acquiring the controlling TTY. No
        # Python preexec_fn runs in the threaded host's forked process.
        enter = "import fcntl,os,sys,termios; fcntl.ioctl(0,termios.TIOCSCTTY,0); os.execv(sys.argv[1],sys.argv[1:])"
        try:
            self.process = subprocess.Popen([sys.executable, "-c", enter, *argv], cwd=cwd, env=env,
                                            stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        except BaseException:
            os.close(self.master)
            raise
        finally:
            os.close(slave)

    def read(self):
        try:
            return os.read(self.master, 8192)
        except OSError:
            return b""

    def write(self, data):
        pending = memoryview(data)
        while pending:
            pending = pending[os.write(self.master, pending):]

    def wait(self):
        return self.process.wait()

    def close(self):
        with suppress(ProcessLookupError):
            os.killpg(self.process.pid, signal.SIGKILL)
        with suppress(OSError):
            os.close(self.master)
        self.process.wait(timeout=5)


class TerminalSession(Session):
    def __init__(self, directory, adapter, cwd, argv, environment):
        super().__init__(directory, adapter, cwd)
        self.argv, self.environment = argv, environment
        self.terminal = None

    def open(self, text, files):
        if files:
            raise ValueError("attach files using the terminal agent's own input")
        if os.name == "nt":
            from .winpty import ConPty

            launcher = ConPty
        else:
            launcher = PosixTerminal
        with self.lock:
            if self.ended:
                return
            self.terminal = launcher(self.argv, self.cwd, self.environment)
            self.controls.update(terminal_input=True, send=True, cancel_turn=True)
            self.state("RUNNING", "terminal started")
        if text:
            self.send_message(text)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while chunk := self.terminal.read():
            self.trace.emit("terminal_output", text=decoder.decode(chunk))
        tail = decoder.decode(b"", final=True)
        if tail:
            self.trace.emit("terminal_output", text=tail)
        code = self.terminal.wait()
        with self.lock:
            if code and not self.closing and not self.ended:
                self.trace.emit("error", message=f"terminal process exited with status {code}")
            self.end("ERROR" if code and not self.closing else "FINISHED")
        self.stop_transport()

    def send_message(self, text, files=()):
        if files:
            raise ValueError("attach files using the terminal agent's own input")
        self.terminal_input(text + "\r")

    def terminal_input(self, text):
        if not isinstance(text, str) or len(text.encode("utf-8")) > 32768:
            raise ValueError("terminal input must be text under 32 KiB")
        with self.lock:
            if self.ended or self.terminal is None:
                raise ValueError("the terminal is unavailable")
            terminal = self.terminal
        terminal.write(text.encode("utf-8"))

    def cancel(self):
        self.terminal_input("\x03")

    def close_transport(self):
        if self.terminal is not None:
            self.terminal.close()

    def set_model(self, model=None, reasoning_effort=None):
        raise ValueError("set the model in the agent's terminal")
