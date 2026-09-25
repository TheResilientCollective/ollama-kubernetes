import asyncio
import json
import logging
import types

import structlog

from config.config import Config
from modules.K8sClient import K8sClient
from utils.logging import logger
from utils.replica_calculations import calculate_desired_pods

k8s = K8sClient()


async def main():
    while True:
        # try:
        status = (
            await k8s.poll_router()
        )  # TODO: this is blocking. Move to asyncio tasks

        for tier in Config.tiers:
            target_replica_count = calculate_desired_pods(tier, status)
            await k8s.scale_to(tier, target_replica_count)
        # except Exception as error:
        #     logger.error(f"Polling loop failed: {error}")
        # finally:
        await asyncio.sleep(Config.update_interval_s)


if __name__ == "__main__":
    logger.info("Scaling Handler started")
    asyncio.run(main())
