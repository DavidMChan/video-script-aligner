import json
import logging
import re


def _filter_and_transform_lines(lines: list):
    for line in lines:
        line = line.replace("\t", "    ")  # Replace tabs with spaces

        # If the line starts with a scene identifier, then replace ONLY the identifer with spaces
        # Scene identifiers match [A-Z]?\d+\s
        match = re.match(r"([A-Z]?\d+(pt)?\s)", line)
        if match:
            line = line.replace(match.group(1), " " * len(match.group(1)))

        # Now check to see if the line is (MORE), (CONTINUED) etc.
        if line.strip().upper() in ("(MORE)", "(CONT'D)", "(CONTINUED)"):
            continue
        if re.match(r"CONTINUED: \(\d+\)", line.strip()):
            continue
        if re.match(r"Revision\s+\d+.", line.strip()):
            continue

        yield line


def _read_script(script_path: str) -> (list, int, int):
    # Return a list of lines, and the width of the script.
    with open(script_path) as f:
        script_lines = list(_filter_and_transform_lines(f.readlines()))

    script_width = max(len(line) for line in script_lines)
    script_indent = min(len(line) - len(line.lstrip()) for line in script_lines)

    return script_lines, script_width, script_indent


def _line_length(line: str, script_width: int) -> int:
    # Return the length of the line, including whitespace at the end.
    # If the line is shorter than the script, pad it with whitespace.
    return len(line) + (script_width - len(line))

def _autoset_ltol_rtol(blocks: list, script_width: int, ltol: int | None = None, rtol: int | None = None, auto_aligner_tolerance: float = 0.01) -> tuple[int, int]:
    logging.info(f"AutoAligner: Setting ltol and rtol with auto-aligner tolerance of {auto_aligner_tolerance}%")
    start_whitespaces = []
    end_whitespaces = []
    for block in blocks:
        for line in block:
            start_whitespaces.append(len(line) - len(line.lstrip()))
            end_whitespaces.append(script_width - len(line.rstrip()))

    # This is a distribution of the whitespace at the start and end of each line.
    # Create a histogram of the whitespace at the start and end of each line.
    start_histogram = {i: start_whitespaces.count(i) / len(start_whitespaces) for i in range(max(start_whitespaces) + 1)}
    # end_histogram = {i: end_whitespaces.count(i) for i in range(max(end_whitespaces) + 1)}

    # Split the histogram into chunks separated by 0s
    start_histogram_chunks = []
    current_chunk = []
    for i in range(max(start_whitespaces) + 1):
        if start_histogram[i] < auto_aligner_tolerance:
            if current_chunk:
                start_histogram_chunks.append(current_chunk)
                current_chunk = []
        else:
            current_chunk.append(i)

    # Remove empty chunks
    start_histogram_chunks = [chunk for chunk in start_histogram_chunks if chunk]
    # Get the biggest number in the second chunk, if it exists
    if len(start_histogram_chunks) > 1:
        ltol = max(start_histogram_chunks[1]) + 1
        logging.info(f"AutoAligner: Setting ltol to {ltol}")
    else:
        logging.warn(f"AutoAligner: Could not determine ltol from auto-aligner: {start_histogram_chunks}")
        ltol = None

    logging.info(f"AutoAligner: Setting rtol to {rtol or 6}")

    return ltol or 8, rtol or 6




def _determine_block_alignment(
    block: list, script_width: int, script_indent: int, ltol: int = 8, rtol: int = 6
) -> tuple[str, str]:
    # Check the whitespace at the beginning of each line
    whitespace_at_start_of_line = [len(line) - len(line.lstrip()) for line in block]
    whitespace_at_end_of_line = [script_width - len(line.rstrip()) for line in block]
    if all(
        w_start > ltol and w_end > rtol
        for w_start, w_end in zip(whitespace_at_start_of_line, whitespace_at_end_of_line)
    ):
        return "C", "{}"
    elif all(abs(whitespace - script_indent) <= ltol for whitespace in whitespace_at_start_of_line):
        # Block is left-aligned.
        return "L", "{}"
    elif all(whitespace < rtol for whitespace in whitespace_at_end_of_line) or all(
        w_start > script_width // 2 for w_start, w_end in zip(whitespace_at_start_of_line, whitespace_at_end_of_line)
    ):
        return "R", "{}"

    # This is a weird block. We need to figure out how to handle it.
    block_info = json.dumps(
        {
            "block": block,
            "script_indent": script_indent,
            "script_width": script_width,
            "whitespace_at_start_of_line": whitespace_at_start_of_line,
            "whitespace_at_end_of_line": whitespace_at_end_of_line,
        }
    )

    return "U", block_info


