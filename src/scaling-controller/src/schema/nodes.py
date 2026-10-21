from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel

from schema.router import PodStatus


class Node(BaseModel):
    name: str
    status: str
    roles: list[str]
    age: str
    version: str
    internal_ip: str
    external_ip: str
    os_image: str
    kernel_version: str
    container_runtime: str
