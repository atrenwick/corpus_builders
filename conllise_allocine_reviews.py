import argparse
import re
import sys
import math
import pandas as pd
from pathlib import Path
from spacy.pipeline import Sentencizer
from tqdm import tqdm

def send_to_files(source_file, output_data, chunk_size=25000):
  """
  Splits CoNLL formatted data from a dictionary into multiple numbered files.

    This function extracts the 'conll_str' from each entry in the output_data 
    dictionary and writes them to separate .conll files in chunks to avoid 
    creating files that are too large. The output filenames are derived from 
    the source_file path.

    Args:
        source_file (str): The path to the original source file (e.g., a .pickle file). 
            Used as a template for the output filename.
        output_data (dict): A dictionary where values are expected to be 
            dictionaries containing a 'conll_str' key.
        chunk_size (int, optional): The number of records to write per file. 
            Defaults to 25000.

    Returns:
        None
  """
  # LC to get a list of all the reviews to print as conll : 1 item to print per article
  print_data = ['\n'.join([x for x in  (v['conll_str'])]) for v in output_data.values()]
  # Calculate the number of files needed
  num_files = math.ceil(len(print_data) / chunk_size)

  # Loop through the data in chunks and write to separate files
  for i in range(num_files):
      # Determine the start and end of the current chunk
      start_idx = i * chunk_size
      end_idx = start_idx + chunk_size
      # Extract the current chunk of data
      chunk = print_data[start_idx:end_idx]
      
      subpart_num = f"{i + 1:02d}"
      output_file = source_file.replace('pickle','conll').replace('.conll', f'_part{subpart_num}.conll') 
      # Write the chunk to a new file
      with open(output_file, 'w', encoding='UTF-8') as f:
          for line in tqdm(chunk, desc=f"Writing file {i+1}/{num_files}"):
              outline = "".join([item for item in line])
              _ = f.write(outline)
              
def define_pipe(lang):
    """Initializes a spaCy NLP pipeline with a sentencizer for a specific language.

    Currently, this function only supports French. It creates a blank language 
    model and adds a sentencizer to the pipeline to enable sentence segmentation 
    without needing a full heavy model.

    Args:
        lang (str): The ISO language code (e.g., 'fr' for French).

    Returns:
        spacy.language.Language: A configured spaCy NLP pipeline object if the 
            language is supported.
        None: Returns None if the language is not supported.

    Example:
        >>> nlp = define_pipe("fr")
        >>> doc = nlp("Bonjour tout le monde. Comment ça va?")
        >>> [sent.text for sent in doc.sents]
        ['Bonjour tout le monde.', 'Comment ça va?']
    """
    if lang == "fr":
        from spacy.lang.fr import French
        
        nlp = French()
        # The string "sentencizer" tells spaCy to load the built-in Sentencizer component
        nlp.add_pipe("sentencizer")      
        return nlp
    else:
        print(f"Language '{lang}' not supported; reviews are only processed in French.")
        return None

def preprocess_reviews(this_review):
    """Cleans and normalizes review text by removing control characters and extra whitespace."""
    # Replace BOM, non-breaking spaces, and all whitespace characters (\r, \n, \t) with a space
    this_review = re.sub(r'[\xa0\x0D\r\n\t\ufeff]', ' ', this_review)
    # Collapse multiple spaces into one
    this_review = re.sub(r' +', ' ', this_review)
    # Trim leading/trailing whitespace
    return this_review.strip()

def make_conll_strings(doc, top_key):
    """Converts a spaCy Doc object into a list of CoNLL-formatted strings.

    Each sentence in the document is transformed into a string that includes 
    metadata headers (Article number and Sentence ID) and a tab-separated 
    format for each token. The tokens are padded with underscores to 
    comply with CoNLL-style column requirements.

    Args:
        doc (spacy.tokens.Doc): The spaCy document object to be converted.
        top_key (Union[int, str]): the name of the data split: train,test…

    Returns:
        list[str]: A list of strings, where each element represents one 
            sentence from the document in CoNLL format.
    """
    line_tail = "\t_\t_\t_\t_\t_\t_\t_\t_\n"
    doc_output = []
    for s, sent in enumerate(doc.sents, start=1):
        current_sent = []
        # add metalines so explicitating the link between each sent and each doc
        meta_lines = f"\n# Article_num = {top_key}\n# sent_ID = {top_key}-{int(s+1)}\n# sent_id_serial = {int(s+1)}\n"
        current_sent.append(meta_lines)
        for t, token in enumerate(sent):
            line = (f'{int(t)+1}\t{token.text}{line_tail}')
            current_sent.append(line)

        # when iterated over all toks add \n to end of sent
        current_sent.append("\n")
        # at end of sent processing, make string, append to output  
        current_sent_tidy = "".join([c for c in current_sent])  
        doc_output.append(current_sent_tidy)
    
    conll_chunk = doc_output
    return conll_chunk

