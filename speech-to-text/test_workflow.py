import json
import queue
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import Mock, patch

import numpy as np

import app
from documents import export_word, load_session, save_session, timestamp
from engine import transcription_worker
from speakers import decode_labels, make_turns


class DocumentTests(unittest.TestCase):
    def test_atomic_recovery_roundtrip_and_reject_invalid_positions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.json"
            data = dict(version=1, text="Hello café", turns=[], speakers={})
            save_session(path, data)
            self.assertEqual(load_session(path), data)
            self.assertFalse(path.with_suffix(".tmp").exists())
            data["turns"] = [dict(begin=-1)]
            save_session(path, data)
            with self.assertRaises(ValueError):
                load_session(path)

    def test_word_export_preserves_edited_text_and_timestamps(self):
        from docx import Document
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "transcript.docx"
            export_word(path, "Recording: demo.wav\n\n[00:00:04] Alice:\nEdited café text.\n\n[00:00:08] Bob:\nReply.")
            document = Document(path)
            text = "\n".join(p.text for p in document.paragraphs)
            self.assertIn("[00:00:04] Alice:\nEdited café text.", text)
            self.assertIn("[00:00:08] Bob:\nReply.", text)
            paragraph = next(p for p in document.paragraphs if p.text.startswith("[00:00:04]"))
            self.assertTrue(paragraph.runs[0].bold)

    def test_timestamp_hours(self):
        self.assertEqual(timestamp(3661.9), "01:01:01")


class TurnTests(unittest.TestCase):
    def test_smoothing_retains_a_strong_short_reply(self):
        labels = decode_labels(np.array([[.95, .1], [.9, .2], [.1, .95], [.95, .1]]), [0, 1, 2, 3], [.9, 1.9, 2.9, 3.9])
        self.assertEqual(labels, [0, 0, 1, 0])

    def test_smoothing_suppresses_weak_single_word_flip(self):
        labels = decode_labels(np.array([[.95, .1], [.68, .7], [.95, .1]]), [0, 1, 2], [.9, 1.9, 2.9])
        self.assertEqual(labels, [0, 0, 0])

    def test_word_aligned_turns_preserve_punctuation_and_returning_speakers(self):
        words = [S(start=0., end=1., word=" Hello"), S(start=1., end=1.1, word=","),
                 S(start=2., end=2.4, word=" Yes."), S(start=3., end=4., word=" Thanks.")]
        turns = make_turns(words, [8, 8, 2, 8], [False, False, True, False])
        self.assertEqual([t["speaker"] for t in turns], ["Person 1", "Person 2", "Person 1"])
        self.assertEqual(turns[0]["text"], "Hello,")
        self.assertEqual(turns[1]["start"], 2.)
        self.assertTrue(turns[1]["review"])


class EngineTests(unittest.TestCase):
    def test_language_and_vocabulary_reach_decoder_with_short_reply_detection(self):
        events = queue.Queue()
        model = Mock()
        model.transcribe.return_value = (iter([]), S(duration=3., language="en"))
        with patch("faster_whisper.WhisperModel", return_value=model):
            transcription_worker(events, "test.wav", "small", "models", True, False, None,
                                 "en", "C L Paints, Hazel")
        options = model.transcribe.call_args.kwargs
        self.assertEqual(options["language"], "en")
        self.assertEqual(options["hotwords"], "C L Paints, Hazel")
        self.assertEqual(options["vad_parameters"]["min_speech_duration_ms"], 100)
        self.assertFalse(options["condition_on_previous_text"])
        self.assertTrue(options["word_timestamps"])
        self.assertFalse(any(kind == "error" for kind, _ in list(events.queue)))

    def test_speaker_failure_retains_timestamped_plain_transcript(self):
        events = queue.Queue()
        segment = S(start=1., end=2., text=" Hello.", words=[])
        model = S(transcribe=lambda *args, **kwargs: (iter([segment]), S(duration=3., language="en")))
        with patch("faster_whisper.WhisperModel", return_value=model), patch("faster_whisper.audio.decode_audio", return_value=np.zeros(16000)), patch("speakers.diarize_turns", side_effect=RuntimeError("test failure")):
            transcription_worker(events, "test.wav", "base", "models", True, True, 2)
        messages = []
        while not events.empty():
            messages.append(events.get())
        result = next(value for kind, value in messages if kind == "result")
        self.assertEqual(result[0][0]["text"], "Hello.")
        self.assertEqual(result[0][0]["start"], 1.)
        self.assertIn("plain transcript retained", result[2])
        self.assertEqual(messages[-1][0], "done")
        self.assertTrue(any(kind == "partial" for kind, _ in messages))


