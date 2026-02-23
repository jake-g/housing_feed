"""
Fetches, parses, and saves housing-related emails from a Gmail inbox to an HTML file.

This script connects to a Gmail account, retrieves emails from specific senders and
recipients, extracts relevant information, cleans up the HTML content, and saves
the processed emails to an HTML file for easy viewing.

The script uses the following libraries:
    - imaplib: For interacting with the Gmail IMAP server.
    - email: For parsing email messages.
    - pandas: For data manipulation and analysis.
    - beautifulsoup4: For parsing and manipulating HTML content.

Ensure you have the necessary libraries installed and that your email credentials
are correctly configured in the `creds.py` file.
"""

import argparse
import email
import email.message
import imaplib
import logging
import os
import re
import shutil
import time
import traceback
from typing import Any, Dict, Iterator, List, Optional

from bs4 import BeautifulSoup
from bs4 import Tag
import pandas as pd
from tqdm import tqdm

from credentials import EMAIL_ADDRESS
from credentials import EMAIL_PASSWORD
import generate_report

logger = logging.getLogger(__name__)

# Configuration

# IMAP Settings
IMAP_SERVER = 'imap.gmail.com'
MAILBOX_NAME = 'inbox'

# Search criteria
TO_ALLOWED = ['seattle.housing.feed@gmail.com']
FROM_ALLOWED = [
    '"Zillow" <daily-updates@mail.zillow.com>',
    '"Zillow" <open-houses@mail.zillow.com>', 'Redfin <listings@redfin.com>',
    '"Redfin" <redmail@redfin.com>'
]

# Pagination and Saving
N_ENTRIES_PER_HTML = 100
EMAIL_CACHE_FILE = '.email_cache.tsv'

# Fetch Settings
BATCH_SIZE = 50
RATE_LIMIT_DELAY = 2  # Seconds to wait between batches to avoid throttling

# Override Settings for "SINCE" date
# Use OVERRIDE_SINCE_DATE to fetch from a specific date.
# If None, fetches only new emails since the last cached date.
# FORCE_FETCH_ALL=True ignores cache and re-fetches everything.
FORCE_FETCH_ALL = False  # Set to True to re-fetch everthing
OVERRIDE_SINCE_DATE = None  # Format: "DD-Mon-YYYY" (e.g., "01-Jan-2025")
OVERRIDE_BEFORE_DATE = None  # Optional, format: "DD-Mon-YYYY" (e.g., "31-Jan-2025"), if None, fetches until today.

# Save .tsv of the scraped df (same info as in html)
EMAIL_CACHE_FILE = '.email_cache.tsv'


def save_emails_to_html(
    emails: pd.DataFrame,
    html_filepath: str,
    header: str,
    footer: Optional[str] = None,
    encoding: str = 'utf-8',
):
  """Saves a DataFrame of email data to an HTML file.

  Args:
      emails: DataFrame containing email data, including an 'html' column with
        HTML content.
      html_filepath: Path to the output HTML file.
      encoding: Character encoding to use. Defaults to 'utf-8'.
  """
  if not footer:  # Use header as footer.
    footer = header

  with open(html_filepath, 'w', encoding=encoding) as file:
    # Concatenate first, then encode/decode for efficiency
    raw_html = emails['html'].str.cat(sep='\n')

    # helper to clean
    cleaned_html, stats = clean_html_bloat(raw_html)

    # Accumulate stats
    if 'original_bytes' not in HTML_STATS:
      HTML_STATS['original_bytes'] = 0
      HTML_STATS['cleaned_bytes'] = 0
      HTML_STATS['pages_count'] = 0
    HTML_STATS['original_bytes'] += stats['orig_len']
    HTML_STATS['cleaned_bytes'] += stats['clean_len']
    HTML_STATS['pages_count'] += 1

    final_content = (header + cleaned_html + footer).encode(
        encoding, 'replace').decode(encoding)
    file.write(final_content)


