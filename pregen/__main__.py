"""
Main entry point for running the package as a module.

Usage:
    python -m pregen scan --output manifest.json
    python -m pregen report --manifest manifest.json
    python -m pregen generate --manifest manifest.json
"""

import sys
from .cli import main

if __name__ == '__main__':
    sys.exit(main())
