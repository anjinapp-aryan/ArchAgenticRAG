"""Langfuse tracing: off by default, LangChain callback when enabled, fail fast when the server is unusable.

No test needs a Langfuse server.
"""

from __future__ import annotations

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda

from archagenticrag.evaluation import runner as runner_module
from archagenticrag.evaluation.langfuse_sync import LangfuseUnavailable, langchain_callbacks, make_client
from archagenticrag.evaluation.persistence import read_run

from .test_runner import _run


@pytest.fixture
def unreachable_langfuse(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:9")  # nothing listens on the discard port
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)


def test_disabled_tracing_adds_no_callback():
    assert langchain_callbacks(False) == []


def test_enabled_tracing_adds_the_langfuse_langchain_handler(unreachable_langfuse):
    from langfuse.langchain import CallbackHandler

    (handler,) = langchain_callbacks(True)
    assert isinstance(handler, CallbackHandler)  # constructing it does not contact the server


def test_unavailable_server_fails_before_any_model_call(unreachable_langfuse):
    with pytest.raises(LangfuseUnavailable, match="Langfuse"):
        make_client(True)


def test_runner_passes_tracing_callbacks_to_the_graph(mini_repo, monkeypatch):
    class Seen(BaseCallbackHandler):
        chains = 0

        def on_chain_start(self, *args, **kwargs):  # noqa: ANN002, ANN003
            Seen.chains += 1

    monkeypatch.setattr(runner_module, "langchain_callbacks", lambda enabled: [Seen()])
    root, config_path = mini_repo()
    run_dir = _run(root, config_path, target=RunnableLambda(lambda inputs: {"answer": "42.", "documents": []}))
    assert Seen.chains >= 3  # one per golden item at least
    assert read_run(run_dir)["manifest"]["config"]["langfuse"]["enabled"] is False
