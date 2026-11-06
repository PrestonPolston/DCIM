from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session, select

from app.crud import crud_router
from app.db import commit_or_409, get_session
from app.modules.auth.deps import ADMIN, TECH, get_current_user
from app.modules.directory.models import (
    ContactRow, GroupRow, ProjectContactRow, ProjectReferenceRow, ProjectRow, VendorRow,
)
from app.modules.directory.schemas import (
    Contact, ContactCreate, ContactUpdate, Group, GroupCreate, GroupUpdate, Project, ProjectContact,
    ProjectContactCreate, ProjectCreate, ProjectUpdate, Reference, ReferenceCreate, Vendor, VendorCreate,
    VendorUpdate,
)
from app.modules.locations.models import SiteRow
from app.modules.locations.service import get_or_404

router = APIRouter(dependencies=[Depends(get_current_user)])


def _check_vendor(session, obj):
    if obj.vendor_id is not None:
        get_or_404(session, VendorRow, obj.vendor_id, "Vendor")
    if not obj.name and not obj.email:
        raise HTTPException(status_code=422, detail="A contact needs a name or an email")


def _check_site(session, obj):
    if obj.site_id is not None:
        get_or_404(session, SiteRow, obj.site_id, "Site")


def _vendor_in_use(session, obj):
    return session.exec(select(ContactRow.id).where(ContactRow.vendor_id == obj.id)).first() is not None


crud_router(router, "/groups", GroupRow, GroupCreate, GroupUpdate, Group, "Group",
            "A group with this name already exists (names are case-insensitive)", [GroupRow.name])
crud_router(router, "/vendors", VendorRow, VendorCreate, VendorUpdate, Vendor, "Vendor",
            "A vendor with this name already exists (names are case-insensitive)", [VendorRow.name])
crud_router(router, "/contacts", ContactRow, ContactCreate, ContactUpdate, Contact, "Contact",
            "A contact with this email already exists", [ContactRow.name, ContactRow.email, ContactRow.organization],
            before_save=_check_vendor)
crud_router(router, "/projects", ProjectRow, ProjectCreate, ProjectUpdate, Project, "Project",
            "A project with this intake_id already exists", [ProjectRow.name, ProjectRow.intake_id],
            before_save=_check_site)


# ---- ticket references ----
@router.get("/projects/{project_id}/references", response_model=list[Reference])
def list_references(project_id: int, session: Session = Depends(get_session)):
    get_or_404(session, ProjectRow, project_id, "Project")
    return session.exec(select(ProjectReferenceRow).where(ProjectReferenceRow.project_id == project_id)
                        .order_by(ProjectReferenceRow.id)).all()


@router.post("/projects/{project_id}/references", response_model=Reference, status_code=201,
             dependencies=[Depends(TECH)])
def add_reference(project_id: int, payload: ReferenceCreate, session: Session = Depends(get_session)):
    get_or_404(session, ProjectRow, project_id, "Project")
    ref = ProjectReferenceRow(project_id=project_id, **payload.model_dump())
    session.add(ref)
    commit_or_409(session, "This project already has that reference")
    session.refresh(ref)
    return ref


@router.delete("/projects/{project_id}/references/{ref_id}", status_code=204, dependencies=[Depends(TECH)])
def delete_reference(project_id: int, ref_id: int, session: Session = Depends(get_session)):
    ref = session.get(ProjectReferenceRow, ref_id)
    if ref is None or ref.project_id != project_id:
        raise HTTPException(status_code=404, detail="Reference not found")
    session.delete(ref)
    session.commit()
    return Response(status_code=204)


# Ticket lookup: which project(s) carry CHG123?
@router.get("/project-references", response_model=list[Reference])
def find_references(kind: str = Query(..., max_length=8), ref: str = Query(..., max_length=64),
                    session: Session = Depends(get_session)):
    return session.exec(select(ProjectReferenceRow).join(ProjectRow)
                        .where(ProjectReferenceRow.kind == kind.upper(), ProjectReferenceRow.ref == ref,
                               ProjectRow.deleted_at.is_(None))).all()


# ---- project contacts ----
@router.get("/projects/{project_id}/contacts", response_model=list[ProjectContact])
def list_project_contacts(project_id: int, session: Session = Depends(get_session)):
    get_or_404(session, ProjectRow, project_id, "Project")
    return session.exec(select(ProjectContactRow).where(ProjectContactRow.project_id == project_id)).all()


@router.post("/projects/{project_id}/contacts", response_model=ProjectContact, status_code=201,
             dependencies=[Depends(TECH)])
def add_project_contact(project_id: int, payload: ProjectContactCreate, session: Session = Depends(get_session)):
    get_or_404(session, ProjectRow, project_id, "Project")
    get_or_404(session, ContactRow, payload.contact_id, "Contact")
    link = ProjectContactRow(project_id=project_id, **payload.model_dump())
    session.add(link)
    commit_or_409(session, "That contact already has this role on the project")
    session.refresh(link)
    return link


@router.delete("/projects/{project_id}/contacts/{contact_id}", status_code=204, dependencies=[Depends(TECH)])
def remove_project_contact(project_id: int, contact_id: int, contact_role: str = Query(...),
                           session: Session = Depends(get_session)):
    link = session.get(ProjectContactRow, (project_id, contact_id, contact_role))
    if link is None:
        raise HTTPException(status_code=404, detail="Project contact not found")
    session.delete(link)
    session.commit()
    return Response(status_code=204)


_TAGS = {"/groups": "groups", "/vendors": "contacts", "/contacts": "contacts"}
for r in router.routes:
    r.tags = [next((t for p, t in _TAGS.items() if r.path.startswith(p)), "projects")]
