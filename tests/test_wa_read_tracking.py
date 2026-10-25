import unittest
from unittest.mock import patch

from alfa.core.db.connection import init_db_sync
from alfa.core.db.wa_tracking import (
    archive_wa_messages_sync,
    clear_wa_reported_state_sync,
    get_last_read_wa_ts_sync,
    get_read_wa_msg_ids_sync,
    is_wa_message_read_sync,
    record_wa_messages_read_sync,
    search_wa_archive_sync,
    set_last_read_wa_ts_sync,
)
from alfa.tools.system.integrations import (
    wa_clear_history,
    wa_get_incoming,
    wa_get_messages,
    wa_mark_read,
)


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
        with patch("alfa.tools.system.integrations._wa_api", return_value={"status": "success", "incoming": []}):
            res = wa_get_incoming(limit=5, only_unread=False, mark_as_read=False)
            self.assertEqual(res.get("status"), "success")
            self.assertIn("incoming", res)
            self.assertIn("total", res)
            self.assertIn("unread_count", res)

    def test_wa_get_incoming_filters_seen_and_sorts_newest_first(self):
        """Verify wa_get_incoming filters already seen messages and sorts newest first."""
        # Pre-mark msg_read_1 as read
        record_wa_messages_read_sync([{"msg_id": "msg_read_1", "chat": "c1"}])

        mock_incoming = [
            {"msg_id": "msg_read_1", "msg_ts": 100, "ts": "2026-10-01T01:00:00Z", "body": "old read"},
            {"msg_id": "msg_new_1", "msg_ts": 200, "ts": "2026-10-01T02:00:00Z", "body": "new older"},
            {"msg_id": "msg_new_2", "msg_ts": 300, "ts": "2026-10-01T03:00:00Z", "body": "new latest"},
        ]

        with patch("alfa.tools.system.integrations._wa_api", return_value={"status": "success", "incoming": mock_incoming}):
            # Test default: only_unread=True, mark_as_read=False
            res = wa_get_incoming(limit=10, only_unread=True, mark_as_read=False)
            self.assertEqual(res["status"], "success")
            incoming = res["incoming"]

            # msg_read_1 should be excluded
            ids = [m["msg_id"] for m in incoming]
            self.assertNotIn("msg_read_1", ids)
            self.assertIn("msg_new_2", ids)
            self.assertIn("msg_new_1", ids)

            # msg_new_2 (msg_ts=300) must come before msg_new_1 (msg_ts=200) (newest first)
            self.assertEqual(incoming[0]["msg_id"], "msg_new_2")
            self.assertEqual(incoming[1]["msg_id"], "msg_new_1")

    def test_wa_get_incoming_defaults_to_unread(self):
        """Verify wa_get_incoming defaults to only_unread=True without arguments."""
        record_wa_messages_read_sync([{"msg_id": "already_read_default", "chat": "c2"}])
        mock_incoming = [
            {"msg_id": "already_read_default", "msg_ts": 100, "body": "read"},
            {"msg_id": "fresh_msg_default", "msg_ts": 200, "body": "unread"},
        ]
        with patch("alfa.tools.system.integrations._wa_api", return_value={"status": "success", "incoming": mock_incoming}):
            res = wa_get_incoming()
            self.assertEqual(res["status"], "success")
            self.assertEqual(len(res["incoming"]), 1)
            self.assertEqual(res["incoming"][0]["msg_id"], "fresh_msg_default")

    def test_wa_get_incoming_qr_warning(self):
        """Verify wa_get_incoming alerts when client_status is QR_READY."""
        with patch("alfa.tools.system.integrations._wa_api", return_value={"status": "success", "client_status": "QR_READY", "is_ready": False, "incoming": []}):
            res = wa_get_incoming()
            self.assertIn("QR_READY", res.get("warning", "") or res.get("message", ""))

    def test_wa_clear_history(self):
        """Verify wa_clear_history cleans archive and read state correctly."""
        archive_wa_messages_sync([{"msg_id": "test_clear_arch_1", "body": "archive clear me"}])
        record_wa_messages_read_sync([{"msg_id": "test_clear_read_1", "chat": "c3"}])

        self.assertTrue(is_wa_message_read_sync("test_clear_read_1"))
        self.assertGreaterEqual(len(search_wa_archive_sync(query="archive clear me")), 1)

        with patch("alfa.tools.system.integrations._wa_api", return_value={"status": "success"}):
            res = wa_clear_history(target="all", clear_archive=True, clear_read_state=True)
            self.assertEqual(res["status"], "success")

        self.assertFalse(is_wa_message_read_sync("test_clear_read_1"))
        self.assertEqual(len(search_wa_archive_sync(query="archive clear me")), 0)

    def test_wa_get_messages_filters_seen_and_sorts_newest_first(self):
        """Verify wa_get_messages filters already seen messages and orders newest first."""
        record_wa_messages_read_sync([{"id": "chat_msg_old", "chat": "grup1"}])

        mock_msgs = [
            {"id": "chat_msg_old", "sender": "User1", "body": "sudah dibaca", "ts": 100, "from_me": False},
            {"id": "chat_msg_new_a", "sender": "User2", "body": "pesan baru 1", "ts": 200, "from_me": False},
            {"id": "chat_msg_new_b", "sender": "User3", "body": "pesan baru 2", "ts": 300, "from_me": False},
        ]

        with patch("alfa.tools.system.integrations._wa_api", return_value={"status": "success", "chat_name": "Grup A", "messages": mock_msgs}):
            # Test only_unread=True
            res = wa_get_messages(chat="Grup A", limit=10, only_unread=True, mark_as_read=False)
            self.assertEqual(res["status"], "success")
            msgs = res["messages"]

            ids = [m["id"] for m in msgs]
            self.assertNotIn("chat_msg_old", ids)
            self.assertEqual(len(msgs), 2)
            # Newest first
            self.assertEqual(msgs[0]["id"], "chat_msg_new_b")
            self.assertEqual(msgs[1]["id"], "chat_msg_new_a")


class TestWAReportedTracking(unittest.TestCase):
    def setUp(self):
        clear_wa_reported_state_sync()

    def tearDown(self):
        clear_wa_reported_state_sync()

    def test_record_and_get_reported_ids(self):
        from alfa.core.db.wa_tracking import (
            get_reported_wa_msg_ids_sync,
            is_wa_message_reported_sync,
            record_wa_messages_reported_sync,
        )

        msgs = [
            {"msg_id": "rep_1", "chat_id": "c1", "chat_name": "Grup A", "msg_ts": 100},
            {"msg_id": "rep_2", "chat_id": "c2", "chat_name": "Grup B", "msg_ts": 200},
        ]
        self.assertFalse(is_wa_message_reported_sync("rep_1"))
        recorded = record_wa_messages_reported_sync(msgs, shift="daily")
        self.assertEqual(recorded, 2)
        self.assertTrue(is_wa_message_reported_sync("rep_1"))
        self.assertTrue(is_wa_message_reported_sync("rep_2"))
        self.assertFalse(is_wa_message_reported_sync("rep_3"))

        rep_set = get_reported_wa_msg_ids_sync(["rep_1", "rep_3"])
        self.assertIn("rep_1", rep_set)
        self.assertNotIn("rep_3", rep_set)


if __name__ == "__main__":
    unittest.main()
