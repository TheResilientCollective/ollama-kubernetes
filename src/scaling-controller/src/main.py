import asyncio
import json
import logging
import types
from contextlib import suppress

import structlog

from config.config import Config
from modules.K8sClient import K8sClient
from modules.NodeProvisioner import NodeProvisioner
from modules.PodProvisioner import PodProvisioner
from utils.logging import logger
from utils.replica_calculations import calculate_desired_pods

RESTART_DELAY_S = 2.0


async def main():
    k8s = K8sClient()
    NodeProvisioner.check_for_existing_nodes()

    pod_provisioner = PodProvisioner()
    restart_task: asyncio.Task | None = None

    async def restart_pod_provisioner():
        await asyncio.sleep(RESTART_DELAY_S)
        if not pod_provisioner.is_running:
            logger.info("Restarting pod provisioner")
            pod_provisioner.start()

    def on_pod_provisioner_error(error: Exception):
        nonlocal restart_task
        logger.warning("Pod provisioner error", error=str(error))
        if restart_task is None or restart_task.done():
            restart_task = asyncio.create_task(restart_pod_provisioner())

    pod_provisioner.on_error += on_pod_provisioner_error

    try:
        if Config.use_node_provisioner:
            pod_provisioner.start()
        while True:
            status = (
                await k8s.poll_router()
            )  # TODO: this is blocking. Move to asyncio tasks

            for tier in Config.tiers:
                target_replica_count = calculate_desired_pods(tier, status)
                await k8s.scale_to(tier, target_replica_count)

            if Config.use_node_provisioner:
                await NodeProvisioner.update(pod_provisioner.snapshot)

            await asyncio.sleep(Config.update_interval_s)
    finally:
        if restart_task is not None and not restart_task.done():
            restart_task.cancel()
            with suppress(asyncio.CancelledError):
                await restart_task
        await pod_provisioner.stop()


if __name__ == "__main__":
    logger.info("Scaling Controller started")
    asyncio.run(main())
