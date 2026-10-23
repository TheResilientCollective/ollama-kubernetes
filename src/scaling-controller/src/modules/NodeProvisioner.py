import os
import re
import subprocess
import time

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.models.v1_node import V1Node
from kubernetes.client.models.v1_pod import V1Pod

from config.config import Config
from utils.logging import logger
from utils.staticproperty import staticproperty

logger = logger.bind(namespace=Config.namespace)

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()


class NodeProvisioner:
    """
    Adds nodes when pods are unschedulable and removes nodes that sit empty.
    Nodes are added/removed by running Config.node_scale_up_command / node_scale_down_command.
    """

    nodes: list[V1Node] = []
    unscheduled_pods: list[V1Pod] = []
    core_api = client.CoreV1Api()

    __idle_since: dict[str, float] = {}
    __scale_up_requested_at: float | None = None
    __node_count_at_scale_up: int = 0

    @staticproperty
    def ready_nodes() -> list[V1Node]:
        return [n for n in NodeProvisioner.nodes if NodeProvisioner.__is_ready(n)]

    @staticproperty
    def managed_nodes() -> list[V1Node]:
        return [
            n
            for n in NodeProvisioner.nodes
            if re.match(r"ollama-kubernetes-worker-", n.metadata.name)
        ]

    @staticproperty
    def managed_ready_nodes() -> list[V1Node]:
        return [
            n
            for n in NodeProvisioner.nodes
            if (
                re.match(r"ollama-kubernetes-worker-", n.metadata.name)
                and NodeProvisioner.__is_ready(n)
            )
        ]

    @staticmethod
    async def update():
        NodeProvisioner.poll_nodes()
        NodeProvisioner.poll_unscheduled_pods()

        if NodeProvisioner.unscheduled_pods:
            NodeProvisioner.scale_up()
        else:
            NodeProvisioner.scale_down()

    @staticmethod
    def poll_nodes():
        NodeProvisioner.nodes = NodeProvisioner.core_api.list_node().items

    @staticmethod
    def poll_unscheduled_pods():
        pods = NodeProvisioner.core_api.list_namespaced_pod(
            namespace=Config.namespace, field_selector="status.phase=Pending"
        ).items
        NodeProvisioner.unscheduled_pods = [
            pod
            for pod in pods
            if any(
                c.type == "PodScheduled"
                and c.status == "False"
                and (
                    "Insufficient" in (c.reason or "")
                    or "Unschedulable" in (c.reason or "")
                    or "MatchNodeSelector" in (c.reason or "")
                )
                for c in (pod.status.conditions or [])
            )
        ]

    @staticmethod
    def scale_up():
        if not Config.node_server_scale_up_command:
            return
        node_count = len(NodeProvisioner.nodes)
        if Config.max_nodes >= 0 and node_count >= Config.max_nodes:
            logger.warn("Unschedulable pods but at max nodes", max_nodes=node_count)
            return

        # Don't stack requests while a previously requested node is still joining
        requested_at = NodeProvisioner.__scale_up_requested_at
        if (
            requested_at is not None
            and node_count <= NodeProvisioner.__node_count_at_scale_up
            and time.time() - requested_at < Config.node_join_timeout
        ):
            return

        logger.info(
            "Scaling up nodes", unscheduled_pods=len(NodeProvisioner.unscheduled_pods)
        )
        tier = Config.tiers[0]  # TODO: determine which tier to use
        node_name = f"ollama-kubernetes-worker-{tier}-{int(time.time())}"
        if NodeProvisioner.__run(
            Config.node_server_scale_up_command, {"NODE_NAME": node_name, "TIER": tier}
        ):
            NodeProvisioner.__scale_up_requested_at = time.time()
            NodeProvisioner.__node_count_at_scale_up = node_count

    @staticmethod
    def scale_down():
        if not Config.node_server_scale_down_command:
            return
        now = time.time()
        pods_by_node: dict[str, int] = {}
        for pod in NodeProvisioner.core_api.list_pod_for_all_namespaces().items:
            if NodeProvisioner.__is_daemonset_pod(pod):
                continue
            node_name = pod.spec.node_name
            pods_by_node[node_name] = pods_by_node.get(node_name, 0) + 1

        ready = NodeProvisioner.managed_ready_nodes
        idle_names = {
            n.metadata.name for n in ready if pods_by_node.get(n.metadata.name, 0) == 0
        }
        NodeProvisioner.__idle_since = {
            name: NodeProvisioner.__idle_since.get(name, now) for name in idle_names
        }

        # Remove one node per update, and never remove the last one
        if len(ready) <= 1:
            return
        for name, since in NodeProvisioner.__idle_since.items():
            if now - since >= Config.node_server_scale_down_idle:
                logger.info("Scaling down node", node=name)
                if NodeProvisioner.__run(
                    Config.node_server_scale_down_command, {"NODE_NAME": name}
                ):
                    del NodeProvisioner.__idle_since[name]
                return

    @staticmethod
    def __is_ready(node: V1Node) -> bool:
        return any(
            c.type == "Ready" and c.status == "True"
            for c in (node.status.conditions or [])
        )

    @staticmethod
    def __is_daemonset_pod(pod: V1Pod) -> bool:
        return any(o.kind == "DaemonSet" for o in (pod.metadata.owner_references or []))

    @staticmethod
    def __run(command: str, extra_env: dict[str, str] | None = None) -> bool:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            env={**os.environ, **(extra_env or {})},
        )
        if result.returncode != 0:
            logger.error(
                "Node command failed", command=command, stderr=result.stderr.strip()
            )
            return False
        return True
