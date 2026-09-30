"""Convert CoNLL files with custom metadata to XML-TEI compatible output"""
import argparse
import copy
import glob
import logging
import os
import re
import sys

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from multiprocessing import Pool, cpu_count
from typing import Any, List, Literal, Optional, Tuple, Union

from lxml import etree
from stanza.utils.conll import CoNLL
from stanza.models.common.doc import Sentence
from tqdm import tqdm


@dataclass
class MainProcessingConfiguration:
    """Encapsulate the six required parameters used in transforming CoNLL files to XML.

    Attributes:
        year (str): Year for which files are to be processed.
            This corresponds to the year in which the data was scraped by the CC-News bot.
        mode (Literal['A', 'E', 'O']):  Selection mode
            - 'A': Matches all files with the .conll extension.
            - 'E': Matches only those containing an even number before the extension.
            - 'O': Matches only those containing an odd number before the extension.
             This means that articles from 1980 uploaded in 2025 can be\
             recognised as written in 2025.
        lang (str) : language code for the language to be processed.
            Default values allowed : en, fr, de, it, es
        nproc (int) : number of processors in the pool
        log_path (str) : absolute path to which to write the log
            eg `/data/logs/abc123.log`
        publi (str) : file pattern to select files to process
            eg `bbc.com`, `conversation.com`
    """

    year: str
    mode: Literal['A','E','O']
    lang: str
    nproc: int
    log_path: str
    publi: str



RAW_HEADER_STR = '''
<TEI.2>
  <teiHeader>
    <fileDesc>
    <titleStmt>
    <title></title>
    <author></author>
    </titleStmt>
    <publicationStmt>
    <publisher></publisher>
    <date></date>
    <pubDate></pubDate>
    </publicationStmt>
        <sourceDesc>
        <p></p>
        </sourceDesc>
    </fileDesc>
    <profileDesc>
        <langUsage>
        <language  ident="fr"/>
        </langUsage>
    <textDesc  thema="" type="journalistic" sub_genre=""/>
    </profileDesc>
</teiHeader>
<text>
<body>


</body>
</text>
</TEI.2>
'''

# Parse the XML once at the global level to save time during execution
ARTICLE_MOULD_TEMPLATE = etree.fromstring(RAW_HEADER_STR)

#################################################################################################
##################################          functions           #################################
#################################################################################################

def setup_logger(log_path: str):
    """Configure logger to write to file and stderr."""
    logger = logging.getLogger("file_processor")
    logger.setLevel(logging.INFO)

    # File handler
    fh = logging.FileHandler(log_path, mode="w")
    fh.setLevel(logging.INFO)
    fh_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fh_formatter)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger

def start_article(sent: Sentence, input_file: Union[str, Path]):
    '''
    Make an etree Tree of a prescribed form for a specific parser,
        add metadata to the header
    Args:
        sent (sentence) : a CoNLL document Sentence object
        input_file : (string or Path) : absolute path to a parsed conll file
    Returns:
        current_article  (etree._Element): an etree element tree with the structure
            and metadata for the article
    '''

    article_mould = copy.deepcopy(ARTICLE_MOULD_TEMPLATE)

    ##  parse the raw string as an etree tree and add the metadata
    date_for_attrib = os.path.basename(input_file).replace('_out.conllu','')[-4:]
    art_metas = [sent.comments[i] for i in [0,3,4,5,6,7,8,9,10,11,12]]

    article_mould.findall('.//title')[0].text = art_metas[2].replace("# title=","")
    article_mould.findall(".//author")[0].text =art_metas[3].replace("# author=","")
    article_mould.findall(".//publisher")[0].text =art_metas[6].replace("# publi=","")
    article_mould.findall(".//date")[0].text = date_for_attrib

    source_desc_el = article_mould.findall(".//sourceDesc")[0]
    crawl_dt_el = etree.SubElement(source_desc_el, 'p')
    crawl_dt_el.text =art_metas[8].replace("# crawl_date=","")
    crawl_url_el = etree.SubElement(source_desc_el, 'p')
    crawl_url_el.text =art_metas[7].replace("# warc_path=","")
    current_article = article_mould
    return current_article

