"""Make conll files for CC News articles with custom metas"""
# Standard library
import argparse
import glob
import hashlib
import importlib
import json
import math
import os
import re

from dataclasses import dataclass
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple, Union

# Third-party
import numpy as np
import pandas as pd
import polars as pl
from spacy.language import Language
from spacy.tokens import Span
from spacy.tokens import Doc
from tqdm import tqdm

@dataclass(frozen=True)
class FilteringConfiguration:
    """Configuration object for filtering dataset records.

    This class encapsulates the four required parameters used to filter 
    the dataset based on specific criteria such as type, value, 
    operational mode, and year.

    Attributes:
        filter_type (str): The category of the filter (e.g., 'genre', 'author').
        filter_value (str): The specific value to match (e.g., 'Drama', 'Hugo').
        mode (Literal['S', 'X']): 
          - "S" is strict mode: filter to only articles where scrape year is publication year
          - "X" is non-strict: i.e. accept any year X.\
             This means that articles from 1980 uploaded in 2025 can be\
             recognised as written in 2025.
        year (str): The target year for the filter (e.g., '2023').
    """
    filter_type: str
    filter_value: str
    mode: Literal['S', 'X']
    year: str

def filter_parquet(this_file: str, filter_type: str, filter_value: str) -> pl.DataFrame :
    '''
    Scan, filter and load a trimmed version of a polars dataframe 
    Inputs:
      this_file (str): absolute reference to a parquet file to parse with Polars
      filter_type (str) : `lang` to filter on language, `domain` to filter on domain
      filter_value (str) : a language code if filtering on the language column,
          or a domain + top level extension if filtering on a website
    Return:
      trimmed (pl.DataFrame) : a Polars df collected from only the rows matching the filter(s)
    '''
    df = pl.scan_parquet(this_file)
    filter_map = { "lang": pl.col("language") == filter_value,
          "domain": pl.col("requested_url").str.contains(rf'{filter_value}', literal=False) }

    if filter_type not in filter_map:
        raise ValueError(f"Unknown filter_type: {filter_type}")

    filtered_df = df.filter(filter_map[filter_type])
    trimmed = filtered_df.collect()

    return trimmed

def make_arrays(trimmed_df: Union[pd.DataFrame, pl.DataFrame]) -> Dict[str, np.ndarray]:
    """Extracts metadata from a DataFrame into a dictionary of NumPy arrays.

    This function takes a DataFrame (either Pandas or Polars), extracts specific 
    columns, and organizes them into a dictionary. It also performs a 
    transformation on the 'published_date' column to split it into 
    separate year, month, and day arrays.

    Args:
        trimmed_df (Union[pd.DataFrame, pl.DataFrame]): Dataframe trimmed from initial parquet df
        
    Returns:
        Dict[str, np.ndarray]: A dictionary where keys are column names 
            (e.g., 'url_array', 'years_arr') and values are NumPy arrays 
            containing the corresponding data.
    """

    years_list, days_list, months_list = [], [], []

    # Extract and split the publication date
    pub_date_arr = trimmed_df['published_date'].to_numpy()

    for date in pub_date_arr:
        # Split "YYYY-MM-DD" into components
        date_parts = date.split("-")
        years_list.append(date_parts[0])
        months_list.append(date_parts[1])
        days_list.append(date_parts[2])

    # Construct the dictionary of arrays with .to_numpy()
    my_arrays = {
        "url_array": trimmed_df['requested_url'].to_numpy(),
        "years_arr": np.array(years_list),
        "days_arr": np.array(days_list),
        "months_arr": np.array(months_list),
        "plain_tex_arr": trimmed_df['plain_text'].to_numpy(),
        "title_arr": trimmed_df['title'].to_numpy(),
        "author_arr": trimmed_df['author'].to_numpy(),
        "sitename_arr": trimmed_df['sitename'].to_numpy(),
        "resp_url_arr": trimmed_df['responded_url'].to_numpy(),
        "publisher_arr": trimmed_df['publisher'].to_numpy(),
        "warc_path_arr": trimmed_df['warc_path'].to_numpy(),
        "crawl_date_arr": trimmed_df['crawl_date'].to_numpy(),
    }

    return my_arrays

