"""
Ramayana Sanskrit Text Web Scraper.

This module provides functionality to scrape Sanskrit verses from various websites,
specifically targeting Ramayana texts. It can extract Sanskrit text from modern
websites as well as older sites using framesets.

Features:
- Scrape single pages or entire chapter collections
- Extract Sanskrit verses using selectors or Devanagari character detection
- Fix encoding issues in Sanskrit text
- Save output in multiple formats (JSON, CSV, TXT)
- Respects robots.txt and implements polite scraping practices
- Session-based requests with retry logic for improved reliability

Usage:
    python web_scraper.py [URL] [options]

Example:
    python web_scraper.py http://example.com/ramayana --all-chapters -f json -d ./output
"""

import argparse
import csv
import json
import logging
import os
import random
import re
import time
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Constants
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3
BACKOFF_FACTOR = 0.3
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 11.5; rv:90.0) Gecko/20100101 Firefox/90.0",
]


class TimeoutHTTPAdapter(HTTPAdapter):
    """
    HTTP adapter that adds timeout capabilities to requests.

    This adapter ensures that all requests have a timeout specified,
    which helps prevent hanging connections when a server is unresponsive.

    Attributes:
        timeout (int): Default timeout in seconds for requests.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the adapter with optional timeout parameter.

        Args:
            *args: Variable length argument list passed to HTTPAdapter.
            **kwargs: Arbitrary keyword arguments passed to HTTPAdapter.
                timeout (int, optional): Default timeout for requests in seconds.
                    Defaults to DEFAULT_TIMEOUT if not provided.
        """
        self.timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT)
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        """
        Send a request with a default timeout if none is specified.

        Args:
            request: The prepared request to send.
            **kwargs: Arbitrary keyword arguments passed to HTTPAdapter's send method.

        Returns:
            requests.Response: The response from the server.
        """
        kwargs["timeout"] = kwargs.get("timeout", self.timeout)
        return super().send(request, **kwargs)


def create_session(timeout: int = DEFAULT_TIMEOUT) -> requests.Session:
    """
    Create a requests session with retry capabilities and timeout.

    This function creates a session that automatically retries failed requests
    with exponential backoff, handles timeouts, and sets common headers.

    Args:
        timeout (int, optional): Default timeout in seconds. Defaults to DEFAULT_TIMEOUT.

    Returns:
        requests.Session: Configured session object with retry capabilities.

    Example:
        >>> session = create_session(timeout=15)
        >>> response = session.get('https://example.com')
    """
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = TimeoutHTTPAdapter(max_retries=retry_strategy, timeout=timeout)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml",
            "Accept-Language": "en-US,en;q=0.5",
        }
    )
    return session


