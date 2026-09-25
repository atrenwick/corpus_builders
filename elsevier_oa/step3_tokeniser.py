"""A rule-based tokeniser for French and English based.
input is a text string or an etree or ET element.
A list of tokens <w> in an XML structure is returned
"""
import re
import glob
import argparse

from dataclasses import dataclass
from functools import partial
from multiprocessing import Pool
from multiprocessing import Value
from multiprocessing import Lock
from pathlib import Path
from typing import Dict, List, Optional, Union

from lxml import etree
from tqdm import tqdm

COUNTER: Optional[Value] = None
COUNTER_LOCK: Optional[Lock] = None
NO_WRITE: Optional[bool] = None


LATIN_ABBREVIATION_MAP = {
    'et_al': r'\bet\.?\s*al\b\.?',
    'e_g_':  r'\be\.\s*g\.\b|\be\.g\b',
    'i_e_':  r'\bi\.\s*e\.\b|\bi\.e\b'
}
INITIALISM_MAP = {
    # Countries & Geographic Initialisms
    'UK':     r'\bU\.?\s*K\.\b|\bU\.K\b',
    'USA':    r'\bU\.?\s*S\.?\s*A\.\b|\bU\.S\.A\b',
    'US':     r'\bU\.?\s*S\.\b',
    'UAE':    r'\bU\.?\s*A\.?\s*E\.\b|\bU\.A\.E\b',
    'EU':     r'\bE\.?\s*U\.\b|\bE\.U\b',
    'UN':     r'\bU\.?\s*N\.\b|\bU\.N\b',
    'NZ':     r'\bN\.?\s*Z\.\b|\bN\.Z\b',

    # Common Academic & General Initialisms
    'PhD':    r'\bP\.?\s*h\.?\s*D\.\b|\bP\.h\.D\b',
    'MA':     r'\bM\.?\s*A\.\b|\bM\.A\b',
    'BA':     r'\bB\.?\s*A\.\b|\bB\.A\b',
    'BC':     r'\bB\.?\s*C\.\b|\bB\.C\b',
    'AD':     r'\bA\.?\s*D\.\b|\bA\.D\b',
    'AM':     r'\bA\.?\s*M\.\b|\bA\.M\b',
    'PM':     r'\bP\.?\s*M\.\b|\bP\.M\b',
}

COMPILED_LATIN_ABBREV_PATTERNS = re.compile(
    '|'.join(f'(?P<{key}>{pattern})' for key, pattern in LATIN_ABBREVIATION_MAP.items())
)

# Compile all keys into a single named-capture-group regex
COMPILED_INITIALISM_PATTERN = re.compile(
    '|'.join(f'(?P<{key}>{pattern})' for key, pattern in INITIALISM_MAP.items())
)

CLEAN_WHITESPACE_PATTERN = re.compile(r'[\r\n\t\xa0\\|]+')
COLLAPSE_SPACES = re.compile(r' {2,}')
ELLIPSIS_PATTERN = re.compile(r"\.\.\.")

COLLAPSE_NEWLINES = re.compile(r'\n+')
COMPILED_COMMA_PERIOD = re.compile(r',\.(?=\s|$)')
COMPILED_PERIOD_COMMA = re.compile(r'\.,')
PUNCTUATION_PAD_PATTERN = re.compile(r'([,\]\[;:\-&\(\)?!\.«»“”"])')

URL_PATTERN = re.compile(r'https?://\S+')
PAD_HYPHENS_PATTERN = re.compile(r'([–-])')
JOIN_HYPHENS_PATTERN = re.compile(r' [–-] ')

EN_APOSTROPHE_PATTERN = re.compile(r"[’’'']")
EN_DOUBLE_QUOTE_PATTERN = re.compile(r'[“”]')