def run_exporter_to_json_dict(my_arrays, this_file, config: FilteringConfiguration):
    '''
    Export the arrays to a json file
    Inputs:
      my_arrays (Dict) : a dictionary of arrays containing metadata created by `make_arrays`
      this_file (string) : absolute path to the parquet file being used
      config (FilteringConfiguration): dataclass of filtering params, including:
        filter_type (str) : `lang` to filter on language, `domain` to filter on domain
        filter_value (str) : a language code if filtering on the language column, \
        or a domain + top level extension if filtering on a website
        mode (string) : indicate whether to process in strict mode or not. \
            If processing in strict mode, using `S`, the year in the crawl_date \
            metadata must match the year specified in the `year` argument.
        year (string) : 4 character string to indicate year being targeted
        
          ##TODO: is it better to get this from filename ??
          ##Note : the year arg in the filtering config points to `get me stuff from this year'
          ## and gets sent to target_years; years_array needs name tweak -> year_current
          ## there's really 5 years : 
          file year == the year in the parquet file name
          article year == the year the article was actually published
          scrape year == the year the article was scraped
          target year == the year I'm searching for
          current_year == year when iterating over a list of years…

    Returns:
      None. A json file will be printed in the same location as the source parquet file

    '''
    # make the path to the folder to write to
    source_short = this_file.replace(".parquet","")
    if config.filter_type =="domain":
        domain_tidy = re.sub(r'www_|_com','', config.filter_value.replace('.','_'))
        source_short = source_short.replace(f'{config.year}/',f'{config.year}/{domain_tidy}_')

    source_short = source_short.replace('0_raw_parquet','1_conllised_json')
    file_year = os.path.basename(this_file)[:4]

    ## use the `mode` argument to filter to the year specified as an argument
    if config.mode =="S":
        target_years = set({file_year})
    else:
        target_years = sorted(set(my_arrays['years_arr']))

    # for each target_year, make a dictionary with integer keys, values as dicts\
    #  built from the metadata arrays
    for target_year in target_years:
        tidy_dict = {}
        for i in range(my_arrays['url_array'].size):
            year = my_arrays['years_arr'][i]
            if year == target_year:
                values = {
                  "url":my_arrays['url_array'][i],
                  "txt": my_arrays['plain_tex_arr'][i],
                  "title" : my_arrays['title_arr'][i],
                  "author": my_arrays['author_arr'][i],
                  "site" : my_arrays['sitename_arr'][i],
                  "resp_url" : my_arrays['resp_url_arr'][i],
                  "publi"  : my_arrays['publisher_arr'][i],
                  "warc_path" : my_arrays['warc_path_arr'][i],
                  "crawl_date" : my_arrays['crawl_date_arr'][i],
                  "month" : my_arrays['months_arr'][i],
                  "day" : my_arrays['days_arr'][i]
                  }
                tidy_dict[i] = values

        ## add the target_year to the path where the json will be written, then write to the file
        outputfile = f'{source_short}_{target_year}.json'
        with open(outputfile, 'w', encoding='UTF-8') as k:
            json.dump(tidy_dict, k)
        print(f'Printed file {outputfile}')

