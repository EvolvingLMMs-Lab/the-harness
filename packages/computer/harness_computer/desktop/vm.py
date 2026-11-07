"""A virtual machine of a display workspace's own (Windows and macOS; Linux where asked): a
computer nobody else sees or uses, where the agent's applications run and its input goes,
never the user's screen, mouse or keyboard.

The machine starts from a disk image the user names (settings computer.vm_image), over a
copy-on-write layer of the workspace's own, so several run side by side from one image
and none changes it; the layer is deleted when the workspace ends. Any x86-64 desktop
image works: OS-Omni's Ubuntu VM, the one the osomni bench's workers drive, runs as it is
from its VMware folder (its .vmx names the disk and the firmware).

Hypervisors (settings computer.vm_hypervisor):

    qemu   QEMU, with the system's hypervisor: WHPX (Windows Hypervisor Platform), HVF
           (macOS), KVM (Linux); software emulation only when computer.vm_accel is "any".
           Headless (-display none), no network port: its picture (screendump) and its
           input (input-send-event: a USB tablet's absolute points, keys as QEMU's key
           codes, US layout) go through QMP, on a named pipe (Windows) or a socket in the
           workspace's directory that only the guard holds.
    vz     macOS's Virtualization.framework, through a helper of the harness's own
           (desktop/vz/HarnessVZ.swift, built and ad-hoc signed with the virtualization
           entitlement on first use). A Tart VM folder (a macOS guest: OS-Omni's macOS VM
           once imported) or a raw EFI disk (a Linux guest); copies are APFS clones. Its
           screen is the guest's own VNC server (macOS Screen Sharing: the guest's user,
           computer.vm_user, and $HARNESS_VM_PASSWORD; Tart's images use admin/admin).

Every machine boots cold: WHPX and Virtualization.framework cannot restore a saved state.

A guard process owns the machine (`python -m harness_computer.desktop.vm`): it reads its request
on standard input, starts the machine (on Windows in a job object that ends it with the
guard), prints where its screen is, then serves the worker's requests (a QEMU machine's
picture and input) a line each, and ends the machine and deletes its layer when its
standard input closes: when the VM is closed, and when the worker that made it ends in any
way. Standard library only (pictures need Pillow).

    vm = VM((1280, 800), directory, {"vm_image": "D:/vms/ubuntu.qcow2"}).start()
    vm.name             "vm-4242"
    vm.screen           its screen: picture(), click(), drag(), scroll(), keys(), type()
    vm.close()
"""

import ctypes
import functools
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import secrets
import shutil

from harness.sdk import pid_alive
import signal
import socket
import subprocess
import sys
import threading
import time

from . import rfb

HYPERVISORS = ("qemu", "vz")
ACCELS = ("hardware", "any")
# The settings (section computer) a machine is made from, and their defaults.
SETTINGS = {"display_backend": "auto", "vm_image": "", "vm_hypervisor": "auto", "vm_memory": 2048, "vm_cpus": 2,
            "vm_accel": "hardware", "vm_user": "admin"}
# Programs found on PATH (and QEMU's install folders) unless these variables name them.
OVERRIDES = {"qemu": "HARNESS_QEMU", "vz": "HARNESS_VZ", "image": "HARNESS_VM_IMAGE",
             "password": "HARNESS_VM_PASSWORD", "firmware": "HARNESS_VM_FIRMWARE"}
QEMU_FOLDERS = {"win32": ("C:/Program Files/qemu", "C:/Program Files (x86)/qemu"),
                "darwin": ("/opt/homebrew/bin", "/usr/local/bin"), "linux": ("/usr/bin", "/usr/local/bin")}
# Disk images by their suffix (QEMU's format names); "iso" boots a live system, writes nothing.
FORMATS = {".qcow2": "qcow2", ".qcow": "qcow2", ".vmdk": "vmdk", ".vhdx": "vhdx", ".vhd": "vpc", ".vdi": "vdi",
           ".raw": "raw", ".img": "raw", ".iso": "iso"}
QEMU_SECONDS = 60.0
VZ_SECONDS = 240.0
REQUEST_SECONDS = 20.0
INSTALL = {
    "win32": "install QEMU (winget install SoftwareFreedomConservancy.QEMU, or set HARNESS_QEMU to "
             "qemu-system-x86_64.exe)",
    "darwin": "install the Xcode command line tools (xcode-select --install): the harness builds its "
              "Virtualization.framework helper with them on first use; or install QEMU (brew install qemu) and set "
              "computer.vm_hypervisor to qemu",
    "linux": "install QEMU (Debian/Ubuntu: sudo apt install qemu-system-x86 qemu-utils; Fedora: sudo dnf install "
             "qemu-kvm qemu-img; Arch: sudo pacman -S qemu-full)"}
ACCEL_HINT = {
    "win32": "turn on Windows Hypervisor Platform (Windows features: \"Windows Hypervisor Platform\", then "
             "restart)",
    "darwin": "this Mac has no hypervisor (kern.hv_support is 0)",
    "linux": "KVM: /dev/kvm must exist and be readable and writable by you (sudo usermod -aG kvm $USER, then log in "
             "again)"}
