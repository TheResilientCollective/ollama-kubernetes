import json
import os
from typing import Any, TypedDict

import requests

from utils.staticproperty import staticproperty


class Config:

    debug: bool = bool(os.environ.get("DEBUG", False))
    tiers: list[str] = json.loads(
        os.environ.get("TIERS", '["small", "medium", "large"]')
    )
    namespace: str = os.environ.get("NAMESPACE", "ollama")

    router_endpoint: str = os.environ.get(
        "ROUTER_ENDPOINT", "http://ollama-router:11434"
    )
    router_metrics_path: str = os.environ.get(
        "ROUTER_METRICS_PATH", "/api/gateway/status"
    )
    router_disable_ip_path: str = os.environ.get(
        "ROUTER_DISABLE_IP_PATH", "/api/gateway/disable-pod"
    )
    router_prometheus_path: str = os.environ.get("ROUTER_PROMETHEUS_PATH", "/metrics")
    router_metrics_endpoint: str = router_endpoint + router_metrics_path
    router_disable_ip_endpoint: str = router_endpoint + router_disable_ip_path
    router_prometheus_endpoint: str = router_endpoint + router_prometheus_path

    """ How often to check the router for status updates """
    update_interval_s: int = int(os.environ.get("UPDATE_INTERVAL_S", 1))
    """ How long a pod needs to be idle for before scaling down """
    scale_down_idle_default: float = float(os.environ.get("SCALE_DOWN_IDLE", 5.0))

    """ Node scaling """
    use_node_provisioner: bool = (
        os.environ.get("USE_NODE_PROVISIONER", "false").lower() == "true"
    )

    max_nodes: int = int(os.environ.get("MAX_NODES", -1))
    node_server_scale_up_command: str | None = os.environ.get(
        "NODE_SERVER_SCALE_UP_COMMAND"
    )
    node_server_scale_down_command: str | None = os.environ.get(
        "NODE_SERVER_SCALE_DOWN_COMMAND"
    )
    node_server_status_command: str | None = os.environ.get(
        "NODE_SERVER_STATUS_COMMAND"
    )
    node_server_status_command_ready: str | None = os.environ.get(
        "NODE_SERVER_STATUS_COMMAND_READY"
    )
    node_server_scale_down_idle: float = float(
        os.environ.get("NODE_SERVER_SCALE_DOWN_IDLE", "900")
    )
    node_join_timeout: float = float(os.environ.get("NODE_JOIN_TIMEOUT", "180"))
    node_necessary_labels: dict[str, Any] = json.loads(
        os.environ.get("NODE_NECESSARY_LABELS", "{}")
    )

    """ Pod provisioner """
    pod_provisioner_interval_s: float = float(
        os.environ.get("POD_PROVISIONER_INTERVAL_S", "2")
    )
    pod_provisioner_request_timeout_s: float = float(
        os.environ.get("POD_PROVISIONER_REQUEST_TIMEOUT_S", "5")
    )
    pod_provisioner_stale_after_interval_s: float = float(
        os.environ.get("POD_PROVISIONER_STALE_AFTER_INTERVAL_S", "3")
    )

    @staticproperty
    def scale_down_idle() -> dict[str, float]:
        ret = {}
        for tier in Config.tiers:
            ret[tier] = float(
                os.environ.get(
                    f"SCALE_DOWN_IDLE_{tier.upper()}", Config.scale_down_idle_default
                )
            )
        return ret

    @staticproperty
    def min_replicas() -> dict[str, int]:
        ret = {}
        for tier in Config.tiers:
            ret[tier] = int(os.environ.get(f"MIN_REPLICAS_{tier.upper()}", 0))
        return ret

    @staticproperty
    def max_replicas() -> dict[str, int]:
        ret = {}
        for tier in Config.tiers:
            ret[tier] = int(os.environ.get(f"MAX_REPLICAS_{tier.upper()}", 0))
        return ret
