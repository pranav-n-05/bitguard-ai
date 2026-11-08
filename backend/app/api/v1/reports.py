import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select

from app.api.deps import PageDep, SessionDep, require
from app.core.errors import NotFoundError
from app.models import ReportRecord, User
from app.reports import service as svc
from app.schemas.cases import ReportOut, ReportRequest
from app.schemas.common import Paginated
from app.services import audit

router = APIRouter(prefix="/reports", tags=["reports"])
MEDIA = {"pdf": "application/pdf", "csv": "text/csv; charset=utf-8", "json": "application/json"}


@router.get("", response_model=Paginated[ReportOut])
async def list_reports(
    s: SessionDep, page: PageDep, _: Annotated[User, Depends(require("case.read"))], investigation_id: uuid.UUID | None = None
) -> Paginated[ReportOut]:
    q = select(ReportRecord)
    if investigation_id:
        q = q.where(ReportRecord.investigation_id == investigation_id)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (await s.execute(q.order_by(ReportRecord.generated_at.desc()).limit(page.limit).offset(page.offset))).scalars()
    return Paginated(items=[ReportOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.post("/generate", response_model=ReportOut, status_code=201)
async def generate(body: ReportRequest, s: SessionDep, user: Annotated[User, Depends(require("report.generate"))]) -> ReportOut:
    rec = await svc.generate(s, user, body.report_type, body.format, body.parameters)
    await s.commit()
    return ReportOut.model_validate(rec)


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: uuid.UUID, s: SessionDep, _: Annotated[User, Depends(require("case.read"))]) -> ReportOut:
    r = await s.get(ReportRecord, report_id)
    if r is None:
        raise NotFoundError("Report not found")
    return ReportOut.model_validate(r)


@router.get(
    "/{report_id}/download", response_class=Response, responses={200: {"content": {"application/pdf": {}, "text/csv": {}}}}
)
async def download(report_id: uuid.UUID, s: SessionDep, user: Annotated[User, Depends(require("report.generate"))]) -> Response:
    r = await s.get(ReportRecord, report_id)
    if r is None:
        raise NotFoundError("Report not found")
    data = svc.read_verified(r)
    await audit.record(s, "report.downloaded", "report", str(r.id), actor_id=user.id, actor_email=user.email)
    await s.commit()
    return Response(
        data,
        media_type=MEDIA[r.format],
        headers={
            "Content-Disposition": f'attachment; filename="bitguard-{r.report_type}-{r.id}.{r.format}"',
            "X-Content-SHA256": r.sha256,
        },
    )
