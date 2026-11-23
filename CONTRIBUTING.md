# Contributing

Thanks for helping! 🎉 All skill levels are welcome.

## Ways to contribute
- **Papers**: add to [`papers/reading-list.md`](papers/reading-list.md) or write a summary
  using [`papers/summaries/TEMPLATE.md`](papers/summaries/TEMPLATE.md).
- **Code**: pick an item from [ROADMAP.md](ROADMAP.md).
- **Experiments**: add a write-up in `experiments/YYYY-MM-DD-short-name.md` (setup, data,
  results, what went wrong).
- **Docs**: fix errors, clarify explanations, add diagrams.
- **Issues**: report mistakes, suggest ideas, ask questions.

## Workflow
1. Fork the repo and create a branch: `git checkout -b feat/phase-sanitization`.
2. Make focused changes (one topic per PR).
3. For code: add tests in `tests/` and run `pytest`.
4. Commit with a clear message, e.g. `docs: summarize AdaPose paper`.
5. Open a pull request and fill out the template.

## Style
- Python ≥ 3.10, formatted with `black`, linted with `ruff`.
- Type hints and docstrings for public functions.
- Markdown: one sentence or idea per line where practical, links to arXiv abstracts (not PDFs).

## Rules
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md) and [Ethics policy](ETHICS.md).
- Don't commit datasets, model weights, or copyrighted paper PDFs.
- Cite your sources.
