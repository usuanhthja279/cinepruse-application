import csv,json,sqlite3,sys,tempfile,unittest
from datetime import date,datetime,timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from venue_locations import prepare_geometry,locate,address_states,canonical,load_locations
from smart_collector import SCHEMA,record_snapshot

class VenueLocationTests(unittest.TestCase):
    def setUp(self):
        self.geo={"features":[{"properties":{"name":"Example State"},"geometry":{"type":"Polygon","coordinates":[[[70,10],[72,10],[72,12],[70,12],[70,10]],[[70.8,10.8],[71.2,10.8],[71.2,11.2],[70.8,11.2],[70.8,10.8]]]}}]}
        self.geometry=prepare_geometry(self.geo)
    def test_inside_outside_holes_and_boundaries(self):
        self.assertEqual(locate(10.5,70.5,self.geometry),("Example State","inside_boundary"))
        self.assertEqual(locate(11,71,self.geometry)[0],None)
        self.assertEqual(locate(10.001,70.5,self.geometry)[1],"inside_boundary")
        neighbour={"features":self.geo["features"]+[{"properties":{"name":"Other State"},"geometry":{"type":"Polygon","coordinates":[[[72,10],[74,10],[74,12],[72,12],[72,10]]]}}]}
        self.assertEqual(locate(10.5,71.999,prepare_geometry(neighbour))[1],"near_boundary")
        self.assertEqual(locate(None,None,self.geometry)[1],"missing_coordinates")
    def test_state_address_requires_word_boundaries(self):
        self.assertEqual(address_states("Town, Example State 123456",["Example State"]),{canonical("Example State")})
        self.assertFalse(address_states("NotExample Statehouse",["Example State"]))
        self.assertEqual(address_states("Delhi Mathura Road, Faridabad, Haryana 121003, India",["Delhi","Haryana"]),{"haryana"})
        self.assertEqual(address_states("Tuticorin, TamilNadu, 628001",["Tamil Nadu"]),{"tamilnadu"})
        self.assertEqual(address_states("Balaghat, Madhya Pradesh –481001",["Madhya Pradesh"]),{"madhyapradesh"})
    def test_venue_address_requires_exact_id_and_conflicts_remain_unassigned(self):
        conn=sqlite3.connect(":memory:");conn.row_factory=sqlite3.Row
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);geo=p/'map.json';geo.write_text(json.dumps(self.geo));saved=p/'locations.csv';checked=p/'checks.csv'
            fields=['cinema_id','state_or_ut','status','source_url','address','secondary_source_url','notes']
            with checked.open('w',newline='',encoding='utf8') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
                for cid,url in [('42','https://www.district.in/movies/a-CD42'),('43','https://www.district.in/movies/a-CD430')]:
                    w.writerow(dict(cinema_id=cid,state_or_ut='Example State',status='district_venue_address',source_url=url,address='Town, Example State 123456'))
            result=load_locations(conn,path=saved,map_path=geo,address_path=checked)
            self.assertEqual(result['42']['state_or_ut'],'Example State');self.assertNotIn('43',result)
            with saved.open('w',newline='',encoding='utf8') as f:
                w=csv.DictWriter(f,fieldnames=['cinema_id','status','state_or_ut']);w.writeheader();w.writerow(dict(cinema_id='42',status='conflicting_or_boundary_review',state_or_ut=''))
            self.assertEqual(load_locations(conn,path=saved,map_path=geo,address_path=checked)['42']['status'],'needs_review')
        conn.close()
    def test_capture_persists_only_parsed_venue_information(self):
        conn=sqlite3.connect(":memory:");conn.row_factory=sqlite3.Row;conn.executescript(SCHEMA)
        at=datetime(2025,1,1,6,tzinfo=timezone.utc)
        show={"session_key":"s","show_datetime_ist":"2025-01-01T14:00:00+05:30","cinema_id":"42","cinema_name":"Cinema","cinema_address":"Town, Example State","latitude":10.5,"longitude":70.5,"total_seats":10,"available_seats":8,"unavailable_seats":2,"pricing_complete":True}
        snap={"metadata":{"movie_id":"m","source_city":"town","actual_city":"town","source_url":"https://www.district.in/movies/example"},"shows":[show]}
        record_snapshot(conn,snap,at,"hourly",date(2025,1,1))
        row=dict(conn.execute("SELECT * FROM cinema_location_observations").fetchone())
        self.assertEqual((row["cinema_id"],row["latitude"],row["longitude"]),("42",10.5,70.5))
        self.assertEqual(row["address"],"Town, Example State")
        with patch.object(Path,"read_text",return_value=json.dumps(self.geo)):
            mapped=load_locations(conn,path=Path("nonexistent_location_file.csv"),map_path=Path("unused.geojson"))
        self.assertEqual(mapped["42"]["state_or_ut"],"Example State")
        self.assertEqual(mapped["42"]["status"],"address_and_boundary_agree")
        conn.close()
    def test_conflicting_coordinates_for_same_cinema_are_held_for_review(self):
        conn=sqlite3.connect(":memory:");conn.row_factory=sqlite3.Row;conn.executescript(SCHEMA)
        geo={"features":[{"properties":{"name":"First State"},"geometry":{"type":"Polygon","coordinates":[[[70,10],[72,10],[72,12],[70,12],[70,10]]]}},{"properties":{"name":"Second State"},"geometry":{"type":"Polygon","coordinates":[[[74,10],[76,10],[76,12],[74,12],[74,10]]]}}]}
        base={"show_datetime_ist":"2025-01-01T14:00:00+05:30","cinema_id":"42","cinema_name":"Cinema","total_seats":10,"available_seats":8,"unavailable_seats":2,"pricing_complete":True}
        shows=[dict(base,session_key="one",latitude=11,longitude=71,cinema_address="Town, First State"),dict(base,session_key="two",latitude=11,longitude=75,cinema_address="Town, Second State")]
        snap={"metadata":{"movie_id":"m","source_city":"town","actual_city":"town"},"shows":shows}
        record_snapshot(conn,snap,datetime(2025,1,1,6,tzinfo=timezone.utc),"hourly",date(2025,1,1))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cinema_location_observations").fetchone()[0],2)
        with patch.object(Path,"read_text",return_value=json.dumps(geo)):
            result=load_locations(conn,path=Path("nonexistent_location_file.csv"),map_path=Path("unused.geojson"))
        self.assertEqual(result["42"]["status"],"needs_review")
        self.assertEqual(result["42"]["state_or_ut"],"")
        conn.close()

if __name__=="__main__":unittest.main()
