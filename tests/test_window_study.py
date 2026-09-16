import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from key_boundary import InvalidInput, read_spec
from window_study import study, render_study, parse_windows

BASE = Path(__file__).resolve().parents[1]


class WindowStudyTests(unittest.TestCase):
    def setUp(self):
        self.spec = read_spec(BASE/'examples/window-tradeoff.json')

    def test_short_and_long_windows_fail_for_different_reasons(self):
        result = study(self.spec, [None,11,5,10,6])
        self.assertEqual(result['windows'], [5,6,10,11,None])
        order, identity = result['policies']
        self.assertEqual([e['within_limits'] for e in order['evaluations']], [False,True,True,False,False])
        self.assertEqual([e['within_limits'] for e in identity['evaluations']], [False,True,True,True,True])
        self.assertEqual(order['evaluations'][0]['counts']['false_split'],1)
        self.assertEqual(order['evaluations'][3]['counts']['false_merge'],1)

    def test_changes_show_exact_boundary_and_earlier_witness(self):
        evaluations = study(self.spec,[5,6,10,11])['policies'][0]['evaluations']
        self.assertEqual(evaluations[0]['changes_from_previous'],[])
        self.assertEqual(evaluations[1]['changes_from_previous'],[{'id':'retry-first','from_status':'false_split','to_status':'duplicate','from_witness':'first-item','to_witness':'first-item'}])
        self.assertEqual(evaluations[2]['changes_from_previous'],[])
        self.assertEqual(evaluations[3]['changes_from_previous'],[{'id':'second-item','from_status':'accepted','to_status':'false_merge','from_witness':None,'to_witness':'first-item'}])

    def test_no_cross_evaluation_cache_or_input_mutation(self):
        before = copy.deepcopy(self.spec)
        result = study(self.spec,[5,6,None])
        self.assertEqual(self.spec,before)
        self.assertEqual(result,study(self.spec,[None,6,5]))
        for policy in result['policies']:
            for e in policy['evaluations']:
                self.assertEqual(e['rows'][0]['status'],'accepted')

    def test_unresolved_is_visible_and_fails_default_limits(self):
        self.spec['deliveries'].append({'id':'unknown','at':15,'body':{'order':'order-17'}})
        for p in study(self.spec,[6,None])['policies']:
            self.assertTrue(all(not e['within_limits'] and e['counts']['unresolved']==1 for e in p['evaluations']))
        allowed = study(self.spec,[6],max_unresolved=1)
        self.assertTrue(allowed['policies'][0]['evaluations'][0]['within_limits'])
        self.assertEqual(allowed['policies'][0]['evaluations'][0]['counts']['unresolved'],1)

    def test_explicit_limits_do_not_hide_failures(self):
        result = study(self.spec,[5,11],max_wrong_drops=1,max_repeat_admits=1)
        self.assertTrue(all(e['within_limits'] for e in result['policies'][0]['evaluations']))
        self.assertEqual(result['policies'][0]['evaluations'][1]['counts']['false_merge'],1)
        self.assertIn('Limits: 1 wrong drops / 1 repeats / 0 unresolved',render_study(result))

    def test_invalid_grids_and_limits(self):
        for windows in [[],[0],[-1],[True],[float('nan')],[float('inf')],[1,1.0],[None,None],list(range(1,34))]:
            with self.subTest(windows=windows), self.assertRaises(InvalidInput): study(self.spec,windows)
        for value in [-1,True,0.5]:
            with self.assertRaises(InvalidInput): study(self.spec,[1],max_wrong_drops=value)
        self.spec['policies'] = [dict(self.spec['policies'][0],name=str(i)) for i in range(5)]
        with self.assertRaises(InvalidInput): study(self.spec,list(range(1,33)))

    def test_svg_escapes_names_and_reflects_results(self):
        self.spec['policies'][0]['name']='<order>&'
        svg=render_study(study(self.spec,[5,6,None]))
        ET.fromstring(svg)
        self.assertIn('&lt;order&gt;&amp;',svg)
        self.assertIn('3 deliveries. 3 windows.',svg)
        self.assertIn('Whole input',svg)
        self.assertEqual(parse_windows(' all, 5, 6 '),[5.0,6.0,None])

    def test_cli_runs_without_dependencies_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'report'
            cmd=[sys.executable,str(BASE/'window_study.py'),str(BASE/'examples/window-tradeoff.json'),'--windows','5,6,10,11,all','--out',str(out)]
            first=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            result=json.loads((out/'window-study.json').read_text())
            self.assertEqual(result,study(self.spec,[5,6,10,11,None]))
            before={p.name:p.read_bytes() for p in out.iterdir()}
            self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,2)
            self.assertEqual(before,{p.name:p.read_bytes() for p in out.iterdir()})
            invalid=cmd.copy();invalid[invalid.index('5,6,10,11,all')]='0';invalid[-1]=str(Path(folder)/'invalid')
            self.assertEqual(subprocess.run(invalid,capture_output=True).returncode,2)
            self.assertFalse(Path(invalid[-1]).exists())


if __name__ == '__main__': unittest.main()
