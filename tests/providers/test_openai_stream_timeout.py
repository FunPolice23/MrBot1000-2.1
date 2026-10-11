import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents.providers.openai_compatible import OpenAICompatibleAdapter, _stream_timeout_seconds


class _FakeCompletions:
    def create(self, **_kwargs):
        return iter([SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content="ok", reasoning_content=None))])])


class _FakeOpenAIClient:
    captured = {}

    def __init__(self, **kwargs):
        self.captured = kwargs
        _FakeOpenAIClient.captured = kwargs
        self.chat = SimpleNamespace(completions=_FakeCompletions())


class TestOpenAIStreamTimeout(unittest.TestCase):
    def test_streaming_client_receives_timeout(self):
        fake_openai = types.SimpleNamespace(OpenAI=_FakeOpenAIClient)
        with patch.dict(sys.modules, {"openai": fake_openai}), \
             patch.dict(os.environ, {"OPENAI_STREAM_TIMEOUT_SECONDS": "7"}):
            adapter = OpenAICompatibleAdapter(
                "test", api_key_env="KEY", base_url="http://127.0.0.1:1234",
                require_api_key=False)
            self.assertEqual(adapter.complete("m", "s", "u", 10), "ok")
        self.assertEqual(_FakeOpenAIClient.captured["timeout"], 7.0)

    def test_timeout_is_bounded_and_invalid_values_use_default(self):
        with patch.dict(os.environ, {"OPENAI_STREAM_TIMEOUT_SECONDS": "0"}):
            self.assertEqual(_stream_timeout_seconds(), 1.0)
        with patch.dict(os.environ, {"OPENAI_STREAM_TIMEOUT_SECONDS": "invalid"}):
            self.assertEqual(_stream_timeout_seconds(), 120.0)


if __name__ == "__main__":
    unittest.main()
