"""coordinate parsing of CoNLL documents with stanza pipeline"""
import argparse
import sys
import os
import time

from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import stanza
from stanza.utils.conll import CoNLL
from stanza.models.common.doc import Document
from tqdm import tqdm

def run_parsing(
    input_files:List[str],
    output_dirname: str,
    lang: str,
    my_size: float,
    depparse_only: bool
    ) -> None:
    '''
    Parse files with Stanza
    Inputs:
        input_files (List[str]) : a list of files to process
        output_dirname: str : name of the folder in which to export files
        lang (str) : a 2-3 character language code
        my_size (int) : an integer used to define batch sizes
        depparse_only (bool) : Run dependency parsing only.
            If True or T, only the dependency parser will be called. For processing
            to be successful, input data needs to be well-formatted conll with at
            least POS, LEM annotations present.
    '''

    if not input_files:
        print("No input files found")
        sys.exit(0)

    # check we have files to process
    print(f'{len(input_files)} files found')
    # instantiate the nlp object and print batch sizes to the console

    nlp, batch_sizes_tidy, parse_settings_dict = prepare_for_parsing(
        input_files,
        output_dirname,
        lang,
        my_size,
        depparse_only
        )

    for input_file in tqdm(input_files):
        try:
            ## load input file and check that longest sent is under the set limit
            starttime = time.time()
            source_doc = CoNLL.conll2doc(input_file)
            max_len = max(len(sent.tokens) for sent in source_doc.sentences)

            if max_len >= parse_settings_dict.get('limit'):
                write_log(
                    parse_settings_dict.get('log_file_path'),
                    str(f'\tSkipping {input_file} : max_len exceeded:: {max_len}\n')
                    )

            else:
                ## print the number of tokens in the doc, run pipeline, export
                print(f"\tProcessing {input_file} :: {source_doc.num_tokens} tokens")
                annotated_document = nlp(source_doc)
                write_annotations_to_file(
                    annotated_document,
                    input_file,
                    parse_settings_dict
                    )

                move_processed_source(input_file, parse_settings_dict)
                ## make reportstring, write to log
                write_log(
                    parse_settings_dict.get('log_file_path'),
                    log_entry = (
                        f"{starttime}\t"
                        f"{time.time()}\t"
                        f"{source_doc.num_tokens}\t"
                        f"{input_file}\t"
                        f"{batch_sizes_tidy}\n"
                        )
                    )
        # quietly catch and log all exceptions
        except Exception as e:
            report_string = f'{input_file}\t{e}\n'
            print(report_string)
            write_log(parse_settings_dict.get('log_file_path'), str(report_string))

def load_nlp(lang: str, my_size: Union[int, float, str], depparse_only: bool) -> stanza.Pipeline:
    """
    Load specific Stanza pipelines for pre-configured languages and processing needs.

    Args:
        lang (str): Language code (e.g., 'en', 'fr', 'grc') to be passed to the
            `lang` argument in stanza.Pipeline.
        my_size (Union[int, float, str]): Batch size multiplier passed to
            `set_batch_sizes`. Input is cast to float to allow for decimal input.
        depparse_only (bool): Indicate whether to only perform dependency parsing
            - If True, requires well-formatted CoNLL with tokens, IDs, lemmas, and POS tags.
                Any existing HEAD or DEPREL entries will be overwritten.
            - If False, requires pre-tokenized, pre-sentencized well-formatted CoNLL.
            - Note: For 'grc' (Ancient Greek), depparse_only is ignored.

    Returns:
        stanza.Pipeline: A configured Stanza Pipeline object.
    """

    if lang == "grc":
        return stanza.Pipeline(lang="grc")

    std_batch_size, pos_max = set_batch_sizes(my_size)

    # 1. map langs to packages
    depparse_pkgs = {"fr": "gsd", "en": "ewt"}
    full_pkgs = {"ang": "nerthus", "it": "isdt", "de": "gsd", "fr": "gsd", "en": "ewt"}

    # 2. Define the Language Lists
    depparse_langs = ["fr", "fro", "frm", "en"]
    full_langs = ["ang", "it", "de", "es", "fr", "fro", "en"]

    # 3. Use dictionary comprehensions to build configs dynamically
    #  **({...} if ...)  injects the 'package' key only if it exists in our mapping
    depparse_configs = {
        lang: {
            "processors": "depparse",
            "depparse_pretagged": True,
            **({"package": depparse_pkgs[lang]} if lang in depparse_pkgs else {})
        }
        for lang in depparse_langs
    }

    full_configs = {
        lang: {
            "processors": "tokenize,mwt,pos,lemma,depparse",
            "tokenize_pretokenized": True,
            "tokenize_ssplit": True,
            **({"package": full_pkgs[lang]} if lang in full_pkgs else {})
        }
        for lang in full_langs
    }

    # 4. Selection Logic
    if depparse_only:
        config = depparse_configs.get(lang, {}).copy()
        if config:
            config.update(
                {
                    "depparse_batch_size": std_batch_size,
                    "depparse_second_batch_size": std_batch_size
                    }
                )
    else:
        config = full_configs.get(lang, {}).copy()
        if config:
            config.update({
                "mwt_batch_size": std_batch_size,
                "pos_batch_size": std_batch_size,
                "pos_batch_maximum_tokens": pos_max,
                "lemma_batch_size": std_batch_size,
                "depparse_batch_size": std_batch_size,
                "depparse_second_batch_size": std_batch_size
            })

    return stanza.Pipeline(lang=lang, **config)