def clean_html_bloat(content: str) -> tuple[str, Dict[str, int]]:
  """Removes Outlook VML, tracking pixels, and other bloat from HTML."""
  orig_len = len(content.encode('utf-8'))

  # Remove Outlook Conditional Comments
  content = re.sub(r'<!--\[if gte mso.*?<!\[endif\]-->',
                   '',
                   content,
                   flags=re.DOTALL)

  # Remove VML tags
  content = re.sub(r'<v:[a-zA-Z0-9]+[^>]*>.*?</v:[a-zA-Z0-9]+>',
                   '',
                   content,
                   flags=re.DOTALL)
  content = re.sub(r'<v:[a-zA-Z0-9]+[^>]*/>', '', content)

  # Remove Tracking Pixels (1x1 images or display:none)
  content = re.sub(r'<img\s+[^>]*\b(?:width|height)=["\']1["\'][^>]*\/?>',
                   '',
                   content,
                   flags=re.IGNORECASE)
  content = re.sub(
      r'<img\s+[^>]*\bstyle=["\'][^"\']*display:\s*none[^"\']*["\'][^>]*\/?>',
      '',
      content,
      flags=re.IGNORECASE)

  clean_len = len(content.encode('utf-8'))
  return content, {'orig_len': orig_len, 'clean_len': clean_len}


HTML_STATS: Dict[str, int] = {}


def _stable_html_header(cur_page_file: str,
                        prev_page_file: Optional[str],
                        next_page_file: Optional[str],
                        first_page_file: str,
                        last_page_file: str,
                        all_pages: List[str],
                        min_date: str = "",
                        max_date: str = "") -> str:
  # pylint: disable=too-many-positional-arguments
  """Generates HTML header with date-based navigation and keyboard shortcuts.

    Args:
        cur_page_file: Filename of current page.
        prev_page_file: Filename of previous (newer) page, or None.
        next_page_file: Filename of next (older) page, or None.
        first_page_file: Filename of first (newest) page.
        last_page_file: Filename of last (oldest) page.
        all_pages: List of all page filenames (ordered Newest to Oldest) for dropdown.
        min_date: Start date of current page.
        max_date: End date of current page.

    Returns:
        HTML string.
    """
  newer_link = prev_page_file if prev_page_file else "#"
  newer_disabled = "" if prev_page_file else "disabled"
  newer_style = "" if prev_page_file else "cursor: not-allowed; opacity: 0.5;"

  older_link = next_page_file if next_page_file else "#"
  older_disabled = "" if next_page_file else "disabled"
  older_style = "" if next_page_file else "cursor: not-allowed; opacity: 0.5;"

  date_range_html = ""
  if min_date and max_date:
    date_range_html = f'<div style="font-size: 0.9em; color: #666; margin-top: 5px;">{min_date} - {max_date}</div>'

  # Dropdown options
  dropdown_options = []
  for page in all_pages:
    selected = "selected" if page == cur_page_file else ""
    # Extract date range from filename for display (e.g. 2025-01-01_2025-01-05.html -> 2025-01-01 to 2025-01-05)
    display_text = page.replace(".html", "").replace("_", " to ")
    dropdown_options.append(
        f'<option value="{page}" {selected}>{display_text}</option>')
  dropdown_html = "\n".join(dropdown_options)

  return f"""
    <head>
    <!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-VH5BZ1X3TL"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());

      gtag('config', 'G-VH5BZ1X3TL');

      // Keyboard Navigation
      document.addEventListener('keydown', function(event) {{
          if (event.key === "ArrowLeft") {{
              // Left Arrow -> Newer Page
              var link = "{newer_link}";
              if (link !== "#") window.location.href = link;
          }} else if (event.key === "ArrowRight") {{
              // Right Arrow -> Older Page
              var link = "{older_link}";
              if (link !== "#") window.location.href = link;
          }}
      }});
    </script>
    <title>Housing Feed</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🏠</text></svg>">
    <style>
        /* Styles for desktop */
        body {{
            zoom: 150%;
            margin: 50px;
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
        /* Styles for mobile */
        @media screen and (max-width: 600px) {{
            body {{
                zoom: 90%;
                margin: 5px;
            }}
        }}
        .page-buttons {{
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-top: 20px;
        }}
        /* Force header text color to black to prevent email styles from overriding it */
        .header-container, .header-container div, .header-container a {{
            color: #000000 !important;
        }}
    </style>
    </head>
    <body>
    <div class="header-container" style="text-align:center; margin-bottom: 20px;">
        <div class="page-info" style="font-size: 1.2em; font-weight: bold;">Housing Feed</div>
        {date_range_html}
        <div class="page-buttons">
            <button onclick="window.location.href='{first_page_file}'">Newest</button>
            <button onclick="window.location.href='{newer_link}'" {newer_disabled} style="{newer_style}">Newer (←)</button>
            <button onclick="window.location.href='{older_link}'" {older_disabled} style="{older_style}">Older (→)</button>
            <button onclick="window.location.href='{last_page_file}'">Oldest</button>
        </div>
        <div style="margin-top: 10px;">
            <label for="jumpPage">Jump to:</label>
            <select id="jumpPage" onchange="window.location.href=this.value">
                {dropdown_html}
            </select>
        </div>
        <div class="src-link" style="margin-top: 10px;">
            <a href="https://github.com/jake-g/housing_feed" target="_blank" style="text-decoration: none; font-size: 0.9em;">View on GitHub</a>
        </div>
    </div>

        <div class="src-link" style="margin-top: 10px;">
            <a href="https://github.com/jake-g/housing_feed" target="_blank" style="text-decoration: none; font-size: 0.9em;">View on GitHub</a>
        </div>
    </div>
    """


