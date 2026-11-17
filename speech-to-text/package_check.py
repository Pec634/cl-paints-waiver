"""Exercise the frozen GUI, Word export and actual spawned speech worker."""
import json
import multiprocessing as mp
from pathlib import Path
import queue
import time
import traceback


def main(audio, models, report):
    report = Path(report)
    worker = root = None
    result = {"ok": False}
    try:
        from app import SpeechApp, tk
        from documents import export_word
        from engine import transcription_worker

        root = tk.Tk()
        root.withdraw()
        ui = SpeechApp(root, data_dir=report.parent / "check-data", recover=False)
        root.update()
        context = mp.get_context("spawn")
        events = context.Queue()
        worker = context.Process(target=transcription_worker,
            args=(events, audio, "base", models, True, True, 2, "en", None))
        worker.start()
        deadline = time.monotonic() + 300
        turns = None
        while time.monotonic() < deadline:
            root.update()
            try:
                kind, value = events.get(timeout=0.1)
            except queue.Empty:
                if worker.exitcode is not None:
                    raise RuntimeError(f"Worker exited without completion: {worker.exitcode}")
                continue
            if kind == "error":
                raise RuntimeError(value)
            if kind == "diagnostic":
                result["diagnostic"] = value
            if kind == "result":
                turns, language, warning = value
                if warning:
                    raise RuntimeError(warning)
            if kind == "done":
                break
        else:
            raise TimeoutError("Speech worker exceeded five minutes")
        assert turns, "No transcript returned"
        ui.append_turns(turns, audio, "package-check")
        text = ui.text.get("1.0", "end-1c")
        assert "appointment" in text.lower(), text
        assert len({turn["speaker"] for turn in turns}) == 2, turns
        assert ui.autosave(), "Autosave failed"
        export_word(report.with_suffix(".docx"), text)
        result = dict(ok=True, text=text, language=language, speakers=2)
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        if worker is not None and worker.is_alive():
            worker.join(5)
            if worker.is_alive():
                worker.terminate()
                worker.join()
        if root is not None:
            root.destroy()
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
