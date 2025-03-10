import sys
import os
import re
from datetime import datetime, timedelta
import pdfplumber
import sqlite3
import pandas as pd
from fuzzywuzzy import fuzz

# Constants
TEMP_DIR = 'temp'  # Directory for PDFs
DB_FILE = 'voters.db'  # SQLite database file
CURRENT_YEAR = 2024  # Fallback year if filename parsing fails

# Extract date from filename (e.g., "Decedents_List_10152024.pdf")
def extract_date_from_filename(filename):
    date_match = re.search(r'\d{8}', filename)
    if date_match:
        date_str = date_match.group(0)
        try:
            return datetime.strptime(date_str, '%m%d%Y')
        except ValueError:
            print(f"Invalid date format in {filename}: {date_str}")
            return None
    print(f"No date found in {filename}")
    return None

# Check if the file is older than two months
def is_older_than_two_months(file_date):
    two_months_ago = datetime.now() - timedelta(days=60)
    return file_date < two_months_ago

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

# Split a name into first, middle, and last components
def split_name(name):
    tokens = name.strip().lower().split()
    if len(tokens) < 2:
        return None, None, None
    first = tokens[0]
    last = tokens[-1]
    middle = ' '.join(tokens[1:-1]) if len(tokens) > 2 else ''
    return first, middle, last

# Custom name matching function
def is_name_match(decedent_name, voter_name):
    first1, middle1, last1 = split_name(decedent_name)
    first2, middle2, last2 = split_name(voter_name)
    if first1 is None or first2 is None:
        return False
    # Require high similarity for first and last names
    first_sim = fuzz.ratio(first1, first2)
    last_sim = fuzz.ratio(last1, last2)
    if first_sim > 90 and last_sim > 90:
        if middle1 and middle2:
            # Both have middle names: match if equal or one is initial of the other
            if middle1 == middle2:
                return True
            elif len(middle1) == 1 and middle2.startswith(middle1):
                return True
            elif len(middle2) == 1 and middle1.startswith(middle2):
                return True
            else:
                return False  # Middle names don't match
        else:
            # No middle names or one is missing: still a match
            return True
    else:
        return False

# Load voter registration into SQLite, storing full lines if DB doesn't exist
def load_voter_registration_to_sqlite(voter_file):
    if os.path.exists(DB_FILE):
        print(f"Database '{DB_FILE}' already exists. Skipping data loading.")
        return sqlite3.connect(DB_FILE)
    
    try:
        df = pd.read_csv(voter_file, delimiter='|', header=0, dtype=str, names=[
            'StateVoterID', 'FName', 'MName', 'LName', 'NameSuffix', 'Birthyear', 'Gender',
            'RegStNum', 'RegStFrac', 'RegStName', 'RegStType', 'RegUnitType', 'RegStPreDirection',
            'RegStPostDirection', 'RegStUnitNum', 'RegStCity', 'RegState', 'RegZipCode', 'CountyCode',
            'PrecinctCode', 'PrecinctPart', 'LegislativeDistrict', 'CongressionalDistrict',
            'Mail1', 'Mail2', 'Mail3', 'MailCity', 'MailZip', 'MailState', 'MailCountry',
            'Registrationdate', 'LastVoted', 'StatusCode'
        ], encoding='windows-1252')
        
        df['FullName'] = (
            df['FName'].str.lower().fillna('') + ' ' +
            df['MName'].str.lower().fillna('') + ' ' +
            df['LName'].str.lower().fillna('')
        ).str.replace(r'\s+', ' ', regex=True).str.strip()
        
        df['Birthyear'] = pd.to_numeric(df['Birthyear'], errors='coerce')
        df = df.dropna(subset=['Birthyear'])
        df['Birthyear'] = df['Birthyear'].astype(int)
        
        conn = sqlite3.connect(DB_FILE)
        # Store all columns in the database
        df.to_sql('voters', conn, if_exists='replace', index=False)
        conn.execute('CREATE INDEX idx_name_birthyear ON voters (FullName, Birthyear)')
        print(f"Loaded {len(df)} voter records into SQLite database.")
        return conn
    except (FileNotFoundError, pd.errors.EmptyDataError) as e:
        print(f"Error loading voter file {voter_file}: {e}")
        return None