def get_json_from_parquet(
  config: FilteringConfiguration,
  number:str,
  local_dir:Union[str,Path]=None
  ) -> None:
    '''
    Load, filter, extract and export articles from parquet files for a given year
    Inputs:
      config: (FilteringConfiguration) : dataclass of filtering parameters, including:
        filter_type (str) : `lang` to filter on language, `domain` to filter on domain
        filter_value (str) : a language code if filtering on the language column, \
          or a domain + top level extension if filtering on a website
        mode (string) : indicate whether to process in strict mode or not. \
        If processing in strict mode, using `S`, the year in the crawl_date metadata \
        must match the year specified in the `year` argument.
        year (str) : a year as 4 characters
    	number (int) : number of items at which to stop processing
      local_dir : str : default = None ; option to specify local dir in which to work
    Returns :
      No return object : a file will be printed or an error message will be printed to the console.

    '''
    if local_dir is None:
        these_files = glob.glob(f'/Volumes/HC3Beta/data/cc_corpus/{config.year}/*.parquet')
    else:
        these_files = glob.glob(f'{local_dir}/{config.year}/*.parquet')
    # get the list of files to process and restrict it if necessary, and confirm this
    if number !=0:
        these_files = these_files[:number]
    print(f'{len(these_files)} to process with domain filter')


    exportlog=[]
    # loop to process files, printing export log errors to console if any
    for this_file in tqdm(sorted(these_files)):
        try:
            trimmed= filter_parquet(this_file, config.filter_type, config.filter_value)
            if len(trimmed) ==0:
                print(f"\nNo hits in {os.path.basename(this_file)}")

            if len(trimmed) > 0:
                my_arrays = make_arrays(trimmed)

                run_exporter_to_json_dict(
                  my_arrays,
                  this_file,
                  config
                  )
        ## capture, log all exceptions to avoid crashing
        except Exception as e:
            report = this_file, e
            exportlog.append(report)

    if len(exportlog) >0:
        for item in exportlog:
            print(item)


def define_pipe(lang: str) -> Optional[Language]:
    """Dynamically imports and returns the correct spacy language model.
    
    Args:
        lang (str): The language code (e.g., 'fr', 'de', 'en', 'it', 'es').

    Returns:
        Optional[Language]: The initialized spacy language object, 
            or None if the language is unsupported.
    """
    # Map the language code to the spacy module path
    # We map the code to the path of the class we want to instantiate
    models = {
        "fr": "spacy.lang.fr.French",
        "de": "spacy.lang.de.German",
        "it": "spacy.lang.it.Italian",
        "en": "spacy.lang.en.English",
        "es": "spacy.lang.es.Spanish"
    }

    if lang not in models:
        print(f"Language '{lang}' not supported.")
        return None

    try:
        # 1. Dynamically import the module (e.g., 'spacy.lang.fr')
        module_path, class_name = models[lang].rsplit(".", 1)
        module = importlib.import_module(module_path)

        # 2. Get the class from the module (e.g., 'French')
        model_class = getattr(module, class_name)

        # 3. Instantiate the model
        nlp = model_class()

        # 4. Add the sentencizer as usual
        nlp.add_pipe("sentencizer")
        return nlp

    except ImportError as e:
        print(f"Error loading language module for {lang}: {e}")
        return None



def url_to_hex_id(url: str) -> str:
    """Creates a 256-bit SHA-256 hash from a URL.

    This function takes a URL string, encodes it into UTF-8 bytes,
    computes its SHA-256 hash, and returns the resulting hexadecimal
    digest. This is useful for creating unique, fixed-length identifiers
    for URLs.

    Args:
        url (str): The URL to be hashed.

    Returns:
        str: A hexadecimal string representing the 256-bit hash of the URL.
    """
    # Encode URL to bytes
    url_bytes = url.encode('utf-8')

    # Create a SHA-256 hash object, then update the hash object with URL bytes
    sha256 = hashlib.sha256()
    sha256.update(url_bytes)

    # Get the hexadecimal representation of the hash
    hex_id = sha256.hexdigest()

    return hex_id

