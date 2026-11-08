"""Explicit permission catalogue and default role grants."""

PERMISSIONS: dict[str, str] = {
    "dataset.read": "View datasets, ingestion jobs and errors",
    "dataset.upload": "Upload dataset files",
    "dataset.process": "Start / resume dataset processing",
    "intel.read": "View transactions, addresses, network intelligence, graph and analytics",
    "intel.analyze": "Trigger on-demand analysis of transactions/addresses",
    "model.read": "View model versions, evaluations and predictions",
    "model.train": "Train and activate ML models",
    "alert.read": "View alerts",
    "alert.create": "Create manual alerts",
    "alert.acknowledge": "Acknowledge / assign alerts and add notes",
    "alert.resolve": "Resolve, escalate or mark alerts as false positive",
    "case.read": "View investigations",
    "case.create": "Create investigations and add notes / linked entities",
    "case.assign": "Assign investigations to analysts",
    "evidence.attach": "Attach evidence to investigations",
    "report.generate": "Generate and download reports",
    "user.admin": "Manage users and roles",
    "config.change": "Change thresholds, risk weights and model configuration",
    "audit.read": "View audit logs",
}

_READ = {"dataset.read", "intel.read", "model.read", "alert.read", "case.read"}
_ANALYST = _READ | {"intel.analyze", "alert.acknowledge", "case.create", "evidence.attach", "report.generate", "dataset.upload"}
_SENIOR = _ANALYST | {"dataset.process", "model.train", "alert.create", "alert.resolve", "case.assign", "audit.read"}

ROLES: dict[str, tuple[str, set[str]]] = {
    "administrator": ("Full administrative access", set(PERMISSIONS)),
    "senior_analyst": ("Senior analyst: processing, training, resolution, assignment", _SENIOR),
    "analyst": ("Analyst: investigate, acknowledge, create cases, attach evidence", _ANALYST),
    "viewer": ("Read-only viewer", _READ),
}
