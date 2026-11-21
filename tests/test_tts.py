"""sotto-tts (tts/): the front end, the table format and the synthesiser on the committed
tables. SPDX-License-Identifier: MIT"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "sim")]
from tts import frontend, lts, synth, table  # noqa: E402

DATA = os.path.join(ROOT, "tts", "data")


def words(text):
    return [w["text"] for ph in frontend.text_to_phrases(text) for w in ph["words"]]


def test_callsign_is_spoken_in_nato_phonetics():
    assert words("This is AG7EW.") == ["this", "is", "alfa", "golf", "seven", "echo", "whiskey"]
    assert words("ag7ew/p") == ["alfa", "golf", "seven", "echo", "whiskey", "stroke", "papa"]


def test_numbers():
    assert words("440.850 MHz") == ["four", "four", "zero", "point", "eight", "five", "zero",
                                    "megahertz"]
    assert words("146 and 1950") == ["one", "hundred", "forty", "six", "and", "nineteen", "fifty"]


def test_phrases_and_question():
    ph = frontend.text_to_phrases("Stand by, please. Is it on?")
    assert [p["end"] for p in ph] == [",", ".", "?"]


def test_letter_to_sound_rules():
    assert [p for p, _ in lts.word_to_phones("sheet")] == ["SH", "IY", "T"]
    assert [p for p, _ in lts.word_to_phones("batter")] == ["B", "AE", "T", "AXR"]


@pytest.mark.parametrize("name", ["robot.stt", "diphone.stt"])
def test_table_round_trip(name):
    raw = open(os.path.join(DATA, name), "rb").read()
    tab = table.read(raw)
    assert table.write(tab["kind"], tab["shape_bits"], tab["f0"], tab["dur"], tab["units"]) == raw


def test_robot_table_under_1kb():
    assert os.path.getsize(os.path.join(DATA, "robot.stt")) < 1024


@pytest.mark.parametrize("name", ["robot.stt", "diphone.stt"])
def test_synth_makes_superframes(name):
    tab = synth.load_table(os.path.join(DATA, name))
    p, rep = synth.synth_params("This is AG7EW. Is the repeater on?", tab)
    bits = synth.encode(p)
    assert bits.shape == (len(p["code"]) // 2, 48)
    assert rep["substitutions"] == 0
    assert 2.0 < rep["seconds"] < 6.0
    # the question ends higher than the statement does
    assert p["wi"][-12:].max() > p["wi"][len(p["wi"]) // 3]
