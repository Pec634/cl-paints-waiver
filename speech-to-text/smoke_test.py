r"""Optional Windows integration check using two synthetic voices, no microphone.

Run: .venv\Scripts\python.exe smoke_test.py
Requires the already downloaded base model and installed Windows speech voices.
"""
import multiprocessing as mp
from pathlib import Path
import subprocess
import tempfile
import time
import wave

from app import SpeechApp, tk
from documents import export_word, load_session


def main():
    with tempfile.TemporaryDirectory() as folder:
        directory = Path(folder)
        lines = [
            ("Microsoft Hazel Desktop", "Good morning. I would like to book an appointment for next Tuesday. Can you tell me what times are available?"),
            ("Microsoft Zira Desktop", "Certainly. We have an appointment at ten in the morning, or two in the afternoon. Which time would you prefer?"),
            ("Microsoft Hazel Desktop", "Two in the afternoon would be perfect. Thank you very much for your help."),
        ]
        script = "Add-Type -AssemblyName System.Speech\n"
        for index, (voice, text) in enumerate(lines):
            output = str(directory / f"voice{index}.wav").replace("'", "''")
            script += ("$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                       f"$s.SelectVoice('{voice}')\n$s.SetOutputToWaveFile('{output}')\n"
                       f"$s.Speak('{text}')\n$s.Dispose()\n")
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        path = directory / "conversation.wav"
        with wave.open(str(path), "wb") as output:
            for index in range(len(lines)):
                with wave.open(str(directory / f"voice{index}.wav"), "rb") as source:
                    if index == 0:
                        output.setparams(source.getparams())
                    output.writeframes(source.readframes(source.getnframes()))
                    output.writeframes(b"\x00" * int(source.getframerate() * source.getnchannels() * source.getsampwidth() * .8))
        root = tk.Tk()
        root.withdraw()
        ui = SpeechApp(root, data_dir=directory / "recovery", recover=False)
        try:
            ui.size.set("base")  # This offline check uses the already downloaded base model.
            ui.offline.set(True)
            ui.transcribe(path)
            deadline = time.monotonic() + 180
            while ui.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.03)
            assert not ui.busy, "Transcription timed out"
            text = ui.text.get("1.0", "end-1c")
            assert "appointment" in text.lower(), ui.status.get()
            assert "[00:" in text
            assert len({turn["speaker"] for turn in ui.turns}) == 2
            assert ui.turns[0]["speaker"] == ui.turns[-1]["speaker"], "Returning synthetic voice was labelled inconsistently"
            ui.speaker_choice.current(0)
            ui.rename_speaker("First voice")
            assert "] First voice:" in ui.text.get("1.0", "end-1c")
            assert ui.autosave()
            recovered = load_session(ui.recovery_path)
            ui.restore(recovered)
            assert ui.turns[0]["source"] == str(path.resolve())
            export_word(directory / "transcript.docx", ui.text.get("1.0", "end-1c"))
            assert (directory / "transcript.docx").is_file()
            print(text)
            print("PASS: two-voice transcription, returning voice, timestamps, renaming, recovery and Word export")
        finally:
            if ui.busy:
                ui.cancel()
            ui.closed = True
            ui.stop_playback()
            root.destroy()


if __name__ == "__main__":
    mp.freeze_support()
    main()
