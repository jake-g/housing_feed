import imaplib
import email
import pandas as pd
from bs4 import BeautifulSoup

from creds import EMAIL_ADDRESS, EMAIL_PASSWORD

import time

# Only pull emails TO/FROM entries in these lists
TO_ALLOWED = ['seattle.housing.feed@gmail.com']
FROM_ALLOWED = [
    '"Zillow" <daily-updates@mail.zillow.com>',
    '"Zillow" <open-houses@mail.zillow.com>',
    'Redfin <listings@redfin.com>',
    '"Redfin" <redmail@redfin.com>'
]


def save_emails_to_html(emails, html_filepath):
    with open(html_filepath, 'w') as file:
        file.write(_html_header() + emails['html'].str.cat(sep='\n'))


def _html_header():
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


def fetch_email_messages(username, password, from_allowed, to_allowed):
    # Connect to the Gmail IMAP server
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(username, password)
    mail.select('inbox')
    _, data = mail.search(None, 'ALL')
    email_messages = []
    for num in data[0].split():
        _, msg_data = mail.fetch(num, '(RFC822)')
        email_message = email.message_from_bytes(msg_data[0][1])
        if email_message['From'] not in from_allowed:
            print(f"Skipping email not in from_allow_list,",
                  f"From: {email_message['From']}")
            continue
        elif email_message['To'] not in to_allowed:
            print(f"Skipping email not in to_allow_list,",
                  f"To: {email_message['To']}")
            continue
        email_messages.append(email_message)
    mail.logout()
    return email_messages


def parse_housing_email_message(email_message):
    email_res = {k: email_message[k]
                 for k in ['Subject', 'To', 'From', 'Date']}
    from_name, from_email = email_res['From'].split(' <')
    email_res['Sender'] = from_name.replace('"', '').strip()
    email_res['From'] = from_email.replace('>', '').strip()
    content = ''
    if email_message.is_multipart():
        for part in email_message.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain' or content_type == 'text/html':
                content += part.get_payload(decode=True).decode('UTF-8')
    else:
        content_type = email_message.get_content_type()
        if content_type == 'text/plain' or content_type == 'text/html':
            email_res['Content'] = email_message.get_payload(
                decode=True).decode('UTF-8')
    # email_res['Content'] = content
    bs4 = BeautifulSoup(content, 'html.parser')

    # Find all script tags and remove
    script_tags = bs4.find_all('script')
    for script_tag in script_tags:
        script_tag.decompose()
    # Find all the style tags and remove
    style_tags = bs4.find_all('style')
    for style_tag in style_tags:
        style_tag.extract()

    elements_to_remove = []
    if email_res['From'] == 'listings@redfin.com':
        elements_to_remove += bs4.find_all(class_='footer-layout-wrapper')
    elif email_res['From'] == 'redmail@redfin.com':
        elements_to_remove += bs4.find_all(class_='footer')
    elif (email_res['From'] == 'daily-updates@mail.zillow.com' or
          email_res['From'] == 'open-houses@mail.zillow.com'):
        elements_to_remove = bs4.find_all('address')
        elements_to_remove += bs4.find_all(class_='dmTxtLinkSecondary')
    #     elements_to_remove = bs4.find_all(
        # class_=lambda value: value and value.startswith('width100'))
    for element in elements_to_remove:
        element.extract()

    email_res['html'] = str(bs4.html)
    email_res['bs4'] = bs4
    return email_res


def format_email_df(emails):
    emails['Date'] = pd.to_datetime(
        emails['Date'], format='%a, %d %b %Y %H:%M:%S %z')
    emails['title'] = '<p style="text-align:center;">'+"<b>" + \
        emails['Date'].astype(str)+"  :  "+emails['From']+"</b></p>"
    emails['html'] = emails['title'] + emails['html']
    emails = emails.sort_values('Date', ascending=False)
    return emails


if __name__ == "__main__":
    t0 = time.time()
    # Filename of output .html
    HTML_FILE = 'index.html'
    # Get the current date as a string
    DATE = time.strftime('%Y-%m-%d', time.localtime())

    # Fetch emails and extract information
    housing_emails = fetch_email_messages(EMAIL_ADDRESS, EMAIL_PASSWORD,
                                          FROM_ALLOWED, TO_ALLOWED)
    print(f'Fetched {len(housing_emails)} gmail housing messages',
          f'TO: {EMAIL_ADDRESS}')
    # Convert to emails DataFrame
    emails = pd.DataFrame([parse_housing_email_message(e)
                          for e in housing_emails])
    emails = format_email_df(emails)
    # Save to html with customized header/styles
    save_emails_to_html(emails, HTML_FILE)
    print(f'Parsed {len(emails)} housing emails and saved to {HTML_FILE}',
          f'in {round((time.time() - t0)/60, 2)} minutes')
