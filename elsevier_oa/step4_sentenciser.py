
import argparse
import glob
import os
import re
import sys
import uuid

from lxml import etree
from pathlib import Path
from tqdm import tqdm
from typing import List, Union, Tuple, Any, Optional

from functools import partial
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Pool

def mark_EOS(
    input_tree: etree._Element, 
    mode: str, 
    pagination_type: Union[str, int], 
    lang: str
) -> etree._Element:
    """
    Identifies and marks End-of-Sentence (EOS) tags in an XML tree.

    This function iterates through paragraph blocks in an XML tree and determines
    where sentences end based on punctuation, abbreviations, and language-specific
    rules. It marks the identified positions with an 'EOS' attribute and,
    in 'dev' mode, provides a reason for the tagging.

    Args:
        input_tree (etree._Element): The lxml XML tree to process.
        mode (str): The operational mode. Use "dev" to include additional
            annotations (EOS_reason) for debugging, or "prod" for standard
            processing.
        pagination_type (Union[str, int]): Controls EOS tagging at the end
            of paragraphs.
            - "1" (or 1): Forces the final element of a paragraph to be
              marked as an EOS.
            - "0" (or 0): Only marks the final element as EOS if it contains
              an EOS character.
        lang (str): A 2-character ISO language code (e.g., "en", "fr") to
            determine language-specific abbreviations.

    Returns:
        etree._Element: The modified XML tree with EOS attributes added.
    """
    # declaration of useful lists
    EOS_list = ("!", "?", r".", r'\n')
    punct_list = (";","-",",")
    right_els = ("”",'’', "»",'\"', "}", ")")
    excl_list = ('1','2','3','4','5','6','7','8','9','0', "com", "net", "L","M", "R")

    # use lang argument to load language specific abbreviations
    if lang == "en":
        abbrev_list = ("Mr", "Mrs","Dr","Bt")
    if lang == "fr":
        abbrev_list = ("M", "Mme","Dr")
    else:
        abbrev_list = () # Fallback if lang is not en or fr

    # main processing for loop
    for p_block in (input_tree.findall(".//p")):
        w_blocks = p_block.findall(".//w")
        if w_blocks != []:
            prev_tok = "__"
            # iterate over all but the last w block, which will be marked EOS
            for wnum, w_block in enumerate(w_blocks[:-1]):
        
                # get the next block
                next_block = w_blocks[wnum+1]
                # deal with cases where current token is in the list of EOS characters and the prev token is not an abbreviation 
                if w_block.text in EOS_list and prev_tok not in abbrev_list:
                
                    # if current_token tok is in EOS list and prev not in abbrevlist and next in rights: example ==    foo ! ” : next_tok is EOStagged
                    if next_block.text in right_els:
                        next_block.set("EOS", "True")
                        prev_tok = w_block.text
                        if mode == "dev":
                            next_block.set("EOS_reason", "rights")    
                            prev_tok = w_block.text
                    # if tok is in EOS list but next not in rights
                    else :
                        # deal with 1.0 cases : if we have . see if prev is int
                        # if the prev isn't in the exclusion list, set T
                        ## previous token is in neither excl_list nor abbrev_list 
                        ## example == foo Bar :: Bar == foo gets EOS tag as new sent starts with capital.
                        ##TODO: this if is far too long
                        if prev_tok not in excl_list and prev_tok not in abbrev_list and next_block.text not in punct_list and next_block.text not in excl_list and next_block.text[0].islower() is False:
                            w_block.set("EOS", "True")
                            prev_tok = w_block.text
                            if mode == "dev":
                                w_block.set("EOS_reason", "notExc")    
                # when no conditions met:
                prev_tok = w_block.text
            
            # always set last in para to to EOS : useful unless <page> els present
            last_block = w_blocks[len(w_blocks)-1]
            if pagination_type == "1":
                last_block.set("EOS", "True")
            if pagination_type != "1" and w_block.text in EOS_list:
                last_block.set("EOS", "True")

            # if dev mode, add reason why final block is marked EOS
            if mode == "dev":
                last_block.set("EOS_reason", "always")    
                
    return input_tree

