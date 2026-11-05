import unittest,tempfile,os,io,json
from pathlib import Path
from unittest.mock import patch
from server.config import load_env
from server.adapters import request_json

class Configuration(unittest.TestCase):
 def test_env_is_literal_and_preserves_environment(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'EXISTING':'keep'},clear=True):
   p=Path(tmp)/'.env';p.write_text('EXISTING=replace\nKEY="value with spaces"\nEMPTY=\nexport LITERAL=\'$(do-not-run)\'\nCOMMENT=value # comment\n')
   load_env(p);self.assertEqual(os.environ['EXISTING'],'keep');self.assertEqual(os.environ['KEY'],'value with spaces');self.assertEqual(os.environ['EMPTY'],'');self.assertEqual(os.environ['LITERAL'],'$(do-not-run)');self.assertEqual(os.environ['COMMENT'],'value')
 def test_invalid_env_does_not_echo_secret(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'.env';p.write_text('KEY="unclosed-sensitive-value')
   with self.assertRaises(ValueError) as e:load_env(p)
   self.assertNotIn('sensitive',str(e.exception));self.assertIn('line 1',str(e.exception))
 def test_shopify_token_transport_is_form_encoded(self):
  with patch('server.adapters.urllib.request.urlopen',return_value=io.BytesIO(b'{"access_token":"fixture-only"}')) as opened:
   request_json('https://test.myshopify.com/admin/oauth/access_token',{'Content-Type':'application/x-www-form-urlencoded'},{'grant_type':'client_credentials','client_secret':'a+b&c'})
   req=opened.call_args.args[0];self.assertEqual(req.get_header('User-agent'),'WalnutsRoastery/0.1');self.assertEqual(req.get_header('Content-type'),'application/x-www-form-urlencoded');self.assertIn(b'client_secret=a%2Bb%26c',req.data)