IMAGE_HINT = ("set the disk image it starts from (Settings, Computer: VM image; or harness settings set "
              "computer.vm_image PATH): an x86-64 desktop as qcow2, vmdk, vhdx, vdi, raw or a live ISO, or a VMware "
              "folder (OS-Omni's Ubuntu VM: Hugging Face dataset Cloudriver/OS-Omni-VM, linux/v3, 13 GB to download)")


# -- what this machine has -----------------------------------------------------------------

def options(given: dict | None = None, data=None) -> dict:
    """The machine's settings: `given` over the app's settings (computer.vm_*, of `data`,
    default DATA) over the defaults; $HARNESS_VM_IMAGE stands for an empty image."""
    found = dict(SETTINGS)
    try:
        from harness.sdk import data as data_dir
        from harness.sdk import Settings

        computer = Settings(Path(data) if data else data_dir()).get().get("computer", {})
        found.update({key: computer[key] for key in SETTINGS if key in computer})
    except Exception:
        pass
    found.update({key: value for key, value in (given or {}).items() if value is not None})
    if not found.get("vm_image") and os.environ.get(OVERRIDES["image"]):
        found["vm_image"] = os.environ[OVERRIDES["image"]]
    return found


def programs(system: str | None = None) -> dict:
    """The programs a machine uses that this computer has: qemu (qemu-system-x86_64), qemu_img,
    swiftc, codesign (macOS); None where missing."""
    system = _system(system)
    exe = ".exe" if system == "win32" else ""
    found = {"qemu": None, "qemu_img": None, "swiftc": None, "codesign": None}
    given = os.environ.get(OVERRIDES["qemu"])
    candidates = []
    if given:
        candidates.append(Path(given) / f"qemu-system-x86_64{exe}" if Path(given).is_dir() else Path(given))
    which = shutil.which("qemu-system-x86_64")
    if which:
        candidates.append(Path(which))
    candidates += [Path(folder) / f"qemu-system-x86_64{exe}" for folder in QEMU_FOLDERS.get(system, ())]
    for candidate in candidates:
        if candidate.is_file():
            found["qemu"] = str(candidate)
            image = candidate.with_name(f"qemu-img{candidate.suffix}")
            found["qemu_img"] = str(image) if image.is_file() else shutil.which("qemu-img")
            break
    if system == "darwin":
        found["swiftc"] = shutil.which("swiftc")
        found["codesign"] = shutil.which("codesign")
    return found