def split_on_EOS(
    tree: etree.ElementTree, 
    offset: int, 
    file_uuid: str
) -> Tuple[etree.ElementTree, int]:
    """Split a list of w elements in a p block into s blocks with w child blocks.

    Args:
        tree (etree.ElementTree): An etree ElementTree with p blocks and w 
            blocks with EOS annotations.
        offset (int): Offset at which to start numbering sentences in the 
            input_file.
        file_uuid (str): A unique identifier used to prefix the s_id.

    Returns:
        Tuple[etree.ElementTree, int]: A tuple containing the modified tree 
            and the updated offset.

    Note:
        split_on_eos throws UnboundError on this_sentnum if it gets passed 
        untokenised texts (i.e., if no <s> tags are found)!
    """
    # get p elements, then w elements from the input tree
    para_els = [p for p in tree.iter("p")]
    for para_el in para_els:
        w_els = list(para_el.iter("w"))
        
        # Create an <s> element to hold <w> elements, and insert it in the para_el
        current_s = etree.Element("s")
        para_el.insert(0, current_s)    
        
        # loop over the w elements appending them to the current s element. 
        # If this <w> element has EOS="True", finalize the current <s> 
        # and start a new one
        for w in w_els:
            current_s.append(w)    
            if w.get("EOS") == "True":
                # create new s element inside para_el
                current_s = etree.Element("s")    
                para_el.append(current_s)    
    
    # find and remove sentences with no tokens
    duds = [sent for sent in tree.iter("s") if len(sent.findall(".//w")) == 0]
    _ = [dud.getparent().remove(dud) for dud in duds]
    
    # add sequential s_id attribute-value pairs to each s element
    for s, sent_element in enumerate(tree.iter("s")):
        this_sentnum = int(offset) + int(s) + 1
        zfilled_sentsnum = str(this_sentnum).zfill(4)
        s_id = f'{file_uuid}_{zfilled_sentsnum}'
        sent_element.set("s_id", s_id)

    offset = this_sentnum
    return tree, offset

def xml_to_conllu(mod_tree: etree.ElementTree, xml_filename: str) -> None:
    """Make a conll file from an xml file.

    Args:
        mod_tree (etree.ElementTree): An etree ElementTree containing the 
            modified XML structure with <s> tags.
        xml_filename (str): The absolute path to the XML file to be 
            converted to CONLLU format.

    Returns:
        None: The function writes the resulting CONLLU strings directly 
            to a file and does not return an object.
    """
    
    # make output filename from input filename, and ensure output directory exists
    output_file = Path(str(xml_filename).replace('.xml', '.conll'))

    # make a list of sentences over which to iterate then make the conll strings
    sents = [sent for sent in mod_tree.iter("s")]
    
    # Note: conllise_sentence must be defined in the scope of this script
    conll_store = [conllise_sentence(sent) for sent in sents]
    
    # dump the conll strings to file
    with open(output_file, 'w', encoding='UTF-8') as c:
        for chunk in conll_store:
            _ = c.write(chunk)

def conllise_sentence(sent: etree._Element) -> str:
    """Convert a sentence to a conll string.

    Args:
        sent (etree._Element): An etree <s> element with a w child for 
            each token.

    Returns:
        str: A conll string of the sentence and its metadata.
    """
    tail = "\t_\t_\t_\t_\t_\t_\t_"
    storage_list = []
    
    # Create the metadata header for the sentence
    meta_line = f'\n\n# sent_id = {sent.get("s_id")}\n'
    storage_list.append(meta_line)
    
    # Iterate through w elements to build token lines
    for tnum, w_el in enumerate(sent.iter("w"), start=1):
        w_id = f'w_{str(w_el.get("id"))}'
        tok = str(w_el.text)
        # Construct the line: index \t token \t features \t word_id
        tok_line = f'{str(tnum)}\t{str(tok)}{tail}\t{w_id}\n'
        storage_list.append(tok_line)
    
    sent_as_conll = "".join([chunk for chunk in storage_list])    

    return sent_as_conll

def safe_process_one_file(file_path: str, **kwargs: Any) -> Tuple[bool, Optional[str]]:
    """Safely execute process_one_file and catch any exceptions.

    Args:
        file_path (str): The path to the file to be processed.
        **kwargs (Any): Arbitrary keyword arguments to be passed to 
            process_one_file.

    Returns:
        Tuple[bool, Optional[str]]: A tuple where the first element is a 
            boolean indicating success (True) or failure (False), and the 
            second element is an error message string if processing failed, 
            otherwise None.
    """
    try:
        process_one_file(file_path, **kwargs)
        return True, None
    except Exception as e:
        return False, f"{file_path}: {e}"
      

