import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from analyze_pipeline import _extract_json_payload
from tasks import _StaticValidationError, _validate_static_answer


class StaticHandlingTests(unittest.TestCase):
    def test_extract_json_payload_accepts_prefixed_json(self) -> None:
        payload = _extract_json_payload('VariableA: {"VariableA":{"senders":"sender array"}}')
        self.assertEqual({"VariableA": {"senders": "sender array"}}, payload)

    def test_validate_static_answer_rejects_msg_sender_alias(self) -> None:
        vul = {
            "name": "unauthorized-transfer",
            "static": {
                "exclude_variable": {
                    "VariableA": ["msgsender", "msg.sender"],
                }
            },
        }

        with self.assertRaises(_StaticValidationError):
            _validate_static_answer(
                vul,
                {"VariableA": "_msgSender()"},
                {"VariableA": {"_msgSender()": "caller address"}},
            )


if __name__ == "__main__":
    unittest.main()
