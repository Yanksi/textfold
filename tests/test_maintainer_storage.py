"""Compatibility regressions from the maintainer review; disposable data only."""
import copy, json, tempfile, unittest
from pathlib import Path
from textfold import sync_records
from textfold.documents import Document, Source
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
                initial, initial_conflicts = backend.reconcile(records({}), records({'phone':{'section':'s2'}}), records({'laptop':{'section':'s3'}}))
                self.assertEqual(initial_conflicts, [])
                self.assertEqual(set(history(initial)), {'phone','laptop'})
                first, first_conflicts = backend.reconcile({}, records({'phone':{'section':'s2'}}), records({'laptop':{'section':'s3'}}))
                self.assertEqual(first_conflicts, [])
                self.assertEqual(set(history(first)), {'phone','laptop'})
                deleted, deleted_conflicts = backend.reconcile(base, {}, records({'old':{'section':'s1'},'new':{'section':'s4'}}))
                self.assertEqual(deleted_conflicts, [])
                self.assertEqual(set(history(deleted)), {'new'})
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

    def test_canonical_head_honors_one_sided_append_and_prefers_descendants(self):
        base = {'annotation/n-one':{'id':'n-one','text':'Old','thread_head':'z-old'}}
        local = copy.deepcopy(base); local['annotation/n-one']['thread_head'] = 'a-new'
        remote = copy.deepcopy(base); remote['annotation/n-one']['text'] = 'Remote annotation'
        merged, conflicts = sync_records.reconcile(base,local,remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged['annotation/n-one']['thread_head'], 'a-new')
        self.assertEqual(merged['annotation/n-one']['text'], 'Remote annotation')
        local['annotation/n-one']['thread_head'] = 'z-parent'
        remote['annotation/n-one']['thread_head'] = 'a-child'
        local['message/n-one/z-parent'] = {'id':'z-parent','parent':'z-old','role':'assistant','text':'Parent'}
        remote.update({'message/n-one/z-parent':local['message/n-one/z-parent'],
            'message/n-one/a-child':{'id':'a-child','parent':'z-parent','role':'assistant','text':'Child'}})
        merged, conflicts = sync_records.reconcile(base,local,remote)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged['annotation/n-one']['thread_head'], 'a-child')

    def test_local_layers_catalog_progress_cached_fetch_and_images_are_lazy(self):
        import threading, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        from types import SimpleNamespace
        from unittest import mock
        from textfold import store, storage, library, server, fetch
        with tempfile.TemporaryDirectory() as root:
            backend = storage.LocalDirectoryBackend(root)
            backend.save(Document('2306.03310',meta={'id':'2306.03310','title':'Lazy fixture'},
                source=Source(html='<p>Source</p>'), images={'one.png':b'image-fixture'}))
            with store.use_backend(backend) as repo, mock.patch.object(backend,'get',side_effect=AssertionError('No whole-document read')), \
                 mock.patch.object(repo,'library',side_effect=AssertionError('No catalog snapshot')), \
                 mock.patch.object(repo,'save_library',side_effect=AssertionError('No catalog backend write')):
                store.write('2306.03310','en',{'version':'test'})
                library.change({'op':'new','name':'Reading'})
                job={'kind':'generate','pid':'2306.03310'}
                server.Jobs._progress(SimpleNamespace(),job,threading.Event())('parse',0,1)
                self.assertEqual(job['title'],'Lazy fixture')
                self.assertEqual(fetch.fetch('2306.03310',Path(root)).resolve(), (Path(root)/'papers/2306.03310').resolve())
                httpd=ThreadingHTTPServer(('127.0.0.1',0),server.make_handler(SimpleNamespace()))
                worker=threading.Thread(target=httpd.serve_forever,daemon=True);worker.start()
                try:
                    url='http://127.0.0.1:'+str(httpd.server_port)+'/p/2306.03310/img/'
                    with urllib.request.urlopen(url+'one.png') as response: self.assertEqual(response.read(),b'image-fixture')
                    with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(url+'missing.png')
                    self.assertEqual(error.exception.code,404)
                finally: httpd.shutdown();httpd.server_close();worker.join(5)

    def test_local_parser_paths_honor_readonly_snapshot_and_discard_edits(self):
        from textfold import store, storage
        with tempfile.TemporaryDirectory() as root, store.use_backend(storage.LocalDirectoryBackend(root)) as repo:
            doc = Document('md-readonly',meta={'title':'Original'},source=Source(html='Original source'))
            repo.save(doc)
            original = store.pdir(doc.id)
            with repo.workspace(doc.id,write=False) as folder:
                self.assertNotEqual(folder.resolve(), original.resolve())
                self.assertEqual(store.pdir(doc.id).resolve(), folder.resolve())
                (store.pdir(doc.id)/'source.html').write_text('Discard this edit',encoding='utf-8')
                self.assertFalse(repo.checkpoint(doc.id))
            self.assertEqual((original/'source.html').read_text(encoding='utf-8'),'Original source')
