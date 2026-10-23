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

    __start_time: datetime
    __ready_timeout_task: asyncio.Task | None = None

    def __init__(self, name, tier):
        super().__init__()
        self.__name = name
        self.__tier = tier
        self.__server_ready = False
        self.on_node_state_changed += lambda ready: (
            self.__ready_timeout_task.cancel()
            if self.__ready_timeout_task and ready
            else logger.info("Node not ready", name=self.name)
        )
        self.on_node_state_changed += lambda ready: (
            asyncio.ensure_future(self.label_node()) if ready else None
        )

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

    async def label_node(self):
        """Adds the gpu label to the node"""
        body = {"metadata": {"labels": Config.node_necessary_labels}}
        Node.core_api.patch_node(self.name, body)

    async def delete_node(self):
        """Deletes the node and stops kubernetes from tracking it"""
        pass

    """ SERVER """

    async def start_server(self):
        """Tells cloud provider to create a new server"""
        self.__set_server_ready(False)
        assert Config.node_server_scale_up_command
        self.__start_time = datetime.now()
        failure, output = await self.__run(Config.node_server_scale_up_command)

        self.__ready_timeout_task = asyncio.create_task(self.__handle_ready_timeout())

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
        logger.info("Deleting node", node=self.name)
        assert Config.node_server_scale_down_command
        failure, output = await self.__run(Config.node_server_scale_down_command)
        await self.get_server_status()

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
            )
            return (1, stderr.strip())
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
