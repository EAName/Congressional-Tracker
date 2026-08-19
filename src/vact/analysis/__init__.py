"""Analysis layer: the signed scoring frame and everything built on it.

This package sits on top of the ingest/classify/publication pipeline. It never
persists a computed metric — signed scores are recomputed live from
`data/votes.csv` (or the warehouse SQL path) every time the frame is built
(AGENTS.md §8). The only persisted scoring input is adjudicated valence.
"""
