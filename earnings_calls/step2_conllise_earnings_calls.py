"""Sentencise and convert Earnings call transcripts to conll format"""
import argparse
import hashlib
import json
import os
import re

from dataclasses import dataclass
from functools import partial
from typing import Dict, List, Tuple, Any
from pathlib import Path

from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd
import spacy
from stanza.models.common.doc import Sentence
from tqdm import tqdm

@dataclass
class ConllisationProcessingConfig:
    """Configuration for conllisation of earnings calls.

    Bundles the paths, identifiers, and runtime options needed by
    `run_main()` to process a batch of files, so they can be passed
    around as a set of arguments.

    Attributes:
        source_dir: Path to the folder with parquet files.
        output_dir: Path to dir where conll files will be exported.
        nprocs (int, optional): Maximum number of processes to use.
            Defaults to the number of CPU cores.
        chunk_size: Number of sentences per conll file
        export_jsons: Export intermediate results as json files
        verbose: add extra print statements of progress, values…. 
    """
    input_dir: str
    output_dir: str
    n_procs: int
    chunk_size: int
    export_jsons: bool
    verbose: bool

# Pre-compile the regex for better performance
SPEAKER_PATTERN = re.compile(r'^([A-Z][a-z]+ [A-Z][a-z]+)\s*:\s*')
CONLL_LINETAIL = "\t_\t_\t_\t_\t_\t_\t_\t_\n"

# Global NLP object to be initialized in each worker process
NLP = None

def get_next_quarterdate(datafqrt: str) -> Tuple[str, str, str]:
    """Calculates the first day of the first month of the next fiscal quarter.

    If a fiscal quarter (e.g., '2023Q3') is provided, this function determines
    the first day of the first month of the subsequent quarter. If the input
    is the 4th quarter, it rolls over to the 1st quarter of the following year.

    Args:
        datafqrt (str): A string representing the fiscal quarter reported for
            (expected format: 'YYYYQX', e.g., '2023Q3').

    Returns:
        Tuple[str, str, str]: A tuple containing the next quarter's
            (year, month, day) as strings.
    """
    quarters = {
        '1': ['01', '01'],
        '2': ['04', '01'],
        '3': ['07', '01'],
        '4': ['10', '01']
    }

    this_year = datafqrt[:4]
    qrt = datafqrt[-1]

    # Check if the current quarter is 1, 2, or 3 to determine the next quarter
    if qrt in ('1', '2', '3'):
        next_qrt = str(int(qrt) + 1)
    else:
        next_qrt = '1'
        this_year = str(int(this_year) + 1)

    this_month, this_day = quarters[next_qrt]
    return this_year, this_month, this_day

