import argparse
import glob
import os
import re

from lxml import etree
from pathlib import Path
from stanza.utils.conll import CoNLL
from tqdm import tqdm
from typing import Any, Dict, List, Optional, Tuple, Union

from concurrent.futures import ProcessPoolExecutor
from functools import partial

def make_file_names(
    tagged_file: Union[str, Path], 
    xml_dirname: str, 
    xml_output_dirname: str
) -> Tuple[Path, Path]:
    """Constructs input and output paths by swapping directory names in a hierarchy.

    This function takes a file path and identifies a specific directory in the 
    hierarchy (the 'conll' directory). It then replaces that directory name 
    with a new input name and a new output name to generate full paths for 
    XML files.

    Args:
        tagged_file: The absolute path to the source tagged file.
        xml_dirname: The new directory name to use for the XML input.
        xml_output_dirname: The new directory name to use for the XML output.

    Returns:
        A tuple containing (xml_input_filepath, xml_output_filepath) as Path objects.

    Raises:
        ValueError: If the path manipulation results in an invalid structure.
    """
    # Convert to Path object for consistent behavior
    tagged_path = Path(tagged_file)
    
    # Extract the base filename, conll dirname and subfolder - 01, 02…
    file_basename = tagged_path.stem.replace('_OUT', '')
    conll_dirname = tagged_path.parent.parent.name
    parent_str = str(tagged_path.parent)
    
    # ---- Construct XML Input Path ----
    xml_input_dir_str = parent_str.replace(conll_dirname, xml_dirname)
    xml_input_filepath = Path(xml_input_dir_str) / f"{file_basename}.xml"

    # ---- Construct XML Output Path, create dir structure ----
    xml_output_dir_str = parent_str.replace(conll_dirname, xml_output_dirname)
    xml_output_dir_path = Path(xml_output_dir_str)
    xml_output_dir_path.mkdir(parents=True, exist_ok=True)
    xml_output_filepath = xml_output_dir_path / f"{file_basename}_full.xml"
    
    return xml_input_filepath, xml_output_filepath



def prepare_xml_tree(
    xml_input_filepath: Union[str, Path], 
    id_attrib: str
) -> Tuple[etree._Element, Dict[str, etree._Element]]:
    """Parses an XML file and builds a dictionary mapping IDs to 's' elements.

    This function parses an XML file, finds all elements with the tag 's', 
    and creates a dictionary where the keys are the values of a specific 
    attribute (e.g., 'id' or 's_id') and the values are the elements themselves.
    If only one element is found, it attempts to swap the attribute naming 
    convention to find a more appropriate mapping.

    Args:
        xml_input_filepath: The path to the XML file to be parsed.
        id_attrib: The primary attribute name to use for identification 
            (e.g., "s_id" or "id").

    Returns:
        A tuple containing:
            - The parsed lxml etree object.
            - A dictionary mapping the attribute values to the corresponding 
              's' elements.

    Raises:
        FileNotFoundError: If the provided xml_input_filepath does not exist.
        etree.XMLSyntaxError: If the file is not a valid XML.
    """
    # Convert to Path object
    path = Path(xml_input_filepath)
    if not path.exists():
        raise FileNotFoundError(f"The file {path} does not exist.")

    # Parse the tree, get s elements, dict with provided id_attrib
    input_tree = etree.parse(path)
    s_elements = input_tree.findall(".//s")
    target_dict: Dict[str, etree._Element] = {
        el.get(id_attrib): el for el in s_elements if el.get(id_attrib) is not None
    }

    # There should be more than 1 sentence in the dict, so try alternative attributes
    if len(target_dict) == 1:
        print("Trying alternative attribs to get valid_dict")
        
        if id_attrib == "s_id":
            # Swap "s_id" -> "id"
            alt_attr = id_attrib.replace('s_', '')
            target_dict = {el.get(alt_attr): el for el in s_elements if el.get(alt_attr) is not None}
        elif id_attrib == "id":
            # Swap "id" -> "s_id"
            alt_attr = f"s_{id_attrib}"
            target_dict = {el.get(alt_attr): el for el in s_elements if el.get(alt_attr) is not None}

    return input_tree, target_dict


