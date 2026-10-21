import json
import os
from typing import TypedDict

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
    node_scale_up_command: str | None = os.environ.get("NODE_SCALE_UP_COMMAND")
    node_scale_down_command: str | None = os.environ.get("NODE_SCALE_DOWN_COMMAND")
    node_scale_down_idle: float = float(os.environ.get("NODE_SCALE_DOWN_IDLE", "900"))
    node_join_timeout: float = float(os.environ.get("NODE_JOIN_TIMEOUT", "180"))

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

    @staticmethod
    def test_config():
        from utils.logging import logger

        logger = logger.bind(namespace=Config.namespace)
        logger.info("Testing the configuration")

        # Check if we're in a kubernetes pod
        import os

        assert os.path.exists(
            os.environ.get("KUBECONFIG", "~/.kube/config")
        ), "Scaling Controller must be run inside of kubernetes"

        # Check if Node Provisioner is configured
        if Config.use_node_provisioner:
            assert (
                Config.node_scale_up_command
            ), "Missing NODE_SCALE_UP_COMMAND environment variable"
            assert (
                Config.node_scale_down_command
            ), "Missing NODE_SCALE_DOWN_COMMAND environment variable"

        # Check access to router
        try:
            response = requests.get(Config.router_endpoint + "/api/tags")
            assert response.status_code == 200
        except Exception as e:
            raise Exception(
                f"Could not reach {Config.router_endpoint+"/api/tags"} (environment variable ROUTER_ENDPOINT={Config.router_endpoint})"
            )

        logger.info("Configuration tests passed")