def transform_data(source_file):
    """Loads review data from a pickle file and transforms it into a processed dictionary.

    This function reads a pickle file containing DataFrames (expected to be from the 
    Allocine French reviews dataset), filters for specific data sets (those with 
    '_set' in the key), and performs a full preprocessing pipeline for each review. 
    The pipeline includes text normalization, spaCy tokenization, and CoNLL string 
    generation.

    Args:
        source_file (str): Absolute path to the pickle file containing the dataset.

    Returns:
        dict: A nested dictionary where keys are unique identifiers (e.g., 'train_set0') 
            and values are dictionaries containing the following keys:
            - 'url' (str): The URL of the film.
            - 'review' (str): The raw review text.
            - 'tidy_review' (str): The cleaned text after preprocess_reviews.
            - 'reviewdoc' (spacy.tokens.Doc): The spaCy document object.
            - 'conll_str' (list[str]): A list of CoNLL-formatted strings for each sentence.
    """
    # ensure tidy filepath, load data
    source_path = Path(source_file)
    data = pd.read_pickle(source_path)

    # set lang and load nlp pipeline
    lang = "fr"
    nlp = define_pipe(lang)

    output_data = {}
    # iterate over dfs if their key contains 'set' and get the url and review
    for top_key, v in data.items():
        if '_set' in top_key:
            urls = v["film-url"]
            reviews = v["review"]
            
            # make new keys, and new subdicts 
            for k in tqdm(urls.index):  
                new_key = f"{top_key}{k}"  
                output_data[new_key] = {
                    "url": urls[k],
                    # walrus to get specific review and set to named variable to be used in next lines
                    "review": (raw_review := reviews[k]),
                    # walrus to run text preprocessor on raw text, set output to named variable to be used below
                    "tidy_review": (tidy_review := preprocess_reviews(raw_review)),
                    # walrus to run pass tidy text to pipeline and assign output to a new variable to be used below
                    "reviewdoc": (doc_obj := nlp(tidy_review)),
                    # make conll strings 
                    "conll_str": make_conll_strings(doc_obj, new_key)
                }
    return output_data


def run_main_pipe(source_file, chunk_size):
    """Orchestrates the full pipeline from raw data to CoNLL files.

    Args:
        source_file (str): Path to the input pickle file.
        chunk_size (int): Number of records per output file.
    """
    print(f"🚀 Starting pipeline for: {source_file}")
    
    try:
        # Step 1: Process raw data into the nested dictionary structure
        print("Step 1/2: Transforming data and generating CoNLL strings...")
        output_data = transform_data(source_file)
        
        # Step 2: Split that data into multiple files
        print("Step 2/2: Writing data to files...")
        send_to_files(source_file, output_data, chunk_size=chunk_size)
        
        print("✅ Pipeline completed successfully!")
        
    except FileNotFoundError:
        print(f"❌ Error: The file '{source_file}' was not found.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Initialize the argument parser
    parser = argparse.ArgumentParser(
        description="Allocine French Reviews CoNLL Processing Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Required argument: source file path
    parser.add_argument(
        "--source", 
        type=str, 
        required=True, 
        help="Absolute path to the source pickle file."
    )

    # Optional argument: chunk size for output files
    parser.add_argument(
        "--chunk_size", 
        type=int, 
        default=25000, 
        help="Number of reviews to include in each output .conll file."
    )

    # Parse the arguments from the command line
    args = parser.parse_args()

    # Execute the main pipeline
    run_main_pipe(args.source, args.chunk_size)
