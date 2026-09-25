import json
import os
from typing import TypedDict

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