@functools.lru_cache(maxsize=8)
def accelerator(system: str | None = None) -> str | None:
    """The system's hypervisor QEMU can use: "whpx", "hvf", "kvm", or None (asked once a
    process: the app's status asks often)."""
    system = _system(system)
    if system == "win32":
        try:
            dll = ctypes.WinDLL("WinHvPlatform.dll")
            present, written = ctypes.c_uint64(0), ctypes.c_uint32(0)
            # WHvCapabilityCodeHypervisorPresent.
            if dll.WHvGetCapability(0, ctypes.byref(present), 8, ctypes.byref(written)) == 0 and present.value:
                return "whpx"
        except (OSError, AttributeError):
            pass
        return None
    if system == "darwin":
        try:
            answer = subprocess.run(["sysctl", "-n", "kern.hv_support"], capture_output=True, encoding="utf-8",
                                    errors="replace", timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return "hvf" if answer == "1" else None
    return "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else None


def image(path) -> dict | None:
    """What `path` is as a machine's disk: {path, format, guest, firmware} (guest "macos" for
    a Tart folder, else "pc"); None when it is nothing a machine boots."""
    if not path:
        return None
    path = Path(os.path.expanduser(str(path)))
    firmware = os.environ.get(OVERRIDES["firmware"]) or None
    if path.is_dir():
        if (path / "config.json").is_file() and (path / "disk.img").is_file():
            try:
                config = json.loads((path / "config.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            guest = "macos" if config.get("os") == "darwin" else "pc"
            return {"path": str(path), "format": "tart", "guest": guest, "firmware": "efi",
                    "arch": config.get("arch")}
        machines = sorted(path.glob("*.vmx"))
        if machines:
            return _vmware(machines[0], firmware)
        return None
    if path.suffix.lower() == ".vmx" and path.is_file():
        return _vmware(path, firmware)
    kind = FORMATS.get(path.suffix.lower())
    if kind is None or not path.is_file():
        return None
    return {"path": str(path), "format": kind, "guest": "pc", "firmware": firmware or "bios"}


def _vmware(machine: Path, firmware=None) -> dict | None:
    """A VMware machine's first disk (its .vmx's fileName) and firmware."""
    try:
        text = machine.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    settings = dict(re.findall(r'^\s*([\w:.]+)\s*=\s*"([^"]*)"', text, re.M))
    disks = [value for key, value in settings.items() if re.fullmatch(r"(scsi|sata|nvme|ide)\d+:\d+\.fileName", key)
             and value.lower().endswith(".vmdk") and settings.get(key.replace("fileName", "present"), "TRUE").upper()
             != "FALSE"]
    if not disks:
        return None
    disk = machine.parent / disks[0]
    if not disk.is_file():
        return None
    return {"path": str(disk), "format": "vmdk", "guest": "pc",
            "firmware": firmware or ("efi" if settings.get("firmware", "").lower() == "efi" else "bios")}


def hypervisor(settings: dict, system: str | None = None) -> str | None:
    """The hypervisor a machine of `settings` runs under here: "qemu", "vz", or None."""
    system = _system(system)
    wanted = settings.get("vm_hypervisor", "auto")
    if wanted in HYPERVISORS:
        return wanted
    disk = image(settings.get("vm_image"))
    if system == "darwin" and (disk is None or disk["format"] in ("tart", "raw")):
        return "vz"
    return "qemu"


def unavailable(settings: dict | None = None, system: str | None = None) -> str:
    """Why a machine cannot run here (empty when it can), with what to install or set."""
    system = _system(system)
    settings = options() if settings is None else settings
    kind = hypervisor(settings, system)
    disk = image(settings.get("vm_image"))
    if not settings.get("vm_image"):
        return f"a display workspace runs in a virtual machine here: {IMAGE_HINT}"
    if disk is None:
        return f"the VM image {settings['vm_image']} is not a disk image a machine boots: {IMAGE_HINT}"
    found = programs(system)
    if kind == "vz":
        if system != "darwin":
            return "Virtualization.framework is macOS's: set computer.vm_hypervisor to qemu or auto"
        if _mac_version() < (13, 0):
            return "Virtualization.framework machines need macOS 13 or later here; or install QEMU (brew install " \
                   "qemu) and set computer.vm_hypervisor to qemu"
        if disk["format"] not in ("tart", "raw"):
            return f"Virtualization.framework boots a Tart VM folder or a raw EFI disk, not {disk['format']}: " \
                   f"convert it (qemu-img convert -O raw), or set computer.vm_hypervisor to qemu"
        if disk.get("arch") and disk["arch"] != _mac_arch():
            return f"the image is for {disk['arch']} and this Mac is {_mac_arch()}: Virtualization.framework runs " \
                   f"guests of its own architecture"
        if not os.environ.get(OVERRIDES["vz"]) and not _built_helper() and not (found["swiftc"] and found["codesign"]):
            return INSTALL["darwin"]
        return ""
    if not found["qemu"]:
        return INSTALL.get(system, INSTALL["linux"])
    if disk["format"] != "iso" and not found["qemu_img"]:
        return f"qemu-img is missing beside {found['qemu']}: {INSTALL.get(system, INSTALL['linux'])}"
    if settings.get("vm_accel", "hardware") == "hardware" and accelerator(system) is None:
        return f"no hardware virtualization for QEMU: {ACCEL_HINT.get(system, ACCEL_HINT['linux'])}; or set " \
               f"computer.vm_accel to any (software emulation: much slower)"
    return ""


def available(settings: dict | None = None, system: str | None = None) -> bool:
    return not unavailable(settings, system)


def _system(system=None) -> str:
    system = system or sys.platform
    return "linux" if system.startswith("linux") else system


def _mac_version() -> tuple:
    try:
        return tuple(int(part) for part in platform.mac_ver()[0].split(".")[:2])
    except ValueError:
        return (0, 0)


def _mac_arch() -> str:
    return "arm64" if platform.machine() in ("arm64", "aarch64") else "amd64"


# -- the machine -----------------------------------------------------------------------------

class VM:
    """A virtual machine of a workspace's own (see the module's text)."""

    def __init__(self, size=(1280, 800), directory=None, settings: dict | None = None, system: str | None = None):
        self.size = (int(size[0]), int(size[1]))
        self.directory = Path(directory) if directory else None
        self.settings = options(settings)
        self.system = _system(system)
        self.name = None
        self.screen = None
        self.hypervisor = None
        self.accelerator = None
        self._guard = None
        self._answers = None
        self._lock = threading.Lock()

    def start(self, timeout: float | None = None):
        missing = unavailable(self.settings, self.system)
        if missing:
            raise RuntimeError(missing)
        self.hypervisor = hypervisor(self.settings, self.system)
        timeout = timeout or (VZ_SECONDS if self.hypervisor == "vz" else QEMU_SECONDS)
        directory = self.directory or Path(home_dir()) / "vms" / f"worker-{os.getpid()}"
        sweep(directory.parent)
        directory.mkdir(parents=True, exist_ok=True)
        request = {"hypervisor": self.hypervisor, "image": image(self.settings["vm_image"]), "size": list(self.size),
                   "memory": int(self.settings["vm_memory"]), "cpus": int(self.settings["vm_cpus"]),
                   "accel": self.settings["vm_accel"], "directory": str(directory),
                   "programs": programs(self.system), "user": self.settings.get("vm_user") or "admin",
                   "password": os.environ.get(OVERRIDES["password"]) or "admin",
                   "helper": helper_path() if self.hypervisor == "vz" else None}
        flags = {"creationflags": 0x08000000 | 0x00000200} if self.system == "win32" else {"start_new_session": True}
        log = open(directory / "guard.log", "ab")
        try:
            self._guard = subprocess.Popen([sys.executable, "-m", "harness_computer.desktop.vm"], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=log, env={**os.environ,
                                                                                    "PYTHONPATH": _python_path()},
                                           **flags)
        finally:
            log.close()
        self._answers = _lines(self._guard.stdout)
        try:
            self._guard.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
            self._guard.stdin.flush()
            answer = self._answer(timeout)
            if answer is None:
                raise RuntimeError(f"the VM did not start within {timeout:g} s ({self.hypervisor}; see {directory})")
            if answer.get("error"):
                raise RuntimeError(f"the VM did not start: {answer['error']} (see {directory})")
            self.name = answer.get("name") or f"vm-{self._guard.pid}"
            self.accelerator = answer.get("accelerator")
            if self.hypervisor == "qemu":
                self.screen = QemuScreen(self)
            else:
                served = answer["vnc"]
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        self.screen = rfb.Client(served["host"], served["port"], password=answer.get("password"),
                                                 user=answer.get("user")).connect()
                        break
                    except (OSError, rfb.RFBError) as error:
                        if time.monotonic() > deadline or self._guard.poll() is not None:
                            raise RuntimeError(f"the VM's screen did not answer: {error} (see {directory})")                                 from error
                        time.sleep(1.0)
        except BaseException:
            self.close()
            raise
        return self

    def _answer(self, timeout):
        try:
            line = self._answers.get(timeout=timeout)
        except queue.Empty:
            return None
        return json.loads(line) if line else None

    def request(self, op: str, timeout: float = REQUEST_SECONDS, **arguments) -> dict:
        """One request to the guard (a QEMU machine's picture or input), and its answer."""
        with self._lock:
            if self._guard is None or self._guard.poll() is not None:
                raise RuntimeError("the VM has ended")
            self._guard.stdin.write(json.dumps({"op": op, **arguments}).encode("utf-8") + b"\n")
            self._guard.stdin.flush()
            answer = self._answer(timeout)
        if answer is None:
            raise RuntimeError(f"the VM did not answer {op} within {timeout:g} s")
        if answer.get("error"):
            raise RuntimeError(f"the VM: {answer['error']}")
        return answer

    def close(self) -> None:
        if self.screen is not None:
            self.screen.close()
            self.screen = None
        guard, self._guard = self._guard, None
        if guard is None:
            return
        try:
            guard.stdin.close()
        except OSError:
            pass
        try:
            guard.wait(30)
        except subprocess.TimeoutExpired:
            _kill_tree(guard)
        try:
            guard.stdout.close()
        except OSError:
            pass

    def describe(self) -> dict:
        disk = image(self.settings.get("vm_image")) or {}
        return {"display": self.name, "vm": True, "hypervisor": self.hypervisor, "accelerator": self.accelerator,
                "image": Path(disk.get("path") or self.settings.get("vm_image") or "").name,
                "size": list(self.screen.size if self.screen and self.screen.size[0] else self.size)}

    def __enter__(self):
        return self.start() if self._guard is None else self

    def __exit__(self, *_):
        self.close()


# A QEMU machine's keys (QEMU's QKeyCode names): the key names of runtime/safety/shield.py, and
# the characters of a US keyboard (with shift where the character needs it).
QCODES = {
    "enter": "ret", "return": "ret", "\n": "ret", "\r": "ret", "tab": "tab", "\t": "tab", "backspace": "backspace",
    "delete": "delete", "del": "delete", "esc": "esc", "escape": "esc", "space": "spc", "up": "up", "down": "down",
    "left": "left", "right": "right", "home": "home", "end": "end", "pageup": "pgup", "pgup": "pgup",
    "pagedown": "pgdn", "pgdn": "pgdn", "insert": "insert", "ctrl": "ctrl", "ctrlleft": "ctrl", "ctrlright": "ctrl_r",
    "shift": "shift", "shiftleft": "shift", "shiftright": "shift_r", "alt": "alt", "altleft": "alt",
    "altright": "alt_r", "option": "alt", "optionleft": "alt", "optionright": "alt_r", "win": "meta_l",
    "winleft": "meta_l", "winright": "meta_r", "command": "meta_l", "capslock": "caps_lock", "numlock": "num_lock",
    "scrolllock": "scroll_lock", "pause": "pause", "printscreen": "print", "prtsc": "print", "prtscr": "print",
    "prntscrn": "print", "print": "print", "apps": "menu", "help": "help", "add": "kp_add",
    "subtract": "kp_subtract", "multiply": "kp_multiply", "divide": "kp_divide", "decimal": "kp_decimal",
    "separator": "kp_comma", "volumemute": "audiomute", "volumedown": "volumedown", "volumeup": "volumeup",
    "playpause": "audioplay", "nexttrack": "audionext", "prevtrack": "audioprev", "stop": "audiostop",
    "browserback": "ac_back", "browserforward": "ac_forward", "browserrefresh": "ac_refresh",
    "browserhome": "ac_home", "browserfavorites": "ac_bookmarks", "sleep": "sleep",
    **{f"f{n}": f"f{n}" for n in range(1, 25)}, **{f"num{n}": f"kp_{n}" for n in range(10)}}
_PLAIN = {" ": "spc", "-": "minus", "=": "equal", "[": "bracket_left", "]": "bracket_right", "\\": "backslash",
          ";": "semicolon", "'": "apostrophe", "`": "grave_accent", ",": "comma", ".": "dot", "/": "slash"}
_SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
            "_": "minus", "+": "equal", "{": "bracket_left", "}": "bracket_right", "|": "backslash",
            ":": "semicolon", '"': "apostrophe", "~": "grave_accent", "<": "comma", ">": "dot", "?": "slash"}
# The tablet's range: a point is its pixel's centre over the screen, scaled to 0..ABS_MAX.
ABS_MAX = 0x7FFF
QEMU_BUTTONS = {"left": "left", "middle": "middle", "right": "right"}
QEMU_WHEEL = {"up": "wheel-up", "down": "wheel-down", "left": "wheel-left", "right": "wheel-right"}


def char_qcode(char: str) -> tuple[str, bool]:
    """The QEMU key and whether shift goes with it for one character (US layout)."""
    if char in QCODES and len(char) == 1:
        return QCODES[char], False
    if char.isascii() and char.isalnum():
        return char.lower(), char.isupper()
    if char in _PLAIN:
        return _PLAIN[char], False
    if char in _SHIFTED:
        return _SHIFTED[char], True
    raise ValueError(f"a QEMU machine's keyboard types US ASCII, not {char!r}")


def key_qcodes(name: str) -> list[str]:
    """The QEMU keys one key name presses (a shifted character takes shift too)."""
    lower = str(name).lower()
    if lower in QCODES:
        return [QCODES[lower]]
    if len(name) == 1:
        code, shift = char_qcode(name)
        return ["shift", code] if shift else [code]
    raise ValueError(f"no QEMU key for {name!r}")


class QemuScreen:
    """A QEMU machine's screen through its guard: the picture (QMP screendump, PPM) and input
    (input-send-event to a USB tablet and the keyboard). The same methods as rfb.Client."""

    def __init__(self, vm: "VM"):
        self._vm = vm
        self.size = (0, 0)
        self._pointer = (0, 0)

    def picture(self):
        from PIL import Image

        answer = self._vm.request("picture")
        with Image.open(answer["path"]) as shot:
            image = shot.convert("RGB")
        self.size = image.size
        return image

    def _known_size(self):
        if self.size == (0, 0):
            self.picture()
        return self.size

    def _point(self, x, y) -> list:
        width, height = self._known_size()
        x = min(max(float(x), 0.0), width - 1.0)
        y = min(max(float(y), 0.0), height - 1.0)
        self._pointer = (int(round(x)), int(round(y)))
        return [{"type": "abs", "data": {"axis": "x", "value": int((x + 0.5) * ABS_MAX / width)}},
                {"type": "abs", "data": {"axis": "y", "value": int((y + 0.5) * ABS_MAX / height)}}]

    def _send(self, events) -> None:
        self._vm.request("input", events=events)

    @staticmethod
    def _button(name, down) -> dict:
        return {"type": "btn", "data": {"down": bool(down), "button": name}}

    def move(self, x, y) -> None:
        self._send(self._point(x, y))

    def click(self, x, y, button="left", count=1) -> None:
        name = QEMU_BUTTONS[button]
        self._send(self._point(x, y))
        for _ in range(int(count)):
            time.sleep(0.02)
            self._send([self._button(name, True)])
            time.sleep(0.03)
            self._send([self._button(name, False)])
            time.sleep(0.04)

    def drag(self, x, y, to_x, to_y, seconds=0.4, button="left") -> None:
        name = QEMU_BUTTONS[button]
        steps = max(2, int(float(seconds) / 0.02))
        self._send(self._point(x, y))
        self._send([self._button(name, True)])
        for step in range(1, steps + 1):
            time.sleep(float(seconds) / steps)
            self._send(self._point(x + (to_x - x) * step / steps, y + (to_y - y) * step / steps))
        self._send([self._button(name, False)])

    def scroll(self, direction, amount=1, x=None, y=None) -> None:
        name = QEMU_WHEEL[direction]
        if x is not None:
            self._send(self._point(x, y))
        for _ in range(max(1, int(amount))):
            self._send([self._button(name, True)])
            self._send([self._button(name, False)])
            time.sleep(0.01)

    def keys(self, names) -> None:
        """Press the keys together, release them in reverse."""
        codes = list(dict.fromkeys(code for name in names for code in key_qcodes(name)))
        for code in codes:
            self._send([_key(code, True)])
            time.sleep(0.01)
        time.sleep(0.03)
        for code in reversed(codes):
            self._send([_key(code, False)])

    def type(self, text) -> None:
        """Type the text a character at a time."""
        keys = [char_qcode(char) for char in str(text)]
        for code, shift in keys:
            events = ([_key("shift", True)] if shift else []) + [_key(code, True), _key(code, False)] + \
                     ([_key("shift", False)] if shift else [])
            self._send(events)
            time.sleep(0.01)

    @property
    def pointer(self) -> tuple[int, int]:
        return self._pointer

    def close(self) -> None:
        pass


def _key(code, down) -> dict:
    return {"type": "key", "data": {"down": bool(down), "key": {"type": "qcode", "data": code}}}


def home_dir() -> Path:
    from harness.sdk import home

    return home()


def sweep(root: Path) -> None:
    """Delete what machines of workers that ended left behind (their layers)."""
    root = Path(root)
    if not root.is_dir():
        return
    for directory in root.glob("worker-*"):
        try:
            pid = int(directory.name.split("-", 1)[1])
        except ValueError:
            continue
        if pid != os.getpid() and not _alive(pid):
            shutil.rmtree(directory, ignore_errors=True)


def _alive(pid: int) -> bool:
    """Whether process `pid` runs (core/procs.py: access denied means it runs)."""
    return pid_alive(pid)
    return True


def _kill_tree(process) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.wait(5)
    except subprocess.TimeoutExpired:
        pass


def _python_path() -> str:
    """The harness and its packages first (this one among them), so the guard imports this
    harness."""
    from harness.sdk import python_path

    return python_path(os.environ.get("PYTHONPATH"))


def _lines(stream) -> "queue.Queue":
    """A stream's lines as they come, read on a thread of its own (pipes cannot be
    selected on Windows); "" when the stream ends."""
    lines = queue.Queue()

    def read():
        for line in iter(stream.readline, b""):
            lines.put(line.decode("utf-8", "replace").strip())
        lines.put("")

    threading.Thread(target=read, daemon=True).start()
    return lines


# -- QEMU ------------------------------------------------------------------------------------

def qemu_command(qemu: str, disk: dict, layer: str | None, size, memory: int, cpus: int, accel: str,
                 accelerator_name: str | None, qmp: str, firmware: dict | None = None) -> list[str]:
    """QEMU's command line for a machine: headless, no network port of its own (its screen
    and input go through QMP), a USB tablet for absolute pointing, user-mode networking."""
    width, height = size
    command = [qemu, "-name", "harness-display", "-machine", "q35", "-m", str(int(memory)), "-smp", str(int(cpus))]
    if accelerator_name:
        command += ["-accel", accelerator_name]
    if accel == "any" or not accelerator_name:
        command += ["-accel", "tcg"]
    command += ["-display", "none", "-vga", "none", "-device", f"VGA,edid=on,xres={int(width)},yres={int(height)}",
                "-usb", "-device", "usb-tablet",
                "-nic", "user,model=e1000", "-qmp", qmp, "-no-shutdown"]
    if firmware:
        command += ["-drive", f"if=pflash,format=raw,readonly=on,file={firmware['code']}",
                    "-drive", f"if=pflash,format=raw,file={firmware['vars']}"]
    if disk["format"] == "iso":
        command += ["-cdrom", disk["path"], "-boot", "d"]
    else:
        command += ["-drive", f"file={layer},format=qcow2,if=ide"]
    return command


def _firmware(qemu: str, directory: Path) -> dict:
    """UEFI for QEMU (edk2, which QEMU installs beside it): its code, and a copy of its
    variables for this machine."""
    base = Path(qemu).parent
    for share in (base / "share", base.parent / "share" / "qemu", Path("/usr/share/qemu"), Path("/usr/share/OVMF"),
                  Path("/opt/homebrew/share/qemu"), Path("/usr/local/share/qemu")):
        code = next((share / name for name in ("edk2-x86_64-code.fd", "OVMF_CODE.fd", "OVMF_CODE_4M.fd")
                     if (share / name).is_file()), None)
        variables = next((share / name for name in ("edk2-i386-vars.fd", "OVMF_VARS.fd", "OVMF_VARS_4M.fd")
                          if (share / name).is_file()), None)
        if code and variables:
            copy = directory / "efivars.fd"
            shutil.copyfile(variables, copy)
            return {"code": str(code), "vars": str(copy)}
    raise RuntimeError(f"the image boots with UEFI and no edk2/OVMF firmware was found beside {qemu}")


class QMP:
    """QEMU's machine protocol on a named pipe (Windows) or a socket."""

    def __init__(self, address: str, process, timeout: float = 30.0):
        deadline = time.monotonic() + timeout
        self._file = None
        self._socket = None
        while True:
            try:
                if address.startswith("pipe:"):
                    self._file = open("\\\\.\\pipe\\" + address[5:], "r+b", buffering=0)
                else:
                    self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self._socket.connect(address.split(":", 1)[1].split(",", 1)[0])
                    self._file = self._socket.makefile("rwb", buffering=0)
                break
            except OSError:
                if self._socket is not None:
                    self._socket.close()
                    self._socket = None
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("QEMU's machine protocol did not answer (QEMU ended or is stuck)")
                time.sleep(0.05)
        self._read()
        self.call("qmp_capabilities")

    def _read(self) -> dict:
        line = b""
        while not line.endswith(b"\n"):
            chunk = self._file.read(1)
            if not chunk:
                raise EOFError("QEMU closed its machine protocol")
            line += chunk
        return json.loads(line)

    def call(self, name: str, **arguments):
        self._file.write(json.dumps({"execute": name, **({"arguments": arguments} if arguments else {})}).encode()
                         + b"\n")
        while True:
            reply = self._read()
            if "event" in reply:
                continue
            if "error" in reply:
                raise RuntimeError(f"QEMU: {name}: {reply['error'].get('desc')}")
            return reply.get("return")

    def close(self):
        for thing in (self._file, self._socket):
            try:
                if thing is not None:
                    thing.close()
            except OSError:
                pass


def _job_for(process) -> object:
    """A Windows job object that ends `process` when this guard ends, however it ends."""
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.windll.kernel32
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(limits), ctypes.sizeof(limits))
    kernel.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(process._handle)))
    return job


