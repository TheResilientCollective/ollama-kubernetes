from datetime import datetime
from enum import Enum
from typing import Any, NewType

from pydantic import BaseModel

from config.config import Config
from utils.tiers import dict_has_tiers


class PodStatus(BaseModel):
    ip: str
    activeRequests: int
    loadedModels: list[str]
    lastPolledMsAgo: int


class QueueStatus(BaseModel):
    length: int
    items: list[Any]


class Status(BaseModel):
    timestamp: int
    queues: dict[str, QueueStatus]
    pods: dict[str, list[PodStatus]]

    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp / 1000)