def make_tidy_art_string(text: str) -> str:
    """Cleans and normalizes whitespace in a string.

    This function replaces non-breaking spaces (\xa0), carriage returns (\x0D), 
    newlines (\n), and tabs (\t) with standard spaces. It then collapses 
    multiple consecutive spaces into a single space to ensure a tidy string 
    representation.

    Args:
        text (str): The raw text to be cleaned and normalized.

    Returns:
        str: The normalized string with uniform spacing.
    """
    # Replace non-breaking spaces and carriage returns with standard spaces
    this_art = re.sub(r'\xa0', ' ', text)
    this_art = re.sub(r'\x0D', ' ', this_art)

    # Replace newlines, carriage returns, and tabs with spaces
    this_art = re.sub(r'\r|\n|\t', ' ', this_art)

    # Collapse multiple spaces into one
    this_art = re.sub(r' +', ' ', this_art)
    this_art = re.sub(r'  ', ' ', this_art)

    return this_art.strip()

def make_sent_metas(
    valueset: Dict[str, Any],
    sentence: Span,
    k: int,
    s: int
) -> str:
    """Generates CoNLL-formatted metadata headers for a single sentence.

    This function constructs a multi-line header block for a CoNLL file. It 
    includes article/sentence numbering, a unique hex ID derived from a URL, 
    all non-textual metadata from a provided dictionary, and the joined 
    text of the sentence.

    Args:
        valueset (Dict[str, Any]): A dictionary of metadata loaded from json.
        sentence (Span): A spaCy Sentence object containing the tokens 
            to be joined into text.
        k (int): The zero-based index of the current key in the JSON keylist
        s (int): The zero-based index of the current sentence.

    Returns:
        str: A string containing the full CoNLL metadata header block.
    """
    # Generate the unique hex ID from the URL
    hex_id = url_to_hex_id(valueset['url'])

    # Construct a block of metadata from the dictionary (excluding 'txt' keys)
    # Each entry is formatted as a comment: # key=value
    metas = "".join(
        [f"# {key}={value}\n" for key, value in valueset.items() if 'txt' not in key]
    )

    # Join tokens from the spaCy sentence into a single string
    # Using .text is the standard way to access the word in spaCy
    meta_text = " ".join([token.text for token in sentence])

    # Assemble the final multi-line CoNLL header
    # We use explicit newlines and f-strings for clarity and correct formatting
    meta_lines = (
        f"\n# Article_num = {k + 1}\n"
        f"# sent_ID = {hex_id}-{s + 1}\n"
        f"# sent_id_serial = {s + 1}\n"
        f"{metas}"
        f"# text = {meta_text}\n"
    )

    return meta_lines


