"""Local speech transcription, review, playback and recovery."""
from pathlib import Path
import math
import multiprocessing as mp
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import uuid
import wave

import numpy as np
import sounddevice as sd

from documents import export_word, load_session, save_session, timestamp
from engine import transcription_worker

BASE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
LANGUAGES = {"Auto detect": None, "English": "en", "French": "fr", "German": "de",
             "Spanish": "es", "Italian": "it", "Portuguese": "pt", "Dutch": "nl",
             "Polish": "pl", "Welsh": "cy", "Chinese": "zh", "Japanese": "ja",
             "Arabic": "ar", "Hindi": "hi"}


class SpeechApp:
    def __init__(self, root, data_dir=None, recover=True):
        self.root = root
        self.data_dir = Path(data_dir) if data_dir else BASE / "data"
        self.recovery_path = self.data_dir / "recovery.json"
        self.recovery_pending = recover
        self.context = mp.get_context("spawn")
        self.worker, self.events, self.stream = None, None, None
        self.local_events = queue.Queue()
        self.chunks, self.turns, self.partial_turns = [], [], []
        self.busy = False
        self.processing_started = 0
        self.processing_stage = "Preparing audio"
        self.estimated_finish = self.transcription_fraction = None
        self.pending_source = self.session_id = None
        self.speaker_names, self.speaker_keys = {}, []
        self.playback_generation = 0
        self.playback_end = self.audio_cache = None
        self.decode_busy = self.closed = False
        self.last_snapshot = None
        root.title("Local Speech to Text")
        root.geometry("1080x820")
        root.minsize(820, 690)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Local Speech to Text", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Record or import audio, then review the timed speaker paragraphs.").pack(anchor="w", pady=(4, 12))
        options = ttk.Frame(frame)
        options.pack(fill="x")
        ttk.Label(options, text="Microphone:").pack(side="left")
        self.mic = ttk.Combobox(options, state="readonly", width=40)
        self.mic.pack(side="left", padx=6)
        self.devices = []
        try:
            self.devices = [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
            self.mic["values"] = [name for _, name in self.devices]
            if self.devices:
                default = sd.default.device[0]
                self.mic.current(next((n for n, (i, _) in enumerate(self.devices) if i == default), 0))
        except Exception as exc:
            self.local_events.put(("status", f"Microphone unavailable: {exc}. Audio import is still available."))
        ttk.Label(options, text="Model:").pack(side="left", padx=(10, 0))
        self.size = ttk.Combobox(options, values=("tiny", "base", "small", "medium", "large-v3"), state="readonly", width=9)
        self.size.set("small")
        self.size.pack(side="left", padx=6)
        self.offline = tk.BooleanVar(value=False)
        self.offline_check = ttk.Checkbutton(frame, text="Offline only (model must already be downloaded)", variable=self.offline)
        self.offline_check.pack(anchor="w", pady=8)
        accuracy_options = ttk.Frame(frame)
        accuracy_options.pack(fill="x", pady=(0, 8))
        ttk.Label(accuracy_options, text="Spoken language:").pack(side="left")
        self.language = ttk.Combobox(accuracy_options, values=tuple(LANGUAGES), state="readonly", width=14)
        self.language.set("Auto detect")
        self.language.pack(side="left", padx=6)
        ttk.Label(accuracy_options, text="Names / specialist terms:").pack(side="left", padx=(10, 6))
        self.hotwords = ttk.Entry(accuracy_options)
        self.hotwords.pack(side="left", fill="x", expand=True)
        ttk.Label(frame, text="Choose the spoken language for short clips. Add relevant names or terms, separated by commas. Larger models are slower.",
                  wraplength=990).pack(anchor="w", pady=(0, 8))
        speaker_options = ttk.Frame(frame)
        speaker_options.pack(fill="x", pady=(0, 8))
        self.separate = tk.BooleanVar(value=True)
        self.separate_check = ttk.Checkbutton(speaker_options, text="Separate speakers (estimated)", variable=self.separate)
        self.separate_check.pack(side="left")
        ttk.Label(speaker_options, text="Number of people:").pack(side="left", padx=(14, 6))
        self.speaker_count = ttk.Combobox(speaker_options, values=("Auto", "1", "2", "3", "4", "5", "6"), state="readonly", width=5)
        self.speaker_count.set("2")
        self.speaker_count.pack(side="left")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(4, 10))
        self.record = ttk.Button(buttons, text="Start recording", command=self.start)
        self.record.pack(side="left")
        self.stop = ttk.Button(buttons, text="Stop & transcribe", command=self.finish, state="disabled")
        self.stop.pack(side="left", padx=6)
        self.open = ttk.Button(buttons, text="Open audio…", command=self.open_file)
        self.open.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="Cancel processing", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=6)
        self.activity = ttk.Frame(frame, padding=8)
        self.activity_text = tk.StringVar()
        ttk.Label(self.activity, textvariable=self.activity_text, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.progress = ttk.Progressbar(self.activity, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 0))
        review = ttk.Frame(frame)
        review.pack(fill="x", pady=(0, 8))
        ttk.Label(review, text="Speaker:").pack(side="left")
        self.speaker_choice = ttk.Combobox(review, state="readonly", width=28)
        self.speaker_choice.pack(side="left", padx=6)
        ttk.Button(review, text="Rename…", command=self.rename_speaker).pack(side="left")
        self.play_button = ttk.Button(review, text="Play paragraph", command=self.play_selected)
        self.play_button.pack(side="left", padx=6)
        self.play_recording_button = ttk.Button(review, text="Play whole recording", command=self.play_recording)
        self.play_recording_button.pack(side="left", padx=6)
        self.play_from_button = ttk.Button(review, text="Play from here", command=self.play_from_selected)
        self.play_from_button.pack(side="left", padx=6)
        ttk.Button(review, text="Stop playback", command=self.stop_playback).pack(side="left")
        ttk.Label(frame, text="Click a paragraph, then Play paragraph (or double-click its timestamp). Amber headers need review.", wraplength=780).pack(anchor="w", pady=(0, 6))
        self.editor = ttk.Frame(frame)
        self.editor.pack(fill="both", expand=True)
        self.text = tk.Text(self.editor, wrap="word", font=("Segoe UI", 12), undo=True, padx=12, pady=12)
        scrollbar = ttk.Scrollbar(self.editor, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("heading", foreground="#185788", font=("Segoe UI", 11, "bold"))
        self.text.tag_configure("review", foreground="#996000")
        self.text.tag_configure("playing", background="#dfedf9")
        self.text.bind("<ButtonRelease-1>", self.select_paragraph)
        self.text.bind("<Double-Button-1>", self.double_click)
        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="Copy text", command=self.copy).pack(side="left")
        ttk.Button(bottom, text="Save text…", command=self.save).pack(side="left", padx=6)
        ttk.Button(bottom, text="Export Word…", command=self.save_word).pack(side="left")
        ttk.Button(bottom, text="New transcript", command=self.new_transcript).pack(side="left", padx=6)
        self.status = tk.StringVar(value="Ready. All speech processing stays on this computer.")
        ttk.Label(frame, textvariable=self.status, wraplength=990).pack(anchor="w", pady=(10, 0))
        self.autosave_status = tk.StringVar(value="Autosave every 3 seconds. Microphone recordings are kept locally for playback.")
        ttk.Label(frame, textvariable=self.autosave_status, wraplength=990).pack(anchor="w", pady=(4, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.controls()
        root.after(100, self.poll)
        root.after(3000, self.autosave_tick)
        if recover:
            root.after(200, self.recover)

    def controls(self):
        recording = self.stream is not None
        locked = self.busy or recording
        self.record.configure(state="normal" if not locked and self.devices else "disabled")
        self.stop.configure(state="normal" if recording or self.chunks else "disabled")
        self.open.configure(state="disabled" if locked else "normal")
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        for control in (self.mic, self.size, self.speaker_count, self.language):
            control.configure(state="disabled" if locked else "readonly")
        self.hotwords.configure(state="disabled" if locked else "normal")
        for control in (self.separate_check, self.offline_check):
            control.configure(state="disabled" if locked else "normal")
        self.play_button.configure(state="disabled" if recording else "normal")
        self.play_recording_button.configure(state="disabled" if recording else "normal")
        self.play_from_button.configure(state="disabled" if recording else "normal")

    def capture(self, data, frames, timing, status):
        if status:
            self.recording_warning = True
        if self.sample_count < self.rate * 1800:
            self.chunks.append(data.copy())
            self.sample_count += frames

    def start(self):
        if self.chunks and not messagebox.askyesno("Unsaved recording", "Discard the previous recording that could not be saved?"):
            return
        self.stop_playback()
        try:
            device = self.devices[self.mic.current()][0]
            self.rate = int(sd.query_devices(device)["default_samplerate"])
            self.chunks, self.sample_count, self.recording_warning = [], 0, False
            self.stream = sd.InputStream(device=device, samplerate=self.rate, channels=1, dtype="int16", callback=self.capture)
            self.stream.start()
            self.started = time.monotonic()
        except Exception as exc:
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            messagebox.showerror("Microphone error", f"{exc}\n\nCheck Windows microphone permissions and the selected input.")
        self.controls()

    def finish(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if not self.chunks:
            self.status.set("No audio recorded.")
            self.controls()
            return
        try:
            folder = BASE / "recordings"
            folder.mkdir(exist_ok=True)
            path = folder / f"recording-{uuid.uuid4().hex}.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self.rate)
                wav.writeframes(np.concatenate(self.chunks).tobytes())
            self.chunks = []
            if self.recording_warning:
                messagebox.showwarning("Recording warning", "The microphone reported dropped audio. Some words may be missing.")
            self.transcribe(path)
        except Exception as exc:
            messagebox.showerror("Recording error", f"{exc}\nThe recording remains in memory; use Stop & transcribe to retry.")
        self.controls()

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.mp4"), ("All files", "*.*")])
        if path:
            self.transcribe(Path(path))

    def transcribe(self, path):
        if self.busy:
            return
        self.stop_playback()
        self.pending_source = str(Path(path).resolve())
        self.session_id = uuid.uuid4().hex
        self.partial_turns = []
        self.busy = True
        self.processing_started = time.monotonic()
        self.set_stage("Loading speech model")
        self.activity.pack(fill="x", pady=(0, 8), before=self.editor)
        self.controls()
        self.status.set("Loading model. First use may download the selected model.")
        count = self.speaker_count.get()
        self.events = self.context.Queue()
        self.worker = self.context.Process(target=transcription_worker, args=(
            self.events, self.pending_source, self.size.get(), str(BASE / "models"),
            self.offline.get(), self.separate.get(), None if count == "Auto" else int(count),
            LANGUAGES[self.language.get()], self.hotwords.get().strip()), daemon=True)
        try:
            self.worker.start()
            self.autosave()
        except Exception as exc:
            self.finish_processing()
            messagebox.showerror("Cannot start transcription", str(exc))

    def set_stage(self, name):
        self.processing_stage = name
        self.estimated_finish = self.transcription_fraction = None
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start()
        self.activity_text.set(name + "...")

    def cancel(self):
        if not self.busy:
            return
        # Drain completed segments before stopping; never wait for a new inference segment.
        if self.events is not None:
            try:
                while True:
                    kind, value = self.events.get_nowait()
                    if kind == "partial":
                        self.partial_turns.append(value)
            except (queue.Empty, EOFError, OSError):
                pass
        if self.worker is not None and self.worker.is_alive():
            self.worker.terminate()
            self.worker.join(timeout=1)
        self.keep_partial()
        self.finish_processing()
        self.status.set("Cancelled. Completed segments were kept; source audio is available to retry.")
        self.autosave()

    def keep_partial(self):
        if self.partial_turns:
            self.append_turns(self.partial_turns, self.pending_source, self.session_id, partial=True)
            self.partial_turns = []

    def finish_processing(self):
        self.busy = False
        if self.worker is not None:
            if self.worker.pid is not None:
                self.worker.join(timeout=0.1)
                if self.worker.is_alive():
                    self.worker.terminate()
                    self.worker.join(timeout=1)
            self.worker = None
        if self.events is not None:
            self.events.close()
            self.events = None
        if hasattr(self, "dead_since"):
            del self.dead_since
        self.progress.stop()
        self.activity.pack_forget()
        self.controls()

    def append_turns(self, turns, source, session_id, partial=False):
        if not turns:
            return
        if self.text.get("1.0", "end-1c").strip():
            self.text.insert("end", "\n\n")
        self.text.insert("end", f"Recording: {Path(source).name}" + (" (partial transcript)" if partial else "") + "\n\n")
        for item in turns:
            speaker_key = f"{session_id}:{item['speaker']}"
            name = self.speaker_names.setdefault(speaker_key, item["speaker"])
            uid = "turn_" + uuid.uuid4().hex
            begin = self.text.index("end-1c")
            self.text.insert("end", f"[{timestamp(item['start'])}] ")
            name_begin = self.text.index("end-1c")
            self.text.insert("end", name)
            name_finish = self.text.index("end-1c")
            self.text.insert("end", ":" + (" (review speaker)" if item.get("review") else "") + "\n")
            heading_finish = self.text.index("end-1c")
            self.text.insert("end", item["text"])
            finish = self.text.index("end-1c")
            turn = dict(id=uid, source=source, start=float(item["start"]), end=float(item["end"]), speaker=speaker_key,
                        review=item.get("review", False))
            self.turns.append(turn)
            self.text.tag_add(uid, begin, finish)
            self.text.tag_add(uid + "_name", name_begin, name_finish)
            self.text.tag_add("heading", begin, heading_finish)
            if turn["review"]:
                self.text.tag_add("review", begin, heading_finish)
            self.text.insert("end", "\n\n")
        self.refresh_speakers()
        self.text.see("end")

    def refresh_speakers(self):
        self.speaker_keys = list(self.speaker_names)
        sessions = list(dict.fromkeys(key.split(":")[0] for key in self.speaker_keys))
        self.speaker_choice["values"] = [f"{self.speaker_names[key]} (recording {sessions.index(key.split(':')[0]) + 1})" for key in self.speaker_keys]
        if self.speaker_keys:
            self.speaker_choice.current(0)

    def current_turn(self, index=None):
        index = self.text.index(index or "insert")
        for turn in self.turns:
            ranges = self.text.tag_ranges(turn["id"])
            if ranges and self.text.compare(index, ">=", ranges[0]) and self.text.compare(index, "<=", ranges[-1]):
                return turn
        return None

    def select_paragraph(self, event):
        turn = self.current_turn(f"@{event.x},{event.y}")
        if turn and turn["speaker"] in self.speaker_keys:
            self.speaker_choice.current(self.speaker_keys.index(turn["speaker"]))

    def double_click(self, event):
        turn = self.current_turn(f"@{event.x},{event.y}")
        if turn:
            ranges = self.text.tag_ranges(turn["id"])
            index = self.text.index(f"@{event.x},{event.y}")
            if self.text.compare(index, "<", f"{ranges[0]} + 10 chars"):
                self.play_turn(turn)
                return "break"

    def rename_speaker(self, new_name=None):
        selected = self.speaker_choice.current()
        if selected < 0 or selected >= len(self.speaker_keys):
            return
        key = self.speaker_keys[selected]
        if new_name is None:
            new_name = simpledialog.askstring("Rename speaker", "Name for this speaker throughout this recording:", initialvalue=self.speaker_names[key], parent=self.root)
        if new_name is None or not new_name.strip():
            return
        new_name = " ".join(new_name.split())[:80]
        self.text.edit_separator()
        for turn in reversed(self.turns):
            if turn["speaker"] != key:
                continue
            tag = turn["id"] + "_name"
            ranges = self.text.tag_ranges(tag)
            if not ranges:
                continue
            begin = self.text.index(ranges[0])
            self.text.delete(ranges[0], ranges[-1])
            self.text.insert(begin, new_name)
            self.text.tag_add(tag, begin, f"{begin} + {len(new_name)} chars")
        self.text.edit_separator()
        self.speaker_names[key] = new_name
        self.refresh_speakers()
        self.speaker_choice.current(selected)
        self.autosave()

    def play_selected(self):
        turn = self.current_turn()
        if turn is None:
            self.status.set("Click inside a timed paragraph first, then choose Play paragraph.")
            return
        self.play_turn(turn)

    def play_recording(self):
        turn = self.current_turn() or (self.turns[-1] if self.turns else None)
        if turn is None:
            self.status.set("Record or open audio and transcribe it first.")
            return
        self.play_turn(dict(turn, start=0., end=None))

    def play_from_selected(self):
        turn = self.current_turn()
        if turn is None:
            self.status.set("Click inside a timed paragraph first, then choose Play from here.")
            return
        self.play_turn(dict(turn, end=None))

    def play_turn(self, turn):
        if self.stream is not None:
            return
        if not Path(turn["source"]).is_file():
            messagebox.showerror("Audio unavailable", f"The source recording has moved or is unavailable:\n{turn['source']}")
            return
        if self.decode_busy:
            self.status.set("Loading audio for playback; please wait.")
            return
        self.stop_playback()
        token = self.playback_generation
        self.decode_busy = True
        self.status.set("Loading paragraph audio…")
        cached = self.audio_cache

        def decode():
            try:
                from faster_whisper.audio import decode_audio
                audio = cached[1] if cached and cached[0] == turn["source"] else decode_audio(turn["source"])
                self.local_events.put(("audio_ready", (token, turn, audio)))
            except Exception as exc:
                self.local_events.put(("audio_error", (token, str(exc))))

        threading.Thread(target=decode, daemon=True).start()

    def stop_playback(self):
        self.playback_generation += 1
        sd.stop()
        self.playback_end = None
        self.text.tag_remove("playing", "1.0", "end")

    def handle_local_event(self, kind, value):
        if kind == "status":
            self.status.set(value)
        elif kind == "audio_error":
            self.decode_busy = False
            if value[0] == self.playback_generation:
                messagebox.showerror("Playback error", value[1])
        elif kind == "audio_ready":
            self.decode_busy = False
            token, turn, audio = value
            if token != self.playback_generation:
                return
            self.audio_cache = (turn["source"], audio)
            start = max(0, int(turn["start"] * 16000))
            end = len(audio) if turn["end"] is None else int(turn["end"] * 16000)
            clip = audio[start:end]
            if not len(clip):
                self.status.set("No playable audio at this position.")
                return
            try:
                sd.play(clip, 16000, blocking=False)
                self.playback_end = time.monotonic() + len(clip) / 16000
                for item in self.turns:
                    if item["source"] == turn["source"] and item["end"] > start / 16000 and item["start"] < end / 16000:
                        ranges = self.text.tag_ranges(item["id"])
                        if ranges:
                            self.text.tag_add("playing", ranges[0], ranges[-1])
                self.status.set(f"Playing {timestamp(start / 16000)} to {timestamp(end / 16000)} | Stop playback to stop.")
            except Exception as exc:
                messagebox.showerror("Playback error", str(exc))

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                self.handle_local_event(*self.local_events.get_nowait())
        except queue.Empty:
            pass
        try:
            for _ in range(100):
                if self.events is None:
                    break
                kind, value = self.events.get_nowait()
                if kind == "stage":
                    self.set_stage(value)
                elif kind == "partial":
                    self.partial_turns.append(value)
                elif kind == "estimate":
                    self.transcription_fraction, self.estimated_finish = value
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=100, value=self.transcription_fraction * 100)
                elif kind == "result":
                    turns, language, warning = value
                    self.append_turns(turns, self.pending_source, self.session_id)
                    self.partial_turns = []
                    self.status.set(warning or (f"Done. Language: {language}. Speaker labels are estimates; review against the audio." if turns else "No speech detected."))
                    self.autosave()
                elif kind == "error":
                    self.keep_partial()
                    self.status.set("Transcription failed. Completed segments were retained.")
                    messagebox.showerror("Transcription error", value + "\n\nFor dependency errors, rerun Setup.cmd. A model's first download needs internet.")
                elif kind == "done":
                    self.finish_processing()
                    self.autosave()
        except (queue.Empty, EOFError, OSError):
            pass
        if self.busy:
            elapsed = int(time.monotonic() - self.processing_started)
            if self.estimated_finish is not None:
                remaining = max(0, math.ceil(self.estimated_finish - time.monotonic()))
                countdown = f"About {timestamp(remaining)} remaining" if remaining else "Updating time estimate…"
                detail = f"{int(self.transcription_fraction * 100)}% of this stage | {countdown}"
            else:
                detail = "Estimating time remaining…" if self.processing_stage != "Loading speech model" else "Download / loading time varies"
            self.activity_text.set(f"{self.processing_stage}…  {timestamp(elapsed)} elapsed\n{detail}")
            if self.worker is not None and self.worker.exitcode is not None:
                if not hasattr(self, "dead_since"):
                    self.dead_since = time.monotonic()
                elif time.monotonic() - self.dead_since > 1:
                    self.keep_partial()
                    self.finish_processing()
                    self.autosave()
                    self.status.set("Processing stopped unexpectedly. Completed segments were retained.")
            elif hasattr(self, "dead_since"):
                del self.dead_since
        if self.stream is not None:
            elapsed = int(time.monotonic() - self.started)
            self.status.set(f"Recording… {timestamp(elapsed)} (30-minute limit)")
            if elapsed >= 1800:
                self.finish()
        if self.playback_end is not None and time.monotonic() >= self.playback_end:
            self.stop_playback()
            if not self.busy:
                self.status.set("Playback finished.")
        self.root.after(100, self.poll)

    def snapshot(self):
        turns = []
        for item in self.turns:
            ranges = self.text.tag_ranges(item["id"])
            name = self.text.tag_ranges(item["id"] + "_name")
            if not ranges or not name:
                continue
            # Tk 8.6's count() counts UTF-16 units, while '+ N chars' counts
            # Unicode characters. Store Python character counts for round trips.
            offsets = [len(self.text.get("1.0", index))
                       for index in (ranges[0], ranges[-1], name[0], name[-1])]
            turns.append(dict(item, **dict(zip(("begin", "finish", "name_begin", "name_finish"), offsets))))
        return dict(version=1, text=self.text.get("1.0", "end-1c"), turns=turns, speakers=dict(self.speaker_names),
                    pending=dict(source=self.pending_source, session=self.session_id, turns=list(self.partial_turns)) if self.busy else None)

    def autosave(self):
        if self.recovery_pending:
            return True
        try:
            data = self.snapshot()
            if data != self.last_snapshot:
                save_session(self.recovery_path, data)
                self.last_snapshot = data
            self.autosave_status.set("Autosaved locally. Recordings are retained in speech-to-text/recordings for playback.")
            return True
        except (OSError, ValueError, TypeError) as exc:
            self.autosave_status.set(f"Autosave failed: {exc}. Please save or export your text.")
            return False

    def autosave_tick(self):
        if not self.closed:
            self.autosave()
            self.root.after(3000, self.autosave_tick)

    def recover(self):
        try:
            if not self.recovery_path.exists():
                return
            data = load_session(self.recovery_path)
            if not data["text"].strip() and not data.get("pending"):
                return
            if not messagebox.askyesno("Restore transcript", "Restore the last autosaved transcript, edits, speaker names and audio links?", parent=self.root):
                save_session(self.data_dir / f"previous-{uuid.uuid4().hex}.json", data)
                return
            self.restore(data)
            self.status.set("Restored the last autosaved transcript. Imported audio must still be at its original location.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showwarning("Recovery unavailable", f"Could not restore the recovery file.\n{exc}")
            try:
                self.recovery_path.replace(self.data_dir / f"unreadable-{uuid.uuid4().hex}.json")
            except OSError:
                pass
        finally:
            self.recovery_pending = False

    def restore(self, data):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", data["text"])
        self.turns = data.get("turns", [])
        self.speaker_names = data.get("speakers", {})
        for item in self.turns:
            for tag, begin, finish in ((item["id"], item["begin"], item["finish"]),
                                       (item["id"] + "_name", item["name_begin"], item["name_finish"])):
                self.text.tag_add(tag, f"1.0 + {begin} chars", f"1.0 + {finish} chars")
            start = f"1.0 + {item['begin']} chars"
            self.text.tag_add("heading", start, f"{start} lineend")
            if item.get("review"):
                self.text.tag_add("review", start, f"{start} lineend")
        pending = data.get("pending")
        if pending and pending.get("turns"):
            self.append_turns(pending["turns"], pending["source"], pending["session"], partial=True)
        self.refresh_speakers()
        self.text.edit_reset()

    def copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.status.set("Transcript copied with speaker names and timestamps.")

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text file", "*.txt")])
        if path:
            try:
                Path(path).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
                self.status.set(f"Saved to {path}")
            except OSError as exc:
                messagebox.showerror("Save error", str(exc))

    def save_word(self):
        path = filedialog.asksaveasfilename(defaultextension=".docx", filetypes=[("Word document", "*.docx")])
        if path:
            try:
                export_word(path, self.text.get("1.0", "end-1c"))
                self.status.set(f"Word document saved to {path}")
            except Exception as exc:
                messagebox.showerror("Word export error", f"{exc}\nRerun Setup.cmd if python-docx is missing.")

    def new_transcript(self):
        if self.busy or self.stream is not None:
            self.status.set("Stop recording or cancel processing before starting a new transcript.")
            return
        if self.text.get("1.0", "end-1c").strip():
            if not messagebox.askyesno("New transcript", "Archive this workspace locally and start an empty transcript?"):
                return
            try:
                save_session(self.data_dir / f"archive-{uuid.uuid4().hex}.json", self.snapshot())
            except OSError as exc:
                messagebox.showerror("Cannot archive transcript", str(exc))
                return
        self.stop_playback()
        self.text.delete("1.0", "end")
        self.text.edit_reset()
        self.turns, self.speaker_names = [], {}
        self.refresh_speakers()
        self.speaker_choice.set("")
        self.autosave()

    def close(self):
        if self.busy and not messagebox.askyesno("Cancel and close", "Cancel processing and close? Completed segments will be saved for recovery."):
            return
        if (self.stream is not None or self.chunks) and not messagebox.askyesno("Recording in progress", "Close and discard the active recording? Stop & transcribe first to keep it."):
            return
        if self.busy:
            self.cancel()
        if not self.autosave() and not messagebox.askyesno("Autosave failed", "Close without saving? Current edits may be lost."):
            return
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
        self.stop_playback()
        self.closed = True
        self.root.destroy()


if __name__ == "__main__":
    mp.freeze_support()
    SpeechApp(tk.Tk()).root.mainloop()
