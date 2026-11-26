"""Native modern OS folder picker dialogs (zero third-party dependencies).

On Windows: invokes COM IFileOpenDialog with FOS_PICKFOLDERS via stdlib ctypes,
producing the modern Explorer folder picker (address bar, Quick Access, search)
anchored to the active foreground window — never the legacy Win98 FolderBrowserDialog.
On macOS: invokes NSOpenPanel via osascript.
On Linux: invokes zenity or kdialog when a display session is active.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys


def _pick_folder_windows(initial: str = "", title: str = "Open folder") -> dict:
    """Call Windows Vista+ COM IFileOpenDialog (FOS_PICKFOLDERS) on an STA thread."""
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def _guid(text: str) -> GUID:
        g = GUID()
        hr = ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        if hr != 0:
            raise OSError(f"CLSIDFromString failed: 0x{hr & 0xffffffff:08x}")
        return g

    CLSID_FileOpenDialog = _guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")
    IID_IFileOpenDialog = _guid("{D57C7288-D4AD-4768-BE02-9D969532D960}")
    IID_IShellItem = _guid("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")

    COINIT_APARTMENTTHREADED = 0x2
    COINIT_DISABLE_OLE1DDE = 0x4
    CLSCTX_INPROC_SERVER = 0x1
    FOS_PICKFOLDERS = 0x00000020
    FOS_FORCEFILESYSTEM = 0x00000040
    FOS_PATHMUSTEXIST = 0x00000800
    SIGDN_FILESYSPATH = 0x80058000
    HRESULT_CANCELLED = 0x800704C7

    def _vtable(ptr, index, restype, *argtypes):
        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])

    hr_init = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE)
    did_init = hr_init in (0, 1)  # S_OK or S_FALSE
    dialog = ctypes.c_void_p()
    init_item = ctypes.c_void_p()
    result_item = ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_FileOpenDialog), None, CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_IFileOpenDialog), ctypes.byref(dialog),
        )
        if hr != 0 or not dialog:
            return {"path": None, "cancelled": False, "supported": False}

        # IFileDialog vtable indices (inherits IUnknown[0..2], IModalWindow[3]):
        #   3: Show(hwndOwner)
        #   9: SetOptions(fos)
        #  10: GetOptions(pfos)
        #  12: SetFolder(psi)
        #  17: SetTitle(pszTitle)
        #  20: GetResult(ppsi)
        get_opts = _vtable(dialog, 10, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
        set_opts = _vtable(dialog, 9, ctypes.c_long, wintypes.DWORD)
        set_folder = _vtable(dialog, 12, ctypes.c_long, ctypes.c_void_p)
        set_title = _vtable(dialog, 17, ctypes.c_long, ctypes.c_wchar_p)
        show = _vtable(dialog, 3, ctypes.c_long, wintypes.HWND)
        get_result = _vtable(dialog, 20, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))

        opts = wintypes.DWORD(0)
        get_opts(dialog, ctypes.byref(opts))
        set_opts(dialog, opts.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST)
        if title:
            set_title(dialog, title)

        if initial and Path(initial).is_dir():
            shell32.SHCreateItemFromParsingName.argtypes = [
                ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
            ]
            shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
            if shell32.SHCreateItemFromParsingName(str(Path(initial).resolve()), None, ctypes.byref(IID_IShellItem), ctypes.byref(init_item)) == 0 and init_item:
                set_folder(dialog, init_item)

        hwnd = user32.GetForegroundWindow()
        hr_show = show(dialog, hwnd)
        if (hr_show & 0xffffffff) == HRESULT_CANCELLED:
            return {"path": None, "cancelled": True, "supported": True}
        if hr_show != 0:
            return {"path": None, "cancelled": True, "supported": True}

        if get_result(dialog, ctypes.byref(result_item)) != 0 or not result_item:
            return {"path": None, "cancelled": True, "supported": True}

        # IShellItem::GetDisplayName is vtable index 5
        get_display = _vtable(result_item, 5, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
        name_ptr = ctypes.c_void_p()
        if get_display(result_item, SIGDN_FILESYSPATH, ctypes.byref(name_ptr)) != 0 or not name_ptr:
            return {"path": None, "cancelled": True, "supported": True}
        try:
            chosen = ctypes.wstring_at(name_ptr.value)
        finally:
            ole32.CoTaskMemFree(name_ptr)
        return {"path": chosen or None, "cancelled": not chosen, "supported": True}
    finally:
        for ptr in (result_item, init_item, dialog):
            if ptr:
                try:
                    _vtable(ptr, 2, ctypes.c_ulong)(ptr)  # IUnknown::Release
                except Exception:
                    pass
        if did_init:
            ole32.CoUninitialize()


def pick_folder(initial: str = "", title: str = "Open folder") -> dict:
    """Invoke the modern native OS folder dialog; returns {path, cancelled, supported}."""
    if os.environ.get("HARNESS_NO_NATIVE_DIALOG"):
        return {"path": None, "cancelled": False, "supported": False}
    try:
        if os.name == "nt":
            import threading

            box = {}

            def _run():
                try:
                    box["res"] = _pick_folder_windows(initial=initial, title=title)
                except Exception:
                    box["res"] = {"path": None, "cancelled": False, "supported": False}

            t = threading.Thread(target=_run, name="win-folder-dialog", daemon=True)
            t.start()
            t.join(timeout=300)
            return box.get("res") or {"path": None, "cancelled": True, "supported": True}
        if sys.platform == "darwin":
            script = 'POSIX path of (choose folder with prompt "Open folder")'
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
            chosen = res.stdout.strip()
            return {"path": chosen or None, "cancelled": not chosen, "supported": True}
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            zenity = shutil.which("zenity")
            if zenity:
                cmd = [zenity, "--file-selection", "--directory", f"--title={title}"]
                if initial and Path(initial).is_dir():
                    cmd.append(f"--filename={Path(initial).resolve()}/")
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                chosen = res.stdout.strip()
                return {"path": chosen or None, "cancelled": not chosen, "supported": True}
            kdialog = shutil.which("kdialog")
            if kdialog:
                res = subprocess.run([kdialog, "--getexistingdirectory", initial or str(Path.home())],
                                     capture_output=True, text=True, timeout=300)
                chosen = res.stdout.strip()
                return {"path": chosen or None, "cancelled": not chosen, "supported": True}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"path": None, "cancelled": False, "supported": False}
