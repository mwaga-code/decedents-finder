import unittest
import os
from find_decedents import extract_names_and_ages_from_pdf

class TestNameExtraction(unittest.TestCase):
    def setUp(self):
        # Path to test data
        self.test_pdf = os.path.join('testdata', 'Decedents_List_12312024.pdf')
        
        # Known correct data from the PDF
        self.expected_data = [
            ('scott gregory peters', 66),
            ('cary wyatt-brown', 51),
            ('michael joseph creegan', 64),
            ('deshaun nathaniel nickelberry', 47),
            ('addison coonradt', 33),
            ('donald joseph pacheco', 54),
            ('josiah leo tomasi talai', 26),
            ('michael lane sayers', 62),
            ('gary peter lesmeister', 60),
        ]

    def test_pdf_exists(self):
        """Test that the test PDF file exists"""
        self.assertTrue(os.path.exists(self.test_pdf), 
                       f"Test PDF file not found: {self.test_pdf}")

    def test_extract_names_and_ages(self):
        """Test that names and ages are correctly extracted from the PDF"""
        results = extract_names_and_ages_from_pdf(self.test_pdf)
        
        # Check the total number of entries
        self.assertEqual(len(results), len(self.expected_data),
                        f"Expected {len(self.expected_data)} entries, but got {len(results)}")
        
        # Sort both lists to ensure consistent comparison
        expected_sorted = sorted(self.expected_data)
        results_sorted = sorted(results)
        
        # Compare each entry
        for (expected_name, expected_age), (result_name, result_age) in zip(expected_sorted, results_sorted):
            # Test name match
            self.assertEqual(result_name, expected_name,
                           f"Name mismatch: expected '{expected_name}', got '{result_name}'")
            
            # Test age match
            self.assertEqual(result_age, expected_age,
                           f"Age mismatch for {expected_name}: expected {expected_age}, got {result_age}")

    def test_specific_entries(self):
        """Test specific important entries are correctly extracted"""
        results = extract_names_and_ages_from_pdf(self.test_pdf)
        results_dict = {name: age for name, age in results}
        
        # Test Nickelberry entry (spans multiple lines in PDF)
        self.assertIn('deshaun nathaniel nickelberry', results_dict,
                     "Failed to find Deshaun Nathaniel Nickelberry")
        self.assertEqual(results_dict['deshaun nathaniel nickelberry'], 47,
                        "Incorrect age for Deshaun Nathaniel Nickelberry")
        
        # Test entry with hyphenated name
        self.assertIn('cary wyatt-brown', results_dict,
                     "Failed to find Cary Wyatt-Brown")
        self.assertEqual(results_dict['cary wyatt-brown'], 51,
                        "Incorrect age for Cary Wyatt-Brown")
        
        # Test entry with three part name
        self.assertIn('michael joseph creegan', results_dict,
                     "Failed to find Michael Joseph Creegan")
        self.assertEqual(results_dict['michael joseph creegan'], 64,
                        "Incorrect age for Michael Joseph Creegan")

    def test_name_formats(self):
        """Test that various name formats are handled correctly"""
        results = extract_names_and_ages_from_pdf(self.test_pdf)
        names = [name for name, _ in results]
        
        # Test handling of different name patterns
        patterns_found = {
            'two_part_name': any(len(name.split()) == 2 for name in names),
            'three_part_name': any(len(name.split()) == 3 for name in names),
            'four_part_name': any(len(name.split()) == 4 for name in names),
            'hyphenated_name': any('-' in name for name in names)
        }
        
        # Verify each pattern is found
        self.assertTrue(patterns_found['two_part_name'], "No two-part names found")
        self.assertTrue(patterns_found['three_part_name'], "No three-part names found")
        self.assertTrue(patterns_found['hyphenated_name'], "No hyphenated names found")

    def test_age_range(self):
        """Test that extracted ages are within reasonable range"""
        results = extract_names_and_ages_from_pdf(self.test_pdf)
        ages = [age for _, age in results]
        
        # Test age constraints
        self.assertTrue(all(0 < age < 120 for age in ages),
                       "Found ages outside reasonable range (1-120)")
        
        # Verify specific age statistics
        self.assertTrue(min(ages) > 20, "Found unexpectedly young age")
        self.assertTrue(max(ages) < 70, "Found unexpectedly old age")

if __name__ == '__main__':
    unittest.main() 