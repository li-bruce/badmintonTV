"""Windows gate: never start a CLI until worker assigned us to its Job Object."""

import json
import subprocess
import sys


def main():
    line = sys.stdin.readline()
    if not line:
        return 1
    argv = json.loads(line)
    # The worker is the only writer of this stdin; argv came from fixed/admin configuration.
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, shell=False)
    return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
