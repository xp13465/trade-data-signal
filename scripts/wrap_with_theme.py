#!/usr/bin/env python3
"""Wrap first-build setOption({...}) with withTheme(...) and delete standalone
setOption(chartThemeOpts()) that precede business setOption.

Skips setOption calls inside rethemeCharts() (those are second-update re-injections).
Operates by brace/paren counting with string & comment awareness, so it is
line-number independent and works on both web/app.js and static-site/app.js.
"""
import sys

def transform(text):
    lines = text.split("\n")
    n = len(lines)

    # Find rethemeCharts function span: from line "function rethemeCharts()" to
    # the matching closing brace at column 0.
    retheme_start = None
    for i, ln in enumerate(lines):
        if "function rethemeCharts()" in ln:
            retheme_start = i
            break
    retheme_end = None
    if retheme_start is not None:
        depth = 0
        for i in range(retheme_start, n):
            ln = lines[i]
            # naive brace count (good enough for finding function end at col 0)
            for ch in ln:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        retheme_end = i
                        break
            if retheme_end is not None:
                break

    def in_retheme(i):
        return retheme_start is not None and retheme_start <= i <= retheme_end

    # State machine to skip strings/comments while counting braces.
    def scan_setoption_blocks():
        """Return list of (open_line_idx, close_line_idx) for setOption({...}) calls
        NOT inside rethemeCharts. close_line is the line containing the final });"""
        blocks = []
        i = 0
        while i < n:
            if in_retheme(i):
                i += 1
                continue
            ln = lines[i]
            # Detect a setOption({ call on this line (first-build business option).
            # Match patterns like:  VAR.setOption({
            idx = ln.find(".setOption({")
            if idx == -1:
                i += 1
                continue
            # Find matching close by brace counting from this line, string-aware.
            depth = 0
            in_str = None  # ', ", or `
            close_idx = None
            j = i
            while j < n:
                line = lines[j]
                k = 0
                if j == i:
                    # start scanning right AFTER the '{' that opens the object
                    brace_pos = line.find("{", idx)
                    k = brace_pos + 1
                    depth = 1  # we are inside the object now
                while k < len(line):
                    ch = line[k]
                    if in_str:
                        if ch == "\\":
                            k += 2
                            continue
                        if ch == in_str:
                            in_str = None
                        k += 1
                        continue
                    # not in string
                    if ch in ("'", '"', "`"):
                        in_str = ch
                        k += 1
                        continue
                    if ch == "/" and k + 1 < len(line) and line[k+1] == "/":
                        # line comment: rest of line is comment
                        break
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            close_idx = j
                            break
                    k += 1
                if close_idx is not None:
                    break
                j += 1
            if close_idx is not None:
                blocks.append((i, close_idx))
                i = close_idx + 1
            else:
                i += 1
        return blocks

    blocks = scan_setoption_blocks()

    # Determine which standalone setOption(chartThemeOpts()) lines to delete:
    # those NOT inside rethemeCharts.
    delete_lines = set()
    for i, ln in enumerate(lines):
        if in_retheme(i):
            continue
        if ".setOption(chartThemeOpts())" in ln:
            delete_lines.add(i)

    # Apply edits on a copy, bottom-up so indices don't shift.
    out = list(lines)
    # First mark wraps (modify open & close lines), then deletes.
    # Process wraps bottom-up.
    for open_idx, close_idx in sorted(blocks, reverse=True):
        out[open_idx] = out[open_idx].replace(".setOption({", ".setOption(withTheme({", 1)
        # On close line, replace the trailing }); with }));
        cl = out[close_idx]
        # The close line looks like:  <indent>});
        # Replace last occurrence of }); with }));
        pos = cl.rfind("});")
        if pos != -1:
            out[close_idx] = cl[:pos] + "}));" + cl[pos+3:]

    # Deletes bottom-up.
    for i in sorted(delete_lines, reverse=True):
        del out[i]

    return "\n".join(out)


def main():
    for path in sys.argv[1:]:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        new_text = transform(text)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        # report
        import re
        wrap_count = new_text.count("setOption(withTheme(")
        del_count = text.count("setOption(chartThemeOpts())") - new_text.count("setOption(chartThemeOpts())")
        print(f"{path}: wrapped={wrap_count} deleted_chartThemeOpts={del_count}")

if __name__ == "__main__":
    main()
