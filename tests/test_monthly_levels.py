import os
import tempfile
import unittest
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
import auth_backend as a

class Levels(unittest.TestCase):
    def test_boundaries(self):
        for points, level in [(500,'L1'),(501,'L2'),(750,'L2'),(751,'L3'),(1000,'L3'),(1001,'L4'),(1250,'L4'),(1251,'L5'),(1500,'L5'),(1501,'L6')]:
            self.assertEqual(a.level_info(points)['level'],level)
    def test_first_102(self):
        awards=a.bottle_awards(0,102)
        self.assertEqual(awards[99][4],500)
        self.assertEqual(awards[100][0],5)
        self.assertEqual(awards[100][4],505)
        self.assertEqual(awards[101][0],6)
    def test_batch_crosses(self):
        self.assertEqual([x[0] for x in a.bottle_awards(499,3)],[5,6,6])
    def test_timezone_rollover(self):
        self.assertEqual(a.month_key(datetime(2026,1,31,15,59,tzinfo=timezone.utc)),'2026-01')
        self.assertEqual(a.month_key(datetime(2026,1,31,16,0,tzinfo=timezone.utc)),'2026-02')

    def test_simultaneous_deposits(self):
        import time
        class Handler:
            headers={'X-Device-Key':'k'*32}
            def _send_json(self,status,data,**kwargs): self.status=status; self.data=data
        old_db, old_url, old_keys, old_secret = a.DB, a.DATABASE_URL, a.DEVICE_KEYS, a.SECRET
        with tempfile.TemporaryDirectory() as folder:
            try:
                from pathlib import Path
                a.DB=Path(folder)/'test.sqlite'; a.DATABASE_URL='';a.DEVICE_KEYS={'machine':'k'*32};a.SECRET=b'x'*32
                from unittest.mock import patch
                with patch.object(a, "hash_password", return_value="test"):
                    a.init()
                with a.connect() as db:
                    db.execute("INSERT INTO users(id,email,password_hash,created_at,monthly_points,monthly_points_month) VALUES(?,?,?,?,?,?)",('u','u@example.com','x',a.now(),500,a.month_key()))
                    db.execute('INSERT INTO sessions(id,user_id,expires) VALUES(?,?,?)',('s','u',int(time.time())+300))
                    db.execute('INSERT INTO machine_pairings(machine_id,user_id,expires) VALUES(?,?,?)',('machine','u',int(time.time())+300))
                def deposit(i):
                    h=Handler();a.handle(h,'POST','/api/hardware/deposit',{'machine_id':'machine','event_id':f'event_id_{i:010d}'});return h
                with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(deposit,range(2)))
                self.assertEqual([r.status for r in results],[200,200])
                self.assertEqual(sorted(r.data['earned_points'] for r in results),[5,6])
                with a.connect() as db:
                    self.assertEqual(db.execute('SELECT monthly_points FROM users WHERE id=?',('u',)).fetchone()['monthly_points'],511)
                    self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM bottle_ledger').fetchone()['n'],2)
            finally: a.DB,a.DATABASE_URL,a.DEVICE_KEYS,a.SECRET=old_db,old_url,old_keys,old_secret

if __name__=='__main__': unittest.main()
