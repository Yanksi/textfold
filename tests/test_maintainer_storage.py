"""Compatibility regressions from the maintainer review; disposable data only."""
import copy, json, tempfile, unittest
from pathlib import Path
from textfold import sync_records
from textfold.documents import Document
from textfold.document_wire import pack
from textfold.sqlite_storage import SQLiteBackend

class ReviewRegressions(unittest.TestCase):
    def test_documented_thread_additions_survive_stale_message_sidecars(self):
        note = {'id':'n-thread', 'anchor':{}, 'thread':[{'q':'First', 'a':'Old reply'}]}
        note['messages'] = sync_records.messages(note)
        note['thread'].append({'q':'Added by old pip', 'a':'Paid reply'})
        doc = Document('md-legacy', notes={'notes':[note]})
        joined = sync_records.join(doc.id, sync_records.split(pack(doc)[0]))
        actual = joined['notes']['notes'][0]
        self.assertEqual([t['q'] for t in actual['thread']], ['First', 'Added by old pip'])
        self.assertEqual(len(actual['messages']), 4)
        self.assertEqual(sync_records.last_answer(note), actual['thread'][-1]['message_id'])
        actual['text'] = 'Edited annotation'
        again = sync_records.join(doc.id, sync_records.note_records(doc.id, {'notes':[actual]}))
        self.assertEqual(again['notes']['notes'][0]['thread'], actual['thread'])

    def test_empty_canonical_thread_does_not_resurrect_archived_messages(self):
        note = {'id':'n-thread', 'anchor':{}, 'thread':[{'q':'First', 'a':'Old reply'}]}
        note['messages'] = sync_records.messages(note); note['thread'] = []
        value = sync_records.join('md-thread', sync_records.note_records('md-thread', {'notes':[note]}))
        self.assertEqual(value['notes']['notes'][0]['thread'], [])
        self.assertEqual(len(value['notes']['notes'][0]['messages']), 2)

    def test_id_history_merges_each_identity_and_conflict_candidates_keep_other_ids(self):
        with tempfile.TemporaryDirectory() as root:
            backend = SQLiteBackend(root)
            def records(units):
                raw = json.dumps({'format':'textfold/ids', 'version':1, 'units':units, 'sections':{}}).encode()
                doc = Document('md-history', extensions={'ids.json':raw}, _legacy={'ids.json':raw})
                manifest, blobs = pack(doc)
                backend._blobs(blobs)
                return sync_records.split(manifest)
            def history(values):
                ref = values['extensions/ids.json']
                return json.loads(backend._download(ref['sha256'], ref['size']))['units']
            with backend.transaction():
                base = records({'old':{'section':'s1'}})
                left = records({'old':{'section':'s1'}, 'phone':{'section':'s2'}})
                right = records({'old':{'section':'s1'}, 'laptop':{'section':'s3'}})
                merged, conflicts = backend.reconcile(base,left,right)
                self.assertEqual(conflicts, [])
                self.assertEqual(set(history(merged)), {'old','phone','laptop'})
                left = records({'old':{'section':'phone'}, 'phone':{'section':'s2'}})
                right = records({'old':{'section':'laptop'}, 'laptop':{'section':'s3'}})
                merged, conflicts = backend.reconcile(base,left,right)
                self.assertEqual(len(conflicts), 1)
                for ref in merged['conflict/'+conflicts[0]]['variants']:
                    value = json.loads(backend._download(ref['sha256'], ref['size']))
                    self.assertEqual(set(value['units']), {'old','phone','laptop'})

    def test_default_local_mode_runs_without_cloud_optional_packages(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as root:
            script = r"""
import builtins, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in ('keyring', 'websockets'): raise ImportError('Optional cloud package absent')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from textfold import store, local, notes, cloud_settings
store.initialize_storage()
pid = local.import_text('# Default local\n\nNo cloud packages required.')
notes.put(pid, {'id':'n-local','anchor':{'on':'paper'},'text':'Kept'})
assert notes.read(pid)['notes'][0]['text'] == 'Kept'
assert cloud_settings.status(store.HOME, store.repository().backend)['enabled'] is False
"""
            env = {**os.environ, 'TEXTFOLD_DATA':root, 'USERPROFILE':root, 'HOME':root, 'PYTHONUTF8':'1'}
            result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8','replace'))
