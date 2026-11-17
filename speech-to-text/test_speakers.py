import unittest
from types import SimpleNamespace

from speakers import format_turns


def words(*texts):
    return [SimpleNamespace(word=text) for text in texts]


class SpeakerFormattingTests(unittest.TestCase):
    def test_labels_follow_first_appearance_and_preserve_returning_speaker(self):
        result = format_turns(
            [words(" Hello", " there."), words(" Good", " morning."), words(" Welcome."), words(" Thanks.")],
            [8, 3, 3, 8],
        )
        self.assertEqual(result, "Person 1: Hello there.\n\nPerson 2: Good morning. Welcome.\n\nPerson 1: Thanks.")

    def test_single_voice_is_one_paragraph_without_losing_words(self):
        self.assertEqual(format_turns([words(" One."), words(" Two.")], [0, 0]), "Person 1: One. Two.")

    def test_no_speech_produces_no_labels(self):
        self.assertEqual(format_turns([], []), "")


if __name__ == "__main__":
    unittest.main()
