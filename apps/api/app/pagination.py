from fastapi import Query, Response
from sqlmodel import Session, func, select


# Query params shared by every list endpoint
class Pagination:
    def __init__(
        self,
        limit: int = Query(50, ge=1, le=500, description="Max items to return"),
        offset: int = Query(0, ge=0, description="Items to skip"),
    ):
        self.limit = limit
        self.offset = offset


# Helper: run a filtered select with limit/offset; total goes in X-Total-Count
def paginate(session: Session, statement, pagination: Pagination, response: Response, order_by):
    total = session.exec(select(func.count()).select_from(statement.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    return session.exec(
        statement.order_by(order_by).offset(pagination.offset).limit(pagination.limit)
    ).all()


# Helper: case-insensitive "contains" with % and _ matched literally
def contains(column, q: str):
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")