def _end_with_parent() -> None:
    """In the child, before it runs QEMU: SIGKILL when the guard dies (prctl PR_SET_PDEATHSIG)."""
    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0)


def _start_qemu(request: dict, directory: Path, children: list) -> dict:
    found, disk = request["programs"], request["image"]
    accelerator_name = accelerator()
    if request["accel"] == "hardware" and accelerator_name is None:
        raise RuntimeError("no hardware virtualization for QEMU")
    layer = None
    if disk["format"] != "iso":
        layer = str(directory / "disk.qcow2")
        made = subprocess.run([found["qemu_img"], "create", "-q", "-f", "qcow2", "-b", disk["path"], "-F",
                               disk["format"], layer], capture_output=True, encoding="utf-8", errors="replace")
        if made.returncode:
            raise RuntimeError(f"qemu-img could not layer {disk['path']}: {made.stderr.strip()}")
    firmware = _firmware(found["qemu"], directory) if disk.get("firmware") == "efi" else None
    if sys.platform == "win32":
        qmp = f"pipe:harness-vm-{os.getpid()}-{secrets.token_hex(4)}"
    else:
        qmp = f"unix:{directory / 'qmp.sock'},server=on,wait=off"
    command = qemu_command(found["qemu"], disk, layer, request["size"], request["memory"], request["cpus"],
                           request["accel"], accelerator_name, qmp, firmware)
    log = open(directory / "qemu.log", "ab")
    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    if sys.platform.startswith("linux"):
        # QEMU ends with its guard however the guard ends (the job object's part on Linux).
        flags["preexec_fn"] = _end_with_parent
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **flags)
    finally:
        log.close()
    children.append(process)
    if sys.platform == "win32":
        children.append(_job_for(process))
    try:
        control = QMP(qmp, process)
    except RuntimeError as error:
        tail = (directory / "qemu.log").read_text(encoding="utf-8", errors="replace").strip()[-600:]
        raise RuntimeError(f"{error}: {tail}") from None
    children.append(control)
    return {"name": f"vm-{process.pid}", "accelerator": accelerator_name or "tcg", "hypervisor": "qemu"}


