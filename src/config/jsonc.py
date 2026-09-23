"""JSON with // comments, for settings.json.

Comments are not preserved from the file. render() re-applies them from the
template, so they cannot drift from what the app writes.
"""

import json


def strip_comments(text: str) -> str:
    """Remove // line comments. String-aware: a value may contain //."""
    out = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and text[i + 1:i + 2] == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def loads(text: str):
    """json.loads, tolerating comments and a trailing comma."""
    stripped = strip_comments(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return json.loads(_drop_trailing_commas(stripped))


def _drop_trailing_commas(text: str) -> str:
    out = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            continue
        if ch == ",":
            rest = text[i + 1:].lstrip()
            if rest[:1] in ("}", "]"):
                continue
        out.append(ch)
    return "".join(out)


def value_spans(text: str) -> dict:
    """Where each top-level key's value starts and ends, by character offset."""
    spans = {}
    depth = 0
    in_string = False
    escaped = False
    key_start = 0
    pending_key = None
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
                if depth == 1 and pending_key is None:
                    pending_key = text[key_start:i]
            i += 1
            continue
        if ch == "/" and text[i + 1:i + 2] == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if ch == '"':
            in_string = True
            escaped = False
            key_start = i + 1
            i += 1
            continue
        if ch == ":" and depth == 1 and pending_key is not None:
            start = i + 1
            while start < len(text) and text[start] in " \t\n":
                start += 1
            end = _end_of_value(text, start)
            spans[pending_key] = [start, end]
            pending_key = None
            i = end
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    return spans


def _end_of_value(text: str, start: int) -> int:
    """One past the last character of the value beginning at start."""
    ch = text[start]
    if ch in "{[":
        closing = {"{": "}", "[": "]"}[ch]
        depth = 0
        in_string = False
        escaped = False
        i = start
        while i < len(text):
            c = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    in_string = False
            elif c == '"':
                in_string = True
            elif c == ch:
                depth += 1
            elif c == closing:
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return len(text)
    if ch == '"':
        i = start + 1
        escaped = False
        while i < len(text):
            c = text[i]
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                return i + 1
            i += 1
        return len(text)
    i = start
    while i < len(text) and text[i] not in ",\n":
        i += 1
    return i


def render(template: str, values: dict, indent: int = 2) -> str:
    """The template with each value replaced by the one in hand.

    Comments, order and layout come from the template. Keys it does not mention
    are appended before the closing brace.
    """
    spans = value_spans(template)
    out = template
    for key in sorted(spans, key=lambda k: spans[k][0], reverse=True):
        if key not in values:
            continue
        start, end = spans[key]
        text = json.dumps(values[key], indent=indent)
        text = text.replace("\n", "\n" + " " * indent)
        out = out[:start] + text + out[end:]

    extra = {k: v for k, v in values.items() if k not in spans}
    if extra:
        lines = []
        for k, v in extra.items():
            text = json.dumps(v, indent=indent).replace("\n", "\n" + " " * indent)
            lines.append(f'{" " * indent}"{k}": {text}')
        closing = out.rstrip().rfind("}")
        head = out[:closing].rstrip()
        if not head.rstrip().endswith("{"):
            head += ","
        block = (f"\n{' ' * indent}// Not known to this version.\n"
                 + ",\n".join(lines))
        out = head + block + "\n}\n"
    return out