def make_s_blockopener(sent_metas):
    '''
    Make the XML <s> element and its attributes for a new sentence
 
    Args :
        sent_metas (List[Str]): a list of metadata for the sentence
    Returns :
        s_string_open (str): raw string representation of an <s> element
    '''
    sent_serial = sent_metas[0].replace("# sent_id = ",'')
    sent_uuid = sent_metas[1].replace('# sent_ID = ','')
    s_string_open = f'\n<s id="{sent_serial}" uuid="{sent_uuid}">'
    return s_string_open

def make_art_metablock(input_file: str, art_metas: List[str]) -> str:
    """Constructs an XML article element from metadata strings.

    This function maps a list of metadata strings (extracted from CoNLL 
    metalines) to specific XML attributes. It extracts the publication year 
    from the input filename and formats all attributes into a single, 
    valid XML tag string.

    Args:
        input_file (str): The path to the source file, used to extract 
            the publication year from the filename.
        art_metas (List[str]): A list of metadata strings in the 
            format '# key = value'.

    Returns:
        str: A string representing the formatted XML article element.
    """
    mapping = {
        0: "num",
        1: "url",
        2: "title",
        3: "author",
        4: "site",
        5: "resp_url",
        6: "publi",
        7: "crawllink",
        8: "crawl_dt",
        9: "mm",
        10: "dd"
    }

    # Build a dictionary of cleaned attributes
    attrs = {}
    for idx, xml_key in mapping.items():
        # Strip the "# prefix=" and extract the value
        raw_val = art_metas[idx].split(" = ", 1)[1]
        attrs[xml_key] = raw_val

    # Add the special logic for the year
    attrs["yyyy"] = os.path.basename(input_file).replace('_out.conllu', '')[-4:]
    attr_str = " ".join([f'{k}="{v}"' for k, v in attrs.items()])
    return f'\n<article {attr_str}>\n'

def consolidate_xmls(lang: str, year: str, publi: str) -> None:
    """Consolidates multiple XML files for a publication in a year into a single file.

    This function gathers all XML files matching a specific publication pattern 
    within a directory structure based on language and year. It parses each 
    file, extracts the article elements, and appends them to a new 
    `<teiCorpus>` root. Finally, it renumbers the sentence IDs sequentially 
    and writes the consolidated tree to a new XML file.

    Args:
        lang (str): Language code for the files to be processed.
        year (str): The year for which files are to be processed.
        publi (str): Pattern used to restrict filename matches to those 
            of the desired publication (used as a regex/substring).

    Returns:
        None: The function writes the consolidated XML file to the 
            specified output location.
    """
    input_files = glob.glob(
        f'/Volumes/HC3Beta/uncompressed_parquet/cc_{lang}/{year}/4_xml/*{publi}*.xml'
    )
    print(f"Consolidating {len(input_files)}")

    # Handle case where no files are found to avoid IndexError on input_files[0]
    if not input_files:
        print("No files found matching the criteria.")
        return

    outputfilename = f'{os.path.dirname(input_files[0])}/{year}_{publi}_{lang}.xml'
    new_tree = etree.Element("teiCorpus")

    for input_file in tqdm(input_files):
        input_tree = etree.parse(input_file)
        articles = input_tree.findall(".//TEI.2")
        for art in articles:
            new_tree.append(art)

    # Re-number all sentence IDs sequentially across the entire consolidated corpus
    for snum, sentblock in enumerate(new_tree.findall(".//s"), start=1):
        sentblock.set("id", str(snum))

    tree_out = etree.ElementTree(new_tree)
    tree_out.write(
        outputfilename,
        encoding='UTF-8',
        pretty_print=True,
        xml_declaration=True
    )
    print(f"{len(input_files)} consolidated to 1 file: {os.path.basename(outputfilename)}")

