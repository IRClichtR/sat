from src.pyconf import Reference, Expression, DOLLAR, DOT, LBRACK, PLUS, WORDCHARS, Config

class TemplateError(Exception):
    pass


# --- phase 1: scanning -------------------------------------------------------
# Pure string work. Knows nothing about pyconf, configuration or resolution.
# Produces the parts list: an ordered list of (tag, content) pairs in which the
# syntax is gone -- no '$', no braces, escapes already resolved -- and no pyconf
# object has appeared yet.

LITERAL = "lit"
REF = "ref"


def scan(text: str) -> list:
    """
    Split text into an ordered list of (tag, content) parts.

    '$$' collapses to a single '$' and never opens a template; '${' opens one
    and must be closed by the next '}'. Empty literals are never emitted and
    neighbouring literals are merged, so the builder never sees a degenerate
    part.
    """
    parts = []
    literal = []
    i = 0
    end = len(text)

    def flush():
        if literal:
            parts.append((LITERAL, "".join(literal)))
            del literal[:]

    while i < end:
        if text[i] == '$' and text[i + 1:i + 2] == '$':
            literal.append('$')
            i += 2
        elif text[i] == '$' and text[i + 1:i + 2] == '{':
            close = text.find('}', i + 2)
            if close < 0:
                raise TemplateError(
                    "unterminated ${ at position %d in %r" % (i, text))
            name = text[i + 2:close]
            if not name:
                raise TemplateError(
                    "empty reference ${} at position %d in %r" % (i, text))
            flush()
            parts.append((REF, name))
            i = close + 1
        else:
            literal.append(text[i])
            i += 1

    flush()
    return parts


# The path grammar -- a second, smaller language living inside a REF part.
# Mirrors pyconf's own parseReference/parseSuffix (src/pyconf.py:1489): a name,
# then any number of '.name' or '[subscript]' steps. DOT and LBRACK are pyconf
# token types, not characters, and are used here only to tag the steps so the
# builder can hand them straight to Reference.addElement.

DIGITS = "0123456789"
IDENTCHARS = WORDCHARS + DIGITS


def _parse_name(path: str, pos: int) -> tuple:
    """Read one identifier. Return (name, position after it)."""
    start = pos
    if pos < len(path) and path[pos] in WORDCHARS:
        pos += 1
        while pos < len(path) and path[pos] in IDENTCHARS:
            pos += 1
    if pos == start:
        raise TemplateError(
            "expected a name at position %d in path %r" % (start, path))
    return path[start:pos], pos


def _parse_subscript(path: str, pos: int) -> tuple:
    """Read one subscript body, the '[' already consumed.

    A quoted string yields str, a run of digits yields int -- the same two kinds
    pyconf's parseSuffix accepts. The first ']' closes, so a ']' inside a quoted
    key is not supported; the corpus has none.
    """
    close = path.find(']', pos)
    if close < 0:
        raise TemplateError(
            "unterminated '[' at position %d in path %r" % (pos - 1, path))
    raw = path[pos:close]
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        key = raw[1:-1]
    elif raw.isdigit():
        key = int(raw)
    else:
        raise TemplateError(
            "subscript must be a quoted string or a number, found %r at "
            "position %d in path %r" % (raw, pos, path))
    return key, close + 1


def split_path(path: str) -> tuple:
    """
    Split a reference path into (head_name, steps).

    steps is a list of (token_type, name) pairs, token_type being DOT or LBRACK,
    shaped so the builder can do Reference(config, DOLLAR, head) followed by one
    addElement(*step) per entry.

        'name'                -> ('name', [])
        'APPLICATION.workdir' -> ('APPLICATION', [(DOT, 'workdir')])
        'A["x"]'              -> ('A', [(LBRACK, 'x')])
    """
    head, pos = _parse_name(path, 0)
    steps = []
    while pos < len(path):
        if path[pos] == '.':
            name, pos = _parse_name(path, pos + 1)
            steps.append((DOT, name))
        elif path[pos] == '[':
            key, pos = _parse_subscript(path, pos + 1)
            steps.append((LBRACK, key))
        else:
            raise TemplateError(
                "expected '.' or '[' at position %d in path %r" % (pos, path))
    return head, steps


# --- phase 2: building -------------------------------------------------------
# Knows pyconf's object model. Knows nothing about '$', braces or escapes: every
# syntax question was already answered by scan(). Nothing here resolves or
# evaluates -- that needs a container and a parent chain, neither of which
# exists yet.


def _build_reference(path: str, config) -> Reference:
    """Turn one REF part's raw text into a pyconf Reference."""
    head, steps = split_path(path)
    ref = Reference(config, DOLLAR, head)
    for step_type, step_name in steps:
        ref.addElement(step_type, step_name)
    return ref


def contains_template(text: str) -> bool:
    """
    True if text holds at least one ${...} once escapes are resolved.

    Derived from scan() rather than looking for characters, so there is exactly
    one authority on what a template is. An unterminated ${ raises here too.
    """
    return any(tag == REF for tag, _ in scan(text))


def parse_template(text: str, config: Config) -> object:
    """
    Turn a TOML string into plain text, a Reference, or an Expression.

    no reference parts   -> str
    one part, a REF      -> Reference
    anything else        -> a left-associative chain of Expression(PLUS, ...)
    """
    parts = scan(text)

    if not any(tag == REF for tag, _ in parts):
        return "".join(content for _, content in parts)

    if len(parts) == 1:
        return _build_reference(parts[0][1], config)

    operands = [_build_reference(content, config) if tag == REF else content
                for tag, content in parts]
    expression = operands[0]
    for operand in operands[1:]:
        expression = Expression(PLUS, expression, operand)
    return expression