def check_robots_txt(url: str, user_agent: str) -> bool:
    """
    Check if scraping is allowed according to robots.txt.

    Args:
        url (str): The URL to check for permission to scrape.
        user_agent (str): User agent to check permissions for.

    Returns:
        bool: True if scraping is allowed, False otherwise.

    Note:
        If robots.txt cannot be read or parsed, this function assumes
        scraping is allowed but logs a warning.
    """
    parsed_url = urlparse(url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"

    rp = RobotFileParser()
    rp.set_url(robots_url)

    try:
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception as e:
        logging.warning(f"Error reading robots.txt: {e}. Assuming scraping is allowed.")
        return True


def extract_sanskrit_verses(soup: BeautifulSoup) -> List[str]:
    """
    Extract Sanskrit verses from a BeautifulSoup object.

    This function attempts to extract Sanskrit verses using a specific CSS selector.
    If no verses are found, it falls back to searching for paragraphs containing
    Devanagari characters.

    Args:
        soup (BeautifulSoup): Parsed HTML content to extract verses from.

    Returns:
        List[str]: List of extracted Sanskrit verses.

    Note:
        The function replaces <br> tags with newlines to preserve verse formatting.
        If no verses are found with the primary selector, it detects text containing
        Devanagari Unicode characters (0900-097F range).
    """
    verses = []

    # Try specific selector first
    elements = soup.select("p.SanSloka")
    logging.debug(f"Found {len(elements)} elements with selector 'p.SanSloka'")

    if elements:
        for element in elements:
            # Replace <br> tags with newlines
            for br in element.find_all("br"):
                br.replace_with("\n")

            verse_text = element.get_text(strip=True)
            if verse_text:
                verses.append(verse_text)

    # If no verses found, look for text with Devanagari characters
    if not verses:
        logging.debug("Looking for text containing Devanagari characters")
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            # Check for Devanagari Unicode range (0900-097F)
            if any(0x0900 <= ord(c) <= 0x097F for c in text):
                for br in p.find_all("br"):
                    br.replace_with("\n")
                verses.append(p.get_text(strip=True))

    return verses


def scrape_webpage(url: str, session: requests.Session) -> Optional[Dict[str, Any]]:
    """
    Scrape a webpage and extract Sanskrit verses.

    This function handles both modern websites and older sites using framesets.
    For framed pages, it recursively scrapes each frame for Sanskrit content.

    Args:
        url (str): URL of the webpage to scrape.
        session (requests.Session): Session object for making HTTP requests.

    Returns:
        Optional[Dict[str, Any]]: Dictionary with the URL and a list of extracted
            Sanskrit verses, or None if scraping fails.
            Format: {'url': str, 'sanskrit_verses': List[str]}

    Raises:
        No exceptions are raised; errors are logged and None is returned.
    """
    try:
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        logging.debug(
            f"Page title: {
                soup.title.string if soup.title else 'No title'}"
        )

        sanskrit_verses = []

        # Check for framesets (common in older websites)
        framesets = soup.find_all("frameset")
        if framesets:
            logging.info(
                f"Found {
                    len(framesets)} framesets - processing frames"
            )

            frames = soup.find_all("frame")
            for frame in frames:
                frame_src = frame.get("src")
                if not frame_src:
                    continue

                # Handle relative URLs
                if not frame_src.startswith("http"):
                    base_url = "{uri.scheme}://{uri.netloc}{uri.path}".format(
                        uri=urlparse(url)
                    )
                    if not base_url.endswith("/"):
                        base_url = base_url.rsplit("/", 1)[0] + "/"
                    frame_src = urljoin(base_url, frame_src)

                logging.debug(f"Processing frame: {frame_src}")

                # Add slight delay between frame requests
                time.sleep(random.uniform(0.5, 1.5))

                try:
                    frame_response = session.get(frame_src)
                    frame_soup = BeautifulSoup(frame_response.text, "html.parser")

                    frame_sanskrit = extract_sanskrit_verses(frame_soup)
                    if frame_sanskrit:
                        sanskrit_verses.extend(frame_sanskrit)
                except Exception as e:
                    logging.error(f"Error processing frame {frame_src}: {e}")
        else:
            # No framesets, process the page directly
            sanskrit_verses = extract_sanskrit_verses(soup)

        logging.info(f"Total Sanskrit verses found: {len(sanskrit_verses)}")
        return {"url": url, "sanskrit_verses": sanskrit_verses}

    except requests.RequestException as e:
        logging.error(f"Error fetching {url}: {e}")
        return None
    except Exception as e:
        logging.error(f"Error parsing {url}: {e}")
        return None


