# vtt2txt.py
import re, sys, pathlib, html

# Drop headers/notes and cue timing lines
RX_META = re.compile(r'^(WEBVTT|Kind:|Language:|STYLE|NOTE|REGION|Region:)', re.IGNORECASE)
RX_TIMING = re.compile(r'-->\s')  # lines containing cue timestamps

# Clean inline junk
RX_INLINE_TS = re.compile(r'<\d{2}:\d{2}:\d{2}\.\d{3}>')  # <00:00:00.000>
RX_TAGS = re.compile(r'</?[^>]+>')                        # <c>, </c>, <i>, etc.
RX_WS = re.compile(r'\s+')                                # any whitespace -> single space

def normalize(line: str) -> str:
    line = RX_INLINE_TS.sub("", line)
    line = RX_TAGS.sub("", line)
    line = html.unescape(line)
    line = RX_WS.sub(" ", line).strip()                   # remove the spaces (normalize to single)
    return line

def process(path: pathlib.Path):
    seen = set()
    out_lines = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            if RX_META.match(raw) or RX_TIMING.search(raw):
                continue
            text = normalize(raw)
            if not text:
                continue
            if text not in seen:                          # de-duplicate lines globally
                seen.add(text)
                out_lines.append(text)
    path.with_suffix(".txt").write_text("\n".join(out_lines) + "\n", encoding="utf-8")

if __name__ == "__main__":
    targets = [pathlib.Path(p) for p in (sys.argv[1:] or [])]
    if not targets:
        sys.exit("Usage: python vtt2txt.py file1.vtt [file2.vtt ...] | DIRS")
    for p in targets:
        if p.is_dir():
            for v in p.rglob("*.vtt"):
                process(v)
        elif p.suffix.lower() == ".vtt":
            process(p)
