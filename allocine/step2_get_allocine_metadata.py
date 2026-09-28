# -*- coding: utf-8 -*-
"""Get film metadata from the Allocine website"""
import argparse
import time
from typing import Any
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from lxml import etree
from tqdm import tqdm


def make_url_set(source_file: str):
    """Reads URL fragments from a file and constructs a list of unique full URLs.

    Args:
        source_file (str): The path to the text file containing URL paths (one per line).

    Returns:
        list[str]: A list of unique full URLs prepended with the Allociné base domain.
    """
    header = 'http://www.allocine.fr'
    input_urls = []
    with open(source_file, 'r', encoding='utf-8') as k:
        for line in k.readlines():
            full_url = f'{header}{line.replace("\n","")}'
            input_urls.append(full_url)
    url_list = list(set(input_urls))
    print(f"URL set made : {len(url_list)} items")

    return url_list

def make_soup(response: requests.Response):
    """Parses the HTML content of a response object into a BeautifulSoup object.

    Args:
        response (requests.Response): The response object returned from a requests call.

    Returns:
        bs4.BeautifulSoup: The parsed HTML document for further scraping.
    """
    html_response = response.content
    soup = BeautifulSoup(html_response, 'html.parser')
    return soup

def get_duration(soup: BeautifulSoup, release_date: str):
    """Extracts the film duration from the page soup by filtering out noise.

    Args:
        soup (bs4.BeautifulSoup): The parsed HTML of the film page.
        release_date (str): The release date string to be excluded from the extracted text.

    Returns:
        str | None: The film duration string if found, otherwise None.
    """
    div = soup.select_one("div.meta-body-item.meta-body-info")
    film_duration = next(
        (x for x in div.stripped_strings if x not in
        ['', '|', 'sur', 'en salle', 'genre', release_date]
        ),
        None
    )
    return film_duration

def get_director(soup: BeautifulSoup):
    """Extracts the director's name from the page soup.

    Args:
        soup (bs4.BeautifulSoup): The parsed HTML of the film page.

    Returns:
        str: The name of the director, or 'UNK' if the director information 
            cannot be found.
    """
    div = soup.select_one("div.meta-body-item.meta-body-direction.meta-body-oneline")

    if div:
        # Use stripped_strings to get all text, already stripped
        director = next(
            (text for text in div.stripped_strings if text not in ('', 'De')),
            None
        )
    else:
        director = 'UNK'
    return director

def get_rating_data(soup: BeautifulSoup):
    """Extracts press and spectator ratings from the film page.

    Args:
        soup (bs4.BeautifulSoup): The parsed HTML of the film page.

    Returns:
        tuple[str, str]: A tuple containing (press_rating, spect_rating). 
            Returns 'UNK' for either value if the rating is not found.
    """
    ratings: dict[str, str] = {}
    for item in soup.select('div.rating-item-content'):
        label_el = item.select_one('span')
        note_el = item.select_one('span.stareval-note')
        if label_el and note_el:
            ratings[label_el.get_text(strip=True)] = note_el.get_text(strip=True)

    press_rating = ratings.get("Presse", "UNK")
    spect_rating = ratings.get("Spectateurs", "UNK")

    return press_rating, spect_rating

def get_release_date(soup: BeautifulSoup):
    """Extracts the release date of the film.

    Args:
        soup (bs4.BeautifulSoup): The parsed HTML of the film page.

    Returns:
        str: The release date string, or 'UNK' if the date is missing or 
            cannot be found.
    """
    try:
        temp_date = soup.select_one("span.date").get_text(strip=True)
    except Exception:
        temp_date = "UNK"

    if temp_date == "":
        temp_date = "UNK"

    output_date = temp_date
    return output_date

def get_genre(soup: BeautifulSoup):
    """Extracts the film genre from the movie page.

    Args:
        soup (bs4.BeautifulSoup): The parsed HTML of the film page.

    Returns:
        str: The genre name (with 'Films ' prefix removed), or 'UNK' 
            if the genre is not found.
    """
    try:
        genre = soup.select_one('a[href*="/films/genre-"]').get_text().replace('Films ', '')
    except Exception:
        genre = "UNK"
    return genre

def process_url(response: requests.Response) -> etree._Element:
    """Orchestrates the extraction of movie metadata and packages it into an XML element.

    This function coordinates several helper functions to scrape the title, 
    release date, genre, duration, director, and ratings from a movie page, 
    then stores these values as attributes in an lxml Element.

    Args:
        response (requests.Response): The response object containing the page HTML.

    Returns:
        lxml.etree._Element: An XML element named <metadata> containing all 
            extracted movie details as attributes.
    """
    soup = make_soup(response)
    title = soup.select_one(".titlebar-title.titlebar-title-xl").get_text(strip=True)
    release_date = get_release_date(soup)
    genre = get_genre(soup)
    duration = get_duration(soup, release_date)
    director = get_director(soup)
    press_rating, spect_rating = get_rating_data(soup)

    meta_element = etree.Element("metadata")
    meta_element.set("url", str(response.url))
    meta_element.set("title", str(title))
    meta_element.set("release_date", str(release_date))
    meta_element.set("genre", str(genre))
    meta_element.set("duration", str(duration))
    meta_element.set("director", str(director))
    meta_element.set("press_rating", str(press_rating))
    meta_element.set("spect_rating", str(spect_rating))

    return meta_element



