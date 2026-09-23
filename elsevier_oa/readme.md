# Building a Corpus from the Elsevier OA-BY-CC Dataset

This repository contains a pipeline to transform the **Elsevier OA-BY-CC dataset** (comprising over 40,000 documents) into a structured, tokenized, and sentencised XML corpus.

> [!IMPORTANT]
> **Environment Recommendation:** It is highly recommended to run this in a fresh virtual environment (e.g., `elsevier_env`),

## 📋 Pipeline Overview
The processing follows this sequence:
1. **Move/Chunking**: `1_elsevier_mover.py`
2. **JSON to XML**: `2_json_to_xml.py`
3. **Tokenisation**: `3_tokeniser.py`
4. **Sentencisation**: `4_sentenciser.py`
5. **Re-insertion**: `5_reinsert.py`
6. **Easiest step**: Go to step 7. 
7. **Metadata Querying**: `7_issn_querying.py`
8. **Tree Update**: `8_update_trees.py`

---

## 🚀 Script Details

### 1. `1_elsevier_mover.py`
**Purpose:** Handles 40,000+ files by chunking them into subfolders. This reduces OS strain, improves file explorer performance, and allows for batch processing.

**Example Usage:**
```bash
python 1_elsevier_mover.py --source /data/elsevier_oa/data_step0 --chunks 1000 --extension json --verbose
```
*   `--source`: Path to folder containing 40,000 JSON files.
*   `--chunks`: Number of files per chunk (default: 1000).
*   `--extension`: File type to target (default: `json`).
*   `--verbose`: Prints details of each individual file move.

---

### 2. `2_json_to_xml.py`
**Purpose:** Transforms source JSON documents into TEI-compatible XML. It preserves the text body and hierarchical information (e.g., identifying "Introduction to exciting topic number 1" as a specific paragraph).

**Example Usage:**
```bash
python 2_json_to_xml.py --source_dir /data/elsevier_oa/data_step0 --output_dir /data/elsevier_oa/data_step1
```
*   `--source_dir`: Path to folder containing the chunked JSON subfolders.
*   `--output_dir`: Path to the new folder for output XML files (reproduces the folder organization).

---

### 3. `3_tokeniser.py`
**Purpose:** Performs tokenization on paragraphs, adding a `<w>` element with a unique ID for every token. It handles standard English boundaries (spaces/punctuation) and special cases like possessive apostrophes and Latin abbreviations.

**Example Usage:**
```bash
python 3_tokeniser.py --inputPath /data/elsevier_oa/data_step1 --output_path /data/elsevier_oa/data_step2 --nprocs 4 --join_hyphen True --lang en
```
*   `--inputPath`: Path to the folder containing chunked XML files.
*   `--output_path`: Path for the tokenized XML files.
*   `--nprocs`: Number of worker processes (limited by CPU cores and file count).
*   `--lang`: Language for rules (e.g., `en` for English).

---

### 4. `4_sentenciser.py`
**Purpose:** Identifies sentence boundaries. Since paragraphs are reliable anchors, this script labels tokens as "end of sentence" using logical rules (e.g., ignoring periods in "Mr.", "1.2", or "e.g.").

**Outputs:**
1.  **Sentencised XML**: The reference file.
2.  **CoNLL File**: For ingestion by Stanza for POS tagging, lemmatization, and dependency parsing.

**Example Usage:**
```bash
python 4_sentenciser.py --source_dir /data/elsevier_oa/data_step2 --output_dir /data/elsevier_oa/data_step3 --n_procs 4 --join_hyphen True --lang en
```
*   `--offset`: Starting number for sentence numbering (e.g., `--offset 314`).
*   `--chunksize`: Number of files each worker should read in a single batch.

---

### 5. `5_reinsert.py`
**Purpose:** Takes `.conll` files produced by Stanza and inserts those annotations back into the XML files.

**Example Usage:**
```bash
python 5_reinsert.py --conll_source /data/elsevier_oa/data_step4/03 --xml_dirname data_step3 --xml_output data_step5 --id_attrib s_id --n_procs 4 --sibling
```
*   `--conll_source`: Path to folder containing tagged CoNLL files.
*   `--xml_dirname`: The *name* (not path) of the folder containing the sentencised XML.
*   `--sibling`: If enabled, iterates over all sibling folders (e.g., `/01/`, `/02/`, etc.) instead of just the specified source.

---

### 7. `7_issn_querying.py`
**Purpose:** A two-part metadata harvester.
1.  Builds a dictionary of article-level metadata from the source JSONs.
2.  Queries the Elsevier API to build a journal-level dictionary (ISSN $\rightarrow$ Title $\rightarrow$ Subject Area).

> [!IMPORTANT]
> **API Key Requirements:** Requires a free API key from [Elsevier's Dev Portal](https://dev.elsevier.com).
> *   **Rate Limiting:** Respect the quotas. The `--delay` argument can be used to remain "polite."
> *   **Secrets:** Save your key in a file named `secrets.env` in the same directory as the script.

**Example Usage:**
```bash
python 7_issn_querying.py --json_source /data/elsevier_oa/data_step0 --delay 30 --buffer 10
```
*   `--delay`: Seconds to pause between API calls.
*   `--buffer`: Number of responses to hold in memory before flushing to disk.

---

### 8. `8_update_trees.py`
**Purpose:** Finalizes the XML. It injects the metadata gathered in Script 7 into new `<teiHeader>` elements and groups `<p>` tags into `<div type="...">` elements based on their shared categories.

**Example Usage:**
```bash
python 8_update_trees.py --source /data/elsevier_oa/data_step5/03 --output /data/elsevier_oa/data_step6 --issn /data/elsevier_oa/data_step0/issn_success_titles.json -a /data/elsevier_oa/data_step0/metadata_dict.json --n_procs 7 --sibling --extension .xml
```
*   `--issn`: Path to the ISSN-title-subject dictionary.
*   `-a`: Path to the article-level metadata dictionary.

---

## 🛠 Helper Scripts

### `zip_here.py`
A CLI helper to compress files/folders for archival or remote transfer.

*   **Monolithic Mode** (`--mode mono`): Compresses a folder into a single zip.
*   **Individual Mode** (`--mode indiv`): Compresses every file into its own zip file (parallelized via `--n_procs`).
*   **Subfolder Mode** (`--mode subfolder`): Zips files with a specific extension into their respective subfolders (ideal for feeding files to a GPU server).
