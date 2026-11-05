"""Single-instance server. Bind loopback behind HTTPS reverse proxy in production."""
import os,json,sys,argparse,threading,secrets,hashlib,hmac,base64,sqlite3,mimetypes,time,csv,io,re
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit,parse_qs
from .db import ROOT,connect,migrate,transaction,rows,one,settings,uid
from .domain import *
from .imports import roast_import,order_import,csv_preview,fulfillment_pick,release_excess
from .planner import plan
from .wholesale import save_order,dispatch_order
from .auth import password_hash,login,token_hash
from .adapters import Scheduler
from . import green

LIMIT=2*1024*1024

def state(db,user,scheduler):
    cfg=settings(db);clock=now(db);stocks=[]
    for r in rows(db,'SELECT id FROM stocks'):
        s=stock(db,r['id']);s['free_mg']=s['quantity_mg']-s['reserved_mg'];s['readiness']={u:dict(zip(('eligible','ready_at','label'),eligibility(s,u,clock))) for u in ('brew','dispatch','retail')};stocks.append(s)
    batches=rows(db,'SELECT b.*,c.name coffee,c.profile FROM batches b LEFT JOIN coffees c ON c.id=b.coffee_id ORDER BY roasted_at DESC')
    for b in batches:
        b['remaining_mg']=sum(s['quantity_mg']+s['overfill_mg'] for s in stocks if s['batch_id']==b['id']);b['readiness']={u:dict(zip(('eligible','ready_at','label'),eligibility(b,u,clock))) for u in ('brew','dispatch','retail')}
        b.pop('source_json',None)
    orders=rows(db,'SELECT * FROM orders ORDER BY due_at,number')
    for o in orders:
        o['wholesale']=one(db,'SELECT * FROM wholesale_orders WHERE order_id=?',(o['id'],)) if o['source']=='wholesale' else None
        if o['wholesale']:o['wholesale']['customer']=json.loads(o['wholesale'].pop('customer_json'))
        o['lines']=rows(db,'SELECT l.*,v.kind,v.coffee_id,v.package_id,p.weight_mg FROM lines l LEFT JOIN variants v ON v.id=l.variant_id LEFT JOIN packages p ON p.id=v.package_id WHERE l.order_id=?',(o['id'],))
        for l in o['lines']:
            l['allocations']=rows(db,'SELECT r.*,b.code,s.package_id FROM reservations r JOIN stocks s ON s.id=r.stock_id JOIN batches b ON b.id=s.batch_id WHERE line_id=?',(l['id'],))
            l['required_mg']=l['unfulfilled']*(l['weight_mg'] or 0);l['allocated_mg']=sum(a['quantity_mg'] for a in l['allocations']);l['missing_mg']=max(0,l['required_mg']-l['allocated_mg'])
            if l['kind']=='noncoffee':status='Non-coffee'
            elif o['cancelled']:status='Cancelled'
            elif l['kind']!='coffee':status='Needs mapping'
            elif not order_eligible(db,o['id']):status='Wholesale draft' if o['source']=='wholesale' else 'Awaiting payment'
            elif not l['unfulfilled']:status='Shopify fulfilled / removed'
            elif not o['due_at']:status='Needs deadline'
            elif any(not eligibility(stock(db,a['stock_id']),'dispatch',o['due_at'])[0] for a in l['allocations']):status='Allocation at risk'
            elif any(a['quantity_mg']%l['weight_mg'] for a in l['allocations']):status='Review split-bag allocations'
            elif l['missing_mg']:status='Needs allocation / roasting'
            elif any(not eligibility(stock(db,a['stock_id']),'dispatch',clock)[0] for a in l['allocations']):status='Resting'
            elif any(a['package_id']=='bulk' for a in l['allocations']):status='Ready to pack'
            else:status='Packed / allocated'
            l['status']=status
    sync={}
    for source,configured in scheduler.configured().items():
        runs=rows(db,'SELECT * FROM sync_runs WHERE source=? ORDER BY started_at DESC,rowid DESC LIMIT 1',(source,));success=rows(db,"SELECT finished_at FROM sync_runs WHERE source=? AND status='success' ORDER BY finished_at DESC LIMIT 1",(source,))
        last=success[0]['finished_at'] if success else None
        sync[source]={'configured':configured and not cfg['demo'],'last_attempt':runs[0] if runs else None,'last_success':last,'stale':not last or (dt(stamp())-dt(last)).total_seconds()>cfg['poll_seconds']*2}
    return {'user':{k:user[k] for k in ('id','name','role')},'settings':cfg,'clock':clock,'shop_admin_url':('https://'+os.environ['SHOPIFY_SHOP']+'/admin') if re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com',os.getenv('SHOPIFY_SHOP','')) else None,'green':green.snapshot(db),'stocks':stocks,'batches':batches,'orders':orders,'coffees':rows(db,'SELECT * FROM coffees'),'locations':rows(db,'SELECT * FROM locations'),'packages':rows(db,'SELECT * FROM packages'),'reservations':rows(db,'SELECT r.*,b.code FROM reservations r JOIN stocks s ON s.id=r.stock_id JOIN batches b ON b.id=s.batch_id'),'variants':rows(db,'SELECT * FROM variants'),'bean_mappings':rows(db,'SELECT * FROM bean_mappings'),'demands':rows(db,'SELECT * FROM demands'),'plans':rows(db,'SELECT p.*,c.name coffee FROM plans p JOIN coffees c ON c.id=p.coffee_id ORDER BY roast_at'),'issues':rows(db,'SELECT * FROM issues WHERE resolved=0 ORDER BY created_at DESC'),'sync':sync,'planner':plan(db),'fulfillments':rows(db,'SELECT * FROM fulfillment_events WHERE recorded=0'),'imports':rows(db,"SELECT source,external_id,payload FROM imports WHERE source IN ('beans','roastworld')"),'users':rows(db,'SELECT id,name,role,active FROM users') if user['role']=='admin' else []}

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,addr,path):
        self.dbpath=path;self.scheduler=Scheduler(path);self.login_attempts={};self.rate_lock=threading.Lock();super().__init__(addr,Handler)

