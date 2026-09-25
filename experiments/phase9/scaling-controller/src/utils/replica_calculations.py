from config.config import Config
from modules.K8sClient import K8sClient
from schema.router import Status
from utils.logging import logger
from utils.pod_status import *


def calculate_desired_pods(tier: str, status: Status) -> int:
    if tier not in status.queues:  # no requests have even been sent yet
        # logger.debug("Queue doesn't exist yet", tier=tier)
        return Config.min_replicas[tier]

    # Get queue
    queue_length = status.queues[tier].length

    if tier not in status.pods:
        # Handle scale from 0
        target_replicas = queue_length
    else:
        # Get idle pods
        pods = status.pods[tier]
        pending_replica_change = K8sClient.get_pending_replica_change(tier)
        busy_pods = list(filter(lambda pod: pod.activeRequests > 0, pods))
        all_idle_pods: list[IdlePodStatus] = K8sClient.get_idle_pod_statuses_in(tier)
        timed_out_pods = list(
            filter(
                lambda idle_pod: idle_pod.idle_duration > Config.scale_down_idle[tier],
                all_idle_pods,
            )
        )
        target_replicas = len(busy_pods) + queue_length - len(all_idle_pods)

    # Bound target_replicas to configured min/max
    target_replicas = min(target_replicas, Config.max_replicas[tier])
    target_replicas = max(target_replicas, Config.min_replicas[tier])
    return target_replicas
