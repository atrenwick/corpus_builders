## get ISSN info
import argparse
import json
import os
import requests
import time

from dotenv import load_dotenv
from pathlib import Path
from tqdm import tqdm

from concurrent.futures import ThreadPoolExecutor, as_completed


env_path = Path(__file__).resolve().parent / "secrets.env"
load_dotenv(env_path)
MY_KEY = os.environ["MY_API_KEY"]
try:
	print(f"key loaded: as MY_KEY")
except:
	print("Error")

### part 1 : get local metadata

## get json files
def get_files(folder_with_jsons):
    path_to_jsons =Path(folder_with_jsons) 
    json_files = []
    folders = sorted([ 
        p for p in path_to_jsons.iterdir() if p.is_dir() 
        ])
    for folder in folders:
            files = sorted(folder.glob("*.json"))
            json_files.extend(files)
    print(f"Found {len(json_files)} files")
    return json_files

# refactor 
def refactor_metas(json_file):
    docId = json_file.stem
    with open(json_file, 'r', encoding='utf-8') as j:
        input_dict = json.load(j)
    
    metadata = input_dict['metadata']
    try:
      first_author = f"{metadata['authors'][0]['last']} et al. "
    except Exception as e:
      first_author = 'NA'
    title = str(metadata['title'])
    year = str(metadata['pub_year'])
    journal_issn = str(metadata['issn'])
    article_subj = metadata['subjareas']
    issue =  str(metadata['issue']) if 'issue' in metadata.keys() else "_"
    number =  str(metadata['number']) if 'number' in metadata.keys() else "_"
    volume=  str(metadata['volume']) if 'volume' in metadata.keys() else "_"
    refactored_dict = {
      "docId": docId,
      "first_author": first_author,
      "title": title,
      "year": year,
      "journal_issn": journal_issn,
      "article_subj":article_subj,
      "issue":issue,
      "number":number,
      "volume":volume
    }
    return docId, refactored_dict

# make dict, dump dict, issn_list to file, return dict
def make_dict(folder_with_jsons):
    json_files = get_files(folder_with_jsons)
    
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        results = list(tqdm(
            executor.map(refactor_metas, json_files, chunksize=128),
            total=len(json_files)
        ))
    
    output_dict = dict(results)
    metadata_dict_file = Path(Path(folder_with_jsons).parent , "metadata_dict.json")
    with open(metadata_dict_file, 'w', encoding='UTF-8') as j:
        json.dump(output_dict, j)
    print(f'Metadata dict saved to {metadata_dict_file}')

    issns = [v.get('journal_issn', "X") for  v in metadata_dict.values() if isinstance(v, dict)]
    tidy_issns = list(set(issns))
    issn_list_file = Path(Path(folder_with_jsons).parent , "issn_list.json")
    issns_as_dict = {issn:"" for issn in tidy_issns}
    with open(issn_list_file, 'w', encoding='UTF-8') as j:
        json.dump(issns_as_dict, j)
    print(f'ISSN list saved to {issn_list_file}')
    return tidy_issns



# part 2 : get metadata from remote
def process_one_issn(issn):
    params = {"mailto": 'mailto_email'}
    full_url = f'https://api.elsevier.com/content/serial/title/issn/{issn}?apiKey={MY_KEY}'

    try:
        resp = requests.get(full_url, params=params, timeout=10)

    except:
        return  {
            "status_code":"GET error", 
            "serial_metas": "NA",
            "subj_code":"NA",
            "title": "NA"
            }
         
    if resp.status_code != 200:
        # handle error, maybe return None or raise
        return  {
            "status_code":resp.status_code, 
            "serial_metas": "NA",
            "subj_code":"NA",
            "title": "NA"
            }

    ## if we have a 200 response, parse the data
    try:
        data = resp.json()
    except Exception as e:
        return {"status_code": resp.status_code, "serial_metas": "json_decode_error", "subj_code": "NA", "title": "NA"}


    if "serial-metadata-response" not in data:
        return  {
            "status_code":resp.status_code, 
            "serial_metas": "serial_error",
            "subj_code":"NA",
            "title": "NA"
            }
    try:
        # if there is usable data
        msg = data["serial-metadata-response"]
        
        try:
          subj_code =   msg['entry'][0]['subject-area'][0]['@abbrev']
        except:
          subj_code = "UNK"
        
        try:
          title = msg['entry'][0]['dc:title'] 
        except:
          title = "UNK"

        return {
            "status_code":resp.status_code, 
            "serial_metas": "success",
            "subj_code":subj_code,
            "title": title
            }
   
    
    except Exception as e:
        return {
            "status_code":resp.status_code, 
            "serial_metas": "Exception_error",
            "subj_code":"NA",
            "title": "NA"
            }

