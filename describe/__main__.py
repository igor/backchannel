import logging
import os

from describe.cli import main

logging.basicConfig(
    level=os.environ.get("BC_DESCRIBE_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
main()
raise SystemExit(0)
