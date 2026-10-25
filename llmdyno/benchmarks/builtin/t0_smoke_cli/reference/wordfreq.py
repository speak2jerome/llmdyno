"""Most frequent words in a text file."""
import argparse
import re
import sys
from collections import Counter

WORD = re.compile(r"[a-z']+")


def top_words(text: str, n: int = 3) -> list[tuple[str, int]]:
    if n <= 0:
        return []
    counts = Counter(WORD.findall(text.lower()))
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file")
    ap.add_argument("-n", type=int, default=3)
    a = ap.parse_args(argv)
    try:
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for word, count in top_words(text, a.n):
        print(f"{word}\t{count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
