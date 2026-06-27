"""
Fix: inside main.py's f-string template, ALL CSS curly braces must be doubled.
The SETUP_CSS (Phase 1) and PHASE2_CSS (Phase 2) were inserted with single { }
which Python evaluates as f-string variable references -> NameError at render time.

Strategy: scan the <style> block, collect single { } that aren't already doubled,
and double them using a placeholder swap so we don't double-double existing {{ }}.
"""
import sys, re
sys.stdout.reconfigure(encoding="utf-8")

with open("backend/main.py", "r", encoding="utf-8") as f:
    content = f.read()

# ── Locate the FIRST <style> ... </style> block ───────────────────────────────
style_start = content.find("<style>")
style_end   = content.find("</style>", style_start)
assert style_start != -1 and style_end != -1, "style block not found"

style_block = content[style_start:style_end]

# ── Escape single { } in the style block without touching existing {{ }} ──────
# Step 1: protect already-doubled braces with placeholders
PH_OPEN  = "\x00DBLOPEN\x00"
PH_CLOSE = "\x00DBLCLOSE\x00"

fixed = style_block
fixed = fixed.replace("{{", PH_OPEN)
fixed = fixed.replace("}}", PH_CLOSE)

# Step 2: double all remaining single braces
fixed = fixed.replace("{", "{{")
fixed = fixed.replace("}", "}}")

# Step 3: restore doubled-brace placeholders
fixed = fixed.replace(PH_OPEN,  "{{")
fixed = fixed.replace(PH_CLOSE, "}}")

# ── Verify no single braces remain (except in already-safe {{ }} pairs) ───────
# Count single vs double braces
single_open  = len(re.findall(r"(?<!\{)\{(?!\{)", fixed))
single_close = len(re.findall(r"(?<!\})\}(?!\})", fixed))
print(f"Remaining single braces after fix: open={single_open} close={single_close}")

# ── Rebuild content ───────────────────────────────────────────────────────────
content = content[:style_start] + fixed + content[style_end:]

with open("backend/main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("DONE — CSS braces escaped")
