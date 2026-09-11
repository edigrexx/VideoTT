import textwrap
from pathlib import Path


def ass_time(seconds):
    centiseconds = max(0, round(seconds * 100))
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{cs:02}"


def escape_ass(text):
    # Fullwidth substitutions preserve readability without allowing ASS override injection.
    return (
        text.replace("\\", "／").replace("{", "｛").replace("}", "｝").replace("\n", " ").replace("\r", " ")
    )


def write_subtitles(cues, duration: float, path: Path, is_test=False):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,DejaVu Sans,66,&H00FFFFFF,&H0000D7FF,&H00151515,&H90000000,-1,0,0,0,100,100,0,0,1,5,2,2,130,170,430,1
Style: Test,DejaVu Sans,38,&H0000FFFF,&H0000FFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,3,2,0,8,90,90,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    groups, group = [], []
    for cue in cues:
        proposed = " ".join(c.text for c in [*group, cue])
        if group and (len(group) >= 5 or len(proposed) > 42 or cue.start - group[-1].end > 0.45):
            groups.append(group)
            group = []
        group.append(cue)
        if cue.text.endswith((".", "?", "!", ";")):
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    lines = []
    for i, group in enumerate(groups):
        start = group[0].start
        limit = groups[i + 1][0].start if i + 1 < len(groups) else duration
        end = min(limit, max(group[-1].end + 0.12, start + 0.25))
        wrapped = textwrap.wrap(escape_ass(" ".join(c.text for c in group)), width=24)
        text = r"\N".join(wrapped)
        size_tag = r"{\fs50}" if len(wrapped) > 2 else ""
        if len(wrapped) > 2:
            text = r"\N".join(textwrap.wrap(escape_ass(" ".join(c.text for c in group)), width=32))
        animation = r"{\fad(65,65)\fscx103\fscy103\t(0,110,\fscx100\fscy100)}"
        lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{size_tag}{animation}{text}"
        )
    if is_test:
        lines.append(
            f"Dialogue: 1,0:00:00.00,{ass_time(duration)},Test,,0,0,0,,TEST FIXTURE — SYNTHETIC VIDEO + TONE"
        )
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
