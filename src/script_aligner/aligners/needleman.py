import json
from functools import lru_cache
from xml.etree import ElementTree

import numpy as np
import pysrt
from Levenshtein import distance
from rich.progress import Progress

NORM = None


def _prepare_aligner():
    from nemo_text_processing.utils.logging import c_handler, logger

    # Remove the c_handler from the logger
    logger.removeHandler(c_handler)
    # Set the logger to the default logging level

    from nemo_text_processing.text_normalization.normalize import Normalizer

    np.set_printoptions(precision=3, suppress=True, linewidth=500)
    global NORM
    NORM = Normalizer(input_case="cased", lang="en")


INDEL_PENALTY = -0.1


def prepare_data_for_alignment(script_events, subtitles):
    dialogue_events = [s if s["type"] == "dialogue" else None for s in script_events]
    d_events = []
    for i, event in enumerate(dialogue_events):
        if event:
            d_events.append({"text": event["content"].replace("\n", " "), "original_index": i, "item": event})

    s_events = []
    for i, sub in enumerate(subtitles):
        s_events.append({"text": sub["text"].replace("\n", " "), "original_index": i, "item": sub})

    return d_events, s_events


def load_srt_file(dialogue_file):
    subtitles = []
    subs = pysrt.open(dialogue_file)
    for s in subs:
        # Remove font XML tags
        if "<" in s.text:
            try:
                tree = ElementTree.fromstring(s.text)
                notags = ElementTree.tostring(tree, encoding="utf8", method="text").decode("utf8")
            except ElementTree.ParseError:
                notags = s.text
        else:
            notags = s.text

        subtitles.append({"text": notags, "start": s.start.ordinal, "end": s.end.ordinal})

    return subtitles


def _load_data(script_file, dialogue_file):
    # Load the script events
    with open(script_file) as jf:
        script_events = [json.loads(line) for line in jf.readlines()]

    # Load the SRT file
    subtitles = load_srt_file(dialogue_file)

    d_events, s_events = prepare_data_for_alignment(script_events, subtitles)

    return d_events, s_events


@lru_cache(maxsize=None)
def _normalize(s1):
    global NORM
    if NORM is None:
        _prepare_aligner()
    assert NORM is not None, "Normalizer not initialized"
    return NORM.normalize(s1)


def _match(s1, s2):
    # e1 = model.encode([s1], convert_to_tensor=True).cpu()
    # e2 = model.encode([s2], convert_to_tensor=True).cpu()
    s1 = _normalize(s1)
    s2 = _normalize(s2)

    # Compute the normalized levenstein distance
    ls = 1 - (distance(s1, s2) / max(len(s1), len(s2)))

    # return util.cos_sim(e1, e2)[0][0] + ls
    return 1 if ls > 0.4 else -0.5


def align(script_events, subtitles):
    script_data, sub_data = prepare_data_for_alignment(script_events, subtitles)

    # Build the cost matrix for the Needleman-Wunsch algorithm
    nw_matrix = np.zeros((len(script_data) + 1, len(sub_data) + 1))
    # Build the direction matrix for the Needleman-Wunsch algorithm
    direction_matrix = np.zeros((len(script_data) + 1, len(sub_data) + 1))

    # model = SentenceTransformer("all-MiniLM-L6-v2").cuda()

    # We need to fill the rest of the matrix diagonally, following the Needleman-Wunsch algorithm
    with Progress() as progress:
        task = progress.add_task("[cyan]Aligning...", total=(max(len(script_data), len(sub_data)) + 1) * 2)

        for diagonal in range(0, (max(len(script_data), len(sub_data)) + 1) * 2):
            # For each diagonal, we need to fill the cells in the diagonal
            # The diagonal is the set of cells where the row index + column index = diagonal
            for i in range(diagonal + 1):
                j = diagonal - i
                # If the cell is out of bounds, skip it
                if i >= len(script_data) + 1 or j >= len(sub_data) + 1:
                    continue

                # If the cell is on the diagonal, we need to fill it
                if i == 0 or j == 0:
                    nw_matrix[i, j] = INDEL_PENALTY * diagonal
                    if i == 0:
                        direction_matrix[i, j] = 2
                    else:
                        direction_matrix[i, j] = 1
                    continue

                # Get the scores for the three possible directions
                diag_score = nw_matrix[i - 1, j - 1] + _match(script_data[i - 1]["text"], sub_data[j - 1]["text"])

                up_score = nw_matrix[i - 1, j] + INDEL_PENALTY
                left_score = nw_matrix[i, j - 1] + INDEL_PENALTY

                # Get the maximum score
                max_score = max(diag_score, up_score, left_score)

                # Fill the cell with the maximum score
                nw_matrix[i, j] = max_score

                # Fill the direction matrix
                if max_score == diag_score:
                    direction_matrix[i, j] = 0
                elif max_score == up_score:
                    direction_matrix[i, j] = 1
                elif max_score == left_score:
                    direction_matrix[i, j] = 2

            progress.update(task, advance=1)

        # Print the cost matrix (pretty)
        # print(nw_matrix)

    # Now we need to backtrack through the direction matrix to get the alignment
    alignment = []
    i = len(script_data)
    j = len(sub_data)
    while i > 0 or j > 0:
        if direction_matrix[i, j] == 0:
            alignment.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif direction_matrix[i, j] == 1:
            alignment.append((i - 1, None))
            i -= 1
        elif direction_matrix[i, j] == 2:
            alignment.append((None, j - 1))
            j -= 1

    # Reverse the alignment
    alignment.reverse()

    # Write the results to a file
    for sample in script_events:
        if sample["type"] == "dialogue":
            sample["meta"]["subtitle"] = None
            sample["meta"]["subtitle_start"] = None
            sample["meta"]["subtitle_end"] = None

    for i, j in alignment:
        if i is not None and j is not None:
            elem = script_data[i]
            script_events[elem["original_index"]]["meta"]["subtitle"] = sub_data[j]["text"]
            script_events[elem["original_index"]]["meta"]["subtitle_start"] = sub_data[j]["item"]["start"]
            script_events[elem["original_index"]]["meta"]["subtitle_end"] = sub_data[j]["item"]["end"]

    return script_events, (alignment, script_data, sub_data)
