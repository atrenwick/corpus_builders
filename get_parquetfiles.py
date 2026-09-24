import os
import requests
import argparse

from tqdm import tqdm

from huggingface_hub import HfApi, get_token, hf_hub_url
## note that this script assumes a token has been obtained 
## from HF and appropriately placed on the machine running
## this script
def download_files_for_year(year, repo_id, local_dir):
  '''
  Download parquet files for a given year from the HF repo
  Inputs:
    year (str) : a year as 4 characters
    repo_id (str) : the repo_id of the HF repo to get files from
  Return :
    no return object : files will be downloaded
  '''
  # talking to the HF API
  token = get_token()
  api = HfApi()
  headers = {"Authorization": f"Bearer {token}"} if token else {}
  # List all files in the repo
  files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
  
  # Filter parquet files and then filter these to restrict to a specific year
  parquet_files = [f for f in files if f.endswith(".parquet")]
  target_files = [a for a in parquet_files  if a.startswith(f"{year}")]
  # ensure that the specified directory exists
  os.makedirs(local_dir, exist_ok=True)
  
  # for loop to get the files and do the downloading, with progress bar
  for filename in target_files:
      url = hf_hub_url(repo_id=repo_id, filename=filename, repo_type="dataset")
      local_path = os.path.join(local_dir, os.path.basename(filename))
      if os.path.exists(local_path) is False:
        # Stream download with progress bar
        with requests.get(url, headers=headers, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            with open(local_path, "wb") as f_out, tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=os.path.basename(local_path),
                leave=True,   # ✅ keep completed bars
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    _ = f_out.write(chunk)
                    _ = bar.update(len(chunk))
    
        print(f"✅ Downloaded {filename} → {local_path}")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download specific parquet files from  a HF repo to a specified directory.")
    parser.add_argument("-year",help="YEAR for folder in standard hierarchy ")
    parser.add_argument("repo", help="path to HF repo")
    parser.add_argument("-local_dir", help="absolute path to local directory where files will be downloaded")
    args = parser.parse_args()
  
    year = str(args.year)
    repo = str(args.repo)
    local_dir = str(args.local_dir)
    download_files_for_year(year, repo, local_dir)
