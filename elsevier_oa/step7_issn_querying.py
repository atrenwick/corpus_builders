## get ISSN info
import argparse
import json
import os
import requests
import time

from dotenv import load_dotenv
from pathlib import Path
from tqdm import tqdm
from typing import Any, Dict, Final, List, Tuple, Union

from concurrent.futures import ThreadPoolExecutor, as_completed


# Define the global variable at the module level
MY_KEY: str = ""

def load_secrets() -> None:
    """
    Loads environment variables from a local secrets.env file.

    This function constructs the path to 'secrets.env' based on the 
    current file's location, loads the environment variables into 
    the system environment, and populates the global `MY_KEY` 
    variable with the value of 'MY_API_KEY'.

    Returns:
        None

    Raises:
        KeyError: If 'MY_API_KEY' is missing from the environment.
    """
    global MY_KEY
    
    # Resolve the path to secrets.env relative to this script
    env_path = Path(__file__).resolve().parent / "secrets.env"
    
    # Load the variables
    load_dotenv(env_path)
    
    try:
        MY_KEY = os.environ["MY_API_KEY"]
        print("key loaded: as MY_KEY")
    except KeyError:
        print("Error: MY_API_KEY not found in secrets.env")
    except Exception as e:
        print(f"Error: {e}")

### part 1 : get local metadata

def get_files(folder_with_jsons: str) -> List[Path]:
    """
    Recursively finds and returns a sorted list of JSON files in subdirectories.

    This function takes a directory path, identifies all immediate subdirectories 
    within it, and collects every file ending in ".json" from those subfolders. 
    The results are sorted alphabetically by directory name and then by filename.

    Args:
        folder_with_jsons (str): The file path to the root directory containing 
            the subfolders that hold JSON files.

    Returns:
        List[Path]: A sorted list of pathlib.Path objects representing the 
            discovered JSON files.
    """
    path_to_jsons = Path(folder_with_jsons)
    json_files: List[Path] = []
    
    # Identify subdirectories and sort them alphabetically
    folders = sorted([ 
        p for p in path_to_jsons.iterdir() if p.is_dir() 
    ])
    
    for folder in folders:
        # Find all .json files in the current subdirectory and sort them
        files = sorted(folder.glob("*.json"))
        json_files.extend(files)
        
    print(f"Found {len(json_files)} files")
    return json_files

def refactor_metas(json_file: Path) -> Tuple[str, Dict[str, str]]:
    """
    Parses a JSON file to extract and normalize metadata into a structured dictionary.

    This function reads a JSON file, extracts specific fields from the 
    'metadata' object  and returns a cleaned dictionary along with the document ID.

    Args:
        json_file (Path): The Path object pointing to the source JSON file.

    Returns:
        Tuple[str, Dict[str, str]]: A tuple containing:
            - docId (str): The stem of the filename.
            - refactored_dict (Dict[str, str]): A dictionary of normalized metadata.

    Raises:
        FileNotFoundError: If the provided path does not exist.
        json.JSONDecodeError: If the file content is not valid JSON.
        KeyError: If the 'metadata' key is missing from the JSON.
    """
    docId = json_file.stem
    
    with open(json_file, 'r', encoding='utf-8') as f:
        input_dict = json.load(f)
    
    # Extract metadata dictionary safely
    metadata = input_dict.get('metadata', {})
    
    # Extract author info safely
    authors = metadata.get('authors', [])
    if authors and isinstance(authors, list) and len(authors) > 0:
        last_name = authors[0].get('last', 'Unknown')
        first_author = f"{last_name} et al."
    else:
        first_author = 'NA'

    ## page info
    try:
        pageinfo  = f"p. {str(metadata['firstpage'])}-{str(metadata['lastpage'])}"
    except Exception as e:
        pageinfo = 'unknown pages'


    # Helper to get values and ensure they are strings
    def get_str(key: str, default: str = "NA") -> str:
        val = metadata.get(key, default)
        return str(val) if val is not None else default

    refactored_dict = {
        "docId": docId,
        "first_author": first_author,
        "title": get_str('title'),
        "year": get_str('pub_year'),
        "journal_issn": get_str('issn'),
        "article_subj": get_str('subjareas'),
        "issue": get_str('issue', "_"),
        "doi": get_str('doi',"_"),
        "pageinfo": pageinfo,
        "number": get_str('number', "_"),
        "volume": get_str('volume', "_"),
    }

    return docId, refactored_dict

