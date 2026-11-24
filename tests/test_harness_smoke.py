"""Smoke test untuk memastikan harness fixtures tersedia."""



def test_fake_llm_fixture(fake_llm):
    assert fake_llm is not None
    import asyncio
    resp = asyncio.run(fake_llm.complete("test prompt"))
    assert isinstance(resp.text, str)
    assert "Fake" in resp.text


def test_discord_client_fixture(discord_client):
    assert discord_client is not None
    channel = discord_client.create_channel()
    assert channel is not None
    assert channel.id > 0


def test_discord_channel_fixture(discord_channel):
    import asyncio
    assert discord_channel is not None
    msg = asyncio.run(discord_channel.send("hello"))
    assert msg.content == "hello"


def test_fake_task_group_fixture(fake_task_group_fixture):
    assert fake_task_group_fixture is not None


def test_sequential_task_group_fixture(sequential_task_group_fixture):
    assert sequential_task_group_fixture is not None


def test_ptb_app_fixture(ptb_app_factory):
    import asyncio

    async def _test():
        async with ptb_app_factory(handlers=[]) as app:
            assert app is not None
            assert hasattr(app, "bot")
            # Test feed_update
            from tests.harness.ptb_app import make_mock_message, make_mock_update
            msg = make_mock_message(text="/start")
            upd = make_mock_update(message=msg)
            await app.feed_update(upd)
            return app

    app = asyncio.run(_test())
    assert app is not None


def test_fake_os_fixture(fake_os):
    import os
    path = os.path.expanduser("~/test.txt")
    assert str(fake_os) in path
    assert os.path.exists(fake_os / "test.txt") is False  # belum dibuat


def test_sched_env_fixture(sched_env):
    # Hanya memastikan fixture jalan tanpa error
    pass
