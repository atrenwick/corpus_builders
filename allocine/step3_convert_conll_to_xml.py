"""Convert conll files to XML-TEI compatible .xml documents"""
import argparse
import copy
import os
import re

from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
from typing import List, Optional, Union

from lxml import etree
from stanza.utils.conll import CoNLL
from stanza.models.common.doc import Sentence
from tqdm import tqdm

# Global variable to hold the raw XML string
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
          <language ident="fr"/>
        </langUsage>
        <textDesc thema="" type="" sub_genre=""/>
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


def make_tidy_sent_element(sent: Sentence, current_sent_el: etree._Element) -> str:
    """Add sentence metadata and normalize token text.
    
    Args:
        sent (Sentence): A sentence object containing a list of tokens 
            with a .to_conll_text() method.
        current_sent_el (etree._Element): an etree Element of type <s>
    Returns:
        None. etree element modified in-place
    """
    ## text is data
    intermed_text = "\n" + "\n".join(
        [re.sub("’", "'", token.to_conll_text()) for token in sent.tokens]
    ) + '\n'
    tidy_text_string = intermed_text.replace('”', '"').replace('“', '"')
    current_sent_el.text = tidy_text_string

    ## metas
    # Assign UUID from the second comment (e.g., "# sent_ID = ...")
    uuid_val = sent.comments[1].replace('# sent_ID = ', '')
    current_sent_el.set('uuid', uuid_val)



def start_article(art_metas: List[str]) -> etree._Element:
    """
    Initializes a new TEI XML structure for an article using a predefined 
    XML template and populates the title with the article number.

    The function uses a pre-parsed global template and creates a deep copy 
    of it to ensure thread safety and to prevent modifications from persisting 
    between function calls.

    Args:
        art_metas (List[str]): A list of metadata strings. The first element 
            is expected to be the article number string 
            (e.g., "# Article_num = 123").

    Returns:
        etree._Element: An etree element representing the initialized 
            TEI article structure.
    """
    # Create a deep copy of the template so the global object remains unchanged
    article_mould = copy.deepcopy(ARTICLE_MOULD_TEMPLATE)

    # Extract the number from the meta string and assign to title
    title_element = article_mould.findall('.//title')[0]
    title_element.text = art_metas[0].replace("# Article_num = ", "")

    return article_mould

def finalize_and_export_tree(
  articles_processed: List[etree._Element],
  lang: str,
  outputfile: Path
  ) -> None:
    """
    Constructs a final TEI Corpus XML tree from processed articles, tidies the 
    structure (language, IDs, and paragraph wrapping), and exports to a file.

    The function performs the following tidying steps:
    1. Wraps all processed articles in a <teiCorpus> element.
    2. Updates the 'ident' attribute of all <language> elements to the provided lang.
    3. Renumbers all <s> elements sequentially starting from 1 and removes their 'uuid' attribute.
    4. Wraps all <s> elements inside a single <p> element within each <body>.

    Args:
        articles_processed (List[etree._Element]): A list of lxml etree elements 
            representing processed articles.
        lang (str): The language identifier (e.g., 'fr') to assign to the corpus.
        outputfile (Path): A pathlib.Path object where the final XML will be saved.

    Returns:
        None
    """
    # Initialize the root corpus element
    outputtree = etree.fromstring("<teiCorpus></teiCorpus>")

    # Append all processed articles to the corpus
    for item in articles_processed:
        outputtree.append(item)

    # Update language identifiers across the entire tree
    for el in outputtree.findall(".//language"):
        el.set("ident", str(lang))

    # Tidy sent_ids by removing the UUIDs and renumbering from 1
    # We use .pop("uuid", None) to avoid KeyErrors if the attribute is missing
    for snum, sblock in enumerate(outputtree.findall(".//s"), start=1):
        sblock.set("id", str(snum))
        sblock.attrib.pop("uuid", None)

    # Add p level between body and s to ensure tree has expected structure
    # This wraps all <s> elements within a single <p> for each <body> found
    for body_el in outputtree.findall(".//body"):
        p_block = etree.SubElement(body_el, 'p')
        for s_block in body_el.findall(".//s"):
            body_el.remove(s_block)
            p_block.append(s_block)

    # Create the final ElementTree and write to disk
    final_tree = etree.ElementTree(outputtree)
    final_tree.write(
        str(outputfile),
        encoding='UTF-8',
        pretty_print=True,
        xml_declaration=True
    )

    print(f"Successfully processed {outputfile.name} -> {outputfile}")