# Match decedents with voters, retrieving the full original line
def match_decedents_with_voters(decedents, conn, pdf_year):
    matches = []
    cursor = conn.cursor()
    
    for name, age in decedents:
        reference_year = pdf_year if pdf_year else CURRENT_YEAR
        possible_birth_years = [reference_year - age - 1, reference_year - age]
        
        query = """
            SELECT FName, MName, LName, NameSuffix, Birthyear, Gender,
                   RegStNum, RegStFrac, RegStName, RegStType, RegUnitType,
                   RegStPreDirection, RegStPostDirection, RegStUnitNum,
                   RegStCity, RegState, RegZipCode, CountyCode,
                   PrecinctCode, PrecinctPart, LegislativeDistrict,
                   CongressionalDistrict, Mail1, Mail2, Mail3, MailCity,
                   MailZip, MailState, MailCountry, Registrationdate,
                   LastVoted, StatusCode
            FROM voters
            WHERE Birthyear IN (?, ?)
        """
        cursor.execute(query, possible_birth_years)
        rows = cursor.fetchall()
        
        for row in rows:
            voter_name = f"{row[0]} {row[1]} {row[2]}".strip().lower()
            if is_name_match(name, voter_name):
                matches.append({
                    'Name': name,
                    'VoterInfo': {
                        'FName': row[0],
                        'MName': row[1],
                        'LName': row[2],
                        'NameSuffix': row[3],
                        'Birthyear': row[4],
                        'Gender': row[5],
                        'RegStNum': row[6],
                        'RegStFrac': row[7],
                        'RegStName': row[8],
                        'RegStType': row[9],
                        'RegUnitType': row[10],
                        'RegStPreDirection': row[11],
                        'RegStPostDirection': row[12],
                        'RegStUnitNum': row[13],
                        'RegStCity': row[14],
                        'RegState': row[15],
                        'RegZipCode': row[16],
                        'CountyCode': row[17],
                        'PrecinctCode': row[18],
                        'PrecinctPart': row[19],
                        'LegislativeDistrict': row[20],
                        'CongressionalDistrict': row[21],
                        'Mail1': row[22],
                        'Mail2': row[23],
                        'Mail3': row[24],
                        'MailCity': row[25],
                        'MailZip': row[26],
                        'MailState': row[27],
                        'MailCountry': row[28],
                        'Registrationdate': row[29],
                        'LastVoted': row[30],
                        'StatusCode': row[31]
                    }
                })
    
    return matches

def format_voter_info(voter_info):
    """Format voter information in a readable way."""
    return {
        'name': f"{voter_info['FName']} {voter_info['MName']} {voter_info['LName']}".strip(),
        'address': f"{voter_info['RegStNum']} {voter_info['RegStFrac']} {voter_info['RegStName']} {voter_info['RegStType']} {voter_info['RegUnitType']} {voter_info['RegStPreDirection']} {voter_info['RegStPostDirection']} {voter_info['RegStUnitNum']}".strip(),
        'city': voter_info['RegStCity'],
        'zip': voter_info['RegZipCode'],
        'birth_year': voter_info['Birthyear'],
        'registration_date': voter_info['Registrationdate'],
        'last_voted': voter_info['LastVoted'],
        'status': voter_info['StatusCode'],
        'precinct': f"{voter_info['PrecinctCode']}{voter_info['PrecinctPart']}",
        'legislative_district': voter_info['LegislativeDistrict'],
        'congressional_district': voter_info['CongressionalDistrict'],
        'mailing_address': f"{voter_info['Mail1']} {voter_info['Mail2']} {voter_info['Mail3']}".strip(),
        'mailing_city': voter_info['MailCity'],
        'mailing_zip': voter_info['MailZip'],
        'mailing_state': voter_info['MailState']
    }

