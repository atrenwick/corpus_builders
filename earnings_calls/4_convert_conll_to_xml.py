import argparse
import glob
import os
import re

from pathlib import Path
from lxml import etree
from typing import Any, Dict, List, Optional
from tqdm import tqdm
from stanza.utils.conll import CoNLL
from functools import partial
from multiprocessing import Pool, cpu_count
from multiprocessing.pool import AsyncResult


def generate_file_list(source_dir: str) -> List[str]:
    """Generates a sorted list of .conll files located in the specified directory.

    Args:
        source_dir (str): The path to the directory containing the files to be processed.

    Returns:
        List[str]: An alphabetically sorted list of paths to all files ending in '.conll'
            found within the source directory.
    """
    # Use os.path.join to ensure the path is constructed correctly regardless of OS
    search_pattern = os.path.join(source_dir, "*.conll")
    file_list = sorted(glob.glob(search_pattern))
    
    return file_list

def get_clean_sentence_text(sent: Any) -> str:
    """
    Extracts tokens from a sentence object, standardizes quotes, 
    and formats the text with surrounding newlines.

    Args:
        sent (Any): A sentence object containing a list of tokens. 
            Each token must have a `to_conll_text()` method.

    Returns:
        str: The cleaned and formatted text string.
    """
    # 1. Extract text from tokens and replace smart single quotes (’)
    # We use a list comprehension to process each token in the sentence
    tokens_cleaned = [re.sub("’", "'", token.to_conll_text()) for token in sent.tokens]
    
    # 2. Join tokens with newlines and wrap with leading/trailing newlines
    intermed_text = "\n" + "\n".join(tokens_cleaned) + "\n"
    
    # 3. Replace smart double quotes (“ and ”) with standard double quotes (")
    return intermed_text.replace('”', '"').replace('“', '"')

def process_file(input_file: str, output_dir: str) -> int:
    """
    Converts a CoNLL formatted file into a TEI XML file.
    
    This function parses a CoNLL file, extracts metadata from comments to group 
    sentences into 'articles', cleans the text (standardizing quotes), 
    and structures the result into a specific XML hierarchy with re-indexed IDs.

    Args:
        input_file (str): Path to the source .conll file.
        output_dir (str): Directory where the resulting .xml file will be saved.

    Returns:
        int: Returns 0 if processing was successful, 1 if an exception occurred.
    """
    try:
        # Handle filename transformation
        # Replaces .conll with .xml and swaps folder names in the basename
        output_basename = os.path.basename(input_file).replace('.conll', '.xml')
        output_fullpath = Path(output_dir) / output_basename
        
        input_doc = CoNLL.conll2doc(input_file)
        art_num_prev = -1
        outputtree = etree.fromstring("<teiCorpus></teiCorpus>")
        
        current_article = None
        articles_processed = []
        
        for s, sent in enumerate(input_doc.sentences):
            # Get article number from the first comment
            art_num = sent.comments[0]
            
            # Case 1: Sentence belongs to the same article as the previous sentence
            if art_num_prev == art_num:
                # Indices 2, 1, 10 are used for metadata extraction
                sent_metas = [sent.comments[i] for i in [2, 1, 10]]
                parent = current_article.findall(".//body")[0]
                
                current_sent_el = etree.SubElement(parent, 's')
                
                # Clean text: normalize smart quotes and join tokens
                current_sent_el.text = get_clean_sentence_text(sent)
                
                current_sent_el.set('uuid', sent_metas[1].replace('# sent_ID = ', ''))
                current_sent_el.set("type", "dd")
                current_sent_el.set("speakername", str(sent_metas[2].replace('#speakername=', '')))

            # Case 2: This is the start of a new article
            else:
                # If we were already processing an article, save it before starting the new one
                if current_article is not None:
                    articles_processed.append(current_article)
                
                # Extract article-level metadata (indices 0-9)
                art_metas = [sent.comments[i] for i in range(10)]
                
                # Initialize new article XML structure via helper function
                current_article = start_call(art_metas, input_file)
                
                # Process the first sentence of the new article
                sent_metas = [sent.comments[i] for i in [12, 1]]
                parent = current_article.findall(".//body")[0]
                current_sent_el = etree.SubElement(parent, 's')
                
                current_sent_el.text = get_clean_sentence_text(sent)
                current_sent_el.set('uuid', sent_metas[1].replace('# sent_ID = ', ''))
                
                art_num_prev = art_num

        # Append the final article processed in the file
        if current_article is not None:
            articles_processed.append(current_article)

        # Build the final XML tree
        for item in articles_processed:
            outputtree.append(item)

        # Tidy up the tree: 
        # 1. Remove temporary UUIDs and re-index sentences starting from 1
        for snum, sblock in enumerate(outputtree.findall(".//s"), start=1):
            sblock.set("id", str(snum))
            if "uuid" in sblock.attrib:
                sblock.attrib.pop("uuid")
        
        # 2. Wrap sentence blocks (<s>) inside a paragraph block (<p>) within the body
        body_els = outputtree.findall(".//body")
        for body_el in body_els:
            s_blocks = body_el.findall(".//s")
            p_block = etree.SubElement(body_el, 'p')
            for s_block in s_blocks:
                body_el.remove(s_block)
                p_block.append(s_block)
        
        # Write to file
        final_tree = etree.ElementTree(outputtree)
        final_tree.write(
            output_fullpath, 
            encoding='UTF-8', 
            pretty_print=True, 
            xml_declaration=True
        )
        return 0

    except Exception as e:
        print(f"❌ Error processing {os.path.basename(input_file)}: {e}", exc_info=True)
        return 1

