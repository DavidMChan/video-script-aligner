from rich.console import Console
from rich.table import Table


# Print the alignment
def save_alignment_to_html(alignment, script_data, sub_data, output_path: str):
    table = Table(title="Alignment")
    table.add_column("Script", justify="right", no_wrap=True, width=80)
    table.add_column("Subtitle", justify="left", no_wrap=True, width=80)
    for i, j in alignment:
        if i is None:
            table.add_row("", f"[red]{sub_data[j]['text']}[/red]")
        elif j is None:
            table.add_row(f"[red]{script_data[i]['text']}[/red]", "")
        else:
            table.add_row(f"{script_data[i]['text']}", f"{sub_data[j]['text']}")

    console = Console(record=True)
    console.print(table)
    console.save_html(output_path)
