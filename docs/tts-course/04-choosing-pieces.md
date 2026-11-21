---
title: "4. Choosing the best pieces"
---

# 4. Choosing the best pieces

Previous: [Sounds in pairs: diphones](03-diphones.md) · [Course home](README.md) · Next: [Rhythm and melody](05-rhythm-and-melody.md)

## Big idea

The corpus has many recordings of most pairs (half of the 1,634 pairs have more than 10). The table can keep only one of each. Picking the "best" one for each pair on its own isn't enough, because pieces have to **fit their neighbours**. sotto-tts picks all 1,634 together, like a jigsaw, and then runs some extra checks for faults it learned to spot by ear.

## What makes a good piece?

Each candidate recording of a pair gets a **cost**, a number where lower is better. The table keeps the candidate with the lowest cost. The cost adds up a few things:

1. **Is it a normal length?** Each phone has a typical length (its median in the corpus, stressed or unstressed). A candidate whose phones are much longer or shorter than usual costs more. The engine measures this on a log scale, so twice as long and half as long cost the same.
2. **Does it match its neighbours where they join?** This is the important one, explained next.
3. **Does it pass the fault checks?** Explained at the end of the chapter.

## Fitting the neighbours

Think about the word "golf" again: `G AA L F`. The engine will use the pairs AA-L and L-F. They meet in the middle of the L. If AA-L's recording ends with one kind of L and L-F's begins with a different kind, the join clicks or the vowel colour jumps.

And there *are* different kinds of L. An L at the start of a word ("lamp") is clear and bright. An L at the end of a syllable ("golf", "ball") is dark, said with the back of the tongue raised. Speech scientists call these versions of the same phone **allophones** (say *AL-uh-fohnz*).

So the cost of a candidate includes how far its shape at each end is from the shape of the pieces it will meet there. "How far" is the **distance** between the two shapes: sotto describes a shape with 19 numbers, so imagine each shape as a point in a space with 19 directions, one per number, and measure the straight-line distance between the points.

But which pieces will it meet? AA-L can be followed by L-F, L-IY, L-AX and dozens of others. The engine **weights** each neighbour by how often English actually puts those three phones together. AA-L followed by L-F (as in "golf") counts more than AA-L followed by L-ZH, which almost never happens.

## The jigsaw problem

Here is the catch: the best choice for AA-L depends on which L-F was chosen, and the best L-F depends on which AA-L was chosen. Everything depends on everything else.

sotto-tts solves this by going round in passes:

1. Start each pair with the candidate whose ends are closest to that phone's *average* shape.
2. Go through all 1,634 pairs. For each one, pick the candidate with the lowest cost, given the neighbours' current choices.
3. Repeat. Each pass, fewer pairs change their minds.

In the real build, the first pass changed 562 pairs, the second 175, the third 54 and the fourth only 7. The choices settle down, like people shuffling seats at a table until everyone is happy enough. (Each pair keeps its 40 most promising candidates, so a pass is quick: the whole build takes about 20 seconds.)

Choosing together made a big difference. On 30 hard test sentences, a speech recogniser's word error dropped from 33% to 22% when the engine switched from choosing each pair alone to choosing them together.

## Fault checks: lessons from listening

After the table was built, a listener went through every diphone by ear (chapter 7 tells how) and found some rough patches. Tracking each one back to the recording it was cut from showed three kinds of fault:

| Fault | What it sounded like | Cause |
|---|---|---|
| A vowel analysed as hiss | "happy" sounded like "cathy" | the IY at the end was cut from someone *spelling* "P", and sotto's analysis had marked some of its frames unvoiced |
| A stop with no closure | the T in "put" sounded smeared | a T has a short silence before its burst; this recording had sound where the silence should be |
| A cut across two words | "tube", "ruin" and "fluid" sounded odd | the UW came from the word "you" in a phrase like "to you", so it carried a bit of the word before |

Instead of fixing those three words by hand, the build now adds to the cost of **any** candidate with the same fault:

- each frame inside a vowel half (or other voiced half) that is marked as hiss, while still loud, costs extra;
- a stop (P, T, K, B, D, G) whose quietest frame isn't quiet costs extra, more the louder it is;
- a pair cut across a gap between two words costs extra.

Because the checks apply to the whole table, every pair with the same fault got better, not only the ones the listener happened to notice. Chapter 7 shows "happy" before and after.

## Try it

1. A candidate's phones last 2 times their usual length; another's last half their usual length. The length cost is 4 × |log(actual ÷ usual)|. Which costs more? (Hint: log(2) = 0.69.)
2. Why weight each neighbour by how often English uses the three phones together? What could go wrong without the weights?
3. The passes changed 562, 175, 54 and 7 pairs. Roughly what fraction fewer changed each time?
4. Why is fixing a *cause* in the build better than replacing the three bad words by hand?

## Where this is in the code

- `tools/tts_build.py`: `diphone_table()` (candidates, costs, the passes), `triphone_weights()` (how often three phones go together), `checks()` (the fault checks).
- `tools/tts_build.py --sources FILE` writes where every pair was cut from, which is how the rough patches were traced.

<details markdown="1"><summary>Answers</summary>

1. They cost the same: 4 × |log 2| = 4 × |log ½| = 4 × 0.69 ≈ 2.8. That's the point of the log scale.
2. Without weights, a rare neighbour (one that almost never comes up in real text) would count as much as a common one, so a piece could be chosen to fit joins nobody ever hears, at the cost of joins people hear all the time.
3. 175 is about 0.31 of 562, 54 is about 0.31 of 175, and 7 is about 0.13 of 54. Each pass changed roughly a third as many pairs as the one before, or fewer.
4. The same fault was in other pairs nobody had listened to yet. A check in the build catches all of them, and keeps catching them whenever the table is rebuilt.

</details>
