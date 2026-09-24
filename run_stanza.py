import glob
import time
import argparse
import os
import stanza

from stanza.utils.conll import CoNLL
from tqdm import tqdm

def write_annotations_to_file(conll_output, input_file, myletter, lang):
	'''
	Write the annotated document object to file
	
	Inputs: 
		conll_output : CoNLL Document : a conll document object containing the annotated documents
		input_file : str: absolute path to the file taken as input. This will be used to create the output file name and path
	Returns:
		no return object : a file is written to the specified location and confirmation message printed to the console
	'''
	## make name of output file and check that the folder containing it exists, creating it if not
	output_file = input_file.replace('conll',f'{myletter}_{lang}_OUT.conll').replace('tag_input','tag_output')
	check_outputpath(output_file)
	
	# make a string from the conll_output and write it
	string = "{:C}".format(conll_output)
	with open(output_file, 'w', encoding='UTF-8') as w:
		_ = w.write(string)
	print(f":::::			Exported to {output_file}")
	

def write_log(log_entry, launch_time):
	'''
	Simple helper to write-append a log entry to the logfile
	Inputs:
		log_entry : str : the string to write to the logfile
		launch_time : int : unix time at which the parsing process was launched
	Returns:
		no return object : a string is write-appended to a file
	'''
	log_file_path = f'/home/username/tag_output/{launch_time}_log.txt'
	with open(log_file_path ,'a', encoding='UTF-8') as k:
		_ = k.write(log_entry)

def check_outputpath(output_file):
	'''
	Helper to ensure that when an output file is to be printed to output_file in a directory, the directory that is the immediate ascendent of output_file exists, creating it if not.
	Inputs : 
		output_file : str : absolute path to the outputfile to be written
	Returns : 
		no return object, a folder will be created if necessary
	'''
	target_path = os.path.dirname(output_file)
	if os.path.exists(target_path) is False:
		os.mkdir(target_path)


def set_batch_sizes(my_size):
	'''
	Set batch sizes for Stanza processing
	Inputs :
		my_size : int, float or string : a number to be multiplied by 2e10 to define batch sizes for Stanza processing.
	
	Notes:
	0. my_size is always sent to a float before all multiplications. It is after all multiplications that results are coerced to integers.
	1. All batch sizes  [mwt_batch_size, pos_batch_size, lemma_batch_size, depparse_batch_size and depparse_second_batch_size] will be set to a common value, value1.
	2. The only batch given a different size is pos_batch_maximum_tokens, which in the defaults has a value 16x that of the other batches. This function thus preserves that geometry.
	'''

	x = float(my_size)
	value_1 = x * 1024
	value_2 = x * 1024 *16
	value_1 = int(value_1)
	value_2 = int(value_2)	
	mwt_batch_size = value_1
	pos_batch_size=value_1
	lemma_batch_size=value_1
	depparse_batch_size=value_1
	depparse_second_batch_size=value_1
	pos_batch_maximum_tokens=value_2
	return mwt_batch_size, pos_batch_size, lemma_batch_size, depparse_batch_size, depparse_second_batch_size, pos_batch_maximum_tokens

