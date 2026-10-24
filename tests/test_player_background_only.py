"""
Unit tests to ensure play_youtube_music plays in the background only (no double audio from browser).
"""

from unittest.mock import patch

from alfa.tools.media.player import play_youtube_music


def test_play_youtube_music_auto_mode_does_not_open_browser():
    """In auto mode (default), play_youtube_music must NOT open desktop browser."""
    fake_info = {
        "ok": True,
        "id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "duration": 212,
        "uploader": "Rick Astley",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "watch_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }

    with patch("alfa.tools.media.player._resolve", return_value=fake_info), \
         patch("alfa.tools.media.player._start_playback", return_value=(True, "Streaming started", "12345")) as mock_play, \
         patch("alfa.tools.desktop.input_automation.open_url_in_default_browser") as mock_browser:
        res = play_youtube_music("rick astley", mode="auto")
        assert res["status"] == "success"
        assert res["audio"]["playing"] is True
        assert res["audio"]["pid"] == "12345"
        mock_play.assert_called_once_with("dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        # Browser must NOT be opened!
        mock_browser.assert_not_called()
        assert "browser" not in res or not res.get("browser", {}).get("opened")


def test_play_youtube_music_audio_mode_does_not_open_browser():
    """In audio mode, play_youtube_music must NOT open desktop browser."""
    fake_info = {
        "ok": True,
        "id": "abc12345",
        "title": "Test Song",
        "duration": 180,
        "uploader": "Artist",
        "url": "https://www.youtube.com/watch?v=abc12345",
        "watch_url": "https://www.youtube.com/watch?v=abc12345",
    }

    with patch("alfa.tools.media.player._resolve", return_value=fake_info), \
         patch("alfa.tools.media.player._start_playback", return_value=(True, "Playing", "54321")), \
         patch("alfa.tools.desktop.input_automation.open_url_in_default_browser") as mock_browser:
        res = play_youtube_music("test song", mode="audio")
        assert res["status"] == "success"
        assert res["audio"]["playing"] is True
        mock_browser.assert_not_called()


def test_play_youtube_music_browser_mode_opens_browser_only():
    """In explicit browser mode, browser is opened and audio is NOT started."""
    fake_info = {
        "ok": True,
        "id": "xyz98765",
        "title": "Video Only",
        "duration": 300,
        "uploader": "Channel",
        "url": "https://www.youtube.com/watch?v=xyz98765",
        "watch_url": "https://www.youtube.com/watch?v=xyz98765",
    }

    with patch("alfa.tools.media.player._resolve", return_value=fake_info), \
         patch("alfa.tools.media.player._start_playback") as mock_play, \
         patch("alfa.tools.desktop.input_automation.open_url_in_default_browser", return_value=(True, "brave")) as mock_browser:
        res = play_youtube_music("video only", mode="browser")
        assert res["status"] == "success"
        assert res["browser"]["opened"] is True
        mock_browser.assert_called_once()
        mock_play.assert_not_called()


def test_play_youtube_music_stop_mode():
    """Mode stop stops local audio without searching."""
    with patch("alfa.tools.media.player._stop_audio", return_value={"status": "success", "message": "Stopped"}) as mock_stop:
        res = play_youtube_music(mode="stop")
        assert res["status"] == "success"
        mock_stop.assert_called_once()
