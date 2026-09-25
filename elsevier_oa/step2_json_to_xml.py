"""script implementing a pipeline to transform json docs of a specific format to xml"""

import argparse
import json
import os

from pathlib import Path
from typing import Any, Dict, List, Tuple, Union
from lxml import etree
from tqdm import tqdm

def run_main(
    source_dir: Union[str, Path],
    output_dir: Union[str, Path]
) -> List[str]:
    """Iterates through subdirectories in a source directory, processes each,
    and collects all reported errors.

    Args:
        source_dir (Union[str, Path]): Path to the directory containing subfolders
            to process.
        output_dir (Union[str, Path]): Path to the directory where processed
            results should be saved.

    Returns:
        No returns. If errors are encountered, they will be printed.
    """
    folder_list = sorted([p for p in Path(source_dir).iterdir() if p.is_dir()])
    full_errorlist: List[str] = []

    for folder in folder_list:
        errorlist = process_one_folder(folder, output_dir)
        full_errorlist.extend(errorlist)

    for item in full_errorlist:
        print(item)


def make_header_element(metadata_dict: Dict[str, Any]) -> etree._Element:
    """
    Creates an XML metadata header element from a dictionary.

    This function takes a dictionary containing article identifiers and metadata, 
    then constructs an lxml etree._Element representing a `<metas>` tag. 
    Attributes like docId, title, doi, and issn are extracted and set 
    as XML attributes.

    Args:
        metadata_dict (Dict[str, Any]): A dictionary containing:
            - 'docId' (str/int): Unique identifier for the document.
            - 'metadata' (Dict): A dictionary containing 'title', 'doi', 
              and 'issn' keys.

    Returns:
        etree._Element: The constructed <metas> XML element.
    """
    header_el = etree.Element('metas')
    header_el.set('docId', str(metadata_dict['docId']))
    header_el.set('art_title', str(metadata_dict['metadata']['title']))
    header_el.set('doi', str(metadata_dict['metadata']['doi']))
    header_el.set('issn', str(metadata_dict['metadata']['issn']))
    return header_el


def make_body_element(body_el_itemdict: List[Dict[str, Any]]) -> etree._Element:
    """
    Constructs a body XML element populated with paragraph tags.

    This function takes a list of dictionaries, where each dictionary represents 
    a sentence or paragraph with its associated metadata (offsets, section IDs, 
    and titles). It creates a `<body>` element and appends a `<p>` tag for 
    each dictionary item, populating the tag with relevant attributes and 
    the actual text content.

    Args:
        body_el_itemdict (List[Dict[str, Any]]): A list of dictionaries. Each 
            dictionary must contain keys for: 'startOffset', 'endOffset', 
            'secId', 'title' (mapped to 'belongs_to'), and 'sentence'.

    Returns:
        etree._Element: The constructed <body> XML element containing all 
            paragraph tags.
    """
    body_el = etree.Element('body')

    for x in body_el_itemdict:
        p_el = etree.SubElement(body_el, "p")
        p_el.set('startOffset', str(x.get('startOffset', '0')))
        p_el.set('endOffset', str(x.get('endOffset', '0')))
        p_el.set('secId', str(x.get('secId', '')))
        p_el.set('belongs_to', str(x.get('title', '')))
        p_el.text = x.get('sentence', "")

    return body_el



def check_dirs(output_dir: Union[str, Path], source_dir: Union[str, Path]) -> Path:
    """
    Creates the required output directory structure based on the source directory.

    This function takes a base output directory and the name of the source 
    directory to construct a mirrored directory path. It ensures that the 
    output directory and its specific subfolder exist on the filesystem.

    Args:
        output_dir (Union[str, Path]): The root directory where processed 
            outputs will be saved.
        source_dir (Union[str, Path]): The directory path of the source 
            data, used to derive the subfolder name.

    Returns:
        Path: The Path object for the newly created or verified 
            output subdirectory.
    """
    out_head_dir = Path(output_dir)
    # parents=True ensures that if the base output_dir doesn't exist,
    # it will create the full path leading to it.
    out_head_dir.mkdir(parents=True, exist_ok=True)

    # Derive the subfolder name from the source_dir path
    # e.g., if source_dir is /data/folder_a, subfolder_name is 'folder_a'
    subfolder_name = Path(source_dir).name
    current_output_dir = out_head_dir / subfolder_name
    current_output_dir.mkdir(parents=True, exist_ok=True)

    return current_output_dir