def prepare_for_parsing(
    input_files: List[str],
    output_dirname: str,
    lang: str,
    my_size: float,
    depparse_only: bool
) -> Tuple[stanza.Pipeline, str, Dict[str, Any]]:
    """
    Initializes the Stanza NLP pipeline and prepares metadata for parsing.

    This function captures the launch time, constructs a configuration dictionary
    containing log paths and parsing limits, initializes the Stanza pipeline
    based on language and batch size settings, and generates a summary of
    the resulting batch configurations.

    Args:
        output_dirname (str): The name, *not path* to dir where files and logs
            will be saved.
        lang (str): The language code for the Stanza pipeline (e.g., 'en', 'fr').
        my_size (float): The batch size multiplier used to calculate internal
            Stanza batch limits.
        depparse_only (bool): If True, loads a pipeline configured for
            dependency parsing only.

    Returns:
        Tuple[stanza.Pipeline, str, Dict[str, Any]]: A tuple containing:
            - nlp (stanza.Pipeline): The initialized Stanza pipeline object.
            - batch_sizes_tidy (str): A formatted string summary of the
              batch sizes for the initialized pipeline.
            - parse_settings_dict (Dict[str, Any]): A dictionary containing
              metadata for the run (launch time, log path, limit, etc.).
    """
    launch_time = time.time()
    output_dir = Path(input_files[0]).parent.parent / output_dirname
    output_dir.mkdir(parents=True, exist_ok=True)

    # Construct metadata dictionary
    parse_settings_dict = {
        "launch_time" : launch_time,
        "log_file_path": Path(f'{output_dir}/{launch_time}_log.txt'),
        "output_dir": Path(output_dir),
        "limit" : 1600,
        "myletter": "_",
        "lang": lang
    }

    # Initialize the NLP pipeline and generate the summary report
    nlp = load_nlp(lang, my_size, depparse_only)
    batch_sizes_tidy = make_config_reports(nlp)

    return nlp, batch_sizes_tidy, parse_settings_dict

def write_annotations_to_file(
    annotated_document: Document,
    input_file: str,
    parse_settings_dict: Dict[str, Any]
    ) -> None:
    """
    Write the annotated document object to a file.

    Constructs an output path by combining the input file's parent directory,
    a destination folder (from parse_settings_dict), and a new filename
    derived from the input filename and metadata.

    Args:
        annotated_document (Docuemnt): A CoNLL document object of annotated sentences.
        input_file (str): The absolute path to the file taken as input.
            This is used to determine the parent directory and the base filename.
        parse_settings_dict (Dict[str, Any]): A dictionary of constants for parsing.
            Expected keys used in this function:
                - 'output_dir' (Path): Path of the folder to export
                  annotations to.
                - 'myletter' (str): Optional string prefix (defaults to '_').
                - 'lang' (str): Language code to insert into the output filename.

    Returns:
        None: A file is written, and a confirmation message is printed to the console.
    """
    # Extract settings with sensible defaults
    my_letter = parse_settings_dict.get('myletter', '_')
    lang = parse_settings_dict.get('lang', 'UNK')
    output_dir = parse_settings_dict.get('output_dir', '/data/output')

    # Construct the new suffix, path
    newvalue_fstring = f"{my_letter}_{lang}_OUT.conll"
    input_file_path = Path(input_file)
    new_basename = input_file_path.name.replace('.conll', newvalue_fstring)
    output_fullpath = Path(output_dir) / new_basename

    # Convert the document object to a string using the :C format specifier
    string_content = f"{annotated_document:C}"

    with open(output_fullpath, 'w', encoding='UTF-8') as w:
        w.write(string_content)
    print(f":::::            Exported to {output_fullpath}")


