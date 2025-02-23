import sys
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import pdfplumber
import sqlite3
import pandas as pd
import re
from fuzzywuzzy import fuzz
from urllib.parse import urljoin
import os

# Constants
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
CURRENT_YEAR = 2024  # Fallback if filename parsing fails
TEMP_DIR = 'temp'    # Directory for downloaded PDFs
DB_FILE = 'voters.db'  # SQLite database file

# Initialize headless Chrome driver
def initialize_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=chrome_options)

# Get rendered HTML from a URL
def get_rendered_html(url, driver):
    driver.get(url)
    time.sleep(5)  # Wait for JavaScript to load
    return driver.page_source

# Find GovDelivery URLs in HTML
def find_govdelivery_urls(html):
    soup = BeautifulSoup(html, 'html.parser')
    return [a['href'] for a in soup.find_all('a', href=True) if a['href'].startswith("https://content.govdelivery.com/")]

# Extract PDF URLs from a GovDelivery page
def find_pdf_urls_from_page(page_url):
    try:
        response = requests.get(page_url, headers={'User-Agent': USER_AGENT})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        pdf_urls = [urljoin(page_url, a['href']) for a in soup.find_all('a', href=True) if a['href'].lower().endswith('.pdf')]
        return pdf_urls
    except requests.RequestException as e:
        print(f"Error fetching {page_url}: {e}")
        return []

# Download PDF and return its filepath
def download_pdf(pdf_url, temp_dir):
    try:
        filename = pdf_url.split('/')[-1].replace('%20', '_')  # Replace URL-encoded spaces with underscores
        filepath = os.path.join(temp_dir, filename)
        response = requests.get(pdf_url)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(response.content)
        return filepath
    except requests.RequestException as e:
        print(f"Error downloading PDF {pdf_url}: {e}")
        return None

# Extract names and ages from PDF
def extract_names_and_ages_from_pdf(pdf_path):
    try:
        names_and_ages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                text = text.replace('\n', ' <NEWLINE> ')
                case_pattern = r'(\d{2}-\d{5})'
                matches = list(re.finditer(case_pattern, text))
                for i, match in enumerate(matches):
                    start_idx = match.start()
                    end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                    entry_text = text[start_idx:end_idx]
                    case_num = match.group(1)
                    age_pattern = r'(\d+)\s*years'
                    age_match = re.search(age_pattern, entry_text)
                    if not age_match:
                        continue
                    age = int(age_match.group(1))
                    name_end_idx = age_match.start()
                    name_text = entry_text[len(case_num):name_end_idx].strip()
                    name = re.sub(r'(<NEWLINE>|<br>)', ' ', name_text).strip()
                    name = ' '.join(name.split())
                    names_and_ages.append((name.lower(), age))
        return names_and_ages
    except pdfplumber.PDFSyntaxError as e:
        print(f"Error processing PDF {pdf_path}: {e}")
        return []

# Extract year from PDF filename (e.g., "Decedents List_12312024.pdf")
def extract_year_from_filename(filename):
    # Clean filename to handle URL-encoded spaces or underscores
    filename = filename.replace('%20', '_')
    # Find the first 8-digit number (MMDDYYYY)
    date_match = re.search(r'\d{8}', filename)
    if date_match:
        date_str = date_match.group(0)
        # Extract the last 4 digits as the year
        year = date_str[-4:]
        return int(year)
    return None

# Load voter data into SQLite
def load_voter_registration_to_sqlite(filename):
    try:
        columns = [
            'StateVoterID', 'FName', 'MName', 'LName', 'NameSuffix', 'Birthyear', 'Gender',
            'RegStNum', 'RegStFrac', 'RegStName', 'RegStType', 'RegUnitType', 'RegStPreDirection',
            'RegStPostDirection', 'RegStUnitNum', 'RegCity', 'RegState', 'RegZipCode', 'CountyCode',
            'PrecinctCode', 'PrecinctPart', 'LegislativeDistrict', 'CongressionalDistrict',
            'Mail1', 'Mail2', 'Mail3', 'MailCity', 'MailZip', 'MailState', 'MailCountry',
            'Registrationdate', 'LastVoted', 'StatusCode'
        ]
        df = pd.read_csv(filename, delimiter='|', names=columns, header=0, encoding='windows-1252')
        df = df.dropna(subset=['Birthyear'])
        df['Birthyear'] = df['Birthyear'].astype(int)
        df['FullName'] = (
            df['LName'].str.lower().fillna('') + ', ' + 
            df['FName'].str.lower().fillna('') + ' ' + 
            df['MName'].str.lower().fillna('')
        ).str.replace(r'\s+', ' ', regex=True).str.strip()
        
        conn = sqlite3.connect(DB_FILE)
        df[['StateVoterID', 'FullName', 'Birthyear', 'LastVoted', 'StatusCode']].to_sql('voters', conn, if_exists='replace', index=False)
        conn.execute('CREATE INDEX idx_name_birthyear ON voters (FullName, Birthyear)')
        print(f"Loaded {len(df)} voter records into SQLite database.")
        return conn
    except (FileNotFoundError, pd.errors.EmptyDataError) as e:
        print(f"Error loading voter file {filename}: {e}")
        return None

# Match decedents with voters using the PDF year
def match_decedents_with_voters(decedents, conn, pdf_year):
    matches = []
    cursor = conn.cursor()
    
    for name, age in decedents:
        # Use pdf_year if available, otherwise fall back to CURRENT_YEAR
        reference_year = pdf_year if pdf_year else CURRENT_YEAR
        possible_birth_years = [reference_year - age - 1, reference_year - age, reference_year - age + 1]
        
        query = """
            SELECT StateVoterID, FullName, Birthyear, LastVoted, StatusCode
            FROM voters
            WHERE Birthyear IN (?, ?, ?)
        """
        cursor.execute(query, possible_birth_years)
        rows = cursor.fetchall()
        
        for row in rows:
            voter_id, voter_name, birthyear, last_voted, status_code = row
            similarity = fuzz.token_set_ratio(name, voter_name)
            if similarity > 90:
                matches.append({
                    'StateVoterID': voter_id,
                    'Name': name,
                    'Birthyear': birthyear,
                    'LastVoted': last_voted,
                    'StatusCode': status_code
                })
    
    return matches

# Main execution flow
def main(page_url):
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
        print(f"Created directory: {TEMP_DIR}")

    driver = initialize_driver()
    try:
        print(f"Loading page: {page_url}")
        rendered_html = get_rendered_html(page_url, driver)
        govdelivery_urls = find_govdelivery_urls(rendered_html)
        
        if not govdelivery_urls:
            print("No GovDelivery URLs found.")
            return

        all_pdf_urls = []
        for url in govdelivery_urls:
            print(f"Processing GovDelivery URL: {url}")
            pdf_urls = find_pdf_urls_from_page(url)
            all_pdf_urls.extend(pdf_urls)

        if not all_pdf_urls:
            print("No PDF URLs found.")
            return

        for pdf_url in all_pdf_urls:
            print(f"\nProcessing PDF: {pdf_url}")
            pdf_path = download_pdf(pdf_url, TEMP_DIR)
  
    finally:
        driver.quit()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <page_url>")
        sys.exit(1)
    
    page_url = sys.argv[1]
    main(page_url)