class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = app.tk.Tk()
        self.root.withdraw()
        self.ui = app.SpeechApp(self.root, data_dir=self.folder.name, recover=False)
        self.source = str(Path(self.folder.name) / "conversation.wav")
        self.items = [dict(start=1., end=2., text="Person 1 appears in spoken text.", speaker="Person 1", review=False),
                      dict(start=3., end=4., text="Reply.", speaker="Person 2", review=True),
                      dict(start=5., end=6., text="Returning speaker.", speaker="Person 1", review=False)]

    def tearDown(self):
        if self.ui.busy:
            self.ui.cancel()
        self.ui.closed = True
        self.ui.stop_playback()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.folder.cleanup()

    def test_accuracy_controls_are_passed_to_worker_and_locked_during_processing(self):
        self.assertEqual(self.ui.size.get(), "small")
        self.ui.language.set("English")
        self.ui.hotwords.insert(0, "  Hazel, C L Paints  ")
        with patch.object(self.ui.context, "Process") as process:
            self.ui.transcribe(self.source)
            args = process.call_args.kwargs["args"]
            self.assertEqual(args[-2:], ("en", "Hazel, C L Paints"))
            self.assertEqual(str(self.ui.language.cget("state")), "disabled")
            self.assertEqual(str(self.ui.hotwords.cget("state")), "disabled")
            self.ui.finish_processing()
        self.assertEqual(str(self.ui.language.cget("state")), "readonly")
        self.assertEqual(str(self.ui.hotwords.cget("state")), "normal")

    def test_rename_only_headers_and_recording_scope_then_recover_edits(self):
        self.ui.append_turns(self.items, self.source, "first")
        self.ui.append_turns(self.items[:1], self.source, "second")
        self.ui.speaker_choice.current(0)
        self.ui.rename_speaker("Alice")
        content = self.ui.text.get("1.0", "end-1c")
        self.assertEqual(content.count("] Alice:"), 2)
        self.assertEqual(content.count("] Person 1:"), 1)
        self.assertIn("Person 1 appears in spoken text.", content)
        turn = self.ui.turns[0]
        location = self.ui.text.tag_ranges(turn["id"])[-1]
        self.ui.text.insert(location, " Edited!")
        self.assertTrue(self.ui.autosave())
        saved = load_session(self.ui.recovery_path)
        self.ui.restore(saved)
        self.assertIn("Edited!", self.ui.text.get("1.0", "end-1c"))
        self.assertEqual(len(self.ui.turns), 4)
        location = self.ui.text.tag_ranges(self.ui.turns[2]["id"])[0]
        self.assertEqual(self.ui.current_turn(location)["start"], 5.)
        self.ui.speaker_choice.current(0)
        self.ui.rename_speaker("Alicia")
        self.assertEqual(self.ui.text.get("1.0", "end-1c").count("] Alicia:"), 2)

    def test_playback_uses_matching_source_and_exact_time_slice_and_can_stop(self):
        self.ui.append_turns(self.items, self.source, "first")
        audio = np.arange(16000 * 7, dtype=np.float32)
        with patch("app.sd.play") as play, patch("app.sd.stop") as stop:
            self.ui.handle_local_event("audio_ready", (self.ui.playback_generation, self.ui.turns[1], audio))
            clip = play.call_args.args[0]
            self.assertEqual(len(clip), 16000)
            self.assertEqual(clip[0], audio[3 * 16000])
            self.assertEqual(play.call_args.args[1], 16000)
            self.assertTrue(self.ui.text.tag_ranges("playing"))
            self.ui.stop_playback()
            stop.assert_called()
            self.assertFalse(self.ui.text.tag_ranges("playing"))

    def test_stale_playback_result_after_stop_is_ignored(self):
        self.ui.append_turns(self.items, self.source, "first")
        token = self.ui.playback_generation
        self.ui.stop_playback()
        with patch("app.sd.play") as play:
            self.ui.handle_local_event("audio_ready", (token, self.ui.turns[0], np.zeros(16000)))
            play.assert_not_called()

    def test_cancel_stops_real_process_and_preserves_partial_recovery(self):
        self.ui.pending_source, self.ui.session_id = self.source, "cancelled"
        self.ui.partial_turns = self.items[:1]
        self.ui.worker = self.ui.context.Process(target=time.sleep, args=(30,), daemon=True)
        self.ui.worker.start()
        worker = self.ui.worker
        self.ui.busy = True
        started = time.monotonic()
        self.ui.cancel()
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(self.ui.busy)
        self.assertIn("partial transcript", self.ui.text.get("1.0", "end-1c"))
        saved = load_session(self.ui.recovery_path)
        self.assertIsNone(saved["pending"])
        self.assertEqual(len(saved["turns"]), 1)

    def test_pending_segments_are_recovered_after_interruption(self):
        self.ui.busy = True
        self.ui.pending_source, self.ui.session_id = self.source, "interrupted"
        self.ui.partial_turns = self.items[:1]
        self.ui.autosave()
        data = load_session(self.ui.recovery_path)
        self.ui.busy = False
        self.ui.restore(data)
        self.assertIn("partial transcript", self.ui.text.get("1.0", "end-1c"))
        self.assertEqual(self.ui.turns[0]["start"], 1.)

    def test_autosave_failure_keeps_editor_intact(self):
        self.ui.append_turns(self.items, self.source, "first")
        with patch("app.save_session", side_effect=OSError("disk full")):
            self.assertFalse(self.ui.autosave())
        self.assertIn("disk full", self.ui.autosave_status.get())
        self.assertIn("Reply.", self.ui.text.get("1.0", "end-1c"))

    def test_unicode_names_and_text_survive_recovery_with_playback_links(self):
        self.items[0]["text"] = "Café, 中文 and an emoji 🙂."
        self.ui.append_turns(self.items, self.source, "unicode")
        self.ui.speaker_choice.current(0)
        self.ui.rename_speaker("Zoë 🙂")
        self.assertTrue(self.ui.autosave())
        saved = load_session(self.ui.recovery_path)
        content = self.ui.text.get("1.0", "end-1c")
        self.ui.restore(saved)
        self.assertEqual(content, self.ui.text.get("1.0", "end-1c"))
        ranges = self.ui.text.tag_ranges(self.ui.turns[-1]["id"])
        self.assertIn("Returning speaker.", self.ui.text.get(ranges[0], ranges[-1]))
        self.ui.speaker_choice.current(0)
        self.ui.rename_speaker("Renamed")
        self.assertEqual(self.ui.text.get("1.0", "end-1c").count("] Renamed:"), 2)

    def test_recovery_prompt_cannot_overwrite_saved_workspace(self):
        self.ui.append_turns(self.items, self.source, "previous")
        self.ui.autosave()
        expected = self.ui.recovery_path.read_text(encoding="utf-8")
        self.ui.text.delete("1.0", "end")
        self.ui.recovery_pending = True
        self.ui.autosave()
        self.assertEqual(self.ui.recovery_path.read_text(encoding="utf-8"), expected)
        self.ui.recovery_pending = False


if __name__ == "__main__":
    unittest.main()
