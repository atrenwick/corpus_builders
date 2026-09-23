Building corpus out of the Elsevier OA-BY-CC dataset

The Elsevier OA-BY-CC Corpus consists of just over 40,000 documents, and is available from `https://elsevier.digitalcommonsdata.com/datasets/zm33cdndxs/3`

Script 1 : 1_elsevier_mover.py
Once the source file is downloaded and unzipped, the main directory of json files contains all the data we want, but with 40000 files in one folder, it's not very manageable. 
This script divides the files into chunks, and places them in subfolders to make things easier from a human standpoint as well as organisationally - we can send batches of files to process with, for example - as well as reducing the strain on the OS, keeping track of tens/hundreds of thousands of files within a single folder - that's not precisely what most file explorers are built for.

Script 2 : 2_json_to_xml.py
This script transforms the json source documents into TEI-compatible XML documents, preserving the body of the texts as well as hierarchical information - this sentence is part of this paragraph called "Introduction to exciting topic number 1"

Script 3 : 3_tokeniser.py
This script performs tokenisation on the paragraphs present in the json documents, adding a <w> element with an ID for each token recognised. The bulk of tokens are like the bulk of words in English: spaces and punctuation form their boundaries, but special cases such as possessive apostrophes, Latin abbreviations and similar items are recognised as single tokens. 

Script 4: 4_sentenciser.py
This script might seem to have put the cart before the horse, defining tokens before defining where the sentences containing these tokens start and end. However, given the paragraphs are reliable start-end points for sentences, this script takes the approach that the tokens are present and some of them need to get a extra label « The end of the sentence is here » that we recognise when we see a full stop. This script applies a series of logical rules to determine where the label should be placed, as for example, not all `.` indicate the end of sentences: 1.2 can be left as a non-sentence boundary by checking whether the preceding/following token is a number, if we see a title such as `Mr.`, again, the full stop doesn't indicate a sentence boundary.
Once sentences have been identified, the results are exported to a new XML file : this contains everything, and is the reference file. A conll file is also produced, this can be easily ingested by Stanza to do POS tagging, lemmatisation, morphological feature analysis and dependency parsing. 

Script 5: 5_reinsert.py
This script takes the .conll files produced by Stanza, and inserts these annotations into the XML file created

Script 7: 7_issn_querying.py
This script performs two tasks. The first is to build a dictionary of metadata from all the source json files processed in Scripts 1-2. This brings all the article-level metadata into a single dictionary, which Script 8 will use. The second part involves obtaining journal-level metadata. To do this, the script queries the Elsevier API to get information on the journals in question : by looking up the ISSN for each journal, a dictionary can be built of ISSNs, journal titles and their subject areas.

Note that use of this API requires a free API key, which can be obtained from `https://dev.elsevier.com`. Among the conditions of using the API are that usage is research based and in accordance with the terms of use, notably the rate at which requests are sent : the more polite the script is in terms of delay between requests, the more likely it is that things will go well : the delay argument can be used to change this from the default : if only 10 requests are to be sent, a shorter delay may be appropriate, but for thousands of requests, carefully consider the usage quotas detailed here `https://dev.elsevier.com/api_key_settings.html`.
Once an API key has been obtained, it can be saved in a file named 'secrets.env' and placed in the same directory as `7_issn_querying.py` - this way the script will read the key directly from the file and insert it where necessary without a human copy-paste being added to the script itself.
When this script is complete, 2 dictionaries should have been created : one of article-level metadata, one entitled `issn_success.json`. These dicts will be needed by script 8 to add all the metadata to the appropriate articles. If everything goes well, a third dictionary,  `issn_errors.json` will be empty. 


Script 8 : 8_update_trees.py
Like its name suggests, this script will update the XML trees : new `teiHeader` elements will be created with metadata from the dictionaries built in script7. <p> elements that share a common type get grouped into new <div> elements, so that rather than having no <div> and 5 <p type="Introduction">, the new <div> parent of these <p> elements gets this attribute : <div type="Introduction">.

Script 9: 


Helper scripts:
zip_here.py : a CLI helper to compress files/folders ; this is useful for both archival/backup purposes as well as for transfer to/from remote servers with big GPUs. 
It functions in one of 3 modes.
In monolithic mode, (specify `--mode mono`) it takes a folder and makes a single zip containing everything in the specified folder and its descendants. As it's writing to a single zip, it's not the sort of process than can be parallelised easily in py.
In individual mode, (specify `--mode indiv`), it takes a folder and for each file in the folder, compresses it to its own zip file. Use `--n_procs N` followed by an integer to request N workers to run in parallel.
In subfolder mode, (specify `--mode subfolder`), each of the subfolders is examined and files with the specified extension are added to a zip file for that folder : thus with 41 chunks in the Elsevier OA corpus, we can easily get 41 zip files, each containing 1000 files to feed to a server with a big enough GPU.