def make_dict(folder_with_jsons: str) -> List[str]:
    """
    Processes all JSON files in subdirectories, refactors their metadata,
    saves the results to disk, and extracts unique ISSNs.

    This function uses a ThreadPoolExecutor to parallelize the refactoring 
    of JSON files. It saves two files: a master metadata dictionary and 
    a unique list of ISSNs.

    Args:
        folder_with_jsons (str): The path to the directory containing subfolders 
            of JSON files.

    Returns:
        List[str]: A sorted list of unique journal ISSNs found in the metadata.

    Raises:
        FileNotFoundError: If the provided directory path does not exist.
    """
    path_obj = Path(folder_with_jsons)
    json_files = get_files(folder_with_jsons)
    
    # Parallel processing of files
    # Using chunksize helps with overhead when dealing with many small files
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        results = list(tqdm(
            executor.map(refactor_metas, json_files, chunksize=128),
            total=len(json_files),
            desc="Refactoring Metadata"
        ))
    
    # Convert list of tuples [(docId, dict), ...] into a single dictionary
    output_dict: Dict[str, Dict[str, str]] = {doc_id: meta for doc_id, meta in results}
    
    # Define output paths (saved in the parent directory of the input folder)
    base_path = path_obj.parent
    metadata_dict_file = base_path / "metadata_dict.json"
    issn_list_file = base_path / "issn_list.json"

    # Save the full metadata dictionary
    with open(metadata_dict_file, 'w', encoding='UTF-8') as j:
        json.dump(output_dict, j, indent=2)
    print(f'Metadata dict saved to {metadata_dict_file}')

    # Get unique ISSNs for which we need to get titles, subjects
    issns = [
        v.get('journal_issn', "X") 
        for v in output_dict.values() 
        if isinstance(v, dict)
    ]
    
    tidy_issns = sorted(list(set(issns)))
    
    # Save the unique ISSNs as a dictionary (issn: "")
    issns_as_dict = {issn: "" for issn in tidy_issns}
    with open(issn_list_file, 'w', encoding='UTF-8') as j:
        json.dump(issns_as_dict, j, indent=2)
    print(f'ISSN list saved to {issn_list_file}')

    return tidy_issns

# part 2 : get metadata from remote

def process_one_issn(issn: str) -> Dict[str, str]:
    """
    Fetches and parses metadata for a specific ISSN from the Elsevier API.

    This function queries the Elsevier content API for serial title information
    based on an ISSN. It extracts the subject area abbreviation and the 
    publication title, providing fallback values in case of missing data or 
    network errors.

    Args:
        issn (str): The International Standard Serial Number to query.

    Returns:
        Dict[str, str]: A dictionary containing:
            - status_code (str): The HTTP status or a custom error string.
            - serial_metas (str): The result status ("success", "serial_error", etc.).
            - subj_code (str): The subject area abbreviation or "UNK"/"NA".
            - title (str): The publication title or "UNK"/"NA".

    Example:
        >>> process_one_issn("1234-5678")
        {'status_code': '200', 'serial_metas': 'success', 'subj_code': 'SCI', 'title': 'Nature'}
    """
    params = {"mailto": 'mailto_email'}
    url = f'https://api.elsevier.com/content/serial/title/issn/{issn}?apiKey={MY_KEY}'

    # Helper function to standardize error responses and reduce code duplication
    def make_error_res(status: str, meta_msg: str) -> Dict[str, str]:
        return {
            "status_code": status,
            "serial_metas": meta_msg,
            "subj_code": "NA",
            "title": "NA"
        }

    try:
        resp = requests.get(url, params=params, timeout=10)
        
        # Check for HTTP errors immediately
        if resp.status_code != 200:
            return make_error_res(str(resp.status_code), "Request Error")

        # Attempt to decode JSON
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return make_error_res(str(resp.status_code), "json_decode_error")

        # Validate the presence of the required response key
        msg = data.get("serial-metadata-response")
        if not msg:
            return make_error_res(str(resp.status_code), "serial_error")

        # Extract data using safe navigation
        try:
            # msg['entry'][0] is the standard structure for Elsevier entries
            entry = msg['entry'][0]
            
            # Get subject code with a fallback
            try:
                subj_code = entry['subject-area'][0]['@abbrev']
            except (KeyError, IndexError, TypeError):
                subj_code = "UNK"
            
            # Get title with a fallback
            try:
                title = entry['dc:title']
            except (KeyError, IndexError, TypeError):
                title = "UNK"

            return {
                "status_code": str(resp.status_code),
                "serial_metas": "success",
                "subj_code": subj_code,
                "title": title
            }

        except Exception:
            return make_error_res(str(resp.status_code), "Exception_error")

    except requests.RequestException:
        # Catches timeouts, DNS issues, etc.
        return make_error_res("GET error", "Connection Error")
    except Exception as e:
        # Catch-all for any other unexpected issues
        print(f"Unexpected error: {e}")
        return make_error_res("Error", "Unknown Exception")

