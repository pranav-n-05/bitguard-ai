import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PageDep, SessionDep, apply_sort, require
from app.core.errors import NotFoundError
from app.graph import query as gq
from app.models import (
    Dataset,
    DatasetFile,
    GraphDetection,
    NetworkObservation,
    RawRecord,
    RiskAssessment,
    Transaction,
    TransactionFeature,
    TransactionInput,
    TransactionOutput,
    User,
)
from app.schemas.common import Paginated
from app.schemas.intel import AnalyzeRequest, EvidenceProvenance, IoOut, ObservationOut, TransactionDetail, TransactionOut
from app.services.intel import alert_counts, current_risk, detection_dict
from app.services.risk_read import analyze_transaction, risk_detail

router = APIRouter(prefix="/transactions", tags=["transactions"])
Reader = Annotated[User, Depends(require("intel.read"))]
TXID = Annotated[str, Query(pattern=r"^[0-9a-fA-F]{64}$")]


async def _get_tx(s: AsyncSession, txid: str) -> Transaction:
    t = (await s.execute(select(Transaction).where(Transaction.txid == txid.lower()))).scalar_one_or_none()
    if t is None:
        raise NotFoundError("Transaction not found in ingested data")
    return t


@router.get("", response_model=Paginated[TransactionOut], summary="Search transactions")
async def list_transactions(
    s: SessionDep,
    page: PageDep,
    _: Reader,
    q: Annotated[str | None, Query(max_length=100, description="txid prefix or exact address")] = None,
    start: datetime | None = None,
    end: datetime | None = None,
    min_value_sat: Annotated[int | None, Query(ge=0)] = None,
    max_value_sat: Annotated[int | None, Query(ge=0)] = None,
    min_inputs: Annotated[int | None, Query(ge=0)] = None,
    min_outputs: Annotated[int | None, Query(ge=0)] = None,
    dataset_id: uuid.UUID | None = None,
    min_risk: Annotated[int | None, Query(ge=0, le=100)] = None,
    band: Annotated[str | None, Query(pattern="^(low|moderate|elevated|high)$")] = None,
) -> Paginated[TransactionOut]:
    stmt = select(Transaction)
    if q:
        ql = q.strip()
        sub_in = select(TransactionInput.transaction_id).where(TransactionInput.address == ql)
        sub_out = select(TransactionOutput.transaction_id).where(TransactionOutput.address == ql)
        stmt = stmt.where(or_(Transaction.txid.startswith(ql.lower()), Transaction.id.in_(sub_in), Transaction.id.in_(sub_out)))
    if start:
        stmt = stmt.where(Transaction.first_seen_at >= start)
    if end:
        stmt = stmt.where(Transaction.first_seen_at <= end)
    if min_value_sat is not None:
        stmt = stmt.where(Transaction.total_output_sat >= min_value_sat)
    if max_value_sat is not None:
        stmt = stmt.where(Transaction.total_output_sat <= max_value_sat)
    if min_inputs is not None:
        stmt = stmt.where(Transaction.input_count >= min_inputs)
    if min_outputs is not None:
        stmt = stmt.where(Transaction.output_count >= min_outputs)
    if dataset_id:
        stmt = stmt.where(Transaction.dataset_id == dataset_id)
    if min_risk is not None or band:
        r = select(RiskAssessment.entity_key).where(
            RiskAssessment.entity_type == "transaction", RiskAssessment.is_current.is_(True)
        )
        if min_risk is not None:
            r = r.where(RiskAssessment.score >= min_risk)
        if band:
            r = r.where(RiskAssessment.band == band)
        stmt = stmt.where(Transaction.txid.in_(r))
    total = await s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = apply_sort(
        stmt,
        Transaction,
        page.sort,
        {"first_seen_at", "total_output_sat", "fee_sat", "input_count", "output_count", "block_height"},
        Transaction.first_seen_at.desc(),
    )
    rows = (await s.execute(stmt.limit(page.limit).offset(page.offset))).scalars().all()
    keys = [t.txid for t in rows]
    risk, alerts = await current_risk(s, "transaction", keys), await alert_counts(s, keys)
    items = [
        TransactionOut.model_validate(t).model_copy(update={"risk": risk.get(t.txid), "alert_count": alerts.get(t.txid, 0)})
        for t in rows
    ]
    return Paginated(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("/analyze", summary="On-demand analysis (features, reproducible model score, risk explanation) for up to 50 txids")
async def analyze(
    body: AnalyzeRequest, s: SessionDep, _: Annotated[User, Depends(require("intel.analyze"))]
) -> list[dict[str, Any]]:
    txids = [t.lower() for t in (body.txids or [])][:50]
    if not txids:
        from app.core.errors import AppError

        raise AppError("Provide txids")
    out = []
    for t in txids:
        try:
            out.append(await analyze_transaction(s, t))
        except NotFoundError:
            out.append({"txid": t, "error": "not_found"})
    return out


@router.get("/{txid}", response_model=TransactionDetail)
async def get_transaction(txid: str, s: SessionDep, _: Reader) -> TransactionDetail:
    t = await _get_tx(s, txid)
    ins = (
        await s.execute(
            select(TransactionInput).where(TransactionInput.transaction_id == t.id).order_by(TransactionInput.position)
        )
    ).scalars()
    outs = (
        await s.execute(
            select(TransactionOutput).where(TransactionOutput.transaction_id == t.id).order_by(TransactionOutput.position)
        )
    ).scalars()
    obs = (
        await s.execute(
            select(NetworkObservation).where(NetworkObservation.transaction_id == t.id).order_by(NetworkObservation.observed_at)
        )
    ).scalars()
    feat = (
        (
            await s.execute(
                select(TransactionFeature)
                .where(TransactionFeature.transaction_id == t.id)
                .order_by(TransactionFeature.computed_at.desc())
            )
        )
        .scalars()
        .first()
    )
    dets = (await s.execute(select(GraphDetection).where(GraphDetection.txids.contains([t.txid])))).scalars().all()
    raw = await s.get(RawRecord, t.source_raw_record_id)
    assert raw is not None
    df = await s.get(DatasetFile, raw.dataset_file_id)
    ds = await s.get(Dataset, t.dataset_id)
    assert df is not None and ds is not None
    risk = await current_risk(s, "transaction", [t.txid])
    base = TransactionOut.model_validate(t).model_dump()
    return TransactionDetail(
        **{**base, "risk": risk.get(t.txid), "alert_count": (await alert_counts(s, [t.txid])).get(t.txid, 0)},
        block_hash=t.block_hash,
        vsize=t.vsize,
        version=t.version,
        locktime=t.locktime,
        content_hash=t.content_hash,
        inputs=[IoOut.model_validate(i) for i in ins],
        outputs=[IoOut.model_validate(o) for o in outs],
        observations=[ObservationOut.model_validate(o) for o in obs],
        features=feat.features if feat else None,
        feature_schema_version=feat.schema_version if feat else None,
        graph_detections=[detection_dict(d) for d in dets],
        provenance=EvidenceProvenance(
            dataset_id=ds.id,
            dataset_name=ds.name,
            provenance=ds.provenance,
            dataset_file_id=df.id,
            file_name=df.original_name,
            file_sha256=df.sha256,
            raw_record_id=raw.id,
            record_index=raw.record_index,
            record_hash=raw.content_hash,
        ),
        data_labels=[ds.provenance, "historical-bulk"],
    )


@router.get("/{txid}/inputs", response_model=list[IoOut])
async def get_inputs(txid: str, s: SessionDep, _: Reader) -> list[IoOut]:
    t = await _get_tx(s, txid)
    rows = (
        await s.execute(
            select(TransactionInput).where(TransactionInput.transaction_id == t.id).order_by(TransactionInput.position)
        )
    ).scalars()
    return [IoOut.model_validate(r) for r in rows]


@router.get("/{txid}/outputs", response_model=list[IoOut])
async def get_outputs(txid: str, s: SessionDep, _: Reader) -> list[IoOut]:
    t = await _get_tx(s, txid)
    rows = (
        await s.execute(
            select(TransactionOutput).where(TransactionOutput.transaction_id == t.id).order_by(TransactionOutput.position)
        )
    ).scalars()
    return [IoOut.model_validate(r) for r in rows]


@router.get("/{txid}/graph", summary="Cytoscape elements around a transaction")
async def tx_graph(
    txid: str,
    s: SessionDep,
    _: Reader,
    hops: Annotated[int, Query(ge=1, le=4)] = 2,
    max_nodes: Annotated[int, Query(ge=10, le=2000)] = 300,
    include_network: bool = True,
) -> dict[str, Any]:
    await _get_tx(s, txid)
    return await gq.neighbourhood(s, txid=txid.lower(), hops=hops, max_nodes=max_nodes, include_network=include_network)


@router.get("/{txid}/trace", summary="Follow value forward/backward (address-level)")
async def tx_trace(
    txid: str,
    s: SessionDep,
    _: Reader,
    direction: Annotated[str, Query(pattern="^(forward|backward)$")] = "forward",
    depth: Annotated[int, Query(ge=1, le=10)] = 4,
) -> dict[str, Any]:
    await _get_tx(s, txid)
    return await gq.trace_flow(s, txid.lower(), direction, depth)


@router.get("/{txid}/risk", summary="Current risk assessment with components, explanation and history")
async def tx_risk(txid: str, s: SessionDep, _: Reader) -> dict[str, Any]:
    await _get_tx(s, txid)
    return await risk_detail(s, "transaction", txid.lower())
