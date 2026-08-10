"""AgentOps AUTO/MANUAL runtime adapter (AGE-30).

Thin control glue only. Durable state belongs to LoopX; GPT Web transport
belongs to the existing Neutral Relay. This package only:
  - reads the active Linear task (mode + criteria),
  - reads the exact-PR/HEAD GitHub review verdict,
  - decides the AUTO/MANUAL next step,
  - keeps a watcher alive until terminal (PR/task closure or completion).

No risk classifier, no parallel state kernel, no re-implemented transport.
"""
