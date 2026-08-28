import glob
import os
import argparse
import re
from pathlib import Path

from stanza.utils.conll import CoNLL
from lxml import etree
from tqdm import tqdm

from functools import partial
from multiprocessing import cpu_count
from concurrent.futures import ProcessPoolExecutor


def make_tidy_conll_text_strings(sent):
    """
    Normalizes token text from a CoNLL sentence object by joining tokens 
    and replacing curly quotes with straight quotes.

    Args:
        sent (Sentence): A sentence object containing a list of tokens 
                         with a .to_conll_text() method.

    Returns:
        str: A cleaned string of the sentence text wrapped in newlines.
    """
    intermed_text = "\n" + "\n".join([re.sub("’", "'", token.to_conll_text()) for token in sent.tokens]) + '\n'
    tidy_text_string = intermed_text.replace('”', '"').replace('“', '"')
    return tidy_text_string

def start_article(art_metas):
    """
    Initializes a new TEI XML structure for an article using a predefined 
    XML template and populates the title with the article number.

    Args:
        art_metas (list): A list of metadata strings. The first element 
                          is expected to be the article number string 
                          (e.g., "# Article_num = 123").

    Returns:
        lxml.etree._Element: An etree element representing the initialized 
                             TEI article structure.
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

    article_mould = etree.fromstring(raw_str_header)
    # Extract the number from the meta string and assign to title
    article_mould.findall('.//title')[0].text = art_metas[0].replace("# Article_num = ", "")
    return article_mould

def conll_to_structured_xml(input_file, output_dir, lang):
    """
    Converts a CoNLL formatted file into a structured TEI XML file.
    
    The process involves grouping sentences by article number, generating 
    TEI XML wrappers for each article, normalizing sentence text, and 
    performing final tree tidying (renumbering IDs and nesting sentences 
    within paragraph tags).

    Args:
        input_file (str): Path to the source .conll file.
        output_dir (str): Directory path where the resulting .xml file will be saved.

    Returns:
        None: Writes the output directly to a file.
    """
    outputfile_basename = os.path.basename(input_file).replace('.conll', 'v2.xml')
    outputfile = Path(output_dir) / outputfile_basename # Using / operator for Path
    input_doc = CoNLL.conll2doc(input_file)
    
    
    art_num_prev = -1
    outputtree = etree.fromstring("<teiCorpus></teiCorpus>")
    current_article = None
    articles_processed = []

    try:
        # iterate over sents ## can add tqdm here for more detailed output
        for s, sent in enumerate(input_doc.sentences):
            # get article number from first comment.
            art_num = sent.comments[0]
            
            # 1. Handle Article Transition
            if art_num != art_num_prev:
                # If we were already processing an article, save it before starting the new one
                if current_article is not None:
                    articles_processed.append(current_article)
                
                # Start new article
                art_metas = [art_num]
                current_article = start_article(art_metas)
                art_num_prev = art_num
    
            # 2. Process Sentence 
            sent_metas = sent.comments 
            parent = current_article.findall(".//body")[0]
            
            current_sent_el = etree.SubElement(parent, 's')
            current_sent_el.text = make_tidy_conll_text_strings(sent)
            current_sent_el.set('uuid', sent_metas[1].replace('# sent_ID = ', ''))
          
        # Add the final article processed to the list
        if current_article is not None:
            articles_processed.append(current_article)
          
        # when all sentences have been processed, make output tree:
        for item in articles_processed:
            outputtree.append(item)
      
        # all sentences in the current file have now been processed, so tidy the tree :
        for el in outputtree.findall(".//language"):
            el.set("ident", str(lang)) 
    
        # tidy sent_ids by removing the UUIDs and renumbering from 1
        for snum, sblock in enumerate(outputtree.findall(".//s"), start=1):
            sblock.set("id", str(snum))
            _ = sblock.attrib.pop("uuid")
        
        # add p level between body and s to ensure tree has expected structure
        body_els = outputtree.findall(".//body")
        for body_el in body_els:
            s_blocks = body_el.findall(".//s")
            p_block = etree.SubElement(body_el, 'p')
            for s_block in s_blocks:
                body_el.remove(s_block)
                p_block.append(s_block)
        
        final_tree = etree.ElementTree(outputtree)
        final_tree.write(outputfile, encoding='UTF-8', pretty_print=True, xml_declaration=True)
        print(f"Successfully processed {outputfile_basename} -> {outputfile}")
    except Exception as e:
        return f"Error processing {input_file}: {e}"

def run_parallel_processing(file_list, output_directory, lang, n_proc):
    """
    Processes multiple CoNLL files in parallel.

    Args:
        file_list (list): List of paths to the .conll files.
        output_directory (str): Directory to save the resulting XMLs.
        language (str): Language identifier (e.g., 'fr').
        n_proc (int): Number of worker processes to spawn. 
                      If None or 0, it will use all available CPU cores.
    """
    # Create a partial function that 'pre-fills' output_dir and lang
    # The worker function now only needs the 'input_file' argument
    worker = partial(conll_to_structured_xml, output_dir=output_dir, lang=lang)

    # Determine the number of workers
    # If n_proc is 0 or None, ProcessPoolExecutor defaults to os.cpu_count()
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

def get_pool_size(n_procs, file_list, cpu_count):
    """
    Determine an appropriate size for a processing pool.

    - Never exceed the number of files to process.
    - Never exceed the number of CPU cores available.
    """
    return max(1, min(n_procs, len(file_list), cpu_count))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='''Convert CoNLL parsed files to tidy XML in parallel.
    
    Usage : 
      python3 /scripts/3_convert_conll_to_xml.py -source_dir /data/source -output_dir /data/target/ -lang fr -n_procs 4
            
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

    source_dir = args.source_dir
    output_dir = args.output_dir
    lang = args.lang
    file_list = [str(p) for p in Path(source_dir).glob("*.conll")]
    current_cpu_count = cpu_count()
    n_procs = get_pool_size(args.n_procs, file_list, current_cpu_count)
    
    # You can now specify exactly how many cores to use (e.g., 4)
    run_parallel_processing(file_list, output_dir, lang, n_proc=n_procs)