FR_QUOTE_SPACE_PATTERN = re.compile(r"[’'']")
FR_PRUDHOMME_PATTERN = re.compile(r"rud' homm")
FR_AUJOURDHUI_PATTERN = re.compile(r"aujourd' hui")
FR_PRONOUN_HYPHEN = re.compile(
  r'(-je|-tu|-il|-elle|-on|-ça|-cela|-nous|-vous|-ils|-elles|-moi|-toi|-lui|-leur|-en|-y|-ilz)\b',
  re.IGNORECASE)


@dataclass
class TokeniserProcessingConfig:
    """Configuration for a Pool-tokenise run.

    Bundles the paths, identifiers, and runtime options needed by
    `main()` to process a batch of files, so they can be passed
    around as a set of arguments.

    Attributes:
        conll_source: Path to the folder with XML files to tokenise.
        id_attrib: Name of the XML attribute used as id in XML : eg id, s, s_id…
        n_procs: Number of workers to request.
        lang: language of the text to tokenise
        hyphen_join_value: join hyphens to their preceding word
        no_write: skip writing output to files 
        files: list of files generated from the specified path
    """
    path: str
    output_path: str
    n_procs: int
    lang: str
    hyphen_join_value: bool
    no_write: bool
    files:list


def run_fr_only_replacements(this_text: str) -> str:
    """
    Apply French-specific linguistic string replacements to a text block.

    This function performs a series of regular expression substitutions to 
    standardize specific French words (e.g., "rud'homm", "aujourd'hui") and 
    ensure that hyphenated pronouns are correctly spaced.

    Args:
        this_text (str): The raw French text string to be processed.

    Returns:
        str: The processed French text string with corrections applied.
    """
    # Apply specific French word corrections
    this_text = FR_PRUDHOMME_PATTERN.sub(r"rud'homm", this_text)
    this_text = FR_AUJOURDHUI_PATTERN.sub(r"aujourd'hui", this_text)

    # Ensure proper spacing for hyphenated pronouns
    this_text = FR_PRONOUN_HYPHEN.sub(r' \1 ', this_text)

    return this_text

def run_tokeniser_core(
    this_text: str,
    lang: str,
    hyphen_join_value: Optional[bool]
) -> str:
    """
    Performs core text normalization and cleaning before tokenization.

    This function applies a sequence of regular expression substitutions to 
    standardize whitespace, normalize punctuation, handle language-specific 
    quotes, and manage hyphenation. 

    Args:
        this_text (str): The raw text string to be cleaned and normalized.
        lang (str): The ISO language code (e.g., "en", "fr") used to 
            trigger language-specific substitution rules.
        hyphen_join_value (Optional[bool]): If True, hyphens will be joined. 
            If False, hyphens will be padded with spaces.

    Returns:
        str: The normalized and cleaned text string.
    """
    # Initial whitespace and ellipsis cleaning
    this_text = CLEAN_WHITESPACE_PATTERN.sub(' ', this_text)
    this_text = COLLAPSE_SPACES.sub(' ', this_text).strip()
    this_text = ELLIPSIS_PATTERN.sub('…', this_text)

    # Abbreviation and Initialism normalization
    this_text = COMPILED_LATIN_ABBREV_PATTERNS.sub(
        lambda m: m.lastgroup if m.lastgroup else m.group(0), this_text)
    this_text = COMPILED_INITIALISM_PATTERN.sub(
        lambda m: m.lastgroup if m.lastgroup else m.group(0), this_text)

    # Punctuation and URL normalization
    this_text = COMPILED_COMMA_PERIOD.sub('.', this_text)
    this_text = COMPILED_PERIOD_COMMA.sub('. ', this_text)
    this_text = URL_PATTERN.sub('_URL_ ', this_text)

    # Language-specific rules
    if lang.lower() in ("fr", "FR"):
        this_text = FR_QUOTE_SPACE_PATTERN.sub("' ", this_text)
        this_text = run_fr_only_replacements(this_text)
    elif lang.lower() in ("en", "EN"):
        this_text = EN_APOSTROPHE_PATTERN.sub("'", this_text)
        this_text = EN_DOUBLE_QUOTE_PATTERN.sub('"', this_text)

    # Punctuation padding
    this_text = PUNCTUATION_PAD_PATTERN.sub(r' \1 ', this_text)

    # Hyphenation logic
    if hyphen_join_value:
        this_text = JOIN_HYPHENS_PATTERN.sub('-', this_text)
    else:
        this_text = PAD_HYPHENS_PATTERN.sub(r' \1 ', this_text)

    # Final cleanup of whitespaces and newlines
    this_text = CLEAN_WHITESPACE_PATTERN.sub(' ', this_text)
    this_text = COLLAPSE_NEWLINES.sub('\n', this_text)
    this_text = COLLAPSE_SPACES.sub(' ', this_text).strip()

    return this_text


