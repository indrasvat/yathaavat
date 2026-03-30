from __future__ import annotations

import re

from yathaavat.core.session import (
    BreakMode,
    ExceptionInfo,
    ExceptionNode,
    ExceptionRelation,
    TracebackFrame,
)

_FRAME_RE = re.compile(
    r'^\s*File "(?P<path>.+?)", line (?P<line>\d+), in (?P<name>.+)$',
    re.MULTILINE,
)

_EXCEPTION_LINE_RE = re.compile(
    r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Group|Interrupt|Exit"
    r"|KeyboardInterrupt|StopIteration|StopAsyncIteration|GeneratorExit"
    r"|SystemExit|BaseException))"
    r"(?::?\s*(?P<message>.*))?$",
    re.MULTILINE,
)

_CAUSE_MARKER = "\nThe above exception was the direct cause of the following exception:\n"
_CONTEXT_MARKER = "\nDuring handling of the above exception, another exception occurred:\n"

_GROUP_HEADER_RE = re.compile(r"\+\s*Exception Group Traceback")
_GROUP_SEP_RE = re.compile(r"^\s*\+[-+─]*[-─]+\s*(\d+)\s*[-─]+\s*$", re.MULTILINE)


def build_exception_tree(
    exception_id: str,
    description: str,
    break_mode: BreakMode,
    stack_trace: str,
) -> ExceptionInfo:
    fallback = ExceptionNode(type_name=exception_id, message=description)
    try:
        tree = _parse_stack_trace(exception_id, description, stack_trace)
    except Exception:
        tree = fallback
    # If parsing produced a generic result, prefer the DAP-provided metadata.
    if tree.type_name == "Exception" and tree.message == "" and exception_id != "Exception":
        tree = ExceptionNode(
            type_name=exception_id,
            message=description,
            frames=tree.frames,
            children=tree.children,
            relation=tree.relation,
            is_group=tree.is_group,
        )
    return ExceptionInfo(
        exception_id=exception_id,
        break_mode=break_mode,
        stack_trace=stack_trace,
        tree=tree,
    )


def parse_traceback_frames(text: str) -> tuple[TracebackFrame, ...]:
    frames: list[TracebackFrame] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _FRAME_RE.match(line)
        if m is None:
            continue
        source_text: str | None = None
        if i + 1 < len(lines):
            candidate = lines[i + 1].strip()
            if candidate and not _FRAME_RE.match(lines[i + 1]):
                source_text = candidate
        frames.append(
            TracebackFrame(
                path=m.group("path"),
                line=int(m.group("line")),
                name=m.group("name"),
                text=source_text,
            )
        )
    return tuple(frames)


def _parse_stack_trace(exception_id: str, description: str, stack_trace: str) -> ExceptionNode:
    if not stack_trace.strip():
        return ExceptionNode(type_name=exception_id, message=description)

    if _GROUP_HEADER_RE.search(stack_trace):
        return _parse_group(stack_trace)

    if _CAUSE_MARKER in stack_trace or _CONTEXT_MARKER in stack_trace:
        return _parse_chained(stack_trace)

    return _parse_simple(stack_trace)


def _parse_simple(text: str) -> ExceptionNode:
    frames = parse_traceback_frames(text)
    type_name, message = _extract_exception_line(text)
    return ExceptionNode(type_name=type_name, message=message, frames=frames)


def _extract_exception_line(text: str) -> tuple[str, str]:
    for line in reversed(text.strip().splitlines()):
        stripped = line.strip().lstrip("| ")
        m = _EXCEPTION_LINE_RE.match(stripped)
        if m:
            return m.group("type"), (m.group("message") or "").strip()
    return "Exception", ""


def _parse_chained(text: str) -> ExceptionNode:
    # Split on both chain markers to handle tracebacks with mixed __cause__ and __context__.
    segments: list[tuple[str, ExceptionRelation]] = []
    _split_on_chain_markers(text, segments)

    if not segments:
        return _parse_simple(text)

    # The last segment is the primary (root) exception, earlier ones are causes.
    # Build from the innermost cause outward.
    root_text, _root_rel = segments[-1]
    root = _parse_simple(root_text)

    children: list[ExceptionNode] = []
    for seg_text, rel in segments[:-1]:
        node = _parse_simple(seg_text)
        children.append(
            ExceptionNode(
                type_name=node.type_name,
                message=node.message,
                frames=node.frames,
                children=node.children,
                relation=rel,
                is_group=node.is_group,
            )
        )

    return ExceptionNode(
        type_name=root.type_name,
        message=root.message,
        frames=root.frames,
        children=tuple(children),
        relation=ExceptionRelation.ROOT,
        is_group=root.is_group,
    )


