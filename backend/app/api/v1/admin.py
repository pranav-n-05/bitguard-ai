import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.api.deps import PageDep, SessionDep, require
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.passwords import check_policy
from app.core.security import hash_password
from app.database.session import get_sessionmaker
from app.models import AlertRule, AuditLog, RefreshToken, Role, SystemConfig, User
from app.schemas.auth import UserOut
from app.schemas.common import Paginated
from app.services import audit
from app.services.risk import DEFAULT_WEIGHTS

router = APIRouter(prefix="/admin", tags=["administration"])
Admin = Annotated[User, Depends(require("user.admin"))]


def _out(u: User) -> UserOut:
    o = UserOut.model_validate(u)
    o.permission_codes = sorted(o.permission_codes)
    return o


@router.get("/users", response_model=Paginated[UserOut])
async def list_users(
    s: SessionDep, page: PageDep, _: Admin, q: Annotated[str | None, Query(max_length=100)] = None
) -> Paginated[UserOut]:
    stmt = select(User)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%") | User.full_name.ilike(f"%{q}%"))
    total = await s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await s.execute(stmt.order_by(User.email).limit(page.limit).offset(page.offset))).scalars()
    return Paginated(items=[_out(u) for u in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/users/assignable")
async def assignable(s: SessionDep, _: Annotated[User, Depends(require("case.read"))]) -> list[dict[str, str]]:
    users = (await s.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))).scalars()
    return [{"id": str(u.id), "full_name": u.full_name, "email": u.email} for u in users if "case.create" in u.permission_codes]


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)
    roles: list[str] = Field(min_length=1)


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    roles: list[str] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=256)
    reset_mfa: bool = False


async def _roles(s: SessionDep, names: list[str]) -> list[Role]:
    roles = (await s.execute(select(Role).where(Role.name.in_(names)))).scalars().all()
    if len(roles) != len(set(names)):
        raise AppError(f"Unknown role(s); available: {sorted((await s.execute(select(Role.name))).scalars())}")
    return list(roles)


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, s: SessionDep, admin: Admin) -> UserOut:
    email = body.email.lower()
    if (await s.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise ConflictError("A user with this email already exists")
    check_policy(body.password, email)
    u = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password), roles=await _roles(s, body.roles))
    s.add(u)
    await s.flush()
    await audit.record(
        s,
        "user.created",
        "user",
        str(u.id),
        actor_id=admin.id,
        actor_email=admin.email,
        details={"email": email, "roles": body.roles},
    )
    await s.commit()
    await s.refresh(u)
    return _out(u)


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: uuid.UUID, body: UserPatch, s: SessionDep, admin: Admin) -> UserOut:
    u = await s.get(User, user_id)
    if u is None:
        raise NotFoundError("User not found")
    diff: dict[str, Any] = {}
    if body.roles is not None:
        if u.id == admin.id and "administrator" not in body.roles:
            raise AppError("You cannot remove your own administrator role")
        diff["roles"] = [u.role_names, sorted(body.roles)]
        u.roles = await _roles(s, body.roles)
    if body.is_active is not None and body.is_active != u.is_active:
        if u.id == admin.id and not body.is_active:
            raise AppError("You cannot deactivate yourself")
        diff["is_active"] = [u.is_active, body.is_active]
        u.is_active = body.is_active
    if body.full_name:
        u.full_name = body.full_name
    if body.password:
        check_policy(body.password, u.email)
        u.password_hash = hash_password(body.password)
        diff["password"] = "reset"  # noqa: S105 - audit marker, not a credential
    if body.reset_mfa:
        u.mfa_enabled, u.mfa_secret = False, None
        diff["mfa"] = "reset"
    if "password" in diff or diff.get("is_active") == [True, False] or "roles" in diff or "mfa" in diff:
        await s.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == u.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        diff["sessions"] = "revoked"
    await audit.record(s, "user.updated", "user", str(u.id), actor_id=admin.id, actor_email=admin.email, details=diff)
    await s.commit()
    await s.refresh(u)
    return _out(u)


@router.get("/roles")
async def roles(s: SessionDep, _: Admin) -> list[dict[str, Any]]:
    return [
        {"name": r.name, "description": r.description, "permissions": sorted(p.code for p in r.permissions)}
        for r in (await s.execute(select(Role).order_by(Role.id))).scalars()
    ]


