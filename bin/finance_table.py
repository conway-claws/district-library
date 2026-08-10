"""Layout-preserving extraction for the district's monthly financial reports.

The reports are born-digital Excel PDFs whose tables collapse under flow-order
extraction (figures glom into one cell, labels into another). `pdftotext -layout`
keeps the column geometry, so every figure reads on the same line as its label —
the property an agent needs to answer "what was state revenue in August". The
output is the layout text in fenced blocks, one per page, not a reconstructed
markdown table: reconstruction is where the mis-mapping risk lives.
"""

import re
import subprocess
import tempfile

MARKER = ("<!-- finance report: pdftotext -layout extraction; monospace columns "
          "preserved so every figure reads on the same line as its label -->")


def extract(data):
    """Markdown for a finance PDF, or None when the result fails validation."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(data)
        tf.flush()
        try:
            proc = subprocess.run(["pdftotext", "-layout", tf.name, "-"],
                                  capture_output=True, timeout=120)
        except FileNotFoundError:
            return None  # no poppler on this machine; caller falls back to anydoc
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", errors="replace")
    if not _valid(text):
        return None
    pages = [p.rstrip() for p in text.split("\f") if p.strip()]
    body = "\n\n".join(f"```text\n{p}\n```" for p in pages)
    return f"{MARKER}\n\n{body}\n"


def _valid(text):
    """At least 5 figure lines, and ≥90% of them carry a label on the same line.

    A layout collapse decouples figures from labels (lines that are only dollar
    amounts); that is the failure this guard exists to catch.
    """
    figure_lines = labeled = 0
    for line in text.splitlines():
        if not re.search(r"\$\s*\(?[\d,.-]", line):
            continue
        figure_lines += 1
        prefix = line.split("$", 1)[0]
        if len(re.sub(r"[^a-zA-Z]", "", prefix)) >= 3:
            labeled += 1
    if figure_lines < 5:
        return False
    return labeled / figure_lines >= 0.9
