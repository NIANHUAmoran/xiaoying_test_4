import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from src.models import HTTPModel, ModelServiceError, parse_action_text


class ModelTests(unittest.TestCase):
    def test_http_contract_and_secret_not_in_prompt(self):
        env = {"LLM_BASE_URL": "https://provider.example/v1", "LLM_MODEL": "example", "LLM_API_KEY": "local-secret"}
        decision = {"action": "search_materials", "arguments": {"query": "字幕"}, "basis": "Need sources"}
        body = json.dumps({"choices": [{"message": {"content": json.dumps(decision)}}]}).encode()
        with patch.dict(os.environ, env), patch("urllib.request.urlopen", return_value=io.BytesIO(body)) as mocked:
            self.assertEqual(HTTPModel().decide({"request": {}}), decision)
            self.assertNotIn(b"local-secret", mocked.call_args.args[0].data)

    def test_provider_error_does_not_leak_credentials_or_body(self):
        env = {"LLM_BASE_URL": "https://provider.example/v1", "LLM_MODEL": "example", "LLM_API_KEY": "local-secret"}
        error = urllib.error.HTTPError("https://private-host/", 401, "local-secret", {}, None)
        with patch.dict(os.environ, env), patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ModelServiceError) as caught:
                HTTPModel().decide({})
            self.assertEqual(str(caught.exception), "provider_http_401")

    def test_complete_json_fence_is_unwrapped_without_changing_the_action(self):
        action = {"action": "estimate_duration", "arguments": {}, "basis": "Check the draft"}
        value, output_format = parse_action_text("```json\n" + json.dumps(action) + "\n```")
        self.assertEqual(value, action)
        self.assertEqual(output_format, "fenced_json")

    def test_arbitrary_prose_and_broken_json_are_not_repaired_or_logged(self):
        for text in ["private-body before {broken}", '```json\n{"action":\n```']:
            with self.assertRaises(ModelServiceError) as caught:
                parse_action_text(text)
            self.assertNotIn("private-body", str(caught.exception))
            self.assertIn("invalid_model_json_line_", str(caught.exception))
