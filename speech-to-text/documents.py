"""Local transcript recovery and document export."""
import json
import os
import re
from pathlib import Path


def timestamp(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def save_session(path, data):
    """Replace atomically so an interrupted write leaves the last complete save."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def load_session(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("text"), str):
        raise ValueError("Unrecognised recovery file")
    for turn in data.get("turns", []):
        for key in ("begin", "finish", "name_begin", "name_finish"):
            offset = turn[key]
            if not isinstance(offset, int) or not 0 <= offset <= len(data["text"]):
                raise ValueError("Invalid paragraph position in recovery file")
        if turn["begin"] > turn["finish"] or turn["name_begin"] > turn["name_finish"]:
            raise ValueError("Invalid paragraph range in recovery file")
        if not isinstance(turn["source"], str) or not isinstance(turn["speaker"], str):
            raise ValueError("Invalid paragraph metadata")
        if not 0 <= float(turn["start"]) <= float(turn["end"]):
            raise ValueError("Invalid audio timestamps")
    return data


def export_word(path, text):
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.add_heading("Speech transcript", 0)
    document.add_paragraph("Speaker labels and timestamps are estimates. Review against the recording.", style="Subtitle")
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        paragraph = document.add_paragraph()
        header, separator, body = block.partition("\n")
        if separator and re.match(r"^\[\d+:\d{2}:\d{2}\] .+:", header):
            paragraph.add_run(header).bold = True
            paragraph.add_run("\n" + body)
        else:
            paragraph.add_run(block)
        paragraph.paragraph_format.space_after = Pt(12)
    document.save(path)
