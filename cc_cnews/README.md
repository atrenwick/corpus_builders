# cc_news: Creating corpora from CC News dumps 


### 1. Dataset Acquisition (HF Download)

This script handles the initial data ingestion phase. It retrieves raw `.parquet` files from a specified Hugging Face dataset repository, filtering the results by a specific year to ensure only the relevant data is downloaded for the pipeline. This is of course not the only way to get data from HF, it was just a test « can I make something to download what I want my way »

#### Key Features:
*   **Hugging Face Integration**: Connects directly to the HF Hub to list files and generate download URLs.
*   **Year-based Filtering**: Automatically identifies and targets only the files for specified 4-character years (e.g., "2020").
*   **Streaming Downloads**: Uses streaming requests to handle large files efficiently, ensuring low memory overhead by writing chunks directly to disk.
*   **Progress Tracking**: Integrates with `tqdm` to provide real-time visual feedback on the download progress, including data transfer rates.

#### Prerequisites:
> [!IMPORTANT]
> This script requires a Hugging Face Access Token. Ensure you are authenticated on your machine by running `huggingface-cli login` or by setting the `HF_TOKEN` environment variable before execution.


#### Example Usage:
```bash
python get_parquetfiles.py --year 2020 --repo foo/bar --local_dir /data/raw_parquet
```

**Argument Reference:**
*   `--year`: The 4-character year prefix (e.g., `2020`) used to filter the files.
*   `--repo`: The Hugging Face repository ID following the standard pattern of username/datasetname (here, user 'foo', dataset = 'bar').
*   `--local_dir`: The absolute path to the local directory where the `.parquet` files will be saved.

---

### 2. Data Extraction and ConLLU Conversion

This script serves as the core processing engine, transforming raw parquet data into structured JSON files and subsequently into CoNLLU format for NLP analysis. It handles multi-stage filtering, metadata extraction, and parallelized tokenization.

#### Key Features:
*   **Polars-Powered Filtering**: Uses `polars` for high-performance scanning and filtering of parquet files by language or specific website domains.
*   **Metadata Mapping**: Extracts and organizes complex metadata (URLs, titles, authors, publication dates, crawl timestamps) from raw data into structured dictionaries.
*   **Multi-Process Tokenization**: Integrates with the `spacy` library to perform language-specific tokenization (English, French, German, Italian, Spanish) using a parallel worker pool.
*   **ConLLU Serialization**: Converts processed text into the CoNLLU format, supporting large file handling by splitting output into chunks (up to 1 million words per file).
*   **Robust Batching**: Includes a flexible filtering system (`mode S` for strict year matching vs. standard mode) and a `nproc` logic that automatically scales based on available CPU cores and file counts.

#### Processing Workflow:
1.  **Parquet to JSON**: Scans raw data $\rightarrow$ Filters by language/domain $\rightarrow$ Extracts metadata $\rightarrow$ Exports to JSON.
2.  **JSON to CoNLLU**: Loads JSON $\rightarrow$ Cleans text $\rightarrow$ Tokenizes via `spacy` $\rightarrow$ Serializes to CoNLLU with unique `uuid` and `sent_id`.

#### Example Usage:
To export data from 2017 filtering on the `lemonade.fr` domain, looking for English articles, with  8 parallel workers:
```bash
python make_conll.py -year 2017 -filter_type domain -filter_value lemonde.fr --nproc 8 -lang en
```

