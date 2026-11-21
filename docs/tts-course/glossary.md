---
title: "Glossary"
---

# Glossary

[Course home](README.md)

Terms used in this course and in the sotto-tts code, in plain words. Names in `code font` are how a term appears in the code. The chapter where each idea is explained is in brackets. Many sound and signal words (harmonic, spectrogram, codebook) are explained in more depth in the [sotto course glossary](../course/glossary.md).

**Saying the words.** Where a word is hard to say, a sound-it-out spelling follows it, like **diphone** (say *DY-fone*). The part in CAPITALS is the one you stress. "Said as letters" means you spell it out.

### A
**Allophone** (say *AL-uh-fohn*): one of the different ways the same phone is said in different places. The L in "lamp" (clear) and the L in "golf" (dark) are allophones of L. [4]

**ARPAbet** (say *AR-puh-bet*): a way of writing English speech sounds with capital letters, such as `AA` for the vowel in "father" and `SH` for "sh". sotto-tts uses 41 of them plus `PAU`. [2]

### C
**Callsign**: a radio station's identity, like AG7EW: letters, a digit, more letters. sotto-tts always says callsigns in the NATO phonetic alphabet, with whole recorded words. [2, 6]

**Candidate**: one recording of a phone pair in the corpus, which the table might keep. Each pair keeps up to 40 candidates while the build decides. [4]

**Coarticulation** (say *koh-ar-TIK-yoo-LAY-shun*): the way each speech sound is coloured by the sounds around it, because the mouth slides from one to the next. The reason diphones work better than single phones. [3]

**Codebook**: sotto's list of learned shapes. A frame's shape is sent as a few numbers that pick entries from it, instead of the shape itself. [1, 6]

**Content word**: a word that carries meaning: a noun, verb, adjective or adverb. Content words get stress and a pitch peak; see function word. [2, 5]

**Corpus** (say *KOR-pus*; plural *corpora*): the collection of recordings the tables are cut from. sotto-tts's is 2,052 recordings, 122 minutes, of Kokoro's af_sarah voice. [3]

**Cost**: a number that says how bad a choice is (lower is better). The build picks, for each pair, the candidate with the lowest cost. [4]

**Creak** (also *vocal fry*): a crackly, very low way of voicing, common at the end of a phrase. Pitch trackers often read it as half the true pitch. [6]

### D
**Declination** (say *dek-li-NAY-shun*): the slow fall of pitch through a phrase. sotto-tts's baseline falls 15% over each phrase. [5]

**Decision tree**: a chain of yes/no questions that ends in a prediction. sotto-tts's optional trained prosody uses two: one for durations, one for pitch (`tts/prosody.py`). [5]

**Decoder**: the part of a vocoder that turns the received numbers back into sound. The radio already has sotto's. [1]

**Diphone** (say *DY-fone*): the stretch of speech from the middle of one phone to the middle of the next. The diphone table (`tts/data/diphone.stt`, 37 KB) holds 1,634 of them. [3]

**Distance**: how different two shapes are, measured as the straight-line distance between them when each shape is a point in a 19-dimensional space. [4]

### E
**Energy**: how loud a frame is; one of sotto's four fields. Code `ei` (energy index) in the code. [1, 6]

**Exceptions list** (also *lexicon*, say *LEK-si-kon*): the words whose pronunciation is stored instead of worked out by rules (`tts/data/lexicon.txt`, 878 words). [2]

### F
**Fault checks**: extra costs in the build for three kinds of bad recording found by ear: a voiced sound analysed as hiss, a stop with no silence, a cut across two words (`checks()` in `tools/tts_build.py`). [4, 7]

**Frame**: 20 ms of speech, described by voicing, pitch, energy and shape. [1]

**Front end**: the part of the engine that turns text into phones: normalisation, rules and the exceptions list (`tts/frontend.py`). [2]

**Function word**: a small grammar word like "the", "of", "is" or "to". Function words are said quickly with no stress, and their vowels become AX. [2, 5]

### H
**Harvard sentences**: a standard set of test sentences from the 1960s, such as "The birch canoe slid on the smooth planks", written so that words can't be guessed from the meaning. [7]

