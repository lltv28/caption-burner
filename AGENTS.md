# Caption Burner — LLM Instructions

## Overview

Caption Burner generates styled title slides and bullet slides burned onto video with perfect audio sync. It uses word-level timestamps from faster-whisper to match captions to speech.

## Two Modes

### 1. Title Slides (`burn.py`)
Centered text captions synced to audio. For simple videos with no bullet sections.

```bash
# Full pipeline: transcribe + burn
python burn.py --video input.mp4 --script script.txt --transcribe --output output.mp4

# Re-render with existing word timestamps (fast)
python burn.py --video input.mp4 --script script.txt --words words.json --output output.mp4
```

### 2. Mixed Title + Bullet Slides (`build_latter.py` + `render_sections.py`)
For videos with both regular captions and bullet-point sections. Requires manual configuration of section boundaries and bullet definitions.

```bash
# 1. Transcribe video to get word timestamps
python -c "..." # (see burn.py --transcribe for the transcription code)

# 2. Configure build_latter.py with section boundaries and bullet definitions
# 3. Build the ASS file
python build_latter.py

# 4. Render individual sections
python render_sections.py
```

## Caption Generation Rules

### Text Source
- **Always use transcript text** (from word timestamps), not the script text
- Each slide's timing comes directly from its words' start/end timestamps
- This gives perfect audio sync — no proportional mapping, no drift

### Slide Layout
- **Font**: Instrument Sans Bold (static .ttf extracted from variable font at weight 700)
- **Title slides**: 120pt, centered (ASS alignment 5), up to 3 lines
- **Bullet slides**: 70pt body / 100pt title, top-left (ASS alignment 7)
- **Background**: `captions-bg.png` (or custom via `--bg-image`)
- **Max characters per line**: `int(1720 / (font_size * 0.55))` — at 120pt this is ~26 chars
- **Max lines per slide**: 3

### Line Splitting
- Split slides into up to 3 balanced lines
- Prefer splitting at punctuation (`.`, `,`, `!`, `?`, `;`, `:`) — score bonus of -10 to -15
- Minimum 2 words per line when splitting
- Minimize line length imbalance

### Sentence Boundaries
- Slides MUST end at sentence boundaries (`.`, `!`, `?`) when possible
- If a slide hits a sentence end and has >20 chars and >=3 words, end the slide there
- Trailing incomplete sentences at section edges are trimmed
- Never cut off mid-sentence at a section boundary

### Text Cleanup Rules
- Capitalize first word only at sentence starts (not every slide)
- `i` → `I` at word boundaries
- `ai` → `AI` as standalone word
- Spelled-out numbers → numeric: `two` → `2`, `fifty` → `50`, `ninety` → `90`, etc.
- Join `%` with preceding number: `90 %` → `90%`
- Join whisper-split compounds: `high` + `-ticket` → `high-ticket`, `done` + `-for` → `done-for`
- Join split numbers: `$6` + `,000.` → `$6,000.`

### Whisper Hallucination Filtering
- Remove zero-duration words (start == end)
- Remove rapid-fire burst clusters: 3+ consecutive words where each gap < 0.08s and duration < 0.15s
- These are phantom text whisper generates without actual audio

### Timing
- 50ms gap between consecutive title slides
- Each slide's start = first word's start time, end = last word's end time
- Minimum slide duration: 0.5s

## Bullet Slides

### Structure
- Title line at `{\fs100}` with section heading
- Blank `\N` for spacing
- Bullet items at `{\fs70}` prefixed with `•  `
- Progressive reveal: each state is a cumulative non-overlapping dialogue event

### Rules
- First bullet shows **immediately** at section start (no blank screen delay)
- Each subsequent bullet appears when the speaker says its key phrase
- The final state (all bullets) stays on screen until the section ends
- Trigger timestamps come from searching word-level JSON for key phrases in each bullet
- Non-overlapping events: state N ends when state N+1 begins

### Example ASS Events
```
Dialogue: 0,0:02:01.00,0:02:23.00,Bullet,,0,0,0,,{\fs100}The Kodara Flagship System\N\N{\fs70}•  Full done-for-you AI build out
Dialogue: 0,0:02:23.00,0:02:37.00,Bullet,,0,0,0,,{\fs100}The Kodara Flagship System\N\N{\fs70}•  Full done-for-you AI build out\N•  Fully custom marketing plan
```

## Section-Based Rendering

For long videos (>3 minutes), divide into sections at known boundaries (bullet sections are natural dividers). This prevents timing drift.

### Per-Section Process
1. Extract word timestamps for the section's time range
2. Generate slides using only those words
3. Create a separate ASS file with timestamps shifted to start at 0
4. Render with `ffmpeg -ss <start> -t <duration>` + the shifted ASS

### Section Types
- **title**: Regular centered captions from transcript words
- **bullet**: Progressive reveal with manual trigger timestamps
- **skip**: No captions (for off-script sections to edit later)

## ASS Styles

```
Style: Title,Instrument Sans Bold,120,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,100,100,40,1
Style: Bullet,Instrument Sans Bold,70,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,150,100,200,1
```

Key parameters: BorderStyle=1, Outline=0, Shadow=0. Do NOT use BorderStyle=3 (causes double rendering with variable fonts).

## FFmpeg Rendering

### With background image
```
ffmpeg -y -i video.mp4 -loop 1 -i bg.png \
  -filter_complex "[1:v]scale=1920:1080[bg];[bg]ass='subtitle.ass':fontsdir='fonts_dir'[v]" \
  -map "[v]" -map "0:a" -c:v libx264 -preset medium -crf 18 -c:a copy -shortest output.mp4
```

### Important
- Always pass `fontsdir` pointing to the directory containing `InstrumentSans-Bold.ttf`
- Delete the ASS file after burning to prevent video players from auto-loading it as a soft subtitle (causes double text at different sizes)
- Escape Windows paths in ASS filter: backslashes → forward slashes, colons → `\:`

## Dependencies
- Python 3.11+
- FFmpeg with libass support
- faster-whisper (for transcription)
- fonttools (only needed to re-extract static font from variable font)