def conll_to_structured_xml(
    input_file: str,
    output_dir: str,
    lang: str
) -> None:
    """Converts a CoNLL formatted file into a structured TEI XML file.

    The process involves grouping sentences by article number, generating 
    TEI XML wrappers for each article, normalizing sentence text, and 
    performing final tree tidying (renumbering IDs and nesting sentences 
    within paragraph tags).

    Args:
        input_file (str): Path to the source .conll file.
        output_dir (str): Directory path where the resulting .xml file will be saved.
        lang (str): The language identifier to assign to the XML (e.g., 'fr').

    Returns:
        None: Writes the output directly to a file.

    Raises:
        Exception: Catches and prints errors occurring during the parsing or 
            writing process.
    """
    # Prepare output path
    outputfile_basename = os.path.basename(input_file).replace('.conll', 'v2.xml')
    outputfile = Path(output_dir) / outputfile_basename

    # Load the CoNLL document
    input_doc = CoNLL.conll2doc(input_file)

    art_num_prev: int = -1
    current_article: Optional[etree._Element] = None
    articles_processed: List[etree._Element] = []

    try:
        # Iterate over sentences
        for _, sent in enumerate(input_doc.sentences):
            # Get article number from first comment (e.g., "# Article_num = 123")
            # Assumes sent.comments[0] exists and contains the article header
            art_num = sent.comments[0]

            # 1. Handle Article Transition
            if art_num != art_num_prev:
                # If we were already processing an article, save it before starting the new one
                if current_article is not None:
                    articles_processed.append(current_article)

                # Start new article using the helper function
                art_metas = [art_num]
                current_article = start_article(art_metas)
                art_num_prev = art_num

            # 2. Process Sentence
            # Find the body tag and create a new sentence element
            parent = current_article.findall(".//body")[0]
            current_sent_el = etree.SubElement(parent, 's')

            # Clean and assign text
            make_tidy_sent_element(sent, current_sent_el)

        # Add the final article processed to the list
        if current_article is not None:
            articles_processed.append(current_article)

        # Finalize the tree structure and export to disk
        finalize_and_export_tree(articles_processed, lang, outputfile)

    except Exception as e:
        print(f"Error processing {input_file}: {e}")



def run_parallel_processing(
  file_list: List[Union[str, Path]],
  output_directory: Union[str, Path],
  lang: str,
  n_proc: int
  ):
    """
    Processes multiple CoNLL files in parallel.

    Args:
        file_list (List[Union[str, Path]]): List of paths to the .conll files.
        output_directory (Union[str, Path]): Directory to save the resulting XMLs.
        lang (str): Language identifier (e.g., 'fr').
        n_proc (int): Number of worker processes to spawn. 
                      If None or 0, it will use all available CPU cores.
    """
    # Create a partial function that freezes output directory and lang inputs
    worker = partial(conll_to_structured_xml, output_dir=output_directory, lang=lang)

    # Determine the number of workers
    workers = n_proc if n_proc and n_proc > 0 else None

    print(f"Starting parallel processing with {workers if workers else 'all available'} cores...")

    with ProcessPoolExecutor(max_workers=workers) as executor:
        # map distributes the file_list across the specified number of workers
        # tqdm provides a progress bar for the total number of files
        results = list(tqdm(executor.map(worker, file_list), total=len(file_list)))

    # Log any errors encountered during processing
    errors = [res for res in results if res and "Error" in res]
    if errors:
        print(f"\nCompleted with {len(errors)} errors:")
        for err in errors:
            print(err)
    else:
        print("\nAll files processed successfully.")


def get_pool_size(n_procs: int, file_list: List[Union[str, Path]]) -> int:
    """Determine an appropriate size for a processing pool.

    The pool size is calculated by finding the minimum of the requested processes,
    the number of files to process, and the available CPU cores. The result 
    is guaranteed to be at least 1.

    Args:
        n_procs (int): The maximum number of processes requested by the user.
        file_list (List[Union[str, Path]]): A list of file paths (as strings or 
            Path objects) to be processed.

    Returns:
        int: The calculated pool size.
    """
    # Get available CPU cores, defaulting to 1 if unknown
    cores = os.cpu_count() or 1

    return max(1, min(n_procs, len(file_list), cores))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
      description='''Convert CoNLL parsed files to tidy XML in parallel.

    Usage : 
      python3 /scripts/3_convert_conll_to_xml.py -source_dir /data/source\
          -output_dir /data/target/ -lang fr -n_procs 4

    ''')
    parser.add_argument(
        "-source_dir", type=str,help="folder with source CoNLL files", required=True
    )
    parser.add_argument(
        "-output_dir", type=str,help="folder for exported XML files", required=True
    )
    parser.add_argument(
        "-lang", type=str,help="Language of files to be processed", required=True
    )
    parser.add_argument(
        "-n_procs", type=int,help="Number of workers", default=4
    )

    args = parser.parse_args()

    file_list_for_run = [str(p) for p in Path(args.source_dir).glob("*.conll")]
    n_procs_pool = get_pool_size(args.n_procs, file_list_for_run)
    run_parallel_processing(file_list_for_run, args.output_dir, args.lang, n_proc=n_procs_pool)
