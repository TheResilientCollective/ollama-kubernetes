from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel

from schema.router import PodStatus


class IdlePodStatus(PodStatus):
    name: str
    idle_duration: float


class ScaleDirection(Enum):
    up = "up"
    down = "down"


class ScaleRequest:

    scale_direction: ScaleDirection
    id: UUID
    number_of_replicas: int
    tier: str
    completed: bool
    request_initialized: datetime
    request_resolved: datetime

    def __init__(
        self,
        tier: str,
        number_of_replicas: int,
        scale_direction: ScaleDirection | str,
    ):
        """
        Struct for keeping track of pending scaling changes

        Params:
            tier (str): the small/medium/large tier the request is for
            number_of_replicas (int): the delta or change in number of replicas this request makes
            scale_direction (str): where the request is scaling "up" or "down"
        """
        self.id = uuid4()
        self.completed = False
        self.number_of_replicas = number_of_replicas
        self.scale_direction = ScaleDirection(scale_direction)
        self.request_initialized = datetime.now()
        self.tier = tier

    def mark_complete(self):
        request_resolved = datetime.now()
        completed = True

    def __eq__(self, other):
        return self.id == other.id

    def __lt__(self, other):
        return self.request_initialized < other.request_initialized

    def __gt__(self, other):
        return self.request_initialized > other.request_initialized
