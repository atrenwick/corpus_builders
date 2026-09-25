# a tokeniser for French and English  using re, and lxml
# input is a text string or an etree or ET element, a list of tokens is returned

import re
import os
import glob
import argparse

from lxml import etree
from lxml.etree import Element
from tqdm import tqdm
from pathlib import Path

from multiprocessing import Pool
from multiprocessing import Value
from multiprocessing import Lock
from functools import partial

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
URL_PATTERN = re.compile(r'https?://\S+')
PUNCTUATION_PAD_PATTERN = re.compile(r'([,\]\[;:\-&\(\)?!\.«»“”"])')
PAD_HYPHENS_PATTERN = re.compile(r'([–-])')
JOIN_HYPHENS_PATTERN = re.compile(r' [–-] ')

EN_APOSTROPHE_PATTERN = re.compile(r"[’’'']")
EN_DOUBLE_QUOTE_PATTERN = re.compile(r'[“”]')

FR_QUOTE_SPACE_PATTERN = re.compile(r"[’'']")
FR_PRUDHOMME_PATTERN = re.compile(r"rud' homm")
FR_AUJOURDHUI_PATTERN = re.compile(r"aujourd' hui")
FR_PRONOUN_HYPHEN = re.compile(r'(-je|-tu|-il|-elle|-on|-ça|-cela|-nous|-vous|-ils|-elles|-moi|-toi|-lui|-leur|-en|-y|-ilz)\b', re.IGNORECASE)

def run_fr_only_replacements(this_text):
    '''
    Run string replacements specific to French language text 
    Inputs:
      this_text : str : a string of French text
    Returns:
      this_text : str : a string of French text
    '''

    this_text = FR_PRUDHOMME_PATTERN.sub(r"rud'homm", this_text)
    this_text = FR_AUJOURDHUI_PATTERN.sub(r"aujourd'hui", this_text)
    this_text = FR_PRONOUN_HYPHEN.sub(r' \1 ', this_text)
    return this_text

def run_tokeniser_core(this_text, lang, hyphen_join_value):
    ''' 
    Run tokeniser core section to apply replacements pre-tokenising
    Inputs:
      this_text: str : the text string to be tokenised
      lang : str : code of the language being processed
      hyphen_join_value : 
    '''
    this_text = CLEAN_WHITESPACE_PATTERN.sub(' ', this_text)
    this_text = COLLAPSE_SPACES.sub(' ', this_text).strip() 
    this_text= ELLIPSIS_PATTERN.sub('…', this_text)

    this_text = COMPILED_LATIN_ABBREV_PATTERNS.sub(
        lambda m: m.lastgroup if m.lastgroup else m.group(0), this_text)  
    this_text = COMPILED_INITIALISM_PATTERN.sub(
        lambda m: m.lastgroup if m.lastgroup else m.group(0), this_text)

    this_text = COMPILED_COMMA_PERIOD.sub('.', this_text)
    this_text = COMPILED_PERIOD_COMMA.sub('. ', this_text)
    this_text = URL_PATTERN.sub('_URL_ ', this_text)

    if lang in ("fr", "FR"):
      this_text = QUOTE_SPACE_PATTERN.sub("' ", this_text)
      this_text = run_fr_only_replacements(this_text)
    if lang == ("en", "EN"):
      this_text = EN_APOSTROPHE_PATTERN.sub("'", this_text)
      this_text = EN_DOUBLE_QUOTE_PATTERN.sub('"', this_text)
      
    this_text = PUNCTUATION_PAD_PATTERN.sub(r' \1 ', this_text)

    if hyphen_join_value:
        this_text = JOIN_HYPHENS_PATTERN.sub('-', this_text)
    else:
        this_text = PAD_HYPHENS_PATTERN.sub(r' \1 ', this_text)    

    this_text = CLEAN_WHITESPACE_PATTERN.sub(' ', this_text)
    this_text = COLLAPSE_NEWLINES.sub('\n', this_text)
    this_text = COLLAPSE_SPACES.sub(' ', this_text).strip()

    return this_text
    
def get_text_from_input(input_text):
    '''
    Get the string of text from a string or an etree Element
    Input:
      input_text: etree Element or string : an etree Element with a string in the text attribute or a string
    Return :
      output_text : str : a text string
    '''

    # if the input is of type string, return the string unmodified
    if isinstance(input_text, str):
      output_text = input_text
    
    # if the input is not a string, iterate over the text in the element, strip and concatenate the text 
    else:
      output_text = ''.join([chunk for chunk in input_text.itertext()]).strip()
    return output_text

def get_tok_from_text(text):
    '''
    Split the tidied text into tokens based on spaces
    Inputs :
      text : string : a text string to tokenise
    Returns:
      tokens_tidy : list : a list of tokens
    '''
    # split the text into tokens on spaces and return the list of non "" elements
    tokens_raw = text.split(" ")
    tokens_tidy = [tok for tok in tokens_raw if tok != ""]
    return tokens_tidy

