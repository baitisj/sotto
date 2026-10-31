"""Build a blind A/B listening page from the template and a render script's key.json.

Usage: python tools/listening/build_page.py ROUND "TITLE" INTRO.html KEY.json OUT_DIR/index.html

TITLE follows "sotto listening test N: blind A/B, ". INTRO.html holds the <p> paragraphs that
explain the round. KEY.json is {"trials": [{"n": 1, "voice": "..."}, ...], "key": {...}}; only
"trials" goes into the page. The page expects audio/t{n}o.wav, t{n}a.wav and t{n}b.wav next
to it. See docs/listening-tests.md.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(rnd, title, intro, key, out):
    s = open(os.path.join(HERE, "ab_page.html")).read()
    trials = json.load(open(key))["trials"]
    js = "[\n" + "".join(f"    {{ n: {t['n']}, voice: {json.dumps(t['voice'])} }},\n" for t in trials) + "  ]"
    for a, b in (("{{ROUND}}", str(rnd)), ("{{TITLE}}", title), ("{{INTRO}}", open(intro).read().strip()),
                 ("{{TRIALS}}", js)):
        s = s.replace(a, b)
    open(out, "w").write(s)


if __name__ == "__main__":
    main(*sys.argv[1:6])
