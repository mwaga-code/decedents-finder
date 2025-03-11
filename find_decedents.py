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

# Extract names and ages from PDF
def extract_names_and_ages_from_pdf(pdf_path):
    try:
        names_and_ages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                
                # First, find all case numbers and their positions
                case_pattern = r'(\d{2}-\d{5})'
                case_matches = list(re.finditer(case_pattern, text))
                
                for i, match in enumerate(case_matches):
                    start_idx = match.start()
                    end_idx = case_matches[i + 1].start() if i + 1 < len(case_matches) else len(text)
                    entry_text = text[start_idx:end_idx]
                    case_num = match.group(1)
                    
                    # Look for the age pattern
                    age_pattern = r'(\d+)\s*years\s*(Male|Female)'
                    age_match = re.search(age_pattern, entry_text)
                    if not age_match:
                        continue
                    
                    age = int(age_match.group(1))
                    
                    # Get text before and after the age
                    before_age = entry_text[len(case_num):age_match.start()].strip()
                    after_age = entry_text[age_match.end():].strip()
                    
                    # Extract name parts
                    name_parts = []
                    
                    # Add the part before age
                    if before_age:
                        name_parts.append(before_age)
                    
                    # Look for additional name parts after "Male/Female"
                    if after_age:
                        # Split at "Date of Incident" and take the first part
                        additional_text = after_age.split('Date of Incident')[0].strip()
                        
                        # Remove city names and dates
                        cities = ['Seattle', 'Renton', 'Federal Way', 'Des Moines']
                        date_pattern = r'\d{1,2}/\d{1,2}/\d{4}'
                        
                        # Remove dates
                        additional_text = re.sub(date_pattern, '', additional_text)
                        
                        # Remove cities
                        for city in cities:
                            additional_text = additional_text.replace(city, '')
                        
                        # Clean up any remaining text
                        additional_text = additional_text.strip()
                        
                        if additional_text:
                            name_parts.append(additional_text)
                    
                    # Combine and clean up the name
                    name = ' '.join(' '.join(name_parts).split())
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

# Extract date from voter registration filename (e.g., "20250203_VRDB_Extract.txt")
def extract_date_from_voter_file(filename):
    date_match = re.search(r'^(\d{8})_', os.path.basename(filename))
    if date_match:
        return date_match.group(1)
    # Use today's date as fallback
    today = datetime.now()
    return today.strftime('%Y%m%d')

