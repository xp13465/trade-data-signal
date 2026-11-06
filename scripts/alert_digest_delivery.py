"""Pure digest framing helpers; no configuration, I/O, or notification side effects."""
import hashlib
import json
from collections import Counter

MAX_REQUEST_BYTES = 16 * 1024
MAX_ROWS = 80
TITLE_BYTES = 240


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def signature(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def request_sizes(post, chat_id=""):
    """Match notify's UTF-8 webhook and double-serialized app request bodies."""
    content = json.dumps(post, ensure_ascii=False)
    app = {"receive_id": chat_id, "msg_type": "post", "content": content}
    hook = {"msg_type": "post", "content": {"post": post}}
    return tuple(len(json.dumps(v, ensure_ascii=False).encode("utf-8")) for v in (app, hook))


def split_posts(subject, lines, chat_id="", max_rows=MAX_ROWS):
    """Frame all text without truncation; oversize rows split at codepoint boundaries.

    The concatenation of text nodes equals the concatenation of input lines. Newline
    characters are retained in nodes, including those inside giant logical rows.
    Title overflow is prepended to the body; the subject passed to send stays intact.
    """
    title = ""
    for char in subject:
        if len((title + char).encode("utf-8")) > TITLE_BYTES:
            break
        title += char
    source = list(lines)
    if title != subject:
        source.insert(0, subject[len(title):] + "\n")
    # Reserve the largest possible ordinal (at most one part per codepoint/row).
    bound = max(1, sum(max(1, len(line)) for line in source))
    reserved_title = f"{title} {bound}/{bound}"

    def post(rows, heading=reserved_title):
        return {"zh_cn": {"title": heading, "content": [[{"tag": "text", "text": t}] for t in rows]}}

    def fits(rows):
        return len(rows) <= max_rows and max(request_sizes(post(rows), chat_id)) <= MAX_REQUEST_BYTES

    groups, rows = [], []
    for line in source:
        remaining = line
        while True:
            if fits(rows + [remaining]):
                rows.append(remaining)
                break
            if rows:
                groups.append(rows)
                rows = []
                continue
            lo, hi = 0, len(remaining)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fits([remaining[:mid]]):
                    lo = mid
                else:
                    hi = mid - 1
            if not lo:
                raise ValueError("digest request envelope exceeds byte budget")
            groups.append([remaining[:lo]])
            remaining = remaining[lo:]
            if not remaining:
                break
    if rows:
        groups.append(rows)
    return [post(group, title if len(groups) == 1 else f"{title} {i}/{len(groups)}")
            for i, group in enumerate(groups, 1)]


def remove_snapshot(current, snapshot):
    """Multiset subtraction by FULL contents, retaining changed hits and new arrivals."""
    counts = Counter(canonical(entry) for entry in snapshot)
    kept = []
    for entry in current:
        key = canonical(entry)
        if counts[key]:
            counts[key] -= 1
        else:
            kept.append(entry)
    return kept


def validate_pending(pending):
    """Reject malformed journals before sends or destructive cleanup."""
    from html import unescape

    def require(condition, detail):
        if not condition:
            raise ValueError(f"invalid digest pending: {detail}")

    require(isinstance(pending, dict), "object")
    require(type(pending.get('version')) is int and pending['version'] == 1, "version")
    entries = pending.get('entries')
    require(isinstance(entries, list) and bool(entries) and all(isinstance(e, dict) for e in entries), "entries")
    require(type(pending.get('n')) is int and 0 <= pending['n'] <= len(entries), "n")
    require(all(isinstance(pending.get(k), str) for k in ('subject', 'body', 'signature', 'route_hash', 'parts_signature')), "strings")
    lines = pending.get('lines')
    require(isinstance(lines, list) and bool(lines) and all(isinstance(line, str) for line in lines), "lines")
    require(pending['signature'] == signature([entries, pending['subject'], pending['body'], lines, pending['n']]), "frozen signature")
    require(''.join(lines) == unescape(pending['body'].replace('<br>', '\n')), "body/lines coverage")
    parts = pending.get('parts')
    require(isinstance(parts, list) and bool(parts), "parts")
    require(pending['parts_signature'] == signature([pending['signature'], parts]), "parts signature")
    text = []
    for part in parts:
        require(isinstance(part, dict) and isinstance(part.get('zh_cn'), dict), "post object")
        zh = part['zh_cn']
        require(isinstance(zh.get('title'), str), "post title")
        rows = zh.get('content')
        require(isinstance(rows, list) and 0 < len(rows) <= MAX_ROWS, "post rows")
        for row in rows:
            require(isinstance(row, list) and len(row) == 1, "post row")
            node = row[0]
            require(isinstance(node, dict) and set(node) == {'tag', 'text'} and node['tag'] == 'text' and isinstance(node['text'], str), "plain text node")
            text.append(node['text'])
    title = ''
    for char in pending['subject']:
        if len((title + char).encode('utf-8')) > TITLE_BYTES:
            break
        title += char
    overflow = pending['subject'][len(title):] + '\n' if title != pending['subject'] else ''
    require(''.join(text) == overflow + ''.join(lines), "parts text coverage")
    confirmed = pending.get('confirmed_parts')
    require(isinstance(confirmed, list) and all(type(i) is int and 0 <= i < len(parts) for i in confirmed), "receipt indexes")
    require(len(set(confirmed)) == len(confirmed), "duplicate receipt indexes")
    require(all(type(pending.get(k)) is bool for k in ('feishu_required', 'other_attempted', 'first_attempted', 'complete')), "receipt flags")
    other = pending.get('other_success')
    require(isinstance(other, dict) and set(other) == {'email', 'telegram'} and all(type(v) is bool for v in other.values()), "other channel receipts")
    require(not any(other.values()) or pending['other_attempted'], "attempt receipt")
    require(not (confirmed or any(other.values())) or pending['first_attempted'], "logical count receipt")
    all_parts = len(confirmed) == len(parts)
    complete = all_parts if pending['feishu_required'] else (all_parts or any(other.values()))
    require(not pending['complete'] or complete, "incomplete success receipts")
