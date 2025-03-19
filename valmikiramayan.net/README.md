# Ramayana Sanskrit Text Web Scraper

A Python tool for ethically scraping Sanskrit verses from websites, specifically targeting Ramayana texts, with respect for robots.txt and other web scraping best practices.

## Features

- Extracts Sanskrit verses using CSS selectors or Devanagari character detection
- Handles both modern websites and older sites using framesets
- Scrapes single pages or entire chapter collections
- Implements session-based requests with retry logic and timeout handling
- Uses exponential backoff for failed requests
- Respects robots.txt directives and implements polite scraping practices
- Preserves verse formatting (line breaks, etc.)
- Saves data in JSON, CSV, or TXT formats
- Fixes encoding issues in Sanskrit text
- Provides comprehensive logging with debug options
- Uses type hints throughout codebase for better maintainability

## Installation

1. Clone this repository or download the files
2. Install the required packages:

```bash
pip install requests beautifulsoup4
```

## Usage

Basic usage:

```bash
python web_scraper.py https://www.valmikiramayan.net/utf8/baala/sarga1/bala_1_frame.htm
```

Specify output format:

```bash
python web_scraper.py https://www.valmikiramayan.net/utf8/baala/sarga1/bala_1_frame.htm -f csv
```

Specify output file:

```bash
python web_scraper.py https://www.valmikiramayan.net/utf8/baala/sarga1/bala_1_frame.htm -f json -o ramayana_verses.json
```

Scrape all chapters from a contents page:

```bash
python web_scraper.py https://www.valmikiramayan.net/utf8/baala/bala_contents.htm --all-chapters
```

Fix encoding in an existing JSON file:

```bash
python web_scraper.py dummy_url --fix-file ramayana_verses.json -o fixed_verses.json
```

Enable debug logging:

```bash
python web_scraper.py https://www.valmikiramayan.net/utf8/baala/sarga1/bala_1_frame.htm --debug
```

### Command-line Arguments

- `url`: URL of the webpage to scrape (required, but can be a placeholder when using --fix-file)
- `-f, --format`: Output file format (json, csv, or txt). Default: json
- `-o, --output`: Output file path. If not provided, a filename will be generated automatically
- `-d, --directory`: Output directory for multiple chapters when using --all-chapters
- `--fix-encoding`: Fix encoding issues in Sanskrit verses
- `--fix-file`: Fix encoding in an existing JSON file instead of scraping
- `--all-chapters`: Scrape all chapters from a contents page
- `--debug`: Enable debug logging for more detailed output

## Output Structure

### JSON Format
```json
{
    "url": "https://www.valmikiramayan.net/utf8/baala/sarga1/bala_1_frame.htm",
    "sanskrit_verses": [
        "तपःस्वाध्यायनिरतं तपस्वी वाग्विदां वरम् |\nनारदं परिपप्रच्छ वाल्मीकिर्मुनिपुङ्गवम् || १-१-१",
        "..."
    ],
    "chapter_title": "Sample Chapter",
    "chapter_number": 1
}
```

### CSV Format
Each verse is listed with a verse number, content, and source URL.

### TXT Format
Plain text format with verse numbers and content.

## Multiple Chapter Scraping

When using the `--all-chapters` option, the script:

1. Parses the contents page to find all chapter links
2. Creates a directory structure to store individual chapter files
3. Processes each chapter and saves it as a separate file
4. Generates a summary JSON file with statistics about the scraping session

Example:

```bash
python web_scraper.py https://www.valmikiramayan.net/utf8/baala/bala_contents.htm --all-chapters -d ramayana_output
```

## Performance Features

- Uses a single session for all HTTP requests to benefit from connection pooling
- Implements automatic retry with exponential backoff for failed requests
- Handles timeouts properly to avoid hanging on unresponsive servers
- Adds random jitter to request delays to prevent thundering herd problems
- Uses proper error handling throughout the code

## Technical Implementation

- Type hints throughout the code for better IDE support and code quality
- Custom HTTP adapter for timeout handling
- Modular code structure for better maintainability
- Comprehensive docstrings following Google docstring style
- Debug logging to help troubleshoot issues

## Ethics & Best Practices

This scraper implements several best practices for ethical web scraping:

- Checks robots.txt before scraping any site
- Uses a reasonable delay between requests with random jitter
- Identifies itself with a user-agent string
- Handles errors gracefully
- Logs all activities for monitoring
