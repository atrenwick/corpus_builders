# Standard library
import argparse
import glob
import hashlib
import json
import math
import os
import re
import time
from functools import partial
from multiprocessing import Pool, cpu_count

# Third-party
from spacy.pipeline import Sentencizer
import numpy as np
from tqdm import tqdm
import polars as pl


def filter_parquet(this_file, filter_type, filter_value):
  '''
  Trim a polars dataframe to only the rows where the `filter_value` matches in the `filter_type` column or the `requested_url` column contains `this_domain` to restrict data to a specific website.
  Inputs:
    this_file (str): absolute reference to a parquet file to parse with Polars
    filter_type (str) : `lang` to filter on language, `domain` to filter on domain
    filter_value (str) : a language code if filtering on the language column, or a domain + top level extension if filtering on a website
  Return:
    trimmed (df) : a Polars df collected from only the rows matching the filter
  '''
  df = pl.scan_parquet(this_file)  

  filter_map = { "lang": pl.col("language") == filter_value,
        "domain": pl.col("requested_url").str.contains(rf'{filter_value}', literal=False) }

  if filter_type not in filter_map:
      raise ValueError(f"Unknown filter_type: {filter_type}")

  filtered_df = df.filter(filter_map[filter_type])
  
  trimmed = filtered_df.collect()
    
  return trimmed
  



def make_arrays(trimmed):
  '''
  Make arrays with metadata extracted from the df
  Inputs: 
    trimmed (df) : a Polars or Pandas dataframe
    my_arrays (list) : a list of arrays of metadata
  
  '''
  df = trimmed
  years_list, days_list, months_list = [],[],[]
  
  url_array = df['requested_url'].to_numpy()
  plain_tex_arr = df['plain_text'].to_numpy()
  pub_date_arr = df['published_date'].to_numpy()
  title_arr = df['title'].to_numpy()
  author_arr = df['author'].to_numpy()
  sitename_arr = df['sitename'].to_numpy()
  resp_url_arr  = df['responded_url'].to_numpy()
  publisher_arr  = df['publisher'].to_numpy()
  warc_path_arr = df['warc_path'].to_numpy()
  crawl_date_arr = df['crawl_date'].to_numpy()
  
  for date in pub_date_arr:
    this_year = date.split("-")[0]
    this_month = date.split("-")[1]
    this_day = date.split("-")[2]
    years_list.append(this_year)
    months_list.append(this_month)
    days_list.append(this_day)
    
  years_arr = np.array(years_list)
  months_arr = np.array(months_list)
  days_arr = np.array(days_list)
  my_arrays = [url_array, years_arr,  months_arr, days_arr, plain_tex_arr, pub_date_arr, title_arr, author_arr, sitename_arr, resp_url_arr, publisher_arr, warc_path_arr, crawl_date_arr]
  
  return my_arrays




def run_exporter_to_json_dict(my_arrays, this_file, mode, year, filter_type, filter_value):
  '''
  Export the arrays to a json file
  Inputs:
    my_arrays (list) : a list of arrays containing metadata created by `make_arrays`
    this_file (string) : absolute path to the parquet file being used
    mode (string) : indicate whether to process in strict mode or not. If processing in strict mode, using `S`, the year in the crawl_date metadata must match the year specified in the `year` argument. 
    year (string) : 4 character string to indicate year being processed
    filter_type (str) : `lang` to filter on language, `domain` to filter on domain
    filter_value (str) : a language code if filtering on the language column, or a domain + top level extension if filtering on a website
  Returns:
    no return object. A json file will be printed in the same location as the source parquet file

  '''
  # get the list of metadata arrays out of the my_arrays list
  url_array, years_arr,  months_arr, days_arr, plain_tex_arr, pub_date_arr, title_arr, author_arr, sitename_arr, resp_url_arr, publisher_arr, warc_path_arr, crawl_date_arr   =my_arrays
  
  # make the path to the folder to write to
  source_short = this_file.replace(".parquet","")
  if filter_type =="domain":  
    domain_tidy = re.sub(r'www_|_com','', filter_value.replace('.','_'))
    source_short = source_short.replace(f'{year}/',f'{year}/{domain_tidy}_')

  source_short = source_short.replace('0_raw_parquet','1_conllised_json')

  ## use the `mode` argument to filter to the year specified as an argument
  if mode =="S":
    target_years = set({year})
  else:
    target_years = sorted(set(years_arr))

  # for each target_year, make a dictionary : in this dictionary, the keys will be integers, and the values will be dictionaries build from the metadata arrays
  for target_year in target_years:
    tidy_dict = {}
    for i in range(url_array.size):
      year = years_arr[i]
      if year == target_year:
        values = {"url":url_array[i], "txt": plain_tex_arr[i], "title" : title_arr[i], "author": author_arr[i], "site" : sitename_arr[i], "resp_url" : resp_url_arr[i], "publi"  : publisher_arr[i], "warc_path" : warc_path_arr[i], "crawl_date" : crawl_date_arr[i], "month" : months_arr[i], "day" : days_arr[i]}
        tidy_dict[i] = values

    ## add the target_year to the path where the json will be written, then write to the file
    outputfile = f'{source_short}_{target_year}.json'
    with open(outputfile, 'w', encoding='UTF-8') as k:
      json.dump(tidy_dict, k)
    print(f'Printed file {outputfile}')


