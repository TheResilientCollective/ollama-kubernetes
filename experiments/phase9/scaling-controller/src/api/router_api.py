import json

import aiohttp
import requests

from config.config import Config
from schema.router import PodStatus, QueueStatus, Status
from utils.logging import logger

# async def get_status() -> Status:
#     # logger.debug(f"Getting status from {Config.router_metrics_endpoint}")
#     async with aiohttp.ClientSession() as session:
#         async with session.get(Config.router_metrics_endpoint) as response:
#             if response.status != 200:
#                 logger.error(f"{response.status} - { response.text }")
#                 raise Exception(f"{response.status} - {response.text}")
#
#             response_as_json: dict = await response.json()
#             status = Status(**response_as_json)
#             return status


def get_status() -> Status:
    response = requests.get(Config.router_metrics_endpoint)
    if response.status_code != 200:
        logger.error(f"{response.status_code} - { response.text }")
        raise Exception(f"{response.status_code} - {response.text}")

    response_as_json: dict = response.json()
    status = Status(**response_as_json)
    return status
