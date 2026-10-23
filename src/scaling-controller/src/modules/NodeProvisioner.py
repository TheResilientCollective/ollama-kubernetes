import asyncio
import os
import re
import subprocess
import time

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.models.v1_node import V1Node
from kubernetes.client.models.v1_pod import V1Pod

from config.config import Config
from modules.Node import Node
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

    nodes: list[Node] = []
    unscheduled_pods: list[V1Pod] = []
    core_api = client.CoreV1Api()

    __idle_since: dict[str, float] = {}

    @staticproperty
    def ready_nodes() -> list[Node]:
        return [n for n in NodeProvisioner.nodes if n.is_node_ready]

    @staticproperty
    def managed_nodes() -> list[Node]:
        return [
            n
            for n in NodeProvisioner.nodes
            if re.match(r"ollama-kubernetes-worker-", n.name)
        ]

    @staticproperty
    def managed_ready_nodes() -> list[Node]:
        return [
            n
            for n in NodeProvisioner.nodes
            if (re.match(r"ollama-kubernetes-worker-", n.name) and n.is_node_ready)
        ]

    @staticmethod
    async def update():
        NodeProvisioner.poll_unscheduled_pods()
        unready_nodes = [n for n in NodeProvisioner.nodes if not n.is_node_ready]

        necessary_delta = len(NodeProvisioner.unscheduled_pods) - len(unready_nodes)

        if necessary_delta > 0:
            for i in range(necessary_delta):
                NodeProvisioner.scale_up()
        else:
            NodeProvisioner.scale_down()

    @staticmethod
    def poll_unscheduled_pods():
        pods = getattr(
            NodeProvisioner.core_api.list_namespaced_pod(
                namespace=Config.namespace, field_selector="status.phase=Pending"
            ),
            "items",
            [],
        )
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
        node_count = len(NodeProvisioner.nodes)
        if Config.max_nodes >= 0 and node_count >= Config.max_nodes:
            logger.warn("Unschedulable pods but at max nodes", max_nodes=node_count)
            return

        logger.info(
            "Scaling up nodes", unscheduled_pods=len(NodeProvisioner.unscheduled_pods)
        )
        NodeProvisioner.spin_up_node()

    @staticmethod
    def scale_down():
        if not Config.node_server_scale_down_command:
            return
        now = time.time()

        # get how long each pod has been idle for
        pods_by_node: dict[str, int] = {}  # FIXME: unclear naming of variable
        all_pods = getattr(
            NodeProvisioner.core_api.list_namespaced_pod(Config.namespace), "items", []
        )
        # Filter out daemon sets
        for pod in all_pods:
            if NodeProvisioner.__is_daemonset_pod(pod):
                continue
            node_name = pod.spec.node_name
            pods_by_node[node_name] = pods_by_node.get(node_name, 0) + 1

        # FIXME: what is this doing?
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

                node_to_delete = next(
                    (node for node in NodeProvisioner.nodes if node.name == name), None
                )
                if not node_to_delete:
                    continue

                del NodeProvisioner.__idle_since[name]
                NodeProvisioner.nodes.remove(node_to_delete)
                node_to_delete.delete()
                return

    @staticmethod
    def __is_daemonset_pod(pod: V1Pod) -> bool:
        return any(
            o.kind == "DaemonSet" for o in getattr(pod.metadata, "owner_references", [])
        )

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

    """ New Node Module """

    @staticmethod
    def spin_up_node():
        tier = "medium"  # TODO: determine which tier to use
        node_name = f"ollama-kubernetes-worker-{tier}-{int(time.time())}"

        node = Node(node_name, tier)
        NodeProvisioner.nodes.append(node)
        asyncio.create_task(node.start_server())
        # node.start_polling() # not necessary
