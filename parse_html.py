import argparse
import glob
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm

import generate_report

logger = logging.getLogger(__name__)


# CONFIGURATION
INPUT_FILES_PATTERN = 'listings/*.html'
DATABASE_OUTPUT_FILE = 'housing_database.tsv'

# Parsing Rules
POTENTIAL_PROPERTY_TYPES = [
    'Condo', 'Townhome', 'Townhouse', 'House', 'Multi-Family', 'Single Family',
    'Co-op', 'Studio', 'Apartment', 'Home', 'Residence'
]

TYPE_NORMALIZATION_MAPPING = {
    'Single Family': 'House',
    'House': 'House',
    'Townhome': 'Townhouse',
    'Townhouse': 'Townhouse',
    'Multi-Family': 'Multi-Family',
    'Multi-family': 'Multi-Family',
    'Co-op': 'Co-op',
    'Coop': 'Co-op'
}

# Compiled Regex Patterns
PRICE_RE = re.compile(r'\$\d{1,3}(?:,\d{3})*')
BEDS_RE = re.compile(r'(\d+)\s*(?:bd|Beds|Bds|Bedrooms?|Bed)', re.IGNORECASE)
BATHS_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:ba|Baths|Bths|Bathrooms?|Bath)', re.IGNORECASE)
SQFT_RE = re.compile(r'(\d+(?:,\d+)?)\s*(?:sq\s*ft\.?|sqft|Sq\.\s*Ft\.|square\s*feet)', re.IGNORECASE)
ZIP_RE = re.compile(r'\b(98\d{3})\b')
CITY_WA_RE = re.compile(r'([A-Za-z\s]+),\s*(WA)\b')
TYPE_RE = re.compile(
    r'\b(Condo|Townhome|Townhouse|House|Multi-Family|Multi-family|Single Family|Single Family Residence|Co-?op|Apartment|Loft|Triplex|Fourplex|Duplex|Manufactured|Mobile)\b',
    re.IGNORECASE)
ADDRESS_LINK_RE = re.compile(r'WA\s+98\d{3}')
# Complex address regex: Lookbehind to avoid price, Lookahead to avoid amenities
ADDRESS_TEXT_RE = re.compile(
    r'(?<![\$,])\b(\d+\s+(?:(?!(?:Beds?|Baths?|Sqft|Sq\.?\s*Ft\.?|bd|ba)\b)[^,])+,?\s*[A-Za-z\s]+,\s*WA\s+98\d{3})',
    re.IGNORECASE)
STATUS_RE = re.compile(r'\b(Active|New|Price cut)\b', re.IGNORECASE)
OPEN_HOUSE_RE = re.compile(
    r'(?:Open:?\s*)?((?:Sun|Mon|Tue|Wed|Thu|Fri|Sat)\.?\s*[\d:apm\-\s,]+(?:am|pm))',
    re.IGNORECASE)
BUILDER_RE = re.compile(r'Builder:\s*([A-Za-z0-9\s]+)')
LINK_RE = re.compile(
    r'zpid|WA/|homedetails|urn:msg:|redfin\.com/.*click|click\.mail\.zillow',
    re.IGNORECASE)

# Pre-compile header type pattern
HEADER_TYPE_RE = re.compile(
    r'\b(' + '|'.join(map(re.escape, POTENTIAL_PROPERTY_TYPES)) + r')\b',
    re.IGNORECASE)

def clean_html_text(text: Optional[str]) -> str:
  """Removes zero-width characters and normalizes spacing from BeautifulSoup text."""
  if not text:
    return ""
  text = text.replace('\u200c', '').replace('\u200b', '').replace('\xa0', ' ')
  return ' '.join(text.split())


