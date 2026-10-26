import importlib.util
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

spec=importlib.util.spec_from_file_location('fires',Path(__file__).parents[1]/'tools'/'update_fires.py')
f=importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)

class RegionalFiresTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,25,12,tzinfo=timezone.utc)
        self.geom={'type':'Polygon','coordinates':[[[30,50],[40,50],[40,60],[30,60],[30,50]],[[34,54],[36,54],[36,56],[34,56],[34,54]]]}
        self.region={'id':'r','geometry':self.geom,'coverage':{'min_lon':30,'max_lon':40,'min_lat':50,'max_lat':60}}
        self.data={'regions':[self.region], 'zones':[]}
    def point(self,lat=52,lon=32,satellite='NOAA-20'):
        return {'lat':lat,'lon':lon,'acquired':'2026-10-25T10:00:00Z','satellite':satellite}
    def test_holes_and_outside_excluded(self):
        out=f.enrich([self.point(),self.point(55,35),self.point(61,41)],self.region,[])
        self.assertEqual(len(out),1)
    def test_all_region_fires_kept_even_without_nearby_zones(self):
        out=f.enrich([self.point()],self.region,[])
        self.assertEqual(len(out),1)
        self.assertFalse(out[0]['near_oopt'])
    def test_dedup_preserves_distinct_satellites(self):
        out=f.enrich([self.point(),self.point(),self.point(satellite='NOAA-21')],self.region,[])
        self.assertEqual(len(out),2)
    def test_invalid_csv_is_not_zero_fires(self):
        for text in ['Invalid MAP_KEY','<html>Error</html>','']:
            with self.assertRaises(ValueError):f.parse_points(text,'s',self.now)
    def test_empty_valid_csv(self):
        self.assertEqual(f.parse_points('latitude,longitude,acq_date,acq_time,satellite','s',self.now),[])
    def test_actual_48_hour_window(self):
        text='latitude,longitude,acq_date,acq_time,satellite\n52,32,2026-10-23,1159,N20\n52,32,2026-10-23,1200,N20\n52,32,2026-10-25,1100,N20'
        self.assertEqual(len(f.parse_points(text,'s',self.now)),2)
    def test_failure_preserves_previous_data(self):
        old={'regions':{'r':{'updated':'2026-10-25T09:00:00Z','fires':[self.point()]}}}
        def fail(*args):raise ValueError('network failure')
        result=f.update(self.data,old,'not-a-real-key',fail,self.now)
        self.assertEqual(result['regions']['r']['status'],'error')
        self.assertEqual(result['regions']['r']['updated'],'2026-10-25T09:00:00Z')
        self.assertEqual(len(result['fires']),1)
    def test_failure_is_isolated_to_one_region(self):
        data={'regions':[self.region,dict(self.region,id='other')],'zones':[]}
        def fetcher(key,source,region,now):
            if region['id']=='r':raise ValueError('failure')
            return [self.point()]
        result=f.update(data,{},'test',fetcher,self.now)
        self.assertEqual(result['regions']['r']['status'],'error')
        self.assertEqual(result['regions']['other']['status'],'ok')
    def test_timestamp_advances_when_no_fires(self):
        result=f.update(self.data,{},'test',lambda *a:[],self.now)
        self.assertEqual(result['regions']['r']['updated'],'2026-10-25T12:00:00Z')
    def test_near_oopt(self):
        geom={'type':'Polygon','coordinates':[[[31,51],[33,51],[33,53],[31,53],[31,51]]]}
        z={'id':'zone','name':'Zone','geometry':geom,'precise':False}
        result=f.enrich([self.point()],self.region,[z])[0]
        self.assertTrue(result['near_oopt'])
        self.assertEqual(result['distance_m'],0)

class ReceiptTimeTests(unittest.TestCase):
    setUp = RegionalFiresTests.setUp
    point = RegionalFiresTests.point
    def test_first_receipt_is_preserved_on_refresh(self):
        first=f.update(self.data,{},'test',lambda *a:[self.point()],self.now)
        later=f.update(self.data,first,'test',lambda *a:[self.point()],self.now+timedelta(hours=1))
        self.assertEqual(first['fires'][0]['first_seen'],'2026-10-25T12:00:00Z')
        self.assertEqual(later['fires'][0]['first_seen'],first['fires'][0]['first_seen'])
    def test_legacy_observation_has_unknown_receipt_time(self):
        old={'regions':{'r':{'fires':[self.point()]}}}
        result=f.update(self.data,old,'test',lambda *a:[self.point()],self.now)
        self.assertIsNone(result['fires'][0]['first_seen'])

if __name__=='__main__':unittest.main()
