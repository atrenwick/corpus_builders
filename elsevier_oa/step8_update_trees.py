"""Update and reshape XML files based on metadata dictionaries."""

import argparse
import copy
import json
import os
import sys

from concurrent.futures import as_completed, ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple, Union

from tqdm import tqdm
from lxml import etree

@dataclass
class UpdateTreeProcessingConfig:
    """Configuration for a single file-processing run to updateTrees.

    Bundles the paths, identifiers, and runtime options needed by
    `main()` to process a batch of files, so they can be passed
    around as a set of arguments.

    Attributes:
        source_dir: Path to the folder with XML-conll files.
        output_dir: Path to dir where updated XML trees will be exported.
        article_metas_dict_file_path: Path to json dict of article metadata
        issn_title_dict_file_path: Path to json dict of journal metadata
        sibling: Processing mode selector. 
            Run in sibling mode to process a folder of MXL files AND 
            all its sibling folders.
        nprocs (int, optional): Maximum number of processes to use.
            Defaults to the number of CPU cores.
        extension: File extension used to find files to process
    """
    source_dir: Path
    output_dir: Path
    article_metas_dict_file_path: str
    issn_title_dict_file_path: str
    sibling: bool
    n_procs: int
    extension: str


# ---  Global Variables ---
top_article_metas_dict: Dict[str, Any] = {}
top_issn_title_dict: Dict[str, Any] = {}

def init_worker(
    article_metas_dict_file: Union[str, Path],
    issn_title_dict_file: Union[str, Path]
) -> None:
    """
    Initializes worker processes by loading metadata dictionaries into global memory.

    This function is intended to be used as an initializer for a ProcessPoolExecutor.
    It loads the large JSON dictionaries into the worker's global memory space
    once upon process startup. This prevents the script from re-reading these
    heavy files from disk for every individual file in the 40,000-file queue.

    Args:
        article_metas_dict_file (Union[str, Path]): Path to the JSON file
            containing article-level metadata.
        issn_title_dict_file (Union[str, Path]): Path to the JSON file
            containing the ISSN-to-title mapping.

    Returns:
        None
    """
    global top_article_metas_dict, top_issn_title_dict

    # Call the previously defined load_dicts function.
    # Since load_dicts calls sys.exit(1) on failure, if the files
    # are missing or corrupt, the worker process will terminate
    # immediately, preventing the script from running with empty data.
    top_article_metas_dict, top_issn_title_dict = load_dicts(
        article_metas_dict_file,
        issn_title_dict_file
    )


EMPTY_HEADER_STR = """
<teiHeader>
    <fileDesc>
        <titleStmt>
            <title>title</title>
            <author>author_list</author>
            <respStmt>
                <name />
                <resp />
            </respStmt>
            <respStmt>
                <name />
                <resp />
            </respStmt>
        </titleStmt>
        <publicationStmt>
            <sourceinfo/>
        </publicationStmt>
        <profileDesc>
            <langUsage>
                <language ident="en" />
            </langUsage>
        </profileDesc>
    </fileDesc>
</teiHeader>
"""
TEMPLATE_HEADER = etree.fromstring(EMPTY_HEADER_STR.strip())
## end of global variables


