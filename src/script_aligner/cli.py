import json
import logging
from typing import Optional

import click
from rich.logging import RichHandler

from script_aligner.aligners.needleman import align, load_srt_file
from script_aligner.aligners.utils import save_alignment_to_html
from script_aligner.parser import parse_script_to_blocks

logger = logging.getLogger(__name__)


@click.command()
@click.argument("input_srt", type=click.Path(exists=True))
@click.argument("input_script", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="output.html")
@click.option("--save-script-blocks", type=click.Path(), default=None)
@click.option("--script-ltol", type=Optional[int], default=None, help="Left tolerance for script alignment")
@click.option("--script-rtol", type=int, default=6, help="Right tolerance for script alignment")
@click.option("--auto-aligner-tolerance", type=float, default=0.01, help="Tolerance for the auto-tolerance selector")
def main(
    input_srt: str,
    input_script: str,
    output: str = "output.html",
    save_script_blocks: str | None = None,
    script_ltol: int | None = None,
    script_rtol: int | None = 6,
    auto_aligner_tolerance: float = 0.01,
):
    # Setup rich logging
    logging.basicConfig(level=logging.INFO, format="%(message)s", datefmt="[%X]", handlers=[RichHandler()])

    logging.info(f"Aligning {input_srt} and {input_script}")

    # Step 1: Parse the script
    logging.info("Step 1: Parsing the script into blocks")
    script_blocks = parse_script_to_blocks(
        input_script, script_ltol, script_rtol, auto_aligner_tolerance=auto_aligner_tolerance
    )

    logging.info("Step 2: Loading SRT")
    subtitles = load_srt_file(input_srt)

    logging.info("Step 3: Aligning script and subtitles")
    script_blocks_aligned, (alignment, script_data, sub_data) = align(script_blocks, subtitles)

    logging.info("Step 4: Saving alignment to HTML")
    save_alignment_to_html(alignment, script_data, sub_data, output)

    if save_script_blocks:
        with open(save_script_blocks, "w") as f:
            json.dump(script_blocks_aligned, f, indent=2)


if __name__ == "__main__":
    main()