def get_text_from_input(input_text: Union[str, etree._Element]) -> str:
    """
    Extracts a clean string from either a raw string or an lxml Element.

    This function handles two types of input:
    1. If the input is already a string, it is returned as-is.
    2. If the input is an lxml etree Element, the function iterates through 
       all text nodes (including those nested within children), concatenates 
       them into a single string, and strips any leading or trailing whitespace.

    Args:
        input_text (Union[str, etree._Element]): The input to extract text from. 
            Can be a raw string or an lxml etree._Element.

    Returns:
        str: The extracted and stripped text string.
    """
    # If the input is already a string, return it unmodified
    if isinstance(input_text, str):
        return input_text

    # If the input is an etree Element, concatenate all text nodes and strip
    # We use .itertext() to ensure we catch text inside nested tags (like <b> or <i>)
    return "".join(input_text.itertext()).strip()

def get_tok_from_text(text):
    '''
    Split the tidied text into tokens based on spaces
    Inputs :
      text : string : a text string to tokenise
    Returns:
      tokens_tidy : list : a list of tokens
    '''
    # split on whitespace : previous steps have removed whitespace other than spaces
    return text.split()


def run_tokenizer(
    input_text: Union[str, etree._Element],
    lang: str,
    hyphen_join_value: Optional[bool]
) -> List[str]:
    """
    Runs the complete tokenization pipeline on an input text block.

    This function coordinates three distinct steps:
    1. Extraction: Converts an lxml Element or raw string into a clean string.
    2. Normalization: Applies regex-based cleaning, language-specific 
       replacements, and hyphenation rules.
    3. Tokenization: Splits the normalized string into a list of individual 
       tokens based on whitespace.

    Args:
        input_text (Union[str, etree._Element]): The raw input to be processed. 
            Can be an lxml element (e.g., a paragraph tag) or a raw string.
        lang (str): The language code (e.g., "en", "fr") used to determine 
            linguistic rules.
        hyphen_join_value (Optional[bool]): If True, hyphens are joined; 
            if False, they are padded with spaces.

    Returns:
        List[str]: A list of cleaned and normalized tokens.
    """
    # Step 1: Extract raw text from the input source
    this_text = get_text_from_input(input_text)

    # Step 2: Run the core regex pipeline (normalization, language rules)
    this_text = run_tokeniser_core(this_text, lang, hyphen_join_value)

    # Step 3: Split into final token list
    tokens_tidy = get_tok_from_text(this_text)

    return tokens_tidy


