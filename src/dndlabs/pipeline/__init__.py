"""Pipeline orchestration: the run queue's worker and the stages of a run.

A run goes ingest -> resolve -> validate -> store -> featurize -> enrich
(``orchestrator.py``), executed by ``worker.py``; ``assessment.py`` and
``exporter.py`` serve finished datasets, and ``factory.py`` wires it all.
"""