def load_dicts(
    article_metas_dict_file: Union[Path, str],
    issn_title_dict_file: Union[Path, str]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Loads two JSON files containing article metadata and ISSN-to-title mappings.

    This function reads the article metadata dictionary and the ISSN title map
    from the filesystem. It validates that both files exist and contain
    valid JSON objects of type dictionary. If validation fails, the
    script will terminate with an error message.

    Args:
        article_metas_dict_file (Union[Path, str]): Path to the JSON file
            containing article-level metadata.
        issn_title_dict_file (Union[Path, str]): Path to the JSON file
            containing the mapping of ISSNs to titles.

    Returns:
        Tuple[Dict[str, Any], Dict[str, Any]]: A tuple containing:
            - article_metas_dict (Dict): The first dictionary loaded.
            - issn_title_dict (Dict): The second dictionary loaded.

    Raises:
        SystemExit: If files are not found, are not valid JSON, or
            do not contain dictionary objects.
    """
    try:
        # 1. Load article level metas
        metadata_dict_path = Path(article_metas_dict_file)
        with open(metadata_dict_path, 'r', encoding='UTF-8') as j:
            article_metas_dict = json.load(j)

        if not isinstance(article_metas_dict, dict):
            print(f"Error: File {metadata_dict_path} did not load as a dictionary.")
            sys.exit(1)

        # 2. Load journal metas (issn title map)
        issn_title_dict_path = Path(issn_title_dict_file)
        with open(issn_title_dict_path, 'r', encoding='UTF-8') as j:
            issn_title_dict = json.load(j)

        if not isinstance(issn_title_dict, dict):
            print(f"Error: File {issn_title_dict_file} did not load as a dictionary.")
            sys.exit(1)

        #print("Successfully loaded both metadata and ISSN dictionaries.")
        return article_metas_dict, issn_title_dict

    except FileNotFoundError as e:
        print(f"Critical Error: File not found - {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Critical Error: Failed to decode JSON - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)


def make_full_header(
    doc_id: str,
    article_metas_dict: Dict[str, Any],
    issn_title_dict: Dict[str, Any]
) -> etree._Element:
    """
    Generates an XML header by cloning a pre-parsed template.

    This function retrieves metadata for a specific document ID, maps the
    journal title using the provided ISSN-to-Title dictionary, and constructs
    a TEI-compliant <teiHeader>. It populates the <sourceinfo> block with
    all metadata fields except for the primary title and author.

    Args:
        doc_id (str): The unique identifier for the document (filename stem).
        article_metas_dict (Dict[str, Any]): Dictionary containing all article
            metadata, keyed by doc_id.
        issn_title_dict (Dict[str, Any]): Dictionary mapping ISSNs to
            journal titles.

    Returns:
        etree._Element: The populated <teiHeader> XML element.

    Raises:
        KeyError: If the doc_id is not found in article_metas_dict.
    """
    # Extract article metadata
    article_metas = article_metas_dict[doc_id]

    # Map journal title based on ISSN
    issn_from_art_metas = article_metas.get('journal_issn')
    article_metas['journal_title'] = issn_title_dict.get(issn_from_art_metas, "Unknown Journal")

    # Parse the template into an etree element
    header = copy.deepcopy(TEMPLATE_HEADER)

    # Update basic fields
    title_elem = header.find(".//title")
    if title_elem is not None:
        title_elem.text = article_metas.get('title', "UNK TITLE")

    author_elem = header.find(".//author")
    if author_elem is not None:
        author_elem.text = article_metas.get('first_author', "Author Unknown")

    # Update sourceinfo block
    sourceinfo_block = header.find(".//sourceinfo")
    if sourceinfo_block is not None:
        # Define fields to skip (don't want to duplicate title/author inside sourceinfo)
        skip_keys = ['first_author', 'title']

        for key, value in article_metas.items():
            if key not in skip_keys:
                # Ensure value is a string and handle None/Empty
                clean_value = str(value) if value is not None else "_"
                sourceinfo_block.set(key, clean_value)

    return header


def make_paths(
    xml_input_filepath: Union[str, Path],
    output_dir: Union[str, Path]
) -> Tuple[Union[str, Path], Path]:
    """
    Determines the output path for a given input XML file by mirroring the
    input's subfolder structure into a target output directory.

    This function takes the folder name containing the input file (e.g.,
    'FolderA' from 'data/FolderA/file.xml') and replicates that folder
    inside the target output directory.

    Args:
        xml_input_filepath (Union[str, Path]): The path to the source
            XML file.
        output_dir (Union[str, Path]): The base directory where all
            processed files should be saved.

    Returns:
        Tuple[Union[str, Path], Path]: A tuple containing:
            - xml_input_filepath (str/Path): The original input path.
            - xml_output_full_path (Path): The new Path object for the
              processed output file.

    Raises:
        NotADirectoryError: If the input path provided is not a valid
            file path.
    """
    # Convert inputs to Path objects
    input_path = Path(xml_input_filepath)
    out_head = Path(output_dir)

    # Get parent folder and name based on current file
    src_dir = input_path.parent
    xml_subfolder = src_dir.name if src_dir.name else "root"

    # make full path for output file + parent dirs
    xml_output_full_path = out_head / xml_subfolder / input_path.name
    xml_output_dir_path = xml_output_full_path.parent
    xml_output_dir_path.mkdir(parents=True, exist_ok=True)

    return xml_input_filepath, xml_output_full_path


def reshape_tree_body(input_tree: etree._Element) -> None:
    """
    Reshapes the XML tree by grouping paragraph elements into div containers.

    This function iterates through all `<p>` elements in the input tree. It
    groups consecutive paragraphs that share the same `belongs_to` attribute
    value into a single `<div>` element. It then replaces the original
    `<body>` element with a new `<body>` containing these grouped `<div>`s.

    The modification is performed in-place on the `input_tree` object.

    Args:
        input_tree (etree._Element): The XML element tree to be modified.

    Returns:
        None
    """
    # Create the container for the new structure
    new_body = etree.Element("body")
    old_body = input_tree.find(".//body")

    if old_body is None:
        print("Warning: No <body> tag found in the input tree.")
        return

    current_div: Optional[etree._Element] = None
    current_type: Optional[str] = None

    # Iterate through all paragraph elements
    for pblock in input_tree.findall(".//p"):
        # Extract the category from the 'belongs_to' attribute
        p_type = pblock.get("belongs_to")

        # Remove the 'belongs_to' attribute from the original element
        if "belongs_to" in pblock.attrib:
            del pblock.attrib["belongs_to"]

        # If the category changes (or is the first item), create a new div
        if p_type != current_type:
            current_div = etree.Element(
                "div", 
                type=str(p_type) if p_type is not None else "unknown"
            )
            new_body.append(current_div)
            current_type = p_type

        # Detach the <p> tag from its original location
        parent = pblock.getparent()
        if parent is not None:
            parent.remove(pblock)

        # Append the detached <p> to the current div
        current_div.append(pblock)

    # Replace the old body with the new reconstructed body
    parent = old_body.getparent()
    if parent is not None:
        parent.remove(old_body)
        parent.append(new_body)
    else:
        # If the old body was the root, replace it directly
        # (This handles cases where the input_tree IS the body)
        pass


def update_tree_header(input_tree: etree._Element, tei_header_element: etree._Element) -> None:
    """
    Replaces the metadata block with a TEI header in the XML tree.

    This function locates the first occurrence of a <metas> tag in the
    provided XML tree, removes it from its parent, and inserts the
    provided `tei_header_element` at the very beginning of that same
    parent container.

    Args:
        input_tree (etree._Element): The XML tree to modify.
        tei_header_element (etree._Element): The new <teiHeader>
            element to insert.

    Returns:
        None
    """
    # Locate the metadata block
    old_metas = input_tree.find(".//metas")

    if old_metas is None:
        print("Warning: No <metas> tag found in the input tree. Skipping header update.")
        return

    # Get the parent of the metadata tag
    parent = old_metas.getparent()

    if parent is not None:
        # Remove the old metadata block
        parent.remove(old_metas)
        # Insert the new header at the first position (index 0)
        parent.insert(0, tei_header_element)
    else:
        # This handles the edge case where <metas> is the root element
        print("Warning: <metas> is the root element and has no parent to insert into.")

def process_one_file(file_path: str, output_dir: str) -> None:
    """
    Processes a single XML file: parses metadata, updates headers,
    reshapes the body, and writes to a new location.

    This function performs the following sequence:
    1. Determines the output path based on the input directory structure.
    2. Parses the XML content.
    3. Extracts the document ID from the <metas> tag.
    4. Generates a new TEI header using metadata dictionaries in `global`.
    5. Updates the XML tree by replacing the old header with the new one.
    6. Reshapes the body of the XML to group paragraphs into divs.
    7. Saves the final XML to the output directory.

    Args:
        file_path (str): The filesystem path to the input XML file.
        output_dir (str): The base directory where the output should be saved.

    Returns:
        None
    """
    # 1. Determine paths,
    xml_input_filepath, xml_output_full_path = make_paths(file_path, output_dir)

    # 2. Parse Input, extract doc_id
    input_tree = etree.parse(xml_input_filepath)

    # 3. Extract ID
    # Note: .xpath(...)[0] will raise IndexError if the tag is missing,
    # which the safe wrapper will catch.
    doc_id = input_tree.xpath(".//metas/@docId")[0]

    # 4. Construct and Update Header
    # Note: These dicts are assumed to be available in the scope
    # (e.g., via global loader or passed via initializer).
    new_header_element = make_full_header(doc_id, top_article_metas_dict, top_issn_title_dict)
    update_tree_header(input_tree, new_header_element)

    # 5. Reshape Body
    reshape_tree_body(input_tree)

    # 6. Write Output
    input_tree.write(xml_output_full_path, encoding='UTF-8', pretty_print=True)

def safely_process_one_file(file_path: str, **kwargs: Any) -> Tuple[bool, Optional[str]]:
    """Safely process one file and catch any exceptions.

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


def make_file_lists(source_dir: Union[str, Path], sibling: bool, extension: str) -> List[Path]:
    """Generates a sorted list of xml file paths based on a source folder.

    This function identifies files to process based on source_dir.
    - If `sibling` is True: It looks into all subdirectories of the parent
      directory of source_dir, collecting all .xml files within them.
    - If `sibling` is False: It looks for all .xml files in the source_dir
      directory.

    Args:
        source_dir: (str,Path) The path to a folder of XML files to process.
        sibling: (bool) If True, search subdirectories of source_dir's parent.
            If False, search the source's parent directory directly.
        extension: (str) A file extension to search for

    Returns:
        A sorted list of Path objects pointing to .xml files.
    """
    # Ensure we are working with a Path object and resolve it to an absolute path
    source_dir = Path(source_dir).resolve()
    parent_dir = source_dir.parent

    extension = str(extension).replace(".", "")
    xml_files: List[Path] = []

    if sibling:
        # 1. Get all dirs in the parent dir, sort alphabetically
        folders = sorted([
            p for p in parent_dir.iterdir() if p.is_dir()
        ])

        # Collect .conll files from every subdirectory
        for folder in folders:
            files = sorted(folder.glob(f"*.{extension}"))
            xml_files.extend(files)

    else:
        # Look for .conll files in the specified dir only
        xml_files = sorted(source_dir.glob(f"*.{extension}"))

    return xml_files


def main(config: UpdateTreeProcessingConfig) -> None:
    """
    Orchestrates the multi-process pipeline to process XML files.

    This function identifies all XML files in the source directory, initializes
    a process pool with shared metadata dictionaries, and executes the
    processing logic across all available CPU cores.

    Args:
        config (UpdateTreeProcessingConfig): Custom data class holding all
        parameters needed to update trees.

    Returns:
        None
    """
    # 1. Gather files
    source_dir = Path(config.source_dir)
    xml_files = make_file_lists(config.source_dir, config.sibling, config.extension)
    file_count = len(xml_files)

    if file_count == 0:
        print(f"No files with .xml extension found in {source_dir}")
        return

    print(f'Found {file_count} files to process.')

    # 2. Prepare worker function
    safe_worker_function = partial(
        safely_process_one_file,
        output_dir=config.output_dir
    )

    # 3. Determine process count
    actual_procs = min(config.n_procs, file_count, os.cpu_count() or 1)
    print(f"Starting pool with {actual_procs} workers.")

    # 4. Run the pool
    with ProcessPoolExecutor(
        max_workers=actual_procs,
        initializer=init_worker,
        initargs=(
          config.article_metas_dict_file_path,
          config.issn_title_dict_file_path
          )
    ) as ex:

        future_to_file = {
            ex.submit(safe_worker_function, str(f)): f for f in xml_files
        }

        # Track results
        for future in tqdm(as_completed(future_to_file), total=file_count, desc="Processing"):
            file_path = future_to_file[future]
            try:
                success, err = future.result()
                if not success:
                    tqdm.write(f"Error processing file: {err}")
            except Exception as e:
                tqdm.write(f"Critical exception on {file_path}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update and reshape XML files based on metadata dictionaries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Source directory
    parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="Directory containing nested folders which contain the XML files to process"
    )
    # Output directory
    parser.add_argument(
        "-o", "--output",
        type=str,
        required=True,
        help="Top level folder where nested subfolders of output will be placed"
    )

    # Metadata paths
    parser.add_argument(
        "-a", "--artmetas",
        type=str,
        required=True,
        help="Path to dict of article metadata"
    )
    parser.add_argument(
        "--issn",
        type=str,
        required=True,
        help="Path to dict with ISSN-title mapping"
    )

    # Processing options
    parser.add_argument(
        "--n_procs",
        type=int,
        default=2,
        required=False,
        metavar="N",
        help="How many worker processes to request"
    )
    parser.add_argument(
        "--sibling",
        help="Run in sibling mode : specify a folder of xml files and process all its siblings",
        required=False,
        default=False,
        action="store_true"
    )
    parser.add_argument(
        "--extension",
        type=str,
        required=False,
        default="xml" ,
        help="File extension to use in searches"
    )

    args = parser.parse_args()

    config_from_argparse = UpdateTreeProcessingConfig(
        source_dir=Path(args.source),
        output_dir=Path(args.output),
        article_metas_dict_file_path=args.artmetas,
        issn_title_dict_file_path=str(args.issn),
        n_procs=int(args.n_procs),
        sibling=bool(args.sibling),
        extension=(args.extension)

    )

    main(config_from_argparse)
