import argparse
import glob
import os
import re

from typing import Optional, Any, Tuple
from pathlib import Path
from lxml import etree
from tqdm import tqdm
from stanza.utils.conll import CoNLL

from functools import partial
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Pool


def make_file_names(tagged_file, xml_dirname, xml_output_dir):
  
  tagged_file_path = Path(tagged_file)
  file_basename = tagged_file_path.name.replace(tagged_file_path.suffix, '').replace('_OUT','')
  conll_dirname = Path(tagged_file).parent.parent.name
  
  ## xml input files::
  xml_dir_path = re.sub(str(conll_dirname), str(xml_dirname), str(tagged_file_path.parent))
  xml_input_filepath = Path(xml_dir_path, f'{file_basename}.xml')
  xml_subdir = xml_input_filepath.parent.name

  ## xml output dir: define full path
  xml_output_dir_fullpath = Path(re.sub(str(conll_dirname), str(xml_output_dir), str(tagged_file_path.parent)))
  xml_output_dir_fullpath.parent.mkdir(exist_ok=True)
  xml_output_dir_fullpath.mkdir(exist_ok=True)
  xml_output_filepath = Path(xml_output_dir_fullpath , f'{file_basename}_full.xml')
  
  return xml_input_filepath, xml_output_filepath
  
  

def prepare_xml_tree(xml_input_filepath, id_attrib):
  
  input_tree = etree.parse(xml_input_filepath)
  target_dict = {el.get(f"{id_attrib}"):el for el in input_tree.findall(".//s")}
  # check dict:
  if len(target_dict.keys()) ==1:
    print("Trying alternative attribs to get valid_dict")
    if id_attrib =="s_id":
      target_dict = {el.get(f"{id_attrib.replace('s_','')}"):el for el in input_tree.findall(".//s")}
    if id_attrib =="id":
      target_dict = {el.get(f"s_{id_attrib}"):el for el in input_tree.findall(".//s")}
  return input_tree, target_dict

def add_parse_to_tree(input_tree, target_dict, tagged_file):
  
  conll_doc = CoNLL.conll2doc(tagged_file)
  for sent in (conll_doc.sentences):
    sent_id = sent.comments[0].replace('# sent_id = ','')
    target_el = target_dict[sent_id]
    droplist = target_el.findall(".//w")
    for item in droplist:
      item.getparent().remove(item)
    conll_chunk = "\n".join([token.to_conll_text() for token in sent.tokens])
    target_el.text = conll_chunk  

def process_one_file(tagged_file, xml_dirname, xml_output, id_attrib):
    xml_input_filepath, xml_output_filepath = make_file_names(tagged_file, xml_dirname, xml_output) ## from argprser
    input_tree, target_dict = prepare_xml_tree(xml_input_filepath, id_attrib)
    add_parse_to_tree(input_tree, target_dict, tagged_file)
    input_tree.write(xml_output_filepath, encoding='UTF-8', pretty_print=True)

def safely_process_one_file(file_path: str, **kwargs: Any) -> Tuple[bool, Optional[str]]:
    """Safely process one file and catch any exceptions.

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


def make_tagged_file_lists(conll_source: str, sibling:bool):
    if sibling:
        source_path = Path(conll_source)
        folder_list = sorted([
            str(p) for p in source_path.parent.iterdir() if p.is_dir() 
        ])
        
        tagged_files = [
            Path(folder, file)
            for folder in folder_list
            for file in os.listdir(folder)
            if file.endswith(".conll")
        ]
    else: 
        tagged_files = sorted([str(p) for p in Path(conll_source).glob("*.conll")])
    
    return tagged_files



def main(
    conll_source: Path,
    xml_dirname: str,
    xml_output: Path,
    id_attrib: str,
    n_procs: int,
    sibling: bool
    ):


    tagged_files = make_tagged_file_lists(conll_source, sibling)
    file_count = len(tagged_files)
    print(f'{file_count} files found')
    if not tagged_files:
        print(f"No files with extension conll found in {conll_source}")
        return
    
    
    

    ## define worker function with 3 frozen args
    safe_worker_function = partial(
        safely_process_one_file, 
        xml_dirname = xml_dirname,
        xml_output=xml_output, 
        id_attrib=id_attrib
    )

    # Determine a safe size for the processor pool
    actual_procs = min(n_procs, file_count, os.cpu_count() or 1)

    with ProcessPoolExecutor(max_workers=actual_procs) as ex:
        # Map the processing function to the list of input files
        results = ex.map(safe_worker_function, tagged_files)


        # Wrap the results in tqdm for a visual progress bar
        for success, err in tqdm(results, total=len(tagged_files)):
            if not success:
                tqdm.write(f"failed: {err}")
    print("Done !")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insert annotations into source XML file")
    parser.add_argument(
        "--conll_source",help="Path to dir with tagged CoNLL files"
    )
    parser.add_argument(
        "--xml_dirname",help="Name (not path) of dir with xml files as input"
    )
    parser.add_argument(
        "--xml_output",help="Path to dir where xml trees will be exported"
    )
    parser.add_argument(
        "--id_attrib",help="attribute of s elements used as id : s, s_id…"
    )
    parser.add_argument(
        "--n_procs",help="How many worker processes to request", required=False, default=2, type=int,metavar="N"
    )
    parser.add_argument(
        "--sibling",help="Run in sibling mode : specify a fodler of conll files and run the process for all its siblings ", required=False, default=False, action="store_true"
    )


    args = parser.parse_args()
    main(
        Path(args.conll_source),
        Path(args.xml_dirname),
        Path(args.xml_output),    
        str(args.id_attrib),
        int(args.n_procs),
        args.sibling
        )
    
