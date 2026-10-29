import asyncio
import time

from events import Events
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.models.v1_pod import V1Pod

from config.config import Config
from schema.pods import PodInfo, PodSnapshot
from utils.logging import logger

logger = logger.bind(namespace=Config.namespace)

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()


class PodProvisioner(Events):
    """
    Observes pods in the namespace and keeps a snapshot of their state.
    Pending ollama pods that need capacity are derived from the snapshot.
    """

    __events__ = ("on_error",)

    def __init__(self, core_api: client.CoreV1Api | None = None):
        super().__init__()
        self.__core_api = core_api or client.CoreV1Api()
        self.__snapshot: PodSnapshot | None = None
        self.__task: asyncio.Task | None = None
        self.__last_signature: tuple | None = None
        self.on_error += self.__handle_error

    @property
    def snapshot(self) -> PodSnapshot | None:
        snapshot = self.__snapshot
        if snapshot is None:
            return None
        if (
            snapshot.snapshot_age_s
            > Config.pod_provisioner_interval_s
            * Config.pod_provisioner_stale_after_interval_s
        ):
            return None
        return snapshot

    @property
    def is_running(self) -> bool:
        return self.__task is not None and not self.__task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self.__task = asyncio.create_task(self.__run(), name="pod-provisioner")

    async def stop(self) -> None:
        task = self.__task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def __run(self) -> None:
        logger.info(
            "Pod provisioner started", interval_s=Config.pod_provisioner_interval_s
        )
        try:
            while True:
                try:
                    await self.__refresh()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Pod provisioner refresh failed", error=str(exc))
                    try:
                        self.on_error(exc)
                    except Exception as handler_exc:
                        logger.error(
                            "Pod provisioner error handler failed",
                            error=str(handler_exc),
                        )
                    return
                await asyncio.sleep(Config.pod_provisioner_interval_s)
        finally:
            if self.__task is asyncio.current_task():
                self.__task = None
            logger.info("Pod provisioner stopped")

    async def __refresh(self) -> None:
        pods = await asyncio.to_thread(self.__list_pods)
        self.__snapshot = build_snapshot(pods, time.monotonic())
        self.__log_change()

    def __list_pods(self) -> list[V1Pod]:
        result = self.__core_api.list_namespaced_pod(
            namespace=Config.namespace,
            _request_timeout=Config.pod_provisioner_request_timeout_s,
        )
        return getattr(result, "items", [])

    def __log_change(self) -> None:
        snapshot = self.__snapshot
        if snapshot is None:
            return
        pending = snapshot.pending_pods
        signature = (
            len(snapshot.pods),
            len(pending),
            tuple(sorted(p.name for p in pending)),
        )
        if signature == self.__last_signature:
            logger.debug(
                "Pod state unchanged",
                total=len(snapshot.pods),
                pending=len(pending),
            )
            return

        logger.info(
            "Pod state changed",
            total=len(snapshot.pods),
            pending=len(pending),
            pending_pods=[
                {"name": p.name, "tier": p.tier, "reason": p.unschedulable_reason}
                for p in pending
            ],
        )
        self.__last_signature = signature

    def __handle_error(self, error: Exception) -> None:
        logger.warning("Pod provisioner resetting after error")
        self.__snapshot = None
        self.__last_signature = None


def pod_info_from(pod: V1Pod) -> PodInfo:
    status = pod.status
    conditions = (status.conditions or []) if status else []

    ready = any(c.type == "Ready" and c.status == "True" for c in conditions)

    unschedulable_reason = None
    for condition in conditions:
        if condition.type == "PodScheduled" and condition.status == "False":
            unschedulable_reason = condition.reason or condition.message
            break

    owner_references = getattr(pod.metadata, "owner_references", None) or []

    return PodInfo(
        name=pod.metadata.name,
        tier=(pod.metadata.labels or {}).get("tier"),
        app=(pod.metadata.labels or {}).get("app"),
        phase=(status.phase if status and status.phase else "Unknown"),
        node_name=pod.spec.node_name,
        ip=status.pod_ip if status else None,
        created_at=pod.metadata.creation_timestamp,
        ready=ready,
        scheduled=pod.spec.node_name is not None,
        terminating=pod.metadata.deletion_timestamp is not None,
        owner_kind=owner_references[0].kind if owner_references else None,
        unschedulable_reason=unschedulable_reason,
    )


def build_snapshot(pods: list[V1Pod], fetched_at: float) -> PodSnapshot:
    return PodSnapshot(
        pods=tuple(pod_info_from(pod) for pod in pods), fetched_at=fetched_at
    )
