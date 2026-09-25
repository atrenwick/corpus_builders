# -*- coding: utf-8 -*-
import json
import os
import argparse
from pathlib import Path
from lxml import etree
from tqdm import tqdm
from typing import Dict, Tuple, Any, List



def load_meta_dicts(key_url_json_file: str, metadata_detail_file: str) -> Tuple[Dict, Any, Dict]:
    """
    Loads article mapping from a JSON file and metadata details from an XML file.

    Args:
        key_url_json_file (str): Path to the JSON file mapping article keys to URLs.
        metadata_detail_file (str): Path to the XML file containing metadata details.

    Returns:
        Tuple containing:
            - key_url_dict (Dict): Mapping of article numbers to URLs.
            - metadata_detail_tree (etree._ElementTree): The parsed XML tree.
            - metadata_detail_dict (Dict): Mapping of URLs to their corresponding XML elements.
    """
    print("Loading metas…")
    
    with open(key_url_json_file, 'r', encoding='UTF-8') as f:
        key_url_dict = json.load(f)
    
    metadata_detail_tree = etree.parse(metadata_detail_file)
    
    # Create a dictionary mapping the 'url' attribute of each <metadata> element to the element itself
    metadata_detail_dict = {
        el.get("url"): el for el in metadata_detail_tree.xpath(".//metadata")
    }
    
    print("Loading metas complete")
    return key_url_dict, metadata_detail_dict


def get_urls_and_el_from_article_key(
    article_key: str, 
    key_url_dict: Dict[str, str], 
    metadata_detail_dict: Dict[str, Any]
) -> Tuple[Any, str, str]:
    """
    Transforms an article key into a film URL and retrieves the associated metadata element.

    Args:
        article_key (str): The unique identifier for the article.
        key_url_dict (Dict[str, str]): Dictionary mapping article keys to review URLs.
        metadata_detail_dict (Dict[str, Any]): Dictionary mapping film URLs to metadata elements.

    Returns:
        Tuple containing:
            - target_el (Any): The XML element containing the film's metadata.
            - film_url (str): The generated URL for the film page.
            - review_url (str): The original URL for the review page.
            
    Raises:
        KeyError: If the article_key or the generated film_url is not found in the provided dictionaries.
    """
    # URL Transformation Constants
    SOURCE_HEADER = 'fichefilm-'
    SOURCE_FOOTER = '/critiques/spectateurs'
    TARGET_HEADER = 'fichefilm_gen_cfilm='
    TARGET_FOOTER = '.html'

    # Retrieve the review URL using the article key
    review_url = key_url_dict[article_key]
    
    # Construct the film URL by replacing the header and footer
    film_url = (
        review_url.replace(SOURCE_HEADER, TARGET_HEADER)
                   .replace(SOURCE_FOOTER, TARGET_FOOTER)
    )
    
    # Retrieve the metadata element using the constructed film URL
    target_el = metadata_detail_dict[film_url]
    
    return target_el, film_url, review_url


def consolidate_metas(
    key_url_dict: Dict[str, str], 
    metadata_detail_dict: Dict[str, Any], 
    xml_conll_file: str, 
    output_dir: str
):
    """
    Enriches a CoNLL XML file with metadata by mapping article keys to film details.

    Args:
        key_url_dict (Dict): Mapping of article keys to review URLs.
        metadata_detail_dict (Dict): Mapping of film URLs to metadata XML elements.
        xml_conll_file (str): Path to the input CoNLL XML file.
        output_dir (str): Directory where the processed XML file will be saved.
    """
    # Parse the input XML file
    review_tree = etree.parse(xml_conll_file)
    reviews = review_tree.xpath(".//TEI.2")
    
    # Define a mapping of {xml_attribute_name: metadata_element_attribute}
    # This replaces the long list of repetitive .set() calls
    METADATA_MAP = {
        "genre": "genre",
        "director": "director",
        "press_rating": "press_rating",
        "spect_rating": "spect_rating",
        "duration": "duration_tidy",
        "rel_yyyy": "rel_yyyy",
        "rel_mm": "rel_mm",
        "rel_dd": "rel_dd",
    }

    for review in tqdm(reviews, desc="Consolidating metadata"):
        # 1. Extract the original title/key
        title_elements = review.xpath(".//title")
        if not title_elements:
            continue
        
        temp_title = title_elements[0].text
        
        try:
            # Retrieve metadata using the helper function from the previous step
            metadata_el, film_url, review_url = get_urls_and_el_from_article_key(
                temp_title, key_url_dict, metadata_detail_dict
            )
            
            # 2. Update the title with the official metadata title
            title_elements[0].text = metadata_el.get("title")
            
            # 3. Update sourceDesc element
            sourcedesc_elements = review.xpath(".//sourceDesc")
            if sourcedesc_elements:
                sourcedesc_el = sourcedesc_elements[0]
                
                # Handle the split of the article key (e.g., "123_set4")
                if "_set" in temp_title:
                    orig_split, orig_number = temp_title.split("_set", 1)
                    sourcedesc_el.set("orig_split", str(orig_split))
                    sourcedesc_el.set("orig_number", str(orig_number))
                
                # Set URL information
                sourcedesc_el.set("review_url", str(review_url))
                sourcedesc_el.set("film_url", str(film_url))
                
                # Set all other metadata attributes using the map
                for xml_attr, meta_attr in METADATA_MAP.items():
                    val = metadata_el.get(meta_attr)
                    if val:
                        sourcedesc_el.set(xml_attr, str(val))
            
            # 4. Set text type to 'review'
            textdesc_elements = review.xpath(".//textDesc")
            if textdesc_elements:
                textdesc_elements[0].set("type", "review")
                
        except (KeyError, IndexError) as e:
            # Log error or skip if the article key isn't found in the metadata dicts
            print(f"Skipping {temp_title}: Metadata not found. Error: {e}")
            continue
    
    # Construct output path and save
    output_path = Path(output_dir) / os.path.basename(xml_conll_file)
    review_tree.write(output_path, encoding='UTF-8', pretty_print=True, xml_declaration=True)

