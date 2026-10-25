You are working in /workspace, an empty project.

Create a tiny Python command-line tool `wordfreq.py`:

1. `top_words(text: str, n: int = 3) -> list[tuple[str, int]]` returns the `n` most frequent words with their counts.
   Words are case-insensitive runs of letters and apostrophes (`don't` is one word); everything else separates words.
   Sort by count (highest first), then alphabetically. `n <= 0` returns an empty list.
2. Running `python wordfreq.py FILE [-n N]` prints one `word<TAB>count` line per result for the text in FILE
   (default N is 3). A missing file prints an error to stderr and exits with status 1.
3. Add at least three pytest tests in `tests/test_wordfreq.py` and make sure `pytest -q` passes.

When you are done, reply with a one-paragraph summary of what you built.