def run_issn_querying(folder_with_jsons, tidy_issns, delay, qtest, number):
    batchSize = 10
    error_dict = dict()
    success_dict = dict()    
    success_output_file = Path(Path(folder_with_jsons).parent, "issn_success_data.json")
    print(f"Exporting success ->> {success_output_file}")
    error_output_file = Path(Path(folder_with_jsons).parent, "issn_error_data.json")
    print(f"Exporting errors ->> {error_output_file}")
    if qtest:
        these_issns= tidy_issns[:int(number)]
    print(f"Running queries on {len(these_issns)} issns with batch == {batchSize} and delay = {delay}")

    for num, issn in tqdm(enumerate(these_issns, start=1)):
        return_dict = process_one_issn(issn)
        if return_dict['serial_metas'] != "success":
            error_dict[issn] = return_dict
        else:
            success_dict[issn] = return_dict
            print(f'ISSN {issn} == {return_dict["title"]} :: subj = {return_dict["subj_code"]}')
    
        if num % batchSize == 0:
            for result_dict, output_file in zip([success_dict, error_dict], [success_output_file, error_output_file]):
                flush_dict_buffer(result_dict, output_file)
            success_dict, error_dict = dict(), dict()
        
        time.sleep(int(delay))

def load_issns_from_json(issn_infile):
    with open(Path(issn_infile), 'r', encoding='UTF-8') as j:
        input_dict = json.load(j)
    issn_tidy = [k for k in input_dict.keys()]  
    print("ISSNs loaded from file successfully")
    return issn_tidy

def flush_dict_buffer(result_dict, output_file):
    with open(output_file, 'a', encoding='UTF-8') as j:
        for key, value in result_dict.items():
            j.write(json.dumps({key: value}) + '\n')


def main(folder_with_jsons, delay,skip, qtest, number, issn_infile):
    if skip not in ("1", 1):
        tidy_issns = make_dict(folder_with_jsons)
    else:
    	try:
    	    print("working in skip1")
    	    tidy_issns = load_issns_from_json(issn_infile)
    	except Exception as e:
    	    print(f"Error : {e}")
    	    raise
        
    	run_issn_querying(folder_with_jsons, tidy_issns, delay, qtest, number)
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deal with metadata and ISSNs")
    
    parser.add_argument(
        "--json_source", 
        help="Path to dir with original json files"
    )
    parser.add_argument(
        "-d", "--delay", 
        help="Delay time in seconds",
        required=False,
        default=10,
        type=int,
        metavar="N"
    )
    parser.add_argument(
        "-s", "--skip", 
        help="Number of stage to skip",
        required=False,
        default="0"
    )
    parser.add_argument(
        "--q_test", 
        help="Run test queries only",
        required=False, 
        default=False, 
        action="store_true"
    )
    parser.add_argument(
        "--number", 
        help="How many tests to do", 
        required=False, 
        default=10, 
        type=int, 
        metavar="N"
    )
    parser.add_argument(
        "--issn_infile", 
        help="Path to existing file of issns", 
        required=False, 
        type=str
    )

    args = parser.parse_args()
    
    main(
        folder_with_jsons=Path(args.json_source),
        delay=int(args.delay),      
        skip=args.skip,  
        qtest=bool(args.q_test),
        number=int(args.number),
        issn_infile=Path(args.issn_infile)
    ) 
    
    
    