def make_error_el(url: str, **attrs: Any) -> etree._Element:
    """Build an <error> XML element describing a failed request.

    The element always carries a ``url`` attribute. Any additional
    keyword arguments are added as further attributes, so callers can
    record whatever describes the failure (status code, exception text,
    and so on).

    Args:
        url: The URL that failed to fetch or process.
        **attrs: Extra attributes to set on the element, e.g.
            ``status_code=404`` or ``exception="timeout"``. Values are
            converted to strings, since XML attributes must be strings.

    Returns:
        An ``<error>`` element with ``url`` and any extra attributes set.

    Example:
        >>> el = make_error_el("https://example.com", status_code=404)
        >>> el.get("status_code")
        '404'
    """
    el = etree.Element("error")
    el.set("url", str(url))
    for key, value in attrs.items():
        el.set(key, str(value))
    return el


def get_metas_from_urls(url_list:(list[str]), output_dir: str, delay:float=5.0, offset:int=0):
    """Fetches movie metadata from a list of URLs and saves progress to XML files.

    This function iterates through a set of URLs, requests the page content, 
    and extracts metadata using `process_url`. It handles HTTP errors by 
    recording them in the XML tree. To prevent server blocking, it implements 
    a request delay. The progress is saved to the output directory every 50 
    items and once more after the final item is processed.

    Args:
        url_list (list[str]): A list of full URLs to be scraped.
        output_dir (str): The directory path where XML snapshots will be saved.
        delay (float, optional): Seconds to wait between requests. Defaults to 5.0.
        offset (int, optional): The index to start from in the url_list. Defaults to 0.

    Returns:
        None, XML file written
    """
    if offset > 0:
        my_urls = url_list[offset:]
    else:
        my_urls = url_list

    full_tree = etree.Element('xml')

    # We use enumerate(my_urls, 1) so that 'u' starts at 1 for easier modulo math
    for u, url in tqdm(enumerate(my_urls, 1)):
        try:
            response = requests.request("GET", url, timeout=20)
            if response.status_code == 200:
                meta_element = process_url(response)
                full_tree.append(meta_element)
            else:
                err_el = make_error_el(url, exception="statuscode")
                err_el.set("status_code", str(response.status_code))
                full_tree.append(err_el)

        except requests.exceptions.Timeout:
            err_el = make_error_el(url, exception="timeout")
            full_tree.append(err_el)

        except Exception as e:
            # Catch other errors
            err_el = make_error_el(url, exception=str(e))
            full_tree.append(err_el)
            err_el = etree.Element("error")
            err_el.set("url", str(url))
            err_el.set("exception", str(e))
            full_tree.append(err_el)

        time.sleep(delay)  # wait x seconds before next request

        # Save every 50 items
        if u % 50 == 0:
            output_path_full = Path(output_dir) / f'allocine_metas_{str(u).zfill(6)}.xml'
            outtree = etree.ElementTree(full_tree)
            outtree.write(
                output_path_full,
                encoding='UTF-8',
                pretty_print=True,
                xml_declaration=True
                )

    # FINAL SAVE: Process the last remaining items (the final chunk)
    # This ensures that if you have 123 items, the last 23 are saved.
    output_path_final = Path(output_dir) / f'allocine_metas_{str(len(my_urls)).zfill(6)}_final.xml'
    outtree = etree.ElementTree(full_tree)
    outtree.write(output_path_final, encoding='UTF-8', pretty_print=True, xml_declaration=True)

if __name__ == "__main__":
    # 1. Initialize the ArgumentParser
    parser = argparse.ArgumentParser(
        description="Scrape movie metadata from Allociné URLs and save to XML."
    )

    # 2. Define Required Arguments
    parser.add_argument(
        "--source_file",
        type=str,
        required=True,
        help="Path to the text file containing URL fragments (one per line)."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        required=True,
        help="Directory where the resulting XML files will be saved."
    )

    # 3. Define Optional Arguments
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Seconds to wait between requests to avoid being blocked (default: 5.0)."
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Index to start from in the URL list (useful for resuming crashes) (default: 0)."
    )

    # 4. Parse the arguments from the command line
    args = parser.parse_args()

    # Ensure output directory exists
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        print(f"Step 1: Loading URLs from {args.source_file}...")
        arg_url_list = make_url_set(args.source_file)
        print(f"Step 2: Starting scrape with offset {args.offset} and delay {args.delay}s...")
        # This will call the function we just wrote
        get_metas_from_urls(
            arg_url_list,
            args.output_dir,
            args.delay,
            args.offset
        )

        print("Process complete. Final XML tree generated.")

    except FileNotFoundError:
        print(f"Error: The file {args.source_file} was not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
