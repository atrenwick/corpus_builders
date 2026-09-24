
import glob
import os
import argparse
import re
import logging
from lxml import etree
from tqdm import tqdm
from stanza.utils.conll import CoNLL
from multiprocessing import Pool, cpu_count
from functools import partial

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

def start_article(art_metas, input_file):
  '''
  Make an etree Tree of a prescribed form for a specific parser, add metadata to the header
  Inputs:
  	art_metas : list : a list of metadata for each article
  	input_file : string : absolute path to a parsed conll file
  Returns:
  	current_article : etree : an etree element tree with the structure and metadata for the article
  '''
  # the raw string to be parsed as an etree
  raw_str_header= '''
    
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
  ##  parse the raw string as an etree tree and add the metadata
  article_mould = etree.fromstring(raw_str_header)
  article_mould.findall('.//title')[0].text = art_metas[2].replace("# title=","")
  article_mould.findall(".//author")[0].text =art_metas[3].replace("# author=","")
  article_mould.findall(".//publisher")[0].text =art_metas[6].replace("# publi=","")
  article_mould.findall(".//date")[0].text =os.path.basename(input_file).replace('_out.conllu','')[-4:]
  
  source_desc_el = article_mould.findall(".//sourceDesc")[0]
  crawl_dt_el = etree.SubElement(source_desc_el, 'p')
  crawl_dt_el.text =art_metas[8].replace("# crawl_date=","") 
  crawl_url_el = etree.SubElement(source_desc_el, 'p')
  crawl_url_el.text =art_metas[7].replace("# warc_path=","") 
  current_article = article_mould
  return current_article



def make_s_blockopener(sent_metas):
  '''
  parse conll meta lines to get the IDs for the s block opening tag and its attributes
  Inputs : 
  	sent_metas : list : a list of metadata for the sentence
  Returns :
  	s_string_open : str: a customised string to open an s block with the attribute-value pairs for id and uuid; able to be parsed into a valid etree element
  '''
  sent_serial = sent_metas[0].replace("# sent_id = ",'')
  sent_UUID = sent_metas[1].replace('# sent_ID = ','')
  s_string_open = f'\n<s id="{sent_serial}" uuid="{sent_UUID}">'
  return s_string_open

def make_art_metablock(art_metas):
  '''
  extract remaining metadata from conll metalines and send these to placeholder xml element for each article
  Inputs :
  	art_metas : list : a list of article-level metadata
  Returns :
    article_block : string : a raw string declaring an xml element with attribute-value pairs for article-level metadata ; able to be parsed into a valid etree element
  '''
  
  article_num = art_metas[0].replace("# Article_num = ","")
  article_url = art_metas[1].replace("# url=","")
  article_title = art_metas[2].replace("# title=","")
  article_author = art_metas[3].replace("# author=","")
  article_site = art_metas[4].replace("# site=","")
  article_resp_url =art_metas[5].replace("# resp_url=","")
  article_publi= art_metas[6].replace("# publi=","")
  article_crawllink= art_metas[7].replace("# warc_path=","")
  article_crawl_dt =art_metas[8].replace("# crawl_date=","")
  article_yyyy = os.path.basename(input_file).replace('_out.conllu','')[-4:]
  article_mm = art_metas[9].replace("# month=","")
  article_dd = art_metas[10].replace("# day=","")
  article_block = f'\n<article num="{article_num}" url="{article_url}" title="{article_title}" author="{article_author}" site="{article_site}" resp_url="{article_resp_url}" publi="{article_publi}" crawllink="{article_crawllink}" crawl_dt="{article_crawl_dt}" yyyy="{article_yyyy}" mm="{article_mm}" dd="{article_dd}">\n'
  
  return article_block

def consolidate_xmls(lang, year, publi):
  '''
  Consolidate XML files for a publication in a year to a single file
  Inputs :
	year : str: year for which files are to be processed
	lang : str : language code for the language to be processed
	publi : str : pattern used to restrict filename matches to those of the desired publication with regex
  '''

  input_files = glob.glob(f'/Volumes/HC3Beta/uncompressed_parquet/cc_{lang}/{year}/4_xml/*{publi}*.xml')
  print(f"Consolidating {len(input_files)}")
  outputfilename = f'{os.path.dirname(input_files[0])}/{year}_{publi}_{lang}.xml'
  new_tree = etree.Element("teiCorpus")
  
  for input_file in tqdm(input_files):
    input_tree = etree.parse(input_file)
    articles = input_tree.findall(".//TEI.2")
    for art in articles:
      new_tree.append(art)
  
  for snum, sentblock in enumerate(new_tree.findall(".//s"), start=1):
    sentblock.set("id", str(snum))
  
  tree_out = etree.ElementTree(new_tree)  
  tree_out.write(outputfilename, encoding='UTF-8', pretty_print=True, xml_declaration=True)
  print(f"{len(input_files)} consolidated into 1 file : {os.path.basename(outputfilename)}")




def process_file(input_file, year, lang, logger):
  '''
  The function processing a single file, from which a partial function for the pool can be created.
  Inputs:
  	input_file (str) : absolute path to the conll file taken as input
  	year : string : year for which files are to be processed
  	lang : string : language to be processed
    logger : logger : a logger
  Returns:
    1: 1 is returned in the case of an error in order to trigger callback is triggered 
    If the function runs successfully, there is no return object, a file is written.
  
  '''
  
  try:
    logger.info(f"Processing: {input_file} ")

    ## TODO : remove the hardcoding of these paths ??
    folder1 = '3_conllu_out'
    folder2 = '4_xml'
    outputfile = input_file.replace('.conll','.xml').replace(folder1, folder2)
    
    # load the input file as a conll document
    input_doc = CoNLL.conll2doc(input_file)
    # reset counter to ensure first iteration will be 0
    art_num_prev = -1
    ## make a tree in which to append the tree for article, 
    outputtree = etree.fromstring("<teiCorpus></teiCorpus>")
    current_article, articles_processed = [],[]


    # iterate over sents, get the first comment which contains the article number
    for s, sent in (enumerate(input_doc.sentences)):
      art_num = sent.comments[0]
      # add article metas if start of new article
      if art_num_prev != art_num :
        if s>0:
          articles_processed.append(current_article)
        ## get the article metadata for the current sentence and make an etree for this article
        art_metas = [sent.comments[i] for i in [0,3,4,5,6,7,8,9,10,11,12]]
        current_article = start_article(art_metas, input_file)
      # always run this chunk which adds the sent level metadata and token level data
      sent_metas = [sent.comments[i] for i in [14,1]]
      parent = current_article.findall(".//body")[0]
      current_sent_el = etree.SubElement(parent, 's')
      ## get the conll strings for each token, and concatenate them into a single string, then tidy this
      intermed_text =  "\n" +"\n".join([re.sub("’", "'", token.to_conll_text()) for token in sent.tokens]) + '\n'
      current_sent_el.text = intermed_text.replace('”','"').replace('“','"')
      current_sent_el.set('uuid', sent_metas[1].replace('# sent_ID = ',''))
      art_num_prev = art_num
    # add final article to processed_list as there's no subsequent sentence to call the append
    articles_processed.append(current_article)

  
    # when all the articles have been processed, append them to the output tree
    for item in articles_processed:
      outputtree.append(item)

  
    # tidy the output tree by inserting the date and language
    for el in outputtree.findall(".//date"):
      el.text = year
    for el in outputtree.findall(".//language"):
      el.set("ident", str(lang))
    # tidy sent_ids by removing the UUIDs and renumbering from 1
    for snum, sblock in enumerate(outputtree.findall(".//s"), start=1):
      sblock.set("id", str(snum))
      _ = sblock.attrib.pop("uuid")
    
    # ensure that s elements have a parent p element, and that p elements have a parent <body> element to ensure tree conforms to expected structure
    body_els = outputtree.findall(".//body")
    for body_el in body_els:
      s_blocks = body_el.findall(".//s")
      p_block = etree.SubElement(body_el, 'p')
      for s_block in s_blocks:
        body_el.remove(s_block)
        p_block.append(s_block)
    
    # tidy the custom source_desc xml element by adding date time, month, day and url elements 
    source_descEls = outputtree.findall(".//sourceDesc")
    for current_el in source_descEls:
      subels = current_el.findall(".//*")
      current_el.set("datetime", f'{subels[1].text}')
      current_el.set("month", f'{subels[1].text[5:7]}')
      current_el.set("day", f'{subels[1].text[8:10]}')
      current_el.set("ccrawl_url", f'{subels[2].text}')
      for el in subels:
        current_el.remove(el)
  
    final_tree = etree.ElementTree(outputtree)
    final_tree.write(outputfile, encoding='UTF-8', pretty_print=True, xml_declaration=True)

  except Exception as e:
    logger.error(f"❌ Error processing {input_file}: {e}", exc_info=True)
    return 1  # Always return something so callback triggers
  

def generate_file_list(year, lang, mode, publi):
    """
    Generate the list of files to process based on year and path and pattern.
	Inputs:
		Year : str: year for which files are to be processed
		lang : str : language code for the language to be processed
		mode : char. One of three options describing the mode in which to generate files. `A` for All will match all files with the .conll extension. `E` for EVEN will match only those containing an even number before the conll extension.. `O` for ODD will match only those containing an odd number before the conll extension.
		publi: char : file pattern to select files to process
	Returns :
		file_list : list : a list of absolute paths to files to process
    """
    ## hardcoded subfolder names for robustness
    folder1 = '3_conllu_out'
    folder2 = '4_xml'

    input_folder = f'/Volumes/HC3Beta/uncompressed_parquet/cc_{lang}/{year}/3_conllu_out'
    if mode =="A":
      # files = sorted(glob.glob(input_folder + '*/*_.conllu'))
      files = sorted(glob.glob(input_folder + f'/{publi}*.conll'))
    if mode =="E":
      # files = sorted(glob.glob(input_folder + '*[02468]/*_out.conllu'))
      files = sorted(glob.glob(input_folder + f'/{publi}*[02468]*.conll'))
    if mode =="O":
      # files = sorted(glob.glob(input_folder + '*[13579]/*_out.conllu'))
      files = sorted(glob.glob(input_folder + f'/{publi}*[13579]*.conll'))
    file_list = files
    return file_list

def define_poolsize(nproc, file_list):
    '''
    Define poolsize to use by running 2 sanity/safety checks
    The first check is that the number of processors is not greater than the number of CPU cores available
    The second check is that the number of files to process is lower then the number of processors. As files are not split between processors, this avoids creating processors that won't be called.
    Inputs: 
    	nproc : int/string : number of procesors in pool specified as command line argument
    	file_list : list of files to be processed
    Returns:
    	pool_size : int : an integer defining the number of processors in the pool
    '''
    
    pool_size = min(nproc, cpu_count())  
    if pool_size >= len(file_list):
      pool_size = len(file_list)
      print(f"Using pool size == file size == {pool_size}")
    else:
      print(f"Using pool size: {pool_size}")
    return pool_size

def run_processing(year, mode, lang, nproc, log_path, publi):
    """
    Convert conll files to XML with a pool of parallel processes
    Inputs:
		year : str: year for which files are to be processed
		mode : char. One of three options describing the mode in which to generate files. `A` for All will match all files with the .conll extension. `E` for EVEN will match only those containing an even number before the conll extension.. `O` for ODD will match only those containing an odd number before the conll extension.
		lang : str : language code for the language to be processed
    	nproc : int : number of processors in the pool
    	log_path : absolute path to which to write the log
		publi: char : file pattern to select files to process
    Returns:
    	results : list : a list of results from the pool processors
    """
    logger = setup_logger(log_path)

    # generate list of files
    file_list = generate_file_list(year, lang, mode, publi)
    logger.info(f"Found {len(file_list)} files to process.")

    # create the pool with sanity checks
    pool_size = define_poolsize(nproc, file_list)

    ## make worker 
    worker_func = partial(process_file,  year=year, lang=lang, logger=logger)

    # map the work to the pool
    with Pool(pool_size) as pool, tqdm(total=len(file_list), desc="Processing", unit="file") as pbar:
        results = []
        for file_path in file_list:
            # Submit tasks asynchronously
            r = pool.apply_async(worker_func, (file_path,), callback=lambda _: pbar.update(1))
            results.append(r)

        # Wait for all tasks to complete
        for r in results:
            r.wait()
    logger.info("✅ All processing complete.")
    print("Processing complete.")

    return results
    
#################################################################################################
############################       actual processing starts here       ##########################
#################################################################################################




if __name__ == "__main__":

    parser = argparse.ArgumentParser(
    	prog='conll_out_to_article_xml',
    	formatter_class=argparse.RawTextHelpFormatter,
    	description='''\
    Read conll files and send send to XML
    
    Examples of usage:
    ## use 4 processors in a pool to find all files from 2020 with smh in the filename located in the English subfolder, convert them to XML, and then consolidate these into 1 output XMLfile
    send_to_xml.py -year 2020 -mode A -lang en --nproc 4 -consolidate True -publi smh

    ## use 3 processors in a pool to find all files from 2017 with monde in the filename AND an even number, located in the French subfolder, convert them to XML, without consolidating
    send_to_xml.py -year 2017 -mode E -lang fr --nproc 5 -publi monde
    
    '''
    )
    
    ### parser - reading arguments
    parser.add_argument('-year',help='''Year in cc_corpus/ folder''',default="")
    parser.add_argument('-mode',help='''E for Even, O for Odd, A for all''',default="A")
    parser.add_argument("--nproc", type=int, default=4, help="Number of parallel processes")
    parser.add_argument('-lang',help='''lang''',default="")
    parser.add_argument("--log", type=str, default="/Users/Adam/Desktop/processing2.log", help="Path to log file")
    parser.add_argument('-consolidate',type=bool,default=False,help='''When done, consolidate to single XML file''')
    parser.add_argument('-publi',type=str,default="",help='''file pattern to process''')
    args = parser.parse_args()
    year=args.year
    mode=args.mode
    lang = args.lang
    nproc = args.nproc
    consolidate = args.consolidate
    publi = args.publi
    run_processing(year, mode, lang, nproc, args.log, publi)
    if consolidate ==True:
        consolidate_xmls(lang, year, publi)
	

