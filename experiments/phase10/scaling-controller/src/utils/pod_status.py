from datetime import datetime

from config.config import Config
from schema.pods import IdlePodStatus
from schema.router import PodStatus, QueueStatus, Status
from utils.logging import logger


def check_if_pod_is_idle(tier: str, ip: str, status: Status) -> bool:
    """
    Checks if a pod matching an ip in a tier is idle or not

    Params:
        tier (str): the tier to find the pod in
        pod (PodStatus): the pod to check
        status (Status): the recorded status from the router to check for idle state in.
    """
    logger = globals()["logger"].bind(tier=tier)
    if tier not in status.pods:
        logger.debug(f"No status for tier", tiers=status.pods.keys())
        return False

    pods: list[PodStatus] = status.pods[tier]
    target_pod_search = [p for p in pods if p.ip == ip]
    if len(target_pod_search) != 1:
        return False
    target_pod: PodStatus = target_pod_search[0]
    if target_pod.activeRequests == 0:
        return True
    else:
        return False


def get_idle_pods_in(tier: str, status: Status) -> list[PodStatus]:
    """
    Gets a list of pods that are idle in a tier.

    Params:
        tier (str): The pod tier (small/medium/large) to check
        status (Status): The recorded status from the router to check for idle status in.

    Returns:
        list[PodStatus] a list of pods that are idle in the status
    """
    if tier not in status.pods:
        return []
    if len(status.pods[tier]) == 0:
        return []

    logger = globals()["logger"].bind(tier=tier)
    idle_pods: list[PodStatus] = []
    pods: list[PodStatus] = status.pods[tier]

    for pod in pods:
        isIdle = check_if_pod_is_idle(tier, pod.ip, status)
        if not isIdle:
            continue

        # Add to list
        idle_pods.append(pod)

    return idle_pods
