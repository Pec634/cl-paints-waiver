"""Estimate speaker turns from local voice embeddings and timed transcript words."""
import numpy as np


def format_turns(chunks, labels):
    """Number voices by first appearance and combine consecutive matching turns."""
    numbers, paragraphs = {}, []
    previous = None
    for words, label in zip(chunks, labels):
        number = numbers.setdefault(int(label), len(numbers) + 1)
        text = "".join(word.word for word in words).strip()
        if not text:
            continue
        if previous == number:
            paragraphs[-1] += " " + text
        else:
            paragraphs.append(f"Person {number}: {text}")
            previous = number
    return "\n\n".join(paragraphs)


def decode_labels(scores, word_starts, word_ends, change_penalty=0.12):
    """Prefer stable turns while allowing a brief, strongly different reply."""
    if not len(scores):
        return []
    costs = -scores[0].copy()
    back = []
    count = scores.shape[1]
    for index in range(1, len(scores)):
        penalty = 0.02 if word_starts[index] - word_ends[index - 1] > 0.65 else change_penalty
        transitions = costs[:, None] + penalty * (1 - np.eye(count))
        previous = transitions.argmin(axis=0)
        costs = transitions[previous, np.arange(count)] - scores[index]
        back.append(previous)
    labels = [int(costs.argmin())]
    for previous in reversed(back):
        labels.append(int(previous[labels[-1]]))
    return list(reversed(labels))


def make_turns(words, labels, uncertain):
    numbers, turns = {}, []
    for word, label, review in zip(words, labels, uncertain):
        name = f"Person {numbers.setdefault(int(label), len(numbers) + 1)}"
        text = word.word.strip()
        if not text:
            continue
        if (turns and turns[-1]["speaker"] == name and word.start - turns[-1]["end"] <= 2
                and word.end - turns[-1]["start"] <= 30):
            # Preserve tokenizer spacing (including punctuation in non-English text).
            turns[-1]["text"] += (" " if word.word.startswith(" ") else "") + text
            turns[-1]["end"] = float(word.end)
            turns[-1]["review"] = turns[-1]["review"] or bool(review)
        else:
            turns.append(dict(start=float(word.start), end=float(word.end), text=text, speaker=name, review=bool(review)))
    for turn in turns:
        if turn["end"] - turn["start"] < 0.7:
            turn["review"] = True
    return turns


def diarize_turns(audio, segments, speaker_count, report):
    """Use overlapping speech-only windows, word alignment and stable turn decoding.

    Similarity margins flag ambiguous text for review; they are not calibrated
    probabilities. Clustering is capped at 1200 windows to bound memory usage.
    """
    # Windows can deny reading a running frozen EXE. Numba uses that EXE
    # as its cache fingerprint; retain invalidation using its timestamp/size
    # when content hashing is unavailable. Source Python runs are unaffected.
    import sys
    if getattr(sys, "frozen", False):
        import os
        from numba.core import caching

        original_stamp = caching._SourceFileBackedLocatorMixin.get_source_stamp

        def frozen_stamp(locator):
            try:
                return original_stamp(locator)
            except PermissionError:
                stat = os.stat(sys.executable)
                return (stat.st_mtime_ns, stat.st_size)

        caching._SourceFileBackedLocatorMixin.get_source_stamp = frozen_stamp

    from resemblyzer import VoiceEncoder
    from sklearn.cluster import AgglomerativeClustering

    words = [word for segment in segments for word in (segment.words or [])]
    if not words:
        return [dict(start=s.start, end=s.end, text=s.text.strip(), speaker="Person 1", review=True)
                for s in segments if s.text.strip()]
    if speaker_count == 1:
        return make_turns(words, [0] * len(words), [False] * len(words))
    # Keep original timestamps and split at pauses so windows don't blend voices
    # separated by silence. Normalise each window without trimming the timeline.
    regions, current = [], []
    for word in words:
        if current and word.start - current[-1].end > 0.65:
            regions.append((current[0].start, current[-1].end))
            current = []
        current.append(word)
    if current:
        regions.append((current[0].start, current[-1].end))
    windows = []
    for start, end in regions:
        for center in np.arange(start, max(end, start + 0.001), 0.65):
            left = max(start, min(center - 0.8, end - 1.6))
            right = min(end, left + 1.6)
            if not windows or (left, right) != windows[-1][:2]:
                windows.append((left, right, (left + right) / 2))
    encoder = VoiceEncoder(device="cpu")
    embeddings = []
    for index, (start, end, _) in enumerate(windows):
        clip = audio[max(0, int(start * 16000)):max(0, int(end * 16000))]
        if not len(clip):
            clip = np.zeros(1600, dtype=np.float32)
        rms = float(np.sqrt(np.mean(clip ** 2)))
        if rms > 1e-6:
            clip = np.clip(clip * min(10, 0.1 / rms), -1, 1).astype(np.float32)
        embeddings.append(encoder.embed_utterance(clip))
        report(0.9 * (index + 1) / len(windows))
    embeddings = np.asarray(embeddings)
    selected = np.linspace(0, len(embeddings) - 1, min(1200, len(embeddings)), dtype=int)
    training = embeddings[selected]
    if len(training) == 1:
        return make_turns(words, [0] * len(words), [True] * len(words))
    options = dict(metric="cosine", linkage="average")
    if speaker_count is None:
        options.update(n_clusters=None, distance_threshold=0.35)
    else:
        options.update(n_clusters=min(speaker_count, len(training)))
    clusters = AgglomerativeClustering(**options).fit_predict(training)
    centroids = np.asarray([training[clusters == label].mean(axis=0) for label in sorted(set(clusters))])
    centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-8)
    report(0.95)
    centers = np.asarray([window[2] for window in windows])
    scores = []
    for word in words:
        center = (word.start + word.end) / 2
        right = min(len(centers) - 1, int(np.searchsorted(centers, center)))
        left = max(0, right - 1)
        weights = 1 / np.maximum(0.05, np.abs(centers[[left, right]] - center))
        embedding = np.average(embeddings[[left, right]], axis=0, weights=weights)
        embedding /= max(float(np.linalg.norm(embedding)), 1e-8)
        scores.append(embedding @ centroids.T)
    scores = np.asarray(scores)
    labels = decode_labels(scores, [w.start for w in words], [w.end for w in words])
    if scores.shape[1] > 1:
        sorted_scores = np.sort(scores, axis=1)
        uncertain = ((sorted_scores[:, -1] - sorted_scores[:, -2] < 0.08)
                     | (scores[np.arange(len(labels)), labels] < sorted_scores[:, -1] - 0.03))
    else:
        uncertain = np.zeros(len(words), dtype=bool)
    report(1.0)
    return make_turns(words, labels, uncertain)


def separate_speakers(audio, segments, speaker_count, report):
    """Compatibility wrapper for callers wanting plain paragraph text."""
    return "\n\n".join(f"{turn['speaker']}: {turn['text']}" for turn in diarize_turns(audio, segments, speaker_count, report))
