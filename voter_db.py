import os
import re
import sqlite3
import pandas as pd
from datetime import datetime

# Constants
DB_FILE = 'voters.db'
CURRENT_YEAR = datetime.now().year

class VoterDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = None
        
    def connect(self):
        """Connect to the SQLite database."""
        self.conn = sqlite3.connect(self.db_file)
        return self.conn
        
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def get_latest_voter_table(self):
        """Get the name of the most recent voter table."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name LIKE 'voters_%'
            ORDER BY name DESC LIMIT 1
        """)
        result = cursor.fetchone()
        return result[0] if result else None

    def load_voter_registration(self, voter_file):
        """Load voter registration data into SQLite database."""
        try:
            # Extract date from filename
            date_match = re.search(r'^(\d{8})_', os.path.basename(voter_file))
            if not date_match:
                raise ValueError("Voter file name must start with date (YYYYMMDD)")
                
            date_part = date_match.group(1)
            table_name = f"voters_{date_part}"
            
            # Check if table exists
            cursor = self.conn.cursor()
            cursor.execute(f"""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='{table_name}'
            """)
            if cursor.fetchone():
                print(f"Table '{table_name}' already exists. Reusing existing data.")
                return table_name
            
            print(f"Creating new table '{table_name}' for voter data...")
            df = pd.read_csv(voter_file, delimiter='|', header=0, dtype=str, names=[
                'StateVoterID', 'FName', 'MName', 'LName', 'NameSuffix', 'Birthyear', 'Gender',
                'RegStNum', 'RegStFrac', 'RegStName', 'RegStType', 'RegUnitType', 'RegStPreDirection',
                'RegStPostDirection', 'RegStUnitNum', 'RegStCity', 'RegState', 'RegZipCode', 'CountyCode',
                'PrecinctCode', 'PrecinctPart', 'LegislativeDistrict', 'CongressionalDistrict',
                'Mail1', 'Mail2', 'Mail3', 'MailCity', 'MailZip', 'MailState', 'MailCountry',
                'Registrationdate', 'LastVoted', 'StatusCode'
            ], encoding='windows-1252')
            
            # Convert birthyear to numeric and calculate age
            df['Birthyear'] = pd.to_numeric(df['Birthyear'], errors='coerce')
            df = df.dropna(subset=['Birthyear'])
            df['Birthyear'] = df['Birthyear'].astype(int)
            df['Age'] = CURRENT_YEAR - df['Birthyear']
            
            # Create full name column
            df['FullName'] = (
                df['FName'].str.lower().fillna('') + ' ' +
                df['MName'].str.lower().fillna('') + ' ' +
                df['LName'].str.lower().fillna('')
            ).str.replace(r'\s+', ' ', regex=True).str.strip()
            
            # Store all columns in the database
            df.to_sql(table_name, self.conn, if_exists='replace', index=False)
            
            # Create indexes for common queries
            self.conn.execute(f'CREATE INDEX idx_{table_name}_age ON {table_name} (Age)')
            self.conn.execute(f'CREATE INDEX idx_{table_name}_name ON {table_name} (FullName)')
            self.conn.execute(f'CREATE INDEX idx_{table_name}_birthyear ON {table_name} (Birthyear)')
            
            print(f"Loaded {len(df)} voter records into table '{table_name}'.")
            return table_name
            
        except Exception as e:
            print(f"Error loading voter file {voter_file}: {e}")
            return None

    def initialize_decedents_table(self, reset=False):
        """Create or reset the table to track processed decedents."""
        cursor = self.conn.cursor()
        
        if reset:
            cursor.execute("DROP TABLE IF EXISTS processed_decedents")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_decedents (
                name TEXT,
                age INTEGER,
                first_seen_date DATE,
                last_seen_date DATE,
                case_number TEXT,
                run_id TEXT,  -- Track which run processed this decedent
                PRIMARY KEY (case_number, run_id)  -- Case number uniquely identifies a person
            )
        """)
        self.conn.commit()

    def format_voter_info(self, row):
        """Format voter information in a readable way."""
        return {
            'voter_id': row['StateVoterID'],
            'name': f"{row['FName']} {row['MName']} {row['LName']}".strip(),
            'birth_year': row['Birthyear'],
            'age': row['Age'],
            'address': f"{row['RegStNum']} {row['RegStFrac']} {row['RegStName']} {row['RegStType']} {row['RegUnitType']} {row['RegStPreDirection']} {row['RegStPostDirection']} {row['RegStUnitNum']}".strip(),
            'city': row['RegStCity'],
            'zip': row['RegZipCode'],
            'registration_date': row['Registrationdate'],
            'last_voted': row['LastVoted'],
            'status': row['StatusCode'],
            'precinct': f"{row['PrecinctCode']}{row['PrecinctPart']}",
            'legislative_district': row['LegislativeDistrict'],
            'congressional_district': row['CongressionalDistrict'],
            'mailing_address': f"{row['Mail1']} {row['Mail2']} {row['Mail3']}".strip(),
            'mailing_city': row['MailCity'],
            'mailing_zip': row['MailZip'],
            'mailing_state': row['MailState']
        } 