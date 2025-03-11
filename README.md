# decedents-finder
Scripts for finding possible decedents in Washington state voter registration.

# Prerequisites

Visit: https://www.sos.wa.gov/elections/data-research/election-data-and-maps/reports-data-and-statistics
and request Voter registration data, wait for the email, then download the data.

The voter registration data file has a filename like follows:
20250203_VRDB_Extract.txt

# Usage

```sh
# Clone the repository
$ git clone https://github.com/mwaga-code/decedents-finder.git
$ cd decedents-finder

# Set up Python environment
$ python -m venv .venv
$ source .venv/bin/activate  # On Windows: .venv\Scripts\activate
$ pip install -r requirements.txt

# Fetch decedents lists from King county web site
$ python fetch-decedents-lists.py \
  https://kingcounty.gov/en/dept/dph/health-safety/medical-examiner/decedents

# Copy the voter registration data
$ cp ../somewhere/20250203_VRDB_Extract.txt .

# Run the main script
$ python find_decedents.py temp 20250203_VRDB_Extract.txt > output.txt 2>&1
```

# Running Tests

```sh
# Run all tests
$ python -m unittest discover -v

# Run specific test file
$ python -m unittest test_find_decedents.py -v
```

The test suite verifies:
1. Name extraction from PDFs (including complex cases like multi-line names)
2. Age extraction and validation
3. Various name format handling (hyphenated names, multi-part names)

# TODO
- Add more decedents list sources from other counties
- Automate whole process
- Better reporting
- Add more test coverage for edge cases