def add_parse_to_tree(
    input_tree: etree._Element, 
    target_dict: Dict[str, etree._Element], 
    tagged_file: Union[str, Path]
) -> None:
    """Updates the XML tree with text content parsed from a CoNLL file.

    This function loads a CoNLL file, iterates through its sentences, 
    locates the corresponding sentence element in the XML tree using a 
    matching ID, removes any 'w' (word) child elements from that XML 
    node, and replaces the node's text with the new CoNLL-formatted 
    sentence string.

    Args:
        input_tree: The lxml etree object containing the XML structure.
        target_dict: A dictionary mapping sentence IDs (from the CoNLL 
            comments) to the corresponding 's' elements in the XML.
        tagged_file: The path to the CoNLL file to be parsed.

    Returns:
        None: This function modifies the input_tree in-place.

    Raises:
        FileNotFoundError: If the tagged_file path is invalid.
        KeyError: If a sentence ID is found in the CoNLL file but is 
            missing from the target_dict.
    """
    # Convert to Path for consistency
    tagged_path = Path(tagged_file)
    if not tagged_path.exists():
        raise FileNotFoundError(f"The file {tagged_path} does not exist.")

    # Load the CoNLL document
    conll_doc = CoNLL.conll2doc(str(tagged_path))

    for sent in conll_doc.sentences:
        first_comment_raw = sent.comments[0]
        sent_id = first_comment_raw.replace('# sent_id = ', '').strip()
        
        if sent_id not in target_dict:
            print(f"Warning: Sentence ID {sent_id} not found in target_dict. Skipping file {tagged_path}.")
            break
            
        # Retrieve the corresponding XML element
        target_el = target_dict[sent_id]
        
        # Remove all 'w' tags from the target element
        droplist = target_el.findall(".//w")
        for item in droplist:
            parent = item.getparent()
            if parent is not None:
                parent.remove(item)
        
        # Generate the new CoNLL string for the sentence
        conll_chunk = "\n".join([token.to_conll_text() for token in sent.tokens])
        
        # Update the XML element text
        target_el.text = conll_chunk



def process_one_file(
    tagged_file: Union[str, Path], 
    xml_dirname: str, 
    xml_output_dirname: str, 
    id_attrib: str
) -> None:
    """Runs the full pipeline to consolidate annotations and reference xml files.

    This function coordinates the path generation, XML parsing, CoNLL 
    data injection, and final file writing for one specific file.

    Args:
        tagged_file: The path to the source CoNLL-tagged file.
        xml_dirname: The name of the directory for XML inputs.
        xml_output_dirname: The name of the directory for XML outputs.
        id_attrib: The attribute name used to map CoNLL IDs to XML nodes.

    Returns:
        None

    Raises:
        FileNotFoundError: If the input files do not exist.
        Exception: Logs any other processing errors to the console.
    """
    # 1. Determine Paths
    xml_input_filepath, xml_output_filepath = make_file_names(
        tagged_file, 
        xml_dirname, 
        xml_output_dirname
    )

    # 2. Parse & Map
    input_tree, target_dict = prepare_xml_tree(xml_input_filepath, id_attrib)

    # 3. Inject Data
    add_parse_to_tree(input_tree, target_dict, tagged_file)

    # 4. Write modified tree to the new location
    input_tree.write(str(xml_output_filepath), encoding='UTF-8', pretty_print=True)
        



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


def make_tagged_file_lists(conll_source: Union[str, Path], sibling: bool) -> List[Path]:
    """Generates a sorted list of CoNLL file paths based on a source file.

    This function identifies files to process based on a reference path.
    - If `sibling` is True: It looks into all subdirectories of the parent 
      directory of the source, collecting all .conll files within them.
    - If `sibling` is False: It looks for all .conll files in the same 
      directory as the source file.

    Args:
        conll_source: The path to a reference CoNLL file.
        sibling: If True, search subdirectories of the source's parent. 
            If False, search the source's parent directory directly.

    Returns:
        A sorted list of Path objects pointing to .conll files.
    """
    # Ensure we are working with a Path object and resolve it to an absolute path
    source_path = Path(conll_source).resolve()
    parent_dir = source_path.parent

    tagged_files: List[Path] = []

    if sibling:
        # 1. Get all dirs in the parent dir, sort alphabetically
        folders = sorted([
            p for p in parent_dir.iterdir() if p.is_dir()
        ])
        
        # Collect .conll files from every subdirectory
        for folder in folders:
            files = sorted(folder.glob("*.conll"))
            tagged_files.extend(files)
            
    else:
        # Look for .conll files in the specified dir only
        tagged_files = sorted(parent_dir.glob("*.conll"))

    return tagged_files



