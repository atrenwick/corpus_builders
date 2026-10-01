# Earnings Calls: Creating an XML corpus of tagged, parsed English language financial earnings calls

## 📋 Project Overview
This pipeline transforms an existing dataset of earnings calls into XML-TEI files of a specific structure. The process involves foud main stages:
1.  **Data Acquisition**: Downloading `.parquet` files from Hugging Face.
2.  **Preprocessing**: Sentencizing, tokenizing, transcripts, identifying speakers, and formatting them into CoNLL format.
3.  **Parsing with Stanza**: Parsing the files with Stanza to add POS tags, lemmas, morphological features and syntactic dependencies.
4.  **XML Structuring**: Converting tagged CoNLL files into TEI XML format and consolidating them into yearly corpora.

---

## 🚀 Pipeline Workflow

### Step 1: Data Acquisition (`step1_get_parquets_from_hf.py`)
Downloads the raw dataset from a specified Hugging Face repository.
- **Input**: Hugging Face Repository ID.
- **Output**: Local `.parquet` files.
- **Key Features**: 
    - Automatic progress tracking via `tqdm`.
    - Handles authentication via HF tokens.
    - Downloads only `.parquet` files to a designated local directory.

### Step 2: Conllisation (`step2_conllise_earnings_calls.py`)
Processes raw text into a structured CoNLL format, preserving speaker identities and metadata.
- **Input**: `.parquet` files.
- **Output**: Chunked `.conll` files (e.g., `ArticleID_part01.conll`).
- **Key Features**:
    - **NLP Pipeline**: Uses `spaCy` to perform high-speed sentencizing.
    - **Speaker Detection**: Uses Regex to identify and separate speaker prefixes (e.g., "John Doe:").
    - **Parallel Processing**: Utilizes `ProcessPoolExecutor` for multi-core CPU processing.
    - **Metadata Handling**: Automatically calculates fiscal dates and extracts company/quarter information.

### Step 3: Parsing with Stanza 
Use Stanza to perform POS tagging, lemmatisation, morphological feature analysis and dependency parsing.
- **Input**: `.conll` files.
- **Output**: `.conll` files.
- **Key Features**:
    - **Parsing only**: Preserves existing tokenisation and sentencisation.
    - **Customisable batch sizes**: Batch sizes for the internal components of the stanza model can be customised.
    - **Dependency parsing only**: Option to run only the dependency parsing if the input files are already POS-tagged, lemmatized and have morphological features.


### Step 4: XML Conversion (`step4_convert_conll_to_xml.py`)
Converts the tagged CoNLL files into a final TEI XML structure.
- **Input**: `.conll` files.
- **Output**: `.xml` files with TEI headers.
- **Key Features**:
    - **XML Templating**: Uses `lxml` to build a valid TEI header with metadata (title, author, dates…).
    - **Text Cleaning**: Normalizes "smart quotes" and standardizes whitespace.
    - **Consolidation**: Option to automatically merge all XML files for a specific year into a single annual file (e.g., `earnings_2023.en.xml`).
    - **Parallel Processing**: Uses `multiprocessing.Pool` for concurrent file conversion.

---

## 🛠 Installation & Setup

### Prerequisites
Python 3.8+, with the following libraries:
```bash
pip install lxml stanza spacy pandas huggingface_hub tqdm requests
```

### NLP Models
The pipeline uses `spaCy` for sentenisation and `Stanza` for the actual parsing. 
```bash
python -m spacy download en_core_web_sm
# For Stanza (used in step 4)
python -m stanza download en
```

### Environment Variables
For Step 1, ensure your Hugging Face token is set in your environment:
```bash
export HF_TOKEN='your_token_here'
```

---

## 📖 Usage

### 1. Download Data
```bash
python3 step1_get_parquets_from_hf.py \
    --repo "path/to/hf/repo" \
    --local_dir "./data/raw"
```

### 2. Make CoNLL-format docs for Stanza
```bash
python3 step2_conllise_earnings_calls.py \
    -input_dir "./data/raw" \
    -output_dir "./data/conll_files" \
    -n_procs 8 \
    -chunk_size 50000
```

### 3. Run parsing with Stanza
```bash
python3 run_stanza.py \
    --size 1.0 \
    --lang en\
```


### 4. Convert to XML & Consolidate
```bash
python3 step4_convert_conll_to_xml.py \
    --source_dir "./data/conll_files" \
    --output_dir "./data/xml_corpus" \
    --nproc 8 \
    --consolidate
```

---

## ⚙️ Technical Notes
- **Concurrency**: Both the Conllisation and XML Conversion steps are designed for high-performance multi-core processing using `ProcessPoolExecutor` and `multiprocessing.Pool`.
- **Data Integrity**: The pipeline uses deterministic hashing (`SHA-256`) to generate unique sentence IDs for use in processsing. These are replaced with simple sequential integers in the output files.
- **Memory Management**: The `_init_worker` pattern in Step 2 loads a spacy NLP object with only the sentencizer in the pipeline - it is thus very light, minimising the risk of OOM errors even with multiple workers on less powerful/modern platforms.
