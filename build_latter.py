"""
Build ASS subtitle file for the 'latter' video with mixed Title + Bullet styles.

Title sections use TRANSCRIPT WORDS directly (not script text) for perfect
audio sync. Each slide's timing comes from the actual word timestamps.

Bullet sections use manually defined items with word-index triggers.

Reads word-level timestamps, produces latter.ass.
"""

import json
import re
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE = Path(__file__).parent
WORDS_PATH = BASE / "latter.words.json"
OUTPUT_PATH = BASE / "latter.ass"

# ─── Config ───────────────────────────────────────────────────────────────────

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
TITLE_FONT_SIZE = 120
BULLET_FONT_SIZE = 70
MAX_CHARS_PER_LINE = int(1720 / (TITLE_FONT_SIZE * 0.55))  # ~26
MAX_LINES = 3
MAX_CHARS_PER_SLIDE = MAX_CHARS_PER_LINE * MAX_LINES  # ~78

SLIDE_GAP = 0.05  # 50ms gap between consecutive title slides

# ─── Section definitions ──────────────────────────────────────────────────────

SECTIONS = [
    {
        "type": "title",
        "start_time": 0.0,
        "end_time": 120.98,
    },
    {
        "type": "bullet",
        "start_time": 120.98,
        "end_time": 198.10,
        "bullet_id": 1,
    },
    {
        "type": "skip",
        "start_time": 198.10,
        "end_time": 254.06,
        "note": "Testimonials — no captions",
    },
    {
        "type": "title",
        "start_time": 254.06,
        "end_time": 381.62,
    },
    {
        "type": "bullet",
        "start_time": 381.62,
        "end_time": 434.22,
        "bullet_id": 2,
    },
    {
        "type": "title",
        "start_time": 434.22,
        "end_time": 602.82,
    },
    {
        "type": "bullet",
        "start_time": 602.82,
        "end_time": 967.38,
        "bullet_id": 3,
    },
    {
        "type": "title",
        "start_time": 967.38,
        "end_time": 1031.6,
    },
]

# ─── Bullet definitions ──────────────────────────────────────────────────────

