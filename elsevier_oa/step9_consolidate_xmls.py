""""Consolidate XML files to 1 XML per ISSN then organise these by subject"""
import argparse
import ast
import json
import os
import sys

from typing import Any, Dict, Tuple, Union
from pathlib import Path

from lxml import etree
from tqdm import tqdm


def prepare_dicts(metas_dict: Union[str, Path]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Loads a JSON metadata file and builds a mapping of ISSNs subjects.

    This function reads a JSON file from the provided path and parses it into
    a dictionary. It then iterates through the records to create a
    mapping where each unique journal ISSN is associated with the first
    subject found in the 'article_subj' field.

    Args:
        metas_dict (Union[str, Path]): The file path to the JSON metadata file.

    Returns:
        Tuple[Dict[str, Any], Dict[str, Any]]: A tuple containing:
            - master_dict (Dict[str, Any]): The complete dictionary loaded from the JSON.
            - issn_to_subj_dict (Dict[str, Any]): A dictionary mapping
              journal ISSN strings to their primary subject strings.
    """
    metadata_dict_as_path = Path(metas_dict)
    with open(metadata_dict_as_path, 'r', encoding='UTF-8') as j:
        master_dict = json.load(j)

    issn_to_subj_dict =  {}
    for _, topvalue in master_dict.items():
        issn = topvalue.get("journal_issn", "UNK")
        if issn not in issn_to_subj_dict:
            # Use ast.literal_eval to safely evaluate the string representation
            # of a list (e.g., "[sub1, sub2]") into an actual Python list.
            subjs = ast.literal_eval(topvalue.get("article_subj", "UNK"))
            subj = subjs[0]
            issn_to_subj_dict[issn] = subj

    return master_dict, issn_to_subj_dict

def move_to_issn_folders(search_dir: Union[str, Path], master_dict: Dict[str, Any]) -> Path:
    """
    Organizes XML files into subfolders based on their journal's ISSN.

    This function scans all subdirectories within the specified target directory,
    identifies XML files, and moves them to a new directory structure organized
    by ISSN (e.g., 'issn_level/ISSN_NUMBER/'). It uses the 'master_dict'
    to look up the correct ISSN based on a file's unique key.

    Args:
        search_dir (Union[str, Path]): The root directory to scan for
            subfolders containing XML files.
        master_dict (Dict[str, Any]): A dictionary mapping file prefixes
            to metadata dictionaries containing the 'journal_issn' key.

    Returns:
        None. Files are moved on disk, and progress is shown via a tqdm progress bar.
    """
    search_dir_as_path = Path(search_dir)
    if not search_dir_as_path.exists():
        print(f"Error: Directory doesn't exist: {search_dir_as_path}")
        sys.exit(0)

    # List only directories within the target path
    these_directories = [p for p in search_dir_as_path.iterdir() if p.is_dir()]

    for directory in these_directories:
        current_files = sorted(directory.glob("*.xml"))
        if not current_files:
            continue

        for file in tqdm(current_files, desc=f"Moving {directory.name}", leave=False):
            file_as_path = Path(file)

            # Extract the unique key from the filename
            key_from_file = file_as_path.name.replace('_tokenizedsentencised_full.xml', '')

            # Retrieve ISSN from master dictionary
            metadata = master_dict.get(key_from_file)
            if not metadata:
                print(f"Warning: No metadata found for key: {key_from_file}")
                continue

            issn_folder = metadata.get('journal_issn', 'UNK')

            # Construct the new path
            target_dir_path = file_as_path.parent.parent / 'issn_level' / Path(issn_folder)

            # Create directory if it doesn't exist
            target_dir_path.mkdir(parents=True, exist_ok=True)

            # Define new name and move file
            newname_as_path = target_dir_path / (key_from_file + ".xml")
            os.rename(file_as_path, newname_as_path)


def process_all_issn_folders(
    search_dir: Union[str, Path],
    issn_to_subj_dict: Dict[str, Any]
    ) -> None:
    """
    Iterates through all subfolders in the 'issn_level' directory and processes each.

    This function identifies the 'issn_level' directory located in the parent
    directory of the provided `search_dir`. It then loops through every
    subdirectory within 'issn_level' and executes the processing logic
    for each folder.

    Args:
        search_dir (Union[str, Path]): The directory path used to locate the
            'issn_level' folder. The logic assumes 'issn_level' is a sibling
            to the parent of the directory provided in `search_dir`.

    Returns:
        None. XML files in each folder are consolidated into a one XML document.
    """
    # Construct the path to the 'issn_level' folder
    issn_level_path = Path(search_dir).parent / 'issn_level'

    # Filter for directories only
    issn_folders = [f for f in issn_level_path.iterdir() if f.is_dir()]

    # Process each folder found
    for issn_folder in tqdm(issn_folders, desc="Processing ISSN Folders"):
        process_one_issn_folder(issn_folder, issn_to_subj_dict)


def process_one_issn_folder(issn_folder: Path, issn_to_subj_dict: Dict[str, Any]) -> None:
    """
    Consolidates all XML files within an ISSN folder into a single TEI corpus
    organized by subject.

    This function reads all XML files in a specific ISSN directory, merges their
    root elements into a single <teiCorpus> tree, and saves the result in
    a new 'subj_level' directory named after the subject associated with
    that ISSN.

    Args:
        issn_folder (Path): The directory path for a specific ISSN
            (e.g., .../issn_level/12345/).
        issn_to_subj_dict (Dict[str, Any]): A dictionary mapping ISSN strings
            to subject strings.

    Returns:
        None.
    """
    # Get the ISSN from the folder name
    current_issn = issn_folder.name

    # Retrieve the subject from our mapping, defaulting to 'UNK'
    output_subject = issn_to_subj_dict.get(current_issn, 'UNK')

    # Construct the output path
    output_dir = issn_folder.parent.parent / 'subj_level' / output_subject
    output_dir.mkdir(parents=True, exist_ok=True)

    output_full_path = output_dir / (current_issn + ".xml")

    # Gather all files in the current ISSN folder
    current_input_files = [f for f in issn_folder.iterdir() if f.is_file()]

    # Initialize the new TEI corpus root
    new_tree = etree.fromstring("<teiCorpus></teiCorpus>")

    # Parse files iteratively, appending their root to the new tree
    for file_path in current_input_files:
        input_tree = etree.parse(file_path)
        new_tree.append(input_tree.getroot())

    # Wrap the tree in an ElementTree object and write to disk
    output_tree = etree.ElementTree(new_tree)
    output_tree.write(output_full_path, encoding='UTF-8', pretty_print=True)



def main(search_dir: str, metas_dict_input_path: str) -> None:
    """
    Orchestrates the end-to-end data processing pipeline.

    This function coordinates the three main stages of the pipeline:
    1. Preparing metadata and generating a mapping of ISSNs to subjects.
    2. Reorganizing the raw files into a structured ISSN-level directory tree.
    3. Processing those folders to produce consolidated subject-level XML files.

    Args:
        search_dir (str): The directory path containing the files to be processed.
        metas_dict_input_path (str): The file path to the JSON metadata file.

    Returns:
        None.
    """
    # 1. Prepare dictionaries (loads JSON and builds ISSN -> Subject mappings)
    master_dict, issn_to_subj_dict = prepare_dicts(metas_dict_input_path)

    # 2. Move files to ISSN folders
    move_to_issn_folders(search_dir, master_dict)

    # 3. Process ISSN folders to create subject-level corpora
    process_all_issn_folders(search_dir, issn_to_subj_dict)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Consolidate XML files to 1 XML per ISSN then organise these by subject",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Source directory
    parser.add_argument(
        "-s", "--searchdir",
        type=str,
        required=True,
        help="Path to directory containing Chunk01, Chunk02 folders"
    )
    # Output directory
    parser.add_argument(
        "--metadict",
        type=str,
        required=True,
        help="Path to the master metadata.json dict"
    )

    args = parser.parse_args()
    main(
        search_dir=args.searchdir,
        metas_dict_input_path = args.metadict
        )