def finalise_tree_from_elements(
    header_element: etree._Element,
    body_element: etree._Element
    ) -> etree.ElementTree:
    """
    Wraps header and body elements into a complete TEI XML structure.

    This function constructs a root <TEI> element, appends the provided 
    header element, and nests the provided body element inside a <text> 
    tag. It returns a fully formed etree.ElementTree object ready for 
    serialization to disk.

    Args:
        header_element (etree._Element): The XML element containing 
            metadata (usually the <metas> tag).
        body_element (etree._Element): The XML element containing 
            the main content (usually the <body> tag).

    Returns:
        etree.ElementTree: The complete TEI ElementTree.
    """
    # Make TEI element and append the header (metadata)
    tei_el = etree.Element('TEI')
    tei_el.append(header_element)

    # Create a text container and append the body
    text_el = etree.SubElement(tei_el, 'text')
    text_el.append(body_element)

    # Return the full tree
    return etree.ElementTree(tei_el)

def process_one_folder(
    source_dir: Union[str, Path],
    output_dir: Union[str, Path]
) -> List[Tuple[Exception, str]]:
    """Processes all JSON files in a single folder and converts them to TEI XML.

    Reads each `.json` file in `source_dir`, extracts metadata and ordered body text
    segments, builds an XML tree adhering to a simple TEI structure, and writes
    the resulting XML file into a corresponding subfolder under `output_dir`.

    Args:
        source_dir (Union[str, Path]): Path to the folder containing source JSON files.
        output_dir (Union[str, Path]): Path to the root output directory where
            processed XML results will be saved.

    Returns:
        List[Tuple[Exception, str]]: A list of tuples containing any caught Exception
            and the file path (as a string) where the exception occurred.
    """
    errorlist: List[Tuple[Exception, str]] = []
    source_files = sorted([str(p) for p in Path(source_dir).glob("*.json")])
    current_output_dir = check_dirs(output_dir, source_dir)

    for source_file in tqdm(source_files):
        try:
            with open(source_file, 'r', encoding='UTF-8') as k:
                my_dict: Dict[str, Any] = json.load(k)

            ordered_body_items = sorted(
                my_dict['body_text'],
                key=lambda x: x.get("startOffset", float("inf"))
                )

            header_el = make_header_element(my_dict)
            body_el = make_body_element(ordered_body_items)
            tidy_tree = finalise_tree_from_elements(header_el, body_el)
            output_basename = os.path.basename(source_file).replace('.json', '.xml')
            output_filename = Path(current_output_dir / output_basename)
            tidy_tree.write(output_filename, encoding='UTF-8', pretty_print=True)


        except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError) as e:
            errorlist.append((e, source_file, "file read error"))
        except json.JSONDecodeError as e:
            errorlist.append((e, source_file, "invalid JSON"))
        except (KeyError, TypeError, AttributeError) as e:
            errorlist.append((e, source_file, "unexpected data structure"))
        except OSError as e:
            errorlist.append((e, source_file, "output write error"))
        except Exception as e:
            errorlist.append((e, source_file, "unexpected error"))

    return errorlist


if __name__ == "__main__":
    # Initialize the argument parser
    parser = argparse.ArgumentParser(
        description="Convert folders of JSON articles to XML",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Required argument: source file path
    parser.add_argument(
        "--source_dir",
        type=str,
        required=True,
        help="Directory containing nested folders which contain the JSON files to process"
    )

    # Required argument: output dir
    parser.add_argument(
        "--output_dir",
        type=str,
        required=True,
        help="The folder where XML output will be written"
    )
    args = parser.parse_args()
    my_source_dir = args.source_dir
    my_output_dir = args.output_dir
    run_main(my_source_dir, my_output_dir)
