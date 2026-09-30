#!/usr/bin/env python3
"""A helper to zip all the items in FOLDER if fullname ends with SUFFIX
using maximum compression with zipfile"""
import os
import zipfile
import argparse

from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Tuple, List, Optional, Union


from tqdm import tqdm

## functions dealing with folders
def zip_subfolders(input_folder: Path, extension: str, n_procs: int) -> None:
    """Zips all subfolders within a directory in parallel.

    Identifies all immediate subdirectories of the input folder and processes
    them using a process pool. Each subfolder is zipped independently.

    Args:
        input_folder: The Path object of the directory containing folders to zip.
        extension: The file extension to include in the zip (e.g., 'xml').
        n_procs: The maximum number of parallel processes to use.

    Returns:
        None

    Raises:
        FileNotFoundError: If the input_folder does not exist.
    """
    if not input_folder.exists() or not input_folder.is_dir():
        raise FileNotFoundError(f"Input path {input_folder} is not a valid directory.")

    # Get list of subdirectories (filtering out files)
    # Using .iterdir() is the Pathlib equivalent of os.scandir
    subfolders = [f for f in input_folder.iterdir() if f.is_dir()]

    if not subfolders:
        print(f"No subfolders found in {input_folder}")
        return

    # Setup the worker function with the fixed extension argument
    # partial is used to "pre-fill" the extension argument
    safe_worker_function = partial(safely_process_one_folder, extension=extension)

    # Set the number of workers : at least 1, not more than cpu count or number of folders
    actual_procs = min(n_procs, len(subfolders), os.cpu_count() or 1)
    print(f"Processing {len(subfolders)} folders using {actual_procs} processes...")


    with ProcessPoolExecutor(max_workers=actual_procs) as executor:
        # map returns results in order. We wrap it in tqdm for the progress bar.
        results = list(tqdm(
            executor.map(safe_worker_function, subfolders),
            total=len(subfolders),
            desc="Zipping folders"
        ))

        # Handle and report errors from the results
        for success, err in results:
            if not success:
                tqdm.write(f"Error processing a folder: {err}")
def safely_process_one_folder(folder_path: str, **kwargs: Any) -> Tuple[bool, Optional[str]]:
    """Safely execute zip_one_folder and catch any exceptions.

    Args:
        folder_path (str): The path to the folder to be processed.
        **kwargs (Any): Arbitrary keyword arguments to be passed to
            process_one_file.

    Returns:
        Tuple[bool, Optional[str]]: A tuple where the first element is a
            boolean indicating success (True) or failure (False), and the
            second element is an error message string if processing failed,
            otherwise None.
    """
    try:
        process_one_folder(folder_path, **kwargs)
        return True, None
    except Exception as e:
        return False, f"{folder_path}: {e}"

def process_one_folder(folder_path: Path, extension: str) -> None:
    """Zips all files with a specific extension in a folder into a .zip archive.

    The resulting zip file is created in the same directory as the target folder,
    using the folder's name as the base filename. Files are stored in the zip
    using their relative paths from the source folder.

    Args:
        folder_path: The Path object of the directory to be zipped.
        extension: The file extension to filter by (e.g., 'xml', 'txt').

    Returns:
        None

    Raises:
        FileNotFoundError: If the provided folder_path does not exist.
        PermissionError: If the script lacks permissions to write the zip file.
    """
    folder_path = Path(folder_path)
    if not folder_path.is_dir():
        raise FileNotFoundError(f"The path {folder_path} is not a valid directory.")

    # Construct the zip filename (e.g., /path/to/folder -> /path/to/folder.zip)
    zip_filename = folder_path.with_name(f"{folder_path.name}.zip")

    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        # recursively filter by extension and get relative paths
        for file_path in folder_path.rglob(f"*.{extension}"):
            relative_path = file_path.relative_to(folder_path)

            # Add the file to the zip archive
            zipf.write(file_path, relative_path)

## functions dealing with files
def safely_process_one_file(file_path: str, **kwargs: Any) -> Tuple[bool, Optional[str]]:
    """Safely execute zip_one_folder and catch any exceptions.

    Args:
        file_path (str): The path to the file to be processed.
        **kwargs (Any): Arbitrary keyword arguments to be passed to
            process_one_file.

    Returns:
        Tuple[bool, Optional[str]]: A tuple where the first element is a
            boolean indicating success (True) or failure (False), and the
            second element is an error message string if processing failed,
            otherwise None.
    """
    try:
        process_one_file(file_path, **kwargs)
        return True, None
    except Exception as e:
        return False, f"{file_path}: {e}"

