import subprocess
import sys


def cli(db, *args):
    return subprocess.run([sys.executable, "-m", "inventory", "--db", str(db), *map(str, args)],
                          capture_output=True, text=True, timeout=60)


def lines(proc):
    return [l for l in proc.stdout.strip().splitlines() if l.strip()]
