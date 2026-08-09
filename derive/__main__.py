import logging
import os
from derive.cli import main

logging.basicConfig(
    level=os.environ.get("BC_DERIVE_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
main()
raise SystemExit(0)
