import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.deps import PageDep, SessionDep, apply_sort, require
from app.core.errors import NotFoundError
from app.investigations import service as svc
from app.models import EvidenceRecord, Investigation, User
from app.models.base import CaseStatus, Severity
from app.reports import service as reports
from app.schemas.cases import CaseCreate, CaseOut, CasePatch, EvidenceIn, EvidenceOut, ExportIn, Links, NoteIn, ReportOut
from app.schemas.common import Paginated

router = APIRouter(prefix="/investigations", tags=["investigations"])
Reader = Annotated[User, Depends(require("case.read"))]


@router.get("", response_model=Paginated[CaseOut])
async def list_cases(
    s: SessionDep,
    page: PageDep,
    _: Reader,
    status: Annotated[list[CaseStatus] | None, Query()] = None,
    priority: Annotated[list[Severity] | None, Query()] = None,
    assigned_to: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Paginated[CaseOut]:
    stmt = select(Investigation)
    if status:
        stmt = stmt.where(Investigation.status.in_(status))
    if priority:
        stmt = stmt.where(Investigation.priority.in_(priority))
    if assigned_to:
        stmt = stmt.where(Investigation.assigned_to == assigned_to)
    if q:
        stmt = stmt.where(or_(Investigation.title.ilike(f"%{q}%"), Investigation.case_number == q))
    total = await s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = apply_sort(
        stmt, Investigation, page.sort, {"created_at", "updated_at", "priority", "status"}, Investigation.updated_at.desc()
    )
    rows = (await s.execute(stmt.limit(page.limit).offset(page.offset))).scalars().all()
    return Paginated(items=[CaseOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=CaseOut, status_code=201)
async def create_case(body: CaseCreate, s: SessionDep, user: Annotated[User, Depends(require("case.create"))]) -> CaseOut:
    c = await svc.create(
        s,
        user,
        body.title,
        body.summary,
        body.priority,
        body.assigned_to,
        body.model_dump(include={"txids", "addresses", "alert_ids", "observation_ids"}),
    )
    await s.commit()
    await s.refresh(c)
    return CaseOut.model_validate(c)


@router.get("/{case_id}")
async def get_case(case_id: uuid.UUID, s: SessionDep, _: Reader) -> dict[str, Any]:
    await svc.get_case(s, case_id)
    return await reports.case_bundle(s, case_id)


@router.patch("/{case_id}", response_model=CaseOut)
async def patch_case(
    case_id: uuid.UUID, body: CasePatch, s: SessionDep, user: Annotated[User, Depends(require("case.create"))]
) -> CaseOut:
    c = await svc.get_case(s, case_id, lock=True)
    changes = body.model_dump(exclude_unset=True, exclude={"unassign"})
    if body.unassign:
        changes["assigned_to"] = None
    await svc.update(s, c, user, changes)
    await s.commit()
    await s.refresh(c)
    return CaseOut.model_validate(c)


@router.post("/{case_id}/entities", summary="Link transactions, addresses, alerts or network observations")
async def link_entities(
    case_id: uuid.UUID, body: Links, s: SessionDep, user: Annotated[User, Depends(require("case.create"))]
) -> dict[str, int]:
    c = await svc.get_case(s, case_id, lock=True)
    added = await svc.link(s, c, user, body.model_dump(mode="json"))
    await s.commit()
    return added


@router.post("/{case_id}/notes", status_code=201)
async def add_note(
    case_id: uuid.UUID, body: NoteIn, s: SessionDep, user: Annotated[User, Depends(require("case.create"))]
) -> dict[str, Any]:
    c = await svc.get_case(s, case_id)
    n = await svc.add_note(s, c, user, body.body)
    await s.commit()
    return {"id": n.id, "body": n.body, "author_id": str(n.author_id), "created_at": n.created_at}


@router.post("/{case_id}/evidence", response_model=EvidenceOut, status_code=201)
async def attach_evidence(
    case_id: uuid.UUID, body: EvidenceIn, s: SessionDep, user: Annotated[User, Depends(require("evidence.attach"))]
) -> EvidenceOut:
    c = await svc.get_case(s, case_id, lock=True)
    ev = await svc.attach_evidence(s, c, user, body.evidence_type, body.reference, body.description)
    await s.commit()
    return EvidenceOut.model_validate(ev)


@router.get("/{case_id}/evidence", response_model=list[EvidenceOut])
async def list_evidence(case_id: uuid.UUID, s: SessionDep, _: Reader) -> list[EvidenceOut]:
    await svc.get_case(s, case_id)
    rows = (
        await s.execute(select(EvidenceRecord).where(EvidenceRecord.investigation_id == case_id).order_by(EvidenceRecord.id))
    ).scalars()
    return [EvidenceOut.model_validate(r) for r in rows]


@router.get("/{case_id}/evidence/{evidence_id}/verify", summary="Recompute integrity and provenance hashes")
async def verify_evidence(case_id: uuid.UUID, evidence_id: int, s: SessionDep, _: Reader) -> dict[str, Any]:
    ev = await s.get(EvidenceRecord, evidence_id)
    if ev is None or ev.investigation_id != case_id:
        raise NotFoundError("Evidence not found in this case")
    return await svc.verify_evidence(s, ev)


@router.post("/{case_id}/export", response_model=ReportOut, status_code=201)
async def export_case(
    case_id: uuid.UUID, body: ExportIn, s: SessionDep, user: Annotated[User, Depends(require("report.generate"))]
) -> ReportOut:
    await svc.get_case(s, case_id)
    rec = await reports.generate(s, user, "investigation_summary", body.format, {"investigation_id": str(case_id)})
    await s.commit()
    return ReportOut.model_validate(rec)