def generate_report(matches, pdf_file, pdf_date):
    """Generate a formatted report for the matches found in a PDF file."""
    if not matches:
        return f"\nNo matches found in {pdf_file} (dated {pdf_date.strftime('%m/%d/%Y')})"
    
    report = []
    report.append(f"\n{'='*80}")
    report.append(f"Report for {pdf_file}")
    report.append(f"PDF Date: {pdf_date.strftime('%m/%d/%Y')}")
    report.append(f"Total Matches Found: {len(matches)}")
    report.append(f"{'='*80}\n")
    
    for i, match in enumerate(matches, 1):
        voter_info = format_voter_info(match['VoterInfo'])
        report.append(f"Match #{i}")
        report.append(f"{'-'*40}")
        report.append(f"Decedent Name: {match['Name']}")
        report.append(f"Voter Name: {voter_info['name']}")
        report.append(f"Registration Address: {voter_info['address']}")
        report.append(f"City: {voter_info['city']}")
        report.append(f"ZIP: {voter_info['zip']}")
        report.append(f"Precinct: {voter_info['precinct']}")
        report.append(f"Legislative District: {voter_info['legislative_district']}")
        report.append(f"Congressional District: {voter_info['congressional_district']}")
        report.append(f"Birth Year: {voter_info['birth_year']}")
        report.append(f"Registration Date: {voter_info['registration_date']}")
        report.append(f"Last Voted: {voter_info['last_voted']}")
        report.append(f"Status: {voter_info['status']}")
        if voter_info['mailing_address']:
            report.append("\nMailing Address:")
            report.append(f"  {voter_info['mailing_address']}")
            report.append(f"  {voter_info['mailing_city']}, {voter_info['mailing_state']} {voter_info['mailing_zip']}")
        report.append(f"{'-'*40}\n")
    
    return '\n'.join(report)

def main(pdf_folder, voter_file):
    conn = load_voter_registration_to_sqlite(voter_file)
    if conn is None:
        return

    pdf_files = [f for f in os.listdir(pdf_folder) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"No PDF files found in {pdf_folder}.")
        return

    print(f"Found {len(pdf_files)} PDF files in {pdf_folder}. Processing...")
    
    total_matches = 0
    reports = []

    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_folder, pdf_file)
        print(f"\nProcessing {pdf_file}...")

        pdf_date = extract_date_from_filename(pdf_file)
        if not pdf_date:
            print(f"Skipping {pdf_file}: Could not determine date.")
            continue

        if not is_older_than_two_months(pdf_date):
            print(f"Skipping {pdf_file}: Date {pdf_date.strftime('%m/%d/%Y')} is within the last 2 months.")
            continue

        pdf_year = pdf_date.year

        decedents = extract_names_and_ages_from_pdf(pdf_path)
        if not decedents:
            print(f"No decedents found in {pdf_file}.")
            continue

        print(f"Found {len(decedents)} decedents in {pdf_file}.")
        print("Matching with voter records...")

        matches = match_decedents_with_voters(decedents, conn, pdf_year)
        total_matches += len(matches)
        
        report = generate_report(matches, pdf_file, pdf_date)
        reports.append(report)
        print(report)

    # Print summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total PDF files processed: {len(pdf_files)}")
    print(f"Total matches found across all files: {total_matches}")
    print(f"Average matches per file: {total_matches/len(pdf_files):.1f}")
    print(f"{'='*80}\n")

    conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python script.py <pdf_folder> <voter_file>")
        sys.exit(1)

    pdf_folder = sys.argv[1]
    voter_file = sys.argv[2]
    main(pdf_folder, voter_file)
