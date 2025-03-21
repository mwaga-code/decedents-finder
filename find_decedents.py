import sys
import os
import re
from datetime import datetime, timedelta
import pdfplumber
import argparse
from fuzzywuzzy import fuzz
from voter_db import VoterDB

# Constants
TEMP_DIR = 'temp'  # Directory for PDFs

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
                    
                    # Handle names split across lines
                    # First, replace newline markers with spaces
                    name = re.sub(r'\s*<NEWLINE>\s*|\s*<br>\s*', ' ', name_text)
                    
                    # Look for additional name parts between the age and "Date of Incident"
                    if 'Date of Incident' in entry_text:
                        after_age = entry_text[name_end_idx:entry_text.index('Date of Incident')].strip()
                        # Split into lines and look for name parts
                        lines = after_age.split('<NEWLINE>')
                        for line in lines:
                            line = line.strip()
                            # Skip lines that look like metadata
                            if any(x in line.lower() for x in ['years', 'male', 'female', 'seattle']):
                                continue
                            # Skip empty lines or lines starting with numbers
                            if not line or line[0].isdigit():
                                continue
                            name = f"{name} {line}"
                    
                    # Remove any remaining numbers from the name
                    name = re.sub(r'\d+', '', name)
                    # Normalize whitespace
                    name = ' '.join(name.split())
                    
                    # Skip if name is empty after cleaning
                    if not name:
                        continue
                    
                    names_and_ages.append({
                        'name': name.lower(),
                        'age': age,
                        'case_number': case_num
                    })
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

def match_decedents_with_voters(decedents, db, pdf_year):
    """Match decedents with voters using the PDF year."""
    matches = []
    cursor = db.conn.cursor()
    
    # Get the table name from the voter file date
    table_name = db.get_latest_voter_table()
    if not table_name:
        print("Error: No voters table found in database")
        return matches
    
    for name, age in decedents:
        reference_year = pdf_year if pdf_year else datetime.now().year
        possible_birth_years = [reference_year - age - 1, reference_year - age]
        
        query = f"""
            SELECT *
            FROM {table_name}
            WHERE Birthyear IN (?, ?)
        """
        cursor.execute(query, possible_birth_years)
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        
        for row in rows:
            row_dict = dict(zip(columns, row))
            voter_name = f"{row_dict['FName']} {row_dict['MName']} {row_dict['LName']}".strip().lower()
            if is_name_match(name, voter_name):
                matches.append({
                    'Name': name,
                    'VoterInfo': row_dict
                })
    
    return matches

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
        voter_info = match['VoterInfo']
        report.append(f"Match #{i}")
        report.append(f"{'-'*40}")
        report.append(f"Voter ID: {voter_info['StateVoterID']}")
        report.append(f"Decedent Name: {match['Name']}")
        report.append(f"Voter Name: {voter_info['FName']} {voter_info['MName']} {voter_info['LName']}".strip())
        report.append(f"Registration Address: {voter_info['RegStNum']} {voter_info['RegStFrac']} {voter_info['RegStName']} {voter_info['RegStType']} {voter_info['RegUnitType']} {voter_info['RegStPreDirection']} {voter_info['RegStPostDirection']} {voter_info['RegStUnitNum']}".strip())
        report.append(f"City: {voter_info['RegStCity']}")
        report.append(f"ZIP: {voter_info['RegZipCode']}")
        report.append(f"Precinct: {voter_info['PrecinctCode']}{voter_info['PrecinctPart']}")
        report.append(f"Legislative District: {voter_info['LegislativeDistrict']}")
        report.append(f"Congressional District: {voter_info['CongressionalDistrict']}")
        report.append(f"Birth Year: {voter_info['Birthyear']}")
        report.append(f"Registration Date: {voter_info['Registrationdate']}")
        report.append(f"Last Voted: {voter_info['LastVoted']}")
        report.append(f"Status: {voter_info['StatusCode']}")
        
        # Add mailing address if any part exists
        mailing_parts = [voter_info['Mail1'], voter_info['Mail2'], voter_info['Mail3']]
        if any(mailing_parts):
            report.append("\nMailing Address:")
            report.append(f"  {' '.join(part for part in mailing_parts if part)}")
            report.append(f"  {voter_info['MailCity']}, {voter_info['MailState']} {voter_info['MailZip']}")
        report.append(f"{'-'*40}\n")
    
    return '\n'.join(report)

