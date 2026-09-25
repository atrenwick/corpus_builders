
import argparse
import glob
import json

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
    
    output_head_dir = Path(output_dir)
    output_head_dir.mkdir(exist_ok=True)
    
    current_output_dir = output_head_dir / Path(source_dir).name
    current_output_dir.mkdir(exist_ok=True)

    for source_file in tqdm(source_files):
        try:
            with open(source_file, 'r', encoding='UTF-8') as k:
                my_dict: Dict[str, Any] = json.load(k)
            
            data = my_dict['body_text']
            ordered_items = sorted(data, key=lambda x: x.get("startOffset", float("inf")))
            
            header_el = etree.Element('metas')
            header_el.set('docId', str(my_dict['docId']))
            header_el.set('art_title', str(my_dict['metadata']['title']))
            header_el.set('doi', str(my_dict['metadata']['doi']))
            header_el.set('issn', str(my_dict['metadata']['issn']))
            
            body_el = etree.Element('body')
            for x in ordered_items:
                p_el = etree.SubElement(body_el, "p")
                p_el.set('startOffset', str(x.get('startOffset')))
                p_el.set('endOffset', str(x.get('endOffset')))
                p_el.set('secId', str(x.get('secId')))
                p_el.set('belongs_to', str(x.get('title')))
                p_el.text = x.get('sentence')
                
            tei_el = etree.Element('TEI')
            tei_el.append(header_el)
            text_el = etree.SubElement(tei_el, 'text')
            text_el.append(body_el)
            
            tidy_tree = etree.ElementTree(tei_el)
            output_basename = os.path.basename(source_file).replace('.json', '.xml')
            output_filename = Path(current_output_dir / output_basename)
            
            tidy_tree.write(output_filename, encoding='UTF-8', pretty_print=True)
        except Exception as e:
            my_report = (e, source_file)
            errorlist.append(my_report)

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
        help="The folder where XML output will be written in a structure mirroring that of the source directory, including subfolders"
    )
    args = parser.parse_args()
    source_dir = args.source_dir
    output_dir = args.output_dir

    run_main(source_dir, output_dir)

