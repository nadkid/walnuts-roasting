"""Historical shipments clear reminders without inventing or deducting stock."""
import json,sqlite3,unittest
from types import SimpleNamespace
import test_core
from server import shipments
from server.app import state
from server.db import one,rows
from server.domain import stock_id
from server.imports import fulfillment_pick


class HistoricalShipments(unittest.TestCase):
    def setUp(self):
        self.c=test_core.Core();self.c.setUp();self.db=self.c.db
        self.fulfillment={'id':'old-shipment','createdAt':'2026-11-03T03:00:00Z','status':'SUCCESS','lines':[{'line_id':'l','quantity':2}]}
        self.c.order(0,2,fulfillments=[self.fulfillment])
    def tearDown(self):self.c.tearDown()
    def op(self,action='pre_dashboard',id='old-shipment',key=None,reason='Shipped using untracked stock before launch'):
        return self.c.runop(shipments.reconcile,{'fulfillment_id':id,'action':action,'reason':reason},'Tester',key or action+id)
    def snapshot(self):return state(self.db,{'id':'test','name':'Test','role':'admin'},SimpleNamespace(configured=lambda:{}))
    def inventory(self):
        return {t:rows(self.db,'SELECT * FROM '+t) for t in ('stocks','batches','entries','movements','reservations','green_events','fulfillment_picks')}
    def test_acknowledgement_with_no_batches_clears_only_its_reminder_and_survives_sync(self):
        self.assertEqual(len(self.snapshot()['fulfillments']),1);before=self.inventory()
        result=self.op();self.assertEqual(self.inventory(),before)
        s=self.snapshot();self.assertEqual(s['fulfillments'],[])
        self.assertEqual(rows(self.db,"SELECT * FROM issues WHERE source='shopify' AND kind='external_fulfillment' AND resolved=0"),[])
        record=s['orders'][0]['shipment_reconciliations'][0]
        self.assertEqual(record['fulfillment_id'],'old-shipment');self.assertEqual(record['actor'],'Tester')
        self.assertNotIn('payload_hash',record);self.assertNotIn('request_id',record)
        self.assertEqual(one(self.db,"SELECT * FROM audit WHERE action='fulfillment_pre_dashboard'")['actor'],'Tester')
        self.c.order(0,2,fulfillments=[self.fulfillment])
        self.assertEqual(self.snapshot()['fulfillments'],[]);self.assertEqual(self.inventory(),before)
        self.assertEqual(shipments.active(self.db)[0]['id'],result['reconciliation_id'])
    def test_partial_order_reservations_and_other_shipments_are_untouched(self):
        self.fulfillment['lines'][0]['quantity']=1
        self.c.order(1,2,fulfillments=[self.fulfillment])
        b=self.c.batch();s=stock_id(self.db,b,'roastery');self.c.reserve(s,100)
        self.db.execute('INSERT INTO fulfillment_events VALUES (?,?,?,?,0)',('second-shipment','o','2026-11-10T03:00:00Z',json.dumps({'lines':[{'line_id':'l','quantity':1}]})))
        before=self.inventory();line=one(self.db,'SELECT * FROM lines');self.op()
        self.assertEqual(self.inventory(),before);self.assertEqual(one(self.db,'SELECT * FROM lines'),line)
        self.assertEqual([f['id'] for f in self.snapshot()['fulfillments']],['second-shipment'])
    def test_request_replay_is_idempotent_and_request_reuse_is_rejected(self):
        first=self.op();audit=len(rows(self.db,'SELECT * FROM audit'))
        repeat=self.op();self.assertTrue(repeat['duplicate']);self.assertEqual(repeat['reconciliation_id'],first['reconciliation_id'])
        self.assertEqual(len(rows(self.db,'SELECT * FROM audit')),audit)
        with self.assertRaisesRegex(ValueError,'different data'):self.op(reason='Different reason')
        with self.assertRaisesRegex(ValueError,'already been reconciled'):self.op(key='second-request')
    def test_real_picks_cannot_be_reclassified_or_reopened(self):
        batch=self.c.batch();bulk=stock_id(self.db,batch,'roastery');self.c.move(bulk,'pack',package_id='p',units='2')
        self.c.runop(fulfillment_pick,{'fulfillment_id':'old-shipment','picks':[{'line_id':'l','stock_id':stock_id(self.db,batch,'roastery','p'),'grams':200}]},'Tester','real-pick')
        before=self.inventory()
        for action in ('pre_dashboard','reopen'):
            with self.assertRaisesRegex(ValueError,'physical stock pick'):self.op(action=action)
        self.assertEqual(self.inventory(),before);self.assertEqual(rows(self.db,'SELECT * FROM fulfillment_reconciliations'),[])
    def test_reopen_restores_reminder_with_history_and_can_be_acknowledged_again(self):
        before=self.inventory();self.op();self.op('reopen',reason='Marked the wrong shipment')
        self.assertEqual(self.inventory(),before);self.assertEqual(shipments.active(self.db),[])
        self.assertEqual(len(self.snapshot()['fulfillments']),1)
        self.assertEqual(one(self.db,"SELECT resolved FROM issues WHERE kind='external_fulfillment'")['resolved'],0)
        self.assertEqual(len(rows(self.db,'SELECT * FROM fulfillment_reconciliations')),2)
        # Replaying the old confirmation cannot hide the reopened reminder.
        self.assertTrue(self.op()['duplicate']);self.assertEqual(len(self.snapshot()['fulfillments']),1)
        self.op(key='reviewed-again');self.assertEqual(len(shipments.active(self.db)),1)
        self.assertEqual(len(rows(self.db,'SELECT * FROM fulfillment_reconciliations')),3)
    def test_invalid_notes_actions_requests_sources_and_dates_are_atomic(self):
        for changes in ({'reason':''},{'reason':'   '},{'reason':'x'*2001},{'key':''},{'action':'other'},{'action':'reopen'},{'id':'not-a-shipment'}):
            with self.subTest(changes=changes):
                data={'fulfillment_id':changes.get('id','old-shipment'),'action':changes.get('action','pre_dashboard'),'reason':changes.get('reason','Reviewed')}
                with self.assertRaises(ValueError):self.c.runop(shipments.reconcile,data,'Tester',changes.get('key','test-request'))
                self.assertEqual(rows(self.db,'SELECT * FROM fulfillment_reconciliations'),[])
                self.assertEqual(one(self.db,'SELECT recorded FROM fulfillment_events')['recorded'],0)
        self.db.execute("UPDATE fulfillment_events SET at='2026-12-01T03:00:00Z'")
        with self.assertRaisesRegex(ValueError,'future'):self.op()
        self.db.execute("UPDATE fulfillment_events SET at='2026-11-03T03:00:00Z'")
        self.db.execute("UPDATE orders SET source='wholesale'")
        with self.assertRaisesRegex(ValueError,'Shopify'):self.op()
    def test_reconciliation_history_cannot_be_changed_or_deleted(self):
        self.op()
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE fulfillment_reconciliations SET reason='replacement'")
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM fulfillment_reconciliations')