def safely_process_one_file(
    tagged_file: Union[str, Path], 
    xml_dirname: str, 
    xml_output_dirname: str, 
    id_attrib: str
) -> Tuple[bool, Union[str, None]]:
    """Wrapper to catch exceptions during parallel processing.
    
    Returns:
        (True, None) if successful.
        (False, error_message) if an exception occurred.
    """
    try:
        process_one_file(tagged_file, xml_dirname, xml_output_dirname, id_attrib)
        return True, None
    except Exception as e:
        return False, str(e)

def main(
    conll_source: Path,
    xml_dirname: str,
    xml_output_dirname: str,
    id_attrib: str,
    n_procs: int,
    sibling: bool
) -> None:
    """Main entry point for the parallel XML annotation pipeline.

    Args:
        conll_source: Path to a reference CoNLL file.
        xml_dirname: Name of the directory for XML inputs.
        xml_output_dirname: Name of the directory for XML outputs.
        id_attrib: The attribute name for ID mapping (e.g., 's_id').
        n_procs: Max number of processes to use.
        sibling: Whether to search sibling directories for files.
    """
    # 1. Make file list
    tagged_files = make_tagged_file_lists(conll_source, sibling)
    file_count = len(tagged_files)
    
    if file_count == 0:
        print(f"No files with .conll extension found in {conll_source}")
        return

    print(f'Found {file_count} files to process.')

    # 2. Define the worker function with 3 frozen args
    safe_worker_function = partial(
        safely_process_one_file, 
        xml_dirname=xml_dirname,
        xml_output_dirname=xml_output_dirname, 
        id_attrib=id_attrib
    )

    # 3. Determine a safe size for the processor pool
    actual_procs = min(n_procs, file_count, os.cpu_count() or 1)
    print(f"Starting pool with {actual_procs} workers.")

    # 4. Execution
    with ProcessPoolExecutor(max_workers=actual_procs) as ex:
        # ex.map maintains the order of the tagged_files list, returns a generator
        results = ex.map(safe_worker_function, tagged_files)

        # Wrap results in tqdm for a progress bar
        for success, err in tqdm(results, total=file_count, desc="Processing"):
            if not success:
                # tqdm.write ensures the print doesn't break the progress bar
                tqdm.write(f"Error processing file: {err}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insert annotations into source XML file")
    
    parser.add_argument(
        "-c", "--conll_source", 
        help="Path to dir with tagged CoNLL files"
    )
    parser.add_argument(
        "-i", "--xml_dirname", 
        help="Name (not path) of dir with xml files as input"
    )
    parser.add_argument(
        "-o", "--xml_output", 
        help="Name (not path) of dir where xml trees will be exported"
    )
    parser.add_argument(
        "--id_attrib", 
        help="attribute of s elements used as id : s, s_id…"
    )
    parser.add_argument(
        "--n_procs", 
        help="How many worker processes to request", 
        required=False, 
        default=2, 
        type=int, 
        metavar="N"
    )
    parser.add_argument(
        "--sibling", 
        help="Run in sibling mode : specify a folder of conll files and run the process for all its siblings", 
        required=False, 
        default=False, 
        action="store_true"
    )

    args = parser.parse_args()
    
    main(
        conll_source=Path(args.conll_source),
        xml_dirname=args.xml_dirname,      
        xml_output_dirname=args.xml_output,  
        id_attrib=str(args.id_attrib),
        n_procs=int(args.n_procs),
        sibling=bool(args.sibling)
    )
