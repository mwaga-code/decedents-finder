# decedents-finder
Scripts for finding possible decedents in Washington state voter registration.

# Prerequisites

Visit: https://www.sos.wa.gov/elections/data-research/election-data-and-maps/reports-data-and-statistics
and request Voter registration data, wait for the email, then download the data.

The voter registration data file has a filename like follows:
20250203_VRDB_Extract.txt

# Usage

```sh

$ git clone https://github.com/mwaga-code/decedents-finder.git
$ cd decedents-finder
$ pip -r requirements.txt
$ python fetch-decedents-lists.py \
  https://kingcounty.gov/en/dept/dph/health-safety/medical-examiner/decedents
...
...

# Sometimes manual tweaks needed
$ cd temp
$ mv Decedents_List_11072024%28Revised%29.pdf Decedents_List_11072024.pdf
$ mv Decedents_List_10182024_-_For_Correction.pdf Decedents_List_10182024.pdf
$ cd ..

# Copy the voter registration data
$ cp ../somewhere/20250203_VRDB_Extract.txt .

# Run the main script

```