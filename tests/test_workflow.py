import unittest

from smpldoc.domain.workflow import TransitionError, allowed_actions, next_status

TABLE = {
    "review": {"received": "ready", "held": "ready", "failed": "ready"},
    "hold": {"received": "held", "ready": "held", "failed": "held"},
    "close": {"received": "closed", "extracting": "closed", "ready": "closed", "held": "closed", "failed": "closed"},
    "reopen": {"closed": "ready"},
    "reprocess": {"extracting": "extracting", "ready": "extracting", "held": "extracting", "failed": "extracting", "closed": "extracting", "done": "extracting"},
    "forward": {"ready": "ready"},
}


class WorkflowTest(unittest.TestCase):
    def test_every_allowed_move(self):
        for action, moves in TABLE.items():
            for frm, to in moves.items():
                self.assertEqual(next_status(frm, action), to, f"{action} from {frm}")

    def test_every_other_move_is_refused(self):
        for action, moves in TABLE.items():
            for status in ("received", "extracting", "ready", "held", "failed", "closed", "done"):
                if status not in moves:
                    with self.assertRaises(TransitionError, msg=f"{action} from {status}"):
                        next_status(status, action)

    def test_an_unknown_action_is_refused(self):
        with self.assertRaises(TransitionError):
            next_status("ready", "explode")

    def test_allowed_actions_lists_what_a_person_can_do_now(self):
        self.assertEqual(allowed_actions("ready"), ["close", "forward", "hold", "reprocess"])
        self.assertEqual(allowed_actions("closed"), ["reopen", "reprocess"])
        self.assertEqual(allowed_actions("done"), ["reprocess"])


if __name__ == "__main__":
    unittest.main()