def process_historical_html(file_path):
  with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

  soup = BeautifulSoup(content, 'html.parser')
  extracted_data = []

  stats = {
      'emails_parsed': 0,
      'properties_found': 0,
      'missing_price': 0,
      'missing_beds': 0,
      'missing_baths': 0,
      'missing_sqft': 0,
      'missing_link': 0,
      'missing_city': 0,
      'missing_zip': 0,
      'missing_type': 0,
      'missing_address': 0,
      'missing_status': 0,
      'missing_open_house': 0,
      'missing_builder': 0
  }

  # Iterate over all emails separated by <p style="text-align:center;">
  headers = soup.find_all('p', style="text-align:center;")

  for header in headers:
    header_text = header.get_text(strip=True)
    if '  :  ' in header_text:
      parts = header_text.split('  :  ')
      if len(parts) >= 3:
        date_str, source, subject = parts[0], parts[1], parts[2]
      elif len(parts) == 2:
        date_str, source = parts[0], parts[1]
        subject = ""
      else:
        date_str, source = header_text, ''
        subject = ""
    else:
      date_str, source = header_text, ''
      subject = ""

    # Get elements until next header
    sibling = header.find_next_sibling()
    html_chunk = []
    while sibling:
      if sibling.name == 'p' and sibling.get('style') == "text-align:center;":
        break
      if sibling.name:
        html_chunk.append(str(sibling))
      sibling = sibling.find_next_sibling()

    email_soup = BeautifulSoup("".join(html_chunk), 'html.parser')

    # Header/Subject Parsing
    # Use the subject line if available, otherwise fall back to scanning the start of the email text
    # Text to scan: Subject + first 5000 chars of body
    body_text = clean_html_text(email_soup.get_text(separator=' '))[:5000]
    text_to_scan = f"{subject} {body_text}" if subject else body_text

    # Optimized Header Type Search
    header_inferred_types = HEADER_TYPE_RE.findall(text_to_scan)

    # Normalize inferred types
    normalized_header_types = {}
    for pt in header_inferred_types:
      title_pt = pt.title()
      normalized_header_types[TYPE_NORMALIZATION_MAPPING.get(title_pt, title_pt)] = True

    normalized_header_types = list(normalized_header_types.keys())

    properties_found = {}

    for a in email_soup.find_all('a', href=LINK_RE):
      url = a['href']
      parent = a.parent
      while parent and '$' not in parent.get_text():
        parent = parent.parent
        if not parent:
          break

      if not parent:
        continue

      text = clean_html_text(parent.get_text(separator=' '))
      price_match = PRICE_RE.search(text)
      if not price_match:
        continue

      price = price_match.group(0)
      beds_match = BEDS_RE.search(text)
      beds = beds_match.group(1) if beds_match else ''

      key = f"{price}_{beds}_{url[:50]}"
      if key not in properties_found:
        properties_found[key] = (text, url, parent)

    # Fallback for single-property emails that might lack a distinct link structure
    if not properties_found:
      text = clean_html_text(email_soup.get_text(separator=' '))
      if PRICE_RE.search(text):
        link_elem = email_soup.find('a', href=LINK_RE)
        url = link_elem.get('href') if link_elem else ''
        properties_found['fallback'] = (text, url, None)

    stats['emails_parsed'] += 1

    for key, (text, listing_link, parent) in properties_found.items():
      # Base RegEx Parsing
      price_match = PRICE_RE.search(text)
      price = price_match.group(0) if price_match else ''

      beds_match = BEDS_RE.search(text)
      beds = beds_match.group(1) if beds_match else ''

      baths_match = BATHS_RE.search(text)
      baths = baths_match.group(1) if baths_match else ''

      sqft_match = SQFT_RE.search(text)
      sqft = sqft_match.group(1).replace(',', '') if sqft_match else ''

      # Location and Type Parsers
      zip_match = ZIP_RE.search(text)
      zip_code = zip_match.group(1) if zip_match else ''

      type_match = TYPE_RE.search(text)
      prop_type = type_match.group(1).title() if type_match else 'Unknown'

      # Standardize Property Types
      prop_type = TYPE_NORMALIZATION_MAPPING.get(prop_type, prop_type)
      if prop_type in ['Single Family', 'Single Family Residence', 'House']: prop_type = 'House'

      city_match = CITY_WA_RE.search(text)
      city = city_match.group(1).strip() if city_match else ''

      # New Fields Extraction
      address = ''
      if parent:
        # Try to find address in anchor tags matching zip pattern
        for a_tag in parent.find_all('a'):
          a_text = clean_html_text(a_tag.get_text(separator=' '))
          if ADDRESS_LINK_RE.search(a_text):
            address = a_text.strip()
            break

      if not address:
        address_match = ADDRESS_TEXT_RE.search(text)
        address = address_match.group(1).strip() if address_match else ''

      status_match = STATUS_RE.search(text)
      status = status_match.group(1).title() if status_match else ''

      open_house_match = OPEN_HOUSE_RE.search(text)
      open_house = open_house_match.group(1).strip() if open_house_match else ''

      builder_match = BUILDER_RE.search(text)
      builder = builder_match.group(1).strip() if builder_match else ''

      # Expanded Search Fallbacks
      pp = parent
      levels = 0
      while pp and levels < 5 and (not zip_code or not prop_type or not city or
                                   not address):
        if pp.name in ['body', 'html', '[document]']:
          break
        broader_text = clean_html_text(pp.get_text(separator=' '))
        if not zip_code:
          zip_match = ZIP_RE.search(broader_text)
          if zip_match:
            zip_code = zip_match.group(1)
        if not prop_type or prop_type == 'Unknown':
          type_match = TYPE_RE.search(broader_text)
          if type_match:
            prop_type = type_match.group(1).title()

        # Fallback to URL parsing if still unknown
        if (not prop_type or prop_type == 'Unknown') and listing_link:
          url_lower = listing_link.lower()
          if '/condo' in url_lower:
            prop_type = 'Condo'
          elif '/townhouse' in url_lower or '/townhome' in url_lower:
            prop_type = 'Townhouse'
          elif '/home/' in url_lower or '/house' in url_lower:
            prop_type = 'House'
          elif '/apartment' in url_lower:
            prop_type = 'Apartment'
          elif '/multi-family' in url_lower:
            prop_type = 'Multi-Family'

        if (not prop_type or prop_type == 'Unknown') and logger.level <= logging.DEBUG:
          logger.debug("UNKNOWN_PROP_TYPE: Link=%s Text='%s'", listing_link, broader_text[:100])

        if prop_type:
          prop_type = TYPE_NORMALIZATION_MAPPING.get(prop_type, prop_type)
          if prop_type in ['Single Family', 'Single Family Residence', 'House']: prop_type = 'House'

        if not city:
          city_match = CITY_WA_RE.search(broader_text)
          if city_match:
            city = city_match.group(1).strip()
        if not address:
          # Try finding address in sub-elements first
          if pp:
            for a_tag in pp.find_all('a', limit=50):
              a_text = clean_html_text(a_tag.get_text(separator=' '))
              if ADDRESS_LINK_RE.search(a_text):
                address = a_text.strip()
                break
          if not address:
            address_match = ADDRESS_TEXT_RE.search(broader_text)
            if address_match:
              address = address_match.group(1).strip()

        pp = pp.parent
        levels += 1

      stats['properties_found'] += 1
      if not price: stats['missing_price'] += 1
      if not beds: stats['missing_beds'] += 1
      if not baths: stats['missing_baths'] += 1
      if not sqft: stats['missing_sqft'] += 1
      if not listing_link: stats['missing_link'] += 1
      if not city: stats['missing_city'] += 1
      if not zip_code: stats['missing_zip'] += 1
      if not prop_type or prop_type == 'Unknown':
        # Try to use header inference if available
        if len(normalized_header_types) == 1:
          prop_type = normalized_header_types[0]

        # Final Normalization Check
        prop_type = TYPE_NORMALIZATION_MAPPING.get(prop_type, prop_type)
        if prop_type in ['Single Family', 'Single Family Residence', 'House']: prop_type = 'House'

        if not prop_type or prop_type == 'Unknown':
          stats['missing_type'] += 1
      if not address: stats['missing_address'] += 1
      if not status: stats['missing_status'] += 1
      if not open_house: stats['missing_open_house'] += 1
      if not builder: stats['missing_builder'] += 1

      extracted_data.append({
          'Date': date_str,
          'Source': source,
          'Email_Subject': '',  # Subject wasn't preserved in HTML output
          'Property_Type': prop_type,
          'City': city,
          'Zip': zip_code,
          'Address': address,
          'Status': status,
          'Open_House': open_house,
          'Builder': builder,
          'Price': price,
          'Beds': beds,
          'Baths': baths,
          'Sqft': sqft,
          'Listing_Link': listing_link
      })

  return extracted_data, stats