# Check if the file is older than two months
def is_older_than_two_months(file_date):
    two_months_ago = datetime.now() - timedelta(days=60)
    return file_date < two_months_ago

def process_decedent(db, decedent, pdf_date, run_id):
    """Process a decedent, handling duplicates based on case number."""
    cursor = db.conn.cursor()
    
    # First check if we've seen this case number in any previous run
    cursor.execute("""
        SELECT first_seen_date, run_id
        FROM processed_decedents
        WHERE case_number = ?
        ORDER BY first_seen_date DESC LIMIT 1
    """, (decedent['case_number'],))
    
    previous_result = cursor.fetchone()
    
    # Then check if we've seen this case in the current run
    cursor.execute("""
        SELECT first_seen_date
        FROM processed_decedents
        WHERE case_number = ? AND run_id = ?
    """, (decedent['case_number'], run_id))
    
    current_run_result = cursor.fetchone()
    
    if current_run_result:
        # We've seen this case in this run, skip it
        return False
    else:
        # First time seeing this case in this run
        # If we've seen it in a previous run, skip it
        if previous_result:
            return False
        
        # New case, add to tracking table
        cursor.execute("""
            INSERT INTO processed_decedents
            (name, age, first_seen_date, last_seen_date, case_number, run_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (decedent['name'], decedent['age'], pdf_date.strftime('%Y-%m-%d'), pdf_date.strftime('%Y-%m-%d'), 
              decedent['case_number'], run_id))
        db.conn.commit()
        return True  # Process new cases

def main(pdf_folder, voter_file, reset=False):
    # Generate a unique run ID using timestamp
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Initialize database connection
    with VoterDB() as db:
        # Load voter registration data
        table_name = db.load_voter_registration(voter_file)
        if not table_name:
            print("Failed to load voter registration data.")
            return

        # Initialize decedents tracking table
        db.initialize_decedents_table(reset)

        pdf_files = [f for f in os.listdir(pdf_folder) if f.endswith('.pdf') and not f.endswith('.org.pdf')]
        if not pdf_files:
            print(f"No PDF files found in {pdf_folder}.")
            return

        print(f"Found {len(pdf_files)} PDF files in {pdf_folder}. Processing...")
        print(f"Run ID: {run_id}")
        if reset:
            print("Reset mode: Processing all files from scratch")
        
        total_matches = 0
        reports = []

        # Sort PDF files by date to process older files first
        pdf_files.sort(key=lambda x: extract_date_from_filename(x) or datetime.max)

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
            decedents = extract_names_and_ages_from_pdf(pdf_path)
            if not decedents:
                print(f"No names and ages found in {filename}")
                continue
            
            # Filter decedents to process based on deduplication rules
            decedents_to_process = []
            for decedent in decedents:
                if process_decedent(db, decedent, pdf_date, run_id):
                    decedents_to_process.append((decedent['name'], decedent['age']))
            
            if not decedents_to_process:
                print(f"No new decedents to process in {filename}")
                continue
                
            matches = match_decedents_with_voters(decedents_to_process, db, pdf_date.year)
            total_matches += len(matches)
            report = generate_report(matches, filename, pdf_date)
            reports.append(report)
            print(report)

        # Print summary
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        print(f"Run ID: {run_id}")
        print(f"Total PDF files processed: {len(pdf_files)}")
        print(f"Total matches found across all files: {total_matches}")
        if len(pdf_files) > 0:
            print(f"Average matches per file: {total_matches/len(pdf_files):.1f}")
        print(f"{'='*80}\n")
        
        # Print deduplication statistics for current run
        cursor = db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM processed_decedents WHERE run_id = ?", (run_id,))
        total_decedents = cursor.fetchone()[0]
        print(f"Deduplication Statistics (This Run):")
        print(f"Total unique decedents: {total_decedents}")
        print(f"{'='*80}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process decedents lists and match with voter registration.')
    parser.add_argument('pdf_folder', help='Folder containing PDF files')
    parser.add_argument('voter_file', help='Voter registration file')
    parser.add_argument('--reset', action='store_true', 
                      help='Reset processed_decedents table and process all files from scratch')
    
    args = parser.parse_args()
    main(args.pdf_folder, args.voter_file, args.reset)
