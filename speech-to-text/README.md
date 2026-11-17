# Local Speech to Text

A standalone desktop app for Windows, separate from the waiver application.

## Portable Windows app (no Python installation)

Share `dist/LocalSpeechToText-Windows.zip`. The recipient extracts the entire
ZIP into a writable folder and double-clicks `LocalSpeechToText.exe` inside
`LocalSpeechToText`. Keep `_internal` beside the executable. Internet is needed
for the first download of each speech model; downloaded models work offline.
The ZIP excludes your recordings, transcripts and model cache.

To rebuild on Windows after changing the source, run `Setup.cmd`, then
`Build.cmd`. Only the build computer needs Python. The portable app stores
`models`, `recordings` and `data` beside its executable, so avoid Program Files
or other read-only folders. See `PORTABLE-README.txt` for recipient instructions.

## Start

1. Install **Python 3.11 or 3.12** from https://www.python.org/downloads/windows/ with Tcl/Tk and the Python launcher included.
2. Double-click **Setup.cmd** once. Internet is needed to install dependencies.
3. Double-click **Start.cmd**.
4. Choose your microphone, click **Start recording**, speak, then click **Stop & transcribe**. Text appears after processing finishes.

You can also open an existing audio file. Edit the transcript directly, copy it, or save it as UTF-8 text. Successive transcriptions append to the current text. This app does not type into other programs or provide live captions.

## Speaker paragraphs

Enable **Separate speakers (estimated)** and select the actual **Number of people** before recording or opening an audio file. The app groups voices locally and formats turns as `Person 1: ...`, `Person 2: ...`, with a blank line between turns. Labels follow the order voices first appear and restart for each recording. They do not identify real people. Copying or saving preserves the paragraphs.

Speaker labels are estimates: short replies, similar voices, background noise, and overlapping speech can be assigned incorrectly. Choosing more people than actually speak can split one voice into several labels. Review and edit the transcript and labels before relying on them. Voice analysis adds a processing stage with its own progress estimate; its model is bundled with the installed package. Existing transcripts must be retranscribed to get labels.

Choose **Auto** to estimate the number of voices, or the actual number for more predictable grouping. Voice analysis now uses overlapping windows, per-window volume normalisation, word-level timing and turn smoothing. Short or ambiguous turns are marked **review speaker** in amber. These flags indicate uncertainty, not a guarantee that other labels are correct.

## Review and export

- **Timestamps:** each paragraph starts with its position in its recording, for example `[00:01:23] Person 1:`. Time resets for each recording.
- **Rename:** click a paragraph or choose a speaker, then **Rename…**. This updates that speaker's headers throughout that recording, leaving spoken text and other recordings alone.
- **Playback:** click inside a paragraph and choose **Play paragraph**, or double-click its timestamp. **Stop playback** stops audio. Imported audio must remain at the original path. If you edit the words or displayed timestamps, playback still uses the paragraph's original audio times.
- **Autosave:** edits, speaker names, paragraph/audio links and completed in-progress segments are saved every 3 seconds. On reopening, choose to restore the last workspace. Autosave does not recover an active microphone recording that has not been stopped.
- **Cancel processing:** stops the background process without closing the app. Completed speech segments are retained as a partial transcript; speaker separation may not have completed. Original audio remains available to transcribe again.
- **Export Word…:** saves the currently edited text as `.docx`, with speaker headings and timestamps. **Save text…** and **Copy text** also preserve the paragraph layout.
- **New transcript:** archives the current workspace locally and starts an empty editor. The app appends new recordings to the current workspace unless you choose this.

You can keep editing existing text while another recording is transcribed. Speaker numbering is separate for each recording; the dropdown shows the recording number. Time remaining is an estimate for the current processing stage and resets when speaker analysis starts.

## Local processing

Transcription uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your CPU; no API key or paid service is required. Each model downloads on its first use into `models/`. After downloading, enable **Offline only** to prevent model downloads. Speech recognition processes audio locally and does not upload recordings.

The default model is `small`. Choose `medium` or `large-v3` for higher accuracy at the cost of more memory, a larger download and substantially longer CPU processing; `tiny` and `base` remain available for speed. Downloads and transcription can take several minutes. Accuracy varies, so review important text.

Select the **Spoken language** when you know it, particularly for short clips that are difficult to identify automatically. Leave **Auto detect** selected for other languages. Add relevant spellings to **Names / specialist terms**, separated by commas, to guide recognition of names and specialist vocabulary. These hints do not guarantee a spelling and unrelated hints can hurt accuracy. Speech detection retains short replies and pads speech boundaries; recognition resets text context between decoding windows to limit repeated errors. Changes apply to the next transcription; open the original audio again to retry an existing transcript.

Microphone recordings are limited to 30 minutes and use memory while recording. On stopping, a WAV is retained in `recordings/` for playback and retry, including after cancellation or transcription failure. Imported audio files are never modified or copied. Workspace autosaves are in `data/recovery.json`; archived workspaces are in `data/archive-*.json`. Remove unneeded audio and saved workspaces manually when the app is closed; deleting audio makes its playback links unavailable. These folders are excluded from Git.

If this folder is inside OneDrive, OneDrive may sync its recordings and autosaves. Move the standalone `speech-to-text` folder outside OneDrive if you want to avoid that storage sync (rerun Setup.cmd to recreate its virtual environment after moving).

## Troubleshooting

- No microphone: connect a microphone before starting the app and allow desktop apps to use it in Windows Settings → Privacy & security → Microphone.
- No text: check the selected microphone and Windows input level.
- Offline loading fails: disable Offline only and transcribe once with that model while connected to the internet.
- Installation errors: use 64-bit Python 3.11 or 3.12 and rerun Setup.cmd. This app has its own virtual environment and requirements.

Other operating systems: create a virtual environment, install `requirements.txt`, run `python -m pip install --no-deps resemblyzer==0.1.4`, then run `python app.py`. Linux may additionally require Tk and PortAudio packages. Setup installs Resemblyzer separately because its legacy `webrtcvad` dependency needs a compiler on Windows; `webrtcvad-wheels` supplies the same module prebuilt. `pip check` may report the legacy dependency as missing despite the replacement being installed.

## Verification

Run `.venv\Scripts\python.exe -m unittest test_speakers.py test_workflow.py -v` from this folder. `smoke_test.py` additionally exercises the real offline model and two Windows synthetic voices (Hazel and Zira) without using your microphone or uploading audio. It creates and removes its own temporary audio files.