def main(args):
  logger.info("Processing historical index*.html files...")

  if args.file:
    html_files = glob.glob(args.file)
    logger.info("Processing manually specified file(s): %s", args.file)
  else:
    html_files = [f for f in glob.glob(INPUT_FILES_PATTERN) if not f.endswith('index.html')]

  all_data = []
  # Initialize stats with 0
  total_stats = {k: 0 for k in [
      'emails_parsed', 'properties_found', 'missing_price', 'missing_beds',
      'missing_baths', 'missing_sqft', 'missing_link', 'missing_city',
      'missing_zip', 'missing_type', 'missing_address', 'missing_status',
      'missing_open_house', 'missing_builder'
  ]}

  for file in tqdm(html_files, desc="Parsing HTML Pages", unit="page"):
    logger.debug("Parsing %s...", file)
    data, stats = process_historical_html(file)
    all_data.extend(data)
    for k in total_stats:
      total_stats[k] += stats.get(k, 0)

  if not all_data:
    logger.warning("No historical data found.")
    return

  df = pd.DataFrame(all_data)
  logger.info("Total records before deduplication: %d", len(df))

  # 1. Strict Deduplication (same link, price, date)
  len_before = len(df)
  df.drop_duplicates(subset=['Listing_Link', 'Price', 'Date'], inplace=True)
  logger.info("Dropped %d strict duplicates.", len_before - len(df))

  # 2. Content Deduplication (Address-aware)
  # Only dedupe items with valid Address/Zip to prevent data loss.
  len_before = len(df)
  valid_loc_mask = (df['Address'].str.strip().astype(bool) & df['Zip'].str.strip().astype(bool))

  clean_part = df[valid_loc_mask].drop_duplicates(
      subset=['Price', 'Beds', 'Baths', 'Sqft', 'Zip', 'Address', 'Date'],
      keep='last'
  )

  df = pd.concat([clean_part, df[~valid_loc_mask]]).sort_values('Date')
  logger.info("Dropped %d content duplicates.", len_before - len(df))

  # Clean numerical columns
  for col in ['Price', 'Beds', 'Baths', 'Sqft', 'Zip']:
    df[col] = df[col].astype(str).replace(r'[^\d.]', '', regex=True)
    df[col] = pd.to_numeric(df[col], errors='coerce')

  # Finalize
  df['Date'] = pd.to_datetime(df['Date'], errors='coerce', utc=True)
  df.sort_values('Date', inplace=True)
  df.to_csv(DATABASE_OUTPUT_FILE, sep='\t', index=False)
  logger.info("Saved %d records to %s.", len(df), DATABASE_OUTPUT_FILE)

  # Reports
  logger.info("Generating reports...")
  plot_files = generate_report.generate_plots(df)

  if os.path.exists('.email_cache.tsv'):
    try:
      # Efficient line count (minus header)
      with open('.email_cache.tsv', 'r', encoding='utf-8') as f:
        total_stats['cache_total'] = sum(1 for _ in f) - 1
    except Exception as e:
      logger.warning("Cache stats error: %s", e)

  report_content = generate_report.create_report_content(df, total_stats, plot_files)
  generate_report.inject_report_into_readme(report_content)
  logger.info("Report injected into README.md.")


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description="Parse scraped housing HTML to TSV database.")
  parser.add_argument('--debug', action='store_true', help='Enable debug logging')
  parser.add_argument('--file', type=str, help='Process only a specific HTML file (glob pattern supported)')
  args = parser.parse_args()

  log_level = logging.DEBUG if args.debug else logging.INFO
  generate_report.setup_logging('parse_html', log_level)

  main(args)