def final_consolidator(output_dir):
    """
    Aggregates all XML files from a source directory into a single combined XML document.

    The function performs the following steps:
    1. Identifies and sorts all files with the '.xml' extension in the target directory.
    2. Initializes a new XML root element named <teiCorpus>.
    3. Iterates through each discovered XML file, parses its content, and appends 
       the root element of that file as a child of the main <TEI.2> element.
    4. Writes the resulting combined XML tree to a file named 'combined.xml' 
       with UTF-8 encoding and pretty-printed formatting.

    Note:
        Currently uses hard-coded file paths for input and output. 
        A progress bar is displayed during the merging process via tqdm.

    Returns:
        None
    """
    output_filename_full = f'{output_dir}/single_output.xml'
    input_files = sorted([str(p) for p in Path(source_dir).glob("*.xml")])
    if len(input_files) ==0:
        print(f"Error : no files found in {output_dir} with the extension «.xml» ")
    else:
        print(f"Consolidating {len(input_files)} files :::: ")
        output_tree_element = etree.Element("teiCorpus")
        for f in tqdm(input_files):
            current_input = etree.parse(f)
            output_tree_element.append(current_input.getroot())
    
    output_tree =etree.ElementTree(output_tree_element)
    output_tree.write(output_filename_full, encoding='UTF-8', pretty_print=True)
    print(f"Complete :: single file exported to {output_filename_full}")



def run_consolidator(file_list: List[str], output_dir: str, key_url_json_file: str, metadata_xml_file: str):
    """
    Main orchestrator that loads metadata and processes a list of CoNLL XML files.

    Args:
        file_list (List[str]): List of paths to the XML files to be processed.
        output_dir (str): Directory where processed files will be saved.
        key_url_json_file (str): Path to the JSON file mapping keys to URLs.
        metadata_xml_file (str): Path to the XML file containing film metadata.
    """
    # Ensure the output directory exists before processing
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Load metadata dictionaries
    key_url_dict, metadata_detail_dict = load_meta_dicts(key_url_json_file, metadata_xml_file)
    
    print(f"Processing {len(file_list)} files...")

    for xml_conll_file in file_list:
        consolidate_metas(
            key_url_dict=key_url_dict, 
            metadata_detail_dict=metadata_detail_dict, 
            xml_conll_file=xml_conll_file, 
            output_dir=output_dir
        )
        
    print("All files processed successfully.")



if __name__ == "__main__":
    # Initialize the argument parser
    parser = argparse.ArgumentParser(
        description="Consolidate metadata in parsed reviews",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Required argument: source file path
    parser.add_argument(
        "-source_dir", 
        type=str, 
        required=True, 
        help="Folder with XML-conllu files in which to consolidate metadata"
    )

    # Required argument: output dir
    parser.add_argument(
        "-output_dir", 
        type=str, 
        required=True, 
        help="Folder where exported files will be written"
    )

    # Required argument: json_metas
    parser.add_argument(
        "-json_metas", 
        type=str, 
        required=True, 
        help="Path to json file with key-url dict"
    )

    # Required argument: output dir
    parser.add_argument(
        "-xml_metas", 
        type=str, 
        required=True, 
        help="Path to XML file with review metadata"
    )

    # Optional arguments: limit
    parser.add_argument(
        "-limit", 
        type=int, 
        required=False, 
        help="Number of files to process"
    )

    parser.add_argument(
        "-offset", 
        type=int, 
        required=False, 
        help="Offset start by this many files"
    )

    parser.add_argument(
        "--singleExport", 
        action="store_true",
        default=False, 
        help="Consolidate all outputs into single file"
    )

    # Parse the arguments from the command line

    args = parser.parse_args()
    source_dir = args.source_dir
    output_dir = args.output_dir
    key_url_json_file = args.json_metas
    metadata_xml_file = args.xml_metas
    file_list = sorted([str(p) for p in Path(source_dir).glob("*.xml")])
    if args.limit and args.offset:
      file_list = file_list[args.offset:args.limit]
    elif args.limit:
      file_list = file_list[args.offset:args.limit]
    elif args.offset:
      file_list = file_list[args.offset:]
    single_export = args.singleExport
    # Execute the main pipeline
    print(f"Running consol for {len(file_list)} files")
    run_consolidator(file_list, output_dir, key_url_json_file, metadata_xml_file)
    if single_export:
      final_consolidator(output_dir)






