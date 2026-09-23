Building corpus out of the Elsevier OA-BY-CC dataset

The Elsevier OA-BY-CC Corpus consists of just over 40,000 documents, and is available from `https://elsevier.digitalcommonsdata.com/datasets/zm33cdndxs/3`

(recommendation : do this in a fresh venv ; I called mine elsevier_env, and had a different dir where all the data lived)
Script 1 : 1_elsevier_mover.py
Once the source file is downloaded and unzipped, the main directory of json files contains all the data we want, but with 40000 files in one folder, it's not very manageable. 
This script divides the files into chunks, and places them in subfolders to make things easier from a human standpoint as well as organisationally - we can send batches of files to process with, for example - as well as reducing the strain on the OS, keeping track of tens/hundreds of thousands of files within a single folder - that's not precisely what most file explorers are built for.
Example usage :
`python /elsevier_env/1_make_subfolders.py --source /data/elsevier_oa/data_step0 --chunks 1000 --extension json --verbose`

`--source` is the path to the folder that contains 40000 jsons : here's it's the folder `data_step0` in  `elsevier_oa` which is in the `data` directory. New folders will be made inside it,
`--chunks` is the number of files to put in each chunk - here it's set to 1000
`--extension json` specifies we're looking only for files with the `json` extension ; the `.` before the extension is not needed
`--verbose` will tell the script to print details of each individual file move to the console

Script 2 : 2_json_to_xml.py
This script transforms the json source documents into TEI-compatible XML documents, preserving the body of the texts as well as hierarchical information - this sentence is part of this paragraph called "Introduction to exciting topic number 1"
Example usage:
`python /elsevier_env/2_json_to_xml.py --source_dir /data/elsevier_oa/data_step0 --output_dir /data/elsevier_oa/data_step1`
`--source_dir` is the path to the folder that contains the newly-made subfolders which contain 40000 jsons : here's it's still the folder `data_step0` in  `elsevier_oa` which is in the `data` directory. 
`--output_dir` is the path to a new folder where output XML files will be saved, reproducing the folder organisation of `data_step1`.


Script 3 : 3_tokeniser.py
This script performs tokenisation on the paragraphs present in the json documents, adding a <w> element with an ID for each token recognised. The bulk of tokens are like the bulk of words in English: spaces and punctuation form their boundaries, but special cases such as possessive apostrophes, Latin abbreviations and similar items are recognised as single tokens. 
Example usage:
`python /elsevier_env/3_tokeniser.py --inputPath /data/elsevier_oa/data_step1 --output_path /data/elsevier_oa/data_step2 --nprocs 4 -join_hyphen True --lang en`
`--source_dir` is the path to the folder that contains the newly-made subfolders which contain 40000 xml : 
`--output_path` is the path to a new folder where tokenised XML files will be saved, reproducing the folder organisation of `data_step1`.
`--nprocs` specifies the number of workers for parallel processing, each worker processing files independently. Specify an integer to request this number of workers. The number of workers created will be the smallest of three values : the number of workers requested, the number of files to process, and the number of CPU cores.
`--lang en` specifies the language as English, so English rules for tokenisation will be applied: `e.g.`  get recognised as 1 token in English,  but this isn't the case in French, but for both, `et al.` should be 1 token.
      
Script 4: 4_sentenciser.py
This script might seem to have put the cart before the horse, defining tokens before defining where the sentences containing these tokens start and end. However, given the paragraphs are reliable start-end points for sentences, this script takes the approach that the tokens are present and some of them need to get a extra label « The end of the sentence is here » that we recognise when we see a full stop. This script applies a series of logical rules to determine where the label should be placed, as for example, not all `.` indicate the end of sentences: 1.2 can be left as a non-sentence boundary by checking whether the preceding/following token is a number, if we see a title such as `Mr.`, again, the full stop doesn't indicate a sentence boundary.
Once sentences have been identified, the results are exported to a new XML file : this contains everything, and is the reference file. A conll file is also produced, this can be easily ingested by Stanza to do POS tagging, lemmatisation, morphological feature analysis and dependency parsing. 
Example usage : 
`python /elsevier_env/4_sentenciser.py --source_dir /data/elsevier_oa/data_step2 --output_dir /data/elsevier_oa/data_step3 --n_procs 4 -join_hyphen True --lang en`
`--source_dir` is the path to the parent folder that contains the subfolders which contain 40000 tokenised XML files.
`--output_dir` is the path to a new folder where sentencised XML files will be saved, reproducing the folder organisation of `data_step2`.
`--n_procs` specifies the number of workers for parallel processing, each worker processing files independently. Specify an integer to request this number of workers. The number of workers created will be the smallest of three values : the number of workers requested, the number of files to process, and the number of CPU cores.
`--lang en` specifies the language as English, so English rules for sentence boundary recognition will be applied: `Mr. X`  shouldn't be the end of a sentence,  but if it's French, we need to look for `M. X`,  `MM. X`, `Mme. X` etc as these aren't sentences boundaries either.
`--offset` can be set to the number from which sentences will be numbered : if you want to number from 314, use `--offset 314`
`--chunksize` can be set to an integer to define the number of files each worker should read in a batch, rather than reading each file individually