def set_batch_sizes(my_size: Union[int, float, str]) -> Tuple[int, int]:
    """
    Set batch sizes for Stanza processing.

    Args:
        my_size (Union[int, float, str]): A numeric value (int, float, or string)
            to be multiplied by 1024 to define base batch sizes.

    Returns:
        Tuple[int, int]: A tuple containing (std_batch_size, pos_max).
            std_batch_size is used for all batches except pos_max, which is
            set to 16x the std_batch_size preserving the default geometry.
    """

    x = float(my_size)
    std_batch_size = int(x * 1024)
    pos_max = std_batch_size * 16
    return (std_batch_size, pos_max)

def make_config_reports(nlp: stanza.Pipeline) -> str:
    """
    Extracts and prints batch size configurations from a Stanza pipeline.

    This function iterates through all processors in the provided Stanza
    pipeline, identifies configuration keys containing the word 'batch',
    prints them to the console, and compiles them into a formatted string
    for logging purposes.

    Args:
        nlp (stanza.Pipeline): The Stanza pipeline object to inspect.

    Returns:
        str: A newline-separated string of processor names, configuration
            keys, and values for all batch-related settings.
    """
    # Print to console
    for name, processor in nlp.processors.items():
        for key, value in processor.config.items():
            if "batch" in key:
                print(f'{name}\t{key}\t{value}')

    # Create a tidy list of batch sizes to insert into log
    # Note: The comprehension order is fixed to (outer loop, inner loop)
    batch_sizes = [
        f'{name}\t{key}\t{value}'
        for name, processor in nlp.processors.items()
        for key, value in processor.config.items()
        if 'batch' in key
    ]

    return "\t".join(batch_sizes)

def move_processed_source(input_file: Union[str,Path], parse_settings_dict: Dict[str: Any]) -> None:
    '''
    Move source documents to output folder after successful processing
    Args:
        input_file (Union[str, Path]): input .conll file successfully processed
        parse_settings_dict (Dict[str, Any]): A dictionary containing
              metadata for the run (launch time, log path, limit, etc.).
    Returns:
        None. The input file is moved to the output directory.
    '''
    output_dir = parse_settings_dict.get("output_dir")
    input_file_path = Path(input_file)
    output_fullpath = Path(output_dir) / input_file_path.name
    output_fullpath.parent.mkdir(parents=True, exist_ok=True)
    os.rename(input_file_path, output_fullpath)

def write_log(log_file_path, log_entry):
    '''
    Simple helper to write-append a log entry to the logfile
    Inputs:
        log_entry : str : the string to write to the logfile
        launch_time : int : unix time at which the parsing process was launched
    Returns:
        no return object : a string is write-appended to a file
    '''
    with open(log_file_path ,'a', encoding='UTF-8') as k:
        _ = k.write(log_entry)

def get_input_files(input_args: argparse.Namespace) -> List[str]:
    """
    Retrieves a sorted list of .conll and .conllu files from the target directory.

    This function constructs the correct directory path based on the provided
    base directory and optional subfolder name, then gathers all files
    matching the .conll or .conllu extensions.

    Args:
        input_args (argparse.Namespace): The parsed arguments object containing
            'source_dir' (str) and 'subf' (str).

    Returns:
        List[str]: A sorted list of paths to the matched files.
    """
    # Convert source_dir to a Path object for robust path manipulation
    source_dir = Path(input_args.source_dir)

    # Construct target directory: source_dir/subf if subf is provided, else source_dir
    search_dir = source_dir / input_args.subf if input_args.subf else source_dir

    # Check if the directory actually exists to avoid errors
    if not search_dir.exists():
        print(f"⚠️ Warning: Directory not found: {search_dir}")
        return []

    # Search for both extensions in one go using a list comprehension
    # This gathers all files matching either *.conll or *.conllu
    input_files = [
        str(f) for ext in ["*.conll", "*.conllu"]
        for f in search_dir.glob(ext)
    ]

    return sorted(input_files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="parse conllised texts with LANGUAGE and specified batch SIZE"
        )
    parser.add_argument(
        "--source_dir",
        help="Path to source dir"
        )
    parser.add_argument(
        "--output_dirname",
        help="Name of the output dir"
        )
    parser.add_argument(
        "--size",
        help="integer value for size of batch : x for all except pos_batch_max_tokens == 16x"
        )
    parser.add_argument(
        "--lang",
        help="language : use two/three letter codes that Stanza expects"
        )
    parser.add_argument(
        "--depparse_only",
        action="store_true",
        required=False,
        help="Run dependency parsing only"
        )
    parser.add_argument(
        "--subf",
        type=str,
        required=False,
        help="path to subfolder to process",
        default=''
        )

    args = parser.parse_args()
    arg_input_files = get_input_files(args)
    run_parsing(
        arg_input_files,
        args.output_dirname,
        args.lang,
        str(args.size),
        args.depparse_only
        )