def get_doc_and_name(
    input_file: Union[str, Path],
    source_folder: Optional[Union[str, Path]] = None,
    target_folder: Optional[Union[str, Path]] = None
) -> Tuple[Any, str]:
    """Loads a CoNLL document and determines its corresponding output path.

    This function takes an input file path and determines the target output 
    path by replacing a source folder string (defaulting to '3_conllu_out') 
    with a target folder string (defaulting to '4_xml'). It also loads the 
    document using the CoNLL library.

    Args:
        input_file (Union[str, Path]): The path to the source CoNLL file.
        source_folder (Optional[Union[str, Path]], optional): The folder 
            string to be replaced in the path. Defaults to '3_conllu_out'.
        target_folder (Optional[Union[str, Path]], optional): The folder 
            string to replace it with. Defaults to '4_xml'.

    Returns:
        Tuple[Any, str]: A tuple containing:
            - doc (Document): The loaded CoNLL document object.
            - outputfile (str): The constructed path for the output XML file.
    """
    # Ensure input_file is a string for the .replace() method to work
    input_file_str = str(input_file)

    # Determine folder names, defaulting to your standard paths
    folder1 = str(source_folder) if source_folder else '3_conllu_out'
    folder2 = str(target_folder) if target_folder else '4_xml'

    # Construct the output file path
    # This replaces the source folder segment and the extension
    outputfile = input_file_str.replace(folder1, folder2).replace('.conll', '.xml')

    # Load the input file as a conll document
    # Note: CoNLL must be imported/defined in your scope
    input_doc = CoNLL.conll2doc(input_file_str)

    return input_doc, outputfile

def process_file(input_file, year, lang, logger):
    '''
    The function processing a single file, from which a partial \
        function for the pool can be created.
    Inputs:
        input_file (str) : absolute path to the conll file taken as input
        year : string : year for which files are to be processed
        lang : string : language to be processed
        logger : logger : a logger
    Returns:
        1: 1 is returned in the case of an error in order to \
        trigger callback is triggered
        If the function runs successfully, no return object: a file is written.
    '''

    try:
        logger.info(f"Processing: {input_file} ")

        # reset counter to ensure first iteration will be 0
        art_num_prev = -1
        ## make a tree in which to append the tree for article,
        outputtree = etree.fromstring("<teiCorpus></teiCorpus>")
        current_article, articles_processed = [],[]
        input_doc, outputfile = get_doc_and_name(input_file)

        # iterate over sents, get the first comment which contains the article number
        for s, sent in (enumerate(input_doc.sentences)):
            art_num = sent.comments[0]
            # add article metas if start of new article
            if art_num_prev != art_num :
                if s>0:
                    articles_processed.append(current_article)
              # get the article metadata for the current sentence
              # and make an etree for this article
                current_article = start_article(sent, input_file)

            ## modify inplace
            process_sentence(current_article, sent)
            art_num_prev = art_num

        # add final article to processed_list as there's no
        articles_processed.append(current_article)

        # when all the articles have been processed, append them to the output tree
        for item in articles_processed:
            outputtree.append(item)

        finalise_and_export_tree(outputtree, year, lang, outputfile)
        return 0

    ## catch and log all exceptions without interrupting pipeline
    except Exception as e:
        logger.error(f"❌ Error processing {input_file}: {e}", exc_info=True)
        return 1  # Always return something so callback triggers

