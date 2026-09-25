from collections import deque
from datetime import datetime
from typing import Any, TypedDict

import requests
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client import ApiException, AppsV1Api, CoreV1Api
from kubernetes.client.models.v1_pod import V1Pod
from kubernetes.client.models.v1_pod_list import V1PodList
from pydantic import BaseModel

from api.router_api import get_status as get_router_status
from config.config import Config
from schema.pods import IdlePodStatus, ScaleRequest
from schema.router import PodStatus, Status
from utils.logging import logger
from utils.pod_status import *
from utils.staticproperty import staticproperty

logger = logger.bind(namespace=Config.namespace)


class K8sClient:

    __instance: K8sClient | None = None
    __statuses: deque[Status]
    __apps_api: AppsV1Api
    __core_api: CoreV1Api
    __pending_scale_up_by: list[ScaleRequest] = []
    __pending_scale_down_by: list[ScaleRequest] = []
    __target_replicas: dict[str, int]

    @staticproperty
    def pending_requests() -> list[ScaleRequest]:
        all_requests = (
            K8sClient.__pending_scale_down_by + K8sClient.__pending_scale_up_by
        )
        all_requests = sorted(all_requests, key=lambda req: req.request_initialized)
        return all_requests

    def __init__(self):
        if K8sClient.__instance:
            raise Exception("K8sClient instance already exists.")
        K8sClient.__instance = self

        # Setup status queue
        max_scale_down_idle: float = 0
        for tier in Config.scale_down_idle:
            max_scale_down_idle = max(max_scale_down_idle, Config.scale_down_idle[tier])

        min_queue_length = max_scale_down_idle / Config.update_interval_s
        queue_length = max(int(min_queue_length * 1.5), 50)
        K8sClient.__statuses = deque(maxlen=queue_length)

        # Setup kubernetes api
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()

        K8sClient.__apps_api = client.AppsV1Api()
        K8sClient.__core_api = client.CoreV1Api()

        # Get target replicas
        self.__target_replicas = {}
        for tier in Config.tiers:
            replicas = self.__get_deployment_replica_count(tier)
            self.__target_replicas[tier] = replicas

    @staticmethod
    def get_pending_replica_change(tier: str) -> int:
        if not K8sClient.__instance:
            return 0
        return K8sClient.__instance.__get_pending_replica_change(tier)

    @staticmethod
    def get_pending_target_replicas(tier: str) -> int:
        if not K8sClient.__instance:
            return 0
        return K8sClient.__instance.__get_pending_replica_count(tier)

    def __get_pending_replica_change(self, tier: str) -> int:
        scale_up_requests = filter(
            lambda req: req.tier == tier, self.__pending_scale_up_by
        )
        scale_down_requests = filter(
            lambda req: req.tier == tier, self.__pending_scale_down_by
        )
        pending_delta = sum([r.number_of_replicas for r in scale_up_requests]) - sum(
            [r.number_of_replicas for r in scale_down_requests]
        )
        return pending_delta

    def __get_pending_replica_count(self, tier: str) -> int:
        current_replicas = (
            len(self.__statuses[-2].pods[tier])
            if len(self.__statuses) > -1 and tier in self.__statuses[-1].pods
            else -1
        )
        pending_delta = self.__get_pending_replica_change(tier)
        target_replicas = current_replicas + pending_delta
        return target_replicas

    async def scale_to(self, tier: str, replica_count: int) -> bool:
        """
        Scales a tier to a target number of replicas

        Params:
            tier (str): the small/medium/large tier to scale
            replica_count (int): the number of replicas to scale the tier to
        """
        if self.__target_replicas[tier] > replica_count:
            delta = abs(self.__target_replicas[tier] - replica_count)
            destroyed_pods = await self.scale_down(tier, delta)
            return len(destroyed_pods) == delta
        elif self.__target_replicas[tier] < replica_count:
            delta = abs(self.__target_replicas[tier] - replica_count)
            return await self.scale_up(tier, delta)
        else:
            return True

    async def scale_up(self, tier: str, n: int = 1) -> bool:
        """
        Increases the number of pods in a tier by n

        Params:
            tier (str): the small/medium/large tier to scale up
            n (int): the number of pods to add

        Returns:
            True if successful
        """
        if n <= 0:
            logger.warn("Scale up by invalid number", n=n, tier=tier)
            return False
        scale_request = ScaleRequest(tier, n, "up")
        self.__pending_scale_up_by.append(scale_request)
        current_replicas = self.__target_replicas[tier]
        self.__target_replicas[tier] += n

        body = {"spec": {"replicas": self.__target_replicas[tier]}}
        success = False
        try:
            self.__apps_api.patch_namespaced_deployment_scale(
                name=f"ollama-{tier}", namespace=Config.namespace, body=body
            )
            logger.info(
                "Scale up",
                from_replicas=current_replicas,
                to_replicas=self.__target_replicas[tier],
                tier=tier,
            )
            success = True
        except ApiException as e:
            logger.error(
                "Scale up failed",
                tier=tier,
                from_replicas=current_replicas,
                to_replicas=self.__target_replicas[tier],
                status=e.status,
                reason=e.reason,
            )
            self.__target_replicas[tier] -= n
        finally:
            self.__pending_scale_up_by.remove(scale_request)
            if len(self.pending_requests) == 0:
                self.__target_replicas[tier] = self.__get_deployment_replica_count(tier)

        return success

    async def scale_down(self, tier: str, n: int = 1) -> list[IdlePodStatus]:
        """
        Scales down a pod tier by n pods

        Params:
            tier (str): the small/medium/large tier to scale down
            n (int): the number of pods to remove

        Returns:
            list json descriptions of pods that were removed {name: "ollama-<tier>-asdf", pod: Pod, idle_duration: 1000}
        """
        logger = globals()["logger"].bind(n=n, tier=tier)
        if n <= 0:
            logger.warn("Scale down by invalid number")
            return []
        scale_request = ScaleRequest(tier, n, "down")
        self.__pending_scale_down_by.append(scale_request)

        current_replicas = self.__target_replicas[tier]
        self.__target_replicas[tier] -= n

        logger = logger.bind(old_replica_count=current_replicas)
        idle_pods: list[IdlePodStatus] = self.get_idle_pod_statuses_in(tier)
        timed_out_pods = [
            idle_pod
            for idle_pod in idle_pods
            if idle_pod.idle_duration > Config.scale_down_idle[tier]
        ]
        timed_out_pods.sort(key=lambda idle_pod: idle_pod.idle_duration, reverse=True)
        logger = logger.bind(timed_out_pods=len(timed_out_pods))
        if len(timed_out_pods) == 0:
            logger.debug(f"No pods have timed out yet.")
            return []
        if len(timed_out_pods) < n:
            logger.debug(
                f"Not enough timed out pods to satisfy request to scale down. Expect warnings"
            )

        # Tell router to disable pods
        successful_disables = 0
        pods_to_delete: list[IdlePodStatus] = []
        for i in range(len(timed_out_pods)):
            pod = timed_out_pods[i]
            response = requests.post(
                Config.router_disable_ip_endpoint,
                json={"ip": pod.ip, "tier": tier},
            )
            if response.status_code == 200:
                successful_disables += 1
                pods_to_delete.append(pod)
                if successful_disables == n:
                    break
            else:
                logger.warn(
                    f"Router rejected request to disable pod",
                    ip=pod.ip,
                    name=pod.name,
                    reason=response.text,
                    url=Config.router_disable_ip_endpoint,
                )
                continue
        if successful_disables != n:
            logger.warn(
                f"Router refused to disable all requested pods",
                requested_number_to_disable=n,
                successfully_disabled=successful_disables,
            )
        self.__target_replicas[tier] += n - successful_disables
        logger = logger.bind(target_replicas=self.__target_replicas[tier])

        logger.info(
            f"Will delete pods",
            pods_to_delete=[
                f"{pod.ip} idle for {pod.idle_duration}" for pod in pods_to_delete
            ],
        )

        # Delete pods
        for idle_pod in pods_to_delete:
            name = idle_pod.name or self.get_pod_name_from_ip(idle_pod.ip)
            assert name, f"Could not determine pod name from ip {idle_pod.ip}"
            self.__core_api.delete_namespaced_pod(
                name=name,
                namespace=Config.namespace,
                body=client.V1DeleteOptions(
                    grace_period_seconds=10, propagation_policy="Foreground"
                ),
            )
            logger.info("Deleted pod", pod_name=name, pod_ip=idle_pod.ip)

        # Update target replica count
        self.__apps_api.patch_namespaced_deployment_scale(
            name=f"ollama-{tier}",
            namespace=Config.namespace,
            body={"spec": {"replicas": self.__target_replicas[tier]}},
        )
        logger.debug("Patched replica count")

        # Remove ScaleRequest
        self.__pending_scale_down_by.remove(scale_request)
        if len(self.pending_requests) == 0:
            self.__target_replicas[tier] = self.__get_deployment_replica_count(tier)

        return pods_to_delete

    @staticmethod
    def __get_deployment_replica_count(tier: str) -> int:
        """
        Gets the number of current replicas set in a small/medium/large tier
        """
        try:
            deployment_name = f"ollama-{tier}"
            deployment: Any = K8sClient.__apps_api.read_namespaced_deployment_scale(
                name=f"ollama-{tier}", namespace=Config.namespace
            )
            return deployment.spec.replicas or 0
        except ApiException as e:
            logger.error(
                "Deployment read failed", tier=tier, status=e.status, reason=e.reason
            )
            raise e
        except AssertionError as e:
            logger.error("Deployment read, but didn't have a spec", tier=tier)
            raise e

    @staticmethod
    def get_idle_pod_statuses_in(tier: str) -> list[IdlePodStatus]:
        """
        Gets how long different pods have been idle for

        Params:
            tier (str): the small/medium/large tier to check
        """
        logger = globals()["logger"].bind(tier=tier)
        if len(K8sClient.__statuses) == 0:
            return []
        most_recent_status = K8sClient.__statuses[-1]

        idle_pods: list[PodStatus] = get_idle_pods_in(tier, most_recent_status)
        idle_pods_with_metadata: list[IdlePodStatus] = []

        for pod in idle_pods:
            logger.debug(
                "Checking pod for idle status",
                pod=pod,
                type=type(pod),
                is_idle_type=isinstance(pod, IdlePodStatus),
            )
            # Get idle duration
            last_timestamp: datetime = most_recent_status.datetime
            idle_started: datetime = most_recent_status.datetime

            for i in range(len(K8sClient.__statuses) - 1, -1, -1):
                wasIdle = check_if_pod_is_idle(tier, pod.ip, K8sClient.__statuses[-1])
                if not wasIdle:
                    break
                idle_started = min(idle_started, K8sClient.__statuses[i].datetime)

            idle_duration: float = (last_timestamp - idle_started).total_seconds()

            # Get pod name
            name = K8sClient.get_pod_name_from_ip(pod.ip)
            if not name:
                logger.warn(f"Couldn't find pod name", ip=pod.ip)
                continue

            # Add to list
            # if isinstance(pod, IdlePodStatus):
            #     idle_pods_with_metadata.append(pod)
            # else:
            idle_pods_with_metadata.append(
                IdlePodStatus(
                    **pod.model_dump(), name=name, idle_duration=idle_duration
                )
            )
            logger.debug(
                f"Pod idle duration determined",
                ip=pod.ip,
                name=name,
                idle_duration=idle_duration,
            )

        return idle_pods_with_metadata

    @staticmethod
    def get_pod_name_from_ip(ip: str) -> str | None:
        """
        Finds a pod name based on its ip.

        Return:
            pod_name (str) the name of the pod if found. Otherwise, returns None
        """

        all_pods_search: Any = K8sClient.__core_api.list_namespaced_pod(
            namespace=Config.namespace
        )
        assert hasattr(all_pods_search, "items")
        all_pods = all_pods_search.items
        for pod in all_pods:
            if pod.status.pod_ip == ip:
                return pod.metadata.name

        return None

    async def poll_router(self) -> Status:
        router_status = get_router_status()
        K8sClient.__statuses.append(router_status)
        return router_status
