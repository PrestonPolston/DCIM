"""Item 47f / REVIEW_REMOVAL_SCRIPT: where removal exports may be written.

The file goes in DCIM_EXPORT_DIR (0700, owned by the operator), never inside the repository, apps/web,
any dist/ build output, /var/www or a configured static root. --export takes a bare file name."""
import os
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
FORBIDDEN_ROOTS = (REPO_ROOT, Path("/var/www"), Path("/srv/www"), Path("/usr/share/nginx"))


class ExportPolicyError(Exception):
    pass


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def export_dir(configured: str | None, extra_forbidden=()) -> Path:
    if not configured:
        raise ExportPolicyError("DCIM_EXPORT_DIR is not set; exports are refused")
    d = Path(configured).expanduser().resolve()
    static_root = os.environ.get("DCIM_STATIC_ROOT")
    roots = [*FORBIDDEN_ROOTS, *(Path(r) for r in extra_forbidden), *([Path(static_root)] if static_root else [])]
    for root in roots:
        if _inside(d, root):
            raise ExportPolicyError(f"DCIM_EXPORT_DIR {d} is inside {root} (repo or web root); refused")
    if any(part in ("dist", "www") for part in d.parts):
        raise ExportPolicyError(f"DCIM_EXPORT_DIR {d} looks like a web/build directory; refused")
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = d.stat()
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise ExportPolicyError(f"DCIM_EXPORT_DIR {d} must be 0700 (is {oct(stat.S_IMODE(st.st_mode))})")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise ExportPolicyError(f"DCIM_EXPORT_DIR {d} is not owned by the current user")
    return d


def export_target(configured: str | None, name: str) -> Path:
    if not name or Path(name).name != name or name.startswith("."):
        raise ExportPolicyError("--export takes a plain file name; it is written inside DCIM_EXPORT_DIR")
    return export_dir(configured) / name