def load_nlp(lang, my_size, depparseOnly):
	'''
	TO DO :: would defining nlp object from dictionaries or dict comprehensions be tidier and or easier to read?
	Load specific Stanza pipelines for pre-configured languages and processing needs
	Inputs :
		lang : language code (2 or three lowercase letters) to be passed to the `lang` argument in stanza.Pipeline. Also used as an exclusion value for Ancient Greek, for which DepparseOnly was not necessary
		my_size : batch size to be passed to `set_batch_sizes` : input is cast to a float to allow for decimals to be entered easily
		depparseOnly : T/F value to indicate whether to only dependency parsing only. Only `T` is recognised, all other input is interpreted as equivalent of `F`
			If depparseOnly is T, input needs to be well-formatted conll with tokens, token ids (column 1), tokens (column 2), lemmas (column 3) and POS tags (column 4) as a minimum. FEATS and cols 9-10 can be present. Any values for HEAD, DEPPREL will be ignored.
			If depparseOnly is False, pretokenised, pre-sentencised well-formatted conll is is required.
	Returns :
		nlp : an nlp object == stanza Pipeline object is returned.
	'''
	if lang != "grc":
		mwt_batch_size, pos_batch_size, lemma_batch_size, depparse_batch_size, depparse_second_batch_size, pos_batch_maximum_tokens = set_batch_sizes(my_size)
	
	if depparseOnly =="T":
		if lang =="fr":
			nlp = stanza.Pipeline(lang="fr", package='gsd', processors="depparse", depparse_pretagged=True,  depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
		if lang =="fro":
			nlp = stanza.Pipeline(lang="fro", processors="depparse", depparse_pretagged=True,  depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
		if lang =="frm":
			nlp = stanza.Pipeline(lang="frm", processors="depparse", depparse_pretagged=True,  depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
		if lang =="en":
			nlp = stanza.Pipeline(lang="en", package='ewt', processors="depparse", depparse_pretagged=True,  depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
	else:
	
		if lang =="ang":
			nlp = stanza.Pipeline(lang="ang", package='nerthus', processors="tokenize,pos,lemma,depparse", tokenize_pretokenized=True, tokenize_ssplit=True, mwt_batch_size = mwt_batch_size, pos_batch_size=pos_batch_size, pos_batch_maximum_tokens=pos_batch_maximum_tokens, lemma_batch_size=lemma_batch_size, depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
		if lang =="grc":
			nlp = stanza.Pipeline(lang="grc")
		if lang =="it":
			nlp = stanza.Pipeline(lang="it", package='isdt', processors="tokenize,mwt,pos,lemma,depparse", tokenize_pretokenized=True, tokenize_ssplit=True, mwt_batch_size = mwt_batch_size, pos_batch_size=pos_batch_size, pos_batch_maximum_tokens=pos_batch_maximum_tokens, lemma_batch_size=lemma_batch_size, depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)

		if lang =="de":
			nlp = stanza.Pipeline(lang="de", package='gsd', processors="tokenize,mwt,pos,lemma,depparse", tokenize_pretokenized=True, tokenize_ssplit=True, mwt_batch_size = mwt_batch_size, pos_batch_size=pos_batch_size, pos_batch_maximum_tokens=pos_batch_maximum_tokens, lemma_batch_size=lemma_batch_size, depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
		if lang =="es":
			nlp = stanza.Pipeline(lang="es",  processors="tokenize,mwt,pos,lemma,depparse", tokenize_pretokenized=True, tokenize_ssplit=True, mwt_batch_size = mwt_batch_size, pos_batch_size=pos_batch_size, pos_batch_maximum_tokens=pos_batch_maximum_tokens, lemma_batch_size=lemma_batch_size, depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
		if lang =="fr":
			nlp = stanza.Pipeline(lang="fr", package='gsd', processors="tokenize,mwt,pos,lemma,depparse", tokenize_pretokenized=True, tokenize_ssplit=True, mwt_batch_size = mwt_batch_size, pos_batch_size=pos_batch_size, pos_batch_maximum_tokens=pos_batch_maximum_tokens, lemma_batch_size=lemma_batch_size, depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
		if lang =="fro":
			nlp = stanza.Pipeline(lang="fro",  processors="tokenize,mwt,pos,lemma,depparse", tokenize_pretokenized=True, tokenize_ssplit=True, mwt_batch_size = mwt_batch_size, pos_batch_size=pos_batch_size, pos_batch_maximum_tokens=pos_batch_maximum_tokens, lemma_batch_size=lemma_batch_size, depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
		if lang =="en":
			nlp = stanza.Pipeline(lang="en", package='ewt', processors="tokenize,mwt,pos,lemma,depparse", tokenize_pretokenized=True, tokenize_ssplit=True, mwt_batch_size = mwt_batch_size, pos_batch_size=pos_batch_size, pos_batch_maximum_tokens=pos_batch_maximum_tokens, lemma_batch_size=lemma_batch_size, depparse_batch_size=depparse_batch_size, depparse_second_batch_size=depparse_second_batch_size)
	return nlp
	
def run_parsing(input_files, lang, my_size, depparseOnly):
	'''
	Parse the files with Stanza
	Inputs:
		input_files : list : a list of files to process
		lang : string : the 2-3 letter code of the language of the files to be processed as Stanza expects it
		my_size : int : an integer used to define batch sizes for the processors in the NLP pipeline
		depparseOnly : string/bool : string (T, True, F, False) or boolean (True, False) determining which processors in the NLP pipeline to call. If True or T, only the dependency parser will be called. For processing to be successful, input data needs to be well-formatted conll with at least POS, LEM annotations present.
	
	'''

	# check we have files to process
	print(f'{len(input_files)} files found')

	if len(input_files)>0:
		# prepare logs
		log, error_log =[], []
		launch_time = time.time()
		log_file_path = f'/home/username/tag_output/{launch_time}_log.txt'

		# wordlimit after which a sentence is deemed 'too long' and yield useless dependency trees, due to length, sentence segmentation errors or repeating punctuation
		limit = 1600
	
		## additional option to allow for another level of nesting or extending of output path. Default value is underscore, which may cause errors in downstream scripts relying on string.replace() methods looking for __
		myletter="_" 
	
		# instantiate the nlp object and print batch sizes to the console
		nlp = load_nlp(lang, my_size, depparseOnly)
		for name, processor in nlp.processors.items(): 
			for key, value in processor.config.items():
				if "batch" in key:
					print(f'{name}\t{key}\t{value}')

		## make tidy list of batch sizes to insert into log
		batch_sizes= [f'{name}\t{key}\t{value}' for key,value in processor.config.items() if 'batch' in key for name, processor in nlp.processors.items()]
		batch_sizes_tidy = "\t".join([chunk for chunk in batch_sizes])

	
		with open(log_file_path ,'a', encoding='UTF-8') as k:
			for f, input_file	in tqdm(enumerate (input_files)):
				try:
					## load input file and check that no sentence has length exceeding `max_len` ; if so, add to log and skip file
					starttime = time.time()
					source_doc = CoNLL.conll2doc(input_file)
					max_len = max([len(sent.tokens) for sent in source_doc.sentences])
					if max_len >= limit:
						report_string = f'\tSkipping {input_file} : max_len exceeded:: {max_len}\n'
						write_log(str(report_string), launch_time)
		
					if max_len < limit:
						## print the number of tokens in the doc to the console to allow for guesstimate of how long the doc will take to process, then annotate it
						tokens = source_doc.num_tokens
						print(f"\tProcessing {input_file} :: {tokens} tokens")

						## run the nlp pipeline on the document
						annotated_document =nlp(source_doc)
					
						## make name for output file explicitating that it's output, sending to appropriate output directory, checking that parent path exists, then write
						write_annotations_to_file(annotated_document, input_file, myletter, lang)
						source_new_name = input_file.replace('tag_input','tag_output')
						os.rename(input_file, source_new_name)

						## make reportstring, write to log
						report_string = f'{starttime}\t{time.time()}\t{tokens}\t{input_file}\t{batch_sizes_tidy}\n'
						write_log(str(report_string),launch_time)
				# log exceptions
				except Exception as e:
					report_string = f'{input_file}\t{e}\n'
					print(report_string)
					write_log(str(report_string), launch_time)		


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="parse conllised texts with LANGUAGE and specified batch SIZE")
	parser.add_argument("-size",help="integer value for size of batch : x for all except pos_batch_max_tokens == 16x" )
	parser.add_argument("-lang",help="language : use two/three letter codes that Stanza expects" )
	parser.add_argument("-depparseOnly",help="Run dependency parsing only" )
	parser.add_argument("--subf",help="path to subfolder to process",default='' )
	args = parser.parse_args()
	subf_name = args.subf
	if subf_name == '':
		input_files = sorted(glob.glob(f'/home/username/tag_input/*.conll'))
		if len(input_files) ==0:
			input_files = sorted(glob.glob(f'/home/username/tag_input/*.conllu'))
	if subf_name != '':
		input_files = sorted(glob.glob(f'/home/username/tag_input/{subf_name}/*.conll'))
		if len(input_files) ==0:
			input_files = sorted(glob.glob(f'/home/username/tag_input/{subf_name}/*.conllu'))
	my_size = str(args.size)
	lang = args.lang
	depparseOnly = args.depparseOnly
	run_parsing(input_files, lang, my_size, depparseOnly)