Script 5: 5_reinsert.py
This script takes the .conll files produced by Stanza, and inserts these annotations into the XML file created
Example usage : 
`python /elsevier_env/5_reinsert.py --conll_source /data/elsevier_oa/data_step4/03 --xml_dirname data_step3 --xml_output data_step5 --id_attrib s_id --n_procs 4 --sibling`
`--conll_source` is the full path to a folder that contains the tagged conll files exported by Stanza. : here, it's subfolder 03 in the data_step4 dir.
`--xml_dirname` is the the name (just the name, not the path) to the folder that contains the sentencised XML files exported along with the untagged conll files. Here, it's the subfolder `data_step3`. No need to specify the subfolder, the script will work this out based on the input filter.
`--xml_output` is the name of a new folder where we want to export the XML with the conll tags : here, we're exporting to the folder `data_step5` ; again, subfolders will be handled automatically..
`--n_procs` specifies the number of workers for parallel processing, each worker processing files independently. Specify an integer to request this number of workers. The number of workers created will be the smallest of three values : the number of workers requested, the number of files to process, and the number of CPU cores.
`--id_attrib` Specify the attribute into which sentence IDs were placed ; default is `s_id` ; if this gives no results, `id` will be tried before abandoning.
`--sibling` can be added to change the default behaviour. Without this flag, only the  subfolder specified in `--conll_source` will be processed : in this case, `data_step4/03/` ; if `--sibling` is added, the script will iterate over all folders which are siblings of /03/ : ie it will look for all directories which are children of /data_step4/ and find /01/, /02/, /03… etc and attempt to process these, preserving the subfolder organisation in the new `xml_output` directory.



Script 7: 7_issn_querying.py
This script performs two tasks. The first is to build a dictionary of metadata from all the source json files processed in Scripts 1-2. This brings all the article-level metadata into a single dictionary, which Script 8 will use. The second part involves obtaining journal-level metadata. To do this, the script queries the Elsevier API to get information on the journals in question : by looking up the ISSN for each journal, a dictionary can be built of ISSNs, journal titles and their subject areas.
`python /elsevier_env/7_issn_querying.py --json_source /data/elsevier_oa/data_step0 --delay 30 --buffer 10`
`--json_source` is the path to the parent directory from step1 with all the json files : here, it's data_step0
`--delay` is an integer, the number of seconds to pause between API calls.
`--buffer` is an integer, specifying the number of responses to hold in a buffer before appending the contents of the buffer to the file on disk and clearing the buffer.


Note that use of this API requires a free API key, which can be obtained from `https://dev.elsevier.com`. Among the conditions of using the API are that usage is research based and in accordance with the terms of use, notably the rate at which requests are sent : the more polite the script is in terms of delay between requests, the more likely it is that things will go well : the delay argument can be used to change this from the default : if only 10 requests are to be sent, a shorter delay may be appropriate, but for thousands of requests, carefully consider the usage quotas detailed here `https://dev.elsevier.com/api_key_settings.html`.
Once an API key has been obtained, it can be saved in a file named 'secrets.env' and placed in the same directory as `7_issn_querying.py` - this way the script will read the key directly from the file and insert it where necessary without a human copy-paste being added to the script itself.
When this script is complete, 2 dictionaries should have been created : one of article-level metadata, one entitled `issn_success.json`. These dicts will be needed by script 8 to add all the metadata to the appropriate articles. If everything goes well, a third dictionary,  `issn_errors.json` will be empty. 


Script 8 : 8_update_trees.py
Like its name suggests, this script will update the XML trees : new `teiHeader` elements will be created with metadata from the dictionaries built in script7. `<p>` elements that share a common type get grouped into new `<div>` elements, so that rather than having no `<div>` and 5 `<p type="Introduction">`, the new `<div>` parent of these `<p>` elements gets this attribute : `<div type="Introduction">`.
Example usage: 
`python3 /elsevier_env/8_update_trees.py --source /data/elsevier_oa/data_step5/03 --output /data/elsevier_oa/data_step6 --issn /data/elsevier_oa/data_step0/issn_success_titles.json -a /data/elsevier_oa/data_step0/metadata_dict.json --n_procs 7 --sibling --extension .xml`
`--source` This is the path to the source folder of XML files with tags newly-added to the XML : here, it's `/data/elsevier_oa/data_step5`
`--output` This is where this script will write its output files : `/data/elsevier_oa/data_step6 `
`--issn` Path to the dictionary of ISSN-title-subject information built in script 7. : Here, it's `/data/elsevier_oa/data_step0/issn_success_titles.json`
`-a` Path to the dictionary of article level metadata, build from the source JSONs in step7: here, this file is found at `/data/elsevier_oa/data_step0/metadata_dict.json`
`--n_procs` specifies the number of workers for parallel processing, each worker processing files independently. Specify an integer to request this number of workers. The number of workers created will be the smallest of three values : the number of workers requested, the number of files to process, and the number of CPU cores.
`--extension` This tells the script to look for files with the `.xml` extension ; no need to add the `.`
`--sibling` can be added to change the default behaviour. Without this flag, only the  subfolder specified in `--source` will be processed : in this case, `data_step5/03/` ; if `--sibling` is added, the script will iterate over all folders which are siblings of /03/ : ie it will look for all directories which are children of /data_step5/ and find /01/, /02/, /03… etc and attempt to process these, preserving the subfolder organisation in the new `output` directory.

        

Script 9: coming soon


Helper scripts:
zip_here.py : a CLI helper to compress files/folders ; this is useful for both archival/backup purposes as well as for transfer to/from remote servers with big GPUs. 
It functions in one of 3 modes.
In monolithic mode, (specify `--mode mono`) it takes a folder and makes a single zip containing everything in the specified folder and its descendants. As it's writing to a single zip, it's not the sort of process than can be parallelised easily in py.
In individual mode, (specify `--mode indiv`), it takes a folder and for each file in the folder, compresses it to its own zip file. Use `--n_procs N` followed by an integer to request N workers to run in parallel.
In subfolder mode, (specify `--mode subfolder`), each of the subfolders is examined and files with the specified extension are added to a zip file for that folder : thus with 41 chunks in the Elsevier OA corpus, we can easily get 41 zip files, each containing 1000 files to feed to a server with a big enough GPU.
