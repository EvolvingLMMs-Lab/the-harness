"""Persistent read-only same-origin attachment serving for the app.

Serves files saved under an identity's `sessions/<chat>/files/` directory by attachment ID:
    GET /api/app/attachments/<id>?identity=<identity>&chat=<chat>
    GET /api/app/attachments?id=<id>&identity=<identity>&chat=<chat>

Security guarantees:
- Strict ID allowlist (`^[A-Za-z0-9_-]{4,64}$`); rejects traversal/encoded slashes with 403.
- Rejects symlinks and any path escaping `sessions/<chat>/files/` with 403.
- Accurate Content-Type with `X-Content-Type-Options: nosniff` and sandboxed CSP.
"""
from __future__ import annotations

from http import HTTPStatus
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import quote, unquote

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_CHAT_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

# Active/executable MIME types that must never execute inline.
_FORCE_TEXT_TYPES = {"text/html", "application/xhtml+xml", "application/javascript", "text/javascript"}
_FORCE_ATTACHMENT_TYPES = {"image/svg+xml"}


def attachment_url(attachment_id: str, *, identity: str | None = None, chat: str | None = None) -> str:
    """Same-origin read-only URL for an attachment descriptor."""
    base = f"/api/app/attachments/{quote(str(attachment_id), safe='')}"
    params = []
    if identity:
        params.append(f"identity={quote(str(identity), safe='')}")
    if chat:
        params.append(f"chat={quote(str(chat), safe='')}")
    return f"{base}?{'&'.join(params)}" if params else base


def _one(body, key, default=None):
    val = body.get(key, default)
    return val[0] if isinstance(val, list) else val


def _send_json_error(status: HTTPStatus, message: str):
    payload = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")

    def _serve(handler):
        handler._send(
            status,
            payload,
            "application/json; charset=utf-8",
            [("X-Content-Type-Options", "nosniff")],
        )

    return _serve


def _valid_id(raw: str) -> bool:
    if not raw or "/" in raw or "\\" in raw or ".." in raw or "%" in raw or "\x00" in raw:
        return False
    decoded = unquote(raw)
    if decoded != raw or "/" in decoded or "\\" in decoded or ".." in decoded:
        return False
    return bool(_ID_RE.fullmatch(raw))


def _guess_mime(row: dict, filename: str) -> str:
    for key in ("mime", "type"):
        val = str(row.get(key) or "").split(";")[0].strip().lower()
        if val and val != "application/octet-stream" and "/" in val:
            return val
    guessed, _ = mimetypes.guess_type(str(row.get("name") or filename))
    return (guessed or "application/octet-stream").lower()


def _load_index(files_dir: Path) -> list[dict]:
    index_path = files_dir / "index.json"
    if not index_path.is_file() or index_path.is_symlink():
        return []
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _locate_attachment(identity_dir: Path, chat_id: str | None, attachment_id: str):
    """Return `(files_dir, row)` or `None` if not found; raises PermissionError on unsafe layout."""
    sessions_root = identity_dir / "sessions"
    if not sessions_root.is_dir():
        return None
    if chat_id is not None:
        if not _CHAT_RE.fullmatch(chat_id):
            raise PermissionError("invalid chat id")
        chat_dir = sessions_root / chat_id
        if chat_dir.is_symlink():
            raise PermissionError("symlinked chat directory")
        files_dir = chat_dir / "files"
        if files_dir.is_symlink():
            raise PermissionError("symlinked files directory")
        for row in _load_index(files_dir):
            if isinstance(row, dict) and row.get("id") == attachment_id:
                return files_dir, row
        return None

    for chat_dir in sorted(sessions_root.iterdir()):
        if not chat_dir.is_dir() or chat_dir.is_symlink():
            continue
        files_dir = chat_dir / "files"
        if not files_dir.is_dir() or files_dir.is_symlink():
            continue
        for row in _load_index(files_dir):
            if isinstance(row, dict) and row.get("id") == attachment_id:
                return files_dir, row
    return None


def _resolve_contained(files_dir: Path, filename: str) -> Path:
    if (
        not filename
        or "\x00" in filename
        or "/" in filename
        or "\\" in filename
        or filename in (".", "..")
        or Path(filename).name != filename
    ):
        raise PermissionError("invalid attachment filename")
    if files_dir.is_symlink():
        raise PermissionError("symlinked files directory")
    root_resolved = files_dir.resolve()
    candidate = files_dir / filename
    if candidate.is_symlink():
        raise PermissionError("symlinked attachment blocked")
    resolved = candidate.resolve()
    if root_resolved not in resolved.parents:
        raise PermissionError("attachment escapes files directory")
    if not resolved.is_file():
        raise FileNotFoundError(filename)
    return resolved


def serve_attachment(server, body):
    """GET /api/app/attachments/<id> or /api/app/attachments?id=<id>."""
    from . import host as app_host

    raw_id = str(_one(body, "_raw_id") or _one(body, "id") or "")
    if not _valid_id(raw_id):
        return _send_json_error(HTTPStatus.FORBIDDEN, "invalid attachment id")

    chat_raw = _one(body, "chat")
    chat_id = str(chat_raw).strip() if chat_raw is not None and str(chat_raw).strip() else None
    if chat_id is not None and not _CHAT_RE.fullmatch(chat_id):
        return _send_json_error(HTTPStatus.FORBIDDEN, "invalid chat id")

    try:
        identity_row = app_host._identity_row(server, _one(body, "identity"))
    except ValueError:
        return _send_json_error(HTTPStatus.NOT_FOUND, "identity not found")

    identity_dir = Path(identity_row["folder"])
    try:
        located = _locate_attachment(identity_dir, chat_id, raw_id)
    except PermissionError as exc:
        return _send_json_error(HTTPStatus.FORBIDDEN, str(exc))

    if located is None:
        return _send_json_error(HTTPStatus.NOT_FOUND, "attachment not found")

    files_dir, row = located
    filename = str(row.get("file") or "")
    try:
        target = _resolve_contained(files_dir, filename)
    except PermissionError as exc:
        return _send_json_error(HTTPStatus.FORBIDDEN, str(exc))
    except FileNotFoundError:
        return _send_json_error(HTTPStatus.NOT_FOUND, "attachment file missing")

    mime = _guess_mime(row, filename)
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("Cache-Control", "private, max-age=3600"),
        ("Content-Security-Policy", "default-src 'none'; sandbox"),
    ]
    if mime in _FORCE_TEXT_TYPES or mime in _FORCE_ATTACHMENT_TYPES:
        if mime in _FORCE_TEXT_TYPES:
            mime = "text/plain; charset=utf-8"
        safe_name = re.sub(r'[^A-Za-z0-9._-]', "_", str(row.get("name") or target.name))[:80] or "attachment"
        headers.append(("Content-Disposition", f'attachment; filename="{safe_name}"'))

    data = target.read_bytes()

    def _serve(handler):
        handler._send(HTTPStatus.OK, data, mime, headers)

    return _serve
