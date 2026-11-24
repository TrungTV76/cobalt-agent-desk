#!/usr/bin/env python3
"""Convenience entrypoint so `python server.py` works directly from a git clone."""

from __future__ import annotations

from cobalt_desk.server import main

if __name__ == "__main__":
    main()