def finalise_and_export_tree(
  output_tree: etree._Element,
  year: str,
  lang: str,
  outputfile: str
  )-> None:
    """Finalise etree metadata and export to file

    Args:
        output_tree (etree._Element): etree element containing processed articles.
        year (str): Year as indicated in the same of the source parquet file.
            This value is added to the TEI header in the `<date>` element.
        lang (str): A language code (`fr`, `en`, `it`…) to add to TEI header as 
            the value of the `<lang>` element's `ident` attribute.
        outputfile (Union[str, Path]): String/Path to the output file to be created. 

    Returns:
        None. The input etree element is modified in-place then exported.
    """
    ## tidy year, lang values, renumber sent ids
    set_year_lang_sentids(output_tree, year, lang)
    # ensure that s elements have a parent p element,
    # and that p elements have a parent <body> element
    restructure_body_elements(output_tree)

    # tidy the custom source_desc xml element
    finalise_source_desc_els(output_tree)

    final_tree = etree.ElementTree(output_tree)
    final_tree.write(outputfile, encoding='UTF-8', pretty_print=True, xml_declaration=True)


def process_sentence(current_article: etree._Element, sent: Sentence) -> None:
    """Add CoNLL sentence to an etree Element as a  new child <s> element

    Args:
        current_article (etree._Element): etree element of the current article
        sent (Sentence): A CoNLL sentence object 

    Returns:
        None. etree Element is modified in-place.
    """
    sent_metas = [sent.comments[i] for i in [14,1]]
    parent = current_article.findall(".//body")[0]
    current_sent_el = etree.SubElement(parent, 's')
    current_sent_el.text = get_tidy_sent_text(sent)
    current_sent_el.set('uuid', sent_metas[1].replace('# sent_ID = ',''))


def get_tidy_sent_text(sent: Sentence) -> str:
    """Normalizes token text from a CoNLL sentence object by joining tokens 
    and replacing curly quotes with straight quotes.

    Args:
        sent (Sentence): A CoNLL sentence object 

    Returns:
        str: A cleaned string of the sentence text wrapped in newlines.
    """
    # Use a list comprehension over token as conll text
    tokens_as_conll = [re.sub(r"’", "'", token.to_conll_text()) for token in sent.tokens]

    # Join, wrap with line breaks, and clean curly quotes
    intermed_text = "\n" + "\n".join(tokens_as_conll) + '\n'
    tidied_text = intermed_text.replace('”', '"').replace('“', '"')

    return tidied_text

def finalise_source_desc_els(output_tree: etree._Element) -> None:
    """Tidies the custom source_desc XML element by moving child data to attributes.

    This function finds all <sourceDesc> elements and extracts data from their 
    child elements. It specifically looks for a date string (expected at index 1) 
    and a URL (expected at index 2). It then sets these as attributes on the 
    parent <sourceDesc> tag and removes the child elements to clean up the tree.

    Args:
        output_tree (etree._Element): The root TEI XML tree element.

    Returns:
        None: This function modifies the `output_tree` object in-place.
    """
    # Find all sourceDesc elements in the tree
    source_desc_els = output_tree.findall(".//sourceDesc")

    for current_el in source_desc_els:
        # Get all child elements
        subels = current_el.findall(".//*")

        # Initialize default values
        raw_date: Optional[str] = None
        raw_url: Optional[str] = None

        # Safe retrieval: Check if elements exist before accessing index
        if len(subels) > 1:
            raw_date = subels[1].text

        if len(subels) > 2:
            raw_url = subels[2].text

        # Logic for date parsing with defaults
        # If raw_date exists, try to slice month/day; otherwise default to '01'
        datetime_val = raw_date if raw_date else "UNK"
        month_val = raw_date[5:7] if raw_date and len(raw_date) >= 7 else "01"
        day_val = raw_date[8:10] if raw_date and len(raw_date) >= 10 else "01"

        # Logic for URL with default
        url_val = raw_url if raw_url else "UNK"

        # Set attributes on the sourceDesc element
        current_el.set("datetime", datetime_val)
        current_el.set("month", month_val)
        current_el.set("day", day_val)
        current_el.set("ccrawl_url", url_val)

        # Remove the child elements to keep the sourceDesc tag "tidy"
        for el in subels:
            current_el.remove(el)