def make_paths(input_file: Union[str, Path], output_path: Union[str, Path]) -> Path:
    """
    Constructs an output file path by mirroring the input file's directory structure.

    This function takes an input file path and an output base directory. It extracts 
    the name of the parent folder of the input file and creates a corresponding 
    subfolder in the output directory. The output filename is derived from the 
    input filename with a '_tokenized' suffix.

    Args:
        input_file (Union[str, Path]): The path to the source file (e.g., 
            '/data/source/folder_a/file.xml').
        output_path (Union[str, Path]): The base directory where all 
            processed outputs will be saved (e.g., '/data/output').

    Returns:
        Path: The constructed Path object for the new output file.
    """
    # Convert inputs to Path objects
    input_path = Path(input_file)
    output_head = Path(output_path)

    # Handle the output filename: replace .xml with _tokenized.xml
    output_basename = input_path.name.replace('.xml', '_tokenized.xml')

    # Determine the name of the folder containing the input file
    # os.path.basename(os.path.dirname(input_file)) is equivalent to input_path.parent.name
    parent_folder_basename = input_path.parent.name

    # Fallback for cases where the input file is in the current working directory
    if not parent_folder_basename:
        parent_folder_basename = "root"

    # Build the output directory path
    output_parent_folder = output_head / parent_folder_basename

    # Ensure the directory structure exists
    output_head.mkdir(parents=True, exist_ok=True)
    output_parent_folder.mkdir(parents=True, exist_ok=True)

    # Return the final joined path
    return output_parent_folder / output_basename

def add_w_element(
    tok_repl_dict: Dict[str, str],
    p_el: etree._Element,
    tok: str,
    w_count: int
) -> None:
    """
    Creates and appends a <w> (word) element to a parent paragraph element.

    This function adds a new word tag to an existing XML element (such as a 
    paragraph). It assigns a unique ID to the word based on the provided 
    counter and checks the replacement dictionary to see if the token 
    needs to be swapped (e.g., for language-specific mappings). If the 
    token is not in the dictionary, the original token is preserved.

    Args:
        tok_repl_dict (Dict[str, str]): A dictionary mapping tokens to their 
            replacement strings (e.g., {"et": "and", "al": "all"}).
        p_el (etree._Element): The lxml element (e.g., <p>) that will 
            act as the parent for the new <w> tag.
        tok (str): The raw token string to be processed and inserted as 
            the text content of the <w> element.
        w_count (int): The sequential integer ID to assign to the word's 
            'id' attribute.

    Returns:
        None: The function modifies the `p_el` object in-place.
    """
    w_el = etree.SubElement(p_el, "w")
    w_el.set("id", str(w_count))

    # Get value from replacement dict for tok if it's there
    # if it isn't, don't change tok
    replacement = tok_repl_dict.get(tok, tok)
    w_el.text = str(replacement)



def tokenise_file(
    input_file: Union[str, Path],
    output_path: Union[str, Path],
    lang: str,
    hyphen_join_value: Optional[bool]
) -> None:
    """
    Parses an XML file, tokenizes its content, and saves the result to a new file.

    This function iterates through all paragraph (`<p>`) elements in a source XML 
    file. For each paragraph, it runs a tokenization pipeline and populates the 
    paragraph with individual `<w>` (word) elements. It also manages a global 
    word counter to assign unique IDs to the first token of every file.

    Args:
        input_file (Union[str, Path]): The path to the source XML file 
            containing paragraphs to be tokenized.
        output_path (Union[str, Path]): The base directory where the 
            tokenized XML files will be saved.
        lang (str): The language code (e.g., "en", "fr") used to determine 
            linguistic rules during tokenization.
        hyphen_join_value (Optional[bool]): If True, hyphens are joined; 
            if False, they are padded with spaces.

    Returns:
        None: The function writes the results to a new file on disk.
    """
    # Increment the global counter safely to get a unique starting point for this file
    with COUNTER_LOCK:
        COUNTER.value += 1
        w_count = COUNTER.value

    # Construct the final output path using the mirrored directory logic
    outputfile_full_path = make_paths(input_file, output_path)

    # Load the XML tree from the source file
    tree_in = etree.parse(input_file)
    p_els = tree_in.findall(".//p")

    # Dictionary of custom replacements for specific Latin abbreviations
    tok_repl_dict = {
        'e_g_': 'e.g.', 
        'e_g_#': 'e.g.,', 
        'et_al': 'et al.', 
        'i_e_': 'i.e.'
    }

    # Process each paragraph element
    for p_el in p_els:
        # Run the multi-step tokenization pipeline
        tokens_tidy = run_tokenizer(p_el, lang, hyphen_join_value)

        # Iterate through tokens and append <w> elements to the paragraph
        for tok in tokens_tidy:
            w_count += 1
            add_w_element(tok_repl_dict, p_el, tok, w_count)

        # Clear the original text content of the paragraph
        p_el.text = ""

    # Save the modified tree to the output path if writing is enabled
    if not NO_WRITE:
        tree_in.write(
            str(outputfile_full_path),
            encoding='UTF-8',
            pretty_print=True,
            xml_declaration=True
        )