def _split_on_chain_markers(text: str, out: list[tuple[str, ExceptionRelation]]) -> None:
    """Split text on both __cause__ and __context__ markers, preserving which marker
    separated each segment. This handles tracebacks with mixed chain types."""
    cause_pos = text.find(_CAUSE_MARKER)
    context_pos = text.find(_CONTEXT_MARKER)

    if cause_pos < 0 and context_pos < 0:
        out.append((text, ExceptionRelation.ROOT))
        return

    # Find the first marker.
    if cause_pos >= 0 and (context_pos < 0 or cause_pos < context_pos):
        before = text[:cause_pos]
        after = text[cause_pos + len(_CAUSE_MARKER) :]
        out.append((before, ExceptionRelation.CAUSE))
    else:
        before = text[:context_pos]
        after = text[context_pos + len(_CONTEXT_MARKER) :]
        out.append((before, ExceptionRelation.CONTEXT))

    # Recurse on the remainder (may contain more markers).
    _split_on_chain_markers(after, out)


def _parse_group(text: str) -> ExceptionNode:
    # Strip leading pipe/space prefixes that CPython adds to ExceptionGroup tracebacks.
    lines = text.splitlines()

    # Find the ExceptionGroup header line (e.g. "ExceptionGroup: message (N sub-exceptions)")
    group_type = "ExceptionGroup"
    group_message = ""
    header_frames: list[str] = []
    header_ended = False

    for line in lines:
        stripped = line.strip().lstrip("| +")
        if not header_ended:
            if _FRAME_RE.match(stripped) or stripped.startswith("File "):
                header_frames.append(line)
            eg_match = re.match(r"((?:Base)?ExceptionGroup):\s*(.+)", stripped)
            if eg_match:
                group_type = eg_match.group(1)
                group_message = eg_match.group(2).strip()
                header_ended = True

    frames = parse_traceback_frames("\n".join(header_frames))

    # Parse sub-exceptions by splitting on separator lines
    child_blocks = _split_group_children(text)
    children: list[ExceptionNode] = []
    for block in child_blocks:
        block_stripped = block.strip()
        if not block_stripped:
            continue
        # Clean pipe prefixes
        clean = _strip_pipe_prefix(block)
        # Detect nested groups: either has the full header or has group separators
        has_group_header = bool(_GROUP_HEADER_RE.search(clean))
        has_group_seps = bool(_GROUP_SEP_RE.search(clean))
        if has_group_header or has_group_seps:
            child = _parse_group(clean)
        else:
            child = _parse_simple(clean)
        children.append(
            ExceptionNode(
                type_name=child.type_name,
                message=child.message,
                frames=child.frames,
                children=child.children,
                relation=ExceptionRelation.GROUP_MEMBER,
                is_group=child.is_group,
            )
        )

    return ExceptionNode(
        type_name=group_type,
        message=group_message,
        frames=frames,
        children=tuple(children),
        relation=ExceptionRelation.ROOT,
        is_group=True,
    )


def _split_group_children(text: str) -> list[str]:
    lines = text.splitlines()
    children: list[str] = []
    current: list[str] = []
    depth = 0
    in_child = False

    for line in lines:
        normalized = re.sub(r"^\s*(?:\|\s?)*", "", line)

        # Check for nested group start: +-+ prefix (increases depth)
        is_nested_open = bool(re.match(r"\+-\+[-─]+\s*\d+\s*[-─]+", normalized))
        # Check for numbered separator at current depth
        is_sep = bool(_GROUP_SEP_RE.match(normalized))
        # Check for closing rule (just dashes, no number)
        is_close = bool(re.match(r"^\+[-─]+\s*$", normalized))

        if is_nested_open and depth == 0 and not in_child:
            # First child of top-level group
            in_child = True
            continue

        if is_sep and not is_nested_open and depth == 0:
            # Top-level separator between children
            if in_child and current:
                children.append("\n".join(current))
                current = []
            in_child = True
            continue

        if is_nested_open and depth >= 0 and in_child:
            # Entering a nested group within a child block
            depth += 1
            current.append(line)
            continue

        if is_close and in_child:
            if depth > 0:
                depth -= 1
                current.append(line)
                continue
            # Top-level closing rule
            if current:
                children.append("\n".join(current))
                current = []
            in_child = False
            continue

        if in_child:
            current.append(line)

    if current:
        children.append("\n".join(current))

    return children


def _strip_pipe_prefix(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    for line in lines:
        # Remove leading whitespace + pipe + optional space
        cleaned = re.sub(r"^\s*\|\s?", "", line)
        result.append(cleaned)
    return "\n".join(result)
