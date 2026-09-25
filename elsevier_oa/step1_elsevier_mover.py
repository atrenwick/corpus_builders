"""Move json files into subfolders"""
import argparse
import os
import re

from pathlib import Path
from tqdm import tqdm

def run_main_mover(source_dir: str, extension: str, chunk_size: int, verbose: bool):
    """
    Make subfolders and place files from source directory in these subfolders

    Args:
        source_dir (str): Path to the source directory.
        extension (str): extension of the files to move without the period/full stop.
        chunk_size (int): Number of files per chunk. Default value is 1000.
        verbose (bool): Print original path and new path of each file moved. Defaults to False

    Returns:
        None:
    """

    tidy_extension = re.sub(r"^\.","", extension)
    file_list = sorted([str(p) for p in Path(source_dir).glob(f"*.{tidy_extension}")])
    chunk = 1
    for i, item in tqdm(enumerate(file_list)):
        name_base = os.path.basename(item)
        chunk = (i // chunk_size) + 1
        target_folder = Path(f'{source_dir}/{chunk:02d}/')
        target_folder.mkdir(exist_ok=True)
        newname = target_folder / name_base
        if verbose:
            print(f'{item} -->> {newname}')
        os.rename(item, newname)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='''Move json files into subfolders.

    Usage :
      python3 /scripts/1_make_subfolders.py --source /data/elsevier_oa/data --chunks 1000 --extension json --verbose

    ''')
    parser.add_argument(
        "--source", type=str,help="path to file1 AKA fileA", required = True
    )
    parser.add_argument(
        "--extension", type=str,help="file extension without the dot, eg json", required = True
    )
    parser.add_argument(
        "--chunks",
        type=int,
        help="Chunk size in files, defaults to 1000",
        default=1000,
        required=False
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False
    )
    args = parser.parse_args()

    my_source_dir = args.source
    chosen_extension = args.extension
    chosen_chunk_size = args.chunks
    use_verbose = args.verbose
    run_main_mover(my_source_dir, chosen_extension, chosen_chunk_size, use_verbose)