def process_one_file(input_file: str, output_head_dir: Path, mode: str, lang: str, offset: int = 0) -> None:
    """Process a single XML file to create a sentencised XML and a CONLLU file.

    This function handles directory creation, marks EOS, splits sentences based 
    on EOS, writes the modified XML, and finally generates a CONLLU output.

    Args:
        input_file (str): The absolute path to the input XML file.
        output_head_dir (Path): A Path object representing the base directory 
            where outputs should be stored.
        mode (str): The processing mode (e.g., 'train', 'dev').
        lang (str): The language code.
        offset (int): The starting number for sentence IDs. Defaults to 0.

    Returns:
        None: The function writes files to disk and does not return a value.
    """

    ## deal with dirs and filenames
    current_output_dir = output_head_dir / Path(input_file).parent.name
    current_output_dir.mkdir(parents=True, exist_ok=True)
    output_basename = Path(input_file).name.replace('.xml', 'sentencised.xml')
    xml_filename = current_output_dir / output_basename

    # Parse the input XML
    input_tree = etree.parse(input_file)
    file_uuid = str(uuid.uuid4())

    
    # mark EOS tokens and split
    mod_tree = mark_EOS(input_tree, mode, 1, lang)
    mod_tree, offset = split_on_EOS(mod_tree, offset, file_uuid )
    
    # Write the modified XML and conll outputs
    mod_tree.write(xml_filename, encoding='UTF-8', pretty_print=True)  
    xml_to_conllu(mod_tree, xml_filename)  
    

def run_main(
    source_dir: str, 
    output_dir: str, 
    lang: str, 
    offset: int, 
    mode: str, 
    n_procs: int, 
    chunksize: int
) -> None:
    """Orchestrate the parallel processing of XML files to generate CONLLU updated XML versions.

    This function identifies all XML files in a nested directory structure, 
    sets up a process pool, and distributes the processing task across 
    multiple CPU cores while providing a progress bar.

    Args:
        source_dir (str): The directory path containing the source XML files.
        output_dir (str): The base directory path where processed files will be saved.
        lang (str): The language code for processing.
        offset (int): The starting number for sentence IDs.
        mode (str): The processing mode (e.g., 'train', 'dev').
        n_procs (int): The maximum number of processes to use.
        chunksize (int): The number of tasks to send to each worker in the pool.

    Returns:
        None: The function prints progress and errors to the console while exporting files to the specified output directory.
    """
    # Collect all XML files in subdirectories
    input_files = sorted([str(p) for p in Path(source_dir).glob("*/*.xml")])

    # Prepare output directory
    output_head_dir = Path(output_dir)
    output_head_dir.mkdir(parents=True, exist_ok=True)
    
    # Bind constant arguments to the worker function using partial
    safe_worker_function = partial(
        safe_process_one_file, 
        output_head_dir=output_head_dir, 
        mode=mode, 
        lang=lang, 
        offset=offset
    )

    # Determine a safe size for the processor pool
    actual_procs = min(n_procs, len(input_files), os.cpu_count() or 1)
    
    with ProcessPoolExecutor(max_workers=actual_procs) as ex:
        # Map the processing function to the list of input files
        results = ex.map(safe_worker_function, input_files, chunksize=chunksize)
        
        # Wrap the results in tqdm for a visual progress bar
        for success, err in tqdm(results, total=len(input_files)):
            if not success:
                tqdm.write(f"failed: {err}")


if __name__ == "__main__":
    # Initialize the argument parser
    parser = argparse.ArgumentParser(
        description="Sentencise xml files in folders",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Required arguments: paths:
    parser.add_argument(
        "--source_dir", 
        type=Path, 
        required=True, 
        help="Directory containing nested folders with XML files"
    )
    parser.add_argument(
        "--output_dir", 
        type=Path, 
        required=True, 
        help="Folder where XML output will be written (mirrors source structure)"
    )
    # processing parameters
    parser.add_argument(
        "--lang", 
        type=str, 
        required=True, 
        help="Use sentencising rules for this language (e.g., 'en', 'fr')"
    )
    parser.add_argument(
        "--offset", 
        type=int, 
        required=False, 
        default=0,
        help="Start numbering sentences at this number"
    )
    parser.add_argument(
        "--mode", 
        type=str, 
        required=False,
        default="prod",
        choices=["prod", "dev"], # Restricts input to only these two options
        help="Set mode (dev will add XML attributes with EOS rule followed)"
    )
    ## performance 
    parser.add_argument(
        "--n_procs", 
        type=int, 
        required=False,
        default=4,
        metavar="N",
        help="Numebr of workers to request"
    )
    ## chunksize
    parser.add_argument(
        "--chunksize", 
        type=int, 
        required=False,
        default=64,
        metavar="N",
        help="Number of paths per chunk for each worker"
    )
    args = parser.parse_args()

    # Validation: Check if source exists before starting
    if not args.source_dir.exists():
        parser.error(f"The source directory '{args.source_dir}' does not exist.")
    
    run_main(
      args.source_dir, 
      args.output_dir, 
      args.lang, 
      args.offset, 
      args.mode, 
      args.n_procs, 
      args.chunksize
      )