def restructure_body_elements(output_tree: etree._Element) -> None:
    """Restructures the XML tree by wrapping all sentence elements inside a paragraph element.

    This function traverses the XML tree to find all `<body>` elements. For each body 
    found, it identifies all child `<s>` elements (representing sentences) and 
    moves them inside a newly created `<p>` (paragraph) element. This ensures 
    the tree follows the expected schema where sentences are nested within paragraphs.

    Args:
        output_tree (etree._Element): The root element of the TEI XML tree.

    Returns:
        None: This function modifies the `output_tree` object in-place.
    """
    # Find all body elements in the tree
    body_els = output_tree.findall(".//body")

    for body_el in body_els:
        # Find all sentence elements (s) within this body
        s_blocks = body_el.findall(".//s")

        # Create a new paragraph (p) element as a child of the body
        p_block = etree.SubElement(body_el, 'p')

        # Move every sentence block into the new paragraph element
        for s_block in s_blocks:
            body_el.remove(s_block)
            p_block.append(s_block)

def set_year_lang_sentids(output_tree: etree._Element, year: str, lang: str) -> None:
    """Reset Year, Language and sent ID values in an XML tree

    This function traverses the XML tree to find all `<date>`, `<language>` and 
    `<s>`elements. <s> elements are renumbered with sequential IDs as integers. 
    `<date>` is set to the year of the source 
    found, it identifies all child `<s>` elements (representing sentences) and 
    moves them inside a newly created `<p>` (paragraph) element. This ensures 
    the tree follows the expected schema where sentences are nested within paragraphs.

    Args:
        output_tree (etree._Element): The root element of the TEI XML tree.
        year (str): The year to be set as text of the `<date>` element
        lang (str): The language code to be set in the `<ident> attribute of the
            `<language>` element in the TEI header.
    Returns:
        None: This function modifies the `output_tree` object in-place.
    """
    # tidy the output tree by inserting the date and language
    for el in output_tree.findall(".//date"):
        el.text = year
    for el in output_tree.findall(".//language"):
        el.set("ident", str(lang))
    # tidy sent_ids by removing the UUIDs and renumbering from 1
    for snum, sblock in enumerate(output_tree.findall(".//s"), start=1):
        sblock.set("id", str(snum))
        _ = sblock.attrib.pop("uuid")

def generate_file_list(year: str, lang: str, mode: str, publi: str) -> List[str]:
    """Generate the list of files to process based on year, language, and selection mode.

    This function constructs a file path for a specific language and year, then 
    filters the files based on a publication pattern and a selection mode 
    ('A' for All, 'E' for Even, 'O' for Odd).

    Args:
        year (str): The year for which files are to be processed.
        lang (str): The language code for the language to be processed.
        mode (str): The selection mode:
            - 'A': Matches all files with the .conll extension.
            - 'E': Matches only those containing an even number before the extension.
            - 'O': Matches only those containing an odd number before the extension.
        publi (str): The file pattern used to restrict matches to a specific 
            publication.

    Returns:
        List[str]: A sorted list of absolute paths to the files to be processed.
    """
    base_path = f'/Volumes/HC3Beta/uncompressed_parquet/cc_{lang}/{year}/3_conllu_out'

    # Map the modes to their specific glob patterns
    patterns = {
        "A": f"/{publi}*.conll",
        "E": f"/{publi}*[02468]*.conll",
        "O": f"/{publi}*[13579]*.conll"
    }

    if mode not in patterns:
        print(f"Error: No valid mode selected. Choose from {list(patterns.keys())}")
        sys.exit(0)

    # Execute glob only once using the pattern selected from the dictionary
    pattern = patterns[mode]
    files = sorted(glob.glob(base_path + pattern))

    return files

def define_poolsize(nproc: int, file_list: List[str]) -> int:
    """Calculates the optimal number of worker processes to use.

    The pool size is determined by the minimum of the requested processes,
    the available system CPUs, and the total number of files to process,
    ensuring at least one process is always used.

    Args:
        nproc (int): The requested number of parallel processes.
        file_list (List[str]): A list of file paths to be processed.

    Returns:
        int: The final calculated number of processes to initialize in the pool.
    """
    # Ensure pool_size is at least 1, and no more than nproc or available CPUs
    pool_size = max(1, min(nproc, cpu_count()))

    if pool_size >= len(file_list):
        pool_size = len(file_list)
        print(f"Using pool size == file size == {pool_size}")
    else:
        print(f"Using pool size: {pool_size}")

    return pool_size


