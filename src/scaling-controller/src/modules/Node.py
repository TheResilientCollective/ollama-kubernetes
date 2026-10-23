"""
Note the difference between a **server** and a **node**. A server is the compute instance / VM / server running on AWS/Azure/... . A **node** is the kubernetes node that runs on that server.

A different script will need to trigger these functions to regularly check status updates and listen for events
"""

import asyncio
import os
import subprocess
import time
from datetime import datetime
from typing import Any

from events import Events
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.models.v1_node import V1Node
from kubernetes.client.models.v1_node_status import V1NodeStatus
from kubernetes.client.models.v1_pod import V1Pod

from config.config import Config
from schema.nodes import NodeState
from utils.logging import logger
from utils.staticproperty import staticproperty

logger = logger.bind(namespace=Config.namespace)
try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()


class Node(Events):
    __events__ = (
        "on_node_state_changed",
        "on_server_state_changed",
    )
    __server_ready: bool
    __V1Node: V1Node | None
    __V1Pods: list[V1Pod]
    __name: str
    __tier: str
    core_api: client.CoreV1Api = client.CoreV1Api()

    __ready_timeout_task: asyncio.Task | None
    __polling_task: asyncio.Task | None

    def __init__(self, name, tier):
        super().__init__()
        self.__name = name
        self.__tier = tier
        self.__V1Node = None
        self.__V1Pods = []
        self.__server_ready = False
        self.__ready_timeout_task = None
        self.__polling_task = None
        self.on_node_state_changed += self.__clear_ready_timeout  # type: ignore
        self.on_node_state_changed += self.label_node
        self.start_polling()

    """ ACCESSORS """

    @property
    def name(self):
        return self.__name

    @property
    def tier(self):
        return self.__tier

    @property
    def node(self) -> V1Node | None:
        return self.__V1Node

    @node.setter
    def node(self, value: V1Node | None):
        original = self.__V1Node
        self.__V1Node = value

        if not original or not original.status:
            original_ready = False
        else:
            ready_conditions = [
                cond for cond in original.status.conditions if cond.type == "Ready"
            ]
            original_ready = (
                ready_conditions[0].status == "True"
                if len(ready_conditions) > 0
                else False
            )

        if not value or not value.status:
            new_ready = False
        else:
            logger.info(
                "Updating node status",
                name=self.name,
                status=[
                    cond for cond in value.status.conditions if cond.type == "Ready"
                ],
                condition_types=[cond.type for cond in value.status.conditions],
            )

            ready_conditions = [
                cond for cond in value.status.conditions if cond.type == "Ready"
            ]
            new_ready = (
                ready_conditions[0].status == "True"
                if len(ready_conditions) > 0
                else False
            )

        if original_ready != new_ready:
            self.on_node_state_changed(new_ready)

    @property
    def is_node_ready(self) -> bool:
        if not self.node or not self.node.status:
            return False

        ready_conditions = [
            cond for cond in self.node.status.conditions if cond.type == "Ready"
        ]
        ready = (
            ready_conditions[0].status == "True" if len(ready_conditions) > 0 else False
        )
        return ready

    def __set_server_ready(self, value: bool):
        original = self.__server_ready
        self.__server_ready = value
        if value != original:
            self.on_server_state_changed(
                {"from": original, "to": value, "ready": self.__server_ready}
            )

    """ NODE """

    def get_node_status(self):
        """
        Gets the latest data from kubernetes on this node.
        """
        k8s_nodes: list[V1Node] = getattr(Node.core_api.list_node(), "items", [])
        matches = [n for n in k8s_nodes if n.metadata and n.metadata.name == self.name]
        if len(matches) == 0:
            return False
        elif len(matches) == 1:
            self.node = matches[0]
        else:
            logger.error(
                "Found multiple nodes with the same name", name=self.name, nodes=matches
            )
            # raise Exception(f"Found multiple nodes with the same name")

    def label_node(self, *args, **kwargs):
        """Adds the gpu and other labels to the node, defined by environment variables"""
        logger.debug(
            "Adding labels to node", name=self.name, labels=Config.node_necessary_labels
        )
        assert self.node
        body = {"metadata": {"labels": Config.node_necessary_labels}}
        try:
            response = Node.core_api.patch_node(self.name, body)
        except Exception as e:
            logger.error("Failed to label node", name=self.name, error=str(e))

    def delete_node(self):
        """Deletes the node and stops kubernetes from tracking it"""
        logger.info("Deleting node", name=self.name)
        # drain node
        try:
            body = {"spec": {"unschedulable": True}}
            Node.core_api.patch_node(self.name, body)

            pods = getattr(
                Node.core_api.list_namespaced_pod(
                    Config.namespace, field_selector=f"spec.nodeName={self.name}"
                ),
                "items",
                [],
            )
            for pod in pods:
                if pod.metadata.owner_references:
                    # skip daemonsets and controllers
                    if any(
                        o.kind in ["DaemonSet", "ReplicaSet", "StatefulSet", "Job"]
                        for o in pod.metadata.owner_references
                    ):
                        continue

                    try:
                        Node.core_api.delete_namespaced_pod(
                            pod.metadata.name, Config.namespace
                        )
                    except:
                        pass
        except Exception as e:
            logger.error("Failed to drain node", error=str(e))

        # delete the node
        try:
            Node.core_api.delete_node(self.name)
        except:
            pass
        self.node = None

        # Stop the ready timeout task
        if (
            self.__ready_timeout_task
            and not self.__ready_timeout_task.cancelled
            and not self.__ready_timeout_task.cancelling
        ):
            self.__ready_timeout_task.cancel()
            self.__ready_timeout_task = None

    """ SERVER """

    async def start_server(self):
        """Tells cloud provider to create a new server"""
        self.__set_server_ready(False)
        assert Config.node_server_scale_up_command
        failure, output = await self.__run(Config.node_server_scale_up_command)

        self.__ready_timeout_task = asyncio.create_task(self.__handle_ready_timeout())

        # TODO: check if reached quota limit, or if otherwise failed. Destroy self if failed.

    async def get_server_status(self):
        """
        Gets the server's ready status from cloud provider
        """
        original = self.__server_ready
        assert Config.node_server_status_command
        failure, output = await self.__run(Config.node_server_status_command)
        if failure:
            ready = False
            logger.error(
                "Failed to get server status",
                name=self.name,
                command=Config.node_server_status_command,
                output=output,
            )
        elif output != Config.node_server_status_command_ready:
            ready = False
        else:
            ready = True
        self.__set_server_ready(ready)

    async def delete_server(self):
        """Tells cloud provider to delete the server"""
        if self.node:
            self.delete_node()

        logger.info("Deleting server", node=self.name)
        assert Config.node_server_scale_down_command
        failure, output = await self.__run(Config.node_server_scale_down_command)
        self.__set_server_ready(False)

        # Stop the polling task
        if (
            self.__polling_task
            and not self.__polling_task.cancelled
            and not self.__polling_task.cancelling
        ):
            self.__polling_task.cancel()
        # Stop the ready timeout task
        if (
            self.__ready_timeout_task
            and not self.__ready_timeout_task.cancelled
            and not self.__ready_timeout_task.cancelling
        ):
            self.__ready_timeout_task.cancel()
            self.__ready_timeout_task = None

    """ HELPER """

    async def __run(self, command: str) -> tuple[int, str]:
        """
        Runs a shell command on the control node. Injects the following additional environment variables:
            - NODE_NAME: the name of this server/node
            - TIER: the small/medium/large scale tier of this server/node

        Params:
            command (str): the command to run. shell strings like $NODE_NAME and $TIER will work

        Returns:
            tuple (int, str): (exit_code, stdout/stderr) exit_code is 1 for fail, 0 for success. stdout/stderr is chosen based on whether the exit_code is a fail or success.
        """
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "NODE_NAME": self.name, "TIER": self.tier},
        )

        stdout_bytes, stderr_bytes = await process.communicate()
        stdout = stdout_bytes.decode()
        stderr = stderr_bytes.decode()

        if process.returncode != 0:
            logger.error(
                "Node command failed",
                name=self.name,
                tier=self.tier,
                command=command,
                stderr=stderr.strip(),
                exit_code=process.returncode,
            )
            return (1, stderr.strip())
        logger.debug(
            "Node command succeeded",
            name=self.name,
            tier=self.tier,
            command=command,
            stdout=stdout.strip(),
            exit_code=process.returncode,
        )
        return (0, stdout.strip())

    async def __handle_ready_timeout(self):
        """Wait for node to become ready, timeout if it takes too long"""
        try:
            await asyncio.sleep(Config.node_join_timeout)

            if not self.is_node_ready:
                logger.error(
                    "Node initialization timed out",
                    name=self.name,
                    server_ready=self.__server_ready,
                    node_ready=self.is_node_ready,
                )
                # Cleanup
                try:
                    await self.delete_server()
                except Exception as e:
                    logger.error("Failed to cleanup server", error=str(e))

        except asyncio.CancelledError:
            pass

    def __clear_ready_timeout(self, ready: bool):
        if self.__ready_timeout_task and ready:
            self.__ready_timeout_task.cancel()
            self.__ready_timeout_task = None

    async def __poll(self):
        try:
            while True:
                await self.get_server_status()
                self.get_node_status()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    def start_polling(self):
        """
        Starts regularly polling server and node for status updates in the background.
        Runs automatically by default and shouldn't need to be called
        unless you delete/stop things and are trying to restart them
        """
        logger.info("Starting Polling", polling_task=self.__polling_task)
        if self.__polling_task:
            self.__polling_task.cancel()
        self.__polling_task = asyncio.create_task(self.__poll())

    def delete(self):
        asyncio.create_task(self.delete_server())
