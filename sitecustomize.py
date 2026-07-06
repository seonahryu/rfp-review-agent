from __future__ import annotations

import os
import sys


os.environ.setdefault("PYTHONIOENCODING", "utf-8")

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")