def run_main_processing(config: MainProcessingConfiguration):
    """
    Convert conll files to XML with a pool of parallel processes
    Args:
      config (MainProcessingConfiguration): dataclass with parameters for the 
      processing pipeline, including the following:
      
        year : str: year for which files are to be processed
        mode (str): The selection mode:
            - 'A': Matches all files with the .conll extension.
            - 'E': Matches only those containing an even number before the extension.
            - 'O': Matches only those containing an odd number before the extension.
        lang : str : language code for the language to be processed
        nproc : int : number of processors in the pool
        log_path : absolute path to which to write the log
        publi: char : file pattern to select files to process
    Returns:
        results : list : a list of results from the pool processors
    """
    logger = setup_logger(config.log_path)

    # generate list of files
    file_list = generate_file_list(config.year, config.lang, config.mode, config.publi)
    logger.info("Found %s files to process.", len(file_list))

    # create the pool with sanity checks
    pool_size = define_poolsize(config.nproc, file_list)

    ## make worker
    worker_func = partial(process_file, year=config.year, lang=config.lang, logger=logger)

    # map the work to the pool
    with Pool(pool_size) as pool, tqdm(
      total=len(file_list),
      desc="Processing",
      unit="file"
      ) as pbar:
        results = []
        for file_path in file_list:
            # Submit tasks asynchronously
            r = pool.apply_async(
              worker_func,
              (file_path,),
              callback=lambda _: pbar.update(1)
              )
            results.append(r)

        # Wait for all tasks to complete
        for r in results:
            r.wait()
    logger.info("✅ All processing complete.")
    print("Processing complete.")

    return results

#################################################################################################
############################       end of functions  ##########################
#################################################################################################




if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        prog='conll_out_to_article_xml',
        formatter_class=argparse.RawTextHelpFormatter,
        description='''\
    Read conll files and send send to XML

    Examples of usage:
    ## use 4 processors in a pool to find all files from 2020 with smh
    in the filename located in the English subfolder, convert them to XML,
    and then consolidate these into 1 output XMLfile

    send_to_xml.py -year 2020 -mode A -lang en --nproc 4 --consolidate -publi smh

    ## use 3 processors in a pool to find all files from 2017 with `monde`
    in the filename AND an even number, located in the French subfolder,
    convert them to XML, without consolidating

    send_to_xml.py -year 2017 -mode E -lang fr --nproc 5 -publi monde

    '''
    )

    ### parser - reading arguments
    parser.add_argument(
      '--year',
      help='''Year in cc_corpus/ folder''',
      default=""
      )
    parser.add_argument(
      '--mode',
      help='''E for Even, O for Odd, A for all''',
      default="A"
      )
    parser.add_argument(
      "--nproc",
      type=int,
      default=4,
      help="Number of parallel processes"
      )
    parser.add_argument(
      '--lang',
      help='''lang''',
      default=""
      )
    parser.add_argument(
      "--log",
      type=str,
      default="/data/logs/my_log.log",
      help="Path to log file"
      )
    parser.add_argument(
      '--consolidate',
      action="store_true",
      default=False,
      required=False,
      help='''When done, consolidate to single XML file'''
      )
    parser.add_argument(
      '--publi',
      type=str,
      default="",
      help='''file pattern to process'''
      )
    args = parser.parse_args()
    args_config = MainProcessingConfiguration(
        year = args.year,
        mode = args.mode,
        lang = args.lang,
        nproc = args.nproc,
        log_path = args.log,
        publi = args.publi
    )
    run_main_processing(args_config)
    if args.consolidate:
        consolidate_xmls(args.lang, args.year, args.publi)
