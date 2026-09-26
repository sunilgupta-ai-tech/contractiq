The regression baseline for `python -m app.evaluation run --baseline eval/baseline/report.json`.

Create it on a known-good commit with the production models configured (`make eval-baseline`),
review `report.md`, and commit `report.json`. Update it deliberately, in its own commit, whenever
a change is *meant* to move the metrics (new model, new prompt, new chunker version).
See docs/evaluation.md.
