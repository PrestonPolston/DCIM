from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db import get_session
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import UserRow
from app.modules.home.constants import SEARCH_DEFAULT_LIMIT, SEARCH_MAX_LIMIT, SEARCH_MIN_CHARS
from app.modules.home.schemas import HomeSearch, HomeSummary
from app.modules.home.search import build_search
from app.modules.home.service import build_summary
from app.timestamps import utcnow

router = APIRouter(prefix="/home", tags=["home"], dependencies=[Depends(get_current_user)])


@router.get("/summary", response_model=HomeSummary)
def get_home_summary(session: Session = Depends(get_session),
                     user: UserRow = Depends(get_current_user)):
    """Counts and capped lists for the post-login home tiles this role can see."""
    return build_summary(session, user.role, utcnow())


@router.get("/search", response_model=HomeSearch)
def get_home_search(
    q: str = Query(..., max_length=100, description="Case-insensitive substring; at least 2 characters after trimming"),
    limit: int = Query(SEARCH_DEFAULT_LIMIT, ge=1, le=SEARCH_MAX_LIMIT, description="Maximum hits per group"),
    session: Session = Depends(get_session),
):
    """Quick search across devices, cabinets, rows and halls. DCREQ search is parked."""
    term = q.strip()
    if len(term) < SEARCH_MIN_CHARS:
        raise HTTPException(status_code=422, detail="q must be at least 2 characters")
    return build_search(session, term, limit, utcnow())