def get_json_from_parquet(filter_type, filter_value, number, mode, year, local_dir=None):
  '''
  TO DO : tweak the args to allow these_domains to be specified as a list in CLI
  
  Load, filter, extract and export articles from parquet files for a given year
  Inputs:
    filter_type (str) : `lang` to filter on language, `domain` to filter on domain
    filter_value (str) : a language code if filtering on the language column, or a domain + top level extension if filtering on a website
  	number (int) : number of items at which to stop processing
    mode (string) : indicate whether to process in strict mode or not. If processing in strict mode, using `S`, the year in the crawl_date metadata must match the year specified in the `year` argument. 
    year (str) : a year as 4 characters
    local_dir : str : default = None ; option to specify local dir in which to work
  Returns :
    No return object : a file will be printed or an error message will be printed to the console.
  
  '''
  if local_dir == None:
    these_files = glob.glob(f'/Volumes/HC3Beta/uncompressed_parquet/cc_corpus/{year}/*.parquet')
  else:
    these_files = glob.glob(f'{local_dir}/{year}/*.parquet')
  # get the list of files to process and restrict it if necessary, and confirm this  
  if number ==0:
    these_files = these_files
  else:
    these_files = these_files[:number]
  print(f'{len(these_files)} to process with domain filter')

  
  exportlog=[]#

  # loop to process files, printing export log errors to console if any  
  for this_file in tqdm(sorted(these_files)):
    year = os.path.basename(this_file)[:4]
    try:
      trimmed= filter_parquet(this_file, filter_type, filter_value)
      if len(trimmed) ==0:
        print(f"\nNo hits in {os.path.basename(this_file)}")
        
      if len(trimmed) > 0:
        my_arrays = make_arrays(trimmed)
        
        run_exporter_to_json_dict(my_arrays, this_file, mode, year, filter_type, filter_value)
    except Exception as e:
      report = this_file, e
      exportlog.append(report)
  if len(exportlog) >0:
    for item in exportlog:
      print(item)


def define_pipe(lang):
  '''
  Load the spacy nlp object for the specified language and add a sentencizer to the pipeline
  Inputs:
  	lang (str) : language code indicating the spacy language pipeline to load to get the language specific tokenizer
  Returns:
  	nlp (spacy pipeline object) : a spacy pipeline for the language specified with a tokenizer and sentencizer 
  
  '''
  if lang =="de":
    from spacy.lang.de import German
    nlp = German()
  if lang == "it":
    from spacy.lang.it import Italian
    nlp = Italian()
  if lang =="en":
    from spacy.lang.en import English
    nlp= English()
  if lang == "es":
    from spacy.lang.es import Spanish
    nlp = Spanish()
  
  if lang == "fr":
    from spacy.lang.fr import French
    nlp = French()
  if lang not in ['fr','de','en','it','es']:
    print(f"lang {lang} not supported ")
  
  sentencizer = Sentencizer()

  nlp.add_pipe("sentencizer")
  return nlp
  