def flush_dict_buffer(data: Dict[str, Any], file_path: Path) -> None:
    """
    Writes a dictionary to a JSON file.
    
    Args:
        data (Dict[str, Any]): The dictionary to save.
        file_path (Path): The path where the JSON should be saved.
    """
    with open(file_path, 'a', encoding='UTF-8') as j:
        for key, value in data.items():
            j.write(json.dumps({key: value}) + '\n')

def run_issn_querying(
    folder_with_jsons: str, 
    tidy_issns: List[str], 
    delay: int, 
    qtest: bool, 
    number: int,
    buffer: int,
) -> None:
    """
    Queries Elsevier API for multiple ISSNs with batch processing and rate limiting.

    This function iterates through a list of ISSNs, queries their metadata,
    and separates the results into success and error categories. To optimize 
    performance and prevent memory issues, it flushes the results to disk 
    every `buffer` iterations.

    Args:
        folder_with_jsons (str): The path to the directory containing JSON files.
        tidy_issns (List[str]): A list of unique ISSN strings to query.
        delay (int): Seconds to wait between each API request.
        qtest (bool): If True, only queries a subset of the ISSNs.
        number (int): The number of ISSNs to query if `qtest` is True.
        buffer (int): The number items to hold in the buffer before writing to file.

    Returns:
        None
    """
    
    load_secrets()
    
    success_dict: Dict[str, Any] = {}
    error_dict: Dict[str, Any] = {}
    
    # Setup Paths
    base_path = Path(folder_with_jsons).parent
    success_output_file = base_path / "issn_success_data.json"
    error_output_file = base_path / "issn_error_data.json"
    
    print(f"Exporting success ->> {success_output_file}")
    print(f"Exporting errors ->> {error_output_file}")

    # Determine target list (Fixes the bug where these_issns was undefined if qtest=False)
    if qtest:
        these_issns = tidy_issns[:int(number)]
    else:
        these_issns = tidy_issns

    print(f"Running queries on {len(these_issns)} issns with batch == {buffer} and delay = {delay}")

    for num, issn in tqdm(enumerate(these_issns, start=1), desc="Querying ISSNs"):
        result = process_one_issn(issn)
        
        if result.get('serial_metas') != "success":
            error_dict[issn] = result
        else:
            success_dict[issn] = result
            print(f'ISSN {issn} == {result["title"]} :: subj = {result["subj_code"]}')
        
        # Batch Flush Logic
        if num % buffer == 0:
            flush_dict_buffer(success_dict, success_output_file)
            flush_dict_buffer(error_dict, error_output_file)
            # Reset buffers
            success_dict.clear()
            error_dict.clear()
        
        time.sleep(delay)


