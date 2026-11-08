import ipaddress
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import INET

from app.api.deps import PageDep, SessionDep, apply_sort, require
from app.core.errors import AppError, NotFoundError
from app.models import CorrelationIndicator, IpEntity, NetworkFeature, NetworkObservation, User
from app.schemas.common import Paginated
from app.schemas.intel import IndicatorOut
from app.services.intel import current_risk

router = APIRouter(prefix="/network", tags=["network"])
Reader = Annotated[User, Depends(require("intel.read"))]
NOTICE = "Network observations show co-occurrence and timing only. They do not show that an IP owner controls any address."


async def _entity(s: SessionDep, etype: str, key: str) -> dict[str, Any]:
    f = (
        (
            await s.execute(
                select(NetworkFeature)
                .where(NetworkFeature.entity_type == etype, NetworkFeature.entity_key == key)
                .order_by(NetworkFeature.computed_at.desc())
            )
        )
        .scalars()
        .first()
    )
    inds = (
        (
            await s.execute(
                select(CorrelationIndicator).where(
                    CorrelationIndicator.entity_type == etype, CorrelationIndicator.entity_key == key
                )
            )
        )
        .scalars()
        .all()
    )
    col = NetworkObservation.src_ip if etype == "ip" else NetworkObservation.asn
    val: Any = cast(key, INET) if etype == "ip" else int(key)
    obs = (
        (await s.execute(select(NetworkObservation).where(col == val).order_by(NetworkObservation.observed_at.desc()).limit(50)))
        .scalars()
        .all()
    )
    txids = sorted({o.txid for o in obs})
    risk = await current_risk(s, "transaction", txids)
    return {
        "entity_type": etype,
        "key": key,
        "features": f.features if f else None,
        "indicators": [IndicatorOut.model_validate(i).model_dump() for i in inds],
        "recent_observations": [
            {
                "id": o.id,
                "txid": o.txid,
                "observed_at": o.observed_at,
                "src_ip": str(o.src_ip),
                "dst_ip": str(o.dst_ip),
                "dst_port": o.dst_port,
                "asn": o.asn,
                "country": o.geo_country,
                "tx_risk": risk[o.txid].model_dump() if o.txid in risk else None,
            }
            for o in obs
        ],
        "notice": NOTICE,
    }


@router.get("/ips/{ip}")
async def get_ip(ip: str, s: SessionDep, _: Reader) -> dict[str, Any]:
    try:
        norm = str(ipaddress.ip_address(ip))
    except ValueError as e:
        raise AppError("Invalid IP address") from e
    ent = await s.get(IpEntity, norm)
    if ent is None:
        raise NotFoundError("IP not observed in ingested data")
    out = await _entity(s, "ip", norm)
    out.update(version=ent.version, is_private=ent.is_private, first_seen_at=ent.first_seen_at, last_seen_at=ent.last_seen_at)
    return out


@router.get("/asns/{asn}")
async def get_asn(asn: int, s: SessionDep, _: Reader) -> dict[str, Any]:
    n = await s.scalar(select(func.count()).select_from(NetworkObservation).where(NetworkObservation.asn == asn))
    if not n:
        raise NotFoundError("ASN not observed in ingested data")
    out = await _entity(s, "asn", str(asn))
    out["observation_count"] = n
    return out


@router.get("/correlations", response_model=Paginated[IndicatorOut])
async def correlations(
    s: SessionDep,
    page: PageDep,
    _: Reader,
    indicator_type: Annotated[str | None, Query(max_length=48)] = None,
    entity_type: Annotated[str | None, Query(pattern="^(ip|address|asn|country)$")] = None,
    entity_key: Annotated[str | None, Query(max_length=100)] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
) -> Paginated[IndicatorOut]:
    q = select(CorrelationIndicator)
    if indicator_type:
        q = q.where(CorrelationIndicator.indicator_type == indicator_type)
    if entity_type:
        q = q.where(CorrelationIndicator.entity_type == entity_type)
    if entity_key:
        q = q.where(CorrelationIndicator.entity_key == entity_key)
    if min_confidence is not None:
        q = q.where(CorrelationIndicator.confidence >= min_confidence)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    q = apply_sort(
        q, CorrelationIndicator, page.sort, {"strength", "confidence", "window_start"}, CorrelationIndicator.strength.desc()
    )
    rows = (await s.execute(q.limit(page.limit).offset(page.offset))).scalars().all()
    return Paginated(items=[IndicatorOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/patterns", summary="Aggregate network patterns: ports, protocols, countries, top origin IPs")
async def patterns(s: SessionDep, _: Reader) -> dict[str, Any]:
    ports = await s.execute(
        select(NetworkObservation.dst_port, func.count())
        .group_by(NetworkObservation.dst_port)
        .order_by(func.count().desc())
        .limit(20)
    )
    protos = await s.execute(select(NetworkObservation.protocol, func.count()).group_by(NetworkObservation.protocol))
    countries = await s.execute(
        select(NetworkObservation.geo_country, func.count())
        .group_by(NetworkObservation.geo_country)
        .order_by(func.count().desc())
    )
    top = await s.execute(
        select(NetworkFeature.entity_key, NetworkFeature.features)
        .where(NetworkFeature.entity_type == "ip")
        .order_by(NetworkFeature.features["max_tx_in_10m"].as_integer().desc())
        .limit(15)
    )
    by_type = await s.execute(
        select(CorrelationIndicator.indicator_type, func.count()).group_by(CorrelationIndicator.indicator_type)
    )
    return {
        "destination_ports": [{"port": p, "count": c} for p, c in ports],
        "protocols": [{"protocol": p, "count": c} for p, c in protos],
        "countries": [{"country": k, "count": c, "unavailable": k is None} for k, c in countries],
        "top_burst_ips": [
            {"ip": k, "max_tx_in_10m": f.get("max_tx_in_10m"), "unique_tx_count": f.get("unique_tx_count")} for k, f in top
        ],
        "indicators_by_type": {t: c for t, c in by_type},
        "notice": NOTICE,
    }
