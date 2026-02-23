import re
from unittest.mock import mock_open
from unittest.mock import patch

from bs4 import BeautifulSoup
import pytest

from parse_html import clean_html_text
from parse_html import process_historical_html

# --- Test Data & Fixtures ---


@pytest.fixture
def sample_zillow_html():
  """Returns a snippet of Zillow-style HTML with fake data."""
  # Ensure href matches: zpid|WA/|homedetails|urn:msg:|redfin\.com/.*click|click\.mail\.zillow
  return """
  <div>
    <p style="text-align:center;">2026-01-01  :  Zillow</p>
    <p>$950,000 3 bds, 2 ba, 1,850 sqft
           <a href="https://zillow.com/homedetails/123_fake_st">123 Fake St, Seattle, WA 98109</a>
           <span class="statusText">Active</span>
           <span>Open: Sun. 1pm-4pm</span>
           <span>Builder: Fake Builders Inc</span>
    </p>
  </div>
  """


@pytest.fixture
def sample_redfin_html():
  """Returns a snippet of Redfin-style HTML with fake data."""
  # Ensure href matches: redfin\.com/.*click (or just standard redfin link if regex allows)
  # The regex in parse_html.py is: zpid|WA/|homedetails|urn:msg:|redfin\.com/.*click|click\.mail\.zillow
  # Wait, 'redfin.com/WA/Seattle/456-mockingbird' matches 'WA/' part!
  return """
  <div>
    <p style="text-align:center;">2026-01-02  :  Redfin</p>
    <p>$1,200,000 4 Beds · 3 Baths · 2,500 Sq. Ft.
           456 Mockingbird Ln, Seattle, WA 98115
           <a href="https://redfin.com/WA/Seattle/456-mockingbird">Link</a>
           <span class="indicatorText">Price Cut</span>
    </p>
  </div>
  """


# --- Helper Tests ---


def test_clean_html_text():
  """Verifies that HTML text cleaning normalizes spaces and removes zero-width characters."""
  assert clean_html_text("  Hello   World  ") == "Hello World"
  assert clean_html_text("No\u200bSpace") == "NoSpace"
  assert clean_html_text("Non\xa0Breaking\xa0Space") == "Non Breaking Space"
  assert clean_html_text("") == ""
  assert clean_html_text(None) == ""


# --- Extraction Logic Tests ---


@pytest.mark.parametrize("text, expected", [
    ("$1,200,000 for this house", "$1,200,000"),
    ("Price: $950,500", "$950,500"),
    ("No price here", None),
])
def test_price_regex(text, expected):
  """Checks extraction of price strings."""
  match = re.search(r'\$\d{1,3}(?:,\d{3})+', text)
  if expected:
    assert match and match.group(0) == expected
  else:
    assert match is None


@pytest.mark.parametrize("text, expected", [
    ("3 bds", "3"),
    ("4 Beds", "4"),
    ("5 Bedrooms", "5"),
    ("1 Bed", "1"),
    ("Studio", None),
])
def test_beds_regex(text, expected):
  """Checks extraction of bedroom counts."""
  match = re.search(r'(\d+)\s*(?:bd|Beds|Bedrooms?|Bed)', text, re.IGNORECASE)
  if expected:
    assert match and match.group(1) == expected
  else:
    assert match is None


@pytest.mark.parametrize(
    "text, expected_components",
    [
        # Format: (Input Text, {Field: ExpectedValue})
        ("$920,000 4 bd | 4 ba | 1,990 sqft 5555 Mockingbird Ln, Seattle, WA 98103",
         {
             "Price": "$920,000",
             "Beds": "4",
             "Baths": "4",
             "Sqft": "1990",
             "Zip": "98103",
             "Address": "5555 Mockingbird Ln, Seattle, WA 98103"
         }),
        ("$798,000 2 Beds · 2.5 Baths · 968 Sq. Ft. 1234 Fake Street, Seattle, WA 98109",
         {
             "Price": "$798,000",
             "Beds": "2",
             "Baths": "2.5",
             "Sqft": "968",
             "Zip": "98109",
             "Address": "1234 Fake Street, Seattle, WA 98109"
         }),
        ("Builder: Acme Homes LLC. Status: New", {
            "Builder": "Acme Homes LLC",
            "Status": "New"
        })
    ])