def load_issns_from_json(issn_infile: str) -> List[str]:
    """
    Loads a list of ISSNs from a JSON file.

    This function opens a JSON file where the top-level keys are expected to be 
    ISSNs. It extracts these keys into a list and returns them.

    Args:
        issn_infile (str): The file path (as a string) to the JSON file 
            containing the ISSNs.

    Returns:
        List[str]: A list of unique ISSN strings extracted from the JSON keys.

    Raises:
        FileNotFoundError: If the provided file path does not exist.
        json.JSONDecodeError: If the file is not a valid JSON format.
    """
    # Ensure the input is treated as a Path object for robust path handling
    file_path = Path(issn_infile)
    
    with open(file_path, 'r', encoding='UTF-8') as j:
        input_dict = json.load(j)
    
    # Extract keys into a list
    issn_tidy = list(input_dict.keys())
    
    print(f"ISSNs loaded from {file_path.name} successfully")
    return issn_tidy

def main(
    folder_with_jsons: str, 
    delay: int, 
    skip: Union[str, int], 
    qtest: bool, 
    number: int, 
    issn_infile: str,
    buffer: int
) -> None:
    """
    Main entry point for the ISSN querying pipeline.

    This function coordinates the workflow of either generating a metadata dictionary 
    from local JSON files or loading a pre-existing list of ISSNs from a file. 
    Once the ISSN list is obtained, it executes the querying process with 
    specified batching, delays, and testing parameters.

    Args:
        folder_with_jsons (str): Path to the folder containing the source JSON files.
        delay (float): The sleep duration (in seconds) between each API request.
        skip (Union[str, int]): A flag to determine the data source. 
            If "1" or 1, loads from `issn_infile`. Otherwise, runs `make_dict`.
        qtest (bool): If True, only processes a subset of the ISSNs.
        number (int): The number of ISSNs to process if `qtest` is True.
        issn_infile (str): The file path to the JSON file containing ISSNs 
            (used only if `skip` is active).
        buffer (int) : Maximum number of items to hold in buffer before writing 
            to file and flushing buffer.

    Returns:
        None
    """
    
    # Determine the source of the ISSNs
    if skip not in ("1", 1):
        # Standard flow: Generate dict from folder
        tidy_issns = make_dict(folder_with_jsons)
    
    else:
        # Skip flow: Load from provided file
        try:
            print("Working in skip1 mode...")
            tidy_issns = load_issns_from_json(issn_infile)
        except Exception as e:
            print(f"Error loading ISSNs from file: {e}")
            raise

    if skip not in (2,"2"):
    # Execute the query process
        run_issn_querying(
            folder_with_jsons=folder_with_jsons, 
            tidy_issns=tidy_issns, 
            delay=delay, 
            qtest=qtest, 
            number=number,
            buffer=buffer
        )



    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deal with metadata and ISSNs")
    
    parser.add_argument(
        "--json_source", 
        type=str,
        required=True,
        help="Path to dir with original json files"
    )
    parser.add_argument(
        "-d", "--delay", 
        type=int,        
        default=30.0,
        metavar="N",
        help="Delay time in seconds between API requests"
    )
    parser.add_argument(
        "-s", "--skip", 
        type=str,
        default="0",
        help="Skip flag (set to '1' to skip reparsing of source JSONs and load from issn_infile instead of folder. Set to 2 to skip API querying.)"
    )
    parser.add_argument(
        "--q_test", 
        action="store_true", 
        required=False, 
        default=False, 
        help="Run test queries only"
    )
    parser.add_argument(
        "--number", 
        type=int,
        default=10,
        metavar="N",
        help="How many tests to do"
    )
    parser.add_argument(
        "--issn_infile", 
        type=str,
        required=False, 
        default="",
        help="Path to existing file of issns"
    )
    parser.add_argument(
        "-b", "--buffer", 
        type=int,
        required=False, 
        default=10,
        help="Number of results to hold in buffer"
    )
    

    args = parser.parse_args()
    
    main(
        folder_with_jsons=Path(args.json_source),
        delay=int(args.delay),      
        skip=args.skip,  
        qtest=bool(args.q_test),
        number=int(args.number),
        issn_infile=Path(args.issn_infile),
        buffer=int(args.buffer)
    ) 
    
    
    