class Handler(BaseHTTPRequestHandler):
    server_version='Walnuts'
    def log_message(self,fmt,*args):pass # no URLs, payloads, passwords, tokens or customer fields in request logs
    def send(self,status,data,content_type='application/json',cookie=None):
        body=json.dumps(data,ensure_ascii=False).encode() if content_type=='application/json' else data
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store' if self.path.startswith('/api') else 'no-cache')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin');self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(body)
    def cookie(self,token='',expired=False):
        return 'walnuts_session='+token+'; Path=/; HttpOnly; SameSite=Strict; Max-Age='+('0' if expired else '43200')+('; Secure' if os.getenv('COOKIE_SECURE','0')=='1' else '')
    def session(self,db):
        cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''));token=cookies.get('walnuts_session')
        if not token:return None
        r=db.execute('SELECT u.id,u.name,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1',(token_hash(token.value),stamp())).fetchone()
        return dict(r) if r else None
    def origin_ok(self):
        configured=os.getenv('APP_ORIGIN');host=self.headers.get('Host','');expected=configured or 'http://'+host
        if not configured and host.split(':')[0] not in ('127.0.0.1','localhost','[::1]'):return False
        return self.headers.get('Origin') in (None,expected) and (not self.headers.get('Sec-Fetch-Site') or self.headers['Sec-Fetch-Site'] in ('same-origin','none'))
    def do_GET(self):
        db=connect(self.server.dbpath)
        try:
            path=urlsplit(self.path).path
            if path=='/api/session':
                user=self.session(db);return self.send(200,{'user':user,'demo':settings(db)['demo'],'configured':bool(db.execute('SELECT 1 FROM users').fetchone())})
            if path.startswith('/api/'):
                user=self.session(db)
                if not user:return self.send(401,{'error':'Please sign in.'})
                if path=='/api/state':return self.send(200,state(db,user,self.server.scheduler))
                if path=='/api/history':
                    query=parse_qs(urlsplit(self.path).query);batch=query.get('batch',[''])[0]
                    return self.send(200,{'movements':rows(db,'SELECT m.*,e.delta_mg,e.delta_overfill_mg,s.location_id,s.package_id FROM entries e JOIN movements m ON m.id=e.movement_id JOIN stocks s ON s.id=e.stock_id WHERE s.batch_id=? ORDER BY m.at DESC,m.rowid DESC',(batch,)),'audit':rows(db,'SELECT * FROM audit ORDER BY id DESC LIMIT 200')})
                if path=='/api/export':
                    if user['role']!='admin':return self.send(403,{'error':'Administrator access required.'})
                    return self.send(200,{'exported_at':stamp(),'green_beans':rows(db,'SELECT * FROM green_beans'),'green_coffee_links':rows(db,'SELECT * FROM green_coffee_links'),'green_events':rows(db,'SELECT * FROM green_events'),'stocks':rows(db,'SELECT * FROM stocks'),'batches':rows(db,'SELECT * FROM batches'),'movements':rows(db,'SELECT * FROM movements'),'entries':rows(db,'SELECT * FROM entries'),'reservations':rows(db,'SELECT * FROM reservations'),'audit':rows(db,'SELECT * FROM audit')})
                return self.send(404,{'error':'Unknown endpoint.'})
            relative='index.html' if path=='/' else path.lstrip('/')
            f=(ROOT/'static'/relative).resolve()
            if not f.is_relative_to(ROOT/'static') or not f.is_file():return self.send(404,b'Not found','text/plain')
            return self.send(200,f.read_bytes(),mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
        except (ValueError,sqlite3.Error):self.send(400,{'error':'Unable to read records. Refresh or check server health.'})
        finally:db.close()
    def webhook(self):
        secret=os.getenv('SHOPIFY_WEBHOOK_SECRET')
        if not secret:return self.send(404,{'error':'Webhooks are not enabled.'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self.send(400,{'error':'Invalid payload length.'})
        if length<=0 or length>LIMIT:return self.send(413,{'error':'Webhook payload exceeds the configured 2 MB limit.'})
        raw=self.rfile.read(length)
        expected=base64.b64encode(hmac.new(secret.encode(),raw,hashlib.sha256).digest()).decode()
        if not hmac.compare_digest(expected,self.headers.get('X-Shopify-Hmac-Sha256','')):return self.send(401,{'error':'Invalid webhook signature.'})
        if self.headers.get('X-Shopify-Shop-Domain')!=os.getenv('SHOPIFY_SHOP'):return self.send(403,{'error':'Unexpected shop.'})
        id=self.headers.get('X-Shopify-Webhook-Id','');topic=self.headers.get('X-Shopify-Topic','')
        if not id or len(id)>200 or topic not in ('orders/create','orders/updated','orders/cancelled','refunds/create','fulfillments/create','fulfillments/update'):return self.send(400,{'error':'Unsupported topic or missing delivery identity.'})
        # Authenticate raw bytes first. Persist only delivery metadata, never customer payloads.
        try:json.loads(raw)
        except (ValueError,UnicodeDecodeError):return self.send(400,{'error':'Invalid JSON.'})
        db=connect(self.server.dbpath)
        try:
            if settings(db)['demo']:return self.send(409,{'error':'Live webhooks are disabled in demo mode.'})
            digest=hashlib.sha256(raw).hexdigest()
            with transaction(db):
                old=db.execute('SELECT payload_hash FROM webhook_deliveries WHERE id=?',(id,)).fetchone()
                if old and old['payload_hash']!=digest:return self.send(409,{'error':'Delivery ID conflicts with earlier payload.'})
                db.execute('INSERT OR IGNORE INTO webhook_deliveries VALUES (?,?,?,?,?,NULL)',(id,self.headers.get('X-Shopify-Event-Id',''),topic,digest,stamp()))
            self.server.scheduler.wake.set()
            return self.send(200,{'accepted':True})
        except sqlite3.Error:return self.send(503,{'error':'Could not persist delivery. Please retry.'})
        finally:db.close()
    def do_POST(self):
        if urlsplit(self.path).path=='/api/webhook/shopify':return self.webhook()
        if not self.origin_ok():return self.send(403,{'error':'Request origin rejected. Configure APP_ORIGIN to the HTTPS site URL.'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self.send(400,{'error':'Invalid content length.'})
        if length<=0 or length>LIMIT:return self.send(413,{'error':'Request must be between 1 byte and 2 MB.'})
        try:d=json.loads(self.rfile.read(length))
        except (json.JSONDecodeError,UnicodeDecodeError):return self.send(400,{'error':'Invalid JSON.'})
        if not isinstance(d,dict):return self.send(400,{'error':'Expected a JSON object.'})
        db=connect(self.server.dbpath);path=urlsplit(self.path).path
        try:
            if path=='/api/login':
                address=self.client_address[0]
                with self.server.rate_lock:
                    attempts=[t for t in self.server.login_attempts.get(address,[]) if time.monotonic()-t<300]
                    if len(attempts)>=10:return self.send(429,{'error':'Too many attempts. Wait five minutes.'})
                    attempts.append(time.monotonic());self.server.login_attempts[address]=attempts
                with transaction(db):token,csrf,user=login(db,str(d.get('name',''))[:100],str(d.get('password',''))[:1024])
                return self.send(200,{'csrf':csrf,'user':{k:user[k] for k in ('id','name','role')}},cookie=self.cookie(token))
            user=self.session(db)
            if not user:return self.send(401,{'error':'Session expired. Sign in again.'})
            if not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),user['csrf']):return self.send(403,{'error':'Session token missing. Reload and retry.'})
            admin=path in ('/api/settings','/api/coffee','/api/package','/api/location','/api/user','/api/variant','/api/bean-map','/api/csv-preview','/api/csv-commit','/api/retry-import','/api/batch-policy','/api/issue','/api/order-import','/api/sync','/api/roast-import','/api/green-reverse') or (path=='/api/move' and d.get('kind') in ('reverse','return'))
            if admin and user['role']!='admin':return self.send(403,{'error':'Administrator access required.'})
            actor=user['name'];request=self.headers.get('Idempotency-Key','')
            if path=='/api/sync':
                source=d['source']
                if source not in ('roastworld','shopify'):raise ValueError('Unknown connection.')
                threading.Thread(target=self.server.scheduler.sync,args=(source,),daemon=True).start();return self.send(202,{'status':'queued'})
            with transaction(db):result=self.mutate(db,path,d,actor,user,request)
            return self.send(200,result or {'ok':True},cookie=self.cookie(expired=True) if path=='/api/logout' else None)
        except (ValueError,KeyError,TypeError,OverflowError) as e:
            message=str(e) if isinstance(e,ValueError) else 'Missing or invalid field. Check the form and try again.'
            self.send(400,{'error':message})
        except sqlite3.IntegrityError:self.send(409,{'error':'This record conflicts with existing data. Refresh; no partial action was saved.'})
        except sqlite3.OperationalError:self.send(503,{'error':'Database is busy or unavailable. No success confirmed; refresh before retrying.'})
        except Exception:self.send(500,{'error':'Action failed. No success confirmed. Check the server and retry with the same request identifier.'})
        finally:db.close()
    def mutate(self,db,path,d,actor,user,request):
        if path=='/api/logout':db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],));return
        if path=='/api/batch-notes':
            one(db,'SELECT id FROM batches WHERE id=?',(d['id'],))
            db.execute('UPDATE batches SET notes=? WHERE id=?',(d['notes'],d['id']));audit(db,actor,'batch_notes',d);return
        if path=='/api/green-bean':return green.save_bean(db,d,actor,request)
        if path=='/api/green-purchase':return green.receive(db,d,actor,request)
        if path=='/api/green-count':return green.count(db,d,actor,request)
        if path=='/api/green-reverse':return green.reverse(db,d,actor,request)
        if path=='/api/batch':return create_batch(db,d,actor,request)
        if path=='/api/move':return movement(db,d,actor,request)
        if path=='/api/link-plan':return link_completed_plan(db,d,actor,request)
        if path=='/api/wholesale':return save_order(db,d,actor,request)
        if path=='/api/wholesale-dispatch':return dispatch_order(db,d,actor,request)
        if path=='/api/fulfillment-pick':return fulfillment_pick(db,d,actor,request)
        if path=='/api/settings':
            allowed={'charge_mg','max_charge_mg','roast_days','roast_slots','roast_days_confirmed','buffer_days','safety_bp','channel_priority','eligible_payments','cutover_at','roastworld_start_at','poll_seconds','brand_color'}
            if not set(d)<=allowed:raise ValueError('Unknown setting.')
            for k in ('charge_mg','max_charge_mg','poll_seconds','buffer_days','safety_bp'):
                if k in d:d[k]=int(d[k])
                if k in d and (d[k]<0 or d[k]>10**9):raise ValueError('Setting out of range.')
            if 'charge_mg' in d and d['charge_mg']==0:raise ValueError('Working charge must be positive.')
            if 'poll_seconds' in d and d['poll_seconds']<60:raise ValueError('Poll interval must be at least 60 seconds.')
            if 'roast_days' in d and (not d['roast_days'] or any(type(n)!=int or n not in range(7) for n in d['roast_days'])):raise ValueError('Choose at least one valid roast weekday.')
            if 'roast_slots' in d and (not isinstance(d['roast_slots'],list) or not d['roast_slots'] or len(d['roast_slots'])!=len(set(d['roast_slots'])) or any(not isinstance(t,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',t) for t in d['roast_slots'])):raise ValueError('Choose distinct roast start slots in HH:MM format.')
            if 'channel_priority' in d and sorted(d['channel_priority'])!=['brew','dispatch','retail']:raise ValueError('Choose each channel once.')
            if 'eligible_payments' in d and (not isinstance(d['eligible_payments'],list) or not all(v in ['PAID','PARTIALLY_PAID','PENDING','AUTHORIZED'] for v in d['eligible_payments'])):raise ValueError('Invalid payment policy.')
            if d.get('cutover_at'):d['cutover_at']=stamp(d['cutover_at'])
            if d.get('roastworld_start_at'):d['roastworld_start_at']=stamp(d['roastworld_start_at'])
            for k,v in d.items():db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(v),k))
            if 'eligible_payments' in d:
                for l in rows(db,'SELECT l.id,o.payment,o.cancelled,o.source FROM lines l JOIN orders o ON o.id=l.order_id'):
                    if l['source']!='wholesale' and (l['cancelled'] or l['payment'] not in d['eligible_payments']):release_excess(db,l['id'],0,actor)
            audit(db,actor,'settings',d);return
        if path=='/api/coffee':
            id=d.get('id') or uid();brew=int(d['brew_days']);dispatch=None if d.get('dispatch_days') in (None,'') else int(d['dispatch_days']);retail=None if d.get('retail_days') in (None,'') else int(d['retail_days']);fresh=int(d['fresh_days']);yb=int(d['yield_bp'])
            if fresh<=brew or (dispatch is not None and fresh<=dispatch) or (retail is not None and fresh<=retail):raise ValueError('Freshness window must extend beyond the selected rest periods.')
            db.execute('INSERT INTO coffees VALUES (?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET name=excluded.name,profile=excluded.profile,brew_days=excluded.brew_days,dispatch_days=excluded.dispatch_days,retail_days=excluded.retail_days,fresh_days=excluded.fresh_days,yield_bp=excluded.yield_bp,policy_version=coffees.policy_version+1',(id,d['name'],d['profile'],brew,dispatch,retail,fresh,yb));audit(db,actor,'coffee_policy',d);return {'id':id}
        if path=='/api/package':
            id=uid();db.execute('INSERT INTO packages VALUES (?,?,?)',(id,d['name'],positive(d['grams'])));return {'id':id}
        if path=='/api/location':
            id=uid();db.execute('INSERT INTO locations VALUES (?,?)',(id,d['name']));return {'id':id}
        if path=='/api/user':
            if d.get('id'):
                if d['id']==user['id'] and (not d.get('active',True) or d['role']!='admin'):raise ValueError('Cannot demote or deactivate your current admin account.')
                db.execute('UPDATE users SET role=?,active=? WHERE id=?',(d['role'],int(d.get('active',True)),d['id']));db.execute('DELETE FROM sessions WHERE user_id=?',(d['id'],))
                if d.get('password'):db.execute('UPDATE users SET password_hash=? WHERE id=?',(password_hash(d['password']),d['id']))
            else:db.execute('INSERT INTO users VALUES (?,?,?,?,1)',(uid(),d['name'],password_hash(d['password']),d['role']))
            audit(db,actor,'user_access',{'name':d.get('name'),'id':d.get('id'),'role':d['role']});return
        if path=='/api/variant':
            v=one(db,'SELECT * FROM variants WHERE id=?',(d['id'],))
            if db.execute('SELECT 1 FROM reservations r JOIN lines l ON l.id=r.line_id WHERE l.variant_id=?',(v['id'],)).fetchone():raise ValueError('Release current allocations before changing the variant mapping.')
            kind=d['kind'];c=d.get('coffee_id') if kind=='coffee' else None;p=d.get('package_id') if kind=='coffee' else None
            if kind=='coffee' and (not c or not p):raise ValueError('Choose a coffee and net package size.')
            db.execute('UPDATE variants SET kind=?,coffee_id=?,package_id=?,grind=? WHERE id=?',(kind,c,p,d.get('grind',''),v['id']))
            if kind!='unresolved':db.execute("UPDATE issues SET resolved=1 WHERE source='shopify' AND external_id=? AND kind='variant_mapping'",(v['id'],))
            audit(db,actor,'variant_mapping',d);return
        if path=='/api/bean-map':
            db.execute('INSERT INTO bean_mappings VALUES (?,?) ON CONFLICT(external_id) DO UPDATE SET coffee_id=excluded.coffee_id',(d['external_id'],d['coffee_id']));audit(db,actor,'bean_mapping',d);return
        if path=='/api/roast-import':return roast_import(db,d,actor)
        if path=='/api/retry-import':return roast_import(db,json.loads(one(db,"SELECT payload FROM imports WHERE source='roastworld' AND external_id=?",(d['external_id'],))['payload']),actor)
        if path=='/api/order-import':return order_import(db,d,actor)
        if path=='/api/csv-preview':return {'rows':csv_preview(db,d['csv'])}
        if path=='/api/csv-commit':
            records=csv_preview(db,d['csv'])
            if any(r['errors'] for r in records):raise ValueError('Resolve every validation error before import.')
            return {'results':[roast_import(db,r['source'],actor) for r in records]}
        if path=='/api/batch-policy':
            b=one(db,'SELECT * FROM batches WHERE id=?',(d['id'],))
            if not d.get('reason'):raise ValueError('A policy or quality decision requires a reason.')
            if 'held' in d:db.execute('UPDATE batches SET held=?,hold_reason=? WHERE id=?',(int(d['held']),d['reason'],b['id']))
            if 'archived' in d:db.execute('UPDATE batches SET archived=? WHERE id=?',(int(d['archived']),b['id']))
            if d.get('recalculate'):
                p=policy(one(db,'SELECT * FROM coffees WHERE id=?',(b['coffee_id'],)))
                db.execute('UPDATE batches SET policy=? WHERE id=?',(json.dumps(p),b['id']))
            if 'override' in d:
                p=json.loads(b['policy']);override=d['override']
                if not set(override)<={'brew_days','dispatch_days','retail_days','fresh_days'} or any(type(v)!=int or v<0 for v in override.values()):raise ValueError('Rest override must contain nonnegative whole days.')
                p.update(override)
                if p['fresh_days']<=max(v or 0 for k,v in p.items() if k in ('brew_days','dispatch_days','retail_days')):raise ValueError('Freshness window must extend beyond rest periods.')
                db.execute('UPDATE batches SET policy=? WHERE id=?',(json.dumps(p),b['id']))
            for r in rows(db,'SELECT r.* FROM reservations r JOIN stocks s ON s.id=r.stock_id WHERE s.batch_id=?',(b['id'],)):
                if not eligibility(one(db,'SELECT * FROM batches WHERE id=?',(b['id'],)),r['use'],r['due_at'])[0]:issue(db,'local',r['id'],'allocation_at_risk','Batch policy/hold changed. Review and replace the affected reservation.')
            audit(db,actor,'batch_policy',{'before':b,'change':d});return
        if path=='/api/order-local':
            if one(db,'SELECT source FROM orders WHERE id=?',(d['id'],))['source']=='wholesale':raise ValueError('Use Edit wholesale order to change this order and its deadline.')
            db.execute('UPDATE orders SET due_at=?,notes=? WHERE id=?',(stamp(d['due_at']) if d.get('due_at') else None,d.get('notes',''),d['id']));audit(db,actor,'order_deadline',d);return
        if path=='/api/demand':
            if d.get('delete'):
                if db.execute('SELECT 1 FROM reservations WHERE demand_id=?',(d['id'],)).fetchone():raise ValueError('Release allocations first.')
                db.execute('DELETE FROM demands WHERE id=?',(d['id'],));audit(db,actor,'demand_removed',d);return
            q=positive(d['grams']);id=d.get('id') or uid()
            if db.execute('SELECT 1 FROM reservations WHERE demand_id=?',(id,)).fetchone():raise ValueError('Release allocations before editing demand.')
            db.execute('INSERT INTO demands VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET coffee_id=excluded.coffee_id,channel=excluded.channel,due_at=excluded.due_at,quantity_mg=excluded.quantity_mg,note=excluded.note',(id,d['coffee_id'],d['channel'],stamp(d['due_at']),q,d.get('note','')));audit(db,actor,'forecast',d);return
        if path=='/api/plan':
            m,repeat=begin_move(db,'plan',actor,d,request)
            if repeat:return {'duplicate':True}
            cfg=settings(db);g=positive(d['green_g']);c=one(db,'SELECT * FROM coffees WHERE id=?',(d['coffee_id'],));roast=stamp(d['roast_at'])
            if not cfg['max_charge_mg'] or g>cfg['max_charge_mg']:raise ValueError('Confirm maximum Bullet capacity; charge must fit.')
            if dt(roast).astimezone(JST).weekday() not in cfg['roast_days']:raise ValueError('This date is not a configured roasting day.')
            if dt(roast).astimezone(JST).strftime('%H:%M') not in cfg['roast_slots']:raise ValueError('Choose a configured roast start slot, or edit slots in Settings.')
            if db.execute("SELECT 1 FROM plans WHERE status='planned' AND roast_at=? AND id!=?",(roast,d.get('id',''))).fetchone():raise ValueError('This roast slot is occupied. Choose another slot.')
            if dt(roast)<dt(now(db)):raise ValueError('A plan cannot be scheduled in the past. Review the deadline conflict.')
            id=d.get('id') or uid();expected=positive(d['expected_g'])
            if expected>=g:raise ValueError('Expected roasted output must be below green input.')
            old=db.execute('SELECT * FROM plans WHERE id=?',(id,)).fetchone()
            if old and old['status']!='planned':raise ValueError('Only open plans can be edited.')
            db.execute('INSERT INTO plans VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET roast_at=excluded.roast_at,green_mg=excluded.green_mg,expected_mg=excluded.expected_mg,explanation=excluded.explanation',(id,c['id'],roast,g,expected,'planned',d.get('explanation','Reviewed manual plan'),json.dumps(policy(c))));audit(db,actor,'plan',d);return
        if path=='/api/plan-cancel':
            db.execute("UPDATE plans SET status='cancelled' WHERE id=? AND status='planned'",(d['id'],));audit(db,actor,'plan_cancel',d);return
        if path=='/api/issue':
            if not d.get('reason'):raise ValueError('Document the reconciliation decision.')
            db.execute('UPDATE issues SET resolved=1 WHERE id=?',(d['id'],));audit(db,actor,'issue_resolved',d);return
        raise ValueError('Unknown action.')

def main():
    from .config import load_env
    load_env(ROOT/'.env')
    ap=argparse.ArgumentParser();ap.add_argument('--db',default=os.getenv('DATABASE_PATH','data/production.sqlite'));ap.add_argument('--host',default='127.0.0.1');ap.add_argument('--port',type=int,default=8765);ap.add_argument('--demo',action='store_true');ap.add_argument('--init-admin',action='store_true');args=ap.parse_args()
    path=str(Path(args.db).resolve())
    if args.demo and args.db=='data/production.sqlite':ap.error('--demo requires an explicit separate --db path')
    migrate(path);db=connect(path)
    if args.init_admin:
        import getpass
        if db.execute('SELECT 1 FROM users').fetchone():raise SystemExit('An account already exists. Manage access in Settings.')
        name=input('First administrator username: ').strip();password=getpass.getpass('Password (12+ characters): ')
        if not name or password!=getpass.getpass('Repeat password: '):raise SystemExit('Username or password confirmation invalid.')
        with transaction(db):db.execute('INSERT INTO users VALUES (?,?,?,?,1)',(uid(),name,password_hash(password),'admin'))
        print('Administrator created. Start the server normally.');return
    if args.demo:
        if not db.execute('SELECT 1 FROM users').fetchone():
            from .demo import seed
            seed(db)
        if not settings(db)['demo']:raise SystemExit('Refusing to start a production database as demo.')
    if settings(db)['demo'] and args.host not in ('127.0.0.1','localhost'):raise SystemExit('Demo is loopback-only. Do not expose demo credentials.')
    if args.host not in ('127.0.0.1','localhost') and (not os.getenv('APP_ORIGIN','').startswith('https://') or os.getenv('COOKIE_SECURE')!='1'):raise SystemExit('Network binding requires HTTPS APP_ORIGIN and COOKIE_SECURE=1. Use a reverse proxy.')
    db.close();server=Server((args.host,args.port),path);threading.Thread(target=server.scheduler.loop,daemon=True).start()
    print(f'Walnuts Roastery ready at http://{args.host}:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.scheduler.stop.set();server.scheduler.wake.set();server.server_close()
if __name__=='__main__':main()