def fetch_email_messages(
    username: str,
    password: str,
    from_allowed: List[str],
    to_allowed: List[str],
    since_date: str = "",
    before_date: Optional[str] = None) -> Iterator[List[email.message.Message]]:
  # pylint: disable=too-many-positional-arguments
  """Fetches email messages from inbox based on sender and recipient criteria.

  Args:
      username: Email address for login.
      password: Email password for login.
      from_allowed: List of allowed sender email addresses.
      to_allowed: List of allowed recipient email addresses.
      since_date: Optional IMAP formatted date string (e.g. "14-Feb-2023") to limit search.
      before_date: Optional IMAP formatted date string (e.g. "14-Feb-2023") to limit search.

  Yields:
      Batches (lists) of email messages that meet the criteria. Yields partial batches if interrupted.
  """
  try:
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(username, password)
    mail.select(MAILBOX_NAME)
  except Exception as e:
    logger.error("Failed to connect or login to IMAP: %s", e)
    return

  # To avoid local iteration bottlenecks, use server-side SEARCH
  # Construct the OR query for FROM addresses
  from_query_parts = [
      f'(FROM "{sender.split("<")[1].replace(">", "")}")'
      if "<" in sender else f'(FROM "{sender}")' for sender in from_allowed
  ]
  # Construct server-side search query
  # Note: IMAP search is limited. We use a broad search for allowed senders/recipients
  # and perform stricter filtering locally.

  # Simplified dynamic query based on TO_ALLOWED and FROM_ALLOWED isn't trivial without robust parsing.
  # Sticking to the specific domains mentioned in FROM_ALLOWED for the search query to be safe/broad:
  search_query = f'(TO "{to_allowed[0]}" OR (FROM "zillow.com") (FROM "redfin.com"))'
  if since_date:
    search_query = f'SINCE "{since_date}" {search_query}'
  if before_date:
    search_query = f'BEFORE "{before_date}" {search_query}'

  logger.info("Executing Server-Side IMAP search: %s", search_query)
  _, data = mail.search(None, search_query)

  msg_nums = data[0].split()
  total_emails = len(msg_nums)
  logger.info("Found %d exact matches from server. Fetching full contents...",
              total_emails)

  batch_size = BATCH_SIZE
  start_time = time.time()

  for i in range(0, total_emails, batch_size):
    batch_nums = msg_nums[i:i + batch_size]
    batch_str = b",".join(batch_nums).decode('utf-8')

    elapsed = time.time() - start_time
    percent = (i / total_emails) * 100 if total_emails > 0 else 0
    logger.debug("[%.1fs] Downloading emails %d to %d of %d (%.1f%%)...",
                 elapsed, i + 1, min(i + batch_size,
                                     total_emails), total_emails, percent)

    try:
      # Fetch multiple emails at once
      _, msg_data = mail.fetch(batch_str, '(RFC822)')

      batch_messages = []
      # msg_data contains tuples of (header, content) interspersed with closing parenthesis
      # Ensure msg_data is a list before iterating
      if isinstance(msg_data, list):
        for item in msg_data:
          if isinstance(item, tuple):
            email_message = email.message_from_bytes(item[1])  # type: ignore # pylint: disable=unsubscriptable-object

            # Final exact check locally just in case
            sender = email_message.get('From', '').strip()
            if not any(allowed in sender for allowed in from_allowed):
              continue

            batch_messages.append(email_message)

      yield batch_messages
    except imaplib.IMAP4.abort as e:  # Abort is often more critical, handle first
      logger.error(
          "IMAP connection aborted (OVERQUOTA or network error), stopping early: %s",
          e)
      break
    except imaplib.IMAP4.error as e:
      logger.error("IMAP error during batch fetch (stopping early): %s", e)
      break

    # Rate limiting to avoid throttling (e.g. Gmail "Account exceeded command or bandwidth limits")
    time.sleep(RATE_LIMIT_DELAY)

  logger.info("Finished processing IMAP fetch loop.")
  try:
    mail.logout()
  except Exception:
    pass


