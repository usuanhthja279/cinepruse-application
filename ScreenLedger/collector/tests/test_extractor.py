import csv
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from district_extractor import extract_snapshot, make_url, parse_movie_url, slugify_city, save_results
from city_catalog import extract_catalog, extract_catalog_from_json, extract_city_links
import json
import tempfile

BASE = Path(__file__).resolve().parents[1]

class ExtractorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = extract_snapshot((BASE / 'fixtures/ramayana_kolkata_2026-11-06.html').read_text(encoding='utf-8'),
                                        source_city='kolkata', expected_movie_id='176276')

    def test_counts(self):
        m = self.snapshot['metadata']
        self.assertEqual(m['movie_id'], '176276')
        self.assertEqual(m['cinemas_with_shows'], 29)
        self.assertEqual(m['shows'], 117)
        self.assertEqual(m['seat_categories'], 410)
        self.assertEqual(m['total_seats_across_shows'], 27663)
        self.assertEqual(m['available_seats_across_shows'], 20461)
        self.assertEqual(m['unavailable_pct'], 26.03)
        self.assertEqual(m['assumed_booked_seats_across_shows'], 7202)
        self.assertEqual(m['estimated_gross_inr'], 3948610)
        self.assertEqual(m['priced_show_count'], 117)
        self.assertEqual(m['unpriced_show_count'], 0)

    def test_acropolis_first_session(self):
        shows = [x for x in self.snapshot['shows'] if x['cinema_id'] == 148 and x['show_time_ist'] == '21:45']
        self.assertTrue(shows)
        row = shows[0]
        self.assertEqual(row['total_seats'], 252)
        self.assertEqual(row['available_seats'], 86)
        self.assertEqual(row['screen_format'], '3D')
        areas = [x for x in self.snapshot['areas'] if x['session_key'] == row['session_key']]
        self.assertEqual([x['category_label'] for x in areas], ['NORMAL','EXECUTIVE','PREMIUM'])
        self.assertEqual([x['available_seats'] for x in areas], [21,51,14])
        self.assertEqual(row['assumed_booked_seats'], 166)
        self.assertEqual(row['estimated_gross_inr'], 92220)
        self.assertEqual([x['estimated_gross_inr'] for x in areas], [0,19980,72240])

    def test_url(self):
        url = make_url('Ramayana', '176276', 'Delhi', '2026-11-07', 'rtb7dmwvuo')
        self.assertEqual(url, 'https://www.district.in/movies/ramayana-movie-tickets-in-delhi-ncr-MV176276?frmtid=rtb7dmwvuo&fromdate=2026-11-07')
        self.assertEqual(parse_movie_url(url)['city'], 'delhi-ncr')
        self.assertEqual(slugify_city('Visakhapatnam'), 'vizag')

    def test_catalog_example(self):
        rows = extract_catalog(BASE / 'fixtures/sample_authorized_city_export.json')
        self.assertEqual({x['slug'] for x in rows}, {'mumbai', 'kolkata', 'delhi-ncr'})
        self.assertTrue(all(x['confidence'] == 'source_slug' for x in rows))

    def test_city_links_are_partial_and_movie_html_is_not_a_city_list(self):
        rows = extract_city_links('<a href="/movies/mumbai-movie-tickets">Mumbai</a>'
                                  '<a href="/movies/kolkata-movie-tickets">Kolkata</a>',
                                  '2026-11-06T00:00:00Z')
        self.assertEqual({x['slug'] for x in rows}, {'mumbai', 'kolkata'})
        movie_html = (BASE / 'fixtures/ramayana_kolkata_2026-11-06.html').read_text(encoding='utf-8')
        self.assertEqual(extract_city_links(movie_html, '2026-11-06T00:00:00Z'), [])

    def test_duplicate_city_snapshot_is_not_double_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            save_results(Path(folder), [self.snapshot, self.snapshot])
            report = json.loads((Path(folder) / 'unique_collection_summary.json').read_text(encoding='utf-8'))
            self.assertEqual(report['raw_show_rows'], 234)
            self.assertEqual(report['unique_shows'], 117)
            self.assertEqual(report['duplicates_removed'], 117)
            self.assertEqual(report['estimated_gross_inr'], 3948610)

    def test_500_candidate_uniq(self):
        with (BASE / 'cities_500_candidates.csv').open(encoding='utf-8-sig') as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows), 500)
        self.assertEqual(len({r['slug'] for r in rows}),500)
        self.assertEqual(rows[0]['slug'],'mumbai')

if __name__ == '__main__': unittest.main()
