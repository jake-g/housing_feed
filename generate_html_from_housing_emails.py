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


import time
import os
from typing import List, Dict
import pandas as pd

import email
import email.message
import imaplib
from bs4 import BeautifulSoup
from creds import EMAIL_ADDRESS, EMAIL_PASSWORD


# Constants for allowed email addresses
TO_ALLOWED = ['seattle.housing.feed@gmail.com']
FROM_ALLOWED = [
    '"Zillow" <daily-updates@mail.zillow.com>',
    '"Zillow" <open-houses@mail.zillow.com>',
    'Redfin <listings@redfin.com>',
    '"Redfin" <redmail@redfin.com>'
]

# Pagination configuration
N_ENTRIES_PER_HTML = 100

# Save .tsv of the scraped df (same info as in html)
SAVE_DEBUG_CACHE = False
LOAD_DEBUG_CACHE = False
EMAIL_CACHE_FILE = '.email_cache.tsv'


def save_emails_to_html(
    emails: pd.DataFrame,
    html_filepath: str,
    header: str,
    footer: str = None,
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
    html_content = (
        emails['html']
        .str.cat(sep='\n')
        .encode(encoding, 'replace')
        .decode(encoding)
    )
    file.write(header + html_content + footer)


def _html_header(cur_page: int, n_pages: int) -> str:
  """Returns the HTML header with embedded styles and page buttons.

  Args:
      cur_page: The index of the current page.
      n_pages: The total number of pages.

  Returns:
      The HTML header string.
  """
  first_page = ''  # dont append 0 to index
  last_page = n_pages - 1
  prev_page = cur_page - 1
  next_page = cur_page + 1
  if cur_page == 0:
    prev_page = ''
  elif cur_page == last_page:
    next_page = ''

  return f"""
    <head>
    <title>Seattle Housing Inbox</title>
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
    </style>
    </head>
    <body>
    <div class="page-buttons">
        <button onclick="window.location.href='index{first_page}.html'">Oldest</button>
        <button onclick="window.location.href='index{prev_page}.html'">Older</button>
        <button onclick="window.location.href='index{next_page}.html'">Newer</button>
        <button onclick="window.location.href='index{last_page}.html'">Newest</button>
    </div>
    """


def fetch_email_messages(
    username: str, password: str, from_allowed: List[str], to_allowed: List[str]
) -> List[email.message.Message]:
  """Fetches email messages from inbox based on sender and recipient criteria.

  Args:
      username: Email address for login.
      password: Email password for login.
      from_allowed: List of allowed sender email addresses.
      to_allowed: List of allowed recipient email addresses.

  Returns:
      A list of email messages that meet the criteria.
  """
  mail = imaplib.IMAP4_SSL('imap.gmail.com')
  mail.login(username, password)
  mail.select('inbox')
  _, data = mail.search(None, 'ALL')

  email_messages = []
  for num in data[0].split():
    _, msg_data = mail.fetch(num, '(RFC822)')
    email_message = email.message_from_bytes(msg_data[0][1])

    # Simplified filtering logic with early return
    if email_message['From'] not in from_allowed:
      print(
          'Skipping email not in from_allow_list,',
          f"From: {email_message['From']}")
      continue
    if email_message['To'] not in to_allowed:
      print(
          'Skipping email not in to_allow_list,',
          f"To: {email_message['To']}")
      continue
    email_messages.append(email_message)

  mail.logout()
  return email_messages


def parse_housing_email_message(
    email_message: email.message.Message,
) -> Dict[str, str]:
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
    email_res['Sender'], email_res['From'] = email_message['From'].split(' <')
    email_res['Sender'] = email_res['Sender'].replace('"', '').strip()
    email_res['From'] = email_res['From'].replace('>', '').strip()
  except ValueError:
    print(f"Warning: Unable to parse 'From' field: {email_message['From']}")

  # Extract email content
  content = ''
  for part in email_message.walk():
    if part.get_content_type() in ('text/plain', 'text/html'):
      try:
        content += part.get_payload(decode=True).decode('UTF-8')
      except UnicodeDecodeError:
        print('Warning: Encoding issue, trying alternative decoding.')
        content += part.get_payload(decode=True).decode('latin-1')

  # Clean up HTML content
  soup = BeautifulSoup(content, 'html.parser')

  # Remove unwanted elements based on sender
  sender_specific_removals = {
      'listings@redfin.com': ('.footer-layout-wrapper',),
      'redmail@redfin.com': ('footer',),
      'daily-updates@mail.zillow.com': ('address',),
      'open-houses@mail.zillow.com': ('address', '.dmTxtLinkSecondary'),
  }

  sender = email_res['From']
  if sender in sender_specific_removals:
    for element in sender_specific_removals[sender]:
      for item in soup.find_all(class_=element):
        item.extract()

  # Remove common unwanted elements
  for tag in soup.find_all(['script', 'style']):
    tag.decompose()
  email_res['html'] = str(soup.html)
  return email_res


def format_email_df(emails: pd.DataFrame) -> pd.DataFrame:
  """Formats the email DataFrame for HTML output.

  Args:
      emails: DataFrame containing parsed email data.

  Returns:
      pd.DataFrame: The formatted DataFrame with added 'title' column and sorted
      by date.
  """
  emails['Date'] = pd.to_datetime(
      emails['Date'], format='%a, %d %b %Y %H:%M:%S %z'
  )
  emails['title'] = (
      '<p style="text-align:center;">'
      + '<b>'
      + emails['Date'].astype(str)
      + '  :  '
      + emails['From']
      + '</b></p>'
  )
  emails['html'] = emails['title'] + emails['html']
  return emails


def run_email_scraper() -> None:
  """Fetches, parses, and saves housing-related emails to an HTML file."""
  print('Scraping emails to html...', flush=True)
  t0 = time.time()
  if LOAD_DEBUG_CACHE and os.path.exists(EMAIL_CACHE_FILE):
    print(f'Loading email cache: {EMAIL_CACHE_FILE}')
    emails = pd.read_csv(EMAIL_CACHE_FILE, sep='\t',  index_col=0)
  else:
    housing_emails = fetch_email_messages(
        EMAIL_ADDRESS, EMAIL_PASSWORD, FROM_ALLOWED, TO_ALLOWED
    )
    print(
        f'Fetched {len(housing_emails)} gmail',
        f'housing messages TO: {EMAIL_ADDRESS}',
        flush=True,
    )
    emails = pd.DataFrame(
        [parse_housing_email_message(e) for e in housing_emails]
    )
    emails = format_email_df(emails)
    emails = emails.sort_values('Date', ascending=True) # oldest first
    if SAVE_DEBUG_CACHE:
      print(f'Saving email cache: {EMAIL_CACHE_FILE}')
      emails.to_csv(EMAIL_CACHE_FILE, sep='\t', index=True)

  # Pagination logic
  n_pages = (len(emails) + N_ENTRIES_PER_HTML - 1) // N_ENTRIES_PER_HTML
  for page in range(n_pages):
    start = page * N_ENTRIES_PER_HTML
    end = min((page + 1) * N_ENTRIES_PER_HTML, len(emails))
    subset = emails.iloc[start:end]
    if page == 0:
      html_file = 'index.html'
    else:
      html_file = f'index{page}.html'

    header = _html_header(page, n_pages)
    save_emails_to_html(subset, html_file, header)

  print(
      f'Parsed {len(emails)} housing emails in',
      f'{(time.time() - t0) / 60:0.1f} minutes and saved to',
      f'{n_pages} HTML pages',
      flush=True,
  )


if __name__ == '__main__':
  run_email_scraper()