@router.get("/audit-logs", response_model=Paginated[dict[str, Any]])
async def audit_logs(
    s: SessionDep,
    page: PageDep,
    _: Annotated[User, Depends(require("audit.read"))],
    action: Annotated[str | None, Query(max_length=96)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=128)] = None,
    actor_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Paginated[dict[str, Any]]:
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action.startswith(action))
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if start:
        q = q.where(AuditLog.occurred_at >= start)
    if end:
        q = q.where(AuditLog.occurred_at <= end)
    total = await s.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (await s.execute(q.order_by(AuditLog.seq.desc()).limit(page.limit).offset(page.offset))).scalars()
    return Paginated(
        items=[
            {
                "seq": a.seq,
                "occurred_at": a.occurred_at,
                "actor_id": a.actor_id,
                "actor_email": a.actor_email,
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "details": a.details,
                "request_id": a.request_id,
                "prev_hash": a.prev_hash,
                "entry_hash": a.entry_hash,
            }
            for a in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/audit-logs/verify", summary="Verify the audit hash chain end to end")
async def verify_audit(s: SessionDep, _: Annotated[User, Depends(require("audit.read"))]) -> dict[str, Any]:
    ok, n, bad = await audit.verify_chain(s)
    return {"valid": ok, "entries_checked": n, "first_invalid_seq": bad}


@router.get("/configuration")
async def get_config(s: SessionDep, _: Annotated[User, Depends(require("config.change"))]) -> dict[str, Any]:
    from app.alerts.engine import seed_rules

    await seed_rules(s)
    await s.commit()
    cfg: dict[str, dict[str, Any]] = {
        c.key: {"value": c.value, "version": c.version} for c in (await s.execute(select(SystemConfig))).scalars()
    }
    rules = [
        {
            "code": r.code,
            "category": r.category,
            "description": r.description,
            "enabled": r.enabled,
            "thresholds": r.thresholds,
            "version": r.version,
        }
        for r in (await s.execute(select(AlertRule).order_by(AlertRule.id))).scalars()
    ]
    rw: dict[str, Any] = cfg.get("risk_weights", {})
    return {
        "risk_weights": {**DEFAULT_WEIGHTS, **(rw.get("value") or {})},
        "risk_weights_version": rw.get("version", 0),
        "alert_rules": rules,
    }


class RulePatch(BaseModel):
    code: str
    enabled: bool | None = None
    thresholds: dict[str, float] | None = None


class ConfigPatch(BaseModel):
    risk_weights: dict[str, float] | None = None
    alert_rules: list[RulePatch] | None = None


@router.patch("/configuration")
async def patch_config(
    body: ConfigPatch, s: SessionDep, admin: Annotated[User, Depends(require("config.change"))]
) -> dict[str, Any]:
    if body.risk_weights is not None:
        unknown = set(body.risk_weights) - set(DEFAULT_WEIGHTS)
        if unknown or any(not 0 <= v <= 1 for v in body.risk_weights.values()):
            raise AppError(f"Risk weights must be within [0,1] and one of {sorted(DEFAULT_WEIGHTS)}")
        row = (await s.execute(select(SystemConfig).where(SystemConfig.key == "risk_weights"))).scalar_one_or_none()
        if row is None:
            s.add(SystemConfig(key="risk_weights", value=body.risk_weights, version=1, updated_by=admin.id))
        else:
            row.value, row.version, row.updated_by = {**row.value, **body.risk_weights}, row.version + 1, admin.id
        await audit.record(
            s,
            "config.risk_weights_changed",
            "config",
            "risk_weights",
            actor_id=admin.id,
            actor_email=admin.email,
            details=body.risk_weights,
        )
    for rp in body.alert_rules or []:
        r = (await s.execute(select(AlertRule).where(AlertRule.code == rp.code))).scalar_one_or_none()
        if r is None:
            raise NotFoundError(f"Unknown alert rule {rp.code}")
        old = {"enabled": r.enabled, "thresholds": r.thresholds}
        if rp.thresholds:
            if unknown_keys := set(rp.thresholds) - set(r.thresholds):
                raise AppError(f"Unknown threshold(s) for {rp.code}: {sorted(unknown_keys)}")
            r.thresholds = {**r.thresholds, **rp.thresholds}
        if rp.enabled is not None:
            r.enabled = rp.enabled
        r.version += 1
        await audit.record(
            s,
            "config.alert_rule_changed",
            "alert_rule",
            r.code,
            actor_id=admin.id,
            actor_email=admin.email,
            details={"old": old, "new": {"enabled": r.enabled, "thresholds": r.thresholds}, "version": r.version},
        )
    await s.commit()
    return await get_config(s, admin)


@router.post("/pipeline/rerun", summary="Recompute analytics, risk and alerts with current configuration")
async def rerun(
    s: SessionDep, admin: Annotated[User, Depends(require("config.change"))], stages: Annotated[list[str] | None, Query()] = None
) -> dict[str, Any]:
    from app.alerts.engine import generate
    from app.services import ml
    from app.services.analytics_stage import run_analytics
    from app.services.risk import assess_all

    sm = get_sessionmaker()
    wanted = stages or ["analytics", "ml", "risk", "alerts"]
    out: dict[str, Any] = {}
    if "analytics" in wanted:
        out["analytics"] = await run_analytics(sm)
    if "ml" in wanted:
        out["ml"] = {et: await ml.score_all(sm, et) for et in ("transaction", "address")}
    if "risk" in wanted:
        out["risk"] = await assess_all(sm)
    if "alerts" in wanted:
        out["alerts"] = await generate(sm)
    await audit.record(
        s, "pipeline.rerun", "pipeline", None, actor_id=admin.id, actor_email=admin.email, details={"stages": wanted}
    )
    await s.commit()
    return out