def _extract_blocks(script_lines: list, script_width: int, script_indent: int, ltol: int | None = None, rtol: int | None = 6, auto_aligner_tolerance: float = 0.01) -> list:
    # Return a list of blocks, where each block is a list of lines, and the alignment of the block.

    # Step 1: There is a '\n\n' between each block. Split the script into blocks.
    blocks = []
    block = []
    for line in script_lines:
        if not line.strip():
            blocks.append(block)
            block = []
        else:
            block.append(line)

    # Filter out empty blocks.
    blocks = [block for block in blocks if block]

    # Step 2: Determine the alignment of each block.
    # Blocks are either left-aligned, right-aligned, or centered with an indent.
    if ltol is None or rtol is None:
        # We need to determine the left and right tolerance for block alignment.
        # We'll do this by looking at the whitespace at the beginning and end of each line.
        ltol, rtol = _autoset_ltol_rtol(blocks, script_width, ltol, rtol, auto_aligner_tolerance)

    output_blocks_with_alignment = []
    for block in blocks:
        block_alignment, block_info = _determine_block_alignment(block, script_width, script_indent, ltol, rtol)
        if block_alignment in ("L", "R", "C"):
            output_blocks_with_alignment.append((block, block_alignment))
        else:
            # Otherwise we need to figure out how to handle it.
            # Check to see if it's two spoken blocks (i.e. two blocks with a space in between each line)
            # The problem is that the blocks will have spaces themselves. So we need to split into two chunks if
            # The length of the space between the blocks is more than two.

            # There's a bit of a problem here, where if the block is too long on one speaker, then it's not two spoken blocks,
            # but we'll ignore that for now.
            # TODO: Fixme
            block_split = [re.sub(r"\s{2,}", "+++", line.strip()).split("+++") for line in block]
            block_chunks = list(zip(*block_split))
            # If the length of the block chunks is the same as the length of the block, then it's two spoken blocks.
            if len(block_chunks) == len(block):
                for b in block_chunks:
                    output_blocks_with_alignment.append((b, "C/2"))
            else:
                logging.warning(f"Unknown Block Alignment: {block_info}")
                pass

    # We can strip all of the individual lines now
    output_blocks_with_alignment = [
        ([line.strip() for line in block], alignment) for block, alignment in output_blocks_with_alignment
    ]

    return output_blocks_with_alignment


def _parse_center_aligned_block(block_lines: list) -> list:
    # If the first line is all caps, then it's a dialogue block.
    if len(block_lines) > 1 and block_lines[0].isupper():
        # There's a lot of information about the dialogue block
        speaker = block_lines[0].strip()
        # Check if there are Parentheses, and get the content inside
        voice_modifiers = re.findall(r"\(.*?\)", speaker)
        voice_modifier = []
        if voice_modifiers:
            # Get all of the voice modifiers
            for voice_modifier_string in voice_modifiers:
                voice_modifier.append(voice_modifier_string[1:-1])
            # Remove the voice modifiers from the character name
            speaker = re.sub(r"\(.*?\)", "", speaker).strip()

        outputs = []
        # Split the dialogue with additional action information
        individual_dialogue_actions = []
        current_dialogue_action = None
        for line in block_lines[1:]:
            if line.strip().startswith("(") and line.strip().endswith(")"):
                if individual_dialogue_actions:
                    outputs.append(
                        {
                            "type": "dialogue",
                            "content": " ".join(individual_dialogue_actions),
                            "meta": {
                                "speaker": speaker,
                                "voice_modifiers": voice_modifier,
                                "dialogue_actions": current_dialogue_action,
                            },
                        }
                    )
                    individual_dialogue_actions = []

                current_dialogue_action = line.strip()[1:-1]
            else:
                individual_dialogue_actions.append(line.strip())

        if individual_dialogue_actions:
            outputs.append(
                {
                    "type": "dialogue",
                    "content": " ".join(individual_dialogue_actions),
                    "meta": {
                        "speaker": speaker,
                        "voice_modifiers": voice_modifier,
                        "dialogue_actions": current_dialogue_action,
                    },
                }
            )

        return outputs

    # Check for some weird cases
    # if block_lines[0][-1] in (":", "."):
    #     return [{"type": "camera_action", "content": " ".join(block_lines), "meta": {}}]
    # if "INT" in block_lines[0] or "EXT" in block_lines[0]:
    #     return [{"type": "setting", "content": " ".join(block_lines), "meta": {}}]

    # print(block_lines)
    return [{"type": "metadata", "content": " ".join(block_lines), "meta": {}}]


def _parse_left_aligned_block(block_lines: list) -> list:
    # Check if it's a description or a setting
    if block_lines[0].upper() == block_lines[0]:
        # This is a setting or a camera action...
        if "EXT" in block_lines[0] or "INT" in block_lines[0]:
            return [{"type": "setting", "content": " ".join(block_lines), "meta": {}}]
        return [{"type": "camera_action", "content": " ".join(block_lines), "meta": {}}]

    return [{"type": "description", "content": " ".join(block_lines), "meta": {}}]


def _parse_right_aligned_block(block_lines: list) -> list:
    # This could either be metadata or it could be camera action
    if block_lines[0].isupper():
        # This is a camera action
        return [{"type": "camera_action", "content": " ".join(block_lines), "meta": {}}]

    return [{"type": "metadata", "content": " ".join(block_lines), "meta": {}}]


def _parse_extracted_blocks(blocks: list) -> list:
    # Parse the extracted blocks into a list of dictionaries.
    parsed_blocks = []
    for block in blocks:
        block_lines, block_alignment = block
        if block_alignment in ("C", "C/2"):
            parsed_blocks.extend(_parse_center_aligned_block(block_lines))
        elif block_alignment == "L":
            parsed_blocks.extend(_parse_left_aligned_block(block_lines))
        elif block_alignment == "R":
            parsed_blocks.extend(_parse_right_aligned_block(block_lines))

    # Merge sequenctial metadata blocks, and sequential camera_action blocks
    merged_blocks = []
    for block in parsed_blocks:
        if not merged_blocks:
            merged_blocks.append(block)
        elif block["type"] in ("metadata", "camera_action") and merged_blocks[-1]["type"] == block["type"]:
            merged_blocks[-1]["content"] += " " + block["content"]
        else:
            merged_blocks.append(block)

    return merged_blocks


def parse_script_to_blocks(script_path: str, ltol: int | None = None, rtol: int | None = 6, auto_aligner_tolerance: float = 0.01) -> list:
    script_lines, script_width, script_indent = _read_script(script_path)
    blocks = _extract_blocks(script_lines, script_width, script_indent, ltol, rtol, auto_aligner_tolerance)
    return _parse_extracted_blocks(blocks)