# Load voter registration into SQLite, storing full lines if table doesn't exist
def load_voter_registration_to_sqlite(voter_file):
    try:
        # Extract date from filename
        date_part = extract_date_from_voter_file(voter_file)
        table_name = f"voters_{date_part}"
        conn = sqlite3.connect(DB_FILE)
        
        # Check if table exists
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='{table_name}'
        """)
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            print(f"Table '{table_name}' already exists. Reusing existing data.")
            return conn
        
        print(f"Creating new table '{table_name}' for voter data...")
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
        
        # Store all columns in the database with the date-based table name
        df.to_sql(table_name, conn, if_exists='replace', index=False)
        conn.execute(f'CREATE INDEX idx_name_birthyear ON {table_name} (FullName, Birthyear)')
        print(f"Loaded {len(df)} voter records into table '{table_name}'.")
        return conn
    except (FileNotFoundError, pd.errors.EmptyDataError) as e:
        print(f"Error loading voter file {voter_file}: {e}")
        return None

# Match decedents with voters using the PDF year
def match_decedents_with_voters(decedents, conn, pdf_year):
    matches = []
    cursor = conn.cursor()
    
    # Get the table name from the voter file date
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name LIKE 'voters_%'
        ORDER BY name DESC LIMIT 1
    """)
    result = cursor.fetchone()
    if not result:
        print("Error: No voters table found in database")
        return matches
    
    table_name = result[0]
    
    for name, age in decedents:
        reference_year = pdf_year if pdf_year else CURRENT_YEAR
        possible_birth_years = [reference_year - age - 1, reference_year - age]
        
        query = f"""
            SELECT StateVoterID, FName, MName, LName, NameSuffix, Birthyear, Gender,
                   RegStNum, RegStFrac, RegStName, RegStType, RegUnitType,
                   RegStPreDirection, RegStPostDirection, RegStUnitNum,
                   RegStCity, RegState, RegZipCode, CountyCode,
                   PrecinctCode, PrecinctPart, LegislativeDistrict,
                   CongressionalDistrict, Mail1, Mail2, Mail3, MailCity,
                   MailZip, MailState, MailCountry, Registrationdate,
                   LastVoted, StatusCode
            FROM {table_name}
            WHERE Birthyear IN (?, ?)
        """
        cursor.execute(query, possible_birth_years)
        rows = cursor.fetchall()
        
        for row in rows:
            voter_name = f"{row[1]} {row[2]} {row[3]}".strip().lower()
            if is_name_match(name, voter_name):
                matches.append({
                    'Name': name,
                    'VoterInfo': {
                        'StateVoterID': row[0],
                        'FName': row[1],
                        'MName': row[2],
                        'LName': row[3],
                        'NameSuffix': row[4],
                        'Birthyear': row[5],
                        'Gender': row[6],
                        'RegStNum': row[7],
                        'RegStFrac': row[8],
                        'RegStName': row[9],
                        'RegStType': row[10],
                        'RegUnitType': row[11],
                        'RegStPreDirection': row[12],
                        'RegStPostDirection': row[13],
                        'RegStUnitNum': row[14],
                        'RegStCity': row[15],
                        'RegState': row[16],
                        'RegZipCode': row[17],
                        'CountyCode': row[18],
                        'PrecinctCode': row[19],
                        'PrecinctPart': row[20],
                        'LegislativeDistrict': row[21],
                        'CongressionalDistrict': row[22],
                        'Mail1': row[23],
                        'Mail2': row[24],
                        'Mail3': row[25],
                        'MailCity': row[26],
                        'MailZip': row[27],
                        'MailState': row[28],
                        'MailCountry': row[29],
                        'Registrationdate': row[30],
                        'LastVoted': row[31],
                        'StatusCode': row[32]
                    }
                })
    
    return matches

def format_voter_info(voter_info):
    """Format voter information in a readable way."""
    return {
        'voter_id': voter_info['StateVoterID'],
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
        report.append(f"Voter ID: {voter_info['voter_id']}")
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

# Check if the file is older than two months
def is_older_than_two_months(file_date):
    two_months_ago = datetime.now() - timedelta(days=60)
    return file_date < two_months_ago

def main(pdf_folder, voter_file):
    # Load voter registration data
    conn = load_voter_registration_to_sqlite(voter_file)
    if not conn:
        print("Failed to load voter registration data.")
        return

    pdf_files = [f for f in os.listdir(pdf_folder) if f.endswith('.pdf') and not f.endswith('.org.pdf')]
    if not pdf_files:
        print(f"No PDF files found in {pdf_folder}.")
        return

    print(f"Found {len(pdf_files)} PDF files in {pdf_folder}. Processing...")
    
    total_matches = 0
    reports = []

    # Process each PDF file in the folder
    for filename in pdf_files:
        pdf_path = os.path.join(pdf_folder, filename)
        pdf_date = extract_date_from_filename(filename)
        if not pdf_date:
            print(f"Skipping {filename}: Could not extract date")
            continue
            
        if not is_older_than_two_months(pdf_date):
            print(f"Skipping {filename}: File date {pdf_date.strftime('%m/%d/%Y')} is newer than 2 months")
            continue
            
        print(f"\nProcessing {filename}...")
        names_and_ages = extract_names_and_ages_from_pdf(pdf_path)
        if not names_and_ages:
            print(f"No names and ages found in {filename}")
            continue
            
        matches = match_decedents_with_voters(names_and_ages, conn, pdf_date.year)
        total_matches += len(matches)
        report = generate_report(matches, filename, pdf_date)
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