def init_pool(
    shared_counter: Value,
    lock: Lock,
    no_write: bool
) -> None:
    """
    Initializes shared resources for the worker pool.

    This function sets the global variables for the shared counter, the 
    locking mechanism, and the write-toggle flag. These variables are 
    used by all worker processes to ensure thread-safe updates to 
    global states (like unique IDs) and to control output behavior 
    across the parallel pool.

    Args:
        shared_counter (multiprocessing.Value): The shared counter object 
            used to generate unique IDs.
        lock (multiprocessing.Lock): The lock object used to prevent 
            race conditions when accessing the shared counter.
        no_write (bool): A flag indicating whether to suppress writing 
            to the filesystem.

    Returns:
        None
    """
    global COUNTER, COUNTER_LOCK, NO_WRITE

    COUNTER = shared_counter
    COUNTER_LOCK = lock
    NO_WRITE = no_write


def pool_tokenise(config: TokeniserProcessingConfig):
    '''
    Tokenise files with a processor pool
    inputs:
      config (TokeniserProcessingConfig) : Dataclass with args needed for pool tokenisation:
          output_path: str : path to top level output dir
          files : list : a list of files to tokenise
          n_procs : int : number of processors to use in the processor pool
          lang : string : language code of the texts to be tokenised
          hyphen_join_value : bool : should hyphenated tokens be joined in French

    Returns :
      no return object : a processor pool will be created,
          each processor tokenising and printing files
    '''
    # define worker  function to send to each processor
    worker = partial(tokenise_file,
        output_path=config.output_path,
        lang=config.lang,
        hyphen_join_value=config.hyphen_join_value
        )

    # initialise the shared counter and lock
    shared_counter = Value("i", 0)   # int, initialized to 0
    lock = Lock()

    # use the pool to process the files unordered, with a progress bar
    with Pool(
      processes=config.n_procs,
      initializer=init_pool,
      initargs=(shared_counter, lock, config.no_write)
      ) as pool:
        for _ in tqdm(pool.imap_unordered(worker, config.files), total=len(config.files)):
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='''Process files with multiprocessing.

    Usage :
      example : process files in /home/folder with 4 processors in pool, 
      joining hyphens set to True, for files in French
      tokeniser.py -input_path /home/folder --nprocs 4 -join_hyphen True --lang fr

    ''')
    parser.add_argument(
        "--input_path", type=str,help="path to folder containing XML"
    )
    parser.add_argument(
        "--output_path", type=str,help="output folder toplevel"
    )
    parser.add_argument(
        "--nprocs", type=int, default=2,
        help="Number of worker processes to use"
    )
    parser.add_argument(
        "--lang", type=str, default="en",
        help="Language code (e.g., en, fr, de)"
    )
    parser.add_argument(
        "--join_hyphen", action="store_true", default=False,
        help="Should hyphenated forms other than PRON be joined"
    )
    parser.add_argument(
        "--no_write", action="store_true", default=False,
        help="actually print files"
    )
    args = parser.parse_args()

    files = [x for x in glob.glob(f'{args.input_path}/*/*.xml') if "tokenised.xml" not in x]

    tokeniser_processing_config = TokeniserProcessingConfig(
        path = args.input_path,
        output_path = args.output_path,
        n_procs = args.nprocs,
        lang = args.lang,
        hyphen_join_value = args.join_hyphen,
        no_write = args.no_write,
        files = files
        )
    print(f'{len(files)} files found : processing with {args.nprocs} workers')

    pool_tokenise(tokeniser_processing_config)
