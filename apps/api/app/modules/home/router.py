from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import UserRow
from app.modules.home.schemas import HomeSummary
from app.modules.home.service import build_summary
from app.timestamps import utcnow

router = APIRouter(prefix="/home", tags=["home"], dependencies=[Depends(get_current_user)])


@router.get("/summary", response_model=HomeSummary)
def get_home_summary(session: Session = Depends(get_session),
                     user: UserRow = Depends(get_current_user)):
    """Counts and capped lists for the post-login home tiles this role can see."""
    return build_summary(session, user.role, utcnow())