def make_arrays(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Converts DataFrame columns into a dictionary of NumPy arrays \
    and handles missing date parsing.

    Extract metadata columns from a DataFrame and txt of the transcript. It specifically
    processes the 'earnings_date' column to extract year, month, and day. If a
    date is missing or invalid, it falls back to using the 'datafqtr' column
    via the `get_next_quarterdate` function to estimate the date.

    Args:
        df (pd.DataFrame): A pandas DataFrame containing at least the following columns:
            'company', 'quarter', 'earnings_date', 'datafqtr', and 'transcript'.

    Returns:
        Dict[str, np.ndarray]: A dictionary where keys are string identifiers and
            values are NumPy arrays containing the extracted data.
            Keys are: 'id_array', 'years_arr', 'months_arr', 'days_arr',
            'text_array', 'acutaldates_array', 'companies_array',
            'quarters_array', and 'datafqtr_array'.
    """
    acutaldates_array = df['earnings_date'].values
    datafqtr_array = df['datafqtr'].values

    years_list, days_list, months_list = [], [], []

    for x, date in enumerate(acutaldates_array):
        # Check if date is a valid string format (YYYY-MM-DD)
        if isinstance(date, str) and len(str(date).split("-")) == 3:
            date_str = str(date)
            years_list.append(date_str.split('-', maxsplit=1)[0])
            months_list.append(date_str.split("-")[1])
            days_list.append(date_str.split("-")[2])
        else:
            # Fallback: use the datafqtr to calculate the next quarter's start date
            item = datafqtr_array[x]
            this_year, this_month, this_day = get_next_quarterdate(item)
            years_list.append(this_year)
            months_list.append(this_month)
            days_list.append(this_day)

    my_arrays = {
        "id_array": df.index.values,
        "years_arr": np.array(years_list),
        "months_arr": np.array(months_list),
        "days_arr": np.array(days_list),
        "text_array": df['transcript'].values,
        "acutaldates_array": acutaldates_array,
        "companies_array": df['company'].values,
        "quarters_array": df['quarter'].values,
        "datafqtr_array": datafqtr_array
    }

    return my_arrays

def make_dicts(
    my_arrays: Dict[str, np.ndarray],
    parquet_file: str,
    output_dir: str,
    export_jsons: bool = False,
    verbose: bool = False
    ) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Groups data by year into dictionaries and optionally exports them to JSON.

    Process the arrays generated by `make_arrays`, groups the
    records by year, and organizes them into a nested dictionary structure.
    If `export_jsons` is True, it saves each year's data into a separate JSON file.

    Args:
        my_arrays (Dict[str, np.ndarray]): Dictionary containing NumPy arrays
            of the dataset (keys: 'id_array', 'years_arr', etc.).
        parquet_file (str): Path to the source parquet file (used for naming).
        export_jsons (bool, optional): Whether to export the grouped data to
            JSON files. Defaults to False.
        verbose (bool, optional): Whether to print the paths of exported
            files. Defaults to False.

    Returns:
        Tuple[str, List[Dict[str, Any]], Dict[str, Any]]: A tuple containing:
            - output_dir (str): The path to the directory where JSONs are saved.
            - output_dictlist (List): A list of dictionaries grouped by year.
            - print_info (Dict): Metadata containing the number of year
              splits and the filename.
    """
    # Setup output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    source_short = Path(parquet_file).stem
    target_years = sorted(set(my_arrays['years_arr']))
    print_info = {'y_splits': len(target_years), 'file': source_short}

    # Group data by year in a single pass O(N) instead of O(Y*N)
    grouped_data = {year: {} for year in target_years}

    grouped_data = populate_dict(my_arrays, grouped_data)
    output_dictlist = []

    # Iterate through sorted years to handle export and final list construction
    for target_year in target_years:
        tidy_dict = grouped_data[target_year]

        if export_jsons:
            export_verbosity_helper(output_dir, source_short, target_year, tidy_dict, verbose)

        # Wrap in a top-level key
        top_key = f"{source_short}_{target_year}"
        output_dictlist.append({top_key: tidy_dict})

    return output_dictlist, print_info

def populate_dict(
    my_arrays: Dict[str, np.ndarray],
    grouped_data: Dict[str, Dict[int, Dict[str, Any]]]
    ) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Populates a nested dictionary with records extracted from parallel arrays.

    This function iterates through a set of parallel arrays (contained within a 
    dictionary) to construct individual record dictionaries. These records are 
    then inserted into a nested dictionary structure organized by year and 
    sequential index.

    Args:
        my_arrays (Dict[str, Any]): A dictionary where keys correspond to array 
            names (e.g., 'id_array', 'years_arr', 'text_array', 'companies_array', 
            'quarters_array', 'datafqtr_array', 'acutaldates_array', 'months_arr', 
            'days_arr') and values are array-like objects supporting `.size` 
            and integer indexing.
        grouped_data (Dict[str, Dict[int, Dict[str, Any]]]): A nested dictionary 
            to be populated. The first level keys are the years (e.g., '2023'), 
            and the second level keys are integers representing the sequence 
            index.

    Returns:
        Dict[str, Dict[int, Dict[str, Any]]]: The populated nested dictionary.
    """
    for i in range(my_arrays['id_array'].size):
        year = my_arrays['years_arr'][i]

        # Construct the record for this row
        record = {
            "id": str(my_arrays['id_array'][i]),
            "txt": my_arrays['text_array'][i],
            "company": my_arrays['companies_array'][i],
            "quarter": my_arrays['quarters_array'][i],
            "fqtr": my_arrays['datafqtr_array'][i],
            "acutaldate": my_arrays['acutaldates_array'][i],
            "month": my_arrays['months_arr'][i],
            "day":  my_arrays['days_arr'][i]
        }
        grouped_data[year][i] = record

    return grouped_data

def export_verbosity_helper(
    output_dir: str,
    source_short: str,
    target_year: str,
    tidy_dict: Dict[str, Any],
    verbose: bool
    ) -> None:
    """Exports a dictionary to a JSON file with a specific naming convention.

    The function constructs a filename using the source identifier and the target
    year, then writes the provided dictionary to that file as a JSON object.
    If verbose mode is enabled, the file path is printed to the console.

    Args:
        output_dir (str): The directory where the resulting JSON file will be saved.
        source_short (str): A short string identifier for the source (e.g., 'allocine').
        target_year (str): The year string to be included in the filename.
        tidy_dict (Dict[str, Any]): The dictionary of data to be serialized into JSON.
        verbose (bool): If True, the path of the output file will be printed
            to the console during execution.

    Returns:
        None: This function performs I/O operations and does not return a value.
    """
    output_file = Path(output_dir) / f"{source_short}_{target_year}.json"

    if verbose:
        print(output_file)

    with open(output_file, 'w', encoding='UTF-8') as f:
        json.dump(tidy_dict, f)

def make_hex_id(input_string: Any) -> str:
    """Generates a deterministic SHA-256 hexadecimal identifier from a given input.

    This function takes an input (converted to a string), encodes it as UTF-8,
    and produces a unique 64-character hexadecimal hash to be used as unique
    sentence ID

    Args:
        input_string (Any): The value to be hashed. While typically a string,
            any type that can be cast to a string will be accepted.

    Returns:
        str: The SHA-256 hash of the input represented as a hexadecimal string.
    """
    #cast to string and encode to bytes
    string_value = str(input_string)
    input_bytes = string_value.encode('utf-8')

    # Create a SHA-256 hash object, update with bytes
    sha256 = hashlib.sha256()
    sha256.update(input_bytes)

    # Get the hexadecimal representation of the hash
    hex_id = sha256.hexdigest()

    return hex_id

def make_tidy_article(valueset: Dict[str, Any]) -> str:
    """Cleans and normalizes a text article by removing noise and whitespace.

    This function extracts the 'txt' value from a dictionary and applies a
    series of regular expression substitutions to remove non-breaking spaces,
    carriage returns, tabs, newlines, multiple consecutive spaces, and
    Byte Order Marks (BOM).

    Args:
        valueset (Dict[str, Any]): A dictionary containing the article data.
            Must include the key 'txt' with the text content as a string.

    Returns:
        str: The cleaned and normalized version of the text.
    """
    this_art = valueset['txt']

    # Replace non-breaking spaces and carriage returns with standard spaces
    this_art = re.sub('\xa0', ' ', this_art)
    this_art = re.sub('\x0D', ' ', this_art)

    # Replace newlines, tabs, and carriage returns with a single space
    this_art = re.sub('\r|\n|\t', ' ', this_art)

    # Collapse multiple spaces into a single space
    this_art = re.sub('(  )+', ' ', this_art)
    this_art = re.sub('  ', ' ', this_art)

    # Remove leading space
    this_art = re.sub('^ ', '', this_art)

    # Remove Byte Order Marks (BOM)
    this_art = re.sub('\ufeff ', '', this_art)
    this_art = re.sub('\ufeff', '', this_art)

    return this_art

def run_pool(
    output_dictlist: List[Dict[str, Any]],
    print_info: Dict[str, Any],
    config: ConllisationProcessingConfig
    ) -> None:
    """Orchestrates the parallel processing of year-based dictionaries using a process pool.
    After calculating an appropriate number of workers, submit dictionaries to the
    `process_one_dict` function in the processor pool.

    Args:
        output_dictlist (List[Dict[str, Any]]): A list of dictionaries, where each
            dictionary represents a single year's data
        print_info (Dict[str, Any]): Metadata about the current job, expected to
            contain 'file' (filename) and 'y_splits' (number of years).
        config: ConllisationProcessingConfig containing:
            n_procs (int): The requested number of worker processes.
            output_dir (str): The directory path where processed outputs should be
                stored (passed to workers if needed).
            chunk_size (int) : number of sents per conll file to print
            verbose (bool) : print all print statements


    Returns:
        None
    """
    # Calculate an appropriate number of workers
    actual_procs = min(config.n_procs, len(output_dictlist), os.cpu_count() or 1)

    print(
        f"Processing file {print_info['file']} into "
        f"{print_info['y_splits']} year-based files with {actual_procs} workers"
    )

    # make a partial function to pass to pool executor, freezing the specified pickleable args
    worker_funct = partial(
      process_one_dict,
      output_dir = config.output_dir,
      chunk_size=config.chunk_size,
      verbose=config.verbose
      )
    # Use ProcessPoolExecutor for CPU-bound tasks
    # _init_worker is used to initialize global variables for each child process
    with ProcessPoolExecutor(max_workers=actual_procs, initializer=_init_worker) as ex:
        # Schedule all processing tasks
        futures = [ex.submit(worker_funct, subdict) for subdict in output_dictlist]

        # Wrap as_completed in tqdm for a visual progress bar
        for future in tqdm(as_completed(futures), total=len(futures)):
            try:
                # result() will raise any exception that occurred during the execution of the task
                future.result()
            except Exception as e:
                # Use tqdm.write to avoid breaking the progress bar formatting
                tqdm.write(f"failed: {e}")

def process_match(
    sentence: Sentence,
    sent_text: str,
    match: re.Match
    ) -> Tuple[str, int, str]:
    """Processes a regex match to extract a speaker's name and calculate the token offset.

    This function extracts the speaker's name from a regex match, identifies 
    how many tokens in the original sentence were part of that speaker prefix 
    (to help with positional alignment), and trims the speaker prefix from 
    the remaining sentence text.

    Args:
        sentence (Sentence): A CoNLL sentence object containing a list of 
            tokens with a .text attribute.
        sent_text (str): The raw string content of the sentence.
        match (re.Match): The regex match object representing the speaker 
            prefix (e.g., "Speaker Name:").

    Returns:
        Tuple[str, int, str]: A tuple containing:
            - The speaker's name (str).
            - The number of tokens consumed by the speaker prefix (int).
            - The remaining sentence text after removing the prefix (str).
    """
    # Extract speaker name and remove trailing colons/whitespace
    speaker_name = match.group(1).strip()

    # Calculate how many tokens the speaker prefix consumes
    # We find the index of the first character after the speaker prefix
    prefix_text = match.group(0)

    # Count tokens that make up the prefix to set the offset correctly
    # Based on previous context, we access the .tokens attribute
    offset = len([t for t in sentence if t.text in prefix_text])

    # Remove the matched prefix from the string and trim whitespace
    sent_text = sent_text[match.end():].strip()

    return speaker_name, offset, sent_text

def process_one_sentence(
    sent_metas_dict: Dict[str, Any],
    previous_speaker: str,
    sentence: Sentence
    ) -> Tuple[str, str]:
    """Processes a single sentence into a CoNLL-formatted block with speaker handling.

    This function detects if a sentence starts with a speaker prefix. If found, it 
    extracts the speaker's name and calculates an offset to skip the prefix tokens 
    during CoNLL generation. It then constructs a multi-line CoNLL block including 
    metadata headers (article number, unique IDs, and base metadata), the speaker 
    name, and the cleaned sentence text.

    Args:
        sent_metas_dict (Dict[str, Any]): A dictionary containing metadata for the 
            current sentence (e.g., 'idx', 'hex_id', 'sent_idx', 'meta_base').
        previous_speaker (str): The name of the speaker from the previous sentence.
        sentence (Sentence): A CoNLL sentence object containing tokens and text.

    Returns:
        Tuple[str, str]: A tuple containing:
            - A string representing the full CoNLL block for the sentence.
            - The name of the current speaker (updated if a new speaker was detected).
    """
    current_sent_lines = []

    # Convert sentence to string for speaker detection
    sent_text = sentence.text
    match = SPEAKER_PATTERN.match(sent_text)

    speaker_name = previous_speaker
    offset = 0

    # If the regex finds a speaker prefix (e.g., "John: Hello")
    if match:
        # Use the process_match helper to update speaker_name, offset, and clean sent_text
        # Note: process_match must be defined in the scope
        speaker_name, offset, sent_text = process_match(sentence, sent_text, match)

    # Construct the metadata header block
    current_sent_lines.append(
        f"# Article_num = {sent_metas_dict.get('idx', 'UNK')}\n"
        f"# sent_ID = {sent_metas_dict.get('hex_id','UNK')}-\
        {sent_metas_dict.get('sent_idx', 'UNK')}\n"
        f"# sent_id_serial = {sent_metas_dict.get('sent_idx', 'UNK')}\n"
        f"{sent_metas_dict.get('meta_base', 'UNK')}"
        f"# speakername={speaker_name}\n"
        f"# text = {sent_text}\n"
    )

    # Add tokens to the CoNLL block
    for token_idx, token in enumerate(sentence):
        if token_idx >= offset:
            # token_idx - offset + 1 ensures the actual content numbering starts at 1
            current_sent_lines.append(
                f"{token_idx - offset + 1}\t{token.text}{CONLL_LINETAIL}"
            )

    return_lines = "".join(current_sent_lines) + "\n"
    return return_lines, speaker_name


def make_conll_strings(articles_data: Dict[str, Any]) -> List[str]:
    """
    Converts a dictionary of article data into a list of CoNLL-formatted strings.

    Each string represents a sentence, containing metadata as comments (#)
    followed by tokens and their indices. It handles speaker identification
    at the start of sentences and tracks speaker continuity.

    Args:
        articles_data (Dict[str, Any]): A dictionary where keys are identifiers
            and values are dictionaries containing article content (including 'txt').

    Returns:
        List[str]: A list of strings, where each string is a formatted CoNLL
            block for a single sentence.
    """
    file_output = []

    for idx, (article_id, valueset) in enumerate(articles_data.items(), start=1):
        # Process article text and get NLP doc
        article_text = make_tidy_article(valueset)
        hex_id = make_hex_id(article_id)
        doc = NLP(article_text)
        previous_speaker = "UNK"
        meta_base = "".join([f'# {k}={v}\n' for k, v in valueset.items() if 'txt' not in k])

        # Pre-generate metadata that is constant for the whole article
        sent_metas_dict = {
          "idx":idx,
          "hex_id":hex_id,
          "meta_base":meta_base
          }

        for sent_idx, sentence in enumerate(doc.sents, start=1):
            # get return lines and update previous_speaker to current speaker
            sent_metas_dict['sent_idx'] = sent_idx
            return_lines, previous_speaker = process_one_sentence(
              sent_metas_dict,
              previous_speaker,
              sentence
            )
            file_output.append(return_lines)

    return file_output

def process_one_dict(
    output_dictlist_item: Dict[str, Any],
    output_dir: str,
    chunk_size: int,
    verbose: bool = False
) -> None:
    """
    Processes a single-item dictionary, converts its content to CoNLL format,
    and saves the result into one or more chunked files.

    Args:
        output_dictlist_item (Dict[str, Any]): A dictionary containing one entry
            where the key is the identifier and the value is the article data.
        output_dir (str): The directory path where the resulting .conll files
            should be saved.
        chunk_size (int, optional): The maximum number of sentences per file.
            Defaults to 50000, set from argparser
        verbose (bool, optional): If True, prints processing status to the console.
            Defaults to False.

    Returns:
        None
    """
    if not output_dictlist_item:
        if verbose:
            print("Provided dictionary is empty. Skipping.")
        return


    top_key, target_item = next(iter(output_dictlist_item.items()))

    if verbose:
        print(f"Processing {top_key}")

    # Convert the article data to CoNLL strings
    conll_strings = make_conll_strings(target_item)

    # Ensure the output directory exists
    base_path = Path(output_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    # Loop through the data in chunks using a step-based range
    for i, start_idx in enumerate(range(0, len(conll_strings), chunk_size), start=1):
        end_idx = start_idx + chunk_size
        chunk = conll_strings[start_idx:end_idx]

        # Create filename: e.g., "ArticleID_part01.conll"
        file_name = f"{top_key}_part{i:02d}.conll"
        output_file = base_path / file_name

        # Write the chunk to the file
        with open(output_file, 'w', encoding='UTF-8') as f:
            f.writelines(chunk)

        if verbose:
            print(f'{output_file} exported')

def _init_worker() -> None:
    """
    Initializes the global spaCy NLP pipeline for the worker process.

    This function is designed to be used as an 'initializer' in a
    multiprocessing Pool. By loading the model once per process
    rather than once per task, we significantly reduce memory
    overhead and startup time.
    """
    global NLP
    # Loading a blank English model with only the sentencizer
    NLP = spacy.blank("en")
    NLP.add_pipe("sentencizer")

def run_main(config: ConllisationProcessingConfig) -> None:
    """
    Main execution pipeline to process parquet files into CoNLL format.

    This function scans a directory for parquet files, extracts specific
    columns, converts the data into dictionaries, and distributes the
    processing across multiple CPU cores.

    Args:
      config: ConllisationProcessingConfig: Dataclass used to set the following parameters:
        input_dir (str): Path to the directory containing .parquet files.
        output_dir (str): Path to the directory where conll files will be written.
        n_procs (int): Number of processor cores to use for parallel execution.
        chunk_size (int): Number of sents per conll file.
        verbose (bool, optional): If True, prints detailed progress to
            the console. Defaults to False.

    Returns:
        None
    """
    print(f"Processing {config.input_dir} with {config.n_procs} requested cores.")

    # Columns required for processing; kept as a constant for maintainability
    target_cols = ['company', 'quarter', 'datafqtr', 'earnings_date', 'transcript']

    # get files from path
    input_path = Path(config.input_dir)
    parquet_files = sorted(list(input_path.glob("*.parquet")))

    if not parquet_files:
        print(f"No parquet files found in {config.input_dir}...")
        return

    for parquet_file in parquet_files:
        # 1. Load Parquet
        try:
            df = pd.read_parquet(parquet_file, columns=target_cols)
            if config.verbose:
                print(f"Loaded: {parquet_file.name}")
        except Exception as e:
            print(f"Error loading {parquet_file}: {e}")
            continue

        # 2. Transform data into arrays
        my_arrays = make_arrays(df)
        if config.verbose:
            print(f"Arrays built for {parquet_file.name}")

        # 3. Group arrays into dictionaries for processing
        output_dictlist, print_info = make_dicts(
            my_arrays,
            str(parquet_file),
            str(config.output_dir),
            config.export_jsons
        )
        if config.verbose:
            print(f"Dictionaries created for {parquet_file.name}")

        # 4. Execute parallel processing
        run_pool(output_dictlist, print_info, config)
        if config.verbose:
            print(f"Finished processing {config.parquet_file.name}\n" + "-"*30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='''Process parquet formatted earnings calls

    Usage :
      python3 /scripts/earnings_calls.py -input_dir /data/folder -n_procs 10
    ''')
    parser.add_argument(
        "-input_dir", type=str,help="path to folder with parquet files"
    )
    parser.add_argument(
        "-output_dir", type=Path, required=True,
        help="output directory, in which results and subfolders will be placed"
    )
    parser.add_argument(
        "-n_procs", type=int, default=2,
        help="Number of worker processes requested"
    )
    parser.add_argument(
        "-chunk_size", type=int, default=50000,
        help="Number of sentences per CoNLL file"
    )
    parser.add_argument(
        "-export_jsons", action="store_true", default=False,
        help="export jsons before connlisation"
    )
    parser.add_argument(
        "-verbose", action='store_true', default=False,
        help="Include print statements with paths at file export"
    )
    args = parser.parse_args()
    argparse_config = ConllisationProcessingConfig(
      args.input_dir,
      args.output_dir,
      args.n_procs,
      args.chunk_size,
      args.export_jsons,
      args.verbose
      )

    run_main(argparse_config)
