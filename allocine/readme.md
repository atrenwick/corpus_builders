***

# AlloCiné fan reviews: French-language movie reviews for corpus linguistics

This project provides a pipeline to transform raw French movie reviews from a pickle format into a structured, metadata-rich **TEI XML Corpus**. The final output is designed to be compatible with **Lexicoscope 2.0**, enabling advanced linguistic querying across various film attributes.


## 📌 Project Overview

The goal of this project is to take raw review data, perform linguistic processing via **Stanza**, scrape relevant film metadata from the web, and consolidate everything into a standardized XML format, to allow for querying based on both linguistic annotations and metadata.

### Data Source
The raw data is sourced from [Théophile Blard's sentiment analysis repository](https://github.com/TheophileBlard/french-sentiment-analysis-with-bert/blob/master/allocine_dataset/data.tar.bz2). 
- **Source File:** `allocine_dataset.pickle` (contained within the `data` folder after decompression).
- **Contents:** Raw movie reviews and their corresponding Allociné URLs.

---

## 🚀 The Pipeline

The workflow is divided into four distinct steps.

### Step 1: CoNLL Conversion
**Script:** `step1_conllise_allocine_reviews.py`
Processes the raw `allocine_dataset.pickle` file to generate CoNLL-style formatted files that parsers, like [Stanza](https://github.com/stanfordnlp/stanza/tree/main), can easily ingest while preserving tokenisation and sentencisation.
- **Usage:**
  ```bash
  python step1_conllise_allocine_reviews.py --source <path_to_pickle> --chunk_size <int>
  ```
  *Example: `python step1_conllise_allocine_reviews.py --source data/allocine_dataset.pickle --chunk_size 25000`*



### Step 2: Metadata 
**Script:** `step2_get_allocine_metadata.py`
This script extracts movie metadata from the URLs provided in the initial dataset.

- **Output:** An XML file containing all scraped metadata.
- **Note:** The resulting XML is compressed into `allocine_metasV2.tar.bz2` to prevent the need for repeated scraping.

### Step 2: Metadata Scraping
**Script:** `step2_get_allocine_metadata.py`
Extracts movie metadata for the films in the source dataset based on URLs.
- **Data Extracted:** Genre, release date, ratings, duration, and director names.
- **Usage:**
  ```bash
  python step2_get_allocine_metadata.py --source_file <url_fragment_file> --output_dir <dir> --delay <float> --offset <int>
  ```
  *Example: `python step2_get_allocine_metadata.py --source_file urls.txt --output_dir ./metadata_raw --delay 5.0 --offset 0`*


### Step 3: TEI XML Conversion
**Script:** `step3_convert_conll_to_xml.py`
Converts the CoNLL files (processed by Stanza) into a structured TEI Corpus where each review is a distinct document.
- **Usage:**
  ```bash
  python step3_convert_conll_to_xml.py -source_dir <dir> -output_dir <dir> -lang fr -n_procs <int>
  ```
  *Example: `python step3_convert_conll_to_xml.py -source_dir ./conll_output -output_dir ./xml_corpus -lang fr -n_procs 4`*


### Step 4: Metadata Consolidation
**Script:** `step4_consolidate_metas.py`
Merges the tidied XML files with the metadata obtained in Step 2. This populates the `<sourceDesc>` element with queryable fields for Lexicoscope 2.0.
- **Queryable Fields:** Film title, director, genre, length, press/view ratings, release date (year, month, day), and URLs for both the film page and user reviews.

- **Usage:**
  ```bash
  python step4_consolidate_metas.py -source_dir <dir> -output_dir <dir> -json_metas <path> -xml_metas <path> [--limit <int>] [--offset <int>] [--singleExport]
  ```
  *Example: `python step4_consolidate_metas.py -source_dir ./xml_corpus -output_dir ./final_xml -json_metas metas.json -xml_metas metas.xml --singleExport`*

---

## 🛠 Prerequisites

This pipeline uses Python 3.12+ along with the following libraries:

**External Libraries:**
- `pandas` (Data manipulation)
- `spacy` & `stanza` (NLP processing and models)
- `lxml` (XML parsing and construction)
- `tqdm` (Progress bars)
- `requests` (Web scraping)
- `beautifulsoup4` (HTML parsing)

**Installation:**
```bash
pip install pandas spacy stanza lxml tqdm requests beautifulsoup4
python -m spacy download fr_core_news_sm
```

---

## 📂 Project Structure
```text
.
├── data/
│   └── allocine_dataset.pickle      # Raw source data
├── step1_conllise_annocine_reviews.py
├── step2_get_allocine_metadata.py
├── step3_convert_conll_to_xml.py
├── step4_consolidate_metas.py
└── allocine_metasV2.tar.bz2         # Cached metadata
```