def test_comprehensive_extraction_regex(text, expected_components):
  """
  Parametrized test for extracting various fields from text strings.
  Refactored to cover multiple fields in one go for efficiency.
  """
  # Price
  if "Price" in expected_components:
    match = re.search(r'\$\d{1,3}(?:,\d{3})+', text)
    assert match and match.group(0) == expected_components["Price"]

  # Beds
  if "Beds" in expected_components:
    match = re.search(r'(\d+)\s*(?:bd|Beds|Bedrooms?)', text, re.IGNORECASE)
    assert match and match.group(1) == expected_components["Beds"]

  # Baths
  if "Baths" in expected_components:
    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:ba|Baths|Bathrooms?)', text,
                      re.IGNORECASE)
    assert match and match.group(1) == expected_components["Baths"]

  # Sqft
  if "Sqft" in expected_components:
    # Flexible Sqft regex to match "sqft", "sq ft", "Sq. Ft.", "square feet"
    # Debugging: Ensure the text matches the regex
    match = re.search(
        r'(\d+(?:,\d+)?)\s*(?:sq\s*ft\.?|sqft|Sq\.\s*Ft\.|square\s*feet)', text,
        re.IGNORECASE)
    # If match failed, try to debug why (maybe standard regex issue?)
    if not match:
      pytest.fail(f"Sqft Regex failed for text: '{text}'")
    assert match.group(1).replace(',', '') == expected_components["Sqft"]

  # Zip
  if "Zip" in expected_components:
    match = re.search(r'\b(98\d{3})\b', text)
    assert match and match.group(1) == expected_components["Zip"]

    # Address
    if "Address" in expected_components:
      # Using the strict regex from parse_html.py
      match = re.search(
          r'(?<![\$,])\b(\d+\s+(?:(?!(?:Beds?|Baths?|Sqft|Sq\.?\s*Ft\.?|bd|ba)\b)[^,])+,?\s*[A-Za-z\s]+,\s*WA\s+98\d{3})',
          text, re.IGNORECASE)
      assert match and match.group(1) == expected_components["Address"]

  # Builder
  if "Builder" in expected_components:
    match = re.search(r'Builder:\s*([A-Za-z0-9\s]+)', text)
    assert match and match.group(1).strip() == expected_components["Builder"]

  # Status
  if "Status" in expected_components:
    match = re.search(r'\b(Active|New|Price cut)\b', text, re.IGNORECASE)
    assert match and match.group(1).title() == expected_components["Status"]


# --- Integration Tests ---


def test_process_historical_html_zillow(sample_zillow_html):
  """Integration test simulating processing a Zillow email."""
  # We must patch 'open' where it is used in parse_html
  with patch("builtins.open",
             mock_open(read_data=sample_zillow_html)) as mock_file:
    data, stats = process_historical_html("dummy_zillow.html")

  # Debugging assertion
  assert len(data) == 1, f"Expected 1 item, got 0. Stats: {stats}"
  item = data[0]

  assert item["Price"] == "$950,000"
  assert item["Beds"] == "3"
  assert item["Baths"] == "2"
  assert item["Sqft"] == "1850"
  assert item["Address"] == "123 Fake St, Seattle, WA 98109"
  assert item["Zip"] == "98109"
  assert item["Status"] == "Active"
  assert item["Open_House"] == "Sun. 1pm-4pm"
  assert item["Builder"] == "Fake Builders Inc"
  assert item["Source"] == "Zillow"


def test_process_historical_html_redfin(sample_redfin_html):
  """Integration test simulating processing a Redfin email."""
  with patch("builtins.open", mock_open(read_data=sample_redfin_html)):
    data, stats = process_historical_html("dummy_redfin.html")

  assert len(data) == 1, f"Expected 1 item, got 0. Stats: {stats}"
  item = data[0]

  assert item["Price"] == "$1,200,000"
  assert item["Beds"] == "4"
  assert item["Address"] == "456 Mockingbird Ln, Seattle, WA 98115"
  assert item["Status"] == "Price Cut"
  assert item["Source"] == "Redfin"


def test_fallback_address_extraction():
  """
  Tests the fallback logic where address is not in a clear <a> tag
  but embedded in textual content, without getting confused by '3 Beds'.
  """
  html_content = """
  <p style="text-align:center;">2026-05-01 : Test Source</p>
  <div>
    <!-- Tricky case: 3 Beds appearing before address components -->
    <p>$880,000 3 Beds
           Some Text 8888 Test Drive NE, Seattle, WA 98115
           More Text
           <a href="https://redfin.com/WA/Test/Link">Link</a>
    </p>
  </div>
  """
  with patch("builtins.open", mock_open(read_data=html_content)):
    data, stats = process_historical_html("dummy_fallback.html")

  assert len(data) == 1
  assert data[0]["Address"] == "8888 Test Drive NE, Seattle, WA 98115"
  assert data[0]["Zip"] == "98115"
