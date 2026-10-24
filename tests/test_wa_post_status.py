"""Unit tests for WhatsApp status posting tool (wa_post_status)."""

from unittest.mock import patch

from alfa.tools.system.integrations import wa_post_status


def test_wa_post_status_tool():
    """Test wa_post_status tool sends request to wa-sheets-bot API."""
    with patch("alfa.tools.system.integrations._wa_api") as mock_api:
        mock_api.return_value = {"status": "success", "id": "msg_123", "to": "status@broadcast"}
        res = wa_post_status(text="Status uji coba", background_color="#0b3296")
        assert res["status"] == "success"
        mock_api.assert_called_once_with(
            "POST",
            "/api/status",
            body={"text": "Status uji coba", "backgroundColor": "#0b3296"},
        )