# Compiled Regex Patterns
PRICE_RE = re.compile(r'\$\d{1,3}(?:,\d{3})+')
BEDS_RE = re.compile(r'(\d+)\s*(?:bd|Beds|Bds)', re.IGNORECASE)
BATHS_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:ba|Baths|Bths)', re.IGNORECASE)
SQFT_RE = re.compile(r'(\d+(?:,\d+)?)\s*(?:sq\s*ft\.?|sqft)', re.IGNORECASE)
ZIP_RE = re.compile(r'\b(98\d{3})\b')
CITY_WA_RE = re.compile(r'([A-Za-z\s]+),\s*(WA)\b')
TYPE_RE = re.compile(
    r'\b(Condo|Townhome|Townhouse|House|Multi-Family|Multi-family|Single Family)\b',
    re.IGNORECASE)
LINK_RE = re.compile(
    r'zpid|WA/|homedetails|urn:msg:|redfin\.com/.*click|click\.mail\.zillow',
    re.IGNORECASE)


def parse_housing_email_message(
    email_message: email.message.Message,) -> Dict[str, Any]:
  """Parses a single email message, extracts info, and cleans HTML content.

  Args:
      email_message: An email message object.

  Returns:
      A dictionary containing parsed email data, including cleaned HTML content.
  """
  # Extract header data
  email_res = {
      'Subject': email_message['Subject'],
      'To': email_message['To'],
      'From': email_message['From'],
      'Date': email_message['Date'],
  }

  # Parse sender's name and email
  try:
    if ' <' in email_message.get('From', ''):
      email_res['Sender'], email_res['From'] = email_message['From'].split(' <')
      email_res['Sender'] = email_res['Sender'].replace('"', '').strip()
      email_res['From'] = email_res['From'].replace('>', '').strip()
  except ValueError:
    logger.warning("Unable to parse 'From' field: %s", email_message['From'])

  # Extract email content
  content = ''
  for part in email_message.walk():
    if part.get_content_type() in ('text/plain', 'text/html'):
      payload = part.get_payload(decode=True)
      if isinstance(payload, bytes):
        try:
          content += payload.decode('UTF-8')
        except UnicodeDecodeError:
          logger.debug(
              "Encoding issue on part decoding, trying alternative latin-1.")
          content += payload.decode('latin-1')

  # Clean up HTML content
  soup = BeautifulSoup(content, 'html.parser')

  # Remove unwanted elements based on sender
  sender_specific_removals = {
      'listings@redfin.com': ('.footer-layout-wrapper',),
      'redmail@redfin.com': ('footer',),
      'daily-updates@mail.zillow.com': ('address',),
      'open-houses@mail.zillow.com': ('address', '.dmTxtLinkSecondary'),
  }

  sender = email_res.get('From', '')
  if sender in sender_specific_removals:
    for element in sender_specific_removals[sender]:
      for item in soup.find_all(class_=element):
        item.extract()

  # Remove common unwanted elements
  for tag in soup.find_all(['script', 'style']):
    tag.decompose()

  # Extract multiple properties structured data before serializing to html
  properties_found = {}

  for a in soup.find_all('a', href=LINK_RE):
    url = a['href']
    parent = a.parent
    while parent and '$' not in parent.get_text():
      parent = parent.parent
      if not parent:
        break

    if not parent:
      continue

    text = parent.get_text(separator=' ', strip=True)
    price_match = PRICE_RE.search(text)
    if not price_match:
      continue

    price = price_match.group(0)
    beds_match = BEDS_RE.search(text)
    beds = beds_match.group(1) if beds_match else ''

    key = f"{price}_{beds}_{url[:50]}"
    if key not in properties_found:
      properties_found[key] = (text, url, parent)

  if not properties_found:
    text = soup.get_text(separator=' ', strip=True)
    if PRICE_RE.search(text):
      link_elem = soup.find('a', href=LINK_RE)
      url = link_elem.get('href') if isinstance(link_elem, Tag) else ''
      properties_found['fallback'] = (text, url, None)

  extracted_props = []
  for key, (text, listing_link, parent) in properties_found.items():
    price_match = PRICE_RE.search(text)
    price = price_match.group(0) if price_match else ''

    beds_match = BEDS_RE.search(text)
    beds = beds_match.group(1) if beds_match else ''

    baths_match = BATHS_RE.search(text)
    baths = baths_match.group(1) if baths_match else ''

    sqft_match = SQFT_RE.search(text)
    sqft = sqft_match.group(1).replace(',', '') if sqft_match else ''

    zip_match = ZIP_RE.search(text)
    zip_code = zip_match.group(1) if zip_match else ''

    type_match = TYPE_RE.search(text)
    prop_type = type_match.group(1).title() if type_match else ''
    if prop_type == 'Single Family':
      prop_type = 'House'

    city_match = CITY_WA_RE.search(text)
    city = city_match.group(1).strip() if city_match else ''

    # Expanded Search Fallbacks
    pp = parent
    levels = 0
    while pp and levels < 5 and (not zip_code or not prop_type or not city):
      broader_text = pp.get_text(separator=' ', strip=True)
      if not zip_code:
        zip_match = ZIP_RE.search(broader_text)
        if zip_match:
          zip_code = zip_match.group(1)
      if not prop_type:
        type_match = TYPE_RE.search(broader_text)
        if type_match:
          prop_type = type_match.group(1).title()
          if prop_type == 'Single Family':
            prop_type = 'House'
      if not city:
        city_match = CITY_WA_RE.search(broader_text)
        if city_match:
          city = city_match.group(1).strip()
      pp = pp.parent
      levels += 1

    extracted_props.append({
        'Property_Type': prop_type,
        'City': city,
        'Zip': zip_code,
        'Price': price,
        'Beds': beds,
        'Baths': baths,
        'Sqft': sqft,
        'Listing_Link': listing_link
    })

  email_res['properties_list'] = extracted_props
  email_res['html'] = str(soup.html)
  return email_res


