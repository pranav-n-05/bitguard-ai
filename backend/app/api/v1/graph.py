import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import PageDep, SessionDep, apply_sort, require
from app.core.errors import NotFoundError
from app.graph import query as gq
from app.models import AddressCluster, ClusterMembership, GraphDetection, User
from app.models.base import ReviewStatus
from app.schemas.common import Paginated
from app.schemas.intel import ClusterDetail, ClusterOut, DetectionOut
from app.services import audit

router = APIRouter(prefix="/graph", tags=["graph"])
Reader = Annotated[User, Depends(require("intel.read"))]
ADDR = Annotated[str, Query(min_length=14, max_length=100)]


@router.get("/path", summary="Shortest path between two addresses over the bipartite graph")
async def path(
    s: SessionDep, _: Reader, source: ADDR, target: ADDR, max_hops: Annotated[int, Query(ge=1, le=8)] = 4
) -> dict[str, Any]:
    return await gq.shortest_path(s, source, target, max_hops)


@router.get("/detections", response_model=Paginated[DetectionOut])
async def detections(
    s: SessionDep,
    page: PageDep,
    _: Reader,
    pattern: Annotated[str | None, Query(max_length=48)] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
) -> Paginated[DetectionOut]:
    q = select(GraphDetection)
    if pattern:
        q = q.where(GraphDetection.pattern == pattern)
    if min_confidence is not None:
        q = q.where(GraphDetection.confidence >= min_confidence)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    q = apply_sort(q, GraphDetection, page.sort, {"confidence", "window_start", "pattern"}, GraphDetection.confidence.desc())
    rows = (await s.execute(q.limit(page.limit).offset(page.offset))).scalars().all()
    return Paginated(items=[DetectionOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/clusters", response_model=Paginated[ClusterOut])
async def clusters(
    s: SessionDep,
    page: PageDep,
    _: Reader,
    method: Annotated[str | None, Query(pattern="^(common_input|change_output|behavioural)$")] = None,
    min_size: Annotated[int, Query(ge=2)] = 2,
    review_status: ReviewStatus | None = None,
) -> Paginated[ClusterOut]:
    q = select(AddressCluster).where(AddressCluster.size >= min_size)
    if method:
        q = q.where(AddressCluster.method == method)
    if review_status:
        q = q.where(AddressCluster.review_status == review_status)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    q = apply_sort(q, AddressCluster, page.sort, {"size", "confidence", "created_at"}, AddressCluster.size.desc())
    rows = (await s.execute(q.limit(page.limit).offset(page.offset))).scalars().all()
    return Paginated(items=[ClusterOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/clusters/{cluster_id}", response_model=ClusterDetail)
async def cluster(cluster_id: uuid.UUID, s: SessionDep, _: Reader) -> ClusterDetail:
    c = await s.get(AddressCluster, cluster_id)
    if c is None:
        raise NotFoundError("Cluster not found (clusters are recomputed on each analysis run)")
    members = (
        await s.execute(
            select(ClusterMembership)
            .where(ClusterMembership.cluster_id == cluster_id)
            .order_by(ClusterMembership.link_confidence.desc())
            .limit(1000)
        )
    ).scalars()
    return ClusterDetail(
        **ClusterOut.model_validate(c).model_dump(),
        members=[
            {"address": m.address, "link_confidence": m.link_confidence, "evidence_txids": m.evidence_txids} for m in members
        ],
    )


class ClusterReview(BaseModel):
    review_status: ReviewStatus
    note: str | None = None


@router.patch("/clusters/{cluster_id}", response_model=ClusterOut, summary="Record analyst review of a cluster")
async def review_cluster(
    cluster_id: uuid.UUID, body: ClusterReview, s: SessionDep, user: Annotated[User, Depends(require("alert.acknowledge"))]
) -> ClusterOut:
    c = await s.get(AddressCluster, cluster_id)
    if c is None:
        raise NotFoundError("Cluster not found")
    old = c.review_status
    c.review_status, c.reviewed_by = body.review_status, user.id
    await audit.record(
        s,
        "cluster.reviewed",
        "cluster",
        str(cluster_id),
        actor_id=user.id,
        actor_email=user.email,
        details={"from": old.value, "to": body.review_status.value, "note": body.note},
    )
    await s.commit()
    await s.refresh(c)
    return ClusterOut.model_validate(c)
