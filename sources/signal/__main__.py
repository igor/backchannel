import logging
import os
from sources.signal.cli import main

logging.basicConfig(
    level=os.environ.get("BC_SIGNAL_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
raise SystemExit(main())