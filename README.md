# cc_news
Creating corpora from CC News dumps with a bit of py

## Step1
Step 1 is performed by `get_parquetfiles.py`
This step involves downloading the parquet files we want from HF. Downloading can also be done with `huggingface_hub` , see https://huggingface.co/docs/huggingface_hub/en/guides/download.

This script was more of a "Let's see if I can do it my way" exercise.
Note : requirements : HfFolder will need an HF token to have been set up to access the dataset.

## Step2
Step 2 is performed by `make_conll.py`
This step takes parquet files retrieved in Step1, and extracts articles from them, exporting the data to json files as an intermediate step. This means we do the slower parquet processing step once.
The files can thus be inspected and any changes made much more speedily than from the parquet, before exporting the data to the conll files the parsing script wants.

## Step3
Step 3 is performed by `runStanza.py`
This is the longest step, sending the files to the parser.

## Step4
Step 4 is performed by `send_to_xml.py`
This script takes conll files and converts them to XML, using the metadata stored in the conll comment lines.
