from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, union_all

from app.api.deps import PageDep, SessionDep, require
from app.core.errors import NotFoundError
from app.graph import query as gq
from app.ingestion.address_codec import classify_address
from app.models import (
    Address,
    AddressCluster,
    AddressFeature,
    ClusterMembership,
    CorrelationIndicator,
    GraphDetection,
    InvestigationAddress,
    Transaction,
    TransactionInput,
    TransactionOutput,
    User,
)
from app.schemas.common import Paginated
from app.schemas.intel import AddressOut, AnalyzeRequest, TransactionOut
from app.services.intel import alert_counts, current_risk, detection_dict
from app.services.risk_read import analyze_address, risk_detail

router = APIRouter(prefix="/addresses", tags=["addresses"])
Reader = Annotated[User, Depends(require("intel.read"))]
NOTICE = (
    "An address is not a wallet or a person. Cluster, network and risk information below are probabilistic "
    "investigative indicators, not identity attribution."
)


async def _get(s: SessionDep, address: str) -> Address:
    a = await s.get(Address, address)
    if a is None:
        if classify_address(address) is None:
            raise NotFoundError("Not a valid Bitcoin address")
        raise NotFoundError("Address not present in ingested data")
    return a


@router.post("/analyze", summary="On-demand analysis for up to 50 addresses")
async def analyze(
    body: AnalyzeRequest, s: SessionDep, _: Annotated[User, Depends(require("intel.analyze"))]
) -> list[dict[str, Any]]:
    addrs = (body.addresses or [])[:50]
    if not addrs:
        from app.core.errors import AppError

        raise AppError("Provide addresses")
    out = []
    for a in addrs:
        try:
            out.append(await analyze_address(s, a))
        except NotFoundError:
            out.append({"address": a, "error": "not_found"})
    return out


@router.get("/{address}", response_model=AddressOut)
async def get_address(address: str, s: SessionDep, _: Reader) -> AddressOut:
    a = await _get(s, address)
    f = (
        (
            await s.execute(
                select(AddressFeature).where(AddressFeature.address == address).order_by(AddressFeature.computed_at.desc())
            )
        )
        .scalars()
        .first()
    )
    clusters = [
        {
            "cluster_id": str(r.id),
            "method": r.method,
            "cluster_confidence": r.confidence,
            "size": r.size,
            "link_confidence": r.link_confidence,
            "review_status": r.review_status.value,
            "limitations": r.limitations,
        }
        for r in await s.execute(
            select(
                AddressCluster.id,
                AddressCluster.method,
                AddressCluster.confidence,
                AddressCluster.size,
                AddressCluster.review_status,
                AddressCluster.limitations,
                ClusterMembership.link_confidence,
            )
            .join(ClusterMembership, ClusterMembership.cluster_id == AddressCluster.id)
            .where(ClusterMembership.address == address)
        )
    ]
    corr = [
        {
            "id": c.id,
            "type": c.indicator_type,
            "strength": c.strength,
            "confidence": c.confidence,
            "metrics": c.metrics,
            "limitations": c.limitations,
        }
        for c in (
            await s.execute(
                select(CorrelationIndicator).where(
                    CorrelationIndicator.entity_type == "address", CorrelationIndicator.entity_key == address
                )
            )
        ).scalars()
    ]
    dets = (await s.execute(select(GraphDetection).where(GraphDetection.addresses.contains([address])).limit(50))).scalars()
    cases = (
        await s.execute(select(InvestigationAddress.investigation_id).where(InvestigationAddress.address == address))
    ).scalars()
    risk = await current_risk(s, "address", [address])
    return AddressOut(
        address=a.address,
        address_type=a.address_type,
        network=a.network,
        first_seen_at=a.first_seen_at,
        last_seen_at=a.last_seen_at,
        features=f.features if f else None,
        clusters=clusters,
        correlations=corr,
        graph_detections=[detection_dict(d) for d in dets],
        risk=risk.get(address),
        investigations=list(cases),
        notice=NOTICE,
    )


@router.get("/{address}/transactions", response_model=Paginated[TransactionOut])
async def address_transactions(
    address: str, s: SessionDep, page: PageDep, _: Reader, role: Annotated[str | None, Query(pattern="^(input|output)$")] = None
) -> Paginated[TransactionOut]:
    await _get(s, address)
    parts = []
    if role in (None, "input"):
        parts.append(select(TransactionInput.transaction_id.label("tid")).where(TransactionInput.address == address))
    if role in (None, "output"):
        parts.append(select(TransactionOutput.transaction_id.label("tid")).where(TransactionOutput.address == address))
    sub = union_all(*parts).subquery()
    stmt = select(Transaction).where(Transaction.id.in_(select(sub.c.tid)))
    total = await s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    desc = (page.sort or "-first_seen_at").startswith("-")
    stmt = stmt.order_by(Transaction.first_seen_at.desc() if desc else Transaction.first_seen_at)
    rows = (await s.execute(stmt.limit(page.limit).offset(page.offset))).scalars().all()
    keys = [t.txid for t in rows]
    risk, alerts = await current_risk(s, "transaction", keys), await alert_counts(s, keys)
    return Paginated(
        items=[
            TransactionOut.model_validate(t).model_copy(update={"risk": risk.get(t.txid), "alert_count": alerts.get(t.txid, 0)})
            for t in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{address}/statistics")
async def address_statistics(address: str, s: SessionDep, _: Reader) -> dict[str, Any]:
    await _get(s, address)
    recv = await s.execute(
        select(func.count(), func.coalesce(func.sum(TransactionOutput.amount_sat), 0)).where(TransactionOutput.address == address)
    )
    sent = await s.execute(
        select(func.count(), func.coalesce(func.sum(TransactionInput.amount_sat), 0)).where(TransactionInput.address == address)
    )
    rc, rv = recv.one()
    sc, sv = sent.one()
    daily = await s.execute(
        select(func.date_trunc("day", Transaction.first_seen_at).label("d"), func.count())
        .where(
            Transaction.id.in_(
                select(TransactionInput.transaction_id)
                .where(TransactionInput.address == address)
                .union(select(TransactionOutput.transaction_id).where(TransactionOutput.address == address))
            )
        )
        .group_by("d")
        .order_by("d")
    )
    return {
        "address": address,
        "received_outputs": rc,
        "received_sat": int(rv),
        "spent_inputs": sc,
        "spent_sat": int(sv),
        "balance_estimate_sat": int(rv) - int(sv),
        "balance_note": "Estimate from ingested data only; outputs/inputs outside the dataset are not visible.",
        "daily_activity": [{"day": d.isoformat(), "tx_count": c} for d, c in daily],
    }


@router.get("/{address}/graph")
async def address_graph(
    address: str,
    s: SessionDep,
    _: Reader,
    hops: Annotated[int, Query(ge=1, le=4)] = 1,
    max_nodes: Annotated[int, Query(ge=10, le=2000)] = 300,
    start: datetime | None = None,
    end: datetime | None = None,
    include_network: bool = True,
) -> dict[str, Any]:
    await _get(s, address)
    return await gq.neighbourhood(
        s, address=address, hops=hops, max_nodes=max_nodes, start=start, end=end, include_network=include_network
    )


@router.get("/{address}/risk")
async def address_risk(address: str, s: SessionDep, _: Reader) -> dict[str, Any]:
    await _get(s, address)
    return await risk_detail(s, "address", address)