def _serve_qemu(request: dict, directory: Path, children: list) -> dict:
    """One request of the worker to a QEMU machine: its picture, or input."""
    control = next(child for child in children if isinstance(child, QMP))
    if request.get("op") == "picture":
        path = directory / "screen.ppm"
        control.call("screendump", filename=str(path), format="ppm")
        return {"path": str(path)}
    if request.get("op") == "input":
        control.call("input-send-event", events=list(request["events"]))
        return {"ok": True}
    raise ValueError(f"no request {request.get('op')!r}")


def _end_qemu(children) -> None:
    control = next((child for child in children if isinstance(child, QMP)), None)
    process = next((child for child in children if isinstance(child, subprocess.Popen)), None)
    if control is not None:
        try:
            control.call("quit")
        except (OSError, RuntimeError, EOFError, ValueError):
            pass
        control.close()
    if process is not None:
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


# -- Virtualization.framework ----------------------------------------------------------------

HELPER_SOURCES = ("HarnessVZ.swift", "vz.entitlements")


def helper_path() -> str:
    """The Virtualization.framework helper: $HARNESS_VZ, else the one built from this
    package's source (built now, the first time)."""
    given = os.environ.get(OVERRIDES["vz"])
    if given:
        return given
    built = _built_helper()
    if built:
        return built
    return build_helper()


