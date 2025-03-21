import sys
import os
import argparse
from voter_db import VoterDB

def generate_report(ancient_voters):
    """Generate a formatted report for the ancient voters found."""
    if not ancient_voters:
        return "\nNo voters aged 120 or older found."
    
    report = []
    report.append(f"\n{'='*80}")
    report.append("ANCIENT VOTERS REPORT")
    report.append(f"Total Ancient Voters Found: {len(ancient_voters)}")
    report.append(f"{'='*80}\n")
    
    for i, voter in enumerate(ancient_voters, 1):
        report.append(f"Ancient Voter #{i}")
        report.append(f"{'-'*40}")
        report.append(f"Voter ID: {voter['StateVoterID']}")
        report.append(f"Name: {voter['FName']} {voter['MName']} {voter['LName']}".strip())
        report.append(f"Age: {voter['Age']}")
        report.append(f"Birth Year: {voter['Birthyear']}")
        report.append(f"Registration Address: {voter['RegStNum']} {voter['RegStFrac']} {voter['RegStName']} {voter['RegStType']} {voter['RegUnitType']} {voter['RegStPreDirection']} {voter['RegStPostDirection']} {voter['RegStUnitNum']}".strip())
        report.append(f"City: {voter['RegStCity']}")
        report.append(f"ZIP: {voter['RegZipCode']}")
        report.append(f"Precinct: {voter['PrecinctCode']}{voter['PrecinctPart']}")
        report.append(f"Legislative District: {voter['LegislativeDistrict']}")
        report.append(f"Congressional District: {voter['CongressionalDistrict']}")
        report.append(f"Registration Date: {voter['Registrationdate']}")
        report.append(f"Last Voted: {voter['LastVoted']}")
        report.append(f"Status: {voter['StatusCode']}")
        
        # Add mailing address if any part exists
        mailing_parts = [voter['Mail1'], voter['Mail2'], voter['Mail3']]
        if any(mailing_parts):
            report.append("\nMailing Address:")
            report.append(f"  {' '.join(part for part in mailing_parts if part)}")
            report.append(f"  {voter['MailCity']}, {voter['MailState']} {voter['MailZip']}")
        
        report.append(f"{'-'*40}\n")
    
    return '\n'.join(report)

def main(voter_file):
    # Initialize database connection
    with VoterDB() as db:
        # Load voter registration data
        table_name = db.load_voter_registration(voter_file)
        if not table_name:
            print("Failed to load voter registration data.")
            return
        
        # Find voters aged 120 or older
        cursor = db.conn.cursor()
        query = f"""
            SELECT *
            FROM {table_name}
            WHERE Age >= 120
            ORDER BY Age DESC
        """
        cursor.execute(query)
        columns = [description[0] for description in cursor.description]
        ancient_voters = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        # Generate and print report
        report = generate_report(ancient_voters)
        print(report)
        
        # Print summary statistics
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        print(f"Total ancient voters found: {len(ancient_voters)}")
        if ancient_voters:
            oldest_age = max(voter['Age'] for voter in ancient_voters)
            print(f"Oldest voter age: {oldest_age}")
            print(f"Average age of ancient voters: {sum(voter['Age'] for voter in ancient_voters)/len(ancient_voters):.1f}")
        print(f"{'='*80}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Find voters aged 120 or older in voter registration data.')
    parser.add_argument('voter_file', help='Voter registration file')
    
    args = parser.parse_args()
    main(args.voter_file) 