def run_tokenizer(input_text, lang, hyphen_join_value):
    '''
    Run the three steps of the tokenisation pipeline
    Inputs :
        input_text: etree Element or string : an etree Element with a string in the text attribute or a string
    Returns:
        tokens_tidy : list : a list of tokens
    '''
  
    this_text = get_text_from_input(input_text)
    this_text = run_tokeniser_core(this_text, lang, hyphen_join_value)
    tokens_tidy = get_tok_from_text(this_text)
    return tokens_tidy
  

def tokenise_file(input_file, outputPath, lang, hyphen_join_value):
    '''
    Run all steps of tokenisation for a file, to pass as basis for partial function
    '''
    
    # use the global variables shared by the pool
    global counter, counter_lock
    
    with counter_lock:
        counter.value += 1
        w_count = counter.value
    
    # filenames
    output_head = Path(outputPath)
    output_head.mkdir(exist_ok=True)

    output_basename = os.path.basename(input_file).replace('.xml', '_tokenized.xml')
    
    parent_folder_basename = os.path.basename(os.path.dirname(input_file) )
    output_parent_folder = Path(output_head / parent_folder_basename)
    output_parent_folder.mkdir(exist_ok=True)
    outputfile_full_path = Path(output_parent_folder/output_basename)

    # get the tree and its s elements  
    tree_in = etree.parse(input_file)
    p_els = tree_in.findall(".//p")
    
    # define a dictionary of custom replacements to allow proper processing of Latin abbreviations
    tok_repl_dict =   {'e_g_': 'e.g.', 'e_g_#': 'e.g.,', 'et_al': 'et al.', 'i_e_': 'i.e.,', 'i_e_': 'i.e.'}
    
    # run the tokeniser for each p element, adding a w element to each p el for each token, and when done, set p_el text to ""
    for p_el in (p_els):
        tokens_tidy = run_tokenizer(p_el, lang, hyphen_join_value)
        for tok in tokens_tidy:
            w_count +=1
            w_el = etree.SubElement(p_el, "w")
            w_el.set("id", str(w_count))
            if tok in tok_repl_dict.keys():
                tok = tok_repl_dict[tok]
            w_el.text = str(tok)
    
        p_el.text = ""  
    if not NO_WRITE:
        tree_in.write(outputfile_full_path, encoding='UTF-8', pretty_print=True, xml_declaration=True) 


def init(shared_counter, lock, no_write):
    '''
    initialiser function to set and lock a counter to be shared between pool processors
    Inputs :
      shared_counter : counter : the counter to be shared
      lock : lock : a lock
    Returns :
      no return object 2 globals declared
    '''
    global counter, counter_lock, NO_WRITE
    counter = shared_counter
    counter_lock = lock
    NO_WRITE = no_write
    
def pool_tokenise(outputPath, files, n_procs, lang, hyphen_join_value, no_write):
    '''
    Tokenise files with a processor pool
    inputs:
      outputPath: str : path to top level output dir
      files : list : a list of files to tokenise
      n_procs : int : number of processors to use in the processor pool
      lang : string : language code of the texts to be tokenised
      hyphen_join_value : bool : should hyphenated tokens be joined in French
    Returns :
      no return object : a processor pool will be created, each processor tokenising and printing files
    '''
    # define worker  function to send to each processor
    worker = partial(tokenise_file, outputPath=outputPath, lang=lang, hyphen_join_value=hyphen_join_value)
    
    # initialise the shared counter and lock
    shared_counter = Value("i", 0)   # int, initialized to 0
    lock = Lock()
    
    # use the pool to process the files unordered, with a progress bar  
    with Pool(processes=n_procs, initializer=init, initargs=(shared_counter, lock, no_write)) as pool:
        for _ in tqdm(pool.imap_unordered(worker, files), total=len(files)):
            pass
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='''Process files with multiprocessing.
    
    Usage : 
      example : process files in /home/folder with 4 processors in pool, joining hyphens set to True for files in French
      tokeniser.py -inputPath /home/folder --nprocs 4 -join_hyphen True --lang fr
            
    ''')
    parser.add_argument(
        "--inputPath", type=str,help="path to folder containing XML"
    )
    parser.add_argument(
        "--outputPath", type=str,help="output folder toplevel"
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
    
    path = args.inputPath
    outputPath = args.outputPath
    n_procs = args.nprocs
    lang = args.lang
    hyphen_join_value = args.join_hyphen
    no_write = args.no_write
    files = glob.glob(f'{path}/*/*.xml')

    files = [x for x in files if "tokenised.xml" not in x]
    print(f'{len(files)} files found : processing with {n_procs} workers')

    pool_tokenise(outputPath, files, n_procs, lang, hyphen_join_value, no_write)
