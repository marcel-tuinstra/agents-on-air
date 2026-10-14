#!/usr/bin/env python3
"""Start the local viewer without voice models or platform-specific engines."""
import os
from pathlib import Path
import sys
os.execv(sys.executable,[sys.executable,str(Path(__file__).resolve().parent/'server.py'),'--open-browser',*sys.argv[1:]])