def make_s_blockopener(sent_metas: List[str]) -> str:
    """
    Parse sentence CoNLL metadata to create an XML opening tag for a sentence block.

    Args:
        sent_metas (List[str]): A list of metadata strings extracted from CoNLL comments.
            Expected indices: [0] = serial ID, [1] = UUID.

    Returns:
        str: A formatted XML string: '<s id="..." uuid="...">'.
    """
    # Use .strip() to ensure no trailing newlines or spaces remain after replacement
    sent_serial = sent_metas[0].replace("# sent_id_serial = ", "").strip()
    sent_uuid = sent_metas[1].replace('# sent_ID = ', '').strip()
    s_string_open = f'\n<s id="{sent_serial}" uuid="{sent_UUID}">'
    
    return s_string_open

def make_sourceDesc_dict(art_metas: List[str], input_file: str) -> Dict[str, str]:
    """
    Extract article metadata from CoNLL lines and organize it into a dictionary.

    This dictionary acts as a single source of truth for article-level metadata 
    which can be mapped to XML elements later.

    Args:
        art_metas (List[str]): A list of metadata strings. 
            Expected indices:
            0: Article Num, 3: ID, 4: Company, 5: Quarter, 6: Fiscal Qtr, 
            7: Actual Date, 8: Month, 9: Day.
        input_file (str): The path to the source file, used to generate the source location.

    Returns:
        Dict[str, str]: A dictionary containing cleaned metadata fields.
    """
    # Pre-clean common fields to avoid repeating .replace() multiple times
    company = art_metas[4].replace("# company=", "").strip()
    fqtr = art_metas[6].replace("# fqtr=", "").strip()
    actual_date = art_metas[7].replace("# acutaldate=", "").strip()
    
    # Generate formatted helper strings
    article_title = f"Earnings Call - {company} - {fqtr}"
    # Takes first 20 chars of filename and appends the row ID
    row_id = art_metas[3].replace("# id=", "").strip()
    article_index_num = f'{os.path.basename(input_file)[:20]}.parquet row {row_id}'
    
    source_desc = {
        'num': art_metas[0].replace("# Article_num = ", "").strip(),
        'title': article_title,
        'company': company,
        'fiscal_quarter_reporting': fqtr,
        'calendar_quarter': art_metas[5].replace("# quarter=", "").strip()[:1],
        'source_location': article_index_num,
        'full_date': actual_date,
        'yyyy': actual_date[:4],
        'mm': art_metas[8].replace("# month=", "").strip(),
        'dd': art_metas[9].replace("# day=", "").strip(),  
    }
    
    return source_desc

def start_call(art_metas: List[str], input_file: str) -> etree._Element:
    """
    Create a TEI XML structure for a single call and populates it with metadata.

    This function uses a raw XML template as a 'mould', then fills in the 
    header elements (title, author, date) and adds metadata attributes to 
    the sourceDesc element using a helper dictionary.

    Args:
        art_metas (List[str]): A list of metadata strings extracted from CoNLL comments.
        input_file (str): Path to the source file (passed to the metadata dictionary helper).

    Returns:
        etree._Element: An lxml element representing the structured XML for one article.
    """
    raw_str_header = '''
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
                    <language ident="en"/>
                </langUsage>
                <textDesc thema="" type="earnings_call" sub_genre=""/>
            </profileDesc>
        </teiHeader>
        <text>
            <body>
            </body>
        </text>
    </TEI.2>
    '''

    # Parse the template string into an etree element
    article_mould = etree.fromstring(raw_str_header)
    
    # 1. Get the cleaned metadata dictionary first to avoid repeating .replace() logic
    # We pass both art_metas and input_file as required by make_sourceDesc_dict
    source_desc_dict = make_sourceDesc_dict(art_metas, input_file)
    
    # 2. Populate the main header elements
    # Use .find() instead of .findall()[0] for better readability and performance
    title_el = article_mould.find('.//title')
    if title_el is not None:
        title_el.text = source_desc_dict['title']
        
    author_el = article_mould.find('.//author')
    if author_el is not None:
        author_el.text = source_desc_dict['company']
        
    date_el = article_mould.find('.//date')
    if date_el is not None:
        date_el.text = source_desc_dict['yyyy']
    
    # 3. Populate the sourceDesc element attributes
    source_desc_el = article_mould.find(".//sourceDesc")
    if source_desc_el is not None:
        for key, value in source_desc_dict.items():
            source_desc_el.set(key, value)

    return article_mould


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

