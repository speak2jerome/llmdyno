"""`python -m llmdyno` and the `llmdyno` command: the web app by default, and every library call as a command
(see llmdyno/cli.py and `llmdyno --help`)."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
