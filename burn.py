"""
Caption Burner — burn centered title slides onto video.

Usage:
    python burn.py --video input.mp4 --output output.mp4 --transcribe --script script.txt
    python burn.py --video input.mp4 --words words.json --script script.txt --output output.mp4

Workflow:
1. Transcribe video → word-level timestamps (JSON)
2. Split transcript into sentences → get precise timing per sentence
3. Match script sentences to transcript sentences (by order)
4. Display script text at transcript timing
5. Burn as white-on-black centered title slides
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# ─── Transcription ────────────────────────────────────────────────────────────

def transcribe_video(video_path: str, output_json: str, model: str = "large-v3") -> str:
    """Transcribe video to word-level JSON using faster-whisper."""
    script = f"""
import json
from faster_whisper import WhisperModel

model = WhisperModel("{model}", device="cuda", compute_type="float16")
segments, info = model.transcribe("{video_path.replace(chr(92), '/')}", beam_size=5, word_timestamps=True)

words = []
for segment in segments:
    if segment.words:
        for w in segment.words:
            words.append({{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}})

with open("{output_json.replace(chr(92), '/')}", "w", encoding="utf-8") as f:
    json.dump(words, f, indent=2)

print(f"Transcribed {{len(words)}} words")
"""
    print(f"Transcribing video with faster-whisper ({model})...")
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    if result.returncode != 0:
        print("GPU failed, trying CPU fallback...")
        script_cpu = script.replace('device="cuda", compute_type="float16"', 'device="cpu", compute_type="int8"')
        result = subprocess.run([sys.executable, "-c", script_cpu], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Transcription failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
    print(result.stdout.strip())
    return output_json


# ─── Text splitting ───────────────────────────────────────────────────────────

def split_into_phrases(text: str, max_words: int = 16, min_words: int = 6) -> list[str]:
    """Split text into readable phrases for title slides.

    Splits at sentence boundaries first, then at commas for long sentences.
    Merges fragments that are too short.
    """
    text = re.sub(r"\s+", " ", text.strip())
    sentences = re.split(r"(?<=[.!?])\s+", text)

    raw_phrases = []
    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue
        if len(words) <= max_words:
            raw_phrases.append(sentence.strip())
            continue

        # Split long sentences at commas
        parts = re.split(r"(?<=,)\s+", sentence)
        buffer = []
        buffer_words = 0
        for part in parts:
            part_words = len(part.split())
            if buffer_words + part_words <= max_words:
                buffer.append(part)
                buffer_words += part_words
            else:
                if buffer:
                    raw_phrases.append(" ".join(buffer))
                if part_words <= max_words:
                    buffer = [part]
                    buffer_words = part_words
                else:
                    part_word_list = part.split()
                    for i in range(0, len(part_word_list), max_words):
                        chunk = " ".join(part_word_list[i : i + max_words])
                        if chunk.strip():
                            raw_phrases.append(chunk.strip())
                    buffer = []
                    buffer_words = 0
        if buffer:
            raw_phrases.append(" ".join(buffer))

    # Merge short fragments — strict max to prevent line wrapping
    merge_max = max_words
    phrases = []
    for phrase in raw_phrases:
        word_count = len(phrase.split())
        if phrases and word_count < min_words:
            prev_words = len(phrases[-1].split())
            if prev_words + word_count <= merge_max:
                phrases[-1] = phrases[-1] + " " + phrase
                continue
        phrases.append(phrase)

    # Second pass: merge short phrases forward
    final = []
    i = 0
    while i < len(phrases):
        phrase = phrases[i]
        word_count = len(phrase.split())
        if word_count < min_words and i + 1 < len(phrases):
            next_words = len(phrases[i + 1].split())
            if word_count + next_words <= merge_max:
                phrases[i + 1] = phrase + " " + phrases[i + 1]
                i += 1
                continue
        final.append(phrase)
        i += 1

    return final


# ─── Word-level alignment ─────────────────────────────────────────────────────

def build_transcript_sentences(words: list[dict]) -> list[dict]:
    """Group word-level timestamps into sentences based on punctuation."""
    sentences = []
    current_words = []
    current_start = None

    for w in words:
        if current_start is None:
            current_start = w["start"]
        current_words.append(w["word"])

        # Check if this word ends a sentence
        if re.search(r"[.!?]$", w["word"]):
            sentences.append({
                "text": " ".join(current_words),
                "start": current_start,
                "end": w["end"],
            })
            current_words = []
            current_start = None

    # Flush remaining words as final sentence
    if current_words:
        sentences.append({
            "text": " ".join(current_words),
            "start": current_start,
            "end": words[-1]["end"],
        })

    return sentences


def match_sentences(script_sentences: list[str], transcript_sentences: list[dict]) -> list[dict]:
    """Match script sentences to transcript sentences by sequential order.

    Both follow the same structure, so we walk through both lists together.
    If counts differ, we distribute proportionally.
    """
    if not transcript_sentences:
        return []

    n_script = len(script_sentences)
    n_trans = len(transcript_sentences)

    matched = []

    if n_script <= n_trans:
        # More transcript sentences than script — group transcript sentences per script sentence
        ratio = n_trans / n_script
        for i, script_sent in enumerate(script_sentences):
            t_start_idx = int(i * ratio)
            t_end_idx = int((i + 1) * ratio)
            t_end_idx = min(t_end_idx, n_trans)

            start_time = transcript_sentences[t_start_idx]["start"]
            end_time = transcript_sentences[t_end_idx - 1]["end"]

            matched.append({
                "text": script_sent,
                "start": start_time,
                "end": end_time,
            })
    else:
        # More script sentences than transcript — distribute script sentences across transcript time
        ratio = n_script / n_trans
        for i, t_sent in enumerate(transcript_sentences):
            s_start_idx = int(i * ratio)
            s_end_idx = int((i + 1) * ratio)
            s_end_idx = min(s_end_idx, n_script)

            for j in range(s_start_idx, s_end_idx):
                # Distribute time within this transcript sentence
                sub_ratio = (j - s_start_idx) / max(s_end_idx - s_start_idx, 1)
                sub_ratio_end = (j - s_start_idx + 1) / max(s_end_idx - s_start_idx, 1)

                duration = t_sent["end"] - t_sent["start"]
                start_time = t_sent["start"] + sub_ratio * duration
                end_time = t_sent["start"] + sub_ratio_end * duration

                matched.append({
                    "text": script_sentences[j],
                    "start": start_time,
                    "end": end_time,
                })

    return matched


# ─── Slide generation ─────────────────────────────────────────────────────────

def split_long_slides(matched: list[dict], max_words: int = 16) -> list[dict]:
    """Split matched entries that are too long into shorter phrases."""
    result = []
    for entry in matched:
        words = entry["text"].split()
        if len(words) <= max_words:
            result.append(entry)
            continue

        # Split at commas for long sentences
        parts = re.split(r"(?<=,)\s+", entry["text"])
        phrases = []
        buffer = []
        buffer_wc = 0

        for part in parts:
            pwc = len(part.split())
            if buffer_wc + pwc <= max_words:
                buffer.append(part)
                buffer_wc += pwc
            else:
                if buffer:
                    phrases.append(" ".join(buffer))
                buffer = [part]
                buffer_wc = pwc
        if buffer:
            phrases.append(" ".join(buffer))

        # Distribute time proportionally
        total_wc = sum(len(p.split()) for p in phrases)
        duration = entry["end"] - entry["start"]
        t = entry["start"]

        for phrase in phrases:
            pwc = len(phrase.split())
            pd = (pwc / total_wc) * duration
            result.append({"text": phrase, "start": t, "end": t + pd})
            t += pd

    return result


def ensure_no_overlap(slides: list[dict], gap: float = 0.05) -> list[dict]:
    """Ensure no two slides overlap by adding a small gap."""
    for i in range(len(slides) - 1):
        if slides[i]["end"] > slides[i + 1]["start"] - gap:
            slides[i]["end"] = slides[i + 1]["start"] - gap
    return slides


# ─── ASS generation ───────────────────────────────────────────────────────────

def seconds_to_ass(seconds: float) -> str:
    """Convert seconds to ASS timestamp (H:MM:SS.cc)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def generate_ass(slides: list[dict], video_width: int, video_height: int, font_size: int = 56) -> str:
    """Generate ASS subtitle content."""
    ass_content = f"""[Script Info]
Title: Caption Burner
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Instrument Sans Bold,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,100,100,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    for slide in slides:
        start = seconds_to_ass(slide["start"])
        end = seconds_to_ass(slide["end"])
        text = slide["text"]
        ass_content += f"Dialogue: 0,{start},{end},Title,,0,0,0,,{text}\n"

    return ass_content


# ─── FFmpeg ───────────────────────────────────────────────────────────────────

def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Get video width and height via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffprobe error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    parts = [p for p in result.stdout.strip().split(",") if p]
    return int(parts[0]), int(parts[1])


def burn_subtitles(video_path: str, ass_path: str, output_path: str,
                   bg_image: str = None, black_bg: bool = True):
    """Burn ASS subtitles onto video with FFmpeg."""
    escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
    fonts_dir = str(Path(ass_path).parent).replace("\\", "/").replace(":", "\\:")

    if bg_image:
        # Use background image: overlay scaled image, then burn subtitles
        escaped_bg = bg_image.replace("\\", "/").replace(":", "\\:")
        # Input 0 = video (for audio + duration), Input 1 = bg image
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-loop", "1", "-i", bg_image,
            "-filter_complex",
            f"[1:v]scale=1920:1080[bg];[bg]ass='{escaped_ass}':fontsdir='{fonts_dir}'[v]",
            "-map", "[v]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "copy", "-shortest",
            output_path,
        ]
    else:
        if black_bg:
            vf = f"drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill,ass='{escaped_ass}':fontsdir='{fonts_dir}'"
        else:
            vf = f"ass='{escaped_ass}':fontsdir='{fonts_dir}'"
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "copy",
            output_path,
        ]

    print(f"Burning: {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg error: {result.stderr[-500:]}", file=sys.stderr)
        sys.exit(1)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Burn centered title-slide captions onto video")
    parser.add_argument("--video", required=True, help="Input video file")
    parser.add_argument("--script", required=True, help="Clean script text file")
    parser.add_argument("--words", help="Word-level timestamps JSON (from prior transcription)")
    parser.add_argument("--transcribe", action="store_true", help="Transcribe video to get word timestamps")
    parser.add_argument("--output", required=True, help="Output video file")
    parser.add_argument("--model", default="large-v3", help="Whisper model (default: large-v3)")
    parser.add_argument("--max-words", type=int, default=5, help="Max words per line (default: 5)")
    parser.add_argument("--font-size", type=int, default=120, help="Font size (default: 120)")
    parser.add_argument("--bg-image", default=str(Path(__file__).parent / "captions-bg.png"),
                        help="Background image (default: captions-bg.png)")
    parser.add_argument("--no-black-bg", dest="black_bg", action="store_false", default=True)
    args = parser.parse_args()

    # Validate
    if not Path(args.video).exists():
        print(f"Error: Video not found: {args.video}", file=sys.stderr)
        sys.exit(1)
    if not Path(args.script).exists():
        print(f"Error: Script not found: {args.script}", file=sys.stderr)
        sys.exit(1)
    if not args.words and not args.transcribe:
        print("Error: Provide --words or use --transcribe", file=sys.stderr)
        sys.exit(1)

    # Step 1: Get word-level timestamps
    words_path = args.words
    if args.transcribe:
        words_path = str(Path(args.output).with_suffix(".words.json"))
        transcribe_video(args.video, words_path, model=args.model)

    print(f"Loading word timestamps: {words_path}")
    with open(words_path, "r", encoding="utf-8") as f:
        words = json.load(f)
    print(f"  {len(words)} words, {words[0]['start']:.1f}s – {words[-1]['end']:.1f}s")

    # Step 2: Build balanced 2-line slides using character-based limits
    print("Building slides...")
    script_text = Path(args.script).read_text(encoding="utf-8")
    script_text = re.sub(r"\s+", " ", script_text.strip())
    script_words = script_text.split()
    total_script_words = len(script_words)
    total_transcript_words = len(words)

    # Character limit per line based on font size
    # ~55px per char at 100pt on 1920px with 100px margins = 1720px usable
    max_chars_per_line = int(1720 / (args.font_size * 0.55))
    max_chars_per_slide = max_chars_per_line * 2

    print(f"  Script: {total_script_words} words -> Transcript: {total_transcript_words} words across {words[-1]['end']:.1f}s")
    print(f"  Max ~{max_chars_per_line} chars/line at {args.font_size}pt")

    # Chunk script into slides that fit within character limit
    chunks = []
    pos = 0
    while pos < total_script_words:
        # Grow chunk until we hit the character limit
        end = pos + 1
        while end < total_script_words:
            candidate = " ".join(script_words[pos:end + 1])
            if len(candidate) > max_chars_per_slide:
                break
            end += 1

        # Try to end at a sentence or comma break
        best_break = end
        search_lo = max(pos + 2, end - 4)
        for i in range(end, search_lo, -1):
            if i <= total_script_words and script_words[i - 1][-1] in ".!?":
                best_break = i
                break
        if best_break == end:
            for i in range(end, search_lo, -1):
                if i <= total_script_words and script_words[i - 1].endswith(","):
                    best_break = i
                    break

        chunk_words = script_words[pos:best_break]
        chunks.append(chunk_words)
        pos = best_break

    # For each chunk, split into 2 balanced lines and map to timeline
    slides = []
    script_word_pos = 0

    for chunk in chunks:
        chunk_text = " ".join(chunk)
        chunk_len = len(chunk)

        if len(chunk_text) <= max_chars_per_line:
            # Fits on one line — no split needed
            slide_text = chunk_text
        else:
            # Find split point where both lines fit within char limit
            # and are as balanced as possible
            best_split = chunk_len // 2
            best_score = 999

            for i in range(1, chunk_len):
                line1 = " ".join(chunk[:i])
                line2 = " ".join(chunk[i:])

                # Both lines must fit
                if len(line1) > max_chars_per_line or len(line2) > max_chars_per_line:
                    continue

                # Score: prefer balanced length + punctuation breaks
                imbalance = abs(len(line1) - len(line2))
                score = imbalance
                if chunk[i - 1][-1] in ",.!?;:":
                    score -= 10  # Strong bonus for punctuation
                if score < best_score:
                    best_score = score
                    best_split = i

            line1 = " ".join(chunk[:best_split])
            line2 = " ".join(chunk[best_split:])
            slide_text = line1 + "\\N" + line2 if line2 else line1

        # Map to timeline
        start_frac = script_word_pos / total_script_words
        end_frac = (script_word_pos + chunk_len) / total_script_words

        t_start_idx = int(start_frac * total_transcript_words)
        t_end_idx = int(end_frac * total_transcript_words) - 1

        t_start_idx = max(0, min(t_start_idx, total_transcript_words - 1))
        t_end_idx = max(t_start_idx, min(t_end_idx, total_transcript_words - 1))

        slides.append({
            "text": slide_text,
            "start": words[t_start_idx]["start"],
            "end": words[t_end_idx]["end"],
        })
        script_word_pos += chunk_len

    print(f"  {len(slides)} slides (2 balanced lines each)")

    # Step 6: Fix overlaps
    slides = ensure_no_overlap(slides)

    # Step 7: Generate ASS
    print("Getting video dimensions...")
    width, height = get_video_dimensions(args.video)
    print(f"  {width}x{height}")

    # Step 7: Generate ASS and burn
    ass_content = generate_ass(slides, width, height, font_size=args.font_size)
    ass_path = str(Path(args.output).with_suffix(".ass"))
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    burn_subtitles(args.video, ass_path, args.output,
                   bg_image=args.bg_image, black_bg=args.black_bg)

    # Remove ASS file so video players don't auto-load it as a soft subtitle
    Path(ass_path).unlink(missing_ok=True)
    print(f"Done! {args.output}")


if __name__ == "__main__":
    main()