def _helper_target() -> Path:
    source = Path(__file__).with_name("vz")
    digest = hashlib.sha256(b"".join((source / name).read_bytes() for name in HELPER_SOURCES)).hexdigest()[:12]
    return Path(home_dir()) / "vz" / digest / "harness-vz"


def _built_helper() -> str | None:
    try:
        target = _helper_target()
    except OSError:
        return None
    return str(target) if target.is_file() else None


def build_helper() -> str:
    """Compile desktop/vz/HarnessVZ.swift and sign it ad hoc with the virtualization
    entitlement (macOS runs no Virtualization.framework machine without it)."""
    found = programs("darwin")
    if not (found["swiftc"] and found["codesign"]):
        raise RuntimeError(INSTALL["darwin"])
    source = Path(__file__).with_name("vz")
    target = _helper_target()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name("harness-vz.partial")
    for argv in ([found["swiftc"], "-O", "-framework", "Virtualization", "-o", str(partial),
                  str(source / "HarnessVZ.swift")],
                 [found["codesign"], "--force", "--sign", "-", "--entitlements", str(source / "vz.entitlements"),
                  str(partial)]):
        done = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace")
        if done.returncode:
            raise RuntimeError(f"building the Virtualization.framework helper failed: {argv[0]}: "
                               f"{(done.stderr or done.stdout).strip()[-800:]}")
    os.replace(partial, target)
    return str(target)


