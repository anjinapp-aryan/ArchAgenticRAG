"""Evaluation harness: glue between our RAG graphs, Ragas metrics and Langfuse experiments.

Nothing in this package computes a quality metric itself. Metrics come from Ragas;
experiment execution and storage come from Langfuse. This package only loads the
golden dataset, adapts the system under test, records run metadata, and persists
results to disk.
"""
