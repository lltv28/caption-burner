"""Render each section as a separate video for debugging sync issues.

Generates a per-section ASS file with timestamps shifted to start at 0,
since ffmpeg -ss resets the output timeline.
"""

import re
import subprocess
from pathlib import Path

VIDEO = "C:/Users/lucas/Downloads/2026-04-12 14-53-05-latter.mp4"
BG = str(Path(__file__).parent / "captions-bg.png")
ASS = str(Path(__file__).parent / "latter.ass")
FONTS = str(Path(__file__).parent)
OUTDIR = Path(__file__).parent / "sections"

SECTIONS = [
    ("s1-intro", 0.0, 120.98),
    ("s2-bullet-kodara", 120.98, 198.10),
    ("s3-testimonials-skip", 198.10, 254.06),
    ("s4-how-it-works", 254.06, 381.62),
    ("s5-bullet-benefits", 381.62, 434.22),
    ("s6-marketing", 434.22, 602.82),
    ("s7-bullet-faq", 602.82, 967.38),
    ("s8-closing", 967.38, 1031.6),
]

OUTDIR.mkdir(exist_ok=True)


def parse_ass_time(ts):
    """Parse ASS timestamp H:MM:SS.cc to seconds."""
    m = re.match(r"(\d+):(\d+):(\d+\.\d+)", ts)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def format_ass_time(seconds):
    """Format seconds to ASS timestamp H:MM:SS.cc."""
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def create_section_ass(full_ass_path, section_start, section_end, output_path):
    """Extract events for a section and shift timestamps to start at 0."""
    with open(full_ass_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split into header and events
    parts = content.split("[Events]\n")
    header = parts[0] + "[Events]\n"

    # Get format line and dialogue lines
    event_lines = parts[1].strip().split("\n")
    format_line = event_lines[0]  # Format: Layer, Start, End, ...

    shifted_events = [format_line]
    for line in event_lines[1:]:
        if not line.startswith("Dialogue:"):
            continue

        # Parse start/end times from dialogue line
        # Dialogue: 0,H:MM:SS.cc,H:MM:SS.cc,Style,...
        m = re.match(r"(Dialogue:\s*\d+,)(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),(.*)", line)
        if not m:
            continue

        prefix = m.group(1)
        evt_start = parse_ass_time(m.group(2))
        evt_end = parse_ass_time(m.group(3))
        rest = m.group(4)

        # Skip events outside this section
        if evt_end <= section_start or evt_start >= section_end:
            continue

        # Clamp to section boundaries and shift to 0
        new_start = max(0, evt_start - section_start)
        new_end = min(section_end - section_start, evt_end - section_start)

        shifted_events.append(
            f"{prefix}{format_ass_time(new_start)},{format_ass_time(new_end)},{rest}"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(shifted_events) + "\n")

    return len(shifted_events) - 1  # exclude format line


fonts_esc = FONTS.replace("\\", "/").replace(":", "\\:")

for name, start, end in SECTIONS:
    duration = end - start
    out = str(OUTDIR / f"{name}.mp4")

    if name == "s3-testimonials-skip":
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(duration), "-i", VIDEO,
            "-loop", "1", "-i", BG,
            "-filter_complex", "[1:v]scale=1920:1080[v]",
            "-map", "[v]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy", "-shortest",
            out,
        ]
        print(f"Rendering {name} ({duration:.0f}s) [no captions]...")
    else:
        # Create shifted ASS for this section
        section_ass = str(OUTDIR / f"{name}.ass")
        n_events = create_section_ass(ASS, start, end, section_ass)
        section_ass_esc = section_ass.replace("\\", "/").replace(":", "\\:")

        vf = f"[1:v]scale=1920:1080[bg];[bg]ass='{section_ass_esc}':fontsdir='{fonts_esc}'[v]"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(duration), "-i", VIDEO,
            "-loop", "1", "-i", BG,
            "-filter_complex", vf,
            "-map", "[v]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy", "-shortest",
            out,
        ]
        print(f"Rendering {name} ({duration:.0f}s) [{n_events} events]...")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[-300:]}")
    else:
        print(f"  Done: {out}")
