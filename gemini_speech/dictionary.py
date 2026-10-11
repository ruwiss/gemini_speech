import re


def normalize(entries):
    """Pairs of (match, replacement). A later pair replaces an earlier match that differs only by case."""
    pairs = []
    for match, replacement in _pairs(entries):
        for index, (existing, _) in enumerate(pairs):
            if re.fullmatch(re.escape(existing), match, re.IGNORECASE):
                pairs[index] = (match, replacement)
                break
        else:
            pairs.append((match, replacement))
    return pairs


def same(left, right):
    return re.fullmatch(re.escape(left), right, re.IGNORECASE) is not None


def dump(pairs):
    return [{"match": match, "replace": replacement} for match, replacement in pairs]


def apply(text, pairs):
    """Replace whole matches. The match ignores case. The replacement is written as stored."""
    pairs = normalize(pairs)
    if not text or not pairs:
        return text
    ordered = sorted(pairs, key=lambda item: len(item[0]), reverse=True)
    pattern = re.compile(
        r"(?<!\w)(?:%s)(?!\w)" % "|".join(re.escape(match) for match, _ in ordered),
        re.IGNORECASE,
    )

    def replace(found):
        chunk = found.group()
        for match, replacement in ordered:
            if re.fullmatch(re.escape(match), chunk, re.IGNORECASE):
                return replacement
        return chunk

    return pattern.sub(replace, text)


def _pairs(entries):
    for item in entries or []:
        match = ""
        replacement = ""
        if isinstance(item, str):
            match = replacement = item
        elif isinstance(item, dict):
            match = str(item.get("match") or "")
            replacement = item.get("replace")
            if replacement is None:
                replacement = item.get("to") or ""
            replacement = str(replacement)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            match = str(item[0])
            replacement = str(item[1])
        match = " ".join(match.split())
        replacement = " ".join(replacement.split())
        if match and replacement:
            yield match, replacement
