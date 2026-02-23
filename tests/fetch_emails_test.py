import email
import sys
from unittest.mock import MagicMock
from unittest.mock import patch

# Mock credentials before importing fetch_emails
sys.modules['credentials'] = MagicMock()
sys.modules['credentials'].EMAIL_ADDRESS = 'test@example.com'
sys.modules['credentials'].EMAIL_PASSWORD = 'password'

import pandas as pd
import pytest

from fetch_emails import fetch_email_messages
from fetch_emails import format_email_df
from fetch_emails import parse_housing_email_message


@pytest.fixture
def mock_imap_connection():
  with patch('imaplib.IMAP4_SSL') as mock_imap:
    mock_conn = MagicMock()
    mock_imap.return_value = mock_conn
    mock_conn.login.return_value = ('OK', [b'Logged in'])
    mock_conn.select.return_value = ('OK', [b'1'])
    mock_conn.search.return_value = ('OK', [b'1 2'])
    yield mock_conn

def test_fetch_email_messages(mock_imap_connection):
  raw_email = b"""From: "Zillow" <daily-updates@mail.zillow.com>
To: seattle.housing.feed@gmail.com
Subject: New Zillow Listings
Date: Mon, 01 Jan 2023 12:00:00 -0000
Content-Type: text/html

<html><body><p>Test Email</p></body></html>
"""
  mock_imap_connection.fetch.return_value = ('OK', [(b'1 (RFC822)', raw_email), b')', (b'2 (RFC822)', raw_email), b')'])

  messages = fetch_email_messages(
      'user', 'pass', ['"Zillow" <daily-updates@mail.zillow.com>'],
      ['seattle.housing.feed@gmail.com'])

  all_messages = [msg for batch in messages for msg in batch]

  assert len(all_messages) == 2
  assert all_messages[0]['Subject'] == 'New Zillow Listings'

def test_parse_housing_email_message():
  msg = email.message.Message()
  msg['From'] = '"Zillow" <daily-updates@mail.zillow.com>'
  msg['To'] = 'seattle.housing.feed@gmail.com'
  msg['Subject'] = 'Test'
  msg['Date'] = 'Mon, 01 Jan 2023 12:00:00 -0000'
  msg.set_payload('''
  <html>
      <body>
    <div>
          <p>$500,000 3 bds, 2 ba, 1500 sqft
             <a href="https://zillow.com/homedetails/1">Link</a>
          </p>
    </div>
      </body>
  </html>
''')
  parsed = parse_housing_email_message(msg)
  assert parsed['Subject'] == 'Test'
  assert parsed['Sender'] == 'Zillow'
  assert len(parsed['properties_list']) == 1
  assert parsed['properties_list'][0]['Price'] == '$500,000'

def test_format_email_df():
  data = [{
      'Date': 'Mon, 01 Jan 2023 12:00:00 -0000',
      'From': 'Zillow',
      'Subject': 'Test Subject',
      'html': '<div>Content</div>'
  }]
  df = pd.DataFrame(data)
  formatted_df = format_email_df(df)

  assert 'title' in formatted_df.columns
  assert formatted_df['html'].iloc[0].startswith('<p style="text-align:center;">')
