"""Analysis layer: the signed scoring frame and everything built on it.

This package sits on top of the ingest/classify/publication pipeline. It never
persists a computed metric — signed scores are recomputed live from the
warehouse every time the frame is built (AGENTS.md §8). The only persisted
input it owns is adjudicated valence (fact_vote_valence).
"""