def mac_address() -> str:
    """A random locally administered unicast MAC address."""
    octets = bytearray(os.urandom(6))
    octets[0] = (octets[0] & 0xFC) | 0x02
    return ":".join(f"{octet:02x}" for octet in octets)


def lease(mac: str, leases: str = "/var/db/dhcpd_leases") -> str | None:
    """The address macOS's DHCP server leased to `mac` (its file drops leading zeros)."""
    try:
        text = Path(leases).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    wanted = [int(part, 16) for part in mac.split(":")]
    for block in re.findall(r"\{(.*?)\}", text, re.S):
        address = re.search(r"ip_address=(\S+)", block)
        hardware = re.search(r"hw_address=\d+,(\S+)", block)
        if address and hardware:
            try:
                if [int(part, 16) for part in hardware.group(1).split(":")] == wanted:
                    return address.group(1)
            except ValueError:
                continue
    return None


def _clone(source: Path, target: Path) -> None:
    """An APFS clone (copy-on-write) of `source`, else a copy."""
    done = subprocess.run(["cp", "-c", str(source), str(target)], capture_output=True)
    if done.returncode:
        shutil.copyfile(source, target)


def vz_command(helper: str, disk: dict, directory: Path, size, memory: int, cpus: int, mac: str) -> list[str]:
    """The helper's command line for a machine whose disk (and macOS auxiliary storage) is
    already cloned into `directory`."""
    width, height = size
    command = [helper, "--disk", str(directory / "disk.img"), "--cpus", str(int(cpus)), "--memory",
               str(int(memory)), "--width", str(int(width)), "--height", str(int(height)), "--mac", mac]
    if disk["guest"] == "macos":
        config = json.loads((Path(disk["path"]) / "config.json").read_text(encoding="utf-8"))
        command += ["--macos", "--aux", str(directory / "nvram.bin"), "--hardware-model", config["hardwareModel"]]
    else:
        command += ["--efi-store", str(directory / "efivars.bin")]
    return command