def generate_paginated_html(emails: pd.DataFrame,
                            output_dir: str = 'listings') -> int:
  """Generates paginated HTML files with Date-Based Filenames (Stable Archiving).

  Args:
      emails: DataFrame of emails.
      output_dir: Directory to save HTML files.

  Returns:
      Number of pages generated.
  """
  if emails is None or emails.empty:
    logger.warning("Cannot paginate empty emails")
    return 0

  os.makedirs(output_dir, exist_ok=True)

  # Sort by Date Ascending (Oldest First) to ensure stable chunks.
  # This guarantees that if historical data remains constant, the older pages
  # (and their filenames) remain unchanged, preventing git churn.
  emails_sorted = emails.sort_values('Date', ascending=True)

  n_entries = N_ENTRIES_PER_HTML
  total_emails = len(emails_sorted)
  n_pages = (total_emails + n_entries - 1) // n_entries

  logger.info('Generating %d HTML pages (Date-Based Archiving) in "%s/"...',
              n_pages, output_dir)

  # Prepare page metadata first to link them
  page_metadata: List[Dict[str, Any]] = []

  chunks = []
  for i in range(n_pages):
    start_idx = i * n_entries
    end_idx = min((i + 1) * n_entries, total_emails)
    chunk = emails_sorted.iloc[start_idx:end_idx]

    min_date = chunk['Date'].min().strftime('%Y-%m-%d')
    max_date = chunk['Date'].max().strftime('%Y-%m-%d')
    filename = f'{min_date}_{max_date}.html'

    chunks.append({
        'chunk': chunk,
        'filename': filename,
        'min_date': min_date,
        'max_date': max_date
    })

  # Sort pages by date descending (Newest First) for navigation flow
  # Page 0 = Newest
  chunks.sort(key=lambda x: x['chunk']['Date'].max(), reverse=True)

  all_filenames = [c['filename'] for c in chunks]
  first_page = all_filenames[0] if all_filenames else ""
  last_page = all_filenames[-1] if all_filenames else ""

  generated_count = 0
  for i, data in enumerate(tqdm(chunks, desc="Generating HTML Pages")):
    chunk = data['chunk']
    filename = data['filename']
    min_date = data['min_date']
    max_date = data['max_date']

    # Determine Next/Prev
    # Logic: "Newer" (Left Arrow) -> Index i-1 (if i>0)
    #        "Older" (Right Arrow) -> Index i+1 (if i<len-1)
    prev_page = all_filenames[i - 1] if i > 0 else None
    next_page = all_filenames[i + 1] if i < len(all_filenames) - 1 else None

    # Reverse display within page so newest is at top
    chunk_display = chunk.sort_values('Date', ascending=False)

    html_file = os.path.join(output_dir, filename)

    header = _stable_html_header(cur_page_file=filename,
                                 prev_page_file=prev_page,
                                 next_page_file=next_page,
                                 first_page_file=first_page,
                                 last_page_file=last_page,
                                 all_pages=all_filenames,
                                 min_date=min_date,
                                 max_date=max_date)

    save_emails_to_html(chunk_display, html_file, header)
    generated_count += 1

  # Create index.html as a copy of the Newest Page
  if all_filenames:
    latest_page = os.path.join(output_dir, first_page)

    # link listings/index.html
    index_page_listings = os.path.join(output_dir, 'index.html')
    shutil.copy(latest_page, index_page_listings)

    # link ./index.html (root) for GitHub Pages
    index_page_root = 'index.html'
    # Copy and inject <base href="listings/"> so links work at root
    try:
      with open(latest_page, 'r', encoding='utf-8') as f_in, \
           open(index_page_root, 'w', encoding='utf-8') as f_out:
        content = f_in.read()
        # Inject base tag after <head> to fix relative links (css, js, anchors)
        if '<head>' in content:
          content = content.replace('<head>',
                                    '<head>\n    <base href="listings/">')
        else:
          # Fallback if no head tag (unlikely)
          logger.warning(
              "No <head> tag found in %s, appending base tag at start.",
              latest_page)
          content = '<base href="listings/">\n' + content
        f_out.write(content)
    except Exception as e:
      logger.error("Failed to create root index.html with base tag: %s", e)
      # Fallback to copy if injection fails
      shutil.copy(latest_page, index_page_root)

    logger.info(
        "Updated index.html (listings/ and root) to point to latest page (%s)",
        first_page)

  return generated_count