def fix_encoding(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fix encoding issues in Sanskrit verses.

    This function attempts to fix common encoding issues by re-encoding text,
    which is particularly useful for Sanskrit text that may have been incorrectly
    encoded or garbled during scraping.

    Args:
        data (Dict[str, Any]): Dictionary containing scraped data with 'sanskrit_verses' key.

    Returns:
        Dict[str, Any]: Dictionary with fixed encoding for Sanskrit verses.

    Note:
        This function preserves the original verse if encoding correction fails.
    """
    if "sanskrit_verses" not in data:
        logging.warning("No 'sanskrit_verses' key found in data")
        return data

    fixed_verses = []
    for verse in data["sanskrit_verses"]:
        try:
            # First encode as Latin-1, then decode properly as UTF-8
            fixed_verse = verse.encode("latin1").decode("utf-8")
            fixed_verses.append(fixed_verse)
        except Exception as e:
            logging.debug(f"Error fixing verse encoding: {e}")
            # Keep original if there's an error
            fixed_verses.append(verse)

    # Replace with fixed verses
    data["sanskrit_verses"] = fixed_verses
    return data


def save_data(data: Dict[str, Any], output_file: str, output_format: str) -> None:
    """
    Save data in the specified format (JSON, CSV, or TXT).

    Args:
        data (Dict[str, Any]): Dictionary containing the scraped data.
        output_file (str): Path where the output file should be saved.
        output_format (str): Format to save the data in ("json", "csv", or "txt").

    Note:
        - Creates any necessary directories in the output path.
        - For CSV output, flattens the data structure.
        - For TXT output, formats each verse with a number.
        - Uses UTF-8 encoding for all output formats.
    """
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    if output_format == "json":
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    elif output_format == "csv":
        flattened_data = [
            {"verse_number": i, "content": verse, "url": data["url"]}
            for i, verse in enumerate(data.get("sanskrit_verses", []), 1)
        ]

        if flattened_data:
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=flattened_data[0].keys())
                writer.writeheader()
                writer.writerows(flattened_data)
        else:
            logging.warning("No Sanskrit verses found to save to CSV")
            return
    elif output_format == "txt":
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Sanskrit verses from: {data['url']}\n\n")
            for i, verse in enumerate(data.get("sanskrit_verses", []), 1):
                f.write(f"Verse {i}:\n{verse}\n\n")

    logging.info(
        f"Sanskrit verses saved as {
            output_format.upper()} to {output_file}"
    )


def extract_chapter_links(soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
    """
    Extract chapter links from a contents page.

    This function looks for a table structure containing chapter titles and links.

    Args:
        soup (BeautifulSoup): Parsed HTML content to extract chapter links from.
        base_url (str): Base URL for resolving relative URLs.

    Returns:
        List[Dict[str, str]]: List of dictionaries with chapter information.
            Each dictionary contains:
            - 'url': The chapter URL (absolute)
            - 'title': The chapter title (cleaned for use in filenames)

    Note:
        The function cleans chapter titles by removing leading numbers,
        special characters, and formatting the text for use in filenames.
    """
    chapter_links = []
    rows = soup.find_all("tr")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 2:
            link_cell = cells[1]
            anchor = link_cell.find("a", href=True)

            if anchor and "href" in anchor.attrs:
                href = anchor["href"]

                # Get chapter title from first cell
                title_cell = cells[0]
                title_anchor = title_cell.find("a")
                title = (
                    title_anchor.get_text(strip=True)
                    if title_anchor
                    else title_cell.get_text(strip=True)
                )

                # Clean the title for filename
                # Remove leading numbers
                title = re.sub(r"^\d+\.?\s*", "", title)
                # Remove special characters
                title = re.sub(r"[^\w\s-]", "", title)
                title = title.strip().replace(" ", "_")[:50]  # Format and limit length

                # Handle relative URLs
                if not href.startswith("http"):
                    href = urljoin(base_url, href)

                chapter_links.append({"url": href, "title": title})
                logging.debug(f"Found chapter link: {title} -> {href}")

    return chapter_links


def process_chapter_links(
    chapter_links: List[Dict[str, str]],
    session: requests.Session,
    output_format: str,
    fix_encoding_flag: bool,
    output_dir: str = "ramayana_chapters",
) -> Dict[str, Any]:
    """
    Process a list of chapter links, scrape content, and save to files.

    Args:
        chapter_links (List[Dict[str, str]]): List of chapter dictionaries with 'url' and 'title' keys.
        session (requests.Session): Session object for making HTTP requests.
        output_format (str): Format to save the data in ("json", "csv", or "txt").
        fix_encoding_flag (bool): Whether to attempt to fix encoding issues.
        output_dir (str, optional): Directory to save output files to. Defaults to "ramayana_chapters".

    Returns:
        Dict[str, Any]: Results dictionary containing:
            - 'successful': Number of successfully processed chapters
            - 'failed': Number of failed chapters
            - 'chapters': List of successfully processed chapter information

    Note:
        - Creates the output directory if it doesn't exist.
        - Implements polite scraping with delays between requests.
        - Saves a summary of results as JSON in the output directory.
    """
    os.makedirs(output_dir, exist_ok=True)
    logging.info(f"Saving chapters to directory: {output_dir}")

    results = {"successful": 0, "failed": 0, "chapters": []}

    for i, chapter in enumerate(chapter_links, 1):
        logging.info(f"Processing chapter {i}/{len(chapter_links)}: {chapter['title']}")

        try:
            # Add delay with jitter to be respectful to the server
            time.sleep(1 + random.random())

            # Check if scraping is allowed
            if not check_robots_txt(chapter["url"], session.headers["User-Agent"]):
                logging.error(
                    f"Scraping not allowed for {
                        chapter['url']} according to robots.txt"
                )
                results["failed"] += 1
                continue

            # Scrape the webpage
            data = scrape_webpage(chapter["url"], session)

            if not data or not data.get("sanskrit_verses"):
                logging.warning(
                    f"No Sanskrit verses found in chapter {
                        chapter['title']}"
                )
                results["failed"] += 1
                continue

            # Fix encoding if requested
            if fix_encoding_flag:
                data = fix_encoding(data)

            # Add chapter information
            data["chapter_title"] = chapter["title"]
            data["chapter_number"] = i

            # Create filename and save
            filename_base = f"{i:02d}_{chapter['title']}"
            output_file = os.path.join(output_dir, f"{filename_base}.{output_format}")

            save_data(data, output_file, output_format)

            results["successful"] += 1
            results["chapters"].append(
                {
                    "title": chapter["title"],
                    "url": chapter["url"],
                    "file": output_file,
                    "verses_count": len(data.get("sanskrit_verses", [])),
                }
            )

        except Exception as e:
            logging.error(f"Error processing chapter {chapter['title']}: {e}")
            results["failed"] += 1

    # Save scraping summary
    summary_file = os.path.join(output_dir, "scraping_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_chapters": len(chapter_links),
                "successful": results["successful"],
                "failed": results["failed"],
                "chapters": results["chapters"],
            },
            f,
            ensure_ascii=False,
            indent=4,
        )

    logging.info(
        f"Scraping summary: {
            results['successful']} successful, {
            results['failed']} failed"
    )
    return results


def fix_file(filename: str, output: Optional[str] = None) -> None:
    """
    Fix encoding in an existing JSON file containing Sanskrit verses.

    Args:
        filename (str): Path to the JSON file to fix.
        output (Optional[str], optional): Output file path. If None, creates a new file
            with '_fixed' suffix in the same directory. Defaults to None.

    Note:
        This is useful for fixing previously scraped files with encoding issues.
    """
    try:
        logging.info(f"Loading JSON from {filename}")
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Fix encoding
        fixed_data = fix_encoding(data)

        # Determine output filename
        if not output:
            base_name = os.path.splitext(os.path.basename(filename))[0]
            output = f"{
                os.path.dirname(filename) or '.'}/{base_name}_fixed.json"

        # Save the fixed data
        save_data(fixed_data, output, "json")

    except Exception as e:
        logging.error(f"Error fixing file {filename}: {e}")


def process_all_chapters(args: argparse.Namespace, session: requests.Session) -> None:
    """
    Process all chapters from a contents page.

    Args:
        args (argparse.Namespace): Command line arguments.
        session (requests.Session): Session object for making HTTP requests.

    Note:
        This function handles the entire workflow for multi-chapter scraping:
        1. Fetches and parses the contents page
        2. Extracts chapter links
        3. Processes each chapter using process_chapter_links()
    """
    logging.info(f"Starting to scrape all chapters from {args.url}")

    # Check if scraping is allowed
    if not check_robots_txt(args.url, session.headers["User-Agent"]):
        logging.error(
            f"Scraping not allowed for {
                args.url} according to robots.txt"
        )
        return

    try:
        # Fetch and parse contents page
        response = session.get(args.url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract chapter links
        chapter_links = extract_chapter_links(soup, args.url)

        if not chapter_links:
            logging.error("No chapter links found on the contents page")
            return

        logging.info(f"Found {len(chapter_links)} chapters to scrape")

        # Process all chapters
        output_dir = args.directory if args.directory else "ramayana_chapters"
        process_chapter_links(
            chapter_links, session, args.format, args.fix_encoding, output_dir
        )

    except Exception as e:
        logging.error(f"Error processing contents page: {e}")


def process_single_page(args: argparse.Namespace, session: requests.Session) -> None:
    """
    Process a single webpage for Sanskrit verses.

    Args:
        args (argparse.Namespace): Command line arguments.
        session (requests.Session): Session object for making HTTP requests.

    Note:
        This function handles the entire workflow for single-page scraping:
        1. Checks if scraping is allowed
        2. Scrapes the webpage
        3. Processes encoding if requested
        4. Saves the data in the specified format
    """
    # Check if scraping is allowed
    if not check_robots_txt(args.url, session.headers["User-Agent"]):
        logging.error(
            f"Scraping not allowed for {
                args.url} according to robots.txt"
        )
        return

    # Scrape the webpage
    logging.info(f"Starting to scrape {args.url}")
    data = scrape_webpage(args.url, session)

    if not data:
        logging.error("Failed to scrape data. Exiting.")
        return

    # Fix encoding if requested
    if args.fix_encoding:
        data = fix_encoding(data)

    # Determine output filename if not specified
    if not args.output:
        parsed_url = urlparse(args.url)
        domain = parsed_url.netloc.replace(".", "_")
        args.output = f"scraped_{domain}_{int(time.time())}.{args.format}"

    # Save data
    save_data(data, args.output, args.format)


def main() -> None:
    """
    Main entry point for the scraper.

    This function:
    1. Parses command line arguments
    2. Sets up logging
    3. Processes files or URLs based on the specified mode

    Command line arguments:
        url: URL of the webpage to scrape
        -f/--format: Output format (json, csv, or txt)
        -o/--output: Output file path
        -d/--directory: Output directory for multiple chapters
        --fix-encoding: Fix encoding issues in Sanskrit verses
        --fix-file: Fix encoding in an existing JSON file
        --all-chapters: Scrape all chapters from a contents page
        --debug: Enable debug logging

    Returns:
        None
    """
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Web Scraper Tool for Sanskrit Texts")
    parser.add_argument("url", help="URL of the webpage to scrape")
    parser.add_argument(
        "-f",
        "--format",
        choices=["json", "csv", "txt"],
        default="json",
        help="Output file format (default: json)",
    )
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument(
        "-d", "--directory", help="Output directory for multiple chapters"
    )
    parser.add_argument(
        "--fix-encoding",
        action="store_true",
        help="Fix encoding issues in Sanskrit verses",
    )
    parser.add_argument(
        "--fix-file", help="Fix encoding in an existing JSON file instead of scraping"
    )
    parser.add_argument(
        "--all-chapters",
        action="store_true",
        help="Scrape all chapters from a contents page",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Set up logging
    logging_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=logging_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("scraper.log"), logging.StreamHandler()],
    )

    # Fix encoding in existing file if requested
    if args.fix_file:
        fix_file(args.fix_file, args.output)
        return

    # Select random user agent and create session
    user_agent = random.choice(USER_AGENTS)
    session = create_session()
    session.headers.update({"User-Agent": user_agent})

    # Process according to mode
    if args.all_chapters:
        process_all_chapters(args, session)
    else:
        process_single_page(args, session)


if __name__ == "__main__":
    main()