def url_to_hex_id(url):
  '''
  create a 256 byte hash from a URL
  Input:
    url : string : a URL
  Return :
    hex_id : string : a 256 byte hash of the URL specified
  '''

  # Encode URL to bytes
  url_bytes = url.encode('utf-8')
    
  # Create a SHA-256 hash object, then update the hash object with  URL bytes
  sha256 = hashlib.sha256()
  sha256.update(url_bytes)
  
  # Get the hexadecimal representation of the hash
  hex_id = sha256.hexdigest()
  
  return hex_id

## to do?? add functionality to consolidate all to 1x file by adding offset ; offset can be added to k at line 70

def make_conll_strings_from_json_with_allmetas(input_file, nlp, method=None, tidy_dict=None):
  '''
  Make a list of conll strings for each input file
  Inputs:
  	input_file : str : absolute path to a json file
  	nlp : spacy nlp pipeline : nlp pipeline with tokenizer and sentencizer for the specified language
  Return:
  	file_output : list : a list of conll_strings, each article itself being a list of conll strings, which together constitute a valid conll document object
  '''

  # define a special string for the empty conll fields
  line_tail = "\t_\t_\t_\t_\t_\t_\t_\t_\n"
  
  # if method is not none, 
  if method is not None:
    json_input_parsed = tidy_dict
  else:
  ##  open, read and parse the json data into a python dictionary
    with open(input_file, 'r', encoding="UTF-8") as j:
      json_input = j.read()
    json_input_parsed = json.loads(json_input)


  # make a list to store the processed conll strings for each document, and make list of keys
  file_output = []
  key_list = list(json_input_parsed.keys())
  ## iterate over the list of keys getting the text from the dictionary, and apply some text tidying steps before passing the raw text to the nlp object which will give a doc object
  for k, input_key in enumerate(key_list):
    valueset = json_input_parsed[input_key]
    this_art = valueset['txt']
    this_art = re.sub('\xa0',' ', this_art)
    this_art = re.sub('\x0D', ' ', this_art)
    this_art = re.sub('\r|\n|\t',' ',this_art)
    this_art = re.sub('(  )+',' ',this_art)
    this_art = re.sub('  ',' ',this_art)
    this_url = valueset['url']
    hex_id = url_to_hex_id(this_url)
    doc = nlp(this_art)
    ## iterate over the sentences, adding the metatext from the doc object and the metadata from the dictionary to make the sentence-level annotations
    for s, sentence in enumerate(doc.sents):
      current_sent = []
      
      metas = "".join([(f'# {key}={value}\n') for key,value in valueset.items() if 'txt' not in key])    
      meta_text = " ".join([token.__str__() for token in sentence])
      meta_lines = f"\n# Article_num = {str(k+1)}\n# sent_ID = {hex_id}-{int(s+1)}\n# sent_id_serial = {int(s+1)}\n{metas}\n# text = {meta_text}\n"
      current_sent.append(meta_lines)
      ## iterate over the tokens in the sentence to make token-level conll strings
      for t, token in enumerate(sentence):
        line = (f'{int(t)+1}\t{token.text}{line_tail}')
        # print(f'{int(t)+1}\t{token.text}')
        current_sent.append(line)
      # add a line break at the end of every sentence
      current_sent.append("\n")
      # at the end of every sentence, join all the lines into a single string
      current_sent_tidy = "".join([c for c in current_sent])  
      file_output.append(current_sent_tidy)
      
  return file_output

def send_to_files(input_file, file_output, chunk_size=50000):
  '''
  Print conll strings to output file, in chunks of 50 000 sentences, to limit filesizes
  Inputs:
  	input_file (str) : absolute path to the json file taken as input
  	file_output (str) : absolute output path to which a file will be written
	chunk_size (int) : number of sentences to which to limit files ; default =50000, which yields 0.5-1.0 million words per file 
  Returns : no return object ; a file is exported to the specified location
  '''

  # Calculate the number of files needed
  num_files = math.ceil(len(file_output) / chunk_size)
  
  # Loop through the data in chunks and write to separate files
  for i in range(num_files):
      # Determine the start and end of the current chunk
      start_idx = i * chunk_size
      end_idx = start_idx + chunk_size
      # Extract the current chunk of data
      chunk = file_output[start_idx:end_idx]
      subpart_num = f"{i + 1:02d}"
      output_file = input_file.replace('.json', f'_part{subpart_num}.conll').replace('1_conllised_json','2_conllu')
      # Write the chunk to a new file
      with open(output_file, 'w', encoding='UTF-8') as f:
          for line in tqdm(chunk, desc=f"Writing file {i+1}/{num_files}"):
              outline = "".join([item for item in line])
              _ = f.write(outline)
              

