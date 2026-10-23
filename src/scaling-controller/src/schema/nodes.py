from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel

from schema.router import PodStatus


class NodeState(Enum):
    PROVISIONING = "provisioning"
    JOINING = "joining"
    READY = "ready"
    DRAINING = "draining"
    TERMINATING = "terminating"
