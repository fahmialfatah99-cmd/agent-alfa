import unittest
from alfa.core.db.connection import init_db_sync
from alfa.core.db.wa_tracking import (
    record_wa_messages_read_sync,
    get_read_wa_msg_ids_sync,
    is_wa_message_read_sync,
    mark_chat_read_sync,
    get_last_read_wa_ts_sync,
    set_last_read_wa_ts_sync,
)
from alfa.tools.system.integrations import wa_get_incoming, wa_mark_read


class TestWAReadTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db_sync()

    def test_record_and_check_read_state(self):
        mid = "test_unit_msg_999"
        msgs = [{"msg_id": mid, "chat": "120363@g.us", "sender_name": "TestUser", "msg_ts": 1792465000}]
        ins = record_wa_messages_read_sync(msgs)
        self.assertGreaterEqual(ins, 0)

        self.assertTrue(is_wa_message_read_sync(mid))
        self.assertFalse(is_wa_message_read_sync("random_non_existent_id"))

        read_set = get_read_wa_msg_ids_sync([mid, "another_id"])
        self.assertIn(mid, read_set)
        self.assertNotIn("another_id", read_set)

    def test_last_read_timestamp(self):
        set_last_read_wa_ts_sync(1792469999)
        self.assertEqual(get_last_read_wa_ts_sync(), 1792469999)

    def test_wa_mark_read_tool(self):
        res = wa_mark_read(chat="120363@g.us", msg_id="test_unit_msg_888", send_seen_to_wa=False)
        self.assertEqual(res.get("status"), "success")
        self.assertTrue(is_wa_message_read_sync("test_unit_msg_888"))

    def test_wa_get_incoming_parameters(self):
        res = wa_get_incoming(limit=5, only_unread=False, mark_as_read=False)
        self.assertEqual(res.get("status"), "success")
        self.assertIn("incoming", res)
        self.assertIn("total", res)
        self.assertIn("unread_count", res)


if __name__ == "__main__":
    unittest.main()