def _start_vz(request: dict, directory: Path, children: list) -> dict:
    disk = request["image"]
    source = Path(disk["path"])
    if disk["format"] == "tart":
        _clone(source / "disk.img", directory / "disk.img")
        if disk["guest"] == "macos":
            _clone(source / "nvram.bin", directory / "nvram.bin")
    else:
        _clone(source, directory / "disk.img")
    mac = mac_address()
    command = vz_command(request["helper"], disk, directory, request["size"], request["memory"], request["cpus"], mac)
    log = open(directory / "vz.log", "ab")
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
    finally:
        log.close()
    children.append(process)
    started = json.loads(process.stdout.readline().decode("utf-8") or "{}")
    if started.get("error") or not started:
        raise RuntimeError(f"Virtualization.framework: {started.get('error') or 'the helper ended'}")
    deadline = time.monotonic() + VZ_SECONDS
    address = None
    while address is None:
        address = lease(mac)
        if address is None:
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("the machine got no network address (DHCP) in time")
            time.sleep(1.0)
    while True:
        try:
            socket.create_connection((address, 5900), timeout=2).close()
            break
        except OSError:
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"the machine's screen (VNC at {address}:5900) did not open in time: turn on "
                                   "Screen Sharing in the guest") from None
            time.sleep(1.0)
    return {"name": f"vm-{process.pid}", "vnc": {"host": address, "port": 5900}, "user": request["user"],
            "password": request["password"], "accelerator": "vz", "hypervisor": "vz"}


def _end_vz(children) -> None:
    process = next((child for child in children if isinstance(child, subprocess.Popen)), None)
    if process is None:
        return
    try:
        process.stdin.close()
    except OSError:
        pass
    try:
        process.wait(15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


# -- the guard ---------------------------------------------------------------------------------

def _guard() -> int:
    """Read the request, start the machine, print where its screen is; end it and delete its
    layer when standard input closes."""
    request = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
    directory = Path(request["directory"])
    children = []
    end_machine = _end_vz if request["hypervisor"] == "vz" else _end_qemu
    ended = threading.Event()

    def end(*_):
        if ended.is_set():
            return
        ended.set()
        end_machine(children)
        for name in ("disk.qcow2", "disk.img", "nvram.bin", "efivars.fd", "efivars.bin", "qmp.sock",
                     "screen.ppm"):
            for _ in range(20):
                try:
                    (directory / name).unlink(missing_ok=True)
                    break
                except OSError:
                    time.sleep(0.25)
        os._exit(0)

    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, end)
        signal.signal(signal.SIGHUP, end)
    try:
        start = _start_vz if request["hypervisor"] == "vz" else _start_qemu
        answer = start(request, directory, children)
        print(json.dumps(answer), flush=True)
    except Exception as error:
        print(json.dumps({"error": str(error)}), flush=True)
        end()
    while True:
        try:
            line = sys.stdin.buffer.readline()
        except (InterruptedError, OSError):
            break
        if not line:
            break
        try:
            if request["hypervisor"] != "qemu":
                raise ValueError("this machine's screen is served by its guest, not the guard")
            answer = _serve_qemu(json.loads(line.decode("utf-8")), directory, children)
        except Exception as error:
            answer = {"error": f"{type(error).__name__}: {error}"}
        print(json.dumps(answer), flush=True)
    end()
    return 0


if __name__ == "__main__":
    sys.exit(_guard())
