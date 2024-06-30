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
from typing import List, Dict, Any
import pandas as pd

import email
import email.message
import imaplib
from bs4 import BeautifulSoup
from creds import EMAIL_ADDRESS, EMAIL_PASSWORD


# Constants for allowed email addresses (moved outside for better organization)
TO_ALLOWED = ['seattle.housing.feed@gmail.com']
FROM_ALLOWED = [
    '"Zillow" <daily-updates@mail.zillow.com>',
    '"Zillow" <open-houses@mail.zillow.com>',
    'Redfin <listings@redfin.com>',
    '"Redfin" <redmail@redfin.com>'
]


def save_emails_to_html(emails: pd.DataFrame, html_filepath: str, encoding: str = 'utf-8') -> None:
    """Saves a DataFrame of email data to an HTML file.

    Args:
        emails (pd.DataFrame): DataFrame containing email data,
                                 including an 'html' column with HTML content.
        html_filepath (str): Path to the output HTML file.
        encoding (str, optional): Character encoding to use. Defaults to 'utf-8'.
    """
    with open(html_filepath, 'w', encoding=encoding) as file:
        # Concatenate first, then encode/decode for efficiency
        html_content = emails['html'].str.cat(sep='\n').encode(
            encoding, 'replace').decode(encoding)
        file.write(_html_header() + html_content)


def _html_header() -> str:
    """Returns the HTML header with embedded styles.

    Returns:
        str: The HTML header string.
    """
    return """
    <head>
    <title>Seattle Housing Inbox</title>
    <style>
        /* Styles for desktop */
        body {
            zoom: 150%;
            margin: 50px;
        }
        img {
            max-width: 100%;
            height: auto;
        }
        /* Styles for mobile */
        @media screen and (max-width: 600px) {
            body {
                zoom: 90%;
                margin: 5px;
            }
        }
    </style>
    </head>
    """


def fetch_email_messages(username: str, password: str,
                         from_allowed: List[str],
                         to_allowed: List[str]) -> List[email.message.Message]:
    """Fetches email messages from a Gmail inbox based on sender and recipient criteria.

    Args:
        username (str): Email address for login.
        password (str): Email password for login.
        from_allowed (List[str]): List of allowed sender email addresses.
        to_allowed (List[str]): List of allowed recipient email addresses.

    Returns:
        List[email.message.Message]: A list of email messages that meet the criteria.
    """
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(username, password)
    mail.select('inbox')
    _, data = mail.search(None, 'ALL')

    email_messages = []
    for num in data[0].split():
        _, msg_data = mail.fetch(num, '(RFC822)')
        email_message = email.message_from_bytes(msg_data[0][1])

        # Simplified filtering logic with early return
        if email_message['From'] not in from_allowed:
            print(f"Skipping email not in from_allow_list, From: {
                  email_message['From']}")
            continue
        if email_message['To'] not in to_allowed:
            print(f"Skipping email not in to_allow_list, To: {
                  email_message['To']}")
            continue

        email_messages.append(email_message)

    mail.logout()
    return email_messages


def parse_housing_email_message(email_message: email.message.Message) -> Dict[str, str]:
    """Parses a single email message, extracts relevant information, and cleans up the HTML content.

    Args:
        email_message (email.message.Message): An email message object.

    Returns:
        Dict[str, str]: A dictionary containing parsed email data, including cleaned HTML content.
    """
    email_res = {k: email_message[k]
                 for k in ['Subject', 'To', 'From', 'Date']}

    # Extract sender name and email from 'From' field
    try:
        from_name, from_email = email_res['From'].split(' <')
    except ValueError:
        print(f"Warning: Unable to parse 'From' field: {email_res['From']}")
        # Or handle differently (e.g., raise an error)
        from_name, from_email = "", ""

    email_res['Sender'] = from_name.replace('"', '').strip()
    email_res['From'] = from_email.replace('>', '').strip()

    content = ''
    for part in email_message.walk():
        content_type = part.get_content_type()
        if content_type in ('text/plain', 'text/html'):
            try:
                content += part.get_payload(decode=True).decode('UTF-8')
            except UnicodeDecodeError:
                print("Warning: Encoding issue, trying alternative decoding.")
                # Try a common fallback
                content += part.get_payload(decode=True).decode('latin-1')

    bs4 = BeautifulSoup(content, 'html.parser')

    # Remove script and style tags
    for tag in bs4.find_all(['script', 'style']):
        tag.decompose()

    # Remove unwanted elements based on sender (more concise logic)
    elements_to_remove = []
    if email_res['From'] == 'listings@redfin.com':
        elements_to_remove.extend(bs4.find_all(class_='footer-layout-wrapper'))
    elif email_res['From'] == 'redmail@redfin.com':
        elements_to_remove.extend(bs4.find_all(class_='footer'))
    elif email_res['From'] in ('daily-updates@mail.zillow.com', 'open-houses@mail.zillow.com'):
        elements_to_remove.extend(bs4.find_all('address'))
        elements_to_remove.extend(bs4.find_all(class_='dmTxtLinkSecondary'))

    for element in elements_to_remove:
        element.extract()

    email_res['html'] = str(bs4.html)  # Store the cleaned HTML
    # email_res['bs4'] = bs4  # No need to store the entire bs4 object

    return email_res


def format_email_df(emails: pd.DataFrame) -> pd.DataFrame:
    """Formats the email DataFrame for HTML output.

    Args:
        emails (pd.DataFrame): DataFrame containing parsed email data.

    Returns:
        pd.DataFrame: The formatted DataFrame with added 'title' column and sorted by date.
    """
    emails['Date'] = pd.to_datetime(
        emails['Date'], format='%a, %d %b %Y %H:%M:%S %z')
    emails['title'] = (
        '<p style="text-align:center;">' + "<b>" +
        emails['Date'].astype(str) + "  :  " + emails['From'] + "</b></p>"
    )
    emails['html'] = emails['title'] + emails['html']
    emails = emails.sort_values('Date', ascending=False)
    return emails


def run_email_scraper(html_filepath: str = 'index.html') -> None:
    """Fetches, parses, and saves housing-related emails to an HTML file. 

    Args:
        html_filepath (str, optional): The path to the output HTML file. 
                                         Defaults to 'index.html'.
    """
    t0 = time.time()
    housing_emails = fetch_email_messages(
        EMAIL_ADDRESS, EMAIL_PASSWORD, FROM_ALLOWED, TO_ALLOWED)
    print(f'Fetched {len(housing_emails)
                     } gmail housing messages TO: {EMAIL_ADDRESS}')
    emails = pd.DataFrame([parse_housing_email_message(e)
                          for e in housing_emails])
    emails = format_email_df(emails)
    save_emails_to_html(emails, html_filepath)
    print(f'Parsed {len(emails)} housing emails and saved to {html_filepath} '
          f'in {round((time.time() - t0)/60, 2)} minutes')


if __name__ == "__main__":
    run_email_scraper()
