"""Default, configurable alert rules. Thresholds live in the alert_rules table (editable by config.change)."""

from typing import Any

DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "code": "TX_HIGH_ANOMALY",
        "category": "high_anomaly_score",
        "description": "Transaction is an extreme outlier for the active model AND its risk score is at least Elevated.",
        "thresholds": {"min_anomaly_score": 0.99, "min_risk": 50},
    },
    {
        "code": "GRAPH_FAN_OUT",
        "category": "high_fan_out",
        "description": "Graph detection: high fan-out.",
        "thresholds": {"min_confidence": 0.6, "min_risk": 50},
    },
    {
        "code": "GRAPH_SPLITTING",
        "category": "repeated_transaction_splitting",
        "description": "High fan-out with near-identical output values (value spread below threshold).",
        "thresholds": {"max_value_spread": 0.05, "min_risk": 50},
    },
    {
        "code": "GRAPH_FAN_IN",
        "category": "high_fan_in",
        "description": "Graph detection: high fan-in.",
        "thresholds": {"min_confidence": 0.6, "min_risk": 50},
    },
    {
        "code": "GRAPH_CONSOLIDATION",
        "category": "unusual_consolidation",
        "description": "Fan-in consolidation that is also a model outlier.",
        "thresholds": {"min_anomaly_score": 0.95, "min_risk": 50},
    },
    {
        "code": "GRAPH_PEEL_CHAIN",
        "category": "suspicious_graph_pattern",
        "description": "Peel-chain structure.",
        "thresholds": {"min_confidence": 0.6, "min_hops": 5},
    },
    {
        "code": "GRAPH_LAYERING",
        "category": "potential_layering_pattern",
        "description": "Rapid multi-hop layering through fresh addresses.",
        "thresholds": {"min_confidence": 0.6, "min_hops": 4},
    },
    {
        "code": "GRAPH_CYCLE",
        "category": "circular_transaction_pattern",
        "description": "Circular value flow returning to origin.",
        "thresholds": {"min_confidence": 0.6},
    },
    {
        "code": "TX_RAPID_MOVEMENT",
        "category": "rapid_transaction_movement",
        "description": "Inputs spent within seconds of being received, combined with Elevated risk.",
        "thresholds": {"max_holding_secs": 120, "min_risk": 50},
    },
    {
        "code": "TX_UNUSUAL_AMOUNT",
        "category": "unusual_transaction_amount",
        "description": "Value in the dataset's top percentile AND a model outlier (size alone never alerts).",
        "thresholds": {"value_percentile": 99.9, "min_anomaly_score": 0.97},
    },
    {
        "code": "NET_IP_BURST",
        "category": "network_blockchain_correlation_anomaly",
        "description": "Burst of transactions first-observed from one source IP well above its baseline.",
        "thresholds": {"min_confidence": 0.6, "min_ratio_to_baseline": 20},
    },
    {
        "code": "ADDR_UNUSUAL_BEHAVIOUR",
        "category": "unusual_wallet_behaviour",
        "description": "Address-level risk at least Elevated with a model outlier rank.",
        "thresholds": {"min_risk": 60, "min_anomaly_score": 0.99},
    },
    {
        "code": "ADDR_UNUSUAL_FREQUENCY",
        "category": "unusual_transaction_frequency",
        "description": "Address activity rate far above population and Elevated risk.",
        "thresholds": {"min_tx_per_day": 20, "min_tx_count": 10, "min_risk": 50},
    },
    {
        "code": "CLUSTER_NEW_UNUSUAL",
        "category": "new_unusual_transaction_cluster",
        "description": "Common-input cluster where a large share of members are Elevated risk.",
        "thresholds": {"min_size": 3, "min_elevated_share": 0.5},
    },
]