**Hunt bench** (also *diphone hunt*): the web page that plays every diphone four ways (reference, reference encoder, radio encoder, TTS), scores them and saves a listener's marks (`docs/diphone-hunt.html`). [7]

### I
**ICAO** (said as letters, *I-C-A-O*): the International Civil Aviation Organization, which publishes the official spellings and pronunciations of the NATO phonetic alphabet (Lima is *LEE-ma*). [2]

**Interpolation** (say *in-TER-puh-LAY-shun*): filling in values between known points by drawing straight lines between them. The engine interpolates between keyframes to get every 20 ms frame. [6]

### K
**Keyframe**: a frame from a diphone, placed at its moment in the plan. The frames in between are interpolated, like the drawings between the key drawings in an animation. [6]

**Kokoro** (say *koh-KOH-roh*): an open neural text-to-speech model (Apache-2.0 licence). Far too big for a radio, it was sotto-tts's teacher: its voice af_sarah read the corpus, and it reports how long each phone lasts. [1, 3]

### L
**Letter-to-sound rules**: rules of the form `LEFT[MATCH]RIGHT=PHONES` that say how to pronounce letters in context. sotto-tts has 313, after NRL Report 7948 (`tts/lts.py`). [2]

### M
**Median** (say *MEE-dee-un*): the middle value when a list of numbers is sorted. A phone's typical length is its median length in the corpus. [5]

### N
**NATO phonetic alphabet**: Alfa, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, Juliett, Kilo, Lima, Mike, November, Oscar, Papa, Quebec, Romeo, Sierra, Tango, Uniform, Victor, Whiskey, X-ray, Yankee, Zulu: words for letters that can't be confused on a noisy radio. [2]

**Normalisation**: turning things that aren't plain words (numbers, callsigns, units) into words. [2]

### O
**Octave error**: a pitch measured at double or half the true pitch. [6]

### P
**PAU**: the pause "phone". Diphones like `PAU-G` cover the start of a word after silence. [2, 3]

**Phone**: one speech sound, such as the "sh" in "ship" (`SH`). [2]

**Phrase-final lengthening**: slowing down on the last syllable of a phrase; sotto-tts makes it 1.35 times as long. [5]

**Pitch**: how fast the vocal cords buzz, in hertz. The af_sarah voice's middle pitch is about 188 Hz. The table stores none; the melody rules make it. [1, 5]

**Prosody** (say *PROSS-uh-dee*): the rhythm and melody of speech: how long each sound lasts, where the pauses go, and where the pitch rises and falls. [5]

### R
**Robot table** (`tts/data/robot.stt`, 493 bytes): 3 averaged frames for each phone. Small and clear, but robotic, because it has no coarticulation. [1, 3]

### S
**Shape** (also *spectral envelope*): which frequencies are loud and which are quiet in a frame; this is what tells one vowel or consonant from another. [1]

**Speech recogniser**: a program that turns speech into text. sotto-tts is scored with one called Parakeet (`tools/tts_eval.py`). [7]

**Stress**: how strongly a syllable is said. Marked 1 (main stress) or 2 (secondary) after a vowel in ARPAbet. [2]

**Superframe**: sotto 1200's packet: two 20 ms frames in 48 bits (6 bytes). [1]

### T
**TTS**: text to speech (said as letters, *T-T-S*). [1]

### U
**Unit selection**: choosing which recording of each piece to use. sotto-tts chooses all the pairs together, so neighbours fit. [4]

### V
**Vocoder** (say *VOH-koh-der*): a voice coder: a program that describes a voice with a few numbers and rebuilds it from them. sotto is one. [1]

**Voicing**: whether a frame buzzes (vocal cords vibrating, as in vowels) or hisses (as in "s" and "f"). [1]

### W
**WebAssembly** (also *wasm*): a way to run compiled C code inside a web page. The demo page runs the C engine this way (`docs/sotto_tts.wasm`). [6]

**Word error rate** (WER, said as letters): the share of words a recogniser gets wrong (left out, added or changed). [7]

**Whole-word units**: the 37 recorded callsign words (`tts/data/words.stw`, 5 KB) used instead of diphones for callsigns. [6]
