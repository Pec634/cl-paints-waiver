"""Transcription runs in an isolated process that can be cancelled immediately."""
import time


def transcription_worker(events, path, model_name, model_root, offline, separate, speaker_count,
                         language=None, hotwords=None):
    try:
        from faster_whisper import WhisperModel

        events.put(("stage", "Loading speech model"))
        model = WhisperModel(model_name, device="cpu", compute_type="int8",
                             download_root=model_root, local_files_only=offline)
        events.put(("stage", "Transcribing audio"))
        started = time.monotonic()
        segments, info = model.transcribe(
            path, language=language, hotwords=hotwords or None,
            beam_size=5, word_timestamps=True, vad_filter=True,
            # Keep brief replies and leave context around speech boundaries.
            vad_parameters=dict(min_speech_duration_ms=100, min_silence_duration_ms=500,
                                speech_pad_ms=400),
            # Avoid carrying a mistaken phrase through the rest of a recording.
            condition_on_previous_text=False,
        )
        timed, turns = [], []
        for segment in segments:
            timed.append(segment)
            turn = dict(start=segment.start, end=segment.end, text=segment.text.strip(), speaker="Speech", review=False)
            if turn["text"]:
                turns.append(turn)
                events.put(("partial", turn))
            if info.duration > 0 and segment.end > 0:
                fraction = min(segment.end / info.duration, 1.0)
                events.put(("estimate", (fraction, time.monotonic() + (time.monotonic() - started) * (1 - fraction) / fraction)))
        warning = ""
        if separate and turns:
            events.put(("stage", "Separating speakers"))
            try:
                from faster_whisper.audio import decode_audio
                from speakers import diarize_turns
                started = time.monotonic()

                def report(fraction):
                    events.put(("estimate", (fraction, time.monotonic() + (time.monotonic() - started) * (1 - fraction) / fraction)))

                turns = diarize_turns(decode_audio(path), timed, speaker_count, report)
            except Exception as exc:
                import traceback
                events.put(("diagnostic", traceback.format_exc()))
                warning = f"Speaker separation failed; plain transcript retained. {exc}"
        events.put(("result", (turns, info.language, warning)))
    except Exception as exc:
        events.put(("error", str(exc)))
    finally:
        events.put(("done", None))