def process_one_file(file_path: Path, folder_path: Path) -> None:
    """Zips a single file into its own archive.

    The zip file is created in the same directory as the source file,
    preserving the relative path from the parent folder inside the archive.

    Args:
        file_path: The Path object of the file to be zipped.
        folder_path: The Path object of the parent folder.

    Returns:
        None
    """
    # make paths
    zip_path = file_path.with_suffix(".zip")
    relative_path = file_path.relative_to(folder_path)

    # compress
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        zipf.write(file_path, arcname=str(relative_path))

def zip_individually(folder_path: Path, extension: str, n_procs: int) -> None:
    """Processes all files of a specific extension in a folder in parallel.

    Identifies all files matching the extension within the provided directory
    and zips them one by one using a process pool.

    Args:
        folder_path: The Path object of the directory to scan.
        extension: The file extension to filter for (e.g., 'xml').
        n_procs: The maximum number of parallel processes to use.

    Returns:
        None
    """
    if not folder_path.exists() or not folder_path.is_dir():
        raise FileNotFoundError(f"The path {folder_path} is not a valid directory.")

    # Use pathlib's glob for cleaner file discovery
    source_files = list(folder_path.glob(f"*.{extension}"))

    if not source_files:
        print(f"No files with extension {extension} found in {folder_path}")
        return

    # Determine optimal worker count
    actual_procs = min(n_procs, len(source_files), os.cpu_count() or 1)

    # We use partial because ProcessPoolExecutor.map only accepts one argument per task.
    # We "pre-fill" the folder_path so the map only has to pass the file_path.
    worker_func = partial(safely_process_one_file, folder_path=folder_path)

    with ProcessPoolExecutor(max_workers=actual_procs) as executor:
        # Use list() to force evaluation so tqdm can track the total count
        _ = list(tqdm(
            executor.map(worker_func, source_files),
            total=len(source_files),
            desc=f"Zipping {extension} files"
        ))

def make_monolithic_archive(folder_path: Union[str, Path], extension: str, savename: str) -> None:
    """Recursively zips files with a specific extension from a given folder.

    This function walks through the directory tree of the provided folder,
    identifies all files ending with the specified extension, and compresses
    them into a single .zip file located in the same directory as the
    source folder.

    Args:
        folder_path (Union[str, Path]): The path to the directory to be zipped.
        extension (str): The file extension to filter for (e.g., '.txt' or '.csv').

    Returns:
        None

    Raises:
        FileNotFoundError: If the provided folder_path does not exist.
        PermissionError: If the script lacks permissions to read the folder
            or write the zip file.
    """
    # Convert to Path object for robust path manipulation
    base_path = Path(folder_path)

    if not base_path.exists() or not base_path.is_dir():
        raise FileNotFoundError(f"The path {folder_path} is not a valid directory.")

    # Create the zip path (e.g., "my_folder" becomes "my_folder.zip")
    if savename is None:
        zip_path = base_path.with_suffix('.zip')
    else:
        zip_path = Path(base_path.parent, f'{savename}.zip')
    print(f"Creating zip: {zip_path}")

    # ---- First pass: collect matching files ----
    matching_files: List[Tuple[Path, Path]] = []

    # rglob handles recursive searching and returns Path objects
    for path in base_path.rglob(f"*{extension}"):
        if path.is_file():
            # Calculate the path relative to the base folder
            rel_path = path.relative_to(base_path)
            matching_files.append((path, rel_path))

    print(f"Found {len(matching_files)} matching files.")

    # ---- Second pass: write to zip with progress ----
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        for full_path, rel_path in tqdm(matching_files, desc="Zipping", unit="file"):
            # rel_path must be converted to string for arcname
            zipf.write(full_path, arcname=str(rel_path))

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Zip all the items in FOLDER if fullname ends with SUFFIX"
        )

    parser.add_argument(
        "--folder", 
        help="Path to folder containing files to compress",
        required=True
        )
    parser.add_argument(
        "--savename",
        help="Save zip as this name",
        required=False,
        default="my_zip"
        )
    parser.add_argument(
        "--extension",
        help="extension to search for",
        required=True
        )
    parser.add_argument(
        "--n_procs",
        type=int,
        default=2,
        help="Number of processors for the pool"
        )
    parser.add_argument(
        "--mode",
        dest="mode",
        choices=["mono", "indiv", "subfolder"],
        required=True,
        help="Select the processing mode (mono, indiv, or subfolder)"
    )
    args = parser.parse_args()

    if args.mode == "mono":
        make_monolithic_archive(Path(args.folder), args.extension, args.savename)
    elif args.mode == "subfolder":
        zip_subfolders(Path(args.folder), args.extension, args.n_procs)
    else:
        zip_individually(Path(args.folder), args.extension, args.n_procs)