BULLETS = {
    1: {
        "title": "The Kodara Flagship System",
        "items": [
            "Full done-for-you AI build out",
            "Fully custom marketing plan",
            "Branded, fully customized platform",
            "Full launch implementation",
            "Done-for-you, white-glove service",
            "50 high-ticket clients guarantee",
        ],
        # Word indices verified from transcript dump:
        # [432] "fully" [433] "done" [434] "-for" [435] "-you" [436] "AI" [437] "build" @ 125.16s
        # [487] "marketing" [488] "plan" @ 142.94s
        # [544] "branded" @ 156.54s
        # [577] "launch" [578] "implementation" @ 167.00s
        # [630] "white" [631] "-glove" @ 184.98s
        # [657] "guarantee," @ 192.10s
        "trigger_word_indices": [432, 487, 544, 577, 630, 657],
    },
    2: {
        "title": "Benefits of a low-ticket AI product",
        "items": [
            "Easy entry point to attract cold leads",
            "AI delivers experience without your involvement",
            "New revenue stream covers marketing costs",
            "Nurtures leads to high-ticket offers",
            "Automate and productize your IP",
            "Focus only on premium clients",
        ],
        # Word indices verified from transcript dump:
        # [1275] "easy," -> actually [1278] "entry" @ 385.52s
        # [1302] "positive" [1303] "experience" @ 392.88s
        # [1322] "revenue" [1323] "stream" @ 399.56s
        # [1339] "nurturing" @ 405.16s
        # [1363] "productize" @ 413.24s
        # [1409] "focus" @ 423.08s
        "trigger_word_indices": [1278, 1302, 1322, 1339, 1363, 1409],
    },
    3: {
        "title": "Most common questions",
        "items": [
            "How much time does this take?",
            "Will this work in my industry?",
            "Can AI really do what I do?",
            "How will this work with my current offer?",
            "Who will do the technical setup?",
            "How do you drive actual sales?",
            "How do you ensure privacy/security?",
            "How does the guarantee work?",
        ],
        # Word indices verified from transcript dump:
        # [2039] "How" "much" "time" @ 607.18s
        # [2045] "Will" "this" "work" "in" "my" "industry?" @ 608.64s
        # [2051] "Can" "AI" "really" @ 610.12s
        # [2068] "How" "will" "this" "work" "with" "my" "current" @ 614.40s
        # [2086] "Who's" @ 618.36s (technical setup)
        # [2103] "How" "do" "you" ... "drive" @ 623.20s
        # [2124] "How" "do" "you" "ensure" "privacy" @ 625.66s
        # [2139] "guarantee" "work?" @ 629.54s
        "trigger_word_indices": [2039, 2045, 2051, 2068, 2086, 2103, 2124, 2139],
    },
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def seconds_to_ass(seconds: float) -> str:
    """Convert seconds to ASS timestamp (H:MM:SS.cc)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def get_words_in_range(words, start_time, end_time):
    """Get word entries within a time range."""
    return [w for w in words if w["start"] >= start_time - 0.01 and w["start"] < end_time]


def filter_hallucinations(word_list):
    """Remove whisper hallucinations/artifacts.

    Filters:
    - Zero-duration words (start == end)
    - Clusters of words with near-identical timestamps (< 0.08s apart)
      that indicate hallucinated text
    """
    if not word_list:
        return []

    # First pass: remove zero-duration
    filtered = [w for w in word_list if w["end"] > w["start"]]

    # Second pass: remove clusters of rapid-fire words (hallucination bursts)
    # If 3+ consecutive words all start within 0.15s of each other, remove them
    result = []
    i = 0
    while i < len(filtered):
        # Check if this starts a hallucination burst
        burst_end = i + 1
        while burst_end < len(filtered):
            gap = filtered[burst_end]["start"] - filtered[burst_end - 1]["start"]
            duration = filtered[burst_end]["end"] - filtered[burst_end]["start"]
            if gap < 0.08 and duration < 0.15:
                burst_end += 1
            else:
                break

        burst_len = burst_end - i
        if burst_len >= 3:
            # Skip the whole burst
            i = burst_end
        else:
            result.append(filtered[i])
            i += 1

    return result


# ─── Text cleanup ────────────────────────────────────────────────────────────

def join_split_words(word_list):
    """Join words that whisper splits incorrectly.

    Handles:
    - Hyphenated compounds: 'done' + '-for' + '-you' -> 'done-for-you'
    - Split numbers: '$6' + ',000.' -> '$6,000.'
    - Split decimals: '$4' + '.4' -> '$4.4'
    """
    if not word_list:
        return []

    result = []
    i = 0
    while i < len(word_list):
        current = word_list[i]
        # Look ahead for hyphen/comma/dot/percent-prefixed continuations
        while i + 1 < len(word_list) and (
            word_list[i + 1]["word"].startswith("-") or
            word_list[i + 1]["word"].startswith(",") or
            word_list[i + 1]["word"] == "%" or
            (word_list[i + 1]["word"].startswith(".") and len(word_list[i + 1]["word"]) > 1
             and word_list[i + 1]["word"][1:2].isdigit())
        ):
            current = {
                "word": current["word"] + word_list[i + 1]["word"],
                "start": current["start"],
                "end": word_list[i + 1]["end"],
            }
            i += 1
        result.append(current)
        i += 1
    return result


def clean_text(text, prev_slide_text=None):
    """Apply text cleanup rules to a slide's text.

    - Only capitalize first letter if it starts a new sentence
      (previous slide ended with .!? or this is the first slide)
    - Fix 'i' -> 'I' at word boundaries
    - Fix 'ai' -> 'AI' as standalone word
    """
    if not text:
        return text

    # Only capitalize if starting a new sentence
    starts_new_sentence = (
        prev_slide_text is None or
        prev_slide_text.rstrip().endswith(('.', '!', '?'))
    )
    if starts_new_sentence:
        text = text[0].upper() + text[1:]

    # Fix standalone 'i' -> 'I'
    text = re.sub(r'\bi\b', 'I', text)

    # Fix 'ai' -> 'AI' as standalone word (case insensitive match)
    text = re.sub(r'\bai\b', 'AI', text, flags=re.IGNORECASE)

    # Convert spelled-out numbers to numeric
    number_map = {
        'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
        'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
        'ten': '10', 'eleven': '11', 'twelve': '12', 'thirteen': '13',
        'fourteen': '14', 'fifteen': '15', 'sixteen': '16', 'seventeen': '17',
        'eighteen': '18', 'nineteen': '19', 'twenty': '20', 'thirty': '30',
        'forty': '40', 'fifty': '50', 'sixty': '60', 'seventy': '70',
        'eighty': '80', 'ninety': '90', 'hundred': '100', 'thousand': '1,000',
        'million': 'million',  # keep "million" as-is (e.g., "$50 million")
    }
    for word, num in number_map.items():
        text = re.sub(r'\b' + word + r'\b', num, text, flags=re.IGNORECASE)

    return text


# ─── Title slide generation (transcript-based) ──────────────────────────────

def group_words_into_slides(word_entries, max_chars_per_slide, max_chars_per_line):
    """Group transcript word entries into slide-sized chunks.

    Each slide has max ~78 chars (3 lines x 26 chars).
    Prefers ending slides at sentence boundaries (.!?) so slides
    don't cut off mid-sentence.
    Returns list of lists of word entries.
    """
    if not word_entries:
        return []

    slides = []
    current_slide = []
    current_text = ""

    for entry in word_entries:
        word = entry["word"]
        test_text = (current_text + " " + word).strip() if current_text else word

        # Check if adding this word would exceed slide capacity
        if current_text and not can_fit_in_lines(test_text, max_chars_per_line):
            # Current slide is full, start a new one
            slides.append(current_slide)
            current_slide = [entry]
            current_text = word
        else:
            current_slide.append(entry)
            current_text = test_text

            # If we just hit a sentence end and have a decent amount of text,
            # end the slide here rather than continuing mid-next-sentence
            if (word.rstrip().endswith(('.', '!', '?'))
                    and len(current_text) > 20
                    and len(current_slide) >= 3):
                slides.append(current_slide)
                current_slide = []
                current_text = ""

    if current_slide:
        slides.append(current_slide)

    return slides


def can_fit_in_lines(text, max_chars_per_line, max_lines=MAX_LINES):
    """Check if text can fit within max_lines of max_chars_per_line each."""
    if len(text) <= max_chars_per_line:
        return True
    words = text.split()
    lines = []
    current = []
    for w in words:
        test = " ".join(current + [w])
        if len(test) <= max_chars_per_line:
            current.append(w)
        else:
            if current:
                lines.append(current)
            current = [w]
    if current:
        lines.append(current)
    return len(lines) <= max_lines


def split_into_lines(chunk_words, max_chars_per_line):
    """Split a list of words into up to MAX_LINES balanced lines.

    Rules:
    - Max 26 chars per line at word boundaries
    - Prefer splitting at punctuation
    - Balance line lengths
    - Min 2 words per line when splitting
    """
    text = " ".join(chunk_words)

    if len(text) <= max_chars_per_line:
        return text

    # For 2 words or fewer, no splitting needed
    if len(chunk_words) <= 2:
        return text

    # Try 2-line split first
    best_result = None
    best_score = 9999

    for i in range(1, len(chunk_words)):
        line1 = " ".join(chunk_words[:i])
        line2 = " ".join(chunk_words[i:])

        if len(line1) > max_chars_per_line or len(line2) > max_chars_per_line:
            continue

        # Enforce min 2 words per line
        if i < 2 and len(chunk_words) - i >= 2:
            continue
        if len(chunk_words) - i < 2 and i >= 2:
            continue

        imbalance = abs(len(line1) - len(line2))
        score = imbalance
        if chunk_words[i - 1][-1] in ",.!?;:": score -= 15

        if score < best_score:
            best_score = score
            best_result = line1 + "\\N" + line2

    if best_result:
        return best_result

    # Need 3-line split
    best_result = None
    best_score = 9999

    for i in range(1, len(chunk_words) - 1):
        for j in range(i + 1, len(chunk_words)):
            line1 = " ".join(chunk_words[:i])
            line2 = " ".join(chunk_words[i:j])
            line3 = " ".join(chunk_words[j:])

            if (len(line1) > max_chars_per_line or
                len(line2) > max_chars_per_line or
                len(line3) > max_chars_per_line):
                continue

            lengths = [len(line1), len(line2), len(line3)]
            imbalance = max(lengths) - min(lengths)
            score = imbalance
            if chunk_words[i - 1][-1] in ",.!?;:": score -= 10
            if chunk_words[j - 1][-1] in ",.!?;:": score -= 10

            if score < best_score:
                best_score = score
                best_result = line1 + "\\N" + line2 + "\\N" + line3

    if best_result:
        return best_result

    # Fallback: greedy line packing
    lines = []
    current = []
    for w in chunk_words:
        test = " ".join(current + [w])
        if len(test) <= max_chars_per_line:
            current.append(w)
        else:
            if current:
                lines.append(" ".join(current))
            current = [w]
    if current:
        lines.append(" ".join(current))
    return "\\N".join(lines)


def build_title_slides(words, section):
    """Build centered title slides for a title section using transcript words directly.

    Each slide's timing comes from the actual word timestamps — no proportional
    mapping needed. This gives perfect audio sync.
    """
    start_time = section["start_time"]
    end_time = section["end_time"]

    # Get transcript words in this time range
    section_words = get_words_in_range(words, start_time, end_time)
    if not section_words:
        print(f"  WARNING: No words found in range {start_time:.1f}-{end_time:.1f}")
        return []

    # Filter out zero-duration words (Whisper hallucinations)
    before_count = len(section_words)
    section_words = filter_hallucinations(section_words)
    filtered = before_count - len(section_words)
    if filtered:
        print(f"  Filtered {filtered} zero-duration words ({before_count} -> {len(section_words)})")

    # Join split words (hyphenated compounds + split numbers)
    section_words = join_split_words(section_words)

    # Trim trailing words that don't complete a sentence
    # This prevents slides ending mid-sentence at section boundaries
    if section_words:
        last_sentence_end = len(section_words)
        for i in range(len(section_words) - 1, -1, -1):
            if section_words[i]["word"].rstrip().endswith(('.', '!', '?')):
                last_sentence_end = i + 1
                break
        if last_sentence_end < len(section_words):
            trimmed = len(section_words) - last_sentence_end
            section_words = section_words[:last_sentence_end]
            print(f"  Trimmed {trimmed} trailing words (incomplete sentence)")

    # Group words into slide-sized chunks
    slide_groups = group_words_into_slides(
        section_words, MAX_CHARS_PER_SLIDE, MAX_CHARS_PER_LINE
    )

    if not slide_groups:
        return []

    slides = []
    prev_text = None
    for group in slide_groups:
        # Extract word texts
        word_texts = [w["word"] for w in group]

        # Clean text
        slide_text_raw = " ".join(word_texts)
        slide_text_raw = clean_text(slide_text_raw, prev_slide_text=prev_text)
        prev_text = slide_text_raw

        # Split cleaned text into balanced lines
        cleaned_words = slide_text_raw.split()
        slide_text = split_into_lines(cleaned_words, MAX_CHARS_PER_LINE)

        # Timing directly from word timestamps
        slide_start = group[0]["start"]
        slide_end = group[-1]["end"]

        # Ensure minimum duration
        if slide_end - slide_start < 0.5:
            slide_end = slide_start + 0.5

        slides.append({
            "text": slide_text,
            "start": slide_start,
            "end": slide_end,
            "style": "Title",
        })

    # Merge trailing single-word slides into the previous slide
    if len(slides) > 1:
        last = slides[-1]
        last_word_count = len(last["text"].replace("\\N", " ").split())
        if last_word_count <= 2 and last["end"] - last["start"] < 1.5:
            # Merge into previous slide
            prev = slides[-2]
            prev_words = prev["text"].replace("\\N", " ").split()
            last_words = last["text"].replace("\\N", " ").split()
            merged_words = prev_words + last_words
            prev["text"] = split_into_lines(merged_words, MAX_CHARS_PER_LINE)
            prev["end"] = last["end"]
            slides.pop()

    # Add small gap between consecutive slides (50ms)
    for i in range(len(slides) - 1):
        next_start = slides[i + 1]["start"]
        if slides[i]["end"] >= next_start:
            slides[i]["end"] = next_start - SLIDE_GAP

    # Ensure no overlaps
    for i in range(len(slides) - 1):
        if slides[i]["end"] > slides[i + 1]["start"] - SLIDE_GAP:
            slides[i]["end"] = slides[i + 1]["start"] - SLIDE_GAP

    # Ensure minimum duration after gap adjustments
    for i in range(len(slides)):
        if slides[i]["end"] - slides[i]["start"] < 0.3:
            slides[i]["end"] = slides[i]["start"] + 0.3

    return slides


# ─── Bullet slide generation ─────────────────────────────────────────────────

def build_bullet_slides(words, bullet_id, section):
    """Build progressive-reveal bullet slides.

    Uses verified word indices from the transcript to find exact reveal times.
    Each cumulative state is a non-overlapping dialogue event.
    """
    bullet_def = BULLETS[bullet_id]
    title = bullet_def["title"]
    items = bullet_def["items"]
    trigger_indices = bullet_def["trigger_word_indices"]
    section_end = section["end_time"]

    slides = []

    # Get timestamps from verified word indices
    timestamps = []
    for i, idx in enumerate(trigger_indices):
        t = words[idx]["start"]
        timestamps.append(t)
        print(f"    Bullet {i+1}: '{items[i]}' -> word [{idx}] "
              f"('{words[idx]['word']}') @ {t:.2f}s")

    # Build progressive states
    section_start = section["start_time"]
    for i in range(len(items)):
        # First bullet shows immediately at section start
        start_t = section_start if i == 0 else timestamps[i]

        if i + 1 < len(items):
            end_t = timestamps[i + 1] - 0.05
        else:
            end_t = section_end

        # Build cumulative text: title + all bullets up to this one
        lines = []
        lines.append("{\\fs100}" + title)
        lines.append("")  # blank line for spacing
        for j in range(i + 1):
            lines.append("{\\fs70}\u2022  " + items[j])

        text = "\\N".join(lines)

        slides.append({
            "text": text,
            "start": start_t,
            "end": end_t,
            "style": "Bullet",
        })

    return slides


# ─── ASS file generation ──────────────────────────────────────────────────────

def generate_ass(slides):
    """Generate complete ASS file content."""
    header = f"""[Script Info]
Title: Latter Video Captions
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Instrument Sans Bold,{TITLE_FONT_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,100,100,40,1
Style: Bullet,Instrument Sans Bold,{BULLET_FONT_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,150,100,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = ""
    for slide in slides:
        start = seconds_to_ass(slide["start"])
        end = seconds_to_ass(slide["end"])
        style = slide["style"]
        text = slide["text"]
        events += f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}\n"

    return header + events


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading data...")
    with open(WORDS_PATH, "r", encoding="utf-8") as f:
        words = json.load(f)

    print(f"  {len(words)} words in timestamps, {words[-1]['end']:.1f}s total")
    print(f"  Max chars/line: {MAX_CHARS_PER_LINE}, max chars/slide: {MAX_CHARS_PER_SLIDE}")

    # Delete existing output
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()
        print(f"  Deleted existing {OUTPUT_PATH.name}")

    all_slides = []

    for si, section in enumerate(SECTIONS):
        sec_type = section["type"]
        start_t = section["start_time"]
        end_t = section["end_time"]

        if sec_type == "title":
            print(f"\n[Section {si+1}] TITLE {start_t:.1f}s-{end_t:.1f}s")
            slides = build_title_slides(words, section)
            print(f"  -> {len(slides)} title slides")
            if slides:
                print(f"     First: {slides[0]['start']:.2f}s-{slides[0]['end']:.2f}s")
                print(f"     Last:  {slides[-1]['start']:.2f}s-{slides[-1]['end']:.2f}s")
                # Show first 3 slides as preview
                for j, s in enumerate(slides[:3]):
                    preview = s['text'].replace('\\N', ' | ')
                    print(f"     [{j}] {s['start']:.2f}s-{s['end']:.2f}s: {preview[:80]}")
            all_slides.extend(slides)

        elif sec_type == "skip":
            note = section.get("note", "skipped")
            print(f"\n[Section {si+1}] SKIP {start_t:.1f}s-{end_t:.1f}s: {note}")

        elif sec_type == "bullet":
            bullet_id = section["bullet_id"]
            title = BULLETS[bullet_id]["title"]
            print(f"\n[Section {si+1}] BULLET {start_t:.1f}s-{end_t:.1f}s: \"{title}\"")
            slides = build_bullet_slides(words, bullet_id, section)
            print(f"  -> {len(slides)} bullet states")
            all_slides.extend(slides)

    # Sort all slides by start time
    all_slides.sort(key=lambda s: s["start"])

    # Global overlap fix at section boundaries
    for i in range(len(all_slides) - 1):
        if all_slides[i]["end"] > all_slides[i + 1]["start"] - 0.05:
            all_slides[i]["end"] = all_slides[i + 1]["start"] - 0.05

    # Remove zero/negative duration slides
    all_slides = [s for s in all_slides if s["end"] - s["start"] > 0.1]

    # Validate: check for overlaps
    overlap_count = 0
    for i in range(len(all_slides) - 1):
        if all_slides[i]["end"] > all_slides[i + 1]["start"] + 0.01:
            overlap_count += 1
            if overlap_count <= 5:
                print(f"  OVERLAP: slide {i} ends at {all_slides[i]['end']:.2f}s "
                      f"but slide {i+1} starts at {all_slides[i+1]['start']:.2f}s")
    if overlap_count > 0:
        print(f"  WARNING: {overlap_count} overlapping events!")
    else:
        print(f"\n  No overlapping events.")

    # Check for large gaps within title sections
    gap_count = 0
    for i in range(len(all_slides) - 1):
        gap = all_slides[i + 1]["start"] - all_slides[i]["end"]
        if gap > 0.5 and all_slides[i]["style"] == "Title" and all_slides[i + 1]["style"] == "Title":
            gap_count += 1
            if gap_count <= 5:
                print(f"  GAP: {gap:.2f}s between title slides {i} and {i+1} "
                      f"({all_slides[i]['end']:.2f}s to {all_slides[i+1]['start']:.2f}s)")
    if gap_count > 0:
        print(f"  WARNING: {gap_count} gaps > 0.5s between consecutive title slides")

    # Generate ASS
    print(f"\nTotal: {len(all_slides)} dialogue events")
    ass_content = generate_ass(all_slides)

    OUTPUT_PATH.write_text(ass_content, encoding="utf-8")
    print(f"Written: {OUTPUT_PATH}")

    # Summary by style
    title_count = sum(1 for s in all_slides if s["style"] == "Title")
    bullet_count = sum(1 for s in all_slides if s["style"] == "Bullet")
    print(f"  Title slides: {title_count}, Bullet states: {bullet_count}")

    # Duration coverage
    total_covered = sum(s["end"] - s["start"] for s in all_slides)
    total_video = words[-1]["end"]
    print(f"  Coverage: {total_covered:.1f}s / {total_video:.1f}s ({100*total_covered/total_video:.1f}%)")


if __name__ == "__main__":
    main()
