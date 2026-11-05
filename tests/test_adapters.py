import unittest,json,tempfile,os
from pathlib import Path
from unittest.mock import patch
from server.adapters import roast_records,Shopify,Scheduler,SyncError
from server.db import connect,migrate,rows,transaction
from server.imports import roast_import
import test_core

class Adapters(unittest.TestCase):
    def test_aillio_documented_pagination_and_headers(self):
        pages=[{'page':1,'size':100,'total':2,'totalPages':2,'data':[{'uid':'r1'}]},{'page':2,'size':100,'total':2,'totalPages':2,'data':[{'uid':'r2'}]}]
        with patch('server.adapters.request_json',side_effect=pages) as request:
            self.assertEqual([r['uid'] for r in roast_records('fixture-only-key')],['r1','r2'])
            self.assertEqual(request.call_args_list[0].args[0],'https://api.roast.world/api/v3/public/roasts?size=100&page=1')
            self.assertEqual(request.call_args_list[1].args[1],{'x-api-key':'fixture-only-key'})
    def test_aillio_unexpected_schema_fails_closed(self):
        with patch('server.adapters.request_json',return_value={'roasts':[]}):
            with self.assertRaises(SyncError):list(roast_records('fixture-only'))
    def test_shopify_outer_nested_pagination_and_fulfillment(self):
        o={'id':'gid://shopify/Order/1','name':'#1','updatedAt':'2026-11-20T01:00:00Z','cancelledAt':None,'displayFinancialStatus':'PAID','displayFulfillmentStatus':'PARTIALLY_FULFILLED'}
        line={'id':'gid://shopify/LineItem/1','title':'Coffee','sku':'COFFEE','quantity':2,'currentQuantity':2,'unfulfilledQuantity':1,'variant':{'id':'gid://shopify/ProductVariant/1'}}
        responses=[{'orders':{'nodes':[o],'pageInfo':{'hasNextPage':True,'endCursor':'outer1'}}},{'order':{'lineItems':{'nodes':[line],'pageInfo':{'hasNextPage':True,'endCursor':'line1'}}}},{'order':{'lineItems':{'nodes':[],'pageInfo':{'hasNextPage':False,'endCursor':None}}}},{'order':{'fulfillments':[{'id':'gid://shopify/Fulfillment/1','status':'SUCCESS','createdAt':'2026-11-20T00:00:00Z'}]}},{'fulfillment':{'fulfillmentLineItems':{'nodes':[{'quantity':1,'lineItem':{'id':line['id']}}],'pageInfo':{'hasNextPage':False,'endCursor':None}}}},{'orders':{'nodes':[],'pageInfo':{'hasNextPage':False,'endCursor':None}}}]
        responses.insert(3,{'order':{'shippingLines':{'nodes':[{'title':'Local pickup','deliveryCategory':'PICKUP'}],'pageInfo':{'hasNextPage':False,'endCursor':None}}}})
        with patch.dict(os.environ,{'SHOPIFY_SHOP':'test.myshopify.com','SHOPIFY_ACCESS_TOKEN':'fixture-only'},clear=True),patch.object(Shopify,'query',side_effect=responses) as q:
            result=list(Shopify().orders('2026-11-01T00:00:00Z'))
            self.assertEqual(result[0]['deliveryMethod'],'Local pickup · PICKUP');self.assertEqual(len(result),1);self.assertEqual(result[0]['lines'][0]['unfulfilledQuantity'],1);self.assertEqual(result[0]['fulfillments'][0]['lines'][0]['quantity'],1)
            self.assertEqual(q.call_args_list[0].args[1]['q'],"updated_at:>='2026-11-01T00:00:00+00:00'");self.assertIn('createdAt closedAt',q.call_args_list[0].args[0]);self.assertEqual(q.call_args_list[2].args[1]['after'],'line1');self.assertEqual(q.call_args_list[-1].args[1]['after'],'outer1')
    def test_shopify_api_pin_no_credentials_in_url(self):
        with patch.dict(os.environ,{'SHOPIFY_SHOP':'test.myshopify.com','SHOPIFY_ACCESS_TOKEN':'fixture-only'},clear=True),patch('server.adapters.request_json',return_value={'data':{'ok':1}}) as request:
            Shopify().query('query { shop { id } }',{})
            self.assertEqual(request.call_args.args[0],'https://test.myshopify.com/admin/api/2026-10/graphql.json');self.assertNotIn('fixture-only',request.call_args.args[0]);self.assertEqual(request.call_args.args[1]['X-Shopify-Access-Token'],'fixture-only')
    def test_shopify_host_allowlist(self):
        with patch.dict(os.environ,{'SHOPIFY_SHOP':'attacker.example/myshopify.com','SHOPIFY_ACCESS_TOKEN':'fixture'},clear=True):
            with self.assertRaises(SyncError):Shopify()
    def test_shopify_throttle_and_graphql_errors_redacted(self):
        with patch.dict(os.environ,{'SHOPIFY_SHOP':'test.myshopify.com','SHOPIFY_ACCESS_TOKEN':'fixture'},clear=True),patch('server.adapters.time.sleep'),patch('server.adapters.request_json',side_effect=[{'errors':[{'extensions':{'code':'THROTTLED'},'message':'private raw provider text'}]},{'data':{'ok':True}}]):self.assertEqual(Shopify().query('query{}',{}),{'ok':True})
        with patch.dict(os.environ,{'SHOPIFY_SHOP':'test.myshopify.com','SHOPIFY_ACCESS_TOKEN':'fixture'},clear=True),patch('server.adapters.request_json',return_value={'errors':[{'message':'SECRET customer address'}]}):
            with self.assertRaises(SyncError) as e:Shopify().query('query{}',{})
            self.assertNotIn('SECRET',str(e.exception))
    def test_sync_failure_visible_and_manual_operations_intact(self):
        case=test_core.Core();case.setUp()
        try:
            case.batch();scheduler=Scheduler(case.path)
            with patch.dict(os.environ,{'ROASTWORLD_API_KEY':'fixture'},clear=True),patch('server.adapters.roast_records',side_effect=SyncError('Authentication rejected.')):r=scheduler.sync('roastworld')
            self.assertEqual(r['status'],'error');self.assertEqual(case.total(),850000);self.assertEqual(rows(case.db,'SELECT * FROM sync_runs')[0]['status'],'error');case.batch();self.assertEqual(case.total(),1700000)
        finally:case.tearDown()
    def test_complete_sync_missing_source_preserves_inventory(self):
        case=test_core.Core();case.setUp()
        try:
            case.runop(roast_import,case.roast_record())
            with patch.dict(os.environ,{'ROASTWORLD_API_KEY':'fixture'},clear=True),patch('server.adapters.roast_records',return_value=iter([])):r=Scheduler(case.path).sync('roastworld')
            self.assertEqual(r['status'],'success');self.assertEqual(case.total(),850000);self.assertEqual(rows(case.db,'SELECT * FROM issues')[0]['kind'],'missing_source')
        finally:case.tearDown()
    def test_interrupted_roast_import_restarts_without_duplication(self):
        case=test_core.Core();case.setUp()
        try:
            def records(key,resource='roasts'):
                if resource=='beans':return iter([])
                def stream():
                    yield case.roast_record()
                    raise SyncError('Connection failed.')
                return stream()
            with patch.dict(os.environ,{'ROASTWORLD_API_KEY':'fixture'},clear=True),patch('server.adapters.roast_records',side_effect=records):self.assertEqual(Scheduler(case.path).sync('roastworld')['status'],'error')
            self.assertEqual(case.total(),850000)
            with patch.dict(os.environ,{'ROASTWORLD_API_KEY':'fixture'},clear=True),patch('server.adapters.roast_records',side_effect=lambda key,resource='roasts':iter([] if resource=='beans' else [case.roast_record()])):self.assertEqual(Scheduler(case.path).sync('roastworld')['status'],'success')
            self.assertEqual(case.total(),850000)
        finally:case.tearDown()

    def test_query_fix_backfills_before_reusing_old_watermark(self):
        case=test_core.Core();case.setUp()
        try:
            case.db.execute('INSERT INTO settings VALUES (?,?)',('shopify_watermark',json.dumps('2026-11-05T05:00:00Z')))
            with patch.dict(os.environ,{'SHOPIFY_SHOP':'test.myshopify.com','SHOPIFY_ACCESS_TOKEN':'fixture'},clear=True),patch('server.adapters.Shopify') as client:
                client.return_value.orders.return_value=iter([])
                self.assertEqual(Scheduler(case.path).sync('shopify')['status'],'success')
                from server.domain import dt,stamp
                from server.db import settings
                self.assertGreater((dt(stamp())-dt(client.return_value.orders.call_args.args[0])).days,50)
                self.assertEqual(settings(case.db)['shopify_import_version'],2)
        finally:case.tearDown()

    def test_roast_import_start_skips_old_invalid_logs_and_clears_only_their_reviews(self):
        case=test_core.Core();case.setUp()
        try:
            from server.domain import issue
            case.db.execute("UPDATE settings SET value=? WHERE key='roastworld_start_at'",(json.dumps('2026-11-04T15:00:00Z'),))
            r=case.roast_record(dateTime=1793804399000,weightRoasted=0,beanId=None)
            # Use an exact Tokyo boundary independently of the literal fixture value.
            from server.domain import dt
            r['dateTime']=int(dt('2026-11-04T23:59:59+09:00').timestamp()*1000)
            issue(case.db,'roastworld','r1','import_review','Old missing data');issue(case.db,'shopify','v1','variant_mapping','Keep Shopify issue')
            result=case.runop(roast_import,r);self.assertEqual(result['reason'],'before_import_start');self.assertEqual(case.total(),0)
            self.assertEqual(rows(case.db,"SELECT * FROM issues WHERE resolved=0")[0]['source'],'shopify')
            case.runop(roast_import,r);self.assertEqual(len(rows(case.db,"SELECT * FROM issues WHERE resolved=0")),1)
        finally:case.tearDown()
    def test_roast_import_start_includes_midnight_tokyo_and_keeps_new_validation(self):
        case=test_core.Core();case.setUp()
        try:
            from server.domain import dt
            case.db.execute("UPDATE settings SET value=? WHERE key='roastworld_start_at'",(json.dumps('2026-11-04T15:00:00Z'),))
            r=case.roast_record(dateTime=int(dt('2026-11-05T00:00:00+09:00').timestamp()*1000));result=case.runop(roast_import,r)
            self.assertIn('batch_id',result);self.assertEqual(case.total(),850000)
            bad=case.roast_record(uid='new-bad',weightRoasted=0);self.assertTrue(case.runop(roast_import,bad)['pending']);self.assertTrue(rows(case.db,"SELECT * FROM issues WHERE external_id='new-bad' AND resolved=0"))
        finally:case.tearDown()
    def test_existing_posted_roast_date_edit_still_creates_review_before_start(self):
        case=test_core.Core();case.setUp()
        try:
            from server.domain import dt
            r=case.roast_record();case.runop(roast_import,r)
            case.db.execute("UPDATE settings SET value=? WHERE key='roastworld_start_at'",(json.dumps('2026-11-04T15:00:00Z'),))
            r['dateTime']=int(dt('2026-10-01T00:00:00+09:00').timestamp()*1000);case.runop(roast_import,r)
            self.assertEqual(case.total(),850000);self.assertEqual(rows(case.db,"SELECT * FROM issues WHERE resolved=0")[0]['kind'],'source_edit')
        finally:case.tearDown()