def format_email_df(emails: pd.DataFrame) -> pd.DataFrame:
  """Formats the email DataFrame for HTML output.

  Args:
      emails: DataFrame containing parsed email data.

  Returns:
      pd.DataFrame: The formatted DataFrame with added 'title' column and sorted
      by date.
  """
  emails['Date'] = pd.to_datetime(emails['Date'],
                                  format='%a, %d %b %Y %H:%M:%S %z',
                                  utc=True)
  emails['title'] = emails.apply(
      lambda row:
      f'<p style="text-align:center;"><b>{row["Date"]}  :  {row["From"]}  :  {row["Subject"]}</b></p>',
      axis=1)
  emails['html'] = emails['title'] + emails['html']
  return emails


def run_email_scraper() -> None:
  """Fetches, parses, and saves housing-related emails to an HTML file."""
  logger.info('Scraping emails to html...')
  t0 = time.time()

  cached_emails = None
  since_date_str = ""

  if os.path.exists(EMAIL_CACHE_FILE):
    logger.info('Loading existing email cache: %s', EMAIL_CACHE_FILE)
    try:
      # Read cache to find the latest date. Handle bad lines gracefully to prevent full crash.
      cached_emails = pd.read_csv(EMAIL_CACHE_FILE,
                                  sep='\t',
                                  index_col=0,
                                  on_bad_lines='skip')
      if not cached_emails.empty and 'Date' in cached_emails.columns:
        # Convert date strings back to datetime to find the max
        # The cache has dates formatted as strings, but pandas can usually parse them
        cached_emails['Date'] = pd.to_datetime(cached_emails['Date'],
                                               errors='coerce',
                                               utc=True)
    except Exception as e:
      logger.warning("Could not load or parse cache. Fetching all. (%s)", e)
      cached_emails = None

  if FORCE_FETCH_ALL:
    logger.info(
        "FORCE_FETCH_ALL is True. Ignoring cache date and fetching ALL emails.")
    since_date_str = ""
  elif OVERRIDE_SINCE_DATE:
    logger.info("OVERRIDE_SINCE_DATE set to '%s'. Using this start date.",
                OVERRIDE_SINCE_DATE)
    since_date_str = OVERRIDE_SINCE_DATE
  elif cached_emails is not None and not cached_emails.empty:
    max_date = cached_emails['Date'].max()
    if pd.notna(max_date):
      # IMAP search uses "dd-Mon-yyyy" format
      since_date_str = max_date.strftime("%d-%b-%Y")
      logger.info("Latest cache date found: %s. Fetching emails SINCE %s",
                  max_date.strftime('%Y-%m-%d'), since_date_str)

  email_batches = fetch_email_messages(EMAIL_ADDRESS,
                                       EMAIL_PASSWORD,
                                       FROM_ALLOWED,
                                       TO_ALLOWED,
                                       since_date=since_date_str,
                                       before_date=OVERRIDE_BEFORE_DATE)

  new_emails_fetched = 0

  # Ensure parsing and sorting compatibility with fetch updates
  try:
    for housing_emails_batch in tqdm(email_batches,
                                     desc="Fetching and Parsing Emails",
                                     unit="batch"):
      if not housing_emails_batch:
        continue

      new_emails_fetched += len(housing_emails_batch)
      batch_df = pd.DataFrame(
          [parse_housing_email_message(e) for e in housing_emails_batch])
      batch_df = format_email_df(batch_df)

      if cached_emails is not None and not cached_emails.empty:
        cached_emails = pd.concat([cached_emails, batch_df], ignore_index=True)
      else:
        cached_emails = batch_df

      # Sort oldest first (ascending=True), so newest rows are appended at the bottom
      cached_emails = cached_emails.sort_values('Date', ascending=True)
      # Keep the most recent data row if duplicates found
      cached_emails = cached_emails.drop_duplicates(subset=['Date', 'From'],
                                                    keep='last')

      # Incremental save immediately writes to disk
      cached_emails.to_csv(EMAIL_CACHE_FILE, sep='\t', index=True)
  except Exception as e:
    logger.error("Error occurred during incremental processing: %s", e)
    traceback.print_exc()
    logger.info("Saving currently fetched emails before exiting...")
    if cached_emails is not None and not cached_emails.empty:
      cached_emails.to_csv(EMAIL_CACHE_FILE, sep='\t', index=True)

  if new_emails_fetched > 0:
    logger.info('Fetched a total of %d new gmail housing messages TO: %s',
                new_emails_fetched, EMAIL_ADDRESS)
  else:
    logger.info("No new emails found. Using cached data.")
    if cached_emails is None or cached_emails.empty:
      logger.info("No emails to process.")
      return

  emails = cached_emails

  # Pagination logic
  if emails is None or emails.empty:
    logger.warning("Cannot paginate empty emails")
    return
  if emails is None or emails.empty:
    logger.warning("Cannot paginate empty emails")
    return

  # Use new stable pagination
  n_pages = generate_paginated_html(emails, 'listings')

  elapsed_mins = (time.time() - t0) / 60
  logger.info(
      'Parsed %d housing emails in %.1f minutes and saved to %d HTML pages',
      len(emails), elapsed_mins, n_pages)

  if 'original_bytes' in HTML_STATS:
    orig = HTML_STATS['original_bytes']
    clean = HTML_STATS['cleaned_bytes']
    diff = orig - clean
    pct = (diff / orig * 100) if orig > 0 else 0
    logger.info("HTML Optimization Report:")
    logger.info("  Original Size: %.2f MB", orig / 1024 / 1024)
    logger.info("  Cleaned Size:  %.2f MB", clean / 1024 / 1024)
    logger.info("  Reduction:     %.2f MB (%.1f%%)", diff / 1024 / 1024, pct)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(
      description="Fetch and parse housing emails.")
  parser.add_argument('--debug',
                      action='store_true',
                      help='Enable debug logging')
  args = parser.parse_args()

  log_level = logging.DEBUG if args.debug else logging.INFO
  generate_report.setup_logging('fetch_emails', log_level)

  run_email_scraper()
