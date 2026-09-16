## sentenciser consolidation
# step1 : last item in p is EOS
# general rule : if in EOS_list, == mark
## TODO: multithread this, each thread can use a letter prepended to its own count
import re
import glob
import os
import argparse

from pathlib import Path
from lxml import etree
from tqdm import tqdm

def mark_EOS(input_tree, mode, pagination_type, lang):
    '''
    Inputs:
        input_tree : etree Element : an etree to process
        mode : str : string to control whether to run in dev/verbose mode or prod        
            usage : specify to run in dev or prod mode. When dev mode is selected, additional annotations are added to add reason for specific EOS value was attributed.
        pagination_type : int : indicates the type of pagination. 
            usage : 
                1 : use 1 if final element of a paragraph is necessarily and end of sentence
                0 : use 0 if final element of para is not necessarily an EOS. This is useful when page tags are present or when sents run over paragraphs.
        
        lang : str : 2 char code of language being processed
    '''
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

    # mode = "dev"
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

def split_on_EOS(tree, offset):
    '''
    Split a list of w elements in a p block into s blocks with w child blocks
    
    Inputs:
        tree : ElementTree : an etree ElementTree with p blocks and w blocks with EOS annotations
        offset : int : offset at which to start numnbering sentences in the input_file
    NOTE : ## split_onEOS throws UNBOUNDerror on this_sentnum if it gets passed untokenised texts!  
    '''
    
    # get p elements, then w elements from the input tree
    para_els = [p for p in tree.iter("p")]
    for para_el in para_els:
        w_els = list(para_el.iter("w"))
        
        # Create an <s> element to hold <w> elements, and insert it in the para_el
        current_s = etree.Element("s")
        para_el.insert(0, current_s)    
        
        # loop over the w elements appending them to the current s element. If this <w> element has EOS="true", finalize the current <s> and start a new one
        for w in w_els:
            current_s.append(w)    
            if w.get("EOS") == "True":
                # create new s element inside para_el
                current_s = etree.Element("s")    
                para_el.append(current_s)    
    
    # find and remove sentences with no tokens
    duds = [sent for sent in tree.iter("s") if len(sent.findall(".//w")) ==0]
    _ = [dud.getparent().remove(dud) for dud in duds]
    
    # add sequential s_id attribute-value pairs to each s element
    for s, sent_element in enumerate(tree.iter("s")):
        this_sentnum = offset + s +1
        sent_element.set("s_id", str(this_sentnum).zfill(6))

    offset = this_sentnum
    return tree, offset

def xml_to_conllu(mod_tree, xml_filename):
    '''
    Make a conll file from an xml file
    Inputs:
      mod_tree : ElementTree : an etree Element tree
      input_file : str : absolute path to an xml file to be converted to conll
    Returns:
      no return object. The function write a file of conll strings
    '''
  
    # make output filename from input filename, and ensure output directory exists
    output_file = Path(str(xml_filename).replace('.xml','.conll'))

    # make a list of sentences over which to iterate then make the conll strings
    sents = [sent for sent in mod_tree.iter("s")]
    conll_store = [conllise_sentence(sent) for sent in sents]
    # dump the conll strings to file
    with open(output_file, 'w', encoding='UTF-8') as c:
        for chunk in conll_store:
            _ = c.write(chunk)

def conllise_sentence(sent):
    '''
    Convert a sentence to a conll string
    Input:
      sent : etree <s> element : an etree <s> element with a w child for each token
    Return :
      sent_as_conll : str : a conll string of the sentence and its metadata
    '''
    tail = "\t_\t_\t_\t_\t_\t_\t_"
    storage_list = []
    meta_line = f'\n\n# sent_id = {sent.get("s_id")}\n'
    storage_list.append(meta_line)
    for tnum, w_el in enumerate(sent.iter("w"), start=1):
        w_id = f'w_{str(w_el.get("id"))}'
        tok = str(w_el.text)
        tok_line = f'{str(tnum)}\t{str(tok)}{tail}\t{w_id}\n'
        storage_list.append(tok_line)
    
    sent_as_conll = "".join([chunk for chunk in storage_list])    

    return sent_as_conll

def run_main(source_dir, output_dir, lang, offset, mode): 

    input_files = sorted([str(p) for p in Path(source_dir).glob("*/*.xml")])

    output_head_dir = Path(output_dir)
    output_head_dir.mkdir(exist_ok=True)
    
    for input_file in tqdm(input_files):  
    
        current_output_dir = output_head_dir / Path(Path(input_file).parent).name
        current_output_dir.mkdir(exist_ok=True)
        output_basename = os.path.basename(input_file).replace('.xml','sentencised.xml')
        xml_filename = Path(current_output_dir / output_basename)

        input_tree  = etree.parse(input_file)
    
        mod_tree = mark_EOS(input_tree, mode, 1, lang)
        mod_tree, offset = split_on_EOS(mod_tree, offset)
        mod_tree.write(xml_filename, encoding='UTF-8', pretty_print=True)  
      
        xml_to_conllu(mod_tree, xml_filename)  
        offset = offset
      
  

if __name__ == "__main__":
    # Initialize the argument parser
    parser = argparse.ArgumentParser(
        description="Sentencise xml files in folders",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Required argument: source file path
    parser.add_argument(
        "--source_dir", 
        type=str, 
        required=True, 
        help="Directory containing nested folders which contain the XML files to process"
    )
    # Required argument: output dir
    parser.add_argument(
        "--output_dir", 
        type=str, 
        required=True, 
        help="The folder where XML output will be written in a structure mirroring that of the source directory, including subfolders"
    )
    # Required argument: output dir
    parser.add_argument(
        "--lang", 
        type=str, 
        required=True, 
        help="Use sentencising rules for which language : Mr. X is not EOS in English, ni « M. X » en français"
    )
    # Required argument: output dir
    parser.add_argument(
        "--offset", 
        type=int, 
        required=False, 
        help="Start numbering sentences at this number"
    )
    # Required argument: output dir
    parser.add_argument(
        "--mode", 
        type=str, 
        required=False,
        default="prod",
        help="Set mode to dev to XML attrib with rules followed in calculating EOS position"
    )
    args = parser.parse_args()
    source_dir = args.source_dir
    output_dir = args.output_dir
    lang = args.lang
    offset = args.offset
    mode = args.mode

    run_main(source_dir, output_dir, lang, offset, mode) 