def run_processing(source_dir: str, output_dir: str, nproc: int) -> List[AsyncResult]:
    """Parallel processing of files with robust logging and progress tracking.

    This function identifies files in the source directory, initializes a 
    multiprocessing pool, and executes a processing worker on each file.

    Args:
        source_dir (str): The path to the directory containing the source files.
        output_dir (str): The path to the directory where xml files will be saved.
        nproc (int): The requested number of parallel processes. This will be 
            capped by the system's available CPU count.

    Returns:
        List[AsyncResult]: A list of AsyncResult objects returned by the 
            multiprocessing pool for each processed file.
    """
    ## get files
    file_list = generate_file_list(source_dir)

    # Step 2: create the pool
    pool_size = define_poolsize(nproc, file_list)

    ## make worker
    worker_func = partial(process_file, output_dir=output_dir)

    # Step 3: map the work to the pool
    with Pool(pool_size) as pool, tqdm(total=len(file_list), desc="Processing", unit="file") as pbar:
        results: List[AsyncResult] = []
        for file_path in file_list:
            # Apply async to avoid blocking the loop and allow the progress bar to update
            r = pool.apply_async(
                worker_func, 
                (file_path,), 
                callback=lambda _: pbar.update(1)
            )
            results.append(r)

        # Wait for all tasks to complete before exiting the 'with' block
        for r in results:
            r.wait()
            
    print("✅ All processing complete.")
    
    return results

def consolidate_xml_files(output_dir: str) -> None:
    """Consolidates yearly XML files into single annual corpus files.

    This function iterates through folders for years 2013 to 2024. For each year, 
    it gathers all XML files, extracts the <TEI.2> elements, and merges them 
    into a single <teiCorpus> root element, which is then saved as a 
    consolidated XML file.

    Args:
        output_dir (str): The base directory containing the year-specific 
            folders (e.g., '.../step4/') where the XML files are located.

    Returns:
        None
    """
    # Define the range of years to process
    for year_int in range(2013, 2025):
        year = str(year_int)
        
        # Construct path to the yearly folder: output_dir/year/*.xml
        search_pattern = os.path.join(output_dir, year, "*.xml")
        these_xmls = glob.glob(search_pattern)
        
        if not these_xmls:
            print(f"⚠️ No XML files found for year {year}, skipping...")
            continue

        # Initialize the root element for the consolidated corpus
        new_tree = etree.Element("teiCorpus")
        
        print(f"Consolidating {len(these_xmls)} files for year {year}...")
        for file in these_xmls:
            try:
                input_tree = etree.parse(file)
                # Find all TEI.2 elements within the current file
                elements = input_tree.findall(".//TEI.2")
                
                for element in elements:
                    new_tree.append(element)
            except etree.XMLSyntaxError as e:
                print(f"❌ Error parsing {file}: {e}")

        # Create the ElementTree object and write to disk
        final_tree = etree.ElementTree(new_tree)
        
        # Naming convention: output_dir/earnings_{year}.en.xml
        final_tree_name = os.path.join(output_dir, f"earnings_{year}.en.xml")
        
        final_tree.write(
            final_tree_name, 
            encoding='UTF-8', 
            pretty_print=True, 
            xml_declaration=True
        )
        
        print(f"✅ Exported to {os.path.basename(final_tree_name)}")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='''
    Read `.*.conllu_out.conllu` files from Stanza as conllu and send to XML
    
    Usage : 
      python3 /scripts/convert_conll_to_xml.py --source_dir /data/input --output_dir /data/output --nproc 10 --consolidate
            
    ''')
    
    # Added short-hand aliases (e.g., -s) for convenience
    parser.add_argument(
        '-s', '--source_dir', 
        type=str, 
        required=True, 
        help='Path to the directory containing parsed CoNLL files'
    )
    parser.add_argument(
        '-o', '--output_dir', 
        type=str, 
        required=True, 
        help='Path to the directory where XML files will be saved'
    )
    parser.add_argument(
        '-p', '--nproc', 
        type=int, 
        default=4, 
        help='Number of worker processes to request (default: 4)'
    )
    parser.add_argument(
        '-c', '--consolidate', 
        action="store_true", 
        default=False, 
        help="Consolidate all XMLs for a year into a single XML file"
    )    args = parser.parse_args()

    source_dir = args.source_dir
    output_dir = args.output_dir
    nproc = args.nproc
    run_consolidate = args.consolidate
    
    run_processing( source_dir, output_dir, nproc)
    if run_consolidate:
        consolidate_xml_files(output_dir)


