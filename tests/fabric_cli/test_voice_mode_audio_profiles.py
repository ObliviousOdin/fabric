import asyncio
from contextlib import contextmanager
import json
from typing import Optional


def test_desktop_audio_routes_scope_each_request_to_the_selected_profile(
    monkeypatch, tmp_path
):
    import fabric_cli.web_server as web_server
    import tools.transcription_tools as transcription_tools
    import tools.tts_tool as tts_tool

    scoped_profiles: list[Optional[str]] = []

    @contextmanager
    def capture_scope(profile):
        scoped_profiles.append(profile)
        yield None

    audio_file = tmp_path / "voice.mp3"
    audio_file.write_bytes(b"ID3profile-scoped-audio")

    monkeypatch.setattr(web_server, "_config_profile_scope", capture_scope)
    monkeypatch.setattr(web_server, "load_env", lambda: {})
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(
        transcription_tools,
        "transcribe_audio",
        lambda _path: {
            "provider": "fixture",
            "success": True,
            "transcript": "profile scoped",
        },
    )
    monkeypatch.setattr(
        tts_tool,
        "text_to_speech_tool",
        lambda _text: json.dumps({
            "file_path": str(audio_file),
            "provider": "fixture",
            "success": True,
        }),
    )

    profile = "voice_operator"
    transcription = asyncio.run(
        web_server.transcribe_audio_upload(
            web_server.AudioTranscriptionRequest(
                data_url="data:audio/webm;base64,aGVsbG8="
            ),
            profile=profile,
        )
    )
    voices = asyncio.run(web_server.get_elevenlabs_voices(profile=profile))
    speech = asyncio.run(
        web_server.speak_text(web_server.TTSSpeakRequest(text="Hello"), profile=profile)
    )

    assert transcription["ok"] is True
    assert voices == {"available": False, "voices": []}
    assert speech["provider"] == "fixture"
    assert scoped_profiles == [profile, profile, profile]
