"""Segmentation: where does each part of a filing begin and end.

`us.py` anchors on 10-K Item boundaries, which are regex-reliable.
`hk.py` falls back to heading heuristics for filings without them.
`router.py` picks between them on `documents.format`.
"""
