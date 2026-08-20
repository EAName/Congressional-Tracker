"""CLI shim. Prefer `vact irt` or `make irt` from the repo root."""

from __future__ import annotations

from vact.analysis.irt_pipeline import run_irt


def main() -> None:
    payload = run_irt(progressbar=True)
    print(
        f"wrote IRT artifact: {payload['n_members']} members, "
        f"{payload['n_items']} items, R-hat max {payload['rhat_max']}"
    )


if __name__ == "__main__":
    main()