**Argument Reference:**
*   `-year`: The 4-character year (e.g., `2017`). Accepts multiple values (e.g., `2017,2018`).
*   `-num`: Upper limit of number of files to process
*   `-mode`: `S` for strict (requested year matches crawl year AND publication year), `X` (default) matches on crawl year only.
*   `-filter_type`: Either `lang` (filter by language code) or `domain` (filter by URL). If `domain` is used, an additional `-lang` filter can be added to filter on language as well.
*   `-filter_value`: The value to filter on (e.g., `en` or `fr` if filter type is `lang` ; e.g. `usatoday.com` or `bbc.com`' using a domain filter.
*   `--nproc`: Number of worker processes (defaults to 4).
*   `-skip`: Skip steps: `1` skips making jsons from .parquet files, `2` skips making conll files from jsons.
*   `-local_dir`: Optional local directory override for data paths.


---

### 3. NLP Annotation and Dependency Parsing

This script performs deep linguistic analysis on the processed CoNLLU files using the **Stanza** NLP library, adding POS tags, lemmas, and syntactic dependencies.

#### Key Features:
*   **Language-Specific Pipelines**: Dynamically loads a Stanza pipeline for target languages (English, French, German, Italian, Spanish, etc.).
*   **Configurable Batching**: Provides a granular control system for batch sizes. It allows users to scale memory usage via a `size` multiplier, ensuring that the `pos_batch_maximum_tokens` is scaled correctly to maintain pipeline geometry.
*   **Dependency Parsing Modes**: Supports a `depparseOnly` mode for scenarios where only dependency trees are required (e.g., for specific structural analyses), which skips the overhead of tokenization and lemmatization.
*   **Automated Quality Control**: Automatically identifies and logs files that exceed a maximum sentence length limit (default 1,600 tokens) to prevent memory overflows and ensure the integrity of the dependency trees.
*   **File Management made idiot-proof**: Automatically renames files from `tag_input` to `tag_output` upon successful completion, preserving the directory structure.

#### Processing Logic:
1.  **Pipeline Initialization**: Based on the language code, the script selects the appropriate Stanza package (e.g., `ewt` for English, `gsd` for French/German) and configures the batching parameters.
2.  **Ingestion**: Reads the CoNLLU documents and passes them to the language-specific parsing pipeline without changing sentencisation or tokenisation.
3.  **Annotation**: Applies POS tags, lemmatises, and adds dependency parses.
4.  **Serialization**: Writes the final annotated objects back to the filesystem as structured CoNLL files.

#### Example Usage:
To run the French dependency parser with a batch size multiplier of 1.5:
```bash
python parse_conll.py -lang fr -size 1.0 
```

**Argument Reference:**
*   `-lang`: The 2-3 letter language code expected by Stanza (e.g., `en`, `fr`, `de`, `it`, `es`, `ang`, `fro`, `frm`).
*   `-size`: An integer or float used to define `mwt_batch_size`, `pos_batch_size`, `lemma_batch_size`, `depparse_batch_size` and  `depparse_second_batch_size`. The base batch size is calculated as `size * 1024` so specifying `1.0` will limit batch sizes to 1024. 
*   `-depparseOnly`: If set to `T` or `True`, the script will only run the dependency parser. The input files must be well-formatted CoNLL with at least POS and LEM annotations already present.
*   `--subf`: (Optional) Specifies a subfolder within `tag_input` to process. If left blank, the script scans the root `tag_input` directory for both `.conll` and `.conllu` files.

---


### 4. ConLL to Article XML Conversion
#### Key Features:
*   **Metadata Extraction**: Uses article and sentence IDs to insert article-level metadata (titles, authors, publication dates, URLs, and crawl timestamps).
*   **Hierarchical Reconstruction**: Automatically groups consecutive sentences into paragraph (`<p>`) elements based on their structure in the source file.
*   **Tree tidying**: All tokens are in `<s>` (sentence) elements, preserving token IDs and cleaning up punctuation (e.g., converting curly quotes to standard quotes).
*   **Multi-Process Parallelism**: Utilizes a worker pool for parallel processing.
*   **Consolidation**: Includes an optional feature to merge multiple XML files from a specific publication/year into a single file.

#### Processing Logic:
1.  **Metadata Mapping**: Identifies the start of new articles and initializes a TEI header containing the source metadata.
2.  **Sentence Processing**: Iterates through the sentences, extracting the `uuid` and `sent_id`.
3.  **Tree Tidying**: 
    *   Ensures all `<s>` blocks have a parent `<p>` element.
    *   Ensures all `<p>` elements have a parent `<body>` element.
    *   Normalizes date and language attributes across the document.
4.  **Source Description**: Populates a specific `<sourceDesc>` block with crawl URLs and timestamps extracted from the metadata.

#### Example Usage:
To process all files from 2020 in English, using 4 parallel workers, consolidating all the files for the SMH (Sydney Morning Herald) into 1 xml file `shm.xml`:
```bash
python send_to_xml.py -year 2020 -mode A -lang en --nproc 4 --log /data/logs/mylogfile.txt -consolidate True -publi smh
```

**Argument Reference:**
*   `-year`: The year folder in the `cc_corpus` directory (e.g., `2020`).
*   `-mode`: Filtering mode: `A` (All), `E` (Even numbers), or `O` (Odd numbers).
*   `-lang`: Language code for language rules (e.g., `en`, `fr`).
*   `--nproc`: Number of parallel worker processes.
*   `--log`: Path to the log file for tracking progress and errors.
*   `-consolidate`: Boolean flag; if `True`, merges all individual XMLs into one file at the end.
*   `-publi`: A regex-like file pattern to filter the specific publication you wish to process.
