import copy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from key_boundary import audit, InvalidInput, pointer, read_spec
from report import render_svg, render_html

BASE = Path(__file__).resolve().parents[1] / 'examples/deliveries.json'


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.spec = read_spec(BASE)

    def test_order_loses_second_item_tenant_action_and_revision(self):
        result = audit(self.spec)['policies'][0]
        self.assertEqual(result['counts'], {'accepted': 1, 'false_merge': 4, 'duplicate': 1, 'unresolved': 1})
        self.assertEqual(result['rows'][1]['witness'], 'first-item')

    def test_delivery_envelope_admits_retry(self):
        p = audit(self.spec)['policies'][1]
        self.assertEqual(p['rows'][2]['status'], 'false_split')
        self.assertEqual(p['rows'][2]['witness'], 'first-item')

    def test_reference_policy_keeps_distinct_actions(self):
        self.assertEqual(audit(self.spec)['policies'][2]['counts'], {'accepted': 5, 'duplicate': 1, 'unresolved': 1})

    def test_missing_reference_never_teaches_cache(self):
        self.spec['deliveries'][0]['body']['item'] = None
        result = audit(self.spec)['policies'][0]
        self.assertEqual(result['rows'][0]['status'], 'unresolved')
        self.assertEqual(result['rows'][1]['status'], 'accepted')

    def test_candidate_missing_does_not_admit(self):
        del self.spec['deliveries'][0]['body']['delivery']
        self.assertEqual(audit(self.spec)['policies'][1]['rows'][0]['status'], 'unresolved')

    def test_expiry_exact_boundary_and_fixed_not_sliding(self):
        self.spec['policies'] = [{'name':'timed', 'fields':self.spec['reference_fields'], 'window_seconds':10}]
        first = self.spec['deliveries'][0]
        self.spec['deliveries'] = [dict(copy.deepcopy(first), id=str(t), at=t) for t in [0,9,10]]
        rows = audit(self.spec)['policies'][0]['rows']
        self.assertEqual([r['status'] for r in rows], ['accepted','duplicate','false_split'])
        self.assertEqual(rows[2]['witness'],'0')

    def test_delimiter_and_type_collisions_are_avoided(self):
        self.spec['reference_fields']=['/a','/b']
        self.spec['policies']=[{'name':'tuple','fields':['/a','/b']}]
        pairs=[('a|b','c'),('a','b|c'),(True,'c'),(1,'c'),('1','c')]
        self.spec['deliveries']=[dict(id=str(i),at=i,a=a,b=b) for i,(a,b) in enumerate(pairs)]
        self.assertEqual(audit(self.spec)['policies'][0]['counts'], {'accepted':5})

    def test_array_position_is_not_stable_identity(self):
        self.spec['reference_fields']=['/item']
        self.spec['policies']=[{'name':'position','fields':['/position']}]
        self.spec['deliveries']=[dict(id='a',at=0,item='a',position=0),dict(id='b',at=1,item='a',position=1)]
        self.assertEqual(audit(self.spec)['policies'][0]['rows'][1]['status'],'false_split')

    def test_pointer_escaping_arrays_and_missing(self):
        self.assertEqual(pointer({'a/b':{'~x':[0]}},'/a~1b/~0x/0'),'0')
        self.assertIsNone(pointer({'a':[3]},'/a/01'))
        self.assertIsNone(pointer({'a':{}},'/a'))
        with self.assertRaises(InvalidInput): pointer({},'/a~2')

    def test_rejects_unsorted_or_nonfinite_times_and_duplicate_rows(self):
        for bad in [-1, float('nan'), float('inf'), True]:
            s=copy.deepcopy(self.spec); s['deliveries'][1]['at']=bad
            with self.assertRaises(InvalidInput): audit(s)
        self.spec['deliveries'][1]['id']='first-item'
        with self.assertRaises(InvalidInput): audit(self.spec)

    def test_invalid_policy_config(self):
        for value in [0,-1,True,float('inf')]:
            s=copy.deepcopy(self.spec); s['policies'][0]['window_seconds']=value
            with self.assertRaises(InvalidInput): audit(s)
        self.spec['policies'][0]['fields']=[]
        with self.assertRaises(InvalidInput): audit(self.spec)

    def test_strict_json(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'input.json'
            for content in ['{"a":1,"a":2}', '{"a":NaN}']:
                p.write_text(content)
                with self.assertRaises(InvalidInput): read_spec(p)

    def test_audit_is_pure_and_repeatable(self):
        before=copy.deepcopy(self.spec)
        self.assertEqual(audit(self.spec),audit(self.spec))
        self.assertEqual(before,self.spec)

    def test_native_report_uses_computed_results_and_escapes(self):
        self.spec['policies'][0]['name']='<script>&'
        result=audit(self.spec); svg=render_svg(result)
        ET.fromstring(svg)
        self.assertIn('&lt;script&gt;&amp;',svg)
        self.assertIn('4 wrong drops / 0 repeat admits',svg)
        self.assertEqual(svg.count('WRONG DROP'),4)

    def test_field_evidence_reveals_why_two_items_collide(self):
        result=audit(self.spec)
        first, second = result['policies'][0]['rows'][:2]
        self.assertEqual(first['candidate_values'],second['candidate_values'])
        self.assertNotEqual(first['reference_values']['/body/item'],second['reference_values']['/body/item'])
        html=render_html(result)
        self.assertIn('Earlier delivery: first-item',html)
        self.assertIn('class="changed"',html)
        self.assertNotIn('<script',html)

    def test_cli_clean_start_outputs_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'audit'
            command=[sys.executable,str(BASE.parents[1]/'key_boundary.py'),str(BASE),'--out',str(out)]
            first=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            self.assertEqual(json.loads((out/'audit.json').read_text()),audit(self.spec))
            self.assertTrue((out/'comparison.svg').is_file())
            self.assertTrue((out/'audit.html').is_file())
            before={p.name:p.read_bytes() for p in out.iterdir()}
            second=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(second.returncode,2)
            self.assertEqual(before,{p.name:p.read_bytes() for p in out.iterdir()})


if __name__ == '__main__': unittest.main()