def load_parse_json(
    input_file: Union[str, Path],
    method: Optional[Any] = None,
    tidy_dict: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Loads and parses a JSON file or returns a provided dictionary.

    This function serves as a flexible data loader. By default, it opens and 
    parses a JSON file from the provided `input_file`. If a `method` is 
    provided (i.e., is not None), it bypasses the file system and returns 
    the `tidy_dict` directly.

    Args:
        input_file (Union[str, Path]): The path to the JSON file to be loaded 
            (used only if `method` is None).
        method (Optional[Any], optional): A flag to indicate an alternative 
            loading method. If provided, the function returns `tidy_dict`. 
            Defaults to None.
        tidy_dict (Optional[Dict[str, Any]], optional): A pre-parsed dictionary 
            to be returned if `method` is not None. Defaults to None.

    Returns:
        Dict[str, Any]: The parsed JSON dictionary or the provided 
            `tidy_dict`.
    """
    ## normal usage is with no method == load from file
    if method is None:
        # Open, read, and parse the json data into a python dictionary
        with open(input_file, 'r', encoding="UTF-8") as j:
            json_input = j.read()
        return json.loads(json_input)

    # If a method is provided, return the provided tidy_dict.
    # We return an empty dict if tidy_dict is None to satisfy the type hint.
    return tidy_dict if tidy_dict is not None else {}



def process_one_sentence(
    valueset: Dict[str, Any],
    sentence: Span,
    k: int,
    s: int
) -> str:
    """Converts a spaCy sentence into a CoNLL-formatted string block.

    This function assembles a CoNLL document segment by combining metadata 
    headers (article number, unique sentence IDs, and custom attributes) 
    with the token-level information extracted from a spaCy Sentence object.

    Args:
        valueset (Dict[str, Any]): A dictionary containing the metadata 
            for the current sentence (e.g., URLs, titles, dates).
        sentence (Span): A spaCy Sentence object containing the 
            tokens for the current sentence.
        k (int): The zero-based index of the article/row in the dataset.
        s (int): The zero-based index of the sentence within the article.

    Returns:
        str: A single string containing the full CoNLL block for the sentence,
            including headers, tokens, and a trailing newline.
    """
    # Define a special string for the empty CoNLL fields
    line_tail = "\t_\t_\t_\t_\t_\t_\t_\t_\n"

    current_sent = []

    # Add the metadata header block
    current_sent.append(make_sent_metas(valueset, sentence, k, s))

    # Iterate over the tokens in the sentence to make token-level CoNLL strings
    for t, token in enumerate(sentence):
        # token index is 0-based, so we add 1 to match CoNLL requirements
        current_sent.append(
            f'{t + 1}\t{token.text}{line_tail}'
        )

    # Add a line break at the end of every sentence to separate blocks
    current_sent.append("\n")

    # Join all the accumulated lines into a single string
    return "".join(current_sent)



def get_document_and_values(
    nlp: Language,
    json_input_parsed: Dict[str, Any],
    input_key: str
) -> Tuple[Doc, Dict[str, Any]]:
    """Extracts a spaCy Doc and its associated metadata from a parsed JSON object.

    This function retrieves the raw metadata dictionary for a specific record using 
    the provided `input_key`. It then extracts the text content from the 'txt' 
    field, cleans it using `make_tidy_art_string`, and processes it through 
    the provided spaCy NLP pipeline.

    Args:
        nlp (Language): A configured spaCy NLP pipeline object (including 
            tokenizer and sentencizer).
        json_input_parsed (Dict[str, Any]): The dictionary containing the 
            parsed JSON data, where keys correspond to unique record identifiers.
        input_key (str): top level key from json_input_parsed.keys


    Returns:
        Tuple[Doc, Dict[str, Any]]: A tuple containing:
            - doc (Doc): The spaCy Doc object representing the cleaned 
              sentence(s) from the 'txt' field.
            - valueset (Dict[str, Any]): The original metadata dictionary 
              associated with the input_key.
    """
    # Retrieve the specific metadata dictionary for the record
    valueset = json_input_parsed[input_key]

    # Extract and clean the text content
    # Assumption: The dictionary contains a key 'txt' with the raw text
    this_art = make_tidy_art_string(valueset['txt'])

    # Process the cleaned text through the NLP pipeline
    doc = nlp(this_art)

    return doc, valueset



def make_conll_strings_from_json_with_allmetas(
    input_file: str,
    nlp: Language,
    method: Optional[Any] = None,
    tidy_dict: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Makes a list of CoNLL strings for each input file.

    This function loads a JSON file containing dataset metadata, iterates through 
    the records, and uses a spaCy NLP pipeline to transform the text into 
    CoNLL-formatted strings. It incorporates sentence-level metadata (like 
    speaker names and IDs) into the header of every CoNLL block.

    Args:
        input_file (str): Absolute path to the JSON file to process.
        nlp (Language): A spaCy NLP pipeline object with a tokenizer 
            and sentencizer.
        method (Optional[Any], optional): A loading method flag for 
            `load_parse_json`. Defaults to None.
        tidy_dict (Optional[Dict[str, Any]], optional): A pre-parsed 
            dictionary to be used if `method` is provided. Defaults to None.

    Returns:
        List[str]: A flat list of CoNLL-formatted strings. Each string 
            represents a valid CoNLL document object (one article).
    """

    # Data parsed from JSON via the helper function
    json_input_parsed = load_parse_json(input_file, method, tidy_dict)

    # List to store the processed conll strings
    file_output: List[str] = []
    key_list = list(json_input_parsed.keys())

    # Iterate over the list of keys (each key represents one review/document)
    for k, input_key in enumerate(key_list):
        # Retrieve the spaCy Doc and the associated metadata values
        doc, valueset = get_document_and_values(nlp, json_input_parsed, input_key)

        # Iterate over the sentences in the doc
        for s, sentence in enumerate(doc.sents):
            conll_string = process_one_sentence(valueset, sentence, k, s)
            file_output.append(conll_string)

    return file_output

def send_to_files(
    input_file: str,
    file_output: List[str],
    chunk_size: int = 50000
) -> None:
    """Writes CoNLL strings to output files in chunks to limit file sizes.

    This function takes a list of processed CoNLL strings and splits them 
    into smaller chunks based on the specified chunk_size. Each chunk is 
    saved to a separate `.conll` file. The output filenames are derived 
    from the input file path by replacing specific directory/extension 
    segments.

    Args:
        input_file (str): The absolute path to the input JSON file.
        file_output (List[str]): A list of CoNLL-formatted strings to be written.
        chunk_size (int, optional): The number of sentences to write per file.
            Defaults to 50,000, which typically yields 0.5-1.0 million 
            words per file.

    Returns:
        None: The function writes files to disk and does not return an object.
    """
    # Calculate the number of files needed based on the total length of the list
    num_files = math.ceil(len(file_output) / chunk_size)

    # Loop through the data in chunks and write to separate files
    for i in range(num_files):
        # Determine the start and end of the current chunk
        start_idx = i * chunk_size
        end_idx = start_idx + chunk_size
        # Extract the current chunk of data
        chunk = file_output[start_idx:end_idx]

        subpart_num = f"{i + 1:02d}"

        # Construct the output filename.
        output_file = input_file.replace(
            '.json', f'_part{subpart_num}.conll'
        ).replace(
            '1_conllised_json', '2_conllu'
        )

        # Write the chunk to a new file
        with open(output_file, 'w', encoding='UTF-8') as f:
            for line in tqdm(chunk, desc=f"Writing file {i+1}/{num_files}", leave=False):
                # Write the line directly (joining a list of characters is redundant
                # for a string, so we use the string directly)
                _ = f.write(line)

def process_one_file(input_file: str, nlp: Language) -> None:
    """Processes a single input file to generate CoNLL strings and distribute them to files.

    This function serves as the worker for a multiprocessing pool. It takes an 
    absolute path to an input file, uses a spaCy NLP pipeline to transform that 
    file's contents into CoNLL-formatted strings, and then distributes those 
    strings into multiple output files to manage file size.

    Args:
        input_file (str): The absolute path to the input JSON file to be processed.
        nlp (Language): A configured spaCy NLP pipeline object used for 
            linguistic processing.

    Returns:
        None: This function performs I/O operations and prints progress to the console.
    """
    # Convert JSON to CoNLL strings using the provided NLP pipeline
    file_output = make_conll_strings_from_json_with_allmetas(input_file, nlp)

    print(f"Processing {input_file}")

    # Distribute the generated strings into chunks for final file storage
    send_to_files(input_file, file_output, chunk_size=50000)

def sent_json_to_conll(year: str, lang: str, nproc: int) -> List[Any]:
    """Orchestrates a multiprocessing pipeline to convert JSON files to CoNLL format.

    This function identifies all relevant JSON files for a given year and language,
    calculates an optimal pool size for parallel processing, initializes the 
    required NLP pipeline, and distributes the work across multiple CPU cores 
    using a process pool.

    Args:
        year (str): The year string used to locate the data directory.
        lang (str): The language code (e.g., 'fr') for the NLP pipeline.
        nproc (int): The requested number of processor cores for the pool.

    Returns:
        List[multiprocessing.pool.ApplyResult]: A list of results from the 
            asynchronous pool tasks.
    """
    # Step 1: Generate list of files
    input_files = glob.glob(
        f'/Volumes/data/cc_{lang}/{year}/1_conllised_json/*.json'
    )
    print(f'{len(input_files)} files to process')

    if not input_files:
        print("No files found to process.")
        return []

    # Step 2: Determine pool size with safety checks
    # Use os.cpu_count() to get the total number of cores available
    pool_size = min(nproc, os.cpu_count(), 1)

    if pool_size >= len(input_files):
        pool_size = len(input_files)
        print(f"Using pool size == file size == {pool_size}")
    else:
        print(f"Using pool size: {pool_size}")

    # Step 3: Define NLP pipeline and create the worker function
    # define_pipe must return a valid spacy Language object
    nlp = define_pipe(lang)
    print(f'nlp loaded for {lang}')

    # Use partial to "freeze" the nlp object into the worker function
    # so it can be passed into the multiprocessing pool.
    worker_func = partial(process_one_file, nlp=nlp)

    # Step 4: Map work to the pool and track progress
    results = []
    with Pool(pool_size) as pool:
        with tqdm(total=len(input_files), desc="Processing", unit="file") as pbar:
            results=[]
            for file_path in input_files:
                # apply_async is non-blocking; the callback updates the tqdm bar
                r = pool.apply_async(worker_func, (file_path,), callback=lambda _: pbar.update(1))
                results.append(r)

            # Wait for all tasks to complete before returning
            for r in results:
                r.wait()

    return results

def parse_years(year_args: Iterable[str]) -> List[str]:
    """Parses a collection of strings into a flattened list of years.

    This function takes an iterable of strings (where each string may contain 
    one or more years separated by commas) and expands them into a single 
    flattened list of cleaned year strings. It ignores empty values and 
    removes leading/trailing whitespace.

    Args:
        year_args (Iterable[str]): An iterable of strings, where each 
            string may contain comma-separated years (e.g., ["2021,2022", "2023"]).

    Returns:
        List[str]: A flattened list of cleaned year strings.
    """
    years = []
    for y in year_args:
        # allow comma-separated values in each argument
        parts = y.split(",")
        for p in parts:
            cleaned = p.strip()
            if cleaned:      # ignore empty
                years.append(cleaned)
    return years


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
      description="run step 1 to convert parquet to json files. \
      Speed = about 30s per parquet file ≈ 4GB of parquet per min from external HDD\
      \nrun step 2 to convert json to conllu files."
      )
    parser.add_argument(
        "-year", "-y",
        nargs="+",
        help="Year or list of years",
        required=True
    )
    parser.add_argument(
        "-num",
        type=int,
        help="Upper limit of range of number of files to process"
        )
    parser.add_argument(
        "-filter_type",
        type=str,
        help="filter_type: domain or lang"
        )
    parser.add_argument(
        "-filter_value",
        type=str,
        help="url or language"
        )
    parser.add_argument(
        "-mode",
        default="X",
        help="Processing mode. \
        Use `S` for strict to get only year_matches for source and scrape"
        )
    parser.add_argument(
        "-local_dir",
        default=None,
        help="local dir override"
        )
    parser.add_argument(
        "-skip",
        default="",
        help="skip steps 1 -process parquet- or 2 -process json"
        )
    parser.add_argument(
      "--nproc",
      type=int,
      default=4,
      help="Number of parallel processes"
      )
    parser.add_argument(
        "-lang",
        type=str,
        default="en",
        help="Language code (e.g., en, fr, de)"
    )

    args = parser.parse_args()
    tidy_years = parse_years(args.year)


    for tidy_year in tidy_years:
        if "1" not in args.skip:
            filter_config = FilteringConfiguration(
                filter_type = args.filter_type,
                filter_value = args.filter_value,
                mode = args.mode,
                year = tidy_year
            )
            get_json_from_parquet(
              filter_config,
              args.num,
              args.local_dir
            )
        if "2" not in args.skip:
            sent_json_to_conll(
              tidy_year,
              args.lang,
              args.nproc
            )