def process_one_file(input_file, nlp):
  '''
  Function to serve as base for the partial function to be run once per pool
  Inputs :
    input_file: str : absolute path to input file to process
    nlp : a spacy nlp pipeline object
  '''

  file_output = make_conll_strings_from_json_with_allmetas(input_file, nlp)
  print(f"processing {input_file}")      
  send_to_files(input_file, file_output, chunk_size=50000)
  

def sent_json_to_conll(year, lang, nproc):
  '''
  define the processing pipeline to run as in __main__
  Inputs :
  	year : string : year for which to process files
  	lang : string : language to be processed
  	nproc : int : number of processors to use in the pool
  '''

  # step1 : gen list of files
  input_files = glob.glob(f'/Volumes/HC3Beta/uncompressed_parquet/cc_{lang}/{year}/1_conllised_json/*.json')
  print(f'{len(input_files)} to process')
  
  ## step2 make pool and use 2 safety-checks : n procs is less than cpu_count() and that nprocs is not less than the number of files to process.
  pool_size = min(nproc, cpu_count())
  if pool_size >= len(input_files):
    pool_size = len(input_files)
    print(f"Using pool size == file size == {pool_size}")
  else:
    print(f"Using pool size: {pool_size}")
  
  ## define nlp pipeline and make worker functuin
  nlp = define_pipe(lang)
  print(f'nlp loaded for {lang}')
  worker_func = partial(process_one_file, nlp=nlp)
  
  # map work to pool
  with Pool(pool_size) as pool, tqdm(total=len(input_files), desc="Processing", unit="file") as pbar:
    results=[]
    for file_path in input_files:
      r = pool.apply_async(worker_func, (file_path,), callback=lambda _: pbar.update(1))
      results.append(r)

    # Wait for all tasks to complete
    for r in results:
      r.wait()

  return results

def parse_years(year_args):
  '''
  parse years into a list
  '''
  years = []
  for y in year_args:
    # allow comma-separated values in each argument
    parts = y.split(",")
    for p in parts:
      cleaned = p.strip()
      if cleaned:      # ignore empty
        years.append(cleaned)
  return years
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="run step 1 to convert parquet to json files. Speed = about 30s per parquet file ≈ 4GB of parquet per min from external HDD\nrun step 2 to convert json to conllu files.")

    parser.add_argument(
        "-year", "-y",
        nargs="+",
        help="Year or list of years",
        required=True
    )
    #parser.add_argument(
    #    "-year",help="YEAR for folder in standard hierarchy ")
    parser.add_argument(
        "-num", type=int, help="Upper limit of range of number of files to process")
    parser.add_argument(
        "-filter_type", type=str, help="filter_type: domain or lang")
    parser.add_argument(
        "-filter_value", type=str, help="url or language")
    parser.add_argument(
        "-mode",default="X",help="Processing mode : S for strict to get only year_matches for source and scrape")
    parser.add_argument(
        "-local_dir",default=None,help="local dir override")    
    parser.add_argument(
        "-skip",default="",help="skip steps 1 -process parquet- or 2 -process json-")    
    parser.add_argument("--nproc", type=int, default=4, help="Number of parallel processes")
    parser.add_argument(
        "-lang", type=str, default="en",
        help="Language code (e.g., en, fr, de)"
    )

    args = parser.parse_args()
    
    nproc = args.nproc
    year_arg = args.year
    tidy_years = parse_years(year_arg)
    lang = args.lang
    number = args.num
    filter_type = args.filter_type
    filter_value = args.filter_value
    mode = args.mode
    local_dir= args.local_dir
    skip_value = args.skip
    for year in tidy_years:
        if "1" not in skip_value:
            get_json_from_parquet(filter_type, filter_value, number, mode, year, local_dir=local_dir)
        if "2" not in skip_value:
            sent_json_to_conll(year, lang, nproc)

