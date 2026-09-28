import logging

import structlog

from config.config import Config

logging.basicConfig(
    level=(logging.DEBUG if Config.debug else logging.INFO),
    # format="%(levelname)s\t[%(filename)s](%(funcName)s)\t%(message)s",
    format="%(levelname)s\t[%(filename)s]\t%(message)s",
)
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()
# logger = logging.getLogger()

# Suppress HTTP request/response logs
for logger_name in (
    "urllib3",
    "urllib3.connectionpool",
    "http.client",
    "requests.packages.urllib3",
    "httpx",
    "httpcore",
    "kubernetes.client.rest",
):
    logging.getLogger(logger_name).setLevel(logging.WARNING)
