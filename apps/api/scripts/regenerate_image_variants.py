"""Backfill/regenerate derived profile image variants (thumb 512 px, tex 1024 px WebP) from stored originals.

    python scripts/regenerate_image_variants.py              # dry run: lists originals missing a variant
    python scripts/regenerate_image_variants.py --execute    # create the missing variants (idempotent)
    python scripts/regenerate_image_variants.py --execute --all   # also rebuild existing thumb/tex rows

Non-destructive: originals are never modified; only thumb/tex rows are inserted (or, with --all, rewritten).
Run after `alembic upgrade head` (needs p1_22_profile_image_tex). Uses DCIM_DATABASE_URL like the app.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

import app.models  # noqa: E402,F401
from app.modules.images import service  # noqa: E402
from app.modules.images.models import ProfileImageRow as I  # noqa: E402


def run(session: Session, execute: bool = False, rebuild: bool = False) -> dict:
    have = {(p, f, v): i for i, p, f, v in session.exec(select(I.id, I.profile_id, I.face, I.variant)).all()}
    originals = [(p, f) for (p, f, v) in have if v == "original"]
    todo = [(p, f) for p, f in originals if rebuild or any((p, f, v) not in have for v in service.DERIVED)]
    created = updated = 0
    if execute:
        for p, f in todo:
            orig = session.get(I, have[(p, f, "original")])
            for variant, info in service.process(bytes(orig.data), orig.content_type).items():
                if variant == "original":
                    continue
                rid = have.get((p, f, variant))
                if rid is None:
                    session.add(I(profile_id=p, face=f, variant=variant, uploaded_by="script", **info))
                    created += 1
                elif rebuild:
                    row = session.get(I, rid)
                    if row.sha256 != info["sha256"]:
                        for k, val in info.items():
                            setattr(row, k, val)
                        row.version += 1
                        updated += 1
        session.commit()
    return {"originals": len(originals), "pending": len(todo), "created": created, "updated": updated}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--all", action="store_true", help="rebuild existing derived variants too")
    a = ap.parse_args()
    from app.db import engine
    with Session(engine) as s:
        print(run(s, a.execute, a.all))
    return 0


if __name__ == "__main__":
    sys.exit(main())
